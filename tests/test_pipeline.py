"""Failure paths and audio behavior; no installed Chrome required for unit tests.
Optional real ffmpeg audio test: set VK_TEST_FFMPEG to a binary path.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import render
try:
    from engine import audio
except render.PipelineError:
    audio = None

class Page:
    _vk_errors = ()
    def evaluate(self, expression, *args):
        if expression == "END": return .1
        if expression == "FPS": return 30
        return True

class Process:
    def __init__(self, status=None):
        self.status = status
        self.stdin = io.BytesIO()
        self.waited = 0
        self.terminated = False
        self.killed = False
    def poll(self): return self.status
    def wait(self, timeout=None):
        self.waited += 1
        if self.status is None: self.status = 0
        return self.status
    def terminate(self): self.terminated = True; self.status = -1
    def kill(self): self.killed = True; self.status = -9

class PipelineTests(unittest.TestCase):
    def test_help_succeeds_with_or_without_project(self):
        for args in (["--help"], ["-h"], ["missing-project", "--help"], ["missing-project", "-h"]):
            with self.subTest(args=args), patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(render.main(args), 0)
                self.assertIn("--doctor", output.getvalue())
                self.assertIn("renders/raw.mp4", output.getvalue())

    def test_atomic_output_preserves_previous_file_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "raw.mp4"
            target.write_bytes(b"previous")
            with self.assertRaisesRegex(RuntimeError, "failed"):
                with render.atomic_output(target) as tmp:
                    tmp.write_bytes(b"partial")
                    raise RuntimeError("failed")
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_encoder_failure_is_fatal_and_preserves_previous_video(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "raw.mp4"
            target.write_bytes(b"previous")
            proc = Process(7)
            def launch(command, **kwargs):
                Path(command[-1]).write_bytes(b"partial")
                kwargs["stderr"].write(b"encoder unavailable")
                return proc
            with patch.object(render, "require_ffmpeg", return_value="ffmpeg"), \
                 patch.object(render, "with_page", side_effect=lambda proj, fn: fn(Page())), \
                 patch.object(render, "shot", return_value=b"frame"), \
                 patch.object(render.subprocess, "Popen", side_effect=launch):
                with self.assertRaisesRegex(render.PipelineError, "encoder unavailable"):
                    render.frames(Path(directory), target)
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertGreaterEqual(proc.waited, 1)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_successful_encoder_replaces_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "raw.mp4"
            target.write_bytes(b"previous")
            def launch(command, **kwargs):
                Path(command[-1]).write_bytes(b"complete")
                return Process(0)
            with patch.object(render, "require_ffmpeg", return_value="ffmpeg"), \
                 patch.object(render, "with_page", side_effect=lambda proj, fn: fn(Page())), \
                 patch.object(render, "shot", return_value=b"frame"), \
                 patch.object(render.subprocess, "Popen", side_effect=launch):
                render.frames(Path(directory), target)
            self.assertEqual(target.read_bytes(), b"complete")

    def test_page_error_aborts_initialization_and_closes_browser(self):
        pg = Mock()
        handlers = {}
        pg.on.side_effect = lambda event, handler: handlers.update({event: handler})
        pg.goto.side_effect = lambda url: (handlers["pageerror"]("bad scene"), None)[1]
        browser = Mock()
        browser.new_page.return_value = pg
        playwright = SimpleNamespace(chromium=SimpleNamespace(launch=Mock(return_value=browser)))
        with patch.dict(os.environ, {"VK_CHROME_EXECUTABLE": ""}):
            with self.assertRaisesRegex(render.PipelineError, "bad scene"):
                render.open_page(playwright, "http://localhost/")
        browser.close.assert_called_once()

    def test_ready_timeout_is_fatal_and_closes_browser(self):
        pg = Mock()
        pg.goto.return_value = None
        pg.evaluate.return_value = {"ready": False, "error": None}
        browser = Mock()
        browser.new_page.return_value = pg
        playwright = SimpleNamespace(chromium=SimpleNamespace(launch=Mock(return_value=browser)))
        with patch.dict(os.environ, {"VK_CHROME_EXECUTABLE": "", "VK_READY_TIMEOUT_MS": "1"}), \
             patch.object(render.time, "monotonic", side_effect=[0, 1]):
            with self.assertRaisesRegex(render.PipelineError, "READY"):
                render.open_page(playwright, "http://localhost/")
        browser.close.assert_called_once()

    def test_stored_film_error_aborts_without_console_event(self):
        pg = Mock()
        pg.goto.return_value = None
        pg.evaluate.return_value = {"ready": False, "error": "Error: texture prepare failed\n at prepare (film.js:2)"}
        browser = Mock()
        browser.new_page.return_value = pg
        playwright = SimpleNamespace(chromium=SimpleNamespace(launch=Mock(return_value=browser)))
        with patch.dict(os.environ, {"VK_CHROME_EXECUTABLE": ""}):
            with self.assertRaisesRegex(render.PipelineError, "texture prepare failed"):
                render.open_page(playwright, "http://localhost/")
        pg.wait_for_timeout.assert_not_called()
        browser.close.assert_called_once()

    def test_determinism_failure_raises(self):
        with patch.object(render, "with_page", side_effect=lambda proj, fn: fn(Page())), \
             patch.object(render, "shot", side_effect=[b"first", b"second"]):
            with self.assertRaisesRegex(render.PipelineError, "NOT deterministic"):
                render.det(Path("."), n=1)

    def test_cli_returns_nonzero_on_determinism_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("index.html", "film.js"): (Path(directory) / name).touch()
            with patch.object(render, "det", side_effect=render.PipelineError("NOT deterministic")):
                self.assertEqual(render.main([directory, "--det"]), 1)

    def test_event_export_failure_preserves_previous_json(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / "audio/events.json"
            target.parent.mkdir(); target.write_text("previous", encoding="utf-8")
            page = Page()
            page.evaluate = Mock(side_effect=RuntimeError("scene failed at 1.2s"))
            with patch.object(render, "with_page", side_effect=lambda proj, fn: fn(page)):
                with self.assertRaisesRegex(render.PipelineError, "scene failed"):
                    render.events(project)
            self.assertEqual(target.read_text(encoding="utf-8"), "previous")

    def test_parallel_failure_reaps_all_children_and_removes_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / "renders/raw.mp4"
            target.parent.mkdir(); target.write_bytes(b"previous")
            procs = [Process(1), Process(None)]
            with patch.object(render, "require_ffmpeg", return_value="ffmpeg"), \
                 patch.object(render, "with_page", return_value=(1, 30)), \
                 patch.object(render.subprocess, "Popen", side_effect=procs), \
                 patch.object(render.subprocess, "run") as concat:
                with self.assertRaisesRegex(render.PipelineError, "分段 1"):
                    render.frames_parallel(project, target, 2)
            concat.assert_not_called()
            self.assertTrue(all(proc.waited for proc in procs))
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_parallel_jobs_are_capped_at_frame_count(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / "renders/raw.mp4"
            launched = []
            def launch(command, **kwargs):
                name = command[-1]
                (project / "renders" / (name + ".mp4")).write_bytes(b"part")
                launched.append(command)
                return Process(0)
            def concat(command, **kwargs): Path(command[-1]).write_bytes(b"joined")
            with patch.object(render, "require_ffmpeg", return_value="ffmpeg"), \
                 patch.object(render, "with_page", return_value=(.1, 30)), \
                 patch.object(render.subprocess, "Popen", side_effect=launch), \
                 patch.object(render.subprocess, "run", side_effect=concat):
                render.frames_parallel(project, target, 99)
            self.assertEqual(len(launched), 3)
            self.assertEqual(target.read_bytes(), b"joined")
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_stills_do_not_require_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(render, "with_page", side_effect=lambda proj, fn: fn(Page())), \
                 patch.object(render, "shot", return_value=b"png"), \
                 patch.object(render, "require_ffmpeg", side_effect=AssertionError("unexpected ffmpeg")):
                render.stills(Path(directory), [0.0])
            self.assertTrue((Path(directory) / "review/s_0000.00.png").is_file())

    def test_cooperative_cancel_is_checked_before_page_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            signal_file = Path(directory) / "cancel"; signal_file.touch()
            page = Mock()
            with patch.dict(os.environ, {"VK_RENDER_CANCEL_FILE": str(signal_file)}):
                with self.assertRaisesRegex(render.PipelineError, "已取消"):
                    render.evaluate(page, "END")
            page.evaluate.assert_not_called()

    def test_doctor_reports_missing_environment_without_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory)
            with patch.object(render, "ENGINE", engine), \
                 patch.object(render, "require_module", side_effect=render.PipelineError("missing dependency")), \
                 patch.object(render, "chrome_location", return_value=None), \
                 patch.object(render, "require_ffmpeg", side_effect=render.PipelineError("missing ffmpeg")), \
                 patch.object(render.subprocess, "run") as external:
                self.assertEqual(render.doctor(), 1)
            external.assert_not_called()
            self.assertEqual(list(engine.iterdir()), [])

    def test_chrome_standard_windows_environment_paths(self):
        scenarios = [
            ({"ProgramFiles": "Q:/Applications"}, "Q:/Applications/Google/Chrome/Application/chrome.exe"),
            ({"ProgramFiles(x86)": "R:/Programs32"}, "R:/Programs32/Google/Chrome/Application/chrome.exe"),
            ({"LocalAppData": "S:/Profiles/me/Local"}, "S:/Profiles/me/Local/Google/Chrome/Application/chrome.exe"),
            ({"pRoGrAmFiLeS": "T:/CaseInsensitive"}, "T:/CaseInsensitive/Google/Chrome/Application/chrome.exe"),
        ]
        for environment, expected in scenarios:
            with self.subTest(environment=environment):
                with patch.dict(os.environ, dict(environment, USERPROFILE="U:/Users/test"), clear=True), \
                     patch.object(render.shutil, "which", return_value=None), \
                     patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path.as_posix() == expected):
                    self.assertEqual(render.chrome_location().as_posix(), expected)

    def test_chrome_falls_back_to_system_drive_and_profile(self):
        scenarios = [
            ({"SystemDrive": "V:", "USERPROFILE": "W:/Users/test"}, "V:/Program Files/Google/Chrome/Application/chrome.exe"),
            ({"SystemDrive": "V:", "USERPROFILE": "W:/Users/test"}, "V:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
            ({"SystemDrive": "V:", "USERPROFILE": "W:/Users/test"}, "W:/Users/test/AppData/Local/Google/Chrome/Application/chrome.exe"),
            ({"SystemRoot": "X:/Windows", "USERPROFILE": "W:/Users/test"}, "X:/Program Files/Google/Chrome/Application/chrome.exe"),
        ]
        for environment, expected in scenarios:
            with self.subTest(expected=expected):
                with patch.dict(os.environ, environment, clear=True), \
                     patch.object(render.shutil, "which", return_value=None), \
                     patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path.as_posix() == expected):
                    self.assertEqual(render.chrome_location().as_posix(), expected)

    def test_doctor_rejects_missing_or_empty_local_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory)
            for name in render.ENGINE_FILES:
                target = engine / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"export {};")
            for name in render.FONT_FILES:
                target = engine / "fonts" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"font" * 300)
            chrome = engine / "chrome.exe"; chrome.write_bytes(b"browser")
            with patch.object(render, "ENGINE", engine), \
                 patch.object(render, "require_module", return_value=SimpleNamespace(__version__="test")), \
                 patch.object(render, "chrome_location", return_value=chrome), \
                 patch.object(render, "require_ffmpeg", return_value="ffmpeg"), \
                 patch.object(render.subprocess, "run", return_value=SimpleNamespace(stdout="ffmpeg test\n")):
                with patch("sys.stdout", new_callable=io.StringIO):
                    self.assertEqual(render.doctor(), 0)
                for name in render.ENGINE_FILES:
                    target = engine / name
                    for empty in (False, True):
                        with self.subTest(module=name, empty=empty):
                            if empty: target.write_bytes(b"")
                            else: target.unlink()
                            with patch("sys.stdout", new_callable=io.StringIO) as output:
                                self.assertEqual(render.doctor(), 1)
                            self.assertIn(name, output.getvalue())
                            target.write_bytes(b"export {};")

    def test_missing_ffmpeg_has_actionable_error(self):
        with patch.object(render.shutil, "which", return_value=None):
            with self.assertRaisesRegex(render.PipelineError, "PATH"):
                render.require_ffmpeg()

@unittest.skipIf(audio is None, "audio dependencies not installed")
class AudioTests(unittest.TestCase):
    def spec(self):
        return {"end": 5, "meta": {"silence": [[3, 3.5]]}, "events": [[1, "hush", {"dur": 1}]]}

    def test_envelope_covers_hush_silence_and_fades(self):
        t = audio.np.array([0, .3, .8, 1.08, 1.5, 2.2, 2.5, 3.3, 3.9, 4.8, 5])
        gain = audio.audio_envelope(self.spec(), t)
        self.assertEqual(gain[0], 0)
        self.assertAlmostEqual(gain[1], .5)
        self.assertEqual(gain[2], 1)
        self.assertTrue(0 < gain[3] < 1)
        self.assertEqual(gain[4], 0)
        self.assertAlmostEqual(gain[5], .5)
        self.assertEqual(gain[6], 1)
        self.assertEqual(gain[7], 0)
        self.assertAlmostEqual(gain[8], (5 - 3.9) / 1.2)
        self.assertTrue(0 < gain[9] < 1)
        self.assertEqual(gain[10], 0)

    def test_filter_applies_envelope_after_mix_and_normalization(self):
        graph = audio.mix_filter(self.spec())
        self.assertLess(graph.index("amix="), graph.index("loudnorm="))
        self.assertLess(graph.index("loudnorm="), graph.index("aeval="))
        self.assertIn("val(0)", graph)
        self.assertIn("val(1)", graph)

    def test_wav_only_does_not_require_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / "audio/events.json"
            target.parent.mkdir()
            target.write_text(json.dumps({"end": .1, "events": [], "meta": {}}), encoding="utf-8")
            with patch.object(audio, "synth", return_value=audio.np.zeros((4800, 2))), \
                 patch.object(audio, "require_ffmpeg", side_effect=AssertionError("unexpected ffmpeg")):
                self.assertEqual(audio.main([directory, "--wav-only"]), 0)
            self.assertTrue((target.parent / "score.wav").is_file())

    def test_failed_audio_mux_preserves_previous_final(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "audio").mkdir(); (project / "renders").mkdir()
            (project / "audio/events.json").write_text(json.dumps({"end": .1, "events": [], "meta": {}}), encoding="utf-8")
            (project / "renders/raw.mp4").write_bytes(b"raw")
            target = project / "renders/final.mp4"; target.write_bytes(b"previous")
            def fail(command, **kwargs):
                Path(command[-1]).write_bytes(b"partial")
                raise subprocess.CalledProcessError(7, command)
            with patch.object(audio, "synth", return_value=audio.np.zeros((4800, 2))), \
                 patch.object(audio, "require_ffmpeg", return_value="ffmpeg"), \
                 patch.object(audio.subprocess, "run", side_effect=fail):
                self.assertEqual(audio.main([directory]), 1)
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertEqual(sorted(path.name for path in target.parent.iterdir()), ["final.mp4", "raw.mp4"])

    def test_real_ffmpeg_final_mix_mutes_external_bgm(self):
        ffmpeg = os.environ.get("VK_TEST_FFMPEG") or shutil.which("ffmpeg")
        if not ffmpeg: self.skipTest("set VK_TEST_FFMPEG for real audio integration test")
        command = [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000",
                   "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                   "-filter_complex", audio.mix_filter(self.spec()), "-map", "[a]", "-t", "5", "-ar", "48000", "-ac", "2", "-f", "s16le", "-"]
        result = subprocess.run(command, check=True, capture_output=True)
        pcm = audio.np.frombuffer(result.stdout, dtype="<i2").reshape(-1, 2)
        def rms(a, b):
            block = pcm[int(a * 48000):int(b * 48000)].astype(float)
            return float(audio.np.sqrt(audio.np.mean(block ** 2)))
        self.assertGreater(rms(.7, .9), 100)
        self.assertLess(rms(1.4, 1.8), 1)
        self.assertGreater(rms(2.6, 2.8), 100)
        self.assertLess(rms(3.2, 3.4), 1)

if __name__ == "__main__":
    unittest.main()

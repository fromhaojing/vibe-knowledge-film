"""Real-browser integration checks. Run after installing requirements and fonts.

    python -m unittest discover -s tests -p test_browser.py -v

No dependency or skill installation is performed by this test.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vk_render_browser", ROOT / "engine/render.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "playwright is required for browser integration")
class BrowserIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        executable = os.environ.get("VK_CHROME_EXECUTABLE")
        options = {"executable_path": executable} if executable else {"channel": "chrome"}
        cls.browser = cls.playwright.chromium.launch(
            **options, args=["--force-color-profile=srgb", "--disable-lcd-text"]
        )
        cls.output = Path(os.environ.get("VK_TEST_OUTPUT", ROOT / "review/browser-tests"))
        cls.output.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def visit(self, project, fn):
        server, url = RENDER.serve(ROOT / project)
        page = self.browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        try:
            page.goto(url)
            page.wait_for_function("window.READY === true || window.FILM_ERROR", timeout=60000)
            self.assertIsNone(page.evaluate("window.FILM_ERROR"))
            self.assertTrue(page.evaluate("window.READY === true"))
            fn(page)
            self.assertEqual(errors, [], "Browser errors: " + json.dumps(errors, ensure_ascii=False))
        finally:
            page.close()
            server.shutdown()
            server.server_close()

    def test_all_examples_render_and_seek_independently(self):
        cases = {
            "fold_C": [3.8, 6.7, 11.2, 18.6, 24.8, 28.2],
            "pigeon_B": [2.5, 7.0, 14.8, 17.0, 23.0, 30.4],
            "info_C": [3.0, 12.0, 25.0, 40.0],
            "stim_B": [2.0, 6.0, 10.0],
            "kit_gallery": [1.0, 6.0, 12.0],
            "three_native": [0.8, 2.3, 4.5, 6.5],
        }
        for name, requested in cases.items():
            with self.subTest(example=name):
                def check(page):
                    self.assertEqual(page.evaluate("RENDERER"), "three-webgl")
                    self.assertTrue(page.evaluate("document.getElementById('stage').getContext('webgl2') !== null"))
                    duration = page.evaluate("END")
                    times = [min(t, duration - 0.001) for t in requested]
                    page.evaluate("(t) => seek(t)", times[0])
                    first = hashlib.sha256(page.screenshot()).hexdigest()
                    for index, t in enumerate(times):
                        page.evaluate("(t) => seek(t)", t)
                        page.screenshot(path=str(self.output / f"{name}-{index}.png"))
                    page.evaluate("(t) => seek(t)", times[0])
                    self.assertEqual(hashlib.sha256(page.screenshot()).hexdigest(), first)
                    events = page.evaluate("events()")
                    self.assertTrue(all(0 <= event[0] <= duration for event in events))
                    self.assertEqual(events, sorted(events, key=lambda event: event[0]))
                self.visit("examples/" + name, check)

    def test_repeated_frames_do_not_accumulate_gpu_resources(self):
        def check(page):
            for _ in range(3):
                page.evaluate("seek(2.3)")
            baseline = page.evaluate("renderInfo().memory")
            for _ in range(15):
                page.evaluate("seek(2.3)")
            final = page.evaluate("renderInfo().memory")
            self.assertLessEqual(final["geometries"], baseline["geometries"] + 1)
            self.assertLessEqual(final["textures"], baseline["textures"] + 1)
        self.visit("examples/three_native", check)


if __name__ == "__main__":
    unittest.main()

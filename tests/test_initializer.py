"""Initializer must preserve existing files and emit valid configured modules."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vk_initializer", ROOT / "scripts/new_film.py")
INITIALIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INITIALIZER)


class InitializerTests(unittest.TestCase):
    def test_existing_index_is_preserved_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text("existing work", encoding="utf-8")
            with self.assertRaises(SystemExit):
                INITIALIZER.main([directory])
            self.assertEqual(index.read_text(encoding="utf-8"), "existing work")
            self.assertFalse((Path(directory) / "film.js").exists())

    def test_configuration_and_title_are_encoded(self):
        with tempfile.TemporaryDirectory() as directory:
            INITIALIZER.main([directory, "--world", "b", "--fps", "24", "--duration", "8.5", "--title", '引号"与换行\n'])
            source = (Path(directory) / "film.js").read_text(encoding="utf-8")
            self.assertIn("end: 8.5", source)
            self.assertIn("fps: 24", source)
            self.assertIn("events: EVENTS", source)
            self.assertIn('引号\\"与换行\\n', source)
            html = (Path(directory) / "index.html").read_text(encoding="utf-8")
            self.assertIn('type="module"', html)
            self.assertNotIn("import \"./ch1.js\"", html)

    def test_invalid_duration_creates_no_project(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "film"
            with self.assertRaises(SystemExit):
                INITIALIZER.main([str(project), "--duration", "nan"])
            self.assertFalse(project.exists())


if __name__ == "__main__":
    unittest.main()

import unittest

from tests.skill_loader import load_script, script_path


class TestSmoke(unittest.TestCase):
    def test_module_loads(self):
        path = script_path("ush-events", "events")
        self.assertTrue(path.is_file(), f"missing script: {path}")
        module = load_script("ush-events", "events")
        self.assertTrue(callable(getattr(module, "main", None)), "events.main is not callable")


if __name__ == "__main__":
    unittest.main()

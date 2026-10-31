"""The launcher list of ush-processes is a copy of the one in ush-inventory (plan 074, M2 K7)."""

import json
import unittest

from tests.skill_loader import REPO_ROOT

INVENTORY_OWN = REPO_ROOT / "skills" / "ush-inventory" / "data" / "windows-own.json"
PROCESSES_LAUNCHERS = REPO_ROOT / "skills" / "ush-processes" / "data" / "launchers.json"

NEW_LAUNCHERS = ("svchost.exe", "dllhost.exe", "cmstp.exe", "control.exe", "wsl.exe",
                 "bash.exe", "presentationhost.exe")


def launchers(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name.lower() for name in data["launchers"]}


class TestLaunchersCopy(unittest.TestCase):
    def test_lists_are_equal(self):
        inventory = launchers(INVENTORY_OWN)
        processes = launchers(PROCESSES_LAUNCHERS)
        self.assertEqual(inventory, processes)
        for name in NEW_LAUNCHERS:
            with self.subTest(name=name):
                self.assertIn(name, inventory)
                self.assertIn(name, processes)


if __name__ == "__main__":
    unittest.main()

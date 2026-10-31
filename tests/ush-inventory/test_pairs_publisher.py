"""Plan 140 milestone M1: install pairs only between programs of the same publisher (K1-K3).

The general interface (``main``, ``FakePowerShell``, summary keys) is described in
``fakes.py``; ``per_user_pair`` is described in ``summary-contract.md`` ("Install pairs").

Assumptions added by these tests beyond the plan text:

- Each element of ``per_user_pair`` is ``{"id": <summary id of the partner>, "name":
  <partner name>}``, as in ``test_review_notes_m3.py``.
- Every fixture also holds a control pair of one publisher, so a run in which pairing
  did not happen at all cannot pass the "not paired" tests.

Every value here is invented; nothing comes from a machine.
"""

import re
import unittest

from tests.skill_loader import REPO_ROOT

from .fakes import FakePowerShell, InventoryTestCase, ok, win32

SKILL_DIR = REPO_ROOT / "skills" / "ush-inventory"

TOOL = "Example Tool"
TOOL_USER = "Example Tool (User)"
EDITOR = "Invented Code Editor"
EDITOR_USER = "Invented Code Editor (User)"

PUBLISHER = "Invented Publisher Ltd"
OTHER_PUBLISHER = "Other Invented Co"
EDITOR_PUBLISHER = "Invented Editor Works"

KEY_TOOL = "win32:hklm64:InventedExampleTool"
KEY_TOOL_USER = "win32:hkcu:InventedExampleToolUser"
KEY_EDITOR = "win32:hklm64:{2A6E1B44-7C3D-4E5F-9A10-0B1C2D3E4F50}_is1"
KEY_EDITOR_USER = "win32:hkcu:{5F4E3D2C-1B0A-4F9E-8D7C-6B5A49382716}_is1"


def key_name(key):
    return key.split(":", 2)[2]


def control_pair():
    """A machine and a user install of one program with one publisher: always a pair."""
    return [
        win32(key_name(KEY_EDITOR), EDITOR, version="2.4.0", publisher=EDITOR_PUBLISHER,
              install_date="20260310"),
        win32(key_name(KEY_EDITOR_USER), EDITOR_USER, version="2.5.0", hive="hkcu",
              publisher=EDITOR_PUBLISHER, install_date="20260311"),
    ]


def tool_rows(machine_publisher, user_publisher):
    return [
        win32(key_name(KEY_TOOL), TOOL, version="3.0.0", publisher=machine_publisher,
              install_date="20260303"),
        win32(key_name(KEY_TOOL_USER), TOOL_USER, version="3.1.0", hive="hkcu",
              publisher=user_publisher, install_date="20260305"),
    ]


class TestPairsPublisher(InventoryTestCase):
    def programs(self, rows):
        fake = FakePowerShell({"win32_programs": ok(rows), "msix_programs": ok([])})
        summary = self.collect(fake)
        programs = self.by_key(summary.get("programs"))
        for key in (KEY_TOOL, KEY_TOOL_USER, KEY_EDITOR, KEY_EDITOR_USER):
            self.assertIn(key, programs, sorted(programs))
        return programs

    def partner(self, programs, key):
        return [{"id": programs[key].get("id"), "name": programs[key].get("name")}]

    def assert_paired(self, programs, key, other):
        self.assertEqual(programs[key].get("per_user_pair"), self.partner(programs, other),
                         programs[key])

    def assert_control_paired(self, programs):
        self.assert_paired(programs, KEY_EDITOR, KEY_EDITOR_USER)
        self.assert_paired(programs, KEY_EDITOR_USER, KEY_EDITOR)

    def test_different_publishers_not_paired(self):
        programs = self.programs(tool_rows(PUBLISHER, OTHER_PUBLISHER) + control_pair())

        for key in (KEY_TOOL, KEY_TOOL_USER):
            with self.subTest(point=f"{key} has no per_user_pair"):
                self.assertNotIn("per_user_pair", programs[key], programs[key])

        with self.subTest(point="the control pair of one publisher is still paired"):
            self.assert_control_paired(programs)

    def test_same_publisher_paired(self):
        spelled_otherwise = "INVENTED publisher LTD "
        programs = self.programs(tool_rows(PUBLISHER, spelled_otherwise) + control_pair())

        with self.subTest(point="the machine copy names the (User) entry only"):
            self.assert_paired(programs, KEY_TOOL, KEY_TOOL_USER)

        with self.subTest(point="the (User) entry names the machine copy only"):
            self.assert_paired(programs, KEY_TOOL_USER, KEY_TOOL)

        with self.subTest(point="the control pair is paired"):
            self.assert_control_paired(programs)

    def test_missing_publisher_not_paired(self):
        for case, missing in (("empty publisher", ""), ("null publisher", None)):
            with self.subTest(point=case):
                programs = self.programs(tool_rows(PUBLISHER, missing) + control_pair())
                for key in (KEY_TOOL, KEY_TOOL_USER):
                    self.assertNotIn("per_user_pair", programs[key], programs[key])
                self.assert_control_paired(programs)

    def test_docs_name_publisher_and_neutral_inf(self):
        """K4: the docs say "same publisher" and the neutral sentence about INF rows."""
        def flat(path):
            return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))

        references = SKILL_DIR / "references"
        for path in sorted(references.glob("*.md")):
            text = flat(path)
            for phrase in ("installed twice", "software and built-in devices"):
                with self.subTest(point=f"{path.name} has no {phrase!r}"):
                    self.assertNotIn(phrase, text)
        script = flat(SKILL_DIR / "scripts" / "inventory.py")
        for phrase in ("software and built-in devices", "software or built-in device"):
            with self.subTest(point=f"inventory.py has no {phrase!r}"):
                self.assertNotIn(phrase, script)
        for name in ("report-format.md", "summary-contract.md"):
            text = flat(references / name)
            for phrase in ("a device without a driver", "same publisher"):
                with self.subTest(point=f"{name} has {phrase!r}"):
                    self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()

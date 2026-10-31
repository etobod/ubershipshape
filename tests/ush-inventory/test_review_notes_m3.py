"""Review notes, plan 107 milestone M3: install pairs and short lists (K6, K7).

The general interface (``main``, ``FakePowerShell``, summary keys) is described in
``fakes.py``, ``fakes_components.py`` and ``fakes_additions.py``.

Assumptions added by these tests beyond the plan text:

- ``per_user_pair`` sits on the program items of the summary ``programs`` list; each
  element is ``{"id": <summary id of the partner>, "name": <partner name>}``.
- The script reads ``skills/ush-inventory/data/per_user_suffixes.json`` through a
  module-level path constant ``PER_USER_SUFFIXES_FILE`` (like ``DEFAULT_OWN_FILE``), read
  at run time, so the tests patch it with ``unittest.mock.patch.object``.
- The ``not_checked`` item about an unusable suffix file has ``per_user`` (as in
  ``per_user_suffixes.json`` or ``per_user_pair``) in its ``what`` or ``reason``.
- ``DRIVERS_MIN`` and ``COMPONENTS_MIN`` are module constants; when absent the tests use
  the plan's value 10 so they fail on assertions, not on ``AttributeError``.

Every value here is invented; nothing comes from a machine.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .fakes import NOW, FakePowerShell, InventoryTestCase, id_number, ok, win32
from .fakes_additions import custom_rule, firewall_result, fw_value, m2_responses
from .fakes_components import ENABLED, driver, feature

BUDGET = 35000
REFERENCES = REPO_ROOT / "skills" / "ush-inventory" / "references"

VSCODE = "Microsoft Visual Studio Code"
VSCODE_USER = "Microsoft Visual Studio Code (User)"
TOOL = "Example Tool"
TOOL_USER = "Example Tool (User)"
VCREDIST_X64 = "Microsoft Visual C++ 2015-2022 Redistributable (x64)"
VCREDIST_X86 = "Microsoft Visual C++ 2015-2022 Redistributable (x86)"

KEY_VSCODE = "win32:hklm64:{EA457B21-F73E-494C-ACAB-524FDE069978}_is1"
KEY_VSCODE_USER = "win32:hkcu:{771FD6B0-FA20-440A-A002-3B3BAC16DC50}_is1"
KEY_TOOL_64 = "win32:hklm64:InventedExampleTool"
KEY_TOOL_32 = "win32:hklm32:InventedExampleTool"
KEY_TOOL_USER = "win32:hkcu:InventedExampleToolUser"
KEY_VC_X64 = "win32:hklm64:{11111111-AAAA-4BBB-8CCC-000000000064}"
KEY_VC_X86 = "win32:hklm32:{11111111-AAAA-4BBB-8CCC-000000000086}"

FILLERS = 12

DRIVERS = 60
COMPONENTS = 40
RULES_OVER_BUDGET = 1000
RULES_IN_BUDGET = 2
DISPLAY_DEVICE_ID = "PCI\\VEN_1BBB&DEV_9999\\INVENTEDDISPLAY"
LAST_PROVIDER = "Zzz Invented Graphics Vendor"


def key_name(key):
    return key.split(":", 2)[2]


def pair_programs():
    """Win32 rows for K6: two pairs, a triple and a look-alike that is no pair."""
    rows = [
        win32(key_name(KEY_VSCODE), VSCODE, version="1.90.0", install_date="20260301"),
        win32(key_name(KEY_VSCODE_USER), VSCODE_USER, version="1.91.0", hive="hkcu",
              install_date="20260302"),
        win32(key_name(KEY_TOOL_64), TOOL, version="3.0.0", install_date="20260303"),
        win32(key_name(KEY_TOOL_32), TOOL, version="3.0.0", hive="hklm32",
              install_date="20260304"),
        win32(key_name(KEY_TOOL_USER), TOOL_USER, version="3.1.0", hive="hkcu",
              install_date="20260305"),
        win32(key_name(KEY_VC_X64), VCREDIST_X64, version="14.40.0", install_date="20260306"),
        win32(key_name(KEY_VC_X86), VCREDIST_X86, version="14.40.0", hive="hklm32",
              install_date="20260307"),
    ]
    # Fillers push the ids past ten, so a2 before a10 is a real ordering.
    rows += [
        win32(f"InventedFillerApp{i:02d}", f"Invented Filler App {i:02d}",
              install_date=f"202602{i + 1:02d}")
        for i in range(FILLERS)
    ]
    return rows


def third_party_drivers(count):
    """``count`` invented ``oem*.inf`` drivers; the last one is a ``Display`` driver whose
    provider sorts after every other provider."""
    rows = [
        driver(f"PCI\\VEN_1AAA&DEV_{i:04X}\\M3DEV{i:02d}", f"oem{i}.inf",
               device_name=f"Invented M3 Device {i:02d}",
               provider="Invented Hardware Vendor", version=f"1.{i}.0.0")
        for i in range(count - 1)
    ]
    rows.append(driver(DISPLAY_DEVICE_ID, f"oem{count - 1}.inf",
                       device_name="Invented Graphics Adapter", device_class="Display",
                       provider=LAST_PROVIDER, version="31.0.15.0"))
    return rows


def enabled_features(count):
    return [feature(f"InventedM3Feature{i:02d}", ENABLED) for i in range(count)]


def firewall_rules(count):
    """``count`` invented rules in the ``local`` store, none of them built in."""
    return firewall_result(local=[
        fw_value(f"{{00000000-0000-0000-0107-{i:012d}}}",
                 custom_rule(f"Invented M3 Server {i:04d}", port=str(10000 + i),
                             app=f"C:\\Invented\\M3 Server {i:04d}\\server.exe"))
        for i in range(count)
    ])


class TestReviewNotesM3(InventoryTestCase):
    def listed(self, data, name):
        value = data.get(name)
        self.assertIsInstance(value, list, f"{name}: {type(value).__name__}")
        return value

    def count(self, summary, name):
        value = summary.get(name)
        self.assertIsInstance(value, int, f"{name}: {value!r}")
        return value

    def programs_by_key(self, summary):
        return self.by_key(self.listed(summary, "programs"))

    def pair_notes(self, summary):
        return [
            item for item in self.not_checked(summary)
            if "per_user" in (str(item.get("what")) + " " + str(item.get("reason"))).lower()
        ]

    def expected_pair(self, programs, *keys):
        partners = []
        for key in keys:
            self.assertIn(key, programs, sorted(programs))
            partners.append({"id": programs[key].get("id"), "name": programs[key].get("name")})
        return sorted(partners, key=lambda p: id_number(p["id"], "a"))

    def collect_pairs(self, suffix_file=None):
        fake = FakePowerShell({"win32_programs": ok(pair_programs()), "msix_programs": ok([])})
        if suffix_file is None:
            return self.collect(fake)
        with mock.patch.object(self.inventory, "PER_USER_SUFFIXES_FILE", suffix_file,
                               create=True):
            return self.collect(fake)

    def test_per_user_pair(self):
        summary = self.collect_pairs()
        programs = self.programs_by_key(summary)

        with self.subTest(point="VS Code machine and user installs pair with each other"):
            self.assertEqual(programs[KEY_VSCODE].get("per_user_pair"),
                             self.expected_pair(programs, KEY_VSCODE_USER), programs[KEY_VSCODE])
            self.assertEqual(programs[KEY_VSCODE_USER].get("per_user_pair"),
                             self.expected_pair(programs, KEY_VSCODE),
                             programs[KEY_VSCODE_USER])

        with self.subTest(point="(User) entry lists both machine copies, sorted by id number"):
            pair = programs[KEY_TOOL_USER].get("per_user_pair")
            self.assertIsInstance(pair, list, programs[KEY_TOOL_USER])
            self.assertEqual(len(pair), 2, pair)
            for element in pair:
                self.assertEqual(set(element), {"id", "name"}, element)
            self.assertEqual(pair, self.expected_pair(programs, KEY_TOOL_64, KEY_TOOL_32))

        with self.subTest(point="each machine copy lists the (User) entry"):
            for key in (KEY_TOOL_64, KEY_TOOL_32):
                self.assertEqual(programs[key].get("per_user_pair"),
                                 self.expected_pair(programs, KEY_TOOL_USER), programs[key])

        with self.subTest(point="x64 and x86 redistributables get no field"):
            for key in (KEY_VC_X64, KEY_VC_X86):
                self.assertIn(key, programs, sorted(programs))
                self.assertNotIn("per_user_pair", programs[key], programs[key])

        with self.subTest(point="a clean run has no not_checked item about the suffix file"):
            self.assertEqual(self.pair_notes(summary), [])

        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        missing = Path(scratch.name).resolve() / "per_user_suffixes.json"
        broken = Path(scratch.name).resolve() / "broken" / "per_user_suffixes.json"
        broken.parent.mkdir()
        broken.write_text('[" (User)"', encoding="utf-8")

        for case, path in (("missing data file", missing), ("invalid JSON", broken)):
            with self.subTest(point=case):
                summary = self.collect_pairs(suffix_file=path)
                notes = self.pair_notes(summary)
                self.assertTrue(notes, self.not_checked(summary))
                for note in notes:
                    self.assertIsInstance(note.get("reason"), str, note)
                    self.assertTrue(note["reason"].strip(), note)
                programs = self.programs_by_key(summary)
                self.assertEqual(len(programs), len(pair_programs()), sorted(programs))
                self.assertEqual(
                    [key for key, item in programs.items() if "per_user_pair" in item], [])

        for name in ("summary-contract.md", "report-format.md"):
            with self.subTest(point=f"{name} names per_user_pair"):
                text = (REFERENCES / name).read_text(encoding="utf-8")
                self.assertIn("per_user_pair", text)

    def run_lists(self, rules):
        responses = m2_responses(
            msix_programs=ok([]),
            drivers=ok(third_party_drivers(DRIVERS)),
            optional_features=ok(enabled_features(COMPONENTS)),
            firewall_rules=ok(firewall_rules(rules)),
        )
        code, stdout, stderr = self.run_main(self.data_dir(), FakePowerShell(responses), now=NOW)
        self.assertEqual(code, 0, stderr[:300])
        return stdout, self.parse(stdout)

    def test_short_lists_keep_minimum(self):
        drivers_min = getattr(self.inventory, "DRIVERS_MIN", 10)
        components_min = getattr(self.inventory, "COMPONENTS_MIN", 10)
        display_key = f"driver:{DISPLAY_DEVICE_ID}"

        stdout, summary = self.run_lists(RULES_OVER_BUDGET)
        with self.subTest(point="the summary keeps the budget"):
            self.assertLessEqual(len(stdout.strip()), BUDGET)

        with self.subTest(point="exactly DRIVERS_MIN drivers, the Display one first"):
            drivers = self.listed(summary, "drivers")
            self.assertEqual(len(drivers), drivers_min, [d.get("key") for d in drivers])
            self.assertEqual(drivers[0].get("key"), display_key, drivers[0])
            self.assertEqual(str(drivers[0].get("class")).lower(), "display", drivers[0])

        with self.subTest(point="exactly COMPONENTS_MIN components"):
            components = self.listed(summary, "components")
            self.assertEqual(len(components), components_min,
                             [c.get("key") for c in components])

        with self.subTest(point="truncated_drivers equals the drivers cut"):
            self.assertEqual(self.count(summary, "truncated_drivers"), DRIVERS - drivers_min)

        with self.subTest(point="truncated_components equals the components cut"):
            self.assertEqual(self.count(summary, "truncated_components"),
                             COMPONENTS - components_min)

        with self.subTest(point="a fixture that fits the budget loses nothing"):
            stdout, summary = self.run_lists(RULES_IN_BUDGET)
            self.assertLessEqual(len(stdout.strip()), BUDGET)
            self.assertEqual(self.count(summary, "truncated_drivers"), 0)
            self.assertEqual(self.count(summary, "truncated_components"), 0)
            self.assertEqual(self.count(summary, "truncated_additions"), 0)
            self.assertEqual(
                {item.get("key") for item in self.listed(summary, "drivers")},
                {f"driver:{row['DeviceID']}" for row in third_party_drivers(DRIVERS)},
            )
            self.assertEqual(
                {item.get("key") for item in self.listed(summary, "components")},
                {f"feature:InventedM3Feature{i:02d}" for i in range(COMPONENTS)},
            )
            self.assertEqual(len(self.listed(summary, "additions")), RULES_IN_BUDGET)


if __name__ == "__main__":
    unittest.main()

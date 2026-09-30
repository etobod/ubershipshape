"""The ush-settings catalogue of settings and its validator.

``TestRealCatalogue`` loads the real ``skills/ush-settings/data/settings-catalogue.json``.
``TestValidator`` writes invented catalogues to a temporary directory; each invalid
catalogue is built from one valid invented base entry with exactly one thing wrong.
Nothing here touches the machine.
"""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import REPO_ROOT, load_script

SKILL = "ush-settings"
REAL_CATALOGUE = REPO_ROOT / "skills" / SKILL / "data" / "settings-catalogue.json"

MAC_RE = re.compile(r"\b[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}\b")
BRACED_GUID_RE = re.compile(
    r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)


def _string_values(data):
    """Every string value in parsed JSON (dict values and list items, recursively)."""
    found = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            found.append(item)
    return found


class TestRealCatalogue(unittest.TestCase):
    def setUp(self):
        self.catalogue = load_script(SKILL, "catalogue")

    def test_loads_clean(self):
        self.assertTrue(REAL_CATALOGUE.is_file(), f"catalogue missing: {REAL_CATALOGUE}")
        entries = self.catalogue.load(str(REAL_CATALOGUE))
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 54)
        ids = [entry["id"] for entry in entries]
        self.assertEqual(len(set(ids)), len(ids), f"duplicate ids: {ids}")

    def test_seed_entries(self):
        # Values of the nine changes made on 2026-09-19 (the seed of the catalogue).
        seed = {
            "input_implicit_text": [1],
            "input_implicit_ink": [1],
            "input_harvest_contacts": [0],
            "inking_typing_personalization": [0],
            "search_bing": [0],
            "search_box_suggestions": [1],
            "wifi_power_management": [24],
            "vss_max_space": None,
        }
        entries = self.catalogue.load(str(REAL_CATALOGUE))
        by_id = {entry["id"]: entry for entry in entries}
        for entry_id, expected in seed.items():
            with self.subTest(entry=entry_id):
                self.assertIn(entry_id, by_id)
                self.assertIn("expected", by_id[entry_id])
                self.assertEqual(by_id[entry_id]["expected"], expected)

    def test_hibernation_falls_back_to_windows_default(self):
        # Without HibernateEnabled, Windows uses HibernateEnabledDefault; reading only the
        # first would leave hibernation unknown and skip fast_startup (applies_if).
        entries = self.catalogue.load(str(REAL_CATALOGUE))
        entry = {item["id"]: item for item in entries}["hibernation_enabled"]
        names = [location["name"] for location in entry["read"]["locations"]]
        self.assertEqual(names, ["HibernateEnabled", "HibernateEnabledDefault"])

    def test_no_machine_identifiers(self):
        raw = REAL_CATALOGUE.read_text(encoding="utf-8")
        with self.subTest(text="raw"):
            self.assertNotIn("s-1-5-21", raw.lower())
            # In JSON text a backslash is escaped: \Users\ is written as \\Users\\.
            self.assertNotIn("\\\\users\\\\", raw.lower())
            self.assertIsNone(MAC_RE.search(raw), "MAC address in the raw catalogue")
            self.assertIsNone(BRACED_GUID_RE.search(raw), "braced GUID in the raw catalogue")
        data = json.loads(raw)
        strings = _string_values(data)
        self.assertTrue(strings, "no string values parsed from the catalogue")
        for value in strings:
            with self.subTest(value=value):
                self.assertNotIn("s-1-5-21", value.lower())
                self.assertNotIn("\\users\\", value.lower())
                self.assertIsNone(MAC_RE.search(value))
                self.assertIsNone(BRACED_GUID_RE.search(value))


def _base_entry(entry_id="invented_base"):
    """A valid invented registry entry; every invalid case changes one thing."""
    return {
        "id": entry_id,
        "area": "privacy",
        "level": "standard",
        "title": "Invented toggle",
        "rationale": "Turns off an invented feature; costs nothing.",
        "read": {
            "type": "registry",
            "locations": [
                {
                    "hive": "HKCU",
                    "path": "Software\\InventedVendor\\InventedProduct",
                    "name": "InventedToggle",
                    "role": "preference",
                },
            ],
        },
        "expected": [0],
        "default": 1,
        "apply": {"location": 0, "value": 0, "kind": "DWord"},
    }


def _unknown_level():
    entry = _base_entry("bad_level")
    entry["level"] = "extreme"
    return entry


def _orphan_condition():
    entry = _base_entry("orphan_condition")
    entry["applies_if"] = {"entry": "ghost_entry", "in": [1]}
    return entry


def _case_duplicate_id():
    return "dup_entry", [_base_entry(), _base_entry("dup_entry"), _base_entry("dup_entry")]


def _case_unknown_level():
    return "bad_level", [_base_entry(), _unknown_level()]


def _case_unknown_read_type():
    entry = _base_entry("bad_read_type")
    entry["read"] = {"type": "crystal_ball"}
    entry["expected"] = None
    entry["apply"] = None
    del entry["default"]
    return "bad_read_type", [_base_entry(), entry]


def _case_location_out_of_range():
    entry = _base_entry("bad_location")
    entry["apply"] = {"location": 1, "value": 0, "kind": "DWord"}
    return "bad_location", [_base_entry(), entry]


def _case_apply_null_without_manual():
    entry = _base_entry("no_manual")
    entry["apply"] = None
    return "no_manual", [_base_entry(), entry]


def _case_appx_without_rollback_manual():
    entry = _base_entry("appx_no_rollback")
    entry["read"] = {"type": "appx", "name": "Invented.SampleApp"}
    entry["expected"] = ["absent"]
    entry["apply"] = {"remove": True}
    del entry["default"]
    return "appx_no_rollback", [_base_entry(), entry]


def _case_applies_if_missing_entry():
    return "orphan_condition", [_base_entry(), _orphan_condition()]


def _case_apply_on_hkcu_policies():
    entry = _base_entry("hkcu_policy_apply")
    entry["read"]["locations"] = [
        {"hive": "HKCU", "path": "Software\\Policies\\X", "name": "InventedValue",
         "role": "policy"},
    ]
    entry["apply"] = {"location": 0, "value": 0, "kind": "DWord"}
    return "hkcu_policy_apply", [_base_entry(), entry]


def _case_apply_on_shadow_storage():
    entry = _base_entry("shadow_apply")
    entry["area"] = "storage"
    entry["read"] = {"type": "shadow_storage"}
    entry["expected"] = None
    entry["apply"] = {"value": 0}
    del entry["default"]
    return "shadow_apply", [_base_entry(), entry]


CASES = {
    "duplicate id": _case_duplicate_id,
    "unknown level": _case_unknown_level,
    "unknown read type": _case_unknown_read_type,
    "apply location out of range": _case_location_out_of_range,
    "apply null without manual": _case_apply_null_without_manual,
    "appx without rollback_manual": _case_appx_without_rollback_manual,
    "applies_if to a missing entry": _case_applies_if_missing_entry,
    "apply on HKCU Software\\Policies": _case_apply_on_hkcu_policies,
    "apply with shadow_storage": _case_apply_on_shadow_storage,
}


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.catalogue = load_script(SKILL, "catalogue")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).absolute()

    def _write(self, name, entries):
        path = self.root / f"{name}.json"
        data = {"schema_version": 1, "entries": copy.deepcopy(entries)}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(path)

    def test_each_error_named(self):
        with self.subTest(case="control: the valid base loads"):
            entries = self.catalogue.load(self._write("control", [_base_entry()]))
            self.assertEqual([entry["id"] for entry in entries], ["invented_base"])

        for number, (case, build) in enumerate(CASES.items()):
            with self.subTest(case=case):
                entry_id, entries = build()
                path = self._write(f"case{number}", entries)
                with self.assertRaises(self.catalogue.CatalogueError) as caught:
                    self.catalogue.load(path)
                self.assertIn(entry_id, str(caught.exception))

        with self.subTest(case="two errors, both named"):
            path = self._write("two", [_base_entry(), _unknown_level(), _orphan_condition()])
            with self.assertRaises(self.catalogue.CatalogueError) as caught:
                self.catalogue.load(path)
            message = str(caught.exception)
            self.assertIn("bad_level", message)
            self.assertIn("orphan_condition", message)

    def _assert_rejected(self, name, entries, *names):
        path = self._write(name, entries)
        with self.assertRaises(self.catalogue.CatalogueError) as caught:
            self.catalogue.load(path)
        for text in names:
            self.assertIn(text, str(caught.exception))

    def test_unhashable_values_are_catalogue_errors(self):
        # JSON lists and objects where a text is expected must be reported, not crash.
        cases = {
            "area list": ("area", ["privacy"]),
            "level object": ("level", {"x": 1}),
            "id list": ("id", ["x"]),
        }
        for number, (case, (key, value)) in enumerate(cases.items()):
            with self.subTest(case=case):
                entry = _base_entry("odd_value")
                entry[key] = value
                self._assert_rejected(f"odd{number}", [_base_entry(), entry], "odd_value"
                                      if key != "id" else "entry #1")

        with self.subTest(case="read.type list"):
            entry = _base_entry("odd_read")
            entry["read"]["type"] = ["registry"]
            self._assert_rejected("odd_read", [_base_entry(), entry], "odd_read")

        with self.subTest(case="hive and role lists"):
            entry = _base_entry("odd_location")
            entry["read"]["locations"][0]["hive"] = ["HKCU"]
            entry["read"]["locations"][0]["role"] = ["policy"]
            self._assert_rejected("odd_location", [_base_entry(), entry], "odd_location")

        with self.subTest(case="service start_type list"):
            entry = _base_entry("odd_service")
            entry["read"] = {"type": "service", "name": "InventedSvc"}
            entry["expected"] = ["Disabled"]
            entry["apply"] = {"start_type": ["Disabled"]}
            del entry["default"]
            self._assert_rejected("odd_service", [_base_entry(), entry], "odd_service")

        with self.subTest(case="applies_if.entry list"):
            entry = _base_entry("odd_condition")
            entry["applies_if"] = {"entry": ["invented_base"], "in": [1]}
            self._assert_rejected("odd_condition", [_base_entry(), entry], "odd_condition")

    def test_id_with_trailing_newline_rejected(self):
        self._assert_rejected("newline_id", [_base_entry(), _base_entry("newline_id\n")],
                              "id must match")

    def test_apply_on_hkcu_current_version_policies(self):
        entry = _base_entry("hkcu_cv_policy")
        entry["read"]["locations"] = [
            {"hive": "HKCU",
             "path": "Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer",
             "name": "InventedValue", "role": "policy"},
        ]
        self._assert_rejected("hkcu_cv_policy", [_base_entry(), entry], "hkcu_cv_policy")

    def test_applies_if_cycle_rejected(self):
        first = _base_entry("cycle_a")
        first["applies_if"] = {"entry": "cycle_b", "in": [1]}
        second = _base_entry("cycle_b")
        second["applies_if"] = {"entry": "cycle_a", "in": [1]}
        self._assert_rejected("cycle", [_base_entry(), first, second], "cycle")

    def test_applies_if_chain_without_cycle_loads(self):
        # Clean data: a chain a -> b -> base is not a cycle and must load.
        first = _base_entry("chain_a")
        first["applies_if"] = {"entry": "chain_b", "in": [1]}
        second = _base_entry("chain_b")
        second["applies_if"] = {"entry": "invented_base", "in": [1]}
        entries = self.catalogue.load(self._write("chain", [_base_entry(), first, second]))
        self.assertEqual(len(entries), 3)


if __name__ == "__main__":
    unittest.main()

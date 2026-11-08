"""The user's decisions file: skills/ush-common/scripts/decisions.py (plan 030, M1).

Public interface under test (from the plan):
- ``FILE_NAME = "decisions.json"``.
- ``load(data_dir, catalogue_ids=None) -> {status, reason, path, decisions}``; ``status`` is
  ``none`` (no file), ``read`` or ``unreadable``; ``reason`` is None or a text naming the
  problem; ``path`` is the absolute path of ``<data_dir>/decisions.json`` as a string;
  ``decisions`` is empty unless ``read``. It never raises on a bad file.
- File shape: ``{"schema_version": 1, "decisions": [{"id", "made", "text", "source",
  "checks"}]}``; a check is ``{"kind": "setting", "skill": "ush-settings", "item",
  "expected"}`` or ``{"kind": "vendor_absent", "match": "publisher"|"provider"|"folder",
  "name"}``.
- With ``catalogue_ids`` a ``setting`` check naming an item not among them makes the file
  unreadable; two decisions with ``setting`` checks on one item make it unreadable too.

Every decision here is invented and lives in a temporary directory.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

CATALOGUE_IDS = ["invented_privacy_toggle", "invented_telemetry_level"]


def setting_check(item, expected):
    return {"kind": "setting", "skill": "ush-settings", "item": item, "expected": expected}


def decision(decision_id, checks, text="Invented decision text."):
    return {"id": decision_id, "made": "2026-01-02", "text": text,
            "source": "invented repair plan", "checks": checks}


def decisions_file(*decisions):
    return {"schema_version": 1, "decisions": list(decisions)}


class TestDecisions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.decisions = load_script("ush-common", "decisions")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def write(self, data_dir, data):
        path = data_dir / "decisions.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load(self, data_dir, catalogue_ids=CATALOGUE_IDS):
        result = self.decisions.load(data_dir, catalogue_ids=catalogue_ids)
        self.assertIsInstance(result, dict, result)
        return result

    def assert_unreadable(self, result, path, named):
        self.assertEqual(result.get("status"), "unreadable", result)
        self.assertEqual(result.get("decisions"), [], result)
        self.assertEqual(result.get("path"), str(path), result)
        reason = result.get("reason")
        self.assertIsInstance(reason, str, result)
        self.assertIn(named, reason, result)

    def test_load_states(self):
        self.assertEqual(self.decisions.FILE_NAME, "decisions.json")

        with self.subTest(case="missing file"):
            data_dir = self.data_dir()
            result = self.load(data_dir)
            self.assertEqual(result.get("status"), "none", result)
            self.assertEqual(result.get("decisions"), [], result)
            self.assertIsNone(result.get("reason"), result)
            path = result.get("path")
            self.assertEqual(path, str(data_dir / "decisions.json"), result)
            self.assertTrue(Path(path).is_absolute(), path)

        with self.subTest(case="valid file"):
            data_dir = self.data_dir()
            path = self.write(data_dir, decisions_file(
                decision("D1", [setting_check("invented_privacy_toggle", 0),
                                setting_check("invented_telemetry_level", [0, 1])],
                         text="Invented privacy settings stay as set."),
                decision("D2", [{"kind": "vendor_absent", "match": "publisher",
                                 "name": "Invented Vendor Ltd."},
                                {"kind": "vendor_absent", "match": "folder",
                                 "name": "InventedVendorTools"}],
                         text="No Invented Vendor software on this machine."),
            ))
            result = self.load(data_dir)
            self.assertEqual(result.get("status"), "read", result)
            self.assertIsNone(result.get("reason"), result)
            self.assertEqual(result.get("path"), str(path), result)
            found = result.get("decisions")
            self.assertIsInstance(found, list, result)
            self.assertEqual([d.get("id") for d in found], ["D1", "D2"], result)

        with self.subTest(case="check of an unknown kind"):
            data_dir = self.data_dir()
            path = self.write(data_dir, decisions_file(
                decision("D1", [setting_check("invented_privacy_toggle", 0)]),
                decision("D2", [{"kind": "invented_unknown_kind",
                                 "name": "Invented Vendor Ltd."}]),
            ))
            self.assert_unreadable(self.load(data_dir), path, "invented_unknown_kind")

        with self.subTest(case="unknown catalogue item id"):
            data_dir = self.data_dir()
            path = self.write(data_dir, decisions_file(
                decision("D1", [setting_check("invented_privacy_toggle", 0),
                                setting_check("invented_missing_item", 1)]),
            ))
            self.assert_unreadable(self.load(data_dir), path, "invented_missing_item")

        with self.subTest(case="two decisions for one item"):
            data_dir = self.data_dir()
            path = self.write(data_dir, decisions_file(
                decision("D1", [setting_check("invented_telemetry_level", 0)]),
                decision("D2", [setting_check("invented_telemetry_level", 1)]),
            ))
            self.assert_unreadable(self.load(data_dir), path, "invented_telemetry_level")


    def test_catalogue_expected(self):
        # Review fix (plan 030 M1): with the catalogue's expectations, a decision value of
        # another kind than the catalogue's (a string or a bool where it expects a number)
        # and a decision on an entry with no expectation (an info entry) are bad shapes.
        catalogue = {"invented_privacy_toggle": [1], "invented_telemetry_level": None}
        cases = {
            "clean: a number where the catalogue expects a number": (0, None),
            "a string where the catalogue expects a number": ("0", "invented_privacy_toggle"),
            "a bool where the catalogue expects a number": (False, "invented_privacy_toggle"),
        }
        for case, (value, named) in cases.items():
            with self.subTest(case=case):
                data_dir = self.data_dir()
                path = self.write(data_dir, decisions_file(
                    decision("D1", [setting_check("invented_privacy_toggle", value)])))
                result = self.decisions.load(data_dir, catalogue_expected=catalogue)
                if named is None:
                    self.assertEqual(result.get("status"), "read", result)
                    self.assertIsNone(result.get("reason"), result)
                else:
                    self.assert_unreadable(result, path, named)

        with self.subTest(case="an entry with no expectation in the catalogue"):
            data_dir = self.data_dir()
            path = self.write(data_dir, decisions_file(
                decision("D1", [setting_check("invented_telemetry_level", 0)])))
            result = self.decisions.load(data_dir, catalogue_expected=catalogue)
            self.assert_unreadable(result, path, "invented_telemetry_level")

        with self.subTest(case="an item missing from the catalogue"):
            data_dir = self.data_dir()
            path = self.write(data_dir, decisions_file(
                decision("D1", [setting_check("invented_missing_item", 0)])))
            result = self.decisions.load(data_dir, catalogue_expected=catalogue)
            self.assert_unreadable(result, path, "invented_missing_item")


if __name__ == "__main__":
    unittest.main()

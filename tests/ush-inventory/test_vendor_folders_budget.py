"""The summary list ``vendor_folders`` is cut to the budget (plan 025, final review).

A long list of folders that no rule matches (each repeating the same ``not_judged``
cause) must not push ``additions`` below their minimum: ``vendor_folders`` is cut to
``VENDOR_FOLDERS_MIN`` early and to nothing only right before ``additions`` are cut.
The cut folders are counted in ``truncated_vendor_folders``, never named.

PowerShell never starts; every value is invented.
"""

import json
import unittest
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .fakes import FakePowerShell, InventoryTestCase, ok, win32
from .fakes_vendor_folders import PROGRAM_DATA, VendorFoldersTestCase, folder, listing

LISTS = ("programs", "driver_packages", "drivers", "components", "additions",
         "autostart", "changes", "vendor_folders")
COUNT_KEYS = {"programs": "truncated", "driver_packages": "truncated_driver_packages",
              "drivers": "truncated_drivers", "components": "truncated_components",
              "additions": "truncated_additions", "autostart": "truncated_autostart",
              "changes": "truncated_changes", "vendor_folders": "truncated_vendor_folders"}
NOT_JUDGED = ("the source scheduled_tasks; the target path of 3 autostart entries; "
              "2 program key(s) of win32_programs that are in no baseline")
FOLDERS = 40
ADDITIONS = 20


def folder_items(count):
    """``count`` invented listed vendor folders, all not judged."""
    return [{
        "id": f"v{i}",
        "key": f"vendor_folder:c:\\programdata\\invented vendor {i:03d}",
        "path": f"C:\\ProgramData\\Invented Vendor {i:03d}",
        "root": "%ProgramData%",
        "matched": None,
        "has_entries": True,
        "last_write": "2025-04-05T06:07:08Z",
        "not_judged": NOT_JUDGED,
    } for i in range(count)]


def addition_items(count):
    return [{"id": f"x{i}", "kind": "firewall_rule",
             "name": f"Invented Firewall Rule {i:03d} " + "n" * 80} for i in range(count)]


def summary_of(lists):
    """An invented summary holding ``lists`` (name -> items or None), nothing cut."""
    summary = {"not_checked": [], "autostart_counts": None, "change_counts": None}
    for name in LISTS:
        summary[name] = lists.get(name, [])
        summary[COUNT_KEYS[name]] = 0
    return summary


def cut_state(summary, kept):
    state = json.loads(json.dumps(summary))
    for name, number in kept.items():
        state[name] = summary[name][:number]
        state[COUNT_KEYS[name]] = len(summary[name]) - number
    return state


class TestVendorFoldersCut(InventoryTestCase):
    def size(self, summary):
        return len(self.inventory.dump(summary))

    def fit(self, summary, budget):
        with mock.patch.object(self.inventory, "SUMMARY_MAX_CHARS", budget):
            text = self.inventory.fit_budget(summary)
        self.assertLessEqual(len(text), budget)
        return text

    def folders_min(self):
        return getattr(self.inventory, "VENDOR_FOLDERS_MIN", 10)

    def test_long_folder_list_keeps_additions(self):
        inv = self.inventory
        folders, additions = folder_items(FOLDERS), addition_items(ADDITIONS)
        summary = summary_of({"vendor_folders": folders, "additions": additions})
        keep = self.folders_min()
        self.assertLess(keep, FOLDERS)
        budget = self.size(cut_state(summary, {"vendor_folders": keep})) + 5
        # Folders never cut: additions would have to go below their minimum.
        never_cut = cut_state(summary, {"additions": inv.ADDITIONS_MIN})
        self.assertGreater(self.size(never_cut), budget, "fixture: folders too short")

        self.fit(summary, budget)

        self.assertEqual(summary["additions"], additions)
        self.assertEqual(summary["truncated_additions"], 0)
        self.assertEqual(summary["vendor_folders"], folders[:keep])
        self.assertEqual(summary["truncated_vendor_folders"], FOLDERS - keep)

    def test_additions_to_minimum_before_folders_below_minimum(self):
        # Fits with additions and folders at their minimums, and one addition more
        # does not fit: folders keep VENDOR_FOLDERS_MIN, additions go to ADDITIONS_MIN.
        inv = self.inventory
        folders, additions = folder_items(FOLDERS), addition_items(ADDITIONS)
        summary = summary_of({"vendor_folders": folders, "additions": additions})
        keep = self.folders_min()
        both_min = {"vendor_folders": keep, "additions": inv.ADDITIONS_MIN}
        budget = self.size(cut_state(summary, both_min)) + 5
        one_more = dict(both_min, additions=inv.ADDITIONS_MIN + 1)
        self.assertGreater(self.size(cut_state(summary, one_more)), budget)
        # Emptying the folders alone would make the whole additions list fit.
        self.assertLessEqual(self.size(cut_state(summary, {"vendor_folders": 0})), budget,
                             "fixture: folders too short to tell the orders apart")

        self.fit(summary, budget)

        self.assertEqual(summary["vendor_folders"], folders[:keep])
        self.assertEqual(summary["truncated_vendor_folders"], FOLDERS - keep)
        self.assertEqual(summary["additions"], additions[:inv.ADDITIONS_MIN])
        self.assertEqual(summary["truncated_additions"], ADDITIONS - inv.ADDITIONS_MIN)

    def test_folders_emptied_before_additions_below_minimum(self):
        inv = self.inventory
        folders, additions = folder_items(FOLDERS), addition_items(ADDITIONS)
        summary = summary_of({"vendor_folders": folders, "additions": additions})
        self.assertLess(5, self.folders_min())
        low = self.size(cut_state(summary, {"vendor_folders": 5,
                                            "additions": inv.ADDITIONS_MIN}))
        high = self.size(cut_state(summary, {"vendor_folders": 6,
                                             "additions": inv.ADDITIONS_MIN}))
        budget = (low + high) // 2

        self.fit(summary, budget)

        self.assertEqual(summary["vendor_folders"], folders[:5])
        self.assertEqual(summary["truncated_vendor_folders"], FOLDERS - 5)
        self.assertEqual(summary["additions"], additions[:inv.ADDITIONS_MIN])
        self.assertEqual(summary["truncated_additions"], ADDITIONS - inv.ADDITIONS_MIN)

    def test_fitting_summary_keeps_every_folder(self):
        folders = folder_items(FOLDERS)
        summary = summary_of({"vendor_folders": folders, "additions": addition_items(5)})
        budget = self.size(summary) + 100

        self.fit(summary, budget)

        self.assertEqual(summary["vendor_folders"], folders)
        self.assertEqual(summary["truncated_vendor_folders"], 0)

    def test_null_folders_stay_null(self):
        for case, cut in (("first pass", 10), ("nothing fits", None)):
            with self.subTest(case):
                summary = summary_of({"vendor_folders": None,
                                      "additions": addition_items(ADDITIONS)})
                budget = self.size(summary) - cut if cut else 100
                with mock.patch.object(self.inventory, "SUMMARY_MAX_CHARS", budget):
                    self.inventory.fit_budget(summary)
                self.assertIsNone(summary["vendor_folders"])
                self.assertEqual(summary["truncated_vendor_folders"], 0)

    def test_cut_label_is_folder_name(self):
        label = self.inventory.CUT_LABELS["vendor_folders"]
        self.assertEqual(label({"path": "C:\\ProgramData\\Invented Vendor 007\\"}),
                         "Invented Vendor 007")

    def test_profile_counts_cut_folders(self):
        path = REPO_ROOT / "skills" / "ush-inventory" / "data" / "report-profile.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn({"list": "vendor_folders", "prefix": "v",
                       "count_key": "truncated_vendor_folders"}, profile["truncated"])


class TestVendorFoldersCutRun(VendorFoldersTestCase):
    def test_summary_counts_and_detail_lists_folder_ids(self):
        fake = FakePowerShell({
            "win32_programs": ok_programs(),
            "vendor_folders": listing([folder(PROGRAM_DATA, "Contoso")]),
        })
        summary = self.collect(fake)
        self.assertEqual(summary.get("truncated_vendor_folders"), 0, sorted(summary))
        listed = self.summary_list(summary, "vendor_folders")
        self.assertEqual(len(listed), 1, listed)
        detail = self.detail(summary)
        self.assertEqual(detail["listed"].get("vendor_folders"), [listed[0]["id"]],
                         detail["listed"])


def ok_programs():
    return ok([win32("InventedOther", "Invented Other App", publisher="Invented Ltd",
                     install_location="C:\\Invented\\Other")])


if __name__ == "__main__":
    unittest.main()

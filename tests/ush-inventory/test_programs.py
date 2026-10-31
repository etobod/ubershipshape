"""Programs and the baseline comparison of skills/ush-inventory/scripts/inventory.py
(plan 048, milestone M2).

The interface and the assumptions these tests add are listed in ``fakes.py``.
PowerShell never starts; every baseline lives in a temporary directory; every value
is invented.

Extra assumptions stated here:
- MSIX ``install_date`` is the UTC date (``YYYY-MM-DD``) of ``FolderCreated``, the same
  format as the Win32 ``install_date``.
- "Higher Version" of two packages of one family is compared as numbers per dotted
  part (``1.2.10.0`` is higher than ``1.2.9.0``), as MSIX versions are.
"""

import json
import unittest
from datetime import timedelta
from unittest import mock

from .fakes import (
    NOW,
    SOURCES,
    SYSTEM_DN,
    FakePowerShell,
    InventoryTestCase,
    failure,
    id_number,
    msix,
    ok,
    win32,
)

# The compared sources of plan 048: programs and the autostart sources with items.
SOURCES_048 = SOURCES + ("run_keys", "startup_folders", "scheduled_tasks", "services")

STATE_FILE = "ush-inventory.json"
ELEVATED_STATE_FILE = "ush-inventory.elevated.json"


class TestBaseline(InventoryTestCase):
    def test_first_run_no_comparison(self):
        data_dir = self.data_dir()
        summary = self.collect(FakePowerShell(), data_dir=data_dir)

        self.assertEqual(summary.get("skill"), "ush-inventory")
        self.assertEqual(summary.get("baseline", {}).get("status"), "none", summary.get("baseline"))
        comparison = self.comparison(summary)
        for name in SOURCES:
            self.assertEqual(comparison.get(name), "no_baseline", comparison)
        # Narrowed to the sources of plan 048 (plan 052 M1, "Starsze testy"): a source
        # added later that needs administrator rights is not_read in this run.
        self.assertEqual({comparison.get(name) for name in SOURCES_048}, {"no_baseline"},
                         comparison)
        self.assertEqual(self.changes(summary), [])

        state = data_dir / "state" / STATE_FILE
        self.assertTrue(state.is_file(), f"{state} was not written")
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        self.assertEqual(saved.get("skill"), "ush-inventory")
        self.assertIs(summary["baseline"].get("saved"), True, summary["baseline"])

    def test_second_run_changes(self):
        data_dir = self.data_dir()
        keep = win32("InventedKeep", "Invented App Keep", version="1.0.0")
        gone = win32("InventedGone", "Invented App Gone", version="3.1.0")
        bumped_old = win32("InventedBump", "Invented App Bump", version="1.0.0")
        bumped_new = win32("InventedBump", "Invented App Bump", version="2.0.0")
        new = win32("InventedNew", "Invented App New", version="0.9.0")

        self.collect(FakePowerShell({"win32_programs": ok([keep, gone, bumped_old])}),
                     data_dir=data_dir, now=NOW)
        second_data = {"win32_programs": ok([keep, bumped_new, new])}
        second = self.collect(FakePowerShell(second_data), data_dir=data_dir,
                              now=NOW + timedelta(days=2, hours=12))

        self.assertEqual(second["baseline"].get("status"), "compared", second["baseline"])
        self.assertEqual(second["baseline"].get("age_days"), 2.5, second["baseline"])
        self.assertEqual(self.comparison(second).get("win32_programs"), "compared")

        changes = self.by_key(self.changes(second))
        self.assertEqual(
            set(changes),
            {"win32:hklm64:InventedNew", "win32:hklm64:InventedGone",
             "win32:hklm64:InventedBump"},
            changes,
        )
        added = changes["win32:hklm64:InventedNew"]
        removed = changes["win32:hklm64:InventedGone"]
        changed = changes["win32:hklm64:InventedBump"]
        self.assertEqual(added.get("change"), "added", added)
        self.assertEqual(added.get("name"), "Invented App New", added)
        self.assertNotIn("fields", added)
        self.assertEqual(removed.get("change"), "removed", removed)
        self.assertEqual(removed.get("name"), "Invented App Gone", removed)
        self.assertNotIn("fields", removed)
        self.assertEqual(changed.get("change"), "changed", changed)
        self.assertEqual(changed.get("fields"),
                         {"version": {"before": "1.0.0", "after": "2.0.0"}}, changed)
        for entry in changes.values():
            self.assertEqual(entry.get("source"), "win32_programs", entry)
            id_number(entry.get("id"), "c")
        self.assert_no_own_changes(second)

        third = self.collect(FakePowerShell(second_data), data_dir=data_dir,
                             now=NOW + timedelta(days=3))
        self.assertEqual(third["baseline"].get("status"), "compared", third["baseline"])
        self.assertEqual(third["baseline"].get("age_days"), 0.5, third["baseline"])
        self.assertEqual(self.changes(third), [])
        self.assert_no_own_changes(third)

    def test_unread_source_no_false_changes(self):
        data_dir = self.data_dir()
        app_a = msix("Invented.AppA_0abc1def2ghj3", "Invented.AppA")
        app_b = msix("Invented.AppB_0abc1def2ghj3", "Invented.AppB")
        app_c = msix("Invented.AppC_0abc1def2ghj3", "Invented.AppC")

        self.collect(FakePowerShell({"msix_programs": ok([app_a, app_b])}),
                     data_dir=data_dir, now=NOW)

        second = self.collect(
            FakePowerShell({"msix_programs": failure("Invented AppX query failure")}),
            data_dir=data_dir, now=NOW + timedelta(days=1),
        )
        self.assert_unreadable(second, "msix_programs")
        self.assertEqual(self.comparison(second).get("msix_programs"), "not_read")
        self.assertTrue(self.notes_about_source(second, "msix_programs"),
                        second.get("not_checked"))
        self.assertEqual(
            [c for c in self.changes(second) if c.get("source") == "msix_programs"], []
        )
        self.assertEqual(self.changes(second), [])

        third = self.collect(FakePowerShell({"msix_programs": ok([app_a, app_c])}),
                             data_dir=data_dir, now=NOW + timedelta(days=2))
        self.assertEqual(self.comparison(third).get("msix_programs"), "compared")
        changes = self.by_key(self.changes(third))
        self.assertEqual(set(changes),
                         {"msix:Invented.AppB_0abc1def2ghj3", "msix:Invented.AppC_0abc1def2ghj3"},
                         changes)
        self.assertEqual(changes["msix:Invented.AppB_0abc1def2ghj3"].get("change"), "removed")
        self.assertEqual(changes["msix:Invented.AppC_0abc1def2ghj3"].get("change"), "added")

    def test_elevated_baseline_separate(self):
        data_dir = self.data_dir()
        state = data_dir / "state"

        first = self.collect(FakePowerShell(), data_dir=data_dir, admin=True, now=NOW)
        self.assertIs(first.get("elevated"), True)
        self.assertTrue((state / ELEVATED_STATE_FILE).is_file())
        self.assertFalse((state / STATE_FILE).exists())

        second = self.collect(FakePowerShell(), data_dir=data_dir, admin=True,
                              now=NOW + timedelta(days=1))
        self.assertEqual(second["baseline"].get("status"), "compared", second["baseline"])
        self.assertEqual(second["baseline"].get("age_days"), 1.0, second["baseline"])
        self.assertFalse((state / STATE_FILE).exists())

        plain = self.collect(FakePowerShell(), data_dir=data_dir, admin=False,
                             now=NOW + timedelta(days=2))
        self.assertEqual(plain["baseline"].get("status"), "none", plain["baseline"])
        self.assertTrue((state / STATE_FILE).is_file())

    def test_unreadable_baseline_kept(self):
        with self.subTest("unreadable baseline file"):
            data_dir = self.data_dir()
            state = data_dir / "state"
            state.mkdir(parents=True)
            garbage = b'{"schema_version": 1, "skill": "ush-inventory", not json'
            (state / STATE_FILE).write_bytes(garbage)

            summary = self.collect(FakePowerShell(), data_dir=data_dir)
            baseline = summary.get("baseline")
            self.assertEqual(baseline.get("status"), "unreadable", baseline)
            self.assertIsInstance(baseline.get("reason"), str, baseline)
            self.assertTrue(baseline["reason"].strip(), baseline)
            comparison = self.comparison(summary)
            for name in SOURCES:
                self.assertEqual(comparison.get(name), "no_baseline", comparison)
            self.assertEqual(self.changes(summary), [])
            self.assertTrue(self.notes_about_baseline(summary), summary.get("not_checked"))

            kept = sorted(state.glob("ush-inventory.unreadable-*.json"))
            self.assertEqual(len(kept), 1, sorted(p.name for p in state.iterdir()))
            self.assertEqual(kept[0].read_bytes(), garbage)

        with self.subTest("save fails"):
            data_dir = self.data_dir()
            calls = []

            def failing_save(*args, **kwargs):
                calls.append(args)
                return "invented verification failure: the file read back differs"

            with mock.patch.object(self.inventory.baseline, "save", failing_save):
                summary = self.collect(FakePowerShell(), data_dir=data_dir)
            self.assertTrue(calls, "baseline.save was not called")
            self.assertIs(summary["baseline"].get("saved"), False, summary["baseline"])
            self.assertTrue(self.notes_about_baseline(summary), summary.get("not_checked"))

            files = sorted((data_dir / "work").glob("inventory-*.summary.json"))
            self.assertEqual(len(files), 1, files)
            on_disk = json.loads(files[0].read_text(encoding="utf-8-sig"))
            self.assertIs(on_disk.get("baseline", {}).get("saved"), False, on_disk.get("baseline"))
            self.assertTrue(self.notes_about_baseline(on_disk), on_disk.get("not_checked"))


class TestWin32(InventoryTestCase):
    def test_fields(self):
        rows = [
            win32("InventedDated", "Invented App Dated", install_date="20260915",
                  system_component=1),
            win32("InventedDotted", "Invented App Dotted", install_date="15.09.2026",
                  system_component=0),
            win32("InventedNoDate", "Invented App No Date", install_date=None,
                  system_component=None, hive="hkcu"),
            win32("InventedNoName", None, install_date="20260101"),
        ]
        summary = self.collect(FakePowerShell({"win32_programs": ok(rows),
                                               "msix_programs": ok([])}))
        programs = self.by_key(summary.get("programs"))

        dated = programs.get("win32:hklm64:InventedDated")
        dotted = programs.get("win32:hklm64:InventedDotted")
        no_date = programs.get("win32:hkcu:InventedNoDate")
        for item in (dated, dotted, no_date):
            self.assertIsNotNone(item, sorted(programs))

        self.assertEqual(dated.get("install_date"), "2026-09-15", dated)
        self.assertIn("install_date", dotted)
        self.assertIsNone(dotted["install_date"], dotted)
        self.assertIn("install_date", no_date)
        self.assertIsNone(no_date["install_date"], no_date)

        self.assertIs(dated.get("system_component"), True, dated)
        self.assertIs(dotted.get("system_component"), False, dotted)
        self.assertIs(no_date.get("system_component"), False, no_date)

        self.assertNotIn("win32:hklm64:InventedNoName", programs)
        self.assertEqual(len(programs), 3, sorted(programs))
        detail_keys = {item.get("key") for item in self.detail(summary).get("programs")}
        self.assertNotIn("win32:hklm64:InventedNoName", detail_keys)

    def test_denied_subkey(self):
        """One subkey that cannot be opened is named in not_checked and is not 'removed'."""
        data_dir = self.data_dir()
        locked = win32("InventedLocked", "Invented App Locked")
        other = win32("InventedOther", "Invented App Other")
        denied = {"Hive": "hklm64", "KeyName": "InventedLocked",
                  "Error": "Requested registry access is not allowed."}
        self.collect(FakePowerShell({"win32_programs": ok([locked, other])}),
                     data_dir=data_dir)
        second = self.collect(FakePowerShell({"win32_programs": ok([denied, other])}),
                              data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.source(second, "win32_programs").get("status"), "read")
        self.assertEqual(self.changes(second), [])
        notes = [n for n in self.not_checked(second) if "InventedLocked" in str(n.get("what"))]
        self.assertEqual(len(notes), 1, self.not_checked(second))
        carried = self.by_key(second.get("programs")).get("win32:hklm64:InventedLocked")
        self.assertIsNotNone(carried)
        self.assertIs(carried.get("from_baseline"), True, carried)
        self.assertNotIn("from_baseline",
                         self.by_key(second.get("programs"))["win32:hklm64:InventedOther"])

        with self.subTest("only denied subkeys and no baseline: unreadable, not empty"):
            only_denied = self.collect(FakePowerShell({"win32_programs": ok([denied])}))
            self.assert_unreadable(only_denied, "win32_programs")

        with self.subTest("control: a subkey that is really gone is removed"):
            third = self.collect(FakePowerShell({"win32_programs": ok([other])}),
                                 data_dir=data_dir, now=NOW + timedelta(days=2))
            removed = self.by_key(self.changes(third))
            self.assertEqual(removed.get("win32:hklm64:InventedLocked", {}).get("change"),
                             "removed", removed)


class TestMsix(InventoryTestCase):
    def test_own_counted_not_listed(self):
        system_app = msix("Invented.SystemApp_0abc1def2ghj3", "Invented.SystemApp",
                          kind="System", publisher=SYSTEM_DN)
        store_app = msix("Invented.StoreApp_0abc1def2ghj3", "Invented.StoreApp")
        summary = self.collect(FakePowerShell({"msix_programs": ok([system_app, store_app])}))

        programs = self.by_key(summary.get("programs"))
        self.assertNotIn("msix:Invented.SystemApp_0abc1def2ghj3", programs)
        self.assertIn("msix:Invented.StoreApp_0abc1def2ghj3", programs)
        self.assertEqual(summary.get("own_counts", {}).get("programs"), 1, summary.get("own_counts"))

        last_summary_id = max(id_number(p.get("id"), "a") for p in programs.values())
        detail = self.by_key(self.detail(summary).get("programs"))
        # own is not in the summary item (plan 074, M1): read it from the detail file.
        self.assertIs(detail["msix:Invented.StoreApp_0abc1def2ghj3"].get("own"), False)
        own = detail.get("msix:Invented.SystemApp_0abc1def2ghj3")
        self.assertIsNotNone(own, sorted(detail))
        self.assertIs(own.get("own"), True, own)
        self.assertGreater(id_number(own.get("id"), "a"), last_summary_id, own)

    def test_own_changes_counted(self):
        data_dir = self.data_dir()
        sys_gone = msix("Invented.SysGone_0abc1def2ghj3", "Invented.SysGone",
                        kind="System", publisher=SYSTEM_DN)
        sys_switch = msix("Invented.SysSwitch_0abc1def2ghj3", "Invented.SysSwitch",
                          kind="System", publisher=SYSTEM_DN)
        switched = dict(sys_switch, SignatureKind="Developer")
        store = msix("Invented.StoreKeep_0abc1def2ghj3", "Invented.StoreKeep")

        self.collect(FakePowerShell({"msix_programs": ok([sys_gone, sys_switch, store])}),
                     data_dir=data_dir, now=NOW)
        second = self.collect(FakePowerShell({"msix_programs": ok([switched, store])}),
                              data_dir=data_dir, now=NOW + timedelta(days=1))

        changes = self.by_key(self.changes(second))
        self.assertNotIn("msix:Invented.SysGone_0abc1def2ghj3", changes)
        switch = changes.get("msix:Invented.SysSwitch_0abc1def2ghj3")
        self.assertIsNotNone(switch, changes)
        self.assertEqual(switch.get("change"), "changed", switch)
        self.assertEqual(switch.get("source"), "msix_programs", switch)
        self.assertEqual(switch.get("fields"),
                         {"signature_kind": {"before": "System", "after": "Developer"}}, switch)
        self.assertEqual(
            {k: self.own_changes(second).get(k) for k in ("added", "removed", "changed")},
            {"added": 0, "removed": 1, "changed": 0},
        )

        last_summary_id = max(id_number(c.get("id"), "c") for c in changes.values())
        detail_changes = self.by_key(self.detail(second).get("changes"))
        gone = detail_changes.get("msix:Invented.SysGone_0abc1def2ghj3")
        self.assertIsNotNone(gone, sorted(detail_changes))
        self.assertEqual(gone.get("change"), "removed", gone)
        self.assertGreater(id_number(gone.get("id"), "c"), last_summary_id, gone)

    def test_family_and_folder_date(self):
        family = "Invented.TwoVersions_0abc1def2ghj3"
        rows = [
            msix(family, "Invented.TwoVersions", version="1.2.10.0",
                 folder_created="2026-08-14T09:30:00Z"),
            msix(family, "Invented.TwoVersions", version="1.2.9.0",
                 folder_created="2026-07-01T08:00:00Z"),
            msix("Invented.NoFolder_0abc1def2ghj3", "Invented.NoFolder", folder_created=None),
        ]
        summary = self.collect(FakePowerShell({"msix_programs": ok(rows)}))

        listed = [p for p in summary.get("programs") if p.get("key") == f"msix:{family}"]
        self.assertEqual(len(listed), 1, summary.get("programs"))
        self.assertEqual(listed[0].get("version"), "1.2.10.0", listed[0])
        self.assertEqual(listed[0].get("install_date"), "2026-08-14", listed[0])
        in_detail = [p for p in self.detail(summary).get("programs")
                     if p.get("key") == f"msix:{family}"]
        self.assertEqual(len(in_detail), 1, in_detail)

        no_folder = self.by_key(summary.get("programs")).get("msix:Invented.NoFolder_0abc1def2ghj3")
        self.assertIsNotNone(no_folder)
        self.assertIn("install_date", no_folder)
        self.assertIsNone(no_folder["install_date"], no_folder)


class TestSources(InventoryTestCase):
    def test_each_source_statuses(self):
        single_rows = {
            "win32_programs": (win32("InventedSingle", "Invented App Single"),
                               "win32:hklm64:InventedSingle", "win32:"),
            "msix_programs": (msix("Invented.Single_0abc1def2ghj3", "Invented.Single"),
                              "msix:Invented.Single_0abc1def2ghj3", "msix:"),
        }
        self.assertEqual(set(single_rows), set(SOURCES))
        for name, (row, key, prefix) in single_rows.items():
            with self.subTest(source=name, case="failed job"):
                summary = self.collect(FakePowerShell(
                    {name: failure("Invented access failure 0x80070005")}
                ))
                self.assert_unreadable(summary, name)
                self.assertTrue(self.notes_about_source(summary, name),
                                summary.get("not_checked"))

            with self.subTest(source=name, case="empty result"):
                summary = self.collect(FakePowerShell({name: ok([])}))
                self.assertEqual(self.source(summary, name).get("status"), "empty")
                self.assertEqual(self.notes_about_source(summary, name), [])

            with self.subTest(source=name, case="single object"):
                summary = self.collect(FakePowerShell({name: ok(row)}))
                self.assertEqual(self.source(summary, name).get("status"), "read")
                from_source = [p.get("key") for p in summary.get("programs")
                               if str(p.get("key")).startswith(prefix)]
                self.assertEqual(from_source, [key])


if __name__ == "__main__":
    unittest.main()

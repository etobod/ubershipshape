"""First-seen date and pass count of autostart entries (plan 026, milestone M1, K1-K9).

The general interface (``main(argv, run_ps, is_admin, now)``, ``FakePowerShell``, item
``key``, ``not_checked``) is in ``fakes.py``; the autostart rows are in
``fakes_autostart.py``. PowerShell never starts; every baseline lives in a temporary
directory; every value is invented.

Interface under test (from the plan):

- Each autostart item of a read or ``empty`` source (``run_keys``, ``startup_folders``,
  ``scheduled_tasks``, ``services``) carries ``first_seen`` (UTC date ``YYYY-MM-DD``) and
  ``passes_seen`` (int), in the summary's ``autostart`` items and in the saved baseline
  (``<data dir>/state/ush-inventory.json``, ``.elevated.json`` with administrator rights,
  ``{created_at, sources: {source: {key: item}}}``).
- The date of the run is the injected ``now`` (no clock patch is needed).

Assumptions added by these tests beyond the plan text:

- The ``not_checked`` entry about the unknown age (K7) mentions ``first_seen``,
  ``passes_seen``, "first seen" or the word "age" somewhere in the item.
- A task row with ``Error`` (as in ``test_compare_to.py``) is a single item whose read
  failed inside a read source, kept from the baseline with ``from_baseline``.
"""

import json
import re
import unittest
from datetime import datetime, timedelta, timezone

from .fakes import NOW, FakePowerShell, InventoryTestCase, failure, ok
from .fakes_autostart import (
    CLEAN_SERVICES,
    CLEAN_TASKS,
    VENDOR,
    clean_responses,
    exec_action,
    file_row,
    run_value,
    service,
    task,
)

AUTOSTART_SOURCES = ("run_keys", "startup_folders", "scheduled_tasks", "services")
STATE_FILE = "ush-inventory.json"
ELEVATED_STATE_FILE = "ush-inventory.elevated.json"

DAY1 = NOW
DAY2 = NOW + timedelta(days=3)
DAY3 = NOW + timedelta(days=7)


def day(moment):
    return moment.astimezone(timezone.utc).date().isoformat()


TRAY_TARGET = "C:\\Invented\\Age Tray\\tray.exe"
TRAY_TARGET_NEW = "C:\\Invented\\Age Tray 2\\tray2.exe"
ONCE_TARGET = "C:\\Invented\\Age Once\\once.exe"
NEW_TARGET = "C:\\Invented\\Age New\\new.exe"
TASK_TARGET = "C:\\Invented\\Age Task\\task.exe"
OTHER_TASK_TARGET = "C:\\Invented\\Age Other Task\\other.exe"
SVC_TARGET = "C:\\Invented\\Age Svc\\svc.exe"

TRAY = run_value("InventedAgeTray", f'"{TRAY_TARGET}" --tray')
TRAY_CHANGED = run_value("InventedAgeTray", f'"{TRAY_TARGET_NEW}" --tray')
ONCE = run_value("InventedAgeOnce", ONCE_TARGET, key="RunOnce")
NEW_RUN = run_value("InventedAgeNew", NEW_TARGET)
AGE_TASK = task("InventedAgeTask", [exec_action(TASK_TARGET, "/run")])
OTHER_TASK = task("InventedAgeOtherTask", [exec_action(OTHER_TASK_TARGET)])
AGE_SVC = service("InventedAgeSvc", f'"{SVC_TARGET}"')

TRAY_KEY = "run:hkcu\\Run:InventedAgeTray"
ONCE_KEY = "run:hkcu\\RunOnce:InventedAgeOnce"
NEW_KEY = "run:hkcu\\Run:InventedAgeNew"
TASK_KEY = "task:\\Invented\\InventedAgeTask"
OTHER_TASK_KEY = "task:\\Invented\\InventedAgeOtherTask"
SVC_KEY = "service:InventedAgeSvc"

FILES = [file_row(path, signer=VENDOR)
         for path in (TRAY_TARGET, TRAY_TARGET_NEW, ONCE_TARGET, NEW_TARGET, TASK_TARGET,
                      OTHER_TASK_TARGET, SVC_TARGET)]

AGE_NOTE = re.compile(r"first_seen|passes_seen|first seen|\bage\b", re.IGNORECASE)


def machine(runs=(TRAY, ONCE), tasks=(AGE_TASK, OTHER_TASK), services=(AGE_SVC,),
            run_keys=None, scheduled_tasks=None):
    """An invented machine: the clean own services and tasks plus vendor entries."""
    responses = clean_responses(extra_files=FILES)
    responses["run_keys"] = ok(list(runs)) if run_keys is None else run_keys
    responses["scheduled_tasks"] = (ok(list(CLEAN_TASKS) + list(tasks))
                                    if scheduled_tasks is None else scheduled_tasks)
    responses["services"] = ok(list(CLEAN_SERVICES) + list(services))
    return FakePowerShell(responses)


class TestAutostartAge(InventoryTestCase):
    # --- helpers ------------------------------------------------------------------------

    def summary_items(self, summary):
        items = summary.get("autostart")
        self.assertIsInstance(items, list, summary)
        result = {}
        for item in items:
            self.assertIn("key", item, item)
            result[item["key"]] = item
        return result

    def saved(self, data_dir, admin=False):
        path = data_dir / "state" / (ELEVATED_STATE_FILE if admin else STATE_FILE)
        self.assertTrue(path.is_file(), f"{path} was not written")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))
        return data

    def saved_items(self, data_dir, admin=False):
        sources = self.saved(data_dir, admin).get("sources") or {}
        result = {}
        for name in AUTOSTART_SOURCES:
            for key, item in (sources.get(name) or {}).items():
                result[key] = item
        return result

    def created_day(self, data_dir, admin=False):
        created = self.saved(data_dir, admin).get("created_at")
        self.assertIsInstance(created, str, created)
        return day(datetime.fromisoformat(created.replace("Z", "+00:00")))

    def assert_age(self, item, first_seen, passes_seen):
        self.assertIn("first_seen", item, item)
        self.assertIn("passes_seen", item, item)
        self.assertEqual(item["first_seen"], first_seen, item)
        self.assertEqual(item["passes_seen"], passes_seen, item)

    def assert_ages(self, items, expected):
        for key, (first_seen, passes_seen) in expected.items():
            with self.subTest(key=key):
                self.assertIn(key, items, sorted(items))
                self.assert_age(items[key], first_seen, passes_seen)

    def assert_bound(self, items, keys, value):
        """``first_seen_lower_bound`` is ``value`` for each of ``keys``."""
        for key in keys:
            with self.subTest(bound=key):
                self.assertIn(key, items, sorted(items))
                self.assertIn("first_seen_lower_bound", items[key], items[key])
                self.assertIs(items[key]["first_seen_lower_bound"], value, items[key])

    # --- K1 -----------------------------------------------------------------------------

    def test_first_run_stamps_today(self):
        data_dir = self.data_dir()
        summary = self.collect(machine(), data_dir=data_dir, now=DAY1)

        listed = self.summary_items(summary)
        self.assertTrue({TRAY_KEY, ONCE_KEY, TASK_KEY, SVC_KEY} <= set(listed), sorted(listed))
        for key, item in listed.items():
            with self.subTest(where="summary", key=key):
                self.assert_age(item, day(DAY1), 1)

        saved = self.saved_items(data_dir)
        self.assertTrue({TRAY_KEY, ONCE_KEY, TASK_KEY, OTHER_TASK_KEY, SVC_KEY,
                         "service:InventedWinSvcA", "task:\\Invented\\InventedLogonTask"}
                        <= set(saved), sorted(saved))
        for key, item in saved.items():
            with self.subTest(where="baseline", key=key):
                self.assert_age(item, day(DAY1), 1)

    # --- K2 -----------------------------------------------------------------------------

    def test_second_run_carries_and_counts(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        second = self.collect(machine(runs=(TRAY, ONCE, NEW_RUN)), data_dir=data_dir,
                              now=DAY2)

        expected = {
            TRAY_KEY: (day(DAY1), 2),
            ONCE_KEY: (day(DAY1), 2),
            TASK_KEY: (day(DAY1), 2),
            NEW_KEY: (day(DAY2), 1),
        }
        self.assert_ages(self.summary_items(second), expected)
        self.assert_ages(self.saved_items(data_dir), expected)
        # A date the tool saw itself is not a lower bound.
        self.assert_bound(self.summary_items(second), expected, False)
        self.assert_bound(self.saved_items(data_dir), expected, False)

    # --- K3 -----------------------------------------------------------------------------

    def test_old_baseline_uses_created_at(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)

        # Make the saved baseline look as one written before the plan: no age fields.
        path = data_dir / "state" / STATE_FILE
        saved = self.saved(data_dir)
        for name in AUTOSTART_SOURCES:
            for item in ((saved.get("sources") or {}).get(name) or {}).values():
                item.pop("first_seen", None)
                item.pop("passes_seen", None)
        path.write_text(json.dumps(saved), encoding="utf-8")
        created = self.created_day(data_dir)
        self.assertNotEqual(created, day(DAY2))

        second = self.collect(machine(), data_dir=data_dir, now=DAY2)
        expected = {key: (created, 2) for key in (TRAY_KEY, ONCE_KEY, TASK_KEY, SVC_KEY)}
        self.assert_ages(self.summary_items(second), expected)
        self.assert_ages(self.saved_items(data_dir), expected)
        # The fallback date is marked as a lower bound, and stays so in a later run.
        self.assert_bound(self.summary_items(second), expected, True)
        self.assert_bound(self.saved_items(data_dir), expected, True)
        third = self.collect(machine(), data_dir=data_dir, now=DAY3)
        later = {key: (created, 3) for key in expected}
        self.assert_ages(self.summary_items(third), later)
        self.assert_bound(self.summary_items(third), later, True)
        self.assert_bound(self.saved_items(data_dir), later, True)

    # --- K4 -----------------------------------------------------------------------------

    def test_unread_items_keep_values(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        self.collect(machine(), data_dir=data_dir, now=DAY2)
        before = self.saved_items(data_dir)
        for key in (TRAY_KEY, ONCE_KEY, TASK_KEY, OTHER_TASK_KEY):
            with self.subTest(precondition=key):
                self.assertIn(key, before, sorted(before))
                self.assert_age(before[key], day(DAY1), 2)

        failed_task = {"TaskPath": "\\Invented\\", "TaskName": "InventedAgeTask",
                       "Error": "Invented task access denied"}
        third = self.collect(machine(
            run_keys=failure("Invented registry read failure"),
            scheduled_tasks=ok(list(CLEAN_TASKS) + [failed_task, OTHER_TASK]),
        ), data_dir=data_dir, now=DAY3)
        self.assertEqual(self.source(third, "scheduled_tasks").get("status"), "read")
        self.assert_unreadable(third, "run_keys")

        saved = self.saved_items(data_dir)
        self.assertIn(TASK_KEY, saved, sorted(saved))
        self.assertIs(saved[TASK_KEY].get("from_baseline"), True, saved[TASK_KEY])
        self.assert_ages(saved, {
            TASK_KEY: (day(DAY1), 2),
            OTHER_TASK_KEY: (day(DAY1), 3),
            TRAY_KEY: (day(DAY1), 2),
            ONCE_KEY: (day(DAY1), 2),
        })

        listed = self.summary_items(third)
        self.assert_ages(listed, {OTHER_TASK_KEY: (day(DAY1), 3)})
        if TASK_KEY in listed:
            self.assert_age(listed[TASK_KEY], day(DAY1), 2)

    # --- K7 -----------------------------------------------------------------------------

    def test_unreadable_baseline_gives_null_age(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        (data_dir / "state" / STATE_FILE).write_text("{not json", encoding="utf-8")

        second = self.collect(machine(), data_dir=data_dir, now=DAY2)

        listed = self.summary_items(second)
        self.assertTrue({TRAY_KEY, ONCE_KEY, TASK_KEY, SVC_KEY} <= set(listed), sorted(listed))
        for key, item in listed.items():
            with self.subTest(where="summary", key=key):
                self.assertNotEqual(item.get("first_seen"), day(DAY2), item)
                self.assert_age(item, None, None)

        saved = self.saved_items(data_dir)
        self.assertTrue(saved, "no autostart items in the saved baseline")
        for key, item in saved.items():
            with self.subTest(where="baseline", key=key):
                self.assertNotEqual(item.get("first_seen"), day(DAY2), item)
                self.assert_age(item, None, None)
        self.assert_bound(listed, listed, None)
        self.assert_bound(saved, saved, None)

        notes = [item for item in self.not_checked(second)
                 if AGE_NOTE.search(json.dumps(item))]
        self.assertTrue(notes, f"no not_checked entry about the unknown age: "
                               f"{self.not_checked(second)}")

    # --- K9 -----------------------------------------------------------------------------

    def test_null_values_after_unreadable_baseline(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        (data_dir / "state" / STATE_FILE).write_text("{not json", encoding="utf-8")
        self.collect(machine(), data_dir=data_dir, now=DAY2)

        before = self.saved_items(data_dir)
        self.assertIn(TRAY_KEY, before, sorted(before))
        self.assert_age(before[TRAY_KEY], None, None)
        created = self.created_day(data_dir)
        self.assertNotEqual(created, day(DAY3))

        code, stdout, stderr = self.run_main(data_dir, machine(), now=DAY3)
        self.assertEqual(code, 0, stderr[:300])
        third = self.parse(stdout)

        expected = {key: (created, 2) for key in (TRAY_KEY, ONCE_KEY, TASK_KEY, SVC_KEY)}
        self.assert_ages(self.summary_items(third), expected)
        self.assert_ages(self.saved_items(data_dir), expected)
        self.assert_bound(self.summary_items(third), expected, True)

    # --- K8 -----------------------------------------------------------------------------

    def test_counts_per_privilege_level(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        self.collect(machine(), data_dir=data_dir, now=DAY2)
        self.assertFalse((data_dir / "state" / ELEVATED_STATE_FILE).exists(),
                         "an elevated baseline exists before the elevated run")

        elevated = self.collect(machine(), data_dir=data_dir, admin=True, now=DAY3)

        expected = {key: (day(DAY3), 1) for key in (TRAY_KEY, ONCE_KEY, TASK_KEY, SVC_KEY)}
        self.assert_ages(self.summary_items(elevated), expected)
        self.assert_ages(self.saved_items(data_dir, admin=True), expected)
        # The normal baseline keeps its own count.
        self.assert_ages(self.saved_items(data_dir),
                         {key: (day(DAY1), 2) for key in (TRAY_KEY, TASK_KEY, SVC_KEY)})

    # --- K5 -----------------------------------------------------------------------------

    def test_fields_are_not_compared(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        second = self.collect(machine(), data_dir=data_dir, now=DAY2)

        # The fields really differ between the two runs.
        self.assert_ages(self.summary_items(second), {TRAY_KEY: (day(DAY1), 2)})
        self.assertEqual(self.changes(second), [])
        self.assertEqual(self.detail(second).get("changes") or [], [])
        self.assert_no_own_changes(second)

    # --- K6 -----------------------------------------------------------------------------

    def test_summary_and_changed_command(self):
        data_dir = self.data_dir()
        first = self.collect(machine(), data_dir=data_dir, now=DAY1)
        for key, item in self.summary_items(first).items():
            with self.subTest(run=1, key=key):
                self.assertIn("first_seen", item, item)
                self.assertIn("passes_seen", item, item)

        second = self.collect(machine(runs=(TRAY_CHANGED, ONCE)), data_dir=data_dir,
                              now=DAY2)
        listed = self.summary_items(second)
        for key, item in listed.items():
            with self.subTest(run=2, key=key):
                self.assertIn("first_seen", item, item)
                self.assertIn("passes_seen", item, item)

        changes = self.by_key(self.changes(second))
        self.assertIn(TRAY_KEY, changes, changes)
        tray_change = changes[TRAY_KEY]
        self.assertEqual(tray_change.get("change"), "changed", tray_change)
        self.assertIn("command", tray_change.get("fields") or {}, tray_change)
        for change in changes.values():
            fields = change.get("fields") or {}
            self.assertNotIn("first_seen", fields, change)
            self.assertNotIn("passes_seen", fields, change)

        self.assert_ages(listed, {TRAY_KEY: (day(DAY1), 2)})
        self.assert_ages(self.saved_items(data_dir), {TRAY_KEY: (day(DAY1), 2)})


if __name__ == "__main__":
    unittest.main()

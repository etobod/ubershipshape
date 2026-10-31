"""``--compare-to <N>d`` of ush-inventory: comparison with a dated history copy
(plan 110, M2, K3).

Interface under test (from the plan; the general one is in ``fakes.py``):

- ``--compare-to`` takes ``<N>d`` with N from 1 to 30; another value is a usage error
  (exit code 2, ``parser.error``).
- Every run (with or without the flag) calls ``baseline.archive`` after ``save``, which
  leaves ``<data dir>/state/history/ush-inventory.<YYYY-MM-DD>.json`` dated by the UTC day
  of the saved baseline's ``created_at``.
- With the flag the run compares with ``baseline.load_reference``: the newest history copy
  dated no later than the UTC day of ``now`` minus N days.
- The summary ``baseline`` object carries ``reference`` (``"latest"`` or the flag value,
  e.g. ``"7d"``) and ``reference_file`` (the history file name or ``null``);
  ``created_at`` and ``age_days`` are those of the state compared with.
- No copy old enough: ``status: "none"``, a reason, no changes.
- Latest baseline damaged, reference read: ``status: "compared"``, a reason, and the
  ``not_checked`` entry "the latest baseline could not be read; sources not read in this
  run keep nothing (the file is kept)", never "nothing was compared".
- Reference copy damaged: ``status: "unreadable"``, no changes, and a ``not_checked``
  entry "the reference baseline <file> could not be read, so nothing was compared".

Assumptions added by this test beyond the plan text:

- ``reference_file`` is ``null`` when no history copy was picked (``status: "none"``)
  and names the picked file also when that file could not be read.
- ``baseline.created_at`` is the injected ``now`` of the run that wrote the state
  compared with (as in ``fakes.py``).

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import json
import shutil
import unittest
from datetime import datetime, timedelta

from .fakes import NOW, FakePowerShell, InventoryTestCase, failure, ok, win32
from .fakes_additions import custom_rule, firewall_result, fw_value, m2_responses
from .fakes_autostart import (
    SHARE_PROCESS,
    VENDOR,
    approved,
    exec_action,
    facts,
    file_row,
    run_value,
    service,
    task,
)

RULE_A = fw_value("{00000000-0000-0000-0110-00000000000A}",
                  custom_rule("Invented Compare Rule A", port="23001",
                              app="C:\\Invented\\Compare A\\server.exe"))
RULE_B = fw_value("{00000000-0000-0000-0110-00000000000B}",
                  custom_rule("Invented Compare Rule B", port="23002",
                              app="C:\\Invented\\Compare B\\server.exe"))
KEY_A = f"firewall:local:{RULE_A['name']}"
KEY_B = f"firewall:local:{RULE_B['name']}"

FIRST = NOW - timedelta(days=10)
SECOND = NOW - timedelta(days=2)
THIRD = NOW

BASELINE_FILE = "ush-inventory.json"
FIRST_COPY = f"ush-inventory.{FIRST.date().isoformat()}.json"
SECOND_COPY = f"ush-inventory.{SECOND.date().isoformat()}.json"
THIRD_COPY = f"ush-inventory.{THIRD.date().isoformat()}.json"

LATEST_UNREADABLE = ("the latest baseline could not be read; sources not read in this "
                     "run keep nothing")


def machine(rules):
    return FakePowerShell(m2_responses(firewall_rules=ok(firewall_result(local=rules))))


# Values not read in the third run (plan 110, M2, review fix): each of these changed
# between the first and the second run and is not read in the third one.
DENIED_PROGRAM = "InventedCompareDenied"  # its Uninstall subkey cannot be opened
READ_PROGRAM = "InventedCompareRead"  # read in every run; changes from 1.0.0 to 2.0.0
REGISTRY_SERVICE = "InventedCompareHostSvc"  # its registry values fail
FILE_SERVICE = "InventedCompareFileSvc"  # its target file cannot be checked
FILE_TARGET = "C:\\Invented\\Compare File\\filesvc.exe"
RUN_NAME = "InventedCompareRun"  # StartupApproved is not read
RUN_TARGET = "C:\\Invented\\Compare Run\\run.exe"
HOST_PATH = "C:\\Windows\\system32\\svchost.exe -k InventedCompareGroup -p"
SERVICE_DLL = {1: "C:\\Invented\\Compare Host\\one.dll", 2: "C:\\Invented\\Compare Host\\two.dll"}
UNREAD_KEYS = {f"win32:hklm64:{DENIED_PROGRAM}", f"service:{REGISTRY_SERVICE}",
               f"service:{FILE_SERVICE}", f"run:hkcu\\Run:{RUN_NAME}"}
READ_KEY = f"win32:hklm64:{READ_PROGRAM}"


def unread_machine(run):
    """The invented machine of run 1, 2 or 3 (3: the values above are not read)."""
    version = "1.0.0" if run == 1 else "2.0.0"
    programs = [win32(READ_PROGRAM, "Invented Compare Read", version=version)]
    if run == 3:
        programs.append({"Hive": "hklm64", "KeyName": DENIED_PROGRAM,
                         "Error": "Invented registry access denied"})
    else:
        programs.append(win32(DENIED_PROGRAM, "Invented Compare Denied", version=version))
    dll = SERVICE_DLL[min(run, 2)]
    host = service(REGISTRY_SERVICE, HOST_PATH, type_=SHARE_PROCESS, service_dll=dll)
    if run == 3:
        host["ServiceDll"] = None
        host["Error"] = "Invented registry failure"
        host["ErrorAt"] = "ServiceDll"
    files = [file_row(dll, signer=VENDOR), file_row(RUN_TARGET, signer=VENDOR)]
    if run == 3:
        files.append({"Kind": "file", "Path": FILE_TARGET, "Error": "Invented access denied"})
    else:
        files.append(file_row(FILE_TARGET, signer=VENDOR,
                              status="Valid" if run == 1 else "HashMismatch"))
    responses = {
        "win32_programs": ok(programs),
        "msix_programs": ok([]),
        "run_keys": ok([run_value(RUN_NAME, RUN_TARGET)]),
        "startup_folders": ok([]),
        "startup_approved": (failure("Invented StartupApproved failure") if run == 3
                             else ok([approved(RUN_NAME, 2 if run == 1 else 3)])),
        "scheduled_tasks": ok([]),
        "services": ok([host, service(FILE_SERVICE, FILE_TARGET)]),
        "file_facts": facts(*files),
    }
    return FakePowerShell(responses)


# Items not read in the third run whose latest baseline cannot fill them (plan 110, M2,
# review fix 2): the latest baseline is damaged, or it lacks the item.
MISSING_PROGRAM = "InventedHistoryDenied"  # its Uninstall subkey cannot be opened in run 3
GONE_PROGRAM = "InventedHistoryGone"  # in run 1, not listed in run 2, denied in run 3
MISSING_SERVICE = "InventedHistoryHostSvc"  # its registry values fail in run 3
MISSING_DLL = "C:\\Invented\\History Host\\host.dll"
MISSING_TASK = "InventedHistoryTask"  # its row cannot be read in run 3
MISSING_TASK_KEY = f"task:\\Invented\\{MISSING_TASK}"
TASK_TARGET = "C:\\Invented\\History Task\\task.exe"
HISTORY_READ_PROGRAM = "InventedHistoryRead"  # read in every run; 1.0.0, then 2.0.0
HISTORY_UNREAD_KEYS = {f"win32:hklm64:{MISSING_PROGRAM}", f"win32:hklm64:{GONE_PROGRAM}",
                       f"service:{MISSING_SERVICE}", MISSING_TASK_KEY}
HISTORY_READ_KEY = f"win32:hklm64:{HISTORY_READ_PROGRAM}"


def history_machine(run):
    """The invented machine of run 1, 2 or 3 (3: the items above are not read)."""
    denied = "Invented registry access denied"
    programs = [win32(HISTORY_READ_PROGRAM, "Invented History Read",
                      version="1.0.0" if run == 1 else "2.0.0")]
    if run == 3:
        programs += [{"Hive": "hklm64", "KeyName": MISSING_PROGRAM, "Error": denied},
                     {"Hive": "hklm64", "KeyName": GONE_PROGRAM, "Error": denied}]
    else:
        programs.append(win32(MISSING_PROGRAM, "Invented History Denied"))
    if run == 1:
        programs.append(win32(GONE_PROGRAM, "Invented History Gone"))
    host = service(MISSING_SERVICE, HOST_PATH, type_=SHARE_PROCESS, service_dll=MISSING_DLL)
    files = [file_row(TASK_TARGET, signer=VENDOR)]
    read_task = task("InventedHistoryReadTask", [exec_action(TASK_TARGET)])
    if run == 3:
        host["ServiceDll"] = None
        host["Error"] = "Invented registry failure"
        host["ErrorAt"] = "ServiceDll"
        tasks = [{"TaskPath": "\\Invented\\", "TaskName": MISSING_TASK,
                  "Error": "Invented task access denied"}, read_task]
    else:
        tasks = [task(MISSING_TASK, [exec_action(TASK_TARGET)]), read_task]
        files.append(file_row(MISSING_DLL, signer=VENDOR))
    return FakePowerShell({
        "win32_programs": ok(programs),
        "msix_programs": ok([]),
        "run_keys": ok([]),
        "startup_folders": ok([]),
        "startup_approved": ok([]),
        "scheduled_tasks": ok(tasks),
        "services": ok([host]),
        "file_facts": facts(*files),
    })


class TestCompareTo(InventoryTestCase):
    # --- helpers ------------------------------------------------------------------------

    def run_flagged(self, data_dir, rules, now, extra=()):
        code, stdout, stderr = self.run_main(data_dir, machine(rules), now=now, extra=extra)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def exit_code(self, data_dir, value):
        try:
            code, _, _ = self.run_main(data_dir, machine([RULE_A, RULE_B]), now=THIRD,
                                       extra=["--compare-to", value])
        except SystemExit as exc:
            code = exc.code
        return code

    def copy_of(self, data_dir, name):
        target = data_dir.parent / name
        shutil.copytree(data_dir, target)
        return target

    def baseline_object(self, summary):
        value = summary.get("baseline")
        self.assertIsInstance(value, dict, summary)
        return value

    def change_keys(self, summary):
        return sorted(str(change.get("key")) for change in self.changes(summary))

    def assert_history(self, data_dir, *names):
        history = data_dir / "state" / "history"
        for name in names:
            self.assertTrue((history / name).is_file(),
                            f"{name} missing from {sorted(p.name for p in history.glob('*'))}"
                            if history.is_dir() else f"no history directory in {data_dir}")

    def not_checked_text(self, summary):
        return json.dumps(self.not_checked(summary)).lower()

    # --- K3 -----------------------------------------------------------------------------

    def test_reference_from_history(self):
        data_dir = self.data_dir()

        self.run_flagged(data_dir, [], FIRST)
        self.assert_history(data_dir, FIRST_COPY)
        second = self.run_flagged(data_dir, [RULE_A], SECOND)
        self.assertEqual(self.change_keys(second), [KEY_A])
        self.assert_history(data_dir, FIRST_COPY, SECOND_COPY)

        # Usage errors: exit code 2 for a zero day count and for a value without "d".
        for value in ("0d", "7"):
            with self.subTest(compare_to=value):
                self.assertEqual(self.exit_code(self.copy_of(data_dir, f"bad-{value}"), value),
                                 2)

        # Third run with --compare-to 7d (on a copy): compared with the copy from 10 days
        # ago, so both rules are changes.
        week_dir = self.copy_of(data_dir, "compare-7d")
        week = self.run_flagged(week_dir, [RULE_A, RULE_B], THIRD,
                                extra=["--compare-to", "7d"])
        with self.subTest("--compare-to 7d"):
            self.assertEqual(self.change_keys(week), sorted([KEY_A, KEY_B]))
            info = self.baseline_object(week)
            self.assertEqual(info.get("status"), "compared", info)
            self.assertEqual(info.get("reference"), "7d", info)
            self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
            self.assertEqual(info.get("age_days"), 10.0, info)
            self.assertIsNone(info.get("reason"), info)
            created = datetime.fromisoformat(str(info.get("created_at")).replace("Z", "+00:00"))
            self.assertEqual(created, FIRST, info)
            self.assert_history(week_dir, FIRST_COPY, SECOND_COPY, THIRD_COPY)

        # --compare-to 30d: no copy that old.
        month_dir = self.copy_of(data_dir, "compare-30d")
        month = self.run_flagged(month_dir, [RULE_A, RULE_B], THIRD,
                                 extra=["--compare-to", "30d"])
        with self.subTest("--compare-to 30d"):
            info = self.baseline_object(month)
            self.assertEqual(info.get("status"), "none", info)
            self.assertEqual(info.get("reference"), "30d", info)
            self.assertIsNone(info.get("reference_file"), info)
            self.assertIsInstance(info.get("reason"), str, info)
            self.assertTrue(info["reason"].strip(), info)
            self.assertEqual(self.changes(month), [])
            self.assert_history(month_dir, THIRD_COPY)

        # Damaged latest baseline, reference read: compared with the reference.
        broken_latest_dir = self.copy_of(data_dir, "broken-latest")
        (broken_latest_dir / "state" / BASELINE_FILE).write_text("{not json",
                                                                 encoding="utf-8")
        broken_latest = self.run_flagged(broken_latest_dir, [RULE_A, RULE_B], THIRD,
                                         extra=["--compare-to", "7d"])
        with self.subTest("damaged latest baseline"):
            info = self.baseline_object(broken_latest)
            self.assertEqual(info.get("status"), "compared", info)
            self.assertEqual(info.get("reference"), "7d", info)
            self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
            self.assertEqual(info.get("age_days"), 10.0, info)
            self.assertIsInstance(info.get("reason"), str, info)
            self.assertTrue(info["reason"].strip(), info)
            self.assertEqual(self.change_keys(broken_latest), sorted([KEY_A, KEY_B]))
            text = self.not_checked_text(broken_latest)
            self.assertIn(LATEST_UNREADABLE, text)
            self.assertNotIn("nothing was compared", text)
            self.assert_history(broken_latest_dir, THIRD_COPY)

        # Damaged history copy from 10 days ago: unreadable, no fallback, no changes.
        broken_copy_dir = self.copy_of(data_dir, "broken-history")
        (broken_copy_dir / "state" / "history" / FIRST_COPY).write_text(
            "{not json", encoding="utf-8")
        broken_copy = self.run_flagged(broken_copy_dir, [RULE_A, RULE_B], THIRD,
                                       extra=["--compare-to", "7d"])
        with self.subTest("damaged history copy"):
            info = self.baseline_object(broken_copy)
            self.assertEqual(info.get("status"), "unreadable", info)
            self.assertEqual(info.get("reference"), "7d", info)
            self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
            self.assertIsInstance(info.get("reason"), str, info)
            self.assertTrue(info["reason"].strip(), info)
            self.assertEqual(self.changes(broken_copy), [])
            matching = [item for item in self.not_checked(broken_copy)
                        if "the reference baseline" in json.dumps(item).lower()]
            self.assertTrue(matching, self.not_checked(broken_copy))
            self.assertTrue(any(FIRST_COPY in json.dumps(item) for item in matching),
                            matching)
            self.assert_history(broken_copy_dir, THIRD_COPY)

        # Third run without the flag on the original: compared with the latest run.
        latest = self.run_flagged(data_dir, [RULE_A, RULE_B], THIRD)
        with self.subTest("no flag"):
            self.assertEqual(self.change_keys(latest), [KEY_B])
            info = self.baseline_object(latest)
            self.assertEqual(info.get("status"), "compared", info)
            self.assertEqual(info.get("reference"), "latest", info)
            self.assertIsNone(info.get("reference_file"), info)
            self.assertEqual(info.get("age_days"), 2.0, info)
            self.assert_history(data_dir, FIRST_COPY, SECOND_COPY, THIRD_COPY)

    def test_unread_values_are_no_change_against_history(self):
        """A value the third run could not read is taken from the latest baseline; with
        --compare-to it is no change against the history copy, while a value read is."""
        data_dir = self.data_dir()

        def run(directory, number, now, extra=()):
            code, stdout, stderr = self.run_main(directory, unread_machine(number), now=now,
                                                 extra=extra)
            self.assertEqual(code, 0, stderr[:300])
            summary = self.parse(stdout)
            self.assertIsInstance(summary, dict, stdout[:300])
            return summary

        def all_change_keys(summary):
            return {str(change.get("key")) for change in self.detail(summary)["changes"]}

        run(data_dir, 1, FIRST)
        second = run(data_dir, 2, SECOND)
        # The fixture really changes every one of them between the first two runs.
        self.assertEqual(all_change_keys(second), UNREAD_KEYS | {READ_KEY})

        week_dir = self.copy_of(data_dir, "compare-7d-unread")
        week = run(week_dir, 3, THIRD, extra=["--compare-to", "7d"])
        with self.subTest("--compare-to 7d"):
            info = self.baseline_object(week)
            self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
            for source in ("win32_programs", "run_keys", "services"):
                self.assertEqual(self.comparison(week).get(source), "compared", source)
            self.assertEqual(all_change_keys(week), {READ_KEY})
            # The saved baseline keeps the values taken from the latest one.
            saved = json.loads((week_dir / "state" / BASELINE_FILE).read_text(
                encoding="utf-8-sig"))["sources"]
            denied = saved["win32_programs"][f"win32:hklm64:{DENIED_PROGRAM}"]
            self.assertEqual(denied.get("version"), "2.0.0", denied)
            self.assertIs(denied.get("from_baseline"), True, denied)
            host = saved["services"][f"service:{REGISTRY_SERVICE}"]
            self.assertEqual(host.get("targets"), [SERVICE_DLL[2]], host)
            entry = saved["run_keys"][f"run:hkcu\\Run:{RUN_NAME}"]
            self.assertEqual(entry.get("approved"), "disabled", entry)
            file_service = saved["services"][f"service:{FILE_SERVICE}"]
            self.assertEqual([f.get("signature_status") for f in file_service["facts"]],
                             ["HashMismatch"], file_service)

        # Without the flag: compared with the latest baseline, nothing changed.
        latest = run(data_dir, 3, THIRD)
        with self.subTest("no flag"):
            self.assertEqual(all_change_keys(latest), set())

    def test_unread_items_missing_from_latest_are_not_removed(self):
        """An item seen in the third run but not read, which the latest baseline cannot
        fill (damaged, or without the item), is neither removed nor changed against the
        history copy with --compare-to; a value read is still a change."""
        data_dir = self.data_dir()

        def run(directory, number, now, extra=()):
            code, stdout, stderr = self.run_main(directory, history_machine(number),
                                                 now=now, extra=extra)
            self.assertEqual(code, 0, stderr[:300])
            summary = self.parse(stdout)
            self.assertIsInstance(summary, dict, stdout[:300])
            return summary

        def changes_by_key(summary):
            return {str(change.get("key")): change.get("change")
                    for change in self.detail(summary)["changes"]}

        first = run(data_dir, 1, FIRST)
        self.assertEqual(changes_by_key(first), {})
        second = run(data_dir, 2, SECOND)
        # GONE_PROGRAM is not in the latest baseline; the others are.
        self.assertEqual(changes_by_key(second),
                         {HISTORY_READ_KEY: "changed", f"win32:hklm64:{GONE_PROGRAM}": "removed"})

        broken_dir = self.copy_of(data_dir, "unread-broken-latest")
        (broken_dir / "state" / BASELINE_FILE).write_text("{not json", encoding="utf-8")
        intact_dir = self.copy_of(data_dir, "unread-intact-latest")
        for label, directory in (("damaged latest baseline", broken_dir),
                                 ("item missing from the latest baseline", intact_dir)):
            summary = run(directory, 3, THIRD, extra=["--compare-to", "7d"])
            with self.subTest(label):
                info = self.baseline_object(summary)
                self.assertEqual(info.get("status"), "compared", info)
                self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
                for source in ("win32_programs", "scheduled_tasks", "services"):
                    self.assertEqual(self.comparison(summary).get(source), "compared",
                                     source)
                found = changes_by_key(summary)
                self.assertEqual(found, {HISTORY_READ_KEY: "changed"})
                self.assertFalse(HISTORY_UNREAD_KEYS & set(found), found)
                # The fallback is in the comparison only: not in the saved baseline.
                saved = json.loads((directory / "state" / BASELINE_FILE).read_text(
                    encoding="utf-8-sig"))["sources"]
                self.assertNotIn(f"win32:hklm64:{GONE_PROGRAM}", saved["win32_programs"])
                if directory is broken_dir:
                    self.assertNotIn(f"win32:hklm64:{MISSING_PROGRAM}",
                                     saved["win32_programs"])
                    self.assertNotIn(MISSING_TASK_KEY, saved["scheduled_tasks"])


if __name__ == "__main__":
    unittest.main()

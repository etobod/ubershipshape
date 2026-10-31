"""``--compare-to <N>d`` of ush-settings: comparison with a dated history copy
(plan 110, M2, K4).

Interface under test (from the plan; the general one is in ``fakes.py``):

- ``--compare-to`` takes ``<N>d`` with N from 1 to 30; another value is a usage error
  (exit code 2, ``parser.error``).
- Every run (with or without the flag) calls ``baseline.archive`` after ``save``, which
  leaves ``<data dir>/state/history/ush-settings.<YYYY-MM-DD>.json`` dated by the UTC day
  of the saved baseline's ``created_at``.
- With the flag the run compares with ``baseline.load_reference``: the newest history copy
  dated no later than the UTC day of ``now`` minus N days. Only ``settings_changes``,
  ``usage_changes`` and ``comparison_state`` get the reference; the saved baseline is
  built from the latest one, so a source not read in this run (``capability_usage``)
  keeps the items of the latest run, not those of the old copy.
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
  compared with.
- The saved baseline keeps its items under ``sources["capability_usage"]`` (shared
  contract: ``{source name: {key: item}}``), and the text of that source names each
  usage item's registry subkey.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import json
import shutil
import unittest
from datetime import datetime, timedelta, timezone

from .fakes import (
    NOW,
    FakePowerShell,
    SettingsTestCase,
    fail,
    loc,
    ok,
    present,
    registry,
    registry_entry,
)

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

ENTRY_X = "invented_compare_x"
ENTRY_Y = "invented_compare_y"
LOC_X = loc("HKCU", "Software\\InventedVendor\\CompareX", "InventedCompareX", "preference")
LOC_Y = loc("HKCU", "Software\\InventedVendor\\CompareY", "InventedCompareY", "preference")

FIRST = NOW - timedelta(days=10)
SECOND = NOW - timedelta(days=2)
THIRD = NOW

BASELINE_FILE = "ush-settings.json"
FIRST_COPY = f"ush-settings.{FIRST.date().isoformat()}.json"
SECOND_COPY = f"ush-settings.{SECOND.date().isoformat()}.json"
THIRD_COPY = f"ush-settings.{THIRD.date().isoformat()}.json"

LATEST_UNREADABLE = ("the latest baseline could not be read; sources not read in this "
                     "run keep nothing")


def filetime(moment):
    """A FILETIME integer (100-ns ticks since 1601-01-01 UTC)."""
    return (moment - FILETIME_EPOCH) // timedelta(microseconds=1) * 10


def usage_row(subkey, moment):
    return {"capability": "webcam", "packaged": True, "subkey": subkey, "value": "Allow",
            "last_used_start": filetime(moment - timedelta(hours=1)),
            "last_used_stop": filetime(moment)}


FIRST_USAGE_SUBKEY = "InventedVendor.FirstCameraApp_invented0"
SECOND_USAGE_SUBKEY = "InventedVendor.SecondCameraApp_invented0"
FIRST_USAGE = usage_row(FIRST_USAGE_SUBKEY, FIRST)
SECOND_USAGE = usage_row(SECOND_USAGE_SUBKEY, SECOND)


def machine(x, y, usage):
    """``usage`` is a list of rows, or None for a failed ``capability_usage`` job."""
    return FakePowerShell({
        "registry_values": registry(present(LOC_X, x), present(LOC_Y, y)),
        "capability_usage": fail("Invented access failure.") if usage is None else ok(usage),
    })


def first_machine():
    return machine(0, 0, [FIRST_USAGE])


def second_machine():
    # ENTRY_X changes; the usage list holds another app.
    return machine(1, 0, [SECOND_USAGE])


def third_machine():
    # ENTRY_Y changes; capability_usage cannot be read.
    return machine(1, 1, None)


class TestCompareTo(SettingsTestCase):
    def setUp(self):
        super().setUp()
        self.write_catalogue([
            registry_entry(ENTRY_X, [LOC_X], expected=[0], default=1),
            registry_entry(ENTRY_Y, [LOC_Y], expected=[0], default=1),
        ])

    # --- helpers ------------------------------------------------------------------------

    def run_flagged(self, data_dir, fake, now, extra=()):
        code, stdout, stderr = self.run_main(data_dir, fake, now=now, extra=extra)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def exit_code(self, data_dir, value):
        try:
            code, _, _ = self.run_main(data_dir, third_machine(), now=THIRD,
                                       extra=["--compare-to", value])
        except SystemExit as exc:
            code = exc.code
        return code

    def copy_of(self, data_dir, name):
        target = self.root / name
        shutil.copytree(data_dir, target)
        return target

    def baseline_object(self, summary):
        value = summary.get("baseline")
        self.assertIsInstance(value, dict, summary)
        return value

    def change_keys(self, summary):
        return sorted(str(change.get("key")) for change in self.changes(summary))

    def usage_changes(self, summary):
        return [change for change in self.changes(summary) if change.get("entry") is None]

    def assert_history(self, data_dir, *names):
        history = data_dir / "state" / "history"
        self.assertTrue(history.is_dir(), f"no history directory in {data_dir}")
        present_names = sorted(p.name for p in history.iterdir())
        for name in names:
            self.assertIn(name, present_names)

    # --- K4 -----------------------------------------------------------------------------

    def test_reference_from_history(self):
        data_dir = self.data_dir()

        self.run_flagged(data_dir, first_machine(), FIRST)
        self.assert_history(data_dir, FIRST_COPY)
        second = self.run_flagged(data_dir, second_machine(), SECOND)
        self.assertIn(ENTRY_X, self.change_keys(second))
        self.assertNotIn(ENTRY_Y, self.change_keys(second))
        self.assert_history(data_dir, FIRST_COPY, SECOND_COPY)

        # Usage errors: exit code 2 for a zero day count and for a value without "d".
        for value in ("0d", "7"):
            with self.subTest(compare_to=value):
                self.assertEqual(self.exit_code(self.copy_of(data_dir, f"bad-{value}"), value),
                                 2)

        # Third run with --compare-to 7d (on a copy): compared with the copy from 10 days
        # ago, so both entries are changes; the unread usage source gives none.
        week_dir = self.copy_of(data_dir, "compare-7d")
        week = self.run_flagged(week_dir, third_machine(), THIRD,
                                extra=["--compare-to", "7d"])
        with self.subTest("--compare-to 7d"):
            self.assertEqual(self.change_keys(week), sorted([ENTRY_X, ENTRY_Y]))
            self.assertEqual(self.usage_changes(week), [])
            info = self.baseline_object(week)
            self.assertEqual(info.get("status"), "compared", info)
            self.assertEqual(info.get("reference"), "7d", info)
            self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
            self.assertEqual(info.get("age_days"), 10.0, info)
            self.assertIsNone(info.get("reason"), info)
            created = datetime.fromisoformat(str(info.get("created_at")).replace("Z", "+00:00"))
            self.assertEqual(created, FIRST, info)
            self.assert_history(week_dir, FIRST_COPY, SECOND_COPY, THIRD_COPY)

            # The saved baseline keeps the usage items of the latest (second) run.
            saved = json.loads((week_dir / "state" / BASELINE_FILE)
                               .read_text(encoding="utf-8-sig"))
            sources = saved.get("sources")
            self.assertIsInstance(sources, dict, sorted(saved))
            self.assertIn("capability_usage", sources, sorted(sources))
            usage_text = json.dumps(sources["capability_usage"])
            self.assertIn(SECOND_USAGE_SUBKEY, usage_text)
            self.assertNotIn(FIRST_USAGE_SUBKEY, usage_text)

        # --compare-to 30d: no copy that old.
        month_dir = self.copy_of(data_dir, "compare-30d")
        month = self.run_flagged(month_dir, third_machine(), THIRD,
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
        broken_latest = self.run_flagged(broken_latest_dir, third_machine(), THIRD,
                                         extra=["--compare-to", "7d"])
        with self.subTest("damaged latest baseline"):
            info = self.baseline_object(broken_latest)
            self.assertEqual(info.get("status"), "compared", info)
            self.assertEqual(info.get("reference"), "7d", info)
            self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
            self.assertEqual(info.get("age_days"), 10.0, info)
            self.assertIsInstance(info.get("reason"), str, info)
            self.assertTrue(info["reason"].strip(), info)
            self.assertEqual(self.change_keys(broken_latest), sorted([ENTRY_X, ENTRY_Y]))
            text = self.not_checked_text(broken_latest)
            self.assertIn(LATEST_UNREADABLE, text)
            self.assertNotIn("nothing was compared", text)
            self.assert_history(broken_latest_dir, THIRD_COPY)

        # Damaged history copy from 10 days ago: unreadable, no fallback, no changes.
        broken_copy_dir = self.copy_of(data_dir, "broken-history")
        (broken_copy_dir / "state" / "history" / FIRST_COPY).write_text(
            "{not json", encoding="utf-8")
        broken_copy = self.run_flagged(broken_copy_dir, third_machine(), THIRD,
                                       extra=["--compare-to", "7d"])
        with self.subTest("damaged history copy"):
            info = self.baseline_object(broken_copy)
            self.assertEqual(info.get("status"), "unreadable", info)
            self.assertEqual(info.get("reference"), "7d", info)
            self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
            self.assertIsInstance(info.get("reason"), str, info)
            self.assertTrue(info["reason"].strip(), info)
            self.assertEqual(self.changes(broken_copy), [])
            matching = [item for item in self.not_checked_items(broken_copy)
                        if "the reference baseline" in json.dumps(item).lower()]
            self.assertTrue(matching, self.not_checked_items(broken_copy))
            self.assertTrue(any(FIRST_COPY in json.dumps(item) for item in matching),
                            matching)
            self.assert_history(broken_copy_dir, THIRD_COPY)

        # Third run without the flag on the original: compared with the latest run.
        latest = self.run_flagged(data_dir, third_machine(), THIRD)
        with self.subTest("no flag"):
            self.assertEqual(self.change_keys(latest), [ENTRY_Y])
            info = self.baseline_object(latest)
            self.assertEqual(info.get("status"), "compared", info)
            self.assertEqual(info.get("reference"), "latest", info)
            self.assertIsNone(info.get("reference_file"), info)
            self.assertEqual(info.get("age_days"), 2.0, info)
            self.assert_history(data_dir, FIRST_COPY, SECOND_COPY, THIRD_COPY)


if __name__ == "__main__":
    unittest.main()

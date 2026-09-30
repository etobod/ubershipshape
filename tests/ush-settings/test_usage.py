"""Camera, microphone and location usage in skills/ush-settings/scripts/settings.py
(plan 050, M3).

Interface under test (see ``fakes.py`` for the full contract):

- Job ``capability_usage``: rows ``{capability, packaged, subkey, value, last_used_start,
  last_used_stop}``; times are FILETIME integers, 0 = null.
- Summary ``usage`` (ids ``u1``...): ``capability, app, packaged, value, last_used_start,
  last_used_stop, in_use``; ``app`` of a NonPackaged subkey has ``#`` replaced by ``\\``.
  Order: in use first, then ``last_used_stop`` descending, null last.
- Baseline source ``capability_usage``: added/removed keys go to ``changes`` with
  ``entry: null`` and ``app``.
- The 35 000-character budget cuts ``usage`` from the end; ``truncated`` counts the cut
  items; the detail file keeps all of them.

Every value is invented (paths, package names, times); PowerShell never starts.
"""

import unittest
from datetime import datetime, timedelta, timezone

from .fakes import (
    NOW,
    FakePowerShell,
    SettingsTestCase,
    fail,
    loc,
    minutes,
    ok,
    present,
    registry,
    registry_entry,
)

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
SUMMARY_MAX_CHARS = 35000

INFO = loc("HKCU", "Software\\InventedVendor\\Usage", "InventedUsageInfo", "preference")


def filetime(moment):
    """A FILETIME integer (100-ns ticks since 1601-01-01 UTC)."""
    return (moment - FILETIME_EPOCH) // timedelta(microseconds=1) * 10


def usage_row(capability, packaged, subkey, value="Allow", start=None, stop=None):
    return {"capability": capability, "packaged": packaged, "subkey": subkey,
            "value": value, "last_used_start": start, "last_used_stop": stop}


IN_USE = usage_row("webcam", True, "InventedVendor.CameraApp_invented0",
                   start=filetime(NOW - timedelta(minutes=10)), stop=0)
PROGRAM = usage_row("microphone", False, "C:#Apps#rec.exe",
                    start=filetime(NOW - timedelta(hours=3)),
                    stop=filetime(NOW - timedelta(hours=2)))
NO_TIMES = usage_row("location", True, "InventedVendor.MapApp_invented0", value="Deny")
NEW_PROGRAM = usage_row("microphone", False, "C:#Apps#new.exe",
                        start=filetime(NOW - timedelta(hours=1)),
                        stop=filetime(NOW - timedelta(minutes=30)))


def machine(usage_rows):
    return FakePowerShell({
        "registry_values": registry(present(INFO, 0)),
        "capability_usage": ok(usage_rows),
    })


class TestUsage(SettingsTestCase):
    def setUp(self):
        super().setUp()
        self.write_catalogue([
            registry_entry("invented_usage_info", [INFO], expected=None, default=0),
        ])

    def test_order_and_changes(self):
        data_dir = self.data_dir()
        summary = self.collect(machine([NO_TIMES, PROGRAM, IN_USE]), data_dir=data_dir,
                               now=minutes(0))
        usage = summary.get("usage")
        self.assertIsInstance(usage, list, summary)
        self.assertEqual([item.get("id") for item in usage], ["u1", "u2", "u3"], usage)
        self.assertEqual([item.get("capability") for item in usage],
                         ["webcam", "microphone", "location"], usage)

        in_use, program, no_times = usage
        self.assertIs(in_use.get("in_use"), True, in_use)
        self.assertIsNone(in_use.get("last_used_stop"), in_use)
        self.assertEqual(program.get("app"), "C:\\Apps\\rec.exe", program)
        self.assertIs(program.get("packaged"), False, program)
        self.assertIsNone(no_times.get("last_used_stop"), no_times)

        summary = self.collect(machine([NO_TIMES, PROGRAM, IN_USE, NEW_PROGRAM]),
                               data_dir=data_dir, now=minutes(1))
        changes = self.changes(summary)
        self.assertEqual(len(changes), 1, changes)
        change = changes[0]
        self.assertEqual(change.get("change"), "added", change)
        self.assertIn("entry", change)
        self.assertIsNone(change["entry"], change)
        self.assertEqual(change.get("app"), "C:\\Apps\\new.exe", change)

    def test_budget(self):
        rows = [
            usage_row(("webcam", "microphone", "location")[i % 3], False,
                      f"C:#InventedApps#tool{i:04d}.exe",
                      start=filetime(NOW - timedelta(minutes=i + 1)),
                      stop=filetime(NOW - timedelta(minutes=i)))
            for i in range(3000)
        ]
        code, stdout, stderr = self.run_main(self.data_dir(), machine(rows))
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.rstrip()), SUMMARY_MAX_CHARS)
        summary = self.parse(stdout)

        truncated = summary.get("truncated")
        self.assertIsInstance(truncated, int, summary.get("truncated"))
        self.assertGreater(truncated, 0)
        self.assertEqual(len(summary.get("usage")) + truncated, 3000)

        detail_usage = self.detail(summary).get("usage")
        self.assertIsInstance(detail_usage, list)
        self.assertEqual(len(detail_usage), 3000)


class TestUsageChanges(SettingsTestCase):
    """TEST-PLAN (b), diff skill: each change kind and an unread source (added by loc-qa)."""

    def setUp(self):
        super().setUp()
        self.write_catalogue([
            registry_entry("invented_usage_info", [INFO], expected=None, default=0),
        ])

    def test_removed_and_changed(self):
        data_dir = self.data_dir()
        first = self.collect(machine([PROGRAM, NO_TIMES]), data_dir=data_dir,
                             now=minutes(0))
        self.assertEqual(self.changes(first), [])

        denied = dict(PROGRAM, value="Deny")
        summary = self.collect(machine([denied]), data_dir=data_dir, now=minutes(1))
        by_kind = {change.get("change"): change for change in self.changes(summary)}
        self.assertEqual(sorted(by_kind), ["changed", "removed"], self.changes(summary))

        changed = by_kind["changed"]
        self.assertIsNone(changed.get("entry"), changed)
        self.assertEqual(changed.get("app"), "C:\\Apps\\rec.exe", changed)
        self.assertEqual(changed.get("before"), "Allow", changed)
        self.assertEqual(changed.get("after"), "Deny", changed)

        removed = by_kind["removed"]
        self.assertIsNone(removed.get("entry"), removed)
        self.assertEqual(removed.get("app"), NO_TIMES["subkey"], removed)
        self.assertNotIn("before", removed)
        self.assertNotIn("after", removed)

    def test_unread_usage_no_false_changes(self):
        data_dir = self.data_dir()
        self.collect(machine([PROGRAM, IN_USE]), data_dir=data_dir, now=minutes(0))

        unread = FakePowerShell({
            "registry_values": registry(present(INFO, 0)),
            "capability_usage": fail("Invented access failure."),
        })
        summary = self.collect(unread, data_dir=data_dir, now=minutes(1))
        self.assertEqual(self.changes(summary), [])
        self.assertIn("capability_usage", self.not_checked_text(summary))

        summary = self.collect(machine([PROGRAM, IN_USE]), data_dir=data_dir,
                               now=minutes(2))
        self.assertEqual(self.changes(summary), [])

    def test_unread_subkey_keeps_previous_value(self):
        data_dir = self.data_dir()
        self.collect(machine([PROGRAM]), data_dir=data_dir, now=minutes(0))

        unread = dict(PROGRAM, value=None, error="Invented access failure.")
        summary = self.collect(machine([unread]), data_dir=data_dir, now=minutes(1))
        self.assertEqual(self.changes(summary), [])

        denied = dict(PROGRAM, value="Deny")
        summary = self.collect(machine([denied]), data_dir=data_dir, now=minutes(2))
        changes = self.changes(summary)
        self.assertEqual(len(changes), 1, changes)
        self.assertEqual(changes[0].get("change"), "changed", changes)
        self.assertEqual(changes[0].get("before"), "Allow", changes)
        self.assertEqual(changes[0].get("after"), "Deny", changes)


if __name__ == "__main__":
    unittest.main()

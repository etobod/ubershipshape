"""ush-health: fields left out of the comparison are named in ``not_checked``
(plan 141, M1, K1-K4).

Interface under test (from the plan):

- After comparing, for each baseline source whose ``comparison`` state is ``compared``,
  the fields named in ``unread_fields`` of an item on either side (this run or the
  reference baseline), counted only for keys present on both sides, give one
  ``not_checked`` item whose ``what`` is
  ``"<source> not compared: <fields, comma-separated, sorted>"``.
- An item present on one side only is ``added`` or ``removed`` and gives no such item.

Every run here has administrator rights and uses the invented ``machine()`` of
``test_baseline.py`` (a disk with a ``UniqueId``, a read Windows version), so a clean
pair of runs reads every compared field. Every value here is invented; nothing comes
from a machine. PowerShell never starts.
"""

import unittest
from datetime import timedelta

from .fakes import NOW, HealthTestCase, failure, ok
from .test_baseline import counter_error, machine, volume_row

NOT_COMPARED = "not compared:"
DISK_COUNTER_FIELDS = ("wear_percent", "read_errors_total", "write_errors_total")


class TestUnreadCompared(HealthTestCase):
    # --- helpers ------------------------------------------------------------------------

    def run_health(self, data_dir, fake, now=NOW):
        code, stdout, stderr = self.run_main(data_dir, fake, admin=True, now=now)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def two_runs(self, first_fake, second_fake):
        """Run twice in one data directory; return the summary of the second run."""
        data_dir = self.data_dir()
        self.run_health(data_dir, first_fake, now=NOW)
        return self.run_health(data_dir, second_fake, now=NOW + timedelta(hours=1))

    def assert_compared(self, summary, *sources):
        """The second run really compared: the baseline and each named source."""
        info = summary.get("baseline")
        self.assertIsInstance(info, dict, summary)
        self.assertEqual(info.get("status"), "compared", info)
        comparison = summary.get("comparison")
        self.assertIsInstance(comparison, dict, summary)
        for source in sources:
            self.assertEqual(comparison.get(source), "compared", comparison)

    def changes(self, summary):
        changes = summary.get("changes")
        self.assertIsInstance(changes, list, summary)
        return changes

    def entries_starting(self, summary, prefix):
        return [what for what in self.not_checked_whats(summary) if what.startswith(prefix)]

    def listed_fields(self, what, source):
        """The field list of a "<source> not compared: a, b" item; it must be sorted."""
        prefix = f"{source} {NOT_COMPARED}"
        self.assertTrue(what.startswith(prefix), what)
        fields = [field.strip() for field in what[len(prefix):].split(",")]
        self.assertTrue(all(fields), what)
        self.assertEqual(fields, sorted(fields), what)
        return fields

    # --- K1 -----------------------------------------------------------------------------

    def test_unread_protection_named(self):
        # First run reads protection of C; the second fails the encryption job.
        second = self.two_runs(
            machine(),
            machine(encryption=failure("New-Object : Invented COM failure")),
        )
        self.assert_compared(second, "volumes")
        entries = self.entries_starting(second, f"volumes {NOT_COMPARED}")
        self.assertEqual(len(entries), 1, second["not_checked"])
        self.assertIn("protection", self.listed_fields(entries[0], "volumes"), entries)
        self.assertEqual([c for c in self.changes(second) if c.get("source") == "volumes"],
                         [])

    # --- K2 -----------------------------------------------------------------------------

    def test_all_read_no_item(self):
        # Clean data: two identical runs with every read complete.
        second = self.two_runs(machine(), machine())
        self.assert_compared(second, "disks", "volumes", "devices", "os")
        whats = self.not_checked_whats(second)
        self.assertEqual([what for what in whats if NOT_COMPARED in what], [], whats)

    # --- K3 -----------------------------------------------------------------------------

    def test_unread_in_reference_named(self):
        # The counter is empty only in the reference run; this run reads it.
        second = self.two_runs(
            machine(disk_reliability=ok([counter_error("0")])),
            machine(),
        )
        self.assert_compared(second, "disks")
        entries = self.entries_starting(second, f"disks {NOT_COMPARED}")
        self.assertEqual(len(entries), 1, second["not_checked"])
        fields = self.listed_fields(entries[0], "disks")
        self.assertTrue(any(field in DISK_COUNTER_FIELDS for field in fields), entries)

    # --- K4 -----------------------------------------------------------------------------

    def test_added_item_not_named(self):
        # Volume D is new in this run and its protection is null; C is read on both sides.
        second = self.two_runs(
            machine(),
            machine(
                volumes=ok([volume_row(214.6), volume_row(50.0, letter="D")]),
                encryption=ok([{"DriveLetter": "C", "BitLockerProtection": 1},
                               {"DriveLetter": "D", "BitLockerProtection": None}]),
            ),
        )
        self.assert_compared(second, "volumes")
        new_volumes = [v for v in second.get("volumes") or []
                       if self.letter(v.get("drive_letter")) == "D"]
        self.assertEqual(len(new_volumes), 1, second.get("volumes"))
        self.assertIsNone(new_volumes[0].get("protection"), new_volumes)
        volume_changes = [c for c in self.changes(second) if c.get("source") == "volumes"]
        self.assertEqual([c.get("kind") for c in volume_changes], ["added"], volume_changes)
        self.assertEqual(self.letter(volume_changes[0].get("name")), "D", volume_changes)
        self.assertEqual(self.entries_starting(second, f"volumes {NOT_COMPARED}"), [],
                         second["not_checked"])


if __name__ == "__main__":
    unittest.main()

"""Windows Update history and pending-reboot flags in health.py (plan 047, M3).

Every update entry and registry flag is invented; PowerShell is never started.
"""

import importlib
import unittest
from datetime import datetime, timezone

_fakes = importlib.import_module("tests.ush-health.fakes_m3")
FakePowerShell = _fakes.FakePowerShell
HealthTestCase = _fakes.HealthTestCase
ok = _fakes.ok

TITLE_A = "Invented Cumulative Update for Windows (KB9900001)"
TITLE_B = "Invented Security Intelligence Update (KB9900002)"
TITLE_C = "Invented Driver Update for Example Device"


def entry(title, result_code, date, hresult=0):
    """One row of the update_history projection; Date is UTC without a zone."""
    return {"Title": title, "ResultCode": result_code, "HResult": hresult, "Date": date}


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestHistory(HealthTestCase):
    def updates(self, summary):
        self.assertIsInstance(summary.get("updates"), dict, summary.get("updates"))
        return summary["updates"]

    def test_failures_grouped_utc(self):
        # -2145116149 & 0xFFFFFFFF == 0x8024200B (the plan's example -2145124341
        # is 0x8024000B, so the signed value is taken from the expected hex).
        rows = [
            entry(TITLE_A, 4, "2026-09-01T10:30:00", hresult=-2145116149),
            entry(TITLE_B, 2, "2026-09-03T09:00:00"),
            entry(TITLE_C, 5, "2026-09-05T12:00:00", hresult=-2147467259),
            entry(TITLE_A, 4, "2026-09-10T08:15:00", hresult=-2145116149),
        ]
        fake = FakePowerShell({"update_history": ok(rows)})
        summary = self.collect(fake)

        self.assertEqual(self.source(summary, "update_history").get("status"), "read")
        updates = self.updates(summary)
        self.assertEqual(updates.get("history_count"), 4)
        failures = updates.get("failures")
        self.assertIsInstance(failures, list, failures)
        self.assertEqual(len(failures), 2, failures)

        # Newest `last` first: group A (2026-09-10) before group C (2026-09-05).
        group_a, group_c = failures
        self.assertEqual(group_a.get("id"), "u1")
        self.assertEqual(group_a.get("title"), TITLE_A)
        self.assertEqual(group_a.get("result"), "Failed")
        self.assertEqual(group_a.get("hresult"), "0x8024200B")
        self.assertEqual(group_a.get("count"), 2)
        for key, expected in (("first", "2026-09-01T10:30:00"), ("last", "2026-09-10T08:15:00")):
            with self.subTest(field=key):
                value = group_a.get(key)
                self.assertIsInstance(value, str, group_a)
                self.assertTrue(value.endswith("Z"), value)
                # The zone-less time is UTC: no shift by the local zone.
                self.assertEqual(
                    instant(value),
                    datetime.fromisoformat(expected).replace(tzinfo=timezone.utc),
                )

        self.assertEqual(group_c.get("id"), "u2")
        self.assertEqual(group_c.get("title"), TITLE_C)
        self.assertEqual(group_c.get("result"), "Aborted")
        self.assertEqual(group_c.get("hresult"), "0x80004005")
        self.assertEqual(group_c.get("count"), 1)
        self.assertTrue(group_c.get("first", "").endswith("Z"), group_c)
        self.assertEqual(group_c.get("first"), group_c.get("last"))
        self.assertEqual(
            instant(group_c["last"]), datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        )

        script = fake.script_of("update_history")
        self.assertIn("SpecifyKind", script)
        self.assertNotIn("ToUniversalTime", script)

    def test_clean_and_empty_history(self):
        with self.subTest(case="only succeeded"):
            rows = [
                entry(TITLE_A, 2, "2026-09-01T10:30:00"),
                entry(TITLE_B, 2, "2026-09-03T09:00:00"),
                entry(TITLE_C, 2, "2026-09-05T12:00:00"),
            ]
            summary = self.collect(FakePowerShell({"update_history": ok(rows)}))
            self.assertEqual(self.source(summary, "update_history").get("status"), "read")
            updates = self.updates(summary)
            self.assertEqual(updates.get("failures"), [])
            self.assertEqual(updates.get("by_result"), {"Succeeded": 3})
            self.assertEqual(updates.get("history_count"), 3)

        with self.subTest(case="empty history"):
            summary = self.collect(FakePowerShell({"update_history": ok([])}))
            self.assertEqual(self.source(summary, "update_history").get("status"), "empty")

        with self.subTest(case="unknown result code"):
            rows = [
                entry(TITLE_A, 7, "2026-09-01T10:30:00"),
                entry(TITLE_B, 2, "2026-09-03T09:00:00"),
            ]
            summary = self.collect(FakePowerShell({"update_history": ok(rows)}))
            self.assertEqual(self.source(summary, "update_history").get("status"), "read")
            updates = self.updates(summary)
            self.assertEqual(updates.get("by_result"), {"7": 1, "Succeeded": 1})
            self.assertEqual(updates.get("failures"), [])


class TestReboot(HealthTestCase):
    def test_flags_separate(self):
        with self.subTest(case="no reboot pending"):
            flags = {
                "WindowsUpdateRebootRequired": False,
                "ComponentBasedServicingRebootPending": False,
                "PendingFileRenameOperations": False,
            }
            summary = self.collect(FakePowerShell({"pending_reboot": ok(flags)}))
            self.assertEqual(self.source(summary, "pending_reboot").get("status"), "read")
            self.assertEqual(
                summary.get("pending_reboot"),
                {
                    "windows_update": False,
                    "component_servicing": False,
                    "file_rename_operations": False,
                },
            )

        with self.subTest(case="only file rename operations"):
            flags = {
                "WindowsUpdateRebootRequired": False,
                "ComponentBasedServicingRebootPending": False,
                "PendingFileRenameOperations": True,
            }
            summary = self.collect(FakePowerShell({"pending_reboot": ok(flags)}))
            self.assertEqual(self.source(summary, "pending_reboot").get("status"), "read")
            self.assertEqual(
                summary.get("pending_reboot"),
                {
                    "windows_update": False,
                    "component_servicing": False,
                    "file_rename_operations": True,
                },
            )


if __name__ == "__main__":
    unittest.main()

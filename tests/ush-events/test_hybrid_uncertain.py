"""Hybrid Kernel-Boot 27 joining an untyped session (invented data only).

A Kernel-Boot 27 of type "1" that joins an open session with no boot type
yet may be a separate hybrid boot. analyze() lists such sessions under
"uncertain_boots" and build_summary names them in not_checked.

Every event is created inside the list in the intended RecordId order: the
code under test orders by RecordId.
"""

import importlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Helpers of the Fast Startup tests; the package name has a hyphen.
_fast = importlib.import_module("tests.ush-events.test_fast_startup")

JOINED = "Fast Startup Kernel-Boot 27 joined"
EXPECTED_WHAT_B1 = (
    "boot sessions b1: a Fast Startup Kernel-Boot 27 joined a session without "
    "a typed Kernel-Boot 27"
)
EXPECTED_REASON = (
    "it may be a separate hybrid boot; the boot_type of these sessions and the "
    "clean_shutdown before them are uncertain"
)
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _untyped_session_then_hybrid_27():
    """Kernel start and event log markers without a 27, then a lone 27 "1"."""
    return [
        _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-20T08:00:00+02:00"),
        _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-20T08:00:10+02:00"),
        _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-20T08:00:10+02:00"),
        _fast.boot_type_event("2026-09-21T08:00:02+02:00", "1"),
    ]


def _joined_entries(summary):
    return [
        item for item in summary["not_checked"]
        if isinstance(item.get("what"), str) and JOINED in item["what"]
    ]


class TestHybridUncertain(_fast.FastStartupTestCase):
    def _summary(self, analysis, sources):
        with tempfile.TemporaryDirectory() as tmp:
            return self.events.build_summary(
                NOW, 7, sources, analysis, [],
                Path(tmp) / "summary.json", Path(tmp) / "detail.json",
            )

    def test_hybrid_27_joining_untyped_session_is_reported(self):
        # K1
        analysis = self.events.analyze(_untyped_session_then_hybrid_27(), [])
        self.assertEqual(
            [(b["index"], b["boot_type"]) for b in analysis["boots"]],
            [(1, "fast_startup")],
        )
        self.assertEqual(analysis["uncertain_boots"], [1])
        summary = self._summary(analysis, [])
        entries = _joined_entries(summary)
        self.assertEqual(len(entries), 1, summary["not_checked"])
        self.assertIn("b1", entries[0]["what"])
        self.assertEqual(entries[0]["what"], EXPECTED_WHAT_B1)
        self.assertEqual(entries[0]["reason"], EXPECTED_REASON)

    def test_normal_hybrid_boot_adds_no_entry(self):
        # K2 (clean data)
        for with_6006 in (False, True):
            with self.subTest(with_6006=with_6006):
                events = [
                    _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-20T08:00:10+02:00"),
                    _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-20T08:00:10+02:00"),
                    _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-20T08:00:00+02:00"),
                    _fast.boot_type_event("2026-09-20T08:00:02+02:00", "0"),
                ]
                if with_6006:
                    events.append(
                        _fast.event(_fast.EVENTLOG, 6006, 4, "2026-09-20T18:00:00+02:00")
                    )
                events.append(_fast.boot_type_event("2026-09-21T08:00:02+02:00", "1"))
                analysis = self.events.analyze(events, [])
                self.assertEqual(len(analysis["boots"]), 2)
                self.assertEqual(analysis["uncertain_boots"], [])
                summary = self._summary(analysis, [])
                self.assertEqual(_joined_entries(summary), [], summary["not_checked"])

    def test_session_opened_by_hybrid_27_is_not_uncertain(self):
        # K3 (clean data)
        events = [
            _fast.boot_type_event("2026-09-20T08:00:02+02:00", "1"),
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
            _fast.boot_type_event("2026-09-21T08:00:02+02:00", "0"),
        ]
        analysis = self.events.analyze(events, [])
        self.assertEqual(len(analysis["boots"]), 2)
        self.assertEqual(analysis["uncertain_boots"], [])

    def test_no_entry_without_pass_b(self):
        # K4
        analysis = self.events.analyze(_untyped_session_then_hybrid_27(), [])
        self.assertEqual(analysis["uncertain_boots"], [1])
        sources = [
            {
                "log": "System",
                "pass": "B",
                "status": "unreadable",
                "reason": "invented: the log could not be read",
                "event_count": 0,
                "log_oldest_record": None,
                "coverage_start": None,
            }
        ]
        summary = self._summary(analysis, sources)
        self.assertEqual(_joined_entries(summary), [], summary["not_checked"])


if __name__ == "__main__":
    unittest.main()

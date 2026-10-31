"""Where a session opened by a hybrid boot (Fast Startup) ends (invented data only).

A session opened by a Kernel-Boot 27 of type "1" never takes a boot marker
(Kernel-General 12, EventLog 6009, EventLog 6005); such a marker opens the
next session. A session opened by 12, 6009 or 6005 keeps its markers, even
when a 27 of type "1" comes later in it.

Every event is created inside the list in the intended RecordId order: the
code under test orders by RecordId, so times are out of order on purpose.
"""

import importlib
import unittest
from datetime import datetime

# Helpers of the Fast Startup tests; the package name has a hyphen.
_fast = importlib.import_module("tests.ush-events.test_fast_startup")

CRASH_KINDS = ("unexpected_shutdown", "kernel_power_41")


def _crash_anomalies(result):
    return sorted(
        (a["kind"], a["boot"]) for a in result["anomalies"] if a["kind"] in CRASH_KINDS
    )


class TestHybridSession(_fast.FastStartupTestCase):
    def test_crash_boot_after_hybrid_gets_its_own_session(self):
        # K1: cold boot, no 6006; a hybrid boot writing only its 27; no 6006;
        # a crash boot whose 6009/6005/6008 come before its Kernel-General 12.
        events = _fast.boot_markers("2026-09-20", "08", "0") + [
            _fast.boot_type_event("2026-09-21T08:00:02+02:00", "1"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6008, 2, "2026-09-22T08:00:05+02:00"),
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-22T08:00:00+02:00"),
            _fast.boot_type_event("2026-09-22T08:00:02+02:00", "0"),
            _fast.event(_fast.KERNEL_POWER, 41, 1, "2026-09-22T08:00:12+02:00"),
        ]
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual(
            [(b["index"], b["boot_type"]) for b in boots],
            [(1, "cold"), (2, "fast_startup"), (3, "cold")],
        )
        self.assertEqual(
            _crash_anomalies(result),
            [("kernel_power_41", 3), ("unexpected_shutdown", 3)],
        )
        self.assertIs(boots[1]["clean_shutdown"], False)

    def test_kernel_start_after_hybrid_opens_the_next_session(self):
        # K2: as K1, but the crash boot starts with its Kernel-General 12.
        hybrid_time = "2026-09-21T08:00:02+02:00"
        kernel_start_time = "2026-09-22T08:00:00+02:00"
        events = _fast.boot_markers("2026-09-20", "08", "0") + [
            _fast.boot_type_event(hybrid_time, "1"),
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, kernel_start_time),
            _fast.boot_type_event("2026-09-22T08:00:02+02:00", "0"),
            _fast.event(_fast.EVENTLOG, 6008, 2, "2026-09-22T08:00:05+02:00"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.KERNEL_POWER, 41, 1, "2026-09-22T08:00:12+02:00"),
        ]
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2, 3])
        self.assertEqual(
            datetime.fromisoformat(boots[2]["start"]),
            datetime.fromisoformat(kernel_start_time),
        )
        self.assertEqual(
            datetime.fromisoformat(boots[1]["start"]),
            datetime.fromisoformat(hybrid_time),
        )
        self.assertEqual(
            _crash_anomalies(result),
            [("kernel_power_41", 3), ("unexpected_shutdown", 3)],
        )

    def test_hybrid_boot_then_restart(self):
        # K3: cold boot, no 6006; a hybrid boot writing only its 27; a clean
        # 6006; then a restart whose 6009/6005 come before its 12 and 27 "0".
        events = _fast.boot_markers("2026-09-20", "08", "0") + [
            _fast.boot_type_event("2026-09-21T08:00:02+02:00", "1"),
            _fast.event(_fast.EVENTLOG, 6006, 4, "2026-09-21T18:00:00+02:00"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-22T08:00:00+02:00"),
            _fast.boot_type_event("2026-09-22T08:00:02+02:00", "0"),
        ]
        boots = self.events.analyze(events, [])["boots"]
        # Session 1 is followed by a hybrid boot, so its shutdown is unknown.
        self.assertEqual(
            [(b["index"], b["clean_shutdown"], b["boot_type"]) for b in boots],
            [(1, None, "cold"), (2, True, "fast_startup"), (3, None, "cold")],
        )

    def test_session_opened_by_kernel_start_keeps_its_markers(self):
        # K4: one boot opened by Kernel-General 12; its 27 "1" comes before
        # its 6009 and 6005, which still belong to the same session.
        events = [
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-20T08:00:00+02:00"),
            _fast.boot_type_event("2026-09-20T08:00:02+02:00", "1"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-20T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-20T08:00:10+02:00"),
        ]
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual(
            [(b["index"], b["boot_type"]) for b in boots],
            [(1, "fast_startup")],
        )


if __name__ == "__main__":
    unittest.main()

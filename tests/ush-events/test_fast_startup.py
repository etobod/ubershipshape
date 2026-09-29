"""Boot sessions with Fast Startup and hibernation resumes (invented data only).

Kernel-Boot 27 carries the boot type in Properties[0]: "0" cold boot,
"1" hybrid boot (Fast Startup), "2" resume from hibernation.
"""

import itertools
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

EVENTLOG = "EventLog"
KERNEL_POWER = "Microsoft-Windows-Kernel-Power"
KERNEL_GENERAL = "Microsoft-Windows-Kernel-General"
KERNEL_BOOT = "Microsoft-Windows-Kernel-Boot"

_record_ids = itertools.count(7001)


def event(provider, event_id, level, time, properties=None):
    return {
        "ProviderName": provider,
        "Id": event_id,
        "Level": level,
        "LogName": "System",
        "RecordId": next(_record_ids),
        "TimeCreated": time,
        "Message": f"Invented message for {provider} {event_id}.",
        "Properties": [] if properties is None else properties,
    }


def boot_type_event(time, value):
    return event(KERNEL_BOOT, 27, 4, time, [value])


def boot_markers(date, hour, boot_type):
    """Kernel start, event log markers and a Kernel-Boot 27 of the given type."""
    return [
        event(KERNEL_GENERAL, 12, 4, f"{date}T{hour}:00:00+02:00"),
        event(EVENTLOG, 6009, 4, f"{date}T{hour}:00:10+02:00"),
        event(EVENTLOG, 6005, 4, f"{date}T{hour}:00:10+02:00"),
        boot_type_event(f"{date}T{hour}:00:02+02:00", boot_type),
    ]


class FastStartupTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")


class TestBootType(FastStartupTestCase):
    def test_cold_boot_and_session_without_27(self):
        events = boot_markers("2026-09-20", "08", "0") + [
            event(EVENTLOG, 6006, 4, "2026-09-20T18:00:00+02:00"),
            # Second boot writes no Kernel-Boot 27 at all.
            event(KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["boot_type"], b["hibernate_resumes"]) for b in result["boots"]],
            [(1, "cold", 0), (2, None, 0)],
        )

    def test_hibernate_resumes_stay_in_session(self):
        events = boot_markers("2026-09-20", "08", "0") + [
            event(KERNEL_POWER, 506, 4, "2026-09-20T12:00:00+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-20T13:00:00+02:00"),
            boot_type_event("2026-09-20T13:00:01+02:00", "2"),
            event(KERNEL_POWER, 506, 4, "2026-09-20T16:00:00+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-20T17:00:00+02:00"),
            boot_type_event("2026-09-20T17:00:01+02:00", "2"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["hibernate_resumes"]) for b in result["boots"]],
            [(1, 2)],
        )
        self.assertNotIn(
            "sleep_without_wake", [a["kind"] for a in result["anomalies"]]
        )

    def test_unreadable_boot_type_is_ignored(self):
        events = [
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T08:00:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-20T08:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:10+02:00"),
            # Created here, so its RecordId comes after the markers.
            event(KERNEL_BOOT, 27, 4, "2026-09-20T08:00:01+02:00"),
            boot_type_event("2026-09-20T08:00:02+02:00", "0"),
            boot_type_event("2026-09-20T08:00:03+02:00", "7"),
        ]
        del events[3]["Properties"]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["boot_type"], b["hibernate_resumes"]) for b in result["boots"]],
            [(1, "cold", 0)],
        )

    def test_resume_before_first_boot_counts_in_session_0(self):
        events = [
            event(KERNEL_POWER, 506, 4, "2026-09-20T06:00:00+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-20T07:00:00+02:00"),
            boot_type_event("2026-09-20T07:00:01+02:00", "2"),
        ] + boot_markers("2026-09-20", "08", "0")
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["boot_type"], b["hibernate_resumes"]) for b in result["boots"]],
            [(0, None, 1), (1, "cold", 0)],
        )


class TestFastStartupSessions(FastStartupTestCase):
    def test_session_before_fast_startup_is_not_unclean(self):
        # No 6006 before the hybrid boot: a Fast Startup shutdown hibernates
        # the kernel instead of writing 6006, so the shutdown is unknown.
        events = boot_markers("2026-09-20", "08", "0") + boot_markers(
            "2026-09-21", "08", "1"
        )
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["clean_shutdown"], b["boot_type"]) for b in result["boots"]],
            [(1, None, "cold"), (2, None, "fast_startup")],
        )

    def test_fast_startup_with_only_27_opens_one_session(self):
        events = boot_markers("2026-09-20", "08", "0") + [
            # Hybrid boot that writes only Kernel-Boot 27.
            boot_type_event("2026-09-21T08:00:02+02:00", "1"),
            # Cold boot without a 6006 before it; its 27 comes last.
            event(KERNEL_POWER, 41, 1, "2026-09-22T08:00:02+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-22T08:00:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-22T08:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-22T08:00:10+02:00"),
            boot_type_event("2026-09-22T08:00:12+02:00", "0"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["boot_type"]) for b in result["boots"]],
            [(1, "cold"), (2, "fast_startup"), (3, "cold")],
        )

    def test_session_before_cold_boot_stays_unclean(self):
        events = boot_markers("2026-09-20", "08", "0") + boot_markers(
            "2026-09-21", "08", "0"
        )
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["clean_shutdown"], b["boot_type"]) for b in result["boots"]],
            [(1, False, "cold"), (2, None, "cold")],
        )


class TestSummaryFields(FastStartupTestCase):
    def test_pass_b_and_summary_carry_boot_type(self):
        self.assertIn(27, self.events.PASS_B_IDS)
        events = boot_markers("2026-09-20", "08", "0") + [
            event(KERNEL_POWER, 506, 4, "2026-09-20T12:00:00+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-20T13:00:00+02:00"),
            boot_type_event("2026-09-20T13:00:01+02:00", "2"),
        ]
        analysis = self.events.analyze(events, [])
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            summary = self.events.build_summary(
                now, 7, [], analysis, [],
                Path(tmp) / "summary.json", Path(tmp) / "detail.json",
            )
        self.assertEqual(
            [(b["id"], b["boot_type"], b["hibernate_resumes"]) for b in summary["boots"]],
            [("b1", "cold", 1)],
        )


def unreadable_boot_type_event(time):
    """A Kernel-Boot 27 with no Properties at all: its boot type cannot be read."""
    no_properties = event(KERNEL_BOOT, 27, 4, time)
    del no_properties["Properties"]
    return no_properties


def boot_without_type(date, hour):
    """Kernel start and event log markers with no Kernel-Boot 27."""
    return [
        event(KERNEL_GENERAL, 12, 4, f"{date}T{hour}:00:00+02:00"),
        event(EVENTLOG, 6009, 4, f"{date}T{hour}:00:10+02:00"),
        event(EVENTLOG, 6005, 4, f"{date}T{hour}:00:10+02:00"),
    ]


class TestUnreadableNextBoot(FastStartupTestCase):
    def _cold_session_then_unreadable_boot(self):
        # Cold session with no 6006, then a boot whose 27 has no Properties.
        return (
            boot_markers("2026-09-20", "08", "0")
            + boot_without_type("2026-09-21", "08")
            + [unreadable_boot_type_event("2026-09-21T08:00:02+02:00")]
        )

    def test_session_before_unreadable_boot_type_is_unknown(self):
        result = self.events.analyze(self._cold_session_then_unreadable_boot(), [])
        boots = result["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2])
        self.assertEqual(boots[0]["boot_type"], "cold")
        self.assertIsNone(boots[0]["clean_shutdown"])
        self.assertIsNone(boots[1]["boot_type"])

    def test_session_before_boot_without_27_stays_unclean(self):
        events = boot_markers("2026-09-20", "08", "0") + boot_without_type(
            "2026-09-21", "08"
        )
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2])
        self.assertIs(boots[0]["clean_shutdown"], False)
        self.assertIsNone(boots[1]["boot_type"])

    def test_summary_still_counts_unread_and_adds_no_field(self):
        analysis = self.events.analyze(self._cold_session_then_unreadable_boot(), [])
        now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            summary = self.events.build_summary(
                now, 7, [], analysis, [],
                Path(tmp) / "summary.json", Path(tmp) / "detail.json",
            )
        expected = "1 Kernel-Boot 27 events without a readable boot type"
        matching = [
            item for item in summary["not_checked"]
            if any(isinstance(v, str) and expected in v for v in item.values())
        ]
        self.assertEqual(len(matching), 1, summary["not_checked"])
        self.assertEqual(len(summary["boots"]), 2)
        for boot in summary["boots"]:
            self.assertEqual(
                set(boot),
                {"id", "index", "start", "end", "clean_shutdown", "boot_type",
                 "hibernate_resumes"},
            )

    def test_unreadable_27_before_first_boot(self):
        events = [
            unreadable_boot_type_event("2026-09-20T06:00:00+02:00"),
        ] + boot_markers("2026-09-20", "08", "0")
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["boot_type"]) for b in result["boots"]],
            [(1, "cold")],
        )


if __name__ == "__main__":
    unittest.main()

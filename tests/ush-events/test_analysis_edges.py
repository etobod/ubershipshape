"""Edge cases of the event analysis found in review (invented data only)."""

import itertools
import json
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

DCOM = "Microsoft-Windows-DistributedCOM"
EVENTLOG = "EventLog"
KERNEL_POWER = "Microsoft-Windows-Kernel-Power"
KERNEL_GENERAL = "Microsoft-Windows-Kernel-General"

_record_ids = itertools.count(5001)


def event(provider, event_id, level, time):
    return {
        "ProviderName": provider,
        "Id": event_id,
        "Level": level,
        "LogName": "System",
        "RecordId": next(_record_ids),
        "TimeCreated": time,
        "Message": f"Invented message for {provider} {event_id}.",
        "Properties": [],
    }


class EdgeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")


class TestSleepAtWindowEnd(EdgeTestCase):
    def test_sleep_followed_only_by_unrelated_events_is_not_reported(self):
        events = [
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:00+02:00"),
            event(KERNEL_POWER, 506, 4, "2026-09-20T22:00:00+02:00"),
            event(DCOM, 10016, 3, "2026-09-20T22:05:00+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(result["anomalies"], [])

    def test_sleep_before_next_boot_is_still_reported(self):
        events = [
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:00+02:00"),
            event(KERNEL_POWER, 506, 4, "2026-09-20T22:00:00+02:00"),
            event(DCOM, 10016, 3, "2026-09-20T22:05:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-21T08:00:00+02:00"),
        ]
        kinds = [a["kind"] for a in self.events.analyze(events, [])["anomalies"]]
        self.assertEqual(kinds, ["sleep_without_wake"])


class TestCrashBeforeEventLogStart(EdgeTestCase):
    """Kernel-Power 41 and EventLog 6008 are stamped before the 6005 of their boot."""

    def test_crash_events_belong_to_the_boot_they_describe(self):
        events = [
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T08:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:10+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T20:00:00+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-20T20:00:02+02:00"),
            event(EVENTLOG, 6008, 2, "2026-09-20T20:00:09+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T20:00:10+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["clean_shutdown"]) for b in result["boots"]],
            [(1, False), (2, None)],
        )
        self.assertEqual(
            [(a["kind"], a["boot"]) for a in result["anomalies"]],
            [("kernel_power_41", 2), ("unexpected_shutdown", 2)],
        )

    def test_without_kernel_general_6005_still_starts_sessions(self):
        events = [
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:10+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T19:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T20:00:10+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["clean_shutdown"]) for b in result["boots"]],
            [(1, True), (2, None)],
        )
        self.assertEqual(result["anomalies"], [])


class TestClockCorrectedAtBoot(EdgeTestCase):
    """Sessions follow the System log's write order (RecordId), not the clock."""

    def test_backward_clock_jump_keeps_one_session(self):
        events = [
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T07:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T07:00:10+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T18:00:00+02:00"),
            # Next boot: the clock ran ahead and was pulled back before 6005.
            event(KERNEL_GENERAL, 12, 4, "2026-09-21T08:01:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-21T08:00:20+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["clean_shutdown"]) for b in result["boots"]],
            [(1, True), (2, None)],
        )
        self.assertEqual(result["anomalies"], [])

    def test_crash_written_after_6005_belongs_to_new_boot(self):
        events = [
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T07:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T07:00:10+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T20:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T20:00:10+02:00"),
            # Written last, stamped with the earlier kernel time.
            event(KERNEL_POWER, 41, 1, "2026-09-20T20:00:02+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(a["kind"], a["boot"]) for a in result["anomalies"]],
            [("kernel_power_41", 2)],
        )


class TestEventLogBeforeKernel(EdgeTestCase):
    """The event log may write 6009 and 6005 before the kernel's Kernel-General 12."""

    def test_markers_in_any_order_make_one_session(self):
        events = [
            event(EVENTLOG, 6009, 4, "2026-09-20T08:00:13+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:13+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T08:00:00+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T18:00:00+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-21T08:00:12+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-21T08:00:12+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["start"], b["clean_shutdown"]) for b in result["boots"]],
            [(1, "2026-09-20T06:00:00+00:00", True), (2, "2026-09-21T06:00:00+00:00", None)],
        )

    def test_crash_with_kernel_clock_ahead_makes_two_sessions(self):
        # Both boots write the event log markers first and the kernel's clock
        # runs ahead; the first boot crashes. Two boots, no third one invented.
        events = [
            event(EVENTLOG, 6009, 4, "2026-09-20T07:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T07:00:10+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T07:01:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-20T20:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T20:00:10+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T20:01:00+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-20T20:01:02+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["clean_shutdown"]) for b in result["boots"]],
            [(1, False), (2, None)],
        )
        self.assertEqual(
            [(a["kind"], a["boot"]) for a in result["anomalies"]],
            [("kernel_power_41", 2)],
        )

    def test_lost_kernel_start_invents_no_session(self):
        # A boot whose Kernel-General 12 is missing: its edge may shift, but
        # two boots never become three.
        events = [
            event(EVENTLOG, 6009, 4, "2026-09-20T08:00:13+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:13+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T20:00:00+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-20T20:00:02+02:00"),
            event(EVENTLOG, 6008, 2, "2026-09-20T20:00:09+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-20T20:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T20:00:10+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(len(result["boots"]), 2)

    def test_kernel_clock_ahead_after_event_log_keeps_one_session(self):
        # Clean data: the event log writes first and the kernel's clock ran
        # ahead of it; no boot may be invented and none marked unclean.
        events = [
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T07:00:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-20T07:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T07:00:10+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T18:00:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-21T08:00:20+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-21T08:00:20+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-21T08:01:00+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-21T18:00:00+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["clean_shutdown"]) for b in result["boots"]],
            [(1, True), (2, True)],
        )
        self.assertEqual(result["anomalies"], [])


class TestOtherLogAtBoot(EdgeTestCase):
    """An Application event written while a boot writes its markers."""

    def app_event(self, time):
        ev = event("Invented-App", 1000, 2, time)
        ev["LogName"] = "Application"
        return ev

    def test_kernel_clock_ahead_invents_no_session_zero(self):
        events = [
            event(EVENTLOG, 6009, 4, "2026-09-20T07:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T07:00:10+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T07:01:00+02:00"),
            self.app_event("2026-09-20T07:00:30+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T18:00:00+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(
            [(b["index"], b["start"], b["clean_shutdown"]) for b in result["boots"]],
            [(1, "2026-09-20T05:00:10+00:00", True)],
        )

    def test_lost_kernel_start_invents_no_session_zero(self):
        events = [
            event(EVENTLOG, 6009, 4, "2026-09-20T08:00:13+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T08:00:13+02:00"),
            self.app_event("2026-09-20T12:00:00+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T20:00:00+02:00"),
            event(EVENTLOG, 6009, 4, "2026-09-20T20:00:10+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T20:00:10+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual([b["index"] for b in result["boots"]], [1, 2])


class TestSleepAcrossClockCorrection(EdgeTestCase):
    def test_wake_after_next_boot_in_time_is_still_found(self):
        # Clean data: the next boot's clock was set back, so its markers are
        # stamped before this sleep's wake. No sleep_without_wake.
        app = event("Invented-App", 1000, 2, "2026-09-20T12:05:00+02:00")
        app["LogName"] = "Application"
        events = [
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T10:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T10:00:10+02:00"),
            event(KERNEL_POWER, 506, 4, "2026-09-20T12:00:00+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-20T12:10:00+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T12:20:00+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T11:55:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T11:55:10+02:00"),
            app,
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(result["anomalies"], [])


class TestClockSetBackOtherLog(EdgeTestCase):
    def test_other_log_event_joins_the_most_recent_boot(self):
        crash = event(KERNEL_POWER, 41, 1, "2026-09-20T09:40:00+02:00")
        crash["LogName"] = "Application"
        events = [
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T10:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T10:00:10+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T12:00:00+02:00"),
            event(KERNEL_GENERAL, 12, 4, "2026-09-20T09:00:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T09:00:10+02:00"),
            crash,
        ]
        result = self.events.analyze(events, [])
        self.assertEqual([(a["kind"], a["boot"]) for a in result["anomalies"]],
                         [("kernel_power_41", 2)])


class TestMergeWithoutRecordId(EdgeTestCase):
    def test_events_without_record_id_are_not_collapsed(self):
        first = event(DCOM, 10010, 2, "2026-09-20T10:00:00+02:00")
        second = event(DCOM, 10010, 2, "2026-09-20T11:00:00+02:00")
        first["RecordId"] = second["RecordId"] = None
        self.assertEqual(len(self.events.merge([first], [second])), 2)
        self.assertEqual(len(self.events.merge([first], [first])), 1)


class TestSleepThenCleanShutdown(EdgeTestCase):
    def test_clean_shutdown_after_sleep_is_no_anomaly(self):
        events = [
            event(EVENTLOG, 6005, 4, "2026-09-20T10:00:10+02:00"),
            event(KERNEL_POWER, 506, 4, "2026-09-20T12:00:00+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-20T12:20:00+02:00"),
            event(EVENTLOG, 6005, 4, "2026-09-20T18:00:10+02:00"),
        ]
        result = self.events.analyze(events, [])
        self.assertEqual(result["anomalies"], [])


class TestPassBOnlyMakesNoGroups(EdgeTestCase):
    def test_pass_b_events_feed_anomalies_not_groups(self):
        kp41 = event(KERNEL_POWER, 41, 1, "2026-09-20T10:00:00+02:00")
        lost = event(EVENTLOG, 6008, 2, "2026-09-20T10:00:05+02:00")
        result = self.events.analyze(self.events.merge([], [kp41, lost]), [])
        self.assertEqual(result["groups"], [])
        self.assertEqual(sorted(a["kind"] for a in result["anomalies"]),
                         ["kernel_power_41", "unexpected_shutdown"])

    def test_event_in_both_passes_is_grouped_once(self):
        kp41 = event(KERNEL_POWER, 41, 1, "2026-09-20T10:00:00+02:00")
        result = self.events.analyze(self.events.merge([kp41], [dict(kp41)]), [])
        self.assertEqual([g["count"] for g in result["groups"]], [1])


class TestUnreadableTime(EdgeTestCase):
    def test_bad_time_is_listed_not_fatal(self):
        good = event(DCOM, 10016, 3, "2026-09-20T10:00:00+02:00")
        naive = event(DCOM, 10016, 3, "2026-09-20T11:00:00")
        missing = event(DCOM, 10016, 3, "2026-09-20T12:00:00+02:00")
        del missing["TimeCreated"]
        result = self.events.analyze([good, naive, missing], [])
        self.assertEqual([g["count"] for g in result["groups"]], [1])
        self.assertEqual(
            sorted(u["record_id"] for u in result["unreadable"]),
            sorted([naive["RecordId"], missing["RecordId"]]),
        )

    def test_clean_data_has_empty_unreadable(self):
        good = event(DCOM, 10016, 3, "2026-09-20T10:00:00+02:00")
        self.assertEqual(self.events.analyze([good], [])["unreadable"], [])


class TestShortenEarlyFullStop(EdgeTestCase):
    def test_early_sentence_end_does_not_empty_the_sample(self):
        sample = self.events.shorten("Error. " + "word " * 60)
        self.assertGreater(len(sample), 100)
        self.assertLessEqual(len(sample), 200)
        self.assertTrue(sample.endswith("..."), repr(sample))


class TestPropertiesShapes(EdgeTestCase):
    """ConvertTo-Json on PS 5.1 can write Properties in three wrong shapes."""

    def test_capture_properties_become_string_lists(self):
        shapes = [
            ({"value": ["0x0000019c (0x1)", "x", 3], "Count": 3}, ["0x0000019c (0x1)", "x", "3"]),
            ("0x0000019c (0x1)", ["0x0000019c (0x1)"]),
            ({}, []),
            (None, []),
            (["a", "b"], ["a", "b"]),
        ]
        captured = []
        for n, (raw, _) in enumerate(shapes):
            ev = event(DCOM, 10016, 3, "2026-09-20T10:00:00+02:00")
            ev["Properties"] = raw
            ev["RecordId"] = 9000 + n
            captured.append(ev)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.json"
            path.write_text(json.dumps(captured), encoding="utf-8")
            loaded = self.events.load_capture(path)
        self.assertEqual([ev["Properties"] for ev in loaded], [want for _, want in shapes])


class TestNoiseFileShape(EdgeTestCase):
    def test_non_list_file_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "noise.json"
            path.write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.events.load_noise(path)


if __name__ == "__main__":
    unittest.main()

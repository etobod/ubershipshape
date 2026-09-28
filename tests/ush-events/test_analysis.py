"""Behaviour tests for the analysis part of skills/ush-events/scripts/events.py.

Public interface under test:
- ``load_noise(path) -> list[dict]`` (entries: provider, event_id, reason)
- ``analyze(events, noise) -> dict`` with keys groups, noise, boots, anomalies

All events are invented here; nothing is read from the machine.
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

SYSTEM = "System"
APPLICATION = "Application"

DCOM = "Microsoft-Windows-DistributedCOM"
EVENTLOG = "EventLog"
KERNEL_POWER = "Microsoft-Windows-Kernel-Power"
WER_SYSTEM = "Microsoft-Windows-WER-SystemErrorReporting"

NOISE_REASON = "Invented reason: DCOM permission warning for a built-in app, harmless."

BUGCHECK_PROPERTY = (
    "0x0000019c (0x0000000000000050, 0xffffc10bd6c1f040, "
    "0x0000000000000000, 0x0000000000000000)"
)

_record_ids = iter(range(1000, 100000))


def event(provider, event_id, level, time, log=SYSTEM, properties=None, message=""):
    """Build one event in the agreed projection."""
    return {
        "ProviderName": provider,
        "Id": event_id,
        "Level": level,
        "LogName": log,
        "RecordId": next(_record_ids),
        "TimeCreated": time,
        "Message": message or f"Invented message for {provider} {event_id}.",
        "Properties": list(properties or []),
    }


def instant(text):
    """Parse an ISO 8601 string to an aware datetime in UTC."""
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def utc(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


class AnalysisTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def write_noise(self, entries):
        """Write a noise file into a temporary directory and load it through load_noise."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "noise.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return self.events.load_noise(path)


class TestNoise(AnalysisTestCase):
    def test_noise_counted_not_hidden(self):
        noise = self.write_noise(
            [{"provider": DCOM, "event_id": 10016, "reason": NOISE_REASON}]
        )
        self.assertEqual(
            noise, [{"provider": DCOM, "event_id": 10016, "reason": NOISE_REASON}]
        )

        events = [
            event(EVENTLOG, 6005, 4, "2026-09-18T09:00:00.0000000+02:00"),
            # Three noise events (listed provider + Id), out of order on purpose.
            event(DCOM, 10016, 3, "2026-09-18T11:00:00.0000000+02:00"),
            event(DCOM, 10016, 3, "2026-09-18T09:10:00.0000000+02:00"),
            event(DCOM, 10016, 3, "2026-09-18T10:00:00.0000000+02:00"),
            # Same provider, different Id: not noise.
            event(DCOM, 10010, 2, "2026-09-18T09:20:00.0000000+02:00"),
            # Same Id, different provider: not noise.
            event("Invented-Other-Provider", 10016, 3, "2026-09-18T09:30:00.0000000+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-18T12:00:00.0000000+02:00"),
        ]

        result = self.events.analyze(events, noise)

        # The noise section holds the listed events with their count and reason.
        self.assertEqual(len(result["noise"]), 1)
        entry = result["noise"][0]
        self.assertEqual(entry["provider"], DCOM)
        self.assertEqual(entry["event_id"], 10016)
        self.assertEqual(entry["count"], 3)
        self.assertEqual(entry["reason"], NOISE_REASON)
        self.assertEqual(instant(entry["first"]), utc(2026, 9, 18, 7, 10))
        self.assertEqual(instant(entry["last"]), utc(2026, 9, 18, 9, 0))

        # Events outside the list are ordinary groups, never marked as noise.
        group_keys = {(g["provider"], g["event_id"]): g["count"] for g in result["groups"]}
        self.assertEqual(
            group_keys,
            {(DCOM, 10010): 1, ("Invented-Other-Provider", 10016): 1},
        )

        # Nothing disappears: every level 1-3 event is counted once, in groups or noise.
        total = sum(g["count"] for g in result["groups"]) + sum(
            n["count"] for n in result["noise"]
        )
        self.assertEqual(total, 5)

    def test_noise_list_is_data(self):
        # The list shipped with the skill holds the five starting entries.
        shipped = self.events.load_noise()
        self.assertEqual({(n["provider"], n["event_id"]) for n in shipped}, DEFAULT_NOISE_PAIRS)
        for entry in shipped:
            self.assertTrue(entry["reason"].strip(), entry)

        events = [
            event("Invented-Fan-Provider", 42, 2, "2026-09-18T09:00:00.0000000+02:00"),
            event("Invented-Fan-Provider", 42, 2, "2026-09-18T09:30:00.0000000+02:00"),
        ]
        other = {"provider": "Invented-Other-Provider", "event_id": 1, "reason": "Invented."}
        added = {"provider": "Invented-Fan-Provider", "event_id": 42,
                 "reason": "Invented: fan warning that repeats harmlessly."}

        # Without the entry the events are an ordinary group.
        before = self.events.analyze(events, self.write_noise([other]))
        self.assertEqual(
            [(g["provider"], g["event_id"], g["count"]) for g in before["groups"]],
            [("Invented-Fan-Provider", 42, 2)],
        )
        self.assertEqual(before["noise"], [])

        # One more entry in the file, same code: now they are noise, with the file's reason.
        after = self.events.analyze(events, self.write_noise([other, added]))
        self.assertEqual(after["groups"], [])
        self.assertEqual(
            [(n["provider"], n["event_id"], n["count"], n["reason"]) for n in after["noise"]],
            [("Invented-Fan-Provider", 42, 2, added["reason"])],
        )


class TestAnomalies(AnalysisTestCase):
    def test_detects_each_kind(self):
        events = [
            # Boot 0: partial session before the first 6005 in the window.
            event("Invented-Disk-Provider", 153, 3, "2026-09-18T08:00:00.0000000+02:00"),
            # Boot 1.
            event(EVENTLOG, 6005, 4, "2026-09-18T09:00:00.0000000+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-18T09:00:10.0000000+02:00"),
            event(EVENTLOG, 6008, 2, "2026-09-18T09:00:12.0000000+02:00"),
            event(
                WER_SYSTEM,
                1001,
                2,
                "2026-09-18T09:01:00.0000000+02:00",
                properties=[BUGCHECK_PROPERTY, "C:\\Windows\\Minidump\\invented.dmp", "00000-00000"],
            ),
            # Sleep 10:00+02:00 and wake 08:30Z (= 10:30+02:00): a paired 506/507,
            # later as an instant although earlier as a string.
            event(KERNEL_POWER, 506, 4, "2026-09-18T10:00:00.0000000+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-18T08:30:00.0000000+00:00"),
            event(EVENTLOG, 6006, 4, "2026-09-18T11:00:00.0000000+02:00"),
            # Boot 2: sleep with no wake before the next boot.
            event(EVENTLOG, 6005, 4, "2026-09-18T11:05:00.0000000+02:00"),
            event(KERNEL_POWER, 506, 4, "2026-09-18T12:00:00.0000000+02:00"),
            # Boot 3.
            event(EVENTLOG, 6005, 4, "2026-09-18T13:00:00.0000000+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-18T13:00:05.0000000+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-18T14:00:00.0000000+02:00"),
        ]
        events.reverse()  # analyze must not rely on input order

        result = self.events.analyze(events, [])
        anomalies = result["anomalies"]

        for anomaly in anomalies:
            self.assertTrue(
                anomaly["time"].endswith("+00:00"), f"time not in UTC: {anomaly['time']}"
            )

        found = sorted(
            (a["kind"], a["boot"], instant(a["time"])) for a in anomalies
        )
        expected = sorted(
            [
                ("kernel_power_41", 1, utc(2026, 9, 18, 7, 0, 10)),
                ("unexpected_shutdown", 1, utc(2026, 9, 18, 7, 0, 12)),
                ("bugcheck", 1, utc(2026, 9, 18, 7, 1)),
                ("sleep_without_wake", 2, utc(2026, 9, 18, 10, 0)),
                ("kernel_power_41", 3, utc(2026, 9, 18, 11, 0, 5)),
            ]
        )
        # Exact list: the paired 506/507 in boot 1 is not an anomaly.
        self.assertEqual(found, expected)

        bugchecks = [a for a in anomalies if a["kind"] == "bugcheck"]
        self.assertEqual(len(bugchecks), 1)
        self.assertEqual(bugchecks[0]["bugcheck_code"], "0x0000019c")

    def test_clean_data_no_findings(self):
        noise = self.write_noise(
            [{"provider": DCOM, "event_id": 10016, "reason": NOISE_REASON}]
        )
        events = [
            # Boot 1: clean start and shutdown, a paired sleep/wake, only noise.
            event(EVENTLOG, 6005, 4, "2026-09-18T09:00:00.0000000+02:00"),
            event(DCOM, 10016, 3, "2026-09-18T09:05:00.0000000+02:00"),
            event(KERNEL_POWER, 506, 4, "2026-09-18T10:00:00.0000000+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-18T10:20:00.0000000+02:00"),
            event(DCOM, 10016, 3, "2026-09-18T10:25:00.0000000+02:00"),
            # Level-4 events whose Ids collide with anomaly Ids, from other providers.
            event("Windows Error Reporting", 1001, 4, "2026-09-18T10:40:00.0000000+02:00",
                  log=APPLICATION, properties=["0", "Invented", "Not a bugcheck"]),
            event("Invented-Kernel-Processor-Provider", 41, 4,
                  "2026-09-18T10:45:00.0000000+02:00"),
            event("Invented-PnP-Provider", 506, 4, "2026-09-18T10:50:00.0000000+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-18T12:00:00.0000000+02:00"),
            # Boot 2: clean again, another paired sleep/wake and one noise event.
            event(EVENTLOG, 6005, 4, "2026-09-18T12:05:00.0000000+02:00"),
            event(KERNEL_POWER, 506, 4, "2026-09-18T13:00:00.0000000+02:00"),
            event(KERNEL_POWER, 507, 4, "2026-09-18T13:40:00.0000000+02:00"),
            event(DCOM, 10016, 3, "2026-09-18T14:00:00.0000000+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-18T15:00:00.0000000+02:00"),
        ]

        result = self.events.analyze(events, noise)

        self.assertEqual(result["anomalies"], [])
        self.assertEqual(result["groups"], [])

        # The clean data was actually analysed: noise is present and counted.
        self.assertEqual(len(result["noise"]), 1)
        entry = result["noise"][0]
        self.assertEqual((entry["provider"], entry["event_id"]), (DCOM, 10016))
        self.assertEqual(entry["count"], 3)
        self.assertEqual(entry["reason"], NOISE_REASON)


FIXTURES = Path(__file__).absolute().parent / "fixtures"
BIDI_MARKS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
DEFAULT_NOISE_PAIRS = {
    ("Microsoft-Windows-Kernel-PnP", 219),
    ("Wdf01000", 3),
    ("Win32k", 700),
    ("Win32k", 701),
    (DCOM, 10016),
}


class TestLoad(AnalysisTestCase):
    def temp_file(self, name, data: bytes):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / name
        path.write_bytes(data)
        return path

    def test_single_object_and_bom(self):
        fixture = FIXTURES / "single_event_bom.json"
        raw = fixture.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "fixture must start with a BOM")
        expected = {
            "ProviderName": "Invented-Storage-Provider",
            "Id": 129,
            "Level": 3,
            "LogName": SYSTEM,
            "RecordId": 4711,
            "TimeCreated": "2026-09-18T09:15:30.1234567+02:00",
            "Message": "Reset to device, \u200e\\Device\\RaidPort0, was issued at "
                       "\u200e18.\u200e09.\u200e2026.",
            "Properties": ["\\Device\\RaidPort0", "0"],
        }

        # A single object (ConvertTo-Json with one element), with a BOM.
        self.assertEqual(self.events.load_capture(fixture), [expected])

        # The same object without a BOM.
        no_bom = self.temp_file("no_bom.json", raw[3:])
        self.assertEqual(self.events.load_capture(no_bom), [expected])

        # An array stays a list, in order.
        second = dict(expected, RecordId=4712)
        array = self.temp_file("array.json", json.dumps([expected, second]).encode("utf-8"))
        self.assertEqual(self.events.load_capture(array), [expected, second])

        # An empty file and a JSON null both mean "no events".
        self.assertEqual(self.events.load_capture(self.temp_file("empty.json", b"")), [])
        self.assertEqual(self.events.load_capture(self.temp_file("null.json", b"null")), [])

    def test_merge_deduplicates(self):
        boot = event(EVENTLOG, 6005, 4, "2026-09-18T09:00:00.0000000+02:00")
        crash = event(KERNEL_POWER, 41, 1, "2026-09-18T09:00:10.0000000+02:00")
        error = event("Invented-Disk-Provider", 7, 2, "2026-09-18T09:30:00.0000000+02:00")
        app_error = event("Invented-App-Provider", 1000, 2,
                          "2026-09-18T09:40:00.0000000+02:00", log=APPLICATION)
        # Same RecordId as the System error, but another log: a different event.
        app_error["RecordId"] = error["RecordId"]

        pass_a = [crash, error, app_error]  # levels 1-3
        pass_b = [boot, dict(crash)]        # by Id; the 41 is in both passes

        merged = self.events.merge(pass_a, pass_b)

        addresses = sorted((e["LogName"], e["RecordId"]) for e in merged)
        self.assertEqual(
            addresses,
            sorted((e["LogName"], e["RecordId"]) for e in (boot, crash, error, app_error)),
        )
        self.assertEqual(len(merged), 4)


class TestGrouping(AnalysisTestCase):
    def test_group_fields(self):
        sentence = "The invented driver \u200efailed to \u200fstart its worker thread number {}. "
        message = "".join(sentence.format(n) for n in range(1, 8)).strip()
        clean_message = message.translate({ord(c): None for c in BIDI_MARKS})
        self.assertGreater(len(clean_message), 300)

        events = [
            # Across the DST fall-back: 02:50+02:00 (00:50Z) happened before
            # 02:10+01:00 (01:10Z), although it sorts later as a string.
            event("Invented-Driver", 219, 3, "2026-10-25T02:10:00.0000000+01:00",
                  message=message),
            event("Invented-Driver", 219, 2, "2026-10-25T02:50:00.0000000+02:00",
                  message=message),
            event("Invented-Driver", 219, 3, "2026-10-25T01:30:00.0000000+00:00",
                  message=message),
            # Level 4 events never form groups.
            event(EVENTLOG, 6005, 4, "2026-10-25T00:00:00.0000000+02:00"),
            event(EVENTLOG, 6006, 4, "2026-10-25T05:00:00.0000000+01:00"),
            event(KERNEL_POWER, 506, 4, "2026-10-25T03:00:00.0000000+01:00"),
            event(KERNEL_POWER, 507, 4, "2026-10-25T03:10:00.0000000+01:00"),
        ]

        result = self.events.analyze(events, [])

        self.assertEqual(len(result["groups"]), 1, result["groups"])
        group = result["groups"][0]
        self.assertEqual(group["provider"], "Invented-Driver")
        self.assertEqual(group["event_id"], 219)
        self.assertEqual(group["count"], 3)
        self.assertEqual(group["level"], 2)  # the most severe level in the group
        self.assertEqual(group["log"], SYSTEM)
        self.assertTrue(group["first"].endswith("+00:00"), group["first"])
        self.assertTrue(group["last"].endswith("+00:00"), group["last"])
        self.assertEqual(instant(group["first"]), utc(2026, 10, 25, 0, 50))
        self.assertEqual(instant(group["last"]), utc(2026, 10, 25, 1, 30))

        sample = group["sample"]
        self.assertFalse(any(c in sample for c in BIDI_MARKS), repr(sample))
        self.assertLessEqual(len(sample), 200)
        self.assertGreater(len(sample), 50)
        self.assertTrue(clean_message.startswith(sample), repr(sample))
        self.assertTrue(sample.endswith("."), repr(sample))  # cut at a sentence end


class TestBoots(AnalysisTestCase):
    def test_sessions(self):
        events = [
            # Before the first boot in the window: partial session 0.
            event("Invented-Disk-Provider", 153, 3, "2026-09-18T07:00:00.0000000+02:00"),
            # Boot 1, shut down cleanly.
            event(EVENTLOG, 6005, 4, "2026-09-18T08:00:00.0000000+02:00"),
            event(EVENTLOG, 6006, 4, "2026-09-18T07:00:00.0000000+00:00"),
            # Boot 2: no 6006 before the next 6005. A 6005 from another
            # provider does not start a session.
            event(EVENTLOG, 6005, 4, "2026-09-18T09:05:00.0000000+02:00"),
            event("Invented-Other-Provider", 6005, 4, "2026-09-18T09:30:00.0000000+02:00"),
            # Boot 3 (09:00Z = 11:00+02:00): still running at the end of the window.
            event(EVENTLOG, 6005, 4, "2026-09-18T09:00:00.0000000+00:00"),
            event("Invented-Disk-Provider", 153, 3, "2026-09-18T12:00:00.0000000+02:00"),
        ]
        events.reverse()

        boots = self.events.analyze(events, [])["boots"]

        def shape(b):
            start = instant(b["start"]) if b["start"] else None
            end = instant(b["end"]) if b["end"] else None
            return (b["index"], start, end, b["clean_shutdown"])

        self.assertEqual(
            [shape(b) for b in boots],
            [
                (0, None, None, False),
                (1, utc(2026, 9, 18, 6, 0), utc(2026, 9, 18, 7, 0), True),
                (2, utc(2026, 9, 18, 7, 5), None, False),
                (3, utc(2026, 9, 18, 9, 0), None, None),
            ],
        )
        for b in boots:
            for key in ("start", "end"):
                if b[key]:
                    self.assertTrue(b[key].endswith("+00:00"), b[key])

        # No events before the first boot: no session 0.
        boots = self.events.analyze(
            [
                event(EVENTLOG, 6005, 4, "2026-09-18T08:00:00.0000000+02:00"),
                event(EVENTLOG, 6006, 4, "2026-09-18T09:00:00.0000000+02:00"),
            ],
            [],
        )["boots"]
        self.assertEqual([(b["index"], b["clean_shutdown"]) for b in boots], [(1, True)])


if __name__ == "__main__":
    unittest.main()

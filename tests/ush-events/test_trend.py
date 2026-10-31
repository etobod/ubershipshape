"""Behaviour tests for the per-group trend in skills/ush-events/scripts/events.py.

Public interface under test:
- ``analyze(events, noise, window=None, coverage=None, trend_rule=None) -> dict``
  ``window`` is a (start, end) pair of aware datetimes, ``coverage`` maps a log name to its
  ``coverage_start`` (or None), ``trend_rule`` is the loaded
  ``skills/ush-events/data/trend.json``. Each group gains ``first_half``, ``second_half`` and
  ``trend`` (rising / falling / stable / too_few / unknown).
- ``main(argv=None, run_ps=None, now=None, trend_file=None) -> int``

Thresholds come from the shipped data file, never from this test. All events are invented;
PowerShell is replaced by a fake and nothing is read from the machine.
"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.skill_loader import REPO_ROOT, load_script


def NO_DUMPS():
    """Fake read_dumps: no memory dumps (the machine is never read)."""
    return {"status": "empty", "reason": None, "settings": None, "files": []}

TREND_FILE = REPO_ROOT / "skills" / "ush-events" / "data" / "trend.json"

SYSTEM = "System"
APPLICATION = "Application"

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
DAYS = 30
START = NOW - timedelta(days=DAYS)
WINDOW = (START, NOW)
MIDPOINT = START + timedelta(days=DAYS / 2)  # 2026-09-13T12:00:00Z

_record_ids = iter(range(5000, 100000))


def stamp(moment):
    """Format an aware datetime like Get-WinEvent's TimeCreated projection."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000+00:00")


def event(provider, event_id, moment, log=SYSTEM, level=2):
    """One level 1-3 event in the agreed projection."""
    return {
        "ProviderName": provider,
        "Id": event_id,
        "Level": level,
        "LogName": log,
        "RecordId": next(_record_ids),
        "TimeCreated": stamp(moment),
        "Message": f"Invented message for {provider} {event_id}.",
        "Properties": [],
    }


def spread(provider, event_id, count, begin, end, log=SYSTEM):
    """``count`` events evenly spread over [begin, end)."""
    step = (end - begin) / count
    return [event(provider, event_id, begin + step * i + step / 2, log=log)
            for i in range(count)]


def first_half(provider, event_id, count, log=SYSTEM):
    return spread(provider, event_id, count, START, MIDPOINT, log=log)


def second_half(provider, event_id, count, log=SYSTEM):
    return spread(provider, event_id, count, MIDPOINT, NOW, log=log)


class TrendTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")
        cls.rule = json.loads(TREND_FILE.read_text(encoding="utf-8-sig"))

    # Preconditions, computed from the data file: they state which rule the invented
    # counts are meant to hit, so a change of thresholds shows up here, not as a riddle.
    def is_rising(self, first, second):
        return (second >= self.rule["factor"] * first
                and second - first >= self.rule["min_delta"])

    def is_falling(self, first, second):
        return (first >= self.rule["factor"] * second
                and first - second >= self.rule["min_delta"])

    def analyze(self, events, coverage=None):
        if coverage is None:
            coverage = {SYSTEM: None, APPLICATION: None}
        return self.events.analyze(events, [], window=WINDOW, coverage=coverage,
                                   trend_rule=self.rule)

    def group(self, result, provider, event_id):
        found = [g for g in result["groups"]
                 if (g["provider"], g["event_id"]) == (provider, event_id)]
        self.assertEqual(len(found), 1, result["groups"])
        return found[0]


class TestTrend(TrendTestCase):
    def test_new_errors_are_rising(self):
        self.assertGreaterEqual(5, self.rule["min_count"])
        self.assertTrue(self.is_rising(0, 5), self.rule)

        result = self.analyze(second_half("Invented-New-Driver", 17, 5))
        group = self.group(result, "Invented-New-Driver", 17)

        self.assertEqual(group["count"], 5)
        self.assertEqual(group["first_half"], 0)
        self.assertEqual(group["second_half"], 5)
        self.assertEqual(group["trend"], "rising")

    def test_fewer_errors_are_falling(self):
        self.assertGreaterEqual(8, self.rule["min_count"])
        self.assertTrue(self.is_falling(6, 2), self.rule)

        events = (first_half("Invented-Fading-Service", 7031, 6)
                  + second_half("Invented-Fading-Service", 7031, 2))
        group = self.group(self.analyze(events), "Invented-Fading-Service", 7031)

        self.assertEqual(group["first_half"], 6)
        self.assertEqual(group["second_half"], 2)
        self.assertEqual(group["trend"], "falling")

    def test_even_rate_is_stable(self):
        # Clean data: a steady trickle with a little more in the second half is no alarm.
        self.assertGreaterEqual(12, self.rule["min_count"])
        self.assertFalse(self.is_rising(5, 7), self.rule)
        self.assertFalse(self.is_falling(5, 7), self.rule)

        events = (first_half("Invented-Steady-App", 1000, 5, log=APPLICATION)
                  + second_half("Invented-Steady-App", 1000, 7, log=APPLICATION))
        group = self.group(self.analyze(events), "Invented-Steady-App", 1000)

        self.assertEqual(group["first_half"], 5)
        self.assertEqual(group["second_half"], 7)
        self.assertEqual(group["trend"], "stable")
        self.assertNotEqual(group["trend"], "rising")

    def test_few_events_and_midpoint(self):
        self.assertLess(3, self.rule["min_count"])

        few = [
            event("Invented-Rare-Driver", 51, MIDPOINT),  # exactly at the midpoint
            event("Invented-Rare-Driver", 51, MIDPOINT + timedelta(days=3)),
            event("Invented-Rare-Driver", 51, NOW - timedelta(hours=1)),
        ]
        # The other side of the boundary: one second before the midpoint is the first half.
        before = [event("Invented-Edge-Driver", 52, MIDPOINT - timedelta(seconds=1))]

        result = self.analyze(few + before)

        rare = self.group(result, "Invented-Rare-Driver", 51)
        self.assertEqual(rare["count"], 3)
        self.assertEqual(rare["first_half"], 0)
        self.assertEqual(rare["second_half"], 3)
        self.assertEqual(rare["trend"], "too_few")

        edge = self.group(result, "Invented-Edge-Driver", 52)
        self.assertEqual(edge["first_half"], 1)
        self.assertEqual(edge["second_half"], 0)
        self.assertEqual(edge["trend"], "too_few")

        # The midpoint event alone still counts in the second half.
        alone = self.group(self.analyze([event("Invented-Mid-Driver", 53, MIDPOINT)]),
                           "Invented-Mid-Driver", 53)
        self.assertEqual((alone["first_half"], alone["second_half"]), (0, 1))

    def test_partial_coverage_is_unknown(self):
        self.assertGreaterEqual(5, self.rule["min_count"])
        self.assertTrue(self.is_rising(0, 5), self.rule)

        # The Application log reaches back only to after the window start: its halves
        # are not comparable. The System log covers the whole window.
        coverage = {SYSTEM: None, APPLICATION: stamp(START + timedelta(days=10))}
        events = (second_half("Invented-Short-Log-App", 1000, 5, log=APPLICATION)
                  + second_half("Invented-Full-Log-Driver", 17, 5, log=SYSTEM))

        result = self.analyze(events, coverage=coverage)

        short = self.group(result, "Invented-Short-Log-App", 1000)
        self.assertEqual(short["trend"], "unknown")
        self.assertEqual(short["first_half"], 0)
        self.assertEqual(short["second_half"], 5)

        # Same counts from a fully covered log: the rule applies as usual.
        full = self.group(result, "Invented-Full-Log-Driver", 17)
        self.assertEqual(full["trend"], "rising")


NO_MATCH_STDERR = (
    "Get-WinEvent : No events were found that match the specified selection criteria.\r\n"
    "    + FullyQualifiedErrorId : NoMatchingEventsFound,"
    "Microsoft.PowerShell.Commands.GetWinEventCommand\r\n"
)


class FakePowerShell:
    """Stands in for run_ps; answers every job with invented data, never PowerShell."""

    def __init__(self):
        old = "2026-06-01T00:00:00.0000000+00:00"
        self.responses = {
            "oldest:System": [dict(event("Invented-Oldest", 1, START, level=4),
                                   TimeCreated=old)],
            "oldest:Application": [dict(event("Invented-Oldest", 1, START, log=APPLICATION,
                                              level=4), TimeCreated=old)],
            "A:System": second_half("Invented-Disk", 7, 5),
            "A:Application": second_half("Invented-App", 1000, 1, log=APPLICATION),
            "B:System": [event("EventLog", 6005, START + timedelta(days=1), level=4)],
            "R:metrics": [],
            "R:records": [],
        }
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append(job)
        response = self.responses.get(job)
        if response is None:
            return 1, NO_MATCH_STDERR
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(response), encoding="utf-8")
        return 0, ""


class TestTrendData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def test_incomplete_data_file_fails(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        data_dir = root / "ush-data"

        shipped = json.loads(TREND_FILE.read_text(encoding="utf-8-sig"))
        self.assertIn("factor", shipped)
        broken = {key: value for key, value in shipped.items() if key != "factor"}
        broken_file = root / "trend.json"
        broken_file.write_text(json.dumps(broken), encoding="utf-8")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.events.main(["--data-dir", str(data_dir)], run_ps=FakePowerShell(),
                                    now=NOW, trend_file=broken_file,
                                    read_dumps=NO_DUMPS)

        self.assertEqual(code, 1, out.getvalue()[:300])
        self.assertTrue(err.getvalue().strip(), "expected a message on stderr")
        self.assertNotIn("summary_file", out.getvalue())
        written = sorted(str(p) for p in root.rglob("*.summary.json"))
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()

"""Behaviour tests for the Reliability Monitor part of skills/ush-events/scripts/events.py
and for r<n> ids in skills/ush-events/scripts/check_report.py.

Public interface under test:
- ``events.main(argv=None, run_ps=None, now=None) -> int``
- ``run_ps(job, script, out_path) -> (exit_code, stderr)`` is replaced by a fake that
  writes invented JSON to ``out_path``. The WMI jobs are ``R:metrics`` and ``R:records``.
- ``check_report.main(argv) -> int``

Every measurement and record here is invented; PowerShell is never started and nothing
is read from the machine. All output goes to a temporary directory.
"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.skill_loader import load_script


def NO_DUMPS():
    """Fake read_dumps: no memory dumps (the machine is never read)."""
    return {"status": "empty", "reason": None, "settings": None, "files": []}

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
DAYS = 30

METRICS = "R:metrics"
RECORDS = "R:records"

DENIED_TEXT = "Invented access denied to the reliability provider."
DENIED_STDERR = (
    f"Get-CimInstance : {DENIED_TEXT}\r\n"
    "At line:1 char:1\r\n"
    "    + CategoryInfo          : PermissionDenied: (:) [Get-CimInstance], CimException\r\n"
    "    + FullyQualifiedErrorId : HRESULT 0x80041003,"
    "Microsoft.Management.Infrastructure.CimCmdlets.GetCimInstanceCommand\r\n"
)
NO_MATCH_STDERR = (
    "Get-WinEvent : No events were found that match the specified selection criteria.\r\n"
    "    + FullyQualifiedErrorId : NoMatchingEventsFound,"
    "Microsoft.PowerShell.Commands.GetWinEventCommand\r\n"
)


def event(provider, event_id, level, log, record_id, time):
    """One event in the Get-WinEvent projection."""
    return {"ProviderName": provider, "Id": event_id, "Level": level, "LogName": log,
            "RecordId": record_id, "TimeCreated": time, "Message": "Invented message.",
            "Properties": []}


OLD_SYSTEM = event("Invented-Oldest", 1, 4, "System", 1, "2026-06-01T00:00:00.0000000+00:00")
OLD_APPLICATION = event("Invented-Oldest", 1, 4, "Application", 1,
                        "2026-06-01T00:00:00.0000000+00:00")


def metric(time, index):
    """One Win32_ReliabilityStabilityMetrics row in the planned projection."""
    return {"TimeGenerated": time, "SystemStabilityIndex": index}


def record(time, source, event_id, product):
    """One Win32_ReliabilityRecords row in the planned projection."""
    return {"TimeGenerated": time, "SourceName": source, "EventIdentifier": event_id,
            "ProductName": product}


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


class FakePowerShell:
    """Stands in for run_ps.

    Every event log job reads one invented event, so nothing but the WMI jobs can add a
    ``not_checked`` entry. ``R:*`` jobs answer an empty list unless told otherwise.
    A response is a list (written as the result file, exit 0) or a string (stderr, exit 1).
    """

    def __init__(self, responses=None):
        self.responses = {
            "oldest:System": [OLD_SYSTEM],
            "oldest:Application": [OLD_APPLICATION],
            "A:System": [event("Invented-Disk", 7, 2, "System", 10,
                               "2026-09-20T10:00:00.0000000+00:00")],
            "A:Application": [event("Invented-App", 1000, 2, "Application", 11,
                                    "2026-09-20T11:00:00.0000000+00:00")],
            "B:System": [event("EventLog", 6005, 4, "System", 12,
                               "2026-09-20T09:00:00.0000000+00:00")],
            METRICS: [],
            RECORDS: [],
        }
        self.responses.update(responses or {})
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        response = self.responses.get(job)
        if response is None:
            return 1, NO_MATCH_STDERR
        if isinstance(response, str):
            return 1, response
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Windows PowerShell 5.1 would write a BOM; the planned script writes none.
        out_path.write_text(json.dumps(response), encoding="utf-8")
        return 0, ""


class ReliabilityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def collect(self, fake, data_dir=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.events.main(["--data-dir", str(data_dir or self.data_dir())],
                                    run_ps=fake, now=NOW, read_dumps=NO_DUMPS)
        self.assertEqual(code, 0, out.getvalue()[:300])
        try:
            summary = json.loads(out.getvalue())
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {out.getvalue()[:300]!r}")
        return summary

    def reliability(self, summary):
        self.assertIn("reliability", summary)
        self.assertIsInstance(summary["reliability"], dict, summary["reliability"])
        return summary["reliability"]

    def records(self, summary):
        self.assertIn("reliability_records", summary)
        self.assertIsInstance(summary["reliability_records"], list,
                              summary["reliability_records"])
        return summary["reliability_records"]


class TestStability(ReliabilityTestCase):
    def test_daily_index_is_last_of_day(self):
        # Rows arrive out of order; the day's value is the one with the latest time.
        two_days = [
            metric("2026-09-20T23:30:00.0000000Z", 6.9),
            metric("2026-09-20T06:00:00.0000000Z", 7.5),
            metric("2026-09-21T10:00:00.0000000Z", 8.0),
            metric("2026-09-20T12:00:00.0000000Z", 6.2),
        ]
        rel = self.reliability(self.collect(FakePowerShell({METRICS: two_days})))

        self.assertEqual(rel["status"], "read", rel)
        self.assertEqual(rel["daily"], [{"date": "2026-09-20", "index": 6.9},
                                        {"date": "2026-09-21", "index": 8.0}])
        self.assertEqual(rel["lowest"], {"date": "2026-09-20", "index": 6.9})
        self.assertEqual(rel["drops"], [])

        # A third day lower than the second: one drop, compared with the previous day.
        three_days = [*two_days, metric("2026-09-22T09:00:00.0000000Z", 7.1)]
        rel = self.reliability(self.collect(FakePowerShell({METRICS: three_days})))

        self.assertEqual([d["index"] for d in rel["daily"]], [6.9, 8.0, 7.1])
        self.assertEqual(rel["lowest"], {"date": "2026-09-20", "index": 6.9})
        self.assertEqual(rel["drops"], [{"date": "2026-09-22", "index": 7.1,
                                         "previous_index": 8.0}])

    def test_unreadable_is_not_empty(self):
        records = [record("2026-09-20T10:00:00.0000000Z", "Invented-Source", 1000,
                          "invented.exe")]

        # Unreadable metrics query.
        summary = self.collect(FakePowerShell({METRICS: DENIED_STDERR, RECORDS: records}))
        rel = self.reliability(summary)
        self.assertEqual(rel["status"], "unreadable", rel)
        self.assertIsInstance(rel["reason"], str)
        self.assertIn(DENIED_TEXT, rel["reason"])
        self.assertIsNone(rel["daily"])
        not_checked = summary["not_checked"]
        named = [item for item in not_checked if DENIED_TEXT in (item.get("reason") or "")]
        self.assertEqual(len(named), 1, not_checked)

        # Empty metrics query: read, nothing there.
        summary = self.collect(FakePowerShell({METRICS: [], RECORDS: records}))
        rel = self.reliability(summary)
        self.assertEqual(rel["status"], "empty", rel)
        self.assertEqual(rel["daily"], [])
        self.assertEqual(summary["not_checked"], [])


class TestRecords(ReliabilityTestCase):
    def test_records_grouped_with_ids(self):
        app = ("Application Error", 1000)
        wu = ("WindowsUpdateClient", 19)
        rows = [
            record("2026-09-12T08:00:00.0000000Z", *app, "invented-old.exe"),
            record("2026-09-15T08:00:00.0000000Z", *wu, "Invented Update A"),
            record("2026-09-25T18:30:00.0000000Z", *app, "invented-new.exe"),
            record("2026-09-10T08:00:00.0000000Z", *app, "invented-first.exe"),
            record("2026-09-24T08:00:00.0000000Z", *wu, "Invented Update B"),
            record("2026-09-20T08:00:00.0000000Z", *app, "invented-mid.exe"),
            record("2026-09-21T08:00:00.0000000Z", *app, "invented-mid.exe"),
        ]
        groups = self.records(self.collect(FakePowerShell({RECORDS: rows})))

        self.assertEqual(
            [(g.get("id"), g.get("source"), g.get("event_id"), g.get("count")) for g in groups],
            [("r1", "Application Error", 1000, 5), ("r2", "WindowsUpdateClient", 19, 2)],
        )
        r1, r2 = groups
        self.assertEqual(instant(r1["first"]), instant("2026-09-10T08:00:00Z"))
        self.assertEqual(instant(r1["last"]), instant("2026-09-25T18:30:00Z"))
        self.assertEqual(r1["product"], "invented-new.exe")
        self.assertEqual(instant(r2["first"]), instant("2026-09-15T08:00:00Z"))
        self.assertEqual(instant(r2["last"]), instant("2026-09-24T08:00:00Z"))
        self.assertEqual(r2["product"], "Invented Update B")

    def test_outside_window_is_dropped(self):
        start = NOW - timedelta(days=DAYS)
        before = (start - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        before_day = (start - timedelta(days=3)).strftime("%Y-%m-%d")
        fake = FakePowerShell({
            METRICS: [metric(before, 1.5), metric("2026-09-20T10:00:00.0000000Z", 9.5)],
            RECORDS: [
                record(before, "Invented-Old-Source", 1000, "invented-old.exe"),
                record("2026-09-20T10:00:00.0000000Z", "Invented-New-Source", 1000,
                       "invented-new.exe"),
            ],
        })
        summary = self.collect(fake)
        self.assertEqual(instant(summary["window"]["start"]), start)

        rel = self.reliability(summary)
        self.assertEqual(rel["daily"], [{"date": "2026-09-20", "index": 9.5}])
        self.assertNotIn(before_day, [d["date"] for d in rel["daily"]])

        groups = self.records(summary)
        self.assertEqual([(g["source"], g["count"]) for g in groups],
                         [("Invented-New-Source", 1)])
        self.assertNotIn("Invented-Old-Source", json.dumps(groups))


NOT_CHECKED = ["<!-- ush:not-checked -->", "## Not checked", "Nothing."]


class TestIds(ReliabilityTestCase):
    def test_detail_and_checker_know_r_ids(self):
        # --detail r1 with --detail-file prints that run's record group r1.
        data_dir = self.data_dir()
        rows = [
            record("2026-09-20T10:00:00.0000000Z", "Application Error", 1000, "invented.exe"),
            record("2026-09-21T10:00:00.0000000Z", "Application Error", 1000, "invented.exe"),
            record("2026-09-22T10:00:00.0000000Z", "WindowsUpdateClient", 19, "Invented KB"),
        ]
        summary = self.collect(FakePowerShell({RECORDS: rows}), data_dir=data_dir)
        r1 = self.records(summary)[0]
        self.assertEqual(r1["id"], "r1")

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.events.main(["--data-dir", str(data_dir), "--detail", "r1",
                                     "--detail-file", summary["detail_file"]])
        self.assertEqual(code, 0, out.getvalue()[:300])
        self.assertEqual(json.loads(out.getvalue()), r1)

        # check_report knows r<n>: seven groups, no 7 in any other value.
        check = load_script("ush-common", "check_report")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        (root / "reports").mkdir()
        summary_file = root / "summary.json"
        names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf"]
        counts = [10, 9, 8, 6, 5, 4, 3]
        event_ids = [1000, 19, 1001, 1002, 1003, 1004, 1005]
        records = [
            {"id": f"r{i}", "source": f"Invented-{name}", "event_id": event_id,
             "count": n, "first": "2026-09-20T10:00:00+00:00",
             "last": "2026-09-21T10:00:00+00:00", "product": f"invented-{name.lower()}.exe"}
            for i, (name, event_id, n) in enumerate(zip(names, event_ids, counts), start=1)
        ]
        data = {"groups": [], "truncated": 0, "reliability_records": records}
        # Only the ids carry a 7 (the temporary paths below are not readings).
        self.assertNotIn("7", json.dumps(data).replace('"r7"', ""))
        data.update({"skill": "ush-events", "summary_file": str(summary_file),
                     "detail_file": str(root / "detail.json")})
        summary_file.write_text(json.dumps(data), encoding="utf-8")

        report = root / "reports" / "events-2026-09-28-1200.md"
        report.write_text("\n".join([f"<!-- ush:summary {summary_file} -->",
                                     "Reliability record group r7: Invented-Golf.",
                                     *NOT_CHECKED]) + "\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = check.main([str(report)])
        self.assertEqual(code, 0, out.getvalue())


class TestScripts(ReliabilityTestCase):
    def test_wmi_job_script_shape(self):
        data_dir = self.data_dir()
        fake = FakePowerShell()
        self.collect(fake, data_dir=data_dir)

        scripts = {job: (script, out_path) for job, script, out_path in fake.calls}
        self.assertIn(METRICS, scripts, sorted(scripts))
        self.assertIn(RECORDS, scripts, sorted(scripts))
        work = (data_dir / "work").resolve()

        cases = ((METRICS, "Win32_ReliabilityStabilityMetrics", "Win32_ReliabilityRecords"),
                 (RECORDS, "Win32_ReliabilityRecords", "Win32_ReliabilityStabilityMetrics"))
        for job, wmi_class, other_class in cases:
            script, out_path = scripts[job]
            self.assertIn(f"Get-CimInstance {wmi_class}", script, job)
            self.assertNotIn(other_class, script, job)
            self.assertIn("TimeGenerated", script, job)
            # Data travels only through a BOM-less UTF-8 file at an absolute path in work/.
            self.assertIn("WriteAllText", script, job)
            self.assertRegex(script, r"UTF8Encoding(\]::new)?\(\$false\)", job)
            self.assertNotIn("Out-File", script, job)
            self.assertTrue(out_path.is_absolute(), out_path)
            self.assertEqual(out_path.parent.resolve(), work, out_path)
            self.assertIn(str(out_path), script, job)


if __name__ == "__main__":
    unittest.main()

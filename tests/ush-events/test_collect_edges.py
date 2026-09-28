"""Edge cases of the collection found in review (fake PowerShell, invented data)."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
START = NOW - timedelta(days=30)


def no_matches(job, script, out_path):
    return 1, "Get-WinEvent : No events were found. NoMatchingEventsFound"


def invented(provider, event_id, level, log, record_id, time):
    return {"ProviderName": provider, "Id": event_id, "Level": level, "LogName": log,
            "RecordId": record_id, "TimeCreated": time, "Message": "Invented.",
            "Properties": []}


def fake(answers):
    """run_ps that writes answers[job] (a list of events) or reports its error."""
    def run_ps(job, script, out_path):
        answer = answers.get(job)
        if answer is None:
            return no_matches(job, script, out_path)
        if isinstance(answer, str):
            return 1, answer
        out_path.write_text(json.dumps(answer), encoding="utf-8")
        return 0, ""
    return run_ps


OLD = invented("Invented-Old", 1, 4, "System", 1, "2026-06-01T00:00:00+00:00")


class TestEmptyLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def test_log_without_records_covers_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources, _, not_checked = self.events.collect(
                no_matches, Path(tmp).absolute() / "work", "20260928-120000", START, NOW)
        for source in sources:
            self.assertEqual(source["status"], "empty")
            self.assertEqual(source["coverage_start"], NOW.isoformat())
        gaps = [item for item in not_checked if "from" in item]
        self.assertEqual(sorted(g["what"].split()[0] for g in gaps), ["Application", "System"])
        for gap in gaps:
            self.assertEqual((gap["from"], gap["to"]), (START.isoformat(), NOW.isoformat()))

    def test_log_filled_after_the_oldest_query_is_not_called_empty(self):
        late = invented("Invented-Disk", 7, 2, "Application", 50, "2026-09-28T11:59:00+00:00")
        run_ps = fake({"oldest:System": [OLD], "A:Application": [late]})
        with tempfile.TemporaryDirectory() as tmp:
            sources, _, not_checked = self.events.collect(
                run_ps, Path(tmp).absolute() / "work", "20260928-120000", START, NOW)
        app = next(s for s in sources if s["log"] == "Application")
        self.assertEqual((app["status"], app["coverage_start"]),
                         ("read", "2026-09-28T11:59:00+00:00"))
        self.assertFalse(any("no records at all" in n["what"] for n in not_checked))


class TestSummaryEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def run_main(self, answers):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "stdout.txt"
            with open(out, "w", encoding="utf-8") as handle, contextlib.redirect_stdout(handle):
                code = self.events.main(["--data-dir", str(Path(tmp).absolute())],
                                        run_ps=fake(answers), now=NOW)
            self.assertEqual(code, 0)
            return json.loads(out.read_text(encoding="utf-8"))

    def test_unreadable_pass_b_makes_boots_unknown(self):
        kp41 = invented("Microsoft-Windows-Kernel-Power", 41, 1, "System", 10,
                        "2026-09-20T10:00:00+00:00")
        summary = self.run_main({"oldest:System": [OLD], "oldest:Application": [OLD],
                                 "A:System": [kp41], "B:System": "Access denied"})
        self.assertIsNone(summary["boots"])
        self.assertEqual([(a["kind"], a["boot"]) for a in summary["anomalies"]],
                         [("kernel_power_41", None)])

    def test_readable_pass_b_keeps_boots(self):
        boot = invented("EventLog", 6005, 4, "System", 11, "2026-09-20T09:00:00+00:00")
        summary = self.run_main({"oldest:System": [OLD], "oldest:Application": [OLD],
                                 "B:System": [boot]})
        self.assertEqual([b["id"] for b in summary["boots"]], ["b1"])

    def test_record_without_time_is_listed_not_fatal(self):
        good = invented("Invented-Disk", 7, 2, "System", 30, "2026-09-20T10:00:00+00:00")
        timeless = invented("Invented-Disk", 7, 2, "System", 31, None)
        summary = self.run_main({"oldest:System": [OLD], "oldest:Application": [OLD],
                                 "A:System": [good, timeless]})
        self.assertEqual([g["count"] for g in summary["groups"]], [1])
        self.assertTrue(any("TimeCreated" in n["reason"] for n in summary["not_checked"]))

    def test_projection_guards_a_null_time(self):
        self.assertRegex(self.events.PROJECTION, r"if\s*\(\$e\.TimeCreated\)")

    def test_same_provider_and_id_in_two_logs_are_two_groups(self):
        sys_ev = invented("Invented-Both", 9, 2, "System", 20, "2026-09-20T10:00:00+00:00")
        app_ev = invented("Invented-Both", 9, 2, "Application", 20, "2026-09-20T11:00:00+00:00")
        summary = self.run_main({"oldest:System": [OLD], "oldest:Application": [OLD],
                                 "A:System": [sys_ev], "A:Application": [app_ev]})
        self.assertEqual(sorted((g["log"], g["count"]) for g in summary["groups"]),
                         [("Application", 1), ("System", 1)])


class TestDetailFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def test_detail_file_option_reads_that_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp).absolute() / "work"
            work.mkdir()
            older = work / "events-20260927-120000.detail.json"
            older.write_text(json.dumps({"groups": [{"id": "g1", "count": 11}]}),
                             encoding="utf-8")
            (work / "events-20260928-120000.detail.json").write_text(
                json.dumps({"groups": [{"id": "g1", "count": 22}]}), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.events.main(["--data-dir", tmp, "--detail", "g1",
                                         "--detail-file", str(older)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["count"], 11)


if __name__ == "__main__":
    unittest.main()

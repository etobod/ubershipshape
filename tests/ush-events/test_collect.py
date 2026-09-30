"""Behaviour tests for collection, the summary contract and the CLI of
skills/ush-events/scripts/events.py.

Public interface under test:
- ``main(argv=None, run_ps=None, now=None) -> int``
- ``run_ps(job, script, out_path) -> (exit_code, stderr)`` is replaced by a fake
  that simulates PowerShell by writing a JSON file to ``out_path`` (or not).

Every event is invented here; nothing is read from the machine and PowerShell is
never started. All output goes to a temporary directory passed as ``--data-dir``.
"""

import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script, script_path


def NO_DUMPS():
    """Fake read_dumps: no memory dumps (the machine is never read)."""
    return {"status": "empty", "reason": None, "settings": None, "files": []}

SYSTEM = "System"
APPLICATION = "Application"

EVENTLOG = "EventLog"
KERNEL_POWER = "Microsoft-Windows-Kernel-Power"
WER_SYSTEM = "Microsoft-Windows-WER-SystemErrorReporting"

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
DAYS = 30

# The oldest record of each log, well before the window: no coverage gap.
OLD_TIME = "2026-06-01T00:00:00.0000000+02:00"

NO_MATCH_STDERR = (
    "Get-WinEvent : No events were found that match the specified selection criteria.\r\n"
    "At line:1 char:1\r\n"
    "    + CategoryInfo          : ObjectNotFound: (:) [Get-WinEvent], Exception\r\n"
    "    + FullyQualifiedErrorId : NoMatchingEventsFound,"
    "Microsoft.PowerShell.Commands.GetWinEventCommand\r\n"
)
DENIED_TEXT = "Attempted to perform an invented unauthorized operation."
DENIED_STDERR = (
    f"Get-WinEvent : {DENIED_TEXT}\r\n"
    "At line:1 char:1\r\n"
    "    + CategoryInfo          : NotSpecified: (:) [Get-WinEvent], UnauthorizedAccessException\r\n"
    "    + FullyQualifiedErrorId : System.UnauthorizedAccessException,"
    "Microsoft.PowerShell.Commands.GetWinEventCommand\r\n"
)

CONTRACT_FIELDS = {
    "schema_version",
    "skill",
    "generated_at",
    "window",
    "sources",
    "groups",
    "noise",
    "boots",
    "anomalies",
    "not_checked",
    "summary_file",
    "detail_file",
    "truncated",
}
SOURCE_FIELDS = {
    "log",
    "pass",
    "status",
    "reason",
    "event_count",
    "log_oldest_record",
    "coverage_start",
}

_record_ids = count(5000)


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


def ps_time(local, offset="+02:00"):
    """Format a naive local datetime the way the projection carries TimeCreated."""
    return local.strftime("%Y-%m-%dT%H:%M:%S.0000000") + offset


def bugcheck(time, code):
    prop = (f"{code} (0x0000000000000050, 0xffffc10bd6c1f040, "
            "0x0000000000000000, 0x0000000000000000)")
    return event(WER_SYSTEM, 1001, 2, time,
                 properties=[prop, "C:\\Windows\\Minidump\\invented.dmp", "00000-00000"])


def oldest(log, time=OLD_TIME):
    return event("Invented-Oldest-Provider", 1, 4, time, log=log)


def instant(text):
    """Parse an ISO 8601 string to an aware datetime in UTC."""
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def ok(payload):
    """PowerShell wrote its result and exited 0."""
    return ("ok", payload)


NO_MATCH = ("fail", 1, NO_MATCH_STDERR, None)


def failure(stderr, code=1, stale=None):
    """PowerShell failed; ``stale`` is a leftover file already sitting at out_path."""
    return ("fail", code, stderr, stale)


class FakePowerShell:
    """Stands in for run_ps. Unknown jobs answer 'no matching events'."""

    def __init__(self, responses=None):
        self.responses = {
            "oldest:System": ok(oldest(SYSTEM)),
            "oldest:Application": ok(oldest(APPLICATION)),
            "R:metrics": ok([]),
            "R:records": ok([]),
        }
        self.responses.update(responses or {})
        self.calls = []

    @staticmethod
    def _write(out_path, payload):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Windows PowerShell 5.1 writes UTF-8 with a BOM.
        out_path.write_text(json.dumps(payload), encoding="utf-8-sig")

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        response = self.responses.get(job, NO_MATCH)
        if response[0] == "ok":
            self._write(out_path, response[1])
            return 0, ""
        _, code, stderr, stale = response
        if stale is not None:
            self._write(out_path, stale)
        return code, stderr


class CollectTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def run_main(self, data_dir, fake, now=NOW, extra=()):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.events.main(
                ["--data-dir", str(data_dir), *extra], run_ps=fake, now=now,
                read_dumps=NO_DUMPS,
            )
        return code, out.getvalue()

    def parse(self, stdout):
        try:
            summary = json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def collect(self, fake, data_dir=None, now=NOW):
        """Run a collection and return the parsed summary (exit code must be 0)."""
        code, stdout = self.run_main(data_dir or self.data_dir(), fake, now=now)
        self.assertEqual(code, 0, stdout[:300])
        return self.parse(stdout)

    def source(self, summary, log, pass_):
        self.assertIsInstance(summary.get("sources"), list, summary)
        matches = [
            s for s in summary["sources"] if s.get("log") == log and s.get("pass") == pass_
        ]
        self.assertEqual(len(matches), 1, f"source {log}/{pass_}: {summary['sources']}")
        return matches[0]

    def list_field(self, summary, key):
        self.assertIn(key, summary)
        self.assertIsInstance(summary[key], list, summary[key])
        return summary[key]


class TestCollect(CollectTestCase):
    def test_empty_vs_unreadable(self):
        stale_system = [
            event("Invented-Stale-Provider", 11, 2, "2026-09-20T10:00:00.0000000+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-20T10:05:00.0000000+02:00"),
        ]
        stale_application = [
            event("Invented-Stale-App-Provider", 1000, 2,
                  "2026-09-20T11:00:00.0000000+02:00", log=APPLICATION),
        ]
        fake = FakePowerShell({
            # No matches, but a leftover file from an earlier run sits at out_path.
            "A:System": failure(NO_MATCH_STDERR, stale=stale_system),
            # Another error, again with a leftover file.
            "A:Application": failure(DENIED_STDERR, stale=stale_application),
            "B:System": ok([event(EVENTLOG, 6005, 4, "2026-09-20T09:00:00.0000000+02:00")]),
        })

        summary = self.collect(fake)

        empty = self.source(summary, SYSTEM, "A")
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["event_count"], 0)

        unreadable = self.source(summary, APPLICATION, "A")
        self.assertEqual(unreadable["status"], "unreadable")
        self.assertIsInstance(unreadable["reason"], str)
        self.assertIn(DENIED_TEXT, unreadable["reason"])
        self.assertEqual(unreadable["event_count"], 0)

        read = self.source(summary, SYSTEM, "B")
        self.assertEqual(read["status"], "read")
        self.assertEqual(read["event_count"], 1)

        # The stale files were never read: nothing from them in any section.
        self.assertEqual(self.list_field(summary, "groups"), [])
        self.assertEqual(self.list_field(summary, "noise"), [])
        self.assertEqual(self.list_field(summary, "anomalies"), [])
        self.assertNotIn("Invented-Stale", json.dumps(summary))

    def test_degradation_not_checked(self):
        # One log unreadable: the summary still comes from the others.
        fake = FakePowerShell({
            "A:System": ok([
                event("Invented-Disk-Provider", 7, 2, "2026-09-20T10:00:00.0000000+02:00"),
                event("Invented-Disk-Provider", 7, 2, "2026-09-21T10:00:00.0000000+02:00"),
            ]),
            "A:Application": failure(DENIED_STDERR),
            "B:System": ok([event(EVENTLOG, 6005, 4, "2026-09-20T09:00:00.0000000+02:00")]),
        })

        summary = self.collect(fake)

        system = self.source(summary, SYSTEM, "A")
        self.assertEqual(system["status"], "read")
        self.assertEqual(system["event_count"], 2)
        groups = self.list_field(summary, "groups")
        self.assertEqual(
            [(g.get("provider"), g.get("event_id"), g.get("count")) for g in groups],
            [("Invented-Disk-Provider", 7, 2)],
        )
        self.assertEqual(self.source(summary, APPLICATION, "A")["status"], "unreadable")

        not_checked = self.list_field(summary, "not_checked")
        named = [
            item for item in not_checked
            if APPLICATION in item.get("what", "") and DENIED_TEXT in (item.get("reason") or "")
        ]
        self.assertEqual(len(named), 1, not_checked)

        # Everything read: not_checked is present in the JSON and empty.
        fake = FakePowerShell({
            "A:System": ok([
                event("Invented-Disk-Provider", 7, 2, "2026-09-20T10:00:00.0000000+02:00"),
            ]),
            "A:Application": ok([
                event("Invented-App-Provider", 1000, 2, "2026-09-20T11:00:00.0000000+02:00",
                      log=APPLICATION),
            ]),
            "B:System": ok([event(EVENTLOG, 6005, 4, "2026-09-20T09:00:00.0000000+02:00")]),
        })

        summary = self.collect(fake)

        for log, pass_ in ((SYSTEM, "A"), (APPLICATION, "A"), (SYSTEM, "B")):
            self.assertEqual(self.source(summary, log, pass_)["status"], "read")
        self.assertIn("not_checked", summary)
        self.assertEqual(summary["not_checked"], [])

    def test_shortened_coverage(self):
        system_oldest = "2026-09-20T10:00:00.0000000+02:00"  # inside the window
        application_oldest = "2026-09-25T08:00:00.0000000+00:00"  # log cleared in the window
        fake = FakePowerShell({
            "oldest:System": ok(oldest(SYSTEM, system_oldest)),
            "oldest:Application": ok(oldest(APPLICATION, application_oldest)),
            "A:System": ok([
                event("Invented-Disk-Provider", 7, 2, "2026-09-21T10:00:00.0000000+02:00"),
            ]),
            "B:System": ok([event(EVENTLOG, 6005, 4, "2026-09-20T10:00:05.0000000+02:00")]),
            # Application has no level 1-3 events since it was cleared.
            "A:Application": NO_MATCH,
        })

        summary = self.collect(fake)

        self.assertIn("window", summary)
        window_start = instant(summary["window"]["start"])
        self.assertEqual(window_start, NOW - timedelta(days=DAYS))

        cases = (
            (SYSTEM, ("A", "B"), instant(system_oldest)),
            (APPLICATION, ("A",), instant(application_oldest)),
        )
        for log, passes, oldest_time in cases:
            for pass_ in passes:
                src = self.source(summary, log, pass_)
                self.assertIsNotNone(src["log_oldest_record"], src)
                self.assertEqual(instant(src["log_oldest_record"]), oldest_time, src)
                self.assertIsNotNone(src["coverage_start"], src)
                self.assertEqual(instant(src["coverage_start"]), oldest_time, src)

        # The cleared log is empty, yet its gap is still reported.
        self.assertEqual(self.source(summary, APPLICATION, "A")["status"], "empty")

        not_checked = self.list_field(summary, "not_checked")
        for log, _, oldest_time in cases:
            gaps = [
                item for item in not_checked
                if log in item.get("what", "") and "from" in item and "to" in item
            ]
            self.assertTrue(gaps, f"no coverage gap named for {log}: {not_checked}")
            for gap in gaps:
                self.assertEqual(instant(gap["from"]), window_start, gap)
                self.assertEqual(instant(gap["to"]), oldest_time, gap)
                self.assertTrue((gap.get("reason") or "").strip(), gap)

    def test_powershell_script_shape(self):
        data_dir = self.data_dir()
        fake = FakePowerShell()
        self.collect(fake, data_dir=data_dir)

        scripts = {job: (script, out_path) for job, script, out_path in fake.calls}
        self.assertEqual(
            set(scripts),
            {"A:System", "A:Application", "B:System", "oldest:System", "oldest:Application",
             "R:metrics", "R:records"},
        )
        work = (data_dir / "work").resolve()
        projection = ("TimeCreated.ToString('o')", "ProviderName", "Id", "Level", "LogName",
                      "RecordId", "Message", "Properties")
        for job, (script, out_path) in scripts.items():
            # Data travels only through a BOM-less UTF-8 file at an absolute path.
            self.assertIn("WriteAllText", script, job)
            self.assertRegex(script, r"UTF8Encoding(\]::new)?\(\$false\)", job)
            self.assertNotIn("Out-File", script, job)
            self.assertTrue(out_path.is_absolute(), out_path)
            self.assertEqual(out_path.parent.resolve(), work, out_path)
            self.assertIn(str(out_path), script, job)
            if not job.startswith(("A:", "B:", "oldest:")):
                continue  # the WMI jobs have their own projection (test_reliability.py)
            # The M2 projection, Properties as a list of strings.
            for name in projection:
                self.assertIn(name, script, f"{job}: {name}")
            self.assertNotIn("Select-Object", script, job)
            self.assertRegex(
                script,
                # [string[]] on a [pscustomobject] field: PS 5.1 writes a plain
                # list; a Select-Object calculated property does not.
                r"Properties\s*=\s*\[string\[\]\]@\(\s*foreach\s*\(\$p in \$e\.Properties\)"
                r"\s*\{\s*\[string\]\$p\.Value\s*\}\s*\)",
                job,
            )

        # Pass A: levels 1-3, one log per job.
        for log, other in ((SYSTEM, APPLICATION), (APPLICATION, SYSTEM)):
            script = scripts[f"A:{log}"][0]
            self.assertIn(f"LogName='{log}'", script)
            self.assertNotIn(f"'{other}'", script)
            self.assertRegex(script, r"Level\s*=\s*1,\s*2,\s*3")
            self.assertIn("StartTime", script)

        # Pass B: System only, the eleven boot, shutdown status and anomaly Ids.
        script = scripts["B:System"][0]
        self.assertIn("LogName='System'", script)
        self.assertNotIn("'Application'", script)
        self.assertIn("StartTime", script)
        match = re.search(r"\bId\s*=\s*([\d,\s]+)", script)
        self.assertIsNotNone(match, script)
        self.assertEqual(
            sorted(int(i) for i in match.group(1).split(",") if i.strip()),
            [12, 20, 27, 41, 506, 507, 1001, 6005, 6006, 6008, 6009],
        )

        # The oldest record of each log, without a level filter.
        for log in (SYSTEM, APPLICATION):
            script = scripts[f"oldest:{log}"][0]
            self.assertRegex(script, rf"-LogName\s+'{log}'")
            self.assertRegex(script, r"-MaxEvents\s+1\s+-Oldest")
            self.assertNotRegex(script, r"Level\s*=\s*\d")


class TestSummary(CollectTestCase):
    def find_item(self, detail, item_id):
        for key in ("groups", "noise", "boots", "anomalies"):
            for item in detail.get(key) or []:
                if isinstance(item, dict) and item.get("id") == item_id:
                    return item
        self.fail(f"id {item_id} not in detail file")

    def test_contract_fields_and_detail_lookup(self):
        data_dir = self.data_dir()

        # First run (older).
        first = FakePowerShell({
            "A:System": ok([
                event("Invented-Run1-Provider", 3, 2, "2026-09-10T10:00:00.0000000+02:00"),
            ]),
            "B:System": ok([
                event(EVENTLOG, 6005, 4, "2026-09-10T09:00:00.0000000+02:00"),
                event(KERNEL_POWER, 41, 1, "2026-09-10T11:00:00.0000000+02:00"),
            ]),
        })
        self.collect(first, data_dir=data_dir, now=NOW - timedelta(days=1))

        # Second run (newest): two groups, anomalies, boots.
        crash = bugcheck("2026-09-20T12:00:00.0000000+02:00", "0x0000019c")
        pass_a_system = [
            event("Invented-Run2-Disk-Provider", 7, 2, "2026-09-20T10:00:00.0000000+02:00"),
            event("Invented-Run2-Disk-Provider", 7, 2, "2026-09-20T10:30:00.0000000+02:00"),
            event("Invented-Run2-Net-Provider", 4202, 3, "2026-09-21T10:00:00.0000000+02:00"),
            crash,
        ]
        pass_a_application = [
            event("Invented-Run2-App-Provider", 1000, 2, "2026-09-21T11:00:00.0000000+02:00",
                  log=APPLICATION),
        ]
        pass_b_system = [
            event(EVENTLOG, 6005, 4, "2026-09-20T09:00:00.0000000+02:00"),
            dict(crash),
            event(EVENTLOG, 6005, 4, "2026-09-21T09:00:00.0000000+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-21T09:00:10.0000000+02:00"),
        ]
        second = FakePowerShell({
            "A:System": ok(pass_a_system),
            "A:Application": ok(pass_a_application),
            "B:System": ok(pass_b_system),
        })
        code, stdout = self.run_main(data_dir, second)
        self.assertEqual(code, 0, stdout[:300])
        summary = self.parse(stdout)

        # All contract fields, with their fixed values.
        self.assertLessEqual(CONTRACT_FIELDS, set(summary), sorted(set(summary)))
        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(summary["skill"], "ush-events")
        instant(summary["generated_at"])
        self.assertLessEqual({"start", "end", "days"}, set(summary["window"]))
        self.assertEqual(summary["window"]["days"], DAYS)
        self.assertEqual(instant(summary["window"]["end"]), NOW)
        self.assertEqual(summary["truncated"], 0)

        # Each source gives the number of events read.
        expected_counts = {
            (SYSTEM, "A"): len(pass_a_system),
            (APPLICATION, "A"): len(pass_a_application),
            (SYSTEM, "B"): len(pass_b_system),
        }
        self.assertEqual(
            {(s.get("log"), s.get("pass")) for s in summary["sources"]}, set(expected_counts)
        )
        for (log, pass_), expected in expected_counts.items():
            src = self.source(summary, log, pass_)
            self.assertLessEqual(SOURCE_FIELDS, set(src), src)
            self.assertEqual(src["status"], "read", src)
            self.assertEqual(src["event_count"], expected, src)

        # The summary file holds the same text as stdout.
        summary_file = Path(summary["summary_file"])
        detail_file = Path(summary["detail_file"])
        work = (data_dir / "work").resolve()
        for path, suffix in ((summary_file, ".summary.json"), (detail_file, ".detail.json")):
            self.assertTrue(path.is_absolute(), path)
            self.assertTrue(path.is_file(), path)
            self.assertTrue(path.name.endswith(suffix), path)
            self.assertEqual(path.parent.resolve(), work)
        self.assertEqual(
            summary_file.read_text(encoding="utf-8-sig").strip(), stdout.strip()
        )

        # Every group, anomaly and boot has an id.
        groups = summary["groups"]
        anomalies = summary["anomalies"]
        boots = summary["boots"]
        self.assertGreaterEqual(len(groups), 2, groups)
        self.assertGreaterEqual(len(anomalies), 2, anomalies)
        self.assertGreaterEqual(len(boots), 2, boots)
        self.assertEqual([g.get("id") for g in groups],
                         [f"g{i}" for i in range(1, len(groups) + 1)])
        self.assertEqual([a.get("id") for a in anomalies],
                         [f"a{i}" for i in range(1, len(anomalies) + 1)])
        for boot in boots:
            self.assertEqual(boot.get("id"), f"b{boot.get('index')}", boot)

        detail = json.loads(detail_file.read_text(encoding="utf-8-sig"))
        self.assertEqual([a.get("id") for a in detail["anomalies"]],
                         [a["id"] for a in anomalies])

        # A newer-named summary file with a conflicting g1 must be ignored.
        planted = work / "events-20991231-235959.summary.json"
        planted.write_text(
            json.dumps({"groups": [{"id": "g1", "provider": "Planted-Summary-Provider"}]}),
            encoding="utf-8",
        )

        # --detail prints the item from the newest detail file, without PowerShell.
        for item_id in ("g1", "a1", boots[0]["id"]):
            no_ps = FakePowerShell()
            code, out = self.run_main(data_dir, no_ps, extra=("--detail", item_id))
            self.assertEqual(code, 0, out[:300])
            self.assertEqual(no_ps.calls, [])
            printed = self.parse(out)
            self.assertEqual(printed, self.find_item(detail, item_id))
        g1 = self.find_item(detail, "g1")
        self.assertTrue(str(g1.get("provider")).startswith("Invented-Run2-"), g1)

        # An id that does not exist: non-zero exit, still no PowerShell.
        no_ps = FakePowerShell()
        code, _ = self.run_main(data_dir, no_ps, extra=("--detail", "g999"))
        self.assertNotEqual(code, 0)
        self.assertEqual(no_ps.calls, [])

    def test_budget(self):
        base = datetime(2026, 9, 2, 0, 0, 0)  # noqa: DTZ001 - local wall time; ps_time adds the offset
        many = [
            event(
                f"Invented-Provider-{i:04d}",
                100 + i,
                2 + i % 2,
                ps_time(base + timedelta(minutes=i)),
                message=f"The invented component number {i} reported a recoverable fault "
                        "while processing an invented request.",
            )
            for i in range(5000)
        ]
        invented_pairs = {(e["ProviderName"], e["Id"]) for e in many}
        self.assertEqual(len(invented_pairs), 5000)

        crash_times = [
            "2026-09-10T08:00:00.0000000+02:00",
            "2026-09-11T08:00:00.0000000+02:00",
            "2026-09-12T08:00:00.0000000+02:00",
            "2026-09-13T08:00:00.0000000+02:00",
            "2026-09-14T08:00:00.0000000+02:00",
            "2026-09-15T08:00:00.0000000+02:00",
        ]
        codes = ["0x0000019c", "0x0000000a", "0x0000003b", "0x00000050", "0x0000009f",
                 "0x00000124"]
        crashes = [bugcheck(t, c) for t, c in zip(crash_times, codes)]
        power_41 = [
            event(KERNEL_POWER, 41, 1, "2026-09-16T08:00:00.0000000+02:00"),
            event(KERNEL_POWER, 41, 1, "2026-09-17T08:00:00.0000000+02:00"),
        ]
        fake = FakePowerShell({
            "A:System": ok(many),
            "B:System": ok(
                [event(EVENTLOG, 6005, 4, "2026-09-01T00:00:00.0000000+02:00")]
                + crashes + power_41
            ),
        })

        code, stdout = self.run_main(self.data_dir(), fake)
        self.assertEqual(code, 0, stdout[:300])
        self.assertLessEqual(len(stdout), 35000)
        summary = self.parse(stdout)

        # The full list is in the detail file; the summary says how many it left out.
        self.assertIn("detail_file", summary)
        detail = json.loads(Path(summary["detail_file"]).read_text(encoding="utf-8-sig"))
        detail_groups = detail["groups"]
        self.assertLessEqual(
            invented_pairs, {(g.get("provider"), g.get("event_id")) for g in detail_groups}
        )
        summary_groups = self.list_field(summary, "groups")
        self.assertLess(len(summary_groups), len(detail_groups))
        self.assertIn("truncated", summary)
        self.assertEqual(summary["truncated"], len(detail_groups) - len(summary_groups))
        self.assertGreater(summary["truncated"], 0)

        # Anomalies are never cut.
        anomalies = self.list_field(summary, "anomalies")
        self.assertEqual(
            sorted(instant(a["time"]) for a in anomalies if a.get("kind") == "bugcheck"),
            sorted(instant(t) for t in crash_times),
        )
        self.assertEqual(sum(1 for a in anomalies if a.get("kind") == "kernel_power_41"), 2)
        self.assertEqual([a.get("id") for a in anomalies],
                         [a.get("id") for a in detail["anomalies"]])


class TestCli(CollectTestCase):
    def test_data_dir_resolution(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = Path(tmp.name).resolve()
        previous = os.getcwd()
        os.chdir(cwd)
        self.addCleanup(os.chdir, previous)
        script_dir = script_path("ush-events", "events").parent
        appdata_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(appdata_tmp.cleanup)
        appdata = Path(appdata_tmp.name).resolve()

        # (argv, environment or None for the unchanged one, expected data dir)
        cases = ((["--data-dir", "relative-data"], None, cwd / "relative-data"),
                 ([], {"LOCALAPPDATA": str(appdata)}, appdata / "ubershipshape"))
        for argv, environ, expected in cases:
            fake = FakePowerShell({
                "A:System": ok([
                    event("Invented-Disk-Provider", 7, 2, "2026-09-20T10:00:00.0000000+02:00"),
                ]),
            })
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()), \
                    mock.patch.dict(os.environ, environ or {}, clear=environ is not None):
                code = self.events.main(argv, run_ps=fake, now=NOW, read_dumps=NO_DUMPS)
            self.assertEqual(code, 0, out.getvalue()[:300])
            summary = self.parse(out.getvalue())
            self.assertIn("summary_file", summary)
            self.assertIn("detail_file", summary)

            work = (expected / "work").resolve()
            written = [Path(summary["summary_file"]), Path(summary["detail_file"])]
            written += [path for _, _, path in fake.calls]
            self.assertTrue(fake.calls, "run_ps was never called")
            for path in written:
                self.assertTrue(path.is_absolute(), path)
                self.assertEqual(path.parent.resolve(), work, path)
                self.assertNotEqual(path.parent.resolve(), script_dir.resolve(), path)
            self.assertTrue(Path(summary["summary_file"]).is_file())
            self.assertTrue(Path(summary["detail_file"]).is_file())

        # Neither USH_DATA_DIR nor LOCALAPPDATA: a usage error before PowerShell runs.
        ps_calls = []

        def no_ps(job, script, out_path):
            ps_calls.append(job)
            raise AssertionError("run_ps was called without a data directory")

        def no_dumps():
            ps_calls.append("read_dumps")
            raise AssertionError("read_dumps was called without a data directory")

        before = sorted(p.name for p in cwd.iterdir())
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err), \
                mock.patch.dict(os.environ, {}, clear=True), \
                self.assertRaises(SystemExit) as raised:
            self.events.main([], run_ps=no_ps, now=NOW, read_dumps=no_dumps)
        self.assertEqual(raised.exception.code, 2, err.getvalue()[:300])
        self.assertEqual(ps_calls, [])
        self.assertEqual(sorted(p.name for p in cwd.iterdir()), before)

        # Nothing was written next to the script.
        self.assertFalse((script_dir / "ush-data").exists())
        self.assertFalse((script_dir / "ubershipshape").exists())
        self.assertFalse((script_dir / "relative-data").exists())
        self.assertFalse((script_dir / "work").exists())


if __name__ == "__main__":
    unittest.main()

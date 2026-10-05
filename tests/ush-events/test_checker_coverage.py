"""Report check: every group, anomaly and dump file of the summary is named (invented data only)."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script


class CheckerTestCase(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "reports").mkdir()
        self.summary_file = self.root / "summary.json"
        self.detail_file = self.root / "detail.json"

    def summary(self, data):
        data = {**data, "skill": "ush-events", "summary_file": str(self.summary_file),
                "detail_file": str(self.detail_file)}
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

    def detail(self, data):
        self.detail_file.write_text(json.dumps(data), encoding="utf-8")

    def run_check(self, body, name="events-2026-09-28-1200.md"):
        path = self.root / "reports" / name
        path.write_text("\n".join([f"<!-- ush:summary {self.summary_file} -->", *body]) + "\n",
                        encoding="utf-8")
        return self.run_argv([str(path)])

    def run_argv(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.check.main(argv)
        return code, out.getvalue(), err.getvalue()


NOT_CHECKED = ["<!-- ush:not-checked -->", "## Not checked", "Nothing."]

NOT_NAMED_FAILED = re.compile(r"FAILED: .+: (\d+) summary items not named in the report")


def group(n):
    return {"id": f"g{n}", "provider": "Invented-Provider", "event_id": 7, "level": 2,
            "log": "System", "count": 3}


def anomaly(n):
    return {"id": f"a{n}", "kind": "unexpected_shutdown", "time": "2026-01-02T03:04:05Z",
            "boot": "b1", "log": "System", "record_id": 1000 + n}


def dump(n, name):
    return {"id": f"d{n}", "name": name, "size": 4096}


def full_summary():
    return {
        "groups": [group(1), group(2)],
        "anomalies": [anomaly(1)],
        "dumps": {"files": [dump(1, "invented-alpha.dmp")]},
        "boots": [{"id": "b1", "start": "2026-01-02T01:00:00Z"}],
        "noise": [{"id": "n1", "provider": "X", "event_id": 9, "count": 2}],
        "reliability_records": [{"id": "r1", "source": "Invented-App",
                                 "time": "2026-01-02T02:00:00Z"}],
    }


class TestSummaryItemsNamed(CheckerTestCase):
    def test_all_items_named_passes(self):
        self.summary(full_summary())
        code, out, err = self.run_check([
            "# Event log review",
            "Errors from Invented-Provider in System (g1).",
            "Warnings from Invented-Provider (g2).",
            "An unexpected shutdown (a1).",
            "A crash dump was found: invented-alpha.dmp (d1).",
            *NOT_CHECKED,
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("OK", out)
        self.assertNotIn("not named in the report", out)

    def test_missing_group_fails(self):
        self.summary(full_summary())
        code, out, err = self.run_check([
            "# Event log review",
            "Errors from Invented-Provider in System (g1), 999 times.",
            "An unexpected shutdown (a1).",
            "A crash dump was found: invented-alpha.dmp (d1).",
            *NOT_CHECKED,
        ])
        self.assertEqual(code, 1, out + err)
        self.assertIn("not named in the report: g2 (groups)", out)
        self.assertNotIn("not named in the report: g1 ", out)
        match = NOT_NAMED_FAILED.search(out)
        self.assertIsNotNone(match, out)
        self.assertEqual(match.group(1), "1")
        # The number check still runs alongside the coverage check.
        self.assertIn("999 is not in the summary", out + err)

    def test_missing_anomaly_or_dump_fails(self):
        cases = [
            ("anomaly", [
                "Errors from Invented-Provider (g1) and (g2).",
                "A crash dump was found: invented-alpha.dmp (d1).",
            ], "not named in the report: a1 (anomalies)"),
            ("dump", [
                "Errors from Invented-Provider (g1) and (g2).",
                "An unexpected shutdown (a1).",
            ], "not named in the report: d1 (dumps.files)"),
        ]
        for label, lines, expected in cases:
            with self.subTest(label):
                self.summary(full_summary())
                code, out, err = self.run_check(["# Event log review", *lines, *NOT_CHECKED])
                self.assertEqual(code, 1, out + err)
                self.assertIn(expected, out)
                match = NOT_NAMED_FAILED.search(out)
                self.assertIsNotNone(match, out)
                self.assertEqual(match.group(1), "1")

    def test_mention_in_code_or_marker_does_not_count(self):
        named = [
            "Errors from Invented-Provider (g1).",
            "An unexpected shutdown (a1).",
            "A crash dump was found: invented-alpha.dmp (d1).",
        ]
        cases = [
            ("code block", ["```", "g2 Invented-Provider", "```"]),
            ("detail marker", ["<!-- ush:detail g2 -->"]),
        ]
        for label, mention in cases:
            with self.subTest(label):
                self.summary(full_summary())
                self.detail({"groups": [{"id": "g2", "provider": "Invented-Provider",
                                         "event_id": 7}]})
                code, out, err = self.run_check(
                    ["# Event log review", *named, *mention, *NOT_CHECKED])
                self.assertEqual(code, 1, out + err)
                self.assertIn("not named in the report: g2 (groups)", out)

    def test_longer_id_does_not_name_shorter(self):
        data = full_summary()
        data["groups"] = [group(n) for n in range(1, 26)]
        self.summary(data)
        others = ", ".join(f"g{n}" for n in range(3, 26))
        code, out, err = self.run_check([
            "# Event log review",
            f"Groups: g1, {others}.",
            "An unexpected shutdown (a1).",
            "A crash dump was found: invented-alpha.dmp (d1).",
            *NOT_CHECKED,
        ])
        self.assertEqual(code, 1, out + err)
        self.assertIn("not named in the report: g2 (groups)", out)
        self.assertNotIn("not named in the report: g25 ", out)
        self.assertEqual(out.count("not named in the report: "), 1, out)

    def test_other_ids_and_missing_lists_not_required(self):
        cases = [
            ("b n r ids and truncated groups", {
                "groups": [group(1)],
                "truncated": 2,
                "anomalies": [],
                "dumps": {"files": []},
                "boots": [{"id": "b1", "start": "2026-01-02T01:00:00Z"}],
                "noise": [{"id": "n1", "provider": "X", "event_id": 9, "count": 2}],
                "reliability_records": [{"id": "r1", "source": "Invented-App",
                                         "time": "2026-01-02T02:00:00Z"}],
            }, ["Errors from Invented-Provider in System (g1)."]),
            ("missing lists", {
                "anomalies": None,
                "dumps": {"read": True},
                "boots": [{"id": "b1", "start": "2026-01-02T01:00:00Z"}],
            }, ["No error groups, anomalies or crash dumps."]),
        ]
        # The two groups cut from the first case are in the detail file (stable ids).
        self.detail({"groups": [group(1), group(6), group(9)], "noise": [], "boots": [],
                     "anomalies": []})
        for label, data, lines in cases:
            with self.subTest(label):
                self.summary(data)
                code, out, err = self.run_check(["# Event log review", *lines, *NOT_CHECKED])
                self.assertEqual(code, 0, out + err)
                self.assertIn("OK", out)
                self.assertNotIn("not named in the report", out)


if __name__ == "__main__":
    unittest.main()

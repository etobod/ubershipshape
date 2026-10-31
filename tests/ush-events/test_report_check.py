import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

# All data below is invented. The heading number of the report ("## 1.") is
# skipped as the first numbered heading of its level.


def _summary_data(detail_file):
    return {
        "skill": "ush-events",
        "bugcheck_code": "0x0000019c",
        "last_bugcheck_time": "2026-09-18T10:15:00+00:00",
        "event_count": 1234,
        # "1 234" in the report splits into 1 and 234; both are present here,
        # as is 1234, so the thousands-separator form is backed by the JSON.
        "boot_count": 1,
        "max_per_source": 234,
        "avg_per_day": 3.5,
        "detail_file": str(detail_file),
    }


def _detail_data():
    return {
        "groups": [
            {"id": "g1", "provider": "Invented-Provider", "event_id": 41, "count": 4321},
        ],
        "noise": [],
        "boots": [],
        "anomalies": [
            {"id": "a1", "provider": "Other-Invented-Provider", "event_id": 41, "count": 5555},
        ],
    }


def _valid_body_lines():
    """Report lines after the ush:summary line; every number is backed by JSON."""
    return [
        "# Event log report",
        "",
        "Bugcheck 0x19C was recorded on 18.09.2026.",
        "Events in total: 1 234.",
        "Average per day: 3,5.",
        "<!-- ush:detail g1 -->",
        "The largest group has 4321 events.",
        "## 1. Findings",
        "- Nothing else stands out.",
        "",
        "## Not checked",
        "<!-- ush:not-checked -->",
        "Nothing.",
    ]


class TestReportCheck(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.detail_file = self.root / "work" / "events-detail.json"
        self.summary_file = self.root / "work" / "events-summary.json"
        self.detail_file.parent.mkdir(parents=True)
        self.detail_file.write_text(json.dumps(_detail_data()), encoding="utf-8")
        self.summary_file.write_text(
            json.dumps(_summary_data(self.detail_file)), encoding="utf-8"
        )
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()

    def _summary_line(self, path=None):
        return f"<!-- ush:summary {path or self.summary_file} -->"

    def _write_report(self, lines, name="report.md"):
        path = self.reports_dir / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _run(self, report_path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(report_path)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def _assert_not_in_temp_path(self, number):
        # Guard: the temp directory name is random and ends up in the summary
        # (detail_file); make sure it cannot accidentally supply the number.
        self.assertNotIn(number, str(self.root), "temp path collides with test number")

    def _assert_passes(self, lines):
        code, output = self._run(self._write_report(lines, "control.md"))
        self.assertEqual(code, 0, f"control report should pass; output:\n{output}")
        self.assertIn("OK", output)

    def _assert_reports_number_on_line(self, output, number, line_no):
        pattern = re.compile(rf"\b{line_no}\b")
        matching = [
            line for line in output.splitlines()
            if number in line and pattern.search(line.replace(number, " "))
        ]
        self.assertTrue(
            matching,
            f"expected an output line naming {number} and line {line_no}; got:\n{output}",
        )

    def test_all_numbers_from_json(self):
        lines = [self._summary_line()] + _valid_body_lines()
        code, output = self._run(self._write_report(lines))
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)

    def test_invented_number_fails(self):
        valid = [self._summary_line()] + _valid_body_lines()
        self._assert_passes(valid)

        with self.subTest("number in no file"):
            number = "98765"
            self._assert_not_in_temp_path(number)
            lines = list(valid)
            insert_at = 5  # 0-based index; becomes line 6 of the report
            lines.insert(insert_at, f"There were also {number} warnings.")
            code, output = self._run(self._write_report(lines, "invented.md"))
            self.assertNotEqual(code, 0, f"output:\n{output}")
            self._assert_reports_number_on_line(output, number, insert_at + 1)

        with self.subTest("number only in a detail item not named in ush:detail"):
            # 5555 is the count of anomaly a1; only g1 is named in the marker.
            number = "5555"
            self._assert_not_in_temp_path(number)
            lines = list(valid)
            marker_index = lines.index("<!-- ush:detail g1 -->")
            insert_at = marker_index + 2
            lines.insert(insert_at, f"One anomaly counted {number} events.")
            code, output = self._run(self._write_report(lines, "unnamed-detail.md"))
            self.assertNotEqual(code, 0, f"output:\n{output}")
            self._assert_reports_number_on_line(output, number, insert_at + 1)

    def test_missing_markers_fail(self):
        body = _valid_body_lines()
        self._assert_passes([self._summary_line()] + body)

        cases = {
            "no ush:not-checked marker": [self._summary_line()]
            + [line for line in body if line != "<!-- ush:not-checked -->"],
            "no ush:summary line at all": list(body),
            "ush:summary not on the first line": [body[0], self._summary_line()] + body[1:],
            "ush:summary points to a missing file": [
                self._summary_line(self.root / "work" / "missing-summary.json")
            ]
            + body,
        }
        for index, (label, lines) in enumerate(cases.items()):
            with self.subTest(label):
                code, output = self._run(self._write_report(lines, f"defect-{index}.md"))
                self.assertNotEqual(code, 0, f"{label}: output:\n{output}")
                self.assertTrue(output.strip(), f"{label}: expected a message")

    def _run_argv(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_latest_selection(self):
        valid = [self._summary_line()] + _valid_body_lines()
        broken = [line for line in valid if line != "<!-- ush:not-checked -->"]
        # The newest name is valid; the older names fail. The older-named
        # broken report is written last, so a choice by modification time
        # instead of by name would pick it and fail.
        self._write_report(broken, "events-2026-09-01-0800.md")
        self._write_report(valid, "events-2026-09-20-0715.md")
        self._write_report(broken, "events-2026-09-19-2330.md")
        (self.reports_dir / "events-2026-09-30-0000.txt").write_text("x", encoding="utf-8")

        code, output = self._run_argv(["--latest", "--skill", "ush-events", "--data-dir", str(self.root)])
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)
        self.assertIn("events-2026-09-20-0715.md", output)

        with self.subTest("newest report is checked, not just any"):
            self._write_report(broken, "events-2026-09-21-0600.md")
            code, output = self._run_argv(["--latest", "--skill", "ush-events", "--data-dir", str(self.root)])
            self.assertNotEqual(code, 0, f"output:\n{output}")

        with self.subTest("no report in the reports directory"):
            empty = self.root / "empty-data"
            (empty / "reports").mkdir(parents=True)
            code, output = self._run_argv(["--latest", "--skill", "ush-events", "--data-dir", str(empty)])
            self.assertNotEqual(code, 0, f"output:\n{output}")
            self.assertTrue(output.strip(), "expected a message")


if __name__ == "__main__":
    unittest.main()

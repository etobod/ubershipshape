"""Shared report check: time pairs quoted from JSON strings and backtick-continued commands.

A local and UTC time pair that is part of a JSON string value in the summary (a quoted
message) needs no backing time. A pair not quoted from any JSON string still has to
match a time with a zone. A skill script command in a code block that continues on the
next line with a PowerShell backtick is named as such, not as a missing --data-dir.
All data is invented; tests always pass a fixed zone.
"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOT_CHECKED = ["## Not checked", "<!-- ush:not-checked -->", "Nothing."]

GENERATED_AT = "2026-09-30T07:26:40+00:00"
BACKING_TIME = "2026-09-30T08:00:00+00:00"
QUOTED_MESSAGE = "Started 2026-09-30 10:00 (08:00 UTC)"
QUOTING_SENTENCE = f'The service log says "{QUOTED_MESSAGE}" for the invented task.'

FENCE = "```"
SET_LOCATION = 'Set-Location "C:\\proj"'
HEALTH = "python -B skills/ush-health/scripts/health.py"
DATA_DIR = '--data-dir "C:\\x"'
CONTINUED_MESSAGE = "continued with a backtick"
DATA_DIR_MESSAGE = "needs --data-dir"
PAIR_MESSAGE = "matches no time with a zone"


def plus_two(dt):
    """A fixed +02:00 zone, independent of the machine running the tests."""
    return dt.astimezone(timezone(timedelta(hours=2)))


def _profile():
    return {
        "detail_sections": ["things"],
        "id_letters": "c",
        "path_keys": ["detail_file", "summary_file"],
        "id_keys": ["id"],
        "required_lists": [],
        "truncated": None,
        "report_prefix": "test-",
    }


def _block(lines):
    return [FENCE + "powershell", *lines, FENCE]


class TestQuoted(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        # The temp path must not hold the numbers used in the reports.
        guarded = ("2026", "0726", "0800", "1000", "0930", "7d")
        for _ in range(20):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.root = Path(tmp.name).resolve()
            if not any(number in str(self.root) for number in guarded):
                break
        else:
            self.skipTest("the temp folder path holds a number these tests use")
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.summary_file = self.work_dir / "summary.json"
        self.detail_file = self.work_dir / "detail.json"
        self.detail_file.write_text(json.dumps({"things": []}), encoding="utf-8")

        self.skills_dir = self.root / "skills"
        patcher = mock.patch.object(self.check, "SKILLS_DIR", self.skills_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        profile_path = self.skills_dir / "ush-test" / "data" / "report-profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(json.dumps(_profile()), encoding="utf-8")

    def write_summary(self, data):
        data = dict(data)
        data["skill"] = "ush-test"
        data["summary_file"] = str(self.summary_file)
        data["detail_file"] = str(self.detail_file)
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

    def run_report(self, body, name):
        path = self.reports_dir / name
        first = f"<!-- ush:summary {self.summary_file} -->"
        path.write_text("\n".join([first, "# Test report", *body, *NOT_CHECKED]) + "\n",
                        encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(path)], to_local=plus_two)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def assert_passes(self, body, name):
        code, output = self.run_report(body, name)
        self.assertEqual(code, 0, output)
        self.assertIn("OK", output)

    def assert_fails_with(self, body, name, expected, absent=()):
        code, output = self.run_report(body, name)
        self.assertEqual(code, 1, output)
        self.assertIn("FAILED", output)
        self.assertIn(expected, output)
        for text in absent:
            self.assertNotIn(text, output)

    def test_quoted_pair_passes(self):
        # 08:00 UTC is not backed by any time in the summary: only generated_at (07:26).
        self.write_summary({"generated_at": GENERATED_AT, "message": QUOTED_MESSAGE})
        self.assert_passes([QUOTING_SENTENCE], "quoted-pair.md")

    def test_unquoted_pair_still_checked(self):
        with self.subTest("pair without a quoting JSON string or a backing time fails"):
            self.write_summary({"generated_at": GENERATED_AT, "message": "Invented task ran."})
            self.assert_fails_with([QUOTING_SENTENCE], "unquoted-pair.md", PAIR_MESSAGE)

        with self.subTest("pair backed by a time with a zone passes"):
            self.write_summary({"generated_at": GENERATED_AT, "started_at": BACKING_TIME})
            self.assert_passes([QUOTING_SENTENCE], "backed-pair.md")

    def test_backtick_continuation_named(self):
        self.write_summary({"note": "invented"})
        intro = "Run the health check from the project folder:"

        with self.subTest("--data-dir on the continued line"):
            self.assert_fails_with(
                [intro, *_block([SET_LOCATION, HEALTH + " `", DATA_DIR])],
                "continued-data-dir.md", CONTINUED_MESSAGE, absent=(DATA_DIR_MESSAGE,))

        with self.subTest("absolute --data-dir already on the backtick line"):
            self.assert_fails_with(
                [intro, *_block([SET_LOCATION, f"{HEALTH} {DATA_DIR} `", "--compare-to 7d"])],
                "continued-compare.md", CONTINUED_MESSAGE)

    def test_one_line_commands_unchanged(self):
        self.write_summary({"note": "invented"})
        intro = "Run the health check from the project folder:"

        with self.subTest("one-line command without --data-dir fails"):
            self.assert_fails_with(
                [intro, *_block([SET_LOCATION, HEALTH])], "one-line-no-data-dir.md",
                DATA_DIR_MESSAGE, absent=(CONTINUED_MESSAGE,))

        with self.subTest("one-line command with an absolute --data-dir passes"):
            self.assert_passes(
                [intro, *_block([SET_LOCATION, f"{HEALTH} {DATA_DIR}"])], "one-line-ok.md")


if __name__ == "__main__":
    unittest.main()

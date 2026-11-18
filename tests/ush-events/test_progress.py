"""Progress lines of ush-events (plan 071, M1 code review round 2): an event query that
finds no events exits non-zero with NoMatchingEventsFound, which run_job counts as a
normal empty result, so its end line says done, not failed.

No PowerShell is started (``subprocess.run`` is faked); every value is invented.
"""

import io
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

JOB = "invented-pass"
NO_EVENTS = ("Get-WinEvent : No events were found that match the specified selection "
             "criteria.\r\n    + FullyQualifiedErrorId : NoMatchingEventsFound,"
             "Microsoft.PowerShell.Commands.GetWinEventCommand\r\n")
OTHER_ERR = "Get-WinEvent : invented access failure\r\n"


def lines_of(text):
    return [line.rstrip("\r") for line in text.splitlines() if line.strip()]


class TestEventsProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def end_line(self, stderr):
        def run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            return subprocess.CompletedProcess(cmd, 1, "", stderr)

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"USH_PROGRESS": "1"}), \
                mock.patch("subprocess.run", run), redirect_stderr(err):
            code, returned = self.events.default_run_ps(JOB, "Get-WinEvent", Path(tmp) / "x.json")
        self.assertEqual((code, returned), (1, stderr))
        lines = lines_of(err.getvalue())
        self.assertEqual(lines[0], f"{JOB} ...", lines)
        return lines[-1]

    def test_no_events_ends_as_done(self):
        self.assertRegex(self.end_line(NO_EVENTS), rf"^{re.escape(JOB)} done \(\d+(?:\.\d+)? s\)$")

    def test_other_error_still_failed(self):
        self.assertEqual(self.end_line(OTHER_ERR), f"{JOB} failed")


class TestLogsProgress(unittest.TestCase):
    """logs.py runs the export and the clear (an argv, not PowerShell) in the run-me
    window: each gets a start line and a done or failed end line (plan 071, final review)."""

    @classmethod
    def setUpClass(cls):
        cls.logs = load_script("ush-events", "logs")

    def lines(self, fake_run):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"USH_PROGRESS": "1"}), \
                mock.patch("subprocess.run", fake_run), redirect_stderr(err):
            self.logs.default_run("export", ["wevtutil.exe", "epl", "Invented"],
                                  Path(tmp) / "x.json")
        return lines_of(err.getvalue())

    def test_argv_job_ends_as_done(self):
        def run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, b"", b"")

        lines = self.lines(run)
        self.assertEqual(lines[0], "export ...", lines)
        self.assertRegex(lines[-1], r"^export done \(\d+(?:\.\d+)? s\)$")
        self.assertEqual(len(lines), 2, lines)

    def test_powershell_job_with_no_match_ends_as_failed(self):
        # logs.py's own PowerShell bodies catch NoMatchingEventsFound, so a non-zero
        # exit is a real failure that logs.py counts: its window line says failed.
        def run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, "", NO_EVENTS)

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"USH_PROGRESS": "1"}), \
                mock.patch("subprocess.run", run), redirect_stderr(err):
            os.environ.pop("USH_PROGRESS_MARK", None)
            self.logs.default_run("verify", "Get-WinEvent", Path(tmp) / "x.json")
        self.assertEqual(lines_of(err.getvalue()), ["verify ...", "verify failed"])

    def test_argv_job_failure_and_timeout_end_as_failed(self):
        def nonzero(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 5, b"", b"invented access denied")

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 1)

        for name, fake in (("non-zero exit", nonzero), ("timeout", timeout)):
            with self.subTest(name):
                self.assertEqual(self.lines(fake), ["export ...", "export failed"])


if __name__ == "__main__":
    unittest.main()

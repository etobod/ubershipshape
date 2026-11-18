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


if __name__ == "__main__":
    unittest.main()

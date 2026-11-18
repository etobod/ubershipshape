"""Progress lines of ush-health (plan 071, QA round 1): a PowerShell job that run_job counts
as an empty read ends with a done line in the window, not failed, and a job whose
error is not an empty read still ends with failed.

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

SKILL, SCRIPT = "ush-health", "health"
OTHER_ERR = "invented access failure\r\n"


def lines_of(text):
    return [line.rstrip("\r") for line in text.splitlines() if line.strip()]


class TestHealthProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script(SKILL, SCRIPT)
        cls.marker = cls.mod.NO_PNP_DEVICE
        cls.jobs = ("tpm_devices",)

    def run_job(self, job, stderr):
        """run_job through the skill's default_run_ps; return (status, window end line)."""

        def run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            return subprocess.CompletedProcess(cmd, 1, "", stderr)

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"USH_PROGRESS": "1"}), \
                mock.patch("subprocess.run", run), redirect_stderr(err):
            result = self.mod.psrun.run_job(self.mod.default_run_ps, job, "Get-Invented",
                                            Path(tmp) / "x.json",
                                            empty_markers=(self.marker,))
        lines = lines_of(err.getvalue())
        self.assertEqual(lines[0], f"{job} ...", lines)
        return result["status"], lines[-1]

    def test_empty_read_ends_as_done(self):
        for job in self.jobs:
            with self.subTest(job):
                status, end = self.run_job(job, f"invented text {self.marker} invented\r\n")
                self.assertEqual(status, "empty")
                self.assertRegex(end, rf"^{re.escape(job)} done \(\d+(?:\.\d+)? s\)$")

    def test_other_error_still_failed(self):
        for job in self.jobs:
            with self.subTest(job):
                status, end = self.run_job(job, OTHER_ERR)
                self.assertNotEqual(status, "empty")
                self.assertEqual(end, f"{job} failed")

    def test_marker_does_not_turn_other_jobs_done(self):
        _status, end = self.run_job("invented_job", f"invented text {self.marker}\r\n")
        self.assertEqual(end, "invented_job failed")


if __name__ == "__main__":
    unittest.main()

"""Progress lines on stderr (plan 071, M1): the shared helper ``progress.py`` and the
start and end lines of ``psrun.default_run_ps``.

Interface from the plan:

- ``skills/ush-common/scripts/progress.py``: ``enabled()`` is true when ``USH_PROGRESS``
  is ``1``, or when it is unset and ``sys.stderr.isatty()``; ``step(text)`` writes one
  ASCII line to stderr when enabled; ``count(label, n, total=None)`` prints at most once
  per fixed step of items and always for the last: ``<label> <n> / <total>`` with a
  total, ``<label> <n> directories`` without one.
- ``psrun.default_run_ps(job, script, out_path)`` prints ``<job> ...`` before the job and
  ``<job> done (<s> s)`` or ``<job> failed`` after it; it returns ``(code, stderr)``.

Assumptions added by these tests beyond the plan text:

- ``progress`` looks ``sys.stderr`` and ``os.environ`` up at call time, so
  ``redirect_stderr`` and ``mock.patch.dict(os.environ)`` reach it.
- ``default_run_ps`` calls the PowerShell process through ``subprocess.run`` (the module
  attribute), so patching ``subprocess.run`` replaces it; a timeout is
  ``subprocess.TimeoutExpired`` raised by ``subprocess.run``. The fake returns ``str``
  output when ``text``/``encoding``/``universal_newlines`` is passed, else ``bytes``.
- A failed job is one whose process exits non-zero, or that times out.
- ``<s>`` in the done line is a non-negative number (integer or decimal).

No PowerShell is started; every value is invented.
"""

import io
import itertools
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

JOB = "invented-job"
SCRIPT = "Get-InventedThing | ConvertTo-Json -Depth 3"
INVENTED_ERR = "Get-InventedThing : invented failure text\r\n"


def fake_subprocess_run(returncode=0, stdout="", stderr="", timeout=False, calls=None):
    """A stand-in for ``subprocess.run`` that never starts a process."""

    def run(*args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        cmd = args[0] if args else kwargs.get("args")
        if timeout:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 300))
        as_text = bool(kwargs.get("text") or kwargs.get("encoding")
                       or kwargs.get("universal_newlines"))
        out = stdout if as_text else stdout.encode("utf-8")
        err = stderr if as_text else stderr.encode("utf-8")
        return subprocess.CompletedProcess(cmd, returncode, out, err)

    return run


def lines_of(text):
    return [line.rstrip("\r") for line in text.splitlines() if line.strip()]


class TestProgress(unittest.TestCase):
    def setUp(self):
        self.progress = load_script("ush-common", "progress")
        self.psrun = load_script("ush-common", "psrun")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out_path = Path(tmp.name).resolve() / "invented-job.json"

    def run_ps(self, fake, progress_on):
        """Call default_run_ps with ``subprocess.run`` faked; return (outcome, stdout,
        stderr). ``outcome`` is ``("returned", value)`` or ``("raised", type)``."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ), mock.patch("subprocess.run", fake), \
                redirect_stdout(out), redirect_stderr(err):
            if progress_on:
                os.environ["USH_PROGRESS"] = "1"
            else:
                os.environ.pop("USH_PROGRESS", None)
            try:
                outcome = ("returned", self.psrun.default_run_ps(JOB, SCRIPT, self.out_path))
            except Exception as exc:  # noqa: BLE001 - compared between both runs
                outcome = ("raised", type(exc))
        return outcome, out.getvalue(), err.getvalue()

    def test_run_ps_prints_job_start_and_end_on_stderr(self):
        calls = []
        outcome, stdout, stderr = self.run_ps(fake_subprocess_run(0, calls=calls), True)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(outcome[0], "returned", outcome)
        self.assertEqual(stdout, "")
        lines = lines_of(stderr)
        self.assertEqual(len(lines), 2, lines)
        self.assertEqual(lines[0], f"{JOB} ...")
        self.assertRegex(lines[1], rf"^{re.escape(JOB)} done \(\d+(?:\.\d+)? s\)$")

    def test_run_ps_failure_line(self):
        cases = {
            "non-zero exit": lambda: fake_subprocess_run(1, stderr=INVENTED_ERR),
            "timeout": lambda: fake_subprocess_run(timeout=True),
        }
        for name, make_fake in cases.items():
            with self.subTest(name):
                quiet, quiet_out, quiet_err = self.run_ps(make_fake(), False)
                loud, loud_out, loud_err = self.run_ps(make_fake(), True)
                self.assertEqual(quiet_err, "")
                self.assertEqual(loud, quiet)
                self.assertEqual(loud_out, quiet_out)
                lines = lines_of(loud_err)
                self.assertEqual(len(lines), 2, lines)
                self.assertEqual(lines[0], f"{JOB} ...")
                self.assertEqual(lines[1], f"{JOB} failed")
                self.assertNotIn("done", loud_err)

    def counter_lines(self, label, last, total):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"USH_PROGRESS": "1"}), redirect_stderr(err):
            for n in range(1, last + 1):
                self.progress.count(label, n, total)
        return err.getvalue()

    def assert_throttled(self, values, last):
        """Printed counts rise, never one line per item, and follow one fixed step."""
        self.assertTrue(values, "no counter line printed")
        self.assertEqual(values, sorted(set(values)), values[:20])
        self.assertLess(len(values), last // 2, f"{len(values)} lines for {last} items")
        gaps = [b - a for a, b in itertools.pairwise(values)]
        self.assertTrue(all(gap > 1 for gap in gaps), gaps[:20])
        # The gap before a forced last line and the first printed value may be shorter;
        # every other gap is the same fixed step.
        self.assertLessEqual(len(set(gaps[1:-1])), 1, sorted(set(gaps))[:20])

    def test_counter_is_throttled_and_ends_on_total(self):
        total = 100003
        with self.subTest("with a total"):
            text = self.counter_lines("items", total, total)
            self.assertTrue(text.isascii(), text[:200])
            lines = lines_of(text)
            values = []
            for line in lines:
                match = re.fullmatch(rf"items (\d+) / {total}", line)
                self.assertIsNotNone(match, line)
                values.append(int(match.group(1)))
            self.assertEqual(lines[-1], f"items {total} / {total}")
            self.assert_throttled(values, total)

        with self.subTest("without a total"):
            text = self.counter_lines("walk", total, None)
            self.assertTrue(text.isascii(), text[:200])
            lines = lines_of(text)
            values = []
            for line in lines:
                match = re.fullmatch(r"walk (\d+) directories", line)
                self.assertIsNotNone(match, line)
                values.append(int(match.group(1)))
            self.assert_throttled(values, total)

    def test_silent_when_not_a_console(self):
        err, out = io.StringIO(), io.StringIO()
        calls = []
        with mock.patch.dict(os.environ), \
                mock.patch("subprocess.run", fake_subprocess_run(0, calls=calls)), \
                redirect_stdout(out), redirect_stderr(err):
            os.environ.pop("USH_PROGRESS", None)
            self.assertFalse(self.progress.enabled())
            self.progress.step("invented step")
            for n in range(1, 2001):
                self.progress.count("items", n, 2000)
            for n in range(1, 2001):
                self.progress.count("walk", n)
            self.psrun.default_run_ps(JOB, SCRIPT, self.out_path)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

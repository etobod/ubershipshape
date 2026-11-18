"""Progress lines of ush-runall (plan 071, M2): a start and an end line per child, and the
child's own stderr passed through as it comes.

Interface from the plan:

- ``runall.py`` prints, through ``progress.step``, ``[<n>/<N>] <skill> ...`` before each
  child and ``[<n>/<N>] <skill> <status> (<s> s)`` after it.
- ``default_run_child(argv, timeout_s) -> {returncode, stdout, stderr_tail, duration_s}``
  sets ``USH_PROGRESS=1`` in the child's environment exactly when ``progress.enabled()``
  is true for runall, reads the child's stderr as it comes (a reader thread) and writes
  each line to runall's own stderr, keeps the last ``STDERR_TAIL_CHARS`` characters as
  ``stderr_tail``, and keeps the timeout and tree stop (``kill_tree(pid)``, then
  ``proc.kill()``, then ``TimeoutExpired`` raised again).
- ``progress.enabled()`` is true when ``USH_PROGRESS`` is ``1``, or when it is unset and
  ``sys.stderr.isatty()``; it reads ``os.environ`` and ``sys.stderr`` at call time.
- ``.claude-plugin/plugin.json`` ``version`` is raised above 1.0.43.

Assumptions added by these tests beyond the plan text:

- The relay writes to ``sys.stderr`` as looked up at run time, so ``redirect_stderr``
  reaches it, and the reader thread has ended (been joined) when ``default_run_child``
  returns or raises.
- ``<s>`` in an end line is a non-negative number (integer or decimal); the status of a
  child that exits 0 with a valid summary is ``ok``.

The only real process is a small invented child, ``sys.executable -I -c <script>``
(plan 071, "Tests never touch the machine"); ``kill_tree`` is replaced by a recorder and
``subprocess.run`` refuses every call. Every value is invented.
"""

import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .test_runall import TABLE, FakeChildren, RunallTestCase, entries, refuse

PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKER = "invented-child-7f3a"
LINE_ONE = "invented progress one"
LINE_TWO = "invented progress two"
STALL_LINE = "invented line before the stall"

# Writes two lines to stderr, then a JSON object with the USH_PROGRESS it saw on stdout.
CHILD_TWO_LINES = (
    "import json, os, sys; "
    f"sys.stderr.write('{LINE_ONE}\\n'); sys.stderr.flush(); "
    f"sys.stderr.write('{LINE_TWO}\\n'); sys.stderr.flush(); "
    f"sys.stdout.write(json.dumps({{'marker': '{MARKER}', "
    "'ush_progress': os.environ.get('USH_PROGRESS')}))"
)

# Writes to stderr only when it was given USH_PROGRESS=1, as a real skill script does.
CHILD_PROGRESS_ONLY = (
    "import json, os, sys; "
    "seen = os.environ.get('USH_PROGRESS'); "
    f"seen == '1' and (sys.stderr.write('{LINE_ONE}\\n'), sys.stderr.flush()); "
    f"sys.stdout.write(json.dumps({{'marker': '{MARKER}', 'ush_progress': seen}}))"
)

# Writes one line to stderr, then stalls far beyond the time limit.
CHILD_STALLS = (
    "import sys, time; "
    f"sys.stderr.write('{STALL_LINE}\\n'); sys.stderr.flush(); "
    "time.sleep(120)"
)

END_RE = re.compile(r"^\[(\d+)/(\d+)\] (ush-[a-z]+) (\S+) \((\d+(?:\.\d+)?) s\)$")


class TtyStringIO(io.StringIO):
    """A captured stderr that says it is a console."""

    def isatty(self):
        return True


def lines_of(text):
    return [line.rstrip("\r") for line in text.splitlines() if line.strip()]


def child_argv(script):
    return [sys.executable, "-I", "-c", script]


def expected_stdout(seen):
    return json.dumps({"marker": MARKER, "ush_progress": seen})


class TestRunallProgress(RunallTestCase):
    def run_child_real(self, script, timeout_s, err, kill_calls=None, progress_env=None):
        """Call ``default_run_child`` on an invented child with ``err`` as runall's
        stderr. ``progress_env`` is the value of ``USH_PROGRESS`` (None: unset).
        Return ``("returned", result)`` or ``("raised", exception)``."""

        def kill_tree(pid):
            if kill_calls is None:
                raise AssertionError(f"kill_tree called on a normal run: {pid}")
            kill_calls.append(pid)
            return True

        out = io.StringIO()
        with mock.patch.dict(os.environ), \
                mock.patch.object(subprocess, "run", refuse), \
                mock.patch.object(self.runall, "kill_tree", kill_tree), \
                redirect_stdout(out), redirect_stderr(err):
            if progress_env is None:
                os.environ.pop("USH_PROGRESS", None)
            else:
                os.environ["USH_PROGRESS"] = progress_env
            try:
                outcome = ("returned", self.runall.default_run_child(child_argv(script),
                                                                     timeout_s))
            except Exception as exc:  # noqa: BLE001 - the timeout test inspects it
                outcome = ("raised", exc)
        self.assertEqual(out.getvalue(), "", "runall wrote to its stdout")
        return outcome

    def test_child_start_and_end_lines(self):
        fake = FakeChildren(self.temp())
        children = self.children_file(entries(TABLE))
        with mock.patch.dict(os.environ, {"USH_PROGRESS": "1"}):
            code, stdout, stderr = self.run_main(self.data_dir(), fake, children=children)
        self.assertEqual(code, 0, (stdout[:300], stderr[-500:]))
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        self.assertEqual(len(self.items(summary, "children")), len(TABLE))

        total = len(TABLE)
        lines = lines_of(stderr)
        self.assertEqual(len(lines), 2 * total, lines)
        for index, (skill, _script, _timeout) in enumerate(TABLE):
            n = index + 1
            start, end = lines[2 * index], lines[2 * index + 1]
            self.assertEqual(start, f"[{n}/{total}] {skill} ...", lines)
            match = END_RE.match(end)
            self.assertIsNotNone(match, end)
            self.assertEqual(match.group(1), str(n), end)
            self.assertEqual(match.group(2), str(total), end)
            self.assertEqual(match.group(3), skill, end)
            self.assertEqual(match.group(4), "ok", end)

    def test_child_stderr_passed_through_and_tail_kept(self):
        # Progress enabled the console way: USH_PROGRESS unset, stderr a console, so the
        # child can only get USH_PROGRESS=1 from runall itself.
        loud_err = TtyStringIO()
        kind, loud = self.run_child_real(CHILD_TWO_LINES, 60, loud_err)
        self.assertEqual(kind, "returned", loud)
        quiet_err = io.StringIO()
        kind, quiet = self.run_child_real(CHILD_TWO_LINES, 60, quiet_err)
        self.assertEqual(kind, "returned", quiet)

        relayed = lines_of(loud_err.getvalue())
        self.assertIn(LINE_ONE, relayed)
        self.assertIn(LINE_TWO, relayed)
        self.assertLess(relayed.index(LINE_ONE), relayed.index(LINE_TWO), relayed)

        self.assertEqual(loud["returncode"], 0, loud)
        self.assertEqual(loud["stdout"], expected_stdout("1"))
        self.assertEqual(json.loads(loud["stdout"])["ush_progress"], "1")
        self.assertEqual(set(loud), {"returncode", "stdout", "stderr_tail", "duration_s"})
        self.assertEqual(lines_of(loud["stderr_tail"]), [LINE_ONE, LINE_TWO])
        self.assertEqual(lines_of(loud["stderr_tail"]), lines_of(quiet["stderr_tail"]))
        self.assertEqual(quiet["stdout"], expected_stdout(None))

    def test_no_progress_when_not_enabled(self):
        with self.subTest("runall main prints no progress line"):
            fake = FakeChildren(self.temp())
            children = self.children_file(entries(TABLE))
            with mock.patch.dict(os.environ):
                os.environ.pop("USH_PROGRESS", None)
                code, stdout, stderr = self.run_main(self.data_dir(), fake,
                                                     children=children)
            self.assertEqual(code, 0, (stdout[:300], stderr[-500:]))
            self.parse(stdout)
            self.assertEqual(stderr, "")

        with self.subTest("the child gets no USH_PROGRESS=1"):
            err = io.StringIO()
            kind, result = self.run_child_real(CHILD_PROGRESS_ONLY, 60, err)
            self.assertEqual(kind, "returned", result)
            self.assertEqual(result["returncode"], 0, result)
            self.assertEqual(result["stdout"], expected_stdout(None))
            self.assertEqual(err.getvalue(), "")

    def test_timeout_still_stops_child(self):
        err = io.StringIO()
        kill_calls = []
        threads_before = set(threading.enumerate())
        started = time.monotonic()
        kind, outcome = self.run_child_real(CHILD_STALLS, 5, err, kill_calls=kill_calls,
                                            progress_env="1")
        elapsed = time.monotonic() - started

        self.assertEqual(kind, "raised", outcome)
        self.assertIsInstance(outcome, subprocess.TimeoutExpired)
        self.assertLess(elapsed, 60, "the stalled child was not stopped at its time limit")
        self.assertEqual(len(kill_calls), 1, kill_calls)
        self.assertIsInstance(kill_calls[0], int)
        self.assertIn(STALL_LINE, lines_of(err.getvalue()))
        alive = [thread for thread in threading.enumerate()
                 if thread not in threads_before and thread.is_alive()]
        self.assertEqual(alive, [], "the stderr relay thread is still running")

    def test_plugin_version_raised(self):
        plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        version = str(plugin.get("version"))
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertGreater(tuple(int(part) for part in version.split(".")), (1, 0, 43))


if __name__ == "__main__":
    unittest.main()

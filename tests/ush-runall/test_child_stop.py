"""Tests for skills/ush-runall/scripts/runall.py (plan 134, M1): how a child is stopped
and the upper limit of a child's time limit.

Interface under test (from the plan and the existing runall tests):

- The script is loaded with ``load_script("ush-runall", "runall")`` (through
  ``RunallTestCase``).
- ``main(argv=None, run_child=None, now=None) -> int``; the tests pass
  ``--data-dir <tmp dir>``, inject ``run_child`` and patch ``CHILDREN_FILE``.
- ``data/children.json`` is an ordered list of ``{skill, script, timeout_s}``; a bad file
  exits 2 before any child runs. ``timeout_s`` may be at most 86400 (one day).

No real process is started: ``run_child`` is a fake, and ``subprocess.Popen`` and
``subprocess.run`` refuse every call. Every value is invented.
"""

import subprocess
import sys
import unittest
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .test_runall import FAKE_PID, TABLE, FakeChildren, RunallTestCase, entries, refuse

LIMIT_S = 86400
CONTRACT = REPO_ROOT / "skills" / "ush-runall" / "references" / "summary-contract.md"
ARGV = [sys.executable, "-B", "C:\\invented\\skills\\ush-x\\scripts\\x.py",
        "--data-dir", "C:\\invented-data-dir"]


class ScriptedPopen:
    """A process that never runs: the first ``communicate`` raises ``first`` (or returns
    ``("out", "err")`` when it is None); later calls raise ``reap``, or return when it is
    None. Every step goes to ``events``."""

    def __init__(self, events, first, reap=None):
        self.events = events
        self.first = first
        self.reap = reap
        self.pid = FAKE_PID
        self.returncode = None
        self.calls = 0

    def communicate(self, input=None, timeout=None):
        self.events.append(("communicate", timeout))
        self.calls += 1
        if self.calls == 1:
            if self.first is not None:
                raise self.first
            self.returncode = 0
            return "invented out", "invented err"
        if self.reap is not None:
            raise self.reap
        return "", ""

    def kill(self):
        self.events.append(("kill", self.pid))
        self.returncode = 1

    terminate = kill

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


def table_with_health_timeout(timeout_s):
    """The plan's table with only the ush-health time limit changed."""
    rows = entries(TABLE)
    for row in rows:
        if row["skill"] == "ush-health":
            row["timeout_s"] = timeout_s
    return rows


class TestChildStop(RunallTestCase):
    def test_timeout_limit(self):
        with self.subTest("timeout_s one second over the limit is rejected"):
            fake = FakeChildren(self.temp())
            children = self.children_file(table_with_health_timeout(LIMIT_S + 1))
            code, stdout, stderr = self.run_main(self.data_dir(), fake, children=children)
            self.assertEqual(code, 2, (stdout[:300], stderr[-300:]))
            self.assertEqual(fake.calls, [])

        with self.subTest("timeout_s exactly at the limit is accepted"):
            fake = FakeChildren(self.temp())
            children = self.children_file(table_with_health_timeout(LIMIT_S))
            self.collect(self.data_dir(), fake, children=children)
            self.assertEqual(len(fake.calls), len(TABLE), fake.calls)
            health = [timeout for argv, timeout in fake.calls
                      if "ush-health" in argv[2]]
            self.assertEqual(health, [LIMIT_S], fake.calls)

    def run_default(self, popen):
        """``default_run_child`` with ``popen`` as the process and ``kill_tree`` recorded."""
        events = popen.events

        def kill_tree(pid):
            events.append(("kill_tree", pid))
            return True

        with mock.patch.object(subprocess, "Popen", lambda args, **kwargs: popen), \
                mock.patch.object(subprocess, "run", refuse), \
                mock.patch.object(self.runall, "kill_tree", kill_tree):
            return self.runall.default_run_child(ARGV, 5)

    def test_other_exception_stops_child(self):
        cases = {
            "OverflowError": (OverflowError("invented overflow"), None),
            "KeyboardInterrupt": (KeyboardInterrupt(), None),
            "OverflowError, reaping times out": (
                OverflowError("invented overflow"),
                subprocess.TimeoutExpired(ARGV, 30)),
        }
        for label, (first, reap) in cases.items():
            with self.subTest(label):
                events = []
                popen = ScriptedPopen(events, first, reap)
                with self.assertRaises(type(first)) as raised:
                    self.run_default(popen)
                self.assertIs(raised.exception, first)
                steps = [event[0] for event in events]
                self.assertIn(("kill_tree", FAKE_PID), events, events)
                self.assertIn("kill", steps, events)
                self.assertLess(steps.index("kill_tree"), steps.index("kill"), events)

    def test_normal_run_no_kill(self):
        events = []
        result = self.run_default(ScriptedPopen(events, None))
        steps = [event[0] for event in events]
        self.assertNotIn("kill_tree", steps, events)
        self.assertNotIn("kill", steps, events)
        self.assertEqual(set(result), {"returncode", "stdout", "stderr_tail", "duration_s"})
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"], "invented out")
        self.assertEqual(result["stderr_tail"], "invented err")

    def test_contract_names_limit(self):
        text = CONTRACT.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if "timeout_s" in line]
        self.assertTrue(any("86400" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()

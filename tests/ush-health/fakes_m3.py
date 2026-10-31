"""Shared fake and helpers for the M3 tests of skills/ush-health/scripts/health.py.

Public interface under test:
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``
- ``run_ps(job, script, out_path) -> (exit_code, stderr)`` is replaced by a fake
  that simulates PowerShell by writing a JSON file to ``out_path`` (or not).
- ``is_admin() -> bool`` is replaced by a lambda.

Every value here is invented; PowerShell is never started and the machine is
never read. All output goes to a temporary directory passed as ``--data-dir``.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def ok(payload):
    """PowerShell wrote ``payload`` as JSON and exited 0."""
    return ("ok", payload)


def failure(stderr="Invented PowerShell failure text.", code=1):
    """PowerShell exited with ``code``, wrote ``stderr`` and no output file."""
    return ("fail", code, stderr)


class FakePowerShell:
    """Stands in for run_ps. Any job without a response answers an empty list."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls = []

    @staticmethod
    def _write(out_path, payload):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Windows PowerShell 5.1 writes UTF-8 with a BOM.
        out_path.write_text(json.dumps(payload), encoding="utf-8-sig")

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        response = self.responses.get(job, ok([]))
        if response[0] == "ok":
            self._write(out_path, response[1])
            return 0, ""
        _, code, stderr = response
        return code, stderr

    def jobs(self):
        return [call[0] for call in self.calls]

    def script_of(self, job):
        scripts = [call[1] for call in self.calls if call[0] == job]
        if not scripts:
            raise AssertionError(f"job {job!r} was not run; jobs run: {self.jobs()}")
        return scripts[0]


class HealthTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.health = load_script("ush-health", "health")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def run_main(self, fake, admin=True, data_dir=None):
        """Run main and return (exit code, stdout text)."""
        data_dir = data_dir or self.data_dir()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.health.main(
                ["--data-dir", str(data_dir)],
                run_ps=fake,
                is_admin=lambda: admin,
                now=NOW,
            )
        return code, out.getvalue()

    def collect(self, fake, admin=True, data_dir=None):
        """Run main, require exit code 0 and return the parsed summary."""
        code, stdout = self.run_main(fake, admin=admin, data_dir=data_dir)
        self.assertEqual(code, 0, stdout[:300])
        try:
            summary = json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def source(self, summary, name):
        self.assertIsInstance(summary.get("sources"), list, summary.get("sources"))
        matches = [s for s in summary["sources"] if s.get("name") == name]
        self.assertEqual(len(matches), 1, f"source {name}: {summary['sources']}")
        return matches[0]

    def not_checked(self, summary):
        self.assertIsInstance(summary.get("not_checked"), list, summary.get("not_checked"))
        return summary["not_checked"]

    def not_checked_whats(self, summary):
        return [str(entry.get("what")) for entry in self.not_checked(summary)]

    def assert_unreadable_with_entry(self, summary, name):
        """Source ``name`` is unreadable with a reason and has a not_checked entry."""
        src = self.source(summary, name)
        self.assertEqual(src.get("status"), "unreadable", src)
        self.assertIsInstance(src.get("reason"), str, src)
        self.assertTrue(src["reason"].strip(), src)
        entries = [e for e in self.not_checked(summary) if e.get("what") == name]
        self.assertTrue(entries, f"no not_checked entry for {name}: {summary['not_checked']}")
        self.assertTrue(str(entries[0].get("reason") or "").strip(), entries[0])
        return src

"""Trend edge cases found in review (invented data only)."""

import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script


def NO_DUMPS():
    """Fake read_dumps: no memory dumps (the machine is never read)."""
    return {"status": "empty", "reason": None, "settings": None, "files": []}

# The package name has a hyphen, so import the shared helpers by string.
_trend = importlib.import_module("tests.ush-events.test_trend")


class OldestUnreadable(_trend.FakePowerShell):
    """The oldest-record query of the System log fails with an invented error."""

    def __call__(self, job, script, out_path):
        if job == "oldest:System":
            self.calls.append(job)
            return 1, "Invented failure: the RPC server is unavailable."
        return super().__call__(job, script, out_path)


class OldestWithoutTime(_trend.FakePowerShell):
    """The oldest System record comes back, but without a TimeCreated."""

    def __init__(self):
        super().__init__()
        record = dict(self.responses["oldest:System"][0])
        del record["TimeCreated"]
        self.responses["oldest:System"] = [record]


class TestUnknownCoverage(unittest.TestCase):
    def disk_group(self, fake):
        events = load_script("ush-events", "events")
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = events.main(["--data-dir", str(Path(tmp) / "ush-data")],
                                   run_ps=fake, now=_trend.NOW,
                                   read_dumps=NO_DUMPS)
            self.assertEqual(code, 0)
            summary = json.loads(out.getvalue())
        disk = [g for g in summary["groups"] if g["provider"] == "Invented-Disk"]
        self.assertEqual(len(disk), 1, summary["groups"])
        self.assertEqual((disk[0]["first_half"], disk[0]["second_half"]), (0, 5))
        return disk[0]

    def test_unreadable_oldest_record_makes_trend_unknown(self):
        self.assertEqual(self.disk_group(OldestUnreadable())["trend"], "unknown")

    def test_oldest_record_without_time_makes_trend_unknown(self):
        self.assertEqual(self.disk_group(OldestWithoutTime())["trend"], "unknown")


if __name__ == "__main__":
    unittest.main()

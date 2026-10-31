"""Shared PowerShell job runner: status of a job from its exit code and JSON file.

PowerShell is replaced by a fake run_ps; all data is invented.
"""

import codecs
import json
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

SCRIPT = "Get-InventedThing | ConvertTo-Json -Depth 3"


def fake_run_ps(exit_code, stderr="", payload=None, calls=None):
    """Return a run_ps that writes payload (UTF-8 with BOM, like PowerShell 5.1)."""

    def run_ps(job, script, out_path):
        if calls is not None:
            calls.append((job, script, out_path))
        if payload is not None:
            Path(out_path).write_bytes(codecs.BOM_UTF8 + payload.encode("utf-8"))
        return exit_code, stderr

    return run_ps


class TestRunJob(unittest.TestCase):
    def setUp(self):
        self.psrun = load_script("ush-common", "psrun")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out_path = Path(tmp.name).resolve() / "invented-job.json"

    def test_empty_list(self):
        calls = []
        result = self.psrun.run_job(fake_run_ps(0, "", "[]", calls), "invented-job", SCRIPT,
                                    self.out_path)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["rows"], [])

    def test_nonzero_exit(self):
        with self.subTest("error text becomes the trimmed reason"):
            run_ps = fake_run_ps(1, "  \r\nAccess to the invented resource is denied.\r\n  ")
            result = self.psrun.run_job(run_ps, "invented-job", SCRIPT, self.out_path)
            self.assertEqual(result["status"], "unreadable")
            self.assertEqual(result["rows"], [])
            reason = result["reason"]
            self.assertIsInstance(reason, str)
            self.assertIn("Access to the invented resource is denied.", reason)
            self.assertEqual(reason, reason.strip())

        with self.subTest("error text with an empty marker means empty"):
            marker = "No invented records were found"
            run_ps = fake_run_ps(1, f"Get-InventedThing : {marker} matching the query.\r\n")
            result = self.psrun.run_job(run_ps, "invented-job", SCRIPT, self.out_path,
                                        empty_markers=(marker,))
            self.assertEqual(result["status"], "empty")
            self.assertEqual(result["rows"], [])

    def test_missing_file(self):
        result = self.psrun.run_job(fake_run_ps(0, ""), "invented-job", SCRIPT, self.out_path)
        self.assertFalse(self.out_path.exists())
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(result["rows"], [])
        self.assertIsInstance(result["reason"], str)
        self.assertTrue(result["reason"].strip(), "expected a reason for the missing file")

    def test_single_object(self):
        row = {"Name": "InventedService", "Status": "Running", "StartType": 2}
        result = self.psrun.run_job(fake_run_ps(0, "", json.dumps(row)), "invented-job",
                                    SCRIPT, self.out_path)
        self.assertEqual(result["status"], "read")
        self.assertEqual(result["rows"], [row])


if __name__ == "__main__":
    unittest.main()

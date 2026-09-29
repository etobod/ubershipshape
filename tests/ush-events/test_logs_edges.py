"""logs.py edge cases found in review of milestone M4 (invented data only)."""

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

base = importlib.import_module("tests.ush-events.test_logs")


class TestStampCollision(base.LogsTestCase):
    def test_existing_export_file_is_not_recorded_again(self):
        data_dir = self.data_dir()
        first = base.FakeRun(log="Application")
        code, out, _ = self.run_logs(data_dir, first, base.FakeAdmin(False),
                                     "--export", "Application")
        self.assertEqual(code, 0, out)
        before = self.manifest(data_dir)
        self.assertEqual(len(before), 1)

        # A second run in the same second finds its target taken: epl never runs.
        second = base.FakeRun(log="Application")
        code, out, _ = self.run_logs(data_dir, second, base.FakeAdmin(False),
                                     "--export", "Application")
        self.assertEqual(code, 1, out)
        self.assertNotIn("export:Application", second.jobs())
        self.assertEqual(self.manifest(data_dir), before)


class TestClearReadBack(base.LogsTestCase):
    def test_log_not_emptied_is_not_cleared(self):
        # wevtutil cl exits 0 and the backup is complete, but the log still holds
        # every record: the read-back shows it was not cleared.
        fake = base.FakeRun(log="System",
                            rest_read={"Count": 260, "Minimum": 1001, "Maximum": 1260},
                            after={"RecordCount": 260, "OldestRecordId": 1001,
                                   "NewestRecordId": 1260})
        code, out, err = self.run_logs(self.data_dir(), fake, base.FakeAdmin(True),
                                       "--export", "System", "--clear")
        self.assertEqual(code, 1, out[:300] + err[:300])
        cleared = self.clear_results(out)
        self.assertEqual(len(cleared), 1, out[:600])
        self.assertIs(cleared[0]["cleared"], False, cleared[0])
        self.assertIn("260", cleared[0]["reason"])


OTHER_ENTRY = {"log": "Application", "kind": "export", "file": "invented-other.evtx",
               "verified": True}


class OverlappingRun(base.FakeRun):
    """While epl runs, another run appends its own entry to the manifest."""

    def __init__(self, manifest_path, **kwargs):
        super().__init__(**kwargs)
        self.manifest_path = manifest_path

    def __call__(self, job, command, out_path):
        if job.startswith("export:"):
            self.manifest_path.write_text(json.dumps([OTHER_ENTRY]), encoding="utf-8")
        return super().__call__(job, command, out_path)


class TestOverlappingRuns(base.LogsTestCase):
    def test_entry_of_an_overlapping_run_is_kept(self):
        data_dir = self.data_dir()
        fake = OverlappingRun(data_dir / "exports" / "manifest.json", log="System")
        code, out, _ = self.run_logs(data_dir, fake, base.FakeAdmin(False),
                                     "--export", "System")
        self.assertEqual(code, 0, out[:300])
        entries = self.manifest(data_dir)
        self.assertEqual(entries[0], OTHER_ENTRY)
        self.assertEqual([e["log"] for e in entries], ["Application", "System"])


class RaceLost(base.FakeRun):
    """Another run in the same second creates the file; this run's epl fails."""

    def __call__(self, job, command, out_path):
        if job.startswith("export:"):
            self.calls.append((job, command, out_path))
            self.export_path = Path(command[3])
            self.export_path.write_bytes(base.EXPORT_BYTES)
            return 1, "Invented: the file exists."
        return super().__call__(job, command, out_path)


class TestLostRace(base.LogsTestCase):
    def test_failed_epl_on_a_taken_name_writes_no_entry(self):
        data_dir = self.data_dir()
        fake = RaceLost(log="System")
        code, out, _ = self.run_logs(data_dir, fake, base.FakeAdmin(False),
                                     "--export", "System")
        self.assertEqual(code, 1, out[:300])
        manifest = data_dir / "exports" / "manifest.json"
        entries = self.manifest(data_dir) if manifest.exists() else []
        self.assertEqual(entries, [])


class TestPartialInjection(unittest.TestCase):
    def test_one_machine_function_alone_is_refused(self):
        logs = load_script("ush-events", "logs")

        def never(*args, **kwargs):
            raise AssertionError("a real machine function was called")

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(logs, "default_run", never), \
                mock.patch.object(logs, "default_is_admin", never):
            argv = ["--export", "System", "--data-dir", tmp]
            with self.assertRaises(TypeError):
                logs.main(argv, run=base.FakeRun(log="System"))
            with self.assertRaises(TypeError):
                logs.main(argv, is_admin=base.FakeAdmin(False))


if __name__ == "__main__":
    unittest.main()

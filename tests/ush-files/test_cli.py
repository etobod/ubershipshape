"""CLI tests for skills/ush-files/scripts/files.py (plan 096, M1): the summary limit and
the 35 000-character budget, gigabyte fields, the injection guard, a bad scan.json and
``--detail``.

The interface and the assumptions are described in ``fakes.py``; another scan.json is
injected by patching the module constant ``SCAN_FILE``. Every value is invented.
"""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from unittest import mock

from .fakes import (
    GIB,
    NOW,
    FakeMachine,
    FilesTestCase,
    machine_touched,
    norm,
)

SUMMARY_MAX_CHARS = 35000
USED_5_GIB = 5368709120


def flat_tree(count):
    """``count`` folders at depth 1, each with one file of a distinct size."""
    return {f"d{i:05d}": {"x.bin": i + 1} for i in range(count)}


def deep_tree(count):
    """``count`` folders at depth 3 under ``C:\\Users\\a``."""
    return {"Users": {"a": {f"d{i:05d}": {"x.bin": i + 1} for i in range(count)}}}


class TestCli(FilesTestCase):
    def test_budget_and_gb(self):
        usage = {"C": (100 * GIB, USED_5_GIB, 100 * GIB - USED_5_GIB)}

        # 99 folders at depth 1 plus the drive root C:\ give 100 folders.
        reference, _ = self.collect(FakeMachine({"C": flat_tree(99)}, usage=usage),
                                    scan=self.scan_file(summary_folders=100))

        with self.subTest("summary_folders limit"):
            summary, _ = self.collect(FakeMachine({"C": flat_tree(99)}, usage=usage),
                                      scan=self.scan_file(summary_folders=25))
            all_folders = self.items(self.detail(summary), "folders")
            self.assertEqual(len(all_folders), 100, [f.get("path") for f in all_folders][:5])
            self.assertEqual(len(self.items(summary, "folders")), 25)
            self.assertEqual(summary.get("truncated_folders"), 75, summary.get("truncated_folders"))
            # Cut by the limit only: no not_checked entry beyond the uncut run's.
            self.assertEqual(self.not_checked(summary), self.not_checked(reference))

        with self.subTest("used_gb"):
            drive = self.drive_item(summary, "C")
            self.assertEqual(drive.get("used_bytes"), USED_5_GIB, drive)
            self.assertEqual(drive.get("used_gb"), 5.0, drive)
            self.assertEqual(self.items(summary, "drives")[0].get("used_gb"), 5.0)

        with self.subTest("35 000-character budget"):
            count = 20000
            summary, stdout = self.collect(FakeMachine({"C": deep_tree(count)}, usage=usage),
                                           scan=self.scan_file(summary_folders=100000))
            self.assertLessEqual(len(stdout.strip()), SUMMARY_MAX_CHARS)
            truncated = summary.get("truncated_folders")
            self.assertIsInstance(truncated, int, summary.get("truncated_folders"))
            self.assertGreater(truncated, 0)
            all_folders = self.items(self.detail(summary), "folders")
            self.assertEqual(len(self.items(summary, "folders")) + truncated, len(all_folders))
            paths = {norm(f.get("path")) for f in all_folders}
            expected = {norm(f"C:\\Users\\a\\d{i:05d}") for i in range(count)}
            self.assertEqual(expected - paths, set())
            self.assertGreater(len(self.not_checked(summary)),
                               len(self.not_checked(reference)),
                               self.not_checked(summary))

    def test_guard_bad_data_detail(self):
        with self.subTest("partial injection"), \
                mock.patch.object(self.files, "default_list_drives", machine_touched), \
                mock.patch.object(self.files, "default_scan_dir", machine_touched), \
                mock.patch.object(self.files, "default_disk_usage", machine_touched), \
                mock.patch.object(self.files, "default_is_admin", machine_touched):
            fake = FakeMachine({"C": {"Data": {"a.bin": 1}}})
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    self.assertRaises(TypeError):
                self.files.main(["--data-dir", str(self.data_dir())],
                                scan_dir=fake.scan_dir, now=NOW)
            self.assertEqual(fake.calls, [])

        with self.subTest("scan.json without depth"):
            data_dir = self.data_dir()
            fake = FakeMachine({"C": {"Data": {"a.bin": 1}}})
            code, stdout, stderr = self.run_main(data_dir, fake,
                                                 scan=self.scan_file(drop=("depth",)))
            self.assertEqual(code, 2, (stdout[:300], stderr[-300:]))
            work = data_dir / "work"
            written = list(work.iterdir()) if work.exists() else []
            self.assertEqual(written, [])

        with self.subTest("--detail"):
            data_dir = self.data_dir()
            older = FakeMachine({"C": {"Data": {"a.bin": 10}, "top.bin": 3}})
            newer = FakeMachine({"C": {"Data": {"a.bin": 30}, "top.bin": 3}})
            self.collect(older, data_dir=data_dir, now=NOW)
            newer_summary, _ = self.collect(newer, data_dir=data_dir,
                                            now=NOW + timedelta(hours=1))
            first = [f for f in self.items(newer_summary, "folders") if f.get("id") == "f1"]
            self.assertEqual(len(first), 1, newer_summary.get("folders"))
            expected = first[0]

            code, stdout, stderr = self.run_main(data_dir, FakeMachine({"C": {}}),
                                                 now=NOW + timedelta(hours=2),
                                                 extra=["--detail", "f1"])
            self.assertEqual(code, 0, stderr[-300:])
            item = self.parse(stdout)
            self.assertIsInstance(item, dict, stdout[:300])
            self.assertEqual(norm(item.get("path")), norm(expected.get("path")), item)
            self.assertEqual(item.get("bytes"), expected.get("bytes"), item)
            # The newest run, not the older one: C:\ is 33 bytes there, 13 before.
            if norm(item.get("path")) == norm("C:\\"):
                self.assertEqual(item.get("bytes"), 33, item)

            code, stdout, stderr = self.run_main(data_dir, FakeMachine({"C": {}}),
                                                 now=NOW + timedelta(hours=2),
                                                 extra=["--detail", "f999"])
            self.assertEqual(code, 1, stdout[:300])


if __name__ == "__main__":
    unittest.main()

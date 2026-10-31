"""CLI tests for skills/ush-runall/scripts/runall.py (plan 098, M1): the injected
``run_child`` replaces the default one, and ``--detail`` / ``--detail-file`` read a
child item without running any child.

The interface and the assumptions are listed in ``test_runall.py``. In addition:
``--detail h2`` prints the detail item (with ``id`` and ``summary``) as JSON on stdout;
the newest ``runall-*.detail.json`` is the one written by the run with the later ``now``.
Every value is invented.
"""

import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .test_runall import NOW, FakeChildren, RunallTestCase, ok


class Recorder:
    """Records each call; refuses to do anything else."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError(f"called: {args!r} {kwargs!r}")


class TestCli(RunallTestCase):
    def test_detail_and_injection(self):
        data_dir = self.data_dir()
        default = Recorder()

        with mock.patch.object(self.runall, "default_run_child", default):
            older = FakeChildren(self.temp(), {"ush-events": ok(extra={"event_count": 111})})
            older_summary = self.collect(data_dir, older, now=NOW)
            newer = FakeChildren(self.temp(), {"ush-events": ok(extra={"event_count": 222})})
            newer_summary = self.collect(data_dir, newer, now=NOW + timedelta(hours=1))
        self.assertEqual(default.calls, [])
        self.assertTrue(older.calls)
        self.assertTrue(newer.calls)

        self.assertEqual(self.by_id(older_summary, "h2").get("skill"), "ush-events")
        older_file = Path(str(older_summary.get("detail_file")))
        newer_file = Path(str(newer_summary.get("detail_file")))
        self.assertNotEqual(older_file, newer_file)

        def run_detail(extra):
            child = Recorder()
            default = Recorder()
            with mock.patch.object(self.runall, "default_run_child", default):
                code, stdout, stderr = self.run_main(data_dir, child,
                                                     now=NOW + timedelta(hours=2), extra=extra)
            self.assertEqual(child.calls, [], extra)
            self.assertEqual(default.calls, [], extra)
            return code, stdout, stderr

        with self.subTest("--detail h2 reads the newest detail file"):
            code, stdout, stderr = run_detail(["--detail", "h2"])
            self.assertEqual(code, 0, stderr[-300:])
            item = self.parse(stdout)
            self.assertIsInstance(item, dict, stdout[:300])
            self.assertEqual(item.get("id"), "h2", item)
            self.assertEqual(item.get("summary"), newer.summaries["ush-events"])
            self.assertEqual(item["summary"].get("event_count"), 222)

        with self.subTest("--detail-file <older> --detail h2 reads that file"):
            code, stdout, stderr = run_detail(["--detail-file", str(older_file),
                                               "--detail", "h2"])
            self.assertEqual(code, 0, stderr[-300:])
            item = self.parse(stdout)
            self.assertIsInstance(item, dict, stdout[:300])
            self.assertEqual(item.get("id"), "h2", item)
            self.assertEqual(item.get("summary"), older.summaries["ush-events"])
            self.assertEqual(item["summary"].get("event_count"), 111)

        with self.subTest("--detail h9 is an unknown id"):
            code, stdout, stderr = run_detail(["--detail", "h9"])
            self.assertEqual(code, 1, (stdout[:300], stderr[-300:]))


if __name__ == "__main__":
    unittest.main()

"""CLI tests for skills/ush-processes/scripts/processes.py (plan 051, M1): a failed
``processes`` job, the injection guard and ``--detail``.

The interface is described in ``fakes.py``. PowerShell never starts; the guard test
replaces both module-level machine functions with one that raises ``AssertionError``.
Every value is invented.
"""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from unittest import mock

from .fakes import (
    NOW,
    FakePowerShell,
    ProcessesTestCase,
    failure,
    machine,
    machine_touched,
    proc,
)


class TestCli(ProcessesTestCase):
    def test_failure_guard_detail(self):
        with self.subTest("processes job failed"):
            responses = machine([proc(500, "shell.exe", r"C:\Apps\Shell\shell.exe", created=1)])
            responses["processes"] = failure("Invented: Win32_Process query failed.")
            code, stdout, stderr = self.run_main(self.data_dir(), FakePowerShell(responses))
            self.assertEqual(code, 0, stderr[:300])
            summary = self.parse(stdout)
            self.assertEqual(summary.get("groups"), [], summary)
            self.assertNotEqual(self.source(summary, "processes").get("status"), "read")
            self.assertGreaterEqual(len(self.notes_about(summary, "processes")), 1,
                                    self.not_checked(summary))

        with self.subTest("partial injection"), \
                mock.patch.object(self.processes, "default_run_ps", machine_touched), \
                mock.patch.object(self.processes, "default_is_admin", machine_touched):
            data_dir = self.data_dir()
            fake = FakePowerShell()
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    self.assertRaises(TypeError):
                self.processes.main(["--data-dir", str(data_dir)], run_ps=fake, now=NOW)
            self.assertEqual(fake.calls, [])
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    self.assertRaises(TypeError):
                self.processes.main(
                    ["--data-dir", str(data_dir)], is_admin=lambda: False, now=NOW
                )

        with self.subTest("--detail"):
            data_dir = self.data_dir()
            older = FakePowerShell(machine([
                proc(700, "oldapp.exe", r"C:\Apps\Old\oldapp.exe", created=1),
            ]))
            newer = FakePowerShell(machine([
                proc(800, "newapp.exe", r"C:\Apps\New\newapp.exe",
                     command_line=r'"C:\Apps\New\newapp.exe" --invented-profile=7',
                     created=2),
            ]))
            older_summary = self.collect(older, data_dir=data_dir, now=NOW)
            newer_summary = self.collect(newer, data_dir=data_dir, now=NOW + timedelta(hours=1))
            # Group ids are stable across runs (plan 108): the newer run's only group is
            # not g1 when the older run in the same data directory already gave g1 away.
            newer_id = newer_summary["groups"][0]["id"]
            self.assertEqual(older_summary["groups"][0]["id"], "g1", older_summary["groups"])
            self.assertEqual(newer_id, "g2", newer_summary["groups"])

            detail_fake = FakePowerShell()
            code, stdout, stderr = self.run_main(data_dir, detail_fake,
                                                 extra=["--detail", newer_id])
            self.assertEqual(code, 0, stderr[:300])
            self.assertEqual(detail_fake.calls, [])
            group = json.loads(stdout)
            self.assertIsInstance(group, dict, stdout[:300])
            self.assertEqual(group.get("id"), newer_id, group)
            self.assertEqual(group.get("name"), "newapp.exe", group)
            members = group.get("processes")
            self.assertIsInstance(members, list, group)
            self.assertEqual([p.get("pid") for p in members], [800], group)
            self.assertEqual(
                members[0].get("command_line"), r'"C:\Apps\New\newapp.exe" --invented-profile=7'
            )
            self.assertNotIn("oldapp", stdout)

            code, stdout, stderr = self.run_main(data_dir, detail_fake, extra=["--detail", "g99"])
            self.assertEqual(code, 1, stdout[:300])
            self.assertEqual(detail_fake.calls, [])

        with self.subTest("--detail-file reads the named run"):
            older_id = older_summary["groups"][0]["id"]
            extra = ["--detail", older_id, "--detail-file", older_summary.get("detail_file")]
            try:
                code, stdout, stderr = self.run_main(data_dir, detail_fake, extra=extra)
            except SystemExit as exc:
                self.fail(f"--detail-file was not accepted: {exc}")
            self.assertEqual(code, 0, stderr[:300])
            self.assertEqual(detail_fake.calls, [])
            self.assertEqual(json.loads(stdout).get("name"), "oldapp.exe", stdout[:300])


if __name__ == "__main__":
    unittest.main()

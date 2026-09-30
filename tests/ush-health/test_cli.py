"""CLI tests for skills/ush-health/scripts/health.py (milestone M2): the
injection guard and ``--detail``.

Public interface under test:
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``
- module-level ``default_run_ps`` and ``default_is_admin``, used only when neither
  machine function is injected.

PowerShell never starts; every value is invented.
"""

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from unittest import mock

from .fakes import NOW, FakePowerShell, HealthTestCase, disk, ok


def machine_touched(*args, **kwargs):
    raise AssertionError("a real machine function was called")


class TestGuard(HealthTestCase):
    def test_partial_injection_raises(self):
        data_dir = self.data_dir()
        with mock.patch.object(self.health, "default_run_ps", machine_touched), \
                mock.patch.object(self.health, "default_is_admin", machine_touched):
            with self.subTest("only run_ps injected"):
                fake = FakePowerShell()
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                        self.assertRaises(TypeError):
                    self.health.main(
                        ["--data-dir", str(data_dir)], run_ps=fake, now=NOW
                    )
                self.assertEqual(fake.calls, [])

            with self.subTest("only is_admin injected"), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    self.assertRaises(TypeError):
                self.health.main(
                    ["--data-dir", str(data_dir)], is_admin=lambda: True, now=NOW
                )


class TestDetail(HealthTestCase):
    def test_known_and_unknown_id(self):
        data_dir = self.data_dir()
        older = FakePowerShell({"physical_disks": ok([disk("0", "Invented Old Disk 1100")])})
        newer = FakePowerShell({"physical_disks": ok([disk("0", "Invented New Disk 2200")])})
        self.collect(older, data_dir=data_dir, now=NOW)
        self.collect(newer, data_dir=data_dir, now=NOW + timedelta(hours=1))

        detail_fake = FakePowerShell()
        code, stdout, stderr = self.run_main(
            data_dir, detail_fake, extra=["--detail", "k1"]
        )
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(detail_fake.calls, [])
        item = json.loads(stdout)
        self.assertIsInstance(item, dict, stdout[:300])
        self.assertIn("Invented New Disk 2200", stdout)
        self.assertNotIn("Invented Old Disk 1100", stdout)

        code, stdout, stderr = self.run_main(
            data_dir, detail_fake, extra=["--detail", "k99"]
        )
        self.assertEqual(code, 1, stdout[:300])
        self.assertTrue(stderr.strip(), "no message on stderr for an unknown id")
        self.assertEqual(detail_fake.calls, [])

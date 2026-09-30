"""CLI tests for skills/ush-inventory/scripts/inventory.py (plan 048, M2): the
injection guard and ``--detail``.

Public interface under test (see ``fakes.py``):
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``
- module-level ``default_run_ps`` and ``default_is_admin``, used only when neither
  machine function is injected.

PowerShell never starts; every value is invented.
"""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from unittest import mock

from .fakes import NOW, FakePowerShell, InventoryTestCase, ok, win32


def machine_touched(*args, **kwargs):
    raise AssertionError("a real machine function was called")


class TestGuard(InventoryTestCase):
    def test_partial_injection_raises(self):
        data_dir = self.data_dir()
        with mock.patch.object(self.inventory, "default_run_ps", machine_touched), \
                mock.patch.object(self.inventory, "default_is_admin", machine_touched):
            with self.subTest("only run_ps injected"):
                fake = FakePowerShell()
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                        self.assertRaises(TypeError):
                    self.inventory.main(
                        ["--data-dir", str(data_dir)], run_ps=fake, now=NOW
                    )
                self.assertEqual(fake.calls, [])

            with self.subTest("only is_admin injected"), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    self.assertRaises(TypeError):
                self.inventory.main(
                    ["--data-dir", str(data_dir)], is_admin=lambda: False, now=NOW
                )


class TestDetail(InventoryTestCase):
    def test_detail_file_needs_detail(self):
        """--detail-file alone is a usage error, not a collection that saves a baseline."""
        data_dir = self.data_dir()
        fake = FakePowerShell()
        with self.assertRaises(SystemExit) as raised:
            self.run_main(data_dir, fake, extra=("--detail-file", str(data_dir / "x.json")))
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(fake.calls, [])
        self.assertFalse((data_dir / "state").exists())

    def test_known_and_unknown_id(self):
        data_dir = self.data_dir()
        older = FakePowerShell({
            "win32_programs": ok([win32("InventedOld", "Invented Old App 1100")]),
            "msix_programs": ok([]),
        })
        newer = FakePowerShell({
            "win32_programs": ok([win32("InventedNew", "Invented New App 2200")]),
            "msix_programs": ok([]),
        })
        self.collect(older, data_dir=data_dir, now=NOW)
        self.collect(newer, data_dir=data_dir, now=NOW + timedelta(hours=1))

        detail_fake = FakePowerShell()
        code, stdout, stderr = self.run_main(data_dir, detail_fake, extra=["--detail", "a1"])
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(detail_fake.calls, [])
        item = json.loads(stdout)
        self.assertIsInstance(item, dict, stdout[:300])
        self.assertEqual(item.get("id"), "a1", item)
        self.assertEqual(item.get("name"), "Invented New App 2200", item)
        self.assertNotIn("Invented Old App 1100", stdout)

        code, stdout, stderr = self.run_main(data_dir, detail_fake, extra=["--detail", "a99"])
        self.assertEqual(code, 1, stdout[:300])
        self.assertTrue(stderr.strip(), "no message on stderr for an unknown id")
        self.assertEqual(detail_fake.calls, [])


if __name__ == "__main__":
    unittest.main()

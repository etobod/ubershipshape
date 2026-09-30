"""CLI tests for skills/ush-settings/scripts/settings.py (plan 050, M2): the injection guard
and ``--detail``.

Interface under test (see ``fakes.py`` for the full contract):

- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``; module-level
  ``default_run_ps`` and ``default_is_admin`` are used only when neither machine function
  is injected; exactly one injected raises ``TypeError`` before any job runs.
- ``--detail ID`` prints the item with that id from the newest
  ``<data dir>/work/settings-*.detail.json`` (sections ``settings``, ``changes``, ``usage``)
  and returns 0; an unknown id returns 1 with a message on stderr.

PowerShell never starts; every value is invented.
"""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from .fakes import (
    NOW,
    FakePowerShell,
    SettingsTestCase,
    loc,
    minutes,
    present,
    registry,
    registry_entry,
)

FIRST = loc("HKCU", "Software\\InventedVendor\\First", "InventedFirst", "preference")
SECOND = loc("HKCU", "Software\\InventedVendor\\Second", "InventedSecond", "preference")


def machine_touched(*args, **kwargs):
    raise AssertionError("a real machine function was called")


class TestGuard(SettingsTestCase):
    def test_partial_injection_raises(self):
        self.write_catalogue([
            registry_entry("invented_first", [FIRST], expected=[0], default=1),
        ])
        data_dir = self.data_dir()
        with mock.patch.object(self.settings, "default_run_ps", machine_touched), \
                mock.patch.object(self.settings, "default_is_admin", machine_touched):
            with self.subTest("only run_ps injected"):
                fake = FakePowerShell()
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                        self.assertRaises(TypeError):
                    self.settings.main(["--data-dir", str(data_dir)], run_ps=fake, now=NOW)
                self.assertEqual(fake.calls, [])

            with self.subTest("only is_admin injected"), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    self.assertRaises(TypeError):
                self.settings.main(
                    ["--data-dir", str(data_dir)], is_admin=lambda: False, now=NOW
                )


class TestDetail(SettingsTestCase):
    def test_known_and_unknown_id(self):
        self.write_catalogue([
            registry_entry("invented_first", [FIRST], expected=[0], default=1),
            registry_entry("invented_second", [SECOND], expected=[0], default=1),
        ])
        data_dir = self.data_dir()
        # Older run: only invented_first differs, so it is e1 there.
        older = FakePowerShell({"registry_values": registry(
            present(FIRST, 1), present(SECOND, 0))})
        # Newer run: only invented_second differs, so it is e1 in the newest detail file.
        newer = FakePowerShell({"registry_values": registry(
            present(FIRST, 0), present(SECOND, 1))})
        self.collect(older, data_dir=data_dir, now=minutes(0))
        self.collect(newer, data_dir=data_dir, now=minutes(1))

        detail_fake = FakePowerShell()
        code, stdout, stderr = self.run_main(data_dir, detail_fake, now=minutes(2),
                                             extra=["--detail", "e1"])
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(detail_fake.calls, [])
        self.assertIn('"e1"', stdout)
        item = self.parse(stdout)
        self.assertIsInstance(item, dict, stdout[:300])
        self.assertEqual(item.get("id"), "e1", item)
        self.assertEqual(item.get("entry"), "invented_second", item)
        self.assertNotIn("invented_first", stdout)

        code, stdout, stderr = self.run_main(data_dir, detail_fake, now=minutes(2),
                                             extra=["--detail", "e99"])
        self.assertEqual(code, 1, stdout[:300])
        self.assertTrue(stderr.strip(), "no message on stderr for an unknown id")
        self.assertEqual(detail_fake.calls, [])


if __name__ == "__main__":
    unittest.main()

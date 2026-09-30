"""Baseline comparison of skills/ush-settings/scripts/settings.py (plan 050, M2).

Interface under test (see ``fakes.py`` for the full contract):

- Several runs share one ``--data-dir``; each run's ``now`` is one minute later. The
  baseline is ``<data dir>/state/ush-settings.json``.
- Baseline source ``settings``: key = entry id, compared field ``effective``. The source is
  always ``read`` once the catalogue loaded; a failed job only marks its own entries as
  unread, so their saved ``effective`` is carried from the previous baseline and the next
  read gives no false change.
- ``changes`` items: ``id`` (``c1``...), ``key`` (entry id), ``change``, ``entry``, ``area``,
  ``title``, ``state``; ``before``/``after`` on ``changed``. Only ``changed`` comes from the
  ``settings`` source; keys added to or removed from the catalogue are counted in
  ``catalogue_changes`` ``{"added": n, "removed": n}``, not in ``changes``.
- ``wifi_adapter_value`` effective lists are sorted by ``driver_key``, so adapters in
  another order give no change.
- On the first run ``baseline.status`` is ``"none"``.

Every value is invented; PowerShell never starts.
"""

import unittest

from .fakes import (
    FakePowerShell,
    SettingsTestCase,
    fail,
    loc,
    minutes,
    ok,
    present,
    registry,
    registry_entry,
    wifi,
    wifi_entry,
)

TOGGLE = loc("HKCU", "Software\\InventedVendor\\Toggle", "InventedToggleEnabled",
             "preference")
KEEP = loc("HKCU", "Software\\InventedVendor\\Keep", "InventedKeep", "preference")
OLD = loc("HKCU", "Software\\InventedVendor\\Old", "InventedOld", "preference")
NEW = loc("HKCU", "Software\\InventedVendor\\New", "InventedNew", "preference")

ADAPTER_A = "InventedClass\\0001"
ADAPTER_B = "InventedClass\\0002"


def machine(toggle, wifi_rows):
    """Registry value of the toggle and the Wi-Fi rows, both jobs successful."""
    return FakePowerShell({
        "registry_values": registry(present(TOGGLE, toggle)),
        "wifi_adapter": ok(wifi_rows),
    })


class TestBaseline(SettingsTestCase):
    def setUp(self):
        super().setUp()
        self.write_catalogue([
            registry_entry("invented_toggle", [TOGGLE], expected=None, default=0),
            wifi_entry("invented_wifi_power", expected=None, default=0),
        ])

    def test_runs(self):
        data_dir = self.data_dir()
        adapters = [wifi(ADAPTER_A, 24), wifi(ADAPTER_B, 16)]

        with self.subTest(run="first"):
            summary = self.collect(machine(0, adapters), data_dir=data_dir, now=minutes(0))
            self.assertEqual(summary.get("baseline", {}).get("status"), "none",
                             summary.get("baseline"))
            self.assertEqual(self.changes(summary), [])

        with self.subTest(run="second, one value 0 -> 1"):
            summary = self.collect(machine(1, adapters), data_dir=data_dir, now=minutes(1))
            changes = self.changes(summary)
            self.assertEqual(len(changes), 1, changes)
            change = changes[0]
            self.assertEqual(change.get("id"), "c1", change)
            self.assertEqual(change.get("change"), "changed", change)
            self.assertEqual(change.get("entry"), "invented_toggle", change)
            self.assertEqual(change.get("key"), "invented_toggle", change)
            self.assertEqual(change.get("before"), 0, change)
            self.assertEqual(change.get("after"), 1, change)

        with self.subTest(run="third, same data"):
            summary = self.collect(machine(1, adapters), data_dir=data_dir, now=minutes(2))
            self.assertEqual(self.changes(summary), [])

        with self.subTest(run="fourth, same adapters in reverse order"):
            reversed_adapters = list(reversed(adapters))
            summary = self.collect(machine(1, reversed_adapters), data_dir=data_dir,
                                   now=minutes(3))
            self.assertEqual(self.changes(summary), [])

    def test_unread_no_false_changes(self):
        data_dir = self.data_dir()
        self.collect(machine(0, [wifi(ADAPTER_A, 24), wifi(ADAPTER_B, 16)]),
                     data_dir=data_dir, now=minutes(0))

        with self.subTest(run="registry_values failed, Wi-Fi changed"):
            fake = FakePowerShell({
                "registry_values": fail("Invented failure of the registry job."),
                "wifi_adapter": ok([wifi(ADAPTER_A, 24), wifi(ADAPTER_B, 24)]),
            })
            summary = self.collect(fake, data_dir=data_dir, now=minutes(1))
            toggle = self.detail_item(summary, "invented_toggle")
            self.assertEqual(toggle.get("state"), "not_read", toggle)
            self.assertIn("registry_values", self.not_checked_text(summary))

            changes = self.changes(summary)
            self.assertEqual([c.get("entry") for c in changes], ["invented_wifi_power"],
                             changes)
            self.assertEqual(changes[0].get("change"), "changed", changes[0])
            self.assertEqual(changes[0].get("before"), [24, 16], changes[0])
            self.assertEqual(changes[0].get("after"), [24, 24], changes[0])
            # An unread entry stays in the baseline: no false catalogue change either.
            self.assertEqual(summary.get("catalogue_changes"), {"added": 0, "removed": 0})

        with self.subTest(run="registry read again with the first run's value"):
            summary = self.collect(machine(0, [wifi(ADAPTER_A, 24), wifi(ADAPTER_B, 24)]),
                                   data_dir=data_dir, now=minutes(2))
            self.assertEqual(self.changes(summary), [])
            self.assertEqual(summary.get("catalogue_changes"), {"added": 0, "removed": 0})

    def test_catalogue_changes_not_machine_changes(self):
        data_dir = self.data_dir()
        fake = FakePowerShell({"registry_values": registry(
            present(KEEP, 1), present(OLD, 1), present(NEW, 1),
        )})
        self.write_catalogue([
            registry_entry("invented_keep", [KEEP], expected=None, default=0),
            registry_entry("invented_old", [OLD], expected=None, default=0),
        ])
        self.collect(fake, data_dir=data_dir, now=minutes(0))

        self.write_catalogue([
            registry_entry("invented_keep", [KEEP], expected=None, default=0),
            registry_entry("invented_new", [NEW], expected=None, default=0),
        ])
        summary = self.collect(fake, data_dir=data_dir, now=minutes(1))
        self.assertEqual(summary.get("catalogue_changes"), {"added": 1, "removed": 1},
                         summary.get("catalogue_changes"))
        self.assertEqual(self.changes(summary), [])


if __name__ == "__main__":
    unittest.main()

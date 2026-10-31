"""Optional features, capabilities and drivers of skills/ush-inventory/scripts/inventory.py
(plan 052, milestone M1, criteria K1-K8).

The interface these tests assume is listed in ``fakes.py`` and ``fakes_components.py``.
PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.

Extra assumption stated here: a baseline written by a run in which ``optional_features``
and ``drivers`` failed has no such sources (048 ``merge_sources``), which is the shape of a
baseline written before M1 (K6).
"""

import unittest
from datetime import timedelta

from .fakes import NOW, FakePowerShell, failure, id_number, ok, win32
from .fakes_components import (
    ABSENT,
    DISABLED,
    ENABLED,
    UNKNOWN,
    ComponentsTestCase,
    capability,
    driver,
    feature,
    windows_driver,
)


class TestFeatures(ComponentsTestCase):
    def test_states_and_listing(self):
        rows = [
            feature("InventedOn", ENABLED),
            feature("InventedOff", DISABLED),
            feature("InventedGone", ABSENT),
            feature("InventedUnknown", UNKNOWN),
            feature("InventedOdd", 7),
        ]
        summary = self.collect(FakePowerShell({"optional_features": ok(rows)}))

        listed = self.components(summary)
        self.assertEqual([item.get("key") for item in listed], ["feature:InventedOn"], listed)
        on = listed[0]
        self.assertEqual(on.get("kind"), "feature", on)
        self.assertEqual(on.get("name"), "InventedOn", on)
        self.assertEqual(on.get("state"), "enabled", on)
        self.assertEqual(id_number(on.get("id"), "f"), 1, on)

        counts = self.kind_counts(summary, "feature")
        for state, number in (("enabled", 1), ("disabled", 1), ("absent", 1), ("unread", 2)):
            self.assertEqual(counts.get(state), number, counts)

        detail = self.by_key(self.detail_list(summary, "components"))
        for key, state in (("feature:InventedOn", "enabled"),
                           ("feature:InventedOff", "disabled"),
                           ("feature:InventedGone", "absent")):
            item = detail.get(key)
            self.assertIsNotNone(item, sorted(map(str, detail)))
            self.assertEqual(item.get("state"), state, item)
            self.assertNotIn("state", item.get("unread_fields") or [], item)
        self.assertEqual(detail["feature:InventedOn"].get("caption"),
                         "Invented caption of InventedOn", detail["feature:InventedOn"])

        for key, number in (("feature:InventedUnknown", 4), ("feature:InventedOdd", 7)):
            item = detail.get(key)
            self.assertIsNotNone(item, sorted(map(str, detail)))
            self.assertIn("state", item, item)
            self.assertIsNone(item["state"], item)
            self.assertIn("state", item.get("unread_fields") or [], item)
            self.assertEqual(item.get("install_state"), number, item)

    def test_enabled_after_update_is_listed(self):
        data_dir = self.data_dir()
        first = [feature("InventedA", DISABLED), feature("InventedB", DISABLED)]
        second = [feature("InventedA", ENABLED), feature("InventedB", UNKNOWN),
                  feature("InventedC", ENABLED)]
        third = [feature("InventedA", ENABLED), feature("InventedB", DISABLED),
                 feature("InventedC", ENABLED)]

        self.collect(FakePowerShell({"optional_features": ok(first)}),
                     data_dir=data_dir, now=NOW)
        run2 = self.collect(FakePowerShell({"optional_features": ok(second)}),
                            data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("optional_features"), "compared",
                         self.comparison(run2))
        changes = self.by_key(self.changes_from(run2, "optional_features"))
        self.assertEqual(set(changes), {"feature:InventedA", "feature:InventedC"}, changes)
        enabled = changes["feature:InventedA"]
        self.assertEqual(enabled.get("change"), "changed", enabled)
        self.assertEqual(self.field_names(enabled), ["state"], enabled)
        added = changes["feature:InventedC"]
        self.assertEqual(added.get("change"), "added", added)

        run3 = self.collect(FakePowerShell({"optional_features": ok(third)}),
                            data_dir=data_dir, now=NOW + timedelta(days=2))
        self.assertEqual(self.comparison(run3).get("optional_features"), "compared",
                         self.comparison(run3))
        self.assertEqual(self.changes_from(run3, "optional_features"), [])


class TestCapabilities(ComponentsTestCase):
    def test_admin_only(self):
        rows = [capability("Invented.Tool~~~~0.0.1.0", "Installed"),
                capability("Invented.Extra~~~~0.0.1.0", "NotPresent")]

        plain_fake = FakePowerShell({"capabilities": ok(rows)})
        plain = self.collect(plain_fake, admin=False)
        self.assertNotIn("capabilities", plain_fake.jobs())
        source = self.assert_unreadable(plain, "capabilities")
        self.assertIn("requires administrator", source.get("reason"), source)
        self.assertEqual(self.comparison(plain).get("capabilities"), "not_read",
                         self.comparison(plain))
        self.assertEqual(len(self.notes_about_source(plain, "capabilities")), 1,
                         plain.get("not_checked"))

        admin_fake = FakePowerShell({"capabilities": ok(rows)})
        elevated = self.collect(admin_fake, admin=True)
        self.assertIn("capabilities", admin_fake.jobs())
        self.assertEqual(self.source(elevated, "capabilities").get("status"), "read")
        listed = self.by_key(self.components(elevated))
        installed = listed.get("capability:Invented.Tool~~~~0.0.1.0")
        self.assertIsNotNone(installed, sorted(map(str, listed)))
        self.assertEqual(installed.get("kind"), "capability", installed)
        self.assertEqual(installed.get("state"), "Installed", installed)
        self.assertNotIn("capability:Invented.Extra~~~~0.0.1.0", listed)
        counts = self.kind_counts(elevated, "capability")
        self.assertEqual(counts.get("NotPresent"), 1, counts)
        self.assertEqual(counts.get("Installed"), 1, counts)


class TestDrivers(ComponentsTestCase):
    def test_third_party_listed(self):
        rows = [
            driver("PCI\\VEN_1AAA&DEV_0001\\0001", "OEM3.INF",
                   device_name="Invented Alpha Controller", provider=None),
            driver("PCI\\VEN_1AAA&DEV_0002\\0002", "oem12.inf",
                   device_name="Invented Zulu Controller", date=None),
            windows_driver("USB\\VID_1BBB&PID_0001\\0003", "usbstor.inf"),
            windows_driver("ACPI\\INVENTED0001\\0004", "machine.inf"),
            driver("ROOT\\INVENTED\\0005", None, device_name="Invented Device Without Driver",
                   provider=None, version=None, date=None, signer=None),
        ]
        summary = self.collect(FakePowerShell({"drivers": ok(rows)}))

        listed = self.drivers(summary)
        self.assertEqual(
            [item.get("key") for item in listed],
            ["driver:PCI\\VEN_1AAA&DEV_0002\\0002", "driver:PCI\\VEN_1AAA&DEV_0001\\0001"],
            listed,
        )
        with_provider, without_provider = listed
        self.assertEqual(id_number(with_provider.get("id"), "d"), 1, with_provider)
        self.assertEqual(with_provider.get("device_name"), "Invented Zulu Controller")
        self.assertEqual(with_provider.get("class"), "SYSTEM", with_provider)
        self.assertEqual(with_provider.get("provider"), "Invented Hardware Vendor Ltd")
        self.assertEqual(with_provider.get("version"), "1.0.0.0", with_provider)
        self.assertEqual(with_provider.get("signer"),
                         "Invented Hardware Compatibility Publisher", with_provider)
        self.assertIn("date", with_provider, with_provider)
        self.assertIsNone(with_provider["date"], with_provider)
        self.assertIn("provider", without_provider, without_provider)
        self.assertIsNone(without_provider["provider"], without_provider)
        self.assertEqual(without_provider.get("date"), "2026-01-15", without_provider)

        self.assertEqual(self.own_counts(summary).get("drivers"), 2, self.own_counts(summary))
        self.assertEqual(self.component_counts(summary).get("drivers_without_inf"), 1,
                         self.component_counts(summary))

        detail = self.by_key(self.detail_list(summary, "drivers"))
        self.assertNotIn("driver:ROOT\\INVENTED\\0005", detail)
        for key in ("driver:PCI\\VEN_1AAA&DEV_0001\\0001", "driver:PCI\\VEN_1AAA&DEV_0002\\0002"):
            item = detail.get(key)
            self.assertIsNotNone(item, sorted(map(str, detail)))
            self.assertIs(item.get("own"), False, item)
            self.assertIs(item.get("third_party"), True, item)
        for key in ("driver:USB\\VID_1BBB&PID_0001\\0003", "driver:ACPI\\INVENTED0001\\0004"):
            item = detail.get(key)
            self.assertIsNotNone(item, sorted(map(str, detail)))
            self.assertIs(item.get("own"), True, item)
            self.assertIs(item.get("third_party"), False, item)

    def test_renumbered_inf_no_change(self):
        data_dir = self.data_dir()
        renumbered = "PCI\\VEN_1AAA&DEV_0010\\0010"
        updated = "PCI\\VEN_1AAA&DEV_0011\\0011"
        unplugged = "USB\\VID_1BBB&PID_0012\\0012"
        first = [
            driver(renumbered, "oem12.inf", device_name="Invented Renumbered Device"),
            driver(updated, "oem20.inf", device_name="Invented Updated Device",
                   version="2.0.0.0"),
            windows_driver(unplugged, "usbstor.inf", device_name="Invented Stick"),
        ]
        second = [
            driver(renumbered, "oem31.inf", device_name="Invented Renumbered Device"),
            driver(updated, "oem20.inf", device_name="Invented Updated Device",
                   version="2.1.0.0"),
        ]

        self.collect(FakePowerShell({"drivers": ok(first)}), data_dir=data_dir, now=NOW)
        run2 = self.collect(FakePowerShell({"drivers": ok(second)}), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("drivers"), "compared",
                         self.comparison(run2))
        changes = self.by_key(self.changes_from(run2, "drivers"))
        self.assertEqual(set(changes), {f"driver:{updated}"}, changes)
        change = changes[f"driver:{updated}"]
        self.assertEqual(change.get("change"), "changed", change)
        self.assertEqual(self.field_names(change), ["version"], change)
        self.assertNotIn(f"driver:{unplugged}",
                         {c.get("key") for c in self.changes(run2)})
        self.assertEqual(self.by_source(run2, "drivers").get("removed"), 1,
                         self.own_changes(run2))


class TestBaseline(ComponentsTestCase):
    def test_new_sources_no_wave(self):
        data_dir = self.data_dir()
        keep = win32("InventedKeep", "Invented App Keep", version="1.0.0")
        bump_old = win32("InventedBump", "Invented App Bump", version="1.0.0")
        bump_new = win32("InventedBump", "Invented App Bump", version="2.0.0")
        features = [feature("InventedFeatureOn", ENABLED),
                    feature("InventedFeatureOff", DISABLED)]
        drivers = [driver("PCI\\VEN_1AAA&DEV_0020\\0020", "oem5.inf"),
                   windows_driver("ACPI\\INVENTED0021\\0021", "machine.inf")]

        # A baseline without the M1 sources, as plan 048 wrote it.
        self.collect(FakePowerShell({
            "win32_programs": ok([keep, bump_old]),
            "optional_features": failure("Invented CIM failure"),
            "drivers": failure("Invented CIM failure"),
        }), data_dir=data_dir, now=NOW)

        now_data = {"win32_programs": ok([keep, bump_new]),
                    "optional_features": ok(features), "drivers": ok(drivers)}
        run2 = self.collect(FakePowerShell(now_data), data_dir=data_dir,
                            now=NOW + timedelta(days=1))
        comparison = self.comparison(run2)
        self.assertEqual(comparison.get("optional_features"), "no_baseline", comparison)
        self.assertEqual(comparison.get("drivers"), "no_baseline", comparison)
        self.assertEqual(comparison.get("capabilities"), "not_read", comparison)
        self.assertEqual(comparison.get("win32_programs"), "compared", comparison)
        self.assertEqual(self.changes_from(run2, "optional_features"), [])
        self.assertEqual(self.changes_from(run2, "drivers"), [])
        programs = self.by_key(self.changes_from(run2, "win32_programs"))
        self.assertEqual(set(programs), {"win32:hklm64:InventedBump"}, programs)
        self.assertEqual(programs["win32:hklm64:InventedBump"].get("change"), "changed")

        run3 = self.collect(FakePowerShell(now_data), data_dir=data_dir,
                            now=NOW + timedelta(days=2))
        comparison = self.comparison(run3)
        self.assertEqual(comparison.get("optional_features"), "compared", comparison)
        self.assertEqual(comparison.get("drivers"), "compared", comparison)
        self.assertEqual(self.changes_from(run3, "optional_features"), [])
        self.assertEqual(self.changes_from(run3, "drivers"), [])


class TestSources(ComponentsTestCase):
    def test_each_new_source_statuses(self):
        cases = {
            # source: (admin, single row, key, summary list holding it)
            "optional_features": (False, feature("InventedSingle", ENABLED),
                                  "feature:InventedSingle", "components"),
            "capabilities": (True, capability("Invented.Single~~~~0.0.1.0", "Installed"),
                             "capability:Invented.Single~~~~0.0.1.0", "components"),
            "drivers": (False, driver("PCI\\VEN_1AAA&DEV_0030\\0030", "oem7.inf"),
                        "driver:PCI\\VEN_1AAA&DEV_0030\\0030", "drivers"),
        }
        for name, (admin, row, key, list_name) in cases.items():
            with self.subTest(source=name, case="failed job"):
                summary = self.collect(
                    FakePowerShell({name: failure("Invented access failure 0x80070005")}),
                    admin=admin,
                )
                self.assert_unreadable(summary, name)
                self.assertTrue(self.notes_about_source(summary, name),
                                summary.get("not_checked"))
                for present in ("components", "component_counts", "drivers"):
                    self.assertIn(present, summary, sorted(summary))
                if name == "optional_features":
                    self.assertIsNone(summary["components"], summary["components"])
                    counts = self.component_counts(summary)
                    self.assertIn("feature", counts, counts)
                    self.assertIsNone(counts["feature"], counts)

            with self.subTest(source=name, case="single object"):
                summary = self.collect(FakePowerShell({name: ok(row)}), admin=admin)
                self.assertEqual(self.source(summary, name).get("status"), "read")
                keys = [item.get("key") for item in self.summary_list(summary, list_name)]
                self.assertIn(key, keys)

    def test_rows_without_key_are_not_empty(self):
        cases = {
            "optional_features": (False, feature(None, ENABLED)),
            "capabilities": (True, capability(None, "Installed")),
            "drivers": (False, driver(None, "oem7.inf")),
        }
        for name, (admin, row) in cases.items():
            with self.subTest(source=name):
                summary = self.collect(FakePowerShell({name: ok([row])}), admin=admin)
                self.assert_unreadable(summary, name)
                self.assertTrue(self.notes_about_source(summary, name),
                                summary.get("not_checked"))


class TestClean(ComponentsTestCase):
    def test_clean_machine_lists_no_drivers(self):
        features = [feature("InventedCleanOn", ENABLED),
                    feature("InventedCleanOff", DISABLED),
                    feature("InventedCleanGone", ABSENT)]
        drivers = [
            windows_driver("USB\\VID_1BBB&PID_0040\\0040", "usbstor.inf"),
            windows_driver("ACPI\\INVENTED0041\\0041", "machine.inf"),
            windows_driver("SCSI\\DISK&VEN_INVENTED\\0042", "disk.inf"),
        ]
        summary = self.collect(FakePowerShell({"optional_features": ok(features),
                                               "drivers": ok(drivers)}))

        self.assertEqual(self.drivers(summary), [])
        self.assertEqual(self.own_counts(summary).get("drivers"), 3, self.own_counts(summary))

        notes = self.m1_notes(summary)
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn("capabilities", str(notes[0].get("what")), notes)


if __name__ == "__main__":
    unittest.main()

"""Orphan driver packages: the ``driver_packages`` source of
skills/ush-inventory/scripts/inventory.py (plan 024, milestone M2, criteria K1-K5, K7, K8).

The interface these tests assume is listed in ``fakes.py``, ``fakes_components.py`` and
``fakes_driver_packages.py``. PowerShell never starts; every data dir lives in a
temporary directory; every value is invented.
"""

import io
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta

from .fakes import NOW, FakePowerShell, failure, ok
from .fakes_components import WINDOWS_PROVIDER, WINDOWS_SIGNER, driver, windows_driver
from .fakes_driver_packages import (
    BROKEN_XML,
    EXTENSION_GUID,
    MONITOR_GUID,
    USAGE_TEXT,
    DriverPackagesTestCase,
    package,
    package_key,
    store,
    store_text,
    store_xml,
)

MOUSE = package("oem3.inf", "inventedmouse.inf", version="1.2.3.4", date="03/14/2024")
PAD = package("oem12.inf", "inventedpad.inf", class_name="HIDClass", version="2.0.1.0",
              date="11/02/2025")
MONITOR = package("oem40.inf", "inventedmonitor.inf", provider="Invented Display Ltd",
                  class_name="Monitor", class_guid=MONITOR_GUID, version="1.0.0.7",
                  date="06/30/2023", signer="Invented Display Signer")


class TestDriverPackages(DriverPackagesTestCase):
    def block(self, data_dir, item_id, detail_file):
        """Run ``--block <id> --detail-file <file>``; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = self.inventory.main(
                    ["--data-dir", str(data_dir), "--block", item_id,
                     "--detail-file", str(detail_file)],
                    run_ps=FakePowerShell(), is_admin=lambda: False, now=NOW)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def test_orphans_listed(self):
        fake = FakePowerShell({
            "driver_packages": store([MOUSE, PAD, MONITOR]),
            # The device row names the INF in another case than the store.
            "drivers": ok([driver("HID\\VID_1CCC&PID_0001\\0001", "OEM12.INF",
                                  device_name="Invented Touch Pad",
                                  device_class="HIDClass")]),
        })
        summary = self.collect(fake)
        self.assertIn("driver_packages", fake.jobs())
        self.assertEqual(self.source(summary, "driver_packages").get("status"), "read",
                         self.source(summary, "driver_packages"))

        listed = self.by_key(self.packages(summary))
        self.assertEqual(set(listed), {package_key(MOUSE), package_key(MONITOR)}, listed)
        for pkg in (MOUSE, MONITOR):
            self.assert_package(listed[package_key(pkg)], pkg, False)
        ids = [item.get("id") for item in listed.values()]
        self.assertEqual(len(set(ids)), 2, ids)

        counts = self.component_counts(summary)
        self.assertEqual(counts.get("driver_packages"), 3, counts)
        self.assertEqual(counts.get("driver_packages_without_device"), 2, counts)

    def test_clean_store_lists_nothing(self):
        with self.subTest(case="every third-party package has a present device"):
            audio = package("oem5.inf", "inventedaudio.inf", class_name="MEDIA",
                            version="6.0.1.2", date="01/20/2026")
            net = package("oem6.inf", "inventednet.inf", class_name="Net",
                          version="12.7.3.1", date="02/11/2026")
            summary = self.collect(FakePowerShell({
                "driver_packages": store([audio, net]),
                "drivers": ok([
                    driver("HDAUDIO\\FUNC_01&VEN_1DDD\\0001", "oem5.inf",
                           device_name="Invented Audio", device_class="MEDIA"),
                    driver("PCI\\VEN_1DDD&DEV_0002\\0002", "Oem6.inf",
                           device_name="Invented Network Adapter", device_class="Net"),
                    windows_driver("ACPI\\INVENTED0003\\0003", "machine.inf"),
                ]),
            }))
            self.assertEqual(self.source(summary, "driver_packages").get("status"), "read")
            self.assertEqual(self.packages(summary), [])
            self.assertEqual(self.package_notes(summary), [], summary.get("not_checked"))

        with self.subTest(case="only Windows packages"):
            inbox = package("inventedinbox.inf", "inventedinbox.inf",
                            provider=WINDOWS_PROVIDER, class_name="System",
                            signer=WINDOWS_SIGNER)
            summary = self.collect(FakePowerShell({
                "driver_packages": store([inbox]),
                "drivers": ok([windows_driver("ACPI\\INVENTED0004\\0004",
                                              "inventedinbox.inf")]),
            }))
            self.assertEqual(self.source(summary, "driver_packages").get("status"), "empty",
                             self.source(summary, "driver_packages"))
            self.assertEqual(self.packages(summary), [])
            self.assertEqual(self.package_notes(summary), [], summary.get("not_checked"))

    def test_unreadable_store(self):
        cases = {
            "failed job": failure("Invented job failure 0x80070005"),
            "refused /format": store_text(USAGE_TEXT, exit_code=87),
            "exit code other than 0": store([MOUSE], exit_code=5),
            "broken XML": store_text(BROKEN_XML, exit_code=0),
            "not XML": store_text(USAGE_TEXT, exit_code=0),
        }
        for case, response in cases.items():
            with self.subTest(case=case):
                summary = self.collect(FakePowerShell({
                    "driver_packages": response,
                    "drivers": ok([driver("PCI\\VEN_1AAA&DEV_0050\\0050", "oem99.inf")]),
                }))
                self.assert_unreadable(summary, "driver_packages")
                self.assertTrue(self.package_notes(summary), summary.get("not_checked"))
                self.assertIn("driver_packages", summary, sorted(summary))
                self.assertIsNone(summary["driver_packages"], summary["driver_packages"])

    def test_package_without_published_name_kept(self):
        # A listing holds third-party packages only: a package whose published name
        # is not read keeps its key, so it is neither dropped as a Windows package
        # nor reported as removed against the baseline, and it is never listed as
        # without a device.
        data_dir = self.data_dir()
        devices = ok([driver("PCI\\VEN_1AAA&DEV_0050\\0050", "oem99.inf")])
        self.collect(FakePowerShell({"driver_packages": store([MOUSE, PAD]),
                                     "drivers": devices}),
                     data_dir=data_dir, now=NOW)
        text = store_xml([MOUSE, PAD])
        nameless = text.replace(' DriverName="oem3.inf"', "", 1)
        self.assertNotEqual(nameless, text)
        summary = self.collect(FakePowerShell({
            "driver_packages": store_text(nameless, exit_code=0),
            "drivers": devices,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        source = [s for s in summary["sources"] if s["name"] == "driver_packages"]
        self.assertEqual([s["status"] for s in source], ["read"], source)
        detail = self.detail_packages(summary)
        self.assertEqual(set(detail), {package_key(MOUSE), package_key(PAD)}, detail)
        mouse = detail[package_key(MOUSE)]
        self.assertIsNone(mouse.get("published_name"), mouse)
        self.assertIn("published_name", mouse.get("unread_fields") or [], mouse)
        self.assertIsNone(mouse.get("present_device"), mouse)
        self.assertEqual(set(self.by_key(self.packages(summary))), {package_key(PAD)})
        changes = self.by_key(self.changes_from(summary, "driver_packages"))
        self.assertNotIn(package_key(MOUSE), changes, changes)

    def test_drivers_unread_no_orphans(self):
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, PAD]),
            "drivers": failure("Invented CIM failure"),
        }))
        self.assert_unreadable(summary, "drivers")
        self.assertIn("driver_packages", summary, sorted(summary))
        self.assertIsNone(summary["driver_packages"], summary["driver_packages"])

        notes = self.package_notes(summary)
        self.assertTrue(
            any(re.search(r"(?i)device|\bdrivers\b",
                          f"{note.get('what')} {note.get('reason')}") for note in notes),
            summary.get("not_checked"))

        detail = self.detail_packages(summary)
        self.assertEqual(set(detail), {package_key(MOUSE), package_key(PAD)}, detail)
        for pkg in (MOUSE, PAD):
            self.assert_package(detail[package_key(pkg)], pkg, None)

    def test_versions_and_reinstall(self):
        data_dir = self.data_dir()
        pad_old = package("oem20.inf", "inventedpad.inf", class_name="HIDClass",
                          version="2.0.0.0", date="05/01/2025")
        pad_new = package("oem21.inf", "inventedpad.inf", class_name="HIDClass",
                          version="2.1.0.0", date="09/15/2025")
        cam_old = package("oem30.inf", "inventedcam.inf", class_name="Camera",
                          version="3.0.0.0", date="01/10/2025")
        cam_new = package("oem31.inf", "inventedcam.inf", class_name="Camera",
                          version="3.1.0.0", date="08/22/2025")
        mouse_first = package("oem10.inf", "inventedmouse.inf", version="1.0.0.0",
                              date="02/02/2024")
        mouse_again = dict(mouse_first, published="oem55.inf")
        devices = ok([driver("HID\\VID_1CCC&PID_0021\\0021", "oem21.inf",
                             device_name="Invented Touch Pad", device_class="HIDClass")])

        run1 = self.collect(FakePowerShell({
            "driver_packages": store([mouse_first, pad_old, pad_new, cam_old]),
            "drivers": devices,
        }), data_dir=data_dir, now=NOW)

        # Two versions of one package: both kept, only the unused one listed.
        detail1 = self.detail_packages(run1)
        self.assert_package(detail1.get(package_key(pad_old)), pad_old, False)
        self.assert_package(detail1.get(package_key(pad_new)), pad_new, True)
        listed1 = self.by_key(self.packages(run1))
        self.assertEqual(set(listed1),
                         {package_key(mouse_first), package_key(pad_old),
                          package_key(cam_old)}, listed1)

        run2 = self.collect(FakePowerShell({
            "driver_packages": store([mouse_again, pad_old, pad_new, cam_new]),
            "drivers": devices,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("driver_packages"), "compared",
                         self.comparison(run2))
        # Installed again under a new oem number: same key, same id.
        detail2 = self.detail_packages(run2)
        mouse_key = package_key(mouse_first)
        self.assertEqual(package_key(mouse_again), mouse_key)
        self.assert_package(detail2.get(mouse_key), mouse_again, False)
        self.assertEqual(detail2[mouse_key].get("id"), detail1[mouse_key].get("id"),
                         (detail1[mouse_key], detail2[mouse_key]))

        changes = self.by_key(self.changes_from(run2, "driver_packages"))
        self.assertNotIn(mouse_key, changes, changes)
        self.assertEqual(set(changes), {package_key(cam_old), package_key(cam_new)}, changes)
        self.assertEqual(changes[package_key(cam_new)].get("change"), "added",
                         changes[package_key(cam_new)])
        self.assertEqual(changes[package_key(cam_old)].get("change"), "removed",
                         changes[package_key(cam_old)])

    def test_extension_and_idless_rows_not_orphans(self):
        extension = package("oem60.inf", "inventedmonitorext.inf",
                            provider="Invented Display Ltd", class_name="Extension",
                            class_guid=EXTENSION_GUID, version="1.0.2.0",
                            date="04/04/2025", signer="Invented Display Signer")
        idless = package("oem61.inf", "inventedhelper.inf", class_name="System",
                         version="4.4.0.1", date="07/07/2025")
        device = package("oem62.inf", "inventedmonitor.inf",
                         provider="Invented Display Ltd", class_name="Monitor",
                         class_guid=MONITOR_GUID, version="1.0.0.9", date="04/04/2025",
                         signer="Invented Display Signer")
        summary = self.collect(FakePowerShell({
            "driver_packages": store([extension, idless, device]),
            "drivers": ok([
                driver("DISPLAY\\INV0001\\0001", "oem62.inf",
                       device_name="Invented Monitor", device_class="Monitor"),
                driver(None, "OEM61.inf", device_name="Invented Helper",
                       device_class="System"),
            ]),
        }))

        self.assertEqual(self.packages(summary), [])
        detail = self.detail_packages(summary)
        self.assert_package(detail.get(package_key(extension)), extension, None)
        self.assert_package(detail.get(package_key(idless)), idless, True)
        self.assert_package(detail.get(package_key(device)), device, True)

    def test_detail_section_and_no_block(self):
        data_dir = self.data_dir()
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, PAD]),
            "drivers": ok([driver("HID\\VID_1CCC&PID_0001\\0001", "oem12.inf",
                                  device_name="Invented Touch Pad",
                                  device_class="HIDClass")]),
        }), data_dir=data_dir)

        detail = self.detail_packages(summary)
        self.assertEqual(set(detail), {package_key(MOUSE), package_key(PAD)}, detail)
        self.assert_package(detail[package_key(MOUSE)], MOUSE, False)
        self.assert_package(detail[package_key(PAD)], PAD, True)
        self.assertIn("o1", {item.get("id") for item in detail.values()}, detail)

        code, stdout, stderr = self.block(data_dir, "o1", summary.get("detail_file"))
        self.assertRegex(stdout, r"(?m)^\s*#\s*o1\s*:\s*no block\s*:", stdout or stderr)
        commands = [line for line in stdout.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        self.assertEqual(commands, [], stdout)
        self.assertEqual(code, 1, stdout[:300] or stderr[:300])


class TestDriverPackagesBaseline(DriverPackagesTestCase):
    """TEST-PLAN (b) for a new source in a diff skill (added by loc-qa, plan 024)."""

    def test_single_package_store(self):
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE]),
            "drivers": ok([driver("PCI\\VEN_1AAA&DEV_0050\\0050", "oem99.inf")]),
        }))
        self.assertEqual(self.source(summary, "driver_packages").get("status"), "read")
        listed = self.by_key(self.packages(summary))
        self.assertEqual(set(listed), {package_key(MOUSE)}, listed)
        self.assert_package(listed[package_key(MOUSE)], MOUSE, False)

    def test_first_run_unreadable_run_and_carry_over(self):
        data_dir = self.data_dir()
        devices = ok([driver("HID\\VID_1CCC&PID_0001\\0001", "oem12.inf",
                             device_name="Invented Touch Pad", device_class="HIDClass")])

        run1 = self.collect(FakePowerShell({"driver_packages": store([MOUSE, PAD]),
                                            "drivers": devices}),
                            data_dir=data_dir, now=NOW)
        with self.subTest(point="first run: no comparison, no changes"):
            self.assertEqual(self.comparison(run1).get("driver_packages"), "no_baseline",
                             self.comparison(run1))
            self.assertEqual(self.changes_from(run1, "driver_packages"), [])
        first_ids = {key: item.get("id")
                     for key, item in self.detail_packages(run1).items()}

        run2 = self.collect(FakePowerShell({
            "driver_packages": failure("Invented job failure 0x80070005"),
            "drivers": devices,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))
        with self.subTest(point="unreadable source: not compared, no changes"):
            self.assert_unreadable(run2, "driver_packages")
            self.assertNotEqual(self.comparison(run2).get("driver_packages"), "compared",
                                self.comparison(run2))
            self.assertEqual(self.changes_from(run2, "driver_packages"), [])

        run3 = self.collect(FakePowerShell({"driver_packages": store([MOUSE, PAD]),
                                            "drivers": devices}),
                            data_dir=data_dir, now=NOW + timedelta(days=2))
        with self.subTest(point="items carried over the unreadable run"):
            self.assertEqual(self.comparison(run3).get("driver_packages"), "compared",
                             self.comparison(run3))
            self.assertEqual(self.changes_from(run3, "driver_packages"), [])
            third_ids = {key: item.get("id")
                         for key, item in self.detail_packages(run3).items()}
            self.assertEqual(third_ids, first_ids)


if __name__ == "__main__":
    unittest.main()

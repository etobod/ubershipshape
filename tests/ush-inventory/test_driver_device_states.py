"""Device states of driver packages from every device Windows knows: the ``devices``
source of skills/ush-inventory/scripts/inventory.py (plan 051, milestone M1, criteria K1
to K7 and K9).

The interface these tests assume is listed in ``fakes.py``, ``fakes_components.py`` and
``fakes_driver_packages.py`` (the ``devices`` job answer and its ``last_removal`` field).
The ``drivers`` job answers nothing here, so a state can only come from ``devices``.
PowerShell never starts; every data dir lives in a temporary directory; every value is
invented.
"""

import json
import unittest

from .fakes import FakePowerShell, failure
from .fakes_driver_packages import (
    EXTENSION_GUID,
    DriverPackagesTestCase,
    device,
    devices_answer,
    devices_text,
    package,
    package_key,
    store,
)

MOUSE = package("oem3.inf", "inventedmouse.inf", version="1.2.3.4", date="03/14/2024")
WEBCAM = package("oem12.inf", "inventedwebcam.inf", class_name="Camera",
                 class_guid="{00000000-0000-0000-0000-00000000a003}",
                 version="2.0.1.0", date="11/02/2025")
TABLET = package("oem40.inf", "inventedtablet.inf", class_name="HIDClass",
                 version="1.0.0.7", date="06/30/2023")

MOUSE_DEVICE_ID = "USB\\VID_0000&PID_0001\\0000"
WEBCAM_DEVICE_ID = "USB\\VID_0000&PID_0002\\0000"
WINDOWS_DEVICE_ID = "ACPI\\INVENTED0003\\0000"

STARTED_MOUSE = device(MOUSE_DEVICE_ID, "oem3.inf", "Started", name="Invented Mouse")
DISCONNECTED_WEBCAM = device(WEBCAM_DEVICE_ID, "oem12.inf", "Disconnected",
                             name="Invented Webcam", class_name="Camera",
                             class_guid="{00000000-0000-0000-0000-00000000a003}")
WINDOWS_DEVICE = device(WINDOWS_DEVICE_ID, "inventedmachine.inf", "Started",
                        name="Invented System Board", class_name="System",
                        class_guid="{00000000-0000-0000-0000-00000000a004}",
                        manufacturer="Invented Windows Provider")

WEBCAM_REMOVED = "2026-05-04"

UNKNOWN_STATUS = "Invented Unknown Status"
EXTENSION = package("oem55.inf", "inventedextension.inf", class_name="Extension",
                    class_guid=EXTENSION_GUID, version="3.1.0.0", date="01/20/2025")

UNREAD_TEXT = (
    "Invented PnP Utility\r\n\r\n"
    "Invented usage text: the listing could not be produced.\r\n"
)


class DeviceStatesTestCase(DriverPackagesTestCase):
    def detail_package(self, summary, pkg):
        detail = self.detail_packages(summary)
        self.assertIn(package_key(pkg), detail, detail)
        return detail[package_key(pkg)]


class TestStates(DeviceStatesTestCase):
    def test_present_device(self):
        """K1: a package named by a ``Started`` device is ``present`` and not listed."""
        fake = FakePowerShell({
            "driver_packages": store([MOUSE, TABLET]),
            "devices": devices_answer([STARTED_MOUSE, WINDOWS_DEVICE]),
        })
        summary = self.collect(fake)
        self.assertIn("devices", fake.jobs())
        self.assertEqual(self.source(summary, "devices").get("status"), "read",
                         self.source(summary, "devices"))

        mouse = self.detail_package(summary, MOUSE)
        self.assertEqual(mouse.get("device_state"), "present", mouse)

        listed = self.by_key(self.packages(summary))
        self.assertNotIn(package_key(MOUSE), listed, listed)
        # The control in the same run: the package no device names is listed.
        self.assertIn(package_key(TABLET), listed, listed)

    def test_non_present_device_named(self):
        """K2: a package named only by a ``Disconnected`` device is ``non_present`` and
        names that device without its instance id."""
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, WEBCAM]),
            "devices": devices_answer([STARTED_MOUSE, DISCONNECTED_WEBCAM],
                                      last_removal={WEBCAM_DEVICE_ID: WEBCAM_REMOVED}),
        }))
        expected = [{"device_name": "Invented Webcam", "class": "Camera",
                     "status": "Disconnected", "last_removal": WEBCAM_REMOVED}]

        webcam = self.detail_package(summary, WEBCAM)
        self.assertEqual(webcam.get("device_state"), "non_present", webcam)
        self.assertEqual(webcam.get("devices"), expected, webcam)

        listed = self.by_key(self.packages(summary))
        self.assertIn(package_key(WEBCAM), listed, listed)
        item = listed[package_key(WEBCAM)]
        self.assertEqual(item.get("device_state"), "non_present", item)
        self.assertEqual(item.get("devices"), expected, item)

        text = json.dumps(summary, ensure_ascii=False)
        for instance_id in (WEBCAM_DEVICE_ID, MOUSE_DEVICE_ID):
            self.assertNotIn(instance_id, text)
            self.assertNotIn(json.dumps(instance_id)[1:-1], text)
            self.assertNotIn(instance_id.split("\\")[1], text)

    def test_no_device_found(self):
        """K3: a package named by no device is ``no_device_found``."""
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, TABLET]),
            "devices": devices_answer([STARTED_MOUSE, WINDOWS_DEVICE]),
        }))
        self.assertEqual(self.source(summary, "devices").get("status"), "read",
                         self.source(summary, "devices"))
        tablet = self.detail_package(summary, TABLET)
        self.assertEqual(tablet.get("device_state"), "no_device_found", tablet)

        listed = self.by_key(self.packages(summary))
        self.assertIn(package_key(TABLET), listed, listed)
        self.assertEqual(listed[package_key(TABLET)].get("device_state"),
                         "no_device_found", listed[package_key(TABLET)])

    def test_present_wins(self):
        """K4: a package named by a ``Disconnected`` and a ``Started`` device is
        ``present`` and not listed."""
        started_webcam = device("USB\\VID_0000&PID_0003\\0000", "oem12.inf", "Started",
                                name="Invented Webcam Two", class_name="Camera",
                                class_guid="{00000000-0000-0000-0000-00000000a003}")
        orders = {
            "disconnected first": [DISCONNECTED_WEBCAM, started_webcam],
            "started first": [started_webcam, DISCONNECTED_WEBCAM],
        }
        for order, devices in orders.items():
            with self.subTest(order=order):
                summary = self.collect(FakePowerShell({
                    "driver_packages": store([MOUSE, WEBCAM, TABLET]),
                    "devices": devices_answer(
                        devices, last_removal={WEBCAM_DEVICE_ID: WEBCAM_REMOVED}),
                }))
                webcam = self.detail_package(summary, WEBCAM)
                self.assertEqual(webcam.get("device_state"), "present", webcam)
                listed = self.by_key(self.packages(summary))
                self.assertNotIn(package_key(WEBCAM), listed, listed)
                # The control in the same run: the package no device names is listed.
                self.assertIn(package_key(TABLET), listed, listed)

    def test_disconnected_device_of_other_class(self):
        """A disconnected device whose class differs from the package's class (a reused
        oem number) is no evidence: the state is null with the reason, the package is not
        listed and the device is not named; a device of the same class, in any case, is."""
        printer = package("oem12.inf", "inventedprinter.inf", class_name="Printer",
                          version="3.0.0.0", date="01/02/2026")
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, printer]),
            "devices": devices_answer([STARTED_MOUSE, DISCONNECTED_WEBCAM],
                                      last_removal={WEBCAM_DEVICE_ID: WEBCAM_REMOVED}),
        }))
        item = self.detail_package(summary, printer)
        self.assertIsNone(item.get("device_state"), item)
        self.assertIn("another class", item.get("device_state_reason") or "", item)
        self.assertNotIn("devices", item)
        listed = self.by_key(self.packages(summary))
        self.assertNotIn(package_key(printer), listed, listed)
        notes = self.notes_about_source(summary, "driver_packages device_class")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertTrue(str(notes[0].get("reason")).startswith("1 package(s)"), notes)

        same_class = package("oem12.inf", "inventedwebcam.inf", class_name="camera",
                             version="2.0.1.0", date="11/02/2025")
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, same_class]),
            "devices": devices_answer([STARTED_MOUSE, DISCONNECTED_WEBCAM]),
        }))
        self.assertEqual(self.detail_package(summary, same_class).get("device_state"),
                         "non_present")
        self.assertEqual(self.notes_about_source(summary, "driver_packages device_class"),
                         [], summary.get("not_checked"))

    def test_last_removal_missing(self):
        """K7: a last removal date that was not read is null, not a guess."""
        cases = {
            "no entry for the device": {},
            "entry null": {WEBCAM_DEVICE_ID: None},
        }
        expected = [{"device_name": "Invented Webcam", "class": "Camera",
                     "status": "Disconnected", "last_removal": None}]
        for case, last_removal in cases.items():
            with self.subTest(case=case):
                summary = self.collect(FakePowerShell({
                    "driver_packages": store([MOUSE, WEBCAM]),
                    "devices": devices_answer([STARTED_MOUSE, DISCONNECTED_WEBCAM],
                                              last_removal=last_removal),
                }))
                webcam = self.detail_package(summary, WEBCAM)
                self.assertEqual(webcam.get("device_state"), "non_present", webcam)
                self.assertEqual(webcam.get("devices"), expected, webcam)
                listed = self.by_key(self.packages(summary))
                self.assertIn(package_key(WEBCAM), listed, listed)
                self.assertEqual(listed[package_key(WEBCAM)].get("devices"), expected,
                                 listed[package_key(WEBCAM)])


class TestSource(DeviceStatesTestCase):
    def test_unreadable_devices(self):
        """K5: an unreadable ``devices`` source gives every package state null with a
        reason, the summary list null and a ``not_checked`` entry."""
        with self.subTest(case="clean control: a read source gives no devices entry"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, WEBCAM]),
                "devices": devices_answer([STARTED_MOUSE]),
            }))
            self.assertEqual(self.source(summary, "devices").get("status"), "read")
            self.assertEqual(self.notes_about_source(summary, "devices"), [],
                             summary.get("not_checked"))

        cases = {
            "failed job": failure("Invented job failure 0x80070005"),
            "exit code 1": devices_answer([STARTED_MOUSE], exit_code=1),
            "text that is no XML": devices_text(UNREAD_TEXT, exit_code=0),
        }
        for case, response in cases.items():
            with self.subTest(case=case):
                summary = self.collect(FakePowerShell({
                    "driver_packages": store([MOUSE, WEBCAM]),
                    "devices": response,
                }))
                self.assert_unreadable(summary, "devices")
                self.assertTrue(self.notes_about_source(summary, "devices"),
                                summary.get("not_checked"))
                self.assertIn("driver_packages", summary, sorted(summary))
                self.assertIsNone(summary["driver_packages"], summary["driver_packages"])

                detail = self.detail_packages(summary)
                self.assertEqual(set(detail), {package_key(MOUSE), package_key(WEBCAM)},
                                 detail)
                for item in detail.values():
                    self.assertIn("device_state", item, item)
                    self.assertIsNone(item["device_state"], item)
                    self.assertNotEqual(item.get("device_state"), "no_device_found", item)
                    reason = item.get("device_state_reason")
                    self.assertIsInstance(reason, str, item)
                    self.assertTrue(reason.strip(), item)

    def test_single_empty_and_unknown_status(self):
        """K6: a listing with one ``Device`` is ``read``, one with none is ``empty``,
        and a device of an unknown or missing status gives its package null with the
        reason, not ``no_device_found``."""
        with self.subTest(case="one Device element"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, TABLET]),
                "devices": devices_answer([STARTED_MOUSE]),
            }))
            self.assertEqual(self.source(summary, "devices").get("status"), "read",
                             self.source(summary, "devices"))
            mouse = self.detail_package(summary, MOUSE)
            self.assertEqual(mouse.get("device_state"), "present", mouse)
            tablet = self.detail_package(summary, TABLET)
            self.assertEqual(tablet.get("device_state"), "no_device_found", tablet)

        with self.subTest(case="no Device element"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, TABLET]),
                "devices": devices_answer([]),
            }))
            self.assertEqual(self.source(summary, "devices").get("status"), "empty",
                             self.source(summary, "devices"))
            self.assertEqual(self.notes_about_source(summary, "devices"), [],
                             summary.get("not_checked"))
            for pkg in (MOUSE, TABLET):
                item = self.detail_package(summary, pkg)
                self.assertEqual(item.get("device_state"), "no_device_found", item)
            listed = self.by_key(self.packages(summary))
            self.assertEqual(set(listed), {package_key(MOUSE), package_key(TABLET)},
                             listed)

        for status in (UNKNOWN_STATUS, None):
            with self.subTest(case=f"device status {status!r}"):
                odd_tablet = device("HID\\VID_0000&PID_0004\\0000", "oem40.inf", status,
                                    name="Invented Tablet", class_name="HIDClass")
                summary = self.collect(FakePowerShell({
                    "driver_packages": store([MOUSE, WEBCAM, TABLET]),
                    "devices": devices_answer([STARTED_MOUSE, odd_tablet]),
                }))
                self.assertEqual(self.source(summary, "devices").get("status"), "read",
                                 self.source(summary, "devices"))
                tablet = self.detail_package(summary, TABLET)
                self.assertIn("device_state", tablet, tablet)
                self.assertIsNone(tablet["device_state"], tablet)
                reason = tablet.get("device_state_reason")
                self.assertIsInstance(reason, str, tablet)
                self.assertIn("device status not known", reason, tablet)
                if status is not None:
                    self.assertIn(status, reason, tablet)
                listed = self.by_key(self.packages(summary))
                self.assertNotIn(package_key(TABLET), listed, listed)
                # The controls in the same run: the other packages keep their states.
                mouse = self.detail_package(summary, MOUSE)
                self.assertEqual(mouse.get("device_state"), "present", mouse)
                webcam = self.detail_package(summary, WEBCAM)
                self.assertEqual(webcam.get("device_state"), "no_device_found", webcam)

        with self.subTest(case="unknown status and a Started device"):
            odd_mouse = device("HID\\VID_0000&PID_0005\\0000", "oem3.inf", UNKNOWN_STATUS,
                               name="Invented Mouse Two")
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE]),
                "devices": devices_answer([odd_mouse, STARTED_MOUSE]),
            }))
            mouse = self.detail_package(summary, MOUSE)
            self.assertEqual(mouse.get("device_state"), "present", mouse)


class TestCounts(DeviceStatesTestCase):
    def test_counts_and_clean_store(self):
        """K9: ``driver_packages_by_state`` counts every package once by state, the
        summary list holds the ``non_present`` and ``no_device_found`` packages, and a
        clean store gives ``[]``."""
        with self.subTest(case="one package in each state"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, WEBCAM, TABLET, EXTENSION]),
                "devices": devices_answer(
                    [STARTED_MOUSE, DISCONNECTED_WEBCAM, WINDOWS_DEVICE],
                    last_removal={WEBCAM_DEVICE_ID: WEBCAM_REMOVED}),
            }))
            counts = self.component_counts(summary)
            self.assertNotIn("driver_packages_without_device", counts, counts)
            self.assertEqual(counts.get("driver_packages"), 4, counts)
            self.assertEqual(counts.get("driver_packages_by_state"),
                             {"present": 1, "non_present": 1, "no_device_found": 1,
                              "unread": 1}, counts)
            packages = self.packages(summary)
            self.assertEqual(len(packages), 2, packages)
            self.assertEqual(set(self.by_key(packages)),
                             {package_key(WEBCAM), package_key(TABLET)}, packages)

        with self.subTest(case="clean store: every package present"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE]),
                "devices": devices_answer([STARTED_MOUSE, WINDOWS_DEVICE]),
            }))
            self.assertEqual(self.source(summary, "devices").get("status"), "read",
                             self.source(summary, "devices"))
            self.assertEqual(self.packages(summary), [], summary.get("driver_packages"))
            counts = self.component_counts(summary)
            self.assertEqual(counts.get("driver_packages_by_state"),
                             {"present": 1, "non_present": 0, "no_device_found": 0,
                              "unread": 0}, counts)


if __name__ == "__main__":
    unittest.main()

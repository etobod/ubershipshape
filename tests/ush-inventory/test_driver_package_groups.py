"""Driver package groups from the data file of driver classes and providers of
skills/ush-inventory/scripts/inventory.py (plan 051, milestone M2, criteria K1 to K6).

The interface these tests assume is listed in ``fakes.py``, ``fakes_components.py`` and
``fakes_driver_packages.py``. Assumptions added here beyond the plan text:

- The data file path is the module constant ``inventory.DRIVER_PACKAGE_GROUPS_FILE`` (a
  ``Path`` to ``skills/ush-inventory/data/driver-package-groups.json``), patched with
  ``mock.patch.object`` like ``VENDOR_FOLDERS_FILE``. ``TestGroups`` runs with the
  shipped file; ``TestFile`` patches in invented broken files.
- ``driver_package_groups`` is a top-level summary key: a list of ``{group, count,
  by_state}`` with one entry per group; ``by_state`` maps a state name (``present``,
  ``non_present``, ``no_device_found``, ``unread``) to a number.
- The ``not_checked`` entry about a broken file names ``driver-package-groups`` in
  ``what`` or ``reason``.
- K5 tests the public file check ``inventory.load_driver_package_groups(path)``, which
  returns ``(rules, error)`` with ``error`` None when the file is valid.

PowerShell never starts; every data dir lives in a temporary directory; every value is
invented except the vendor name of the shipped provider rule the plan names.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .fakes import FakePowerShell
from .fakes_driver_packages import (
    EXTENSION_GUID,
    MOUSE_GUID,
    DriverPackagesTestCase,
    device,
    devices_answer,
    package,
    package_key,
    store,
)

ESET = "ESET, spol. s r.o."
SECURITY_VENDOR = "Invented Security Vendor Ltd"
OTHER_VENDOR = "Invented Keyboard Works Inc"

ANTIVIRUS_GUID = "{00000000-0000-0000-0000-00000000b001}"
DISPLAY_GUID = "{00000000-0000-0000-0000-00000000b002}"
SYSTEM_GUID = "{00000000-0000-0000-0000-00000000b003}"
KEYBOARD_GUID = "{00000000-0000-0000-0000-00000000b004}"
UNKNOWN_GUID = "{00000000-0000-0000-0000-00000000b005}"
CAMERA_GUID = "{00000000-0000-0000-0000-00000000b006}"

MOUSE = package("oem3.inf", "inventedmouse.inf", class_name="Mouse",
                class_guid=MOUSE_GUID, version="1.2.3.4", date="03/14/2024")
DISPLAY = package("oem7.inf", "inventeddisplay.inf", class_name="Display",
                  class_guid=DISPLAY_GUID, version="31.0.15.1", date="08/21/2025")
SYSTEM = package("oem9.inf", "inventedchipset.inf", class_name="System",
                 class_guid=SYSTEM_GUID, version="10.1.2.3", date="02/02/2024")
ANTIVIRUS = package("oem21.inf", "inventedavfilter.inf", provider=SECURITY_VENDOR,
                    class_name="AntiVirus", class_guid=ANTIVIRUS_GUID,
                    version="5.0.0.1", date="09/09/2025")
WEBCAM = package("oem12.inf", "inventedwebcam.inf", class_name="Camera",
                 class_guid=CAMERA_GUID, version="2.0.1.0", date="11/02/2025")
TABLET = package("oem40.inf", "inventedtablet.inf", class_name="HIDClass",
                 version="1.0.0.7", date="06/30/2023")

ESET_KEYBOARD = package("oem30.inf", "inventedesetkbd.inf", provider=ESET,
                        class_name="Keyboard", class_guid=KEYBOARD_GUID,
                        version="1.0.0.2", date="04/04/2025", signer=ESET)
ESET_UNKNOWN = package("oem31.inf", "inventedesetaux.inf", provider=ESET,
                       class_name="Unknown", class_guid=UNKNOWN_GUID,
                       version="1.0.0.3", date="04/04/2025", signer=ESET)
OTHER_KEYBOARD = package("oem32.inf", "inventedkeyboard.inf", provider=OTHER_VENDOR,
                         class_name="Keyboard", class_guid=KEYBOARD_GUID,
                         version="4.2.0.0", date="07/07/2024")
OTHER_UNKNOWN = package("oem33.inf", "inventedgadget.inf", provider=OTHER_VENDOR,
                        class_name="Unknown", class_guid=UNKNOWN_GUID,
                        version="0.9.1.0", date="07/07/2024")

STARTED_MOUSE = device("USB\\VID_0000&PID_0001\\0000", "oem3.inf", "Started",
                       name="Invented Mouse")
STARTED_DISPLAY = device("PCI\\VEN_0000&DEV_0002\\0000", "oem7.inf", "Started",
                         name="Invented Graphics Adapter", class_name="Display",
                         class_guid=DISPLAY_GUID)
STARTED_SYSTEM = device("ACPI\\INVENTED0003\\0000", "oem9.inf", "Started",
                        name="Invented Chipset Device", class_name="System",
                        class_guid=SYSTEM_GUID)
STARTED_KEYBOARD = device("HID\\VID_0000&PID_0004\\0000", "oem32.inf", "Started",
                          name="Invented Keyboard", class_name="Keyboard",
                          class_guid=KEYBOARD_GUID, manufacturer=OTHER_VENDOR)
STARTED_GADGET = device("ROOT\\INVENTED0005\\0000", "oem33.inf", "Started",
                        name="Invented Gadget", class_name="Unknown",
                        class_guid=UNKNOWN_GUID, manufacturer=OTHER_VENDOR)
DISCONNECTED_WEBCAM = device("USB\\VID_0000&PID_0006\\0000", "oem12.inf", "Disconnected",
                             name="Invented Webcam", class_name="Camera",
                             class_guid=CAMERA_GUID)

GROUPS_FILE_NAME = "driver-package-groups.json"

# The class rules the plan ships: class -> (group, no_device_by_nature).
FILTER_CLASSES = (
    "ActivityMonitor", "Bottom", "Compression", "ContentScreener", "ContinuousBackup",
    "CopyProtection", "Encryption", "FSFilterSystem", "HSM", "Infrastructure",
    "OpenFileBackup", "PhysicalQuotaManagement", "QuotaManagement", "Replication",
    "SecurityEnhancer", "Top", "Undelete", "Virtualization",
)
PERIPHERAL_CLASSES = ("Camera", "Image", "Mouse", "Keyboard", "HIDClass", "Bluetooth",
                      "Net", "MEDIA", "Monitor", "USB")
SYSTEM_CLASSES = ("System", "SCSIAdapter", "HDC", "Firmware", "SoftwareComponent",
                  "Extension")
SHIPPED_CLASS_RULES = {
    "AntiVirus": ("antivirus", True),
    "Display": ("graphics", False),
    **{name: ("filter", True) for name in FILTER_CLASSES},
    **{name: ("peripherals", False) for name in PERIPHERAL_CLASSES},
    **{name: ("system", False) for name in SYSTEM_CLASSES},
}
UNLISTED_CLASS = "InventedUnlistedClass"


def rule(group, by_nature=False, class_name=None, provider=None):
    """One rule of an invented groups file (only the keys given are written)."""
    item = {"group": group, "no_device_by_nature": by_nature}
    if class_name is not None:
        item["class"] = class_name
    if provider is not None:
        item["provider"] = provider
    return item


BROKEN_FILES = {
    "missing": None,
    "not a list": {"rules": [rule("peripherals", class_name="Mouse")]},
    "rule without group": [
        rule("peripherals", class_name="Mouse"),
        {"class": "Display", "no_device_by_nature": False},
    ],
    "rule with both class and provider": [
        rule("peripherals", class_name="Mouse"),
        rule("antivirus", True, class_name="AntiVirus", provider=SECURITY_VENDOR),
    ],
    "a class in two rules": [
        rule("peripherals", class_name="Mouse"),
        rule("system", class_name="Mouse"),
    ],
}


class GroupsTestCase(DriverPackagesTestCase):
    def detail_package(self, summary, pkg):
        detail = self.detail_packages(summary)
        self.assertIn(package_key(pkg), detail, detail)
        return detail[package_key(pkg)]

    def listed_package(self, summary, pkg):
        listed = self.by_key(self.packages(summary))
        self.assertIn(package_key(pkg), listed, listed)
        return listed[package_key(pkg)]

    def groups(self, summary):
        """The summary's ``driver_package_groups`` by group name."""
        self.assertIn("driver_package_groups", summary, sorted(summary))
        groups = summary["driver_package_groups"]
        self.assertIsInstance(groups, list, groups)
        result = {}
        for entry in groups:
            self.assertNotIn(entry.get("group"), result, f"duplicate group in {groups}")
            result[entry.get("group")] = entry
        return result

    def assert_grouped(self, item, group, by_nature, owner):
        self.assertEqual(item.get("group"), group, item)
        self.assertIn("no_device_by_nature", item, item)
        self.assertIs(item["no_device_by_nature"], by_nature, item)
        self.assertEqual(item.get("owner"), owner, item)


class TestGroups(GroupsTestCase):
    def test_antivirus_owned(self):
        """K1: an ``AntiVirus`` package with state ``no_device_found`` is group
        ``antivirus``, ``no_device_by_nature`` true and owned by its provider."""
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, ANTIVIRUS]),
            "devices": devices_answer([STARTED_MOUSE]),
        }))
        detail = self.detail_package(summary, ANTIVIRUS)
        self.assertEqual(detail.get("device_state"), "no_device_found", detail)
        self.assert_grouped(detail, "antivirus", True, SECURITY_VENDOR)

        listed = self.listed_package(summary, ANTIVIRUS)
        self.assertEqual(listed.get("device_state"), "no_device_found", listed)
        self.assert_grouped(listed, "antivirus", True, SECURITY_VENDOR)

        # The control in the same run: a present Mouse package is no filter.
        mouse = self.detail_package(summary, MOUSE)
        self.assert_grouped(mouse, "peripherals", False, MOUSE["provider"])

    def test_clean_data_no_by_nature(self):
        """K3: a present ``Display``, ``Mouse`` and ``System`` package: none is
        ``no_device_by_nature``, and the groups count them under ``graphics``,
        ``peripherals`` and ``system``."""
        summary = self.collect(FakePowerShell({
            "driver_packages": store([DISPLAY, MOUSE, SYSTEM]),
            "devices": devices_answer([STARTED_DISPLAY, STARTED_MOUSE, STARTED_SYSTEM]),
        }))
        expected = {DISPLAY["published"]: "graphics", MOUSE["published"]: "peripherals",
                    SYSTEM["published"]: "system"}
        for pkg in (DISPLAY, MOUSE, SYSTEM):
            item = self.detail_package(summary, pkg)
            self.assertEqual(item.get("device_state"), "present", item)
            self.assert_grouped(item, expected[pkg["published"]], False, pkg["provider"])
        self.assertEqual(self.packages(summary), [], summary.get("driver_packages"))

        groups = self.groups(summary)
        counted = {name: entry.get("count") for name, entry in groups.items()
                   if entry.get("count")}
        self.assertEqual(counted, {"graphics": 1, "peripherals": 1, "system": 1}, groups)
        for name in ("graphics", "peripherals", "system"):
            by_state = groups[name].get("by_state")
            self.assertIsInstance(by_state, dict, groups[name])
            self.assertEqual(by_state.get("present"), 1, groups[name])
            self.assertEqual(sum(by_state.values()), 1, groups[name])

    def test_provider_rule_wins_and_clean_data(self):
        """K6: ESET packages in ``Keyboard`` and ``Unknown`` follow the provider rule;
        another provider's packages in those classes follow the class rule or ``other``."""
        with self.subTest(case="ESET packages with no device found"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, ESET_KEYBOARD, ESET_UNKNOWN]),
                "devices": devices_answer([STARTED_MOUSE]),
            }))
            for pkg in (ESET_KEYBOARD, ESET_UNKNOWN):
                item = self.detail_package(summary, pkg)
                self.assertEqual(item.get("device_state"), "no_device_found", item)
                self.assert_grouped(item, "antivirus", True, ESET)
                listed = self.listed_package(summary, pkg)
                self.assert_grouped(listed, "antivirus", True, ESET)

        with self.subTest(case="clean data: another provider in the same classes"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([OTHER_KEYBOARD, OTHER_UNKNOWN]),
                "devices": devices_answer([STARTED_KEYBOARD, STARTED_GADGET]),
            }))
            keyboard = self.detail_package(summary, OTHER_KEYBOARD)
            self.assertEqual(keyboard.get("device_state"), "present", keyboard)
            self.assert_grouped(keyboard, "peripherals", False, OTHER_VENDOR)
            gadget = self.detail_package(summary, OTHER_UNKNOWN)
            self.assertEqual(gadget.get("device_state"), "present", gadget)
            self.assert_grouped(gadget, "other", False, OTHER_VENDOR)

    def test_shipped_rules_and_other(self):
        """K2: every shipped class rule matches its class case-insensitively (the class
        written lower-, upper- and mixed-cased) and gives the plan's group and
        ``no_device_by_nature``; a class in no rule gives ``other``."""
        expected = dict(SHIPPED_CLASS_RULES)
        expected[UNLISTED_CLASS] = ("other", False)
        spellings = (str.lower, str.upper, str.swapcase)
        packages = {}
        for number, class_name in enumerate(sorted(expected)):
            written = spellings[number % len(spellings)](class_name)
            packages[class_name] = package(
                f"oem{100 + number}.inf", f"inventedclass{number}.inf",
                class_name=written, version=f"1.0.{number}.0")
        summary = self.collect(FakePowerShell({
            "driver_packages": store(list(packages.values())),
            "devices": devices_answer([]),
        }))
        detail = self.detail_packages(summary)
        for class_name, (group, by_nature) in sorted(expected.items()):
            with self.subTest(class_name=class_name):
                pkg = packages[class_name]
                self.assertIn(package_key(pkg), detail, sorted(detail))
                self.assert_grouped(detail[package_key(pkg)], group, by_nature,
                                    pkg["provider"])


class TestFile(GroupsTestCase):
    def run_with_file(self, content):
        """Collect with ``content`` as the groups file (None: the file does not exist)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name).resolve() / GROUPS_FILE_NAME
        if content is not None:
            path.write_text(json.dumps(content), encoding="utf-8")
        with mock.patch.object(self.inventory, "DRIVER_PACKAGE_GROUPS_FILE", path):
            return self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, WEBCAM, TABLET]),
                "devices": devices_answer([STARTED_MOUSE, DISCONNECTED_WEBCAM]),
            }))

    def group_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if "driver-package-groups" in f"{item.get('what')} {item.get('reason')}"]

    def test_broken_file(self):
        """K4: a missing or broken groups file gives every package ``group`` null,
        ``driver_package_groups`` null, one ``not_checked`` entry and the M1 states."""
        states = {package_key(MOUSE): "present", package_key(WEBCAM): "non_present",
                  package_key(TABLET): "no_device_found"}

        with self.subTest(case="clean control: the shipped file"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, WEBCAM, TABLET]),
                "devices": devices_answer([STARTED_MOUSE, DISCONNECTED_WEBCAM]),
            }))
            self.assertEqual(self.group_notes(summary), [], summary.get("not_checked"))
            self.assertIsInstance(summary.get("driver_package_groups"), list,
                                  summary.get("driver_package_groups"))
            for pkg in (MOUSE, WEBCAM, TABLET):
                item = self.detail_package(summary, pkg)
                self.assertIsNotNone(item.get("group"), item)

        for case, content in BROKEN_FILES.items():
            with self.subTest(case=case):
                summary = self.run_with_file(content)

                self.assertIn("driver_package_groups", summary, sorted(summary))
                self.assertIsNone(summary["driver_package_groups"],
                                  summary["driver_package_groups"])

                notes = self.group_notes(summary)
                self.assertEqual(len(notes), 1, summary.get("not_checked"))
                reason = notes[0].get("reason")
                self.assertIsInstance(reason, str, notes)
                self.assertTrue(reason.strip(), notes)

                detail = self.detail_packages(summary)
                self.assertEqual(set(detail), set(states), detail)
                for key, item in detail.items():
                    self.assertIn("group", item, item)
                    self.assertIsNone(item["group"], item)
                    self.assertEqual(item.get("device_state"), states[key], item)

                listed = self.by_key(self.packages(summary))
                self.assertEqual(set(listed),
                                 {package_key(WEBCAM), package_key(TABLET)}, listed)
                for key, item in listed.items():
                    self.assertIn("group", item, item)
                    self.assertIsNone(item["group"], item)
                    self.assertEqual(item.get("device_state"), states[key], item)

    def test_shipped_file_valid(self):
        """K5: the shipped groups file passes the file check of
        ``inventory.load_driver_package_groups(path)`` (assumed to return ``(rules,
        error)`` with ``error`` None for a valid file) and no class or provider is in two
        of its rules (compared case-insensitively)."""
        path = self.inventory.DRIVER_PACKAGE_GROUPS_FILE
        rules, error = self.inventory.load_driver_package_groups(path)
        self.assertIsNone(error, error)
        self.assertIsInstance(rules, list, rules)
        self.assertTrue(rules, rules)

        self.assertTrue(Path(path).is_file(), path)
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertIsInstance(raw, list, raw)
        seen = {"class": set(), "provider": set()}
        for item in raw:
            self.assertIsInstance(item, dict, item)
            keys = [key for key in ("class", "provider") if key in item]
            self.assertEqual(len(keys), 1, item)
            value = item[keys[0]]
            self.assertIsInstance(value, str, item)
            folded = value.strip().casefold()
            self.assertNotIn(folded, seen[keys[0]], f"{keys[0]} {value!r} in two rules")
            seen[keys[0]].add(folded)



class TestSummaryOrder(GroupsTestCase):
    """Deviation of M3 (the run on this machine): the summary list is cut from its end,
    so the packages the report must name come first."""

    def test_named_packages_first(self):
        """A ``non_present`` package first, then a ``no_device_by_nature`` one, then the
        other ``no_device_found`` ones, each part in provider/name/version order."""
        disconnected = device(r"USB\VID_0000&PID_0009\0000", "oem3.inf", "Disconnected",
                              name="Invented Mouse")
        summary = self.collect(FakePowerShell({
            "driver_packages": store([DISPLAY, MOUSE, ANTIVIRUS]),
            "devices": devices_answer([disconnected]),
        }))
        keys = [item.get("key") for item in self.packages(summary)]
        self.assertEqual(keys, [package_key(MOUSE), package_key(ANTIVIRUS),
                                package_key(DISPLAY)], self.packages(summary))

    def test_clean_order_unchanged(self):
        """Clean data: only ``no_device_found`` packages without a by-nature group keep
        the provider/name/version order."""
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, DISPLAY]),
            "devices": devices_answer([]),
        }))
        keys = [item.get("key") for item in self.packages(summary)]
        self.assertEqual(keys, [package_key(DISPLAY), package_key(MOUSE)])


class TestExtensionNotChecked(GroupsTestCase):
    def test_extension_named_in_not_checked(self):
        """An ``Extension`` package has state null and one not_checked entry names it."""
        extension = package("oem40.inf", "inventedext.inf", class_name="Extension",
                            class_guid=EXTENSION_GUID)
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, extension]),
            "devices": devices_answer([STARTED_MOUSE]),
        }))
        self.assertIsNone(self.detail_package(summary, extension).get("device_state"))
        notes = [entry for entry in summary.get("not_checked") or []
                 if "driver_packages" in str(entry.get("what"))
                 and "xtension" in json.dumps(entry)]
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn("1 package", notes[0].get("reason", ""), notes[0])

    def test_no_extension_no_entry(self):
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE]),
            "devices": devices_answer([STARTED_MOUSE]),
        }))
        notes = [entry for entry in summary.get("not_checked") or []
                 if "xtension" in json.dumps(entry)]
        self.assertEqual(notes, [], summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

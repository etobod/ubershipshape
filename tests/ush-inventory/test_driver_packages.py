"""Driver packages without a present device: the ``driver_packages`` source of
skills/ush-inventory/scripts/inventory.py (plan 024, milestone M2, criteria K1-K5, K7, K8).

Since plan 051 M1 the state of a package comes from the ``devices`` source
(``device_state``), no longer from the ``drivers`` rows (``present_device``); these
tests were moved to that contract.

The interface these tests assume is listed in ``fakes.py``, ``fakes_components.py`` and
``fakes_driver_packages.py``. PowerShell never starts; every data dir lives in a
temporary directory; every value is invented.
"""

import io
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta

from .fakes import NOW, FakePowerShell, failure
from .fakes_components import WINDOWS_PROVIDER, WINDOWS_SIGNER
from .fakes_driver_packages import (
    BROKEN_XML,
    EXTENSION_GUID,
    MONITOR_GUID,
    USAGE_TEXT,
    DriverPackagesTestCase,
    device,
    devices_answer,
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

# A present device whose driver is no package of these tests.
OTHER_DEVICES = devices_answer([device("PCI\\VEN_0000&DEV_0050\\0050", "oem99.inf",
                                       "Started")])
# A present device of PAD.
PAD_DEVICES = devices_answer([device("HID\\VID_0000&PID_0001\\0001", "oem12.inf",
                                     "Started", name="Invented Touch Pad",
                                     class_name="HIDClass")])


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
            # The device names the INF in another case than the store.
            "devices": devices_answer([device("HID\\VID_0000&PID_0001\\0001", "OEM12.INF",
                                              "Started", name="Invented Touch Pad",
                                              class_name="HIDClass")]),
        })
        summary = self.collect(fake)
        self.assertIn("driver_packages", fake.jobs())
        self.assertEqual(self.source(summary, "driver_packages").get("status"), "read",
                         self.source(summary, "driver_packages"))

        listed = self.by_key(self.packages(summary))
        self.assertEqual(set(listed), {package_key(MOUSE), package_key(MONITOR)}, listed)
        for pkg in (MOUSE, MONITOR):
            self.assert_package(listed[package_key(pkg)], pkg, "no_device_found")
        ids = [item.get("id") for item in listed.values()]
        self.assertEqual(len(set(ids)), 2, ids)

        counts = self.component_counts(summary)
        self.assertEqual(counts.get("driver_packages"), 3, counts)
        self.assertEqual(counts.get("driver_packages_by_state"),
                         {"present": 1, "non_present": 0, "no_device_found": 2,
                          "unread": 0}, counts)

    def test_clean_store_lists_nothing(self):
        with self.subTest(case="every third-party package has a present device"):
            audio = package("oem5.inf", "inventedaudio.inf", class_name="MEDIA",
                            version="6.0.1.2", date="01/20/2026")
            net = package("oem6.inf", "inventednet.inf", class_name="Net",
                          version="12.7.3.1", date="02/11/2026")
            summary = self.collect(FakePowerShell({
                "driver_packages": store([audio, net]),
                "devices": devices_answer([
                    device("HDAUDIO\\FUNC_01&VEN_0000\\0001", "oem5.inf", "Started",
                           name="Invented Audio", class_name="MEDIA"),
                    device("PCI\\VEN_0000&DEV_0002\\0002", "Oem6.inf", "Stopped",
                           name="Invented Network Adapter", class_name="Net"),
                    device("ACPI\\INVENTED0003\\0003", "machine.inf", "Started",
                           name="Invented Windows Device", class_name="System"),
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
                "devices": devices_answer([device("ACPI\\INVENTED0004\\0004",
                                                  "inventedinbox.inf", "Started")]),
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
                    "devices": OTHER_DEVICES,
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
        self.collect(FakePowerShell({"driver_packages": store([MOUSE, PAD]),
                                     "devices": OTHER_DEVICES}),
                     data_dir=data_dir, now=NOW)
        text = store_xml([MOUSE, PAD])
        nameless = text.replace(' DriverName="oem3.inf"', "", 1)
        self.assertNotEqual(nameless, text)
        summary = self.collect(FakePowerShell({
            "driver_packages": store_text(nameless, exit_code=0),
            "devices": OTHER_DEVICES,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        source = [s for s in summary["sources"] if s["name"] == "driver_packages"]
        self.assertEqual([s["status"] for s in source], ["read"], source)
        detail = self.detail_packages(summary)
        self.assertEqual(set(detail), {package_key(MOUSE), package_key(PAD)}, detail)
        mouse = detail[package_key(MOUSE)]
        self.assertIsNone(mouse.get("published_name"), mouse)
        self.assertIn("published_name", mouse.get("unread_fields") or [], mouse)
        self.assertIn("device_state", mouse, mouse)
        self.assertIsNone(mouse["device_state"], mouse)
        self.assertEqual(set(self.by_key(self.packages(summary))), {package_key(PAD)})
        changes = self.by_key(self.changes_from(summary, "driver_packages"))
        self.assertNotIn(package_key(MOUSE), changes, changes)

    def test_drivers_unread_no_orphans(self):
        """The devices not read: no package is judged (the ``drivers`` source no longer
        decides it)."""
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, PAD]),
            "devices": failure("Invented PnP failure"),
        }))
        self.assert_unreadable(summary, "devices")
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

        with self.subTest(case="the drivers source unreadable does not matter"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store([MOUSE, PAD]),
                "drivers": failure("Invented CIM failure"),
                "devices": PAD_DEVICES,
            }))
            self.assert_unreadable(summary, "drivers")
            detail = self.detail_packages(summary)
            self.assert_package(detail[package_key(MOUSE)], MOUSE, "no_device_found")
            self.assert_package(detail[package_key(PAD)], PAD, "present")

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
        devices = devices_answer([device("HID\\VID_0000&PID_0021\\0021", "oem21.inf",
                                         "Started", name="Invented Touch Pad",
                                         class_name="HIDClass")])

        run1 = self.collect(FakePowerShell({
            "driver_packages": store([mouse_first, pad_old, pad_new, cam_old]),
            "devices": devices,
        }), data_dir=data_dir, now=NOW)

        # Two versions of one package: both kept, only the unused one listed.
        detail1 = self.detail_packages(run1)
        self.assert_package(detail1.get(package_key(pad_old)), pad_old, "no_device_found")
        self.assert_package(detail1.get(package_key(pad_new)), pad_new, "present")
        listed1 = self.by_key(self.packages(run1))
        self.assertEqual(set(listed1),
                         {package_key(mouse_first), package_key(pad_old),
                          package_key(cam_old)}, listed1)

        run2 = self.collect(FakePowerShell({
            "driver_packages": store([mouse_again, pad_old, pad_new, cam_new]),
            "devices": devices,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("driver_packages"), "compared",
                         self.comparison(run2))
        # Installed again under a new oem number: same key, same id.
        detail2 = self.detail_packages(run2)
        mouse_key = package_key(mouse_first)
        self.assertEqual(package_key(mouse_again), mouse_key)
        self.assert_package(detail2.get(mouse_key), mouse_again, "no_device_found")
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
        """An ``Extension`` package is not judged; a package whose device is
        ``Stopped`` is present (plan 051 replaced the rows without ``DeviceID``)."""
        extension = package("oem60.inf", "inventedmonitorext.inf",
                            provider="Invented Display Ltd", class_name="Extension",
                            class_guid=EXTENSION_GUID, version="1.0.2.0",
                            date="04/04/2025", signer="Invented Display Signer")
        stopped = package("oem61.inf", "inventedhelper.inf", class_name="System",
                          version="4.4.0.1", date="07/07/2025")
        monitor = package("oem62.inf", "inventedmonitor.inf",
                          provider="Invented Display Ltd", class_name="Monitor",
                          class_guid=MONITOR_GUID, version="1.0.0.9", date="04/04/2025",
                          signer="Invented Display Signer")
        summary = self.collect(FakePowerShell({
            "driver_packages": store([extension, stopped, monitor]),
            "devices": devices_answer([
                device("DISPLAY\\INV0001\\0001", "oem62.inf", "Started",
                       name="Invented Monitor", class_name="Monitor"),
                device("ROOT\\INVENTED\\0000", "OEM61.inf", "Stopped",
                       name="Invented Helper", class_name="System"),
            ]),
        }))

        self.assertEqual(self.packages(summary), [])
        detail = self.detail_packages(summary)
        self.assert_package(detail.get(package_key(extension)), extension, None)
        self.assert_package(detail.get(package_key(stopped)), stopped, "present")
        self.assert_package(detail.get(package_key(monitor)), monitor, "present")

    def test_detail_section_and_block(self):
        data_dir = self.data_dir()
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, PAD]),
            "devices": PAD_DEVICES,
        }), data_dir=data_dir)

        detail = self.detail_packages(summary)
        self.assertEqual(set(detail), {package_key(MOUSE), package_key(PAD)}, detail)
        self.assert_package(detail[package_key(MOUSE)], MOUSE, "no_device_found")
        self.assert_package(detail[package_key(PAD)], PAD, "present")
        self.assertIn("o1", {item.get("id") for item in detail.values()}, detail)

        # Plan 051 M1: no package gets a removal block, whatever its state.
        _code, stdout, stderr = self.block(data_dir, "o1", summary.get("detail_file"))
        self.assertRegex(stdout, r"(?m)^\s*#\s*o1\s*:\s*no block\s*:", stdout or stderr)
        self.assertNotIn("/delete-driver", stdout, stdout)


class TestDriverPackagesBaseline(DriverPackagesTestCase):
    """TEST-PLAN (b) for a new source in a diff skill (added by loc-qa, plan 024)."""

    def test_single_package_store(self):
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE]),
            "devices": OTHER_DEVICES,
        }))
        self.assertEqual(self.source(summary, "driver_packages").get("status"), "read")
        listed = self.by_key(self.packages(summary))
        self.assertEqual(set(listed), {package_key(MOUSE)}, listed)
        self.assert_package(listed[package_key(MOUSE)], MOUSE, "no_device_found")

    def test_first_run_unreadable_run_and_carry_over(self):
        data_dir = self.data_dir()

        run1 = self.collect(FakePowerShell({"driver_packages": store([MOUSE, PAD]),
                                            "devices": PAD_DEVICES}),
                            data_dir=data_dir, now=NOW)
        with self.subTest(point="first run: no comparison, no changes"):
            self.assertEqual(self.comparison(run1).get("driver_packages"), "no_baseline",
                             self.comparison(run1))
            self.assertEqual(self.changes_from(run1, "driver_packages"), [])
        first_ids = {key: item.get("id")
                     for key, item in self.detail_packages(run1).items()}

        run2 = self.collect(FakePowerShell({
            "driver_packages": failure("Invented job failure 0x80070005"),
            "devices": PAD_DEVICES,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))
        with self.subTest(point="unreadable source: not compared, no changes"):
            self.assert_unreadable(run2, "driver_packages")
            self.assertNotEqual(self.comparison(run2).get("driver_packages"), "compared",
                                self.comparison(run2))
            self.assertEqual(self.changes_from(run2, "driver_packages"), [])

        run3 = self.collect(FakePowerShell({"driver_packages": store([MOUSE, PAD]),
                                            "devices": PAD_DEVICES}),
                            data_dir=data_dir, now=NOW + timedelta(days=2))
        with self.subTest(point="items carried over the unreadable run"):
            self.assertEqual(self.comparison(run3).get("driver_packages"), "compared",
                             self.comparison(run3))
            self.assertEqual(self.changes_from(run3, "driver_packages"), [])
            third_ids = {key: item.get("id")
                         for key, item in self.detail_packages(run3).items()}
            self.assertEqual(third_ids, first_ids)


def store_without_published_names(packages, unread):
    """The ``driver_packages`` job answer for ``packages`` where the ``DriverName``
    attribute (the published name) is missing on the first copy of each name in
    ``unread``."""
    text = store_xml(packages)
    for name in unread:
        attribute = f' DriverName="{name}"'
        stripped = text.replace(attribute, "", 1)
        if stripped == text:
            raise AssertionError(f"no {attribute!r} in the invented store")
        text = stripped
    return store_text(text, exit_code=0)


class TestPublishedNameUnread(DriverPackagesTestCase):
    """Plan 035, milestone M2 (criteria K5-K7): third-party packages whose published
    name was not read, so they cannot be matched to a device, are named once in
    ``not_checked`` with their count and ``PUBLISHED_UNREAD_REASON``."""

    def unread_notes(self, summary):
        """``not_checked`` entries naming ``PUBLISHED_UNREAD_REASON`` in ``what`` or
        ``reason``."""
        reason = self.inventory.PUBLISHED_UNREAD_REASON
        return [item for item in self.not_checked(summary)
                if reason in f"{item.get('what')} {item.get('reason')}"]

    def test_unread_names_give_one_not_checked_entry(self):
        packages = [MOUSE, PAD, MONITOR]
        devices = devices_answer([device("DISPLAY\\INV0040\\0040", "oem40.inf", "Started",
                                         name="Invented Monitor", class_name="Monitor")])
        clean = self.collect(FakePowerShell({"driver_packages": store(packages),
                                             "devices": devices}))
        summary = self.collect(FakePowerShell({
            "driver_packages": store_without_published_names(
                packages, [MOUSE["published"], PAD["published"]]),
            "devices": devices,
        }))

        notes = self.unread_notes(summary)
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        note = notes[0]
        text = f"{note.get('what')} {note.get('reason')}"
        if "count" in note:
            self.assertEqual(note["count"], 2, note)
        else:
            self.assertRegex(text, r"(?<![\w.])2(?![\w.])", note)
        self.assertNotRegex(text, r"(?<![\w.])3(?![\w.])", note)

        others = [item for item in self.not_checked(summary) if item is not note]
        self.assertEqual(others, self.not_checked(clean),
                         (summary.get("not_checked"), clean.get("not_checked")))

    def test_clean_store_gives_no_entry(self):
        summary = self.collect(FakePowerShell({
            "driver_packages": store([MOUSE, PAD, MONITOR]),
            "devices": PAD_DEVICES,
        }))
        self.assertEqual(self.source(summary, "driver_packages").get("status"), "read")
        self.assertEqual(self.unread_notes(summary), [], summary.get("not_checked"))

    def test_matched_or_unjudged_gives_no_entry(self):
        other_copy = dict(MOUSE, published="oem13.inf")
        self.assertEqual(package_key(other_copy), package_key(MOUSE))
        devices = devices_answer([device("HID\\VID_0000&PID_0013\\0013", "oem13.inf",
                                         "Started", name="Invented Mouse")])
        orders = {"unread copy first": [MOUSE, other_copy, PAD],
                  "unread copy last": [other_copy, MOUSE, PAD]}
        for case, packages in orders.items():
            with self.subTest(case=f"matched through another published name, {case}"):
                summary = self.collect(FakePowerShell({
                    "driver_packages": store_without_published_names(
                        packages, [MOUSE["published"]]),
                    "devices": devices,
                }))
                detail = self.detail_packages(summary)
                self.assertEqual(detail.get(package_key(MOUSE), {}).get("device_state"),
                                 "present", detail)
                self.assertEqual(self.unread_notes(summary), [],
                                 summary.get("not_checked"))

        with self.subTest(case="devices not read"):
            summary = self.collect(FakePowerShell({
                "driver_packages": store_without_published_names(
                    [MOUSE, PAD], [MOUSE["published"], PAD["published"]]),
                "devices": failure("Invented PnP failure"),
            }))
            self.assert_unreadable(summary, "devices")
            self.assertEqual(self.unread_notes(summary), [], summary.get("not_checked"))
            notes = self.package_notes(summary)
            self.assertTrue(
                any(re.search(r"(?i)device|\bdrivers\b",
                              f"{note.get('what')} {note.get('reason')}") for note in notes),
                summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

"""The ``--block o<n>`` printer for a driver package (plan 027, milestone M1; plan 051,
milestone M1).

Interface under test (the general one is in ``test_block.py``):

- ``main(["--data-dir", <dir>, "--block", "o1", "--detail-file", <file>])`` prints no
  removal for any ``driver_packages`` item of the detail file (plan 051): whatever its
  ``device_state``, sources or names, it prints ``# o<n>: no block: <reason>`` with the
  reason ``PACKAGE_NO_BLOCK_REASON`` and no ``pnputil`` line, and starts no job.

Assumptions added by these tests beyond the plan text:

- A detail item of ``driver_packages`` has the fields of references/summary-contract.md
  "Driver packages" plus ``source`` (``driver_packages``) and ``own`` (``false``) like the
  other detail items; ``listed["driver_packages"]`` holds the listable ids.

Every value here is invented; nothing comes from a machine. PowerShell never starts and
no block is run.
"""

import json
import os
import re
import unittest
from unittest import mock

from .fakes import FakePowerShell
from .test_block import (
    STAMP,
    AdditionBlockTestCase,
    commands,
    detail_document,
    source,
)

PROVIDER = "Invented Peripherals Corp"
SIGNER = "Invented Driver Signer"
ORIGINAL = "inventedmouse.inf"
PUBLISHED = "oem7.inf"

# The temporary data dir lies under the real LOCALAPPDATA on Windows; invented profile
# variables keep the printed path a literal path under <data dir>\work.
INVENTED_ENV = {"LOCALAPPDATA": r"Q:\InventedProfile\AppData\Local",
                "USERPROFILE": r"Q:\InventedProfile"}


def package_item(item_id, published, original, present_device, version="1.2.3.4",
                 class_name="Mouse", **extra):
    """One ``driver_packages`` detail item in the shape of the summary contract."""
    item = {
        "id": item_id,
        "key": f"driver_package:{original}|{PROVIDER}|{version}".casefold(),
        "source": "driver_packages",
        "published_name": published,
        "original_name": original,
        "provider": PROVIDER,
        "class": class_name,
        "version": version,
        "date": "2024-03-14",
        "signer": SIGNER,
        "present_device": present_device,
        "own": False,
    }
    item.update(extra)
    return item


ORPHAN = package_item("o1", PUBLISHED, ORIGINAL, False)


class DriverPackageBlockTestCase(AdditionBlockTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, INVENTED_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare_packages(self, packages, drivers_status="read", packages_status="read"):
        """A data dir whose ``work/`` holds one detail file with ``packages``."""
        data_dir = self.data_dir()
        work = data_dir / "work"
        work.mkdir(parents=True)
        summary_file = work / f"inventory-{STAMP}.summary.json"
        summary_file.write_text(json.dumps({"skill": "ush-inventory", "not_checked": []}),
                                encoding="utf-8")
        document = detail_document(summary_file)
        drivers = source("drivers", status=drivers_status)
        if drivers_status != "read":
            drivers["reason"] = "invented failure of the drivers job"
        store = source("driver_packages", status=packages_status)
        if packages_status != "read":
            store["reason"] = "invented failure of the driver store job"
        document["sources"] = document["sources"] + [drivers, store]
        document["drivers"] = []
        document["driver_packages"] = [dict(item) for item in packages]
        document["listed"]["drivers"] = []
        document["listed"]["driver_packages"] = [item["id"] for item in packages]
        detail_file = work / f"inventory-{STAMP}.detail.json"
        detail_file.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return data_dir, detail_file

    def assert_refused(self, stdout, item_id, reason=None):
        """No command and no pnputil line; the ``# <id>: no block: <reason>`` line."""
        self.assertTrue(stdout.strip(), "nothing printed")
        self.assertEqual(commands(stdout), [], stdout)
        self.assertFalse([line for line in stdout.splitlines()
                          if "pnputil" in line.lower()], stdout)
        line = self.assert_no_block_line(stdout, item_id)
        if reason is not None:
            self.assertRegex(line, reason, line)
        return line


class TestDriverPackageBlock(DriverPackageBlockTestCase):
    def test_refused_packages(self):
        """Plan 051 M1: every package gets the one ``no block`` reason, whatever its
        state, sources or copies (plan 027 K2 gave a block to ``present_device`` false;
        that block is gone)."""
        reason = re.escape(self.inventory.PACKAGE_NO_BLOCK_REASON)
        present = package_item("o2", "oem8.inf", "inventedcamera.inf", True)
        extension = package_item(
            "o3", "oem9.inf", "inventedextension.inf", None, class_name="Extension",
            present_device_reason="extension package: not listed per device")
        baseline = package_item("o4", "oem10.inf", "inventedkeyboard.inf", False,
                                from_baseline=True)
        data_dir, detail_file = self.prepare_packages([ORPHAN, present, extension, baseline])
        for case, item_id in (("former orphan", "o1"), ("present_device true", "o2"),
                              ("present_device null", "o3"), ("from_baseline", "o4")):
            with self.subTest(case=case):
                fake = FakePowerShell()
                _code, stdout, _stderr = self.block(data_dir, [item_id],
                                                    detail_file=detail_file, fake=fake)
                self.assert_refused(stdout, item_id, reason)
                self.assertEqual(fake.calls, [])

        prepared = {
            "drivers source unreadable": self.prepare_packages(
                [ORPHAN], drivers_status="unreadable"),
            "driver_packages source unreadable": self.prepare_packages(
                [ORPHAN], packages_status="unreadable"),
            "more than one copy in the driver store": self.prepare_packages(
                [package_item("o1", "oem11.inf", "inventedtablet.inf", False,
                              other_published_names=["oem13.inf"])]),
            "a non-ASCII provider": self.prepare_packages(
                [package_item("o1", "oem14.inf", "inventedpen.inf", False,
                              provider="Invénted Pens®")]),
        }
        for case, (case_dir, case_file) in prepared.items():
            with self.subTest(case=case):
                fake = FakePowerShell()
                _code, stdout, _stderr = self.block(case_dir, ["o1"],
                                                    detail_file=case_file, fake=fake)
                self.assert_refused(stdout, "o1", reason)
                self.assertEqual(fake.calls, [])

    def test_bad_published_name(self):
        """K3: a bad published or original name gives no block and is never printed."""
        cases = (
            ("valid names, upper-case published name", "OEM12.INF", ORIGINAL, ()),
            ("published with a command", "oem1.inf; calc", ORIGINAL,
             ("oem1.inf; calc", "oem1.inf", "; calc", "calc")),
            ("published with a parent path", "..\\x.inf", ORIGINAL,
             ("..\\x.inf", "..\\", "x.inf")),
            ("original with a subexpression", PUBLISHED, "a$(calc).inf",
             ("a$(calc).inf", "$(", "calc")),
            ("original with a quote", PUBLISHED, "x';calc.inf",
             ("x';calc.inf", "x'", "';", "calc")),
        )
        for case, published, original, fragments in cases:
            with self.subTest(case=case):
                item = package_item("o1", published, original, False)
                data_dir, detail_file = self.prepare_packages([item])
                fake = FakePowerShell()
                _code, stdout, _stderr = self.block(data_dir, ["o1"],
                                                    detail_file=detail_file, fake=fake)
                self.assert_refused(stdout, "o1")
                self.assertEqual(fake.calls, [])
                for fragment in fragments:
                    self.assertNotIn(fragment.lower(), stdout.lower(),
                                     f"{fragment!r} reached the printed text:\n{stdout}")

    def test_no_removal_in_any_state(self):
        """Plan 051 M1, K8: a package in each of the three device states, otherwise fit
        for a block (valid names, not from the baseline, every source read), gets the
        ``no block`` line with the reason and no ``pnputil /delete-driver`` line."""
        def state_item(item_id, published, original, state, **extra):
            item = package_item(item_id, published, original, None, **extra)
            del item["present_device"]
            item["device_state"] = state
            return item

        present = state_item("o1", "oem7.inf", "inventedmouse.inf", "present")
        non_present = state_item(
            "o2", "oem8.inf", "inventedwebcam.inf", "non_present", class_name="Camera",
            devices=[{"device_name": "Invented Webcam", "class": "Camera",
                      "status": "Disconnected", "last_removal": "2026-05-04"}])
        no_device = state_item("o3", "oem9.inf", "inventedtablet.inf", "no_device_found",
                               class_name="HIDClass")
        data_dir, detail_file = self.prepare_packages([present, non_present, no_device])
        document = json.loads(detail_file.read_text(encoding="utf-8"))
        document["sources"].append(source("devices"))
        detail_file.write_text(json.dumps(document, indent=2), encoding="utf-8")

        reason = ("Windows refused every removal tried on this machine although no "
                  "device names the package without administrator rights; a removal is "
                  "not offered until a read proves Windows will accept it")
        for item_id, state in (("o1", "present"), ("o2", "non_present"),
                               ("o3", "no_device_found")):
            with self.subTest(state=state):
                fake = FakePowerShell()
                _code, stdout, _stderr = self.block(data_dir, [item_id],
                                                    detail_file=detail_file, fake=fake)
                self.assertEqual(fake.calls, [], "--block started a PowerShell job")
                line = self.assert_refused(stdout, item_id)
                self.assertIn(reason, line, line)
                self.assertNotRegex(stdout, r"(?i)/delete-driver", stdout)


if __name__ == "__main__":
    unittest.main()

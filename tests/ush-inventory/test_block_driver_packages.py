"""The ``--block o<n>`` printer for an orphan driver package (plan 027, milestone M1).

Interface under test (from the plan; the general one is in ``test_block.py``):

- ``main(["--data-dir", <dir>, "--block", "o1", "--detail-file", <file>])`` prints a block
  for a ``driver_packages`` item of the detail file only when all of these hold:
  ``present_device`` is ``false``; the item is not ``from_baseline``; the sources
  ``driver_packages`` and ``drivers`` were read; ``published_name`` matches
  ``^oem\\d+\\.inf$`` (any case); ``original_name`` matches ``^[A-Za-z0-9_.\\-]+\\.inf$``.
  Otherwise it prints ``# o<n>: no block: <reason>``.
- The block is for an elevated shell. In order: ``pnputil /export-driver <oem>
  '<data dir>\\work\\driver-<stamp>-<oem>'``; a check of ``$LASTEXITCODE`` and of
  ``Test-Path -LiteralPath '<export folder>\\<original name>'`` that throws "export
  missing, nothing removed"; ``pnputil /delete-driver <oem>`` without ``/force`` or
  ``/uninstall``; a check of ``$LASTEXITCODE`` that throws; ``Test-Path
  "$env:WINDIR\\INF\\<oem>"`` as the read-back. Then ``# Rollback, same shell:`` and
  ``pnputil /add-driver '<export folder>\\<original name>' /install``.

Assumptions added by these tests beyond the plan text:

- A detail item of ``driver_packages`` has the fields of references/summary-contract.md
  "Driver packages" plus ``source`` (``driver_packages``) and ``own`` (``false``) like the
  other detail items; ``listed["driver_packages"]`` holds the listable ids.
- ``<oem>`` in the export folder name may be written with or without ``.inf``; the stamp
  holds at least one digit.

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

ROLLBACK_MARKER = r"^\s*#\s*Rollback, same shell:\s*$"


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

    def assert_has_block(self, data_dir, detail_file, item_id, published):
        """Clean-data control: the same fixture with a valid item keeps its block, so a
        refusal that fires too widely fails."""
        code, stdout, stderr = self.block(data_dir, [item_id], detail_file=detail_file)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        self.assertNotRegex(stdout, rf"(?m)^\s*#\s*{item_id}\s*:\s*no block", stdout)
        delete = rf"(?i)\bpnputil(?:\.exe)?\s+/delete-driver\s+'?{re.escape(published)}'?"
        self.assertTrue(any(re.search(delete, line) for line in commands(stdout)), stdout)


class TestDriverPackageBlock(DriverPackageBlockTestCase):
    def test_orphan_block_order_and_rollback(self):
        """K1: the guarded export, check, delete and read-back, then the rollback."""
        data_dir, detail_file = self.prepare_packages([ORPHAN])
        work = str(data_dir / "work")
        fake = FakePowerShell()
        with mock.patch("subprocess.Popen",
                        side_effect=AssertionError("a process was started")) as popen:
            code, stdout, stderr = self.block(data_dir, ["o1"], detail_file=detail_file,
                                              fake=fake)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        self.assertEqual(fake.calls, [], "--block started a PowerShell job")
        self.assertFalse(popen.called, "--block started a process")
        self.assertNotRegex(stdout, r"(?m)^\s*#\s*o1\s*:\s*no block", stdout)

        lines = stdout.splitlines()
        markers = [i for i, line in enumerate(lines) if re.match(ROLLBACK_MARKER, line)]
        self.assertEqual(len(markers), 1, stdout)
        change_part = "\n".join(lines[:markers[0]])
        rollback_part = "\n".join(lines[markers[0] + 1:])
        self.assert_shell(change_part, elevated=True)

        text = "\n".join(commands(change_part))
        published = re.escape(PUBLISHED)
        export = re.search(
            rf"(?i)\bpnputil(?:\.exe)?\s+/export-driver\s+'?{published}'?\s+"
            rf"'({re.escape(work)}\\driver-[^'\\]*\d[^'\\]*-oem7(?:\.inf)?)'", text)
        self.assertIsNotNone(export, f"no export into a stamped folder under {work}:\n"
                                     + change_part)
        folder = export.group(1)
        exported_inf = f"{folder}\\{ORIGINAL}"

        deletes = list(re.finditer(
            rf"(?i)\bpnputil(?:\.exe)?\s+/delete-driver\s+'?{published}'?", stdout))
        self.assertEqual(len(deletes), 1, stdout)
        delete = re.search(rf"(?i)\bpnputil(?:\.exe)?\s+/delete-driver\s+'?{published}'?",
                           text)
        self.assertIsNotNone(delete, change_part)
        self.assertLess(export.end(), delete.start(), change_part)
        self.assertNotRegex(stdout, r"(?i)/force\b", stdout)
        self.assertNotRegex(stdout, r"(?i)/uninstall\b", stdout)

        # Between the export and the delete: the exit code and the exact exported inf
        # are checked, and a failed check throws that nothing was removed.
        check = text[export.end():delete.start()]
        self.assertIn("$LASTEXITCODE", check, change_part)
        self.assertRegex(
            check,
            rf"(?is)Test-Path\s+-LiteralPath\s+'{re.escape(exported_inf)}'"
            r".*?\bthrow\b[^\n]*nothing (?:was )?removed", change_part)

        # After the delete: its exit code is checked with a throw, then the read-back.
        after = text[delete.end():]
        readback = re.search(
            rf'(?i)Test-Path\s+(?:-LiteralPath\s+)?"\$env:WINDIR\\INF\\{published}"', after)
        self.assertIsNotNone(readback, change_part)
        between = after[:readback.start()]
        self.assertIn("$LASTEXITCODE", between, change_part)
        self.assertRegex(between, r"(?i)\bthrow\b", change_part)

        rollback_commands = commands(rollback_part)
        self.assertTrue(rollback_commands, stdout)
        self.assertRegex(
            rollback_commands[0],
            rf"(?i)^\s*pnputil(?:\.exe)?\s+/add-driver\s+'{re.escape(exported_inf)}'"
            r"\s+/install\b", rollback_part)
        self.assertNotRegex(rollback_part, r"(?i)/delete-driver", rollback_part)

    def test_refused_packages(self):
        """K2: a used, extension or baseline package and an unread drivers source."""
        present = package_item("o2", "oem8.inf", "inventedcamera.inf", True)
        extension = package_item(
            "o3", "oem9.inf", "inventedextension.inf", None, class_name="Extension",
            present_device_reason="extension package: not listed per device")
        baseline = package_item("o4", "oem10.inf", "inventedkeyboard.inf", False,
                                from_baseline=True)
        data_dir, detail_file = self.prepare_packages([ORPHAN, present, extension, baseline])
        with self.subTest(case="clean control: the orphan of the same file"):
            self.assert_has_block(data_dir, detail_file, "o1", PUBLISHED)
        cases = (
            ("present_device true", "o2", r"(?i)device"),
            ("present_device null", "o3", r"(?i)device"),
            ("from_baseline", "o4", r"(?i)baseline"),
        )
        for case, item_id, reason in cases:
            with self.subTest(case=case):
                fake = FakePowerShell()
                _code, stdout, _stderr = self.block(data_dir, [item_id],
                                                    detail_file=detail_file, fake=fake)
                self.assert_refused(stdout, item_id, reason)
                self.assertEqual(fake.calls, [])

        with self.subTest(case="drivers source unreadable"):
            unread_dir, unread_file = self.prepare_packages([ORPHAN],
                                                            drivers_status="unreadable")
            fake = FakePowerShell()
            _code, stdout, _stderr = self.block(unread_dir, ["o1"],
                                                detail_file=unread_file, fake=fake)
            self.assert_refused(stdout, "o1", r"(?i)\bdrivers\b")
            self.assertEqual(fake.calls, [])

        with self.subTest(case="driver_packages source unreadable"):
            unread_dir, unread_file = self.prepare_packages([ORPHAN],
                                                            packages_status="unreadable")
            fake = FakePowerShell()
            _code, stdout, _stderr = self.block(unread_dir, ["o1"],
                                                detail_file=unread_file, fake=fake)
            self.assert_refused(stdout, "o1", r"(?i)\bdriver_packages\b")
            self.assertEqual(fake.calls, [])

        with self.subTest(case="more than one copy in the driver store"):
            copies = package_item("o5", "oem11.inf", "inventedtablet.inf", False,
                                  other_published_names=["oem13.inf"])
            copies_dir, copies_file = self.prepare_packages([copies])
            fake = FakePowerShell()
            _code, stdout, _stderr = self.block(copies_dir, ["o5"],
                                                detail_file=copies_file, fake=fake)
            self.assert_refused(stdout, "o5", r"(?i)cop(?:y|ies)")
            self.assertEqual(fake.calls, [])

        with self.subTest(case="clean control: a non-ASCII provider keeps the block"):
            accent = package_item("o6", "oem14.inf", "inventedpen.inf", False,
                                  provider="Invénted Pens®")
            accent_dir, accent_file = self.prepare_packages([accent])
            self.assert_has_block(accent_dir, accent_file, "o6", "oem14.inf")

    def test_bad_published_name(self):
        """K3: a bad published or original name gives no block and is never printed."""
        with self.subTest(case="clean control: valid names, upper-case published name"):
            item = package_item("o1", "OEM12.INF", ORIGINAL, False)
            data_dir, detail_file = self.prepare_packages([item])
            self.assert_has_block(data_dir, detail_file, "o1", "OEM12.INF")
        cases = (
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


if __name__ == "__main__":
    unittest.main()

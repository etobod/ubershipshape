"""Antivirus, Defender, restore points, WinRE and per-source statuses in
health.py (plan 047, M3).

Every product, status and reagentc output is invented; PowerShell is never
started and nothing is read from the machine.
"""

import importlib
import unittest
from typing import ClassVar

_fakes = importlib.import_module("tests.ush-health.fakes_m3")
FakePowerShell = _fakes.FakePowerShell
HealthTestCase = _fakes.HealthTestCase
ok = _fakes.ok
failure = _fakes.failure

PRODUCT = {"displayName": "Invented Antivirus Suite", "productState": 397312}  # 0x61000


def defender(signature_age=1, quick_scan_age=1):
    return {
        "AMRunningMode": "Normal",
        "RealTimeProtectionEnabled": True,
        "AntivirusSignatureAge": signature_age,
        "QuickScanAge": quick_scan_age,
        "AntivirusSignatureLastUpdated": "2026-09-27T06:00:00Z",
    }


def restore_point(creation_time, sequence):
    return {
        "CreationTime": creation_time,
        "Description": f"Invented restore point {sequence}",
        "SequenceNumber": sequence,
    }


WINRE_ENABLED = (
    "\r\n"
    "Windows Recovery Environment (Windows RE) and system reset configuration\r\n"
    "Information:\r\n"
    "\r\n"
    "    Windows RE status:         Enabled\r\n"
    "    Windows RE location:       \\\\?\\GLOBALROOT\\device\\harddisk9\\partition9"
    "\\Recovery\\WindowsRE\r\n"
    "    Boot Configuration Data (BCD) identifier: 00000000-0000-0000-0000-000000000000\r\n"
    "    Recovery image location:   \r\n"
    "    Recovery image index:      0\r\n"
    "    Custom image location:     \r\n"
    "    Custom image index:        0\r\n"
    "\r\n"
    "REAGENTC.EXE: Operation Successful.\r\n"
    "\r\n"
)

WINRE_UNRECOGNISED = (
    "\r\n"
    "Invented tool banner without any recognisable status line.\r\n"
    "Some other invented text: 12345\r\n"
)

OS_VERSION = {
    "DisplayVersion": "24H2",
    "CurrentBuild": "26100",
    "UBR": 1234,
    "EditionID": "Professional",
}


class TestDefender(HealthTestCase):
    def defender_block(self, summary):
        antivirus = summary.get("antivirus")
        self.assertIsInstance(antivirus, dict, antivirus)
        self.assertIsInstance(antivirus.get("defender"), dict, antivirus)
        return antivirus["defender"]

    def test_sentinels_are_unknown(self):
        with self.subTest(case="sentinel values"):
            fake = FakePowerShell({
                "antivirus_products": ok([PRODUCT]),
                "defender": ok(defender(signature_age=65535, quick_scan_age=4294967295)),
            })
            block = self.defender_block(self.collect(fake))
            self.assertIn("signature_age_days", block)
            self.assertIsNone(block["signature_age_days"])
            self.assertIn("quick_scan_age_days", block)
            self.assertIsNone(block["quick_scan_age_days"])
            self.assertEqual(block.get("running_mode"), "Normal")
            self.assertIs(block.get("real_time_protection_enabled"), True)

        with self.subTest(case="ordinary values"):
            fake = FakePowerShell({
                "antivirus_products": ok([PRODUCT]),
                "defender": ok(defender(signature_age=1, quick_scan_age=1)),
            })
            block = self.defender_block(self.collect(fake))
            self.assertEqual(block.get("signature_age_days"), 1)
            self.assertEqual(block.get("quick_scan_age_days"), 1)


class TestAdmin(HealthTestCase):
    def test_recovery_not_checked_without_admin(self):
        fake = FakePowerShell({
            "restore_points": ok([restore_point("20260901103000.000000+120", 1)]),
            "winre": ok({"Output": WINRE_ENABLED}),
        })
        summary = self.collect(fake, admin=False)

        self.assertNotIn("restore_points", fake.jobs())
        self.assertNotIn("winre", fake.jobs())
        whats = self.not_checked_whats(summary)
        for name in ("restore_points", "winre"):
            with self.subTest(source=name):
                src = self.source(summary, name)
                self.assertEqual(src.get("status"), "unreadable", src)
                self.assertIn("administrator", str(src.get("reason")), src)
                self.assertIn(name, whats)


class TestWinre(HealthTestCase):
    def test_status_line(self):
        with self.subTest(case="enabled"):
            fake = FakePowerShell({"winre": ok({"Output": WINRE_ENABLED})})
            summary = self.collect(fake, admin=True)
            self.assertEqual(self.source(summary, "winre").get("status"), "read")
            self.assertIsInstance(summary.get("winre"), dict, summary.get("winre"))
            self.assertEqual(summary["winre"].get("status"), "Enabled")

        with self.subTest(case="unrecognised output"):
            fake = FakePowerShell({"winre": ok({"Output": WINRE_UNRECOGNISED})})
            summary = self.collect(fake, admin=True)
            src = self.source(summary, "winre")
            self.assertEqual(src.get("status"), "unreadable", src)
            self.assertIn("unrecognised reagentc output", str(src.get("reason")), src)
            winre = summary.get("winre")
            if isinstance(winre, dict):
                # Never guessed as disabled.
                self.assertNotIn(str(winre.get("status")).lower(), ("disabled", "false"))


class TestAntivirus(HealthTestCase):
    def test_partial_read(self):
        with self.subTest(case="defender fails, SecurityCenter2 works"):
            fake = FakePowerShell({
                "antivirus_products": ok([PRODUCT]),
                "defender": failure("Get-MpComputerStatus : Invented failure text."),
            })
            summary = self.collect(fake)
            self.assertEqual(self.source(summary, "antivirus").get("status"), "read")
            antivirus = summary.get("antivirus")
            self.assertIsInstance(antivirus, dict, antivirus)
            self.assertIn("defender", antivirus)
            self.assertIsNone(antivirus["defender"])
            self.assertEqual(
                antivirus.get("products"),
                [{"display_name": "Invented Antivirus Suite", "product_state": "0x61000"}],
            )
            entries = [
                e for e in self.not_checked(summary) if "defender" in str(e.get("what")).lower()
            ]
            self.assertTrue(entries, summary["not_checked"])
            self.assertTrue(str(entries[0].get("reason") or "").strip(), entries[0])

        with self.subTest(case="both parts fail"):
            fake = FakePowerShell({
                "antivirus_products": failure("Get-CimInstance : Invented failure text."),
                "defender": failure("Get-MpComputerStatus : Invented failure text."),
            })
            summary = self.collect(fake)
            src = self.source(summary, "antivirus")
            self.assertEqual(src.get("status"), "unreadable", src)
            self.assertTrue(str(src.get("reason") or "").strip(), src)

        with self.subTest(case="no products listed, defender fails"):
            fake = FakePowerShell({
                "antivirus_products": ok([]),
                "defender": failure("Get-MpComputerStatus : Invented failure text."),
            })
            summary = self.collect(fake)
            src = self.source(summary, "antivirus")
            # Half the source failed: not "empty", which would mean "no antivirus".
            self.assertEqual(src.get("status"), "unreadable", src)
            self.assertIn("defender", str(src.get("reason")))
            self.assertEqual(summary["antivirus"]["products"], [])


class TestRestorePoints(HealthTestCase):
    def test_dmtf_time(self):
        rows = [
            restore_point("20260901103000.000000+120", 1),
            restore_point("20260915201500.000000-060", 2),
        ]
        summary = self.collect(FakePowerShell({"restore_points": ok(rows)}), admin=True)
        self.assertEqual(self.source(summary, "restore_points").get("status"), "read")
        points = summary.get("restore_points")
        self.assertIsInstance(points, dict, points)
        self.assertEqual(points.get("count"), 2)
        self.assertEqual(points.get("oldest"), "2026-09-01T08:30:00Z")
        # A negative offset moves the UTC time forward.
        self.assertEqual(points.get("newest"), "2026-09-15T21:15:00Z")


class TestSources(HealthTestCase):
    FAILING_JOBS: ClassVar[dict] = {
        "update_history": ("update_history",),
        "pending_reboot": ("pending_reboot",),
        "os_version": ("os_version",),
        "antivirus": ("antivirus_products", "defender"),
        "restore_points": ("restore_points",),
        "winre": ("winre",),
    }

    def check_single_object(self, name, summary):
        """The source read from a single JSON object, not a list."""
        self.assertEqual(self.source(summary, name).get("status"), "read")
        if name == "update_history":
            updates = summary.get("updates")
            self.assertIsInstance(updates, dict, updates)
            self.assertEqual(updates.get("history_count"), 1)
            self.assertEqual(len(updates.get("failures") or []), 1, updates)
            self.assertEqual(updates["failures"][0].get("hresult"), "0x80004005")
        elif name == "pending_reboot":
            self.assertEqual(
                summary.get("pending_reboot"),
                {
                    "windows_update": True,
                    "component_servicing": False,
                    "file_rename_operations": False,
                },
            )
        elif name == "os_version":
            version = summary.get("os_version")
            self.assertIsInstance(version, dict, version)
            self.assertEqual(version.get("display_version"), "24H2")
            self.assertEqual(str(version.get("build")), "26100")
            self.assertEqual(version.get("ubr"), 1234)
            self.assertEqual(version.get("edition_id"), "Professional")
        elif name == "antivirus":
            antivirus = summary.get("antivirus")
            self.assertIsInstance(antivirus, dict, antivirus)
            self.assertEqual(
                antivirus.get("products"),
                [{"display_name": "Invented Antivirus Suite", "product_state": "0x61000"}],
            )
        elif name == "restore_points":
            points = summary.get("restore_points")
            self.assertIsInstance(points, dict, points)
            self.assertEqual(points.get("count"), 1)
            self.assertEqual(points.get("newest"), "2026-09-01T08:30:00Z")
            self.assertEqual(points.get("oldest"), "2026-09-01T08:30:00Z")
        elif name == "winre":
            self.assertEqual((summary.get("winre") or {}).get("status"), "Enabled")

    def single_object_responses(self):
        return {
            "update_history": ok({
                "Title": "Invented Feature Update",
                "ResultCode": 4,
                "HResult": -2147467259,
                "Date": "2026-09-02T07:00:00",
            }),
            "pending_reboot": ok({
                "WindowsUpdateRebootRequired": True,
                "ComponentBasedServicingRebootPending": False,
                "PendingFileRenameOperations": False,
            }),
            "os_version": ok(OS_VERSION),
            "antivirus_products": ok(PRODUCT),
            "defender": ok(defender()),
            "restore_points": ok(restore_point("20260901103000.000000+120", 1)),
            "winre": ok({"Output": WINRE_ENABLED}),
        }

    def test_each_source_statuses(self):
        for name, jobs in self.FAILING_JOBS.items():
            with self.subTest(source=name, case="job fails"):
                responses = {
                    job: failure(f"Invented failure text for {job}.") for job in jobs
                }
                fake = FakePowerShell(responses)
                summary = self.collect(fake, admin=True)
                for job in jobs:
                    self.assertIn(job, fake.jobs())
                if name == "antivirus":
                    src = self.source(summary, "antivirus")
                    self.assertEqual(src.get("status"), "unreadable", src)
                    self.assertTrue(str(src.get("reason") or "").strip(), src)
                    whats = [w.lower() for w in self.not_checked_whats(summary)]
                    self.assertTrue(any("defender" in w for w in whats), whats)
                    self.assertTrue(
                        any("defender" not in w and ("antivirus" in w or "product" in w)
                            for w in whats),
                        whats,
                    )
                else:
                    self.assert_unreadable_with_entry(summary, name)
                if name == "update_history":
                    self.assertIn("updates", summary)
                    self.assertIsNone(summary["updates"])

            with self.subTest(source=name, case="single object"):
                fake = FakePowerShell(self.single_object_responses())
                summary = self.collect(fake, admin=True)
                self.check_single_object(name, summary)


if __name__ == "__main__":
    unittest.main()

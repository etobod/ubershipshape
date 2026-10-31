"""Behaviour tests for the hardware and storage sources of
skills/ush-health/scripts/health.py (milestone M2).

Public interface under test:
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``, summary JSON on stdout.
- ``run_ps`` and ``is_admin`` are replaced by fakes; PowerShell never starts and
  nothing is read from the machine. All data is invented.
"""

from typing import ClassVar

from .fakes import (
    GIB,
    FakePowerShell,
    HealthTestCase,
    device,
    disk,
    failure,
    ok,
    reliability,
    volume,
)

NO_PNP_STDERR = (
    "Get-PnpDevice : No matching Win32_PnPEntity objects found by CIM query for "
    "instances of the ROOT/cimv2/Win32_PnPEntity class on the  CIM server: "
    "SELECT * FROM Win32_PnPEntity  WHERE ((PNPClass LIKE 'SecurityDevices')). "
    "Verify query parameters and retry.\r\n"
    "At line:1 char:1\r\n"
    "    + CategoryInfo          : ObjectNotFound: (Win32_PnPEntity:String) "
    "[Get-PnpDevice], CimJobException\r\n"
)


class TestAdmin(HealthTestCase):
    def test_admin_only_source_is_not_checked_without_admin(self):
        fake = FakePowerShell()
        summary = self.collect(fake, admin=False)

        self.assertNotIn("disk_reliability", fake.jobs())
        self.assertIs(summary["elevated"], False)
        self.assert_unreadable(summary, "disk_reliability", reason_part="administrator")
        self.assertIn("disk_reliability", self.not_checked_whats(summary))

        self.assertEqual(self.source(summary, "physical_disks")["status"], "read")
        disks = summary["disks"]
        self.assertEqual(len(disks), 1, disks)
        self.assertIsNone(disks[0]["reliability"])

    def test_reliability_joined_to_disk_when_admin(self):
        fake = FakePowerShell({
            "physical_disks": ok([
                disk("0", "Invented Disk 1000"),
                disk("1", "Invented Disk 2000", size=1024 * GIB),
            ]),
            # Listed in the opposite order to the disks: the join goes by DeviceId.
            "disk_reliability": ok([
                reliability("1", temperature=48, wear=17, read_errors=5,
                            write_errors=3, hours=20000),
                reliability("0", temperature=31, wear=1, read_errors=0,
                            write_errors=0, hours=150),
            ]),
        })
        summary = self.collect(fake, admin=True)

        self.assertIn("disk_reliability", fake.jobs())
        self.assertIs(summary["elevated"], True)
        self.assertEqual(self.source(summary, "disk_reliability")["status"], "read")

        by_name = {d["friendly_name"]: d for d in summary["disks"]}
        self.assertEqual(set(by_name), {"Invented Disk 1000", "Invented Disk 2000"})
        self.assertEqual({d["id"] for d in summary["disks"]}, {"k1", "k2"})
        self.assertEqual(by_name["Invented Disk 1000"]["reliability"], {
            "temperature_c": 31,
            "wear_percent": 1,
            "read_errors_total": 0,
            "write_errors_total": 0,
            "power_on_hours": 150,
        })
        self.assertEqual(by_name["Invented Disk 2000"]["reliability"], {
            "temperature_c": 48,
            "wear_percent": 17,
            "read_errors_total": 5,
            "write_errors_total": 3,
            "power_on_hours": 20000,
        })

    def test_zero_temperature_is_unknown(self):
        fake = FakePowerShell({
            "disk_reliability": ok([reliability("0", temperature=0, wear=0,
                                                read_errors=0)]),
        })
        summary = self.collect(fake, admin=True)

        counters = summary["disks"][0]["reliability"]
        self.assertIsNone(counters["temperature_c"])
        # Zero stays a reading where zero is a real value.
        self.assertEqual(counters["wear_percent"], 0)
        self.assertEqual(counters["read_errors_total"], 0)

    def test_one_disk_counter_error_keeps_the_others(self):
        failed = reliability("1")
        for key in ("Temperature", "Wear", "ReadErrorsTotal", "WriteErrorsTotal",
                    "PowerOnHours"):
            failed[key] = None
        failed["Error"] = "Invented: the counter is not supported"
        fake = FakePowerShell({
            "physical_disks": ok([
                disk("0", "Invented Disk 1000"),
                disk("1", "Invented Disk 2000"),
            ]),
            "disk_reliability": ok([reliability("0", temperature=31), failed]),
        })
        summary = self.collect(fake, admin=True)

        script = next(call[1] for call in fake.calls if call[0] == "disk_reliability")
        self.assertIn("-ErrorAction Stop", script)
        self.assertEqual(self.source(summary, "disk_reliability")["status"], "read")
        by_name = {d["friendly_name"]: d for d in summary["disks"]}
        self.assertEqual(by_name["Invented Disk 1000"]["reliability"]["temperature_c"], 31)
        self.assertIsNone(by_name["Invented Disk 2000"]["reliability"])
        skipped = [item for item in summary["not_checked"]
                   if "Invented Disk 2000" in item["what"]]
        self.assertEqual(len(skipped), 1, summary["not_checked"])
        self.assertIn("not supported", skipped[0]["reason"])


class TestTpm(HealthTestCase):
    def test_null_fields_stay_null(self):
        fake = FakePowerShell({
            "tpm_wmi": ok({
                "SpecVersion": None,
                "IsEnabled_InitialValue": None,
                "IsActivated_InitialValue": None,
            }),
        })
        summary = self.collect(fake, admin=True)

        self.assertIn("tpm_wmi", fake.jobs())
        for job, script, _ in fake.calls:
            with self.subTest(job=job):
                self.assertNotIn("get-tpm", script.lower())

        tpm = summary["tpm"]
        self.assertIsNone(tpm["spec_version"])
        self.assertIsNone(tpm["is_enabled"])
        self.assertIsNone(tpm["is_activated"])
        self.assertEqual(
            tpm["devices"],
            [{"name": "Invented Trusted Platform Module 2.0", "status": "OK"}],
        )

    def test_no_security_device_is_empty(self):
        fake = FakePowerShell({
            "tpm_devices": failure(NO_PNP_STDERR, code=1),
            "tpm_wmi": ok([]),
        })
        summary = self.collect(fake, admin=True)

        self.assertIn("tpm_devices", fake.jobs())
        src = self.source(summary, "tpm")
        self.assertEqual(src["status"], "empty", src)
        self.assertEqual(summary["tpm"]["devices"], [])

    def test_no_device_and_wmi_failure_is_unreadable(self):
        fake = FakePowerShell({
            "tpm_devices": failure(NO_PNP_STDERR, code=1),
            "tpm_wmi": failure("Get-CimInstance : Invented access failure", code=1),
        })
        summary = self.collect(fake, admin=True)

        src = self.source(summary, "tpm")
        # Half of the source failed: not "empty", which would mean "no TPM".
        self.assertEqual(src["status"], "unreadable", src)
        self.assertIn("tpm_wmi", src["reason"])
        self.assertIn("tpm_wmi", self.not_checked_whats(summary))


class TestBattery(HealthTestCase):
    def test_no_battery_is_empty(self):
        fake = FakePowerShell({"battery": ok([])})
        summary = self.collect(fake)

        self.assertIn("battery", fake.jobs())
        self.assertNotIn("battery_report", fake.jobs())
        src = self.source(summary, "battery")
        self.assertEqual(src["status"], "empty", src)
        self.assertIs(summary["battery"]["present"], False)

    def test_failure_and_zero_cycles(self):
        present = ok([{"Name": "Invented Battery 3000", "DeviceID": "Invented-Battery-1"}])

        with self.subTest("powercfg fails"):
            fake = FakePowerShell({
                "battery": present,
                "battery_report": failure(
                    "Unable to perform operation. An unexpected error (0x1) has occurred: "
                    "Invented failure.", code=1),
            })
            summary = self.collect(fake)
            self.assertIn("battery_report", fake.jobs())
            self.assert_unreadable(summary, "battery")

        with self.subTest("zero cycles and zero design capacity"):
            fake = FakePowerShell({
                "battery": present,
                "battery_report": ok(
                    {"DesignCapacity": 0, "FullChargeCapacity": 41000, "CycleCount": 0}
                ),
            })
            summary = self.collect(fake)
            self.assertEqual(self.source(summary, "battery")["status"], "read")
            battery = summary["battery"]
            self.assertIs(battery["present"], True)
            self.assertEqual(battery["full_charge_capacity_mwh"], 41000)
            self.assertIsNone(battery["cycle_count"])
            self.assertIsNone(battery["full_charge_percent_of_design"])

        with self.subTest("control: real values pass through"):
            fake = FakePowerShell({
                "battery": present,
                "battery_report": ok(
                    {"DesignCapacity": 50000, "FullChargeCapacity": 41000, "CycleCount": 87}
                ),
            })
            battery = self.collect(fake)["battery"]
            self.assertEqual(battery["design_capacity_mwh"], 50000)
            self.assertEqual(battery["cycle_count"], 87)
            self.assertEqual(battery["full_charge_percent_of_design"], 82.0)


class TestVolumes(HealthTestCase):
    def test_rounded_values(self):
        fake = FakePowerShell({
            "volumes": ok([
                volume("C", size=107374182400, remaining=32212254720),
                volume("D", size=0, remaining=0, fs="RAW"),
                volume(None, size=524288000, remaining=104857600),
            ]),
            "encryption": ok([
                {"DriveLetter": "C", "BitLockerProtection": 1},
                {"DriveLetter": "D", "BitLockerProtection": 0},
            ]),
        })
        summary = self.collect(fake)

        self.assertEqual(self.source(summary, "volumes")["status"], "read")
        volumes = summary["volumes"]
        by_letter = {self.letter(v["drive_letter"]): v for v in volumes}
        self.assertEqual(set(by_letter), {"C", "D"}, volumes)
        self.assertEqual({v["id"] for v in volumes}, {"v1", "v2"})

        c = by_letter["C"]
        self.assertEqual(c["size_gb"], 100.0)
        self.assertEqual(c["free_gb"], 30.0)
        self.assertEqual(c["free_percent"], 30.0)
        self.assertEqual(c["file_system"], "NTFS")

        d = by_letter["D"]
        self.assertIsNone(d["free_percent"])
        self.assertEqual(d["size_gb"], 0.0)


class TestDevices(HealthTestCase):
    def test_clean_devices_read_not_empty(self):
        with self.subTest("all devices OK"):
            fake = FakePowerShell({
                "devices": ok([
                    device("Invented PCI Bridge 1"),
                    device("Invented Audio Device 2", cls="MEDIA"),
                    device("Invented Network Adapter 3", cls="Net"),
                ]),
            })
            summary = self.collect(fake)
            src = self.source(summary, "devices")
            self.assertEqual(src["status"], "read", src)
            self.assertEqual(summary["devices"], [])
            self.assertEqual(summary["devices_by_status"], {"OK": 3})

        with self.subTest("one device as a single JSON object"):
            fake = FakePowerShell({"devices": ok(device("Invented PCI Bridge 1"))})
            summary = self.collect(fake)
            src = self.source(summary, "devices")
            self.assertEqual(src["status"], "read", src)
            self.assertEqual(summary["devices"], [])
            self.assertEqual(summary["devices_by_status"], {"OK": 1})


class TestSecureBoot(HealthTestCase):
    def test_missing_value_is_unknown(self):
        fake = FakePowerShell({
            "secure_boot": ok({"UEFISecureBootEnabled": None, "FirmwareType": "UEFI"}),
        })
        summary = self.collect(fake)
        src = self.source(summary, "secure_boot")
        self.assertEqual(src["status"], "read", src)
        self.assertIsNone(summary["secure_boot"]["enabled"])
        self.assertEqual(summary["secure_boot"]["firmware_type"], "UEFI")

        # Control: an explicit 0 is a real "off", not unknown.
        fake = FakePowerShell({
            "secure_boot": ok({"UEFISecureBootEnabled": 0, "FirmwareType": "UEFI"}),
        })
        self.assertIs(self.collect(fake)["secure_boot"]["enabled"], False)


class TestEncryption(HealthTestCase):
    def test_missing_value_and_no_volumes(self):
        fake = FakePowerShell({
            "volumes": ok([volume("C"), volume("D"), volume("E")]),
            "encryption": ok([
                {"DriveLetter": "C", "BitLockerProtection": ""},
                {"DriveLetter": "D", "BitLockerProtection": None},
                {"DriveLetter": "E", "BitLockerProtection": 1},
            ]),
        })
        summary = self.collect(fake)
        by_letter = {self.letter(v["drive_letter"]): v for v in summary["volumes"]}
        self.assertIsNone(by_letter["C"]["protection"])
        self.assertIsNone(by_letter["D"]["protection"])
        self.assertEqual(by_letter["E"]["protection"], 1)

        fake = FakePowerShell({
            "volumes": failure("Get-Volume : Invented access denied", code=1),
        })
        summary = self.collect(fake)
        self.assertNotIn("encryption", fake.jobs())
        self.assert_unreadable(summary, "volumes")
        self.assert_unreadable(summary, "encryption", reason_part="volumes not read")


# source name -> (failing job, invented stderr)
FAILING_JOBS = {
    "physical_disks": ("physical_disks", "Get-PhysicalDisk : Access denied"),
    "volumes": ("volumes", "Get-Volume : Access denied"),
    "battery": ("battery", "Get-CimInstance : Invalid class \"Win32_Battery\""),
    "devices": ("devices", "Get-PnpDevice : Access denied"),
    "secure_boot": ("secure_boot", "Get-ItemProperty : Invented registry failure"),
    "tpm": ("tpm_devices", "Get-PnpDevice : Invented generic failure"),
    "encryption": ("encryption", "New-Object : Invented COM failure"),
}


class TestSources(HealthTestCase):
    def check_single_object(self, name, summary):
        """Each source read from one JSON object instead of a one-element list."""
        self.assertEqual(self.source(summary, name)["status"], "read")
        if name == "physical_disks":
            self.assertEqual(len(summary["disks"]), 1)
            self.assertEqual(summary["disks"][0]["friendly_name"], "Invented Disk 7000")
        elif name == "volumes":
            self.assertEqual(len(summary["volumes"]), 1)
            self.assertEqual(self.letter(summary["volumes"][0]["drive_letter"]), "C")
        elif name == "battery":
            self.assertIs(summary["battery"]["present"], True)
        elif name == "devices":
            self.assertEqual(summary["devices_by_status"], {"Error": 1})
            self.assertEqual(len(summary["devices"]), 1)
            self.assertEqual(summary["devices"][0]["name"], "Invented Camera 7")
        elif name == "secure_boot":
            self.assertIs(summary["secure_boot"]["enabled"], True)
        elif name == "tpm":
            self.assertEqual(
                summary["tpm"]["devices"],
                [{"name": "Invented Trusted Platform Module 7.0", "status": "OK"}],
            )
        elif name == "encryption":
            self.assertEqual(len(summary["volumes"]), 1)
            self.assertEqual(summary["volumes"][0]["protection"], 1)

    SINGLE_OBJECTS: ClassVar[dict] = {
        "physical_disks": {"physical_disks": ok(disk("0", "Invented Disk 7000"))},
        "volumes": {"volumes": ok(volume("C"))},
        "battery": {
            "battery": ok({"Name": "Invented Battery 7", "DeviceID": "Invented-Battery-7"}),
        },
        "devices": {
            "devices": ok(device("Invented Camera 7", status="Error",
                                 cls="Camera", problem="CM_PROB_FAILED_START")),
        },
        "secure_boot": {
            "secure_boot": ok({"UEFISecureBootEnabled": 1, "FirmwareType": "UEFI"}),
        },
        "tpm": {
            "tpm_devices": ok({"Name": "Invented Trusted Platform Module 7.0", "Status": "OK"}),
        },
        "encryption": {
            "volumes": ok(volume("C")),
            "encryption": ok({"DriveLetter": "C", "BitLockerProtection": 1}),
        },
    }

    def test_each_source_statuses(self):
        for name, (job, stderr) in FAILING_JOBS.items():
            with self.subTest(source=name, case="failing job"):
                fake = FakePowerShell({job: failure(stderr, code=1)})
                summary = self.collect(fake, admin=True)
                self.assertIn(job, fake.jobs())
                self.assert_unreadable(summary, name)
                whats = self.not_checked_whats(summary)
                self.assertTrue(
                    any(name in what for what in whats),
                    f"no not_checked entry for {name}: {summary['not_checked']}",
                )
                if name == "physical_disks":
                    self.assertIsNone(summary["disks"])
                if name == "volumes":
                    self.assertIsNone(summary["volumes"])

        for name, responses in self.SINGLE_OBJECTS.items():
            with self.subTest(source=name, case="single object"):
                summary = self.collect(FakePowerShell(responses), admin=True)
                self.check_single_object(name, summary)

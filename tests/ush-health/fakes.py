"""Shared fakes for the ush-health tests of milestone M2 (hardware and CLI).

``run_ps(job, script, out_path) -> (exit_code, stderr)`` is replaced by
``FakePowerShell``, which answers by job name and writes JSON to ``out_path``
the way Windows PowerShell 5.1 does (UTF-8 with a BOM). ``is_admin`` is replaced
by a plain function. Every value here is invented; nothing comes from a machine.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)

GIB = 1024 ** 3


def ok(payload):
    """PowerShell wrote ``payload`` as JSON and exited 0."""
    return ("ok", payload)


def failure(stderr, code=1):
    """PowerShell exited with ``code`` and wrote ``stderr``; no file is written."""
    return ("fail", code, stderr)


def disk(device_id="0", name="Invented Disk 1000", size=512 * GIB):
    return {
        "DeviceId": device_id,
        "FriendlyName": name,
        "MediaType": "SSD",
        "BusType": "NVMe",
        "Size": size,
        "HealthStatus": "Healthy",
        "OperationalStatus": "OK",
    }


def reliability(device_id="0", temperature=35, wear=2, read_errors=0,
                write_errors=0, hours=1200):
    return {
        "DeviceId": device_id,
        "Temperature": temperature,
        "Wear": wear,
        "ReadErrorsTotal": read_errors,
        "WriteErrorsTotal": write_errors,
        "PowerOnHours": hours,
    }


def volume(letter="C", size=200 * GIB, remaining=80 * GIB, fs="NTFS"):
    return {
        "DriveLetter": letter,
        "FileSystem": fs,
        "Size": size,
        "SizeRemaining": remaining,
        "HealthStatus": "Healthy",
    }


def device(name, status="OK", cls="System", problem="CM_PROB_NONE"):
    return {"Name": name, "Class": cls, "Status": status, "Problem": problem}


def default_responses():
    """A clean, invented machine: one disk, one volume, no battery, all devices OK."""
    return {
        "physical_disks": ok([disk()]),
        "disk_reliability": ok([reliability()]),
        "volumes": ok([volume()]),
        "battery": ok([]),
        "battery_report": ok(
            {"DesignCapacity": 50000, "FullChargeCapacity": 45000, "CycleCount": 120}
        ),
        "devices": ok([
            device("Invented PCI Bridge 1"),
            device("Invented USB Controller 2", cls="USB"),
        ]),
        "secure_boot": ok({"UEFISecureBootEnabled": 1, "FirmwareType": "UEFI"}),
        "tpm_devices": ok([{"Name": "Invented Trusted Platform Module 2.0", "Status": "OK"}]),
        "tpm_wmi": ok({
            "SpecVersion": "2.0, 0, 1.59",
            "IsEnabled_InitialValue": True,
            "IsActivated_InitialValue": True,
        }),
        "encryption": ok([{"DriveLetter": "C", "BitLockerProtection": 1}]),
    }


class FakePowerShell:
    """Stands in for run_ps. Jobs not listed answer ``ok([])``."""

    def __init__(self, responses=None):
        self.responses = default_responses()
        self.responses.update(responses or {})
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        response = self.responses.get(job, ok([]))
        if response[0] == "ok":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Windows PowerShell 5.1 writes UTF-8 with a BOM.
            out_path.write_text(json.dumps(response[1]), encoding="utf-8-sig")
            return 0, ""
        _, code, stderr = response
        return code, stderr

    def jobs(self):
        return [call[0] for call in self.calls]


class HealthTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.health = load_script("ush-health", "health")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def run_main(self, data_dir, fake, admin=True, now=NOW, extra=()):
        """Run main with both machine functions injected; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.health.main(
                ["--data-dir", str(data_dir), *extra],
                run_ps=fake,
                is_admin=lambda: admin,
                now=now,
            )
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            data = json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")
        return data

    def collect(self, fake, admin=True, data_dir=None, now=NOW):
        """Run a collection and return the parsed summary (exit code must be 0)."""
        code, stdout, stderr = self.run_main(
            data_dir or self.data_dir(), fake, admin=admin, now=now
        )
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def source(self, summary, name):
        self.assertIsInstance(summary.get("sources"), list, summary)
        matches = [s for s in summary["sources"] if s.get("name") == name]
        self.assertEqual(len(matches), 1, f"source {name}: {summary['sources']}")
        return matches[0]

    def assert_unreadable(self, summary, name, reason_part=None):
        src = self.source(summary, name)
        self.assertEqual(src["status"], "unreadable", src)
        self.assertIsInstance(src["reason"], str, src)
        self.assertTrue(src["reason"].strip(), src)
        if reason_part is not None:
            self.assertIn(reason_part, src["reason"], src)
        return src

    def not_checked_whats(self, summary):
        self.assertIsInstance(summary.get("not_checked"), list, summary)
        return [str(entry.get("what")) for entry in summary["not_checked"]]

    @staticmethod
    def letter(value):
        """Normalise a drive letter ("C", "C:" or "C:\\") to "C"."""
        return None if value is None else str(value).rstrip(":\\")

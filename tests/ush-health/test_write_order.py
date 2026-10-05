"""ush-health writes the detail file before the baseline (plan 141, M2, K5 and K7).

Interface under test (from the plan):

- ``health.main`` writes ``<data dir>/work/health-<stamp>.detail.json`` before
  ``baseline.save`` and ``baseline.archive``; the summary, which names the result of the
  baseline save (``baseline.saved``), is written last.
- An exception while writing the detail file ends the run without saving the baseline
  and without a history copy.

Assumptions added by these tests beyond the plan text:

- ``<stamp>`` is the UTC time of ``now`` as ``%Y%m%d-%H%M%S`` (the first run checks this
  against its own ``detail_file`` before the second run relies on it).
- A directory at the path of the detail file makes the write fail with an ``OSError``
  (``PermissionError`` / ``IsADirectoryError``) that ``main`` does not catch.
- Every run here has administrator rights, so the baseline is
  ``state/ush-health.elevated.json``; a moved-aside generation ends in ``.previous.json``
  and history copies live in ``state/history/`` with the ``YYYY-MM-DD`` day in the name.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import unittest
from datetime import timedelta
from pathlib import Path

from .fakes import GIB, NOW, FakePowerShell, HealthTestCase, ok, reliability

BASELINE_FILE = "ush-health.elevated.json"
DISK_UID = "INVENTED-UNIQUE-ID-0000000000W0RD3R"

FIRST_AT = NOW
# A different UTC day, so a history copy of the second run would carry another date.
SECOND_AT = NOW + timedelta(days=1)

OS_VERSION = {
    "DisplayVersion": "24H2",
    "CurrentBuild": "26100",
    "UBR": 4321,
    "EditionID": "Professional",
}


def stamp(moment):
    return moment.strftime("%Y%m%d-%H%M%S")


def volume_row(free_gb):
    return {
        "DriveLetter": "C",
        "FileSystem": "NTFS",
        "Size": 476 * GIB,
        "SizeRemaining": round(free_gb * GIB),
        "HealthStatus": "Healthy",
    }


def machine(free_gb=180.5):
    """An invented machine with a keyed disk, volume C and an os version."""
    return FakePowerShell({
        "physical_disks": ok([{
            "DeviceId": "0",
            "FriendlyName": "Invented Disk Order",
            "MediaType": "SSD",
            "BusType": "NVMe",
            "Size": 512 * GIB,
            "HealthStatus": "Healthy",
            "OperationalStatus": "OK",
            "UniqueId": DISK_UID,
        }]),
        "disk_reliability": ok([reliability("0")]),
        "volumes": ok([volume_row(free_gb)]),
        "os_version": ok(OS_VERSION),
    })


class TestWriteOrder(HealthTestCase):
    def first_run(self, data_dir):
        """Run once at FIRST_AT; check the detail file name; return the baseline bytes."""
        summary = self.collect(machine(), admin=True, data_dir=data_dir, now=FIRST_AT)
        detail = Path(summary.get("detail_file"))
        self.assertEqual(detail.name, f"health-{stamp(FIRST_AT)}.detail.json", summary)
        self.assertEqual(detail.parent.resolve(), (data_dir / "work").resolve())
        baseline_path = data_dir / "state" / BASELINE_FILE
        self.assertTrue(baseline_path.is_file(), f"{BASELINE_FILE} was not written")
        return baseline_path.read_bytes()

    def test_detail_failure_keeps_old_baseline(self):
        data_dir = self.data_dir()
        before = self.first_run(data_dir)
        state = data_dir / "state"
        previous_before = sorted(p.name for p in state.glob("*.previous.json"))

        blocker = data_dir / "work" / f"health-{stamp(SECOND_AT)}.detail.json"
        blocker.mkdir(parents=True)

        with self.assertRaises(OSError):
            self.run_main(data_dir, machine(free_gb=95.2), admin=True, now=SECOND_AT)

        self.assertEqual((state / BASELINE_FILE).read_bytes(), before,
                         "the baseline changed although the detail file was not written")
        self.assertEqual(sorted(p.name for p in state.glob("*.previous.json")),
                         previous_before, "a .previous.json was created")
        self.assertEqual(previous_before, [], "the first run left a .previous.json")
        history = state / "history"
        second_day = SECOND_AT.date().isoformat()
        dated = ([p.name for p in history.iterdir() if second_day in p.name]
                 if history.is_dir() else [])
        self.assertEqual(dated, [], "a history copy of the second run was written")

    def test_normal_run_saves_baseline(self):
        data_dir = self.data_dir()
        before = self.first_run(data_dir)

        summary = self.collect(machine(free_gb=95.2), admin=True, data_dir=data_dir,
                               now=SECOND_AT)
        info = summary.get("baseline")
        self.assertIsInstance(info, dict, summary)
        self.assertIs(info.get("saved"), True, info)
        baseline_path = data_dir / "state" / BASELINE_FILE
        self.assertTrue(baseline_path.is_file(), f"{BASELINE_FILE} was not written")
        self.assertNotEqual(baseline_path.read_bytes(), before,
                            "the baseline of the second run was not saved")
        self.assertTrue(Path(summary.get("detail_file")).is_file(), summary)


if __name__ == "__main__":
    unittest.main()

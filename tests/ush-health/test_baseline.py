"""The ush-health baseline: changes of disks, volumes, failing devices and the Windows
version between runs (plan 110, M3, K5), and blank keys treated as no key
(loc/inbox/123).

Interface under test (from the plan; the general one is in ``fakes.py``):

- ``health.main`` loads and saves a baseline (``baseline.load``, ``save``, ``archive``)
  and takes ``--compare-to <N>d`` as ``ush-inventory`` does. Baseline sources and keys:
  ``disks`` (``unique_id``), ``volumes`` (``drive_letter``), ``devices``
  (``instance_id``, only devices whose status is not ``OK``) and ``os`` (``"os"``).
- The summary has ``changes``: items ``{id, source, kind, item, name, fields}`` with ids
  ``c1``... in the order of the sources above, then by key; ``kind`` is ``added``,
  ``removed`` or ``changed``; ``item`` is the id of the current item; ``fields`` is
  ``{field: {before, after}}`` for ``changed``.
- The summary has ``baseline`` (shared shape plus ``reference`` and ``reference_file``)
  and ``comparison`` (``{baseline source: comparison state}``).
- A compared field whose current value is ``None`` gives no change; the saved item keeps
  the previous value for it.
- A device whose ``instance_id`` is ``null`` or repeated is not in the baseline and gives
  a ``not_checked`` item "device not compared: ..."; a disk without ``unique_id`` gives
  the ``not_checked`` item with ``what`` "disk not compared: no UniqueId" and its name
  in ``reason``.
- An empty or blank ``UniqueId`` / ``InstanceId`` is treated exactly like ``null``
  (loc/inbox/123): a one-time id not kept in ``state/ush-health.ids.json``, not in the
  baseline, and the same ``not_checked`` items as for ``null``.

Assumptions added by these tests beyond the plan text:

- Every run here has administrator rights, so the baseline is
  ``state/ush-health.elevated.json`` and its history copies
  ``state/history/ush-health.elevated.<YYYY-MM-DD>.json`` (shared contract).
- The saved baseline has the shared shape ``{"sources": {source: {key: item}}}`` and a
  saved device item keeps ``name``, a saved disk item ``friendly_name``.
- The ``not_checked`` item for a device not compared names the device (its name or its
  id) in ``what`` or ``reason``.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import json
import shutil
import unittest
from datetime import timedelta

from .fakes import GIB, NOW, FakePowerShell, HealthTestCase, failure, ok, reliability

DISK_UID = "INVENTED-UNIQUE-ID-00000000000D15C"
ALPHA_UID = "INVENTED-UNIQUE-ID-0000000000ALPHA"

BRIDGE_ID = "PCI\\VEN_1AAA&DEV_0110\\INVENTEDBRIDGE0001"
READER_ID = "USB\\VID_1AAA&PID_0111\\INVENTEDREADER0002"
FINE_ID = "PCI\\VEN_1AAA&DEV_0112\\INVENTEDFINE0003"
TWIN_ID = "USB\\VID_1AAA&PID_0113\\INVENTEDTWIN0004"
KNOWN_ID = "PCI\\VEN_1AAA&DEV_0114\\INVENTEDKNOWN0005"

DISK_NAME = "Invented Disk Alpha"
BRIDGE = "Invented Failing Bridge"
READER = "Invented Failing Reader"

OS_VERSION = {
    "DisplayVersion": "24H2",
    "CurrentBuild": "26100",
    "UBR": 1234,
    "EditionID": "Professional",
}

BASELINE_FILE = "ush-health.elevated.json"

DISK_NOT_COMPARED = "disk not compared: no UniqueId"
DEVICE_NOT_COMPARED = "device not compared"


def disk_row(name=DISK_NAME, unique_id=DISK_UID, health="Healthy", device_id="0"):
    return {
        "DeviceId": device_id,
        "FriendlyName": name,
        "MediaType": "SSD",
        "BusType": "NVMe",
        "Size": 1024 * GIB,
        "HealthStatus": health,
        "OperationalStatus": "OK",
        "UniqueId": unique_id,
    }


def volume_row(free_gb, letter="C"):
    """A lettered volume whose free space rounds to ``free_gb`` (one decimal place)."""
    return {
        "DriveLetter": letter,
        "FileSystem": "NTFS",
        "Size": 476 * GIB,
        "SizeRemaining": round(free_gb * GIB),
        "HealthStatus": "Healthy",
    }


def device_row(name, instance_id, status="Error", problem="CM_PROB_FAILED_START"):
    return {"Name": name, "Class": "System", "Status": status, "Problem": problem,
            "InstanceId": instance_id}


def ok_device(name, instance_id):
    return device_row(name, instance_id, status="OK", problem="CM_PROB_NONE")


def protection(value):
    return ok([{"DriveLetter": "C", "BitLockerProtection": value}])


def counter_error(device_id="0"):
    failed = reliability(device_id)
    for key in ("Temperature", "Wear", "ReadErrorsTotal", "WriteErrorsTotal",
                "PowerOnHours"):
        failed[key] = None
    failed["Error"] = "Invented: the counter is not supported"
    return failed


def machine(**overrides):
    """The invented machine: one disk, volume C with 214.6 GB free, one failing device."""
    responses = {
        "physical_disks": ok([disk_row()]),
        "disk_reliability": ok([reliability("0", wear=3, read_errors=0, write_errors=0)]),
        "volumes": ok([volume_row(214.6)]),
        "encryption": protection(1),
        "devices": ok([device_row(BRIDGE, BRIDGE_ID), ok_device("Invented Fine Hub",
                                                                FINE_ID)]),
        "os_version": ok(OS_VERSION),
    }
    responses.update(overrides)
    return FakePowerShell(responses)


class TestHealthBaseline(HealthTestCase):
    # --- helpers ------------------------------------------------------------------------

    def run_health(self, data_dir, fake, now=NOW, extra=()):
        code, stdout, stderr = self.run_main(data_dir, fake, admin=True, now=now,
                                             extra=extra)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def changes(self, summary):
        changes = summary.get("changes")
        self.assertIsInstance(changes, list, summary)
        return changes

    def baseline_object(self, summary):
        value = summary.get("baseline")
        self.assertIsInstance(value, dict, summary)
        return value

    def comparison(self, summary):
        value = summary.get("comparison")
        self.assertIsInstance(value, dict, summary)
        return value

    def item_id(self, summary, section, field, value):
        items = summary.get(section)
        self.assertIsInstance(items, list, f"{section}: {items!r}")
        matches = [item for item in items if item.get(field) == value]
        self.assertEqual(len(matches), 1, f"{section} with {field} {value!r}: {items}")
        return matches[0].get("id")

    def saved_sources(self, data_dir):
        path = data_dir / "state" / BASELINE_FILE
        self.assertTrue(path.is_file(), f"{BASELINE_FILE} was not written")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data.get("sources"), dict, data)
        return data["sources"]

    def saved_values(self, data_dir, source, field):
        items = self.saved_sources(data_dir).get(source)
        self.assertIsInstance(items, dict, f"saved {source}: {items!r}")
        return sorted(str(item.get(field)) for item in items.values())

    def copy_of(self, data_dir, name):
        target = data_dir.parent / name
        shutil.copytree(data_dir, target)
        return target

    def map_numbers(self, data_dir, prefix):
        path = data_dir / "state" / "ush-health.ids.json"
        self.assertTrue(path.is_file(), "the id map was not written")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        keys = ((data.get("prefixes") or {}).get(prefix) or {}).get("keys") or {}
        return {record.get("n") for record in keys.values()}

    def number(self, item_id, prefix):
        self.assertRegex(str(item_id), rf"^{prefix}[0-9]+$")
        return int(item_id[len(prefix):])

    def entries_starting(self, summary, prefix):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return [entry for entry in items if str(entry.get("what")).startswith(prefix)]

    def names_entry(self, entries, *needles):
        """True when one of ``entries`` holds one of ``needles`` in what or reason."""
        for entry in entries:
            text = f"{entry.get('what')} {entry.get('reason')}"
            if any(needle and needle in text for needle in needles):
                return True
        return False

    def not_checked_texts(self, summary, data_dir):
        texts = []
        for entry in summary.get("not_checked") or []:
            dumped = json.dumps(entry, sort_keys=True)
            for form in (json.dumps(str(data_dir))[1:-1], str(data_dir)):
                dumped = dumped.replace(form, "<data dir>")
            texts.append(dumped)
        return sorted(texts)

    # --- K5 -----------------------------------------------------------------------------

    def test_changes_between_runs(self):
        with self.subTest("free space, a new failing device and disk health"):
            data_dir = self.data_dir()
            first = self.run_health(data_dir, machine(), now=NOW)
            self.assertEqual(self.baseline_object(first).get("status"), "none", first)
            self.assertEqual(self.changes(first), [])

            second = self.run_health(data_dir, machine(
                physical_disks=ok([disk_row(health="Warning")]),
                volumes=ok([volume_row(97.3)]),
                devices=ok([device_row(BRIDGE, BRIDGE_ID), device_row(READER, READER_ID),
                            ok_device("Invented Fine Hub", FINE_ID)]),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual(self.baseline_object(second).get("status"), "compared")
            changes = self.changes(second)
            self.assertEqual(len(changes), 3, changes)
            self.assertEqual([c.get("id") for c in changes], ["c1", "c2", "c3"], changes)
            self.assertEqual([c.get("source") for c in changes],
                             ["disks", "volumes", "devices"], changes)
            disk_change, volume_change, device_change = changes

            self.assertEqual(disk_change.get("kind"), "changed", disk_change)
            self.assertEqual(disk_change.get("item"),
                             self.item_id(second, "disks", "friendly_name", DISK_NAME))
            self.assertRegex(str(disk_change.get("item")), r"^k[0-9]+$")
            self.assertEqual(disk_change.get("name"), DISK_NAME, disk_change)
            self.assertEqual(disk_change.get("fields"),
                             {"health_status": {"before": "Healthy", "after": "Warning"}})

            self.assertEqual(volume_change.get("kind"), "changed", volume_change)
            self.assertEqual(volume_change.get("item"),
                             self.item_id(second, "volumes", "drive_letter", "C"))
            self.assertRegex(str(volume_change.get("item")), r"^v[0-9]+$")
            self.assertEqual(self.letter(volume_change.get("name")), "C", volume_change)
            self.assertEqual(volume_change.get("fields"),
                             {"free_gb": {"before": 214.6, "after": 97.3}})

            self.assertEqual(device_change.get("kind"), "added", device_change)
            self.assertEqual(device_change.get("item"),
                             self.item_id(second, "devices", "name", READER))
            self.assertRegex(str(device_change.get("item")), r"^p[0-9]+$")
            self.assertEqual(device_change.get("name"), READER, device_change)

        with self.subTest("disk counter error: reliability null gives no change"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                disk_reliability=ok([counter_error("0")]),
            ), now=NOW + timedelta(hours=1))
            self.assertIsNone(second["disks"][0].get("reliability"), second["disks"])
            self.assertEqual(self.comparison(second).get("disks"), "compared")
            for change in self.changes(second):
                for field in ("wear_percent", "read_errors_total", "write_errors_total"):
                    self.assertNotIn(field, change.get("fields") or {}, change)
            self.assertEqual(self.changes(second), [])

        with self.subTest("encryption not read: no volume change"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                encryption=failure("New-Object : Invented COM failure"),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual(self.comparison(second).get("volumes"), "compared")
            volume_changes = [c for c in self.changes(second)
                              if c.get("source") == "volumes"]
            self.assertEqual(volume_changes, [])

        with self.subTest("devices not read: not_read and no device change"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                devices=failure("Get-PnpDevice : Invented access denied"),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual(self.comparison(second).get("devices"), "not_read")
            device_changes = [c for c in self.changes(second)
                              if c.get("source") == "devices"]
            self.assertEqual(device_changes, [])

        with self.subTest("repeated and null instance_id: not compared"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                devices=ok([device_row(BRIDGE, BRIDGE_ID),
                            device_row("Invented Twin Camera A", TWIN_ID),
                            device_row("Invented Twin Camera B", TWIN_ID),
                            device_row("Invented Keyless Sensor", None)]),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual(self.comparison(second).get("devices"), "compared")
            device_changes = [c for c in self.changes(second)
                              if c.get("source") == "devices"]
            self.assertEqual(device_changes, [])
            entries = self.entries_starting(second, DEVICE_NOT_COMPARED)
            self.assertGreaterEqual(len(entries), 2, second["not_checked"])
            keyless_id = self.item_id(second, "devices", "name", "Invented Keyless Sensor")
            self.assertTrue(self.names_entry(entries, "Invented Keyless Sensor", keyless_id),
                            entries)
            twin_ids = [self.item_id(second, "devices", "name", name)
                        for name in ("Invented Twin Camera A", "Invented Twin Camera B")]
            self.assertTrue(self.names_entry(entries, "Invented Twin Camera A",
                                             "Invented Twin Camera B", *twin_ids), entries)
            self.assertEqual(self.saved_values(data_dir, "devices", "name"), [BRIDGE])

        with self.subTest("--compare-to 7d over three runs"):
            first_at = NOW - timedelta(days=10)
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=first_at)
            self.run_health(data_dir, machine(
                volumes=ok([volume_row(97.3)]),
                devices=ok([device_row(BRIDGE, BRIDGE_ID), device_row(READER, READER_ID)]),
            ), now=NOW - timedelta(days=2))
            week_dir = self.copy_of(data_dir, "compare-7d")
            third = self.run_health(week_dir, machine(
                volumes=ok([volume_row(97.3)]),
                devices=failure("Get-PnpDevice : Invented access denied"),
            ), now=NOW, extra=["--compare-to", "7d"])
            info = self.baseline_object(third)
            self.assertEqual(info.get("status"), "compared", info)
            self.assertEqual(info.get("reference"), "7d", info)
            self.assertEqual(info.get("reference_file"),
                             f"ush-health.elevated.{first_at.date().isoformat()}.json", info)
            self.assertEqual(info.get("age_days"), 10.0, info)
            self.assertEqual(self.comparison(third).get("devices"), "not_read")
            changes = self.changes(third)
            self.assertEqual(len(changes), 1, changes)
            self.assertEqual(changes[0].get("source"), "volumes", changes)
            self.assertEqual(changes[0].get("kind"), "changed", changes)
            self.assertEqual(changes[0].get("fields"),
                             {"free_gb": {"before": 214.6, "after": 97.3}})
            # devices were not read in the third run: the saved baseline keeps the
            # items of the second run, not those of the ten-day-old copy.
            self.assertEqual(self.saved_values(week_dir, "devices", "name"),
                             sorted([BRIDGE, READER]))

        with self.subTest("protection 1, then unknown, then 0"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(encryption=protection(1)), now=NOW)
            middle = self.run_health(data_dir, machine(
                encryption=failure("New-Object : Invented COM failure"),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual([c for c in self.changes(middle)
                              if c.get("source") == "volumes"], [])
            last = self.run_health(data_dir, machine(encryption=protection(0)),
                                   now=NOW + timedelta(hours=2))
            changes = self.changes(last)
            self.assertEqual(len(changes), 1, changes)
            self.assertEqual(changes[0].get("source"), "volumes", changes)
            self.assertEqual(changes[0].get("kind"), "changed", changes)
            self.assertEqual(changes[0].get("fields"),
                             {"protection": {"before": 1, "after": 0}})

        with self.subTest("clean data: two identical runs"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(), now=NOW + timedelta(hours=1))
            self.assertEqual(self.baseline_object(second).get("status"), "compared")
            self.assertEqual(self.changes(second), [])

    # --- loc-qa 110: the os source (plan 110, M3 table and result shape) ----------------

    def test_os_version_change(self):
        with self.subTest("a new UBR is one os change with item null and name os"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                os_version=ok(dict(OS_VERSION, UBR=1300)),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual(self.comparison(second).get("os"), "compared")
            changes = self.changes(second)
            self.assertEqual(len(changes), 1, changes)
            self.assertEqual(changes[0].get("id"), "c1", changes)
            self.assertEqual(changes[0].get("source"), "os", changes)
            self.assertEqual(changes[0].get("kind"), "changed", changes)
            self.assertIsNone(changes[0].get("item"), changes)
            self.assertEqual(changes[0].get("name"), "os", changes)
            self.assertEqual(changes[0].get("fields"),
                             {"ubr": {"before": 1234, "after": 1300}})

        with self.subTest("os version not read: not_read and no os change"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                os_version=failure("Get-ItemProperty : Invented access denied"),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual(self.comparison(second).get("os"), "not_read")
            self.assertEqual([c for c in self.changes(second)
                              if c.get("source") == "os"], [])
            third = self.run_health(data_dir, machine(), now=NOW + timedelta(hours=2))
            self.assertEqual(self.changes(third), [])

    # --- loc/inbox/123: a blank key is no key -------------------------------------------

    def blank_machine(self, disk_keys, device_keys):
        return machine(
            physical_disks=ok([disk_row(DISK_NAME, ALPHA_UID, device_id="0"),
                               disk_row("Invented Disk Blank One", disk_keys[0],
                                        device_id="1"),
                               disk_row("Invented Disk Blank Two", disk_keys[1],
                                        device_id="2")]),
            disk_reliability=ok([reliability("0"), reliability("1"), reliability("2")]),
            devices=ok([device_row("Invented Failing Known", KNOWN_ID),
                        device_row("Invented Failing Blank One", device_keys[0]),
                        device_row("Invented Failing Blank Two", device_keys[1])]),
        )

    def test_blank_keys_are_no_key(self):
        null_dir = self.data_dir()
        null_run = self.run_health(null_dir, self.blank_machine((None, None), (None, None)),
                                   now=NOW)
        blank_dir = self.data_dir()
        blank_run = self.run_health(blank_dir, self.blank_machine(("", "   "), ("", "  ")),
                                    now=NOW)

        # One-time ids, not kept in the id map.
        disks = {name: self.item_id(blank_run, "disks", "friendly_name", name)
                 for name in (DISK_NAME, "Invented Disk Blank One",
                              "Invented Disk Blank Two")}
        kept_disks = self.map_numbers(blank_dir, "k")
        self.assertIn(self.number(disks[DISK_NAME], "k"), kept_disks)
        blank_disk_ids = [disks["Invented Disk Blank One"], disks["Invented Disk Blank Two"]]
        self.assertNotEqual(blank_disk_ids[0], blank_disk_ids[1])
        for item_id in blank_disk_ids:
            self.assertNotIn(self.number(item_id, "k"), kept_disks)

        devices = {name: self.item_id(blank_run, "devices", "name", name)
                   for name in ("Invented Failing Known", "Invented Failing Blank One",
                                "Invented Failing Blank Two")}
        kept_devices = self.map_numbers(blank_dir, "p")
        self.assertIn(self.number(devices["Invented Failing Known"], "p"), kept_devices)
        blank_device_ids = [devices["Invented Failing Blank One"],
                            devices["Invented Failing Blank Two"]]
        self.assertNotEqual(blank_device_ids[0], blank_device_ids[1])
        for item_id in blank_device_ids:
            self.assertNotIn(self.number(item_id, "p"), kept_devices)

        # Named as items without a key, as for null.
        notes = [entry for entry in blank_run["not_checked"]
                 if entry.get("what") == "stable ids k"]
        self.assertEqual(len(notes), 1, blank_run["not_checked"])
        for item_id in blank_disk_ids:
            self.assertIn(item_id, str(notes[0].get("reason")))

        disk_entries = [entry for entry in blank_run["not_checked"]
                        if entry.get("what") == DISK_NOT_COMPARED]
        self.assertEqual(len(disk_entries), 2, blank_run["not_checked"])
        reasons = " ".join(str(entry.get("reason")) for entry in disk_entries)
        self.assertIn("Invented Disk Blank One", reasons)
        self.assertIn("Invented Disk Blank Two", reasons)

        device_entries = self.entries_starting(blank_run, DEVICE_NOT_COMPARED)
        for name in ("Invented Failing Blank One", "Invented Failing Blank Two"):
            self.assertTrue(self.names_entry(device_entries, name, devices[name]),
                            device_entries)
        self.assertFalse(self.names_entry(device_entries, "Invented Failing Known"),
                         device_entries)

        # Not in the baseline.
        self.assertEqual(self.saved_values(blank_dir, "disks", "friendly_name"), [DISK_NAME])
        self.assertEqual(self.saved_values(blank_dir, "devices", "name"),
                         ["Invented Failing Known"])

        # Exactly as for null: the same not_checked items and the same ids.
        self.assertEqual(self.not_checked_texts(blank_run, blank_dir),
                         self.not_checked_texts(null_run, null_dir))
        self.assertEqual([d.get("id") for d in blank_run["disks"]],
                         [d.get("id") for d in null_run["disks"]])
        self.assertEqual([d.get("id") for d in blank_run["devices"]],
                         [d.get("id") for d in null_run["devices"]])

        # Clean data: a second identical run has no changes; the blank items are
        # neither added nor removed.
        second = self.run_health(blank_dir, self.blank_machine(("", "   "), ("", "  ")),
                                 now=NOW + timedelta(hours=1))
        self.assertEqual(self.baseline_object(second).get("status"), "compared")
        self.assertEqual(self.changes(second), [])
        kept_disks = self.map_numbers(blank_dir, "k")
        for name in ("Invented Disk Blank One", "Invented Disk Blank Two"):
            item_id = self.item_id(second, "disks", "friendly_name", name)
            self.assertNotIn(self.number(item_id, "k"), kept_disks)

    # --- code review M3 round 1: a key left out never gives removed ---------------------

    def test_left_out_keys_keep_saved_items(self):
        with self.subTest("repeated UniqueId: no disk change, the saved disk stays"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            twins = machine(
                physical_disks=ok([disk_row(DISK_NAME, DISK_UID, device_id="0"),
                                   disk_row("Invented Disk Twin", DISK_UID,
                                            device_id="1")]),
                disk_reliability=ok([reliability("0"), reliability("1")]),
            )
            second = self.run_health(data_dir, twins, now=NOW + timedelta(hours=1))
            self.assertEqual(self.comparison(second).get("disks"), "compared")
            self.assertEqual([c for c in self.changes(second)
                              if c.get("source") == "disks"], [])
            self.assertEqual(self.saved_values(data_dir, "disks", "friendly_name"),
                             [DISK_NAME])
            third = self.run_health(data_dir, machine(), now=NOW + timedelta(hours=2))
            self.assertEqual(self.changes(third), [])

        with self.subTest("blank InstanceId: no device removed, the saved device stays"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                devices=ok([device_row(BRIDGE, "  "), device_row(READER, READER_ID)]),
            ), now=NOW + timedelta(hours=1))
            self.assertEqual(self.comparison(second).get("devices"), "compared")
            device_changes = [c for c in self.changes(second)
                              if c.get("source") == "devices"]
            self.assertEqual([c.get("kind") for c in device_changes], ["added"],
                             device_changes)
            self.assertEqual(device_changes[0].get("name"), READER, device_changes)
            entries = self.entries_starting(second, "device not compared: no InstanceId")
            self.assertEqual(len(entries), 1, second["not_checked"])
            self.assertIn("removed devices were not checked", entries[0].get("reason"))
            self.assertEqual(self.saved_values(data_dir, "devices", "name"),
                             sorted([BRIDGE, READER]))

        with self.subTest("clean data: a gone keyed device is still removed"):
            data_dir = self.data_dir()
            self.run_health(data_dir, machine(), now=NOW)
            second = self.run_health(data_dir, machine(
                devices=ok([ok_device("Invented Fine Hub", FINE_ID)]),
            ), now=NOW + timedelta(hours=1))
            changes = self.changes(second)
            self.assertEqual(len(changes), 1, changes)
            self.assertEqual(changes[0].get("source"), "devices", changes)
            self.assertEqual(changes[0].get("kind"), "removed", changes)
            self.assertEqual(changes[0].get("name"), BRIDGE, changes)
            self.assertEqual(self.entries_starting(second, DEVICE_NOT_COMPARED), [])


if __name__ == "__main__":
    unittest.main()

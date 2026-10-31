"""Stable disk and device ids of ush-health across runs (plan 108, M4, K7).

Interface under test (from the plan; the general one is in ``fakes.py``):

- Disks ``k``, volumes ``v`` and devices ``p`` take their numbers from a map kept in
  ``<data dir>/state/ush-health.ids.json`` with the shape
  ``{"version": 1, "skill": "ush-health", "prefixes": {"k": {"next": N, "keys":
  {"<key>": {"n": 1, "seen": "YYYY-MM-DD"}}}}}``.
- ``PHYSICAL_DISKS_BODY`` also reads ``UniqueId``; a disk gets ``unique_id``, kept only
  in the detail file. The disk key is built from ``unique_id`` (not from the
  enumeration number ``DeviceId``); a disk without ``UniqueId`` gets a one-time number.
- The device key is built from ``instance_id``; a device without one gets a one-time
  number; two device rows with the same ``instance_id`` give a ``not_checked`` entry
  and exit code 0. Update failures ``u`` stay positional.
- ``unique_id`` is in the ``path_keys`` of ``skills/ush-health/data/report-profile.json``.

Assumptions added by these tests beyond the plan text:

- A disk row without ``UniqueId`` carries ``"UniqueId": null`` (the job's ``S`` helper
  gives null for an empty value).
- The disk reliability counter is joined by ``DeviceId`` within one run, as today.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import json
import unittest
from datetime import timedelta

from tests.skill_loader import REPO_ROOT

from .fakes import GIB, NOW, FakePowerShell, HealthTestCase, ok, reliability

PROFILE = REPO_ROOT / "skills" / "ush-health" / "data" / "report-profile.json"

ALPHA_UID = "INVENTED-UNIQUE-ID-0000000000AAAA"
BETA_UID = "INVENTED-UNIQUE-ID-0000000000BBBB"

FIRST_DEVICE = "PCI\\VEN_1AAA&DEV_0001\\INVENTEDDEVICE0001"
SECOND_DEVICE = "USB\\VID_1AAA&PID_0002\\INVENTEDDEVICE0002"


def disk_row(device_id, name, unique_id, size=512 * GIB):
    return {
        "DeviceId": device_id,
        "FriendlyName": name,
        "MediaType": "SSD",
        "BusType": "NVMe",
        "Size": size,
        "HealthStatus": "Healthy",
        "OperationalStatus": "OK",
        "UniqueId": unique_id,
    }


def device_row(name, instance_id, status="Error", problem="CM_PROB_FAILED_START"):
    return {"Name": name, "Class": "System", "Status": status, "Problem": problem,
            "InstanceId": instance_id}


def ok_device(name, instance_id):
    return device_row(name, instance_id, status="OK", problem="CM_PROB_NONE")


class TestStableIds(HealthTestCase):
    # --- helpers ------------------------------------------------------------------------

    def collect_in(self, data_dir, responses, now):
        code, stdout, stderr = self.run_main(data_dir, FakePowerShell(responses), now=now)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def detail(self, summary):
        with open(summary["detail_file"], encoding="utf-8-sig") as handle:
            data = json.load(handle)
        self.assertIsInstance(data, dict)
        return data

    def items(self, data, name):
        items = data.get(name)
        self.assertIsInstance(items, list, f"{name}: {items!r}")
        return items

    def map_numbers(self, data_dir, prefix):
        """The numbers kept in the id map for ``prefix``."""
        path = data_dir / "state" / "ush-health.ids.json"
        self.assertTrue(path.is_file(), "the id map was not written")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        keys = ((data.get("prefixes") or {}).get(prefix) or {}).get("keys") or {}
        return {record.get("n") for record in keys.values()}

    def number(self, item_id, prefix):
        self.assertRegex(str(item_id), rf"^{prefix}[0-9]+$")
        return int(item_id[len(prefix):])

    def by_field(self, items, field):
        result = {}
        for item in items:
            self.assertNotIn(item.get(field), result, f"two items with {field} "
                                                      f"{item.get(field)!r}")
            result[item.get(field)] = item
        return result

    def not_checked_texts(self, summary, data_dir):
        texts = set()
        for entry in self.not_checked_list(summary):
            dumped = json.dumps(entry, sort_keys=True)
            for form in (json.dumps(str(data_dir))[1:-1], str(data_dir)):
                dumped = dumped.replace(form, "<data dir>")
            texts.add(dumped)
        return texts

    def not_checked_list(self, summary):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return items

    # --- K7: disk and device ids survive -------------------------------------------------

    def test_disk_and_device_ids_survive(self):
        self.assertIn("UniqueId", self.health.PHYSICAL_DISKS_BODY)
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertIn("unique_id", profile.get("path_keys") or [])

        data_dir = self.data_dir()
        first = self.collect_in(data_dir, {
            "physical_disks": ok([disk_row("0", "Invented Disk Alpha", ALPHA_UID),
                                  disk_row("1", "Invented Disk Beta", BETA_UID)]),
            "disk_reliability": ok([reliability("0"), reliability("1", hours=3400)]),
            "devices": ok([device_row("Invented Failing Bridge", FIRST_DEVICE),
                           device_row("Invented Failing Reader", SECOND_DEVICE),
                           ok_device("Invented Fine Controller",
                                     "PCI\\VEN_1AAA&DEV_0003\\INVENTEDDEVICE0003")]),
        }, now=NOW)

        first_disks = self.by_field(self.items(first, "disks"), "friendly_name")
        self.assertEqual(set(first_disks), {"Invented Disk Alpha", "Invented Disk Beta"})
        for item in self.items(first, "disks"):
            self.assertNotIn("unique_id", item, item)
        detail_disks = self.by_field(self.items(self.detail(first), "disks"),
                                     "friendly_name")
        self.assertEqual(detail_disks["Invented Disk Beta"].get("unique_id"), BETA_UID)
        first_devices = self.by_field(self.items(first, "devices"), "name")
        self.assertEqual(set(first_devices),
                         {"Invented Failing Bridge", "Invented Failing Reader"})

        # The first disk is gone and the second is now enumerated as "0"; the first
        # failing device is gone too: positional numbers would shift.
        second = self.collect_in(data_dir, {
            "physical_disks": ok([disk_row("0", "Invented Disk Beta", BETA_UID)]),
            "disk_reliability": ok([reliability("0", hours=3401)]),
            "devices": ok([device_row("Invented Failing Reader", SECOND_DEVICE)]),
        }, now=NOW + timedelta(hours=1))

        second_disks = self.items(second, "disks")
        self.assertEqual([d.get("friendly_name") for d in second_disks],
                         ["Invented Disk Beta"])
        self.assertEqual(second_disks[0].get("id"),
                         first_disks["Invented Disk Beta"].get("id"))
        self.assertNotIn("unique_id", second_disks[0], second_disks[0])

        second_devices = self.items(second, "devices")
        self.assertEqual([d.get("name") for d in second_devices],
                         ["Invented Failing Reader"])
        self.assertEqual(second_devices[0].get("id"),
                         first_devices["Invented Failing Reader"].get("id"))

    def test_disk_without_unique_id_gets_one_time_number(self):
        data_dir = self.data_dir()
        summary = self.collect_in(data_dir, {
            "physical_disks": ok([disk_row("0", "Invented Disk Alpha", ALPHA_UID),
                                  disk_row("1", "Invented Disk Nameless", None)]),
            "disk_reliability": ok([reliability("0"), reliability("1")]),
        }, now=NOW)
        disks = self.by_field(self.items(summary, "disks"), "friendly_name")
        kept = self.map_numbers(data_dir, "k")
        self.assertIn(self.number(disks["Invented Disk Alpha"].get("id"), "k"), kept)
        self.assertNotIn(self.number(disks["Invented Disk Nameless"].get("id"), "k"), kept)
        # The one-time id is named in not_checked, so the report does not match it
        # with an earlier run; the disk with a key is not named.
        notes = [entry for entry in summary["not_checked"]
                 if entry.get("what") == "stable ids k"]
        self.assertEqual(len(notes), 1, summary["not_checked"])
        self.assertIn(disks["Invented Disk Nameless"]["id"], notes[0]["reason"])
        self.assertNotIn(disks["Invented Disk Alpha"]["id"] + ",", notes[0]["reason"])
        self.assertNotIn(ALPHA_UID, json.dumps(summary["not_checked"]))

    def test_devices_without_instance_id_get_one_time_numbers(self):
        data_dir = self.data_dir()
        summary = self.collect_in(data_dir, {
            "devices": ok([device_row("Invented Failing One", None),
                           device_row("Invented Failing Two", None),
                           device_row("Invented Failing Known", FIRST_DEVICE)]),
        }, now=NOW)
        devices = self.by_field(self.items(summary, "devices"), "name")
        one = self.number(devices["Invented Failing One"].get("id"), "p")
        two = self.number(devices["Invented Failing Two"].get("id"), "p")
        self.assertNotEqual(one, two)
        kept = self.map_numbers(data_dir, "p")
        self.assertIn(self.number(devices["Invented Failing Known"].get("id"), "p"), kept)
        self.assertNotIn(one, kept)
        self.assertNotIn(two, kept)

    def test_repeated_instance_id_noted(self):
        clean_dir = self.data_dir()
        clean = self.collect_in(clean_dir, {
            "devices": ok([device_row("Invented Failing Twin A", FIRST_DEVICE),
                           device_row("Invented Failing Twin B", SECOND_DEVICE)]),
        }, now=NOW)

        twin_dir = self.data_dir()
        code, stdout, stderr = self.run_main(twin_dir, FakePowerShell({
            "devices": ok([device_row("Invented Failing Twin A", FIRST_DEVICE),
                           device_row("Invented Failing Twin B", FIRST_DEVICE)]),
        }), now=NOW)
        self.assertEqual(code, 0, stderr[:300])
        twins = self.parse(stdout)

        known = self.not_checked_texts(clean, clean_dir)
        extra = self.not_checked_texts(twins, twin_dir) - known
        self.assertTrue(extra, f"no not_checked entry about the repeated instance_id: "
                               f"{self.not_checked_list(twins)}")
        ids = [d.get("id") for d in self.items(twins, "devices")]
        self.assertEqual(len(ids), 2, ids)
        self.assertEqual(len(set(ids)), 2, ids)


if __name__ == "__main__":
    unittest.main()

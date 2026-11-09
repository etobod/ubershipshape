"""Accepted findings: skills/ush-common/scripts/accepted.py (plan 060, M1, criteria K1-K4).

Interface under test (from the plan):

- ``load(data_dir) -> {status, reason, path, entries}``; ``status`` is ``none`` (no file),
  ``read`` or ``unreadable``; ``path`` is ``<data_dir>/state/accepted.json`` as a string;
  it never raises on a bad file.
- ``accepted.py --accept "<skill> <id>" --detail-file <runall detail> --data-dir <dir>``
  finds the item through the child summary in the runall detail file (``children[]``
  ``summary.detail_file``) and that child's own detail file, adds ``{kind, key, facts}``
  (an entry with the same key is replaced, never duplicated), writes
  ``state/accepted.json`` and prints ``{ok, key, kind, path}`` as JSON on stdout. A refused
  accept prints ``ok`` ``false`` with a ``reason`` and writes nothing.
- Kinds (``skills/ush-common/data/accepted-kinds.json``): ``update`` (ush-health
  ``update_failures``, ids ``u``), ``autostart`` (ush-inventory ``autostart``, ids ``s``),
  ``event_group`` (ush-events ``groups``, ids ``g``), ``firewall_rule`` (ush-inventory
  ``additions`` with ``kind`` ``firewall_rule``, ids ``x``).

Assumptions added by these tests beyond the plan text:

- An ``update`` key is the list ``[title, hresult]`` (the plan spells the event group key
  as the list ``[log, provider, event_id]``); an autostart and a firewall rule key is the
  inventory ``key`` string.
- The written file holds ``schema_version`` at its top level (as ``decisions.json``) and
  each entry is an object with ``kind`` and ``key``; K1 builds its valid file through
  ``--accept`` instead of guessing the rest of the shape.
- The shape of ``facts`` is not pinned: ``last`` and ``sha256`` are looked up anywhere
  inside an entry's ``facts``.
- The path printed by ``--accept`` is ``<data dir>/state/accepted.json``.

The script is run as a child process on invented detail files in a temporary directory;
nothing on the machine is read. Every value is invented (Contoso, Fabrikam).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script, script_path

ACCEPTED_SCRIPT = script_path("ush-common", "accepted")
GENERATED_AT = "2026-11-05T10:15:00Z"

U2_TITLE = "2026-10 Security Update for Invented Windows (KB5099002) (26100.4100)"
U2_HRESULT = "0x80070002"
U2_LAST = "2026-10-22T03:15:00Z"
U2_LATER_LAST = "2026-11-04T02:40:00Z"

TASK_KEY = "task:\\Fabrikam\\FabrikamUpdaterLogon"
TASK_SHA_MAIN = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
TASK_SHA_HELPER = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
RUN_SHA = "5e5e5e5e1a1a1a1a2b2b2b2b3c3c3c3c4d4d4d4d6f6f6f6f7a7a7a7a8b8b8b8b"

RULE_KEY = "firewall:local:{6A1C0E52-1111-4D2B-9C3A-0F0E0D0C0B0A}"
EVENT_KEY = ["Application", "Contoso-Agent", 7001]


def source(name, status="read"):
    return {"name": name, "status": status, "reason": None}


def update_group(group_id, title, hresult, last, result="Failed", count=2):
    return {"id": group_id, "title": title, "result": result, "hresult": hresult,
            "count": count, "first": "2026-10-01T03:00:00Z", "last": last,
            "superseded_by": None}


def health_detail(u2_last):
    return {
        "schema_version": 1, "skill": "ush-health", "generated_at": GENERATED_AT,
        "elevated": False,
        "sources": [source("physical_disks"), source("update_history")],
        "comparison": {"disks": "compared", "volumes": "compared", "devices": "compared",
                       "os": "compared"},
        "disks": [{"id": "k1", "friendly_name": "Contoso NVMe 512", "media_type": "SSD",
                   "bus_type": "NVMe", "size_gb": 476.9, "health_status": "Healthy",
                   "operational_status": "OK", "reliability": None, "device_id": "0",
                   "unique_id": "INVENTED-UNIQUE-0001"}],
        "volumes": [], "devices": [],
        "update_failures": [
            update_group("u1", "Contoso Driver Update - Display - 31.0.101.5000",
                         "0x80073701", "2026-10-30T09:00:00Z", count=1),
            update_group("u2", U2_TITLE, U2_HRESULT, u2_last),
            update_group("u3", U2_TITLE, "0x800F0922", "2026-09-12T04:00:00Z",
                         result="Aborted", count=1),
        ],
        "pending_updates": [], "changes": [],
    }


def health_summary(detail_file):
    return {
        "schema_version": 1, "skill": "ush-health", "generated_at": GENERATED_AT,
        "sources": [source("physical_disks"), source("update_history")],
        "not_checked": [], "summary_file": str(detail_file).replace(".detail.", ".summary."),
        "detail_file": str(detail_file), "truncated": 0, "elevated": False,
        "updates": {"history_count": 40, "by_result": {"Succeeded": 37, "Failed": 2,
                                                       "Aborted": 1},
                    "failures": [], "superseded": 0},
    }


def fact(path, signer, sha256, company=None):
    return {"path": path, "expanded_path": path, "exists": True,
            "signature_status": "Valid", "signer": signer,
            "company": company or signer, "program": None, "sha256": sha256}


def inventory_detail():
    task_main = "C:\\Program Files\\Fabrikam\\Updater\\fupdate.exe"
    task_helper = "C:\\Program Files\\Fabrikam\\Updater\\fhelper.exe"
    run_target = "C:\\Program Files\\Contoso\\Tray\\ctray.exe"
    return {
        "schema_version": 1, "skill": "ush-inventory", "generated_at": GENERATED_AT,
        "elevated": False,
        "sources": [source("win32_programs"), source("run_keys"),
                    source("scheduled_tasks"), source("file_facts"),
                    source("firewall_rules"), source("root_certificates")],
        "comparison": {},
        "programs": [{"id": "a1", "key": "win32:hklm64:ContosoTray",
                      "source": "win32_programs", "own": False, "name": "Contoso Tray",
                      "version": "4.2.0", "publisher": "Contoso Ltd.",
                      "install_date": "2026-03-14",
                      "install_location": "C:\\Program Files\\Contoso\\Tray",
                      "scope": "machine", "system_component": False}],
        "autostart": [
            {"id": "s1", "key": "run:hkcu\\Run:ContosoTray", "source": "run_keys",
             "kind": "run",
             "location": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
             "name": "ContosoTray", "command": '"' + run_target + '" /minimized',
             "value_kind": "String", "enabled": True, "approved": "not_set",
             "approved_byte": None, "approved_raw": None, "targets": [run_target],
             "facts": [fact(run_target, "Contoso Ltd.", RUN_SHA)],
             "facts_from_baseline": False, "own": False, "unread_fields": []},
            {"id": "s3", "key": TASK_KEY, "source": "scheduled_tasks", "kind": "task",
             "location": "\\Fabrikam\\", "name": "FabrikamUpdaterLogon",
             "command": '"' + task_main + '" /logon; "' + task_helper + '" /check',
             "enabled": True, "state": "Ready", "targets": [task_main, task_helper],
             "facts": [fact(task_main, "Fabrikam Inc.", TASK_SHA_MAIN),
                       fact(task_helper, "Fabrikam Inc.", TASK_SHA_HELPER)],
             "facts_from_baseline": False, "own": False, "unread_fields": []},
        ],
        "components": [], "drivers": [], "driver_packages": [],
        "additions": [
            {"id": "x2", "key": RULE_KEY, "kind": "firewall_rule",
             "source": "firewall_rules", "own": False, "store": "local",
             "action": "Allow", "dir": "In", "active": "TRUE", "lport": "8080",
             "rport": None, "app": "C:\\Program Files\\Fabrikam\\Sync\\fsync.exe",
             "svc": None, "name": "Fabrikam Sync", "profile": "Private",
             "embed_ctxt": None, "protocol": 6, "protocol_name": "TCP", "lport2": None,
             "version": "v2.33", "app_exists": True},
            {"id": "x4", "key": "cert:machine_root:0A1B2C3D4E5F60718293A4B5C6D7E8F901234567",
             "kind": "root_certificate", "source": "root_certificates", "own": False,
             "store": "machine_root", "thumbprint": "0A1B2C3D4E5F60718293A4B5C6D7E8F901234567",
             "subject": "CN=Contoso Invented Root", "issuer": "CN=Contoso Invented Root",
             "not_before": "2025-01-01", "not_after": "2035-01-01", "self_signed": True,
             "in_authroot": False, "serial": "1F2E3D"},
        ],
        "leftovers": [], "vendor_folders": [], "changes": [],
    }


def inventory_summary(detail_file):
    return {
        "schema_version": 1, "skill": "ush-inventory", "generated_at": GENERATED_AT,
        "sources": inventory_detail()["sources"], "not_checked": [],
        "summary_file": str(detail_file).replace(".detail.", ".summary."),
        "detail_file": str(detail_file), "truncated": 0, "elevated": False,
    }


def events_detail():
    return {
        "schema_version": 1, "skill": "ush-events", "generated_at": GENERATED_AT,
        "window": {"start": "2026-10-22T10:15:00Z", "end": GENERATED_AT, "days": 14},
        "sources": [source("System pass A"), source("Application pass A")],
        "groups": [
            {"id": "g4", "provider": "Contoso-Agent", "event_id": 7001, "level": 2,
             "log": "Application", "count": 12, "first": "2026-10-23T08:00:00Z",
             "last": "2026-11-04T19:30:00Z", "sample": "Invented agent error.",
             "first_half": 5, "second_half": 7, "trend": "stable"},
            {"id": "g7", "provider": "Fabrikam-Service", "event_id": 12, "level": 3,
             "log": "System", "count": 3, "first": "2026-10-25T08:00:00Z",
             "last": "2026-11-01T08:00:00Z", "sample": "Invented service warning.",
             "first_half": 1, "second_half": 2, "trend": "too_few"},
        ],
        "noise": [], "listed": {"groups": ["g4", "g7"], "noise": []},
    }


def events_summary(detail_file):
    return {
        "schema_version": 1, "skill": "ush-events", "generated_at": GENERATED_AT,
        "sources": events_detail()["sources"], "not_checked": [],
        "summary_file": str(detail_file).replace(".detail.", ".summary."),
        "detail_file": str(detail_file), "truncated": 0,
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def make_pass(data_dir, stamp="20261105-101500", u2_last=U2_LAST,
              health_detail_missing=False):
    """Write invented child detail files and a runall detail file; return its path."""
    work = data_dir / "work"
    health_file = work / f"health-{stamp}.detail.json"
    events_file = work / f"events-{stamp}.detail.json"
    inventory_file = work / f"inventory-{stamp}.detail.json"
    if not health_detail_missing:
        write_json(health_file, health_detail(u2_last))
    write_json(events_file, events_detail())
    write_json(inventory_file, inventory_detail())

    def child(child_id, skill, summary):
        return {"id": child_id, "skill": skill, "status": "ok", "summary": summary}

    runall_file = work / f"runall-{stamp}.detail.json"
    return write_json(runall_file, {
        "schema_version": 1, "skill": "ush-runall", "generated_at": GENERATED_AT,
        "summary_file": str(work / f"runall-{stamp}.summary.json"),
        "children": [
            child("h1", "ush-health", health_summary(health_file)),
            child("h2", "ush-events", events_summary(events_file)),
            {"id": "h3", "skill": "ush-settings", "status": "failed", "summary": None},
            child("h4", "ush-inventory", inventory_summary(inventory_file)),
        ],
        "firewall_ports": [], "firewall_ports_counts": None, "network_categories": None,
        "driver_update_links": None, "link_counts": None, "decisions": [],
    })


def values_of(data, field):
    """Every value of ``field`` anywhere inside ``data``."""
    found = []
    if isinstance(data, dict):
        for name, value in data.items():
            if name == field:
                found.append(value)
            found.extend(values_of(value, field))
    elif isinstance(data, list):
        for value in data:
            found.extend(values_of(value, field))
    return found


def entry_objects(data):
    """The entry objects (with ``kind`` and ``key``) anywhere inside a written file."""
    found = []
    if isinstance(data, dict):
        if "kind" in data and "key" in data:
            return [data]
        for value in data.values():
            found.extend(entry_objects(value))
    elif isinstance(data, list):
        for value in data:
            found.extend(entry_objects(value))
    return found


class AcceptedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.accepted = load_script("ush-common", "accepted")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    @staticmethod
    def accepted_path(data_dir):
        return data_dir / "state" / "accepted.json"

    def run_accept(self, data_dir, target, detail_file):
        env = dict(os.environ)
        env.pop("USH_DATA_DIR", None)
        env["PYTHONIOENCODING"] = "utf-8"
        done = subprocess.run(
            [sys.executable, "-B", str(ACCEPTED_SCRIPT), "--accept", target,
             "--detail-file", str(detail_file), "--data-dir", str(data_dir)],
            capture_output=True, text=True, check=False, encoding="utf-8", env=env, timeout=120)
        try:
            result = json.loads(done.stdout)
        except ValueError:
            self.fail(f"stdout is not JSON: {done.stdout!r}; stderr: {done.stderr!r}")
        self.assertIsInstance(result, dict, done.stdout)
        return result

    def accept_ok(self, data_dir, target, detail_file):
        result = self.run_accept(data_dir, target, detail_file)
        self.assertIs(result.get("ok"), True, result)
        self.assertEqual(result.get("path"), str(self.accepted_path(data_dir)), result)
        return result

    def entries(self, data_dir):
        loaded = self.accepted.load(data_dir)
        self.assertEqual(loaded.get("status"), "read", loaded)
        entries = loaded.get("entries")
        self.assertIsInstance(entries, list, loaded)
        return entries


class TestLoad(AcceptedTestCase):
    def assert_unreadable(self, data_dir):
        result = self.accepted.load(data_dir)
        self.assertIsInstance(result, dict, result)
        self.assertEqual(result.get("status"), "unreadable", result)
        self.assertEqual(result.get("path"), str(self.accepted_path(data_dir)), result)
        self.assertFalse(result.get("entries"), result)
        reason = result.get("reason")
        self.assertIsInstance(reason, str, result)
        self.assertTrue(reason.strip(), result)

    def valid_file(self):
        data_dir = self.data_dir()
        self.accept_ok(data_dir, "ush-health u2", make_pass(data_dir))
        path = self.accepted_path(data_dir)
        self.assertTrue(path.is_file(), path)
        return data_dir, path, json.loads(path.read_text(encoding="utf-8"))

    def test_load_states(self):
        with self.subTest(case="missing file"):
            data_dir = self.data_dir()
            result = self.accepted.load(data_dir)
            self.assertIsInstance(result, dict, result)
            self.assertEqual(result.get("status"), "none", result)
            self.assertEqual(result.get("entries"), [], result)
            self.assertIsNone(result.get("reason"), result)
            path = result.get("path")
            self.assertEqual(path, str(self.accepted_path(data_dir)), result)
            self.assertTrue(Path(path).is_absolute(), path)

        with self.subTest(case="valid file"):
            data_dir, path, _ = self.valid_file()
            result = self.accepted.load(data_dir)
            self.assertEqual(result.get("status"), "read", result)
            self.assertIsNone(result.get("reason"), result)
            self.assertEqual(result.get("path"), str(path), result)
            entries = result.get("entries")
            self.assertIsInstance(entries, list, result)
            self.assertEqual(len(entries), 1, result)
            self.assertEqual(entries[0].get("kind"), "update", result)
            self.assertEqual(entries[0].get("key"), [U2_TITLE, U2_HRESULT], result)

        with self.subTest(case="bad JSON"):
            data_dir = self.data_dir()
            path = self.accepted_path(data_dir)
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version": 1, "entries": [', encoding="utf-8")
            self.assert_unreadable(data_dir)

        with self.subTest(case="wrong schema version"):
            data_dir, path, data = self.valid_file()
            self.assertIn("schema_version", data, data)
            data["schema_version"] = 999
            write_json(path, data)
            self.assert_unreadable(data_dir)

        with self.subTest(case="entry of an unknown kind"):
            data_dir, path, data = self.valid_file()
            found = entry_objects(data)
            self.assertEqual(len(found), 1, data)
            found[0]["kind"] = "invented_unknown_kind"
            write_json(path, data)
            self.assert_unreadable(data_dir)


class TestAccept(AcceptedTestCase):
    def test_saved_but_previous_is_ok_with_warning(self):
        data_dir = Path(self.data_dir())
        detail = make_pass(data_dir)
        warning = ("the new accepted.json is saved, but accepted.previous.json could not "
                   "be replaced: locked")
        with mock.patch.object(self.accepted.baseline, "save_json", return_value=warning):
            result = self.accepted.accept("ush-health u2", detail, data_dir)
        self.assertIs(result["ok"], True, result)
        self.assertEqual(result["key"], [U2_TITLE, U2_HRESULT], result)
        self.assertEqual(result["warning"], warning)

        with mock.patch.object(self.accepted.baseline, "save_json",
                               return_value="cannot write accepted.json.tmp: denied"):
            result = self.accepted.accept("ush-health u2", detail, data_dir)
        self.assertIs(result["ok"], False, result)
        self.assertIn("not saved", result["reason"])

    def test_update_entry(self):
        data_dir = self.data_dir()
        first = self.accept_ok(data_dir, "ush-health u2", make_pass(data_dir))
        self.assertEqual(first.get("kind"), "update", first)
        self.assertEqual(first.get("key"), [U2_TITLE, U2_HRESULT], first)

        entries = self.entries(data_dir)
        self.assertEqual(len(entries), 1, entries)
        entry = entries[0]
        self.assertEqual(entry.get("kind"), "update", entry)
        self.assertEqual(entry.get("key"), [U2_TITLE, U2_HRESULT], entry)
        self.assertEqual(values_of(entry.get("facts"), "last"), [U2_LAST], entry)

        # The same item accepted again (a later pass where it failed once more): the entry
        # is replaced, never duplicated.
        later = make_pass(data_dir, stamp="20261106-091000", u2_last=U2_LATER_LAST)
        second = self.accept_ok(data_dir, "ush-health u2", later)
        self.assertEqual(second.get("key"), [U2_TITLE, U2_HRESULT], second)

        entries = self.entries(data_dir)
        self.assertEqual(len(entries), 1, entries)
        self.assertEqual(entries[0].get("key"), [U2_TITLE, U2_HRESULT], entries)
        self.assertEqual(values_of(entries[0].get("facts"), "last"), [U2_LATER_LAST],
                         entries)

    def test_other_kinds(self):
        data_dir = self.data_dir()
        detail = make_pass(data_dir)
        expected = {
            "ush-inventory s3": ("autostart", TASK_KEY),
            "ush-events g4": ("event_group", EVENT_KEY),
            "ush-inventory x2": ("firewall_rule", RULE_KEY),
        }
        for target, (kind, key) in expected.items():
            with self.subTest(target=target):
                result = self.accept_ok(data_dir, target, detail)
                self.assertEqual(result.get("kind"), kind, result)
                self.assertEqual(result.get("key"), key, result)

        entries = self.entries(data_dir)
        self.assertEqual(len(entries), 3, entries)
        by_kind = {entry.get("kind"): entry for entry in entries}
        self.assertEqual(set(by_kind), {"autostart", "event_group", "firewall_rule"},
                         entries)
        for kind, key in expected.values():
            self.assertEqual(by_kind[kind].get("key"), key, by_kind[kind])

        autostart_hashes = values_of(by_kind["autostart"].get("facts"), "sha256")
        self.assertEqual(sorted(autostart_hashes), sorted([TASK_SHA_MAIN, TASK_SHA_HELPER]),
                         by_kind["autostart"])

    def assert_refused(self, data_dir, target, detail_file, before):
        result = self.run_accept(data_dir, target, detail_file)
        self.assertIs(result.get("ok"), False, result)
        reason = result.get("reason")
        self.assertIsInstance(reason, str, result)
        self.assertTrue(reason.strip(), result)
        path = self.accepted_path(data_dir)
        if before is None:
            self.assertFalse(path.exists(), path)
        else:
            self.assertEqual(path.read_bytes(), before, path)

    def test_refused(self):
        def good(data_dir):
            return make_pass(data_dir)

        def missing_runall_detail(data_dir):
            make_pass(data_dir)
            return data_dir / "work" / "runall-20261105-999999.detail.json"

        def runall_detail_not_json(data_dir):
            path = data_dir / "work" / "runall-20261105-101500.detail.json"
            make_pass(data_dir)
            path.write_text('{"schema_version": 1, "children": [', encoding="utf-8")
            return path

        def missing_child_detail(data_dir):
            return make_pass(data_dir, stamp="20261107-080000", health_detail_missing=True)

        cases = {
            "unknown id": ("ush-health u9", good),
            "skill not in the kinds file (a program)": ("ush-inventory a1", good),
            "skill not in the kinds file (a disk)": ("ush-health k1", good),
            "kind not in the kinds file (a root certificate)": ("ush-inventory x4", good),
            "missing runall detail file": ("ush-health u2", missing_runall_detail),
            "runall detail file not JSON": ("ush-health u2", runall_detail_not_json),
            "missing child detail file": ("ush-health u2", missing_child_detail),
        }
        for case, (target, build) in cases.items():
            with self.subTest(case=case, accepted="absent"):
                data_dir = self.data_dir()
                self.assert_refused(data_dir, target, build(data_dir), None)

            with self.subTest(case=case, accepted="earlier entries"):
                data_dir = self.data_dir()
                self.accept_ok(data_dir, "ush-inventory x2", make_pass(data_dir))
                before = self.accepted_path(data_dir).read_bytes()
                self.assert_refused(data_dir, target, build(data_dir), before)

        with self.subTest(case="autostart facts carried from the baseline"):
            data_dir = self.data_dir()
            detail = make_pass(data_dir)
            inventory_file = data_dir / "work" / "inventory-20261105-101500.detail.json"
            carried = inventory_detail()
            carried["autostart"][1]["facts_from_baseline"] = True
            write_json(inventory_file, carried)
            self.assert_refused(data_dir, "ush-inventory s3", detail, None)

        with self.subTest(case="existing accepted.json with bad JSON"):
            data_dir = self.data_dir()
            path = self.accepted_path(data_dir)
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"schema_version": 1, "entries": [{"kind": "update"')
            before = path.read_bytes()
            self.assert_refused(data_dir, "ush-health u2", make_pass(data_dir), before)


if __name__ == "__main__":
    unittest.main()

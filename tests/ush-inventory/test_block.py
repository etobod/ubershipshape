"""Paste-ready change blocks of skills/ush-inventory/scripts/inventory.py (plan 005, M1
and M2).

Interface under test (from the plan; the general one is in ``fakes.py``):

- ``main(["--data-dir", <dir>, "--block", "s1,s2", ("--detail-file", <file>)])``.
  ``--block`` takes a comma-separated id list and is mutually exclusive with ``--detail``
  and ``--cut``. Without ``--detail-file`` it reads the newest ``inventory-*.detail.json``
  in ``<data dir>/work/``.
- It prints the blocks on stdout, starts no PowerShell job and writes no file.
- Each block follows the templates of SKILL.md "Change blocks": a header naming the shell
  (non-elevated for HKCU and user entries, elevated otherwise), the risk and the previous
  value; the change commands; then the rollback block.
- An entry that meets a no-block condition prints ``# <id>: no block: <reason>`` and no
  command. An unknown id gives exit code 1.

Assumptions added by these tests beyond the plan text:

- The rollback block is introduced by a comment line containing the word "rollback"
  (any case) that comes after the change commands.
- The detail file is hand-written here in the shape ``inventory.py`` writes it: the
  top-level keys of ``main`` and autostart entries ``{id, key, source, kind, location,
  name, command, ...}``.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from .fakes import NOW, FakePowerShell, InventoryTestCase

STAMP = "20260920T120000Z"

# A previous StartupApproved value of an enabled entry (first byte 2) with invented
# trailing bytes, so the rollback can only have come from the entry.
RUN_APPROVED_RAW = "02000000a1b2c3d4e5f60718"

RUN_ENTRY = {
    "id": "s1",
    "key": "run:hkcu\\Run:InventedTool",
    "source": "run_keys",
    "kind": "run",
    "location": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "name": "InventedTool",
    "command": "\"%LOCALAPPDATA%\\InventedTool\\tool.exe\" --tray",
    "value_kind": "String",
    "targets": ["%LOCALAPPDATA%\\InventedTool\\tool.exe"],
    "approved": "enabled",
    "approved_raw": RUN_APPROVED_RAW,
    "enabled": True,
    "own": False,
}

TASK_ENTRY = {
    "id": "s2",
    "key": "task:\\InventedVendor\\InventedUpdater",
    "source": "scheduled_tasks",
    "kind": "task",
    "location": "\\InventedVendor\\",
    "name": "InventedUpdater",
    "command": "\"C:\\Program Files\\InventedVendor\\updater.exe\" /logon",
    "state": "Ready",
    "enabled": True,
    "targets": ["C:\\Program Files\\InventedVendor\\updater.exe"],
    "own": False,
}

SERVICE_ENTRY = {
    "id": "s3",
    "key": "service:InventedAgent",
    "source": "services",
    "kind": "service",
    "location": "HKLM\\SYSTEM\\CurrentControlSet\\Services\\InventedAgent",
    "name": "InventedAgent",
    "display_name": "Invented Agent",
    "command": "\"C:\\Program Files\\InventedVendor\\agent.exe\"",
    "state": "Running",
    "delayed": True,
    "user_service": False,
    "enabled": True,
    "targets": ["C:\\Program Files\\InventedVendor\\agent.exe"],
    "own": False,
}

USER_SERVICE_ENTRY = {
    "id": "s4",
    "key": "service:InventedSync",
    "source": "services",
    "kind": "service",
    "location": "HKLM\\SYSTEM\\CurrentControlSet\\Services\\InventedSync",
    "name": "InventedSync",
    "display_name": "Invented Sync",
    "command": "C:\\Windows\\system32\\svchost.exe -k InventedGroup",
    "state": "Running",
    "delayed": False,
    "user_service": True,
    "template_start": 2,
    "enabled": True,
    "targets": ["C:\\Windows\\System32\\inventedsync.dll"],
    "own": False,
}

# A task not read in this run, kept from the previous baseline.
BASELINE_TASK_ENTRY = {
    "id": "s5",
    "key": "task:\\InventedVendor\\InventedOldTask",
    "source": "scheduled_tasks",
    "kind": "task",
    "location": "\\InventedVendor\\",
    "name": "InventedOldTask",
    "command": "\"C:\\Program Files\\InventedVendor\\old.exe\"",
    "state": "Ready",
    "enabled": True,
    "targets": ["C:\\Program Files\\InventedVendor\\old.exe"],
    "from_baseline": True,
    "own": False,
}

# A Run entry whose StartupApproved value has an unknown first byte.
UNKNOWN_RUN_ENTRY = {
    "id": "s6",
    "key": "run:hkcu\\Run:InventedOdd",
    "source": "run_keys",
    "kind": "run",
    "location": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "name": "InventedOdd",
    "command": "\"%LOCALAPPDATA%\\InventedOdd\\odd.exe\"",
    "value_kind": "String",
    "targets": ["%LOCALAPPDATA%\\InventedOdd\\odd.exe"],
    "approved": "unknown",
    "approved_byte": 7,
    "approved_raw": "070000000000000000000000",
    "enabled": None,
    "unread_fields": ["enabled"],
    "own": False,
}

ENTRIES = [RUN_ENTRY, TASK_ENTRY, SERVICE_ENTRY, USER_SERVICE_ENTRY, BASELINE_TASK_ENTRY,
           UNKNOWN_RUN_ENTRY]


def source(name, status="read"):
    return {"name": name, "status": status, "reason": None}


def detail_document(summary_file):
    """A detail file in the top-level shape ``inventory.py`` writes."""
    return {
        "schema_version": 1,
        "skill": "ush-inventory",
        "generated_at": NOW.isoformat(),
        "elevated": False,
        "sources": [source(name) for name in (
            "run_keys", "startup_folders", "startup_approved", "scheduled_tasks",
            "services")],
        "comparison": {},
        "programs": [],
        "autostart": [dict(entry) for entry in ENTRIES],
        "components": [],
        "drivers": [],
        "drivers_without_inf_items": [],
        "additions": [],
        "hosts_file": None,
        "current_sid": None,
        "changes": [],
        "listed": {"programs": [], "autostart": [e["id"] for e in ENTRIES],
                   "components": [], "drivers": [], "additions": []},
        "summary_file": str(summary_file),
    }


def is_comment(line):
    return line.strip().startswith("#")


def commands(text):
    """Non-empty lines that are not comments."""
    return [line for line in text.splitlines() if line.strip() and not is_comment(line)]


def comments(text):
    return [line for line in text.splitlines() if is_comment(line)]


def snapshot(root):
    """Every directory and file under ``root`` with the bytes of each file."""
    result = {}
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root).as_posix()
        result[rel] = path.read_bytes() if path.is_file() else "<dir>"
    return result


class BlockTestCase(InventoryTestCase):
    def prepare(self):
        """A data dir whose ``work/`` holds one hand-written detail file (and summary)."""
        data_dir = self.data_dir()
        work = data_dir / "work"
        work.mkdir(parents=True)
        summary_file = work / f"inventory-{STAMP}.summary.json"
        summary_file.write_text(json.dumps({"skill": "ush-inventory"}), encoding="utf-8")
        detail_file = work / f"inventory-{STAMP}.detail.json"
        detail_file.write_text(json.dumps(detail_document(summary_file), indent=2),
                               encoding="utf-8")
        return data_dir, detail_file

    def block(self, data_dir, ids, detail_file=None, fake=None):
        """Run ``--block``; return (code, stdout, stderr). An argparse error gives 2."""
        extra = ["--block", ",".join(ids)]
        if detail_file is not None:
            extra += ["--detail-file", str(detail_file)]
        fake = fake if fake is not None else FakePowerShell()
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = self.inventory.main(
                    ["--data-dir", str(data_dir), *extra],
                    run_ps=fake, is_admin=lambda: False, now=NOW)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def split_rollback(self, stdout, change):
        """(change part, rollback part): the text before and after the first comment line
        naming "rollback" that follows the first command line matching ``change``."""
        lines = stdout.splitlines()
        first = next((i for i, line in enumerate(lines)
                      if not is_comment(line) and re.search(change, line)), None)
        self.assertIsNotNone(first, f"no change command matching {change!r}:\n{stdout}")
        marker = next((i for i in range(first + 1, len(lines))
                       if is_comment(lines[i]) and "rollback" in lines[i].lower()), None)
        self.assertIsNotNone(marker, f"no rollback comment after the change:\n{stdout}")
        return "\n".join(lines[:marker]), "\n".join(lines[marker + 1:])

    def assert_shell(self, text, elevated):
        lower = text.lower()
        if elevated:
            self.assertRegex(lower, r"(?<!non-)(?<!non )\belevated\b", text)
            self.assertNotIn("non-elevated", lower, text)
        else:
            self.assertIn("non-elevated", lower, text)

    def assert_header(self, change_part):
        header = "\n".join(comments(change_part)).lower()
        self.assertIn("risk", header, change_part)
        self.assertIn("previous", header, change_part)


class TestBlock(BlockTestCase):
    def test_run_entry_block(self):
        data_dir, detail_file = self.prepare()
        code, stdout, stderr = self.block(data_dir, ["s1"], detail_file=detail_file)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])

        change, rollback = self.split_rollback(stdout, r"New-ItemProperty")
        self.assert_shell(change, elevated=False)
        self.assert_header(change)
        # The previous state is shown before the commands run.
        self.assertTrue(any("enabled" in line.lower() for line in comments(change)), change)

        approved_key = ("HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer"
                        "\\StartupApproved\\Run")
        self.assertIn(approved_key, "\n".join(commands(change)), change)
        self.assertNotIn("HKLM:", "\n".join(commands(stdout)), stdout)
        writes = [line for line in commands(change)
                  if "New-ItemProperty" in line and "'InventedTool'" in line]
        self.assertTrue(writes, change)
        self.assertTrue(any(re.search(r"-PropertyType\s+Binary", line)
                            and re.search(r"\(\s*3\s*,\s*0\s*,", line) for line in writes),
                        writes)
        # The value or file itself stays: the change does not remove the Run value.
        self.assertFalse(any("Remove-ItemProperty" in line for line in commands(change)),
                         change)

        rollback_commands = "\n".join(commands(rollback))
        self.assertIn(approved_key, rollback_commands, rollback)
        self.assertIn(RUN_APPROVED_RAW, rollback_commands, rollback)
        self.assertTrue(any("New-ItemProperty" in line and "'InventedTool'" in line
                            and re.search(r"-PropertyType\s+Binary", line)
                            for line in commands(rollback)), rollback)
        self.assertFalse(any("Remove-ItemProperty" in line for line in commands(rollback)),
                         "the entry had a value: the rollback writes it back\n" + rollback)

    def test_task_and_service_blocks(self):
        data_dir, detail_file = self.prepare()

        with self.subTest(case="task"):
            code, stdout, stderr = self.block(data_dir, ["s2"], detail_file=detail_file)
            self.assertEqual(code, 0, stderr[:300] or stdout[:300])
            change, rollback = self.split_rollback(stdout, r"Disable-ScheduledTask")
            self.assert_shell(change, elevated=True)
            self.assert_header(change)
            self.assertTrue(any("Ready" in line for line in comments(change)), change)
            self.assertTrue(any(
                "Disable-ScheduledTask" in line
                and re.search(r"-TaskPath\s+'\\InventedVendor\\'", line)
                and re.search(r"-TaskName\s+'InventedUpdater'", line)
                for line in commands(change)), change)
            self.assertTrue(any(
                "Enable-ScheduledTask" in line
                and re.search(r"-TaskPath\s+'\\InventedVendor\\'", line)
                and re.search(r"-TaskName\s+'InventedUpdater'", line)
                for line in commands(rollback)), rollback)

        with self.subTest(case="service, delayed"):
            code, stdout, stderr = self.block(data_dir, ["s3"], detail_file=detail_file)
            self.assertEqual(code, 0, stderr[:300] or stdout[:300])
            change, rollback = self.split_rollback(stdout, r"Set-Service")
            self.assert_shell(change, elevated=True)
            self.assert_header(change)
            header = "\n".join(comments(change))
            self.assertIn("Automatic", header, change)
            self.assertIn("delayed", header.lower(), change)
            self.assertTrue(any(
                re.search(r"Set-Service\s+-Name\s+'InventedAgent'\s+-StartupType\s+Manual",
                          line)
                for line in commands(change)), change)
            self.assertTrue(any(
                re.search(r"sc\.exe\s+config\s+InventedAgent\s+start=\s*delayed-auto", line)
                for line in commands(rollback)), rollback)

        with self.subTest(case="per-user service"):
            code, stdout, stderr = self.block(data_dir, ["s4"], detail_file=detail_file)
            self.assertEqual(code, 0, stderr[:300] or stdout[:300])
            change, rollback = self.split_rollback(stdout, r"Set-ItemProperty")
            self.assert_shell(change, elevated=True)
            self.assert_header(change)
            self.assertTrue(any("start" in line.lower() and re.search(r"\b2\b", line)
                                for line in comments(change)), change)
            self.assertIn("HKLM:\\SYSTEM\\CurrentControlSet\\Services\\InventedSync",
                          stdout)
            self.assertTrue(any(
                "Set-ItemProperty" in line and re.search(r"-Name\s+'?Start'?", line)
                and re.search(r"-Value\s+3\b", line)
                for line in commands(change)), change)
            self.assertTrue(any(
                "Set-ItemProperty" in line and "InventedSync" in line
                and re.search(r"-Name\s+'?Start'?", line)
                and re.search(r"-Value\s+2\b", line)
                for line in commands(rollback)), rollback)

    def test_no_block_conditions(self):
        data_dir, detail_file = self.prepare()
        cases = {
            "from_baseline true": ("s5", "InventedOldTask"),
            "approved unknown": ("s6", "InventedOdd"),
        }
        for case, (item_id, name) in cases.items():
            with self.subTest(case=case):
                code, stdout, stderr = self.block(data_dir, [item_id],
                                                  detail_file=detail_file)
                self.assertTrue(stdout.strip(), f"nothing printed (exit {code}): {stderr}")
                self.assertEqual(commands(stdout), [], stdout)
                self.assertRegex(stdout, rf"(?m)^\s*#\s*{item_id}\s*:\s*no block\s*:\s*\S",
                                 stdout)
                self.assertNotIn(name, "\n".join(commands(stdout)), stdout)

        with self.subTest(case="both together"):
            code, stdout, stderr = self.block(data_dir, ["s5", "s6"],
                                              detail_file=detail_file)
            self.assertEqual(commands(stdout), [], stdout)
            for item_id in ("s5", "s6"):
                self.assertRegex(stdout, rf"(?m)^\s*#\s*{item_id}\s*:\s*no block\s*:\s*\S",
                                 stdout)

    def test_print_only_and_unknown_id(self):
        data_dir, _detail_file = self.prepare()
        before = snapshot(data_dir)
        fake = FakePowerShell()
        with mock.patch("subprocess.Popen",
                        side_effect=AssertionError("a process was started")) as popen:
            # No --detail-file: the newest detail file in <data dir>/work/ is read.
            code, stdout, stderr = self.block(data_dir, ["s1", "s2", "s3"], fake=fake)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        self.assertTrue(commands(stdout), stdout)
        self.assertIn("InventedTool", stdout)
        self.assertIn("InventedUpdater", stdout)
        self.assertIn("InventedAgent", stdout)
        self.assertEqual(fake.calls, [], "--block started a PowerShell job")
        self.assertFalse(popen.called, "--block started a process")
        after = snapshot(data_dir)
        self.assertEqual(sorted(after), sorted(before), "a file was created or removed")
        changed = [name for name in before if before[name] != after.get(name)]
        self.assertEqual(changed, [], "a file under the data dir was changed")

        unknown_fake = FakePowerShell()
        code, stdout, stderr = self.block(data_dir, ["s999"], fake=unknown_fake)
        self.assertEqual(code, 1, stdout[:300] or stderr[:300])
        self.assertEqual(commands(stdout), [], stdout)
        self.assertEqual(unknown_fake.calls, [])
        self.assertEqual(snapshot(data_dir), before)


# --- M2: additions (x..) and components (f..) -------------------------------------------
#
# Assumptions added by these tests beyond the plan text (field shapes from
# references/summary-contract.md, "Additions", "Components" and "Drivers"):
#
# - Detail items carry ``id``, ``key``, ``source``, ``kind``, ``own`` and the fields of
#   their kind; the ``method`` of ``administrators`` and ``defender_exclusions`` is on
#   that source's entry in ``sources``.
# - Each block, like the M1 ones, has a header naming the shell, the risk and the
#   previous state, then the change commands, then a comment naming "rollback" followed
#   by the rollback commands.
# - Capabilities and Defender exclusions are read only in an elevated run, so their
#   items come from an elevated detail file; every other item from a non-elevated one.

CURRENT_SID = "S-1-5-21-0-0-0-1001"
OTHER_ADMIN_SID = "S-1-5-21-0-0-0-1002"

LOCAL_RULE_NAME = "{00000000-0000-0000-0000-00000000A001}"
MACHINE_THUMB = "0123456789ABCDEF0123456789ABCDEF01234567"
USER_THUMB = "89ABCDEF0123456789ABCDEF0123456789ABCDEF"
HOSTS_ADDRESS = "0.0.0.0"
HOSTS_NAME = "ads.invented.example"
DEFENDER_PATH = "C:\\InventedTool\\cache"
FEATURE_NAME = "Invented-Feature-Client"
CAPABILITY_NAME = "Invented.Tools~~~~0.0.1.0"
DRIVER_ID = "PCI\\VEN_0000&DEV_0000&SUBSYS_00000000\\0&INVENTED"


def firewall_item(item_id, store, value_name, name, no_block_reason=None):
    item = {
        "id": item_id,
        "key": f"firewall:{store}:{value_name}",
        "source": "firewall_rules",
        "kind": "firewall_rule",
        "store": store,
        "action": "Allow",
        "dir": "In",
        "active": "TRUE",
        "protocol": 6,
        "protocol_name": "TCP",
        "lport": "47001",
        "rport": None,
        "app": "C:\\Program Files\\InventedSync\\sync.exe",
        "svc": None,
        "name": name,
        "profile": None,
        "embed_ctxt": None,
        "lport2": None,
        "version": "v2.33",
        "app_exists": True,
        "own": False,
    }
    if no_block_reason is not None:
        item["no_block_reason"] = no_block_reason
    return item


def certificate_item(item_id, store, thumbprint, subject):
    return {
        "id": item_id,
        "key": f"cert:{store}:{thumbprint}",
        "source": "root_certificates",
        "kind": "root_certificate",
        "store": store,
        "thumbprint": thumbprint,
        "subject": subject,
        "issuer": subject,
        "not_before": "2025-01-01",
        "not_after": "2035-01-01",
        "self_signed": True,
        "in_authroot": False,
        "serial": "5A3C",
        "own": False,
    }


def admin_item(item_id, sid, name, is_current):
    return {
        "id": item_id,
        "key": f"admin:{sid}",
        "source": "administrators",
        "kind": "administrator",
        "name": name,
        "object_class": "User",
        "principal_source": "Local",
        "enabled": True,
        "is_current": is_current,
        "builtin": False,
        "own": False,
    }


LOCAL_RULE = firewall_item("x1", "local", LOCAL_RULE_NAME, "Invented Sync TCP in")
APP_ISO_RULE = firewall_item("x2", "app_iso", "{00000000-0000-0000-0000-00000000A002}",
                             "Invented Store App in", no_block_reason="store_app_iso")
POLICY_RULE = firewall_item("x3", "policy", "{00000000-0000-0000-0000-00000000A003}",
                            "Invented Policy Rule in", no_block_reason="store_policy")
MACHINE_CERT = certificate_item("x4", "machine_root", MACHINE_THUMB, "CN=Invented Root CA")
USER_CERT = certificate_item("x5", "user_root", USER_THUMB, "CN=Invented User Root")
HOSTS_ITEM = {
    "id": "x6",
    "key": f"hosts:{HOSTS_NAME}:{HOSTS_ADDRESS}",
    "source": "hosts",
    "kind": "hosts_entry",
    "address": HOSTS_ADDRESS,
    "hostname": HOSTS_NAME,
    "line": 23,
    "duplicates": 0,
    "own": False,
}
OTHER_ADMIN = admin_item("x7", OTHER_ADMIN_SID, "InventedHelper", False)
CURRENT_ADMIN = admin_item("x8", CURRENT_SID, "InventedOwner", True)
DEFENDER_ITEM = {
    "id": "x9",
    "key": f"defender:path:{DEFENDER_PATH.lower()}",
    "source": "defender_exclusions",
    "kind": "defender_exclusion",
    "type": "path",
    "value": DEFENDER_PATH,
    "origin": "local",
    "own": False,
}
FEATURE_ITEM = {
    "id": "f1",
    "key": f"feature:{FEATURE_NAME}",
    "source": "optional_features",
    "kind": "feature",
    "name": FEATURE_NAME,
    "caption": "Invented Feature Client",
    "state": "enabled",
    "own": False,
}
CAPABILITY_ITEM = {
    "id": "f2",
    "key": f"capability:{CAPABILITY_NAME}",
    "source": "capabilities",
    "kind": "capability",
    "name": CAPABILITY_NAME,
    "state": "Installed",
    "own": False,
}
DRIVER_ITEM = {
    "id": "d1",
    "key": f"driver:{DRIVER_ID}",
    "source": "drivers",
    "device_name": "Invented Capture Device",
    "class": "MEDIA",
    "inf_name": "oem42.inf",
    "provider": "Invented Hardware Vendor Ltd",
    "version": "1.2.3.4",
    "date": "2026-01-15",
    "signer": "Invented Hardware Compatibility Publisher",
    "third_party": True,
    "own": False,
}

ADMIN_ONLY = "requires administrator rights (not read in this run, which is not elevated)"


def additions_document(summary_file, elevated):
    """A detail file with autostart entries, additions, components and a driver.

    Non-elevated: every addition but the Defender exclusion, the feature and the driver;
    ``capabilities`` and ``defender_exclusions`` are unreadable. Elevated: the Defender
    exclusion, the feature and the capability.
    """
    document = detail_document(summary_file)
    document["elevated"] = elevated
    sources = [source(name) for name in (
        "run_keys", "startup_folders", "startup_approved", "scheduled_tasks", "services",
        "optional_features", "drivers", "firewall_rules", "root_certificates", "hosts")]
    admins = source("administrators")
    admins["method"] = "local_group_member"
    sources.append(admins)
    if elevated:
        sources.append(source("capabilities"))
        defender = source("defender_exclusions")
        defender["method"] = "preference"
        sources.append(defender)
        additions = [DEFENDER_ITEM]
        components = [FEATURE_ITEM, CAPABILITY_ITEM]
        drivers = []
    else:
        for name in ("capabilities", "defender_exclusions"):
            unread = source(name, status="unreadable")
            unread["reason"] = ADMIN_ONLY
            sources.append(unread)
        additions = [LOCAL_RULE, APP_ISO_RULE, POLICY_RULE, MACHINE_CERT, USER_CERT,
                     HOSTS_ITEM, OTHER_ADMIN, CURRENT_ADMIN]
        components = [FEATURE_ITEM]
        drivers = [DRIVER_ITEM]
    document["sources"] = sources
    document["additions"] = [dict(item) for item in additions]
    document["components"] = [dict(item) for item in components]
    document["drivers"] = [dict(item) for item in drivers]
    document["hosts_file"] = {"exists": True, "path_is_default": True}
    document["current_sid"] = CURRENT_SID
    document["listed"]["additions"] = [item["id"] for item in additions]
    document["listed"]["components"] = [item["id"] for item in components]
    document["listed"]["drivers"] = [item["id"] for item in drivers]
    return document


def first_index(lines, pattern):
    return next((i for i, line in enumerate(lines) if re.search(pattern, line)), None)


class AdditionBlockTestCase(BlockTestCase):
    def prepare_additions(self, elevated=False):
        """A data dir whose ``work/`` holds one detail file of ``additions_document``."""
        data_dir = self.data_dir()
        work = data_dir / "work"
        work.mkdir(parents=True)
        summary_file = work / f"inventory-{STAMP}.summary.json"
        summary_file.write_text(json.dumps({"skill": "ush-inventory", "not_checked": []}),
                                encoding="utf-8")
        detail_file = work / f"inventory-{STAMP}.detail.json"
        detail_file.write_text(json.dumps(additions_document(summary_file, elevated),
                                          indent=2), encoding="utf-8")
        return data_dir, detail_file

    def printed_block(self, data_dir, detail_file, item_id, change, elevated):
        """Print one block; check exit 0, the shell and the header; return (change part,
        rollback part)."""
        code, stdout, stderr = self.block(data_dir, [item_id], detail_file=detail_file)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        self.assertIsNone(re.search(rf"(?m)^\s*#\s*{item_id}\s*:\s*no block", stdout),
                          stdout)
        change_part, rollback = self.split_rollback(stdout, change)
        self.assert_shell(change_part, elevated=elevated)
        self.assert_header(change_part)
        return change_part, rollback

    def assert_no_block_line(self, stdout, item_id):
        """The ``# <id>: no block: <reason>`` line; returns it."""
        match = re.search(rf"(?m)^\s*#\s*{item_id}\s*:\s*no block\s*:\s*\S.*$", stdout)
        self.assertIsNotNone(match, stdout)
        return match.group(0)


class TestAdditionBlocks(AdditionBlockTestCase):
    def test_firewall_rule_block(self):
        data_dir, detail_file = self.prepare_additions()

        with self.subTest(case="local rule"):
            change, rollback = self.printed_block(
                data_dir, detail_file, "x1", r"Disable-NetFirewallRule", elevated=True)
            quoted = re.escape(f"'{LOCAL_RULE_NAME}'")
            disables = [line for line in commands(change)
                        if "Disable-NetFirewallRule" in line]
            self.assertEqual(len(disables), 1, change)
            # -Name is the registry value name from the key, not the display name.
            self.assertRegex(disables[0], rf"Disable-NetFirewallRule\s+-Name\s+{quoted}")
            self.assertNotIn("Invented Sync TCP in", "\n".join(commands(change)), change)
            # Previous state: Active = TRUE.
            self.assertTrue(any("TRUE" in line for line in comments(change)), change)
            # Disable only: the rule is never removed.
            self.assertNotIn("Remove-NetFirewallRule", change)
            self.assertTrue(any(
                re.search(rf"Enable-NetFirewallRule\s+-Name\s+{quoted}", line)
                for line in commands(rollback)), rollback)
            self.assertFalse(any("Disable-NetFirewallRule" in line
                                 for line in commands(rollback)), rollback)

        for item_id, rule in (("x2", APP_ISO_RULE), ("x3", POLICY_RULE)):
            with self.subTest(case=f"store {rule['store']}"):
                _code, stdout, _stderr = self.block(data_dir, [item_id],
                                                    detail_file=detail_file)
                self.assertEqual(commands(stdout), [], stdout)
                line = self.assert_no_block_line(stdout, item_id)
                self.assertNotIn("not supported", line)
                self.assertRegex(line, r"store|local|app_iso|policy", line)
                value_name = rule["key"].rsplit(":", 1)[1]
                self.assertNotIn(value_name, "\n".join(commands(stdout)), stdout)

    def test_certificate_blocks(self):
        data_dir, detail_file = self.prepare_additions()
        cases = {
            "machine_root": ("x4", MACHINE_THUMB, True, "Cert:\\LocalMachine\\Root",
                             "Cert:\\CurrentUser\\Root"),
            "user_root": ("x5", USER_THUMB, False, "Cert:\\CurrentUser\\Root",
                          "Cert:\\LocalMachine\\Root"),
        }
        for store, (item_id, thumbprint, elevated, own_store, other_store) in cases.items():
            with self.subTest(store=store):
                change, rollback = self.printed_block(
                    data_dir, detail_file, item_id, r"Export-Certificate",
                    elevated=elevated)
                lines = commands(change)
                text = "\n".join(lines)
                self.assertIn(thumbprint, text, change)
                self.assertIn(own_store, text, change)
                self.assertNotIn(other_store, text, change)
                # The export comes first, into <data dir>\work\, and a thumbprint check
                # that can stop the block stands between it and the removal.
                export = first_index(lines, r"Export-Certificate")
                check = next((i for i in range(export + 1, len(lines))
                              if re.search(r"(?i)thumbprint.*throw|throw.*thumbprint",
                                           lines[i])), None)
                remove = first_index(lines, r"Remove-Item")
                self.assertIsNotNone(remove, change)
                self.assertIsNotNone(check, change)
                self.assertLess(export, check, change)
                self.assertLess(check, remove, change)
                self.assertIn(str(data_dir / "work"), text, change)

                exported = str(data_dir / "work" / f"cert-{thumbprint}.cer")
                imports = [line for line in commands(rollback)
                           if "Import-Certificate" in line]
                self.assertEqual(len(imports), 1, rollback)
                self.assertIn(f"'{exported}'", imports[0], rollback)
                self.assertRegex(imports[0],
                                 rf"-CertStoreLocation\s+'{re.escape(own_store)}'")
                self.assertNotIn("Remove-Item", "\n".join(commands(rollback)), rollback)

    def test_other_addition_blocks(self):
        data_dir, detail_file = self.prepare_additions()
        elevated_dir, elevated_file = self.prepare_additions(elevated=True)

        with self.subTest(case="feature"):
            change, rollback = self.printed_block(
                data_dir, detail_file, "f1", r"Disable-WindowsOptionalFeature", elevated=True)
            name = re.escape(f"'{FEATURE_NAME}'")
            self.assertTrue(any(
                re.search(rf"Disable-WindowsOptionalFeature\s+-Online\s+-FeatureName\s+{name}",
                          line) for line in commands(change)), change)
            self.assertTrue(any("enabled" in line.lower() for line in comments(change)),
                            change)
            self.assertTrue(any("restart" in line.lower() for line in comments(change)),
                            change)
            self.assertTrue(any(
                re.search(rf"Enable-WindowsOptionalFeature\s+-Online\s+-FeatureName\s+{name}",
                          line) for line in commands(rollback)), rollback)

        with self.subTest(case="capability"):
            change, rollback = self.printed_block(
                elevated_dir, elevated_file, "f2", r"Remove-WindowsCapability", elevated=True)
            name = re.escape(f"'{CAPABILITY_NAME}'")
            self.assertTrue(any(
                re.search(rf"Remove-WindowsCapability\s+-Online\s+-Name\s+{name}", line)
                for line in commands(change)), change)
            self.assertTrue(any("Installed" in line for line in comments(change)), change)
            self.assertTrue(any(
                re.search(rf"Add-WindowsCapability\s+-Online\s+-Name\s+{name}", line)
                for line in commands(rollback)), rollback)

        with self.subTest(case="hosts entry"):
            change, rollback = self.printed_block(
                data_dir, detail_file, "x6", r"Copy-Item", elevated=True)
            lines = commands(change)
            text = "\n".join(lines)
            self.assertIn(f"'{HOSTS_ADDRESS}'", text, change)
            self.assertIn(f"'{HOSTS_NAME}'", text, change)
            self.assertIn("DataBasePath", text, change)
            backups = re.findall(r"'([^']*\\hosts-[^']*\.bak)'", text)
            self.assertTrue(backups, change)
            backup = backups[0]
            self.assertTrue(backup.startswith(str(data_dir / "work") + "\\"), backup)
            # The copy is made and compared before the file is written.
            copy = first_index(lines, r"Copy-Item")
            compare = first_index(lines, r"Get-FileHash")
            write = first_index(lines, r"WriteAllText|Set-Content|Out-File")
            self.assertIsNotNone(compare, change)
            self.assertIsNotNone(write, change)
            self.assertLess(copy, compare, change)
            self.assertLess(compare, write, change)
            self.assertTrue(any("Copy-Item" in line and f"'{backup}'" in line
                                and "hosts" in line.split(f"'{backup}'", 1)[1]
                                for line in commands(rollback)), rollback)

        with self.subTest(case="administrator"):
            change, rollback = self.printed_block(
                data_dir, detail_file, "x7", r"Remove-LocalGroupMember", elevated=True)
            sid = re.escape(f"'{OTHER_ADMIN_SID}'")
            group = re.escape("'S-1-5-32-544'")
            self.assertTrue(any(
                re.search(rf"Remove-LocalGroupMember\s+-SID\s+{group}\s+-Member\s+{sid}", line)
                for line in commands(change)), change)
            self.assertNotIn(CURRENT_SID, "\n".join(commands(change)), change)
            self.assertTrue(any(
                re.search(rf"Add-LocalGroupMember\s+-SID\s+{group}\s+-Member\s+{sid}", line)
                for line in commands(rollback)), rollback)

        with self.subTest(case="defender exclusion"):
            change, rollback = self.printed_block(
                elevated_dir, elevated_file, "x9", r"Remove-MpPreference", elevated=True)
            value = re.escape(f"'{DEFENDER_PATH}'")
            self.assertTrue(any(
                re.search(rf"Remove-MpPreference\s+-ExclusionPath\s+{value}", line)
                for line in commands(change)), change)
            self.assertTrue(any(
                re.search(rf"Add-MpPreference\s+-ExclusionPath\s+{value}", line)
                for line in commands(rollback)), rollback)

        with self.subTest(case="driver"):
            _code, stdout, _stderr = self.block(data_dir, ["d1"], detail_file=detail_file)
            self.assertEqual(commands(stdout), [], stdout)
            line = self.assert_no_block_line(stdout, "d1")
            self.assertIn("driver", line.lower(), line)
            self.assertNotIn("not supported", line)

    def test_ids_order_and_duplicates(self):
        data_dir, detail_file = self.prepare_additions()
        firewall = r"\bDisable-NetFirewallRule\b"
        task = r"\bDisable-ScheduledTask\b"

        with self.subTest(ids="x1,x1,s2"):
            code, stdout, stderr = self.block(data_dir, ["x1", "x1", "s2"],
                                              detail_file=detail_file)
            self.assertEqual(code, 0, stderr[:300] or stdout[:300])
            lines = commands(stdout)
            self.assertEqual(len([line for line in lines if re.search(firewall, line)]), 1,
                             stdout)
            self.assertEqual(len([line for line in lines
                                  if re.search(r"\bEnable-NetFirewallRule\b", line)]),
                             1, stdout)
            self.assertEqual(len([line for line in lines if re.search(task, line)]), 1,
                             stdout)
            self.assertEqual(len([line for line in lines
                                  if re.search(r"\bEnable-ScheduledTask\b", line)]),
                             1, stdout)
            # Block x1 with its rollback, then block s2.
            enable_rule = first_index(lines, r"\bEnable-NetFirewallRule\b")
            self.assertLess(first_index(lines, firewall), enable_rule, stdout)
            self.assertLess(enable_rule, first_index(lines, task), stdout)
            self.assertNotRegex(stdout, r"(?m)^\s*#\s*(x1|s2)\s*:\s*no block", stdout)

        with self.subTest(ids="s2,x1"):
            code, stdout, stderr = self.block(data_dir, ["s2", "x1"],
                                              detail_file=detail_file)
            self.assertEqual(code, 0, stderr[:300] or stdout[:300])
            lines = commands(stdout)
            enable_task = first_index(lines, r"\bEnable-ScheduledTask\b")
            self.assertIsNotNone(first_index(lines, task), stdout)
            self.assertIsNotNone(first_index(lines, firewall), stdout)
            self.assertIsNotNone(enable_task, stdout)
            self.assertLess(first_index(lines, task), enable_task, stdout)
            self.assertLess(enable_task, first_index(lines, firewall), stdout)


# --- plan 007 M2: leftover registry keys (K3) and the missing-target fact line (K4) -----
#
# Assumptions added by these tests beyond the plan text:
#
# - The detail file has a ``leftovers`` section (``listed["leftovers"]`` holds the ids) in
#   the shape of references/summary-contract.md "Leftovers"; a registry part is
#   ``{kind: "registry_key", path, exists, status, reason, values, subkeys}`` with
#   ``path`` as ``HKLM\SOFTWARE\<publisher>\<name>`` or ``HKCU\SOFTWARE\<publisher>\<name>``;
#   the block takes the hive and the key from ``path`` alone.
# - The block per key: a ``reg export`` (or ``reg.exe export``) of the key; after it a
#   check with ``Test-Path`` and the key's header line written literally
#   (``[HKEY_LOCAL_MACHINE\SOFTWARE\...]``, e.g. via ``Select-String -SimpleMatch``) that
#   can ``throw``; then ``Remove-Item ... -Recurse`` of the key (``HKLM:\`` / ``HKCU:\``
#   or ``Registry::HKEY_...``). Then a comment naming "rollback" and ``reg import`` of the
#   export file, whose folder is named in the rollback itself.
# - With an explicit data dir the export goes under ``<data dir>\work``; with the default
#   data dir the path is built from ``$env:LOCALAPPDATA`` at run time.
# - K4: an autostart entry's ``facts`` are ``[{path, expanded_path, exists,
#   signature_status, signer, company, program}]`` (the detail file shape); the fact line
#   is a comment holding "does not exist" and the target path.

LEFTOVER_FIRST_GONE = "2026-09-19"


def registry_part(path, values, subkeys):
    return {"kind": "registry_key", "path": path, "exists": True, "status": "read",
            "reason": None, "values": values, "subkeys": subkeys}


def leftover(item_id, key_name, name, publisher, parts):
    program = {
        "key": f"win32:hklm64:{key_name}",
        "source": "win32_programs",
        "name": name,
        "publisher": publisher,
        "install_location": f"C:\\Invented\\{publisher}\\{name}",
        "first_seen_gone": LEFTOVER_FIRST_GONE,
    }
    return {"id": item_id, "key": program["key"], "program": program, "other_programs": [],
            "first_seen_gone": LEFTOVER_FIRST_GONE, "folder": None, "parts": parts}


WIDGET_HKLM = "HKLM\\SOFTWARE\\Contoso\\Widget Pro"
GADGET_HKCU = "HKCU\\SOFTWARE\\Contoso\\Gadget Lite"
LEFTOVERS = [
    leftover("l1", "ContosoWidgetPro", "Widget Pro", "Contoso",
             [registry_part(WIDGET_HKLM, 3, 1)]),
    leftover("l2", "ContosoGadgetLite", "Gadget Lite", "Contoso",
             [registry_part(GADGET_HKCU, 2, 0)]),
]

REG_EXPORT = r"(?i)\breg(\.exe)?\s+export\b"
REG_IMPORT = r"(?i)\breg(\.exe)?\s+import\b"


def fact(path, exists):
    return {"path": path, "expanded_path": path, "exists": exists,
            "signature_status": None, "signer": None, "company": None, "program": None}


GONE_RUN_TARGET = "C:\\Invented\\GoneTool\\tool.exe"
GONE_TASK_TARGET = "C:\\Invented\\GoneVendor\\updater.exe"
GONE_SERVICE_TARGET = "C:\\Invented\\GoneVendor\\agent.exe"


def target_entries(exists):
    """A run value, a task and a service, each with one target whose ``exists`` is given."""
    run = dict(RUN_ENTRY, command=f"\"{GONE_RUN_TARGET}\" --tray",
               targets=[GONE_RUN_TARGET], facts=[fact(GONE_RUN_TARGET, exists)])
    task = dict(TASK_ENTRY, command=f"\"{GONE_TASK_TARGET}\" /logon",
                targets=[GONE_TASK_TARGET], facts=[fact(GONE_TASK_TARGET, exists)])
    svc = dict(SERVICE_ENTRY, command=f"\"{GONE_SERVICE_TARGET}\"",
               targets=[GONE_SERVICE_TARGET], facts=[fact(GONE_SERVICE_TARGET, exists)])
    return [run, task, svc]


class LeftoverBlockTestCase(BlockTestCase):
    def prepare_document(self, change):
        """A data dir whose ``work/`` holds one detail file: ``detail_document`` changed
        by ``change(document)``."""
        data_dir = self.data_dir()
        work = data_dir / "work"
        work.mkdir(parents=True)
        summary_file = work / f"inventory-{STAMP}.summary.json"
        summary_file.write_text(json.dumps({"skill": "ush-inventory", "not_checked": []}),
                                encoding="utf-8")
        document = detail_document(summary_file)
        change(document)
        detail_file = work / f"inventory-{STAMP}.detail.json"
        detail_file.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return data_dir, detail_file

    def prepare_leftovers(self):
        def change(document):
            document["leftovers"] = json.loads(json.dumps(LEFTOVERS))
            document["listed"]["leftovers"] = [item["id"] for item in LEFTOVERS]
        return self.prepare_document(change)

    def prepare_targets(self, exists):
        def change(document):
            entries = target_entries(exists)
            document["autostart"] = entries
            document["listed"]["autostart"] = [entry["id"] for entry in entries]
        return self.prepare_document(change)

    def assert_registry_block(self, stdout, reg_key, ps_key, header, elevated, work):
        """The export, the check, the removal and the rollback of one key."""
        change, rollback = self.split_rollback(stdout, REG_EXPORT)
        self.assert_shell(change, elevated=elevated)
        lines = commands(change)
        export = first_index(lines, REG_EXPORT)
        self.assertRegex(lines[export], reg_key, change)
        # The export file lies in the work folder, named at or before the export.
        self.assertIn(work.lower(), "\n".join(lines[:export + 1]).lower(), change)
        remove = next((i for i, line in enumerate(lines)
                       if "Remove-Item" in line and re.search(r"-Recurse\b", line)
                       and re.search(ps_key, line)), None)
        self.assertIsNotNone(remove, change)
        self.assertLess(export, remove, change)
        check = "\n".join(lines[export + 1:remove])
        self.assertIn("Test-Path", check, change)
        self.assertIn(header, check, change)
        self.assertRegex(check, r"\bthrow\b", change)

        rollback_lines = commands(rollback)
        self.assertTrue([line for line in rollback_lines if re.search(REG_IMPORT, line)],
                        rollback)
        self.assertIn(work.lower(), "\n".join(rollback_lines).lower(), rollback)
        self.assertFalse([line for line in rollback_lines if "Remove-Item" in line],
                         rollback)


class TestLeftoverBlocks(LeftoverBlockTestCase):
    def test_leftover_registry_block(self):
        data_dir, detail_file = self.prepare_leftovers()
        work = str(data_dir / "work")
        # The temporary data dir must not lie under LOCALAPPDATA or USERPROFILE, or the
        # HKCU export path is built from the variable (TestExportPathFromEnv covers that).
        invented = {"LOCALAPPDATA": r"Q:\InventedProfile\AppData\Local",
                    "USERPROFILE": r"Q:\InventedProfile"}
        patcher = mock.patch.dict(os.environ, invented)
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.subTest(case="HKLM key"):
            fake = FakePowerShell()
            with mock.patch("subprocess.Popen",
                            side_effect=AssertionError("a process was started")) as popen:
                code, stdout, stderr = self.block(data_dir, ["l1"], detail_file=detail_file,
                                                  fake=fake)
            self.assertEqual(code, 0, stderr[:300] or stdout[:300])
            self.assertNotRegex(stdout, r"(?m)^\s*#\s*l1\s*:\s*no block", stdout)
            self.assert_registry_block(
                stdout,
                reg_key=r"(HKLM|HKEY_LOCAL_MACHINE)\\SOFTWARE\\Contoso\\Widget Pro",
                ps_key=r"(HKLM:|Registry::HKEY_LOCAL_MACHINE|Registry::HKLM)"
                       r"\\SOFTWARE\\Contoso\\Widget Pro",
                header="[HKEY_LOCAL_MACHINE\\SOFTWARE\\Contoso\\Widget Pro]",
                elevated=True, work=work)
            self.assertEqual(fake.calls, [], "--block started a PowerShell job")
            self.assertFalse(popen.called, "--block started a process")

        with self.subTest(case="HKCU key"):
            fake = FakePowerShell()
            code, stdout, stderr = self.block(data_dir, ["l2"], detail_file=detail_file,
                                              fake=fake)
            self.assertEqual(code, 0, stderr[:300] or stdout[:300])
            self.assert_registry_block(
                stdout,
                reg_key=r"(HKCU|HKEY_CURRENT_USER)\\SOFTWARE\\Contoso\\Gadget Lite",
                ps_key=r"(HKCU:|Registry::HKEY_CURRENT_USER|Registry::HKCU)"
                       r"\\SOFTWARE\\Contoso\\Gadget Lite",
                header="[HKEY_CURRENT_USER\\SOFTWARE\\Contoso\\Gadget Lite]",
                elevated=False, work=work)
            self.assertEqual(fake.calls, [])

    def test_missing_target_fact_line(self):
        missing_dir, missing_file = self.prepare_targets(exists=False)
        present_dir, present_file = self.prepare_targets(exists=True)
        cases = (("run", "s1", GONE_RUN_TARGET), ("task", "s2", GONE_TASK_TARGET),
                 ("service", "s3", GONE_SERVICE_TARGET))
        for kind, item_id, target in cases:
            with self.subTest(kind=kind):
                code, missing, stderr = self.block(missing_dir, [item_id],
                                                   detail_file=missing_file)
                self.assertEqual(code, 0, stderr[:300] or missing[:300])
                code, present, stderr = self.block(present_dir, [item_id],
                                                   detail_file=present_file)
                self.assertEqual(code, 0, stderr[:300] or present[:300])
                self.assertTrue(commands(missing), missing)
                self.assertTrue(commands(present), present)

                fact_lines = [line for line in comments(missing)
                              if re.search(r"(?i)does not exist", line)]
                self.assertEqual(len(fact_lines), 1, missing)
                self.assertIn(target.lower(), fact_lines[0].lower(), missing)
                self.assertFalse([line for line in present.splitlines()
                                  if re.search(r"(?i)does not exist", line)], present)

                def risk_lines(text):
                    return [line.strip() for line in comments(text)
                            if "risk" in line.lower()]
                self.assertTrue(risk_lines(present), present)
                self.assertEqual(risk_lines(missing), risk_lines(present),
                                 f"--- missing ---\n{missing}\n--- present ---\n{present}")


def entries_of(stdout):
    """The printed entries: blocks of lines separated by blank lines."""
    return [chunk for chunk in re.split(r"\n\s*\n", stdout) if chunk.strip()]


EXPORT_NAME = r"(?i)reg-[^'\")\s]*\.reg"


class TestLeftoverBlocksReview(LeftoverBlockTestCase):
    """Plan 007 M2, review round 1: findings #2 to #5."""

    def prepare_parts(self, leftovers):
        def change(document):
            document["leftovers"] = leftovers
            document["listed"]["leftovers"] = [item["id"] for item in leftovers]
        return self.prepare_document(change)

    def test_export_names_unique_per_key(self):
        """#2: keys whose names sanitise alike get their own export file, and each
        rollback imports its own."""
        one = "HKLM\\SOFTWARE\\Pub\\Foo Bar"
        two = "HKLM\\SOFTWARE\\Pub\\Foo_Bar"
        three = "HKLM\\SOFTWARE\\Pub\\Foo&Bar"
        data_dir, detail_file = self.prepare_parts([
            leftover("l1", "PubFooBar", "Foo Bar", "Pub", [registry_part(one, 1, 0)]),
            leftover("l2", "PubFooBar2", "Foo_Bar", "Pub",
                     [registry_part(two, 1, 0), registry_part(three, 1, 0)]),
        ])
        code, stdout, stderr = self.block(data_dir, ["l1", "l2"], detail_file=detail_file)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        entries = [entry for entry in entries_of(stdout) if re.search(REG_EXPORT, entry)]
        self.assertEqual(len(entries), 3, stdout)
        names = []
        for entry in entries:
            change, rollback = self.split_rollback(entry, REG_EXPORT)
            in_change = {n.lower() for n in re.findall(EXPORT_NAME, "\n".join(
                commands(change)))}
            in_rollback = {n.lower() for n in re.findall(EXPORT_NAME, "\n".join(
                commands(rollback)))}
            self.assertEqual(len(in_change), 1, entry)
            self.assertEqual(in_rollback, in_change, entry)
            names.append(in_change.pop())
        self.assertEqual(len(set(names)), 3, names)

    def test_missing_fact_from_baseline_no_line(self):
        """#3: a fact carried over from the baseline gives no "does not exist" line."""
        def change(document):
            entries = target_entries(False)
            for entry in entries:
                entry["facts_from_baseline"] = True
            document["autostart"] = entries
            document["listed"]["autostart"] = [entry["id"] for entry in entries]
        data_dir, detail_file = self.prepare_document(change)
        for item_id in ("s1", "s2", "s3"):
            with self.subTest(item=item_id):
                _code, stdout, _stderr = self.block(data_dir, [item_id],
                                                    detail_file=detail_file)
                self.assertFalse([line for line in stdout.splitlines()
                                  if re.search(r"(?i)does not exist", line)], stdout)

    def test_hklm_rollback_refuses_32_bit_shell(self):
        """#4: the HKLM rollback refuses a 32-bit shell and imports into the 64-bit view;
        the HKCU rollback is as before."""
        data_dir, detail_file = self.prepare_leftovers()
        _code, stdout, _stderr = self.block(data_dir, ["l1"], detail_file=detail_file)
        _change, rollback = self.split_rollback(stdout, REG_EXPORT)
        text = "\n".join(commands(rollback))
        self.assertIn("Is64BitProcess", text, rollback)
        self.assertRegex(text, r"(?i)\bthrow\b", rollback)
        self.assertRegex(text, r"(?i)reg(\.exe)?\s+import\b.*?/reg:64", rollback)
        _code, stdout, _stderr = self.block(data_dir, ["l2"], detail_file=detail_file)
        _change, rollback = self.split_rollback(stdout, REG_EXPORT)
        self.assertNotIn("Is64BitProcess", rollback, rollback)

    def test_registry_path_shape(self):
        """#5: only SOFTWARE\\<publisher>\\<name> (or under WOW6432Node) gets a block."""
        bad = ("HKLM\\SOFTWARE\\Microsoft", "HKLM\\SOFTWARE\\WOW6432Node",
               "HKLM\\SOFTWARE\\WOW6432Node\\Pub", "HKLM\\SOFTWARE\\Pub\\App\\Sub",
               "HKLM\\SOFTWARE\\Pub\\\\App", "HKCU\\SOFTWARE\\WOW6432Node\\Pub\\App")
        for path in bad:
            with self.subTest(path=path):
                data_dir, detail_file = self.prepare_parts([
                    leftover("l1", "PubApp", "App", "Pub", [registry_part(path, 1, 0)])])
                _code, stdout, _stderr = self.block(data_dir, ["l1"],
                                                    detail_file=detail_file)
                self.assertNotIn("Remove-Item", stdout, stdout)
                self.assertRegex(stdout, r"(?m)^#\s*l1\b.*no block", stdout)
        good = ("HKLM\\SOFTWARE\\Pub\\App", "HKLM\\SOFTWARE\\WOW6432Node\\Pub\\App",
                "HKCU\\SOFTWARE\\Pub\\App")
        for path in good:
            with self.subTest(path=path):
                data_dir, detail_file = self.prepare_parts([
                    leftover("l1", "PubApp", "App", "Pub", [registry_part(path, 1, 0)])])
                code, stdout, stderr = self.block(data_dir, ["l1"],
                                                  detail_file=detail_file)
                self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                self.assertIn("Remove-Item", stdout, stdout)


# Plan 020 M1 (K4): the export path of a leftover registry key block is written from an
# environment variable when the data dir lies under the user profile, so the expanded
# profile path (with the account name) never appears in an HKCU block. The publisher is
# "Fabrikam" so that "contoso" can only come from the invented profile path.
FABRIKAM_HKLM = "HKLM\\SOFTWARE\\Fabrikam\\Widget Pro"
FABRIKAM_HKCU = "HKCU\\SOFTWARE\\Fabrikam\\Gadget Lite"
ENV_LEFTOVERS = [
    leftover("l1", "FabrikamWidgetPro", "Widget Pro", "Fabrikam",
             [registry_part(FABRIKAM_HKLM, 3, 1)]),
    leftover("l2", "FabrikamGadgetLite", "Gadget Lite", "Fabrikam",
             [registry_part(FABRIKAM_HKCU, 2, 0)]),
]
ENV_PROFILE = r"(?i)\$env:USERPROFILE\b"
ENV_LOCAL = r"(?i)\$env:LOCALAPPDATA\b"


class TestExportPathFromEnv(LeftoverBlockTestCase):
    def prepare_env_leftovers(self):
        """The detail file lies in a temporary dir outside the invented profile."""
        def change(document):
            document["leftovers"] = json.loads(json.dumps(ENV_LEFTOVERS))
            document["listed"]["leftovers"] = [item["id"] for item in ENV_LEFTOVERS]
        _fixture_dir, detail_file = self.prepare_document(change)
        return detail_file

    def run_block(self, flag, data_dir, item_id, detail_file, environ):
        """Run ``--block`` with the data dir given by ``flag``; return (code, stdout,
        stderr, fake). An argparse error gives its exit code."""
        fake = FakePowerShell()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True):
            try:
                with redirect_stdout(out), redirect_stderr(err):
                    code = self.inventory.main(
                        [flag, str(data_dir), "--block", item_id,
                         "--detail-file", str(detail_file)],
                        run_ps=fake, is_admin=lambda: False, now=NOW)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue(), fake

    def export_prefix(self, stdout):
        """The command lines of the change part up to and including ``reg export``."""
        change, _rollback = self.split_rollback(stdout, REG_EXPORT)
        lines = commands(change)
        export = first_index(lines, REG_EXPORT)
        self.assertIsNotNone(export, change)
        return "\n".join(lines[:export + 1])

    def test_export_path_env(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        profile = root / "Users" / "contoso"
        local = profile / "AppData" / "Local"
        under_profile = profile / ".claude" / "plugins" / "data" / "ubershipshape-ubershipshape"
        under_local = local / "ubershipshape"
        elsewhere = root / "ushdata"
        for path in (under_profile, under_local, elsewhere):
            path.mkdir(parents=True)
        environ = {"USERPROFILE": str(profile), "LOCALAPPDATA": str(local),
                   "SystemRoot": "C:\\Windows"}
        detail_file = self.prepare_env_leftovers()

        cases = (
            ("under USERPROFILE", under_profile, ENV_PROFILE,
             ".claude\\plugins\\data\\ubershipshape-ubershipshape\\work"),
            ("under LOCALAPPDATA", under_local, ENV_LOCAL, "ubershipshape\\work"),
            ("elsewhere", elsewhere, None, None),
        )
        for flag in ("--data-dir", "--default-data-dir"):
            for label, data_dir, env_pattern, tail in cases:
                work = str(data_dir / "work").lower()

                with self.subTest(flag=flag, data_dir=label, key="HKCU"):
                    code, stdout, stderr, fake = self.run_block(
                        flag, data_dir, "l2", detail_file, environ)
                    self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                    self.assertEqual(fake.calls, [])
                    self.assertEqual(len(re.findall(REG_EXPORT, stdout)), 1, stdout)
                    prefix = self.export_prefix(stdout)
                    self.assertRegex(prefix, r"(?i)(HKCU|HKEY_CURRENT_USER)\\SOFTWARE"
                                             r"\\Fabrikam\\Gadget Lite", stdout)
                    if env_pattern is None:
                        self.assertIn(work, prefix.lower(), stdout)
                        self.assertNotRegex(prefix, ENV_PROFILE, stdout)
                        self.assertNotRegex(prefix, ENV_LOCAL, stdout)
                    else:
                        self.assertRegex(prefix, env_pattern, stdout)
                        self.assertIn(tail.lower(), prefix.lower(), stdout)
                        lower = stdout.lower()
                        for expanded in (str(local), str(profile), "contoso"):
                            self.assertNotIn(expanded.lower(), lower, stdout)

                with self.subTest(flag=flag, data_dir=label, key="HKLM"):
                    code, stdout, stderr, fake = self.run_block(
                        flag, data_dir, "l1", detail_file, environ)
                    self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                    self.assertEqual(fake.calls, [])
                    self.assertEqual(len(re.findall(REG_EXPORT, stdout)), 1, stdout)
                    prefix = self.export_prefix(stdout)
                    self.assertRegex(prefix, r"(?i)(HKLM|HKEY_LOCAL_MACHINE)\\SOFTWARE"
                                             r"\\Fabrikam\\Widget Pro", stdout)
                    self.assertIn(work, prefix.lower(), stdout)
                    self.assertNotRegex(stdout, ENV_PROFILE, stdout)
                    self.assertNotRegex(stdout, ENV_LOCAL, stdout)


if __name__ == "__main__":
    unittest.main()

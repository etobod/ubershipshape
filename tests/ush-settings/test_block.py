"""Paste-ready block of skills/ush-settings/scripts/settings.py (plan 050, M3).

Interface under test (see ``fakes.py`` for the full contract):

- ``--block e3,e7`` after a collect run in the same ``--data-dir``: ids are those of the
  newest detail file (found here by ``entry``). The previous state of a registry target
  comes from the detail file's ``locations``.
- stdout has up to four parts, each headed by a comment line containing
  "Run in a normal (non-elevated) Windows PowerShell", "Run in an elevated Windows
  PowerShell", "Rollback: normal" or "Rollback: elevated"; an empty part is left out.
- Normal shell: ``registry`` in HKCU and ``appx``; elevated shell: everything else.
- A new key is created only inside ``if (-not (Test-Path ...)) { New-Item -Path ... -Force
  | Out-Null }``; values are written with ``New-ItemProperty ... -Value <v> -PropertyType
  <kind> -Force`` or removed with ``Remove-ItemProperty``.
- An entry without a block gives only comments with the reason; exit 0 with at least one
  command, 1 with none or with an unknown id (message on stderr). Texts are quoted with
  ``psrun.ps_quote``.

Every value is invented; PowerShell never starts.
"""

import re
import unittest

from tests.skill_loader import load_script

from .fakes import (
    ADAPTER_1,
    ADAPTER_2,
    ANTIVIRUS_OFF,
    FakePowerShell,
    SettingsTestCase,
    absent,
    clean_registry,
    clean_responses,
    entry_location,
    firewall_rows,
    loc,
    minutes,
    ok,
    present,
    real_entries,
    registry,
    registry_entry,
    service_row,
    wifi,
)

# Checked in this order: a rollback header may also name the shell.
HEADERS = {
    "rollback_normal": "Rollback: normal",
    "rollback_elevated": "Rollback: elevated",
    "normal": "Run in a normal (non-elevated) Windows PowerShell",
    "elevated": "Run in an elevated Windows PowerShell",
}

NEW_ITEM = re.compile(r"\bNew-Item\b")

USER_LOC = loc("HKCU", "Software\\InventedVendor\\BlockUser", "InventedUserToggle",
               "preference")
MACHINE_LOC = loc("HKLM", "SOFTWARE\\InventedVendor\\BlockMachine", "InventedMachineToggle",
                  "preference")
QUOTE_LOC = loc("HKCU", "Software\\InventedVendor\\Quote", "Invented'Quote", "preference")

DWORD_0 = {"location": 0, "value": 0, "kind": "DWord"}
DWORD_1 = {"location": 0, "value": 1, "kind": "DWord"}


def split_parts(text):
    """Map part name -> text of the lines under its header comment."""
    parts, current = {}, None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            found = [name for name, header in HEADERS.items() if header in stripped]
            if found:
                current = found[0]
                parts.setdefault(current, [])
                continue
        if current is not None:
            parts[current].append(line)
    return {name: "\n".join(lines) for name, lines in parts.items()}


def commands(text):
    """Non-empty lines that are not comments."""
    return [line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


class BlockTestCase(SettingsTestCase):
    def block(self, data_dir, entry_ids, summary):
        ids = [self.detail_item(summary, entry_id).get("id") for entry_id in entry_ids]
        for entry_id, item_id in zip(entry_ids, ids):
            self.assertIsInstance(item_id, str, entry_id)
        return self.block_ids(data_dir, ids)

    def block_ids(self, data_dir, ids):
        return self.run_main(data_dir, FakePowerShell(), now=minutes(5),
                             extra=["--block", ",".join(ids)])


class TestBlock(BlockTestCase):
    def test_registry_block_and_rollback(self):
        self.write_catalogue([
            registry_entry("invented_user_toggle", [USER_LOC], expected=[0], default=1,
                           apply=DWORD_0),
            registry_entry("invented_machine_toggle", [MACHINE_LOC], expected=[1],
                           default=0, apply=DWORD_1),
        ])
        data_dir = self.data_dir()
        summary = self.collect(FakePowerShell({"registry_values": registry(
            present(USER_LOC, 1), absent(MACHINE_LOC))}), data_dir=data_dir)
        for entry_id in ("invented_user_toggle", "invented_machine_toggle"):
            self.assertEqual(self.detail_item(summary, entry_id).get("state"), "differs")

        code, stdout, stderr = self.block(
            data_dir, ["invented_user_toggle", "invented_machine_toggle"], summary)
        self.assertEqual(code, 0, stderr[:300])
        parts = split_parts(stdout)
        self.assertEqual(set(parts), set(HEADERS), stdout)

        normal = commands(parts["normal"])
        self.assertTrue(any("New-ItemProperty" in line and "InventedVendor\\BlockUser" in line
                            and "-Value 0 -PropertyType DWord" in line for line in normal),
                        parts["normal"])
        self.assertNotIn("BlockMachine", parts["normal"])

        elevated = commands(parts["elevated"])
        guards = [line for line in elevated
                  if "if (-not (Test-Path" in line and "BlockMachine" in line]
        self.assertTrue(guards, parts["elevated"])
        self.assertTrue(any(
            "New-Item -Path" in line and "-Force" in line
            and line.index("New-Item -Path") > line.index("if (-not (Test-Path")
            for line in guards), guards)
        self.assertTrue(any("New-ItemProperty" in line and "BlockMachine" in line
                            and "-Value 1 -PropertyType DWord" in line
                            for line in elevated), parts["elevated"])
        self.assertNotIn("BlockUser", parts["elevated"])

        self.assertTrue(any("New-ItemProperty" in line and "BlockUser" in line
                            and "-Value 1 -PropertyType DWord" in line
                            for line in commands(parts["rollback_normal"])),
                        parts["rollback_normal"])

        self.assertTrue(any("Remove-ItemProperty" in line and "BlockMachine" in line
                            for line in commands(parts["rollback_elevated"])),
                        parts["rollback_elevated"])
        self.assertIn("if the key was created, it stays empty", parts["rollback_elevated"])

        for line in stdout.splitlines():
            if NEW_ITEM.search(line) and "-Force" in line:
                with self.subTest(line=line):
                    self.assertIn("if (-not (Test-Path", line)
                    self.assertLess(line.index("if (-not (Test-Path"),
                                    NEW_ITEM.search(line).start())

    def test_no_block_cases(self):
        entries = real_entries()
        self.write_catalogue(entries)
        data_dir = self.data_dir()
        fake = FakePowerShell(clean_responses(entries, {
            "security_center": ok([{"display_name": "Invented Antivirus",
                                    "product_state": ANTIVIRUS_OFF}]),
            "registry_values": clean_registry(
                entries,
                present(entry_location(entries, "input_harvest_contacts"), "01",
                        kind="Binary"),
                present(entry_location(entries, "advertising_id", 0), 1),
            ),
        }))
        summary = self.collect(fake, data_dir=data_dir)
        cases = {
            "search_bing": "matches",
            "antivirus_active": "differs",
            "input_harvest_contacts": "differs",
            "advertising_id": None,
        }
        for entry_id, state in cases.items():
            item = self.detail_item(summary, entry_id)
            if state is not None:
                self.assertEqual(item.get("state"), state, item)
        self.assertEqual(self.detail_item(summary, "advertising_id").get("source"), "policy")

        for entry_id in cases:
            with self.subTest(entry=entry_id):
                code, stdout, stderr = self.block(data_dir, [entry_id], summary)
                self.assertEqual(code, 1, stdout[:500])
                self.assertTrue(stdout.strip(), "no comment with the reason")
                self.assertEqual(commands(stdout), [], stdout)
                item_id = self.detail_item(summary, entry_id).get("id")
                self.assertTrue(entry_id in stdout or item_id in stdout, stdout)
                if entry_id == "advertising_id":
                    self.assertIn("set by policy", stdout)

        with self.subTest(case="all four together"):
            code, stdout, stderr = self.block(data_dir, list(cases), summary)
            self.assertEqual(code, 1, stdout[:500])
            self.assertEqual(commands(stdout), [], stdout)
            self.assertIn("set by policy", stdout)

        with self.subTest(case="unknown id"):
            code, stdout, stderr = self.block_ids(data_dir, ["e999"])
            self.assertEqual(code, 1, stdout[:500])
            self.assertTrue(stderr.strip(), "no message on stderr for an unknown id")

        with self.subTest(case="name with an apostrophe"):
            psrun = load_script("ush-common", "psrun")
            self.write_catalogue([
                registry_entry("invented_quote", [QUOTE_LOC], expected=[0], default=1,
                               apply=DWORD_0),
            ])
            quote_dir = self.data_dir()
            summary = self.collect(FakePowerShell({"registry_values": registry(
                present(QUOTE_LOC, 1))}), data_dir=quote_dir)
            code, stdout, stderr = self.block(quote_dir, ["invented_quote"], summary)
            self.assertEqual(code, 0, stderr[:300])
            self.assertIn(psrun.ps_quote("Invented'Quote"), stdout)

    def test_typed_blocks(self):
        entries = real_entries()
        self.write_catalogue(entries)
        data_dir = self.data_dir()
        fake = FakePowerShell(clean_responses(entries, {
            "services": ok([service_row("DiagTrack", "Automatic", delayed=1)]),
            "wifi_adapter": ok([wifi(ADAPTER_1, 0),
                                wifi(ADAPTER_2, None, status="absent")]),
            "appx": ok([{"name": "Microsoft.Copilot", "status": "present"}]),
        }))
        summary = self.collect(fake, data_dir=data_dir)
        service = self.detail_item(summary, "diagtrack_service")
        self.assertEqual(service.get("effective"), "AutomaticDelayed", service)

        with self.subTest(case="service"):
            code, stdout, stderr = self.block(data_dir, ["diagtrack_service"], summary)
            self.assertEqual(code, 0, stderr[:300])
            parts = split_parts(stdout)
            self.assertTrue(any("Set-Service" in line and "DiagTrack" in line
                                for line in commands(parts.get("elevated", ""))), stdout)
            self.assertIn("sc.exe config DiagTrack start= delayed-auto",
                          parts.get("rollback_elevated", ""))

        with self.subTest(case="Wi-Fi, two adapters"):
            code, stdout, stderr = self.block(data_dir, ["wifi_power_management"], summary)
            self.assertEqual(code, 0, stderr[:300])
            parts = split_parts(stdout)
            writes = [line for line in commands(parts.get("elevated", ""))
                      if "New-ItemProperty" in line]
            self.assertEqual(len(writes), 2, parts.get("elevated"))
            for adapter in (ADAPTER_1, ADAPTER_2):
                self.assertEqual(sum(adapter in line for line in writes), 1, writes)
                self.assertIn("Control\\Class\\" + adapter, parts["elevated"])

        with self.subTest(case="appx"):
            code, stdout, stderr = self.block(data_dir, ["copilot_app"], summary)
            self.assertEqual(code, 0, stderr[:300])
            parts = split_parts(stdout)
            self.assertTrue(any("Remove-AppxPackage" in line
                                for line in commands(parts.get("normal", ""))), stdout)
            for name in ("rollback_normal", "rollback_elevated"):
                self.assertEqual(commands(parts.get(name, "")), [], stdout)
            self.assertIn("Install Microsoft Copilot again from the Microsoft Store.", stdout)


class TestFirewallBlock(BlockTestCase):
    def test_policy_decided_firewall_gives_no_block(self):
        # The block writes the local setting; when a policy decides the effective state,
        # the change would not take effect and the rollback would write the policy's value.
        entries = real_entries()
        self.write_catalogue(entries)
        data_dir = self.data_dir()
        cases = {"policy decides": (True, 1), "local not read": (None, 1),
                 "local decides": (False, 0)}
        for case, (local, expected_code) in cases.items():
            with self.subTest(case=case):
                fake = FakePowerShell(clean_responses(entries, {
                    "firewall": ok(firewall_rows(False, local=local)),
                }))
                summary = self.collect(fake, data_dir=data_dir)
                item = self.detail_item(summary, "firewall_public")
                self.assertIs(item.get("effective"), False, item)
                self.assertIn("local_enabled", item, item)
                code, stdout, _stderr = self.block(data_dir, ["firewall_public"], summary)
                self.assertEqual(code, expected_code, stdout[:500])
                if expected_code:
                    self.assertEqual(commands(stdout), [], stdout)
                else:
                    parts = split_parts(stdout)
                    self.assertIn("-Enabled True", parts.get("elevated", ""))
                    self.assertIn("-Enabled False", parts.get("rollback_elevated", ""))

    def firewall_block(self, rows):
        """Collect with ``rows`` as the firewall answer, then ask for firewall_public."""
        entries = real_entries()
        self.write_catalogue(entries)
        data_dir = self.data_dir()
        fake = FakePowerShell(clean_responses(entries, {"firewall": ok(rows)}))
        summary = self.collect(fake, data_dir=data_dir)
        item = self.detail_item(summary, "firewall_public")
        self.assertIs(item.get("effective"), False, item)
        code, stdout, _stderr = self.block(data_dir, ["firewall_public"], summary)
        return item, code, stdout

    def test_policy_equal_to_local_gives_no_block(self):
        # Local equal to effective does not prove the local setting decides: a policy
        # with the same value would keep the firewall off after the local change.
        _item, code, stdout = self.firewall_block(
            firewall_rows(False, local=False, policy_read=True, policy="False"))
        self.assertEqual(code, 1, stdout[:500])
        self.assertEqual(commands(stdout), [], stdout)
        self.assertIn("policy", stdout.lower())

    def test_policy_not_read_gives_no_block(self):
        _item, code, stdout = self.firewall_block(
            firewall_rows(False, local=False, policy_read=False, policy=None))
        self.assertEqual(code, 1, stdout[:500])
        self.assertEqual(commands(stdout), [], stdout)

    def test_no_policy_keeps_block(self):
        # RSOP read without the profile: no policy, so the local setting decides.
        item, code, stdout = self.firewall_block(
            firewall_rows(False, local=False, policy_read=True, policy=None))
        self.assertEqual(item.get("policy_enabled"), "NotConfigured", item)
        self.assertEqual(code, 0, stdout[:500])
        parts = split_parts(stdout)
        self.assertIn("-Enabled True", parts.get("elevated", ""))
        # The rollback restores the local value (False).
        self.assertIn("-Enabled False", parts.get("rollback_elevated", ""))


class TestQuotedRollback(BlockTestCase):
    def test_curly_quote_in_previous_value_gives_no_block(self):
        # Windows PowerShell also ends a single-quoted string at U+2018..U+201B.
        url_loc = loc("HKCU", "Software\\InventedVendor\\Url", "InventedUrl", "preference")
        self.write_catalogue([
            registry_entry("invented_url", [url_loc], expected=[""], default="",
                           apply={"location": 0, "remove": True}),
        ])
        data_dir = self.data_dir()
        for quote in ("‘", "’", "‚", "‛"):
            with self.subTest(quote=hex(ord(quote))):
                value = f"http://invented.example/{quote}; Start-Process calc; {quote}"
                summary = self.collect(FakePowerShell({"registry_values": registry(
                    present(url_loc, value, kind="String"))}), data_dir=data_dir)
                code, stdout, _stderr = self.block(data_dir, ["invented_url"], summary)
                self.assertEqual(code, 1, stdout[:500])
                self.assertEqual(commands(stdout), [], stdout)
                self.assertNotIn("Start-Process", stdout)


class TestElevatedDetail(BlockTestCase):
    """HKCU read in an elevated run may be another account's hive: no HKCU commands."""

    def test_hkcu_block_refused_after_elevated_run(self):
        self.write_catalogue([
            registry_entry("invented_user_toggle", [USER_LOC], expected=[0], default=1,
                           apply=DWORD_0),
            registry_entry("invented_machine_toggle", [MACHINE_LOC], expected=[1],
                           default=0, apply=DWORD_1),
        ])
        data_dir = self.data_dir()
        fake = FakePowerShell({"registry_values": registry(
            present(USER_LOC, 1), absent(MACHINE_LOC))})
        summary = self.collect(fake, data_dir=data_dir, admin=True)
        self.assertIs(self.detail_item(summary, "invented_user_toggle")
                      .get("hkcu_elevated"), True)

        with self.subTest(case="HKCU alone"):
            code, stdout, stderr = self.block(data_dir, ["invented_user_toggle"], summary)
            self.assertEqual(code, 1, stdout[:500])
            self.assertEqual(commands(stdout), [], stdout)
            self.assertNotIn("BlockUser", "\n".join(commands(stdout)))
            self.assertIn("elevated run", stdout)

        with self.subTest(case="HKCU with HKLM"):
            code, stdout, stderr = self.block(
                data_dir, ["invented_user_toggle", "invented_machine_toggle"], summary)
            self.assertEqual(code, 0, stderr[:300])
            parts = split_parts(stdout)
            self.assertNotIn("normal", parts, stdout)
            self.assertNotIn("rollback_normal", parts, stdout)
            self.assertNotIn("BlockUser", "\n".join(commands(stdout)))
            self.assertIn("BlockMachine", parts.get("elevated", ""))

    def test_appx_is_per_user_in_elevated_run(self):
        entries = real_entries()
        self.write_catalogue(entries)
        data_dir = self.data_dir()
        fake = FakePowerShell(clean_responses(entries, {
            "appx": ok([{"name": "Microsoft.Copilot", "status": "present"}]),
        }))
        summary = self.collect(fake, data_dir=data_dir, admin=True)
        item = self.detail_item(summary, "copilot_app")
        self.assertIs(item.get("hkcu_elevated"), True, item)

        code, stdout, _stderr = self.block(data_dir, ["copilot_app"], summary)
        self.assertEqual(code, 1, stdout[:500])
        self.assertEqual(commands(stdout), [], stdout)
        self.assertIn("elevated run", stdout)


if __name__ == "__main__":
    unittest.main()

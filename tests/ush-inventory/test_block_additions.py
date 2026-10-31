"""Guards of the ``--block`` printer for additions and components (plan 005, M2).

Each guard has a no-block test and, beside it, a clean-data test that keeps the block, so
a guard that fires too widely fails here (a false "no block" hides a valid change).

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from .fakes import NOW, FakePowerShell
from .test_block import (
    CAPABILITY_ITEM,
    CURRENT_ADMIN,
    DEFENDER_ITEM,
    FEATURE_ITEM,
    HOSTS_ITEM,
    LOCAL_RULE,
    MACHINE_CERT,
    OTHER_ADMIN,
    USER_CERT,
    AdditionBlockTestCase,
    commands,
    comments,
)

INVENTED_PROFILE = "C:\\Users\\InventedPerson"


def with_changes(base, **changes):
    result = dict(base)
    result.update(changes)
    return result


class AdditionGuardTestCase(AdditionBlockTestCase):
    def prepare_edited(self, edit, elevated=False):
        """A detail file of ``additions_document`` changed by ``edit(document)``."""
        data_dir, detail_file = self.prepare_additions(elevated=elevated)
        document = json.loads(detail_file.read_text(encoding="utf-8"))
        edit(document)
        detail_file.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return data_dir, detail_file

    def replace_item(self, document, item_id, item):
        for section in ("additions", "components"):
            document[section] = [item if entry["id"] == item_id else entry
                                 for entry in document[section]]

    def assert_no_block(self, data_dir, detail_file, item_id, reason=None):
        _code, stdout, _stderr = self.block(data_dir, [item_id], detail_file=detail_file)
        self.assertEqual(commands(stdout), [], stdout)
        line = self.assert_no_block_line(stdout, item_id)
        if reason is not None:
            self.assertRegex(line, reason, line)
        return line

    def assert_block(self, data_dir, detail_file, item_id, pattern):
        code, stdout, stderr = self.block(data_dir, [item_id], detail_file=detail_file)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        self.assertTrue(any(re.search(pattern, line) for line in commands(stdout)), stdout)
        return stdout


class TestFirewallGuards(AdditionGuardTestCase):
    def test_wildcard_rule_name_gets_no_block(self):
        rule = with_changes(LOCAL_RULE, key="firewall:local:Invented*Rule")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x1", rule))
        self.assert_no_block(data_dir, detail_file, "x1", r"wildcard")

    def test_quote_in_rule_name_is_doubled(self):
        rule = with_changes(LOCAL_RULE, key="firewall:local:Invented'Rule")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x1", rule))
        stdout = self.assert_block(data_dir, detail_file, "x1",
                                   r"^Disable-NetFirewallRule -Name 'Invented''Rule'$")
        self.assertIn("Enable-NetFirewallRule -Name 'Invented''Rule'", stdout)

    def test_control_character_in_rule_name_gets_no_block(self):
        rule = with_changes(LOCAL_RULE, key="firewall:local:Invented\tRule")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x1", rule))
        self.assert_no_block(data_dir, detail_file, "x1", r"control character")

    def test_disabled_or_unknown_active_gets_no_block(self):
        for active, reason in (("FALSE", r"already disabled"), (None, r"active")):
            with self.subTest(active=active):
                rule = with_changes(LOCAL_RULE, active=active)
                data_dir, detail_file = self.prepare_edited(
                    lambda d, rule=rule: self.replace_item(d, "x1", rule))
                self.assert_no_block(data_dir, detail_file, "x1", reason)

    def test_unread_source_gets_no_block(self):
        def edit(document):
            for source in document["sources"]:
                if source["name"] == "firewall_rules":
                    source.update(status="unreadable", reason="invented failure")
        data_dir, detail_file = self.prepare_edited(edit)
        self.assert_no_block(data_dir, detail_file, "x1", r"firewall_rules was not read")

    def test_rule_from_baseline_gets_no_block(self):
        rule = with_changes(LOCAL_RULE, from_baseline=True)
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x1", rule))
        self.assert_no_block(data_dir, detail_file, "x1", r"from_baseline")


class TestCertificateGuards(AdditionGuardTestCase):
    def test_thumbprint_in_another_store_gets_no_block(self):
        # No no_block_reason on the item: the printer finds the copy itself.
        copy = with_changes(MACHINE_CERT, id="x20", store="authroot",
                            key=f"cert:authroot:{MACHINE_CERT['thumbprint']}", own=True)
        data_dir, detail_file = self.prepare_edited(
            lambda d: d["additions"].append(copy))
        self.assert_no_block(data_dir, detail_file, "x4", r"authroot")

    def test_in_authroot_gets_no_block(self):
        cert = with_changes(MACHINE_CERT, in_authroot=True)
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x4", cert))
        self.assert_no_block(data_dir, detail_file, "x4", r"authroot")

    def test_user_root_of_an_elevated_run_gets_no_block(self):
        def edit(document):
            document["additions"] += [dict(MACHINE_CERT), dict(USER_CERT)]
        data_dir, detail_file = self.prepare_edited(edit, elevated=True)
        self.assert_no_block(data_dir, detail_file, "x5", r"elevated")
        # Clean data: a machine root of the same elevated run keeps its block.
        self.assert_block(data_dir, detail_file, "x4", r"Export-Certificate")

    def test_export_drops_store_properties_is_said(self):
        data_dir, detail_file = self.prepare_additions()
        change, rollback = self.printed_block(data_dir, detail_file, "x4",
                                              r"Export-Certificate", elevated=True)
        for part in (change, rollback):
            self.assertTrue(any("friendly name" in line and "all its purposes" in line
                                for line in comments(part)), part)

    def test_null_or_missing_own_store_gets_no_block(self):
        for case in ("null", "missing"):
            with self.subTest(store=case):
                cert = with_changes(MACHINE_CERT, store=None)
                if case == "missing":
                    del cert["store"]
                data_dir, detail_file = self.prepare_edited(
                    lambda d, c=cert: self.replace_item(d, "x4", c))
                self.assert_no_block(data_dir, detail_file, "x4", r"store is null or missing")

    def test_copy_with_null_store_is_not_another_store(self):
        # Clean data: a copy whose store is null names no store, so x4 keeps its block.
        copy = with_changes(MACHINE_CERT, id="x20", store=None)
        data_dir, detail_file = self.prepare_edited(lambda d: d["additions"].append(copy))
        self.assert_block(data_dir, detail_file, "x4", r"Export-Certificate")

    def test_null_store_beside_a_real_copy_does_not_break_the_sort(self):
        thumb = MACHINE_CERT["thumbprint"]
        null_copy = with_changes(MACHINE_CERT, id="x20", store=None)
        real_copy = with_changes(MACHINE_CERT, id="x21", store="authroot",
                                 key=f"cert:authroot:{thumb}", own=True)
        data_dir, detail_file = self.prepare_edited(
            lambda d: d["additions"].extend([null_copy, real_copy]))
        try:
            line = self.assert_no_block(data_dir, detail_file, "x4", r"authroot")
        except TypeError as exc:
            self.fail(f"the printer raised {exc!r}")
        self.assertNotIn("None", line)

    def test_bad_thumbprint_gets_no_block(self):
        cert = with_changes(MACHINE_CERT, thumbprint="0123*", key="cert:machine_root:0123*")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x4", cert))
        self.assert_no_block(data_dir, detail_file, "x4", r"thumbprint")


class TestHostsGuards(AdditionGuardTestCase):
    def test_hosts_file_not_known_to_exist_gets_no_block(self):
        for hosts_file in ({"exists": None, "path_is_default": None,
                            "unread_fields": ["exists", "path_is_default"]}, None):
            with self.subTest(hosts_file=hosts_file):
                data_dir, detail_file = self.prepare_edited(
                    lambda d, h=hosts_file: d.update(hosts_file=h))
                self.assert_no_block(data_dir, detail_file, "x6", r"hosts file")

    def test_no_data_dir_gets_no_block_for_a_backup(self):
        _data_dir, detail_file = self.prepare_additions()
        environ = {k: v for k, v in os.environ.items()
                   if k not in ("USH_DATA_DIR", "LOCALAPPDATA")}
        with mock.patch.dict(os.environ, environ, clear=True):
            code, stdout, _stderr = self.block_without_data_dir(["x6", "x4", "x1"],
                                                                detail_file)
        self.assertEqual(code, 0, stdout)
        for item_id in ("x6", "x4"):
            line = self.assert_no_block_line(stdout, item_id)
            self.assertIn("data directory", line)
        # Clean data: a block that needs no backup is still printed.
        self.assertTrue(any("Disable-NetFirewallRule" in line for line in commands(stdout)),
                        stdout)

    def block_without_data_dir(self, ids, detail_file):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.inventory.main(
                ["--block", ",".join(ids), "--detail-file", str(detail_file)],
                run_ps=FakePowerShell(), is_admin=lambda: False, now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_two_hosts_blocks_get_two_backups(self):
        second = with_changes(HOSTS_ITEM, id="x21", hostname="cdn.invented.example",
                              key="hosts:cdn.invented.example:0.0.0.0", line=24)
        data_dir, detail_file = self.prepare_edited(
            lambda d: d["additions"].append(second))
        code, stdout, stderr = self.block(data_dir, ["x6", "x21"], detail_file=detail_file)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        backups = re.findall(r"(?m)^\s*\$backup = '([^']*)'$", stdout)
        self.assertEqual(len(backups), 2, stdout)
        self.assertNotEqual(backups[0], backups[1])

    def test_space_in_host_name_gets_no_block(self):
        item = with_changes(HOSTS_ITEM, hostname="ads invented",
                            key="hosts:ads invented:0.0.0.0")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x6", item))
        self.assert_no_block(data_dir, detail_file, "x6", r"space")

    def test_non_ascii_host_name_gets_no_block(self):
        name = "ads.invent\u00e9d.example"
        item = with_changes(HOSTS_ITEM, hostname=name, key=f"hosts:{name}:0.0.0.0")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x6", item))
        self.assert_no_block(data_dir, detail_file, "x6", r"not ASCII")


class TestAdministratorGuards(AdditionGuardTestCase):
    def test_a_member_with_unknown_enabled_stops_every_removal(self):
        current = with_changes(CURRENT_ADMIN, enabled=None)
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x8", current))
        self.assert_no_block(data_dir, detail_file, "x7", r"enabled null")

    def test_last_enabled_member_gets_no_block(self):
        current = with_changes(CURRENT_ADMIN, enabled=False)
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x8", current))
        self.assert_no_block(data_dir, detail_file, "x7", r"no member with enabled true")

    def test_unknown_is_current_gets_no_block(self):
        other = with_changes(OTHER_ADMIN, is_current=None, unread_fields=["is_current"])
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x7", other))
        self.assert_no_block(data_dir, detail_file, "x7", r"is_current")

    def test_enabled_member_that_is_not_current_does_not_count(self):
        # Two blocks could remove x7 and x22 and leave no enabled member.
        current = with_changes(CURRENT_ADMIN, enabled=False)
        third = with_changes(OTHER_ADMIN, id="x22", key="admin:S-1-5-21-0-0-0-1003",
                             name="InventedThird")

        def edit(document):
            self.replace_item(document, "x8", current)
            document["additions"].append(third)
        data_dir, detail_file = self.prepare_edited(edit)
        for item_id in ("x7", "x22"):
            with self.subTest(item_id=item_id):
                self.assert_no_block(data_dir, detail_file, item_id, r"is_current true")

    def test_current_member_from_baseline_does_not_count(self):
        current = with_changes(CURRENT_ADMIN, from_baseline=True)
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x8", current))
        self.assert_no_block(data_dir, detail_file, "x7", r"read in this run")

    def test_enabled_current_member_keeps_the_other_block(self):
        # Clean data: x8 (enabled, is_current, read in this run) stays; a member from the
        # baseline with enabled null is not counted, so it does not stop the block.
        old = with_changes(OTHER_ADMIN, id="x23", key="admin:S-1-5-21-0-0-0-1004",
                           name="InventedOld", enabled=None, from_baseline=True)
        data_dir, detail_file = self.prepare_edited(lambda d: d["additions"].append(old))
        self.assert_block(data_dir, detail_file, "x7",
                          r"^Remove-LocalGroupMember -SID 'S-1-5-32-544' -Member "
                          r"'S-1-5-21-0-0-0-1002'$")

    def test_member_name_is_not_printed(self):
        data_dir, detail_file = self.prepare_additions()
        stdout = self.assert_block(data_dir, detail_file, "x7", r"Remove-LocalGroupMember")
        self.assertNotIn(OTHER_ADMIN["name"], stdout)


class TestDefenderGuards(AdditionGuardTestCase):
    def test_method_registry_gets_no_block(self):
        def edit(document):
            for source in document["sources"]:
                if source["name"] == "defender_exclusions":
                    source["method"] = "registry"
        data_dir, detail_file = self.prepare_edited(edit, elevated=True)
        self.assert_no_block(data_dir, detail_file, "x9", r"preference")

    def test_policy_origin_gets_no_block(self):
        item = with_changes(DEFENDER_ITEM, origin="policy")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x9", item), elevated=True)
        self.assert_no_block(data_dir, detail_file, "x9", r"origin")

    def test_profile_path_is_built_from_userprofile(self):
        value = INVENTED_PROFILE + "\\InventedCache"
        item = with_changes(DEFENDER_ITEM, value=value,
                            key=f"defender:path:{value.lower()}")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x9", item), elevated=True)
        with mock.patch.dict(os.environ, {"USERPROFILE": INVENTED_PROFILE}):
            stdout = self.assert_block(
                data_dir, detail_file, "x9",
                r"^Remove-MpPreference -ExclusionPath \(\$env:USERPROFILE \+ "
                r"'\\InventedCache'\)$")
        self.assertNotIn("InventedPerson", stdout)
        self.assertIn("Add-MpPreference -ExclusionPath ($env:USERPROFILE + "
                      "'\\InventedCache')", stdout)

    def test_other_profile_gets_no_block(self):
        value = "C:\\Users\\InventedOther\\cache"
        item = with_changes(DEFENDER_ITEM, value=value,
                            key=f"defender:path:{value.lower()}")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "x9", item), elevated=True)
        with mock.patch.dict(os.environ, {"USERPROFILE": INVENTED_PROFILE}):
            self.assert_no_block(data_dir, detail_file, "x9", r"another account")


class TestComponentGuards(AdditionGuardTestCase):
    def test_disabled_feature_gets_no_block(self):
        item = with_changes(FEATURE_ITEM, state="disabled")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "f1", item))
        self.assert_no_block(data_dir, detail_file, "f1", r"state")

    def test_dependent_features_are_named(self):
        data_dir, detail_file = self.prepare_additions(elevated=True)
        change, _rollback = self.printed_block(
            data_dir, detail_file, "f1", r"Disable-WindowsOptionalFeature", elevated=True)
        self.assertTrue(any("depend on this one are disabled too" in line
                            and "enables only this one" in line
                            for line in comments(change)), change)

    def test_wildcard_feature_name_gets_no_block(self):
        item = with_changes(FEATURE_ITEM, name="Invented-*", key="feature:Invented-*")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "f1", item))
        self.assert_no_block(data_dir, detail_file, "f1", r"wildcard")

    def test_capability_of_an_unread_source_gets_no_block(self):
        # The non-elevated detail file marks capabilities unreadable.
        data_dir, detail_file = self.prepare_edited(
            lambda d: d["components"].append(dict(CAPABILITY_ITEM)))
        self.assert_no_block(data_dir, detail_file, "f2", r"capabilities was not read")

    def test_not_installed_capability_gets_no_block(self):
        item = with_changes(CAPABILITY_ITEM, state="NotPresent")
        data_dir, detail_file = self.prepare_edited(
            lambda d: self.replace_item(d, "f2", item), elevated=True)
        self.assert_no_block(data_dir, detail_file, "f2", r"Installed")


class TestSeveralIds(AdditionGuardTestCase):
    def test_no_block_and_blocks_keep_their_order(self):
        data_dir, detail_file = self.prepare_additions()
        code, stdout, stderr = self.block(data_dir, ["d1", "x7", "x2", "x7", "f1"],
                                          detail_file=detail_file)
        self.assertEqual(code, 0, stderr[:300] or stdout[:300])
        heads = re.findall(r"(?m)^# (d1|x7|x2|f1):", stdout)
        self.assertEqual(heads, ["d1", "x7", "x2", "f1"], stdout)


if __name__ == "__main__":
    unittest.main()

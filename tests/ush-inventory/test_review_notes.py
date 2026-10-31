"""Review notes on ush-inventory (plan 107, milestone M2, criteria K4 and K5): whether the
program file of a firewall rule exists, why an addition has no change block, the built-in
Administrator account and the driver rows without an INF file.

The general interface is described in ``fakes.py``, ``fakes_components.py`` and
``fakes_additions.py``. Assumptions added here beyond the plan text:

- The ``firewall_apps`` job answers rows ``{app, expanded, exists}``; ``app`` is the raw
  ``App`` value of a rule and the match key. Every test that has rules with ``App`` gives
  the ``firewall_apps`` answer explicitly.
- The task script checked is the script the fake received for the job ``firewall_apps``
  (the body after ``__INPUT__`` is replaced), so no module constant name is assumed.
- A ``not_checked`` item about the job names ``firewall_apps`` in ``what`` or ``reason``.
- ``drivers_without_inf_items`` is a top-level key of the detail file;
  ``drivers_without_inf`` stays in ``component_counts`` of the summary.
- ``builtin`` is read from the summary ``additions`` items of kind ``administrator``.

PowerShell never starts; every value is invented.
"""

import json
import unittest

from tests.skill_loader import REPO_ROOT

from .fakes import FakePowerShell, failure, ok
from .fakes_additions import (
    AdditionsTestCase,
    admins_result,
    cert,
    certificates_result,
    custom_rule,
    defender_result,
    firewall_result,
    fw_value,
    m2_responses,
    member,
    rule_text,
    thumb,
)
from .fakes_components import driver

SKILL_DIR = REPO_ROOT / "skills" / "ush-inventory"

APP_PRESENT = "C:\\Invented\\Present\\present.exe"
APP_GONE = "C:\\Invented\\Gone\\gone.exe"
APP_DENIED = ("C:\\Program Files\\WindowsApps\\Invented.App_1.0.0.0_x64__abc1def2\\"
              "invented.exe")
APP_UNKNOWN_VAR = "%NIEZNANA%\\a.exe"
APP_NO_ROW = "C:\\Invented\\NoRow\\norow.exe"
APP_SVCHOST = "%SystemRoot%\\system32\\svchost.exe"
SVCHOST_EXPANDED = "C:\\Windows\\system32\\svchost.exe"


def rule_name(n):
    return f"{{00000000-0000-0000-0000-0000000E{n:04d}}}"


def firewall_key(store, name):
    return f"firewall:{store}:{name}"


def cert_key(store, thumbprint):
    return f"cert:{store}:{thumbprint}"


def app_row(app, expanded, exists):
    """One row of the ``firewall_apps`` job."""
    return {"app": app, "expanded": expanded, "exists": exists}


def plain_rule(name, version="v2.33"):
    """A rule without ``App`` and without ``EmbedCtxt`` (so not own)."""
    return rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "In"),
                      ("Protocol", "6"), ("LPort", "7070"), ("Name", name)], version=version)


def two_app_rule(name):
    """A rule with the ``App`` key twice: the parsed ``app`` is a list."""
    return rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "In"),
                      ("Protocol", "6"), ("LPort", "9090"),
                      ("App", "C:\\Invented\\Twin\\one.exe"),
                      ("App", "C:\\Invented\\Twin\\two.exe"), ("Name", name)])


def flat(text):
    """Text with every run of whitespace as one space, lowercase."""
    return " ".join(text.split()).lower()


class TestReviewNotes(AdditionsTestCase):
    def listed(self, summary, kind):
        """Summary ``additions`` of one kind, by key."""
        return self.by_key(self.additions_of(summary, kind))

    def item(self, listed, key):
        item = listed.get(key)
        self.assertIsNotNone(item, f"{key} not in summary additions: {sorted(map(str, listed))}")
        return item

    def assert_app_exists(self, item, value):
        self.assertIn("app_exists", item, item)
        if value is None:
            self.assertIsNone(item.get("app_exists"), item)
            self.assertIn("app_exists", item.get("unread_fields") or [], item)
        else:
            self.assertIs(item.get("app_exists"), value, item)

    def firewall_apps_notes(self, summary):
        return [n for n in self.not_checked(summary)
                if "firewall_apps" in f"{n.get('what')} {n.get('reason')}"]

    def test_firewall_app_exists_and_no_block_reason(self):
        names = {label: rule_name(n) for n, label in enumerate((
            "present", "gone", "denied", "unknown_var", "no_row", "svchost", "no_app",
            "system", "two_apps", "app_iso", "policy"), 1)}
        firewall = firewall_result(
            local=[
                fw_value(names["present"], custom_rule("Invented Present", app=APP_PRESENT)),
                fw_value(names["gone"], custom_rule("Invented Gone", app=APP_GONE)),
                fw_value(names["denied"], custom_rule("Invented Denied", app=APP_DENIED)),
                fw_value(names["unknown_var"],
                         custom_rule("Invented Unknown Variable", app=APP_UNKNOWN_VAR)),
                fw_value(names["no_row"], custom_rule("Invented No Row", app=APP_NO_ROW)),
                fw_value(names["svchost"], custom_rule("Invented Svchost", app=APP_SVCHOST)),
                fw_value(names["no_app"], plain_rule("Invented No App")),
                fw_value(names["system"], custom_rule("Invented System", app="System")),
                fw_value(names["two_apps"], two_app_rule("Invented Two Apps")),
            ],
            app_iso=[fw_value(names["app_iso"],
                              plain_rule("Invented Store App Rule", version="v2.31"))],
            policy=[fw_value(names["policy"], plain_rule("Invented Policy Rule"))],
        )
        app_rows = [
            app_row(APP_PRESENT, APP_PRESENT, True),
            app_row(APP_GONE, APP_GONE, False),
            app_row(APP_DENIED, APP_DENIED, None),
            app_row(APP_UNKNOWN_VAR, APP_UNKNOWN_VAR, None),
            app_row(APP_SVCHOST, SVCHOST_EXPANDED, True),
        ]
        blocked, other_store, in_authroot, several = (thumb(0xE01), thumb(0xE02),
                                                      thumb(0xE03), thumb(0xE04))
        certificates = certificates_result(
            machine_root=[cert(blocked, subject="CN=Invented Blocked Root"),
                          cert(in_authroot, subject="CN=Invented AuthRoot Twin"),
                          cert(several, subject="CN=Invented Two Store Root")],
            enterprise=[cert(other_store, subject="CN=Invented Enterprise Root")],
            user_root=[cert(several, subject="CN=Invented Two Store Root")],
            authroot=[cert(in_authroot, subject="CN=Invented AuthRoot Twin")],
        )
        admin_sid = "S-1-5-21-0-0-0-1002"
        # Read from the registry: the policy value has a non-local origin, the other
        # one is local but read by another method than preference.
        defender = defender_result(
            method="registry", path=["C:\\Invented\\Local", "C:\\Invented\\Policy"],
            policy={"path": ["C:\\Invented\\Policy"], "extension": [], "process": [],
                    "ip": []})
        fake = FakePowerShell(m2_responses(
            firewall_rules=ok(firewall),
            firewall_apps=ok(app_rows),
            root_certificates=ok(certificates),
            administrators=ok(admins_result([member(admin_sid, "EXAMPLE-PC\\InventedTwo")])),
            defender_exclusions=ok(defender),
        ))
        code, stdout, stderr = self.run_main(self.data_dir(), fake, admin=True)
        summary = self.parse(stdout)
        rules = self.listed(summary, "firewall_rule")

        def local(label):
            return self.item(rules, firewall_key("local", names[label]))

        with self.subTest(point="App that exists gives true"):
            self.assert_app_exists(local("present"), True)
        with self.subTest(point="App that does not exist gives false"):
            self.assert_app_exists(local("gone"), False)
        with self.subTest(point="access denied (exists null) gives null and unread"):
            self.assert_app_exists(local("denied"), None)
        with self.subTest(point="expanded still with % gives null"):
            self.assert_app_exists(local("unknown_var"), None)
        with self.subTest(point="App without a row in the job result gives null"):
            self.assert_app_exists(local("no_row"), None)
        with self.subTest(point="clean data: %SystemRoot% svchost gives true, no unread"):
            item = local("svchost")
            self.assert_app_exists(item, True)
            self.assertFalse(item.get("unread_fields"), item)
        with self.subTest(point="rule without App has no app_exists"):
            self.assertNotIn("app_exists", local("no_app"))
        with self.subTest(point="rule with App System has no app_exists"):
            self.assertNotIn("app_exists", local("system"))
        with self.subTest(point="rule with two App keys gives null, unread, exit 0"):
            self.assertEqual(code, 0, stderr[:300])
            self.assert_app_exists(local("two_apps"), None)

        with self.subTest(point="no_block_reason store_app_iso"):
            item = self.item(rules, firewall_key("app_iso", names["app_iso"]))
            self.assertEqual(item.get("no_block_reason"), "store_app_iso", item)
        with self.subTest(point="no_block_reason store_policy"):
            item = self.item(rules, firewall_key("policy", names["policy"]))
            self.assertEqual(item.get("no_block_reason"), "store_policy", item)

        certs = self.listed(summary, "root_certificate")
        with self.subTest(point="no_block_reason cert_other_store"):
            item = self.item(certs, cert_key("enterprise", other_store))
            self.assertEqual(item.get("no_block_reason"), "cert_other_store", item)
        with self.subTest(point="no_block_reason cert_in_authroot"):
            item = self.item(certs, cert_key("machine_root", in_authroot))
            self.assertEqual(item.get("no_block_reason"), "cert_in_authroot", item)
        with self.subTest(point="no_block_reason cert_in_several_stores"):
            for store in ("machine_root", "user_root"):
                item = self.item(certs, cert_key(store, several))
                self.assertEqual(item.get("no_block_reason"), "cert_in_several_stores", item)

        exclusions = self.listed(summary, "defender_exclusion")
        with self.subTest(point="no_block_reason defender_origin"):
            item = self.item(exclusions, "defender:path:c:\\invented\\policy")
            self.assertEqual(item.get("no_block_reason"), "defender_origin", item)
        with self.subTest(point="no_block_reason defender_method"):
            item = self.item(exclusions, "defender:path:c:\\invented\\local")
            self.assertEqual(item.get("no_block_reason"), "defender_method", item)

        with self.subTest(point="rules in local have no no_block_reason"):
            local_rules = [i for i in rules.values() if i.get("store") == "local"]
            self.assertTrue(local_rules, rules)
            for item in local_rules:
                self.assertNotIn("no_block_reason", item)
        with self.subTest(point="certificate with a block has no no_block_reason"):
            self.assertNotIn("no_block_reason",
                             self.item(certs, cert_key("machine_root", blocked)))
        with self.subTest(point="Administrators member has no no_block_reason"):
            admins = self.listed(summary, "administrator")
            self.assertNotIn("no_block_reason", self.item(admins, f"admin:{admin_sid}"))

        with self.subTest(point="task script contains ItemNotFoundException"):
            scripts = [script for job, script, _ in fake.calls if job == "firewall_apps"]
            self.assertTrue(scripts, fake.jobs())
            for script in scripts:
                self.assertIn("ItemNotFoundException", script)

        with self.subTest(point="not found is confirmed by the parent folder; access denied there is null"):
            for script in scripts:
                self.assertIn("GetFileSystemEntries", script)
                self.assertIn("DirectoryNotFoundException", script)

        with self.subTest(point="only local drives are checked, never UNC or network drives"):
            for script in scripts:
                self.assertIn("DriveType", script)
                self.assertNotIn("IsPathRooted", script)

        two_programs = firewall_result(local=[
            fw_value(rule_name(101), custom_rule("Invented Present", app=APP_PRESENT)),
            fw_value(rule_name(102), custom_rule("Invented Gone", app=APP_GONE)),
        ])
        for point, answer in (
                ("empty result for two programs gives null and not_checked", ok([])),
                ("failed job gives null and not_checked",
                 failure("Invented: the firewall_apps job failed"))):
            with self.subTest(point=point):
                summary = self.collect(FakePowerShell(m2_responses(
                    firewall_rules=ok(two_programs), firewall_apps=answer)))
                rules = self.listed(summary, "firewall_rule")
                for n in (101, 102):
                    self.assert_app_exists(
                        self.item(rules, firewall_key("local", rule_name(n))), None)
                self.assertTrue(self.firewall_apps_notes(summary),
                                summary.get("not_checked"))

    def test_builtin_account_and_devices_without_inf(self):
        builtin_sid = "S-1-5-21-1-2-3-500"
        user_sid = "S-1-5-21-1-2-3-1001"
        group_sid = "S-1-5-32-544"
        members = [
            member(builtin_sid, "EXAMPLE-PC\\InventedAdmin", enabled=False),
            member(user_sid, "EXAMPLE-PC\\invented.user"),
            member(group_sid, "BUILTIN\\Invented Group", object_class="Group",
                   principal_source=None, enabled=None, is_user=False),
        ]
        no_inf_ids = ("ROOT\\INVENTED\\0001", "SWD\\INVENTED\\0002")
        drivers = [
            driver(no_inf_ids[0], None, device_name="Invented Software Device",
                   device_class="SoftwareDevice"),
            driver(no_inf_ids[1], None, device_name="Invented Volume",
                   device_class="Volume"),
            driver("PCI\\VEN_0000&DEV_0003\\INVENTED", "oem7.inf",
                   device_name="Invented Display Adapter", device_class="Display"),
        ]
        summary = self.collect(FakePowerShell(m2_responses(
            administrators=ok(admins_result(members, current_sid=user_sid)),
            drivers=ok(drivers),
        )))

        admins = self.listed(summary, "administrator")
        for point, sid, expected in (
                ("S-1-5-21-...-500 is builtin", builtin_sid, True),
                ("S-1-5-21-...-1001 is not builtin", user_sid, False),
                ("group S-1-5-32-544 is not builtin", group_sid, False)):
            with self.subTest(point=point):
                item = self.item(admins, f"admin:{sid}")
                self.assertIn("builtin", item, item)
                self.assertIs(item.get("builtin"), expected, item)

        with self.subTest(point="two rows without InfName give two detail entries"):
            detail = self.detail(summary)
            self.assertIn("drivers_without_inf_items", detail, sorted(detail))
            entries = detail.get("drivers_without_inf_items")
            self.assertIsInstance(entries, list, entries)
            self.assertEqual(
                sorted((e.get("device_name"), e.get("class")) for e in entries),
                [("Invented Software Device", "SoftwareDevice"),
                 ("Invented Volume", "Volume")],
                entries)
            for entry in entries:
                self.assertNotIn("device_id", entry)
                for device_id in no_inf_ids:
                    self.assertNotIn(json.dumps(device_id), json.dumps(entry))
        with self.subTest(point="summary counter drivers_without_inf is 2"):
            self.assertEqual(self.component_counts(summary).get("drivers_without_inf"), 2,
                             self.component_counts(summary))

        with self.subTest(point="drivers not read give drivers_without_inf_items null"):
            unread = self.collect(FakePowerShell(m2_responses(
                drivers=failure("Invented: the driver query failed"))))
            detail = self.detail(unread)
            self.assertIn("drivers_without_inf_items", detail, sorted(detail))
            self.assertIsNone(detail.get("drivers_without_inf_items"), detail)

        contract = (SKILL_DIR / "references" / "summary-contract.md").read_text(
            encoding="utf-8")
        report_format = (SKILL_DIR / "references" / "report-format.md").read_text(
            encoding="utf-8")
        script = (SKILL_DIR / "scripts" / "inventory.py").read_text(encoding="utf-8")

        with self.subTest(point="summary-contract describes drivers_without_inf with ush-health"):
            lines = [line for line in contract.splitlines()
                     if "drivers_without_inf" in line.replace("drivers_without_inf_items", "")]
            self.assertTrue(lines, "summary-contract.md never names drivers_without_inf")
            self.assertTrue(any("ush-health" in line for line in lines), lines)
        for name, text in (("report-format.md", report_format), ("inventory.py", script)):
            # Plan 140 (decision of 116) reverses the plan 107 rule: the neutral
            # wording names "a device without a driver"; the firm one is gone.
            with self.subTest(point=f"{name} has no 'software and built-in devices'"):
                self.assertNotIn("software and built-in devices", flat(text))
        for field in ("app_exists", "no_block_reason", "builtin", "drivers_without_inf_items"):
            with self.subTest(point=f"summary-contract names {field}"):
                self.assertIn(f"`{field}", contract)


if __name__ == "__main__":
    unittest.main()

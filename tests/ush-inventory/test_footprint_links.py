"""Explicit trace links in the ush-inventory detail file (plan 064, milestone M1,
criteria K1-K3).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``not_checked``, item
``key``/``id``, the detail file) is described in ``fakes.py``; firewall rows in
``fakes_additions.py``, vendor folder rows in ``fakes_vendor_folders.py``, autostart rows
in ``fakes_autostart.py``.

Assumptions taken from the plan text:

- Every firewall rule in the detail ``additions`` section (kind ``firewall_rule``) whose
  ``app`` is one path gets ``program`` (the key of the program whose
  ``install_location`` holds the rule's expanded path, else null) and ``linked_by``
  ``"path"`` when linked. A rule without ``app``, with ``app`` ``System``, or whose
  expansion failed (the ``firewall_apps`` row still holds ``%``) has no link: ``program``
  and ``linked_by`` are absent or null.
- Every folder of the detail ``vendor_folders`` list gets ``programs``: the sorted keys of
  the programs whose ``install_location`` lies under the folder. The ``vendor`` publisher
  rule and an autostart target still set ``matched`` but add no key.
- Autostart facts keep ``program``; on clean data it is null.

PowerShell never starts; every value is invented.
"""

import unittest

from .fakes import FakePowerShell, ok, win32
from .fakes_additions import (
    custom_rule,
    firewall_result,
    fw_value,
    m2_responses,
    rule_text,
)
from .fakes_autostart import (
    VENDOR,
    clean_responses,
    facts,
    file_row,
    run_value,
    service,
)
from .fakes_vendor_folders import (
    INSTALLER,
    PROGRAM_DATA,
    PROGRAM_FILES,
    PROGRAM_FILES_X86,
    VendorFoldersTestCase,
    folder,
    folder_path,
    listing,
)

PROGRAM_FILES_DIR = "C:\\Program Files"
CONTOSO_LOCATION = "C:\\Program Files\\Contoso\\App"
CONTOSO_KEY = "win32:hklm64:ContosoApp"
APP_INSIDE = "C:\\Program Files\\Contoso\\App\\app.exe"
APP_SIBLING = "C:\\Program Files\\Contoso\\AppTools\\x.exe"
# The raw text lies under the program's location, but %ContosoMissing% could not be
# expanded: the firewall_apps row gives it back with the % still in it.
APP_NOT_EXPANDED = "C:\\Program Files\\Contoso\\App\\%ContosoMissing%\\helper.exe"


def rule_name(n):
    return f"{{00000000-0000-0000-0000-0000000F{n:04d}}}"


def firewall_key(store, name):
    return f"firewall:{store}:{name}"


def app_row(app, expanded, exists):
    """One row of the ``firewall_apps`` job."""
    return {"app": app, "expanded": expanded, "exists": exists}


def no_app_rule(name):
    """A rule without ``App``."""
    return rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "In"),
                      ("Protocol", "6"), ("LPort", "7071"), ("Name", name)])


def contoso_app():
    return win32("ContosoApp", "Contoso App", publisher="Contoso Ltd",
                 install_location=CONTOSO_LOCATION)


class FootprintLinksTestCase(VendorFoldersTestCase):
    def detail_rules(self, summary):
        """Firewall rules of the detail ``additions`` section, by key."""
        rules = [item for item in self.detail_list(summary, "additions")
                 if item.get("kind") == "firewall_rule"]
        return self.by_key(rules)

    def rule(self, rules, key):
        item = rules.get(key)
        self.assertIsNotNone(item, f"{key} not in detail additions: {sorted(map(str, rules))}")
        return item

    def assert_no_link(self, item):
        self.assertIsNone(item.get("program"), item)
        self.assertIsNone(item.get("linked_by"), item)


class TestFirewallLinks(FootprintLinksTestCase):
    def test_firewall_rule_links(self):
        names = {label: rule_name(n) for n, label in enumerate(
            ("inside", "sibling", "system", "no_app", "not_expanded"), 1)}
        firewall = firewall_result(local=[
            fw_value(names["inside"], custom_rule("Contoso App", app=APP_INSIDE)),
            fw_value(names["sibling"], custom_rule("Contoso App Tools", app=APP_SIBLING)),
            fw_value(names["system"], custom_rule("Contoso System", app="System")),
            fw_value(names["no_app"], no_app_rule("Contoso No App")),
            fw_value(names["not_expanded"],
                     custom_rule("Contoso Helper", app=APP_NOT_EXPANDED)),
        ])
        fake = FakePowerShell(m2_responses(
            win32_programs=ok([contoso_app()]),
            firewall_rules=ok(firewall),
            firewall_apps=ok([
                app_row(APP_INSIDE, APP_INSIDE, True),
                app_row(APP_SIBLING, APP_SIBLING, True),
                app_row(APP_NOT_EXPANDED, APP_NOT_EXPANDED, None),
            ]),
        ))
        summary = self.collect(fake)
        rules = self.detail_rules(summary)

        def local(label):
            return self.rule(rules, firewall_key("local", names[label]))

        with self.subTest(point="app inside the install location links the program"):
            item = local("inside")
            self.assertEqual(item.get("program"), CONTOSO_KEY, item)
            self.assertEqual(item.get("linked_by"), "path", item)
        with self.subTest(point="sibling folder sharing the prefix text gives program null"):
            item = local("sibling")
            self.assertIn("program", item, item)
            self.assertIsNone(item["program"], item)
        with self.subTest(point="app System gives no link"):
            self.assert_no_link(local("system"))
        with self.subTest(point="rule without app gives no link"):
            self.assert_no_link(local("no_app"))
        with self.subTest(point="failed expansion gives no link"):
            self.assert_no_link(local("not_expanded"))


class TestVendorFolderLinks(FootprintLinksTestCase):
    def test_vendor_folder_programs(self):
        contoso_agent = win32("ContosoAgent", "Contoso Agent", publisher="Contoso Ltd",
                              install_location="C:\\ProgramData\\Contoso\\Agent")
        # Listed in reverse key order: the folder's keys must come out sorted.
        fabrikam_studio = win32("FabrikamStudio", "Fabrikam Studio",
                                publisher="Fabrikam, Inc.",
                                install_location="C:\\Program Files\\Fabrikam\\Studio")
        fabrikam_tools = win32("FabrikamTools", "Fabrikam Tools", publisher="Fabrikam, Inc.",
                               hive="hkcu",
                               install_location="C:\\Program Files\\Fabrikam\\Tools")
        # Installed elsewhere: only the vendor publisher rule matches its folder.
        northwind = win32("{1B2C3D4E-5F60-4718-92A3-B4C5D6E7F809}", "Northwind Order Desk",
                          publisher="Northwind Traders Inc.", install_location=None)
        # No program holds this target: only the autostart target rule matches.
        litware_target = "C:\\Program Files\\Litware\\bin\\litwaresvc.exe"
        fake = FakePowerShell({
            "win32_programs": ok([contoso_agent, fabrikam_studio, fabrikam_tools,
                                  northwind]),
            "services": ok([service("LitwareSvc", f'"{litware_target}" -service')]),
            "file_facts": facts(file_row(litware_target, signer=VENDOR)),
            "vendor_folders": listing([
                folder(PROGRAM_DATA, "Contoso"),
                folder(PROGRAM_FILES, "Fabrikam"),
                folder(PROGRAM_FILES_X86, "Northwind Traders"),
                folder(PROGRAM_FILES, "Litware"),
            ]),
        })
        summary = self.collect(fake)
        folders = self.detail_folders(summary)

        def detail_folder(root, name):
            path = folder_path(root, name).casefold()
            self.assertIn(path, folders, sorted(folders))
            return folders[path]

        with self.subTest(point="folder holding one program's location"):
            item = detail_folder(PROGRAM_DATA, "Contoso")
            self.assertEqual(item.get("programs"), ["win32:hklm64:ContosoAgent"], item)
            self.assertIs(item.get("matched"), True, item)
        with self.subTest(point="folder holding two programs' locations lists both, sorted"):
            item = detail_folder(PROGRAM_FILES, "Fabrikam")
            self.assertEqual(item.get("programs"),
                             ["win32:hkcu:FabrikamTools", "win32:hklm64:FabrikamStudio"],
                             item)
            self.assertIs(item.get("matched"), True, item)
        with self.subTest(point="vendor publisher rule only: programs [] and matched"):
            item = detail_folder(PROGRAM_FILES_X86, "Northwind Traders")
            self.assertEqual(item.get("programs"), [], item)
            self.assertIs(item.get("matched"), True, item)
        with self.subTest(point="autostart target only: programs [] and matched"):
            item = detail_folder(PROGRAM_FILES, "Litware")
            self.assertEqual(item.get("programs"), [], item)
            self.assertIs(item.get("matched"), True, item)


class TestCleanData(FootprintLinksTestCase):
    def test_no_link_on_clean_data(self):
        other_exe = f"{PROGRAM_FILES_DIR}\\Other\\o.exe"
        svchost_raw = "%SystemRoot%\\system32\\svchost.exe"
        svchost = "C:\\Windows\\system32\\svchost.exe"
        tools_exe = "D:\\Tools\\t.exe"
        programs = [
            # Locations under which no trace may be linked: drive roots,
            # %ProgramFiles% itself and the Windows directory.
            win32("InventedRootC", "Invented Root C", install_location="C:\\"),
            win32("InventedRootD", "Invented Root D", install_location="D:\\"),
            win32("InventedPF", "Invented PF", install_location=PROGRAM_FILES_DIR),
            win32("InventedWin", "Invented Win", install_location="C:\\Windows"),
        ]
        responses = clean_responses(extra_files=[file_row(other_exe, signer=VENDOR),
                                                 file_row(tools_exe, signer=VENDOR)])
        responses.update(m2_responses(
            firewall_rules=ok(firewall_result(local=[
                fw_value(rule_name(101), custom_rule("Invented Svchost", app=svchost_raw)),
                fw_value(rule_name(102), custom_rule("Invented Other", app=other_exe)),
                fw_value(rule_name(103), custom_rule("Invented Tools", app=tools_exe)),
            ])),
            firewall_apps=ok([
                app_row(svchost_raw, svchost, True),
                app_row(other_exe, other_exe, True),
                app_row(tools_exe, tools_exe, True),
            ]),
        ))
        responses["win32_programs"] = ok(programs)
        responses["run_keys"] = ok([run_value("InventedOther", other_exe),
                                    run_value("InventedTools", tools_exe)])
        responses["vendor_folders"] = listing([
            folder(PROGRAM_FILES, "Other"),
            folder(PROGRAM_FILES_X86, "Invented Vendor"),
            folder(PROGRAM_DATA, "Contoso"),
            folder(INSTALLER, "Fabrikam"),
        ])
        summary = self.collect(FakePowerShell(responses))

        with self.subTest(point="autostart facts link no program"):
            entries = self.detail(summary).get("autostart")
            self.assertIsInstance(entries, list, entries)
            self.assertTrue(entries, entries)
            for entry in entries:
                for fact in entry.get("facts") or []:
                    self.assertIn("program", fact, entry.get("key"))
                    self.assertIsNone(fact["program"], f"{entry.get('key')}: {fact}")
        with self.subTest(point="firewall rules link no program"):
            rules = self.detail_rules(summary)
            self.assertEqual(len(rules), 3, sorted(map(str, rules)))
            for key, item in rules.items():
                self.assertIsNone(item.get("program"), f"{key}: {item}")
        with self.subTest(point="vendor folders hold no program"):
            folders = self.detail_folders(summary)
            self.assertEqual(len(folders), 4, sorted(folders))
            for path, item in folders.items():
                self.assertEqual(item.get("programs"), [], f"{path}: {item}")


class TestSharedLocation(FootprintLinksTestCase):
    def test_location_of_two_programs_links_none(self):
        name = rule_name(1)
        firewall = firewall_result(local=[
            fw_value(name, custom_rule("Contoso App", app=APP_INSIDE))])
        updater = win32("ContosoUpdater", "Contoso Updater", publisher="Contoso Ltd",
                        install_location=CONTOSO_LOCATION)
        fake = FakePowerShell(m2_responses(
            win32_programs=ok([contoso_app(), updater]),
            firewall_rules=ok(firewall),
            firewall_apps=ok([app_row(APP_INSIDE, APP_INSIDE, True)]),
        ))
        item = self.rule(self.detail_rules(self.collect(fake)), firewall_key("local", name))
        self.assertIn("program", item, item)
        self.assertIsNone(item["program"], item)
        self.assertIsNone(item["linked_by"], item)



class TestDuplicateEntries(FootprintLinksTestCase):
    def test_one_product_two_entries_keeps_program(self):
        """One product with a 64-bit and a 32-bit entry at one location: its missing
        Run target keeps a program (not orphaned) but gets no explicit link."""
        missing = f"{CONTOSO_LOCATION}\\gone.exe"
        responses = clean_responses(extra_files=[file_row(missing, exists=False)])
        responses["win32_programs"] = ok([
            contoso_app(),
            win32("ContosoApp", "Contoso App", publisher="Contoso Ltd", hive="hklm32",
                  install_location=CONTOSO_LOCATION),
        ])
        responses["run_keys"] = ok([run_value("ContosoGone", missing)])
        summary = self.collect(FakePowerShell(responses))
        found = [fact for entry in self.detail(summary).get("autostart") or []
                 for fact in entry.get("facts") or [] if fact.get("path") == missing]
        self.assertEqual(len(found), 1, found)
        self.assertIsNotNone(found[0]["program"], found[0])
        self.assertIsNone(found[0]["linked_by"], found[0])


if __name__ == "__main__":
    unittest.main()

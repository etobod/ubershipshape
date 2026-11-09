"""Global npm packages in skills/ush-packages/scripts/packages.py (moved from
tests/ush-inventory/test_package_managers.py by plan 061, M1; first written for plan
029, M2, and its review rounds).

Interface these tests assume:

- Job ``npmrc`` (read-only, no input) reads ``%USERPROFILE%\\.npmrc`` and answers
  ``{"status": "read"|"absent"|"unreadable", "lines": [str]|null, "reason": str|null}``.
  The first line ``prefix=<value>`` (spaces around ``=`` allowed) gives the prefix; with
  no such line, or no file, the prefix is ``%APPDATA%\\npm``. A non-blank
  ``NPM_CONFIG_PREFIX`` (any case) comes first. An unreadable ``.npmrc`` makes npm
  ``unreadable`` (count null, a not_checked entry naming npm).
- Job ``package_folders`` gets ``{"path": "<raw prefix>\\node_modules", "layout":
  "npm"}``; package ``entry`` is ``left-pad`` or ``@contoso/tool``. ``absent`` means npm
  is not present (status ``empty``, count 0); ``unreadable`` gives npm ``unreadable``
  with count null.
- Source ``npm_packages``: key ``npm:<name case-folded>``, compared field ``version``,
  items carry ``name``, ``version``, ``status``, ``reason``, ``folder`` (and ``key`` in
  the detail file's ``npm_packages`` list).
- Summary ``managers.npm`` = ``{state, status, prefix_from: "NPM_CONFIG_PREFIX"|"npmrc"|
  "default", count, unreadable}``.

PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.
"""

import unittest
from datetime import timedelta
from unittest import mock

from .fakes import (
    DEFAULT_NPM_FOLDER,
    NOW,
    PackagesTestCase,
    install_folder,
    note_text,
    npm_package,
    npmrc_read,
    npmrc_unreadable,
    ok,
    package,
    packages_fake,
    read_folder,
    registration,
    unreadable_folder,
)

PEP514_NOTE = "not registered in pep 514"
NOT_READ_YET = "not read yet"


def npm_fake(folders=None, npmrc=None, registrations=(), extra=None):
    return packages_fake(registrations, folders, npmrc=npmrc, extra=extra)


class TestNpm(PackagesTestCase):
    def npm(self, summary):
        return self.manager(summary, "npm")

    def npm_notes(self, summary):
        """The not_checked items naming npm, without the "pnpm: not read yet" item."""
        return [item for item in self.notes_with(summary, "npm")
                if NOT_READ_YET not in note_text(item)]

    def test_global_packages(self):
        fake = npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            npm_package("left-pad", "1.3.0"),
            npm_package("JSONStream", "1.3.5"),
            npm_package("@contoso/tool", "2.1.0"),
        )})
        summary = self.collect(fake)

        self.assertEqual(fake.npm_inputs(), [{"path": DEFAULT_NPM_FOLDER, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("prefix_from"), "default", npm)
        self.assertEqual(npm.get("count"), 3, npm)
        self.assertEqual(npm.get("unreadable"), 0, npm)
        self.assertEqual(self.source(summary, "npm_packages").get("status"), "read")

        items = self.by_key(self.npm_items(summary))
        expected = {
            "npm:left-pad": ("left-pad", "1.3.0"),
            "npm:jsonstream": ("JSONStream", "1.3.5"),
            "npm:@contoso/tool": ("@contoso/tool", "2.1.0"),
        }
        self.assertEqual(set(items), set(expected), sorted(map(str, items)))
        for key, (name, version) in expected.items():
            item = items[key]
            self.assertEqual(item.get("name"), name, item)
            self.assertEqual(item.get("version"), version, item)
            self.assertEqual(item.get("status"), "read", item)
            self.assertIn("reason", item, item)
            self.assertIsNone(item["reason"], item)
            self.assertIn("folder", item, item)

    def test_prefix_from_npmrc(self):
        custom = "D:\\Invented\\npm-global\\node_modules"
        fake = npm_fake(
            {
                custom: read_folder(npm_package("@contoso/tool", "2.1.0")),
                DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0")),
                "E:\\Invented\\second-prefix\\node_modules":
                    read_folder(npm_package("rimraf", "5.0.5")),
            },
            npmrc=npmrc_read(
                "; invented user config",
                "registry=https://registry.example.invalid/",
                "prefix = D:\\Invented\\npm-global",
                "prefix=E:\\Invented\\second-prefix",
            ),
        )
        summary = self.collect(fake)

        self.assertEqual(fake.npm_inputs(), [{"path": custom, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("prefix_from"), "npmrc", npm)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("count"), 1, npm)
        items = self.by_key(self.npm_items(summary))
        self.assertEqual(set(items), {"npm:@contoso/tool"}, sorted(map(str, items)))
        self.assertEqual(items["npm:@contoso/tool"].get("version"), "2.1.0")

    def test_absent_versus_unreadable(self):
        with self.subTest(case="node_modules missing: npm not present"):
            summary = self.collect(npm_fake())
            npm = self.npm(summary)
            self.assertEqual(npm.get("status"), "empty", npm)
            self.assertEqual(npm.get("count"), 0, npm)
            self.assertEqual(npm.get("unreadable"), 0, npm)
            self.assertEqual(self.source(summary, "npm_packages").get("status"), "empty")
            self.assertEqual(self.npm_items(summary), [])
            # Plan 029 M2 code-review (judge: fix): an absent default folder names the prefixes not searched.
            notes = self.npm_notes(summary)
            self.assertEqual(len(notes), 1, summary.get("not_checked"))
            self.assertIn("node.exe", note_text(notes[0]), notes)

        with self.subTest(case="node_modules cannot be listed"):
            reason = "Access to the path is denied (invented)"
            summary = self.collect(npm_fake({DEFAULT_NPM_FOLDER: unreadable_folder(reason)}))
            npm = self.npm(summary)
            self.assertEqual(npm.get("status"), "unreadable", npm)
            self.assertIn("count", npm, npm)
            self.assertIsNone(npm["count"], npm)
            notes = self.npm_notes(summary)
            self.assertTrue(notes, summary.get("not_checked"))
            self.assertIsInstance(notes[0].get("reason"), str, notes)
            self.assertTrue(notes[0]["reason"].strip(), notes)

        with self.subTest(case=".npmrc cannot be read"):
            reason = "The process cannot access the file (invented)"
            summary = self.collect(npm_fake(
                {DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))},
                npmrc=npmrc_unreadable(reason)))
            npm = self.npm(summary)
            self.assertEqual(npm.get("status"), "unreadable", npm)
            self.assertIn("count", npm, npm)
            self.assertIsNone(npm["count"], npm)
            notes = self.npm_notes(summary)
            self.assertTrue(notes, summary.get("not_checked"))
            self.assertIsInstance(notes[0].get("reason"), str, notes)
            self.assertTrue(notes[0]["reason"].strip(), notes)

    def test_not_checked_entries(self):
        # Plan 061: winget, go and the other managers are each listed as "not read yet"
        # (ush-inventory had one winget item and one item for the other managers).
        path = "C:\\Invented\\Python312"
        runs = {
            "no Python, no npm": npm_fake(),
            "a Python and npm": npm_fake(
                {install_folder(path): read_folder(package("idna", "3.6")),
                 DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))},
                registrations=[registration("3.12", path)]),
        }
        for case, fake in runs.items():
            with self.subTest(case=case):
                summary = self.collect(fake)
                notes = self.not_checked(summary)

                for name in ("winget", "go", "choco", "scoop", "cargo"):
                    own = [item for item in notes if item.get("what") == name]
                    self.assertEqual(len(own), 1, (name, notes))
                    self.assertIn(NOT_READ_YET, note_text(own[0]), own)
                    self.assertEqual(self.manager(summary, name).get("state"), "not_read")

                pep514 = [item for item in notes if PEP514_NOTE in note_text(item)]
                self.assertEqual(len(pep514), 1, notes)

                for item in pep514:
                    self.assertIsInstance(item.get("reason"), str, item)
                    self.assertTrue(item["reason"].strip(), item)

    # Review round 1 (plan 029 M2): regressions.
    def test_unlistable_scope_keeps_baseline(self):
        data_dir = self.data_dir()
        self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            npm_package("@contoso/tool", "1.2.0"), npm_package("left-pad", "1.3.0"))}),
            data_dir=data_dir, now=NOW)
        scope_row = {"entry": "@contoso", "name": None, "version": None,
                     "status": "unreadable", "reason": "Access to the path is denied (invented)"}
        run2 = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            scope_row, npm_package("left-pad", "1.3.0"))}),
            data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.changes_from(run2, "npm_packages"), [])
        items = self.by_key(self.npm_items(run2))
        self.assertNotIn("npm:@contoso", items, sorted(map(str, items)))
        self.assertIn("npm:@contoso/tool", items, sorted(map(str, items)))
        self.assertIs(items["npm:@contoso/tool"].get("from_baseline"), True,
                      items["npm:@contoso/tool"])
        self.assertTrue(self.notes_with(run2, "@contoso"), run2.get("not_checked"))

    def test_unreadable_or_versionless_package_json(self):
        cases = {
            "unreadable answer": {"entry": "left-pad", "name": None, "version": None,
                                  "status": "unreadable",
                                  "reason": "package.json is empty or not a JSON object"},
            "read without name or version": {"entry": "left-pad", "name": None,
                                             "version": None, "status": "read",
                                             "reason": None},
            "read without version": {"entry": "left-pad", "name": "left-pad",
                                     "version": None, "status": "read", "reason": None},
        }
        for case, row in cases.items():
            with self.subTest(case=case):
                data_dir = self.data_dir()
                self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
                    npm_package("left-pad", "1.3.0"))}), data_dir=data_dir, now=NOW)
                run2 = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(row)}),
                                    data_dir=data_dir, now=NOW + timedelta(days=1))
                self.assertEqual(self.changes_from(run2, "npm_packages"), [])
                items = self.by_key(self.npm_items(run2))
                self.assertEqual(set(items), {"npm:left-pad"}, sorted(map(str, items)))
                item = items["npm:left-pad"]
                self.assertEqual(item.get("status"), "unreadable", item)
                self.assertTrue(str(item.get("reason") or "").strip(), item)
                self.assertEqual(self.npm(run2).get("unreadable"), 1, self.npm(run2))

    def test_absent_default_names_other_prefixes(self):
        summary = self.collect(npm_fake())
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "empty", npm)
        self.assertEqual(npm.get("prefix_from"), "default", npm)
        notes = self.notes_with(summary, "node.exe")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn("node.exe", note_text(notes[0]), notes)
        self.assertTrue(str(notes[0].get("reason") or "").strip(), notes)

        with self.subTest(case="prefix from .npmrc, folder absent"):
            summary = self.collect(npm_fake(npmrc=npmrc_read("prefix=D:\\Invented\\npm")))
            self.assertEqual(self.npm(summary).get("status"), "empty")
            self.assertEqual(len(self.notes_with(summary, "node.exe")), 1,
                             summary.get("not_checked"))

        with self.subTest(case="npm read: no entry"):
            summary = self.collect(npm_fake(
                {DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))}))
            self.assertEqual(self.notes_with(summary, "node.exe"), [],
                             summary.get("not_checked"))

    def test_npmrc_non_dict_row(self):
        summary = self.collect(npm_fake(
            {DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))},
            npmrc=ok(["x"])))
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "unreadable", npm)
        self.assertIsNone(npm.get("count"), npm)
        notes = self.npm_notes(summary)
        self.assertTrue(notes and str(notes[0].get("reason") or "").strip(),
                        summary.get("not_checked"))

    # Review round 2 (plan 029 M2): regressions.
    def test_prefix_from_environment(self):
        env_folder = "D:\\invented\\npm\\node_modules"
        folders = {env_folder: read_folder(npm_package("rimraf", "5.0.5")),
                   DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))}
        npmrc = npmrc_read("prefix=E:\\Invented\\from-npmrc")
        with mock.patch.object(self.packages, "ENVIRON",
                               {"npm_config_prefix": "D:\\invented\\npm"}):
            fake = npm_fake(folders, npmrc=npmrc)
            summary = self.collect(fake)
        self.assertEqual(fake.npm_inputs(), [{"path": env_folder, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("prefix_from"), "NPM_CONFIG_PREFIX", npm)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("count"), 1, npm)

        with self.subTest(case="a %VAR% value is passed raw, expanded like .npmrc"):
            with mock.patch.object(self.packages, "ENVIRON",
                                   {"NPM_CONFIG_PREFIX": "%APPDATA%\\npm-env\\"}):
                fake = npm_fake(folders)
                self.collect(fake)
            self.assertEqual(fake.npm_inputs(),
                             [{"path": "%APPDATA%\\npm-env\\node_modules", "layout": "npm"}])

        with self.subTest(case="a blank value does not count"):
            with mock.patch.object(self.packages, "ENVIRON", {"NPM_CONFIG_PREFIX": "  "}):
                fake = npm_fake(folders)
                summary = self.collect(fake)
            self.assertEqual(fake.npm_inputs(), [{"path": DEFAULT_NPM_FOLDER, "layout": "npm"}])
            self.assertEqual(self.npm(summary).get("prefix_from"), "default")

    def test_empty_node_modules_names_other_prefixes(self):
        summary = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder()}))
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "empty", npm)
        self.assertEqual(npm.get("count"), 0, npm)
        notes = self.notes_with(summary, "another prefix")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn("node.exe", note_text(notes[0]), notes)
        self.assertNotIn("npm_config_prefix", note_text(notes[0]), notes)

    def test_only_unlistable_scopes(self):
        data_dir = self.data_dir()
        self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            npm_package("@contoso/tool", "1.2.0"), npm_package("@contoso/cli", "0.4.0"))}),
            data_dir=data_dir, now=NOW)
        scope_row = {"entry": "@contoso", "name": None, "version": None,
                     "status": "unreadable", "reason": "Access to the path is denied (invented)"}
        run2 = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(scope_row)}),
                            data_dir=data_dir, now=NOW + timedelta(days=1))

        npm = self.npm(run2)
        self.assertEqual(npm.get("status"), "unreadable", npm)
        self.assertIn("count", npm, npm)
        self.assertIsNone(npm["count"], npm)
        self.assertIn("unreadable", npm, npm)
        self.assertIsNone(npm["unreadable"], npm)
        self.assertTrue(self.notes_with(run2, "@contoso"), run2.get("not_checked"))
        self.assertEqual(self.changes_from(run2, "npm_packages"), [])
        items = self.by_key(self.npm_items(run2))
        self.assertEqual(set(items), {"npm:@contoso/tool", "npm:@contoso/cli"},
                         sorted(map(str, items)))
        for item in items.values():
            self.assertIs(item.get("from_baseline"), True, item)

    # ConvertTo-Json writes a list of one element as an object (plan 029, loc-qa).
    def test_single_npm_package_and_single_npmrc_line(self):
        custom = "D:\\Invented\\npm-global\\node_modules"
        npmrc = ok({"status": "read", "lines": "prefix=D:\\Invented\\npm-global",
                    "reason": None})
        fake = npm_fake({custom: {"status": "read", "reason": None,
                                  "packages": npm_package("left-pad", "1.3.0")}},
                        npmrc=npmrc)
        summary = self.collect(fake)

        self.assertEqual(fake.npm_inputs(), [{"path": custom, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("prefix_from"), "npmrc", npm)
        self.assertEqual(npm.get("count"), 1, npm)
        items = self.by_key(self.npm_items(summary))
        self.assertEqual(set(items), {"npm:left-pad"}, sorted(map(str, items)))
        self.assertEqual(items["npm:left-pad"].get("version"), "1.3.0")

    # Plan 042 M1: a package added between two runs.
    def test_npm_package_added(self):
        data_dir = self.data_dir()
        first = {DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))}
        second = {DEFAULT_NPM_FOLDER: read_folder(
            npm_package("left-pad", "1.3.0"), npm_package("rimraf", "5.0.5"))}

        self.collect(npm_fake(first), data_dir=data_dir, now=NOW)
        run2 = self.collect(npm_fake(second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("npm_packages"), "compared",
                         self.comparison(run2))
        changes = self.by_key(self.changes_from(run2, "npm_packages"))
        self.assertEqual({key: change.get("change") for key, change in changes.items()},
                         {"npm:rimraf": "added"})


if __name__ == "__main__":
    unittest.main()

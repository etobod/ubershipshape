"""Scoop apps of the user root and the global root, read offline from disk (plan 080,
M2, K1-K4).

Interface these tests assume (fixed before the code exists):

- Folders and files are read in Python through the module-level ``DISK`` object
  (``exists(path)``, ``list_dir(path)``: names, ``OSError`` on failure;
  ``read_text(path)``); locations are expanded from the module's ``ENVIRON``. The tests
  set ``USERPROFILE``, ``ProgramData``, ``SCOOP`` and ``SCOOP_GLOBAL`` to invented
  temporary folders, and replace ``DISK.list_dir`` / ``DISK.read_text`` to raise for
  chosen paths, calling the original for every other path.
- Roots and labels: ``user`` is ``SCOOP`` (non-blank), else the raw
  ``%USERPROFILE%\\scoop``; ``global`` is ``SCOOP_GLOBAL`` (non-blank), else the raw
  ``%ProgramData%\\scoop``. Each root's ``folder_from`` is its variable or ``default``.
- An app is a folder of ``<root>\\apps`` (names starting with ``.`` and files skipped;
  the folder ``scoop`` is Scoop's own core, no app); its version is ``version`` of
  ``<app>\\current\\manifest.json``, its bucket ``bucket`` of
  ``<app>\\current\\install.json`` (null when that file is missing or broken).
- Source ``scoop_apps``; detail list ``scoop_apps``; key
  ``scoop:<label>|<app folder name case-folded>``; fields ``name``, ``version``,
  ``bucket``, ``root`` (the label), ``folder``.
- ``managers.scoop`` is ``{state, status, roots: [{source, status, folder_from, count,
  reason}], count, unreadable, incomplete}``; ``{state: "not_present", looked_in: [raw
  paths]}`` when neither root exists.

PowerShell never starts; every folder and file is written by hand in a temporary folder;
every app name, version, bucket and path is invented.
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, PackagesTestCase, note_text, packages_fake

MANAGER = "scoop"
SOURCE = "scoop_apps"
PREFIX = "scoop:"
USER = "user"
GLOBAL = "global"
RAW_USER_ROOT = "%USERPROFILE%\\scoop"
RAW_GLOBAL_ROOT = "%ProgramData%\\scoop"
NOT_READ_YET = "not read yet"
NO_CURRENT_NOTE = "without a current version"
CORE_NOTE = "scoop core (apps\\scoop)"
DENIED = "Access to the path is denied (invented)"


def key(label, app):
    return f"{PREFIX}{label}|{app.casefold()}"


GIT = key(USER, "git")
JQ = key(USER, "jq")
SEVENZIP = key(GLOBAL, "7zip")


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def manifest_text(version):
    """An invented ``manifest.json`` as Scoop copies it into ``current``."""
    return json.dumps({
        "version": version,
        "description": "An invented app for tests.",
        "homepage": "https://example.invalid/invented-app",
        "license": "MIT",
        "architecture": {
            "64bit": {
                "url": "https://example.invalid/invented-app.zip",
                "hash": "0" * 64,
            },
        },
        "bin": "invented.exe",
    }, indent=4) + "\n"


def install_text(bucket):
    """An invented ``install.json`` as Scoop writes it beside the manifest."""
    return json.dumps({"bucket": bucket, "architecture": "64bit"}, indent=4) + "\n"


def add_app(apps, name, version="1.0.0", bucket="main", current=True, manifest=True,
            manifest_raw=None, install_raw=None):
    """One app folder ``<apps>\\<name>`` with a version folder and ``current``.

    ``current`` False leaves ``current`` out; ``manifest`` False leaves its
    ``manifest.json`` out; ``bucket`` None leaves ``install.json`` out; ``manifest_raw`` /
    ``install_raw`` replace that file's content."""
    folder = Path(apps) / name
    folder.mkdir(parents=True, exist_ok=True)
    if not current:
        (folder / version).mkdir(exist_ok=True)
        return folder
    # A real Scoop install makes ``current`` a junction; a plain folder reads the same.
    current_folder = folder / "current"
    current_folder.mkdir(exist_ok=True)
    (current_folder / "invented.exe").write_bytes(b"MZinvented")
    if manifest_raw is not None:
        (current_folder / "manifest.json").write_text(manifest_raw, encoding="utf-8")
    elif manifest:
        (current_folder / "manifest.json").write_text(manifest_text(version),
                                                      encoding="utf-8")
    if install_raw is not None:
        (current_folder / "install.json").write_text(install_raw, encoding="utf-8")
    elif bucket is not None:
        (current_folder / "install.json").write_text(install_text(bucket),
                                                     encoding="utf-8")
    return folder


def add_core(apps):
    """Scoop's own ``apps\\scoop\\current``: a source checkout without manifest.json."""
    current = Path(apps) / "scoop" / "current"
    (current / "bin").mkdir(parents=True, exist_ok=True)
    (current / "bin" / "scoop.ps1").write_text("Write-Host 'invented'\n", encoding="utf-8")
    (current / "README.md").write_text("Invented core checkout.\n", encoding="utf-8")
    return current


class ScoopTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def profile(self):
        """An invented %USERPROFILE% that exists, without a scoop folder."""
        folder = self.temp_folder() / "Invented"
        folder.mkdir(parents=True)
        return folder

    def program_data(self):
        """An invented %ProgramData% that exists, without a scoop folder."""
        folder = self.temp_folder() / "ProgramData"
        folder.mkdir(parents=True)
        return folder

    @staticmethod
    def apps(root):
        folder = Path(root) / "apps"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def collect_with(self, environ, data_dir=None, now=NOW):
        with mock.patch.object(self.packages, "ENVIRON", dict(environ)):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def items(self, summary):
        items = self.detail(summary).get(SOURCE)
        self.assertIsInstance(items, list, f"detail {SOURCE}: {items!r}")
        return self.by_key(items)

    def scoop(self, summary):
        return self.manager(summary, MANAGER)

    def scoop_changes(self, summary):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith(PREFIX)]

    def notes_about(self, summary, words):
        return [item for item in self.not_checked(summary) if words in note_text(item)]

    def roots(self, manager):
        roots = manager.get("roots")
        self.assertIsInstance(roots, list, manager)
        by_label = {}
        for entry in roots:
            self.assertIsInstance(entry, dict, roots)
            self.assertNotIn(entry.get("source"), by_label, roots)
            by_label[entry.get("source")] = entry
        return by_label

    def failing_list_dir(self, failing_paths, error):
        original = self.packages.DISK.list_dir

        def list_dir(path, *args, **kwargs):
            if any(same_path(path, failing) for failing in failing_paths):
                raise error
            return original(path, *args, **kwargs)

        return mock.patch.object(self.packages.DISK, "list_dir", list_dir)

    def failing_read_text(self, failing_path, error):
        original = self.packages.DISK.read_text

        def read_text(path, *args, **kwargs):
            if same_path(path, failing_path):
                raise error
            return original(path, *args, **kwargs)

        return mock.patch.object(self.packages.DISK, "read_text", read_text)


class TestScoop(ScoopTestCase):
    def test_absent_is_not_present(self):
        summary = self.collect_with({"USERPROFILE": str(self.profile()),
                                     "ProgramData": str(self.program_data())})

        scoop = self.scoop(summary)
        self.assertEqual(set(scoop), {"state", "looked_in"}, scoop)
        self.assertEqual(scoop["state"], "not_present", scoop)
        looked_in = scoop["looked_in"]
        self.assertIsInstance(looked_in, list, scoop)
        self.assertEqual(len(looked_in), 2, scoop)
        self.assertEqual(sorted(str(path).casefold() for path in looked_in),
                         sorted([RAW_USER_ROOT.casefold(), RAW_GLOBAL_ROOT.casefold()]),
                         scoop)
        self.assertEqual(self.notes_with(summary, MANAGER, NOT_READ_YET), [],
                         summary.get("not_checked"))
        self.assertNotEqual(self.source(summary, SOURCE).get("status"), "unreadable")
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith(PREFIX)]
        self.assertEqual(found, [], found)

    def test_apps_of_both_roots(self):
        profile = self.profile()
        user_apps = self.apps(profile / "scoop")
        add_app(user_apps, "git", "2.47.1", bucket="main")
        add_app(user_apps, "jq", "1.7.1", bucket=None)
        add_app(user_apps, "broken", "0.1.0", current=False)
        add_core(user_apps)
        (user_apps / "readme.txt").write_text("invented", encoding="utf-8")
        global_root = self.temp_folder() / "invented-scoop-global"
        add_app(self.apps(global_root), "7zip", "24.08", bucket="main")

        summary = self.collect_with({"USERPROFILE": str(profile),
                                     "SCOOP_GLOBAL": str(global_root)})

        items = self.items(summary)
        self.assertEqual(set(items), {GIT, JQ, SEVENZIP}, sorted(map(str, items)))
        git = items[GIT]
        self.assertEqual(git.get("name"), "git", git)
        self.assertEqual(git.get("version"), "2.47.1", git)
        self.assertEqual(git.get("bucket"), "main", git)
        self.assertEqual(git.get("root"), USER, git)
        # The folder is raw (plan 080 M2 App): the default root unexpanded.
        self.assertTrue(same_path(git.get("folder"), RAW_USER_ROOT + "\\apps\\git"), git)
        jq = items[JQ]
        self.assertEqual(jq.get("version"), "1.7.1", jq)
        self.assertIn("bucket", jq, jq)
        self.assertIsNone(jq["bucket"], jq)
        self.assertEqual(jq.get("status"), "read", jq)
        sevenzip = items[SEVENZIP]
        self.assertEqual(sevenzip.get("version"), "24.08", sevenzip)
        self.assertEqual(sevenzip.get("bucket"), "main", sevenzip)
        self.assertEqual(sevenzip.get("root"), GLOBAL, sevenzip)
        stray = [name for name in map(str, items)
                 if "broken" in name or name.endswith("|scoop") or "readme" in name]
        self.assertEqual(stray, [], sorted(map(str, items)))

        scoop = self.scoop(summary)
        self.assertEqual(scoop.get("state"), "read", scoop)
        self.assertEqual(scoop.get("count"), 3, scoop)
        self.assertEqual(scoop.get("incomplete"), 1, scoop)
        self.assertEqual(scoop.get("unreadable"), 0, scoop)
        self.assertEqual(len(self.notes_about(summary, NO_CURRENT_NOTE)), 1,
                         summary.get("not_checked"))
        self.assertEqual(len(self.notes_about(summary, CORE_NOTE)), 1,
                         summary.get("not_checked"))

        roots = self.roots(scoop)
        self.assertEqual(set(roots), {USER, GLOBAL}, roots)
        self.assertEqual(roots[USER].get("status"), "read", roots)
        self.assertEqual(roots[USER].get("folder_from"), "default", roots)
        self.assertEqual(roots[USER].get("count"), 2, roots)
        self.assertEqual(roots[GLOBAL].get("status"), "read", roots)
        self.assertEqual(roots[GLOBAL].get("folder_from"), "SCOOP_GLOBAL", roots)
        self.assertEqual(roots[GLOBAL].get("count"), 1, roots)

    def test_broken_manifest_and_install(self):
        profile = self.profile()
        apps = self.apps(profile / "scoop")
        add_app(apps, "git", "2.47.1", bucket="main")
        add_app(apps, "contoso", "1.0.0", manifest_raw="this is not json {\n")
        denied = add_app(apps, "fabrikam", "2.0.0")
        add_app(apps, "litware", "3.1.0", install_raw="{ invented: not json\n")

        with self.failing_read_text(denied / "current" / "manifest.json",
                                    PermissionError(DENIED)):
            summary = self.collect_with({"USERPROFILE": str(profile)})

        items = self.items(summary)
        for app in ("contoso", "fabrikam"):
            item_key = key(USER, app)
            self.assertIn(item_key, items, sorted(map(str, items)))
            self.assertEqual(items[item_key].get("status"), "unreadable", items[item_key])
        litware = items.get(key(USER, "litware"))
        self.assertIsNotNone(litware, sorted(map(str, items)))
        self.assertEqual(litware.get("status"), "read", litware)
        self.assertEqual(litware.get("version"), "3.1.0", litware)
        self.assertIn("bucket", litware, litware)
        self.assertIsNone(litware["bucket"], litware)
        self.assertEqual(items[GIT].get("status"), "read", items[GIT])

        scoop = self.scoop(summary)
        self.assertEqual(scoop.get("unreadable"), 2, scoop)
        self.assertEqual(scoop.get("incomplete"), 0, scoop)
        self.assertEqual(self.notes_about(summary, NO_CURRENT_NOTE), [],
                         summary.get("not_checked"))

    def test_partly_read_and_changes(self):
        profile = self.profile()
        user_root = profile / "scoop"
        user_apps = self.apps(user_root)
        program_data = self.program_data()
        global_root = program_data / "scoop"
        global_apps = self.apps(global_root)
        add_app(user_apps, "git", "2.47.1", bucket="main")
        add_app(global_apps, "7zip", "24.08", bucket="main")
        environ = {"USERPROFILE": str(profile), "ProgramData": str(program_data)}
        data_dir = self.data_dir()

        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(set(self.items(first)), {GIT, SEVENZIP},
                         sorted(map(str, self.items(first))))
        self.assertEqual(self.scoop_changes(first), [])

        add_app(user_apps, "git", "2.48.0", bucket="main")
        with self.failing_list_dir((global_root, global_apps), OSError(DENIED)):
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

        scoop = self.scoop(second)
        self.assertEqual(scoop.get("state"), "read", scoop)
        self.assertEqual(self.source(second, SOURCE).get("status"), "read",
                         self.source(second, SOURCE))
        self.assertIn("count", scoop, scoop)
        self.assertIsNone(scoop["count"], scoop)

        changes = self.scoop_changes(second)
        self.assertEqual([(c.get("key"), c.get("change")) for c in changes],
                         [(GIT, "changed")], changes)
        changed = changes[0]
        self.assertEqual(changed.get("source"), SOURCE, changed)
        self.assertEqual(changed.get("root"), USER, changed)

        items = self.items(second)
        self.assertIn(SEVENZIP, items, sorted(map(str, items)))
        self.assertIs(items[SEVENZIP].get("from_baseline"), True, items[SEVENZIP])
        self.assertEqual(items[SEVENZIP].get("version"), "24.08", items[SEVENZIP])

        with self.subTest(case="both roots cannot be listed"):
            failing = (user_root, user_apps, global_root, global_apps)
            with self.failing_list_dir(failing, OSError(DENIED)):
                third = self.collect_with(environ, data_dir=data_dir,
                                          now=NOW + timedelta(days=2))

            scoop = self.scoop(third)
            self.assertEqual(scoop.get("state"), "unreadable", scoop)
            self.assertNotEqual(scoop.get("state"), "not_present", scoop)
            self.assertEqual(self.source(third, SOURCE).get("status"), "unreadable",
                             self.source(third, SOURCE))
            self.assertIn("count", scoop, scoop)
            self.assertIsNone(scoop["count"], scoop)


class TestReviewFixes(ScoopTestCase):
    """Plan 080 M2 code-review round 1."""

    def test_unreadable_install_json_is_named(self):
        profile = self.profile()
        apps = self.apps(profile / "scoop")
        add_app(apps, "git", "2.47.1", bucket=None)  # no install.json: no note
        add_app(apps, "litware", "3.1.0", install_raw="{ invented: not json\n")
        denied = add_app(apps, "fabrikam", "2.0.0", bucket="main")
        with self.failing_read_text(denied / "current" / "install.json",
                                    PermissionError(DENIED)):
            summary = self.collect_with({"USERPROFILE": str(profile)})

        items = self.items(summary)
        for app in ("litware", "fabrikam"):
            item = items[key(USER, app)]
            self.assertEqual((item.get("status"), item.get("bucket")), ("read", None), item)
        notes = self.notes_about(summary, "install.json")
        self.assertEqual(len(notes), 2, summary.get("not_checked"))
        self.assertEqual(self.notes_about(summary, "git install.json"), [],
                         summary.get("not_checked"))

    def test_unlistable_root_beside_empty_root_is_read(self):
        profile = self.profile()
        self.apps(profile / "scoop")  # the user root: apps, no app
        program_data = self.program_data()
        global_root = program_data / "scoop"
        global_apps = self.apps(global_root)
        environ = {"USERPROFILE": str(profile), "ProgramData": str(program_data)}
        with self.failing_list_dir((global_root, global_apps), OSError(DENIED)):
            summary = self.collect_with(environ)

        scoop = self.scoop(summary)
        self.assertEqual(scoop.get("state"), "read", scoop)
        self.assertEqual(self.source(summary, SOURCE).get("status"), "read",
                         self.source(summary, SOURCE))
        self.assertIsNone(scoop.get("count"), scoop)


    def test_absent_root_beside_unlistable_root_is_removed_later(self):
        profile = self.profile()
        user_root = profile / "scoop"
        user_apps = self.apps(user_root)
        program_data = self.program_data()
        global_root = program_data / "scoop"
        global_apps = self.apps(global_root)
        add_app(user_apps, "git", "2.47.1", bucket="main")
        add_app(global_apps, "7zip", "24.08", bucket="main")
        environ = {"USERPROFILE": str(profile), "ProgramData": str(program_data)}
        data_dir = self.data_dir()
        self.collect_with(environ, data_dir=data_dir, now=NOW)

        shutil.rmtree(global_root)
        with self.failing_list_dir((user_root, user_apps), OSError(DENIED)):
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))
        self.assertEqual(self.scoop(second).get("state"), "unreadable", self.scoop(second))
        self.assertEqual(self.scoop_changes(second), [])

        third = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=2))
        changes = self.scoop_changes(third)
        self.assertEqual([(c.get("key"), c.get("change")) for c in changes],
                         [(SEVENZIP, "removed")], changes)

if __name__ == "__main__":
    unittest.main()

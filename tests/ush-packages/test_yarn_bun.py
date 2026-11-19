"""Yarn classic and bun global packages read offline from disk (plan 083, M1, K1-K5).

Interface these tests assume (fixed before the code exists):

- Folders and files are read in Python through the module-level ``DISK`` object
  (``exists``, ``list_dir``, ``read_text``); locations are expanded from the module's
  ``ENVIRON``. The tests set ``LOCALAPPDATA``, ``USERPROFILE``, ``YARN_GLOBAL_FOLDER``,
  ``BUN_INSTALL`` and ``BUN_INSTALL_GLOBAL_DIR`` to invented temporary folders, and
  replace ``DISK.read_text`` to raise for one chosen path, calling the original for every
  other path.
- One global folder ``G``: each key of ``dependencies`` in ``G\\package.json`` is a global
  package; its version is the ``version`` of ``G\\node_modules\\<name>\\package.json``
  (``/`` of a scoped name becomes ``\\``). Other ``node_modules`` entries are no item.
- yarn: ``G`` is ``YARN_GLOBAL_FOLDER`` (non-blank), else the raw
  ``%LOCALAPPDATA%\\Yarn\\Data\\global``. Source ``yarn_packages``; detail list
  ``yarn_packages``; key ``yarn:<name case-folded>``.
- bun: ``G`` is ``BUN_INSTALL_GLOBAL_DIR`` (non-blank), else ``<B>\\install\\global`` with
  ``<B>`` = ``BUN_INSTALL`` (non-blank), else the raw ``%USERPROFILE%\\.bun``. Source
  ``bun_packages``; detail list ``bun_packages``; key ``bun:<name case-folded>``.
- ``managers.yarn`` and ``managers.bun`` are ``{state, status, folder_from, count,
  unreadable}``, or ``{state: "not_present", looked_in: [...]}`` when ``G`` is absent.

PowerShell never starts; every folder and file is written by hand in a temporary folder;
every package name, version and path is invented.
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

YARN = "yarn"
BUN = "bun"
YARN_SOURCE = "yarn_packages"
BUN_SOURCE = "bun_packages"
YARN_PREFIX = "yarn:"
BUN_PREFIX = "bun:"
RAW_YARN_FOLDER = "%LOCALAPPDATA%\\Yarn\\Data\\global"
RAW_BUN_FOLDER = "%USERPROFILE%\\.bun\\install\\global"
NOT_READ_YET = "not read yet"
YARNRC_NOTE = ".yarnrc"
BUNFIG_NOTE = "bunfig.toml"
DENIED = "Access to the path is denied (invented)"

CONTOSO = "contoso-cli"
FABRIKAM = "@fabrikam/tool"
LITWARE = "litware"

GLOBAL_DEPENDENCIES = {CONTOSO: "^1.2.0", FABRIKAM: "^3.0.0", LITWARE: "^2.0.0"}
# litware is a dependency without a node_modules folder; left-pad is hoisted.
GLOBAL_MODULES = {CONTOSO: "1.2.3", FABRIKAM: "3.0.1", "left-pad": "1.3.0"}


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def module_folder(global_folder, name):
    return Path(global_folder, "node_modules", *name.split("/"))


def write_module(global_folder, name, version=None, text=None):
    """One package folder in ``node_modules``; ``text`` replaces its ``package.json``."""
    folder = module_folder(global_folder, name)
    folder.mkdir(parents=True, exist_ok=True)
    if text is None:
        manifest = {"name": name, "description": "An invented package.",
                    "main": "index.js"}
        if version is not None:
            manifest["version"] = version
        text = json.dumps(manifest, indent=2)
    (folder / "package.json").write_text(text, encoding="utf-8")
    (folder / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
    return folder


def write_global(global_folder, dependencies=None, modules=None, text=None):
    """An invented global folder laid out as yarn classic or bun write it.

    ``dependencies`` None writes a ``package.json`` without them; ``text`` replaces the
    global ``package.json``; ``modules`` maps package names to versions."""
    global_folder = Path(global_folder)
    global_folder.mkdir(parents=True, exist_ok=True)
    if text is None:
        manifest = {"private": True}
        if dependencies is not None:
            manifest["dependencies"] = dict(dependencies)
        text = json.dumps(manifest, indent=2)
    (global_folder / "package.json").write_text(text, encoding="utf-8")
    bin_folder = global_folder / "node_modules" / ".bin"
    bin_folder.mkdir(parents=True, exist_ok=True)
    (bin_folder / "contoso-cli.cmd").write_text("@echo invented\n", encoding="utf-8")
    for name, version in (modules or {}).items():
        write_module(global_folder, name, version)
    return global_folder


def write_standard(global_folder):
    """The K2 shape: three dependencies, two installed, a hoisted one and ``.bin``."""
    return write_global(global_folder, GLOBAL_DEPENDENCIES, GLOBAL_MODULES)


class YarnBunTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def local_app_data(self):
        """An invented %LOCALAPPDATA% that exists, without a Yarn folder."""
        folder = self.temp_folder() / "Local"
        folder.mkdir(parents=True)
        return folder

    def user_profile(self):
        """An invented %USERPROFILE% that exists, without a .bun folder."""
        folder = self.temp_folder() / "Profile"
        folder.mkdir(parents=True)
        return folder

    def collect_with(self, environ, data_dir=None, now=NOW):
        with mock.patch.object(self.packages, "ENVIRON", dict(environ)):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def items(self, summary, source):
        items = self.detail(summary).get(source)
        self.assertIsInstance(items, list, f"detail {source}: {items!r}")
        return self.by_key(items)

    def changes_with(self, summary, prefix):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith(prefix)]

    def change_kinds(self, summary, prefix):
        return sorted((str(change.get("key")), str(change.get("change")))
                      for change in self.changes_with(summary, prefix))

    def notes_about(self, summary, word):
        return [item for item in self.not_checked(summary)
                if word.casefold() in note_text(item)]

    def reason_named(self, summary, source, reason):
        """``reason`` appears in a ``not_checked`` entry or in the source's own reason."""
        texts = [note_text(item) for item in self.not_checked(summary)]
        texts.append(str(self.source(summary, source).get("reason")).casefold())
        return any(reason.casefold() in text for text in texts)

    def failing_read_text(self, failing_path, error):
        original = self.packages.DISK.read_text

        def read_text(path, *args, **kwargs):
            if same_path(path, failing_path):
                raise error
            return original(path, *args, **kwargs)

        return mock.patch.object(self.packages.DISK, "read_text", read_text)

    def assert_standard_items(self, summary, manager_name, source, prefix):
        """The items of the K2 shape: two read globals, litware unreadable, no stray."""
        contoso, fabrikam, litware = (prefix + CONTOSO, prefix + FABRIKAM,
                                      prefix + LITWARE)
        items = self.items(summary, source)
        self.assertEqual(set(items), {contoso, fabrikam, litware},
                         sorted(map(str, items)))
        self.assertEqual(items[contoso].get("name"), CONTOSO, items[contoso])
        self.assertEqual(items[contoso].get("version"), "1.2.3", items[contoso])
        self.assertTrue(str(items[contoso].get("folder")).casefold().endswith(
            "\\node_modules\\contoso-cli"), items[contoso])
        self.assertEqual(items[fabrikam].get("name"), FABRIKAM, items[fabrikam])
        self.assertEqual(items[fabrikam].get("version"), "3.0.1", items[fabrikam])
        self.assertEqual(items[litware].get("status"), "unreadable", items[litware])
        stray = [key for key in map(str, items)
                 if "left-pad" in key or ".bin" in key]
        self.assertEqual(stray, [], sorted(map(str, items)))

        manager = self.manager(summary, manager_name)
        self.assertEqual(manager.get("state"), "read", manager)
        self.assertEqual(manager.get("unreadable"), 1, manager)
        named = [item for item in self.not_checked(summary)
                 if LITWARE in note_text(item)]
        self.assertTrue(named, summary.get("not_checked"))

    def assert_carried(self, summary, manager_name, source, prefix, expected):
        """The source is unreadable, ``count`` null, ``expected`` (key -> version) kept
        ``from_baseline`` with no ``removed`` change, never ``not_present``."""
        manager = self.manager(summary, manager_name)
        self.assertEqual(manager.get("state"), "unreadable", manager)
        self.assertNotEqual(manager.get("state"), "not_present", manager)
        self.assertIn("count", manager, manager)
        self.assertIsNone(manager["count"], manager)
        self.assertEqual(self.source(summary, source).get("status"), "unreadable",
                         self.source(summary, source))
        items = self.items(summary, source)
        for key, version in expected.items():
            self.assertIn(key, items, sorted(map(str, items)))
            self.assertIs(items[key].get("from_baseline"), True, items[key])
            self.assertEqual(items[key].get("version"), version, items[key])
        removed = [change for change in self.changes_with(summary, prefix)
                   if change.get("change") == "removed"]
        self.assertEqual(removed, [], summary.get("changes"))


class TestYarn(YarnBunTestCase):
    def test_absent_is_not_present(self):
        local = self.local_app_data()
        profile = self.user_profile()
        summary = self.collect_with({"LOCALAPPDATA": str(local),
                                     "USERPROFILE": str(profile)})

        for name, raw in ((YARN, RAW_YARN_FOLDER), (BUN, RAW_BUN_FOLDER)):
            manager = self.manager(summary, name)
            self.assertEqual(manager.get("state"), "not_present", manager)
            self.assertEqual(sorted(manager), ["looked_in", "state"], manager)
            looked_in = manager.get("looked_in")
            self.assertIsInstance(looked_in, list, manager)
            self.assertEqual([str(path).casefold() for path in looked_in],
                             [raw.casefold()], manager)

        for word in (YARN, BUN):
            for item in self.notes_about(summary, word):
                text = note_text(item)
                self.assertNotIn(NOT_READ_YET, text, item)
                self.assertNotIn("unreadable", text, item)
        for source in (YARN_SOURCE, BUN_SOURCE):
            self.assertNotEqual(self.source(summary, source).get("status"), "unreadable")
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith((YARN_PREFIX, BUN_PREFIX))]
        self.assertEqual(found, [], found)

    def test_globals_from_dependencies(self):
        global_folder = write_standard(self.temp_folder() / "invented-yarn-global")
        summary = self.collect_with({"YARN_GLOBAL_FOLDER": str(global_folder)})

        self.assert_standard_items(summary, YARN, YARN_SOURCE, YARN_PREFIX)
        yarn = self.manager(summary, YARN)
        self.assertEqual(yarn.get("folder_from"), "YARN_GLOBAL_FOLDER", yarn)
        self.assertEqual(len(self.notes_about(summary, YARNRC_NOTE)), 1,
                         summary.get("not_checked"))

        with self.subTest(case="the default folder without package.json is empty"):
            local = self.local_app_data()
            default = local / "Yarn" / "Data" / "global"
            default.mkdir(parents=True)
            summary = self.collect_with({"LOCALAPPDATA": str(local)})

            yarn = self.manager(summary, YARN)
            self.assertNotEqual(yarn.get("state"), "not_present", yarn)
            self.assertEqual(yarn.get("status"), "empty", yarn)
            self.assertEqual(yarn.get("count"), 0, yarn)
            self.assertEqual(yarn.get("folder_from"), "default", yarn)
            self.assertEqual(self.items(summary, YARN_SOURCE), {})

    def test_unreadable(self):
        contoso, fabrikam = YARN_PREFIX + CONTOSO, YARN_PREFIX + FABRIKAM
        baseline = {contoso: "1.2.3", fabrikam: "3.0.1"}
        modules = {CONTOSO: "1.2.3", FABRIKAM: "3.0.1"}
        dependencies = {CONTOSO: "^1.2.0", FABRIKAM: "^3.0.0"}

        def baseline_run():
            global_folder = write_global(self.temp_folder() / "yarn-global",
                                         dependencies, modules)
            environ = {"YARN_GLOBAL_FOLDER": str(global_folder)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, YARN_SOURCE)), set(baseline))
            return global_folder, environ, data_dir

        with self.subTest(case="the global package.json is not JSON"):
            global_folder, environ, data_dir = baseline_run()
            (global_folder / "package.json").write_text(
                '{"dependencies": {"contoso-cli": ', encoding="utf-8")
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

            self.assert_carried(second, YARN, YARN_SOURCE, YARN_PREFIX, baseline)
            self.assertTrue(self.source(second, YARN_SOURCE).get("reason"),
                            self.source(second, YARN_SOURCE))

        with self.subTest(case="the global package.json cannot be read"):
            global_folder, environ, data_dir = baseline_run()
            with self.failing_read_text(global_folder / "package.json",
                                        PermissionError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

            self.assert_carried(second, YARN, YARN_SOURCE, YARN_PREFIX, baseline)
            self.assertTrue(self.reason_named(second, YARN_SOURCE, DENIED),
                            second.get("not_checked"))

        with self.subTest(case="the global folder is a file"):
            global_folder, environ, data_dir = baseline_run()
            shutil.rmtree(global_folder)
            global_folder.write_text("not a folder\n", encoding="utf-8")
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

            self.assert_carried(second, YARN, YARN_SOURCE, YARN_PREFIX, baseline)
            self.assertTrue(self.source(second, YARN_SOURCE).get("reason"),
                            self.source(second, YARN_SOURCE))

        with self.subTest(case="dependencies is a list"):
            global_folder, environ, data_dir = baseline_run()
            (global_folder / "package.json").write_text(
                json.dumps({"dependencies": [CONTOSO, FABRIKAM]}), encoding="utf-8")
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

            self.assert_carried(second, YARN, YARN_SOURCE, YARN_PREFIX, baseline)
            self.assertTrue(self.source(second, YARN_SOURCE).get("reason"),
                            self.source(second, YARN_SOURCE))

        with self.subTest(case="a package's package.json is not JSON or has no version"):
            global_folder, environ, data_dir = baseline_run()
            write_module(global_folder, CONTOSO, text='{"name": "contoso-cli", ')
            write_module(global_folder, FABRIKAM, version=None)
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

            items = self.items(second, YARN_SOURCE)
            for key, name in ((contoso, CONTOSO), (fabrikam, FABRIKAM)):
                self.assertIn(key, items, sorted(map(str, items)))
                self.assertEqual(items[key].get("status"), "unreadable", items[key])
                named = [item for item in self.not_checked(second)
                         if name in note_text(item)]
                self.assertTrue(named, (name, second.get("not_checked")))
            yarn = self.manager(second, YARN)
            self.assertNotEqual(yarn.get("state"), "not_present", yarn)
            self.assertEqual(yarn.get("unreadable"), 2, yarn)
            changed = [change for change in self.changes_with(second, YARN_PREFIX)
                       if change.get("change") == "changed"]
            self.assertEqual(changed, [], second.get("changes"))


class TestBun(YarnBunTestCase):
    def test_folder_and_items(self):
        with self.subTest(case="BUN_INSTALL alone"):
            install = self.temp_folder() / "invented-bun"
            write_standard(install / "install" / "global")
            summary = self.collect_with({"BUN_INSTALL": str(install),
                                         "USERPROFILE": str(self.user_profile())})

            self.assert_standard_items(summary, BUN, BUN_SOURCE, BUN_PREFIX)
            bun = self.manager(summary, BUN)
            self.assertEqual(bun.get("folder_from"), "BUN_INSTALL", bun)
            self.assertEqual(len(self.notes_about(summary, BUNFIG_NOTE)), 1,
                             summary.get("not_checked"))

        with self.subTest(case="BUN_INSTALL_GLOBAL_DIR wins over BUN_INSTALL"):
            install = self.temp_folder() / "invented-bun"
            # A decoy under BUN_INSTALL: if it were read, northwind-decoy would appear.
            write_global(install / "install" / "global", {"northwind-decoy": "^0.1.0"},
                         {"northwind-decoy": "0.1.0"})
            global_dir = write_standard(self.temp_folder() / "invented-bun-global")
            summary = self.collect_with({"BUN_INSTALL": str(install),
                                         "BUN_INSTALL_GLOBAL_DIR": str(global_dir),
                                         "USERPROFILE": str(self.user_profile())})

            self.assert_standard_items(summary, BUN, BUN_SOURCE, BUN_PREFIX)
            bun = self.manager(summary, BUN)
            self.assertEqual(bun.get("folder_from"), "BUN_INSTALL_GLOBAL_DIR", bun)
            self.assertEqual(len(self.notes_about(summary, BUNFIG_NOTE)), 1,
                             summary.get("not_checked"))

        with self.subTest(case="neither variable: the default under USERPROFILE"):
            profile = self.user_profile()
            write_standard(profile / ".bun" / "install" / "global")
            summary = self.collect_with({"USERPROFILE": str(profile)})

            self.assert_standard_items(summary, BUN, BUN_SOURCE, BUN_PREFIX)
            bun = self.manager(summary, BUN)
            self.assertEqual(bun.get("folder_from"), "default", bun)
            self.assertEqual(len(self.notes_about(summary, BUNFIG_NOTE)), 1,
                             summary.get("not_checked"))

    def test_changes(self):
        yarn_global = write_global(self.temp_folder() / "yarn-global",
                                   {CONTOSO: "^1.2.0", FABRIKAM: "^3.0.0"},
                                   {CONTOSO: "1.2.3", FABRIKAM: "3.0.1"})
        bun_global = write_global(self.temp_folder() / "bun-global",
                                  {CONTOSO: "^1.2.0", FABRIKAM: "^3.0.0"},
                                  {CONTOSO: "1.2.3", FABRIKAM: "3.0.1"})
        environ = {"YARN_GLOBAL_FOLDER": str(yarn_global),
                   "BUN_INSTALL_GLOBAL_DIR": str(bun_global)}
        data_dir = self.data_dir()

        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(self.changes_with(first, YARN_PREFIX), [])
        self.assertEqual(self.changes_with(first, BUN_PREFIX), [])

        # Raised version, removed global, added global, in each manager.
        for global_folder in (yarn_global, bun_global):
            shutil.rmtree(module_folder(global_folder, FABRIKAM).parent)
            write_global(global_folder, {CONTOSO: "^1.3.0", LITWARE: "^2.0.0"},
                         {CONTOSO: "1.3.0", LITWARE: "2.0.1"})
        second = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=1))

        for prefix in (YARN_PREFIX, BUN_PREFIX):
            self.assertEqual(self.change_kinds(second, prefix),
                             sorted([(prefix + CONTOSO, "changed"),
                                     (prefix + FABRIKAM, "removed"),
                                     (prefix + LITWARE, "added")]),
                             second.get("changes"))

        with self.subTest(case="an unchanged run"):
            third = self.collect_with(environ, data_dir=data_dir,
                                      now=NOW + timedelta(days=2))
            self.assertEqual(self.changes_with(third, YARN_PREFIX), [])
            self.assertEqual(self.changes_with(third, BUN_PREFIX), [])

        with self.subTest(case="the global folders are gone"):
            shutil.rmtree(yarn_global)
            shutil.rmtree(bun_global)
            fourth = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=3))
            self.assertEqual(self.manager(fourth, YARN).get("state"), "not_present")
            self.assertEqual(self.manager(fourth, BUN).get("state"), "not_present")
            for prefix in (YARN_PREFIX, BUN_PREFIX):
                self.assertEqual(self.change_kinds(fourth, prefix),
                                 sorted([(prefix + CONTOSO, "removed"),
                                         (prefix + LITWARE, "removed")]),
                                 fourth.get("changes"))


if __name__ == "__main__":
    unittest.main()

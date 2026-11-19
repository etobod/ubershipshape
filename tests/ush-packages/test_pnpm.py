"""pnpm global packages read offline from disk, one part per layout folder (plan 083,
M2, K1-K3).

Interface these tests assume (fixed before the code exists):

- Folders and files are read in Python through the module-level ``DISK`` object
  (``exists``, ``list_dir``, ``read_text``); locations are expanded from the module's
  ``ENVIRON``. The tests set ``LOCALAPPDATA`` and ``PNPM_HOME`` to invented temporary
  folders, and replace ``DISK.list_dir`` / ``DISK.read_text`` to raise for chosen paths,
  calling the original for every other path.
- The home is ``PNPM_HOME`` (non-blank), else the raw ``%LOCALAPPDATA%\\pnpm``;
  ``folder_from`` is ``PNPM_HOME`` or ``default``. The global folder is
  ``<home>\\global``; absent, pnpm is ``{state: "not_present", looked_in: [raw path]}``.
- Each folder of ``<home>\\global`` whose name is all digits is one part, labelled with
  the digits; every other entry is skipped and named once in ``not_checked`` ("pnpm
  global entries with a non-numeric name"). Each part is read as one M1 global folder:
  the keys of ``dependencies`` in its ``package.json`` are the globals, each version is
  ``version`` of ``node_modules\\<name>\\package.json``.
- Source ``pnpm_packages``; detail list ``pnpm_packages``; key
  ``pnpm:<label>|<name case-folded>``; fields ``name``, ``version``, ``folder``,
  ``layout`` (the label). A change keeps ``source`` ``pnpm_packages`` and carries
  ``layout``.
- ``managers.pnpm`` is ``{state, status, folder_from, parts: [{source, status, count,
  reason}], count, unreadable}``, where a part's ``source`` is its label.

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

MANAGER = "pnpm"
SOURCE = "pnpm_packages"
PREFIX = "pnpm:"
RAW_GLOBAL = "%LOCALAPPDATA%\\pnpm\\global"
NOT_READ_YET = "not read yet"
NON_NUMERIC_NOTE = "non-numeric name"
RC_NOTE = "global-dir setting in the pnpm rc file"
DENIED = "Access to the path is denied (invented)"

CONTOSO = "contoso-cli"
FABRIKAM = "@fabrikam/tool"


def key(label, name):
    return f"{PREFIX}{label}|{name.casefold()}"


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def write_module(part, name, version):
    """One package folder in ``node_modules`` (a plain folder standing in for pnpm's
    junction into ``.pnpm``)."""
    folder = Path(part, "node_modules", *name.split("/"))
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": version, "description": "An invented package.",
                "main": "index.js"}
    (folder / "package.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (folder / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
    return folder


def write_part(part, dependencies, modules):
    """An invented layout folder ``<home>\\global\\<digits>`` as pnpm writes it: a
    ``package.json`` with ``dependencies``, ``node_modules`` with the globals, the
    ``.pnpm`` store and ``.bin``."""
    part = Path(part)
    part.mkdir(parents=True, exist_ok=True)
    (part / "package.json").write_text(
        json.dumps({"dependencies": dict(dependencies)}, indent=2), encoding="utf-8")
    store = part / "node_modules" / ".pnpm" / "left-pad@1.3.0" / "node_modules" / "left-pad"
    store.mkdir(parents=True, exist_ok=True)
    (store / "package.json").write_text(
        json.dumps({"name": "left-pad", "version": "1.3.0"}), encoding="utf-8")
    bin_folder = part / "node_modules" / ".bin"
    bin_folder.mkdir(parents=True, exist_ok=True)
    (bin_folder / "contoso-cli.cmd").write_text("@echo invented\n", encoding="utf-8")
    for name, version in modules.items():
        write_module(part, name, version)
    return part


def write_standard_home(home):
    """The K2 shape: ``global\\5`` with two globals, ``.pnpm``, a hoisted ``left-pad``,
    and a file ``global\\tmp.txt``."""
    global_folder = Path(home) / "global"
    write_part(global_folder / "5", {CONTOSO: "^1.2.0", FABRIKAM: "^3.0.0"},
               {CONTOSO: "1.2.3", FABRIKAM: "3.0.1", "left-pad": "1.3.0"})
    (global_folder / "tmp.txt").write_text("invented\n", encoding="utf-8")
    return global_folder


class PnpmTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def local_app_data(self):
        """An invented %LOCALAPPDATA% that exists, without a pnpm folder."""
        folder = self.temp_folder() / "Local"
        folder.mkdir(parents=True)
        return folder

    def collect_with(self, environ, data_dir=None, now=NOW):
        with mock.patch.object(self.packages, "ENVIRON", dict(environ)):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def items(self, summary):
        items = self.detail(summary).get(SOURCE)
        self.assertIsInstance(items, list, f"detail {SOURCE}: {items!r}")
        return self.by_key(items)

    def pnpm(self, summary):
        return self.manager(summary, MANAGER)

    def pnpm_changes(self, summary):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith(PREFIX)]

    def notes_about(self, summary, words):
        return [item for item in self.not_checked(summary)
                if words.casefold() in note_text(item)]

    def parts(self, manager):
        parts = manager.get("parts")
        self.assertIsInstance(parts, list, manager)
        by_label = {}
        for entry in parts:
            self.assertIsInstance(entry, dict, parts)
            self.assertNotIn(entry.get("source"), by_label, parts)
            by_label[entry.get("source")] = entry
        return by_label

    def failing_read_text(self, failing_paths, error):
        original = self.packages.DISK.read_text

        def read_text(path, *args, **kwargs):
            if any(same_path(path, failing) for failing in failing_paths):
                raise error
            return original(path, *args, **kwargs)

        return mock.patch.object(self.packages.DISK, "read_text", read_text)

    def failing_list_dir(self, failing_paths, error):
        original = self.packages.DISK.list_dir

        def list_dir(path, *args, **kwargs):
            if any(same_path(path, failing) for failing in failing_paths):
                raise error
            return original(path, *args, **kwargs)

        return mock.patch.object(self.packages.DISK, "list_dir", list_dir)

    def assert_standard(self, summary, folder_from):
        """The K2 result: two globals of layout 5, no stray, both notes, part 5 read."""
        contoso, fabrikam = key("5", CONTOSO), key("5", FABRIKAM)
        items = self.items(summary)
        self.assertEqual(set(items), {contoso, fabrikam}, sorted(map(str, items)))
        self.assertEqual(items[contoso].get("name"), CONTOSO, items[contoso])
        self.assertEqual(items[contoso].get("version"), "1.2.3", items[contoso])
        self.assertEqual(items[contoso].get("layout"), "5", items[contoso])
        self.assertTrue(str(items[contoso].get("folder")).casefold().endswith(
            "\\node_modules\\contoso-cli"), items[contoso])
        self.assertEqual(items[fabrikam].get("name"), FABRIKAM, items[fabrikam])
        self.assertEqual(items[fabrikam].get("version"), "3.0.1", items[fabrikam])
        self.assertEqual(items[fabrikam].get("layout"), "5", items[fabrikam])
        stray = [name for name in map(str, items)
                 if ".pnpm" in name or "left-pad" in name or ".bin" in name
                 or "tmp" in name]
        self.assertEqual(stray, [], sorted(map(str, items)))

        pnpm = self.pnpm(summary)
        self.assertEqual(pnpm.get("state"), "read", pnpm)
        self.assertEqual(pnpm.get("folder_from"), folder_from, pnpm)
        self.assertEqual(pnpm.get("count"), 2, pnpm)
        parts = self.parts(pnpm)
        self.assertEqual(set(parts), {"5"}, parts)
        self.assertEqual(parts["5"].get("status"), "read", parts)
        self.assertEqual(len(self.notes_about(summary, NON_NUMERIC_NOTE)), 1,
                         summary.get("not_checked"))
        self.assertEqual(len(self.notes_about(summary, RC_NOTE)), 1,
                         summary.get("not_checked"))


class TestPnpm(PnpmTestCase):
    def test_absent_is_not_present(self):
        summary = self.collect_with({"LOCALAPPDATA": str(self.local_app_data())})

        pnpm = self.pnpm(summary)
        self.assertEqual(set(pnpm), {"state", "looked_in"}, pnpm)
        self.assertEqual(pnpm["state"], "not_present", pnpm)
        looked_in = pnpm["looked_in"]
        self.assertIsInstance(looked_in, list, pnpm)
        self.assertEqual([str(path).casefold() for path in looked_in],
                         [RAW_GLOBAL.casefold()], pnpm)
        self.assertEqual(self.notes_with(summary, MANAGER, NOT_READ_YET), [],
                         summary.get("not_checked"))
        self.assertNotEqual(self.source(summary, SOURCE).get("status"), "unreadable")
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith(PREFIX)]
        self.assertEqual(found, [], found)

    def test_globals_of_layout_folder(self):
        home = self.temp_folder() / "invented-pnpm-home"
        write_standard_home(home)
        summary = self.collect_with({"PNPM_HOME": str(home)})

        self.assert_standard(summary, "PNPM_HOME")

        with self.subTest(case="the same home under %LOCALAPPDATA%\\pnpm"):
            local = self.local_app_data()
            write_standard_home(local / "pnpm")
            summary = self.collect_with({"LOCALAPPDATA": str(local)})

            self.assert_standard(summary, "default")

    def test_partly_read_and_changes(self):
        home = self.temp_folder() / "invented-pnpm-home"
        global_folder = home / "global"
        part5 = write_part(global_folder / "5", {CONTOSO: "^1.2.0"}, {CONTOSO: "1.2.3"})
        part6 = write_part(global_folder / "6", {FABRIKAM: "^3.0.0"}, {FABRIKAM: "3.0.1"})
        contoso, fabrikam = key("5", CONTOSO), key("6", FABRIKAM)
        environ = {"PNPM_HOME": str(home)}
        data_dir = self.data_dir()

        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(set(self.items(first)), {contoso, fabrikam},
                         sorted(map(str, self.items(first))))
        self.assertEqual(self.pnpm_changes(first), [])

        write_module(part5, CONTOSO, "1.3.0")
        with self.failing_read_text([part6 / "package.json"], PermissionError(DENIED)):
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

        pnpm = self.pnpm(second)
        self.assertEqual(pnpm.get("state"), "read", pnpm)
        self.assertEqual(self.source(second, SOURCE).get("status"), "read",
                         self.source(second, SOURCE))
        self.assertIn("count", pnpm, pnpm)
        self.assertIsNone(pnpm["count"], pnpm)

        items = self.items(second)
        self.assertIn(fabrikam, items, sorted(map(str, items)))
        self.assertIs(items[fabrikam].get("from_baseline"), True, items[fabrikam])
        self.assertEqual(items[fabrikam].get("version"), "3.0.1", items[fabrikam])

        changes = self.pnpm_changes(second)
        self.assertEqual([(c.get("key"), c.get("change")) for c in changes],
                         [(contoso, "changed")], changes)
        changed = changes[0]
        self.assertEqual(changed.get("source"), SOURCE, changed)
        self.assertEqual(changed.get("layout"), "5", changed)

        with self.subTest(case="both parts unreadable"):
            failing = [part5 / "package.json", part6 / "package.json"]
            with self.failing_read_text(failing, PermissionError(DENIED)):
                third = self.collect_with(environ, data_dir=data_dir,
                                          now=NOW + timedelta(days=2))

            pnpm = self.pnpm(third)
            self.assertEqual(pnpm.get("state"), "unreadable", pnpm)
            self.assertNotEqual(pnpm.get("state"), "not_present", pnpm)
            self.assertEqual(self.source(third, SOURCE).get("status"), "unreadable",
                             self.source(third, SOURCE))

        with self.subTest(case="the global folder cannot be listed"):
            with self.failing_list_dir([global_folder], OSError(DENIED)):
                fourth = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=3))

            pnpm = self.pnpm(fourth)
            self.assertEqual(pnpm.get("state"), "unreadable", pnpm)
            self.assertNotEqual(pnpm.get("state"), "not_present", pnpm)
            self.assertEqual(self.source(fourth, SOURCE).get("status"), "unreadable",
                             self.source(fourth, SOURCE))
            self.assertIn("count", pnpm, pnpm)
            self.assertIsNone(pnpm["count"], pnpm)
            items = self.items(fourth)
            for item_key in (contoso, fabrikam):
                self.assertIn(item_key, items, sorted(map(str, items)))
                self.assertIs(items[item_key].get("from_baseline"), True, items[item_key])
            removed = [c for c in self.pnpm_changes(fourth) if c.get("change") == "removed"]
            self.assertEqual(removed, [], fourth.get("changes"))


class TestPnpmEdges(PnpmTestCase):
    """Plan 083 M2 code-review round 1 (judge fix): a global folder with no layout
    folder is empty, never unreadable; a layout folder that cannot be listed is
    unreadable, never empty, and keeps its baseline items."""

    def test_no_layout_folder_is_empty(self):
        home = self.temp_folder() / "invented-pnpm-home"
        global_folder = home / "global"
        global_folder.mkdir(parents=True)
        (global_folder / "tmp.txt").write_text("invented\n", encoding="utf-8")
        summary = self.collect_with({"PNPM_HOME": str(home)})

        self.assertEqual(self.source(summary, SOURCE).get("status"), "empty",
                         self.source(summary, SOURCE))
        pnpm = self.pnpm(summary)
        self.assertNotIn(pnpm.get("state"), ("not_present", "unreadable"), pnpm)
        self.assertEqual(pnpm.get("count"), 0, pnpm)
        self.assertEqual(pnpm.get("parts"), [], pnpm)
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith(PREFIX)]
        self.assertEqual(found, [], found)

    def test_layout_folder_cannot_be_listed(self):
        home = self.temp_folder() / "invented-pnpm-home"
        global_folder = home / "global"
        write_part(global_folder / "5", {CONTOSO: "^1.2.0"}, {CONTOSO: "1.2.3"})
        part6 = write_part(global_folder / "6", {FABRIKAM: "^3.0.0"}, {FABRIKAM: "3.0.1"})
        contoso, fabrikam = key("5", CONTOSO), key("6", FABRIKAM)
        environ = {"PNPM_HOME": str(home)}
        data_dir = self.data_dir()
        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(set(self.items(first)), {contoso, fabrikam},
                         sorted(map(str, self.items(first))))

        with self.failing_list_dir([part6], OSError(DENIED)):
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

        pnpm = self.pnpm(second)
        self.assertEqual(pnpm.get("state"), "read", pnpm)
        self.assertEqual(self.source(second, SOURCE).get("status"), "read",
                         self.source(second, SOURCE))
        self.assertIsNone(pnpm.get("count"), pnpm)
        parts = self.parts(pnpm)
        self.assertEqual(parts["5"].get("status"), "read", parts)
        self.assertEqual(parts["6"].get("status"), "unreadable", parts)
        self.assertTrue(parts["6"].get("reason"), parts)
        items = self.items(second)
        self.assertIn(fabrikam, items, sorted(map(str, items)))
        self.assertIs(items[fabrikam].get("from_baseline"), True, items[fabrikam])
        removed = [c for c in self.pnpm_changes(second) if c.get("change") == "removed"]
        self.assertEqual(removed, [], second.get("changes"))
        self.assertEqual(self.notes_about(second, NON_NUMERIC_NOTE), [],
                         second.get("not_checked"))


class TestPnpmFinalReview(PnpmTestCase):
    """Plan 083 final review (judge fix): a PNPM_HOME that is a file is unreadable,
    never absent, so its baseline items are kept; the rc-file note appears only for
    the states read and not_present."""

    def test_home_is_a_file(self):
        home = self.temp_folder() / "invented-pnpm-home"
        write_part(home / "global" / "5", {CONTOSO: "^1.2.0"}, {CONTOSO: "1.2.3"})
        contoso = key("5", CONTOSO)
        environ = {"PNPM_HOME": str(home)}
        data_dir = self.data_dir()
        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(set(self.items(first)), {contoso})

        shutil.rmtree(home)
        home.write_text("not a folder\n", encoding="utf-8")
        second = self.collect_with(environ, data_dir=data_dir,
                                   now=NOW + timedelta(days=1))

        pnpm = self.pnpm(second)
        self.assertEqual(pnpm.get("state"), "unreadable", pnpm)
        items = self.items(second)
        self.assertIn(contoso, items, sorted(map(str, items)))
        self.assertIs(items[contoso].get("from_baseline"), True, items[contoso])
        removed = [c for c in self.pnpm_changes(second) if c.get("change") == "removed"]
        self.assertEqual(removed, [], second.get("changes"))

    def test_ancestor_cannot_be_checked_is_not_present(self):
        locked = self.temp_folder() / "invented-locked"
        home = locked / "pnpm"
        original = self.packages.DISK.exists

        def exists(path, *args, **kwargs):
            if same_path(path, locked):
                raise PermissionError(DENIED)
            return original(path, *args, **kwargs)

        with mock.patch.object(self.packages.DISK, "exists", exists):
            summary = self.collect_with({"PNPM_HOME": str(home)})

        pnpm = self.pnpm(summary)
        self.assertEqual(pnpm.get("state"), "not_present", pnpm)
        self.assertNotEqual(self.source(summary, SOURCE).get("status"), "unreadable",
                            self.source(summary, SOURCE))

    def test_unreadable_has_no_rc_note(self):
        home = self.temp_folder() / "invented-pnpm-home"
        part5 = write_part(home / "global" / "5", {CONTOSO: "^1.2.0"}, {CONTOSO: "1.2.3"})
        with self.failing_read_text([part5 / "package.json"], PermissionError(DENIED)):
            summary = self.collect_with({"PNPM_HOME": str(home)})

        self.assertEqual(self.pnpm(summary).get("state"), "unreadable", self.pnpm(summary))
        self.assertEqual(self.notes_about(summary, RC_NOTE), [],
                         summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

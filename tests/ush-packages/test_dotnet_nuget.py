"""dotnet global tools and the NuGet global packages folder read offline (plan 079, M1,
K1-K6).

Interface these tests assume (fixed before the code exists):

- Folders are read in Python through the module-level ``DISK`` object (``exists(path)``,
  ``list_dir(path)``: names, ``OSError`` on failure); locations are expanded from the
  module's ``ENVIRON``. The tests set ``USERPROFILE`` (and ``DOTNET_CLI_HOME`` /
  ``NUGET_PACKAGES`` where named) to invented temporary folders, and replace
  ``DISK.list_dir`` / ``DISK.exists`` to raise for one chosen path, calling the original
  for every other path.
- dotnet-tools: the tools folder is ``DOTNET_CLI_HOME`` + ``\\.dotnet\\tools`` (non-blank
  variable), else the raw ``%USERPROFILE%\\.dotnet\\tools``; its store is
  ``<tools>\\.store\\<id>\\<version>``; every version folder is complete. Source
  ``dotnet_tools``; detail list ``dotnet_tools``; key ``dotnet-tools:<id case-folded>``.
- nuget: the packages folder is ``NUGET_PACKAGES`` (non-blank), else the raw
  ``%USERPROFILE%\\.nuget\\packages``, laid out ``<id>\\<version>``; a version is complete
  when its folder holds a file named exactly ``.nupkg.metadata``. Source
  ``nuget_packages``; detail list ``nuget_packages``; key ``nuget:<id case-folded>``.
- Entries whose name starts with ``.`` are skipped at the id and version levels.
- Per id: the highest complete version, ``versions_found`` = complete version folders.
- ``managers.dotnet-tools`` / ``managers.nuget`` are ``{state: "not_present", looked_in:
  [raw path]}`` when the folder is absent, else ``{state, status, folder_from:
  <variable name>|"default", count, unreadable, incomplete}``.

PowerShell never starts; every folder and file is written by hand in a temporary folder;
every id, version, hash and path is invented.
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

DOTNET = "dotnet-tools"
NUGET = "nuget"
DOTNET_SOURCE = "dotnet_tools"
NUGET_SOURCE = "nuget_packages"
DOTNET_PREFIX = "dotnet-tools:"
NUGET_PREFIX = "nuget:"
RAW_DOTNET_FOLDER = "%USERPROFILE%\\.dotnet\\tools"
RAW_NUGET_FOLDER = "%USERPROFILE%\\.nuget\\packages"
NOT_READ_YET = "not read yet"
INCOMPLETE_NOTE = "without a complete version"
INCOMPLETE_REASON = "no .nupkg.metadata"
DENIED = "Access to the path is denied (invented)"

CONTOSO_CLI = "dotnet-tools:contoso.cli"
FABRIKAM_TOOL = "dotnet-tools:fabrikam.tool"
LITWARE_TOOL = "dotnet-tools:litware.tool"
CONTOSO_JSON = "nuget:contoso.json"
FABRIKAM_HTTP = "nuget:fabrikam.http"
LITWARE_LOGGING = "nuget:litware.logging"


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def add_tool(store, tool_id, version):
    """One tool version in a dotnet tool store, laid out as the .NET SDK writes it."""
    inner = Path(store) / tool_id / version / tool_id / version / "tools" / "net8.0" / "any"
    inner.mkdir(parents=True, exist_ok=True)
    (inner / "DotnetToolSettings.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<DotNetCliTool Version="1"><Commands>'
        f'<Command Name="{tool_id}" EntryPoint="{tool_id}.dll" Runner="dotnet" />'
        '</Commands></DotNetCliTool>\n',
        encoding="utf-8")


def add_package(root, package_id, version, complete=True, named_metadata=False):
    """One package version in a NuGet global packages folder (invented content).

    ``complete``: the folder holds ``.nupkg.metadata``; ``named_metadata``: it holds a
    file ``<id>.<version>.nupkg.metadata`` instead (which does not count)."""
    folder = Path(root) / package_id / version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{package_id}.{version}.nupkg").write_bytes(b"PK\x03\x04invented")
    (folder / f"{package_id}.{version}.nupkg.sha512").write_text(
        "aW52ZW50ZWQtaGFzaA==", encoding="utf-8")
    (folder / f"{package_id}.nuspec").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<package><metadata>'
        f"<id>{package_id}</id><version>{version}</version>"
        "</metadata></package>\n",
        encoding="utf-8")
    metadata = json.dumps({"version": 2, "contentHash": "aW52ZW50ZWQtaGFzaA==",
                           "source": "https://api.nuget.org/v3/index.json"})
    if complete:
        (folder / ".nupkg.metadata").write_text(metadata, encoding="utf-8")
    if named_metadata:
        (folder / f"{package_id}.{version}.nupkg.metadata").write_text(
            metadata, encoding="utf-8")
    return folder


class DotnetNugetTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def profile(self):
        """An invented %USERPROFILE% that exists, without .dotnet and .nuget folders."""
        folder = self.temp_folder() / "Invented"
        folder.mkdir(parents=True)
        return folder

    def tools_folder(self, home):
        folder = Path(home) / ".dotnet" / "tools"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def store(self, home):
        folder = self.tools_folder(home) / ".store"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def nuget_root(self, profile):
        folder = Path(profile) / ".nuget" / "packages"
        folder.mkdir(parents=True, exist_ok=True)
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
        return [item for item in self.not_checked(summary) if word in note_text(item)]

    def failing_list_dir(self, failing_path, error):
        original = self.packages.DISK.list_dir

        def list_dir(path):
            if same_path(path, failing_path):
                raise error
            return original(path)

        return mock.patch.object(self.packages.DISK, "list_dir", list_dir)


class TestDotnetTools(DotnetNugetTestCase):
    def test_absent_is_not_present(self):
        profile = self.profile()
        summary = self.collect_with({"USERPROFILE": str(profile)})

        self.assertEqual(self.manager(summary, DOTNET),
                         {"state": "not_present", "looked_in": [RAW_DOTNET_FOLDER]})
        self.assertEqual(self.manager(summary, NUGET),
                         {"state": "not_present", "looked_in": [RAW_NUGET_FOLDER]})
        for word in ("dotnet", "nuget"):
            for item in self.notes_about(summary, word):
                text = note_text(item)
                self.assertNotIn(NOT_READ_YET, text, item)
                self.assertNotIn("unreadable", text, item)
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith((DOTNET_PREFIX, NUGET_PREFIX))]
        self.assertEqual(found, [], found)

    def test_highest_version_per_tool(self):
        profile = self.profile()
        store = self.store(profile)
        (store.parent / "contoso-cli.exe").write_bytes(b"MZinvented")
        add_tool(store, "contoso.cli", "1.2.0")
        add_tool(store, "contoso.cli", "1.10.0")
        add_tool(store, "fabrikam.tool", "3.0.0")
        # The SDK's staging folder: it would look like a tool if it were not skipped.
        (store / ".stage" / "0f1e2d3c" / "9.9.9").mkdir(parents=True)

        summary = self.collect_with({"USERPROFILE": str(profile)})

        items = self.items(summary, DOTNET_SOURCE)
        self.assertEqual(set(items), {CONTOSO_CLI, FABRIKAM_TOOL}, sorted(map(str, items)))
        self.assertEqual(items[CONTOSO_CLI].get("version"), "1.10.0", items[CONTOSO_CLI])
        self.assertEqual(items[CONTOSO_CLI].get("versions_found"), 2, items[CONTOSO_CLI])
        self.assertEqual(items[FABRIKAM_TOOL].get("version"), "3.0.0", items[FABRIKAM_TOOL])
        self.assertEqual(items[FABRIKAM_TOOL].get("versions_found"), 1,
                         items[FABRIKAM_TOOL])
        stage = [key for key in map(str, items) if ".stage" in key.casefold()]
        self.assertEqual(stage, [], sorted(map(str, items)))

        with self.subTest(case="a file in an id folder is no version"):
            profile = self.profile()
            store = self.store(profile)
            add_tool(store, "contoso.cli", "1.2.0")
            (store / "contoso.cli" / "9.9.9.tmp").write_text("invented", encoding="utf-8")
            (store / "litware.tool").mkdir()
            (store / "litware.tool" / "readme.txt").write_text("invented", encoding="utf-8")
            summary = self.collect_with({"USERPROFILE": str(profile)})

            items = self.items(summary, DOTNET_SOURCE)
            self.assertEqual(set(items), {CONTOSO_CLI}, sorted(map(str, items)))
            self.assertEqual(items[CONTOSO_CLI].get("version"), "1.2.0", items[CONTOSO_CLI])
            self.assertEqual(items[CONTOSO_CLI].get("versions_found"), 1, items[CONTOSO_CLI])
            dotnet = self.manager(summary, DOTNET)
            self.assertEqual(dotnet.get("incomplete"), 1, dotnet)

        with self.subTest(case="a version folder that cannot be listed is unreadable"):
            profile = self.profile()
            store = self.store(profile)
            add_tool(store, "contoso.cli", "1.2.0")
            with self.failing_list_dir(store / "contoso.cli" / "1.2.0", OSError(DENIED)):
                summary = self.collect_with({"USERPROFILE": str(profile)})

            items = self.items(summary, DOTNET_SOURCE)
            self.assertIn(CONTOSO_CLI, items, sorted(map(str, items)))
            self.assertEqual(items[CONTOSO_CLI].get("status"), "unreadable", items[CONTOSO_CLI])
            dotnet = self.manager(summary, DOTNET)
            self.assertEqual(dotnet.get("unreadable"), 1, dotnet)
            self.assertEqual(dotnet.get("incomplete"), 0, dotnet)
            named = [item for item in self.not_checked(summary)
                     if "contoso.cli" in note_text(item)
                     and DENIED.casefold() in note_text(item)]
            self.assertTrue(named, summary.get("not_checked"))

        # Added by loc-qa (plan 079): a PermissionError, not only a bare OSError, keeps
        # the version folder unreadable rather than "not a folder".
        with self.subTest(case="a version folder denied with PermissionError is unreadable"):
            profile = self.profile()
            store = self.store(profile)
            add_tool(store, "contoso.cli", "1.2.0")
            with self.failing_list_dir(store / "contoso.cli" / "1.2.0",
                                       PermissionError(DENIED)):
                summary = self.collect_with({"USERPROFILE": str(profile)})

            items = self.items(summary, DOTNET_SOURCE)
            self.assertIn(CONTOSO_CLI, items, sorted(map(str, items)))
            self.assertEqual(items[CONTOSO_CLI].get("status"), "unreadable", items[CONTOSO_CLI])
            dotnet = self.manager(summary, DOTNET)
            self.assertEqual(dotnet.get("unreadable"), 1, dotnet)
            self.assertEqual(dotnet.get("incomplete"), 0, dotnet)

        with self.subTest(case="tools folder without .store"):
            profile = self.profile()
            tools = self.tools_folder(profile)
            (tools / "contoso-cli.exe").write_bytes(b"MZinvented")
            summary = self.collect_with({"USERPROFILE": str(profile)})

            dotnet = self.manager(summary, DOTNET)
            self.assertEqual(dotnet.get("state"), "read", dotnet)
            self.assertNotEqual(dotnet.get("state"), "not_present", dotnet)
            self.assertEqual(dotnet.get("count"), 0, dotnet)
            self.assertEqual(self.items(summary, DOTNET_SOURCE), {})

    def test_variables_replace_defaults(self):
        # The default folders hold a tool and a package; they must not be looked at.
        profile = self.profile()
        add_tool(self.store(profile), "fabrikam.tool", "3.0.0")
        add_package(self.nuget_root(profile), "fabrikam.http", "2.0.0")

        cli_home = self.temp_folder() / "invented-cli-home"
        add_tool(self.store(cli_home), "contoso.cli", "1.2.0")
        packages_folder = self.temp_folder() / "invented-packages"
        packages_folder.mkdir()
        add_package(packages_folder, "contoso.json", "13.0.1")

        summary = self.collect_with({"USERPROFILE": str(profile),
                            "DOTNET_CLI_HOME": str(cli_home),
                            "NUGET_PACKAGES": str(packages_folder)})

        dotnet = self.manager(summary, DOTNET)
        self.assertEqual(dotnet.get("state"), "read", dotnet)
        self.assertEqual(dotnet.get("folder_from"), "DOTNET_CLI_HOME", dotnet)
        self.assertEqual(set(self.items(summary, DOTNET_SOURCE)), {CONTOSO_CLI})
        nuget = self.manager(summary, NUGET)
        self.assertEqual(nuget.get("state"), "read", nuget)
        self.assertEqual(nuget.get("folder_from"), "NUGET_PACKAGES", nuget)
        self.assertEqual(set(self.items(summary, NUGET_SOURCE)), {CONTOSO_JSON})

        with self.subTest(case="absent variable folders: only they are looked in"):
            absent_home = self.temp_folder() / "no-such-cli-home"
            absent_packages = self.temp_folder() / "no-such-packages"
            summary = self.collect_with({"USERPROFILE": str(profile),
                                "DOTNET_CLI_HOME": str(absent_home),
                                "NUGET_PACKAGES": str(absent_packages)})

            for name, expected, default in (
                    (DOTNET, absent_home / ".dotnet" / "tools", RAW_DOTNET_FOLDER),
                    (NUGET, absent_packages, RAW_NUGET_FOLDER)):
                manager = self.manager(summary, name)
                self.assertEqual(manager.get("state"), "not_present", manager)
                looked_in = manager.get("looked_in")
                self.assertIsInstance(looked_in, list, manager)
                self.assertEqual(len(looked_in), 1, manager)
                self.assertTrue(same_path(looked_in[0], expected), manager)
                self.assertNotIn(default.casefold(),
                                 [str(path).casefold() for path in looked_in], manager)
            found = [item for item in self.package_list(summary)
                     if str(item.get("key")).startswith((DOTNET_PREFIX, NUGET_PREFIX))]
            self.assertEqual(found, [], found)


class TestNuget(DotnetNugetTestCase):
    def test_complete_versions_only(self):
        profile = self.profile()
        root = self.nuget_root(profile)
        add_package(root, "contoso.json", "13.0.1")
        add_package(root, "contoso.json", "13.0.3", complete=False)
        add_package(root, "fabrikam.http", "2.0.0", complete=False, named_metadata=True)

        summary = self.collect_with({"USERPROFILE": str(profile)})

        items = self.items(summary, NUGET_SOURCE)
        self.assertEqual(set(items), {CONTOSO_JSON}, sorted(map(str, items)))
        self.assertEqual(items[CONTOSO_JSON].get("version"), "13.0.1", items[CONTOSO_JSON])
        self.assertEqual(items[CONTOSO_JSON].get("versions_found"), 1, items[CONTOSO_JSON])
        nuget = self.manager(summary, NUGET)
        self.assertEqual(nuget.get("incomplete"), 1, nuget)
        notes = [item for item in self.not_checked(summary)
                 if INCOMPLETE_NOTE in note_text(item)]
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn(INCOMPLETE_REASON, str(notes[0].get("reason")).casefold(), notes)

        with self.subTest(case="every version complete"):
            (root / "contoso.json" / "13.0.3" / ".nupkg.metadata").write_text(
                "{}", encoding="utf-8")
            (root / "fabrikam.http" / "2.0.0" / ".nupkg.metadata").write_text(
                "{}", encoding="utf-8")
            summary = self.collect_with({"USERPROFILE": str(profile)})

            self.assertEqual(self.manager(summary, NUGET).get("incomplete"), 0,
                             self.manager(summary, NUGET))
            notes = [item for item in self.not_checked(summary)
                     if INCOMPLETE_NOTE in note_text(item)]
            self.assertEqual(notes, [], summary.get("not_checked"))

    def test_unlistable_root_and_id(self):
        with self.subTest(case="the root cannot be listed"):
            profile = self.profile()
            root = self.nuget_root(profile)
            add_package(root, "contoso.json", "13.0.1")
            add_package(root, "fabrikam.http", "2.0.0")
            environ = {"USERPROFILE": str(profile)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, NUGET_SOURCE)),
                             {CONTOSO_JSON, FABRIKAM_HTTP})

            with self.failing_list_dir(root, OSError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=1))

            nuget = self.manager(second, NUGET)
            self.assertEqual(nuget.get("state"), "unreadable", nuget)
            self.assertNotEqual(nuget.get("state"), "not_present", nuget)
            self.assertIn("count", nuget, nuget)
            self.assertIsNone(nuget["count"], nuget)
            self.assertEqual(self.source(second, NUGET_SOURCE).get("status"), "unreadable")
            reasons = [item for item in self.notes_about(second, "nuget")
                       if DENIED.casefold() in note_text(item)]
            self.assertTrue(reasons, second.get("not_checked"))

            items = self.items(second, NUGET_SOURCE)
            for key, version in ((CONTOSO_JSON, "13.0.1"), (FABRIKAM_HTTP, "2.0.0")):
                self.assertIn(key, items, sorted(map(str, items)))
                self.assertIs(items[key].get("from_baseline"), True, items[key])
                self.assertEqual(items[key].get("version"), version, items[key])
            removed = [change for change in self.changes_with(second, NUGET_PREFIX)
                       if change.get("change") == "removed"]
            self.assertEqual(removed, [], second.get("changes"))

        with self.subTest(case="an id folder and a completeness check fail"):
            profile = self.profile()
            root = self.nuget_root(profile)
            contoso_folder = add_package(root, "contoso.json", "13.0.1")
            add_package(root, "fabrikam.http", "2.0.0")
            environ = {"USERPROFILE": str(profile)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, NUGET_SOURCE)),
                             {CONTOSO_JSON, FABRIKAM_HTTP})

            metadata_path = contoso_folder / ".nupkg.metadata"
            original_exists = self.packages.DISK.exists

            def exists(path):
                if same_path(path, metadata_path):
                    raise PermissionError(DENIED)
                return original_exists(path)

            with self.failing_list_dir(root / "fabrikam.http", OSError(DENIED)), \
                    mock.patch.object(self.packages.DISK, "exists", exists):
                second = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=1))

            items = self.items(second, NUGET_SOURCE)
            for key in (CONTOSO_JSON, FABRIKAM_HTTP):
                self.assertIn(key, items, sorted(map(str, items)))
                self.assertEqual(items[key].get("status"), "unreadable", items[key])
            nuget = self.manager(second, NUGET)
            self.assertEqual(nuget.get("unreadable"), 2, nuget)
            self.assertEqual(nuget.get("incomplete"), 0, nuget)
            for name in ("contoso.json", "fabrikam.http"):
                named = [item for item in self.not_checked(second)
                         if name in note_text(item)]
                self.assertTrue(named, (name, second.get("not_checked")))
            changed = [change for change in self.changes_with(second, NUGET_PREFIX)
                       if change.get("change") == "changed"]
            self.assertEqual(changed, [], second.get("changes"))

    def test_changes(self):
        profile = self.profile()
        store = self.store(profile)
        root = self.nuget_root(profile)
        environ = {"USERPROFILE": str(profile)}
        data_dir = self.data_dir()

        add_tool(store, "contoso.cli", "1.2.0")
        add_tool(store, "fabrikam.tool", "3.0.0")
        add_package(root, "contoso.json", "13.0.1")
        add_package(root, "fabrikam.http", "2.0.0")
        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(self.changes_with(first, DOTNET_PREFIX), [])
        self.assertEqual(self.changes_with(first, NUGET_PREFIX), [])

        # Raised version, removed id, added id, in each manager.
        add_tool(store, "contoso.cli", "1.10.0")
        shutil.rmtree(store / "contoso.cli" / "1.2.0")
        shutil.rmtree(store / "fabrikam.tool")
        add_tool(store, "litware.tool", "0.4.0")
        add_package(root, "contoso.json", "13.0.3")
        shutil.rmtree(root / "contoso.json" / "13.0.1")
        shutil.rmtree(root / "fabrikam.http")
        add_package(root, "litware.logging", "5.1.0")
        second = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.change_kinds(second, DOTNET_PREFIX),
                         sorted([(CONTOSO_CLI, "changed"), (FABRIKAM_TOOL, "removed"),
                                 (LITWARE_TOOL, "added")]),
                         second.get("changes"))
        self.assertEqual(self.change_kinds(second, NUGET_PREFIX),
                         sorted([(CONTOSO_JSON, "changed"), (FABRIKAM_HTTP, "removed"),
                                 (LITWARE_LOGGING, "added")]),
                         second.get("changes"))

        with self.subTest(case="an unchanged run"):
            third = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=2))
            self.assertEqual(self.changes_with(third, DOTNET_PREFIX), [])
            self.assertEqual(self.changes_with(third, NUGET_PREFIX), [])

        with self.subTest(case="the folders are gone"):
            shutil.rmtree(profile / ".dotnet")
            shutil.rmtree(profile / ".nuget")
            fourth = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=3))
            self.assertEqual(self.manager(fourth, DOTNET).get("state"), "not_present")
            self.assertEqual(self.manager(fourth, NUGET).get("state"), "not_present")
            self.assertEqual(self.change_kinds(fourth, DOTNET_PREFIX),
                             sorted([(CONTOSO_CLI, "removed"), (LITWARE_TOOL, "removed")]),
                             fourth.get("changes"))
            self.assertEqual(self.change_kinds(fourth, NUGET_PREFIX),
                             sorted([(CONTOSO_JSON, "removed"),
                                     (LITWARE_LOGGING, "removed")]),
                             fourth.get("changes"))


if __name__ == "__main__":
    unittest.main()

"""Chocolatey packages and classic vcpkg packages read offline from disk (plan 080, M1,
K1-K7).

Interface these tests assume (fixed before the code exists):

- Folders and files are read in Python through the module-level ``DISK`` object
  (``exists(path)``, ``list_dir(path)``: names, ``OSError`` on failure;
  ``read_text(path)``); locations are expanded from the module's ``ENVIRON``. The tests
  set ``ProgramData``, ``LOCALAPPDATA``, ``ChocolateyInstall`` and ``VCPKG_ROOT`` to
  invented temporary folders, and replace ``DISK.list_dir`` / ``DISK.read_text`` to raise
  for one chosen path, calling the original for every other path.
- choco: the root is ``ChocolateyInstall`` (non-blank), else the raw
  ``%ProgramData%\\chocolatey``; each folder of ``<root>\\lib`` (names starting with ``.``
  skipped, files skipped) holding ``<folder>\\<folder>.nuspec`` is a package, its ``id``
  and ``version`` read from the nuspec (any namespace). Source ``choco_packages``; detail
  list ``choco_packages``; key ``choco:<lib folder name case-folded>``.
- vcpkg: the root is ``VCPKG_ROOT`` (non-blank), else the first non-blank line of
  ``%LOCALAPPDATA%\\vcpkg\\vcpkg.path.txt``; the status database is
  ``<root>\\installed\\vcpkg\\status`` with the all-digit files of
  ``<root>\\installed\\vcpkg\\updates\\`` applied after it in numeric order. Source
  ``vcpkg_packages``; detail list ``vcpkg_packages``; key
  ``vcpkg:<Package>:<Architecture>`` case-folded.
- ``managers.choco`` is ``{state, status, folder_from, count, unreadable, incomplete}``,
  ``managers.vcpkg`` is ``{state, status, folder_from, count, unreadable, update_files}``; each is
  ``{state: "not_present", looked_in: [...]}`` when nothing was found.

PowerShell never starts; every folder and file is written by hand in a temporary folder;
every package id, version, triplet and path is invented.
"""

import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, PackagesTestCase, note_text, packages_fake

CHOCO = "choco"
VCPKG = "vcpkg"
CHOCO_SOURCE = "choco_packages"
VCPKG_SOURCE = "vcpkg_packages"
CHOCO_PREFIX = "choco:"
VCPKG_PREFIX = "vcpkg:"
RAW_CHOCO_ROOT = "%ProgramData%\\chocolatey"
PATH_FILE_NAME = "vcpkg.path.txt"
NOT_READ_YET = "not read yet"
NO_NUSPEC_NOTE = "without a nuspec"
NON_NUMERIC_NOTE = "non-numeric name"
DENIED = "Access to the path is denied (invented)"
NUSPEC_NS = "http://schemas.microsoft.com/packaging/2015/06/nuspec.xsd"

CONTOSO_CLI = "choco:contoso.cli"
FABRIKAM_TOOL = "choco:fabrikam.tool"
LITWARE_PKG = "choco:litware.pkg"
ZLIB = "vcpkg:zlib:x64-windows"
FMT = "vcpkg:fmt:x64-windows"
CURL = "vcpkg:curl:x86-windows"


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def nuspec_text(package_id, version, namespace=NUSPEC_NS):
    """The text of an invented ``.nuspec``; ``version`` None leaves the element out."""
    xmlns = f' xmlns="{namespace}"' if namespace else ""
    version_line = f"    <version>{version}</version>\n" if version is not None else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f"<package{xmlns}>\n"
        "  <metadata>\n"
        f"    <id>{package_id}</id>\n"
        f"{version_line}"
        f"    <title>{package_id} (invented)</title>\n"
        "    <authors>Invented Authors</authors>\n"
        "    <description>An invented package.</description>\n"
        "  </metadata>\n"
        "</package>\n"
    )


def add_choco(lib, folder_name, package_id=None, version="1.0.0", namespace=NUSPEC_NS,
              nuspec=True, text=None):
    """One package folder in a Chocolatey ``lib`` folder, laid out as choco writes it.

    ``nuspec`` False leaves the ``<folder>.nuspec`` out; ``text`` replaces its content."""
    folder = Path(lib) / folder_name
    (folder / "tools").mkdir(parents=True, exist_ok=True)
    (folder / "tools" / "chocolateyinstall.ps1").write_text(
        "Write-Host 'invented'\n", encoding="utf-8")
    (folder / f"{folder_name}.nupkg").write_bytes(b"PK\x03\x04invented")
    if nuspec:
        content = text if text is not None else nuspec_text(
            package_id or folder_name, version, namespace)
        (folder / f"{folder_name}.nuspec").write_text(content, encoding="utf-8")
    return folder


def paragraph(package, architecture, version=None, status="install ok installed",
              port_version=None, feature=None):
    """One paragraph of a vcpkg status database (invented values)."""
    lines = [f"Package: {package}"]
    if feature is not None:
        lines.append(f"Feature: {feature}")
    if version is not None:
        lines.append(f"Version: {version}")
    if port_version is not None:
        lines.append(f"Port-Version: {port_version}")
    lines.append(f"Architecture: {architecture}")
    lines.append("Multi-Arch: same")
    if feature is None:
        lines.append("Abi: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    lines.append(f"Description: An invented {package} port")
    lines.append(" continued on a second line")
    lines.append(f"Status: {status}")
    return "\n".join(lines) + "\n"


def database(*paragraphs):
    return "\n".join(paragraphs)


ZLIB_INSTALLED = paragraph("zlib", "x64-windows", "1.3.1")
FMT_INSTALLED = paragraph("fmt", "x64-windows", "10.2.1", port_version="2")
FMT_FEATURE = paragraph("fmt", "x64-windows", feature="json")
CURL_NOT_INSTALLED = paragraph("curl", "x86-windows", "8.4.0",
                               status="purge ok not-installed")


class ChocoVcpkgTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def program_data(self):
        """An invented %ProgramData% that exists, without a chocolatey folder."""
        folder = self.temp_folder() / "ProgramData"
        folder.mkdir(parents=True)
        return folder

    def local_app_data(self):
        """An invented %LOCALAPPDATA% that exists, without a vcpkg folder."""
        folder = self.temp_folder() / "Local"
        folder.mkdir(parents=True)
        return folder

    def choco_lib(self, root):
        lib = Path(root) / "lib"
        lib.mkdir(parents=True, exist_ok=True)
        return lib

    def vcpkg_root(self, status_text=None, updates=None):
        """An invented classic vcpkg root; ``updates`` maps file names to their text."""
        root = self.temp_folder() / "vcpkg"
        root.mkdir(parents=True)
        (root / "vcpkg.exe").write_bytes(b"MZinvented")
        if status_text is not None or updates:
            info = root / "installed" / "vcpkg"
            info.mkdir(parents=True)
            if status_text is not None:
                (info / "status").write_text(status_text, encoding="utf-8")
            if updates:
                (info / "updates").mkdir()
                for name, text in updates.items():
                    (info / "updates" / name).write_text(text, encoding="utf-8")
        return root

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

    def reason_named(self, summary, source, reason):
        """``reason`` appears in a ``not_checked`` entry or in the source's own reason."""
        texts = [note_text(item) for item in self.not_checked(summary)]
        texts.append(str(self.source(summary, source).get("reason")).casefold())
        return any(reason.casefold() in text for text in texts)

    def failing_list_dir(self, failing_path, error):
        original = self.packages.DISK.list_dir

        def list_dir(path, *args, **kwargs):
            if same_path(path, failing_path):
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

    def assert_carried(self, summary, manager_name, source, prefix, expected):
        """The source is unreadable, ``count`` null, ``expected`` (key -> version) kept
        ``from_baseline`` with no ``removed`` change."""
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


class TestChoco(ChocoVcpkgTestCase):
    def test_absent_is_not_present(self):
        program_data = self.program_data()
        local = self.local_app_data()
        summary = self.collect_with({"ProgramData": str(program_data),
                                     "LOCALAPPDATA": str(local)})

        choco = self.manager(summary, CHOCO)
        self.assertEqual(choco.get("state"), "not_present", choco)
        self.assertEqual(sorted(choco), ["looked_in", "state"], choco)
        self.assertEqual([str(path).casefold() for path in choco.get("looked_in")],
                         [RAW_CHOCO_ROOT.casefold()], choco)

        vcpkg = self.manager(summary, VCPKG)
        self.assertEqual(vcpkg.get("state"), "not_present", vcpkg)
        self.assertEqual(sorted(vcpkg), ["looked_in", "state"], vcpkg)
        looked_in = vcpkg.get("looked_in")
        self.assertIsInstance(looked_in, list, vcpkg)
        self.assertTrue(looked_in, vcpkg)
        self.assertTrue(any(PATH_FILE_NAME in str(path).casefold() for path in looked_in),
                        vcpkg)

        for word in ("choco", "vcpkg"):
            for item in self.notes_about(summary, word):
                text = note_text(item)
                self.assertNotIn(NOT_READ_YET, text, item)
                self.assertNotIn("unreadable", text, item)
        for source in (CHOCO_SOURCE, VCPKG_SOURCE):
            self.assertNotEqual(self.source(summary, source).get("status"), "unreadable")
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith((CHOCO_PREFIX, VCPKG_PREFIX))]
        self.assertEqual(found, [], found)

    def test_packages_from_nuspec(self):
        program_data = self.program_data()
        lib = self.choco_lib(program_data / "chocolatey")
        add_choco(lib, "contoso.cli", "Contoso.Cli", "1.10.0", namespace=NUSPEC_NS)
        add_choco(lib, "fabrikam.tool", "fabrikam.tool", "3.0.0", namespace=None)
        add_choco(lib, "litware.pkg", nuspec=False)
        # Chocolatey's own hidden folder: it would look like a package if not skipped.
        add_choco(lib, ".chocolatey", ".chocolatey", "9.9.9")
        (lib / "notes.txt").write_text("invented", encoding="utf-8")

        summary = self.collect_with({"ProgramData": str(program_data)})

        items = self.items(summary, CHOCO_SOURCE)
        self.assertEqual(set(items), {CONTOSO_CLI, FABRIKAM_TOOL}, sorted(map(str, items)))
        self.assertEqual(items[CONTOSO_CLI].get("name"), "Contoso.Cli", items[CONTOSO_CLI])
        self.assertEqual(items[CONTOSO_CLI].get("version"), "1.10.0", items[CONTOSO_CLI])
        self.assertTrue(str(items[CONTOSO_CLI].get("folder")).casefold().endswith(
            "\\lib\\contoso.cli"), items[CONTOSO_CLI])
        self.assertEqual(items[FABRIKAM_TOOL].get("version"), "3.0.0", items[FABRIKAM_TOOL])
        stray = [key for key in map(str, items)
                 if "litware" in key or "chocolatey" in key or "notes" in key]
        self.assertEqual(stray, [], sorted(map(str, items)))

        choco = self.manager(summary, CHOCO)
        self.assertEqual(choco.get("state"), "read", choco)
        self.assertEqual(choco.get("folder_from"), "default", choco)
        self.assertEqual(choco.get("count"), 2, choco)
        self.assertEqual(choco.get("incomplete"), 1, choco)
        self.assertEqual(choco.get("unreadable"), 0, choco)
        notes = self.notes_about(summary, NO_NUSPEC_NOTE)
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        lib_bad = self.notes_with(summary, "lib-bad", "lib-bkp")
        self.assertEqual(len(lib_bad), 1, summary.get("not_checked"))

        with self.subTest(case="a root without lib"):
            program_data = self.program_data()
            (program_data / "chocolatey" / "bin").mkdir(parents=True)
            summary = self.collect_with({"ProgramData": str(program_data)})

            choco = self.manager(summary, CHOCO)
            self.assertEqual(choco.get("state"), "read", choco)
            self.assertNotEqual(choco.get("state"), "not_present", choco)
            self.assertEqual(choco.get("count"), 0, choco)
            self.assertEqual(self.items(summary, CHOCO_SOURCE), {})

        with self.subTest(case="ChocolateyInstall replaces the default"):
            program_data = self.program_data()
            add_choco(self.choco_lib(program_data / "chocolatey"), "fabrikam.tool",
                      "fabrikam.tool", "3.0.0")
            install = self.temp_folder() / "invented-choco"
            add_choco(self.choco_lib(install), "contoso.cli", "Contoso.Cli", "1.10.0")
            summary = self.collect_with({"ProgramData": str(program_data),
                                         "ChocolateyInstall": str(install)})

            choco = self.manager(summary, CHOCO)
            self.assertEqual(choco.get("state"), "read", choco)
            self.assertEqual(choco.get("folder_from"), "ChocolateyInstall", choco)
            self.assertEqual(set(self.items(summary, CHOCO_SOURCE)), {CONTOSO_CLI})

        with self.subTest(case="an absent ChocolateyInstall is the only place looked in"):
            program_data = self.program_data()
            add_choco(self.choco_lib(program_data / "chocolatey"), "fabrikam.tool",
                      "fabrikam.tool", "3.0.0")
            absent = self.temp_folder() / "no-such-choco"
            summary = self.collect_with({"ProgramData": str(program_data),
                                         "ChocolateyInstall": str(absent)})

            choco = self.manager(summary, CHOCO)
            self.assertEqual(choco.get("state"), "not_present", choco)
            looked_in = choco.get("looked_in")
            self.assertIsInstance(looked_in, list, choco)
            self.assertEqual(len(looked_in), 1, choco)
            self.assertTrue(same_path(looked_in[0], absent), choco)
            found = [item for item in self.package_list(summary)
                     if str(item.get("key")).startswith(CHOCO_PREFIX)]
            self.assertEqual(found, [], found)

    def test_unreadable_nuspec_and_lib(self):
        program_data = self.program_data()
        lib = self.choco_lib(program_data / "chocolatey")
        add_choco(lib, "contoso.cli", "Contoso.Cli", "1.10.0")
        add_choco(lib, "adatum.broken", "Adatum.Broken", "2.0.0")
        add_choco(lib, "northwind.nover", "Northwind.NoVer", "4.1.0")
        denied = add_choco(lib, "tailspin.denied", "Tailspin.Denied", "0.9.0")
        environ = {"ProgramData": str(program_data)}
        data_dir = self.data_dir()
        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(len(self.items(first, CHOCO_SOURCE)), 4)

        (lib / "adatum.broken" / "adatum.broken.nuspec").write_text(
            "this is not xml <metadata", encoding="utf-8")
        (lib / "northwind.nover" / "northwind.nover.nuspec").write_text(
            nuspec_text("Northwind.NoVer", None), encoding="utf-8")
        with self.failing_read_text(denied / "tailspin.denied.nuspec",
                                    PermissionError(DENIED)):
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

        items = self.items(second, CHOCO_SOURCE)
        for folder in ("adatum.broken", "northwind.nover", "tailspin.denied"):
            key = CHOCO_PREFIX + folder
            self.assertIn(key, items, sorted(map(str, items)))
            self.assertEqual(items[key].get("status"), "unreadable", items[key])
            self.assertEqual(items[key].get("name"), folder, items[key])
            named = [item for item in self.not_checked(second) if folder in note_text(item)]
            self.assertTrue(named, (folder, second.get("not_checked")))
        self.assertEqual(items[CONTOSO_CLI].get("version"), "1.10.0", items[CONTOSO_CLI])
        choco = self.manager(second, CHOCO)
        self.assertEqual(choco.get("unreadable"), 3, choco)
        self.assertEqual(choco.get("incomplete"), 0, choco)
        self.assertEqual(self.notes_about(second, NO_NUSPEC_NOTE), [],
                         second.get("not_checked"))
        denied_named = [item for item in self.not_checked(second)
                        if "tailspin.denied" in note_text(item)
                        and DENIED.casefold() in note_text(item)]
        self.assertTrue(denied_named, second.get("not_checked"))
        changed = [change for change in self.changes_with(second, CHOCO_PREFIX)
                   if change.get("change") == "changed"]
        self.assertEqual(changed, [], second.get("changes"))

        with self.subTest(case="lib cannot be listed"):
            program_data = self.program_data()
            lib = self.choco_lib(program_data / "chocolatey")
            add_choco(lib, "contoso.cli", "Contoso.Cli", "1.10.0")
            add_choco(lib, "fabrikam.tool", "fabrikam.tool", "3.0.0")
            environ = {"ProgramData": str(program_data)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, CHOCO_SOURCE)),
                             {CONTOSO_CLI, FABRIKAM_TOOL})

            with self.failing_list_dir(lib, OSError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

            self.assert_carried(second, CHOCO, CHOCO_SOURCE, CHOCO_PREFIX,
                                {CONTOSO_CLI: "1.10.0", FABRIKAM_TOOL: "3.0.0"})
            self.assertTrue(self.reason_named(second, CHOCO_SOURCE, DENIED),
                            second.get("not_checked"))


class TestVcpkg(ChocoVcpkgTestCase):
    def test_status_database(self):
        root = self.vcpkg_root(database(ZLIB_INSTALLED, FMT_INSTALLED, FMT_FEATURE,
                                        CURL_NOT_INSTALLED))
        summary = self.collect_with({"VCPKG_ROOT": str(root)})

        items = self.items(summary, VCPKG_SOURCE)
        self.assertEqual(set(items), {ZLIB, FMT}, sorted(map(str, items)))
        self.assertEqual(items[ZLIB].get("name"), "zlib", items[ZLIB])
        self.assertEqual(items[ZLIB].get("version"), "1.3.1", items[ZLIB])
        self.assertEqual(items[ZLIB].get("triplet"), "x64-windows", items[ZLIB])
        self.assertTrue(same_path(items[ZLIB].get("folder"),
                                  root / "installed" / "x64-windows"), items[ZLIB])
        self.assertEqual(items[FMT].get("version"), "10.2.1#2", items[FMT])
        self.assertEqual(items[FMT].get("triplet"), "x64-windows", items[FMT])
        vcpkg = self.manager(summary, VCPKG)
        self.assertEqual(vcpkg.get("state"), "read", vcpkg)
        self.assertEqual(vcpkg.get("folder_from"), "VCPKG_ROOT", vcpkg)
        self.assertEqual(vcpkg.get("count"), 2, vcpkg)

        with self.subTest(case="the root named by vcpkg.path.txt"):
            local = self.local_app_data()
            (local / "vcpkg").mkdir()
            (local / "vcpkg" / PATH_FILE_NAME).write_text(str(root), encoding="utf-8")
            summary = self.collect_with({"LOCALAPPDATA": str(local)})

            items = self.items(summary, VCPKG_SOURCE)
            self.assertEqual(set(items), {ZLIB, FMT}, sorted(map(str, items)))
            self.assertEqual(items[ZLIB].get("version"), "1.3.1", items[ZLIB])
            self.assertEqual(items[FMT].get("version"), "10.2.1#2", items[FMT])
            vcpkg = self.manager(summary, VCPKG)
            self.assertEqual(vcpkg.get("state"), "read", vcpkg)
            self.assertEqual(vcpkg.get("folder_from"), "vcpkg.path.txt", vcpkg)

        with self.subTest(case="a root without installed\\vcpkg\\status"):
            empty_root = self.vcpkg_root()
            summary = self.collect_with({"VCPKG_ROOT": str(empty_root)})

            vcpkg = self.manager(summary, VCPKG)
            self.assertEqual(vcpkg.get("state"), "read", vcpkg)
            self.assertNotEqual(vcpkg.get("state"), "not_present", vcpkg)
            self.assertEqual(vcpkg.get("count"), 0, vcpkg)
            self.assertEqual(self.items(summary, VCPKG_SOURCE), {})

    def test_update_files_applied_in_order(self):
        curl_installed = paragraph("curl", "x86-windows", "8.5.0")
        zlib_purged = paragraph("zlib", "x64-windows", "1.3.1",
                                status="purge ok not-installed")
        # Not applied: if it were, litware would appear as a package.
        stray = paragraph("litware", "x64-windows", "0.1.0")
        root = self.vcpkg_root(database(ZLIB_INSTALLED, FMT_INSTALLED),
                               updates={"0000000001": curl_installed,
                                        "0000000002": zlib_purged,
                                        "incomplete.tmp": stray})
        summary = self.collect_with({"VCPKG_ROOT": str(root)})

        items = self.items(summary, VCPKG_SOURCE)
        self.assertEqual(set(items), {FMT, CURL}, sorted(map(str, items)))
        self.assertEqual(items[CURL].get("version"), "8.5.0", items[CURL])
        self.assertEqual(items[CURL].get("triplet"), "x86-windows", items[CURL])
        vcpkg = self.manager(summary, VCPKG)
        self.assertEqual(vcpkg.get("update_files"), 2, vcpkg)
        notes = self.notes_about(summary, NON_NUMERIC_NOTE)
        self.assertEqual(len(notes), 1, summary.get("not_checked"))

        with self.subTest(case="the later file in name order wins"):
            zlib_reinstalled = paragraph("zlib", "x64-windows", "1.3.2")
            root = self.vcpkg_root(database(ZLIB_INSTALLED, FMT_INSTALLED),
                                   updates={"0000000001": zlib_purged,
                                            "0000000002": zlib_reinstalled})
            summary = self.collect_with({"VCPKG_ROOT": str(root)})

            items = self.items(summary, VCPKG_SOURCE)
            self.assertEqual(set(items), {ZLIB, FMT}, sorted(map(str, items)))
            self.assertEqual(items[ZLIB].get("version"), "1.3.2", items[ZLIB])
            self.assertEqual(self.manager(summary, VCPKG).get("update_files"), 2)
            self.assertEqual(self.notes_about(summary, NON_NUMERIC_NOTE), [],
                             summary.get("not_checked"))

    def test_unreadable_database(self):
        with self.subTest(case="an update file cannot be read"):
            update = paragraph("curl", "x86-windows", "8.5.0")
            root = self.vcpkg_root(database(ZLIB_INSTALLED, FMT_INSTALLED),
                                   updates={"0000000001": update})
            environ = {"VCPKG_ROOT": str(root)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, VCPKG_SOURCE)), {ZLIB, FMT, CURL})

            update_path = root / "installed" / "vcpkg" / "updates" / "0000000001"
            with self.failing_read_text(update_path, PermissionError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

            self.assert_carried(second, VCPKG, VCPKG_SOURCE, VCPKG_PREFIX,
                                {ZLIB: "1.3.1", FMT: "10.2.1#2", CURL: "8.5.0"})
            self.assertTrue(self.reason_named(second, VCPKG_SOURCE, DENIED),
                            second.get("not_checked"))

        with self.subTest(case="vcpkg.path.txt cannot be read"):
            root = self.vcpkg_root(database(ZLIB_INSTALLED, FMT_INSTALLED))
            local = self.local_app_data()
            (local / "vcpkg").mkdir()
            path_file = local / "vcpkg" / PATH_FILE_NAME
            path_file.write_text(str(root), encoding="utf-8")
            environ = {"LOCALAPPDATA": str(local)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, VCPKG_SOURCE)), {ZLIB, FMT})

            with self.failing_read_text(path_file, PermissionError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

            self.assert_carried(second, VCPKG, VCPKG_SOURCE, VCPKG_PREFIX,
                                {ZLIB: "1.3.1", FMT: "10.2.1#2"})
            self.assertTrue(self.reason_named(second, VCPKG_SOURCE, DENIED),
                            second.get("not_checked"))

    def test_changes(self):
        program_data = self.program_data()
        choco_root = program_data / "chocolatey"
        lib = self.choco_lib(choco_root)
        add_choco(lib, "contoso.cli", "Contoso.Cli", "1.10.0")
        add_choco(lib, "fabrikam.tool", "fabrikam.tool", "3.0.0")
        root = self.vcpkg_root(database(ZLIB_INSTALLED, FMT_INSTALLED))
        status = root / "installed" / "vcpkg" / "status"
        environ = {"ProgramData": str(program_data), "VCPKG_ROOT": str(root)}
        data_dir = self.data_dir()

        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(self.changes_with(first, CHOCO_PREFIX), [])
        self.assertEqual(self.changes_with(first, VCPKG_PREFIX), [])

        # Raised version, removed package, added package, in each manager.
        (lib / "contoso.cli" / "contoso.cli.nuspec").write_text(
            nuspec_text("Contoso.Cli", "1.11.0"), encoding="utf-8")
        shutil.rmtree(lib / "fabrikam.tool")
        add_choco(lib, "litware.pkg", "Litware.Pkg", "0.4.0")
        status.write_text(database(paragraph("zlib", "x64-windows", "1.3.2"),
                                   paragraph("curl", "x86-windows", "8.5.0")),
                          encoding="utf-8")
        second = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.change_kinds(second, CHOCO_PREFIX),
                         sorted([(CONTOSO_CLI, "changed"), (FABRIKAM_TOOL, "removed"),
                                 (LITWARE_PKG, "added")]),
                         second.get("changes"))
        self.assertEqual(self.change_kinds(second, VCPKG_PREFIX),
                         sorted([(ZLIB, "changed"), (FMT, "removed"), (CURL, "added")]),
                         second.get("changes"))

        with self.subTest(case="an unchanged run"):
            third = self.collect_with(environ, data_dir=data_dir,
                                      now=NOW + timedelta(days=2))
            self.assertEqual(self.changes_with(third, CHOCO_PREFIX), [])
            self.assertEqual(self.changes_with(third, VCPKG_PREFIX), [])

        with self.subTest(case="the roots are gone"):
            shutil.rmtree(choco_root)
            shutil.rmtree(root)
            fourth = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=3))
            self.assertEqual(self.manager(fourth, CHOCO).get("state"), "not_present")
            self.assertEqual(self.manager(fourth, VCPKG).get("state"), "not_present")
            self.assertEqual(self.change_kinds(fourth, CHOCO_PREFIX),
                             sorted([(CONTOSO_CLI, "removed"), (LITWARE_PKG, "removed")]),
                             fourth.get("changes"))
            self.assertEqual(self.change_kinds(fourth, VCPKG_PREFIX),
                             sorted([(ZLIB, "removed"), (CURL, "removed")]),
                             fourth.get("changes"))


class TestReviewFixes(ChocoVcpkgTestCase):
    """Plan 080 M1 code review round 1: regressions written after the code."""

    def test_pending_install_is_unreadable(self):
        root = self.temp_folder() / "chocolatey"
        lib = self.choco_lib(root)
        add_choco(lib, "contoso.cli", "Contoso.Cli", "1.10.0")
        add_choco(lib, "fabrikam.tool", version="3.0.0")
        data_dir = self.temp_folder() / "data"
        self.collect_with({"ChocolateyInstall": str(root)}, data_dir=data_dir)

        # An upgrade of fabrikam.tool is interrupted: the new folder holds the marker.
        add_choco(lib, "fabrikam.tool", version="3.1.0")
        (lib / "fabrikam.tool" / ".chocolateyPending").write_text("", encoding="utf-8")
        summary = self.collect_with({"ChocolateyInstall": str(root)}, data_dir=data_dir,
                                    now=NOW + timedelta(days=1))

        items = self.items(summary, CHOCO_SOURCE)
        self.assertEqual(set(items), {CONTOSO_CLI, FABRIKAM_TOOL}, sorted(map(str, items)))
        self.assertEqual(items[FABRIKAM_TOOL].get("status"), "unreadable",
                         items[FABRIKAM_TOOL])
        choco = self.manager(summary, CHOCO)
        self.assertEqual((choco.get("count"), choco.get("unreadable")), (1, 1), choco)
        self.assertEqual(len(self.notes_about(summary, ".chocolateypending")), 1,
                         self.not_checked(summary))
        self.assertEqual(self.change_kinds(summary, CHOCO_PREFIX), [],
                         summary.get("changes"))

    def test_nuspec_values_are_stripped(self):
        root = self.temp_folder() / "chocolatey"
        lib = self.choco_lib(root)
        add_choco(lib, "contoso.cli", text=nuspec_text("\n  Contoso.Cli\n  ",
                                                       "\n      1.10.0\n    "))
        summary = self.collect_with({"ChocolateyInstall": str(root)})

        item = self.items(summary, CHOCO_SOURCE)[CONTOSO_CLI]
        self.assertEqual((item.get("name"), item.get("version")), ("Contoso.Cli", "1.10.0"),
                         item)

    def test_installed_without_version_is_unreadable(self):
        root = self.vcpkg_root(database(ZLIB_INSTALLED, paragraph("fmt", "x64-windows")))
        summary = self.collect_with({"VCPKG_ROOT": str(root)})

        items = self.items(summary, VCPKG_SOURCE)
        self.assertEqual(items[FMT].get("status"), "unreadable", items[FMT])
        self.assertIsNone(items[FMT].get("version"), items[FMT])
        self.assertEqual(items[ZLIB].get("status"), "read", items[ZLIB])
        self.assertEqual(len(self.notes_about(summary, "no version")), 1,
                         self.not_checked(summary))
        vcpkg = self.manager(summary, VCPKG)
        self.assertEqual((vcpkg.get("count"), vcpkg.get("unreadable")), (1, 1), vcpkg)


if __name__ == "__main__":
    unittest.main()

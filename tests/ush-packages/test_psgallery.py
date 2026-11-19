"""PowerShell modules installed through PowerShellGet, read offline (plan 079, M2, K1-K5).

Interface these tests assume (fixed before the code exists):

- Folders and files are read in Python through the module-level ``DISK`` object
  (``exists(path)``, ``list_dir(path)``: names, ``OSError`` on failure;
  ``read_text(path)``); locations are expanded from the module's ``ENVIRON``.
- ``DISK.documents_folder()`` returns the raw ``Personal`` value of the user's shell
  folders (or None; ``OSError`` when it cannot be read). Every test here replaces it, so
  no test touches the registry. None means ``%USERPROFILE%\\Documents``.
- Module folders and their labels: ``user-windowspowershell``
  ``<Documents>\\WindowsPowerShell\\Modules``, ``user-powershell``
  ``<Documents>\\PowerShell\\Modules``, ``allusers-windowspowershell``
  ``%ProgramFiles%\\WindowsPowerShell\\Modules``, ``allusers-powershell``
  ``%ProgramFiles%\\PowerShell\\Modules``.
- A module is ``<folder>\\<Name>\\<Version>\\PSGetModuleInfo.xml`` (CLIXML: the elements
  with attribute ``N`` ``Name``, ``Version``, ``Repository`` under the top-level object's
  ``MS``, whatever their tag).
- Source ``psgallery_modules``; detail list ``psgallery_modules``; key
  ``psgallery:<label>|<module folder name case-folded>``; fields ``name``, ``version``,
  ``versions_found``, ``repository``, ``module_folder`` (the label), ``folder``.
- ``managers.psgallery`` is ``{state: "not_present", looked_in: [raw paths]}`` when no
  folder exists, else ``{state, status, folders: [{source, status, count, reason}],
  count, unreadable, other_modules}``.

The PSGetModuleInfo.xml fixtures have the shape ``Export-Clixml`` writes (UTF-16 with a
byte order mark, the CLIXML namespace, no XML declaration). PowerShell never starts;
every folder and file is written by hand in a temporary folder; every module name,
version, repository and path is invented.
"""

import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, PackagesTestCase, note_text, packages_fake

MANAGER = "psgallery"
SOURCE = "psgallery_modules"
PREFIX = "psgallery:"
NOT_READ_YET = "not read yet"
OTHER_MODULES_NOTE = "not installed through powershellget"
DENIED = "Access to the path is denied (invented)"
REGISTRY_ERROR = "Invented registry error: User Shell Folders could not be opened"

USER_WINDOWS = "user-windowspowershell"
USER_CORE = "user-powershell"
ALLUSERS_WINDOWS = "allusers-windowspowershell"
ALLUSERS_CORE = "allusers-powershell"

RAW_LOOKED_IN = (
    "%USERPROFILE%\\Documents\\WindowsPowerShell\\Modules",
    "%USERPROFILE%\\Documents\\PowerShell\\Modules",
    "%ProgramFiles%\\WindowsPowerShell\\Modules",
    "%ProgramFiles%\\PowerShell\\Modules",
)

CLIXML_NS = "http://schemas.microsoft.com/powershell/2004/04"


def key(label, module):
    return f"{PREFIX}{label}|{module.casefold()}"


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def module_info_xml(name, version, repository="PSGallery", version_tag="Version"):
    """A PSGetModuleInfo.xml as PowerShellGet writes it with Export-Clixml (invented
    values). ``name`` / ``version`` None leaves that property out."""
    lines = [
        f'<Objs Version="1.1.0.1" xmlns="{CLIXML_NS}">',
        '  <Obj RefId="0">',
        '    <TN RefId="0">',
        "      <T>Microsoft.PowerShell.Commands.PSRepositoryItemInfo</T>",
        "      <T>System.Management.Automation.PSCustomObject</T>",
        "      <T>System.Object</T>",
        "    </TN>",
        "    <MS>",
    ]
    if name is not None:
        lines.append(f'      <S N="Name">{name}</S>')
    if version is not None:
        lines.append(f'      <{version_tag} N="Version">{version}</{version_tag}>')
    lines += [
        '      <S N="Type">Module</S>',
        '      <S N="Description">An invented module for tests.</S>',
        '      <S N="Author">Invented Author</S>',
        '      <S N="CompanyName">Invented</S>',
        '      <DT N="PublishedDate">2026-03-14T09:30:00+00:00</DT>',
        '      <Nil N="InstalledDate" />',
        '      <Nil N="UpdatedDate" />',
        '      <URI N="ProjectUri">https://example.invalid/invented-module</URI>',
        '      <Obj N="Dependencies" RefId="1">',
        '        <TN RefId="1">',
        "          <T>System.Object[]</T>",
        "          <T>System.Array</T>",
        "          <T>System.Object</T>",
        "        </TN>",
        "        <LST />",
        "      </Obj>",
        f'      <S N="Repository">{repository}</S>',
        '      <S N="PackageManagementProvider">NuGet</S>',
        '      <S N="InstalledLocation">C:\\Invented\\Modules\\Invented\\0.0.0</S>',
        "    </MS>",
        "  </Obj>",
        "</Objs>",
    ]
    return "\r\n".join(lines) + "\r\n"


def write_info(version_folder, text):
    """Write PSGetModuleInfo.xml as Export-Clixml does: UTF-16 with a BOM."""
    path = Path(version_folder) / "PSGetModuleInfo.xml"
    path.write_bytes(text.encode("utf-16"))
    return path


def add_module(modules, folder_name, version, info=True, name=None,
               repository="PSGallery", version_tag="Version", info_text=None):
    """One module version folder ``<modules>\\<folder_name>\\<version>`` with its
    manifest; ``info`` False: no PSGetModuleInfo.xml (a module copied by hand);
    ``info_text``: that exact file content instead of a valid one."""
    folder = Path(modules) / folder_name / version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{folder_name}.psd1").write_text(
        "@{\r\n"
        f"    RootModule = '{folder_name}.psm1'\r\n"
        f"    ModuleVersion = '{version}'\r\n"
        "    GUID = '00000000-0000-4000-8000-000000000079'\r\n"
        "    Author = 'Invented Author'\r\n"
        "}\r\n",
        encoding="utf-8-sig")
    (folder / f"{folder_name}.psm1").write_text(
        "function Get-Invented { 'invented' }\r\n", encoding="utf-8-sig")
    if info_text is not None:
        write_info(folder, info_text)
    elif info:
        write_info(folder, module_info_xml(name or folder_name, version,
                                           repository=repository,
                                           version_tag=version_tag))
    return folder


class PsgalleryTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def profile(self):
        """An invented %USERPROFILE% that exists, without a Documents folder."""
        folder = self.temp_folder() / "Invented"
        folder.mkdir(parents=True)
        return folder

    def program_files(self):
        """An invented %ProgramFiles% that exists, without module folders."""
        folder = self.temp_folder() / "Program Files"
        folder.mkdir(parents=True)
        return folder

    @staticmethod
    def modules(base, edition):
        """``<base>\\<edition>\\Modules`` (edition ``WindowsPowerShell`` or
        ``PowerShell``), created."""
        folder = Path(base) / edition / "Modules"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def collect_with(self, environ, documents=None, data_dir=None, now=NOW):
        """Collect with ``ENVIRON`` = ``environ`` and ``DISK.documents_folder()``
        returning ``documents`` (raising it when it is an exception)."""
        def documents_folder():
            if isinstance(documents, BaseException):
                raise documents
            return documents

        with mock.patch.object(self.packages, "ENVIRON", dict(environ)), \
                mock.patch.object(self.packages.DISK, "documents_folder", documents_folder):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def items(self, summary):
        items = self.detail(summary).get(SOURCE)
        self.assertIsInstance(items, list, f"detail {SOURCE}: {items!r}")
        return self.by_key(items)

    def psgallery(self, summary):
        return self.manager(summary, MANAGER)

    def psgallery_changes(self, summary):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith(PREFIX)]

    def failing_list_dir(self, failing_path, error):
        original = self.packages.DISK.list_dir

        def list_dir(path):
            if same_path(path, failing_path):
                raise error
            return original(path)

        return mock.patch.object(self.packages.DISK, "list_dir", list_dir)

    def failing_read_text(self, failing_path, error):
        original = self.packages.DISK.read_text

        def read_text(path, *args, **kwargs):
            if same_path(path, failing_path):
                raise error
            return original(path, *args, **kwargs)

        return mock.patch.object(self.packages.DISK, "read_text", read_text)


class TestPsgallery(PsgalleryTestCase):
    def test_absent_is_not_present(self):
        summary = self.collect_with({}, documents=None)

        psgallery = self.psgallery(summary)
        self.assertEqual(set(psgallery), {"state", "looked_in"}, psgallery)
        self.assertEqual(psgallery["state"], "not_present", psgallery)
        looked_in = psgallery["looked_in"]
        self.assertIsInstance(looked_in, list, psgallery)
        self.assertEqual(sorted(str(path).casefold() for path in looked_in),
                         sorted(path.casefold() for path in RAW_LOOKED_IN), psgallery)
        for item in self.not_checked(summary):
            text = note_text(item)
            if "psgallery" in text or "powershell" in text:
                self.assertNotIn(NOT_READ_YET, text, item)
                self.assertNotIn("unreadable", text, item)
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith(PREFIX)]
        self.assertEqual(found, [], found)

    def test_modules_from_psgetmoduleinfo(self):
        profile = self.profile()
        modules = self.modules(profile / "Documents", "PowerShell")
        add_module(modules, "Contoso.Az", "1.2.0", repository="PSGallery")
        add_module(modules, "Contoso.Az", "1.10.0", repository="PSGallery")
        # PSResourceGet writes the version as a string element: it parses too.
        add_module(modules, "Fabrikam.Ops", "2.0.0", repository="Internal", version_tag="S")
        add_module(modules, "Litware.Local", "1.0", info=False)

        summary = self.collect_with({"USERPROFILE": str(profile)}, documents=None)

        contoso, fabrikam = key(USER_CORE, "Contoso.Az"), key(USER_CORE, "Fabrikam.Ops")
        items = self.items(summary)
        self.assertEqual(set(items), {contoso, fabrikam}, sorted(map(str, items)))
        self.assertEqual(items[contoso].get("version"), "1.10.0", items[contoso])
        self.assertEqual(items[contoso].get("versions_found"), 2, items[contoso])
        self.assertEqual(items[contoso].get("repository"), "PSGallery", items[contoso])
        self.assertEqual(items[contoso].get("module_folder"), USER_CORE, items[contoso])
        self.assertEqual(items[fabrikam].get("repository"), "Internal", items[fabrikam])
        self.assertEqual(items[fabrikam].get("version"), "2.0.0", items[fabrikam])
        litware = [name for name in map(str, items) if "litware" in name]
        self.assertEqual(litware, [], sorted(map(str, items)))

        psgallery = self.psgallery(summary)
        self.assertEqual(psgallery.get("state"), "read", psgallery)
        self.assertEqual(psgallery.get("other_modules"), 1, psgallery)
        notes = [item for item in self.not_checked(summary)
                 if OTHER_MODULES_NOTE in note_text(item)]
        self.assertEqual(len(notes), 1, summary.get("not_checked"))

    def test_documents_folder(self):
        profile = self.profile()
        onedrive = self.temp_folder() / "OneDrive - Invented"
        documents = onedrive / "Documents"
        add_module(self.modules(documents, "WindowsPowerShell"), "Contoso.Az", "1.2.0")
        add_module(self.modules(documents, "PowerShell"), "Fabrikam.Ops", "2.0.0")
        # The default Documents folder holds a module too; it must not be looked at.
        add_module(self.modules(profile / "Documents", "PowerShell"), "Litware.Decoy", "9.0")
        program_files = self.program_files()
        add_module(self.modules(program_files, "PowerShell"), "Northwind.Admin", "3.1.0")
        environ = {"USERPROFILE": str(profile), "OneDriveTest": str(onedrive),
                   "ProgramFiles": str(program_files)}
        data_dir = self.data_dir()

        user_windows = key(USER_WINDOWS, "Contoso.Az")
        user_core = key(USER_CORE, "Fabrikam.Ops")
        allusers = key(ALLUSERS_CORE, "Northwind.Admin")

        first = self.collect_with(environ, documents="%OneDriveTest%\\Documents",
                                  data_dir=data_dir, now=NOW)
        self.assertEqual(set(self.items(first)), {user_windows, user_core, allusers},
                         sorted(map(str, self.items(first))))

        second = self.collect_with(environ, documents=OSError(REGISTRY_ERROR),
                                   data_dir=data_dir, now=NOW + timedelta(days=1))

        psgallery = self.psgallery(second)
        self.assertEqual(psgallery.get("state"), "read", psgallery)
        self.assertNotEqual(psgallery.get("state"), "not_present", psgallery)
        for label in (USER_WINDOWS, USER_CORE):
            named = [item for item in self.not_checked(second)
                     if label in note_text(item)
                     and REGISTRY_ERROR.casefold() in note_text(item)]
            self.assertTrue(named, (label, second.get("not_checked")))
        items = self.items(second)
        for item_key, version in ((user_windows, "1.2.0"), (user_core, "2.0.0")):
            self.assertIn(item_key, items, sorted(map(str, items)))
            self.assertIs(items[item_key].get("from_baseline"), True, items[item_key])
            self.assertEqual(items[item_key].get("version"), version, items[item_key])
        self.assertIn(allusers, items, sorted(map(str, items)))
        removed = [change for change in self.psgallery_changes(second)
                   if change.get("change") == "removed"]
        self.assertEqual(removed, [], second.get("changes"))

        with self.subTest(case="the Documents setting names an unset variable"):
            third = self.collect_with(environ, documents="%OneDriveUnset%\\Documents",
                                      data_dir=data_dir, now=NOW + timedelta(days=2))
            psgallery = self.psgallery(third)
            self.assertEqual(psgallery.get("state"), "read", psgallery)
            items = self.items(third)
            for item_key in (user_windows, user_core):
                self.assertIn(item_key, items, sorted(map(str, items)))
                self.assertIs(items[item_key].get("from_baseline"), True, items[item_key])
            removed = [change for change in self.psgallery_changes(third)
                       if change.get("change") == "removed"]
            self.assertEqual(removed, [], third.get("changes"))
            for label in (USER_WINDOWS, USER_CORE):
                named = [item for item in self.not_checked(third)
                         if label in note_text(item) and "onedriveunset" in note_text(item)]
                self.assertTrue(named, (label, third.get("not_checked")))

        with self.subTest(case="the Documents setting names an unset variable, nothing else"):
            summary = self.collect_with({"USERPROFILE": str(self.profile())},
                                        documents="%OneDriveUnset%\\Documents")
            psgallery = self.psgallery(summary)
            self.assertNotEqual(psgallery.get("state"), "not_present", psgallery)
            for label in (USER_WINDOWS, USER_CORE):
                named = [item for item in self.not_checked(summary)
                         if label in note_text(item) and "onedriveunset" in note_text(item)]
                self.assertTrue(named, (label, summary.get("not_checked")))

        with self.subTest(case="Documents not readable and nothing else present"):
            summary = self.collect_with({"USERPROFILE": str(self.profile())},
                                        documents=OSError(REGISTRY_ERROR))
            psgallery = self.psgallery(summary)
            self.assertNotEqual(psgallery.get("state"), "not_present", psgallery)
            for path in psgallery.get("looked_in") or []:
                self.assertNotIn("documents", str(path).casefold(), psgallery)
            for label in (USER_WINDOWS, USER_CORE):
                named = [item for item in self.not_checked(summary)
                         if label in note_text(item)
                         and REGISTRY_ERROR.casefold() in note_text(item)]
                self.assertTrue(named, (label, summary.get("not_checked")))

    def test_no_folder_read_is_unreadable(self):
        """Added by loc-qa (plan 079): with no folder read and the user- folders unknown,
        the source is unreadable with count null, never empty or not present."""
        cases = {
            "Documents setting names an unset variable": "%OneDriveUnset%\\Documents",
            "Documents not readable": OSError(REGISTRY_ERROR),
        }
        for case, documents in cases.items():
            with self.subTest(case=case):
                summary = self.collect_with({"USERPROFILE": str(self.profile())},
                                            documents=documents)
                psgallery = self.psgallery(summary)
                self.assertEqual(psgallery.get("state"), "unreadable", psgallery)
                self.assertIn("count", psgallery, psgallery)
                self.assertIsNone(psgallery["count"], psgallery)
                self.assertEqual(self.source(summary, SOURCE).get("status"), "unreadable",
                                 self.source(summary, SOURCE))

    def test_broken_module_info(self):
        profile = self.profile()
        modules = self.modules(profile / "Documents", "PowerShell")
        add_module(modules, "Contoso.Broken", "1.0.0",
                   info_text="Invented: this is not XML <<< \r\n")
        add_module(modules, "Fabrikam.NoVersion", "2.0.0",
                   info_text=module_info_xml("Fabrikam.NoVersion", None))
        # The higher version does not parse; the lower one does.
        add_module(modules, "Litware.Mixed", "2.0.0",
                   info_text="<Objs Version=\"1.1.0.1\"><Obj RefId=\"0\"><MS>")
        add_module(modules, "Litware.Mixed", "1.1.0")
        denied_folder = add_module(modules, "Northwind.Denied", "3.0.0")
        add_module(modules, "Tailspin.Hidden", "4.0.0")
        environ = {"USERPROFILE": str(profile)}

        with self.failing_read_text(denied_folder / "PSGetModuleInfo.xml",
                                    PermissionError(DENIED)), \
                self.failing_list_dir(modules / "Tailspin.Hidden", OSError(DENIED)):
            summary = self.collect_with(environ, documents=None)

        items = self.items(summary)
        unreadable = [key(USER_CORE, name) for name in
                      ("Contoso.Broken", "Fabrikam.NoVersion", "Northwind.Denied",
                       "Tailspin.Hidden")]
        for item_key in unreadable:
            with self.subTest(item=item_key):
                self.assertIn(item_key, items, sorted(map(str, items)))
                self.assertEqual(items[item_key].get("status"), "unreadable", items[item_key])
                reason = items[item_key].get("reason")
                self.assertIsInstance(reason, str, items[item_key])
                self.assertTrue(reason.strip(), items[item_key])
        for name in ("Northwind.Denied", "Tailspin.Hidden"):
            reason = str(items[key(USER_CORE, name)].get("reason")).casefold()
            self.assertIn(DENIED.casefold(), reason, items[key(USER_CORE, name)])

        mixed = items.get(key(USER_CORE, "Litware.Mixed"))
        self.assertIsNotNone(mixed, sorted(map(str, items)))
        self.assertNotEqual(mixed.get("status"), "unreadable", mixed)
        self.assertEqual(mixed.get("version"), "1.1.0", mixed)

        psgallery = self.psgallery(summary)
        self.assertEqual(psgallery.get("unreadable"), 4, psgallery)
        self.assertEqual(psgallery.get("other_modules"), 0, psgallery)
        notes = [item for item in self.not_checked(summary)
                 if OTHER_MODULES_NOTE in note_text(item)]
        self.assertEqual(notes, [], summary.get("not_checked"))

    def test_partly_read_and_changes(self):
        profile = self.profile()
        user_modules = self.modules(profile / "Documents", "PowerShell")
        program_files = self.program_files()
        allusers_modules = self.modules(program_files, "PowerShell")
        add_module(user_modules, "Contoso.Az", "1.2.0")
        add_module(allusers_modules, "Fabrikam.Ops", "2.0.0")
        environ = {"USERPROFILE": str(profile), "ProgramFiles": str(program_files)}
        data_dir = self.data_dir()

        contoso = key(USER_CORE, "Contoso.Az")
        fabrikam = key(ALLUSERS_CORE, "Fabrikam.Ops")

        first = self.collect_with(environ, documents=None, data_dir=data_dir, now=NOW)
        self.assertEqual(set(self.items(first)), {contoso, fabrikam},
                         sorted(map(str, self.items(first))))
        self.assertEqual(self.psgallery_changes(first), [])

        add_module(user_modules, "Contoso.Az", "1.10.0")
        shutil.rmtree(user_modules / "Contoso.Az" / "1.2.0")
        with self.failing_list_dir(allusers_modules, OSError(DENIED)):
            second = self.collect_with(environ, documents=None, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

        psgallery = self.psgallery(second)
        self.assertEqual(psgallery.get("state"), "read", psgallery)
        self.assertIn("count", psgallery, psgallery)
        self.assertIsNone(psgallery["count"], psgallery)

        changes = self.psgallery_changes(second)
        self.assertEqual([(c.get("key"), c.get("change")) for c in changes],
                         [(contoso, "changed")], changes)
        changed = changes[0]
        self.assertEqual(changed.get("source"), SOURCE, changed)
        self.assertEqual(changed.get("module_folder"), USER_CORE, changed)

        items = self.items(second)
        self.assertIn(fabrikam, items, sorted(map(str, items)))
        self.assertIs(items[fabrikam].get("from_baseline"), True, items[fabrikam])


if __name__ == "__main__":
    unittest.main()

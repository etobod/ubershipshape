"""The ``portable_programs`` source of ush-inventory (plan 072, milestone M1, criteria
K1-K6; K7 is in ``test_footprints.py``).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``comparison``,
``changes``, ``not_checked``, item ``key``/``id``/``own``, the detail file) is described in
``fakes.py``; autostart rows in ``fakes_autostart.py``.

Interface under test (from the plan):

- A third program source ``portable_programs``. Item key ``portable:<case-folded folder>``;
  fields ``name`` (the folder's name), ``install_location`` (the folder), ``executables``
  (the started ``.exe`` paths seen in it) and ``found_by`` (the sorted set of
  ``autostart``, ``shortcut`` and ``process``). Items are in the summary and detail
  ``programs`` with ``source`` ``portable_programs``, ``own`` ``false`` and ``a`` ids.
- A folder is portable when an executable in it is the expanded target of an autostart
  entry whose ``own`` is not ``true``, the target of a ``.lnk`` in the Start menu or on the
  Desktop, or the image of a running process; and the folder lies outside the ``file_facts``
  directories and the roots of ``portable-excluded.json``, is not a drive root or a
  user-profile root, lies inside no ``win32:``/``msix:`` ``install_location`` and is not
  the folder (or a subfolder) of a ``win32:`` item's ``DisplayIcon``/``UninstallString``
  executable (folder-boundary aware).
- A kept item from the previous baseline is checked by the ``portable_exists`` job and by
  the same rules; process paths that could not be read are counted in
  ``process_paths_unread``.

Assumptions added by these tests beyond the plan text (the shapes of the new jobs):

- ``shortcuts`` rows ``{Folder: "Programs"|"CommonPrograms"|"Desktop"|
  "CommonDesktopDirectory", FileName, FullName, TargetPath, Arguments}``, following the
  ``startup_folders`` rows.
- ``process_paths`` rows ``{Name, Id, Path}`` (``Get-Process``); ``Path`` null or empty
  when it could not be read.
- ``win32_programs`` rows gain ``DisplayIcon`` and ``UninstallString`` (raw registry text).
- ``portable_exists`` rows follow the ``file_facts`` file rows: ``{Kind: "file", Path,
  ExpandedPath, Exists: true|false|null, ExistsReason: null|"not_local"|
  "not_confirmed"}``, matched by ``Path`` case-insensitively.
- ``portable-excluded.json`` is the shipped data file; its roots are expanded with the
  run's environment, which the tests replace by invented values in both
  ``inventory.ENVIRON`` and ``os.environ``; the user-profile root is ``USERPROFILE``.
- ``process_paths_unread`` is a number somewhere in the summary (its place is not pinned).
- A summary program item may leave ``own`` out (plan 074); ``own`` is read from the detail.

PowerShell never starts; every value is invented (Contoso, Fabrikam, Northwind,
Woodgrove).
"""

import os
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from .fakes import (
    NOW,
    FakePowerShell,
    InventoryTestCase,
    failure,
    id_number,
    msix,
    ok,
    win32,
)
from .fakes_autostart import (
    CLEAN_SERVICES,
    MS,
    VENDOR,
    clean_responses,
    file_row,
    run_value,
    service,
)
from .fakes_vendor_folders import PROGRAM_DATA as VENDOR_PROGRAM_DATA
from .fakes_vendor_folders import folder as vendor_folder
from .fakes_vendor_folders import listing as vendor_listing

SOURCE = "portable_programs"

PROFILE = "C:\\Users\\Invented"
LOCAL_APP_DATA = f"{PROFILE}\\AppData\\Local"
TEMP_DIR = f"{LOCAL_APP_DATA}\\Temp"

# The run's environment, invented (Windows default shapes, not readings).
ENV = {
    "USERPROFILE": PROFILE,
    "LOCALAPPDATA": LOCAL_APP_DATA,
    "APPDATA": f"{PROFILE}\\AppData\\Roaming",
    "TEMP": TEMP_DIR,
    "TMP": TEMP_DIR,
    "ProgramData": "C:\\ProgramData",
    "SystemRoot": "C:\\Windows",
    "windir": "C:\\Windows",
    "ProgramFiles": "C:\\Program Files",
    "ProgramFiles(x86)": "C:\\Program Files (x86)",
    "SystemDrive": "C:",
}
ENVIRON = {**ENV, **{name.upper(): value for name, value in ENV.items()}}

START_MENU = f"{PROFILE}\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs"
DESKTOP = f"{PROFILE}\\Desktop"

DAY1 = NOW
DAY2 = NOW + timedelta(days=1)
DAY3 = NOW + timedelta(days=2)


# --- invented rows ---------------------------------------------------------------------

def portable_key(folder):
    """``portable:<case-folded folder>``."""
    return f"portable:{folder.casefold()}"


def shortcut(target, folder="Programs", name=None, arguments=None):
    """One ``.lnk`` as the ``shortcuts`` job returns it."""
    name = name or "Invented.lnk"
    base = DESKTOP if "Desktop" in folder else START_MENU
    return {
        "Folder": folder,
        "FileName": name,
        "FullName": f"{base}\\{name}",
        "TargetPath": target,
        "Arguments": arguments,
    }


def process(path, name="invented", pid=4000):
    """One ``Get-Process`` row as the ``process_paths`` job returns it."""
    return {"Name": name, "Id": pid, "Path": path}


def exists_row(path, exists, reason=None):
    """One ``portable_exists`` row (the ``file_facts`` file row shape)."""
    return {"Kind": "file", "Path": path, "ExpandedPath": path, "Exists": exists,
            "ExistsReason": reason}


def with_paths(row, display_icon=None, uninstall_string=None):
    """A ``win32_programs`` row with ``DisplayIcon`` and ``UninstallString``."""
    return dict(row, DisplayIcon=display_icon, UninstallString=uninstall_string)


def responses(runs=(), services=(), files=(), shortcuts=(), processes=(), programs=(),
              packages=(), **overrides):
    """A clean invented machine plus the given rows; ``overrides`` replace a job."""
    result = clean_responses(extra_files=list(files))
    result["run_keys"] = ok(list(runs))
    result["services"] = ok(list(CLEAN_SERVICES) + list(services))
    result["shortcuts"] = ok(list(shortcuts))
    result["process_paths"] = ok(list(processes))
    result["win32_programs"] = ok(list(programs))
    result["msix_programs"] = ok(list(packages))
    result.update(overrides)
    return FakePowerShell(result)


def mentions(value, text):
    """``text`` (case-insensitive) is in a string anywhere in ``value``."""
    if isinstance(value, str):
        return text.casefold() in value.casefold()
    if isinstance(value, dict):
        return any(mentions(v, text) for v in value.values())
    if isinstance(value, list):
        return any(mentions(v, text) for v in value)
    return False


def values_of(value, name):
    """Every value of the key ``name`` anywhere in ``value``."""
    found = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == name:
                found.append(inner)
            found.extend(values_of(inner, name))
    elif isinstance(value, list):
        for inner in value:
            found.extend(values_of(inner, name))
    return found


# --- the scenario of K1 ----------------------------------------------------------------

INV_RAW = "%LOCALAPPDATA%\\Invented\\inv.exe"
INV_FOLDER = f"{LOCAL_APP_DATA}\\Invented"
INV_EXE = f"{INV_FOLDER}\\inv.exe"
INV_RUN = run_value("InventedTray", INV_RAW, value_kind="ExpandString")
INV_RUN_KEY = "run:hkcu\\Run:InventedTray"

FAB_FOLDER = "D:\\Tools\\Fab"
FAB_EXE = f"{FAB_FOLDER}\\fab.exe"
FAB_TRAY_EXE = f"{FAB_FOLDER}\\fabtray.exe"

CON_FOLDER = "E:\\Portable\\Contoso"
CON_EXE = f"{CON_FOLDER}\\con.exe"

NW_FOLDER = "F:\\Kit\\Northwind"
NW_EXE = f"{NW_FOLDER}\\nw.exe"
NW_SYNC_EXE = f"{NW_FOLDER}\\nwsync.exe"


class PortableTestCase(InventoryTestCase):
    def setUp(self):
        super().setUp()
        # Fix the temporary directory before the environment is replaced.
        tempfile.gettempdir()
        for patcher in (mock.patch.object(self.inventory, "ENVIRON", dict(ENVIRON)),
                        mock.patch.dict(os.environ, ENV)):
            patcher.start()
            self.addCleanup(patcher.stop)

    # --- helpers ------------------------------------------------------------------------

    def summary_programs(self, summary):
        return self.by_key(summary.get("programs"))

    def detail_programs(self, summary):
        return self.by_key(self.detail(summary).get("programs"))

    def portable(self, summary):
        """The detail program items of the portable source, by key."""
        return {key: item for key, item in self.detail_programs(summary).items()
                if str(key).startswith("portable:")}

    def summary_portable(self, summary):
        return {key: item for key, item in self.summary_programs(summary).items()
                if str(key).startswith("portable:")}

    def assert_item(self, item, folder, executables, found_by):
        self.assertIsNotNone(item, folder)
        self.assertEqual(item.get("key"), portable_key(folder), item)
        self.assertEqual(item.get("source"), SOURCE, item)
        self.assertEqual(item.get("name"), folder.rsplit("\\", 1)[-1], item)
        self.assertEqual(str(item.get("install_location")).casefold(), folder.casefold(),
                         item)
        listed = item.get("executables")
        self.assertIsInstance(listed, list, item)
        self.assertEqual(sorted(str(p).casefold() for p in listed),
                         sorted(p.casefold() for p in executables), item)
        self.assertEqual(item.get("found_by"), sorted(found_by), item)

    def removed(self, summary, key):
        return [change for change in self.changes(summary)
                if change.get("key") == key and change.get("change") == "removed"]

    def notes_naming(self, summary, text):
        return [item for item in self.not_checked(summary)
                if mentions([item.get("what"), item.get("reason")], text)]

    def assert_reasoned(self, notes, label, summary):
        self.assertTrue(notes, f"no not_checked entry about {label}: "
                               f"{self.not_checked(summary)}")
        for note in notes:
            reason = note.get("reason")
            self.assertIsInstance(reason, str, note)
            self.assertTrue(reason.strip(), note)

    def fact(self, summary, entry_key, path):
        entries = self.by_key(self.detail(summary).get("autostart"))
        self.assertIn(entry_key, entries, sorted(entries))
        wanted = path.casefold()
        found = [fact for fact in entries[entry_key].get("facts") or []
                 if wanted in (str(fact.get("path")).casefold(),
                               str(fact.get("expanded_path")).casefold())]
        self.assertEqual(len(found), 1, entries[entry_key])
        return found[0]


# --- K1 --------------------------------------------------------------------------------

class TestFoundBy(PortableTestCase):
    def test_found_by_each_source(self):
        fake = responses(
            runs=[INV_RUN],
            files=[file_row(INV_RAW, expanded=INV_EXE, signer=VENDOR)],
            shortcuts=[shortcut(FAB_EXE, name="Fab.lnk"),
                       shortcut(NW_EXE, folder="Desktop", name="Northwind.lnk")],
            processes=[process(CON_EXE, name="con", pid=4101),
                       process(NW_SYNC_EXE, name="nwsync", pid=4102)],
        )
        summary = self.collect(fake)
        items = self.portable(summary)

        self.assertEqual(set(items), {portable_key(INV_FOLDER), portable_key(FAB_FOLDER),
                                      portable_key(CON_FOLDER), portable_key(NW_FOLDER)},
                         sorted(items))
        with self.subTest(source="autostart (expanded by file facts)"):
            self.assert_item(items.get(portable_key(INV_FOLDER)), INV_FOLDER, [INV_EXE],
                             ["autostart"])
        with self.subTest(source="shortcut"):
            self.assert_item(items.get(portable_key(FAB_FOLDER)), FAB_FOLDER, [FAB_EXE],
                             ["shortcut"])
        with self.subTest(source="process"):
            self.assert_item(items.get(portable_key(CON_FOLDER)), CON_FOLDER, [CON_EXE],
                             ["process"])
        with self.subTest(source="shortcut and process in one folder"):
            self.assert_item(items.get(portable_key(NW_FOLDER)), NW_FOLDER,
                             [NW_EXE, NW_SYNC_EXE], ["process", "shortcut"])


# --- K2 --------------------------------------------------------------------------------

DEFENDER_DIR = "C:\\ProgramData\\Microsoft\\Windows Defender\\Platform\\4.18.24090.11-0"
DEFENDER_EXE = f"{DEFENDER_DIR}\\MsMpEng.exe"
OWN_SVC_EXE = "D:\\Invented\\OwnSvc\\ownsvc.exe"
OWN_SVC_KEY = "service:InventedOwnSvc"
RAW_PF = "%ProgramFiles%\\Invented Raw\\raw.exe"
RAW_PF86 = "%ProgramFiles(x86)%\\Invented Raw86\\raw86.exe"
CONTOSO_APPS = "D:\\Apps\\Contoso"
NOTES_LOCATION = "D:\\Invented\\WindowsApps\\Fabrikam.Notes_1.0.0.0_x64__0abc1def2ghj3"
WOODGROVE_EXE = "E:\\Woodgrove\\Tool\\tool.exe"


class TestCleanData(PortableTestCase):
    def test_clean_data_no_portable(self):
        pf_exe = "C:\\Program Files\\Contoso\\App\\app.exe"
        pf86_exe = "C:\\Program Files (x86)\\Fabrikam\\Tools\\fab.exe"
        win_exe = "C:\\Windows\\SystemApps\\Invented\\inv.exe"
        win_run = "C:\\Windows\\Invented\\winrun.exe"
        fake = responses(
            runs=[
                run_value("InventedPF", f'"{pf_exe}" --tray'),
                run_value("InventedWinRun", win_run),
                run_value("InventedRawPF", RAW_PF, value_kind="ExpandString"),
                run_value("InventedRawPF86", RAW_PF86, value_kind="ExpandString"),
                run_value("WoodgroveTool", f'"{WOODGROVE_EXE}" /tray'),
            ],
            services=[
                service("InventedDefender", f'"{DEFENDER_EXE}"'),
                service("InventedOwnSvc", f'"{OWN_SVC_EXE}"'),
            ],
            files=[
                file_row(pf_exe, signer=VENDOR),
                file_row(win_run, signer=VENDOR),
                file_row(RAW_PF, expanded="C:\\Program Files\\Invented Raw\\raw.exe",
                         signer=VENDOR),
                # RAW_PF86 has no file_facts row: its expanded path stays unknown.
                file_row(WOODGROVE_EXE, signer=VENDOR),
                file_row(DEFENDER_EXE, signer=MS),
                file_row(OWN_SVC_EXE, signer=MS),
            ],
            shortcuts=[
                shortcut(pf86_exe, name="Fabrikam Tools.lnk"),
                shortcut(f"{PROFILE}\\tool.exe", folder="Desktop", name="Tool.lnk"),
                shortcut(f"{CONTOSO_APPS}\\bin\\helper.exe", name="Contoso Helper.lnk"),
                shortcut("D:\\Docs\\Fab\\readme.txt", name="Readme.lnk"),
                shortcut("https://contoso.example/start", folder="CommonDesktopDirectory",
                         name="Contoso Web.lnk"),
            ],
            processes=[
                process(win_exe, pid=4201),
                process(pf86_exe, pid=4202),
                process(DEFENDER_EXE, name="MsMpEng", pid=4203),
                process(f"{TEMP_DIR}\\inv-setup\\setup.exe", name="setup", pid=4204),
                process("D:\\tool.exe", name="tool", pid=4205),
                process(f"{CONTOSO_APPS}\\con.exe", name="con", pid=4206),
                process(f"{NOTES_LOCATION}\\notes.exe", name="notes", pid=4207),
                process(f"{NOTES_LOCATION}\\sub\\notes-helper.exe", name="helper", pid=4208),
                process(None, name="hidden", pid=4209),
                process("", name="blank", pid=4210),
            ],
            programs=[
                win32("ContosoApps", "Contoso Apps", install_location=CONTOSO_APPS),
                with_paths(win32("WoodgroveTool", "Woodgrove Tool", install_location=None),
                           display_icon=f'"{WOODGROVE_EXE}",0'),
            ],
            packages=[msix("Fabrikam.Notes_0abc1def2ghj3", "Fabrikam.Notes",
                           install_location=NOTES_LOCATION)],
        )
        summary = self.collect(fake)

        with self.subTest(point="fixture: the service entry is own"):
            entry = self.by_key(self.detail(summary).get("autostart")).get(OWN_SVC_KEY)
            self.assertIsNotNone(entry, OWN_SVC_KEY)
            self.assertIs(entry.get("own"), True, entry)
        with self.subTest(point="source read"):
            status = self.source(summary, SOURCE).get("status")
            self.assertIn(status, ("read", "empty"), self.source(summary, SOURCE))
        with self.subTest(point="no portable item in the detail file"):
            self.assertEqual(self.portable(summary), {})
        with self.subTest(point="no portable item in the summary"):
            self.assertEqual(self.summary_portable(summary), {})
        with self.subTest(point="no portable change"):
            self.assertEqual([c for c in self.changes(summary)
                              if str(c.get("key")).startswith("portable:")], [])


# --- K3 --------------------------------------------------------------------------------

FAB2_FOLDER = "C:\\Tools\\Fab2"
FAB2_EXE = f"{FAB2_FOLDER}\\fab2.exe"
FAB2_RUN = run_value("FabrikamTwo", f'"{FAB2_EXE}"')
FAB2_RUN_KEY = "run:hkcu\\Run:FabrikamTwo"


class TestBoundary(PortableTestCase):
    def test_boundary(self):
        def machine():
            return responses(
                runs=[FAB2_RUN],
                files=[file_row(FAB2_EXE, signer=VENDOR)],
                shortcuts=[shortcut(FAB_EXE, name="Fab.lnk")],
                processes=[process(FAB2_EXE, name="fab2", pid=4301)],
                programs=[
                    win32("FabrikamOne", "Fabrikam One", install_location="C:\\Tools\\Fab"),
                    with_paths(win32("ContosoSetup", "Contoso Setup", install_location=None),
                               uninstall_string='"D:\\setup.exe" /S'),
                ],
                portable_exists=ok([exists_row(FAB2_EXE, True), exists_row(FAB_EXE, True)]),
            )

        data_dir = self.data_dir()
        first = self.collect(machine(), data_dir=data_dir, now=DAY1)
        items = self.portable(first)
        with self.subTest(run=1, point="sibling folder with a shared text prefix"):
            self.assert_item(items.get(portable_key(FAB2_FOLDER)), FAB2_FOLDER, [FAB2_EXE],
                             ["autostart", "process"])
        with self.subTest(run=1, point="a fact in the sibling folder links the portable "
                                       "program, not the win32 one"):
            fact = self.fact(first, FAB2_RUN_KEY, FAB2_EXE)
            self.assertEqual(fact.get("program"), portable_key(FAB2_FOLDER), fact)
            self.assertEqual(fact.get("linked_by"), "path", fact)
        with self.subTest(run=1, point="an UninstallString in a drive root hides nothing"):
            self.assert_item(items.get(portable_key(FAB_FOLDER)), FAB_FOLDER, [FAB_EXE],
                             ["shortcut"])

        second = self.collect(machine(), data_dir=data_dir, now=DAY2)
        listed = self.summary_programs(second)
        for folder in (FAB2_FOLDER, FAB_FOLDER):
            key = portable_key(folder)
            with self.subTest(run=2, point="a portable folder does not contain itself",
                              folder=folder):
                self.assertIn(key, self.portable(second), sorted(self.portable(second)))
                self.assertIn(key, listed, sorted(listed))
                self.assertNotIn("from_baseline", listed[key], listed[key])
                self.assertEqual(self.removed(second, key), [], self.changes(second))


# --- K4 --------------------------------------------------------------------------------

class TestKept(PortableTestCase):
    def test_kept_while_executable_exists(self):
        key = portable_key(CON_FOLDER)
        running = responses(processes=[process(CON_EXE, name="con", pid=4401)])

        with self.subTest(case="not running, executable exists, then confirmed missing"):
            data_dir = self.data_dir()
            first = self.collect(running, data_dir=data_dir, now=DAY1)
            self.assertIn(key, self.portable(first), sorted(self.portable(first)))

            second = self.collect(
                responses(processes=[],
                          portable_exists=ok([exists_row(CON_EXE, True)])),
                data_dir=data_dir, now=DAY2)
            listed = self.summary_programs(second)
            self.assertIn(key, listed, sorted(listed))
            self.assertNotIn("from_baseline", listed[key], listed[key])
            self.assertEqual(self.removed(second, key), [], self.changes(second))
            self.assert_item(self.portable(second).get(key), CON_FOLDER, [CON_EXE],
                             ["process"])

            third = self.collect(
                responses(processes=[],
                          portable_exists=ok([exists_row(CON_EXE, False)])),
                data_dir=data_dir, now=DAY3)
            self.assertEqual(len(self.removed(third, key)), 1, self.changes(third))
            self.assertEqual(self.removed(third, key)[0].get("source"), SOURCE,
                             self.removed(third, key))
            self.assertNotIn(key, self.summary_programs(third))
            self.assertNotIn(key, self.portable(third))

        with self.subTest(case="a win32 program now holds the folder"):
            data_dir = self.data_dir()
            self.collect(running, data_dir=data_dir, now=DAY1)
            second = self.collect(
                responses(processes=[process(CON_EXE, name="con", pid=4401)],
                          programs=[win32("ContosoPortable", "Contoso Portable",
                                          install_location=CON_FOLDER)],
                          portable_exists=ok([exists_row(CON_EXE, True)])),
                data_dir=data_dir, now=DAY2)
            self.assertEqual(len(self.removed(second, key)), 1, self.changes(second))
            self.assertNotIn(key, self.summary_programs(second))
            self.assertNotIn(key, self.portable(second))
            self.assertIn("win32:hklm64:ContosoPortable", self.summary_programs(second))


# --- K5 --------------------------------------------------------------------------------

class TestUnread(PortableTestCase):
    def assert_kept(self, summary, key):
        listed = self.summary_programs(summary)
        self.assertIn(key, listed, sorted(listed))
        self.assertIs(listed[key].get("from_baseline"), True, listed[key])
        self.assertEqual(self.removed(summary, key), [], self.changes(summary))

    def test_unread_is_not_gone(self):
        fab = portable_key(FAB_FOLDER)
        con = portable_key(CON_FOLDER)
        first_machine = {"shortcuts": [shortcut(FAB_EXE, name="Fab.lnk")],
                         "processes": [process(CON_EXE, name="con", pid=4501)]}

        job_cases = {
            "shortcuts": (fab, {"shortcuts": failure("Invented WScript.Shell error")}),
            "process_paths": (con, {"process_paths": failure("Invented Get-Process error")}),
            "portable_exists": (con, {"process_paths": ok([]), "shortcuts": ok([]),
                                      "portable_exists": failure("Invented Test-Path error")}),
        }
        for job, (key, overrides) in job_cases.items():
            with self.subTest(case=f"{job} job failed"):
                data_dir = self.data_dir()
                self.collect(responses(**first_machine), data_dir=data_dir, now=DAY1)
                second = self.collect(responses(**overrides), data_dir=data_dir, now=DAY2)
                self.assert_reasoned(self.notes_naming(second, job), job, second)
                self.assert_kept(second, key)

        for reason in ("not_local", "not_confirmed"):
            with self.subTest(case=f"existence unknown ({reason})"):
                data_dir = self.data_dir()
                self.collect(responses(**first_machine), data_dir=data_dir, now=DAY1)
                second = self.collect(
                    responses(portable_exists=ok([exists_row(CON_EXE, None, reason),
                                                  exists_row(FAB_EXE, None, reason)])),
                    data_dir=data_dir, now=DAY2)
                self.assert_reasoned(self.notes_naming(second, CON_EXE), CON_EXE, second)
                self.assert_kept(second, con)
                self.assert_kept(second, fab)

        with self.subTest(case="process paths not read are counted, never programs"):
            summary = self.collect(responses(processes=[
                process(None, name="hidden", pid=4511),
                process("", name="blank", pid=4512),
                process(CON_EXE, name="con", pid=4513),
            ]))
            counts = values_of(summary, "process_paths_unread")
            self.assertEqual(counts, [2], f"process_paths_unread in the summary: {counts}")
            self.assertEqual(set(self.portable(summary)), {con},
                             sorted(self.portable(summary)))


# --- K6 --------------------------------------------------------------------------------

FAB_TRAY_RUN = run_value("FabrikamTray", f'"{FAB_TRAY_EXE}" --tray')
FAB_TRAY_KEY = "run:hkcu\\Run:FabrikamTray"
CONTOSO_LOCATION = "C:\\Program Files\\Contoso\\App"
CONTOSO_KEY = "win32:hklm64:ContosoApp"


def contoso_app(icon_index):
    return with_paths(
        win32("ContosoApp", "Contoso App", publisher="Contoso Ltd",
              install_location=CONTOSO_LOCATION),
        display_icon=f'"{CONTOSO_LOCATION}\\contoso.exe",{icon_index}',
        uninstall_string=f'"{CONTOSO_LOCATION}\\uninstall.exe" /S')


class TestListed(PortableTestCase):
    def test_listed_like_any_program(self):
        key = portable_key(FAB_FOLDER)

        def machine(icon_index):
            return responses(
                runs=[FAB_TRAY_RUN],
                files=[file_row(FAB_TRAY_EXE, signer=VENDOR)],
                shortcuts=[shortcut(FAB_EXE, name="Fab.lnk")],
                programs=[contoso_app(icon_index)],
                portable_exists=ok([exists_row(FAB_EXE, True),
                                    exists_row(FAB_TRAY_EXE, True)]),
            )

        data_dir = self.data_dir()
        first = self.collect(machine(0), data_dir=data_dir, now=DAY1)

        listed = self.summary_programs(first)
        with self.subTest(run=1, point="summary programs"):
            self.assertIn(key, listed, sorted(listed))
            self.assertEqual(listed[key].get("source"), SOURCE, listed[key])
            self.assertIsNot(listed[key].get("own"), True, listed[key])
            id_number(listed[key].get("id"), "a")
        detail = self.detail_programs(first)
        with self.subTest(run=1, point="detail programs"):
            self.assertIn(key, detail, sorted(detail))
            self.assertEqual(detail[key].get("source"), SOURCE, detail[key])
            self.assertIs(detail[key].get("own"), False, detail[key])
            self.assertEqual(detail[key].get("id"), listed[key].get("id"))
            self.assert_item(detail[key], FAB_FOLDER, [FAB_EXE, FAB_TRAY_EXE],
                             ["autostart", "shortcut"])
        with self.subTest(run=1, point="autostart fact linked by path"):
            fact = self.fact(first, FAB_TRAY_KEY, FAB_TRAY_EXE)
            self.assertEqual(fact.get("program"), key, fact)
            self.assertEqual(fact.get("linked_by"), "path", fact)
        with self.subTest(run=1, point="win32 items have no new fields"):
            item = detail.get(CONTOSO_KEY)
            self.assertIsNotNone(item, sorted(detail))
            extra = [name for name in item
                     if "icon" in name.casefold() or "uninstall" in name.casefold()]
            self.assertEqual(extra, [], item)

        # Day 2: the same machine; only the icon index of the win32 entry differs.
        second = self.collect(machine(1), data_dir=data_dir, now=DAY2)
        with self.subTest(run=2, point="stable a id"):
            self.assertEqual(self.summary_programs(second).get(key, {}).get("id"),
                             listed[key].get("id"))
        with self.subTest(run=2, point="no changed win32 entry"):
            self.assertEqual([c for c in self.changes(second)
                              if c.get("source") == "win32_programs"], [],
                             self.changes(second))
        with self.subTest(run=2, point="no change at all"):
            self.assertEqual(self.changes(second), [])


# --- architect ruling (2026-11-18): a removed program's folder is a leftover -----------

GADGET_FOLDER = "D:\\Invented\\Gadget"
GADGET_EXE = f"{GADGET_FOLDER}\\gadget.exe"
GADGET_NAME = "Invented Gadget"
GADGET_RUN = run_value("InventedGadgetTray", f'"{GADGET_EXE}" --tray')
GADGET_RUN_KEY = "run:hkcu\\Run:InventedGadgetTray"


class TestRemovedProgramFolder(PortableTestCase):
    def test_removed_program_folder_is_leftover(self):
        """A win32 program removed between two runs whose old folder still holds an
        existing exe that a Run key starts: the folder is its leftover, never a new
        portable program."""
        program = win32("InventedGadget", GADGET_NAME, publisher="Invented Gadget Corp",
                        install_location=GADGET_FOLDER)
        files = [file_row(GADGET_EXE, signer=VENDOR)]
        data_dir = self.data_dir()
        first = self.collect(responses(runs=[GADGET_RUN], files=files, programs=[program]),
                             data_dir=data_dir, now=DAY1)
        self.assertEqual(self.portable(first), {}, sorted(self.portable(first)))

        second = self.collect(responses(runs=[GADGET_RUN], files=files),
                              data_dir=data_dir, now=DAY2)
        self.assertEqual(self.portable(second), {}, sorted(self.portable(second)))
        self.assertEqual(self.summary_portable(second), {},
                         sorted(self.summary_portable(second)))
        self.assertEqual([change for change in self.changes(second)
                          if str(change.get("key")).startswith("portable:")],
                         [], self.changes(second))
        self.assertEqual(self.fact(second, GADGET_RUN_KEY, GADGET_EXE).get("program"), None)

        leftovers = second.get("leftovers")
        self.assertIsInstance(leftovers, list, second.get("leftovers"))
        mine = [item for item in leftovers
                if isinstance(item, dict) and mentions(item.get("program"), GADGET_NAME)]
        self.assertEqual(len(mine), 1, leftovers)
        part_keys = {part.get("key") for part in mine[0].get("parts") or []
                     if isinstance(part, dict)}
        self.assertIn(GADGET_RUN_KEY, part_keys, mine[0])


# --- review round 1 ----------------------------------------------------------------------

DOWNLOADS_EXE = f"{PROFILE}\\Downloads\\setup-tool.exe"
DOWNLOADS_RUN = run_value("InventedDownloaded", f'"{DOWNLOADS_EXE}"')
DESKTOP_EXE = f"{DESKTOP}\\desk-tool.exe"
PROGRAM_DATA_EXE = "C:\\ProgramData\\pd-tool.exe"

WIDGETAPP_FOLDER = "D:\\Invented\\WidgetApp"
WIDGETAPP_EXE = f"{WIDGETAPP_FOLDER}\\widget.exe"
WIDGETAPP_RUN = run_value("InventedWidgetTray", f'"{WIDGETAPP_EXE}"')
WIDGETAPP_RUN_KEY = "run:hkcu\\Run:InventedWidgetTray"
SAME_NAME = "Invented Widget"
SAME_NAME_FOLDER = f"E:\\Portable\\{SAME_NAME}"
SAME_NAME_EXE = f"{SAME_NAME_FOLDER}\\w.exe"


class TestReviewRound1(PortableTestCase):
    def test_broad_folder_not_portable(self):
        """A profile's Downloads or Desktop, or C:\\ProgramData itself, is a folder
        many programs share, never a portable program."""
        summary = self.collect(responses(
            runs=[DOWNLOADS_RUN],
            files=[file_row(DOWNLOADS_EXE, signer=VENDOR)],
            shortcuts=[shortcut(DESKTOP_EXE, folder="Desktop", name="Desk Tool.lnk")],
            processes=[process(PROGRAM_DATA_EXE, name="pd-tool", pid=4501)]))
        self.assertEqual(self.source(summary, SOURCE).get("status"), "empty",
                         self.source(summary, SOURCE))
        self.assertEqual(self.portable(summary), {}, sorted(self.portable(summary)))

    def test_removed_program_with_portable_namesake(self):
        """A removed win32 program is removed even when a live portable program has
        its display name: a portable item is no installer's record."""
        program = win32("InventedWidget", SAME_NAME, publisher="Invented Widget Corp",
                        install_location=WIDGETAPP_FOLDER)
        files = [file_row(WIDGETAPP_EXE, signer=VENDOR)]
        running = [process(SAME_NAME_EXE, name="w", pid=4601)]
        data_dir = self.data_dir()
        first = self.collect(responses(runs=[WIDGETAPP_RUN], files=files, programs=[program],
                                       processes=running),
                             data_dir=data_dir, now=DAY1)
        self.assertIn(portable_key(SAME_NAME_FOLDER), self.portable(first))

        second = self.collect(responses(runs=[WIDGETAPP_RUN], files=files,
                                        processes=running),
                              data_dir=data_dir, now=DAY2)
        self.assertIn(portable_key(SAME_NAME_FOLDER), self.portable(second))
        self.assertNotIn(portable_key(WIDGETAPP_FOLDER), self.portable(second))
        leftovers = second.get("leftovers")
        self.assertIsInstance(leftovers, list, leftovers)
        mine = [item for item in leftovers
                if isinstance(item, dict) and mentions(item.get("program"), SAME_NAME)]
        self.assertEqual(len(mine), 1, leftovers)
        part_keys = {part.get("key") for part in mine[0].get("parts") or []
                     if isinstance(part, dict)}
        self.assertIn(WIDGETAPP_RUN_KEY, part_keys, mine[0])

    def test_portable_unread_keeps_vendor_folders(self):
        """portable_programs not read, win32 and msix read: the vendor folders are
        still listed (a list, not null)."""
        summary = self.collect(responses(
            shortcuts=failure("Invented shortcut read failure"),
            process_paths=failure("Invented process read failure"),
            file_facts=failure("Invented file facts failure")))
        self.assertEqual(self.source(summary, SOURCE).get("status"), "unreadable",
                         self.source(summary, SOURCE))
        self.assertEqual(self.source(summary, "win32_programs").get("status"), "empty")
        self.assertIsInstance(summary.get("vendor_folders"), list,
                              f"vendor_folders: {summary.get('vendor_folders')!r}; "
                              f"{self.not_checked(summary)}")


ORPHAN_VENDOR = "Invented Orphan Tools"


class TestReviewRound2(PortableTestCase):
    def test_portable_unread_leaves_unowned_folder_not_judged(self):
        """portable_programs not read and none in the baseline: a vendor folder no
        win32/msix program owns could be a portable program's, so it is listed with
        matched null and a cause naming portable_programs, never matched false."""
        summary = self.collect(responses(
            shortcuts=failure("Invented shortcut read failure"),
            process_paths=failure("Invented process read failure"),
            file_facts=failure("Invented file facts failure"),
            vendor_folders=vendor_listing([vendor_folder(VENDOR_PROGRAM_DATA,
                                                         ORPHAN_VENDOR)])))
        self.assertEqual(self.source(summary, SOURCE).get("status"), "unreadable",
                         self.source(summary, SOURCE))
        listed = summary.get("vendor_folders")
        self.assertIsInstance(listed, list, f"vendor_folders: {listed!r}")
        mine = [item for item in listed if isinstance(item, dict)
                and mentions(item.get("path"), ORPHAN_VENDOR)]
        self.assertEqual(len(mine), 1, listed)
        self.assertIsNone(mine[0].get("matched"), mine[0])
        self.assertTrue(mentions(mine[0].get("not_judged"), SOURCE), mine[0])

    def test_portable_blocked_leaves_unowned_folder_not_judged(self):
        """Everything else read, portable_programs unreadable only because its data
        file cannot be used: the unowned vendor folder is not judged either."""
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "portable-excluded.json")
            with open(broken, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            with mock.patch.object(self.inventory, "PORTABLE_EXCLUDED_FILE", broken):
                summary = self.collect(responses(
                    shortcuts=[shortcut("D:\\Invented\\Tool\\tool.exe")],
                    vendor_folders=vendor_listing([vendor_folder(VENDOR_PROGRAM_DATA,
                                                                 ORPHAN_VENDOR)])))
        self.assertEqual(self.source(summary, SOURCE).get("status"), "unreadable",
                         self.source(summary, SOURCE))
        listed = summary.get("vendor_folders")
        self.assertIsInstance(listed, list, f"vendor_folders: {listed!r}")
        mine = [item for item in listed if isinstance(item, dict)
                and mentions(item.get("path"), ORPHAN_VENDOR)]
        self.assertEqual(len(mine), 1, listed)
        self.assertIsNone(mine[0].get("matched"), mine[0])
        self.assertTrue(mentions(mine[0].get("not_judged"), SOURCE), mine[0])


# --- TEST-PLAN (b), new source: a single element ---------------------------------------

class TestSingleElement(PortableTestCase):
    """``ConvertTo-Json`` writes one row as an object, not a list (TEST-PLAN (b)); the
    ``shortcuts``, ``process_paths`` and ``portable_exists`` jobs each return one row.
    Added by loc-qa for plan 072."""

    def test_single_row_is_an_object(self):
        fab = portable_key(FAB_FOLDER)
        con = portable_key(CON_FOLDER)
        data_dir = self.data_dir()
        fake = responses()
        # Set after responses(): its shortcuts= and processes= parameters take row lists.
        fake.responses["shortcuts"] = ok(shortcut(FAB_EXE, name="Fab.lnk"))
        fake.responses["process_paths"] = ok(process(CON_EXE, name="con", pid=4601))
        first = self.collect(fake, data_dir=data_dir, now=DAY1)
        with self.subTest(run=1, point="one shortcut and one process as objects"):
            items = self.portable(first)
            self.assert_item(items.get(fab), FAB_FOLDER, [FAB_EXE], ["shortcut"])
            self.assert_item(items.get(con), CON_FOLDER, [CON_EXE], ["process"])
            self.assertEqual(self.notes_naming(first, "shortcuts"), [],
                             self.not_checked(first))
            self.assertEqual(self.notes_naming(first, "process_paths"), [],
                             self.not_checked(first))

        # Day 2: nothing starts them; one existence row, as an object, confirms one
        # executable missing; the other has no row and stays unknown.
        second = self.collect(responses(
            portable_exists=ok(exists_row(CON_EXE, False))),
            data_dir=data_dir, now=DAY2)
        with self.subTest(run=2, point="one portable_exists row as an object"):
            self.assertEqual(len(self.removed(second, con)), 1, self.changes(second))
            self.assertNotIn(con, self.summary_programs(second))


# --- plan 072 final review round 1 -------------------------------------------------------

NET_EXE = "Z:\\Invented\\Net\\net.exe"
NET_RUN = run_value("InventedNetTool", f'"{NET_EXE}"')


class TestFinalReviewRound1(PortableTestCase):
    def test_unchecked_autostart_target_not_portable(self):
        """An autostart target whose existence was not checked (``exists`` null, e.g.
        a network drive) gives no portable program (summary contract)."""
        summary = self.collect(responses(
            runs=[NET_RUN], files=[file_row(NET_EXE, exists=None, signer=VENDOR)]))
        self.assertNotIn(portable_key("Z:\\Invented\\Net"), self.portable(summary),
                         sorted(self.portable(summary)))

    def test_portable_unread_with_baseline_leaves_folder_not_judged(self):
        """portable_programs not read although the baseline holds portable programs:
        the baseline cannot stand in (a new portable program may own the folder), so
        the unowned vendor folder is not judged."""
        data_dir = self.data_dir()
        self.collect(responses(shortcuts=[shortcut(FAB_EXE, name="Fab.lnk")]),
                     data_dir=data_dir, now=DAY1)
        summary = self.collect(responses(
            shortcuts=failure("Invented shortcut read failure"),
            process_paths=failure("Invented process read failure"),
            file_facts=failure("Invented file facts failure"),
            vendor_folders=vendor_listing([vendor_folder(VENDOR_PROGRAM_DATA,
                                                         ORPHAN_VENDOR)])),
            data_dir=data_dir, now=DAY2)
        self.assertEqual(self.source(summary, SOURCE).get("status"), "unreadable",
                         self.source(summary, SOURCE))
        mine = [item for item in summary.get("vendor_folders") or []
                if isinstance(item, dict) and mentions(item.get("path"), ORPHAN_VENDOR)]
        self.assertEqual(len(mine), 1, summary.get("vendor_folders"))
        self.assertIsNone(mine[0].get("matched"), mine[0])
        self.assertTrue(mentions(mine[0].get("not_judged"), SOURCE), mine[0])

    def test_portable_input_unread_leaves_folder_not_judged(self):
        """portable_programs read, but one of its inputs (shortcuts, process_paths)
        failed: a portable program started only from it would be missed, so the
        unowned vendor folder is not judged and the cause names the input."""
        for name in ("shortcuts", "process_paths"):
            with self.subTest(input=name):
                fake = responses(
                    runs=[INV_RUN],
                    files=[file_row(INV_RAW, expanded=INV_EXE, signer=VENDOR)],
                    vendor_folders=vendor_listing([vendor_folder(VENDOR_PROGRAM_DATA,
                                                                 ORPHAN_VENDOR)]))
                fake.responses[name] = failure(f"Invented {name} failure")
                summary = self.collect(fake)
                self.assertIn(self.source(summary, SOURCE).get("status"),
                              ("read", "empty"), self.source(summary, SOURCE))
                mine = [item for item in summary.get("vendor_folders") or []
                        if isinstance(item, dict)
                        and mentions(item.get("path"), ORPHAN_VENDOR)]
                self.assertEqual(len(mine), 1, summary.get("vendor_folders"))
                self.assertIsNone(mine[0].get("matched"), mine[0])
                self.assertTrue(mentions(mine[0].get("not_judged"), name), mine[0])

    def test_partial_shortcut_read_leaves_folder_not_judged(self):
        """portable_programs and every input read, but one shortcut could not be
        read (``shortcuts not read``): the program it starts would be missed, so
        the unowned vendor folder is not judged and the cause names shortcuts."""
        unreadable = dict(shortcut(None, name="Locked.lnk"), Error="Access denied")
        summary = self.collect(responses(
            shortcuts=[shortcut(FAB_EXE, name="Fab.lnk"), unreadable],
            vendor_folders=vendor_listing([vendor_folder(VENDOR_PROGRAM_DATA,
                                                         ORPHAN_VENDOR)])))
        self.assertEqual(self.source(summary, "shortcuts").get("status"), "read",
                         self.source(summary, "shortcuts"))
        self.assertTrue(self.notes_naming(summary, "shortcuts not read"),
                        self.not_checked(summary))
        mine = [item for item in summary.get("vendor_folders") or []
                if isinstance(item, dict) and mentions(item.get("path"), ORPHAN_VENDOR)]
        self.assertEqual(len(mine), 1, summary.get("vendor_folders"))
        self.assertIsNone(mine[0].get("matched"), mine[0])
        self.assertTrue(mentions(mine[0].get("not_judged"), "shortcuts"), mine[0])

    def test_clean_inputs_judge_unowned_folder(self):
        """Clean data: portable_programs and its three inputs read whole, the
        unowned vendor folder is unmatched (matched false) with no portable cause."""
        summary = self.collect(responses(
            runs=[INV_RUN],
            files=[file_row(INV_RAW, expanded=INV_EXE, signer=VENDOR)],
            shortcuts=[shortcut(FAB_EXE, name="Fab.lnk")],
            processes=[process(CON_EXE, name="con", pid=4701)],
            vendor_folders=vendor_listing([vendor_folder(VENDOR_PROGRAM_DATA,
                                                         ORPHAN_VENDOR)])))
        self.assertEqual(self.source(summary, SOURCE).get("status"), "read",
                         self.source(summary, SOURCE))
        mine = [item for item in summary.get("vendor_folders") or []
                if isinstance(item, dict) and mentions(item.get("path"), ORPHAN_VENDOR)]
        self.assertEqual(len(mine), 1, summary.get("vendor_folders"))
        self.assertIs(mine[0].get("matched"), False, mine[0])
        self.assertFalse(mentions(mine[0].get("not_judged"), SOURCE), mine[0])
        self.assertEqual(self.notes_naming(summary, "of portable_programs"), [],
                         self.not_checked(summary))


if __name__ == "__main__":
    unittest.main()

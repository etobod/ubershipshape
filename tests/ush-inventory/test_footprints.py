"""Program footprints in ``<data dir>/state/footprints.json`` (plan 064, milestone M2,
criteria K1-K6).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``not_checked``, the
detail file, the injected ``now`` and ``admin``) is described in ``fakes.py``; firewall
rows in ``fakes_additions.py``, vendor folder rows in ``fakes_vendor_folders.py``,
autostart rows in ``fakes_autostart.py``.

Interface under test (from the plan):

- ``skills/ush-inventory/scripts/footprints.py`` has ``load(data_dir)`` returning
  ``{status: none|read|unreadable, reason, path, entries}`` as ``review_dates.load``; it
  never raises.
- Every ``ush-inventory`` run writes ``<data dir>/state/footprints.json``: top-level
  ``entries`` (one per listed program key, ``{key, name, first_seen, gone_since,
  traces}``; each trace ``{kind, key, linked_by, first_seen, present, gone_since,
  seen_elevated}``) and top-level ``shared`` (vendor folders that hold several programs'
  locations). Dates are UTC dates ``YYYY-MM-DD`` of the injected ``now``.
- The summary has ``footprint_counts`` ``{programs, programs_gone, traces,
  traces_present, shared, gone_with_present_traces}`` or ``null`` with a ``not_checked``
  entry naming ``footprints.json``; the detail file has ``footprints`` (null when the save
  failed).

Assumptions added by these tests beyond the plan text:

- Traces are found by their own ``key`` (the autostart item key, ``firewall:<store>:<name>``
  or ``vendor_folder:<case-folded path>``); the ``kind`` values are not pinned.
- A ``shared`` item is an object with the vendor folder ``key`` and ``programs``, the list
  of every program key linked to it (order not pinned).
- The schema version is a top-level field whose name contains ``version``; the valid
  file for ``load`` is the one an inventory run on invented data wrote in a temporary
  directory, so the test pins no field name the plan leaves open.
- ``inventory`` saves through ``baseline.save_json`` (``None`` on success, else a reason)
  reached as ``inventory.baseline.save_json``, with ``footprints`` in the file name
  argument.
- ``footprint_counts.traces`` and ``traces_present`` count the traces in the programs'
  ``traces`` lists.

PowerShell never starts; every value is invented (Contoso, Fabrikam).
"""

import copy
import json
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

from .fakes import NOW, FakePowerShell, failure, msix, ok, win32
from .fakes_additions import custom_rule, firewall_result, fw_value, m2_responses
from .fakes_autostart import (
    CLEAN_FILES,
    CLEAN_TASKS,
    VENDOR,
    clean_responses,
    exec_action,
    facts,
    file_row,
    run_value,
    startup_file,
    task,
)
from .fakes_vendor_folders import (
    PROGRAM_DATA,
    PROGRAM_FILES,
    ROOTS,
    WINDOWS_NAMES,
    VendorFoldersTestCase,
    data_file_text,
    folder,
    folder_key,
    folder_path,
    listing,
    root_row,
)

DAY1 = NOW
DAY2 = NOW + timedelta(days=3)
DAY3 = NOW + timedelta(days=7)


def day(moment):
    return moment.astimezone(timezone.utc).date().isoformat()


FOOTPRINTS_FILE = "footprints.json"

CONTOSO_LOCATION = "C:\\Program Files\\Contoso\\App"
CONTOSO_KEY = "win32:hklm64:ContosoApp"
UPDATER_LOCATION = "C:\\Program Files\\Contoso\\Updater"
UPDATER_KEY = "win32:hklm64:ContosoUpdater"
NOTES_FAMILY = "Fabrikam.Notes_0abc1def2ghj3"
NOTES_KEY = f"msix:{NOTES_FAMILY}"

TRAY_TARGET = f"{CONTOSO_LOCATION}\\tray.exe"
HELPER_TARGET = f"{CONTOSO_LOCATION}\\helper.exe"
TASK_TARGET = f"{CONTOSO_LOCATION}\\update.exe"
APP_ONE = f"{CONTOSO_LOCATION}\\app.exe"
APP_TWO = f"{CONTOSO_LOCATION}\\server.exe"

TRAY = run_value("ContosoTray", f'"{TRAY_TARGET}" --tray')
HELPER = run_value("ContosoHelper", f'"{HELPER_TARGET}"')
UPDATE_TASK = task("ContosoUpdate", [exec_action(TASK_TARGET, "/check")])

TRAY_KEY = "run:hkcu\\Run:ContosoTray"
HELPER_KEY = "run:hkcu\\Run:ContosoHelper"
TASK_KEY = "task:\\Invented\\ContosoUpdate"

RULE_ONE = "{00000000-0000-0000-0000-0000000F6401}"
RULE_TWO = "{00000000-0000-0000-0000-0000000F6402}"
RULE_ONE_KEY = f"firewall:local:{RULE_ONE}"
RULE_TWO_KEY = f"firewall:local:{RULE_TWO}"
RULE_ONE_ROW = fw_value(RULE_ONE, custom_rule("Contoso App", app=APP_ONE))
RULE_TWO_ROW = fw_value(RULE_TWO, custom_rule("Contoso Server", port="8443", app=APP_TWO))

CONTOSO_FOLDER = folder(PROGRAM_FILES, "Contoso")
CONTOSO_FOLDER_KEY = folder_key(folder_path(PROGRAM_FILES, "Contoso"))

FILES = [file_row(path, signer=VENDOR) for path in (TRAY_TARGET, HELPER_TARGET, TASK_TARGET)]

SAVE_REASON = "invented: cannot write footprints.json.tmp: access denied"


def contoso_app():
    return win32("ContosoApp", "Contoso App", publisher="Contoso Ltd",
                 install_location=CONTOSO_LOCATION)


def contoso_updater():
    return win32("ContosoUpdater", "Contoso Updater", publisher="Contoso Ltd",
                 install_location=UPDATER_LOCATION)


def fabrikam_notes():
    return msix(NOTES_FAMILY, "Fabrikam.Notes")


def machine(programs=None, packages=None, runs=(TRAY,), tasks=(), rules=(RULE_ONE_ROW,),
            folders=(CONTOSO_FOLDER,), **overrides):
    """An invented machine: Contoso App (win32) with a Run value, a firewall rule and its
    vendor folder, and Fabrikam Notes (msix) without traces."""
    responses = clean_responses(extra_files=FILES)
    responses.update(m2_responses(firewall_rules=ok(firewall_result(local=list(rules)))))
    responses["win32_programs"] = ok(list([contoso_app()] if programs is None else programs))
    responses["msix_programs"] = ok(list([fabrikam_notes()] if packages is None
                                         else packages))
    responses["run_keys"] = ok(list(runs))
    responses["scheduled_tasks"] = ok(list(CLEAN_TASKS) + list(tasks))
    responses["vendor_folders"] = listing(list(folders))
    responses.update(overrides)
    return FakePowerShell(responses)


class FootprintsTestCase(VendorFoldersTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.footprints = load_script("ush-inventory", "footprints")

    # --- helpers ------------------------------------------------------------------------

    @staticmethod
    def file_path(data_dir):
        return Path(data_dir) / "state" / FOOTPRINTS_FILE

    def saved(self, data_dir):
        path = self.file_path(data_dir)
        self.assertTrue(path.is_file(), f"{path} was not written")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))
        self.assertIsInstance(data.get("entries"), list, data)
        self.assertIsInstance(data.get("shared"), list, data)
        return data

    def programs(self, data_dir):
        """The saved program entries by key."""
        result = {}
        for entry in self.saved(data_dir)["entries"]:
            key = entry.get("key")
            self.assertNotIn(key, result, f"duplicate program entry {key}")
            self.assertIsInstance(entry.get("traces"), list, entry)
            result[key] = entry
        return result

    def program(self, data_dir, key):
        programs = self.programs(data_dir)
        self.assertIn(key, programs, sorted(map(str, programs)))
        return programs[key]

    def traces(self, entry):
        """The traces of one program entry by trace key."""
        result = {}
        for trace in entry.get("traces") or []:
            key = trace.get("key")
            self.assertNotIn(key, result, f"duplicate trace {key} in {entry.get('key')}")
            result[key] = trace
        return result

    def trace(self, data_dir, program_key, trace_key):
        traces = self.traces(self.program(data_dir, program_key))
        self.assertIn(trace_key, traces, f"{program_key}: {sorted(map(str, traces))}")
        return traces[trace_key]

    def shared(self, data_dir):
        """The saved ``shared`` items by key."""
        result = {}
        for item in self.saved(data_dir)["shared"]:
            self.assertIsInstance(item, dict, item)
            key = item.get("key")
            self.assertNotIn(key, result, f"duplicate shared item {key}")
            result[key] = item
        return result

    def assert_dates(self, item, first_seen, gone_since):
        self.assertIn("first_seen", item, item)
        self.assertIn("gone_since", item, item)
        self.assertEqual(item["first_seen"], first_seen, item)
        self.assertEqual(item["gone_since"], gone_since, item)

    def assert_trace(self, trace, first_seen, present, gone_since):
        self.assert_dates(trace, first_seen, gone_since)
        self.assertIn("present", trace, trace)
        self.assertIs(trace["present"], present, trace)

    def counts(self, summary):
        self.assertIn("footprint_counts", summary, sorted(summary))
        counts = summary["footprint_counts"]
        self.assertIsInstance(counts, dict, f"footprint_counts: {counts!r}")
        return counts

    def footprint_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if FOOTPRINTS_FILE in json.dumps(item)]


class TestLoad(FootprintsTestCase):
    def assert_unreadable(self, data_dir):
        result = self.footprints.load(data_dir)
        self.assertIsInstance(result, dict, result)
        self.assertEqual(result.get("status"), "unreadable", result)
        self.assertEqual(result.get("path"), str(self.file_path(data_dir)), result)
        self.assertFalse(result.get("entries"), result)
        reason = result.get("reason")
        self.assertIsInstance(reason, str, result)
        self.assertTrue(reason.strip(), result)

    def written(self):
        """A data directory holding a valid footprints.json written by an inventory run
        on invented data, and its parsed content."""
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        data = self.saved(data_dir)
        traced = [entry for entry in data["entries"] if entry.get("traces")]
        self.assertTrue(traced, f"no program with traces in {data}")
        return data_dir, data

    def rewrite(self, data_dir, data):
        text = data if isinstance(data, str) else json.dumps(data, indent=2)
        self.file_path(data_dir).write_text(text, encoding="utf-8")

    def test_load_states(self):
        with self.subTest(case="missing file"):
            data_dir = self.data_dir()
            result = self.footprints.load(data_dir)
            self.assertIsInstance(result, dict, result)
            self.assertEqual(result.get("status"), "none", result)
            self.assertEqual(result.get("entries"), [], result)
            self.assertIsNone(result.get("reason"), result)
            self.assertEqual(result.get("path"), str(self.file_path(data_dir)), result)
            self.assertFalse(self.file_path(data_dir).exists())

        with self.subTest(case="valid file"):
            data_dir, data = self.written()
            result = self.footprints.load(data_dir)
            self.assertIsInstance(result, dict, result)
            self.assertEqual(result.get("status"), "read", result)
            self.assertIsNone(result.get("reason"), result)
            self.assertEqual(result.get("path"), str(self.file_path(data_dir)), result)
            entries = result.get("entries")
            self.assertIsInstance(entries, list, result)
            self.assertEqual(sorted(entry.get("key") for entry in entries),
                             sorted(entry.get("key") for entry in data["entries"]), result)
            self.assertIn(CONTOSO_KEY, {entry.get("key") for entry in entries}, result)

        def bad_schema(data):
            names = [name for name in data if "version" in name]
            self.assertEqual(len(names), 1, f"no single schema version field: {sorted(data)}")
            data[names[0]] = 999

        def bad_program_date(data):
            data["entries"][0]["first_seen"] = "2026-02-30"

        def bad_trace_date(data):
            entry = next(e for e in data["entries"] if e.get("traces"))
            entry["traces"][0]["first_seen"] = "20.09.2026"

        def bad_linked_by(data):
            entry = next(e for e in data["entries"] if e.get("traces"))
            entry["traces"][0]["linked_by"] = "name"

        def duplicate_key(data):
            data["entries"].append(copy.deepcopy(data["entries"][0]))

        cases = {
            "wrong schema version": bad_schema,
            "bad program date": bad_program_date,
            "bad trace date": bad_trace_date,
            "linked_by outside path/install_location": bad_linked_by,
            "two entries with the same key": duplicate_key,
        }
        with self.subTest(case="bad JSON"):
            data_dir, _ = self.written()
            self.rewrite(data_dir, '{"entries": [{"key": "win32:hklm64:ContosoApp"')
            self.assert_unreadable(data_dir)
        for case, spoil in cases.items():
            with self.subTest(case=case):
                data_dir, data = self.written()
                spoil(data)
                self.rewrite(data_dir, data)
                self.assert_unreadable(data_dir)


class TestUpdate(FootprintsTestCase):
    def test_first_and_second_run(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)

        with self.subTest(run=1, point="one entry per listed program"):
            programs = self.programs(data_dir)
            self.assertEqual(set(programs), {CONTOSO_KEY, NOTES_KEY}, sorted(programs))
            self.assertEqual(programs[CONTOSO_KEY].get("name"), "Contoso App")
            for entry in programs.values():
                self.assert_dates(entry, day(DAY1), None)
            self.assertEqual(programs[NOTES_KEY]["traces"], [], programs[NOTES_KEY])
        with self.subTest(run=1, point="each linked trace stamped today"):
            traces = self.traces(self.program(data_dir, CONTOSO_KEY))
            self.assertEqual(set(traces), {TRAY_KEY, RULE_ONE_KEY, CONTOSO_FOLDER_KEY},
                             sorted(traces))
            for trace in traces.values():
                self.assert_trace(trace, day(DAY1), True, None)
            self.assertEqual(traces[TRAY_KEY].get("linked_by"), "path")
            self.assertEqual(traces[RULE_ONE_KEY].get("linked_by"), "path")
            self.assertEqual(traces[CONTOSO_FOLDER_KEY].get("linked_by"), "install_location")

        # Day 2: the Run value is gone (run_keys read), a second rule is new.
        self.collect(machine(runs=(), rules=(RULE_ONE_ROW, RULE_TWO_ROW)),
                     data_dir=data_dir, now=DAY2)

        with self.subTest(run=2, point="program first_seen carried"):
            self.assert_dates(self.program(data_dir, CONTOSO_KEY), day(DAY1), None)
            self.assert_dates(self.program(data_dir, NOTES_KEY), day(DAY1), None)
        with self.subTest(run=2, point="traces still present keep first_seen"):
            self.assert_trace(self.trace(data_dir, CONTOSO_KEY, RULE_ONE_KEY),
                              day(DAY1), True, None)
            self.assert_trace(self.trace(data_dir, CONTOSO_KEY, CONTOSO_FOLDER_KEY),
                              day(DAY1), True, None)
        with self.subTest(run=2, point="new trace stamped with the new day"):
            trace = self.trace(data_dir, CONTOSO_KEY, RULE_TWO_KEY)
            self.assert_trace(trace, day(DAY2), True, None)
            self.assertEqual(trace.get("linked_by"), "path", trace)
        with self.subTest(run=2, point="trace missing from its read source is gone"):
            self.assert_trace(self.trace(data_dir, CONTOSO_KEY, TRAY_KEY),
                              day(DAY1), False, day(DAY2))


class TestRemovedProgram(FootprintsTestCase):
    def test_removed_program_keeps_present_traces(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        # Day 2: Contoso App is no longer listed (win32_programs read); its Run value,
        # firewall rule and vendor folder are still on the machine.
        second = self.collect(machine(programs=[]), data_dir=data_dir, now=DAY2)

        with self.subTest(point="program kept with gone_since"):
            self.assert_dates(self.program(data_dir, CONTOSO_KEY), day(DAY1), day(DAY2))
            self.assert_dates(self.program(data_dir, NOTES_KEY), day(DAY1), None)
        for key in (TRAY_KEY, RULE_ONE_KEY, CONTOSO_FOLDER_KEY):
            with self.subTest(point="trace still present", trace=key):
                self.assert_trace(self.trace(data_dir, CONTOSO_KEY, key),
                                  day(DAY1), True, None)
        with self.subTest(point="counts"):
            counts = self.counts(second)
            self.assertEqual(counts.get("programs_gone"), 1, counts)
            self.assertEqual(counts.get("gone_with_present_traces"), 1, counts)
            self.assertEqual(counts.get("traces"), 3, counts)
            self.assertEqual(counts.get("traces_present"), 3, counts)


class TestSharedFolder(FootprintsTestCase):
    def assert_shared(self, data_dir, keys):
        shared = self.shared(data_dir)
        self.assertIn(CONTOSO_FOLDER_KEY, shared, sorted(map(str, shared)))
        programs = shared[CONTOSO_FOLDER_KEY].get("programs")
        self.assertIsInstance(programs, list, shared[CONTOSO_FOLDER_KEY])
        self.assertEqual(sorted(programs), sorted(keys), shared[CONTOSO_FOLDER_KEY])

    def assert_in_no_traces(self, data_dir):
        for key, entry in self.programs(data_dir).items():
            self.assertNotIn(CONTOSO_FOLDER_KEY, self.traces(entry), key)

    def test_folder_becomes_and_stays_shared(self):
        data_dir = self.data_dir()
        # Program A (Contoso App) has the vendor folder as its only trace.
        self.collect(machine(runs=(), rules=()), data_dir=data_dir, now=DAY1)
        with self.subTest(day=1, point="one program's trace"):
            trace = self.trace(data_dir, CONTOSO_KEY, CONTOSO_FOLDER_KEY)
            self.assertEqual(trace.get("linked_by"), "install_location", trace)
            self.assertEqual(self.shared(data_dir), {})

        # Day 2: program B (Contoso Updater) is installed under the same folder.
        second = self.collect(machine(programs=[contoso_app(), contoso_updater()], runs=(),
                                      rules=()),
                              data_dir=data_dir, now=DAY2)
        with self.subTest(day=2, point="moved to shared with A and B"):
            self.assert_shared(data_dir, [CONTOSO_KEY, UPDATER_KEY])
            self.assert_in_no_traces(data_dir)
            self.assertEqual(self.counts(second).get("shared"), 1, self.counts(second))

        # Day 3: A is removed; the folder now holds only B's location.
        third = self.collect(machine(programs=[contoso_updater()], runs=(), rules=()),
                             data_dir=data_dir, now=DAY3)
        with self.subTest(day=3, point="still shared with A and B"):
            self.assert_dates(self.program(data_dir, CONTOSO_KEY), day(DAY1), day(DAY3))
            self.assert_shared(data_dir, [CONTOSO_KEY, UPDATER_KEY])
            self.assert_in_no_traces(data_dir)
        with self.subTest(day=3, point="counts"):
            counts = self.counts(third)
            self.assertEqual(counts.get("shared"), 1, counts)
            self.assertEqual(counts.get("gone_with_present_traces"), 0, counts)


class TestUnread(FootprintsTestCase):
    def first_run(self, admin=False, **kwargs):
        data_dir = self.data_dir()
        self.collect(machine(**kwargs), data_dir=data_dir, admin=admin, now=DAY1)
        return data_dir

    def assert_kept(self, data_dir, program_key, trace_key):
        self.assert_trace(self.trace(data_dir, program_key, trace_key), day(DAY1), True, None)

    def test_unread_source_keeps_trace(self):
        cases = {
            "run_keys not read": (TRAY_KEY, {"run_keys": failure("Invented registry error")}),
            "firewall_rules not read": (
                RULE_ONE_KEY, {"firewall_rules": failure("Invented firewall key error")}),
            "vendor root not read": (
                CONTOSO_FOLDER_KEY,
                {"vendor_folders": listing(
                    [CONTOSO_FOLDER],
                    unreadable={PROGRAM_FILES: "Invented access denied"})}),
        }
        for case, (trace_key, overrides) in cases.items():
            with self.subTest(case=case):
                data_dir = self.first_run()
                self.collect(machine(runs=(), rules=(), folders=(), **overrides),
                             data_dir=data_dir, now=DAY2)
                self.assert_kept(data_dir, CONTOSO_KEY, trace_key)

    def test_vendor_section_none_keeps_trace(self):
        data_dir = self.first_run()
        self.data_file.write_text("{not json", encoding="utf-8")
        self.collect(machine(folders=()), data_dir=data_dir, now=DAY2)
        self.assert_kept(data_dir, CONTOSO_KEY, CONTOSO_FOLDER_KEY)

    def test_task_seen_elevated_stays_present(self):
        data_dir = self.first_run(admin=True, tasks=(UPDATE_TASK,))
        trace = self.trace(data_dir, CONTOSO_KEY, TASK_KEY)
        self.assertIs(trace.get("seen_elevated"), True, trace)

        # A normal run reads scheduled_tasks but does not see the task.
        self.collect(machine(tasks=()), data_dir=data_dir, admin=False, now=DAY2)
        trace = self.trace(data_dir, CONTOSO_KEY, TASK_KEY)
        self.assert_trace(trace, day(DAY1), True, None)
        self.assertIs(trace.get("seen_elevated"), True, trace)

    def test_failed_firewall_apps_adds_and_drops_nothing(self):
        data_dir = self.first_run()
        self.collect(machine(rules=(RULE_ONE_ROW, RULE_TWO_ROW),
                             firewall_apps=failure("Invented expansion error")),
                     data_dir=data_dir, now=DAY2)
        traces = self.traces(self.program(data_dir, CONTOSO_KEY))
        self.assertNotIn(RULE_TWO_KEY, traces, sorted(traces))
        self.assertIn(RULE_ONE_KEY, traces, sorted(traces))
        self.assert_trace(traces[RULE_ONE_KEY], day(DAY1), True, None)

    def test_failed_file_facts_adds_and_drops_nothing(self):
        data_dir = self.first_run()
        self.collect(machine(runs=(TRAY, HELPER),
                             file_facts=failure("Invented file facts error")),
                     data_dir=data_dir, now=DAY2)
        traces = self.traces(self.program(data_dir, CONTOSO_KEY))
        self.assertNotIn(HELPER_KEY, traces, sorted(traces))
        self.assertIn(TRAY_KEY, traces, sorted(traces))
        self.assert_trace(traces[TRAY_KEY], day(DAY1), True, None)

    def test_program_of_unread_source_not_gone(self):
        cases = {
            "win32_programs not read": (
                CONTOSO_KEY, {"win32_programs": failure("Invented uninstall key error")}),
            "msix_programs not read": (
                NOTES_KEY, {"msix_programs": failure("Invented Appx error")}),
        }
        for case, (program_key, overrides) in cases.items():
            with self.subTest(case=case):
                data_dir = self.first_run()
                self.collect(machine(**overrides), data_dir=data_dir, now=DAY2)
                self.assert_dates(self.program(data_dir, program_key), day(DAY1), None)


USER_TOOL_KEY = "win32:hkcu:FabrikamTool"
MACHINE_RUN = run_value("ContosoHelper", f'"{HELPER_TARGET}"', hive="hklm64")
MACHINE_RUN_KEY = "run:hklm64\\Run:ContosoHelper"
START_TARGET = f"{CONTOSO_LOCATION}\\start.exe"
START_NAME = "ContosoStart.lnk"
START_KEY = f"startup:user:{START_NAME}"
START_FILE = startup_file(
    START_NAME,
    f"C:\\Users\\Invented\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs"
    f"\\Startup\\{START_NAME}",
    target=START_TARGET)


USER_TOOL_NAME = "Fabrikam Tool"
# The elevated account's own per-user things: a Run value into Contoso's folder and an
# HKCU program installed under a vendor folder of its own.
ADMIN_HELPER = HELPER
ADMIN_HELPER_KEY = HELPER_KEY
WOODGROVE_FOLDER = folder(PROGRAM_FILES, "Woodgrove")
WOODGROVE_FOLDER_KEY = folder_key(folder_path(PROGRAM_FILES, "Woodgrove"))
ADMIN_TOOL_KEY = "win32:hkcu:WoodgroveTool"
# A machine Run value and an HKLM program that are new on the elevated day.
MACHINE_AGENT = run_value("ContosoAgent", f'"{TASK_TARGET}"', hive="hklm64")
MACHINE_AGENT_KEY = "run:hklm64\\Run:ContosoAgent"


def admin_tool():
    return win32("WoodgroveTool", "Woodgrove Tool", hive="hkcu",
                 install_location=f"{folder_path(PROGRAM_FILES, 'Woodgrove')}\\Tool")


def per_user_machine(user=True, machine_run=True, user_tool_name=USER_TOOL_NAME,
                     extra_programs=(), extra_runs=(), extra_folders=()):
    """Contoso App (HKLM) with, when ``machine_run``, a machine Run value (HKLM) and,
    when ``user``, a per-user program (HKCU), the MSIX package, a Run value under HKCU
    and a user Startup file; ``extra_*`` are added as they are."""
    return machine(
        programs=[contoso_app()] + ([win32("FabrikamTool", user_tool_name, hive="hkcu")]
                                    if user else []) + list(extra_programs),
        packages=[fabrikam_notes()] if user else [],
        runs=(((TRAY,) if user else ()) + ((MACHINE_RUN,) if machine_run else ())
              + tuple(extra_runs)),
        folders=(CONTOSO_FOLDER, *extra_folders),
        startup_folders=ok([START_FILE] if user else []),
        file_facts=facts(*CLEAN_FILES, *FILES, file_row(START_TARGET, signer=VENDOR)))


class TestElevatedPerUser(FootprintsTestCase):
    """An elevated run may read another account's HKCU, user Startup folder and MSIX
    packages: their keys are not read there, never gone (as ``hkcu_absent``)."""

    PER_USER_TRACES = (TRAY_KEY, START_KEY)

    def first_run(self):
        data_dir = self.data_dir()
        self.collect(per_user_machine(), data_dir=data_dir, now=DAY1)
        for key in (*self.PER_USER_TRACES, MACHINE_RUN_KEY):
            self.assert_trace(self.trace(data_dir, CONTOSO_KEY, key), day(DAY1), True, None)
        return data_dir

    def test_elevated_run_keeps_per_user_keys(self):
        data_dir = self.first_run()
        # Day 2, elevated: nothing per-user is seen, the machine Run value is gone too.
        self.collect(per_user_machine(user=False, machine_run=False), data_dir=data_dir,
                     admin=True, now=DAY2)
        for key in (USER_TOOL_KEY, NOTES_KEY):
            with self.subTest(day=2, program=key):
                self.assert_dates(self.program(data_dir, key), day(DAY1), None)
        for key in self.PER_USER_TRACES:
            with self.subTest(day=2, trace=key):
                trace = self.trace(data_dir, CONTOSO_KEY, key)
                self.assert_trace(trace, day(DAY1), True, None)
                self.assertIs(trace.get("seen_elevated"), False, trace)
        with self.subTest(day=2, point="machine key still gone"):
            self.assert_trace(self.trace(data_dir, CONTOSO_KEY, MACHINE_RUN_KEY),
                              day(DAY1), False, day(DAY2))

        # Day 3, normal: the per-user keys are there; nothing flapped.
        self.collect(per_user_machine(), data_dir=data_dir, now=DAY3)
        for key in self.PER_USER_TRACES:
            with self.subTest(day=3, trace=key):
                self.assert_trace(self.trace(data_dir, CONTOSO_KEY, key), day(DAY1), True,
                                  None)

    def test_clean_elevated_run_with_per_user_keys_present(self):
        data_dir = self.first_run()
        self.collect(per_user_machine(), data_dir=data_dir, admin=True, now=DAY2)
        for key in (CONTOSO_KEY, USER_TOOL_KEY, NOTES_KEY):
            with self.subTest(program=key):
                self.assert_dates(self.program(data_dir, key), day(DAY1), None)
        for key in (*self.PER_USER_TRACES, MACHINE_RUN_KEY):
            with self.subTest(trace=key):
                self.assert_trace(self.trace(data_dir, CONTOSO_KEY, key), day(DAY1), True,
                                  None)

    def test_clean_normal_run_marks_per_user_keys_gone(self):
        data_dir = self.first_run()
        self.collect(per_user_machine(user=False, machine_run=False), data_dir=data_dir,
                     now=DAY2)
        for key in (USER_TOOL_KEY, NOTES_KEY):
            with self.subTest(program=key):
                self.assert_dates(self.program(data_dir, key), day(DAY1), day(DAY2))
        for key in (*self.PER_USER_TRACES, MACHINE_RUN_KEY):
            with self.subTest(trace=key):
                self.assert_trace(self.trace(data_dir, CONTOSO_KEY, key), day(DAY1), False,
                                  day(DAY2))

    def test_elevated_run_with_per_user_keys_present_changes_nothing_per_user(self):
        data_dir = self.first_run()
        before = {key: copy.deepcopy(entry) for key, entry in self.programs(data_dir).items()}
        # Day 2, elevated: the elevated account has the same per-user keys (its HKCU
        # program under another name), a Run value of its own into Contoso's folder and
        # an HKCU program of its own under a vendor folder.
        self.collect(per_user_machine(user_tool_name="Fabrikam Tool (admin)",
                                      extra_programs=[admin_tool()],
                                      extra_runs=(ADMIN_HELPER,),
                                      extra_folders=(WOODGROVE_FOLDER,)),
                     data_dir=data_dir, admin=True, now=DAY2)
        programs = self.programs(data_dir)
        for key in (USER_TOOL_KEY, NOTES_KEY):
            with self.subTest(day=2, program=key):
                self.assertEqual(programs[key], before[key])
        with self.subTest(day=2, point="name not overwritten"):
            self.assertEqual(programs[USER_TOOL_KEY].get("name"), USER_TOOL_NAME)
        for key in self.PER_USER_TRACES:
            with self.subTest(day=2, trace=key):
                trace = self.trace(data_dir, CONTOSO_KEY, key)
                self.assert_trace(trace, day(DAY1), True, None)
                self.assertIs(trace.get("seen_elevated"), False, trace)
        with self.subTest(day=2, point="no per-user program of the elevated account"):
            self.assertNotIn(ADMIN_TOOL_KEY, programs, sorted(programs))
        with self.subTest(day=2, point="no new per-user trace or link"):
            self.assertNotIn(ADMIN_HELPER_KEY, self.traces(programs[CONTOSO_KEY]))
            for key, entry in programs.items():
                self.assertNotIn(WOODGROVE_FOLDER_KEY, self.traces(entry), key)
            self.assertNotIn(WOODGROVE_FOLDER_KEY, self.shared(data_dir))

        # Day 3, normal: the user's per-user keys are gone.
        self.collect(per_user_machine(user=False), data_dir=data_dir, now=DAY3)
        for key in (USER_TOOL_KEY, NOTES_KEY):
            with self.subTest(day=3, program=key):
                self.assert_dates(self.program(data_dir, key), day(DAY1), day(DAY3))
        for key in self.PER_USER_TRACES:
            with self.subTest(day=3, trace=key):
                self.assert_trace(self.trace(data_dir, CONTOSO_KEY, key), day(DAY1), False,
                                  day(DAY3))

    def test_clean_elevated_run_keeps_per_machine_keys(self):
        data_dir = self.first_run()
        # Day 2, elevated: the machine Run value is still there, a new machine Run value
        # and a new HKLM program appear.
        self.collect(per_user_machine(extra_programs=[contoso_updater()],
                                      extra_runs=(MACHINE_AGENT,)),
                     data_dir=data_dir, admin=True, now=DAY2)
        with self.subTest(point="machine program stays listed"):
            self.assert_dates(self.program(data_dir, CONTOSO_KEY), day(DAY1), None)
        with self.subTest(point="new HKLM program added"):
            self.assert_dates(self.program(data_dir, UPDATER_KEY), day(DAY2), None)
        with self.subTest(point="machine Run value seen elevated"):
            trace = self.trace(data_dir, CONTOSO_KEY, MACHINE_RUN_KEY)
            self.assert_trace(trace, day(DAY1), True, None)
            self.assertIs(trace.get("seen_elevated"), True, trace)
        with self.subTest(point="new machine Run value linked"):
            trace = self.trace(data_dir, CONTOSO_KEY, MACHINE_AGENT_KEY)
            self.assert_trace(trace, day(DAY2), True, None)
            self.assertIs(trace.get("seen_elevated"), True, trace)

        # Day 3, elevated: the machine Run value is gone.
        self.collect(per_user_machine(machine_run=False, extra_programs=[contoso_updater()],
                                      extra_runs=(MACHINE_AGENT,)),
                     data_dir=data_dir, admin=True, now=DAY3)
        with self.subTest(point="machine key gone in an elevated run"):
            self.assert_trace(self.trace(data_dir, CONTOSO_KEY, MACHINE_RUN_KEY),
                              day(DAY1), False, day(DAY3))


def rows_with(root, children):
    """The ``vendor_folders`` answer: ``children`` as the rows of ``root``, every other
    root of ``ROOTS`` read and empty."""
    return ok([root_row(r, children if r == root else ()) for r in ROOTS])


class TestVendorFolderNotListed(FootprintsTestCase):
    """A vendor folder is gone only when its root was read and listed completely and the
    folder is not among its children; a skipped row or a root no longer listed is not
    read."""

    def first_run(self):
        data_dir = self.data_dir()
        self.collect(machine(), data_dir=data_dir, now=DAY1)
        self.assert_trace(self.trace(data_dir, CONTOSO_KEY, CONTOSO_FOLDER_KEY),
                          day(DAY1), True, None)
        return data_dir

    def test_skipped_row_or_unlisted_root_keeps_folder(self):
        no_path = {"name": "Contoso", "reparse_point": False, "has_entries": True}
        cases = {
            "now a reparse point": (
                None, listing([folder(PROGRAM_FILES, "Contoso", reparse_point=True)])),
            "reparse_point not a boolean": (
                None, listing([dict(CONTOSO_FOLDER, reparse_point="no")])),
            "row without a path in its root": (
                None, rows_with(PROGRAM_FILES, [no_path])),
            "name now in windows_names": (
                data_file_text(windows_names=WINDOWS_NAMES + ["Contoso"]),
                listing([CONTOSO_FOLDER])),
            "root no longer in the data file": (
                data_file_text(roots=[r for r in ROOTS if r != PROGRAM_FILES]),
                listing([CONTOSO_FOLDER])),
        }
        for case, (data_text, answer) in cases.items():
            with self.subTest(case=case):
                data_dir = self.first_run()
                if data_text is not None:
                    self.data_file.write_text(data_text, encoding="utf-8")
                self.addCleanup(self.data_file.write_text, data_file_text(),
                                encoding="utf-8")
                self.collect(machine(vendor_folders=answer), data_dir=data_dir, now=DAY2)
                self.data_file.write_text(data_file_text(), encoding="utf-8")
                self.assert_trace(self.trace(data_dir, CONTOSO_KEY, CONTOSO_FOLDER_KEY),
                                  day(DAY1), True, None)

    def test_clean_listed_root_without_folder_marks_gone(self):
        odd = {"name": "Odd", "reparse_point": False, "has_entries": True}
        cases = {
            "root read, folder not there": listing([]),
            "a skipped row in another root": rows_with(PROGRAM_DATA, [odd]),
            "a reparse point beside it": listing(
                [folder(PROGRAM_FILES, "Northwind", reparse_point=True)]),
        }
        for case, answer in cases.items():
            with self.subTest(case=case):
                data_dir = self.first_run()
                self.collect(machine(vendor_folders=answer), data_dir=data_dir, now=DAY2)
                self.assert_trace(self.trace(data_dir, CONTOSO_KEY, CONTOSO_FOLDER_KEY),
                                  day(DAY1), False, day(DAY2))

    def test_clean_folder_still_listed_stays_present(self):
        data_dir = self.first_run()
        self.collect(machine(), data_dir=data_dir, now=DAY2)
        self.assert_trace(self.trace(data_dir, CONTOSO_KEY, CONTOSO_FOLDER_KEY),
                          day(DAY1), True, None)


class TestInventoryRun(FootprintsTestCase):
    def assert_other_results(self, data_dir, summary):
        self.assertEqual(self.source(summary, "win32_programs").get("status"), "read",
                         self.source(summary, "win32_programs"))
        self.assertTrue((Path(data_dir) / "state" / "ush-inventory.json").is_file())

    def test_unreadable_file_left_as_it_was(self):
        data_dir = self.data_dir()
        path = self.file_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"entries": [{"key": "win32:hklm64:ContosoApp"')
        before = path.read_bytes()

        code, stdout, stderr = self.run_main(data_dir, machine(), now=DAY1)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)

        self.assertEqual(path.read_bytes(), before)
        self.assertIn("footprint_counts", summary, sorted(summary))
        self.assertIsNone(summary["footprint_counts"], summary["footprint_counts"])
        notes = self.footprint_notes(summary)
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        reason = notes[0].get("reason")
        self.assertIsInstance(reason, str, notes[0])
        self.assertTrue(reason.strip(), notes[0])
        self.assert_other_results(data_dir, summary)

    def test_failed_save(self):
        data_dir = self.data_dir()
        original = self.inventory.baseline.save_json

        def failing_save(*args, **kwargs):
            names = [str(value) for value in (*args, *kwargs.values())
                     if isinstance(value, (str, Path))]
            if any("footprints" in name for name in names):
                return SAVE_REASON
            return original(*args, **kwargs)

        with mock.patch.object(self.inventory.baseline, "save_json", side_effect=failing_save):
            code, stdout, stderr = self.run_main(data_dir, machine(), now=DAY1)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)

        self.assertIn("footprint_counts", summary, sorted(summary))
        self.assertIsNone(summary["footprint_counts"], summary["footprint_counts"])
        notes = self.footprint_notes(summary)
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        self.assertIn(SAVE_REASON, json.dumps(notes[0]), notes[0])
        detail = self.detail(summary)
        self.assertIn("footprints", detail, sorted(detail))
        self.assertIsNone(detail["footprints"], detail["footprints"])
        self.assert_other_results(data_dir, summary)

    def test_failed_save_of_unchanged_run(self):
        data_dir = self.data_dir()
        code, stdout, stderr = self.run_main(data_dir, machine(), now=DAY1)
        self.assertEqual(code, 0, stderr[:300])
        self.assertIsNotNone(self.parse(stdout).get("footprint_counts"))
        original = self.inventory.baseline.save_json

        def failing_save(*args, **kwargs):
            names = [str(value) for value in (*args, *kwargs.values())
                     if isinstance(value, (str, Path))]
            if any("footprints" in name for name in names):
                return SAVE_REASON
            return original(*args, **kwargs)

        with mock.patch.object(self.inventory.baseline, "save_json", side_effect=failing_save):
            code, stdout, stderr = self.run_main(data_dir, machine(), now=DAY1)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)

        self.assertIsNone(summary["footprint_counts"], summary["footprint_counts"])
        notes = self.footprint_notes(summary)
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        self.assertIn("were not saved", json.dumps(notes[0]), notes[0])
        self.assertIn(SAVE_REASON, json.dumps(notes[0]), notes[0])
        self.assertIsNone(self.detail(summary)["footprints"])

    def test_saved_but_previous_copy_not_kept(self):
        data_dir = self.data_dir()
        original = self.inventory.baseline.save_json

        def rotation_fails(*args, **kwargs):
            reason = original(*args, **kwargs)
            names = [str(value) for value in (*args, *kwargs.values())
                     if isinstance(value, (str, Path))]
            if reason is None and any("footprints" in name for name in names):
                return ("the new footprints.json is saved, but footprints.previous.json "
                        "could not be replaced: access denied")
            return reason

        with mock.patch.object(self.inventory.baseline, "save_json",
                               side_effect=rotation_fails):
            code, stdout, stderr = self.run_main(data_dir, machine(), now=DAY1)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)

        self.assertIsNotNone(summary.get("footprint_counts"), sorted(summary))
        saved = json.loads(self.file_path(data_dir).read_text(encoding="utf-8"))
        self.assertEqual(summary["footprint_counts"]["programs"], len(saved["entries"]))
        notes = self.footprint_notes(summary)
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        self.assertIn("were saved", json.dumps(notes[0]), notes[0])
        self.assertNotIn("were not saved", json.dumps(notes[0]), notes[0])
        detail = self.detail(summary)
        self.assertIsNotNone(detail.get("footprints"), sorted(detail))
        self.assert_other_results(data_dir, summary)


if __name__ == "__main__":
    unittest.main()

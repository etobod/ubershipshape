"""Time links and the v2 footprints file (plan 074, milestone M1, criteria K1-K6, K9 and
K10; K7 and K8 are in ``test_footprint_links.py``).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``not_checked``, the
detail file, the injected ``now`` and ``admin``) is described in ``fakes.py``; the
footprints file and its helpers in ``test_footprints.py``; portable program rows in
``test_portable.py``; the budget helpers follow ``test_vendor_folders_budget.py``.

Interface under test (from the plan):

- ``state/footprints.json`` has ``schema_version`` 2 and a top-level ``last_run``
  (``{kind: {present: [keys], within: [prefixes] | null}}``) holding only the kinds read
  in full in that run. ``footprints.load`` reads a schema_version 1 file (no
  ``last_run``) as ``read``.
- A trace is linked ``linked_by: "time"`` to every program new in this run when the trace
  is new too, has no explicit link and no owner in the file. A program is new only when
  ``programs`` was read in full in the previous run, its key was not there and the
  previous file has no entry for it; a trace is new only when its kind was read in full
  in the previous run and its key was not there (under a previous root for vendor
  folders). The first run on a v1 file makes no time link.
- An explicit link for a key removes its time traces from every entry.
- ``footprint_counts`` gains ``time_links`` and ``time_links_present``; ``traces``,
  ``traces_present`` and ``gone_with_present_traces`` count explicit traces only.
- The summary has ``footprint_time_links``: one item per present time trace, ``{id:
  t<n>, program, name, kind, trace_name, first_seen}``; ``null`` when ``footprint_counts``
  is ``null``.
- ``footprint_time_links`` joins the cut lists with ``truncated_time_links``; it is cut
  from its end after ``additions`` and before ``autostart`` down to ``TIME_LINKS_MIN``
  (5).

Assumptions added by these tests beyond the plan text:

- ``name`` of a ``footprint_time_links`` item is the program's name (the report names
  "the program's ``name``", plan 074 M2); ``trace_name`` of a Run value is its value
  name, of a firewall rule its ``Name`` field, of a vendor folder its folder name.
- A Run value whose target lies in ``C:\\Program Files`` but in no program's
  ``install_location``, a firewall rule whose app lies there, and a vendor folder no
  program is installed in, have no explicit link (as on the clean data of
  ``test_footprint_links.py``).

PowerShell never starts; every value is invented (Contoso, Fabrikam, Northwind, Litware).
"""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from unittest import mock

from .fakes import (
    NOW,
    SYSTEM_DN,
    InventoryTestCase,
    failure,
    id_number,
    msix,
    ok,
    win32,
)
from .fakes_additions import builtin_rule, custom_rule, fw_value
from .fakes_autostart import (
    CLEAN_FILES,
    VENDOR,
    exec_action,
    facts,
    file_row,
    run_value,
    task,
)
from .fakes_vendor_folders import (
    PROGRAM_FILES,
    folder,
    folder_key,
    folder_path,
    listing,
)
from .test_footprints import (
    CONTOSO_FOLDER,
    CONTOSO_KEY,
    FILES,
    RULE_ONE_ROW,
    TRAY,
    FootprintsTestCase,
    contoso_app,
    fabrikam_notes,
    machine,
    rows_with,
)
from .test_portable import exists_row, portable_key, process

DAY1 = NOW
DAY2 = NOW + timedelta(days=3)
DAY3 = NOW + timedelta(days=7)


def day(moment):
    return moment.date().isoformat()


STUDIO_KEY = "win32:hklm64:FabrikamStudio"
DESK_KEY = "win32:hklm64:NorthwindDesk"
AGENT_PROGRAM_KEY = "win32:hklm64:FabrikamAgent"

AGENT_DIR = "C:\\Program Files\\Fabrikam\\Agent"
AGENT_TARGET = f"{AGENT_DIR}\\agent.exe"
AGENT_RUN = run_value("FabrikamAgent", f'"{AGENT_TARGET}" --background')
AGENT_RUN_KEY = "run:hkcu\\Run:FabrikamAgent"

SYNC_RULE = "{00000000-0000-0000-0000-0000000F7401}"
SYNC_RULE_ROW = fw_value(SYNC_RULE, custom_rule(
    "Fabrikam Sync", port="9443", app="C:\\Program Files\\Fabrikam\\Sync\\sync.exe"))

LITWARE_FOLDER = folder(PROGRAM_FILES, "Litware")
LITWARE_FOLDER_KEY = folder_key(folder_path(PROGRAM_FILES, "Litware"))

PORTABLE_FOLDER = "D:\\Tools\\Fab"
PORTABLE_KEY = portable_key(PORTABLE_FOLDER)
PORTABLE_EXE = f"{PORTABLE_FOLDER}\\fab.exe"


def fabrikam_studio():
    return win32("FabrikamStudio", "Fabrikam Studio", publisher="Fabrikam, Inc.",
                 install_location="C:\\Program Files\\Fabrikam\\Studio")


def northwind_desk():
    return win32("NorthwindDesk", "Northwind Desk", publisher="Northwind Traders Inc.",
                 install_location="C:\\Program Files\\Northwind\\Desk")


def fabrikam_agent():
    return win32("FabrikamAgent", "Fabrikam Agent", publisher="Fabrikam, Inc.",
                 install_location=AGENT_DIR)


def day_machine(programs=(), runs=(TRAY,), rules=(RULE_ONE_ROW,), folders=(CONTOSO_FOLDER,),
                **overrides):
    """``test_footprints.machine`` (Contoso App with its Run value, firewall rule and
    vendor folder, Fabrikam Notes) plus ``programs``; the agent's file fact is always
    there."""
    overrides.setdefault("file_facts", facts(*CLEAN_FILES, *FILES,
                                             file_row(AGENT_TARGET, signer=VENDOR)))
    return machine(programs=[contoso_app(), *programs], runs=runs, rules=rules,
                   folders=folders, **overrides)


def new_day_machine(**overrides):
    """Day 2 of the basic case: Fabrikam Studio and an unlinked Run value both appear."""
    return day_machine(programs=[fabrikam_studio()], runs=(TRAY, AGENT_RUN), **overrides)


class TimeLinksTestCase(FootprintsTestCase):
    def time_traces(self, data_dir):
        """``[(program key, trace)]`` for every trace ``linked_by: "time"``."""
        return [(key, trace) for key, entry in self.programs(data_dir).items()
                for trace in self.traces(entry).values()
                if trace.get("linked_by") == "time"]

    def holders(self, data_dir, trace_key):
        """``{program key: trace}`` of every entry holding ``trace_key``."""
        return {key: self.traces(entry)[trace_key]
                for key, entry in self.programs(data_dir).items()
                if trace_key in self.traces(entry)}

    def assert_no_time_link(self, data_dir):
        found = self.time_traces(data_dir)
        self.assertEqual(found, [], [(key, trace.get("key")) for key, trace in found])

    def time_links(self, summary):
        self.assertIn("footprint_time_links", summary, sorted(summary))
        items = summary["footprint_time_links"]
        self.assertIsInstance(items, list, items)
        return items


class TestVersionOne(TimeLinksTestCase):
    def test_v1_file_carried_without_time_links(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        data = self.saved(data_dir)
        self.assertEqual(data.get("schema_version"), 2, sorted(data))
        # The same file as schema_version 1 wrote it: no last_run.
        data["schema_version"] = 1
        data.pop("last_run", None)
        self.file_path(data_dir).write_text(json.dumps(data, indent=2), encoding="utf-8")
        before = {entry["key"]: entry for entry in data["entries"]}

        with self.subTest(point="v1 file loaded as read"):
            result = self.footprints.load(data_dir)
            self.assertEqual(result.get("status"), "read", result)
            self.assertIsNone(result.get("reason"), result)
            self.assertEqual(sorted(entry.get("key") for entry in result.get("entries")),
                             sorted(before), result)

        # The first v2 run: a program and an unlinked Run value both appear.
        self.collect(new_day_machine(), data_dir=data_dir, now=DAY2)
        saved = self.saved(data_dir)
        with self.subTest(point="written as schema_version 2"):
            self.assertEqual(saved.get("schema_version"), 2, sorted(saved))
            self.assertIsInstance(saved.get("last_run"), dict, sorted(saved))
        with self.subTest(point="every v1 entry carried"):
            after = self.programs(data_dir)
            for key, entry in before.items():
                self.assertIn(key, after, sorted(after))
                self.assert_dates(after[key], entry["first_seen"], entry["gone_since"])
                old = {trace["key"]: trace for trace in entry["traces"]}
                new = self.traces(after[key])
                self.assertEqual(set(new), set(old), key)
                for trace_key, trace in old.items():
                    self.assertEqual(new[trace_key].get("first_seen"),
                                     trace["first_seen"], trace_key)
                    self.assertEqual(new[trace_key].get("linked_by"),
                                     trace["linked_by"], trace_key)
        with self.subTest(point="no time trace"):
            self.assert_no_time_link(data_dir)


class TestNewTrace(TimeLinksTestCase):
    def test_new_trace_with_new_program_is_time_linked(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        self.collect(new_day_machine(), data_dir=data_dir, now=DAY2)

        holders = self.holders(data_dir, AGENT_RUN_KEY)
        self.assertEqual(set(holders), {STUDIO_KEY}, sorted(holders))
        trace = holders[STUDIO_KEY]
        self.assertEqual(trace.get("linked_by"), "time", trace)
        self.assert_trace(trace, day(DAY2), True, None)
        with self.subTest(point="one time trace under the new program"):
            found = [trace.get("key") for key, trace in self.time_traces(data_dir)
                     if key == STUDIO_KEY]
            self.assertEqual(found, [AGENT_RUN_KEY], found)
        with self.subTest(point="the program present before gets none"):
            self.assertNotIn(AGENT_RUN_KEY, self.traces(self.program(data_dir, CONTOSO_KEY)))


NO_PATH_ROW = {"name": "Odd", "reparse_point": False, "has_entries": True}


class TestSourceUnread(TimeLinksTestCase):
    def two_runs(self, first, second, admin=False):
        data_dir = self.data_dir()
        self.collect(first, data_dir=data_dir, admin=admin, now=DAY1)
        self.collect(second, data_dir=data_dir, now=DAY2)
        return data_dir

    def litware_machine(self):
        return day_machine(programs=[fabrikam_studio()],
                           folders=(CONTOSO_FOLDER, LITWARE_FOLDER))

    def test_source_unread_last_run_gives_no_time_link(self):
        # The same second runs after a first run read in full do give a time link: the
        # cases below differ only in the first run.
        with self.subTest(fixture="Run value after a full first run"):
            data_dir = self.two_runs(day_machine(), new_day_machine())
            self.assertEqual(set(self.holders(data_dir, AGENT_RUN_KEY)), {STUDIO_KEY})
        with self.subTest(fixture="vendor folder after a full first run"):
            data_dir = self.two_runs(day_machine(), self.litware_machine())
            holders = self.holders(data_dir, LITWARE_FOLDER_KEY)
            self.assertEqual(set(holders), {STUDIO_KEY}, sorted(holders))
            self.assertEqual(holders[STUDIO_KEY].get("linked_by"), "time")

        cases = {
            "run_keys not read in the first run": (
                day_machine(run_keys=failure("Invented registry error")),
                new_day_machine(), False),
            "a vendor root with a row not read in the first run": (
                day_machine(vendor_folders=rows_with(PROGRAM_FILES,
                                                     [CONTOSO_FOLDER, NO_PATH_ROW])),
                self.litware_machine(), False),
            "a vendor root not listed in the first run": (
                day_machine(vendor_folders=listing(
                    [], unreadable={PROGRAM_FILES: "Invented access denied"})),
                self.litware_machine(), False),
            "first run elevated: per-user Run values not read": (
                day_machine(), new_day_machine(), True),
        }
        for case, (first, second, admin) in cases.items():
            with self.subTest(case=case):
                data_dir = self.two_runs(first, second, admin=admin)
                self.assert_no_time_link(data_dir)


class TestNotNew(TimeLinksTestCase):
    def test_no_time_link_without_new_program_or_for_old_trace(self):
        with self.subTest(case="no new program"):
            data_dir = self.data_dir()
            self.collect(day_machine(), data_dir=data_dir, now=DAY1)
            self.collect(day_machine(runs=(TRAY, AGENT_RUN)), data_dir=data_dir, now=DAY2)
            self.assert_no_time_link(data_dir)

        with self.subTest(case="trace already present in the previous run"):
            data_dir = self.data_dir()
            self.collect(day_machine(runs=(TRAY, AGENT_RUN)), data_dir=data_dir, now=DAY1)
            self.collect(new_day_machine(), data_dir=data_dir, now=DAY2)
            self.assert_no_time_link(data_dir)

        with self.subTest(case="program back after gone_since"):
            data_dir = self.data_dir()
            self.collect(day_machine(programs=[northwind_desk()]), data_dir=data_dir,
                         now=DAY1)
            self.collect(day_machine(), data_dir=data_dir, now=DAY2)
            self.assert_dates(self.program(data_dir, DESK_KEY), day(DAY1), day(DAY2))
            self.collect(day_machine(programs=[northwind_desk()], runs=(TRAY, AGENT_RUN)),
                         data_dir=data_dir, now=DAY3)
            self.assert_no_time_link(data_dir)

        with self.subTest(case="portable program not running in the previous run"):
            data_dir = self.data_dir()
            self.collect(day_machine(process_paths=ok([process(PORTABLE_EXE)])),
                         data_dir=data_dir, now=DAY1)
            self.program(data_dir, PORTABLE_KEY)
            self.collect(day_machine(process_paths=ok([]),
                                     portable_exists=ok([exists_row(PORTABLE_EXE, True)])),
                         data_dir=data_dir, now=DAY2)
            self.collect(day_machine(process_paths=ok([process(PORTABLE_EXE)]),
                                     runs=(TRAY, AGENT_RUN)),
                         data_dir=data_dir, now=DAY3)
            self.assert_no_time_link(data_dir)


SYSTEM_PACKAGE = msix("Invented.SystemTool_0abc1def2ghj3", "Invented.SystemTool",
                      kind="System", publisher=SYSTEM_DN)
BUILTIN_RULE_ROW = fw_value("InventedBuiltin-7", builtin_rule(7))
UPDATE_TASK_TARGET = "C:\\Windows\\System32\\inventedupdate.exe"
UPDATE_TASK = task("InventedUpdateTask", [exec_action(UPDATE_TASK_TARGET)])
UPDATE_TASK_KEY = "task:\\Invented\\InventedUpdateTask"


class TestOwnItemsNotTimeLinked(TimeLinksTestCase):
    """Clean data (final review of plan 074): a Windows update adds its own package, rule
    and nothing else; none of it is ever time-linked."""

    def test_own_items_get_no_time_link(self):
        packages = [fabrikam_notes(), SYSTEM_PACKAGE]
        # Control: the same second run with a third-party Run value does link it, so the
        # cases below fail only because of the own items.
        with self.subTest(case="control: a third-party trace with a new program"):
            data_dir = self.data_dir()
            self.collect(day_machine(), data_dir=data_dir, now=DAY1)
            self.collect(new_day_machine(), data_dir=data_dir, now=DAY2)
            self.assertEqual(set(self.holders(data_dir, AGENT_RUN_KEY)), {STUDIO_KEY})

        with self.subTest(case="own rule with a new third-party program"):
            data_dir = self.data_dir()
            self.collect(day_machine(), data_dir=data_dir, now=DAY1)
            self.collect(day_machine(programs=[fabrikam_studio()],
                                     rules=(RULE_ONE_ROW, BUILTIN_RULE_ROW)),
                         data_dir=data_dir, now=DAY2)
            self.assert_no_time_link(data_dir)

        with self.subTest(case="own package with a new third-party trace"):
            data_dir = self.data_dir()
            self.collect(day_machine(), data_dir=data_dir, now=DAY1)
            self.collect(day_machine(packages=packages, runs=(TRAY, AGENT_RUN)),
                         data_dir=data_dir, now=DAY2)
            self.assert_no_time_link(data_dir)

        # An own task (a kind of ``own_kinds``, a Valid Microsoft-signed target) next to
        # a third-party Run value in the same run: only the Run value is linked.
        own_task_facts = facts(*CLEAN_FILES, *FILES, file_row(AGENT_TARGET, signer=VENDOR),
                               file_row(UPDATE_TASK_TARGET))
        with self.subTest(case="own task with a new third-party program"):
            data_dir = self.data_dir()
            self.collect(day_machine(), data_dir=data_dir, now=DAY1)
            self.collect(new_day_machine(tasks=(UPDATE_TASK,), file_facts=own_task_facts),
                         data_dir=data_dir, now=DAY2)
            self.assertEqual(self.holders(data_dir, UPDATE_TASK_KEY), {})
            self.assertEqual(set(self.holders(data_dir, AGENT_RUN_KEY)), {STUDIO_KEY})

        # File facts not read: whether the task is Windows' own is unknown, so it is not
        # linked; the Run value (no kind of ``own_kinds``) still is.
        with self.subTest(case="task of an own kind with its facts not read"):
            data_dir = self.data_dir()
            self.collect(day_machine(), data_dir=data_dir, now=DAY1)
            self.collect(new_day_machine(tasks=(UPDATE_TASK,),
                                         file_facts=failure("Invented file facts error")),
                         data_dir=data_dir, now=DAY2)
            self.assertEqual(self.holders(data_dir, UPDATE_TASK_KEY), {})
            self.assertEqual(set(self.holders(data_dir, AGENT_RUN_KEY)), {STUDIO_KEY})

        with self.subTest(case="own package with an own rule"):
            data_dir = self.data_dir()
            self.collect(day_machine(), data_dir=data_dir, now=DAY1)
            self.collect(day_machine(packages=packages,
                                     rules=(RULE_ONE_ROW, BUILTIN_RULE_ROW)),
                         data_dir=data_dir, now=DAY2)
            self.assert_no_time_link(data_dir)


class TestExplicitReplacesTime(TimeLinksTestCase):
    def test_explicit_link_replaces_time_links(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        self.collect(day_machine(programs=[fabrikam_studio(), northwind_desk()],
                                 runs=(TRAY, AGENT_RUN)),
                     data_dir=data_dir, now=DAY2)
        with self.subTest(day=2, point="time-linked under both new programs"):
            holders = self.holders(data_dir, AGENT_RUN_KEY)
            self.assertEqual(set(holders), {STUDIO_KEY, DESK_KEY}, sorted(holders))
            for key, trace in holders.items():
                self.assertEqual(trace.get("linked_by"), "time", key)

        # Day 3: the program installed in the Run value's folder links it by path.
        self.collect(day_machine(programs=[fabrikam_studio(), northwind_desk(),
                                           fabrikam_agent()],
                                 runs=(TRAY, AGENT_RUN)),
                     data_dir=data_dir, now=DAY3)
        holders = self.holders(data_dir, AGENT_RUN_KEY)
        self.assertEqual(set(holders), {AGENT_PROGRAM_KEY}, sorted(holders))
        self.assertEqual(holders[AGENT_PROGRAM_KEY].get("linked_by"), "path",
                         holders[AGENT_PROGRAM_KEY])
        self.assertNotIn(AGENT_RUN_KEY,
                         [trace.get("key") for _, trace in self.time_traces(data_dir)])


class TestCounts(TimeLinksTestCase):
    def test_counts_keep_time_links_apart(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        second = self.collect(new_day_machine(), data_dir=data_dir, now=DAY2)
        with self.subTest(day=2):
            counts = self.counts(second)
            # Contoso App's Run value, firewall rule and vendor folder.
            self.assertEqual(counts.get("traces"), 3, counts)
            self.assertEqual(counts.get("traces_present"), 3, counts)
            self.assertEqual(counts.get("time_links"), 1, counts)
            self.assertEqual(counts.get("time_links_present"), 1, counts)
            self.assertEqual(counts.get("gone_with_present_traces"), 0, counts)

        # Day 3: Fabrikam Studio is removed; its time-linked Run value is still there.
        third = self.collect(day_machine(runs=(TRAY, AGENT_RUN)), data_dir=data_dir,
                             now=DAY3)
        with self.subTest(day=3):
            self.assert_dates(self.program(data_dir, STUDIO_KEY), day(DAY2), day(DAY3))
            counts = self.counts(third)
            self.assertEqual(counts.get("programs_gone"), 1, counts)
            self.assertEqual(counts.get("gone_with_present_traces"), 0, counts)
            self.assertEqual(counts.get("traces"), 3, counts)
            self.assertEqual(counts.get("traces_present"), 3, counts)
            self.assertEqual(counts.get("time_links"), 1, counts)
            self.assertEqual(counts.get("time_links_present"), 1, counts)


class TestSummaryList(TimeLinksTestCase):
    def three_traces(self, runs):
        return day_machine(programs=[fabrikam_studio()], runs=runs,
                           rules=(RULE_ONE_ROW, SYNC_RULE_ROW),
                           folders=(CONTOSO_FOLDER, LITWARE_FOLDER))

    def test_summary_lists_time_links(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        second = self.collect(self.three_traces((TRAY, AGENT_RUN)), data_dir=data_dir,
                              now=DAY2)
        items = self.time_links(second)
        with self.subTest(day=2, point="one t item per time trace"):
            self.assertEqual(sorted(item.get("trace_name") for item in items),
                             sorted(["FabrikamAgent", "Fabrikam Sync", "Litware"]), items)
            numbers = [id_number(item.get("id"), "t") for item in items]
            self.assertEqual(len(set(numbers)), len(numbers), items)
            for item in items:
                self.assertEqual(item.get("program"), STUDIO_KEY, item)
                self.assertEqual(item.get("name"), "Fabrikam Studio", item)
                self.assertEqual(item.get("first_seen"), day(DAY2), item)
                self.assertIn("kind", item, item)
        with self.subTest(day=2, point="no path in trace_name"):
            for item in items:
                self.assertIsInstance(item.get("trace_name"), str, item)
                self.assertNotIn("\\", item["trace_name"], item)

        # Day 3: the Run value is gone; its time trace is no longer present.
        third = self.collect(self.three_traces((TRAY,)), data_dir=data_dir, now=DAY3)
        with self.subTest(day=3, point="present time traces only"):
            items = self.time_links(third)
            self.assertEqual(sorted(item.get("trace_name") for item in items),
                             sorted(["Fabrikam Sync", "Litware"]), items)
            for item in items:
                id_number(item.get("id"), "t")

        with self.subTest(point="null when footprints.json could not be read"):
            data_dir = self.data_dir()
            path = self.file_path(data_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"entries": [{"key": "win32:hklm64:ContosoApp"')
            summary = self.collect(self.three_traces((TRAY, AGENT_RUN)), data_dir=data_dir,
                                   now=DAY1)
            self.assertIsNone(summary.get("footprint_counts"), summary.get("footprint_counts"))
            self.assertIn("footprint_time_links", summary, sorted(summary))
            self.assertIsNone(summary["footprint_time_links"])


# --- the cut (follows test_vendor_folders_budget.py) ----------------------------------

LISTS = ("programs", "driver_packages", "drivers", "components", "additions",
         "autostart", "changes", "vendor_folders", "footprint_time_links")
COUNT_KEYS = {"programs": "truncated", "driver_packages": "truncated_driver_packages",
              "drivers": "truncated_drivers", "components": "truncated_components",
              "additions": "truncated_additions", "autostart": "truncated_autostart",
              "changes": "truncated_changes", "vendor_folders": "truncated_vendor_folders",
              "footprint_time_links": "truncated_time_links"}
LINKS = 40
ADDITIONS = 20
AUTOSTART = 40


def time_link_items(count):
    """``count`` invented time links, newest ``first_seen`` first."""
    return [{
        "id": f"t{i + 1}",
        "program": f"win32:hklm64:InventedTimeApp{i:03d}",
        "name": f"Invented Time App {i:03d}",
        "kind": "run_keys",
        "trace_name": f"Invented Time Agent {i:03d} " + "n" * 60,
        "first_seen": (NOW - timedelta(days=i)).date().isoformat(),
    } for i in range(count)]


def addition_items(count):
    return [{"id": f"x{i}", "kind": "firewall_rule",
             "name": f"Invented Firewall Rule {i:03d} " + "n" * 80} for i in range(count)]


def autostart_items(count):
    return [{"id": f"s{i}", "kind": "run",
             "name": f"Invented Autostart Entry {i:03d} " + "n" * 80} for i in range(count)]


def summary_of(lists):
    """An invented summary holding ``lists`` (name -> items), nothing cut."""
    summary = {"not_checked": [], "autostart_counts": None, "change_counts": None}
    for name in LISTS:
        summary[name] = lists.get(name, [])
        summary[COUNT_KEYS[name]] = 0
    return summary


def cut_state(summary, kept):
    state = json.loads(json.dumps(summary))
    for name, number in kept.items():
        state[name] = summary[name][:number]
        state[COUNT_KEYS[name]] = len(summary[name]) - number
    return state


class TestTimeLinksCut(InventoryTestCase):
    def size(self, summary):
        return len(self.inventory.dump(summary))

    def test_time_links_cut_with_count(self):
        inv = self.inventory
        self.assertEqual(inv.TIME_LINKS_MIN, 5)
        links, additions = time_link_items(LINKS), addition_items(ADDITIONS)
        autostart = autostart_items(AUTOSTART)
        summary = summary_of({"footprint_time_links": links, "additions": additions,
                              "autostart": autostart})
        end = {"additions": inv.ADDITIONS_MIN, "footprint_time_links": inv.TIME_LINKS_MIN}
        budget = self.size(cut_state(summary, end)) + 5
        one_more = dict(end, footprint_time_links=inv.TIME_LINKS_MIN + 1)
        self.assertGreater(self.size(cut_state(summary, one_more)), budget,
                           "fixture: one more time link would still fit")

        with mock.patch.object(inv, "SUMMARY_MAX_CHARS", budget):
            text = inv.fit_budget(summary)
        self.assertLessEqual(len(text), budget)

        self.assertEqual(summary["footprint_time_links"], links[:inv.TIME_LINKS_MIN])
        self.assertEqual(summary["truncated_time_links"], LINKS - inv.TIME_LINKS_MIN)
        self.assertEqual(summary["autostart"], autostart)
        self.assertEqual(summary["truncated_autostart"], 0)



# --- code review M1 round 1 ---------------------------------------------------------


class TestElevatedPassBetween(TimeLinksTestCase):
    def test_elevated_pass_between_normal_runs_keeps_time_links(self):
        # Normal run, the elevated pass of the same day, then a normal run with a new
        # program and a new per-user Run value: the elevated pass does not end the links.
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        self.collect(day_machine(), data_dir=data_dir, admin=True, now=DAY2)
        self.collect(new_day_machine(), data_dir=data_dir, now=DAY3)
        holders = self.holders(data_dir, AGENT_RUN_KEY)
        self.assertEqual(set(holders), {STUDIO_KEY}, sorted(holders))
        self.assertEqual(holders[STUDIO_KEY].get("linked_by"), "time")

    def test_elevated_first_run_still_gives_no_time_link(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, admin=True, now=DAY1)
        self.collect(new_day_machine(), data_dir=data_dir, now=DAY2)
        self.assert_no_time_link(data_dir)


class TestProgramSourceUnread(TimeLinksTestCase):
    def test_program_source_unread_between_normal_runs_gives_no_time_link(self):
        # A normal run whose win32 source failed carries no program list forward: the
        # next run cannot tell which programs are new, so it links nothing by time.
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        self.collect(day_machine(win32_programs=failure("Invented uninstall key error")),
                     data_dir=data_dir, now=DAY2)
        self.collect(new_day_machine(), data_dir=data_dir, now=DAY3)
        self.assert_no_time_link(data_dir)

    # loc-qa 074: the stuck M1 code-review item (no test of source_unread in an
    # elevated run). The elevated pass keeps a prefix-only kind from the previous
    # last_run; a whole program source not read must still drop ``programs``.
    def test_program_source_unread_in_elevated_pass_gives_no_time_link(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        self.collect(day_machine(win32_programs=failure("Invented uninstall key error")),
                     data_dir=data_dir, admin=True, now=DAY2)
        self.collect(new_day_machine(), data_dir=data_dir, now=DAY3)
        self.assert_no_time_link(data_dir)


class TestTimeLinkBlock(TimeLinksTestCase):
    def test_block_of_time_link_names_no_block(self):
        data_dir = self.data_dir()
        self.collect(day_machine(), data_dir=data_dir, now=DAY1)
        summary = self.collect(new_day_machine(), data_dir=data_dir, now=DAY2)
        item_id = self.time_links(summary)[0]["id"]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.inventory.main(["--data-dir", str(data_dir), "--block", item_id])
        # Only reasons, no command: the same exit code as every id without a block.
        self.assertEqual(code, 1, err.getvalue())
        self.assertIn(f"# {item_id}: no block:", out.getvalue())


if __name__ == "__main__":
    unittest.main()

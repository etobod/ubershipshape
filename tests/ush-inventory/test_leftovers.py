"""Leftovers per removed program (plan 007, milestone M1, criteria K1-K8; milestone M2,
criteria K1-K2: the registry keys, contract above ``TestLeftoverRegistryKeys``).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``not_checked``, item
``key``/``id``) is described in ``fakes.py``; autostart rows in ``fakes_autostart.py``;
firewall rows in ``fakes_additions.py`` and ``test_review_notes.py``. PowerShell never
starts; every baseline lives in a temporary directory; every value is invented.

Contract fixed here for M1 (the implementation follows it):

- New PowerShell job ``install_folders``. It is asked about the ``install_location`` of
  each removed program (how the folders are passed in is up to the implementation). It
  answers a list of rows, one per folder (a single object is read as a one-element list)::

      {
        "path": "C:\\Invented\\Widget",      # the folder as requested; rows match
                                             # requested folders case-insensitively,
                                             # extra rows are ignored
        "exists": true | false | null,       # null when it could not be read
        "status": "read" | "unreadable",
        "reason": null | "<why it could not be read>",
        "files": 12 | null,                  # file count, recursive; null if not read
                                             # or not there
        "bytes": 3456789 | null,             # total size in bytes
        "newest_write": "2026-09-15T08:30:00Z" | null,   # ISO 8601 UTC
        "extensions": [{"extension": ".dll", "files": 7}, ...] | null
                                             # the 10 most common, most files first
      }

  A folder that is not there is ``{exists: false, status: "read"}`` with null counts. A
  folder that cannot be read is ``{exists: null, status: "unreadable", reason: "..."}``.
- ``summary["leftovers"]`` is always a list (``[]`` when there is none), never cut; the
  detail file has the same section. Each leftover is::

      {
        "id": "l<n>",
        "program": {"name": ..., "publisher": ..., ...} | null,  # the removed program
        "folder": "<deepest folder>" | null,  # set when grouped by missing targets (K5)
        "parts": [part, ...]
      }

  (``name``/``publisher`` directly on the leftover are accepted as well.)
- A part for an autostart entry or firewall rule carries the item's ``key`` and ``id``
  (the same id as in ``autostart`` / ``additions``) and, when its target file is missing,
  ``reason`` ``"target file does not exist"``. The folder part is
  ``{kind: "folder", path, status, reason, files, bytes, newest_write, extensions}``
  copied from the ``install_folders`` row.
- State file ``<data dir>/state/inventory-removed.json``: the removed programs, each with
  ``name``, ``publisher``, ``install_location`` and the date (ISO 8601) it was first seen
  gone. A list of entries, or an object holding such a list, is accepted.
- K8: a firewall rule whose ``app_exists`` is null gets a ``not_checked`` entry that names
  the rule (its key, its name or its ``App`` value) with a non-empty ``reason``.
"""

import json
import unittest
from datetime import timedelta
from pathlib import Path

from .fakes import (
    NOW,
    FakePowerShell,
    InventoryTestCase,
    failure,
    id_number,
    load_script,
    ok,
    win32,
)
from .fakes_additions import custom_rule, firewall_result, fw_value
from .fakes_autostart import (
    VENDOR,
    com_action,
    exec_action,
    facts,
    file_row,
    run_value,
    service,
    task,
)

MISSING_REASON = "target file does not exist"

WIDGET_DIR = "C:\\Invented\\Widget"
WIDGET_NAME = "Invented Widget"
WIDGET_PUBLISHER = "Invented Widget Corp"
WIDGET_KEY_NAME = "InventedWidget"

DAY = timedelta(days=1)


# --- rows of the new install_folders job ---------------------------------------------

def folder_present(path, files, size, newest_write, extensions):
    """A folder that is still on disk and was read."""
    return {
        "path": path,
        "exists": True,
        "status": "read",
        "reason": None,
        "files": files,
        "bytes": size,
        "newest_write": newest_write,
        "extensions": [{"extension": ext, "files": count} for ext, count in extensions],
    }


def folder_absent(path):
    """A folder that is not on disk (read, nothing there)."""
    return {
        "path": path,
        "exists": False,
        "status": "read",
        "reason": None,
        "files": None,
        "bytes": None,
        "newest_write": None,
        "extensions": None,
    }


def folder_unreadable(path, reason):
    """A folder the job could not read."""
    return {
        "path": path,
        "exists": None,
        "status": "unreadable",
        "reason": reason,
        "files": None,
        "bytes": None,
        "newest_write": None,
        "extensions": None,
    }


# --- responses --------------------------------------------------------------------------

def widget_program(install_location=WIDGET_DIR):
    return win32(WIDGET_KEY_NAME, WIDGET_NAME, publisher=WIDGET_PUBLISHER,
                 install_location=install_location)


def machine(programs, services=(), tasks=(), runs=(), files=(), folders=None,
            firewall=None, firewall_apps=None, keys=None):
    """Responses for one invented machine; autostart sources not given are empty.
    ``keys``: rows of the ``leftover_keys`` job (plan 007 M2)."""
    responses = {
        "win32_programs": ok(list(programs)),
        "msix_programs": ok([]),
        "run_keys": ok(list(runs)),
        "startup_folders": ok([]),
        "startup_approved": ok([]),
        "scheduled_tasks": ok(list(tasks)),
        "services": ok(list(services)),
        "file_facts": facts(*files),
    }
    if folders is not None:
        responses["install_folders"] = ok(list(folders))
    if firewall is not None:
        responses["firewall_rules"] = ok(firewall)
    if firewall_apps is not None:
        responses["firewall_apps"] = ok(firewall_apps)
    if keys is not None:
        responses["leftover_keys"] = ok(list(keys))
    return responses


def task_key(name, path="\\Invented\\"):
    return f"task:{path}{name}"


def run_key(name, hive="hkcu", key="Run"):
    return f"run:{hive}\\{key}:{name}"


def firewall_key(store, name):
    return f"firewall:{store}:{name}"


def same_path(a, b):
    return str(a or "").rstrip("\\").lower() == str(b or "").rstrip("\\").lower()


def mentions(item, needles):
    """Whether the JSON text of ``item`` holds one of ``needles`` (JSON-escaped)."""
    text = json.dumps(item, ensure_ascii=False)
    return any(json.dumps(needle, ensure_ascii=False)[1:-1] in text for needle in needles)


class LeftoversTestCase(InventoryTestCase):
    def runs(self, data_dir, machines, start=NOW):
        """One run per responses dict, a day apart, on one data dir; the summaries."""
        return [self.collect(FakePowerShell(responses), data_dir=data_dir,
                             now=start + i * DAY)
                for i, responses in enumerate(machines)]

    def leftovers(self, data):
        items = data.get("leftovers")
        self.assertIsInstance(items, list, f"leftovers: {items!r}")
        for item in items:
            self.assertIsInstance(item, dict, item)
            id_number(item.get("id"), "l")
            self.assertIsInstance(item.get("parts"), list, item)
        return items

    def program_field(self, leftover, field):
        program = leftover.get("program")
        if isinstance(program, dict):
            return program.get(field)
        return leftover.get(field)

    def of_program(self, items, name):
        return [item for item in items if self.program_field(item, "name") == name]

    def parts(self, leftover):
        return [part for part in leftover.get("parts") if isinstance(part, dict)]

    def part_keys(self, leftover):
        return {part.get("key") for part in self.parts(leftover) if part.get("key")}

    def folder_parts(self, leftover):
        return [part for part in self.parts(leftover) if part.get("kind") == "folder"]

    def registry_parts(self, leftover):
        return [part for part in self.parts(leftover) if part.get("kind") == "registry_key"]

    def items_named(self, summary, what):
        """not_checked items whose ``what`` is exactly ``what`` (never a substring)."""
        return [item for item in self.not_checked(summary) if item.get("what") == what]

    def all_part_keys(self, items):
        keys = set()
        for item in items:
            keys |= self.part_keys(item)
        return keys

    def detail_ids(self, summary, section):
        items = self.detail(summary).get(section)
        self.assertIsInstance(items, list, f"detail {section}: {items!r}")
        return {item.get("key"): item.get("id") for item in items}

    def removed_state(self, data_dir):
        """Entries of ``state/inventory-removed.json`` (missing file: no entries)."""
        path = Path(data_dir) / "state" / "inventory-removed.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            lists = [value for value in data.values() if isinstance(value, list)]
            if lists:
                data = [entry for value in lists for entry in value]
            else:
                data = [value for value in data.values() if isinstance(value, dict)]
        self.assertIsInstance(data, list, data)
        return [entry for entry in data if isinstance(entry, dict)]

    def state_of(self, data_dir, name):
        entries = self.removed_state(data_dir) or []
        return [entry for entry in entries
                if entry.get("name") == name or entry.get("display_name") == name]


# --- the widget machine of K1 and K7 -------------------------------------------------------

WIDGET_SVC = "InventedWidgetSvc"
WIDGET_SVC_TARGET = "C:\\Invented\\Widget\\widgetsvc.exe"
WIDGET_TASK = "InventedWidgetUpdate"
WIDGET_TASK_TARGET = "C:\\Invented\\Widget\\update.exe"


def widget_service():
    return service(WIDGET_SVC, f"\"{WIDGET_SVC_TARGET}\" -service",
                   display_name="Invented Widget Service")


def widget_task():
    return task(WIDGET_TASK, [exec_action(WIDGET_TASK_TARGET, "/check")])


def widget_files(exists=True):
    return [file_row(WIDGET_SVC_TARGET, exists=exists, signer=VENDOR),
            file_row(WIDGET_TASK_TARGET, exists=exists, signer=VENDOR)]


WIDGET_FOLDER = folder_present(WIDGET_DIR, 12, 3456789, "2026-09-15T08:30:00Z",
                               [(".dll", 7), (".exe", 3), (".log", 2)])


class TestLeftovers(LeftoversTestCase):
    def test_removed_program_groups_its_leftovers(self):
        data_dir = self.data_dir()
        before = machine([widget_program()], services=[widget_service()],
                         tasks=[widget_task()], files=widget_files(),
                         folders=[WIDGET_FOLDER])
        after = machine([], services=[widget_service()], tasks=[widget_task()],
                        files=widget_files(), folders=[WIDGET_FOLDER])
        _, summary = self.runs(data_dir, [before, after])

        items = self.leftovers(summary)
        mine = self.of_program(items, WIDGET_NAME)
        self.assertEqual(len(mine), 1, items)
        leftover = mine[0]
        self.assertEqual(self.program_field(leftover, "publisher"), WIDGET_PUBLISHER, leftover)

        service_key = f"service:{WIDGET_SVC}"
        widget_task_key = task_key(WIDGET_TASK)
        with self.subTest(point="the service and the task are parts with their ids"):
            self.assertEqual(self.part_keys(leftover), {service_key, widget_task_key},
                             leftover)
            ids = self.detail_ids(summary, "autostart")
            for part in self.parts(leftover):
                if part.get("key") in (service_key, widget_task_key):
                    self.assertEqual(part.get("id"), ids.get(part.get("key")), part)
                    id_number(part.get("id"), "s")

        with self.subTest(point="the folder part with its size"):
            folders = self.folder_parts(leftover)
            self.assertEqual(len(folders), 1, leftover)
            folder = folders[0]
            self.assertTrue(same_path(folder.get("path"), WIDGET_DIR), folder)
            self.assertEqual(folder.get("status"), "read", folder)
            self.assertEqual(folder.get("files"), 12, folder)
            self.assertEqual(folder.get("bytes"), 3456789, folder)
            self.assertEqual(folder.get("newest_write"), "2026-09-15T08:30:00Z", folder)

        with self.subTest(point="the detail file holds the same leftover"):
            detail_mine = self.of_program(self.leftovers(self.detail(summary)), WIDGET_NAME)
            self.assertEqual([item.get("id") for item in detail_mine], [leftover.get("id")])

    def test_clean_data_no_leftover(self):
        gone_dir = "C:\\Invented\\Gone Tool"
        kept_dir = "C:\\Invented\\Kept"
        kept_svc_target = "C:\\Invented\\Kept\\keptsvc.exe"
        kept_helper = "C:\\Invented\\Kept\\helper.exe"
        gone = win32("InventedGoneTool", "Invented Gone Tool", install_location=gone_dir)
        kept = win32("InventedKept", "Invented Kept", install_location=kept_dir)
        services = [service("InventedKeptSvc", f"\"{kept_svc_target}\"")]
        # A still-installed program's Run value whose target is missing is not a leftover.
        runs = [run_value("InventedKeptHelper", f"\"{kept_helper}\" /tray")]
        files = [file_row(kept_svc_target, signer=VENDOR),
                 file_row(kept_helper, exists=False, signer=VENDOR)]
        folders = [folder_absent(gone_dir),
                   folder_present(kept_dir, 4, 20480, "2026-09-01T10:00:00Z",
                                  [(".exe", 2), (".dll", 2)])]

        data_dir = self.data_dir()
        first, second = self.runs(data_dir, [
            machine([gone, kept], services=services, runs=runs, files=files, folders=folders),
            machine([kept], services=services, runs=runs, files=files, folders=folders),
        ])
        for label, summary in (("first run", first), ("run after the removal", second)):
            with self.subTest(run=label):
                self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
                self.assertEqual(self.leftovers(self.detail(summary)), [])

    def test_similar_name_is_not_leftover(self):
        # Every entry is named like the removed program; no target lies under its folder
        # and every target exists.
        helper_target = "D:\\Other Vendor\\widgethelper.exe"
        tray_target = "C:\\Invented\\Widget Tools\\tray.exe"
        sibling_target = "C:\\Invented\\Widget2\\widget.exe"
        rule_app = "C:\\Invented\\WidgetServer\\server.exe"
        rule_name = "{00000000-0000-0000-0000-00000000A001}"
        services = [service("InventedWidgetHelper", f"\"{helper_target}\"",
                            display_name="Invented Widget Helper")]
        runs = [run_value("Invented Widget", f"\"{tray_target}\" /background")]
        tasks = [task("Invented Widget", [exec_action(sibling_target)])]
        files = [file_row(helper_target, signer=VENDOR), file_row(tray_target, signer=VENDOR),
                 file_row(sibling_target, signer=VENDOR)]
        firewall = firewall_result(local=[
            fw_value(rule_name, custom_rule(WIDGET_NAME, app=rule_app))])
        apps = [{"app": rule_app, "expanded": rule_app, "exists": True}]

        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [
            machine([widget_program()], services=services, runs=runs, tasks=tasks,
                    files=files, folders=[folder_absent(WIDGET_DIR)], firewall=firewall,
                    firewall_apps=apps),
            machine([], services=services, runs=runs, tasks=tasks, files=files,
                    folders=[folder_absent(WIDGET_DIR)], firewall=firewall,
                    firewall_apps=apps),
        ])
        items = self.leftovers(summary)
        self.assertEqual(items, [], items)
        for key in ("service:InventedWidgetHelper", run_key("Invented Widget"),
                    task_key("Invented Widget"), firewall_key("local", rule_name)):
            self.assertNotIn(key, self.all_part_keys(items))

    def test_unreadable_folder(self):
        locked_dir = "C:\\Invented\\Locked App"
        locked_target = "C:\\Invented\\Locked App\\lockedsvc.exe"
        reason = "Access to the path 'C:\\Invented\\Locked App' is denied."
        program = win32("InventedLockedApp", "Invented Locked App",
                        publisher="Invented Locked Corp", install_location=locked_dir)
        services = [service("InventedLockedSvc", f"\"{locked_target}\"")]
        files = [file_row(locked_target, signer=VENDOR)]
        folders = [folder_unreadable(locked_dir, reason)]

        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [
            machine([program], services=services, files=files, folders=folders),
            machine([], services=services, files=files, folders=folders),
        ])
        mine = self.of_program(self.leftovers(summary), "Invented Locked App")
        self.assertEqual(len(mine), 1, summary.get("leftovers"))
        self.assertIn("service:InventedLockedSvc", self.part_keys(mine[0]), mine[0])
        folders_found = self.folder_parts(mine[0])
        self.assertEqual(len(folders_found), 1, mine[0])
        folder = folders_found[0]
        self.assertTrue(same_path(folder.get("path"), locked_dir), folder)
        self.assertEqual(folder.get("status"), "unreadable", folder)
        self.assertIsInstance(folder.get("reason"), str, folder)
        self.assertTrue(folder["reason"].strip(), folder)
        # Unreadable is never reported as empty.
        self.assertIsNone(folder.get("files"), folder)
        self.assertIsNone(folder.get("bytes"), folder)

    def test_missing_targets_grouped_by_folder(self):
        orphan_dir = "C:\\Invented\\Orphan\\bin"
        gone_a = orphan_dir + "\\agent.exe"
        gone_b = orphan_dir + "\\updater.exe"
        present = orphan_dir + "\\present.exe"
        tasks = [task("InventedOrphanAgent", [exec_action(gone_a)]),
                 task("InventedOrphanUpdater", [exec_action(gone_b, "/silent")]),
                 task("InventedOrphanPresent", [exec_action(present)])]
        files = [file_row(gone_a, exists=False, signer=None),
                 file_row(gone_b, exists=False, signer=None),
                 file_row(present, signer=VENDOR)]
        responses = machine([win32("InventedOther", "Invented Other",
                                   install_location="C:\\Invented\\Other")],
                            tasks=tasks, files=files)

        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [responses, responses])
        items = self.leftovers(summary)
        grouped = [item for item in items if same_path(item.get("folder"), orphan_dir)]
        self.assertEqual(len(grouped), 1, items)
        leftover = grouped[0]
        self.assertFalse(leftover.get("program"), leftover)

        missing_keys = {task_key("InventedOrphanAgent"), task_key("InventedOrphanUpdater")}
        self.assertEqual(self.part_keys(leftover), missing_keys, leftover)
        ids = self.detail_ids(summary, "autostart")
        for part in self.parts(leftover):
            if part.get("key") in missing_keys:
                with self.subTest(part=part.get("key")):
                    self.assertEqual(part.get("reason"), MISSING_REASON, part)
                    self.assertEqual(part.get("id"), ids.get(part.get("key")), part)
        self.assertNotIn(task_key("InventedOrphanPresent"), self.all_part_keys(items))
        self.assertEqual(len(items), 1, items)

    def test_shared_folder_and_windows_not_leftover(self):
        with self.subTest(case="removed program's folder contains an installed program"):
            suite_dir = "C:\\Invented\\Suite"
            viewer_dir = "C:\\Invented\\Suite\\Viewer"
            viewer_target = viewer_dir + "\\viewersvc.exe"
            suite = win32("InventedSuite", "Invented Suite", install_location=suite_dir)
            viewer = win32("InventedViewer", "Invented Viewer", install_location=viewer_dir)
            services = [service("InventedViewerSvc", f"\"{viewer_target}\"")]
            files = [file_row(viewer_target, signer=VENDOR)]
            folders = [folder_present(suite_dir, 40, 9000000, "2026-09-18T07:00:00Z",
                                      [(".dll", 30), (".exe", 10)]),
                       folder_present(viewer_dir, 10, 2000000, "2026-09-18T07:00:00Z",
                                      [(".dll", 8), (".exe", 2)])]
            data_dir = self.data_dir()
            _, summary = self.runs(data_dir, [
                machine([suite, viewer], services=services, files=files, folders=folders),
                machine([viewer], services=services, files=files, folders=folders),
            ])
            items = self.leftovers(summary)
            self.assertEqual(items, [], items)

        with self.subTest(case="missing target under %SystemRoot%"):
            raw = "%SystemRoot%\\System32\\inventedgone.exe"
            expanded = "C:\\Windows\\System32\\inventedgone.exe"
            tasks = [task("InventedWindowsGone", [exec_action(raw)],
                          path="\\Microsoft\\Windows\\Invented\\")]
            files = [file_row(raw, expanded=expanded, exists=False, signer=None)]
            responses = machine([], tasks=tasks, files=files)
            data_dir = self.data_dir()
            first, second = self.runs(data_dir, [responses, responses])
            for label, summary in (("first run", first), ("second run", second)):
                with self.subTest(run=label):
                    items = self.leftovers(summary)
                    self.assertEqual(items, [], items)

    def test_leftover_survives_next_run(self):
        data_dir = self.data_dir()
        installed = machine([widget_program()], services=[widget_service()],
                            files=widget_files(), folders=[WIDGET_FOLDER])
        left_behind = machine([], services=[widget_service()], files=widget_files(),
                              folders=[WIDGET_FOLDER])
        cleaned = machine([], folders=[folder_absent(WIDGET_DIR)])
        removal_day = (NOW + DAY).date().isoformat()

        self.runs(data_dir, [installed])
        first_after = self.collect(FakePowerShell(left_behind), data_dir=data_dir,
                                   now=NOW + DAY)
        with self.subTest(run="first run after the removal"):
            self.assertEqual(len(self.of_program(self.leftovers(first_after), WIDGET_NAME)),
                             1, first_after.get("leftovers"))
            entries = self.state_of(data_dir, WIDGET_NAME)
            self.assertEqual(len(entries), 1, self.removed_state(data_dir))
            entry = entries[0]
            self.assertEqual(entry.get("publisher"), WIDGET_PUBLISHER, entry)
            self.assertTrue(same_path(entry.get("install_location"), WIDGET_DIR), entry)
            self.assertTrue(mentions(entry, [removal_day]), entry)

        second_after = self.collect(FakePowerShell(left_behind), data_dir=data_dir,
                                    now=NOW + 2 * DAY)
        with self.subTest(run="second run after the removal"):
            mine = self.of_program(self.leftovers(second_after), WIDGET_NAME)
            self.assertEqual(len(mine), 1, second_after.get("leftovers"))
            self.assertIn(f"service:{WIDGET_SVC}", self.part_keys(mine[0]), mine[0])
            folders = self.folder_parts(mine[0])
            self.assertEqual(len(folders), 1, mine[0])
            self.assertEqual(folders[0].get("files"), 12, folders[0])
            self.assertEqual(folders[0].get("bytes"), 3456789, folders[0])
            entries = self.state_of(data_dir, WIDGET_NAME)
            self.assertEqual(len(entries), 1, self.removed_state(data_dir))
            # The date it was first seen gone does not move.
            self.assertTrue(mentions(entries[0], [removal_day]), entries[0])

        gone = self.collect(FakePowerShell(cleaned), data_dir=data_dir, now=NOW + 3 * DAY)
        with self.subTest(run="folder and entries gone"):
            self.assertEqual(self.of_program(self.leftovers(gone), WIDGET_NAME), [],
                             gone.get("leftovers"))
            self.assertEqual(self.state_of(data_dir, WIDGET_NAME), [],
                             self.removed_state(data_dir))

    def test_null_app_exists_has_reason(self):
        clean_app = "C:\\Invented\\Clean Server\\server.exe"
        variable_app = "%INVENTEDVAR%\\Invented Tool\\tool.exe"
        denied_app = "C:\\Invented\\Denied Server\\denied.exe"
        names = {
            "clean": "{00000000-0000-0000-0000-00000000B001}",
            "system": "{00000000-0000-0000-0000-00000000B002}",
            "variable": "{00000000-0000-0000-0000-00000000B003}",
            "denied": "{00000000-0000-0000-0000-00000000B004}",
        }
        clean_rules = [
            fw_value(names["clean"], custom_rule("Invented Clean Server", app=clean_app)),
            fw_value(names["system"], custom_rule("Invented System Rule", app="System")),
        ]
        clean_apps = [{"app": clean_app, "expanded": clean_app, "exists": True}]
        null_rules = [
            # The variable could not be expanded: "%" is still in ``expanded``.
            fw_value(names["variable"], custom_rule("Invented Variable Tool",
                                                    app=variable_app)),
            # The check could not tell (access denied): ``exists`` is not a boolean.
            fw_value(names["denied"], custom_rule("Invented Denied Server", app=denied_app)),
        ]
        null_apps = [{"app": variable_app, "expanded": variable_app, "exists": False},
                     {"app": denied_app, "expanded": denied_app, "exists": None}]

        def rule_notes(summary, label, app, rule):
            # ``app`` None: the App value is too common a word to search for.
            key = firewall_key("local", names[label])
            needles = [key, rule] + ([app] if app else [])
            return [item for item in self.not_checked(summary) if mentions(item, needles)]

        clean_cases = (("clean", clean_app, "Invented Clean Server"),
                       ("system", None, "Invented System Rule"))

        with self.subTest(case="clean data gives no entry"):
            summary = self.collect(FakePowerShell(machine(
                [], firewall=firewall_result(local=clean_rules), firewall_apps=clean_apps)))
            for label, app, rule in clean_cases:
                self.assertEqual(rule_notes(summary, label, app, rule), [],
                                 summary.get("not_checked"))
            self.assertEqual(
                [item for item in self.not_checked(summary) if mentions(item, ["app_exists"])],
                [], summary.get("not_checked"))

        summary = self.collect(FakePowerShell(machine(
            [], firewall=firewall_result(local=clean_rules + null_rules),
            firewall_apps=clean_apps + null_apps)))
        additions = self.by_key([item for item in self.detail(summary).get("additions") or []
                                 if item.get("kind") == "firewall_rule"])
        for label, app, rule in (("variable", variable_app, "Invented Variable Tool"),
                                 ("denied", denied_app, "Invented Denied Server")):
            with self.subTest(case=label):
                item = additions.get(firewall_key("local", names[label]))
                self.assertIsNotNone(item, sorted(map(str, additions)))
                self.assertIn("app_exists", item, item)
                self.assertIsNone(item.get("app_exists"), item)
                notes = rule_notes(summary, label, app, rule)
                self.assertTrue(notes, summary.get("not_checked"))
                for note in notes:
                    self.assertIsInstance(note.get("reason"), str, note)
                    self.assertTrue(note["reason"].strip(), note)
        with self.subTest(case="the clean rules beside them give no entry"):
            for label, app, rule in clean_cases:
                self.assertEqual(rule_notes(summary, label, app, rule), [],
                                 summary.get("not_checked"))


# --- code review round 1 of plan 007 M1 -----------------------------------------------------

PROFILE = "C:\\Users\\InventedUser"


class TestLeftoversReview(LeftoversTestCase):
    def removed_with(self, location, data_dir=None, admin=False):
        """Widget at ``location`` with a service in it, then removed; the second summary."""
        target = location.rstrip("\\") + "\\inventedsvc.exe"
        services = [service("InventedLocSvc", f"\"{target}\"")]
        files = [file_row(target, signer=VENDOR)]
        folders = [folder_present(location, 3, 3000, "2026-09-10T10:00:00Z", [(".exe", 3)])]
        program = widget_program(install_location=location)
        data_dir = data_dir or self.data_dir()
        self.collect(FakePowerShell(machine([program], services=services, files=files,
                                            folders=folders)),
                     data_dir=data_dir, admin=admin)
        return self.collect(FakePowerShell(machine([], services=services, files=files,
                                                   folders=folders)),
                            data_dir=data_dir, admin=admin, now=NOW + DAY)

    def test_broad_or_windows_location_not_leftover(self):
        for location in ("C:\\Windows\\SystemApps\\Pkg_x", "C:\\Windows",
                         "C:\\ProgramData", "C:\\Program Files", "C:\\Program Files (x86)",
                         PROFILE, PROFILE + "\\AppData", PROFILE + "\\AppData\\Local",
                         PROFILE + "\\AppData\\Roaming", PROFILE + "\\AppData\\LocalLow"):
            with self.subTest(location=location):
                summary = self.removed_with(location)
                self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
        for location in (PROFILE + "\\Downloads", PROFILE + "\\Desktop", PROFILE + "\\Documents",
                         "C:\\Users\\Public", "C:\\Users\\Public\\Downloads",
                         "C:\\Users\\Public\\Desktop", "C:\\Users\\Public\\Documents",
                         PROFILE + "\\AppData\\Local\\Temp", PROFILE + "\\AppData\\Local\\Microsoft",
                         PROFILE + "\\AppData\\Roaming\\Microsoft",
                         "C:\\Program Files\\WindowsApps", "C:\\Users",
                         "C:\\Program Files\\Common Files",
                         "C:\\Program Files (x86)\\Common Files",
                         PROFILE + "\\AppData\\Local\\Programs"):
            with self.subTest(location=location):
                summary = self.removed_with(location)
                self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
        for location in (PROFILE + "\\AppData\\Local\\Invented Tool",
                         PROFILE + "\\Downloads\\ToolX",
                         "C:\\Program Files\\WindowsApps\\Pkg_x",
                         PROFILE + "\\AppData\\Local\\Programs\\Invented Tool"):
            with self.subTest(case="clean: a program folder inside a broad one is one",
                              location=location):
                summary = self.removed_with(location)
                mine = self.of_program(self.leftovers(summary), WIDGET_NAME)
                self.assertEqual(len(mine), 1, summary.get("leftovers"))
                self.assertEqual(self.part_keys(mine[0]), {"service:InventedLocSvc"}, mine[0])
                self.assertEqual(len(self.folder_parts(mine[0])), 1, mine[0])

    def test_shared_location_one_leftover(self):
        x64 = win32(WIDGET_KEY_NAME, WIDGET_NAME, publisher=WIDGET_PUBLISHER,
                    install_location=WIDGET_DIR + "\\")
        x86 = win32(WIDGET_KEY_NAME + "32", WIDGET_NAME + " (x86)",
                    publisher=WIDGET_PUBLISHER, hive="hklm32",
                    install_location=WIDGET_DIR.lower())
        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [
            machine([x64, x86], services=[widget_service()], files=widget_files(),
                    folders=[WIDGET_FOLDER]),
            machine([], services=[widget_service()], files=widget_files(),
                    folders=[WIDGET_FOLDER]),
        ])
        items = self.leftovers(summary)
        self.assertEqual(len(items), 1, items)
        leftover = items[0]
        self.assertEqual(len(self.folder_parts(leftover)), 1, leftover)
        self.assertEqual(self.part_keys(leftover), {f"service:{WIDGET_SVC}"}, leftover)
        self.assertTrue(mentions(leftover, [WIDGET_NAME]), leftover)
        self.assertTrue(mentions(leftover, [WIDGET_NAME + " (x86)"]), leftover)

    def test_elevated_part_kept_after_non_elevated_run(self):
        data_dir = self.data_dir()
        installed = machine([widget_program()], tasks=[widget_task()],
                            files=widget_files(), folders=[folder_absent(WIDGET_DIR)])
        left_behind = machine([], tasks=[widget_task()], files=widget_files(),
                              folders=[folder_absent(WIDGET_DIR)])
        # Without elevation the task is not visible and the folder is gone.
        unseen = machine([], folders=[folder_absent(WIDGET_DIR)])
        self.collect(FakePowerShell(installed), data_dir=data_dir, admin=True)
        removed = self.collect(FakePowerShell(left_behind), data_dir=data_dir, admin=True,
                               now=NOW + DAY)
        self.assertEqual(len(self.of_program(self.leftovers(removed), WIDGET_NAME)), 1,
                         removed.get("leftovers"))
        self.assertEqual(len(self.state_of(data_dir, WIDGET_NAME)), 1)

        later = self.collect(FakePowerShell(unseen), data_dir=data_dir, admin=False,
                             now=NOW + 2 * DAY)
        with self.subTest(run="non-elevated run keeps the program"):
            self.assertEqual(len(self.state_of(data_dir, WIDGET_NAME)), 1,
                             self.removed_state(data_dir))
            self.assertTrue([item for item in self.not_checked(later)
                             if mentions(item, [WIDGET_NAME])], later.get("not_checked"))
        with self.subTest(run="clean: an elevated run that reads everything drops it"):
            cleared = self.collect(FakePowerShell(unseen), data_dir=data_dir, admin=True,
                                   now=NOW + 3 * DAY)
            self.assertEqual(self.state_of(data_dir, WIDGET_NAME), [],
                             self.removed_state(data_dir))
            self.assertEqual(self.leftovers(cleared), [], cleared.get("leftovers"))

    def test_source_not_read_keeps_program(self):
        data_dir = self.data_dir()
        self.runs(data_dir, [
            machine([widget_program()], services=[widget_service()], files=widget_files(),
                    folders=[WIDGET_FOLDER]),
            machine([], services=[widget_service()], files=widget_files(),
                    folders=[WIDGET_FOLDER]),
        ])
        responses = machine([], folders=[folder_absent(WIDGET_DIR)])
        responses["services"] = failure("Invented failure: access is denied")
        self.collect(FakePowerShell(responses), data_dir=data_dir, now=NOW + 2 * DAY)
        self.assertEqual(len(self.state_of(data_dir, WIDGET_NAME)), 1,
                         self.removed_state(data_dir))

    def test_unexpanded_target_keeps_program(self):
        variable_app = "%ProgramFiles%\\Widget\\w.exe"
        rule_name = "{00000000-0000-0000-0000-00000000A0E1}"
        firewall = firewall_result(local=[
            fw_value(rule_name, custom_rule("Invented Variable Server", app=variable_app))])
        # The expanded value still holds the variable: the path stays unknown.
        apps = [{"app": variable_app, "expanded": variable_app, "exists": None}]

        def removed(with_rule):
            data_dir = self.data_dir()
            extra = {"firewall": firewall, "firewall_apps": apps} if with_rule else {}
            self.collect(FakePowerShell(machine(
                [widget_program()], folders=[folder_absent(WIDGET_DIR)], **extra)),
                data_dir=data_dir)
            summary = self.collect(FakePowerShell(machine(
                [], folders=[folder_absent(WIDGET_DIR)], **extra)),
                data_dir=data_dir, now=NOW + DAY)
            return data_dir, summary

        data_dir, summary = removed(with_rule=True)
        self.assertEqual(len(self.state_of(data_dir, WIDGET_NAME)), 1,
                         self.removed_state(data_dir))
        notes = [item for item in self.not_checked(summary)
                 if mentions(item, ["leftovers"]) and mentions(item, [WIDGET_NAME])]
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertTrue(mentions(notes[0], ["expand"]), notes[0])
        self.assertNotIn(firewall_key("local", rule_name),
                         self.all_part_keys(self.leftovers(summary)))
        with self.subTest(case="clean: without the rule the program is dropped"):
            data_dir, summary = removed(with_rule=False)
            self.assertEqual(self.state_of(data_dir, WIDGET_NAME), [],
                             self.removed_state(data_dir))
            self.assertEqual([item for item in self.not_checked(summary)
                              if mentions(item, ["leftovers"])
                              and mentions(item, [WIDGET_NAME])], [],
                             summary.get("not_checked"))

    def test_upgrade_with_new_key_not_removed(self):
        old = win32("InventedWidgetOld", WIDGET_NAME, publisher=WIDGET_PUBLISHER,
                    install_location=WIDGET_DIR)
        new = win32("InventedWidgetNew", WIDGET_NAME, version="2.0.0",
                    publisher=WIDGET_PUBLISHER)
        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [
            machine([old], services=[widget_service()], files=widget_files(),
                    folders=[WIDGET_FOLDER]),
            machine([new], services=[widget_service()], files=widget_files(),
                    folders=[WIDGET_FOLDER]),
        ])
        self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
        self.assertEqual(self.state_of(data_dir, WIDGET_NAME), [])
        with self.subTest(case="clean: another name does not stop the removal"):
            other = win32("InventedWidgetNew", WIDGET_NAME + " Pro", version="2.0.0",
                          publisher=WIDGET_PUBLISHER)
            data_dir = self.data_dir()
            _, summary = self.runs(data_dir, [
                machine([old], services=[widget_service()], files=widget_files(),
                        folders=[WIDGET_FOLDER]),
                machine([other], services=[widget_service()], files=widget_files(),
                        folders=[WIDGET_FOLDER]),
            ])
            self.assertEqual(len(self.of_program(self.leftovers(summary), WIDGET_NAME)), 1,
                             summary.get("leftovers"))


# --- plan 007 M2: registry keys of a removed program (criteria K1, K2) ---------------------
#
# Contract fixed here for M2 (the implementation follows it):
#
# - New PowerShell job ``leftover_keys``. It is asked, for each removed program with a
#   ``publisher`` and a display name, about ``HKLM\SOFTWARE\<publisher>\<name>``,
#   ``HKLM\SOFTWARE\WOW6432Node\<publisher>\<name>`` and ``HKCU\SOFTWARE\<publisher>\<name>``
#   (how the keys are passed in is up to the implementation). It answers a list of rows,
#   one per key (a single object is read as a one-element list)::
#
#       {
#         "path": "HKLM\\SOFTWARE\\Contoso\\Widget Pro",  # the key as requested, with an
#                                                        # "HKLM\" or "HKCU\" prefix; rows
#                                                        # match requested keys case-
#                                                        # insensitively, extra rows (keys
#                                                        # not requested) are ignored
#         "exists": true | false | null,     # null when it could not be read
#         "status": "read" | "unreadable",
#         "reason": null | "<why it could not be read>",
#         "values": 3 | null,                # value count of the key
#         "subkeys": 1 | null                # subkey count of the key
#       }
#
# - A key that exists becomes a part of the program's leftover (summary and detail file):
#   ``{kind: "registry_key", path, exists, status, reason, values, subkeys}`` with
#   ``path`` in the same ``HKLM\...`` / ``HKCU\...`` form. A key that is not there gives
#   no part. A program whose only remnant is such a key still gets a leftover.

CONTOSO_DIR = "C:\\Invented\\Contoso\\Widget Pro"
CONTOSO_NAME = "Widget Pro"
CONTOSO_PUBLISHER = "Contoso"

HKLM_KEY = "HKLM\\SOFTWARE\\Contoso\\Widget Pro"
WOW_KEY = "HKLM\\SOFTWARE\\WOW6432Node\\Contoso\\Widget Pro"
HKCU_KEY = "HKCU\\SOFTWARE\\Contoso\\Widget Pro"
SIMILAR_KEYS = ("HKLM\\SOFTWARE\\Contoso\\Widget", "HKCU\\SOFTWARE\\Contoso\\Widget",
                "HKLM\\SOFTWARE\\Contoso\\Widget Pro Beta")

CONTOSO_FOLDER = folder_present(CONTOSO_DIR, 5, 102400, "2026-09-12T09:00:00Z",
                                [(".exe", 2), (".dll", 3)])


def key_row(path, exists=True, values=0, subkeys=0):
    """One row of the ``leftover_keys`` job; a key that is not there has null counts."""
    return {
        "path": path,
        "exists": exists,
        "status": "read",
        "reason": None,
        "values": values if exists else None,
        "subkeys": subkeys if exists else None,
    }


def contoso_program():
    return win32("ContosoWidgetPro", CONTOSO_NAME, publisher=CONTOSO_PUBLISHER,
                 install_location=CONTOSO_DIR)


class TestLeftoverRegistryKeys(LeftoversTestCase):
    def registry_parts(self, leftover):
        return [part for part in self.parts(leftover) if part.get("kind") == "registry_key"]

    def removed_contoso(self, keys, folder):
        """Widget Pro installed, then removed; the summary of the run after the removal."""
        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [
            machine([contoso_program()], folders=[folder], keys=keys),
            machine([], folders=[folder], keys=keys),
        ])
        return summary

    def test_registry_key_exact(self):
        keys = [
            key_row(HKLM_KEY, values=3, subkeys=1),
            key_row(WOW_KEY, exists=False),
            # The registry is case-insensitive: the row matches the requested key.
            key_row("hkcu\\Software\\contoso\\WIDGET PRO", values=1, subkeys=0),
        ] + [key_row(path, values=2, subkeys=0) for path in SIMILAR_KEYS]
        summary = self.removed_contoso(keys, CONTOSO_FOLDER)

        for label, data in (("summary", summary), ("detail file", self.detail(summary))):
            with self.subTest(where=label):
                mine = self.of_program(self.leftovers(data), CONTOSO_NAME)
                self.assertEqual(len(mine), 1, data.get("leftovers"))
                parts = self.registry_parts(mine[0])
                paths = sorted(str(part.get("path")).lower() for part in parts)
                self.assertEqual(paths, sorted([HKLM_KEY.lower(), HKCU_KEY.lower()]),
                                 mine[0])
                hklm = next(part for part in parts if same_path(part.get("path"), HKLM_KEY))
                self.assertEqual(hklm.get("status"), "read", hklm)
                self.assertIs(hklm.get("exists"), True, hklm)
                self.assertEqual(hklm.get("values"), 3, hklm)
                self.assertEqual(hklm.get("subkeys"), 1, hklm)
                # A similar name is never a fact, wherever it would land.
                for path in SIMILAR_KEYS:
                    for item in self.leftovers(data):
                        self.assertFalse(
                            [part for part in self.registry_parts(item)
                             if same_path(part.get("path"), path)], item)

        with self.subTest(case="a key alone still gives the program a leftover"):
            summary = self.removed_contoso([key_row(HKLM_KEY, values=3, subkeys=1)],
                                           folder_absent(CONTOSO_DIR))
            mine = self.of_program(self.leftovers(summary), CONTOSO_NAME)
            self.assertEqual(len(mine), 1, summary.get("leftovers"))
            self.assertEqual([str(part.get("path")).lower()
                              for part in self.registry_parts(mine[0])],
                             [HKLM_KEY.lower()], mine[0])

    def test_registry_clean_data(self):
        absent = [key_row(path, exists=False) for path in (HKLM_KEY, WOW_KEY, HKCU_KEY)]

        with self.subTest(case="folder left, no matching key"):
            summary = self.removed_contoso(absent, CONTOSO_FOLDER)
            for label, data in (("summary", summary), ("detail file", self.detail(summary))):
                mine = self.of_program(self.leftovers(data), CONTOSO_NAME)
                self.assertEqual(len(mine), 1, f"{label}: {data.get('leftovers')}")
                self.assertEqual(self.registry_parts(mine[0]), [], mine[0])

        with self.subTest(case="nothing left, only similar keys exist"):
            similar = [key_row(path, values=2, subkeys=1) for path in SIMILAR_KEYS]
            summary = self.removed_contoso(absent + similar, folder_absent(CONTOSO_DIR))
            self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
            self.assertEqual(self.leftovers(self.detail(summary)), [])

        with self.subTest(case="a program still installed gives no registry part"):
            data_dir = self.data_dir()
            present = [key_row(HKLM_KEY, values=3, subkeys=1)]
            first, second = self.runs(data_dir, [
                machine([contoso_program()], folders=[CONTOSO_FOLDER], keys=present),
                machine([contoso_program()], folders=[CONTOSO_FOLDER], keys=present),
            ])
            for summary in (first, second):
                self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))


FOO_PUBLISHER = "Invented Pub"
FOO_KEYS = ("HKLM\\SOFTWARE\\Invented Pub\\Foo",
            "HKLM\\SOFTWARE\\WOW6432Node\\Invented Pub\\Foo",
            "HKCU\\SOFTWARE\\Invented Pub\\Foo")


def foo_program(name="Foo", key_name="InventedFoo"):
    """A program without an install_location: only its registry keys can be left."""
    return win32(key_name, name, publisher=FOO_PUBLISHER)


class TestLeftoverKeysReview(LeftoversTestCase):
    """Plan 007 M2, review round 1: findings #6 and #7."""

    def registry_paths(self, summary):
        return sorted(str(part.get("path")).lower()
                      for item in self.leftovers(summary)
                      for part in self.parts(item) if part.get("kind") == "registry_key")

    def test_key_of_installed_program_not_leftover(self):
        """#6: a key an installed program of the same publisher uses is no part."""
        present = [key_row(FOO_KEYS[0], values=4, subkeys=0),
                   key_row(FOO_KEYS[1], exists=False), key_row(FOO_KEYS[2], exists=False)]
        for installed, protected in (("Foo (64-bit)", True), ("Foo (x86)", True),
                                     ("Foo Pro", False)):
            with self.subTest(installed=installed):
                data_dir = self.data_dir()
                other = foo_program(installed, key_name="InventedFooOther")
                _, summary = self.runs(data_dir, [
                    machine([foo_program(), other], keys=present),
                    machine([other], keys=present),
                ])
                expected = [] if protected else [FOO_KEYS[0].lower()]
                self.assertEqual(self.registry_paths(summary), expected,
                                 summary.get("leftovers"))

    def test_elevated_hkcu_absence_keeps_program(self):
        """#7: an elevated run's HKCU may be another account's: absence there is not
        proof; a non-elevated run with the same rows drops the program."""
        absent = [key_row(path, exists=False) for path in FOO_KEYS]
        for admin, kept in ((True, True), (False, False)):
            with self.subTest(elevated=admin):
                data_dir = self.data_dir()
                self.collect(FakePowerShell(machine([foo_program()], keys=absent)),
                             data_dir=data_dir, admin=admin)
                summary = self.collect(FakePowerShell(machine([], keys=absent)),
                                       data_dir=data_dir, admin=admin, now=NOW + DAY)
                self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
                self.assertEqual(bool(self.state_of(data_dir, "Foo")), kept,
                                 self.removed_state(data_dir))
                notes = [item for item in self.not_checked(summary)
                         if "leftovers" in str(item.get("what")) and "Foo" in str(item)]
                if kept:
                    self.assertEqual(len(notes), 1, summary.get("not_checked"))
                    self.assertIn("hkcu", str(notes[0].get("reason")).lower(), notes[0])
                    self.assertIn("elevated", str(notes[0].get("reason")).lower(),
                                  notes[0])
                else:
                    self.assertEqual(notes, [], summary.get("not_checked"))

    def test_hkcu_absent_sequence_and_reset(self):
        """Review round 2 (#1, #10): a non-elevated run that read the HKCU key as absent
        lets a later elevated run drop the program; a non-elevated run that reads it
        present again resets the flag, so the elevated run keeps the program."""
        hklm_left = [key_row(FOO_KEYS[0], values=2, subkeys=0),
                     key_row(FOO_KEYS[1], exists=False), key_row(FOO_KEYS[2], exists=False)]
        hkcu_left = [key_row(FOO_KEYS[0], exists=False), key_row(FOO_KEYS[1], exists=False),
                     key_row(FOO_KEYS[2], values=1, subkeys=0)]
        absent = [key_row(path, exists=False) for path in FOO_KEYS]

        def run(data_dir, keys, admin, day, programs=()):
            return self.collect(FakePowerShell(machine(list(programs), keys=keys)),
                                data_dir=data_dir, admin=admin, now=NOW + day * DAY)

        def flag(data_dir):
            entries = self.state_of(data_dir, "Foo")
            self.assertEqual(len(entries), 1, self.removed_state(data_dir))
            return entries[0].get("hkcu_absent")

        with self.subTest(case="absent read without elevation, then an elevated run"):
            data_dir = self.data_dir()
            run(data_dir, hklm_left, False, 0, [foo_program()])
            run(data_dir, hklm_left, False, 1)
            self.assertIs(flag(data_dir), True)
            run(data_dir, absent, True, 2)
            self.assertEqual(self.state_of(data_dir, "Foo"), [],
                             self.removed_state(data_dir))

        with self.subTest(case="HKCU key read as present again resets the flag"):
            data_dir = self.data_dir()
            run(data_dir, hklm_left, False, 0, [foo_program()])
            run(data_dir, hklm_left, False, 1)
            self.assertIs(flag(data_dir), True)
            run(data_dir, hkcu_left, False, 2)
            self.assertIs(flag(data_dir), False)
            summary = run(data_dir, absent, True, 3)
            self.assertEqual(len(self.state_of(data_dir, "Foo")), 1,
                             summary.get("not_checked"))


# --- loc-qa 007: the M1 code-review finding left open (stuck gate) ----------------------

PATHLESS_TASK = "InventedComTask"
PATHLESS_CLSID = "{00000000-0000-0000-0000-00000000C0E1}"


def pathless_task():
    """A third-party task whose only action is a ComHandler with an unknown CLSID: its
    target holds no path at all (nothing to expand)."""
    return task(PATHLESS_TASK, [com_action(PATHLESS_CLSID, None)])


class TestLeftoversQa(LeftoversTestCase):
    def test_target_without_path_does_not_keep_program(self):
        """K7 with an unrelated entry whose target holds no path: once the folder and
        entries are gone the removed program drops out of the state file, and no
        not_checked line claims a path "could not be expanded"."""
        data_dir = self.data_dir()
        installed = machine([widget_program()], services=[widget_service()],
                            tasks=[pathless_task()], files=widget_files(),
                            folders=[WIDGET_FOLDER])
        left_behind = machine([], services=[widget_service()], tasks=[pathless_task()],
                              files=widget_files(), folders=[WIDGET_FOLDER])
        cleaned = machine([], tasks=[pathless_task()], folders=[folder_absent(WIDGET_DIR)])

        self.runs(data_dir, [installed, left_behind])
        self.assertEqual(len(self.state_of(data_dir, WIDGET_NAME)), 1,
                         self.removed_state(data_dir))
        gone = self.collect(FakePowerShell(cleaned), data_dir=data_dir, now=NOW + 2 * DAY)
        self.assertEqual(self.of_program(self.leftovers(gone), WIDGET_NAME), [],
                         gone.get("leftovers"))
        self.assertEqual([item for item in self.not_checked(gone)
                          if mentions(item, ["could not be expanded"])], [],
                         gone.get("not_checked"))
        self.assertEqual(self.state_of(data_dir, WIDGET_NAME), [],
                         self.removed_state(data_dir))


class TestLeftoversFinalReview(LeftoversTestCase):
    """Final review of plan 007: what is not looked at is named, and a target
    whose absence was not confirmed in this run never makes a leftover."""

    def notes(self, summary, needle):
        return [item for item in self.not_checked(summary) if needle in str(item.get("what"))]

    def test_before_first_baseline_is_named(self):
        summary = self.collect(FakePowerShell(machine([widget_program()])))
        notes = self.notes(summary, "before the first baseline")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertTrue(str(notes[0].get("reason") or "").strip(), notes[0])

    def test_program_with_nothing_to_look_up_is_named(self):
        bare = win32("InventedBare", "Invented Bare Tool", publisher=None)
        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [machine([bare]), machine([])])
        self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
        notes = [item for item in self.notes(summary, "leftovers")
                 if mentions(item, ["Invented Bare Tool"])]
        self.assertEqual(len(notes), 1, summary.get("not_checked"))

    def test_clean_program_with_folder_is_not_named(self):
        gone = win32("InventedGoneTool", "Invented Gone Tool",
                     install_location="C:\\Invented\\Gone Tool")
        folders = [folder_absent("C:\\Invented\\Gone Tool")]
        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [machine([gone], folders=folders),
                                          machine([], folders=folders)])
        self.assertEqual([item for item in self.notes(summary, "leftovers")
                          if mentions(item, ["Invented Gone Tool"])], [],
                         summary.get("not_checked"))

    def test_carried_missing_fact_is_not_leftover(self):
        orphan_dir = "C:\\Invented\\Orphan\\bin"
        gone = orphan_dir + "\\agent.exe"
        tasks = [task("InventedOrphanAgent", [exec_action(gone)])]
        read = machine([], tasks=tasks, files=[file_row(gone, exists=False, signer=None)])
        failed = dict(read, file_facts=failure("file_facts failed"))
        data_dir = self.data_dir()
        first, second = self.runs(data_dir, [read, failed])
        self.assertEqual(len([item for item in self.leftovers(first)
                              if same_path(item.get("folder"), orphan_dir)]), 1,
                         first.get("leftovers"))
        self.assertEqual(self.leftovers(second), [], second.get("leftovers"))

    def test_unread_source_missing_fact_is_not_leftover(self):
        orphan_dir = "C:\\Invented\\Orphan\\bin"
        gone = orphan_dir + "\\agent.exe"
        tasks = [task("InventedOrphanAgent", [exec_action(gone)])]
        read = machine([], tasks=tasks, files=[file_row(gone, exists=False, signer=None)])
        unread = machine([], tasks=[{"TaskPath": tasks[0]["TaskPath"],
                                     "TaskName": "InventedOrphanAgent",
                                     "Error": "access denied"}])
        data_dir = self.data_dir()
        first, second = self.runs(data_dir, [read, unread])
        self.assertEqual(len([item for item in self.leftovers(first)
                              if same_path(item.get("folder"), orphan_dir)]), 1,
                         first.get("leftovers"))
        self.assertEqual(self.leftovers(second), [], second.get("leftovers"))

    def test_unconfirmed_missing_file_is_named_not_leftover(self):
        orphan_dir = "C:\\Invented\\Locked\\bin"
        gone = orphan_dir + "\\agent.exe"
        share = "\\\\invented-share\\tools\\sync.exe"
        tasks = [task("InventedLockedAgent", [exec_action(gone)]),
                 task("InventedShareSync", [exec_action(share)])]
        rows = [dict(file_row(gone, exists=None, signer=None), ExistsReason="not_confirmed"),
                dict(file_row(share, exists=None, signer=None), ExistsReason="not_local")]
        summary = self.collect(FakePowerShell(machine([], tasks=tasks, files=rows)))
        self.assertEqual(self.leftovers(summary), [], summary.get("leftovers"))
        notes = self.notes(summary, "file_facts exists")
        self.assertEqual(len(notes), 2, summary.get("not_checked"))
        self.assertEqual(len([n for n in notes if mentions(n, [gone])]), 1, notes)
        self.assertEqual(len([n for n in notes if mentions(n, [share])]), 1, notes)

    def test_many_unconfirmed_files_are_capped(self):
        paths = [f"C:\\Invented\\Locked{n:02d}\\agent.exe" for n in range(30)]
        tasks = [task(f"InventedLocked{n:02d}", [exec_action(path)])
                 for n, path in enumerate(paths)]
        rows = [dict(file_row(path, exists=None, signer=None), ExistsReason="not_confirmed")
                for path in paths]
        summary = self.collect(FakePowerShell(machine([], tasks=tasks, files=rows)))
        notes = self.notes(summary, "file_facts exists")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        reason = str(notes[0].get("reason"))
        self.assertIn("30 target(s)", reason)
        self.assertIn("and 10 more", reason)
        self.assertEqual(len([p for p in paths if mentions(notes[0], [p])]), 20, reason)

    def test_many_failed_file_checks_are_capped(self):
        paths = [f"C:\\Invented\\Denied{n:02d}\\agent.exe" for n in range(30)]
        tasks = [task(f"InventedDenied{n:02d}", [exec_action(path)])
                 for n, path in enumerate(paths)]
        rows = [{"Kind": "file", "Path": path, "Error": "access denied"} for path in paths]
        summary = self.collect(FakePowerShell(machine([], tasks=tasks, files=rows)))
        named = [item for item in self.not_checked(summary)
                 if str(item.get("what")).startswith("file_facts ")
                 and item.get("what") not in ("file_facts more", "file_facts exists")]
        self.assertEqual(len(named), 20, summary.get("not_checked"))
        more = self.notes(summary, "file_facts more")
        self.assertEqual(len(more), 1, summary.get("not_checked"))
        self.assertIn("10 more", str(more[0].get("reason")))
        with self.subTest(point="every failed target keeps its reason in the detail file"):
            errors = {fact.get("path"): fact.get("check_error")
                      for entry in self.detail(summary).get("autostart") or []
                      for fact in entry.get("facts") or []}
            self.assertEqual(errors, {path: "access denied" for path in paths})

    def test_summary_fact_drops_check_error(self):
        """Plan 018 M3 K1: a target read in the first run and failing in the second keeps
        its ``check_error`` in the detail file, never in the summary's fact."""
        target = "C:\\Invented\\Checked\\agent.exe"
        error = "Invented failure: access to the file was denied"
        name = "InventedCheckedAgent"
        key = task_key(name)
        tasks = [task(name, [exec_action(target)])]
        read = machine([], tasks=tasks, files=[file_row(target, signer=VENDOR)])
        failed = machine([], tasks=tasks,
                         files=[{"Kind": "file", "Path": target, "Error": error}])
        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [read, failed])

        def fact_of(section, label):
            entries = [entry for entry in section or []
                       if isinstance(entry, dict) and entry.get("key") == key]
            self.assertEqual(len(entries), 1,
                             f"{label}: no single autostart entry {key}: {section!r}")
            found = [fact for fact in entries[0].get("facts") or []
                     if isinstance(fact, dict) and same_path(fact.get("path"), target)]
            self.assertEqual(len(found), 1,
                             f"{label}: no single fact for {target}: {entries[0]!r}")
            return found[0]

        detail_fact = fact_of(self.detail(summary).get("autostart"), "detail file")
        self.assertEqual(detail_fact.get("check_error"), error, detail_fact)
        summary_fact = fact_of(summary.get("autostart"), "summary")
        self.assertNotIn("check_error", summary_fact)

    def test_read_file_is_not_named_unknown(self):
        here = "C:\\Invented\\Here\\agent.exe"
        gone = "C:\\Invented\\Gone\\agent.exe"
        tasks = [task("InventedHere", [exec_action(here)]),
                 task("InventedGone", [exec_action(gone)])]
        rows = [file_row(here), file_row(gone, exists=False, signer=None)]
        summary = self.collect(FakePowerShell(machine([], tasks=tasks, files=rows)))
        self.assertEqual(self.notes(summary, "file_facts exists"), [],
                         summary.get("not_checked"))

    def test_file_facts_confirms_missing(self):
        body = load_script("ush-inventory", "inventory").FILE_FACTS_BODY
        self.assertIn("function Confirm-Missing", body)
        self.assertIn("function Test-LocalPath", body)
        loop = body[body.index("foreach ($p in $paths)"):]
        check = loop[loop.index("$exists = [System.IO.File]::Exists($expanded)"):]
        check = check[:check.index("$status = $null")]
        self.assertIn("$exists = $null", check)
        self.assertIn("Test-LocalPath $expanded", check)
        self.assertIn("Confirm-Missing $expanded", check)
        self.assertIn("ExistsReason", body)


# --- plan 018 M1: a failed install_folders or leftover_keys job is named ------------------

FOLDERS_STDERR = "Invented failure: the install_folders job could not start (code 1)."
KEYS_STDERR = "Invented failure: the leftover_keys job could not start (code 1)."
KEYS_NOT_READ_PREFIX = "the registry keys of removed programs were not read"


class TestLeftoverJobFailures(LeftoversTestCase):
    """Plan 018 M1: a job that fails is named in not_checked by its exact name, and a
    removed program is never taken as clean because a job could not be read."""

    def test_install_folders_job_fails(self):
        installed = machine([contoso_program()], folders=[CONTOSO_FOLDER])
        removed = machine([])
        removed["install_folders"] = failure(FOLDERS_STDERR)

        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [installed, removed])

        notes = self.items_named(summary, "install_folders")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        reason = notes[0].get("reason")
        self.assertIsInstance(reason, str, notes[0])
        self.assertIn(FOLDERS_STDERR, reason, notes[0])

        mine = self.of_program(self.leftovers(summary), CONTOSO_NAME)
        self.assertEqual(len(mine), 1, summary.get("leftovers"))
        folders = self.folder_parts(mine[0])
        self.assertEqual(len(folders), 1, mine[0])
        folder = folders[0]
        self.assertTrue(same_path(folder.get("path"), CONTOSO_DIR), folder)
        self.assertEqual(folder.get("status"), "unreadable", folder)
        # Never a folder that is not there: exists is null, not false.
        self.assertIn("exists", folder, folder)
        self.assertIsNone(folder.get("exists"), folder)
        for field in ("files", "bytes", "newest_write", "extensions"):
            self.assertIn(field, folder, folder)
            self.assertIsNone(folder.get(field), f"{field}: {folder}")
        self.assertEqual(folder.get("reason"), reason, folder)

    def test_leftover_keys_job_fails(self):
        installed = machine([contoso_program()], folders=[CONTOSO_FOLDER])
        # The folder is read as gone and no item part is left: the registry is the only
        # possible remnant.
        failed = machine([], folders=[folder_absent(CONTOSO_DIR)])
        failed["leftover_keys"] = failure(KEYS_STDERR)
        keys_read = machine([], folders=[folder_absent(CONTOSO_DIR)], keys=[
            key_row(HKLM_KEY, values=3, subkeys=1),
            key_row(WOW_KEY, exists=False),
            key_row(HKCU_KEY, exists=False),
        ])

        data_dir = self.data_dir()
        _, second, third = self.runs(data_dir, [installed, failed, keys_read])

        with self.subTest(run="leftover_keys job failed"):
            notes = self.items_named(second, "leftover_keys")
            self.assertEqual(len(notes), 1, second.get("not_checked"))
            self.assertTrue(str(notes[0].get("reason") or "").startswith(KEYS_NOT_READ_PREFIX),
                            notes[0])
            # The job's own error is part of the reason, not only the fixed prefix.
            self.assertIn(KEYS_STDERR, str(notes[0].get("reason")), notes[0])
            self.assertEqual(self.of_program(self.leftovers(second), CONTOSO_NAME), [],
                             second.get("leftovers"))

        with self.subTest(run="leftover_keys job works again"):
            mine = self.of_program(self.leftovers(third), CONTOSO_NAME)
            self.assertEqual(len(mine), 1, third.get("leftovers"))
            parts = self.registry_parts(mine[0])
            self.assertEqual([str(part.get("path")).lower() for part in parts],
                             [HKLM_KEY.lower()], mine[0])
            hklm = parts[0]
            self.assertEqual(hklm.get("status"), "read", hklm)
            self.assertIs(hklm.get("exists"), True, hklm)
            self.assertEqual(hklm.get("values"), 3, hklm)
            self.assertEqual(hklm.get("subkeys"), 1, hklm)

    def test_jobs_read_nothing_left(self):
        absent = [key_row(path, exists=False) for path in (HKLM_KEY, WOW_KEY, HKCU_KEY)]
        installed = machine([contoso_program()], folders=[CONTOSO_FOLDER], keys=absent)
        removed = machine([], folders=[folder_absent(CONTOSO_DIR)], keys=absent)
        later = machine([], folders=[folder_absent(CONTOSO_DIR)], keys=[
            key_row(HKLM_KEY, values=3, subkeys=1),
            key_row(WOW_KEY, exists=False),
            key_row(HKCU_KEY, exists=False),
        ])

        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [installed, removed])

        for what in ("install_folders", "leftover_keys"):
            with self.subTest(what=what):
                # Neither the job item nor a per-item note ("<job> <path>") on clean data.
                named = [item for item in self.not_checked(summary)
                         if item.get("what") == what
                         or str(item.get("what") or "").startswith(what + " ")]
                self.assertEqual(named, [], summary.get("not_checked"))
        self.assertEqual(self.of_program(self.leftovers(summary), CONTOSO_NAME), [],
                         summary.get("leftovers"))

        with self.subTest(point="the program is no longer kept"):
            self.assertEqual(self.state_of(data_dir, CONTOSO_NAME), [],
                             self.removed_state(data_dir))
            after = self.collect(FakePowerShell(later), data_dir=data_dir, now=NOW + 2 * DAY)
            self.assertEqual(self.of_program(self.leftovers(after), CONTOSO_NAME), [],
                             after.get("leftovers"))


# --- plan 018 M2: an unreadable leftover_keys row is an unreadable part with its reason ----

KEY_UNREADABLE_REASON = "Invented failure: access to the registry key is denied."
NO_KEY_REASON = "the leftover_keys job gave no reason"


def unreadable_key_row(path, reason=None, with_reason=True):
    """A ``leftover_keys`` row the job could not read; ``with_reason=False`` leaves the
    ``reason`` key out of the row."""
    row = {
        "path": path,
        "exists": None,
        "status": "unreadable",
        "values": None,
        "subkeys": None,
    }
    if with_reason:
        row["reason"] = reason
    return row


class TestLeftoverKeyUnreadable(LeftoversTestCase):
    """Plan 018 M2: an unreadable key row is a registry part with status unreadable and
    its reason, never a key that is not there."""

    def removed_with_hklm_row(self, hklm_row):
        """Widget Pro installed, then removed; the folder is read as gone, so the registry
        part is the only possible part. The summary of the run after the removal."""
        keys = [hklm_row, key_row(WOW_KEY, exists=False), key_row(HKCU_KEY, exists=False)]
        data_dir = self.data_dir()
        _, summary = self.runs(data_dir, [
            machine([contoso_program()], folders=[CONTOSO_FOLDER], keys=keys),
            machine([], folders=[folder_absent(CONTOSO_DIR)], keys=keys),
        ])
        return summary

    def unreadable_hklm_part(self, data, label):
        """The single registry part of Widget Pro's leftover, checked as unreadable HKLM."""
        mine = self.of_program(self.leftovers(data), CONTOSO_NAME)
        self.assertEqual(len(mine), 1, f"{label}: {data.get('leftovers')}")
        parts = self.registry_parts(mine[0])
        self.assertEqual(len(parts), 1, mine[0])
        part = parts[0]
        self.assertTrue(same_path(part.get("path"), HKLM_KEY), part)
        self.assertEqual(part.get("status"), "unreadable", part)
        # Never a key that is not there: exists is present and null, not false.
        self.assertIn("exists", part, part)
        self.assertIsNone(part.get("exists"), part)
        self.assertIn("values", part, part)
        self.assertIsNone(part.get("values"), part)
        self.assertIn("subkeys", part, part)
        self.assertIsNone(part.get("subkeys"), part)
        return part

    def test_unreadable_key_row(self):
        summary = self.removed_with_hklm_row(
            unreadable_key_row(HKLM_KEY, reason=KEY_UNREADABLE_REASON))

        for label, data in (("summary", summary), ("detail file", self.detail(summary))):
            with self.subTest(where=label):
                part = self.unreadable_hklm_part(data, label)
                self.assertEqual(part.get("reason"), KEY_UNREADABLE_REASON, part)

        with self.subTest(point="not_checked names the key"):
            notes = self.items_named(summary, f"leftover_keys {HKLM_KEY}")
            self.assertEqual(len(notes), 1, summary.get("not_checked"))
            self.assertIn(KEY_UNREADABLE_REASON, str(notes[0].get("reason")), notes[0])

    def test_unreadable_key_row_without_reason(self):
        rows = {
            "no reason key": unreadable_key_row(HKLM_KEY, with_reason=False),
            "reason null": unreadable_key_row(HKLM_KEY, reason=None),
            "reason empty": unreadable_key_row(HKLM_KEY, reason=""),
        }
        for shape, row in rows.items():
            summary = self.removed_with_hklm_row(row)
            for label, data in (("summary", summary), ("detail file", self.detail(summary))):
                with self.subTest(row=shape, where=label):
                    part = self.unreadable_hklm_part(data, label)
                    # Never null or empty: the fixed fallback reason.
                    self.assertEqual(part.get("reason"), NO_KEY_REASON, part)


if __name__ == "__main__":
    unittest.main()

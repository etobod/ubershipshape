"""``--compare-to`` of ush-inventory: a program taken from the history copy and a guessed
service key (plan 140, M2, K5-K8).

Interface under test (from the plan; the general one is in ``fakes.py`` and
``test_compare_to.py``):

- When the comparison takes at least one program item (``win32_programs`` or
  ``msix_programs``) from the reference because this run could not read it, the
  ``program`` of every autostart fact is not compared: no ``facts[<target>].program``
  change is reported. When nothing comes from the reference, a real ``program`` change is
  reported as before.
- A service whose ``Type`` could not be read is keyed by the latest baseline first, then
  by the reference (the history copy picked by ``--compare-to``), and only then by the
  instance suffix pattern (``_`` plus 5 hex digits -> the template key).

Assumptions added by this test beyond the plan text:

- A change object is ``{key, change, fields: {<field>: {before, after}}}``; the field of
  a fact's program is ``facts[<target as requested>].program`` and the program value is
  the program item key (``win32:<hive>:<KeyName>``), as in ``test_report_profile.py``.
- The detail file lists every change; the summary ``changes`` list is not cut with the
  few changes made here.
- A baseline file (latest or history copy) is ``{"sources": {<source>: {<key>: item}}}``,
  a run entry has ``facts`` (a list of objects with ``path`` and ``program``) and a
  service entry has ``user_service``, as ``test_compare_to.py`` reads them.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import json
import shutil
import unittest
from datetime import timedelta

from .fakes import NOW, FakePowerShell, InventoryTestCase, ok, win32
from .fakes_autostart import OWN_PROCESS, VENDOR, facts, file_row, run_value, service

FIRST = NOW - timedelta(days=10)
SECOND = NOW - timedelta(days=2)
THIRD = NOW

BASELINE_FILE = "ush-inventory.json"
FIRST_COPY = f"ush-inventory.{FIRST.date().isoformat()}.json"

PUBLISHER = "Example Tools Ltd"

# The program whose Uninstall subkey cannot be opened in the third run of K5.
TOOL_KEY_NAME = "ExampleTool"
TOOL_KEY = f"win32:hklm64:{TOOL_KEY_NAME}"
TOOL_DIR = "C:\\Program Files\\Example Tool"
# K6: the same subkey read, with a location that does not cover the Run target.
MOVED_DIR = "C:\\Program Files\\Example Tool 2"

# A second Win32 program, read in every run (so the run is not "nothing read").
HELPER_KEY_NAME = "ExampleHelper"
HELPER_DIR = "C:\\Program Files\\Example Helper"

RUN_NAME = "ExampleToolTray"
RUN_KEY = f"run:hkcu\\Run:{RUN_NAME}"
RUN_TARGET = "C:\\Program Files\\Example Tool\\tool.exe"
PROGRAM_FIELD = f"facts[{RUN_TARGET}].program"

# K7 and K8: a per-user-looking service name whose Type is not read in the third run.
SERVICE_NAME = "Tool_a1b2c"
SERVICE_FULL_KEY = f"service:{SERVICE_NAME}"
SERVICE_TEMPLATE_KEY = "service:Tool"
SERVICE_EXE = "C:\\Program Files\\Example Tool\\toolsvc.exe"


def tool_program(location=TOOL_DIR):
    return win32(TOOL_KEY_NAME, "Example Tool", publisher=PUBLISHER,
                 install_location=location)


def tool_denied():
    return {"Hive": "hklm64", "KeyName": TOOL_KEY_NAME,
            "Error": "Invented registry access denied"}


def tool_machine(tool_row, services=()):
    """The invented machine: two Win32 programs, one Run entry into the Example Tool
    directory, no MSIX package, and ``services``; every file fact is read."""
    return FakePowerShell({
        "win32_programs": ok([
            win32(HELPER_KEY_NAME, "Example Helper", publisher=PUBLISHER,
                  install_location=HELPER_DIR),
            tool_row,
        ]),
        "msix_programs": ok([]),
        "run_keys": ok([run_value(RUN_NAME, f'"{RUN_TARGET}"')]),
        "startup_folders": ok([]),
        "startup_approved": ok([]),
        "scheduled_tasks": ok([]),
        "services": ok(list(services)),
        "file_facts": facts(file_row(RUN_TARGET, signer=VENDOR),
                            file_row(SERVICE_EXE, signer=VENDOR)),
    })


def tool_service(type_):
    return service(SERVICE_NAME, f'"{SERVICE_EXE}"', type_=type_)


class TestCompareToGuess(InventoryTestCase):
    # --- helpers ------------------------------------------------------------------------

    def run_tool(self, data_dir, fake, now, extra=()):
        code, stdout, stderr = self.run_main(data_dir, fake, now=now, extra=extra)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def copy_of(self, data_dir, name):
        target = data_dir.parent / name
        shutil.copytree(data_dir, target)
        return target

    def break_latest(self, data_dir):
        (data_dir / "state" / BASELINE_FILE).write_text("{not json", encoding="utf-8")

    def saved_sources(self, path):
        self.assertTrue(path.is_file(), path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, path)
        sources = data.get("sources")
        self.assertIsInstance(sources, dict, data)
        return sources

    def history_sources(self, data_dir):
        return self.saved_sources(data_dir / "state" / "history" / FIRST_COPY)

    def all_changes(self, summary):
        changes = self.detail(summary).get("changes")
        self.assertIsInstance(changes, list, summary.get("detail_file"))
        return changes

    def assert_compared_with_history(self, summary, *sources):
        info = summary.get("baseline")
        self.assertIsInstance(info, dict, summary)
        self.assertEqual(info.get("status"), "compared", info)
        self.assertEqual(info.get("reference"), "7d", info)
        self.assertEqual(info.get("reference_file"), FIRST_COPY, info)
        for source in sources:
            self.assertEqual(self.comparison(summary).get(source), "compared", source)

    def program_history(self, label):
        """Two runs (10 and 2 days ago) on the machine with the Example Tool program read;
        return a copy of the data directory for the third run."""
        data_dir = self.data_dir()
        self.run_tool(data_dir, tool_machine(tool_program()), FIRST)
        self.run_tool(data_dir, tool_machine(tool_program()), SECOND)
        # The fixture really matches the Run target to the program in the history copy.
        entry = self.history_sources(data_dir).get("run_keys", {}).get(RUN_KEY)
        self.assertIsInstance(entry, dict, RUN_KEY)
        programs = [fact.get("program") for fact in entry.get("facts") or []
                    if fact.get("path") == RUN_TARGET]
        self.assertEqual(programs, [TOOL_KEY], entry)
        return self.copy_of(data_dir, label)

    def service_history(self, label, services):
        """Two runs (10 and 2 days ago) with ``services``; return a copy for the third."""
        data_dir = self.data_dir()
        self.run_tool(data_dir, tool_machine(tool_program(), services), FIRST)
        self.run_tool(data_dir, tool_machine(tool_program(), services), SECOND)
        return self.copy_of(data_dir, label)

    # --- K5 -----------------------------------------------------------------------------

    def test_program_from_history_not_changed(self):
        """Latest baseline damaged, the Example Tool subkey not read in this run: its item
        comes from the history copy, and the Run entry's program is no change."""
        directory = self.program_history("program-from-history")
        self.break_latest(directory)

        summary = self.run_tool(directory, tool_machine(tool_denied()), THIRD,
                                extra=["--compare-to", "7d"])

        self.assert_compared_with_history(summary, "win32_programs", "run_keys")
        program_changes = [change for change in self.all_changes(summary)
                           if change.get("key") == RUN_KEY
                           and PROGRAM_FIELD in (change.get("fields") or {})]
        self.assertEqual(program_changes, [])

    # --- K6 -----------------------------------------------------------------------------

    def test_real_program_change_reported(self):
        """Clean data: the subkey is read, its new location does not cover the Run target,
        nothing comes from the history copy, so the program change is reported."""
        for label, damaged in (("intact latest baseline", False),
                               ("damaged latest baseline", True)):
            with self.subTest(label):
                directory = self.program_history(
                    "real-change-" + ("damaged" if damaged else "intact"))
                if damaged:
                    self.break_latest(directory)

                summary = self.run_tool(directory, tool_machine(tool_program(MOVED_DIR)),
                                        THIRD, extra=["--compare-to", "7d"])

                self.assert_compared_with_history(summary, "win32_programs", "run_keys")
                matching = [change for change in self.changes(summary)
                            if change.get("key") == RUN_KEY]
                self.assertEqual(len(matching), 1, self.changes(summary))
                change = matching[0]
                self.assertEqual(change.get("change"), "changed", change)
                fields = change.get("fields") or {}
                self.assertEqual(fields.get(PROGRAM_FIELD),
                                 {"before": TOOL_KEY, "after": None}, change)

    # --- K7 -----------------------------------------------------------------------------

    def test_guessed_service_key_from_history(self):
        """Latest baseline damaged, Type not read: the history copy knows the full key,
        so the service is neither added under the template key nor removed."""
        directory = self.service_history("guess-from-history",
                                         [tool_service(OWN_PROCESS)])
        # The fixture really has the full key in the history copy, not a user service.
        known = self.history_sources(directory).get("services", {}).get(SERVICE_FULL_KEY)
        self.assertIsInstance(known, dict, SERVICE_FULL_KEY)
        self.assertIs(known.get("user_service"), False, known)
        self.break_latest(directory)

        summary = self.run_tool(directory,
                                tool_machine(tool_program(), [tool_service(None)]),
                                THIRD, extra=["--compare-to", "7d"])

        self.assert_compared_with_history(summary, "services")
        found = {(str(change.get("key")), change.get("change"))
                 for change in self.all_changes(summary)}
        self.assertNotIn((SERVICE_TEMPLATE_KEY, "added"), found)
        self.assertNotIn((SERVICE_FULL_KEY, "removed"), found)

    # --- K8 -----------------------------------------------------------------------------

    def test_unknown_service_guess_unchanged(self):
        """Clean data: neither the latest baseline nor the history copy knows the service,
        Type is not read: the suffix pattern keys it by its template, as today."""
        directory = self.service_history("guess-unknown", [])
        self.assertNotIn(SERVICE_FULL_KEY,
                         self.history_sources(directory).get("services", {}))
        self.assertNotIn(SERVICE_FULL_KEY,
                         self.saved_sources(directory / "state" / BASELINE_FILE)
                         .get("services", {}))

        summary = self.run_tool(directory,
                                tool_machine(tool_program(), [tool_service(None)]),
                                THIRD, extra=["--compare-to", "7d"])

        self.assert_compared_with_history(summary, "services")
        saved = self.saved_sources(directory / "state" / BASELINE_FILE).get("services", {})
        self.assertIn(SERVICE_TEMPLATE_KEY, saved, sorted(saved))
        self.assertNotIn(SERVICE_FULL_KEY, saved, sorted(saved))
        service_changes = sorted(
            (str(change.get("key")), str(change.get("change")))
            for change in self.all_changes(summary)
            if str(change.get("key")).startswith("service:"))
        self.assertEqual(service_changes, [(SERVICE_TEMPLATE_KEY, "added")])


if __name__ == "__main__":
    unittest.main()

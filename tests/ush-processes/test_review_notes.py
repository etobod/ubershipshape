"""Tests for plan 107, M1: the ``image_paths`` fallback path, memory percentages, the
network profile category and the documents that name the new fields.

Interface under test (from the plan, beyond ``fakes.py``):

- Job ``image_paths``: input file ``<work>/processes-<stamp>.image_paths.input.json``
  holding ``{ProcessId, CreationDate}`` pairs of processes with an empty
  ``ExecutablePath`` that are not file-less processes; rows ``{ProcessId, Path,
  CreationTime, Error}`` with the time in UTC. Its body (``BODIES["image_paths"]``) sets
  ``$env:TMP`` before ``Add-Type``.
- A row path is taken only when ``CreationTime`` is within one second of the WMI
  ``CreationDate``; then ``path_source`` is ``query_image``.
- Groups carry ``path_read`` (false only for a group without a read path) and ``name`` is
  the bare process name.
- ``memory.used_percent`` / ``memory.commit_used_percent``: ``used/total*100`` with one
  decimal, null when a component is missing.
- Job ``network_profiles``: rows ``{Category}``; the summary gets ``network_categories``,
  a count per category; ``{}`` for no profile, null for a failed job.

PowerShell never starts; every process, path, time and number is invented.
"""

import json
import re
import unittest
from pathlib import Path

from tests.skill_loader import REPO_ROOT

from .fakes import (
    FakePowerShell,
    ProcessesTestCase,
    failure,
    machine,
    memory_row,
    ok,
    proc,
    started,
)

FIREFOX = r"C:\Program Files\Mozilla Firefox\firefox.exe"
EDITOR = r"C:\Apps\Editor\editor.exe"

SKILL_DIR = REPO_ROOT / "skills" / "ush-processes"


def image_row(pid, path, created_minutes):
    """One successful ``image_paths`` row; the time has the WMI text shape (UTC)."""
    return {"ProcessId": pid, "Path": path, "CreationTime": started(created_minutes),
            "Error": None}


def image_error(pid, error="Invented: access is denied."):
    return {"ProcessId": pid, "Path": None, "CreationTime": None, "Error": error}


def input_pids(data):
    """Every ``ProcessId`` (or ``pid``) found anywhere in a parsed input file."""
    pids, stack = [], [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key in ("ProcessId", "pid"):
                if key in item:
                    pids.append(item[key])
                    break
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return sorted(pids)


class RecordingFake(FakePowerShell):
    """FakePowerShell that keeps the ``image_paths`` input file content at call time."""

    def __init__(self, responses=None):
        super().__init__(responses)
        self.image_inputs = []

    def __call__(self, job, script, out_path):
        if job == "image_paths":
            for path in sorted(Path(out_path).parent.glob("*image_paths*.input.json")):
                self.image_inputs.append(json.loads(path.read_text(encoding="utf-8-sig")))
        return super().__call__(job, script, out_path)

    def sent_pids(self):
        pids = []
        for data in self.image_inputs:
            pids.extend(input_pids(data))
        return sorted(pids)


class TestReviewNotes(ProcessesTestCase):
    def group_named(self, groups, name, path_read=None):
        """The one group with ``name`` (and ``path_read`` when given)."""
        matches = [
            g for g in groups
            if g.get("name") == name and (path_read is None or g.get("path_read") is path_read)
        ]
        self.assertEqual(
            len(matches), 1,
            f"group {name!r} path_read={path_read}: "
            f"{[(g.get('name'), g.get('path_read')) for g in groups]}",
        )
        return matches[0]

    def notes_text(self, summary, job):
        """``what`` and ``reason`` of every not_checked item naming ``job``."""
        return [
            f"{item.get('what')} {item.get('reason')}"
            for item in self.not_checked(summary)
            if job in str(item.get("what")) or job in str(item.get("reason"))
        ]

    def body(self, task):
        bodies = getattr(self.processes, "BODIES", None)
        self.assertIsInstance(bodies, dict, "processes.BODIES")
        self.assertIn(task, bodies, sorted(bodies))
        self.assertIsInstance(bodies[task], str)
        return bodies[task]

    # --- K1 ----------------------------------------------------------------------------

    def test_image_path_fallback(self):
        sandboxed = proc(300, "firefox.exe", path=None, created=10)

        with self.subTest("same creation time: path from the row"):
            fake = RecordingFake(machine([sandboxed]))
            fake.responses["image_paths"] = ok([image_row(300, FIREFOX, 10)])
            summary = self.collect(fake)
            self.assertIn("image_paths", fake.jobs())
            self.assertIn(300, fake.sent_pids())
            group = self.group_named(self.groups(summary), "firefox.exe")
            self.assertEqual(group.get("path"), FIREFOX, group)
            self.assertEqual(group.get("path_source"), "query_image", group)
            self.assertIs(group.get("path_read"), True, group)
            self.assertEqual(group.get("name"), "firefox.exe", group)

        with self.subTest("creation time one minute later: path not taken"):
            fake = RecordingFake(machine([sandboxed]))
            fake.responses["image_paths"] = ok([image_row(300, FIREFOX, 11)])
            summary = self.collect(fake)
            group = self.group_named(self.groups(summary), "firefox.exe")
            self.assertIs(group.get("path_read"), False, group)
            self.assertIsNone(group.get("path"), group)

        with self.subTest("bare name without a drive (no image file): path not taken"):
            vmmem = proc(320, "vmmem", path=None, created=10)
            fake = RecordingFake(machine([vmmem]))
            fake.responses["image_paths"] = ok([image_row(320, "vmmem", 10)])
            summary = self.collect(fake)
            group = self.group_named(self.groups(summary), "vmmem")
            self.assertIs(group.get("path_read"), False, group)
            self.assertIsNone(group.get("path"), group)

        with self.subTest("row with Error: path unread"):
            fake = RecordingFake(machine([sandboxed]))
            fake.responses["image_paths"] = ok([image_error(300)])
            summary = self.collect(fake)
            group = self.group_named(self.groups(summary), "firefox.exe")
            self.assertIs(group.get("path_read"), False, group)
            self.assert_unread(self.detail_processes(summary)[300], "path")

        with self.subTest("System (pid 4) is not sent; its group has path_kind none"):
            system = proc(4, "System", path=None, parent=0, created=0)
            fake = RecordingFake(machine([system, sandboxed]))
            fake.responses["image_paths"] = ok([image_row(300, FIREFOX, 10)])
            summary = self.collect(fake, admin=True)
            self.assertIn("image_paths", fake.jobs())
            self.assertNotIn(4, fake.sent_pids())
            group = self.group_named(self.groups(summary), "System")
            self.assertEqual(group.get("path_kind"), "none", group)
            self.assertIs(group.get("path_read"), True, group)

        with self.subTest("no process without a path: the job does not run"):
            rows = [
                proc(4, "System", path=None, parent=0, created=0),
                proc(120, "editor.exe", EDITOR, created=3),
                proc(130, "firefox.exe", FIREFOX, created=4),
            ]
            fake = RecordingFake(machine(rows))
            summary = self.collect(fake, admin=True)
            self.assertNotIn("image_paths", fake.jobs())
            self.assertEqual(self.notes_text(summary, "image_paths"), [],
                             self.not_checked(summary))

        with self.subTest("failed job: not_checked entry, WMI paths kept"):
            rows = [sandboxed, proc(120, "editor.exe", EDITOR, created=3)]
            fake = RecordingFake(machine(rows))
            fake.responses["image_paths"] = failure("Invented: Add-Type failed.")
            summary = self.collect(fake)
            self.assertIn("image_paths", fake.jobs())
            self.assertEqual(len(self.notes_text(summary, "image_paths")), 1,
                             self.not_checked(summary))
            editor = self.group_named(self.groups(summary), "editor.exe")
            self.assertEqual(editor.get("path"), EDITOR, editor)
            self.assertIs(editor.get("path_read"), True, editor)
            self.assertEqual(self.detail_processes(summary)[120].get("path"), EDITOR)
            firefox = self.group_named(self.groups(summary), "firefox.exe")
            self.assertIs(firefox.get("path_read"), False, firefox)

        with self.subTest("the job script sets $env:TMP before Add-Type"):
            body = self.body("image_paths")
            self.assertIn("$env:TMP", body)
            self.assertIn("Add-Type", body)
            self.assertLess(body.index("$env:TMP"), body.index("Add-Type"), body[:500])

        with self.subTest("empty result for two processes: not_checked with 2, WMI kept"):
            rows = [
                sandboxed,
                proc(310, "firefox.exe", path=None, parent=300, created=12),
                proc(120, "editor.exe", EDITOR, created=3),
            ]
            fake = RecordingFake(machine(rows))
            fake.responses["image_paths"] = ok([])
            summary = self.collect(fake)
            self.assertEqual(fake.sent_pids(), [300, 310])
            notes = self.notes_text(summary, "image_paths")
            self.assertEqual(len(notes), 1, self.not_checked(summary))
            self.assertRegex(notes[0], r"(?<!\d)2(?!\d)")
            editor = self.group_named(self.groups(summary), "editor.exe")
            self.assertEqual(editor.get("path"), EDITOR, editor)
            self.assertIs(editor.get("path_read"), True, editor)

    # --- K2 ----------------------------------------------------------------------------

    def test_memory_percent_and_network_category(self):
        rows = [proc(120, "editor.exe", EDITOR, created=3)]
        kb_per_gb = 1024 * 1024

        with self.subTest("63.1 GB total, 6.4 GB free: used_percent 89.9"):
            row = memory_row(total_kb=round(63.1 * kb_per_gb), free_kb=round(6.4 * kb_per_gb))
            summary = self.collect(FakePowerShell(machine(rows, memory=row)))
            memory = summary.get("memory")
            self.assertIsInstance(memory, dict, summary)
            self.assertEqual(memory.get("used_percent"), 89.9, memory)

        with self.subTest("no FreePhysicalMemory: used_percent null"):
            row = memory_row(total_kb=round(63.1 * kb_per_gb))
            del row["FreePhysicalMemory"]
            summary = self.collect(FakePowerShell(machine(rows, memory=row)))
            memory = summary.get("memory")
            self.assertIsInstance(memory, dict, summary)
            self.assertIn("used_percent", memory)
            self.assertIsNone(memory["used_percent"], memory)

        with self.subTest("Public, Public, Private: counts per category"):
            responses = machine(rows)
            responses["network_profiles"] = ok([
                {"Category": "Public"}, {"Category": "Public"}, {"Category": "Private"},
            ])
            fake = FakePowerShell(responses)
            summary = self.collect(fake)
            self.assertIn("network_profiles", fake.jobs())
            self.assertEqual(summary.get("network_categories"), {"Public": 2, "Private": 1})

        with self.subTest("the job script handles ObjectNotFound"):
            self.assertIn("ObjectNotFound", self.body("network_profiles"))

        with self.subTest("only the not-found query id is no profile, not a missing command"):
            self.assertIn("CmdletizationQuery_NotFound", self.body("network_profiles"))

        with self.subTest("empty result: {}"):
            responses = machine(rows)
            responses["network_profiles"] = ok([])
            summary = self.collect(FakePowerShell(responses))
            self.assertIn("network_categories", summary)
            self.assertEqual(summary["network_categories"], {})
            self.assertEqual(self.notes_text(summary, "network_profiles"), [],
                             self.not_checked(summary))

        with self.subTest("failed job: null and a not_checked entry"):
            responses = machine(rows)
            responses["network_profiles"] = failure("Invented: CIM provider unavailable.")
            summary = self.collect(FakePowerShell(responses))
            self.assertIn("network_categories", summary)
            self.assertIsNone(summary["network_categories"])
            self.assertEqual(len(self.notes_text(summary, "network_profiles")), 1,
                             self.not_checked(summary))

        with self.subTest("the job script reads only the category, as text"):
            body = self.body("network_profiles")
            self.assertIn("[string]$_.NetworkCategory", body)
            self.assertNotRegex(body, re.compile(r"\bName\b", re.IGNORECASE))
            self.assertNotIn("interfacealias", body.lower())
            self.assertNotIn("interfaceindex", body.lower())

    # --- K3 ----------------------------------------------------------------------------

    def test_docs_name_new_fields(self):
        report_format = SKILL_DIR / "references" / "report-format.md"
        contract = SKILL_DIR / "references" / "summary-contract.md"
        script = SKILL_DIR / "scripts" / "processes.py"

        text = report_format.read_text(encoding="utf-8")
        for needle in ("Dashboard", "used_percent", "commit_used_percent",
                       "network_categories", "path_read"):
            with self.subTest(report_format=needle):
                self.assertIn(needle, text)

        for path in (script, report_format, contract):
            with self.subTest(no_path_not_read=path.name):
                self.assertNotIn("path not read", path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()

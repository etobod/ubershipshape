"""Shared fakes for the ush-processes tests of milestone M1 (plan 051).

Interface under test (fixed before the code exists):

- The script is loaded with ``load_script("ush-processes", "processes")``.
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``; ``now`` is a
  tz-aware datetime; the tests always pass ``--data-dir <tmp dir>``. Injecting only one
  of ``run_ps`` / ``is_admin`` raises ``TypeError``; module-level ``default_run_ps`` and
  ``default_is_admin`` are used only when neither is injected.
- ``run_ps(job, script, out_path) -> (exit_code, stderr)``. ``FakePowerShell`` answers
  by job name and writes JSON to ``out_path`` as Windows PowerShell 5.1 does (UTF-8 with
  a BOM); a failed job writes no file and returns a non-zero code with stderr. A job it
  does not know answers ``[]``.
- Jobs and row shapes:
  - ``processes``: ``{ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine,
    SessionId, WorkingSetSize, PrivatePageCount, CreationDate}``, ``CreationDate`` an
    ISO 8601 UTC text or null.
  - ``perf``: ``{IDProcess, WorkingSetPrivate}`` (no ``_Total`` row).
  - ``owners``: ``{pid, return_value, domain, user}`` or ``{pid, error}``.
  - ``memory``: one row ``{TotalVisibleMemorySize, FreePhysicalMemory,
    TotalVirtualMemorySize, FreeVirtualMemory}`` in KB.
- Output: ``<data dir>/work/processes-<UTC stamp YYYYmmdd-HHMMSS>.summary.json`` and
  ``.detail.json``; the summary is also printed on stdout; nothing under
  ``<data dir>/state``.
- Summary: ``sources`` is a list of ``{name, status, reason}``; ``not_checked`` is a
  list of ``{what, reason}`` and an item about a job names the job in ``what``; groups
  have ids ``g1...``; every process and group item carries ``unread_fields`` (a list,
  possibly empty).
- Detail file: ``processes`` (every process item) and ``groups`` (every group, same ids
  as the summary); each detail group has ``processes``, its full process items (with
  ``command_line``).
- Group ``name``: the ``Name`` of the group's process with the lowest pid; a group whose
  processes have path null is named ``"<Name> (path not read)"`` with path null.
- ``--detail g1`` prints the detail group as JSON on stdout and exits 0; an unknown id
  exits 1.

Assumptions added by these tests beyond that interface:

- The ``memory`` job file is written as a one-element JSON list ``[row]``.
- Process items in the detail file carry ``pid`` as an int.

Every value here is invented; nothing comes from a machine.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
BOOT = datetime(2026, 9, 20, 8, 0, 0, tzinfo=timezone.utc)

MB = 1024 ** 2
GB = 1024 ** 3


def started(minutes):
    """CreationDate text as the job writes it: ``ToUniversalTime().ToString('o')``."""
    moment = BOOT + timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def ok(payload):
    """PowerShell wrote ``payload`` as JSON and exited 0."""
    return ("ok", payload)


def failure(stderr="Invented failure: access denied.", code=1):
    """PowerShell exited with ``code`` and wrote ``stderr``; no file is written."""
    return ("fail", code, stderr)


def proc(pid, name, path=None, parent=0, command_line=None, session=1,
         working_set=10 * MB, commit=None, created=None):
    """One ``Win32_Process`` row as the ``processes`` job returns it.

    ``path`` and ``command_line`` default to a path and command line derived from the
    name when ``path`` is given; pass ``""`` or ``None`` explicitly for unread fields.
    ``created`` is minutes after BOOT (``None`` gives a null CreationDate).
    """
    if command_line is None and path:
        command_line = f'"{path}" --invented-flag'
    return {
        "ProcessId": pid,
        "ParentProcessId": parent,
        "Name": name,
        "ExecutablePath": path,
        "CommandLine": command_line,
        "SessionId": session,
        "WorkingSetSize": working_set,
        "PrivatePageCount": commit if commit is not None else working_set,
        "CreationDate": started(created) if created is not None else None,
    }


def perf_row(pid, private_bytes):
    return {"IDProcess": pid, "WorkingSetPrivate": private_bytes}


def owner_row(pid, user="alice", domain="HOST", return_value=0):
    return {"pid": pid, "return_value": return_value, "domain": domain, "user": user}


def owner_error(pid, error="Invented: the process has exited."):
    return {"pid": pid, "error": error}


def memory_row(total_kb=16 * 1024 * 1024, free_kb=8 * 1024 * 1024,
               virtual_kb=20 * 1024 * 1024, free_virtual_kb=10 * 1024 * 1024):
    return {
        "TotalVisibleMemorySize": total_kb,
        "FreePhysicalMemory": free_kb,
        "TotalVirtualMemorySize": virtual_kb,
        "FreeVirtualMemory": free_virtual_kb,
    }


def machine(processes, private=None, owners=None, memory=None):
    """Responses for all four jobs from a list of ``proc`` rows.

    ``private`` maps pid -> WorkingSetPrivate; a pid missing from it has no perf row.
    Without ``private`` every process gets half its working set. ``owners`` defaults to
    ``HOST\\alice`` for every process.
    """
    if private is None:
        private = {row["ProcessId"]: row["WorkingSetSize"] // 2 for row in processes}
    if owners is None:
        owners = [owner_row(row["ProcessId"]) for row in processes]
    return {
        "processes": ok(list(processes)),
        "perf": ok([perf_row(pid, value) for pid, value in private.items()]),
        "owners": ok(list(owners)),
        "memory": ok([memory if memory is not None else memory_row()]),
    }


def default_processes():
    return [
        proc(500, "shell.exe", r"C:\Apps\Shell\shell.exe", created=1),
        proc(600, "notes.exe", r"C:\Apps\Notes\notes.exe", parent=500, created=5),
    ]


class FakePowerShell:
    """Stands in for run_ps. Jobs not listed answer ``ok([])``."""

    def __init__(self, responses=None):
        self.responses = machine(default_processes())
        self.responses.update(responses or {})
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        response = self.responses.get(job, ok([]))
        if response[0] == "ok":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Windows PowerShell 5.1 writes UTF-8 with a BOM.
            out_path.write_text(json.dumps(response[1]), encoding="utf-8-sig")
            return 0, ""
        _, code, stderr = response
        return code, stderr

    def jobs(self):
        return [call[0] for call in self.calls]


def machine_touched(*args, **kwargs):
    raise AssertionError("a real machine function was called")


class ProcessesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.processes = load_script("ush-processes", "processes")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def run_main(self, data_dir, fake, admin=False, now=NOW, extra=()):
        """Run main with both machine functions injected; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.processes.main(
                ["--data-dir", str(data_dir), *extra],
                run_ps=fake,
                is_admin=lambda: admin,
                now=now,
            )
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            return json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")

    def collect(self, fake, data_dir=None, admin=False, now=NOW):
        """Run a collection and return the parsed summary (exit code must be 0)."""
        code, stdout, stderr = self.run_main(
            data_dir or self.data_dir(), fake, admin=admin, now=now
        )
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def summary_text(self, summary):
        path = Path(summary.get("summary_file"))
        self.assertTrue(path.is_absolute(), path)
        return path.read_text(encoding="utf-8-sig")

    def detail(self, summary):
        path = Path(summary.get("detail_file"))
        self.assertTrue(path.is_absolute(), path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))
        return data

    def source(self, summary, name):
        sources = summary.get("sources")
        self.assertIsInstance(sources, list, summary)
        matches = [s for s in sources if s.get("name") == name]
        self.assertEqual(len(matches), 1, f"source {name}: {sources}")
        return matches[0]

    def not_checked(self, summary):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return items

    def notes_about(self, summary, job):
        return [item for item in self.not_checked(summary) if job in str(item.get("what"))]

    def groups(self, summary):
        groups = summary.get("groups")
        self.assertIsInstance(groups, list, summary)
        return groups

    def group_named(self, groups, name):
        matches = [g for g in groups if g.get("name") == name]
        self.assertEqual(len(matches), 1, f"group {name!r}: {[g.get('name') for g in groups]}")
        return matches[0]

    def detail_processes(self, summary):
        """Detail process items keyed by pid."""
        items = self.detail(summary).get("processes")
        self.assertIsInstance(items, list)
        result = PidMap()
        for item in items:
            self.assertNotIn(item.get("pid"), result, f"duplicate pid {item.get('pid')}")
            result[item.get("pid")] = item
        return result

    def assert_unread(self, item, field):
        self.assertIsNone(item.get(field), item)
        self.assertIn(field, item.get("unread_fields"), item)

    def assert_read(self, item, field, value):
        self.assertEqual(item.get(field), value, item)
        self.assertIsInstance(item.get("unread_fields"), list, item)
        self.assertNotIn(field, item["unread_fields"], item)


class PidMap(dict):
    """Detail process items by pid; a missing pid fails as an assertion, not a KeyError."""

    def __missing__(self, pid):
        raise AssertionError(f"no detail process item with pid {pid}: {sorted(self)}")


def find_key(data, key):
    """Return True when ``key`` is an object key anywhere in parsed JSON."""
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if key in item:
                return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False

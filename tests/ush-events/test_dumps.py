"""Behaviour tests for memory dumps: the inventory in skills/ush-events/scripts/dumpfiles.py,
its link to bugchecks in events.py, the copy script skills/ush-events/scripts/dumps.py and
d<n> ids in check_report.py.

Public interface under test:
- ``events.main(argv=None, run_ps=None, now=None, trend_file=None, read_dumps=None) -> int``;
  ``read_dumps()`` takes no arguments and returns the ``dumps`` object without ids or links.
- ``dumpfiles.crash_settings(read_value)`` and
  ``dumpfiles.inventory(settings, list_dir, stat, open_file)``; the inventory is the ``dumps``
  object (``status``, ``reason``, ``settings``, ``files``).
- ``dumps.main(argv=None, read_value=None, list_dir=None, stat=None, open_file=None,
  copy=None, remove=None, disk_usage=None, now=None) -> int``
- ``check_report.main(argv) -> int``

Assumed shapes of the injected machine functions (the natural stdlib ones):
- ``read_value(..., value_name)``: the last positional argument is the value name under
  ``HKLM\\SYSTEM\\CurrentControlSet\\Control\\CrashControl``; returns the plain value.
- ``list_dir(path)`` like ``os.listdir``; ``stat(path)`` like ``os.stat``;
  ``open_file(path, ...)`` like ``open(path, "rb")``; ``copy(src, dst)`` like
  ``shutil.copyfile``; ``remove(path)`` like ``os.remove``; ``disk_usage(path)`` like
  ``shutil.disk_usage`` (a tuple with ``free``).

Every file, event and registry value here is invented. Files live only in temporary
directories; the registry, C:\\Windows and PowerShell are never touched.
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)

WER_SYSTEM = "Microsoft-Windows-WER-SystemErrorReporting"
NO_MATCH_STDERR = (
    "Get-WinEvent : No events were found that match the specified selection criteria.\r\n"
    "    + FullyQualifiedErrorId : NoMatchingEventsFound,"
    "Microsoft.PowerShell.Commands.GetWinEventCommand\r\n"
)
DENIED_TEXT = "Invented access denied to the minidump folder"
LOCKED_TEXT = "Invented sharing violation on the dump file"

COPY_STATUSES = {"copied", "already_copied", "not_copied"}
MANIFEST_FIELDS = {"name", "source", "copy", "size", "sha256", "copied_at", "verified",
                   "source_deleted", "reason"}

Usage = namedtuple("Usage", "total used free")


def event(provider, event_id, level, log, record_id, time, properties=()):
    """One event in the Get-WinEvent projection."""
    return {"ProviderName": provider, "Id": event_id, "Level": level, "LogName": log,
            "RecordId": record_id, "TimeCreated": time, "Message": "Invented message.",
            "Properties": list(properties)}


def bugcheck(record_id, time, code, dump_path):
    """A WER 1001 bugcheck event; Properties[1] is the dump path Windows reports."""
    prop = f"{code} (0x0000000000000050, 0xffffc10bd6c1f040, 0x0000000000000000, 0x0)"
    return event(WER_SYSTEM, 1001, 2, "System", record_id, time,
                 properties=[prop, dump_path, "00000-00000"])


OLD_SYSTEM = event("Invented-Oldest", 1, 4, "System", 1, "2026-06-01T00:00:00.0000000+00:00")
OLD_APPLICATION = event("Invented-Oldest", 1, 4, "Application", 2,
                        "2026-06-01T00:00:00.0000000+00:00")
BOOT = event("EventLog", 6005, 4, "System", 12, "2026-09-19T09:00:00.0000000+00:00")


class FakePowerShell:
    """Stands in for run_ps; every log is readable so only dumps can add not_checked."""

    def __init__(self, responses=None):
        self.responses = {
            "oldest:System": [OLD_SYSTEM],
            "oldest:Application": [OLD_APPLICATION],
            "A:System": [event("Invented-Disk", 7, 2, "System", 10,
                               "2026-09-20T10:00:00.0000000+00:00")],
            "A:Application": [event("Invented-App", 1000, 2, "Application", 11,
                                    "2026-09-20T11:00:00.0000000+00:00")],
            "B:System": [BOOT],
            "R:metrics": [],
            "R:records": [],
        }
        self.responses.update(responses or {})
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append(job)
        response = self.responses.get(job)
        if response is None:
            return 1, NO_MATCH_STDERR
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(response), encoding="utf-8")
        return 0, ""


SETTINGS = {"crash_dump_enabled": 3, "minidump_dir": "C:\\Invented\\Minidump",
            "dump_file": "C:\\Invented\\MEMORY.DMP"}


def dump_entry(name, path, size, modified):
    """One inventory file, as read_dumps returns it (no id, no links)."""
    return {"name": name, "path": path, "size": size, "modified": modified, "readable": True}


def dumps_object(files, status="read"):
    return {"status": status, "reason": None, "settings": dict(SETTINGS), "files": files}


def norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def walk(value):
    """Every dict inside a parsed JSON value."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def copy_name(stem, ext, modified, data):
    return f"{stem}-{modified:%Y%m%d-%H%M%S}-{sha(data)[:12]}{ext}"


class EventsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def temp_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def collect(self, read_dumps, fake=None, data_dir=None):
        data_dir = data_dir or self.temp_root() / "ush-data"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.events.main(["--data-dir", str(data_dir)],
                                    run_ps=fake or FakePowerShell(), now=NOW,
                                    read_dumps=read_dumps)
        self.assertEqual(code, 0, out.getvalue()[:300])
        try:
            summary = json.loads(out.getvalue())
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {out.getvalue()[:300]!r}")
        self.assertIn("dumps", summary)
        self.assertIsInstance(summary["dumps"], dict, summary["dumps"])
        return summary

    def bugchecks(self, summary):
        return [a for a in summary["anomalies"] if a.get("kind") == "bugcheck"]

    def by_dump_path(self, summary, path):
        found = [a for a in self.bugchecks(summary) if a.get("dump_path") == path]
        self.assertEqual(len(found), 1, self.bugchecks(summary))
        return found[0]

    def file(self, summary, name):
        found = [f for f in summary["dumps"]["files"] if f.get("name") == name]
        self.assertEqual(len(found), 1, summary["dumps"]["files"])
        return found[0]


class FakeMachine:
    """Crash settings and dump files in a temporary directory, with recording fakes."""

    def __init__(self, root):
        self.minidump_dir = root / "machine" / "Minidump"
        self.minidump_dir.mkdir(parents=True)
        self.dump_file = root / "machine" / "MEMORY.DMP"
        self.data_dir = root / "ush-data"
        self.dumps_dir = self.data_dir / "dumps"
        self.locked = set()
        self.list_error = None
        self.corrupt_copy = False
        self.remove_error = None
        self.free = 1 << 40
        self.copy_calls = []
        self.remove_calls = []

    def write(self, path, data, modified):
        path.write_bytes(data)
        stamp = modified.timestamp()
        os.utime(path, (stamp, stamp))
        return path

    # The seven machine functions.

    def read_value(self, *args, **kwargs):
        name = args[-1] if args else list(kwargs.values())[-1]
        values = {"CrashDumpEnabled": 3, "MinidumpDir": str(self.minidump_dir),
                  "DumpFile": str(self.dump_file)}
        if name not in values:
            raise FileNotFoundError(2, "Invented missing value", name)
        return values[name]

    def list_dir(self, path):
        if self.list_error is not None:
            raise self.list_error
        return os.listdir(path)

    def stat(self, path):
        return os.stat(path)

    def open_file(self, path, *args, **kwargs):
        if norm(path) in self.locked:
            raise PermissionError(13, LOCKED_TEXT, str(path))
        return open(path, "rb")  # the caller closes it

    def copy(self, src, dst, *args, **kwargs):
        self.copy_calls.append((str(src), str(dst)))
        shutil.copyfile(src, dst)
        if self.corrupt_copy:
            data = bytearray(Path(dst).read_bytes())
            data[len(data) // 2] ^= 0xFF
            Path(dst).write_bytes(bytes(data))
        return dst

    def remove(self, path):
        self.remove_calls.append(str(path))
        if self.remove_error is not None:
            raise self.remove_error
        os.remove(path)

    def disk_usage(self, path):
        return Usage(1 << 41, 1 << 40, self.free)

    def functions(self):
        return {"read_value": self.read_value, "list_dir": self.list_dir, "stat": self.stat,
                "open_file": self.open_file, "copy": self.copy, "remove": self.remove,
                "disk_usage": self.disk_usage}

    # Views of the data directory.

    def manifest(self):
        return json.loads((self.dumps_dir / "manifest.json").read_text(encoding="utf-8-sig"))

    def copies(self):
        """Every file in dumps/ except the manifest (temporary leftovers included)."""
        if not self.dumps_dir.exists():
            return []
        return sorted(p.name for p in self.dumps_dir.iterdir() if p.name != "manifest.json")


class DumpsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dumps = load_script("ush-events", "dumps")

    def machine(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return FakeMachine(Path(tmp.name).resolve())

    def run_dumps(self, machine, *flags):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.dumps.main([*flags, "--data-dir", str(machine.data_dir)],
                                       **machine.functions(), now=NOW)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def results(self, stdout):
        """Per-file results: dicts in the stdout JSON whose status is a copy status."""
        try:
            data = json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")
        return [d for d in walk(data) if d.get("status") in COPY_STATUSES]

    def only_result(self, stdout):
        results = self.results(stdout)
        self.assertEqual(len(results), 1, stdout[:500])
        return results[0]


MINI_NAME = "Mini092026-01.dmp"
MINI_TIME = datetime(2026, 9, 20, 10, 5, 0, tzinfo=timezone.utc)
MINI_DATA = b"PAGEDU64" + bytes(range(256)) * 8


class TestInventory(EventsTestCase):
    def test_bugcheck_links_dump_by_path(self):
        linked = "C:\\WINDOWS\\Minidump\\x.dmp"
        missing = "C:\\WINDOWS\\Minidump\\y.dmp"
        fake = FakePowerShell({"B:System": [
            BOOT,
            bugcheck(20, "2026-09-20T10:00:00.0000000+00:00", "0x0000000a", linked),
            bugcheck(21, "2026-09-22T10:00:00.0000000+00:00", "0x00000050", missing),
        ]})
        files = [
            dump_entry("x.dmp", "C:\\Windows\\Minidump\\x.dmp", 262144,
                       "2026-09-20T10:05:00+00:00"),
            dump_entry("z.dmp", "C:\\Windows\\Minidump\\z.dmp", 262144,
                       "2026-09-24T10:05:00+00:00"),
        ]
        summary = self.collect(lambda: dumps_object(files), fake=fake)

        self.assertEqual([f.get("id") for f in summary["dumps"]["files"]], ["d1", "d2"])
        a1 = self.by_dump_path(summary, linked)
        self.assertEqual(a1["id"], "a1")
        self.assertEqual(a1["dump"], "d1")
        self.assertEqual(self.file(summary, "x.dmp")["bugcheck"], "a1")

        # A dump no bugcheck points at.
        self.assertIsNone(self.file(summary, "z.dmp")["bugcheck"])

        # A bugcheck whose file is gone keeps its path.
        a2 = self.by_dump_path(summary, missing)
        self.assertEqual(a2["id"], "a2")
        self.assertIsNone(a2["dump"])

    def test_shared_path_is_not_linked(self):
        memory = "C:\\Windows\\MEMORY.DMP"
        fake = FakePowerShell({"B:System": [
            BOOT,
            bugcheck(20, "2026-09-20T10:00:00.0000000+00:00", "0x0000000a", memory),
            bugcheck(21, "2026-09-22T10:00:00.0000000+00:00", "0x00000050", memory),
        ]})
        files = [dump_entry("MEMORY.DMP", memory, 1048576, "2026-09-22T10:10:00+00:00")]
        summary = self.collect(lambda: dumps_object(files), fake=fake)

        dump = self.file(summary, "MEMORY.DMP")
        self.assertEqual(dump["id"], "d1")
        self.assertIsNone(dump["bugcheck"])
        self.assertCountEqual(dump["bugcheck_candidates"], ["a1", "a2"])
        crashes = self.bugchecks(summary)
        self.assertEqual(len(crashes), 2, crashes)
        for crash in crashes:
            self.assertEqual(crash["dump_path"], memory, crash)
            self.assertIsNone(crash["dump"], crash)

    def test_empty_unreadable_and_locked_are_distinct(self):
        dumpfiles = load_script("ush-events", "dumpfiles")
        machine = FakeMachine(self.temp_root())

        def read_dumps():
            settings = dumpfiles.crash_settings(machine.read_value)
            return dumpfiles.inventory(settings, machine.list_dir, machine.stat,
                                       machine.open_file)

        # The folder does not exist yet: read, nothing there.
        machine.list_error = FileNotFoundError(2, "Invented missing folder",
                                               str(machine.minidump_dir))
        summary = self.collect(read_dumps)
        self.assertEqual(summary["dumps"]["status"], "empty", summary["dumps"])
        self.assertEqual(summary["dumps"]["files"], [])
        self.assertEqual(summary["not_checked"], [])

        # The folder cannot be listed: unreadable, and named in not_checked.
        machine.list_error = PermissionError(13, DENIED_TEXT, str(machine.minidump_dir))
        summary = self.collect(read_dumps)
        dumps = summary["dumps"]
        self.assertEqual(dumps["status"], "unreadable", dumps)
        self.assertIsInstance(dumps["reason"], str)
        self.assertIn(DENIED_TEXT, dumps["reason"])
        named = [item for item in summary["not_checked"]
                 if DENIED_TEXT in (item.get("reason") or "")]
        self.assertEqual(len(named), 1, summary["not_checked"])

        # A locked file is listed, but not readable, with a reason.
        machine.list_error = None
        machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        locked = machine.write(machine.minidump_dir / "Mini092126-01.dmp", MINI_DATA[::-1],
                               datetime(2026, 9, 21, 9, 0, 0, tzinfo=timezone.utc))
        machine.locked.add(norm(locked))
        summary = self.collect(read_dumps)
        locked_entry = self.file(summary, "Mini092126-01.dmp")
        self.assertIs(locked_entry["readable"], False, locked_entry)
        self.assertIsInstance(locked_entry.get("reason"), str, locked_entry)
        self.assertTrue(locked_entry["reason"].strip(), locked_entry)
        self.assertIs(self.file(summary, MINI_NAME)["readable"], True)


class TestCopy(DumpsTestCase):
    def test_copy_verifies_hash(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        expected = copy_name("Mini092026-01", ".dmp", MINI_TIME, MINI_DATA)

        code, out, err = self.run_dumps(machine, "--copy")

        self.assertEqual(code, 0, out[:300] + err[:300])
        self.assertEqual(machine.copies(), [expected])
        self.assertEqual((machine.dumps_dir / expected).read_bytes(), MINI_DATA)
        manifest = machine.manifest()
        self.assertIsInstance(manifest, list, manifest)
        self.assertEqual(len(manifest), 1, manifest)
        entry = manifest[0]
        self.assertLessEqual(MANIFEST_FIELDS, set(entry), entry)
        self.assertEqual(entry["name"], MINI_NAME)
        self.assertEqual(norm(entry["source"]), norm(source))
        self.assertEqual(Path(entry["copy"]).name, expected)
        self.assertEqual(entry["size"], len(MINI_DATA))
        self.assertEqual(entry["sha256"], sha(MINI_DATA))
        self.assertIs(entry["verified"], True)
        self.assertIs(entry["source_deleted"], False)
        # The source is untouched.
        self.assertEqual(source.read_bytes(), MINI_DATA)
        self.assertEqual(machine.remove_calls, [])

    def test_failed_copy_keeps_source(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        machine.corrupt_copy = True

        code, out, err = self.run_dumps(machine, "--copy", "--delete-source")

        self.assertEqual(code, 1, out[:300] + err[:300])
        manifest = machine.manifest()
        self.assertEqual(len(manifest), 1, manifest)
        self.assertIs(manifest[0]["verified"], False, manifest)
        self.assertIs(manifest[0]["source_deleted"], False, manifest)
        result = self.only_result(out)
        self.assertIs(result.get("source_kept"), True, result)
        self.assertTrue((result.get("reason") or "").strip(), result)
        self.assertEqual(source.read_bytes(), MINI_DATA)
        self.assertEqual(machine.remove_calls, [])

    def test_delete_only_after_verified_copy(self):
        # A verified copy: the source is removed.
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        code, out, err = self.run_dumps(machine, "--copy", "--delete-source")
        self.assertEqual(code, 0, out[:300] + err[:300])
        self.assertFalse(source.exists())
        self.assertEqual([norm(p) for p in machine.remove_calls], [norm(source)])
        entry = machine.manifest()[-1]
        self.assertIs(entry["verified"], True, entry)
        self.assertIs(entry["source_deleted"], True, entry)

        # Copied earlier, deleted in a second run that finds matching hashes.
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        code, out, err = self.run_dumps(machine, "--copy")
        self.assertEqual(code, 0, out[:300] + err[:300])
        self.assertTrue(source.exists())
        first = machine.manifest()
        self.assertEqual(len(first), 1, first)

        code, out, err = self.run_dumps(machine, "--copy", "--delete-source")
        self.assertEqual(code, 0, out[:300] + err[:300])
        self.assertEqual(self.only_result(out)["status"], "already_copied")
        self.assertFalse(source.exists())
        manifest = machine.manifest()
        self.assertEqual(len(manifest), 2, manifest)
        self.assertEqual(manifest[0], first[0])
        self.assertIs(manifest[-1]["verified"], True, manifest)
        self.assertIs(manifest[-1]["source_deleted"], True, manifest)
        expected = copy_name("Mini092026-01", ".dmp", MINI_TIME, MINI_DATA)
        self.assertEqual(machine.copies(), [expected])

        # The removal fails: the original stays, with a reason.
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        machine.remove_error = PermissionError(13, "Invented file in use", str(source))
        code, out, err = self.run_dumps(machine, "--copy", "--delete-source")
        self.assertEqual(code, 1, out[:300] + err[:300])
        self.assertEqual(source.read_bytes(), MINI_DATA)
        result = self.only_result(out)
        self.assertIs(result.get("source_kept"), True, result)
        self.assertTrue((result.get("reason") or "").strip(), result)
        self.assertIs(machine.manifest()[-1]["source_deleted"], False)

    def test_unreadable_source_not_copied(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        machine.locked.add(norm(source))

        code, out, err = self.run_dumps(machine, "--copy", "--delete-source")

        self.assertEqual(code, 1, out[:300] + err[:300])
        result = self.only_result(out)
        self.assertEqual(result["status"], "not_copied", result)
        self.assertIn("needs administrator", (result.get("reason") or "").lower(), result)
        self.assertEqual(machine.copies(), [])
        self.assertEqual(machine.copy_calls, [])
        self.assertEqual(machine.remove_calls, [])
        self.assertEqual(source.read_bytes(), MINI_DATA)

    def test_not_enough_space_not_copied(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        machine.free = len(MINI_DATA) - 1

        code, out, err = self.run_dumps(machine, "--copy")

        self.assertEqual(code, 1, out[:300] + err[:300])
        result = self.only_result(out)
        self.assertEqual(result["status"], "not_copied", result)
        self.assertTrue((result.get("reason") or "").strip(), result)
        self.assertEqual(machine.copy_calls, [])
        self.assertEqual(machine.copies(), [])
        self.assertEqual(source.read_bytes(), MINI_DATA)

    def test_archived_copy_never_overwritten(self):
        machine = self.machine()
        first_time = datetime(2026, 9, 20, 10, 5, 0, tzinfo=timezone.utc)
        second_time = datetime(2026, 9, 24, 18, 30, 15, tzinfo=timezone.utc)
        first_data = b"PAGEDU64" + b"invented first crash" * 64
        second_data = b"PAGEDU64" + b"invented second crash" * 64

        machine.write(machine.dump_file, first_data, first_time)
        code, out, err = self.run_dumps(machine, "--copy")
        self.assertEqual(code, 0, out[:300] + err[:300])
        first_copy = copy_name("MEMORY", ".DMP", first_time, first_data)

        machine.write(machine.dump_file, second_data, second_time)
        code, out, err = self.run_dumps(machine, "--copy")
        self.assertEqual(code, 0, out[:300] + err[:300])
        second_copy = copy_name("MEMORY", ".DMP", second_time, second_data)

        self.assertEqual({n.lower() for n in machine.copies()},
                         {first_copy.lower(), second_copy.lower()})
        self.assertEqual((machine.dumps_dir / first_copy).read_bytes(), first_data)
        self.assertEqual((machine.dumps_dir / second_copy).read_bytes(), second_data)

        # The target name is taken by a file with another hash: it is never overwritten.
        third_time = datetime(2026, 9, 26, 8, 0, 0, tzinfo=timezone.utc)
        third_data = b"PAGEDU64" + b"invented third crash" * 64
        machine.write(machine.dump_file, third_data, third_time)
        third_copy = copy_name("MEMORY", ".DMP", third_time, third_data)
        planted = b"invented unrelated content already archived"
        (machine.dumps_dir / third_copy).write_bytes(planted)

        code, out, err = self.run_dumps(machine, "--copy")
        self.assertEqual(code, 1, out[:300] + err[:300])
        result = self.only_result(out)
        self.assertEqual(result["status"], "not_copied", result)
        self.assertTrue((result.get("reason") or "").strip(), result)
        self.assertEqual((machine.dumps_dir / third_copy).read_bytes(), planted)
        self.assertEqual((machine.dumps_dir / first_copy).read_bytes(), first_data)
        self.assertEqual({n.lower() for n in machine.copies()},
                         {first_copy.lower(), second_copy.lower(), third_copy.lower()})

    def test_corrupt_manifest_aborts(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)
        machine.dumps_dir.mkdir(parents=True)
        broken = b'[{"name": "invented-broken.dmp", "sha256": '
        (machine.dumps_dir / "manifest.json").write_bytes(broken)

        code, out, err = self.run_dumps(machine, "--copy")

        self.assertEqual(code, 1, out[:300] + err[:300])
        self.assertEqual(machine.copy_calls, [])
        self.assertEqual(machine.copies(), [])
        self.assertEqual((machine.dumps_dir / "manifest.json").read_bytes(), broken)
        self.assertEqual(source.read_bytes(), MINI_DATA)


class TestFlags(DumpsTestCase):
    def test_delete_requires_copy(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / MINI_NAME, MINI_DATA, MINI_TIME)

        code, out, err = self.run_dumps(machine, "--delete-source")

        self.assertEqual(code, 2, out[:300] + err[:300])
        self.assertEqual(source.read_bytes(), MINI_DATA)
        self.assertEqual(machine.copy_calls, [])
        self.assertEqual(machine.remove_calls, [])
        self.assertFalse(machine.dumps_dir.exists())


class TestIsolation(EventsTestCase):
    def test_main_with_fakes_touches_no_machine(self):
        dumps = load_script("ush-events", "dumps")
        self.assertIn("dumpfiles", sys.modules)
        dumpfiles = sys.modules["dumpfiles"]
        self.assertIs(self.events.dumpfiles, dumpfiles)

        touched = []

        def forbidden(name):
            def call(*args, **kwargs):
                touched.append(name)
                raise AssertionError(f"{name} would read the machine")
            return call

        root = self.temp_root()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                self.events, "default_read_dumps", forbidden("default_read_dumps")))
            for name in ("default_read_value", "default_list_dir", "default_stat",
                         "default_open_file", "default_copy", "default_remove",
                         "default_disk_usage"):
                stack.enter_context(mock.patch.object(dumpfiles, name, forbidden(name)))

            # Fakes for both inputs: the run passes and no default is reached.
            summary = self.collect(lambda: dumps_object([], status="empty"),
                                   data_dir=root / "events-data")
            self.assertEqual(summary["dumps"]["status"], "empty")
            self.assertEqual(touched, [])

            # Some machine functions injected, others not: a loud error.
            machine = FakeMachine(root)
            functions = machine.functions()
            partial = (
                {"list_dir": functions["list_dir"], "stat": functions["stat"]},
                {k: v for k, v in functions.items() if k != "disk_usage"},
            )
            for injected in partial:
                with self.subTest(injected=sorted(injected)), \
                        contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(TypeError):
                    dumps.main(["--data-dir", str(machine.data_dir)], **injected, now=NOW)

            # A fake run_ps without read_dumps is a loud error too.
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(TypeError):
                self.events.main(["--data-dir", str(root / "events-data-2")],
                                 run_ps=FakePowerShell(), now=NOW)

        self.assertEqual(touched, [])


NOT_CHECKED = ["<!-- ush:not-checked -->", "## Not checked", "Nothing."]


class TestIds(EventsTestCase):
    def test_detail_and_checker_know_d_ids(self):
        # --detail d1 prints that run's dump from the detail file.
        data_dir = self.temp_root() / "ush-data"
        files = [
            dump_entry("x.dmp", "C:\\Invented\\Minidump\\x.dmp", 262144,
                       "2026-09-20T10:05:00+00:00"),
            dump_entry("z.dmp", "C:\\Invented\\Minidump\\z.dmp", 262144,
                       "2026-09-24T10:05:00+00:00"),
        ]
        summary = self.collect(lambda: dumps_object(files), data_dir=data_dir)
        d1 = summary["dumps"]["files"][0]
        self.assertEqual(d1["id"], "d1")
        detail = json.loads(Path(summary["detail_file"]).read_text(encoding="utf-8-sig"))
        self.assertEqual(detail["dump_files"], summary["dumps"]["files"])

        read_calls = []
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.events.main(["--data-dir", str(data_dir), "--detail", "d1",
                                     "--detail-file", summary["detail_file"]],
                                    run_ps=FakePowerShell(), now=NOW,
                                    read_dumps=lambda: read_calls.append(1))
        self.assertEqual(code, 0, out.getvalue()[:300])
        self.assertEqual(json.loads(out.getvalue()), d1)
        self.assertEqual(read_calls, [])

        # check_report knows d<n>: seven dumps, no 7 in any other value.
        check = load_script("ush-events", "check_report")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        (root / "reports").mkdir()
        summary_file = root / "summary.json"

        def run_check(data, line):
            data = {**data, "summary_file": str(summary_file),
                    "detail_file": str(root / "detail.json")}
            summary_file.write_text(json.dumps(data), encoding="utf-8")
            report = root / "reports" / "events-2026-09-28-1200.md"
            report.write_text("\n".join([f"<!-- ush:summary {summary_file} -->", line,
                                         *NOT_CHECKED]) + "\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = check.main([str(report)])
            return result, output.getvalue()

        names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]
        sizes = [200000, 300000, 400000, 500000, 600000, 800000, 900000]
        seven = [
            {"id": f"d{i}", "name": f"invented-{name}.dmp",
             "path": f"C:\\Invented\\Minidump\\invented-{name}.dmp", "size": size,
             "modified": f"2026-09-{19 + i}T10:00:00+00:00", "readable": True,
             "bugcheck": None, "bugcheck_candidates": []}
            for i, (name, size) in enumerate(zip(names, sizes), start=1)
        ]
        data = {"groups": [], "truncated": 0, "anomalies": [],
                "dumps": {"status": "read", "reason": None, "settings": dict(SETTINGS),
                          "files": seven}}
        # Only the id carries a 7 (the temporary paths added later are not readings).
        self.assertNotIn("7", json.dumps(data).replace('"d7"', ""))
        code, output = run_check(data, "Memory dump d7: invented-golf.dmp."
                                 " Other dumps: d1, d2, d3, d4, d5, d6.")
        self.assertEqual(code, 0, output)

        # A number only in a dump file name, or only in a bugcheck reference, is not backed.
        minidump = "093026-54321-01.dmp"
        linked = [{"id": "d1", "name": minidump,
                   "path": f"C:\\Invented\\Minidump\\{minidump}", "size": 200000,
                   "modified": "2026-09-20T10:00:00+00:00", "readable": True,
                   "bugcheck": "a8", "bugcheck_candidates": []}]
        data = {"groups": [], "truncated": 0, "anomalies": [],
                "dumps": {"status": "read", "reason": None, "settings": dict(SETTINGS),
                          "files": linked}}
        text = json.dumps(data)
        self.assertNotIn("54321", text.replace(minidump, ""))
        self.assertNotIn("8", text.replace('"a8"', ""))
        for line, number in (("Dump d1: there were 54321 crashes.", "54321"),
                             ("Dump d1: there were 8 crashes.", "8")):
            with self.subTest(number=number):
                code, output = run_check(data, line)
                self.assertEqual(code, 1, output)
                self.assertIn(number, output)


if __name__ == "__main__":
    unittest.main()

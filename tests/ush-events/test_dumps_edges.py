"""Edge cases of the memory dump scripts found in review of milestone M3.

- dumps.py --delete-source never removes a source whose manifest entry (naming the
  verified copy) could not be written first, and keeps entries an overlapping run
  wrote in the meantime;
- a temporary file that cannot be made gives that dump a not_copied result with a
  reason, and the run still ends with JSON;
- dumpfiles: a modification time that cannot be converted makes that one file
  unreadable (with a reason) instead of ending the events run.

Every file here is invented and lives in a temporary directory; the registry,
C:\\Windows and PowerShell are never touched.
"""

import importlib
import json
import os
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

base = importlib.import_module("tests.ush-events.test_dumps")

WRITE_FAILED = "Invented manifest write failure"
MKSTEMP_FAILED = "Invented temporary file failure"


class TestManifestBeforeDelete(base.DumpsTestCase):
    def test_source_kept_when_manifest_entry_not_written(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / base.MINI_NAME, base.MINI_DATA,
                               base.MINI_TIME)

        def failing_write(path, entries):
            raise OSError(28, WRITE_FAILED, str(path))

        with mock.patch.object(self.dumps, "write_manifest", failing_write):
            code, out, err = self.run_dumps(machine, "--copy", "--delete-source")

        self.assertEqual(code, 1, out[:300] + err[:300])
        # The original is still there and removal was never attempted.
        self.assertEqual(machine.remove_calls, [], "a source was removed although its "
                                                   "manifest entry could not be written")
        self.assertEqual(source.read_bytes(), base.MINI_DATA)
        data = json.loads(out)
        self.assertIn(WRITE_FAILED, data.get("error") or "", data)
        result = self.only_result(out)
        self.assertIs(result["source_deleted"], False, result)
        self.assertIs(result["source_kept"], True, result)

    def test_entry_on_disk_before_removal(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / base.MINI_NAME, base.MINI_DATA,
                               base.MINI_TIME)
        seen_at_removal = []
        real_remove = machine.remove

        def remove(path):
            seen_at_removal.append(machine.manifest())
            real_remove(path)

        machine.remove = remove
        code, out, err = self.run_dumps(machine, "--copy", "--delete-source")

        self.assertEqual(code, 0, out[:300] + err[:300])
        self.assertFalse(source.exists())
        self.assertEqual(len(seen_at_removal), 1, seen_at_removal)
        before = seen_at_removal[0]
        self.assertEqual(len(before), 1, before)
        self.assertIs(before[0]["verified"], True, before)
        self.assertTrue((machine.dumps_dir / Path(before[0]["copy"]).name).exists(), before)
        after = machine.manifest()
        self.assertEqual(len(after), 1, after)
        self.assertEqual(after[0]["copy"], before[0]["copy"])
        self.assertIs(after[0]["source_deleted"], True, after)

    def test_rewrite_failure_after_removal_is_reported(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / base.MINI_NAME, base.MINI_DATA,
                               base.MINI_TIME)
        real_write = self.dumps.write_manifest
        calls = []

        def second_write_fails(path, entries):
            calls.append(1)
            if len(calls) > 1:
                raise OSError(28, WRITE_FAILED, str(path))
            real_write(path, entries)

        with mock.patch.object(self.dumps, "write_manifest", second_write_fails):
            code, out, err = self.run_dumps(machine, "--copy", "--delete-source")

        self.assertEqual(code, 1, out[:300] + err[:300])
        self.assertFalse(source.exists())
        data = json.loads(out)
        self.assertIn(WRITE_FAILED, data.get("error") or "", data)
        manifest = machine.manifest()
        self.assertEqual(len(manifest), 1, manifest)
        self.assertIs(manifest[0]["verified"], True, manifest)
        self.assertTrue((machine.dumps_dir / Path(manifest[0]["copy"]).name).exists())
        self.assertIs(self.only_result(out)["source_deleted"], True)


OTHER_DUMP_ENTRY = {"name": "invented-other.dmp", "copy": "invented-other-copy.dmp",
                    "verified": True, "source_deleted": False}


class TestOverlappingRuns(base.DumpsTestCase):
    def test_entry_of_an_overlapping_run_is_kept(self):
        # Another run appends its entry between this run's two manifest writes.
        machine = self.machine()
        machine.write(machine.minidump_dir / base.MINI_NAME, base.MINI_DATA, base.MINI_TIME)
        real_remove = machine.remove

        def remove(path):
            entries = machine.manifest()
            (machine.dumps_dir / "manifest.json").write_text(
                json.dumps([*entries, OTHER_DUMP_ENTRY]), encoding="utf-8")
            real_remove(path)

        machine.remove = remove
        code, out, err = self.run_dumps(machine, "--copy", "--delete-source")

        self.assertEqual(code, 0, out[:300] + err[:300])
        entries = machine.manifest()
        self.assertEqual(len(entries), 2, entries)
        self.assertIs(entries[0]["source_deleted"], True, entries)
        self.assertEqual(entries[1], OTHER_DUMP_ENTRY)


class TestTemporaryFileFailure(base.DumpsTestCase):
    def test_mkstemp_failure_gives_not_copied(self):
        machine = self.machine()
        source = machine.write(machine.minidump_dir / base.MINI_NAME, base.MINI_DATA,
                               base.MINI_TIME)

        def failing_mkstemp(*args, **kwargs):
            raise PermissionError(13, MKSTEMP_FAILED, kwargs.get("dir"))

        fake_tempfile = types.SimpleNamespace(mkstemp=failing_mkstemp)
        with mock.patch.object(self.dumps, "tempfile", fake_tempfile):
            try:
                code, out, err = self.run_dumps(machine, "--copy", "--delete-source")
            except OSError as exc:
                self.fail(f"the run crashed instead of reporting the dump: {exc!r}")

        self.assertEqual(code, 1, out[:300] + err[:300])
        result = self.only_result(out)
        self.assertEqual(result["status"], "not_copied", result)
        self.assertIn(MKSTEMP_FAILED, result.get("reason") or "", result)
        self.assertIs(result["source_kept"], True, result)
        self.assertEqual(machine.copy_calls, [])
        self.assertEqual(machine.remove_calls, [])
        self.assertEqual(source.read_bytes(), base.MINI_DATA)
        # Never attempted: no manifest entry.
        self.assertFalse((machine.dumps_dir / "manifest.json").exists())


class TestAbsurdModificationTime(base.EventsTestCase):
    def test_absurd_mtime_makes_one_file_unreadable(self):
        dumpfiles = load_script("ush-events", "dumpfiles")
        machine = base.FakeMachine(self.temp_root())
        good = machine.write(machine.minidump_dir / base.MINI_NAME, base.MINI_DATA,
                             base.MINI_TIME)
        odd = machine.write(machine.minidump_dir / "Mini092126-01.dmp", base.MINI_DATA,
                            base.MINI_TIME)
        real_stat = machine.stat

        def stat(path):
            info = real_stat(path)
            if base.norm(path) == base.norm(odd):
                return types.SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size,
                                             st_mtime=1e300)
            return info

        def read_dumps():
            settings = dumpfiles.crash_settings(machine.read_value)
            return dumpfiles.inventory(settings, machine.list_dir, stat, machine.open_file)

        try:
            summary = self.collect(read_dumps)
        except (OSError, ValueError, OverflowError) as exc:
            self.fail(f"the events run crashed on one file's time: {exc!r}")

        entry = self.file(summary, "Mini092126-01.dmp")
        self.assertIs(entry["readable"], False, entry)
        self.assertIsNone(entry["modified"], entry)
        self.assertIn("modification time", entry.get("reason") or "", entry)
        self.assertIs(self.file(summary, base.MINI_NAME)["readable"], True)
        self.assertTrue(os.path.exists(good))


class TestDumpPathListed(unittest.TestCase):
    """A bugcheck naming a dump outside the listed places is not called gone."""

    def test_dump_path_outside_inventory_is_not_listed(self):
        events = load_script("ush-events", "events")
        root = os.path.join("X:" + os.sep, "InventedWindows")
        dumps = {"status": "read", "reason": None, "files": [],
                 "settings": {"minidump_dir": os.path.join(root, "Minidump"),
                              "dump_file": os.path.join(root, "MEMORY.DMP")}}
        inside = {"id": "a1", "kind": "bugcheck",
                  "dump_path": os.path.join(root, "Minidump", "Mini-invented.dmp")}
        full = {"id": "a2", "kind": "bugcheck",
                "dump_path": os.path.join(root, "memory.dmp")}
        outside = {"id": "a3", "kind": "bugcheck",
                   "dump_path": os.path.join("Y:" + os.sep, "Elsewhere", "Mini-invented.dmp")}
        events.link_dumps([inside, full, outside], dumps)
        self.assertEqual([inside["dump_path_listed"], full["dump_path_listed"],
                          outside["dump_path_listed"]], [True, True, False])
        unknown = {"id": "a4", "kind": "bugcheck", "dump_path": inside["dump_path"]}
        events.link_dumps([unknown], {"status": "unreadable", "reason": "x",
                                      "settings": None, "files": []})
        self.assertIsNone(unknown["dump_path_listed"])


class TestWrongRegistryType(unittest.TestCase):
    """A CrashControl path value of the wrong type makes the dumps unreadable."""

    def test_non_string_dump_setting_is_unreadable(self):
        dumpfiles = load_script("ush-events", "dumpfiles")

        def read_value(key, name):
            if name == "MinidumpDir":
                return 12345
            raise FileNotFoundError(2, "Invented missing value", name)

        def never(*args):
            raise AssertionError("nothing may be listed with unknown settings")

        try:
            found = dumpfiles.read_all(read_value, never, never, never)
        except Exception as exc:  # noqa: BLE001 - the mutation shows up here
            self.fail(f"the inventory crashed on a wrong registry type: {exc!r}")
        self.assertEqual(found["status"], "unreadable")
        self.assertIn("MinidumpDir", found["reason"])
        self.assertEqual(found["files"], [])


class TestMissingCrashDumpEnabled(unittest.TestCase):
    """A missing CrashDumpEnabled is the Windows default, never "disabled"."""

    def test_missing_value_takes_the_default(self):
        dumpfiles = load_script("ush-events", "dumpfiles")

        def read_value(key, name):
            if name == "CrashDumpEnabled":
                raise FileNotFoundError(2, "Invented missing value", name)
            return "C:\\Invented\\" + name

        settings = dumpfiles.crash_settings(read_value)
        self.assertEqual(settings["crash_dump_enabled"], 7)
        self.assertEqual(settings["defaulted"], ["crash_dump_enabled"])

    def test_written_value_is_kept(self):
        dumpfiles = load_script("ush-events", "dumpfiles")
        settings = dumpfiles.crash_settings(
            lambda key, name: 0 if name == "CrashDumpEnabled" else "C:\\Invented\\" + name)
        self.assertEqual(settings["crash_dump_enabled"], 0)
        self.assertEqual(settings["defaulted"], [])


if __name__ == "__main__":
    unittest.main()

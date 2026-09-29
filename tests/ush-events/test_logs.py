"""Behaviour tests for exporting and clearing an event log:
skills/ush-events/scripts/logs.py.

Public interface under test:
- ``logs.main(argv=None, run=None, is_admin=None, now=None) -> int``
- Flags: ``--data-dir <dir>``, ``--export {System,Application}``, ``--clear`` (a bare flag,
  allowed only together with ``--export``; it clears the exported log). Any other log name or
  ``--clear`` without ``--export`` is a parser error: exit code 2, nothing run.
- Exit codes: 0 when everything asked for is done and verified; 1 when the export is not
  verified, the export failed, clearing was refused (no administrator) or the clear is not
  verified; 2 for a parser error.

Protocol of the injected ``run`` (every external command goes through it):
``run(job, command, out_path) -> (exit_code, stderr_text)``

- ``job`` is a short label, exactly one of:
  - ``"state:<log>"``: PowerShell query of the log before the export. ``command`` is the
    PowerShell script (a str). The fake writes one JSON object to ``out_path``:
    ``{"RecordCount": int, "OldestRecordId": int, "NewestRecordId": int}``.
  - ``"export:<log>"``: ``command`` is an argv list
    ``["wevtutil", "epl", <log>, <absolute .evtx path>, ...options]``. ``out_path`` is ignored
    (may be None). On exit code 0 the fake creates the .evtx file at that path with invented
    bytes; on a non-zero code it creates nothing.
  - ``"read:export"``: PowerShell ``Get-WinEvent -Path <export file>`` measured over RecordId.
    ``command`` is a str that contains the export file name. The fake writes one JSON object
    to ``out_path`` in the ``Measure-Object`` shape: ``{"Count": int, "Minimum": int,
    "Maximum": int}``.
  - ``"clear:<log>"``: ``command`` is an argv list
    ``["wevtutil", "cl", <log>, "/bu:<absolute ...-rest.evtx path>"]``. ``out_path`` is
    ignored. On exit code 0 the fake creates the backup file at the /bu: path.
  - ``"read:rest"``: like ``read:export`` for the ``-rest`` backup file (its name is in the
    script); same ``{"Count", "Minimum", "Maximum"}`` object.
  - ``"after:<log>"``: PowerShell query of the log after clearing; same object shape as
    ``state:<log>``. Its ``RecordCount`` is stored in the clear result.
- For PowerShell jobs ``out_path`` is an absolute path the script writes its JSON to (UTF-8,
  no BOM); the fake writes there and returns ``(0, "")``. Unknown jobs return
  ``(1, "Invented unknown job")``.

Result on stdout (JSON; the tests search every nested object, so the placement is free):
- an export result object with ``verified`` (bool), ``reason`` (str or null),
  ``file`` (absolute path under ``<data-dir>/exports/``) and ``sha256``; the first object
  holding a ``verified`` key is taken as the export result, and every object holding
  ``verified`` must agree on its value;
- with ``--clear`` and a verified export at most one clear result object with ``cleared``
  (bool), ``reason`` (str or null) and ``record_count_after`` (the RecordCount read back).

Manifest ``<data-dir>/exports/manifest.json``: a JSON list whose entries have ``log``,
``file``, ``sha256``, ``record_count``, ``min_record_id``, ``max_record_id``, ``verified``,
``reason``.

Refusing to clear without administrator rights says "elevated" (an elevated console) on
stdout or stderr.

Every log state, record id and file byte here is invented. wevtutil, PowerShell and the
registry are never run; files live only in temporary directories.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)

EXPORT_BYTES = b"ElfFile\x00" + b"invented exported records" * 40
REST_BYTES = b"ElfFile\x00" + b"invented backup at clearing" * 40
EPL_DENIED = "Invented: access is denied (5)."

MANIFEST_FIELDS = {"log", "file", "sha256", "record_count", "min_record_id", "max_record_id",
                   "verified", "reason"}

STATE = {"RecordCount": 250, "OldestRecordId": 1001, "NewestRecordId": 1250}
COMPLETE_FILE = {"Count": 250, "Minimum": 1001, "Maximum": 1250}


def norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def walk(value):
    """Every dict inside a parsed JSON value."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def is_wevtutil(command):
    if not isinstance(command, (list, tuple)) or not command:
        return False
    first = os.path.basename(str(command[0])).lower()
    return first in ("wevtutil", "wevtutil.exe")


def mentions_clear(command):
    """True for any command that would clear a log, whatever the job label says."""
    if isinstance(command, (list, tuple)):
        tokens = [str(t).lower() for t in command]
        return "cl" in tokens or "clear-log" in tokens or any(
            "clear-eventlog" in t or "clearlog" in t for t in tokens)
    text = str(command).lower()
    return bool(re.search(r"wevtutil(?:\.exe)?['\"]?\s+(?:cl|clear-log)\b", text)
                or "clear-eventlog" in text or "clearlog" in text)


class FakeRun:
    """Stands in for run(job, command, out_path); records every call."""

    def __init__(self, log="System", state=None, export_read=None, rest_read=None, after=None,
                 epl_code=0, epl_stderr="", cl_code=0):
        self.log = log
        self.responses = {
            f"state:{log}": state if state is not None else dict(STATE),
            "read:export": export_read if export_read is not None else dict(COMPLETE_FILE),
            "read:rest": rest_read,
            f"after:{log}": after,
        }
        self.epl_code = epl_code
        self.epl_stderr = epl_stderr
        self.cl_code = cl_code
        self.calls = []
        self.problems = []
        self.export_path = None
        self.rest_path = None

    def jobs(self):
        return [job for job, _, _ in self.calls]

    def clear_calls(self):
        return [(job, command) for job, command, _ in self.calls
                if job.startswith("clear:") or mentions_clear(command)]

    def _wevtutil(self, job, command, verb):
        if not is_wevtutil(command):
            self.problems.append(f"{job}: not a wevtutil argv list: {command!r}")
            return None, []
        tokens = [str(t) for t in command]
        lowered = [t.lower() for t in tokens]
        if verb not in lowered:
            self.problems.append(f"{job}: no '{verb}' verb: {command!r}")
            return None, []
        i = lowered.index(verb)
        rest = tokens[i + 1:]
        if not rest or rest[0] != self.log:
            self.problems.append(f"{job}: log name is not {self.log}: {command!r}")
        return (rest[0] if rest else None), rest[1:]

    def __call__(self, job, command, out_path):
        self.calls.append((job, command, out_path))
        kind, _, _arg = job.partition(":")

        if kind == "export":
            _, options = self._wevtutil(job, command, "epl")
            targets = [t.strip("\"'") for t in options if not t.startswith("/")]
            if not targets:
                self.problems.append(f"{job}: no target path: {command!r}")
                return 1, "Invented: missing target"
            self.export_path = Path(targets[0])
            if self.epl_code == 0:
                self.export_path.write_bytes(EXPORT_BYTES)
            return self.epl_code, self.epl_stderr

        if kind == "clear":
            _, options = self._wevtutil(job, command, "cl")
            backups = [t[4:].strip("\"'") for t in options if t.lower().startswith("/bu:")]
            if not backups:
                self.problems.append(f"{job}: no /bu: backup: {command!r}")
                return 1, "Invented: missing backup"
            self.rest_path = Path(backups[0])
            if self.cl_code == 0:
                self.rest_path.write_bytes(REST_BYTES)
            return self.cl_code, ""

        response = self.responses.get(job)
        if response is None:
            return 1, "Invented unknown job"
        if not isinstance(command, str):
            self.problems.append(f"{job}: expected a PowerShell script: {command!r}")
        if job == "read:export" and self.export_path is not None \
                and self.export_path.name not in str(command):
            self.problems.append(f"{job}: script does not name the export file")
        if job == "read:rest" and self.rest_path is not None \
                and self.rest_path.name not in str(command):
            self.problems.append(f"{job}: script does not name the -rest file")
        if out_path is None or not Path(out_path).is_absolute():
            self.problems.append(f"{job}: out_path is not absolute: {out_path!r}")
            return 1, "Invented: bad out_path"
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(response), encoding="utf-8")
        return 0, ""


class FakeAdmin:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class LogsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs = load_script("ush-events", "logs")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def run_logs(self, data_dir, fake, admin, *flags):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.logs.main([*flags, "--data-dir", str(data_dir)],
                                      run=fake, is_admin=admin, now=NOW)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            return json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")

    def export_result(self, stdout):
        found = [d for d in walk(self.parse(stdout)) if "verified" in d]
        self.assertTrue(found, stdout[:600])
        # The result may repeat the manifest entry; every copy must agree.
        self.assertEqual(len({repr(d["verified"]) for d in found}), 1, stdout[:600])
        return found[0]

    def clear_results(self, stdout):
        return [d for d in walk(self.parse(stdout)) if "cleared" in d]

    def manifest(self, data_dir):
        path = data_dir / "exports" / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def assert_clean_fake(self, fake):
        self.assertEqual(fake.problems, [], fake.calls)


class TestExport(LogsTestCase):
    def test_export_verified(self):
        data_dir = self.data_dir()
        fake = FakeRun(log="Application")
        admin = FakeAdmin(False)

        code, out, err = self.run_logs(data_dir, fake, admin, "--export", "Application")

        self.assertEqual(code, 0, out[:300] + err[:300])
        self.assert_clean_fake(fake)
        self.assertEqual(fake.clear_calls(), [])
        self.assertIsNotNone(fake.export_path, fake.calls)
        # The export goes under <data-dir>/exports/ with an absolute path.
        self.assertTrue(fake.export_path.is_absolute(), fake.export_path)
        self.assertEqual(norm(fake.export_path.parent), norm(data_dir / "exports"))
        self.assertTrue(fake.export_path.name.startswith("Application-"), fake.export_path)
        self.assertEqual(fake.export_path.suffix.lower(), ".evtx")
        self.assertEqual(fake.export_path.read_bytes(), EXPORT_BYTES)

        result = self.export_result(out)
        self.assertIs(result["verified"], True, result)
        self.assertEqual(norm(result["file"]), norm(fake.export_path))
        self.assertEqual(result["sha256"], sha(EXPORT_BYTES))

        manifest = self.manifest(data_dir)
        self.assertIsInstance(manifest, list, manifest)
        self.assertEqual(len(manifest), 1, manifest)
        entry = manifest[0]
        self.assertLessEqual(MANIFEST_FIELDS, set(entry), entry)
        self.assertEqual(entry["log"], "Application")
        self.assertTrue(Path(entry["file"]).is_absolute(), entry)
        self.assertEqual(norm(entry["file"]), norm(fake.export_path))
        self.assertEqual(entry["sha256"], sha(EXPORT_BYTES))
        self.assertEqual(entry["record_count"], 250)
        self.assertEqual(entry["min_record_id"], 1001)
        self.assertEqual(entry["max_record_id"], 1250)
        self.assertIs(entry["verified"], True, entry)

    def test_unverified_export_blocks_clear(self):
        cases = {
            # One record missing between the oldest and the newest.
            "gap": {"Count": 249, "Minimum": 1001, "Maximum": 1250},
            # The file starts after the oldest record the log had before the export.
            "late_start": {"Count": 249, "Minimum": 1002, "Maximum": 1250},
        }
        for name, export_read in cases.items():
            with self.subTest(case=name):
                data_dir = self.data_dir()
                fake = FakeRun(log="System", export_read=export_read)
                admin = FakeAdmin(True)

                code, out, err = self.run_logs(data_dir, fake, admin,
                                               "--export", "System", "--clear")

                self.assertEqual(code, 1, out[:300] + err[:300])
                self.assert_clean_fake(fake)
                result = self.export_result(out)
                self.assertIs(result["verified"], False, result)
                self.assertTrue((result.get("reason") or "").strip(), result)
                self.assertEqual(fake.clear_calls(), [], fake.calls)
                for cleared in self.clear_results(out):
                    self.assertIsNot(cleared["cleared"], True, cleared)

    def test_failed_export_blocks_clear(self):
        data_dir = self.data_dir()
        fake = FakeRun(log="System", epl_code=5, epl_stderr=EPL_DENIED)
        admin = FakeAdmin(True)

        code, out, err = self.run_logs(data_dir, fake, admin, "--export", "System", "--clear")

        self.assertEqual(code, 1, out[:300] + err[:300])
        self.assertIn("export:System", fake.jobs())
        result = self.export_result(out)
        self.assertIs(result["verified"], False, result)
        self.assertTrue((result.get("reason") or "").strip(), result)
        self.assertEqual(fake.clear_calls(), [], fake.calls)
        for cleared in self.clear_results(out):
            self.assertIsNot(cleared["cleared"], True, cleared)


class TestClear(LogsTestCase):
    def test_clear_needs_admin(self):
        data_dir = self.data_dir()
        fake = FakeRun(log="System")
        admin = FakeAdmin(False)

        code, out, err = self.run_logs(data_dir, fake, admin, "--export", "System", "--clear")

        self.assertEqual(code, 1, out[:300] + err[:300])
        self.assert_clean_fake(fake)
        self.assertGreaterEqual(admin.calls, 1)
        self.assertEqual(fake.clear_calls(), [], fake.calls)
        self.assertIn("elevated", (out + err).lower(), out[:300] + err[:300])
        for cleared in self.clear_results(out):
            self.assertIsNot(cleared["cleared"], True, cleared)

        # The verified export stays.
        result = self.export_result(out)
        self.assertIs(result["verified"], True, result)
        self.assertIsNotNone(fake.export_path)
        self.assertEqual(fake.export_path.read_bytes(), EXPORT_BYTES)
        manifest = self.manifest(data_dir)
        self.assertEqual(len(manifest), 1, manifest)
        self.assertIs(manifest[0]["verified"], True, manifest)
        self.assertEqual(norm(manifest[0]["file"]), norm(fake.export_path))

    def test_clear_after_verified_export_with_backup(self):
        after = {"RecordCount": 1, "OldestRecordId": 1, "NewestRecordId": 1}

        # The backup holds everything up to the moment of clearing: cleared.
        data_dir = self.data_dir()
        fake = FakeRun(log="System",
                       rest_read={"Count": 260, "Minimum": 1001, "Maximum": 1260},
                       after=after)
        admin = FakeAdmin(True)

        code, out, err = self.run_logs(data_dir, fake, admin, "--export", "System", "--clear")

        self.assertEqual(code, 0, out[:300] + err[:300])
        self.assert_clean_fake(fake)
        self.assertGreaterEqual(admin.calls, 1)
        clears = fake.clear_calls()
        self.assertEqual(len(clears), 1, fake.calls)
        self.assertEqual(clears[0][0], "clear:System")
        jobs = fake.jobs()
        self.assertLess(jobs.index("export:System"), jobs.index("clear:System"))
        self.assertLess(jobs.index("read:export"), jobs.index("clear:System"))
        self.assertLess(jobs.index("clear:System"), jobs.index("read:rest"))
        # /bu: points under <data-dir>/exports/ and names a -rest file.
        self.assertIsNotNone(fake.rest_path)
        self.assertTrue(fake.rest_path.is_absolute(), fake.rest_path)
        self.assertEqual(norm(fake.rest_path.parent), norm(data_dir / "exports"))
        self.assertTrue(fake.rest_path.name.startswith("System-"), fake.rest_path)
        self.assertTrue(fake.rest_path.name.lower().endswith("-rest.evtx"), fake.rest_path)
        self.assertEqual(fake.rest_path.read_bytes(), REST_BYTES)

        cleared = self.clear_results(out)
        self.assertEqual(len(cleared), 1, out[:600])
        self.assertIs(cleared[0]["cleared"], True, cleared[0])
        self.assertEqual(cleared[0]["record_count_after"], 1, cleared[0])

        # The backup ends before the verified export does: not cleared.
        data_dir = self.data_dir()
        fake = FakeRun(log="System",
                       rest_read={"Count": 240, "Minimum": 1001, "Maximum": 1240},
                       after=after)
        admin = FakeAdmin(True)

        code, out, err = self.run_logs(data_dir, fake, admin, "--export", "System", "--clear")

        self.assertEqual(code, 1, out[:300] + err[:300])
        self.assert_clean_fake(fake)
        cleared = self.clear_results(out)
        self.assertEqual(len(cleared), 1, out[:600])
        self.assertIs(cleared[0]["cleared"], False, cleared[0])
        self.assertTrue((cleared[0].get("reason") or "").strip(), cleared[0])


class TestFlags(LogsTestCase):
    def test_clear_requires_export_and_known_log(self):
        for flags in (["--clear"], ["--export", "Security"]):
            with self.subTest(flags=flags):
                data_dir = self.data_dir()
                fake = FakeRun(log="System")
                admin = FakeAdmin(True)

                code, out, err = self.run_logs(data_dir, fake, admin, *flags)

                self.assertEqual(code, 2, out[:300] + err[:300])
                self.assertEqual(fake.calls, [])
                self.assertEqual(admin.calls, 0)
                self.assertFalse((data_dir / "exports").exists())


if __name__ == "__main__":
    unittest.main()

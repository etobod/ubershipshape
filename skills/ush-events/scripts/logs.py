"""Export an event log to a verified .evtx file and, with --clear, clear it.

Usage (from the project root):

    python -B skills/ush-events/scripts/logs.py --export {System,Application} [--data-dir ush-data]
    python -B skills/ush-events/scripts/logs.py --export System --clear [--data-dir ...]

``--export`` needs no elevation and writes only under ``<data-dir>``:

1. the state of the log is read (``RecordCount``, oldest and newest
   ``RecordId``);
2. ``wevtutil epl <log> <data-dir>/exports/<log>-<UTC stamp>.evtx``; an
   existing file is never overwritten;
3. the file is read back (``Get-WinEvent -Path``): count, smallest and
   largest ``RecordId``;
4. ``verified`` needs all of: exit code 0, file minimum <= oldest before the
   export, file maximum >= newest before the export, and count == maximum -
   minimum + 1 (no gap);
5. the file's SHA-256 and the read-back numbers go to
   ``<data-dir>/exports/manifest.json``, an append-only JSON list; an
   unreadable or corrupt manifest stops the run before any command.

``--clear`` (only with ``--export``) clears that same log, and only after a
verified export whose manifest entry is on disk, and only in an elevated
console (otherwise it stops with a message and exit code 1; the export
stays). It runs ``wevtutil cl <log> /bu:<data-dir>/exports/<log>-<stamp>-rest.evtx``,
so the backup holds the whole log at the moment of clearing, including
records written after the export. ``cleared`` is true only when ``cl``
exited 0, the ``-rest`` file can be read and its largest ``RecordId`` is >=
the largest of the verified export, and the log's ``RecordCount`` read
back after clearing is lower than the ``-rest`` file's record count.
Clearing is irreversible: the .evtx files can be opened in Event
Viewer but cannot be loaded back into the log.

Every external command goes through an injectable ``run(job, command,
out_path) -> (exit_code, stderr_text)``: ``command`` is an argv list for
wevtutil and a PowerShell script (str) for the reads, which write one JSON
object to ``out_path`` in ``<data-dir>/work/``. ``is_admin`` is injectable
too. The script counts and compares record ids; it never judges the log.

Exit codes: 0 everything asked for is done and verified; 1 the export is not
verified or failed, clearing was refused or is not verified, or the manifest
could not be read or written; 2 bad arguments (before any command runs).
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# load_script does not put this directory on sys.path; the helpers live next to this file.
sys.path.insert(0, str(Path(__file__).absolute().parent))

import dumps
import events
from dumpfiles import describe, digest, iso

LOGS = ("System", "Application")
WEVTUTIL_TIMEOUT = 600  # seconds; exporting or clearing a large log takes a while
NEEDS_ELEVATION = ("clearing a log needs an elevated console (Run as administrator); "
                   "the verified export was kept and nothing was cleared")

# Shared head and tail of the read scripts: result through a BOM-less UTF-8
# file, errors on stderr in UTF-8 (the pattern of events.PS_TEMPLATE).
PS_HEAD = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
"""
PS_TAIL = """
$json = ConvertTo-Json -InputObject $o -Compress
[System.IO.File]::WriteAllText({path}, $json, [System.Text.UTF8Encoding]::new($false))
"""

# An empty log gives NoMatchingEventsFound; that is "no record", not an error.
STATE_BODY = """$info = Get-WinEvent -ListLog {log}
function Edge($oldest) {{
  try {{
    if ($oldest) {{ $e = Get-WinEvent -LogName {log} -MaxEvents 1 -Oldest }}
    else {{ $e = Get-WinEvent -LogName {log} -MaxEvents 1 }}
  }} catch {{
    if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {{ return $null }}
    throw
  }}
  return [long]@($e)[0].RecordId
}}
$o = [pscustomobject]@{{
  RecordCount = $(if ($null -ne $info.RecordCount) {{ [long]$info.RecordCount }} else {{ $null }})
  OldestRecordId = Edge $true
  NewestRecordId = Edge $false
}}"""

FILE_BODY = """try {{
  $m = Get-WinEvent -Path {path} -Oldest | Measure-Object -Property RecordId -Minimum -Maximum
  $o = [pscustomobject]@{{ Count = [long]$m.Count; Minimum = [long]$m.Minimum; Maximum = [long]$m.Maximum }}
}} catch {{
  if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') {{ throw }}
  $o = [pscustomobject]@{{ Count = 0; Minimum = $null; Maximum = $null }}
}}"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logs.py",
        description=("Export an event log to <data-dir>/exports/ and verify the file. "
                     "With --clear, clear the log after a verified export (elevated only)."),
    )
    parser.add_argument("--data-dir", default="ush-data",
                        help="output directory, relative to the working directory "
                             "(default: ush-data)")
    parser.add_argument("--export", choices=LOGS, required=True,
                        help="the log to export")
    parser.add_argument("--clear", action="store_true",
                        help="after a verified export, clear the same log with a backup "
                             "(irreversible; needs an elevated console)")
    return parser


# --- the real machine functions (tests replace both) ----------------------
def default_run(job: str, command, out_path) -> tuple[int, str]:
    """Run an argv list directly, a str as a PowerShell script (events.default_run_ps)."""
    if isinstance(command, str):
        return events.default_run_ps(job, command, out_path)
    try:
        result = subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,  # a non-zero exit is data here
            timeout=WEVTUTIL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 1, f"{job}: {command[0]} did not finish within {WEVTUTIL_TIMEOUT} s"
    except OSError as exc:
        return 1, f"{job}: {command[0]} could not be started: {describe(exc)}"
    return result.returncode, _console_text(result.stderr or result.stdout or b"")


def _console_text(data: bytes) -> str:
    """wevtutil writes in the OEM code page; fall back to UTF-8 off Windows."""
    try:
        return data.decode("oem", errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def default_is_admin() -> bool:
    try:
        import ctypes  # Windows-only, and only for a real run

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


# --- reads ----------------------------------------------------------------
def state_script(log: str, out_path: Path) -> str:
    return (PS_HEAD + STATE_BODY.format(log=events.ps_quote(log))
            + PS_TAIL.format(path=events.ps_quote(out_path)))


def file_script(evtx: Path, out_path: Path) -> str:
    return (PS_HEAD + FILE_BODY.format(path=events.ps_quote(evtx))
            + PS_TAIL.format(path=events.ps_quote(out_path)))


def _load_object(path: Path) -> list:
    """events.run_job loader: one JSON object, returned as a one-item list."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("the result is not a JSON object")  # noqa: TRY004
    return [data]


def _number(data: dict, key: str, nullable: bool = False):
    value = data.get(key)
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} is not an integer: {value!r}")  # noqa: TRY004
    return value


def read_json(run, job: str, script: str, out_path: Path, fields: dict) -> dict:
    """Run one read job; {"status": "read"|"unreadable", "reason", <fields>}.

    ``fields`` maps a result key to (JSON key, nullable). Reading nothing is
    never taken for zero: a missing or malformed value makes it unreadable.
    """
    done = events.run_job(run, job, script, out_path, load=_load_object)
    result = {"status": "unreadable", "reason": done["reason"],
              **{name: None for name in fields}}
    if done["status"] != "read":
        result["reason"] = done["reason"] or "PowerShell wrote an empty result"
        return result
    data = done["events"][0]
    try:
        values = {name: _number(data, key, nullable) for name, (key, nullable) in fields.items()}
    except ValueError as exc:
        result["reason"] = f"the result of {job} is malformed: {exc}"
        return result
    result.update(status="read", reason=None, **values)
    return result


STATE_FIELDS = {"record_count": ("RecordCount", False),
                "oldest_record_id": ("OldestRecordId", True),
                "newest_record_id": ("NewestRecordId", True)}
FILE_FIELDS = {"record_count": ("Count", False),
               "min_record_id": ("Minimum", True),
               "max_record_id": ("Maximum", True)}


def export_reason(code: int, stderr: str, state: dict, read: dict) -> str | None:
    """Why the export is not verified, or None when it is."""
    if code != 0:
        return (f"wevtutil epl exited with code {code}: "
                f"{(stderr or '').strip()[:events.STDERR_MAX] or 'no error text'}")
    if read["status"] != "read":
        return f"the exported file could not be read back: {read['reason']}"
    oldest, newest = state["oldest_record_id"], state["newest_record_id"]
    if oldest is None or newest is None:
        return "the log had no records before the export; there is nothing to verify"
    low, high, count = read["min_record_id"], read["max_record_id"], read["record_count"]
    if low is None or high is None:
        return f"the exported file holds no records, the log held {state['record_count']}"
    if low > oldest:
        return (f"the file starts at RecordId {low}, after the oldest record before the "
                f"export ({oldest})")
    if high < newest:
        return (f"the file ends at RecordId {high}, before the newest record before the "
                f"export ({newest})")
    if count != high - low + 1:
        return (f"the file holds {count} records for RecordId {low}..{high} "
                f"({high - low + 1} expected): records are missing")
    return None


def _manifest_entry(log: str, kind: str, path: Path, sha: str | None, read: dict,
                    verified: bool, reason: str | None, now: datetime) -> dict:
    return {"log": log, "kind": kind, "file": str(path), "sha256": sha,
            "record_count": read["record_count"], "min_record_id": read["min_record_id"],
            "max_record_id": read["max_record_id"], "verified": verified, "reason": reason,
            "written_at": iso(now)}


def _hash(path: Path) -> tuple[str | None, str | None]:
    try:
        return digest(path)[0], None
    except OSError as exc:
        return None, f"its SHA-256 could not be computed: {describe(exc)}"


def export(run, log: str, exports: Path, work: Path, stamp: str) -> dict:
    """Steps 1-4; the result carries the file read-back for the manifest."""
    target = exports / f"{log}-{stamp}.evtx"
    result = {"log": log, "file": str(target), "verified": False, "reason": None,
              "sha256": None, "exit_code": None, "state_before": None,
              "record_count": None, "min_record_id": None, "max_record_id": None}
    out = work / f"logs-{stamp}-{os.getpid()}.state-{log}.json"
    state = read_json(run, f"state:{log}", state_script(log, out), out, STATE_FIELDS)
    result["state_before"] = state
    if state["status"] != "read":
        result["reason"] = f"the state of the log could not be read: {state['reason']}"
        return result
    if target.exists():
        result["reason"] = f"{target.name} already exists; it is not overwritten"
        return result

    code, stderr = run(f"export:{log}", ["wevtutil", "epl", log, str(target)], None)
    result["exit_code"] = code
    read = {"status": "unreadable", "reason": "not read", **{k: None for k in FILE_FIELDS}}
    if code == 0 and target.is_file():
        out = work / f"logs-{stamp}-{os.getpid()}.read-export.json"
        read = read_json(run, "read:export", file_script(target, out), out, FILE_FIELDS)
    elif code == 0:
        read["reason"] = "wevtutil epl exited 0 but the file does not exist"
    result.update(record_count=read["record_count"], min_record_id=read["min_record_id"],
                  max_record_id=read["max_record_id"])
    if target.is_file():
        result["sha256"], hash_reason = _hash(target)
    else:
        hash_reason = None
    reason = export_reason(code, stderr, state, read) or hash_reason
    result.update(verified=reason is None, reason=reason)
    return result


def clear(run, log: str, exports: Path, work: Path, stamp: str,
          export_max: int) -> tuple[dict, dict | None]:
    """wevtutil cl with a backup, then the read-back of the backup and the log.

    Returns (clear result, backup check or None when no backup file exists);
    the backup check is {"read": file read-back, "verified": bool, "reason"}.
    """
    backup = exports / f"{log}-{stamp}-rest.evtx"
    result = {"log": log, "cleared": False, "reason": None, "exit_code": None,
              "file": str(backup), "sha256": None, "backup_record_count": None,
              "backup_min_record_id": None, "backup_max_record_id": None,
              "record_count_after": None}
    if backup.exists():
        result["reason"] = f"{backup.name} already exists; nothing was cleared"
        return result, None

    code, stderr = run(f"clear:{log}", ["wevtutil", "cl", log, f"/bu:{backup}"], None)
    result["exit_code"] = code
    reasons, backup_reasons = [], []
    if code != 0:
        reasons.append(f"wevtutil cl exited with code {code}: "
                       f"{(stderr or '').strip()[:events.STDERR_MAX] or 'no error text'}")

    read = {"status": "unreadable", "reason": "the backup file does not exist",
            **{k: None for k in FILE_FIELDS}}
    if backup.is_file():
        out = work / f"logs-{stamp}-{os.getpid()}.read-rest.json"
        read = read_json(run, "read:rest", file_script(backup, out), out, FILE_FIELDS)
        result["sha256"], hash_reason = _hash(backup)
        if hash_reason:
            backup_reasons.append(f"the backup file: {hash_reason}")
    result.update(backup_record_count=read["record_count"],
                  backup_min_record_id=read["min_record_id"],
                  backup_max_record_id=read["max_record_id"])
    if read["status"] != "read":
        backup_reasons.append(f"the backup file could not be read back: {read['reason']}")
    elif read["max_record_id"] is None or read["max_record_id"] < export_max:
        backup_reasons.append(f"the backup file ends at RecordId {read['max_record_id']}, before the "
                       f"verified export ({export_max})")

    out = work / f"logs-{stamp}-{os.getpid()}.after-{log}.json"
    after = read_json(run, f"after:{log}", state_script(log, out), out, STATE_FIELDS)
    result["record_count_after"] = after["record_count"]
    if after["status"] != "read":
        reasons.append(f"the log could not be read back after clearing: {after['reason']}")
    elif (read["status"] == "read" and read["record_count"] is not None
          and (after["record_count"] is None
               or after["record_count"] >= read["record_count"])):
        # The read-back must show the log emptied: fewer records than the backup
        # held (records written after clearing are allowed, a full log is not).
        reasons.append(f"the log still holds {after['record_count']} records after clearing, "
                       f"not fewer than the backup's {read['record_count']}")

    reasons += backup_reasons
    result.update(cleared=not reasons, reason="; ".join(reasons) or None)
    check = None
    if backup.is_file():
        check = {"read": read, "verified": not backup_reasons,
                 "reason": "; ".join(backup_reasons) or None}
    return result, check


def append_entry(path: Path, entry: dict) -> None:
    """Append one entry to the manifest as it is on disk now.

    Re-read right before writing, so a run that overlaps this one (an export
    takes minutes) keeps its entries. A manifest that became corrupt meanwhile
    raises dumps.ManifestError and is left as it is.
    """
    dumps.write_manifest(path, [*dumps.read_manifest(path), entry])


def emit(output: dict, code: int) -> int:
    print(json.dumps(output, ensure_ascii=True, indent=1))
    return code


def main(argv=None, run=None, is_admin=None, now=None) -> int:
    # Both inputs from the machine are injected together, so a test never
    # reaches the real one it forgot.
    if (run is None) != (is_admin is None):
        raise TypeError("inject both run and is_admin, or neither")
    parser = build_parser()
    args = parser.parse_args(argv)  # exit code 2 before anything runs
    run = run or default_run
    is_admin = is_admin or default_is_admin
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    data_dir = Path(args.data_dir).absolute()
    exports, work = data_dir / "exports", data_dir / "work"
    manifest_path = exports / dumps.MANIFEST
    log = args.export

    output = {"generated_at": iso(now), "log": log, "exports_dir": str(exports),
              "manifest": str(manifest_path), "clear_requested": args.clear,
              "export": None, "clear": None, "error": None}
    try:
        dumps.read_manifest(manifest_path)  # a corrupt manifest stops the run here
    except dumps.ManifestError as exc:
        output["error"] = f"{exc}; nothing was exported and the manifest was not changed"
        return emit(output, 1)
    try:
        exports.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        output["error"] = f"the output directories could not be created: {describe(exc)}"
        return emit(output, 1)

    result = export(run, log, exports, work, stamp)
    output["export"] = result
    if result["exit_code"] == 0 and Path(result["file"]).is_file():
        # Even an unverified file is recorded: epl succeeded, so this run wrote it.
        # After a failed epl the file may be another run's (same stamp), so it is
        # not recorded; the stdout result still names it.
        entry = _manifest_entry(log, "export", Path(result["file"]), result["sha256"],
                                result, result["verified"], result["reason"], now)
        try:
            append_entry(manifest_path, entry)
        except (OSError, dumps.ManifestError) as exc:
            output["error"] = (f"{manifest_path} could not be written: {describe(exc)}; "
                               "nothing was cleared")
            return emit(output, 1)
    if not result["verified"]:
        return emit(output, 1)
    if not args.clear:
        return emit(output, 0)

    if not is_admin():
        output["clear"] = {"log": log, "cleared": False, "reason": NEEDS_ELEVATION,
                           "record_count_after": None}
        print(f"logs.py: {NEEDS_ELEVATION}", file=sys.stderr)
        return emit(output, 1)

    cleared, backup = clear(run, log, exports, work, stamp, result["max_record_id"])
    output["clear"] = cleared
    if backup is not None:
        entry = _manifest_entry(log, "clear_backup", Path(cleared["file"]),
                                cleared["sha256"], backup["read"], backup["verified"],
                                backup["reason"], now)
        try:
            append_entry(manifest_path, entry)
        except (OSError, dumps.ManifestError) as exc:
            output["error"] = f"{manifest_path} could not be written: {describe(exc)}"
            return emit(output, 1)
    return emit(output, 0 if cleared["cleared"] else 1)


if __name__ == "__main__":
    sys.exit(main())

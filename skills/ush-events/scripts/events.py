"""Summarise the Windows System and Application event logs (read-only).

Collection runs PowerShell through an injectable ``run_ps`` (tests pass a
fake); PowerShell writes its result to a BOM-less UTF-8 file in the work
directory, never through stdout. The analysis is made of pure functions.
The summary contract is described in ``references/summary-contract.md``.

An event is a dict in the projection written by the PowerShell capture:
ProviderName (str), Id (int), Level (int), LogName (str), RecordId (int),
TimeCreated (ISO 8601 with offset, from ``TimeCreated.ToString('o')``),
Message (str), Properties (list of str).

The script counts; it never judges severity. Noise is classified only by the
data file ``data/noise.json``.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_NOISE_FILE = Path(__file__).absolute().parents[1] / "data" / "noise.json"

# Direction marks that Windows puts into localised text (e.g. pl-PL dates).
BIDI_MARKS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
_STRIP_BIDI = {ord(c): None for c in BIDI_MARKS}
SAMPLE_LENGTH = 200

# Events are matched by (provider, Id): other providers reuse the same Ids.
EVENTLOG = "EventLog"
KERNEL_POWER = "Microsoft-Windows-Kernel-Power"
WER_SYSTEM = "Microsoft-Windows-WER-SystemErrorReporting"
OS_START = ("Microsoft-Windows-Kernel-General", 12)
BOOT = (EVENTLOG, 6005)
OS_VERSION_AT_BOOT = (EVENTLOG, 6009)
# The markers every boot writes once each, in an order that varies.
BOOT_MARKERS = (OS_START, OS_VERSION_AT_BOOT, BOOT)
CLEAN_SHUTDOWN = (EVENTLOG, 6006)
UNEXPECTED_SHUTDOWN = (EVENTLOG, 6008)
KERNEL_POWER_41 = (KERNEL_POWER, 41)
SLEEP = (KERNEL_POWER, 506)
WAKE = (KERNEL_POWER, 507)
BUGCHECK = (WER_SYSTEM, 1001)


# --- loading -------------------------------------------------------------
def load_capture(path) -> list[dict]:
    """Read a capture file written by PowerShell.

    Accepts a file with or without a BOM. ConvertTo-Json writes a single
    object for one event, so an object becomes a one-element list. An empty
    file or ``null`` means no events. Any other shape raises ValueError.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    if not text.strip():
        return []
    data = json.loads(text)
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise ValueError(f"{path}: expected a JSON object or a list of objects")
    for ev in data:
        ev["Properties"] = _property_list(ev.get("Properties"))
    return data


def _property_list(value) -> list[str]:
    """Properties as a list of strings, whatever shape ConvertTo-Json gave them.

    PS 5.1 can write an array as {"value": [...], "Count": n}, a single value
    as a bare string and an empty array as {}.
    """
    if isinstance(value, dict):
        value = value.get("value", [])
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(v) for v in value]


PASS_B_ONLY = "_pass_b_only"


def merge(pass_a: list[dict], pass_b: list[dict]) -> list[dict]:
    """Union of both passes, deduplicated by (LogName, RecordId).

    RecordId is unique only within one log, so the pair is the address. An
    event without a RecordId is told apart by provider, Id and time instead,
    so such events are not collapsed into one.

    Events found only by pass B are marked PASS_B_ONLY: they feed boots and
    anomalies but never groups, so a pass A that could not be read does not
    look like a log with only these errors.
    """
    def address(ev):
        found = (ev.get("LogName"), ev.get("RecordId"))
        if ev.get("RecordId") is None:
            found += (ev.get("ProviderName"), ev.get("Id"), ev.get("TimeCreated"))
        return found

    merged: dict[tuple, dict] = {}
    for ev in pass_a:
        merged.setdefault(address(ev), ev)
    for ev in pass_b:
        if address(ev) not in merged:
            merged[address(ev)] = {**ev, PASS_B_ONLY: True}
    return list(merged.values())


def load_noise(path=None) -> list[dict]:
    """Load the known-noise list: a JSON list of {provider, event_id, reason}.

    A malformed entry raises ValueError naming the file: a broken list must
    not silently change what is reported.
    """
    path = DEFAULT_NOISE_FILE if path is None else Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        # ValueError like every other malformed-file case, so callers catch one type.
        raise ValueError(f"{path}: expected a JSON list of noise entries")  # noqa: TRY004
    entries = []
    for number, item in enumerate(data, 1):
        provider = item.get("provider") if isinstance(item, dict) else None
        event_id = item.get("event_id") if isinstance(item, dict) else None
        reason = item.get("reason") if isinstance(item, dict) else None
        if (
            not isinstance(provider, str) or not provider
            or isinstance(event_id, bool) or not isinstance(event_id, int)
            or not isinstance(reason, str) or not reason.strip()
        ):
            raise ValueError(
                f"{path}: entry {number} needs a non-empty provider, an integer "
                "event_id and a non-empty reason"
            )
        entries.append({"provider": provider, "event_id": event_id, "reason": reason})
    return entries


# --- helpers -------------------------------------------------------------
def event_time(ev: dict) -> datetime:
    """TimeCreated as an aware datetime in UTC. A time without offset is an error."""
    moment = datetime.fromisoformat(ev["TimeCreated"])
    if moment.tzinfo is None:
        raise ValueError(f"TimeCreated has no UTC offset: {ev['TimeCreated']!r}")
    return moment.astimezone(timezone.utc)


def iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def key(ev: dict) -> tuple:
    return (ev.get("ProviderName"), ev.get("Id"))


def shorten(message: str) -> str:
    """One-line sample: bidi marks removed, whitespace collapsed, about 200 chars.

    Cut at the last sentence end within the limit if that keeps at least half
    of it; otherwise cut at a word boundary and mark the cut with "...".
    """
    text = " ".join((message or "").translate(_STRIP_BIDI).split())
    if len(text) <= SAMPLE_LENGTH:
        return text
    head = text[: SAMPLE_LENGTH + 1]  # one more char to see a space after a full stop
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if end + 1 >= SAMPLE_LENGTH // 2:  # an early full stop would leave almost nothing
        return text[: end + 1]
    cut = text[: SAMPLE_LENGTH - 3].rsplit(" ", 1)[0]
    return cut + "..."


# --- analysis ------------------------------------------------------------
def analyze(events: list[dict], noise: list[dict]) -> dict:
    """Groups, known noise, boot sessions and anomalies of the merged events.

    Groups and noise come only from levels 1-3; level 4 events (boots, sleep)
    feed only the boot sessions and the anomalies. An event whose time cannot
    be read is left out of all of them and listed under "unreadable".
    """
    readable, unreadable = [], []
    for ev in events:
        try:
            readable.append((event_time(ev), ev))
        except (KeyError, TypeError, ValueError) as exc:
            unreadable.append({
                "log": ev.get("LogName"),
                "record_id": ev.get("RecordId"),
                "reason": f"TimeCreated: {exc}",
            })
    timed = sorted(
        readable,
        key=lambda pair: (pair[0], str(pair[1].get("LogName")), pair[1].get("RecordId") or 0),
    )
    groups, noise_items = _group(timed, noise)
    boots, boot_of = _boots(timed)
    return {
        "groups": groups,
        "noise": noise_items,
        "boots": boots,
        "anomalies": _anomalies(timed, boot_of),
        "unreadable": unreadable,
    }


def _group(timed: list[tuple], noise: list[dict]) -> tuple[list[dict], list[dict]]:
    """Groups by (log, provider, Id); known noise by (provider, Id) over both logs."""
    reasons = {(n["provider"], n["event_id"]): n["reason"] for n in noise}
    buckets: dict[tuple, dict] = {}
    noise_buckets: dict[tuple, dict] = {}
    for moment, ev in timed:  # sorted by time, so the last event wins "last"
        level = ev.get("Level")
        if ev.get(PASS_B_ONLY) or not isinstance(level, int) or not 1 <= level <= 3:
            continue
        if key(ev) in reasons:
            item = noise_buckets.setdefault(key(ev), {
                "provider": ev.get("ProviderName"),
                "event_id": ev.get("Id"),
                "count": 0,
                "reason": reasons[key(ev)],
                "first": iso(moment),
                "last": None,
            })
            item["count"] += 1
            item["last"] = iso(moment)
            continue
        bucket = buckets.get((ev.get("LogName"), *key(ev)))
        if bucket is None:
            buckets[(ev.get("LogName"), *key(ev))] = {
                "provider": ev.get("ProviderName"),
                "event_id": ev.get("Id"),
                "level": level,
                "log": ev.get("LogName"),
                "count": 1,
                "first": iso(moment),
                "last": iso(moment),
                "sample": shorten(ev.get("Message")),
            }
            continue
        bucket["count"] += 1
        bucket["last"] = iso(moment)
        bucket["level"] = min(bucket["level"], level)  # lower number = more severe

    def order(item):
        return (-item["count"], str(item["provider"]), item["event_id"] or 0,
                str(item.get("log")))

    return sorted(buckets.values(), key=order), sorted(noise_buckets.values(), key=order)


def _system_order(timed: list[tuple]) -> list[int]:
    """Indices of System events in RecordId order (the order of writing).

    Falls back to time order when a RecordId is missing.
    """
    system = [i for i, (_, ev) in enumerate(timed) if ev.get("LogName") == "System"]
    if all(isinstance(timed[i][1].get("RecordId"), int) for i in system):
        system.sort(key=lambda i: timed[i][1]["RecordId"])
    return system


def _boots(timed: list[tuple]) -> tuple[list[dict], list[int]]:
    """Boot sessions and the session of each event.

    Sessions are read from the System log in RecordId order, which is the
    order of writing and does not move when the clock is corrected at boot.
    Every boot writes Kernel-General 12 (the kernel start), EventLog 6009 and
    EventLog 6005 once each, but not always in that order: the event log may
    write 6009 and 6005 before the kernel's 12. So a marker opens a new
    session only when the current one already has a marker of its kind or
    was closed by 6006. Times are not compared: the kernel's clock may run
    ahead of the event log's. A boot that lost one of its markers may take a
    marker of the next boot: the edge of the session shifts, but no session
    is invented. The
    session starts at the earliest time among its markers. Kernel-Power 41 and EventLog 6008 of a crash are written in this
    block or after it, so they fall into the boot that reports the crash.
    Events of other logs join the most recent session that started at or
    before their time.

    Session 0 is the part of a session that started before the window; it
    exists only when events precede the first boot. clean_shutdown is True
    with an EventLog 6006 in the session, False without one before the next
    boot, and None for the last session, which may still be running.
    """
    system = _system_order(timed)

    boots: list[dict] = []
    starts: list[datetime] = []  # start moment of each session opened in the window
    boot_of: list[int | None] = [None] * len(timed)
    seen: set[tuple] = set()  # markers of the current session
    closed = True  # no session is open to join (none yet, or ended by 6006)
    for i in system:
        moment, ev = timed[i]
        marker = key(ev)
        if marker in BOOT_MARKERS:
            joins = not closed and marker not in seen
            if joins:
                seen.add(marker)
                if moment < starts[-1]:
                    boots[-1]["start"] = iso(moment)
                    starts[-1] = moment
            else:
                boots.append({"index": len(starts) + 1, "start": iso(moment), "end": None,
                              "clean_shutdown": None})
                starts.append(moment)
                seen = {marker}
                closed = False
        if marker == CLEAN_SHUTDOWN and boots:
            boots[-1]["end"] = iso(moment)
            boots[-1]["clean_shutdown"] = True
            closed = True
        boot_of[i] = len(starts)

    for i, (moment, _) in enumerate(timed):
        if boot_of[i] is None:
            # The most recent session that had started by then; starts need
            # not rise with the index when the clock was set back at boot.
            boot_of[i] = max((n for n, start in enumerate(starts, 1) if start <= moment),
                             default=0)
    if 0 in boot_of:
        # A 6006 before the first boot closed session 0; it was recorded on
        # no session above, so look for it again.
        end = next((iso(m) for i, (m, ev) in enumerate(timed)
                    if boot_of[i] == 0 and key(ev) == CLEAN_SHUTDOWN), None)
        boots.insert(0, {"index": 0, "start": None, "end": end,
                         "clean_shutdown": True if end else None})
    for boot in boots[:-1]:
        if boot["clean_shutdown"] is None:
            boot["clean_shutdown"] = False
    return boots, boot_of


def _anomalies(timed: list[tuple], boot_of: list[int]) -> list[dict]:
    found = []
    system = _system_order(timed)
    position = {i: n for n, i in enumerate(system)}
    for i, (moment, ev) in enumerate(timed):
        common = {
            "time": iso(moment),
            "boot": boot_of[i],
            "log": ev.get("LogName"),
            "record_id": ev.get("RecordId"),
        }
        if key(ev) == BUGCHECK:
            raw = _first_property(ev)
            found.append({"kind": "bugcheck", **common,
                          "bugcheck_code": _bugcheck_code(raw), "bugcheck_raw": raw})
        elif key(ev) == UNEXPECTED_SHUTDOWN:
            found.append({"kind": "unexpected_shutdown", **common})
        elif key(ev) == KERNEL_POWER_41:
            found.append({"kind": "kernel_power_41", **common})
        elif key(ev) == SLEEP and _sleep_without_wake(timed, boot_of, system,
                                                      position.get(i)):
            found.append({"kind": "sleep_without_wake", **common})
    return found


def _sleep_without_wake(timed: list[tuple], boot_of: list[int], system: list[int],
                        at: int | None) -> bool:
    """A 506 with no 507 before the next 506 or the next boot.

    A clean shutdown (6006) after the 506 counts as a wake: the system shut
    down normally, so the sleep ended.

    The System log is walked in RecordId order, as sessions are, so a clock
    set back at boot cannot put the next boot before this sleep's wake. A 506
    with nothing of that kind after it in the window is not counted: its wake
    may not have been written yet.
    """
    if at is None:
        return False
    i = system[at]
    for j in system[at + 1:]:
        if boot_of[j] != boot_of[i]:
            return True
        following = key(timed[j][1])
        if following in (WAKE, CLEAN_SHUTDOWN):
            return False
        if following == SLEEP:
            return True
    return False


def _first_property(ev: dict) -> str | None:
    props = ev.get("Properties") or []
    return str(props[0]).strip() if props else None


def _bugcheck_code(raw: str | None) -> str | None:
    """The bugcheck code is the first token of Properties[0], e.g. "0x0000019c".

    Taken from Properties, never from the localised Message.
    """
    token = raw.split()[0] if raw and raw.split() else ""
    return token if token.lower().startswith("0x") else None


# --- collection ----------------------------------------------------------
SCHEMA_VERSION = 1
SKILL = "ush-events"
LOGS = ("System", "Application")
# Pass B: boots, shutdowns, sleep and crashes. Most are level 4, which the
# level 1-3 filter of pass A drops.
PASS_B_IDS = (12, 41, 506, 507, 1001, 6005, 6006, 6008, 6009)
NO_MATCH = "NoMatchingEventsFound"
SUMMARY_MAX_CHARS = 35000
STDERR_MAX = 1000
PS_TIMEOUT = 300  # seconds; a pass that runs longer is wedged, not slow

# The M2 projection, built object by object. A calculated property in
# Select-Object makes ConvertTo-Json (PS 5.1) write an array as
# {"value": [...], "Count": n}, one value as a bare string and none as {};
# a [string[]] field of a [pscustomobject] is written as a plain list.
PROJECTION = """@(foreach ($e in $ev) { [pscustomobject]@{
  ProviderName = $e.ProviderName; Id = $e.Id; Level = $e.Level; LogName = $e.LogName
  RecordId = $e.RecordId; TimeCreated = $(if ($e.TimeCreated) { $e.TimeCreated.ToString('o') } else { $null }); Message = [string]$e.Message
  Properties = [string[]]@(foreach ($p in $e.Properties) { [string]$p.Value })
} })"""

# Data goes through a file written by WriteAllText without a BOM; stdout of
# powershell.exe uses the console code page. stderr is switched to UTF-8 so
# the reason of a failure arrives readable.
PS_TEMPLATE = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ev = {query}
$proj = {projection}
$json = ConvertTo-Json -InputObject $proj -Compress -Depth 4
[System.IO.File]::WriteAllText('{path}', $json, [System.Text.UTF8Encoding]::new($false))
"""


def ps_quote(text: str) -> str:
    """A PowerShell single-quoted string literal."""
    return "'" + str(text).replace("'", "''") + "'"


def ps_script(query: str, out_path: Path) -> str:
    return PS_TEMPLATE.format(query=query, projection=PROJECTION, path=str(out_path).replace("'", "''"))


def pass_a_query(log: str, start: datetime) -> str:
    return (f"Get-WinEvent -FilterHashtable @{{LogName={ps_quote(log)}; Level=1,2,3; "
            f"StartTime=[datetime]{ps_quote(_ps_time(start))}}} -ErrorAction Stop")


def pass_b_query(start: datetime) -> str:
    ids = ",".join(str(i) for i in PASS_B_IDS)
    return (f"Get-WinEvent -FilterHashtable @{{LogName='System'; Id={ids}; "
            f"StartTime=[datetime]{ps_quote(_ps_time(start))}}} -ErrorAction Stop")


def oldest_query(log: str) -> str:
    return f"Get-WinEvent -LogName {ps_quote(log)} -MaxEvents 1 -Oldest -ErrorAction Stop"


def _ps_time(moment: datetime) -> str:
    """UTC with a Z: [datetime] parses it culture-independently to local time."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_run_ps(job: str, script: str, out_path: Path) -> tuple[int, str]:
    """Run one script in Windows PowerShell 5.1; return (exit code, stderr).

    The script is a fixed template; nothing from the event log reaches the
    command line. Data comes back only through the file at out_path.
    """
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,  # a non-zero exit is data here
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 1, f"{job}: PowerShell did not finish within {PS_TIMEOUT} s and was stopped"
    except OSError as exc:
        return 1, f"{job}: powershell.exe could not be started: {type(exc).__name__}: {exc}"
    return result.returncode, result.stderr or ""


def run_job(run_ps, job: str, script: str, out_path: Path) -> dict:
    """One capture job: {status: read|empty|unreadable, reason, events}.

    A stale out_path is deleted first, and the file is never read after a
    non-zero exit, so a leftover from an earlier run cannot pass for data.
    """
    try:
        out_path.unlink(missing_ok=True)
    except OSError as exc:
        return _unreadable(f"could not remove the old output file: {type(exc).__name__}: {exc}")
    code, stderr = run_ps(job, script, out_path)
    stderr = (stderr or "").strip()
    if code != 0:
        if NO_MATCH in stderr:
            return {"status": "empty", "reason": None, "events": []}
        return _unreadable(stderr[:STDERR_MAX] or f"PowerShell exit code {code} without an error text")
    if not out_path.is_file():
        return _unreadable("PowerShell exited 0 but wrote no output file")
    try:
        events = load_capture(out_path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return _unreadable(f"the output file could not be read: {type(exc).__name__}: {exc}")
    if not events:
        return {"status": "empty", "reason": None, "events": []}
    return {"status": "read", "reason": None, "events": events}


def _unreadable(reason: str) -> dict:
    return {"status": "unreadable", "reason": reason, "events": []}


def collect(run_ps, work: Path, stamp: str, start: datetime,
            now: datetime) -> tuple[list[dict], dict, list[dict]]:
    """Run all jobs. Returns (sources, {pass: events}, not_checked)."""
    work.mkdir(parents=True, exist_ok=True)

    def job(name: str, query: str) -> dict:
        out_path = work / f"events-{stamp}.{name.replace(':', '-')}.json"
        return run_job(run_ps, name, ps_script(query, out_path), out_path)

    oldest, oldest_status, not_checked = {}, {}, []
    for log in LOGS:
        found = job(f"oldest:{log}", oldest_query(log))
        oldest[log] = None
        oldest_status[log] = found["status"]
        if found["status"] == "unreadable":
            not_checked.append({"what": f"{log} log: time of its oldest record",
                                "reason": found["reason"]})
        for ev in found["events"][:1]:
            try:
                oldest[log] = event_time(ev)
            except (KeyError, TypeError, ValueError) as exc:
                not_checked.append({"what": f"{log} log: time of its oldest record",
                                    "reason": f"TimeCreated: {exc}"})

    passes = [(log, "A", f"A:{log}", pass_a_query(log, start)) for log in LOGS]
    passes.append(("System", "B", "B:System", pass_b_query(start)))
    results = [(log, pass_, job(name, query)) for log, pass_, name, query in passes]

    # A log found empty may have received events before the passes ran: then
    # the earliest event read is the best known start of its records.
    for log in LOGS:
        if oldest_status[log] != "empty":
            continue
        times = []
        for ev in (ev for lg, _, found in results if lg == log for ev in found["events"]):
            try:
                times.append(event_time(ev))
            except (KeyError, TypeError, ValueError):
                pass
        if times:
            oldest[log] = min(times)
            oldest_status[log] = "read"

    def coverage(log: str) -> datetime | None:
        if oldest_status[log] == "empty":
            return now  # an empty log covers nothing of the window
        if oldest[log] is not None and oldest[log] > start:
            return oldest[log]
        return None

    descriptions = {"A": "levels 1-3", "B": "boot, shutdown, sleep and crash events"}
    sources, events = [], {"A": [], "B": []}
    for log, pass_, found in results:
        sources.append({
            "log": log,
            "pass": pass_,
            "status": found["status"],
            "reason": found["reason"],
            "event_count": len(found["events"]),
            "log_oldest_record": iso(oldest[log]),
            "coverage_start": iso(coverage(log)),
        })
        events[pass_].extend(found["events"])
        if found["status"] == "unreadable":
            not_checked.append({"what": f"{log} log, pass {pass_} ({descriptions[pass_]})",
                                "reason": found["reason"]})

    for log in LOGS:
        if oldest_status[log] == "empty":
            not_checked.append({
                "what": f"{log} log: holds no records at all",
                "reason": "the log is empty (cleared, nothing written since), so events "
                          "in the whole window are unknown",
                "from": iso(start),
                "to": iso(now),
            })
        elif coverage(log) is not None:
            not_checked.append({
                "what": f"{log} log before its oldest record",
                "reason": "the log holds no records before this time (cleared or "
                          "overwritten), so events in this span are unknown",
                "from": iso(start),
                "to": iso(oldest[log]),
            })
    return sources, events, not_checked


# --- summary -------------------------------------------------------------
def with_ids(items: list[dict], prefix: str) -> list[dict]:
    return [{"id": f"{prefix}{n}", **item} for n, item in enumerate(items, 1)]


def dump(data) -> str:
    """Compact ASCII JSON: safe on any console code page."""
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


def fit_budget(summary: dict, limit: int = SUMMARY_MAX_CHARS) -> str:
    """Cut groups from the end until the summary fits; never anything else.

    Groups are ordered by count, so the rarest go first. ``truncated`` says
    how many were cut; the full list stays in the detail file.
    """
    groups = summary["groups"]
    text = dump(summary)
    if len(text) <= limit:
        return text
    # Estimate how many groups fit, then correct one group at a time.
    base = len(dump({**summary, "groups": [], "truncated": len(groups)}))
    keep, size = 0, base
    for group in groups:
        size += len(dump(group)) + 1
        if size > limit:
            break
        keep += 1
    while True:
        summary["groups"] = groups[:keep]
        summary["truncated"] = len(groups) - keep
        text = dump(summary)
        if len(text) <= limit or keep == 0:
            return text
        keep -= 1


def build_summary(now, days, sources, analysis, not_checked, summary_file, detail_file):
    start = now - timedelta(days=days)
    unreadable = analysis["unreadable"]
    if unreadable:
        not_checked = not_checked + [{
            "what": f"{len(unreadable)} events whose time could not be read",
            "reason": "TimeCreated missing or without a UTC offset; they are left out of "
                      "every section and listed under 'unreadable' in the detail file",
        }]
    boots = [{"id": f"b{boot['index']}", **boot} for boot in analysis["boots"]]
    anomalies = with_ids(analysis["anomalies"], "a")
    if any(src["pass"] == "B" and src["status"] == "unreadable" for src in sources):
        # Without pass B the boot sessions are unknown, not "none".
        boots = None
        anomalies = [{**item, "boot": None} for item in anomalies]
    return {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": iso(now),
        "window": {"start": iso(start), "end": iso(now), "days": days},
        "sources": sources,
        "groups": with_ids(analysis["groups"], "g"),
        "noise": with_ids(analysis["noise"], "n"),
        "boots": boots,
        "anomalies": anomalies,
        "not_checked": not_checked,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": 0,
    }


# --- command line --------------------------------------------------------
DETAIL_SECTIONS = ("groups", "noise", "boots", "anomalies")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="events.py",
        description=(
            "Read the System and Application event logs without elevation and "
            "write a JSON summary plus a detail file. Read-only."
        ),
    )
    parser.add_argument("--data-dir", default="ush-data",
                        help="output directory, relative to the working directory "
                             "(default: ush-data)")
    parser.add_argument("--days", type=_positive_int, default=30,
                        help="how many days back to read (default: 30)")
    parser.add_argument("--detail", metavar="ID",
                        help="print one item (e.g. g1, a2, b3) from the newest detail "
                             "file instead of collecting")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    return parser


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("events-*.detail.json"), key=lambda p: p.name)
        if not files:
            print(f"no detail file in {work}; run the collection first", file=sys.stderr)
            return 1
        newest = files[-1]
    try:
        detail = json.loads(newest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"{newest} could not be read: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for section in DETAIL_SECTIONS:
        for item in detail.get(section) or []:
            if isinstance(item, dict) and item.get("id") == item_id:
                print(json.dumps(item, ensure_ascii=True, indent=1))
                return 0
    print(f"id {item_id!r} not found in {newest}", file=sys.stderr)
    return 1


def main(argv=None, run_ps=None, now=None) -> int:
    args = build_parser().parse_args(argv)
    work = Path(args.data_dir).absolute() / "work"
    if args.detail is not None:
        detail_file = Path(args.detail_file).absolute() if args.detail_file else None
        return show_detail(work, args.detail, detail_file)

    try:
        noise = load_noise()
    except (OSError, ValueError) as exc:
        print(f"the known-noise list could not be read: {exc}", file=sys.stderr)
        return 1
    run_ps = run_ps or default_run_ps
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = now - timedelta(days=args.days)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    summary_file = work / f"events-{stamp}.summary.json"
    detail_file = work / f"events-{stamp}.detail.json"

    sources, events, not_checked = collect(run_ps, work, stamp, start, now)
    analysis = analyze(merge(events["A"], events["B"]), noise)
    summary = build_summary(now, args.days, sources, analysis, not_checked,
                            summary_file, detail_file)
    detail = {key: summary[key] for key in (
        "schema_version", "skill", "generated_at", "window", "sources", *DETAIL_SECTIONS)}
    detail["unreadable"] = analysis["unreadable"]
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    text = fit_budget(summary)
    summary_file.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

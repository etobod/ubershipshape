"""Summarise the Windows System and Application event logs (read-only).

Collection runs PowerShell through an injectable ``run_ps`` (tests pass a
fake); PowerShell writes its result to a BOM-less UTF-8 file in the work
directory, never through stdout. The analysis is made of pure functions.
The summary contract is described in ``references/summary-contract.md``.

An event is a dict in the projection written by the PowerShell capture:
ProviderName (str), Id (int), Level (int), LogName (str), RecordId (int),
TimeCreated (ISO 8601 with offset, from ``TimeCreated.ToString('o')``),
Message (str), Properties (list of str).

The Reliability Monitor is read through WMI (``Get-CimInstance``) in two
separate jobs, ``R:metrics`` and ``R:records``, each with its own projection
and status; their rows are filtered to the window in Python.

Memory dumps are listed through an injectable ``read_dumps`` (``dumpfiles``:
the CrashControl registry values and the ``*.dmp`` files, never opened for
more than a readability test) and linked to bugchecks by path only.

The script counts; it never judges severity. Noise is classified only by the
data file ``data/noise.json``, the per-group trend only by ``data/trend.json``.
"""

import argparse
import itertools
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# load_script does not put this directory on sys.path; dumpfiles lives next to this file.
sys.path.insert(0, str(Path(__file__).absolute().parent))

import dumpfiles
from dumpfiles import iso

DEFAULT_NOISE_FILE = Path(__file__).absolute().parents[1] / "data" / "noise.json"
DEFAULT_TREND_FILE = Path(__file__).absolute().parents[1] / "data" / "trend.json"
TREND_KEYS = ("min_count", "factor", "min_delta")

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
EVENTLOG_START = (OS_VERSION_AT_BOOT, BOOT)  # the event log block of a boot
# Kernel-Boot 27: the boot type is Properties[0]. Types 0 (cold) and 1 (hybrid,
# Fast Startup) are a boot marker of their own; 2 (resume from hibernation) is not.
# A hybrid boot writes only its 27 of type 1, none of BOOT_MARKERS, so a session
# it opened takes no BOOT_MARKERS: they belong to the next boot.
KERNEL_BOOT = ("Microsoft-Windows-Kernel-Boot", 27)
BOOT_TYPES = {"0": "cold", "1": "fast_startup"}
HIBERNATE_RESUME = "2"
# Kernel-Boot 20: a cold boot writes the success of the last shutdown in
# Properties[0] ("True" or "False") after its Kernel-General 12. A Fast
# Startup or hibernate shutdown writes no 6006, but its status is "True".
LAST_SHUTDOWN = ("Microsoft-Windows-Kernel-Boot", 20)
CLEAN_SHUTDOWN = (EVENTLOG, 6006)
UNEXPECTED_SHUTDOWN = (EVENTLOG, 6008)
KERNEL_POWER_41 = (KERNEL_POWER, 41)
SLEEP = (KERNEL_POWER, 506)
WAKE = (KERNEL_POWER, 507)
BUGCHECK = (WER_SYSTEM, 1001)


# --- loading -------------------------------------------------------------
def load_rows(path) -> list[dict]:
    """Read a result file written by PowerShell as a list of objects.

    Accepts a file with or without a BOM. ConvertTo-Json writes a single
    object for one row, so an object becomes a one-element list. An empty
    file or ``null`` means no rows. Any other shape raises ValueError.
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
    return data


def load_capture(path) -> list[dict]:
    """Read an event capture file (see ``load_rows``); Properties become a list of str."""
    data = load_rows(path)
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


def load_trend(path=None) -> dict:
    """Load the trend rule: {min_count, factor, min_delta, reason}.

    Each threshold must be a finite, non-negative number and ``reason`` a
    non-empty string; anything else raises ValueError naming the file, so a
    broken rule never silently changes what is reported.
    """
    path = DEFAULT_TREND_FILE if path is None else Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        # ValueError like every other malformed-file case, so callers catch one type.
        raise ValueError(f"{path}: expected a JSON object with the trend rule")  # noqa: TRY004
    rule = {}
    for name in TREND_KEYS:
        value = data.get(name)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError(f"{path}: {name!r} must be a non-negative number")
        rule[name] = value
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"{path}: 'reason' must be a non-empty string")
    rule["reason"] = reason
    return rule


# --- helpers -------------------------------------------------------------
def event_time(ev: dict) -> datetime:
    """TimeCreated as an aware datetime in UTC. A time without offset is an error."""
    moment = datetime.fromisoformat(ev["TimeCreated"])
    if moment.tzinfo is None:
        raise ValueError(f"TimeCreated has no UTC offset: {ev['TimeCreated']!r}")
    return moment.astimezone(timezone.utc)


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
def analyze(events: list[dict], noise: list[dict], window=None, coverage=None,
            trend_rule=None) -> dict:
    """Groups, known noise, boot sessions and anomalies of the merged events.

    Groups and noise come only from levels 1-3; level 4 events (boots, sleep)
    feed only the boot sessions and the anomalies. An event whose time cannot
    be read is left out of all of them and listed under "unreadable".

    With ``window`` (a (start, end) pair) each group also gets its trend; see
    ``_group``. ``coverage`` maps a log to its ``coverage_start``, or to any
    other non-None value when its coverage is unknown (None: covers the window);
    ``trend_rule`` is the loaded ``data/trend.json``.
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
    groups, noise_items = _group(timed, noise, window, coverage, trend_rule)
    boots, boot_of, unread_types, uncertain = _boots(timed)
    return {
        "groups": groups,
        "noise": noise_items,
        "boots": boots,
        "anomalies": _anomalies(timed, boot_of),
        "unreadable": unreadable,
        "unread_boot_types": unread_types,
        "uncertain_boots": uncertain,
    }


def _group(timed: list[tuple], noise: list[dict], window=None, coverage=None,
           trend_rule=None) -> tuple[list[dict], list[dict]]:
    """Groups by (log, provider, Id); known noise by (provider, Id) over both logs.

    With ``window`` every group also gets ``first_half``/``second_half`` (events
    before / at or after the window's midpoint) and ``trend`` (see ``trend``).
    Without it no trend field is added.
    """
    if window is not None and trend_rule is None:
        raise ValueError("a trend needs the trend rule (data/trend.json)")
    midpoint = window[0] + (window[1] - window[0]) / 2 if window is not None else None
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
            bucket = buckets[(ev.get("LogName"), *key(ev))] = {
                "provider": ev.get("ProviderName"),
                "event_id": ev.get("Id"),
                "level": level,
                "log": ev.get("LogName"),
                "count": 1,
                "first": iso(moment),
                "last": iso(moment),
                "sample": shorten(ev.get("Message")),
            }
            if midpoint is not None:
                bucket["first_half"] = bucket["second_half"] = 0
        else:
            bucket["count"] += 1
            bucket["last"] = iso(moment)
            bucket["level"] = min(bucket["level"], level)  # lower number = more severe
        if midpoint is not None:
            bucket["first_half" if moment < midpoint else "second_half"] += 1

    if midpoint is not None:
        coverage = coverage or {}
        for bucket in buckets.values():
            bucket["trend"] = trend(bucket, coverage.get(bucket["log"]) is not None, trend_rule)

    def order(item):
        return (-item["count"], str(item["provider"]), item["event_id"] or 0,
                str(item.get("log")))

    return sorted(buckets.values(), key=order), sorted(noise_buckets.values(), key=order)


def trend(group: dict, partial: bool, rule: dict) -> str:
    """The first matching rule of ``data/trend.json`` for one group.

    unknown (the log does not cover the whole window, so the halves are not
    comparable), too_few (count < min_count), rising (second half >= factor x
    first half and at least min_delta more), falling (the same with the halves
    swapped), otherwise stable.
    """
    first, second = group["first_half"], group["second_half"]
    if partial:
        return "unknown"
    if group["count"] < rule["min_count"]:
        return "too_few"
    if second >= rule["factor"] * first and second - first >= rule["min_delta"]:
        return "rising"
    if first >= rule["factor"] * second and first - second >= rule["min_delta"]:
        return "falling"
    return "stable"


def _system_order(timed: list[tuple]) -> list[int]:
    """Indices of System events in RecordId order (the order of writing).

    Falls back to time order when a RecordId is missing.
    """
    system = [i for i, (_, ev) in enumerate(timed) if ev.get("LogName") == "System"]
    if all(isinstance(timed[i][1].get("RecordId"), int) for i in system):
        system.sort(key=lambda i: timed[i][1]["RecordId"])
    return system


def _boots(timed: list[tuple]) -> tuple[list[dict], list[int], int, list[int]]:
    """Boot sessions, the session of each event, the number of unread boot types
    and the indexes of sessions whose boundary is uncertain.

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
    session starts at the earliest time among its markers. Kernel-Power 41
    of a crash is written after the markers of the boot that reports it. An
    EventLog 6008 comes with that boot's event log block, before or after
    its markers, so it joins the session of the System event right after
    it when that is an EventLog 6009 or 6005, and otherwise the session it
    was read in. Both fall into the boot that reports the crash.
    Events of other logs join the most recent session that started at or
    before their time.

    Session 0 is the part of a session that started before the window; it
    exists only when events precede the first boot. clean_shutdown is True
    with an EventLog 6006 in the session, False without one when a next
    boot follows that is not Fast Startup, also when that boot wrote no
    Kernel-Boot 27 at all. It is None for the last session, which may still
    be running, for a session followed by a Fast Startup boot (that shutdown
    hibernates the kernel and writes no 6006, so it is unknown), and for a
    session followed by a boot whose only 27 had no readable type (it may
    have been Fast Startup), and for a session followed by a boot whose
    first Kernel-Boot 20 says the last shutdown succeeded ("True") and that
    holds no EventLog 6008 or Kernel-Power 41: a Fast Startup or hibernate
    shutdown after which the boot was cold. A crash (an EventLog 6008 or
    Kernel-Power 41 in the following session) keeps False whatever its
    status or boot type says.

    Kernel-Boot 27 of type 0 (cold) or 1 (Fast Startup) is a marker of its
    own kind under the same rule; the first one in a session sets its
    boot_type ("cold", "fast_startup", or None without one, always for
    session 0). Type 2, a resume from hibernation, only adds to the
    hibernate_resumes of the current session (session 0 before the first
    boot). A 27 without a readable type is not a marker and is counted, so
    the summary can say what it could not read; it only marks a session as
    having an unread boot type: the next one to open (the first boot too,
    which leaves session 0's shutdown unknown) and, while the current one is open and has no type yet, that
    one too, since the 27 may be its own.

    A session opened by a Kernel-Boot 27 of type 1 (it was the first marker)
    takes no Kernel-General 12, EventLog 6009 or 6005: a Fast Startup boot
    writes only its 27, so such a marker is the next boot's and opens a new
    session, with that boot's crash events. A session opened by 12, 6009 or
    6005 still takes a later 27 of type 1 and the other markers. Such a
    session had no typed 27 of its own when the 27 of type 1 joined it, so
    that 27 may have been a separate hybrid boot: its index is returned as
    uncertain, and the sessions are not split.
    """
    system = _system_order(timed)

    boots: list[dict] = []
    starts: list[datetime] = []  # start moment of each session opened in the window
    boot_of: list[int | None] = [None] * len(timed)
    seen: set[tuple] = set()  # markers of the current session
    closed = True  # no session is open to join (none yet, or ended by 6006)
    hybrid = False  # the current session was opened by a 27 of type 1
    resumes_before_first = 0  # hibernation resumes before the first boot: session 0
    unread: set[int] = set()  # Kernel-Boot 27 without a readable type: in no session
    unread_pending = False  # such a 27 seen for the next session to open
    uncertain: list[int] = []  # sessions a 27 of type 1 joined while untyped
    pending_6008: tuple[int, int] | None = None  # (event, session) of a 6008 not yet placed
    for i in system:
        moment, ev = timed[i]
        marker = key(ev)
        boot_type = None
        if marker == KERNEL_BOOT:
            kind = _first_property(ev)
            if kind == HIBERNATE_RESUME:
                if boots:
                    boots[-1]["hibernate_resumes"] += 1
                else:
                    resumes_before_first += 1
            elif kind not in BOOT_TYPES:
                unread.add(i)
                # While the current session is open and untyped the 27 may be
                # its own (written after its markers) or the next boot's
                # (written before them): mark both. After a 6006 or a typed
                # 27 it belongs to the next boot only.
                if boots and not closed and boots[-1]["boot_type"] is None:
                    boots[-1]["unread_type"] = True  # internal; removed below
                unread_pending = True
            boot_type = BOOT_TYPES.get(kind)
        if marker in BOOT_MARKERS or boot_type:
            joins = (not closed and marker not in seen
                     and not (hybrid and marker in BOOT_MARKERS))
            if joins:
                if boot_type == "fast_startup" and boots[-1]["boot_type"] is None:
                    uncertain.append(boots[-1]["index"])
                seen.add(marker)
                if moment < starts[-1]:
                    boots[-1]["start"] = iso(moment)
                    starts[-1] = moment
            else:
                boots.append({"index": len(starts) + 1, "start": iso(moment), "end": None,
                              "clean_shutdown": None, "boot_type": None,
                              "hibernate_resumes": 0})
                starts.append(moment)
                seen = {marker}
                closed = False
                hybrid = boot_type == "fast_startup"
                if unread_pending:
                    boots[-1]["unread_type"] = True
                    unread_pending = False
            if boot_type and boots[-1]["boot_type"] is None:
                boots[-1]["boot_type"] = boot_type
        if marker == CLEAN_SHUTDOWN and boots:
            boots[-1]["end"] = iso(moment)
            boots[-1]["clean_shutdown"] = True
            closed = True
        # Internal fields for the rule below; removed before returning.
        if marker == LAST_SHUTDOWN and boots and "last_shutdown" not in boots[-1]:
            boots[-1]["last_shutdown"] = _first_property(ev)
        boot_of[i] = len(starts)
        # A 6008 is written in the event log block of the boot that reports
        # the crash. Right before that boot's 6009 or 6005 it belongs to
        # their session; otherwise to the session it was read in.
        if pending_6008 is not None:
            index, session = pending_6008
            if marker in EVENTLOG_START:
                session = len(starts)
            boot_of[index] = session
            if session:
                boots[session - 1]["crash"] = True
            pending_6008 = None
        if marker == UNEXPECTED_SHUTDOWN:
            pending_6008 = (i, len(starts))
        elif marker == KERNEL_POWER_41 and boots:
            boots[-1]["crash"] = True
    if pending_6008 is not None and pending_6008[1]:
        boots[pending_6008[1] - 1]["crash"] = True

    for i, (moment, _) in enumerate(timed):
        if boot_of[i] is None:
            # The most recent session that had started by then; starts need
            # not rise with the index when the clock was set back at boot.
            boot_of[i] = max((n for n, start in enumerate(starts, 1) if start <= moment),
                             default=0)
    if any(n == 0 for i, n in enumerate(boot_of) if i not in unread):
        # A 6006 before the first boot closed session 0; it was recorded on
        # no session above, so look for it again.
        end = next((iso(m) for i, (m, ev) in enumerate(timed)
                    if boot_of[i] == 0 and key(ev) == CLEAN_SHUTDOWN), None)
        boots.insert(0, {"index": 0, "start": None, "end": end,
                         "clean_shutdown": True if end else None, "boot_type": None,
                         "hibernate_resumes": resumes_before_first})
    for boot, following in itertools.pairwise(boots):
        unknown_type = following["boot_type"] is None and following.get("unread_type")
        succeeded = (str(following.get("last_shutdown")).lower() == "true"
                     and not following.get("crash"))
        # A 6008 or 41 proves the crash even when a joined 27 typed the
        # following session Fast Startup.
        if boot["clean_shutdown"] is None and (following.get("crash") or (
                following["boot_type"] != "fast_startup"
                and not unknown_type and not succeeded)):
            boot["clean_shutdown"] = False
    for boot in boots:
        for field in ("unread_type", "last_shutdown", "crash"):
            boot.pop(field, None)
    return boots, boot_of, len(unread), uncertain


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
                          "bugcheck_code": _bugcheck_code(raw), "bugcheck_raw": raw,
                          "dump_path": _dump_path(ev), "dump": None})
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


def _dump_path(ev: dict) -> str | None:
    """WER 1001 writes the full path of the dump it saved in Properties[1]."""
    props = ev.get("Properties") or []
    path = str(props[1]).strip() if len(props) > 1 else ""
    return path or None


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
PASS_B_IDS = (12, 20, 27, 41, 506, 507, 1001, 6005, 6006, 6008, 6009)
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


# Reliability Monitor (WMI, no elevation needed). Times are written in UTC; a
# missing index stays null ([double]$null would be 0, an invented reading).
METRICS_PROJECTION = """@(foreach ($m in $ev) { [pscustomobject]@{
  TimeGenerated = $(if ($m.TimeGenerated) { $m.TimeGenerated.ToUniversalTime().ToString('o') } else { $null })
  SystemStabilityIndex = $(if ($null -ne $m.SystemStabilityIndex) { [double]$m.SystemStabilityIndex } else { $null })
} })"""
RECORDS_PROJECTION = """@(foreach ($r in $ev) { [pscustomobject]@{
  TimeGenerated = $(if ($r.TimeGenerated) { $r.TimeGenerated.ToUniversalTime().ToString('o') } else { $null })
  SourceName = $r.SourceName; EventIdentifier = $r.EventIdentifier; ProductName = $r.ProductName
} })"""
METRICS_JOB = "R:metrics"
RECORDS_JOB = "R:records"


def ps_script(query: str, out_path: Path, projection: str = PROJECTION) -> str:
    return PS_TEMPLATE.format(query=query, projection=projection,
                              path=str(out_path).replace("'", "''"))


def metrics_query() -> str:
    return "Get-CimInstance Win32_ReliabilityStabilityMetrics -ErrorAction Stop"


def records_query() -> str:
    return "Get-CimInstance Win32_ReliabilityRecords -ErrorAction Stop"


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


def run_job(run_ps, job: str, script: str, out_path: Path, load=load_capture) -> dict:
    """One capture job: {status: read|empty|unreadable, reason, events}.

    ``events`` holds the rows ``load`` read from the result file. A stale
    out_path is deleted first, and the file is never read after a non-zero
    exit, so a leftover from an earlier run cannot pass for data.
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
        events = load(out_path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return _unreadable(f"the output file could not be read: {type(exc).__name__}: {exc}")
    if not events:
        return {"status": "empty", "reason": None, "events": []}
    return {"status": "read", "reason": None, "events": events}


def _unreadable(reason: str) -> dict:
    return {"status": "unreadable", "reason": reason, "events": []}


def collect(run_ps, work: Path, stamp: str, start: datetime,
            now: datetime) -> tuple[list[dict], dict, list[dict]]:
    """Run all jobs. Returns (sources, {pass: events}, not_checked).

    The second item also holds, under "reliability", the two Reliability
    Monitor jobs as {"metrics": job result, "records": job result}; their
    rows are not filtered to the window here (``reliability_summary`` does).
    Under "oldest_unreadable" it lists the logs whose oldest record could
    not be read.
    """
    work.mkdir(parents=True, exist_ok=True)

    def job(name: str, query: str, projection: str = PROJECTION, load=load_capture) -> dict:
        out_path = work / f"events-{stamp}.{name.replace(':', '-')}.json"
        return run_job(run_ps, name, ps_script(query, out_path, projection), out_path, load)

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
                oldest_status[log] = "unreadable"  # read, but its time is unknown
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

    # Reliability Monitor: two separate jobs with separate statuses.
    wmi = (("metrics", METRICS_JOB, metrics_query(), METRICS_PROJECTION,
            "Reliability Monitor: daily stability index (Win32_ReliabilityStabilityMetrics)"),
           ("records", RECORDS_JOB, records_query(), RECORDS_PROJECTION,
            "Reliability Monitor: reliability records (Win32_ReliabilityRecords)"))
    events["reliability"] = {}
    for part, name, query, projection, what in wmi:
        found = job(name, query, projection, load_rows)
        events["reliability"][part] = found
        if found["status"] == "unreadable":
            not_checked.append({"what": what, "reason": found["reason"]})
    # Logs whose oldest record could not be read: their coverage is unknown.
    events["oldest_unreadable"] = [log for log in LOGS if oldest_status[log] == "unreadable"]
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
    how many were cut; the full list stays in the detail file. When the
    summary does not fit even with every group cut, ``not_checked`` says so.
    """
    groups = summary["groups"]
    text = dump(summary)
    if len(text) <= limit:
        return text
    # Estimate how many groups fit, then correct one group at a time.
    base = len(dump({**summary, "groups": [], "truncated": len(groups)}))
    if base > limit:
        summary["groups"] = []
        summary["truncated"] = len(groups)
        summary["not_checked"] = summary["not_checked"] + [{
            "what": f"summary over its size limit of {limit} characters",
            "reason": "all groups were cut and the summary still does not fit; only groups "
                      "are ever cut, all lists are complete in the detail file",
        }]
        return dump(summary)
    keep, size = 0, base
    for group in groups:
        size += len(dump(group)) + (1 if keep else 0)  # a comma before all but the first
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


NOT_QUERIED = {"status": "unreadable",
               "reason": "the Reliability Monitor was not queried", "events": []}


def _utc_time(text) -> datetime:
    """An ISO 8601 time with offset (or Z) as an aware datetime in UTC."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"time has no UTC offset: {text!r}")
    return moment.astimezone(timezone.utc)


def stability(found: dict, start: datetime) -> tuple[dict, int]:
    """The ``reliability`` field from the metrics job, and the rows it could not read.

    One entry per UTC day at or after ``start``: the index of the day's latest
    measurement, rounded to 2 places. ``drops`` lists each day whose index is
    lower than the previous entry's; the script compares, the model only picks.
    """
    if found["status"] == "unreadable":
        return {"status": "unreadable", "reason": found["reason"],
                "daily": None, "lowest": None, "drops": None}, 0
    latest: dict[str, tuple[datetime, float]] = {}
    bad = 0
    for row in found["events"]:
        try:
            moment = _utc_time(row["TimeGenerated"])
        except (KeyError, TypeError, ValueError):
            bad += 1
            continue
        if moment < start:
            continue  # outside the window: its index is never read
        value = row.get("SystemStabilityIndex")
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            bad += 1
            continue
        day = moment.date().isoformat()
        if day not in latest or moment >= latest[day][0]:
            latest[day] = (moment, float(value))
    daily = [{"date": day, "index": round(value, 2)}
             for day, (_, value) in sorted(latest.items())]
    # min keeps the first of equal values, and daily is in date order: the earliest wins.
    lowest = dict(min(daily, key=lambda d: d["index"])) if daily else None
    drops = [{"date": cur["date"], "index": cur["index"], "previous_index": prev["index"]}
             for prev, cur in itertools.pairwise(daily) if cur["index"] < prev["index"]]
    return {"status": found["status"], "reason": found["reason"],
            "daily": daily, "lowest": lowest, "drops": drops}, bad


def reliability_records(found: dict, start: datetime) -> tuple[list[dict] | None, int]:
    """Records at or after ``start`` grouped by (SourceName, EventIdentifier).

    Ordered like ``groups`` (count, then source and Id), with ids r1, r2...;
    ``product`` is the ProductName of the newest record, shortened like a
    sample, and ``products`` how many different ProductName values (a
    missing one counts as one value) the group holds. None when the records could not be read. Never cut.
    """
    if found["status"] == "unreadable":
        return None, 0
    timed, bad = [], 0
    for row in found["events"]:
        try:
            timed.append((_utc_time(row["TimeGenerated"]), row))
        except (KeyError, TypeError, ValueError):
            bad += 1
    timed.sort(key=lambda pair: pair[0])
    buckets: dict[tuple, dict] = {}
    for moment, row in timed:
        if moment < start:
            continue
        source, event_id = row.get("SourceName"), row.get("EventIdentifier")
        product = row.get("ProductName")
        item = buckets.setdefault((source, event_id), {
            "source": source, "event_id": event_id, "count": 0,
            "first": iso(moment), "last": None, "product": None, "products": set(),
        })
        item["count"] += 1
        item["last"] = iso(moment)
        item["product"] = shorten(str(product)) if product is not None else None
        item["products"].add(None if product is None else str(product))
    for item in buckets.values():
        item["products"] = len(item["products"])

    def order(item):
        event_id = item["event_id"]
        number = event_id if isinstance(event_id, int) and not isinstance(event_id, bool) else -1
        return (-item["count"], str(item["source"]), number, str(event_id))

    return with_ids(sorted(buckets.values(), key=order), "r"), bad


def reliability_summary(jobs: dict | None, start: datetime) -> dict:
    """``reliability``, ``reliability_records`` and the not_checked entries of their rows.

    ``jobs`` is {"metrics": job result, "records": job result}; an unreadable
    job is already named in not_checked by ``collect``. ``reliability`` also
    carries the records job's own status as ``records_status``/``records_reason``.
    """
    jobs = jobs or {}
    metrics = jobs.get("metrics", NOT_QUERIED)
    records = jobs.get("records", NOT_QUERIED)
    stable, bad_metrics = stability(metrics, start)
    grouped, bad_records = reliability_records(records, start)
    stable["records_status"] = records["status"]
    stable["records_reason"] = records["reason"]
    not_checked = []
    if bad_metrics:
        not_checked.append({
            "what": f"{bad_metrics} Reliability Monitor measurements that could not be read",
            "reason": "TimeGenerated missing or without a UTC offset, or SystemStabilityIndex "
                      "not a number; they are left out of reliability.daily",
        })
    if bad_records:
        not_checked.append({
            "what": f"{bad_records} Reliability Monitor records whose time could not be read",
            "reason": "TimeGenerated missing or without a UTC offset; they are left out of "
                      "reliability_records",
        })
    return {"stability": stable, "records": grouped, "not_checked": not_checked}


NO_INVENTORY = {"status": "unreadable", "reason": "the memory dumps were not listed",
                "settings": None, "files": []}
DUMPS_WHAT = "Memory dumps: CrashControl settings and the dump files"


def link_dumps(anomalies: list[dict], dumps: dict) -> dict:
    """Give the dump files ids d1, d2... and link them to bugchecks by path only.

    Paths are compared after ``os.path.normcase(os.path.normpath(...))``,
    never by time. A file gets ``bugcheck`` = a<n> only when exactly one
    bugcheck in the window names its path; ``bugcheck_candidates`` lists every
    bugcheck that does (several for a MEMORY.DMP overwritten at each crash).
    A bugcheck's ``dump`` is set only for such an unambiguous link; the
    anomalies are changed in place. A bugcheck with a ``dump_path`` also gets
    ``dump_path_listed``: true when the path lies in a place the inventory
    lists (directly in ``minidump_dir``, or equal to ``dump_file``), false
    when it does not, ``null`` when the settings are unknown.
    """
    def same(path):
        return os.path.normcase(os.path.normpath(path))

    settings = dumps.get("settings") or {}
    folder, dump_file = settings.get("minidump_dir"), settings.get("dump_file")
    by_path: dict[str, list[dict]] = {}
    for item in anomalies:
        if item.get("kind") == "bugcheck" and item.get("dump_path"):
            path = same(item["dump_path"])
            by_path.setdefault(path, []).append(item)
            if folder is None and dump_file is None:
                item["dump_path_listed"] = None
            else:
                item["dump_path_listed"] = bool(
                    (folder and os.path.dirname(path) == same(folder))
                    or (dump_file and path == same(dump_file)))
    files = []
    for n, entry in enumerate(dumps.get("files") or [], 1):
        crashes = by_path.get(same(entry["path"]), []) if entry.get("path") else []
        linked = crashes[0] if len(crashes) == 1 else None
        files.append({"id": f"d{n}", **entry,
                      "bugcheck": linked["id"] if linked else None,
                      "bugcheck_candidates": [c["id"] for c in crashes]})
        if linked:
            linked["dump"] = f"d{n}"
    return {**dumps, "files": files}


def build_summary(now, days, sources, analysis, not_checked, summary_file, detail_file,
                  reliability=None, dumps=None):
    """The summary. ``reliability`` comes from ``reliability_summary``; without it
    the Reliability Monitor is reported as not queried. ``dumps`` is the
    inventory from ``read_dumps`` (without ids); an unreadable one is named in
    not_checked. Without it the dumps are reported as not listed, and, as for
    the Reliability Monitor, not_checked is left to the caller."""
    start = now - timedelta(days=days)
    if reliability is None:
        reliability = reliability_summary(None, start)
    not_checked = not_checked + reliability["not_checked"]
    if dumps is None:
        dumps = NO_INVENTORY
    elif dumps.get("status") == "unreadable":
        not_checked = not_checked + [{"what": DUMPS_WHAT, "reason": dumps.get("reason")}]
    unreadable = analysis["unreadable"]
    unread_types = analysis.get("unread_boot_types", 0)
    if unread_types:
        not_checked = not_checked + [{
            "what": f"{unread_types} Kernel-Boot 27 events without a readable boot type",
            "reason": "Properties[0] missing or not 0, 1 or 2; left out of boot_type "
                      "and hibernate_resumes",
        }]
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
    uncertain = sorted(analysis.get("uncertain_boots", []))
    if boots is not None and uncertain:
        ids = ", ".join(f"b{index}" for index in uncertain)
        not_checked = not_checked + [{
            "what": f"boot sessions {ids}: a Fast Startup Kernel-Boot 27 joined a session "
                    "without a typed Kernel-Boot 27",
            "reason": "it may be a separate hybrid boot; the boot_type of these sessions "
                      "and the clean_shutdown before them are uncertain",
        }]
    dumps = link_dumps(anomalies, dumps)
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
        "reliability": reliability["stability"],
        "reliability_records": reliability["records"],
        "dumps": dumps,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": 0,
    }


# --- command line --------------------------------------------------------
DETAIL_SECTIONS = ("groups", "noise", "boots", "anomalies", "reliability_records",
                   "dump_files")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="events.py",
        description=(
            "Read the System and Application event logs, the Reliability "
            "Monitor and the list of memory dumps without elevation and write "
            "a JSON summary plus a detail file. Read-only."
        ),
    )
    parser.add_argument("--data-dir", default="ush-data",
                        help="output directory, relative to the working directory "
                             "(default: ush-data)")
    parser.add_argument("--days", type=_positive_int, default=30,
                        help="how many days back to read (default: 30)")
    parser.add_argument("--detail", metavar="ID",
                        help="print one item (e.g. g1, a2, b3, r1, d1) from the newest detail "
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
    if not isinstance(detail, dict):
        print(f"{newest} does not hold a detail object", file=sys.stderr)
        return 1
    for section in DETAIL_SECTIONS:
        for item in detail.get(section) or []:
            if isinstance(item, dict) and item.get("id") == item_id:
                print(json.dumps(item, ensure_ascii=True, indent=1))
                return 0
    print(f"id {item_id!r} not found in {newest}", file=sys.stderr)
    return 1


def default_read_dumps() -> dict:
    """The real dump inventory: CrashControl from the registry, files from disk (read-only)."""
    return dumpfiles.read_all(dumpfiles.default_read_value, dumpfiles.default_list_dir,
                              dumpfiles.default_stat, dumpfiles.default_open_file)


def main(argv=None, run_ps=None, now=None, trend_file=None, read_dumps=None) -> int:
    """Collect and summarise, or print one detail item with --detail.

    ``run_ps`` and ``read_dumps`` are the two inputs from the machine. Either
    both are injected (tests) or neither (a real run): injecting only one is a
    TypeError, so a test that forgets a fake fails loudly instead of reading
    the machine. ``read_dumps`` is called only when collecting.
    """
    if (run_ps is None) != (read_dumps is None):
        raise TypeError("inject both run_ps and read_dumps, or neither")
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
    try:
        trend_rule = load_trend(trend_file)
    except (OSError, ValueError) as exc:
        print(f"the trend rule could not be read: {exc}", file=sys.stderr)
        return 1
    run_ps = run_ps or default_run_ps
    read_dumps = read_dumps or default_read_dumps
    now =(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = now - timedelta(days=args.days)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    summary_file = work / f"events-{stamp}.summary.json"
    detail_file = work / f"events-{stamp}.detail.json"

    sources, events, not_checked = collect(run_ps, work, stamp, start, now)
    # coverage_start is the same for both passes of a log. A log whose oldest
    # record could not be read may be partial too, so its trend is unknown.
    coverage = {src["log"]: src["coverage_start"] for src in sources}
    for log in events["oldest_unreadable"]:
        coverage[log] = coverage.get(log) or "unknown"
    analysis = analyze(merge(events["A"], events["B"]), noise, window=(start, now),
                       coverage=coverage, trend_rule=trend_rule)
    reliability = reliability_summary(events["reliability"], start)
    summary = build_summary(now, args.days, sources, analysis, not_checked,
                            summary_file, detail_file, reliability, read_dumps())
    detail = {key: summary[key] for key in (
        "schema_version", "skill", "generated_at", "window", "sources", "reliability",
        *DETAIL_SECTIONS) if key != "dump_files"}
    # dump_files is not a summary key: it is the list inside summary["dumps"].
    detail["dump_files"] = summary["dumps"].get("files") or []
    detail["unreadable"] = analysis["unreadable"]
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    text = fit_budget(summary)
    summary_file.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

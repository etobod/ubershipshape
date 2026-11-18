"""Program footprints: ``<data dir>/state/footprints.json``.

One entry per program key ``ush-inventory`` lists, with the traces explicitly linked to
it (autostart entries and firewall rules by ``path``, top-level vendor folders by
``install_location`` or by a line of the ``vendors`` table naming the program's
publisher, ``vendor``). A link, once recorded, is kept; whether a trace is present is
decided by its own key in its read source, never by a link found again. A vendor folder
linked to several programs is one item of ``shared``, never one program's trace, and
stays shared.

A trace with no explicit link that appeared in the same run as a program is linked to it
``linked_by: "time"`` (appeared together, not confirmed): only when the trace's kind and
the programs were both read in full in the previous run (``last_run``), the trace was
not there then and the program has no entry in the previous file; Windows' own programs
and traces (``own`` in the presence) never take part. A time trace is never
shared, never counted with the explicit traces, and goes as soon as the same trace key
gets an explicit link. Dates are UTC dates (``YYYY-MM-DD``). Written by inventory only.

Shape::

    {"schema_version": 2,
     "entries": [{key, name, first_seen, gone_since,
                  traces: [{kind, key, linked_by, first_seen, present, gone_since,
                            seen_elevated}]}],
     "shared": [{kind, key, linked_by, programs, first_seen, present, gone_since,
                 seen_elevated}],
     "last_run": {kind: {present: [keys], within: [key prefixes] | null}}}

``last_run`` holds only the kinds read in full in that run (no key unread, no key prefix
unread). A schema_version 1 file (no ``last_run``) is read as version 2 with an empty
``last_run``, so its first version 2 run makes no time link.
"""

import json
import re
from datetime import date
from pathlib import Path

NAME = "footprints"
FILE_NAME = f"{NAME}.json"
SCHEMA_VERSION = 2
# The versions load reads; version 1 has no last_run.
READ_VERSIONS = (1, 2)
LINKED_BY = ("path", "install_location", "vendor", "time")
# The link of a trace that only appeared in the same run as a program (never explicit).
TIME = "time"
# The trace kind whose item holding several programs' locations is shared.
SHARED_KIND = "vendor_folders"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def date_ok(value, nullable=False) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check_trace(trace, where):
    if not isinstance(trace, dict):
        return f"{where} is not an object"
    for field in ("kind", "key"):
        if not isinstance(trace.get(field), str) or not trace[field].strip():
            return f"{where}: {field} {trace.get(field)!r} is not a non-empty string"
    if trace.get("linked_by") not in LINKED_BY:
        return f"{where}: linked_by {trace.get('linked_by')!r} is not one of {LINKED_BY}"
    if not date_ok(trace.get("first_seen")):
        return f"{where}: first_seen {trace.get('first_seen')!r} is not a date"
    if not date_ok(trace.get("gone_since"), nullable=True):
        return f"{where}: gone_since {trace.get('gone_since')!r} is neither a date nor null"
    for field in ("present", "seen_elevated"):
        if not isinstance(trace.get(field), bool):
            return f"{where}: {field} {trace.get(field)!r} is not true or false"
    return None


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _check_last_run(last_run):
    if not isinstance(last_run, dict):
        return "last_run is not an object"
    for kind, seen in last_run.items():
        if not isinstance(seen, dict):
            return f"last_run {kind!r} is not an object"
        if not _strings(seen.get("present")):
            return f"last_run {kind!r}: present is not a list of keys"
        if seen.get("within") is not None and not _strings(seen["within"]):
            return f"last_run {kind!r}: within is neither a list of prefixes nor null"
    return None


def check(data):
    """None when ``data`` is a valid file content (schema_version 1 or 2), else the
    problem."""
    if not isinstance(data, dict):
        return "the file is not an object"
    version = data.get("schema_version")
    if isinstance(version, bool) or version not in READ_VERSIONS:
        return f"schema_version {version!r} is not one of {READ_VERSIONS}"
    if version >= 2:
        problem = _check_last_run(data.get("last_run"))
        if problem is not None:
            return problem
    entries, shared = data.get("entries"), data.get("shared")
    if not isinstance(entries, list):
        return "entries is not a list"
    if not isinstance(shared, list):
        return "shared is not a list"
    seen = set()
    for n, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            return f"entry {n} is not an object"
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            return f"entry {n}: key {key!r} is not a non-empty string"
        if key in seen:
            return f"entry {n}: key {key!r} is there twice"
        seen.add(key)
        if entry.get("name") is not None and not isinstance(entry["name"], str):
            return f"entry {n}: name {entry['name']!r} is neither a string nor null"
        if not date_ok(entry.get("first_seen")):
            return f"entry {n}: first_seen {entry.get('first_seen')!r} is not a date"
        if not date_ok(entry.get("gone_since"), nullable=True):
            return (f"entry {n}: gone_since {entry.get('gone_since')!r} is neither a date "
                    f"nor null")
        traces = entry.get("traces")
        if not isinstance(traces, list):
            return f"entry {n}: traces is not a list"
        trace_keys = set()
        for m, trace in enumerate(traces, 1):
            problem = _check_trace(trace, f"entry {n} trace {m}")
            if problem is not None:
                return problem
            if trace["key"] in trace_keys:
                return f"entry {n}: trace key {trace['key']!r} is there twice"
            trace_keys.add(trace["key"])
    shared_keys = set()
    for n, item in enumerate(shared, 1):
        problem = _check_trace(item, f"shared item {n}")
        if problem is not None:
            return problem
        if item["linked_by"] == TIME:
            return f"shared item {n}: a time link is never shared"
        if item["key"] in shared_keys:
            return f"shared item {n}: key {item['key']!r} is there twice"
        shared_keys.add(item["key"])
        programs = item.get("programs")
        if not isinstance(programs, list) or not all(isinstance(p, str) for p in programs):
            return f"shared item {n}: programs is not a list of keys"
    return None


def file_path(data_dir) -> Path:
    return Path(data_dir).absolute() / "state" / FILE_NAME


def load(data_dir) -> dict:
    """``{status, reason, path, entries, shared, last_run}`` of
    ``<data_dir>/state/footprints.json``.

    ``status`` is ``none`` (no file), ``read`` (schema_version 1, whose ``last_run`` is
    ``{}``, or 2), or ``unreadable`` (cannot be read, bad JSON or a bad shape;
    ``reason`` names the problem). Without a read file ``entries`` and ``shared`` are
    ``[]`` and ``last_run`` is ``{}``. Never raises."""
    path = file_path(data_dir)
    result = {"status": "none", "reason": None, "path": str(path), "entries": [],
              "shared": [], "last_run": {}}
    try:
        if not path.exists():
            return result
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return dict(result, status="unreadable", reason=f"cannot read {FILE_NAME}: {exc}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        return dict(result, status="unreadable", reason=f"{FILE_NAME} is not JSON: {exc}")
    problem = check(data)
    if problem is not None:
        return dict(result, status="unreadable", reason=f"{FILE_NAME}: {problem}")
    return dict(result, status="read", entries=data["entries"], shared=data["shared"],
                last_run=data.get("last_run") or {})


def _unread(presence, kind, key) -> bool:
    """The presence of ``key`` was not read in this run."""
    seen = presence.get(kind)
    if seen is None:
        return True
    within = seen.get("within")
    if within is not None and not key.startswith(tuple(within)):
        return True
    return key in seen.get("unread", ()) or key.startswith(tuple(seen.get("prefixes", ())))


def _present(presence, kind, key) -> bool:
    seen = presence.get(kind)
    return seen is not None and key in seen.get("present", ())


def _stamp(item, presence, admin, today):
    """Set ``present``, ``gone_since`` and ``seen_elevated`` of an old trace or shared
    item. Not read (its source, its root, or an elevated sighting checked by a normal
    run): kept as it was."""
    kind, key = item["kind"], item["key"]
    if _present(presence, kind, key):
        item.update(present=True, gone_since=None,
                    seen_elevated=item.get("seen_elevated") is True or bool(admin))
    elif _unread(presence, kind, key) or (not admin and item.get("seen_elevated") is True):
        return
    else:
        item["present"] = False
        item["gone_since"] = item.get("gone_since") or today


def last_run(presence: dict, before: dict | None = None) -> dict:
    """The ``last_run`` of this run: the present keys of each kind read in full (no key
    unread, no key prefix unread), with its ``within`` prefixes or null. A kind whose
    only gap is a set of key prefixes (an elevated run's per-user keys; never a whole
    source not read, ``""`` or ``source_unread``) is kept when the
    previous ``last_run`` (``before``) has it: its keys under those prefixes come from
    there, so an elevated pass between two normal runs does not end the time links."""
    before = before or {}
    result = {}
    for kind, seen in sorted(presence.items()):
        prefixes = tuple(seen.get("prefixes") or ())
        present = set(seen.get("present") or ())
        if seen.get("unread") or "" in prefixes or seen.get("source_unread"):
            continue
        if prefixes:
            old = before.get(kind)
            if old is None or old.get("within") != (None if seen.get("within") is None
                                                    else sorted(seen["within"])):
                continue
            present |= {key for key in old["present"] if key.startswith(prefixes)}
        within = seen.get("within")
        result[kind] = {"present": sorted(present),
                        "within": None if within is None else sorted(within)}
    return result


def _new_traces(presence, before, skip):
    """``[(kind, key)]`` of the trace keys present now whose kind was read in full in
    the previous run (``before``, its ``last_run``) without them (and, with ``within``,
    that lie under one of its prefixes), leaving out the keys in ``skip`` and Windows'
    own keys (``own``)."""
    found = []
    for kind, seen in sorted(presence.items()):
        old = before.get(kind)
        if kind == "programs" or old is None:
            continue
        keys, within = set(old["present"]), old.get("within")
        own = seen.get("own") or ()
        for key in sorted(seen.get("present") or ()):
            if key in keys or key in skip or key in own:
                continue
            if within is not None and not key.startswith(tuple(within)):
                continue
            found.append((kind, key))
    return found


def update(previous: dict, programs: dict, links: list, presence: dict, admin: bool,
           today: str) -> dict:
    """The new file content from ``previous`` (a ``load`` result) and this run.

    ``programs``: ``{key: name}`` of every program key the run lists (with the ones its
    baseline brings for a source not read). ``links``: ``[(program key, kind, trace
    key, linked_by)]`` found in this run. ``presence``: ``{kind: {present, unread,
    prefixes[, own][, within]}}``, the keys present in this run, the keys whose presence
    was not read, the key prefixes not read (``""`` for a whole source) and the present
    keys of Windows' own items and of items whose ownership is not known, which take no
    part in a time link; with
    ``within``, a key under none of its prefixes is not read either; a kind missing is
    not read at all. The kind ``programs`` gives the programs' own presence. ``today``: the
    UTC date of the run.

    A program is new when it is present now, ``programs`` is in the previous
    ``last_run`` without its key and the previous file has no entry for it (so a
    portable program not running then, or one back after ``gone_since``, is not new).
    A trace is new when it is present now and its kind is in the previous ``last_run``
    without its key (with ``within``, under one of its prefixes). A new trace with no
    explicit link in this run and no holder in the file (an entry or ``shared``) gets a
    ``time`` trace under every new program; an explicit link for a key first removes
    the time traces of that key from every entry."""
    entries = {e["key"]: {**e, "traces": [dict(t) for t in e["traces"]]}
               for e in previous.get("entries") or []}
    shared = {s["key"]: dict(s, programs=list(s["programs"]))
              for s in previous.get("shared") or []}
    before = previous.get("last_run") or {}

    new_programs = []
    if "programs" in before:
        old_programs = set(before["programs"]["present"])
        seen = presence.get("programs") or {}
        own = seen.get("own") or ()
        new_programs = sorted(
            key for key in seen.get("present") or ()
            if key not in old_programs and key not in entries and key not in own)

    for key, entry in entries.items():
        if _present(presence, "programs", key):
            entry["gone_since"] = None
            entry["name"] = programs.get(key, entry.get("name"))
        elif not _unread(presence, "programs", key):
            entry["gone_since"] = entry.get("gone_since") or today
        for trace in entry["traces"]:
            _stamp(trace, presence, admin, today)
    for item in shared.values():
        _stamp(item, presence, admin, today)

    for key in sorted(set(programs) | {link[0] for link in links} | set(new_programs)):
        entries.setdefault(key, {"key": key, "name": programs.get(key), "first_seen": today,
                                 "gone_since": None, "traces": []})

    new = {}
    for program, kind, trace_key, linked_by in links:
        if _present(presence, kind, trace_key):
            new.setdefault((kind, trace_key), {})[program] = linked_by
    for (kind, trace_key), linked in sorted(new.items()):
        # An explicit link replaces the time links of the same trace.
        for entry in entries.values():
            entry["traces"] = [t for t in entry["traces"]
                               if not (t["key"] == trace_key and t["linked_by"] == TIME)]
        owners = {key for key, entry in entries.items()
                  if any(t["key"] == trace_key for t in entry["traces"])}
        if kind == SHARED_KIND and (trace_key in shared or len(owners | set(linked)) > 1):
            moved = [t for e in entries.values() for t in e["traces"] if t["key"] == trace_key]
            for entry in entries.values():
                entry["traces"] = [t for t in entry["traces"] if t["key"] != trace_key]
            item = shared.get(trace_key)
            if item is None:
                first = min([t["first_seen"] for t in moved] + [today])
                item = {"kind": kind, "key": trace_key, "linked_by": next(iter(linked.values())),
                        "programs": [], "first_seen": first, "present": True,
                        "gone_since": None, "seen_elevated": bool(admin)}
                shared[trace_key] = item
            item["programs"] = sorted(set(item["programs"]) | owners | set(linked))
            continue
        for program, linked_by in linked.items():
            if program in owners:
                continue
            entries[program]["traces"].append(
                {"kind": kind, "key": trace_key, "linked_by": linked_by, "first_seen": today,
                 "present": True, "gone_since": None, "seen_elevated": bool(admin)})

    if new_programs:
        held = {t["key"] for e in entries.values() for t in e["traces"]} | set(shared)
        explicit = {trace_key for _, trace_key in new}
        for kind, trace_key in _new_traces(presence, before, held | explicit):
            for program in new_programs:
                entries[program]["traces"].append(
                    {"kind": kind, "key": trace_key, "linked_by": TIME, "first_seen": today,
                     "present": True, "gone_since": None, "seen_elevated": bool(admin)})

    for entry in entries.values():
        entry["traces"].sort(key=lambda t: (t["kind"], t["key"]))
    return {"schema_version": SCHEMA_VERSION,
            "entries": [entries[key] for key in sorted(entries)],
            "shared": [shared[key] for key in sorted(shared)],
            "last_run": last_run(presence, before)}


def counts(data: dict) -> dict:
    """``footprint_counts`` of a file content. ``traces``, ``traces_present`` and
    ``gone_with_present_traces`` count the explicit traces only; ``time_links`` and
    ``time_links_present`` the time traces."""
    entries = data["entries"]
    traces = [t for e in entries for t in e["traces"] if t["linked_by"] != TIME]
    timed = [t for e in entries for t in e["traces"] if t["linked_by"] == TIME]
    gone = [e for e in entries if e["gone_since"] is not None]
    return {
        "programs": len(entries),
        "programs_gone": len(gone),
        "traces": len(traces),
        "traces_present": sum(1 for t in traces if t["present"]),
        "shared": len(data["shared"]),
        "gone_with_present_traces": sum(
            1 for e in gone
            if any(t["present"] and t["linked_by"] != TIME for t in e["traces"])),
        "time_links": len(timed),
        "time_links_present": sum(1 for t in timed if t["present"]),
    }


def time_links(data: dict) -> list:
    """``[{program, name, kind, key, first_seen}]``: every present time trace, the
    newest ``first_seen`` first, then by program key and trace key."""
    found = [{"program": e["key"], "name": e.get("name"), "kind": t["kind"],
              "key": t["key"], "first_seen": t["first_seen"]}
             for e in data["entries"] for t in e["traces"]
             if t["linked_by"] == TIME and t["present"]]
    found.sort(key=lambda item: (item["program"], item["key"]))
    found.sort(key=lambda item: item["first_seen"], reverse=True)
    return found

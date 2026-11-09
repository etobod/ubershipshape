"""Program footprints: ``<data dir>/state/footprints.json``.

One entry per program key ``ush-inventory`` lists, with the traces explicitly linked to
it (autostart entries and firewall rules by ``path``, top-level vendor folders by
``install_location``). A link, once recorded, is kept; whether a trace is present is
decided by its own key in its read source, never by a link found again. A vendor folder
that holds several programs' locations is one item of ``shared``, never one program's
trace, and stays shared. Dates are UTC dates (``YYYY-MM-DD``). Written by inventory only.

Shape::

    {"schema_version": 1,
     "entries": [{key, name, first_seen, gone_since,
                  traces: [{kind, key, linked_by, first_seen, present, gone_since,
                            seen_elevated}]}],
     "shared": [{kind, key, linked_by, programs, first_seen, present, gone_since,
                 seen_elevated}]}
"""

import json
import re
from datetime import date
from pathlib import Path

NAME = "footprints"
FILE_NAME = f"{NAME}.json"
SCHEMA_VERSION = 1
LINKED_BY = ("path", "install_location")
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


def check(data):
    """None when ``data`` is a valid file content, else the problem."""
    if not isinstance(data, dict):
        return "the file is not an object"
    if data.get("schema_version") != SCHEMA_VERSION:
        return f"schema_version {data.get('schema_version')!r} is not {SCHEMA_VERSION}"
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
    """``{status, reason, path, entries, shared}`` of ``<data_dir>/state/footprints.json``.

    ``status`` is ``none`` (no file; ``entries`` and ``shared`` ``[]``), ``read``, or
    ``unreadable`` (cannot be read, bad JSON or a bad shape; ``reason`` names the
    problem, ``entries`` and ``shared`` are ``[]``). Never raises."""
    path = file_path(data_dir)
    result = {"status": "none", "reason": None, "path": str(path), "entries": [],
              "shared": []}
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
    return dict(result, status="read", entries=data["entries"], shared=data["shared"])


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


def update(previous: dict, programs: dict, links: list, presence: dict, admin: bool,
           today: str) -> dict:
    """The new file content from ``previous`` (a ``load`` result) and this run.

    ``programs``: ``{key: name}`` of every program key the run lists (with the ones its
    baseline brings for a source not read). ``links``: ``[(program key, kind, trace
    key, linked_by)]`` found in this run. ``presence``: ``{kind: {present, unread,
    prefixes[, within]}}``, the keys present in this run, the keys whose presence was
    not read and the key prefixes not read (``""`` for a whole source); with
    ``within``, a key under none of its prefixes is not read either; a kind missing is
    not read at all. The kind ``programs`` gives the programs' own presence. ``today``: the
    UTC date of the run."""
    entries = {e["key"]: {**e, "traces": [dict(t) for t in e["traces"]]}
               for e in previous.get("entries") or []}
    shared = {s["key"]: dict(s, programs=list(s["programs"]))
              for s in previous.get("shared") or []}

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

    for key in sorted(set(programs) | {link[0] for link in links}):
        entries.setdefault(key, {"key": key, "name": programs.get(key), "first_seen": today,
                                 "gone_since": None, "traces": []})

    new = {}
    for program, kind, trace_key, linked_by in links:
        if _present(presence, kind, trace_key):
            new.setdefault((kind, trace_key), {})[program] = linked_by
    for (kind, trace_key), linked in sorted(new.items()):
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

    for entry in entries.values():
        entry["traces"].sort(key=lambda t: (t["kind"], t["key"]))
    return {"schema_version": SCHEMA_VERSION,
            "entries": [entries[key] for key in sorted(entries)],
            "shared": [shared[key] for key in sorted(shared)]}


def counts(data: dict) -> dict:
    """``footprint_counts`` of a file content."""
    entries = data["entries"]
    traces = [t for e in entries for t in e["traces"]]
    gone = [e for e in entries if e["gone_since"] is not None]
    return {
        "programs": len(entries),
        "programs_gone": len(gone),
        "traces": len(traces),
        "traces_present": sum(1 for t in traces if t["present"]),
        "shared": len(data["shared"]),
        "gone_with_present_traces": sum(1 for e in gone
                                        if any(t["present"] for t in e["traces"])),
    }

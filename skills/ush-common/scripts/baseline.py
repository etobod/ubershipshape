"""The saved baseline of a differential skill (the state kept between runs).

A baseline is one JSON file in ``<data dir>/state/``:

    {"schema_version": 1, "skill": "<skill>", "created_at": "<ISO UTC>",
     "elevated": <bool>, "sources": {<source name>: {<key>: <item>}}}

The file is ``<skill>.json``, or ``<skill>.elevated.json`` for a run with administrator
rights: an elevated run sees another set (more tasks, ``HKCU`` of another account), so it
is compared only with an elevated baseline.

This module touches only files in the state directory; it never queries the machine.
Nothing here judges a change: ``compare`` lists what differs, the model decides what it
means.

- ``load`` never raises on a bad file: it reports ``unreadable`` with the reason and leaves
  the file as it is.
- ``save`` writes a temporary file, reads it back and compares it with what was meant to be
  written; only then is the current baseline copied to ``<name>.previous.json`` (one
  generation) and replaced with ``os.replace``. An unreadable current baseline is copied to
  ``<name>.unreadable-<UTC stamp>.json`` instead of ``previous``, so it is never lost.
- A source that was not read this run keeps its items from the previous baseline
  (``merge_sources``) and is not compared (``comparison_state``), so it gives no wave of
  false "added" or "removed" in the next run.
"""

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
READ_STATUSES = ("read", "empty")


def baseline_name(skill, elevated):
    """File stem of the baseline: ``<skill>`` or ``<skill>.elevated``."""
    return f"{skill}.elevated" if elevated else skill


def parse_utc(text):
    """Parse an ISO 8601 time with a zone into an aware UTC datetime.

    A time without a zone raises ``ValueError``: it is never guessed, so it cannot meet an
    aware time in a subtraction (``TypeError``) later. A value that is not a string raises
    ``TypeError``.
    """
    value = datetime.fromisoformat(text)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"time has no time zone: {text!r}")
    return value.astimezone(timezone.utc)


def _check(data, skill, elevated):
    """Return None when ``data`` is a valid baseline of ``skill``/``elevated``, else a reason."""
    if not isinstance(data, dict):
        return "baseline is not a JSON object"
    if data.get("schema_version") != SCHEMA_VERSION:
        return (f"schema_version is {data.get('schema_version')!r}, "
                f"expected {SCHEMA_VERSION}")
    if data.get("skill") != skill:
        return f"skill is {data.get('skill')!r}, expected {skill!r}"
    if data.get("elevated") is not bool(elevated):
        return f"elevated is {data.get('elevated')!r}, expected {bool(elevated)!r}"
    try:
        parse_utc(data.get("created_at"))
    except (TypeError, ValueError) as exc:
        return f"created_at is not an ISO time with a zone: {exc}"
    sources = data.get("sources")
    if not isinstance(sources, dict):
        return "sources is not an object"
    for name, items in sources.items():
        if not isinstance(items, dict):
            return f"source {name!r} is not an object"
        for key, item in items.items():
            if not isinstance(item, dict):
                return f"item {key!r} of source {name!r} is not an object"
            unread = item.get("unread_fields", [])
            if not isinstance(unread, list) or not all(isinstance(f, str) for f in unread):
                return f"unread_fields of item {key!r} in source {name!r} is not a list of names"
    return None


def _read(path):
    """Read and parse a baseline file: ``(data, None)`` or ``(None, reason)``."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"cannot read {path.name}: {exc}"
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, f"invalid JSON in {path.name}: {exc}"


def load(state_dir, skill, elevated):
    """Load the baseline of ``skill`` for this privilege level.

    Returns ``{status, reason, created_at, sources}``: ``status`` is ``none`` (no file),
    ``read`` or ``unreadable`` (bad JSON, another ``schema_version``, another ``skill``,
    another ``elevated``, a time without a zone). Never raises on a bad file and never
    changes it.
    """
    path = Path(state_dir).absolute() / f"{baseline_name(skill, elevated)}.json"
    result = {"status": "none", "reason": None, "created_at": None, "sources": {}}
    if not path.exists():
        return result
    data, reason = _read(path)
    if reason is None:
        reason = _check(data, skill, elevated)
    if reason is not None:
        result.update(status="unreadable", reason=f"{path.name}: {reason}")
        return result
    result.update(status="read", created_at=data["created_at"], sources=data["sources"])
    return result


def compare(previous, current, fields):
    """Compare one source, both dicts ``key -> item``.

    Returns ``{"added": [keys], "removed": [keys], "changed": {key: {field: {before,
    after}}}}``; key lists are sorted. Only ``fields`` are compared, and a field named in
    the ``unread_fields`` of the previous or the current item is skipped.
    """
    previous = previous or {}
    current = current or {}
    added = sorted(key for key in current if key not in previous)
    removed = sorted(key for key in previous if key not in current)
    changed = {}
    for key in sorted(key for key in current if key in previous):
        before, after = previous[key], current[key]
        skip = set(before.get("unread_fields") or []) | set(after.get("unread_fields") or [])
        diff = {}
        for field in fields:
            if field in skip:
                continue
            if before.get(field) != after.get(field):
                diff[field] = {"before": before.get(field), "after": after.get(field)}
        if diff:
            changed[key] = diff
    return {"added": added, "removed": removed, "changed": changed}


def merge_sources(previous, current, statuses):
    """The source map to save: ``{source name: {key: item}}``.

    A source with status ``read`` or ``empty`` takes its current items (``empty`` saves an
    empty dict). Any other status (or none given) keeps the items of the previous baseline,
    or leaves the source out when the previous baseline did not have it.
    """
    previous = previous or {}
    current = current or {}
    merged = {}
    names = list(statuses)
    names += [name for name in current if name not in names]
    names += [name for name in previous if name not in names]
    for name in names:
        if statuses.get(name) in READ_STATUSES:
            merged[name] = copy.deepcopy(current.get(name) or {})
        elif name in previous:
            merged[name] = copy.deepcopy(previous[name])
    return merged


def comparison_state(previous, name, status):
    """``not_read``, ``no_baseline`` or ``compared`` for one source.

    ``previous`` is the source map of the previous baseline (``None`` or ``{}`` when there
    is none). Only ``compared`` gives changes.
    """
    if status not in READ_STATUSES:
        return "not_read"
    if not previous or name not in previous:
        return "no_baseline"
    return "compared"


def _default_read_back(path):
    return Path(path).read_text(encoding="utf-8")


def _utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _unused(path_for):
    """The first of ``path_for("")``, ``path_for("-2")``, ... that does not exist."""
    candidate, number = path_for(""), 1
    while candidate.exists():
        number += 1
        candidate = path_for(f"-{number}")
    return candidate


def _copy_verified(src, dst):
    """Copy ``src`` to ``dst`` through a temporary file and compare the bytes.

    Returns None on success, else a reason; on failure ``dst`` is not touched.
    """
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        content = src.read_bytes()
        tmp.write_bytes(content)
        if tmp.read_bytes() != content:
            return f"copy of {src.name} to {dst.name} did not read back the same"
        os.replace(tmp, dst)
        return None
    except OSError as exc:
        return f"cannot copy {src.name} to {dst.name}: {exc}"
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save(state_dir, name, data, read_back=None):
    """Save ``data`` as ``<state_dir>/<name>.json``; return None, or a reason on failure.

    Order: write ``<name>.json.tmp``, read it back (``read_back(path) -> str``, default a
    UTF-8 read) and compare the parsed JSON with ``data``. A failed verification removes the
    temporary file and leaves the old baseline and ``previous`` untouched. Then the current
    baseline is copied (and verified) to ``<name>.previous.json.tmp``, or, when it is not a
    valid baseline, to ``<name>.unreadable-<UTC stamp>.json``; a failed copy aborts. Then
    ``os.replace`` puts the temporary file in place, and only after that does the copy
    replace ``<name>.previous.json``: a failed replace leaves the old ``previous`` as it was.
    """
    if not isinstance(data, dict):
        return "baseline data is not a dict"
    reason = _check(data, data.get("skill"), data.get("elevated"))
    if reason is not None:
        return f"baseline data is not a valid baseline: {reason}"
    if name != baseline_name(data["skill"], data["elevated"]):
        return (f"name {name!r} does not match skill {data['skill']!r} "
                f"and elevated {data['elevated']!r}")
    read_back = read_back or _default_read_back
    state = Path(state_dir).absolute()
    current = state / f"{name}.json"
    tmp = state / f"{name}.json.tmp"
    try:
        text = json.dumps(data, ensure_ascii=True, indent=1)
        expected = json.loads(text)
    except (TypeError, ValueError) as exc:
        return f"baseline data cannot be written as JSON: {exc}"

    try:
        state.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        _remove(tmp)
        return f"cannot write {tmp.name}: {exc}"

    try:
        written = json.loads(read_back(tmp))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        _remove(tmp)
        return f"verification read of {tmp.name} failed: {exc}"
    if written != expected:
        _remove(tmp)
        return f"verification of {tmp.name} failed: it does not hold what was written"

    previous = state / f"{name}.previous.json"
    previous_tmp = None
    if current.exists():
        old, reason = _read(current)
        if reason is None:
            reason = _check(old, data.get("skill"), data.get("elevated"))
        if reason is None:
            # The old previous generation stays until the new baseline is in place.
            previous_tmp = state / f"{name}.previous.json.tmp"
            target = previous_tmp
        else:
            stamp = _utc_stamp()
            target = _unused(lambda suffix: state / f"{name}.unreadable-{stamp}{suffix}.json")
        reason = _copy_verified(current, target)
        if reason is not None:
            _remove(tmp)
            return reason

    try:
        os.replace(tmp, current)
    except OSError as exc:
        _remove(tmp)
        if previous_tmp is not None:
            _remove(previous_tmp)
        return f"cannot replace {current.name}: {exc}"
    if previous_tmp is not None:
        try:
            os.replace(previous_tmp, previous)
        except OSError as exc:
            _remove(previous_tmp)
            return (f"the new baseline is saved, but {previous.name} could not be "
                    f"replaced: {exc}")
    return None


def _remove(path):
    try:
        path.unlink()
    except OSError:
        pass


def age_days(created_at, now):
    """Days from ``created_at`` (ISO string with a zone) to ``now`` (aware), one decimal."""
    delta = now.astimezone(timezone.utc) - parse_utc(created_at)
    return round(delta.total_seconds() / 86400, 1)

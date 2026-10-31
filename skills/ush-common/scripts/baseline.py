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
  ``save_json`` is that write for any state file, with the check of the old file given by
  the caller (the id map of ``ids.py`` uses it).
- A source that was not read this run keeps its items from the previous baseline
  (``merge_sources``) and is not compared (``comparison_state``), so it gives no wave of
  false "added" or "removed" in the next run.
- History: after each ``save`` (also one that returned a reason) the skill calls
  ``archive``, which copies the baseline that is in ``state/`` (verified, through
  ``_copy_verified``) to ``state/history/<name>.<YYYY-MM-DD>.json``, the UTC day of the
  file's own ``created_at``; a later run on the same day replaces that day's copy. Day
  copies older than ``HISTORY_DAYS`` days are removed, except the newest of them, so a
  comparison after a long pause still finds the state before it; other names are never
  touched.
  ``load_reference`` picks the newest day copy at least ``days`` days old, so a run can be
  compared with an older state than ``previous``. ``parse_compare_to`` reads the
  ``--compare-to <N>d`` value and ``reference_for`` picks what a run compares with; the
  latest baseline stays the base of what is saved, so a source not read in this run keeps
  the state of the latest run, not that of the old copy.
"""

import copy
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1
READ_STATUSES = ("read", "empty")
# One day more than the largest allowed comparison age (30 days), so that a
# comparison with the state of 30 days ago still has a copy.
HISTORY_DAYS = 31
HISTORY_DIR = "history"
PRUNE_FAILED = "the day copy was kept, but old copies were not removed: "


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

    ``data`` must be a valid baseline whose ``skill`` and ``elevated`` match ``name``. The
    write itself is ``save_json`` with the baseline check as ``validate``: an old file that
    is not a valid baseline of the same skill and privilege level is kept as
    ``<name>.unreadable-<UTC stamp>.json`` instead of ``previous``.
    """
    if not isinstance(data, dict):
        return "baseline data is not a dict"
    reason = _check(data, data.get("skill"), data.get("elevated"))
    if reason is not None:
        return f"baseline data is not a valid baseline: {reason}"
    if name != baseline_name(data["skill"], data["elevated"]):
        return (f"name {name!r} does not match skill {data['skill']!r} "
                f"and elevated {data['elevated']!r}")
    skill, elevated = data["skill"], data["elevated"]
    return save_json(state_dir, name, data, lambda old: _check(old, skill, elevated),
                     read_back=read_back)


def save_json(state_dir, name, data, validate, read_back=None):
    """Save ``data`` as ``<state_dir>/<name>.json``; return None, or a reason on failure.

    ``name`` is the file stem (e.g. ``ush-inventory.ids``); ``validate(old) -> None or
    reason`` judges the file that is there now.

    Order: write ``<name>.json.tmp``, read it back (``read_back(path) -> str``, default a
    UTF-8 read) and compare the parsed JSON with ``data``. A failed verification removes the
    temporary file and leaves the old file and ``previous`` untouched. Then the current file
    is copied (and verified) to ``<name>.previous.json.tmp`` when ``validate`` accepts it, or
    else to ``<name>.unreadable-<UTC stamp>.json``; a failed copy aborts. Then
    ``os.replace`` puts the temporary file in place, and only after that does the copy
    replace ``<name>.previous.json``: a failed replace leaves the old ``previous`` as it was.
    """
    read_back = read_back or _default_read_back
    state = Path(state_dir).absolute()
    current = state / f"{name}.json"
    tmp = state / f"{name}.json.tmp"
    try:
        text = json.dumps(data, ensure_ascii=True, indent=1)
        expected = json.loads(text)
    except (TypeError, ValueError) as exc:
        return f"data for {current.name} cannot be written as JSON: {exc}"

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
            reason = validate(old)
        if reason is None:
            # The old previous generation stays until the new file is in place.
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
            return (f"the new {current.name} is saved, but {previous.name} could not be "
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


def _history_day(name, file_name):
    """The date in ``<name>.<YYYY-MM-DD>.json``, or None for another name or a bad date."""
    match = re.fullmatch(re.escape(name) + r"\.(\d{4}-\d{2}-\d{2})\.json", file_name)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def archive(state_dir, name, now):
    """Copy ``<name>.json`` to ``history/<name>.<UTC day of its created_at>.json`` and prune.

    Called by a skill after every ``save``, also one that returned a reason: it archives the
    file that is in place now, under its own date. Day copies of ``name`` older than ``now``
    minus ``HISTORY_DAYS`` days are removed, except the newest of them; other names and
    names with an impossible date are kept. Returns None, or a reason. No ``<name>.json`` gives None and copies nothing; a
    file that does not parse or has no valid ``created_at`` gives a reason and copies
    nothing.
    """
    state = Path(state_dir).absolute()
    current = state / f"{name}.json"
    if not current.exists():
        return None
    data, reason = _read(current)
    if reason is not None:
        return reason
    if not isinstance(data, dict):
        return f"{current.name} is not a JSON object"
    try:
        created = parse_utc(data.get("created_at"))
    except (TypeError, ValueError) as exc:
        return f"created_at of {current.name} is not an ISO time with a zone: {exc}"
    # A file load would reject is not archived: load_reference would pick it and,
    # by design, not fall back to an older copy.
    reason = _check(data, data.get("skill"), data.get("elevated"))
    if reason is None and baseline_name(data.get("skill"), data.get("elevated")) != name:
        reason = f"it is the baseline of {data.get('skill')!r}, not of {name!r}"
    if reason is not None:
        return f"{current.name} is not archived: {reason}"

    history = state / HISTORY_DIR
    try:
        history.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"cannot create {HISTORY_DIR}: {exc}"
    target = history / f"{name}.{created.date().isoformat()}.json"
    reason = _copy_verified(current, target)
    if reason is not None:
        return reason

    cutoff = now.astimezone(timezone.utc).date() - timedelta(days=HISTORY_DAYS)
    failures = []
    try:
        entries = list(history.iterdir())
    except OSError as exc:
        return f"{PRUNE_FAILED}cannot list {HISTORY_DIR}: {exc}"
    old = sorted(
        (found, path) for path in entries
        if (found := _history_day(name, path.name)) is not None and found < cutoff
        and path != target and path.is_file()
    )
    # The newest old copy stays: after a pause between runs it is the state before
    # the pause, which --compare-to still needs. The copy just made stays even when
    # its date is already past the cutoff (a save that kept failing).
    for _, path in old[:-1]:
        try:
            path.unlink()
        except OSError as exc:
            failures.append(f"cannot remove {path.name}: {exc}")
    return PRUNE_FAILED + "; ".join(failures) if failures else None


def history_note(reason):
    """The ``not_checked`` reason for a non-None ``archive`` reason.

    A failed cleanup after a verified day copy is not "history not kept": the copy of
    this run is there.
    """
    if reason.startswith(PRUNE_FAILED):
        return reason
    return f"history not kept: {reason}"


def load_reference(state_dir, skill, elevated, days, now):
    """Load the newest history copy of ``skill`` at least ``days`` days old.

    Picks ``history/<baseline name>.<YYYY-MM-DD>.json`` with the latest date not later
    than the UTC day of ``now`` minus ``days`` (names with an impossible date are skipped).
    Days are UTC calendar days, so the copy can be less than ``days`` times 24 hours old;
    its ``created_at`` says how old it really is. ``days`` outside 1 to
    ``HISTORY_DAYS - 1`` raises ValueError.
    Returns the shape of ``load`` plus ``file`` (the bare file name, ``None`` when nothing
    was picked). A picked file that is not a valid baseline is ``unreadable``, with no
    fallback to an older copy; no copy old enough is ``none`` with a reason.
    """
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days < HISTORY_DAYS:
        # Day 0 is the copy archive just made from this run: comparing with it is not
        # a comparison.
        raise ValueError(f"days must be a whole number from 1 to {HISTORY_DAYS - 1}: "
                         f"{days!r}")
    name = baseline_name(skill, elevated)
    history = Path(state_dir).absolute() / HISTORY_DIR
    limit = now.astimezone(timezone.utc).date() - timedelta(days=days)
    result = {"status": "none", "reason": None, "created_at": None, "sources": {},
              "file": None}
    best = None
    if history.exists():
        try:
            entries = list(history.iterdir())
        except OSError as exc:
            result.update(status="unreadable", reason=f"cannot list {HISTORY_DIR}: {exc}")
            return result
        for path in entries:
            found = _history_day(name, path.name)
            if found is None or found > limit or not path.is_file():
                continue
            if best is None or found > best[0]:
                best = (found, path)
    if best is None:
        result["reason"] = f"no saved state at least {days} days old"
        return result
    path = best[1]
    result["file"] = path.name
    data, reason = _read(path)
    if reason is None:
        reason = _check(data, skill, elevated)
    if reason is not None:
        result.update(status="unreadable", reason=f"{path.name}: {reason}")
        return result
    result.update(status="read", created_at=data["created_at"], sources=data["sources"])
    return result


COMPARE_TO_PATTERN = re.compile(r"([1-9][0-9]?)d")
COMPARE_TO_HELP = (f"compare with the saved state at least N days old (N from 1 to "
                   f"{HISTORY_DAYS - 1}, e.g. 7d) instead of the latest run")


def parse_compare_to(text):
    """The day count of a ``--compare-to`` value ``<N>d``, or None when it is not one.

    N is a whole number from 1 to ``HISTORY_DAYS - 1``; the caller turns None into a
    usage error.
    """
    match = COMPARE_TO_PATTERN.fullmatch(text or "")
    if match is None:
        return None
    days = int(match.group(1))
    return days if 1 <= days < HISTORY_DAYS else None


def reference_for(state_dir, skill, elevated, loaded, compare_to, days, now):
    """What a run compares with: the latest baseline, or a history copy with the flag.

    ``loaded`` is the result of ``load`` (it stays the base of ``collect`` and
    ``merge_sources`` in the skill); ``compare_to`` is the flag value (e.g. ``"7d"``) or
    None, ``days`` its day count. Returns ``{"sources", "info", "notes"}``: ``sources``
    is the source map to compare with (``{}`` when there is nothing to compare with),
    ``info`` the summary ``baseline`` object without ``saved`` and with ``reason`` as a
    list of reasons (the latest file's first), ``notes`` the ``(what, reason)`` pairs for
    ``not_checked``.
    """
    reasons, notes = [], []
    if loaded["status"] == "unreadable":
        reasons.append(loaded["reason"])
    if compare_to is None:
        if loaded["status"] == "unreadable":
            text = (f"the baseline could not be read, so nothing was compared "
                    f"(the file is kept): {loaded['reason']}")
            notes.append(("baseline", text))
        chosen, file_name = loaded, None
    else:
        if loaded["status"] == "unreadable":
            text = (f"the latest baseline could not be read; sources not read in this run "
                    f"keep nothing (the file is kept): {loaded['reason']}")
            notes.append(("baseline", text))
        chosen = load_reference(state_dir, skill, elevated, days, now)
        file_name = chosen["file"]
        if chosen["status"] != "read":
            reasons.append(chosen["reason"])
        if chosen["status"] == "unreadable":
            text = (f"the reference baseline {file_name or HISTORY_DIR} could not be read, "
                    f"so nothing was compared: {chosen['reason']}")
            notes.append(("reference baseline", text))
    compared = chosen["status"] == "read"
    info = {
        "status": "compared" if compared else chosen["status"],
        "created_at": chosen["created_at"] if compared else None,
        "age_days": age_days(chosen["created_at"], now) if compared else None,
        "reason": reasons,
        "reference": compare_to or "latest",
        "reference_file": file_name,
    }
    return {"sources": chosen["sources"] if compared else {}, "info": info,
            "notes": notes}

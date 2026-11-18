"""Review dates: ``<data dir>/state/review-dates.json`` (plans 063, 077, B-03, B-04, B-17).

The file holds ``{"schema_version": 1, "entries": [...]}``. Each entry is
``{kind, key, name, decided_on, period, review_on}``: ``kind`` is ``program`` (an
inventory program, key ``win32:...``, ``msix:...`` or ``portable:...``) or ``package`` (a pip or npm
package, key ``pip:...`` or ``npm:...``), ``key`` the child's stable key, ``name`` the
name at decision time (a string, or ``null`` for a pip package whose metadata was not
read), ``decided_on`` the local date of the decision, ``period`` ``<N>d``, ``<N>m``,
``<N>y`` or ``none``, and ``review_on`` the local date the user wants to look again
(``null`` for ``none``). Dates are ISO ``YYYY-MM-DD``.

``load`` reads the file and never raises. The script has three actions; exactly one is
given per call:

- ``--set r<n>[,r<n>...]=<N>d|<N>m|<N>y|none`` (repeatable, one group per period)
  ``--detail-file <runall detail file> --data-dir <dir>``, on the user's word: it writes
  one entry per id from the runall detail file's ``review`` section, every group or none,
  as one generation, with a verified write. With no ``review-dates.json`` yet, an empty
  file is written first, so the first write also leaves a previous generation.
- ``--list --detail-file <runall detail file>``: read-only; prints the detail file's
  ``review`` items (``id``, ``kind``, ``name``, the key prefix, ``state``) and their counts.
- ``--undo``: writes ``review-dates.previous.json`` back as ``review-dates.json``.

``local_date(now)`` is the one helper that turns a run time into the local date compared
with ``review_on`` (and stored as ``decided_on``). The script judges nothing: the dates
are the user's.
"""

import argparse
import calendar
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# load_script does not put this directory on sys.path; baseline lives next to this file.
_HERE = str(Path(__file__).absolute().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import baseline
import datadir

FILE_STEM = "review-dates"
FILE_NAME = f"{FILE_STEM}.json"
PREVIOUS_NAME = f"{FILE_STEM}.previous.json"
SCHEMA_VERSION = 1
KINDS = ("program", "package")
NO_PERIOD = "none"
PERIOD = re.compile(r"[1-9][0-9]*[dmy]")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SETTABLE = ("no_decision", "due", "not_due", "no_limit")
# The review states of runall.py (REVIEW_STATES); --list counts each, zero included.
STATES = ("due", "gone", "not_checked", "no_decision", "not_due", "no_limit")
EMPTY = {"schema_version": SCHEMA_VERSION, "entries": []}


def local_date(now) -> date:
    """The local date of the aware time ``now`` (the machine's zone)."""
    return now.astimezone().date()


def parse_date(value):
    """The ``date`` of an ISO ``YYYY-MM-DD`` string, or None."""
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def period_ok(value) -> bool:
    return value == NO_PERIOD or (isinstance(value, str) and bool(PERIOD.fullmatch(value)))


def review_on(decided_on: date, period: str):
    """The date ``period`` after ``decided_on``; None for ``none``. Months and years
    are calendar ones; a day past the end of the target month becomes its last day."""
    if period == NO_PERIOD:
        return None
    count, unit = int(period[:-1]), period[-1]
    if unit == "d":
        return decided_on + timedelta(days=count)
    months = count * (12 if unit == "y" else 1)
    year, month = divmod(decided_on.month - 1 + months, 12)
    year += decided_on.year
    month += 1
    return date(year, month, min(decided_on.day, calendar.monthrange(year, month)[1]))


def _check(data):
    """``(problem or None, entries)`` of the parsed file."""
    if not isinstance(data, dict):
        return "the file is not an object", None
    if data.get("schema_version") != SCHEMA_VERSION:
        return (f"schema_version {data.get('schema_version')!r} is not "
                f"{SCHEMA_VERSION}"), None
    entries = data.get("entries")
    if not isinstance(entries, list):
        return "entries is not a list", None
    seen = set()
    for n, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            return f"entry {n} is not an object", None
        kind, key = entry.get("kind"), entry.get("key")
        if kind not in KINDS:
            return f"entry {n}: kind {kind!r} is not one of {KINDS}", None
        if not isinstance(key, str) or not key.strip():
            return f"entry {n}: key {key!r} is not a non-empty string", None
        if (kind, key) in seen:
            return f"entry {n}: kind {kind!r} and key {key!r} are there twice", None
        seen.add((kind, key))
        name = entry.get("name")
        if name is not None and not isinstance(name, str):
            return f"entry {n}: name {name!r} is neither a string nor null", None
        if parse_date(entry.get("decided_on")) is None:
            return f"entry {n}: decided_on {entry.get('decided_on')!r} is not a date", None
        period = entry.get("period")
        if not period_ok(period):
            return (f"entry {n}: period {period!r} is not <N>d, <N>m, <N>y or "
                    f"{NO_PERIOD}"), None
        review_on = entry.get("review_on")
        if period == NO_PERIOD:
            if review_on is not None:
                return f"entry {n}: review_on {review_on!r} must be null for period none", None
        elif parse_date(review_on) is None:
            return f"entry {n}: review_on {review_on!r} is not a date", None
    return None, entries


def file_path(data_dir) -> Path:
    return Path(data_dir).absolute() / "state" / FILE_NAME


def previous_path(data_dir) -> Path:
    return Path(data_dir).absolute() / "state" / PREVIOUS_NAME


def load(data_dir) -> dict:
    """``{status, reason, path, entries}`` of ``<data_dir>/state/review-dates.json``.

    ``status`` is ``none`` (no file; ``entries`` ``[]``), ``read``, or ``unreadable``
    (cannot be read, bad JSON or a bad shape; ``reason`` names the problem and
    ``entries`` is ``[]``). Never raises."""
    return _load_path(file_path(data_dir))


def _load_path(path: Path) -> dict:
    """``load`` of the review dates file at ``path`` (``review-dates.json`` or its
    previous generation)."""
    name = path.name
    result = {"status": "none", "reason": None, "path": str(path), "entries": []}
    try:
        if not path.exists():
            return result
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return dict(result, status="unreadable", reason=f"cannot read {name}: {exc}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        return dict(result, status="unreadable", reason=f"{name} is not JSON: {exc}")
    problem, entries = _check(data)
    if problem is not None:
        return dict(result, status="unreadable", reason=f"{name}: {problem}")
    return dict(result, status="read", entries=entries)


def _review_items(detail_file):
    """``(items by id, None)`` of the runall detail file's ``review`` list, or
    ``(None, reason)``."""
    try:
        data = json.loads(Path(detail_file).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"cannot read the runall detail file {detail_file}: {exc}"
    review = data.get("review") if isinstance(data, dict) else None
    if not isinstance(review, list):
        return None, f"the runall detail file {detail_file} has no review list"
    return {item["id"]: item for item in review
            if isinstance(item, dict) and isinstance(item.get("id"), str)}, None


def _groups(groups):
    """``(list of (ids, period), None)`` of the ``--set`` groups, or ``(None, reason)``."""
    if not groups:
        return None, "no --set group was given"
    parsed, seen = [], {}
    for group in groups:
        text = group if isinstance(group, str) else ""
        ids_text, sep, period = text.partition("=")
        if not sep:
            return None, (f"--set {group!r} is not r<n>[,r<n>...]=<N>d|<N>m|<N>y|"
                          f"{NO_PERIOD}")
        period = period.strip()
        if not period_ok(period):
            return None, (f"--set {group!r}: period {period!r} is not <N>d, <N>m, <N>y or "
                          f"{NO_PERIOD}")
        wanted = [part.strip() for part in ids_text.split(",")]
        if any(not part for part in wanted):
            return None, f"--set {group!r}: the ids are not r<n>[,r<n>...]"
        ids = list(dict.fromkeys(wanted))
        for item_id in ids:
            if item_id in seen:
                return None, (f"{item_id} is in two --set groups ({seen[item_id]!r} and "
                              f"{group!r})")
            seen[item_id] = group
        parsed.append((ids, period))
    return parsed, None


def _saved_only(failure) -> bool:
    # The verified new file is in place; only the previous generation failed.
    return failure.startswith(f"the new {FILE_NAME} is saved, but ")


def _write(path: Path, entries: list):
    """Write ``entries`` through ``baseline.save_json``: ``(None, None)``, ``(None,
    warning)`` when only the previous generation was not replaced, or ``(reason, None)``.

    With no ``review-dates.json`` yet, an empty file is written first, so the first write
    also leaves a previous generation (no review dates) for ``--undo``."""
    def validate(old):
        return _check(old)[0]

    if not path.exists():
        failure = baseline.save_json(path.parent, FILE_STEM, EMPTY, validate)
        if failure is not None and not _saved_only(failure):
            return f"{FILE_NAME} not saved: {failure}", None
    failure = baseline.save_json(path.parent, FILE_STEM,
                                 {"schema_version": SCHEMA_VERSION, "entries": entries},
                                 validate)
    if failure is not None and _saved_only(failure):
        return None, failure
    if failure is not None:
        return f"{FILE_NAME} not saved: {failure}", None
    return None, None


def set_dates(groups, detail_file, data_dir, today=None) -> dict:
    """Write one entry per id of each group of ``groups`` (``["r1,r3=1y", "r2=none"]``)
    with that group's period, every group or none; the printed result ``{ok, keys, path}``
    (with ``warning`` when the file was saved but its ``.previous`` copy was not
    replaced) or ``{ok: false, reason, keys, path}``."""
    path = file_path(data_dir)
    refused = {"ok": False, "keys": [], "path": str(path)}
    parsed, reason = _groups(groups)
    if parsed is None:
        return dict(refused, reason=reason)
    current = load(data_dir)
    if current["status"] == "unreadable":
        return dict(refused, reason=(f"{current['reason']}; it is left as it is: correct "
                                     "or move it first"))
    items, reason = _review_items(detail_file)
    if items is None:
        return dict(refused, reason=reason)
    today = today or local_date(datetime.now().astimezone())
    new = []
    for ids, period in parsed:
        try:
            due = review_on(today, period)
        except (ValueError, OverflowError):
            return dict(refused, reason=f"period {period!r} gives a date past year 9999")
        for item_id in ids:
            item = items.get(item_id)
            if item is None:
                return dict(refused, reason=f"{item_id} is not a review item of that pass")
            if item.get("state") not in SETTABLE:
                return dict(refused, reason=(f"{item_id} is in state {item.get('state')!r}; "
                                             f"only {', '.join(SETTABLE)} can get a date"))
            kind, key, name = item.get("kind"), item.get("key"), item.get("name")
            if kind not in KINDS or not isinstance(key, str) or not key.strip() or not (
                    name is None or isinstance(name, str)):
                return dict(refused, reason=f"{item_id} has no valid kind, key and name")
            new.append({"kind": kind, "key": key, "name": name,
                        "decided_on": today.isoformat(), "period": period,
                        "review_on": None if due is None else due.isoformat()})
    replaced = {(entry["kind"], entry["key"]) for entry in new}
    entries = [entry for entry in current["entries"]
               if (entry.get("kind"), entry.get("key")) not in replaced]
    entries += new
    problem, _ = _check({"schema_version": SCHEMA_VERSION, "entries": entries})
    if problem is not None:
        return dict(refused, reason=f"{FILE_NAME} would not be valid: {problem}")
    reason, warning = _write(path, entries)
    if reason is not None:
        return dict(refused, reason=reason)
    saved = {"ok": True, "keys": [entry["key"] for entry in new], "path": str(path)}
    return saved if warning is None else dict(saved, warning=warning)


def list_items(detail_file) -> dict:
    """The printed result of ``--list``: ``{ok, detail_file, items, counts}`` of the runall
    detail file's ``review`` list, in file order (read-only), or ``{ok: false, reason}``.
    ``prefix`` is the key up to and including its first ``:``; the full key is not
    printed."""
    detail_file = str(Path(detail_file).absolute())
    items, reason = _review_items(detail_file)
    if items is None:
        return {"ok": False, "detail_file": detail_file, "reason": reason}
    listed = []
    by_state = dict.fromkeys(STATES, 0)
    by_kind = dict.fromkeys(KINDS, 0)
    for item_id, item in items.items():
        key, state, kind = item.get("key"), item.get("state"), item.get("kind")
        prefix = key[:key.index(":") + 1] if isinstance(key, str) and ":" in key else None
        listed.append({"id": item_id, "kind": kind, "name": item.get("name"),
                       "prefix": prefix, "state": state})
        by_state[str(state)] = by_state.get(str(state), 0) + 1
        by_kind[str(kind)] = by_kind.get(str(kind), 0) + 1
    return {"ok": True, "detail_file": detail_file, "items": listed,
            "counts": {"by_state": by_state, "by_kind": by_kind}}


def undo(data_dir) -> dict:
    """Write the previous generation back as ``review-dates.json``; the printed result
    ``{ok, entry_count, path}`` (with ``warning``) or ``{ok: false, reason, ...}``."""
    path = file_path(data_dir)
    refused = {"ok": False, "entry_count": None, "path": str(path)}
    current = load(data_dir)
    if current["status"] == "unreadable":
        return dict(refused, reason=(f"{current['reason']}; it is left as it is: correct "
                                     "or move it first"))
    previous = _load_path(previous_path(data_dir))
    if previous["status"] == "none":
        return dict(refused, reason=f"there is no {PREVIOUS_NAME}: no write to undo")
    if previous["status"] != "read":
        return dict(refused, reason=f"{previous['reason']}; nothing was written")
    entries = previous["entries"]
    reason, warning = _write(path, entries)
    if reason is not None:
        return dict(refused, reason=reason)
    now = load(data_dir)
    if now["status"] != "read" or now["entries"] != entries:
        return dict(refused, reason=(f"{FILE_NAME} was written, but it does not read back "
                                     f"as {PREVIOUS_NAME} held it ({now['status']}: "
                                     f"{now['reason']})"))
    saved = {"ok": True, "entry_count": len(entries), "path": str(path)}
    return saved if warning is None else dict(saved, warning=warning)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--set", action="append", metavar="r<n>[,r<n>...]=<period>",
                        help="review items and their period <N>d, <N>m, <N>y or none; "
                             "repeat for another period")
    action.add_argument("--list", action="store_true",
                        help="print the review items of the runall detail file (read-only)")
    action.add_argument("--undo", action="store_true",
                        help="write the previous generation of review-dates.json back")
    parser.add_argument("--detail-file",
                        help="the runall detail file of the pass the ids come from "
                             "(required with --set and --list)")
    datadir.add_arguments(parser)
    args = parser.parse_args(argv)
    if args.undo and args.detail_file is not None:
        parser.error("--detail-file is not used with --undo")
    if not args.undo and args.detail_file is None:
        parser.error("--detail-file is required with --set and --list")
    if args.list:
        # Read-only: the detail file is all --list reads; no data directory is needed.
        result = list_items(args.detail_file)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    try:
        data_dir = datadir.resolve(args.data_dir, default=args.default_data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    if args.undo:
        result = undo(data_dir)
    else:
        result = set_dates(args.set, Path(args.detail_file).absolute(), data_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

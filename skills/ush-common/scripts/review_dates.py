"""Review dates: ``<data dir>/state/review-dates.json`` (plan 063, B-03, B-04, B-17).

The file holds ``{"schema_version": 1, "entries": [...]}``. Each entry is
``{kind, key, name, decided_on, period, review_on}``: ``kind`` is ``program`` (an
inventory program, key ``win32:...`` or ``msix:...``) or ``package`` (a pip or npm
package, key ``pip:...`` or ``npm:...``), ``key`` the child's stable key, ``name`` the
name at decision time (a string, or ``null`` for a pip package whose metadata was not
read), ``decided_on`` the local date of the decision, ``period`` ``<N>d``, ``<N>m``,
``<N>y`` or ``none``, and ``review_on`` the local date the user wants to look again
(``null`` for ``none``). Dates are ISO ``YYYY-MM-DD``.

``load`` reads the file and never raises. On the user's word the model runs
``review_dates.py --set r<n>[,r<n>...] --period <N>d|<N>m|<N>y|none --detail-file
<runall detail file> --data-dir <dir>``: it writes one entry per id from the runall
detail file's ``review`` section, all or nothing, with a verified write. ``local_date(now)`` is the one helper that
turns a run time into the local date compared with ``review_on`` (and stored as
``decided_on``). The script judges nothing: the dates are the user's.
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
SCHEMA_VERSION = 1
KINDS = ("program", "package")
NO_PERIOD = "none"
PERIOD = re.compile(r"[1-9][0-9]*[dmy]")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SETTABLE = ("no_decision", "due", "not_due", "no_limit")


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


def load(data_dir) -> dict:
    """``{status, reason, path, entries}`` of ``<data_dir>/state/review-dates.json``.

    ``status`` is ``none`` (no file; ``entries`` ``[]``), ``read``, or ``unreadable``
    (cannot be read, bad JSON or a bad shape; ``reason`` names the problem and
    ``entries`` is ``[]``). Never raises."""
    path = file_path(data_dir)
    result = {"status": "none", "reason": None, "path": str(path), "entries": []}
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
    problem, entries = _check(data)
    if problem is not None:
        return dict(result, status="unreadable", reason=f"{FILE_NAME}: {problem}")
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


def set_dates(ids: str, period: str, detail_file, data_dir, today=None) -> dict:
    """Write one entry per id of ``ids`` (``r1,r3``) with ``period``, all or nothing;
    the printed result ``{ok, keys, path}`` (with ``warning`` when the file was saved
    but its ``.previous`` copy was not replaced) or ``{ok: false, reason, keys, path}``."""
    path = file_path(data_dir)
    refused = {"ok": False, "keys": [], "path": str(path)}
    if not period_ok(period):
        return dict(refused, reason=(f"--period {period!r} is not <N>d, <N>m, <N>y or "
                                     f"{NO_PERIOD}"))
    wanted = [part.strip() for part in ids.split(",")]
    if not wanted or any(not part for part in wanted):
        return dict(refused, reason=f"--set {ids!r} is not r<n>[,r<n>...]")
    current = load(data_dir)
    if current["status"] == "unreadable":
        return dict(refused, reason=(f"{current['reason']}; it is left as it is: correct "
                                     "or move it first"))
    items, reason = _review_items(detail_file)
    if items is None:
        return dict(refused, reason=reason)
    today = today or local_date(datetime.now().astimezone())
    try:
        due = review_on(today, period)
    except (ValueError, OverflowError):
        return dict(refused, reason=f"--period {period!r} gives a date past year 9999")
    new = []
    for item_id in dict.fromkeys(wanted):
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
    data = {"schema_version": SCHEMA_VERSION, "entries": entries}
    problem, _ = _check(data)
    if problem is not None:
        return dict(refused, reason=f"{FILE_NAME} would not be valid: {problem}")
    failure = baseline.save_json(path.parent, FILE_STEM, data, lambda old: _check(old)[0])
    saved = {"ok": True, "keys": [entry["key"] for entry in new], "path": str(path)}
    if failure is not None and failure.startswith(f"the new {FILE_NAME} is saved, but "):
        # The verified new file is in place; only the previous generation failed.
        return dict(saved, warning=failure)
    if failure is not None:
        return dict(refused, reason=f"{FILE_NAME} not saved: {failure}")
    return saved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", required=True, metavar="r<n>[,r<n>...]",
                        help="the review items of the runall pass to give a date")
    parser.add_argument("--period", required=True, metavar="<N>d|<N>m|<N>y|none",
                        help="when to look again, counted from today")
    parser.add_argument("--detail-file", required=True,
                        help="the runall detail file of the pass the items come from")
    datadir.add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        data_dir = datadir.resolve(args.data_dir, default=args.default_data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    result = set_dates(args.set, args.period, Path(args.detail_file).absolute(), data_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

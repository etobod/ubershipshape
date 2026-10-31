"""Stable item ids across runs: the map from a stable item key to its number.

A skill keeps one map in ``<data dir>/state/<skill>.ids.json`` (the same file for a run
with and without administrator rights):

    {"version": 1, "skill": "<skill>",
     "prefixes": {"x": {"next": 18, "keys": {"<key>": {"n": 17, "seen": "2026-10-03"}}}}}

- ``load_map`` never raises on a bad file: it gives an empty map and the reason, and the
  skill reports that the numbering started again. The bad file is kept by ``save_map``
  (through ``baseline.save_json``) as ``<skill>.ids.unreadable-<UTC stamp>.json``.
- ``assign`` gives a known key its number and a new key the next free number; a number
  is never given back, so an item that went away does not pass its id to another one.
  A key repeated within one call, and an item without a key, get a one-time number that
  is not kept in the map.
- ``save_map`` drops keys not seen for more than ``KEEP_DAYS`` days, never lowers ``next``
  and writes with a verification read.

Dates are ISO date strings (``YYYY-MM-DD``). The map functions touch only the state
directory; ``read_cut`` only reads a detail file and the summary it names.
"""

import copy
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# load_script does not put this directory on sys.path; baseline lives next to this file.
_HERE = str(Path(__file__).absolute().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import baseline

VERSION = 1
KEEP_DAYS = 90


def map_name(skill):
    """File stem of the map: ``<skill>.ids``."""
    return f"{skill}.ids"


def empty_map(skill):
    return {"version": VERSION, "skill": skill, "prefixes": {}}


def _is_date(value):
    """A ``YYYY-MM-DD`` text that is a real date (no week or basic ISO forms)."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_map(data, skill):
    """Return None when ``data`` is a valid id map of ``skill``, else a reason."""
    if not isinstance(data, dict):
        return "id map is not a JSON object"
    if data.get("version") != VERSION:
        return f"version is {data.get('version')!r}, expected {VERSION}"
    if data.get("skill") != skill:
        return f"skill is {data.get('skill')!r}, expected {skill!r}"
    prefixes = data.get("prefixes")
    if not isinstance(prefixes, dict):
        return "prefixes is not an object"
    for prefix, entry in prefixes.items():
        if not isinstance(entry, dict):
            return f"prefix {prefix!r} is not an object"
        nxt, keys = entry.get("next"), entry.get("keys")
        if not _is_count(nxt) or nxt < 1:
            return f"next of prefix {prefix!r} is not a positive whole number"
        if not isinstance(keys, dict):
            return f"keys of prefix {prefix!r} is not an object"
        numbers = set()
        # A key can hold a path, an account or a serial number: name its place, not it.
        for place, record in enumerate(keys.values(), 1):
            if not isinstance(record, dict):
                return f"key number {place} of prefix {prefix!r} is not an object"
            number = record.get("n")
            if not _is_count(number) or not 1 <= number < nxt:
                return (f"n of key number {place} of prefix {prefix!r} is not between "
                        f"1 and next")
            if number in numbers:
                return f"number {number} of prefix {prefix!r} is given to two keys"
            numbers.add(number)
            if not _is_date(record.get("seen")):
                return (f"seen of key number {place} of prefix {prefix!r} is not an "
                        f"ISO date")
    return None


def load_map(state_dir, skill):
    """Load the id map of ``skill``: ``(id_map, reason)``.

    No file gives an empty map and ``None``; an unreadable or malformed file gives an empty
    map and the reason. Never raises on a bad file and never changes it.
    """
    path = Path(state_dir).absolute() / f"{map_name(skill)}.json"
    if not path.exists():
        return empty_map(skill), None
    data, reason = baseline._read(path)
    if reason is None:
        reason = check_map(data, skill)
    if reason is not None:
        return empty_map(skill), f"{path.name}: {reason}"
    return data, None


def assign(id_map, prefix, items, key_of, today):
    """Set ``item["id"]`` to ``<prefix><number>`` for each item, in the order given.

    ``key_of(item)`` gives the stable key (a string) or ``None``. A known key keeps its
    number and its ``seen`` becomes ``today``; a new key takes ``next``. The second and later
    item with the same key in this call, and an item whose key is ``None``, take a one-time
    number (``next``, not kept). Returns the repeated keys, each once, in order of first
    repetition.
    """
    if not _is_date(today):
        raise ValueError(f"today is not a YYYY-MM-DD date: {today!r}")
    entry = id_map["prefixes"].setdefault(prefix, {"next": 1, "keys": {}})
    keys = entry["keys"]
    used, repeated = set(), []
    for item in items:
        key = key_of(item)
        if key is not None and not isinstance(key, str):
            raise TypeError(f"key of an item with prefix {prefix!r} is not a string: {key!r}")
        if key is None or key in used:
            if key is not None and key not in repeated:
                repeated.append(key)
            number = entry["next"]
            entry["next"] += 1
        else:
            used.add(key)
            record = keys.get(key)
            if record is None:
                record = {"n": entry["next"]}
                entry["next"] += 1
                keys[key] = record
            record["seen"] = today
            number = record["n"]
        item["id"] = f"{prefix}{number}"
    return repeated


def _started_from(saved, current):
    """True when ``current`` (one prefix of the map in memory) grew from ``saved``: every
    saved key keeps its number and ``next`` did not go back."""
    if current is None:
        return False
    if current["next"] < saved["next"]:
        return False
    return all(current["keys"].get(key, {}).get("n") == record["n"]
               for key, record in saved["keys"].items())


# A save_map reason that starts with this: the new map is in place.
SAVED_BUT = "the id map was saved, but its previous copy was not: "


def save_map(state_dir, skill, id_map, today):
    """Write the map of ``skill``; return None, or a reason on failure.

    Keys whose ``seen`` is more than ``KEEP_DAYS`` days before ``today`` are left out;
    ``next`` stays as it is. The write is ``baseline.save_json`` with a verification read;
    an old file that is not a valid map is kept as ``<skill>.ids.unreadable-<stamp>.json``.
    A valid saved map that ``id_map`` did not start from (a saved key missing or with
    another number, or a higher saved ``next``) is never replaced.
    """
    try:
        limit = date.fromisoformat(today).toordinal() - KEEP_DAYS
    except (TypeError, ValueError) as exc:
        return f"today is not an ISO date: {exc}"
    reason = check_map({**id_map, "skill": skill}, skill)
    if reason is not None:
        return f"id map to save is not valid: {reason}"
    path = Path(state_dir).absolute() / f"{map_name(skill)}.json"
    if path.exists():
        saved, unread = baseline._read(path)
        if unread is None and check_map(saved, skill) is None:
            behind = sorted(prefix for prefix, entry in saved["prefixes"].items()
                            if not _started_from(entry, id_map["prefixes"].get(prefix)))
            if behind:
                # This run did not start from the saved map (it could not be read then,
                # but can be now): writing would give its numbers to other items.
                return (f"{path.name} holds numbers this run did not start from "
                        f"(prefixes {', '.join(behind)}); the saved map is kept as it is")
    data = empty_map(skill)
    for prefix, entry in id_map["prefixes"].items():
        kept = {key: copy.deepcopy(record) for key, record in entry["keys"].items()
                if date.fromisoformat(record["seen"]).toordinal() >= limit}
        data["prefixes"][prefix] = {"next": entry["next"], "keys": kept}
    reason = baseline.save_json(state_dir, map_name(skill), data,
                                lambda old: check_map(old, skill))
    if reason is not None and reason.startswith(f"the new {path.name} is saved, but "):
        # save_json put the verified new map in place and failed only afterwards, on
        # the previous generation; an unchanged map on disk proves nothing about that.
        return SAVED_BUT + reason
    return reason


def item_key(item):
    """The default stable key of an item: its ``key`` field."""
    return item.get("key")


class Numbering:
    """The numbering of one run: ``assign`` over one map, with the items that took a
    one-time number because their key came twice or could not be read, per prefix.

    ``fresh`` gives a numbering over an empty map (the numbers are the places in the
    list), for a caller without a map, such as a test of one list builder.
    """

    def __init__(self, id_map, today):
        self.id_map = id_map
        self.today = today
        self.one_time = {}  # {prefix: [id of an item whose key came twice, ...]}
        self.keyless = {}  # {prefix: [id of an item without a key, ...]}

    @classmethod
    def fresh(cls, skill):
        return cls(empty_map(skill), datetime.now(timezone.utc).date().isoformat())

    def assign(self, prefix, items, key_of=item_key):
        items = list(items)
        repeated = set(assign(self.id_map, prefix, items, key_of, self.today))
        for item in items:
            if key_of(item) is None:
                self.keyless.setdefault(prefix, []).append(item["id"])
        if not repeated:
            return
        keys = self.id_map["prefixes"][prefix]["keys"]
        for item in items:
            key = key_of(item)
            if key in repeated and item["id"] != f"{prefix}{keys[key]['n']}":
                self.one_time.setdefault(prefix, []).append(item["id"])

    def repeated_notes(self):
        """``[(what, reason)]`` for ``not_checked``: one per prefix with repeated or
        missing keys. Names the ids, never the keys (a key can hold a path or an
        account)."""
        notes = []
        for prefix in sorted(set(self.one_time) | set(self.keyless)):
            parts = []
            given = self.one_time.get(prefix)
            if given:
                parts.append(f"{len(given)} items had the same key as an item listed "
                             f"before them: {', '.join(given)}")
            given = self.keyless.get(prefix)
            if given:
                parts.append(f"{len(given)} items had no key that could be read: "
                             f"{', '.join(given)}")
            reason = "; ".join(parts) + "; these ids are kept for this run only"
            notes.append((f"stable ids {prefix}", reason))
        return notes


def load_note(reason):
    """``(what, reason)`` for ``not_checked`` when ``load_map`` gave a reason."""
    text = (f"the id map could not be read, so the numbering started again "
            f"(the file is kept when the new map is saved): {reason}")
    return ("stable ids", text)


def save_note(reason):
    """``(what, reason)`` for ``not_checked`` when ``save_map`` gave a reason."""
    if reason.startswith(SAVED_BUT):
        text = (f"{reason}; the next run keeps this run's ids")
    else:
        text = (f"the id map was not saved, so the next run may give other ids; "
                f"this run's ids hold: {reason}")
    return ("stable ids save", text)


# --- cut items ------------------------------------------------------------------

def default_label(item):
    return item.get("name")


def summary_ids(summary):
    """The ids of the items in the top-level lists of a summary. An id only named
    inside an item (such as a partner of a program) does not count."""
    found = set()
    for value in summary.values():
        if isinstance(value, list):
            found.update(item["id"] for item in value
                         if isinstance(item, dict) and isinstance(item.get("id"), str))
    return found


def cut_items(detail, summary, labels=None):
    """The listable items of ``detail`` missing from ``summary``: ``[{id, list, name}]``.

    ``detail["listed"]`` is ``{list name: [id, ...]}`` (the ids before the budget cut).
    ``labels`` maps a list name to a function that gives the ``name`` of one item of
    the detail list of that name; a list without one uses the item's ``name``. An id
    the detail list does not hold gets ``name`` null. Raises ``ValueError`` naming the
    field when ``listed`` is missing or malformed.
    """
    labels = labels or {}
    listed = detail.get("listed")
    if not isinstance(listed, dict) or not all(
            isinstance(ids, list) and all(isinstance(i, str) for i in ids)
            for ids in listed.values()):
        raise ValueError("the detail file has no valid field 'listed'")
    in_summary = summary_ids(summary)
    result = []
    for name, listed_ids in listed.items():
        by_id = {item["id"]: item for item in detail.get(name) or []
                 if isinstance(item, dict) and isinstance(item.get("id"), str)}
        label = labels.get(name, default_label)
        for item_id in listed_ids:
            if item_id in in_summary:
                continue
            item = by_id.get(item_id)
            result.append({"id": item_id, "list": name,
                           "name": label(item) if item is not None else None})
    return result


def _read_object(path, what):
    """``(object, None)`` or ``(None, message)``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{what} {path} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"{what} {path} does not hold a JSON object"
    return data, None


def read_cut(detail_path, labels=None):
    """``cut_items`` of a detail file and the summary its ``summary_file`` names:
    ``({detail_file, summary_file, cut}, None)``, or ``(None, message)`` when a file or
    the field ``listed`` or ``summary_file`` is missing or unreadable."""
    detail, reason = _read_object(detail_path, "detail file")
    if reason is not None:
        return None, reason
    summary_file = detail.get("summary_file")
    if not isinstance(summary_file, str) or not summary_file:
        return None, f"the detail file {detail_path} has no field 'summary_file'"
    if "listed" not in detail:
        return None, f"the detail file {detail_path} has no field 'listed'"
    summary, reason = _read_object(summary_file, "summary file")
    if reason is not None:
        return None, reason
    try:
        cut = cut_items(detail, summary, labels)
    except ValueError as exc:
        return None, f"{detail_path}: {exc}"
    return {"detail_file": str(detail_path), "summary_file": summary_file, "cut": cut}, None

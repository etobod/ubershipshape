"""Accepted findings: ``<data dir>/state/accepted.json`` (plan 060, B-23, B-24).

The file holds ``{"schema_version": 1, "entries": [...]}``. Each entry is
``{kind, key, skill, evidence, accepted_on, facts}``: ``kind`` is a kind of
``data/accepted-kinds.json``, ``key`` the item's key by that kind (one field's value, or
the list of the key fields' values), ``evidence`` the ``"<skill> <id>"`` the user accepted,
``accepted_on`` the local date, and ``facts`` the kind's fields copied from the child's
detail item at that time.

``load`` reads the file and never raises. The command line writes one entry:

    accepted.py --accept "<skill> <id>" --detail-file <runall detail file> --data-dir <dir>

It finds the child in the runall detail file (``children[]``, its summary's
``detail_file``), the item in that child's detail file, and saves the file through
``baseline.save_json``; an entry with the same kind and key is replaced. It prints
``{ok, key, kind, path}``, or ``ok`` false with ``reason``; a refusal writes nothing.

    accepted.py --remove "ush-runall a<n>" --detail-file <runall detail file> --data-dir <dir>

removes the entry with the kind and key of item ``a<n>`` of the runall detail file's
``accepted`` list, through the same verified write and with the same output.

Each write keeps the file before it as ``state/accepted.previous.json`` (one generation);
the first write ever first writes an empty accepted file, so that generation exists then too.

    accepted.py --undo --data-dir <dir>

checks ``accepted.previous.json`` as ``load`` checks ``accepted.json``, writes its entries
through the same verified write (the current file becomes the previous generation, so a
second ``--undo`` goes back again), reads the result back and prints ``{ok, entry_count,
path}``, or ``ok`` false with ``reason``; with no previous file it refuses and writes
nothing. ``warning`` (all three actions): the new file is saved, but the previous
generation was not replaced, so ``--undo`` does not restore the state before this write.
The script judges nothing: the user decides what to accept.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# load_script does not put this directory on sys.path; baseline lives next to this file.
_HERE = str(Path(__file__).absolute().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import baseline
import datadir

FILE_STEM = "accepted"
FILE_NAME = f"{FILE_STEM}.json"
SCHEMA_VERSION = 1
KINDS_FILE = Path(__file__).absolute().parents[1] / "data" / "accepted-kinds.json"
HOW = ("changed", "rises", "later")
FACT_LIST = "facts[]."


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _check_kinds(data):
    """``(problem or None, kinds)`` of the parsed kinds file."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return "the kinds file has no schema_version 1", None
    kinds = data.get("kinds")
    if not isinstance(kinds, dict) or not kinds:
        return "the kinds file has no kinds", None
    for name, kind in kinds.items():
        if not isinstance(kind, dict):
            return f"kind {name!r} is not an object", None
        for field in ("skill", "section"):
            if not _text(kind.get(field)):
                return f"kind {name!r}: {field} must be a non-empty string", None
        key = kind.get("key")
        if not (_text(key) or (isinstance(key, list) and key and all(map(_text, key)))):
            return f"kind {name!r}: key must be a field or a list of fields", None
        facts = kind.get("facts")
        if not isinstance(facts, list) or not all(map(_text, facts)):
            return f"kind {name!r}: facts must be a list of fields", None
        watched = kind.get("watched")
        if not isinstance(watched, dict) or not watched:
            return f"kind {name!r}: watched must be a non-empty object", None
        for field, how in watched.items():
            if how not in HOW:
                return f"kind {name!r}: watched {field!r} is {how!r}, not one of {HOW}", None
            top = "facts" if field.startswith(FACT_LIST) else field
            if top not in facts:
                return f"kind {name!r}: watched {field!r} is not a kept fact", None
        match = kind.get("match", {})
        if not isinstance(match, dict):
            return f"kind {name!r}: match must be an object", None
        source = kind.get("source", {})
        if not isinstance(source, dict):
            return f"kind {name!r}: source must be an object", None
        for field, value in source.items():
            if isinstance(value, str) and value.startswith("@") and value[1:] not in facts:
                return f"kind {name!r}: source {field!r} names {value!r}, not a kept fact", None
    return None, kinds


def load_kinds(path=KINDS_FILE):
    """``(kinds, None)`` of the kinds file, or ``(None, reason)``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"cannot read {Path(path).name}: {exc}"
    problem, kinds = _check_kinds(data)
    if problem is not None:
        return None, f"{Path(path).name}: {problem}"
    return kinds, None


def key_of(kind: dict, item: dict):
    """The key of ``item`` by ``kind``: one value, or the list of the key fields' values."""
    key = kind["key"]
    if isinstance(key, list):
        return [item.get(field) for field in key]
    return item.get(key)


def _key_ok(kind: dict, key) -> bool:
    if isinstance(kind["key"], list):
        return (isinstance(key, list) and len(key) == len(kind["key"])
                and all(value is not None for value in key))
    return key is not None and not isinstance(key, (list, dict))


def _check(data, kinds):
    """``(problem or None, entries)`` of the parsed accepted file."""
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
        name = entry.get("kind")
        if name not in kinds:
            return f"entry {n}: kind {name!r} is not in {KINDS_FILE.name}", None
        if not _key_ok(kinds[name], entry.get("key")):
            return f"entry {n}: key {entry.get('key')!r} does not fit kind {name!r}", None
        marker = (name, json.dumps(entry["key"], sort_keys=True))
        if marker in seen:
            return f"entry {n}: kind {name!r} and key {entry['key']!r} are there twice", None
        seen.add(marker)
        try:
            date.fromisoformat(entry.get("accepted_on"))
        except (TypeError, ValueError):
            return f"entry {n}: accepted_on {entry.get('accepted_on')!r} is not a date", None
        if not isinstance(entry.get("facts"), dict):
            return f"entry {n}: facts is not an object", None
    return None, entries


PREVIOUS_NAME = f"{FILE_STEM}.previous.json"
EMPTY = {"schema_version": SCHEMA_VERSION, "entries": []}


def file_path(data_dir) -> Path:
    return Path(data_dir).absolute() / "state" / FILE_NAME


def previous_path(data_dir) -> Path:
    return Path(data_dir).absolute() / "state" / PREVIOUS_NAME


def load(data_dir, kinds=None) -> dict:
    """``{status, reason, path, entries}`` of ``<data_dir>/state/accepted.json``.

    ``status`` is ``none`` (no file; ``entries`` ``[]``), ``read``, or ``unreadable``
    (cannot be read, bad JSON, a bad shape, an entry of a kind not in the kinds file, or
    an unreadable kinds file; ``reason`` names the problem and ``entries`` is ``[]``).
    Never raises."""
    return _load_path(file_path(data_dir), kinds)


def _load_path(path: Path, kinds=None) -> dict:
    """``load`` of the accepted file at ``path`` (``accepted.json`` or its previous
    generation)."""
    name = path.name
    result = {"status": "none", "reason": None, "path": str(path), "entries": []}
    try:
        if not path.exists():
            return result
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return dict(result, status="unreadable", reason=f"cannot read {name}: {exc}")
    if kinds is None:
        kinds, reason = load_kinds()
        if kinds is None:
            return dict(result, status="unreadable", reason=reason)
    try:
        data = json.loads(text)
    except ValueError as exc:
        return dict(result, status="unreadable", reason=f"{name} is not JSON: {exc}")
    problem, entries = _check(data, kinds)
    if problem is not None:
        return dict(result, status="unreadable", reason=f"{name}: {problem}")
    return dict(result, status="read", entries=entries)


def not_read_reason(item: dict, limit: int = 200, fields=None):
    """The reason a child item's own values were not read in its pass, or None:
    the item or its facts carried from the baseline, a target that could not be checked, or fields
    listed in ``unread_fields`` (only those in ``fields``, the kind's kept facts, when
    given: an unread field the kind does not keep changes nothing)."""
    if item.get("from_baseline") is True:
        return "it was carried from the baseline (not read in that pass)"
    if item.get("facts_from_baseline") is True:
        return "its file facts were carried from the baseline"
    errors = [fact.get("check_error") for fact in item.get("facts") or []
              if isinstance(fact, dict) and fact.get("check_error")]
    if errors:
        return f"a target file could not be checked: {str(errors[0])[:limit]}"
    unread = item.get("unread_fields")
    if isinstance(unread, list) and fields is not None:
        unread = [field for field in unread if field in fields]
    if isinstance(unread, list) and unread:
        return f"fields not read: {', '.join(map(str, unread))}"
    return None


def entry_for(name: str, item: dict, kinds=None) -> dict:
    """``{kind, key, facts}`` of a child detail item by kind ``name`` of ``kinds``
    (default: the kinds file); ``accept`` adds ``skill``, ``evidence`` and
    ``accepted_on``."""
    if kinds is None:
        kinds, reason = load_kinds()
        if kinds is None:
            raise ValueError(reason)
    kind = kinds[name]
    facts = {field: item.get(field) for field in kind["facts"]}
    fact_fields = kind.get("fact_fields")
    if fact_fields and isinstance(facts.get("facts"), list):
        facts["facts"] = [{f: fact.get(f) for f in fact_fields}
                          for fact in facts["facts"] if isinstance(fact, dict)]
    return {"kind": name, "key": key_of(kind, item), "facts": facts}


def _read_json(path, what):
    """``(data, None)`` of a JSON object file, or ``(None, reason)``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"cannot read the {what} {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"the {what} {path} is not a JSON object"
    return data, None


def find_item(kinds: dict, skill: str, item_id: str, runall_detail: dict):
    """``((kind name, kind, item), None)`` of ``<skill> <id>``, or ``(None, reason)``."""
    own = {name: kind for name, kind in kinds.items() if kind["skill"] == skill}
    if not own:
        return None, f"{skill} has no kind in {KINDS_FILE.name}"
    children = runall_detail.get("children")
    child = next((c for c in children or [] if isinstance(c, dict)
                  and c.get("skill") == skill), None)
    if child is None:
        return None, f"the runall detail file has no child {skill}"
    summary = child.get("summary")
    if child.get("status") != "ok" or not isinstance(summary, dict):
        return None, f"{skill} did not run in that pass (status {child.get('status')!r})"
    if not _text(summary.get("detail_file")):
        return None, f"the {skill} summary names no detail file"
    detail, reason = _read_json(summary["detail_file"], f"{skill} detail file")
    if detail is None:
        return None, reason
    for name, kind in own.items():
        section = detail.get(kind["section"])
        if not isinstance(section, list):
            continue
        for item in section:
            if not isinstance(item, dict) or item.get("id") != item_id:
                continue
            match = kind.get("match", {})
            if all(item.get(field) == value for field, value in match.items()):
                return (name, kind, item), None
    found = [kind["section"] for kind in own.values()
             if any(isinstance(item, dict) and item.get("id") == item_id
                    for item in detail.get(kind["section"]) or [])]
    if found:
        return None, (f"{skill} {item_id} in {found[0]} is not of a kind that can be "
                      f"accepted ({', '.join(own)})")
    return None, (f"{skill} {item_id} is not an item of a kind that can be accepted "
                  f"({', '.join(own)}) in that pass")


def accept(target: str, detail_file, data_dir, today=None) -> dict:
    """Add the entry of ``target`` (``"<skill> <id>"``); the printed result."""
    path = file_path(data_dir)
    refused = {"ok": False, "key": None, "kind": None, "path": str(path)}
    parts = target.split()
    if len(parts) != 2:
        return dict(refused, reason=f"--accept {target!r} is not '<skill> <id>'")
    skill, item_id = parts
    kinds, reason = load_kinds()
    if kinds is None:
        return dict(refused, reason=reason)
    current = load(data_dir, kinds)
    if current["status"] == "unreadable":
        return dict(refused, reason=(f"{current['reason']}; it is left as it is: correct "
                                     "or move it first"))
    runall_detail, reason = _read_json(detail_file, "runall detail file")
    if runall_detail is None:
        return dict(refused, reason=reason)
    found, reason = find_item(kinds, skill, item_id, runall_detail)
    if found is None:
        return dict(refused, reason=reason)
    name, kind, item = found
    unread = not_read_reason(item, fields=kind["facts"])
    if unread is not None:
        return dict(refused, reason=f"{skill} {item_id} was not fully read in that pass "
                                    f"({unread}); accept it from a pass that read it")
    entry = entry_for(name, item, kinds)
    entry.update(skill=skill, evidence=f"{skill} {item_id}",
                 accepted_on=(today or datetime.now().astimezone().date()).isoformat())
    if not _key_ok(kind, entry["key"]):
        return dict(refused, reason=f"{skill} {item_id} has no complete key {kind['key']!r}")
    entries = [e for e in current["entries"]
               if not (e["kind"] == name and e["key"] == entry["key"])]
    entries.append(entry)
    return _save(path, kinds, entries, name, entry["key"], refused)


def _write(path: Path, kinds: dict, entries: list):
    """Write ``entries`` through ``baseline.save_json``: ``(None, None)``, ``(None,
    warning)`` when only the previous generation was not replaced, or ``(reason, None)``.

    With no ``accepted.json`` yet, an empty accepted file is written first, so the first
    write also leaves a previous generation (no accepted findings) for ``--undo``."""
    def validate(old):
        return _check(old, kinds)[0]

    def saved_only(failure):
        # The verified new file is in place; only the previous generation failed.
        return failure.startswith(f"the new {FILE_NAME} is saved, but ")

    if not path.exists():
        failure = baseline.save_json(path.parent, FILE_STEM, EMPTY, validate)
        if failure is not None and not saved_only(failure):
            return f"{FILE_NAME} not saved: {failure}", None
    failure = baseline.save_json(path.parent, FILE_STEM,
                                 {"schema_version": SCHEMA_VERSION, "entries": entries},
                                 validate)
    if failure is not None and saved_only(failure):
        return None, failure
    if failure is not None:
        return f"{FILE_NAME} not saved: {failure}", None
    return None, None


def _save(path: Path, kinds: dict, entries: list, name: str, key, refused: dict) -> dict:
    """Write ``entries`` through ``_write``; the printed result."""
    reason, warning = _write(path, kinds, entries)
    if reason is not None:
        return dict(refused, reason=reason)
    saved = {"ok": True, "key": key, "kind": name, "path": str(path)}
    return saved if warning is None else dict(saved, warning=warning)


def undo(data_dir) -> dict:
    """Write the previous generation back as ``accepted.json``; the printed result."""
    path = file_path(data_dir)
    refused = {"ok": False, "entry_count": None, "path": str(path)}
    kinds, reason = load_kinds()
    if kinds is None:
        return dict(refused, reason=reason)
    current = load(data_dir, kinds)
    if current["status"] == "unreadable":
        return dict(refused, reason=(f"{current['reason']}; it is left as it is: correct "
                                     "or move it first"))
    previous = _load_path(previous_path(data_dir), kinds)
    if previous["status"] == "none":
        return dict(refused, reason=f"there is no {PREVIOUS_NAME}: no write to undo")
    if previous["status"] != "read":
        return dict(refused, reason=f"{previous['reason']}; nothing was written")
    entries = previous["entries"]
    reason, warning = _write(path, kinds, entries)
    if reason is not None:
        return dict(refused, reason=reason)
    now = load(data_dir, kinds)
    if now["status"] != "read" or now["entries"] != entries:
        return dict(refused, reason=(f"{FILE_NAME} was written, but it does not read back "
                                     f"as {PREVIOUS_NAME} held it ({now['status']}: "
                                     f"{now['reason']})"))
    saved = {"ok": True, "entry_count": len(entries), "path": str(path)}
    return saved if warning is None else dict(saved, warning=warning)


def remove(target: str, detail_file, data_dir) -> dict:
    """Remove the entry of ``target`` (``"ush-runall a<n>"``); the printed result."""
    path = file_path(data_dir)
    refused = {"ok": False, "key": None, "kind": None, "path": str(path)}
    parts = target.split()
    if len(parts) != 2 or parts[0] != "ush-runall" or not re.fullmatch(r"a[1-9]\d*", parts[1]):
        return dict(refused, reason=f"--remove {target!r} is not 'ush-runall a<n>'")
    item_id = parts[1]
    kinds, reason = load_kinds()
    if kinds is None:
        return dict(refused, reason=reason)
    current = load(data_dir, kinds)
    if current["status"] == "unreadable":
        return dict(refused, reason=(f"{current['reason']}; it is left as it is: correct "
                                     "or move it first"))
    runall_detail, reason = _read_json(detail_file, "runall detail file")
    if runall_detail is None:
        return dict(refused, reason=reason)
    listed = runall_detail.get("accepted")
    if not isinstance(listed, list):
        return dict(refused, reason=("the runall detail file has no accepted list "
                                     f"(accepted is {listed!r})"))
    item = next((i for i in listed if isinstance(i, dict) and i.get("id") == item_id), None)
    if item is None:
        return dict(refused, reason=f"the runall detail file has no accepted item {item_id}")
    name, key = item.get("kind"), item.get("key")
    entries = [e for e in current["entries"] if not (e["kind"] == name and e["key"] == key)]
    if len(entries) == len(current["entries"]):
        return dict(refused, reason=(f"ush-runall {item_id} ({name} {key!r}) is no longer "
                                     f"in {FILE_NAME}"))
    return _save(path, kinds, entries, name, key, refused)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--accept", metavar="'<skill> <id>'",
                        help="the finding to accept, as the runall report cites it")
    action.add_argument("--remove", metavar="'ush-runall a<n>'",
                        help="the accepted finding to stop accepting, as the runall "
                             "report cites it")
    action.add_argument("--undo", action="store_true",
                        help="write the previous generation of accepted.json back")
    parser.add_argument("--detail-file",
                        help="the runall detail file of the pass the finding comes from "
                             "(required with --accept and --remove)")
    datadir.add_arguments(parser)
    args = parser.parse_args(argv)
    if args.undo and args.detail_file is not None:
        parser.error("--detail-file is not used with --undo")
    if not args.undo and args.detail_file is None:
        parser.error("--detail-file is required with --accept and --remove")
    try:
        data_dir = datadir.resolve(args.data_dir, default=args.default_data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    if args.undo:
        result = undo(data_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    detail_file = Path(args.detail_file).absolute()
    if args.remove is not None:
        result = remove(args.remove, detail_file, data_dir)
    else:
        result = accept(args.accept, detail_file, data_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

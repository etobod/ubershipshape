"""The user's decisions: ``<data dir>/decisions.json``.

The file holds ``{"schema_version": 1, "decisions": [...]}``. Each decision has ``id``
(``D<n>``), ``made`` (a date), ``text`` (the user's words), ``source`` (the repair plan or
the chat date) and ``checks``, a non-empty list of:

- ``{"kind": "setting", "skill": "ush-settings", "item": "<catalogue id>",
  "expected": <value or list>}``; ``expected`` is stored as a list;
- ``{"kind": "vendor_absent", "match": "publisher" | "provider" | "folder",
  "name": "<exact name>"}``.

The file is only read here, never written.
"""

import json
import re
from datetime import date
from pathlib import Path

FILE_NAME = "decisions.json"
SCHEMA_VERSION = 1
ID_RE = re.compile(r"D[1-9][0-9]*")
MATCHES = ("publisher", "provider", "folder")
SETTINGS_SKILL = "ush-settings"


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _scalar(value) -> bool:
    return isinstance(value, (str, int, float, bool))


def _kind(value) -> str:
    """``bool``, ``number`` or ``str``: the kinds the settings comparison keeps apart."""
    if isinstance(value, bool):
        return "bool"
    return "number" if isinstance(value, (int, float)) else "str"


def _against_catalogue(label, item, expected, catalogue_expected):
    """The problem of a setting check measured against the catalogue's expectation of
    ``item`` (a list, or None for an entry that only informs), or None."""
    if catalogue_expected is None:
        return None
    if item not in catalogue_expected:
        return f"{label}: item {item!r} is not in the settings catalogue"
    known = catalogue_expected[item]
    if known is None:
        return (f"{label}: item {item!r} has no expected value in the settings catalogue "
                "(it only informs), so a decision cannot set one")
    known = known if isinstance(known, list) else [known]
    kinds = {_kind(value) for value in known}
    wrong = [value for value in expected if _kind(value) not in kinds]
    if wrong:
        return (f"{label}: expected {wrong!r} for item {item!r} is not of the kind the "
                f"settings catalogue expects ({known!r})")
    return None


def _check_check(label, check, catalogue_ids, catalogue_expected=None):
    """``(problem or None, normalised check)`` of one check."""
    if not isinstance(check, dict):
        return f"{label} is not an object", None
    kind = check.get("kind")
    if kind == "setting":
        if check.get("skill") != SETTINGS_SKILL:
            return f"{label}: skill {check.get('skill')!r} is not {SETTINGS_SKILL!r}", None
        item = check.get("item")
        if not _text(item):
            return f"{label}: item must be a non-empty string", None
        if catalogue_ids is not None and item not in catalogue_ids:
            return f"{label}: item {item!r} is not in the settings catalogue", None
        if "expected" not in check:
            return f"{label}: expected is missing", None
        expected = check["expected"]
        expected = list(expected) if isinstance(expected, list) else [expected]
        if not expected or not all(_scalar(value) for value in expected):
            return f"{label}: expected must be a value or a non-empty list of values", None
        problem = _against_catalogue(label, item, expected, catalogue_expected)
        if problem is not None:
            return problem, None
        return None, dict(check, expected=expected)
    if kind == "vendor_absent":
        if check.get("match") not in MATCHES:
            return f"{label}: match {check.get('match')!r} is not one of {list(MATCHES)}", None
        if not _text(check.get("name")):
            return f"{label}: name must be a non-empty string", None
        return None, dict(check)
    return f"{label}: unknown kind {kind!r}", None


def _check(data, catalogue_ids, catalogue_expected=None):
    """``(problem or None, normalised decisions)`` of the parsed file."""
    if not isinstance(data, dict):
        return "the file is not an object", None
    if data.get("schema_version") != SCHEMA_VERSION:
        return (f"schema_version {data.get('schema_version')!r} is not "
                f"{SCHEMA_VERSION}"), None
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        return "decisions is not a list", None
    result, seen_ids, decided_items = [], set(), {}
    for n, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            return f"decision {n + 1} is not an object", None
        decision_id = decision.get("id")
        if not isinstance(decision_id, str) or not ID_RE.fullmatch(decision_id):
            return f"decision {n + 1}: id {decision_id!r} is not D<n>", None
        if decision_id in seen_ids:
            return f"decision {decision_id}: the id is used twice", None
        seen_ids.add(decision_id)
        made = decision.get("made")
        try:
            date.fromisoformat(made)
        except (TypeError, ValueError):
            return f"decision {decision_id}: made {made!r} is not a date (YYYY-MM-DD)", None
        for key in ("text", "source"):
            if not _text(decision.get(key)):
                return f"decision {decision_id}: {key} must be a non-empty string", None
        checks = decision.get("checks")
        if not isinstance(checks, list) or not checks:
            return f"decision {decision_id}: checks must be a non-empty list", None
        normalised = []
        for k, check in enumerate(checks):
            problem, check = _check_check(f"decision {decision_id} check {k + 1}", check,
                                          catalogue_ids, catalogue_expected)
            if problem is not None:
                return problem, None
            if check["kind"] == "setting":
                item = check["item"]
                if item in decided_items:
                    return (f"item {item!r} has setting checks in decisions "
                            f"{decided_items[item]} and {decision_id}"), None
                decided_items[item] = decision_id
            normalised.append(check)
        result.append(dict(decision, checks=normalised))
    return None, result


def load(data_dir, catalogue_ids=None, catalogue_expected=None) -> dict:
    """``{status, reason, path, decisions}`` of ``<data_dir>/decisions.json``.

    ``status`` is ``none`` (no file), ``read`` or ``unreadable`` (cannot be read, bad
    JSON or a bad shape; ``reason`` names the file and the problem). With
    ``catalogue_ids``, a ``setting`` check naming another item is a bad shape. With
    ``catalogue_expected`` (``{item id: the catalogue's expected list, or None}``) it is a
    bad shape too, and so is a check on an entry with no expectation, or an expected value
    of another kind (bool, number, string) than the catalogue's. Never
    raises on a bad file and never changes it.
    """
    path = Path(data_dir).absolute() / FILE_NAME
    result = {"status": "none", "reason": None, "path": str(path), "decisions": []}
    if not path.exists():
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        problem = f"cannot read: {exc}"
    except ValueError as exc:
        problem = f"invalid JSON: {exc}"
    else:
        ids = None if catalogue_ids is None else set(catalogue_ids)
        problem, decisions = _check(data, ids, catalogue_expected)
    if problem is not None:
        result.update(status="unreadable", reason=f"{FILE_NAME}: {problem}")
        return result
    result.update(status="read", decisions=decisions)
    return result


def setting_expectations(decisions: list) -> dict:
    """``{item id: (decision id, expected list)}`` of the ``setting`` checks."""
    return {check["item"]: (decision["id"], check["expected"])
            for decision in decisions for check in decision["checks"]
            if check["kind"] == "setting"}

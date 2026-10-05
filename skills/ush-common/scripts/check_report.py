"""Check that every number in an ush-* report comes from the script's JSON,
and that the report names every item the summary requires.

Usage (from the project root):

    python -B skills/ush-common/scripts/check_report.py <report.md>
    python -B skills/ush-common/scripts/check_report.py --latest --skill <ush-name> [--data-dir DIR]

The rules below are shared by every skill. What differs between skills comes
from the report profile ``skills/<skill>/data/report-profile.json``, where
``<skill>`` is the ``skill`` key of the summary; only a name matching
``^ush-[a-z]+$`` is accepted, and a summary without that key or a skill
without a profile cannot be checked. The profile gives:

- ``detail_sections``: the lists of the detail file that hold items with ids;
- ``id_letters``: the letters of item ids (``g3`` with ``g`` among them);
- ``path_keys``: keys whose values are file paths or names, not readings;
- ``id_keys``: keys whose values are item ids or references to them;
- ``required_lists``: dotted paths (``dumps.files``) of the summary lists
  whose every item the report must name;
- ``truncated``: ``null``, or a list of
  ``{"list": <dotted path>, "prefix": <letters>, "count_key": <summary key>}``,
  one per list cut from its end, where the top-level summary key
  ``count_key`` (default ``truncated``) counts the items cut from that list;
  one such object without the list brackets works as a one-item list;
- ``required_keys`` (optional): top-level keys the summary must have; a key
  whose value is ``null`` is present;
- ``report_prefix``: the file name prefix of the skill's reports (``events-``).

The shared contract is described in ``skills/ush-common/references/summary-contract.md``.

Rules:

- The first line of the report is exactly ``<!-- ush:summary <absolute path> -->``;
  the file must exist and parse as JSON.
- The report contains the line ``<!-- ush:not-checked -->``.
- Allowed numbers are the tokens of the summary plus the tokens of those items of
  the detail file (``detail_file`` in the summary, items in the profile's
  ``detail_sections``) whose ids are named in
  ``<!-- ush:detail <id> <id> ... -->`` lines. A named id that is not in the
  detail file is an error.
- Tokens: a hex literal ``0x...`` is one integer (``0x19C`` equals
  ``0x0000019c``); every other run of decimal digits is a separate integer
  (``18.09.2026`` -> 18, 9, 2026; leading zeros do not matter).
- Not scanned: the ``ush:summary`` line, the ``ush:detail`` and
  ``ush:not-checked`` marker lines (their ids are checked separately, or carry
  no figures); the number of a numbered heading (``## 2.``, outside a ``>``
  quote) when it equals the heading's position among the numbered headings
  of its level, counted from 1 again under every heading of a higher level
  (see ``_heading_numbers``); the number in the first cell of
  a table row when it equals the row's position among the table's data rows
  (``| 3 | ...`` as the third row); and item ids (one of the profile's
  ``id_letters`` followed by digits, as a separate lowercase word) of the
  summary, of the ``ush:detail`` items and of the items cut from the
  summary (each ``truncated`` entry). A token of that shape that is no such id is a
  number. Every other number is checked, also one that numbers a list item
  (a report has no numbered lists) or a quoted heading.
- Fenced code blocks are not scanned. Fences follow CommonMark: a fence line
  starts with at most 3 spaces (a block at the top level or directly in a
  first-level list item, ``-`` or a number 1-9; never in a nested list item or
  in a ``>`` quote), then 3 or more backticks or tildes; a block closes only
  on the same character, at least as long, with nothing after it, at exactly
  the indent of its opening fence. Any other fence is not recognised and the
  constants in it are checked. A line inside a block indented less than its
  opening fence is an error, and so is a line shaped like the closing fence
  at another indent (a renderer may close the block there).
- Every key of the profile's ``required_keys`` is a top-level key of the
  summary (its value may be ``null`` or empty); a missing one is named.
  This is how a summary of an older shape, without a list the profile
  requires, fails although a missing list requires nothing.
- Every ``id`` of an item in a ``required_lists`` list of the summary is
  named as a separate word (``g25`` does not name ``g2``) in a line that is
  scanned for numbers: not in a code block, not on the ``ush:summary`` line
  and not on an ``ush:detail`` or ``ush:not-checked`` marker line. A missing
  list, or one that is not a list (``null`` for a source that could not be
  read), requires nothing. Items of other lists, items cut from the summary
  and ``ush:detail`` items are not required: the report selects or
  summarises them.
- Write every number in digits. Outside code blocks and inline code (a run
  of backticks up to the next run of the same length in the line; a run
  without one hides nothing), and outside the marker lines, a word of
  ``skills/ush-common/data/number-words.json`` (``dwa``, ``trzy``, ``two``,
  in any case and in the forms listed) is an error, unless the same word
  stands in a string value of the summary or of an ``ush:detail`` item (a
  name like "Invented Two Sync"), read as for numbers; keys back no word. A
  word counts only whole: a letter, a digit, ``_`` or a hyphen next to it
  (``two-factor``) makes it another word. The list leaves out words with
  other meanings (``jeden``, ``one``, ``ten``, ``oba``). A missing or
  malformed list is an error (exit 2), not an empty one.
- No HTML and no links. Outside code blocks, only the ush: marker lines hold
  an HTML comment: a marker is the whole line (not in a quote or a list item)
  with one ``<!--`` and one ``-->`` and nothing after it. Any other ``<!--``,
  in inline code or after a backslash too, is an error; a literal one is
  written ``&lt;!--``. So is ``<`` before a letter, ``?``, ``!`` or ``/``
  anywhere in a line (written ``&lt;``), ``]:`` and ``](``. ``<`` before a
  space, a digit or ``=`` is text.
- Local time with UTC. Outside code blocks, ``YYYY-MM-DD HH:MM (HH:MM UTC)``
  needs a time with a zone in the JSON (the summary or an ``ush:detail``
  item; a whole string value that ``datetime.fromisoformat`` reads with a
  zone, not a value of the skipped keys) whose UTC hour and minute are the
  part in brackets and whose local time (the zone of this machine) is the
  part before it; seconds are dropped, never rounded. A time that cannot be
  converted (year 1601 on Windows) backs nothing. The digits of a matched
  pair are not checked as numbers. A pair whose text is part of a JSON
  string value (a quoted message) needs no backing time. Any other
  ``HH:MM UTC)`` (``30.09.2026 09:26 (07:26 UTC)``, a time without its
  date) is an error, unless its text is part of a JSON string value (a
  quoted event sample).
- Skill script commands. A line of a code block that runs a skill script
  (``python [-B] .../skills/ush-<name>/scripts/<script>.py``) must give
  ``--data-dir`` an absolute Windows path (``--data-dir "C:\\x"`` or
  ``--data-dir=C:\\x``, no ``<``), and an earlier line of the same block
  must be ``Set-Location`` with an absolute Windows path (no ``<``). A
  command line ending with a backtick is an error of its own (report-style
  rule 9: one command per line), never a missing ``--data-dir``. Comment
  lines (``#``) and lines outside code blocks are not checked.

JSON files are tokenized from their parsed values (strings, numbers and keys),
not from the raw text, so ``\\u0105`` escapes cannot supply numbers. The values
of the profile's ``path_keys`` and ``id_keys`` supply none either. A key named
by a file path (one shaped ``<name>[<item>].<field>``, such as
``facts[C:\\x\\y.exe].signer`` or ``facts[y.exe].signer``, or any other key that
holds a backslash) supplies no number from its own text, but its value is read,
unless its ``<field>`` is one of those skipped keys. A hex token
is backed only by a hex value and a decimal token only by a decimal one. The
``ush:not-checked`` line must stand directly before or after a heading.
``--latest --skill <name>`` takes the newest ``<report_prefix>*.md`` of that
skill's profile, since skills share ``reports/``; a report whose summary names
another skill is an error.

The script counts; it does not judge whether a number is right, only whether
it is backed by the JSON, nor whether an item is described well, only whether
its id is there. Exit codes: 0 OK, 1 numbers not backed, number words, summary
items not named, required summary keys missing or style problems (the
local time and the script command rules), 2 the report, its JSON, its
profile or the number word list could not be checked.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# load_script does not put this directory on sys.path; datadir lives next to this file.
sys.path.insert(0, str(Path(__file__).absolute().parent))

import datadir

# The skills/ directory: where the report profiles are read from (an input,
# never an output path).
SKILLS_DIR = Path(__file__).absolute().parents[2]
PROFILE_FILE = Path("data") / "report-profile.json"
# The number words a report may not use outside code (an input, never an output path).
NUMBER_WORDS_FILE = Path(__file__).absolute().parents[1] / "data" / "number-words.json"
SKILL_NAME = re.compile(r"^ush-[a-z]+$")
ID_LETTERS = re.compile(r"^[a-z]+$")
REPORT_PREFIX = re.compile(r"^[a-z]+-$")

SUMMARY_LINE = re.compile(r"^<!-- ush:summary (?P<path>\S.*?) -->\s*$")
NOT_CHECKED_LINE = re.compile(r"^\s*<!--\s*ush:not-checked\s*-->\s*$")
DETAIL_LINE = re.compile(r"^\s*<!--\s*ush:detail\b(?P<ids>.*?)-->\s*$")

# A hex literal that is not part of a longer word, or a run of ASCII digits.
TOKEN = re.compile(
    r"(?P<hex>(?<![0-9A-Za-z_])0[xX][0-9a-fA-F]+(?![0-9A-Za-z_]))|(?P<dec>[0-9]+)"
)
# An ATX heading outside a quote, and its number if it has one: "## 2. ".
HEADING_NUMBER = re.compile(
    r"^ {0,3}(?P<level>#{1,6})(?:[ \t]+(?P<number>[0-9]+)[.)](?=[ \t]|$)|(?=[ \t]|$))"
)
# One entry of the number-word list: a single lowercase word of letters only.
WORD_ENTRY = re.compile(r"^[^\W\d_]+$")
# A run of backticks: inline code opens on one and closes on the next run of the
# same length in the same line.
BACKTICKS = re.compile(r"`+")
# Row number in the first cell of a table row: "| 3 | ...".
TABLE_ROW_NUMBER = re.compile(r"^\s*\|\s*(?P<number>[0-9]+)\s*(?=\|)")
TABLE_ROW = re.compile(r"^\s*\|")
TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*$")
# A fence (CommonMark): at most 3 spaces of indent, then 3 or more backticks or
# tildes; the rest of an opening line is its info string.
FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<rest>.*)$")
# A local time with its UTC time: "2026-09-30 09:26 (07:26 UTC)".
TIME_PAIR = re.compile(
    r"(?P<local>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \((?P<utc>\d{2}:\d{2}) UTC\)"
)
# A UTC time in brackets; outside a whole TIME_PAIR it is an error.
UTC_TIME = re.compile(r"\d{2}:\d{2} UTC\)")
# A code block line that runs a skill script.
SCRIPT_COMMAND = re.compile(
    r"(?i)\bpython(?:\.exe)?[\"']?\s+(?:-B\s+)?[\"']?[^\"'\s]*skills[\\/]ush-[a-z0-9-]+"
    r"[\\/]scripts[\\/][a-z0-9_]+\.py"
)
# The value of --data-dir: a double- or single-quoted string or a run without spaces.
DATA_DIR_ARG = re.compile(r"""--data-dir(?:=|\s+)(?P<value>"[^"]*"?|'[^']*'?|\S+)""")
ABSOLUTE_WINDOWS = re.compile(r"^[A-Za-z]:[\\/]")
SET_LOCATION = re.compile(
    r"""(?i)^\s*Set-Location\s+(?:-(?:Literal)?Path\s+)?(?P<value>"[^"]*"?|'[^']*'?|\S+)"""
)
# A line shaped like a closing fence, at any indent.
CLOSING_FENCE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*$")
HEADING = re.compile(r"^ {0,3}#{1,6}\s")
# The start of any raw HTML: a tag, an autolink, a processing instruction or CDATA.
RAW_HTML = re.compile(r"<[A-Za-z?!/]")
# One leading piece of a line that is not its text: indent, a quote marker, or
# a list marker followed by a space, a tab or the end of the line.
LINE_PREFIX = re.compile(r"^(?:[ \t]+|>|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$))")

EXIT_OK, EXIT_NUMBERS, EXIT_ERROR = 0, 1, 2


class CheckError(Exception):
    """The report, one of its JSON files or its profile cannot be checked."""


@dataclass(frozen=True)
class Profile:
    """The skill-specific rules of a report (``report-profile.json``)."""

    skill: str
    detail_sections: tuple[str, ...]
    item_id: re.Pattern  # an item id as a separate lowercase word
    skip_keys: frozenset[str]  # path_keys and id_keys: their values are no readings
    required_lists: tuple[str, ...]  # dotted paths
    truncated: tuple[dict, ...]  # ({"list": dotted path, "prefix": letters, "count_key": key}, ...)
    required_keys: tuple[str, ...]  # top-level summary keys that must be present
    report_prefix: str


def check_skill_name(skill) -> str:
    """Return ``skill`` when it is a name like ``ush-events``; raise CheckError
    otherwise, before the name is used in any path."""
    if not isinstance(skill, str) or not SKILL_NAME.match(skill):
        raise CheckError(f"skill name {skill!r} is not of the form ush-<lowercase letters>")
    return skill


def load_profile(skill) -> Profile:
    """Read and validate ``SKILLS_DIR/<skill>/data/report-profile.json``."""
    skill = check_skill_name(skill)
    path = SKILLS_DIR / skill / PROFILE_FILE
    if not path.is_file():
        raise CheckError(f"no report profile for {skill}: {path} does not exist")
    data = read_json(path, "report profile")
    if not isinstance(data, dict):
        raise CheckError(f"report profile {path} is not a JSON object")

    def names(key) -> tuple[str, ...]:
        value = data.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise CheckError(f"report profile {path}: {key} must be a list of names")
        return tuple(value)

    letters = data.get("id_letters")
    if not isinstance(letters, str) or not ID_LETTERS.match(letters):
        raise CheckError(f"report profile {path}: id_letters must be lowercase letters")
    truncated = truncated_entries(data.get("truncated"))
    if truncated is None:
        raise CheckError(
            f"report profile {path}: truncated must be null, "
            f"{{list: <dotted path>, prefix: <lowercase letters>}} or a list of "
            f"{{list, prefix, count_key: <summary key>}} (count_key optional)"
        )
    required_keys = names("required_keys") if "required_keys" in data else ()
    prefix = data.get("report_prefix")
    if not isinstance(prefix, str) or not REPORT_PREFIX.match(prefix):
        raise CheckError(f"report profile {path}: report_prefix must be like 'events-'")
    return Profile(
        skill=skill,
        detail_sections=names("detail_sections"),
        item_id=re.compile(rf"(?<![0-9A-Za-z_])[{letters}][0-9]+(?![0-9A-Za-z_])"),
        skip_keys=frozenset(names("path_keys") + names("id_keys")),
        required_lists=names("required_lists"),
        truncated=truncated,
        required_keys=required_keys,
        report_prefix=prefix,
    )


def truncated_entries(value) -> tuple[dict, ...] | None:
    """The profile's ``truncated`` as a tuple of ``{list, prefix, count_key}``, or
    None when it has another shape.

    ``null`` is no entry; one object is a one-item list; ``count_key`` defaults to
    ``truncated``.
    """
    if value is None:
        return ()
    entries = [value] if isinstance(value, dict) else value
    if not isinstance(entries, list):
        return None
    found = []
    for entry in entries:
        if not (isinstance(entry, dict) and {"list", "prefix"} <= set(entry)
                and set(entry) <= {"list", "prefix", "count_key"}
                and isinstance(entry["list"], str) and entry["list"]
                and isinstance(entry["prefix"], str) and ID_LETTERS.match(entry["prefix"])):
            return None
        count_key = entry.get("count_key", "truncated")
        if not isinstance(count_key, str) or not count_key:
            return None
        found.append({"list": entry["list"], "prefix": entry["prefix"],
                      "count_key": count_key})
    return tuple(found)


def summary_profile(summary, expected: str | None = None) -> Profile:
    """The profile of the skill named by the summary's ``skill`` key.

    With ``expected``, a summary of another skill is an error.
    """
    if not isinstance(summary, dict) or "skill" not in summary:
        raise CheckError("the summary has no skill key; it names the skill whose report "
                         "profile applies")
    skill = check_skill_name(summary["skill"])
    if expected is not None and skill != expected:
        raise CheckError(f"the summary is of skill {skill}, not {expected}")
    return load_profile(skill)


def dotted(data, path: str):
    """The value at a dotted path (``dumps.files``), or None when any part is missing."""
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def tokens(text: str):
    """Yield (as written, (kind, integer value)) for every number token in ``text``.

    Hex and decimal tokens are kept apart, so ``0x0000019c`` never backs a
    decimal 412 and a decimal 65 never backs ``0x41``.
    """
    for match in TOKEN.finditer(text):
        if match.group("hex"):
            yield match.group("hex"), ("hex", int(match.group("hex"), 16))
        else:
            yield match.group("dec"), ("dec", int(match.group("dec")))


# A field of an item named by a file path, with or without a folder:
# ``facts[C:\x\y.exe].signer``, ``facts[y.exe].signer``.
PATH_NAMED_KEY = re.compile(r"^\w+\[.*\]\.(?P<field>[^.\]]+)$", re.DOTALL)


def path_named_field(key: str) -> str | None:
    """The field a key named by a file path stands for: the part after the
    last ``].``, "" for another key that holds a backslash, None for an
    ordinary key."""
    match = PATH_NAMED_KEY.match(key)
    if match:
        return match.group("field")
    return "" if "\\" in key else None


def json_values(data, skip_keys: frozenset[str]) -> set[tuple[str, int]]:
    """Number tokens of every key, string and number in parsed JSON.

    The values of ``skip_keys`` (the profile's path_keys and id_keys) are
    skipped: a file path or an item id is not a reading, and its digits would
    back numbers the report made up. A key named by a file path backs no
    number with its own text; its value is read unless the field it names is
    in ``skip_keys`` (see ``path_named_field``).
    """
    found: set[tuple[str, int]] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                key = str(key)
                field = path_named_field(key)
                if field is None:
                    found.update(value for _, value in tokens(key))
                    if key not in skip_keys:
                        stack.append(value)
                elif field not in skip_keys:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, bool) or item is None:
            continue  # True would otherwise count as 1
        elif isinstance(item, (int, float, str)):
            found.update(value for _, value in tokens(str(item)))
    return found


def json_strings(data, skip_keys: frozenset[str]) -> set[str]:
    """The string values of parsed JSON.

    Walked like ``json_values``: the values of ``skip_keys``, and of keys named
    by a file path whose field is skipped, are left out.
    """
    found: set[str] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                key = str(key)
                field = path_named_field(key)
                if (key if field is None else field) not in skip_keys:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            found.add(item)
    return found


def json_times(data, skip_keys: frozenset[str]) -> set[datetime]:
    """Times with a zone among the string values of parsed JSON, seconds dropped.

    Walked like ``json_values``: the values of ``skip_keys``, and of keys named
    by a file path whose field is skipped, are left out. A string is a time
    only when it is one as a whole.
    """
    found: set[datetime] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                key = str(key)
                field = path_named_field(key)
                if (key if field is None else field) not in skip_keys:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            try:
                parsed = datetime.fromisoformat(item)
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                found.add(parsed.replace(second=0, microsecond=0))
    return found


def _time_backed(local: str, utc: str, times: set[datetime], to_local) -> bool:
    """Whether a JSON time is ``utc`` in UTC and ``local`` in the local zone."""
    for value in times:
        try:
            if (value.astimezone(timezone.utc).strftime("%H:%M") == utc
                    and to_local(value).strftime("%Y-%m-%d %H:%M") == local):
                return True
        except (OSError, OverflowError, ValueError):
            continue  # a time this machine cannot convert backs nothing
    return False


def time_problems(line: str, number: int, times: set[datetime], to_local,
                  texts: frozenset[str] = frozenset()) -> tuple[str, list[str]]:
    """(the line with its time pairs blanked, the problems of its UTC times).

    A pair, or a UTC time outside a pair, is no problem when its text is part
    of a JSON string value in ``texts`` (a quoted message, event sample or name).
    """
    problems = [
        f"line {number}: {match.group()} matches no time with a zone in the summary "
        f"or in a detail item named in ush:detail"
        for match in TIME_PAIR.finditer(line)
        if not any(match.group() in text for text in texts)
        and not _time_backed(match["local"], match["utc"], times, to_local)
    ]
    line = TIME_PAIR.sub(" ", line)
    problems += [f"line {number}: {match.group()} is not part of a local time "
                 f"written YYYY-MM-DD HH:MM (HH:MM UTC)"
                 for match in UTC_TIME.finditer(line)
                 if not any(match.group() in text for text in texts)]
    return line, problems


def command_problems(lines: list[str], blocks: list[tuple[int, int]]) -> list[str]:
    """Skill script commands of code blocks continued with a backtick, or without
    --data-dir or Set-Location."""
    problems = []
    for start, end in blocks:
        located = False
        for index in range(start + 1, end):
            line = lines[index]
            location = SET_LOCATION.match(line)
            if location:
                value = location["value"].strip("\"'")
                located = bool(ABSOLUTE_WINDOWS.match(value)) and "<" not in value
            if line.lstrip().startswith("#") or not SCRIPT_COMMAND.search(line):
                continue
            values = [match["value"].strip("\"'") for match in DATA_DIR_ARG.finditer(line)]
            if line.rstrip().endswith("`"):
                problems.append(
                    f"line {index + 1}: a skill script command is continued with a "
                    f"backtick; write it on one line with --data-dir (report-style rule 9)"
                )
            elif not any(ABSOLUTE_WINDOWS.match(value) and "<" not in value
                         for value in values):
                problems.append(
                    f"line {index + 1}: a skill script command needs --data-dir with "
                    f"an absolute Windows path"
                )
            if not located:
                problems.append(
                    f"line {index + 1}: a skill script command needs a Set-Location "
                    f"line with an absolute Windows path earlier in its code block"
                )
    return problems


def load_number_words() -> re.Pattern:
    """A pattern matching any word of ``NUMBER_WORDS_FILE`` as a whole word.

    The file is ``{"words": [<lowercase word>, ...]}``. A missing or unreadable
    file, or a list of another shape, is a CheckError: a silently empty list
    would switch the rule off. The pattern ignores case; a letter, a digit,
    ``_`` or a hyphen next to the word makes it no match (``two-factor``).
    """
    path = NUMBER_WORDS_FILE
    if not path.is_file():
        raise CheckError(f"number word list {path} does not exist")
    data = read_json(path, "number word list")
    words = data.get("words") if isinstance(data, dict) else None
    if not isinstance(words, list) or not words:
        raise CheckError(f"number word list {path}: words must be a non-empty list")
    for word in words:
        if not (isinstance(word, str) and WORD_ENTRY.match(word) and word == word.lower()):
            raise CheckError(f"number word list {path}: {word!r} is not one lowercase word")
    alternatives = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alternatives})(?![\w-])", re.IGNORECASE)


def json_words(data, skip_keys: frozenset[str], pattern: re.Pattern) -> set[str]:
    """The number words (lowercased) in the string values of parsed JSON.

    The same values as in ``json_values`` back words, except that keys back
    none: a name like "Invented Two Sync" backs "two" in the report.
    """
    found: set[str] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                field = path_named_field(str(key))
                if (str(key) if field is None else field) not in skip_keys:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            found.update(match.lower() for match in pattern.findall(item))
    return found


def strip_inline_code(line: str) -> str:
    """``line`` with its inline code spans blanked: a run of backticks up to the
    next run of the same length. A run without such a partner hides nothing."""
    out, at = [], 0
    while (opening := BACKTICKS.search(line, at)):
        closing = next((m for m in BACKTICKS.finditer(line, opening.end())
                        if len(m.group()) == len(opening.group())), None)
        if closing is None:
            out.append(line[at:opening.end()])
            at = opening.end()
            continue
        out.append(line[at:opening.start()] + " ")
        at = closing.end()
    out.append(line[at:])
    return "".join(out)


def read_text(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckError(f"{what} {path} could not be read: {type(exc).__name__}: {exc}")


def read_json(path: Path, what: str):
    text = read_text(path, what)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise CheckError(f"{what} {path} is not valid JSON: {exc}")


def detail_by_id(summary, profile: Profile, why: str) -> tuple[Path, dict]:
    """(detail file path, {id: item} of its ``profile.detail_sections``).

    A summary without ``detail_file``, a relative path, or a file that is
    missing, unreadable or not a JSON object is a CheckError naming the file;
    ``why`` says what needed it.
    """
    if not isinstance(summary, dict) or not isinstance(summary.get("detail_file"), str):
        raise CheckError(f"{why} but the summary has no detail_file")
    path = Path(summary["detail_file"])
    if not path.is_absolute():
        raise CheckError(f"detail_file in the summary is not an absolute path: {path}")
    detail = read_json(path, "detail file")
    if not isinstance(detail, dict):
        raise CheckError(f"detail file {path} is not a JSON object")
    by_id = {}
    for section in profile.detail_sections:
        items = detail.get(section)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    by_id[item["id"]] = item
    return path, by_id


def detail_items(summary, ids: list[str], profile: Profile) -> list:
    """Return the detail-file items with the given ids; every id must exist."""
    path, by_id = detail_by_id(summary, profile, "the report names ush:detail ids")
    missing = [item_id for item_id in ids if item_id not in by_id]
    if missing:
        raise CheckError(
            f"ush:detail names ids not found in the detail file {path}: {', '.join(missing)}"
        )
    return [by_id[item_id] for item_id in ids]


def to_local(dt):
    """The local time of an aware datetime, in the zone of this machine."""
    return dt.astimezone()


_machine_local = to_local  # check() and main() take a parameter of the same name


def check(report: Path, skill: str | None = None, to_local=None
          ) -> tuple[list[str], int, list[str], list[str], list[str]]:
    """Return (unbacked-number messages, number of checked tokens,
    messages for the summary items the report does not name,
    number-word messages, style messages).

    Style messages: a local time with UTC that no JSON time backs, a UTC time
    outside such a pair, and a skill script command in a code block without
    ``--data-dir`` or an earlier ``Set-Location``. ``to_local`` converts an
    aware datetime to local time (default: the zone of this machine).
    With ``skill``, a report whose summary is of another skill is an error.
    """
    local = to_local or _machine_local
    lines = read_text(report, "report").splitlines()
    first = lines[0] if lines else ""
    match = SUMMARY_LINE.match(first)
    if not match:
        raise CheckError(
            "the first line of the report must be exactly "
            "'<!-- ush:summary <absolute path of the summary file> -->'"
        )
    # Code blocks are paste-ready commands: no markers and no reported numbers.
    blocks = _code_blocks(lines)
    fenced = _fenced_lines(lines)
    # Before the summary path: a comment after the marker would end up in the path.
    _reject_html(lines, fenced)
    summary_path = Path(match.group("path"))
    if not summary_path.is_absolute():
        raise CheckError(f"the ush:summary path is not absolute: {summary_path}")
    if not summary_path.is_file():
        raise CheckError(f"the summary file named on the first line does not exist: {summary_path}")
    summary = read_json(summary_path, "summary file")
    profile = summary_profile(summary, skill)

    style = command_problems(lines, blocks)
    visible = [("" if index in fenced else line) for index, line in enumerate(lines)]
    lines = visible

    if not any(NOT_CHECKED_LINE.match(line) for line in lines):
        raise CheckError(
            "the report has no '<!-- ush:not-checked -->' line before its "
            "'not checked' section"
        )
    if not any(NOT_CHECKED_LINE.match(line) and _next_to_heading(lines, index, fenced)
               for index, line in enumerate(lines)):
        raise CheckError(
            "the '<!-- ush:not-checked -->' line must stand directly before or after "
            "the heading of the 'not checked' section"
        )

    named: list[str] = []
    for line in lines:
        detail = DETAIL_LINE.match(line)
        if detail:
            named.extend(detail.group("ids").split())
    ids = list(dict.fromkeys(named))  # several markers are allowed; keep first order

    number_word = load_number_words()
    allowed = json_values(summary, profile.skip_keys)
    backed_words = json_words(summary, profile.skip_keys, number_word)
    for item in detail_items(summary, ids, profile) if ids else []:
        allowed |= json_values(item, profile.skip_keys)
        backed_words |= json_words(item, profile.skip_keys, number_word)

    times = json_times(summary, profile.skip_keys)
    texts = json_strings(summary, profile.skip_keys)
    for item in detail_items(summary, ids, profile) if ids else []:
        times |= json_times(item, profile.skip_keys)
        texts |= json_strings(item, profile.skip_keys)
    texts = frozenset(text for text in texts if "UTC)" in text)

    known_ids = item_ids(summary, profile) | set(ids)

    in_order = _heading_numbers(lines)
    problems, checked, words = [], 0, []
    mentioned: set[str] = set()
    position = 0  # data-row position in the current table; 0 outside a table
    row = 0  # row index in the current table: 0 header, 1 delimiter row
    for number, line in enumerate(lines[1:], start=2):
        if TABLE_ROW.match(line):
            row = row + 1 if TABLE_ROW.match(lines[number - 2]) else 0
            if row == 0:
                position = 0  # a new table: this is its header row
            elif not (row == 1 and TABLE_SEPARATOR.match(line)):
                position += 1
        else:
            position = row = 0
        if NOT_CHECKED_LINE.match(line) or DETAIL_LINE.match(line):
            continue
        line, found = time_problems(line, number, times, local, texts)
        style += found
        words += [f'line {number}: "{word}" is a number word; write the number in digits'
                  for word in number_word.findall(strip_inline_code(line))
                  if word.lower() not in backed_words]
        numbering = HEADING_NUMBER.match(line) if number - 1 in in_order else None
        if not numbering and position:
            cell = TABLE_ROW_NUMBER.match(line)
            if cell and int(cell["number"]) == position:
                numbering = cell
        if numbering:
            line = line[numbering.end():]
        mentioned.update(profile.item_id.findall(line))
        line = profile.item_id.sub(lambda m: " " if m.group() in known_ids else m.group(), line)
        for written, value in tokens(line):
            checked += 1
            if value not in allowed:
                problems.append(
                    f"line {number}: {written} is not in the summary or in a detail "
                    f"item named in ush:detail"
                )
    missing = [f"required key missing from the summary: {key}"
               for key in profile.required_keys if key not in summary]
    missing += [f"not named in the report: {item_id} ({where})"
                for item_id, where in required_ids(summary, profile)
                if item_id not in mentioned]
    return problems, checked, missing, words, style


def required_ids(summary, profile: Profile) -> list[tuple[str, str]]:
    """(id, dotted list path) of the items of the profile's required lists.

    A list that is missing or not a list (``null``: the source could not be
    read) requires nothing.
    """
    lists = [(where, dotted(summary, where)) for where in profile.required_lists]
    return [(item["id"], where) for where, items in lists if isinstance(items, list)
            for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def item_ids(summary, profile: Profile) -> set[str]:
    """Ids of the summary's items, and of the items cut from it.

    Ids are stable between runs: an id is a number kept for the item, not its
    position in a list, so the id of a cut item does not follow from the list.
    For each entry {list, prefix, count_key} of the profile's ``truncated``
    whose summary key ``count_key`` is above 0, the known cut ids are every
    ``id`` with that prefix in the ``profile.detail_sections`` of the detail
    file (``detail_file``). A missing ``detail_file``, a missing file or an
    unreadable one is then a CheckError naming the file, whatever the report
    mentions. An entry with a count of 0 or none does not read the detail file.
    """
    found: set[str] = set()
    stack = [summary]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get("id"), str):
                found.add(item["id"])
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    by_id = None
    for entry in profile.truncated if isinstance(summary, dict) else ():
        truncated, prefix = summary.get(entry["count_key"]), entry["prefix"]
        if not (isinstance(truncated, int) and not isinstance(truncated, bool)
                and truncated > 0):
            continue
        if by_id is None:
            _, by_id = detail_by_id(
                summary, profile, f"{entry['count_key']} is {truncated}")
        found.update(item_id for item_id in by_id
                     if item_id.startswith(prefix) and item_id[len(prefix):].isdigit())
    return found


def _heading_numbers(lines: list[str]) -> set[int]:
    """Indices of the numbered headings whose number equals their position.

    Numbered ATX headings (``HEADING_NUMBER``) of each level are counted from
    1 in order; a heading of a higher level (fewer ``#``), numbered or not,
    starts the count of every lower level again. A heading whose number is
    out of order still counts, so one wrong number does not shift the rest.
    Setext headings and quoted headings are not counted.
    """
    counts = [0] * 7  # counts[level] for levels 1..6
    found: set[int] = set()
    for index, line in enumerate(lines):
        heading = HEADING_NUMBER.match(line)
        if not heading:
            continue
        level = len(heading["level"])
        for lower in range(level + 1, 7):
            counts[lower] = 0
        if heading["number"] is None:
            continue
        counts[level] += 1
        if int(heading["number"]) == counts[level]:
            found.add(index)
    return found


def _indent(line: str) -> int:
    """Leading columns of a line, a tab reaching the next multiple of 4 (CommonMark)."""
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _fenced_lines(lines: list[str]) -> set[int]:
    """Indices of the lines of fenced code blocks, the fences included."""
    return {index for start, end in _code_blocks(lines) for index in range(start, end + 1)}


def _code_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """(opening fence index, closing fence index) of every fenced code block.

    CommonMark fence rules: a fence line starts with at most 3 spaces, then at
    least 3 backticks or 3 tildes. A backtick opening line with a backtick in
    its info string is not a fence. A block closes only on a line of the same
    character, at least as long as the opening fence, with nothing but spaces
    after it. A block still open at the end of the report is an error, so it
    cannot hide the rest. So is a non-blank line inside a block indented less
    than its opening fence: in a list item the block would end with the item,
    and the text after it would show but not be checked. A block closes only
    at exactly the indent of its opening fence; a line shaped like the closing
    fence at another indent is an error, since a renderer may close the block
    there and show the lines after it.
    """
    blocks: list[tuple[int, int]] = []
    fence, opened_at, indent = None, 0, 0
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if fence is None:
            if match and not (match["fence"][0] == "`" and "`" in match["rest"]):
                fence, opened_at = match["fence"], index
                indent = _indent(line)
            elif _marker_fence(line):
                raise CheckError(
                    f"line {index + 1} opens a code block on the line of a list marker; "
                    f"put the text after the marker and the fence on its own "
                    f"line below, indented to that text"
                )
        elif line.strip() and _indent(line) < indent:
            raise CheckError(
                f"line {index + 1} is indented less than the code block opened at line "
                f"{opened_at + 1}; indent every line of a block, its closing fence "
                f"included, at least as far as its opening fence"
            )
        elif ((closing := CLOSING_FENCE.match(line)) and closing["fence"][0] == fence[0]
              and len(closing["fence"]) >= len(fence)):
            if _indent(line) != indent:
                raise CheckError(
                    f"line {index + 1} looks like the closing fence of the code block "
                    f"opened at line {opened_at + 1} but is indented differently; put "
                    f"the closing fence at exactly the indent of the opening fence"
                )
            fence = None
            blocks.append((opened_at, index))
    if fence is not None:
        raise CheckError(f"code block opened at line {opened_at + 1} is never closed")
    return blocks


def _marker_fence(line: str) -> bool:
    """True when a fence follows a list marker on the same line (``- ```ps``,
    ``1. ```ps``): the checker would miss its opening fence and take its
    closing fence for an opening one."""
    text, marker = line, False
    while (prefix := LINE_PREFIX.match(text)) and prefix.end():
        marker = marker or prefix.group().strip() not in ("", ">")
        text = text[prefix.end():]
    fence = FENCE.match(text)
    return marker and bool(fence) and not (fence["fence"][0] == "`"
                                           and "`" in fence["rest"])


def _reject_html(lines: list[str], fenced: set[int]) -> None:
    """Raise CheckError for an HTML line outside the code blocks.

    A preview hides comments, raw HTML, link targets and link reference
    definitions, so an id in them would count as named without being shown.
    Only the ush: marker lines may hold an HTML comment: a marker is the whole
    raw line (not in a quote or a list item) with one ``<!--`` and one ``-->``.
    Any other ``<!--``, wherever it stands, is an error; so is ``<`` before a
    letter, ``?``, ``!`` or ``/`` (every HTML tag, block start, autolink,
    processing instruction or CDATA), ``]:`` (a link reference definition,
    also one whose label spans lines) and ``](`` (a link or image target).
    These are banned outright, in inline code or after a backslash too,
    rather than recognised.
    """
    for index, line in enumerate(lines):
        if index in fenced:
            continue
        if _is_marker(line, index):
            continue
        if "<!--" in line:
            raise CheckError(
                f"line {index + 1} has an HTML comment: only the ush: marker lines may; "
                f"write a literal '<!--' as '&lt;!--'"
            )
        if RAW_HTML.search(line):
            raise CheckError(
                f"line {index + 1} has raw HTML: a preview may hide it; write a literal '<' "
                f"before a letter, '?', '!' or '/' as '&lt;'"
            )
        if "]:" in line:
            raise CheckError(
                f"line {index + 1} has ']:': a preview may hide it as a link reference "
                f"definition; name items in plain text"
            )
        if "](" in line:
            raise CheckError(
                f"line {index + 1} has a link: a preview shows only its text; name items "
                f"in plain text, without links"
            )


def _is_marker(line: str, index: int) -> bool:
    """True when ``line`` (at 0-based ``index``) is one whole ush: marker line."""
    if line.count("<!--") != 1 or line.count("-->") != 1:
        return False
    if index == 0 and SUMMARY_LINE.match(line):
        return True
    return bool(NOT_CHECKED_LINE.match(line) or DETAIL_LINE.match(line))


def _next_to_heading(lines: list[str], index: int, fenced: set[int] = frozenset()) -> bool:
    """True when the nearest non-blank line before or after ``index`` is a heading.

    A code block in between counts as content, not as blank lines.
    """
    for step in (-1, 1):
        at = index + step
        while 0 <= at < len(lines) and at not in fenced and not lines[at].strip():
            at += step
        if 0 <= at < len(lines) and HEADING.match(lines[at]):
            return True
    return False


def latest_report(data_dir: Path, skill: str) -> Path:
    """The newest (by name) ``<report_prefix>*.md`` of the skill's profile."""
    pattern = f"{load_profile(skill).report_prefix}*.md"
    reports = data_dir / "reports"
    try:
        found = sorted((p for p in reports.glob(pattern) if p.is_file()), key=lambda p: p.name)
    except OSError as exc:
        raise CheckError(f"{reports} could not be listed: {type(exc).__name__}: {exc}")
    if not found:
        raise CheckError(f"no report ({pattern}) in {reports}")
    return found[-1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_report.py",
        description="Check that every number in an ush-* report is backed by its JSON "
                    "and that the report names every item its skill's report profile "
                    "requires.",
    )
    parser.add_argument("report", nargs="?", help="path of the report (.md)")
    parser.add_argument("--latest", action="store_true",
                        help="check the newest <report_prefix>*.md (by name) of --skill "
                             "in <data-dir>/reports/")
    parser.add_argument("--skill",
                        help="the skill whose report is checked (ush-<letters>); required "
                             "with --latest; the summary must name the same skill")
    parser.add_argument("--data-dir", default=None,
                        help=datadir.HELP + "; used with --latest")
    return parser


def main(argv=None, to_local=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.report) == bool(args.latest):
        parser.error("give either a report path or --latest")
    if args.latest and args.skill is None:
        parser.error("--latest needs --skill <name>")
    if args.skill is not None and not SKILL_NAME.match(args.skill):
        parser.error(f"--skill {args.skill!r} is not of the form ush-<lowercase letters>")
    data_dir = None
    if args.latest:
        try:
            data_dir = datadir.resolve(args.data_dir)
        except datadir.DataDirError as exc:
            parser.error(str(exc))
    try:
        if args.latest:
            report = latest_report(data_dir, args.skill)
        else:
            report = Path(args.report).absolute()
        problems, checked, missing, words, style = check(report, args.skill, to_local)
    except CheckError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for line in problems + words + missing + style:
        print(line)
    if problems:
        print(f"FAILED: {report}: {len(problems)} of {checked} numbers are not backed by the JSON")
    if words:
        print(f"FAILED: {report}: {len(words)} number words")
    missing_keys = sum(1 for line in missing if line.startswith("required key missing"))
    if missing_keys:
        print(f"FAILED: {report}: {missing_keys} required summary keys missing")
    if len(missing) > missing_keys:
        print(f"FAILED: {report}: {len(missing) - missing_keys} summary items not named "
              f"in the report")
    if style:
        print(f"FAILED: {report}: {len(style)} style problems")
    if problems or words or missing or style:
        return EXIT_NUMBERS
    print(f"OK: {report}: {checked} numbers checked")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

"""Check that every number in an ush-events report comes from the script's JSON,
and that the report names every group, anomaly and dump file of the summary.

Usage (from the project root):

    python -B skills/ush-events/scripts/check_report.py <report.md>
    python -B skills/ush-events/scripts/check_report.py --latest [--data-dir ush-data]

Rules (see ``references/report-format.md``):

- The first line of the report is exactly ``<!-- ush:summary <absolute path> -->``;
  the file must exist and parse as JSON.
- The report contains the line ``<!-- ush:not-checked -->``.
- Allowed numbers are the tokens of the summary plus the tokens of those items of
  the detail file (``detail_file`` in the summary) whose ids are named in
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
  (``| 3 | ...`` as the third row); and item ids (``g3``, ``n1``, ``a2``,
  ``b0``, ``r4``, ``d1``) of the summary, of the ``ush:detail`` items and of the groups cut
  from the summary. A token of that shape that is no such id is a number.
  Every other number is checked, also one that numbers a list item (a report
  has no numbered lists) or a quoted heading.
- Fenced code blocks are not scanned. Fences follow CommonMark: a fence line
  starts with at most 3 spaces (a block at the top level or directly in a
  first-level list item, ``-`` or a number 1-9; never in a nested list item or
  in a ``>`` quote), then 3 or more backticks or tildes; a block closes only
  on the same character, at least as long, with nothing after it, at exactly
  the indent of its opening fence. Any other fence is not recognised and the
  constants in it are checked. A line inside a block indented less than its
  opening fence is an error, and so is a line shaped like the closing fence
  at another indent (a renderer may close the block there).
- Every ``groups[*].id``, ``anomalies[*].id`` and ``dumps.files[*].id`` of the
  summary is named as a separate word (``g25`` does not name ``g2``) in a line
  that is scanned for numbers: not in a code block, not on the ``ush:summary``
  line and not on an ``ush:detail`` or ``ush:not-checked`` marker line. A
  missing list, or one that is not a list (``null`` for a source that could
  not be read), requires nothing. Boot sessions, noise items, reliability
  records, groups cut from the summary and ``ush:detail`` items are not
  required: the report selects or summarises them.
- No HTML and no links. Outside code blocks, only the ush: marker lines hold
  an HTML comment: a marker is the whole line (not in a quote or a list item)
  with one ``<!--`` and one ``-->`` and nothing after it. Any other ``<!--``,
  in inline code or after a backslash too, is an error; a literal one is
  written ``&lt;!--``. So is ``<`` before a letter, ``?``, ``!`` or ``/``
  anywhere in a line (written ``&lt;``), ``]:`` and ``](``. ``<`` before a
  space, a digit or ``=`` is text.

JSON files are tokenized from their parsed values (strings, numbers and keys),
not from the raw text, so ``\\u0105`` escapes cannot supply numbers. File paths and
names (``summary_file``, ``detail_file``, ``name``, ``path``, ``dump_path``,
``minidump_dir``, ``dump_file``), item ids (``id``) and references to them
(``dump``, ``bugcheck``, ``bugcheck_candidates``) supply none either. A hex token is backed
only by a hex value and a decimal token only by a decimal one. The
``ush:not-checked`` line must stand directly before or after a heading.
``--latest`` takes the newest ``events-*.md``, since other skills share ``reports/``.

The script counts; it does not judge whether a number is right, only whether
it is backed by the JSON, nor whether an item is described well, only whether
its id is there. Exit codes: 0 OK, 1 numbers not backed or summary items not
named, 2 the report or its JSON could not be checked.
"""

import argparse
import json
import re
import sys
from pathlib import Path

DETAIL_SECTIONS = ("groups", "noise", "boots", "anomalies", "reliability_records",
                   "dump_files")

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
# Row number in the first cell of a table row: "| 3 | ...".
TABLE_ROW_NUMBER = re.compile(r"^\s*\|\s*(?P<number>[0-9]+)\s*(?=\|)")
TABLE_ROW = re.compile(r"^\s*\|")
TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*$")
# An id of a summary or detail item: g3, n1, a2, b0, r4, d1 as a separate lowercase word.
ITEM_ID = re.compile(r"(?<![0-9A-Za-z_])[gnabrd][0-9]+(?![0-9A-Za-z_])")

# Keys whose values are file paths or file names, not readings (a minidump is
# named like 093026-54321-01.dmp).
PATH_KEYS = frozenset({"summary_file", "detail_file", "name", "path", "dump_path",
                       "minidump_dir", "dump_file"})
# Keys whose values are item ids (g3, b0) or references to them, not readings.
ID_KEYS = frozenset({"id", "dump", "bugcheck", "bugcheck_candidates"})
REPORT_GLOB = "events-*.md"
# A fence (CommonMark): at most 3 spaces of indent, then 3 or more backticks or
# tildes; the rest of an opening line is its info string.
FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<rest>.*)$")
# A line shaped like a closing fence, at any indent.
CLOSING_FENCE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*$")
HEADING = re.compile(r"^ {0,3}#{1,6}\s")
# One leading piece of a line that is not its text: indent, a quote marker, or
# a list marker followed by a space, a tab or the end of the line.
RAW_HTML = re.compile(r"<[A-Za-z?!/]")
LINE_PREFIX = re.compile(r"^(?:[ \t]+|>|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$))")

EXIT_OK, EXIT_NUMBERS, EXIT_ERROR = 0, 1, 2


class CheckError(Exception):
    """The report or one of its JSON files cannot be checked."""


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


def json_values(data) -> set[tuple[str, int]]:
    """Number tokens of every key, string and number in parsed JSON.

    The values of PATH_KEYS and ID_KEYS are skipped: a file path or an item id
    is not a reading, and its digits would back numbers the report made up.
    """
    found: set[tuple[str, int]] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                found.update(value for _, value in tokens(str(key)))
                if key not in PATH_KEYS and key not in ID_KEYS:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, bool) or item is None:
            continue  # True would otherwise count as 1
        elif isinstance(item, (int, float, str)):
            found.update(value for _, value in tokens(str(item)))
    return found


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


def detail_items(summary, ids: list[str]) -> list:
    """Return the detail-file items with the given ids; every id must exist."""
    if not isinstance(summary, dict) or not isinstance(summary.get("detail_file"), str):
        raise CheckError("the report names ush:detail ids but the summary has no detail_file")
    path = Path(summary["detail_file"])
    if not path.is_absolute():
        raise CheckError(f"detail_file in the summary is not an absolute path: {path}")
    detail = read_json(path, "detail file")
    if not isinstance(detail, dict):
        raise CheckError(f"detail file {path} is not a JSON object")
    by_id = {}
    for section in DETAIL_SECTIONS:
        items = detail.get(section)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    by_id[item["id"]] = item
    missing = [item_id for item_id in ids if item_id not in by_id]
    if missing:
        raise CheckError(
            f"ush:detail names ids not found in the detail file {path}: {', '.join(missing)}"
        )
    return [by_id[item_id] for item_id in ids]


def check(report: Path) -> tuple[list[str], int, list[str]]:
    """Return (unbacked-number messages, number of checked tokens,
    messages for the summary items the report does not name)."""
    lines = read_text(report, "report").splitlines()
    first = lines[0] if lines else ""
    match = SUMMARY_LINE.match(first)
    if not match:
        raise CheckError(
            "the first line of the report must be exactly "
            "'<!-- ush:summary <absolute path of the summary file> -->'"
        )
    # Code blocks are paste-ready commands: no markers and no reported numbers.
    fenced = _fenced_lines(lines)
    # Before the summary path: a comment after the marker would end up in the path.
    _reject_html(lines, fenced)
    summary_path = Path(match.group("path"))
    if not summary_path.is_absolute():
        raise CheckError(f"the ush:summary path is not absolute: {summary_path}")
    if not summary_path.is_file():
        raise CheckError(f"the summary file named on the first line does not exist: {summary_path}")
    summary = read_json(summary_path, "summary file")

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

    allowed = json_values(summary)
    for item in detail_items(summary, ids) if ids else []:
        allowed |= json_values(item)

    known_ids = item_ids(summary) | set(ids)

    in_order = _heading_numbers(lines)
    problems, checked = [], 0
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
        numbering = HEADING_NUMBER.match(line) if number - 1 in in_order else None
        if not numbering and position:
            cell = TABLE_ROW_NUMBER.match(line)
            if cell and int(cell["number"]) == position:
                numbering = cell
        if numbering:
            line = line[numbering.end():]
        mentioned.update(ITEM_ID.findall(line))
        line = ITEM_ID.sub(lambda m: " " if m.group() in known_ids else m.group(), line)
        for written, value in tokens(line):
            checked += 1
            if value not in allowed:
                problems.append(
                    f"line {number}: {written} is not in the summary or in a detail "
                    f"item named in ush:detail"
                )
    missing = [f"not named in the report: {item_id} ({where})"
               for item_id, where in required_ids(summary) if item_id not in mentioned]
    return problems, checked, missing


def required_ids(summary) -> list[tuple[str, str]]:
    """(id, list name) of the groups, anomalies and dump files of the summary.

    A list that is missing or not a list (``null``: the source could not be
    read) requires nothing.
    """
    if not isinstance(summary, dict):
        return []
    dumps = summary.get("dumps")
    lists = (("groups", summary.get("groups")),
             ("anomalies", summary.get("anomalies")),
             ("dumps.files", dumps.get("files") if isinstance(dumps, dict) else None))
    return [(item["id"], where) for where, items in lists if isinstance(items, list)
            for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def item_ids(summary) -> set[str]:
    """Ids of the summary's items, and of the groups cut from it.

    The cut groups are g<N+1>...g<N+truncated>, N being the number of groups
    in the summary; the report is told to mention them.
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
    if isinstance(summary, dict):
        groups, truncated = summary.get("groups"), summary.get("truncated")
        if (isinstance(groups, list) and isinstance(truncated, int)
                and not isinstance(truncated, bool)):
            found.update(f"g{n}" for n in range(len(groups) + 1, len(groups) + truncated + 1))
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
    """Indices of the lines of fenced code blocks, the fences included.

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
    fenced: set[int] = set()
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
            fenced.add(index)
        if fence is not None:
            fenced.add(index)
    if fence is not None:
        raise CheckError(f"code block opened at line {opened_at + 1} is never closed")
    return fenced


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


def latest_report(data_dir: Path) -> Path:
    reports = data_dir / "reports"
    try:
        found = sorted((p for p in reports.glob(REPORT_GLOB) if p.is_file()), key=lambda p: p.name)
    except OSError as exc:
        raise CheckError(f"{reports} could not be listed: {type(exc).__name__}: {exc}")
    if not found:
        raise CheckError(f"no report ({REPORT_GLOB}) in {reports}")
    return found[-1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_report.py",
        description="Check that every number in an ush-events report is backed by its JSON "
                    "and that the report names every group, anomaly and dump file.",
    )
    parser.add_argument("report", nargs="?", help="path of the report (.md)")
    parser.add_argument("--latest", action="store_true",
                        help=f"check the newest {REPORT_GLOB} (by name) in <data-dir>/reports/")
    parser.add_argument("--data-dir", default="ush-data",
                        help="data directory, relative to the working directory "
                             "(default: ush-data); used with --latest")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.report) == bool(args.latest):
        parser.error("give either a report path or --latest")
    try:
        if args.latest:
            report = latest_report(Path(args.data_dir).absolute())
        else:
            report = Path(args.report).absolute()
        problems, checked, missing = check(report)
    except CheckError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for line in problems + missing:
        print(line)
    if problems:
        print(f"FAILED: {report}: {len(problems)} of {checked} numbers are not backed by the JSON")
    if missing:
        print(f"FAILED: {report}: {len(missing)} summary items not named in the report")
    if problems or missing:
        return EXIT_NUMBERS
    print(f"OK: {report}: {checked} numbers checked")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

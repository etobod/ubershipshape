"""Check that every number in an ush-events report comes from the script's JSON.

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
  no figures), list and heading numbering at the start of a line (``1.``,
  ``12)``, ``## 2.``) and the row number in the first cell of a table row
  (``| 3 | ...``). Every other number is checked.

JSON files are tokenized from their parsed values (strings, numbers and keys),
not from the raw text, so ``\\u0105`` escapes cannot supply numbers. File paths
(``summary_file``, ``detail_file``) supply none either. A hex token is backed
only by a hex value and a decimal token only by a decimal one. The
``ush:not-checked`` line must stand directly before or after a heading.
``--latest`` takes the newest ``events-*.md``, since other skills share ``reports/``.

The script counts; it does not judge whether a number is right, only whether
it is backed by the JSON. Exit codes: 0 OK, 1 numbers not backed, 2 the report
or its JSON could not be checked.
"""

import argparse
import json
import re
import sys
from pathlib import Path

DETAIL_SECTIONS = ("groups", "noise", "boots", "anomalies")

SUMMARY_LINE = re.compile(r"^<!-- ush:summary (?P<path>\S.*?) -->\s*$")
NOT_CHECKED_LINE = re.compile(r"^\s*<!--\s*ush:not-checked\s*-->\s*$")
DETAIL_LINE = re.compile(r"^\s*<!--\s*ush:detail\b(?P<ids>.*?)-->\s*$")

# A hex literal that is not part of a longer word, or a run of ASCII digits.
TOKEN = re.compile(
    r"(?P<hex>(?<![0-9A-Za-z_])0[xX][0-9a-fA-F]+(?![0-9A-Za-z_]))|(?P<dec>[0-9]+)"
)
# Numbering at the start of a line: "1. ", "12) ", "## 2. ", "> 3. ".
LIST_NUMBER = re.compile(r"^\s*(?:>\s*)*(?:#{1,6}\s+)?[0-9]+[.)](?=\s|$)")
# Row number in the first cell of a table row: "| 3 | ...".
TABLE_ROW_NUMBER = re.compile(r"^\s*\|\s*[0-9]+\s*(?=\|)")

# Summary keys whose values are file paths, not readings.
PATH_KEYS = frozenset({"summary_file", "detail_file"})
REPORT_GLOB = "events-*.md"
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s*#{1,6}\s")

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

    The values of PATH_KEYS are skipped: a file path is not a reading, and its
    digits would back numbers the report made up.
    """
    found: set[tuple[str, int]] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                found.update(value for _, value in tokens(str(key)))
                if key not in PATH_KEYS:
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


def check(report: Path) -> tuple[list[str], int]:
    """Return (unbacked-number messages, number of checked tokens)."""
    lines = read_text(report, "report").splitlines()
    first = lines[0] if lines else ""
    match = SUMMARY_LINE.match(first)
    if not match:
        raise CheckError(
            "the first line of the report must be exactly "
            "'<!-- ush:summary <absolute path of the summary file> -->'"
        )
    summary_path = Path(match.group("path"))
    if not summary_path.is_absolute():
        raise CheckError(f"the ush:summary path is not absolute: {summary_path}")
    if not summary_path.is_file():
        raise CheckError(f"the summary file named on the first line does not exist: {summary_path}")
    summary = read_json(summary_path, "summary file")

    # Code blocks are paste-ready commands: no markers and no reported numbers.
    fenced = _fenced_lines(lines)
    visible = [("" if index in fenced else line) for index, line in enumerate(lines)]
    lines = visible

    if not any(NOT_CHECKED_LINE.match(line) for line in lines):
        raise CheckError(
            "the report has no '<!-- ush:not-checked -->' line before its "
            "'not checked' section"
        )
    if not any(NOT_CHECKED_LINE.match(line) and _next_to_heading(lines, index)
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

    problems, checked = [], 0
    for number, line in enumerate(lines[1:], start=2):
        if NOT_CHECKED_LINE.match(line) or DETAIL_LINE.match(line):
            continue
        numbering = LIST_NUMBER.match(line) or TABLE_ROW_NUMBER.match(line)
        if numbering:
            line = line[numbering.end():]
        for written, value in tokens(line):
            checked += 1
            if value not in allowed:
                problems.append(
                    f"line {number}: {written} is not in the summary or in a detail "
                    f"item named in ush:detail"
                )
    return problems, checked


def _fenced_lines(lines: list[str]) -> set[int]:
    """Indices of the lines of fenced code blocks, the fences included.

    A block closes only on the fence string that opened it; a block still
    open at the end of the report is an error, so it cannot hide the rest.
    """
    fenced: set[int] = set()
    fence, opened_at = None, 0
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if fence is None and match:
            fence, opened_at = match.group(1), index
        elif fence is not None and match and match.group(1) == fence:
            fence = None
            fenced.add(index)
        if fence is not None:
            fenced.add(index)
    if fence is not None:
        raise CheckError(f"code block opened at line {opened_at + 1} is never closed")
    return fenced


def _next_to_heading(lines: list[str], index: int) -> bool:
    """True when the nearest non-blank line before or after ``index`` is a heading."""
    for step in (-1, 1):
        at = index + step
        while 0 <= at < len(lines) and not lines[at].strip():
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
        description="Check that every number in an ush-events report is backed by its JSON.",
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
        problems, checked = check(report)
    except CheckError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if problems:
        for problem in problems:
            print(problem)
        print(f"FAILED: {report}: {len(problems)} of {checked} numbers are not backed by the JSON")
        return EXIT_NUMBERS
    print(f"OK: {report}: {checked} numbers checked")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

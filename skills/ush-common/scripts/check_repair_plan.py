"""Check that a repair plan has every section and an undo block for every run block.

Usage (from the project root):

    python -B skills/ush-common/scripts/check_repair_plan.py <plan.md>
    python -B skills/ush-common/scripts/check_repair_plan.py --latest [--data-dir DIR]

The format is described in ``skills/ush-common/references/repair-plan.md``.
The checker reads one plan and prints one JSON object on stdout:

- ``file``: the absolute path of the plan;
- ``ok``: true when nothing below is missing;
- ``missing_sections``: the required level-2 headings not found, in format order;
- ``blocks_without_undo``: ``"<skill> <id>"`` of every ``<!-- ush:block <skill> <id> -->``
  marker with no ``<!-- ush:undo <skill> <id> -->`` marker of the same skill and id,
  then ``"unmarked block, line N"`` for every fenced block under
  ``## Bloki do uruchomienia`` whose previous non-blank line is not a run marker.

An undo marker counts only under ``## Bloki cofajace`` (the heading from the
format) and only when its next non-blank line opens a fenced block. A
``<!-- ush:noundo <skill> <id> -->`` marker also counts as the undo of that
skill and id, for a block that cannot be undone: only under ``## Bloki cofajace``
and only when its next non-blank line is a line of words (not a fenced block,
a heading or another marker).
Headings and markers inside a fenced code block do not count. The checker
never judges the text the user wrote: it only looks for the headings and the
markers. ``--latest`` takes the newest ``*.md`` file (by modification time) in
``<data dir>/plans/``, never one in ``plans/done/``; with no such file or no
``plans/`` directory it is a usage error, and a ``plans/`` directory that
cannot be listed is a read error (exit 2 with the reason). The checker writes
nothing and creates no directory.

Exit codes: 0 the plan is complete, 1 something is missing, 2 the plan could
not be read or the call was wrong.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# load_script does not put this directory on sys.path; datadir lives next to this file.
sys.path.insert(0, str(Path(__file__).absolute().parent))

import datadir

EXIT_OK, EXIT_MISSING, EXIT_ERROR = 0, 1, 2

# The required level-2 headings, in format order (Polish, the user's language).
SECTIONS = (
    "Problem",
    "Wybrana opcja",
    "Bloki do uruchomienia",
    "Bloki cofaj\u0105ce",
    "Odczyt po zmianie",
    "Notatki",
)
RUN_SECTION = SECTIONS[2]
UNDO_SECTION = SECTIONS[3]

HEADING2 = re.compile(r"^ {0,3}##[ \t]+(?P<text>.*?)[ \t]*#*[ \t]*$")
MARKER = re.compile(
    r"^ {0,3}<!--[ \t]*ush:(?P<kind>block|undo|noundo)[ \t]+(?P<skill>\S+)[ \t]+(?P<id>\S+)[ \t]*-->[ \t]*$"
)
FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<rest>.*)$")
CLOSING_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})[ \t]*$")


class CheckError(Exception):
    """The plan cannot be read or listed."""


def opens_fence(line: str):
    """The fence string when the line opens a fenced code block, else None."""
    match = FENCE.match(line)
    if match and not (match["fence"][0] == "`" and "`" in match["rest"]):
        return match["fence"]
    return None


def closes_fence(line: str, fence: str) -> bool:
    closing = CLOSING_FENCE.match(line)
    return bool(closing and closing["fence"][0] == fence[0]
                and len(closing["fence"]) >= len(fence))


def check_text(text: str) -> tuple[list[str], list[str]]:
    """(missing sections, run blocks without undo) of a plan's text.

    A block still open at the end hides everything after its opening fence.
    """
    headings = set()
    runs: list[tuple[str, str]] = []
    undos = set()
    unmarked: list[str] = []
    section = None          # the current level-2 heading
    fence = None            # the opening fence of the block we are in
    previous = ""           # the previous non-blank line outside a block's body
    pending_undo = None     # an undo marker waiting for its fence
    pending_noundo = None   # a noundo marker waiting for its line of words
    for number, line in enumerate(text.splitlines(), start=1):
        if fence is not None:
            if closes_fence(line, fence):
                fence = None
                previous = line
            continue
        opening = opens_fence(line)
        if opening:
            if pending_undo is not None:
                undos.add(pending_undo)
                pending_undo = None
            # A noundo marker followed by a block is not a "cannot be undone" note.
            pending_noundo = None
            if section == RUN_SECTION:
                marker = MARKER.match(previous)
                if not (marker and marker["kind"] == "block"):
                    unmarked.append(f"unmarked block, line {number}")
            fence = opening
            previous = line
            continue
        if not line.strip():
            continue
        pending_undo = None
        heading = HEADING2.match(line)
        marker = MARKER.match(line)
        if pending_noundo is not None:
            if not heading and not marker:
                undos.add(pending_noundo)
            pending_noundo = None
        previous = line
        if heading:
            headings.add(heading["text"])
            # An extra level-2 heading stays inside the section it is in.
            if heading["text"] in SECTIONS:
                section = heading["text"]
            continue
        if marker:
            key = (marker["skill"], marker["id"])
            if marker["kind"] == "block":
                if key not in runs:
                    runs.append(key)
            elif section != UNDO_SECTION:
                pass
            elif marker["kind"] == "undo":
                pending_undo = key
            else:
                pending_noundo = key
    missing = [f"## {name}" for name in SECTIONS if name not in headings]
    without_undo = [f"{skill} {ident}" for skill, ident in runs if (skill, ident) not in undos]
    return missing, without_undo + unmarked


def read_plan(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckError(f"plan {path} could not be read: {type(exc).__name__}: {exc}")


def latest_plan(data_dir: Path) -> Path | None:
    """The newest ``*.md`` file directly in ``<data dir>/plans/``, or None."""
    plans = data_dir / "plans"
    stamped = []
    try:
        with os.scandir(plans) as entries:
            for entry in entries:
                if os.path.normcase(entry.name).endswith(".md") and entry.is_file():
                    stamped.append((entry.stat().st_mtime, entry.name, Path(entry.path)))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CheckError(f"{plans} could not be listed: {type(exc).__name__}: {exc}")
    if not stamped:
        return None
    return max(stamped)[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_repair_plan.py",
        description="Check that a repair plan has every required section and an undo "
                    "block for every run block.",
    )
    parser.add_argument("plan", nargs="?", help="path of the repair plan (.md)")
    parser.add_argument("--latest", action="store_true",
                        help="check the newest *.md (by modification time) in "
                             "<data-dir>/plans/, never one in plans/done/")
    datadir.add_arguments(parser, datadir.HELP + "; used with --latest")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.plan) == bool(args.latest):
        parser.error("give either a plan path or --latest")
    try:
        if args.latest:
            try:
                data_dir = datadir.resolve(args.data_dir, default=args.default_data_dir)
            except datadir.DataDirError as exc:
                parser.error(str(exc))
            plan = latest_plan(data_dir)
            if plan is None:
                parser.error(f"no repair plan (*.md) in {data_dir / 'plans'}")
        else:
            plan = Path(args.plan).absolute()
        missing, without_undo = check_text(read_plan(plan))
    except CheckError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return EXIT_ERROR
    ok = not missing and not without_undo
    print(json.dumps({
        "file": str(plan),
        "ok": ok,
        "missing_sections": missing,
        "blocks_without_undo": without_undo,
    }, indent=2))
    return EXIT_OK if ok else EXIT_MISSING


if __name__ == "__main__":
    sys.exit(main())

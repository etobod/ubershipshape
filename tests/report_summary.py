"""A clean summary section for the report fixtures (plan 055, M2).

Every real report profile has ``summary_section`` on, so every invented report
handed to the checker with a real profile opens with the section of the rule
"Summary first" (``skills/ush-common/references/report-style.md``): the
``<!-- ush:attention -->`` line directly before the report's first ``##``
heading, the 4 parts, each "nic" unless a fixture names its high or medium
recommendations in part 1, and the low count 0 (no fixture has a low one).
"""

import re

MARKER = "<!-- ush:attention -->"
NO_DECISIONS = "nie dotyczy: decyzje sprawdza ush-runall"
NOT_CHECKED = re.compile(r"^\s*<!--\s*ush:not-checked\s*-->\s*$")
LEVEL_2 = re.compile(r"^ {0,3}##(?=[ \t]|$)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
TITLE = re.compile(r"^ {0,3}#(?=[ \t]|$)")
INTRO_HEADING = "## Przegląd"
USH_MARKER = re.compile(r"^\s*<!--\s*ush:[^<>]*-->\s*$")


def summary_section(skill, decide=(), accepted=None):
    """The section's lines: ``decide`` are the lines of part 1 (each naming the main
    source of a high or medium recommendation of the fixture), "nic" without them;
    only ush-runall checks decisions (part 2). ``accepted``: the quiet accepted
    count a runall summary gives (``accepted_counts.quiet``, plan 067; ``"not_checked"``
    when it is null or missing), put on the
    last line after the low count; None for a summary without it."""
    return [
        MARKER,
        "## Podsumowanie",
        "",
        "### Do decyzji",
        *(decide or ["nic"]),
        "",
        "### Złamane decyzje",
        "nic" if skill == "ush-runall" else NO_DECISIONS,
        "",
        "### Otwarte plany naprawcze",
        "nic",
        "",
        ("Nic więcej nie wymaga uwagi: 0 niskich." if accepted is None
         else "Nic więcej nie wymaga uwagi: 0 niskich; zaakceptowanych nie sprawdzono."
         if accepted == "not_checked"
         else f"Nic więcej nie wymaga uwagi: 0 niskich, {accepted} zaakceptowanych."),
        "",
    ]


def printed_section(skill):
    """The section as the checker prints it after OK: no marker, no trailing blank."""
    lines = [line for line in summary_section(skill) if line != MARKER]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def with_summary(lines, skill, decide=(), accepted=None):
    """``lines`` with the section before the first ``##`` heading outside a fence
    (above a not-checked marker that stands directly over that heading); with no
    such heading, at the end. Line 1 (the ush:summary line) is never a heading.
    A clean fixture gives its dashboard a ``##`` heading of its own (rule
    "Summary first"), so the section lands right after the header, above it.

    Only the header may stand above the section: the ush:summary line, the
    ``#`` title and the one line under it, with blank and ush: marker lines. A
    fixture with any other line before its first ``##`` heading (an unheaded
    intro) gets the section right after its title (or line 1 without one) and
    ``## Przegląd`` over the intro, so a block or table is never cut.
    """
    at, intro = _place(lines)
    if intro:
        return [*lines[:at], *summary_section(skill, decide, accepted), INTRO_HEADING, *lines[at:]]
    if at == len(lines):
        return [*lines, "", *summary_section(skill, decide, accepted)]
    return [*lines[:at], *summary_section(skill, decide, accepted), *lines[at:]]


def report_line(lines, index, skill, decide=()):
    """The 1-based report line of ``lines[index]`` once ``with_summary`` has put
    the section in (``lines[0]`` is the ush:summary line, report line 1)."""
    at, intro = _place(lines)
    if index < at or at == len(lines):
        return index + 1
    return index + 1 + len(summary_section(skill, decide)) + (1 if intro else 0)


def _place(lines):
    """(index the section goes before, whether an unheaded intro starts there)."""
    fence, first = None, len(lines)
    for index, line in enumerate(lines):
        if fence is not None:
            closing = FENCE.match(line)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence):
                fence = None
            continue
        if (opening := FENCE.match(line)):
            fence = opening.group(1)
            continue
        if index and LEVEL_2.match(line):
            first = index - 1 if NOT_CHECKED.match(lines[index - 1]) else index
            break
    title_seen = False
    for index in range(1, first):
        line = lines[index]
        if not line.strip() or USH_MARKER.match(line):
            continue
        if TITLE.match(line) and not title_seen:
            title_seen = True
        else:
            return index, True
    return first, False

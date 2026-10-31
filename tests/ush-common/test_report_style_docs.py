"""The shared report style document and the per-skill report formats agree.

test_every_format_follows_style reads the shipped documents and looks for phrases
the common style replaced. test_examples_match_checker cuts the Good:/Bad: examples
of rules 1, 7 and 9 out of report-style.md and runs them through check_report with
an invented events summary: Good examples pass, Bad examples fail.
test_recommendation_two_parts checks the two-part layout of rule 4 and runs its
Good example through check_report; test_blocks_after_decision and
test_formats_blocks_after_decision check that no document asks for a change
block in the recommendations before the user decides. test_skills_name_repair_plan and
test_rule8_repair_plan (plan 006 M2) check that the blocks go into a repair plan per
repair-plan.md, not into the chat. All data invented.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path

from tests.skill_loader import REPO_ROOT, load_script

SKILLS = REPO_ROOT / "skills"
STYLE_DOC = SKILLS / "ush-common" / "references" / "report-style.md"
SUMMARY_CONTRACT = SKILLS / "ush-common" / "references" / "summary-contract.md"
EVENTS_SKILL = SKILLS / "ush-events" / "SKILL.md"
INVENTORY_SKILL = SKILLS / "ush-inventory" / "SKILL.md"

# Phrases no report format may contain once wrapped lines are joined.
FORBIDDEN_IN_FORMATS = (
    "as UTC",
    "`generated_at`, UTC",
    "do not convert times",
    "percent free",
    "`Other groups: g29 (2), g22 (1)",
    "| - |",
    "`--data-dir` value of a block for an elevated shell",
    "any other code block writes it from the environment",
    "`--data-dir` of an elevated-shell block",
    "(`1500.0`, not",
    "may be written in local format",
)
EXACT_JSON_PHRASE = "exactly as the JSON has it"  # checked case-insensitively

ICONS = "(?:\U0001F527|\U0001F50D|✅|❌)"
LEGEND_LINE = re.compile(r"^\s*-\s+" + ICONS + r"\s")
LEGEND_WITH_HYPHEN = re.compile(r"^\s*-\s+" + ICONS + r"\s[^\n]*?\s-\s")
TABLE_DOT_DECIMAL = re.compile(r"\|\s*\d+\.\d+\s*\|")
DOT_DECIMAL_PERCENT = re.compile(r"\d+\.\d+\s*%")
DOT_DECIMAL_PERCENT_WORD = re.compile(r"\d+\.\d+ percent")

LEGEND_SKILLS = ("ush-events", "ush-health", "ush-settings", "ush-inventory")

STYLE_DOC_REQUIRED = (
    "Problem",
    "Co zrobić",
    "Szczegóły",
    "Waga",
    "Rodzaj",
    "Ryzyko",
    "Dowód",
    "Uprawnienia",
    "Cofnięcie",
    "—",
    "Set-Location",
    "--data-dir",
    "Brak zaleceń w tym przebiegu.",
)

# Rule markers of the examples run through the checker; each one gets the
# five-group line appended unless it is the long-list rule itself.
RULE_MARKERS = {
    "rule 1": ("**Time.**", True),
    "rule 7": ("**Long lists.**", False),
    "rule 9": ("**Script commands.**", True),
}
NEXT_RULE = re.compile(r"^\d+\.\s+\*\*")
FENCE_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})")

# Two-part recommendation layout of rule 4: part one is read first, part two
# stands under the `Szczegóły` label lower in the same recommendation.
PART_ONE_LABELS = ("Problem", "Co zrobić", "Waga")
DETAILS_LABEL = "Szczegóły"
PART_TWO_LABELS = ("Dowód", "Uprawnienia", "Cofnięcie")
DETAILS_TABLE_LABELS = ("Rodzaj", "Ryzyko", "Dowód", "Uprawnienia", "Cofnięcie")
TABLE_SEPARATOR = re.compile(r"^\|(\s*:?-+:?\s*\|)+$")

RULE_8_TITLE = "**Blocks after the decision.**"
DECISION_WORD = re.compile(r"\bdecid|\bdecision", re.IGNORECASE)

# Plan 006 M2 (loc/inbox/006-plan-3-medium-repair-plans.md): the blocks go into a repair
# plan per repair-plan.md, not into the chat. Assumptions beyond the plan:
# - a repair plan is named "repair plan", "repair-plan" or "repair_plan";
# - "not into the chat" is a sentence naming "chat" together with a negation;
# - a report format that puts a block into the chat is a sentence naming "block" and
#   "chat" with no negation.
REPAIR_PLAN_DOC = "repair-plan.md"
REPAIR_PLAN = re.compile(r"\brepair[-_ ]plan", re.IGNORECASE)
CHAT_WORD = re.compile(r"\bchat\b", re.IGNORECASE)
BLOCK_WORD = re.compile(r"\bblocks?\b", re.IGNORECASE)
NEGATION = re.compile(r"\b(never|no|not|nothing)\b", re.IGNORECASE)
# The skills whose SKILL.md must name repair-plan.md (K2) and whose report-format.md
# must put the blocks into a repair plan (K4).
REPAIR_PLAN_SKILLS = (
    "ush-settings", "ush-files", "ush-inventory", "ush-processes",
    "ush-health", "ush-events", "ush-runall",
)
REPAIR_PLAN_PATH = SKILLS / "ush-common" / "references" / REPAIR_PLAN_DOC
FENCE_TEXT = "```"  # a bare fence line

# Old rule 8 text that put the block into the report before the user decided.
FORBIDDEN_IN_STYLE = (
    "**Blocks now.**",
    "gets its paste-ready block and its rollback in the report's recommendations section",
    "Blok do wklejenia i blok cofający są niżej, przy zaleceniu.",
    "blok przywracający poniżej",
)

# Old report-format phrases that ask for a change block in the report's
# recommendations. A sentence holding one passes only when it also says the
# block comes after the user's decision.
OLD_BLOCK_PHRASES = (
    "A `change` gives a paste-ready block",
    "the paste-ready block from `SKILL.md`",
    "puts the `--block` output into a",
    "the section gives the block",
    "the block, copied word for word into a fenced `powershell` code block",
    "its block stands in section 6",
    "the change blocks of the recommendations",
)

GROUPS_LINE = (
    "Grupy: g3 Invented-Disk (40), g29 Service Control Manager (2), "
    "g22 Kernel-Power (1), g7 Invented-Sync (1), g12 Invented-Update (1)."
)


def plus_two(dt):
    """A fixed +02:00 zone, independent of the machine running the tests."""
    return dt.astimezone(timezone(timedelta(hours=2)))


def _join(text):
    """Join wrapped lines: every whitespace run holding a newline becomes one space."""
    return re.sub(r"\s*\n\s*", " ", text)


def _sentences(joined):
    return re.split(r"\.(?=\s|$)", joined)


def _formats():
    return sorted(SKILLS.glob("ush-*/references/report-format.md"))


def _rule_section(lines, marker):
    """Lines of the rule whose line holds marker, up to the next numbered rule; None if absent."""
    for start, line in enumerate(lines):
        if marker in line:
            break
    else:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if NEXT_RULE.match(lines[index]):
            end = index
            break
    return lines[start:end]


def _numbered_rule(lines, number):
    """Lines of rule `number` (a line like `4. **Title.**`) up to the next numbered rule."""
    opening = re.compile(r"^" + str(number) + r"\.\s+\*\*")
    for start, line in enumerate(lines):
        if opening.match(line):
            break
    else:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if NEXT_RULE.match(lines[index]):
            end = index
            break
    return lines[start:end]


def _tables(section):
    """(lead text, label column) for every Markdown table outside fenced blocks.

    The lead text is the prose between the previous table (or the section start)
    and this table; the label column is the second cell of each body row.
    """
    tables = []
    lead, rows, in_fence = [], None, False
    for line in section:
        stripped = line.strip()
        if FENCE_OPEN.match(line):
            in_fence = not in_fence
        if not in_fence and stripped.startswith("|"):
            if rows is None:
                rows = []
            rows.append(stripped)
            continue
        if rows is not None:
            body = [row for row in rows[1:] if not TABLE_SEPARATOR.match(row)]
            labels = [row.strip("|").split("|")[1].strip() for row in body]
            tables.append(("\n".join(lead), labels))
            lead, rows = [], None
        lead.append(line)
    if rows is not None:
        body = [row for row in rows[1:] if not TABLE_SEPARATOR.match(row)]
        tables.append(("\n".join(lead), [row.strip("|").split("|")[1].strip() for row in body]))
    return tables


def _examples(section):
    """(label, content lines, error) for every Good:/Bad: line followed by a fenced block."""
    found = []
    index = 0
    while index < len(section):
        label = section[index].strip()
        index += 1
        if label not in ("Good:", "Bad:"):
            continue
        while index < len(section) and not section[index].strip():
            index += 1
        if index >= len(section):
            found.append((label, None, "no fenced block after the label"))
            break
        opening = FENCE_OPEN.match(section[index])
        if not opening:
            found.append((label, None, f"no fenced block after the label: {section[index]!r}"))
            continue
        indent, fence = opening.group(1), opening.group(2)
        closing = re.compile("^" + re.escape(fence[0]) + "{" + str(len(fence)) + ",}$")
        content = []
        index += 1
        closed = False
        while index < len(section):
            line = section[index]
            index += 1
            if closing.match(line.strip()):
                closed = True
                break
            content.append(line[len(indent):] if line.startswith(indent) else line.lstrip())
        if not closed:
            found.append((label, None, "fenced block is not closed inside the rule"))
            continue
        found.append((label, content, None))
    return found


class TestReportStyleDocs(unittest.TestCase):
    def test_every_format_follows_style(self):
        formats = _formats()
        self.assertGreaterEqual(len(formats), 5, f"report formats found: {formats}")

        for path in formats:
            rel = path.relative_to(REPO_ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            joined = _join(text)
            lines = text.splitlines()

            for phrase in FORBIDDEN_IN_FORMATS:
                with self.subTest(format=rel, check=f"no phrase {phrase!r}"):
                    self.assertNotIn(phrase, joined)

            with self.subTest(format=rel, check=f"no phrase {EXACT_JSON_PHRASE!r} in any case"):
                self.assertNotIn(EXACT_JSON_PHRASE.lower(), joined.lower())

            with self.subTest(format=rel, check="no table cell with a dot decimal"):
                bad = [line for line in lines
                       if line.lstrip().startswith("|") and TABLE_DOT_DECIMAL.search(line)]
                self.assertEqual(bad, [])

            with self.subTest(format=rel, check="no dot decimal with a percent"):
                bad = [line for line in lines
                       if DOT_DECIMAL_PERCENT.search(line) or DOT_DECIMAL_PERCENT_WORD.search(line)]
                self.assertEqual(bad, [])

            with self.subTest(format=rel, check="recommendation fields point to rule 4"):
                field_sentences = [s for s in _sentences(joined)
                                   if "`weight`, `kind`, `risk`" in s or "rule 4" in s]
                self.assertTrue(field_sentences,
                                "no sentence names `weight`, `kind`, `risk` or rule 4")
                for sentence in field_sentences:
                    self.assertIn("report-style.md", sentence)

            with self.subTest(format=rel, check="legend lines use a dash, not a hyphen"):
                bad = [line for line in lines if LEGEND_WITH_HYPHEN.match(line)]
                self.assertEqual(bad, [])

            with self.subTest(format=rel, check="refers to report-style.md"):
                self.assertIn("report-style.md", text)

        for skill in LEGEND_SKILLS:
            path = SKILLS / skill / "references" / "report-format.md"
            with self.subTest(format=skill, check="has a legend line with an icon"):
                self.assertTrue(path.is_file(), f"missing {path}")
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertTrue([line for line in lines if LEGEND_LINE.match(line)])

        with self.subTest(check="ush-events SKILL.md has no old risk layout"):
            self.assertNotIn("**risk:** high -", _join(EVENTS_SKILL.read_text(encoding="utf-8")))

        with self.subTest(check="ush-inventory SKILL.md has no elevated-shell-only exception"):
            self.assertNotIn("`--data-dir` of an elevated-shell block",
                             _join(INVENTORY_SKILL.read_text(encoding="utf-8")))

        with self.subTest(check="report-style.md exists"):
            self.assertTrue(STYLE_DOC.is_file(), f"missing {STYLE_DOC}")
        style_text = STYLE_DOC.read_text(encoding="utf-8") if STYLE_DOC.is_file() else ""
        for required in STYLE_DOC_REQUIRED:
            with self.subTest(check=f"report-style.md contains {required!r}"):
                self.assertIn(required, style_text)

        with self.subTest(check="summary-contract.md refers to report-style.md"):
            self.assertIn("report-style.md", SUMMARY_CONTRACT.read_text(encoding="utf-8"))

    def _make_temp_root(self):
        # The temp path backs no number: it stands only on the unscanned
        # ush:summary line and under the profile's path_keys.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def _write_summary(self, root):
        work = root / "work"
        work.mkdir()
        detail_file = work / "events-detail.json"
        summary_file = work / "events-summary.json"
        detail_file.write_text(
            json.dumps({"groups": [], "noise": [], "boots": [], "anomalies": []}),
            encoding="utf-8",
        )
        summary = {
            "skill": "ush-events",
            "generated_at": "2026-09-30T07:26:40+00:00",
            "group_count": 5,
            "groups": [
                {"id": "g3", "provider": "Invented-Disk", "count": 40},
                {"id": "g29", "provider": "Service Control Manager", "count": 2},
                {"id": "g22", "provider": "Kernel-Power", "count": 1},
                {"id": "g7", "provider": "Invented-Sync", "count": 1},
                {"id": "g12", "provider": "Invented-Update", "count": 1},
            ],
            "anomalies": [],
            "dumps": {"files": []},
            "detail_file": str(detail_file),
            "summary_file": str(summary_file),
        }
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        return summary_file

    def _run_example(self, check, reports_dir, summary_file, name, content, with_groups):
        body = [f"<!-- ush:summary {summary_file} -->", "# Raport", *content]
        if with_groups:
            body.append(GROUPS_LINE)
        body += ["## Nie sprawdzono", "<!-- ush:not-checked -->", "Nic."]
        report = reports_dir / name
        report.write_text("\n".join(body) + "\n", encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = check.main([str(report)], to_local=plus_two)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_examples_match_checker(self):
        self.assertTrue(STYLE_DOC.is_file(), f"missing {STYLE_DOC}")
        lines = STYLE_DOC.read_text(encoding="utf-8").splitlines()

        check = load_script("ush-common", "check_report")
        root = self._make_temp_root()
        reports_dir = root / "reports"
        reports_dir.mkdir()
        summary_file = self._write_summary(root)

        for rule, (marker, with_groups) in RULE_MARKERS.items():
            section = _rule_section(lines, marker)
            with self.subTest(rule=rule, check="section found"):
                self.assertIsNotNone(section, f"no line holds {marker!r}")
            examples = _examples(section or [])
            labels = [label for label, content, _ in examples if content is not None]
            with self.subTest(rule=rule, check="has a Good and a Bad example"):
                self.assertIn("Good:", labels)
                self.assertIn("Bad:", labels)

            for number, (label, content, error) in enumerate(examples, 1):
                with self.subTest(rule=rule, example=number, label=label):
                    self.assertIsNone(error, error)
                    name = f"example-{rule.replace(' ', '-')}-{number}.md"
                    code, output = self._run_example(
                        check, reports_dir, summary_file, name, content, with_groups
                    )
                    expected = 0 if label == "Good:" else 1
                    self.assertEqual(
                        code, expected,
                        f"{label} example of {rule}:\n" + "\n".join(content)
                        + f"\noutput:\n{output}",
                    )

    def test_recommendation_two_parts(self):
        self.assertTrue(STYLE_DOC.is_file(), f"missing {STYLE_DOC}")
        lines = STYLE_DOC.read_text(encoding="utf-8").splitlines()
        section = _numbered_rule(lines, 4)
        self.assertIsNotNone(section, "report-style.md has no rule 4")
        rule_text = "\n".join(section)

        # The layout is defined by two tables: part one, then part two under a
        # paragraph that names `Szczegóły`. Labels are read from the label
        # column of each table, so a label in an intro example does not count.
        self.assertIn(DETAILS_LABEL, rule_text, "rule 4 does not name `Szczegóły`")
        tables = _tables(section)
        self.assertEqual(len(tables), 2,
                         f"rule 4 should define the layout in two tables, found {len(tables)}")
        (_, part_one), (lead_two, part_two) = tables
        with self.subTest(check=f"the part-two table follows a paragraph naming {DETAILS_LABEL!r}"):
            self.assertIn(DETAILS_LABEL, lead_two)
        with self.subTest(check="part one holds Problem, Co zrobić, Waga in this order"):
            self.assertEqual(part_one, list(PART_ONE_LABELS))
        with self.subTest(check=f"{DETAILS_LABEL!r} holds the part-two fields in this order"):
            self.assertEqual(part_two, list(DETAILS_TABLE_LABELS))

        # The Good example puts the evidence, permissions and rollback under `Szczegóły`.
        goods = [content for label, content, error in _examples(section)
                 if label == "Good:" and content is not None and error is None]
        self.assertTrue(goods, "rule 4 has no Good example in a closed fenced block")
        example = goods[0]
        example_text = "\n".join(example)
        self.assertIn(DETAILS_LABEL, example_text,
                      "the Good example of rule 4 has no `Szczegóły`")
        details_in_example = example_text.index(DETAILS_LABEL)
        for label in PART_TWO_LABELS:
            with self.subTest(check=f"Good example has {label!r} after {DETAILS_LABEL!r}"):
                self.assertIn(label, example_text)
                self.assertGreater(example_text.index(label), details_in_example)

        # The Good example passes the report checker.
        check = load_script("ush-common", "check_report")
        root = self._make_temp_root()
        reports_dir = root / "reports"
        reports_dir.mkdir()
        summary_file = self._write_summary(root)
        code, output = self._run_example(
            check, reports_dir, summary_file, "example-rule-4-good.md", example, True
        )
        self.assertEqual(code, 0, "Good example of rule 4:\n" + example_text
                         + f"\noutput:\n{output}")

    def test_blocks_after_decision(self):
        self.assertTrue(STYLE_DOC.is_file(), f"missing {STYLE_DOC}")
        text = STYLE_DOC.read_text(encoding="utf-8")
        joined = _join(text)

        for phrase in FORBIDDEN_IN_STYLE:
            with self.subTest(check=f"report-style.md has no phrase {phrase!r}"):
                self.assertNotIn(phrase, joined)

        with self.subTest(check="no rule puts a block in the recommendations before a decision"):
            bad = [s.strip() for s in _sentences(joined)
                   if "recommendations section" in s and "block" in s
                   and not DECISION_WORD.search(s)]
            self.assertEqual(bad, [])

        section = _numbered_rule(text.splitlines(), 8)
        self.assertIsNotNone(section, "report-style.md has no rule 8")
        rule_text = _join("\n".join(section))
        with self.subTest(check="rule 8 is titled 'Blocks after the decision'"):
            self.assertTrue(re.sub(r"^8\.\s+", "", section[0]).startswith(RULE_8_TITLE),
                            f"rule 8 opens with {section[0]!r}")
        with self.subTest(check="rule 8 names the --block printer"):
            self.assertIn("`--block`", rule_text)
        with self.subTest(check="rule 8 ties the block to the user's decision"):
            block_sentences = [s for s in _sentences(rule_text) if "`--block`" in s]
            self.assertTrue(block_sentences)
            self.assertTrue(any(DECISION_WORD.search(s) for s in block_sentences),
                            f"no sentence with `--block` mentions the decision: {block_sentences}")
        with self.subTest(check="rule 8 puts the blocks into a repair plan"):
            plan_sentences = [s for s in _sentences(rule_text)
                              if BLOCK_WORD.search(s) and REPAIR_PLAN.search(s)]
            self.assertTrue(plan_sentences, f"no sentence of rule 8 puts a block into a "
                                            f"repair plan: {rule_text}")

    def test_skills_name_repair_plan(self):
        # K2: every skill that offers a change names repair-plan.md in its SKILL.md.
        for skill in REPAIR_PLAN_SKILLS:
            path = SKILLS / skill / "SKILL.md"
            with self.subTest(skill=skill):
                self.assertTrue(path.is_file(), f"missing {path}")
                self.assertIn(REPAIR_PLAN_DOC, path.read_text(encoding="utf-8"))

    def test_rule8_repair_plan(self):
        # K4: rule 8 and every skill's report format put the blocks into a repair plan
        # per repair-plan.md, not into the chat.
        self.assertTrue(STYLE_DOC.is_file(), f"missing {STYLE_DOC}")
        section = _numbered_rule(STYLE_DOC.read_text(encoding="utf-8").splitlines(), 8)
        self.assertIsNotNone(section, "report-style.md has no rule 8")
        rule_text = _join("\n".join(section))

        with self.subTest(check="rule 8 names repair-plan.md"):
            self.assertIn(REPAIR_PLAN_DOC, rule_text)
        with self.subTest(check="rule 8 says the blocks do not go into the chat"):
            found = [s for s in _sentences(rule_text)
                     if CHAT_WORD.search(s) and NEGATION.search(s)]
            self.assertTrue(found, f"no sentence of rule 8 keeps the blocks out of the chat: "
                                   f"{rule_text}")
        with self.subTest(check="rule 8 has no sentence giving a block in the chat"):
            bad = [s.strip() for s in _sentences(rule_text)
                   if BLOCK_WORD.search(s) and CHAT_WORD.search(s) and not NEGATION.search(s)]
            self.assertEqual(bad, [])

        for skill in REPAIR_PLAN_SKILLS:
            path = SKILLS / skill / "references" / "report-format.md"
            with self.subTest(format=skill, check="names repair-plan.md"):
                self.assertTrue(path.is_file(), f"missing {path}")
                self.assertIn(REPAIR_PLAN_DOC, path.read_text(encoding="utf-8"))

        for path in _formats():
            rel = path.relative_to(REPO_ROOT).as_posix()
            joined = _join(path.read_text(encoding="utf-8"))
            with self.subTest(format=rel, check="no sentence giving a block in the chat"):
                bad = [s.strip() for s in _sentences(joined)
                       if BLOCK_WORD.search(s) and CHAT_WORD.search(s)
                       and not NEGATION.search(s)]
                self.assertEqual(bad, [])

    # Plan 006 M2, review round 1 (judge "fix" verdicts). Assumptions beyond the verdicts:
    # - the "judge" step of a SKILL.md is the numbered step of "## Steps" that opens
    #   with "Judge the findings";
    # - a sentence of repair-plan.md is cut at ". " with wrapped lines joined.

    def test_repair_plan_noundo_marker(self):
        # Fix 1: repair-plan.md documents the no-undo marker and its two conditions;
        # the skills with irreversible blocks name it.
        text = _join(REPAIR_PLAN_PATH.read_text(encoding="utf-8"))
        with self.subTest(check="repair-plan.md shows the noundo marker"):
            self.assertIn("<!-- ush:noundo ", text)
        found = [s for s in _sentences(text)
                 if "no-undo marker" in s and "## Bloki cofające" in s
                 and "line of words" in s and "fenced block" in s]
        with self.subTest(check="the noundo marker counts only under the undo section, "
                                "before a line of words, never before a fence"):
            self.assertTrue(found, text)
        for skill, places in (("ush-files", 1), ("ush-events", 2)):
            skill_text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=skill, check="names the noundo marker for each "
                                                 "irreversible block"):
                self.assertGreaterEqual(skill_text.count(f"<!-- ush:noundo {skill} <id> -->"),
                                        places)

    def test_repair_plan_block_sources(self):
        # Fix 3: a block comes from the --block printer or, without one, from the
        # SKILL.md template with every guard kept; never otherwise by hand.
        text = _join(REPAIR_PLAN_PATH.read_text(encoding="utf-8"))
        found = [s for s in _sentences(text)
                 if "`--block`" in s and "template" in s and "`SKILL.md`" in s
                 and "every guard" in s]
        self.assertTrue(found, f"no sentence naming the printer and the template: {text}")
        self.assertIn("never written or filled in by hand otherwise", text)

    def test_repair_plan_never_overwritten(self):
        # Fix 8: a taken name gets -2, -3; also for the move to plans/done/.
        lines = REPAIR_PLAN_PATH.read_text(encoding="utf-8").splitlines()
        start = lines.index("## Location and name")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
        section = _join("\n".join(lines[start:end]))
        with self.subTest(check="a taken name gets -2, -3"):
            self.assertIn("`-2`, `-3`", section)
            self.assertIn("never overwritten", section)
            self.assertIn("`plans/done/`", section)
        with self.subTest(check="the same rule for the move to plans/done/"):
            found = [s for s in _sentences(section)
                     if "move to `plans/done/`" in s and "same rule" in s]
            self.assertTrue(found, section)

    def test_health_contract_repair_plan(self):
        # Fix 6: the ush-health contract gives the step in a repair plan, not in the chat.
        path = SKILLS / "ush-health" / "references" / "summary-contract.md"
        joined = _join(path.read_text(encoding="utf-8"))
        self.assertNotIn("in words in the chat", joined)
        self.assertIn("in words in a repair plan per "
                      "`<plugin root>/skills/ush-common/references/repair-plan.md`", joined)

    def test_skills_read_back_open_plans(self):
        # Fix 9: before judging, every skill that offers changes reads back its open plans.
        for skill in REPAIR_PLAN_SKILLS:
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            steps = re.split(r"(?m)^(?=\d+\.\s)", text.split("## Steps", 1)[-1])
            judge = [_join(step) for step in steps if step.startswith(
                tuple(f"{n}. Judge the findings" for n in range(1, 10)))]
            with self.subTest(skill=skill):
                self.assertEqual(len(judge), 1, f"no single judge step in {skill}")
                step = judge[0]
                for phrase in ("Before judging, list `<data dir>/plans/` (not `done/`)",
                               "`Odczyt po zmianie`", "`Notatki`", "`plans/done/`",
                               "If `plans/` cannot be listed, say so",
                               "not \"no plans\""):
                    self.assertIn(phrase, step)

    def test_read_back_moves_only_applied_plans(self):
        # M2 r2 fix 3, final review fix 2: an open plan moves to done only when every
        # value the plan sets (by a run block or by a step in words) reads back as
        # set; otherwise it stays open.
        for skill in REPAIR_PLAN_SKILLS:
            text = _join((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"))
            with self.subTest(skill=skill):
                found = [s for s in _sentences(text) if "Before judging" in s
                         and "compare this run's values with the values its run blocks set" in s
                         and "only when every value the plan sets (by a run block or by a step in words) reads back as set" in s
                         and "otherwise it stays open" in s]
                self.assertTrue(found, skill)

    def test_every_move_to_done_is_conditional(self):
        # Final review fix 1: every sentence that moves a read-back plan to plans/done/
        # keeps it open unless every value reads back as set.
        files = [SKILLS / s / "SKILL.md" for s in REPAIR_PLAN_SKILLS]
        files += [SKILLS / "ush-runall" / "references" / "report-format.md",
                  SKILLS / "ush-common" / "references" / REPAIR_PLAN_DOC]
        for path in files:
            text = _join(path.read_text(encoding="utf-8"))
            moves = [s for s in _sentences(text) if "plans/done/" in s
                     and "move" in s and ("Notatki" in s or "is the file moved" in s)]
            with self.subTest(file=str(path.relative_to(SKILLS))):
                self.assertTrue(moves, "no move sentence")
                for sentence in moves:
                    self.assertIn("stays open", sentence)

    def test_open_plans_note_not_confirmed(self):
        # Final review fix 3: an open plan in the verdict is "not confirmed by a read-back
        # yet", never "not read back yet" (a partial read-back keeps it open).
        text = _join((SKILLS / "ush-runall" / "references" / "report-format.md")
                     .read_text(encoding="utf-8"))
        self.assertIn("not confirmed by a read-back yet (the last result, if any, is under "
                      "its `Notatki`)", text)
        self.assertNotIn("have not been read back yet", text)

    def test_events_copy_only_noundo(self):
        # M2 r2 fix 6: the copy without --delete-source gets a noundo marker saying
        # there is nothing to undo on the machine.
        text = _join((SKILLS / "ush-events" / "SKILL.md").read_text(encoding="utf-8"))
        found = [s for s in _sentences(text) if "Without `--delete-source`" in s
                 and "<!-- ush:noundo ush-events <id> -->" in s
                 and "nothing to undo on the machine" in s]
        self.assertTrue(found)

    def test_inventory_block_split(self):
        # Fix 2: ush-inventory step 5 splits each printed entry at the printer's own
        # rollback line: above into the run fence, that line and below into the undo fence.
        inventory = load_script("ush-inventory", "inventory")
        note = inventory.ROLLBACK_NOTE
        self.assertEqual(note, "# Rollback, same shell:")
        text = INVENTORY_SKILL.read_text(encoding="utf-8")
        steps = re.split(r"(?m)^(?=\d+\.\s)", text.split("## Steps", 1)[-1])
        step = _join(next(s for s in steps if s.startswith("5. ")))
        found = [s for s in _sentences(step)
                 if f"Split each entry at its `{note}` line" in s
                 and "above it" in s and "<!-- ush:block ush-inventory <id> -->" in s
                 and "below it" in s and "<!-- ush:undo ush-inventory <id> -->" in s
                 and "same id" in s
                 and "put the entry's shell on a line above its undo marker" in s]
        self.assertTrue(found, step)

    def test_fenced_plan_name_passes_checker(self):
        # Fix 5: an open plan's file name in a fenced block passes check_report; in
        # inline code its digits are checked against the summary JSON and fail.
        check = load_script("ush-common", "check_report")
        root = self._make_temp_root()
        reports_dir = root / "reports"
        reports_dir.mkdir()
        summary_file = self._write_summary(root)
        lead = "Otwarte plany naprawy (wartości jeszcze nie odczytane):"
        cases = (
            ("fenced", [lead, "", FENCE_TEXT, "2026-10-15-port-445.md", FENCE_TEXT, ""], 0),
            ("inline", [lead + " `2026-10-15-port-445.md`", ""], 1),
        )
        for name, content, expected in cases:
            with self.subTest(case=name):
                code, output = self._run_example(
                    check, reports_dir, summary_file, f"plan-name-{name}.md", content, True)
                self.assertEqual(code, expected, output)

    def test_formats_blocks_after_decision(self):
        formats = _formats()
        self.assertGreaterEqual(len(formats), 5, f"report formats found: {formats}")

        for path in formats:
            rel = path.relative_to(REPO_ROOT).as_posix()
            joined = _join(path.read_text(encoding="utf-8"))
            for phrase in OLD_BLOCK_PHRASES:
                with self.subTest(format=rel, check=f"{phrase!r} only after a decision"):
                    bad = [s.strip() for s in _sentences(joined)
                           if phrase in s and not DECISION_WORD.search(s)]
                    self.assertEqual(bad, [])

    def test_contracts_blocks_after_decision(self):
        # Plan 004 final review: a skill's own summary contract repeats no block
        # rule that a report format dropped (ush-health once still said so).
        contracts = sorted((REPO_ROOT / "skills").glob("ush-*/references/summary-contract.md"))
        self.assertTrue(contracts)
        for path in contracts:
            rel = path.relative_to(REPO_ROOT).as_posix()
            joined = _join(path.read_text(encoding="utf-8"))
            for phrase in OLD_BLOCK_PHRASES:
                with self.subTest(contract=rel, check=f"{phrase!r} only after a decision"):
                    bad = [s.strip() for s in _sentences(joined)
                           if phrase in s and not DECISION_WORD.search(s)]
                    self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()

"""The ush-runall skill documents (plan 098, M3): the rules of SKILL.md, the sections
and the elevated-shell sentence of references/report-format.md, and ush-runall in the
shared number-word test's ``SKILLS``.

Checks are case-insensitive substrings or patterns within a section or within one item
(a list item or a paragraph, wrapped lines joined), not exact wording.

Assumptions beyond the plan (the plan gives the content, not the English words):

- The rule against passing flags names "flag" and says never/no/not/only.
- The rule on reading the items names the ``h`` items (``h1``, ``h…`` or ``h...``) and
  says they are read in order: "in order", "one at a time", "one by one", "in turn" or
  "before the next".
- The rule against a child's ``--detail`` names ``--detail`` (not only
  ``--detail-file``), "child" and never/no/not/only.
- The section of contradicting findings has a heading with "contradict" or "conflict".
- The "not checked" section heading is "Nie sprawdzono" (the plan's name) or its English
  form "Not checked" (skill documents are in English).
- The elevated-shell sentence is one item naming ``runall.py``, "block", "elevated" or
  "administrator", and "one" or "single".
"""

import importlib
import re
import unittest

from tests.skill_loader import REPO_ROOT, load_script

SKILL_DIR = REPO_ROOT / "skills" / "ush-runall"
SKILL_MD = SKILL_DIR / "SKILL.md"
REPORT_FORMAT = SKILL_DIR / "references" / "report-format.md"

NEGATION = re.compile(r"\b(never|no|not|only|nothing)\b", re.IGNORECASE)
H_ITEMS = re.compile(r"(?<![0-9A-Za-z_])h(\d+|…|\.\.\.)", re.IGNORECASE)
IN_ORDER = ("in order", "one at a time", "one by one", "in turn", "before the next")
CHILD_DETAIL = re.compile(r"--detail(?!-file)")


def _read(path):
    if not path.is_file():
        raise AssertionError(f"missing: {path}")
    return path.read_text(encoding="utf-8")


def _section(text, heading):
    """The text under ``## <heading>`` up to the next heading of level 1 or 2."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^##\s+{re.escape(heading)}\s*$", line.strip(), re.IGNORECASE):
            start = index + 1
            break
    if start is None:
        raise AssertionError(f"no '## {heading}' section")
    body = []
    for line in lines[start:]:
        if re.match(r"^#{1,2}\s", line):
            break
        body.append(line)
    return "\n".join(body)


def _items(text):
    """List items and paragraphs, each with its wrapped lines joined."""
    items, current = [], []
    for line in text.splitlines():
        stripped = line.strip()
        starts_item = re.match(r"^([-*+]|\d+[.)])\s", stripped)
        if not stripped or starts_item or stripped.startswith("#"):
            if current:
                items.append(" ".join(current))
            current = [stripped] if stripped else []
        else:
            current.append(stripped)
    if current:
        items.append(" ".join(current))
    return items


# Plan 004 M2 (loc/inbox/004-plan-1-easy-runall-actionable-answer.md). Assumptions beyond
# the plan, which gives the content, not the English words:
#
# - The layout headings of report-format.md (``##`` or ``###``, numbered or not, outside
#   fenced code) may be in English or Polish: the verdict "Werdykt", "Wniosek" or "Verdict";
#   the recommendations "Recommendations", "Rekomendacje" or "Zalecenia"; the actions
#   "Co możesz zrobić" or "What you can do"; the changes "Changes since the last run" or
#   "Zmiany"; the clean-up "clean-up", "cleanup", "clean up", "Porządki" or "Sprzątanie".
# - A short summary is asked for with "short", "brief" or "krótk".
# - A request to list every change matches "report/list ... every change" or
#   "every change of every child".
# - A forbidden total names "total", "sum" or "add(ing) up" together with a negation.
# - SKILL.md step 5 is the text from the line "5." to the line "6." of "## Steps".

# Plan 055 M2: the summary section of rule 15 of report-style.md replaced the verdict;
# what the verdict tests guarded is now checked in the summary section ("Summary" or
# "Podsumowanie") and, for the memory line, at the start of the details (the run state).
SUMMARY_NAMES = ("Summary", "Podsumowanie")
RUN_STATE_NAMES = ("Run state", "Stan przebiegu")
RECOMMENDATION_NAMES = ("Recommendations", "Rekomendacje", "Zalecenia")
ACTIONS_NAMES = ("Co możesz zrobić", "What you can do")
NOT_CHECKED_NAMES = ("Nie sprawdzono", "Not checked")
CHANGES_NAMES = ("Changes since the last run", "Zmiany")
CLEANUP_NAMES = ("clean-up", "cleanup", "clean up", "Porządki", "Sprzątanie")
FIREWALL_NAMES = ("Firewall rules and listening ports",)

EVERY_CHANGE = re.compile(
    r"\b(report|list)\w*\s+(\w+\s+){0,2}every\s+change\b|\bevery\s+change\s+of\s+every\s+child",
    re.IGNORECASE,
)
TOTAL = re.compile(r"\b(total|sum|summed|add(ed|ing|s)?\s+(\w+\s+){0,2}up)\b", re.IGNORECASE)
GB_FIELD = re.compile(r"(?<![0-9A-Za-z_])gb(?![0-9A-Za-z_])")
PLACE_IN_REPORT = re.compile(r"\b(copy|copies|put|puts|place|places|insert|inserts|include|"
                             r"includes|paste|pastes|write|writes)\b", re.IGNORECASE)


# Plan 006 M2 (loc/inbox/006-plan-3-medium-repair-plans.md). Assumptions beyond the plan:
#
# - The step of SKILL.md "## Steps" that writes the repair plan is the numbered step that
#   names ``repair-plan.md``; that same step names ``check_repair_plan.py``, "after" and
#   "decide"/"decision".
# - A repair plan is named as "repair plan", "repair-plan" or "repair_plan".
# - An open repair plan in the verdict is one item of the verdict section naming
#   ``plans/`` (not only ``plans/done/``), "open" and "repair plan".

DECISION = re.compile(r"\bdecid|\bdecision", re.IGNORECASE)
REPAIR_PLAN = re.compile(r"\brepair[-_ ]plan", re.IGNORECASE)
OPEN_PLANS_DIR = re.compile(r"plans/(?!done)")


def _steps(steps):
    """The text of every numbered step of ``steps``, in order."""
    found = []
    for number in range(1, 30):
        try:
            found.append(_step(steps, number))
        except AssertionError:
            continue
    return found


def _headings(text):
    """``(line index, level, title)`` of every Markdown heading outside fenced code."""
    found, in_fence = [], False
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match and not in_fence:
            found.append((index, len(match.group(1)), match.group(2).strip()))
    return found


def _find_heading(text, names):
    """The first heading outside fenced code whose title contains one of ``names``."""
    for heading in _headings(text):
        if any(name.lower() in heading[2].lower() for name in names):
            return heading
    raise AssertionError(f"no heading with any of {names}")


def _layout_section(text, *names):
    """The text under the first heading with one of ``names``, up to the next heading of
    the same or a higher level (outside fenced code)."""
    index, level, _ = _find_heading(text, names)
    end = None
    for other_index, other_level, _ in _headings(text):
        if other_index > index and other_level <= level:
            end = other_index
            break
    lines = text.splitlines()
    return "\n".join(lines[index + 1:end])


def _step(steps, number):
    """The text of numbered step ``number`` up to the next numbered step."""
    lines = steps.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^{number}[.)]\s", line):
            start = index
            break
    if start is None:
        raise AssertionError(f"no step {number}")
    body = [lines[start]]
    for line in lines[start + 1:]:
        if re.match(r"^\d+[.)]\s", line):
            break
        body.append(line)
    return "\n".join(body)


def _sentences(text):
    joined = " ".join(text.split())
    return [part for part in re.split(r"(?<=[.;:])\s+", joined) if part]


class TestDocs(unittest.TestCase):
    def test_rules_and_sections(self):
        skill = _read(SKILL_MD)
        rules = _section(skill, "Rules")
        rule_items = _items(rules)

        with self.subTest("Rules: no flag is passed on to a child"):
            found = [item for item in rule_items
                     if "flag" in item.lower() and NEGATION.search(item)]
            self.assertTrue(found, f"no rule forbidding flags:\n{rules}")

        with self.subTest("Rules: the h items are read one after another"):
            found = [item for item in rule_items
                     if H_ITEMS.search(item)
                     and any(phrase in item.lower() for phrase in IN_ORDER)]
            self.assertTrue(found, f"no rule on reading the h items in order:\n{rules}")

        with self.subTest("Rules: no --detail of a child script"):
            found = [item for item in rule_items
                     if CHILD_DETAIL.search(item) and "child" in item.lower()
                     and NEGATION.search(item)]
            self.assertTrue(found, f"no rule forbidding a child's --detail:\n{rules}")

        report_format = _read(REPORT_FORMAT)
        headings = [line for line in report_format.splitlines() if re.match(r"^#+\s", line)]

        def has_heading(*names):
            return any(name.lower() in heading.lower()
                       for heading in headings for name in names)

        for label, names in (
            ("Links between skills", ("Links between skills",)),
            ("Firewall rules and listening ports", ("Firewall rules and listening ports",)),
            ("contradicting findings", ("contradict", "conflict")),
            ("Nie sprawdzono", ("Nie sprawdzono", "Not checked")),
        ):
            with self.subTest(f"report-format has a section {label!r}"):
                self.assertTrue(has_heading(*names), f"headings: {headings}")

        with self.subTest("report-format: one block for an elevated shell with runall.py"):
            found = [item for item in _items(report_format)
                     if "runall.py" in item and "block" in item.lower()
                     and re.search(r"elevated|administrator", item, re.IGNORECASE)
                     and re.search(r"\b(one|single)\b", item, re.IGNORECASE)]
            self.assertTrue(found, "no item on one elevated-shell block with runall.py")

        with self.subTest("ush-runall is in SKILLS of the number-word test"):
            words = importlib.import_module("tests.ush-common.test_check_report_words")
            self.assertIn("ush-runall", words.SKILLS)

    def test_summary_and_actions_sections(self):
        report_format = _read(REPORT_FORMAT)
        headings = _headings(report_format)

        summary = _find_heading(report_format, SUMMARY_NAMES)
        recommendations = _find_heading(report_format, RECOMMENDATION_NAMES)
        with self.subTest("the summary section comes before the recommendations"):
            self.assertLess(summary[0], recommendations[0],
                            f"summary {summary[2]!r} after {recommendations[2]!r}")

        not_checked = _find_heading(report_format, NOT_CHECKED_NAMES)
        with self.subTest("'Co możesz zrobić' is the section directly before 'Nie sprawdzono'"):
            before = [heading for heading in headings
                      if heading[0] < not_checked[0] and heading[1] <= not_checked[1]]
            self.assertTrue(before, "no section before 'Nie sprawdzono'")
            title = before[-1][2]
            self.assertTrue(any(name.lower() in title.lower() for name in ACTIONS_NAMES),
                            f"the section before {not_checked[2]!r} is {title!r}")

    def test_changes_short_summary(self):
        report_format = _read(REPORT_FORMAT)
        changes = _layout_section(report_format, *CHANGES_NAMES)

        with self.subTest("the changes section asks for a short summary"):
            self.assertRegex(changes, re.compile(r"\bshort\b|\bbrief\b|krótk", re.IGNORECASE))

        with self.subTest("the changes section names the runall detail file for the full lists"):
            self.assertIn("runall", changes)
            found = [item for item in _items(changes)
                     if re.search(r"detail[ _]file", item, re.IGNORECASE)
                     and re.search(r"\bfull\b", item, re.IGNORECASE)]
            self.assertTrue(found, f"no item on the detail file for the full lists:\n{changes}")

        # Plan 017 M2 (012 #2): the detail file is named in words, as `detail_file` in the
        # work folder, never by its file name (unbacked digits) or path (the account name).
        with self.subTest("the detail file is named in words, never by file name or path"):
            in_words = [item for item in _items(changes)
                        if "`detail_file`" in item and re.search(r"\bwork\b", item)
                        and re.search(r"\b(never|not)\b[^.]*\bfile name\b[^.]*\bpath\b",
                                      item, re.IGNORECASE)]
            self.assertTrue(in_words, f"no item naming `detail_file` in words:\n{changes}")
            # M2 review round 1: `<data dir>` failed the report check, which bans a `<`
            # before a letter even in inline code; the sentence writes `&lt;data dir>`.
            for item in in_words:
                for sentence in _sentences(item):
                    if "`detail_file`" in sentence:
                        self.assertNotRegex(sentence, re.compile(r"<[A-Za-z?!/]"), sentence)

        for label, path in (("SKILL.md", SKILL_MD), ("report-format.md", REPORT_FORMAT)):
            with self.subTest(f"{label} does not ask to list every change of every child"):
                text = " ".join(_read(path).split())
                match = EVERY_CHANGE.search(text)
                self.assertIsNone(match, f"{label}: {match.group(0) if match else ''!r}")

    def test_recommendation_named_by_source(self):
        # Plan 017 M2 (012 #1): a recommendation has no id of the report's own; the summary
        # (once the verdict) and "Co możesz zrobić" name it by its main source,
        # `ush-<skill> <id>`.
        report_format = _read(REPORT_FORMAT)
        for names in (SUMMARY_NAMES, ACTIONS_NAMES):
            section = " ".join(_layout_section(report_format, *names).split())
            with self.subTest(section=names[0]):
                self.assertIn("`ush-<skill> <id>`", section)
                self.assertRegex(section, re.compile(r"main source", re.IGNORECASE))
                self.assertNotRegex(section, re.compile(r"\bits id and\b|recommendation's id",
                                                        re.IGNORECASE))

    def test_old_dumps_rule(self):
        # Plan 017 M2 (012 #4): dump files older than the events window get one line with
        # the child's count, in the recommendations section; none of them, no line.
        section = _layout_section(_read(REPORT_FORMAT), *RECOMMENDATION_NAMES)
        text = " ".join(section.split())
        self.assertIn("older_than_window", text)
        for label, pattern in (
                ("the line is left out at 0", r"`0`[^.]*left out|left out[^.]*`0`"),
                ("null goes under Not checked", r"`null`[^.]*Not checked"),
                ("the stop code needs administrator", r"stop code[^.]*needs administrator"),
                ("a recommendation of weight low", r"weight `low`"),
                ("named by its first old dump file", r"`ush-events d<n>`")):
            with self.subTest(label):
                self.assertRegex(text, re.compile(pattern, re.IGNORECASE))

    def test_collapsed_changes_line(self):
        # Plan 010 M1: ush-inventory collapses the ms-resource firewall changes into one
        # counted entry per change type; runall gives it in the child's wording.
        changes = _layout_section(_read(REPORT_FORMAT), *CHANGES_NAMES)
        text = " ".join(changes.split())
        self.assertIn("<N> zmian `ms-resource:` zwiniętych w jedną linię", text)
        self.assertNotIn("as the child lists them, with no count", text)

    def test_cleanup_section(self):
        report_format = _read(REPORT_FORMAT)
        cleanup = _layout_section(report_format, *CLEANUP_NAMES)

        with self.subTest("the clean-up section takes the cleanup items of h6"):
            self.assertIn("cleanup", cleanup)
            self.assertIn("h6", cleanup)

        with self.subTest("the clean-up section gives gb and gb_older per item"):
            self.assertRegex(cleanup, GB_FIELD)
            self.assertIn("gb_older", cleanup)

        with self.subTest("the clean-up section forbids a total"):
            found = [item for item in _items(cleanup)
                     if TOTAL.search(item) and NEGATION.search(item)]
            self.assertTrue(found, f"no item forbidding a total or sum:\n{cleanup}")

    def test_blocks_after_decision(self):
        # Plan 006 M2 (loc/inbox/006-plan-3-medium-repair-plans.md) replaced the plan-004
        # "block in the chat" with a repair plan: the decision still comes first.
        skill = _read(SKILL_MD)
        step = _step(_section(skill, "Steps"), 5)
        flat = " ".join(step.split())

        with self.subTest("step 5 gives the block after the user decides"):
            self.assertRegex(flat, re.compile(r"\bafter\b", re.IGNORECASE))
            self.assertRegex(flat, DECISION)

        with self.subTest("step 5 puts the blocks into a repair plan"):
            self.assertRegex(flat, REPAIR_PLAN)

        with self.subTest("step 5 does not put a child's block into the report"):
            wrong = [sentence for sentence in _sentences(step)
                     if re.search(r"\breport\b", sentence, re.IGNORECASE)
                     and PLACE_IN_REPORT.search(sentence)
                     and not NEGATION.search(sentence)]
            self.assertFalse(wrong, f"step 5 puts a block into the report: {wrong}")

        with self.subTest("step 5: a --block printer, else the child's SKILL.md template"):
            self.assertIn("--block", flat)
            self.assertRegex(flat, re.compile(r"\btemplate\b", re.IGNORECASE))

    def test_repair_plan_after_decision(self):
        # K1: after the user decides, the model writes a repair plan per repair-plan.md
        # and checks it with check_repair_plan.py.
        steps = _section(_read(SKILL_MD), "Steps")
        found = [" ".join(step.split()) for step in _steps(steps) if "repair-plan.md" in step]
        self.assertTrue(found, f"no step of '## Steps' names repair-plan.md:\n{steps}")
        step = found[0]

        with self.subTest("the repair-plan step names check_repair_plan.py"):
            self.assertIn("check_repair_plan.py", step)

        with self.subTest("the repair-plan step comes after the user decides"):
            self.assertRegex(step, re.compile(r"\bafter\b", re.IGNORECASE))
            self.assertRegex(step, DECISION)

        with self.subTest("the repair-plan step says the model writes a repair plan"):
            self.assertRegex(step, re.compile(r"\bwrit(e|es|ing)\b", re.IGNORECASE))
            self.assertRegex(step, REPAIR_PLAN)

    def test_open_repair_plans_in_summary(self):
        # K3: the runall report format names the open repair plans of <data dir>/plans/
        # in the summary section (once the verdict).
        summary = _layout_section(_read(REPORT_FORMAT), *SUMMARY_NAMES)
        found = [item for item in _items(summary)
                 if OPEN_PLANS_DIR.search(item)
                 and re.search(r"\bopen\b", item, re.IGNORECASE)
                 and REPAIR_PLAN.search(item)]
        self.assertTrue(found, f"no summary item naming open repair plans in plans/:\n{summary}")

    def test_open_plans_fenced_and_unlisted(self):
        # Review round 1, fix 5: the open plans' file names go into a fenced code block
        # (check_report checks the digits of inline code); a plans/ that cannot be
        # listed is said in the summary section (once the verdict), with the reason under
        # "Not checked".
        summary = _layout_section(_read(REPORT_FORMAT), *SUMMARY_NAMES)
        items = _items(summary)
        plans = [item for item in items
                 if OPEN_PLANS_DIR.search(item) and REPAIR_PLAN.search(item)
                 and re.search(r"\bopen\b", item, re.IGNORECASE)]
        self.assertTrue(plans, summary)

        with self.subTest("the file names go into a fenced code block, not inline code"):
            self.assertTrue(any(re.search(r"\bfenced code block\b", item)
                                and re.search(r"\bnever in inline code\b", item)
                                for item in plans), plans)
            self.assertFalse([item for item in plans
                              if re.search(r"by file name in inline code", item)], plans)

        with self.subTest("plans/ that cannot be listed: said, reason under Not checked"):
            found = [item for item in items
                     if OPEN_PLANS_DIR.search(item) and "cannot be listed" in item
                     and any(name in item for name in NOT_CHECKED_NAMES)
                     and re.search(r"\bnever\b[^.]*\bno open plans\b", item)]
            self.assertTrue(found, summary)

    def test_block_printers_split(self):
        # Review round 1, fixes 1 and 2: step 5 says how each printer's output splits
        # into run and undo blocks, in the printers' own words.
        step = " ".join(_step(_section(_read(SKILL_MD), "Steps"), 5).split())
        inventory = load_script("ush-inventory", "inventory")
        settings = load_script("ush-settings", "settings")

        with self.subTest("ush-inventory: split at the printer's rollback line"):
            note = inventory.ROLLBACK_NOTE
            self.assertIn(f"Split each entry at its `{note}` line", step)
            self.assertIn("<!-- ush:block ush-inventory <id> -->", step)
            self.assertIn("<!-- ush:undo ush-inventory <id> -->`, the same id", step)
            self.assertIn("put the entry's shell on a line above its undo marker", step)

        with self.subTest("ush-settings: one fence per printed part"):
            for header in (settings.HEADER_NORMAL, settings.HEADER_ELEVATED,
                           settings.HEADER_ROLLBACK_NORMAL, settings.HEADER_ROLLBACK_ELEVATED):
                prefix = header.split(";")[0].split(" (Run as")[0].split(" (the account")[0]
                self.assertIn(f"`{prefix}`", step)
            self.assertIn("<!-- ush:block ush-settings normal -->", step)
            self.assertIn("<!-- ush:block ush-settings elevated -->", step)

        with self.subTest("ush-files: no rollback block, a noundo marker instead"):
            self.assertIn("<!-- ush:block ush-files <id> -->", step)
            self.assertIn("<!-- ush:noundo ush-files <id> -->", step)

    def test_summary_replaces_verdict(self):
        # Plan 055 M2 K5 (loc/inbox/055-plan-1-hard-report-summary.md): the summary
        # section replaces the "Werdykt" section. Assumptions beyond the plan:
        # - the memory line is the item naming `used_percent` and `available_gb` of the
        #   processes summary; "in the details" means that item names "details";
        # - part 3 is named "part 3" or by its label "Otwarte plany naprawcze";
        # - the broken-decision recommendation is the item naming `ush-runall j<n>`,
        #   "broken" and its evidence ("evidence" or "Dowód").
        report_format = _read(REPORT_FORMAT)
        items = _items(report_format)

        with self.subTest("no Werdykt section"):
            titles = [title for _, _, title in _headings(report_format)]
            bad = [title for title in titles
                   if re.search(r"\bWerdykt\b|\bVerdict\b", title, re.IGNORECASE)]
            self.assertEqual(bad, [], f"headings: {titles}")

        with self.subTest("the memory line stands in the details"):
            found = [item for item in items
                     if "used_percent" in item and "available_gb" in item
                     and re.search(r"\bdetails\b", item, re.IGNORECASE)]
            self.assertTrue(found, "no item puts the memory line into the details")

        with self.subTest("the open repair plans go into part 3"):
            found = [item for item in items
                     if OPEN_PLANS_DIR.search(item) and REPAIR_PLAN.search(item)
                     and re.search(r"\bopen\b", item, re.IGNORECASE)
                     and re.search(r"\bpart 3\b|Otwarte plany naprawcze", item)]
            self.assertTrue(found, "no item puts the open repair plans into part 3")

        with self.subTest("the broken-decision evidence starts with ush-runall j<n>"):
            found = [item for item in items
                     if "`ush-runall j<n>`" in item
                     and re.search(r"\bbroken\b", item, re.IGNORECASE)
                     and re.search(r"\bevidence\b|Dowód", item, re.IGNORECASE)
                     and re.search(r"\bstarts? with\b|\bfirst\b", item, re.IGNORECASE)]
            self.assertTrue(found, "no item starts the broken-decision evidence with "
                                   "`ush-runall j<n>`")

        with self.subTest("step 8 no longer says part one of rule 4"):
            step = " ".join(_step(_section(_read(SKILL_MD), "Steps"), 8).split())
            self.assertNotRegex(step, re.compile(r"part one of rule 4", re.IGNORECASE))

    def test_memory_line_and_firewall_counts(self):
        report_format = _read(REPORT_FORMAT)
        summary = _layout_section(report_format, *SUMMARY_NAMES)
        run_state = _layout_section(report_format, *RUN_STATE_NAMES)

        with self.subTest("the details ask for the memory line of the processes summary"):
            found = [item for item in _items(run_state)
                     if "used_percent" in item and "available_gb" in item
                     and "processes" in item.lower()]
            self.assertTrue(found, f"no memory line from ush-processes:\n{run_state}")

        with self.subTest("the summary gives no count of its own"):
            found = [item for item in _items(summary)
                     if re.search(r"\bcount", item, re.IGNORECASE) and NEGATION.search(item)]
            self.assertTrue(found, f"no item saying the summary gives no count:\n{summary}")

        firewall = _layout_section(report_format, *FIREWALL_NAMES)
        with self.subTest("the firewall section explains why the two port counts differ"):
            found = [item for item in _items(firewall)
                     if "ports_without_path" in item and "System" in item
                     and any(name.lower() in item.lower() for name in NOT_CHECKED_NAMES)
                     and re.search(r"\bdiffer|\bnot the same\b", item, re.IGNORECASE)]
            self.assertTrue(found, f"no item on ports_without_path vs 'Nie sprawdzono':\n{firewall}")


if __name__ == "__main__":
    unittest.main()

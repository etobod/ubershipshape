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

from tests.skill_loader import REPO_ROOT

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


if __name__ == "__main__":
    unittest.main()

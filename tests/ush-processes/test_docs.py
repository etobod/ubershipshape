"""The ush-processes report-format document (plan 004, M3): the Dashboard asks for a
memory assessment judged by the model, and the TCP ports section starts with a
conclusion and puts the remaining ports on a compact line.

Checks are case-insensitive substrings or patterns within one section of the
layout (wrapped lines joined), not exact wording.

Assumptions beyond the plan (the plan gives the content, not the English words):

- A layout section starts at a line that is a top-level numbered item (``2.``) or a
  heading whose text contains its name ("Dashboard", "TCP ports") and ends at the next
  top-level numbered item or the next heading.
- A memory assessment is "memory" together with "assess", "judg", "evaluat", "verdict"
  or "ocen" in the same sentence.
- "The model judges" is a sentence with "model" and "judg"/"decid"/"assess"; "the
  script sets no threshold" is a sentence with "threshold" and a negation.
- A threshold phrase is a word like above/below/over/under/exceeds/more than/less than/
  threshold/powyżej/poniżej/ponad/próg within three words of a number with % or GB, or
  a number with % or GB followed within three words by such a word, or a comparison
  sign (``>``, ``<``, ``≥``, ``≤``) before such a number.
- Per-port detail in section 5 is the first of ``local_port``, ``local_address``,
  ``scope`` or ``group_in_summary``.
"""

import re
import unittest

from tests.skill_loader import REPO_ROOT

REPORT_FORMAT = REPO_ROOT / "skills" / "ush-processes" / "references" / "report-format.md"

MARKS = ("✅", "\U0001F50D", "\U0001F527")  # ✅ 🔍 🔧
NEGATION = re.compile(r"\b(never|no|not|none|without|nie|bez)\b", re.IGNORECASE)
ASSESSMENT = re.compile(r"assess|judg|evaluat|verdict|ocen", re.IGNORECASE)
MODEL_JUDGES = re.compile(r"judg|decid|assess", re.IGNORECASE)

THRESHOLD_WORD = (r"(above|below|over|under|exceed\w*|more\s+than|less\s+than|"
                  r"at\s+least|at\s+most|threshold\w*|powyżej|poniżej|ponad|próg\w*|progu)")
AMOUNT = r"\d+(?:[.,]\d+)?\s*(?:%|gb\b)"
THRESHOLD_PHRASE = re.compile(
    rf"\b{THRESHOLD_WORD}\b\W*(?:\w+\W+){{0,3}}?{AMOUNT}"
    rf"|{AMOUNT}\W*(?:\w+\W+){{0,3}}?{THRESHOLD_WORD}\b"
    rf"|(?:[<>≥≤]|&lt;|&gt;)=?\s*{AMOUNT}",
    re.IGNORECASE,
)

PORT_DETAIL_FIELDS = ("local_port", "local_address", "scope", "group_in_summary")
COMPACT_LINE = re.compile(r"\bid\s+name\s*\(\s*count\s*\)|\bone\s+line\b|\bcompact\b",
                          re.IGNORECASE)
ONE_BULLET_PER = re.compile(r"\bone\s+bullet\s+per\b", re.IGNORECASE)


def _read(path):
    if not path.is_file():
        raise AssertionError(f"missing: {path}")
    return path.read_text(encoding="utf-8")


def _layout_item(text, name):
    """The text of the top-level numbered item or heading whose first line names
    ``name``, up to the next top-level numbered item or heading."""
    start_pattern = re.compile(
        rf"^(\d+[.)]|#{{1,6}})\s+.*\b{re.escape(name)}\b", re.IGNORECASE)
    boundary = re.compile(r"^(\d+[.)]\s|#{1,6}\s)")
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if start_pattern.match(line):
            start = index
            break
    if start is None:
        raise AssertionError(f"no layout item or heading named {name!r}")
    body = [lines[start]]
    for line in lines[start + 1:]:
        if boundary.match(line):
            break
        body.append(line)
    return "\n".join(body)


def _flat(text):
    return " ".join(text.split())


def _sentences(text):
    return [part for part in re.split(r"(?<=[.;:!?])\s+|\n\s*\n", _flat(text)) if part]


class TestDocs(unittest.TestCase):
    def test_memory_assessment_row(self):
        dashboard = _layout_item(_read(REPORT_FORMAT), "Dashboard")
        flat = _flat(dashboard)

        with self.subTest("the Dashboard asks for an assessment of memory"):
            found = [sentence for sentence in _sentences(dashboard)
                     if re.search(r"memory|pamię", sentence, re.IGNORECASE)
                     and ASSESSMENT.search(sentence)]
            self.assertTrue(found, f"no memory assessment in the Dashboard:\n{dashboard}")

        for mark in MARKS:
            with self.subTest(f"the Dashboard names the mark {mark}"):
                self.assertIn(mark, flat)

        with self.subTest("the model judges, or the script sets no threshold"):
            found = [sentence for sentence in _sentences(dashboard)
                     if (re.search(r"\bmodel\b", sentence, re.IGNORECASE)
                         and MODEL_JUDGES.search(sentence))
                     or (re.search(r"threshold|próg|progu", sentence, re.IGNORECASE)
                         and NEGATION.search(sentence))]
            self.assertTrue(found, f"no sentence on who judges memory:\n{dashboard}")

        with self.subTest("the Dashboard gives no threshold number"):
            match = THRESHOLD_PHRASE.search(flat)
            self.assertIsNone(match, f"threshold phrase: {match.group(0) if match else ''!r}")

    def test_ports_conclusion_first(self):
        ports = _layout_item(_read(REPORT_FORMAT), "TCP ports")
        flat = _flat(ports)
        lower = flat.lower()

        with self.subTest("section 5 asks for a conclusion before any per-port detail"):
            conclusion = re.search(r"conclusion|wniosek|wnioski", flat, re.IGNORECASE)
            self.assertIsNotNone(conclusion, f"no conclusion in section 5:\n{ports}")
            details = [lower.find(field) for field in PORT_DETAIL_FIELDS
                       if field in lower]
            if details:
                self.assertLess(conclusion.start(), min(details),
                                f"the conclusion comes after per-port detail:\n{ports}")

        with self.subTest("section 5 puts the remaining ports on a compact line"):
            self.assertRegex(flat, COMPACT_LINE)

        with self.subTest("section 5 no longer asks for one bullet per port"):
            match = ONE_BULLET_PER.search(flat)
            self.assertIsNone(match, f"section 5 still says {match.group(0) if match else ''!r}")


if __name__ == "__main__":
    unittest.main()

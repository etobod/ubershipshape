"""The wording of the manager states not_present and not_read in the ush-packages and
ush-runall documents (plan 066, M2, K7).

Checks are case-insensitive substrings or patterns within one item (a list item or a
paragraph with its wrapped lines joined, or one table row), not exact wording.

Assumptions beyond the plan (the plan gives the content, not the English words):

- The state is named as ``not_present`` / ``not_read`` (with or without backticks).
- "names not_present as 'not present'": one item names ``not_present`` and the words
  "not present".
- "with the Packages cell '—'": in ush-packages' report-format.md one item names "not
  present" and the dash "—". SKILL.md must stay ASCII (test_repo_rules), so it names
  the dash as "em dash" and is not checked for the character (plan 066 M2 deviation).
- "names not_read as 'not read yet'": one item names ``not_read`` and "not read yet".
- "the same rule for h8": in the ush-runall documents the item that names
  ``not_present`` and "not present" also names ``h8``. The dash "—" is not required
  there, since the runall report has no Packages cell of its own.
"""

import re
import unittest

from tests.skill_loader import REPO_ROOT

SKILLS = REPO_ROOT / "skills"
PACKAGES_DOCS = (
    SKILLS / "ush-packages" / "references" / "report-format.md",
    SKILLS / "ush-packages" / "SKILL.md",
)
RUNALL_DOCS = (
    SKILLS / "ush-runall" / "references" / "report-format.md",
    SKILLS / "ush-runall" / "SKILL.md",
)

NOT_PRESENT_STATE = re.compile(r"(?<![\w])not_present(?![\w])")
NOT_READ_STATE = re.compile(r"(?<![\w])not_read(?![\w])")
NOT_PRESENT_WORDS = re.compile(r"\bnot present\b", re.IGNORECASE)
NOT_READ_WORDS = re.compile(r"\bnot read yet\b", re.IGNORECASE)
H8 = re.compile(r"(?<![0-9A-Za-z_])h8(?![0-9])")
DASH = "—"


def _read(path):
    if not path.is_file():
        raise AssertionError(f"missing: {path}")
    return path.read_text(encoding="utf-8")


def _items(text):
    """List items and paragraphs with their wrapped lines joined; each table row alone."""
    items, current = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            if current:
                items.append(" ".join(current))
                current = []
            items.append(stripped)
            continue
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


class TestNotPresentDocs(unittest.TestCase):
    def test_not_present_wording(self):
        for path in PACKAGES_DOCS + RUNALL_DOCS:
            rel = path.relative_to(REPO_ROOT).as_posix()
            items = _items(_read(path))

            named = [item for item in items
                     if NOT_PRESENT_STATE.search(item) and NOT_PRESENT_WORDS.search(item)]
            with self.subTest(doc=rel, check="not_present is 'not present'"):
                self.assertTrue(named, f"{rel}: no item names not_present as 'not present'")

            with self.subTest(doc=rel, check="not_read is 'not read yet'"):
                found = [item for item in items
                         if NOT_READ_STATE.search(item) and NOT_READ_WORDS.search(item)]
                self.assertTrue(found, f"{rel}: no item names not_read as 'not read yet'")

            if path == PACKAGES_DOCS[0]:
                with self.subTest(doc=rel, check="the Packages cell of not present is '—'"):
                    found = [item for item in items
                             if NOT_PRESENT_WORDS.search(item) and DASH in item]
                    self.assertTrue(found, f"{rel}: no item gives '{DASH}' for 'not present'")
            elif path in RUNALL_DOCS:
                with self.subTest(doc=rel, check="the same rule for h8"):
                    found = [item for item in named if H8.search(item)]
                    self.assertTrue(found, f"{rel}: no item names h8 with not_present as "
                                           f"'not present'")

    # Plan 073, M2, K7: npm follows the shared not_present rule; a missing node_modules
    # is no longer npm `empty` worded as "npm not present".
    def test_npm_follows_not_present(self):
        for path in PACKAGES_DOCS + RUNALL_DOCS:
            rel = path.relative_to(REPO_ROOT).as_posix()
            items = _items(_read(path))

            with self.subTest(doc=rel, check="no 'npm not present' wording"):
                found = [item for item in items if NPM_NOT_PRESENT_WORDS.search(item)]
                self.assertEqual(found, [], f"{rel}: npm still named 'npm not present'")

            with self.subTest(doc=rel, check="no npm empty named 'not present'"):
                found = [item for item in items
                         if NPM.search(item) and EMPTY_AS_NOT_PRESENT.search(item)]
                self.assertEqual(found, [], f"{rel}: npm `empty` named 'not present'")

            with self.subTest(doc=rel, check="not_present is 'not present'"):
                found = [item for item in items
                         if NOT_PRESENT_STATE.search(item) and NOT_PRESENT_WORDS.search(item)]
                self.assertTrue(found, f"{rel}: no item names not_present as 'not present'")

            with self.subTest(doc=rel, check="not_read is 'not read yet'"):
                found = [item for item in items
                         if NOT_READ_STATE.search(item) and NOT_READ_WORDS.search(item)]
                self.assertTrue(found, f"{rel}: no item names not_read as 'not read yet'")


NPM = re.compile(r"(?<![\w-])npm(?![\w-])", re.IGNORECASE)
NPM_NOT_PRESENT_WORDS = re.compile(r"\bnpm\W{0,3}not present\b", re.IGNORECASE)
# `empty` given the words "not present" (or the reverse) in one clause, e.g.
# "`empty` is 'not present'", "`empty` (not present)", "not present (`empty`)".
EMPTY_AS_NOT_PRESENT = re.compile(
    r"`empty`\W{0,4}(?:is|means|=|:|->|→|shown as|reads)?\W{0,4}not present\b"
    r"|\bnot present\W{0,4}\(`?empty`?\)",
    re.IGNORECASE,
)


UPDATE_DOCS = (
    SKILLS / "ush-packages" / "SKILL.md",
    SKILLS / "ush-packages" / "references" / "summary-contract.md",
    SKILLS / "ush-packages" / "references" / "report-format.md",
    SKILLS / "ush-packages" / "scripts" / "packages.py",
)
STALE = re.compile(r"(does not exist yet|exists yet|lookup yet|needs an ush-advice lookup)",
                   re.IGNORECASE)
POINTER = re.compile(r"checked for updates only in an ush-advice run with findings",
                     re.IGNORECASE)


class TestUpdateCheckDocs(unittest.TestCase):
    """Plan 075 M2 K10: the ush-packages docs point to the ush-advice lookup."""

    def test_points_to_advice_findings(self):
        for path in UPDATE_DOCS:
            with self.subTest(path=path.name):
                text = " ".join(path.read_text(encoding="utf-8").split())
                self.assertIsNone(STALE.search(text), f"{path}: stale 'no lookup yet' text")
                self.assertRegex(text, POINTER)


if __name__ == "__main__":
    unittest.main()

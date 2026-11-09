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


if __name__ == "__main__":
    unittest.main()

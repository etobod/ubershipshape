"""Repository-wide rules for the skills tree (plain unittest, no tooling)."""

import json
import unittest

from tests.skill_loader import REPO_ROOT

SKILLS = REPO_ROOT / "skills"

# The only non-ASCII characters allowed, and only in references/*.md:
# the report legend (wrench, magnifier, check mark, cross mark).
LEGEND = {"\U0001F527", "\U0001F50D", "✅", "❌"}


def _keys(data):
    """Yield every object key in parsed JSON, at any depth."""
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield from item.keys()
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


class TestRepoRules(unittest.TestCase):
    def test_skills_ascii(self):
        plain = (
            set(SKILLS.glob("**/*.py"))
            | set(SKILLS.glob("**/*.json"))
            | set(SKILLS.glob("**/SKILL.md"))
        )
        references = set(SKILLS.glob("**/references/*.md"))
        self.assertTrue(plain and references, f"no skill files found under {SKILLS}")

        for path in sorted(plain | references):
            allowed = LEGEND if path in references and path not in plain else set()
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                bad = sorted({c for c in line if ord(c) > 127 and c not in allowed})
                self.assertFalse(
                    bad,
                    f"{path.relative_to(REPO_ROOT)}:{number}: non-ASCII "
                    f"{', '.join(f'U+{ord(c):04X}' for c in bad)}",
                )

        for path in sorted(SKILLS.glob("**/data/*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in _keys(data):
                self.assertTrue(
                    key.isascii(), f"{path.relative_to(REPO_ROOT)}: non-ASCII key {key!r}"
                )

    def test_noise_entries_shape(self):
        path = SKILLS / "ush-events" / "data" / "noise.json"
        entries = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(entries, list, "noise.json must be a plain list")
        for index, entry in enumerate(entries):
            with self.subTest(entry=index):
                self.assertIsInstance(entry, dict)
                # Only the general fields; local evidence stays out of the repo.
                self.assertEqual(set(entry), {"provider", "event_id", "reason"})
                for field in ("provider", "reason"):
                    self.assertIsInstance(entry[field], str)
                    self.assertTrue(entry[field].strip(), f"empty {field}")
                self.assertIs(type(entry["event_id"]), int, "event_id must be an int")


if __name__ == "__main__":
    unittest.main()

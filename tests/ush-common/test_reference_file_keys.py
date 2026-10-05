"""Shared report check: digits in baseline.reference_file back no number (invented data only)."""

import re
import unittest

from tests.skill_loader import REPO_ROOT, load_script

SKILLS = ("ush-health", "ush-inventory", "ush-settings", "ush-files")
CONTRACT = REPO_ROOT / "skills" / "ush-common" / "references" / "summary-contract.md"


def _reference_file(skill):
    """An invented history copy name: <skill>.2026-09-23.json."""
    return f"{skill}.2026-09-23.json"


class TestReferenceFileKeys(unittest.TestCase):
    """Tests K3-K5 run against the real report profiles of four skills."""

    @classmethod
    def setUpClass(cls):
        cls.check = load_script("ush-common", "check_report")

    def numbers(self, data, skill):
        # Skip keys come from the skill's own profile, never from a list here.
        profile = self.check.load_profile(skill)
        return {item[-1] for item in self.check.json_values(data, profile.skip_keys)}

    def test_reference_file_backs_no_number(self):
        for skill in SKILLS:
            with self.subTest(skill):
                data = {"baseline": {"reference_file": _reference_file(skill)}}
                found = self.numbers(data, skill)
                for number in (23, 9, 2026):
                    self.assertNotIn(number, found,
                                     f"{skill}: {number} taken from reference_file; got {found}")

    def test_other_baseline_numbers_still_count(self):
        for skill in SKILLS:
            with self.subTest(skill):
                data = {"baseline": {"reference_file": _reference_file(skill), "age_days": 7}}
                found = self.numbers(data, skill)
                self.assertIn(7, found, f"{skill}: age_days 7 missing; got {found}")

    def test_contract_names_reference_file(self):
        text = CONTRACT.read_text(encoding="utf-8")
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if '"kvpuc"' in p]
        with self.subTest("the ush-health profile example"):
            self.assertEqual(len(paragraphs), 1, paragraphs)
            self.assertIn('"reference_file"', paragraphs[0])
        rows = [line for line in text.splitlines() if line.startswith("| `reference_file` |")]
        with self.subTest("the reference_file row"):
            self.assertEqual(len(rows), 1, rows)
            self.assertIn("path_keys", rows[0])


if __name__ == "__main__":
    unittest.main()

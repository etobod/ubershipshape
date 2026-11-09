"""The accepted-findings steps in the ush-runall documents (plan 067, M1 K5, M2 K10).

Checks are case-insensitive substrings within one paragraph or list item of
``SKILL.md`` (wrapped lines joined), not exact wording.
"""

import re
import unittest

from tests.skill_loader import REPO_ROOT

SKILL_MD = REPO_ROOT / "skills" / "ush-runall" / "SKILL.md"
REPORT_FORMAT = REPO_ROOT / "skills" / "ush-runall" / "references" / "report-format.md"
REPORT_STYLE = REPO_ROOT / "skills" / "ush-common" / "references" / "report-style.md"
SUMMARY_CONTRACT = REPO_ROOT / "skills" / "ush-runall" / "references" / "summary-contract.md"


def items(text):
    """Split a Markdown text into paragraphs and list items, wrapped lines joined."""
    out, current = [], []
    for line in text.splitlines():
        stripped = line.strip()
        starts_item = bool(re.match(r"(?:[-*]|\d+\.)\s", stripped))
        if not stripped or starts_item or stripped.startswith("#"):
            if current:
                out.append(" ".join(current))
            current = [stripped] if stripped else []
        else:
            current.append(stripped)
    if current:
        out.append(" ".join(current))
    return [item.lower() for item in out]


class TestAcceptedDocs(unittest.TestCase):
    def setUp(self):
        self.items = items(SKILL_MD.read_text(encoding="utf-8"))

    def find(self, *words):
        return [item for item in self.items if all(word in item for word in words)]

    def test_skill_step(self):
        self.assertTrue(
            self.find("accepted.py", "--accept", "--detail-file"),
            "SKILL.md names accepted.py --accept with --detail-file",
        )
        self.assertTrue(
            self.find("accepted.py", "--remove", "--detail-file"),
            "SKILL.md names accepted.py --remove with --detail-file",
        )
        for flag in ("--accept", "--remove"):
            word = [
                item
                for item in self.find(flag)
                if re.search(r"user'?s word|user says|user asks", item)
                and re.search(r"\bnever\b|\bonly\b", item)
            ]
            self.assertTrue(word, f"{flag} runs only on the user's word")
        back = [
            item
            for item in self.find("--accept", "evidence", "never", "ush-runall a<n>")
            if re.search(r"`back`|\bback\b item", item)
        ]
        self.assertTrue(
            back, "a back item is accepted again with its evidence, never with ush-runall a<n>"
        )
        self.assertTrue(
            self.find("rollback", "--accept", "--remove", "accepted.py --undo"),
            "both commands give their rollback: accepted.py --undo",
        )
        self.assertTrue(
            self.find("accepted.py", "--undo", "--data-dir"),
            "SKILL.md gives the --undo command",
        )
        self.assertTrue(
            [item for item in self.find("--undo", "only", "user's word")
             if re.search(r"never a manual copy|no manual copy", item)],
            "--undo is the only undo, on the user's word, never a manual copy",
        )
        self.assertFalse(
            [item for item in self.items
             if re.search(r"cop(y|ying) (that|the) file back|removing `?accepted\.json",
                          item)],
            "no manual copy or delete of accepted.json as an undo",
        )
        self.assertTrue(
            self.find("--undo", "accepted.previous.json", "first write", "empty"),
            "the first write keeps an empty previous generation",
        )
        self.assertTrue(
            [item for item in self.find("gone", "not_checked", "lost for good")
             if "only the state before the last write" in item],
            "a removed gone/not_checked entry is lost for good after another write",
        )
        self.assertTrue(
            self.find("`warning`", "previous generation", "--undo", "does not restore"),
            "a printed warning means --undo does not restore the state before this write",
        )
        contract = items(SUMMARY_CONTRACT.read_text(encoding="utf-8"))
        self.assertTrue(
            [i for i in contract
             if "rollback" in i and "accepted.py --undo" in i and "only undo" in i],
            "summary-contract.md: --undo is the only undo",
        )
        self.assertTrue(
            [i for i in contract if "`warning`" in i and "does not restore" in i],
            "summary-contract.md: a warning means --undo does not restore",
        )
        self.assertFalse(
            [i for i in contract if re.search(r"copying it back|removing `?accepted\.json", i)],
            "summary-contract.md: no manual copy or delete as an undo",
        )

    def test_report_format(self):
        report_format = items(REPORT_FORMAT.read_text(encoding="utf-8"))
        joined = "\n".join(report_format)
        self.assertRegex(
            joined,
            r"nic więcej nie wymaga uwagi: n niskich, m zaakceptowanych",
            "the summary's last line gives N low and M accepted",
        )
        self.assertIn("zaakceptowanych nie sprawdzono", joined)
        self.assertTrue(
            [i for i in report_format if "zaakceptowane" in i and "quiet" in i],
            "report-format.md names the Zaakceptowane section and its quiet count",
        )
        self.assertTrue(
            [i for i in report_format
             if "back" in i and "skipped" in i and "nie sprawdzono" in i],
            "the skipped fields of a back item go under Nie sprawdzono",
        )
        self.assertTrue(
            [i for i in report_format
             if "back" in i and "ush-runall a<n>" in i and "evidence" in i
             and "no recommendation of its own" in i and "never gets two" in i],
            "report-format.md: a back item's evidence gets no recommendation of its own",
        )
        self.assertTrue(
            [i for i in self.items
             if "back" in i and "evidence" in i
             and "no recommendation of its own" in i and "never gets two" in i],
            "SKILL.md: a back item's evidence gets no recommendation of its own",
        )
        style = items(REPORT_STYLE.read_text(encoding="utf-8"))
        self.assertTrue(
            [i for i in style
             if "nic więcej nie wymaga uwagi" in i and "summary_counts" in i],
            "report-style.md allows a skill's counts from the JSON on the last line",
        )
        self.assertTrue(
            [i for i in self.items
             if "quiet" in i and "evidence" in i and "leftover" in i
             and "recommendation" in i and re.search(r"\bno\b|\bnot\b|\bnever\b", i)],
            "SKILL.md: the evidence of a quiet item gets no recommendation and no leftover line",
        )


if __name__ == "__main__":
    unittest.main()

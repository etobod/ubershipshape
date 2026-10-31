"""The ush-inventory SKILL.md: paste-ready blocks of plan 052 M3 (read as text only)."""

import re
import unittest

from tests.skill_loader import REPO_ROOT

SKILL_MD = REPO_ROOT / "skills" / "ush-inventory" / "SKILL.md"

REQUIRED = (
    "Remove-MpPreference",
    "Disable-NetFirewallRule",
    "Export-Certificate",
    "Get-FileHash",
    "Remove-LocalGroupMember",
    "Disable-WindowsOptionalFeature",
    "DisablePending",
    "Remove-WindowsCapability",
)
# No driver removal block, and a firewall rule is disabled, never removed.
FORBIDDEN = ("pnputil", "Remove-NetFirewallRule")


def _section(text, heading):
    """The body of the level-2 section ``## <heading>``, up to the next level-2 heading."""
    match = re.search(rf"^## {re.escape(heading)}[ \t]*$(.*?)(?=^## |\Z)", text,
                      re.MULTILINE | re.DOTALL)
    return match.group(1) if match else None


class TestDocs(unittest.TestCase):
    def test_blocks_present_and_no_driver_removal(self):
        self.assertTrue(SKILL_MD.is_file(), f"missing: {SKILL_MD}")
        text = SKILL_MD.read_text(encoding="utf-8")

        for word in REQUIRED:
            with self.subTest(required=word):
                self.assertIn(word, text)

        for word in FORBIDDEN:
            with self.subTest(forbidden=word):
                self.assertNotIn(word.lower(), text.lower())

        with self.subTest("the method: registry rule is in Rules"):
            rules = _section(text, "Rules")
            self.assertIsNotNone(rules, "SKILL.md has no '## Rules' section")
            self.assertIn("method: registry", rules or "")

    def test_copy_blocks_stop_before_damage(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        cert = _section(text, "Change blocks") or text
        # Cert:\...\Root joins other physical stores; the block checks them first.
        for store in ("AuthRoot\\Certificates", "Policies\\Microsoft\\SystemCertificates\\Root",
                      "EnterpriseCertificates\\Root",
                      "HKCU:\\Software\\Policies\\Microsoft\\SystemCertificates\\Root"):
            with self.subTest(other_store=store):
                self.assertIn(store, cert)
        with self.subTest("hosts backup never overwritten"):
            self.assertIn("if (Test-Path -LiteralPath $backup) { throw", text)
        with self.subTest("hash failure stops the hosts block"):
            self.assertIn("Get-FileHash -LiteralPath $backup -ErrorAction Stop", text)
            self.assertIn("Get-FileHash -LiteralPath $hosts -ErrorAction Stop", text)
        with self.subTest("duplicates may be on the same line"):
            self.assertNotIn("above 0 means more than one", text)
        with self.subTest("a profile path is expanded"):
            self.assertIn('"$env:USERPROFILE\\', text)


REFERENCES = REPO_ROOT / "skills" / "ush-inventory" / "references"
FIRST_RUN_FILE = "ush-inventory.first-run.json"


def _flat(text):
    """The text with every run of whitespace made one space."""
    return " ".join(text.split())


class TestFirstRunFileDocs(unittest.TestCase):
    """Test K16 (plan 092): the documents describe the first-run decision file."""

    def test_first_run_file_documented(self):
        contract = _flat((REFERENCES / "summary-contract.md").read_text(encoding="utf-8"))
        report = _flat((REFERENCES / "report-format.md").read_text(encoding="utf-8"))

        with self.subTest("contract names the file"):
            self.assertIn(FIRST_RUN_FILE, contract)

        with self.subTest("contract: unusable windows-own.json keeps decisions"):
            match = re.search(r"When `windows-own.json` cannot be read(.*?)(?=\. [A-Z`#]|\Z)",
                              contract)
            self.assertIsNotNone(match, "paragraph on an unusable windows-own.json")
            end = contract.find("`not_checked` has the item", match.start())
            self.assertNotEqual(end, -1, "end of the paragraph")
            paragraph = contract[match.start():end]
            self.assertIn(FIRST_RUN_FILE, paragraph)

        with self.subTest("contract: not_checked table"):
            row = re.search(r"\| `windows-own.json` \|([^|]*)\|", contract)
            self.assertIsNotNone(row, "windows-own.json row")
            self.assertIn(FIRST_RUN_FILE, row.group(1))
            self.assertIn("| `first-run certificates` |", contract)

        bullets =[m.start() for m in
                   re.finditer(re.escape('- `windows-own.json` in "Not checked"'), report)]
        self.assertTrue(bullets, 'no "windows-own.json in Not checked" item')
        for start in bullets:
            with self.subTest("report format: windows-own.json in Not checked", at=start):
                end = report.find(" - ", start + 2)
                bullet = report[start:end if end != -1 else len(report)]
                self.assertIn(FIRST_RUN_FILE, bullet)

        with self.subTest("report format: null means an unreadable decision file"):
            start = report.find("`windows_first_run` `null` means")
            self.assertNotEqual(start, -1)
            sentence = report[start:report.find(";", start)]
            self.assertIn(FIRST_RUN_FILE, sentence)
            self.assertNotIn("windows-own.json", sentence)


if __name__ == "__main__":
    unittest.main()

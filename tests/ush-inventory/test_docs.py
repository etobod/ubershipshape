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


if __name__ == "__main__":
    unittest.main()

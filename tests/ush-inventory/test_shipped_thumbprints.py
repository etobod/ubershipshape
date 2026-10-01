"""The Microsoft root thumbprints Windows ships, as listed in the real
skills/ush-inventory/data/windows-own.json (plan 080, milestone M3, criteria K1-K2;
K3-K4 are in ``test_additions.py``), and its first-run list (plan 083, milestone M2,
criterion K10). The file is read as data only."""

import json
import re
import unittest

from tests.skill_loader import REPO_ROOT

WINDOWS_OWN = REPO_ROOT / "skills" / "ush-inventory" / "data" / "windows-own.json"
KEY = "cert_windows_shipped_thumbprints"
THUMBPRINT = re.compile(r"[0-9A-F]{40}")
REQUIRED_SUBJECTS = (
    "Microsoft ECC Product Root Certificate Authority 2018",
    "Microsoft Time Stamp Root Certificate Authority 2014",
)


FIRST_RUN_KEY = "cert_windows_first_run"
AUTHENTICODE_CN = "Microsoft Authenticode(tm) Root Authority"


def windows_own():
    return json.loads(WINDOWS_OWN.read_text(encoding="utf-8-sig"))


def shipped_entries():
    return windows_own().get(KEY)


class TestShippedThumbprints(unittest.TestCase):
    def entries(self):
        entries = shipped_entries()
        self.assertIsInstance(entries, list, f"{KEY}: {entries!r}")
        self.assertTrue(entries, f"{KEY} is empty")
        return entries

    def test_entries_well_formed(self):
        entries = self.entries()
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertIsInstance(entry, dict, entry)
                thumbprint = entry.get("thumbprint")
                self.assertIsInstance(thumbprint, str, entry)
                self.assertRegex(thumbprint, r"\A[0-9A-F]{40}\Z", entry)
                subject = entry.get("subject")
                self.assertIsInstance(subject, str, entry)
                self.assertTrue(subject.strip(), entry)
                source = entry.get("source")
                self.assertIsInstance(source, str, entry)
                self.assertTrue(source.strip(), entry)
        thumbprints = [entry.get("thumbprint") for entry in entries]
        duplicates = sorted({t for t in thumbprints if thumbprints.count(t) > 1})
        self.assertEqual(duplicates, [], "thumbprints listed more than once")

    def test_required_roots_present(self):
        entries = self.entries()
        for subject in REQUIRED_SUBJECTS:
            with self.subTest(subject=subject):
                matching = [e for e in entries
                            if isinstance(e, dict) and e.get("subject") == subject]
                self.assertTrue(matching, f"no entry with subject {subject!r}")
                for entry in matching:
                    source = entry.get("source")
                    self.assertIsInstance(source, str, entry)
                    self.assertTrue(source.startswith("https://"), entry)
                    self.assertTrue(THUMBPRINT.fullmatch(entry.get("thumbprint") or ""),
                                    entry)

    def test_first_run_entries(self):
        """Authenticode Root is recognised by subject and serial, never by a thumbprint
        (plan 083, milestone M2, criterion K10)."""
        first_run = windows_own().get(FIRST_RUN_KEY)
        self.assertIsInstance(first_run, list, f"{FIRST_RUN_KEY}: {first_run!r}")
        matching = [e for e in first_run
                    if isinstance(e, dict) and e.get("subject_cn") == AUTHENTICODE_CN]
        self.assertTrue(matching, f"no {FIRST_RUN_KEY} entry for {AUTHENTICODE_CN!r}")
        for entry in matching:
            with self.subTest(entry=entry):
                self.assertEqual(entry.get("serial"), "01", entry)
                source = entry.get("source")
                self.assertIsInstance(source, str, entry)
                self.assertTrue(source.startswith("https://learn.microsoft.com/"), entry)
                self.assertNotIn("thumbprint", entry, entry)

        shipped = [e for e in self.entries()
                   if isinstance(e, dict) and "authenticode" in str(e.get("subject")).lower()]
        self.assertEqual(shipped, [], f"{KEY} lists an Authenticode Root thumbprint")


if __name__ == "__main__":
    unittest.main()

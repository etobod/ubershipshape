"""The sha256 fact of each autostart target (plan 060, M1 K5).

The ``file_facts`` job reads the hash with the file (row fields ``Sha256`` and
``Sha256Error``), so a test never reads a file of the machine. Every value is invented.
"""

import json
import unittest
from pathlib import Path

from .fakes import FakePowerShell, failure, ok
from .fakes_autostart import clean_responses, file_row, run_value
from .test_autostart import AutostartTestCase, run_key

TARGET = "C:\\Program Files\\Contoso\\Tray\\tray.exe"
HASH_UPPER = "0F1E2D3C4B5A69788796A5B4C3D2E1F00F1E2D3C4B5A69788796A5B4C3D2E1F0"


def hashed_row(path, sha256=None, error=None, **kwargs):
    row = file_row(path, **kwargs)
    row["Sha256"] = sha256
    row["Sha256Error"] = error
    return row


class TestAutostartHash(AutostartTestCase):
    def run_with(self, row, data_dir=None, file_facts=None):
        responses = clean_responses(extra_files=[row] if row is not None else [])
        responses["run_keys"] = ok([run_value("ContosoTray", f'"{TARGET}" /tray')])
        if file_facts is not None:
            responses["file_facts"] = file_facts
        return self.collect(FakePowerShell(responses), data_dir=data_dir)

    def detail_fact(self, summary):
        return self.first_fact(self.entry(summary, run_key("ContosoTray")))

    def test_existing_file_gets_its_hash(self):
        summary = self.run_with(hashed_row(TARGET, sha256=HASH_UPPER, signer="Contoso Ltd"))
        fact = self.detail_fact(summary)
        self.assertEqual(fact.get("sha256"), HASH_UPPER.lower(), fact)
        self.assertIsNone(fact.get("sha256_error"), fact)

    def test_unreadable_file_has_null_hash_and_reason(self):
        summary = self.run_with(hashed_row(TARGET, error="The process cannot access the file",
                                           signer="Contoso Ltd"))
        fact = self.detail_fact(summary)
        self.assertIsNone(fact.get("sha256"), fact)
        self.assertIn("cannot access", fact.get("sha256_error") or "", fact)

    def test_missing_file_has_null_hash_and_reason(self):
        summary = self.run_with(hashed_row(TARGET, exists=False, status=None, signer=None))
        fact = self.detail_fact(summary)
        self.assertIsNone(fact.get("sha256"), fact)
        self.assertTrue(fact.get("sha256_error"), fact)

    def test_summary_facts_carry_no_hash(self):
        summary = self.run_with(hashed_row(TARGET, sha256=HASH_UPPER, signer="Contoso Ltd"))
        self.assertEqual(self.detail_fact(summary).get("sha256"), HASH_UPPER.lower())
        self.assertTrue(summary.get("autostart"), summary)
        for item in summary.get("autostart") or []:
            for fact in item.get("facts") or []:
                self.assertNotIn("sha256", fact, item)
                self.assertNotIn("sha256_error", fact, item)

    def test_hash_is_carried_from_the_baseline(self):
        data_dir = self.data_dir()
        self.run_with(hashed_row(TARGET, sha256=HASH_UPPER, signer="Contoso Ltd"),
                      data_dir=data_dir)
        summary = self.run_with(None, data_dir=data_dir,
                                file_facts=failure("file_facts failed"))
        entry = self.entry(summary, run_key("ContosoTray"))
        self.assertIs(entry.get("facts_from_baseline"), True, entry)
        self.assertEqual(self.first_fact(entry).get("sha256"), HASH_UPPER.lower(), entry)

    def test_invalid_hash_value_has_null_hash_and_reason(self):
        summary = self.run_with(hashed_row(TARGET, sha256="not-a-hash", signer="Contoso Ltd"))
        fact = self.detail_fact(summary)
        self.assertIsNone(fact.get("sha256"), fact)
        self.assertIn("no valid hash", fact.get("sha256_error") or "", fact)

    def test_target_without_a_row_has_a_reason(self):
        summary = self.run_with(None)
        fact = self.detail_fact(summary)
        self.assertIsNone(fact.get("sha256"), fact)
        self.assertTrue(fact.get("sha256_error"), fact)
        # A target without a row was not read: the item says so (plan 060, M2 review).
        entry = self.entry(summary, run_key("ContosoTray"))
        self.assertIn("facts", entry.get("unread_fields") or [], entry)

    def test_baseline_without_hash_gives_a_reason(self):
        data_dir = self.data_dir()
        self.run_with(hashed_row(TARGET, sha256=HASH_UPPER, signer="Contoso Ltd"),
                      data_dir=data_dir)
        strip_hashes(Path(data_dir) / "state")
        summary = self.run_with(None, data_dir=data_dir,
                                file_facts=failure("file_facts failed"))
        entry = self.entry(summary, run_key("ContosoTray"))
        self.assertIs(entry.get("facts_from_baseline"), True, entry)
        fact = self.first_fact(entry)
        self.assertIsNone(fact.get("sha256"), fact)
        self.assertTrue(fact.get("sha256_error"), fact)


def strip_hashes(state_dir):
    """Make the saved baselines look written before the hash existed."""
    def strip(value):
        if isinstance(value, dict):
            value.pop("sha256", None)
            value.pop("sha256_error", None)
            for inner in value.values():
                strip(inner)
        elif isinstance(value, list):
            for inner in value:
                strip(inner)
    for path in Path(state_dir).glob("ush-inventory*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        strip(data)
        path.write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

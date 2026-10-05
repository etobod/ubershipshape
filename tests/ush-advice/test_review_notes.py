"""Tests for the code-review notes of plan 103, M1: os_version fields that Windows left
empty, products.json keys that could never match, the BIOS date taken in UTC and the
older HP manufacturer name.

The interface is described in ``fakes.py``. PowerShell never starts; every value is
invented.
"""

import json
import unittest
from unittest import mock

from .fakes import AdviceTestCase, FakePowerShell, ok, os_version_row


class TestReviewNotes(AdviceTestCase):
    def test_empty_os_version_fields_are_named(self):
        fake = FakePowerShell({"os_version": ok([os_version_row(ubr=None, edition_id="")])})
        summary = self.collect(fake)
        facts = self.machine_of(summary)
        self.assertIsNone(facts["ubr"])
        self.assertIsNone(facts["edition_id"])
        notes = [item for item in self.not_checked(summary)
                 if item.get("what") == "os_version fields"]
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        self.assertIn("ubr", notes[0]["reason"])
        self.assertIn("edition_id", notes[0]["reason"])

    def test_full_os_version_row_gives_no_field_note(self):
        summary = self.collect(FakePowerShell())
        self.assertEqual([item for item in self.not_checked(summary)
                          if item.get("what") == "os_version fields"], [])

    def test_products_key_that_cannot_match_is_rejected(self):
        for key in ("25H2|amd64", "25h2|AMD64", "25H2 |AMD64", "25H2| AMD64"):
            with self.subTest(key=key):
                products = self.temp_file(
                    "products.json", json.dumps({"products": {key: "Invented product"}}))
                fake = FakePowerShell()
                with mock.patch.object(self.advice, "PRODUCTS_FILE", products):
                    code, stdout, stderr = self.run_main(self.data_dir(), fake)
                self.assertEqual(code, 2, stdout[:300])
                self.assertTrue(stderr.strip())
                self.assertEqual(fake.calls, [])

    def test_domain_with_trailing_newline_is_rejected(self):
        data = json.loads(self.advice.SOURCES_FILE.read_text(encoding="utf-8"))
        data["sources"][0]["domains"] = ["cisa.gov" + chr(10)]
        sources = self.temp_file("sources.json", json.dumps(data))
        fake = FakePowerShell()
        with mock.patch.object(self.advice, "SOURCES_FILE", sources):
            code, stdout, stderr = self.run_main(self.data_dir(), fake)
        self.assertEqual(code, 2, stdout[:300])
        self.assertIn("domains", stderr)
        self.assertEqual(fake.calls, [])

    def test_bios_date_in_utc(self):
        self.assertIn("ReleaseDate.ToUniversalTime().ToString('yyyy-MM-dd'",
                      self.advice.FIRMWARE_BODY)

    def test_older_hp_name_has_hp_domain(self):
        data = json.loads(self.advice.SOURCES_FILE.read_text(encoding="utf-8"))
        prefixes = {entry["manufacturer_prefix"]: entry["domains"]
                    for entry in data["firmware_domains"]}
        self.assertTrue(prefixes.get("HP"))
        self.assertEqual(prefixes.get("Hewlett-Packard"), prefixes.get("HP"))

    def test_asus_prefix_is_the_short_name(self):
        # The SMBIOS manufacturer may be the short form; a prefix of the short form
        # also covers every longer one.
        data = json.loads(self.advice.SOURCES_FILE.read_text(encoding="utf-8"))
        prefixes = {entry["manufacturer_prefix"]: entry["domains"]
                    for entry in data["firmware_domains"]}
        self.assertIn("asus.com", prefixes.get("ASUS", []))


if __name__ == "__main__":
    unittest.main()

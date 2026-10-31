"""Tests for plan 135, M1: when a BIOS version on the manufacturer's page is the
installed one, and when a query carries the machine's BIOS version.

The interface is described in ``fakes.py``. PowerShell never starts; every value is
invented.
"""

import unittest

from .fakes import (
    AdviceTestCase,
    FakePowerShell,
    findings_doc,
    firmware_finding,
    firmware_row,
    machine,
    search,
)

ALL = ("release-info", "msrc", "kev", "release-health", "firmware")
BIOS_URL = "https://example.invalid/bios"


class TestReviewNotes135(AdviceTestCase):
    def firmware_summary(self, installed, offered, manufacturer="Contoso Ltd.",
                         model="Invented Book", bios_date="2026-01-10",
                         release_date="2026-09-01", url=BIOS_URL, query=None):
        fake = FakePowerShell(machine(firmware=firmware_row(
            manufacturer=manufacturer, model=model, bios_version=installed,
            release_date=bios_date)))
        finding = firmware_finding(manufacturer, model, offered, release_date, url,
                                   query=query)
        return self.collect_findings(
            fake, findings_doc([search(s) for s in ALL], [finding]))

    def test_family_code_and_date_are_not_the_version(self):
        cases = (
            ("T70 Ver. 01.16.00", "T70 Ver. 01.17.00"),
            ("F.20", "F.21 (2026-01-20)"),
        )
        for installed, offered in cases:
            with self.subTest(installed=installed, offered=offered):
                summary = self.firmware_summary(installed, offered,
                                                bios_date="2025-11-03",
                                                release_date="2026-02-14")
                item = summary["firmware"][0]
                self.assertIs(item["model_matches"], True, item)
                self.assertIs(item["same_version"], False, item)
                self.assertIs(item["newer"], True, item)

    def test_short_version_alone_still_matches(self):
        """Code-review notes on M1: a short version written alone, as SKILL.md asks."""
        cases = (
            ("X515EA.312", "312", True),
            ("X515EA.312", "v312", True), ("X515EA.312", "BIOS 312", True),
            ("Ver 1.0.1234", "1.0.1234", True),
            ("X515EA.312", "313", False),
            ("F.20", "F.21 (01/20/26)", False),
        )
        for installed, offered, same in cases:
            with self.subTest(installed=installed, offered=offered):
                item = self.firmware_summary(installed, offered)["firmware"][0]
                self.assertIs(item["same_version"], same, item)
                self.assertIs(item["newer"], not same, item)

    def test_version_written_another_way_still_matches(self):
        contoso = ("Contoso Ltd.", "Invented Book")
        hp = ("HP", "Invented Desk 400")
        cases = (
            (contoso, "N3XET82W (1.54 )", "1.54 (N3XET82W)", True),
            (contoso, "N3XET82W (1.54 )", "N3XET82W (1.54)", True),
            (contoso, "F.20", "F.20 Rev.A", True),
            (contoso, "V1.20", "1.20", True),
            (contoso, "1.20", "v1.20", True),
            (contoso, "F.20", "G.20", False),
            (contoso, "F.20", "F.21", False),
            (contoso, "N3XET82W (1.54 )", "N3XET90W (1.62)", False),
            (contoso, "N3XET82W (1.54 )", "BIOS N3XET82W", True),
            (hp, "HP-01.310", "310", True),
        )
        for (manufacturer, model), installed, offered, same in cases:
            with self.subTest(installed=installed, offered=offered):
                summary = self.firmware_summary(installed, offered,
                                                manufacturer=manufacturer, model=model)
                item = summary["firmware"][0]
                self.assertIs(item["same_version"], same, item)
                self.assertIs(item["newer"], not same, item)

    def test_short_whole_bios_version_gives_no_warning(self):
        for installed, query in (("1.0", "bios 1.0 update"), ("324", "bios 324")):
            with self.subTest(installed=installed, query=query):
                plain = self.firmware_summary(installed, "2.05")
                summary = self.firmware_summary(installed, "2.05", query=query)
                self.assertEqual(summary["query_warnings"], [], summary["query_warnings"])
                # The query adds no not_checked item: the list is the one of the same
                # run without a query.
                self.assertEqual(self.not_checked(summary), self.not_checked(plain))

        with self.subTest("a long whole version is still found"):
            summary = self.firmware_summary("N3XET82W (1.54 )", "N3XET90W",
                                            query="Contoso N3XET82W update")
            reasons = [w["reason"] for w in summary["query_warnings"]]
            self.assertIn("bios_version", reasons)

    def test_fact_after_a_single_v_is_found(self):
        for query, warned in (("Contoso BIOS v1.54 update", True),
                              ("Contoso BIOS xv1.54 update", False),
                              ("Contoso bios1.54 update", False)):
            with self.subTest(query=query):
                summary = self.firmware_summary("N3XET82W (1.54 )", "N3XET90W",
                                                query=query)
                reasons = [w["reason"] for w in summary["query_warnings"]]
                self.assertEqual("bios_version" in reasons, warned, reasons)

    def test_installed_version_with_v_found_without_it(self):
        for query, warned in (("Contoso BIOS 1.20 update", True),
                              ("Contoso BIOS v1.20 update", True),
                              ("Contoso BIOS update", False)):
            with self.subTest(query=query):
                summary = self.firmware_summary("V1.20", "V1.30", query=query)
                reasons = [w["reason"] for w in summary["query_warnings"]]
                self.assertEqual("bios_version" in reasons, warned, reasons)


if __name__ == "__main__":
    unittest.main()

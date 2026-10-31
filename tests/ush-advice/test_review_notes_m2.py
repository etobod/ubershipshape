"""Tests for the code-review notes of plan 103, M2: KEV findings without the update
months, machine facts followed by a dot in a query or url, and a ``kind`` that is not
a text.

The interface is described in ``fakes.py``. PowerShell never starts; every value is
invented.
"""

import unittest

from .fakes import (
    AdviceTestCase,
    FakePowerShell,
    exploited_finding,
    findings_doc,
    firmware_finding,
    firmware_row,
    machine,
    search,
    update_finding,
)

ALL = ("release-info", "msrc", "kev", "release-health", "firmware")


class TestReviewNotesM2(AdviceTestCase):
    def test_exploited_needs_the_msrc_search(self):
        update = update_finding("2026-09", "KB5099901", "26200.6899",
                                cves=[("CVE-2026-40001", "Important")])
        kev = exploited_finding("CVE-2026-40001")
        for status in ("partial", "unreadable", None):
            with self.subTest(msrc=status):
                searches = [search(s) for s in ALL if s != "msrc"]
                if status is not None:
                    searches.append(search("msrc", status, "Invented: cut short."))
                summary = self.collect_findings(FakePowerShell(),
                                                findings_doc(searches, [update, kev]))
                self.assertIsNone(summary["exploited"])
                self.assertIsNone(summary["kev_other_count"])
                self.assertTrue([n for n in self.not_checked(summary)
                                 if n.get("what") == "exploited"], self.not_checked(summary))

    def test_fact_followed_by_a_dot_is_found(self):
        fake = FakePowerShell(machine(firmware=firmware_row(bios_version="HP-01.310"),
                                      kbs=["KB5099917"]))
        cases = [
            ("build in a url with .html", None,
             "https://support.microsoft.com/os-build-26200.6899.html", "build"),
            ("build at the end of a sentence", "updates for 26200.6899.",
             None, "build"),
            ("bios in a url with .pdf", None, "https://support.hp.com/HP-01.310.pdf",
             "bios_version"),
            ("kb at the end of a sentence", "what is KB5099917.", None, "kb"),
        ]
        for label, query, url, reason in cases:
            with self.subTest(label):
                finding = firmware_finding("HP", "Invented Book", "01.320", "2026-09-01",
                                           url or "https://support.hp.com/drivers",
                                           query=query)
                summary = self.collect_findings(
                    fake, findings_doc([search(s) for s in ALL], [finding]))
                self.assertIn(reason, [w["reason"] for w in summary["query_warnings"]])

        with self.subTest("a longer version is not this machine's"):
            finding = firmware_finding("HP", "Invented Book", "01.320", "2026-09-01",
                                       "https://support.hp.com/drivers",
                                       query="26200.6899.1 and HP-01.310.5")
            summary = self.collect_findings(
                fake, findings_doc([search(s) for s in ALL], [finding]))
            self.assertEqual(summary["query_warnings"], [])

    def test_member_of_the_bios_version_is_found(self):
        fake = FakePowerShell(machine(firmware=firmware_row(
            manufacturer="Contoso Ltd.", bios_version="N3XET82W (1.54 )")))
        for label, query, warned in (("main member", "N3XET82W BIOS update", True),
                                     ("dotted member", "Contoso BIOS 1.54", True),
                                     ("short member only", "Contoso 54 W", False)):
            with self.subTest(label):
                finding = firmware_finding("Contoso Ltd.", "Invented Book", "N3XET90W",
                                           "2026-09-01", "https://example.invalid/bios",
                                           query=query)
                summary = self.collect_findings(
                    fake, findings_doc([search(s) for s in ALL], [finding]))
                reasons = [w["reason"] for w in summary["query_warnings"]]
                self.assertEqual("bios_version" in reasons, warned, reasons)

    def test_kind_that_is_not_text_exits_2(self):
        bad = update_finding("2026-09", "KB5099901", "26200.6899")
        bad["kind"] = ["update"]
        code, stdout, stderr = self.run_findings(
            self.data_dir(), FakePowerShell(),
            findings_doc([search(s) for s in ALL], [bad]))
        self.assertEqual(code, 2, stdout[:300])
        self.assertIn("entry 0", stderr)


if __name__ == "__main__":
    unittest.main()

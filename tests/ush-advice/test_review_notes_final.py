"""Tests for the final-review notes of plan 103: several known issues on one release
health page, and a BIOS version that the manufacturer's page writes in another form.

The interface is described in ``fakes.py``. PowerShell never starts; every value is
invented.
"""

import json
import unittest
from datetime import timedelta

from .fakes import (
    NOW,
    AdviceTestCase,
    FakePowerShell,
    findings_doc,
    firmware_finding,
    firmware_row,
    issue_finding,
    machine,
    search,
)

ALL = ("release-info", "msrc", "kev", "release-health", "firmware")
PAGE = "https://learn.microsoft.com/windows/release-health/status-invented-version"


class TestReviewNotesFinal(AdviceTestCase):
    def test_issues_on_one_page_are_kept_apart(self):
        data_dir = self.data_dir()
        fake = FakePowerShell()
        first = [issue_finding(f"Invented issue {n}", PAGE) for n in (1, 2, 3)]
        summary = self.collect_findings(
            fake, findings_doc([search(s) for s in ALL], first), data_dir=data_dir)
        titles = [item["title"] for item in summary["issues"]]
        self.assertEqual(titles, ["Invented issue 1", "Invented issue 2",
                                  "Invented issue 3"])

        added = first + [issue_finding("Invented issue 4", PAGE)]
        summary = self.collect_findings(
            fake, findings_doc([search(s) for s in ALL], added), data_dir=data_dir,
            now=NOW + timedelta(hours=1))
        new = {item["title"]: item["new"] for item in summary["issues"]}
        self.assertEqual(new, {"Invented issue 1": False, "Invented issue 2": False,
                               "Invented issue 3": False, "Invented issue 4": True})

    def test_issues_saved_by_address_alone_are_not_new(self):
        data_dir = self.data_dir()
        fake = FakePowerShell()
        issues = [issue_finding(f"Invented issue {n}", PAGE) for n in (1, 2)]
        doc = findings_doc([search(s) for s in ALL], issues)
        self.collect_findings(fake, doc, data_dir=data_dir)
        path = data_dir / "state" / "ush-advice.json"
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["sources"]["issues"] = {PAGE: {"url": PAGE}}
        path.write_text(json.dumps(saved), encoding="utf-8")

        summary = self.collect_findings(fake, doc, data_dir=data_dir,
                                        now=NOW + timedelta(hours=1))
        self.assertEqual(summary["comparison"]["issues"], "no_baseline")
        self.assertEqual([item["new"] for item in summary["issues"]], [None, None])

        summary = self.collect_findings(fake, doc, data_dir=data_dir,
                                        now=NOW + timedelta(hours=2))
        self.assertEqual([item["new"] for item in summary["issues"]], [False, False])
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn(PAGE, saved["sources"]["issues"])

    def test_same_issue_twice_is_one_item(self):
        twice = [issue_finding("Invented issue", PAGE),
                 issue_finding("invented issue ", PAGE)]
        summary = self.collect_findings(
            FakePowerShell(), findings_doc([search(s) for s in ALL], twice))
        self.assertEqual(len(summary["issues"]), 1, summary["issues"])

    def test_bios_version_written_another_way(self):
        cases = (
            ("N3XET82W (1.54 )", "1.54 (N3XET82W)", True),
            ("N3XET82W (1.54 )", "N3XET82W (1.54)", True),
            ("F.20", "F.20 Rev.A", True),
            ("V1.20", "1.20", True),
            ("1.20", "v1.20", True),
            ("F.20", "G.20", False),
            ("F.20", "F.21", False),
            ("N3XET82W (1.54 )", "N3XET90W (1.62)", False),
        )
        for installed, offered, same in cases:
            with self.subTest(installed=installed, offered=offered):
                fake = FakePowerShell(machine(firmware=firmware_row(
                    manufacturer="Contoso Ltd.", model="Invented Book",
                    bios_version=installed, release_date="2026-01-10")))
                finding = firmware_finding("Contoso Ltd.", "Invented Book", offered,
                                           "2026-09-01", "https://example.invalid/bios")
                summary = self.collect_findings(
                    fake, findings_doc([search(s) for s in ALL], [finding]))
                item = summary["firmware"][0]
                self.assertIs(item["same_version"], same, item)
                self.assertIs(item["newer"], not same, item)


if __name__ == "__main__":
    unittest.main()

"""Tests for plan 136, M1: the ``release-info`` search fills ``updates``; ``msrc`` only
gives the CVE counts of the months; ``exploited`` needs ``kev``, ``msrc`` and
``release-info`` all read.

The interface is described in ``fakes.py``. Additions of this milestone:

- Search ids, in this order: ``release-info``, ``msrc``, ``kev``, ``release-health``,
  ``firmware``; the summary ``searches`` has one entry per id in that order.
- An ``update`` finding may have ``cves`` null (a release-information row).
- ``cve_count`` and ``critical_count`` are null when ``msrc`` is not read or no finding
  of the month has a ``cves`` list.
- A search item of ``not_checked`` has ``what`` like ``search msrc``.

PowerShell never starts; every build, KB, CVE and URL is invented.
"""

import json
import re
import unittest

from tests.skill_loader import REPO_ROOT

from .fakes import (
    AdviceTestCase,
    FakePowerShell,
    exploited_finding,
    findings_doc,
    machine,
    os_version_row,
    search,
    update_finding,
)

SEARCH_ORDER = ("release-info", "msrc", "kev", "release-health", "firmware")


def low(value):
    return str(value).lower()


class TestReleaseInfo(AdviceTestCase):
    def notes_with_what(self, summary, text):
        """``not_checked`` items whose ``what`` contains ``text`` (case-insensitive)."""
        return [item for item in self.not_checked(summary)
                if text.lower() in low(item.get("what"))]

    def exploited_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if low(item.get("what")).strip() == "exploited"]

    # K1
    def test_months_without_cves(self):
        fake = FakePowerShell(machine(
            os_row=os_version_row(build="26100", ubr=6584),
            kbs=["KB5099841"]))
        findings = [
            update_finding("2026-09", "KB5099841", "26100.6584", cves=None,
                           release_type="security"),
            update_finding("2026-09", "KB5099862", "26100.6725", cves=None,
                           release_type="preview"),
            exploited_finding("CVE-2026-40001"),
        ]
        searches = [search("release-info"),
                    search("msrc", "unreadable", "Invented: document too large."),
                    search("kev")]
        summary = self.collect_findings(fake, findings_doc(searches, findings))

        updates = self.items(summary, "updates")
        self.assertEqual(len(updates), 1, updates)
        item = updates[0]
        self.assertEqual(item.get("id"), "u1", item)
        self.assertEqual(item.get("month"), "2026-09", item)
        self.assertIs(item.get("applied"), True, item)
        self.assertEqual(sorted(item.get("kbs") or []), ["KB5099841", "KB5099862"], item)
        self.assertIn("cve_count", item, item)
        self.assertIsNone(item["cve_count"], item)
        self.assertIn("critical_count", item, item)
        self.assertIsNone(item["critical_count"], item)

        msrc_notes = self.notes_with_what(summary, "search msrc")
        self.assertTrue(msrc_notes, self.not_checked(summary))
        self.assertTrue(
            [n for n in msrc_notes
             if "cve_count" in low(n.get("what")) or "cve_count" in low(n.get("reason"))],
            msrc_notes)

        self.assertIn("exploited", summary, summary.keys())
        self.assertIsNone(summary["exploited"], summary["exploited"])

    # K2
    def test_updates_need_release_info(self):
        findings = [
            update_finding("2026-09", "KB5099901", "26200.6899",
                           cves=[("CVE-2026-40001", "Important"),
                                 ("CVE-2026-40002", "Critical")]),
            exploited_finding("CVE-2026-40001"),
        ]
        cases = (
            ("release-info unreadable",
             [search("release-info", "unreadable", "Invented: page not loaded."),
              search("msrc"), search("kev")]),
            ("release-info missing", [search("msrc"), search("kev")]),
        )
        for label, searches in cases:
            with self.subTest(label):
                summary = self.collect_findings(FakePowerShell(),
                                                findings_doc(searches, findings))
                self.assertIn("updates", summary, summary.keys())
                self.assertIsNone(summary["updates"], summary["updates"])
                self.assertIn("exploited", summary, summary.keys())
                self.assertIsNone(summary["exploited"], summary["exploited"])
                self.assertTrue(self.notes_with_what(summary, "search release-info"),
                                self.not_checked(summary))
                exploited = self.exploited_notes(summary)
                self.assertTrue(
                    [n for n in exploited if "release-info not read" in low(n.get("reason"))],
                    self.not_checked(summary))

        with self.subTest("module docstring"):
            doc = re.sub(r"[`'\"]", "", low(self.advice.__doc__ or ""))
            doc = re.sub(r"\s+", " ", doc)
            self.assertNotIn("from msrc", doc)

        with self.subTest("msrc unreadable"):
            searches = [search("release-info"),
                        search("msrc", "unreadable", "Invented: document too large."),
                        search("kev")]
            summary = self.collect_findings(FakePowerShell(),
                                            findings_doc(searches, findings))
            exploited = self.exploited_notes(summary)
            self.assertTrue(exploited, self.not_checked(summary))
            self.assertTrue(
                [n for n in exploited if "msrc not read" in low(n.get("reason"))],
                exploited)
            for note in exploited:
                self.assertNotIn("could not be matched", low(note.get("reason")), note)

    # K3
    def test_counts_when_msrc_read(self):
        september = [
            update_finding("2026-09", "KB5099901", "26200.6899",
                           cves=[("CVE-2026-40001", "Critical"),
                                 ("CVE-2026-40002", "Important")]),
            update_finding("2026-09", "KB5099902", "26200.6899",
                           cves=[("CVE-2026-40003", "Important")]),
        ]
        searches = [search("release-info"), search("msrc")]

        with self.subTest("every month has cves"):
            summary = self.collect_findings(FakePowerShell(),
                                            findings_doc(searches, september))
            item = self.item_by(summary, "updates", "month", "2026-09")
            self.assertEqual(item.get("cve_count"), 3, item)
            self.assertEqual(item.get("critical_count"), 1, item)
            self.assertEqual(
                [n for n in self.not_checked(summary)
                 if "cve_count" in low(n.get("what")) or "cve_count" in low(n.get("reason"))],
                [], self.not_checked(summary))
            names = [entry.get("name") for entry in self.items(summary, "searches")]
            self.assertEqual(names, list(SEARCH_ORDER), names)

        with self.subTest("a month without cves"):
            august = [
                update_finding("2026-08", "KB5099881", "26200.6800", cves=None),
                update_finding("2026-08", "KB5099882", "26200.6850", cves=None,
                               release_type="preview"),
            ]
            summary = self.collect_findings(FakePowerShell(),
                                            findings_doc(searches, august + september))
            aug = self.item_by(summary, "updates", "month", "2026-08")
            self.assertIn("cve_count", aug, aug)
            self.assertIsNone(aug["cve_count"], aug)
            self.assertIn("critical_count", aug, aug)
            self.assertIsNone(aug["critical_count"], aug)
            sep = self.item_by(summary, "updates", "month", "2026-09")
            self.assertEqual(sep.get("cve_count"), 3, sep)
            self.assertEqual(sep.get("critical_count"), 1, sep)
            notes = self.notes_with_what(summary, "updates cve_count")
            self.assertEqual(len(notes), 1, self.not_checked(summary))
            self.assertTrue("2026-08" in low(notes[0].get("what"))
                            or "2026-08" in low(notes[0].get("reason")), notes)
            self.assertFalse("2026-09" in low(notes[0].get("what"))
                             or "2026-09" in low(notes[0].get("reason")), notes)
            names = [entry.get("name") for entry in self.items(summary, "searches")]
            self.assertEqual(names, list(SEARCH_ORDER), names)

    # K6
    def test_applied_notes_follow_release_info(self):
        fake = FakePowerShell(machine(os_row=os_version_row(ubr=None)))
        finding = update_finding("2026-09", "KB5099901", "26200.6899", cves=None,
                                 release_type="security")

        with self.subTest("release-info read, msrc unreadable"):
            summary = self.collect_findings(fake, findings_doc(
                [search("release-info"),
                 search("msrc", "unreadable", "Invented: document too large.")],
                [finding]))
            self.assertTrue(self.notes_with_what(summary, "updates applied"),
                            self.not_checked(summary))

        with self.subTest("release-info unreadable, msrc read"):
            summary = self.collect_findings(fake, findings_doc(
                [search("release-info", "unreadable", "Invented: page not loaded."),
                 search("msrc")],
                [finding]))
            self.assertEqual(self.notes_with_what(summary, "updates applied"), [],
                             self.not_checked(summary))

    # K4
    def test_cves_null_or_list(self):
        searches = [search("release-info"), search("msrc")]
        bad = update_finding("2026-09", "KB5099841", "26100.6584")
        bad["cves"] = "CVE-2026-1"
        data_dir = self.data_dir()
        code, _, stderr = self.run_findings(data_dir, FakePowerShell(machine()),
                                            findings_doc(searches, [bad]))
        self.assertEqual(code, 2, stderr[:300])
        self.assertIn("cves", stderr)
        self.assertFalse((data_dir / "state").exists())

        summary = self.collect_findings(FakePowerShell(machine()), findings_doc(
            searches, [update_finding("2026-09", "KB5099841", "26100.6584", cves=None)]))
        self.assertEqual(len(summary.get("updates") or []), 1, summary.get("updates"))

    # K5
    def test_source_entry(self):
        sources = json.loads((REPO_ROOT / "skills" / "ush-advice" / "data" / "sources.json")
                             .read_text(encoding="utf-8"))["sources"]
        entries = [s for s in sources if s.get("id") == "release-info"]
        self.assertEqual(len(entries), 1, sources)
        self.assertEqual(entries[0]["url"], "https://learn.microsoft.com/windows/"
                                            "release-health/windows11-release-information")
        self.assertEqual(entries[0]["kind"], "release-info")
        self.assertEqual(set(entries[0]["domains"]),
                         {"learn.microsoft.com", "support.microsoft.com"})


if __name__ == "__main__":
    unittest.main()

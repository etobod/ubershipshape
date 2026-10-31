"""Findings compared with the machine in skills/ush-advice/scripts/advice.py (plan 103,
M2): ``applied`` by build, CVE counts and exploited CVEs, firmware version then date,
listed domains, file shape, searches, query warnings, ``new`` since the last run and the
summary budget.

The interface is described in ``fakes.py``. PowerShell never starts; every KB, CVE,
build, URL and title is invented.
"""

import json
import unittest
from datetime import timedelta

from .fakes import (
    NOW,
    AdviceTestCase,
    FakePowerShell,
    exploited_finding,
    failure,
    findings_doc,
    firmware_finding,
    firmware_row,
    issue_finding,
    machine,
    os_version_row,
    search,
    update_finding,
)

ALL_SEARCHES = ("release-info", "msrc", "kev", "release-health", "firmware")
LISTS = ("updates", "exploited", "firmware", "issues")
BUDGET = 35000


def all_read():
    return [search(search_id) for search_id in ALL_SEARCHES]


def issue_url(n):
    return f"https://learn.microsoft.com/windows/release-health/invented-issue-{n}"


def padded(entry, count=13):
    """``count`` valid issue findings, then ``entry`` (0-based index ``count``)."""
    return [issue_finding(f"Invented issue {n}", issue_url(n)) for n in range(count)] + [entry]


def lenovo_machine(manufacturer="Lenovo"):
    return machine(firmware=firmware_row(manufacturer=manufacturer,
                                         model="Invented Model 14",
                                         bios_version="N3EET45W",
                                         release_date="2026-04-15"))


def hp_machine():
    return machine(firmware=firmware_row(manufacturer="HP", model="Invented Desk 400",
                                         bios_version="HP-01.310",
                                         release_date="2026-03-01"))


LENOVO_URL = "https://support.lenovo.com/downloads/invented-model-14-bios"


class TestFindings(AdviceTestCase):
    def assert_entry_error(self, findings, index, searches=None):
        """The file with ``findings`` exits 2 naming entry ``index`` and writes no state."""
        data_dir = self.data_dir()
        doc = findings_doc(searches if searches is not None else all_read(), findings)
        code, stdout, stderr = self.run_findings(data_dir, FakePowerShell(), doc)
        self.assertEqual(code, 2, f"stdout={stdout[:300]!r} stderr={stderr[:300]!r}")
        self.assertRegex(stderr, rf"\b({index}|{index + 1})\b",
                         "stderr does not name the entry number")
        state = data_dir / "state"
        written = sorted(p.name for p in state.rglob("*")) if state.exists() else []
        self.assertEqual(written, [], "files written under state/ after a bad file")

    def assert_no_query_text(self, warnings, query):
        for warning in warnings:
            for value in warning.values():
                self.assertNotEqual(str(value), query, warning)
                self.assertNotIn(query, str(value), warning)
            self.assertNotIn(query, json.dumps(warning), warning)

    def warnings_of(self, summary):
        warnings = summary.get("query_warnings")
        self.assertIsInstance(warnings, list, summary.get("query_warnings"))
        for warning in warnings:
            self.assertIsInstance(warning, dict, warnings)
            self.assertTrue(str(warning.get("finding_id", "")).startswith("w"), warnings)
        return warnings

    # K5
    def test_applied_by_build(self):
        months = [
            update_finding("2026-01", "KB5099901", "10.0.26200.6899"),
            update_finding("2026-02", "KB5099902", "26200.6899"),
            update_finding("2026-03", "KB5099903", "10.0.26200.6901"),
            update_finding("2026-04", "KB5099904", "10.0.26200.6800"),
            update_finding("2026-04", "KB5099905", "10.0.26200.6950"),
            update_finding("2026-05", "KB5099906", "10.0.26100.6899"),
            update_finding("2026-06", "KB5099907", "10.0.26200.6950",
                           release_type="preview"),
        ]
        doc = findings_doc([search("release-info"), search("msrc")], months)

        with self.subTest("build 26200 with UBR 6899"):
            summary = self.collect_findings(FakePowerShell(), doc)
            for item in self.items(summary, "updates"):
                self.assertTrue(str(item.get("id", "")).startswith("u"), item)

            first = self.item_by(summary, "updates", "month", "2026-01")
            self.assertIs(first.get("applied"), True, first)
            self.assertEqual(first.get("fixed_builds"), ["26200.6899"], first)
            self.assertEqual(first.get("kbs"), ["KB5099901"], first)
            self.assertEqual(first.get("kb_installed"), ["KB5099901"], first)

            short = self.item_by(summary, "updates", "month", "2026-02")
            self.assertIs(short.get("applied"), True, short)
            self.assertEqual(short.get("fixed_builds"), ["26200.6899"], short)
            self.assertEqual(short.get("kb_installed"), [], short)

            later = self.item_by(summary, "updates", "month", "2026-03")
            self.assertIs(later.get("applied"), False, later)
            self.assertEqual(later.get("kb_installed"), [], later)

            mixed = self.item_by(summary, "updates", "month", "2026-04")
            self.assertIn("applied", mixed, mixed)
            self.assertIsNone(mixed["applied"], mixed)
            self.assertIn("mixed", str(mixed.get("applied_reason")), mixed)

            mismatch = self.item_by(summary, "updates", "month", "2026-05")
            self.assertIn("applied", mismatch, mismatch)
            self.assertIsNone(mismatch["applied"], mismatch)
            self.assertIn("build mismatch", str(mismatch.get("applied_reason")), mismatch)

            preview = self.item_by(summary, "updates", "month", "2026-06")
            self.assertIn("applied", preview, preview)
            self.assertIsNone(preview["applied"], preview)

        with self.subTest("no UBR gives null with a not_checked item"):
            no_ubr = machine(os_row=os_version_row(ubr=None))
            control = self.collect_findings(FakePowerShell(no_ubr),
                                            findings_doc([search("release-info"), search("msrc")], []))
            self.assertEqual(control.get("updates"), [], control.get("updates"))
            summary = self.collect_findings(
                FakePowerShell(no_ubr),
                findings_doc([search("release-info"), search("msrc")], [months[0]]))
            item = self.item_by(summary, "updates", "month", "2026-01")
            self.assertIn("applied", item, item)
            self.assertIsNone(item["applied"], item)
            self.assertGreater(len(self.not_checked(summary)),
                               len(self.not_checked(control)),
                               self.not_checked(summary))

        with self.subTest("hotfixes unreadable gives kb_installed null"):
            summary = self.collect_findings(
                FakePowerShell({"hotfixes": failure("Invented: Get-HotFix failed.")}), doc)
            item = self.item_by(summary, "updates", "month", "2026-01")
            self.assertIn("kb_installed", item, item)
            self.assertIsNone(item["kb_installed"], item)

        with self.subTest("fixed_build 6899 exits 2"):
            good = update_finding("2026-07", "KB5099908", "26200.6899")
            self.collect_findings(FakePowerShell(), findings_doc(all_read(), padded(good)))
            bad = update_finding("2026-07", "KB5099908", "6899")
            self.assert_entry_error(padded(bad), 13)

    # K6
    def test_counts_and_exploited(self):
        findings = [
            update_finding("2026-07", "KB5099871", "26200.6700",
                           cves=[("CVE-2026-40001", "Critical"),
                                 ("CVE-2026-40002", "Important")]),
            update_finding("2026-07", "KB5099872", "26200.6700",
                           cves=[("CVE-2026-40002", "Important")]),
            update_finding("2026-08", "KB5099881", "26200.6800",
                           cves=[("CVE-2026-50010", "Important")]),
            update_finding("2026-08", "KB5099882", "26200.6950",
                           cves=[("CVE-2026-50010", "Important")]),
            update_finding("2026-09", "KB5099891", "26200.6899",
                           cves=[("CVE-2026-50010", "Important")]),
            exploited_finding("CVE-2026-50010"),
            exploited_finding("CVE-2026-59999", product="Invented Mail Server"),
        ]
        summary = self.collect_findings(
            FakePowerShell(), findings_doc([search("release-info"), search("msrc"), search("kev")], findings))

        july = self.item_by(summary, "updates", "month", "2026-07")
        self.assertEqual(july.get("cve_count"), 2, july)
        self.assertEqual(july.get("critical_count"), 1, july)

        august = self.item_by(summary, "updates", "month", "2026-08")
        self.assertIn("applied", august, august)
        self.assertIsNone(august["applied"], august)
        september = self.item_by(summary, "updates", "month", "2026-09")
        self.assertIs(september.get("applied"), True, september)

        exploited = self.items(summary, "exploited")
        self.assertEqual([item.get("cve") for item in exploited], ["CVE-2026-50010"],
                         exploited)
        item = exploited[0]
        self.assertTrue(str(item.get("id", "")).startswith("k"), item)
        self.assertIs(item.get("in_updates"), True, item)
        self.assertEqual(item.get("month"), "2026-08", item)
        self.assertIs(item.get("applied"), True, item)
        self.assertEqual(item.get("vendor"), "Contoso", item)
        self.assertEqual(item.get("date_added"), "2026-09-02", item)
        self.assertEqual(item.get("due_date"), "2026-09-23", item)

        self.assertEqual(summary.get("kev_other_count"), 1, summary.get("kev_other_count"))
        detail = self.detail_of(summary)
        kev_other = detail.get("kev_other")
        self.assertIsInstance(kev_other, list, detail.keys())
        self.assertEqual([entry.get("cve") for entry in kev_other], ["CVE-2026-59999"],
                         kev_other)

    # K7
    def firmware_item(self, responses, finding):
        summary = self.collect_findings(FakePowerShell(responses),
                                        findings_doc([search("firmware")], [finding]))
        items = self.items(summary, "firmware")
        self.assertEqual(len(items), 1, items)
        self.assertTrue(str(items[0].get("id", "")).startswith("f"), items)
        return items[0]

    def test_firmware_version_then_date(self):
        with self.subTest("same version, later date"):
            item = self.firmware_item(lenovo_machine(), firmware_finding(
                "Lenovo", "Invented Model 14", "N3EET45W", "2026-06-01", LENOVO_URL))
            self.assertIs(item.get("model_matches"), True, item)
            self.assertIs(item.get("same_version"), True, item)
            self.assertIs(item.get("newer"), False, item)

        with self.subTest("other version, later date"):
            item = self.firmware_item(lenovo_machine(), firmware_finding(
                "Lenovo", "Invented Model 14", "N3EET50W", "2026-06-01", LENOVO_URL))
            self.assertIs(item.get("same_version"), False, item)
            self.assertIs(item.get("newer"), True, item)

        with self.subTest("other version, same date"):
            item = self.firmware_item(lenovo_machine(), firmware_finding(
                "Lenovo", "Invented Model 14", "N3EET50W", "2026-04-15", LENOVO_URL))
            self.assertIs(item.get("newer"), False, item)

        with self.subTest("other model"):
            item = self.firmware_item(lenovo_machine(), firmware_finding(
                "Lenovo", "Invented Model 16", "N3EET50W", "2026-06-01", LENOVO_URL))
            self.assertIs(item.get("model_matches"), False, item)
            self.assertIn("newer", item, item)
            self.assertIsNone(item["newer"], item)

        with self.subTest("firmware job failed"):
            item = self.firmware_item(
                {"firmware": failure("Invented: Win32_BIOS query failed.")},
                firmware_finding("Lenovo", "Invented Model 14", "N3EET50W", "2026-06-01",
                                 LENOVO_URL))
            self.assertIn("model_matches", item, item)
            self.assertIsNone(item["model_matches"], item)
            self.assertIn("newer", item, item)
            self.assertIsNone(item["newer"], item)

        with self.subTest("HP-01.310 against 310"):
            item = self.firmware_item(hp_machine(), firmware_finding(
                "HP", "Invented Desk 400", "310", "2026-05-01",
                "https://support.hp.com/invented/desk-400-bios"))
            self.assertIs(item.get("same_version"), True, item)
            self.assertIs(item.get("newer"), False, item)

        with self.subTest("support.lenovo.com with manufacturer LENOVO"):
            item = self.firmware_item(lenovo_machine("LENOVO"), firmware_finding(
                "Lenovo", "Invented Model 14", "N3EET50W", "2026-06-01", LENOVO_URL))
            self.assertIs(item.get("listed"), True, item)

        with self.subTest("support.lenovo.com with manufacturer HP"):
            item = self.firmware_item(hp_machine(), firmware_finding(
                "HP", "Invented Desk 400", "02.100", "2026-05-01", LENOVO_URL))
            self.assertIs(item.get("listed"), False, item)

    # K8
    def test_listed_shape_searches_and_warnings(self):
        with self.subTest("domains"):
            urls = {
                "Invented issue on support": "https://support.microsoft.com/help/5099990",
                "Invented issue on answers":
                    "https://answers.microsoft.com/windows/forum/invented-thread-1",
                "Invented issue on a lookalike":
                    "https://microsoft.com.evil.example/windows/invented-issue",
            }
            findings = [issue_finding(title, url) for title, url in urls.items()]
            summary = self.collect_findings(
                FakePowerShell(), findings_doc([search("release-health")], findings))
            expected = {
                "Invented issue on support": True,
                "Invented issue on answers": False,
                "Invented issue on a lookalike": False,
            }
            for title, listed in expected.items():
                item = self.item_by(summary, "issues", "title", title)
                self.assertTrue(str(item.get("id", "")).startswith("i"), item)
                self.assertIs(item.get("listed"), listed, item)

            detail = self.detail_of(summary)
            entries = detail.get("findings")
            self.assertIsInstance(entries, list, detail.keys())
            self.assertEqual([entry.get("id") for entry in entries], ["w1", "w2", "w3"],
                             entries)
            self.assertEqual(entries[0].get("domain"), "support.microsoft.com", entries[0])
            self.assertEqual([entry.get("listed") for entry in entries],
                             [True, False, False], entries)

        for label in ("no url", "http url", "unknown kind"):
            with self.subTest(f"code 2: {label}"):
                good = issue_finding("Invented issue checked", issue_url(99))
                self.collect_findings(FakePowerShell(),
                                      findings_doc(all_read(), padded(good)))
                bad = dict(good)
                if label == "no url":
                    del bad["url"]
                elif label == "http url":
                    bad["url"] = "http://learn.microsoft.com/windows/release-health/x"
                else:
                    bad["kind"] = "advisory"
                self.assert_entry_error(padded(bad), 13)

        with self.subTest("warning: build in the query"):
            query = "26200.6899 issues"
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                [search("release-health")],
                [issue_finding("Invented issue", issue_url(1), query=query)]))
            warnings = self.warnings_of(summary)
            self.assertEqual([(w.get("finding_id"), w.get("reason")) for w in warnings],
                             [("w1", "build")], warnings)
            self.assert_no_query_text(warnings, query)

        bios_cases = (
            ("HP-01.310 in query", hp_machine(),
             {"query": "HP-01.310 update notes"}),
            ("HP-01.310 in url", hp_machine(),
             {"url": "https://support.microsoft.com/invented/HP-01.310"}),
            ("N3EET45W (1.45 ) in query",
             machine(firmware=firmware_row(bios_version="N3EET45W (1.45 )")),
             {"query": "bios N3EET45W (1.45 ) changelog"}),
            ("N3EET45W (1.45 ) in url",
             machine(firmware=firmware_row(bios_version="N3EET45W (1.45 )")),
             {"url": "https://support.microsoft.com/search?q=N3EET45W (1.45 )"}),
        )
        for label, responses, fields in bios_cases:
            with self.subTest(f"warning: bios_version, {label}"):
                finding = issue_finding("Invented issue", issue_url(2))
                finding.update(fields)
                summary = self.collect_findings(FakePowerShell(responses), findings_doc(
                    [search("release-health")], [finding]))
                warnings = self.warnings_of(summary)
                self.assertEqual(
                    [(w.get("finding_id"), w.get("reason")) for w in warnings],
                    [("w1", "bios_version")], warnings)
                if "query" in fields:
                    self.assert_no_query_text(warnings, fields["query"])

        with self.subTest("warning: hotfix KB outside the update findings"):
            query = "KB5099917 install fails"
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                [search("release-info"), search("msrc"), search("release-health")],
                [update_finding("2026-09", "KB5099901", "26200.6899"),
                 issue_finding("Invented issue", issue_url(3), query=query)]))
            warnings = self.warnings_of(summary)
            self.assertEqual([(w.get("finding_id"), w.get("reason")) for w in warnings],
                             [("w2", "kb")], warnings)
            self.assert_no_query_text(warnings, query)

        with self.subTest("no warning"):
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                [search("release-info"), search("msrc"), search("release-health")],
                [update_finding("2026-09", "KB5099901", "26200.6899",
                                url="https://support.microsoft.com/help/KB5099901",
                                query="KB5099901 known issues"),
                 issue_finding("Invented issue A", issue_url(4),
                               query="Windows 11 25H2 known issues"),
                 issue_finding("Invented issue B", issue_url(5),
                               query="error 1268990 after update")]))
            self.assertEqual(self.warnings_of(summary), [])

        exploited = [update_finding("2026-09", "KB5099901", "26200.6899",
                                    cves=[("CVE-2026-50010", "Important")]),
                     exploited_finding("CVE-2026-50010")]

        with self.subTest("searches without kev"):
            summary = self.collect_findings(FakePowerShell(),
                                            findings_doc([search("release-info"), search("msrc")], exploited))
            self.assertIn("exploited", summary, summary.keys())
            self.assertIsNone(summary["exploited"], summary["exploited"])
            notes = [item for item in self.not_checked(summary)
                     if "kev" in str(item.get("what")).lower()
                     or "kev" in str(item.get("reason")).lower()]
            self.assertTrue(notes, self.not_checked(summary))

        with self.subTest("kev partial"):
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                [search("release-info"), search("msrc"), search("kev", "partial", "Invented: document truncated")],
                exploited))
            self.assertIn("exploited", summary, summary.keys())
            self.assertIsNone(summary["exploited"], summary["exploited"])
            entries = self.detail_of(summary).get("findings")
            self.assertIsInstance(entries, list)
            self.assertTrue([entry for entry in entries
                             if entry.get("kind") == "exploited"
                             and entry.get("cve") == "CVE-2026-50010"], entries)

        with self.subTest("kev read without findings"):
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                [search("release-info"), search("msrc"), search("kev")], exploited[:1]))
            self.assertEqual(summary.get("exploited"), [], summary.get("exploited"))

    # K9
    def test_new_since_last_run(self):
        def updates(*months):
            return [update_finding(month, f"KB50999{month[-2:]}", "26200.6899")
                    for month in months]

        def bios(*versions):
            return [firmware_finding("Contoso Ltd.", "Contoso Book 14", version,
                                     "2026-07-01",
                                     "https://www.contoso.example/support/bios")
                    for version in versions]

        def new_of(summary, name, key, value):
            item = self.item_by(summary, name, key, value)
            self.assertIn("new", item, item)
            return item["new"]

        data_dir = self.data_dir()
        baseline = data_dir / "state" / "ush-advice.json"
        fake = FakePowerShell()
        both = [search("release-info"), search("msrc"), search("firmware")]

        with self.subTest("run 1: no baseline"):
            summary = self.collect_findings(
                fake, findings_doc(both, updates("2026-08") + bios("CB14.320.0")),
                data_dir=data_dir, now=NOW)
            self.assertIsNone(new_of(summary, "updates", "month", "2026-08"))
            self.assertIsNone(new_of(summary, "firmware", "version", "CB14.320.0"))
            comparison = summary.get("comparison")
            self.assertIsInstance(comparison, dict, summary.get("comparison"))
            self.assertEqual(comparison.get("updates"), "no_baseline", comparison)
            self.assertEqual(comparison.get("firmware"), "no_baseline", comparison)
            self.assertTrue(baseline.is_file(), "no state/ush-advice.json after run 1")

        with self.subTest("run 2: a new month and a new BIOS"):
            summary = self.collect_findings(
                fake, findings_doc(both, updates("2026-08", "2026-09")
                                   + bios("CB14.320.0", "CB14.330.0")),
                data_dir=data_dir, now=NOW + timedelta(hours=1))
            self.assertIs(new_of(summary, "updates", "month", "2026-08"), False)
            self.assertIs(new_of(summary, "updates", "month", "2026-09"), True)
            self.assertIs(new_of(summary, "firmware", "version", "CB14.320.0"), False)
            self.assertIs(new_of(summary, "firmware", "version", "CB14.330.0"), True)
            self.assertEqual(summary.get("comparison", {}).get("updates"), "compared",
                             summary.get("comparison"))

        with self.subTest("run 3: without --findings"):
            code, stdout, stderr = self.run_main(data_dir, fake,
                                                 now=NOW + timedelta(hours=2))
            self.assertEqual(code, 0, stderr[:300])
            summary = self.parse(stdout)
            comparison = summary.get("comparison")
            self.assertIsInstance(comparison, dict, summary.get("comparison"))
            for name in LISTS:
                self.assertEqual(comparison.get(name), "not_read", comparison)
            self.assertTrue(baseline.is_file(), "baseline gone after a run without findings")

        with self.subTest("run 4: firmware search unreadable"):
            summary = self.collect_findings(
                fake, findings_doc(
                    [search("release-info"), search("msrc"),
                     search("firmware", "unreadable", "Invented: page did not load")],
                    updates("2026-08") + bios("CB14.330.0")),
                data_dir=data_dir, now=NOW + timedelta(hours=3))
            self.assertIn("firmware", summary, summary.keys())
            self.assertIsNone(summary["firmware"], summary["firmware"])
            self.assertEqual(summary.get("comparison", {}).get("firmware"), "not_read",
                             summary.get("comparison"))
            self.assertIs(new_of(summary, "updates", "month", "2026-08"), False)

        with self.subTest("run 5: firmware kept, month back again"):
            summary = self.collect_findings(
                fake, findings_doc(both, updates("2026-08", "2026-09")
                                   + bios("CB14.330.0")),
                data_dir=data_dir, now=NOW + timedelta(hours=4))
            self.assertIs(new_of(summary, "firmware", "version", "CB14.330.0"), False)
            self.assertIs(new_of(summary, "updates", "month", "2026-09"), False)

        with self.subTest("month present, absent, present again"):
            other_dir = self.data_dir()
            msrc = [search("release-info"), search("msrc")]
            self.collect_findings(fake, findings_doc(msrc, updates("2026-05")),
                                  data_dir=other_dir, now=NOW)
            summary = self.collect_findings(fake, findings_doc(msrc, updates("2026-06")),
                                            data_dir=other_dir,
                                            now=NOW + timedelta(hours=1))
            self.assertIs(new_of(summary, "updates", "month", "2026-06"), True)
            summary = self.collect_findings(
                fake, findings_doc(msrc, updates("2026-05", "2026-06")),
                data_dir=other_dir, now=NOW + timedelta(hours=2))
            self.assertIs(new_of(summary, "updates", "month", "2026-05"), False)
            self.assertIs(new_of(summary, "updates", "month", "2026-06"), False)

    # K10
    def test_budget(self):
        def long_title(prefix, n):
            title = f"{prefix} {n}: invented description of a known problem "
            return (title + "with a long explanation " * 10)[:200]

        def build(issue_count, exploited_count):
            cves = [f"CVE-2026-{60000 + n}" for n in range(exploited_count)]
            findings = [update_finding("2026-09", "KB5099909", "26200.6899",
                                       cves=[(cve, "Important") for cve in cves])]
            findings += [exploited_finding(cve, title=long_title("Invented exploited", n))
                         for n, cve in enumerate(cves)]
            findings += [issue_finding(long_title("Invented issue", n), issue_url(n))
                         for n in range(issue_count)]
            return findings_doc([search("release-info"), search("msrc"), search("kev"), search("release-health")],
                                findings)

        small = self.collect_findings(FakePowerShell(), build(1, 1))

        code, stdout, stderr = self.run_findings(self.data_dir(), FakePowerShell(),
                                                 build(500, 300))
        self.assertEqual(code, 0, f"--findings run failed: {stderr[:400]}")
        self.assertLessEqual(len(stdout), BUDGET, f"summary is {len(stdout)} chars")
        summary = self.parse(stdout)

        truncated = summary.get("truncated")
        truncated_exploited = summary.get("truncated_exploited")
        self.assertIsInstance(truncated, int, summary.get("truncated"))
        self.assertIsInstance(truncated_exploited, int, summary.get("truncated_exploited"))
        self.assertGreater(truncated, 0)
        self.assertGreater(truncated_exploited, 0)
        self.assertEqual(len(self.items(summary, "issues")) + truncated, 500)
        self.assertEqual(len(self.items(summary, "exploited")) + truncated_exploited, 300)
        self.assertGreater(len(self.not_checked(summary)), len(self.not_checked(small)),
                           self.not_checked(summary))

        detail = self.detail_of(summary)
        self.assertEqual(len(detail.get("issues") or []), 500)
        self.assertEqual(len(detail.get("exploited") or []), 300)
        self.assertEqual(len(detail.get("findings") or []), 801)


if __name__ == "__main__":
    unittest.main()

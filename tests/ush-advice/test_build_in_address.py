"""The build with its UBR in the hyphen form (``26200-6899``) in a query or an address,
and the KB page exception (plan 147, M1).

The interface is described in ``fakes.py``. PowerShell never starts; the default
machine is build 26200 with UBR 6899 and hotfixes KB5099901 and KB5099917; every URL,
title and query is invented.
"""

import json
import re
import unittest

from tests.skill_loader import REPO_ROOT

from .fakes import (
    AdviceTestCase,
    FakePowerShell,
    findings_doc,
    issue_finding,
    machine,
    search,
    update_finding,
)

SKILL_DIR = REPO_ROOT / "skills" / "ush-advice"
SKILL_MD = SKILL_DIR / "SKILL.md"
CONTRACT = SKILL_DIR / "references" / "summary-contract.md"

UPDATE_SEARCHES = ("release-info", "msrc", "release-health")
PLAIN_ISSUE_URL = "https://learn.microsoft.com/windows/release-health/invented-issue-1"


def searches(*ids):
    return [search(search_id) for search_id in ids]


def update_kb5099901(url=None):
    return update_finding("2026-09", "KB5099901", "26200.6899", url=url)


def _read(path):
    if not path.is_file():
        raise AssertionError(f"missing: {path}")
    return path.read_text(encoding="utf-8")


def _section(text, heading):
    """The text under ``## <heading>`` up to the next heading of level 1 or 2."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^##\s+{re.escape(heading)}\s*$", line.strip(), re.IGNORECASE):
            start = index + 1
            break
    if start is None:
        raise AssertionError(f"no '## {heading}' section")
    body = []
    for line in lines[start:]:
        if re.match(r"^#{1,2}\s", line):
            break
        body.append(line)
    return "\n".join(body)


def _items(text):
    """List items and paragraphs, each with its wrapped lines joined."""
    items, current = [], []
    for line in text.splitlines():
        stripped = line.strip()
        starts_item = re.match(r"^([-*+]|\d+[.)])\s", stripped)
        if not stripped or starts_item or stripped.startswith("#"):
            if current:
                items.append(" ".join(current))
            current = [stripped] if stripped else []
        else:
            current.append(stripped)
    if current:
        items.append(" ".join(current))
    return items


def _item_with(items, *needles):
    lowered = [needle.lower() for needle in needles]
    return [item for item in items if all(needle in item.lower() for needle in lowered)]


class TestBuildInAddress(AdviceTestCase):
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

    def pairs(self, warnings):
        return [(w.get("finding_id"), w.get("reason")) for w in warnings]

    # K1
    def test_hyphen_build_in_query_warns(self):
        with self.subTest("hyphen form alone in the query"):
            query = "26200-6899 install fails"
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                searches("release-health"),
                [issue_finding("Invented issue", PLAIN_ISSUE_URL, query=query)]))
            warnings = self.warnings_of(summary)
            self.assertEqual(self.pairs(warnings), [("w1", "build")], warnings)
            self.assert_no_query_text(warnings, query)

        with self.subTest("a KB of an update finding in the query is no exception"):
            query = "KB5099901 26200-6899 install fails"
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                searches(*UPDATE_SEARCHES),
                [update_kb5099901(),
                 issue_finding("Invented issue", PLAIN_ISSUE_URL, query=query)]))
            warnings = self.warnings_of(summary)
            self.assertEqual(self.pairs(warnings), [("w2", "build")], warnings)
            self.assert_no_query_text(warnings, query)

    # K2
    def test_hyphen_build_in_other_address_warns(self):
        url = "https://support.microsoft.com/en-us/topic/invented-os-build-26200-6899-a1b2"
        summary = self.collect_findings(FakePowerShell(), findings_doc(
            searches(*UPDATE_SEARCHES),
            [update_kb5099901(), issue_finding("Invented issue", url)]))
        warnings = self.warnings_of(summary)
        issue_reasons = [w.get("reason") for w in warnings if w.get("finding_id") == "w2"]
        update_warnings = [w for w in warnings if w.get("finding_id") == "w1"]
        self.assertIn("build", issue_reasons, warnings)
        self.assertEqual(update_warnings, [], warnings)

    # K3
    def test_kb_page_of_update_finding_gives_no_warning(self):
        with self.subTest("clean data"):
            summary = self.collect_findings(FakePowerShell(), findings_doc(
                searches(*UPDATE_SEARCHES),
                [update_kb5099901(), issue_finding("Invented issue", PLAIN_ISSUE_URL)]))
            self.assertEqual(self.warnings_of(summary), [])

        # KB5099901 is not among the hotfixes: only the update finding exception applies.
        fake = FakePowerShell(machine(kbs=["KB5099917"]))
        urls = (
            ("https://support.microsoft.com/en-us/topic/"
             "september-8-2026-kb5099901-os-build-26200-6899-invented"),
            "https://support.microsoft.com/help/5099901/os-build-26200-6899",
        )
        for url in urls:
            with self.subTest(url=url):
                summary = self.collect_findings(fake, findings_doc(
                    searches(*UPDATE_SEARCHES),
                    [update_kb5099901(url=url), issue_finding("Invented issue", url)]))
                self.assertEqual(self.warnings_of(summary), [])

    # K4
    def test_other_numbers_give_no_warning(self):
        for number in ("26200-68991", "126200-6899", "26200-6898", "26100-6899"):
            with self.subTest(number=number, field="query"):
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    searches("release-health"),
                    [issue_finding("Invented issue", PLAIN_ISSUE_URL,
                                   query=f"{number} install fails")]))
                self.assertEqual(self.warnings_of(summary), [])
            with self.subTest(number=number, field="url"):
                url = f"https://support.microsoft.com/en-us/topic/invented-os-build-{number}"
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    searches("release-health"), [issue_finding("Invented issue", url)]))
                self.assertEqual(self.warnings_of(summary), [])

    # K5
    def test_docs_name_hyphen_form_and_kb_page(self):
        rules = _items(_section(_read(SKILL_MD), "Rules"))
        with self.subTest("fetched source rule: as it is, KB page"):
            self.assertTrue(_item_with(rules, "fetched source", "as it is", "KB page"),
                            rules)
        with self.subTest("never holds rule names 26200-6899"):
            self.assertTrue(_item_with(rules, "never holds", "26200-6899"), rules)
        with self.subTest("fetched source rule: machine.hotfixes and may not"):
            self.assertTrue(_item_with(rules, "fetched source", "as it is", "KB page",
                                       "machine.hotfixes", "may not"), rules)

        warnings = _items(_section(_read(CONTRACT), "Query warnings"))
        with self.subTest("build warning: hyphen form and the KB page exception"):
            self.assertTrue(_item_with(warnings, "`build`", "<build>-<UBR>",
                                       "`update` finding", "machine.hotfixes"), warnings)

    # K6
    def test_dot_build_in_kb_address_still_warns(self):
        url = "https://support.microsoft.com/invented/kb5099901/26200.6899"
        summary = self.collect_findings(FakePowerShell(), findings_doc(
            searches(*UPDATE_SEARCHES),
            [update_kb5099901(), issue_finding("Invented issue", url)]))
        warnings = self.warnings_of(summary)
        self.assertEqual(self.pairs(warnings), [("w2", "build")], warnings)

    # K7
    def test_kb_page_of_hotfix_gives_no_warning(self):
        url = ("https://support.microsoft.com/en-us/topic/"
               "invented-kb5099917-os-build-26200-6899-oob")
        summary = self.collect_findings(FakePowerShell(), findings_doc(
            [search("release-info", "unreadable", "Invented: page did not load"),
             search("release-health")],
            [issue_finding("Invented issue", url)]))
        self.assertEqual(self.warnings_of(summary), [])

    def test_kb_beside_build_in_search_address_warns(self):
        # A KB of this machine elsewhere in the url is no KB page name.
        for url in ("https://www.bing.com/search?q=KB5099917+26200-6899",
                    "https://invented.example/kb5099901/notes/26200-6899"):
            with self.subTest(url=url):
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    [search("release-health")],
                    [issue_finding("Invented issue", url)]))
                self.assertEqual(self.pairs(self.warnings_of(summary)), [("w1", "build")])

    def test_page_name_in_search_part_or_build_again_warns(self):
        # Only the page name in the path is cut out; the rest of the url is searched.
        for url in ("https://www.bing.com/search?q=kb5099917-os-build-26200-6899",
                    ("https://support.microsoft.com/en-us/topic/"
                     "kb5099917-os-build-26200-6899?x=26200-6899")):
            with self.subTest(url=url):
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    [search("release-health")],
                    [issue_finding("Invented issue", url)]))
                self.assertEqual(self.pairs(self.warnings_of(summary)), [("w1", "build")])

    def test_build_right_after_page_name_warns(self):
        # A page name holds one build, or two joined by -and-, never more.
        for tail in ("kb5099917-os-build-26200-6899-26200-6899",
                     "kb5099917-os-build-26100-1-26200-6899",
                     "kb5099917-os-build-1-2-and-26200-6899"):
            url = "https://support.microsoft.com/en-us/topic/" + tail
            with self.subTest(url=url):
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    [search("release-health")],
                    [issue_finding("Invented issue", url)]))
                self.assertEqual(self.pairs(self.warnings_of(summary)), [("w1", "build")])

    def test_page_name_with_two_builds_gives_no_warning(self):
        # Pages for two versions name both builds: os-builds-<b>-<u>-and-<b2>-<u2>.
        for url in (("https://support.microsoft.com/en-us/topic/september-8-2026-"
                     "kb5099917-os-builds-26200-6899-and-26100-6899-invented"),
                    ("https://support.microsoft.com/en-us/topic/september-8-2026-"
                     "kb5099917-os-builds-26100-6899-and-26200-6899-invented")):
            with self.subTest(url=url):
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    [search("release-health")],
                    [issue_finding("Invented issue", url)]))
                self.assertEqual(self.warnings_of(summary), [])

    def test_localized_page_name_gives_no_warning(self):
        # Localized pages translate the words between the KB and the builds.
        for tail in ("wrzesnia-8-2026-kb5099917-kompilacja-systemu-operacyjnego-26200-6899-x1",
                     ("wrzesnia-8-2026-kb5099917-kompilacje-systemu-operacyjnego-"
                      "26200-6899-i-26100-6899-x1"),
                     "8-september-2026-kb5099917-betriebssystembuild-26200-6899-x1"):
            url = "https://support.microsoft.com/pl-pl/topic/" + tail
            with self.subTest(url=url):
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    [search("release-health")],
                    [issue_finding("Invented issue", url)]))
                self.assertEqual(self.warnings_of(summary), [])

    def test_page_of_other_kb_warns(self):
        # KB5099999 is neither an update finding nor a hotfix of this machine.
        url = ("https://support.microsoft.com/en-us/topic/"
               "september-8-2026-kb5099999-os-build-26200-6899-invented")
        summary = self.collect_findings(FakePowerShell(), findings_doc(
            searches(*UPDATE_SEARCHES),
            [update_kb5099901(), issue_finding("Invented issue", url)]))
        self.assertEqual(self.pairs(self.warnings_of(summary)), [("w2", "build")])

    def test_page_words_stop_at_a_path_separator(self):
        for url in ("https://invented.example/kb5099917/notes/26200-6899",
                    "https://invented.example/kb5099917-notes/26200-6899"):
            with self.subTest(url=url):
                summary = self.collect_findings(FakePowerShell(), findings_doc(
                    [search("release-health")],
                    [issue_finding("Invented issue", url)]))
                self.assertEqual(self.pairs(self.warnings_of(summary)), [("w1", "build")])


if __name__ == "__main__":
    unittest.main()

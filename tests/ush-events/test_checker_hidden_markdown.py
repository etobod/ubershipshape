"""Report check: no links, link reference definitions or raw HTML anywhere in a line.

Invented data only.
"""

import importlib
import unittest

# The shared base class; the package name has a hyphen, so import it by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
CheckerTestCase, NOT_CHECKED = _edges.CheckerTestCase, _edges.NOT_CHECKED

B3 = "`" * 3

# Every number in the clean report (3, 5, 10, 00) is a reading of this summary,
# and both group ids (g1, g2) are named in plain text.
SUMMARY = {
    "count": 8,
    "groups": [
        {"id": "g1", "provider": "Invented-Provider", "event_id": 10, "count": 3},
        {"id": "g2", "provider": "Invented-Other", "event_id": 7, "count": 5},
    ],
    "truncated": 0,
    "first_time": "10:00",
    "first_hour": 10,
    "first_minute": 0,
}
INTRO = ["# Event log review", "There were 3 events.", "Groups g1 and g2."]
# Line 1 is the summary marker; INTRO fills lines 2-4; the case is line 5.
CASE_LINE = 1 + len(INTRO) + 1


class HiddenMarkdownTestCase(CheckerTestCase):
    def setUp(self):
        super().setUp()
        self.summary(SUMMARY)

    def check_line(self, line):
        return self.run_check([*INTRO, line, "", *NOT_CHECKED])


class TestPlainTextPasses(HiddenMarkdownTestCase):
    def test_plain_text_passes(self):
        code, output = self.run_check([
            *INTRO,
            "Errors a < b in g1.",
            "Count 3<5 in g2.",
            "< 3 ms at the start",
            "- <= 3 ms",
            "",
            "> &lt;Data> sample",
            "",
            "Groups [g1] and (g2), see list: [a], x] (y",
            "Time 10:00 [UTC] in g1.",
            "",
            "> proc[x&rsqb;: sample [y&rsqb;(z) in g1",
            "",
            B3,
            "<log>",
            "[x](g2)",
            "[x]: g2",
            B3,
            "",
            *NOT_CHECKED,
        ])
        self.assertEqual(code, 0, output)
        self.assertIn("OK", output)


class TestRawHtml(HiddenMarkdownTestCase):
    def test_raw_html_mid_line_is_rejected(self):
        cases = [
            "Text <span hidden>g2</span>",
            "a <?x g2 ?>",
            "a <![CDATA[ g2 ]]>",
            "a <!X g2>",
            "a </b> g2",
            "see <http://example.invalid/g2>",
            "Code `<b>` g2",
            "C:\\<b> g2",
            "> Sample \\<Data> g2",
            "- item <i>g2</i>",
        ]
        for line in cases:
            with self.subTest(line=line):
                code, output = self.check_line(line)
                self.assertEqual(code, 2, output)
                self.assertIn(f"line {CASE_LINE} has raw HTML", output)
                self.assertIn("&lt;", output)


class TestLinkReferenceDefinition(HiddenMarkdownTestCase):
    def test_link_reference_definition_is_rejected(self):
        cases = [
            "[//]: # (g2)",
            "[x]: g2",
            "[^1]: g2",
            "   [x]: g2",
            "> [x]: g2",
            "- [x]: g2",
            "1. [x]: g2",
            "[a\\]b g2]: /x",
        ]
        for line in cases:
            with self.subTest(line=line):
                code, output = self.check_line(line)
                self.assertEqual(code, 2, output)
                self.assertIn(f"line {CASE_LINE} has ']:'", output)

        with self.subTest(case="label split over lines 5-7 after a blank line 4"):
            # Lines 2-3 are text, line 4 is blank, the label spans lines 5-7.
            code, output = self.run_check([*INTRO[:2], "", "[", "g2", "]: /x", "",
                                           *NOT_CHECKED])
            self.assertEqual(code, 2, output)
            self.assertIn("line 7 has ']:'", output)


class TestLink(HiddenMarkdownTestCase):
    def test_link_is_rejected(self):
        cases = [
            "[szczegóły](g2)",
            "See [x](#g1) now",
            "![img](g2)",
            '[x](http://example.invalid "g2")',
            "> quote [x](g2)",
        ]
        for line in cases:
            with self.subTest(line=line):
                code, output = self.check_line(line)
                self.assertEqual(code, 2, output)
                self.assertIn(f"line {CASE_LINE} has a link", output)


class TestRuleOrder(HiddenMarkdownTestCase):
    def test_existing_rules_keep_their_order(self):
        for line in ["<b>text", "- <details>"]:
            with self.subTest(line=line):
                code, output = self.check_line(line)
                self.assertEqual(code, 2, output)
                self.assertIn(f"line {CASE_LINE} has raw HTML", output)
                self.assertIn("&lt;", output)
                self.assertNotIn("\\<", output)

        with self.subTest(line="<!-- g2 -->"):
            code, output = self.check_line("<!-- g2 -->")
            self.assertEqual(code, 2, output)
            self.assertIn(f"line {CASE_LINE} has an HTML comment", output)
            self.assertNotIn("has raw HTML", output)


if __name__ == "__main__":
    unittest.main()

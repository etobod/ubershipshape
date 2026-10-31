"""The narrow report format the checker understands in full (invented data only)."""

import importlib
import unittest

# The shared base class; the package name has a hyphen, so import it by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
CheckerTestCase, NOT_CHECKED = _edges.CheckerTestCase, _edges.NOT_CHECKED

B3 = "`" * 3


class TestFenceIndent(CheckerTestCase):
    def test_closing_fence_must_match_opening_indent(self):
        with self.subTest(case="closing fence indented deeper than the opening one"):
            # A renderer closes the block at the 4-space fence; 412 must not hide in it.
            self.summary({"count": 3})
            code, output = self.run_check(["- Fix:", "  " + B3, "  cmd", "    " + B3,
                                           "  There were 412 events.", "  " + B3,
                                           *NOT_CHECKED])
            self.assertNotEqual(code, 0, output)
            self.assertEqual(code, 2, output)

        with self.subTest(case="closing fence at the opening indent"):
            self.summary({"count": 3})
            code, output = self.run_check(["- Fix:", "  " + B3, "  cmd", "  " + B3,
                                           "- There were 3 events.", *NOT_CHECKED])
            self.assertEqual(code, 0, output)


class TestNoHtml(CheckerTestCase):
    def test_html_block_is_rejected(self):
        self.summary({"count": 3})
        rejected = {
            "html block hiding a fence": ["<details>", B3, "</details>",
                                          "There were 412 events.", "", B3],
            "comment not closed on its line": ["<!-- note", "There were 3 events."],
            "comment opened mid-line and not closed on it": [
                "There were 3 events. <!-- note", "g2 -->"],
            "comment opener after an escaped backslash": [r"Sample: C:\\<!-- note", "-->"],
            "comment opener after an escaped backtick": [r"See \` and <!-- g2 `n`", "-->"],
            "one-line comment": ["<!-- note -->", "There were 3 events."],
            "comment closed within a line": ["There were 3 events. <!-- note -->"],
            "escaped comment opener in a quote": ["> Sample: payload \\<!-- cut"],
            "comment opener in inline code": ["Payload `<!--` cut"],
            "inline code after an escaped backslash": [r"Path C:\\`<!-- x` shown"],
            "comment after an escaped backtick": [r"Escape \` then <!-- g2 `x` --> hidden"],
            "backticks in two comments": ["Note <!-- a ` --> x <!-- g2 ` --> end"],
            "html after a bullet marker": ["- <details>", "  " + B3, "  </details>",
                                           "  There were 412 events.", "", "  " + B3],
            "html after an ordered marker": ["1. <details>", "  " + B3, "  </details>",
                                             "  There were 412 events.", "", "  " + B3],
            "html after a bullet and a tab": ["-\t<details>", "  " + B3, "  </details>",
                                              "  There were 412 events.", "", "  " + B3],
            "escaped angle bracket in a quote": ["> \\<tag> text"],
        }
        for case, body in rejected.items():
            with self.subTest(case=case):
                code, output = self.run_check([*body, *NOT_CHECKED])
                self.assertEqual(code, 2, output)

        accepted = {
            "powershell block comment inside a code block": [B3 + "powershell",
                                                             "<# note #>", B3],
            "entity angle bracket in a quote": ["> &lt;tag> text"],
        }
        for case, body in accepted.items():
            with self.subTest(case=case):
                code, output = self.run_check([*body, *NOT_CHECKED])
                self.assertEqual(code, 0, output)


class TestParenDelimiter(CheckerTestCase):
    def test_number_after_text_is_checked_whatever_the_delimiter(self):
        self.summary({"count": 3})
        with self.subTest(case="paren number after a dot item"):
            code, output = self.run_check(["1. a", "text", "7) b", *NOT_CHECKED])
            self.assertEqual(code, 1, output)
            self.assertIn(": 7 is not", output)

        with self.subTest(case="paren number after mixed items"):
            code, output = self.run_check(["1) x", "1. a", "text", "2) b", *NOT_CHECKED])
            self.assertEqual(code, 1, output)
            self.assertIn(": 2 is not", output)


class TestNumberInItem(CheckerTestCase):
    def test_number_continuing_a_numbered_item_is_checked(self):
        self.summary({"count": 3})
        code, output = self.run_check(["1. First item", "   412. more", "2. second",
                                       *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)
        self.assertIn(": 2 is not", output)


class TestSetextUnderline(CheckerTestCase):
    def test_numbers_near_a_setext_underline_are_checked(self):
        self.summary({"count": 3})
        with self.subTest(case="number after a setext heading is checked"):
            code, output = self.run_check(["Title", "===", "2. Next", *NOT_CHECKED])
            self.assertEqual(code, 1, output)
            self.assertIn(": 2 is not", output)

        with self.subTest(case="number mid paragraph is still checked"):
            code, output = self.run_check(["Some text", "2. Next", *NOT_CHECKED])
            self.assertEqual(code, 1, output)
            self.assertIn(": 2 is not", output)

        with self.subTest(case="underline after a blank line is paragraph text"):
            code, output = self.run_check(["", "===", "2. Next", *NOT_CHECKED])
            self.assertEqual(code, 1, output)
            self.assertIn(": 2 is not", output)


if __name__ == "__main__":
    unittest.main()

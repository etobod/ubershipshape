"""The narrowed report format: no numbered lists, only in-order numbered headings (invented data)."""

import importlib
import unittest

# The shared base class; the package name has a hyphen, so import it by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
CheckerTestCase, NOT_CHECKED = _edges.CheckerTestCase, _edges.NOT_CHECKED


class TestNarrowFormat(CheckerTestCase):
    def test_number_starting_a_line_is_checked(self):
        self.summary({"count": 3})
        reports = (["Intro.", "", "412. more text"], ["- 412. text"], ["> 412. text"])
        for body in reports:
            with self.subTest(body=body):
                code, output = self.run_check([*body, *NOT_CHECKED])
                self.assertEqual(code, 1, output)
                self.assertIn(": 412 is not", output)

    def test_headings_numbered_in_order_are_skipped(self):
        # 1, 2 and 3 are not readings, so the pass depends on the heading exemption.
        self.summary({"count": 7})
        code, output = self.run_check(["# Title", "## 1. A", "### 1. Sub", "### 2. Sub",
                                       "## 2. B", "### 1. Sub", "## Plain", "## 3. C",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_heading_number_out_of_order_is_checked(self):
        self.summary({"count": 7})
        with self.subTest(body="412"):
            code, output = self.run_check(["## 412. A", *NOT_CHECKED])
            self.assertEqual(code, 1, output)
            self.assertIn(": 412 is not", output)

        with self.subTest(body="1, 3, 3"):
            # The marker is line 1, so "## 3. B" is line 3; "## 3. C" is the third
            # numbered heading and keeps its exemption.
            code, output = self.run_check(["## 1. A", "## 3. B", "## 3. C", *NOT_CHECKED])
            self.assertEqual(code, 1, output)
            self.assertEqual(output.count(": 3 is not"), 1, output)
            self.assertIn("line 3: 3 is not", output)

    def test_quoted_heading_number_is_checked(self):
        self.summary({"count": 7})
        code, output = self.run_check(["> ## 2. Quoted", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn(": 2 is not", output)

    def test_clean_report_passes(self):
        # No false alarm on a report written in the narrowed format.
        self.summary({"count": 41, "trend": "rising", "first_half": 7, "second_half": 34})
        code, output = self.run_check([
            "# Title",
            "| # | Name | Count |",
            "|---|---|---|",
            "| 1 | a | 41 |",
            "| 2 | b | 7 |",
            "## 1. A",
            "- **weight:** high",
            "## 2. B",
            "## Known noise",
            "```powershell",
            'Set-Location "C:\\x"',
            "```",
            *NOT_CHECKED,
        ])
        self.assertEqual(code, 0, output)

    def test_numbered_list_numbers_are_numbers(self):
        self.summary({"count": 3})
        code, output = self.run_check(["1. first", "2. second", *NOT_CHECKED])
        self.assertEqual(code, 1, output)


if __name__ == "__main__":
    unittest.main()

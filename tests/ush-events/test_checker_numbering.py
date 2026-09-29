"""Numbers at the start of a line are checked like any number (invented data only)."""

import importlib
import unittest

# The shared base class; the package name has a hyphen, so import it by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
CheckerTestCase, NOT_CHECKED = _edges.CheckerTestCase, _edges.NOT_CHECKED


class TestNumberInsideItemOrQuote(CheckerTestCase):
    def test_number_continuing_an_item_is_checked(self):
        self.summary({"count": 7})
        code, output = self.run_check(["- The service restarted", "  412. times", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_number_continuing_a_quote_is_checked(self):
        self.summary({"count": 7})
        code, output = self.run_check(["> Error text", "> 412. retries", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_quoted_text_line_is_not_blank(self):
        self.summary({"count": 7})
        code, output = self.run_check(["> Intro", "> more", "> 412. retries", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)


class TestConsecutiveNumbers(CheckerTestCase):
    def test_paragraph_number_does_not_start_a_list(self):
        self.summary({"count": 7})
        code, output = self.run_check(["Some text", "412. more", "413. more", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn(": 413 is not", output)


class TestHeadingCount(CheckerTestCase):
    # 1 and 2 are not readings, so each pass depends on the heading exemption.
    def test_comment_in_a_code_block_does_not_restart_the_count(self):
        self.summary({"count": 7})
        code, output = self.run_check(["## 1. A", "```powershell", "# 1. step", "# note",
                                       "```", "## 2. B", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_unnumbered_higher_heading_restarts_the_count(self):
        self.summary({"count": 7})
        code, output = self.run_check(["## A", "### 1. x", "### 2. y", "## B", "### 1. z",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestTable(CheckerTestCase):
    def test_dash_row_is_a_data_row(self):
        self.summary({"count": 7})
        code, output = self.run_check(["| # | Value |", "|---|---|", "| 1 | a |", "| - | - |",
                                       "| 3 | c |", *NOT_CHECKED])
        self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()

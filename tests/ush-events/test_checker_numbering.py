"""When a number at the start of a line is list numbering (invented data only)."""

import importlib
import unittest

# The shared base class; the package name has a hyphen, so import it by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
CheckerTestCase, NOT_CHECKED = _edges.CheckerTestCase, _edges.NOT_CHECKED


class TestListStartsAfterParagraph(CheckerTestCase):
    def test_list_starting_at_one_may_follow_a_paragraph(self):
        # CommonMark lets only a list starting at 1 interrupt a paragraph.
        self.summary({"count": 7})
        code, output = self.run_check(["Steps:", "1. Export the log", "2. Read it back",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_lazy_continuation_keeps_the_list(self):
        self.summary({"count": 7})
        code, output = self.run_check(["", "1. First", "wrapped text", "2. Second",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_list_after_thematic_break(self):
        self.summary({"count": 7})
        code, output = self.run_check(["Some text.", "---", "2. Next steps", *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestNumberInsideItemOrQuote(CheckerTestCase):
    def test_number_continuing_an_item_is_checked(self):
        self.summary({"count": 7})
        code, output = self.run_check(["1. The service restarted", "   412. times", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_number_continuing_a_quote_is_checked(self):
        self.summary({"count": 7})
        code, output = self.run_check(["> Error text", "> 412. retries", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_quoted_list_items_keep_their_numbers(self):
        self.summary({"count": 7})
        code, output = self.run_check(["", "> 1. first", "> 2. second", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_blank_quote_line_ends_the_paragraph(self):
        # "> " alone is a blank line inside the quote: a list may start after it.
        self.summary({"count": 7})
        for blank in (">", "> ", "> >"):
            with self.subTest(blank=blank):
                code, output = self.run_check(["> Intro", blank, "> 3. third", *NOT_CHECKED])
                self.assertEqual(code, 0, output)

    def test_quoted_text_line_is_not_blank(self):
        self.summary({"count": 7})
        code, output = self.run_check(["> Intro", "> more", "> 412. retries", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)


class TestSiblingItems(CheckerTestCase):
    def test_paragraph_number_does_not_start_a_list(self):
        self.summary({"count": 7})
        code, output = self.run_check(["Some text", "412. more", "413. more", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn(": 413 is not", output)

    def test_right_aligned_numbers_are_siblings(self):
        self.summary({"count": 7})
        code, output = self.run_check(["", " 9. a", "10. b", "", ">1. c", "> 2. d",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestTableAndQuotedHeading(CheckerTestCase):
    def test_dash_row_is_a_data_row(self):
        self.summary({"count": 7})
        code, output = self.run_check(["| # | Value |", "|---|---|", "| 1 | a |", "| - | - |",
                                       "| 3 | c |", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_quoted_heading_number_is_exempt(self):
        self.summary({"count": 7})
        code, output = self.run_check(["> ## 2. Title", *NOT_CHECKED])
        self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()

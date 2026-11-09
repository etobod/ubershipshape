"""Where the not-checked marker may stand relative to a heading (invented data only)."""

import importlib
import unittest

from tests.report_summary import report_line

# The shared base class; the package name has a hyphen, so import it by string.
CheckerTestCase = importlib.import_module("tests.ush-events.test_checker_edges").CheckerTestCase

B3 = "`" * 3


class TestMarkerNextToHeading(CheckerTestCase):
    def test_indented_code_line_is_not_a_heading(self):
        # Four spaces make an indented code line, not a heading.
        self.summary({})
        code, output = self.run_check(["<!-- ush:not-checked -->", "    ## Not checked",
                                       "Nothing."])
        self.assertEqual(code, 2, output)
        self.assertIn("not-checked", output)

    def test_code_block_between_marker_and_heading_is_rejected(self):
        self.summary({})
        code, output = self.run_check(["<!-- ush:not-checked -->", B3, "powercfg /a", B3,
                                       "## Not checked", "Nothing."])
        self.assertEqual(code, 2, output)
        self.assertIn("not-checked", output)

    def test_heading_indented_three_spaces_counts(self):
        self.summary({})
        code, output = self.run_check(["<!-- ush:not-checked -->", "   ## Not checked",
                                       "Nothing."])
        self.assertEqual(code, 0, output)


class TestCodeBlockInListItem(CheckerTestCase):
    def test_block_cannot_outlive_its_list_item(self):
        # A renderer ends the block with its list item, so the 412 is visible text.
        self.summary({"count": 3})
        body = ["- Fix:", "  " + B3, "  reg add 4096", "- There were 412 events.",
                "  " + B3, *NOT_CHECKED]
        code, output = self.run_check(body)
        self.assertEqual(code, 2, output)
        # The 412 line, moved down by the summary section above the intro (plan 055).
        line = report_line(["<!-- ush:summary -->", *body], 4, "ush-events")
        self.assertIn(f"line {line}", output)

    def test_block_indented_with_its_item_passes(self):
        self.summary({"count": 3})
        code, output = self.run_check(["- There were 3 events:", "  " + B3, "  reg add 4096",
                                       "", "  cmd 1024", "  " + B3, *NOT_CHECKED])
        self.assertEqual(code, 0, output)


NOT_CHECKED = ["<!-- ush:not-checked -->", "## Not checked", "Nothing."]


if __name__ == "__main__":
    unittest.main()

"""Long lists and fences after a list marker (invented data only)."""

import importlib
import threading
import unittest

# The shared base class; the package name has a hyphen, so import it by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
CheckerTestCase, NOT_CHECKED = _edges.CheckerTestCase, _edges.NOT_CHECKED

B3 = "`" * 3


class TestLongLists(CheckerTestCase):
    def test_numbers_after_text_finish_quickly(self):
        # Every numbered line here is paragraph text; each used to repeat the
        # whole search above it, doubling the run time per line. A daemon
        # thread with a timeout makes a return of that fail, not hang.
        self.summary({"count": 3})
        body = ["Top days:"] + [f"{n}. day" for n in range(2, 42)]
        result = []
        worker = threading.Thread(
            target=lambda: result.append(self.run_check([*body, *NOT_CHECKED])), daemon=True)
        worker.start()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "the check did not finish in 10 s")
        code, output = result[0]
        self.assertEqual(code, 1, output)
        self.assertIn(": 41 is not", output)

    def test_very_long_list_is_checked(self):
        self.summary({"count": 3})
        body = [f"{n}. item" for n in range(1, 1501)]
        code, output = self.run_check([*body, *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestListIndent(CheckerTestCase):
    def test_number_indented_four_or_more_is_checked(self):
        self.summary({"count": 3})
        for case, line in {"four spaces": "    412. events were logged",
                           "tab": "\t412. events were logged",
                           "non-breaking space": "\u00a0412. events were logged"}.items():
            with self.subTest(case=case):
                code, output = self.run_check(["Intro", "", line, *NOT_CHECKED])
                self.assertEqual(code, 1, output)
                self.assertIn(": 412 is not", output)

    def test_nested_list_within_three_spaces_is_numbering(self):
        self.summary({"count": 3})
        code, output = self.run_check(["1. Steps:", "   1. open", "   2. run", "2. Done",
                                       "", "> 1. quoted", "> 2. quoted", *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestNonBreakingSpace(CheckerTestCase):
    def test_non_breaking_space_is_not_markdown_whitespace(self):
        self.summary({"count": 3})
        cases = {"after the delimiter": ["Intro", "", "412. events"],
                 "after the heading hashes": ["# 412. events"],
                 "as a blank line": ["Text", " ", "412. events"]}
        for case, body in cases.items():
            with self.subTest(case=case):
                code, output = self.run_check([*body, *NOT_CHECKED])
                self.assertEqual(code, 1, output)
                self.assertIn(": 412 is not", output)


class TestTextColumn(CheckerTestCase):
    def test_sibling_left_of_text_after_wide_gap(self):
        # "1.  a" puts its text at column 4, so "   2. b" stands left of it.
        self.summary({"count": 3})
        code, output = self.run_check(["1.  a", "   2. b", *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestFenceAfterMarker(CheckerTestCase):
    def test_inline_code_after_a_marker_is_accepted(self):
        self.summary({"count": 3})
        code, output = self.run_check(["- " + B3 + "x" + B3 + " inline", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_fence_on_a_list_marker_line_is_rejected(self):
        self.summary({"count": 3})
        for marker in ("- ", "1. ", "* "):
            with self.subTest(marker=marker):
                code, output = self.run_check([
                    "Fix:", marker + B3 + "powershell", "  cmd1", "  " + B3,
                    "  There were 412 events.", "", "  " + B3 + "powershell", "  cmd2",
                    "  " + B3, *NOT_CHECKED])
                self.assertEqual(code, 2, output)

    def test_fence_below_the_marker_is_accepted(self):
        self.summary({"count": 3})
        code, output = self.run_check(["- Fix:", "  " + B3 + "powershell", "  cmd 412",
                                       "  " + B3, "- There were 3 events.", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

class TestNestedListDelimiter(CheckerTestCase):
    def test_outer_item_after_nested_list_with_other_delimiter(self):
        self.summary({"count": 3})
        code, output = self.run_check(["1. a", "   1) sub", "   2) sub", "2. b", *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestUnderlineAfterListOrQuote(CheckerTestCase):
    def test_equals_line_after_list_item_or_quote_is_text(self):
        self.summary({"count": 3})
        for above in (["- a"], ["> a"], ["- a", "  b"], ["> a", "b"]):
            with self.subTest(above=above):
                code, output = self.run_check([*above, "===", "412. x", *NOT_CHECKED])
                self.assertEqual(code, 1, output)
                self.assertIn(": 412 is not", output)


class TestNumberOpeningAContainer(CheckerTestCase):
    def test_number_in_a_new_quote_or_after_a_bullet_is_numbering(self):
        self.summary({"count": 3})
        for line in ("> 412. x", "- 412. x", "> - 412. x"):
            with self.subTest(line=line):
                code, output = self.run_check(["Summary:", line, *NOT_CHECKED])
                self.assertEqual(code, 0, output)

    def test_number_in_the_same_quote_after_text_is_checked(self):
        self.summary({"count": 3})
        for above in (["> Summary:"], ["> Summary:", "text"], [">> a", "> b"]):
            with self.subTest(above=above):
                marker = ">" * max(line.count(">") for line in above)
                code, output = self.run_check([*above, f"{marker} 412. x", *NOT_CHECKED])
                self.assertEqual(code, 1, output)
                self.assertIn(": 412 is not", output)


class TestBlankLineInsideItem(CheckerTestCase):
    def test_item_after_a_second_paragraph_is_numbering(self):
        self.summary({"count": 3})
        for body in (["   more text"], ["   - sub"], ["   more", "", "   again"]):
            with self.subTest(body=body):
                code, output = self.run_check(["1. first", "", *body, "412. second",
                                               *NOT_CHECKED])
                self.assertEqual(code, 0, output)

    def test_number_after_an_unindented_paragraph_is_checked(self):
        self.summary({"count": 3})
        code, output = self.run_check(["1. first", "", "text", "412. x", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn(": 412 is not", output)


if __name__ == "__main__":
    unittest.main()

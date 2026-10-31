"""Report check: HTML comments are allowed only on the ush: marker lines (invented data only)."""

import importlib
import json
import unittest

# The shared base class; the package name has a hyphen, so import it by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
CheckerTestCase, NOT_CHECKED = _edges.CheckerTestCase, _edges.NOT_CHECKED

B3 = "`" * 3

# Every number in the text (3) is a reading of the summary, and its only group id is named.
SUMMARY = {"count": 3, "groups": [{"id": "g1", "provider": "Invented-Provider",
                                   "event_id": 7, "count": 3}], "truncated": 0}
INTRO = ["# Event log review", "There were 3 events.", "Errors from Invented-Provider (g1)."]


class MarkerTestCase(CheckerTestCase):
    def setUp(self):
        super().setUp()
        self.summary(SUMMARY)
        (self.root / "detail.json").write_text(json.dumps(
            {"groups": [{"id": "g1", "provider": "Invented-Provider", "event_id": 7,
                         "count": 3}]}), encoding="utf-8")

    def assert_comment_rejected(self, code, output, line_no):
        self.assertEqual(code, 2, output)
        self.assertIn(f"line {line_no} has an HTML comment", output)
        self.assertIn("&lt;!--", output)


class TestMarkerLinesPass(MarkerTestCase):
    def test_marker_lines_pass(self):
        code, output = self.run_check([
            *INTRO,
            "<!-- ush:detail g1 -->",
            "Group g1 had 3 events.",
            "",
            *NOT_CHECKED,
        ])
        self.assertEqual(code, 0, output)
        self.assertIn("OK", output)


class TestCommentOutsideMarkers(MarkerTestCase):
    def test_comment_outside_markers_is_rejected(self):
        cases = [
            "<!-- note -->",
            "Text <!-- g2 --> more",
            "Text <!-- open",
            "C:\\<!-- x -->",
            "C:\\\\<!-- x -->",  # a literal double backslash
            "Payload `<!-- g2 -->`",
            "> Sample <!-- x -->",
            "- item <!-- x -->",
            "<!-- ush:detail g1 --> tail <!-- x -->",
            "- <!-- ush:detail g2 -->",
            "> <!-- ush:not-checked -->",
        ]
        # Line 1 is the summary marker; INTRO fills lines 2-4; the case is line 5.
        line_no = 1 + len(INTRO) + 1
        for line in cases:
            with self.subTest(line=line):
                code, output = self.run_check([*INTRO, line, "", *NOT_CHECKED])
                self.assert_comment_rejected(code, output, line_no)

        with self.subTest(line="summary marker followed by another comment on line 1"):
            path = self.root / "reports" / "events-2026-09-28-1300.md"
            first = f"<!-- ush:summary {self.summary_file} --> <!-- x -->"
            path.write_text("\n".join([first, *INTRO, *NOT_CHECKED]) + "\n", encoding="utf-8")
            code, output = self.run_argv([str(path)])
            self.assert_comment_rejected(code, output, 1)


class TestCommentTextAllowedWhereInert(MarkerTestCase):
    def test_comment_text_in_code_block_or_entity_passes(self):
        with self.subTest(case="comment opener inside a fenced code block"):
            code, output = self.run_check([*INTRO, B3, "<!-- note -->", "<!-- open", B3,
                                           "", *NOT_CHECKED])
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest(case="entity-escaped comment opener in plain text"):
            code, output = self.run_check([*INTRO, "Write &lt;!-- to show a comment opener.",
                                           "", *NOT_CHECKED])
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)


if __name__ == "__main__":
    unittest.main()

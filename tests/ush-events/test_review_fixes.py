"""Cases found in the final review of the report check and boot types (invented data only)."""

import contextlib
import importlib
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

# The shared helpers; the package name has a hyphen, so import them by string.
_edges = importlib.import_module("tests.ush-events.test_checker_edges")
_fast = importlib.import_module("tests.ush-events.test_fast_startup")
CheckerTestCase = _edges.CheckerTestCase
NOT_CHECKED = _edges.NOT_CHECKED

B3 = "`" * 3


class TestTabIndentInCodeBlock(CheckerTestCase):
    def test_tab_counts_as_indent(self):
        # A tab reaches column 4, past the item's 2 spaces: the line is in the block.
        self.summary({"count": 3})
        code, output = self.run_check(["- There were 3 events:", "  " + B3, "\treg add 4096",
                                       "  " + B3, *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestUnreadBootType(unittest.TestCase):
    def setUp(self):
        self.events = load_script("ush-events", "events")

    def summary_of(self, events):
        analysis = self.events.analyze(events, [])
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            return self.events.build_summary(
                now, 7, [], analysis, [],
                Path(tmp) / "summary.json", Path(tmp) / "detail.json",
            )

    def test_unread_boot_type_is_reported(self):
        events = _fast.boot_markers("2026-09-20", "08", "0") + [
            _fast.boot_type_event("2026-09-20T13:00:01+02:00", "7"),
        ]
        summary = self.summary_of(events)
        self.assertEqual(len(summary["not_checked"]), 1, summary["not_checked"])
        item = summary["not_checked"][0]
        self.assertIn("Kernel-Boot 27", item["what"])
        self.assertTrue(item["what"].startswith("1 "), item["what"])

    def test_readable_boot_types_report_nothing(self):
        events = _fast.boot_markers("2026-09-20", "08", "0") + [
            _fast.boot_type_event("2026-09-20T13:00:01+02:00", "2"),
        ]
        self.assertEqual(self.summary_of(events)["not_checked"], [])


class TestDetailFileNotAnObject(unittest.TestCase):
    def test_list_in_detail_file_is_a_message_not_a_traceback(self):
        events = load_script("ush-events", "events")
        with tempfile.TemporaryDirectory() as tmp:
            detail = Path(tmp) / "detail.json"
            detail.write_text("[]", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = events.main(["--data-dir", tmp, "--detail", "g1",
                                    "--detail-file", str(detail)])
        self.assertEqual(code, 1)
        self.assertIn("detail.json", err.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Edge cases of the report check found in review (invented data only)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script


class CheckerTestCase(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-events", "check_report")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "reports").mkdir()
        self.summary_file = self.root / "summary.json"

    def summary(self, data):
        data = {**data, "summary_file": str(self.summary_file),
                "detail_file": str(self.root / "detail.json")}
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

    def run_check(self, body, name="events-2026-09-28-1200.md"):
        path = self.root / "reports" / name
        path.write_text("\n".join([f"<!-- ush:summary {self.summary_file} -->", *body]) + "\n",
                        encoding="utf-8")
        return self.run_argv([str(path)])

    def run_argv(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.check.main(argv)
        return code, out.getvalue()


NOT_CHECKED = ["<!-- ush:not-checked -->", "## Not checked", "Nothing."]


class TestHexAndDecimalApart(CheckerTestCase):
    def test_hex_value_does_not_back_a_decimal(self):
        self.summary({"bugcheck_code": "0x0000019c"})
        code, output = self.run_check(["There were 412 events.", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_decimal_value_does_not_back_a_hex(self):
        self.summary({"event_id": 65})
        code, output = self.run_check(["Code 0x41.", *NOT_CHECKED])
        self.assertEqual(code, 1, output)

    def test_hex_backs_hex(self):
        self.summary({"bugcheck_code": "0x0000019c"})
        code, output = self.run_check(["Bugcheck 0x19C.", *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestCodeBlocks(CheckerTestCase):
    def test_command_constants_are_not_checked(self):
        self.summary({"count": 3})
        code, output = self.run_check(
            ["There were 3 events.", "```", "reg add HKLM /v Y /d 4096", "```",
             *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_numbers_after_the_block_are_checked_again(self):
        self.summary({"count": 3})
        code, output = self.run_check(["```", "powercfg /a", "```", "There were 412 events.",
                                       *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)


class TestUnclosedCodeBlock(CheckerTestCase):
    def test_unclosed_block_cannot_hide_numbers(self):
        self.summary({"count": 3})
        code, output = self.run_check(["```", "powercfg /a", "There were 412 events.",
                                       *NOT_CHECKED])
        self.assertEqual(code, 2, output)

    def test_other_fence_inside_a_block_does_not_close_it(self):
        self.summary({"count": 3})
        code, output = self.run_check(["```", "~~~", "cmd 4096", "```", "There were 3 events.",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)


class TestMarkerInCodeBlock(CheckerTestCase):
    def test_marker_inside_a_code_block_does_not_count(self):
        self.summary({"count": 3})
        code, output = self.run_check(["There were 3 events.", "```", *NOT_CHECKED, "```"])
        self.assertEqual(code, 2, output)


class TestPathsSupplyNoNumbers(CheckerTestCase):
    def test_digits_in_file_paths_do_not_back_numbers(self):
        # Only the file paths contain a 7; the readings do not.
        self.summary_file = self.root / "run7" / "summary.json"
        self.summary_file.parent.mkdir()
        self.summary({"count": 3})
        code, output = self.run_check(["There were 7 events.", *NOT_CHECKED])
        self.assertEqual(code, 1, output)


class TestNotCheckedPosition(CheckerTestCase):
    def test_marker_after_heading_passes(self):
        self.summary({})
        code, output = self.run_check(["## Not checked", "<!-- ush:not-checked -->", "Nothing."])
        self.assertEqual(code, 0, output)

    def test_marker_away_from_a_heading_is_rejected(self):
        self.summary({})
        code, output = self.run_check(["Some text.", "<!-- ush:not-checked -->", "More text.",
                                       "## Not checked", "Nothing."])
        self.assertEqual(code, 2, output)
        self.assertIn("not-checked", output)


class TestLatestIgnoresOtherSkills(CheckerTestCase):
    def test_other_skill_report_is_not_picked(self):
        self.summary({})
        self.run_check(NOT_CHECKED, name="events-2026-09-28-1200.md")
        (self.root / "reports" / "updates-2026-09-29-0800.md").write_text(
            "not an events report\n", encoding="utf-8")
        code, output = self.run_argv(["--latest", "--data-dir", str(self.root)])
        self.assertEqual(code, 0, output)
        self.assertIn("events-2026-09-28-1200.md", output)


if __name__ == "__main__":
    unittest.main()

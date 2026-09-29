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


B3 = "`" * 3
B4 = "`" * 4


class TestCommonMarkFences(CheckerTestCase):
    def test_shorter_fence_does_not_close_a_longer_one(self):
        # B4 block holds a B3 line; the number sits between two closed B4 blocks.
        self.summary({"count": 3})
        code, output = self.run_check([B4, B3, B4, "There were 412 events.", B4, B3, B4,
                                       *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_fence_with_trailing_text_does_not_close(self):
        self.summary({"count": 3})
        code, output = self.run_check(["There were 3 events.", B3, "powercfg /a",
                                       B3 + " text", "cmd 4096", *NOT_CHECKED])
        self.assertEqual(code, 2, output)
        self.assertIn("never closed", output)

    def test_indented_four_spaces_is_not_a_fence(self):
        self.summary({"count": 3})
        code, output = self.run_check(["    " + B3, "    There were 412 events.", "    " + B3,
                                       *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_info_string_opens_and_longer_fence_closes(self):
        self.summary({"count": 3})
        code, output = self.run_check(["There were 3 events.", B3 + "powershell",
                                       "reg add HKLM /v Y /d 4096", B4, *NOT_CHECKED])
        self.assertEqual(code, 0, output)

        code, output = self.run_check([B3 + "powershell", "reg add HKLM /v Y /d 4096", B4,
                                       "There were 412 events.", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_deeply_indented_fence_is_checked(self):
        # A block in a nested list item is not recognised (report-format.md forbids it),
        # so its constants are checked like any text.
        self.summary({"count": 3})
        code, output = self.run_check(["- There were 3 events.", "  - nested item",
                                       "     " + B3, "     cmd 4096", "     " + B3,
                                       *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("4096", output)


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


class TestIdsSupplyNoNumbers(CheckerTestCase):
    def test_group_id_does_not_back_a_count(self):
        # g17 is an id, not a reading; no count is 17.
        groups = [{"id": f"g{i}", "count": 1000 + i} for i in range(1, 26)]
        self.summary({"groups": groups, "truncated": 0})
        named = "Groups: " + ", ".join(group["id"] for group in groups) + "."
        code, output = self.run_check(["There were 17 critical errors.", named, *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn(": 17 is not", output)

    def test_known_ids_are_skipped(self):
        self.summary({"groups": [{"id": "g6", "count": 11}, {"id": "g22", "count": 2}],
                      "truncated": 0})
        code, output = self.run_check(["Wi-Fi: g6: 11, g22: 2", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_unknown_id_shape_is_a_number(self):
        quote = "> Sample: adapter b2 lost the link."
        # b2 is not an id of any summary item and 2 is not a reading.
        self.summary({"groups": [{"id": "g1", "count": 4}], "truncated": 0})
        code, output = self.run_check([quote, "Group g1.", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn(": 2 is not", output)

        # With 2 among the readings the same token is backed.
        self.summary({"groups": [{"id": "g1", "count": 2}], "truncated": 0})
        code, output = self.run_check([quote, "Group g1.", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_truncated_group_ids_are_known(self):
        # Two groups listed, three cut off: g3..g5 are known ids, g6 is not.
        self.summary({"groups": [{"id": "g1", "count": 4}, {"id": "g2", "count": 7}],
                      "truncated": 3})
        code, output = self.run_check(["Group g5 was cut from the summary.", "Groups g1 and g2.",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)

        code, output = self.run_check(["Group g6 was cut from the summary.", "Groups g1 and g2.",
                                       *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn(": 6 is not", output)


class TestNumberingExemptions(CheckerTestCase):
    def test_table_first_cell_must_be_its_position(self):
        self.summary({"event_id": 41})
        header = ["| # | Event |", "|---|---|"]
        code, output = self.run_check([*header, "| 412 | Kernel-Power 41 |", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

        code, output = self.run_check([*header, "| 1 | Kernel-Power 41 |",
                                       "| 2 | Kernel-Power 41 |", *NOT_CHECKED])
        self.assertEqual(code, 0, output)

    def test_list_number_mid_paragraph_is_checked(self):
        self.summary({"count": 3})
        code, output = self.run_check(["Some text", "412. more text", *NOT_CHECKED])
        self.assertEqual(code, 1, output)
        self.assertIn("412", output)

    def test_bullets_and_heading_keep_exemption(self):
        self.summary({"count": 4})
        code, output = self.run_check(["Intro.", "", "- text", "  continued text", "- next",
                                       "", "A plain paragraph line.", "## 1. Title",
                                       *NOT_CHECKED])
        self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()

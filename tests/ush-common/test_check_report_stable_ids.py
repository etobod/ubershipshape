"""Shared report check: ids cut from the summary come from the detail file (plan 108 M2).

Item ids are stable between runs, so the id of an item cut from a summary list no
longer follows from its position. The checker takes the cut ids from the detail
file. All data below is invented; the profile lives in a temporary skills directory.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

REPO = Path(__file__).resolve().parents[2]
SUMMARY_CONTRACT = REPO / "skills" / "ush-common" / "references" / "summary-contract.md"

NOT_CHECKED = ["## Not checked", "<!-- ush:not-checked -->", "Nothing."]
DETAIL_NAME = "invented-run.detail.json"

# The temporary path ends up in the summary (summary_file, detail_file): it must
# hold no digit 4 and nothing shaped like an x id.
UNSAFE_PATH = re.compile(r"4|x\d")


def _profile():
    return {
        "detail_sections": ["additions", "own"],
        "id_letters": "x",
        "path_keys": ["detail_file", "summary_file"],
        "id_keys": ["id"],
        "required_lists": ["additions"],
        "truncated": [{"list": "additions", "prefix": "x",
                       "count_key": "truncated_additions"}],
        "report_prefix": "test-",
    }


def _listed():
    return [{"id": "x3", "name": "alpha"}, {"id": "x7", "name": "beta"}]


def _detail():
    # x12 and x15 were cut from the summary; x20 is an own item never listed.
    return {
        "additions": [*_listed(), {"id": "x12", "name": "gamma"},
                      {"id": "x15", "name": "delta"}],
        "own": [{"id": "x20", "name": "epsilon"}],
    }


def _clean_temp_dir():
    for _ in range(50):
        tmp = tempfile.TemporaryDirectory()
        if not UNSAFE_PATH.search(str(Path(tmp.name).resolve())):
            return tmp
        tmp.cleanup()
    raise AssertionError("every temporary directory holds a 4 or an x id")


class TestStableIds(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _clean_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.summary_file = self.work_dir / "invented-run.summary.json"
        self.detail_file = self.work_dir / DETAIL_NAME

        self.skills_dir = self.root / "skills"
        patcher = mock.patch.object(self.check, "SKILLS_DIR", self.skills_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        profile_path = self.skills_dir / "ush-test" / "data" / "report-profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(json.dumps(_profile()), encoding="utf-8")

    def write_summary(self, cut):
        data = {
            "skill": "ush-test",
            "summary_file": str(self.summary_file),
            "detail_file": str(self.detail_file),
            "additions": _listed(),
            "truncated_additions": cut,
        }
        text = json.dumps(data)
        self.summary_file.write_text(text, encoding="utf-8")
        return text

    def write_detail(self):
        self.detail_file.write_text(json.dumps(_detail()), encoding="utf-8")

    def run_report(self, body, name):
        path = self.reports_dir / name
        first = f"<!-- ush:summary {self.summary_file} -->"
        path.write_text("\n".join([first, *body]) + "\n", encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(path)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_cut_ids_from_detail_file(self):
        named = "Additions x3 and x7."
        cut_line = "Addition x12 was cut from the summary."

        summary_text = self.write_summary(2)
        self.assertNotIn("4", summary_text, "no value of the summary may hold a 4")
        self.write_detail()

        with self.subTest("x12 is a cut id found in the detail file"):
            code, output = self.run_report(
                ["# Test report", named, cut_line, *NOT_CHECKED], "cut-x12.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("x4 follows the list by position but is in no detail section"):
            code, output = self.run_report(
                ["# Test report", named, "Addition x4 was cut from the summary.",
                 *NOT_CHECKED], "cut-positional.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)

        with self.subTest("x20 of a detail section, never on the list, is known"):
            code, output = self.run_report(
                ["# Test report", named, "Addition x20 is an own item.", *NOT_CHECKED],
                "own-item.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("cut count above 0 without the detail file"):
            self.detail_file.unlink()
            code, output = self.run_report(
                ["# Test report", named, cut_line, *NOT_CHECKED], "cut-no-detail.md")
            self.assertEqual(code, 2, output)
            self.assertNotIn("OK", output)
            self.assertIn(DETAIL_NAME, output)

        with self.subTest("cut count 0 does not read the missing detail file"):
            self.assertFalse(self.detail_file.exists())
            self.write_summary(0)
            code, output = self.run_report(
                ["# Test report", named, *NOT_CHECKED], "no-cut.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("the shared contract no longer describes the positional range"):
            text = SUMMARY_CONTRACT.read_text(encoding="utf-8")
            self.assertNotIn("<prefix><N+1>", text)


if __name__ == "__main__":
    unittest.main()

"""Shared report check: digits in path-shaped JSON keys back no number (invented data only).

A key like ``facts[C:\\Invented42\\tray.exe].signer`` supplies no numbers from its
own text, but its value is read like any other value. When the field after the
last ``].`` is a skip key of the profile (path_keys or id_keys), the value is
skipped as well.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOT_CHECKED = ["## Not checked", "<!-- ush:not-checked -->", "Nothing."]

PATH_KEY = "facts[C:\\Invented42\\tray.exe]"
BARE_KEY = "facts[invented32.exe]"

# The profile's path_keys and id_keys, as the checker would combine them.
SKIP_KEYS = frozenset({"detail_file", "summary_file", "program", "id"})


def _profile():
    """An invented profile; "program" is a path key, so its value backs nothing."""
    return {
        "detail_sections": ["things"],
        "id_letters": "c",
        "path_keys": ["detail_file", "summary_file", "program"],
        "id_keys": ["id"],
        "required_lists": [],
        "truncated": None,
        "report_prefix": "test-",
    }


def _change(fields):
    return {"id": "c1", "source": "autostart", "change": "changed", "fields": fields}


def _path_summary():
    """One change on a fact keyed by a full path with digits in the folder name."""
    return {
        "change_count": 1,
        "changes": [_change({
            f"{PATH_KEY}.signer": {"before": "Invented Soft 7", "after": "Example Soft"},
            f"{PATH_KEY}.description": {"before": "Tray helper", "after": "Tray helper 58"},
            f"{PATH_KEY}.program": {"before": "InventedProg_9431",
                                    "after": "InventedProg_9431"},
        })],
    }


def _bare_summary():
    """One change on a fact keyed by a file name without a folder."""
    return {
        "change_count": 1,
        "changes": [_change({
            f"{BARE_KEY}.signer": {"before": "Invented Soft 7", "after": "Example Soft"},
            f"{BARE_KEY}.program": {"before": "InventedProg_9431", "after": "InventedApp"},
        })],
    }


def _numbers(tokens):
    return {value for _kind, value in tokens}


class TestBackslashKeys(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        # The temp path must not hold the numbers asserted in the output; a random
        # name that does is replaced; a temp folder that always does skips the test.
        for _ in range(20):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.root = Path(tmp.name).resolve()
            if not any(number in str(self.root) for number in ("42", "32", "9431")):
                break
        else:
            self.skipTest("the temp folder path holds a number these tests assert on")
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.summary_file = self.work_dir / "summary.json"
        self.detail_file = self.work_dir / "detail.json"
        self.detail_file.write_text(json.dumps({"things": []}), encoding="utf-8")

        self.skills_dir = self.root / "skills"
        patcher = mock.patch.object(self.check, "SKILLS_DIR", self.skills_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        profile_path = self.skills_dir / "ush-test" / "data" / "report-profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(json.dumps(_profile()), encoding="utf-8")

    def write_summary(self, data):
        data = dict(data)
        data["skill"] = "ush-test"
        data["summary_file"] = str(self.summary_file)
        data["detail_file"] = str(self.detail_file)
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

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

    def test_value_of_path_keyed_field_backs_numbers(self):
        summary = _path_summary()
        self.write_summary(summary)

        with self.subTest("json_values reads the values of backslash keys"):
            numbers = _numbers(self.check.json_values(summary, SKIP_KEYS))
            self.assertIn(7, numbers)
            self.assertIn(58, numbers)

        with self.subTest("number from before"):
            code, output = self.run_report(
                ["# Test report",
                 "The signer of the tray program changed from Invented Soft 7 to Example Soft.",
                 *NOT_CHECKED], "from-before.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("number from after"):
            code, output = self.run_report(
                ["# Test report",
                 "The description of the tray program is now Tray helper 58.",
                 *NOT_CHECKED], "from-after.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

    def test_digits_of_path_key_back_no_number(self):
        summary = _path_summary()
        self.write_summary(summary)

        with self.subTest("json_values takes no number from the key text"):
            self.assertNotIn(42, _numbers(self.check.json_values(summary, SKIP_KEYS)))

        with self.subTest("the checker reports 42 as not backed"):
            code, output = self.run_report(
                ["# Test report", "The tray program sits in folder Invented 42.",
                 *NOT_CHECKED], "path-digits.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)
            self.assertIn("42", output)

    def test_value_of_path_key_field_backs_no_number(self):
        summary = _path_summary()
        self.write_summary(summary)

        with self.subTest("json_values skips the value of a path_keys field"):
            self.assertNotIn(9431, _numbers(self.check.json_values(summary, SKIP_KEYS)))

        with self.subTest("the checker reports 9431 as not backed"):
            code, output = self.run_report(
                ["# Test report", "The tray program is program 9431.", *NOT_CHECKED],
                "program-digits.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)
            self.assertIn("9431", output)

    def test_folderless_fact_key(self):
        summary = _bare_summary()
        self.write_summary(summary)

        with self.subTest("json_values: 7 backed, 32 and 9431 not"):
            tokens = self.check.json_values(summary, SKIP_KEYS)
            numbers = _numbers(tokens)
            self.assertIn(("dec", 7), tokens)
            self.assertNotIn(32, numbers)
            self.assertNotIn(9431, numbers)

        with self.subTest("7 from the signer before value passes"):
            code, output = self.run_report(
                ["# Test report",
                 "The signer changed from Invented Soft 7 to Example Soft.",
                 *NOT_CHECKED], "bare-signer.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("32 from the file name is not backed"):
            code, output = self.run_report(
                ["# Test report", "The file name carries the number 32.", *NOT_CHECKED],
                "bare-name.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)
            self.assertIn("32", output)

        with self.subTest("9431 from the program value is not backed"):
            code, output = self.run_report(
                ["# Test report", "The program was program 9431.", *NOT_CHECKED],
                "bare-program.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)
            self.assertIn("9431", output)

    def test_clean_report_passes(self):
        summary = _path_summary()
        summary["changes"].append({
            "id": "c2", "source": "autostart", "change": "changed",
            "fields": {
                f"{BARE_KEY}.signer": {"before": "Invented Soft 7", "after": "Example Soft"},
                f"{BARE_KEY}.program": {"before": "InventedProg_9431", "after": "InventedApp"},
            },
        })
        summary["change_count"] = 2
        self.write_summary(summary)

        code, output = self.run_report(
            ["# Test report",
             "There were 2 changes in autostart.",
             "The signer of the tray program changed from Invented Soft 7 to Example Soft.",
             "Its description is now Tray helper 58.",
             "The signer of the second entry also changed from Invented Soft 7.",
             *NOT_CHECKED], "clean.md")
        self.assertEqual(code, 0, output)
        self.assertIn("OK", output)


if __name__ == "__main__":
    unittest.main()

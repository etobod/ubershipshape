"""Shared report check: --contains "<text>" (plan 004, M5; invented data only).

With one or more ``--contains`` options the report must also hold each text,
or the check fails and names the missing text. Without the option the result
is the same as before. The invented profile, summary and detail file come from
``test_check_report_words``.
"""

import contextlib
import io
import unittest

from .test_check_report_words import NOT_CHECKED, _InventedProfileCase, _word_problem

TEXT = "Co możesz zrobić"
OTHER_TEXT = "Szczegóły"

WITH_TEXT = [
    "# Raport testowy",
    "",
    f"## {TEXT}",
    "Nic do zrobienia w tym przebiegu.",
    "",
    f"## {OTHER_TEXT}",
    "Brak.",
    "",
    *NOT_CHECKED,
]

WITHOUT_TEXT = [
    "# Raport testowy",
    "",
    "## Co dalej",
    "Nic do zrobienia w tym przebiegu.",
    "",
    *NOT_CHECKED,
]


class TestContains(_InventedProfileCase):
    def run_args(self, path, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(path), *extra])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def assert_fails(self, code, output):
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertFalse(any(line.startswith("OK:") for line in output.splitlines()),
                         f"no OK line expected; output:\n{output}")
        self.assertIn("FAILED", output)

    def test_contains_present_and_missing(self):
        present = self.write_report(WITH_TEXT, "test-2026-10-30-0900.md")
        missing = self.write_report(WITHOUT_TEXT, "test-2026-10-30-0910.md")

        with self.subTest("control: both reports pass today without --contains"):
            self.assert_ok(*self.run_args(present))
            self.assert_ok(*self.run_args(missing))

        with self.subTest("the text is in the report"):
            code, output = self.run_args(present, "--contains", TEXT)
            self.assert_ok(code, output)

        with self.subTest("the text is not in the report"):
            code, output = self.run_args(missing, "--contains", TEXT)
            self.assert_fails(code, output)
            self.assertIn(TEXT, output)

        with self.subTest("repeated: every text is in the report"):
            code, output = self.run_args(
                present, "--contains", TEXT, "--contains", OTHER_TEXT)
            self.assert_ok(code, output)

        with self.subTest("repeated: one text is missing and is named"):
            code, output = self.run_args(
                missing, "--contains", "Nic do zrobienia", "--contains", TEXT)
            self.assert_fails(code, output)
            self.assertIn(TEXT, output)

        with self.subTest("repeated: a missing text given first is still checked"):
            code, output = self.run_args(
                missing, "--contains", TEXT, "--contains", "Nic do zrobienia")
            self.assert_fails(code, output)
            self.assertIn(TEXT, output)

    def test_without_contains_unchanged(self):
        with self.subTest("passing report"):
            path = self.write_report(WITH_TEXT, "test-2026-10-30-0920.md")
            code, output = self.run_args(path)
            self.assert_ok(code, output)
            self.assertNotIn("FAILED", output)

        with self.subTest("failing report"):
            # Line 1 is ush:summary, line 2 the heading, line 3 the sentence.
            path = self.write_report(
                ["# Raport testowy", "Obcięto dwa sterowniki.", *NOT_CHECKED],
                "test-2026-10-30-0930.md")
            code, output = self.run_args(path)
            self.assert_fails(code, output)
            self.assertIn(_word_problem("dwa", 3), output)
            self.assertIn(f"FAILED: {path}: 1 number words", output)


if __name__ == "__main__":
    unittest.main()

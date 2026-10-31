"""Shared report check: local time pairs and skill script commands (invented data only).

A time written as ``YYYY-MM-DD HH:MM (HH:MM UTC)`` outside code blocks must match a
whole timezone-aware JSON string value: the UTC part is its hour and minute (seconds
dropped), the local part is what ``to_local`` makes of it. A time ``to_local`` cannot
convert (e.g. year 1601 on Windows) is skipped as a candidate. A skill script command
inside a fenced code block needs ``--data-dir`` with an absolute Windows path and an
earlier ``Set-Location`` line in the same block. Tests always pass a fixed zone.
"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOT_CHECKED = ["## Not checked", "<!-- ush:not-checked -->", "Nothing."]

GENERATED_AT = "2026-09-30T07:26:40+00:00"
LATE_TIME = "2026-09-30T23:30:00+00:00"
OLD_TIME = "1601-01-01T00:00:00+00:00"

FENCE = "```"
SET_LOCATION = 'Set-Location "C:\\proj"'
INVENTORY_OK = 'python -B skills/ush-inventory/scripts/inventory.py --data-dir "C:\\dane\\ush"'
INVENTORY_PLACEHOLDER = 'python -B skills/ush-inventory/scripts/inventory.py --data-dir "<dir>"'
INVENTORY_NO_DATA_DIR = "python -B skills/ush-inventory/scripts/inventory.py"
INVENTORY_EQUALS = "python -B skills/ush-inventory/scripts/inventory.py --data-dir=C:\\dane\\ush"
SETTINGS_BARE = "python skills\\ush-settings\\scripts\\settings.py --block e7"
HEALTH_QUOTED = 'python -B "C:\\proj\\skills\\ush-health\\scripts\\health.py"'


def plus_two(dt):
    """A fixed +02:00 zone, independent of the machine running the tests."""
    return dt.astimezone(timezone(timedelta(hours=2)))


def plus_two_like_windows(dt):
    """Like plus_two, but fails for years before 1970 as astimezone() does on Windows."""
    if dt.year < 1970:
        raise OSError(22, "Invalid argument")
    return plus_two(dt)


def _profile():
    return {
        "detail_sections": ["things"],
        "id_letters": "c",
        "path_keys": ["detail_file", "summary_file"],
        "id_keys": ["id"],
        "required_lists": [],
        "truncated": None,
        "report_prefix": "test-",
    }


def _block(lines, indent=""):
    return [indent + FENCE + "powershell", *(indent + line for line in lines), indent + FENCE]


class TestStyle(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        # The temp path must not hold the numbers used in the reports; a random
        # name that does is replaced; a temp folder that always does skips the test.
        guarded = ("2026", "1601", "0926", "0726", "2330", "65", "69")
        for _ in range(20):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.root = Path(tmp.name).resolve()
            if not any(number in str(self.root) for number in guarded):
                break
        else:
            self.skipTest("the temp folder path holds a number these tests use")
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

    def run_report(self, body, name, to_local=plus_two):
        path = self.reports_dir / name
        first = f"<!-- ush:summary {self.summary_file} -->"
        path.write_text("\n".join([first, "# Test report", *body, *NOT_CHECKED]) + "\n",
                        encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(path)], to_local=to_local)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def assert_passes(self, body, name, to_local=plus_two):
        code, output = self.run_report(body, name, to_local)
        self.assertEqual(code, 0, output)
        self.assertIn("OK", output)

    def assert_style_failure(self, body, name, to_local=plus_two, names=None):
        code, output = self.run_report(body, name, to_local)
        self.assertEqual(code, 1, output)
        self.assertNotIn("OK", output)
        self.assertIn("FAILED", output)
        self.assertIn("style problem", output)
        if names is not None:
            self.assertIn(names, output)

    def test_local_time_pair_and_decimal_comma(self):
        self.write_summary({
            "generated_at": GENERATED_AT,
            "finished_at": LATE_TIME,
            "queue_average": 6.5,
            "load_percent": 69.0,
        })

        with self.subTest("correct local and UTC pair passes"):
            self.assert_passes(
                ["The scan ran at 2026-09-30 09:26 (07:26 UTC)."], "pair-ok.md")

        with self.subTest("wrong local hour fails"):
            self.assert_style_failure(
                ["The scan ran at 2026-09-30 10:26 (07:26 UTC)."], "pair-wrong-local.md")

        with self.subTest("minute not in JSON fails (seconds are dropped, not rounded)"):
            self.assert_style_failure(
                ["The scan ran at 2026-09-30 09:27 (07:27 UTC)."], "pair-rounded.md")

        with self.subTest("local date rolls over to the next day"):
            self.assert_passes(
                ["The scan finished at 2026-10-01 01:30 (23:30 UTC)."], "pair-next-day.md")

        with self.subTest("report without times passes"):
            self.assert_passes(["The scan finished without trouble."], "no-times.md")

        with self.subTest("day-first local date fails"):
            self.assert_style_failure(
                ["The scan ran at 30.09.2026 09:26 (07:26 UTC)."], "pair-day-first.md")

        with self.subTest("local time without date fails"):
            self.assert_style_failure(
                ["The scan ran at 09:26 (07:26 UTC)."], "pair-no-date.md")

        with self.subTest("decimal comma backed by JSON floats passes"):
            self.assert_passes(
                ["The queue averaged 6,5 and the load was 69,0%."], "decimal-comma.md")

        self.write_summary({"generated_at": GENERATED_AT,
                            "sample": "Invented service restarted (10:00 UTC)."})

        with self.subTest("UTC time quoted from a JSON string passes"):
            self.assert_passes(
                ["> Invented service restarted (10:00 UTC)."], "quoted-utc.md")

        with self.subTest("UTC time not in any JSON string fails"):
            self.assert_style_failure(
                ["> Invented service restarted (11:00 UTC)."], "unquoted-utc.md")

        self.write_summary({"generated_at": GENERATED_AT, "last_boot": OLD_TIME})

        with self.subTest("year 1601 is skipped; correct pair passes"):
            self.assert_passes(
                ["The scan ran at 2026-09-30 09:26 (07:26 UTC)."], "old-pair-ok.md",
                to_local=plus_two_like_windows)

        with self.subTest("year 1601 is skipped; wrong pair fails without exception"):
            self.assert_style_failure(
                ["The scan ran at 2026-09-30 10:26 (07:26 UTC)."], "old-pair-wrong.md",
                to_local=plus_two_like_windows)

    def test_script_commands_need_data_dir(self):
        self.write_summary({"note": "invented"})
        intro = "Run the inventory from the project folder:"

        with self.subTest("Set-Location and absolute --data-dir pass"):
            self.assert_passes(
                [intro, *_block([SET_LOCATION, INVENTORY_OK])], "cmd-ok.md")

        with self.subTest("placeholder --data-dir fails"):
            self.assert_style_failure(
                [intro, *_block([SET_LOCATION, INVENTORY_PLACEHOLDER])],
                "cmd-placeholder.md", names="--data-dir")

        with self.subTest("missing --data-dir fails"):
            self.assert_style_failure(
                [intro, *_block([SET_LOCATION, INVENTORY_NO_DATA_DIR])],
                "cmd-no-data-dir.md", names="--data-dir")

        with self.subTest("missing Set-Location fails"):
            self.assert_style_failure(
                [intro, *_block([INVENTORY_OK])], "cmd-no-set-location.md",
                names="Set-Location")

        with self.subTest("placeholder Set-Location fails"):
            self.assert_style_failure(
                [intro, *_block(['Set-Location "<project root>"', INVENTORY_OK])],
                "cmd-placeholder-location.md", names="Set-Location")

        with self.subTest("relative Set-Location fails"):
            self.assert_style_failure(
                [intro, *_block(["Set-Location proj", INVENTORY_OK])],
                "cmd-relative-location.md", names="Set-Location")

        with self.subTest("backslash path without -B and --data-dir fails"):
            self.assert_style_failure(
                [intro, *_block([SET_LOCATION, SETTINGS_BARE])], "cmd-settings.md",
                names="--data-dir")

        with self.subTest("quoted absolute script path without --data-dir fails"):
            self.assert_style_failure(
                [intro, *_block([SET_LOCATION, HEALTH_QUOTED])], "cmd-health.md",
                names="--data-dir")

        with self.subTest("correct block indented by three spaces in a list item passes"):
            self.assert_passes(
                ["* Run the inventory from the project folder:",
                 *_block([SET_LOCATION, INVENTORY_OK], indent="   ")],
                "cmd-indented.md")

        with self.subTest("--data-dir with equals sign passes"):
            self.assert_passes(
                [intro, *_block([SET_LOCATION, INVENTORY_EQUALS])], "cmd-equals.md")

        with self.subTest("single-quoted paths pass"):
            self.assert_passes(
                [intro, *_block(["Set-Location 'C:\\proj'",
                                 ("python -B skills/ush-inventory/scripts/inventory.py "
                                  "--data-dir 'C:\\dane\\ush'")])], "cmd-single-quotes.md")

        with self.subTest("comment line naming a script passes"):
            self.assert_passes(
                [intro, *_block([SET_LOCATION, INVENTORY_OK,
                                 "# then run python -B skills/ush-events/scripts/events.py"])],
                "cmd-comment.md")

        with self.subTest("plain PowerShell block without a skill script passes"):
            self.assert_passes(
                ["Check the service yourself:",
                 *_block(['Get-Service -Name "WSearch"'])], "cmd-plain.md")

        with self.subTest("script command in text outside any block passes"):
            self.assert_passes(
                [("You can also run python -B skills/ush-inventory/scripts/inventory.py "
                  "by hand.")], "cmd-in-text.md")


if __name__ == "__main__":
    unittest.main()

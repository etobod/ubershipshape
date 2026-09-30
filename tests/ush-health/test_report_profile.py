"""The shared report checker driven by the real ush-health report profile.

All data below is invented. The checker and the profile are the real ones:
``skills/ush-common/scripts/check_report.py`` and
``skills/ush-health/data/report-profile.json`` (SKILLS_DIR is not patched).
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

DEVICE_NAME = "Invented Adapter 6 AX201"
PLAIN_DEVICE_NAME = "Invented Wireless Adapter"

FAILURE_U1 = {"id": "u1", "title": "Invented Cumulative Update", "result": "Failed",
              "count": 2}
FAILURE_U2 = {"id": "u2", "title": "Invented Driver Update", "result": "Failed",
              "count": 7}

PATH_KEYS = ("summary_file", "detail_file")

VOLUME_LINE = "Volume v1 (C:) has 29.2 GB free of 236.9 GB, that is 12.3 percent."
DEVICE_LINE = "Device p1 reports problem CM_PROB_FAILED_START."
DEVICE_NAME_LINE = f"Device p1 ({DEVICE_NAME}) reports problem CM_PROB_FAILED_START."
UPDATE_LINES = ["Update u1 (Invented Cumulative Update) failed 2 times."]


def _summary_data(summary_file, detail_file, device_name=DEVICE_NAME, failures=None,
                  truncated=None):
    return {
        "skill": "ush-health",
        "elevated": False,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": truncated,
        "disks": [
            {"id": "k1", "friendly_name": "Invented NVMe Disk", "media_type": "SSD",
             "health_status": "Healthy", "size_gb": 238.7},
        ],
        "volumes": [
            {"id": "v1", "drive_letter": "C", "file_system": "NTFS", "size_gb": 236.9,
             "free_gb": 29.2, "free_percent": 12.3},
        ],
        "devices": [
            {"id": "p1", "name": device_name, "class": "Net", "status": "Error",
             "problem": "CM_PROB_FAILED_START"},
        ],
        "updates": {
            "failures": list(failures) if failures is not None else [dict(FAILURE_U1)],
        },
        "pending_reboot": {"windows_update": False, "component_servicing": False,
                           "file_rename_operations": False},
    }


def _detail_data(summary):
    return {
        "disks": [dict(item) for item in summary["disks"]],
        "volumes": [dict(item) for item in summary["volumes"]],
        "devices": [dict(item) for item in summary["devices"]],
        "update_failures": [dict(item) for item in summary["updates"]["failures"]],
    }


def _body_lines(volume_line=VOLUME_LINE, device_lines=(DEVICE_LINE,),
                update_lines=tuple(UPDATE_LINES)):
    """Report lines after the ush:summary line; every number is backed by the JSON."""
    return [
        "# Health report",
        "",
        "| # | Area | State | Action |",
        "|---|---|---|---|",
        "| 1 | Disks | Healthy | None |",
        "| 2 | Volumes | Low free space | Free up space |",
        "| 3 | Devices | Error | Check the driver |",
        "| 4 | Updates | Failed | Retry |",
        "",
        "## Disks",
        "Disk k1 (Invented NVMe Disk, 238.7 GB) is Healthy.",
        "",
        "## Volumes",
        volume_line,
        "",
        "## Devices",
        *device_lines,
        "",
        "## Updates",
        *update_lines,
        "",
        "## Not checked",
        "<!-- ush:not-checked -->",
        "- disk_reliability: needs administrator.",
    ]


def _number_tokens(text):
    """Digit runs of a text as integers (the checker splits numbers on non-digits)."""
    return {int(token) for token in re.findall(r"\d+", text)}


def _digit_free_tempdir():
    """A temporary directory whose random name holds no digits.

    The random part of a temp name could otherwise supply a guarded number
    (for example a lone 6) and make a guard fail by chance.
    """
    for _ in range(500):
        tmp = tempfile.TemporaryDirectory(prefix="ush-health-")
        if not re.search(r"\d", Path(tmp.name).resolve().name):
            return tmp
        tmp.cleanup()
    raise AssertionError("could not get a temporary directory name without digits")


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _digit_free_tempdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.summary_file = self.work_dir / "health-summary.json"
        self.detail_file = self.work_dir / "health-detail.json"

    def _write_data(self, **kwargs):
        summary = _summary_data(self.summary_file, self.detail_file, **kwargs)
        detail = _detail_data(summary)
        self.summary_file.write_text(json.dumps(summary), encoding="utf-8")
        self.detail_file.write_text(json.dumps(detail), encoding="utf-8")
        return summary, detail

    def _write_report(self, body, name):
        path = self.reports_dir / name
        first = f"<!-- ush:summary {self.summary_file} -->"
        path.write_text("\n".join([first, *body]) + "\n", encoding="utf-8")
        return path

    def _run(self, report_path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(report_path)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def _assert_not_in_temp_path(self, number):
        # Guard: the temp directory ends up in the summary (summary_file,
        # detail_file); make sure it cannot supply the number.
        self.assertNotIn(int(number), _number_tokens(str(self.root)),
                         "temp path collides with test number")

    def _assert_passes(self, body, name):
        code, output = self._run(self._write_report(body, name))
        self.assertEqual(code, 0, f"report should pass; output:\n{output}")
        self.assertIn("OK", output)

    def test_clean_report_passes(self):
        self._write_data()
        code, output = self._run(
            self._write_report(_body_lines(), "health-2026-09-28-1200.md"))
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)

    def test_missing_item_or_rewritten_number_fails(self):
        self._write_data()
        # Control: the unchanged report passes.
        self._assert_passes(_body_lines(), "health-2026-09-28-1201.md")

        with self.subTest("device p1 not named"):
            code, output = self._run(self._write_report(
                _body_lines(device_lines=()), "health-2026-09-28-1202.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertIn("devices", output)

        with self.subTest("free_percent written as 12.35 instead of 12.3"):
            summary_text = self.summary_file.read_text(encoding="utf-8")
            detail_text = self.detail_file.read_text(encoding="utf-8")
            self.assertNotIn("35", summary_text, "35 occurs in the summary JSON")
            self.assertNotIn("35", detail_text, "35 occurs in the detail JSON")
            self._assert_not_in_temp_path("35")
            rewritten = VOLUME_LINE.replace("12.3 percent", "12.35 percent")
            self.assertNotEqual(rewritten, VOLUME_LINE)
            code, output = self._run(self._write_report(
                _body_lines(volume_line=rewritten), "health-2026-09-28-1203.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)

    def test_device_name_digits_backed(self):
        summary, detail = self._write_data(device_name=DEVICE_NAME)

        # Guard: 6 and 201 come only from the device name, not from any other
        # value of the JSON, nor from the temp path.
        self.assertTrue({6, 201} <= _number_tokens(DEVICE_NAME))
        stripped_summary = json.loads(json.dumps(summary))
        for key in PATH_KEYS:
            stripped_summary.pop(key)
        stripped_summary["devices"][0].pop("name")
        stripped_detail = json.loads(json.dumps(detail))
        stripped_detail["devices"][0].pop("name")
        other_tokens = (_number_tokens(json.dumps(stripped_summary))
                        | _number_tokens(json.dumps(stripped_detail)))
        for number in ("6", "201"):
            self.assertNotIn(int(number), other_tokens,
                             f"{number} occurs in the JSON outside the device name")
            self._assert_not_in_temp_path(number)

        body = _body_lines(device_lines=(DEVICE_NAME_LINE,))
        code, output = self._run(self._write_report(body, "health-2026-09-28-1210.md"))
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)

        with self.subTest("control: the same line fails when the name holds no digits"):
            self._write_data(device_name=PLAIN_DEVICE_NAME)
            code, output = self._run(
                self._write_report(body, "health-2026-09-28-1211.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)

    def test_detail_identifiers_back_no_number(self):
        # instance_id and device_id are identifiers kept only in the detail
        # file; once p1 and k1 are named in ush:detail, their digits must not
        # back a number the report writes.
        summary, detail = self._write_data(device_name=PLAIN_DEVICE_NAME)
        detail["devices"][0]["instance_id"] = "PCI\\VEN_ABCD&DEV_4417"
        detail["disks"][0]["device_id"] = "5308"
        self.detail_file.write_text(json.dumps(detail), encoding="utf-8")
        stripped_summary = json.loads(json.dumps(summary))
        for key in PATH_KEYS:
            stripped_summary.pop(key)
        tokens = _number_tokens(json.dumps(stripped_summary))
        for number in ("4417", "5308"):
            self.assertNotIn(int(number), tokens, f"{number} occurs in the summary")
            self._assert_not_in_temp_path(number)

        for number, item in (("4417", "p1"), ("5308", "k1")):
            with self.subTest(number=number):
                body = [f"<!-- ush:detail {item} -->",
                        *_body_lines(update_lines=(
                            *UPDATE_LINES, f"Item {item} shows {number} errors."))]
                code, output = self._run(
                    self._write_report(body, f"health-2026-09-28-123{item[1]}.md"))
                self.assertEqual(code, 1, f"output:\n{output}")
                self.assertNotIn("OK", output)
                self.assertIn(number, output)

    def test_cut_failures_are_known(self):
        # Two failure groups in the summary, three more cut (truncated: 3).
        # The device name holds no digits, so no reading backs 4, 5 or 6;
        # u4, u5 and u6 can only pass as ids.
        summary, detail = self._write_data(
            device_name=PLAIN_DEVICE_NAME,
            failures=[dict(FAILURE_U1), dict(FAILURE_U2)],
            truncated=3)
        stripped_summary = json.loads(json.dumps(summary))
        for key in PATH_KEYS:
            stripped_summary.pop(key)
        tokens = (_number_tokens(json.dumps(stripped_summary))
                  | _number_tokens(json.dumps(detail)))
        for number in ("4", "5", "6"):
            self.assertNotIn(int(number), tokens, f"{number} occurs in the JSON")
            self._assert_not_in_temp_path(number)

        listed = "Updates u1 and u2 failed 2 and 7 times."

        with self.subTest("u3, u4 and u5 are known ids"):
            body = _body_lines(update_lines=(
                listed, "Groups u3, u4 and u5 were cut from the summary."))
            code, output = self._run(self._write_report(body, "health-2026-09-28-1220.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("control: u6 is not a known id"):
            body = _body_lines(update_lines=(
                listed, "Group u6 was cut from the summary."))
            code, output = self._run(self._write_report(body, "health-2026-09-28-1221.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)


if __name__ == "__main__":
    unittest.main()

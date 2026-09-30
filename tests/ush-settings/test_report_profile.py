"""The ush-settings report profile, checked through the shared report checker.

The checker loads the real ``skills/ush-settings/data/report-profile.json``
through its unpatched ``SKILLS_DIR``; no copy of the profile is used.
All summary data below is invented.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

SKILL = "ush-settings"
# Keys whose values supply no numbers (the profile's path_keys and id_keys).
SKIP_KEYS = frozenset({"summary_file", "detail_file", "id"})
DETAIL_SECTIONS = ("settings", "changes", "usage")

GENERATED_AT = "2026-09-30T08:10:00+00:00"
KEY_PATH = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\AdvertisingInfo"


def _setting_item():
    return {
        "id": "e1",
        "entry": "advertising_id",
        "area": "privacy",
        "level": "standard",
        "title": "Advertising ID",
        "state": "differs",
        "effective": 1,
        "expected": [0],
        "source": "preference",
        "from_policy_on_home": False,
        "reason": None,
        "has_block": True,
    }


def _change_item():
    return {
        "id": "c1",
        "key": "advertising_id",
        "change": "changed",
        "entry": "advertising_id",
        "area": "privacy",
        "title": "Advertising ID",
        "state": "differs",
        "before": 0,
        "after": 1,
    }


def _usage_u1():
    return {
        "id": "u1",
        "capability": "webcam",
        "app": "Invented.CameraApp_abc",
        "packaged": True,
        "value": "Allow",
        "last_used_start": "2026-09-29T18:00:00+00:00",
        "last_used_stop": "2026-09-29T18:25:00+00:00",
        "in_use": False,
    }


def _usage_u2():
    return {
        "id": "u2",
        "capability": "microphone",
        "app": "Invented.RecorderApp_xyz",
        "packaged": True,
        "value": "Allow",
        "last_used_start": "2026-09-28T21:00:00+00:00",
        "last_used_stop": "2026-09-28T21:40:00+00:00",
        "in_use": False,
    }


def _summary_data(summary_file, detail_file, *, usage, truncated):
    return {
        "schema_version": 1,
        "skill": SKILL,
        "generated_at": GENERATED_AT,
        "elevated": False,
        "edition_id": "Core",
        "sources": [
            {"name": "registry_values", "status": "read", "reason": None},
            {"name": "capability_usage", "status": "read", "reason": None},
        ],
        "not_checked": [],
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": truncated,
        "baseline": {
            "status": "compared",
            "created_at": "2026-09-23T08:10:00+00:00",
            "age_days": 6.9,
            "saved": True,
            "reason": None,
        },
        "comparison": {"settings": "compared", "capability_usage": "compared"},
        "counts": {
            "by_state": {"differs": 1, "not_read": 0, "default_unknown": 0, "info": 0,
                         "matches": 40, "not_applicable": 2},
            "by_area": {"privacy": {"differs": 1, "matches": 7},
                        "security": {"matches": 33, "not_applicable": 2}},
        },
        "settings": [_setting_item()],
        "changes": [_change_item()],
        "catalogue_changes": {"added": 0, "removed": 0},
        "usage": usage,
    }


def _clean_summary(summary_file, detail_file):
    """One setting that differs, one change, one capability use; compared with a baseline."""
    return _summary_data(summary_file, detail_file, usage=[_usage_u1()], truncated=0)


BASELINE_LINE = "Compared with the baseline of 2026-09-23, 6.9 days old."
USAGE_U1_LINE = ("- u1: Invented.CameraApp_abc used the webcam on 2026-09-29 "
                 "from 18:00 to 18:25; allowed, not in use now.")


def _block_lines():
    """A paste-ready block as ``--block`` prints it, inside a powershell code block."""
    return [
        "```powershell",
        "# Run in a normal (non-elevated) Windows PowerShell",
        (f"New-ItemProperty -LiteralPath '{KEY_PATH}' -Name 'Enabled' -Value 0 "
         "-PropertyType DWord -Force | Out-Null"),
        "# Rollback",
        (f"New-ItemProperty -LiteralPath '{KEY_PATH}' -Name 'Enabled' -Value 1 "
         "-PropertyType DWord -Force | Out-Null"),
        "```",
    ]


def _clean_report_lines(summary_file, usage_lines=(USAGE_U1_LINE,)):
    """A report whose numbers all come from the clean summary."""
    return [
        f"<!-- ush:summary {summary_file} -->",
        "# Settings report, 2026-09-30 08:10",
        "",
        "| # | Area | State | Action |",
        "|---|------|-------|--------|",
        "| 1 | Settings | one differs | review |",
        "| 2 | Changes | one since the baseline | none |",
        "| 3 | Capability use | one listed | none |",
        "",
        "## Comparison",
        BASELINE_LINE,
        "- c1: Advertising ID changed from 0 to 1.",
        "",
        "## Settings",
        "- Matching: 40. Differing: 1. Not applicable: 2. Not read: 0.",
        "- Privacy: 7 settings as expected. Security: 33 settings as expected.",
        ("- e1: Advertising ID (privacy, standard) differs: effective 1, expected 0; "
         "set as a preference."),
        "",
        "Paste into a normal Windows PowerShell to turn the advertising ID off:",
        "",
        *_block_lines(),
        "",
        "## Capability use",
        *usage_lines,
        "",
        "## Not checked",
        "<!-- ush:not-checked -->",
        "- nothing.",
    ]


def _numbers(data):
    """Integers the checker would take from parsed JSON (skip keys left out)."""
    found = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                found.update(int(n) for n in re.findall(r"[0-9]+", str(key)))
                if key not in SKIP_KEYS:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, (int, float, str)) and not isinstance(item, bool):
            found.update(int(n) for n in re.findall(r"[0-9]+", str(item)))
    return found


def _digit_free_tempdir():
    """A temporary directory whose random name holds no digits.

    The random part of a temp name could otherwise hold a guarded number and
    make a guard fail by chance.
    """
    for _ in range(500):
        tmp = tempfile.TemporaryDirectory(prefix="ush-settings-")
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
        self.work = self.root / "work"
        self.work.mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def _assert_real_profile(self):
        # The checker's own SKILLS_DIR, not patched: the real profile file.
        profile = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        self.assertTrue(profile.is_file(),
                        f"the ush-settings report profile is missing: {profile}")

    def _write_summary(self, name, builder):
        summary_file = self.work / f"{name}-summary.json"
        detail_file = self.work / f"{name}-detail.json"
        summary = builder(summary_file, detail_file)
        detail = {section: summary[section] for section in DETAIL_SECTIONS}
        detail_file.write_text(json.dumps(detail), encoding="utf-8")
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        return summary_file, summary

    def _write_report(self, lines, name):
        path = self.reports / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _run_args(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def _run(self, report):
        code, out, err = self._run_args([str(report)])
        return code, out + err

    def test_clean_report_passes(self):
        self._assert_real_profile()
        summary_file, _ = self._write_summary("settings", _clean_summary)
        report = self._write_report(_clean_report_lines(summary_file),
                                    "settings-2026-09-30-0810.md")
        code, out, err = self._run_args([str(report)])
        self.assertEqual(code, 0, f"stdout:\n{out}\nstderr:\n{err}")
        self.assertTrue(out.startswith("OK"), f"stdout:\n{out}\nstderr:\n{err}")

        with self.subTest("--latest --skill ush-settings finds settings-*.md"):
            code, out, err = self._run_args(
                ["--latest", "--skill", SKILL, "--data-dir", str(self.root)])
            self.assertEqual(code, 0, f"stdout:\n{out}\nstderr:\n{err}")
            self.assertTrue(out.startswith("OK"), f"stdout:\n{out}\nstderr:\n{err}")
            self.assertIn("settings-2026-09-30-0810.md", out)

    def test_missing_item_or_rewritten_number_fails(self):
        self._assert_real_profile()
        summary_file, summary = self._write_summary("settings", _clean_summary)
        clean = _clean_report_lines(summary_file)
        code, output = self._run(self._write_report(clean, "settings-2026-09-30-0811.md"))
        self.assertEqual(code, 0, f"the control report should pass; output:\n{output}")

        with self.subTest("usage item u1 not named"):
            lines = _clean_report_lines(summary_file, usage_lines=("- none listed.",))
            self.assertFalse(any(re.search(r"\bu1\b", line) for line in lines[1:]))
            code, output = self._run(self._write_report(lines, "settings-2026-09-30-0812.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertTrue(
                any(re.search(r"\bu1\b", line) and "usage" in line
                    for line in output.splitlines()),
                f"expected a line naming u1 and usage; output:\n{output}",
            )

        with self.subTest("age_days written differently from the JSON"):
            number = "64"
            summary_text = summary_file.read_text(encoding="utf-8")
            self.assertNotIn(number, summary_text, "the number must not occur in the JSON")
            self.assertNotIn(int(number), _numbers(summary))
            self.assertNotIn(number, str(self.root), "temp path collides with the number")
            self.assertIn(BASELINE_LINE, clean)
            lines = [line.replace("6.9 days", f"{number} days") if line == BASELINE_LINE
                     else line for line in clean]
            self.assertNotEqual(lines, clean)
            code, output = self._run(self._write_report(lines, "settings-2026-09-30-0813.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertIn(number, output)

    def test_cut_usage_is_known(self):
        self._assert_real_profile()

        def cut_summary(summary_file, detail_file):
            return _summary_data(summary_file, detail_file,
                                 usage=[_usage_u1(), _usage_u2()], truncated=3)

        summary_file, summary = self._write_summary("settings-cut", cut_summary)
        self.assertEqual(len(summary["usage"]), 2)
        self.assertEqual(summary["truncated"], 3)
        # u4 and u5 are backed only by being known ids, not by their digits.
        self.assertNotIn(4, _numbers(summary))
        self.assertNotIn(5, _numbers(summary))

        usage_lines = (
            USAGE_U1_LINE,
            ("- u2: Invented.RecorderApp_xyz used the microphone on 2026-09-28 "
             "from 21:00 to 21:40; allowed, not in use now."),
            "- 3 more uses were cut from the summary: u3, u4, u5.",
        )
        lines = _clean_report_lines(summary_file, usage_lines=usage_lines)
        code, output = self._run(self._write_report(lines, "settings-2026-09-30-0814.md"))
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)


if __name__ == "__main__":
    unittest.main()

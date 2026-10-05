"""The ush-files report profile, checked through the shared report checker (plan 096, M3).

The checker loads the real ``skills/ush-files/data/report-profile.json`` through its
unpatched ``SKILLS_DIR``; no copy of the profile is used. The plan gives the profile:
``report_prefix`` ``files-``, ``id_letters`` ``fldc``, ``id_keys`` ``["id", "item"]``
(``item`` added later), ``detail_sections`` folders/large_files/changes/cleanup/unreadable, ``required_lists``
changes/cleanup/large_files, ``truncated`` for folders (f), large_files (l) and changes
(d), and ``path_keys`` summary_file, detail_file, path, paths, unreadable_key,
parent_key, block, reference_file, skipped_key, expanded_paths (later plans).

The invented summary has the shape of M1-M3: ``drives``, ``folders`` (f...),
``large_files`` (l...), ``changes`` (d...), ``cleanup`` (c...), ``sources`` per drive
(``folders:C``, ``large_files:C``, ``drives:C``), ``baseline``, ``comparison``,
``counts``, ``not_checked`` and the ``truncated_*`` counts. Assumed beyond the plan: a
cleanup item names its catalogue entry in ``entry``.

``_clean_summary``, ``_detail_data`` are also used by
``tests/ush-common/test_check_report_words.py``. All data below is invented.
"""

import contextlib
import importlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

SKILL = "ush-files"
# Keys whose values supply no numbers (the profile's path_keys and id_keys).
SKIP_KEYS = frozenset({"summary_file", "detail_file", "path", "paths", "unreadable_key",
                       "parent_key", "block", "reference_file", "skipped_key",
                       "expanded_paths", "id", "item"})
DETAIL_SECTIONS = ("folders", "large_files", "changes", "cleanup", "unreadable")

GENERATED_AT = "2026-10-02T08:10:00+00:00"
PREVIOUS_AT = "2026-09-25T07:00:00+00:00"
GIB = 1024 ** 3
VHDX = "C:\\VMs\\Invented Lab 7342\\disk.vhdx"
TEMP_BLOCK = (
    "$cutoff = (Get-Date).AddDays(-2)\n"
    "$deleted = 0; $skipped = 0\n"
    "Get-ChildItem -LiteralPath $env:TEMP -File -Recurse -Force |\n"
    "  Where-Object { $_.LastWriteTime -lt $cutoff } |\n"
    "  ForEach-Object { try { Remove-Item -LiteralPath $_.FullName -Force "
    "-ErrorAction Stop; $deleted++ } catch { $skipped++ } }\n"
    "\"Deleted: $deleted, skipped: $skipped\""
)
RECYCLE_BLOCK = (
    "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {\n"
    "  Clear-RecycleBin -DriveLetter $_.DeviceID.TrimEnd(':') -Force }"
)


def _sources():
    return [{"name": f"{kind}:C", "status": "read", "reason": None}
            for kind in ("folders", "large_files", "drives")]


def _folders():
    return [
        {"id": "f1", "path": "C:\\Windows", "depth": 1, "bytes": 33715493273, "gb": 31.4,
         "files": 180234, "cloud_only_files": 0, "listed": True, "readable_part": True,
         "unreadable_dirs": 6, "unreadable_key": "9f2c" * 16},
        {"id": "f2", "path": "C:\\Program Files (x86)", "depth": 1, "bytes": 13207024435,
         "gb": 12.3, "files": 41872, "cloud_only_files": 0, "listed": True,
         "readable_part": False, "unreadable_dirs": 0, "unreadable_key": None},
    ]


def _large_files():
    return [{"id": "l1", "path": VHDX, "bytes": 42949672960, "gb": 40.0,
             "modified": "2026-09-30T19:00:00+00:00"}]


def _changes():
    return [{"id": "d1", "kind": "folder_grew", "path": "C:\\Users\\a\\Downloads",
             "drive": "C", "depth": 3, "before_bytes": GIB, "after_bytes": 3 * GIB,
             "delta_bytes": 2 * GIB, "delta_gb": 2.0, "readable_part": False}]


def _cleanup():
    return [
        {"id": "c1", "entry": "temp-user", "paths": ["%TEMP%"], "status": "read",
         "reason": None, "bytes": 730144440, "files": 1532, "gb": 0.68,
         "bytes_older": 633507020, "files_older": 1204, "gb_older": 0.59,
         "min_age_days": 2, "risk": "low", "needs_admin": False,
         "conditions": "close programs that may hold temporary files",
         "rollback": "cannot be undone", "block": TEMP_BLOCK},
        {"id": "c2", "entry": "recycle-bin", "paths": ["<drive>:\\$Recycle.Bin"],
         "status": "read", "reason": None, "bytes": 53687091, "files": 12, "gb": 0.05,
         "min_age_days": 0, "risk": "low", "needs_admin": False,
         "conditions": "the user has looked through the recycle bin",
         "rollback": "cannot be undone", "block": RECYCLE_BLOCK},
    ]


def _clean_summary(summary_file, detail_file):
    """A second run on one drive: compared with the baseline, nothing cut."""
    return {
        "schema_version": 1,
        "skill": SKILL,
        "generated_at": GENERATED_AT,
        "elevated": False,
        "duration_s": 412.7,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "sources": _sources(),
        "baseline": {"status": "compared", "created_at": PREVIOUS_AT, "age_days": 7.1,
                     "saved": True, "reason": None},
        "comparison": {"sources": {source["name"]: "compared" for source in _sources()},
                       "previous_at": PREVIOUS_AT, "age_days": 7.1},
        "drives": [{"letter": "C", "total_bytes": 255980048794, "used_bytes": 171798691840,
                    "free_bytes": 84181356954, "scanned_bytes": 160627394560,
                    "scanned_files": 412345, "unreadable_dirs": 6, "total_gb": 238.4,
                    "used_gb": 160.0, "free_gb": 78.4, "scanned_gb": 149.6}],
        "folders": _folders(),
        "large_files": _large_files(),
        "changes": _changes(),
        "cleanup": _cleanup(),
        "counts": {"reparse_skipped": 3, "cloud_only_dirs": 0, "vanished_dirs": 1,
                   "not_compared": 0},
        "truncated_folders": 0,
        "truncated_large_files": 0,
        "truncated_changes": 0,
        "not_checked": [],
    }


def _detail_data(summary):
    """The detail file of ``summary``: every list of it, and no unreadable folder."""
    detail = {section: list(summary.get(section) or []) for section in DETAIL_SECTIONS}
    detail["unreadable"] = []
    return detail


def _clean_report_lines(summary_file):
    """A report whose numbers all come from the clean summary; paths with digits stand
    only in code blocks."""
    return [
        f"<!-- ush:summary {summary_file} -->",
        "# Files report, 2026-10-02",
        "",
        "## Drives",
        "- Drive C: 160.0 GB used of 238.4 GB, 78.4 GB free.",
        ("- Files under the scanned folders: 149.6 GB; the used space of the drive is the "
         "figure that counts."),
        "- f1: the Windows folder, 31.4 GB; f2: the folder of older programs, 12.3 GB.",
        "",
        "```",
        "C:\\Program Files (x86)",
        "```",
        "",
        "## What changed",
        "Compared with the run of 2026-09-25, 7.1 days old.",
        "- d1: the Downloads folder of the user grew by 2.0 GB.",
        "",
        "## Large files",
        "- l1: a virtual disk, 40.0 GB, modified 2026-09-30.",
        "",
        "## To clean up",
        ("- c1: temporary files of the user, 0.68 GB in 1532 files; older than 2 days: "
         "0.59 GB in 1204 files."),
        ("  Recommendation: weight low, risk low; evidence c1; permissions: the user's "
         "own shell; rollback: cannot be undone."),
        "",
        "```powershell",
        *TEMP_BLOCK.splitlines(),
        "```",
        "",
        "- c2: the recycle bin, 0.05 GB in 12 files; risk low, cannot be undone.",
        "",
        "```powershell",
        *RECYCLE_BLOCK.splitlines(),
        "```",
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


class TestReportProfile(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def _write_summary(self, name):
        summary_file = self.work / f"{name}.summary.json"
        detail_file = self.work / f"{name}.detail.json"
        summary = _clean_summary(summary_file, detail_file)
        detail_file.write_text(json.dumps(_detail_data(summary)), encoding="utf-8")
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        return summary_file, summary

    def _write_report(self, lines, name):
        path = self.reports / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _run(self, report):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(report)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_cleanup_item_id_backs_no_number(self):
        # A not_checked note names the cleanup item by its id (``"item": "c3"``); the
        # digit of the id is no reading, while the note's other numbers still count.
        profile = self.check.load_profile(SKILL)
        note = {"what": "cleanup item", "item": "c3", "reason": "listed 41 of 58"}
        found = {item[-1] for item in self.check.json_values({"not_checked": [note]},
                                                            profile.skip_keys)}
        self.assertNotIn(3, found, found)
        self.assertTrue({41, 58} <= found, found)

    def test_detail_keys_back_no_number(self):
        # A folder's skipped_key is a hash and a cleanup item's expanded_paths are
        # paths: an ush:detail marker reads them, and their digits are no readings.
        profile = self.check.load_profile(SKILL)
        folder = {"id": "f2", "skipped_key": "9f42a7" + "0" * 58, "size_bytes": 512}
        cleanup = {"id": "c1", "expanded_paths": [r"C:\Users\user2024\AppData\Local\Temp"],
                   "size_bytes": 640}
        found = {item[-1] for item in self.check.json_values({"folders": [folder],
                                                             "cleanup": [cleanup]},
                                                            profile.skip_keys)}
        for number in (9, 42, 7, 7 * 10 ** 58, 2024):
            self.assertNotIn(number, found, found)
        self.assertTrue({512, 640} <= found, found)

    def test_clean_and_invented_number(self):
        profile = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        self.assertTrue(profile.is_file(), f"the ush-files report profile is missing: {profile}")
        summary_file, summary = self._write_summary("files-20261002T081000Z")
        clean = _clean_report_lines(summary_file)

        with self.subTest("clean report, with C:\\Program Files (x86) in a code block"):
            self.assertIn("C:\\Program Files (x86)", clean)
            self.assertNotIn(86, _numbers(summary))
            code, output = self._run(self._write_report(clean, "files-2026-10-02-0810.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("a number that is not in the JSON"):
            number = "4096"
            self.assertNotIn(int(number), _numbers(summary))
            self.assertNotIn(number, str(self.root), "temp path collides with the number")
            lines = clean + [f"- {number} folders were checked."]
            code, output = self._run(self._write_report(lines, "files-invented.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn(number, output)

        with self.subTest("a number only in a path backs nothing"):
            number = "7342"
            self.assertIn(number, VHDX)
            self.assertNotIn(int(number), _numbers(summary))
            self.assertNotIn(number, str(self.root), "temp path collides with the number")
            lines = clean + [f"- The virtual disk lies in the lab folder {number}."]
            code, output = self._run(self._write_report(lines, "files-path-number.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn(number, output)

        with self.subTest("ush-files in SKILLS and SCRIPTS"):
            words = importlib.import_module("tests.ush-common.test_check_report_words")
            self.assertIn(SKILL, words.SKILLS)
            datadir = importlib.import_module("tests.ush-common.test_datadir")
            self.assertTrue(any(spec[1] == SKILL for spec in datadir.SCRIPTS),
                            [spec[:2] for spec in datadir.SCRIPTS])


if __name__ == "__main__":
    unittest.main()

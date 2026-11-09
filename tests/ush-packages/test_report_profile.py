"""The ush-packages report profile, checked through the shared report checker
(plan 061, M1, K5).

The checker loads the real ``skills/ush-packages/data/report-profile.json`` through
its unpatched ``SKILLS_DIR``; no copy of the profile is used. The detail sections and
the cut-count keys of the invented summary are taken from that profile, so the
fixture follows it. All summary data below is invented.

Plan 066, M2, K6 (``TestReportProfile``): a report naming pipx, uv and conda in state
``not_present`` as "nie ma" or "not present", with the Packages cell "—", passes the
checker; the managers not read keep "not read yet".
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.report_summary import with_summary
from tests.skill_loader import load_script

from .fakes import SKILL, load_profile, truncated_count_keys

GENERATED_AT = "2026-11-09T10:00:00+00:00"
NPM_FOLDER = "C:\\Users\\Invented\\AppData\\Roaming\\npm\\node_modules"
NOT_READ = ("winget", "go", "vscode")
NOT_UPDATED = "nie sprawdzono pod k\u0105tem aktualizacji"


def _packages():
    return [
        {"id": "k1", "manager": "pip", "key": "pip:PythonCore/3.12|install|requests",
         "name": "requests", "version": "2.32.0", "python": "PythonCore/3.12",
         "folder": "install"},
        {"id": "k2", "manager": "pip", "key": "pip:PythonCore/3.12|user|idna",
         "name": "idna", "version": "3.6", "python": "PythonCore/3.12", "folder": "user"},
        {"id": "k3", "manager": "npm", "key": "npm:left-pad", "name": "left-pad",
         "version": "1.3.0", "folder": NPM_FOLDER},
        {"id": "k4", "manager": "npm", "key": "npm:@contoso/tool", "name": "@contoso/tool",
         "version": "2.1.0", "folder": NPM_FOLDER},
    ]


def _changes():
    return [
        {"id": "c1", "key": "pip:PythonCore/3.12|install|requests", "source": "pip_packages",
         "change": "changed", "name": "requests",
         "fields": {"version": {"before": "2.31.0", "after": "2.32.0"}}},
        {"id": "c2", "key": "npm:@contoso/tool", "source": "npm_packages",
         "change": "added", "name": "@contoso/tool"},
    ]


def clean_summary(summary_file, detail_file):
    """pip with one Python and two packages, npm with two, three managers not read,
    and two changes since a baseline; nothing cut."""
    summary = {
        "schema_version": 1,
        "skill": SKILL,
        "generated_at": GENERATED_AT,
        "elevated": False,
        "sources": [{"name": name, "status": "read", "reason": None}
                    for name in ("pip_packages", "npm_packages")],
        "baseline": {"status": "compared", "created_at": "2026-11-02T10:00:00+00:00",
                     "age_days": 7.0, "saved": True, "reason": None},
        "comparison": {"pip_packages": "compared", "npm_packages": "compared"},
        "managers": {
            "pip": {"state": "read", "status": "read", "pythons": [{
                "python": "PythonCore/3.12", "count": 2, "unreadable": 0,
                "folders": {"install": "read", "user": "read"}}]},
            "npm": {"state": "read", "status": "read", "prefix_from": "default",
                    "count": 2, "unreadable": 0},
            **{name: {"state": "not_read"} for name in NOT_READ},
        },
        "packages": _packages(),
        "changes": _changes(),
        "counts": {"packages": 4, "changes": 2},
        "not_checked": [
            *({"what": name, "reason": "not read yet"} for name in NOT_READ),
            {"what": "Python installs not registered in PEP 514 (venvs, portable builds)",
             "reason": "not searched"},
        ],
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
    }
    for count_key in set(truncated_count_keys().values()):
        summary[count_key] = 0
    return summary


def clean_report_lines(summary_file):
    """A report in the shape of references/report-format.md whose numbers all come
    from ``clean_summary``."""
    return [
        f"<!-- ush:summary {summary_file} -->",
        "# Packages report, 2026-11-09 10:00",
        "",
        "## Dashboard",
        "| Manager | State | Packages |",
        "|---------|-------|----------|",
        "| pip | read | 2 |",
        "| npm | read | 2 |",
        "| winget | not read yet | - |",
        "| go | not read yet | - |",
        "| vscode | not read yet | - |",
        "",
        "## Changes since the last run",
        "Compared with the baseline of 2026-11-02, 7.0 days old.",
        "- c1: requests (Python PythonCore/3.12, install) changed from 2.31.0 to 2.32.0.",
        "- c2: @contoso/tool was added, version 2.1.0.",
        "",
        "## Installed packages",
        "### pip",
        f"- k1: requests 2.32.0, Python PythonCore/3.12, install folder; {NOT_UPDATED}.",
        f"- k2: idna 3.6, Python PythonCore/3.12, user folder; {NOT_UPDATED}.",
        "",
        "### npm",
        f"- k3: left-pad 1.3.0, global folder; {NOT_UPDATED}.",
        f"- k4: @contoso/tool 2.1.0, global folder; {NOT_UPDATED}.",
        "",
        "## Not checked",
        "<!-- ush:not-checked -->",
        "- winget: not read yet.",
        "- go: not read yet.",
        "- vscode: not read yet.",
        "- Python installs not registered in PEP 514 (venvs, portable builds): not searched.",
        "- Newer versions: no package was checked, there is no ush-advice lookup yet.",
    ]


# Plan 066, M2, K6: pipx, uv and conda not present (none of their locations exists).
NOT_PRESENT = {
    "pipx": ["%USERPROFILE%\\pipx", "%USERPROFILE%\\.local\\pipx",
             "%LOCALAPPDATA%\\pipx\\pipx"],
    "uv": ["%APPDATA%\\uv\\data\\tools"],
    "conda": ["%USERPROFILE%\\.conda\\environments.txt"],
}
NOT_PRESENT_SOURCES = ("pipx_packages", "uv_tools", "conda_packages")
NOT_PRESENT_NOTES = (
    ("pipx homes outside looked_in",
     ("a pipx home set by another account's PIPX_HOME, or the default of another pipx "
      "version, is not searched")),
    ("uv tools outside looked_in",
     ("a tool folder set by UV_TOOL_DIR in another environment, or under XDG_DATA_HOME, "
      "is not searched")),
    ("conda environments outside environments.txt (.condarc envs_dirs, CONDA_ENVS_PATH)",
     "not searched"),
)


def not_present_summary(summary_file, detail_file):
    """``clean_summary`` with pipx, uv and conda not present: each source read as
    ``empty`` and compared, each manager ``{state: "not_present", looked_in}``, and
    each one's "outside the locations searched" note."""
    summary = clean_summary(summary_file, detail_file)
    summary["sources"] += [{"name": name, "status": "empty", "reason": None}
                           for name in NOT_PRESENT_SOURCES]
    summary["comparison"].update({name: "compared" for name in NOT_PRESENT_SOURCES})
    summary["managers"].update({name: {"state": "not_present", "looked_in": list(paths)}
                                for name, paths in NOT_PRESENT.items()})
    summary["not_checked"] += [{"what": what, "reason": reason}
                               for what, reason in NOT_PRESENT_NOTES]
    return summary


def not_present_report_lines(summary_file, wording):
    """``clean_report_lines`` with a dashboard row per not-present manager in
    ``wording`` and the Packages cell "—"; the managers not read keep "not read yet"."""
    lines = clean_report_lines(summary_file)
    last_row = lines.index("| vscode | not read yet | - |")
    rows = [f"| {name} | {wording} | — |" for name in NOT_PRESENT]
    lines[last_row + 1:last_row + 1] = rows
    marker = lines.index("<!-- ush:not-checked -->")
    notes = [f"- {what}: {reason}." for what, reason in NOT_PRESENT_NOTES]
    lines[marker + 1:marker + 1] = notes
    return lines


def _quiet_tempdir():
    """A temporary directory whose random name holds no digits (so it cannot supply an
    id or a number) and whose path holds no word the tests assert on."""
    for _ in range(500):
        tmp = tempfile.TemporaryDirectory(prefix="ush-pk-")
        path = str(Path(tmp.name).resolve())
        name = Path(path).name
        if not re.search(r"\d", name) and "managers" not in path.casefold():
            return tmp
        tmp.cleanup()
    raise AssertionError("could not get a quiet temporary directory")


class ReportCheckMixin:
    """Workspace and checker helpers shared by the ush-packages profile tests."""

    def make_workspace(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _quiet_tempdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def assert_real_profile(self):
        # The checker's own SKILLS_DIR, not patched: the real profile file.
        profile = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        self.assertTrue(profile.is_file(),
                        f"the ush-packages report profile is missing: {profile}")

    def write_summary(self, name, builder=clean_summary, drop=()):
        """Write the summary and its detail file (every detail section of the profile;
        ``packages`` and ``changes`` hold the summary's lists)."""
        summary_file = self.work / f"{name}-summary.json"
        detail_file = self.work / f"{name}-detail.json"
        summary = builder(summary_file, detail_file)
        for key in drop:
            summary.pop(key, None)
        sections = load_profile().get("detail_sections") or []
        detail = {section: [] for section in sections}
        detail["packages"] = _packages()
        detail["changes"] = _changes()
        detail_file.write_text(json.dumps(detail), encoding="utf-8")
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        return summary_file, summary

    def write_report(self, lines, name):
        path = self.reports / name
        path.write_text("\n".join(with_summary(lines, SKILL)) + "\n", encoding="utf-8")
        return path

    def run_check(self, report):
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = self.check.main([str(report)])
                except SystemExit as exc:
                    code = exc.code
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            return None, f"checker raised {type(exc).__name__}: {exc}"
        return code, out.getvalue() + err.getvalue()

    def assert_passes(self, lines, name):
        code, output = self.run_check(self.write_report(lines, name))
        self.assertEqual(code, 0, f"the report should pass; output:\n{output}")
        self.assertTrue(output.startswith("OK"), f"output:\n{output}")

    def assert_names_missing(self, lines, name, item_id):
        """A report without ``item_id`` fails and the checker names it."""
        self.assertNotIn(item_id, str(self.root), "temp path collides with the id")
        self.assertFalse(any(re.search(rf"\b{item_id}\b", line) for line in lines[1:]),
                         f"{item_id} is still in the report")
        code, output = self.run_check(self.write_report(lines, name))
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertNotIn("OK", output)
        self.assertTrue(
            any("not named in the report" in line and re.search(rf"\b{item_id}\b", line)
                for line in output.splitlines()),
            f"expected 'not named in the report' naming {item_id}; output:\n{output}")


class TestPackagesProfile(ReportCheckMixin, unittest.TestCase):
    def setUp(self):
        self.make_workspace()

    def test_clean_report_passes_and_omissions_fail(self):
        self.assert_real_profile()
        summary_file, _ = self.write_summary("packages")
        clean = clean_report_lines(summary_file)

        with self.subTest("clean report"):
            self.assert_passes(clean, "packages-2026-11-09-1000.md")

        with self.subTest("change c2 not named"):
            lines = [line for line in clean if not line.startswith("- c2:")]
            self.assert_names_missing(lines, "packages-2026-11-09-1001.md", "c2")

        with self.subTest("summary without managers"):
            old_file, old = self.write_summary("packages-no-mgr", drop=("managers",))
            self.assertNotIn("managers", old)
            lines = clean_report_lines(old_file)
            self.assertFalse(any("managers" in line for line in lines))
            self.assertNotIn("managers", str(self.root), "temp path contains the key")
            code, output = self.run_check(
                self.write_report(lines, "packages-2026-11-09-1002.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertIn("managers", output)


class TestReportProfile(ReportCheckMixin, unittest.TestCase):
    """Plan 066, M2, K6."""

    def setUp(self):
        self.make_workspace()

    def test_not_present_manager_report(self):
        self.assert_real_profile()
        summary_file, summary = self.write_summary("packages-np", not_present_summary)
        for name in NOT_PRESENT:
            self.assertEqual(summary["managers"][name]["state"], "not_present")

        for number, wording in enumerate(("nie ma", "not present")):
            with self.subTest(wording=wording):
                lines = not_present_report_lines(summary_file, wording)
                for name in NOT_PRESENT:
                    self.assertIn(f"| {name} | {wording} | — |", lines)
                # The managers not read keep "not read yet", never the not-present words.
                for name in NOT_READ:
                    self.assertIn(f"| {name} | not read yet | - |", lines)
                    self.assertIn(f"- {name}: not read yet.", lines)
                self.assert_passes(lines, f"packages-2026-11-09-110{number}.md")

        with self.subTest("the shared clean report keeps 'not read yet'"):
            clean = clean_report_lines(summary_file)
            for name in NOT_READ:
                self.assertIn(f"| {name} | not read yet | - |", clean)
            self.assertFalse([line for line in clean
                              if "not present" in line or "nie ma" in line], clean)


if __name__ == "__main__":
    unittest.main()

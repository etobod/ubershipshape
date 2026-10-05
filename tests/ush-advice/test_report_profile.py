"""The ush-advice report profile, checked through the shared report checker
(plan 103, M3).

The checker loads the real ``skills/ush-advice/data/report-profile.json``
through its unpatched ``SKILLS_DIR``; no copy of the profile is used.
All summary data below is invented (Contoso-style names, invented KB and CVE).
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

SKILL = "ush-advice"
GENERATED_AT = "2026-09-20T12:00:00+00:00"
ISSUE_TITLE = "Invented issue"
# A number that appears only in a finding's title (a path key in the profile).
TITLE_NUMBER = "4471"
TITLE_WITH_NUMBER = f"Invented issue {TITLE_NUMBER}"
DETAIL_KEYS = ("comparison", "exploited", "findings", "firmware", "generated_at", "issues",
               "kev_other", "machine", "query_warnings", "schema_version", "searches",
               "skill", "sources", "updates")


def _clean_summary(summary_file, detail_file, issue_title=ISSUE_TITLE):
    """A summary of the shape advice.py --findings writes; nothing cut, no baseline."""
    return {
        "schema_version": 1,
        "skill": SKILL,
        "generated_at": GENERATED_AT,
        "sources": [{"name": name, "status": "read", "reason": None}
                    for name in ("os_version", "hotfixes", "firmware")],
        "not_checked": [],
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": 0,
        "truncated_exploited": 0,
        "baseline": {"status": "none", "created_at": None, "age_days": None,
                     "saved": True, "reason": None},
        "comparison": {"updates": "no_baseline", "exploited": "no_baseline",
                       "firmware": "no_baseline", "issues": "no_baseline"},
        "searches": [{"name": name, "status": "read", "reason": None}
                     for name in ("release-info", "msrc", "kev", "release-health", "firmware")],
        "machine": {
            "display_version": "25H2",
            "build": "26200",
            "ubr": 6899,
            "edition_id": "Core",
            "architecture": "AMD64",
            "product": "Windows 11 Version 25H2 for x64-based Systems",
            "product_reason": None,
            "hotfixes": ["KB5099901", "KB5099917"],
            "firmware": {"manufacturer": "Contoso Ltd.", "model": "Contoso Book 14",
                         "bios_version": "CB14.317.0", "bios_date": "2026-04-15"},
        },
        "query_warnings": [],
        "kev_other_count": 0,
        "updates": [
            {"id": "u1", "month": "2026-09", "kbs": ["KB5099901"],
             "fixed_builds": ["26200.6899"], "cve_count": 1, "critical_count": 0,
             "listed": True, "kb_installed": ["KB5099901"], "applied": True,
             "applied_reason": None, "new": None},
        ],
        "exploited": [
            {"id": "k1", "cve": "CVE-2026-40001", "vendor": "Contoso",
             "product": "Invented Product", "date_added": "2026-09-02",
             "due_date": "2026-09-23", "ransomware": "Unknown",
             "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
             "listed": True, "in_updates": True, "month": "2026-09", "applied": True,
             "new": None},
        ],
        "firmware": [
            {"id": "f1", "manufacturer": "Contoso Ltd.", "model": "Contoso Book 14",
             "version": "1.20", "release_date": "2026-09-01",
             "url": "https://example.invalid/bios", "listed": False,
             "model_matches": True, "same_version": False, "newer": True, "new": None},
        ],
        "issues": [
            {"id": "i1", "title": issue_title, "published": "2026-09-10",
             "url": "https://learn.microsoft.com/windows/release-health/x",
             "listed": True, "new": None},
        ],
    }


def _detail_data(summary):
    """The detail file: the summary's lists plus empty kev_other and findings."""
    detail = {key: summary.get(key) for key in DETAIL_KEYS}
    detail["kev_other"] = []
    detail["findings"] = []
    return detail


def _clean_body(issue_title=ISSUE_TITLE):
    """A clean Polish report after the ush:summary line; every number is in the JSON."""
    return [
        "# Raport porad, 2026-09-20",
        "",
        "| Obszar | Stan | Działanie |",
        "|---|---|---|",
        "| Poprawki | zainstalowane | brak |",
        "| Wykorzystywane podatności | załatane | brak |",
        "| Firmware | wynik niesprawdzony | brak |",
        "",
        "## Stan poprawek",
        ("System: Windows 11 w wersji 25H2, kompilacja 26200.6899, wydanie Core, "
         "architektura AMD64."),
        "Zainstalowane poprawki: KB5099901, KB5099917.",
        ("- u1 aktualizacja z 2026-09 (KB5099901): zainstalowana, poprawiona kompilacja "
         "26200.6899; CVE zapisane w ustaleniach: 1, krytyczne: 0."),
        "",
        "## Wykorzystywane podatności",
        ("- k1 CVE-2026-40001 (Contoso Invented Product): w katalogu CISA od 2026-09-02, "
         "termin 2026-09-23; poprawka z 2026-09 jest zainstalowana."),
        "- Wykorzystywane podatności spoza miesięcy Windows w ustaleniach: 0.",
        "",
        "## Firmware",
        "BIOS tej maszyny: Contoso Ltd. Contoso Book 14, wersja CB14.317.0 z 2026-04-15.",
        "",
        "## Znane problemy",
        f"- i1 {issue_title}: opublikowany 2026-09-10.",
        "",
        "## Nowe od ostatniego sprawdzenia",
        "Brak wcześniejszego stanu do porównania; bieżący stan zapisano.",
        "",
        "## Niezweryfikowane",
        ("- f1 Contoso Book 14: strona spoza listy źródeł podaje wersję 1.20 "
         "z 2026-09-01, nowszą od zainstalowanej."),
        "",
        "## Zalecenia",
        "Brak zaleceń w tym przebiegu.",
        "",
        "## Nie sprawdzono",
        "<!-- ush:not-checked -->",
        "- nic.",
    ]


def _digit_free_tempdir():
    """A temporary directory whose random name holds no digits."""
    for _ in range(500):
        tmp = tempfile.TemporaryDirectory(prefix="ush-advice-")
        if not re.search(r"\d", Path(tmp.name).resolve().name):
            return tmp
        tmp.cleanup()
    raise AssertionError("could not get a temporary directory name without digits")


class TestReportProfile(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _digit_free_tempdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def _write_summary(self, name, issue_title=ISSUE_TITLE):
        summary_file = self.work / f"{name}-summary.json"
        detail_file = self.work / f"{name}-detail.json"
        summary = _clean_summary(summary_file, detail_file, issue_title=issue_title)
        detail_file.write_text(json.dumps(_detail_data(summary)), encoding="utf-8")
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        return summary_file

    def _write_report(self, summary_file, body, name):
        path = self.reports / name
        lines = [f"<!-- ush:summary {summary_file} -->", *body]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_clean_and_title_number(self):
        profile = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        self.assertTrue(profile.is_file(), f"the ush-advice report profile is missing: {profile}")

        with self.subTest("clean Polish report passes (--latest --skill ush-advice)"):
            summary_file = self._write_summary("advice")
            report = self._write_report(summary_file, _clean_body(),
                                        "advice-2026-09-20-1400.md")
            code, output = self._run(["--latest", "--skill", SKILL,
                                      "--data-dir", str(self.root)])
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertTrue(any(line.startswith("OK") for line in output.splitlines()),
                            f"expected an OK line; output:\n{output}")
            self.assertIn(report.name, output)

        with self.subTest("a number only in a finding title is not backed"):
            clean_text = (self.work / "advice-summary.json").read_text(encoding="utf-8")
            self.assertNotIn(TITLE_NUMBER, clean_text, "the number must not be in the JSON")
            self.assertNotIn(TITLE_NUMBER, str(self.root), "temp path holds the number")
            summary_file = self._write_summary("advice-title", issue_title=TITLE_WITH_NUMBER)
            self.assertIn(TITLE_NUMBER, summary_file.read_text(encoding="utf-8"))
            report = self._write_report(summary_file, _clean_body(TITLE_WITH_NUMBER),
                                        "advice-2026-09-20-1401.md")
            code, output = self._run([str(report)])
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertFalse(any(line.startswith("OK") for line in output.splitlines()),
                             f"no OK line expected; output:\n{output}")
            self.assertIn(TITLE_NUMBER, output)

        with self.subTest("ush-advice is in SKILLS"):
            words = importlib.import_module("tests.ush-common.test_check_report_words")
            self.assertIn(SKILL, words.SKILLS)

        with self.subTest("ush-advice is the skill of one SCRIPTS entry"):
            datadir = importlib.import_module("tests.ush-common.test_datadir")
            entries = [spec for spec in datadir.SCRIPTS if spec[1] == SKILL]
            self.assertEqual(len(entries), 1, f"SCRIPTS entries for {SKILL}: {entries}")
            self.assertEqual(entries[0][2], "advice")


if __name__ == "__main__":
    unittest.main()

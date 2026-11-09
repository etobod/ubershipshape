"""Shared report check: skill counts on the summary's last line (plan 067, M2).

Two optional profile keys:

- ``summary_counts``: dotted summary paths. The summary's last line gives the
  low count first and then the value of each path in order; each must equal
  its JSON value. A path whose value is ``null`` (its parent ``null``) gives no
  number, so the line has one number fewer.
- ``required_except``: a list of ``{list, field, values}``. Every item of
  ``list`` whose ``field`` is not one of ``values`` must be named in the report.

A profile without these keys checks as before. All data below is invented;
the profiles live in a temporary skills directory.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

MARKER = "<!-- ush:attention -->"
SECTION_HEADING = "## Podsumowanie"
DETAILS_HEADING = "## Zalecenia"
ACCEPTED_HEADING = "## Zaakceptowane"
NOT_CHECKED = ["## Nie sprawdzono", "<!-- ush:not-checked -->", "Nic."]

NAMES = {
    "c1": "Invented-Sync",
    "c4": "Invented-Backup",
}

RUNALL_EXTRA = {
    "summary_counts": ["accepted_counts.quiet"],
    "summary_null_words": {"accepted_counts.quiet": "zaakceptowanych nie sprawdzono"},
    "required_except": [{"list": "accepted", "field": "state", "values": ["quiet"]}],
}


def _profile(id_letters, detail_sections, extra=None):
    data = {
        "detail_sections": detail_sections,
        "id_letters": id_letters,
        "path_keys": ["detail_file", "summary_file"],
        "id_keys": ["id"],
        "required_lists": [],
        "truncated": None,
        "report_prefix": "test-",
        "summary_section": True,
    }
    if extra:
        data.update(extra)
    return data


def _block(ident, weight):
    """A rule-4 recommendation block whose main source is ident."""
    return [
        f"- **Problem:** program {NAMES[ident]} zgłasza błąd przy starcie.",
        "- **Co zrobić:** A — sprawdź ustawienia programu; B — zostaw tak i obserwuj.",
        f"- **Waga:** {weight}",
        "- **Szczegóły:**",
        "  - **Rodzaj:** obserwacja",
        "  - **Ryzyko:** brak",
        f"  - **Dowód:** {ident} {NAMES[ident]}.",
        "  - **Uprawnienia:** brak",
        "  - **Cofnięcie:** nic do cofnięcia.",
        "",
    ]


def _line(ident):
    return f"- {ident} — {NAMES[ident]}: sprawdź ustawienia programu."


def _section(last_line, part1=()):
    return [
        MARKER,
        SECTION_HEADING,
        "",
        "### Do decyzji",
        *(part1 or ["nic"]),
        "",
        "### Złamane decyzje",
        "nic",
        "",
        "### Otwarte plany naprawcze",
        "nic",
        "",
        last_line,
        "",
    ]


def _report(section, blocks, accepted_lines=None):
    """Body lines after the ush:summary line (report line 1)."""
    details = [line for block in blocks for line in block] or [
        "Brak zaleceń w tym przebiegu.", ""]
    accepted = []
    if accepted_lines is not None:
        accepted = [ACCEPTED_HEADING, "", *accepted_lines, ""]
    return ["# Raport testowy", "", *section, DETAILS_HEADING, "", *details,
            *accepted, *NOT_CHECKED]


def _accepted_item(ident, state, key, **fields):
    item = {
        "id": ident,
        "kind": "autostart",
        "key": key,
        "state": state,
        "changed": [],
        "skipped": [],
        "evidence": None,
        "accepted_on": "2026-10-01",
        "reason": None,
    }
    item.update(fields)
    return item


def _counts(items):
    counts = {"quiet": 0, "back": 0, "gone": 0, "not_checked": 0}
    for item in items:
        counts[item["state"]] += 1
    return counts


class _CountsCase(unittest.TestCase):
    """The checker with invented profiles in a temporary skills directory."""

    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.summary_file = self.work_dir / "summary.json"
        self.detail_file = self.work_dir / "detail.json"
        self.skills_dir = self.root / "skills"
        patcher = mock.patch.object(self.check, "SKILLS_DIR", self.skills_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_profile(self, skill, profile):
        path = self.skills_dir / skill / "data" / "report-profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile), encoding="utf-8")

    def write_runall(self, accepted):
        """An invented ush-runall profile and summary with the accepted list.

        accepted is a list of items, or None for an accepted.json that could
        not be used (accepted and accepted_counts both null).
        """
        self.write_profile("ush-runall",
                           _profile("ca", ["things", "accepted"], RUNALL_EXTRA))
        things = [{"id": ident, "name": name} for ident, name in NAMES.items()]
        self.detail_file.write_text(
            json.dumps({"things": things, "accepted": accepted}), encoding="utf-8")
        data = {
            "skill": "ush-runall",
            "status": "read",
            "things": things,
            "accepted": accepted,
            "accepted_counts": None if accepted is None else _counts(accepted),
            "summary_file": str(self.summary_file),
            "detail_file": str(self.detail_file),
        }
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

    def write_health(self):
        """An invented ush-health profile without summary_counts and required_except."""
        self.write_profile("ush-health", _profile("c", ["things"]))
        things = [{"id": ident, "name": name} for ident, name in NAMES.items()]
        self.detail_file.write_text(json.dumps({"things": things}), encoding="utf-8")
        data = {
            "skill": "ush-health",
            "status": "read",
            "things": things,
            # A 2 the JSON does back, so an extra 2 on the last line is wrong by
            # the line's form, not because the number is unknown.
            "uptime_days": 2,
            "summary_file": str(self.summary_file),
            "detail_file": str(self.detail_file),
        }
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

    def assert_ok(self, code, output):
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertTrue(any(line.startswith("OK:") for line in output.splitlines()),
                        f"expected an OK line; output:\n{output}")

    def assert_fails(self, code, output):
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertFalse(any(line.startswith("OK:") for line in output.splitlines()),
                         f"no OK line expected; output:\n{output}")


class TestSummaryCounts(_CountsCase):
    def test_accepted_count(self):
        accepted = [
            _accepted_item("a1", "quiet", "Invented-Tray", evidence="ush-inventory s4"),
            _accepted_item("a2", "quiet", "Invented-Helper", evidence="ush-inventory s7"),
        ]
        self.write_runall(accepted)
        blocks = [_block("c4", "niska")]
        quiet_line = ["Bez zmian od akceptacji: 2."]

        with self.subTest("1 low and 2 accepted, equal to accepted_counts.quiet, passes"):
            line = "Nic więcej nie wymaga uwagi: 1 niskich, 2 zaakceptowanych."
            body = _report(_section(line), blocks, quiet_line)
            code, output = self.run_report(body, "accepted-2.md")
            self.assert_ok(code, output)

        with self.subTest("3 accepted against accepted_counts.quiet 2 fails"):
            line = "Nic więcej nie wymaga uwagi: 1 niskich, 3 zaakceptowanych."
            body = _report(_section(line), blocks, quiet_line)
            code, output = self.run_report(body, "accepted-3.md")
            self.assert_fails(code, output)
            self.assertIn("accepted_counts.quiet", output)

        with self.subTest("2 accepted also called not checked fails"):
            line = ("Nic więcej nie wymaga uwagi: 1 niskich, 2 zaakceptowanych; "
                    "zaakceptowanych nie sprawdzono.")
            body = _report(_section(line), blocks)
            code, output = self.run_report(body, "accepted-2-not-checked.md")
            self.assert_fails(code, output)
            self.assertIn("must not say", output)

    def test_accepted_not_checked(self):
        self.write_runall(None)
        blocks = [_block("c4", "niska")]

        with self.subTest("accepted null: the line without M passes"):
            line = "Nic więcej nie wymaga uwagi: 1 niskich; zaakceptowanych nie sprawdzono."
            body = _report(_section(line), blocks)
            code, output = self.run_report(body, "accepted-null.md")
            self.assert_ok(code, output)

        with self.subTest("accepted null: a line that still gives M fails"):
            line = "Nic więcej nie wymaga uwagi: 1 niskich, 0 zaakceptowanych."
            body = _report(_section(line), blocks)
            code, output = self.run_report(body, "accepted-null-m.md")
            self.assert_fails(code, output)

        with self.subTest("accepted null: a line that hides it was not checked fails"):
            line = "Nic więcej nie wymaga uwagi: 1 niskich."
            body = _report(_section(line), blocks)
            code, output = self.run_report(body, "accepted-null-silent.md")
            self.assert_fails(code, output)
            self.assertIn("zaakceptowanych nie sprawdzono", output)

    def test_required_except_quiet(self):
        accepted = [
            _accepted_item("a1", "quiet", "Invented-Tray", evidence="ush-inventory s4"),
            _accepted_item("a2", "back", "Invented-Helper", evidence="ush-inventory s7",
                           changed=[{"field": "command", "accepted": "helper.exe",
                                     "now": "helper.exe --boot"}]),
            _accepted_item("a3", "gone", "Invented-Agent"),
            _accepted_item("a4", "not_checked", "Invented-Updater",
                           reason="ush-inventory detail file could not be read"),
        ]
        self.write_runall(accepted)
        blocks = [_block("c4", "niska")]
        line = "Nic więcej nie wymaga uwagi: 1 niskich, 1 zaakceptowanych."
        quiet = "Bez zmian od akceptacji: 1."
        back = "- a2 — Invented-Helper: wpis autostartu zmienił polecenie; wróciło."
        gone = ("- a3 — Invented-Agent: wpisu już nie ma; można go usunąć z "
                "zaakceptowanych (--remove).")
        not_checked = "- a4 — Invented-Updater: nie sprawdzono, szczegóły nie do odczytu."

        with self.subTest("a2, a3 and a4 named, quiet a1 not named, passes"):
            body = _report(_section(line), blocks, [quiet, back, gone, not_checked])
            self.assertFalse(any("a1" in text for text in body))
            code, output = self.run_report(body, "required-all.md")
            self.assert_ok(code, output)

        with self.subTest("the gone item a3 left out fails"):
            body = _report(_section(line), blocks, [quiet, back, not_checked])
            code, output = self.run_report(body, "required-no-a3.md")
            self.assert_fails(code, output)
            self.assertIn("not named in the report: a3", output)

    def test_other_skills_unchanged(self):
        self.write_health()
        blocks = [_block("c1", "wysoka")]
        part1 = [_line("c1")]

        with self.subTest("a profile without the new keys: '0 niskich.' passes"):
            line = "Nic więcej nie wymaga uwagi: 0 niskich."
            body = _report(_section(line, part1), blocks)
            code, output = self.run_report(body, "health-ok.md")
            self.assert_ok(code, output)

        with self.subTest("an extra number on the last line still fails"):
            line = "Nic więcej nie wymaga uwagi: 0 niskich, 2 zaakceptowanych."
            body = _report(_section(line, part1), blocks)
            code, output = self.run_report(body, "health-extra.md")
            self.assert_fails(code, output)


if __name__ == "__main__":
    unittest.main()

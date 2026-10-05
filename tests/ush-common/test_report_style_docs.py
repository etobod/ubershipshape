"""The shared report style document and the per-skill report formats agree.

test_every_format_follows_style reads the shipped documents and looks for phrases
the common style replaced. test_examples_match_checker cuts the Good:/Bad: examples
of rules 1, 7 and 9 out of report-style.md and runs them through check_report with
an invented events summary: Good examples pass, Bad examples fail. All data invented.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path

from tests.skill_loader import REPO_ROOT, load_script

SKILLS = REPO_ROOT / "skills"
STYLE_DOC = SKILLS / "ush-common" / "references" / "report-style.md"
SUMMARY_CONTRACT = SKILLS / "ush-common" / "references" / "summary-contract.md"
EVENTS_SKILL = SKILLS / "ush-events" / "SKILL.md"
INVENTORY_SKILL = SKILLS / "ush-inventory" / "SKILL.md"

# Phrases no report format may contain once wrapped lines are joined.
FORBIDDEN_IN_FORMATS = (
    "as UTC",
    "`generated_at`, UTC",
    "do not convert times",
    "percent free",
    "`Other groups: g29 (2), g22 (1)",
    "| - |",
    "`--data-dir` value of a block for an elevated shell",
    "any other code block writes it from the environment",
    "`--data-dir` of an elevated-shell block",
    "(`1500.0`, not",
    "may be written in local format",
)
EXACT_JSON_PHRASE = "exactly as the JSON has it"  # checked case-insensitively

ICONS = "(?:\U0001F527|\U0001F50D|✅|❌)"
LEGEND_LINE = re.compile(r"^\s*-\s+" + ICONS + r"\s")
LEGEND_WITH_HYPHEN = re.compile(r"^\s*-\s+" + ICONS + r"\s[^\n]*?\s-\s")
TABLE_DOT_DECIMAL = re.compile(r"\|\s*\d+\.\d+\s*\|")
DOT_DECIMAL_PERCENT = re.compile(r"\d+\.\d+\s*%")
DOT_DECIMAL_PERCENT_WORD = re.compile(r"\d+\.\d+ percent")

LEGEND_SKILLS = ("ush-events", "ush-health", "ush-settings", "ush-inventory")

STYLE_DOC_REQUIRED = (
    "Waga",
    "Rodzaj",
    "Ryzyko",
    "Dowód",
    "Uprawnienia",
    "Cofnięcie",
    "—",
    "Set-Location",
    "--data-dir",
    "Brak zaleceń w tym przebiegu.",
)

# Rule markers of the examples run through the checker; each one gets the
# five-group line appended unless it is the long-list rule itself.
RULE_MARKERS = {
    "rule 1": ("**Time.**", True),
    "rule 7": ("**Long lists.**", False),
    "rule 9": ("**Script commands.**", True),
}
NEXT_RULE = re.compile(r"^\d+\.\s+\*\*")
FENCE_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})")

GROUPS_LINE = (
    "Grupy: g3 Invented-Disk (40), g29 Service Control Manager (2), "
    "g22 Kernel-Power (1), g7 Invented-Sync (1), g12 Invented-Update (1)."
)


def plus_two(dt):
    """A fixed +02:00 zone, independent of the machine running the tests."""
    return dt.astimezone(timezone(timedelta(hours=2)))


def _join(text):
    """Join wrapped lines: every whitespace run holding a newline becomes one space."""
    return re.sub(r"\s*\n\s*", " ", text)


def _sentences(joined):
    return re.split(r"\.(?=\s|$)", joined)


def _formats():
    return sorted(SKILLS.glob("ush-*/references/report-format.md"))


def _rule_section(lines, marker):
    """Lines of the rule whose line holds marker, up to the next numbered rule; None if absent."""
    for start, line in enumerate(lines):
        if marker in line:
            break
    else:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if NEXT_RULE.match(lines[index]):
            end = index
            break
    return lines[start:end]


def _examples(section):
    """(label, content lines, error) for every Good:/Bad: line followed by a fenced block."""
    found = []
    index = 0
    while index < len(section):
        label = section[index].strip()
        index += 1
        if label not in ("Good:", "Bad:"):
            continue
        while index < len(section) and not section[index].strip():
            index += 1
        if index >= len(section):
            found.append((label, None, "no fenced block after the label"))
            break
        opening = FENCE_OPEN.match(section[index])
        if not opening:
            found.append((label, None, f"no fenced block after the label: {section[index]!r}"))
            continue
        indent, fence = opening.group(1), opening.group(2)
        closing = re.compile("^" + re.escape(fence[0]) + "{" + str(len(fence)) + ",}$")
        content = []
        index += 1
        closed = False
        while index < len(section):
            line = section[index]
            index += 1
            if closing.match(line.strip()):
                closed = True
                break
            content.append(line[len(indent):] if line.startswith(indent) else line.lstrip())
        if not closed:
            found.append((label, None, "fenced block is not closed inside the rule"))
            continue
        found.append((label, content, None))
    return found


class TestReportStyleDocs(unittest.TestCase):
    def test_every_format_follows_style(self):
        formats = _formats()
        self.assertGreaterEqual(len(formats), 5, f"report formats found: {formats}")

        for path in formats:
            rel = path.relative_to(REPO_ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            joined = _join(text)
            lines = text.splitlines()

            for phrase in FORBIDDEN_IN_FORMATS:
                with self.subTest(format=rel, check=f"no phrase {phrase!r}"):
                    self.assertNotIn(phrase, joined)

            with self.subTest(format=rel, check=f"no phrase {EXACT_JSON_PHRASE!r} in any case"):
                self.assertNotIn(EXACT_JSON_PHRASE.lower(), joined.lower())

            with self.subTest(format=rel, check="no table cell with a dot decimal"):
                bad = [line for line in lines
                       if line.lstrip().startswith("|") and TABLE_DOT_DECIMAL.search(line)]
                self.assertEqual(bad, [])

            with self.subTest(format=rel, check="no dot decimal with a percent"):
                bad = [line for line in lines
                       if DOT_DECIMAL_PERCENT.search(line) or DOT_DECIMAL_PERCENT_WORD.search(line)]
                self.assertEqual(bad, [])

            with self.subTest(format=rel, check="recommendation fields point to rule 4"):
                field_sentences = [s for s in _sentences(joined)
                                   if "`weight`, `kind`, `risk`" in s or "rule 4" in s]
                self.assertTrue(field_sentences,
                                "no sentence names `weight`, `kind`, `risk` or rule 4")
                for sentence in field_sentences:
                    self.assertIn("report-style.md", sentence)

            with self.subTest(format=rel, check="legend lines use a dash, not a hyphen"):
                bad = [line for line in lines if LEGEND_WITH_HYPHEN.match(line)]
                self.assertEqual(bad, [])

            with self.subTest(format=rel, check="refers to report-style.md"):
                self.assertIn("report-style.md", text)

        for skill in LEGEND_SKILLS:
            path = SKILLS / skill / "references" / "report-format.md"
            with self.subTest(format=skill, check="has a legend line with an icon"):
                self.assertTrue(path.is_file(), f"missing {path}")
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertTrue([line for line in lines if LEGEND_LINE.match(line)])

        with self.subTest(check="ush-events SKILL.md has no old risk layout"):
            self.assertNotIn("**risk:** high -", _join(EVENTS_SKILL.read_text(encoding="utf-8")))

        with self.subTest(check="ush-inventory SKILL.md has no elevated-shell-only exception"):
            self.assertNotIn("`--data-dir` of an elevated-shell block",
                             _join(INVENTORY_SKILL.read_text(encoding="utf-8")))

        with self.subTest(check="report-style.md exists"):
            self.assertTrue(STYLE_DOC.is_file(), f"missing {STYLE_DOC}")
        style_text = STYLE_DOC.read_text(encoding="utf-8") if STYLE_DOC.is_file() else ""
        for required in STYLE_DOC_REQUIRED:
            with self.subTest(check=f"report-style.md contains {required!r}"):
                self.assertIn(required, style_text)

        with self.subTest(check="summary-contract.md refers to report-style.md"):
            self.assertIn("report-style.md", SUMMARY_CONTRACT.read_text(encoding="utf-8"))

    def _make_temp_root(self):
        # The temp path backs no number: it stands only on the unscanned
        # ush:summary line and under the profile's path_keys.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def _write_summary(self, root):
        work = root / "work"
        work.mkdir()
        detail_file = work / "events-detail.json"
        summary_file = work / "events-summary.json"
        detail_file.write_text(
            json.dumps({"groups": [], "noise": [], "boots": [], "anomalies": []}),
            encoding="utf-8",
        )
        summary = {
            "skill": "ush-events",
            "generated_at": "2026-09-30T07:26:40+00:00",
            "group_count": 5,
            "groups": [
                {"id": "g3", "provider": "Invented-Disk", "count": 40},
                {"id": "g29", "provider": "Service Control Manager", "count": 2},
                {"id": "g22", "provider": "Kernel-Power", "count": 1},
                {"id": "g7", "provider": "Invented-Sync", "count": 1},
                {"id": "g12", "provider": "Invented-Update", "count": 1},
            ],
            "anomalies": [],
            "dumps": {"files": []},
            "detail_file": str(detail_file),
            "summary_file": str(summary_file),
        }
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        return summary_file

    def _run_example(self, check, reports_dir, summary_file, name, content, with_groups):
        body = [f"<!-- ush:summary {summary_file} -->", "# Raport", *content]
        if with_groups:
            body.append(GROUPS_LINE)
        body += ["## Nie sprawdzono", "<!-- ush:not-checked -->", "Nic."]
        report = reports_dir / name
        report.write_text("\n".join(body) + "\n", encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = check.main([str(report)], to_local=plus_two)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_examples_match_checker(self):
        self.assertTrue(STYLE_DOC.is_file(), f"missing {STYLE_DOC}")
        lines = STYLE_DOC.read_text(encoding="utf-8").splitlines()

        check = load_script("ush-common", "check_report")
        root = self._make_temp_root()
        reports_dir = root / "reports"
        reports_dir.mkdir()
        summary_file = self._write_summary(root)

        for rule, (marker, with_groups) in RULE_MARKERS.items():
            section = _rule_section(lines, marker)
            with self.subTest(rule=rule, check="section found"):
                self.assertIsNotNone(section, f"no line holds {marker!r}")
            examples = _examples(section or [])
            labels = [label for label, content, _ in examples if content is not None]
            with self.subTest(rule=rule, check="has a Good and a Bad example"):
                self.assertIn("Good:", labels)
                self.assertIn("Bad:", labels)

            for number, (label, content, error) in enumerate(examples, 1):
                with self.subTest(rule=rule, example=number, label=label):
                    self.assertIsNone(error, error)
                    name = f"example-{rule.replace(' ', '-')}-{number}.md"
                    code, output = self._run_example(
                        check, reports_dir, summary_file, name, content, with_groups
                    )
                    expected = 0 if label == "Good:" else 1
                    self.assertEqual(
                        code, expected,
                        f"{label} example of {rule}:\n" + "\n".join(content)
                        + f"\noutput:\n{output}",
                    )


if __name__ == "__main__":
    unittest.main()

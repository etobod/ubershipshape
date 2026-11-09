"""Shared report check: the summary section at the top of a report (plan 055, M1).

With the profile field ``summary_section`` set, a report opens with the
``<!-- ush:attention -->`` marker directly before its first ``##`` heading. The
section names the main source (first evidence id) of every high or medium
recommendation exactly once, names no id that is not a main source, and ends
with a line whose number is the count of low recommendations it does not name.
On OK the checker prints the section after the OK line. All data below is
invented; the profile lives in a temporary skills directory.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOT_CHECKED = ["## Nie sprawdzono", "<!-- ush:not-checked -->", "Nic."]
MARKER = "<!-- ush:attention -->"
SECTION_HEADING = "## Podsumowanie"
DETAILS_HEADING = "## Zalecenia"
FENCE = "```"
OMIT = object()  # profile without the summary_section key

# The temporary path ends up in the summary JSON; it must not hold the low
# count that K7 shows to be absent from the JSON.
UNSAFE_PATH = re.compile(r"13")

NAMES = {
    "c1": "Invented-Sync", "c2": "Invented-Disk", "c3": "Invented-Update",
    "c4": "Invented-Backup", "c5": "Invented-Print", "c6": "Invented-Audio",
    "c7": "Invented-Video", "c8": "Invented-Mail",
}
# 13 ids for the 13 low blocks of K7; none of them holds "13".
LOW_IDS = [f"c{n}" for n in range(20, 33)]
for _index, _ident in enumerate(LOW_IDS):
    NAMES[_ident] = f"Invented-Low-{chr(ord('A') + _index)}"


def _profile(summary_section):
    data = {
        "detail_sections": ["things"],
        "id_letters": "c",
        "path_keys": ["detail_file", "summary_file"],
        "id_keys": ["id"],
        "required_lists": [],
        "truncated": None,
        "report_prefix": "test-",
    }
    if summary_section is not OMIT:
        data["summary_section"] = summary_section
    return data


def _items():
    return [{"id": ident, "name": name} for ident, name in NAMES.items()]


def _block(ids, weight):
    """A rule-4 recommendation block; its evidence names ids in this order."""
    evidence = ", ".join(f"{ident} {NAMES[ident]}" for ident in ids)
    return [
        f"- **Problem:** program {NAMES[ids[0]]} zgłasza błąd przy starcie.",
        "- **Co zrobić:** A — sprawdź ustawienia programu; B — zostaw tak i obserwuj.",
        f"- **Waga:** {weight}",
        "- **Szczegóły:**",
        "  - **Rodzaj:** obserwacja",
        "  - **Ryzyko:** brak",
        f"  - **Dowód:** {evidence}.",
        "  - **Uprawnienia:** brak",
        "  - **Cofnięcie:** nic do cofnięcia.",
        "",
    ]


def _line(ident):
    """A part-1 or part-2 line naming ident as its main source."""
    return f"- {ident} — {NAMES[ident]}: sprawdź ustawienia programu."


def _count_line(count):
    return f"Nic więcej nie wymaga uwagi: {count} niskich."


# The rule-4 labels of a recommendation block in each report language.
LABELS = {
    "pl": {"problem": "Problem", "todo": "Co zrobić", "weight": "Waga",
           "details": "Szczegóły", "kind": "Rodzaj", "risk": "Ryzyko",
           "evidence": "Dowód", "permissions": "Uprawnienia", "rollback": "Cofnięcie",
           "none": "brak", "high": "wysoka", "medium": "średnia", "low": "niska"},
    "en": {"problem": "Problem", "todo": "What to do", "weight": "Weight",
           "details": "Details", "kind": "Kind", "risk": "Risk",
           "evidence": "Evidence", "permissions": "Permissions", "rollback": "Rollback",
           "none": "none", "high": "high", "medium": "medium", "low": "low"},
}


def _free_block(name, evidence, weight, lang="pl", with_weight=True, with_evidence=True):
    """A rule-4 block with a free evidence text; weight is high, medium or low."""
    label = LABELS[lang]
    lines = [
        f"- **{label['problem']}:** {name} — błąd przy starcie.",
        f"- **{label['todo']}:** A — sprawdź ustawienia; B — zostaw tak i obserwuj.",
    ]
    if with_weight:
        lines.append(f"- **{label['weight']}:** {label[weight]}")
    lines += [
        f"- **{label['details']}:**",
        f"  - **{label['kind']}:** {label['none']}",
        f"  - **{label['risk']}:** {label['none']}",
    ]
    if with_evidence:
        lines.append(f"  - **{label['evidence']}:** {evidence}.")
    lines += [
        f"  - **{label['permissions']}:** {label['none']}",
        f"  - **{label['rollback']}:** {label['none']}.",
        "",
    ]
    return lines


def _problem_line(block):
    return block[0]


def _section(part1=(), part2=(), plans=(), low=0):
    return [
        MARKER,
        SECTION_HEADING,
        "",
        "### Do decyzji",
        *(part1 or ["nic"]),
        "",
        "### Złamane decyzje",
        *(part2 or ["nic"]),
        "",
        "### Otwarte plany naprawcze",
        *(plans or ["nic"]),
        "",
        _count_line(low),
        "",
    ]


def _report(section, blocks):
    """Body lines after the ush:summary line (report line 1)."""
    details = [line for block in blocks for line in block] or [
        "Brak zaleceń w tym przebiegu.", ""]
    return ["# Raport testowy", "", *section, DETAILS_HEADING, "", *details, *NOT_CHECKED]


def _line_number(body, text):
    """Report line number of text: line 1 is ush:summary, body starts on line 2."""
    return body.index(text) + 2


def _expected_section(body):
    """The section from its heading to the line before the next ## heading, no markers."""
    start = body.index(SECTION_HEADING)
    end = body.index(DETAILS_HEADING)
    lines = [line for line in body[start:end] if not line.startswith("<!-- ush:")]
    return _strip_trailing_blank(lines)


def _strip_trailing_blank(lines):
    lines = list(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _clean_temp_dir():
    for _ in range(50):
        tmp = tempfile.TemporaryDirectory()
        if not UNSAFE_PATH.search(str(Path(tmp.name).resolve())):
            return tmp
        tmp.cleanup()
    raise AssertionError("every temporary directory holds 13")


class _SummaryCase(unittest.TestCase):
    """The checker with an invented ush-test profile in a temporary skills dir."""

    summary_section = True

    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _clean_temp_dir()
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
        self.write_profile(self.summary_section)
        self.write_data(_items())

    def write_profile(self, summary_section):
        profile_path = self.skills_dir / "ush-test" / "data" / "report-profile.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(_profile(summary_section)), encoding="utf-8")

    def write_data(self, items):
        self.detail_file.write_text(json.dumps({"things": items}), encoding="utf-8")
        data = {
            "skill": "ush-test",
            "status": "read",
            "things": items,
            "summary_file": str(self.summary_file),
            "detail_file": str(self.detail_file),
        }
        text = json.dumps(data)
        self.summary_file.write_text(text, encoding="utf-8")
        return text

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

    def assert_names(self, output, ident):
        self.assertRegex(output, rf"\b{re.escape(ident)}\b",
                         f"output does not name {ident}:\n{output}")

    def assert_line_problem(self, output, line_no, ident):
        found = any(
            re.search(rf"\bline {line_no}\b", line) and re.search(rf"\b{ident}\b", line)
            for line in output.splitlines()
        )
        self.assertTrue(found, f"no output line names line {line_no} and {ident}:\n{output}")

    def assert_prints_section(self, output, body):
        lines = output.splitlines()
        self.assertTrue(lines and lines[0].startswith("OK:"),
                        f"the output should start with the OK line:\n{output}")
        self.assertEqual(_strip_trailing_blank(lines[1:]), _expected_section(body))


class TestSection(_SummaryCase):
    def test_missing_section(self):
        blocks = [_block(["c1"], "wysoka")]
        with_marker = _report(_section(part1=[_line("c1")]), blocks)

        with self.subTest("control: the same report with the marker passes"):
            code, output = self.run_report(with_marker, "with-marker.md")
            self.assert_ok(code, output)

        with self.subTest("the section text without the marker"):
            body = [line for line in with_marker if line != MARKER]
            code, output = self.run_report(body, "no-marker.md")
            self.assert_fails(code, output)
            self.assertIn("ush:attention", output)

        with self.subTest("no section at all"):
            body = ["# Raport testowy", "", DETAILS_HEADING, "",
                    *[line for block in blocks for line in block], *NOT_CHECKED]
            code, output = self.run_report(body, "no-section.md")
            self.assert_fails(code, output)
            self.assertIn("ush:attention", output)

    def test_prints_section(self):
        plans = [f"{FENCE}text", "2026-11-08-repair-plan-ush-test.md", FENCE]
        section = _section(
            part1=[_line("c1"), _line("c3")],
            plans=plans,
            low=1,
        )
        # A marker inside the section is left out of the printed text.
        section.insert(section.index("### Do decyzji"), "<!-- ush:detail c1 -->")
        body = _report(section, [
            _block(["c1", "c2"], "wysoka"),
            _block(["c3"], "średnia"),
            _block(["c4"], "niska"),
        ])
        code, output = self.run_report(body, "prints.md")
        self.assert_ok(code, output)
        self.assert_prints_section(output, body)
        printed = output.splitlines()[1:]
        self.assertIn("### Do decyzji", printed, "### sub-headings belong to the section")
        self.assertIn("2026-11-08-repair-plan-ush-test.md", printed)
        self.assertEqual(printed.count(FENCE), 1, "the closing fence is printed")
        self.assertIn(f"{FENCE}text", printed, "the opening fence is printed")
        self.assertFalse(any("ush:" in line for line in printed),
                         f"no marker line may be printed:\n{output}")
        self.assertNotIn(DETAILS_HEADING, printed)
        self.assertNotIn("- **Problem:** program Invented-Sync zgłasza błąd przy starcie.",
                         printed)

    def test_prints_utf8_on_a_narrow_code_page(self):
        # Final review 055: the printed section is copied word for word into the chat,
        # so it is UTF-8 whatever the code page of the pipe is.
        body = _report(_section(part1=[_line("c1")]), [_block(["c1"], "wysoka")])
        path = self.reports_dir / "utf8.md"
        first = f"<!-- ush:summary {self.summary_file} -->"
        path.write_text(chr(10).join([first, *body]) + chr(10), encoding="utf-8")
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        with mock.patch("sys.stdout", stream):
            code = self.check.main([str(path)])
            stream.flush()
        self.assertEqual(code, 0)
        text = raw.getvalue().decode("utf-8")
        self.assertIn("Nic więcej nie wymaga uwagi", text)

    def test_section_not_first(self):
        blocks = [_block(["c1"], "wysoka")]
        section = _section(part1=[_line("c1")])

        with self.subTest("control: the marker directly before the first ## heading passes"):
            code, output = self.run_report(_report(section, blocks), "first.md")
            self.assert_ok(code, output)

        with self.subTest("a blank line between the marker and the heading"):
            spaced = [MARKER, "", *section[1:]]
            code, output = self.run_report(_report(spaced, blocks), "spaced.md")
            self.assert_fails(code, output)
            self.assertIn("ush:attention", output)

        with self.subTest("the section after another ## heading"):
            body = ["# Raport testowy", "", DETAILS_HEADING, "",
                    *[line for block in blocks for line in block], *section, *NOT_CHECKED]
            code, output = self.run_report(body, "second.md")
            self.assert_fails(code, output)
            self.assertIn("ush:attention", output)

        with self.subTest("the marker before a ### heading"):
            body = ["# Raport testowy", "", SECTION_HEADING, "", MARKER, *section[3:],
                    DETAILS_HEADING, "", *[line for block in blocks for line in block],
                    *NOT_CHECKED]
            code, output = self.run_report(body, "sub-heading.md")
            self.assert_fails(code, output)
            self.assertIn("ush:attention", output)


class TestPlacement(_SummaryCase):
    """Final review 055 round 2: only the header stands above the summary section.

    The header is the ush:summary line, the # title and the paragraph under the
    title (plan 058 M2): after skipping blank and ush: marker lines, the run of
    non-blank lines up to the first blank line. A line starting with ``|``,
    ``#``, a list marker or a code fence is never a paragraph line. Blank lines
    and ush: marker lines may stand between the header and the
    ``<!-- ush:attention -->`` line, nothing else.
    """

    def _with_header(self, header):
        blocks = [_block(["c1"], "wysoka")]
        body = _report(_section(part1=[_line("c1")]), blocks)
        title = body.index("# Raport testowy")
        return [*body[:title + 1], *header, *body[title + 1:]]

    def test_clean_headers_pass(self):
        cases = {
            "title only": [],
            "title and its line": ["Przebieg ręczny, tylko odczyt."],
            "its line after a blank": ["", "Przebieg ręczny, tylko odczyt."],
            "its line and a detail marker": ["Przebieg ręczny, tylko odczyt.", "",
                                             "<!-- ush:detail c1 -->"],
            # Plan 058 M2 K1: the header is the paragraph under the title.
            "a two-line paragraph under the title": ["Przebieg ręczny, tylko odczyt.",
                                                     "Dane z ostatniego przebiegu."],
            "a blank, then a two-line paragraph": ["", "Przebieg ręczny, tylko odczyt.",
                                                   "Dane z ostatniego przebiegu."],
            # M2 code-review: a # with no space after it is no heading (clean data).
            "a paragraph line starting with #word": ["#BC: przebieg ręczny, tylko odczyt."],
            # M2 code-review round 2: an ordered marker other than 1 cannot interrupt a
            # paragraph, so a wrapped line starting with a year stays paragraph text.
            "a wrapped line starting with a year": ["Dane z przebiegu w",
                                                    "2025. roku, tylko odczyt."],
        }
        # The year of the wrapped line is a number the report must have backed.
        data = json.loads(self.summary_file.read_text(encoding="utf-8"))
        data["year"] = 2025
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")
        for label, header in cases.items():
            with self.subTest(label):
                code, output = self.run_report(self._with_header(header), "clean-header.md")
                self.assert_ok(code, output)

    def test_unheaded_dashboard_fails(self):
        table = ["| # | Obszar | Stan |", "|---|---|---|", "| a | Dysk | ok |"]
        # Plan 058 M2 K2: a table line is never a paragraph line, so the table's
        # first line is the one reported in every case.
        one_line = ["Przebieg ręczny, tylko odczyt."]
        two_lines = ["Przebieg ręczny, tylko odczyt.", "Dane z ostatniego przebiegu."]
        cases = {
            "a table directly under the title": (table, table[0]),
            "a table directly after the header line, no blank": ([*one_line, *table],
                                                                 table[0]),
            "a table after a two-line paragraph and a blank": ([*two_lines, "", *table],
                                                               table[0]),
            "a table after a one-line paragraph and a blank": ([*one_line, "", *table],
                                                               table[0]),
        }
        for label, (header, first_bad) in cases.items():
            with self.subTest(label):
                body = self._with_header(header)
                code, output = self.run_report(body, "dashboard-first.md")
                self.assert_fails(code, output)
                line_no = _line_number(body, first_bad)
                self.assertTrue(
                    any(re.search(rf"\bline {line_no}\b", line) and "directly after the header"
                        in line for line in output.splitlines()),
                    f"no output line names line {line_no} and the header:\n{output}")

    def test_block_lines_are_no_paragraph(self):
        # M2 code-review: a heading, a list line or a fence directly under the title
        # is never a header paragraph line; its first line is reported.
        cases = {
            "a heading": ["### Stan", "Dysk: ok."],
            "an empty heading": ["###", "Dysk: ok."],
            "a bullet list": ["- Dysk: ok", "- Pamięć: ok"],
            "a numbered list": ["1. Dysk: ok", "2. Pamięć: ok"],
            "a fence": ["```text", "Dysk: ok", "```"],
        }
        for label, header in cases.items():
            with self.subTest(label):
                body = self._with_header(header)
                code, output = self.run_report(body, "block-under-title.md")
                self.assert_fails(code, output)
                line_no = _line_number(body, header[0])
                self.assertTrue(
                    any(re.search(rf"\bline {line_no}\b", line) and "directly after the header"
                        in line for line in output.splitlines()),
                    f"no output line names line {line_no} and the header:\n{output}")


class TestIds(_SummaryCase):
    def test_unknown_id(self):
        blocks = [_block(["c1", "c2"], "wysoka")]

        with self.subTest("control: the main source alone passes"):
            body = _report(_section(part1=[_line("c1")]), blocks)
            code, output = self.run_report(body, "main-source.md")
            self.assert_ok(code, output)

        with self.subTest("an id that is only a later evidence id"):
            body = _report(_section(part1=[_line("c1"), _line("c2")]), blocks)
            code, output = self.run_report(body, "later-evidence.md")
            self.assert_fails(code, output)
            self.assert_line_problem(output, _line_number(body, _line("c2")), "c2")

        with self.subTest("an id of no recommendation at all"):
            body = _report(_section(part1=[_line("c1"), _line("c5")]), blocks)
            code, output = self.run_report(body, "no-recommendation.md")
            self.assert_fails(code, output)
            self.assert_line_problem(output, _line_number(body, _line("c5")), "c5")

    def test_high_medium_named_once(self):
        blocks = [_block(["c1", "c2"], "wysoka"), _block(["c3"], "średnia")]

        with self.subTest("control: each named once passes"):
            body = _report(_section(part1=[_line("c1"), _line("c3")]), blocks)
            code, output = self.run_report(body, "once.md")
            self.assert_ok(code, output)

        with self.subTest("a high block named by no line"):
            body = _report(_section(part1=[_line("c3")]), blocks)
            code, output = self.run_report(body, "high-unnamed.md")
            self.assert_fails(code, output)
            self.assert_names(output, "c1")

        with self.subTest("a medium block named by no line"):
            body = _report(_section(part1=[_line("c1")]), blocks)
            code, output = self.run_report(body, "medium-unnamed.md")
            self.assert_fails(code, output)
            self.assert_names(output, "c3")

        with self.subTest("a medium block named by 2 lines"):
            body = _report(
                _section(part1=[_line("c1"), _line("c3"),
                                f"- c3 — {NAMES['c3']}: zostaw tak i obserwuj."]),
                blocks)
            code, output = self.run_report(body, "medium-twice.md")
            self.assert_fails(code, output)
            self.assert_names(output, "c3")

        with self.subTest("a high block named in part 1 and again in part 2"):
            body = _report(
                _section(part1=[_line("c1"), _line("c3")], part2=[_line("c1")]), blocks)
            code, output = self.run_report(body, "high-twice.md")
            self.assert_fails(code, output)
            self.assert_names(output, "c1")

    def test_shared_main_source(self):
        # Final review 055: two high or medium blocks with the same main source each
        # get a line of their own, so the source is named once per block.
        blocks = [_block(["c1", "c2"], "wysoka"), _block(["c1", "c3"], "średnia")]
        second = f"- c1 — {NAMES['c1']}: zostaw tak i obserwuj."

        with self.subTest("one line per block passes"):
            body = _report(_section(part1=[_line("c1"), second]), blocks)
            code, output = self.run_report(body, "shared-two.md")
            self.assert_ok(code, output)

        with self.subTest("one line for two blocks fails"):
            body = _report(_section(part1=[_line("c1")]), blocks)
            code, output = self.run_report(body, "shared-one.md")
            self.assert_fails(code, output)
            self.assert_names(output, "c1")

        with self.subTest("three lines for two blocks fails"):
            body = _report(_section(part1=[_line("c1"), second, second]), blocks)
            code, output = self.run_report(body, "shared-three.md")
            self.assert_fails(code, output)
            self.assert_names(output, "c1")

    def test_shared_main_source_low(self):
        # Plan 058 M1 K2 (architect ruling, replaces the 055 round 2 rule): a section
        # line naming c1 names every recommendation whose main source is c1, the low
        # one included; the lines naming c1 equal its high and medium blocks.
        blocks = [_block(["c1", "c2"], "wysoka"), _block(["c1", "c3"], "niska")]
        second = f"- c1 — {NAMES['c1']}: zostaw tak i obserwuj."

        with self.subTest("one line naming c1 names the low block too: count 0 passes"):
            body = _report(_section(part1=[_line("c1")], low=0), blocks)
            code, output = self.run_report(body, "shared-low-zero.md")
            self.assert_ok(code, output)

        with self.subTest("one line naming c1 and a count of 1 fails"):
            body = _report(_section(part1=[_line("c1")], low=1), blocks)
            code, output = self.run_report(body, "shared-low-one.md")
            self.assert_fails(code, output)
            self.assertRegex(output, rf"\bline {_line_number(body, _count_line(1))}\b")

        with self.subTest("two lines naming c1 for one high block fails"):
            body = _report(_section(part1=[_line("c1"), second], low=0), blocks)
            code, output = self.run_report(body, "shared-low-two.md")
            self.assert_fails(code, output)
            self.assert_names(output, "c1")

    def test_shared_source_names_its_low_blocks(self):
        # Plan 058 M1 K1: a line naming a main source names every low block on it,
        # so those low blocks are not in the count.
        with self.subTest("a high and two low blocks on c1, one line: count 0 passes"):
            blocks = [_block(["c1", "c2"], "wysoka"), _block(["c1", "c3"], "niska"),
                      _block(["c1", "c4"], "niska")]
            body = _report(_section(part1=[_line("c1")], low=0), blocks)
            code, output = self.run_report(body, "shared-two-low-zero.md")
            self.assert_ok(code, output)

        with self.subTest("a high and two low blocks on c1, one line: count 2 fails"):
            blocks = [_block(["c1", "c2"], "wysoka"), _block(["c1", "c3"], "niska"),
                      _block(["c1", "c4"], "niska")]
            body = _report(_section(part1=[_line("c1")], low=2), blocks)
            code, output = self.run_report(body, "shared-two-low-two.md")
            self.assert_fails(code, output)
            self.assertRegex(output, rf"\bline {_line_number(body, _count_line(2))}\b",
                             f"expected the last line's number:\n{output}")

        with self.subTest("two low blocks on c1, no high block, c1 named once: count 0 passes"):
            blocks = [_block(["c1", "c3"], "niska"), _block(["c1", "c4"], "niska")]
            body = _report(_section(part2=[_line("c1")], low=0), blocks)
            code, output = self.run_report(body, "low-only-named.md")
            self.assert_ok(code, output)

    def write_runall(self):
        """An invented ush-runall profile and summary: decision items j<n>."""
        profile = _profile(True)
        profile.update(detail_sections=["decisions"], id_letters="j",
                       report_prefix="runall-")
        path = self.skills_dir / "ush-runall" / "data" / "report-profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile), encoding="utf-8")
        decisions = [{"id": "j1", "decision": "D1", "name": "Invented-Firewall"}]
        self.detail_file.write_text(json.dumps({"decisions": decisions}), encoding="utf-8")
        data = {
            "skill": "ush-runall",
            "status": "read",
            "children": [{"skill": "ush-health", "finding": "ush-health u8"}],
            "decisions": decisions,
            "summary_file": str(self.summary_file),
            "detail_file": str(self.detail_file),
        }
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

    def test_runall_source_ids(self):
        self.write_runall()
        child = "- ush-health u8 — Invented-Driver: sprawdź sterownik."
        own = "- ush-runall j1 — decyzja D1: przywróć ustawienie."
        bare = "- j1 — decyzja D1: przywróć ustawienie."

        def blocks(decision_source):
            return [
                _free_block("Invented-Driver", "ush-health u8 Invented-Driver, ush-runall j1",
                            "high"),
                _free_block("Invented-Firewall", f"{decision_source} decyzja D1, ush-health u8",
                            "medium"),
            ]

        with self.subTest("evidence ush-runall j1, section line bare j1"):
            body = _report(_section(part1=[child], part2=[bare]), blocks("ush-runall j1"))
            code, output = self.run_report(body, "runall-own-bare.md")
            self.assert_ok(code, output)

        with self.subTest("evidence bare j1, section line ush-runall j1"):
            body = _report(_section(part1=[child], part2=[own]), blocks("j1"))
            code, output = self.run_report(body, "runall-bare-own.md")
            self.assert_ok(code, output)

        with self.subTest("ush-runall j1 and j1 are one id: named twice fails"):
            body = _report(_section(part1=[child, own], part2=[bare]), blocks("ush-runall j1"))
            code, output = self.run_report(body, "runall-twice.md")
            self.assert_fails(code, output)
            self.assert_names(output, "j1")

        with self.subTest("the child id is the main source: an unnamed child fails"):
            body = _report(_section(part2=[bare]), blocks("ush-runall j1"))
            code, output = self.run_report(body, "runall-child-unnamed.md")
            self.assert_fails(code, output)
            self.assert_names(output, "u8")

    def test_line_names_id_twice(self):
        blocks = [_block(["c1", "c2"], "wysoka"), _block(["c3"], "średnia")]
        twice = f"- c1 — {NAMES['c1']} (c1): sprawdź ustawienia programu."
        body = _report(_section(part1=[twice, _line("c3")]), blocks)
        code, output = self.run_report(body, "line-twice.md")
        self.assert_ok(code, output)

    def test_bare_key_is_no_id(self):
        line = f"- c1 — {NAMES['c1']}: sprawdź ustawienia (`skill` = ush-common)."
        blocks = [_block(["c1", "c2"], "wysoka")]
        body = _report(_section(part1=[line]), blocks)
        code, output = self.run_report(body, "bare-key.md")
        self.assert_ok(code, output)

    def add_memory(self):
        data = json.loads(self.summary_file.read_text(encoding="utf-8"))
        data["memory"] = {"used_percent": 87}
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

    def test_key_path_source(self):
        self.add_memory()
        path_line = "- `memory.used_percent` — pamięć: zamknij nieużywane programy."

        def block(path):
            return _free_block("pamięć", f"`{path}` 87, c1 {NAMES['c1']}", "high")

        with self.subTest("a key path of the summary is the main source"):
            body = _report(_section(part1=[path_line]), [block("memory.used_percent")])
            code, output = self.run_report(body, "path-named.md")
            self.assert_ok(code, output)

        with self.subTest("the key path block unnamed fails with its path"):
            body = _report(_section(), [block("memory.used_percent")])
            code, output = self.run_report(body, "path-unnamed.md")
            self.assert_fails(code, output)
            self.assert_names(output, "memory.used_percent")

        with self.subTest("the later evidence id c1 is no main source"):
            body = _report(_section(part1=[path_line, _line("c1")]),
                           [block("memory.used_percent")])
            code, output = self.run_report(body, "path-later-id.md")
            self.assert_fails(code, output)
            self.assert_line_problem(output, _line_number(body, _line("c1")), "c1")

        with self.subTest("a key path not in the summary is no id"):
            absent = block("memory.free_percent")
            body = _report(_section(), [absent])
            code, output = self.run_report(body, "path-absent.md")
            self.assert_fails(code, output)
            self.assertRegex(output, rf"\bline {_line_number(body, _problem_line(absent))}\b")


class TestBlocks(_SummaryCase):
    def test_block_without_weight_or_id(self):
        def run(block, low, name):
            body = _report(_section(low=low), [block])
            return body, self.run_report(body, name)

        with self.subTest("control: a low block with weight and id passes"):
            _, (code, output) = run(_free_block(NAMES["c4"], f"c4 {NAMES['c4']}", "low"), 1,
                                    "block-ok.md")
            self.assert_ok(code, output)

        cases = {
            "no weight item": _free_block(NAMES["c4"], f"c4 {NAMES['c4']}", "low",
                                          with_weight=False),
            "no id in the evidence": _free_block(NAMES["c4"], "program zgłasza błąd", "low"),
            "no evidence item": _free_block(NAMES["c4"], "", "low", with_evidence=False),
        }
        for index, (label, block) in enumerate(cases.items()):
            for low in (0, 1):
                with self.subTest(label, low=low):
                    body, (code, output) = run(block, low, f"block-{index}-{low}.md")
                    self.assert_fails(code, output)
                    line_no = _line_number(body, _problem_line(block))
                    self.assertRegex(output, rf"\bline {line_no}\b",
                                     f"expected the block's line {line_no}:\n{output}")
                    # Plan 058 M1 K4: the message says which item is missing.
                    if label == "no evidence item":
                        self.assertTrue(
                            any(re.search(rf"\bline {line_no}\b", line)
                                and "no evidence item" in line
                                for line in output.splitlines()),
                            f"no output line names line {line_no} and 'no evidence item':"
                            f"\n{output}")
                    elif label == "no id in the evidence":
                        self.assertIn("names no id", output)
                        self.assertNotIn("no evidence item", output)

    def test_english_labels(self):
        for lang in ("pl", "en"):
            blocks = [
                _free_block(NAMES["c1"], f"c1 {NAMES['c1']}, c2 {NAMES['c2']}", "high", lang),
                _free_block(NAMES["c3"], f"c3 {NAMES['c3']}", "medium", lang),
                _free_block(NAMES["c4"], f"c4 {NAMES['c4']}", "low", lang),
            ]

            with self.subTest(lang, case="high and medium named, 1 low counted"):
                body = _report(_section(part1=[_line("c1"), _line("c3")], low=1), blocks)
                code, output = self.run_report(body, f"{lang}-ok.md")
                self.assert_ok(code, output)

            with self.subTest(lang, case="the medium block unnamed"):
                body = _report(_section(part1=[_line("c1")], low=1), blocks)
                code, output = self.run_report(body, f"{lang}-medium.md")
                self.assert_fails(code, output)
                self.assert_names(output, "c3")

            with self.subTest(lang, case="a later evidence id named"):
                body = _report(_section(part1=[_line("c1"), _line("c2"), _line("c3")], low=1),
                               blocks)
                code, output = self.run_report(body, f"{lang}-later.md")
                self.assert_fails(code, output)
                self.assert_line_problem(output, _line_number(body, _line("c2")), "c2")

            with self.subTest(lang, case="the low block not counted"):
                body = _report(_section(part1=[_line("c1"), _line("c3")], low=0), blocks)
                code, output = self.run_report(body, f"{lang}-low.md")
                self.assert_fails(code, output)


class TestLowCount(_SummaryCase):
    def test_low_count(self):
        two_low = [_block(["c1"], "wysoka"), _block(["c4"], "niska"),
                   _block(["c5"], "niska")]

        with self.subTest("2 unnamed low blocks with 2 passes"):
            body = _report(_section(part1=[_line("c1")], low=2), two_low)
            code, output = self.run_report(body, "low-2.md")
            self.assert_ok(code, output)

        with self.subTest("2 unnamed low blocks with 3 fails"):
            body = _report(_section(part1=[_line("c1")], low=3), two_low)
            code, output = self.run_report(body, "low-3.md")
            self.assert_fails(code, output)

        with self.subTest("2 unnamed low blocks with 0 fails"):
            body = _report(_section(part1=[_line("c1")], low=0), two_low)
            code, output = self.run_report(body, "low-0.md")
            self.assert_fails(code, output)

        named_low = [*two_low, _block(["c6"], "niska")]
        with self.subTest("a low block named in part 2 is not counted"):
            body = _report(
                _section(part1=[_line("c1")], part2=[_line("c6")], low=2), named_low)
            code, output = self.run_report(body, "low-named.md")
            self.assert_ok(code, output)

        with self.subTest("control: the named low block counted gives 3, which fails"):
            body = _report(
                _section(part1=[_line("c1")], part2=[_line("c6")], low=3), named_low)
            code, output = self.run_report(body, "low-named-counted.md")
            self.assert_fails(code, output)

        with self.subTest("13 unnamed low blocks with 13, absent from the JSON, pass"):
            self.assertNotIn("13", self.summary_file.read_text(encoding="utf-8"))
            self.assertNotIn("13", self.detail_file.read_text(encoding="utf-8"))
            blocks = [_block(["c1"], "wysoka"), *(_block([i], "niska") for i in LOW_IDS)]
            body = _report(_section(part1=[_line("c1")], low=13), blocks)
            code, output = self.run_report(body, "low-13.md")
            self.assert_ok(code, output)


class TestClean(_SummaryCase):
    def test_clean_no_recommendations(self):
        self.write_data([])
        body = _report(_section(low=0), [])
        code, output = self.run_report(body, "clean.md")
        self.assert_ok(code, output)
        self.assertNotIn("FAILED", output)
        self.assert_prints_section(output, body)
        printed = output.splitlines()[1:]
        self.assertEqual(printed.count("nic"), 3, "every part reads nic")
        self.assertIn(_count_line(0), printed)

    def test_flag_off_unchanged(self):
        body = ["# Raport testowy", "", DETAILS_HEADING, "",
                *_block(["c1", "c2"], "wysoka"), *_block(["c4"], "niska"), *NOT_CHECKED]
        for label, value in (("false", False), ("missing", OMIT)):
            with self.subTest(label):
                self.write_profile(value)
                code, output = self.run_report(body, f"flag-{label}.md")
                self.assert_ok(code, output)
                printed = [line for line in output.splitlines() if line.strip()]
                self.assertEqual(len(printed), 1, f"only the OK line expected:\n{output}")
                self.assertTrue(printed[0].startswith("OK:"), output)


if __name__ == "__main__":
    unittest.main()

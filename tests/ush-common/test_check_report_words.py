"""Shared report check: numbers written as words (plan 075, M1; invented data only).

A report that writes a number as a word ("dwa sterowniki", "Three programs")
bypasses the check of digits against the JSON, so the checker rejects it. The
word list is the data file named by ``NUMBER_WORDS_FILE``; tests K1-K5 and K7
use the real list, K6 patches the constant to a temporary file and never
touches the file in the repository.
"""

import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT, load_script

NOT_CHECKED = ["## Nie sprawdzono", "<!-- ush:not-checked -->", "Nic."]
REAL_WORDS_FILE = REPO_ROOT / "skills" / "ush-common" / "data" / "number-words.json"
SKILLS = ("ush-events", "ush-health", "ush-inventory", "ush-processes", "ush-settings")
EXIT_ERROR = 2  # "the report, its JSON or its profile could not be checked"


def _profile():
    """An invented profile; "program" is a path key, so its value backs nothing."""
    return {
        "detail_sections": ["things"],
        "id_letters": "c",
        "path_keys": ["detail_file", "summary_file", "program"],
        "id_keys": ["id"],
        "required_lists": [],
        "truncated": None,
        "report_prefix": "test-",
    }


def _word_problem(word, line=None):
    text = f'"{word}" is a number word; write the number in digits'
    return text if line is None else f"line {line}: {text}"


class _CheckerCase(unittest.TestCase):
    """Temporary data directory and a call of the checker's main()."""

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

    def write_report(self, body, name, summary_file=None):
        path = self.reports_dir / name
        first = f"<!-- ush:summary {summary_file or self.summary_file} -->"
        path.write_text("\n".join([first, *body]) + "\n", encoding="utf-8")
        return path

    def run_path(self, path):
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

    def assert_word_fails(self, code, output, word):
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertFalse(any(line.startswith("OK:") for line in output.splitlines()),
                         f"no OK line expected; output:\n{output}")
        self.assertIn(_word_problem(word), output)


class _InventedProfileCase(_CheckerCase):
    """The checker with an invented ush-test profile in a temporary skills dir."""

    def setUp(self):
        super().setUp()
        self.skills_dir = self.root / "skills"
        patcher = mock.patch.object(self.check, "SKILLS_DIR", self.skills_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        profile_path = self.skills_dir / "ush-test" / "data" / "report-profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
        self.detail_file.write_text(json.dumps({"things": []}), encoding="utf-8")
        self.write_summary({"status": "read"})

    def write_summary(self, data):
        data = dict(data)
        data["skill"] = "ush-test"
        data["summary_file"] = str(self.summary_file)
        data["detail_file"] = str(self.detail_file)
        self.summary_file.write_text(json.dumps(data), encoding="utf-8")

    def run_report(self, body, name):
        path = self.write_report(body, name)
        code, output = self.run_path(path)
        return path, code, output


class TestNumberWords(_InventedProfileCase):
    def test_number_word_fails(self):
        cases = {
            "polish": ("Obcięto dwa sterowniki.", "dwa"),
            "english": ("Three programs were cut.", "Three"),
        }
        for index, (label, (sentence, word)) in enumerate(cases.items()):
            with self.subTest(label):
                # Line 1 is ush:summary, line 2 the heading, line 3 the sentence.
                path, code, output = self.run_report(
                    ["# Raport testowy", sentence, *NOT_CHECKED], f"word-{index}.md")
                self.assert_word_fails(code, output, word)
                self.assertIn(_word_problem(word, 3), output)
                self.assertIn(f"FAILED: {path}: 1 number words", output)
                self.assertNotIn("numbers are not backed", output)

    def test_inflected_and_capitalised_forms_fail(self):
        cases = {
            "dwóch": "Sprawdzono dwóch dostawców.",
            "pięciu": "Brakuje pięciu wpisów.",
            "trzema": "Dysk zakończył pracę z trzema błędami.",
            "pięćset": "Plik zajmuje pięćset megabajtów.",
            "Trzej": "Trzej dostawcy zgłosili błąd.",
            "Dwa": "Dwa dyski są pełne.",
        }
        for index, (word, sentence) in enumerate(cases.items()):
            with self.subTest(word):
                _path, code, output = self.run_report(
                    ["# Raport testowy", sentence, *NOT_CHECKED], f"form-{index}.md")
                self.assert_word_fails(code, output, word)
                self.assertIn(_word_problem(word, 3), output)

    def test_clean_report_passes(self):
        cases = {
            "polish": [
                "# Raport testowy",
                "Ten program musi trzymać jeden z wpisów autostartu.",
                "Sprawdzono oba dyski.",
                "Twoje ustawienia są zgodne z katalogiem.",
                "Dysk ma układ dwu-partycyjny.",
                "W dzienniku są tysiące wpisów.",
                *NOT_CHECKED,
            ],
            "english": [
                "# Test report",
                "This is one of the entries with two-factor authentication.",
                "The switch is three-way.",
                *NOT_CHECKED,
            ],
        }
        for index, (label, body) in enumerate(cases.items()):
            with self.subTest(label):
                _path, code, output = self.run_report(body, f"clean-{index}.md")
                self.assert_ok(code, output)
                self.assertNotIn("number word", output)

    def test_word_backed_by_name_or_code_passes(self):
        body = [
            "# Raport testowy",
            "Program Invented Two Sync działa od rana.",
            "Polecenie `dwa trzy` jest tylko przykładem.",
            "Podwójny znacznik ``cztery`` też jest kodem.",
            "",
            "```",
            "dwa trzy cztery",
            "```",
            "",
            *NOT_CHECKED,
        ]

        with self.subTest("name in the summary, words in code"):
            self.write_summary({"programs": [{"name": "Invented Two Sync"}]})
            _path, code, output = self.run_report(body, "backed.md")
            self.assert_ok(code, output)

        with self.subTest("control: the name without the word backs nothing"):
            self.write_summary({"programs": [{"name": "Invented Sync"}]})
            _path, code, output = self.run_report(body, "not-backed.md")
            self.assert_word_fails(code, output, "Two")
            self.assertIn(_word_problem("Two", 3), output)

        with self.subTest("an unpaired backtick hides no word"):
            self.write_summary({"programs": [{"name": "Invented Two Sync"}]})
            _path, code, output = self.run_report(
                ["# Raport testowy", "Znak ` nie ukrywa słowa dwa.", *NOT_CHECKED],
                "unpaired.md")
            self.assert_word_fails(code, output, "dwa")
            self.assertIn(_word_problem("dwa", 3), output)

    def test_word_backed_by_detail_item_passes(self):
        self.write_summary({"programs": []})
        self.detail_file.write_text(json.dumps(
            {"things": [{"id": "c1", "name": "Invented Two Sync"}]}), encoding="utf-8")
        sentence = "Program Invented Two Sync działa od rana."

        with self.subTest("name in an item named in ush:detail"):
            _path, code, output = self.run_report(
                ["# Raport testowy", "<!-- ush:detail c1 -->", sentence, *NOT_CHECKED],
                "detail-backed.md")
            self.assert_ok(code, output)

        with self.subTest("control: the same item not named in ush:detail"):
            _path, code, output = self.run_report(
                ["# Raport testowy", sentence, *NOT_CHECKED], "detail-not-named.md")
            self.assert_word_fails(code, output, "Two")
            self.assertIn(_word_problem("Two", 3), output)

    def test_path_value_backs_no_word(self):
        folder_line = ["# Raport testowy", "Plik leży w folderze Invented Two.", *NOT_CHECKED]

        with self.subTest("word only in the text of a path-shaped key"):
            self.write_summary({"changes": [{"fields": {
                "facts[C:\\Invented Two\\x.exe].signer": "Example Soft"}}]})
            _path, code, output = self.run_report(folder_line, "path-key.md")
            self.assert_word_fails(code, output, "Two")

        with self.subTest("word only in the value of a path_keys key"):
            self.write_summary({"programs": [{"program": "C:\\Invented Two\\x.exe"}]})
            _path, code, output = self.run_report(folder_line, "path-value.md")
            self.assert_word_fails(code, output, "Two")

        with self.subTest("the value of a path-keyed signer field backs the word"):
            self.write_summary({"changes": [{"fields": {
                "facts[C:\\x.exe].signer": "Invented Two Soft"}}]})
            _path, code, output = self.run_report(
                ["# Raport testowy", "Plik podpisuje Invented Two Soft.", *NOT_CHECKED],
                "signer.md")
            self.assert_ok(code, output)

    def test_bad_word_list_is_an_error(self):
        before = REAL_WORDS_FILE.read_bytes() if REAL_WORDS_FILE.is_file() else None
        lists_dir = self.root / "lists"
        lists_dir.mkdir()
        clean = ["# Raport testowy", "Obcięto trzy sterowniki.", *NOT_CHECKED]

        def use_list(name, text=None):
            path = lists_dir / name
            if text is not None:
                path.write_text(text, encoding="utf-8")
            patcher = mock.patch.object(self.check, "NUMBER_WORDS_FILE", path)
            patcher.start()
            self.addCleanup(patcher.stop)
            return patcher

        with self.subTest("control: a valid temporary list replaces the real one"):
            patcher = use_list("valid.json", json.dumps({"words": ["dwa"]}))
            # "trzy" is not on the temporary list, so this report passes.
            _path, code, output = self.run_report(clean, "control-clean.md")
            self.assert_ok(code, output)
            _path, code, output = self.run_report(
                ["# Raport testowy", "Obcięto dwa sterowniki.", *NOT_CHECKED],
                "control-word.md")
            self.assert_word_fails(code, output, "dwa")
            patcher.stop()

        cases = {
            "missing file": ("missing.json", None),
            "invalid JSON": ("broken.json", '{"words": ["dwa"'),
            "empty words list": ("empty.json", json.dumps({"words": []})),
            "empty element": ("blank.json", json.dumps({"words": ["dwa", ""]})),
            "element with a capital letter": ("capital.json", json.dumps({"words": ["Dwa"]})),
            "element of two words": ("two-words.json", json.dumps({"words": ["dwa trzy"]})),
        }
        for index, (label, (name, text)) in enumerate(cases.items()):
            with self.subTest(label):
                patcher = use_list(name, text)
                _path, code, output = self.run_report(clean, f"bad-list-{index}.md")
                patcher.stop()
                self.assertEqual(code, EXIT_ERROR, f"{label}: output:\n{output}")
                self.assertIn("FAILED", output)
                self.assertFalse(any(line.startswith("OK:") for line in output.splitlines()),
                                 f"{label}: no OK line expected; output:\n{output}")

        after = REAL_WORDS_FILE.read_bytes() if REAL_WORDS_FILE.is_file() else None
        self.assertEqual(before, after, "the word list in the repository was changed")


def _skill_tests(skill, module):
    return importlib.import_module(f"tests.{skill}.{module}")


def _events_data(summary_file, detail_file):
    mod = _skill_tests("ush-events", "test_report_check")
    return mod._summary_data(detail_file), mod._detail_data()


def _health_data(summary_file, detail_file):
    mod = _skill_tests("ush-health", "test_report_profile")
    summary = mod._summary_data(summary_file, detail_file)
    return summary, mod._detail_data(summary)


def _inventory_data(summary_file, detail_file):
    mod = _skill_tests("ush-inventory", "test_report_profile")
    summary = mod._clean_summary(summary_file, detail_file)
    return summary, {section: summary.get(section) or [] for section in mod.DETAIL_SECTIONS}


def _processes_data(summary_file, detail_file):
    mod = _skill_tests("ush-processes", "test_report_profile")
    summary = mod._clean_summary(summary_file, detail_file)
    return summary, {section: summary[section] for section in mod.DETAIL_SECTIONS}


def _settings_data(summary_file, detail_file):
    mod = _skill_tests("ush-settings", "test_report_profile")
    summary = mod._clean_summary(summary_file, detail_file)
    return summary, {section: summary[section] for section in mod.DETAIL_SECTIONS}


def _events_body():
    return [
        "# Raport dziennika zdarzeń",
        "",
        "Błąd krytyczny 0x19C zapisano 18.09.2026.",
        "Zdarzeń łącznie: 1 234.",
        "Średnio na dzień: 3,5.",
        "<!-- ush:detail g1 -->",
        "Największa grupa ma 4321 zdarzeń; ten dostawca jest jeden.",
        "## 1. Ustalenia",
        "- Nic więcej nie odstaje.",
        "",
        *NOT_CHECKED,
    ]


def _health_body():
    return [
        "# Raport stanu",
        "",
        "| # | Obszar | Stan | Działanie |",
        "|---|---|---|---|",
        "| 1 | Dyski | Sprawne | Brak |",
        "| 2 | Woluminy | Mało wolnego miejsca | Zwolnić miejsce |",
        "| 3 | Urządzenia | Błąd | Sprawdzić sterownik |",
        "| 4 | Aktualizacje | Nieudane | Ponowić |",
        "",
        "## Dyski",
        "Dysk k1 (Invented NVMe Disk, 238.7 GB) jest sprawny.",
        "",
        "## Woluminy",
        "Wolumin v1 (C:) ma 29.2 GB wolnego z 236.9 GB, czyli 12.3 procent.",
        "",
        "## Urządzenia",
        "Urządzenie p1 zgłasza problem CM_PROB_FAILED_START.",
        "",
        "## Aktualizacje",
        "Aktualizacja u1 (Invented Cumulative Update) nie powiodła się 2 razy.",
        "",
        "## Nie sprawdzono",
        "<!-- ush:not-checked -->",
        "- disk_reliability: wymaga uprawnień administratora.",
    ]


def _inventory_body():
    return [
        "# Raport inwentarza, 2026-09-30 08:10",
        "",
        "| # | Obszar | Stan | Działanie |",
        "|---|------|-------|--------|",
        "| 1 | Programy | jeden na liście | brak |",
        "| 2 | Autostart | jeden na liście | przejrzeć |",
        "| 3 | Zmiany | jedna od punktu odniesienia | brak |",
        "",
        "## Porównanie",
        "Porównano z punktem odniesienia z 2026-05-07, sprzed 146.3 dnia.",
        "- c1: dodano Invented Editor, wersja 4.2.0.",
        "",
        "## Programy",
        "- a1: Invented Editor 4.2.0 od Example Soft, zainstalowany 2026-03-14.",
        "- Programy Windows: 23.",
        "",
        "## Autostart",
        ("- s1: InventedTray startuje przy logowaniu z klucza Run w HKCU; zatwierdzony, "
         "plik obecny, podpis ważny."),
        "- Usługi Windows (bez listy): 17.",
        "- Zadania Windows (bez listy): 9.",
        "",
        "## Nie sprawdzono",
        "<!-- ush:not-checked -->",
        "- widoczność scheduled_tasks: bez uprawnień administratora lista zadań może być niepełna.",
    ]


def _processes_body(total_bytes):
    return [
        "# Raport procesów, 2026-09-30 08:10",
        "",
        "## Pamięć",
        f"- Pamięć w użyciu: 6.0 GB z 8.0 GB ({total_bytes} bajtów); dostępne 2.0 GB.",
        "- Grupy z listy zajmują 1.2 GB pamięci prywatnej.",
        "",
        "## Programy",
        "| # | Program | Procesy | Pamięć (MB) | Uruchomiony przez |",
        "|---|---------|-----------|-------------|------------|",
        "| 1 | g1 browser.exe | 2 | 1000.0 | autostart |",
        "| 2 | g2 host.exe | 1 | 250.0 | usługa |",
        "",
        "- g1: Invented Browser, oba procesy uruchamia wpis autostartu InventedBrowser.",
        "- g2: Invented Host, działa jako usługa InventedHostSvc.",
        "",
        "## Porty TCP",
        "- p1: host.exe (g2) nasłuchuje na TCP 8080 na wszystkich adresach (0.0.0.0).",
        "- p2: browser.exe (g1) nasłuchuje na TCP 3000 tylko na pętli zwrotnej (127.0.0.1).",
        "",
        "## Gniazda UDP",
        "- g2 host.exe: 2 powiązane gniazda UDP na wszystkich adresach.",
        "",
        "## Inwentarz",
        "Powiązania pochodzą z punktu odniesienia ush-inventory z 2026-09-28, sprzed 1.6 dnia.",
        "",
        "## Nie sprawdzono",
        "<!-- ush:not-checked -->",
        "- nic.",
    ]


def _settings_body(block_lines):
    return [
        "# Raport ustawień, 2026-09-30 08:10",
        "",
        "| # | Obszar | Stan | Działanie |",
        "|---|------|-------|--------|",
        "| 1 | Ustawienia | jedno się różni | przejrzeć |",
        "| 2 | Zmiany | jedna od punktu odniesienia | brak |",
        "| 3 | Użycie funkcji | jedno na liście | brak |",
        "",
        "## Porównanie",
        "Porównano z punktem odniesienia z 2026-09-23, sprzed 6.9 dnia.",
        "- c1: Advertising ID zmienił się z 0 na 1.",
        "",
        "## Ustawienia",
        "- Zgodne: 40. Różne: 1. Nie dotyczy: 2. Nieodczytane: 0.",
        "- Prywatność: 7 ustawień zgodnych. Bezpieczeństwo: 33 ustawienia zgodne.",
        ("- e1: Advertising ID (privacy, standard) się różni: obecnie 1, oczekiwane 0; "
         "ustawione jako preferencja."),
        "",
        "Wklej do zwykłego Windows PowerShell, żeby wyłączyć identyfikator reklamowy:",
        "",
        *block_lines,
        "",
        "## Użycie funkcji",
        ("- u1: Invented.CameraApp_abc używała kamery 2026-09-29 od 18:00 do 18:25; "
         "dozwolone, teraz nieużywana."),
        "",
        "## Nie sprawdzono",
        "<!-- ush:not-checked -->",
        "- nic.",
    ]


class TestPolishSkillReports(_CheckerCase):
    """Real profiles (SKILLS_DIR not patched), real word list, invented summaries."""

    def _cases(self):
        processes = _skill_tests("ush-processes", "test_report_profile")
        settings = _skill_tests("ush-settings", "test_report_profile")
        return {
            "ush-events": (_events_data, _events_body()),
            "ush-health": (_health_data, _health_body()),
            "ush-inventory": (_inventory_data, _inventory_body()),
            "ush-processes": (_processes_data, _processes_body(processes.TOTAL_BYTES)),
            "ush-settings": (_settings_data, _settings_body(settings._block_lines())),
        }

    def test_polish_clean_report_of_each_skill(self):
        cases = self._cases()
        self.assertEqual(set(cases), set(SKILLS))
        for skill, (builder, body) in cases.items():
            with self.subTest(skill):
                name = skill.removeprefix("ush-")
                summary_file = self.work_dir / f"{name}-summary.json"
                detail_file = self.work_dir / f"{name}-detail.json"
                summary, detail = builder(summary_file, detail_file)
                self.assertEqual(summary.get("skill"), skill)
                detail_file.write_text(json.dumps(detail), encoding="utf-8")
                summary_file.write_text(json.dumps(summary), encoding="utf-8")
                report = self.write_report(body, f"{name}-2026-09-30-0900.md",
                                           summary_file=summary_file)
                code, output = self.run_path(report)
                self.assert_ok(code, output)


class TestNumberWordDocs(unittest.TestCase):
    def test_every_report_format_says_digits(self):
        for skill in SKILLS:
            with self.subTest(skill):
                path = REPO_ROOT / "skills" / skill / "references" / "report-format.md"
                self.assertTrue(path.is_file(), f"missing: {path}")
                self.assertIn("Write every number in digits",
                              path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

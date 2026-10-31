"""Repair plan checker: sections and run blocks without undo (invented plans only).

The plans below are written from scratch: Polish text, plausible PowerShell lines,
no real user names or profile paths.
"""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

FENCE = "```"


def _block(kind, skill, ident, lines):
    """One marker line followed by a fenced PowerShell block."""
    return [f"<!-- ush:{kind} {skill} {ident} -->", f"{FENCE}powershell", *lines, FENCE, ""]


def _plan(*, run_blocks=None, undo_blocks=None, drop_sections=()):
    """Build an invented repair plan; sections named in drop_sections are left out."""
    if run_blocks is None:
        run_blocks = [
            ("ush-settings", "s1", [
                ("Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection' "
                "-Name 'AllowTelemetry' -Type DWord -Value 1"),
            ]),
            ("ush-settings", "s3", [
                "Set-Service -Name 'DiagTrack' -StartupType Manual",
            ]),
        ]
    if undo_blocks is None:
        undo_blocks = [
            ("ush-settings", "s1", [
                ("Remove-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection' "
                "-Name 'AllowTelemetry'"),
            ]),
            ("ush-settings", "s3", [
                "Set-Service -Name 'DiagTrack' -StartupType Automatic",
            ]),
        ]
    sections = {
        "Problem": [
            "Telemetria jest ustawiona wyżej, niż użytkownik chciał, a usługa DiagTrack",
            "startuje automatycznie.",
            "",
        ],
        "Wybrana opcja": [
            "Opcja B: ograniczyć telemetrię do poziomu podstawowego i przełączyć usługę",
            "na start ręczny. Ryzyko: niskie. Wymaga powłoki z uprawnieniami administratora.",
            "",
        ],
        "Bloki do uruchomienia": [
            "Wklej każdy blok do PowerShell uruchomionego jako administrator.",
            "",
            *[line for skill, ident, body in run_blocks
              for line in _block("block", skill, ident, body)],
        ],
        "Bloki cofające": [
            "Te bloki przywracają poprzedni stan.",
            "",
            *[line for skill, ident, body in undo_blocks
              for line in _block("undo", skill, ident, body)],
        ],
        "Odczyt po zmianie": [
            "Po uruchomieniu bloków uruchom ponownie ush-settings i porównaj wartości.",
            "",
        ],
        "Notatki": [
            "Brak dodatkowych uwag.",
            "",
        ],
    }
    lines = ["# Plan naprawy: telemetria", ""]
    for heading, body in sections.items():
        if heading in drop_sections:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        lines.extend(body)
    return "\n".join(lines) + "\n"


def _tree(root):
    """Every path under root, relative, as a sorted list."""
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*"))


def _same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


class TestCheckRepairPlan(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_repair_plan")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        # No real data directory is ever reached: the environment holds only the temp one.
        patcher = mock.patch.dict(os.environ, {"USH_DATA_DIR": str(self.data_dir)}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def write_plan(self, path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_complete_plan(self):
        path = self.write_plan(self.root / "plan-telemetria.md", _plan())
        code, out, err = self.run_main([str(path)])
        self.assertEqual(code, 0, out + err)
        result = json.loads(out)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["missing_sections"], [])
        self.assertEqual(result["blocks_without_undo"], [])
        self.assertTrue(os.path.isabs(result["file"]), result["file"])
        self.assertTrue(_same_path(result["file"], path), result["file"])

    def test_block_without_undo(self):
        undo_blocks = [
            ("ush-settings", "s1", [
                ("Remove-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection' "
                "-Name 'AllowTelemetry'"),
            ]),
            # Same id, other skill: does not undo ush-settings s3.
            ("ush-files", "s3", [
                "Remove-Item -LiteralPath 'D:\\Kopie\\stary-eksport.zip'",
            ]),
        ]
        path = self.write_plan(self.root / "plan-bez-cofania.md", _plan(undo_blocks=undo_blocks))
        code, out, err = self.run_main([str(path)])
        self.assertEqual(code, 1, out + err)
        result = json.loads(out)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["blocks_without_undo"], ["ush-settings s3"])
        self.assertEqual(result["missing_sections"], [])

    def test_missing_section(self):
        path = self.write_plan(self.root / "plan-bez-odczytu.md",
                               _plan(drop_sections=("Odczyt po zmianie",)))
        code, out, err = self.run_main([str(path)])
        self.assertEqual(code, 1, out + err)
        result = json.loads(out)
        self.assertIs(result["ok"], False)
        self.assertEqual(len(result["missing_sections"]), 1, result["missing_sections"])
        self.assertIn("Odczyt po zmianie", result["missing_sections"][0])
        self.assertEqual(result["blocks_without_undo"], [])

    def test_latest(self):
        plans = self.data_dir / "plans"
        now = time.time()
        older = self.write_plan(plans / "2026-10-28-plan-uslugi.md", _plan())
        newest = self.write_plan(plans / "2026-10-29-plan-telemetria.md", _plan())
        # The done/ plan is the newest file of all and lacks a section, but is never taken.
        done = self.write_plan(plans / "done" / "2026-10-30-plan-zamkniety.md",
                               _plan(drop_sections=("Notatki",)))
        os.utime(older, (now - 7200, now - 7200))
        os.utime(newest, (now - 3600, now - 3600))
        os.utime(done, (now, now))

        with self.subTest("newest plan in plans/, not in plans/done/"):
            code, out, err = self.run_main(["--latest", "--data-dir", str(self.data_dir)])
            self.assertEqual(code, 0, out + err)
            result = json.loads(out)
            self.assertTrue(_same_path(result["file"], newest), result["file"])
            self.assertFalse(_same_path(result["file"], done), result["file"])
            self.assertFalse(_same_path(result["file"], older), result["file"])
            self.assertIs(result["ok"], True)

        with self.subTest("only a plan in done/: usage error, nothing written"):
            only_done = self.root / "only-done"
            self.write_plan(only_done / "plans" / "done" / "2026-10-27-plan.md", _plan())
            before = _tree(only_done)
            code, out, err = self.run_main(["--latest", "--data-dir", str(only_done)])
            self.assertEqual(code, 2, out + err)
            self.assertTrue(err.strip(), "usage error message expected on stderr")
            self.assertEqual(_tree(only_done), before)

        with self.subTest("no plans directory: usage error, nothing created"):
            empty = self.root / "empty"
            empty.mkdir()
            code, out, err = self.run_main(["--latest", "--data-dir", str(empty)])
            self.assertEqual(code, 2, out + err)
            self.assertTrue(err.strip(), "usage error message expected on stderr")
            self.assertEqual(_tree(empty), [])

    def run_plan(self, name, text):
        path = self.write_plan(self.root / name, text)
        code, out, err = self.run_main([str(path)])
        return code, json.loads(out) if out.strip() else None, out + err

    def test_unmarked_run_block(self):
        text = _plan().replace(
            "Wklej każdy blok do PowerShell uruchomionego jako administrator.\n",
            "Wklej każdy blok do PowerShell uruchomionego jako administrator.\n\n"
            f"{FENCE}powershell\nStop-Service -Name 'DiagTrack'\n{FENCE}\n",
        )
        code, result, output = self.run_plan("plan-bez-znacznika.md", text)
        self.assertEqual(code, 1, output)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["missing_sections"], [])
        self.assertEqual(len(result["blocks_without_undo"]), 1, result["blocks_without_undo"])
        entry = result["blocks_without_undo"][0]
        self.assertTrue(entry.startswith("unmarked block, line "), entry)
        line = int(entry.rsplit(" ", 1)[1])
        self.assertEqual(text.splitlines()[line - 1], f"{FENCE}powershell")
        self.assertIn("Stop-Service", text.splitlines()[line])

    def test_extra_heading_in_run_section(self):
        # An unmarked block after an extra level-2 heading under the run section is still found.
        text = _plan().replace(
            "Wklej każdy blok do PowerShell uruchomionego jako administrator.\n",
            "Wklej każdy blok do PowerShell uruchomionego jako administrator.\n\n"
            f"## Krok 2\n\n{FENCE}powershell\nStop-Service -Name 'DiagTrack'\n{FENCE}\n",
        )
        code, result, output = self.run_plan("plan-dodatkowy-naglowek.md", text)
        self.assertEqual(code, 1, output)
        self.assertEqual(len(result["blocks_without_undo"]), 1, result["blocks_without_undo"])
        self.assertTrue(result["blocks_without_undo"][0].startswith("unmarked block, line "))

    def test_extra_heading_in_run_section_clean(self):
        # Clean data: a marked run block under an extra level-2 heading in the run section,
        # with its undo block, keeps the plan complete.
        text = _plan().replace(
            "Wklej każdy blok do PowerShell uruchomionego jako administrator.\n",
            "Wklej każdy blok do PowerShell uruchomionego jako administrator.\n\n"
            f"## Krok 2\n\n<!-- ush:block ush-settings s9 -->\n{FENCE}powershell\n"
            f"Stop-Service -Name 'DiagTrack'\n{FENCE}\n",
        ).replace(
            "## Odczyt po zmianie",
            f"<!-- ush:undo ush-settings s9 -->\n{FENCE}powershell\n"
            f"Start-Service -Name 'DiagTrack'\n{FENCE}\n\n## Odczyt po zmianie",
        )
        self.assertIn("## Krok 2", text)
        self.assertIn("<!-- ush:undo ush-settings s9 -->", text)
        code, result, output = self.run_plan("plan-krok-2-czysty.md", text)
        self.assertEqual(code, 0, output)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["blocks_without_undo"], [])

    def test_extra_heading_in_undo_section(self):
        # Clean data: an extra level-2 heading under the undo section keeps its undo markers.
        text = _plan().replace(
            "<!-- ush:undo ush-settings s1 -->\n",
            "## Cofnięcie s1\n\n<!-- ush:undo ush-settings s1 -->\n",
        )
        self.assertIn("## Cofnięcie s1", text)
        code, result, output = self.run_plan("plan-naglowek-cofania.md", text)
        self.assertEqual(code, 0, output)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["blocks_without_undo"], [])

    def test_undo_marker_without_fence(self):
        # The s3 undo marker is followed by words, not by a block.
        text = _plan().replace(
            "<!-- ush:undo ush-settings s3 -->\n",
            "<!-- ush:undo ush-settings s3 -->\nBlok cofający zostanie dodany później.\n",
        )
        code, result, output = self.run_plan("plan-cofanie-bez-bloku.md", text)
        self.assertEqual(code, 1, output)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["blocks_without_undo"], ["ush-settings s3"])

    def test_undo_marker_in_notes(self):
        undo_blocks = [
            ("ush-settings", "s1", [
                ("Remove-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection' "
                "-Name 'AllowTelemetry'"),
            ]),
        ]
        notes_undo = "\n".join(_block("undo", "ush-settings", "s3", [
            "Set-Service -Name 'DiagTrack' -StartupType Automatic",
        ]))
        text = _plan(undo_blocks=undo_blocks).replace(
            "Brak dodatkowych uwag.\n", "Brak dodatkowych uwag.\n\n" + notes_undo + "\n")
        code, result, output = self.run_plan("plan-cofanie-w-notatkach.md", text)
        self.assertEqual(code, 1, output)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["blocks_without_undo"], ["ush-settings s3"])

    def test_marker_inside_fence_in_notes(self):
        text = _plan().replace(
            "Brak dodatkowych uwag.\n",
            "Brak dodatkowych uwag.\n\n"
            f"{FENCE}text\n<!-- ush:block ush-settings s9 -->\nprzykład znacznika\n{FENCE}\n",
        )
        code, result, output = self.run_plan("plan-znacznik-w-bloku.md", text)
        self.assertEqual(code, 0, output)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["blocks_without_undo"], [])
        self.assertEqual(result["missing_sections"], [])

    # A clean-up block from ush-files: its rollback is "cannot be undone".
    NOUNDO = "<!-- ush:noundo ush-settings s3 -->\nTego bloku nie da się cofnąć (cannot be undone).\n"

    def noundo_plan(self, replacement):
        """The default plan with the s3 undo block replaced by `replacement`."""
        s3_undo = "\n".join(_block("undo", "ush-settings", "s3", [
            "Set-Service -Name 'DiagTrack' -StartupType Automatic",
        ]))
        text = _plan()
        self.assertIn(s3_undo, text)
        return text.replace(s3_undo, replacement)

    def test_noundo_marker_clean_plan(self):
        # Clean data: a complete plan whose s3 is marked as irreversible under the undo section.
        text = self.noundo_plan(self.NOUNDO)
        self.assertNotIn("<!-- ush:undo ush-settings s3 -->", text)
        code, result, output = self.run_plan("plan-bez-cofniecia.md", text)
        self.assertEqual(code, 0, output)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["blocks_without_undo"], [])
        self.assertEqual(result["missing_sections"], [])

    def test_noundo_marker_outside_undo_section(self):
        # The noundo marker sits under Notatki, not under the undo section.
        text = self.noundo_plan("").replace(
            "Brak dodatkowych uwag.\n", "Brak dodatkowych uwag.\n\n" + self.NOUNDO)
        self.assertIn("<!-- ush:noundo ush-settings s3 -->", text)
        code, result, output = self.run_plan("plan-noundo-w-notatkach.md", text)
        self.assertEqual(code, 1, output)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["blocks_without_undo"], ["ush-settings s3"])

    def test_noundo_marker_followed_by_fence(self):
        # A noundo marker followed by a block is not a "cannot be undone" note.
        replacement = "\n".join(_block("noundo", "ush-settings", "s3", [
            "Set-Service -Name 'DiagTrack' -StartupType Automatic",
        ]))
        # Words after the block must not be taken as the noundo marker's line of words.
        replacement += "\nTego bloku nie da się cofnąć.\n"
        text = self.noundo_plan(replacement)
        self.assertIn("<!-- ush:noundo ush-settings s3 -->\n```powershell", text)
        code, result, output = self.run_plan("plan-noundo-z-blokiem.md", text)
        self.assertEqual(code, 1, output)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["blocks_without_undo"], ["ush-settings s3"])

    def test_unreadable_plans_directory(self):
        plans = self.data_dir / "plans"
        self.write_plan(plans / "2026-10-29-plan-telemetria.md", _plan())
        denied = PermissionError(13, "Access is denied", str(plans))
        # Only the checker's listing is refused, in memory; nothing on the machine changes.
        with mock.patch.object(self.check.os, "scandir", side_effect=denied):
            code, out, err = self.run_main(["--latest", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 2, out + err)
        self.assertEqual(out, "")
        self.assertIn("could not be listed", err)
        self.assertIn("PermissionError", err)
        self.assertNotIn("no repair plan", err)


if __name__ == "__main__":
    unittest.main()

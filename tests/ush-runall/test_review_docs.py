"""The ush-runall docs on review dates (plan 077, M2, K3).

Checked in the real files of ``skills/ush-runall``:

- ``SKILL.md`` names ``review_dates.py --list``, ``--set`` and ``--undo``, each on a command
  line that carries ``--data-dir`` or ``--default-data-dir``; it shows the group form
  ``<ids>=<period>``; it says writes run only on the user's word and that ``--undo``
  reverses the last ``--set`` call.
- ``references/report-format.md`` has a ``Przeglądy`` section that gives the wording of
  ``due``, ``gone``, ``not_checked`` and the ``no_decision`` count line.
- ``references/summary-contract.md`` documents the ``--list`` output (``detail_file``,
  ``items`` with ``prefix``, ``counts`` with ``by_state`` and ``by_kind``), the ``--undo``
  output (``entry_count``) and ``warning``.

Assumptions beyond the plan: a command form sits on one line of ``SKILL.md``; the
``Przeglądy`` section is a Markdown heading whose text contains ``Przeglądy`` and names
each state by its key.
"""

import re
import unittest

from tests.skill_loader import REPO_ROOT

RUNALL_DIR = REPO_ROOT / "skills" / "ush-runall"
DATA_DIR_OPTION = re.compile(r"--(?:default-)?data-dir\b")


def _read(name):
    return (RUNALL_DIR / name).read_text(encoding="utf-8")


def _flat(text):
    return " ".join(text.split())


def _sentences(flat):
    return re.split(r"(?<=[.!?])\s+", flat)


def _heading_section(text, word):
    """The flat text from the first heading containing ``word`` to the next heading of the
    same or a higher level, or ``None``."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("#") and word in line), None)
    if start is None:
        return None
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("#")
                and len(lines[i]) - len(lines[i].lstrip("#")) <= level), len(lines))
    return _flat("\n".join(lines[start:end]))


class TestReviewDocs(unittest.TestCase):
    def test_docs(self):
        skill_md = _read("SKILL.md")
        skill_flat = _flat(skill_md)
        report_format = _read("references/report-format.md")
        contract = _read("references/summary-contract.md")
        contract_flat = _flat(contract)

        for action in ("--list", "--set", "--undo"):
            with self.subTest(f"SKILL.md: review_dates.py {action} with a data dir option"):
                lines = [line for line in skill_md.splitlines()
                         if "review_dates.py" in line
                         and re.search(re.escape(action) + r"\b", line)]
                self.assertTrue(lines, f"SKILL.md names no review_dates.py {action} command")
                self.assertTrue(any(DATA_DIR_OPTION.search(line) for line in lines),
                                f"no {action} command with --data-dir or "
                                f"--default-data-dir: {lines}")

        with self.subTest("SKILL.md: the group form <ids>=<period>"):
            self.assertIn("<ids>=<period>", skill_md)

        with self.subTest("SKILL.md: writes run only on the user's word"):
            rule = [s for s in _sentences(skill_flat)
                    if "user's word" in s.casefold() and "only" in s.casefold()]
            self.assertTrue(rule, "SKILL.md does not say writes run only on the user's word")

        with self.subTest("SKILL.md: --undo reverses the last --set call"):
            rule = [s for s in _sentences(skill_flat)
                    if "--undo" in s and "--set" in s and "last" in s.casefold()
                    and "revers" in s.casefold()]
            self.assertTrue(rule, "SKILL.md does not say --undo reverses the last --set call")

        with self.subTest("report-format.md: a Przeglądy section with the states"):
            section = _heading_section(report_format, "Przeglądy")
            self.assertIsNotNone(section, "report-format.md has no Przeglądy section")
            for state in ("due", "gone", "not_checked", "no_decision"):
                self.assertIn(f"`{state}`", section, state)

        with self.subTest("report-format.md: the no_decision count line has no figure but <N>"):
            # check_report.py checks every digit of a report against the JSON, so a step
            # number in the prescribed Polish line would be unbacked in most passes.
            line = re.search(r'"Bez decyzji o przeglądzie: <N>\.(.*?)"', _flat(report_format))
            self.assertIsNotNone(line, "no Polish no_decision count line")
            self.assertNotRegex(line.group(1), r"\d")

        with self.subTest("summary-contract.md: --list output"):
            self.assertIn("--list", contract)
            for key in ("detail_file", "items", "prefix", "counts", "by_state", "by_kind"):
                self.assertIn(f"`{key}`", contract_flat, key)

        with self.subTest("summary-contract.md: --undo output and warning"):
            self.assertIn("--undo", contract)
            self.assertIn("`entry_count`", contract_flat)
            self.assertIn("`warning`", contract_flat)


if __name__ == "__main__":
    unittest.main()

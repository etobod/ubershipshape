"""Repository-wide rules for the skills tree (plain unittest, no tooling)."""

import ast
import json
import unittest

from tests.skill_loader import REPO_ROOT

SKILLS = REPO_ROOT / "skills"
TESTS = REPO_ROOT / "tests"

# Top-level modules that reach the network; only ush-advice may go online, and it does
# so through the model, never through Python code.
NETWORK_MODULES = {
    "asyncio", "ftplib", "http", "imaplib", "poplib", "requests", "smtplib", "socket",
    "socketserver", "ssl", "telnetlib", "urllib", "webbrowser", "xmlrpc",
}


def network_imports(path) -> list[str]:
    """Top-level names of forbidden network modules imported by one .py file.

    Both ``import x.y`` and ``from x.y import z`` count; relative imports do not.
    """
    with open(path, encoding="utf-8-sig") as handle:
        tree = ast.parse(handle.read(), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top in NETWORK_MODULES:
                found.append(top)
    return found

# The only non-ASCII characters allowed, and only in references/*.md:
# the report legend (wrench, magnifier, check mark, cross mark), the em dash,
# the Polish quotes, the ellipsis and the Polish letters of report examples.
LEGEND = {"\U0001F527", "\U0001F50D", "✅", "❌"}
REFERENCE_TEXT = set("\u2014\u201e\u201d\u2026"
                     "\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c"
                     "\u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b")


def check_charset(path, references: bool) -> list[str]:
    """Non-ASCII problems of one skill file; ``references``: a references/*.md file."""
    allowed = LEGEND | REFERENCE_TEXT if references else set()
    try:
        name = path.relative_to(REPO_ROOT)
    except ValueError:
        name = path
    errors = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        bad = sorted({c for c in line if ord(c) > 127 and c not in allowed})
        if bad:
            errors.append(f"{name}:{number}: non-ASCII "
                          f"{', '.join(f'U+{ord(c):04X}' for c in bad)}")
    return errors


def _keys(data):
    """Yield every object key in parsed JSON, at any depth."""
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield from item.keys()
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


class TestRepoRules(unittest.TestCase):
    def test_skills_ascii(self):
        plain = (
            set(SKILLS.glob("**/*.py"))
            | set(SKILLS.glob("**/*.json"))
            | set(SKILLS.glob("**/SKILL.md"))
        )
        references = set(SKILLS.glob("**/references/*.md"))
        self.assertTrue(plain and references, f"no skill files found under {SKILLS}")

        for path in sorted(plain | references):
            errors = check_charset(path, path in references and path not in plain)
            self.assertFalse(errors, "\n".join(errors))

        for path in sorted(SKILLS.glob("**/data/*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in _keys(data):
                self.assertTrue(
                    key.isascii(), f"{path.relative_to(REPO_ROOT)}: non-ASCII key {key!r}"
                )

    def test_reference_charset(self):
        import tempfile
        from pathlib import Path

        check_charset = globals().get("check_charset")
        self.assertIsNotNone(
            check_charset, "tests/test_repo_rules.py has no module-level check_charset()"
        )

        polish_typography = "— „ ” … ąŁ"
        legend = "\U0001F527 \U0001F50D ✅ ❌"
        cases = (
            # (label, file name, text, references flag, errors expected)
            ("reference with dash, quotes, ellipsis and Polish letters",
             "references/report-format.md", f"Line {polish_typography} end.\n", True, False),
            ("reference with legend icons",
             "references/report-format.md", f"- {legend} legend\n", True, False),
            ("reference with an e acute",
             "references/report-format.md", f"Line {polish_typography} café.\n", True, True),
            ("SKILL.md with a dash", "SKILL.md", "Line — end.\n", False, True),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for index, (label, name, text, references, expect_errors) in enumerate(cases):
                with self.subTest(label):
                    path = Path(tmp) / "skills" / f"ush-case{index}" / name
                    path.parent.mkdir(parents=True)
                    path.write_text(text, encoding="utf-8")
                    errors = check_charset(path, references)
                    self.assertIsInstance(errors, list)
                    if expect_errors:
                        self.assertTrue(errors, f"{label}: expected an error")
                    else:
                        self.assertEqual(errors, [], f"{label}: expected no error")

    def test_noise_entries_shape(self):
        path = SKILLS / "ush-events" / "data" / "noise.json"
        entries = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(entries, list, "noise.json must be a plain list")
        for index, entry in enumerate(entries):
            with self.subTest(entry=index):
                self.assertIsInstance(entry, dict)
                # Only the general fields; local evidence stays out of the repo.
                self.assertEqual(set(entry), {"provider", "event_id", "reason"})
                for field in ("provider", "reason"):
                    self.assertIsInstance(entry[field], str)
                    self.assertTrue(entry[field].strip(), f"empty {field}")
                self.assertIs(type(entry["event_id"]), int, "event_id must be an int")

    def test_no_network_imports(self):
        import tempfile
        from pathlib import Path

        cases = (
            ("import_urllib.py", "import urllib.request\n", "urllib"),
            ("from_http.py", "from http import client\n", "http"),
            ("import_socket.py", "import socket\n", "socket"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for name, text, module in cases:
                with self.subTest(name):
                    path = Path(tmp) / name
                    path.write_text(text, encoding="utf-8")
                    self.assertEqual(network_imports(path), [module], text)

        files = sorted(set(SKILLS.glob("**/*.py")) | set(TESTS.glob("**/*.py")))
        self.assertTrue(files, f"no .py files under {SKILLS} or {TESTS}")
        for path in files:
            with self.subTest(str(path.relative_to(REPO_ROOT))):
                self.assertEqual(network_imports(path), [],
                                 f"{path.relative_to(REPO_ROOT)} imports a network module")


if __name__ == "__main__":
    unittest.main()

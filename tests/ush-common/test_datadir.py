"""The data directory: skills/ush-common/scripts/datadir.py and its use by every script.

Public interface under test:
- ``datadir.resolve(arg, environ=os.environ) -> Path`` and ``datadir.DataDirError``.
  Order: ``arg`` (``Path(arg).absolute()``; ``""`` is an error), else a non-empty absolute
  ``USH_DATA_DIR``, else ``<LOCALAPPDATA>/ubershipshape`` when ``LOCALAPPDATA`` is non-empty
  and absolute, else ``DataDirError`` naming ``--data-dir``.
- ``--data-dir`` of events.py, logs.py, dumps.py, health.py and check_report.py defaults to
  that order; no data directory is a parser error (exit code 2, message on stderr) before
  any machine function runs.

Every environment here is invented and passed explicitly, or ``os.environ`` is patched with
``clear=True``; the real %LOCALAPPDATA% is never read or written. Machine functions are
fakes that record and refuse every call.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT, load_script


def temp_dir(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


def chdir(test, path):
    previous = os.getcwd()
    os.chdir(path)
    test.addCleanup(os.chdir, previous)


class TestResolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.datadir = load_script("ush-common", "datadir")

    def setUp(self):
        self.root = temp_dir(self)
        self.ush = self.root / "invented-ush-data-dir"
        self.appdata = self.root / "InventedAppData" / "Local"

    def test_precedence(self):
        both = {"USH_DATA_DIR": str(self.ush), "LOCALAPPDATA": str(self.appdata)}
        cwd = self.root / "invented-cwd"
        cwd.mkdir()
        chdir(self, cwd)

        with self.subTest("an explicit relative arg wins over both variables"):
            self.assertEqual(self.datadir.resolve("rel", environ=dict(both)),
                             Path(os.getcwd()) / "rel")

        with self.subTest("USH_DATA_DIR wins over LOCALAPPDATA"):
            self.assertEqual(self.datadir.resolve(None, environ=dict(both)), self.ush)

        with self.subTest("LOCALAPPDATA without USH_DATA_DIR"):
            self.assertEqual(
                self.datadir.resolve(None, environ={"LOCALAPPDATA": str(self.appdata)}),
                self.appdata / "ubershipshape")

        with self.subTest("an empty USH_DATA_DIR is skipped"):
            self.assertEqual(
                self.datadir.resolve(None, environ={"USH_DATA_DIR": "",
                                                    "LOCALAPPDATA": str(self.appdata)}),
                self.appdata / "ubershipshape")

    def test_errors(self):
        both = {"USH_DATA_DIR": str(self.ush), "LOCALAPPDATA": str(self.appdata)}
        cases = {
            "relative USH_DATA_DIR": (None, {"USH_DATA_DIR": "invented-relative-dir",
                                             "LOCALAPPDATA": str(self.appdata)}),
            "neither variable": (None, {}),
            "relative LOCALAPPDATA": (None, {"LOCALAPPDATA": "invented-relative-appdata"}),
            "empty arg with both variables set": ("", dict(both)),
        }
        for label, (arg, environ) in cases.items():
            with self.subTest(label):
                with self.assertRaises(self.datadir.DataDirError) as raised:
                    self.datadir.resolve(arg, environ=environ)
                self.assertIn("--data-dir", str(raised.exception), label)


class Recorder:
    """Fake machine functions: each call is recorded and refused."""

    def __init__(self):
        self.calls = []

    def fake(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"{name} was called")
        return call

    def kwargs(self, names):
        return {name: self.fake(name) for name in names}


# (label, skill, script, argv without --data-dir, injected machine function names, now)
SCRIPTS = (
    ("logs.py", "ush-events", "logs", ["--export", "System"], ("run", "is_admin"), True),
    ("dumps.py", "ush-events", "dumps", [],
     ("read_value", "list_dir", "stat", "open_file", "copy", "remove", "disk_usage"), True),
    ("health.py", "ush-health", "health", [], ("run_ps", "is_admin"), True),
    ("advice.py", "ush-advice", "advice", [], ("run_ps",), True),
    ("files.py", "ush-files", "files", [], ("list_drives", "scan_dir", "disk_usage", "is_admin"),
     True),
    ("runall.py", "ush-runall", "runall", [], ("run_child",), True),
    ("check_report.py", "ush-common", "check_report", ["--latest", "--skill", "ush-events"],
     (), False),
)
EVENTS = ("events.py", "ush-events", "events", [], ("run_ps", "read_dumps"), True)


def events_summary(detail_file):
    return {
        "skill": "ush-events",
        "bugcheck_code": "0x0000019c",
        "last_bugcheck_time": "2026-09-18T10:15:00+00:00",
        "event_count": 1234,
        "boot_count": 1,
        "max_per_source": 234,
        "avg_per_day": 3.5,
        "detail_file": str(detail_file),
    }


def events_detail():
    return {
        "groups": [
            {"id": "g1", "provider": "Invented-Provider", "event_id": 41, "count": 4321},
        ],
        "noise": [],
        "boots": [],
        "anomalies": [],
    }


def events_body():
    """A valid ush-events report after the ush:summary line; every number is in the JSON."""
    return [
        "# Event log report",
        "",
        "Bugcheck 0x19C was recorded on 18.09.2026.",
        "Events in total: 1 234.",
        "Average per day: 3,5.",
        "<!-- ush:detail g1 -->",
        "The largest group has 4321 events.",
        "## 1. Findings",
        "- Nothing else stands out.",
        "",
        "## Not checked",
        "<!-- ush:not-checked -->",
        "Nothing.",
    ]


class TestScripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = {script: load_script(skill, script)
                       for _, skill, script, _, _, _ in (*SCRIPTS, EVENTS)}

    def run_script(self, spec, argv, environ):
        """Run main with refusing fakes; return (code, stdout, stderr, recorder)."""
        _, _, script, _, names, with_now = spec
        recorder = Recorder()
        kwargs = recorder.kwargs(names)
        if with_now:
            kwargs["now"] = None
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.dict(os.environ, environ, clear=True):
            try:
                code = self.modules[script].main(argv, **kwargs)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue(), recorder

    def test_no_data_dir_is_usage_error(self):
        cwd = temp_dir(self)
        chdir(self, cwd)

        for spec in SCRIPTS:
            label, _, _, argv, _, _ = spec
            with self.subTest(label):
                code, out, err, recorder = self.run_script(spec, list(argv), {})
                self.assertEqual(code, 2, out[:300] + err[:300])
                self.assertIn("--data-dir", err)
                error_lines = [line for line in err.splitlines() if "error:" in line]
                self.assertTrue(any("--data-dir" in line for line in error_lines), err)
                self.assertEqual(recorder.calls, [])
                self.assertEqual(list(cwd.iterdir()), [])

        for spec in (*SCRIPTS, EVENTS):
            label = spec[0]
            with self.subTest(f"{label} --help"):
                code, out, err, recorder = self.run_script(spec, ["--help"], {})
                self.assertEqual(code, 0, err[:300])
                self.assertIn("LOCALAPPDATA", out)
                self.assertEqual(recorder.calls, [])

    def test_latest_uses_default_dir(self):
        appdata = temp_dir(self)
        chdir(self, temp_dir(self))
        data_dir = appdata / "ubershipshape"
        work = data_dir / "work"
        reports = data_dir / "reports"
        work.mkdir(parents=True)
        reports.mkdir()
        detail_file = work / "events-detail.json"
        summary_file = work / "events-summary.json"
        detail_file.write_text(json.dumps(events_detail()), encoding="utf-8")
        summary_file.write_text(json.dumps(events_summary(detail_file)), encoding="utf-8")
        report = reports / "events-2026-09-20-0715.md"
        report.write_text("\n".join([f"<!-- ush:summary {summary_file} -->", *events_body()])
                          + "\n", encoding="utf-8")

        spec = SCRIPTS[-1]
        code, out, err, _ = self.run_script(
            spec, ["--latest", "--skill", "ush-events"], {"LOCALAPPDATA": str(appdata)})
        output = out + err
        self.assertEqual(code, 0, output)
        self.assertIn("OK", output)
        self.assertIn(report.name, output)

    def test_no_old_default_in_scripts(self):
        files = sorted((REPO_ROOT / "skills").glob("**/scripts/*.py"))
        self.assertTrue(files, "no skill scripts found")
        offenders = [str(path.relative_to(REPO_ROOT)) for path in files
                     if "ush-data" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])


def read_text(path):
    return path.read_text(encoding="utf-8")


CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def relative(path):
    return path.relative_to(REPO_ROOT).as_posix()


class TestDocs(unittest.TestCase):
    """The docs name the data directory, not the old ``ush-data`` default."""

    def test_docs_use_data_dir(self):
        skills = REPO_ROOT / "skills"
        skill_docs = sorted(skills.glob("**/SKILL.md"))
        references = sorted(skills.glob("**/references/*.md"))
        self.assertTrue(skill_docs, "no skills/**/SKILL.md found")
        self.assertTrue(references, "no skills/**/references/*.md found")

        for path in (*skill_docs, *references):
            with self.subTest(relative(path)):
                self.assertNotIn("ush-data", read_text(path))

        elevated = [path for path in skill_docs
                    if any(word in read_text(path).lower()
                           for word in ("elevated", "administrator"))]
        detected = {relative(path) for path in elevated}
        for expected in ("skills/ush-events/SKILL.md", "skills/ush-health/SKILL.md"):
            with self.subTest(f"{expected} detected as having an elevated-shell block"):
                self.assertIn(expected, detected)
        for path in elevated:
            with self.subTest(f"{relative(path)} passes the data dir to the elevated shell"):
                self.assertIn('--data-dir "<absolute data dir>"', read_text(path))

    @unittest.skipUnless(CLAUDE_MD.is_file(), "CLAUDE.md is gitignored; absent in a fresh clone")
    def test_claude_md(self):
        claude = read_text(CLAUDE_MD)
        for old in ("--data-dir ush-data", "ush-data/reports", "default `ush-data`"):
            with self.subTest(f"CLAUDE.md without {old!r}"):
                self.assertNotIn(old, claude)

        with self.subTest("CLAUDE.md --data-dir rule names USH_DATA_DIR"):
            rule_lines = [line for line in claude.splitlines()
                          if "Scripts take `--data-dir`" in line]
            self.assertTrue(rule_lines, "no line with the rule 'Scripts take `--data-dir`'")
            for line in rule_lines:
                self.assertIn("USH_DATA_DIR", line)

        for needle in ("%LOCALAPPDATA%\\ubershipshape", "USH_DATA_DIR"):
            with self.subTest(f"CLAUDE.md contains {needle!r}"):
                self.assertIn(needle, claude)

    def test_placeholder_passes_checker(self):
        """The report text spells the placeholder ``&lt;data dir>``: ``<d`` fails the checker."""
        for path in (REPO_ROOT / "skills" / "ush-events" / "SKILL.md",
                     REPO_ROOT / "skills" / "ush-health" / "SKILL.md",
                     REPO_ROOT / "skills" / "ush-events" / "references" / "report-format.md",
                     REPO_ROOT / "skills" / "ush-health" / "references" / "report-format.md"):
            text = " ".join(read_text(path).split())
            with self.subTest(relative(path)):
                self.assertIn("`&lt;data dir>` in plain text, never in inline code", text)
                self.assertNotIn("write `<data dir>`", text)
                self.assertNotIn("writes `<data dir>`", text)

    def test_default_named(self):
        contract = REPO_ROOT / "skills" / "ush-common" / "references" / "summary-contract.md"
        with self.subTest(relative(contract)):
            self.assertIn("USH_DATA_DIR", read_text(contract))

        for skill in ("ush-events", "ush-health"):
            path = REPO_ROOT / "skills" / skill / "references" / "report-format.md"
            with self.subTest(relative(path)):
                self.assertIn("<data dir>", read_text(path))


if __name__ == "__main__":
    unittest.main()

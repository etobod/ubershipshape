"""The data directory: skills/ush-common/scripts/datadir.py and its use by every script.

Public interface under test:
- ``datadir.resolve(arg, environ=os.environ, default=None) -> Path`` and
  ``datadir.DataDirError``. Order: ``arg`` (``Path(arg).absolute()``; ``""`` is an error),
  else a non-empty absolute ``USH_DATA_DIR``, else ``default`` (``--default-data-dir``:
  absolute, no ``${``), else ``DataDirError`` naming ``--data-dir``. ``LOCALAPPDATA`` is
  never a fallback.
- ``--data-dir`` and ``--default-data-dir`` of every skill script follow that order; no
  data directory is a parser error (exit code 2, message on stderr) before any machine
  function runs.

Every environment here is invented and passed explicitly, or ``os.environ`` is patched with
``clear=True``; the real %LOCALAPPDATA% is never read or written. Machine functions are
fakes that record and refuse every call.
"""

import contextlib
import importlib
import io
import json
import os
import subprocess
import tempfile
import traceback
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

        with self.subTest("an empty USH_DATA_DIR is skipped"):
            default = self.root / "invented-plugin-data"
            self.assertEqual(
                self.datadir.resolve(None, environ={"USH_DATA_DIR": "",
                                                    "LOCALAPPDATA": str(self.appdata)},
                                     default=str(default)),
                default)

    def test_plugin_default_order(self):
        default = self.root / "invented-plugin-data"
        with self.subTest("--data-dir wins over USH_DATA_DIR and the default"):
            self.assertEqual(
                self.datadir.resolve(str(self.root / "arg"), environ={"USH_DATA_DIR": str(self.ush)},
                                     default=str(default)),
                self.root / "arg")
        with self.subTest("USH_DATA_DIR wins over the default"):
            self.assertEqual(
                self.datadir.resolve(None, environ={"USH_DATA_DIR": str(self.ush)},
                                     default=str(default)),
                self.ush)
        with self.subTest("the default when nothing else is given"):
            self.assertEqual(
                self.datadir.resolve(None, environ={"LOCALAPPDATA": str(self.appdata)},
                                     default=str(default)),
                default)
        with self.subTest("only LOCALAPPDATA: no fallback, an error naming --data-dir"):
            with self.assertRaises(self.datadir.DataDirError) as raised:
                self.datadir.resolve(None, environ={"LOCALAPPDATA": str(self.appdata)})
            self.assertIn("--data-dir", str(raised.exception))

    def test_plugin_default_rejected(self):
        cases = {
            "relative": "invented-relative-default",
            "empty": "",
            "blank": "   ",
            "unexpanded variable": "${CLAUDE_PLUGIN_DATA}",
            "unexpanded variable inside an absolute path": str(self.root / "${CLAUDE_PLUGIN_DATA}"),
        }
        for label, value in cases.items():
            with self.subTest(label):
                with self.assertRaises(self.datadir.DataDirError) as raised:
                    self.datadir.resolve(None, environ={"LOCALAPPDATA": str(self.appdata)},
                                         default=value)
                self.assertIn("--default-data-dir", str(raised.exception))
                self.assertEqual(list(self.root.iterdir()), [], label)

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
    ("files.py", "ush-files", "files", [], ("list_drives", "scan_dir", "disk_usage", "is_admin",
                                            "shell_folder"), True),
    ("runall.py", "ush-runall", "runall", [], ("run_child",), True),
    ("check_report.py", "ush-common", "check_report", ["--latest", "--skill", "ush-events"],
     (), False),
)
EVENTS = ("events.py", "ush-events", "events", [], ("run_ps", "read_dumps"), True)

# Plan 020 M1 (K3): all twelve skill scripts, for ``--default-data-dir`` and for the
# removed ``<LOCALAPPDATA>/ubershipshape`` fallback. Same shape as SCRIPTS.
DEFAULT_FLAG_SCRIPTS = (
    *SCRIPTS,
    EVENTS,
    ("inventory.py", "ush-inventory", "inventory", [], ("run_ps", "is_admin"), True),
    ("processes.py", "ush-processes", "processes", [], ("run_ps", "is_admin"), True),
    ("settings.py", "ush-settings", "settings", [], ("run_ps", "is_admin"), True),
    ("check_repair_plan.py", "ush-common", "check_repair_plan", ["--latest"], (), False),
)


def other_test_module(name):
    """Another test module of this repository (its fakes), imported on first use."""
    return importlib.import_module(f"tests.{name}")


def refuse_process(*args, **kwargs):
    raise AssertionError(f"a real process function was called: {args!r}")


def tree(root):
    """Every path under ``root``, relative, sorted."""
    return sorted(str(path.relative_to(root)) for path in Path(root).rglob("*"))


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
                self.assertIn("--default-data-dir", out)
                self.assertEqual(recorder.calls, [])

    def test_latest_uses_default_dir(self):
        appdata = temp_dir(self)
        chdir(self, temp_dir(self))
        data_dir = temp_dir(self) / "invented-plugin-data"
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
            spec, ["--latest", "--skill", "ush-events", "--default-data-dir", str(data_dir)],
            {"LOCALAPPDATA": str(appdata)})
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

    # --- plan 020 M1 (K3): --default-data-dir, no LOCALAPPDATA fallback ---------------

    def call_main(self, script, argv, kwargs, environ, patches=()):
        """Run ``main``; return (code, stdout, stderr). An exception from main is turned
        into a text code so that the assertion on the code names it."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(mock.patch.dict(os.environ, environ, clear=True))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            try:
                code = self.modules[script].main(argv, **kwargs)
            except SystemExit as exc:
                code = exc.code
            except Exception as exc:  # noqa: BLE001 - reported through the assertion on the code
                code = f"raised {type(exc).__name__}: {exc}"
                err.write(traceback.format_exc())
        return code, out.getvalue(), err.getvalue()

    def assert_under(self, path, data_dir, context):
        self.assertTrue(Path(path).is_absolute(), f"{path} ({context})")
        self.assertTrue(Path(path).resolve().is_relative_to(data_dir.resolve()),
                        f"{path} is not under {data_dir} ({context})")

    def assert_summary_under(self, data_dir, code, out, err):
        """A collection: exit 0 and the detail file of the stdout summary under data_dir."""
        self.assertEqual(code, 0, out[-300:] + err[-600:])
        try:
            summary = json.loads(out)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {out[:300]!r}")
        self.assertIsInstance(summary, dict, out[:300])
        detail = summary.get("detail_file")
        self.assertIsInstance(detail, str, sorted(summary))
        self.assertTrue(Path(detail).is_file(), detail)
        self.assert_under(detail, data_dir, "detail_file")

    def flag_case(self, script, data_dir, scratch):
        """(argv without the flag, injected kwargs, patches, check(code, out, err)) of one
        script run with working machine fakes; ``check`` shows the data dir was used."""
        if script == "logs":
            base = other_test_module("ush-events.test_logs")
            fake = base.FakeRun(log="System")

            def check(code, out, err):
                self.assertEqual(code, 0, out[-300:] + err[-600:])
                self.assertTrue((data_dir / "exports" / "manifest.json").is_file(),
                                tree(data_dir))
                self.assertIsNotNone(fake.export_path, fake.calls)
                self.assert_under(fake.export_path, data_dir, "export file")
            return (["--export", "System"],
                    {"run": fake, "is_admin": base.FakeAdmin(False), "now": base.NOW},
                    (), check)

        if script == "dumps":
            base = other_test_module("ush-events.test_dumps")
            machine = base.FakeMachine(scratch / "dumps-machine")
            machine.write(machine.minidump_dir / base.MINI_NAME, base.MINI_DATA,
                          base.MINI_TIME)

            def check(code, out, err):
                self.assertEqual(code, 0, out[-300:] + err[-600:])
                self.assertTrue((data_dir / "dumps" / "manifest.json").is_file(),
                                tree(data_dir))
            return ["--copy"], {**machine.functions(), "now": base.NOW}, (), check

        def collection(code, out, err):
            self.assert_summary_under(data_dir, code, out, err)

        if script == "health":
            fakes = other_test_module("ush-health.fakes")
            return ([], {"run_ps": fakes.FakePowerShell(), "is_admin": lambda: True,
                         "now": fakes.NOW}, (), collection)

        if script == "advice":
            fakes = other_test_module("ush-advice.fakes")
            patches = (mock.patch.object(self.modules["advice"], "default_run_ps",
                                         fakes.machine_touched, create=True),)
            return [], {"run_ps": fakes.FakePowerShell(), "now": fakes.NOW}, patches, \
                collection

        if script == "files":
            fakes = other_test_module("ush-files.fakes")
            machine = fakes.FakeMachine({"C": {"invented.txt": 100}})
            return ([], {"list_drives": machine.list_drives, "scan_dir": machine.scan_dir,
                         "disk_usage": machine.disk_usage, "is_admin": machine.is_admin,
                         "shell_folder": machine.shell_folder, "now": fakes.NOW,
                         "environ": fakes.fake_environ()}, (), collection)

        if script == "runall":
            base = other_test_module("ush-runall.test_runall")
            children = base.FakeChildren(scratch / "runall-children")
            patches = (mock.patch.object(subprocess, "Popen", refuse_process),
                       mock.patch.object(subprocess, "run", refuse_process))
            return [], {"run_child": children, "now": base.NOW}, patches, collection

        if script == "events":
            base = other_test_module("ush-events.test_collect")
            return ([], {"run_ps": base.FakePowerShell(), "now": base.NOW,
                         "read_dumps": base.NO_DUMPS}, (), collection)

        if script in ("inventory", "processes"):
            fakes = other_test_module(f"ush-{script}.fakes")
            return ([], {"run_ps": fakes.FakePowerShell(), "is_admin": lambda: False,
                         "now": fakes.NOW}, (), collection)

        if script == "settings":
            fakes = other_test_module("ush-settings.fakes")
            fake = fakes.FakePowerShell(fakes.clean_responses(fakes.real_entries()))
            return ([], {"run_ps": fake, "is_admin": lambda: False, "now": fakes.NOW},
                    (), collection)

        if script == "check_report":
            work = data_dir / "work"
            reports = data_dir / "reports"
            work.mkdir(parents=True, exist_ok=True)
            reports.mkdir(parents=True, exist_ok=True)
            detail_file = work / "events-detail.json"
            summary_file = work / "events-summary.json"
            detail_file.write_text(json.dumps(events_detail()), encoding="utf-8")
            summary_file.write_text(json.dumps(events_summary(detail_file)),
                                    encoding="utf-8")
            report = reports / "events-2026-09-20-0715.md"
            report.write_text("\n".join([f"<!-- ush:summary {summary_file} -->",
                                         *events_body()]) + "\n", encoding="utf-8")

            def check(code, out, err):
                output = out + err
                self.assertEqual(code, 0, output[-600:])
                self.assertIn("OK", output)
                self.assertIn(report.name, output)
            return ["--latest", "--skill", "ush-events"], {}, (), check

        if script == "check_repair_plan":
            base = other_test_module("ush-common.test_check_repair_plan")
            plans = data_dir / "plans"
            plans.mkdir(parents=True, exist_ok=True)
            plan = plans / "2026-10-29-plan-telemetria.md"
            plan.write_text(base._plan(), encoding="utf-8")

            def check(code, out, err):
                self.assertEqual(code, 0, out[-300:] + err[-600:])
                try:
                    result = json.loads(out)
                except ValueError as exc:
                    self.fail(f"stdout is not JSON ({exc}): {out[:300]!r}")
                self.assertIsInstance(result.get("file"), str, result)
                self.assertTrue(base._same_path(result.get("file"), str(plan)),
                                result.get("file"))
            return ["--latest"], {}, (), check

        self.fail(f"no flag case for {script}")

    def test_default_data_dir_flag(self):
        for _, skill, script, _, _, _ in DEFAULT_FLAG_SCRIPTS:
            if script not in self.modules:
                self.modules[script] = load_script(skill, script)
        chdir(self, temp_dir(self))

        for label, _, script, _, _, _ in DEFAULT_FLAG_SCRIPTS:
            with self.subTest(f"{label} --default-data-dir"):
                scratch = temp_dir(self)
                data_dir = scratch / "invented-default-data-dir"
                data_dir.mkdir()
                appdata = scratch / "InventedAppData" / "Local"
                appdata.mkdir(parents=True)
                profile = scratch / "Users" / "contoso"
                profile.mkdir(parents=True)
                environ = {"LOCALAPPDATA": str(appdata), "USERPROFILE": str(profile),
                           "SystemRoot": "C:\\Windows"}
                argv, kwargs, patches, check = self.flag_case(script, data_dir, scratch)
                code, out, err = self.call_main(
                    script, [*argv, "--default-data-dir", str(data_dir)], kwargs, environ,
                    patches)
                check(code, out, err)
                self.assertEqual(tree(appdata), [], "written under LOCALAPPDATA")

        for spec in DEFAULT_FLAG_SCRIPTS:
            label, _, script, argv, names, with_now = spec
            with self.subTest(f"{label} without a data directory, LOCALAPPDATA set"):
                appdata = temp_dir(self) / "InventedAppData" / "Local"
                appdata.mkdir(parents=True)
                recorder = Recorder()
                kwargs = recorder.kwargs(names)
                if with_now:
                    kwargs["now"] = None
                code, out, err = self.call_main(script, list(argv), kwargs,
                                                {"LOCALAPPDATA": str(appdata)})
                self.assertEqual(code, 2, out[:300] + err[-600:])
                error_lines = [line for line in err.splitlines() if "error:" in line]
                self.assertTrue(any("--data-dir" in line for line in error_lines), err)
                self.assertEqual(recorder.calls, [])
                self.assertEqual(tree(appdata), [], "created under LOCALAPPDATA")


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

        for needle in ("--default-data-dir", "USH_DATA_DIR"):
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

"""Tests for skills/ush-runall/scripts/runall.py (plan 098, M1): the child command line,
the children.json checks, the default run_child on a timeout, the run going on after a
child fails, and the summary and detail files.

Interface under test (from the plan):

- The script is loaded with ``load_script("ush-runall", "runall")``.
- ``main(argv=None, run_child=None, now=None) -> int``; the tests always pass
  ``--data-dir <tmp dir>`` and inject ``run_child``.
- ``child_argv(child, data_dir)`` gives exactly
  ``[sys.executable, "-B", <absolute script path under skills/>, "--data-dir", <data_dir>]``.
- ``run_child(argv, timeout_s) -> {returncode, stdout, stderr_tail, duration_s}``.
- ``data/children.json`` is an ordered list of ``{skill, script, timeout_s}``; a bad file
  exits 2 before any child runs.
- The default run_child uses ``subprocess.Popen`` and, on ``TimeoutExpired``, calls the
  module function ``kill_tree(pid)`` (``taskkill /T /F /PID <pid>`` through
  ``subprocess.run``) before ``proc.kill()``, then raises ``TimeoutExpired`` again.
- Child status: ``ok``, ``failed``, ``timeout``, ``bad_output``; every status other than
  ``ok`` gives one ``not_checked`` entry and the run goes on.
- Summary: the common fields, ``children`` (ids ``h...`` in run order, each with
  ``skill``, ``status``, ``exit_code``, ``duration_s``, ``summary_file``,
  ``not_checked_count``, ``truncated``, ``elevated``), ``counts``, ``duration_s``,
  ``not_checked``. Detail file: ``children`` with the same ids and ``summary`` (the full
  child summary, ``null`` when the status is not ``ok``).

Assumptions added by these tests beyond the plan text:

- ``main`` prints the runall summary JSON, and only it, on stdout and writes
  ``<data dir>/work/runall-*.summary.json`` and ``runall-*.detail.json``; the summary
  names both in ``summary_file`` and ``detail_file`` (absolute paths). A usage or
  children.json error may be a return value or a ``SystemExit``; both are accepted.
- ``now`` is a timezone-aware ``datetime``.
- The module reads children.json from its path constant ``CHILDREN_FILE`` at run time,
  so a test injects another file by patching ``CHILDREN_FILE``.
- ``child_argv`` takes a children.json entry as a dict; its path elements may be ``str``
  or ``Path`` (compared as ``str``).
- The default run_child is the module attribute ``default_run_child``.
- Each ``children`` item carries ``id``; each detail ``children`` item carries ``id`` and
  ``summary``.
- The runall ``sources`` entry of a child names it in some value (its skill, e.g.
  ``"ush-events"``, its id or its script name) and carries ``status``.
- A runall ``not_checked`` entry about a failed child names the child's skill somewhere
  in its JSON text; the ``OSError`` type name appears in that entry or in the child's
  ``children`` item.
- The fake child summaries of ``ush-inventory`` and ``ush-processes`` point to readable,
  empty detail files with ``firewall_rules`` / ``tcp_listeners`` read, so that the
  firewall comparison of milestone M2 adds no ``not_checked`` entry to clean runs.

No real process is started: ``run_child`` is a fake, and ``subprocess.Popen`` and
``subprocess.run`` are replaced by fakes that record or refuse. Every value is invented.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT, load_script

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
SKILLS_ROOT = REPO_ROOT / "skills"
REPO_CHILDREN = SKILLS_ROOT / "ush-runall" / "data" / "children.json"

# The order and time limits of the plan's table.
TABLE = (
    ("ush-health", "health.py", 1800),
    ("ush-events", "events.py", 1800),
    ("ush-settings", "settings.py", 1800),
    ("ush-inventory", "inventory.py", 1800),
    ("ush-processes", "processes.py", 1800),
    ("ush-files", "files.py", 3600),
    ("ush-advice", "advice.py", 1800),
)

# A valid order in which the 2nd to 5th children are not inventory or processes.
FAILURE_ORDER = (
    ("ush-health", "health.py", 1800),
    ("ush-events", "events.py", 1800),
    ("ush-settings", "settings.py", 1800),
    ("ush-files", "files.py", 3600),
    ("ush-advice", "advice.py", 1800),
    ("ush-inventory", "inventory.py", 1800),
    ("ush-processes", "processes.py", 1800),
)

FAKE_PID = 4242


def entries(rows):
    return [{"skill": skill, "script": script, "timeout_s": timeout} for skill, script, timeout
            in rows]


def same_path(a, b):
    return (os.path.normcase(os.path.realpath(str(a)))
            == os.path.normcase(os.path.realpath(str(b))))


def skill_of(argv):
    """The skill directory of the script in a child command line."""
    return Path(str(argv[2])).parent.parent.name


def result(returncode=0, stdout="", stderr_tail="", duration_s=1.5):
    return {"returncode": returncode, "stdout": stdout, "stderr_tail": stderr_tail,
            "duration_s": duration_s}


def refuse(*args, **kwargs):
    raise AssertionError(f"a real process function was called: {args!r} {kwargs!r}")


# --- outcomes of a fake child ----------------------------------------------------------

def ok(**kwargs):
    """Exit 0 with a valid summary; ``kwargs`` go to ``FakeChildren.summary``."""
    return lambda fake, skill, argv, timeout_s: result(
        stdout=json.dumps(fake.summary(skill, **kwargs)))


def exits(code, stderr_tail="invented first line\ninvented last line"):
    return lambda fake, skill, argv, timeout_s: result(returncode=code, stderr_tail=stderr_tail)


def prints(text):
    return lambda fake, skill, argv, timeout_s: result(stdout=text)


def times_out():
    def outcome(fake, skill, argv, timeout_s):
        raise subprocess.TimeoutExpired(argv, timeout_s)
    return outcome


def raises(exc):
    def outcome(fake, skill, argv, timeout_s):
        raise exc
    return outcome


class FakeChildren:
    """The injected ``run_child``: records each call and answers per skill.

    By default a child exits 0 with a valid summary of its skill. ``summaries`` keeps
    every summary handed out, by skill.
    """

    def __init__(self, files_dir, outcomes=None):
        self.files_dir = Path(files_dir)
        self.outcomes = dict(outcomes or {})
        self.calls = []
        self.summaries = {}

    def __call__(self, argv, timeout_s):
        self.calls.append(([str(part) for part in argv], timeout_s))
        skill = skill_of(argv)
        outcome = self.outcomes.get(skill, ok())
        return outcome(self, skill, argv, timeout_s)

    def summary(self, skill, skill_field=None, not_checked=(), truncated=0, extra=None):
        """Write an invented child summary and detail file and return the summary."""
        self.files_dir.mkdir(parents=True, exist_ok=True)
        stem = skill.replace("ush-", "")
        summary_file = self.files_dir / f"{stem}-2026-09-20-1200.summary.json"
        detail_file = self.files_dir / f"{stem}-2026-09-20-1200.detail.json"
        if skill == "ush-inventory":
            sources = [{"name": "firewall_rules", "status": "read"}]
            detail = {"sources": sources, "additions": []}
        elif skill == "ush-processes":
            sources = [{"name": "tcp_listeners", "status": "read"}]
            detail = {"sources": sources, "groups": [], "ports": []}
        else:
            sources = [{"name": "invented_source", "status": "read"}]
            detail = {"sources": sources, "items": []}
        summary = {
            "schema_version": 1,
            "skill": skill_field or skill,
            "generated_at": "2026-09-20T12:00:00+00:00",
            "sources": sources,
            "not_checked": list(not_checked),
            "summary_file": str(summary_file),
            "detail_file": str(detail_file),
            "truncated": truncated,
            "marker": f"invented-marker-{stem}-7f3a",
        }
        if skill != "ush-events":
            summary["elevated"] = False
        summary.update(extra or {})
        detail_file.write_text(json.dumps(detail), encoding="utf-8")
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        self.summaries[skill] = summary
        return summary


class FakePopen:
    """A process that never runs: ``communicate`` with a timeout raises
    ``TimeoutExpired`` until ``kill`` is called. Every step goes to ``events``."""

    def __init__(self, events, args, **kwargs):
        self.events = events
        self.args = args
        self.kwargs = kwargs
        self.pid = FAKE_PID
        self.returncode = None
        self.stdout = None
        self.stderr = None
        self.stdin = None
        self.killed = False
        events.append(("popen", args))

    def communicate(self, input=None, timeout=None):
        self.events.append(("communicate", timeout))
        if not self.killed:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return "", ""

    def kill(self):
        self.events.append(("kill", self.pid))
        self.killed = True
        self.returncode = 1

    terminate = kill

    def wait(self, timeout=None):
        self.events.append(("wait", timeout))
        if not self.killed:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def poll(self):
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RunallTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runall = load_script("ush-runall", "runall")

    def temp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def data_dir(self):
        path = self.temp() / "invented-data-dir"
        path.mkdir()
        return path

    def children_file(self, children):
        path = self.temp() / "children.json"
        path.write_text(json.dumps(children), encoding="utf-8")
        return path

    def run_main(self, data_dir, run_child, extra=(), now=NOW, children=None):
        """Run main with ``run_child`` injected; return (code, stdout, stderr).
        ``children`` is a children.json path patched in as ``CHILDREN_FILE``. Real
        process functions refuse every call."""
        out, err = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            if children is not None:
                stack.enter_context(mock.patch.object(self.runall, "CHILDREN_FILE", children))
            stack.enter_context(mock.patch.object(subprocess, "Popen", refuse))
            stack.enter_context(mock.patch.object(subprocess, "run", refuse))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            try:
                code = self.runall.main(["--data-dir", str(data_dir), *extra],
                                        run_child=run_child, now=now)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            return json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")

    def collect(self, data_dir, run_child, now=NOW, children=None):
        """Run a full pass; the exit code must be 0. Return the summary."""
        code, stdout, stderr = self.run_main(data_dir, run_child, now=now, children=children)
        self.assertEqual(code, 0, (stdout[:300], stderr[-500:]))
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def items(self, data, key):
        value = data.get(key)
        self.assertIsInstance(value, list, f"{key}: {str(data)[:300]}")
        return value

    def child(self, summary, skill):
        matches = [c for c in self.items(summary, "children") if c.get("skill") == skill]
        self.assertEqual(len(matches), 1, f"child {skill}: {summary.get('children')}")
        return matches[0]

    def by_id(self, data, item_id):
        matches = [c for c in self.items(data, "children") if c.get("id") == item_id]
        self.assertEqual(len(matches), 1, f"item {item_id}: {str(data.get('children'))[:500]}")
        return matches[0]

    def detail(self, summary):
        path = Path(str(summary.get("detail_file")))
        self.assertTrue(path.is_absolute(), path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))
        return data

    def source_for(self, summary, child):
        names = {child.get("skill"), child.get("id"),
                 str(child.get("skill", "")).replace("ush-", "")}
        names.discard(None)
        sources = self.items(summary, "sources")
        matches = [s for s in sources
                   if isinstance(s, dict) and any(v in names for v in s.values()
                                                  if isinstance(v, str))]
        self.assertEqual(len(matches), 1, f"source of {child.get('skill')}: {sources}")
        return matches[0]

    def notes_about(self, summary, skill):
        return [entry for entry in self.items(summary, "not_checked")
                if skill in json.dumps(entry)]


class TestRunall(RunallTestCase):
    def test_argv_only_data_dir(self):
        children = json.loads(REPO_CHILDREN.read_text(encoding="utf-8"))
        self.assertIsInstance(children, list, children)
        self.assertTrue(children, "children.json is empty")
        data_dir = self.data_dir()

        expected = []
        for child in children:
            with self.subTest(child=child.get("skill")):
                argv = self.runall.child_argv(child, data_dir)
                self.assertEqual(len(argv), 5, argv)
                self.assertEqual(argv[0], sys.executable)
                self.assertEqual(argv[1], "-B")
                script = Path(str(argv[2]))
                self.assertTrue(script.is_absolute(), argv)
                self.assertTrue(same_path(script, SKILLS_ROOT / child["skill"] / "scripts"
                                          / child["script"]), argv)
                self.assertEqual(argv[3], "--data-dir")
                self.assertEqual(str(argv[4]), str(data_dir))
                expected.append([str(part) for part in argv])

        fake = FakeChildren(self.temp())
        self.collect(data_dir, fake)
        called = [argv for argv, _ in fake.calls]
        self.assertEqual(called, expected)

        skills = [skill_of(argv) for argv in called]
        self.assertIn("ush-inventory", skills)
        self.assertIn("ush-processes", skills)
        self.assertLess(skills.index("ush-inventory"), skills.index("ush-processes"), skills)
        for argv in called:
            for part in argv:
                self.assertNotIn(Path(part).name.lower(), ("logs.py", "dumps.py"), argv)

    def test_children_file_rejected(self):
        def table_with(**changes):
            rows = entries(TABLE)
            for skill, change in changes.items():
                for row in rows:
                    if row["skill"] == skill.replace("_", "-"):
                        row.update(change)
            return rows

        swapped = entries(TABLE)
        swapped[3], swapped[4] = swapped[4], swapped[3]
        cases = {
            "logs.py": table_with(ush_events={"script": "logs.py"}),
            "dumps.py": table_with(ush_events={"script": "dumps.py"}),
            "skill ush-runall": entries(TABLE) + [
                {"skill": "ush-runall", "script": "runall.py", "timeout_s": 1800}],
            "repeated skill": entries(TABLE) + [
                {"skill": "ush-health", "script": "health.py", "timeout_s": 1800}],
            "key args": table_with(ush_settings={"args": ["--block"]}),
            "skill ..": entries(TABLE) + [{"skill": "..", "script": "x.py", "timeout_s": 1800}],
            "script ..\\x.py": table_with(ush_health={"script": "..\\x.py"}),
            "script sub/x.py": table_with(ush_health={"script": "sub/x.py"}),
            "processes before inventory": swapped,
            # Windows opens logs.py for each of these names.
            "logs.py with a trailing dot": table_with(ush_events={"script": "logs.py."}),
            "logs.py with a trailing space": table_with(ush_events={"script": "logs.py "}),
            "logs.py with a stream suffix": table_with(
                ush_events={"script": "logs.py::$DATA"}),
        }

        with self.subTest("clean: the plan's table is accepted"):
            fake = FakeChildren(self.temp())
            self.collect(self.data_dir(), fake, children=self.children_file(entries(TABLE)))
            self.assertEqual(len(fake.calls), len(TABLE))

        for label, children in cases.items():
            with self.subTest(label):
                fake = FakeChildren(self.temp())
                code, stdout, stderr = self.run_main(self.data_dir(), fake,
                                                     children=self.children_file(children))
                self.assertEqual(code, 2, (stdout[:300], stderr[-300:]))
                self.assertEqual(fake.calls, [])

        with self.subTest("default run_child kills the tree before kill on a timeout"):
            events = []
            kills = []

            def popen(args, **kwargs):
                return FakePopen(events, args, **kwargs)

            def kill_tree(pid):
                events.append(("kill_tree", pid))
                kills.append(pid)

            argv = [sys.executable, "-B", "C:\\invented\\skills\\ush-x\\scripts\\x.py",
                    "--data-dir", "C:\\invented-data-dir"]
            with mock.patch.object(subprocess, "Popen", popen), \
                    mock.patch.object(subprocess, "run", refuse), \
                    mock.patch.object(self.runall, "kill_tree", kill_tree), \
                    self.assertRaises(subprocess.TimeoutExpired):
                self.runall.default_run_child(argv, 5)
            self.assertEqual(kills, [FAKE_PID], events)
            steps = [event[0] for event in events]
            self.assertIn("kill", steps, events)
            self.assertLess(steps.index("kill_tree"), steps.index("kill"), events)

        with self.subTest("kill_tree runs taskkill /T /F /PID on the child's pid"):
            runs = []

            def run(args, *rest, **kwargs):
                runs.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")

            with mock.patch.object(subprocess, "run", run), \
                    mock.patch.object(subprocess, "Popen", refuse):
                self.runall.kill_tree(FAKE_PID)
            self.assertEqual(len(runs), 1, runs)
            args = runs[0]
            tokens = [str(part).lower() for part in
                      (args.split() if isinstance(args, str) else args)]
            self.assertTrue(any(Path(t).name in ("taskkill", "taskkill.exe") for t in tokens),
                            tokens)
            for flag in ("/t", "/f", "/pid", str(FAKE_PID)):
                self.assertIn(flag, tokens)

    def test_unconfirmed_tree_kill_is_reported(self):
        """A timeout says the child's processes were stopped only when taskkill succeeded
        and the child's pipes closed (code review of M1, round 2)."""
        argv = [sys.executable, "-B", "C:/invented/skills/ush-x/scripts/x.py",
                "--data-dir", "C:/invented-data-dir"]

        class StuckPopen(FakePopen):
            """A grandchild keeps the pipes open: communicate never returns."""

            def communicate(self, input=None, timeout=None):
                self.events.append(("communicate", timeout))
                raise subprocess.TimeoutExpired(self.args, timeout)

        cases = (("taskkill succeeded", FakePopen, True, True),
                 ("taskkill failed", FakePopen, False, False),
                 ("pipes still open", StuckPopen, True, False))
        for label, popen_class, killed, expected in cases:
            with self.subTest(f"default run_child: {label}"):
                events = []

                def popen(args, events=events, popen_class=popen_class, **kwargs):
                    return popen_class(events, args, **kwargs)

                def kill_tree(pid, killed=killed):
                    return killed

                with mock.patch.object(subprocess, "Popen", popen), \
                        mock.patch.object(subprocess, "run", refuse), \
                        mock.patch.object(self.runall, "kill_tree", kill_tree), \
                        self.assertRaises(subprocess.TimeoutExpired) as caught:
                    self.runall.default_run_child(argv, 5)
                self.assertIs(getattr(caught.exception, "tree_stopped", None), expected)

        for label, run_code, expected in (("taskkill exit 0", 0, True),
                                          ("taskkill exit 128", 128, False)):
            with self.subTest(f"kill_tree: {label}"):
                def run(args, *rest, code=run_code, **kwargs):
                    return subprocess.CompletedProcess(args, code, "", "")

                with mock.patch.object(subprocess, "run", run), \
                        mock.patch.object(subprocess, "Popen", refuse):
                    self.assertIs(self.runall.kill_tree(FAKE_PID), expected)

        def timeout_with(stopped):
            def outcome(fake, skill, argv, timeout_s):
                exc = subprocess.TimeoutExpired(argv, timeout_s)
                exc.tree_stopped = stopped
                raise exc
            return outcome

        for label, stopped, unconfirmed in (("confirmed", True, False),
                                            ("not confirmed", False, True)):
            with self.subTest(f"timeout reason: {label}"):
                fake = FakeChildren(self.temp(), {"ush-settings": timeout_with(stopped)})
                summary = self.collect(self.data_dir(), fake,
                                       children=self.children_file(entries(TABLE)))
                self.assertEqual(self.child(summary, "ush-settings").get("status"), "timeout")
                entries_text = json.dumps(summary.get("not_checked"))
                self.assertEqual("not confirmed" in entries_text, unconfirmed, entries_text)
                self.assertEqual("stopped with the processes it started" in entries_text,
                                 not unconfirmed, entries_text)

    def test_one_failure_does_not_stop(self):
        failing = {
            "ush-events": ("failed", exits(1)),
            "ush-settings": ("timeout", times_out()),
            "ush-files": ("bad_output", prints("nie json")),
            "ush-advice": ("failed", raises(OSError("invented spawn failure"))),
        }
        fake = FakeChildren(self.temp(),
                            {skill: outcome for skill, (_, outcome) in failing.items()})
        summary = self.collect(self.data_dir(), fake,
                               children=self.children_file(entries(FAILURE_ORDER)))

        self.assertEqual([skill_of(argv) for argv, _ in fake.calls],
                         [skill for skill, _, _ in FAILURE_ORDER])
        for skill, (status, _) in failing.items():
            with self.subTest(skill):
                child = self.child(summary, skill)
                self.assertEqual(child.get("status"), status, child)
                notes = self.notes_about(summary, skill)
                self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertEqual(self.child(summary, "ush-events").get("exit_code"), 1)
        advice = self.child(summary, "ush-advice")
        self.assertIn("OSError",
                      json.dumps(advice) + json.dumps(self.notes_about(summary, "ush-advice")))
        self.assertEqual(len(self.items(summary, "not_checked")), len(failing),
                         summary.get("not_checked"))
        for skill in ("ush-health", "ush-inventory", "ush-processes"):
            with self.subTest(f"{skill} ok"):
                self.assertEqual(self.child(summary, skill).get("status"), "ok")

        with self.subTest("clean: seven valid children"):
            fake = FakeChildren(self.temp())
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(len(fake.calls), 7)
            self.assertEqual(summary.get("counts"), {"ok": 7})
            self.assertEqual(summary.get("not_checked"), [])
            children = self.items(summary, "children")
            self.assertEqual(len(children), 7, children)
            for child in children:
                self.assertEqual(self.source_for(summary, child).get("status"), "read", child)

        with self.subTest("exit 0 with another skill's summary is bad_output"):
            fake = FakeChildren(self.temp(), {"ush-health": ok(skill_field="ush-events")})
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-health").get("status"), "bad_output")
            self.assertEqual(len(self.notes_about(summary, "ush-health")), 1,
                             summary.get("not_checked"))

    def test_summary_and_detail(self):
        child_notes = [
            {"what": "invented check one", "reason": "invented reason"},
            {"what": "invented check two", "reason": "invented reason"},
            {"what": "invented check three", "reason": "invented reason"},
        ]
        data_dir = self.data_dir()
        fake = FakeChildren(self.temp(), {
            "ush-settings": ok(not_checked=child_notes, truncated=5),
            "ush-files": exits(1),
        })
        code, stdout, stderr = self.run_main(data_dir, fake)
        self.assertEqual(code, 0, stderr[-500:])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])

        ids = [c.get("id") for c in self.items(summary, "children")]
        self.assertEqual(ids, [f"h{n}" for n in range(1, len(TABLE) + 1)])

        settings = self.child(summary, "ush-settings")
        self.assertEqual(settings.get("status"), "ok", settings)
        self.assertEqual(settings.get("not_checked_count"), 3, settings)
        self.assertEqual(settings.get("truncated"), 5, settings)

        detail = self.detail(summary)
        self.assertEqual(self.by_id(detail, settings.get("id")).get("summary"),
                         fake.summaries["ush-settings"])

        files = self.child(summary, "ush-files")
        self.assertEqual(files.get("status"), "failed", files)
        files_detail = self.by_id(detail, files.get("id"))
        self.assertIn("summary", files_detail)
        self.assertIsNone(files_detail["summary"])
        self.assertEqual(self.source_for(summary, files).get("status"), "unreadable")

        events = self.child(summary, "ush-events")
        self.assertIn("elevated", events)
        self.assertIsNone(events["elevated"])

        self.assertEqual(summary.get("skill"), "ush-runall")
        for key in ("schema_version", "generated_at", "sources", "summary_file",
                    "detail_file", "truncated"):
            self.assertIn(key, summary)
        for key, pattern in (("summary_file", "runall-*.summary.json"),
                             ("detail_file", "runall-*.detail.json")):
            path = Path(str(summary[key]))
            self.assertTrue(path.is_absolute(), path)
            self.assertTrue(path.match(pattern), path)
            self.assertTrue(same_path(path.parent, data_dir / "work"), path)
            self.assertTrue(path.is_file(), path)

        for child in self.items(summary, "children"):
            self.assertNotIn("summary", child)
        for child_summary in fake.summaries.values():
            self.assertNotIn(child_summary["marker"], stdout)


if __name__ == "__main__":
    unittest.main()

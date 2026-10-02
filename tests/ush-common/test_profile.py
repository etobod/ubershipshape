"""Shared report check: the per-skill report profile and --latest (invented data only)."""

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOT_CHECKED = ["## Not checked", "<!-- ush:not-checked -->", "Nothing."]


def _profile(**overrides):
    profile = {
        "detail_sections": ["things"],
        "id_letters": "xy",
        "path_keys": ["detail_file", "summary_file"],
        "id_keys": ["id"],
        "required_lists": [],
        "truncated": None,
        "report_prefix": "test-",
    }
    profile.update(overrides)
    return profile

# A temporary path must not supply an id the tests assert on: x or y with a digit,
# or a lone c.
ID_LIKE = re.compile(r"[xy]\d|\bc\b")


def clean_temp_dir(make=None, attempts=20):
    """A temporary directory whose resolved path holds no id-like part.

    A colliding directory is cleaned up at once and another is drawn; when every
    attempt collides (e.g. the parent path itself does), the test fails with the path.
    """
    make = make or tempfile.TemporaryDirectory
    for _ in range(attempts):
        tmp = make()
        path = str(Path(tmp.name).resolve())
        if not ID_LIKE.search(path):
            return tmp
        tmp.cleanup()
    raise AssertionError(f"every temporary directory has an id-like part: {path}")


class CheckerTestCase(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = clean_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.summary_file = self.work_dir / "summary.json"
        self.detail_file = self.work_dir / "detail.json"

    def write_summary(self, data, path=None, with_skill=True):
        path = path or self.summary_file
        data = dict(data)
        if with_skill and "skill" not in data:
            data["skill"] = "ush-test"
        data["summary_file"] = str(path)
        data["detail_file"] = str(self.detail_file)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def write_detail(self, data):
        self.detail_file.write_text(json.dumps(data), encoding="utf-8")

    def write_report(self, body, name="test-2026-09-28-1200.md", summary=None,
                     reports_dir=None):
        path = (reports_dir or self.reports_dir) / name
        first = f"<!-- ush:summary {summary or self.summary_file} -->"
        path.write_text("\n".join([first, *body]) + "\n", encoding="utf-8")
        return path

    def run_argv(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def run_report(self, body, name="test-2026-09-28-1200.md"):
        return self.run_argv([str(self.write_report(body, name))])


class TestProfile(CheckerTestCase):
    """Tests K2-K5 run against a profile in a temporary skills directory."""

    def setUp(self):
        super().setUp()
        self.skills_dir = self.root / "skills"
        patcher = mock.patch.object(self.check, "SKILLS_DIR", self.skills_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_profile(self, profile, skill="ush-test"):
        path = self.skills_dir / skill / "data" / "report-profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile), encoding="utf-8")
        return path

    def test_unknown_skill_is_rejected(self):
        self.write_profile(_profile())
        self.write_detail({"things": []})
        body = ["# Test report", "There were 3 readings.", *NOT_CHECKED]

        # Control: the same report passes when the skill has a profile.
        self.write_summary({"count": 3})
        code, output = self.run_report(body, "control.md")
        self.assertEqual(code, 0, f"control report should pass; output:\n{output}")
        self.assertIn("OK", output)

        with self.subTest("summary without a skill key"):
            self.write_summary({"count": 3}, with_skill=False)
            # Report file names avoid the words asserted in the output.
            code, output = self.run_report(body, "case-a.md")
            self.assertEqual(code, 2, output)
            self.assertNotIn("OK", output)
            self.assertIn("skill", output)

        with self.subTest("skill without a profile file"):
            self.write_summary({"count": 3, "skill": "ush-nothing"})
            code, output = self.run_report(body, "case-b.md")
            self.assertEqual(code, 2, output)
            self.assertNotIn("OK", output)
            self.assertIn("ush-nothing", output)

        with self.subTest("skill name that is not ush-<letters>"):
            # Lexically this path leads to the ush-test profile, which exists.
            self.write_summary({"count": 3, "skill": "ush-nothing/../ush-test"})
            code, output = self.run_report(body, "case-c.md")
            self.assertEqual(code, 2, output)
            self.assertNotIn("OK", output)

    def test_id_letters_come_from_profile(self):
        # The digits 1 and 2 appear in the JSON only inside ids and file paths,
        # neither of which backs a number. The readings are 3 only.
        self.write_profile(_profile(id_letters="xy"))
        self.write_detail({"things": [{"id": "x1", "name": "alpha"},
                                      {"id": "y2", "name": "beta"}]})
        self.write_summary({"count": 3})

        with self.subTest("x1 and y2 are ids found in the detail file"):
            # An id is known when the summary holds it or ush:detail names it.
            code, output = self.run_report(
                ["# Test report", "<!-- ush:detail x1 y2 -->",
                 "Items x1 and y2 were seen 3 times.", *NOT_CHECKED],
                "known-ids.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("g1 is a number and 1 is not backed"):
            code, output = self.run_report(
                ["# Test report", "Item g1 was seen 3 times.", *NOT_CHECKED], "g-unbacked.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)

        with self.subTest("g1 is a number and 1 is backed by a reading"):
            self.write_summary({"count": 3, "other": 1})
            code, output = self.run_report(
                ["# Test report", "Item g1 was seen 3 times.", *NOT_CHECKED], "g-backed.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

    def test_required_lists_from_profile(self):
        self.write_profile(_profile(required_lists=["a.items"]))
        items = [{"id": "x1", "name": "alpha"}, {"id": "x2", "name": "beta"}]
        self.write_detail({"things": items})

        with self.subTest("all elements named"):
            self.write_summary({"a": {"items": items}})
            code, output = self.run_report(
                ["# Test report", "Items x1 and x2.", *NOT_CHECKED], "all-named.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("one element not named"):
            # Guard: the random temp path must not supply the asserted id.
            self.assertNotIn("x2", str(self.root), "temp path collides with test id")
            self.write_summary({"a": {"items": items}})
            code, output = self.run_report(
                ["# Test report", "Item x1.", *NOT_CHECKED], "one-missing.md")
            self.assertEqual(code, 1, output)
            self.assertIn("x2", output)
            self.assertIn("a.items", output)

        cases = {
            "list is null": {"a": {"items": None}},
            "list key absent": {"a": {}},
            "parent absent": {},
        }
        for index, (label, data) in enumerate(cases.items()):
            with self.subTest(label):
                self.write_summary(data)
                code, output = self.run_report(
                    ["# Test report", "No items.", *NOT_CHECKED], f"no-list-{index}.md")
                self.assertEqual(code, 0, f"{label}: output:\n{output}")
                self.assertIn("OK", output)

    def test_truncated_ids_from_profile(self):
        # Readings hold no 4, 5 or 6; x4..x6 can only pass as ids.
        self.write_profile(_profile(required_lists=["a.items"],
                                    truncated={"list": "a.items", "prefix": "x"}))
        items = [{"id": "x1", "name": "alpha"}, {"id": "x2", "name": "beta"},
                 {"id": "x3", "name": "gamma"}]
        self.write_detail({"things": items})
        named = "Items x1, x2 and x3."

        with self.subTest("truncated 2: x4 and x5 are known"):
            self.write_summary({"a": {"items": items}, "truncated": 2})
            code, output = self.run_report(
                ["# Test report", named, "Items x4 and x5 were cut from the summary.",
                 *NOT_CHECKED], "trunc-known.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("truncated 2: x6 is not known"):
            self.write_summary({"a": {"items": items}, "truncated": 2})
            code, output = self.run_report(
                ["# Test report", named, "Item x6 was cut from the summary.", *NOT_CHECKED],
                "trunc-x6.md")
            self.assertEqual(code, 1, output)

        with self.subTest("truncated null: x4 and x5 are not known"):
            self.write_summary({"a": {"items": items}, "truncated": None})
            code, output = self.run_report(
                ["# Test report", named, "Items x4 and x5 were cut from the summary.",
                 *NOT_CHECKED], "trunc-null.md")
            self.assertEqual(code, 1, output)

    def run_report_guarded(self, body, name):
        """Like run_report, but a crash of the checker is a result, not a test error."""
        try:
            return self.run_report(body, name)
        except (TypeError, KeyError, AttributeError, ValueError) as exc:  # a crash fails the assertion
            return None, f"checker raised {type(exc).__name__}: {exc}"

    def test_truncated_list_with_count_keys(self):
        # Readings are 2 and 1 only; x4, x5 and y3 can only pass as ids.
        items_x = [{"id": "x1", "name": "alpha"}, {"id": "x2", "name": "beta"},
                   {"id": "x3", "name": "gamma"}]
        items_y = [{"id": "y1", "name": "delta"}, {"id": "y2", "name": "epsilon"}]
        self.write_detail({"things": items_x + items_y})
        named = ["Items x1, x2 and x3.", "Items y1 and y2."]
        for token in ("x4", "x5", "y3", "y4"):
            self.assertNotIn(token, str(self.root), "temp path collides with a test id")

        self.write_profile(_profile(
            required_lists=["a.items", "b"],
            truncated=[{"list": "a.items", "prefix": "x"},
                       {"list": "b", "prefix": "y", "count_key": "truncated_b"}]))
        summary = {"a": {"items": items_x}, "b": items_y, "truncated": 2, "truncated_b": 1}

        with self.subTest("list: control with only the listed ids"):
            self.write_summary(summary)
            code, output = self.run_report_guarded(
                ["# Test report", *named, *NOT_CHECKED], "list-control.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("list: x4 and x5 are known (count from truncated)"):
            self.write_summary(summary)
            code, output = self.run_report_guarded(
                ["# Test report", *named, "Items x4 and x5 were cut from the summary.",
                 *NOT_CHECKED], "list-x45.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("list: y3 is known (count from truncated_b)"):
            self.write_summary(summary)
            code, output = self.run_report_guarded(
                ["# Test report", *named, "Item y3 was cut from the summary.", *NOT_CHECKED],
                "list-y3.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

        with self.subTest("list: y4 is not known"):
            self.write_summary(summary)
            code, output = self.run_report_guarded(
                ["# Test report", *named, "Item y4 was cut from the summary.", *NOT_CHECKED],
                "list-y4.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)

        with self.subTest("object instead of a list works as before"):
            self.write_profile(_profile(required_lists=["a.items"],
                                        truncated={"list": "a.items", "prefix": "x"}))
            self.write_summary({"a": {"items": items_x}, "truncated": 2})
            code, output = self.run_report_guarded(
                ["# Test report", named[0], "Items x4 and x5 were cut from the summary.",
                 *NOT_CHECKED], "object-x45.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)

    def test_required_keys(self):
        self.write_detail({"things": []})
        body = ["# Test report", "There were 3 readings.", *NOT_CHECKED]
        # The missing key is named by itself: no lone "c" may come from the paths.
        self.assertNotRegex(str(self.root), r"\bc\b", "temp path contains a lone c")

        self.write_profile(_profile(required_keys=["b", "c"]))

        with self.subTest("summary without c"):
            self.write_summary({"count": 3, "b": []})
            code, output = self.run_report_guarded(body, "keys-missing.md")
            self.assertEqual(code, 1, output)
            self.assertNotIn("OK", output)
            self.assertRegex(output, r"\bc\b", f"expected the key c named; output:\n{output}")

        present = {
            "c is an empty list": {"count": 3, "b": [], "c": []},
            "c is null": {"count": 3, "b": [], "c": None},
        }
        for index, (label, data) in enumerate(present.items()):
            with self.subTest(label):
                self.write_summary(data)
                code, output = self.run_report_guarded(body, f"keys-present-{index}.md")
                self.assertEqual(code, 0, f"{label}: output:\n{output}")
                self.assertIn("OK", output)

        with self.subTest("profile without required_keys requires nothing"):
            self.write_profile(_profile())
            self.write_summary({"count": 3})
            code, output = self.run_report_guarded(body, "keys-none.md")
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)


def _events_summary(detail_file, skill="ush-events"):
    return {
        "skill": skill,
        "bugcheck_code": "0x0000019c",
        "last_bugcheck_time": "2026-09-18T10:15:00+00:00",
        "event_count": 1234,
        "boot_count": 1,
        "max_per_source": 234,
        "avg_per_day": 3.5,
        "detail_file": str(detail_file),
    }


def _events_detail():
    return {
        "groups": [
            {"id": "g1", "provider": "Invented-Provider", "event_id": 41, "count": 4321},
        ],
        "noise": [],
        "boots": [],
        "anomalies": [],
    }


def _events_body():
    """A valid ush-events report after the ush:summary line."""
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


class TestLatest(CheckerTestCase):
    """Runs on the real skills directory with the ush-events profile."""

    BASE_TIME = 1790000000

    def _set_mtime(self, path, offset):
        stamp = self.BASE_TIME + offset
        os.utime(path, (stamp, stamp))

    def test_latest_uses_profile_prefix(self):
        self.detail_file.write_text(json.dumps(_events_detail()), encoding="utf-8")
        self.summary_file.write_text(
            json.dumps(_events_summary(self.detail_file)), encoding="utf-8")
        valid = _events_body()
        broken = [line for line in valid if line != "<!-- ush:not-checked -->"]

        # Name order and modification time agree: health > events-0920 > events-0901.
        old = self.write_report(broken, "events-2026-09-01-0800.md")
        good = self.write_report(valid, "events-2026-09-20-0715.md")
        other = self.reports_dir / "health-2026-09-25-0900.md"
        other.write_text("not an events report\n", encoding="utf-8")
        self._set_mtime(old, 0)
        self._set_mtime(good, 100)
        self._set_mtime(other, 200)

        with self.subTest("newest events report, health report skipped"):
            code, output = self.run_argv(
                ["--latest", "--skill", "ush-events", "--data-dir", str(self.root)])
            self.assertEqual(code, 0, output)
            self.assertIn("OK", output)
            self.assertIn("events-2026-09-20-0715.md", output)

        with self.subTest("--latest without --skill"):
            code, output = self.run_argv(["--latest", "--data-dir", str(self.root)])
            self.assertEqual(code, 2, output)
            self.assertNotIn("OK", output)

        with self.subTest("newest events report names another skill"):
            other_root = self.root / "other-data"
            other_reports = other_root / "reports"
            other_reports.mkdir(parents=True)
            health_summary = self.work_dir / "health-summary.json"
            health_summary.write_text(
                json.dumps(_events_summary(self.detail_file, skill="ush-health")),
                encoding="utf-8")
            first = self.write_report(valid, "events-2026-09-20-0715.md",
                                      reports_dir=other_reports)
            newest = self.write_report(valid, "events-2026-09-22-0700.md",
                                       summary=health_summary, reports_dir=other_reports)
            self._set_mtime(first, 0)
            self._set_mtime(newest, 100)
            code, output = self.run_argv(
                ["--latest", "--skill", "ush-events", "--data-dir", str(other_root)])
            self.assertEqual(code, 2, output)
            self.assertNotIn("OK", output)
            self.assertTrue(output.strip(), "expected a message")


class _FakeTemp:
    """A temporary directory stand-in: a fixed name and a recorded cleanup."""

    def __init__(self, name, make_dir=False):
        self.name = str(name)
        self.cleaned = False
        if make_dir:
            Path(self.name).mkdir()

    def cleanup(self):
        self.cleaned = True


class TestCleanTempDir(unittest.TestCase):
    """Tests K1-K3: the temporary root never holds an id-like part."""

    def test_colliding_name_is_drawn_again(self):
        made = [_FakeTemp(Path("C:/ush-fake/tmpx4ab12cd")),
                _FakeTemp(Path("C:/ush-fake/tmpab12cd34"))]
        queue = list(made)
        tmp = clean_temp_dir(make=lambda: queue.pop(0))
        self.assertIs(tmp, made[1])
        self.assertTrue(made[0].cleaned)
        self.assertFalse(made[1].cleaned)

    def test_all_colliding_fails_clearly(self):
        made = []

        def make():
            made.append(_FakeTemp(Path(f"C:/ush-fake/tmpy3{len(made):06d}")))
            return made[-1]

        with self.assertRaises(AssertionError) as caught:
            clean_temp_dir(make=make, attempts=5)
        self.assertEqual(len(made), 5)
        self.assertIn("tmpy3", str(caught.exception))
        self.assertTrue(all(t.cleaned for t in made))

    def test_setup_uses_clean_dir(self):
        parent = clean_temp_dir()
        self.addCleanup(parent.cleanup)
        names = ["tmpx4ab12cd", "tmpab12cd34"]

        def make():
            return _FakeTemp(Path(parent.name) / names.pop(0), make_dir=True)

        case = CheckerTestCase("setUp")
        with mock.patch.object(tempfile, "TemporaryDirectory", make):
            case.setUp()
        self.addCleanup(case.doCleanups)
        self.assertNotIn("x4", str(case.root))


if __name__ == "__main__":
    unittest.main()

"""Baseline history: skills/ush-common/scripts/baseline.py (plan 110, M1).

Public interface under test (from the plan):
- ``HISTORY_DAYS = 31``.
- ``archive(state_dir, name, now)`` copies ``<state_dir>/<name>.json`` to
  ``<state_dir>/history/<name>.<YYYY-MM-DD>.json`` (UTC day of the file's own ``created_at``)
  through ``_copy_verified``, then removes files matching
  ``^<name>\\.(\\d{4}-\\d{2}-\\d{2})\\.json$`` older than ``now`` minus ``HISTORY_DAYS`` days.
  Returns ``None`` or a reason string.
- ``load_reference(state_dir, skill, elevated, days, now)`` picks the newest history file
  ``<baseline name>.<date>.json`` with a date not later than the UTC day of ``now`` minus
  ``days``; returns the shape of ``load`` plus ``file`` (the bare file name).

Assumptions where the plan leaves the shape open:
- ``name`` passed to ``archive`` is the baseline name as passed to ``save``
  (``ush-inventory`` for a non-elevated run).
- A replaced ``_copy_verified`` is looked up as a module attribute at call time, and it
  returns a reason string on failure; its arguments are not asserted.
- An "empty history" means the ``history`` directory is absent or holds no files.
- On ``unreadable``, the result still names the selected ``file``.

Every baseline here is invented and lives in a temporary directory; nothing touches the
machine or the real data directory.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

SKILL = "ush-inventory"
NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


def temp_dir(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def day(moment):
    return moment.strftime("%Y-%m-%d")


def baseline_data(label, created_at, elevated=False):
    return {
        "schema_version": 1,
        "skill": SKILL,
        "created_at": created_at,
        "elevated": elevated,
        "sources": {"win32_programs": {
            f"win32:hklm64:App{label}": {
                "name": f"Invented App {label}",
                "version": "1.0",
                "publisher": "Invented Publisher Ltd",
            }}},
    }


def history_files(state):
    history = state / "history"
    if not history.exists():
        return []
    return sorted(p.name for p in history.iterdir())


class TestHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = load_script("ush-common", "baseline")

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_archive_one_per_day_and_prune(self):
        self.assertEqual(self.baseline.HISTORY_DAYS, 31)

        with self.subTest("two saves on one day leave one day file with the second data"):
            state = temp_dir(self)
            self.assertFalse((state / "history").exists())
            first = baseline_data("first", iso(NOW - timedelta(hours=4)))
            second = baseline_data("second", iso(NOW - timedelta(hours=2)))

            self.assertIsNone(self.baseline.save(state, SKILL, first))
            self.assertIsNone(self.baseline.archive(state, SKILL, NOW))
            self.assertIsNone(self.baseline.save(state, SKILL, second))
            self.assertIsNone(self.baseline.archive(state, SKILL, NOW))

            day_name = f"{SKILL}.{day(NOW)}.json"
            self.assertEqual(history_files(state), [day_name])
            self.assertEqual(self.read_json(state / "history" / day_name), second)

        with self.subTest("the only copy 32 days old stays as the newest old copy; "
                          "other names are kept"):
            state = temp_dir(self)
            old_now = NOW - timedelta(days=32)
            old = baseline_data("old", iso(old_now))
            self.assertIsNone(self.baseline.save(state, SKILL, old))
            self.assertIsNone(self.baseline.archive(state, SKILL, old_now))
            old_name = f"{SKILL}.{day(old_now)}.json"
            self.assertEqual(history_files(state), [old_name])

            history = state / "history"
            elevated_name = f"{SKILL}.elevated.{day(old_now)}.json"
            (history / elevated_name).write_text(
                json.dumps(baseline_data("elevated", iso(old_now), elevated=True)),
                encoding="utf-8")
            foreign_name = "user-notes.txt"
            (history / foreign_name).write_text("invented note\n", encoding="utf-8")

            current = baseline_data("current", iso(NOW - timedelta(hours=1)))
            self.assertIsNone(self.baseline.save(state, SKILL, current))
            self.assertIsNone(self.baseline.archive(state, SKILL, NOW))

            today_name = f"{SKILL}.{day(NOW)}.json"
            self.assertEqual(history_files(state),
                             sorted([old_name, today_name, elevated_name, foreign_name]))
            self.assertEqual(self.read_json(history / today_name), current)

        with self.subTest("a failed copy gives a reason and leaves <name>.json unchanged"):
            state = temp_dir(self)
            data = baseline_data("kept", iso(NOW - timedelta(hours=1)))
            self.assertIsNone(self.baseline.save(state, SKILL, data))
            current_path = state / f"{SKILL}.json"
            before = current_path.read_bytes()

            calls = []

            def failing_copy(*args, **kwargs):
                calls.append((args, kwargs))
                return "invented copy failure"

            real_copy = self.baseline._copy_verified
            self.baseline._copy_verified = failing_copy
            self.addCleanup(setattr, self.baseline, "_copy_verified", real_copy)
            try:
                reason = self.baseline.archive(state, SKILL, NOW)
            finally:
                self.baseline._copy_verified = real_copy

            self.assertTrue(calls, "the substituted _copy_verified was not used")
            self.assertIsInstance(reason, str)
            self.assertTrue(reason.strip(), "failed copy without a reason")
            self.assertEqual(current_path.read_bytes(), before, "<name>.json changed")

        with self.subTest("no <name>.json gives None and an empty history"):
            state = temp_dir(self)
            self.assertIsNone(self.baseline.archive(state, SKILL, NOW))
            self.assertEqual(history_files(state), [])

        with self.subTest("<name>.json without created_at gives a reason and an empty history"):
            state = temp_dir(self)
            data = baseline_data("no-time", iso(NOW))
            del data["created_at"]
            (state / f"{SKILL}.json").write_text(json.dumps(data), encoding="utf-8")
            reason = self.baseline.archive(state, SKILL, NOW)
            self.assertIsInstance(reason, str)
            self.assertTrue(reason.strip(), "bad baseline without a reason")
            self.assertEqual(history_files(state), [])

    def test_load_reference_picks_old_enough(self):
        state = temp_dir(self)
        history = state / "history"
        history.mkdir()

        def write(name, text):
            (history / name).write_text(text, encoding="utf-8")

        names = {}
        for ago in (1, 5, 9):
            moment = NOW - timedelta(days=ago)
            names[ago] = f"{SKILL}.{day(moment)}.json"
            write(names[ago], json.dumps(baseline_data(f"ago{ago}", iso(moment))))

        # Elevated copy 8 days old: newer than the 9-day copy, so a wrong match would win.
        elevated_moment = NOW - timedelta(days=8)
        write(f"{SKILL}.elevated.{day(elevated_moment)}.json",
              json.dumps(baseline_data("elevated", iso(elevated_moment), elevated=True)))
        # Name with an impossible date: skipped, never parsed into a crash.
        write(f"{SKILL}.2026-13-45.json",
              json.dumps(baseline_data("bad-date", iso(NOW - timedelta(days=20)))))

        def expected_sources(ago):
            return baseline_data(f"ago{ago}", "unused")["sources"]

        with self.subTest("days 7 picks the copy from 9 days ago"):
            result = self.baseline.load_reference(state, SKILL, False, 7, NOW)
            self.assertEqual(result["status"], "read")
            self.assertEqual(result["file"], names[9])
            self.assertEqual(result["sources"], expected_sources(9))

        with self.subTest("days 5 picks the copy from 5 days ago"):
            result = self.baseline.load_reference(state, SKILL, False, 5, NOW)
            self.assertEqual(result["status"], "read")
            self.assertEqual(result["file"], names[5])
            self.assertEqual(result["sources"], expected_sources(5))

        with self.subTest("days 10 finds nothing old enough"):
            result = self.baseline.load_reference(state, SKILL, False, 10, NOW)
            self.assertEqual(result["status"], "none")
            self.assertIsInstance(result["reason"], str)
            self.assertIn("no saved state at least 10 days old", result["reason"])

        with self.subTest("a selected file with invalid JSON is unreadable, not the older one"):
            write(names[5], "{\"schema_version\": 1, \"skill\": ")
            result = self.baseline.load_reference(state, SKILL, False, 5, NOW)
            self.assertEqual(result["status"], "unreadable")
            self.assertIsInstance(result["reason"], str)
            self.assertTrue(result["reason"].strip(), "unreadable without a reason")
            self.assertEqual(result["file"], names[5])


    # --- review notes (M1 code-review) ---------------------------------------------

    def write_state(self, state, data):
        state.mkdir(parents=True, exist_ok=True)
        (state / f"{SKILL}.json").write_text(json.dumps(data), encoding="utf-8")

    def test_archive_skips_a_file_load_would_reject(self):
        state = temp_dir(self)
        for bad in ({**baseline_data("A", iso(NOW)), "schema_version": 99},
                    {**baseline_data("A", iso(NOW)), "skill": "ush-settings"},
                    baseline_data("A", iso(NOW), elevated=True)):
            with self.subTest(bad=bad):
                self.write_state(state, bad)
                self.assertTrue(self.baseline.archive(state, SKILL, NOW))
                self.assertEqual(history_files(state), [])

    def test_archive_keeps_its_own_old_copy(self):
        state = temp_dir(self)
        old = NOW - timedelta(days=40)
        self.write_state(state, baseline_data("A", iso(old)))
        self.assertIsNone(self.baseline.archive(state, SKILL, NOW))
        self.assertEqual(history_files(state), [f"{SKILL}.{day(old)}.json"])

    def test_load_reference_days_out_of_range(self):
        state = temp_dir(self)
        for days in (0, -1, 31, True, 1.5):
            with self.subTest(days=days), self.assertRaises(ValueError):
                self.baseline.load_reference(state, SKILL, False, days, NOW)
        self.assertEqual(self.baseline.load_reference(state, SKILL, False, 30, NOW)["status"],
                         "none")


    def test_failed_cleanup_is_not_history_not_kept(self):
        state = temp_dir(self)
        old = NOW - timedelta(days=45)
        newest_old = NOW - timedelta(days=40)
        history = state / "history"
        history.mkdir(parents=True)
        (history / f"{SKILL}.{day(old)}.json").write_text(
            json.dumps(baseline_data("A", iso(old))), encoding="utf-8")
        (history / f"{SKILL}.{day(newest_old)}.json").write_text(
            json.dumps(baseline_data("C", iso(newest_old))), encoding="utf-8")
        self.write_state(state, baseline_data("B", iso(NOW)))
        real_unlink = Path.unlink

        def locked(path, *args, **kwargs):
            if path.name == f"{SKILL}.{day(old)}.json":
                raise PermissionError("invented lock")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", locked):
            reason = self.baseline.archive(state, SKILL, NOW)
        self.assertTrue(reason)
        self.assertIn(f"{SKILL}.{day(NOW)}.json", history_files(state))
        self.assertIn(f"{SKILL}.{day(newest_old)}.json", history_files(state))
        note = self.baseline.history_note(reason)
        self.assertNotIn("history not kept", note)
        self.assertIn("day copy was kept", note)
        self.assertEqual(self.baseline.history_note("copy failed"),
                         "history not kept: copy failed")


class TestNewestOldCopy(unittest.TestCase):
    """Pruning keeps the newest copy older than HISTORY_DAYS, per baseline name."""

    @classmethod
    def setUpClass(cls):
        cls.baseline = load_script("ush-common", "baseline")

    def write_history(self, state, name, data):
        history = state / "history"
        history.mkdir(parents=True, exist_ok=True)
        (history / name).write_text(json.dumps(data), encoding="utf-8")

    def write_state(self, state, data):
        state.mkdir(parents=True, exist_ok=True)
        (state / f"{SKILL}.json").write_text(json.dumps(data), encoding="utf-8")

    def test_gap_keeps_newest_old_copy(self):
        state = temp_dir(self)
        moment40 = NOW - timedelta(days=40)
        moment35 = NOW - timedelta(days=35)
        name40 = f"{SKILL}.{day(moment40)}.json"
        name35 = f"{SKILL}.{day(moment35)}.json"
        self.write_history(state, name40, baseline_data("ago40", iso(moment40)))
        self.write_history(state, name35, baseline_data("ago35", iso(moment35)))
        self.write_state(state, baseline_data("today", iso(NOW - timedelta(hours=1))))

        self.baseline.archive(state, SKILL, NOW)

        today_name = f"{SKILL}.{day(NOW)}.json"
        self.assertEqual(history_files(state), sorted([name35, today_name]))

        expected_sources = baseline_data("ago35", "unused")["sources"]
        for days in (7, 30):
            with self.subTest(days=days):
                result = self.baseline.load_reference(state, SKILL, False, days, NOW)
                self.assertEqual(result["status"], "read")
                self.assertEqual(result["file"], name35)
                self.assertEqual(result["sources"], expected_sources)

    def test_newest_old_copy_per_name(self):
        state = temp_dir(self)
        moment40 = NOW - timedelta(days=40)
        moment33 = NOW - timedelta(days=33)
        moment35 = NOW - timedelta(days=35)
        name40 = f"{SKILL}.{day(moment40)}.json"
        name33 = f"{SKILL}.{day(moment33)}.json"
        elevated_name = f"{SKILL}.elevated.{day(moment35)}.json"
        self.write_history(state, name40, baseline_data("ago40", iso(moment40)))
        self.write_history(state, name33, baseline_data("ago33", iso(moment33)))
        self.write_history(state, elevated_name,
                           baseline_data("elevated35", iso(moment35), elevated=True))
        elevated_path = state / "history" / elevated_name
        elevated_before = elevated_path.read_bytes()
        self.write_state(state, baseline_data("today", iso(NOW - timedelta(hours=1))))

        self.baseline.archive(state, SKILL, NOW)

        today_name = f"{SKILL}.{day(NOW)}.json"
        files = history_files(state)
        self.assertIn(name33, files, "the newest old plain copy was removed")
        self.assertNotIn(name40, files, "the older plain copy was kept")
        self.assertIn(elevated_name, files, "the elevated copy was removed")
        self.assertEqual(elevated_path.read_bytes(), elevated_before,
                         "the elevated copy was changed")
        self.assertEqual(files, sorted([name33, elevated_name, today_name]))

    def test_contract_names_newest_old_copy(self):
        root = Path(__file__).resolve().parents[2]
        contract = root / "skills" / "ush-common" / "references" / "summary-contract.md"
        text = contract.read_text(encoding="utf-8")

        lines = text.splitlines()
        start = next((i for i, line in enumerate(lines) if line.strip() == "## Baseline"),
                     None)
        self.assertIsNotNone(start, "no '## Baseline' section in the shared contract")
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        section = " ".join(" ".join(lines[start:end]).split())

        self.assertIn("History:", section, "the Baseline section does not describe history")
        history_part = section[section.index("History:"):]
        self.assertIn("except the newest of them", history_part)


if __name__ == "__main__":
    unittest.main()

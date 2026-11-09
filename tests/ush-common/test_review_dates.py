"""Review dates: the loader of skills/ush-common/scripts/review_dates.py (plan 063, M1,
criterion K1).

Interface under test (from the plan):

- ``load(data_dir) -> {status, reason, path, entries}`` as ``accepted.load``: ``status`` is
  ``none`` (no file), ``read`` or ``unreadable``; ``path`` is
  ``<data_dir>/state/review-dates.json`` as a string; it never raises on a bad file.
- An entry is ``{kind, key, name, decided_on, period, review_on}``: ``kind`` ``program`` or
  ``package``, ``name`` a string or ``null``, ``period`` ``<N>d``, ``<N>m``, ``<N>y`` or
  ``none``, ``decided_on`` and ``review_on`` local dates (``review_on`` ``null`` for
  ``none``).

Assumptions added by these tests beyond the plan text:

- The file holds ``{"schema_version": 1, "entries": [...]}`` (as ``accepted.json``); the
  writer of M2 does not exist yet, so the valid file is written by hand.
- Dates are ISO ``YYYY-MM-DD`` strings.
- An unreadable file gives no entries (an empty list or ``None``) and a non-empty
  ``reason``; a missing file gives ``entries`` ``[]`` and ``reason`` ``None``.

The writer (plan 063, M2, criteria K1, K3, K4):

- ``review_dates.py --set r<n>[,r<n>...] --period <N>d|<N>m|<N>y|none --detail-file
  <runall detail> --data-dir <dir>`` reads only the runall detail file's ``review``
  section, accepts items in state ``no_decision``, ``due``, ``not_due`` or ``no_limit``,
  stores ``{kind, key, name, decided_on, period, review_on}`` (``decided_on`` the local
  date, ``review_on`` ``null`` for ``none``), never the ``r`` id, replaces an entry with
  the same kind and key, and prints ``{ok: true, keys, path}``; a refusal prints ``ok``
  ``false`` with a ``reason``, exits 1 and writes nothing (all or nothing).

Assumptions added by the writer tests beyond the plan text:

- A ``review`` item in the runall detail file is ``{id, kind, key, name, state}`` (a
  ``not_checked`` item also has a ``reason``); the rest of the invented runall detail
  file is a minimal shell.
- ``keys`` is the list of the keys written (order not pinned); ``path`` is
  ``<data_dir>/state/review-dates.json`` as a string; a success exits 0.
- The script runs as a child process with the real clock: "today" is the local date
  before or after the run (a run across midnight is allowed).

Every value is invented (Contoso, Fabrikam); nothing on the machine is read.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script, script_path

REVIEW_DATES_SCRIPT = script_path("ush-common", "review_dates")

VALID = {
    "schema_version": 1,
    "entries": [
        {"kind": "program", "key": "win32:hklm64:ContosoTray", "name": "Contoso Tray",
         "decided_on": "2026-11-02", "period": "1y", "review_on": "2027-11-02"},
        {"kind": "package", "key": "pip:PythonCore/3.12|install|contoso-http", "name": None,
         "decided_on": "2026-11-02", "period": "none", "review_on": None},
        {"kind": "program", "key": "msix:Fabrikam.Notes_0abc1def2ghj3",
         "name": "Fabrikam Notes", "decided_on": "2026-10-15", "period": "30d",
         "review_on": "2026-11-14"},
        {"kind": "package", "key": "npm:@contoso/tool", "name": "@contoso/tool",
         "decided_on": "2026-08-31", "period": "6m", "review_on": "2027-02-28"},
    ],
}


class ReviewDatesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review_dates = load_script("ush-common", "review_dates")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    @staticmethod
    def file_path(data_dir):
        return data_dir / "state" / "review-dates.json"

    def write(self, data_dir, data):
        path = self.file_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data, indent=2)
        path.write_text(text, encoding="utf-8")
        return path


class TestLoad(ReviewDatesTestCase):
    def assert_unreadable(self, data):
        data_dir = self.data_dir()
        self.write(data_dir, data)
        result = self.review_dates.load(data_dir)
        self.assertIsInstance(result, dict, result)
        self.assertEqual(result.get("status"), "unreadable", result)
        self.assertEqual(result.get("path"), str(self.file_path(data_dir)), result)
        self.assertFalse(result.get("entries"), result)
        reason = result.get("reason")
        self.assertIsInstance(reason, str, result)
        self.assertTrue(reason.strip(), result)

    def changed(self, index, **fields):
        data = copy.deepcopy(VALID)
        data["entries"][index].update(fields)
        return data

    def test_load_states(self):
        with self.subTest(case="missing file"):
            data_dir = self.data_dir()
            result = self.review_dates.load(data_dir)
            self.assertIsInstance(result, dict, result)
            self.assertEqual(result.get("status"), "none", result)
            self.assertEqual(result.get("entries"), [], result)
            self.assertIsNone(result.get("reason"), result)
            path = result.get("path")
            self.assertEqual(path, str(self.file_path(data_dir)), result)
            self.assertTrue(Path(path).is_absolute(), path)
            self.assertFalse(self.file_path(data_dir).exists())

        with self.subTest(case="valid file"):
            data_dir = self.data_dir()
            path = self.write(data_dir, VALID)
            result = self.review_dates.load(data_dir)
            self.assertEqual(result.get("status"), "read", result)
            self.assertIsNone(result.get("reason"), result)
            self.assertEqual(result.get("path"), str(path), result)
            entries = result.get("entries")
            self.assertIsInstance(entries, list, result)
            self.assertEqual(len(entries), len(VALID["entries"]), result)
            by_key = {(entry.get("kind"), entry.get("key")): entry for entry in entries}
            for written in VALID["entries"]:
                loaded = by_key.get((written["kind"], written["key"]))
                self.assertIsNotNone(loaded, (written, entries))
                for field in ("name", "decided_on", "period", "review_on"):
                    self.assertEqual(loaded.get(field), written[field], (field, loaded))
            # A pip package whose metadata was not read keeps a null name.
            self.assertIsNone(
                by_key[("package", "pip:PythonCore/3.12|install|contoso-http")].get("name"))

        bad = {
            "bad JSON": '{"schema_version": 1, "entries": [{"kind": "program"',
            "wrong schema version": dict(copy.deepcopy(VALID), schema_version=999),
            "bad period": self.changed(0, period="2w"),
            "bad review_on date": self.changed(0, review_on="2027-02-30"),
            "bad decided_on date": self.changed(2, decided_on="mid-October"),
            "name a number": self.changed(0, name=42),
            "name a list": self.changed(2, name=["Fabrikam Notes"]),
        }
        duplicate = copy.deepcopy(VALID)
        duplicate["entries"].append(
            {"kind": "program", "key": "win32:hklm64:ContosoTray", "name": "Contoso Tray 2",
             "decided_on": "2026-11-05", "period": "6m", "review_on": "2027-05-05"})
        bad["two entries with the same kind and key"] = duplicate

        for case, data in bad.items():
            with self.subTest(case=case):
                self.assert_unreadable(data)


# --- the writer ------------------------------------------------------------------------------

TRAY_KEY = "win32:hklm64:ContosoTray"
NOTES_KEY = "msix:Fabrikam.Notes_0abc1def2ghj3"
HTTP_KEY = "pip:PythonCore/3.12|install|contoso-http"
TOOL_KEY = "npm:@contoso/tool"
GONE_KEY = "win32:hklm64:FabrikamRemoved"
UNREAD_KEY = "npm:@fabrikam/cli"

REVIEW_ITEMS = [
    {"id": "r1", "kind": "program", "key": TRAY_KEY, "name": "Contoso Tray",
     "state": "no_decision"},
    {"id": "r2", "kind": "program", "key": NOTES_KEY, "name": "Fabrikam Notes",
     "state": "not_due"},
    # A pip package whose metadata was not read: its name is null.
    {"id": "r3", "kind": "package", "key": HTTP_KEY, "name": None, "state": "due"},
    {"id": "r4", "kind": "package", "key": TOOL_KEY, "name": "@contoso/tool",
     "state": "no_limit"},
    {"id": "r5", "kind": "program", "key": GONE_KEY, "name": "Fabrikam Removed",
     "state": "gone"},
    {"id": "r6", "kind": "package", "key": UNREAD_KEY, "name": "@fabrikam/cli",
     "state": "not_checked",
     "reason": "Invented: npm_packages was not read in this pass."},
]


def local_today():
    return datetime.now().astimezone().date()


def add_years(day, years):
    """``day`` plus calendar years; Feb 29 clamps to Feb 28."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def runall_detail(data_dir, review=None):
    """Write an invented runall detail file holding ``review``; return its path."""
    path = data_dir / "work" / "runall-20261109-101500.detail.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {"schema_version": 1, "skill": "ush-runall",
               "generated_at": "2026-11-09T10:15:00Z", "children": [],
               "not_checked": [],
               "review": copy.deepcopy(REVIEW_ITEMS if review is None else review)}
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return path


class TestSet(ReviewDatesTestCase):
    def run_set(self, data_dir, ids, period, detail_file):
        """Run ``--set``; return (exit code, parsed stdout)."""
        env = dict(os.environ)
        env.pop("USH_DATA_DIR", None)
        env["PYTHONIOENCODING"] = "utf-8"
        done = subprocess.run(
            [sys.executable, "-B", str(REVIEW_DATES_SCRIPT), "--set", ids,
             "--period", period, "--detail-file", str(detail_file),
             "--data-dir", str(data_dir)],
            capture_output=True, text=True, check=False, encoding="utf-8", env=env,
            timeout=120)
        try:
            result = json.loads(done.stdout)
        except ValueError:
            self.fail(f"stdout is not JSON: {done.stdout!r}; stderr: {done.stderr!r}")
        self.assertIsInstance(result, dict, done.stdout)
        return done.returncode, result

    def set_ok(self, data_dir, ids, period, detail_file):
        before = local_today()
        code, result = self.run_set(data_dir, ids, period, detail_file)
        after = local_today()
        self.assertEqual(code, 0, result)
        self.assertIs(result.get("ok"), True, result)
        self.assertEqual(result.get("path"), str(self.file_path(data_dir)), result)
        return result, {before, after}

    def entries_by_key(self, data_dir):
        loaded = self.review_dates.load(data_dir)
        self.assertEqual(loaded.get("status"), "read", loaded)
        entries = loaded.get("entries")
        self.assertIsInstance(entries, list, loaded)
        by_key = {}
        for item in entries:
            self.assertNotIn((item.get("kind"), item.get("key")), by_key, entries)
            by_key[(item.get("kind"), item.get("key"))] = item
        return by_key

    def raw_entries(self, data_dir):
        data = json.loads(self.file_path(data_dir).read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict, data)
        self.assertIsInstance(data.get("entries"), list, data)
        return data["entries"]

    def test_entries(self):
        with self.subTest(case="r1,r3 for one year"):
            data_dir = self.data_dir()
            result, today = self.set_ok(data_dir, "r1,r3", "1y", runall_detail(data_dir))
            keys = result.get("keys")
            self.assertIsInstance(keys, list, result)
            self.assertEqual(sorted(keys), sorted([TRAY_KEY, HTTP_KEY]), result)

            by_key = self.entries_by_key(data_dir)
            self.assertEqual(set(by_key), {("program", TRAY_KEY), ("package", HTTP_KEY)},
                             by_key)
            for (kind, key), name in ((("program", TRAY_KEY), "Contoso Tray"),
                                      (("package", HTTP_KEY), None)):
                written = by_key[(kind, key)]
                self.assertEqual(written.get("name"), name, written)
                self.assertEqual(written.get("period"), "1y", written)
                decided_on = date.fromisoformat(written.get("decided_on"))
                self.assertIn(decided_on, today, written)
                self.assertEqual(written.get("review_on"),
                                 add_years(decided_on, 1).isoformat(), written)
            # Exactly the plan's fields (the r id is never stored); a null name stays null.
            for raw in self.raw_entries(data_dir):
                self.assertEqual(set(raw), {"kind", "key", "name", "decided_on", "period",
                                            "review_on"}, raw)
                self.assertNotIn(raw.get("id"), ("r1", "r3"), raw)
                if raw.get("key") == HTTP_KEY:
                    self.assertIn("name", raw, raw)
                    self.assertIsNone(raw["name"], raw)

        with self.subTest(case="period none"):
            data_dir = self.data_dir()
            result, today = self.set_ok(data_dir, "r2", "none", runall_detail(data_dir))
            self.assertEqual(result.get("keys"), [NOTES_KEY], result)
            by_key = self.entries_by_key(data_dir)
            self.assertEqual(set(by_key), {("program", NOTES_KEY)}, by_key)
            written = by_key[("program", NOTES_KEY)]
            self.assertEqual(written.get("name"), "Fabrikam Notes", written)
            self.assertEqual(written.get("period"), "none", written)
            self.assertIn(date.fromisoformat(written.get("decided_on")), today, written)
            self.assertIn("review_on", written, written)
            self.assertIsNone(written["review_on"], written)

    def test_replace(self):
        data_dir = self.data_dir()
        # An earlier decision on the same key, and one on another key that stays.
        self.write(data_dir, {
            "schema_version": 1,
            "entries": [
                {"kind": "program", "key": TRAY_KEY, "name": "Contoso Tray",
                 "decided_on": "2025-01-10", "period": "6m", "review_on": "2025-07-10"},
                {"kind": "package", "key": TOOL_KEY, "name": "@contoso/tool",
                 "decided_on": "2026-02-01", "period": "none", "review_on": None},
            ],
        })
        detail = runall_detail(data_dir)

        result, today = self.set_ok(data_dir, "r1", "30d", detail)
        self.assertEqual(result.get("keys"), [TRAY_KEY], result)
        by_key = self.entries_by_key(data_dir)
        self.assertEqual(set(by_key), {("program", TRAY_KEY), ("package", TOOL_KEY)},
                         by_key)
        replaced = by_key[("program", TRAY_KEY)]
        self.assertEqual(replaced.get("period"), "30d", replaced)
        decided_on = date.fromisoformat(replaced.get("decided_on"))
        self.assertIn(decided_on, today, replaced)
        self.assertEqual(replaced.get("review_on"),
                         (decided_on + timedelta(days=30)).isoformat(), replaced)
        kept = by_key[("package", TOOL_KEY)]
        self.assertEqual(kept.get("decided_on"), "2026-02-01", kept)
        self.assertEqual(kept.get("period"), "none", kept)

        # Decided again through --set: still one entry for the key, with the new period.
        self.set_ok(data_dir, "r1", "1y", detail)
        tray_entries = [raw for raw in self.raw_entries(data_dir)
                        if raw.get("kind") == "program" and raw.get("key") == TRAY_KEY]
        self.assertEqual(len(tray_entries), 1, tray_entries)
        again = tray_entries[0]
        self.assertEqual(again.get("period"), "1y", again)
        self.assertEqual(again.get("review_on"),
                         add_years(date.fromisoformat(again.get("decided_on")), 1).isoformat(),
                         again)
        self.assertEqual(len(self.raw_entries(data_dir)), 2, self.raw_entries(data_dir))

    def assert_refused(self, data_dir, ids, period, detail_file, before):
        code, result = self.run_set(data_dir, ids, period, detail_file)
        self.assertEqual(code, 1, result)
        self.assertIs(result.get("ok"), False, result)
        reason = result.get("reason")
        self.assertIsInstance(reason, str, result)
        self.assertTrue(reason.strip(), result)
        path = self.file_path(data_dir)
        if before is None:
            self.assertFalse(path.exists(), path)
        else:
            self.assertEqual(path.read_bytes(), before, path)

    def test_refused(self):
        def good(data_dir):
            return runall_detail(data_dir)

        def missing_detail(data_dir):
            runall_detail(data_dir)
            return data_dir / "work" / "runall-20261109-999999.detail.json"

        def detail_not_json(data_dir):
            path = runall_detail(data_dir)
            path.write_text('{"schema_version": 1, "review": [{"id": "r1"', encoding="utf-8")
            return path

        cases = {
            "unknown id": ("r9", "1y", good),
            "item in state gone": ("r5", "1y", good),
            "item in state not_checked": ("r6", "1y", good),
            "bad period (weeks)": ("r1", "2w", good),
            "bad period (no number)": ("r1", "y", good),
            "period past year 9999 (years)": ("r1", "10000y", good),
            "period past year 9999 (days)": ("r1", "99999999999d", good),
            "missing detail file": ("r1", "1y", missing_detail),
            "detail file not JSON": ("r1", "1y", detail_not_json),
            "one unknown id of several": ("r1,r9", "6m", good),
            "one gone item of several": ("r1,r3,r5", "6m", good),
            "one not_checked item of several": ("r6,r2", "none", good),
        }
        for case, (ids, period, build) in cases.items():
            with self.subTest(case=case, review_dates="absent"):
                data_dir = self.data_dir()
                self.assert_refused(data_dir, ids, period, build(data_dir), None)

            with self.subTest(case=case, review_dates="earlier entries"):
                data_dir = self.data_dir()
                path = self.write(data_dir, VALID)
                before = path.read_bytes()
                self.assert_refused(data_dir, ids, period, build(data_dir), before)

        with self.subTest(case="existing review-dates.json with bad JSON"):
            data_dir = self.data_dir()
            path = self.file_path(data_dir)
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"schema_version": 1, "entries": [{"kind": "program"')
            before = path.read_bytes()
            self.assert_refused(data_dir, "r1", "1y", runall_detail(data_dir), before)

        with self.subTest(case="existing review-dates.json with a wrong schema version"):
            data_dir = self.data_dir()
            path = self.write(data_dir, dict(copy.deepcopy(VALID), schema_version=999))
            before = path.read_bytes()
            self.assert_refused(data_dir, "r1", "1y", runall_detail(data_dir), before)

class TestSavedButPrevious(ReviewDatesTestCase):
    def test_saved_with_warning(self):
        data_dir = Path(self.data_dir())
        detail = runall_detail(data_dir)
        warning = ("the new review-dates.json is saved, but review-dates.previous.json "
                   "could not be replaced: locked")
        with mock.patch.object(self.review_dates.baseline, "save_json",
                               return_value=warning):
            result = self.review_dates.set_dates("r1", "1y", detail, data_dir)
        self.assertIs(result["ok"], True, result)
        self.assertTrue(result["keys"], result)
        self.assertEqual(result["warning"], warning)

    def test_failed_save_is_refused(self):
        data_dir = Path(self.data_dir())
        detail = runall_detail(data_dir)
        with mock.patch.object(self.review_dates.baseline, "save_json",
                               return_value="cannot write review-dates.json.tmp: denied"):
            result = self.review_dates.set_dates("r1", "1y", detail, data_dir)
        self.assertIs(result["ok"], False, result)
        self.assertEqual(result["keys"], [], result)
        self.assertIn("not saved", result["reason"])


class TestPeriod(ReviewDatesTestCase):
    """Plan 063, M2, K2: ``review_on(decided_on, period)`` adds the period."""

    def check(self, start, period, wanted):
        with self.subTest(start=start, period=period):
            self.assertEqual(self.review_dates.review_on(start, period), wanted)

    def test_days(self):
        self.check(date(2026, 11, 9), "30d", date(2026, 12, 9))
        self.check(date(2026, 12, 31), "1d", date(2027, 1, 1))

    def test_months_and_years(self):
        self.check(date(2026, 11, 9), "6m", date(2027, 5, 9))
        self.check(date(2026, 11, 9), "1y", date(2027, 11, 9))
        self.check(date(2026, 11, 9), "14m", date(2028, 1, 9))

    def test_month_end_clamps(self):
        self.check(date(2027, 1, 31), "1m", date(2027, 2, 28))
        self.check(date(2028, 1, 31), "1m", date(2028, 2, 29))
        self.check(date(2028, 2, 29), "1y", date(2029, 2, 28))
        self.check(date(2026, 8, 31), "1m", date(2026, 9, 30))

    def test_none(self):
        self.assertIsNone(self.review_dates.review_on(date(2026, 11, 9), "none"))


if __name__ == "__main__":
    unittest.main()

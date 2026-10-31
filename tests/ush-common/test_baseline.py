"""The shared baseline: skills/ush-common/scripts/baseline.py (plan 048, M1).

Public interface under test (from the plan):
- ``load(state_dir, skill, elevated) -> {status, reason, created_at, sources}``; reads
  ``<skill>.json`` (or ``<skill>.elevated.json``); ``status`` is ``none``, ``read`` or
  ``unreadable``.
- ``compare(previous, current, fields)`` for one source (dicts ``key -> item``).
- ``merge_sources(previous, current, statuses)`` and
  ``comparison_state(previous, name, status)``.
- ``save(state_dir, name, data)``: temp file, verification read, one ``previous``
  generation, ``os.replace``; an unreadable current baseline is first moved to
  ``<name>.unreadable-<UTC stamp>.json``.
- ``age_days(created_at, now)``: days with one decimal place.

Assumptions where the plan leaves the shape open:
- ``save(state_dir, name, data, read_back=None)``: ``read_back`` is an optional callable
  ``(path) -> str`` used for the verification read instead of reading the file. ``save``
  returns ``None`` on success and a non-empty string reason on failure. The baseline file is
  ``<state_dir>/<name>.json`` and verification compares the parsed JSON with ``data``.
- ``compare`` returns a dict with keys ``added``, ``removed`` (sorted lists of keys) and
  ``changed`` (dict ``key -> {field: {"before": x, "after": y}}``).
- ``merge_sources`` and ``comparison_state`` take ``previous``/``current`` as source maps
  ``{source name: {key: item}}`` (the ``sources`` of a baseline) and ``statuses`` as
  ``{source name: status}``; ``merge_sources`` returns the new source map.
- ``age_days`` takes ``created_at`` as the ISO string stored in the baseline and ``now`` as a
  timezone-aware ``datetime``.

Every baseline here is invented and lives in a temporary directory; nothing touches the
machine or the real data directory.
"""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

SKILL = "ush-inventory"
FIELDS = ["name", "version", "publisher"]


def temp_dir(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


def baseline_data(sources, created_at="2026-09-01T00:00:00Z", **overrides):
    data = {
        "schema_version": 1,
        "skill": SKILL,
        "created_at": created_at,
        "elevated": False,
        "sources": sources,
    }
    data.update(overrides)
    return data


def item(name, version, publisher="Invented Publisher Ltd", **extra):
    result = {"name": name, "version": version, "publisher": publisher}
    result.update(extra)
    return result


class BaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = load_script("ush-common", "baseline")

    def setUp(self):
        self.state = temp_dir(self)

    def write(self, name, text):
        path = self.state / name
        path.write_text(text, encoding="utf-8")
        return path


class TestLoad(BaselineTest):
    def test_missing_and_bad_files(self):
        with self.subTest("no file gives status none"):
            result = self.baseline.load(self.state, SKILL, False)
            self.assertEqual(result["status"], "none")

        path = self.state / f"{SKILL}.json"
        bad_cases = {
            "invalid JSON": "{\"schema_version\": 1, \"skill\": ",
            "other schema_version": json.dumps(baseline_data({}, schema_version=2)),
        }
        for label, text in bad_cases.items():
            with self.subTest(label):
                path.write_text(text, encoding="utf-8")
                before = path.read_bytes()
                result = self.baseline.load(self.state, SKILL, False)
                self.assertEqual(result["status"], "unreadable")
                self.assertIsInstance(result["reason"], str)
                self.assertTrue(result["reason"].strip(), "unreadable without a reason")
                self.assertEqual(path.read_bytes(), before, "load changed the unreadable file")

        with self.subTest("control: a valid file is read, not flagged"):
            sources = {"win32_programs": {"win32:hklm64:InventedApp": item("Invented App", "1.0")}}
            path.write_text(json.dumps(baseline_data(sources)), encoding="utf-8")
            result = self.baseline.load(self.state, SKILL, False)
            self.assertEqual(result["status"], "read")
            self.assertEqual(result["sources"], sources)

    def test_malformed_items(self):
        """An item that compare cannot use makes the baseline unreadable, not a crash later."""
        path = self.state / f"{SKILL}.json"
        cases = {
            "item is null": {"win32_programs": {"win32:hklm64:A": None}},
            "item is a string": {"win32_programs": {"win32:hklm64:A": "x"}},
            "unread_fields is a string": {
                "win32_programs": {"win32:hklm64:A": item("A", None, unread_fields="version")}},
        }
        for label, sources in cases.items():
            with self.subTest(label):
                path.write_text(json.dumps(baseline_data(sources)), encoding="utf-8")
                result = self.baseline.load(self.state, SKILL, False)
                self.assertEqual(result["status"], "unreadable")
                self.assertTrue(result["reason"].strip())

        with self.subTest("control: unread_fields as a list of names is read"):
            sources = {"win32_programs": {
                "win32:hklm64:A": item("A", None, unread_fields=["version"])}}
            path.write_text(json.dumps(baseline_data(sources)), encoding="utf-8")
            self.assertEqual(self.baseline.load(self.state, SKILL, False)["status"], "read")


class TestCompare(BaselineTest):
    def test_three_kinds_and_clean(self):
        previous = {
            "k-same": item("Same App", "1.0", install_date="2026-01-01"),
            "k-gone": item("Gone App", "2.0"),
            "k-changed": item("Changed App", "1.0", install_date="2026-02-01"),
            "k-unread": item("Unread App", None, unread_fields=["version"]),
        }
        current = {
            # Only a field outside FIELDS differs: not a change.
            "k-same": item("Same App", "1.0", install_date="2026-03-03"),
            # version differs (in FIELDS), install_date differs too (outside FIELDS).
            "k-changed": item("Changed App", "1.1", install_date="2026-09-09"),
            # null -> value in a field the previous item lists in unread_fields.
            "k-unread": item("Unread App", "3.0"),
            "k-new": item("New App", "0.1"),
        }

        result = self.baseline.compare(previous, current, FIELDS)
        self.assertEqual(result["added"], ["k-new"])
        self.assertEqual(result["removed"], ["k-gone"])
        self.assertEqual(result["changed"],
                         {"k-changed": {"version": {"before": "1.0", "after": "1.1"}}})

        with self.subTest("identical dicts give no changes"):
            clean = self.baseline.compare(previous, copy.deepcopy(previous), FIELDS)
            self.assertEqual(clean["added"], [])
            self.assertEqual(clean["removed"], [])
            self.assertEqual(clean["changed"], {})


class TestMerge(BaselineTest):
    def test_unread_source_keeps_previous(self):
        previous = {
            "src_unread": {"u1": item("Kept App", "1.0"), "u2": item("Kept Tool", "2.0")},
            "src_read": {"r-old": item("Old App", "1.0")},
            "src_empty": {"e-old": item("Removed App", "1.0")},
        }
        current = {
            "src_unread": {},
            "src_read": {"r-new": item("New App", "1.0")},
            "src_empty": {},
            "src_added": {"a1": item("Added Source App", "1.0")},
        }
        statuses = {
            "src_unread": "unreadable",
            "src_read": "read",
            "src_empty": "empty",
            "src_added": "read",
        }

        merged = self.baseline.merge_sources(copy.deepcopy(previous), copy.deepcopy(current),
                                             statuses)
        with self.subTest("unreadable source keeps the previous items"):
            self.assertEqual(merged["src_unread"], previous["src_unread"])
        with self.subTest("read source takes the current items"):
            self.assertEqual(merged["src_read"], current["src_read"])
        with self.subTest("empty source is saved as an empty dict"):
            self.assertEqual(merged["src_empty"], {})

        with self.subTest("a previous source this run does not name is kept"):
            only_previous = {"src_skipped": {"s1": item("Skipped App", "1.0")}}
            kept = self.baseline.merge_sources(copy.deepcopy(only_previous), {}, {})
            self.assertEqual(kept, only_previous)

        with self.subTest("source absent from an existing baseline gives no_baseline"):
            self.assertEqual(
                self.baseline.comparison_state(previous, "src_added", "read"), "no_baseline")
        with self.subTest("unreadable source gives not_read"):
            self.assertEqual(
                self.baseline.comparison_state(previous, "src_unread", "unreadable"), "not_read")


class TestSave(BaselineTest):
    def generation(self, label):
        return baseline_data({"win32_programs": {f"k-{label}": item(f"App {label}", "1.0")}},
                             created_at=f"2026-09-0{label}T00:00:00Z")

    def read_json(self, name):
        return json.loads((self.state / name).read_text(encoding="utf-8"))

    def test_previous_generation(self):
        first, second, third = self.generation("1"), self.generation("2"), self.generation("3")
        current_name, previous_name = f"{SKILL}.json", f"{SKILL}.previous.json"

        self.assertIsNone(self.baseline.save(self.state, SKILL, first))
        self.assertEqual(self.read_json(current_name), first)

        self.assertIsNone(self.baseline.save(self.state, SKILL, second))
        with self.subTest("second save moves the first to previous"):
            self.assertEqual(self.read_json(current_name), second)
            self.assertEqual(self.read_json(previous_name), first)

        self.assertIsNone(self.baseline.save(self.state, SKILL, third))
        with self.subTest("third save overwrites previous with the second"):
            self.assertEqual(self.read_json(current_name), third)
            self.assertEqual(self.read_json(previous_name), second)

    def test_failed_verification_keeps_old(self):
        old, new = self.generation("1"), self.generation("2")
        self.assertIsNone(self.baseline.save(self.state, SKILL, old))
        current = self.state / f"{SKILL}.json"
        before = current.read_bytes()

        calls = []

        def wrong_read_back(path):
            calls.append(path)
            return json.dumps(self.generation("9"))

        reason = self.baseline.save(self.state, SKILL, new, read_back=wrong_read_back)
        self.assertTrue(calls, "the substituted verification read was not used")
        self.assertIsInstance(reason, str)
        self.assertTrue(reason.strip(), "failed verification without a reason")
        self.assertEqual(current.read_bytes(), before, "old baseline changed")
        self.assertFalse((self.state / f"{SKILL}.previous.json").exists(),
                         "previous created after a failed verification")

    def test_invalid_data_not_saved(self):
        """save refuses data that load would reject, so no run writes an unreadable baseline."""
        cases = {
            "time without a zone": (SKILL, self.generation("1") | {"created_at": "2026-09-01T00:00:00"}),
            "elevated is null": (SKILL, self.generation("1") | {"elevated": None}),
            "name of another privilege level": (f"{SKILL}.elevated", self.generation("1")),
        }
        for label, (name, data) in cases.items():
            with self.subTest(label):
                reason = self.baseline.save(self.state, name, data)
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip())
                self.assertEqual(list(self.state.iterdir()), [], "a file was written")

        with self.subTest("control: a valid baseline is saved and loads back"):
            self.assertIsNone(self.baseline.save(self.state, SKILL, self.generation("1")))
            self.assertEqual(self.baseline.load(self.state, SKILL, False)["status"], "read")

    def test_failed_replace_keeps_previous(self):
        """A failed replace of the current baseline leaves both old generations intact."""
        first, second, third = self.generation("1"), self.generation("2"), self.generation("3")
        self.assertIsNone(self.baseline.save(self.state, SKILL, first))
        self.assertIsNone(self.baseline.save(self.state, SKILL, second))
        current_name, previous_name = f"{SKILL}.json", f"{SKILL}.previous.json"

        real_replace = self.baseline.os.replace

        def failing_replace(src, dst):
            if Path(dst).name == current_name:
                raise OSError("invented replace failure")
            return real_replace(src, dst)

        self.baseline.os.replace = failing_replace
        self.addCleanup(setattr, self.baseline.os, "replace", real_replace)
        reason = self.baseline.save(self.state, SKILL, third)
        self.baseline.os.replace = real_replace

        self.assertIsInstance(reason, str)
        self.assertEqual(self.read_json(current_name), second)
        self.assertEqual(self.read_json(previous_name), first)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()),
                         sorted([current_name, previous_name]), "a temporary file was left")

    def test_unreadable_is_kept(self):
        bad_text = "{\"schema_version\": 1, \"skill\": \"ush-inventory\", broken"
        self.write(f"{SKILL}.json", bad_text)
        new = self.generation("2")

        self.assertIsNone(self.baseline.save(self.state, SKILL, new))
        kept = sorted(self.state.glob(f"{SKILL}.unreadable-*.json"))
        self.assertEqual(len(kept), 1, [p.name for p in self.state.iterdir()])
        self.assertEqual(kept[0].read_text(encoding="utf-8"), bad_text)
        self.assertEqual(self.read_json(f"{SKILL}.json"), new)


class TestAge(BaselineTest):
    def test_age_and_naive_time(self):
        now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(self.baseline.age_days("2026-09-01T00:00:00Z", now), 10.5)

        with self.subTest("naive created_at makes load report unreadable"):
            self.write(f"{SKILL}.json",
                       json.dumps(baseline_data({}, created_at="2026-09-01T00:00:00")))
            try:
                result = self.baseline.load(self.state, SKILL, False)
            except TypeError as exc:
                self.fail(f"load raised TypeError on a naive time: {exc}")
            self.assertEqual(result["status"], "unreadable")
            self.assertTrue(result["reason"], "unreadable without a reason")


if __name__ == "__main__":
    unittest.main()

"""Stable item ids across runs: skills/ush-common/scripts/ids.py (plan 108, M1).

Public interface under test (from the plan):
- ``load_map(state_dir, skill) -> (id_map, reason)``; reads ``<state_dir>/<skill>.ids.json``
  with the shape ``{"version": 1, "skill": "<skill>", "prefixes": {"x": {"next": 18,
  "keys": {"<key>": {"n": 17, "seen": "2026-10-03"}}}}}``. No file gives an empty map and
  ``reason`` ``None``; an unreadable or malformed file gives an empty map and a reason.
- ``assign(id_map, prefix, items, key_of, today)`` sets ``item["id"]`` to prefix + number,
  keeps the order of ``items`` and returns the list of keys repeated within the call.
- ``save_map(state_dir, skill, id_map, today)`` drops keys whose ``seen`` is older than
  ``KEEP_DAYS = 90`` days without lowering ``next``, writes through ``baseline.save_json`` and
  returns ``None`` or a reason.
- ``baseline.save_json(state_dir, name, data, validate, read_back=None)`` writes
  ``<name>.json`` with a verification read; an old file that ``validate`` rejects is kept as
  ``<name>.unreadable-<stamp>.json``.

Assumptions where the plan leaves the shape open:
- ``today`` is an ISO date string (``"2026-10-03"``), the same form as ``seen`` in the file.
- Items are dicts; ``key_of`` is a callable ``item -> key or None``.
- The in-memory map is inspected only through the documented file shape (after ``save_map``),
  never through its in-memory layout.
- ``save_map`` takes no ``read_back``; the failed verification read is exercised through
  ``baseline.save_json`` on the same ``<skill>.ids`` file name.
- ``read_back`` is a callable ``(path) -> str`` (as for ``baseline.save``); ``validate`` is a
  callable ``(old data) -> None or reason``.

Every map here is invented and lives in a temporary directory; nothing touches the machine
or the real data directory.
"""

import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

SKILL = "ush-inventory"
MAP_FILE = f"{SKILL}.ids.json"
MAP_NAME = f"{SKILL}.ids"
TODAY = "2026-10-03"


def temp_dir(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


def map_file(prefixes):
    return {"version": 1, "skill": SKILL, "prefixes": prefixes}


def items(*keys):
    return [{"key": key, "name": f"Invented item {key}"} for key in keys]


def key_of(item):
    return item["key"]


def ids_of(listed):
    return [item["id"] for item in listed]


def validate_map(old):
    if isinstance(old, dict) and isinstance(old.get("prefixes"), dict):
        return None
    return "not an id map"


class IdsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ids = load_script("ush-common", "ids")
        cls.baseline = load_script("ush-common", "baseline")

    def setUp(self):
        self.state = temp_dir(self)

    def write_map(self, data):
        (self.state / MAP_FILE).write_text(json.dumps(data), encoding="utf-8")

    def read_map(self):
        return json.loads((self.state / MAP_FILE).read_text(encoding="utf-8"))

    def saved_prefix(self, id_map, today, prefix="x"):
        self.assertIsNone(self.ids.save_map(self.state, SKILL, id_map, today))
        return self.read_map()["prefixes"][prefix]


class TestIds(IdsTest):
    def test_assign_keeps_numbers(self):
        self.assertEqual(self.ids.KEEP_DAYS, 90)
        old_seen = "2026-09-01"
        self.write_map(map_file({"x": {"next": 4, "keys": {
            "a": {"n": 1, "seen": old_seen},
            "b": {"n": 2, "seen": old_seen},
            "c": {"n": 3, "seen": old_seen},
        }}}))
        id_map, reason = self.ids.load_map(self.state, SKILL)
        self.assertIsNone(reason)

        with self.subTest("known key keeps its number, new key takes next"):
            first = items("c", "d")
            repeated = self.ids.assign(id_map, "x", first, key_of, TODAY)
            self.assertEqual(ids_of(first), ["x3", "x4"])
            self.assertEqual([i["key"] for i in first], ["c", "d"], "order changed")
            self.assertEqual(repeated, [])
            saved = self.saved_prefix(id_map, TODAY)
            self.assertEqual(saved["next"], 5)
            self.assertEqual(saved["keys"]["d"]["n"], 4)
            self.assertEqual(saved["keys"]["c"], {"n": 3, "seen": TODAY})

        with self.subTest("removed key's number is not reused"):
            second = items("a", "d")
            repeated = self.ids.assign(id_map, "x", second, key_of, TODAY)
            self.assertEqual(ids_of(second), ["x1", "x4"])
            self.assertEqual(repeated, [])
            saved = self.saved_prefix(id_map, TODAY)
            self.assertEqual(saved["next"], 5)
            self.assertEqual(saved["keys"]["b"]["n"], 2)

        with self.subTest("repeated key gets a one-time number and is returned"):
            third = items("a", "a")
            repeated = self.ids.assign(id_map, "x", third, key_of, TODAY)
            self.assertEqual(ids_of(third), ["x1", "x5"])
            self.assertEqual(repeated, ["a"])
            saved = self.saved_prefix(id_map, TODAY)
            self.assertEqual(saved["keys"]["a"]["n"], 1)
            self.assertNotIn(5, [entry["n"] for entry in saved["keys"].values()])

        with self.subTest("item without a key gets a number not in keys"):
            fourth = items(None)
            self.ids.assign(id_map, "x", fourth, key_of, TODAY)
            item_id = fourth[0]["id"]
            self.assertRegex(item_id, r"^x[0-9]+$")
            saved = self.saved_prefix(id_map, TODAY)
            self.assertNotIn(int(item_id[1:]), [entry["n"] for entry in saved["keys"].values()])
            self.assertNotIn(None, saved["keys"])
            self.assertNotIn("None", saved["keys"])
            self.assertNotIn("null", saved["keys"])
            next_before = saved["next"]

        with self.subTest("key unseen for 91 days is dropped on save, next unchanged"):
            # b was last seen on old_seen; a, c and d were seen on TODAY.
            late = (date.fromisoformat(old_seen) + timedelta(days=91)).isoformat()
            saved = self.saved_prefix(id_map, late)
            self.assertNotIn("b", saved["keys"])
            self.assertEqual(sorted(saved["keys"]), ["a", "c", "d"])
            self.assertEqual(saved["next"], next_before)

    def test_load_save_and_unreadable(self):
        with self.subTest("no file gives an empty map without a reason"):
            id_map, reason = self.ids.load_map(self.state, SKILL)
            self.assertIsNone(reason)
            listed = items("k1", "k2")
            self.ids.assign(id_map, "x", listed, key_of, TODAY)
            self.assertEqual(ids_of(listed), ["x1", "x2"], "map was not empty")

        with self.subTest("save and load give the same map"):
            self.assertIsNone(self.ids.save_map(self.state, SKILL, id_map, TODAY))
            reloaded, reason = self.ids.load_map(self.state, SKILL)
            self.assertIsNone(reason)
            self.assertEqual(reloaded, id_map)
            again = items("k2", "k1")
            self.ids.assign(reloaded, "x", again, key_of, TODAY)
            self.assertEqual(ids_of(again), ["x2", "x1"])

        bad_cases = {
            "invalid JSON": "{\"version\": 1, \"skill\": \"ush-inventory\", broken",
            "no prefixes": json.dumps({"version": 1, "skill": SKILL}),
        }
        for label, bad_text in bad_cases.items():
            with self.subTest(label):
                state = temp_dir(self)
                path = state / MAP_FILE
                path.write_text(bad_text, encoding="utf-8")
                id_map, reason = self.ids.load_map(state, SKILL)
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip(), "unreadable map without a reason")
                listed = items("k1")
                self.ids.assign(id_map, "x", listed, key_of, TODAY)
                self.assertEqual(ids_of(listed), ["x1"], "map was not empty")

                self.assertIsNone(self.ids.save_map(state, SKILL, id_map, TODAY))
                kept = sorted(state.glob(f"{MAP_NAME}.unreadable-*.json"))
                self.assertEqual(len(kept), 1, [p.name for p in state.iterdir()])
                self.assertEqual(kept[0].read_text(encoding="utf-8"), bad_text)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["prefixes"]["x"]
                                 ["keys"]["k1"]["n"], 1)

        with self.subTest("failed verification read gives a reason and keeps the old file"):
            state = temp_dir(self)
            id_map, _ = self.ids.load_map(state, SKILL)
            self.ids.assign(id_map, "x", items("k1"), key_of, TODAY)
            self.assertIsNone(self.ids.save_map(state, SKILL, id_map, TODAY))
            current = state / MAP_FILE
            before = current.read_bytes()

            new = map_file({"x": {"next": 3, "keys": {
                "k1": {"n": 1, "seen": TODAY}, "k2": {"n": 2, "seen": TODAY}}}})
            other = map_file({"x": {"next": 9, "keys": {}}})
            calls = []

            def wrong_read_back(path):
                calls.append(path)
                return json.dumps(other)

            reason = self.baseline.save_json(state, MAP_NAME, new, validate_map,
                                             read_back=wrong_read_back)
            self.assertTrue(calls, "the substituted verification read was not used")
            self.assertIsInstance(reason, str)
            self.assertTrue(reason.strip(), "failed verification without a reason")
            self.assertEqual(current.read_bytes(), before, "old map changed")
            self.assertEqual(sorted(p.name for p in state.iterdir()), [MAP_FILE],
                             "a temporary or previous file was left")


class TestSaveJson(IdsTest):
    def test_save_json_writes_with_read_back(self):
        first = map_file({"x": {"next": 2, "keys": {"k1": {"n": 1, "seen": TODAY}}}})
        second = map_file({"x": {"next": 3, "keys": {
            "k1": {"n": 1, "seen": TODAY}, "k2": {"n": 2, "seen": TODAY}}}})
        current = self.state / f"{MAP_NAME}.json"
        previous = self.state / f"{MAP_NAME}.previous.json"

        self.assertIsNone(self.baseline.save_json(self.state, MAP_NAME, first, validate_map))
        self.assertEqual(json.loads(current.read_text(encoding="utf-8")), first)

        calls = []

        def read_back(path):
            calls.append(path)
            return Path(path).read_text(encoding="utf-8")

        self.assertIsNone(self.baseline.save_json(self.state, MAP_NAME, second, validate_map,
                                                  read_back=read_back))
        self.assertTrue(calls, "the given verification read was not used")
        self.assertEqual(json.loads(current.read_text(encoding="utf-8")), second)
        self.assertEqual(json.loads(previous.read_text(encoding="utf-8")), first)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()),
                         sorted([current.name, previous.name]), "a temporary file was left")


class TestReviewNotes(IdsTest):
    def test_map_not_read_at_start_is_not_replaced(self):
        # The saved map could not be read when the run started (e.g. locked for a moment),
        # so numbering began again; at save time it reads fine and must be kept.
        saved = map_file({"x": {"next": 4, "keys": {
            "a": {"n": 1, "seen": TODAY}, "b": {"n": 2, "seen": TODAY},
            "c": {"n": 3, "seen": TODAY}}}})
        self.write_map(saved)
        fresh = self.ids.empty_map(SKILL)
        self.ids.assign(fresh, "x", items("d"), key_of, TODAY)
        reason = self.ids.save_map(self.state, SKILL, fresh, TODAY)
        self.assertTrue(reason)
        self.assertEqual(self.read_map(), saved)
        self.assertFalse((self.state / f"{MAP_NAME}.previous.json").exists())

    def test_map_started_from_saved_is_written(self):
        self.write_map(map_file({"x": {"next": 3, "keys": {
            "a": {"n": 1, "seen": TODAY}, "b": {"n": 2, "seen": TODAY}}}}))
        id_map, reason = self.ids.load_map(self.state, SKILL)
        self.assertIsNone(reason)
        self.ids.assign(id_map, "x", items("a", "c"), key_of, TODAY)
        self.assertIsNone(self.ids.save_map(self.state, SKILL, id_map, TODAY))
        self.assertEqual(self.read_map()["prefixes"]["x"]["next"], 4)

    def test_fresh_map_as_long_as_saved_is_not_written(self):
        saved = map_file({"x": {"next": 4, "keys": {
            "a": {"n": 1, "seen": TODAY}, "b": {"n": 2, "seen": TODAY},
            "c": {"n": 3, "seen": TODAY}}}})
        self.write_map(saved)
        fresh = self.ids.empty_map(SKILL)
        self.ids.assign(fresh, "x", items("d", "e", "f"), key_of, TODAY)
        self.assertTrue(self.ids.save_map(self.state, SKILL, fresh, TODAY))
        self.assertEqual(self.read_map(), saved)

    def test_today_must_be_a_plain_date(self):
        for today in ("20261003", "2026-W40-6", None):
            with self.subTest(today=today), self.assertRaises(ValueError):
                self.ids.assign(self.ids.empty_map(SKILL), "x", items("a"), key_of, today)
        self.write_map(map_file({"x": {"next": 2, "keys": {"a": {"n": 1, "seen": "20261003"}}}}))
        self.assertTrue(self.ids.load_map(self.state, SKILL)[1])

    def test_bad_record_reason_does_not_name_the_key(self):
        secret = "task:\\Invented Folder\\Invented Task"
        for record in ("not an object", {"n": 1}, {"n": 9, "seen": TODAY}):
            with self.subTest(record=record):
                self.write_map(map_file({"x": {"next": 2, "keys": {secret: record}}}))
                reason = self.ids.load_map(self.state, SKILL)[1]
                self.assertTrue(reason)
                self.assertNotIn("Invented", reason)
                self.assertNotIn("Invented", self.ids.load_note(reason)[1])

    def test_new_map_saved_but_previous_not_replaced(self):
        self.write_map(map_file({"x": {"next": 2, "keys": {"a": {"n": 1, "seen": TODAY}}}}))
        id_map, reason = self.ids.load_map(self.state, SKILL)
        self.assertIsNone(reason)
        self.ids.assign(id_map, "x", items("a", "b"), key_of, TODAY)
        real_replace = os.replace

        def replace(source, target):
            if str(target).endswith(".previous.json"):
                raise OSError("invented lock")
            return real_replace(source, target)

        with mock.patch.object(os, "replace", replace):
            reason = self.ids.save_map(self.state, SKILL, id_map, TODAY)
        self.assertTrue(reason)
        self.assertEqual(self.read_map()["prefixes"]["x"]["next"], 3)
        what, text = self.ids.save_note(reason)
        self.assertEqual(what, "stable ids save")
        self.assertIn("next run keeps", text)
        self.assertNotIn("may give other ids", text)

    def test_unchanged_map_that_failed_to_save_is_not_called_saved(self):
        self.write_map(map_file({"x": {"next": 2, "keys": {"a": {"n": 1, "seen": TODAY}}}}))
        id_map, reason = self.ids.load_map(self.state, SKILL)
        self.assertIsNone(reason)
        self.ids.assign(id_map, "x", items("a"), key_of, TODAY)
        real_replace = os.replace

        def replace(source, target):
            if str(target).endswith(MAP_FILE):
                raise OSError("invented lock")
            return real_replace(source, target)

        with mock.patch.object(os, "replace", replace):
            reason = self.ids.save_map(self.state, SKILL, id_map, TODAY)
        self.assertTrue(reason)
        text = self.ids.save_note(reason)[1]
        self.assertIn("may give other ids", text)
        self.assertNotIn("next run keeps", text)

    def test_map_not_saved_says_so(self):
        text = self.ids.save_note("cannot write ush-inventory.ids.json.tmp: invented")[1]
        self.assertIn("may give other ids", text)
        self.assertNotIn("next run keeps", text)


if __name__ == "__main__":
    unittest.main()

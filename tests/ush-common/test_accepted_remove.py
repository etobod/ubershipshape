"""Removing an accepted finding: accepted.py --remove (plan 067, M1, criteria K1-K4).

Interface under test (from the plan):

- ``accepted.py --remove "ush-runall a<n>" --detail-file <runall detail> --data-dir <dir>``
  reads the ``a<n>`` item from the ``accepted`` list of the runall detail file and removes
  the entry of ``state/accepted.json`` with that item's ``kind`` and ``key``, through the
  same verified write as ``--accept``. It prints ``{ok, key, kind, path}`` as JSON.
- A target that is not ``ush-runall a<n>``, an id missing from the detail file, a detail
  file with ``accepted`` ``null``, a key no longer in ``accepted.json`` or an unreadable
  ``accepted.json`` prints ``ok`` ``false`` with a ``reason``, exits 1 and writes nothing.
- Removing the last entry leaves ``{"schema_version": 1, "entries": []}``.
- One of ``--accept`` and ``--remove`` is required; both together is a usage error (exit 2).

The ``accepted`` items follow skills/ush-runall/references/summary-contract.md
("Accepted findings"). The ``accepted.json`` entries are built through ``--accept`` on the
invented pass of ``test_accepted.py``, so their shape is not guessed here. Every value is
invented (Contoso, Fabrikam); nothing on the machine is read.
"""

import json
import os
import subprocess
import sys

from .test_accepted import (
    ACCEPTED_SCRIPT,
    EVENT_KEY,
    RULE_KEY,
    TASK_KEY,
    AcceptedTestCase,
    make_pass,
    write_json,
)


def accepted_item(item_id, kind, key, state="quiet", evidence=None):
    return {"id": item_id, "kind": kind, "key": key, "state": state, "changed": [],
            "skipped": [], "evidence": evidence, "accepted_on": "2026-11-05",
            "reason": None}


def counts_of(items):
    counts = {"quiet": 0, "back": 0, "gone": 0, "not_checked": 0}
    for item in items:
        counts[item["state"]] += 1
    return counts


def with_accepted(detail_file, items):
    """Rewrite an invented runall detail file with the given ``accepted`` list (or None)."""
    data = json.loads(detail_file.read_text(encoding="utf-8"))
    data["accepted"] = items
    data["accepted_counts"] = None if items is None else counts_of(items)
    write_json(detail_file, data)
    return detail_file


class TestRemove(AcceptedTestCase):
    def run_script(self, data_dir, args):
        env = dict(os.environ)
        env.pop("USH_DATA_DIR", None)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(ACCEPTED_SCRIPT), *args, "--data-dir", str(data_dir)],
            capture_output=True, text=True, check=False, encoding="utf-8", env=env,
            timeout=120)

    def run_remove(self, data_dir, target, detail_file):
        done = self.run_script(data_dir, ["--remove", target,
                                          "--detail-file", str(detail_file)])
        try:
            result = json.loads(done.stdout)
        except ValueError:
            self.fail(f"stdout is not JSON: {done.stdout!r}; stderr: {done.stderr!r}")
        self.assertIsInstance(result, dict, done.stdout)
        return done.returncode, result

    def two_entries(self, data_dir):
        """accepted.json with a firewall rule (first) and an autostart entry (second)."""
        detail = make_pass(data_dir)
        self.accept_ok(data_dir, "ush-inventory x2", detail)
        self.accept_ok(data_dir, "ush-inventory s3", detail)
        entries = self.entries(data_dir)
        self.assertEqual([(e.get("kind"), e.get("key")) for e in entries],
                         [("firewall_rule", RULE_KEY), ("autostart", TASK_KEY)], entries)
        return detail

    def test_removes_the_named_entry(self):
        data_dir = self.data_dir()
        detail = self.two_entries(data_dir)
        with_accepted(detail, [
            accepted_item("a1", "firewall_rule", RULE_KEY, evidence="ush-inventory x2"),
            accepted_item("a2", "autostart", TASK_KEY, evidence="ush-inventory s3"),
        ])

        code, result = self.run_remove(data_dir, "ush-runall a2", detail)
        self.assertEqual(code, 0, result)
        self.assertIs(result.get("ok"), True, result)
        self.assertEqual(result.get("kind"), "autostart", result)
        self.assertEqual(result.get("key"), TASK_KEY, result)
        self.assertEqual(result.get("path"), str(self.accepted_path(data_dir)), result)

        entries = self.entries(data_dir)
        self.assertEqual(len(entries), 1, entries)
        self.assertEqual(entries[0].get("kind"), "firewall_rule", entries)
        self.assertEqual(entries[0].get("key"), RULE_KEY, entries)

    def test_refusals_write_nothing(self):
        items = [
            accepted_item("a1", "firewall_rule", RULE_KEY, evidence="ush-inventory x2"),
            accepted_item("a2", "autostart", TASK_KEY, evidence="ush-inventory s3"),
            accepted_item("a3", "event_group", EVENT_KEY, state="gone"),
        ]
        cases = {
            "no such a item": ("ush-runall a9", items, False),
            "not an a item": ("ush-inventory s8", items, False),
            "accepted null in the detail file": ("ush-runall a2", None, False),
            "key no longer in accepted.json": ("ush-runall a3", items, False),
            "accepted.json not valid JSON": ("ush-runall a2", items, True),
        }
        for case, (target, listed, break_file) in cases.items():
            with self.subTest(case=case):
                data_dir = self.data_dir()
                detail = with_accepted(self.two_entries(data_dir), listed)
                path = self.accepted_path(data_dir)
                if break_file:
                    path.write_bytes(b'{"schema_version": 1, "entries": [{"kind": "autostart"')
                before = path.read_bytes()

                code, result = self.run_remove(data_dir, target, detail)
                self.assertEqual(code, 1, result)
                self.assertIs(result.get("ok"), False, result)
                reason = result.get("reason")
                self.assertIsInstance(reason, str, result)
                self.assertTrue(reason.strip(), result)
                self.assertEqual(path.read_bytes(), before, path)

    def test_last_entry_leaves_empty_list(self):
        data_dir = self.data_dir()
        detail = make_pass(data_dir)
        self.accept_ok(data_dir, "ush-inventory x2", detail)
        with_accepted(detail, [
            accepted_item("a1", "firewall_rule", RULE_KEY, evidence="ush-inventory x2"),
        ])

        code, result = self.run_remove(data_dir, "ush-runall a1", detail)
        self.assertEqual(code, 0, result)
        self.assertIs(result.get("ok"), True, result)

        path = self.accepted_path(data_dir)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"schema_version": 1, "entries": []})
        loaded = self.accepted.load(data_dir)
        self.assertEqual(loaded.get("status"), "read", loaded)
        self.assertEqual(loaded.get("entries"), [], loaded)
        self.assertIsNone(loaded.get("reason"), loaded)

    def test_one_action_required(self):
        data_dir = self.data_dir()
        detail = with_accepted(make_pass(data_dir), [
            accepted_item("a1", "firewall_rule", RULE_KEY, evidence="ush-inventory x2"),
        ])
        cases = {
            "both": ["--accept", "ush-inventory x2", "--remove", "ush-runall a1",
                     "--detail-file", str(detail)],
            "neither": ["--detail-file", str(detail)],
        }
        for case, args in cases.items():
            with self.subTest(case=case):
                done = self.run_script(data_dir, args)
                self.assertEqual(done.returncode, 2,
                                 f"stdout: {done.stdout!r}; stderr: {done.stderr!r}")


if __name__ == "__main__":
    import unittest

    unittest.main()

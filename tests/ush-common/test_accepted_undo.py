"""Undoing the last write of accepted.json: accepted.py --undo (plan 067, final review).

- ``accepted.py --undo --data-dir <dir>`` (no ``--detail-file``) checks
  ``state/accepted.previous.json`` as ``load`` checks ``accepted.json``, writes it back
  through the same verified write (the current file becomes the previous generation),
  reads it back and prints ``{ok, entry_count, path}``; a refusal prints ``ok`` false with
  ``reason``, exits 1 and writes nothing.
- The first write ever leaves an empty previous generation, so ``--undo`` after it gives
  no accepted findings.

The entries are built through ``--accept`` on the invented pass of ``test_accepted.py``.
Every value is invented; nothing on the machine is read.
"""

import json
import os
import subprocess
import sys
from unittest import mock

from .test_accepted import (
    ACCEPTED_SCRIPT,
    RULE_KEY,
    TASK_KEY,
    AcceptedTestCase,
    make_pass,
)


class TestUndo(AcceptedTestCase):
    def run_script(self, data_dir, args):
        env = dict(os.environ)
        env.pop("USH_DATA_DIR", None)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(ACCEPTED_SCRIPT), *args, "--data-dir", str(data_dir)],
            capture_output=True, text=True, check=False, encoding="utf-8", env=env,
            timeout=120)

    def run_undo(self, data_dir):
        done = self.run_script(data_dir, ["--undo"])
        try:
            result = json.loads(done.stdout)
        except ValueError:
            self.fail(f"stdout is not JSON: {done.stdout!r}; stderr: {done.stderr!r}")
        self.assertIsInstance(result, dict, done.stdout)
        return done.returncode, result

    @staticmethod
    def previous_path(data_dir):
        return data_dir / "state" / "accepted.previous.json"

    def keys(self, data_dir):
        return [(e.get("kind"), e.get("key")) for e in self.entries(data_dir)]

    def test_first_write_leaves_an_empty_previous(self):
        data_dir = self.data_dir()
        self.accept_ok(data_dir, "ush-inventory x2", make_pass(data_dir))
        previous = json.loads(self.previous_path(data_dir).read_text(encoding="utf-8"))
        self.assertEqual(previous, {"schema_version": 1, "entries": []})

    def test_undo_after_first_write_gives_no_entries(self):
        data_dir = self.data_dir()
        self.accept_ok(data_dir, "ush-inventory x2", make_pass(data_dir))

        code, result = self.run_undo(data_dir)
        self.assertEqual(code, 0, result)
        self.assertIs(result.get("ok"), True, result)
        self.assertEqual(result.get("entry_count"), 0, result)
        self.assertEqual(result.get("path"), str(self.accepted_path(data_dir)), result)
        self.assertNotIn("warning", result)
        self.assertEqual(self.entries(data_dir), [])

    def test_undo_after_an_accept(self):
        data_dir = self.data_dir()
        detail = make_pass(data_dir)
        self.accept_ok(data_dir, "ush-inventory x2", detail)
        self.accept_ok(data_dir, "ush-inventory s3", detail)
        self.assertEqual(self.keys(data_dir),
                         [("firewall_rule", RULE_KEY), ("autostart", TASK_KEY)])

        code, result = self.run_undo(data_dir)
        self.assertEqual(code, 0, result)
        self.assertIs(result.get("ok"), True, result)
        self.assertEqual(result.get("entry_count"), 1, result)
        self.assertEqual(self.keys(data_dir), [("firewall_rule", RULE_KEY)])
        # The state the undo replaced is now the previous generation.
        previous = json.loads(self.previous_path(data_dir).read_text(encoding="utf-8"))
        self.assertEqual([(e["kind"], e["key"]) for e in previous["entries"]],
                         [("firewall_rule", RULE_KEY), ("autostart", TASK_KEY)])

    def test_second_undo_toggles_back(self):
        data_dir = self.data_dir()
        detail = make_pass(data_dir)
        self.accept_ok(data_dir, "ush-inventory x2", detail)
        self.accept_ok(data_dir, "ush-inventory s3", detail)
        after_accept = self.accepted_path(data_dir).read_bytes()

        self.assertEqual(self.run_undo(data_dir)[0], 0)
        self.assertEqual(self.keys(data_dir), [("firewall_rule", RULE_KEY)])
        code, result = self.run_undo(data_dir)
        self.assertEqual(code, 0, result)
        self.assertEqual(result.get("entry_count"), 2, result)
        self.assertEqual(self.accepted_path(data_dir).read_bytes(), after_accept)

    def test_refused_with_no_previous_writes_nothing(self):
        cases = {
            "no files at all": False,
            "accepted.json without a previous generation": True,
        }
        for case, with_current in cases.items():
            with self.subTest(case=case):
                data_dir = self.data_dir()
                state = data_dir / "state"
                current = self.accepted_path(data_dir)
                if with_current:
                    state.mkdir(parents=True)
                    current.write_text('{"schema_version": 1, "entries": []}',
                                       encoding="utf-8")
                before = sorted(p.name for p in state.iterdir()) if state.exists() else None
                current_bytes = current.read_bytes() if with_current else None

                code, result = self.run_undo(data_dir)
                self.assertEqual(code, 1, result)
                self.assertIs(result.get("ok"), False, result)
                self.assertTrue(str(result.get("reason") or "").strip(), result)
                after = sorted(p.name for p in state.iterdir()) if state.exists() else None
                self.assertEqual(after, before)
                if with_current:
                    self.assertEqual(current.read_bytes(), current_bytes)

    def test_refused_with_unreadable_previous_writes_nothing(self):
        data_dir = self.data_dir()
        self.accept_ok(data_dir, "ush-inventory x2", make_pass(data_dir))
        self.previous_path(data_dir).write_bytes(b'{"schema_version": 1, "entries": [')
        before = self.accepted_path(data_dir).read_bytes()

        code, result = self.run_undo(data_dir)
        self.assertEqual(code, 1, result)
        self.assertIs(result.get("ok"), False, result)
        self.assertIn("accepted.previous.json", result.get("reason") or "", result)
        self.assertEqual(self.accepted_path(data_dir).read_bytes(), before)

    def test_refused_with_unreadable_current_writes_nothing(self):
        data_dir = self.data_dir()
        detail = make_pass(data_dir)
        self.accept_ok(data_dir, "ush-inventory x2", detail)
        self.accept_ok(data_dir, "ush-inventory s3", detail)
        self.accepted_path(data_dir).write_bytes(b'{"schema_version": 1, "entries": [')
        state = data_dir / "state"
        before = {p.name: p.read_bytes() for p in state.iterdir() if p.is_file()}

        code, result = self.run_undo(data_dir)
        self.assertEqual(code, 1, result)
        self.assertIs(result.get("ok"), False, result)
        self.assertIn("accepted.json", result.get("reason") or "", result)
        after = {p.name: p.read_bytes() for p in state.iterdir() if p.is_file()}
        self.assertEqual(after, before)

    def test_warning_is_passed_through(self):
        data_dir = self.data_dir()
        self.accept_ok(data_dir, "ush-inventory x2", make_pass(data_dir))
        warning = ("the new accepted.json is saved, but accepted.previous.json could not "
                   "be replaced: locked")
        real = self.accepted.baseline.save_json

        def save_json(*args, **kwargs):
            real(*args, **kwargs)
            return warning

        with mock.patch.object(self.accepted.baseline, "save_json", side_effect=save_json):
            result = self.accepted.undo(data_dir)
        self.assertIs(result["ok"], True, result)
        self.assertEqual(result["warning"], warning)

    def test_detail_file_only_with_accept_and_remove(self):
        data_dir = self.data_dir()
        detail = make_pass(data_dir)
        cases = {
            "--undo with --detail-file": ["--undo", "--detail-file", str(detail)],
            "--undo with --accept": ["--undo", "--accept", "ush-inventory x2",
                                     "--detail-file", str(detail)],
            "--accept without --detail-file": ["--accept", "ush-inventory x2"],
            "--remove without --detail-file": ["--remove", "ush-runall a1"],
        }
        for case, args in cases.items():
            with self.subTest(case=case):
                done = self.run_script(data_dir, args)
                self.assertEqual(done.returncode, 2,
                                 f"stdout: {done.stdout!r}; stderr: {done.stderr!r}")
                self.assertFalse(self.accepted_path(data_dir).exists())


if __name__ == "__main__":
    import unittest

    unittest.main()

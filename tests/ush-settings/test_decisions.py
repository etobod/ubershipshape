"""The user's decisions in skills/ush-settings/scripts/settings.py (plan 030, M1).

Interface under test (see ``fakes.py`` for the run contract):

- A collect run reads ``<data dir>/decisions.json``. A ``setting`` check of a valid decision
  that names a catalogue entry replaces that entry's ``expected``: the detail item carries
  ``expected`` = the decision's value as a list and ``expected_from`` = ``"decision D<n>"``;
  ``state`` is ``matches`` / ``differs`` against that expectation.
- Without the file, items carry no ``expected_from`` (absent or None) and nothing changes.
- An unreadable file keeps the catalogue's ``expected`` and adds a ``not_checked`` entry
  naming ``decisions.json``.
- ``--block <id>`` refuses an item whose ``expected_from`` is set and whose catalogue apply
  value is not in the decision's ``expected``: a comment line
  ``# <id> <entry id>: no block: set by decision D<n>...`` and no command.

Every value here is invented; PowerShell never starts.
"""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from .fakes import (
    FakePowerShell,
    SettingsTestCase,
    clean_responses,
    loc,
    minutes,
    present,
    real_entries,
    registry,
    registry_entry,
)

DECIDED_LOC = loc("HKLM", "SOFTWARE\\InventedVendor\\Decided", "InventedDecidedToggle",
                  "preference")
DECIDED_ID = "invented_decided_toggle"
DWORD_1 = {"location": 0, "value": 1, "kind": "DWord"}


def decided_catalogue():
    """One entry whose catalogue expects and applies 1."""
    return [registry_entry(DECIDED_ID, [DECIDED_LOC], expected=[1], default=1,
                           apply=DWORD_1)]


def decisions_data(expected):
    return {"schema_version": 1, "decisions": [{
        "id": "D1",
        "made": "2026-01-02",
        "text": "Invented: the decided toggle stays off.",
        "source": "invented repair plan",
        "checks": [{"kind": "setting", "skill": "ush-settings", "item": DECIDED_ID,
                    "expected": expected}],
    }]}


def commands(text):
    """Non-empty lines that are not comments."""
    return [line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


class TestSettingsDecisions(SettingsTestCase):
    def data_dir_with(self, text):
        """A fresh data directory holding ``decisions.json`` with ``text``."""
        data_dir = self.data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "decisions.json").write_text(text, encoding="utf-8")
        return data_dir

    def data_dir_with_decision(self, expected):
        return self.data_dir_with(json.dumps(decisions_data(expected), indent=2))

    def reading(self, value):
        return FakePowerShell({"registry_values": registry(present(DECIDED_LOC, value))})

    def test_decision_beats_catalogue(self):
        self.write_catalogue(decided_catalogue())
        cases = {0: "matches", 1: "differs"}
        for value, state in cases.items():
            with self.subTest(reading=value):
                data_dir = self.data_dir_with_decision(0)
                summary = self.collect(self.reading(value), data_dir=data_dir)
                item = self.detail_item(summary, DECIDED_ID)
                self.assertEqual(item.get("expected"), [0], item)
                self.assertEqual(item.get("expected_from"), "decision D1", item)
                self.assertEqual(item.get("state"), state, item)

    def test_unreadable_file_keeps_catalogue(self):
        self.write_catalogue(decided_catalogue())
        data_dir = self.data_dir_with('{"schema_version": 1, "decisions": [ invented broken')
        summary = self.collect(self.reading(0), data_dir=data_dir)
        item = self.detail_item(summary, DECIDED_ID)
        self.assertEqual(item.get("expected"), [1], item)
        self.assertIsNone(item.get("expected_from"), item)
        self.assertEqual(item.get("state"), "differs", item)
        self.assertIn("decisions.json", self.not_checked_text(summary))

    def test_no_catalogue_block_against_decision(self):
        self.write_catalogue(decided_catalogue())
        data_dir = self.data_dir_with_decision([0])
        summary = self.collect(self.reading(2), data_dir=data_dir)
        item = self.detail_item(summary, DECIDED_ID)
        self.assertEqual(item.get("expected_from"), "decision D1", item)
        self.assertEqual(item.get("state"), "differs", item)
        item_id = item.get("id")
        self.assertIsInstance(item_id, str, item)

        _code, stdout, stderr = self.run_main(data_dir, FakePowerShell(), now=minutes(5),
                                             extra=("--block", item_id))
        self.assertEqual(commands(stdout), [], stdout)
        refusals = [line.strip() for line in stdout.splitlines()
                    if line.strip().startswith("#")
                    and "no block: set by decision D1" in line]
        self.assertTrue(refusals, stdout + stderr)
        self.assertTrue(any(item_id in line.split("no block:")[0] for line in refusals),
                        refusals)

    def test_block_reads_decisions_made_after_collect(self):
        # Review fix (plan 030 M1): --block reads decisions.json again, so a decision
        # recorded after the collection still refuses the catalogue's change, also with
        # --detail-file and --data-dir as ush-runall passes them.
        self.write_catalogue(decided_catalogue())
        data_dir = self.data_dir()
        summary = self.collect(self.reading(0), data_dir=data_dir)
        item = self.detail_item(summary, DECIDED_ID)
        self.assertIsNone(item.get("expected_from"), item)
        self.assertEqual(item.get("state"), "differs", item)
        item_id = item.get("id")

        _code, before, _err = self.run_main(data_dir, FakePowerShell(), now=minutes(5),
                                            extra=("--block", item_id))
        self.assertTrue(commands(before), before)

        (data_dir / "decisions.json").write_text(json.dumps(decisions_data(0), indent=2),
                                                 encoding="utf-8")
        variants = {"newest detail": ("--block", item_id),
                    "named detail": ("--block", item_id,
                                     "--detail-file", summary.get("detail_file"))}
        for variant, extra in variants.items():
            with self.subTest(variant=variant):
                _code, stdout, stderr = self.run_main(data_dir, FakePowerShell(),
                                                      now=minutes(5), extra=extra)
                self.assertEqual(commands(stdout), [], stdout)
                self.assertIn("no block: set by decision D1", stdout, stdout + stderr)

    def run_block_without_data_dir(self, item_id, detail_file):
        """``--block`` with ``--detail-file`` only: no data directory resolves."""
        env = {key: value for key, value in os.environ.items() if key != "USH_DATA_DIR"}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out), \
                redirect_stderr(err):
            self.settings.main(["--block", item_id, "--detail-file", detail_file],
                               run_ps=FakePowerShell(), is_admin=lambda: False,
                               now=minutes(5))
        return out.getvalue(), err.getvalue()

    def test_block_says_when_decisions_are_not_read_again(self):
        # Review fix (plan 030 M1, round 2): when --block cannot read decisions.json again
        # (a bad file, or no data directory with --detail-file), it says so in a comment
        # line, and the decisions of the detail file still refuse the block.
        self.write_catalogue(decided_catalogue())
        data_dir = self.data_dir_with_decision(0)
        summary = self.collect(self.reading(1), data_dir=data_dir)
        item_id = self.detail_item(summary, DECIDED_ID).get("id")
        detail_file = summary.get("detail_file")

        with self.subTest(case="unreadable decisions.json"):
            (data_dir / "decisions.json").write_text("{ invented broken", encoding="utf-8")
            _code, stdout, stderr = self.run_main(
                data_dir, FakePowerShell(), now=minutes(5),
                extra=("--block", item_id, "--detail-file", detail_file))
            notes = [line for line in stdout.splitlines()
                     if line.startswith("#") and "decisions.json" in line]
            self.assertTrue(notes, stdout + stderr)
            self.assertEqual(commands(stdout), [], stdout)
            self.assertIn("no block: set by decision D1", stdout)

        with self.subTest(case="no data directory"):
            stdout, stderr = self.run_block_without_data_dir(item_id, detail_file)
            notes = [line for line in stdout.splitlines()
                     if line.startswith("#") and "decisions.json" in line]
            self.assertTrue(notes, stdout + stderr)
            self.assertEqual(commands(stdout), [], stdout)
            self.assertIn("no block: set by decision D1", stdout)


    def test_mistyped_decision_keeps_catalogue(self):
        # Review fix (plan 030 M1): "0" where the catalogue expects a number is a bad
        # file, never a permanent "differs".
        self.write_catalogue(decided_catalogue())
        data_dir = self.data_dir_with_decision("0")
        summary = self.collect(self.reading(1), data_dir=data_dir)
        item = self.detail_item(summary, DECIDED_ID)
        self.assertIsNone(item.get("expected_from"), item)
        self.assertEqual(item.get("state"), "matches", item)
        self.assertIn("decisions.json", self.not_checked_text(summary))


    def test_no_file_no_change(self):
        # No-regression guard: on clean data and without decisions.json, every item keeps
        # the catalogue's expectation and the clean state it had before plan 030.
        entries = real_entries()
        self.write_catalogue(entries)
        catalogue = {entry["id"]: entry for entry in entries}
        info_ids = {entry_id for entry_id, entry in catalogue.items()
                    if entry.get("expected") is None}
        data_dir = self.data_dir()
        summary = self.collect(FakePowerShell(clean_responses(entries)), data_dir=data_dir,
                               admin=True)
        self.assertFalse((data_dir / "decisions.json").exists())

        items = self.items_by_entry(self.detail(summary).get("settings"))
        self.assertEqual(set(items), set(catalogue))
        for entry_id, item in items.items():
            with self.subTest(entry=entry_id):
                self.assertIsNone(item.get("expected_from"), item)
                self.assertEqual(item.get("expected"), catalogue[entry_id].get("expected"),
                                 item)
                if entry_id in info_ids:
                    self.assertEqual(item.get("state"), "info", item)
                else:
                    self.assertIn(item.get("state"), ("matches", "not_applicable"), item)

        by_state = summary.get("counts", {}).get("by_state")
        self.assertIsInstance(by_state, dict, summary.get("counts"))
        self.assertEqual(by_state.get("differs", 0), 0, by_state)
        self.assertNotIn("decisions.json", self.not_checked_text(summary))


if __name__ == "__main__":
    unittest.main()

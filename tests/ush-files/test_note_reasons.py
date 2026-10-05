"""ush-files: the detail file is written before the baseline, and the "comparison on
drive" note names every reason (plan 141, M2, K6 and K8).

Interface under test (from the plan; the general one is in ``fakes.py``):

- ``files.main`` writes ``<data dir>/work/files-<stamp>.detail.json`` before
  ``baseline.save`` and ``baseline.archive``; an exception while writing the detail
  file ends the run without saving the baseline and without a history copy.
- The ``not_checked`` note whose ``what`` starts with "comparison on drive" gives, in
  its ``reason``, also "a gone and a new large file look moved or renamed (same size and
  creation time)" and "a new or gone folder could not be listed".

Assumptions added by these tests beyond the plan text:

- ``<stamp>`` is the UTC time of ``now`` as ``%Y%m%d-%H%M%S`` (the first run checks this
  against its own ``detail_file`` before the second run relies on it).
- A directory at the path of the detail file makes the write fail with an ``OSError``
  that ``main`` does not catch.
- Runs here have no administrator rights, so the baseline is ``state/ush-files.json``; a
  moved-aside generation ends in ``.previous.json`` and history copies live in
  ``state/history/`` with the ``YYYY-MM-DD`` day in the name.

Every tree and size is invented; nothing comes from a machine.
"""

import shutil
import unittest
from datetime import timedelta
from pathlib import Path

from .fakes import GIB, NOW, FakeMachine, FilesTestCase, file, folder

BASELINE = "ush-files.json"
NOTE_PREFIX = "comparison on drive"

FIRST_AT = NOW
# A different UTC day, so a history copy of the second run would carry another date.
SECOND_AT = NOW + timedelta(days=1)

BEFORE = {"Data": {"a.bin": 10, "big.bin": 2 * GIB}}
AFTER = {"Data": {"a.bin": 10, "big.bin": 3 * GIB}}


def stamp(moment):
    return moment.strftime("%Y%m%d-%H%M%S")


def denied(path):
    return PermissionError(13, "Access is denied", path)


class TestNoteReasons(FilesTestCase):
    # --- helpers ------------------------------------------------------------------------

    def two_runs(self, before, after):
        """Run ``before`` then ``after`` on drive C: one day apart; return the second
        summary."""
        data_dir = self.data_dir()
        self.collect(FakeMachine({"C": before}), data_dir=data_dir, now=FIRST_AT)
        summary, _ = self.collect(FakeMachine({"C": after}), data_dir=data_dir,
                                  now=SECOND_AT)
        return summary

    def drive_note(self, summary):
        notes = [item for item in self.not_checked(summary)
                 if str(item.get("what")).startswith(NOTE_PREFIX)]
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        self.assertIsInstance(notes[0].get("reason"), str, notes[0])
        return notes[0]

    # --- K6 -----------------------------------------------------------------------------

    def test_detail_failure_keeps_old_baseline(self):
        data_dir = self.data_dir()
        first, _ = self.collect(FakeMachine({"C": BEFORE}), data_dir=data_dir, now=FIRST_AT)
        detail = Path(first.get("detail_file"))
        self.assertEqual(detail.name, f"files-{stamp(FIRST_AT)}.detail.json", first)
        self.assertEqual(detail.parent.resolve(), (data_dir / "work").resolve())
        state = data_dir / "state"
        self.assertTrue((state / BASELINE).is_file(), f"{BASELINE} was not written")
        before = (state / BASELINE).read_bytes()
        self.assertEqual(list(state.glob("*.previous.json")), [],
                         "the first run left a .previous.json")

        # The same data directory, for the second run without the blocking directory.
        control_dir = data_dir.parent / "control"
        shutil.copytree(data_dir, control_dir)

        with self.subTest("detail file cannot be written"):
            blocker = data_dir / "work" / f"files-{stamp(SECOND_AT)}.detail.json"
            blocker.mkdir(parents=True)
            with self.assertRaises(OSError):
                self.run_main(data_dir, FakeMachine({"C": AFTER}), now=SECOND_AT)
            self.assertEqual((state / BASELINE).read_bytes(), before,
                             "the baseline changed although the detail file was not written")
            self.assertEqual([p.name for p in state.glob("*.previous.json")], [],
                             "a .previous.json was created")
            history = state / "history"
            second_day = SECOND_AT.date().isoformat()
            dated = ([p.name for p in history.iterdir() if second_day in p.name]
                     if history.is_dir() else [])
            self.assertEqual(dated, [], "a history copy of the second run was written")

        with self.subTest("the same run without the directory saves the baseline"):
            summary, _ = self.collect(FakeMachine({"C": AFTER}), data_dir=control_dir,
                                      now=SECOND_AT)
            info = summary.get("baseline")
            self.assertIsInstance(info, dict, summary)
            self.assertIs(info.get("saved"), True, info)
            saved = control_dir / "state" / BASELINE
            self.assertTrue(saved.is_file(), f"{BASELINE} was not written")
            self.assertNotEqual(saved.read_bytes(), before,
                                "the baseline of the second run was not saved")
            self.assertTrue(Path(summary.get("detail_file")).is_file(), summary)

    # --- K8 -----------------------------------------------------------------------------

    def test_note_names_moved_and_unlisted(self):
        with self.subTest("a large file moved: same size and creation time"):
            created = (NOW - timedelta(days=30)).timestamp()

            def tree(where):
                user = {"Downloads": {}, "Videos": {}}
                user[where]["film.iso"] = file(4 * GIB, ctime=created)
                return {"Users": {"a": user}}

            summary = self.two_runs(tree("Downloads"), tree("Videos"))
            note = self.drive_note(summary)
            self.assertIn("moved or renamed", note["reason"], note)
            # The note always lists every reason; the detail shows this one was applied.
            detail = self.detail(summary)
            moved = {item["path"].lower(): item["reason"] for item in detail["not_compared"]
                     if "film.iso" in item["path"].lower()}
            self.assertEqual(len(moved), 2, detail["not_compared"])
            for path, reason in moved.items():
                self.assertIn("looks moved or renamed", reason, path)
            self.assertFalse([c for c in detail["changes"]
                              if c.get("kind") in ("large_file_gone", "large_file_new")],
                             detail["changes"])

        with self.subTest("a new folder that could not be listed"):
            locked = r"C:\Data\Locked"
            before = {"Data": {"a.bin": 10}}
            after = {"Data": {"a.bin": 10,
                              "Locked": folder({"x.bin": 5}, error=denied(locked))}}
            summary = self.two_runs(before, after)
            note = self.drive_note(summary)
            self.assertIn("could not be listed", note["reason"], note)
            reasons = [item["reason"] for item in self.detail(summary)["not_compared"]
                       if item["path"].lower() == locked.lower()]
            self.assertEqual(len(reasons), 1, reasons)
            self.assertIn("could not be listed", reasons[0])


if __name__ == "__main__":
    unittest.main()

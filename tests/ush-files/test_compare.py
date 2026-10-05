"""Comparison tests for skills/ush-files/scripts/files.py (plan 096, M2): the first run,
each kind of change, unread parts that give no change, a drive absent in one run, the
elevated baseline, a corrupt baseline and a failed save.

The general interface is described in ``fakes.py``. Interface from the plan (M2):

- Baseline ``<data dir>/state/ush-files.json`` (``ush-files.elevated.json`` with
  administrator rights), read with ``baseline.load`` and written with ``baseline.save``.
- Sources per drive: ``folders:<letter>``, ``large_files:<letter>``, ``drives:<letter>``.
- Summary: ``comparison`` (the state of each source, ``previous_at``, ``age_days``),
  ``changes`` (ids ``d...``), ``baseline`` (shared shape), ``counts.not_compared``.
- A change has ``kind``, ``path``, ``drive``, ``depth``, ``before_bytes``,
  ``after_bytes``, ``delta_bytes``, ``delta_gb``, ``readable_part``;
  ``large_file_changed`` also ``before_modified`` and ``after_modified``. Changes are
  sorted by the absolute value of ``delta_bytes``, largest first.

Assumptions added by these tests beyond the plan text:

- ``summary["comparison"]`` maps each source name (``"folders:C"``; the letter may be
  upper or lower case) to its state string, either directly or under a ``sources`` key;
  a value may also be a dict with ``state``.
- The source names in the saved baseline (``sources``) are the same names, so the
  items of drive ``D`` are found under the names that end in ``:d`` (case-insensitive).
- A change's ``drive`` is the letter (``"C"`` or ``"C:"``).
- The depth of a large file is the depth of the file itself: ``C:\\vm.vhdx`` is 1 and
  ``C:\\New\\game\\big.bin`` is 3 (a folder ``C:\\Users`` is 1).
- ``folder_new`` has ``delta_bytes`` equal to the new folder's size, ``folder_gone``
  minus the old size; ``large_file_new`` and ``large_file_gone`` likewise.
- A ``not_checked`` item about a folder that was not compared names the folder's path
  or has the text "compar" in it; an item about the baseline has "baseline" in its text.
- An unreadable baseline still gives exit code 0.
- ``files`` imports the shared module as ``import baseline`` and calls
  ``baseline.save(...)``, so ``files.baseline.save`` can be patched; a save that returns
  a string returns the reason it was not saved.

Every tree and size is invented; nothing comes from a machine.
"""

import json
import unittest
from datetime import timedelta
from unittest import mock

from .fakes import (
    DRIVE_FIXED,
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_RECALL_ON_OPEN,
    FILE_ATTRIBUTE_REPARSE_POINT,
    GIB,
    IO_REPARSE_TAG_MOUNT_POINT,
    MTIME,
    NOW,
    FakeMachine,
    FilesTestCase,
    file,
    folder,
    norm,
)

Q = GIB // 4
BASELINE = "ush-files.json"
ELEVATED = "ush-files.elevated.json"
SOURCE_KINDS = ("folders", "large_files", "drives")
UNLISTED_REASON = "it could not be listed, so its size was not read"


def denied(path):
    return PermissionError(13, "Access is denied", path)


def letter_of(value):
    return str(value or "").rstrip(":\\").upper()


class TestCompare(FilesTestCase):
    # --- helpers ------------------------------------------------------------------------

    def comparison_states(self, summary):
        comparison = summary.get("comparison")
        self.assertIsInstance(comparison, dict, summary.get("comparison"))
        states = comparison.get("sources")
        if not isinstance(states, dict):
            states = comparison
        result = {}
        for name, value in states.items():
            if ":" not in str(name):
                continue
            if isinstance(value, dict):
                value = value.get("state", value.get("status"))
            kind, _, letter = str(name).partition(":")
            result[f"{kind}:{letter_of(letter)}"] = value
        return result

    def state_of(self, summary, kind, letter):
        states = self.comparison_states(summary)
        key = f"{kind}:{letter.upper()}"
        self.assertIn(key, states, summary.get("comparison"))
        return states[key]

    def changes(self, summary):
        return self.items(summary, "changes")

    def changes_at(self, changes, kind, path):
        return [c for c in changes if c.get("kind") == kind and norm(c.get("path")) == norm(path)]

    def changes_on_path(self, changes, path):
        return [c for c in changes if norm(c.get("path")) == norm(path)]

    def baseline_object(self, summary):
        value = summary.get("baseline")
        self.assertIsInstance(value, dict, summary)
        return value

    def saved_sources(self, data_dir, name=BASELINE):
        path = data_dir / "state" / name
        self.assertTrue(path.is_file(), f"{name} was not written")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data.get("sources"), dict, str(data)[:300])
        return data["sources"]

    def saved_drive_sources(self, sources, letter):
        """``{kind: items}`` of the saved sources of drive ``letter``."""
        result = {}
        for name, items in sources.items():
            kind, _, source_letter = str(name).partition(":")
            if letter_of(source_letter) == letter.upper():
                result[kind] = items
        return result

    def baseline_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if "baseline" in json.dumps(item).lower()]

    # --- K7 -----------------------------------------------------------------------------

    def test_first_run_then_clean(self):
        tree = {"Users": {"a": {"Docs": {"f.txt": 10}}}, "Data": {"big.bin": 2 * GIB}}
        data_dir = self.data_dir()

        first, _ = self.collect(FakeMachine({"C": tree}), data_dir=data_dir, now=NOW)
        with self.subTest("first run: no baseline"):
            for kind in SOURCE_KINDS:
                self.assertEqual(self.state_of(first, kind, "C"), "no_baseline",
                                 first.get("comparison"))
            self.assertEqual(self.changes(first), [])
            self.assertEqual(self.baseline_object(first).get("status"), "none")
            self.assertIs(self.baseline_object(first).get("saved"), True,
                          first.get("baseline"))
            self.assertTrue((data_dir / "state" / BASELINE).is_file())

        second, _ = self.collect(FakeMachine({"C": tree}), data_dir=data_dir,
                                 now=NOW + timedelta(days=1))
        with self.subTest("second run on the same tree: compared, no changes"):
            for kind in SOURCE_KINDS:
                self.assertEqual(self.state_of(second, kind, "C"), "compared",
                                 second.get("comparison"))
            self.assertEqual(self.changes(second), [])
            self.assertEqual(self.baseline_object(second).get("status"), "compared")

    # --- K8 -----------------------------------------------------------------------------

    def test_each_kind_of_change(self):
        # Sizes are chosen so that C:\, C:\Users and C:\Users\a keep the same bytes and
        # files in both runs, and every change has a different absolute delta.
        before = {
            "Users": {"a": {
                "Docs": {f"d{i}.bin": Q for i in range(1, 5)},
                "old.iso": 13 * Q,
            }},
            "Data": {"p1.bin": 2 * Q, "p2.bin": 3 * Q},
            "Old": {"old.dat": 2 * Q},
            "vm.vhdx": file(40 * Q, mtime=MTIME),
        }
        after = {
            "Users": {"a": {
                "Docs": {f"d{i}.bin": 3 * Q for i in range(1, 5)},
                "new.iso": 5 * Q,
            }},
            "Data": {"p1.bin": Q},
            "New": {"readme.txt": 1000, "game": {"big.bin": 24 * Q}},
            "vm.vhdx": file(22 * Q - 1000, mtime=MTIME + 86400),
        }
        used_before = 40 * GIB
        used_after = used_before + 3 * Q
        data_dir = self.data_dir()
        self.collect(FakeMachine({"C": before},
                                 usage={"C": (100 * GIB, used_before, 100 * GIB - used_before)}),
                     data_dir=data_dir, now=NOW)
        summary, _ = self.collect(
            FakeMachine({"C": after},
                        usage={"C": (100 * GIB, used_after, 100 * GIB - used_after)}),
            data_dir=data_dir, now=NOW + timedelta(days=1))
        changes = self.changes(summary)

        expected = [
            ("folder_new", r"C:\New", 24 * Q + 1000, 1),
            ("large_file_new", r"C:\New\game\big.bin", 24 * Q, 3),
            ("large_file_changed", r"C:\vm.vhdx", -(18 * Q + 1000), 1),
            ("large_file_gone", r"C:\Users\a\old.iso", -13 * Q, 3),
            ("folder_grew", r"C:\Users\a\Docs", 8 * Q, 3),
            ("large_file_new", r"C:\Users\a\new.iso", 5 * Q, 3),
            ("folder_shrank", r"C:\Data", -4 * Q, 1),
            ("drive_used_changed", None, 3 * Q, None),
            ("folder_gone", r"C:\Old", -2 * Q, 1),
        ]

        with self.subTest("one change per expected item, nothing else"):
            got = [(c.get("kind"),
                    None if c.get("kind") == "drive_used_changed" else norm(c.get("path")))
                   for c in changes]
            want = [(kind, None if path is None else norm(path))
                    for kind, path, _, _ in expected]
            self.assertEqual(sorted(got, key=str), sorted(want, key=str), changes)

        with self.subTest("sorted by absolute delta"):
            kinds_in_order = [c.get("kind") for c in changes]
            self.assertEqual(kinds_in_order, [kind for kind, _, _, _ in expected], changes)

        with self.subTest("delta_bytes, path, drive, depth"):
            for kind, path, delta, depth in expected:
                if path is None:
                    matches = [c for c in changes if c.get("kind") == kind]
                else:
                    matches = self.changes_at(changes, kind, path)
                self.assertEqual(len(matches), 1, (kind, path, changes))
                change = matches[0]
                self.assertEqual(change.get("delta_bytes"), delta, change)
                for key in ("path", "drive", "depth"):
                    self.assertIn(key, change, change)
                self.assertEqual(letter_of(change.get("drive")), "C", change)
                if depth is not None:
                    self.assertEqual(change.get("depth"), depth, change)

        with self.subTest("before and after"):
            docs = self.changes_at(changes, "folder_grew", r"C:\Users\a\Docs")[0]
            self.assertEqual(docs.get("before_bytes"), 4 * Q, docs)
            self.assertEqual(docs.get("after_bytes"), 12 * Q, docs)
            data = self.changes_at(changes, "folder_shrank", r"C:\Data")[0]
            self.assertEqual(data.get("before_bytes"), 5 * Q, data)
            self.assertEqual(data.get("after_bytes"), Q, data)
            drive = next(c for c in changes if c.get("kind") == "drive_used_changed")
            self.assertEqual(drive.get("before_bytes"), used_before, drive)
            self.assertEqual(drive.get("after_bytes"), used_after, drive)
            vm = self.changes_at(changes, "large_file_changed", r"C:\vm.vhdx")[0]
            self.assertEqual(vm.get("before_bytes"), 40 * Q, vm)
            self.assertEqual(vm.get("after_bytes"), 22 * Q - 1000, vm)
            self.assertIn("before_modified", vm)
            self.assertIn("after_modified", vm)
            self.assertNotEqual(vm.get("before_modified"), vm.get("after_modified"), vm)

        with self.subTest("a folder inside a new folder is not new again"):
            self.assertEqual(self.changes_on_path(changes, r"C:\New\game"), [], changes)
            self.assertEqual(self.counts(summary).get("not_compared"), 0,
                             self.counts(summary))

    # --- K9 -----------------------------------------------------------------------------

    def test_unread_gives_no_change(self):
        docs_locked = r"C:\Users\a\Docs\Locked"
        proj = r"C:\Data\Proj"
        vault = r"C:\Archive\Vault"
        users_b = r"C:\Users\b"
        games_locked = r"C:\Users\a\Games\Locked2"
        secret = r"C:\Windows\Secret"

        def tree(second):
            docs = {f"d{i}.bin": (3 * Q if second else Q) for i in range(1, 5)}
            docs["Locked"] = folder({"in.bin": 5}, error=denied(docs_locked))
            games = {"Lib": {"big.pak": file(12 * Q, mtime=MTIME)}}
            if second:
                games["Locked2"] = folder({}, error=denied(games_locked))
            proj_children = {"cache": {"c.bin": 100}, "blob.bin": 2 * GIB}
            b_children = {f"v{i}.bin": 2 * Q for i in range(10)}
            vault_children = {"y2026": {"r.bin": 10}}
            windows = {"System32": {"k.dll": 100}}
            if second:
                windows["Secret"] = folder({}, error=denied(secret))
            result = {
                "Users": {
                    "a": {"Docs": docs, "Games": games},
                    "b": (folder(b_children, error=denied(users_b)) if second
                          else b_children),
                },
                "Data": {
                    "keep.bin": 1000,
                    "Proj": (folder(proj_children, error=denied(proj)) if second
                             else proj_children),
                },
                "Archive": {
                    "Vault": (vault_children if second
                              else folder(vault_children, error=denied(vault))),
                },
                "Windows": windows,
            }
            if second:
                result["New"] = {"n.txt": 50}
            return result

        data_dir = self.data_dir()
        self.collect(FakeMachine({"C": tree(False)}), data_dir=data_dir, now=NOW)
        summary, _ = self.collect(FakeMachine({"C": tree(True)}), data_dir=data_dir,
                                  now=NOW + timedelta(days=1))
        changes = self.changes(summary)

        with self.subTest("same unreadable subfolder: the readable part is compared"):
            grew = self.changes_at(changes, "folder_grew", r"C:\Users\a\Docs")
            self.assertEqual(len(grew), 1, changes)
            self.assertEqual(grew[0].get("delta_bytes"), 2 * GIB, grew[0])
            self.assertIs(grew[0].get("readable_part"), True, grew[0])

        with self.subTest("new unreadable subfolder: not compared"):
            self.assertEqual(self.changes_on_path(changes, r"C:\Data"), [], changes)
            not_compared = self.counts(summary).get("not_compared")
            self.assertIsInstance(not_compared, int, self.counts(summary))
            self.assertGreaterEqual(not_compared, 1, self.counts(summary))
            notes = [item for item in self.not_checked(summary)
                     if "compar" in json.dumps(item).lower()
                     or any(norm(v) == norm(r"C:\Data")
                            for v in item.values() if isinstance(v, str))]
            self.assertTrue(notes, self.not_checked(summary))

        with self.subTest("children of a folder that became unreadable"):
            self.assertEqual(self.changes_at(changes, "folder_gone", r"C:\Data\Proj\cache"),
                             [], changes)
            self.assertEqual(
                self.changes_at(changes, "large_file_gone", r"C:\Data\Proj\blob.bin"),
                [], changes)

        with self.subTest("children of a folder unreadable before"):
            self.assertEqual(
                self.changes_at(changes, "folder_new", r"C:\Archive\Vault\y2026"),
                [], changes)

        with self.subTest("a 5 GiB folder that became unreadable"):
            self.assertEqual(self.changes_at(changes, "folder_shrank", users_b), [], changes)
            self.assertEqual(self.changes_at(changes, "folder_gone", users_b), [], changes)

        with self.subTest("a new unreadable folder does not block a new sibling tree"):
            self.assertEqual(len(self.changes_at(changes, "folder_new", r"C:\New")), 1,
                             changes)

        with self.subTest("same large file under another parent_key"):
            self.assertEqual(
                self.changes_on_path(changes, r"C:\Users\a\Games\Lib\big.pak"), [], changes)

    # --- K10 ----------------------------------------------------------------------------

    def test_absent_drive_carried_over(self):
        c_tree = {"Data": {"a.bin": 10}}
        d_tree = {"Media": {"film.mkv": 2 * GIB, "x": {"y.bin": 10}}, "top.bin": 3}
        usage = {"C": (100 * GIB, 40 * GIB, 60 * GIB), "D": (200 * GIB, 50 * GIB, 150 * GIB)}
        data_dir = self.data_dir()

        self.collect(FakeMachine({"C": c_tree, "D": d_tree}, usage=usage),
                     data_dir=data_dir, now=NOW)
        first_d = self.saved_drive_sources(self.saved_sources(data_dir), "D")
        self.assertEqual(sorted(first_d), sorted(SOURCE_KINDS), first_d.keys())
        for kind in SOURCE_KINDS:
            self.assertTrue(first_d[kind], f"no {kind} items of D in the first baseline")

        summary, _ = self.collect(
            FakeMachine({"C": c_tree}, drives=[("C", DRIVE_FIXED)], usage=usage),
            data_dir=data_dir, now=NOW + timedelta(days=1))

        with self.subTest("D is not read"):
            for kind in SOURCE_KINDS:
                self.assertEqual(self.state_of(summary, kind, "D"), "not_read",
                                 summary.get("comparison"))
            self.assertTrue(self.notes_about_drive(summary, "D"), self.not_checked(summary))
            on_d = [c for c in self.changes(summary)
                    if letter_of(c.get("drive")) == "D" or norm(c.get("path")).startswith("d:")]
            self.assertEqual(on_d, [], self.changes(summary))

        with self.subTest("the baseline keeps every item of D"):
            second_d = self.saved_drive_sources(self.saved_sources(data_dir), "D")
            for kind in SOURCE_KINDS:
                self.assertEqual(second_d.get(kind), first_d[kind], kind)

        third, _ = self.collect(FakeMachine({"C": c_tree, "D": d_tree}, usage=usage),
                                data_dir=data_dir, now=NOW + timedelta(days=2))
        with self.subTest("D is back"):
            for kind in SOURCE_KINDS:
                self.assertEqual(self.state_of(third, kind, "D"), "compared",
                                 third.get("comparison"))
            new = [c for c in self.changes(third)
                   if c.get("kind") in ("folder_new", "large_file_new")]
            self.assertEqual(new, [], self.changes(third))

    # --- K11 ----------------------------------------------------------------------------

    def test_elevated_and_failed_save(self):
        tree = {"Data": {"big.bin": 2 * GIB, "a.bin": 10}}

        with self.subTest("elevated run uses its own baseline"):
            data_dir = self.data_dir()
            self.collect(FakeMachine({"C": tree}), data_dir=data_dir, now=NOW)
            normal = data_dir / "state" / BASELINE
            self.assertTrue(normal.is_file())
            normal_bytes = normal.read_bytes()

            first, _ = self.collect(FakeMachine({"C": tree}, admin=True),
                                    data_dir=data_dir, now=NOW + timedelta(hours=1))
            self.assertEqual(self.baseline_object(first).get("status"), "none",
                             first.get("baseline"))
            self.assertTrue((data_dir / "state" / ELEVATED).is_file())
            self.assertEqual(normal.read_bytes(), normal_bytes)

            second, _ = self.collect(FakeMachine({"C": tree}, admin=True),
                                     data_dir=data_dir, now=NOW + timedelta(hours=2))
            self.assertEqual(self.baseline_object(second).get("status"), "compared",
                             second.get("baseline"))
            for kind in SOURCE_KINDS:
                self.assertEqual(self.state_of(second, kind, "C"), "compared",
                                 second.get("comparison"))
            self.assertEqual(normal.read_bytes(), normal_bytes)

        with self.subTest("corrupt baseline"):
            data_dir = self.data_dir()
            state = data_dir / "state"
            state.mkdir(parents=True)
            corrupt = '{"schema_version": 1, "sources": {'
            (state / BASELINE).write_text(corrupt, encoding="utf-8")

            summary, _ = self.collect(FakeMachine({"C": tree}), data_dir=data_dir, now=NOW)
            base = self.baseline_object(summary)
            self.assertEqual(base.get("status"), "unreadable", base)
            self.assertTrue(base.get("reason"), base)
            notes = self.baseline_notes(summary)
            self.assertTrue(notes, self.not_checked(summary))
            self.assertTrue(any(str(item.get("reason") or "").strip() for item in notes),
                            notes)
            copies = sorted(state.glob("ush-files.unreadable-*"))
            self.assertEqual(len(copies), 1, [p.name for p in state.iterdir()])
            self.assertEqual(copies[0].read_text(encoding="utf-8"), corrupt)

        with self.subTest("save returns a reason"):
            data_dir = self.data_dir()
            with mock.patch.object(self.files.baseline, "save",
                                   return_value="invented reason"):
                code, stdout, stderr = self.run_main(data_dir, FakeMachine({"C": tree}))
            self.assertEqual(code, 0, stderr[-500:])
            summary = self.parse(stdout)
            self.assertIsInstance(summary, dict, stdout[:300])
            self.assertTrue(any("invented reason" in json.dumps(item)
                                for item in self.not_checked(summary)),
                            self.not_checked(summary))
            self.assertIs(self.baseline_object(summary).get("saved"), False,
                          summary.get("baseline"))

    # --- review fixes (M2) --------------------------------------------------------------

    def not_compared_paths(self, summary):
        return {norm(item.get("path"))
                for item in self.items(self.detail(summary), "not_compared")}

    def test_skipped_folder_on_path_gives_no_large_file_change(self):
        # Folders skipped (junction, cloud only) in one run only, at depth 2, at depth 3
        # and below depth 3, each above a large file deeper than the folder records.
        def junction(children):
            return folder(children,
                          attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
                          reparse_tag=IO_REPARSE_TAG_MOUNT_POINT)

        def cloud(children):
            return folder(children,
                          attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_RECALL_ON_OPEN)

        def tree(second):
            one_drive = {"Videos": {"2025": {"x.mkv": 2 * GIB}}}
            cloud_dir = {"Photos": {"p.raw": 2 * GIB}}
            old = {"y.mkv": 2 * GIB}
            arch = {"z.mkv": 2 * GIB}
            b_dir = {"Docs": {"Old": {"w.mkv": 2 * GIB}}}
            season = {"keep.mkv": 2 * GIB}
            if second:
                season["n.mkv"] = 3 * GIB  # a real new file: still found
            return {
                "Users": {
                    "a": {
                        "OneDrive": junction(one_drive) if second else one_drive,
                        "Cloud": cloud_dir if second else cloud(cloud_dir),
                    },
                    "b": junction(b_dir) if second else b_dir,
                },
                "Data": {"Media": {
                    "Films": {
                        "Old": cloud(old) if second else old,
                        "Arch": arch if second else junction(arch),
                    },
                    "Shows": {"Season": season},
                }},
            }

        quiet = (
            r"C:\Users\a\OneDrive\Videos\2025\x.mkv",  # depth 3 skipped in run 2
            r"C:\Data\Media\Films\Old\y.mkv",  # depth 4 skipped in run 2
            r"C:\Users\b\Docs\Old\w.mkv",  # depth 2 skipped in run 2
            r"C:\Users\a\Cloud\Photos\p.raw",  # depth 3 skipped in run 1
            r"C:\Data\Media\Films\Arch\z.mkv",  # depth 4 skipped in run 1
        )
        data_dir = self.data_dir()
        self.collect(FakeMachine({"C": tree(False)}), data_dir=data_dir, now=NOW)
        summary, _ = self.collect(FakeMachine({"C": tree(True)}), data_dir=data_dir,
                                  now=NOW + timedelta(days=1))
        changes = self.changes(summary)
        not_compared = self.not_compared_paths(summary)

        for path in quiet:
            with self.subTest(path=path):
                self.assertEqual(self.changes_on_path(changes, path), [], changes)
                self.assertIn(norm(path), not_compared, sorted(not_compared))
        with self.subTest("a new file under folders listed in both runs is still new"):
            self.assertEqual(len(self.changes_at(
                changes, "large_file_new", r"C:\Data\Media\Shows\Season\n.mkv")), 1,
                changes)
        with self.subTest("no folder size change from a folder skipped in one run only"):
            # Only C:\Data\Media\Shows really grew; every other folder holding a
            # directory skipped in one run only has sizes that are not comparable.
            sized = {norm(c.get("path")) for c in changes
                     if c.get("kind") in ("folder_grew", "folder_shrank")}
            self.assertEqual(sized, {norm(r"C:\Data\Media\Shows")}, changes)

    def test_file_grown_past_threshold_is_not_new(self):
        # mail.ost was created before run 1 and is below the threshold then; in run 2 it
        # is above it. fresh.ost was created after run 1.
        before_run_1 = (NOW - timedelta(days=30)).timestamp()
        after_run_1 = (NOW + timedelta(hours=12)).timestamp()
        grown = r"C:\Data\mail.ost"
        fresh = r"C:\Data\fresh.ost"

        def tree(second):
            size = GIB + GIB // 50 if second else GIB - GIB // 50
            data = {"mail.ost": file(size, ctime=before_run_1)}
            if second:
                data["fresh.ost"] = file(2 * GIB, ctime=after_run_1)
            return {"Data": data}

        data_dir = self.data_dir()
        self.collect(FakeMachine({"C": tree(False)}), data_dir=data_dir, now=NOW)
        summary, _ = self.collect(FakeMachine({"C": tree(True)}), data_dir=data_dir,
                                  now=NOW + timedelta(days=1))
        changes = self.changes(summary)
        with self.subTest("created before run 1: no change, not compared"):
            self.assertEqual(self.changes_on_path(changes, grown), [], changes)
            self.assertIn(norm(grown), self.not_compared_paths(summary))
        with self.subTest("created after run 1: still new"):
            self.assertEqual(len(self.changes_at(changes, "large_file_new", fresh)), 1,
                             changes)
            self.assertNotIn(norm(fresh), self.not_compared_paths(summary))
        with self.subTest("the large-file item keeps its creation time"):
            large = {norm(f.get("path")): f
                     for f in self.items(self.detail(summary), "large_files")}
            self.assertEqual(large[norm(grown)].get("created"),
                             (NOW - timedelta(days=30)).isoformat(timespec="seconds"))

    def test_skipped_folder_new_or_gone_gives_no_folder_change(self):
        # A new junction C:\Games and a cloud-only folder C:\Users\a\Cloud removed in
        # run 2 have no size that was read; C:\Extra is a real new folder.
        junction = folder({"g.bin": 10},
                          attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
                          reparse_tag=IO_REPARSE_TAG_MOUNT_POINT)
        cloud = folder({"p.raw": 10},
                       attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_RECALL_ON_OPEN)
        before = {"Users": {"a": {"Docs": {"d.txt": 10}, "Cloud": cloud}}}
        after = {"Users": {"a": {"Docs": {"d.txt": 10}}}, "Games": junction,
                 "Extra": {"e.bin": 3 * Q}}
        data_dir = self.data_dir()
        self.collect(FakeMachine({"C": before}), data_dir=data_dir, now=NOW)
        summary, _ = self.collect(FakeMachine({"C": after}), data_dir=data_dir,
                                  now=NOW + timedelta(days=1))
        changes = self.changes(summary)
        not_compared = self.not_compared_paths(summary)
        for kind, path in (("folder_new", r"C:\Games"), ("folder_gone", r"C:\Users\a\Cloud")):
            with self.subTest(path=path):
                self.assertEqual(self.changes_at(changes, kind, path), [], changes)
                self.assertEqual(self.changes_on_path(changes, path), [], changes)
                self.assertIn(norm(path), not_compared, sorted(not_compared))
        with self.subTest("a real new folder next to them is still new"):
            self.assertEqual(len(self.changes_at(changes, "folder_new", r"C:\Extra")), 1,
                             changes)

    def test_scan_settings_changed(self):
        tree = {"Users": {"a": {"Docs": {"d.bin": 10}}},
                "Data": {"mid.bin": 3 * Q, "big.bin": 2 * GIB}}

        def settings_notes(summary):
            return [item for item in self.not_checked(summary)
                    if "scan settings changed" in json.dumps(item).lower()]

        for label, overrides, held, kept in (
                ("depth 3 to 2", {"depth": 2}, ["folders"], ["large_files"]),
                ("threshold lowered", {"large_file_bytes": GIB // 2}, ["large_files"],
                 ["folders"]),
                ("both", {"depth": 2, "large_file_bytes": GIB // 2},
                 ["folders", "large_files"], [])):
            with self.subTest(label):
                data_dir = self.data_dir()
                self.collect(FakeMachine({"C": tree}), data_dir=data_dir, now=NOW,
                             scan=self.scan_file())
                summary, _ = self.collect(FakeMachine({"C": tree}), data_dir=data_dir,
                                          now=NOW + timedelta(days=1),
                                          scan=self.scan_file(**overrides))
                self.assertEqual(self.changes(summary), [])
                for kind in held:
                    self.assertNotEqual(self.state_of(summary, kind, "C"), "compared",
                                        summary.get("comparison"))
                for kind in kept + ["drives"]:
                    self.assertEqual(self.state_of(summary, kind, "C"), "compared",
                                     summary.get("comparison"))
                self.assertEqual(len(settings_notes(summary)), 1, self.not_checked(summary))

                third, _ = self.collect(FakeMachine({"C": tree}), data_dir=data_dir,
                                        now=NOW + timedelta(days=2),
                                        scan=self.scan_file(**overrides))
                for kind in SOURCE_KINDS:
                    self.assertEqual(self.state_of(third, kind, "C"), "compared",
                                     third.get("comparison"))
                self.assertEqual(settings_notes(third), [], self.not_checked(third))

        with self.subTest("a baseline without saved settings is compared as before"):
            data_dir = self.data_dir()
            self.collect(FakeMachine({"C": tree}), data_dir=data_dir, now=NOW,
                         scan=self.scan_file())
            path = data_dir / "state" / BASELINE
            data = json.loads(path.read_text(encoding="utf-8"))
            for name in [n for n in data["sources"] if ":" not in n]:
                del data["sources"][name]
            path.write_text(json.dumps(data), encoding="utf-8")
            summary, _ = self.collect(FakeMachine({"C": tree}), data_dir=data_dir,
                                      now=NOW + timedelta(days=1),
                                      scan=self.scan_file(large_file_bytes=GIB // 2))
            self.assertEqual(self.state_of(summary, "large_files", "C"), "compared")
            self.assertEqual(settings_notes(summary), [], self.not_checked(summary))
            self.assertEqual(len(self.changes_at(self.changes(summary), "large_file_new",
                                                 r"C:\Data\mid.bin")), 1,
                             self.changes(summary))

    def test_malformed_baseline_item_is_not_compared(self):
        tree = {"Data": {"big.bin": 2 * GIB, "a.bin": 10}, "Other": {"o.bin": 5}}

        def folder_bytes_null(items):
            items["c:\\data"]["bytes"] = None

        def folder_files_text(items):
            items["c:\\other"]["files"] = "many"

        def folder_without_path(items):
            items["c:\\ghost"] = {"depth": 1, "bytes": 5, "files": 1, "listed": True}

        def large_bytes_text(items):
            items["c:\\data\\big.bin"]["bytes"] = "2 GiB"

        def large_without_path(items):
            items["c:\\data\\ghost.bin"] = {"depth": 2, "bytes": 3 * GIB, "modified": None}

        for kind, edit, path in (
                ("folders", folder_bytes_null, r"C:\Data"),
                ("folders", folder_files_text, r"C:\Other"),
                ("folders", folder_without_path, r"c:\ghost"),
                ("large_files", large_bytes_text, r"C:\Data\big.bin"),
                ("large_files", large_without_path, r"c:\data\ghost.bin")):
            with self.subTest(edit.__name__):
                data_dir = self.data_dir()
                self.collect(FakeMachine({"C": tree}), data_dir=data_dir, now=NOW)
                state = data_dir / "state" / BASELINE
                data = json.loads(state.read_text(encoding="utf-8"))
                edit(data["sources"][f"{kind}:C"])
                state.write_text(json.dumps(data), encoding="utf-8")

                code, stdout, stderr = self.run_main(data_dir, FakeMachine({"C": tree}),
                                                     now=NOW + timedelta(days=1))
                self.assertEqual(code, 0, stderr[-800:])
                summary = self.parse(stdout)
                self.assertEqual(self.baseline_object(summary).get("status"), "compared")
                self.assertEqual(self.changes(summary), [])
                self.assertEqual(self.counts(summary).get("not_compared"), 1,
                                 self.counts(summary))
                self.assertIn(norm(path), self.not_compared_paths(summary))
                self.assertTrue(any("malformed" in json.dumps(item)
                                    for item in self.not_checked(summary)),
                                self.not_checked(summary))

    # --- final review, round 1 ----------------------------------------------------------

    def two_runs(self, before, after):
        """Run ``before`` then ``after`` on drive C: one day apart; return the second
        summary."""
        data_dir = self.data_dir()
        self.collect(FakeMachine({"C": before}), data_dir=data_dir, now=NOW)
        summary, _ = self.collect(FakeMachine({"C": after}), data_dir=data_dir,
                                  now=NOW + timedelta(days=1))
        return summary

    def test_small_change_has_delta_mb(self):
        """A change under 50 MB reads 0.0 in delta_gb; delta_mb carries it, signed."""
        grown = 12345678  # 11.77 MiB
        for name, before, after, want in (
                ("grew", {"Data": {"a.bin": 10}}, {"Data": {"a.bin": 10 + grown}}, 11.8),
                ("shrank", {"Data": {"a.bin": 10 + grown}}, {"Data": {"a.bin": 10}}, -11.8)):
            with self.subTest(name):
                changes = self.changes(self.two_runs(before, after))
                kind = f"folder_{name}"
                found = self.changes_at(changes, kind, r"C:\Data")
                self.assertEqual(len(found), 1, changes)
                self.assertEqual(found[0].get("delta_gb"), 0.0, found[0])
                self.assertEqual(found[0].get("delta_mb"), want, found[0])
                for change in changes:
                    self.assertIn("delta_mb", change, change)

    def test_unlisted_folder_new_or_gone_gives_no_change(self):
        """A new or gone folder whose own listing failed has no size that was read."""
        locked = r"C:\Data\Locked"
        plain = {"a.bin": 10}
        with_locked = {"a.bin": 10, "Locked": folder({"x.bin": 5}, error=denied(locked))}
        for kind, before, after in (("folder_new", plain, with_locked),
                                    ("folder_gone", with_locked, plain)):
            with self.subTest(kind):
                summary = self.two_runs({"Data": dict(before)}, {"Data": dict(after)})
                changes = self.changes(summary)
                self.assertEqual(self.changes_on_path(changes, locked), [], changes)
                not_compared = self.items(self.detail(summary), "not_compared")
                reasons = [item.get("reason") for item in not_compared
                           if norm(item.get("path")) == norm(locked)]
                self.assertEqual(reasons, [UNLISTED_REASON], not_compared)

    def test_one_hour_shift_of_large_file_is_no_change(self):
        """Same bytes and a modified time moved by exactly one hour (FAT after a
        daylight-saving switch): no change. A real change still is one."""
        vm = r"C:\vm.vhdx"
        cases = (
            ("plus one hour", 2 * GIB, MTIME + 3600, False),
            ("minus one hour", 2 * GIB, MTIME - 3600, False),
            ("one hour and a second", 2 * GIB, MTIME + 3601, True),
            ("one hour and other bytes", 2 * GIB + 1, MTIME + 3600, True),
        )
        for name, size, mtime, changed in cases:
            with self.subTest(name):
                summary = self.two_runs({"vm.vhdx": file(2 * GIB, mtime=MTIME)},
                                        {"vm.vhdx": file(size, mtime=mtime)})
                found = self.changes_at(self.changes(summary), "large_file_changed", vm)
                self.assertEqual(len(found), 1 if changed else 0, self.changes(summary))
                self.assertNotIn(norm(vm), self.not_compared_paths(summary))

    def test_moved_large_file_is_not_gone(self):
        """A large file moved from Downloads to Videos keeps its size and creation time:
        no large_file_gone (a file still on the disk is not freed space) and no
        large_file_new; both paths are not compared. A gone file whose only candidate
        has another size is still gone."""
        created = (NOW - timedelta(days=30)).timestamp()
        old = r"C:\Users\a\Downloads\film.iso"
        new = r"C:\Users\a\Videos\film.iso"

        def tree(where, size):
            user = {"Downloads": {}, "Videos": {}}
            user[where]["film.iso"] = file(size, ctime=created)
            return {"Users": {"a": user}}

        with self.subTest("moved: same bytes and creation time"):
            summary = self.two_runs(tree("Downloads", 4 * GIB), tree("Videos", 4 * GIB))
            changes = self.changes(summary)
            self.assertEqual(self.changes_at(changes, "large_file_gone", old), [], changes)
            self.assertEqual(self.changes_at(changes, "large_file_new", new), [], changes)
            self.assertEqual(self.changes_on_path(changes, old), [], changes)
            self.assertEqual(self.changes_on_path(changes, new), [], changes)
            reasons = {norm(item.get("path")): item.get("reason")
                       for item in self.items(self.detail(summary), "not_compared")}
            self.assertIn(norm(old), reasons, reasons)
            self.assertIn(norm(new), reasons, reasons)
            self.assertIn("moved or renamed", reasons[norm(old)])
            self.assertIn(new, reasons[norm(old)])
            self.assertIn(old, reasons[norm(new)])

        with self.subTest("another size: still gone"):
            summary = self.two_runs(tree("Downloads", 4 * GIB), tree("Videos", 5 * GIB))
            changes = self.changes(summary)
            gone = self.changes_at(changes, "large_file_gone", old)
            self.assertEqual(len(gone), 1, changes)
            self.assertEqual(gone[0].get("delta_bytes"), -4 * GIB, gone)
            self.assertNotIn(norm(old), self.not_compared_paths(summary))


if __name__ == "__main__":
    unittest.main()

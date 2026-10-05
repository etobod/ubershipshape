"""Traversal tests for skills/ush-files/scripts/files.py (plan 096, M1): sizes rolled up
to depth 3, reparse points and cloud placeholders, unreadable directories, large files
and fixed drives.

The interface and the assumptions are described in ``fakes.py``. Every tree is
invented; nothing comes from a machine.
"""

import json
import re
import unittest

from .fakes import (
    DRIVE_FIXED,
    DRIVE_REMOVABLE,
    FILE_ATTRIBUTE_ARCHIVE,
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_ATTRIBUTE_SYSTEM,
    IO_REPARSE_TAG_CLOUD_6,
    IO_REPARSE_TAG_MOUNT_POINT,
    FakeMachine,
    FilesTestCase,
    file,
    folder,
    norm,
)

SVI = r"C:\System Volume Information"
GONE = r"C:\Users\a\AppData\Local\Temp\gone"


def mentions_count_one(item):
    """True when a not_checked item carries the count 1 (a field or the text)."""
    for value in item.values():
        if isinstance(value, int) and not isinstance(value, bool) and value == 1:
            return True
    return re.search(r"(?<![\d.])1(?![\d.])", json.dumps(item)) is not None


class TestScan(FilesTestCase):
    def test_sizes_roll_up_to_depth(self):
        tree = {
            "Users": {
                "a": {
                    "Docs": {
                        "f.txt": 10,
                        "deep": {"x": {"y.bin": 5}},
                    },
                },
            },
        }
        fake = FakeMachine({"C": tree})
        summary, _ = self.collect(fake)  # the shipped data/scan.json: depth 3
        folders = self.items(self.detail(summary), "folders")

        docs = self.folder_at(folders, r"C:\Users\a\Docs")
        self.assertEqual(docs.get("depth"), 3, docs)
        self.assertEqual(docs.get("bytes"), 15, docs)
        self.assertEqual(docs.get("files"), 2, docs)

        users = self.folder_at(folders, r"C:\Users")
        self.assertEqual(users.get("bytes"), 15, users)

        too_deep = [f for f in folders
                    if not isinstance(f.get("depth"), int) or f.get("depth") > 3]
        self.assertEqual(too_deep, [], "folders deeper than 3 in the detail file")
        paths = {norm(f.get("path")) for f in folders}
        self.assertNotIn(norm(r"C:\Users\a\Docs\deep"), paths)
        self.assertNotIn(norm(r"C:\Users\a\Docs\deep\x"), paths)

    def test_reparse_and_cloud_only(self):
        junction = folder(
            {"inside.bin": 50},
            attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
            reparse_tag=IO_REPARSE_TAG_MOUNT_POINT,
        )
        onedrive = folder(
            {
                "cloud.docx": file(
                    1000,
                    attributes=(FILE_ATTRIBUTE_ARCHIVE | FILE_ATTRIBUTE_REPARSE_POINT
                                | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS),
                    reparse_tag=IO_REPARSE_TAG_CLOUD_6,
                ),
                "offline.dat": file(2000, attributes=FILE_ATTRIBUTE_ARCHIVE
                                    | FILE_ATTRIBUTE_OFFLINE),
                "local.txt": file(7, attributes=FILE_ATTRIBUTE_ARCHIVE
                                  | FILE_ATTRIBUTE_REPARSE_POINT,
                                  reparse_tag=IO_REPARSE_TAG_CLOUD_6),
            },
            attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
            reparse_tag=IO_REPARSE_TAG_CLOUD_6,
        )
        tree = {"Users": {"Linked": junction, "a": {"OneDrive": onedrive}}}
        fake = FakeMachine({"C": tree})
        summary, _ = self.collect(fake)
        folders = self.items(self.detail(summary), "folders")

        with self.subTest("junction is not entered"):
            self.assertNotIn(norm(r"C:\Users\Linked"), fake.calls)
            self.assertEqual(self.counts(summary).get("reparse_skipped"), 1,
                             self.counts(summary))
            linked = self.folder_at(folders, r"C:\Users\Linked")
            self.assertEqual(linked.get("depth"), 2, linked)
            self.assertIs(linked.get("listed"), False, linked)
            self.assertEqual(linked.get("skipped"), "reparse", linked)
            self.assertEqual(linked.get("bytes"), 0, linked)

        with self.subTest("OneDrive folder is entered; placeholders are not counted"):
            self.assertIn(norm(r"C:\Users\a\OneDrive"), fake.calls)
            one = self.folder_at(folders, r"C:\Users\a\OneDrive")
            self.assertEqual(one.get("cloud_only_files"), 2, one)
            self.assertEqual(one.get("bytes"), 7, one)

    def test_unreadable_is_not_empty(self):
        denied = PermissionError(13, "Access is denied", SVI)
        vanished = FileNotFoundError(2, "The system cannot find the path specified", GONE)
        tree = {
            "System Volume Information": folder(
                {},
                attributes=(FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_HIDDEN
                            | FILE_ATTRIBUTE_SYSTEM),
                error=denied,
            ),
            "Users": {
                "a": {
                    "AppData": {
                        "Local": {
                            "Temp": {"gone": folder({}, error=vanished), "keep.tmp": 4},
                        },
                    },
                },
            },
        }
        fake = FakeMachine({"C": tree})
        summary, _ = self.collect(fake)
        detail = self.detail(summary)
        folders = self.items(detail, "folders")

        with self.subTest("denied directory"):
            svi = self.folder_at(folders, SVI)
            self.assertIs(svi.get("listed"), False, svi)
            self.assertEqual(svi.get("unreadable_dirs"), 1, svi)
            self.assertIs(svi.get("readable_part"), True, svi)
            self.assertEqual(svi.get("bytes"), 0, svi)
            self.assertIsNotNone(svi.get("unreadable_key"), svi)

        with self.subTest("root and drive count it"):
            root = self.folder_at(folders, "C:\\")
            self.assertEqual(root.get("unreadable_dirs"), 1, root)
            self.assertIs(root.get("readable_part"), True, root)
            self.assertIsNotNone(root.get("unreadable_key"), root)
            drive = self.drive_item(summary, "C")
            self.assertEqual(drive.get("unreadable_dirs"), 1, drive)

        with self.subTest("vanished directory is not unreadable"):
            self.assertEqual(self.counts(summary).get("vanished_dirs"), 1,
                             self.counts(summary))
            users = self.folder_at(folders, r"C:\Users")
            self.assertIn("unreadable_key", users)
            self.assertIsNone(users.get("unreadable_key"), users)

        with self.subTest("not_checked and detail unreadable"):
            notes = self.notes_about_drive(summary, "C")
            self.assertTrue(any(mentions_count_one(item) for item in notes),
                            self.not_checked(summary))
            unreadable = self.items(detail, "unreadable")
            self.assertIn(norm(SVI), {norm(u.get("path")) for u in unreadable}, unreadable)
            self.assertNotIn(norm(GONE), {norm(u.get("path")) for u in unreadable},
                             unreadable)

        with self.subTest("clean tree"):
            clean = {"Users": {"a": {"Docs": {"f.txt": 10}}}, "Data": {"b.bin": 3}}
            summary, _ = self.collect(FakeMachine({"C": clean}))
            self.assertEqual(self.notes_about_drive(summary, "C"), [],
                             self.not_checked(summary))
            for item in self.items(self.detail(summary), "folders"):
                self.assertIn("unreadable_key", item)
                self.assertIsNone(item.get("unreadable_key"), item)

    def test_large_files_and_fixed_drives(self):
        tree = {"Data": {"big.bin": 100, "small.bin": 99}}
        fake = FakeMachine({"C": tree},
                           drives=[("C", DRIVE_FIXED), ("E", DRIVE_REMOVABLE)])
        summary, _ = self.collect(fake, scan=self.scan_file(large_file_bytes=100))

        with self.subTest("large file threshold"):
            large = self.items(summary, "large_files")
            paths = {norm(item.get("path")) for item in large}
            self.assertIn(norm(r"C:\Data\big.bin"), paths, large)
            self.assertNotIn(norm(r"C:\Data\small.bin"), paths, large)
            big = [item for item in large if norm(item.get("path")) == norm(r"C:\Data\big.bin")]
            self.assertEqual(big[0].get("bytes"), 100, big)

        with self.subTest("only fixed drives"):
            letters = [str(d.get("letter", "")).rstrip(":\\").upper()
                       for d in self.items(summary, "drives")]
            self.assertEqual(letters, ["C"], summary.get("drives"))
            self.assertEqual([c for c in fake.calls if c.startswith("e:")], [], fake.calls)

    def test_unreadable_root_has_no_scanned_figures(self):
        """Final review, round 1: a drive whose root cannot be listed was not walked, so
        its scanned figures are null, not 0; a clean drive next to it keeps them."""
        root_denied = PermissionError(13, "Access is denied", "D:\\")
        fake = FakeMachine({"C": {"Data": {"a.bin": 7}},
                            "D": folder({"Data": {"b.bin": 5}}, error=root_denied)})
        summary, _ = self.collect(fake)
        sources = {s.get("name"): s.get("status") for s in self.items(summary, "sources")}
        self.assertEqual(sources.get("folders:D"), "unreadable", sources)
        drive_d = self.drive_item(summary, "D")
        for key in ("scanned_bytes", "scanned_gb", "scanned_files", "cloud_only_files"):
            with self.subTest(drive="D", key=key):
                self.assertIn(key, drive_d)
                self.assertIsNone(drive_d[key], drive_d)
        with self.subTest("the usage of the drive is still read"):
            self.assertIsNotNone(drive_d.get("used_gb"), drive_d)
        drive_c = self.drive_item(summary, "C")
        with self.subTest("a readable drive keeps its figures"):
            self.assertEqual(drive_c.get("scanned_bytes"), 7, drive_c)
            self.assertEqual(drive_c.get("scanned_files"), 1, drive_c)
            self.assertEqual(drive_c.get("cloud_only_files"), 0, drive_c)
            self.assertEqual(drive_c.get("scanned_gb"), 0.0, drive_c)

    def test_listing_paths_and_subst_drives(self):
        # A path over 260 characters or a name ending in a dot is reported by Windows
        # as missing unless it is listed with the extended prefix; that would count an
        # existing folder as vanished.
        self.assertEqual(self.files.extended_path("C:\\Users\\a"), "\\\\?\\C:\\Users\\a")
        self.assertEqual(self.files.extended_path("C:\\"), "\\\\?\\C:\\")
        self.assertEqual(self.files.extended_path("\\\\?\\C:\\x"), "\\\\?\\C:\\x")
        # A subst drive maps a folder of another drive: walking it counts those files twice.
        self.assertTrue(self.files.is_subst_target("\\??\\C:\\Users\\a\\Projects"))
        self.assertFalse(self.files.is_subst_target("\\Device\\HarddiskVolume3"))


if __name__ == "__main__":
    unittest.main()

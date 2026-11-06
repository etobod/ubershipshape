"""Vendor folders no installed program matches: the ``vendor_folders`` source of
skills/ush-inventory/scripts/inventory.py (plan 025, milestone M1, criteria K1-K6, K8-K10).

The interface these tests assume is listed in ``fakes.py`` and ``fakes_vendor_folders.py``.
PowerShell never starts; every data dir and data file lives in a temporary directory;
every value is invented.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .fakes import FakePowerShell, failure, ok, win32
from .fakes_autostart import SHARE_PROCESS, VENDOR, facts, file_row, service
from .fakes_vendor_folders import (
    INSTALLER,
    PROGRAM_DATA,
    PROGRAM_FILES,
    PROGRAM_FILES_X86,
    ROOTS,
    VendorFoldersTestCase,
    expanded,
    folder,
    folder_key,
    folder_path,
    listing,
)

CONTOSO_LAST_WRITE = "2024-06-30T18:45:12Z"


def fabrikam_program(location="C:\\Program Files\\Fabrikam\\Fabrikam Studio"):
    return win32("FabrikamStudio", "Fabrikam Studio", publisher="Fabrikam, Inc.",
                 install_location=location)


def northwind_program():
    # Installed under another path: only the data file's vendor list links it.
    return win32("{1B2C3D4E-5F60-4718-92A3-B4C5D6E7F809}", "Northwind Order Desk",
                 publisher="Northwind Traders Inc.", install_location=None)


class TestVendorFolders(VendorFoldersTestCase):
    def test_only_unmatched_listed(self):
        fake = FakePowerShell({
            "win32_programs": ok([fabrikam_program(), northwind_program()]),
            "vendor_folders": listing([
                folder(PROGRAM_DATA, "Contoso", has_entries=True,
                       last_write=CONTOSO_LAST_WRITE),
                folder(PROGRAM_FILES, "Fabrikam"),
                folder(PROGRAM_FILES_X86, "Northwind Traders"),
            ]),
        })
        summary = self.collect(fake)
        self.assertIn("vendor_folders", fake.jobs())

        listed = self.folders(summary)
        contoso = folder_path(PROGRAM_DATA, "Contoso")
        self.assertEqual(set(listed), {folder_key(contoso)}, listed)
        self.assert_listed(listed[folder_key(contoso)], PROGRAM_DATA, "Contoso",
                           has_entries=True, last_write=CONTOSO_LAST_WRITE)

        counts = self.folder_counts(summary)
        self.assertEqual(counts["vendor_folders_read"], 3, counts)
        self.assertEqual(counts["vendor_folders_matched"], 2, counts)
        self.assertEqual(counts["vendor_folders_unmatched"], 1, counts)

    def test_clean_machine_lists_nothing(self):
        target = "C:\\ProgramData\\Contoso\\Agent\\contoso-agent.exe"
        fake = FakePowerShell({
            "win32_programs": ok([
                # Install location equal to the folder itself.
                fabrikam_program(location="C:\\Program Files\\Fabrikam"),
                northwind_program(),
            ]),
            "services": ok([service("ContosoAgent", f'"{target}" -service')]),
            "file_facts": facts(file_row(target, signer=VENDOR)),
            "vendor_folders": listing([
                folder(PROGRAM_FILES, "Fabrikam"),
                folder(PROGRAM_FILES, "Microsoft"),
                folder(PROGRAM_FILES, "common files"),
                folder(PROGRAM_FILES, "WINDOWS NT"),
                folder(PROGRAM_FILES_X86, "Northwind Traders"),
                folder(PROGRAM_FILES_X86, "Windows Defender"),
                folder(PROGRAM_DATA, "Contoso"),
                folder(PROGRAM_DATA, "Package Cache"),
                folder(INSTALLER, "$PatchCache$"),
                folder(INSTALLER, "{6F1E2D3C-4B5A-4978-8695-A4B3C2D1E0F9}"),
            ]),
        })
        summary = self.collect(fake)

        self.assertEqual(self.summary_list(summary, "vendor_folders"), [])
        self.assertEqual(self.vendor_notes(summary), [], summary.get("not_checked"))
        counts = self.folder_counts(summary)
        self.assertEqual(counts["vendor_folders_unmatched"], 0, counts)

    def test_target_match_and_broad_location(self):
        target = "C:\\Program Files\\Fabrikam\\bin\\fabsvc.exe"
        fake = FakePowerShell({
            "win32_programs": ok([
                win32("ContosoDataTool", "Contoso Data Tool", publisher="Contoso Ltd",
                      install_location="C:\\ProgramData"),
            ]),
            "services": ok([service("FabrikamSvc", f'"{target}" -run', state="Running")]),
            "file_facts": facts(file_row(target, signer=VENDOR)),
            "vendor_folders": listing([
                folder(PROGRAM_FILES, "Fabrikam"),
                folder(PROGRAM_DATA, "Contoso"),
            ]),
        })
        summary = self.collect(fake)

        listed = self.folders(summary)
        contoso = folder_path(PROGRAM_DATA, "Contoso")
        self.assertEqual(set(listed), {folder_key(contoso)}, listed)
        self.assert_listed(listed[folder_key(contoso)], PROGRAM_DATA, "Contoso")
        self.assertNotIn(folder_key(folder_path(PROGRAM_FILES, "Fabrikam")), listed)

    def test_installer_guid_folders_counted(self):
        upper = "{9A3F21C4-7B1D-4E2A-8C5F-0D6E4B2A1F37}"
        lower = "{4d2c1b0a-9e8f-4a7b-b6c5-d4e3f2a1b0c9}"
        fake = FakePowerShell({
            "vendor_folders": listing([
                folder(INSTALLER, upper),
                folder(INSTALLER, lower, has_entries=False),
                folder(INSTALLER, "Contoso"),
            ]),
        })
        summary = self.collect(fake)

        listed = self.folders(summary)
        contoso = folder_path(INSTALLER, "Contoso")
        self.assertEqual(set(listed), {folder_key(contoso)}, listed)
        self.assert_listed(listed[folder_key(contoso)], INSTALLER, "Contoso")
        text = json.dumps(summary["vendor_folders"]).casefold()
        for name in (upper, lower):
            self.assertNotIn(name.casefold(), text)

        counts = self.folder_counts(summary)
        self.assertEqual(counts["installer_guid_folders"], 2, counts)

    def test_similar_name_is_not_a_match(self):
        fake = FakePowerShell({
            "win32_programs": ok([
                win32("ContosoSuite", "Contoso Suite", publisher="Contoso",
                      install_location="C:\\Program Files\\Contoso Suite"),
            ]),
            "vendor_folders": listing([
                folder(PROGRAM_FILES, "Contoso"),
                folder(PROGRAM_FILES, "Contoso Suite"),
            ]),
        })
        summary = self.collect(fake)

        listed = self.folders(summary)
        contoso = folder_path(PROGRAM_FILES, "Contoso")
        self.assertEqual(set(listed), {folder_key(contoso)}, listed)
        self.assert_listed(listed[folder_key(contoso)], PROGRAM_FILES, "Contoso")

    def test_unread_program_source_lists_nothing(self):
        fake = FakePowerShell({
            "win32_programs": failure("Invented registry read failure 0x80070005"),
            "vendor_folders": listing([
                folder(PROGRAM_DATA, "Contoso"),
                folder(PROGRAM_FILES, "Fabrikam"),
            ]),
        })
        summary = self.collect(fake)

        self.assert_unreadable(summary, "win32_programs")
        self.assertIn("vendor_folders", summary, sorted(summary))
        self.assertIsNone(summary["vendor_folders"], summary["vendor_folders"])
        notes = self.vendor_notes(summary)
        self.assertTrue(
            any("win32_programs" in f"{note.get('what')} {note.get('reason')}"
                for note in notes),
            summary.get("not_checked"))

    def test_denied_folder_and_reparse_point(self):
        denied_reason = "Invented access to the folder is denied"
        fake = FakePowerShell({
            "vendor_folders": listing([
                folder(PROGRAM_FILES, "Contoso", has_entries=None, reason=denied_reason),
                folder(PROGRAM_FILES, "Northwind Traders", has_entries=False),
                folder(PROGRAM_DATA, "Fabrikam Link", reparse_point=True),
            ]),
        })
        summary = self.collect(fake)

        listed = self.folders(summary)
        contoso = folder_path(PROGRAM_FILES, "Contoso")
        northwind = folder_path(PROGRAM_FILES, "Northwind Traders")
        link = folder_path(PROGRAM_DATA, "Fabrikam Link")
        self.assertEqual(set(listed), {folder_key(contoso), folder_key(northwind)}, listed)

        denied = listed[folder_key(contoso)]
        self.assertIn("has_entries", denied, denied)
        self.assertIsNone(denied["has_entries"], denied)
        self.assertIsNot(denied["has_entries"], False, denied)
        detail = self.detail_folders(summary)
        self.assertIn(contoso.casefold(), detail, sorted(detail))
        self.assertTrue(
            denied_reason in json.dumps(denied)
            or denied_reason in json.dumps(detail[contoso.casefold()]),
            (denied, detail[contoso.casefold()]))

        self.assert_listed(listed[folder_key(northwind)], PROGRAM_FILES,
                           "Northwind Traders", has_entries=False)

        self.assertNotIn(folder_key(link), listed)
        self.assertNotIn(link.casefold(), detail, sorted(detail))
        counts = self.folder_counts(summary)
        self.assertEqual(counts["reparse_points"], 1, counts)

    def test_detail_file_holds_list(self):
        installer_reason = "Invented access to the Installer folder is denied"
        fake = FakePowerShell({
            "win32_programs": ok([fabrikam_program()]),
            "vendor_folders": listing(
                [folder(PROGRAM_DATA, "Contoso"), folder(PROGRAM_FILES, "Fabrikam")],
                unreadable={INSTALLER: installer_reason}),
        })
        summary = self.collect(fake)

        contoso = folder_path(PROGRAM_DATA, "Contoso")
        fabrikam = folder_path(PROGRAM_FILES, "Fabrikam")
        self.assertEqual(set(self.folders(summary)), {folder_key(contoso)})

        section = self.detail_section(summary)
        roots = {row.get("root"): row for row in section["roots"]}
        self.assertEqual(set(roots), set(ROOTS), section["roots"])
        for root in ROOTS:
            row = roots[root]
            self.assertEqual(row.get("expanded"), expanded(root), row)
            if root == INSTALLER:
                self.assertEqual(row.get("status"), "unreadable", row)
                self.assertEqual(row.get("reason"), installer_reason, row)
            else:
                self.assertEqual(row.get("status"), "read", row)
                self.assertIsNone(row.get("reason"), row)

        folders = self.detail_folders(summary)
        self.assertEqual(set(folders), {contoso.casefold(), fabrikam.casefold()}, folders)
        self.assertIs(folders[contoso.casefold()].get("matched"), False,
                      folders[contoso.casefold()])
        self.assertEqual(folders[contoso.casefold()].get("root"), PROGRAM_DATA)
        self.assertIs(folders[fabrikam.casefold()].get("matched"), True,
                      folders[fabrikam.casefold()])
        self.assertEqual(folders[fabrikam.casefold()].get("root"), PROGRAM_FILES)

    def test_every_root_unreadable_is_null(self):
        """The job answers, but no root could be listed: the list and every count are
        null (never [] and 0), and each root is named in not_checked."""
        reasons = {root: f"Invented access to root {place} is denied"
                   for place, root in enumerate(ROOTS)}
        fake = FakePowerShell({"vendor_folders": listing([], unreadable=reasons)})
        summary = self.collect(fake)

        self.assertIn("vendor_folders", summary, sorted(summary))
        self.assertIsNone(summary["vendor_folders"], summary["vendor_folders"])
        counts = self.folder_counts(summary)
        for key in ("vendor_folders_read", "vendor_folders_matched",
                    "vendor_folders_unmatched", "reparse_points", "installer_guid_folders"):
            self.assertIsNone(counts[key], (key, counts))
        self.assert_unreadable(summary, "vendor_folders")
        notes = json.dumps(self.not_checked(summary))
        for reason in reasons.values():
            self.assertIn(reason, notes)

        detail = self.detail(summary)
        self.assertIn("vendor_folders", detail, sorted(detail))
        self.assertIsNone(detail["vendor_folders"], detail["vendor_folders"])
        roots = {row.get("root"): row for row in detail.get("vendor_folder_roots") or []}
        self.assertEqual(set(roots), set(ROOTS), detail.get("vendor_folder_roots"))
        for root, reason in reasons.items():
            self.assertEqual(roots[root].get("status"), "unreadable", roots[root])
            self.assertEqual(roots[root].get("reason"), reason, roots[root])

    def test_failed_job_names_every_root(self):
        """The job fails: the detail file names every root of the data file as
        unreadable with the job's reason, and both folder lists are null."""
        job_reason = "Invented PowerShell start failure 0x80070002"
        summary = self.collect(FakePowerShell({"vendor_folders": failure(job_reason)}))

        self.assertIsNone(summary["vendor_folders"], summary["vendor_folders"])
        self.assert_unreadable(summary, "vendor_folders")
        detail = self.detail(summary)
        self.assertIn("vendor_folders", detail, sorted(detail))
        self.assertIsNone(detail["vendor_folders"], detail["vendor_folders"])
        rows = detail.get("vendor_folder_roots")
        self.assertIsInstance(rows, list, rows)
        self.assertEqual([row.get("root") for row in rows], list(ROOTS), rows)
        for row in rows:
            self.assertEqual(row.get("status"), "unreadable", row)
            self.assertIsNone(row.get("expanded"), row)
            self.assertIn(job_reason, str(row.get("reason")), row)

    def test_unread_program_source_with_baseline_withholds(self):
        """win32_programs unreadable but in the baseline: a folder no rule matches is
        listed as not judged (matched null, counted unknown), never as unmatched."""
        data_dir = self.data_dir()
        folders = listing([folder(PROGRAM_DATA, "Contoso"), folder(PROGRAM_FILES, "Fabrikam")])
        self.collect(FakePowerShell({"win32_programs": ok([fabrikam_program()]),
                                     "vendor_folders": folders}), data_dir)
        summary = self.collect(FakePowerShell({
            "win32_programs": failure("Invented registry read failure 0x80070005"),
            "vendor_folders": folders,
        }), data_dir)

        self.assert_unreadable(summary, "win32_programs")
        listed = self.folders(summary)
        contoso_path = folder_path(PROGRAM_DATA, "Contoso")
        self.assertEqual(set(listed), {folder_key(contoso_path)}, listed)
        item = listed[folder_key(contoso_path)]
        self.assert_listed(item, PROGRAM_DATA, "Contoso")
        self.assertIsNone(item.get("matched", False), item)
        self.assertIn("win32_programs", str(item.get("not_judged")), item)
        counts = self.folder_counts(summary)
        self.assertEqual(counts["vendor_folders_unknown"], 1, counts)
        self.assertEqual(counts["vendor_folders_matched"], 1, counts)
        self.assertEqual(counts["vendor_folders_unmatched"], 0, counts)
        detail = self.detail_folders(summary)
        contoso = contoso_path.casefold()
        self.assertIsNone(detail[contoso].get("matched"), detail[contoso])
        self.assertTrue(
            any("win32_programs" in str(note.get("reason"))
                for note in self.vendor_notes(summary) if note.get("what") == "vendor_folders"),
            summary.get("not_checked"))

    def test_unread_autostart_target_lists_folders_not_judged(self):
        """One service's ServiceDll could not be read: every folder no rule matches is
        still in the summary list, with a ``v`` id, ``matched`` null and the cause;
        none is ``matched`` false and the counts are as before (plan 025, option C)."""
        host = service("InventedDllSvc", "C:\\Windows\\system32\\svchost.exe -k InventedGroup",
                       type_=SHARE_PROCESS, service_dll=None)
        host["Error"] = "Invented registry failure"
        host["ErrorAt"] = "ServiceDll"
        fake = FakePowerShell({
            "win32_programs": ok([fabrikam_program()]),
            "services": ok([host]),
            "vendor_folders": listing([
                folder(PROGRAM_DATA, "Contoso"),
                folder(PROGRAM_FILES, "Fabrikam"),
                folder(PROGRAM_FILES_X86, "Northwind Traders"),
            ]),
        })
        summary = self.collect(fake)

        listed = self.folders(summary)
        contoso = folder_path(PROGRAM_DATA, "Contoso")
        northwind = folder_path(PROGRAM_FILES_X86, "Northwind Traders")
        self.assertEqual(set(listed), {folder_key(contoso), folder_key(northwind)}, listed)
        ids = set()
        for root, name, path in ((PROGRAM_DATA, "Contoso", contoso),
                                 (PROGRAM_FILES_X86, "Northwind Traders", northwind)):
            item = listed[folder_key(path)]
            self.assert_listed(item, root, name)
            self.assertIn("matched", item, item)
            self.assertIsNone(item["matched"], item)
            self.assertIn("autostart", str(item.get("not_judged")), item)
            ids.add(item["id"])
        self.assertEqual(len(ids), 2, listed)
        self.assertFalse(any(item.get("matched") is False for item in listed.values()),
                         listed)

        counts = self.folder_counts(summary)
        self.assertEqual(counts["vendor_folders_read"], 3, counts)
        self.assertEqual(counts["vendor_folders_matched"], 1, counts)
        self.assertEqual(counts["vendor_folders_unmatched"], 0, counts)
        self.assertEqual(counts["vendor_folders_unknown"], 2, counts)
        reasons = " ".join(str(note.get("reason")) for note in self.vendor_notes(summary)
                           if note.get("what") == "vendor_folders")
        self.assertIn("matched null", reasons, summary.get("not_checked"))
        self.assertNotIn("not listed", reasons, summary.get("not_checked"))

    def test_fully_read_run_lists_only_matched_false(self):
        """Clean counterpart: with everything read, every listed folder is ``matched``
        false and has no ``not_judged`` cause."""
        fake = FakePowerShell({
            "win32_programs": ok([fabrikam_program()]),
            "vendor_folders": listing([
                folder(PROGRAM_DATA, "Contoso"),
                folder(PROGRAM_FILES, "Fabrikam"),
            ]),
        })
        summary = self.collect(fake)

        listed = self.folders(summary)
        self.assertEqual(set(listed), {folder_key(folder_path(PROGRAM_DATA, "Contoso"))},
                         listed)
        for item in listed.values():
            self.assertIs(item.get("matched"), False, item)
            self.assertNotIn("not_judged", item, item)
        self.assertEqual(self.folder_counts(summary)["vendor_folders_unknown"], 0)

    def test_unreadable_root_and_bad_data_file(self):
        root_reason = "Invented access to ProgramData is denied"
        with self.subTest(case="unreadable root"):
            fake = FakePowerShell({
                "vendor_folders": listing(
                    [folder(PROGRAM_FILES, "Contoso"),
                     folder(PROGRAM_FILES_X86, "Fabrikam")],
                    unreadable={PROGRAM_DATA: root_reason}),
            })
            summary = self.collect(fake)
            listed = self.folders(summary)
            self.assertEqual(
                set(listed),
                {folder_key(folder_path(PROGRAM_FILES, "Contoso")),
                 folder_key(folder_path(PROGRAM_FILES_X86, "Fabrikam"))},
                listed)
            notes = [json.dumps(note) for note in self.vendor_notes(summary)]
            self.assertTrue(any(json.dumps(PROGRAM_DATA)[1:-1] in note for note in notes),
                            summary.get("not_checked"))
            self.assertTrue(
                any(root_reason in json.dumps(note) for note in self.not_checked(summary)),
                summary.get("not_checked"))

        bad_files = {
            "missing": None,
            "not JSON": "{\"roots\": [",
            "not an object": "[]",
            "roots not a list": json.dumps({"roots": "%ProgramFiles%",
                                            "windows_names": [], "vendors": {}}),
        }
        for case, text in bad_files.items():
            with self.subTest(case=f"data file {case}"):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "vendor-folders.json"
                    if text is not None:
                        path.write_text(text, encoding="utf-8")
                    config, reason = self.inventory.load_vendor_folders(path)
                    self.assertIsNone(config)
                    self.assertIn("vendor-folders.json", str(reason))
                    with mock.patch.object(self.inventory, "VENDOR_FOLDERS_FILE", path):
                        summary = self.collect(FakePowerShell({
                            "vendor_folders": listing([folder(PROGRAM_DATA, "Contoso")]),
                        }))
                self.assertIn("vendor_folders", summary, sorted(summary))
                self.assertIsNone(summary["vendor_folders"], summary["vendor_folders"])
                self.assertTrue(
                    any("vendor-folders.json" in f"{note.get('what')} {note.get('reason')}"
                        for note in self.not_checked(summary)),
                    summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

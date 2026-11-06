"""A single element of the ``vendor_folders`` source (TEST-PLAN (b), new source):
``ConvertTo-Json`` writes one root, and one folder of a root, as an object, not a list
(plan 025, M1; written by loc-qa).

PowerShell never starts; every value is invented.
"""

import unittest

from .fakes import FakePowerShell, ok
from .fakes_vendor_folders import (
    PROGRAM_DATA,
    VendorFoldersTestCase,
    data_file_text,
    expanded,
    folder,
    folder_key,
    folder_path,
)

LAST_WRITE = "2024-03-14T07:30:00Z"


class TestVendorFoldersSingleElement(VendorFoldersTestCase):
    def test_single_root_and_single_folder_as_objects(self):
        """One root in the data file and one folder under it, both as JSON objects:
        the folder is listed exactly as from a list."""
        self.data_file.write_text(data_file_text(roots=[PROGRAM_DATA]), encoding="utf-8")
        row = {"root": PROGRAM_DATA, "expanded": expanded(PROGRAM_DATA), "status": "read",
               "reason": None,
               "folders": folder(PROGRAM_DATA, "Contoso", has_entries=False,
                                 last_write=LAST_WRITE)}
        summary = self.collect(FakePowerShell({"vendor_folders": ok(row)}))

        listed = self.folders(summary)
        contoso = folder_path(PROGRAM_DATA, "Contoso")
        self.assertEqual(set(listed), {folder_key(contoso)}, listed)
        self.assert_listed(listed[folder_key(contoso)], PROGRAM_DATA, "Contoso",
                           has_entries=False, last_write=LAST_WRITE)
        counts = self.folder_counts(summary)
        self.assertEqual(counts["vendor_folders_read"], 1, counts)
        self.assertEqual(counts["vendor_folders_unmatched"], 1, counts)
        self.assertEqual(self.vendor_notes(summary), [], summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

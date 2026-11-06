"""Invented top-level folders for the ``vendor_folders`` source of ush-inventory
(plan 025, milestone M1).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``not_checked``, item
``key``/``id``, the detail file) is described in ``fakes.py``; program rows come from
``fakes.win32`` and autostart rows from ``fakes_autostart``.

Interface fixed for M1 (the code does not exist yet):

- Data file constant ``inventory.VENDOR_FOLDERS_FILE`` (a ``Path`` to
  ``skills/ush-inventory/data/vendor-folders.json``), patched with
  ``mock.patch.object``. A JSON object with ``roots`` (list of raw strings such as
  ``"%ProgramFiles%"``), ``windows_names`` (list of folder names) and ``vendors``
  (object: folder name -> list of exact publisher names). Loader
  ``inventory.load_vendor_folders(path) -> (config, reason)``; an unusable file
  (missing, not JSON, wrong shape) gives ``(None, reason)`` with ``vendor-folders.json``
  in the reason.
- A PowerShell job ``vendor_folders``. Its input file is ``<out stem>.input.json``
  next to ``out_path``: ``{"roots": [<raw root strings of the data file>]}``. It answers
  one row per root: ``{"root": "<raw root>", "expanded": "C:\\...", "status": "read" |
  "unreadable", "reason": null | "<text>", "folders": [{"name", "path",
  "reparse_point": bool, "has_entries": true | false | null, "reason": null | "<text>",
  "last_write": "<ISO 8601 UTC>"}]}`` (``folders`` null when unreadable).
  ``FakePowerShell`` answers every root read and empty when the job is not given.
- Python skips reparse points (counted in ``reparse_points``), names of
  ``windows_names`` (case-insensitive), and, in the root that expands to
  ``...\\Installer``, GUID-named folders (``{8-4-4-4-12}`` hex) before matching
  (counted in ``installer_guid_folders``).
- Matched: a win32 ``InstallLocation`` equal to the folder or under it (a location equal
  to a root such as ``C:\\ProgramData``, or under ``C:\\Windows``, matches nothing); an
  autostart, service or task target under the folder; the data file's ``vendors`` entry
  for the folder name listing a publisher an installed program has (exact, case-folded).
  No fuzzy match.
- Summary list ``vendor_folders`` holds every folder no rule matches, items ``{"id":
  "v<n>", "key": "vendor_folder:<case-folded path>", "path", "root" (raw), "matched",
  "has_entries", "last_write"}``: ``matched`` false, or null with ``not_judged`` (the
  shared cause text) when something the folder could belong to was not read; ``null`` when the data file is unusable or when ``win32_programs`` is
  unreadable with no baseline. ``component_counts`` gains ``vendor_folders_read``,
  ``vendor_folders_matched``, ``vendor_folders_unmatched``, ``reparse_points`` and
  ``installer_guid_folders``. A ``not_checked`` entry about the source names
  ``vendor_folders`` (and ``win32_programs``, the raw root, or ``vendor-folders.json``
  as the case is) in ``what`` or ``reason``.
- Detail file section ``vendor_folders``: ``{"roots": [{"root", "expanded", "status",
  "reason"}], "folders": [every folder read after the skips, each with "matched" and
  "root"]}``.

Every value here is invented; nothing comes from a machine. Root expansions are the
Windows defaults, not readings.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from .fakes import VENDOR_ROOT_EXPANSIONS, ok
from .fakes_components import ComponentsTestCase

PROGRAM_FILES = "%ProgramFiles%"
PROGRAM_FILES_X86 = "%ProgramFiles(x86)%"
PROGRAM_DATA = "%ProgramData%"
INSTALLER = "%WINDIR%\\Installer"
ROOTS = (PROGRAM_FILES, PROGRAM_FILES_X86, PROGRAM_DATA, INSTALLER)

WINDOWS_NAMES = ["Microsoft", "Windows Defender", "Common Files", "Package Cache",
                 "$PatchCache$", "Windows NT"]
VENDORS = {"Northwind Traders": ["Northwind Traders Inc."]}

LAST_WRITE = "2025-11-02T09:15:00Z"

COUNT_KEYS = ("vendor_folders_read", "vendor_folders_matched", "vendor_folders_unmatched",
              "reparse_points", "installer_guid_folders")


def expanded(root):
    """The default expansion of a raw root."""
    return VENDOR_ROOT_EXPANSIONS[root]


def folder_path(root, name):
    """The full path of the direct child ``name`` of ``root``."""
    return f"{expanded(root)}\\{name}"


def folder(root, name, has_entries=True, reparse_point=False, reason=None,
           last_write=LAST_WRITE):
    """One direct child folder of ``root`` as the ``vendor_folders`` job returns it."""
    return {
        "name": name,
        "path": folder_path(root, name),
        "reparse_point": reparse_point,
        "has_entries": has_entries,
        "reason": reason,
        "last_write": last_write,
    }


def root_row(root, folders=()):
    """A root that was listed, holding ``folders``."""
    return {"root": root, "expanded": expanded(root), "status": "read", "reason": None,
            "folders": list(folders)}


def unreadable_root(root, reason):
    """A root that could not be listed."""
    return {"root": root, "expanded": expanded(root), "status": "unreadable",
            "reason": reason, "folders": None}


def listing(folders=(), unreadable=None):
    """The ``vendor_folders`` job answer: one row per root of ``ROOTS``, in order.

    ``folders`` are rows of ``folder(...)`` placed under the root their path starts
    with; ``unreadable`` maps a raw root to its reason."""
    unreadable = unreadable or {}
    rows = []
    for root in ROOTS:
        if root in unreadable:
            rows.append(unreadable_root(root, unreadable[root]))
            continue
        prefix = expanded(root).casefold() + "\\"
        mine = [f for f in folders
                if f["path"].casefold().startswith(prefix)
                and "\\" not in f["path"][len(prefix):]]
        rows.append(root_row(root, mine))
    return ok(rows)


def data_file_text(roots=ROOTS, windows_names=None, vendors=None):
    """The text of an invented ``vendor-folders.json``."""
    return json.dumps({
        "roots": list(roots),
        "windows_names": list(WINDOWS_NAMES if windows_names is None else windows_names),
        "vendors": dict(VENDORS if vendors is None else vendors),
    })


def folder_key(path):
    """``vendor_folder:<case-folded path>``."""
    return f"vendor_folder:{path.casefold()}"


def same_instant(a, b):
    """Two ISO 8601 times name the same instant (``Z`` and ``+00:00`` alike)."""
    return datetime.fromisoformat(str(a)) == datetime.fromisoformat(str(b))


class VendorFoldersTestCase(ComponentsTestCase):
    """Every test runs with an invented ``vendor-folders.json`` patched in."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_file = Path(tmp.name).resolve() / "vendor-folders.json"
        self.data_file.write_text(data_file_text(), encoding="utf-8")
        patcher = mock.patch.object(self.inventory, "VENDOR_FOLDERS_FILE", self.data_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def folders(self, summary):
        """The summary list ``vendor_folders`` by key."""
        return self.by_key(self.summary_list(summary, "vendor_folders"))

    def folder_counts(self, summary):
        counts = self.component_counts(summary)
        for key in COUNT_KEYS:
            self.assertIn(key, counts, f"component_counts has no {key!r}: {counts}")
        return counts

    def vendor_notes(self, summary):
        """``not_checked`` items naming ``vendor_folders`` in ``what`` or ``reason``."""
        return [item for item in self.not_checked(summary)
                if "vendor_folders" in f"{item.get('what')} {item.get('reason')}"]

    def detail_section(self, summary):
        """``{roots, folders}``: the detail list ``vendor_folders`` (every folder read)
        and the roots' status ``vendor_folder_roots`` beside it."""
        detail = self.detail(summary)
        section = {"roots": detail.get("vendor_folder_roots"),
                   "folders": detail.get("vendor_folders")}
        self.assertIsInstance(section["roots"], list, section)
        self.assertIsInstance(section["folders"], list, section)
        return section

    def detail_folders(self, summary):
        """The detail folders by case-folded path."""
        result = {}
        for item in self.detail_section(summary)["folders"]:
            path = str(item.get("path")).casefold()
            self.assertNotIn(path, result, f"duplicate folder {item}")
            result[path] = item
        return result

    def assert_listed(self, item, root, name, has_entries=True, last_write=LAST_WRITE):
        """Every field of one listed (unmatched) folder."""
        self.assertIsNotNone(item, name)
        text = str(item.get("id"))
        self.assertTrue(text.startswith("v") and text[1:].isdigit(), item)
        path = folder_path(root, name)
        self.assertEqual(item.get("key"), folder_key(path), item)
        self.assertEqual(item.get("path"), path, item)
        self.assertEqual(item.get("root"), root, item)
        self.assertIn("has_entries", item, item)
        if has_entries is None:
            self.assertIsNone(item["has_entries"], item)
        else:
            self.assertIs(item["has_entries"], has_entries, item)
        self.assertTrue(same_instant(item.get("last_write"), last_write), item)

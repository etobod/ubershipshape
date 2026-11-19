"""winget packages read offline from its tracking catalogs (plan 073, M1, K1-K8).

Interface these tests assume (fixed before the code exists):

- The module reads files through a module-level ``DISK`` object with the methods
  ``exists(path)``, ``list_dir(path)`` (names; ``OSError`` on failure),
  ``read_text(path)`` and ``query_catalog(path, sql)`` (stdlib ``sqlite3``, read-only and
  immutable). The tests replace ``DISK.list_dir`` / ``DISK.query_catalog`` to raise for
  a chosen path and call the original for every other path.
- Locations are expanded from the module's ``ENVIRON``; the tests set ``LOCALAPPDATA`` to
  an invented temporary folder. winget's location is the raw
  ``%LOCALAPPDATA%\\Packages\\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\\LocalState``.
- Each subfolder of ``LocalState`` holding ``installed.db`` is a tracking catalog; its
  label is the subfolder name, case-folded. A catalog is a SQLite file with the tables
  ``metadata`` (``name``, ``value``; ``majorVersion`` must be ``1``), ``ids``, ``names``,
  ``versions`` and ``manifest`` (whose ``id``, ``name``, ``version`` columns hold rowids
  of those tables).
- Source ``winget_packages`` (in ``comparison`` and the baseline), compared on
  ``version``. The detail file keeps its items in ``winget_packages``, each with its
  ``key`` ``winget:<label>|<id case-folded>`` and the fields ``name``, ``id``,
  ``version``, ``versions_recorded``, ``source`` (the label), ``folder``.
- ``managers.winget`` is ``{state: "not_present", looked_in: [raw path]}`` when
  ``LocalState`` is absent, else ``{state, status, catalogs: [{source, status, count,
  wal_present, reason}], count, unreadable}``.

PowerShell never starts; every catalog is written by hand in a temporary folder; every
id, name, version and path is invented.
"""

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, PackagesTestCase, note_text, packages_fake

WINGET_PACKAGE = "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
RAW_LOCAL_STATE = "%LOCALAPPDATA%\\Packages\\" + WINGET_PACKAGE + "\\LocalState"
NOT_READ_YET = "not read yet"
SOURCE = "winget_packages"

CONTOSO_LABEL = "contoso.source"
CONTOSO_TOOL = "winget:contoso.source|contoso.tool"
FABRIKAM_APP = "winget:contoso.source|fabrikam.app"
LITWARE_KIT = "winget:contoso.source|litware.kit"

# The tables a tracking catalog of schema 1.x holds (invented rows, real shapes).
SCHEMA = """
CREATE TABLE metadata (name TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE ids (id TEXT NOT NULL);
CREATE TABLE names (name TEXT NOT NULL);
CREATE TABLE monikers (moniker TEXT NOT NULL);
CREATE TABLE versions (version TEXT NOT NULL);
CREATE TABLE channels (channel TEXT NOT NULL);
CREATE TABLE pathparts (parent INT64, pathpart TEXT NOT NULL);
CREATE TABLE manifest (
    id INT64 NOT NULL,
    name INT64 NOT NULL,
    moniker INT64 NOT NULL,
    version INT64 NOT NULL,
    channel INT64 NOT NULL,
    pathpart INT64 NOT NULL,
    hash BLOB
);
"""


def write_catalog(local_state, folder_name, rows, major="1", wal=False, journal_wal=False):
    """Write ``<local_state>\\<folder_name>\\installed.db`` with one manifest row per
    ``(id, name, version)`` in ``rows``, in that order. Returns the file's path.

    ``journal_wal``: the file is in WAL journal mode (as winget writes it); closing the
    connection checkpoints it, so no -wal or -shm file stays beside it."""
    folder = Path(local_state) / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "installed.db"
    if path.exists():
        path.unlink()
    with closing(sqlite3.connect(str(path))) as conn:
        if journal_wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO metadata (name, value) VALUES ('majorVersion', ?)",
                     (str(major),))
        conn.execute("INSERT INTO metadata (name, value) VALUES ('minorVersion', '2')")
        channel = conn.execute("INSERT INTO channels (channel) VALUES ('')").lastrowid
        cache = {}

        def ref(table, column, value):
            if (table, value) not in cache:
                cursor = conn.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (value,))
                cache[(table, value)] = cursor.lastrowid
            return cache[(table, value)]

        for package_id, name, version in rows:
            pathpart = conn.execute(
                "INSERT INTO pathparts (parent, pathpart) VALUES (NULL, ?)",
                (f"{package_id}.{version}.yaml",)).lastrowid
            conn.execute(
                "INSERT INTO manifest (id, name, moniker, version, channel, pathpart, hash)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (ref("ids", "id", package_id), ref("names", "name", name),
                 ref("monikers", "moniker", package_id.split(".")[-1].casefold()),
                 ref("versions", "version", version), channel, pathpart))
        conn.commit()
    wal_path = folder / "installed.db-wal"
    if wal == "empty":
        wal_path.write_bytes(b"")  # left after a checkpoint: nothing unmerged
    elif wal:
        wal_path.write_bytes(bytes(32))  # a non-empty -wal file: records not merged
    elif wal_path.exists():
        wal_path.unlink()
    return path


def path_has(path, folder_name):
    """True when ``path`` has ``folder_name`` as one of its folders."""
    return os.path.normcase(os.sep + folder_name + os.sep) in os.path.normcase(
        os.path.normpath(str(path)) + os.sep)


class WingetTestCase(PackagesTestCase):
    def local_app_data(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "Local"

    def local_state(self, local):
        folder = local / "Packages" / WINGET_PACKAGE / "LocalState"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def run_winget(self, local, data_dir=None, now=NOW):
        with mock.patch.object(self.packages, "ENVIRON", {"LOCALAPPDATA": str(local)}):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def failing_query(self, folder_name, error):
        """Make ``DISK.query_catalog`` raise ``error`` for the catalog in ``folder_name``."""
        original = self.packages.DISK.query_catalog

        def query_catalog(path, sql):
            if path_has(path, folder_name):
                raise error
            return original(path, sql)

        return mock.patch.object(self.packages.DISK, "query_catalog", query_catalog)

    def winget_items(self, summary):
        items = self.detail(summary).get(SOURCE)
        self.assertIsInstance(items, list, f"detail {SOURCE}: {items!r}")
        return self.by_key(items)

    def winget_changes(self, summary):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith("winget:")]

    def catalog(self, summary, label):
        winget = self.manager(summary, "winget")
        catalogs = winget.get("catalogs")
        self.assertIsInstance(catalogs, list, winget)
        matches = [row for row in catalogs if row.get("source") == label]
        self.assertEqual(len(matches), 1, f"catalog {label}: {catalogs}")
        return matches[0]

    def winget_notes(self, summary):
        return [item for item in self.not_checked(summary) if "winget" in note_text(item)]


class TestWinget(WingetTestCase):
    def test_absent_is_not_present(self):
        local = self.local_app_data()
        local.mkdir(parents=True)
        summary = self.run_winget(local)

        self.assertEqual(self.manager(summary, "winget"),
                         {"state": "not_present", "looked_in": [RAW_LOCAL_STATE]})
        for item in self.winget_notes(summary):
            text = note_text(item)
            self.assertNotIn(NOT_READ_YET, text, item)
            self.assertNotIn("unreadable", text, item)
            self.assertNotIn("could not", text, item)
        winget_packages = [item for item in self.package_list(summary)
                           if str(item.get("key")).startswith("winget:")]
        self.assertEqual(winget_packages, [], winget_packages)

    def test_highest_version_per_id(self):
        rows = [
            ("Contoso.Tool", "Contoso Tool", "1.2.0"),
            ("Contoso.Tool", "Contoso Tool", "1.10.0"),
            ("Fabrikam.App", "Fabrikam App", "3.0"),
            ("Litware.Kit", "Litware Kit", "1.0-beta"),
            ("Litware.Kit", "Litware Kit", "1.0-rc"),
        ]
        for order, ordered in (("as written", rows), ("reversed", rows[::-1])):
            with self.subTest(order=order):
                local = self.local_app_data()
                write_catalog(self.local_state(local), CONTOSO_LABEL, ordered)
                summary = self.run_winget(local)

                items = self.winget_items(summary)
                self.assertEqual(set(items), {CONTOSO_TOOL, FABRIKAM_APP, LITWARE_KIT},
                                 sorted(map(str, items)))
                self.assertEqual(items[CONTOSO_TOOL].get("version"), "1.10.0",
                                 items[CONTOSO_TOOL])
                self.assertEqual(items[CONTOSO_TOOL].get("versions_recorded"), 2,
                                 items[CONTOSO_TOOL])
                self.assertEqual(items[FABRIKAM_APP].get("version"), "3.0",
                                 items[FABRIKAM_APP])
                self.assertEqual(items[FABRIKAM_APP].get("versions_recorded"), 1,
                                 items[FABRIKAM_APP])
                self.assertEqual(items[LITWARE_KIT].get("version"), "1.0-rc",
                                 items[LITWARE_KIT])

    def test_read_writes_nothing(self):
        local = self.local_app_data()
        path = write_catalog(self.local_state(local), CONTOSO_LABEL,
                             [("Contoso.Tool", "Contoso Tool", "1.2.0")])
        before = path.read_bytes()

        summary = self.run_winget(local)

        # The catalog was really read, so the check below is not about an untouched file.
        self.assertIn(CONTOSO_TOOL, self.winget_items(summary))
        self.assertEqual(sorted(os.listdir(path.parent)), ["installed.db"])
        self.assertEqual(path.read_bytes(), before)

    def test_wal_catalog_is_opened_immutable(self):
        # A WAL-mode catalog opened without immutable gets -shm/-wal files beside it.
        local = self.local_app_data()
        path = write_catalog(self.local_state(local), CONTOSO_LABEL,
                             [("Contoso.Tool", "Contoso Tool", "1.2.0")], journal_wal=True)
        self.assertEqual(sorted(os.listdir(path.parent)), ["installed.db"])
        before = path.read_bytes()
        calls = []
        original = sqlite3.connect

        def connect(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        with mock.patch.object(self.packages.sqlite3, "connect", connect):
            summary = self.run_winget(local)

        self.assertIn(CONTOSO_TOOL, self.winget_items(summary))
        self.assertTrue(calls)
        for args, kwargs in calls:
            self.assertTrue(str(args[0]).endswith("?mode=ro&immutable=1"), args)
            self.assertIs(kwargs.get("uri"), True, kwargs)
        self.assertEqual(sorted(os.listdir(path.parent)), ["installed.db"])
        self.assertEqual(path.read_bytes(), before)

    def test_unreadable_catalog_keeps_baseline(self):
        local = self.local_app_data()
        local_state = self.local_state(local)
        newer, broken = "newschema.source", "broken.source"
        newer_key = "winget:newschema.source|contoso.tool"
        broken_key = "winget:broken.source|fabrikam.app"
        data_dir = self.data_dir()

        write_catalog(local_state, newer, [("Contoso.Tool", "Contoso Tool", "1.10.0")])
        write_catalog(local_state, broken, [("Fabrikam.App", "Fabrikam App", "3.0")])
        first = self.run_winget(local, data_dir=data_dir, now=NOW)
        self.assertEqual(set(self.winget_items(first)), {newer_key, broken_key})

        # Second run: one catalog has schema 2, the other fails to open.
        write_catalog(local_state, newer, [("Contoso.Tool", "Contoso Tool", "1.10.0")],
                      major="2")
        error_text = "database disk image is malformed (invented)"
        with self.failing_query(broken, sqlite3.Error(error_text)):
            second = self.run_winget(local, data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertNotEqual(self.manager(second, "winget").get("state"), "not_present",
                            self.manager(second, "winget"))
        expected = {newer: "tracking catalog schema 2 not known", broken: error_text}
        for label, reason in expected.items():
            with self.subTest(catalog=label):
                row = self.catalog(second, label)
                self.assertEqual(row.get("status"), "unreadable", row)
                self.assertNotEqual(row.get("status"), "not_present", row)
                self.assertIn(reason.casefold(), str(row.get("reason")).casefold(), row)
                notes = [item for item in self.not_checked(second)
                         if label in note_text(item) and reason.casefold() in note_text(item)]
                self.assertTrue(notes, second.get("not_checked"))

        items = self.winget_items(second)
        for key, version in ((newer_key, "1.10.0"), (broken_key, "3.0")):
            self.assertIn(key, items, sorted(map(str, items)))
            self.assertIs(items[key].get("from_baseline"), True, items[key])
            self.assertEqual(items[key].get("version"), version, items[key])

        removed = [change for change in self.winget_changes(second)
                   if change.get("change") == "removed"]
        self.assertEqual(removed, [], second.get("changes"))

    def test_partly_read(self):
        local = self.local_app_data()
        local_state = self.local_state(local)
        good, broken = "contoso.source", "broken.source"
        broken_key = "winget:broken.source|fabrikam.app"
        data_dir = self.data_dir()

        write_catalog(local_state, good, [("Contoso.Tool", "Contoso Tool", "1.2.0")])
        write_catalog(local_state, broken, [("Fabrikam.App", "Fabrikam App", "3.0")])
        self.run_winget(local, data_dir=data_dir, now=NOW)

        write_catalog(local_state, good, [("Contoso.Tool", "Contoso Tool", "1.10.0")])
        with self.failing_query(broken, sqlite3.Error("unable to open database (invented)")):
            second = self.run_winget(local, data_dir=data_dir, now=NOW + timedelta(days=1))

        changes = self.winget_changes(second)
        self.assertEqual([(c.get("key"), c.get("change")) for c in changes],
                         [(CONTOSO_TOOL, "changed")], changes)
        self.assertEqual(self.comparison(second).get(SOURCE), "compared",
                         self.comparison(second))
        winget = self.manager(second, "winget")
        self.assertEqual(winget.get("state"), "read", winget)
        self.assertIn("count", winget, winget)
        self.assertIsNone(winget["count"], winget)
        items = self.winget_items(second)
        self.assertIn(broken_key, items, sorted(map(str, items)))

    def test_present_empty_and_unlistable(self):
        # LocalState exists and holds no catalog (a folder without installed.db, a file).
        local = self.local_app_data()
        local_state = self.local_state(local)
        (local_state / "Diagnostics").mkdir()
        (local_state / "settings.json").write_text("{}", encoding="utf-8")
        summary = self.run_winget(local)

        winget = self.manager(summary, "winget")
        self.assertEqual(winget.get("state"), "read", winget)
        self.assertNotEqual(winget.get("state"), "not_present", winget)
        self.assertEqual(winget.get("count"), 0, winget)

        # LocalState exists but cannot be listed.
        local = self.local_app_data()
        local_state = self.local_state(local)
        write_catalog(local_state, CONTOSO_LABEL, [("Contoso.Tool", "Contoso Tool", "1.2.0")])
        original = self.packages.DISK.list_dir

        def list_dir(path):
            if os.path.normcase(os.path.normpath(str(path))) == os.path.normcase(
                    str(local_state)):
                raise OSError("Access to the path is denied (invented)")
            return original(path)

        with mock.patch.object(self.packages.DISK, "list_dir", list_dir):
            summary = self.run_winget(local)

        winget = self.manager(summary, "winget")
        self.assertEqual(winget.get("state"), "unreadable", winget)
        self.assertIn("count", winget, winget)
        self.assertIsNone(winget["count"], winget)

    def test_wal_file_is_named(self):
        # A zero-byte -wal file is left after a checkpoint and holds nothing unmerged:
        # clean data, no not_checked entry (plan 073 M1 code review, round 1).
        for wal, expected in ((True, True), (False, False), ("empty", False)):
            with self.subTest(wal=wal):
                local = self.local_app_data()
                write_catalog(self.local_state(local), CONTOSO_LABEL,
                              [("Contoso.Tool", "Contoso Tool", "1.2.0")], wal=wal)
                summary = self.run_winget(local)

                row = self.catalog(summary, CONTOSO_LABEL)
                self.assertIs(row.get("wal_present"), expected, row)
                notes = [item for item in self.not_checked(summary)
                         if "not yet merged" in note_text(item)
                         and CONTOSO_LABEL in note_text(item)]
                self.assertEqual(len(notes), 1 if expected else 0,
                                 summary.get("not_checked"))

    def test_wal_that_cannot_be_checked(self):
        # "Could not check" stays apart from "no -wal file": wal_present null and named
        # (plan 073 M1 code review, round 2); a -wal gone before the check is no -wal.
        cases = (("PermissionError", PermissionError("access denied"), None, 1),
                 ("FileNotFoundError", FileNotFoundError("gone"), False, 0))
        for name, error, expected, notes_expected in cases:
            with self.subTest(error=name):
                local = self.local_app_data()
                write_catalog(self.local_state(local), CONTOSO_LABEL,
                              [("Contoso.Tool", "Contoso Tool", "1.2.0")], wal=True)

                def size(path, error=error):
                    raise error

                with mock.patch.object(self.packages.DISK, "size", size):
                    summary = self.run_winget(local)

                row = self.catalog(summary, CONTOSO_LABEL)
                self.assertEqual(row.get("status"), "read", row)
                self.assertIs(row.get("wal_present"), expected, row)
                notes = [item for item in self.not_checked(summary)
                         if "not yet merged" in note_text(item)
                         and CONTOSO_LABEL in note_text(item)]
                self.assertEqual(len(notes), notes_expected, summary.get("not_checked"))

    def test_changes(self):
        local = self.local_app_data()
        local_state = self.local_state(local)
        data_dir = self.data_dir()

        write_catalog(local_state, CONTOSO_LABEL, [
            ("Contoso.Tool", "Contoso Tool", "1.2.0"),
            ("Fabrikam.App", "Fabrikam App", "3.0"),
        ])
        first = self.run_winget(local, data_dir=data_dir, now=NOW)
        self.assertEqual(self.winget_changes(first), [])

        write_catalog(local_state, CONTOSO_LABEL, [("Contoso.Tool", "Contoso Tool", "1.10.0")])
        second = self.run_winget(local, data_dir=data_dir, now=NOW + timedelta(days=1))

        changes = self.by_key(self.winget_changes(second))
        self.assertEqual({key: change.get("change") for key, change in changes.items()},
                         {CONTOSO_TOOL: "changed", FABRIKAM_APP: "removed"}, changes)
        changed = changes[CONTOSO_TOOL]
        self.assertEqual(self.field_names(changed), ["version"], changed)
        # A change's ``source`` is the source name, as for every source of ush-packages;
        # the catalog label is its ``catalog`` (deviation of plan 073 M1).
        self.assertEqual(changed.get("source"), SOURCE, changed)
        self.assertEqual(changed.get("catalog"), CONTOSO_LABEL, changed)
        self.assertEqual(changes[FABRIKAM_APP].get("catalog"), CONTOSO_LABEL,
                         changes[FABRIKAM_APP])

        third = self.run_winget(local, data_dir=data_dir, now=NOW + timedelta(days=2))
        self.assertEqual(self.winget_changes(third), [])
        self.assertEqual(self.changes(third), [])


def add_rows_without_id(catalog_path, rows):
    """Add one manifest row per ``(name, version)`` in ``rows`` to the catalog at
    ``catalog_path`` whose ``id`` refers to an ``ids`` row with a blank identifier (a
    row without an id, as ``winget_items`` counts it). Name and version are valid
    references."""
    with closing(sqlite3.connect(str(catalog_path))) as conn:
        channel = conn.execute("SELECT rowid FROM channels LIMIT 1").fetchone()[0]
        for name, version in rows:
            id_ref = conn.execute("INSERT INTO ids (id) VALUES ('')").lastrowid
            name_ref = conn.execute("INSERT INTO names (name) VALUES (?)", (name,)).lastrowid
            version_ref = conn.execute("INSERT INTO versions (version) VALUES (?)",
                                       (version,)).lastrowid
            moniker_ref = conn.execute("INSERT INTO monikers (moniker) VALUES (?)",
                                       (name.casefold(),)).lastrowid
            pathpart = conn.execute(
                "INSERT INTO pathparts (parent, pathpart) VALUES (NULL, ?)",
                (f"{name}.{version}.yaml",)).lastrowid
            conn.execute(
                "INSERT INTO manifest (id, name, moniker, version, channel, pathpart, hash)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (id_ref, name_ref, moniker_ref, version_ref, channel, pathpart))
        conn.commit()


def add_rows_with_dangling_id(catalog_path, rows):
    """Add one manifest row per ``(name, version)`` in ``rows`` whose ``id`` refers to
    no row of ``ids`` (a damaged catalog). Name and version are valid references."""
    with closing(sqlite3.connect(str(catalog_path))) as conn:
        channel = conn.execute("SELECT rowid FROM channels LIMIT 1").fetchone()[0]
        missing = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM ids").fetchone()[0] + 1000
        for offset, (name, version) in enumerate(rows):
            name_ref = conn.execute("INSERT INTO names (name) VALUES (?)", (name,)).lastrowid
            version_ref = conn.execute("INSERT INTO versions (version) VALUES (?)",
                                       (version,)).lastrowid
            moniker_ref = conn.execute("INSERT INTO monikers (moniker) VALUES (?)",
                                       (name.casefold(),)).lastrowid
            pathpart = conn.execute(
                "INSERT INTO pathparts (parent, pathpart) VALUES (NULL, ?)",
                (f"{name}.{version}.yaml",)).lastrowid
            conn.execute(
                "INSERT INTO manifest (id, name, moniker, version, channel, pathpart, hash)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (missing + offset, name_ref, moniker_ref, version_ref, channel, pathpart))
        conn.commit()


class TestPartlyReadIsRead(WingetTestCase):
    """A partly read winget is ``read``, not ``empty`` (plan 082, M1)."""

    def test_unreadable_beside_empty_catalog_is_read(self):
        local = self.local_app_data()
        local_state = self.local_state(local)
        empty, broken = "empty.source", "broken.source"
        write_catalog(local_state, empty, [])
        write_catalog(local_state, broken, [("Fabrikam.App", "Fabrikam App", "3.0")])

        # No previous baseline: a fresh data directory.
        with self.failing_query(broken, sqlite3.Error("unable to open database (invented)")):
            summary = self.run_winget(local, data_dir=self.data_dir())

        self.assertEqual(self.catalog(summary, broken).get("status"), "unreadable",
                         self.manager(summary, "winget"))
        winget = self.manager(summary, "winget")
        self.assertEqual(winget.get("status"), "read", winget)
        self.assertNotEqual(winget.get("status"), "empty", winget)
        self.assertIn("count", winget, winget)
        self.assertIsNone(winget["count"], winget)

    def test_all_catalogs_empty_is_empty(self):
        local = self.local_app_data()
        local_state = self.local_state(local)
        write_catalog(local_state, CONTOSO_LABEL, [])
        write_catalog(local_state, "fabrikam.source", [])

        summary = self.run_winget(local, data_dir=self.data_dir())

        for label in (CONTOSO_LABEL, "fabrikam.source"):
            with self.subTest(catalog=label):
                row = self.catalog(summary, label)
                self.assertNotEqual(row.get("status"), "unreadable", row)
        winget = self.manager(summary, "winget")
        self.assertEqual(winget.get("status"), "empty", winget)
        self.assertEqual(winget.get("count"), 0, winget)
        self.assertEqual(self.winget_items(summary), {})

    def test_rows_without_id_are_read(self):
        local = self.local_app_data()
        path = write_catalog(self.local_state(local), CONTOSO_LABEL, [])
        add_rows_without_id(path, [("Contoso Tool", "1.2.0"), ("Fabrikam App", "3.0")])

        summary = self.run_winget(local, data_dir=self.data_dir())

        winget = self.manager(summary, "winget")
        self.assertEqual(winget.get("status"), "read", winget)
        self.assertEqual(winget.get("unreadable"), 2, winget)
        self.assertEqual(self.winget_items(summary), {})

    def test_rows_with_dangling_id_are_read(self):
        local = self.local_app_data()
        path = write_catalog(self.local_state(local), CONTOSO_LABEL, [])
        add_rows_with_dangling_id(path, [("Contoso Tool", "1.2.0"), ("Fabrikam App", "3.0")])

        summary = self.run_winget(local, data_dir=self.data_dir())

        winget = self.manager(summary, "winget")
        self.assertEqual(winget.get("status"), "read", winget)
        self.assertEqual(winget.get("unreadable"), 2, winget)
        self.assertEqual(self.winget_items(summary), {})

    def test_rows_without_id_keep_baseline_items(self):
        # Final review (plan 082): a package whose row now gives no id was not read,
        # so it is carried from the baseline, never reported removed.
        local = self.local_app_data()
        local_state = self.local_state(local)
        data_dir = self.data_dir()
        fabrikam_key = f"winget:{CONTOSO_LABEL}|fabrikam.app"
        write_catalog(local_state, CONTOSO_LABEL, [("Contoso.Tool", "Contoso Tool", "1.2.0"),
                                                   ("Fabrikam.App", "Fabrikam App", "3.0")])
        self.run_winget(local, data_dir=data_dir, now=NOW)

        write_catalog(local_state, CONTOSO_LABEL, [("", "Contoso Tool", "1.2.0"),
                                                   ("Fabrikam.App", "Fabrikam App", "3.0")])
        second = self.run_winget(local, data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.winget_changes(second), [])
        items = self.winget_items(second)
        self.assertIn(CONTOSO_TOOL, items, sorted(map(str, items)))
        self.assertTrue(items[CONTOSO_TOOL].get("from_baseline"), items[CONTOSO_TOOL])
        self.assertIn(fabrikam_key, items, sorted(map(str, items)))
        self.assertFalse(items[fabrikam_key].get("from_baseline"), items[fabrikam_key])
        self.assertEqual(self.manager(second, "winget").get("unreadable"), 1)


if __name__ == "__main__":
    unittest.main()

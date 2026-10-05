"""Shared fakes for the ush-files tests of milestone M1 (plan 096).

Interface under test (fixed before the code exists):

- The script is loaded with ``load_script("ush-files", "files")``.
- ``main(argv=None, list_drives=None, scan_dir=None, disk_usage=None, is_admin=None,
  now=None, environ=None) -> int``; ``now`` is a tz-aware datetime; the tests always pass
  ``--data-dir <tmp dir>``. The four machine functions are injected all together or not
  at all; anything else raises ``TypeError``. Module-level ``default_list_drives``,
  ``default_scan_dir``, ``default_disk_usage`` and ``default_is_admin`` are used only
  when none is injected.
- ``list_drives()`` gives the letter and the ``GetDriveTypeW`` type of each drive; only
  ``DRIVE_FIXED`` (3) drives are walked.
- ``scan_dir(path)`` lists one directory: each entry has a name, whether it is a
  directory, ``size``, ``attributes``, ``reparse_tag`` and ``mtime``. A read error is an
  ``OSError``.
- Output: ``<data dir>/work/files-<UTC stamp>.summary.json`` and ``.detail.json``; the
  summary is also printed on stdout and names both files in ``summary_file`` and
  ``detail_file``.
- Summary: ``drives``, ``folders`` (ids ``f...``), ``large_files`` (ids ``l...``),
  ``counts``, ``not_checked``, ``truncated_folders``, ``truncated_large_files``. Detail
  file: ``folders`` (every folder to depth 3), ``large_files``, ``unreadable``.
- ``data/scan.json`` holds ``depth``, ``large_file_bytes``, ``summary_folders``,
  ``summary_large_files``, ``summary_changes``; a bad file exits 2.
- ``--detail f1`` prints a folder from the newest ``files-*.detail.json``; an unknown id
  exits 1.

Assumptions added by these tests beyond the plan text:

- ``list_drives()`` returns a list of ``(letter, drive_type)`` pairs, the letter without
  a colon (``"C"``). The fake pairs also answer ``drive.letter`` / ``drive.type`` and
  ``drive["letter"]`` / ``drive["type"]``.
- ``scan_dir`` entries are dicts ``{name, is_dir, size, attributes, reparse_tag, mtime,
  ctime}`` (``mtime`` and ``ctime``, the creation time, in POSIX seconds; ``ctime`` is
  ``None`` when not known, the default of the fake entries); the fake entries also
  answer attribute access (``entry.name``).
- ``disk_usage(path)`` returns a ``(total, used, free)`` named tuple, as
  ``shutil.disk_usage`` does; the fake takes the drive letter from the first character
  of ``path``.
- ``is_admin()`` returns a bool.
- The module reads ``data/scan.json`` from its path constant ``SCAN_FILE`` at run time,
  so a test injects another file by patching ``SCAN_FILE``.
- Folder items carry ``path`` and ``depth``; the drive root is the folder ``C:\\``
  (depth 0). Paths are compared case-insensitively and without a trailing backslash.
- Drive items carry ``letter`` (``"C"`` or ``"C:"``).
- ``not_checked`` is a list of ``{what, reason, ...}``; an item about a drive mentions
  ``C:`` somewhere in its text or carries ``drive``.
- Detail ``unreadable`` items carry ``path`` and ``reason``.

Added for milestone M3 (cleanup catalogue):

- ``data/cleanup.json`` is read from the module path constant ``CLEANUP_FILE`` at run
  time, so a test injects another catalogue by patching ``CLEANUP_FILE`` (as
  ``SCAN_FILE``); a bad catalogue exits 2.
- ``run_main`` and ``collect`` always pass an invented ``environ`` (``fake_environ()``),
  never ``os.environ``: ``%VAR%`` paths of the catalogue expand to invented paths under
  ``C:\\Users\\tester``. Each variable is given in its usual spelling and in upper case.
- A cleanup path that is not in the fake tree (``CLEANUP_ROOTS`` or
  ``<letter>:\\$Recycle.Bin``) raises ``FileNotFoundError`` from ``scan_dir``, as a
  missing directory does on Windows; any other path outside the tree still raises
  ``AssertionError``. So the cleanup measurement of trees without those folders finds
  them missing, and the walk guard of the M1 tests is unchanged.
- The cleanup measurement first lists the parent of each cleanup root, to see from the
  root's entry there whether the root itself is a junction or a link (code-review fix
  of M3). The parent of a cleanup root that is not in the fake tree
  (``CLEANUP_PARENTS``) also raises ``FileNotFoundError``.

Every value here is invented; nothing comes from a machine.
"""

import io
import json
import re
import tempfile
import unittest
from collections import namedtuple
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
MTIME = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc).timestamp()

GIB = 1024 ** 3

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_ARCHIVE = 0x20
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000

IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_CLOUD_6 = 0x9000601A  # OneDrive placeholder, no name-surrogate bit
NAME_SURROGATE_BIT = 0x20000000

SCAN_DEFAULTS = {
    "depth": 3,
    "large_file_bytes": 1073741824,
    "summary_folders": 25,
    "summary_large_files": 25,
    "summary_changes": 30,
}

Usage = namedtuple("Usage", "total used free")

# Invented environment for the cleanup catalogue (plan 096, M3).
FAKE_PROFILE = "C:\\Users\\tester"
FAKE_ENV = {
    "SystemRoot": "C:\\Windows",
    "windir": "C:\\Windows",
    "TEMP": FAKE_PROFILE + "\\AppData\\Local\\Temp",
    "TMP": FAKE_PROFILE + "\\AppData\\Local\\Temp",
    "LOCALAPPDATA": FAKE_PROFILE + "\\AppData\\Local",
    "APPDATA": FAKE_PROFILE + "\\AppData\\Roaming",
    "USERPROFILE": FAKE_PROFILE,
    "ProgramData": "C:\\ProgramData",
}

TEMP_DIR = FAKE_ENV["TEMP"]
WINDOWS_TEMP = "C:\\Windows\\Temp"
WU_DOWNLOAD = "C:\\Windows\\SoftwareDistribution\\Download"
DO_CACHE = ("C:\\Windows\\ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft"
            "\\Windows\\DeliveryOptimization\\Cache")
CRASH_DUMPS = FAKE_ENV["LOCALAPPDATA"] + "\\CrashDumps"
WER_ARCHIVE = "C:\\ProgramData\\Microsoft\\Windows\\WER\\ReportArchive"
WER_QUEUE = "C:\\ProgramData\\Microsoft\\Windows\\WER\\ReportQueue"


def norm(path):
    """Compare key for a Windows path: backslashes, no trailing one, lower case."""
    return str(path).replace("/", "\\").rstrip("\\").lower()


CLEANUP_ROOTS = frozenset(norm(path) for path in (
    TEMP_DIR, WINDOWS_TEMP, WU_DOWNLOAD, DO_CACHE, CRASH_DUMPS, WER_ARCHIVE, WER_QUEUE))
_RECYCLE_BIN = re.compile(r"[a-z]:\\\$recycle\.bin")
CLEANUP_PARENTS = frozenset(key[:key.rfind("\\")] for key in CLEANUP_ROOTS)


def fake_environ(drop=()):
    """The invented environment, each name also in upper case, minus ``drop`` (any
    spelling)."""
    dropped = {name.upper() for name in drop}
    env = {}
    for name, value in FAKE_ENV.items():
        if name.upper() in dropped:
            continue
        env[name] = value
        env[name.upper()] = value
    return env


def is_cleanup_root(key):
    """True for the ``norm`` key of a cleanup catalogue folder under the fake env, or of
    the parent of one."""
    return (key in CLEANUP_ROOTS or key in CLEANUP_PARENTS
            or bool(_RECYCLE_BIN.fullmatch(key)))


class Entry(dict):
    """One ``scan_dir`` entry: a dict that also answers attribute access."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class Drive(tuple):
    """``(letter, drive_type)`` that also answers ``.letter``/``.type`` and
    ``["letter"]``/``["type"]``."""

    def __new__(cls, letter, drive_type):
        return super().__new__(cls, (letter, drive_type))

    @property
    def letter(self):
        return self[0]

    @property
    def type(self):
        return self[1]

    drive_type = type

    def __getitem__(self, key):
        if key == "letter":
            return tuple.__getitem__(self, 0)
        if key in ("type", "drive_type"):
            return tuple.__getitem__(self, 1)
        return tuple.__getitem__(self, key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (IndexError, TypeError):
            return default


class FileSpec:
    def __init__(self, size, attributes=FILE_ATTRIBUTE_ARCHIVE, reparse_tag=0, mtime=MTIME,
                 ctime=None):
        self.size = size
        self.attributes = attributes
        self.reparse_tag = reparse_tag
        self.mtime = mtime
        self.ctime = ctime


class DirSpec:
    def __init__(self, children=None, attributes=FILE_ATTRIBUTE_DIRECTORY, reparse_tag=0,
                 error=None, mtime=MTIME):
        self.children = dict(children or {})
        self.attributes = attributes
        self.reparse_tag = reparse_tag
        self.error = error
        self.mtime = mtime


def file(size, attributes=FILE_ATTRIBUTE_ARCHIVE, reparse_tag=0, mtime=MTIME, ctime=None):
    """A file entry; a plain int in a tree is ``file(<int>)``. ``ctime`` is the creation
    time in POSIX seconds, ``None`` (the default) when it is not known."""
    return FileSpec(size, attributes, reparse_tag, mtime, ctime)


def folder(children=None, attributes=FILE_ATTRIBUTE_DIRECTORY, reparse_tag=0, error=None):
    """A directory entry; a plain dict in a tree is ``folder(<dict>)``. ``error`` is the
    ``OSError`` its own ``scan_dir`` raises (it still appears in its parent's list)."""
    return DirSpec(children, attributes, reparse_tag, error)


def _spec(value):
    if isinstance(value, (FileSpec, DirSpec)):
        return value
    if isinstance(value, int):
        return FileSpec(value)
    if isinstance(value, dict):
        return DirSpec(value)
    raise TypeError(f"bad tree value: {value!r}")


def must_not_list(spec):
    """True for a directory the script must not enter (name surrogate or recall on open)."""
    return bool((spec.reparse_tag & NAME_SURROGATE_BIT)
                or (spec.attributes & FILE_ATTRIBUTE_RECALL_ON_OPEN))


def machine_touched(*args, **kwargs):
    raise AssertionError("a real machine function was called")


class FakeMachine:
    """Invented drives, directory trees and disk usage.

    ``trees`` maps a drive letter to its root tree (a dict of name -> int | dict |
    FileSpec | DirSpec). Listing a directory the script must not enter, or a path that is
    not in any tree, raises ``AssertionError``; every ``scan_dir`` call is recorded in
    ``calls`` as a ``norm`` key.
    """

    def __init__(self, trees, drives=None, usage=None, admin=False):
        self.trees = {letter.upper(): _spec(tree) for letter, tree in trees.items()}
        if drives is None:
            drives = [(letter, DRIVE_FIXED) for letter in self.trees]
        self.drives = [Drive(letter, kind) for letter, kind in drives]
        self.usage = {letter.upper(): Usage(*values) for letter, values in (usage or {}).items()}
        self.admin = admin
        self.calls = []
        self.usage_calls = []
        self.index = {}
        for letter, root in self.trees.items():
            stack = [(f"{letter}:", root)]
            while stack:
                path, spec = stack.pop()
                self.index[norm(path)] = spec
                for name, child in spec.children.items():
                    child = _spec(child)
                    spec.children[name] = child
                    if isinstance(child, DirSpec):
                        stack.append((f"{path}\\{name}", child))

    def list_drives(self):
        return list(self.drives)

    def scan_dir(self, path):
        key = norm(path)
        self.calls.append(key)
        spec = self.index.get(key)
        if spec is None:
            if is_cleanup_root(key):
                raise FileNotFoundError(2, "The system cannot find the path specified", path)
            raise AssertionError(f"scan_dir called for a path outside the fake tree: {path!r}")
        if must_not_list(spec):
            raise AssertionError(f"scan_dir called for a directory it must not enter: {path!r}")
        if spec.error is not None:
            raise spec.error
        entries = []
        for name, child in spec.children.items():
            is_dir = isinstance(child, DirSpec)
            entries.append(Entry(
                name=name,
                is_dir=is_dir,
                size=0 if is_dir else child.size,
                attributes=child.attributes,
                reparse_tag=child.reparse_tag,
                mtime=child.mtime,
                ctime=getattr(child, "ctime", None),
            ))
        return entries

    def disk_usage(self, path):
        letter = str(path)[:1].upper()
        self.usage_calls.append(letter)
        if letter in self.usage:
            return self.usage[letter]
        return Usage(100 * GIB, 40 * GIB, 60 * GIB)

    def is_admin(self):
        return self.admin


class FilesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = load_script("ush-files", "files")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def scan_file(self, drop=(), **overrides):
        """Write an invented scan.json (defaults plus ``overrides``, minus ``drop``)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = dict(SCAN_DEFAULTS)
        data.update(overrides)
        for key in drop:
            data.pop(key, None)
        path = Path(tmp.name).resolve() / "scan.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def run_main(self, data_dir, fake, now=NOW, extra=(), scan=None, environ=None,
                 cleanup=None):
        """Run main with all four machine functions injected; return (code, stdout,
        stderr). ``scan`` is a scan.json path patched in as ``SCAN_FILE``, ``cleanup``
        a cleanup.json path patched in as ``CLEANUP_FILE``; ``environ`` defaults to
        ``fake_environ()``."""
        out, err = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            if scan is not None:
                stack.enter_context(mock.patch.object(self.files, "SCAN_FILE", scan))
            if cleanup is not None:
                stack.enter_context(mock.patch.object(self.files, "CLEANUP_FILE", cleanup))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            code = self.files.main(
                ["--data-dir", str(data_dir), *extra],
                list_drives=fake.list_drives,
                scan_dir=fake.scan_dir,
                disk_usage=fake.disk_usage,
                is_admin=fake.is_admin,
                now=now,
                environ=fake_environ() if environ is None else environ,
            )
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            return json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")

    def collect(self, fake, data_dir=None, now=NOW, scan=None, environ=None, cleanup=None):
        """Run a collection and return (summary, stdout); the exit code must be 0."""
        code, stdout, stderr = self.run_main(data_dir or self.data_dir(), fake, now=now,
                                             scan=scan, environ=environ, cleanup=cleanup)
        self.assertEqual(code, 0, stderr[-500:])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary, stdout

    def detail(self, summary):
        path = Path(summary.get("detail_file"))
        self.assertTrue(path.is_absolute(), path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))
        return data

    def items(self, data, key):
        value = data.get(key)
        self.assertIsInstance(value, list, f"{key}: {str(data)[:300]}")
        return value

    def folder_at(self, folders, path):
        """The one folder item whose ``path`` is ``path``."""
        matches = [f for f in folders if norm(f.get("path")) == norm(path)]
        self.assertEqual(len(matches), 1,
                         f"folder {path!r}: {[f.get('path') for f in folders][:40]}")
        return matches[0]

    def drive_item(self, summary, letter):
        drives = self.items(summary, "drives")
        matches = [d for d in drives
                   if str(d.get("letter", "")).rstrip(":\\").upper() == letter.upper()]
        self.assertEqual(len(matches), 1, f"drive {letter}: {drives}")
        return matches[0]

    def not_checked(self, summary):
        return self.items(summary, "not_checked")

    def notes_about_drive(self, summary, letter):
        """``not_checked`` items about drive ``letter``."""
        result = []
        for item in self.not_checked(summary):
            drive = str(item.get("drive", "")).rstrip(":\\").upper()
            if drive == letter.upper() or f"{letter.upper()}:" in json.dumps(item).upper():
                result.append(item)
        return result

    def counts(self, summary):
        counts = summary.get("counts")
        self.assertIsInstance(counts, dict, summary)
        return counts

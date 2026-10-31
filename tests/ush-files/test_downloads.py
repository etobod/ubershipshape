"""Downloads listing tests for skills/ush-files/scripts/files.py (plan 008, M1).

The general interface is described in ``fakes.py``. Interface from the plan (M1):

- The Downloads folder is the ``User Shell Folders`` value
  ``{374DE290-123F-4565-9164-E39C4925E467}``, expanded, or ``%USERPROFILE%\\Downloads``
  when that value is not set.
- Summary item ``downloads`` with ``status``: files and bytes in total and older than
  30, 90 and 365 days by last write time; the 20 largest and the 20 oldest files by id
  and name.
- Every file (relative path, bytes, last write time, id ``w<n>``) is written to
  ``<data dir>/work/files-<stamp>.downloads.json``.
- A folder that cannot be listed gives ``status`` ``unreadable``, sizes ``null`` and a
  ``not_checked`` item, never zero.
- Links and cloud-only files are not entered or counted, as in ``measure_dir``.

Assumed interface (beyond the plan text; the implementer matches it):

- ``main`` takes one more machine function, ``shell_folder``:
  ``shell_folder(value_name) -> str | None`` gives the raw (unexpanded, REG_EXPAND_SZ)
  data of the ``HKCU\\...\\Explorer\\User Shell Folders`` value ``value_name``, or
  ``None`` when the value is not set. Its default is the module-level
  ``default_shell_folder``; these tests patch that default to raise, and always pass
  ``shell_folder`` together with the other four machine functions. ``%VAR%`` in the
  value is expanded with the injected ``environ``, never with ``os.environ``.
- The Downloads folder is listed through the injected ``scan_dir``, as every other
  folder. These tests build real Downloads folders in a temporary directory and route
  ``scan_dir`` calls under it to a real listing written here (``os.scandir`` +
  ``lstat``: attributes and reparse tag as on Windows); every other path goes to the
  ``FakeMachine`` of ``fakes.py``. Listing a directory with a name-surrogate reparse
  tag (junction, symlink) raises ``AssertionError``, as in the fake.
- The age of a file is ``now - last write time`` (``mtime``) only; the creation time is
  not used. Ages are set with ``os.utime``; ``now`` is the real current time so the
  real creation time of the temporary files is not in the future.
- Summary ``downloads`` is a dict with ``status`` (``read`` / ``unreadable``),
  ``files``, ``bytes``, ``files_older_30``, ``bytes_older_30``, ``files_older_90``,
  ``bytes_older_90``, ``files_older_365``, ``bytes_older_365``, ``largest`` and
  ``oldest`` (lists of ``{id, name}``, ``name`` ending with the file name; ``largest``
  biggest first, ``oldest`` oldest first) and ``list_file`` (absolute path of the list
  file). When unreadable, ``files``, ``bytes`` and every ``*_older_*`` value are
  ``null`` (the keys are present).
- The list file is ``<data dir>/work/files-<stamp>.downloads.json`` with the same
  ``<stamp>`` as the run's ``files-<stamp>.summary.json``. It holds a JSON object with a
  ``files`` list (a bare list is also accepted); each item has ``id`` (``w<n>``),
  ``path`` (relative to the Downloads folder, ``\\`` or ``/`` separators), ``bytes``
  and ``last_write`` (ISO 8601; a value without an offset is read as UTC).
- The ``not_checked`` item about Downloads contains ``downloads`` (any case) in one of
  its strings.

Every file, size and age is invented; nothing comes from a machine.
"""

import builtins
import inspect
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT, load_script

from .fakes import (
    FILE_ATTRIBUTE_DIRECTORY,
    NAME_SURROGATE_BIT,
    NOW,
    Entry,
    FakeMachine,
    FilesTestCase,
    fake_environ,
    machine_touched,
    norm,
)

DOWNLOADS_VALUE = "{374DE290-123F-4565-9164-E39C4925E467}"
LIST_NAME = re.compile(r"files-(.+)\.downloads\.json")
SUMMARY_NAME = re.compile(r"files-(.+)\.summary\.json")


def denied(path):
    return PermissionError(13, "Access is denied", str(path))


def strings_of(value):
    """Every string inside parsed JSON."""
    found, stack = [], [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            found.append(item)
    return found


def rel_key(path):
    return str(path).replace("/", "\\").strip("\\").lower()


def write_file(path, size, age_days, now):
    """A file of ``size`` bytes whose last write time is ``age_days`` before ``now``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = (now - timedelta(days=age_days)).timestamp()
    os.utime(path, (stamp, stamp))
    return stamp


def make_junction(target, link):
    """Create a directory junction (or, failing that, a directory symlink) ``link`` ->
    ``target``; return an error text when the OS cannot create either."""
    errors = []
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return None
    except (ImportError, AttributeError, OSError) as exc:
        errors.append(f"junction: {exc}")
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return None
    except (OSError, NotImplementedError) as exc:
        errors.append(f"symlink: {exc}")
    return "; ".join(errors)


class RealFolders:
    """``scan_dir`` for real temporary folders under ``root``; other paths go to
    ``fallback`` (a ``FakeMachine.scan_dir``). Every listed real path is recorded in
    ``calls`` as a ``norm`` key; a path in ``deny`` raises ``PermissionError``."""

    def __init__(self, root, fallback):
        self.root = norm(root)
        self.fallback = fallback
        self.calls = []
        self.deny = set()
        self.no_date = set()

    def scan_dir(self, path):
        key = norm(path)
        if key != self.root and not key.startswith(self.root + "\\"):
            return self.fallback(path)
        self.calls.append(key)
        if key in self.deny:
            raise denied(path)
        info = os.lstat(path)
        tag = getattr(info, "st_reparse_tag", 0) or 0
        if tag & NAME_SURROGATE_BIT or os.path.islink(path) or (
                hasattr(os.path, "isjunction") and os.path.isjunction(path)):
            raise AssertionError(f"scan_dir called for a link it must not enter: {path!r}")
        entries = []
        with os.scandir(path) as listing:
            for item in listing:
                st = item.stat(follow_symlinks=False)
                attributes = getattr(st, "st_file_attributes", 0) or 0
                if attributes:
                    is_dir = bool(attributes & FILE_ATTRIBUTE_DIRECTORY)
                else:
                    is_dir = item.is_dir(follow_symlinks=False)
                entries.append(Entry(
                    name=item.name,
                    is_dir=is_dir,
                    size=0 if is_dir else st.st_size,
                    attributes=attributes,
                    reparse_tag=getattr(st, "st_reparse_tag", 0) or 0,
                    mtime=None if item.name in self.no_date else st.st_mtime,
                    ctime=getattr(st, "st_birthtime", None),
                ))
        return entries


class ShellFolders:
    """``shell_folder(value_name)``: the raw data of the Downloads value, or None."""

    def __init__(self, downloads=None):
        self.downloads = downloads
        self.calls = []

    def __call__(self, value_name):
        self.calls.append(value_name)
        if str(value_name).strip().upper() == DOWNLOADS_VALUE:
            return self.downloads
        return None


class TestDownloads(FilesTestCase):
    # --- helpers ------------------------------------------------------------------------

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="ush-dl-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.root = Path(tmp).resolve()
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def environ(self):
        env = fake_environ()  # both spellings of USERPROFILE are the same key
        env["USERPROFILE"] = str(self.profile)
        return env

    def run_downloads(self, shell, deny=(), no_date=()):
        """Run a collection with a fake drive C:, the real temporary folders and
        ``shell``; return (summary, folders, data dir). The exit code must be 0."""
        self.assertIn("shell_folder", inspect.signature(self.files.main).parameters,
                      "main() takes no shell_folder machine function")
        fake = FakeMachine({"C": {"Data": {"a.bin": 1}}})
        folders = RealFolders(self.root, fake.scan_dir)
        folders.deny.update(norm(path) for path in deny)
        folders.no_date.update(no_date)
        data_dir = self.data_dir()
        out, err = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                self.files, "default_shell_folder", machine_touched, create=True))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            code = self.files.main(
                ["--data-dir", str(data_dir)],
                list_drives=fake.list_drives,
                scan_dir=folders.scan_dir,
                disk_usage=fake.disk_usage,
                is_admin=fake.is_admin,
                shell_folder=shell,
                now=self.now,
                environ=self.environ(),
            )
        self.assertEqual(code, 0, err.getvalue()[-500:])
        summary = self.parse(out.getvalue())
        self.assertIsInstance(summary, dict, out.getvalue()[:300])
        return summary, folders, data_dir

    def downloads(self, summary):
        item = summary.get("downloads")
        self.assertIsInstance(item, dict, f"downloads: {str(summary)[:300]}")
        return item

    def notes_about_downloads(self, summary):
        return [note for note in self.not_checked(summary)
                if any("downloads" in text.lower() for text in strings_of(note))]

    def list_items(self, item, data_dir, summary):
        path = Path(str(item.get("list_file")))
        self.assertTrue(path.is_absolute(), path)
        self.assertEqual(norm(path.parent), norm(data_dir / "work"), path)
        name = LIST_NAME.fullmatch(path.name)
        self.assertIsNotNone(name, path.name)
        summary_name = SUMMARY_NAME.fullmatch(Path(str(summary.get("summary_file"))).name)
        self.assertIsNotNone(summary_name, summary.get("summary_file"))
        self.assertEqual(name.group(1), summary_name.group(1), "stamp of the list file")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            data = data.get("files")
        self.assertIsInstance(data, list, str(data)[:300])
        return data

    def last_write(self, value):
        self.assertIsInstance(value, str, value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    # --- K1 -----------------------------------------------------------------------------

    def test_listing_counts_and_list_file(self):
        downloads = self.profile / "Pobrane"  # the shell folder value, not the fallback
        stamps = {
            "fresh.zip": write_file(downloads / "fresh.zip", 4000, 10, self.now),
            "photo.jpg": write_file(downloads / "photo.jpg", 1000, 60, self.now),
            "old\\setup.exe": write_file(downloads / "old" / "setup.exe", 2000, 400,
                                         self.now),
        }
        sizes = {"fresh.zip": 4000, "photo.jpg": 1000, "old\\setup.exe": 2000}
        summary, _, data_dir = self.run_downloads(ShellFolders("%USERPROFILE%\\Pobrane"))
        item = self.downloads(summary)

        with self.subTest("totals"):
            self.assertEqual(item.get("status"), "read", item)
            self.assertEqual(item.get("files"), 3, item)
            self.assertEqual(item.get("bytes"), 7000, item)
            self.assertEqual(self.notes_about_downloads(summary), [])

        with self.subTest("age buckets by last write time"):
            self.assertEqual(item.get("files_older_30"), 2, item)
            self.assertEqual(item.get("bytes_older_30"), 3000, item)
            self.assertEqual(item.get("files_older_90"), 1, item)
            self.assertEqual(item.get("bytes_older_90"), 2000, item)
            self.assertEqual(item.get("files_older_365"), 1, item)
            self.assertEqual(item.get("bytes_older_365"), 2000, item)

        files = self.list_items(item, data_dir, summary)
        ids = {}
        with self.subTest("list file: every file with a w id"):
            self.assertEqual(len(files), 3, files)
            for entry in files:
                self.assertIsInstance(entry, dict, files)
                self.assertRegex(str(entry.get("id")), r"^w\d+$", entry)
                key = rel_key(entry.get("path"))
                self.assertIn(key, sizes, entry)
                self.assertEqual(entry.get("bytes"), sizes[key], entry)
                self.assertAlmostEqual(self.last_write(entry.get("last_write")), stamps[key],
                                       delta=1.0, msg=entry)
                ids[key] = entry.get("id")
            self.assertEqual(len(set(ids.values())), 3, ids)

        with self.subTest("largest and oldest by id and name"):
            largest = self.items(item, "largest")
            oldest = self.items(item, "oldest")
            self.assertEqual([e.get("id") for e in largest],
                             [ids["fresh.zip"], ids["old\\setup.exe"], ids["photo.jpg"]])
            self.assertEqual([e.get("id") for e in oldest],
                             [ids["old\\setup.exe"], ids["photo.jpg"], ids["fresh.zip"]])
            names = {ids[key]: key.split("\\")[-1] for key in ids}
            for entry in largest + oldest:
                self.assertTrue(str(entry.get("name")).replace("/", "\\").lower()
                                .endswith(names[entry.get("id")]), entry)

    # --- K2 -----------------------------------------------------------------------------

    def test_empty_is_not_unreadable(self):
        with self.subTest("empty folder (value not set: %USERPROFILE%\\Downloads)"):
            (self.profile / "Downloads").mkdir()
            summary, folders, _ = self.run_downloads(ShellFolders(None))
            item = self.downloads(summary)
            self.assertIn(norm(self.profile / "Downloads"), folders.calls)
            self.assertEqual(item.get("status"), "read", item)
            self.assertEqual(item.get("files"), 0, item)
            self.assertEqual(item.get("bytes"), 0, item)
            self.assertEqual(self.notes_about_downloads(summary), [])

        with self.subTest("folder that cannot be listed"):
            locked = self.root / "elsewhere" / "Downloads"
            write_file(locked / "kept.iso", 3000, 100, self.now)
            summary, folders, _ = self.run_downloads(ShellFolders(str(locked)),
                                                     deny=[locked])
            item = self.downloads(summary)
            self.assertIn(norm(locked), folders.calls)
            self.assertEqual(item.get("status"), "unreadable", item)
            for key in ("files", "bytes", "files_older_30", "bytes_older_30",
                        "files_older_90", "bytes_older_90", "files_older_365",
                        "bytes_older_365"):
                self.assertIn(key, item)
                self.assertIsNone(item[key], (key, item))
            self.assertTrue(self.notes_about_downloads(summary), self.not_checked(summary))

    # --- K3 -----------------------------------------------------------------------------

    def test_links_not_entered(self):
        downloads = self.root / "D-drive" / "Downloads"
        write_file(downloads / "keep.bin", 500, 5, self.now)
        target = self.root / "Elsewhere"
        write_file(target / "big.bin", 9000, 500, self.now)
        link = downloads / "Linked"
        error = make_junction(target, link)
        if error is not None:
            self.skipTest(f"the OS cannot create a junction or a directory link here: {error}")

        summary, folders, data_dir = self.run_downloads(ShellFolders(str(downloads)))
        item = self.downloads(summary)

        self.assertNotIn(norm(link), folders.calls)
        self.assertNotIn(norm(target), folders.calls)
        self.assertEqual(item.get("status"), "read", item)
        self.assertEqual(item.get("files"), 1, item)
        self.assertEqual(item.get("bytes"), 500, item)
        self.assertEqual(item.get("bytes_older_365"), 0, item)
        files = self.list_items(item, data_dir, summary)
        self.assertEqual([rel_key(entry.get("path")) for entry in files], ["keep.bin"], files)

    # --- code-review fixes (M1 round 1) -------------------------------------------------

    def test_unknown_age_is_counted_not_dropped(self):
        downloads = self.profile / "Downloads"
        write_file(downloads / "dated.bin", 100, 400, self.now)
        write_file(downloads / "nodate.bin", 300, 400, self.now)
        summary, _, _ = self.run_downloads(ShellFolders(None), no_date=["nodate.bin"])
        item = self.downloads(summary)
        self.assertEqual(item.get("files"), 2, item)
        self.assertEqual(item.get("files_older_365"), 1, item)
        self.assertEqual(item.get("files_age_unknown"), 1, item)
        self.assertEqual(item.get("bytes_age_unknown"), 300, item)
        self.assertTrue(self.notes_about_downloads(summary), self.not_checked(summary))

    def test_all_ages_known_gives_zero_unknown(self):
        write_file(self.profile / "Downloads" / "dated.bin", 100, 5, self.now)
        summary, _, _ = self.run_downloads(ShellFolders(None))
        item = self.downloads(summary)
        self.assertEqual(item.get("files_age_unknown"), 0, item)
        self.assertEqual(self.notes_about_downloads(summary), [])

    def test_value_of_wrong_type_is_unreadable(self):
        write_file(self.profile / "Downloads" / "fallback.bin", 100, 5, self.now)
        summary, folders, _ = self.run_downloads(ShellFolders(b"\x01\x02"))
        item = self.downloads(summary)
        self.assertEqual(item.get("status"), "unreadable", item)
        self.assertIsNone(item.get("files"), item)
        self.assertNotIn(norm(self.profile / "Downloads"), folders.calls)
        self.assertTrue(self.notes_about_downloads(summary), self.not_checked(summary))

    def test_registry_reader_refuses_wrong_type(self):
        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        fake = mock.MagicMock()
        fake.OpenKey.return_value = FakeKey()
        fake.QueryValueEx.return_value = (b"\x01\x02", 3)  # REG_BINARY
        with mock.patch.dict("sys.modules", {"winreg": fake}):
            with self.assertRaises(OSError):
                self.files.default_shell_folder(DOWNLOADS_VALUE)
            fake.QueryValueEx.side_effect = FileNotFoundError(2, "not found")
            self.assertIsNone(self.files.default_shell_folder(DOWNLOADS_VALUE))
            fake.QueryValueEx.side_effect = None
            fake.QueryValueEx.return_value = (r"%USERPROFILE%\Pobrane", 2)
            self.assertEqual(self.files.default_shell_folder(DOWNLOADS_VALUE),
                             r"%USERPROFILE%\Pobrane")

    def test_report_checker_skips_downloads_names(self):
        check = load_script("ush-common", "check_report")
        profile = check.load_profile("ush-files")
        summary = {"downloads": {
            "files": 2, "list_file": r"C:\d\work\files-20261030-1015.downloads.json",
            "largest": [{"id": "w1", "name": "invoice_2024_37.pdf"}],
            "oldest": [{"id": "w2", "name": "scan 4811.png"}]}}
        numbers = {value for _, value in check.json_values(summary, profile.skip_keys)}
        for made_up in (2024, 37, 4811, 20261030, 1015):
            self.assertNotIn(made_up, numbers)
        self.assertIn(2, numbers)


# --- plan 008, M2: the printed Downloads block -------------------------------------------

MACHINE_FUNCTIONS = ("list_drives", "scan_dir", "disk_usage", "is_admin", "shell_folder")
DEFAULT_MACHINE = tuple("default_" + name for name in MACHINE_FUNCTIONS)

COPY = re.compile(r"(?i)\bCopy-Item\b")
REMOVE = re.compile(r"(?i)\bRemove-Item\b")
SHA256 = re.compile(r"(?i)\bGet-FileHash\b[^\n]*-Algorithm\s+['\"]?SHA256\b")
THROW = re.compile(r"(?i)\bthrow\b")
COMPARE = re.compile(r"(?im)^[^#\n]*-[ci]?(?:eq|ne)\b[^\n]*$")
UNDO_START = re.compile(r"(?im)^[ \t]*#[^\n]*\bundo\b")
STOP_ON_ERROR = re.compile(r"(?i)-(?:ErrorAction|EA)\s+['\"]?Stop\b")
STOP_PREFERENCE = re.compile(r"(?i)\$ErrorActionPreference\s*=\s*['\"]Stop\b")
EXISTS_CHECK = re.compile(r"(?i)\bTest-Path\b|\]::Exists\(|\.Exists\b")
INSIDE_CHECK = re.compile(r"(?i)\.StartsWith\(|-[ci]?(?:not)?like\b|-[ci]?(?:not)?match\b"
                          r"|GetRelativePath")
NON_ELEVATED = re.compile(r"(?i)non-elevated|not elevated|without elevation|unelevated"
                          r"|user's own|not as admin")
KEYWORD = re.compile(r"(?i)\b(elseif|if|else|foreach|for|while|do|try|catch|finally"
                     r"|function|switch)\b")
HASH_WORDS = ("hash",)
SIZE_WORDS = ("length", "size")

DEST = r"E:\Kopia\pobrane-2026"  # an invented external disk
LIST_FILES = [
    {"id": "w1", "path": "setup-tool.exe", "bytes": 2048,
     "last_write": "2025-03-14T09:30:00Z"},
    {"id": "w2", "path": "photos\\holiday 2019.zip", "bytes": 51200,
     "last_write": "2024-07-02T18:05:00Z"},
]


def ordered_strings(value):
    """Every string inside parsed JSON, in document order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values = list(value.values())
    elif isinstance(value, list):
        values = value
    else:
        return []
    found = []
    for item in values:
        found.extend(ordered_strings(item))
    return found


def printed_text(stdout):
    """The printed blocks: plain text, or every string of a JSON output in order."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return stdout
    return "\n".join(ordered_strings(data))


def split_blocks(text):
    """(main block, undo block or None): the undo block starts at the first comment line
    with the word "undo" after the last ``Remove-Item``."""
    removes = list(REMOVE.finditer(text))
    if not removes:
        return text, None
    undo = UNDO_START.search(text, removes[-1].end())
    if undo is None:
        return text, None
    return text[:undo.start()], text[undo.start():]


def code_lines(text):
    """``text`` without its comment lines."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def line_at(text, pos):
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:end if end != -1 else len(text)]


def compare_positions(text, start, end, words):
    """Start offsets of the code lines in ``text[start:end]`` that compare with -eq/-ne
    (any case variant) and mention one of ``words``."""
    found = []
    for match in COMPARE.finditer(text, start, end):
        line = match.group(0).lower()
        if any(word in line for word in words):
            found.append(match.start())
    return found


def brace_end(text, open_pos):
    """Offset of the ``}`` closing the ``{`` at ``open_pos`` (end of text if none)."""
    depth = 0
    for index in range(open_pos, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def inside_if(text, pos):
    """True when ``pos`` lies in the body of an ``if (...) {`` or ``elseif (...) {``."""
    for match in re.finditer(r"\{", text[:pos]):
        index = match.start()
        if brace_end(text, index) < pos:
            continue
        before = text[:index]
        header = before[max(before.rfind("{"), before.rfind("}")) + 1:]
        keywords = KEYWORD.findall(header)
        if keywords and keywords[-1].lower() in ("if", "elseif"):
            return True
    return False


def catch_without_throw(text):
    """Bodies of ``catch`` blocks that do not throw again."""
    bodies = []
    for match in re.finditer(r"(?i)\bcatch\b[^{\n]*\{", text):
        body = text[match.end() - 1:brace_end(text, match.end() - 1) + 1]
        if not THROW.search(body):
            bodies.append(body.strip()[:200])
    return bodies


def delete_problems(main):
    """K1: every ``Remove-Item`` follows a ``Copy-Item``, two SHA-256 hashes, a hash and a
    size comparison, and is reached only when they match."""
    problems = []
    removes = list(REMOVE.finditer(main))
    if not removes:
        return ["no Remove-Item in the block"]
    for remove in removes:
        r = remove.start()
        line = line_at(main, r).strip()
        copies = [match.start() for match in COPY.finditer(main, 0, r)]
        if not copies:
            problems.append(f"Remove-Item before any Copy-Item: {line!r}")
            continue
        c = copies[-1]
        if len(SHA256.findall(main, c, r)) < 2:
            problems.append(f"fewer than two Get-FileHash -Algorithm SHA256 between the copy "
                            f"and {line!r}")
        hashes = compare_positions(main, c, r, HASH_WORDS)
        sizes = compare_positions(main, c, r, SIZE_WORDS)
        if not hashes:
            problems.append(f"no hash comparison between the copy and {line!r}")
        if not sizes:
            problems.append(f"no size comparison between the copy and {line!r}")
        if hashes and sizes:
            checked = max(hashes[0], sizes[0])
            if THROW.search(main, checked, r) is None and not inside_if(main, r):
                problems.append(f"{line!r} is neither after a throw on mismatch nor inside "
                                f"an if branch")
    return problems


def abort_problems(main):
    """K2: a failed copy stops the block, a mismatch throws, no catch swallows it."""
    problems = []
    copies = [match.start() for match in COPY.finditer(main)]
    if not copies:
        return ["no Copy-Item in the block"]
    for index, c in enumerate(copies):
        end = copies[index + 1] if index + 1 < len(copies) else len(main)
        line = line_at(main, c).strip()
        if not (STOP_ON_ERROR.search(line) or STOP_PREFERENCE.search(main, 0, c)):
            problems.append(f"a failed copy does not stop the block: {line!r}")
        compares = compare_positions(main, c, end, HASH_WORDS + SIZE_WORDS)
        if not compares:
            problems.append(f"no size or hash comparison after {line!r}")
        elif THROW.search(main, compares[0], end) is None:
            problems.append(f"no throw after the comparison that follows {line!r}")
    problems.extend(f"a catch swallows the error: {body!r}"
                    for body in catch_without_throw(main))
    return problems


def runtime_root_problems(text):
    """The Downloads root is built at run time from the shell folder value, with the
    ``$env:USERPROFILE\\Downloads`` fallback, in code lines (not comments)."""
    code = code_lines(text).lower()
    return [f"not in the code lines: {needle}"
            for needle in (DOWNLOADS_VALUE.lower(), "user shell folders", "$env:userprofile",
                           "downloads")
            if needle not in code]


def snapshot(root):
    """Every folder and file under ``root`` with size and write time."""
    found = {}
    for folder, dirs, files in os.walk(root):
        for name in dirs:
            found[os.path.join(folder, name)] = "dir"
        for name in files:
            path = os.path.join(folder, name)
            info = os.stat(path)
            found[path] = (info.st_size, info.st_mtime_ns)
    return found


class Recorder:
    """Machine functions that record their call and refuse it."""

    def __init__(self):
        self.calls = []

    def kwargs(self):
        def make(name):
            def call(*args, **kwargs):
                self.calls.append(name)
                raise AssertionError(f"{name} was called")
            return call
        return {name: make(name) for name in MACHINE_FUNCTIONS}


class DiskGuard:
    """Records every ``open`` and every directory listing made while installed."""

    def __init__(self):
        self.opens = []
        self.listings = []

    def install(self, stack):
        real_open, real_scandir, real_listdir = io.open, os.scandir, os.listdir

        def guarded_open(file, mode="r", *args, **kwargs):
            self.opens.append((file, mode))
            return real_open(file, mode, *args, **kwargs)

        def guarded_scandir(path="."):
            self.listings.append(path)
            return real_scandir(path)

        def guarded_listdir(path="."):
            self.listings.append(path)
            return real_listdir(path)

        stack.enter_context(mock.patch.object(builtins, "open", guarded_open))
        stack.enter_context(mock.patch.object(io, "open", guarded_open))
        stack.enter_context(mock.patch.object(os, "scandir", guarded_scandir))
        stack.enter_context(mock.patch.object(os, "listdir", guarded_listdir))

    def problems(self, allowed_reads, listing_roots):
        allowed = {norm(path) for path in allowed_reads}
        program = norm(REPO_ROOT / "skills")
        roots = [norm(path) for path in listing_roots]
        problems = []
        for file, mode in self.opens:
            key = f"fd {file}" if isinstance(file, int) else norm(os.fspath(file))
            if any(flag in str(mode) for flag in "wax+"):
                problems.append(f"opened for writing: {file!r} ({mode!r})")
            elif key not in allowed and not key.startswith(program + "\\"):
                problems.append(f"read beyond the list file: {file!r}")
        for path in self.listings:
            key = f"fd {path}" if isinstance(path, int) else norm(os.fspath(path))
            if not any(key == root or key.startswith(root + "\\") for root in roots):
                problems.append(f"listed outside the data dir: {path!r}")
        return problems


class TestDownloadsBlock(FilesTestCase):
    """The printed copy-verify-delete block for Downloads (plan 008, M2).

    Interface from the plan: ``files.py --block downloads --list <file> --dest <folder>``
    reads a list file in the M1 format (possibly cut down by the user); ``--ids w1,w5``
    resolves the ids from the newest ``work/files-*.downloads.json`` of the data
    directory (then ``--stamp`` of the approved listing is required and must be the
    newest one's), or from ``--list`` when given. It prints one PowerShell block and an undo
    block, and runs nothing.

    Assumed interface (M2; the implementer matches it):

    - ``main`` is called as in ``test_cleanup.py``: ``main(["--data-dir", <dir>,
      "--block", "downloads", "--list", <file>, "--dest", <folder>, "--ids", "w1,w2"],
      now=..., environ=..., <the five machine functions>)``. No machine function and no
      module ``default_*`` machine function is called; no subprocess is started.
      ``--ids`` takes a comma-separated list. Errors (no ``--dest``, an unknown id, no
      list file) exit 1, not argparse's 2, and print no block.
    - The output is plain text, or JSON whose strings are taken in document order.
    - The main block comes first. Its first non-empty line is a ``#`` header with the
      risk ``medium``, the shell (one of "non-elevated", "not elevated", "without
      elevation", "unelevated", "user's own", "not as admin") and the word "rollback".
    - The undo block follows the main block and starts with a ``#`` comment line holding
      the word "undo"; no such comment line stands between the last ``Remove-Item`` of
      the main block and the start of the undo block. The undo block has no
      ``Remove-Item``.
    - Per file (in a loop or written out per file) the code is inline, in this order: a
      ``Copy-Item``; two ``Get-FileHash ... -Algorithm SHA256`` calls (source and copy;
      not through a helper function defined before the copy); code lines (not comments)
      comparing with ``-eq``/``-ne`` (or a case variant) that mention "hash" and
      "length" or "size"; then ``Remove-Item``, either after a ``throw`` that follows
      those comparisons or inside an ``if (...) {`` body.
    - A failed copy stops the block: ``-ErrorAction Stop`` on the ``Copy-Item`` line or
      ``$ErrorActionPreference = 'Stop'`` before it. Every ``catch`` body throws again.
    - Before the first ``Copy-Item``, code lines hold the shell folder value
      ``{374DE290-123F-4565-9164-E39C4925E467}``, "User Shell Folders",
      ``$env:USERPROFILE``, "Downloads", the ``--dest`` value as given, an existence
      check (``Test-Path``, ``::Exists(`` or ``.Exists``), an inside-the-root check
      (``.StartsWith(``, ``-like``, ``-match`` or ``GetRelativePath``) and a ``throw``.
      The undo block builds the root the same way and names the ``--dest`` value.
    - After the last ``Remove-Item`` of the main block: the words "copied", "verified",
      "deleted" and "not deleted".
    - Each file appears by its relative path as in the list file (``\\`` or ``/``).
    - ``--block downloads`` opens only the list file (files under ``skills/`` are
      program data and allowed), lists directories only inside the data dir and writes
      nothing anywhere.

    Every list file, file name, size and path is invented; nothing comes from a machine.
    """

    # --- helpers ------------------------------------------------------------------------

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="ush-dlb-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.base = Path(tmp).resolve()
        self.data = self.base / "ush-data"
        self.work = self.data / "work"
        self.work.mkdir(parents=True)

    def write_list(self, path, files, stamp="20261030-101500", mtime=None):
        """An invented list file in the M1 format."""
        path.parent.mkdir(parents=True, exist_ok=True)
        when = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
        doc = {
            "schema_version": 1,
            "skill": "ush-files",
            "generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary_file": str(self.work / f"files-{stamp}.summary.json"),
            "files": files,
        }
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        stamp_seconds = when.timestamp() if mtime is None else mtime
        os.utime(path, (stamp_seconds, stamp_seconds))
        return path

    def approved_list(self):
        return self.write_list(self.base / "approved" / "downloads-approved.json", LIST_FILES)

    def run_block(self, extra, environ=None, guard=None):
        """``files.py --block downloads <extra>`` with refusing machine functions;
        return (code, stdout, stderr, recorder)."""
        recorder = Recorder()
        out, err = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            for name in DEFAULT_MACHINE:
                stack.enter_context(mock.patch.object(self.files, name, machine_touched,
                                                      create=True))
            stack.enter_context(mock.patch("subprocess.Popen", machine_touched))
            if guard is not None:
                guard.install(stack)
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            try:
                code = self.files.main(
                    ["--data-dir", str(self.data), "--block", "downloads", *extra],
                    now=NOW, environ=fake_environ() if environ is None else environ,
                    **recorder.kwargs())
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue(), recorder

    def block(self, extra, environ=None):
        """Run a block that must print; return (stdout, text, main block, undo block)."""
        code, stdout, stderr, recorder = self.run_block(extra, environ)
        self.assertEqual(code, 0, (stdout[:300], stderr[-500:]))
        self.assertEqual(recorder.calls, [])
        text = printed_text(stdout)
        main, undo = split_blocks(text)
        return stdout, text, main, undo

    def assert_no_block(self, code, stdout, stderr, recorder):
        self.assertEqual(code, 1, (stdout[:300], stderr[-300:]))
        for pattern in (COPY, REMOVE, SHA256):
            self.assertIsNone(pattern.search(stdout), stdout[:500])
        self.assertEqual(recorder.calls, [])

    def assert_paths(self, text, present, absent=()):
        lower = text.lower()
        for path in present:
            forms = {path.lower(), path.replace("\\", "/").lower()}
            self.assertTrue(any(form in lower for form in forms), f"{path!r} not printed")
        for path in absent:
            forms = {path.lower(), path.replace("\\", "/").lower()}
            self.assertFalse(any(form in lower for form in forms), f"{path!r} printed")

    # --- K1 -----------------------------------------------------------------------------

    def test_block_copies_verifies_then_deletes(self):
        listing = self.approved_list()
        _, _, main, _ = self.block(["--list", str(listing), "--dest", DEST])

        with self.subTest("every approved file by its relative path"):
            self.assert_paths(main, [entry["path"] for entry in LIST_FILES])

        with self.subTest("copy, SHA-256 of both sides, compare, delete only when verified"):
            self.assertRegex(main, COPY)
            self.assertRegex(main, SHA256)
            self.assertRegex(main, REMOVE)
            self.assertEqual(delete_problems(main), [], main)

        with self.subTest("final counts"):
            removes = list(REMOVE.finditer(main))
            self.assertTrue(removes, main)
            tail = main[removes[-1].end():].lower()
            for word in ("copied", "verified", "deleted", "not deleted"):
                self.assertIn(word, tail, main[-800:])

    # --- K2 -----------------------------------------------------------------------------

    def test_block_aborts_on_mismatch(self):
        listing = self.approved_list()
        _, _, main, _ = self.block(["--list", str(listing), "--dest", DEST])
        self.assertRegex(main, COPY)
        self.assertRegex(main, THROW)
        self.assertEqual(abort_problems(main), [], main)

    # --- K3 -----------------------------------------------------------------------------

    def test_block_refuses_bad_input(self):
        listing = self.approved_list()

        with self.subTest("no --dest"):
            self.assert_no_block(*self.run_block(["--list", str(listing)]))

        with self.subTest("unknown w id"):
            self.assert_no_block(*self.run_block(
                ["--list", str(listing), "--ids", "w1,w9", "--dest", DEST]))

        with self.subTest("destination checked at run time before any copy"):
            _, _, main, _ = self.block(["--list", str(listing), "--dest", DEST])
            first = COPY.search(main)
            self.assertIsNotNone(first, main)
            before = code_lines(main[:first.start()])
            self.assertEqual(runtime_root_problems(before), [], before)
            self.assertIn(DEST.lower(), before.lower())
            self.assertRegex(before, EXISTS_CHECK)
            self.assertRegex(before, INSIDE_CHECK)
            self.assertRegex(before, THROW)

    # --- K4 -----------------------------------------------------------------------------

    def test_block_is_print_only(self):
        listing = self.write_list(self.work / "files-20261030-101500.downloads.json",
                                  LIST_FILES)
        dest = self.base / "dest-not-created"
        runs = (("--list", ["--list", str(listing), "--dest", str(dest)]),
                ("--ids from the data dir", ["--ids", "w1", "--stamp", "20261030-101500",
                                             "--dest", str(dest)]))
        for label, extra in runs:
            with self.subTest(label):
                before = snapshot(self.base)
                guard = DiskGuard()
                code, stdout, stderr, recorder = self.run_block(extra, guard=guard)
                self.assertEqual(code, 0, (stdout[:300], stderr[-500:]))
                self.assertRegex(printed_text(stdout), COPY)
                self.assertEqual(recorder.calls, [])
                self.assertEqual(guard.problems([listing], [self.data]), [])
                self.assertEqual(snapshot(self.base), before)
                self.assertFalse(dest.exists())

    def test_block_is_one_script_block(self):
        """Pasted into a console, a top-level ``throw`` ends only its own statement; each
        block runs as one ``& { ... }`` so a guard stops everything after it."""
        listing = self.approved_list()
        _stdout, text, main, undo = self.block(["--list", str(listing), "--dest", DEST])
        self.assertIsNotNone(undo, text[-500:])
        for name, part in (("run", main), ("undo", undo)):
            with self.subTest(name):
                code = [line for line in part.splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
                self.assertTrue(code, part)
                self.assertEqual(code[0].strip(), "& {", part[:300])
                self.assertEqual(code[-1].strip(), "}", part[-300:])

    # --- K5 -----------------------------------------------------------------------------

    def test_block_has_undo_and_no_profile_path(self):
        listing = self.approved_list()
        args = ["--list", str(listing), "--dest", DEST]
        stdout, text, main, undo = self.block(args)

        with self.subTest("header line"):
            lines = [line for line in main.splitlines() if line.strip()]
            self.assertTrue(lines, text[:300])
            header = lines[0]
            self.assertTrue(header.lstrip().startswith("#"), header)
            self.assertIn("medium", header.lower())
            self.assertRegex(header, NON_ELEVATED)
            self.assertIn("rollback", header.lower())

        with self.subTest("undo block copies back and verifies"):
            self.assertIsNotNone(undo, "no undo block after the main block: " + text[-500:])
            self.assertIsNone(REMOVE.search(undo), undo)
            first = COPY.search(undo)
            self.assertIsNotNone(first, undo)
            self.assertGreaterEqual(len(SHA256.findall(undo, first.start())), 2, undo)
            self.assertTrue(compare_positions(undo, first.start(), len(undo), HASH_WORDS),
                            undo)
            self.assertTrue(compare_positions(undo, first.start(), len(undo), SIZE_WORDS),
                            undo)
            self.assertEqual(runtime_root_problems(undo), [], undo)
            self.assertIn(DEST.lower(), undo.lower())
            self.assert_paths(undo, [entry["path"] for entry in LIST_FILES])

        with self.subTest("no expanded profile path"):
            profile = fake_environ()["USERPROFILE"].lower()
            self.assertNotIn(profile, stdout.lower())
            self.assertNotIn(profile, text.lower())

        with self.subTest("another profile"):
            env = fake_environ()
            env["USERPROFILE"] = r"D:\Profiles\anna-k"
            other_stdout, other_text, _, _ = self.block(args, environ=env)
            self.assertNotIn("anna-k", other_stdout.lower())
            self.assertNotIn("anna-k", other_text.lower())

    # --- K6 -----------------------------------------------------------------------------

    def test_ids_resolve_from_data_dir(self):
        older = [
            {"id": "w1", "path": "keep-me.txt", "bytes": 120,
             "last_write": "2025-01-05T07:00:00Z"},
            {"id": "w2", "path": "old-report.pdf", "bytes": 30000,
             "last_write": "2024-11-11T11:11:00Z"},
        ]
        newer = [
            {"id": "w1", "path": "music\\album.flac", "bytes": 700000,
             "last_write": "2025-06-01T20:00:00Z"},
            {"id": "w2", "path": "new-installer.msi", "bytes": 90000,
             "last_write": "2023-02-14T12:00:00Z"},
            {"id": "w3", "path": "notes.txt", "bytes": 64,
             "last_write": "2026-10-01T09:00:00Z"},
        ]
        self.write_list(self.work / "files-20261029-080000.downloads.json", older,
                        stamp="20261029-080000")
        self.write_list(self.work / "files-20261030-101500.downloads.json", newer,
                        stamp="20261030-101500")

        with self.subTest("w2 of the newest list file"):
            _, text, main, _ = self.block(["--ids", "w2", "--stamp", "20261030-101500",
                                           "--dest", DEST])
            self.assertRegex(main, COPY)
            self.assert_paths(text, ["new-installer.msi"],
                              absent=["old-report.pdf", "keep-me.txt", "music\\album.flac",
                                      "notes.txt"])

        with self.subTest("no list file in the data dir"):
            for path in self.work.glob("files-*.downloads.json"):
                path.unlink()
            (self.work / "files-20261030-101500.summary.json").write_text(
                "{}", encoding="utf-8")
            self.assert_no_block(*self.run_block(["--ids", "w2", "--stamp", "20261030-101500",
                                                  "--dest", DEST]))

    # --- code-review fix (M2): the block is tied to the listing the user approved -------
    # A rerun of files.py renumbers the w ids, so the block checks, before any copy, that
    # each listed file still has the approved size (and last write time), and its header
    # names the list file the ids came from.

    def precheck_part(self, main):
        """Code lines of ``main`` before its first ``Copy-Item``."""
        first = COPY.search(main)
        self.assertIsNotNone(first, main)
        return code_lines(main[:first.start()])

    def header_of(self, main):
        lines = [line for line in main.splitlines() if line.strip()]
        self.assertTrue(lines, main[:300])
        return lines[0]

    def test_block_prechecks_size_before_copy(self):
        listing = self.approved_list()
        _, _, main, _ = self.block(["--list", str(listing), "--dest", DEST])
        before = self.precheck_part(main)

        with self.subTest("expected bytes of each approved file before the first copy"):
            for entry in LIST_FILES:
                self.assertRegex(before, rf"(?<![\d.]){entry['bytes']}(?![\d.])", entry)

        with self.subTest("a size comparison that throws, before the first copy"):
            sizes = compare_positions(before, 0, len(before), SIZE_WORDS)
            self.assertTrue(sizes, before)
            self.assertIsNotNone(THROW.search(before, sizes[0]), before)

        with self.subTest("the approved last write time is compared before the first copy"):
            self.assertIn("lastwritetimeutc", before.lower())
            for entry in LIST_FILES:
                seconds = int(datetime.fromisoformat(entry["last_write"]).timestamp())
                self.assertTrue(str(seconds) in before or entry["last_write"][:19] in before,
                                (entry, before[-1500:]))

    def test_block_header_names_list_file(self):
        listing = self.approved_list()

        with self.subTest("--list"):
            stdout, _, main, _ = self.block(["--list", str(listing), "--dest", DEST])
            self.assertIn("downloads-approved.json", self.header_of(main))
            self.assertNotIn(str(self.base).lower(), stdout.lower())

        with self.subTest("--ids from the data dir"):
            self.write_list(self.work / "files-20261030-101500.downloads.json", LIST_FILES)
            stdout, _, main, _ = self.block(["--ids", "w2", "--stamp", "20261030-101500",
                                             "--dest", DEST])
            self.assertIn("files-20261030-101500.downloads.json", self.header_of(main))
            self.assertNotIn(str(self.base).lower(), stdout.lower())

    def test_block_clean_list_prints(self):
        clean = [
            {"id": "w1", "path": "readme.txt", "bytes": 10,
             "last_write": "2026-01-02T03:04:05+00:00"},
            {"id": "w2", "path": "no-date.bin", "bytes": 0, "last_write": None},
        ]
        listing = self.write_list(self.base / "clean" / "approved.json", clean)
        _, _, main, undo = self.block(["--list", str(listing), "--dest", DEST])
        self.assert_paths(main, ["readme.txt", "no-date.bin"])
        self.assertIsNotNone(undo, main[-500:])
        self.assertEqual(delete_problems(main), [], main)
        self.assertEqual(abort_problems(main), [], main)

    def test_block_refuses_entry_without_size(self):
        for label, size in (("no bytes", None), ("text", "2048"), ("negative", -1),
                            ("bool", True)):
            with self.subTest(label):
                entry = {"id": "w1", "path": "setup-tool.exe",
                         "last_write": "2025-03-14T09:30:00Z"}
                if size is not None:
                    entry["bytes"] = size
                listing = self.write_list(self.base / "bad" / "approved.json", [entry])
                self.assert_no_block(*self.run_block(
                    ["--list", str(listing), "--dest", DEST]))

        with self.subTest("last write time that is not a time"):
            entry = {"id": "w1", "path": "setup-tool.exe", "bytes": 2048,
                     "last_write": "yesterday"}
            listing = self.write_list(self.base / "bad" / "approved.json", [entry])
            self.assert_no_block(*self.run_block(["--list", str(listing), "--dest", DEST]))

    # --- code-review fix round 2 (M2): ids are tied to the stamp of the approved listing --
    # The size/last-write pre-check takes its expected values from the same list file the
    # ids resolve from, so it cannot notice ids approved from an older listing. --stamp
    # names the listing the user approved from; a newer listing in the data dir refuses.

    OLDER_STAMP = "20261029-080000"
    NEWER_STAMP = "20261030-101500"

    def two_listings(self):
        """Listing A (older) and listing B (newer) with other files under the same ids."""
        older = [
            {"id": "w1", "path": "keep-me.txt", "bytes": 120,
             "last_write": "2025-01-05T07:00:00Z"},
            {"id": "w2", "path": "old-report.pdf", "bytes": 30000,
             "last_write": "2024-11-11T11:11:00Z"},
        ]
        newer = [
            {"id": "w1", "path": "music\\album.flac", "bytes": 700000,
             "last_write": "2025-06-01T20:00:00Z"},
            {"id": "w2", "path": "new-installer.msi", "bytes": 90000,
             "last_write": "2023-02-14T12:00:00Z"},
        ]
        older_path = self.write_list(
            self.work / f"files-{self.OLDER_STAMP}.downloads.json", older,
            stamp=self.OLDER_STAMP)
        newer_path = self.write_list(
            self.work / f"files-{self.NEWER_STAMP}.downloads.json", newer,
            stamp=self.NEWER_STAMP)
        return older_path, newer_path

    def test_ids_from_older_listing_refused(self):
        self.two_listings()
        code, stdout, stderr, recorder = self.run_block(
            ["--ids", "w2", "--stamp", self.OLDER_STAMP, "--dest", DEST])
        self.assert_no_block(code, stdout, stderr, recorder)
        self.assertEqual(stdout.strip(), "", stdout[:300])
        self.assertIn("newer", stderr.lower(), stderr)
        self.assertIn("listing", stderr.lower(), stderr)
        self.assert_paths(stdout + stderr, [],
                          absent=["new-installer.msi", "old-report.pdf"])

    def test_ids_without_list_need_stamp(self):
        self.two_listings()
        code, stdout, stderr, recorder = self.run_block(["--ids", "w2", "--dest", DEST])
        self.assert_no_block(code, stdout, stderr, recorder)
        self.assertEqual(stdout.strip(), "", stdout[:300])
        self.assertIn("--stamp", stderr, stderr)
        self.assertIn("list_file", stderr, stderr)

    def test_stamp_bad_format_refused(self):
        _, newer_path = self.two_listings()
        for bad in ("2026-10-30", "20261030101500", "20261030-1015", "20261332-101500",
                    " 20261030-101500x", ""):
            with self.subTest("--ids", stamp=bad):
                self.assert_no_block(*self.run_block(
                    ["--ids", "w2", "--stamp", bad, "--dest", DEST]))
            with self.subTest("--list", stamp=bad):
                self.assert_no_block(*self.run_block(
                    ["--list", str(newer_path), "--ids", "w2", "--stamp", bad,
                     "--dest", DEST]))

    def test_ids_with_newest_stamp_prints(self):
        self.two_listings()
        _, _, main, _ = self.block(
            ["--ids", "w2", "--stamp", self.NEWER_STAMP, "--dest", DEST])
        self.assertRegex(main, COPY)
        self.assert_paths(main, ["new-installer.msi"],
                          absent=["old-report.pdf", "keep-me.txt", "music\\album.flac"])
        self.assertIn(f"files-{self.NEWER_STAMP}.downloads.json", self.header_of(main))

    def test_list_stamp_must_match(self):
        older_path, _ = self.two_listings()
        approved = self.write_list(self.base / "approved" / "cut-down.json",
                                   [{"id": "w2", "path": "old-report.pdf", "bytes": 30000,
                                     "last_write": "2024-11-11T11:11:00Z"}],
                                   stamp=self.OLDER_STAMP)

        with self.subTest("--list of the older listing with its own stamp prints"):
            _, _, main, _ = self.block(["--list", str(older_path), "--ids", "w2",
                                        "--stamp", self.OLDER_STAMP, "--dest", DEST])
            self.assert_paths(main, ["old-report.pdf"], absent=["new-installer.msi"])

        with self.subTest("a cut-down copy keeps the stamp of its generated_at"):
            _, _, main, _ = self.block(["--list", str(approved),
                                        "--stamp", self.OLDER_STAMP, "--dest", DEST])
            self.assert_paths(main, ["old-report.pdf"])

        with self.subTest("--list with another stamp is refused"):
            code, stdout, stderr, recorder = self.run_block(
                ["--list", str(older_path), "--ids", "w2", "--stamp", self.NEWER_STAMP,
                 "--dest", DEST])
            self.assert_no_block(code, stdout, stderr, recorder)
            self.assertIn("--stamp", stderr, stderr)

        with self.subTest("--list without --stamp still prints"):
            _, _, main, _ = self.block(["--list", str(older_path), "--ids", "w2",
                                        "--dest", DEST])
            self.assert_paths(main, ["old-report.pdf"])

    def test_stamp_without_downloads_block_is_usage_error(self):
        recorder = Recorder()
        err = io.StringIO()
        with (redirect_stderr(err), redirect_stdout(io.StringIO()),
              self.assertRaises(SystemExit) as caught):
            self.files.main(["--data-dir", str(self.data), "--stamp", self.NEWER_STAMP],
                            now=NOW, environ=fake_environ(), **recorder.kwargs())
        self.assertEqual(caught.exception.code, 2, err.getvalue())
        self.assertIn("--stamp", err.getvalue())
        self.assertEqual(recorder.calls, [])


if __name__ == "__main__":
    unittest.main()

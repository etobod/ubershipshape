"""Cleanup catalogue tests for skills/ush-files/scripts/files.py (plan 096, M3): the
measurement of each catalogue entry, ``--block`` that only prints, and the shape of
``data/cleanup.json``.

The general interface is described in ``fakes.py``. Interface from the plan (M3):

- ``data/cleanup.json`` entries: ``temp-user``, ``temp-windows``,
  ``windows-update-download``, ``delivery-optimization``, ``crash-dumps-user``,
  ``wer-reports``, ``recycle-bin``; each with ``paths``, ``risk``, ``needs_admin``,
  ``conditions``, ``rollback``, ``min_age_days`` and ``block``.
- Summary list ``cleanup`` (ids ``c...``): ``bytes``, ``files``, ``gb``, and with
  ``min_age_days`` > 0 also ``bytes_older``, ``files_older``, ``gb_older``; ``status``
  ``empty`` for a missing path, ``unreadable`` (``bytes: null``) for an unreadable one
  or an unset variable (reason "variable not set"), ``partial`` for a recycle bin with
  read and unreadable ``S-...`` folders.
- ``files.py --block <id>`` only prints the block; an unknown id exits 1.

Assumptions added by these tests beyond the plan text:

- ``cleanup.json`` is a list of entries, an object with an ``entries`` list, or an
  object mapping each entry id to its entry; a list entry carries its id in ``id``.
- A summary ``cleanup`` item names its catalogue entry id (``"temp-user"``) as the
  value of some string field other than ``id`` (``entry``, ``name``, ``key``...).
- The ``not_checked`` item about a cleanup entry contains the catalogue entry id in one
  of its strings, or has a string value equal to the item's ``c...`` id.
- A path that does not exist is found through ``scan_dir`` raising
  ``FileNotFoundError``; the age of a file is ``now - mtime``.
- ``--block`` prints the block as plain text or as JSON; with JSON, every string value
  of it is taken as the block text.
- A bad cleanup.json is injected by patching ``CLEANUP_FILE``.

Every tree, path and size is invented; nothing comes from a machine.
"""

import copy
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .fakes import (
    DO_CACHE,
    FILE_ATTRIBUTE_ARCHIVE,
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_ATTRIBUTE_SYSTEM,
    IO_REPARSE_TAG_CLOUD_6,
    IO_REPARSE_TAG_MOUNT_POINT,
    NOW,
    TEMP_DIR,
    WER_ARCHIVE,
    WER_QUEUE,
    WINDOWS_TEMP,
    WU_DOWNLOAD,
    FakeMachine,
    FilesTestCase,
    fake_environ,
    file,
    folder,
    machine_touched,
)

CATALOGUE = REPO_ROOT / "skills" / "ush-files" / "data" / "cleanup.json"
ENTRY_IDS = ("temp-user", "temp-windows", "windows-update-download", "delivery-optimization",
             "crash-dumps-user", "wer-reports", "recycle-bin")
REQUIRED_FIELDS = ("risk", "needs_admin", "conditions", "rollback", "min_age_days", "block")

OLD = (NOW - timedelta(days=30)).timestamp()
FRESH = (NOW - timedelta(hours=1)).timestamp()
SID_READ = "S-1-5-21-1111111111-2222222222-3333333333-1001"
SID_DENIED = "S-1-5-21-1111111111-2222222222-3333333333-1002"
MACHINE_FUNCTIONS = ("list_drives", "scan_dir", "disk_usage", "is_admin")


def denied(path):
    return PermissionError(13, "Access is denied", path)


def put(tree, path, value):
    """Put ``value`` at the absolute ``C:\\...`` ``path`` of ``tree`` (a dict of the
    drive root), creating the folders on the way."""
    parts = path.split("\\")[1:]
    node = tree
    for name in parts[:-1]:
        node = node.setdefault(name, {})
    node[parts[-1]] = value


def cleanup_tree():
    """Drive C: with every catalogue folder except CrashDumps.

    %TEMP% holds a 10-byte file of 30 days ago and a 5-byte file of today; the Delivery
    Optimization cache cannot be listed; the recycle bin has one readable ``S-...``
    folder (3000 bytes) and one that cannot be listed.
    """
    tree = {}
    put(tree, TEMP_DIR + "\\old.log", file(10, mtime=OLD))
    put(tree, TEMP_DIR + "\\new.log", file(5, mtime=FRESH))
    put(tree, WINDOWS_TEMP, {})
    put(tree, WU_DOWNLOAD, {})
    put(tree, DO_CACHE, folder({}, error=denied(DO_CACHE)))
    put(tree, WER_ARCHIVE, {})
    put(tree, WER_QUEUE, {})
    tree["$Recycle.Bin"] = folder(
        {
            SID_READ: {"$RQ7XK2M.txt": 3000},
            SID_DENIED: folder({}, error=denied("C:\\$Recycle.Bin\\" + SID_DENIED)),
        },
        attributes=FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM,
    )
    return tree


def catalogue_entries(data):
    """``[(entry id, entry dict)]`` of a parsed cleanup.json; the dicts are the objects
    inside ``data``, so changing one changes ``data``."""
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        data = data["entries"]
    if isinstance(data, list):
        return [(entry.get("id"), entry) for entry in data if isinstance(entry, dict)]
    if isinstance(data, dict):
        return [(key, entry) for key, entry in data.items() if isinstance(entry, dict)]
    return []


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


def block_text(stdout):
    """The printed block: plain text, or every string of a JSON output."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return stdout
    if isinstance(data, str):
        return data
    return "\n".join(strings_of(data))


def remove_item_problems(text):
    """Each ``Remove-Item`` that does not act on ``$_.FullName`` in a pipeline that starts
    with ``Get-ChildItem ... -File``."""
    problems = []
    for match in re.finditer(r"Remove-Item\b", text, re.IGNORECASE):
        end = text.find("\n", match.end())
        line = text[match.start():end if end != -1 else len(text)]
        if "$_.FullName" not in line:
            problems.append(f"Remove-Item not on $_.FullName: {line.strip()!r}")
        listings = list(re.finditer(r"Get-ChildItem\b", text[:match.start()], re.IGNORECASE))
        if not listings:
            problems.append(f"Remove-Item without a Get-ChildItem before it: {line.strip()!r}")
            continue
        pipeline = text[listings[-1].start():match.start()]
        if not re.search(r"(?<![\w-])-File\b", pipeline, re.IGNORECASE) or "|" not in pipeline:
            problems.append(f"Remove-Item not in a Get-ChildItem -File pipeline: "
                            f"{pipeline.strip()[:200]!r}")
    return problems


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


class TestCleanup(FilesTestCase):
    # --- helpers ------------------------------------------------------------------------

    def load_catalogue(self):
        self.assertTrue(CATALOGUE.is_file(), f"missing: {CATALOGUE}")
        data = json.loads(CATALOGUE.read_text(encoding="utf-8-sig"))
        entries = catalogue_entries(data)
        self.assertTrue(entries, f"no entries in {CATALOGUE}")
        return data, entries

    def cleanup_item(self, summary, entry_id):
        items = self.items(summary, "cleanup")
        matches = [item for item in items
                   if any(value == entry_id for key, value in item.items()
                          if key != "id" and isinstance(value, str))]
        self.assertEqual(len(matches), 1, f"{entry_id}: {json.dumps(items)[:800]}")
        return matches[0]

    def notes_about_entry(self, summary, entry_id):
        item_id = self.cleanup_item(summary, entry_id).get("id")
        return [note for note in self.not_checked(summary)
                if any(entry_id in text or text == item_id for text in strings_of(note))]

    def run_block(self, ids, data_dir=None):
        """``files.py --block <ids>`` with refusing machine functions; return
        (code, stdout, stderr, recorder, data dir)."""
        data_dir = data_dir or self.data_dir()
        recorder = Recorder()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(self.files, "default_list_drives", machine_touched), \
                mock.patch.object(self.files, "default_scan_dir", machine_touched), \
                mock.patch.object(self.files, "default_disk_usage", machine_touched), \
                mock.patch.object(self.files, "default_is_admin", machine_touched), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                code = self.files.main(["--data-dir", str(data_dir), "--block", ids],
                                       now=NOW, environ=fake_environ(), **recorder.kwargs())
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue(), recorder, data_dir

    def assert_no_work_files(self, data_dir):
        work = data_dir / "work"
        written = list(work.iterdir()) if work.exists() else []
        self.assertEqual(written, [])

    # --- K12 ----------------------------------------------------------------------------

    def test_measure_entries(self):
        summary, _ = self.collect(FakeMachine({"C": cleanup_tree()}))

        with self.subTest("temp-user: all files and files older than min_age_days"):
            temp = self.cleanup_item(summary, "temp-user")
            self.assertEqual(temp.get("bytes"), 15, temp)
            self.assertEqual(temp.get("bytes_older"), 10, temp)
            self.assertEqual(temp.get("files_older"), 1, temp)

        with self.subTest("delivery-optimization: unreadable is not empty"):
            cache = self.cleanup_item(summary, "delivery-optimization")
            self.assertEqual(cache.get("status"), "unreadable", cache)
            self.assertIn("bytes", cache)
            self.assertIsNone(cache.get("bytes"), cache)
            self.assertTrue(self.notes_about_entry(summary, "delivery-optimization"),
                            self.not_checked(summary))

        with self.subTest("crash-dumps-user: missing folder is empty"):
            dumps = self.cleanup_item(summary, "crash-dumps-user")
            self.assertEqual(dumps.get("status"), "empty", dumps)
            self.assertEqual(dumps.get("bytes"), 0, dumps)

        with self.subTest("recycle-bin: one S- folder read, one unreadable"):
            bin_item = self.cleanup_item(summary, "recycle-bin")
            self.assertEqual(bin_item.get("status"), "partial", bin_item)
            self.assertEqual(bin_item.get("bytes"), 3000, bin_item)
            self.assertTrue(self.notes_about_entry(summary, "recycle-bin"),
                            self.not_checked(summary))

        with self.subTest("crash-dumps-user: LOCALAPPDATA not set"):
            summary, _ = self.collect(FakeMachine({"C": cleanup_tree()}),
                                      environ=fake_environ(drop=("LOCALAPPDATA",)))
            dumps = self.cleanup_item(summary, "crash-dumps-user")
            self.assertEqual(dumps.get("status"), "unreadable", dumps)
            reason = str(dumps.get("reason") or "").lower()
            self.assertIn("variable", reason, dumps)
            self.assertIn("not set", reason, dumps)

    # --- K13 ----------------------------------------------------------------------------

    def test_block_only_prints(self):
        _, entries = self.load_catalogue()

        with self.subTest("temp-user"):
            code, stdout, stderr, recorder, data_dir = self.run_block("temp-user")
            self.assertEqual(code, 0, stderr[-300:])
            text = block_text(stdout)
            self.assertIn("$env:TEMP", text)
            self.assertIn("AddDays(-2)", text)
            self.assertEqual(recorder.calls, [])
            self.assert_no_work_files(data_dir)

        with self.subTest("recycle-bin"):
            code, stdout, stderr, recorder, data_dir = self.run_block("recycle-bin")
            self.assertEqual(code, 0, stderr[-300:])
            text = block_text(stdout)
            self.assertIn("Clear-RecycleBin", text)
            self.assertIn("DriveType=3", text)
            self.assertNotIn("AddDays", text)
            self.assertNotIn("list_drives", recorder.calls)
            self.assertEqual(recorder.calls, [])
            self.assert_no_work_files(data_dir)

        for entry_id, entry in entries:
            with self.subTest(entry=entry_id):
                code, stdout, stderr, recorder, _ = self.run_block(str(entry_id))
                self.assertEqual(code, 0, stderr[-300:])
                self.assertEqual(recorder.calls, [])
                text = block_text(stdout)
                self.assertNotIn("c:\\users\\", text.lower())
                days = entry.get("min_age_days")
                if isinstance(days, int) and days > 0:
                    self.assertRegex(text, r"(?i)Remove-Item\b")
                    self.assertEqual(remove_item_problems(text), [], text)

        with self.subTest("unknown id"):
            code, stdout, _, recorder, data_dir = self.run_block("no-such-entry")
            self.assertEqual(code, 1, stdout[:300])
            self.assertEqual(recorder.calls, [])
            self.assert_no_work_files(data_dir)

    # --- K14 ----------------------------------------------------------------------------

    def test_catalogue_shape(self):
        data, entries = self.load_catalogue()

        with self.subTest("the entries of the plan"):
            self.assertEqual(sorted(str(entry_id) for entry_id, _ in entries),
                             sorted(ENTRY_IDS))

        for entry_id, entry in entries:
            with self.subTest(entry=entry_id):
                for field in REQUIRED_FIELDS:
                    self.assertIn(field, entry, f"{entry_id} has no {field}")
                days = entry.get("min_age_days")
                self.assertIsInstance(days, int, entry_id)
                self.assertNotIsInstance(days, bool, entry_id)
                block = entry.get("block")
                self.assertIsInstance(block, str, entry_id)
                if days > 0:
                    self.assertIn("LastWriteTime", block, entry_id)
                    self.assertIn(f"AddDays(-{days})", block, entry_id)
                for field in ("rollback", "conditions"):
                    text = json.dumps(entry.get(field), ensure_ascii=False)
                    self.assertTrue(entry.get(field), f"{entry_id}: {field} is empty")
                    self.assertTrue(text.isascii(), f"{entry_id}: {field} is not ASCII: {text}")

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for field in REQUIRED_FIELDS:
            with self.subTest(missing=field):
                broken = copy.deepcopy(data)
                _, first = catalogue_entries(broken)[0]
                first.pop(field)
                path = Path(tmp.name).resolve() / f"cleanup-without-{field}.json"
                path.write_text(json.dumps(broken), encoding="utf-8")
                fake = FakeMachine({"C": {"Data": {"a.bin": 1}}})
                code, stdout, stderr = self.run_main(self.data_dir(), fake, cleanup=path)
                self.assertEqual(code, 2, (stdout[:300], stderr[-300:]))

    # --- code-review fixes of M3 ----------------------------------------------------------

    def test_age_needs_old_creation_too(self):
        """A file unpacked or copied just now keeps an old last-write time but has a new
        creation time: it is not older, neither in the measurement nor in the block."""
        tree = cleanup_tree()
        put(tree, TEMP_DIR + "\\unpacked.dll", file(7, mtime=OLD, ctime=FRESH))
        put(tree, TEMP_DIR + "\\stale.tmp", file(20, mtime=OLD, ctime=OLD))
        put(tree, TEMP_DIR + "\\rewritten.tmp", file(40, mtime=FRESH, ctime=OLD))
        summary, _ = self.collect(FakeMachine({"C": tree}))
        temp = self.cleanup_item(summary, "temp-user")
        self.assertEqual(temp.get("bytes"), 82, temp)
        # old.log (10, ctime unknown: mtime counts) and stale.tmp (20)
        self.assertEqual(temp.get("bytes_older"), 30, temp)
        self.assertEqual(temp.get("files_older"), 2, temp)

        _, entries = self.load_catalogue()
        for entry_id, entry in entries:
            if entry.get("min_age_days", 0) > 0:
                with self.subTest(entry=entry_id):
                    self.assertRegex(entry["block"],
                                     r"\$_\.LastWriteTime -lt \$cutoff -and "
                                     r"\$_\.CreationTime -lt \$cutoff")

    def test_link_root_not_measured(self):
        """A cleanup folder that is itself a junction is not entered (the fake raises when
        it is listed) and not measured; next to a measured path it makes the item
        partial."""
        junction = {"attributes": FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
                    "reparse_tag": IO_REPARSE_TAG_MOUNT_POINT}
        tree = cleanup_tree()
        put(tree, TEMP_DIR, folder({"elsewhere.bin": 900}, **junction))
        put(tree, WER_ARCHIVE, folder({"Report.wer": 300}, **junction))
        put(tree, WER_QUEUE, {"Queued.wer": 70})
        summary, _ = self.collect(FakeMachine({"C": tree}))

        with self.subTest("temp-user: the only path is a link"):
            temp = self.cleanup_item(summary, "temp-user")
            self.assertEqual(temp.get("status"), "not_measured", temp)
            self.assertIsNone(temp.get("bytes"), temp)
            self.assertIsNone(temp.get("bytes_older"), temp)
            self.assertIn("link", str(temp.get("reason")), temp)
            self.assertTrue(self.notes_about_entry(summary, "temp-user"),
                            self.not_checked(summary))

        with self.subTest("wer-reports: one path a link, one measured"):
            wer = self.cleanup_item(summary, "wer-reports")
            self.assertEqual(wer.get("status"), "partial", wer)
            self.assertEqual(wer.get("bytes"), 70, wer)
            self.assertTrue(self.notes_about_entry(summary, "wer-reports"),
                            self.not_checked(summary))

        _, entries = self.load_catalogue()
        for entry_id, entry in entries:
            if entry.get("min_age_days", 0) > 0:
                with self.subTest(block=entry_id):
                    self.assertIn("(Get-Item -LiteralPath $root -Force -ErrorAction Stop)"
                                  ".Attributes", entry["block"])
                    self.assertRegex(entry["block"], r"if \(\$rootAttributes -band "
                                     r"\[IO\.FileAttributes\]::ReparsePoint\) \{ "
                                     r"\"Skipped[^\"]*\"; continue \}")

    def test_recycle_bin_block_reports_the_result(self):
        code, stdout, stderr, _, _ = self.run_block("recycle-bin")
        self.assertEqual(code, 0, stderr[-300:])
        text = block_text(stdout)
        clear = re.search(r"Clear-RecycleBin[^\n]*", text)
        self.assertIsNotNone(clear, text)
        self.assertIn("-ErrorAction Stop", clear.group(0))
        start = text.rfind("try {", 0, clear.start())
        emptied = text.find("emptied", clear.end())
        catch = text.find("catch {", clear.end())
        self.assertTrue(0 <= start < clear.start() < emptied < catch, text)
        self.assertEqual(text.count("bin emptied"), 1, text)  # only after a call that did not fail
        self.assertIn("NativeErrorCode -eq 3", text)  # an empty bin is not a failure
        self.assertIn("NOT emptied", text[catch:])
        self.assertIn("Namespace(10).Items().Count", text)  # read back

    def test_delivery_optimization_block_checks_elevation_and_read_back(self):
        code, stdout, stderr, _, _ = self.run_block("delivery-optimization")
        self.assertEqual(code, 0, stderr[-300:])
        text = block_text(stdout)
        role = re.search(r"if \(-not \$principal\.IsInRole\(\[Security\.Principal\."
                         r"WindowsBuiltInRole\]::Administrator\)\) \{ '[^'\n]*'; return \}",
                         text)
        self.assertIsNotNone(role, text)  # not elevated: a message and stop
        delete = re.search(r"Delete-DeliveryOptimizationCache -Force[^\n]*", text)
        self.assertIsNotNone(delete, text)
        self.assertTrue(role.start() < delete.start(), text)
        self.assertIn("-ErrorAction Stop", delete.group(0))
        self.assertGreaterEqual(text.rfind("try {", 0, delete.start()), 0, text)
        listing = re.search(r"Get-ChildItem -LiteralPath \$cache[^\n]*", text)
        self.assertIsNotNone(listing, text)
        self.assertIn("-ErrorVariable readErrors", listing.group(0))
        left = text.find("Files left in the cache")
        self.assertRegex(text[:left], r"if \(\$readErrors\.Count -gt 0\) \{[^\n]*not known"
                                      r"[^\n]*\}\s*else \{ \"$")

    # --- code-review fixes of M3, round 2 -------------------------------------------------

    def test_admin_blocks_stop_when_not_elevated(self):
        """Every block of an entry with ``needs_admin`` true stops with a message before it
        does anything when the shell is not elevated."""
        _, entries = self.load_catalogue()
        admin = [(entry_id, entry) for entry_id, entry in entries if entry.get("needs_admin")]
        self.assertTrue(admin)
        for entry_id, entry in admin:
            with self.subTest(entry=entry_id):
                code, stdout, stderr, _, _ = self.run_block(str(entry_id))
                self.assertEqual(code, 0, stderr[-300:])
                text = block_text(stdout)
                principal = text.find("$principal = New-Object Security.Principal."
                                      "WindowsPrincipal([Security.Principal.WindowsIdentity]"
                                      "::GetCurrent())")
                self.assertGreaterEqual(principal, 0, text)
                role = re.search(r"if \(-not \$principal\.IsInRole\(\[Security\.Principal\."
                                 r"WindowsBuiltInRole\]::Administrator\)\) \{ 'Not elevated"
                                 r"[^'\n]*nothing deleted'; return \}", text)
                self.assertIsNotNone(role, text)
                self.assertLess(principal, role.start(), text)
                acts = [m.start() for m in re.finditer(
                    r"Remove-Item|Delete-DeliveryOptimizationCache|Stop-Service|Get-Service|"
                    r"Get-ChildItem|Clear-RecycleBin", text)]
                self.assertTrue(acts, text)
                self.assertLess(role.end(), min(acts), text)

    def test_age_blocks_count_folders_not_read(self):
        """An age-based block collects the errors of both listings and prints how many
        folders it could not read, and that the counts are incomplete when there are any:
        an unreadable folder must not look like an empty one."""
        _, entries = self.load_catalogue()
        aged = [(entry_id, entry) for entry_id, entry in entries
                if entry.get("min_age_days", 0) > 0]
        self.assertEqual(len(aged), 5)
        for entry_id, entry in aged:
            with self.subTest(entry=entry_id):
                block = entry["block"]
                self.assertNotIn("+listErrors", block)  # no stale errors from an outer scope
                self.assertRegex(block, r"\$notRead = 0")
                listings = [line for line in block.split("\n") if "Get-ChildItem" in line]
                self.assertEqual(len(listings), 2, block)
                names = []
                for line in listings:
                    found = re.search(r"Get-ChildItem -LiteralPath \$dir -(?:Directory|File) "
                                      r"-Force -ErrorAction SilentlyContinue "
                                      r"-ErrorVariable (\w+) \|", line)
                    self.assertIsNotNone(found, line)
                    names.append(found.group(1))
                self.assertEqual(len(set(names)), 2, names)
                check = re.search(r"\n *if \(\$" + names[0] + r"\.Count -gt 0 -or \$"
                                  + names[1] + r"\.Count -gt 0\) \{ \$notRead\+\+;", block)
                self.assertIsNotNone(check, block)
                self.assertGreater(check.start(), block.find(listings[1]), block)
                self.assertRegex(block, r"catch \{ \$notRead\+\+;[^\n]*\"Skipped, the folder "
                                        r"could not be read")
                final = re.search(r"\n *\"Deleted files: [^\n]*Folders that could not be "
                                  r"read: \$notRead\.\"\n *if \(\$notRead -gt 0\) \{ \"The "
                                  r"counts are incomplete: \$notRead [^\n]*\" \}\n", block)
                self.assertIsNotNone(final, block)
                self.assertGreater(final.start(), check.end(), block)

    def test_reparse_folders_not_measured(self):
        """A cleanup folder or subfolder with a reparse tag that is not a name surrogate
        (a hydrated cloud folder, no RECALL_ON_OPEN) is skipped by the block, so it is not
        in ``bytes`` and not in ``bytes_older``."""
        cloud = {"attributes": FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
                 "reparse_tag": IO_REPARSE_TAG_CLOUD_6}
        ancient = (NOW - timedelta(days=60)).timestamp()  # older than every min_age_days
        tree = cleanup_tree()
        put(tree, TEMP_DIR + "\\Synced", folder({"old.bin": file(900, mtime=OLD)}, **cloud))
        put(tree, WER_ARCHIVE, folder({"Report.wer": file(300, mtime=ancient)}, **cloud))
        put(tree, WER_QUEUE, {"Queued.wer": file(70, mtime=ancient),
                              "Linked": folder({"Deep.wer": file(500, mtime=ancient)},
                                               **cloud)})
        summary, _ = self.collect(FakeMachine({"C": tree}))

        with self.subTest("temp-user: a cloud subfolder is left out"):
            temp = self.cleanup_item(summary, "temp-user")
            self.assertEqual(temp.get("bytes"), 15, temp)
            self.assertEqual(temp.get("bytes_older"), 10, temp)
            self.assertEqual(temp.get("files_older"), 1, temp)

        with self.subTest("wer-reports: a cloud root and a cloud subfolder are left out"):
            wer = self.cleanup_item(summary, "wer-reports")
            self.assertEqual(wer.get("status"), "partial", wer)
            self.assertEqual(wer.get("bytes"), 70, wer)
            self.assertEqual(wer.get("bytes_older"), 70, wer)
            self.assertEqual(wer.get("files_older"), 1, wer)
            self.assertIn("link", str(wer.get("reason")), wer)

    # --- final review, round 1 ----------------------------------------------------------

    def test_recycle_bin_desktop_ini_is_not_a_file(self):
        """Every account folder of a bin holds a hidden desktop.ini; a bin with nothing
        else is empty, a bin with a deleted file still counts that file."""
        hidden = FILE_ATTRIBUTE_ARCHIVE | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
        bin_attributes = FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM

        def tree(extra=None):
            tree = cleanup_tree()
            own = {"desktop.ini": file(129, attributes=hidden)}
            own.update(extra or {})
            tree["$Recycle.Bin"] = folder(
                {SID_READ: own, SID_DENIED: {"DESKTOP.INI": file(129, attributes=hidden)}},
                attributes=bin_attributes)
            return tree

        with self.subTest("only desktop.ini: empty"):
            summary, _ = self.collect(FakeMachine({"C": tree()}))
            item = self.cleanup_item(summary, "recycle-bin")
            self.assertEqual(item.get("status"), "empty", item)
            self.assertEqual(item.get("files"), 0, item)
            self.assertEqual(item.get("bytes"), 0, item)
            self.assertEqual(self.notes_about_entry(summary, "recycle-bin"), [])

        with self.subTest("a deleted file next to desktop.ini: counted"):
            summary, _ = self.collect(FakeMachine({"C": tree({"$RQ7XK2M.txt": 3000,
                                                               "$IQ7XK2M.txt": 98})}))
            item = self.cleanup_item(summary, "recycle-bin")
            self.assertEqual(item.get("status"), "read", item)
            self.assertEqual(item.get("files"), 2, item)
            self.assertEqual(item.get("bytes"), 3098, item)

        with self.subTest("desktop.ini counts in an entry without ignore_names"):
            temp_tree = tree()
            put(temp_tree, TEMP_DIR + "\\desktop.ini", file(129, attributes=hidden))
            summary, _ = self.collect(FakeMachine({"C": temp_tree}))
            temp = self.cleanup_item(summary, "temp-user")
            self.assertEqual(temp.get("files"), 3, temp)

        with self.subTest("a bad ignore_names stops the run"):
            data, _ = self.load_catalogue()
            broken = copy.deepcopy(data)
            catalogue_entries(broken)[0][1]["ignore_names"] = "desktop.ini"
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            path = Path(tmp.name).resolve() / "cleanup-bad-ignore.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            code, stdout, stderr = self.run_main(self.data_dir(), FakeMachine({"C": tree()}),
                                                 cleanup=path)
            self.assertEqual(code, 2, (stdout[:300], stderr[-300:]))

    def test_summary_cleanup_items_have_no_block(self):
        """The blocks stay out of the summary (its budget); the detail file and --block
        still give each one word for word."""
        summary, _ = self.collect(FakeMachine({"C": cleanup_tree()}))
        _, entries = self.load_catalogue()
        blocks = {entry_id: entry["block"] for entry_id, entry in entries}
        items = self.items(summary, "cleanup")
        self.assertEqual(len(items), len(blocks), items)
        detail = {item.get("id"): item for item in self.items(self.detail(summary), "cleanup")}
        for item in items:
            with self.subTest(item=item.get("entry")):
                self.assertNotIn("block", item)
                self.assertEqual(detail[item["id"]].get("block"), blocks[item["entry"]])
                code, stdout, stderr, _, _ = self.run_block(item["id"])
                self.assertEqual(code, 0, stderr[-300:])
                self.assertTrue(stdout.rstrip("\n").endswith(blocks[item["entry"]]), stdout)

    def test_wer_link_and_missing_path_not_measured(self):
        """ReportArchive missing and ReportQueue a junction: nothing was measured, so the
        item is not_measured with no sizes, not partial with 0 bytes."""
        junction = {"attributes": FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT,
                    "reparse_tag": IO_REPARSE_TAG_MOUNT_POINT}
        tree = cleanup_tree()
        wer = tree["ProgramData"]["Microsoft"]["Windows"]["WER"]
        del wer["ReportArchive"]
        wer["ReportQueue"] = folder({"Queued.wer": 70}, **junction)
        summary, _ = self.collect(FakeMachine({"C": tree}))
        item = self.cleanup_item(summary, "wer-reports")
        self.assertEqual(item.get("status"), "not_measured", item)
        for key in ("bytes", "files", "gb", "bytes_older", "files_older", "gb_older"):
            self.assertIn(key, item)
            self.assertIsNone(item[key], (key, item))
        self.assertEqual(item.get("skipped_paths"), 1, item)
        self.assertIn("link", str(item.get("reason")), item)
        self.assertTrue(self.notes_about_entry(summary, "wer-reports"),
                        self.not_checked(summary))

        with self.subTest("both paths missing is still empty"):
            tree = cleanup_tree()
            del tree["ProgramData"]["Microsoft"]["Windows"]["WER"]
            summary, _ = self.collect(FakeMachine({"C": tree}))
            item = self.cleanup_item(summary, "wer-reports")
            self.assertEqual(item.get("status"), "empty", item)
            self.assertEqual(item.get("bytes"), 0, item)

    def test_unreadable_and_missing_path_is_unreadable(self):
        """ReportArchive missing and ReportQueue cannot be listed: nothing was read, so
        the item is unreadable with no sizes, not partial with 0 bytes."""
        tree = cleanup_tree()
        wer = tree["ProgramData"]["Microsoft"]["Windows"]["WER"]
        del wer["ReportArchive"]
        wer["ReportQueue"] = folder({"Queued.wer": 70}, error=denied(WER_QUEUE))
        summary, _ = self.collect(FakeMachine({"C": tree}))
        item = self.cleanup_item(summary, "wer-reports")
        self.assertEqual(item.get("status"), "unreadable", item)
        for key in ("bytes", "files", "gb", "bytes_older", "files_older", "gb_older"):
            self.assertIn(key, item)
            self.assertIsNone(item[key], (key, item))
        self.assertEqual(item.get("unreadable_dirs"), 1, item)
        self.assertIn("denied", str(item.get("reason")), item)
        self.assertTrue(self.notes_about_entry(summary, "wer-reports"),
                        self.not_checked(summary))


if __name__ == "__main__":
    unittest.main()

"""Show how full each fixed drive is, its largest folders to a set depth and its large
files (read-only snapshot).

Machine inputs (four injectable functions, all or none):

- ``list_drives()``: ``(letter, type)`` pairs from ``GetLogicalDrives`` and
  ``GetDriveTypeW``; only ``DRIVE_FIXED`` (3) drives are walked.
- ``scan_dir(path)``: the entries of one directory from ``os.scandir`` and
  ``stat(follow_symlinks=False)`` (the cached find data, so no file is opened): dicts
  ``{name, is_dir, size, attributes, reparse_tag, mtime, ctime}``: ``mtime`` and
  ``ctime`` (the creation time: ``st_birthtime``, else ``st_ctime`` on Windows) are
  POSIX seconds, ``ctime`` ``None`` when it is not known. A read error is an
  ``OSError``.
- ``disk_usage(path)``: ``shutil.disk_usage`` of the drive root.
- ``is_admin()``: whether the run has administrator rights.

The walk is iterative (no Python recursion), from the drive root (depth 0):

- a directory whose reparse tag has the name-surrogate bit (``0x20000000``: mount
  points, junctions, symbolic links) is not entered (``counts.reparse_skipped``);
- a directory with ``FILE_ATTRIBUTE_RECALL_ON_OPEN`` is not entered, because listing
  it makes the sync provider fetch it (``counts.cloud_only_dirs``);
- every other directory is entered, also one with a cloud reparse tag;
- a file with ``FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`` or ``FILE_ATTRIBUTE_OFFLINE`` is
  not on the disk: it counts in ``cloud_only_files`` and ``cloud_only_bytes`` of its
  folder, never in ``bytes``, ``files`` or the large files;
- a directory whose listing raises ``FileNotFoundError`` or ``NotADirectoryError``
  disappeared during the walk: it counts in ``counts.vanished_dirs``, is left out of
  ``folders`` and is not unreadable; at the drive root such an error is unreadable;
- any other ``OSError`` makes the directory unreadable: it goes to the detail list
  ``unreadable`` (path and reason) and its folder has ``listed: false``.

Every folder to ``depth`` of ``data/scan.json`` has a record; what lies deeper rolls up
into its ancestor at that depth, and every record rolls up into its parent. ``bytes``
and ``files`` are the sizes (``st_size``) and number of the files on the disk in the
readable part; ``unreadable_dirs`` counts the unreadable directories in and under the
folder, ``readable_part`` is true when there is at least one, and ``unreadable_key`` is
the SHA-256 of their lower-case paths, sorted and joined with a newline, encoded with
``encode("utf-8", "surrogatepass")`` (``null`` when there is none). A skipped directory
has ``listed: false``, ``skipped`` (``reparse`` or ``cloud_only``) and ``bytes`` 0.

Nothing is judged and nothing on the machine is changed. The summary goes to stdout and
to ``work/files-<UTC stamp>.summary.json``; every folder, every large file and the
unreadable directories are in ``work/files-<UTC stamp>.detail.json``. Folders (ids
``f``) and large files (ids ``l``) are numbered by their place in each run. The summary
holds ``summary_folders`` and ``summary_large_files`` of them; to stay within
``SUMMARY_MAX_CHARS`` ``folders`` is cut from its end first, then ``large_files``
(``truncated_folders`` and ``truncated_large_files`` count every item left out,
``truncated`` repeats the first). ``--detail <id>`` prints one folder, large file,
change or cleanup item of the newest detail file.

Comparison with the previous run: the baseline is ``state/ush-files.json``
(``ush-files.elevated.json`` with administrator rights, ``baseline.py``), with three
sources per drive, so a drive absent in a run is ``not_read`` and keeps its items:
``folders:<L>`` (key: lower-case path; compared ``bytes`` and ``files``),
``large_files:<L>`` (key: lower-case path; compared ``bytes`` and ``modified``) and
``drives:<L>`` (key: the letter; compared ``used_bytes``). The other fields of an item
(``listed``, ``unreadable_key``, ``parent_path``, ``parent_key``) serve the rules of
``compare_drive`` and never give a change. Changes (ids ``d``) are sorted by the absolute
``delta_bytes``, largest first; the summary holds ``summary_changes`` of them (cut last by
the budget, ``truncated_changes``). Whatever differs but cannot be compared without a
false alarm counts in ``counts.not_compared``, is listed in the detail ``not_compared``
and named in ``not_checked``. A large file of the previous run that is still on the disk
but below the threshold is ``large_file_changed``, not gone; one that is now only in the
cloud is not compared. A large file is new or gone only when every directory on its
path was listed in both runs: for a file deeper than the folder records, its ancestor at
``depth`` must be listed in both and hold the same unreadable (``unreadable_key``) and
skipped directories (``skipped_key``, junctions and cloud-only folders). A baseline item
with no text path or a compared field of the wrong type is not compared. A large file
keeps its creation time (``created``, UTC ISO 8601 or null; not a compared field): a
file that is new to the large-file list but was created before the previous run existed
then below the threshold or in another folder, so it is not compared (its earlier size
is not known); with no creation time it is ``large_file_new``. A gone large file and a
new one on the same drive with the same ``bytes`` and the same known ``created`` look
like one file moved or renamed: neither is a change, both are not compared (each names
the other path). A new or gone folder
that was skipped (junction, cloud only) or could not be listed has no size that was
read, so it gives no change and is not compared. A large file whose ``bytes`` are the
same and whose ``modified`` moved by exactly one hour gives no change (a FAT time stamp
after a daylight-saving switch). Each change has ``delta_bytes``, ``delta_gb`` (one
decimal) and ``delta_mb`` (one decimal, signed).

The source ``scan_settings`` (key: the drive letter) keeps the ``depth`` and
``large_file_bytes`` each drive was walked with. When this run's value differs, the
sources that depend on it (``folders:<L>`` on ``depth``, ``large_files:<L>`` on
``large_file_bytes``) get the comparison state ``settings_changed``: no changes and a
``not_checked`` item. A baseline without ``scan_settings`` is compared as before.

Cleanup catalogue (``data/cleanup.json``, read from ``CLEANUP_FILE``; a bad catalogue
exits 2 before anything is walked): each entry is measured with the same ``scan_dir`` and
the same rules for junctions and cloud files, apart from the main walk and its counts.
``%NAME%`` in a path comes from the environment (the exact name, then any case);
``<drive>`` stands for each fixed drive of the run. A summary item (ids ``c``, the
catalogue order) has ``bytes``, ``files`` and ``gb`` (two decimals), with
``min_age_days`` > 0 also ``bytes_older``, ``files_older`` and ``gb_older`` (both
``mtime`` and ``ctime`` before the run time minus that many days, i.e. the later of the
two; with ``ctime`` unknown, ``mtime`` alone), and ``status``: ``read``; ``empty`` (no
file, or the folder does not exist); ``partial`` (some folder could not be listed, or a
path was not measured: the sizes count the rest; a ``not_checked`` item);
``unreadable`` (no path could be listed, or a variable is not set: sizes ``null``; a
``not_checked`` item; also when no path was read, at least one could not be listed and
the others do not exist or are links: a missing path is not a size of the others); ``not_measured`` (no path was measured: every path that exists
is itself a junction, a symbolic link or a cloud-only folder, not entered, and none
could not be listed; sizes ``null``; a ``not_checked`` item). Whether a path is such a link is seen in its parent's listing (the parent is
listed first); when the parent cannot be listed or does not show the name, the path is
listed as before. The item repeats the entry's ``risk``, ``needs_admin``,
``conditions`` and ``rollback`` and counts ``skipped_paths``; the detail item adds the
``block``, ``expanded_paths``, its unreadable folders and its ``skipped`` paths (the
summary leaves the blocks out, so they do not take its budget). A file named in the
entry's ``ignore_names`` (any case) is not counted.
``--block <id>[,<id>]`` (a catalogue id or a ``c`` id) only prints the blocks: it needs
no data directory, calls no machine function and writes nothing; an unknown id exits 1.
Nothing here deletes anything: the blocks are for the user to run.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline  # called as baseline.save(...), so tests can patch it
import datadir
from psrun import dump, with_ids

SKILL = "ush-files"
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
DETAIL_SECTIONS = ("folders", "large_files", "changes", "cleanup")
SOURCE_KINDS = ("folders", "large_files", "drives")  # baseline sources, one per drive
# Baseline source with the scan settings each drive was walked with: {letter: settings}.
SCAN_SOURCE = "scan_settings"
# The setting each source depends on: a change of it makes the source not comparable.
SETTING_SOURCES = (("depth", "folders"), ("large_file_bytes", "large_files"))
SETTINGS_CHANGED = "settings_changed"  # comparison state of such a source
FOLDER_FIELDS = ("bytes", "files")
LARGE_FILE_FIELDS = ("bytes", "modified")
DRIVE_FIELDS = ("used_bytes",)
NOTE_PATHS_MAX = 10
SCAN_FILE = Path(__file__).absolute().parents[1] / "data" / "scan.json"
SCAN_KEYS = {  # key: smallest allowed value
    "depth": 0,
    "large_file_bytes": 1,
    "summary_folders": 0,
    "summary_large_files": 0,
    "summary_changes": 0,
}
CLEANUP_FILE = Path(__file__).absolute().parents[1] / "data" / "cleanup.json"
CLEANUP_TEXT_KEYS = ("id", "what", "conditions", "rollback", "block")
CLEANUP_RISKS = ("low", "medium", "high")
DRIVE_PLACEHOLDER = "<drive>"
ENV_VARIABLE = re.compile(r"%([^%]+)%")

GB = 1024 ** 3
MB = 1024 ** 2
DST_SHIFT_S = 3600  # a FAT time stamp after a daylight-saving switch
DRIVE_FIXED = 3
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
NOT_ON_DISK = FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_OFFLINE
NAME_SURROGATE_BIT = 0x20000000
VANISHED = (FileNotFoundError, NotADirectoryError)
REASON_MAX = 300


def to_gb(value):
    return None if value is None else round(value / GB, 1)


def error_text(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= REASON_MAX else text[:REASON_MAX - 3] + "..."


def as_count(value) -> int:
    """A non-negative int from an entry field; anything else is 0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def modified_text(mtime):
    """ISO 8601 UTC time of a POSIX ``mtime`` (whole seconds), or None."""
    if isinstance(mtime, bool) or not isinstance(mtime, (int, float)):
        return None
    try:
        moment = datetime.fromtimestamp(mtime, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat(timespec="seconds")


def join_path(parent: str, name: str) -> str:
    return parent + name if parent.endswith("\\") else f"{parent}\\{name}"


def unreadable_key(paths: list):
    if not paths:
        return None
    text = "\n".join(sorted(path.lower() for path in paths))
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def load_scan(path: Path):
    """``(settings, None)`` or ``(None, reason)`` for ``data/scan.json``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{path} could not be read: {error_text(exc)}"
    if not isinstance(data, dict):
        return None, f"{path} does not hold a JSON object"
    settings = {}
    for key, low in SCAN_KEYS.items():
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < low:
            return None, f"{path}: {key} must be an integer of at least {low}, got {value!r}"
        settings[key] = value
    return settings, None


def load_cleanup(path: Path):
    """``(entries, None)`` or ``(None, reason)`` for ``data/cleanup.json``.

    The file holds ``{"entries": [...]}``; every entry needs a unique text ``id``, the
    texts ``what``, ``conditions``, ``rollback`` and ``block``, a non-empty list of text
    ``paths``, ``risk`` (low, medium or high), a bool ``needs_admin`` and an integer
    ``min_age_days`` of at least 0. ``ignore_names`` is optional: a list of texts, the
    names of files (any case) the measurement leaves out (``desktop.ini`` of a recycle
    bin, which Windows keeps in every bin).
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{path} could not be read: {error_text(exc)}"
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return None, f"{path} does not hold an object with a non-empty entries list"
    seen = set()
    for number, entry in enumerate(entries, 1):
        where = f"{path}: entry {number}"
        if not isinstance(entry, dict):
            return None, f"{where} is not an object"
        for key in CLEANUP_TEXT_KEYS:
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                return None, f"{where}: {key} must be a non-empty text"
        if entry["id"] in seen:
            return None, f"{where}: the id {entry['id']!r} is used twice"
        seen.add(entry["id"])
        paths = entry.get("paths")
        if (not isinstance(paths, list) or not paths
                or not all(isinstance(p, str) and p.strip() for p in paths)):
            return None, f"{where}: paths must be a non-empty list of texts"
        if entry.get("risk") not in CLEANUP_RISKS:
            return None, f"{where}: risk must be one of {', '.join(CLEANUP_RISKS)}"
        if not isinstance(entry.get("needs_admin"), bool):
            return None, f"{where}: needs_admin must be true or false"
        days = entry.get("min_age_days")
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            return None, f"{where}: min_age_days must be an integer of at least 0"
        ignore = entry.get("ignore_names", [])
        if (not isinstance(ignore, list)
                or not all(isinstance(n, str) and n.strip() for n in ignore)):
            return None, f"{where}: ignore_names must be a list of texts"
    return entries, None


def find_cleanup(entries: list, wanted: str):
    """``(c id, entry)`` for a catalogue id or a ``c<n>`` id, or None."""
    for number, entry in enumerate(entries, 1):
        if wanted in (entry["id"], f"c{number}"):
            return f"c{number}", entry
    return None


# --- walk -------------------------------------------------------------------------------
def drive_letter(drive) -> str:
    return str(drive[0]).strip().rstrip(":\\").upper()


def new_folder(path: str, letter: str, depth: int, parent) -> dict:
    return {"path": path, "drive": letter, "depth": depth, "bytes": 0, "files": 0,
            "cloud_only_files": 0, "cloud_only_bytes": 0, "listed": False, "skipped": None,
            "_parent": parent, "_unread": [], "_skip": [], "_vanished": False}


def walk_drive(letter: str, scan_dir, settings: dict, counts: dict, large: list,
               unreadable: list, watch=frozenset(), watched=None):
    """Walk one drive; return ``(folders, root_status, root_reason)``.

    ``watch`` holds the lower-case paths of the large files of the previous run; a file
    on that list that is now below the threshold or only in the cloud is recorded in
    ``watched`` (lower-case path -> ``{bytes, modified, cloud_only}``), so it is not
    taken for a file that is gone.
    """
    watched = {} if watched is None else watched
    depth_max = settings["depth"]
    threshold = settings["large_file_bytes"]
    root = f"{letter}:\\"
    folders = [new_folder(root, letter, 0, None)]
    root_status, root_reason = "read", None
    stack = [(root, 0, 0)]  # path, depth, index of its folder (own, or its ancestor's)
    while stack:
        path, depth, index = stack.pop()
        folder = folders[index]
        own = depth <= depth_max
        try:
            entries = scan_dir(path)
        except OSError as exc:
            if depth > 0 and isinstance(exc, VANISHED):
                counts["vanished_dirs"] += 1
                if own:
                    folder["_vanished"] = True
                continue
            reason = error_text(exc)
            unreadable.append({"drive": letter, "path": path, "reason": reason})
            folder["_unread"].append(path)
            if depth == 0:
                root_status, root_reason = "unreadable", reason
            continue
        counts["dirs_listed"] += 1
        if own:
            folder["listed"] = True
        if depth == 0 and not entries:
            root_status = "empty"
        for entry in entries:
            name = str(entry["name"])
            attributes = as_count(entry.get("attributes"))
            tag = as_count(entry.get("reparse_tag"))
            child = join_path(path, name)
            if entry.get("is_dir"):
                child_depth = depth + 1
                skipped = None
                if tag & NAME_SURROGATE_BIT:
                    skipped = "reparse"
                    counts["reparse_skipped"] += 1
                elif attributes & FILE_ATTRIBUTE_RECALL_ON_OPEN:
                    skipped = "cloud_only"
                    counts["cloud_only_dirs"] += 1
                child_index = index
                if child_depth <= depth_max:
                    child_index = len(folders)
                    folders.append(new_folder(child, letter, child_depth, index))
                    folders[child_index]["skipped"] = skipped
                if skipped is None:
                    stack.append((child, child_depth, child_index))
                else:
                    folders[child_index]["_skip"].append(child)
                continue
            size = as_count(entry.get("size"))
            if attributes & NOT_ON_DISK:
                folder["cloud_only_files"] += 1
                folder["cloud_only_bytes"] += size
                counts["cloud_only_files"] += 1
                if watch and child.lower() in watch:
                    watched[child.lower()] = {"bytes": None, "modified": None,
                                              "cloud_only": True}
                continue
            folder["bytes"] += size
            folder["files"] += 1
            counts["files"] += 1
            if size >= threshold:
                large.append({"path": child, "drive": letter, "depth": depth + 1,
                              "bytes": size, "gb": to_gb(size),
                              "modified": modified_text(entry.get("mtime")),
                              "created": modified_text(entry.get("ctime"))})
            elif watch and child.lower() in watch:
                watched[child.lower()] = {"bytes": size,
                                          "modified": modified_text(entry.get("mtime")),
                                          "cloud_only": False}
    # Parents are created before their children, so the reverse order rolls up.
    for folder in reversed(folders):
        parent = folder["_parent"]
        if parent is not None:
            target = folders[parent]
            for key in ("bytes", "files", "cloud_only_files", "cloud_only_bytes"):
                target[key] += folder[key]
            target["_unread"].extend(folder["_unread"])
            target["_skip"].extend(folder["_skip"])
    result = []
    for folder in folders:
        if folder["_vanished"]:
            continue
        paths = folder["_unread"]
        result.append({
            "path": folder["path"], "drive": letter, "depth": folder["depth"],
            "bytes": folder["bytes"], "gb": to_gb(folder["bytes"]), "files": folder["files"],
            "cloud_only_files": folder["cloud_only_files"],
            "cloud_only_bytes": folder["cloud_only_bytes"],
            "listed": folder["listed"], "skipped": folder["skipped"],
            "readable_part": bool(paths), "unreadable_dirs": len(paths),
            "unreadable_key": unreadable_key(paths),
            "skipped_key": unreadable_key(folder["_skip"]),
        })
    return result, root_status, root_reason


# --- cleanup catalogue ------------------------------------------------------------------
def to_gb2(value):
    return None if value is None else round(value / GB, 2)


def env_value(environ, name: str):
    """The value of ``name``: the exact spelling first, then any case; None if unset."""
    value = environ.get(name)
    if value is None:
        upper = name.upper()
        value = next((v for k, v in environ.items() if str(k).upper() == upper), None)
    return value if isinstance(value, str) and value.strip() else None


def expand_paths(paths: list, environ, letters: list):
    """``(expanded paths, unset variable names)`` of catalogue ``paths``: ``%NAME%`` from
    ``environ`` and ``<drive>`` once for each fixed drive of the run."""
    expanded, unset = [], []
    for path in paths:
        def value(match):
            found = env_value(environ, match.group(1))
            if found is None:
                if match.group(1) not in unset:
                    unset.append(match.group(1))
                return match.group(0)
            return found.rstrip("\\")
        text = ENV_VARIABLE.sub(value, path)
        if DRIVE_PLACEHOLDER in text:
            expanded.extend(text.replace(DRIVE_PLACEHOLDER, letter) for letter in letters)
        else:
            expanded.append(text)
    return expanded, unset


def is_older(entry, cutoff) -> bool:
    """True when a file is older than ``cutoff`` (a POSIX time): both its last write
    (``mtime``) and its creation (``ctime``) are before it, so the later of the two
    counts. A file copied or unpacked just now keeps an old ``mtime`` but gets a new
    ``ctime``. With ``ctime`` unknown (``None``) only ``mtime`` counts; with no
    ``mtime`` the file is not older."""
    times = []
    for key in ("mtime", "ctime"):
        value = entry.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            times.append(value)
        elif key == "mtime":
            return False
    return max(times) < cutoff


def is_reparse_dir(entry) -> bool:
    """True for a directory entry the cleanup measurement does not enter: any reparse
    point (``FILE_ATTRIBUTE_REPARSE_POINT`` or a reparse tag; junctions, symbolic links,
    cloud folders...) or a cloud-only folder (``FILE_ATTRIBUTE_RECALL_ON_OPEN``). The
    cleanup blocks skip every folder with ``[IO.FileAttributes]::ReparsePoint``, so the
    measurement counts only what a block can reach."""
    attributes = as_count(entry.get("attributes"))
    return bool(attributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_RECALL_ON_OPEN)
                or as_count(entry.get("reparse_tag")))


def root_skip(root: str, scan_dir):
    """``(state, reason)`` for a cleanup root that must not be listed, from the entry of
    ``root`` in its parent's listing: ``("skipped", ...)`` for any reparse point (a
    junction, a symbolic link, a cloud folder: ``is_reparse_dir``) or a cloud-only
    folder, ``("missing", ...)`` when
    the parent does not exist. ``(None, None)`` means: list ``root`` itself (a plain
    folder, a drive root, a parent that cannot be listed, or a name the parent does not
    show, e.g. an 8.3 short name; then the root's own listing decides)."""
    path = root.rstrip("\\")
    if "\\" not in path or path.endswith(":"):
        return None, None
    name = path[path.rfind("\\") + 1:].casefold()
    try:
        entries = scan_dir(parent_of(path))
    except VANISHED as exc:
        return "missing", error_text(exc)
    except OSError:
        return None, None
    for entry in entries:
        if str(entry.get("name", "")).casefold() != name:
            continue
        if as_count(entry.get("reparse_tag")) & NAME_SURROGATE_BIT:
            return "skipped", ("the folder is a link (junction or symbolic link) to another "
                               "place, so it was not entered and not measured")
        if as_count(entry.get("attributes")) & FILE_ATTRIBUTE_RECALL_ON_OPEN:
            return "skipped", ("the folder is only in the cloud, so it was not entered and "
                               "not measured")
        if is_reparse_dir(entry):
            return "skipped", ("the folder is a link or another reparse point (for example a "
                               "cloud folder), which the block skips, so it was not entered "
                               "and not measured")
        return None, None
    return None, None


def measure_dir(root: str, scan_dir, cutoff, ignore=frozenset()):
    """Sizes of the files on the disk in and under ``root``, by the walk rules.

    Returns ``{state, reason, bytes, files, bytes_older, files_older, unreadable}``:
    ``state`` is ``missing`` (the root does not exist), ``skipped`` (the root itself is
    a reparse point or a cloud-only folder, seen in its parent's listing: not entered),
    ``unreadable`` (the root could not be listed) or ``read``; ``unreadable``
    lists the subdirectories that could not be listed. ``cutoff`` is a POSIX time or
    None: a file is older when it was both written and created before it
    (``is_older``). A subdirectory that disappears during the walk is left out, and so
    is every reparse-point or cloud-only subdirectory (``is_reparse_dir``), as in the
    blocks; unlike the main walk, a folder with a cloud reparse tag is not entered. A
    file whose casefolded name is in ``ignore`` (casefolded names) is not counted.
    """
    result = {"state": "read", "reason": None, "bytes": 0, "files": 0, "bytes_older": 0,
              "files_older": 0, "unreadable": []}
    state, reason = root_skip(root, scan_dir)
    if state is not None:
        result.update({"state": state, "reason": reason})
        return result
    stack = [root]
    while stack:
        path = stack.pop()
        try:
            entries = scan_dir(path)
        except OSError as exc:
            if path == root:
                result["state"] = "missing" if isinstance(exc, VANISHED) else "unreadable"
                result["reason"] = error_text(exc)
                return result
            if not isinstance(exc, VANISHED):
                result["unreadable"].append({"path": path, "reason": error_text(exc)})
            continue
        for entry in entries:
            attributes = as_count(entry.get("attributes"))
            if entry.get("is_dir"):
                if is_reparse_dir(entry):
                    continue
                stack.append(join_path(path, str(entry["name"])))
                continue
            if attributes & NOT_ON_DISK:
                continue
            if ignore and str(entry.get("name", "")).casefold() in ignore:
                continue
            size = as_count(entry.get("size"))
            result["bytes"] += size
            result["files"] += 1
            if cutoff is not None and is_older(entry, cutoff):
                result["bytes_older"] += size
                result["files_older"] += 1
    return result


def measure_cleanup(entries: list, letters: list, scan_dir, environ, now, drives_known):
    """``(items, notes)``: one item per catalogue entry (ids ``c``), and the
    ``not_checked`` notes for entries that were not read in full."""
    items, notes = [], []
    for number, entry in enumerate(entries, 1):
        item_id = f"c{number}"
        days = entry["min_age_days"]
        cutoff = (now - timedelta(days=days)).timestamp() if days > 0 else None
        expanded, unset = expand_paths(entry["paths"], environ, letters)
        results, reason = [], None
        if unset:
            reason = (f"environment variable {', '.join(unset)} is not set, so the path is "
                      f"not known")
        elif not expanded:
            reason = ("no fixed drive was found in this run" if drives_known
                      else "the drive list could not be read")
        else:
            ignore = frozenset(name.casefold() for name in entry.get("ignore_names", []))
            results = [measure_dir(path, scan_dir, cutoff, ignore) for path in expanded]
        read = [r for r in results if r["state"] in ("read", "missing")]
        roots_unread = [(p, r) for p, r in zip(expanded, results) if r["state"] == "unreadable"]
        roots_skipped = [(p, r) for p, r in zip(expanded, results) if r["state"] == "skipped"]
        dirs_unread = [u for r in results for u in r["unreadable"]]
        if ((roots_skipped or roots_unread)
                and not any(r["state"] == "read" for r in results)):
            # Nothing was measured: the paths that exist are links or could not be
            # listed, the rest is missing. A missing path is a reading, but not a size
            # of what the other paths hold.
            read = []
        if not read:
            status = "not_measured" if roots_skipped and not roots_unread else "unreadable"
            if reason is None:
                reason = "; ".join(f"{p}: {r['reason']}"
                                   for p, r in roots_unread + roots_skipped)
                if any(r["state"] == "missing" for r in results):
                    reason += "; the other paths do not exist"
        elif roots_unread or dirs_unread or roots_skipped:
            status = "partial"
            parts = []
            if roots_unread or dirs_unread:
                first = (roots_unread[0][0], roots_unread[0][1]["reason"]) if roots_unread \
                    else (dirs_unread[0]["path"], dirs_unread[0]["reason"])
                parts.append(f"folders that could not be listed: "
                             f"{len(roots_unread) + len(dirs_unread)}, for example "
                             f"{first[0]}: {first[1]}")
            if roots_skipped:
                parts.append(f"paths not measured: {len(roots_skipped)}, for example "
                             f"{roots_skipped[0][0]}: {roots_skipped[0][1]['reason']}")
            reason = ("; ".join(parts) + "; so the sizes count only the part that was "
                      "measured")
        elif all(r["state"] == "missing" for r in read):
            status, reason = "empty", "the folder does not exist"
        else:
            status = "read" if sum(r["files"] for r in read) else "empty"

        def total(key, read=read):
            return sum(r[key] for r in read) if read else None

        item = {"id": item_id, "entry": entry["id"], "what": entry["what"],
                "paths": list(entry["paths"]), "status": status, "reason": reason,
                "bytes": total("bytes"), "files": total("files"),
                "gb": to_gb2(total("bytes"))}
        if days > 0:
            item.update({"bytes_older": total("bytes_older"),
                         "files_older": total("files_older"),
                         "gb_older": to_gb2(total("bytes_older"))})
        item.update({"unreadable_dirs": len(roots_unread) + len(dirs_unread),
                     "skipped_paths": len(roots_skipped),
                     "min_age_days": days, "risk": entry["risk"],
                     "needs_admin": entry["needs_admin"], "conditions": entry["conditions"],
                     "rollback": entry["rollback"], "_block": entry["block"],
                     "_expanded": expanded,
                     "_unreadable": [{"path": p, "reason": r["reason"]}
                                     for p, r in roots_unread] + dirs_unread,
                     "_skipped": [{"path": p, "reason": r["reason"]}
                                  for p, r in roots_skipped]})
        items.append(item)
        if status in ("unreadable", "partial", "not_measured"):
            note = {"what": f"cleanup entry {entry['id']}", "entry": entry["id"],
                    "item": item_id, "reason": reason}
            if status == "partial":
                note["count"] = item["unreadable_dirs"] + item["skipped_paths"]
            notes.append(note)
    return items, notes


def drive_item(letter: str, root: dict, usage, root_status: str = "read") -> dict:
    """The drive item; when the root could not be listed (``root_status``
    ``unreadable``) nothing of the drive was walked, so the scanned figures are None."""
    total, used, free = usage if usage is not None else (None, None, None)
    walked = root_status != "unreadable"
    scanned = root["bytes"] if walked else None
    return {"letter": letter, "total_bytes": total, "used_bytes": used, "free_bytes": free,
            "total_gb": to_gb(total), "used_gb": to_gb(used), "free_gb": to_gb(free),
            "scanned_bytes": scanned, "scanned_gb": to_gb(scanned),
            "scanned_files": root["files"] if walked else None,
            "cloud_only_files": root["cloud_only_files"] if walked else None,
            "unreadable_dirs": root["unreadable_dirs"]}


def summary_folder(folder: dict) -> dict:
    return {key: folder[key] for key in ("id", "path", "depth", "bytes", "gb", "files",
                                         "cloud_only_files", "listed", "readable_part")}


# --- baseline and comparison ------------------------------------------------------------
def source_name(kind: str, letter: str) -> str:
    return f"{kind}:{letter}"


def parent_of(path: str) -> str:
    """The folder that holds ``path`` (``C:\\`` for ``C:\\Data``)."""
    head = path[:path.rfind("\\")]
    return head + "\\" if head.endswith(":") else head


def ancestor_at(path: str, depth: int) -> str:
    """The ancestor of ``path`` at ``depth`` (0 is the drive root)."""
    parts = path.split("\\")
    return parts[0] + "\\" if depth == 0 else "\\".join(parts[:depth + 1])


def folder_record(folder: dict) -> dict:
    """The baseline item of a folder: compared fields plus the facts the rules use.

    A skipped directory (junction, cloud only) was not entered, so its sizes are not
    read: they are named in ``unread_fields``.
    """
    item = {"path": folder["path"], "depth": folder["depth"], "bytes": folder["bytes"],
            "files": folder["files"], "listed": folder["listed"],
            "unreadable_key": folder["unreadable_key"],
            "skipped_key": folder["skipped_key"]}
    if folder["skipped"] is not None:
        item["unread_fields"] = list(FOLDER_FIELDS)
    return item


def large_file_record(large: dict, folders_by_key: dict, depth_max: int) -> dict:
    """The baseline item of a large file, with ``parent_path`` (the folder that holds it,
    when that folder has a record) or ``parent_key`` (the ``unreadable_key`` of its
    ancestor at ``depth_max``)."""
    item = {"path": large["path"], "depth": large["depth"], "bytes": large["bytes"],
            "modified": large["modified"], "created": large.get("created")}
    if large["depth"] - 1 <= depth_max:
        item["parent_path"] = parent_of(large["path"]).lower()
    else:
        ancestor = folders_by_key.get(ancestor_at(large["path"], depth_max).lower())
        item["parent_key"] = None if ancestor is None else ancestor["unreadable_key"]
    return item


def is_size(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def well_formed(item: dict, fields: tuple) -> bool:
    """True when a baseline item has a text ``path`` and readable compared fields: a
    size (``bytes``, ``files``, ``used_bytes``) is a non-negative int, ``modified`` is
    text or null. A field named in ``unread_fields`` is not checked."""
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        return False
    unread = item.get("unread_fields") or []
    for field in fields:
        if field in unread:
            continue
        value = item.get(field)
        if field == "modified":
            if value is not None and not isinstance(value, str):
                return False
        elif not is_size(value):
            return False
    return True


def malformed_keys(letter: str, kind: str, old_items: dict, new_items: dict,
                   fields: tuple, skipped: list) -> set:
    """Keys of the baseline items that cannot be compared (no text ``path``, or a
    compared field that is not a size or a time); each one goes to ``skipped``. The key
    is left out on both sides, so it gives no change, also no new or gone item."""
    bad = set()
    for key in sorted(old_items):
        if well_formed(old_items[key], fields):
            continue
        bad.add(key)
        paths = [item.get("path") for item in (new_items.get(key), old_items[key])
                 if isinstance(item, dict)]
        path = next((p for p in paths if isinstance(p, str)), key)
        skipped.append({"drive": letter, "kind": kind, "path": path,
                        "reason": "its item in the baseline is malformed (no path, or a "
                                  "size or time of the wrong type), so it is not compared"})
    return bad


def changed_settings(saved, settings: dict) -> list:
    """The names in ``SETTING_SOURCES`` whose value differs from the one the drive was
    walked with in the baseline (``saved``). No saved settings (a baseline from before
    they were kept) is no change; a saved entry that is not an object, or a value that
    is missing or of another type, is a change."""
    if saved is None:
        return []
    if not isinstance(saved, dict):
        return [name for name, _ in SETTING_SOURCES]
    return [name for name, _ in SETTING_SOURCES
            if not is_size(saved.get(name)) or saved.get(name) != settings[name]]


def compare_view(items: dict, fields: tuple) -> dict:
    return {key: {**{field: item.get(field) for field in fields},
                  "unread_fields": list(item.get("unread_fields") or [])}
            for key, item in items.items()}


def change_item(kind: str, letter: str, path: str, depth, before, after,
                readable_part: bool) -> dict:
    delta = (after or 0) - (before or 0)
    return {"kind": kind, "path": path, "drive": letter, "depth": depth,
            "before_bytes": before, "after_bytes": after, "delta_bytes": delta,
            "delta_gb": to_gb(delta), "delta_mb": round(delta / MB, 1),
            "readable_part": readable_part}


def created_before(created, previous_at) -> bool:
    """True when the creation time ``created`` and the previous run's time
    ``previous_at`` (both ISO 8601 with a zone) are known and the first is earlier."""
    try:
        return baseline.parse_utc(created) < baseline.parse_utc(previous_at)
    except (TypeError, ValueError):
        return False


def moved_pairs(gone_keys: list, old_items: dict, new_keys: list, new_items: dict) -> dict:
    """``{key: other path}`` for the gone and the new large files that look like one file
    moved or renamed on the drive: the same ``bytes`` and the same known ``created``.
    Each gone file is paired with at most one new file, in key order."""
    def identity(item):
        size = item.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool):
            return None
        try:
            return size, baseline.parse_utc(item.get("created"))
        except (TypeError, ValueError):
            return None

    waiting = {}
    for key in sorted(new_keys):
        ident = identity(new_items[key])
        if ident is not None:
            waiting.setdefault(ident, []).append(key)
    pairs = {}
    for key in sorted(gone_keys):
        ident = identity(old_items[key])
        if ident is not None and waiting.get(ident):
            partner = waiting[ident].pop(0)
            pairs[key] = new_items[partner]["path"]
            pairs[partner] = old_items[key]["path"]
    return pairs


def dst_shift(field) -> bool:
    """True when a ``modified`` change (``{before, after}``) is exactly one hour: FAT
    keeps local times, so after a daylight-saving switch every file of such a drive
    reads one hour off without being written."""
    if not isinstance(field, dict):
        return False
    try:
        delta = (baseline.parse_utc(field.get("after"))
                 - baseline.parse_utc(field.get("before"))).total_seconds()
    except (TypeError, ValueError):
        return False
    return abs(delta) == DST_SHIFT_S


def compare_drive(letter: str, previous: dict, current: dict, comparison: dict,
                  depth_max: int, watched: dict, previous_at=None):
    """The changes of one drive and the items that were not compared.

    Returns ``(changes, not_compared)``; ``not_compared`` items are
    ``{drive, kind, path, reason}``. Only a source in the state ``compared`` gives
    changes. The rules (plan 096, M2):

    - a folder size is compared only when ``unreadable_key`` and ``skipped_key`` are the
      same in both runs;
      otherwise ``bytes`` and ``files`` go to ``unread_fields`` before the comparison;
    - ``folder_new`` and ``folder_gone`` only when the parent folder was listed in both
      runs, or is itself a new or gone folder (then the folder gives no change of its
      own: it is part of its ancestor's);
    - ``large_file_new`` and ``large_file_gone`` only when the folder holding the file
      (to ``depth_max``) was listed in both runs, or for a deeper file its ancestor at
      ``depth_max`` has the same ``unreadable_key`` in both, or that folder is new or
      gone;
    - a new or gone folder that was skipped (``bytes`` in its ``unread_fields``) or whose
      own listing failed (``listed`` not true) gives no change: its size was not read;
    - a large file with the same ``bytes`` whose ``modified`` moved by exactly
      ``DST_SHIFT_S`` gives no change (FAT keeps local times);
    - a large file new to the list whose ``created`` is before ``previous_at`` (the time
      of the baseline compared with) existed then below the threshold or elsewhere: no
      change, its earlier size is not known;
    - a gone and a new large file with the same ``bytes`` and the same known ``created``
      look moved or renamed (``moved_pairs``): no change, both are not compared;
    - everything else that differs is not compared.
    """
    changes, skipped = [], []
    names = {kind: source_name(kind, letter) for kind in SOURCE_KINDS}
    old_folders = previous.get(names["folders"]) or {}
    new_folders = current.get(names["folders"]) or {}
    covered = set()  # new and gone folders, and the folders under them

    def listed_both(key):
        return (old_folders.get(key, {}).get("listed") is True
                and new_folders.get(key, {}).get("listed") is True)

    if comparison[names["folders"]] == "compared":
        bad = malformed_keys(letter, "folder", old_folders, new_folders, FOLDER_FIELDS,
                             skipped)
        old_view = compare_view({k: v for k, v in old_folders.items() if k not in bad},
                                FOLDER_FIELDS)
        new_view = compare_view({k: v for k, v in new_folders.items() if k not in bad},
                                FOLDER_FIELDS)
        for key, view in new_view.items():
            if key in old_folders and any(
                    old_folders[key].get(name) != new_folders[key].get(name)
                    for name in ("unreadable_key", "skipped_key")):
                view["unread_fields"] = sorted(set(view["unread_fields"]) | set(FOLDER_FIELDS))
                skipped.append({"drive": letter, "kind": "folder",
                                "path": new_folders[key]["path"],
                                "reason": "a directory in or under it was listed or "
                                          "skipped (a junction or a cloud-only folder) in "
                                          "only one of the two runs, so its sizes are not "
                                          "comparable"})
        diff = baseline.compare(old_view, new_view, FOLDER_FIELDS)
        for key, fields in diff["changed"].items():
            if "bytes" not in fields:
                continue
            before, after = fields["bytes"]["before"], fields["bytes"]["after"]
            item = new_folders[key]
            changes.append(change_item(
                "folder_grew" if after > before else "folder_shrank", letter, item["path"],
                item["depth"], before, after, item.get("unreadable_key") is not None))
        for kind, keys, items in (("folder_new", diff["added"], new_folders),
                                  ("folder_gone", diff["removed"], old_folders)):
            for key in sorted(keys, key=lambda k: (as_count(items[k].get("depth")), k)):
                item = items[key]
                parent = parent_of(item["path"]).lower()
                if parent in covered:
                    covered.add(key)
                elif listed_both(parent):
                    covered.add(key)
                    if "bytes" in (item.get("unread_fields") or []) or item.get("skipped"):
                        skipped.append({"drive": letter, "kind": "folder",
                                        "path": item["path"],
                                        "reason": "it is a junction or a cloud-only folder, "
                                                  "so its size was not read"})
                        continue
                    if item.get("listed") is not True:
                        skipped.append({"drive": letter, "kind": "folder",
                                        "path": item["path"],
                                        "reason": "it could not be listed, so its size was "
                                                  "not read"})
                        continue
                    size = as_count(item.get("bytes"))
                    before, after = (None, size) if kind == "folder_new" else (size, None)
                    changes.append(change_item(kind, letter, item["path"], item.get("depth"),
                                               before, after,
                                               item.get("unreadable_key") is not None))
                else:
                    skipped.append({"drive": letter, "kind": "folder", "path": item["path"],
                                    "reason": "the folder that holds it could be listed in "
                                              "only one of the two runs"})

    def file_comparable(path, depth):
        """A large file is new or gone only when every directory on its path was listed
        in both runs: none was unreadable and none was skipped (junction, cloud only)."""
        if as_count(depth) - 1 <= depth_max:
            key = parent_of(path).lower()
            return key in covered or listed_both(key)
        key = ancestor_at(path, depth_max).lower()
        if key in covered:
            return True
        # Deeper than the folder records: the ancestor at depth_max must be listed in
        # both runs and hold the same unreadable and the same skipped directories.
        return (listed_both(key)
                and old_folders[key].get("unreadable_key")
                == new_folders[key].get("unreadable_key")
                and old_folders[key].get("skipped_key")
                == new_folders[key].get("skipped_key"))

    if comparison[names["large_files"]] == "compared":
        old_large = previous.get(names["large_files"]) or {}
        new_large = dict(current.get(names["large_files"]) or {})
        bad = malformed_keys(letter, "large_file", old_large, new_large, LARGE_FILE_FIELDS,
                             skipped)
        old_large = {k: v for k, v in old_large.items() if k not in bad}
        new_large = {k: v for k, v in new_large.items() if k not in bad}
        old_view = compare_view(old_large, LARGE_FILE_FIELDS)
        new_view = compare_view(new_large, LARGE_FILE_FIELDS)
        in_cloud = set()
        for key, seen in watched.items():
            if key not in old_large or key in new_large:  # also a malformed item
                continue
            if seen["cloud_only"]:
                in_cloud.add(key)
                skipped.append({"drive": letter, "kind": "large_file",
                                "path": old_large[key]["path"],
                                "reason": "the file is now only in the cloud, so its size "
                                          "on the disk is not comparable"})
            else:
                # Still on the disk, below the threshold: a change, not a file that is gone.
                new_view[key] = {"bytes": seen["bytes"], "modified": seen["modified"],
                                 "unread_fields": []}
                new_large[key] = {**old_large[key], "bytes": seen["bytes"],
                                  "modified": seen["modified"]}
        diff = baseline.compare(old_view, new_view, LARGE_FILE_FIELDS)
        for key, fields in diff["changed"].items():
            before, after = old_large[key], new_large[key]
            if "bytes" not in fields and dst_shift(fields.get("modified")):
                continue  # a FAT time stamp after a daylight-saving switch
            change = change_item("large_file_changed", letter, after["path"],
                                 after.get("depth"), before.get("bytes"),
                                 after.get("bytes"), False)
            change["before_modified"] = before.get("modified")
            change["after_modified"] = after.get("modified")
            changes.append(change)
        moved = moved_pairs([k for k in diff["removed"] if k not in in_cloud], old_large,
                            [k for k in diff["added"] if k not in in_cloud], new_large)
        for key, other_path in moved.items():
            item = old_large[key] if key in old_large else new_large[key]
            skipped.append({"drive": letter, "kind": "large_file", "path": item["path"],
                            "reason": f"it looks moved or renamed: a large file with the "
                                      f"same size and creation time is at {other_path}"})
        for kind, keys, items in (("large_file_new", diff["added"], new_large),
                                  ("large_file_gone", diff["removed"], old_large)):
            for key in keys:
                if key in in_cloud or key in moved:
                    continue
                item = items[key]
                if kind == "large_file_new" and created_before(item.get("created"),
                                                               previous_at):
                    skipped.append({"drive": letter, "kind": "large_file",
                                    "path": item["path"],
                                    "reason": "it existed at the previous run but was not "
                                              "in the large-file list (below the threshold "
                                              "or in another folder), so its earlier size "
                                              "is not known"})
                    continue
                if file_comparable(item["path"], item.get("depth")):
                    size = as_count(item.get("bytes"))
                    before, after = (None, size) if kind == "large_file_new" else (size, None)
                    changes.append(change_item(kind, letter, item["path"], item.get("depth"),
                                               before, after, False))
                else:
                    skipped.append({"drive": letter, "kind": "large_file",
                                    "path": item["path"],
                                    "reason": "the folder that holds it could be listed in "
                                              "only one of the two runs"})

    if comparison[names["drives"]] == "compared":
        old_drive = previous.get(names["drives"]) or {}
        new_drive = current.get(names["drives"]) or {}
        diff = baseline.compare(compare_view(old_drive, DRIVE_FIELDS),
                                compare_view(new_drive, DRIVE_FIELDS), DRIVE_FIELDS)
        for key, fields in diff["changed"].items():
            before, after = fields["used_bytes"]["before"], fields["used_bytes"]["after"]
            if not isinstance(before, int) or not isinstance(after, int):
                continue
            changes.append(change_item("drive_used_changed", letter, f"{letter}:\\", 0,
                                       before, after, False))
    return changes, skipped


# --- budget -----------------------------------------------------------------------------
def most_that_fit(fits, high: int) -> int:
    """The largest n in 0..high with ``fits(n)``, by bisection; ``fits(0)`` holds."""
    low = 0
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    return low


BUDGET_LISTS = (  # list, what is cut from its end, in the order of cutting
    ("folders", "the smallest folders"),
    ("large_files", "the smallest large files"),
    ("changes", "the smallest changes"),
)


def fit_budget(summary: dict, lists: dict, limits: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    At most ``limits[name]`` items of each list go in; ``folders`` is cut from its end
    first, then ``large_files``, then ``changes``, each cut by the budget with a
    ``not_checked`` note. ``truncated_<name>`` counts every item left out, by the limit
    or by the budget; ``truncated`` repeats ``truncated_folders``.
    """
    notes = summary["not_checked"]
    wanted = {name: min(len(lists[name]), limits[name]) for name, _ in BUDGET_LISTS}

    def fits(kept: dict) -> bool:
        for name, _ in BUDGET_LISTS:
            summary[name] = lists[name][:kept[name]]
            summary[f"truncated_{name}"] = len(lists[name]) - kept[name]
        summary["truncated"] = summary["truncated_folders"]
        return len(dump(summary)) <= SUMMARY_MAX_CHARS

    if fits(wanted):
        return dump(summary)
    added = []
    kept = dict(wanted)
    for index, (name, text) in enumerate(BUDGET_LISTS):
        cut_before = [n for n, _ in BUDGET_LISTS[:index]]
        even = f"even without any {' or '.join(n.replace('_', ' ') for n in cut_before)} " \
            if cut_before else ""
        note = {"what": f"{name.replace('_', ' ')} cut from the summary",
                "reason": f"{text} of the list (see truncated_{name}) are only in the detail "
                          f"file; {even}the summary exceeded {SUMMARY_MAX_CHARS} characters"}
        notes.append(note)
        added.append(note)
        if fits({**kept, name: 0}):
            kept[name] = most_that_fit(lambda n, name=name: fits({**kept, name: n}),
                                       wanted[name])
            fits(kept)
            return dump(summary)
        kept[name] = 0
    # Something else is too long: cutting would lose items for nothing.
    for note in added:
        notes.remove(note)
    fits(wanted)
    notes.append({"what": "summary budget",
                  "reason": f"the summary exceeds {SUMMARY_MAX_CHARS} characters and was "
                            f"not cut"})
    return dump(summary)


def cleanup_detail(item: dict) -> dict:
    """A cleanup item of the detail file: with its block, the expanded paths and every
    folder that could not be listed."""
    detail = {k: v for k, v in item.items() if not k.startswith("_")}
    detail["block"] = item["_block"]
    detail["expanded_paths"] = item["_expanded"]
    detail["unreadable"] = item["_unreadable"]
    detail["skipped"] = item["_skipped"]
    return detail


# --- machine functions ------------------------------------------------------------------
def default_list_drives() -> list:
    try:
        import ctypes  # Windows-only, and only for a real run

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, ImportError, OSError) as exc:
        raise OSError(f"kernel32 is not available: {exc}") from exc
    kernel32.GetLogicalDrives.restype = ctypes.c_uint32
    kernel32.GetLogicalDrives.argtypes = []
    kernel32.GetDriveTypeW.restype = ctypes.c_uint
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.QueryDosDeviceW.restype = ctypes.c_uint32
    kernel32.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    mask = kernel32.GetLogicalDrives()
    if mask == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    drives = []
    for number in range(26):
        if mask & (1 << number):
            letter = chr(ord("A") + number)
            target = ctypes.create_unicode_buffer(1024)
            is_subst = (kernel32.QueryDosDeviceW(f"{letter}:", target, len(target))
                        and is_subst_target(target.value))
            if is_subst:
                continue  # a subst alias of a folder: its files are walked on their own drive
            drives.append((letter, int(kernel32.GetDriveTypeW(f"{letter}:\\"))))
    return drives


def is_subst_target(target: str) -> bool:
    """True for a ``QueryDosDevice`` target of a ``subst`` drive (``\\??\\C:\\...``);
    a real volume gives ``\\Device\\HarddiskVolume<n>``."""
    return target.startswith("\\??\\")


def extended_path(path: str) -> str:
    """``path`` with the ``\\\\?\\`` prefix, so a listing is not cut at 260 characters
    and a name ending in a dot or a space is kept (Windows reports both as a missing
    path, which would count an existing folder as vanished)."""
    if path.startswith("\\\\"):
        return path
    return "\\\\?\\" + path


def creation_time(info):
    """The creation time of a ``stat`` result in POSIX seconds, or None: ``st_birthtime``,
    else ``st_ctime`` on Windows (elsewhere ``st_ctime`` is the last metadata change)."""
    birth = getattr(info, "st_birthtime", None)
    if birth is None and os.name == "nt":
        birth = getattr(info, "st_ctime", None)
    return birth


def default_scan_dir(path: str) -> list:
    entries = []
    with os.scandir(extended_path(path)) as listing:
        for entry in listing:
            try:
                info = entry.stat(follow_symlinks=False)
            except VANISHED:
                continue  # the entry went away after the listing: nothing to count
            attributes = getattr(info, "st_file_attributes", 0)
            entries.append({
                "name": entry.name,
                "is_dir": bool(attributes & FILE_ATTRIBUTE_DIRECTORY),
                "size": info.st_size,
                "attributes": attributes,
                "reparse_tag": getattr(info, "st_reparse_tag", 0),
                "mtime": info.st_mtime,
                "ctime": creation_time(info),
            })
    return entries


def default_disk_usage(path: str):
    return shutil.disk_usage(path)


def default_is_admin() -> bool:
    try:
        import ctypes  # Windows-only, and only for a real run

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


# --- command line -----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=None, help=datadir.HELP)
    parser.add_argument("--detail", metavar="ID",
                        help="print one folder, large file, change or cleanup item of the "
                             "newest detail file and exit")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    parser.add_argument("--block", metavar="ID[,ID]",
                        help="print the PowerShell block of cleanup entries (catalogue ids "
                             "or c ids) and exit; nothing is read or changed")
    return parser


def show_block(entries: list, wanted: str) -> int:
    """Print the blocks of the named catalogue entries; nothing else is done."""
    found = []
    for name in (part.strip() for part in wanted.split(",")):
        match = find_cleanup(entries, name)
        if match is None:
            known = ", ".join(entry["id"] for entry in entries)
            print(f"no cleanup entry {name!r}; known: {known}", file=sys.stderr)
            return 1
        if match not in found:
            found.append(match)
    parts = []
    for item_id, entry in found:
        admin = "an elevated" if entry["needs_admin"] else "the user's own"
        parts.append(f"# {item_id} {entry['id']}: {entry['what']}; risk {entry['risk']}; "
                     f"run in {admin} PowerShell; conditions: {entry['conditions']}; "
                     f"rollback: {entry['rollback']}\n{entry['block']}")
    print("\n\n".join(parts))
    return 0


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("files-*.detail.json"), key=lambda p: p.name)
        if not files:
            print(f"no detail file in {work}; run the collection first", file=sys.stderr)
            return 1
        newest = files[-1]
    try:
        detail = json.loads(newest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"{newest} could not be read: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(detail, dict):
        print(f"{newest} does not hold a detail object", file=sys.stderr)
        return 1
    for section in DETAIL_SECTIONS:
        for item in detail.get(section) or []:
            if isinstance(item, dict) and item.get("id") == item_id:
                print(json.dumps(item, ensure_ascii=True, indent=1))
                return 0
    print(f"id {item_id!r} not found in {newest}", file=sys.stderr)
    return 1


def main(argv=None, list_drives=None, scan_dir=None, disk_usage=None, is_admin=None,
         now=None, environ=None) -> int:
    """Walk the fixed drives and summarise, or print one item with --detail.

    The four machine functions are injected all together (tests) or not at all (a real
    run): injecting only some is a TypeError, so a test that forgets a fake fails loudly
    instead of reading the machine.
    """
    machine = (list_drives, scan_dir, disk_usage, is_admin)
    if any(f is None for f in machine) and any(f is not None for f in machine):
        raise TypeError("inject list_drives, scan_dir, disk_usage and is_admin, or none")
    environ = os.environ if environ is None else environ
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.detail_file is not None and args.detail is None:
        parser.error("--detail-file needs --detail")
    if args.block is not None:
        # Only prints: no data directory, no machine function, nothing written.
        entries, cleanup_reason = load_cleanup(CLEANUP_FILE)
        if cleanup_reason is not None:
            print(f"cleanup catalogue not usable: {cleanup_reason}", file=sys.stderr)
            return 2
        return show_block(entries, args.block)
    if args.detail_file is not None:
        # The detail file is named explicitly: no data directory is needed.
        return show_detail(Path(), args.detail, Path(args.detail_file).absolute())
    try:
        data_dir = datadir.resolve(args.data_dir, environ)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    work = data_dir / "work"
    if args.detail is not None:
        return show_detail(work, args.detail)

    settings, scan_reason = load_scan(SCAN_FILE)
    if scan_reason is not None:
        print(f"scan settings not usable, nothing was walked: {scan_reason}", file=sys.stderr)
        return 2
    cleanup_entries, cleanup_reason = load_cleanup(CLEANUP_FILE)
    if cleanup_reason is not None:
        print(f"cleanup catalogue not usable, nothing was walked: {cleanup_reason}",
              file=sys.stderr)
        return 2

    list_drives = list_drives or default_list_drives
    scan_dir = scan_dir or default_scan_dir
    disk_usage = disk_usage or default_disk_usage
    is_admin = is_admin or default_is_admin
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    work.mkdir(parents=True, exist_ok=True)
    summary_file = work / f"files-{stamp}.summary.json"
    detail_file = work / f"files-{stamp}.detail.json"
    started = time.monotonic()

    admin = bool(is_admin())
    state = data_dir / "state"
    loaded = baseline.load(state, SKILL, admin)
    previous = loaded["sources"] if loaded["status"] == "read" else {}
    reference = baseline.reference_for(state, SKILL, admin, loaded, None, None, now)
    reference_sources = reference["sources"]

    sources, not_checked, unreadable = [], [], []
    counts = {"drives": 0, "folders": 0, "dirs_listed": 0, "files": 0, "large_files": 0,
              "cloud_only_files": 0, "cloud_only_dirs": 0, "reparse_skipped": 0,
              "vanished_dirs": 0, "unreadable_dirs": 0, "changes": 0, "not_compared": 0}
    try:
        drives_found = list(list_drives())
    except OSError as exc:
        drives_found = []
        not_checked.append({"what": "drive list",
                            "reason": f"no drive was walked: {error_text(exc)}"})
    letters = []
    for drive in drives_found:
        letter = drive_letter(drive)
        if drive[1] == DRIVE_FIXED and letter not in letters:
            letters.append(letter)

    drives, all_folders, large = [], [], []
    statuses, current, watched = {}, {}, {}
    for letter in letters:
        watch = frozenset(reference_sources.get(source_name("large_files", letter)) or {})
        watched[letter] = {}
        drive_large = []
        folders, status, reason = walk_drive(letter, scan_dir, settings, counts, drive_large,
                                             unreadable, watch, watched[letter])
        large.extend(drive_large)
        if status == "unreadable":
            not_checked.append({"what": f"drive {letter}:", "drive": letter,
                                "reason": f"the drive root could not be listed: {reason}"})
        try:
            usage = tuple(disk_usage(f"{letter}:\\"))[:3]
            usage_status, usage_reason = "read", None
        except OSError as exc:
            usage = None
            usage_status, usage_reason = "unreadable", error_text(exc)
            not_checked.append({"what": f"disk usage of drive {letter}:", "drive": letter,
                                "reason": f"total, used and free are not known: "
                                          f"{usage_reason}"})
        large_status = status if status == "unreadable" or drive_large else "empty"
        for kind, kind_status, kind_reason in (("folders", status, reason),
                                               ("large_files", large_status, reason),
                                               ("drives", usage_status, usage_reason)):
            name = source_name(kind, letter)
            statuses[name] = kind_status
            sources.append({"name": name, "drive": letter, "status": kind_status,
                            "reason": kind_reason})
        folders_by_key = {f["path"].lower(): f for f in folders}
        current[source_name("folders", letter)] = {
            key: folder_record(f) for key, f in folders_by_key.items()}
        current[source_name("large_files", letter)] = {
            f["path"].lower(): large_file_record(f, folders_by_key, settings["depth"])
            for f in drive_large}
        current[source_name("drives", letter)] = (
            {letter: {"letter": letter, "used_bytes": usage[1]}} if usage is not None else {})
        root = folders[0]
        drives.append(drive_item(letter, root, usage, status))
        unread_here = [u for u in unreadable if u["drive"] == letter]
        if unread_here and status != "unreadable":
            first = unread_here[0]
            not_checked.append({
                "what": f"directories on drive {letter}:", "drive": letter,
                "count": len(unread_here),
                "reason": f"{len(unread_here)} directories could not be listed, so the "
                          f"sizes of their folders count only the readable part; for "
                          f"example {first['path']}: {first['reason']}"})
        all_folders.extend(folders)

    # Every source of this run and of the latest baseline: a drive that is not here in
    # this run has no status, so it is not_read and keeps its items.
    names = list(statuses)
    names += [name for name in list(previous) + list(reference_sources)
              if name not in names and name.partition(":")[0] in SOURCE_KINDS]
    comparison_sources = {name: baseline.comparison_state(reference_sources, name,
                                                          statuses.get(name))
                          for name in names}
    absent = []
    for name in names:
        letter = name.partition(":")[2]
        if name not in statuses and letter not in absent:
            absent.append(letter)
            not_checked.append({
                "what": f"drive {letter}:", "drive": letter,
                "reason": f"drive {letter}: is in the baseline but is not a fixed drive of "
                          f"this run, so its folders, large files and usage were not "
                          f"compared; the baseline keeps its items from the earlier run"})

    # Folders and large files depend on the depth and the threshold: walked with other
    # settings they would give a wave of changes that are not on the disk.
    saved_settings = reference_sources.get(SCAN_SOURCE)
    saved_settings = saved_settings if isinstance(saved_settings, dict) else {}
    for letter in letters:
        names_changed = changed_settings(saved_settings.get(letter), settings)
        held = [source_name(kind, letter) for name, kind in SETTING_SOURCES
                if name in names_changed
                and comparison_sources[source_name(kind, letter)] == "compared"]
        if not held:
            continue
        for name in held:
            comparison_sources[name] = SETTINGS_CHANGED
        saved = saved_settings.get(letter)
        before = ({name: saved.get(name) for name, _ in SETTING_SOURCES}
                  if isinstance(saved, dict) else None)
        not_checked.append({
            "what": f"scan settings of drive {letter}:", "drive": letter, "sources": held,
            "previous_settings": before,
            "settings": {name: settings[name] for name, _ in SETTING_SOURCES},
            "reason": f"the scan settings changed since the previous run, so "
                      f"{' and '.join(n.partition(':')[0].replace('_', ' ') for n in held)} "
                      f"on drive {letter}: were not compared; the next run with the same "
                      f"settings compares them again"})

    changes, not_compared = [], []
    for letter in letters:
        drive_changes, drive_skipped = compare_drive(
            letter, reference_sources, current, comparison_sources, settings["depth"],
            watched[letter], reference["info"]["created_at"])
        changes.extend(drive_changes)
        not_compared.extend(drive_skipped)
        if drive_skipped:
            not_checked.append({
                "what": f"comparison on drive {letter}:", "drive": letter,
                "count": len(drive_skipped),
                "paths": [item["path"] for item in drive_skipped[:NOTE_PATHS_MAX]],
                "reason": f"{len(drive_skipped)} folders and large files were not compared "
                          f"with the earlier run, because a directory in, under or above "
                          f"them could be listed (or was skipped) in only one of the two "
                          f"runs, the file is now only in the cloud, a new large file "
                          f"existed at that run below the threshold, a new or gone folder "
                          f"was skipped or could not be listed, a gone and a new large "
                          f"file look moved or renamed (same size and creation time), or "
                          f"the item in the baseline is malformed; every one is in the "
                          f"detail file (not_compared)"})
    changes.sort(key=lambda c: (-abs(c["delta_bytes"]), c["kind"], c["path"].lower()))
    cleanup, cleanup_notes = measure_cleanup(cleanup_entries, letters, scan_dir, environ,
                                             now, bool(drives_found))
    not_checked.extend(cleanup_notes)
    changes = with_ids(changes, "d")

    all_folders.sort(key=lambda f: (-f["bytes"], f["path"].lower()))
    all_folders = with_ids(all_folders, "f")
    large.sort(key=lambda f: (-f["bytes"], f["path"].lower()))
    large = with_ids(large, "l")
    counts["drives"] = len(drives)
    counts["folders"] = len(all_folders)
    counts["large_files"] = len(large)
    counts["unreadable_dirs"] = len(unreadable)
    counts["changes"] = len(changes)
    counts["not_compared"] = len(not_compared)

    # The settings of each drive whose folders were read now; a drive not read keeps the
    # settings its carried-over items were walked with.
    scan_saved = previous.get(SCAN_SOURCE)
    scan_saved = dict(scan_saved) if isinstance(scan_saved, dict) else {}
    for letter in letters:
        if statuses[source_name("folders", letter)] in baseline.READ_STATUSES:
            scan_saved[letter] = {name: settings[name] for name, _ in SETTING_SOURCES}
    new_baseline = {
        "schema_version": baseline.SCHEMA_VERSION,
        "skill": SKILL,
        "created_at": now.isoformat(),
        "elevated": admin,
        "sources": baseline.merge_sources(previous, {**current, SCAN_SOURCE: scan_saved},
                                          {**statuses, SCAN_SOURCE: "read"}),
    }
    info = reference["info"]
    comparison = {"sources": comparison_sources, "previous_at": info["created_at"],
                  "age_days": info["age_days"]}
    duration = round(time.monotonic() - started, 1)

    scan = {"depth": settings["depth"], "large_file_bytes": settings["large_file_bytes"]}
    detail = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "scan": scan,
        "sources": sources,
        "comparison": comparison,
        "drives": drives,
        "folders": all_folders,
        "large_files": large,
        "changes": changes,
        "not_compared": not_compared,
        "cleanup": [cleanup_detail(item) for item in cleanup],
        "unreadable": unreadable,
        "summary_file": str(summary_file),
    }
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    # The detail file is written before the baseline: when it cannot be written the
    # run stops and the old baseline stays, so the next run reports these changes again.
    state_name = baseline.baseline_name(SKILL, admin)
    save_reason = baseline.save(state, state_name, new_baseline)
    history_reason = baseline.archive(state, state_name, now)
    for what, reason in reference["notes"]:
        not_checked.append({"what": what, "reason": reason})
    if save_reason is not None:
        not_checked.append({"what": "baseline save",
                            "reason": f"this run's baseline was not saved: {save_reason}"})
    if history_reason is not None:
        not_checked.append({"what": "baseline history",
                            "reason": baseline.history_note(history_reason)})
    reasons = list(info["reason"])
    if save_reason is not None:
        reasons.append(f"not saved: {save_reason}")
    baseline_info = {
        "status": info["status"],
        "reference": info["reference"],
        "reference_file": info["reference_file"],
        "created_at": info["created_at"],
        "age_days": info["age_days"],
        "saved": save_reason is None,
        "reason": "; ".join(reasons) if reasons else None,
    }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "sources": sources,
        "not_checked": not_checked,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": 0,
        "truncated_folders": 0,
        "truncated_large_files": 0,
        "truncated_changes": 0,
        "duration_s": duration,
        "scan": scan,
        "baseline": baseline_info,
        "comparison": comparison,
        "counts": counts,
        "drives": drives,
        "folders": [],
        "large_files": [],
        "changes": [],
        "cleanup": [{k: v for k, v in item.items() if not k.startswith("_")}
                    for item in cleanup],
    }
    text_out = fit_budget(
        summary,
        {"folders": [summary_folder(f) for f in all_folders], "large_files": large,
         "changes": changes},
        {"folders": settings["summary_folders"],
         "large_files": settings["summary_large_files"],
         "changes": settings["summary_changes"]})
    summary_file.write_text(text_out, encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

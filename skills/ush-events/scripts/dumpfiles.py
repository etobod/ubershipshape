"""Memory dump inventory, shared by events.py (read-only) and dumps.py (copy).

Every access to the machine goes through an injected function; the defaults
named ``default_*`` below are the real ones, and tests replace all of them:

- ``read_value(key_path, value_name)`` reads one value under HKLM and returns
  the plain value; a missing value raises FileNotFoundError (like winreg);
- ``list_dir(path)`` like ``os.listdir``; ``stat(path)`` like ``os.stat``;
- ``open_file(path, mode)`` like ``open``; a locked or protected file raises
  PermissionError from this call;
- ``copy(src, dst)`` like ``shutil.copyfile``; ``remove(path)`` like
  ``os.remove``; ``disk_usage(path)`` like ``shutil.disk_usage`` (``.free``).

The inventory only lists and opens files; it never changes the machine. The
script counts; it never judges whether a dump is a problem.
"""

import hashlib
import os
import shutil
import stat as stat_module
from datetime import datetime, timezone

CRASH_CONTROL = r"SYSTEM\CurrentControlSet\Control\CrashControl"
# Summary key -> registry value name.
VALUE_NAMES = (("crash_dump_enabled", "CrashDumpEnabled"),
               ("minidump_dir", "MinidumpDir"),
               ("dump_file", "DumpFile"))
# What Windows uses when a value is absent (a missing value is the default,
# not "disabled"); 7 is the automatic memory dump of Windows 10 and 11.
WINDOWS_DEFAULTS = {"crash_dump_enabled": 7,
                    "minidump_dir": r"%SystemRoot%\Minidump",
                    "dump_file": r"%SystemRoot%\MEMORY.DMP"}
PATH_KEYS = ("minidump_dir", "dump_file")
DUMP_SUFFIX = ".dmp"
NEEDS_ADMIN = "needs administrator"
CHUNK = 1 << 20


def iso(moment: datetime | None) -> str | None:
    """ISO 8601 text of an aware datetime (``+00:00`` for UTC), or None."""
    return moment.isoformat() if moment is not None else None


# --- the real machine functions (tests replace every one) -----------------
def default_read_value(key_path: str, name: str):
    """One value under HKLM, read-only. winreg is imported only here."""
    import winreg  # Windows-only, and only for a real run

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ) as key:
        value, _ = winreg.QueryValueEx(key, name)
    return value


def default_list_dir(path):
    return os.listdir(path)


def default_stat(path):
    return os.stat(path)


def default_open_file(path, mode="rb"):
    return open(path, mode)  # the caller closes it


def default_copy(src, dst):
    return shutil.copyfile(src, dst)


def default_remove(path):
    os.remove(path)


def default_disk_usage(path):
    return shutil.disk_usage(path)


# --- reading -------------------------------------------------------------
def describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def crash_settings(read_value) -> dict:
    """The CrashControl values, environment variables expanded.

    ``crash_dump_enabled``, ``minidump_dir`` and ``dump_file``. A missing
    value takes the Windows default and is named in ``defaulted``. Any other error
    (e.g. access denied) propagates as OSError, and a path value that is not
    a string (a wrong registry type) raises ValueError: the settings are
    unknown.
    """
    settings, defaulted = {}, []
    for key, name in VALUE_NAMES:
        try:
            value = read_value(CRASH_CONTROL, name)
        except FileNotFoundError:
            value = WINDOWS_DEFAULTS[key]
            defaulted.append(key)
        if isinstance(value, str):
            value = os.path.expandvars(value)
        elif key in PATH_KEYS:
            raise ValueError(f"{name} is not a string ({type(value).__name__})")
        settings[key] = value
    settings["defaulted"] = defaulted
    return settings


def _file_entry(path: str, name: str, stat, open_file) -> dict | None:
    """One inventory file, or None when it does not exist (or is a folder)."""
    entry = {"name": name, "path": path, "size": None, "modified": None, "readable": False}
    try:
        info = stat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        entry["reason"] = f"could not be read (stat): {describe(exc)}"
        return entry
    mode = getattr(info, "st_mode", None)
    if isinstance(mode, int) and stat_module.S_ISDIR(mode):
        return None
    entry["size"] = info.st_size
    try:
        entry["modified"] = iso(datetime.fromtimestamp(info.st_mtime, timezone.utc))
    except (OSError, ValueError, OverflowError) as exc:
        entry["reason"] = f"its modification time could not be read: {describe(exc)}"
        return entry
    try:
        with open_file(path, "rb"):
            pass
    except PermissionError as exc:
        entry["reason"] = f"{NEEDS_ADMIN} to open it: {describe(exc)}"
        return entry
    except OSError as exc:
        entry["reason"] = f"could not be opened: {describe(exc)}"
        return entry
    entry["readable"] = True
    return entry


def _same_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def inventory(settings: dict, list_dir, stat, open_file) -> dict:
    """The ``dumps`` object: {status, reason, settings, files}.

    Files are the ``*.dmp`` in MinidumpDir and DumpFile if it exists, each
    {name, path, size, modified (UTC), readable[, reason]}, ordered by
    ``modified``. A MinidumpDir that does not exist is "empty" (Windows makes
    it at the first dump); any other listing error is "unreadable", with the
    files that could still be listed.
    """
    files, problems, seen = [], [], set()

    def add(entry):
        if entry is not None and _same_path(entry["path"]) not in seen:
            seen.add(_same_path(entry["path"]))
            files.append(entry)

    folder = settings.get("minidump_dir")
    if folder:
        try:
            names = list_dir(folder)
        except FileNotFoundError:
            names = []
        except OSError as exc:
            problems.append(f"{folder} could not be listed: {describe(exc)}")
            names = []
        for name in sorted(names):
            if str(name).lower().endswith(DUMP_SUFFIX):
                add(_file_entry(os.path.join(folder, name), str(name), stat, open_file))
    dump_file = settings.get("dump_file")
    if dump_file:
        add(_file_entry(dump_file, os.path.basename(dump_file), stat, open_file))

    files.sort(key=lambda f: (f["modified"] is None, f["modified"] or "", f["path"]))
    if problems:
        status, reason = "unreadable", "; ".join(problems)
    else:
        status, reason = ("read" if files else "empty"), None
    return {"status": status, "reason": reason, "settings": settings, "files": files}


def read_all(read_value, list_dir, stat, open_file) -> dict:
    """crash_settings and inventory; unreadable settings give an unreadable object."""
    try:
        settings = crash_settings(read_value)
    except (OSError, ValueError) as exc:
        return {"status": "unreadable",
                "reason": f"the CrashControl registry values could not be read: {describe(exc)}",
                "settings": None, "files": []}
    return inventory(settings, list_dir, stat, open_file)


def digest(path, open_file=None) -> tuple[str, int]:
    """(lowercase SHA-256 hex digest, size in bytes) of one file."""
    opener = open_file or open
    hasher, size = hashlib.sha256(), 0
    with opener(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def sha256(path, open_file=None) -> str:
    return digest(path, open_file)[0]

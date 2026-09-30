"""Resolve the data directory every skill script reads and writes.

Order, first match wins:

1. ``--data-dir`` given: ``Path(arg).absolute()``; an empty value is an error, never a
   silent fall-through to the environment.
2. ``USH_DATA_DIR`` when non-empty; it must be absolute (a relative one would depend on
   the working directory, which is what this module avoids).
3. ``<LOCALAPPDATA>/ubershipshape`` when ``LOCALAPPDATA`` is non-empty and absolute.
4. Otherwise ``DataDirError``.

``resolve`` creates nothing; scripts create directories when they write. ``environ`` is a
parameter so tests never read the real environment.
"""

import os
from pathlib import Path

APP_DIR_NAME = "ubershipshape"
HELP = "data directory (default: USH_DATA_DIR, else %%LOCALAPPDATA%%\\ubershipshape)"


class DataDirError(Exception):
    """No usable data directory; the message says how to give one."""


def resolve(arg, environ=os.environ) -> Path:
    """Return the absolute data directory for ``arg`` (``--data-dir`` or None)."""
    if arg is not None:
        if not str(arg).strip():
            raise DataDirError("--data-dir is empty: pass a directory path")
        return Path(arg).absolute()

    ush = environ.get("USH_DATA_DIR", "")
    if ush:
        path = Path(ush)
        if not path.is_absolute():
            raise DataDirError(f"USH_DATA_DIR is not an absolute path ({ush!r}): "
                               "set it to an absolute path or pass --data-dir")
        return path

    appdata = environ.get("LOCALAPPDATA", "")
    if appdata:
        path = Path(appdata)
        if not path.is_absolute():
            raise DataDirError(f"LOCALAPPDATA is not an absolute path ({appdata!r}): "
                               "pass --data-dir, or set USH_DATA_DIR")
        return path / APP_DIR_NAME

    raise DataDirError("no data directory: pass --data-dir, or set USH_DATA_DIR or LOCALAPPDATA")

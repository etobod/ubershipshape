"""Resolve the data directory every skill script reads and writes.

Order, first match wins:

1. ``--data-dir`` given: ``Path(arg).absolute()``; an empty value is an error, never a
   silent fall-through to the environment.
2. ``USH_DATA_DIR`` when non-empty; it must be absolute (a relative one would depend on
   the working directory, which is what this module avoids).
3. ``--default-data-dir`` given: the default the caller supplies (the plugin's data folder,
   passed by SKILL.md as ``${CLAUDE_PLUGIN_DATA}``). It must be absolute and must not still
   hold an unexpanded ``${``.
4. Otherwise ``DataDirError``. There is no fallback to ``LOCALAPPDATA``.

``resolve`` creates nothing; scripts create directories when they write. ``environ`` is a
parameter so tests never read the real environment.
"""

import os
from pathlib import Path

HELP = "data directory (default: USH_DATA_DIR, else --default-data-dir)"
DEFAULT_HELP = ("data directory used when neither --data-dir nor USH_DATA_DIR is given "
                "(the plugin's data folder)")


class DataDirError(Exception):
    """No usable data directory; the message says how to give one."""


def add_arguments(parser, data_dir_help=HELP):
    """Add ``--data-dir`` and ``--default-data-dir`` to ``parser``."""
    parser.add_argument("--data-dir", default=None, help=data_dir_help)
    parser.add_argument("--default-data-dir", default=None, help=DEFAULT_HELP)


def resolve(arg, environ=os.environ, default=None) -> Path:
    """Return the absolute data directory for ``arg`` (``--data-dir`` or None) and
    ``default`` (``--default-data-dir`` or None)."""
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

    if default is not None:
        text = str(default)
        if not text.strip():
            raise DataDirError("--default-data-dir is empty: pass --data-dir")
        if "${" in text:
            raise DataDirError(f"--default-data-dir holds an unexpanded variable ({text!r}): "
                               "pass --data-dir")
        path = Path(text)
        if not path.is_absolute():
            raise DataDirError(f"--default-data-dir is not an absolute path ({text!r}): "
                               "pass --data-dir")
        return path

    raise DataDirError("no data directory: pass --data-dir, or set USH_DATA_DIR")

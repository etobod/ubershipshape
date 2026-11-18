"""Progress lines on stderr for a window the user watches (shared by the ush-* skills).

A script run in a run-me window or a console tells the user what it is doing;
a script run by the model through its shell tool prints nothing extra, because
that tool reads stdout and stderr together. So a line is printed only when
``USH_PROGRESS`` is ``1``, or when it is unset and stderr is a console.

Lines are ASCII and name jobs, skills, kinds and counts only, never a path or
a value from the machine. stdout stays the JSON summary.
"""

import os
import sys

COUNT_EVERY = 1000  # a counter line at most once per this many items


def enabled() -> bool:
    """True when progress lines are wanted: ``USH_PROGRESS=1``, or no
    ``USH_PROGRESS`` and stderr is a console."""
    value = os.environ.get("USH_PROGRESS")
    if value is not None:
        return value.strip() == "1"
    try:
        return bool(sys.stderr.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def step(text) -> None:
    """Print one progress line on stderr when enabled."""
    if not enabled():
        return
    line = str(text).encode("ascii", "replace").decode("ascii")
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass  # a closed or broken stderr never stops the script


def count(label, n, total=None) -> None:
    """A counter line, at most once per ``COUNT_EVERY`` items and always for the
    last item of a known total: ``<label> <n> / <total>``, or
    ``<label> <n> directories`` without a total."""
    if n <= 0:
        return
    last = total is not None and n == total
    if n % COUNT_EVERY and not last:
        return
    if total is None:
        step(f"{label} {n} directories")
    else:
        step(f"{label} {n} / {total}")

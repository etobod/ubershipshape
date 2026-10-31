"""Run read-only PowerShell jobs and read their results (shared by the ush-* skills).

A job is one script run in Windows PowerShell 5.1 through an injectable
``run_ps(job, script, out_path) -> (exit code, stderr)``; tests pass a fake.
The script writes its result as JSON to ``out_path`` (BOM-less UTF-8, see
``ps_script``), never through stdout, whose code page is the console's.

``run_job`` turns one job into ``{status, reason, rows}``:

- ``read``: the file holds at least one object;
- ``empty``: the job ran and found nothing (an empty list, ``null``, an empty
  file, or a non-zero exit whose stderr holds one of ``empty_markers``);
- ``unreadable``: anything else, with the reason; ``rows`` is then ``[]``.

Nothing here decides whether a value is a problem; the skill counts, the
model judges.
"""

import json
import subprocess
from pathlib import Path

STDERR_MAX = 1000
PS_TIMEOUT = 300  # seconds; a job that runs longer is wedged, not slow

# Data goes through a file written by WriteAllText without a BOM; stdout of
# powershell.exe uses the console code page. stderr is switched to UTF-8 so
# the reason of a failure arrives readable. {body} assigns the value to write
# to $result.
PS_TEMPLATE = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
{body}
$json = ConvertTo-Json -InputObject $result -Compress -Depth {depth}
[System.IO.File]::WriteAllText({path}, $json, [System.Text.UTF8Encoding]::new($false))
"""


def ps_quote(text: str) -> str:
    """A PowerShell single-quoted string literal."""
    return "'" + str(text).replace("'", "''") + "'"


def ps_script(body: str, out_path: Path, depth: int = 4) -> str:
    """The full script of a job: ``body`` must assign its result to ``$result``.

    Wrap a pipeline in ``@(...)`` to write a list even for one or no rows;
    ``load_rows`` accepts a single object as well.
    """
    return PS_TEMPLATE.format(body=body, depth=int(depth), path=ps_quote(out_path))


def default_run_ps(job: str, script: str, out_path: Path) -> tuple[int, str]:
    """Run one script in Windows PowerShell 5.1; return (exit code, stderr).

    The script is built from fixed templates; data comes back only through
    the file at out_path.
    """
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,  # a non-zero exit is data here
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 1, f"{job}: PowerShell did not finish within {PS_TIMEOUT} s and was stopped"
    except OSError as exc:
        return 1, f"{job}: powershell.exe could not be started: {type(exc).__name__}: {exc}"
    return result.returncode, result.stderr or ""


def load_rows(path) -> list[dict]:
    """Read a result file written by PowerShell as a list of objects.

    Accepts a file with or without a BOM. ConvertTo-Json writes a single
    object for one row, so an object becomes a one-element list. An empty
    file or ``null`` means no rows. Any other shape raises ValueError.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    if not text.strip():
        return []
    data = json.loads(text)
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise ValueError(f"{path}: expected a JSON object or a list of objects")
    return data


def run_job(run_ps, job: str, script: str, out_path: Path, empty_markers=()) -> dict:
    """One job: {status: read|empty|unreadable, reason, rows}.

    A stale out_path is deleted first, and the file is never read after a
    non-zero exit, so a leftover from an earlier run cannot pass for data.
    A non-zero exit whose stderr contains one of ``empty_markers`` (the text
    a cmdlet gives when it finds nothing) is ``empty``.
    """
    out_path = Path(out_path)
    try:
        out_path.unlink(missing_ok=True)
    except OSError as exc:
        return _unreadable(f"could not remove the old output file: {type(exc).__name__}: {exc}")
    code, stderr = run_ps(job, script, out_path)
    stderr = (stderr or "").strip()
    if code != 0:
        if any(marker in stderr for marker in empty_markers):
            return {"status": "empty", "reason": None, "rows": []}
        reason = stderr[:STDERR_MAX].strip()
        return _unreadable(reason or f"PowerShell exit code {code} without an error text")
    if not out_path.is_file():
        return _unreadable("PowerShell exited 0 but wrote no output file")
    try:
        rows = load_rows(out_path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return _unreadable(f"the output file could not be read: {type(exc).__name__}: {exc}")
    if not rows:
        return {"status": "empty", "reason": None, "rows": []}
    return {"status": "read", "reason": None, "rows": rows}


def _unreadable(reason: str) -> dict:
    return {"status": "unreadable", "reason": reason, "rows": []}


def with_ids(items: list[dict], prefix: str) -> list[dict]:
    """Give each item an ``id`` of ``prefix`` and its 1-based position."""
    return [{"id": f"{prefix}{n}", **item} for n, item in enumerate(items, 1)]


def dump(data) -> str:
    """Compact ASCII JSON: safe on any console code page."""
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))

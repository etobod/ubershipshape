"""Show what uses the memory of this machine, grouped by program, and where each
process comes from (read-only snapshot).

Sources (one read-only PowerShell job each, run through an injectable ``run_ps``;
see ``skills/ush-common/scripts/psrun.py``):

- ``processes``: ``Win32_Process`` (pid, parent pid, name, executable path,
  command line, session, working set, ``PrivatePageCount``); ``CreationDate`` is
  turned into ISO 8601 UTC text in PowerShell (5.1 would write ``\\/Date()\\/``,
  and the idle process may have none).
- ``perf``: ``Win32_PerfRawData_PerfProc_Process`` (``IDProcess``,
  ``WorkingSetPrivate``, the "Memory" column of Task Manager), without ``_Total``.
- ``owners``: ``GetOwner`` of every process, each in its own try/catch, so one
  process that ended between the jobs does not spoil the others.
- ``memory``: ``Win32_OperatingSystem`` (physical and commit memory, in KB).

A field Windows returned empty (path, command line, owner without rights) is
null and named in the item's ``unread_fields``: "not read", never "none". The
only exception is a pseudo-process listed in ``data/no-image-processes.json``
(by pid, or by name with parent pid 4) whose path is empty: it has no image
file even for an administrator, so it has ``path_kind: "none"`` and its null
path is not unread. That data file is the only classification here.

A parent is the process with the parent pid only when it started no later than
the child (pids are reused); otherwise ``parent_gone`` is true, and it is null
when a start time is missing. Processes are grouped by their executable path
(case-insensitive); processes whose path was not read form separate groups by
name, ``"<name> (path not read)"``, never merged with a known path. Groups are
ordered by private memory (by working set when ``perf`` was not read).

Why a group runs (facts, not judgements), from four more jobs and one file:

- ``services``: ``Win32_Service`` with a ``ProcessId`` and the registry ``Type``
  (bit 0x80: a per-user instance, keyed ``service:<template>`` without ``_<hex>``).
- ``file_facts``: existence, signature status (as text), signer (``O=``) and
  company of every group path, plus the expanded ``%ProgramFiles%``,
  ``%ProgramFiles(x86)%``, ``%SystemRoot%`` and ``System32``.
- ``tcp_listeners`` (``Get-NetTCPConnection -State Listen``) and
  ``udp_endpoints`` (``Get-NetUDPEndpoint``); no result is an error whose
  FullyQualifiedErrorId starts with ``CmdletizationQuery_NotFound``, which is
  ``empty``, not ``unreadable``.
- the ush-inventory baseline ``state/ush-inventory.json`` (``.elevated`` for an
  administrator run), read only: autostart entries whose ``expanded_path`` is the
  group path (targets named in ``data/launchers.json`` are never matched), the
  services it lists, and the program whose ``install_location`` is the longest
  folder prefix of the path.

``started_by`` is the first rule that holds: ``service``, ``autostart``,
``parent`` (every process has a parent), else ``unknown``; a rule whose input was
not read stops the walk with ``started_by`` null and unread. UDP endpoints are
bound sockets, not listeners: the summary counts them per group and scope.

Nothing is judged, nothing on the machine is changed, nothing is written in
``state/``. The summary goes to stdout and to
``work/processes-<UTC stamp>.summary.json``; command lines are only in the
detail file ``work/processes-<UTC stamp>.detail.json``. ``--detail <id>``
prints one group (with its processes) or one port of the newest detail file.
To keep the summary within ``SUMMARY_MAX_CHARS`` ``groups`` is cut from its end
(``truncated`` counts the cut groups); only when no group is left and it is
still too long are ``ports`` cut from their end, with a ``not_checked`` note.
"""

import argparse
import ipaddress
import json
import ntpath
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The shared modules live in skills/ush-common/scripts.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline
import datadir
import psrun
from psrun import dump, ps_script, run_job, with_ids

SKILL = "ush-processes"
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
DETAIL_SECTIONS = ("groups", "ports")
NO_IMAGE_FILE = Path(__file__).absolute().parents[1] / "data" / "no-image-processes.json"
LAUNCHERS_FILE = Path(__file__).absolute().parents[1] / "data" / "launchers.json"
JOBS = ("processes", "perf", "owners", "memory", "services")
PORT_JOBS = ("tcp_listeners", "udp_endpoints")
# The FullyQualifiedErrorId prefix of Get-NetTCPConnection / Get-NetUDPEndpoint
# without a result; the suffix depends on the filter (loc/PATTERNS.md).
NOT_FOUND = "CmdletizationQuery_NotFound"
SERVICES_MAX = 15
USER_SERVICE_INSTANCE = 0x80
INSTANCE_SUFFIX = re.compile(r"_[0-9a-f]+$", re.IGNORECASE)
DRIVE_ROOT = re.compile(r"^[a-z]:$", re.IGNORECASE)
INVENTORY_SKILL = "ush-inventory"
INVENTORY_SOURCES = ("run_keys", "startup_folders", "scheduled_tasks", "services",
                     "win32_programs", "msix_programs")
AUTOSTART_SOURCES = ("run_keys", "startup_folders", "scheduled_tasks")
PROGRAM_SOURCES = ("win32_programs", "msix_programs")
DIR_NAMES = ("ProgramFiles", "ProgramFilesX86", "SystemRoot", "System32")
FACT_FIELDS = ("exists", "signature_status", "signer", "company")
SCOPE_ORDER = {"all": 0, "address": 1, "loopback": 2}
GROUP_PIDS_MAX = 20
ANCESTORS_MAX = 6
KB = 1024
MB = 1024 ** 2
GB = 1024 ** 3
NOT_READ_SUFFIX = " (path not read)"
ISO_FRACTION = re.compile(r"^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$")

# --- PowerShell job bodies (each assigns $result) -------------------------------
PROCESSES_BODY = r"""$result = @(Get-CimInstance -ClassName Win32_Process | ForEach-Object {
    [pscustomobject]@{
        ProcessId = $_.ProcessId
        ParentProcessId = $_.ParentProcessId
        Name = $_.Name
        ExecutablePath = $_.ExecutablePath
        CommandLine = $_.CommandLine
        SessionId = $_.SessionId
        WorkingSetSize = $_.WorkingSetSize
        PrivatePageCount = $_.PrivatePageCount
        CreationDate = if ($_.CreationDate) { $_.CreationDate.ToUniversalTime().ToString('o') } else { $null }
    }
})
"""

PERF_BODY = r"""$result = @(Get-CimInstance -ClassName Win32_PerfRawData_PerfProc_Process |
    Where-Object { $_.Name -ne '_Total' } | ForEach-Object {
    [pscustomobject]@{ IDProcess = $_.IDProcess; WorkingSetPrivate = $_.WorkingSetPrivate }
})
"""

OWNERS_BODY = r"""$result = @(Get-CimInstance -ClassName Win32_Process | ForEach-Object {
    $p = $_
    try {
        $o = Invoke-CimMethod -InputObject $p -MethodName GetOwner -ErrorAction Stop
        [pscustomobject]@{ pid = $p.ProcessId; return_value = $o.ReturnValue; domain = $o.Domain; user = $o.User }
    } catch {
        [pscustomobject]@{ pid = $p.ProcessId; error = $_.Exception.Message }
    }
})
"""

MEMORY_BODY = r"""$result = @(Get-CimInstance -ClassName Win32_OperatingSystem | ForEach-Object {
    [pscustomobject]@{
        TotalVisibleMemorySize = $_.TotalVisibleMemorySize
        FreePhysicalMemory = $_.FreePhysicalMemory
        TotalVirtualMemorySize = $_.TotalVirtualMemorySize
        FreeVirtualMemory = $_.FreeVirtualMemory
    }
})
"""

# Services running in a process, with the registry Type (bit 0x80: a per-user
# instance); a registry read that fails leaves Type null.
SERVICES_BODY = r"""$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$result = @(Get-CimInstance -ClassName Win32_Service -Filter 'ProcessId > 0' | ForEach-Object {
    $s = $_
    $type = $null
    try {
        $k = $hklm.OpenSubKey('SYSTEM\CurrentControlSet\Services\' + $s.Name)
        if ($null -ne $k) {
            try { $v = $k.GetValue('Type', $null); if ($null -ne $v) { $type = [int]$v } } finally { $k.Close() }
        }
    } catch { $type = $null }
    [pscustomobject]@{
        Name = $s.Name; DisplayName = $s.DisplayName; ProcessId = $s.ProcessId
        StartMode = $s.StartMode; Type = $type
    }
})
$hklm.Close()
"""

# __INPUT__ is replaced by the quoted path of {"paths": [...]} (absolute group
# paths). Nothing is written; a file that cannot be checked is one row with Error.
# The signature status is written as text: 5.1 writes the enum as a number.
FILE_FACTS_BODY = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$rows = New-Object System.Collections.Generic.List[object]
$dirs = @(
    @('ProgramFiles', $env:ProgramFiles),
    @('ProgramFilesX86', ${env:ProgramFiles(x86)}),
    @('SystemRoot', $env:SystemRoot),
    @('System32', [Environment]::SystemDirectory)
)
foreach ($d in $dirs) { $rows.Add([pscustomobject]@{ Kind = 'dir'; Name = $d[0]; Path = $d[1] }) }
foreach ($p in @($in.paths)) {
    $path = [string]$p
    if (-not $path) { continue }
    try {
        $exists = [System.IO.File]::Exists($path)
        if (-not $exists) {
            # File.Exists is also false when access is denied; only "not found" is missing.
            try { $null = Get-Item -LiteralPath $path -Force -ErrorAction Stop; $exists = $true }
            catch [System.Management.Automation.ItemNotFoundException] { $exists = $false }
        }
        $status = $null; $signer = $null; $company = $null
        if ($exists) {
            $sig = Get-AuthenticodeSignature -LiteralPath $path
            $status = [string]$sig.Status
            if ($null -ne $sig.SignerCertificate) {
                $m = [regex]::Match($sig.SignerCertificate.Subject, '(?:^|,)\s*O=("(?:[^"]|"")*"|[^,]*)')
                if ($m.Success) {
                    $o = $m.Groups[1].Value.Trim()
                    if ($o.Length -ge 2 -and $o.StartsWith('"') -and $o.EndsWith('"')) {
                        $o = $o.Substring(1, $o.Length - 2).Replace('""', '"')
                    }
                    $signer = $o
                }
            }
            $company = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($path).CompanyName
        }
        $rows.Add([pscustomobject]@{
            Kind = 'file'; Path = $path; ExpandedPath = $path; Exists = $exists
            SignatureStatus = $status; Signer = $signer; Company = $company
        })
    } catch {
        $rows.Add([pscustomobject]@{ Kind = 'file'; Path = $path; Error = [string]$_.Exception.Message })
    }
}
$result = $rows.ToArray()
"""

# No result is an error, not an empty list: the FullyQualifiedErrorId goes to
# stderr, where run_job recognises it by its prefix (in any system language).
ENDPOINTS_BODY = r"""try {
    $result = @(__CMDLET__ -ErrorAction Stop | ForEach-Object {
        [pscustomobject]@{
            LocalAddress = [string]$_.LocalAddress; LocalPort = [int]$_.LocalPort
            OwningProcess = [int]$_.OwningProcess
        }
    })
} catch {
    [Console]::Error.WriteLine([string]$_.FullyQualifiedErrorId + ' : ' + [string]$_.Exception.Message)
    exit 1
}
"""

BODIES = {
    "processes": PROCESSES_BODY,
    "perf": PERF_BODY,
    "owners": OWNERS_BODY,
    "memory": MEMORY_BODY,
    "services": SERVICES_BODY,
    "tcp_listeners": ENDPOINTS_BODY.replace("__CMDLET__", "Get-NetTCPConnection -State Listen"),
    "udp_endpoints": ENDPOINTS_BODY.replace("__CMDLET__", "Get-NetUDPEndpoint"),
}


# --- small helpers ---------------------------------------------------------------
def text(value):
    """A non-empty string, or None (an empty field is not read, never "none")."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def as_int(value):
    """An int from a JSON number or a numeric string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def to_mb(value):
    return None if value is None else round(value / MB, 1)


def to_gb(value):
    return None if value is None else round(value / GB, 1)


def parse_time(value):
    """A tz-aware datetime from the job's ``ToString('o')`` text, else None."""
    if not isinstance(value, str):
        return None
    match = ISO_FRACTION.match(value.strip())
    if not match:
        return None
    base, fraction, zone = match.groups()
    micro = (fraction or "")[:6].ljust(6, "0")
    zone = "+00:00" if zone in (None, "Z") else zone
    try:
        moment = datetime.fromisoformat(f"{base}.{micro}{zone}")
    except ValueError:
        return None
    return moment.astimezone(timezone.utc)


def sum_known(values):
    """(sum of the non-null values or None when all are null, count of nulls)."""
    known = [v for v in values if v is not None]
    return (sum(known) if known else None), len(values) - len(known)


# --- data file -------------------------------------------------------------------
def load_no_image(path: Path):
    """``({"pids": set, "names": set}, reason or None)``; unreadable gives empty sets."""
    empty = {"pids": set(), "names": set()}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return empty, f"{path.name} could not be read: {type(exc).__name__}: {exc}"
    pids = data.get("pids") if isinstance(data, dict) else None
    names = data.get("names_with_parent_4") if isinstance(data, dict) else None
    if (not isinstance(pids, list) or not all(as_int(p) is not None for p in pids)
            or not isinstance(names, list) or not all(isinstance(n, str) for n in names)):
        return empty, (f"{path.name} does not hold 'pids' (numbers) and "
                       f"'names_with_parent_4' (texts)")
    return {"pids": {as_int(p) for p in pids}, "names": set(names)}, None


def load_launchers(path: Path):
    """``(set of case-folded file names, None)``, or ``(None, reason)`` when unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{path.name} could not be read: {type(exc).__name__}: {exc}"
    names = data.get("launchers") if isinstance(data, dict) else None
    if not isinstance(names, list) or not all(text(n) for n in names):
        return None, f"{path.name} does not hold 'launchers' (texts)"
    return {n.strip().casefold() for n in names}, None


def file_name(path):
    """The last part of a Windows path, case-folded; None for no path."""
    path = text(path)
    return ntpath.basename(path.strip()).casefold() if path else None


# --- collection --------------------------------------------------------------------
def record(job: str, result: dict, sources: list, not_checked: list) -> dict:
    """Name the job's status in ``sources`` (and in ``not_checked`` when unreadable)."""
    sources.append({"name": job, "status": result["status"], "reason": result["reason"]})
    if result["status"] == "unreadable":
        not_checked.append({"what": f"job {job}", "reason": result["reason"]})
    return result


def collect(run_ps, work: Path, stamp: str, jobs, sources: list, not_checked: list) -> dict:
    """Run ``jobs`` in order; return their results by job."""
    results = {}
    for job in jobs:
        out_path = work / f"processes-{stamp}.{job}.json"
        markers = (NOT_FOUND,) if job in PORT_JOBS else ()
        result = run_job(run_ps, job, ps_script(BODIES[job], out_path), out_path,
                         empty_markers=markers)
        results[job] = record(job, result, sources, not_checked)
    return results


def collect_file_facts(run_ps, work: Path, stamp: str, paths: list) -> dict:
    """The ``file_facts`` job for ``paths``; the list goes through an input file."""
    input_path = work / f"processes-{stamp}.file_facts.input.json"
    out_path = work / f"processes-{stamp}.file_facts.json"
    try:
        input_path.write_text(json.dumps({"paths": paths}, ensure_ascii=True), encoding="utf-8")
    except OSError as exc:
        return {"status": "unreadable", "rows": [],
                "reason": f"the path list could not be written: {type(exc).__name__}: {exc}"}
    body = FILE_FACTS_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
    return run_job(run_ps, "file_facts", ps_script(body, out_path), out_path)


def perf_by_pid(rows) -> dict:
    values = {}
    for row in rows:
        pid = as_int(row.get("IDProcess"))
        if pid is not None and pid not in values:
            values[pid] = as_int(row.get("WorkingSetPrivate"))
    return values


def owner_by_pid(rows) -> dict:
    """pid -> "domain\\user" when GetOwner returned 0 and a user, else None."""
    owners = {}
    for row in rows:
        pid = as_int(row.get("pid"))
        if pid is None or pid in owners:
            continue
        user = text(row.get("user"))
        if "error" in row or as_int(row.get("return_value")) != 0 or user is None:
            owners[pid] = None
            continue
        domain = text(row.get("domain"))
        owners[pid] = f"{domain}\\{user}" if domain else user
    return owners


def build_processes(rows, perf: dict, owners: dict, no_image: dict) -> tuple[list, int]:
    """Process items sorted by pid, and the number of rows without a pid."""
    items, skipped = {}, 0
    for row in rows:
        pid = as_int(row.get("ProcessId"))
        if pid is None or pid in items:
            skipped += 1
            continue
        unread = []
        name = text(row.get("Name")) or ""
        parent_pid = as_int(row.get("ParentProcessId"))
        path = text(row.get("ExecutablePath"))
        no_file = path is None and (
            pid in no_image["pids"] or (name in no_image["names"] and parent_pid == 4))
        if path is None and not no_file:
            unread.append("path")
        command_line = text(row.get("CommandLine"))
        if command_line is None and not no_file:
            unread.append("command_line")
        owner = owners.get(pid)
        if owner is None:
            unread.append("owner")
        private = perf.get(pid)
        working_set = as_int(row.get("WorkingSetSize"))
        commit = as_int(row.get("PrivatePageCount"))
        for field, value in (("memory_private_bytes", private),
                             ("working_set_bytes", working_set), ("commit_bytes", commit)):
            if value is None:
                unread.append(field)
        items[pid] = {
            "pid": pid,
            "name": name,
            "path_kind": "none" if no_file else "file",
            "path": path,
            "command_line": command_line,
            "owner": owner,
            "session_id": as_int(row.get("SessionId")),
            "started_at": text(row.get("CreationDate")),
            "parent_pid": parent_pid,
            "parent": None,
            "parent_gone": None,
            "ancestors": [],
            "memory_private_bytes": private,
            "memory_private_mb": to_mb(private),
            "working_set_bytes": working_set,
            "working_set_mb": to_mb(working_set),
            "commit_bytes": commit,
            "commit_mb": to_mb(commit),
            "group": None,
            "unread_fields": unread,
        }
    link_parents(items, no_image["pids"])
    return [items[pid] for pid in sorted(items)], skipped


def link_parents(items: dict, kernel_pids=frozenset()) -> None:
    """Set parent, parent_gone and ancestors (a reused pid is no parent).

    A pid of ``kernel_pids`` (``no-image-processes.json`` ``pids``) is never reused, and
    Windows may report System as starting after its own children: no time check.
    """
    for item in items.values():
        parent_pid = item["parent_pid"]
        if parent_pid is None:
            item["parent_gone"] = None  # the parent pid itself was not read
            continue
        if parent_pid == 0:
            item["parent_gone"] = False
            continue
        candidate = items.get(parent_pid)
        if candidate is None:
            item["parent_gone"] = True
            continue
        child_time = parse_time(item["started_at"])
        parent_time = parse_time(candidate["started_at"])
        if parent_pid in kernel_pids:
            item["parent"] = {"pid": candidate["pid"], "name": candidate["name"]}
            item["parent_gone"] = False
        elif child_time is None or parent_time is None:
            item["parent_gone"] = None
        elif parent_time <= child_time:
            item["parent"] = {"pid": candidate["pid"], "name": candidate["name"]}
            item["parent_gone"] = False
        else:
            item["parent_gone"] = True
    for item in items.values():
        seen = {item["pid"]}
        ancestors = []
        current = item["parent"]
        while current is not None and len(ancestors) < ANCESTORS_MAX:
            if current["pid"] in seen:
                break
            seen.add(current["pid"])
            ancestors.append(current["name"])
            current = items[current["pid"]]["parent"]
        item["ancestors"] = ancestors


def group_key(item: dict) -> tuple:
    if item["path"] is not None:
        return ("path", item["path"].casefold())
    if item["path_kind"] == "none":
        return ("none", item["name"].casefold())
    return ("unread", item["name"].casefold())


def build_groups(processes: list, sorted_by: str) -> list:
    """Detail groups (with their process items), ordered and with ids ``g1...``."""
    members = {}
    for item in processes:  # processes are sorted by pid
        members.setdefault(group_key(item), []).append(item)
    groups = []
    for key, items in members.items():
        first = items[0]
        pids = {p["pid"] for p in items}
        private, private_unread = sum_known([p["memory_private_bytes"] for p in items])
        working_set, _ = sum_known([p["working_set_bytes"] for p in items])
        commit, _ = sum_known([p["commit_bytes"] for p in items])
        starts = [p["started_at"] for p in items if parse_time(p["started_at"]) is not None]
        unread = []
        if key[0] == "unread":
            unread.append("path")
        for field, value in (("memory_private_bytes", private),
                             ("working_set_bytes", working_set), ("commit_bytes", commit)):
            if value is None:
                unread.append(field)
        groups.append({
            "name": first["name"] + (NOT_READ_SUFFIX if key[0] == "unread" else ""),
            "path": first["path"],
            "path_kind": first["path_kind"],
            "count": len(items),
            "pids": [p["pid"] for p in items],
            "memory_private_bytes": private,
            "memory_private_mb": to_mb(private),
            "memory_unread_count": private_unread,
            "working_set_bytes": working_set,
            "working_set_mb": to_mb(working_set),
            "commit_bytes": commit,
            "commit_mb": to_mb(commit),
            "started_at_min": min(starts, key=parse_time) if starts else None,
            "owners": sorted({p["owner"] for p in items if p["owner"] is not None}),
            "owner_unread_count": sum(1 for p in items if p["owner"] is None),
            "command_line_unread_count": sum(1 for p in items
                                             if "command_line" in p["unread_fields"]),
            "parents": sorted({p["parent"]["name"] for p in items
                               if p["parent"] is not None and p["parent"]["pid"] not in pids}),
            "parent_gone_count": sum(1 for p in items if p["parent_gone"] is True),
            "unread_fields": unread,
            "processes": items,
        })

    def order(group):
        value = group[sorted_by]
        return (value is None, -(value or 0), group["name"].casefold(), group["pids"][0])

    groups.sort(key=order)
    for n, group in enumerate(groups, 1):
        group["id"] = f"g{n}"
        for item in group["processes"]:
            item["group"] = group["id"]
    return [{"id": g.pop("id"), **g} for g in groups]


def summary_group(group: dict) -> dict:
    """A group as the summary lists it: no process items, at most 20 pids and 15
    services (``services_count`` has them all)."""
    kept = {k: v for k, v in group.items() if k != "processes"}
    kept["pids"] = group["pids"][:GROUP_PIDS_MAX]
    if isinstance(group.get("services"), list):
        kept["services"] = group["services"][:SERVICES_MAX]
    return kept


# --- services ------------------------------------------------------------------------
def service_key(name: str, kind, known: dict) -> str:
    """``service:<Name>``, or ``service:<template>`` for a per-user instance (Type bit
    0x80; with no Type, only when the inventory baseline knows the template as one)."""
    template = INSTANCE_SUFFIX.sub("", name)
    if kind is not None:
        instance = bool(kind & USER_SERVICE_INSTANCE)
    else:
        item = known.get(f"service:{template}")
        instance = template != name and isinstance(item, dict) and item.get("user_service") is True
    return f"service:{template if instance else name}"


def services_by_pid(rows, known: dict) -> dict:
    """pid -> service items ``{name, display_name, start_mode, key}``."""
    result, seen = {}, set()
    for row in rows:
        name, pid = text(row.get("Name")), as_int(row.get("ProcessId"))
        if name is None or pid is None or (pid, name.casefold()) in seen:
            continue
        seen.add((pid, name.casefold()))
        result.setdefault(pid, []).append({
            "name": name,
            "display_name": text(row.get("DisplayName")),
            "start_mode": text(row.get("StartMode")),
            "key": service_key(name, as_int(row.get("Type")), known),
        })
    return result


# --- ush-inventory baseline -------------------------------------------------------------
def entry_without_path(item: dict) -> bool:
    """An autostart entry none of whose targets can be matched by path."""
    facts = item.get("facts")
    if "facts" in (item.get("unread_fields") or []) or not isinstance(facts, list) or not facts:
        return True
    return any(not isinstance(f, dict) or text(f.get("expanded_path")) is None for f in facts)


def read_inventory(state_dir: Path, admin: bool, now: datetime):
    """``(inventory summary, sources or None, not_checked notes)``; the file is only read."""
    loaded = baseline.load(state_dir, INVENTORY_SKILL, admin)
    file_name_ = f"{baseline.baseline_name(INVENTORY_SKILL, admin)}.json"
    inventory = {"status": loaded["status"], "reason": loaded["reason"], "age_days": None,
                 "created_at": loaded["created_at"], "missing_sources": None,
                 "entries_without_path": None}
    notes = []
    if loaded["status"] != "read":
        why = (f"there is no {file_name_} in {state_dir}" if loaded["status"] == "none"
               else f"the baseline could not be read: {loaded['reason']}")
        notes.append({"what": "ush-inventory baseline",
                      "reason": f"{why}; autostart entries, the services it lists and "
                                f"programs are not linked to groups (run ush-inventory)"})
        return inventory, None, notes
    sources = loaded["sources"]
    inventory["age_days"] = baseline.age_days(loaded["created_at"], now)
    missing = [name for name in INVENTORY_SOURCES if name not in sources]
    without_path = sum(1 for name in AUTOSTART_SOURCES
                       for item in (sources.get(name) or {}).values()
                       if entry_without_path(item))
    inventory["missing_sources"] = missing
    inventory["entries_without_path"] = without_path
    if missing:
        notes.append({"what": "ush-inventory sources",
                      "reason": f"the baseline has no {', '.join(missing)}: a group without "
                                f"a link from them may still have one"})
    if without_path:
        notes.append({"what": "ush-inventory entries without a path",
                      "reason": f"{without_path} autostart entries of the baseline have no "
                                f"expanded target path and cannot be linked to a group"})
    return inventory, sources, notes


def autostart_index(sources: dict, launchers: set) -> dict:
    """Case-folded expanded target path -> {key: {key, kind, enabled, program}}.

    A target whose file is a launcher (``rundll32.exe`` and the like) is left out: it
    does not tell which process of that program the entry started.
    """
    index = {}
    for source in AUTOSTART_SOURCES:
        for key, item in (sources.get(source) or {}).items():
            if "facts" in (item.get("unread_fields") or []):
                continue
            for fact in item.get("facts") or []:
                if not isinstance(fact, dict):
                    continue
                expanded = text(fact.get("expanded_path"))
                if expanded is None:
                    continue
                if {file_name(fact.get("path")), file_name(expanded)} & launchers:
                    continue
                index.setdefault(expanded.strip().casefold(), {}).setdefault(key, {
                    "key": key,
                    "kind": item.get("kind"),
                    "enabled": item.get("enabled"),
                    "program": text(fact.get("program")),
                })
    return index


def clean_location(value):
    """An install location without quotes and trailing slashes, ``\\SystemRoot\\`` as
    ``%SystemRoot%\\`` (as ush-inventory reads it); else None."""
    value = text(value)
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].strip()
    if value.casefold().startswith("\\systemroot\\"):
        value = "%SystemRoot%" + value[len("\\SystemRoot"):]
    return text(value.rstrip("\\/"))


def program_matcher(sources: dict, dirs: dict):
    """``match(path) -> program key or None``: the longest ``install_location`` that is
    a folder prefix of the path, case-insensitively. A drive root and the four
    directories of ``dirs`` never match (the rule of ush-inventory)."""
    skipped = {d.rstrip("\\/").casefold() for d in dirs.values() if text(d)}
    locations = []
    for source in PROGRAM_SOURCES:
        for key, item in (sources.get(source) or {}).items():
            location = clean_location(item.get("install_location"))
            if not location or DRIVE_ROOT.match(location) or location.casefold() in skipped:
                continue
            locations.append((location.casefold() + "\\", key))
    locations.sort(key=lambda entry: (-len(entry[0]), entry[1]))

    def match(path):
        folded = path.strip().casefold()
        for prefix, key in locations:
            if folded.startswith(prefix):
                return key
        return None

    return match


def program_names(sources: dict) -> dict:
    names = {}
    for source in PROGRAM_SOURCES:
        for key, item in (sources.get(source) or {}).items():
            names.setdefault(key, text(item.get("name")))
    return names


# --- file facts -------------------------------------------------------------------------
def split_facts(rows) -> tuple[dict, dict]:
    """``(directories by name, file rows by case-folded path)``."""
    dirs, files = {}, {}
    for row in rows:
        if row.get("Kind") == "dir" and text(row.get("Name")):
            dirs[text(row.get("Name"))] = text(row.get("Path"))
        elif row.get("Kind") == "file" and text(row.get("Path")):
            files.setdefault(text(row.get("Path")).strip().casefold(), row)
    return dirs, files


def group_facts(path, facts_read: bool, files: dict) -> tuple[dict, list]:
    """``({exists, signature_status, signer, company}, unread field names)``.

    No path: nothing to read, all null and not unread. A failed job, a missing row or
    a row with ``Error``: all unread. A signature status that is not text (5.1 writes
    the enum as a number) is unread; so is a missing one for a file that exists.
    """
    values = dict.fromkeys(FACT_FIELDS)
    if path is None:
        return values, []
    row = files.get(path.strip().casefold()) if facts_read else None
    if row is None or text(row.get("Error")) is not None:
        return values, list(FACT_FIELDS)
    unread = []
    exists = row.get("Exists")
    values["exists"] = exists if isinstance(exists, bool) else None
    if values["exists"] is None:
        unread.append("exists")
    status = row.get("SignatureStatus")
    if isinstance(status, str) and status.strip():
        values["signature_status"] = status
    elif status is not None or values["exists"] is not False:
        unread.append("signature_status")
    values["signer"] = text(row.get("Signer"))
    values["company"] = text(row.get("Company"))
    return values, unread


# --- links of a group -------------------------------------------------------------------
def link_groups(groups: list, services, inventory_sources, launchers, facts: dict) -> None:
    """Add services, autostart, program, file facts and ``started_by`` to every group.

    ``services`` is pid -> items, or None when the job was not read;
    ``inventory_sources`` is None when the baseline was not read; ``launchers`` is
    None when its data file could not be read; ``facts`` is ``{read, dirs_known,
    files}`` of the ``file_facts`` job.
    """
    known_services = (inventory_sources or {}).get("services") or {}
    index = None
    match = names = None
    if inventory_sources is not None:
        if launchers is not None:
            index = autostart_index(inventory_sources, launchers)
        names = program_names(inventory_sources)
        if facts["dirs_known"]:
            match = program_matcher(inventory_sources, facts["dirs"])
    for group in groups:
        unread = group["unread_fields"]
        path = group["path"]
        # A file whose path was not read may still have an entry or a program: unknown.
        path_unread = path is None and group["path_kind"] == "file"

        if services is None:
            group_services = None
            unread.append("services")
        else:
            by_name = {}
            for pid in group["pids"]:
                for item in services.get(pid, []):
                    by_name.setdefault(item["name"].casefold(), item)
            group_services = sorted(by_name.values(),
                                    key=lambda s: (s["name"].casefold(), s["name"]))

        if index is None or path_unread:
            autostart, entries = None, []
            unread.append("autostart")
        else:
            entries = sorted((index.get(path.strip().casefold()) or {}).values()
                             if path is not None else [], key=lambda e: e["key"])
            found = {e["key"]: {k: e[k] for k in ("key", "kind", "enabled")} for e in entries}
            for item in group_services or []:
                baseline_item = known_services.get(item["key"])
                if isinstance(baseline_item, dict) and item["key"] not in found:
                    found[item["key"]] = {"key": item["key"],
                                          "kind": baseline_item.get("kind") or "service",
                                          "enabled": baseline_item.get("enabled")}
            autostart = [found[key] for key in sorted(found)]

        program_key = next((e["program"] for e in entries if e["program"]), None)
        program_unread = False
        if program_key is None and (path is not None or path_unread):
            if match is None or path_unread:
                program_unread = True
            else:
                program_key = match(path)
        if program_unread:
            unread.append("program")
        program = None if program_key is None else {"key": program_key,
                                                    "name": (names or {}).get(program_key)}

        values, facts_unread = group_facts(path, facts["read"], facts["files"])
        unread.extend(facts_unread)

        if group_services is None:
            started_by = None
        elif group_services:
            started_by = "service"
        elif autostart is None:
            started_by = None
        elif any(a["enabled"] is True for a in autostart):
            started_by = "autostart"
        elif any(a["enabled"] is None for a in autostart):
            started_by = None  # an entry whose state was not read might have started it
        elif any(p["parent"] is None and p["parent_gone"] is None
                 for p in group["processes"]):
            started_by = None
        elif all(p["parent"] is not None for p in group["processes"]):
            started_by = "parent"
        else:
            started_by = "unknown"
        if started_by is None:
            unread.append("started_by")

        processes = group.pop("processes")
        unread_fields = group.pop("unread_fields")
        group.update({
            "services": group_services,
            "services_count": None if group_services is None else len(group_services),
            "autostart": autostart,
            "program": program,
            **values,
            "started_by": started_by,
            "unread_fields": unread_fields,
            "processes": processes,
        })


# --- ports ------------------------------------------------------------------------------
def scope_of(address: str) -> str:
    """``loopback`` (127.0.0.0/8, ::1), ``all`` (0.0.0.0, ::) or ``address``."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return "address"
    if ip.is_unspecified:
        return "all"
    if ip.is_loopback:
        return "loopback"
    return "address"


def endpoints(rows, names: dict, group_of: dict) -> tuple[list, int]:
    """Endpoint items, a repeated (address, port, pid) once; and the unusable rows."""
    items, seen, bad = [], set(), 0
    for row in rows:
        address = text(row.get("LocalAddress"))
        port, pid = as_int(row.get("LocalPort")), as_int(row.get("OwningProcess"))
        if address is None or port is None or pid is None:
            bad += 1
            continue
        address = address.strip()
        if (address.casefold(), port, pid) in seen:
            continue
        seen.add((address.casefold(), port, pid))
        items.append({"local_address": address, "local_port": port, "scope": scope_of(address),
                      "pid": pid, "process": names.get(pid), "group": group_of.get(pid)})
    items.sort(key=lambda e: (SCOPE_ORDER[e["scope"]], e["local_port"], e["local_address"],
                              e["pid"]))
    return items, bad


def udp_bound(items: list, group_names: dict) -> list:
    """UDP endpoints counted per (group, scope); a pid without a group by its process."""
    counts = {}
    for item in items:
        name = group_names.get(item["group"]) if item["group"] else item["process"]
        key = (item["group"], name, item["scope"])
        counts[key] = counts.get(key, 0) + 1

    def order(key):
        group, name, scope = key
        number = int(group[1:]) if group else float("inf")
        return (number, str(name), SCOPE_ORDER[scope])

    return [{"group": g, "process": n, "scope": s, "count": counts[(g, n, s)]}
            for g, n, s in sorted(counts, key=order)]


def memory_facts(result: dict) -> dict:
    """Physical and commit memory in bytes and GB; null when the job gave no row."""
    row = result["rows"][0] if result["status"] == "read" else {}
    values = {}
    for prefix, total_field, free_field in (
            ("", "TotalVisibleMemorySize", "FreePhysicalMemory"),
            ("commit_", "TotalVirtualMemorySize", "FreeVirtualMemory")):
        total_kb, free_kb = as_int(row.get(total_field)), as_int(row.get(free_field))
        total = None if total_kb is None else total_kb * KB
        available = None if free_kb is None else free_kb * KB
        used = None if total is None or available is None else total - available
        values[f"{prefix}total_bytes"] = total
        values[f"{prefix}available_bytes"] = available
        values[f"{prefix}used_bytes"] = used
    memory = {}
    for prefix in ("", "commit_"):
        for part in ("total", "available", "used"):
            memory[f"{prefix}{part}_bytes"] = values[f"{prefix}{part}_bytes"]
    for prefix in ("", "commit_"):
        for part in ("total", "available", "used"):
            memory[f"{prefix}{part}_gb"] = to_gb(values[f"{prefix}{part}_bytes"])
    memory["listed_private_bytes"] = None
    memory["listed_private_gb"] = None
    return memory


# --- summary budget -----------------------------------------------------------------
def set_cut(summary: dict, parts: dict, kept_groups: int, kept_ports: int) -> None:
    """Keep the first ``kept_groups`` groups and ``kept_ports`` ports, and set the
    fields that depend on the cut (listed memory, ``group_in_summary``, ``udp_bound``)."""
    groups = parts["groups"]
    summary["groups"] = groups[:kept_groups]
    summary["truncated"] = len(groups) - kept_groups
    listed = None
    values = [g["memory_private_bytes"] for g in summary["groups"]
              if g["memory_private_bytes"] is not None]
    # No group with a read value is no sum at all, not a zero.
    if parts["private_read"] and values:
        listed = sum(values)
    summary["memory"]["listed_private_bytes"] = listed
    summary["memory"]["listed_private_gb"] = to_gb(listed)
    ids = {g["id"] for g in summary["groups"]}
    # A port of a process that is not in the process list has no group to cut: null.
    summary["ports"] = [{**p, "group_in_summary": None if p["group"] is None
                         else p["group"] in ids}
                        for p in parts["ports"][:kept_ports]]
    summary["udp_bound"] = [u for u in parts["udp_bound"]
                            if u["group"] is None or u["group"] in ids]
    summary["counts"]["udp_bound_outside_summary"] = sum(
        u["count"] for u in parts["udp_bound"] if u["group"] is not None and u["group"] not in ids)


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


def fit_budget(summary: dict, parts: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    ``groups`` is cut from its end first. Only when the summary without any group is
    still too long are ``ports`` cut from their end (a ``not_checked`` note gives how
    many), and then as many groups as fit come back. Notes are in place before the
    cut, so their length is measured too.
    """
    groups, ports = parts["groups"], parts["ports"]

    def fits(kept_groups: int, kept_ports: int) -> bool:
        set_cut(summary, parts, kept_groups, kept_ports)
        return len(dump(summary)) <= SUMMARY_MAX_CHARS

    if not fits(len(groups), len(ports)):
        notes = summary["not_checked"]
        group_note = {"what": "groups cut from the summary",
                      "reason": f"the groups with the least memory (see truncated) are only "
                                f"in the detail file; summary budget {SUMMARY_MAX_CHARS} "
                                f"characters"}
        port_note = {"what": "ports cut from the summary", "reason": ""}
        if groups:
            notes.append(group_note)

        def ports_fit(kept: int) -> bool:
            port_note["reason"] = (f"{len(ports) - kept} TCP listening ports at the end of "
                                   f"the list are only in the detail file; even without any "
                                   f"group the summary exceeded {SUMMARY_MAX_CHARS} characters")
            return fits(0, kept)

        if fits(0, len(ports)):
            fits(most_that_fit(lambda n: fits(n, len(ports)), len(groups)), len(ports))
        elif ports:
            notes.append(port_note)
            if ports_fit(0):
                kept_ports = most_that_fit(ports_fit, len(ports))
                ports_fit(kept_ports)
                fits(most_that_fit(lambda n: fits(n, kept_ports), len(groups)), kept_ports)
            else:
                notes.remove(port_note)
        if summary["truncated"] == 0 and group_note in notes:
            notes.remove(group_note)
        if len(dump(summary)) > SUMMARY_MAX_CHARS:
            # Something else is too long: cutting would lose groups and ports for nothing.
            for note in (group_note, port_note):
                if note in notes:
                    notes.remove(note)
            set_cut(summary, parts, len(groups), len(ports))
    text_out = dump(summary)
    if len(text_out) > SUMMARY_MAX_CHARS:
        summary["not_checked"].append({
            "what": "summary budget",
            "reason": f"the summary exceeds {SUMMARY_MAX_CHARS} characters and was not cut",
        })
        text_out = dump(summary)
    return text_out


# --- machine functions ----------------------------------------------------------------
def default_run_ps(job, script, out_path):
    return psrun.default_run_ps(job, script, out_path)


def default_is_admin() -> bool:
    try:
        import ctypes  # Windows-only, and only for a real run

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


# --- command line ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=None, help=datadir.HELP)
    parser.add_argument("--detail", metavar="ID",
                        help="print one group or port of the newest detail file and exit")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    return parser


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("processes-*.detail.json"), key=lambda p: p.name)
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


def main(argv=None, run_ps=None, is_admin=None, now=None) -> int:
    """Collect and summarise, or print one detail group or port with --detail.

    ``run_ps`` and ``is_admin`` are the two inputs from the machine. Either both
    are injected (tests) or neither (a real run): injecting only one is a
    TypeError, so a test that forgets a fake fails loudly instead of reading
    the machine.
    """
    if (run_ps is None) != (is_admin is None):
        raise TypeError("inject both run_ps and is_admin, or neither")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data_dir = datadir.resolve(args.data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    work = data_dir / "work"
    if args.detail_file is not None and args.detail is None:
        parser.error("--detail-file needs --detail")
    if args.detail is not None:
        detail_file = None if args.detail_file is None else Path(args.detail_file).resolve()
        return show_detail(work, args.detail, detail_file)

    run_ps = run_ps or default_run_ps
    is_admin = is_admin or default_is_admin
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    work.mkdir(parents=True, exist_ok=True)
    summary_file = work / f"processes-{stamp}.summary.json"
    detail_file = work / f"processes-{stamp}.detail.json"

    admin = bool(is_admin())
    sources, not_checked = [], []
    results = collect(run_ps, work, stamp, JOBS, sources, not_checked)
    no_image, no_image_reason = load_no_image(NO_IMAGE_FILE)
    if no_image_reason is not None:
        not_checked.append({"what": NO_IMAGE_FILE.name,
                            "reason": f"no process is treated as having no image file: "
                                      f"{no_image_reason}"})

    private_read = results["perf"]["status"] == "read"
    sorted_by = "memory_private_bytes" if private_read else "working_set_bytes"
    processes, skipped = build_processes(
        results["processes"]["rows"], perf_by_pid(results["perf"]["rows"]),
        owner_by_pid(results["owners"]["rows"]), no_image)
    if skipped:
        not_checked.append({"what": "process rows",
                            "reason": f"{skipped} rows of the processes job had no usable "
                                      f"or a repeated ProcessId and were left out"})
    groups = build_groups(processes, sorted_by)

    inventory, inventory_sources, notes = read_inventory(data_dir / "state", admin, now)
    not_checked.extend(notes)
    launchers, launchers_reason = load_launchers(LAUNCHERS_FILE)
    if launchers_reason is not None and inventory_sources is not None:
        not_checked.append({"what": LAUNCHERS_FILE.name,
                            "reason": f"autostart entries are not linked to groups: "
                                      f"{launchers_reason}"})

    paths = [g["path"] for g in groups if g["path"] is not None]
    facts_result = record("file_facts", collect_file_facts(run_ps, work, stamp, paths),
                          sources, not_checked)
    dirs, files = split_facts(facts_result["rows"])
    facts_read = facts_result["status"] == "read"
    facts = {"read": facts_read, "dirs": dirs, "files": files,
             "dirs_known": facts_read and all(name in dirs for name in DIR_NAMES)}
    if facts_read:
        rows = [files.get(path.strip().casefold()) for path in paths]
        missing = sum(1 for row in rows if row is None or text(row.get("Error")) is not None)
        if missing:
            not_checked.append({"what": "file_facts files",
                                "reason": f"{missing} group paths have no file facts (the "
                                          f"file could not be checked or has no row)"})
    elif facts_result["status"] == "empty":
        not_checked.append({"what": "job file_facts",
                            "reason": "the job returned no rows, not even its directories; "
                                      "no file facts and no program by folder"})

    results.update(collect(run_ps, work, stamp, PORT_JOBS, sources, not_checked))
    services = (services_by_pid(results["services"]["rows"],
                                (inventory_sources or {}).get("services") or {})
                if results["services"]["status"] != "unreadable" else None)
    link_groups(groups, services, inventory_sources, launchers, facts)

    names = {p["pid"]: p["name"] for p in processes}
    group_of = {p["pid"]: p["group"] for p in processes}
    tcp, tcp_bad = endpoints(results["tcp_listeners"]["rows"], names, group_of)
    ports = with_ids([{"protocol": "tcp", **item} for item in tcp], "p")
    udp_all, udp_bad = endpoints(results["udp_endpoints"]["rows"], names, group_of)
    udp = [item for item in udp_all if item["local_port"] != 0]
    for job, bad in (("tcp_listeners", tcp_bad), ("udp_endpoints", udp_bad)):
        if bad:
            not_checked.append({"what": f"{job} rows",
                                "reason": f"{bad} rows had no usable address, port or "
                                          f"process id and were left out"})

    counts = {
        "processes": len(processes),
        "groups": len(groups),
        "path_unread": sum(1 for p in processes if "path" in p["unread_fields"]),
        "command_line_unread": sum(1 for p in processes
                                   if "command_line" in p["unread_fields"]),
        "owner_unread": sum(1 for p in processes if p["owner"] is None),
        "memory_unread": sum(1 for p in processes if p["memory_private_bytes"] is None),
        "no_image": sum(1 for p in processes if p["path_kind"] == "none"),
        "ports": len(ports),
        "udp_endpoints": len(udp),
        "udp_port_zero": len(udp_all) - len(udp),
        "udp_bound_outside_summary": 0,
    }

    detail = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "sources": sources,
        "sorted_by": sorted_by,
        "inventory": inventory,
        "processes": processes,
        "groups": groups,
        "ports": ports,
        "udp_endpoints": udp,
    }
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

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
        "sorted_by": sorted_by,
        "memory": memory_facts(results["memory"]),
        "inventory": inventory,
        "counts": counts,
        "groups": [],
        "ports": [],
        "udp_bound": [],
    }
    parts = {"groups": [summary_group(g) for g in groups], "ports": ports,
             "udp_bound": udp_bound(udp, {g["id"]: g["name"] for g in groups}),
             "private_read": private_read}
    text_out = fit_budget(summary, parts)
    summary_file.write_text(text_out, encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

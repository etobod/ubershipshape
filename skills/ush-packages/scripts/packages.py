"""Read the installed packages of the package managers offline from disk (read-only).

Plan 061 moved the pip and npm reading of ush-inventory here, with the same
PowerShell bodies, keys, item fields, ``from_baseline`` carrying and not_checked
entries. No package manager runs: pip, npm and winget are never started.

Sources (read-only PowerShell jobs, run through an injectable ``run_ps``; see
``skills/ush-common/scripts/psrun.py``):

- ``pip_packages``: the Pythons registered under PEP 514 (job
  ``python_registrations``) and the ``dist-info`` / ``egg-info`` metadata of their
  install and per-user ``site-packages`` folders (job ``package_folders``). Key
  ``pip:<company>/<tag>|<install|user>|<PEP 503 name>``.
- ``npm_packages``: the ``package.json`` of each package in the global
  ``node_modules`` folder (job ``package_folders``, layout ``npm``); the prefix comes
  from ``NPM_CONFIG_PREFIX``, else the ``prefix=`` line of ``%USERPROFILE%\\.npmrc``
  (job ``npmrc``), else ``%APPDATA%\\npm``. Key ``npm:<install name>``.

Both are compared with the baseline ``ush-packages`` on ``version``; the changes
are ``c`` items. The summary lists every manager of ``data/managers.json`` under
``managers`` in the file's order: pip and npm with their state, every other one
``not_read`` and named in not_checked as "not read yet" (never "not present").
Every package of a read manager is a ``k`` item of the flat ``packages`` list.
No package is checked for a newer version: that needs an ush-advice lookup.

The summary keeps within ``SUMMARY_MAX_CHARS``: over it, ``packages`` items are
cut first, then ``c`` items; the detail file keeps them all (``--detail <id>``).
"""

import argparse
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The shared modules live in skills/ush-common/scripts.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline  # called as baseline.save(...), so tests can patch it
import datadir
import ids
import psrun
from psrun import dump, ps_script, run_job

SKILL = "ush-packages"
SCHEMA_VERSION = 1
# The same budget as ush-inventory's summary.
SUMMARY_MAX_CHARS = 35000
DETAIL_SECTIONS = ("packages", "changes")
# The managers of B-01 in report order: {name, step, read}; read at run time.
MANAGERS_FILE = Path(__file__).absolute().parents[1] / "data" / "managers.json"
# The managers this script reads; every other one is "not_read".
READ_MANAGERS = {"pip": "pip_packages", "npm": "npm_packages"}
NOT_READ_YET = "not read yet"

# The sources with items, compared with the baseline, in change order.
SOURCES = ("pip_packages", "npm_packages")
READ_STATUSES = ("read", "empty")
COMPARED_FIELDS = {"pip_packages": ("version",), "npm_packages": ("version",)}
CHANGE_ORDER = ("added", "removed", "changed")


# --- PowerShell -----------------------------------------------------------
# Shared helper prepended to every job body: S keeps $null as null (a plain
# [string] cast would turn it into ""); N reads an integer from text or null.
PS_HELPERS = r"""function S($v) {
  if ($null -eq $v) { return $null }
  if ($v -is [array]) { return (@($v | ForEach-Object { [string]$_ }) -join ', ') }
  return [string]$v
}
function N($v) {
  if ($null -eq $v) { return $null }
  [long]$n = 0
  if ([long]::TryParse(([string]$v).Trim(), [ref]$n)) { return $n }
  return $null
}
"""



# PEP 514 registrations: HKCU once (it is not split by registry view), HKLM in the
# 64-bit and the 32-bit view. Read only through the registry API: OpenSubKey gives
# null for a missing key (no Python registered is "nothing there") and throws when
# access is denied, so a denial fails the job instead of passing for an empty list.
PYTHON_REGISTRATIONS_BODY = r"""$rows = New-Object System.Collections.Generic.List[object]
function ReadHive($hive, $view, $name) {
  $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
  try {
    $root = $base.OpenSubKey('Software\Python')
    if ($null -eq $root) { return }
    try {
      foreach ($company in @($root.GetSubKeyNames())) {
        $ck = $root.OpenSubKey($company)
        if ($null -eq $ck) { continue }
        try {
          foreach ($tag in @($ck.GetSubKeyNames())) {
            $tk = $ck.OpenSubKey($tag)
            if ($null -eq $tk) { continue }
            try {
              $install = $null
              $ik = $tk.OpenSubKey('InstallPath')
              if ($null -ne $ik) { try { $install = S $ik.GetValue('') } finally { $ik.Close() } }
              $viewName = $null
              if ($name -eq 'HKLM') {
                $viewName = '32'
                if ($view -eq [Microsoft.Win32.RegistryView]::Registry64) { $viewName = '64' }
              }
              $rows.Add([pscustomobject][ordered]@{
                hive = $name; view = $viewName; company = S $company; tag = S $tag
                install_path = $install; sys_version = S $tk.GetValue('SysVersion')
                sys_architecture = S $tk.GetValue('SysArchitecture')
              })
            } finally { $tk.Close() }
          }
        } finally { $ck.Close() }
      }
    } finally { $root.Close() }
  } finally { $base.Close() }
}
ReadHive ([Microsoft.Win32.RegistryHive]::CurrentUser) ([Microsoft.Win32.RegistryView]::Default) 'HKCU'
ReadHive ([Microsoft.Win32.RegistryHive]::LocalMachine) ([Microsoft.Win32.RegistryView]::Registry64) 'HKLM'
ReadHive ([Microsoft.Win32.RegistryHive]::LocalMachine) ([Microsoft.Win32.RegistryView]::Registry32) 'HKLM'
$result = $rows.ToArray()
"""

# Package folders (layout "python": the *.dist-info\METADATA and *.egg-info\PKG-INFO
# of a site-packages folder, or an *.egg-info file itself; layout "npm": name and
# version of each package.json in a node_modules folder, scoped ones included). Read only; no pip, no
# python, no network. A missing folder is "absent" with no packages; a folder that
# cannot be listed is "unreadable" with packages null; a file that cannot be read is
# a package with status "unreadable" and the reason, so one bad file hides no other.
# Only the header block is read (up to the first empty line): the first Name: and
# Version: lines.
PACKAGE_FOLDERS_BODY = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
function Message($err) {
  $ex = $err.Exception
  if ($null -ne $ex.InnerException) { $ex = $ex.InnerException }
  return S $ex.Message
}
function Headers($file) {
  $out = @{ name = $null; version = $null }
  $lines = [System.IO.File]::ReadAllLines($file, [System.Text.Encoding]::UTF8)
  foreach ($line in $lines) {
    $l = [string]$line
    if ($l.Trim() -eq '') { break }
    if ($null -eq $out.name -and $l -cmatch '^Name:\s*(.*?)\s*$') { $out.name = $Matches[1] }
    elseif ($null -eq $out.version -and $l -cmatch '^Version:\s*(.*?)\s*$') { $out.version = $Matches[1] }
    if ($null -ne $out.name -and $null -ne $out.version) { break }
  }
  return $out
}
# npm layout: <folder>\*\package.json and <folder>\@<scope>\*\package.json. A folder
# without package.json (.bin) is no package; any other error is an unreadable package.
# A scope folder that cannot be listed is one unreadable row whose entry is the scope
# alone (@scope, no slash); an empty, null or non-object package.json, or one without
# a string version, is an unreadable package.
function NpmPackages($children, $list) {
  foreach ($c in $children) {
    if (-not $c.PSIsContainer) { continue }
    $n = S $c.Name
    $dirs = New-Object System.Collections.Generic.List[object]
    if ($n.StartsWith('@')) {
      try {
        foreach ($d in @(Get-ChildItem -LiteralPath $c.FullName -Force -ErrorAction Stop)) {
          if ($d.PSIsContainer) { $dirs.Add(@(($n + '/' + (S $d.Name)), $d.FullName)) }
        }
      } catch {
        $list.Add([pscustomobject][ordered]@{ entry = $n; name = $null; version = $null
          status = 'unreadable'; reason = Message $_ })
        continue
      }
    } else { $dirs.Add(@($n, $c.FullName)) }
    foreach ($d in $dirs) {
      $p = [ordered]@{ entry = $d[0]; name = $null; version = $null; status = 'unreadable'; reason = $null }
      try {
        $j = [System.IO.File]::ReadAllText([System.IO.Path]::Combine($d[1], 'package.json'), [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($null -eq $j -or -not ($j -is [System.Management.Automation.PSCustomObject])) { throw 'package.json is empty or not a JSON object' }
        if (-not ($j.version -is [string])) { throw 'package.json has no string version' }
        $p.name = S $j.name
        $p.version = S $j.version
        $p.status = 'read'
      } catch {
        $ex = $_.Exception
        if ($null -ne $ex.InnerException) { $ex = $ex.InnerException }
        if ($ex -is [System.IO.FileNotFoundException]) { continue }
        $p.reason = Message $_
      }
      $list.Add([pscustomobject]$p)
    }
  }
}
$rows = New-Object System.Collections.Generic.List[object]
foreach ($f in @($in.folders)) {
  $raw = S $f.path
  $layout = S $f.layout
  if (-not $raw) { continue }
  $expanded = ([System.Environment]::ExpandEnvironmentVariables($raw)).TrimEnd('\')
  $row = [ordered]@{ path = $raw; expanded = $expanded; status = 'unreadable'; reason = $null
    packages = $null }
  try {
    if ($expanded.Contains('%')) { throw 'the folder holds a variable this account does not know' }
    if (-not [System.IO.Path]::IsPathRooted($expanded)) { throw 'the folder is not a full path' }
    $item = $null
    try {
      $item = Get-Item -LiteralPath $expanded -Force -ErrorAction Stop
    } catch [System.Management.Automation.ItemNotFoundException] {
      $item = $null
    }
    if ($null -eq $item) {
      $row.status = 'absent'
      $row.packages = @()
    } else {
      if (-not $item.PSIsContainer) { throw 'the path is a file, not a folder' }
      $children = @(Get-ChildItem -LiteralPath $expanded -Force -ErrorAction Stop)
      $list = New-Object System.Collections.Generic.List[object]
      if ($layout -eq 'npm') { NpmPackages $children $list } else {
        foreach ($c in $children) {
          $n = S $c.Name
          $lower = $n.ToLowerInvariant()
          $meta = $null
          if ($lower.EndsWith('.dist-info')) {
            if (-not $c.PSIsContainer) { continue }
            $meta = [System.IO.Path]::Combine($c.FullName, 'METADATA')
          } elseif ($lower.EndsWith('.egg-info')) {
            if ($c.PSIsContainer) { $meta = [System.IO.Path]::Combine($c.FullName, 'PKG-INFO') }
            else { $meta = $c.FullName }
          } else { continue }
          $p = [ordered]@{ entry = $n; name = $null; version = $null; status = 'unreadable'; reason = $null }
          try {
            $h = Headers $meta
            $p.name = $h.name
            $p.version = $h.version
            $p.status = 'read'
          } catch {
            $p.status = 'unreadable'
            $p.reason = Message $_
          }
          $list.Add([pscustomobject]$p)
        }
      }
      $row.status = 'read'
      $row.packages = $list.ToArray()
    }
  } catch {
    $row.status = 'unreadable'
    $row.packages = $null
    $row.reason = Message $_
  }
  $rows.Add([pscustomobject]$row)
}
$result = $rows.ToArray()
"""

# The user's npm configuration %USERPROFILE%\.npmrc, read whole (Python takes the
# prefix line). A missing file is "absent"; any other error "unreadable" with the
# reason. Read only; npm does not run.
NPMRC_BODY = r"""$row = [ordered]@{ status = 'unreadable'; lines = $null; reason = $null }
try {
  $profileDir = $env:USERPROFILE
  if (-not $profileDir) { throw 'USERPROFILE is not set' }
  $path = [System.IO.Path]::Combine($profileDir, '.npmrc')
  $item = $null
  try {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
  } catch [System.Management.Automation.ItemNotFoundException] {
    $item = $null
  }
  if ($null -eq $item) {
    $row.status = 'absent'
  } elseif ($item.PSIsContainer) {
    throw '.npmrc is a folder, not a file'
  } else {
    $row.lines = [string[]][System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
    $row.status = 'read'
  }
} catch {
  $ex = $_.Exception
  if ($null -ne $ex.InnerException) { $ex = $ex.InnerException }
  $row.status = 'unreadable'
  $row.lines = $null
  $row.reason = S $ex.Message
}
$result = [pscustomobject]$row
"""



# --- values ----------------------------------------------------------------
def text(value):
    """A non-empty string, or None; other types become their text."""
    if value is None:
        return None
    value = str(value)
    return value if value.strip() else None


def version_key(value):
    """A dotted version as a tuple of numbers; a part that is not a number is -1."""
    value = text(value) or ""
    return tuple(int(p) if p.strip().isascii() and p.strip().isdigit() else -1
                 for p in value.split("."))


def as_list(value) -> list:
    """A JSON value as a list: a single object or string is a one-element list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# --- collection ------------------------------------------------------------
class Collector:
    """Runs the jobs of one collection and keeps the sources and not_checked."""

    def __init__(self, run_ps, work: Path, stamp: str):
        self.run_ps = run_ps
        self.work = work
        self.stamp = stamp
        self.sources = []
        self.not_checked = []
        # set by the collectors: {(source, key)} of the items seen in this run whose
        # row could not be read, for a comparison with another state (compare_view)
        self.unread_keys = set()
        self.unread_pythons = set()  # PEP 514 names whose folders are not known
        self.store_pythons = set()  # PEP 514 names skipped as Store installs, not read
        # set by collect_pip: the summary part managers.pip (without state)
        self.pip_summary = None
        # set by collect_npm: the summary part managers.npm (without state)
        self.npm_summary = None

    def job(self, job: str, body: str, depth: int = 4, file_name: str | None = None) -> dict:
        """Run one job; its output file is named by ``file_name`` (default: ``job``)."""
        out_path = self.work / f"packages-{self.stamp}.{file_name or job}.json"
        script = ps_script(PS_HELPERS + body, out_path, depth)
        return run_job(self.run_ps, job, script, out_path)

    def record(self, name: str, status: str, reason=None, **extra) -> None:
        """One entry of sources; an unreadable source is also an item of not_checked."""
        self.sources.append({"name": name, "status": status, "reason": reason, **extra})
        if status == "unreadable":
            self.skip(name, reason)

    def skip(self, what: str, reason: str) -> None:
        self.not_checked.append({"what": what, "reason": reason})


# pip packages: the Pythons registered under PEP 514 and the packages of their
# site-packages folders, read from dist-info and egg-info (no pip runs).
PIP_FOLDER_KINDS = ("install", "user")
STORE_PYTHON_PART = "\\windowsapps\\"
UNREGISTERED_PYTHONS = ("Python installs not registered in PEP 514 (venvs, portable builds)",
                        "not searched")
PYTHON_VERSION = re.compile(r"\s*(\d+)\.(\d+)")
# The known PythonCore tag forms (sys.winver) whose per-user folder is the tag
# without dots: 3.12, 3.13t, 3.12-32, 3.13t-32.
PYTHON_CORE_TAG = re.compile(r"\d+\.\d+t?(-32)?")
# A wheel or egg metadata folder: <name>-<version>[...].dist-info / .egg-info.
METADATA_SUFFIX = re.compile(r"\.(dist|egg)-info$", re.IGNORECASE)


def python_registrations(col: Collector) -> tuple[str, str | None, list]:
    """``(status, reason, pythons)`` of the PEP 514 registrations.

    ``pythons`` are ``{python, install_path, sys_version, sys_architecture}``, one per
    install path (case-folded, without a trailing backslash), first row first. A
    Microsoft Store Python (an install path under WindowsApps) is named in not_checked
    and left out, its name added to ``col.store_pythons`` unless another registration
    of it is read; so is a registration without a company or a tag, and one whose
    ``<company>/<tag>`` an earlier Python already has. A ``<company>/<tag>`` that only
    registrations without an install path have is named in not_checked and added to
    ``col.unread_pythons``; status ``unreadable`` when no Python is read and a Store
    name or such a name is left.
    """
    result = col.job("python_registrations", PYTHON_REGISTRATIONS_BODY)
    if result["status"] == "unreadable":
        return "unreadable", result["reason"], []
    pythons, paths, names, no_path, store = [], set(), set(), set(), set()
    for row in result["rows"]:
        if not isinstance(row, dict):
            continue
        company, tag = text(row.get("company")), text(row.get("tag"))
        install = text(row.get("install_path"))
        if company is None or tag is None:
            col.skip("pip_packages registration",
                     "a PEP 514 registration has no company or tag, so its packages are "
                     "not read")
            continue
        python = f"{company}/{tag}"
        if install is None:
            no_path.add(python)
            continue
        folded = install.strip().rstrip("\\/").casefold()
        if folded in paths:
            continue
        paths.add(folded)
        if STORE_PYTHON_PART in folded + "\\":
            col.skip(f"pip_packages {python} from the Microsoft Store (WindowsApps)",
                     "the Store's WindowsApps folder is not read, so its packages are "
                     "not read; those of the previous run are kept")
            store.add(python)
            continue
        if python in names:
            col.skip(f"pip_packages {python}",
                     "another registration with the same company and tag has a different "
                     "install path; only the first one is read")
            continue
        names.add(python)
        pythons.append({"python": python, "company": company, "tag": tag,
                        "install_path": install.strip().rstrip("\\/"),
                        "sys_version": text(row.get("sys_version")),
                        "sys_architecture": text(row.get("sys_architecture"))})
    # A name also read through another registration is read, not carried.
    col.store_pythons |= store - names
    for python in sorted(no_path - names):
        col.skip(f"pip_packages {python}",
                 "the PEP 514 registration has no InstallPath, so its packages are "
                 "not read")
        col.unread_pythons.add(python)
    if not pythons and (col.unread_pythons or col.store_pythons):
        return "unreadable", ("no Python was read: each Python not skipped is a Store "
                              "install (WindowsApps) or has a PEP 514 registration "
                              "without an InstallPath"), []
    return ("read" if pythons else "empty"), None, pythons


def user_site_packages(python: dict) -> tuple[str | None, str | None]:
    """``(raw per-user site-packages path, None)``, or ``(None, reason)`` when the
    registration does not tell the folder.

    For company ``PythonCore`` the tag is ``sys.winver``; for its known forms
    (``PYTHON_CORE_TAG``) the folder suffix is the tag without dots, and any other
    tag gives no folder (``3.13t`` -> ``313t``, ``3.12-32`` -> ``312-32``), plus ``-32``
    when ``SysArchitecture`` is ``32bit`` and the tag does not already end in it. A
    missing ``SysArchitecture`` then counts as not 32-bit: a 32-bit PythonCore 3.5 or
    later carries ``-32`` in its tag, and Pythons before 3.5 wrote no SysArchitecture
    and had no ``-32`` folder. For other companies the suffix comes from
    ``SysVersion`` (``<major>.<minor>``) and ``SysArchitecture``; both are needed.
    """
    architecture = (python["sys_architecture"] or "").strip().casefold()
    if python.get("company") == "PythonCore":
        tag = (python.get("tag") or "").strip()
        if PYTHON_CORE_TAG.fullmatch(tag) is None:
            return None, (f"the PythonCore tag {tag!r} is not a known sys.winver form "
                          "(<major>.<minor>[t][-32]), so the user folder name cannot be "
                          "derived from the registration")
        suffix = tag.replace(".", "")
        if architecture == "32bit" and not suffix.casefold().endswith("-32"):
            suffix += "-32"
        return f"%APPDATA%\\Python\\Python{suffix}\\site-packages", None
    match = PYTHON_VERSION.match(python["sys_version"] or "")
    if match is None or python["sys_architecture"] is None:
        return None, ("SysVersion or SysArchitecture is not registered (or SysVersion is "
                      "not <major>.<minor>), so the per-user folder is not known")
    suffix = "-32" if architecture == "32bit" else ""
    xy = f"{match.group(1)}{match.group(2)}"
    return f"%APPDATA%\\Python\\Python{xy}{suffix}\\site-packages", None


def entry_version(entry: str) -> str:
    """The version part of a ``<name>-<version>.dist-info`` / ``.egg-info`` folder name
    (after the first ``-``), or "" when it has none."""
    parts = METADATA_SUFFIX.sub("", entry.strip()).split("-", 1)
    return parts[1] if len(parts) == 2 else ""


def pip_key_name(name: str) -> str:
    """The PEP 503 normalised project name."""
    return re.sub(r"[-_.]+", "-", name.strip()).casefold()


def read_package_folders(col: Collector, paths: list, layout: str = "python") -> dict:
    """Run ``package_folders`` for the raw ``paths`` of one ``layout``: ``{path
    case-folded: {status, reason, packages}}``; a job that failed (or whose input could
    not be written), or a path without a row, is ``unreadable`` with the reason. Each
    layout has its own input and output file."""
    file_name = "package_folders" if layout == "python" else f"package_folders-{layout}"
    input_path = col.work / f"packages-{col.stamp}.{file_name}.input.json"
    folders = [{"path": path, "layout": layout} for path in paths]
    try:
        input_path.write_text(json.dumps({"folders": folders}, ensure_ascii=True),
                              encoding="utf-8")
    except OSError as exc:
        result = {"status": "unreadable", "rows": [],
                  "reason": f"the folder list could not be written: "
                            f"{type(exc).__name__}: {exc}"}
    else:
        body = PACKAGE_FOLDERS_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
        result = col.job("package_folders", body, depth=5, file_name=file_name)
    rows = {}
    for row in result["rows"]:
        if isinstance(row, dict) and text(row.get("path")) is not None:
            rows.setdefault(row["path"].casefold(), row)
    answers = {}
    for path in paths:
        row = rows.get(path.casefold())
        answer = {"status": "unreadable", "reason": None, "packages": None}
        if row is None:
            answer["reason"] = (result["reason"] if result["status"] == "unreadable"
                                else "the package_folders job gave no row for this folder")
        elif row.get("status") == "absent":
            answer.update(status="absent", packages=[])
        elif row.get("status") == "read" and isinstance(row.get("packages"), (list, dict)):
            answer.update(status="read", packages=as_list(row["packages"]))
        elif row.get("status") == "read":
            answer["reason"] = "the package_folders row says read but gives no package list"
        else:
            answer["reason"] = (text(row.get("reason"))
                                or "the package_folders job gave no reason")
        answers[path.casefold()] = answer
    return answers


def pip_item(python: str, kind: str, package) -> tuple[str, dict, str]:
    """``(key without a duplicate suffix, item, entry case-folded)`` of one package row."""
    package = package if isinstance(package, dict) else {}
    entry, name = text(package.get("entry")), text(package.get("name"))
    status, reason = package.get("status"), text(package.get("reason"))
    if status == "read" and name is None:
        status, reason = "unreadable", "the metadata file gives no Name header"
    elif status not in ("read", "unreadable"):
        status = "unreadable"
        reason = reason or "the package_folders job did not say whether the file was read"
    elif status == "unreadable" and reason is None:
        reason = "the package_folders job gave no reason"
    if status == "read":
        label = pip_key_name(name)
    else:
        # Wheel and egg folder names escape "-" in the name as "_", so the first "-"
        # starts the version.
        label = pip_key_name(METADATA_SUFFIX.sub("", (entry or "").strip()).split("-", 1)[0])
    label = label or "?"
    item = {"python": python, "folder": kind, "name": name,
            "version": text(package.get("version")) if status == "read" else None,
            "status": status, "reason": reason if status == "unreadable" else None}
    if status == "unreadable":
        item["entry"] = entry
        item["unread_fields"] = ["version"]
    return f"pip:{python}|{kind}|{label}", item, (entry or "?").strip().casefold()


def carry_pip(col: Collector, previous: dict, prefix: str, items: dict) -> None:
    """Keep the previous baseline's pip items whose key starts with ``prefix`` (a
    Python or one of its folders not read in this run), marked ``from_baseline``."""
    for key, item in (previous or {}).items():
        if key.startswith(prefix) and isinstance(item, dict):
            items[key] = copy.deepcopy(item)
            items[key]["from_baseline"] = True  # not read in this run
            col.unread_keys.add(("pip_packages", key))


def collect_pip(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``pip_packages``; the summary part
    ``{status, pythons}`` is kept in ``col.pip_summary``.

    Status ``read`` with at least one Python whose folders were looked at, ``empty``
    with none (no registration, or each one skipped without a company or tag and
    named in not_checked), ``unreadable`` when the registrations could not be read
    or every Python not skipped is from the Microsoft Store or has no InstallPath.
    A Python without an InstallPath or from the Store (and not read through another registration of
    the same name) keeps its items from the previous baseline, also when the status
    is ``unreadable``. A folder that could not be read (or was skipped) keeps its
    items from the previous baseline, marked ``from_baseline``, so they are not reported as
    removed; that Python's ``count`` is then null (unreadable) and the folder is named
    in not_checked.
    """
    col.skip(*UNREGISTERED_PYTHONS)
    status, reason, pythons = python_registrations(col)
    col.record("pip_packages", status, reason)
    items = {}
    # Registered, but its folders are unknown or not read (a Store install).
    for name in sorted(col.unread_pythons | col.store_pythons):
        carry_pip(col, previous, f"pip:{name}|", items)
    if status != "read":
        col.pip_summary = {"status": status,
                           "pythons": [] if status == "empty" else None}
        return status, items
    folders = []  # (python, kind, raw path or None, reason when None)
    for python in pythons:
        folders.append((python, "install", python["install_path"] + "\\Lib\\site-packages",
                        None))
        folders.append((python, "user", *user_site_packages(python)))
    answers = read_package_folders(
        col, list(dict.fromkeys(path for _, _, path, _ in folders if path is not None)))
    entries = {}
    for python, kind, path, why in folders:
        name = python["python"]
        entry = entries.setdefault(name, {"python": name, "count": 0, "unreadable": 0,
                                          "folders": {}})
        if path is None:
            answer = {"status": "skipped", "packages": None, "reason": why}
        else:
            answer = answers[path.casefold()]
        entry["folders"][kind] = answer["status"]
        if answer["packages"] is None:
            col.skip(f"pip_packages {name} {kind}", answer["reason"])
            if answer["status"] == "unreadable":
                entry["count"] = None
            carry_pip(col, previous, f"pip:{name}|{kind}|", items)
            continue
        # Entries of one name in one folder (a stale dist-info next to the current
        # one): the plain key goes to the entry with the highest version, so it does
        # not depend on the listing order or on which METADATA could be read; the
        # others keep "|<entry>". The version is the Version header when read, else
        # (or when the header is missing) the one in the folder name.
        rows = sorted((pip_item(name, kind, package) for package in answer["packages"]),
                      key=lambda row: (version_key(row[1]["version"]
                                                   or entry_version(row[2])), row[2]),
                      reverse=True)
        for key, item, entry_name in rows:
            if key in items:  # a second entry of the same name
                key = f"{key}|{entry_name}"
            items[key] = item
            if item["status"] == "read":
                if entry["count"] is not None:
                    entry["count"] += 1
            else:
                entry["unreadable"] += 1
    col.pip_summary = {"status": status, "pythons": list(entries.values())}
    return status, items


# npm global packages: the node_modules folder of the global prefix, read from each
# package.json (npm does not run).
NPM_DEFAULT_PREFIX = "%APPDATA%\\npm"
NPMRC_PREFIX = re.compile(r"\s*prefix\s*=\s*(.*?)\s*$")
# Named when npm is empty (the global node_modules folder is absent or holds no
# package): npm may keep its global packages under another prefix, not searched.
NPM_OTHER_PREFIXES = ("npm global packages under another prefix",
                      ("the global node_modules folder of the prefix read is absent or holds "
                       "no package; the prefixes from the global or builtin npmrc and the "
                       "folder of node.exe (nvm-windows, zip builds) were not searched"))
NPM_PREFIX_VARIABLE = "NPM_CONFIG_PREFIX"
# The environment NPM_CONFIG_PREFIX is read from; tests replace it with an invented one.
ENVIRON = os.environ


def environment_value(name: str) -> str | None:
    """The value of the variable ``name`` in ``ENVIRON`` (name matched without regard
    to case), or None when it is unset or blank."""
    for key, value in ENVIRON.items():
        if isinstance(key, str) and key.casefold() == name.casefold():
            return value.strip() if isinstance(value, str) and value.strip() else None
    return None


def npm_prefix(col: Collector) -> tuple[str | None, str | None, str | None]:
    """``(raw prefix, prefix_from, None)``, or ``(None, None, reason)`` when ``.npmrc``
    could not be read.

    A non-blank ``NPM_CONFIG_PREFIX`` gives the prefix (``NPM_CONFIG_PREFIX``) and
    ``.npmrc`` is not read. Else the first ``prefix=`` line of ``%USERPROFILE%\\.npmrc``
    (spaces around ``=`` allowed, a value in quotes unquoted) gives it (``npmrc``);
    with no such line, or no file, it is ``%APPDATA%\\npm`` (``default``). The prefix
    stays raw: ``%VAR%`` is expanded by the ``package_folders`` job.
    """
    value = environment_value(NPM_PREFIX_VARIABLE)
    if value is not None:
        return value.rstrip("\\/"), NPM_PREFIX_VARIABLE, None
    result = col.job("npmrc", NPMRC_BODY)
    rows = result["rows"]
    if result["status"] == "unreadable":
        return None, None, f"the npmrc job failed: {result['reason']}"
    if len(rows) != 1 or not isinstance(rows[0], dict) \
            or rows[0].get("status") not in ("read", "absent", "unreadable"):
        return None, None, "the npmrc job gave no answer, so the npm prefix is not known"
    row = rows[0]
    if row["status"] == "unreadable":
        return None, None, (f"%USERPROFILE%\\.npmrc could not be read, so the npm prefix "
                            f"is not known: {text(row.get('reason')) or 'no reason given'}")
    if row["status"] == "read":
        for line in as_list(row.get("lines")):
            match = NPMRC_PREFIX.match(line) if isinstance(line, str) else None
            if match is None:
                continue
            value = match.group(1)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1].strip()
            if value:
                return value.rstrip("\\/"), "npmrc", None
    return NPM_DEFAULT_PREFIX, "default", None


def npm_item(folder: str, package) -> tuple[str, dict]:
    """``(key, item)`` of one ``package_folders`` row of the npm layout.

    The key is the install name (the ``node_modules`` entry, ``@scope/name`` for a
    scoped package), case-folded: it is the package name, also when ``package.json``
    could not be read.
    """
    package = package if isinstance(package, dict) else {}
    entry, name = text(package.get("entry")), text(package.get("name"))
    status, reason = package.get("status"), text(package.get("reason"))
    if status not in ("read", "unreadable"):
        status = "unreadable"
        reason = reason or "the package_folders job did not say whether the file was read"
    elif status == "unreadable" and reason is None:
        reason = "the package_folders job gave no reason"
    if status == "read" and text(package.get("version")) is None:
        status, reason = "unreadable", "package.json gives no version"
    label = (entry or name or "?").strip().casefold()
    item = {"name": (name or entry) if status == "read" else entry,
            "version": text(package.get("version")) if status == "read" else None,
            "status": status, "reason": reason if status == "unreadable" else None,
            "folder": folder + "\\" + (entry or "?").replace("/", "\\")}
    if status == "unreadable":
        item["unread_fields"] = ["version"]
    return f"npm:{label}", item


def collect_npm(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``npm_packages``; the summary part
    ``{status, prefix_from, count, unreadable}`` is kept in ``col.npm_summary``.

    Status ``read`` with at least one package, ``empty`` when ``node_modules`` is
    missing ("npm not present") or holds no package, ``unreadable`` (count null, named
    in not_checked) when ``.npmrc`` or the folder could not be read; then the items of
    the previous baseline are kept, marked ``from_baseline``. ``unreadable`` (the
    package count) is null with status ``unreadable``. When npm is ``empty``, names the
    prefixes not searched in not_checked.
    """
    prefix, prefix_from, reason = npm_prefix(col)
    answer = None
    if prefix is not None:
        folder = prefix + "\\node_modules"
        answer = read_package_folders(col, [folder], layout="npm")[folder.casefold()]
        if answer["packages"] is None:
            reason = (f"the global node_modules folder {folder} could not be listed: "
                      f"{answer['reason']}")
    if answer is None or answer["packages"] is None:
        col.record("npm_packages", "unreadable", reason)
        items = {}
        for key, item in (previous or {}).items():
            if isinstance(item, dict):
                items[key] = copy.deepcopy(item)
                items[key]["from_baseline"] = True  # not read in this run
                col.unread_keys.add(("npm_packages", key))
        col.npm_summary = {"status": "unreadable", "prefix_from": prefix_from,
                           "count": None, "unreadable": None}
        return "unreadable", items
    items, count, unreadable = {}, 0, 0
    packages, scopes = [], 0
    for package in answer["packages"]:
        scope = text(package.get("entry")) if isinstance(package, dict) else None
        if scope is None or not scope.startswith("@") or "/" in scope:
            packages.append(package)
            continue
        # A scope folder that could not be listed: its packages keep the previous
        # baseline's items, so they are not reported as removed, and the count is null.
        scopes += 1
        col.skip(f"npm_packages {folder}\\{scope}",
                 text(package.get("reason")) or "the scope folder could not be listed")
        prefix = f"npm:{scope.casefold()}/"
        for key, item in (previous or {}).items():
            if key.startswith(prefix) and isinstance(item, dict):
                items[key] = copy.deepcopy(item)
                items[key]["from_baseline"] = True  # not read in this run
                col.unread_keys.add(("npm_packages", key))
    rows = sorted((npm_item(folder, package) for package in packages),
                  key=lambda row: (row[0], row[1]["folder"].casefold()))
    for key, item in rows:
        if key in items:  # a second entry of the same name (not written by npm)
            key = f"{key}|{item['folder'].casefold()}"
        items[key] = item
        if item["status"] == "read":
            count += 1
        else:
            unreadable += 1
    reason = None
    if packages:
        status = "read"
    elif scopes:
        status, reason = "unreadable", "no scope folder of node_modules could be listed"
    else:
        status = "empty"
        col.skip(*NPM_OTHER_PREFIXES)
    col.record("npm_packages", status, reason)
    col.npm_summary = {"status": status, "prefix_from": prefix_from,
                       "count": None if scopes else count,
                       "unreadable": None if status == "unreadable" else unreadable}
    return status, items


# --- managers ----------------------------------------------------------------
def load_managers(path: Path) -> tuple[list | None, str | None]:
    """``(entries, None)`` of ``data/managers.json`` (``{name, step, read}`` each, in
    order), or ``(None, reason)`` when the file cannot be read or has another shape."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{Path(path).name} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(data, list):
        return None, f"{Path(path).name} does not hold a list"
    names = set()
    for entry in data:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name.strip() or name.casefold() in names:
            return None, f"{Path(path).name} has an entry without a unique name: {entry!r}"
        names.add(name.casefold())
    return data, None


def manager_state(status: str | None) -> str:
    """``read`` for a source read (with or without packages), else ``unreadable``."""
    return "read" if status in READ_STATUSES else "unreadable"


def build_managers(col: Collector) -> dict:
    """``{name: entry}`` in the order of ``data/managers.json``: pip and npm with
    their state and summary part, every other manager ``{state: "not_read"}`` with one
    not_checked entry ``<name>: not read yet``. Without a readable file, pip and npm
    only, and the file is named in not_checked."""
    read_parts = {"pip": col.pip_summary, "npm": col.npm_summary}
    entries, reason = load_managers(MANAGERS_FILE)
    if entries is None:
        col.skip(MANAGERS_FILE.name, f"the managers not read by this skill are not "
                                     f"listed: {reason}")
        entries = [{"name": name} for name in READ_MANAGERS]
    managers = {}
    for entry in entries:
        name = entry["name"]
        part = read_parts.get(name)
        if part is None:
            managers[name] = {"state": "not_read"}
            col.skip(name, NOT_READ_YET)
        else:
            managers[name] = {"state": manager_state(part["status"]), **part}
    return managers


def collect(run_ps, work: Path, stamp: str, previous: dict):
    """``(statuses, current, col)``: the status and ``{key: item}`` of each source."""
    col = Collector(run_ps, work, stamp)
    statuses, current = {}, {}
    statuses["pip_packages"], current["pip_packages"] = collect_pip(
        col, previous.get("pip_packages") or {})
    statuses["npm_packages"], current["npm_packages"] = collect_npm(
        col, previous.get("npm_packages") or {})
    return statuses, current, col


# --- comparison ----------------------------------------------------------------
def compare_view(current: dict, unread_keys: set = frozenset(),
                 reference: dict | None = None) -> dict:
    """A copy of ``current`` for a comparison with a state other than the latest
    baseline (``--compare-to``): what this run did not read is unread in it.

    An item kept ``from_baseline`` has its compared fields in ``unread_fields``, so it
    can still be added but never changed. An item seen in this run but not read
    (``unread_keys``) that ``current`` lacks is taken from ``reference`` with
    ``from_baseline``: it is still there, so it is not removed.
    """
    view = copy.deepcopy(current)
    for source, key in sorted(unread_keys):
        items = view.get(source)
        before = (reference or {}).get(source) or {}
        if isinstance(items, dict) and key not in items and isinstance(before.get(key), dict):
            items[key] = copy.deepcopy(before[key])
            items[key]["from_baseline"] = True  # not read in this run
    for source in SOURCES:
        for item in (view.get(source) or {}).values():
            if item.get("from_baseline"):
                unread = set(item.get("unread_fields") or []) | set(COMPARED_FIELDS[source])
                item["unread_fields"] = sorted(unread)
    return view


def build_changes(previous: dict, current: dict, comparison: dict, numbering) -> list:
    """Every change of a compared source, pip first, each source added, removed,
    changed and then by key; ids ``c<n>`` from ``numbering`` (by key)."""
    changes = []
    for source in SOURCES:
        if comparison.get(source) != "compared":
            continue
        before_items = previous.get(source) or {}
        after_items = current.get(source) or {}
        diff = baseline.compare(before_items, after_items, COMPARED_FIELDS[source])
        found = [("added", key, None) for key in diff["added"]]
        found += [("removed", key, None) for key in diff["removed"]]
        found += [("changed", key, fields) for key, fields in diff["changed"].items()]
        found.sort(key=lambda f: (CHANGE_ORDER.index(f[0]), f[1]))
        for change, key, fields in found:
            item = after_items.get(key) if change != "removed" else before_items.get(key)
            entry = {"key": key, "source": source, "change": change,
                     "name": item.get("name")}
            if source == "pip_packages":
                entry["python"] = item.get("python")
            if fields is not None:
                entry["fields"] = fields
            else:
                entry["version"] = item.get("version")
            changes.append(entry)
    numbering.assign("c", changes)
    return [{"id": entry.pop("id"), **entry} for entry in changes]


# --- packages ------------------------------------------------------------------
def build_packages(current: dict, numbering) -> list:
    """Every package of the read managers, pip then npm, each by key; ids ``k<n>``
    from ``numbering``. The full item of the source, with ``manager`` and ``key``."""
    packages = []
    for manager, source in READ_MANAGERS.items():
        for key, item in sorted((current.get(source) or {}).items()):
            packages.append({"manager": manager, "key": key, **copy.deepcopy(item)})
    numbering.assign("k", packages)
    return [{"id": item.pop("id"), **item} for item in packages]


def summary_package(item: dict) -> dict:
    """The summary form of a package: ``id``, ``manager``, ``key``, ``name``,
    ``version``, the Python (pip) and ``folder``; ``unreadable`` and ``reason`` when
    its metadata could not be read, ``from_baseline`` when it was kept from the
    baseline because its folder could not be listed."""
    out = {"id": item["id"], "manager": item["manager"], "key": item["key"],
           "name": item.get("name"), "version": item.get("version")}
    if item["manager"] == "pip":
        out["python"] = item.get("python")
    out["folder"] = item.get("folder")
    if item.get("status") == "unreadable":
        out["unreadable"] = True
        out["reason"] = item.get("reason")
        if item.get("entry") is not None:
            out["entry"] = item["entry"]
    if item.get("from_baseline"):
        out["from_baseline"] = True
    return out


# --- summary budget --------------------------------------------------------------
# The lists cut over the budget, in order, with the key of their cut count.
CUT_LISTS = (("packages", "truncated"), ("changes", "truncated_changes"))


def fit_budget(summary: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    ``packages`` items are cut first, from the end, then ``c`` items; each list keeps
    the most items that fit (all of a list may be cut) and its count key counts the cut
    ones. A summary that is still too long says so in not_checked.
    """
    text_out = dump(summary)
    for name, count_key in CUT_LISTS:
        if len(text_out) <= SUMMARY_MAX_CHARS:
            break
        items = summary[name]

        def fits(kept: int, items=items, name=name, count_key=count_key) -> bool:
            summary[name] = items[:kept]
            summary[count_key] = len(items) - kept
            return len(dump(summary)) <= SUMMARY_MAX_CHARS

        low, high = 0, len(items)  # the most items that fit, by bisection
        while low < high:
            middle = (low + high + 1) // 2
            if fits(middle):
                low = middle
            else:
                high = middle - 1
        fits(low)
        text_out = dump(summary)
    if len(text_out) > SUMMARY_MAX_CHARS:
        summary["not_checked"].append({
            "what": "summary budget",
            "reason": f"the summary exceeds {SUMMARY_MAX_CHARS} characters after every "
                      f"package and change was cut",
        })
        text_out = dump(summary)
    return text_out


# --- machine functions ----------------------------------------------------------
def default_run_ps(job, script, out_path):
    return psrun.default_run_ps(job, script, out_path)


def default_is_admin() -> bool:
    try:
        import ctypes  # Windows-only, and only for a real run

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


# --- command line --------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    datadir.add_arguments(parser)
    parser.add_argument("--detail", metavar="ID",
                        help="print one item (k.. or c..) of the newest detail file and exit")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    parser.add_argument("--compare-to", metavar="<N>d", help=baseline.COMPARE_TO_HELP)
    return parser


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("packages-*.detail.json"), key=lambda p: p.name)
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
    """Collect, compare and summarise, or print one detail item with --detail.

    ``run_ps`` and ``is_admin`` are the two inputs from the machine. Either both
    are injected (tests) or neither (a real run): injecting only one is a
    TypeError, so a test that forgets a fake fails loudly instead of reading
    the machine.
    """
    if (run_ps is None) != (is_admin is None):
        raise TypeError("inject both run_ps and is_admin, or neither")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.detail_file and args.detail is None:
        parser.error("--detail-file needs --detail")
    compare_days = None
    if args.compare_to is not None:
        compare_days = baseline.parse_compare_to(args.compare_to)
        if compare_days is None:
            parser.error(f"--compare-to takes <N>d with N from 1 to "
                         f"{baseline.HISTORY_DAYS - 1}, e.g. 7d: {args.compare_to!r}")
    if args.detail is not None and args.detail_file:
        # The detail file is named explicitly: no data directory is needed.
        return show_detail(Path(), args.detail, Path(args.detail_file).absolute())
    try:
        data_dir = datadir.resolve(args.data_dir, default=args.default_data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    work = data_dir / "work"
    state = data_dir / "state"
    if args.detail is not None:
        return show_detail(work, args.detail)

    run_ps = run_ps or default_run_ps
    is_admin = is_admin or default_is_admin
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    work.mkdir(parents=True, exist_ok=True)
    summary_file = work / f"packages-{stamp}.summary.json"
    detail_file = work / f"packages-{stamp}.detail.json"

    admin = bool(is_admin())
    loaded = baseline.load(state, SKILL, admin)
    previous = loaded["sources"] if loaded["status"] == "read" else {}
    # The state compared with: the latest baseline, or a history copy with --compare-to.
    # ``previous`` stays the base of collect and merge_sources.
    reference = baseline.reference_for(state, SKILL, admin, loaded, args.compare_to,
                                       compare_days, now)
    reference_sources = reference["sources"]

    statuses, current, col = collect(run_ps, work, stamp, previous)
    managers = build_managers(col)
    id_map, map_reason = ids.load_map(state, SKILL)
    if map_reason is not None:
        col.skip(*ids.load_note(map_reason))
    numbering = ids.Numbering(id_map, now.date().isoformat())

    comparison = {name: baseline.comparison_state(reference_sources, name, statuses[name])
                  for name in SOURCES}
    # Values taken from the latest baseline are no change against it, but would be
    # against a history copy: with --compare-to they are not compared.
    compared = (current if args.compare_to is None
                else compare_view(current, col.unread_keys, reference_sources))
    changes = build_changes(reference_sources, compared, comparison, numbering)
    packages = build_packages(current, numbering)

    detail = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "sources": col.sources,
        "comparison": comparison,
        "packages": packages,
        "changes": changes,
        "pip_packages": [{"key": key, **item}
                         for key, item in sorted(current["pip_packages"].items())],
        "npm_packages": [{"key": key, **item}
                         for key, item in sorted(current["npm_packages"].items())],
        "summary_file": str(summary_file),
    }
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    new_baseline = {
        "schema_version": baseline.SCHEMA_VERSION,
        "skill": SKILL,
        "created_at": now.isoformat(),
        "elevated": admin,
        "sources": baseline.merge_sources(previous, current, statuses),
    }
    state_name = baseline.baseline_name(SKILL, admin)
    save_reason = baseline.save(state, state_name, new_baseline)
    history_reason = baseline.archive(state, state_name, now)
    if history_reason is not None:
        col.skip("baseline history", baseline.history_note(history_reason))
    map_save_reason = ids.save_map(state, SKILL, id_map, now.date().isoformat())
    if map_save_reason is not None:
        col.skip(*ids.save_note(map_save_reason))
    for what, reason in numbering.repeated_notes():
        col.skip(what, reason)

    for what, reason in reference["notes"]:
        col.skip(what, reason)
    reasons = list(reference["info"]["reason"])
    if save_reason is not None:
        reasons.append(f"not saved: {save_reason}")
        col.skip("baseline save", f"this run's baseline was not saved: {save_reason}")
    info = reference["info"]
    baseline_info = {
        "status": info["status"],
        "created_at": info["created_at"],
        "age_days": info["age_days"],
        "saved": save_reason is None,
        "reason": "; ".join(reasons) if reasons else None,
        "reference": info["reference"],
        "reference_file": info["reference_file"],
    }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "sources": col.sources,
        "baseline": baseline_info,
        "comparison": comparison,
        "managers": managers,
        "counts": {
            "packages": len(packages),
            "changes": len(changes),
            **{kind: sum(1 for c in changes if c["change"] == kind) for kind in CHANGE_ORDER},
        },
        "truncated": 0,
        "truncated_changes": 0,
        "not_checked": col.not_checked,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "changes": changes,
        "packages": [summary_package(item) for item in packages],
    }
    text_out = fit_budget(summary)
    summary_file.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

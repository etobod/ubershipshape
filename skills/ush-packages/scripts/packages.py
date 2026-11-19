"""Read the installed packages of the package managers offline from disk (read-only).

Plan 061 moved the pip and npm reading of ush-inventory here, with the same
PowerShell bodies, keys, item fields, ``from_baseline`` carrying and not_checked
entries. No package manager runs: pip, npm, winget, VS Code, dotnet, nuget, choco,
scoop, vcpkg and the PowerShell module commands are never started.
Plan 073 added a Python read path beside the jobs: ``DISK`` reads files directly,
at locations expanded from ``ENVIRON`` (an unset ``%VAR%`` counts as absent).

Sources (read-only PowerShell jobs, run through an injectable ``run_ps``; see
``skills/ush-common/scripts/psrun.py``):

- ``pip_packages``: the Pythons registered under PEP 514 (job
  ``python_registrations``) and the ``dist-info`` / ``egg-info`` metadata of their
  install and per-user ``site-packages`` folders (job ``package_folders``). Key
  ``pip:<company>/<tag>|<install|user>|<PEP 503 name>``.
- ``npm_packages``: the ``package.json`` of each package in the global
  ``node_modules`` folder (job ``package_folders``, layout ``npm``); the prefix comes
  from ``NPM_CONFIG_PREFIX``, else the ``prefix=`` line of ``%USERPROFILE%\\.npmrc``
  (job ``npmrc``), else ``%APPDATA%\\npm``; no ``node_modules`` folder there is npm
  ``not_present``. Key ``npm:<install name>``.
- ``pipx_packages``: the ``venvs\\<venv>\\pipx_metadata.json`` of each pipx home
  (``PIPX_HOME``, else the homes of pipx 1.5+, before 1.3 and 1.3-1.4; job
  ``pipx_homes``): the main package and each injected one. Keys ``pipx:<venv>`` and
  ``pipx:<venv>|<injected>``; a venv name of an earlier home gives ``~2``, ``~3``.
- ``uv_tools``: each subfolder with ``uv-receipt.toml`` of the uv tool folder
  (``UV_TOOL_DIR``, else ``%APPDATA%\\uv\\data\\tools``; job ``uv_tools``), its version
  from the ``dist-info`` of its ``Lib\\site-packages`` (job ``package_folders``). Key
  ``uv:<tool>``.
- ``conda_packages``: each prefix listed in ``%USERPROFILE%\\.conda\\environments.txt``
  and the ``*.json`` file names of its ``conda-meta`` folder, split into
  ``<name>-<version>-<build>`` (job ``conda_environments``; file contents are not
  read). Key ``conda:<environment label>|<name>``; the label is the prefix's last folder
  name, with ``~2``, ``~3`` for later prefixes of the same label.
- ``winget_packages``: the tracking catalogs of winget, each subfolder of
  ``%LOCALAPPDATA%\\Packages\\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\\LocalState``
  holding ``installed.db`` (SQLite schema 1, opened read-only and immutable through
  ``DISK``, no job): per id the highest version recorded. Key
  ``winget:<catalog label>|<id>``; the label is the subfolder name.
- ``vscode_extensions``: the ``extensions.json`` of the VS Code extensions folder
  (``VSCODE_EXTENSIONS``, else ``%USERPROFILE%\\.vscode\\extensions``; read through
  ``DISK``, no job). Key ``vscode:<extension id>``.
- ``dotnet_tools``: the .NET global tool store ``<tools>\\.store\\<id>\\<version>``
  (``<tools>`` is ``DOTNET_CLI_HOME``, else ``%USERPROFILE%``, + ``\\.dotnet\\tools``;
  through ``DISK``, no job): per id the highest version. Key ``dotnet-tools:<id>``.
- ``nuget_packages``: the NuGet global packages folder ``<id>\\<version>``
  (``NUGET_PACKAGES``, else ``%USERPROFILE%\\.nuget\\packages``; through ``DISK``, no
  job): per id the highest version whose folder holds ``.nupkg.metadata``. Key
  ``nuget:<id>``.
- ``psgallery_modules``: the ``PSGetModuleInfo.xml`` of each module version folder of
  the four standard module folders (``<Documents>`` and ``%ProgramFiles%``, each with
  ``WindowsPowerShell\\Modules`` and ``PowerShell\\Modules``; ``<Documents>`` from the
  user's shell folders, read-only, else ``%USERPROFILE%\\Documents``; through ``DISK``,
  no job): per module folder the highest parsed version. Key
  ``psgallery:<folder label>|<module folder name>``.
- ``choco_packages``: the ``<folder>.nuspec`` (``id``, ``version``) of each package
  folder of ``<root>\\lib`` (``ChocolateyInstall``, else ``%ProgramData%\\chocolatey``;
  through ``DISK``, no job). Key ``choco:<lib folder name>``.
- ``scoop_apps``: the ``current\\manifest.json`` (``version``) and
  ``current\\install.json`` (``bucket``) of each app folder of ``<root>\\apps`` for the
  ``user`` root (``SCOOP``, else ``%USERPROFILE%\\scoop``) and the ``global`` root
  (``SCOOP_GLOBAL``, else ``%ProgramData%\\scoop``; through ``DISK``, no job). Key
  ``scoop:<root label>|<app folder name>``.
- ``vcpkg_packages``: the status database ``<root>\\installed\\vcpkg\\status`` with the
  all-digit files of ``installed\\vcpkg\\updates`` applied after it in numeric order
  (``<root>`` is ``VCPKG_ROOT``, else the first line of
  ``%LOCALAPPDATA%\\vcpkg\\vcpkg.path.txt``; through ``DISK``, no job): the installed
  paragraphs without ``Feature``. Key ``vcpkg:<Package>:<Architecture>``.

Each is compared with the baseline ``ush-packages`` on ``version``; the changes
are ``c`` items. The summary lists every manager of ``data/managers.json`` under
``managers`` in the file's order: the read ones with their state (``not_present``
when none of their locations exists), every other one ``not_read`` and named in
not_checked as "not read yet" (never "not present").
Every package of a read manager is a ``k`` item of the flat ``packages`` list.
No package is checked for a newer version here: packages are checked for updates
only in an ush-advice run with findings.

The summary keeps within ``SUMMARY_MAX_CHARS``: over it, ``packages`` items are
cut first, then ``c`` items; the detail file keeps them all (``--detail <id>``).
"""

import argparse
import copy
import functools
import json
import ntpath
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import tomllib

# The shared modules live in skills/ush-common/scripts.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline  # called as baseline.save(...), so tests can patch it
import datadir
import ids
import progress
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
READ_MANAGERS = {"pip": "pip_packages", "npm": "npm_packages", "pipx": "pipx_packages",
                 "uv": "uv_tools", "conda": "conda_packages", "winget": "winget_packages",
                 "vscode": "vscode_extensions", "dotnet-tools": "dotnet_tools",
                 "nuget": "nuget_packages", "psgallery": "psgallery_modules",
                 "choco": "choco_packages", "scoop": "scoop_apps",
                 "vcpkg": "vcpkg_packages", "pnpm": "pnpm_packages",
                 "yarn": "yarn_packages",
                 "bun": "bun_packages", "cargo": "cargo_packages",
                 "gem": "gem_packages", "composer": "composer_packages"}
NOT_READ_YET = "not read yet"

# The sources with items, compared with the baseline, in change order.
SOURCES = ("pip_packages", "npm_packages", "pipx_packages", "uv_tools", "conda_packages",
           "winget_packages", "vscode_extensions", "dotnet_tools", "nuget_packages",
           "psgallery_modules", "choco_packages", "scoop_apps", "vcpkg_packages",
           "pnpm_packages", "yarn_packages", "bun_packages", "cargo_packages",
           "gem_packages", "composer_packages")
READ_STATUSES = ("read", "empty")
COMPARED_FIELDS = {source: ("version",) for source in SOURCES}
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

# Shared by the pipx_homes and uv_tools bodies: the input file, the reason of an
# error, and one location given raw. Location returns the expanded path and the
# folder item, or $null as the item when the path does not exist; it throws when
# the path holds an unknown variable, is not a full path or is a file.
LOCATION_HELPERS = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
function Message($err) {
  $ex = $err.Exception
  if ($null -ne $ex.InnerException) { $ex = $ex.InnerException }
  return S $ex.Message
}
function Folder($path) {
  $item = $null
  try {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
  } catch [System.Management.Automation.ItemNotFoundException] {
    $item = $null
  }
  if ($null -ne $item -and -not $item.PSIsContainer) { throw 'the path is a file, not a folder' }
  return $item
}
function Location($raw) {
  $expanded = ([System.Environment]::ExpandEnvironmentVariables($raw)).TrimEnd('\')
  if ($expanded.Contains('%')) { throw 'the folder holds a variable this account does not know' }
  if (-not [System.IO.Path]::IsPathRooted($expanded)) { throw 'the folder is not a full path' }
  return $expanded
}
"""

# pipx homes: for each home, the text of each venvs\<venv>\pipx_metadata.json
# (Python parses it). Read only; pipx does not run. A missing home is "absent"; an
# existing home without a venvs folder holds no venv; a home or venvs folder that
# cannot be listed is "unreadable" with venvs null; a metadata file that cannot be
# read is a venv with status "unreadable" and the reason.
PIPX_HOMES_BODY = LOCATION_HELPERS + r"""$rows = New-Object System.Collections.Generic.List[object]
foreach ($h in @($in.homes)) {
  $raw = S $h
  if (-not $raw) { continue }
  $row = [ordered]@{ path = $raw; expanded = $null; status = 'unreadable'; reason = $null
    venvs = $null }
  try {
    $row.expanded = Location $raw
    $item = Folder $row.expanded
    if ($null -eq $item) {
      $row.status = 'absent'
    } else {
      $list = New-Object System.Collections.Generic.List[object]
      $venvs = Folder ([System.IO.Path]::Combine($row.expanded, 'venvs'))
      if ($null -ne $venvs) {
        foreach ($c in @(Get-ChildItem -LiteralPath $venvs.FullName -Force -ErrorAction Stop)) {
          if (-not $c.PSIsContainer) { continue }
          $v = [ordered]@{ venv = S $c.Name; status = 'unreadable'; reason = $null; metadata = $null }
          try {
            $v.metadata = [System.IO.File]::ReadAllText([System.IO.Path]::Combine($c.FullName, 'pipx_metadata.json'), [System.Text.Encoding]::UTF8)
            $v.status = 'read'
          } catch {
            $v.metadata = $null
            $v.reason = Message $_
          }
          $list.Add([pscustomobject]$v)
        }
      }
      $row.venvs = $list.ToArray()
      $row.status = 'read'
    }
  } catch {
    $row.status = 'unreadable'
    $row.venvs = $null
    $row.reason = Message $_
  }
  $rows.Add([pscustomobject]$row)
}
$result = $rows.ToArray()
"""

# uv tool folders: each subfolder with whether it holds uv-receipt.toml (receipt
# true/false; null with the reason when that could not be checked). Read only; uv
# does not run. A missing folder is "absent"; one that cannot be listed is
# "unreadable" with entries null.
UV_TOOLS_BODY = LOCATION_HELPERS + r"""$rows = New-Object System.Collections.Generic.List[object]
foreach ($f in @($in.folders)) {
  $raw = S $f
  if (-not $raw) { continue }
  $row = [ordered]@{ path = $raw; expanded = $null; status = 'unreadable'; reason = $null
    entries = $null }
  try {
    $row.expanded = Location $raw
    $item = Folder $row.expanded
    if ($null -eq $item) {
      $row.status = 'absent'
    } else {
      $list = New-Object System.Collections.Generic.List[object]
      foreach ($c in @(Get-ChildItem -LiteralPath $row.expanded -Force -ErrorAction Stop)) {
        if (-not $c.PSIsContainer) { continue }
        $e = [ordered]@{ name = S $c.Name; receipt = $null; reason = $null }
        try {
          $r = $null
          try {
            $r = Get-Item -LiteralPath ([System.IO.Path]::Combine($c.FullName, 'uv-receipt.toml')) -Force -ErrorAction Stop
          } catch [System.Management.Automation.ItemNotFoundException] {
            $r = $null
          }
          $e.receipt = ($null -ne $r -and -not $r.PSIsContainer)
        } catch {
          $e.receipt = $null
          $e.reason = Message $_
        }
        $list.Add([pscustomobject]$e)
      }
      $row.entries = $list.ToArray()
      $row.status = 'read'
    }
  } catch {
    $row.status = 'unreadable'
    $row.entries = $null
    $row.reason = Message $_
  }
  $rows.Add([pscustomobject]$row)
}
$result = $rows.ToArray()
"""

# conda: the file environments.txt read whole, and for each non-blank line (a prefix)
# the *.json file names of <prefix>\conda-meta (Python splits them; file contents are
# not read). Read only; conda does not run. A missing file is "absent" with prefixes
# null; a file that cannot be read is "unreadable" with the reason. A prefix whose
# folder is missing is "absent"; an existing prefix without conda-meta is "read" with
# no file; a prefix that is not a full path or whose conda-meta cannot be listed is
# "unreadable" with files null and the reason.
CONDA_ENVIRONMENTS_BODY = LOCATION_HELPERS + r"""$raw = S $in.file
$row = [ordered]@{ path = $raw; expanded = $null; status = 'unreadable'; reason = $null
  prefixes = $null }
try {
  if (-not $raw) { throw 'no environments.txt path was given' }
  $row.expanded = Location $raw
  $item = $null
  try {
    $item = Get-Item -LiteralPath $row.expanded -Force -ErrorAction Stop
  } catch [System.Management.Automation.ItemNotFoundException] {
    $item = $null
  }
  if ($null -eq $item) {
    $row.status = 'absent'
  } else {
    if ($item.PSIsContainer) { throw 'environments.txt is a folder, not a file' }
    # conda writes UTF-8, older versions the ANSI code page: strict UTF-8 first, so a
    # prefix with non-ASCII letters is not garbled into an absent folder.
    $bytes = [System.IO.File]::ReadAllBytes($row.expanded)
    try {
      $all = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($bytes)
    } catch {
      $all = [System.Text.Encoding]::Default.GetString($bytes)
    }
    $lines = $all.TrimStart([char]0xFEFF) -split '\r?\n'
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($line in $lines) {
      $prefix = ([string]$line).Trim()
      if (-not $prefix) { continue }
      $p = [ordered]@{ prefix = $prefix; status = 'unreadable'; reason = $null; files = $null }
      try {
        $path = $prefix.TrimEnd('\')
        if (-not [System.IO.Path]::IsPathRooted($path)) { throw 'the line is not a full path' }
        if ($null -eq (Folder $path)) {
          $p.status = 'absent'
        } else {
          $names = New-Object System.Collections.Generic.List[string]
          $meta = Folder ([System.IO.Path]::Combine($path, 'conda-meta'))
          if ($null -ne $meta) {
            foreach ($c in @(Get-ChildItem -LiteralPath $meta.FullName -Force -ErrorAction Stop)) {
              if ($c.PSIsContainer) { continue }
              $n = S $c.Name
              if ($n.ToLowerInvariant().EndsWith('.json')) { $names.Add($n) }
            }
          }
          $p.files = $names.ToArray()
          $p.status = 'read'
        }
      } catch {
        $p.status = 'unreadable'
        $p.files = $null
        $p.reason = Message $_
      }
      $list.Add([pscustomobject]$p)
    }
    $row.prefixes = $list.ToArray()
    $row.status = 'read'
  }
} catch {
  $row.status = 'unreadable'
  $row.prefixes = $null
  $row.reason = Message $_
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
        # set by collect_pipx / collect_uv: the summary parts managers.pipx / managers.uv
        # (without state)
        self.pipx_summary = None
        self.uv_summary = None
        # set by collect_conda: the summary part managers.conda (without state)
        self.conda_summary = None
        # set by collect_winget: the summary part managers.winget (without state)
        self.winget_summary = None
        # set by collect_vscode: the summary part managers.vscode (without state)
        self.vscode_summary = None
        # set by collect_dotnet_tools / collect_nuget: the summary parts
        # managers.dotnet-tools / managers.nuget (without state)
        self.dotnet_tools_summary = None
        self.nuget_summary = None
        # set by collect_psgallery: the summary part managers.psgallery (without state)
        self.psgallery_summary = None
        # set by collect_choco / collect_scoop / collect_vcpkg: the summary parts
        # managers.choco / managers.scoop / managers.vcpkg (without state)
        self.choco_summary = None
        self.scoop_summary = None
        self.vcpkg_summary = None
        # set by read_pnpm: the summary part managers.pnpm (without state)
        self.pnpm_summary = None
        # set by collect_yarn / collect_bun: the summary parts managers.yarn /
        # managers.bun (without state)
        self.yarn_summary = None
        self.bun_summary = None
        # set by collect_cargo / collect_composer: the summary parts managers.cargo /
        # managers.composer (without state)
        self.cargo_summary = None
        self.composer_summary = None
        # set by read_gem: the summary part managers.gem (without state)
        self.gem_summary = None
        # the managers none of whose disk locations exists (state not_present)
        self.not_present = set()

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


def read_locations(col: Collector, job: str, body: str, file_name: str, input_data: dict,
                   paths: list, list_key: str, list_name: str, depth: int = 4) -> dict:
    """Write ``input_data`` to the job's input file and run ``job`` (``body`` reads it
    through ``__INPUT__``): ``{path case-folded: {status, reason, <list_key>}}`` for each
    raw path. ``absent`` has an empty list; a job that failed (or whose input could not
    be written), or a path without a row, is ``unreadable`` with the reason and the list
    null. The input and output files are named by ``file_name``."""
    input_path = col.work / f"packages-{col.stamp}.{file_name}.input.json"
    try:
        input_path.write_text(json.dumps(input_data, ensure_ascii=True), encoding="utf-8")
    except OSError as exc:
        result = {"status": "unreadable", "rows": [],
                  "reason": f"the folder list could not be written: "
                            f"{type(exc).__name__}: {exc}"}
    else:
        result = col.job(job, body.replace("__INPUT__", psrun.ps_quote(input_path)),
                         depth=depth, file_name=file_name)
    rows = {}
    for row in result["rows"]:
        if isinstance(row, dict) and text(row.get("path")) is not None:
            rows.setdefault(row["path"].casefold(), row)
    answers = {}
    for path in paths:
        row = rows.get(path.casefold())
        answer = {"status": "unreadable", "reason": None, list_key: None}
        if row is None:
            answer["reason"] = (result["reason"] if result["status"] == "unreadable"
                                else f"the {job} job gave no row for this folder")
        elif row.get("status") == "absent":
            answer.update({"status": "absent", list_key: []})
        elif row.get("status") == "read" and isinstance(row.get(list_key), (list, dict)):
            answer.update({"status": "read", list_key: as_list(row[list_key])})
        elif row.get("status") == "read":
            answer["reason"] = f"the {job} row says read but gives no {list_name} list"
        else:
            answer["reason"] = text(row.get("reason")) or f"the {job} job gave no reason"
        answers[path.casefold()] = answer
    return answers


def read_package_folders(col: Collector, paths: list, layout: str = "python",
                         file_name: str | None = None) -> dict:
    """Run ``package_folders`` for the raw ``paths`` of one ``layout``: ``{path
    case-folded: {status, reason, packages}}``; a job that failed (or whose input could
    not be written), or a path without a row, is ``unreadable`` with the reason. Each
    layout has its own input and output file; ``file_name`` names another pair (the uv
    tools' site-packages, so pip's files are not overwritten)."""
    file_name = file_name or ("package_folders" if layout == "python"
                              else f"package_folders-{layout}")
    folders = [{"path": path, "layout": layout} for path in paths]
    return read_locations(col, "package_folders", PACKAGE_FOLDERS_BODY, file_name,
                          {"folders": folders}, paths, "packages", "package", depth=5)


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


def carry(col: Collector, source: str, previous: dict, items: dict, keep) -> None:
    """Keep the previous baseline's items of ``source`` for whose key ``keep`` is true
    (not read in this run), marked ``from_baseline``."""
    for key, item in (previous or {}).items():
        if keep(key) and isinstance(item, dict):
            items[key] = copy.deepcopy(item)
            items[key]["from_baseline"] = True  # not read in this run
            col.unread_keys.add((source, key))


def carry_pip(col: Collector, previous: dict, prefix: str, items: dict) -> None:
    """Keep the previous baseline's pip items whose key starts with ``prefix`` (a
    Python or one of its folders not read in this run), marked ``from_baseline``."""
    carry(col, "pip_packages", previous, items, lambda key: key.startswith(prefix))


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
# Named when npm is not_present (no global node_modules folder) or empty (the folder
# holds no package): npm may keep its global packages under another prefix, not searched.
NPM_OTHER_PREFIXES = ("npm global packages under another prefix",
                      ("the global node_modules folder of the prefix read is absent or holds "
                       "no package; the prefixes from the global or builtin npmrc and the "
                       "folder of node.exe (nvm-windows, zip builds) were not searched"))
NPM_PREFIX_VARIABLE = "NPM_CONFIG_PREFIX"
# The environment NPM_CONFIG_PREFIX is read from and the locations of the Python read
# path are expanded from; tests replace it with an invented one.
ENVIRON = os.environ
ENVIRONMENT_REFERENCE = re.compile(r"%([^%]+)%")
# The user's Documents folder: a value of the user's shell folders (read-only).
USER_SHELL_FOLDERS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
DOCUMENTS_VALUE = "Personal"
# The uninstall keys, read for the Ruby installs (read-only, plan 086).
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
ERROR_NO_MORE_ITEMS = 259


class PartlyReadError(OSError):
    """Some keys could not be read; ``found`` holds what the others gave."""

    def __init__(self, message: str, found: list):
        super().__init__(message)
        self.found = found


class Disk:
    """The direct, read-only file access of the Python read path (plan 073): tests
    replace its methods to raise ``OSError`` or ``sqlite3.Error`` for a chosen path."""

    def exists(self, path) -> bool:
        """True when ``path`` exists; False when it (or a parent) is not there. Any other
        ``OSError`` (access denied) is raised, so "absent" never hides "unreadable"."""
        return Path(path).exists()

    def is_file(self, path) -> bool:
        """True when ``path`` is a file; False when it is a folder or not there. Any other
        ``OSError`` (access denied) is raised."""
        return Path(path).is_file()

    def size(self, path) -> int:
        """The size in bytes of the file ``path``; ``OSError`` when it cannot be read."""
        return Path(path).stat().st_size

    def list_dir(self, path) -> list:
        """The entry names of the folder ``path``; ``OSError`` when it cannot be listed."""
        return os.listdir(path)

    def read_text(self, path, utf16_bom: bool = False) -> str:
        """The text of the UTF-8 file ``path`` (a BOM is dropped); with ``utf16_bom``, a
        file starting with a UTF-16 byte order mark is read as UTF-16 (as Export-Clixml
        of Windows PowerShell writes it). ``OSError`` or ``UnicodeDecodeError`` when it
        cannot be read."""
        data = Path(path).read_bytes()
        if utf16_bom and data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")

    def documents_folder(self) -> str | None:
        """The raw (unexpanded) ``Personal`` value of ``HKCU\\...\\Explorer\\User Shell
        Folders`` (the user's Documents folder), or None when it is not set; opened
        read-only. A read error, or a value that is not text, is an ``OSError``."""
        try:
            import winreg  # Windows-only, and only for a real run
        except ImportError as exc:
            raise OSError(f"winreg is not available: {exc}") from exc
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_SHELL_FOLDERS, 0,
                                winreg.KEY_READ) as key:
                data, _ = winreg.QueryValueEx(key, DOCUMENTS_VALUE)
        except FileNotFoundError:
            return None
        if not isinstance(data, str):
            raise OSError(f"the value {DOCUMENTS_VALUE} is not text")
        return data

    def ruby_install_locations(self) -> list:
        """The ``InstallLocation`` of every uninstall key whose ``DisplayName`` starts with
        ``Ruby `` (as RubyInstaller writes them), from ``HKCU`` and from ``HKLM`` in the
        64-bit and the 32-bit view, each key opened read-only. A missing key, or a key
        without a text ``DisplayName`` or ``InstallLocation``, is no entry. A key that
        cannot be read does not stop the scan: after it, ``PartlyReadError`` carries the
        locations found (``found``) and names the keys not read; any other read error
        is an ``OSError``."""
        try:
            import winreg  # Windows-only, and only for a real run
        except ImportError as exc:
            raise OSError(f"winreg is not available: {exc}") from exc
        views = ((winreg.HKEY_CURRENT_USER, 0),
                 (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                 (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY))
        found, errors = [], []
        for hive, view in views:
            access = winreg.KEY_READ | view
            try:
                root = winreg.OpenKey(hive, UNINSTALL_KEY, 0, access)
            except FileNotFoundError:
                continue
            except OSError as exc:
                errors.append(f"{UNINSTALL_KEY}: {type(exc).__name__}: {exc}")
                continue
            with root:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, index)
                    except OSError as exc:
                        if getattr(exc, "winerror", None) == ERROR_NO_MORE_ITEMS:
                            break
                        raise
                    index += 1
                    try:
                        with winreg.OpenKey(root, name, 0, access) as key:
                            display, _ = winreg.QueryValueEx(key, "DisplayName")
                            location, _ = winreg.QueryValueEx(key, "InstallLocation")
                    except FileNotFoundError:
                        continue  # the key went away, or it lacks one of the values
                    except OSError as exc:
                        errors.append(f"{name}: {type(exc).__name__}: {exc}")
                        continue
                    if (isinstance(display, str) and display.startswith("Ruby ")
                            and isinstance(location, str) and location.strip()):
                        found.append(location.strip())
        if errors:
            raise PartlyReadError(f"{len(errors)} uninstall keys could not be read "
                                  f"({'; '.join(errors)})", found)
        return found

    def query_catalog(self, path, sql) -> list:
        """The rows of ``sql`` on the SQLite file ``path``, opened read-only and immutable
        (nothing is written beside it, no -journal, -shm or -wal file); the connection is
        always closed. ``sqlite3.Error`` when it cannot be read."""
        uri = Path(path).as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            return conn.execute(sql).fetchall()


DISK = Disk()


def environment_value(name: str) -> str | None:
    """The value of the variable ``name`` in ``ENVIRON`` (name matched without regard
    to case), or None when it is unset or blank."""
    for key, value in ENVIRON.items():
        if isinstance(key, str) and key.casefold() == name.casefold():
            return value.strip() if isinstance(value, str) and value.strip() else None
    return None


def expand_path(raw: str) -> str | None:
    """``raw`` with each ``%VAR%`` replaced from ``ENVIRON`` (no trailing slash), or None
    when one of them is unset or blank: such a location is not looked at and counts as
    absent, so a test with an empty ``ENVIRON`` never reads the machine."""
    missing = []

    def value(match):
        found = environment_value(match.group(1))
        if found is None:
            missing.append(match.group(1))
            return match.group(0)
        return found.rstrip("\\/")

    expanded = ENVIRONMENT_REFERENCE.sub(value, raw)
    return None if missing else expanded


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

    A missing ``node_modules`` makes npm ``not_present`` (``looked_in`` the folder; the
    source is ``empty``). Status ``read`` with at least one package, ``empty`` when
    ``node_modules`` exists and holds no package, ``unreadable`` (count null, named
    in not_checked) when ``.npmrc`` or the folder could not be read; then the items of
    the previous baseline are kept, marked ``from_baseline``. ``unreadable`` (the
    package count) is null with status ``unreadable``. When npm is ``not_present`` or
    ``empty``, names the prefixes not searched in not_checked.
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
    if answer["status"] == "absent":
        col.skip(*NPM_OTHER_PREFIXES)
        status, items, col.npm_summary = not_present(col, "npm", "npm_packages", [folder])
        return status, items
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


def not_present(col: Collector, manager: str, source: str, looked_in: list) -> tuple:
    """Record a manager none of whose locations exists: the source is ``empty`` (its old
    items are removed from the baseline), the manager ``not_present``."""
    col.record(source, "empty", None)
    col.not_present.add(manager)
    return "empty", {}, {"status": "empty", "looked_in": list(looked_in)}


def carry_source(col: Collector, source: str, previous: dict, reason: str) -> dict:
    """Record ``source`` as ``unreadable`` (named in not_checked) and keep every item of
    the previous baseline, marked ``from_baseline``."""
    col.record(source, "unreadable", reason)
    items = {}
    carry(col, source, previous, items, lambda key: True)
    return items


def unreadable_item(item: dict, reason: str) -> dict:
    """``item`` as one whose metadata could not be read: no version, the reason."""
    item.update(version=None, status="unreadable", reason=reason, unread_fields=["version"])
    return item


# pipx: the pipx_metadata.json of each venv of the pipx homes (pipx does not run).
PIPX_HOME_VARIABLE = "PIPX_HOME"
# pipx 1.5+, before 1.3, 1.3-1.4.
PIPX_DEFAULT_HOMES = ("%USERPROFILE%\\pipx", "%USERPROFILE%\\.local\\pipx",
                      "%LOCALAPPDATA%\\pipx\\pipx")
PIPX_OUTSIDE = ("pipx homes outside looked_in",
                ("a pipx home set by another account's PIPX_HOME, or the default of "
                 "another pipx version, is not searched"))
PIPX_SHARED = ("pipx shared libraries",
               ("the shared folder of each pipx home (the pip that the venvs share) is "
                "no venv and is not read"))


def pipx_homes() -> list:
    """The raw pipx homes: a non-blank ``PIPX_HOME`` alone, else the defaults."""
    value = environment_value(PIPX_HOME_VARIABLE)
    if value is not None:
        return [value.rstrip("\\/")]
    return list(PIPX_DEFAULT_HOMES)


def same_folder(folder: str) -> str:
    """One spelling of a Windows folder: case, slashes and doubled separators folded."""
    return ntpath.normcase(ntpath.normpath(folder.strip().rstrip("\\/")))


def stable_labels(rows: list, previous: dict) -> list:
    """The label of each ``(name, folder)`` row, in order: ``name``, else ``name~2``,
    ``name~3``... A folder whose items of the previous baseline had a label of this
    name keeps it while no earlier row took it, so a same-named folder that goes away
    does not hand its key to another one (no false ``changed``); the other rows take
    the first free label in order."""
    old = {}
    for key, item in (previous or {}).items():
        folder = text(item.get("folder")) if isinstance(item, dict) else None
        if folder is not None:
            label = key.split(":", 1)[-1].split("|", 1)[0]
            old.setdefault(same_folder(folder), label)
    labels, taken = [None] * len(rows), set()
    for index, (name, folder) in enumerate(rows):
        label = old.get(same_folder(folder))
        if label is not None and label not in taken and (
                label == name or re.fullmatch(re.escape(name) + r"~[2-9]\d*", label)):
            labels[index] = label
            taken.add(label)
    for index, (name, _folder) in enumerate(rows):
        if labels[index] is None:
            label, number = name, 1
            while label in taken:
                number += 1
                label = f"{name}~{number}"
            labels[index] = label
            taken.add(label)
    return labels


def pipx_venv_items(home: str, label: str, venv) -> list:
    """``[(key, item)]`` of one venv row: the main package and each injected one.

    A metadata file that could not be read or parsed, or whose main package lacks a
    string ``package_version``, is one unreadable item; an injected entry without a
    string ``package_version`` is an unreadable item of its own."""
    venv = venv if isinstance(venv, dict) else {}
    name = text(venv.get("venv")) or "?"
    base = {"name": name, "version": None, "venv": name, "injected": False,
            "folder": f"{home}\\venvs\\{name}", "status": "read", "reason": None}
    key = f"pipx:{label}"
    status, reason = venv.get("status"), text(venv.get("reason"))
    if status == "unreadable":
        return [(key, unreadable_item(base, reason or "the pipx_homes job gave no reason"))]
    if status != "read":
        return [(key, unreadable_item(
            base, reason or "the pipx_homes job did not say whether the file was read"))]
    try:
        data = json.loads(venv.get("metadata") or "")
    except (TypeError, ValueError) as exc:
        return [(key, unreadable_item(
            base, f"pipx_metadata.json is not JSON: {type(exc).__name__}: {exc}"))]
    main = data.get("main_package") if isinstance(data, dict) else None
    injected = data.get("injected_packages") if isinstance(data, dict) else None
    if not isinstance(main, dict) or not isinstance(main.get("package_version"), str) \
            or not main["package_version"].strip():
        return [(key, unreadable_item(
            base, "pipx_metadata.json has no string main_package.package_version"))]
    if injected is not None and not isinstance(injected, dict):
        return [(key, unreadable_item(
            base, "pipx_metadata.json has an injected_packages that is not an object"))]
    base.update(name=text(main.get("package")) or name, version=main["package_version"])
    found = [(key, base)]
    for injected_name, entry in sorted((injected or {}).items()):
        item = {"name": injected_name, "version": None, "venv": name, "injected": True,
                "folder": base["folder"], "status": "read", "reason": None}
        version = entry.get("package_version") if isinstance(entry, dict) else None
        if isinstance(version, str) and version.strip():
            item["version"] = version
        else:
            unreadable_item(item, "pipx_metadata.json gives this injected package no "
                                  "string package_version")
        found.append((f"{key}|{injected_name.strip().casefold()}", item))
    return found


def collect_pipx(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``pipx_packages``; the summary part is
    kept in ``col.pipx_summary``.

    No home exists: ``not_present`` (source ``empty``). A home that exists but could
    not be listed: ``unreadable`` (count null, named in not_checked), the previous
    baseline's items kept ``from_baseline``. Else ``read`` with at least one item,
    ``empty`` with none. A venv name already seen in an earlier home gets ``~2``,
    ``~3``... A venv whose metadata could not be read keeps its previous injected
    items ``from_baseline``.
    """
    homes = pipx_homes()
    answers = read_locations(col, "pipx_homes", PIPX_HOMES_BODY, "pipx_homes",
                             {"homes": homes}, homes, "venvs", "venv")
    if all(answers[home.casefold()]["status"] == "absent" for home in homes):
        col.skip(*PIPX_OUTSIDE)
        status, items, col.pipx_summary = not_present(col, "pipx", "pipx_packages", homes)
        return status, items
    unread = [(home, answers[home.casefold()]["reason"]) for home in homes
              if answers[home.casefold()]["status"] == "unreadable"]
    if unread:
        reason = "; ".join(f"the pipx home {home} could not be listed: {why}"
                           for home, why in unread)
        items = carry_source(col, "pipx_packages", previous, reason)
        col.pipx_summary = {
            "status": "unreadable",
            "homes": [{"folder": home, "status": answers[home.casefold()]["status"]}
                      for home in homes],
            "count": None, "unreadable": None}
        return "unreadable", items
    items, count, unreadable = {}, 0, 0
    rows = []
    for home in homes:
        venvs = sorted(answers[home.casefold()]["venvs"],
                       key=lambda v: (text(v.get("venv")) or "?").casefold()
                       if isinstance(v, dict) else "?")
        for venv in venvs:
            name = (text(venv.get("venv")) if isinstance(venv, dict) else None) or "?"
            rows.append((home, venv, name.casefold(), f"{home}\\venvs\\{name}"))
    labels = stable_labels([(name, folder) for _h, _v, name, folder in rows],
                           previous)
    for (home, venv, _name, _folder), label in zip(rows, labels):
        found = pipx_venv_items(home, label, venv)
        if len(found) == 1 and found[0][1]["status"] == "unreadable":
            carry(col, "pipx_packages", previous, items,
                  lambda key, label=label: key.startswith(f"pipx:{label}|"))
        for key, item in found:
            items[key] = item
            if item["status"] == "read":
                count += 1
            else:
                unreadable += 1
    status = "read" if items else "empty"
    col.record("pipx_packages", status, None)
    col.skip(*PIPX_OUTSIDE)
    col.skip(*PIPX_SHARED)
    col.pipx_summary = {
        "status": status,
        "homes": [{"folder": home, "status": answers[home.casefold()]["status"]}
                  for home in homes],
        "count": count, "unreadable": unreadable}
    return status, items


# uv tools: each tool's dist-info in its own venv (uv does not run).
UV_TOOL_VARIABLE = "UV_TOOL_DIR"
UV_DEFAULT_FOLDER = "%APPDATA%\\uv\\data\\tools"
UV_OUTSIDE = ("uv tools outside looked_in",
              ("a tool folder set by UV_TOOL_DIR in another environment, or under "
               "XDG_DATA_HOME, is not searched"))
UV_PYTHONS = ("Python installs managed by uv",
              "the Pythons that uv installs are not read; their packages are not listed")
UV_NO_DIST_INFO = "no dist-info of the tool's package"


def uv_tool_item(tool: str, folder: str, packages: list) -> dict:
    """The item of uv tool ``tool``: the version of the ``dist-info`` (or ``egg-info``)
    whose PEP 503 name is the tool folder's name, the highest when there are several;
    unreadable when there is none or only one whose metadata could not be read."""
    wanted = pip_key_name(tool)
    matches = []
    for package in packages:
        key, item, entry = pip_item("", "", package)
        if key.rsplit("|", 1)[1] == wanted:
            matches.append((version_key(item["version"] or entry_version(entry)), entry,
                            item))
    base = {"name": tool, "version": None, "folder": f"{folder}\\{tool}", "status": "read",
            "reason": None}
    if not matches:
        return unreadable_item(base, UV_NO_DIST_INFO)
    _, _, best = max(matches, key=lambda match: match[:2])
    if best["status"] != "read" or best["version"] is None:
        return unreadable_item(base, best["reason"] or "the dist-info gives no Version header")
    base.update(name=best["name"], version=best["version"])
    return base


def collect_uv(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``uv_tools``; the summary part is kept in
    ``col.uv_summary``.

    No tool folder: ``not_present`` (source ``empty``). A tool folder that could not be
    listed: ``unreadable`` (count null), the previous items kept ``from_baseline``.
    Else each subfolder holding ``uv-receipt.toml`` is a tool, read from its
    ``Lib\\site-packages`` (job ``package_folders``, layout ``python``, work files
    ``package_folders-uv``). A tool whose folder could not be listed or checked keeps
    its previous item ``from_baseline``, is named in not_checked, and makes the count
    null.
    """
    value = environment_value(UV_TOOL_VARIABLE)
    folder = value.rstrip("\\/") if value is not None else UV_DEFAULT_FOLDER
    answer = read_locations(col, "uv_tools", UV_TOOLS_BODY, "uv_tools", {"folders": [folder]},
                            [folder], "entries", "entry")[folder.casefold()]
    if answer["status"] == "absent":
        col.skip(*UV_OUTSIDE)
        status, items, col.uv_summary = not_present(col, "uv", "uv_tools", [folder])
        return status, items
    if answer["status"] == "unreadable":
        items = carry_source(col, "uv_tools", previous,
                             f"the uv tool folder {folder} could not be listed: "
                             f"{answer['reason']}")
        col.uv_summary = {"status": "unreadable", "folder": folder, "count": None,
                          "unreadable": None}
        return "unreadable", items
    items, tools, count, unreadable, unread_tools = {}, [], 0, 0, 0
    for entry in answer["entries"]:
        name = text(entry.get("name")) if isinstance(entry, dict) else None
        if name is None:
            continue
        receipt = entry.get("receipt")
        if receipt is True:
            tools.append(name)
        elif receipt is not False:
            unread_tools += 1
            col.skip(f"uv_tools {name}",
                     "whether the folder holds uv-receipt.toml could not be checked: "
                     f"{text(entry.get('reason')) or 'no reason given'}")
            carry(col, "uv_tools", previous, items,
                  lambda key, name=name: key == f"uv:{name.casefold()}")
    tools.sort(key=str.casefold)
    paths = {tool: f"{folder}\\{tool}\\Lib\\site-packages" for tool in tools}
    folders = (read_package_folders(col, list(paths.values()), file_name="package_folders-uv")
               if tools else {})
    for tool in tools:
        site = folders[paths[tool].casefold()]
        key = f"uv:{tool.casefold()}"
        if site["packages"] is None:
            unread_tools += 1
            col.skip(f"uv_tools {tool}", f"{paths[tool]} could not be listed: {site['reason']}")
            carry(col, "uv_tools", previous, items, lambda k, key=key: k == key)
            continue
        items[key] = uv_tool_item(tool, folder, site["packages"])
        if items[key]["status"] == "read":
            count += 1
        else:
            unreadable += 1
    status = "read" if tools or unread_tools else "empty"
    col.record("uv_tools", status, None)
    col.skip(*UV_OUTSIDE)
    col.skip(*UV_PYTHONS)
    col.uv_summary = {"status": status, "folder": folder,
                      "count": None if unread_tools else count, "unreadable": unreadable}
    return status, items


# conda: the conda-meta file names of each environment of environments.txt (conda
# does not run, no file content is read).
CONDA_ENVIRONMENTS_FILE = "%USERPROFILE%\\.conda\\environments.txt"
CONDA_OUTSIDE = (("conda environments outside environments.txt (.condarc envs_dirs, "
                  "CONDA_ENVS_PATH)"), "not searched")
CONDA_META_SUFFIX = ".json"


def conda_item(label: str, folder: str, file_name: str) -> tuple[str, dict]:
    """``(key, item)`` of one ``conda-meta`` file name ``<name>-<version>-<build>.json``,
    split at the last two ``-``. A name that does not split into three non-empty parts
    is an unreadable item, never guessed."""
    stem = file_name.strip()
    if stem.casefold().endswith(CONDA_META_SUFFIX):
        stem = stem[:-len(CONDA_META_SUFFIX)]
    parts = stem.rsplit("-", 2)
    item = {"name": stem, "version": None, "build": None, "environment": label,
            "folder": folder, "status": "read", "reason": None}
    if len(parts) == 3 and all(part.strip() for part in parts):
        item.update(name=parts[0], version=parts[1], build=parts[2])
    else:
        unreadable_item(item, f"the conda-meta file name {file_name} does not split into "
                              f"<name>-<version>-<build>")
    return f"conda:{label}|{item['name'].strip().casefold()}", item


def collect_conda(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``conda_packages``; the summary part is
    kept in ``col.conda_summary``.

    No ``environments.txt``: ``not_present`` (source ``empty``). A file that could not
    be read: ``unreadable`` (count null), the previous items kept ``from_baseline``.
    Else each prefix is an environment labelled by its last folder name (``~2``,
    ``~3``... for a later prefix of the same label): a prefix whose folder is absent
    gives no item; one whose ``conda-meta`` could not be listed keeps its previous items
    ``from_baseline``, is named in not_checked, and makes the count null.
    """
    file = CONDA_ENVIRONMENTS_FILE
    answer = read_locations(col, "conda_environments", CONDA_ENVIRONMENTS_BODY,
                            "conda_environments", {"file": file}, [file], "prefixes",
                            "prefix", depth=5)[file.casefold()]
    if answer["status"] == "absent":
        col.skip(*CONDA_OUTSIDE)
        status, items, col.conda_summary = not_present(col, "conda", "conda_packages", [file])
        return status, items
    if answer["status"] == "unreadable":
        items = carry_source(col, "conda_packages", previous,
                             f"{file} could not be read: {answer['reason']}")
        col.conda_summary = {"status": "unreadable", "file": file, "environments": None,
                             "count": None, "unreadable": None}
        return "unreadable", items
    items, environments, count, unreadable, unread_envs = {}, [], 0, 0, 0
    # one prefix may be written twice (case, slashes, trailing separator): read it once
    done, rows = set(), []
    for row in answer["prefixes"]:
        row = row if isinstance(row, dict) else {}
        prefix = text(row.get("prefix"))
        if prefix is None:
            unread_envs += 1
            col.skip("conda_packages environment",
                     "the conda_environments job gave a line without a prefix, so its "
                     "packages are not read")
            continue
        prefix = prefix.strip().rstrip("\\/")
        same = same_folder(prefix)
        if same in done:
            continue
        done.add(same)
        rows.append((row, prefix, re.split(r"[\\/]", prefix)[-1].casefold() or "?"))
    labels = stable_labels([(name, prefix + "\\conda-meta") for _r, prefix, name in rows],
                           previous)
    for (row, prefix, _name), label in zip(rows, labels):
        folder = prefix + "\\conda-meta"
        status, files = row.get("status"), row.get("files")
        if status == "absent":
            environments.append({"label": label, "folder": prefix, "status": "absent"})
            continue
        if status != "read" or not isinstance(files, (list, str)):
            reason = text(row.get("reason")) or (
                "the conda_environments job gave no reason" if status == "unreadable"
                else "the conda_environments job gave no file list")
            environments.append({"label": label, "folder": prefix, "status": "unreadable"})
            unread_envs += 1
            col.skip(f"conda_packages {label}", f"{folder} could not be listed: {reason}")
            carry(col, "conda_packages", previous, items,
                  lambda key, label=label: key.startswith(f"conda:{label}|"))
            continue
        environments.append({"label": label, "folder": prefix, "status": "read"})
        # Two files of one name (not written by conda): the plain key goes to the
        # highest version, the others keep "|<file name>".
        rows = sorted((conda_item(label, folder, file_name) + (file_name,)
                       for file_name in as_list(files) if text(file_name) is not None),
                      key=lambda found: (version_key(found[1]["version"]),
                                         found[2].casefold()),
                      reverse=True)
        for key, item, file_name in rows:
            if key in items:
                key = f"{key}|{file_name.strip().casefold()}"
            items[key] = item
            if item["status"] == "read":
                count += 1
            else:
                unreadable += 1
    status = "read" if items or unread_envs else "empty"
    col.record("conda_packages", status, None)
    col.skip(*CONDA_OUTSIDE)
    col.conda_summary = {"status": status, "file": file, "environments": environments,
                         "count": None if unread_envs else count, "unreadable": unreadable}
    return status, items


# winget: the packages winget recorded as installed through it, read from its tracking
# catalogs (SQLite, opened read-only and immutable; winget does not run).
WINGET_SOURCE = "winget_packages"
WINGET_LOCAL_STATE = ("%LOCALAPPDATA%\\Packages\\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
                      "\\LocalState")
WINGET_CATALOG_FILE = "installed.db"
# The tracking catalog schema this reader knows (metadata majorVersion).
WINGET_SCHEMA = "1"
WINGET_SCHEMA_SQL = "SELECT value FROM metadata WHERE name = 'majorVersion'"
# LEFT JOIN: a manifest row whose id, name or version points at no row is still
# returned, with NULL there, instead of being dropped. winget_items counts a NULL id
# as a row without an id, shows the id for a NULL name, and marks an id unreadable
# when none of its rows gives a version.
WINGET_MANIFEST_SQL = ("SELECT manifest.rowid, ids.id, names.name, versions.version "
                       "FROM manifest "
                       "LEFT JOIN ids ON ids.rowid = manifest.id "
                       "LEFT JOIN names ON names.rowid = manifest.name "
                       "LEFT JOIN versions ON versions.rowid = manifest.version")
WINGET_NOT_MERGED = ("the catalog is read immutable; writes still in its -wal file are "
                     "not seen")
WINGET_READ_NOTES = (("winget records not checked against installed programs",
                      ("the tracking catalogs list what winget installed; a package removed "
                       "outside winget may still be listed")),
                     ("packages installed outside winget",
                      ("only winget's tracking catalogs are read; programs installed "
                       "another way are not winget packages here")))


def winget_rows(path: str) -> tuple[list | None, str | None]:
    """``(rows, None)`` of one tracking catalog, each ``(manifest rowid, id, name,
    version)``, or ``(None, reason)`` when it cannot be read or its schema
    (``metadata`` ``majorVersion``) is not ``WINGET_SCHEMA``."""
    try:
        schema = DISK.query_catalog(path, WINGET_SCHEMA_SQL)
        values = sorted({str(row[0]).strip() for row in schema})
        if values != [WINGET_SCHEMA]:
            return None, f"tracking catalog schema {', '.join(values) or '(none)'} not known"
        return DISK.query_catalog(path, WINGET_MANIFEST_SQL), None
    except (sqlite3.Error, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def winget_items(label: str, folder: str, rows: list) -> tuple[dict, int]:
    """``({key: item}, rows without an id)`` of one catalog: per id (case-folded) the row
    with the highest version by ``version_key``, a tie broken by the version string,
    then by the highest manifest rowid, so the choice never depends on row order."""
    by_id, no_id = {}, 0
    for row in rows:
        rowid, package_id, name, version = (tuple(row) + (None,) * 4)[:4]
        package_id = text(package_id)
        if package_id is None:
            no_id += 1
            continue
        by_id.setdefault(package_id.strip().casefold(), []).append(
            (rowid if isinstance(rowid, int) else -1, package_id.strip(), text(name),
             text(version)))
    items = {}
    for folded, found in sorted(by_id.items()):
        rowid, package_id, name, version = max(
            found, key=lambda r: (version_key(r[3]), r[3] or "", r[0]))
        item = {"name": name or package_id, "id": package_id, "version": version,
                "versions_recorded": len(found), "source": label, "folder": folder,
                "status": "read", "reason": None}
        if version is None:
            unreadable_item(item, "the tracking catalog gives no version for this id")
        items[f"winget:{label}|{folded}"] = item
    return items, no_id


def collect_winget(col: Collector, previous: dict) -> tuple[str, dict]:
    """Read the winget tracking catalogs, with a start and an end progress line."""
    progress.step(f"{WINGET_SOURCE} ...")
    status, items = read_winget(col, previous)
    progress.step(f"{WINGET_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def read_winget(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``winget_packages``; the summary part
    ``{status, catalogs, count, unreadable}`` is kept in ``col.winget_summary``.

    ``LocalState`` absent (or its ``%VAR%`` unset): ``not_present``. Present but not
    listable: ``unreadable``, the previous items kept ``from_baseline``. Each subfolder
    holding ``installed.db`` is a catalog, labelled by its name case-folded. A catalog
    that cannot be read keeps its previous items ``from_baseline`` and is named in
    not_checked; the source is ``unreadable`` only when no catalog could be read. The
    count is null while any catalog is unreadable. A catalog with manifest rows that
    give no id keeps its previous items not found now ``from_baseline``. The source
    is ``read`` when an item was found, a catalog was unreadable or a row gave no id;
    ``empty`` only when every catalog was read and gave neither.
    """
    path = expand_path(WINGET_LOCAL_STATE)
    try:
        present = path is not None and DISK.exists(path)
        names = sorted(DISK.list_dir(path), key=str.casefold) if present else None
    except OSError as exc:
        reason = (f"{WINGET_LOCAL_STATE} could not be listed: "
                  f"{type(exc).__name__}: {exc}")
        items = carry_source(col, WINGET_SOURCE, previous, reason)
        col.winget_summary = {"status": "unreadable", "catalogs": None, "count": None,
                              "unreadable": None}
        return "unreadable", items
    if not present:
        status, items, col.winget_summary = not_present(
            col, "winget", WINGET_SOURCE, [WINGET_LOCAL_STATE])
        return status, items
    items, catalogs, unreadable = {}, [], 0
    for name in names:
        label = name.casefold()
        folder = f"{WINGET_LOCAL_STATE}\\{name}"
        catalog = f"{path}\\{name}\\{WINGET_CATALOG_FILE}"
        row = {"source": label, "status": "read", "count": None, "wal_present": None,
               "reason": None}
        wal_reason = None
        try:
            if not DISK.exists(catalog):
                continue  # a folder or file that is no catalog
        except OSError as exc:
            # Whether it is a catalog is not known: its items, if any, are kept.
            row.update(status="unreadable", reason=f"{type(exc).__name__}: {exc}")
        else:
            try:
                # A zero-byte -wal is left after a checkpoint and holds nothing
                # unmerged; only a non-empty one is named. One stat call: a -wal that
                # is not there (or is deleted meanwhile) is no -wal.
                row["wal_present"] = DISK.size(catalog + "-wal") > 0
            except FileNotFoundError:
                row["wal_present"] = False
            except OSError as exc:
                wal_reason = f"{type(exc).__name__}: {exc}"
            rows, reason = winget_rows(catalog)
            if rows is None:
                row.update(status="unreadable", reason=reason)
        catalogs.append(row)
        if row["status"] == "unreadable":
            col.skip(f"winget_packages {label}",
                     f"{folder}\\{WINGET_CATALOG_FILE} could not be read: {row['reason']}")
            carry(col, WINGET_SOURCE, previous, items,
                  lambda key, label=label: key.startswith(f"winget:{label}|"))
            continue
        if row["wal_present"]:
            col.skip(f"winget records not yet merged into {label}\\{WINGET_CATALOG_FILE}",
                     WINGET_NOT_MERGED)
        elif row["wal_present"] is None:
            col.skip(f"winget records not yet merged into {label}\\{WINGET_CATALOG_FILE}",
                     f"whether a -wal file is beside the catalog could not be checked: "
                     f"{wal_reason}")
        found, no_id = winget_items(label, folder, rows)
        items.update(found)
        if no_id:
            col.skip(f"winget_packages {label} rows without an id",
                     f"{no_id} manifest rows of the tracking catalog give no id and are "
                     f"not read")
            # A previous package of this catalog not found now may be behind a row
            # without an id: carried from the baseline, never reported removed.
            carry(col, WINGET_SOURCE, previous, items,
                  lambda key, label=label, found=found:
                  key.startswith(f"winget:{label}|") and key not in found)
        row["count"] = sum(1 for item in found.values() if item["status"] == "read")
        unreadable += no_id + sum(1 for item in found.values()
                                  if item["status"] == "unreadable")
    read = [row for row in catalogs if row["status"] == "read"]
    if catalogs and not read:
        col.record(WINGET_SOURCE, "unreadable", "no tracking catalog of winget could be read")
        col.winget_summary = {"status": "unreadable", "catalogs": catalogs, "count": None,
                              "unreadable": None}
        return "unreadable", items
    # Partly read is read: an unread catalog or rows without an id were there and
    # not read, so the source is never "empty" (read, nothing there).
    status = "read" if items or len(read) < len(catalogs) or unreadable else "empty"
    col.record(WINGET_SOURCE, status, None)
    for note in WINGET_READ_NOTES:
        col.skip(*note)
    col.winget_summary = {
        "status": status, "catalogs": catalogs,
        "count": None if len(read) < len(catalogs) else sum(r["count"] for r in read),
        "unreadable": unreadable}
    return status, items


# VS Code extensions: the extensions.json of the extensions folder (VS Code does not
# run). Other editions (Insiders, VSCodium, portable) are not read.
VSCODE_SOURCE = "vscode_extensions"
VSCODE_VARIABLE = "VSCODE_EXTENSIONS"
VSCODE_DEFAULT_FOLDER = "%USERPROFILE%\\.vscode\\extensions"
VSCODE_LIST_FILE = "extensions.json"
VSCODE_NO_LIST = "no extensions.json in the extensions folder"
VSCODE_EDITIONS = ("VS Code Insiders, VSCodium and portable VS Code",
                   ("only the extensions folder of VS Code (VSCODE_EXTENSIONS, else "
                    "%USERPROFILE%\\.vscode\\extensions) is read; the extensions of other "
                    "editions and of editors built on VS Code are not"))


def vscode_entry(raw: str, entry) -> tuple[str, dict] | None:
    """``(key, item)`` of one ``extensions.json`` entry, or None when it has no string
    ``identifier.id`` (it cannot be keyed). An entry without a string ``version`` is an
    item with status ``unreadable``. ``folder`` is the raw extensions folder joined with
    ``relativeLocation``, or None without one."""
    identifier = entry.get("identifier") if isinstance(entry, dict) else None
    ext_id = identifier.get("id") if isinstance(identifier, dict) else None
    if not isinstance(ext_id, str) or not ext_id.strip():
        return None
    ext_id = ext_id.strip()
    version, relative = entry.get("version"), entry.get("relativeLocation")
    item = {"name": ext_id,
            "version": version.strip() if isinstance(version, str) and version.strip()
            else None,
            "status": "read", "reason": None,
            "folder": f"{raw}\\{relative.strip()}"
            if isinstance(relative, str) and relative.strip() else None}
    if item["version"] is None:
        unreadable_item(item, "extensions.json gives no version for this extension")
    return f"vscode:{ext_id.casefold()}", item


def collect_vscode(col: Collector, previous: dict) -> tuple[str, dict]:
    """Read the VS Code extensions, with a start and an end progress line."""
    progress.step(f"{VSCODE_SOURCE} ...")
    status, items = read_vscode(col, previous)
    progress.step(f"{VSCODE_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def read_vscode(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``vscode_extensions``; the summary part
    ``{status, folder_from, count, unreadable}`` is kept in ``col.vscode_summary``.

    The folder is ``VSCODE_EXTENSIONS`` (non-blank), else
    ``%USERPROFILE%\\.vscode\\extensions``. Absent (or its ``%VAR%`` unset):
    ``not_present``. Present without a readable ``extensions.json`` holding a list:
    ``unreadable``, the previous items kept ``from_baseline``. An entry without an id
    counts in ``unreadable`` and is named once in not_checked; a second entry of the
    same id gets ``|<folder case-folded>`` (as npm).
    """
    raw = environment_value(VSCODE_VARIABLE)
    folder_from = VSCODE_VARIABLE
    if raw is None:
        raw, folder_from = VSCODE_DEFAULT_FOLDER, "default"
    raw = raw.rstrip("\\/") or raw
    path = expand_path(raw)
    list_file = f"{raw}\\{VSCODE_LIST_FILE}"

    def unreadable(reason: str) -> tuple[str, dict]:
        items = carry_source(col, VSCODE_SOURCE, previous, reason)
        col.vscode_summary = {"status": "unreadable", "folder_from": folder_from,
                              "count": None, "unreadable": None}
        return "unreadable", items

    try:
        present = path is not None and DISK.exists(path)
        listed = DISK.read_text(f"{path}\\{VSCODE_LIST_FILE}") if present else None
    except FileNotFoundError:
        return unreadable(VSCODE_NO_LIST)
    except (OSError, UnicodeDecodeError) as exc:
        return unreadable(f"{list_file} could not be read: {type(exc).__name__}: {exc}")
    if not present:
        col.skip(*VSCODE_EDITIONS)
        status, items, col.vscode_summary = not_present(col, "vscode", VSCODE_SOURCE, [raw])
        return status, items
    try:
        entries = json.loads(listed)
    except ValueError as exc:
        return unreadable(f"{list_file} is not JSON: {type(exc).__name__}: {exc}")
    if not isinstance(entries, list):
        return unreadable(f"{list_file} does not hold a list")
    rows, no_id = [], 0
    for entry in entries:
        row = vscode_entry(raw, entry)
        if row is None:
            no_id += 1
        else:
            rows.append(row)
    if entries and not rows:
        # Entries, none of them keyed: not "read, nothing there".
        return unreadable(f"none of the {no_id} entries of {list_file} gives an "
                          f"identifier.id")
    rows.sort(key=lambda row: (row[0], (row[1]["folder"] or "").casefold()))
    items = {}
    for key, item in rows:
        if key in items:  # a second entry of the same id (not written by VS Code)
            key = f"{key}|{(item['folder'] or '?').casefold()}"
        base, suffix = key, 2
        while key in items:  # the same id and folder again: no entry is overwritten
            key, suffix = f"{base}~{suffix}", suffix + 1
        items[key] = item
    if no_id:
        col.skip(f"{VSCODE_SOURCE} entries without an id",
                 f"{no_id} of the entries of {list_file} give no identifier.id; they "
                 f"cannot be keyed and are not read")
    count = sum(1 for item in items.values() if item["status"] == "read")
    status = "read" if items else "empty"
    col.record(VSCODE_SOURCE, status, None)
    col.skip(*VSCODE_EDITIONS)
    col.vscode_summary = {"status": status, "folder_from": folder_from, "count": count,
                          "unreadable": no_id + len(items) - count}
    return status, items


# dotnet global tools and the NuGet global packages folder: folders laid out
# <root>\<id>\<version>\ read through DISK (neither dotnet nor nuget runs).
DOTNET_SOURCE = "dotnet_tools"
DOTNET_VARIABLE = "DOTNET_CLI_HOME"
DOTNET_DEFAULT_HOME = "%USERPROFILE%"
DOTNET_TOOLS = "\\.dotnet\\tools"
DOTNET_STORE = "\\.store"
DOTNET_OUTSIDE = ("dotnet local tools (tool manifests) and tools installed with --tool-path",
                  ("only the global tool store is read; tool manifests in repositories and "
                   "--tool-path folders are not searched"))
DOTNET_INCOMPLETE = ("dotnet tool folders without a version",
                     "no version folder in the tool's folder of the tool store")
NUGET_SOURCE = "nuget_packages"
NUGET_VARIABLE = "NUGET_PACKAGES"
NUGET_DEFAULT_FOLDER = "%USERPROFILE%\\.nuget\\packages"
NUGET_METADATA = ".nupkg.metadata"
NUGET_OUTSIDE = (("NuGet globalPackagesFolder of NuGet.Config, fallback folders and the "
                  "http-cache"), "not read")
NUGET_INCOMPLETE = ("NuGet package folders without a complete version",
                    ("no .nupkg.metadata in any version folder (NuGet writes it after a "
                     "package is fully extracted)"))


def store_items(col: Collector, source: str, prefix: str, path: str, raw: str,
                complete) -> tuple[dict, int]:
    """``({key: item}, incomplete)`` of the store folder ``path`` (``raw`` unexpanded),
    laid out ``<id>\\<version>``; ``complete(version path)`` tells a complete version.
    Entries starting with ``.`` are skipped at both levels; an entry that is no folder is
    no id. Per id the highest complete version by ``version_key`` (a tie broken by the
    version string) and ``versions_found``; an id without a complete version is no item
    and counts in ``incomplete``. An id or version folder that cannot be read gives an
    ``unreadable`` item, named in not_checked. ``OSError`` when ``path`` cannot be
    listed."""
    items, incomplete = {}, 0
    names = sorted(DISK.list_dir(path), key=str.casefold)
    for number, name in enumerate(names, 1):
        progress.count(source, number, len(names))
        if name.startswith("."):
            continue
        folder = f"{raw}\\{name}"
        item = {"name": name, "version": None, "versions_found": None, "status": "read",
                "reason": None, "folder": folder}
        try:
            versions = [version for version in DISK.list_dir(f"{path}\\{name}")
                        if not version.startswith(".")]
            done = [version for version in versions
                    if complete(f"{path}\\{name}\\{version}")]
        except NotADirectoryError:
            continue  # a file beside the id folders
        except OSError as exc:
            reason = f"{folder} could not be read: {type(exc).__name__}: {exc}"
            unreadable_item(item, reason)
            col.skip(f"{source} {name}", reason)
        else:
            if not done:
                incomplete += 1
                continue
            item["version"] = max(done, key=lambda version: (version_key(version), version))
            item["versions_found"] = len(done)
        key, number = f"{prefix}{name.casefold()}", 2
        while key in items:  # ids differing only in case (a case-sensitive folder)
            key, number = f"{prefix}{name.casefold()}~{number}", number + 1
        items[key] = item
    return items, incomplete


def read_store_source(col: Collector, previous: dict, *, manager: str, source: str,
                      variable: str, default: str, tail: str, store: str, read_items,
                      outside: tuple, no_version: tuple) -> tuple[str, dict, dict]:
    """``(status, {key: item}, summary part)`` of a manager kept in a store folder.

    The folder is the non-blank ``variable`` + ``tail``, else ``default`` + ``tail``;
    absent (or its ``%VAR%`` unset): ``not_present``. The store is the folder +
    ``store``; a store folder that is absent is read with nothing there.
    ``read_items(path, raw)`` gives ``({key: item}, incomplete)`` of the store, or raises
    ``OSError`` when it cannot be listed. A folder that exists but cannot be listed:
    ``unreadable``, the previous items kept ``from_baseline``. The part is ``{status,
    folder_from, count, unreadable, incomplete}``; ``outside`` is named when read or not
    present, ``no_version`` when ``incomplete`` is above 0.
    """
    home = environment_value(variable)
    folder_from = variable
    if home is None:
        home, folder_from = default, "default"
    raw = (home.rstrip("\\/") or home) + tail
    path = expand_path(raw)
    try:
        present = folder_present(path)
        store_present = present and (not store or DISK.exists(path + store))
        items, incomplete = (read_items(path + store, raw + store)
                             if store_present else ({}, 0))
    except OSError as exc:
        reason = f"{raw + store} could not be listed: {type(exc).__name__}: {exc}"
        items = carry_source(col, source, previous, reason)
        return "unreadable", items, {"status": "unreadable", "folder_from": folder_from,
                                     "count": None, "unreadable": None, "incomplete": None}
    col.skip(*outside)
    if not present:
        return not_present(col, manager, source, [raw])
    status = "read" if items else "empty"
    col.record(source, status, None)
    if incomplete:
        col.skip(*no_version)
    count = sum(1 for item in items.values() if item["status"] == "read")
    return status, items, {"status": status, "folder_from": folder_from, "count": count,
                           "unreadable": len(items) - count, "incomplete": incomplete}


def is_folder(path: str) -> bool:
    """True when ``path`` is a folder that can be listed, False when it is a file;
    any other ``OSError`` is raised, so a folder that cannot be read is never taken
    for a file."""
    try:
        DISK.list_dir(path)
    except NotADirectoryError:
        return False
    return True


def folder_present(path) -> bool:
    """True when the folder ``path`` exists, False when it (or its ``%VAR%``) is absent.
    A file at ``path``, or a folder that cannot be listed, raises ``OSError``, so a root
    that is no folder is never read as an empty one; so does an absent ``path`` under a
    file (a variable root such as PNPM_HOME that is a file)."""
    if path is None:
        return False
    if not DISK.exists(path):
        for parent in Path(path).parents:
            try:
                if not DISK.exists(parent):
                    continue
                parent_is_file = DISK.is_file(parent)
            except OSError:
                # An ancestor that cannot be checked proves nothing: the path stays absent.
                break
            if parent_is_file:
                raise NotADirectoryError(f"{parent} is a file, not a folder")
            break
        return False
    if not is_folder(path):
        raise NotADirectoryError(f"{path} is a file, not a folder")
    return True


def collect_dotnet_tools(col: Collector, previous: dict) -> tuple[str, dict]:
    """The .NET global tools of the tool store ``<tools>\\.store\\<id>\\<version>``,
    where ``<tools>`` is ``DOTNET_CLI_HOME`` (non-blank), else ``%USERPROFILE%``, +
    ``\\.dotnet\\tools``; every version folder is complete (a file is no version). Key
    ``dotnet-tools:<id case-folded>``; the part goes to ``col.dotnet_tools_summary``."""
    progress.step(f"{DOTNET_SOURCE} ...")
    status, items, col.dotnet_tools_summary = read_store_source(
        col, previous, manager="dotnet-tools", source=DOTNET_SOURCE,
        variable=DOTNET_VARIABLE, default=DOTNET_DEFAULT_HOME, tail=DOTNET_TOOLS,
        store=DOTNET_STORE,
        read_items=lambda path, raw: store_items(col, DOTNET_SOURCE, "dotnet-tools:",
                                                 path, raw, is_folder),
        outside=DOTNET_OUTSIDE,
        no_version=DOTNET_INCOMPLETE)
    progress.step(f"{DOTNET_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def collect_nuget(col: Collector, previous: dict) -> tuple[str, dict]:
    """The NuGet global packages folder ``<id>\\<version>`` (``NUGET_PACKAGES``, non-blank,
    else ``%USERPROFILE%\\.nuget\\packages``); a version is complete when its folder holds
    a file named exactly ``.nupkg.metadata``. Key ``nuget:<id case-folded>``; the part
    goes to ``col.nuget_summary``."""
    progress.step(f"{NUGET_SOURCE} ...")
    status, items, col.nuget_summary = read_store_source(
        col, previous, manager="nuget", source=NUGET_SOURCE, variable=NUGET_VARIABLE,
        default=NUGET_DEFAULT_FOLDER, tail="", store="",
        read_items=lambda path, raw: store_items(
            col, NUGET_SOURCE, "nuget:", path, raw,
            lambda version: DISK.exists(f"{version}\\{NUGET_METADATA}")),
        outside=NUGET_OUTSIDE, no_version=NUGET_INCOMPLETE)
    progress.step(f"{NUGET_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


# PowerShell modules installed through PowerShellGet or PSResourceGet: the
# PSGetModuleInfo.xml of each module version folder of the four standard module folders,
# read through DISK (no PowerShell module command runs).
PSGALLERY_SOURCE = "psgallery_modules"
PSGALLERY_DEFAULT_DOCUMENTS = "%USERPROFILE%\\Documents"
# (label, under the Documents folder, the folder below it or the full raw folder)
PSGALLERY_FOLDERS = (
    ("user-windowspowershell", True, "\\WindowsPowerShell\\Modules"),
    ("user-powershell", True, "\\PowerShell\\Modules"),
    ("allusers-windowspowershell", False, "%ProgramFiles%\\WindowsPowerShell\\Modules"),
    ("allusers-powershell", False, "%ProgramFiles%\\PowerShell\\Modules"),
)
PSGALLERY_INFO_FILE = "PSGetModuleInfo.xml"
PSGALLERY_OUTSIDE = ("PowerShell module folders outside looked_in (PSModulePath)",
                     ("only the four standard module folders are searched; other folders "
                      "of PSModulePath are not"))
PSGALLERY_OTHER = ("PowerShell modules not installed through PowerShellGet",
                   ("module folders without a PSGetModuleInfo.xml (shipped with Windows or "
                    "copied by hand) are counted in other_modules, not listed"))
PSGALLERY_FIELDS = ("Name", "Version", "Repository")


def module_info(text_value: str) -> tuple[dict | None, str | None]:
    """``({Name, Version, Repository}, None)`` of a PSGetModuleInfo.xml (CLIXML): the text
    of the elements with attribute ``N`` of those names that are children of the
    top-level object's ``MS`` element, whatever their tag; ``(None, reason)`` when the
    text is not XML or lacks ``Name`` or ``Version``."""
    try:
        root = ElementTree.fromstring(text_value)
    except (ElementTree.ParseError, ValueError) as exc:
        return None, f"not XML: {type(exc).__name__}: {exc}"

    def local(element) -> str:
        return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""

    found = {}
    top = next((child for child in root if local(child) == "Obj"), None)
    members = (next((child for child in top if local(child) == "MS"), None)
               if top is not None else None)
    for child in members if members is not None else ():
        name = child.get("N")
        if name in PSGALLERY_FIELDS and name not in found:
            found[name] = text(child.text)
    missing = [name for name in PSGALLERY_FIELDS[:2] if found.get(name) is None]
    if missing:
        return None, f"no {' or '.join(missing)} in the top-level object"
    return found, None


def psgallery_module(label: str, raw: str, path: str, module: str) -> dict | None:
    """The item of the module folder ``<path>\\<module>``, or None when no version folder
    holds a PSGetModuleInfo.xml (not installed through PowerShellGet). A version that
    does not parse is skipped while another one parses; a folder or file that cannot be
    read makes the item ``unreadable``. ``NotADirectoryError`` for a file beside the
    module folders."""
    folder = f"{raw}\\{module}"
    item = {"name": module, "version": None, "versions_found": None, "repository": None,
            "status": "read", "reason": None, "module_folder": label, "folder": folder}
    parsed, bad = [], []
    try:
        versions = sorted(DISK.list_dir(f"{path}\\{module}"), key=str.casefold)
    except NotADirectoryError:
        raise
    except OSError as exc:
        return unreadable_item(item, f"{folder} could not be read: {type(exc).__name__}: "
                                     f"{exc}")
    for version in versions:
        info = f"{folder}\\{version}\\{PSGALLERY_INFO_FILE}"
        try:
            content = DISK.read_text(f"{path}\\{module}\\{version}\\{PSGALLERY_INFO_FILE}",
                                     utf16_bom=True)
        except (FileNotFoundError, NotADirectoryError):
            continue  # no record of PowerShellGet in it, or a file of the module
        except (OSError, UnicodeDecodeError) as exc:
            return unreadable_item(item, f"{info} could not be read: "
                                         f"{type(exc).__name__}: {exc}")
        fields, reason = module_info(content)
        if fields is None:
            bad.append(f"{info}: {reason}")
        else:
            parsed.append(fields)
    if not parsed:
        return unreadable_item(item, "; ".join(bad)) if bad else None
    best = max(parsed, key=lambda fields: (version_key(fields["Version"]),
                                            fields["Version"]))
    item.update(name=best["Name"], version=best["Version"], versions_found=len(parsed),
                repository=best.get("Repository"))
    return item


def psgallery_folders() -> tuple[list, str | None]:
    """``([(label, raw folder or None)], reason)``: the four module folders; the two
    ``user-`` ones have no folder (None) when the Documents folder cannot be read, with
    the reason."""
    try:
        documents = DISK.documents_folder()
    except OSError as exc:
        documents, reason = None, (f"the Documents folder (User Shell Folders, Personal) "
                                   f"could not be read: {type(exc).__name__}: {exc}")
    else:
        reason = None
        documents = text(documents)  # unset or blank: the default
        if documents and expand_path(documents.strip()) is None:
            # The setting names a variable this run's environment lacks: the folder is
            # unknown, not absent, so its modules are carried and never "removed".
            documents, reason = None, (f"the Documents folder (User Shell Folders, "
                                       f"Personal) {documents.strip()} names an "
                                       f"environment variable that is not set")
        else:
            documents = (documents.strip().rstrip("\\/") or documents.strip()
                         if documents else PSGALLERY_DEFAULT_DOCUMENTS)
    folders = []
    for label, in_documents, tail in PSGALLERY_FOLDERS:
        if in_documents:
            folders.append((label, None if reason else documents + tail))
        else:
            folders.append((label, tail))
    return folders, reason


def collect_psgallery(col: Collector, previous: dict) -> tuple[str, dict]:
    """Read the PowerShellGet modules, with a start and an end progress line."""
    progress.step(f"{PSGALLERY_SOURCE} ...")
    status, items = read_psgallery(col, previous)
    progress.step(f"{PSGALLERY_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def read_psgallery(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``psgallery_modules``; the summary part
    ``{status, folders, count, unreadable, other_modules}`` is kept in
    ``col.psgallery_summary``.

    Each of the four module folders that exists is listed; a module folder whose version
    folders hold a PSGetModuleInfo.xml is an item keyed
    ``psgallery:<label>|<module folder name case-folded>``, one without counts in
    ``other_modules``. A folder that cannot be looked at (or the Documents folder of the
    ``user-`` ones that cannot be read) keeps its previous items ``from_baseline`` and is
    named in not_checked. ``not_present`` only when every folder was looked at and none
    exists; ``unreadable`` only when no folder was read and one could not be; the count
    is null while any folder is unreadable.
    """
    folders, documents_reason = psgallery_folders()
    items, rows, looked_in, other_modules = {}, [], [], 0
    for label, raw in folders:
        row = {"source": label, "status": "read", "count": None, "reason": None}
        names = None
        if raw is None:
            row.update(status="unreadable", reason=documents_reason)
        else:
            looked_in.append(raw)
            path = expand_path(raw)
            try:
                if path is None or not DISK.exists(path):
                    continue  # absent (or its %VAR% unset)
                names = sorted(DISK.list_dir(path), key=str.casefold)
            except OSError as exc:
                row.update(status="unreadable", reason=(
                    f"{raw} could not be listed: {type(exc).__name__}: {exc}"))
        rows.append(row)
        if names is None:
            col.skip(f"{PSGALLERY_SOURCE} {label}", row["reason"])
            carry(col, PSGALLERY_SOURCE, previous, items,
                  lambda key, label=label: key.startswith(f"psgallery:{label}|"))
            continue
        row["count"] = 0
        for number, module in enumerate(names, 1):
            progress.count(f"{PSGALLERY_SOURCE} {label}", number, len(names))
            try:
                item = psgallery_module(label, raw, path, module)
            except NotADirectoryError:
                continue  # a file beside the module folders
            if item is None:
                other_modules += 1
                continue
            if item["status"] == "unreadable":
                col.skip(f"{PSGALLERY_SOURCE} {label} {module}", item["reason"])
            else:
                row["count"] += 1
            key, suffix = f"psgallery:{label}|{module.casefold()}", 2
            while key in items:  # names differing only in case (a case-sensitive folder)
                key, suffix = f"psgallery:{label}|{module.casefold()}~{suffix}", suffix + 1
            items[key] = item
    read = [row for row in rows if row["status"] == "read"]
    if rows and not read:
        col.record(PSGALLERY_SOURCE, "unreadable", "no PowerShell module folder could be read")
        col.psgallery_summary = {"status": "unreadable", "folders": rows, "count": None,
                                 "unreadable": None, "other_modules": None}
        return "unreadable", items
    col.skip(*PSGALLERY_OUTSIDE)
    if not rows:
        status, items, col.psgallery_summary = not_present(
            col, "psgallery", PSGALLERY_SOURCE, looked_in)
        return status, items
    # A folder that could not be listed is never "nothing there": partly read is read.
    status = "read" if items or len(read) < len(rows) else "empty"
    col.record(PSGALLERY_SOURCE, status, None)
    if other_modules:
        col.skip(*PSGALLERY_OTHER)
    unreadable = sum(1 for item in items.values()
                     if item.get("status") == "unreadable" and not item.get("from_baseline"))
    col.psgallery_summary = {
        "status": status, "folders": rows,
        "count": None if len(read) < len(rows) else sum(row["count"] for row in read),
        "unreadable": unreadable, "other_modules": other_modules}
    return status, items


# Chocolatey: the <id>.nuspec of each package folder of <root>\lib, read through DISK
# (choco does not run).
CHOCO_SOURCE = "choco_packages"
CHOCO_VARIABLE = "ChocolateyInstall"
CHOCO_DEFAULT_ROOT = "%ProgramData%\\chocolatey"
CHOCO_LIB = "\\lib"
CHOCO_OUTSIDE = ("Chocolatey lib-bad and lib-bkp folders",
                 "failed and backed-up installs are not read")
CHOCO_PENDING = ".chocolateyPending"  # left in a package folder while an install runs
CHOCO_INCOMPLETE = ("Chocolatey package folders without a nuspec",
                    "no <folder>.nuspec in the package's folder of lib")


def nuspec_info(text_value: str) -> tuple[tuple | None, str | None]:
    """``((id, version), None)`` of a ``.nuspec``: the text of ``metadata/id`` and
    ``metadata/version`` under the root, any namespace on each element; ``(None,
    reason)`` when the text is not XML or lacks ``id`` or ``version``."""
    try:
        root = ElementTree.fromstring(text_value)
    except (ElementTree.ParseError, ValueError) as exc:
        return None, f"not XML: {type(exc).__name__}: {exc}"

    def local(element) -> str:
        return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""

    metadata = next((child for child in root if local(child) == "metadata"), None)
    found = {}
    for child in metadata if metadata is not None else ():
        if local(child) in ("id", "version") and local(child) not in found:
            found[local(child)] = text((child.text or "").strip())
    missing = [name for name in ("id", "version") if found.get(name) is None]
    if missing:
        return None, f"no {' or '.join(missing)} in metadata"
    return (found["id"], found["version"]), None


def choco_items(col: Collector, path: str, raw: str) -> tuple[dict, int]:
    """``({key: item}, incomplete)`` of the Chocolatey ``lib`` folder ``path`` (``raw``
    unexpanded): each folder (names starting with ``.`` skipped, a file is no package)
    holding ``<folder>\\<folder>.nuspec``; a folder without it is no item and counts in
    ``incomplete``; a folder holding ``.chocolateyPending`` (an unfinished install or
    upgrade) gives an ``unreadable`` item named in not_checked, so it is never reported
    as removed. A folder or nuspec that cannot be read, or a nuspec that does not
    parse, gives an ``unreadable`` item named in not_checked. Key
    ``choco:<folder case-folded>``. ``OSError`` when ``path`` cannot be listed."""
    items, incomplete = {}, 0
    names = sorted(DISK.list_dir(path), key=str.casefold)
    for number, name in enumerate(names, 1):
        progress.count(CHOCO_SOURCE, number, len(names))
        if name.startswith("."):
            continue
        folder = f"{raw}\\{name}"
        nuspec = f"{folder}\\{name}.nuspec"
        item = {"name": name, "version": None, "status": "read", "reason": None,
                "folder": folder}
        reason = None
        try:
            if not is_folder(f"{path}\\{name}"):
                continue  # a file beside the package folders
        except OSError as exc:
            reason = f"{folder} could not be read: {type(exc).__name__}: {exc}"
        else:
            try:
                pending = DISK.exists(f"{path}\\{name}\\{CHOCO_PENDING}")
            except OSError as exc:
                reason = f"{folder} could not be read: {type(exc).__name__}: {exc}"
            else:
                if pending:
                    reason = f"{folder}: {CHOCO_PENDING} present, the install is not finished"
        if reason is None:
            try:
                if not DISK.exists(f"{path}\\{name}\\{name}.nuspec"):
                    incomplete += 1
                    continue
                content = DISK.read_text(f"{path}\\{name}\\{name}.nuspec")
            except (OSError, UnicodeDecodeError) as exc:
                reason = f"{nuspec} could not be read: {type(exc).__name__}: {exc}"
            else:
                fields, bad = nuspec_info(content)
                if fields is None:
                    reason = f"{nuspec}: {bad}"
                else:
                    item["name"], item["version"] = fields
        if reason is not None:
            unreadable_item(item, reason)
            col.skip(f"{CHOCO_SOURCE} {name}", reason)
        key, suffix = f"choco:{name.casefold()}", 2
        while key in items:  # names differing only in case (a case-sensitive folder)
            key, suffix = f"choco:{name.casefold()}~{suffix}", suffix + 1
        items[key] = item
    return items, incomplete


def collect_choco(col: Collector, previous: dict) -> tuple[str, dict]:
    """The Chocolatey packages of ``<root>\\lib`` (``ChocolateyInstall``, non-blank, else
    ``%ProgramData%\\chocolatey``); the part goes to ``col.choco_summary``."""
    progress.step(f"{CHOCO_SOURCE} ...")
    status, items, col.choco_summary = read_store_source(
        col, previous, manager="choco", source=CHOCO_SOURCE, variable=CHOCO_VARIABLE,
        default=CHOCO_DEFAULT_ROOT, tail="", store=CHOCO_LIB,
        read_items=lambda path, raw: choco_items(col, path, raw),
        outside=CHOCO_OUTSIDE, no_version=CHOCO_INCOMPLETE)
    progress.step(f"{CHOCO_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


# Scoop: the apps of the user root and the global root, each app's version from
# apps\<app>\current\manifest.json and its bucket from install.json, read through DISK
# (scoop does not run; the current junction is read through, never resolved).
SCOOP_SOURCE = "scoop_apps"
SCOOP_ROOTS = (("user", "SCOOP", "%USERPROFILE%\\scoop"),
               ("global", "SCOOP_GLOBAL", "%ProgramData%\\scoop"))
SCOOP_APPS = "\\apps"
SCOOP_CORE = "scoop"  # apps\scoop: Scoop's own checkout, no manifest.json
SCOOP_CORE_NOTE = ("Scoop core (apps\\scoop)", "Scoop's own folder is not an app")
SCOOP_INCOMPLETE = ("Scoop apps without a current version",
                    "no current\\manifest.json with a version in the app's folder")


def scoop_bucket(path: str, raw: str) -> tuple[str | None, str | None]:
    """``(bucket, reason)`` of ``<path>\\install.json`` (``raw`` its unexpanded path for
    the reason). A missing file or one without a bucket (older installs have none) is
    ``(None, None)``; a file that could not be read or is not JSON is ``(None, reason)``."""
    try:
        data = json.loads(DISK.read_text(f"{path}\\install.json"))
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{raw} could not be read: {type(exc).__name__}: {exc}"
    except ValueError as exc:
        return None, f"{raw}: not JSON: {type(exc).__name__}: {exc}"
    return (text(data.get("bucket")) if isinstance(data, dict) else None), None


def scoop_app(col: Collector, label: str, raw: str, path: str, app: str) -> dict | None:
    """The item of the app folder ``<path>\\<app>`` (``raw`` unexpanded), or None when it
    has no ``current\\manifest.json`` with a non-blank text ``version`` (incomplete).
    A folder or manifest that cannot be read, or a manifest that is not JSON, gives an
    ``unreadable`` item. An ``install.json`` that could not be read or is not JSON leaves
    ``bucket`` null on a ``read`` item and is named in not_checked.
    ``NotADirectoryError`` when the entry is a file."""
    folder = f"{raw}\\{app}"
    manifest = f"{folder}\\current\\manifest.json"
    current = f"{path}\\{app}\\current"
    item = {"name": app, "version": None, "bucket": None, "root": label,
            "status": "read", "reason": None, "folder": folder}
    try:
        if not is_folder(f"{path}\\{app}"):
            raise NotADirectoryError(f"{path}\\{app}")
        if not DISK.exists(current) or not DISK.exists(f"{current}\\manifest.json"):
            return None
    except NotADirectoryError:
        raise
    except OSError as exc:
        return unreadable_item(item, f"{folder} could not be read: "
                                     f"{type(exc).__name__}: {exc}")
    try:
        data = json.loads(DISK.read_text(f"{current}\\manifest.json"))
    except (OSError, UnicodeDecodeError) as exc:
        return unreadable_item(item, f"{manifest} could not be read: "
                                     f"{type(exc).__name__}: {exc}")
    except ValueError as exc:
        return unreadable_item(item, f"{manifest}: not JSON: {type(exc).__name__}: {exc}")
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version.strip():
        return None
    bucket, bad = scoop_bucket(current, f"{folder}\\current\\install.json")
    if bad is not None:
        col.skip(f"{SCOOP_SOURCE} {label} {app} install.json", f"{bad}; bucket unknown")
    item.update(version=version.strip(), bucket=bucket)
    return item


def collect_scoop(col: Collector, previous: dict) -> tuple[str, dict]:
    """Read the Scoop apps, with a start and an end progress line."""
    progress.step(f"{SCOOP_SOURCE} ...")
    status, items = read_scoop(col, previous)
    progress.step(f"{SCOOP_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def read_scoop(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``scoop_apps``; the summary part
    ``{status, roots, count, unreadable, incomplete}`` is kept in ``col.scoop_summary``.

    Each root (``user``: ``SCOOP``, else ``%USERPROFILE%\\scoop``; ``global``:
    ``SCOOP_GLOBAL``, else ``%ProgramData%\\scoop``) that exists is a row of ``roots``;
    each folder of its ``apps`` (``.`` names, files and Scoop's own ``scoop`` folder
    skipped) is an item keyed ``scoop:<label>|<app folder case-folded>``, one without a
    current version counts in ``incomplete``. A root that cannot be listed keeps its
    previous items ``from_baseline`` and is named in not_checked. ``not_present`` only
    when neither root exists; ``unreadable`` only when no root was read and one could
    not be; the count is null while any root is unreadable.
    """
    items, rows, looked_in, incomplete, core = {}, [], [], 0, False
    for label, variable, default in SCOOP_ROOTS:
        root = environment_value(variable)
        folder_from = variable
        if root is None:
            root, folder_from = default, "default"
        root = root.rstrip("\\/") or root
        looked_in.append(root)
        path = expand_path(root)
        row = {"source": label, "status": "read", "folder_from": folder_from,
               "count": None, "reason": None}
        names = None
        try:
            if not folder_present(path):
                continue  # absent (or its %VAR% unset)
            apps = path + SCOOP_APPS
            names = (sorted(DISK.list_dir(apps), key=str.casefold)
                     if DISK.exists(apps) else [])
        except OSError as exc:
            row.update(status="unreadable", reason=(
                f"{root}{SCOOP_APPS} could not be listed: {type(exc).__name__}: {exc}"))
        rows.append(row)
        if names is None:
            col.skip(f"{SCOOP_SOURCE} {label}", row["reason"])
            carry(col, SCOOP_SOURCE, previous, items,
                  lambda key, label=label: key.startswith(f"scoop:{label}|"))
            continue
        row["count"] = 0
        for number, app in enumerate(names, 1):
            progress.count(f"{SCOOP_SOURCE} {label}", number, len(names))
            if app.startswith("."):
                continue
            if app.casefold() == SCOOP_CORE:
                core = True
                continue
            try:
                item = scoop_app(col, label, root + SCOOP_APPS, apps, app)
            except NotADirectoryError:
                continue  # a file beside the app folders
            if item is None:
                incomplete += 1
                continue
            if item["status"] == "unreadable":
                col.skip(f"{SCOOP_SOURCE} {label} {app}", item["reason"])
            else:
                row["count"] += 1
            key, suffix = f"scoop:{label}|{app.casefold()}", 2
            while key in items:  # names differing only in case (a case-sensitive folder)
                key, suffix = f"scoop:{label}|{app.casefold()}~{suffix}", suffix + 1
            items[key] = item
    if core:
        col.skip(*SCOOP_CORE_NOTE)
    read = [row for row in rows if row["status"] == "read"]
    if rows and not read:
        col.record(SCOOP_SOURCE, "unreadable", "no Scoop root could be read")
        col.scoop_summary = {"status": "unreadable", "roots": rows, "count": None,
                             "unreadable": None, "incomplete": None}
        return "unreadable", items
    if not rows:
        status, items, col.scoop_summary = not_present(col, "scoop", SCOOP_SOURCE,
                                                       looked_in)
        return status, items
    # A root that could not be listed is never "nothing there": partly read is read.
    status = "read" if items or len(read) < len(rows) else "empty"
    col.record(SCOOP_SOURCE, status, None)
    if incomplete:
        col.skip(*SCOOP_INCOMPLETE)
    unreadable = sum(1 for item in items.values()
                     if item.get("status") == "unreadable" and not item.get("from_baseline"))
    col.scoop_summary = {
        "status": status, "roots": rows,
        "count": None if len(read) < len(rows) else sum(row["count"] for row in read),
        "unreadable": unreadable, "incomplete": incomplete}
    return status, items


# vcpkg (classic mode): the status database <root>\installed\vcpkg\status with the
# update files of installed\vcpkg\updates applied after it, read through DISK (vcpkg
# does not run).
VCPKG_SOURCE = "vcpkg_packages"
VCPKG_VARIABLE = "VCPKG_ROOT"
VCPKG_PATH_FILE = "%LOCALAPPDATA%\\vcpkg\\vcpkg.path.txt"  # vcpkg integrate install
VCPKG_PATH_FROM = "vcpkg.path.txt"
VCPKG_STATUS = "\\installed\\vcpkg\\status"
VCPKG_UPDATES = "\\installed\\vcpkg\\updates"
VCPKG_OUTSIDE = ("vcpkg manifest-mode vcpkg_installed folders in projects",
                 "only the classic install's status database is read")
VCPKG_NON_NUMERIC = ("vcpkg update entries with a non-numeric name",
                     "not applied: vcpkg names its update files by digits only")


def vcpkg_paragraphs(content: str) -> list:
    """The paragraphs of a vcpkg status file, each ``{field: value}``: paragraphs are
    separated by blank lines, a line starting with a space or tab continues the previous
    value, a line without ``:`` is skipped."""
    paragraphs, current, last = [], {}, None
    for line in content.splitlines():
        if not line.strip():
            if current:
                paragraphs.append(current)
            current, last = {}, None
        elif line[0] in " \t":
            if last is not None:
                current[last] += "\n" + line.strip()
        else:
            field, sep, value = line.partition(":")
            if sep:
                last = field.strip()
                current[last] = value.strip()
    if current:
        paragraphs.append(current)
    return paragraphs


def vcpkg_root() -> tuple[str | None, str, list, str | None]:
    """``(root, folder_from, looked_in, reason)``: ``VCPKG_ROOT`` (non-blank), else the
    first non-blank line of ``vcpkg.path.txt``; root None when neither names one
    (``looked_in`` the raw places looked at); ``reason`` when the path file exists but
    cannot be read."""
    root = environment_value(VCPKG_VARIABLE)
    if root is not None:
        return root.rstrip("\\/") or root, VCPKG_VARIABLE, [], None
    looked_in = [VCPKG_PATH_FILE]
    path_file = expand_path(VCPKG_PATH_FILE)
    try:
        content = (DISK.read_text(path_file)
                   if path_file is not None and DISK.exists(path_file) else "")
    except (OSError, UnicodeDecodeError) as exc:
        return None, VCPKG_PATH_FROM, looked_in, (
            f"{VCPKG_PATH_FILE} could not be read: {type(exc).__name__}: {exc}")
    root = next((line.strip() for line in content.splitlines() if line.strip()), None)
    if root is None:
        return None, VCPKG_PATH_FROM, looked_in, None
    return root.rstrip("\\/") or root, VCPKG_PATH_FROM, looked_in, None


def vcpkg_database(col: Collector, root: str) -> tuple[list, int]:
    """``(paragraphs, update files applied)``: the status file, then the all-digit files
    of the updates folder in numeric order (other entries named in not_checked). A
    missing status file or updates folder adds nothing. ``OSError`` or
    ``UnicodeDecodeError`` when a file or the updates folder cannot be read."""
    paragraphs = []
    if DISK.exists(root + VCPKG_STATUS):
        paragraphs += vcpkg_paragraphs(DISK.read_text(root + VCPKG_STATUS))
    updates = root + VCPKG_UPDATES
    names = DISK.list_dir(updates) if DISK.exists(updates) else []
    numbered = sorted((name for name in names if name.isascii() and name.isdigit()),
                      key=lambda name: (int(name), name))
    if len(numbered) < len(names):
        col.skip(*VCPKG_NON_NUMERIC)
    for number, name in enumerate(numbered, 1):
        progress.count(VCPKG_SOURCE, number, len(numbered))
        paragraphs += vcpkg_paragraphs(DISK.read_text(f"{updates}\\{name}"))
    return paragraphs, len(numbered)


def collect_vcpkg(col: Collector, previous: dict) -> tuple[str, dict]:
    """Read the vcpkg packages, with a start and an end progress line."""
    progress.step(f"{VCPKG_SOURCE} ...")
    status, items = read_vcpkg(col, previous)
    progress.step(f"{VCPKG_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def read_vcpkg(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``vcpkg_packages``; the summary part
    ``{status, folder_from, count, update_files}`` is kept in ``col.vcpkg_summary``.

    A later paragraph with the same ``(Package, Architecture, Feature)`` replaces an
    earlier one; the items are the paragraphs without ``Feature`` whose ``Status`` ends
    in `` installed``. Key ``vcpkg:<Package>:<Architecture>`` case-folded. No root found
    (or the root absent): ``not_present``; a root without a status file: read, nothing
    there; a file or folder of the database that cannot be read: ``unreadable``, the
    previous items kept ``from_baseline``.
    """
    root, folder_from, looked_in, reason = vcpkg_root()
    try:
        present = folder_present(root)
        paragraphs, update_files = vcpkg_database(col, root) if present else ([], 0)
    except (OSError, UnicodeDecodeError) as exc:
        reason = f"{root}: the status database could not be read: {type(exc).__name__}: {exc}"
    if reason is not None:
        items = carry_source(col, VCPKG_SOURCE, previous, reason)
        col.vcpkg_summary = {"status": "unreadable", "folder_from": folder_from,
                             "count": None, "unreadable": None, "update_files": None}
        return "unreadable", items
    col.skip(*VCPKG_OUTSIDE)
    if not present:
        status, items, col.vcpkg_summary = not_present(
            col, "vcpkg", VCPKG_SOURCE, looked_in + ([root] if root is not None else []))
        return status, items
    latest = {}
    for fields in paragraphs:
        latest[(fields.get("Package"), fields.get("Architecture"),
                fields.get("Feature"))] = fields
    items = {}
    for (package, triplet, feature), fields in latest.items():
        if (not package or not triplet or feature is not None
                or not fields.get("Status", "").endswith(" installed")):
            continue
        version = fields.get("Version")
        port_version = fields.get("Port-Version")
        if version is not None and port_version not in (None, "", "0"):
            version = f"{version}#{port_version}"
        item = {"name": package, "version": version, "triplet": triplet,
                "status": "read", "reason": None,
                "folder": f"{root}\\installed\\{triplet}"}
        if not (version or "").strip():
            bad = f"{package}:{triplet}: no Version in the status database"
            unreadable_item(item, bad)
            col.skip(f"{VCPKG_SOURCE} {package}:{triplet}", bad)
        items[f"vcpkg:{package}:{triplet}".casefold()] = item
    status = "read" if items else "empty"
    col.record(VCPKG_SOURCE, status, None)
    count = sum(1 for item in items.values() if item["status"] == "read")
    col.vcpkg_summary = {"status": status, "folder_from": folder_from, "count": count,
                         "unreadable": len(items) - count, "update_files": update_files}
    return status, items


# Node.js global folders (yarn classic, bun): the dependencies of the global folder's
# package.json are the global packages; each version comes from
# node_modules\<name>\package.json, read through DISK (no yarn or bun command runs).
YARN_SOURCE = "yarn_packages"
YARN_VARIABLE = "YARN_GLOBAL_FOLDER"
YARN_DEFAULT_FOLDER = "%LOCALAPPDATA%\\Yarn\\Data\\global"
YARN_CONFIG = ("yarn global-folder setting in .yarnrc",
               ("the config file is not read; only YARN_GLOBAL_FOLDER and the default are "
                "looked at"))
BUN_SOURCE = "bun_packages"
BUN_GLOBAL_VARIABLE = "BUN_INSTALL_GLOBAL_DIR"
BUN_INSTALL_VARIABLE = "BUN_INSTALL"
BUN_DEFAULT_INSTALL = "%USERPROFILE%\\.bun"
BUN_GLOBAL = "\\install\\global"
BUN_CONFIG = ("bun globalDir setting in bunfig.toml",
              ("the config file is not read; only BUN_INSTALL_GLOBAL_DIR, BUN_INSTALL and "
               "the default are looked at"))
GLOBAL_MANIFEST = "\\package.json"


def global_dependencies(path: str, raw: str) -> tuple[list | None, str | None]:
    """``(names, None)``: the keys of ``dependencies`` in ``<path>\\package.json`` (none
    when the file or the key is absent), or ``(None, reason)`` when the file cannot be
    read, is not a JSON object or its ``dependencies`` is not an object."""
    manifest = path + GLOBAL_MANIFEST
    try:
        if not DISK.exists(manifest):
            return [], None
        data = json.loads(DISK.read_text(manifest))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{raw}{GLOBAL_MANIFEST} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"{raw}{GLOBAL_MANIFEST} does not hold a JSON object"
    dependencies = data.get("dependencies")
    if dependencies is None:
        return [], None
    if not isinstance(dependencies, dict):
        return None, f"{raw}{GLOBAL_MANIFEST}: dependencies is not an object"
    return list(dependencies), None


def global_items(col: Collector, source: str, prefix: str, path: str, raw: str,
                 names: list) -> dict:
    """``{key: item}`` of the global packages ``names`` of the global folder ``path``
    (``raw`` unexpanded): ``name``, ``version`` (the non-blank string ``version`` of
    ``node_modules\\<name>\\package.json``) and the raw ``folder``. A package whose
    ``package.json`` is missing, cannot be read or gives no version is ``unreadable``,
    named in not_checked. Key ``<prefix><name case-folded>``."""
    items = {}
    for number, name in enumerate(names, 1):
        progress.count(source, number, len(names))
        relative = "\\node_modules\\" + name.replace("/", "\\")
        item = {"name": name, "version": None, "status": "read", "reason": None,
                "folder": raw + relative}
        manifest = path + relative + GLOBAL_MANIFEST
        reason = None
        try:
            data = json.loads(DISK.read_text(manifest))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            reason = (f"{item['folder']}{GLOBAL_MANIFEST} could not be read: "
                      f"{type(exc).__name__}: {exc}")
        else:
            version = data.get("version") if isinstance(data, dict) else None
            if isinstance(version, str) and version.strip():
                item["version"] = version.strip()
            else:
                reason = f"{item['folder']}{GLOBAL_MANIFEST} gives no version"
        if reason is not None:
            unreadable_item(item, reason)
            col.skip(f"{source} {name}", reason)
        key, suffix = f"{prefix}{name.casefold()}", 2
        while key in items:  # names differing only in case
            key, suffix = f"{prefix}{name.casefold()}~{suffix}", suffix + 1
        items[key] = item
    return items


def read_global_folder(col: Collector, previous: dict, *, manager: str, source: str,
                       prefix: str, raw: str, folder_from: str, config: tuple,
                       read_names=None, make_items=None) -> tuple[str, dict, dict]:
    """``(status, {key: item}, summary part)`` of the single folder ``raw`` (by default
    a Node.js global folder).

    The folder absent (or its ``%VAR%`` unset): ``not_present``. ``read_names(path,
    raw)`` gives ``(names, None)``, or ``(None, reason)`` when the folder's record cannot
    be read (default ``global_dependencies``); ``make_items(path, raw, names)`` gives
    ``{key: item}`` (default ``global_items``). No item: ``empty``. A folder or record
    that cannot be read: ``unreadable``, the previous items kept ``from_baseline``. The
    part is ``{status, folder_from, count, unreadable}``; ``config`` is named when read
    or not present."""
    read_names = read_names or global_dependencies
    make_items = make_items or (lambda path, raw, names: global_items(
        col, source, prefix, path, raw, names))
    raw = raw.rstrip("\\/") or raw
    path = expand_path(raw)
    try:
        present = folder_present(path)
    except OSError as exc:
        present, names = True, None
        reason = f"{raw} could not be read: {type(exc).__name__}: {exc}"
    else:
        names, reason = read_names(path, raw) if present else ([], None)
    if names is None:
        items = carry_source(col, source, previous, reason)
        return "unreadable", items, {"status": "unreadable", "folder_from": folder_from,
                                     "count": None, "unreadable": None}
    col.skip(*config)
    if not present:
        return not_present(col, manager, source, [raw])
    items = make_items(path, raw, names)
    status = "read" if items else "empty"
    col.record(source, status, None)
    count = sum(1 for item in items.values() if item["status"] == "read")
    return status, items, {"status": status, "folder_from": folder_from, "count": count,
                           "unreadable": len(items) - count}


def collect_yarn(col: Collector, previous: dict) -> tuple[str, dict]:
    """The Yarn classic global packages of ``YARN_GLOBAL_FOLDER`` (non-blank), else
    ``%LOCALAPPDATA%\\Yarn\\Data\\global``. Key ``yarn:<name case-folded>``; the part
    goes to ``col.yarn_summary``."""
    progress.step(f"{YARN_SOURCE} ...")
    raw, folder_from = environment_value(YARN_VARIABLE), YARN_VARIABLE
    if raw is None:
        raw, folder_from = YARN_DEFAULT_FOLDER, "default"
    status, items, col.yarn_summary = read_global_folder(
        col, previous, manager="yarn", source=YARN_SOURCE, prefix="yarn:", raw=raw,
        folder_from=folder_from, config=YARN_CONFIG)
    progress.step(f"{YARN_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def collect_bun(col: Collector, previous: dict) -> tuple[str, dict]:
    """The bun global packages of ``BUN_INSTALL_GLOBAL_DIR`` (non-blank), else
    ``<BUN_INSTALL or %USERPROFILE%\\.bun>\\install\\global``. Key ``bun:<name
    case-folded>``; the part goes to ``col.bun_summary``."""
    progress.step(f"{BUN_SOURCE} ...")
    raw, folder_from = environment_value(BUN_GLOBAL_VARIABLE), BUN_GLOBAL_VARIABLE
    if raw is None:
        install, folder_from = environment_value(BUN_INSTALL_VARIABLE), BUN_INSTALL_VARIABLE
        if install is None:
            install, folder_from = BUN_DEFAULT_INSTALL, "default"
        raw = (install.rstrip("\\/") or install) + BUN_GLOBAL
    status, items, col.bun_summary = read_global_folder(
        col, previous, manager="bun", source=BUN_SOURCE, prefix="bun:", raw=raw,
        folder_from=folder_from, config=BUN_CONFIG)
    progress.step(f"{BUN_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


# cargo: the crates installed with cargo install, from the install root's .crates.toml
# (read with tomllib; no cargo command runs). The source URL is never kept: a path
# install's URL holds a local path.
CARGO_SOURCE = "cargo_packages"
CARGO_ROOT_VARIABLES = ("CARGO_INSTALL_ROOT", "CARGO_HOME")
CARGO_DEFAULT_ROOT = "%USERPROFILE%\\.cargo"
CARGO_RECORD = "\\.crates.toml"
CARGO_CONFIG = ("cargo install.root setting in config.toml",
                ("the config file is not read; only CARGO_INSTALL_ROOT, CARGO_HOME and the "
                 "default are looked at"))
# A .crates.toml key: <name> <version> (<source>).
CRATE_KEY = re.compile(r"(\S+) (\S+) \((.*)\)")
CRATE_NAME = re.compile(r"[A-Za-z0-9_-]+")


def cargo_crate_keys(path: str, raw: str) -> tuple[list | None, str | None]:
    """``(keys, None)``: the keys of ``v1`` in ``<path>\\.crates.toml`` (none when the
    file is absent, empty or only whitespace), or ``(None, reason)`` when it cannot be
    read, is not TOML or its ``v1`` is missing or not a table."""
    record = path + CARGO_RECORD
    try:
        if not DISK.exists(record):
            return [], None
        content = DISK.read_text(record)
        if not content.strip():
            return [], None  # cargo creates it empty and reads it as no installs
        data = tomllib.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{raw}{CARGO_RECORD} could not be read: {type(exc).__name__}: {exc}"
    crates = data.get("v1")
    if not isinstance(crates, dict):
        return None, f"{raw}{CARGO_RECORD}: v1 is missing or not a table"
    return list(crates), None


def cargo_items(col: Collector, raw: str, keys: list) -> dict:
    """``{key: item}`` of the ``.crates.toml`` keys: ``name``, ``version`` (as written)
    and ``source_kind`` (the text before the first ``+`` in the parentheses, or None). A
    key that cannot be split is ``unreadable``, named in not_checked by its first word
    when that is a crate name, else as ``unparsed key <n>`` (the key may hold a source
    URL). Key ``cargo:<name case-folded>``."""
    items = {}
    for number, entry in enumerate(keys, 1):
        progress.count(CARGO_SOURCE, number, len(keys))
        match = CRATE_KEY.fullmatch(entry)
        if match:
            name = match.group(1)
        else:
            first = entry.split(" ")[0]
            name = first if CRATE_NAME.fullmatch(first) else f"unparsed key {number}"
        item = {"name": name, "version": None, "source_kind": None, "status": "read",
                "reason": None, "folder": raw}
        if match:
            item["version"] = match.group(2)
            kind, plus, _ = match.group(3).partition("+")
            item["source_kind"] = kind if plus else None
        else:
            reason = "the .crates.toml key could not be split"
            unreadable_item(item, reason)
            col.skip(f"{CARGO_SOURCE} {name}", reason)
        key, suffix = f"cargo:{name.casefold()}", 2
        while key in items:
            key, suffix = f"cargo:{name.casefold()}~{suffix}", suffix + 1
        items[key] = item
    return items


def collect_cargo(col: Collector, previous: dict) -> tuple[str, dict]:
    """The crates of ``<root>\\.crates.toml``, the root ``CARGO_INSTALL_ROOT``, else
    ``CARGO_HOME`` (non-blank), else ``%USERPROFILE%\\.cargo``. Key ``cargo:<name
    case-folded>``; the part goes to ``col.cargo_summary``."""
    progress.step(f"{CARGO_SOURCE} ...")
    raw, folder_from = CARGO_DEFAULT_ROOT, "default"
    for variable in CARGO_ROOT_VARIABLES:
        if environment_value(variable) is not None:
            raw, folder_from = environment_value(variable), variable
            break
    status, items, col.cargo_summary = read_global_folder(
        col, previous, manager="cargo", source=CARGO_SOURCE, prefix="cargo:", raw=raw,
        folder_from=folder_from, config=CARGO_CONFIG, read_names=cargo_crate_keys,
        make_items=lambda path, raw, keys: cargo_items(col, raw, keys))
    progress.step(f"{CARGO_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


# gem: the specifications\*.gemspec files of every gem folder (part) found: GEM_HOME,
# GEM_PATH, the user gem folders and each Ruby of the uninstall keys (no gem or ruby
# command runs).
GEM_SOURCE = "gem_packages"
GEM_HOME_VARIABLE = "GEM_HOME"
GEM_PATH_VARIABLE = "GEM_PATH"
GEM_USER_BASE = "%USERPROFILE%\\.gem\\ruby"
GEM_XDG_VARIABLE = "XDG_DATA_HOME"
GEM_XDG_DEFAULT = "%USERPROFILE%\\.local\\share"
GEM_XDG_TAIL = "\\gem\\ruby"
GEM_RUBY_TAIL = "\\lib\\ruby\\gems"
GEM_SPECIFICATIONS = "\\specifications"
GEM_SPEC_SUFFIX = ".gemspec"
GEM_DEFAULTS = ("Ruby default gems (specifications\\default)", "they ship with Ruby")
GEM_OTHER_RUBIES = (("Ruby installs outside the uninstall keys (portable, MSYS2, Scoop) and "
                     "uninstall keys without InstallLocation"),
                    ("not searched; only GEM_HOME, GEM_PATH, the user gem folders and the "
                     "Rubies of the uninstall keys are looked at"))
GEM_REGISTRY = "Ruby installs in the uninstall keys"
GEM_STUB = re.compile(r"^# stub: (\S+) (\S+)", re.MULTILINE)
GEM_NAME = re.compile(r"""^\s*s\.name\s*=\s*["']([^"']+)["'](?:\.freeze)?\s*$""",
                      re.MULTILINE)
GEM_VERSION = re.compile(r"""^\s*s\.version\s*=\s*["']([^"']+)["'](?:\.freeze)?\s*$""",
                         re.MULTILINE)
GEM_SEGMENT = re.compile(r"[0-9]+|[a-z]+", re.IGNORECASE)


def gem_segments(version: str) -> list:
    """The canonical segments of a gem version, as ``Gem::Version`` makes them: numbers
    and letter runs, the trailing zeros dropped from the numeric part and from the part
    after the first letter run."""
    segments = [int(s) if s.isdigit() else s for s in GEM_SEGMENT.findall(version)]
    first = next((i for i, s in enumerate(segments) if isinstance(s, str)), len(segments))
    canonical = []
    for chunk in (segments[:first], segments[first:]):
        while chunk and chunk[-1] == 0:
            chunk = chunk[:-1]
        canonical += chunk
    return canonical


def gem_compare(left: str, right: str) -> int:
    """``Gem::Version#<=>``: segment by segment, a missing one is 0 and a letter run
    sorts below a number, so ``1.0.0.pre`` < ``1.0.0``."""
    lhs, rhs = gem_segments(left), gem_segments(right)
    for index in range(max(len(lhs), len(rhs))):
        a = lhs[index] if index < len(lhs) else 0
        b = rhs[index] if index < len(rhs) else 0
        if a == b:
            continue
        if isinstance(a, str) != isinstance(b, str):
            return -1 if isinstance(a, str) else 1
        return -1 if a < b else 1
    return 0


GEM_VERSION_KEY = functools.cmp_to_key(gem_compare)


def gemspec_name_version(content: str) -> tuple[str, str] | None:
    """``(name, version)`` of a gemspec: from its ``# stub:`` line, else from its
    ``s.name`` and ``s.version`` lines; None when neither gives both."""
    stub = GEM_STUB.search(content)
    if stub:
        return stub.group(1), stub.group(2)
    name, version = GEM_NAME.search(content), GEM_VERSION.search(content)
    if name and version:
        return name.group(1).strip(), version.group(1).strip()
    return None


def gem_part_items(col: Collector, label: str, raw: str, path: str) -> tuple[dict, int]:
    """``{key: item}`` of the gem folder ``path`` (``raw`` unexpanded): per gem name the
    highest version of its ``specifications\\*.gemspec`` files and ``versions_found``
    (distinct versions); a gemspec that cannot be read or gives no name and version is
    an ``unreadable`` item keyed by its file name, named in not_checked. No
    ``specifications`` folder: no item. With the items, the number of gemspec files
    not read. ``OSError`` when it cannot be listed."""
    specifications = path + GEM_SPECIFICATIONS
    try:
        names = sorted(DISK.list_dir(specifications), key=str.casefold)
    except (FileNotFoundError, NotADirectoryError):
        return {}, 0
    found, unread, items = {}, [], {}
    files = [name for name in names if name.casefold().endswith(GEM_SPEC_SUFFIX)]
    for number, file_name in enumerate(files, 1):
        progress.count(f"{GEM_SOURCE} {label}", number, len(files))
        stem = file_name[:-len(GEM_SPEC_SUFFIX)]
        shown = f"{raw}{GEM_SPECIFICATIONS}\\{file_name}"
        file_path = f"{specifications}\\{file_name}"
        try:
            parsed = gemspec_name_version(DISK.read_text(file_path))
        except (OSError, UnicodeDecodeError) as exc:
            try:
                folder = DISK.exists(file_path) and not DISK.is_file(file_path)
            except OSError:
                folder = False
            if folder:
                continue  # a folder named *.gemspec is no gemspec
            reason = f"{shown} could not be read: {type(exc).__name__}: {exc}"
        else:
            reason = None if parsed else f"{shown} gives no gem name and version"
        if reason is not None:
            unread.append((stem, reason))
            col.skip(f"{GEM_SOURCE} {label} {stem}", reason)
            continue
        name, version = parsed
        found.setdefault(name.casefold(), []).append((name, version))
    # A gemspec not read whose file name is <name>-<version...> of a gem read may hold
    # its highest version: that gem's version is unknown, never an older one.
    unknown, entries = {}, []
    for stem, reason in unread:
        owner = next((folded for folded in found
                      if stem.casefold().startswith(folded + "-")
                      and stem[len(folded) + 1:][:1].isdigit()), None)
        if owner is None:
            entries.append(unreadable_item(
                {"name": stem, "versions_found": None, "gem_dir": label, "status": "read",
                 "reason": None, "folder": raw}, reason))
        else:
            unknown.setdefault(owner, reason)
    for folded, value in found.items():
        name, version = max(value, key=lambda nv: (GEM_VERSION_KEY(nv[1]), nv[1]))
        item = {"name": name, "version": version,
                "versions_found": len({v for _, v in value}), "gem_dir": label,
                "status": "read", "reason": None, "folder": raw}
        if folded in unknown:
            unreadable_item(item, unknown[folded])
        entries.append(item)
    for item in entries:
        name = item["name"]
        key, suffix = f"gem:{label}|{name.casefold()}", 2
        while key in items:
            key, suffix = f"gem:{label}|{name.casefold()}~{suffix}", suffix + 1
        items[key] = item
    return items, len(unread)


def next_label(name: str, used: set) -> str:
    """``name``, else ``name~2``, ``name~3``... the first one not in ``used`` (added)."""
    label, number = name, 1
    while label in used:
        number += 1
        label = f"{name}~{number}"
    used.add(label)
    return label


def gem_candidates() -> tuple[list, list, str | None]:
    """``(candidates, looked_in, registry reason)``. Each candidate is ``(kind, label,
    raw)`` in part order: kind ``part`` (a gem folder) or ``parent`` (a folder whose
    subfolders ``<abi>`` are gem folders, ``label`` its label prefix)."""
    candidates, looked_in = [], []
    home = environment_value(GEM_HOME_VARIABLE)
    if home is not None:
        candidates.append(("part", "GEM_HOME", home))
        looked_in.append(home)
    entries = [entry.strip() for entry in (environment_value(GEM_PATH_VARIABLE) or "")
               .split(";") if entry.strip()]
    for number, entry in enumerate(entries, 1):
        candidates.append(("part", f"GEM_PATH-{number}", entry))
        looked_in.append(entry)
    xdg = environment_value(GEM_XDG_VARIABLE) or GEM_XDG_DEFAULT
    for prefix, raw in (("user", GEM_USER_BASE),
                        ("xdg", (xdg.rstrip("\\/") or xdg) + GEM_XDG_TAIL)):
        candidates.append(("parent", prefix, raw))
        looked_in.append(raw)
    try:
        rubies = DISK.ruby_install_locations()
    except OSError as exc:
        # PartlyReadError: the Rubys of the keys that were read are still parts.
        rubies = list(getattr(exc, "found", None) or [])
        reason = f"the uninstall keys could not be read: {type(exc).__name__}: {exc}"
    else:
        reason = None
    for location in rubies:
        location = text(location)
        if location is None:
            continue
        raw = (location.strip().rstrip("\\/") or location.strip()) + GEM_RUBY_TAIL
        candidates.append(("parent", "ruby", raw))
        looked_in.append(raw)
    return candidates, looked_in, reason


def collect_gem(col: Collector, previous: dict) -> tuple[str, dict]:
    """Read the Ruby gems, with a start and an end progress line."""
    progress.step(f"{GEM_SOURCE} ...")
    status, items = read_gem(col, previous)
    progress.step(f"{GEM_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def read_gem(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``gem_packages``; the summary part
    ``{status, parts, count, unreadable}`` is kept in ``col.gem_summary``.

    The parts, in order: ``GEM_HOME``, each ``GEM_PATH`` entry (``GEM_PATH-<n>``), each
    subfolder ``<abi>`` of ``%USERPROFILE%\\.gem\\ruby`` (``user-<abi>``), of
    ``<XDG_DATA_HOME, else %USERPROFILE%\\.local\\share>\\gem\\ruby`` (``xdg-<abi>``) and
    of ``<InstallLocation>\\lib\\ruby\\gems`` of each Ruby of the uninstall keys
    (``ruby-<abi>``); a label already used gets ``~2``, ``~3``, a folder already a part
    is skipped. A part, or a parent folder (labelled ``user``, ``xdg``, ``ruby``), that
    exists but cannot be listed is an ``unreadable`` part: its previous items are kept
    ``from_baseline`` (never over an item of this run, never of a label read in this
    run) and the count is null. Uninstall keys that cannot be read are named in
    not_checked and keep the previous ``ruby-`` items the same way. ``not_present``
    only when no part exists and the keys were read; ``unreadable`` only when no part
    was read and one (or the keys) could not be.
    """
    candidates, looked_in, registry_reason = gem_candidates()
    col.skip(*GEM_OTHER_RUBIES)
    items, rows, used, seen, kept, unread_files = {}, [], set(), set(), [], 0
    queue = list(candidates)
    while queue:
        kind, name, raw = queue.pop(0)
        path = expand_path(raw)
        try:
            present = folder_present(path)
        except OSError as exc:
            if kind == "listed" and isinstance(exc, NotADirectoryError):
                continue  # a file beside the <abi> folders
            present, error = True, f"{raw} could not be listed: {type(exc).__name__}: {exc}"
        else:
            error = None
        if not present:
            continue
        if error is None and kind == "parent":
            try:
                subfolders = sorted(DISK.list_dir(path), key=str.casefold)
            except OSError as exc:
                error = f"{raw} could not be listed: {type(exc).__name__}: {exc}"
            else:
                queue[0:0] = [("listed", f"{name}-{abi}", f"{raw}\\{abi}")
                              for abi in subfolders]
                continue
        place = (kind == "parent", same_folder(path))
        if place in seen:
            continue  # a folder already looked at (GEM_HOME equal to a Ruby's gem folder)
        seen.add(place)
        label = next_label(name, used)
        row = {"source": label, "status": "read", "count": None, "reason": None}
        rows.append(row)
        if error is None:
            try:
                found, unread = gem_part_items(col, label, raw, path)
            except OSError as exc:
                error = (f"{raw}{GEM_SPECIFICATIONS} could not be listed: "
                         f"{type(exc).__name__}: {exc}")
            else:
                row["count"] = sum(1 for item in found.values() if item["status"] == "read")
                items.update(found)
                unread_files += unread
                continue
        row.update(status="unreadable", reason=error)
        col.skip(f"{GEM_SOURCE} {label}", error)
        kept.append(f"gem:{label}|" if kind != "parent" else f"gem:{name}-")
    if registry_reason is not None:
        col.skip(GEM_REGISTRY, registry_reason)
        kept.append("gem:ruby-")
    read_labels = {row["source"] for row in rows if row["status"] == "read"}
    carry(col, GEM_SOURCE, previous, items, lambda key: (
        key not in items and any(key.startswith(prefix) for prefix in kept)
        and key[len("gem:"):].split("|", 1)[0] not in read_labels))
    read = [row for row in rows if row["status"] == "read"]
    if not read and (rows or registry_reason is not None):
        if rows:
            col.record(GEM_SOURCE, "unreadable", "no gem folder could be read")
        else:  # the keys are the only thing not read, already named in not_checked
            col.sources.append({"name": GEM_SOURCE, "status": "unreadable",
                                "reason": registry_reason})
        col.gem_summary = {"status": "unreadable", "parts": rows, "count": None,
                           "unreadable": None}
        return "unreadable", items
    if not rows:
        status, items, col.gem_summary = not_present(col, "gem", GEM_SOURCE, looked_in)
        return status, items
    # A part that could not be read is never "nothing there": partly read is read.
    status = ("read" if items or len(read) < len(rows) or registry_reason is not None
              else "empty")
    col.record(GEM_SOURCE, status, None)
    col.skip(*GEM_DEFAULTS)
    col.gem_summary = {
        "status": status, "parts": rows,
        "count": (None if len(read) < len(rows) or registry_reason is not None
                  else sum(row["count"] for row in read)),
        "unreadable": unread_files}
    return status, items


# composer: the global packages are the require keys (with a "/") of the global
# composer.json, each version from vendor\composer\installed.json (no composer or php
# command runs).
COMPOSER_SOURCE = "composer_packages"
COMPOSER_VARIABLE = "COMPOSER_HOME"
COMPOSER_DEFAULT_HOME = "%APPDATA%\\Composer"
COMPOSER_MANIFEST = "\\composer.json"
COMPOSER_INSTALLED = "\\vendor\\composer\\installed.json"
COMPOSER_CONFIG = (("composer vendor-dir setting (config.json, COMPOSER_VENDOR_DIR) and "
                    "COMPOSER"),
                   "only <home>\\vendor and composer.json are read")


NOT_INSTALLED = object()  # a require key with no installed.json entry


def composer_installed(path: str, raw: str) -> tuple[dict | None, str | None]:
    """``({name case-folded: version}, None)`` of ``installed.json`` (an object with a
    ``packages`` list, Composer 2, or a bare list, Composer 1; ``{}`` when it is
    absent), or ``(None, reason)`` when it cannot be read or has neither shape."""
    installed = path + COMPOSER_INSTALLED
    try:
        if not DISK.exists(installed):
            return {}, None
        data = json.loads(DISK.read_text(installed))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, (f"{raw}{COMPOSER_INSTALLED} could not be read: "
                      f"{type(exc).__name__}: {exc}")
    entries = data.get("packages") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return None, f"{raw}{COMPOSER_INSTALLED} holds neither a packages list nor a list"
    return {entry["name"].casefold(): entry.get("version") for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)}, None


def composer_globals(path: str, raw: str) -> tuple[list | None, str | None]:
    """``([(name, version or None), ...], None)``: the ``require`` keys holding ``/`` of
    ``<path>\\composer.json`` (none when the file or the key is absent), each with its
    ``installed.json`` entry's version, or ``(None, reason)`` when either file cannot be
    read or has another shape."""
    manifest = path + COMPOSER_MANIFEST
    try:
        if not DISK.exists(manifest):
            return [], None
        data = json.loads(DISK.read_text(manifest))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{raw}{COMPOSER_MANIFEST} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"{raw}{COMPOSER_MANIFEST} does not hold a JSON object"
    require = data.get("require")
    if require is None:
        return [], None
    if not isinstance(require, dict):
        return None, f"{raw}{COMPOSER_MANIFEST}: require is not an object"
    names = [name for name in require if "/" in name]  # others are platform requirements
    if not names:
        return [], None
    versions, reason = composer_installed(path, raw)
    if versions is None:
        return None, reason
    return [(name, versions.get(name.casefold(), NOT_INSTALLED)) for name in names], None


def composer_items(col: Collector, raw: str, globals_: list) -> dict:
    """``{key: item}`` of the global packages: ``name`` and ``version`` (the non-blank
    string version of its ``installed.json`` entry); a package with none is
    ``unreadable``, named in not_checked. Key ``composer:<name case-folded>``."""
    items = {}
    for number, (name, version) in enumerate(globals_, 1):
        progress.count(COMPOSER_SOURCE, number, len(globals_))
        item = {"name": name, "version": None, "status": "read", "reason": None,
                "folder": f"{raw}\\vendor\\{name.replace('/', '\\')}"}
        if isinstance(version, str) and version.strip():
            item["version"] = version.strip()
        else:
            reason = (f"{name} is not in {raw}{COMPOSER_INSTALLED}"
                      if version is NOT_INSTALLED
                      else f"{name} gives no version in {raw}{COMPOSER_INSTALLED}")
            unreadable_item(item, reason)
            col.skip(f"{COMPOSER_SOURCE} {name}", reason)
        key, suffix = f"composer:{name.casefold()}", 2
        while key in items:
            key, suffix = f"composer:{name.casefold()}~{suffix}", suffix + 1
        items[key] = item
    return items


def collect_composer(col: Collector, previous: dict) -> tuple[str, dict]:
    """The global Composer packages of ``COMPOSER_HOME`` (non-blank), else
    ``%APPDATA%\\Composer``. Key ``composer:<name case-folded>``; the part goes to
    ``col.composer_summary``."""
    progress.step(f"{COMPOSER_SOURCE} ...")
    raw, folder_from = environment_value(COMPOSER_VARIABLE), COMPOSER_VARIABLE
    if raw is None:
        raw, folder_from = COMPOSER_DEFAULT_HOME, "default"
    status, items, col.composer_summary = read_global_folder(
        col, previous, manager="composer", source=COMPOSER_SOURCE, prefix="composer:",
        raw=raw, folder_from=folder_from, config=COMPOSER_CONFIG,
        read_names=composer_globals,
        make_items=lambda path, raw, globals_: composer_items(col, raw, globals_))
    progress.step(f"{COMPOSER_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


# pnpm: each layout folder <home>\global\<digits> is read as one Node.js global folder
# (no pnpm command runs; node_modules\<name> is pnpm's junction into .pnpm, read through).
PNPM_SOURCE = "pnpm_packages"
PNPM_VARIABLE = "PNPM_HOME"
PNPM_DEFAULT_HOME = "%LOCALAPPDATA%\\pnpm"
PNPM_GLOBAL = "\\global"
PNPM_CONFIG = ("pnpm global-dir setting in the pnpm rc file",
               ("the config file is not read; only PNPM_HOME and the default are "
                "looked at"))
PNPM_NON_NUMERIC = ("pnpm global entries with a non-numeric name",
                    ("not read: pnpm names its global layout folders by digits only"))


def pnpm_order(name: str) -> tuple:
    """Sort key of a global folder entry: all-digit names first, by number."""
    numeric = name.isascii() and name.isdigit()
    return (not numeric, int(name) if numeric else 0, name.casefold())


def collect_pnpm(col: Collector, previous: dict) -> tuple[str, dict]:
    """Read the pnpm global packages, with a start and an end progress line."""
    progress.step(f"{PNPM_SOURCE} ...")
    status, items = read_pnpm(col, previous)
    progress.step(f"{PNPM_SOURCE} {'failed' if status == 'unreadable' else 'done'}")
    return status, items


def read_pnpm(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``pnpm_packages``; the summary part
    ``{status, folder_from, parts, count, unreadable}`` is kept in ``col.pnpm_summary``.

    The global folder is ``<PNPM_HOME (non-blank), else %LOCALAPPDATA%\\pnpm>\\global``;
    absent (or its ``%VAR%`` unset): ``not_present``; one that cannot be listed:
    ``unreadable``, the previous items kept ``from_baseline``. Each of its folders with
    an all-digit name is one part (a row of ``parts``, labelled by the digits), read as
    one global folder; every other entry is named once in not_checked. Key
    ``pnpm:<label>|<name case-folded>``, with ``layout`` the label. A part whose
    ``package.json`` cannot be read keeps its previous items ``from_baseline``;
    ``unreadable`` only when no part was read and one could not be; the count is null
    while any part is unreadable.
    """
    home, folder_from = environment_value(PNPM_VARIABLE), PNPM_VARIABLE
    if home is None:
        home, folder_from = PNPM_DEFAULT_HOME, "default"
    raw = (home.rstrip("\\/") or home) + PNPM_GLOBAL
    path = expand_path(raw)
    try:
        present = folder_present(path)
        names = sorted(DISK.list_dir(path), key=pnpm_order) if present else []
    except OSError as exc:
        items = carry_source(col, PNPM_SOURCE, previous,
                             f"{raw} could not be listed: {type(exc).__name__}: {exc}")
        col.pnpm_summary = {"status": "unreadable", "folder_from": folder_from,
                            "parts": None, "count": None, "unreadable": None}
        return "unreadable", items
    if not present:
        col.skip(*PNPM_CONFIG)
        status, items, col.pnpm_summary = not_present(col, "pnpm", PNPM_SOURCE, [raw])
        return status, items
    items, rows, other = {}, [], False
    for label in names:
        part_path, part_raw = f"{path}\\{label}", f"{raw}\\{label}"
        row = {"source": label, "status": "read", "count": None, "reason": None}
        try:
            if not (label.isascii() and label.isdigit()) or not is_folder(part_path):
                other = True
                continue
        except OSError as exc:
            dependencies = None
            reason = f"{part_raw} could not be listed: {type(exc).__name__}: {exc}"
        else:
            dependencies, reason = global_dependencies(part_path, part_raw)
        rows.append(row)
        prefix = f"pnpm:{label}|"
        if dependencies is None:
            row.update(status="unreadable", reason=reason)
            col.skip(f"{PNPM_SOURCE} {label}", reason)
            carry(col, PNPM_SOURCE, previous, items,
                  lambda key, prefix=prefix: key.startswith(prefix))
            continue
        found = global_items(col, f"{PNPM_SOURCE} {label}", prefix, part_path, part_raw,
                             dependencies)
        for item in found.values():
            item["layout"] = label
        row["count"] = sum(1 for item in found.values() if item["status"] == "read")
        items.update(found)
    if other:
        col.skip(*PNPM_NON_NUMERIC)
    read = [row for row in rows if row["status"] == "read"]
    if rows and not read:
        col.record(PNPM_SOURCE, "unreadable", "no pnpm global layout folder could be read")
        col.pnpm_summary = {"status": "unreadable", "folder_from": folder_from,
                            "parts": rows, "count": None, "unreadable": None}
        return "unreadable", items
    col.skip(*PNPM_CONFIG)
    # A part that could not be read is never "nothing there": partly read is read.
    status = "read" if items or len(read) < len(rows) else "empty"
    col.record(PNPM_SOURCE, status, None)
    unreadable = sum(1 for item in items.values()
                     if item.get("status") == "unreadable" and not item.get("from_baseline"))
    col.pnpm_summary = {
        "status": status, "folder_from": folder_from, "parts": rows,
        "count": None if len(read) < len(rows) else sum(row["count"] for row in read),
        "unreadable": unreadable}
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


def manager_state(status: str | None, present: bool = True) -> str:
    """``not_present`` when the collector found none of the manager's locations
    (``present`` false), else ``read`` for a source read (with or without packages),
    else ``unreadable``. The status alone never gives ``not_present``: a source read
    with no package is ``empty`` too."""
    if not present:
        return "not_present"
    return "read" if status in READ_STATUSES else "unreadable"


def build_managers(col: Collector) -> dict:
    """``{name: entry}`` in the order of ``data/managers.json``: each read manager
    with its state and summary part (``{state: "not_present", looked_in}`` when none of
    its locations exists), every other manager ``{state: "not_read"}`` with one
    not_checked entry ``<name>: not read yet``. Without a readable file, the read
    managers only, and the file is named in not_checked."""
    read_parts = {"pip": col.pip_summary, "npm": col.npm_summary,
                  "pipx": col.pipx_summary, "uv": col.uv_summary,
                  "conda": col.conda_summary, "winget": col.winget_summary,
                  "vscode": col.vscode_summary, "dotnet-tools": col.dotnet_tools_summary,
                  "nuget": col.nuget_summary, "psgallery": col.psgallery_summary,
                  "choco": col.choco_summary, "scoop": col.scoop_summary,
                  "vcpkg": col.vcpkg_summary, "pnpm": col.pnpm_summary,
                  "yarn": col.yarn_summary,
                  "bun": col.bun_summary, "cargo": col.cargo_summary,
                  "gem": col.gem_summary, "composer": col.composer_summary}
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
        elif name in col.not_present:
            managers[name] = {"state": manager_state(part["status"], present=False),
                              "looked_in": part["looked_in"]}
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
    statuses["pipx_packages"], current["pipx_packages"] = collect_pipx(
        col, previous.get("pipx_packages") or {})
    statuses["uv_tools"], current["uv_tools"] = collect_uv(
        col, previous.get("uv_tools") or {})
    statuses["conda_packages"], current["conda_packages"] = collect_conda(
        col, previous.get("conda_packages") or {})
    statuses["winget_packages"], current["winget_packages"] = collect_winget(
        col, previous.get("winget_packages") or {})
    statuses["vscode_extensions"], current["vscode_extensions"] = collect_vscode(
        col, previous.get("vscode_extensions") or {})
    statuses["dotnet_tools"], current["dotnet_tools"] = collect_dotnet_tools(
        col, previous.get("dotnet_tools") or {})
    statuses["nuget_packages"], current["nuget_packages"] = collect_nuget(
        col, previous.get("nuget_packages") or {})
    statuses["psgallery_modules"], current["psgallery_modules"] = collect_psgallery(
        col, previous.get("psgallery_modules") or {})
    statuses["choco_packages"], current["choco_packages"] = collect_choco(
        col, previous.get("choco_packages") or {})
    statuses["scoop_apps"], current["scoop_apps"] = collect_scoop(
        col, previous.get("scoop_apps") or {})
    statuses["vcpkg_packages"], current["vcpkg_packages"] = collect_vcpkg(
        col, previous.get("vcpkg_packages") or {})
    statuses["pnpm_packages"], current["pnpm_packages"] = collect_pnpm(
        col, previous.get("pnpm_packages") or {})
    statuses["yarn_packages"], current["yarn_packages"] = collect_yarn(
        col, previous.get("yarn_packages") or {})
    statuses["bun_packages"], current["bun_packages"] = collect_bun(
        col, previous.get("bun_packages") or {})
    statuses["cargo_packages"], current["cargo_packages"] = collect_cargo(
        col, previous.get("cargo_packages") or {})
    statuses["gem_packages"], current["gem_packages"] = collect_gem(
        col, previous.get("gem_packages") or {})
    statuses["composer_packages"], current["composer_packages"] = collect_composer(
        col, previous.get("composer_packages") or {})
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
    """Every change of a compared source in ``SOURCES`` order, each source added, removed,
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
            elif source == "pipx_packages":
                entry["venv"] = item.get("venv")
            elif source == "conda_packages":
                entry["environment"] = item.get("environment")
            elif source == "winget_packages":
                # ``source`` stays the source name; the catalog label is ``catalog``.
                entry["catalog"] = item.get("source")
            elif source == "psgallery_modules":
                # ``source`` stays the source name; the folder label is ``module_folder``.
                entry["module_folder"] = item.get("module_folder")
                entry["repository"] = item.get("repository")
            elif source == "scoop_apps":
                # ``source`` stays the source name; the root label is ``root``.
                entry["root"] = item.get("root")
                entry["bucket"] = item.get("bucket")
            elif source == "vcpkg_packages":
                entry["triplet"] = item.get("triplet")
            elif source == "pnpm_packages":
                entry["layout"] = item.get("layout")
            elif source == "cargo_packages":
                entry["source_kind"] = item.get("source_kind")
            elif source == "gem_packages":
                # ``source`` stays the source name; the gem folder label is ``gem_dir``.
                entry["gem_dir"] = item.get("gem_dir")
            if fields is not None:
                entry["fields"] = fields
            else:
                entry["version"] = item.get("version")
            changes.append(entry)
    numbering.assign("c", changes)
    return [{"id": entry.pop("id"), **entry} for entry in changes]


# --- packages ------------------------------------------------------------------
def build_packages(current: dict, numbering) -> list:
    """Every package of the read managers (pip, npm, pipx, uv, conda, winget, vscode,
    dotnet-tools, nuget, psgallery, choco, scoop, vcpkg, pnpm, yarn, bun, cargo,
    gem, composer), each
    by key; ids ``k<n>`` from ``numbering``. The full item of the source, with ``manager`` and ``key``."""
    packages = []
    for manager, source in READ_MANAGERS.items():
        for key, item in sorted((current.get(source) or {}).items()):
            packages.append({"manager": manager, "key": key, **copy.deepcopy(item)})
    numbering.assign("k", packages)
    return [{"id": item.pop("id"), **item} for item in packages]


def summary_package(item: dict) -> dict:
    """The summary form of a package: ``id``, ``manager``, ``key``, ``name``,
    ``version``, the Python (pip), the venv and ``injected`` (pipx), the environment
    (conda), the catalog label ``source`` (winget), ``versions_found`` (dotnet-tools,
    nuget, psgallery), ``module_folder`` and ``repository`` (psgallery), ``root`` and
    ``bucket`` (scoop), ``triplet`` (vcpkg), ``layout`` (pnpm), ``source_kind`` (cargo),
    ``versions_found`` and ``gem_dir`` (gem) and ``folder``; ``unreadable`` and ``reason`` when its metadata could not be read, ``from_baseline`` when it was kept from the
    baseline because its folder could not be listed (winget: its catalog could not be
    read, or had rows without an id)."""
    out = {"id": item["id"], "manager": item["manager"], "key": item["key"],
           "name": item.get("name"), "version": item.get("version")}
    if item["manager"] == "pip":
        out["python"] = item.get("python")
    elif item["manager"] == "pipx":
        out["venv"] = item.get("venv")
        out["injected"] = item.get("injected")
    elif item["manager"] == "conda":
        out["environment"] = item.get("environment")
    elif item["manager"] == "winget":
        out["source"] = item.get("source")
    elif item["manager"] in ("dotnet-tools", "nuget"):
        out["versions_found"] = item.get("versions_found")
    elif item["manager"] == "psgallery":
        out["versions_found"] = item.get("versions_found")
        out["module_folder"] = item.get("module_folder")
        out["repository"] = item.get("repository")
    elif item["manager"] == "scoop":
        out["root"] = item.get("root")
        out["bucket"] = item.get("bucket")
    elif item["manager"] == "vcpkg":
        out["triplet"] = item.get("triplet")
    elif item["manager"] == "pnpm":
        out["layout"] = item.get("layout")
    elif item["manager"] == "cargo":
        out["source_kind"] = item.get("source_kind")
    elif item["manager"] == "gem":
        out["versions_found"] = item.get("versions_found")
        out["gem_dir"] = item.get("gem_dir")
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
        **{source: [{"key": key, **item} for key, item in sorted(current[source].items())]
           for source in SOURCES},
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

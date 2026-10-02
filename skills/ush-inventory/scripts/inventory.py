"""List what is installed on this machine and compare it with the saved baseline
(read-only).

Sources (one read-only PowerShell job each, run through an injectable ``run_ps``;
see ``skills/ush-common/scripts/psrun.py``):

- ``win32_programs``: the ``Uninstall`` keys of ``HKLM`` (64-bit view),
  ``HKLM\\SOFTWARE\\WOW6432Node`` and ``HKCU``; only subkeys with a ``DisplayName``
  become items.
- ``msix_programs``: ``Get-AppxPackage -PackageTypeFilter Main`` of the current
  account; of two packages of one family the higher ``Version`` stays.
- ``run_keys``: ``Run`` and ``RunOnce`` of ``HKCU``, ``HKLM`` and
  ``HKLM\\SOFTWARE\\WOW6432Node`` (raw values, not expanded).
- ``startup_folders``: the ``Startup`` and ``CommonStartup`` folders; a ``.lnk``
  is read through ``WScript.Shell`` (never saved).
- ``startup_approved``: ``Explorer\\StartupApproved`` (``Run``, ``Run32``,
  ``StartupFolder``) of ``HKCU`` and ``HKLM``; it gives no items, only the
  ``approved`` and ``enabled`` fields of the ``run_keys`` and
  ``startup_folders`` entries.
- ``scheduled_tasks``: ``Get-ScheduledTask``, only tasks with a logon or boot
  trigger.
- ``services``: ``Win32_Service`` with ``StartMode`` ``Auto``, with ``Type``,
  ``DelayedAutostart`` and ``ServiceDll`` from the registry; the instances of a
  per-user service are one entry keyed by the template name.
- ``file_facts``: one more job gets the target files of all autostart entries
  (``target_path``) in a JSON file and answers, per file, its expanded path,
  whether it exists, its Authenticode status, the ``O=`` of the signer and the
  company of its version info; next to them the expanded ``%ProgramFiles%``,
  ``%ProgramFiles(x86)%``, ``%SystemRoot%`` and ``System32``.
- ``optional_features``: ``Win32_OptionalFeature`` (works without administrator
  rights); ``InstallState`` 1, 2, 3 is ``enabled``, ``disabled``, ``absent``, any
  other value is ``state`` null, named in ``unread_fields``, with ``install_state``.
- ``capabilities``: ``Get-WindowsCapability -Online``, only with administrator
  rights; without them the job is not run and the source is unreadable
  (``requires administrator``), never empty.
- ``drivers``: ``Win32_PnPSignedDriver``, one entry per device; a row without
  ``InfName`` (a device without a driver) is no entry, only counted in
  ``component_counts.drivers_without_inf``. A ``removed`` driver is a device that
  is not present now (e.g. unplugged), not an uninstalled driver.
- ``firewall_rules``: the rule values of the ``FirewallRules`` keys of the local
  store (``local``), of Store apps (``app_iso``) and of the policy (``policy``);
  a missing key is no rules, a key that cannot be read fails the source. The
  rule text is split by ``parse_firewall_rule``.
- ``root_certificates``: the thumbprint subkeys of five physical root stores in
  the registry (``machine_root``, ``machine_policy``, ``enterprise``,
  ``user_root``, ``authroot``), with subject, issuer and dates from ``Cert:``.
- ``hosts``: the ``hosts`` file in ``Tcpip\\Parameters\\DataBasePath``, split by
  ``parse_hosts``; a missing file is read and holds no entries.
- ``administrators``: ``Get-LocalGroupMember -SID S-1-5-32-544`` (``Enabled``
  from ``Get-LocalUser`` for local and Microsoft accounts), else ADSI
  (``method: adsi``).
- ``defender_exclusions``: only with administrator rights; ``Get-MpPreference``
  (``method: preference``), else the ``Exclusions`` registry keys
  (``method: registry``); each entry has ``origin`` ``policy`` or ``local``. A
  value hidden by Defender (``N/A: ...``) makes the source unreadable.

Every item has a stable key (``win32:<hive>:<subkey>``, ``msix:<family>``,
``run:<hive>\\<Run|RunOnce>:<name>``, ``startup:<user|common>:<file>``,
``task:<path><name>``, ``service:<name or template>``, ``feature:<Name>``,
``capability:<Name>``, ``driver:<DeviceID>``, ``firewall:<store>:<value name>``,
``cert:<store>:<THUMBPRINT>``, ``hosts:<host name, lower case>:<address>``,
``admin:<SID>``, ``defender:<path|extension|process|ip>:<value, lower case>``).
The items are compared
with the baseline in ``<data dir>/state/`` (``baseline.py``):
``ush-inventory.json``, or ``ush-inventory.elevated.json`` for a run with
administrator rights. A source that was not read keeps its previous items and
gives no changes. A field derived from a source that was not read (``approved``
and ``enabled`` from ``startup_approved``, ``facts`` from ``file_facts``) is
taken from the previous baseline by the entry key; without a previous value it
is null and named in the entry's ``unread_fields``, and such a field is never
compared.

The only classification is the data file ``data/windows-own.json``: an MSIX app
whose signature kind it lists is part of Windows (``own: true``), and so is a
service or task (``own_kinds``) whose every target exists, is ``Valid``, is
signed by a listed organisation and is no launcher. Such items are counted in
the summary and listed only in the detail file; their changes are counted in
``own_changes``. ``Run`` and Startup entries and Win32 programs are never own.
An entry whose facts could not be read has ``own: null`` and is counted in
``own_counts.unknown``. A driver whose ``InfName`` matches a pattern of
``driver_third_party_inf`` is ``third_party`` and listed; any other driver is
own. Components (features and capabilities) are never own, so every change of
one is listed. A firewall rule with every field of ``firewall_builtin`` and a
``Name`` that starts with its prefix is own; a root certificate is own in a
store of ``cert_windows_managed_stores``, or in ``machine_root`` with a
thumbprint of ``cert_windows_shipped_thumbprints``, or trusted by the decision
of the first run that read it, kept per entry of ``cert_windows_first_run`` in
``state/ush-inventory.first-run.json`` (``windows_first_run``); hosts entries,
Administrators members and Defender exclusions are never own. The items of these
five sources that are not own are listed in ``additions`` (ids ``x..``).
``own_changes.by_source`` splits the own-only changes by source.
The script counts; it never judges.

The summary goes to stdout and to ``work/inventory-<UTC stamp>.summary.json``;
the detail file ``work/inventory-<UTC stamp>.detail.json`` holds every program,
every autostart entry, every component, every driver, every addition and every
change with the same ids. ``--detail <id>`` prints one item of the newest detail
file. To keep the summary within ``SUMMARY_MAX_CHARS`` four lists are cut from
their end: ``programs`` (``truncated``; programs without an install date, then
the oldest installs) down to ``PROGRAMS_MIN``, then ``drivers``
(``truncated_drivers``), ``components`` (``truncated_components``) and
``additions`` (``truncated_additions``; the items without a change block in
SKILL.md first, then the ones with a block), each only after the one before is
empty, and only then ``programs`` below ``PROGRAMS_MIN``. A listed
program and autostart entry in the summary lack some fields the report does not
use (``install_location``, ``display_name``, a fact's ``company``, ...); the
detail file and the baseline keep the full items, and the comparison uses them.
"""

import argparse
import copy
import fnmatch
import json
import ntpath
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

# The shared modules live in skills/ush-common/scripts.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline  # called as baseline.save(...), so tests can patch it
import datadir
import psrun
from psrun import dump, ps_script, run_job

SKILL = "ush-inventory"
FIRST_RUN_FILE = "ush-inventory.first-run.json"
FIRST_RUN_SCHEMA = 1
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
DETAIL_SECTIONS = ("programs", "autostart", "components", "drivers", "additions", "changes")
DEFAULT_OWN_FILE = Path(__file__).absolute().parents[1] / "data" / "windows-own.json"

PROGRAM_SOURCES = ("win32_programs", "msix_programs")
AUTOSTART_SOURCES = ("run_keys", "startup_folders", "scheduled_tasks", "services")
COMPONENT_SOURCES = ("optional_features", "capabilities")
# Things added to the system: the kind of each source's items, in list order.
ADDITION_KINDS = {
    "administrators": "administrator",
    "defender_exclusions": "defender_exclusion",
    "root_certificates": "root_certificate",
    "firewall_rules": "firewall_rule",
    "hosts": "hosts_entry",
}
ADDITION_SOURCES = ("firewall_rules", "root_certificates", "hosts", "administrators",
                    "defender_exclusions")
# The sources with items, compared with the baseline.
SOURCES = (PROGRAM_SOURCES + AUTOSTART_SOURCES + COMPONENT_SOURCES + ("drivers",)
           + ADDITION_SOURCES)
READ_STATUSES = ("read", "empty")
# The fields compared with the baseline, per source. inf_name is not compared:
# Windows numbers oem<N>.inf anew when a driver is installed again.
AUTOSTART_FIELDS = ("command", "targets", "enabled")
COMPARED_FIELDS = {
    "win32_programs": ("name", "version", "publisher"),
    "msix_programs": ("name", "version", "publisher", "signature_kind"),
    **{source: AUTOSTART_FIELDS for source in AUTOSTART_SOURCES},
    "optional_features": ("state",),
    "capabilities": ("state",),
    "drivers": ("provider", "version", "date", "signer", "third_party"),
    "firewall_rules": ("action", "dir", "active", "protocol", "lport", "rport", "app",
                       "svc", "profile"),
    "root_certificates": ("subject", "issuer", "not_after"),
    # The key holds the host name and the address; the line number is not compared,
    # so a moved line is no change and any other change is added or removed.
    "hosts": (),
    "administrators": ("name", "enabled"),
    "defender_exclusions": ("origin",),
}
# The field that names an item in a change, when it is not "name".
NAME_FIELDS = {"drivers": "device_name", "root_certificates": "subject",
               "hosts": "hostname", "defender_exclusions": "value"}
# Components: the kind of each source (in list order) and the state that is listed.
COMPONENT_KINDS = {"optional_features": "feature", "capabilities": "capability"}
LISTED_STATES = {"feature": "enabled", "capability": "Installed"}
FEATURE_STATES = {1: "enabled", 2: "disabled", 3: "absent"}
ADMIN_REASON = ("requires administrator rights (not read in this run, which is not "
                "elevated); this is not an empty list")
# The lists cut to fit the budget, in this order, with the key that counts the cut items.
CUT_LISTS = (("programs", "truncated"), ("drivers", "truncated_drivers"),
             ("components", "truncated_components"), ("additions", "truncated_additions"))
# The newest programs kept before the other lists are cut.
PROGRAMS_MIN = 20
# Firewall rules: the stores (registry keys under HKLM) and the fields of a rule.
FIREWALL_STORES = ("local", "app_iso", "policy")
FIREWALL_FIELDS = {
    "action": "Action", "dir": "Dir", "active": "Active", "lport": "LPort",
    "rport": "RPort", "app": "App", "svc": "Svc", "name": "Name", "profile": "Profile",
    "embed_ctxt": "EmbedCtxt",
}
PROTOCOL_NAMES = {6: "TCP", 17: "UDP"}
# protocol next to protocol_name: a null name alone would not tell "any protocol"
# (no Protocol) from a protocol without a name (e.g. 1, ICMP).
FIREWALL_SUMMARY = ("store", "name", "action", "dir", "active", "protocol", "protocol_name",
                    "lport", "app")
# Root certificates: the physical stores and the fields read from Cert:.
CERT_STORES = ("machine_root", "machine_policy", "enterprise", "user_root", "authroot")
CERT_DETAILS = ("subject", "issuer", "not_before", "not_after", "serial")
CERT_SUMMARY = ("store", "subject", "not_after", "self_signed", "in_authroot")
SUBJECT_MAX = 120
# Defender exclusions: the lists of Get-MpPreference by their key word.
DEFENDER_TYPES = ("path", "extension", "process", "ip")
DEFENDER_HIDDEN = "N/A:"
ADMIN_SOURCES = ("Local", "MicrosoftAccount")  # principal sources with a local Enabled
# The fields of one fact compared by path, as facts[<path>].<field>.
FACT_COMPARED = ("exists", "signature_status", "signer", "program")
FACT_FIELDS = ("expanded_path", "exists", "signature_status", "signer", "company")
APPROVED_FIELDS = ("approved", "approved_byte", "approved_raw", "enabled")
CHANGE_ORDER = ("added", "removed", "changed")
HIVE_SCOPE = {"hklm64": "machine", "hklm32": "machine", "hkcu": "user"}
REGISTRY_DATE = re.compile(r"^\d{8}$")
RUN_LOCATION = {
    "hkcu": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion",
    "hklm64": "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion",
    "hklm32": "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion",
}
# The StartupApproved value that holds the state of a Run value: (hive, key).
RUN_APPROVED = {"hkcu": ("hkcu", "Run"), "hklm64": ("hklm", "Run"), "hklm32": ("hklm", "Run32")}
STARTUP_APPROVED = {"user": ("hkcu", "StartupFolder"), "common": ("hklm", "StartupFolder")}
APPROVED_STATES = {2: "enabled", 3: "disabled"}
TRIGGERS = ("MSFT_TaskLogonTrigger", "MSFT_TaskBootTrigger")
USER_SERVICE_INSTANCE = 0x80
INSTANCE_SUFFIX = re.compile(r"_[0-9a-f]+$", re.IGNORECASE)
# The suffix that makes an unread service an instance when the baseline knows neither name.
INSTANCE_GUESS_SUFFIX = re.compile(r"_[0-9a-f]{5,}$", re.IGNORECASE)
# The registry values of a services row in the order SERVICES_BODY reads them.
SERVICE_READ_ORDER = ("Type", "DelayedAutostart", "ServiceDll", "KeyServiceDll",
                      "TemplateServiceDll", "TemplateKeyServiceDll", "TemplateStart")
COMMAND_FILE = re.compile(r"^(.*?\.(?:exe|com|bat|cmd|dll|ps1|vbs|js))(?=[ ,]|$)", re.IGNORECASE)
DRIVE_ROOT = re.compile(r"^[a-z]:$", re.IGNORECASE)

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

# Every subkey is returned, with or without DisplayName; Python filters. The
# registry API is used directly: OpenSubKey gives null for a missing key (no
# Uninstall key in HKCU is "nothing there") and throws when access is denied,
# so a denial of an Uninstall key fails the job instead of passing for an
# empty list. A denied program subkey is one row with Error, so one vendor's
# key does not make the whole source unreadable. The 32-bit
# key is read by its WOW6432Node path in the 64-bit view.
WIN32_PROGRAMS_BODY = r"""$path = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
$views = @(
  @('hklm64', [Microsoft.Win32.RegistryHive]::LocalMachine, $path),
  @('hklm32', [Microsoft.Win32.RegistryHive]::LocalMachine, 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
  @('hkcu', [Microsoft.Win32.RegistryHive]::CurrentUser, $path)
)
$rows = New-Object System.Collections.Generic.List[object]
foreach ($v in $views) {
  $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($v[1], [Microsoft.Win32.RegistryView]::Registry64)
  $root = $base.OpenSubKey($v[2])
  if ($null -ne $root) {
    foreach ($name in $root.GetSubKeyNames()) {
      try { $k = $root.OpenSubKey($name) }
      catch {
        $rows.Add([pscustomobject]@{ Hive = $v[0]; KeyName = S $name; Error = S $_.Exception.Message })
        continue
      }
      if ($null -eq $k) { continue }
      $rows.Add([pscustomobject]@{
        Hive = $v[0]
        KeyName = S $name
        DisplayName = S $k.GetValue('DisplayName')
        DisplayVersion = S $k.GetValue('DisplayVersion')
        Publisher = S $k.GetValue('Publisher')
        InstallDate = S $k.GetValue('InstallDate')
        SystemComponent = N $k.GetValue('SystemComponent')
        InstallLocation = S $k.GetValue('InstallLocation')
      })
      $k.Close()
    }
    $root.Close()
  }
  $base.Close()
}
$result = $rows.ToArray()
"""

# The current account only (-AllUsers needs administrator rights). PS 5.1 has
# no InstallDate: FolderCreated is the UTC creation time of InstallLocation
# (the install or update of the current version), null when the folder is not
# there or its attributes cannot be read.
MSIX_PROGRAMS_BODY = r"""$rows = @(Get-AppxPackage -PackageTypeFilter Main | ForEach-Object {
  $loc = S $_.InstallLocation
  $created = $null
  if ($loc) {
    $dir = New-Object System.IO.DirectoryInfo -ArgumentList $loc
    if ($dir.Exists) { $created = $dir.CreationTimeUtc.ToString('s') + 'Z' }
  }
  [pscustomobject]@{
    Name = S $_.Name
    PackageFamilyName = S $_.PackageFamilyName
    Version = S $_.Version
    Publisher = S $_.Publisher
    SignatureKind = S $_.SignatureKind
    InstallLocation = $loc
    FolderCreated = $created
  }
})
$result = $rows
"""

# Raw values (DoNotExpandEnvironmentNames) and their kind, so the command is
# what the registry holds. A missing key is nothing there; a denied key fails
# the job.
RUN_KEYS_BODY = r"""$cv = 'SOFTWARE\Microsoft\Windows\CurrentVersion'
$views = @(
  @('hkcu', [Microsoft.Win32.RegistryHive]::CurrentUser, $cv),
  @('hklm64', [Microsoft.Win32.RegistryHive]::LocalMachine, $cv),
  @('hklm32', [Microsoft.Win32.RegistryHive]::LocalMachine, 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion')
)
$noExpand = [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
$rows = New-Object System.Collections.Generic.List[object]
foreach ($v in $views) {
  $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($v[1], [Microsoft.Win32.RegistryView]::Registry64)
  foreach ($keyName in @('Run', 'RunOnce')) {
    $k = $base.OpenSubKey($v[2] + '\' + $keyName)
    if ($null -eq $k) { continue }
    foreach ($name in $k.GetValueNames()) {
      $rows.Add([pscustomobject]@{
        Hive = $v[0]
        Key = $keyName
        Name = [string]$name
        Value = S $k.GetValue($name, $null, $noExpand)
        ValueKind = S $k.GetValueKind($name)
      })
    }
    $k.Close()
  }
  $base.Close()
}
$result = $rows.ToArray()
"""

# CreateShortcut on an existing .lnk only reads it; nothing is saved. A
# shortcut that cannot be read is one row with Error.
STARTUP_FOLDERS_BODY = r"""$shell = New-Object -ComObject WScript.Shell
$rows = New-Object System.Collections.Generic.List[object]
foreach ($scope in @(@('user', 'Startup'), @('common', 'CommonStartup'))) {
  $dir = [Environment]::GetFolderPath($scope[1])
  if (-not $dir -or -not [System.IO.Directory]::Exists($dir)) { continue }
  foreach ($f in @(Get-ChildItem -LiteralPath $dir -Force -File)) {
    if ($f.Name -eq 'desktop.ini') { continue }
    $target = $null
    $arguments = $null
    if ($f.Extension -eq '.lnk') {
      try {
        $lnk = $shell.CreateShortcut($f.FullName)
        $target = S $lnk.TargetPath
        $arguments = S $lnk.Arguments
      } catch {
        $rows.Add([pscustomobject]@{ Scope = $scope[0]; FileName = S $f.Name; FullName = S $f.FullName; Error = S $_.Exception.Message })
        continue
      }
    }
    $rows.Add([pscustomobject]@{
      Scope = $scope[0]
      FileName = S $f.Name
      FullName = S $f.FullName
      TargetPath = $target
      Arguments = $arguments
    })
  }
}
$result = $rows.ToArray()
"""

# A missing StartupApproved key is nothing there (the registry API gives null
# where Get-Item throws ItemNotFoundException).
STARTUP_APPROVED_BODY = r"""$sub = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\'
$hives = @(@('hkcu', [Microsoft.Win32.RegistryHive]::CurrentUser), @('hklm', [Microsoft.Win32.RegistryHive]::LocalMachine))
$rows = New-Object System.Collections.Generic.List[object]
foreach ($h in $hives) {
  $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($h[1], [Microsoft.Win32.RegistryView]::Registry64)
  foreach ($keyName in @('Run', 'Run32', 'StartupFolder')) {
    $k = $base.OpenSubKey($sub + $keyName)
    if ($null -eq $k) { continue }
    foreach ($name in $k.GetValueNames()) {
      $value = $k.GetValue($name)
      $bytes = $null
      if ($value -is [byte[]]) { $bytes = [int[]]$value }
      $rows.Add([pscustomobject]@{ Hive = $h[0]; Key = $keyName; Name = [string]$name; Bytes = $bytes })
    }
    $k.Close()
  }
  $base.Close()
}
$result = $rows.ToArray()
"""

# Every task with its trigger classes (Python keeps logon and boot tasks); a
# ComHandler action gets the file of HKCR\CLSID\{id}\InprocServer32. A task
# that cannot be read is one row with Error.
SCHEDULED_TASKS_BODY = r"""$classes = [Microsoft.Win32.Registry]::ClassesRoot
$noExpand = [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
$rows = New-Object System.Collections.Generic.List[object]
foreach ($t in @(Get-ScheduledTask)) {
  try {
    $triggers = [string[]]@(foreach ($tr in @($t.Triggers)) { if ($null -ne $tr) { S $tr.CimClass.CimClassName } })
    $actions = New-Object System.Collections.Generic.List[object]
    foreach ($a in @($t.Actions)) {
      if ($null -eq $a) { continue }
      $type = S $a.CimClass.CimClassName
      if ($type -eq 'MSFT_TaskExecAction') { $type = 'Exec' }
      elseif ($type -eq 'MSFT_TaskComHandlerAction') { $type = 'ComHandler' }
      $execute = $null; $arguments = $null; $classId = $null; $inproc = $null
      if ($type -eq 'Exec') { $execute = S $a.Execute; $arguments = S $a.Arguments }
      if ($type -eq 'ComHandler') {
        $classId = S $a.ClassId
        if ($classId) {
          $k = $classes.OpenSubKey('CLSID\' + $classId + '\InprocServer32')
          if ($null -ne $k) {
            $inproc = S $k.GetValue('', $null, $noExpand)
            $k.Close()
          }
        }
      }
      $actions.Add([pscustomobject]@{ Type = $type; Execute = $execute; Arguments = $arguments; ClassId = $classId; InprocServer32 = $inproc })
    }
    $rows.Add([pscustomobject]@{
      TaskPath = S $t.TaskPath
      TaskName = S $t.TaskName
      State = S $t.State
      Triggers = $triggers
      Actions = [object[]]$actions.ToArray()
    })
  } catch {
    $rows.Add([pscustomobject]@{ TaskPath = S $t.TaskPath; TaskName = S $t.TaskName; Error = S $_.Exception.Message })
  }
}
$result = $rows.ToArray()
"""

# Automatic services with the registry values of their key (raw, not
# expanded); for a per-user instance (Type bit 0x80) also those of its
# template, whose name is the instance name without _<hex>. A registry read
# that fails leaves the Win32_Service fields and the values read before it, and
# adds Error and ErrorAt, the name of the value whose read failed ($at is set
# before each read, in SERVICE_READ_ORDER, and reset for each service).
SERVICES_BODY = r"""$svcRoot = 'SYSTEM\CurrentControlSet\Services\'
$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$noExpand = [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
function V($path, $name) {
  $k = $hklm.OpenSubKey($path)
  if ($null -eq $k) { return $null }
  try { return $k.GetValue($name, $null, $noExpand) } finally { $k.Close() }
}
$rows = New-Object System.Collections.Generic.List[object]
foreach ($s in @(Get-CimInstance -ClassName Win32_Service -Filter "StartMode = 'Auto'")) {
  $name = S $s.Name
  $row = [ordered]@{
    Name = $name; DisplayName = S $s.DisplayName; PathName = S $s.PathName
    State = S $s.State; StartMode = S $s.StartMode; Type = $null; DelayedAutostart = $null
    ServiceDll = $null; KeyServiceDll = $null; TemplateServiceDll = $null
    TemplateKeyServiceDll = $null; TemplateStart = $null
  }
  $at = $null
  try {
    $key = $svcRoot + $name
    $at = 'Type'
    $row.Type = N (V $key 'Type')
    $at = 'DelayedAutostart'
    $row.DelayedAutostart = N (V $key 'DelayedAutostart')
    $at = 'ServiceDll'
    $row.ServiceDll = S (V ($key + '\Parameters') 'ServiceDll')
    $at = 'KeyServiceDll'
    $row.KeyServiceDll = S (V $key 'ServiceDll')
    if ($null -ne $row.Type -and ($row.Type -band 0x80)) {
      $tkey = $svcRoot + ($name -replace '_[0-9a-f]+$', '')
      $at = 'TemplateServiceDll'
      $row.TemplateServiceDll = S (V ($tkey + '\Parameters') 'ServiceDll')
      $at = 'TemplateKeyServiceDll'
      $row.TemplateKeyServiceDll = S (V $tkey 'ServiceDll')
      $at = 'TemplateStart'
      $row.TemplateStart = N (V $tkey 'Start')
    }
  } catch { $row.Error = S $_.Exception.Message; $row.ErrorAt = $at }
  $rows.Add([pscustomobject]$row)
}
$hklm.Close()
$result = $rows.ToArray()
"""

# __INPUT__ is replaced by the quoted path of {"paths": [...]}. A path without
# a folder is looked up in System32, the Windows folder and PATH, as Windows
# would start it. Nothing is written; a file that cannot be read is one row
# with Error.
FILE_FACTS_BODY = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$paths = @($in.paths)
$rows = New-Object System.Collections.Generic.List[object]
$dirs = @(
  @('ProgramFiles', $env:ProgramFiles),
  @('ProgramFilesX86', ${env:ProgramFiles(x86)}),
  @('SystemRoot', $env:SystemRoot),
  @('System32', [Environment]::SystemDirectory)
)
foreach ($d in $dirs) { $rows.Add([pscustomobject]@{ Kind = 'dir'; Name = $d[0]; Path = S $d[1] }) }
# PATH entries are expanded and unquoted once; an empty one or one with a
# character not allowed in a path is dropped, so it cannot fail a file's lookup.
$search = @([Environment]::SystemDirectory, $env:SystemRoot) + @(($env:Path -split ';') |
  ForEach-Object { [Environment]::ExpandEnvironmentVariables($_).Trim('"') } |
  Where-Object { $_ -and $_.IndexOfAny([System.IO.Path]::GetInvalidPathChars()) -lt 0 })
foreach ($p in $paths) {
  $path = S $p
  if (-not $path) { continue }
  try {
    $expanded = [Environment]::ExpandEnvironmentVariables($path)
    if (-not [System.IO.Path]::IsPathRooted($expanded)) {
      foreach ($dir in $search) {
        $candidate = [System.IO.Path]::Combine($dir, $expanded)
        if ([System.IO.File]::Exists($candidate)) { $expanded = $candidate; break }
      }
    }
    $exists = [System.IO.File]::Exists($expanded)
    $status = $null; $signer = $null; $company = $null
    if ($exists) {
      $sig = Get-AuthenticodeSignature -LiteralPath $expanded
      $status = S $sig.Status
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
      $company = S ([System.Diagnostics.FileVersionInfo]::GetVersionInfo($expanded).CompanyName)
    }
    $rows.Add([pscustomobject]@{
      Kind = 'file'; Path = $path; ExpandedPath = $expanded; Exists = $exists
      SignatureStatus = $status; Signer = $signer; Company = $company
    })
  } catch {
    $rows.Add([pscustomobject]@{ Kind = 'file'; Path = $path; Error = S $_.Exception.Message })
  }
}
$result = $rows.ToArray()
"""

# Works without administrator rights (Get-WindowsOptionalFeature does not).
# InstallState stays a number; Python maps it.
OPTIONAL_FEATURES_BODY = r"""$rows = @(Get-CimInstance -ClassName Win32_OptionalFeature | ForEach-Object {
  [pscustomobject]@{ Name = S $_.Name; Caption = S $_.Caption; InstallState = N $_.InstallState }
})
$result = $rows
"""

# Needs administrator rights; the job is run only then. State is the enum's name.
CAPABILITIES_BODY = r"""$rows = @(Get-WindowsCapability -Online | ForEach-Object {
  [pscustomobject]@{ Name = S $_.Name; State = S $_.State }
})
$result = $rows
"""

# Works without administrator rights. DriverDate arrives as a local DateTime of a
# UTC date, so it is turned back into UTC and written as yyyy-MM-dd, else null.
DRIVERS_BODY = r"""$inv = [System.Globalization.CultureInfo]::InvariantCulture
$rows = @(Get-CimInstance -ClassName Win32_PnPSignedDriver | ForEach-Object {
  $day = $null
  if ($_.DriverDate -is [datetime]) { $day = $_.DriverDate.ToUniversalTime().ToString('yyyy-MM-dd', $inv) }
  [pscustomobject]@{
    DeviceID = S $_.DeviceID
    DeviceName = S $_.DeviceName
    DeviceClass = S $_.DeviceClass
    InfName = S $_.InfName
    DriverProviderName = S $_.DriverProviderName
    DriverVersion = S $_.DriverVersion
    DriverDate = $day
    Signer = S $_.Signer
  }
})
$result = $rows
"""

# One row per store with the raw rule text of every value. OpenSubKey gives null
# for a missing key (no rules in that store) and throws when access is denied,
# which fails the whole job.
FIREWALL_RULES_BODY = r"""$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$policy = 'SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\'
$stores = @(
  @('local', ($policy + 'FirewallRules')),
  @('app_iso', ($policy + 'RestrictedServices\AppIso\FirewallRules')),
  @('policy', 'SOFTWARE\Policies\Microsoft\WindowsFirewall\FirewallRules')
)
$rows = New-Object System.Collections.Generic.List[object]
foreach ($s in $stores) {
  $k = $hklm.OpenSubKey($s[1])
  $values = New-Object System.Collections.Generic.List[object]
  if ($null -ne $k) {
    foreach ($name in $k.GetValueNames()) {
      $values.Add([pscustomobject]@{ name = [string]$name; data = S $k.GetValue($name) })
    }
    $k.Close()
  }
  $rows.Add([pscustomobject]@{ store = $s[0]; exists = ($null -ne $k); values = [object[]]$values.ToArray() })
}
$hklm.Close()
$result = $rows.ToArray()
"""

# One row per physical store: the thumbprint subkeys from the registry (Cert:
# merges the stores, so it cannot tell them apart), and the details of each from
# Cert:, null when Cert: has no such certificate or throws. A missing key is an
# empty store; a denied key fails the whole job.
ROOT_CERTIFICATES_BODY = r"""$inv = [System.Globalization.CultureInfo]::InvariantCulture
$stores = @(
  @('machine_root', [Microsoft.Win32.RegistryHive]::LocalMachine, 'SOFTWARE\Microsoft\SystemCertificates\ROOT\Certificates', 'Cert:\LocalMachine\Root'),
  @('machine_policy', [Microsoft.Win32.RegistryHive]::LocalMachine, 'SOFTWARE\Policies\Microsoft\SystemCertificates\Root\Certificates', 'Cert:\LocalMachine\Root'),
  @('enterprise', [Microsoft.Win32.RegistryHive]::LocalMachine, 'SOFTWARE\Microsoft\EnterpriseCertificates\Root\Certificates', 'Cert:\LocalMachine\Root'),
  @('user_root', [Microsoft.Win32.RegistryHive]::CurrentUser, 'Software\Microsoft\SystemCertificates\Root\Certificates', 'Cert:\CurrentUser\Root'),
  @('authroot', [Microsoft.Win32.RegistryHive]::LocalMachine, 'SOFTWARE\Microsoft\SystemCertificates\AuthRoot\Certificates', 'Cert:\LocalMachine\AuthRoot')
)
$rows = New-Object System.Collections.Generic.List[object]
foreach ($s in $stores) {
  $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($s[1], [Microsoft.Win32.RegistryView]::Registry64)
  $k = $base.OpenSubKey($s[2])
  $certs = New-Object System.Collections.Generic.List[object]
  if ($null -ne $k) {
    foreach ($thumb in $k.GetSubKeyNames()) {
      $details = $null
      try {
        $c = Get-Item -LiteralPath ($s[3] + '\' + $thumb) -ErrorAction Stop
        $details = [pscustomobject]@{
          subject = S $c.Subject
          issuer = S $c.Issuer
          not_before = $c.NotBefore.ToUniversalTime().ToString('yyyy-MM-dd', $inv)
          not_after = $c.NotAfter.ToUniversalTime().ToString('yyyy-MM-dd', $inv)
          serial = S $c.SerialNumber
        }
      } catch { $details = $null }
      $certs.Add([pscustomobject]@{ thumbprint = [string]$thumb; details = $details })
    }
    $k.Close()
  }
  $base.Close()
  $rows.Add([pscustomobject]@{ store = $s[0]; exists = ($null -ne $k); certificates = [object[]]$certs.ToArray() })
}
$result = $rows.ToArray()
"""

# One object: the raw DataBasePath (not expanded), its expansion, whether the
# hosts file is there and its text. A missing DataBasePath fails the job: the
# folder is never guessed.
HOSTS_BODY = r"""$k = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('SYSTEM\CurrentControlSet\Services\Tcpip\Parameters')
if ($null -eq $k) { throw 'the key Tcpip\Parameters is missing' }
$raw = S $k.GetValue('DataBasePath', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
$k.Close()
if (-not $raw) { throw 'Tcpip\Parameters has no DataBasePath value' }
$expanded = [Environment]::ExpandEnvironmentVariables($raw)
$file = [System.IO.Path]::Combine($expanded, 'hosts')
# File.Exists is also false when the file cannot be checked; only a file or
# folder that is not there counts as missing, any other error fails the job.
$exists = $true
$text = $null
try { $text = [System.IO.File]::ReadAllText($file) }
catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { $exists = $false }
$result = [pscustomobject]@{ raw_dir = $raw; expanded_dir = $expanded; exists = $exists; text = $text; system_root = $env:SystemRoot }
"""

# One object: the members of the Administrators group (S-1-5-32-544) and the SID
# of the current account. Get-LocalGroupMember first; Enabled from Get-LocalUser
# only for local and Microsoft accounts (enabled_error when it fails). When
# Get-LocalGroupMember fails (e.g. a member that cannot be resolved), ADSI
# (method adsi, without PrincipalSource and Enabled). Both failing fails the job.
ADMINISTRATORS_BODY = r"""$current = S ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
$method = 'local_group_member'
$members = New-Object System.Collections.Generic.List[object]
try {
  foreach ($m in @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction Stop)) {
    $sid = S $m.SID
    $class = S $m.ObjectClass
    $source = S $m.PrincipalSource
    $isUser = $null; $enabled = $null; $enabledError = $null
    # ObjectClass is in the system language; a local group is told from a user by
    # Get-LocalUser finding no user with the SID.
    if ($source -eq 'Local' -or $source -eq 'MicrosoftAccount') {
      try { $enabled = [bool](Get-LocalUser -SID $sid -ErrorAction Stop).Enabled; $isUser = $true }
      catch [Microsoft.PowerShell.Commands.UserNotFoundException] { $isUser = $false }
      catch { $enabledError = S $_.Exception.Message }
    }
    $members.Add([pscustomobject]@{ sid = $sid; name = S $m.Name; object_class = $class; principal_source = $source; is_user = $isUser; enabled = $enabled; enabled_error = $enabledError })
  }
} catch {
  $first = S $_.Exception.Message
  $method = 'adsi'
  $members.Clear()
  try {
    $group = @(Get-CimInstance -ClassName Win32_Group -Filter "SID = 'S-1-5-32-544'" -ErrorAction Stop)[0]
    if ($null -eq $group) { throw 'no Win32_Group with the SID S-1-5-32-544' }
    $adsi = [ADSI]('WinNT://' + $group.Domain + '/' + $group.Name + ',group')
    foreach ($m in @($adsi.psbase.Invoke('Members'))) {
      $t = $m.GetType()
      $path = S $t.InvokeMember('ADsPath', 'GetProperty', $null, $m, $null)
      $class = S $t.InvokeMember('Class', 'GetProperty', $null, $m, $null)
      $bytes = [byte[]]$t.InvokeMember('objectSid', 'GetProperty', $null, $m, $null)
      $sid = (New-Object System.Security.Principal.SecurityIdentifier -ArgumentList $bytes, 0).Value
      $parts = @(($path -replace '^WinNT://', '') -split '/')
      $name = $parts[-1]
      if ($parts.Count -ge 2) { $name = $parts[-2] + '\' + $parts[-1] }
      $members.Add([pscustomobject]@{ sid = S $sid; name = S $name; object_class = $class; principal_source = $null; is_user = $null; enabled = $null; enabled_error = $null })
    }
  } catch {
    throw ('Get-LocalGroupMember: ' + $first + '; ADSI: ' + $_.Exception.Message)
  }
}
$result = [pscustomobject]@{ method = $method; current_sid = $current; members = [object[]]$members.ToArray() }
"""

# Run only with administrator rights. Get-MpPreference first (method
# preference); when it fails (e.g. 0x800106ba with another antivirus active) the
# value names of the Exclusions keys (method registry). In both methods the value
# names under the policy keys, or policy_error when they cannot be read. Both
# local methods failing fails the job.
DEFENDER_EXCLUSIONS_BODY = r"""$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$kinds = @(
  @('path', 'Paths', 'ExclusionPath'),
  @('extension', 'Extensions', 'ExclusionExtension'),
  @('process', 'Processes', 'ExclusionProcess'),
  @('ip', 'IpAddresses', 'ExclusionIpAddress')
)
function Names($path) {
  $k = $hklm.OpenSubKey($path)
  if ($null -eq $k) { return ,([string[]]@()) }
  try { return ,([string[]]@($k.GetValueNames())) } finally { $k.Close() }
}
$out = [ordered]@{ method = 'preference'; path = @(); extension = @(); process = @(); ip = @(); policy = $null; policy_error = $null }
try {
  $pref = Get-MpPreference -ErrorAction Stop
  foreach ($kd in $kinds) {
    $out[$kd[0]] = [string[]]@(@($pref.($kd[2])) | Where-Object { $null -ne $_ } | ForEach-Object { [string]$_ })
  }
} catch {
  $first = S $_.Exception.Message
  $out.method = 'registry'
  try {
    foreach ($kd in $kinds) { $out[$kd[0]] = Names ('SOFTWARE\Microsoft\Windows Defender\Exclusions\' + $kd[1]) }
  } catch {
    throw ('Get-MpPreference: ' + $first + '; registry: ' + $_.Exception.Message)
  }
}
try {
  $pol = [ordered]@{}
  foreach ($kd in $kinds) { $pol[$kd[0]] = Names ('SOFTWARE\Policies\Microsoft\Windows Defender\Exclusions\' + $kd[1]) }
  $out.policy = [pscustomobject]$pol
} catch { $out.policy_error = S $_.Exception.Message }
$hklm.Close()
$result = [pscustomobject]$out
"""


# --- values ----------------------------------------------------------------
def text(value):
    """A non-empty string, or None; other types become their text."""
    if value is None:
        return None
    value = str(value)
    return value if value.strip() else None


def registry_date(value):
    """``YYYYMMDD`` as ``YYYY-MM-DD``; any other format (or no value) is None."""
    value = text(value)
    if value is None or not REGISTRY_DATE.match(value.strip()):
        return None
    try:
        digits = value.strip()
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:  # eight digits that are no date
        return None


def utc_date(value):
    """The UTC date (``YYYY-MM-DD``) of an ISO 8601 time with a zone, else None.

    A time without a zone is None: its zone is never guessed.
    """
    value = text(value)
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None or moment.utcoffset() is None:
        return None
    return moment.astimezone(timezone.utc).date().isoformat()


def system_component(value) -> bool:
    """True only for ``SystemComponent`` = 1; a missing or other value is False."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == 1
    return text(value) is not None and text(value).strip() == "1"


def dn_parts(dn: str) -> dict:
    """The attributes of a distinguished name (``CN=..., O=..., C=US``), upper-case keys.

    Commas inside double quotes do not split; the first value of an attribute wins.
    """
    parts, current, quoted = [], [], False
    for char in dn:
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    result = {}
    for part in parts:
        name, sep, value = part.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        result.setdefault(name.strip().upper(), value)
    return result


def dn_publisher(value):
    """The ``O=`` value of a publisher DN, else its ``CN=`` value, else None."""
    value = text(value)
    if value is None:
        return None
    parts = dn_parts(value)
    return text(parts.get("O")) or text(parts.get("CN"))


def version_key(value):
    """A dotted version as a tuple of numbers; a part that is not a number is -1."""
    value = text(value) or ""
    return tuple(int(p) if p.strip().isdigit() else -1 for p in value.split("."))


def clean_path(value):
    """A path without surrounding quotes, ``\\SystemRoot\\`` as ``%SystemRoot%\\``; else None."""
    value = text(value)
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].strip()
    if value.casefold().startswith("\\systemroot\\"):
        value = "%SystemRoot%" + value[len("\\SystemRoot"):]
    return text(value)


def target_path(command):
    """The file a command line starts, as text (environment variables not expanded).

    A quoted start is the file; else the shortest prefix that ends in a known
    extension before a space, a comma or the end; else the first word. A leading
    ``\\SystemRoot\\`` becomes ``%SystemRoot%\\``. No command gives None.
    """
    value = text(command)
    if value is None:
        return None
    value = value.strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        found = value[1:end] if end > 0 else value[1:]
    else:
        match = COMMAND_FILE.match(value)
        found = match.group(1) if match else value.split()[0]
    return clean_path(found)


def file_name(path):
    """The last part of a Windows path, case-folded; None for no path."""
    path = text(path)
    return ntpath.basename(path.strip()).casefold() if path else None


# The lists of data/windows-own.json; the name sets are compared case-insensitively.
OWN_LISTS = ("msix_signature_kinds", "signer_organizations", "launchers", "own_kinds",
             "driver_third_party_inf")
FOLDED_LISTS = ("signer_organizations", "launchers", "driver_third_party_inf")


def is_strings(values) -> bool:
    return isinstance(values, list) and all(isinstance(v, str) for v in values)


def load_additions_own(data: dict):
    """The fields of the data file for the added-to-the-system sources, or a reason.

    ``firewall_builtin`` is ``{name_prefix, required_fields}``; the managed stores are
    a set; the shipped thumbprints a set of upper-case thumbprints (their ``subject``
    and ``source`` only document the entry); ``cert_windows_first_run`` a list of
    ``{subject_cn, serial}`` with the serial in upper case (``source`` only documents
    the entry); ``hosts_default_dir`` a string.
    """
    builtin = data.get("firewall_builtin")
    if not isinstance(builtin, dict) or not isinstance(builtin.get("name_prefix"), str) \
            or not is_strings(builtin.get("required_fields")):
        return None, "firewall_builtin is not {name_prefix, required_fields}"
    stores = data.get("cert_windows_managed_stores")
    if not is_strings(stores):
        return None, "cert_windows_managed_stores is not a list of strings"
    shipped = data.get("cert_windows_shipped_thumbprints")
    if not isinstance(shipped, list) or not all(
            isinstance(e, dict) and isinstance(e.get("thumbprint"), str) for e in shipped):
        return None, "cert_windows_shipped_thumbprints is not a list of {thumbprint, subject}"
    first_run = data.get("cert_windows_first_run")
    if not isinstance(first_run, list) or not all(
            isinstance(e, dict) and all(isinstance(e.get(k), str) and e[k].strip()
                                        for k in ("subject_cn", "serial"))
            for e in first_run):
        return None, "cert_windows_first_run is not a list of {subject_cn, serial}"
    hosts_dir = data.get("hosts_default_dir")
    if not isinstance(hosts_dir, str):
        return None, "hosts_default_dir is not a string"
    return {
        "firewall_builtin": {"name_prefix": builtin["name_prefix"],
                             "required_fields": list(builtin["required_fields"])},
        "cert_windows_managed_stores": set(stores),
        "cert_windows_shipped_thumbprints": {e["thumbprint"].strip().upper() for e in shipped},
        "cert_windows_first_run": [{"subject_cn": e["subject_cn"].strip(),
                                    "serial": e["serial"].strip().upper()}
                                   for e in first_run],
        "hosts_default_dir": hosts_dir,
    }, None


def load_own(path: Path):
    """The data file as ``({name: value}, None)``, or empty values and a reason.

    ``signer_organizations``, ``launchers`` and ``driver_third_party_inf`` are
    case-folded. A file that cannot be read classifies nothing as part of Windows,
    so every entry is listed: ``driver_third_party_inf`` is then None (unknown), and
    every driver is listed with ``third_party`` unread; ``firewall_builtin`` and
    ``hosts_default_dir`` are None, so no firewall rule is own and ``path_is_default``
    is unread; ``cert_windows_first_run`` is None, so no new first-run decision is
    made and the recorded ones still apply.
    """
    empty = {name: set() for name in OWN_LISTS}
    empty.update(driver_third_party_inf=None, firewall_builtin=None,
                 cert_windows_managed_stores=set(), cert_windows_shipped_thumbprints=set(),
                 cert_windows_first_run=None, hosts_default_dir=None)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return empty, f"{Path(path).name} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return empty, f"{Path(path).name} does not hold an object"
    config = {}
    for name in OWN_LISTS:
        values = data.get(name)
        if not is_strings(values):
            return empty, f"{Path(path).name}: {name} is not a list of strings"
        if name in FOLDED_LISTS:
            values = [v.casefold() for v in values]
        config[name] = set(values)
    additions, reason = load_additions_own(data)
    if additions is None:
        return empty, f"{Path(path).name}: {reason}"
    config.update(additions)
    return config, None


# --- collection ------------------------------------------------------------
class Collector:
    """Runs the jobs of one collection and keeps the sources and not_checked."""

    def __init__(self, run_ps, work: Path, stamp: str):
        self.run_ps = run_ps
        self.work = work
        self.stamp = stamp
        self.sources = []
        self.not_checked = []
        self.drivers_without_inf = None  # set by collect: rows without InfName
        self.hosts_file = None  # set by collect_hosts: the folder and file of hosts
        self.current_sid = None  # set by collect_administrators

    def job(self, job: str, body: str, depth: int = 4) -> dict:
        out_path = self.work / f"inventory-{self.stamp}.{job}.json"
        script = ps_script(PS_HELPERS + body, out_path, depth)
        return run_job(self.run_ps, job, script, out_path)

    def record(self, name: str, status: str, reason=None, **extra) -> None:
        """One entry of sources (with ``extra`` fields such as ``method``); an
        unreadable source is also an item of not_checked."""
        self.sources.append({"name": name, "status": status, "reason": reason, **extra})
        if status == "unreadable":
            self.skip(name, reason)

    def skip(self, what: str, reason: str) -> None:
        self.not_checked.append({"what": what, "reason": reason})


def collect_win32(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})``; a subkey without DisplayName is no program.

    A subkey that could not be opened (a row with ``Error``) is named in
    not_checked and keeps its item from the previous baseline, marked
    ``from_baseline: true``, so it is not reported as removed; without a
    previous item it is left out. When nothing but denied subkeys came, the
    source is unreadable, not empty.
    """
    result = col.job("win32_programs", WIN32_PROGRAMS_BODY)
    items, denied = {}, 0
    for row in result["rows"]:
        name = text(row.get("DisplayName"))
        hive = text(row.get("Hive"))
        key_name = text(row.get("KeyName"))
        if hive is None or key_name is None:
            continue
        key = f"win32:{hive}:{key_name}"
        error = text(row.get("Error"))
        if error is not None:
            denied += 1
            col.skip(f"win32_programs key {hive}:{key_name}", error)
            if key in previous:
                items[key] = copy.deepcopy(previous[key])
                items[key]["from_baseline"] = True  # not read in this run
            continue
        if name is None:
            continue
        if key in items:  # one registry key is one item
            continue
        items[key] = {
            "name": name,
            "version": text(row.get("DisplayVersion")),
            "publisher": text(row.get("Publisher")),
            "install_date": registry_date(row.get("InstallDate")),
            "scope": HIVE_SCOPE.get(hive),
            "system_component": system_component(row.get("SystemComponent")),
            "install_location": text(row.get("InstallLocation")),
        }
    status, reason = result["status"], result["reason"]
    if status == "read" and not items and denied:
        status = "unreadable"  # every program subkey that came was denied
        reason = f"{denied} program subkey(s) could not be opened"
    elif status == "read" and not items:
        status = "empty"  # rows came, but none of them is a program
    col.record("win32_programs", status, reason)
    return status, items


def collect_msix(col: Collector) -> tuple[str, dict]:
    """``(status, {key: item})``; of one package family the higher Version stays."""
    result = col.job("msix_programs", MSIX_PROGRAMS_BODY)
    items = {}
    for row in result["rows"]:
        family = text(row.get("PackageFamilyName"))
        if family is None:
            continue
        key = f"msix:{family}"
        item = {
            "name": text(row.get("Name")),
            "version": text(row.get("Version")),
            "publisher": dn_publisher(row.get("Publisher")),
            "signature_kind": text(row.get("SignatureKind")),
            "install_location": text(row.get("InstallLocation")),
            "install_date": utc_date(row.get("FolderCreated")),
        }
        kept = items.get(key)
        if kept is None or version_key(item["version"]) > version_key(kept["version"]):
            items[key] = item
    status = result["status"]
    if status == "read" and not items:
        status = "empty"
    col.record("msix_programs", status, result["reason"])
    return status, items


def as_list(value) -> list:
    """A JSON value as a list: a single object or string is a one-element list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def entry_status(name: str, result: dict, items: dict, failed: int) -> tuple[str, str]:
    """The status of an autostart source from its job, its items and its Error rows.

    Rows that give no entry make the source ``empty``; only Error rows make it
    unreadable, not empty.
    """
    status, reason = result["status"], result["reason"]
    if status == "read" and not items and failed:
        status = "unreadable"
        reason = f"{failed} row(s) of {name} could not be read"
    elif status == "read" and not items:
        status = "empty"
    return status, reason


def keep_previous(col: Collector, source: str, key: str, error: str, items: dict,
                  previous: dict) -> None:
    """An item that could not be read: named in not_checked, kept from the baseline."""
    col.skip(f"{source} {key}", error)
    if key in previous:
        items[key] = copy.deepcopy(previous[key])
        items[key]["from_baseline"] = True  # not read in this run


def collect_run_keys(col: Collector) -> tuple[str, dict, dict]:
    """``(status, {key: entry}, {key: StartupApproved slot})`` of ``Run``/``RunOnce``."""
    result = col.job("run_keys", RUN_KEYS_BODY)
    items, slots = {}, {}
    for row in result["rows"]:
        hive, key_name, name = text(row.get("Hive")), text(row.get("Key")), row.get("Name")
        if hive not in RUN_LOCATION or key_name not in ("Run", "RunOnce") \
                or not isinstance(name, str):
            continue
        key = f"run:{hive}\\{key_name}:{name}"
        command = text(row.get("Value"))
        items[key] = {
            "kind": "run" if key_name == "Run" else "run_once",
            "location": f"{RUN_LOCATION[hive]}\\{key_name}",
            "name": name,
            "command": command,
            "value_kind": text(row.get("ValueKind")),
            "targets": [target_path(command)],
        }
        if key_name == "Run":  # RunOnce has no StartupApproved value
            slots[key] = (*RUN_APPROVED[hive], name)
    status, reason = entry_status("run_keys", result, items, 0)
    col.record("run_keys", status, reason)
    return status, items, slots


def collect_startup(col: Collector, previous: dict) -> tuple[str, dict, dict]:
    """``(status, {key: entry}, {key: StartupApproved slot})`` of the Startup folders."""
    result = col.job("startup_folders", STARTUP_FOLDERS_BODY)
    items, slots, failed = {}, {}, 0
    for row in result["rows"]:
        scope, name = text(row.get("Scope")), text(row.get("FileName"))
        if scope not in STARTUP_APPROVED or name is None or name.casefold() == "desktop.ini":
            continue
        key = f"startup:{scope}:{name}"
        error = text(row.get("Error"))
        if error is not None:
            failed += 1
            keep_previous(col, "startup_folders", key, error, items, previous)
            continue
        full_name = text(row.get("FullName"))
        target, arguments = text(row.get("TargetPath")), text(row.get("Arguments"))
        if name.casefold().endswith(".lnk"):
            command = f"{target} {arguments}" if target and arguments else (target or full_name)
        else:
            command, target = full_name, full_name
        items[key] = {
            "kind": "startup_folder",
            "location": ntpath.dirname(full_name) if full_name else None,
            "name": name,
            "command": command,
            "targets": [clean_path(target)],
        }
        slots[key] = (*STARTUP_APPROVED[scope], name)
    status, reason = entry_status("startup_folders", result, items, failed)
    col.record("startup_folders", status, reason)
    return status, items, slots


NOT_BINARY = "not binary"  # read as approved "unknown" with approved_byte null


def collect_approved(col: Collector) -> tuple[str, dict]:
    """``(status, {(hive, key, name casefolded): bytes})`` of ``StartupApproved``."""
    result = col.job("startup_approved", STARTUP_APPROVED_BODY)
    values = {}
    for row in result["rows"]:
        hive, key_name, name = text(row.get("Hive")), text(row.get("Key")), row.get("Name")
        if hive is None or key_name is None or not isinstance(name, str):
            continue
        raw = row.get("Bytes")
        if raw is None:
            # A value that is there but not binary: unknown, never "not set".
            col.skip(f"startup_approved {hive}\\{key_name}:{name}", "the value is not binary")
            raw = NOT_BINARY
        values.setdefault((hive, key_name, name.casefold()), raw)
    col.record("startup_approved", result["status"], result["reason"])
    return result["status"], values


def approved_fields(raw) -> dict:
    """``approved`` (and its companions) from a StartupApproved value, None when absent.

    First byte 2 is ``enabled``, 3 is ``disabled``, anything else ``unknown`` with
    ``approved_byte``; ``approved_raw`` is the whole value in hex, for a rollback.
    ``enabled`` is null for ``unknown``: what the other bytes mean is not known.
    """
    if raw is None:
        return {"approved": "not_set", "enabled": True}
    values = as_list(raw)
    valid = all(isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 255
                for b in values)
    first = values[0] if values and valid else None
    fields = {"approved": APPROVED_STATES.get(first, "unknown")}
    if fields["approved"] == "unknown":
        fields["approved_byte"] = first
    fields["approved_raw"] = "".join(f"{b:02x}" for b in values) if valid else None
    fields["enabled"] = {"enabled": True, "disabled": False}.get(fields["approved"])
    return fields


def apply_approved(items: dict, slots: dict, status: str, values: dict,
                   previous: dict) -> None:
    """Set ``approved`` and ``enabled`` of Run and Startup entries.

    When StartupApproved was not read, the fields come from the previous baseline
    by entry key; without a previous entry they are null and unread.
    """
    for key, item in items.items():
        if item.get("from_baseline"):
            continue
        slot = slots.get(key)
        if slot is None:  # RunOnce: no StartupApproved value exists for it
            item.update(approved="not_set", enabled=True)
            continue
        if status in READ_STATUSES:
            item.update(approved_fields(values.get((slot[0], slot[1], slot[2].casefold()))))
            if item["enabled"] is None:
                item["unread_fields"] = sorted(set(item.get("unread_fields") or []) | {"enabled"})
            continue
        before = previous.get(key)
        unread = set(item.get("unread_fields") or [])
        if before is None:
            item.update(approved=None, enabled=None)
            unread |= {"approved", "enabled"}
        else:
            item.update({f: before[f] for f in APPROVED_FIELDS if f in before})
            item.setdefault("approved", None)
            item.setdefault("enabled", None)
            unread |= set(before.get("unread_fields") or []) & {"approved", "enabled"}
        if unread:
            item["unread_fields"] = sorted(unread)


def action_command(action: dict):
    """One task action as text: ``Execute Arguments``, or the handler's CLSID."""
    kind = text(action.get("Type"))
    if kind == "Exec":
        execute, arguments = text(action.get("Execute")), text(action.get("Arguments"))
        return f"{execute} {arguments}" if execute and arguments else execute
    if kind == "ComHandler":
        return f"ComHandler {text(action.get('ClassId'))}"
    return kind


def action_target(action: dict):
    """The file of one task action: the program of Exec, the DLL of ComHandler."""
    kind = text(action.get("Type"))
    if kind == "Exec":
        execute = text(action.get("Execute"))
        return target_path(f'"{execute.strip().strip(chr(34))}"') if execute else None
    if kind == "ComHandler":
        return clean_path(action.get("InprocServer32"))
    return None


def collect_tasks(col: Collector, previous: dict, admin: bool) -> tuple[str, dict]:
    """``(status, {key: entry})`` of the tasks with a logon or boot trigger."""
    result = col.job("scheduled_tasks", SCHEDULED_TASKS_BODY, depth=5)
    items, failed = {}, 0
    for row in result["rows"]:
        path, name = text(row.get("TaskPath")), text(row.get("TaskName"))
        if name is None:
            continue
        key = f"task:{path or ''}{name}"
        error = text(row.get("Error"))
        if error is not None:
            failed += 1
            keep_previous(col, "scheduled_tasks", key, error, items, previous)
            continue
        if not set(as_list(row.get("Triggers"))) & set(TRIGGERS):
            continue
        actions = [a for a in as_list(row.get("Actions")) if isinstance(a, dict)]
        state = text(row.get("State"))
        items[key] = {
            "kind": "task",
            "location": path,
            "name": name,
            "command": "; ".join(c for c in map(action_command, actions) if c) or None,
            "state": state,
            "enabled": (state or "").casefold() != "disabled",
            "targets": [action_target(a) for a in actions],
        }
    status, reason = entry_status("scheduled_tasks", result, items, failed)
    col.record("scheduled_tasks", status, reason)
    if status in READ_STATUSES and not admin:
        col.skip("scheduled_tasks visibility",
                 "run without administrator rights: the task list may miss tasks this "
                 "account cannot see, without any error")
    return status, items


def service_dll_names(instance: bool) -> tuple:
    """The registry values that give the ServiceDll of svchost.exe, first match wins."""
    names = ("ServiceDll", "KeyServiceDll")
    if instance:
        names = ("TemplateServiceDll", "TemplateKeyServiceDll") + names
    return names


def service_read_values(row: dict) -> set:
    """The registry values of a services row that were read: all without ``Error``;
    those before ``ErrorAt`` when it names a value of ``SERVICE_READ_ORDER``; else none."""
    if text(row.get("Error")) is None:
        return set(SERVICE_READ_ORDER)
    at = row.get("ErrorAt")
    if at not in SERVICE_READ_ORDER:
        return set()
    return set(SERVICE_READ_ORDER[:SERVICE_READ_ORDER.index(at)])


def service_target_unread(row: dict, instance: bool) -> bool:
    """Whether the ServiceDll of a svchost.exe row is unknown: a value not read comes
    before the first non-empty one, in the order of ``service_target``."""
    read = service_read_values(row)
    for name in service_dll_names(instance):
        if name not in read:
            return True
        if clean_path(row.get(name)) is not None:
            return False
    return False


def service_target(row: dict, instance: bool):
    """The file a service starts; for svchost.exe its ServiceDll (the template's for an
    instance), else None."""
    target = target_path(row.get("PathName"))
    if file_name(target) != "svchost.exe":
        return target
    for name in service_dll_names(instance):
        dll = clean_path(row.get(name))
        if dll is not None:
            return dll
    return None


def guess_instance(name: str, previous: dict) -> bool:
    """Whether a service whose ``Type`` was not read is a per-user instance.

    A baseline entry under the full name wins; then one under the template decides
    by its ``user_service``; with neither, only a name ending in
    ``INSTANCE_GUESS_SUFFIX`` (``_`` and at least 5 hex digits) is taken for an
    instance, so a name such as ``Agent_1`` keeps its own key.
    """
    template = INSTANCE_SUFFIX.sub("", name)
    if template == name or f"service:{name}" in previous:
        return False
    known = previous.get(f"service:{template}")
    if known is not None:
        return isinstance(known, dict) and known.get("user_service") is True
    return INSTANCE_GUESS_SUFFIX.search(name) is not None


def collect_services(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: entry})`` of the automatic services; per-user instances by template.

    A service whose registry values could not be read is named in not_checked and
    kept from the previous baseline, so a missing ``ServiceDll`` is no change. The
    reason names the value whose read failed when ``ErrorAt`` is one of
    ``SERVICE_READ_ORDER``. Without a previous entry, when the entry's row is the one
    not read, the values read before ``ErrorAt`` count as read (none without a known
    ``ErrorAt``): ``delayed`` not read is null and named in ``unread_fields``; for
    svchost.exe, whose target is a registry value, ``targets`` and ``facts`` are
    named when a value not read comes before the first non-empty one in the order of
    ``service_target``. A row whose ``Type`` is not a number names ``user_service``,
    which keeps its guessed value.

    When ``Type`` is not read, the key is, in this order: the full name when the
    baseline has ``service:<full name>``; the template (the name without
    ``INSTANCE_SUFFIX``) when the baseline has ``service:<template>`` with
    ``user_service`` true; the full name when it has that key otherwise; the template
    when the name ends in ``INSTANCE_GUESS_SUFFIX`` (``_`` and at least 5 hex
    digits); else the full name.
    """
    result = col.job("services", SERVICES_BODY)
    groups, failed, guessed = {}, set(), set()
    for row in result["rows"]:
        name = text(row.get("Name"))
        if name is None or (text(row.get("StartMode")) or "").casefold() != "auto":
            continue
        error = text(row.get("Error"))
        kind = row.get("Type")
        if isinstance(kind, int) and not isinstance(kind, bool):
            instance = bool(kind & USER_SERVICE_INSTANCE)
        else:
            instance = guess_instance(name, previous)
        entry_name = INSTANCE_SUFFIX.sub("", name) if instance else name
        key = f"service:{entry_name}"
        # The template itself may be listed next to its instances, under the same key.
        groups.setdefault(key, (entry_name, []))[1].append((instance, row))
        if not (isinstance(kind, int) and not isinstance(kind, bool)):
            guessed.add(key)  # user_service comes from the name, not from Type
        if error is not None:
            at = row.get("ErrorAt")
            reason = (f"registry values not read from {at} on: {error}"
                      if at in SERVICE_READ_ORDER else f"registry values not read: {error}")
            col.skip(f"services {name}", reason)
            failed.add(key)
    items = {}
    for key, (entry_name, pairs) in groups.items():
        if key in failed and key in previous:
            items[key] = copy.deepcopy(previous[key])
            items[key]["from_baseline"] = True  # not read in this run
            continue
        pairs.sort(key=lambda p: (text(p[1].get("Name")).casefold(), text(p[1].get("Name"))))
        rows = [row for _, row in pairs]
        instances = [row for flag, row in pairs if flag]
        instance = bool(instances)
        first = instances[0] if instances else rows[0]  # the first instance by name
        states = [text(r.get("State")) for r in rows]
        item = {
            "kind": "service",
            "location": f"HKLM\\SYSTEM\\CurrentControlSet\\Services\\{entry_name}",
            "name": entry_name,
            "display_name": text(first.get("DisplayName")),
            "command": text(first.get("PathName")),
            "state": "Running" if "Running" in states else text(first.get("State")),
            "delayed": system_component(first.get("DelayedAutostart")),  # 1 is delayed
            "user_service": instance,
            "enabled": True,
            "targets": [service_target(first, instance)],
        }
        if instance:
            item["template_start"] = first.get("TemplateStart")
        unread = set()
        if text(first.get("Error")) is not None:
            # Neither this run nor a baseline has the values not read, so a later
            # clean read of them is no change; those read before the error stay.
            # The target of svchost.exe is its ServiceDll, a registry value: when it
            # is unknown its facts stay unread and own is null. Any other target is
            # PathName, read from Win32_Service, and stays checked.
            if "DelayedAutostart" not in service_read_values(first):
                unread.add("delayed")
                item["delayed"] = None
            if file_name(target_path(first.get("PathName"))) == "svchost.exe"                     and service_target_unread(first, instance):
                unread.update(("targets", "facts"))
        if key in guessed:
            unread.add("user_service")
        if unread:
            item["unread_fields"] = sorted(unread)
        items[key] = item
    status, reason = entry_status("services", result, items, 0)
    col.record("services", status, reason)
    return status, items


def null_fact(path) -> dict:
    return {"path": path, **{field: None for field in FACT_FIELDS}, "program": None}


def program_matcher(programs: dict, dirs: dict):
    """``match(expanded path) -> program key or None``: the longest ``install_location``
    that is a folder prefix of the path, case-insensitively.

    A drive root and the four directories of ``dirs`` (``%ProgramFiles%`` and the
    others) never match.
    """
    skipped = {d.rstrip("\\/").casefold() for d in dirs.values() if text(d)}
    locations = []
    for source in PROGRAM_SOURCES:
        for key, item in (programs.get(source) or {}).items():
            location = clean_path(item.get("install_location") if isinstance(item, dict) else None)
            location = location.rstrip("\\/") if location else None
            if not location or DRIVE_ROOT.match(location) or location.casefold() in skipped:
                continue
            locations.append((location.casefold() + "\\", key))
    locations.sort(key=lambda entry: (-len(entry[0]), entry[1]))

    def match(expanded):
        expanded = text(expanded)
        if expanded is None:
            return None
        folded = expanded.strip().casefold()
        for prefix, key in locations:
            if folded.startswith(prefix):
                return key
        return None

    return match


def entry_own(item: dict, config: dict):
    """True only for a kind of ``own_kinds`` whose every target exists, is ``Valid``,
    is signed by a listed organisation and is no launcher; None when its facts
    were not read; else False."""
    if item.get("kind") not in config["own_kinds"]:
        return False
    if "facts" in (item.get("unread_fields") or []):
        return None
    targets, facts = item.get("targets") or [], item.get("facts") or []
    if not targets or None in targets or len(facts) != len(targets):
        return False
    for fact in facts:
        signer = text(fact.get("signer"))
        if fact.get("exists") is not True or fact.get("signature_status") != "Valid" \
                or signer is None or signer.casefold() not in config["signer_organizations"]:
            return False
        if {file_name(fact.get("path")), file_name(fact.get("expanded_path"))} \
                & config["launchers"]:
            return False
    return True


def collect_facts(col: Collector, current: dict, previous: dict, programs: dict,
                  config: dict) -> tuple[str, dict]:
    """Run ``file_facts`` for every target and set ``facts`` and ``own`` of each entry.

    Returns ``(status, {directory name: {"path": ...}})``; the directories are kept
    in the baseline, so a later run whose job failed still skips them when it
    matches programs. When the job failed, each entry takes the facts of its
    targets from the previous baseline (``facts_from_baseline``), with ``program``
    matched again; a target without a previous fact makes ``facts`` unread.
    """
    entries = [(source, key, item) for source in AUTOSTART_SOURCES
               for key, item in current[source].items() if not item.get("from_baseline")]
    paths, seen = [], set()
    for _, _, item in entries:
        for target in item["targets"]:
            if target is not None and target.casefold() not in seen:
                seen.add(target.casefold())
                paths.append(target)
    input_path = col.work / f"inventory-{col.stamp}.file_facts.input.json"
    try:
        input_path.write_text(json.dumps({"paths": paths}, ensure_ascii=True), encoding="utf-8")
    except OSError as exc:
        result = {"status": "unreadable", "rows": [],
                  "reason": f"the path list could not be written: {type(exc).__name__}: {exc}"}
    else:
        body = FILE_FACTS_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
        result = col.job("file_facts", body)
    status = result["status"]
    col.record("file_facts", status, result["reason"])
    read = status in READ_STATUSES

    dirs, files = {}, {}
    for row in result["rows"]:
        if row.get("Kind") == "dir" and text(row.get("Name")):
            dirs[text(row.get("Name"))] = {"path": text(row.get("Path"))}
        elif row.get("Kind") == "file" and text(row.get("Path")):
            files.setdefault(text(row.get("Path")).casefold(), row)
    if not read:
        dirs = {name: value for name, value in (previous.get("file_facts") or {}).items()
                if isinstance(value, dict)}
    match = program_matcher(programs, {n: v.get("path") for n, v in dirs.items()})

    errors = {}
    for source, key, item in entries:
        unread = set(item.get("unread_fields") or [])
        before = (previous.get(source) or {}).get(key) or {}
        known = {}
        if "facts" not in (before.get("unread_fields") or []):
            for fact in before.get("facts") or []:
                if isinstance(fact, dict) and fact.get("path") is not None:
                    known.setdefault(fact["path"], fact)
        facts = []
        if read:
            for target in item["targets"]:
                fact = null_fact(target)
                row = files.get(target.casefold()) if target is not None else None
                if row is not None and text(row.get("Error")) is not None:
                    # A file that could not be checked keeps its previous facts.
                    errors.setdefault(target, text(row.get("Error")))
                    if target in known:
                        fact.update({f: known[target].get(f) for f in FACT_FIELDS})
                        item["facts_from_baseline"] = True
                    else:
                        unread.add("facts")
                elif row is not None:
                    exists = row.get("Exists")
                    fact.update(
                        expanded_path=text(row.get("ExpandedPath")),
                        exists=exists if isinstance(exists, bool) else None,
                        signature_status=text(row.get("SignatureStatus")),
                        signer=text(row.get("Signer")),
                        company=text(row.get("Company")),
                    )
                fact["program"] = match(fact["expanded_path"])
                facts.append(fact)
        else:
            for target in item["targets"]:
                fact = null_fact(target)
                if target in known:
                    fact.update({f: known[target].get(f) for f in FACT_FIELDS})
                    fact["program"] = match(fact["expanded_path"])
                    item["facts_from_baseline"] = True
                elif target is not None:
                    unread.add("facts")
                facts.append(fact)
        item["facts"] = facts
        if unread:
            item["unread_fields"] = sorted(unread)
        item["own"] = entry_own(item, config)
    for target, error in errors.items():
        col.skip(f"file_facts {target}", error)
    return status, dirs


def skip_keyless(col: Collector, source: str, field: str, count: int) -> None:
    """Rows without their key field: named in not_checked, never silently dropped."""
    if count:
        col.skip(f"{source} without {field}",
                 f"{count} row(s) of {source} have no {field}, so they have no key")


def collect_features(col: Collector) -> tuple[str, dict]:
    """``(status, {key: item})`` of ``Win32_OptionalFeature``.

    An ``InstallState`` other than 1, 2 or 3 (4 is "unknown") gives ``state`` null,
    named in ``unread_fields``, and the number in ``install_state``.
    """
    result = col.job("optional_features", OPTIONAL_FEATURES_BODY)
    items, without_name = {}, 0
    for row in result["rows"]:
        name = text(row.get("Name"))
        if name is None:
            without_name += 1
            continue
        number = row.get("InstallState")
        if isinstance(number, bool) or not isinstance(number, int):
            number = None
        item = {"name": name, "caption": text(row.get("Caption")),
                "state": FEATURE_STATES.get(number)}
        if item["state"] is None:
            item["install_state"] = number
            item["unread_fields"] = ["state"]
        items.setdefault(f"feature:{name}", item)
    skip_keyless(col, "optional_features", "Name", without_name)
    status, reason = entry_status("optional_features", result, items, without_name)
    col.record("optional_features", status, reason)
    return status, items


def collect_capabilities(col: Collector, admin: bool) -> tuple[str, dict]:
    """``(status, {key: item})`` of ``Get-WindowsCapability``; only run with
    administrator rights, else unreadable without calling the job."""
    if not admin:
        col.record("capabilities", "unreadable", ADMIN_REASON)
        return "unreadable", {}
    result = col.job("capabilities", CAPABILITIES_BODY)
    items, without_name = {}, 0
    for row in result["rows"]:
        name = text(row.get("Name"))
        if name is None:
            without_name += 1
            continue
        item = {"name": name, "state": text(row.get("State"))}
        if item["state"] is None:
            item["unread_fields"] = ["state"]
        items.setdefault(f"capability:{name}", item)
    skip_keyless(col, "capabilities", "Name", without_name)
    status, reason = entry_status("capabilities", result, items, without_name)
    col.record("capabilities", status, reason)
    return status, items


def collect_drivers(col: Collector, patterns) -> tuple[str, dict, int | None]:
    """``(status, {key: item}, rows without InfName)`` of ``Win32_PnPSignedDriver``.

    ``third_party`` is whether ``inf_name`` matches one of ``patterns`` (case-folded
    fnmatch patterns); ``own`` is its opposite. With ``patterns`` None (the data file
    could not be read) ``third_party`` is null and unread, and ``own`` is false. The
    count of rows without ``InfName`` is None when the source was not read.
    """
    result = col.job("drivers", DRIVERS_BODY)
    items, without_inf, without_id = {}, 0, 0
    for row in result["rows"]:
        inf_name = text(row.get("InfName"))
        if inf_name is None:  # a device without a driver
            without_inf += 1
            continue
        device_id = text(row.get("DeviceID"))
        if device_id is None:
            without_id += 1
            continue
        item = {
            "device_name": text(row.get("DeviceName")),
            "class": text(row.get("DeviceClass")),
            "inf_name": inf_name,
            "provider": text(row.get("DriverProviderName")),
            "version": text(row.get("DriverVersion")),
            "date": text(row.get("DriverDate")),
            "signer": text(row.get("Signer")),
        }
        if patterns is None:
            item.update(third_party=None, own=False, unread_fields=["third_party"])
        else:
            folded = inf_name.strip().casefold()
            third_party = any(fnmatch.fnmatchcase(folded, p) for p in patterns)
            item.update(third_party=third_party, own=not third_party)
        items.setdefault(f"driver:{device_id}", item)
    skip_keyless(col, "drivers", "DeviceID", without_id)
    status, reason = entry_status("drivers", result, items, without_id)
    col.record("drivers", status, reason)
    return status, items, (without_inf if status in READ_STATUSES else None)


def parse_firewall_rule(value, builtin) -> dict:
    """The fields of one rule text ``v2.xx|Key=Value|...|``.

    A key that appears more than once (e.g. ``LPort``) gives a list, once a string,
    never a null placeholder for a missing key. ``protocol`` is a number,
    ``protocol_name`` its name when known. ``own`` is true when every field of
    ``builtin['required_fields']`` is there and ``Name`` starts with its
    ``name_prefix``; with ``builtin`` None (the data file could not be read) no rule
    is own. A text that is no ``v2.`` rule gives every field null, and ``rule`` and
    every compared field in ``unread_fields``, so a later run that reads it is no change.
    """
    rule = {field: None for field in FIREWALL_FIELDS}
    rule.update(protocol=None, protocol_name=None, version=None, own=False)
    raw = value if isinstance(value, str) else None
    if raw is None or not raw.startswith("v2."):
        rule["unread_fields"] = ["rule", *COMPARED_FIELDS["firewall_rules"]]
        return rule
    parts = raw.split("|")
    pairs = {}
    for part in parts[1:]:
        key, sep, data = part.partition("=")
        if sep:
            pairs.setdefault(key, []).append(data)
    rule["version"] = parts[0]
    for field, key in FIREWALL_FIELDS.items():
        values = pairs.get(key)
        if values:
            rule[field] = values[0] if len(values) == 1 else values
    protocol = pairs.get("Protocol")
    if protocol and len(protocol) == 1 and protocol[0].strip().isdigit():
        rule["protocol"] = int(protocol[0])
        rule["protocol_name"] = PROTOCOL_NAMES.get(rule["protocol"])
    if builtin is not None:
        name = rule["name"]
        rule["own"] = (all(key in pairs for key in builtin["required_fields"])
                       and isinstance(name, str) and name.startswith(builtin["name_prefix"]))
    return rule


def collect_firewall(col: Collector, builtin) -> tuple[str, dict]:
    """``(status, {key: item})`` of the three rule stores; a store without its key
    (``exists`` false) has no rules."""
    result = col.job("firewall_rules", FIREWALL_RULES_BODY)
    items, without_name = {}, 0
    for row in result["rows"]:
        store = text(row.get("store"))
        for value in as_list(row.get("values")):
            name = text(value.get("name")) if isinstance(value, dict) else None
            if store is None or name is None:
                without_name += 1
                continue
            items.setdefault(f"firewall:{store}:{name}",
                             {"store": store, **parse_firewall_rule(value.get("data"), builtin)})
    skip_keyless(col, "firewall_rules", "value name", without_name)
    col.record("firewall_rules", result["status"], result["reason"])
    return result["status"], items


def first_run_names(subject: str, first_run: list) -> list:
    """The entries of ``cert_windows_first_run`` whose name ``subject`` has:
    ``CN=<subject_cn>`` or starting with ``CN=<subject_cn>,``."""
    return [e for e in first_run if subject == f"CN={e['subject_cn']}"
            or subject.startswith(f"CN={e['subject_cn']},")]


def first_run_subject(item: dict, first_run: list) -> list:
    """The entries of ``cert_windows_first_run`` whose subject a ``machine_root``
    certificate has: self-signed, with the name as in ``first_run_names``. An unread
    field matches nothing."""
    subject = item.get("subject")
    if item.get("store") != "machine_root" or item.get("self_signed") is not True \
            or not isinstance(subject, str):
        return []
    return first_run_names(subject, first_run)


def first_run_undecided(item: dict, first_run: list) -> bool:
    """Whether a ``machine_root`` certificate's fields leave ``first_run_match``
    undecided: its subject unread, or the name of an entry with ``self_signed`` or
    the serial number unread."""
    subject = item.get("subject")
    if item.get("store") != "machine_root":
        return False
    if not isinstance(subject, str):
        return True
    return bool(first_run_names(subject, first_run)) and (
        item.get("self_signed") is None or not isinstance(item.get("serial"), str))


def first_run_match(item: dict, first_run: list) -> bool:
    """Whether a certificate is one of ``cert_windows_first_run``: its subject as in
    ``first_run_subject`` and its serial number, in upper case, that of the entry."""
    serial = item.get("serial")
    if not isinstance(serial, str):
        return False
    return any(serial.strip().upper() == e["serial"]
               for e in first_run_subject(item, first_run))


def _thumb_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(t, str) for t in value)


def first_run_reason(data) -> str | None:
    """None when ``data`` has the shape of the first-run file, else what is wrong."""
    if not isinstance(data, dict):
        return "it is not a JSON object"
    if data.get("schema_version") != FIRST_RUN_SCHEMA:
        return f"schema_version is {data.get('schema_version')!r}, not {FIRST_RUN_SCHEMA}"
    entries = data.get("entries")
    if not isinstance(entries, list):
        return "entries is not a list"
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) \
                or not all(isinstance(entry.get(field), str)
                           for field in ("subject_cn", "serial", "decided_at")) \
                or not _thumb_list(entry.get("matched")) \
                or not _thumb_list(entry.get("unchecked")):
            return f"entry {index} does not have the expected fields"
    return None


def load_first_run(state_dir) -> dict:
    """Read ``<state_dir>/ush-inventory.first-run.json``, never changing it.

    ``{"status": "none" | "read" | "unreadable", "entries": [...], "reason"}``: none
    when the file does not exist, unreadable (with the reason) when it cannot be read
    or has the wrong shape; entries only when read.
    """
    path = Path(state_dir).absolute() / FIRST_RUN_FILE
    if not path.exists():
        return {"status": "none", "entries": [], "reason": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return {"status": "unreadable", "entries": [], "reason": str(exc)}
    reason = first_run_reason(data)
    if reason is not None:
        return {"status": "unreadable", "entries": [], "reason": reason}
    return {"status": "read", "entries": data["entries"], "reason": None}


def save_first_run(state_dir, data, read_back=None) -> None:
    """Write ``data`` as ``<state_dir>/ush-inventory.first-run.json``.

    Through ``<name>.tmp``: it is read back (``read_back(path) -> str``, default a
    UTF-8 read) and compared before ``os.replace`` puts it in place, so a failed
    write leaves the old file as it was. Raises OSError or ValueError.
    """
    reason = first_run_reason(data)
    if reason is not None:
        raise ValueError(f"first-run data has the wrong shape: {reason}")
    state = Path(state_dir).absolute()
    tmp = state / f"{FIRST_RUN_FILE}.tmp"
    content = json.dumps(data, ensure_ascii=True, indent=1)
    read_back = read_back or (lambda path: path.read_text(encoding="utf-8"))
    try:
        state.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        if json.loads(read_back(tmp)) != json.loads(content):
            raise ValueError(f"{tmp.name} does not read back what was written")
        os.replace(tmp, state / FIRST_RUN_FILE)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def first_run_trusted(entry: dict, matching: list, items: dict) -> list:
    """The keys an entry of the first-run file trusts: every ``machine_root``
    certificate with its one ``matched`` thumbprint; with none matched, the one
    certificate of ``matching`` whose thumbprint is in ``unchecked``, if exactly one."""
    if len(entry["matched"]) == 1:
        pinned = entry["matched"][0].strip().upper()
        return [key for key, item in items.items()
                if item["store"] == "machine_root" and item["thumbprint"] == pinned]
    if entry["matched"]:
        return []
    unchecked = {thumbprint.strip().upper() for thumbprint in entry["unchecked"]}
    found = [key for key in matching if items[key]["thumbprint"] in unchecked]
    return found if len(found) == 1 else []


def collect_certificates(col: Collector, config: dict, first_run: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the five root stores.

    Details that ``Cert:`` did not give are null and named in ``unread_fields``.
    ``self_signed`` is subject equal to issuer; ``in_authroot`` whether the
    thumbprint is also in ``authroot``; ``own`` true in a managed store, or in
    ``machine_root`` with a shipped thumbprint.

    ``first_run`` is ``{"dir", "loaded", "decided_at"}``: the state directory, what
    ``load_first_run`` gave and the time of a new decision. The first-run file holds,
    per entry of ``cert_windows_first_run`` (subject and serial number), the decision
    of the first run that read the certificates: ``matched``, the thumbprints that
    matched, and ``unchecked``, those whose details left the match undecided. One
    file serves both modes and an entry is never changed. The entries in force are
    the file's entries on the list (all of them when the list could not be used).
    A certificate that matches an entry in force (``first_run_match``) carries
    ``windows_first_run``, false unless the entry trusts it (``first_run_trusted``):
    then it is true and ``own`` true, also with the details unread now. A list entry
    without a record gets a new decision only when the list could be used, the
    certificates were read and the file was read or absent; a failed write is named
    in ``not_checked`` and the decision still applies to this run. When the file
    cannot be read nothing is decided or written, and every certificate matching the
    list has ``windows_first_run`` null, named in ``unread_fields``.
    """
    result = col.job("root_certificates", ROOT_CERTIFICATES_BODY)
    managed = config["cert_windows_managed_stores"]
    shipped = config["cert_windows_shipped_thumbprints"]
    found, without_thumb = [], 0
    for row in result["rows"]:
        store = text(row.get("store"))
        for entry in as_list(row.get("certificates")):
            thumbprint = text(entry.get("thumbprint")) if isinstance(entry, dict) else None
            if store is None or thumbprint is None:
                without_thumb += 1
                continue
            found.append((store, thumbprint.strip().upper(), entry.get("details")))
    authroot = {thumbprint for store, thumbprint, _ in found if store == "authroot"}
    items = {}
    for store, thumbprint, details in found:
        item = {"store": store, "thumbprint": thumbprint}
        if isinstance(details, dict):
            item.update({field: text(details.get(field)) for field in CERT_DETAILS})
            unread = [field for field in CERT_DETAILS if item[field] is None]
        else:
            item.update({field: None for field in CERT_DETAILS})
            unread = list(CERT_DETAILS)
        subject, issuer = item["subject"], item["issuer"]
        item["self_signed"] = None if subject is None or issuer is None else subject == issuer
        if item["self_signed"] is None:
            unread.append("self_signed")
        item["in_authroot"] = thumbprint in authroot
        item["own"] = store in managed or (store == "machine_root" and thumbprint in shipped)
        if unread:
            item["unread_fields"] = unread
        items.setdefault(f"cert:{store}:{thumbprint}", item)
    apply_first_run(col, items, config["cert_windows_first_run"], first_run,
                    result["status"] in READ_STATUSES)
    skip_keyless(col, "root_certificates", "thumbprint", without_thumb)
    col.record("root_certificates", result["status"], result["reason"])
    return result["status"], items


def apply_first_run(col: Collector, items: dict, listed, first_run: dict,
                    read: bool) -> None:
    """Set ``windows_first_run`` (and ``own`` when trusted) on ``items`` from the
    first-run file, as ``collect_certificates`` describes; ``listed`` is
    ``cert_windows_first_run`` (None when the list could not be used), ``read``
    whether the certificates were read."""
    loaded = first_run["loaded"]
    if loaded["status"] == "unreadable":
        col.skip("first-run certificates",
                 f"{FIRST_RUN_FILE} in the state directory could not be read "
                 f"({loaded['reason']}), so no certificate is trusted as Windows' "
                 f"first-run certificate and no decision is written; deleting the "
                 f"file starts a new first run")
        for item in items.values():
            if first_run_match(item, listed or []):
                item["windows_first_run"] = None
                item["unread_fields"] = item.get("unread_fields", []) + ["windows_first_run"]
        return
    recorded = {(e["subject_cn"], e["serial"]): e for e in loaded["entries"]}
    can_decide = listed is not None and read
    new, trusted = [], set()
    for entry in (list(recorded.values()) if listed is None else listed):
        matching = [key for key, item in items.items() if first_run_match(item, [entry])]
        for key in matching:
            items[key]["windows_first_run"] = False
        record = recorded.get((entry["subject_cn"], entry["serial"]))
        if record is None:
            if not can_decide:
                continue
            record = {
                "subject_cn": entry["subject_cn"],
                "serial": entry["serial"],
                "decided_at": first_run["decided_at"],
                "matched": [items[key]["thumbprint"] for key in matching],
                "unchecked": [item["thumbprint"] for key, item in items.items()
                              if key not in matching and first_run_undecided(item, [entry])],
            }
            new.append(record)
        trusted.update(first_run_trusted(record, matching, items))
    for key in trusted:
        items[key].update(own=True, windows_first_run=True)
    if not new:
        return
    try:
        save_first_run(first_run["dir"], {"schema_version": FIRST_RUN_SCHEMA,
                                          "entries": loaded["entries"] + new})
    except (OSError, ValueError) as exc:
        col.skip("first-run certificates",
                 f"the first-run decision could not be saved to {FIRST_RUN_FILE} "
                 f"({exc}); it applies to this run only")


def parse_hosts(value) -> list:
    """The entries of a hosts file text: ``{address, hostname, line, duplicates}``.

    Lines are numbered from 1; ``#`` starts a comment; the first word is the
    address and every further word a host name. The first line of a (host name,
    address) pair wins; ``duplicates`` counts every later occurrence of the pair,
    also one in the same line.
    """
    entries = {}
    for number, line in enumerate((value or "").splitlines(), 1):
        words = re.split(r"[ \t]+", line.split("#", 1)[0].strip())
        if len(words) < 2:
            continue
        address = words[0]
        for hostname in words[1:]:
            pair = (hostname.casefold(), address)
            if pair in entries:
                entries[pair]["duplicates"] += 1
            else:
                entries[pair] = {"address": address, "hostname": hostname, "line": number,
                                 "duplicates": 0}
    return list(entries.values())


def same_dir(left: str, right: str) -> bool:
    """Whether two Windows folder paths are the same text, ignoring case and a
    trailing backslash."""
    return left.rstrip("\\").casefold() == right.rstrip("\\").casefold()


def collect_hosts(col: Collector, default_dir) -> tuple[str, dict]:
    """``(status, {key: item})`` of the hosts file; ``col.hosts_file`` gets its
    folder, whether it exists and whether the folder is the default one. A missing
    file is read and holds no entries."""
    result = col.job("hosts", HOSTS_BODY)
    rows = [row for row in result["rows"] if isinstance(row, dict)]
    status, reason = result["status"], result["reason"]
    if status == "read" and len(rows) != 1:
        status, reason = "unreadable", f"the hosts job gave {len(rows)} objects, not one"
    items = {}
    if status != "read":
        col.hosts_file = {"exists": None, "path_is_default": None,
                          "unread_fields": ["exists", "path_is_default"]}
        col.record("hosts", status, reason)
        return status, items
    row = rows[0]
    raw_dir = text(row.get("raw_dir"))
    exists = row.get("exists") if isinstance(row.get("exists"), bool) else None
    if exists is not False and not isinstance(row.get("text"), str):
        # A file that is there (or may be) without its text is not an empty file.
        col.hosts_file = {"exists": exists, "path_is_default": None,
                          "unread_fields": ["path_is_default"] if exists else
                          ["exists", "path_is_default"]}
        col.record("hosts", "unreadable", "the hosts job gave no text for the hosts file")
        return "unreadable", items
    hosts_file = {"exists": exists, "path_is_default": None}
    expanded = text(row.get("expanded_dir"))
    if raw_dir is not None and default_dir is not None:
        hosts_file["path_is_default"] = same_dir(raw_dir, default_dir)
        # The default folder written out in full (e.g. REG_SZ C:\Windows\...) is
        # still the default folder.
        system_root = text(row.get("system_root"))
        if not hosts_file["path_is_default"] and expanded and system_root:
            full_default = re.sub(r"%systemroot%", lambda _: system_root, default_dir,
                                  flags=re.IGNORECASE)
            hosts_file["path_is_default"] = same_dir(expanded, full_default)
    unread = [field for field, value in hosts_file.items() if value is None]
    if unread:
        hosts_file["unread_fields"] = unread
    col.hosts_file = {**hosts_file, "raw_dir": raw_dir, "expanded_dir": expanded,
                      "path": ntpath.join(expanded, "hosts") if expanded else None}
    for entry in parse_hosts(row.get("text") if isinstance(row.get("text"), str) else ""):
        items[f"hosts:{entry['hostname'].casefold()}:{entry['address']}"] = entry
    col.record("hosts", status, reason)
    return status, items


def collect_administrators(col: Collector) -> tuple[str, dict]:
    """``(status, {key: item})`` of the members of Administrators.

    ``enabled`` is read only for local and Microsoft accounts; a failed
    ``Get-LocalUser`` (``enabled_error``) and the ADSI method (no
    ``PrincipalSource``, no ``Enabled``, a name in another form) name the fields
    they could not read in ``unread_fields``. A member ``Get-LocalUser`` does not
    know (``is_user: false``) is a group, never unread. ``is_current`` is whether the
    member is the running account, ``null`` in ``unread_fields`` when its SID was not read.
    """
    result = col.job("administrators", ADMINISTRATORS_BODY)
    rows = [row for row in result["rows"] if isinstance(row, dict)]
    method = text(rows[0].get("method")) if rows else None
    col.current_sid = text(rows[0].get("current_sid")) if rows else None
    items, without_sid = {}, 0
    for row in rows:
        for entry in as_list(row.get("members")):
            sid = text(entry.get("sid")) if isinstance(entry, dict) else None
            if sid is None:
                without_sid += 1
                continue
            enabled = entry.get("enabled") if isinstance(entry.get("enabled"), bool) else None
            item = {"name": text(entry.get("name")),
                    "object_class": text(entry.get("object_class")),
                    "principal_source": text(entry.get("principal_source")),
                    "enabled": enabled,
                    "is_current": (None if col.current_sid is None
                                   else sid == col.current_sid)}
            unread = [] if col.current_sid is not None else ["is_current"]
            if method == "adsi":
                # ADSI names a member from its WinNT path, not as
                # Get-LocalGroupMember does, so the name is not compared.
                unread += ["name", "principal_source"]
                if item["object_class"] == "User":
                    unread.append("enabled")
            elif text(entry.get("enabled_error")) is not None or (
                    enabled is None and entry.get("is_user") is not False
                    and item["principal_source"] in ADMIN_SOURCES):
                unread.append("enabled")
            if unread:
                item["unread_fields"] = unread
            items.setdefault(f"admin:{sid}", item)
    skip_keyless(col, "administrators", "SID", without_sid)
    col.record("administrators", result["status"], result["reason"], method=method)
    return result["status"], items


def collect_defender(col: Collector, admin: bool) -> tuple[str, dict]:
    """``(status, {key: item})`` of the Defender exclusions; only run with
    administrator rights, else unreadable without calling the job.

    ``origin`` is ``policy`` for a value under the policy keys, else ``local``; a
    policy value missing from the effective lists is an entry too. A value hidden by
    Defender (``N/A: ...``) makes the source unreadable: it is never an entry.
    """
    if not admin:
        col.record("defender_exclusions", "unreadable", ADMIN_REASON, method=None)
        return "unreadable", {}
    result = col.job("defender_exclusions", DEFENDER_EXCLUSIONS_BODY)
    rows = [row for row in result["rows"] if isinstance(row, dict)]
    status, reason = result["status"], result["reason"]
    method = text(rows[0].get("method")) if rows else None
    items = {}
    for row in rows:
        policy = row.get("policy") if isinstance(row.get("policy"), dict) else None
        policy_error = text(row.get("policy_error"))
        if policy is None and policy_error is None:
            policy_error = "the job gave no policy lists"
        values = {kind: [v for v in map(text, as_list(row.get(kind))) if v is not None]
                  for kind in DEFENDER_TYPES}
        hidden = [v for kind in DEFENDER_TYPES for v in values[kind]
                  if v.startswith(DEFENDER_HIDDEN)]
        if hidden:
            status, reason = "unreadable", f"Defender hid the exclusions: {hidden[0]}"
            items = {}
            break
        if policy_error is not None:
            col.skip("defender_exclusions origin",
                     f"the policy exclusions could not be read, so origin is null: "
                     f"{policy_error}")
        for kind in DEFENDER_TYPES:
            from_policy = [v for v in map(text, as_list((policy or {}).get(kind)))
                           if v is not None]
            folded = {v.casefold() for v in from_policy}
            for value in values[kind] + from_policy:
                key = f"defender:{kind}:{value.casefold()}"
                if key in items:
                    continue
                item = {"type": kind, "value": value, "origin": None}
                if policy_error is None:
                    item["origin"] = "policy" if value.casefold() in folded else "local"
                else:
                    item["unread_fields"] = ["origin"]
                items[key] = item
    col.record("defender_exclusions", status, reason, method=method)
    return status, items


def collect(run_ps, work: Path, stamp: str, previous: dict, config: dict, admin: bool,
            first_run: dict):
    """Run every source: ``(statuses, {source: {key: item}}, collector)``.

    ``statuses`` and the returned map also hold ``file_facts`` (its directories), so
    they are kept in the baseline; ``startup_approved`` has a status and no items.
    The collector keeps the count of driver rows without ``InfName``.
    """
    col = Collector(run_ps, work, stamp)
    statuses, current = {}, {}
    statuses["win32_programs"], current["win32_programs"] = collect_win32(col, previous.get("win32_programs") or {})
    statuses["msix_programs"], current["msix_programs"] = collect_msix(col)

    statuses["run_keys"], current["run_keys"], slots = collect_run_keys(col)
    statuses["startup_folders"], current["startup_folders"], startup_slots = collect_startup(
        col, previous.get("startup_folders") or {})
    approved_status, approved_values = collect_approved(col)
    statuses["startup_approved"] = approved_status
    for source, source_slots in (("run_keys", slots), ("startup_folders", startup_slots)):
        apply_approved(current[source], source_slots, approved_status, approved_values,
                       previous.get(source) or {})
    statuses["scheduled_tasks"], current["scheduled_tasks"] = collect_tasks(
        col, previous.get("scheduled_tasks") or {}, admin)
    statuses["services"], current["services"] = collect_services(
        col, previous.get("services") or {})

    # Targets are matched to the programs as they will be saved: an unread
    # program source brings its items from the previous baseline.
    programs = baseline.merge_sources(
        {s: previous[s] for s in PROGRAM_SOURCES if s in previous},
        {s: current[s] for s in PROGRAM_SOURCES},
        {s: statuses[s] for s in PROGRAM_SOURCES},
    )
    statuses["file_facts"], current["file_facts"] = collect_facts(
        col, current, previous, programs, config)

    statuses["optional_features"], current["optional_features"] = collect_features(col)
    statuses["capabilities"], current["capabilities"] = collect_capabilities(col, admin)
    statuses["drivers"], current["drivers"], col.drivers_without_inf = collect_drivers(
        col, config["driver_third_party_inf"])

    statuses["firewall_rules"], current["firewall_rules"] = collect_firewall(
        col, config["firewall_builtin"])
    statuses["root_certificates"], current["root_certificates"] = collect_certificates(
        col, config, first_run)
    statuses["hosts"], current["hosts"] = collect_hosts(col, config["hosts_default_dir"])
    statuses["administrators"], current["administrators"] = collect_administrators(col)
    statuses["defender_exclusions"], current["defender_exclusions"] = collect_defender(
        col, admin)
    return statuses, current, col


# --- classification and comparison ---------------------------------------------
def is_own(source: str, item, own_kinds: set):
    """Part of Windows by the data file: an MSIX app by its signature kind, an
    autostart entry, a driver or an addition by its stored ``own`` (True, False or
    None); a component never."""
    if not isinstance(item, dict):
        return False
    if source in AUTOSTART_SOURCES or source == "drivers" or source in ADDITION_SOURCES:
        return item.get("own")
    if source != "msix_programs":
        return False
    return item.get("signature_kind") in own_kinds


def program_order(entry):
    """Newest install first, no date last, then by name."""
    item = entry[2]
    day = item.get("install_date")
    try:
        ordinal = date.fromisoformat(day).toordinal() if day else None
    except (TypeError, ValueError):
        ordinal = None
    name = item.get("name") or ""
    return (ordinal is None, -(ordinal or 0), name.casefold(), name, entry[1])


def build_programs(current: dict, own_kinds: set) -> tuple[list, int]:
    """Every program with an id: listed ones (``own: false``) first, then own ones."""
    entries = [(source, key, item) for source in PROGRAM_SOURCES
               for key, item in current.get(source, {}).items()]
    entries.sort(key=program_order)
    listed = [e for e in entries if not is_own(e[0], e[2], own_kinds)]
    own = [e for e in entries if is_own(e[0], e[2], own_kinds)]
    programs = []
    for number, (source, key, item) in enumerate(listed + own, 1):
        programs.append({"id": f"a{number}", "key": key, "source": source,
                         "own": is_own(source, item, own_kinds), **item})
    return programs, len(own)


def build_autostart(current: dict) -> tuple[list, dict, int]:
    """Every autostart entry with an id, listed ones (``own: false``) first.

    Returns the entries, ``{kind: number of own entries}`` and the number of entries
    with ``own: null``.
    """
    entries = [(source, key, item) for source in AUTOSTART_SOURCES
               for key, item in sorted(current.get(source, {}).items(),
                                       key=lambda pair: (pair[0].casefold(), pair[0]))]
    listed = [e for e in entries if e[2].get("own") is False]
    rest = [e for e in entries if e[2].get("own") is not False]
    autostart = [{"id": f"s{n}", "key": key, "source": source, **item}
                 for n, (source, key, item) in enumerate(listed + rest, 1)]
    per_kind = Counter(e[2].get("kind") for e in rest if e[2].get("own") is True)
    unknown = sum(1 for e in rest if e[2].get("own") is None)
    return autostart, dict(sorted(per_kind.items())), unknown


def text_order(value) -> tuple:
    """A sort key for text: case-insensitive, None last."""
    return (value is None, (value or "").casefold(), value or "")


def build_components(current: dict) -> tuple[list, int]:
    """Every feature and capability with an id; the listed ones (features
    ``enabled``, capabilities ``Installed``) first, each group by kind, then name.

    Returns the items and the number of listed ones.
    """
    kinds = list(COMPONENT_KINDS.values())
    entries = [{"key": key, "kind": kind, "source": source, **item}
               for source, kind in COMPONENT_KINDS.items()
               for key, item in (current.get(source) or {}).items()]
    entries.sort(key=lambda e: (kinds.index(e["kind"]), text_order(e.get("name")), e["key"]))
    listed = [e for e in entries if e.get("state") == LISTED_STATES[e["kind"]]]
    rest = [e for e in entries if e.get("state") != LISTED_STATES[e["kind"]]]
    return [{"id": f"f{n}", **e} for n, e in enumerate(listed + rest, 1)], len(listed)


def state_counts(items: dict, fixed=()) -> dict:
    """``{state: number}`` of a component source; a null state counts as ``unread``."""
    counts = Counter(item.get("state") or "unread" for item in items.values())
    result = {state: counts.pop(state, 0) for state in fixed}
    result.update(sorted(counts.items()))
    result.setdefault("unread", 0)
    return result


def build_drivers(current: dict) -> tuple[list, int]:
    """Every driver with an id; the listed ones (``own`` not true) first, each group
    by provider, then device name, null last. Returns the items and the listed count."""
    entries = [{"key": key, **item} for key, item in (current.get("drivers") or {}).items()]
    entries.sort(key=lambda e: (text_order(e.get("provider")),
                                text_order(e.get("device_name")), e["key"]))
    listed = [e for e in entries if e.get("own") is not True]
    rest = [e for e in entries if e.get("own") is True]
    return [{"id": f"d{n}", **e} for n, e in enumerate(listed + rest, 1)], len(listed)


def addition_order(entry: dict) -> tuple:
    """The sort key of an addition within its kind; the key breaks ties."""
    def field(name):
        value = entry.get(name)
        return text_order(value if value is None or isinstance(value, str) else str(value))

    kind = entry["kind"]
    if kind == "administrator":
        fields = ("name",)
    elif kind == "defender_exclusion":
        fields = ("value",)
    elif kind == "root_certificate":
        fields = ("subject", "thumbprint")
    elif kind == "firewall_rule":
        fields = ("store", "name")
    else:
        fields = ("hostname", "address")
    return (*(field(name) for name in fields), entry["key"])


def block_context(current: dict, defender_method) -> dict:
    """What the change-block rules of SKILL.md need beyond one item: the method
    of ``defender_exclusions`` and the root stores of each thumbprint."""
    stores: dict = {}
    for item in (current.get("root_certificates") or {}).values():
        thumb = item.get("thumbprint")
        if isinstance(thumb, str):
            stores.setdefault(thumb.upper(), set()).add(item.get("store"))
    return {"defender_method": defender_method, "cert_stores": stores}


def has_change_block(entry: dict, context: dict) -> bool:
    """Whether the addition goes to the group with a change block (SKILL.md,
    "Change blocks"). Not: a firewall rule outside ``local``; a certificate outside
    ``machine_root`` and ``user_root``, with ``in_authroot`` true or whose
    thumbprint is also in another root store; a Defender exclusion whose
    ``origin`` is not ``local`` (null included) or read by another method than
    ``preference``. An Administrators member always counts as one with a block:
    members are few and stay listed when additions are cut (plan 048), even one
    the "Rules" of SKILL.md forbid removing."""
    kind = entry["kind"]
    if kind == "firewall_rule":
        return entry.get("store") == "local"
    if kind == "root_certificate":
        thumb = entry.get("thumbprint")
        stores = (context["cert_stores"].get(thumb.upper(), set())
                  if isinstance(thumb, str) else set())
        return (entry.get("store") in ("machine_root", "user_root")
                and entry.get("in_authroot") is not True
                and stores <= {entry.get("store")})
    if kind == "defender_exclusion":
        return entry.get("origin") == "local" and context["defender_method"] == "preference"
    return True


def build_additions(current: dict, defender_method=None) -> tuple[list, int]:
    """Every item of the added-to-the-system sources with an id: the listed ones
    (``own`` not true) first, the rest after them. The listed ones are in two
    groups: those with a change block (``has_change_block``), then those without;
    within each group and within the rest by kind (``ADDITION_KINDS`` order), then
    by the kind's own order. Returns the items and the listed count."""
    kinds = list(ADDITION_KINDS.values())
    entries = [{"key": key, "kind": kind, "source": source, **item,
                "own": item.get("own") is True}
               for source, kind in ADDITION_KINDS.items()
               for key, item in (current.get(source) or {}).items()]
    entries.sort(key=lambda e: (kinds.index(e["kind"]), addition_order(e)))
    listed = [e for e in entries if not e["own"]]
    # Listed items with a change block (SKILL.md, "Change blocks") come first, so
    # the budget cuts the ones without a block before them.
    context = block_context(current, defender_method)
    listed = ([e for e in listed if has_change_block(e, context)]
              + [e for e in listed if not has_change_block(e, context)])
    rest = [e for e in entries if e["own"]]
    return [{"id": f"x{n}", **e} for n, e in enumerate(listed + rest, 1)], len(listed)


def summary_addition(entry: dict) -> dict:
    """One listed addition as it goes to the summary: a firewall rule and a root
    certificate with their main fields only (the subject cut to SUBJECT_MAX, and
    ``windows_first_run`` when the certificate has it), any
    other kind with every field but ``own`` (and ``unread_fields`` when there are)."""
    head = {k: entry.get(k) for k in ("id", "key", "kind")}
    if entry["kind"] == "firewall_rule":
        fields = {k: entry.get(k) for k in FIREWALL_SUMMARY}
    elif entry["kind"] == "root_certificate":
        fields = {k: entry.get(k) for k in CERT_SUMMARY}
        if isinstance(fields["subject"], str):
            fields["subject"] = fields["subject"][:SUBJECT_MAX]
        if "windows_first_run" in entry:
            fields["windows_first_run"] = entry["windows_first_run"]
    else:
        fields = {k: v for k, v in entry.items()
                  if k not in head and k not in ("own", "source", "unread_fields")}
    if entry.get("unread_fields"):
        fields["unread_fields"] = entry["unread_fields"]
    return {**head, **fields}


def summary_program(program: dict) -> dict:
    """One listed program as it goes to the summary: without ``install_location``,
    ``source`` and ``own`` (the detail file keeps them)."""
    return {k: v for k, v in program.items()
            if k not in ("install_location", "source", "own")}


def summary_fact(fact):
    """One file fact as it goes to the summary: without ``company``, and without
    ``expanded_path`` when it equals ``path``."""
    if not isinstance(fact, dict):
        return fact
    return {k: v for k, v in fact.items()
            if k != "company"
            and not (k == "expanded_path" and v == fact.get("path"))}


def summary_autostart(entry: dict) -> dict:
    """One listed autostart entry as it goes to the summary: without
    ``approved_raw`` (only for a rollback block) and ``display_name``, each fact
    slimmed by ``summary_fact``. The detail file keeps the full entry."""
    slim = {k: v for k, v in entry.items() if k not in ("approved_raw", "display_name")}
    if isinstance(slim.get("facts"), list):
        slim["facts"] = [summary_fact(fact) for fact in slim["facts"]]
    return slim


def facts_by_path(item: dict) -> dict:
    """``{path: fact}`` of an entry; the first fact of a path wins."""
    result = {}
    for fact in item.get("facts") or []:
        if isinstance(fact, dict) and fact.get("path") is not None:
            result.setdefault(fact["path"], fact)
    return result


def compare_autostart(before_items: dict, after_items: dict, skip_facts: bool,
                      skip_program: bool) -> dict:
    """``baseline.compare`` of the entry fields plus the facts of the targets both
    sides have, as ``facts[<path>].<field>``.

    ``facts`` is skipped when ``file_facts`` was not read in this run or either side
    has it in ``unread_fields``; ``program`` likewise when a program source was not
    read. A target added or removed is a change of ``targets`` only.
    """
    diff = baseline.compare(before_items, after_items, AUTOSTART_FIELDS)
    if skip_facts:
        return diff
    for key in sorted(k for k in after_items if k in before_items):
        before, after = before_items[key], after_items[key]
        unread = set(before.get("unread_fields") or []) | set(after.get("unread_fields") or [])
        if "facts" in unread:
            continue
        fields = [f for f in FACT_COMPARED
                  if not (f == "program" and (skip_program or "program" in unread))]
        before_facts = facts_by_path(before)
        for path, fact in facts_by_path(after).items():
            if path not in before_facts:
                continue
            for field in fields:
                old, new = before_facts[path].get(field), fact.get(field)
                if old != new:
                    diff["changed"].setdefault(key, {})[f"facts[{path}].{field}"] = {
                        "before": old, "after": new}
    return diff


def build_changes(previous: dict, current: dict, comparison: dict, own_kinds: set,
                  skip_facts: bool = False, skip_program: bool = False):
    """All changes with ids (listed ones first) and the counts of own-only changes.

    A change is listed when the item is not own (False or None) before or after it;
    a change of an item that is own on both sides (or on its only side) is counted
    only, in the totals and in ``by_source`` (every source, zeros included). A change
    of ``administrators`` carries no ``name``, and its changed ``name`` field is
    ``{"changed": true}`` without the values: a change carries no account name.
    """
    listed, own_only = [], []
    for source in SOURCES:
        if comparison.get(source) != "compared":
            continue
        before_items = previous.get(source) or {}
        after_items = current.get(source) or {}
        if source in AUTOSTART_SOURCES:
            diff = compare_autostart(before_items, after_items, skip_facts, skip_program)
        else:
            diff = baseline.compare(before_items, after_items, COMPARED_FIELDS[source])
        found = []
        for key in diff["added"]:
            found.append(("added", key, None, after_items[key], None))
        for key in diff["removed"]:
            found.append(("removed", key, before_items[key], None, None))
        for key, fields in diff["changed"].items():
            found.append(("changed", key, before_items[key], after_items[key], fields))
        found.sort(key=lambda f: (CHANGE_ORDER.index(f[0]), f[1]))
        for change, key, before, after, fields in found:
            sides = [side for side in (before, after) if side is not None]
            own = all(is_own(source, side, own_kinds) is True for side in sides)
            name_field = NAME_FIELDS.get(source, "name")
            # A Defender exclusion is named by its value, a path: it keeps the key
            # ``value``, which the report profile lists among the path keys.
            label = "value" if name_field == "value" else "name"
            entry = {"key": key, "source": source, "change": change,
                     label: (after or before).get(name_field), "own": own}
            if source == "administrators":
                # A change carries no account name: it has no ``name``, and a
                # changed name is only flagged as changed.
                del entry["name"]
                if fields is not None and "name" in fields:
                    fields = {**fields, "name": {"changed": True}}
            if fields is not None:
                entry["fields"] = fields
            (own_only if own else listed).append(entry)
    counts = {kind: sum(1 for e in own_only if e["change"] == kind) for kind in CHANGE_ORDER}
    counts["by_source"] = {
        source: {kind: sum(1 for e in own_only if e["source"] == source and e["change"] == kind)
                 for kind in CHANGE_ORDER}
        for source in SOURCES}
    changes = [{"id": f"c{n}", **entry} for n, entry in enumerate(listed + own_only, 1)]
    return changes, len(listed), counts


# --- summary and detail ------------------------------------------------------
def fit_budget(summary: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    The lists of ``CUT_LISTS`` are cut from their end, in stages, each stage only
    when the one before could not make the summary fit: ``programs`` (programs
    without an install date, then the oldest installs) down to ``PROGRAMS_MIN``
    (or all of them when there are fewer), then ``drivers``, ``components`` and
    ``additions`` (the items without a change block, from the end of their group,
    then the items with one) down to nothing, and last ``programs`` below
    ``PROGRAMS_MIN``. Each count key (``truncated``, ``truncated_drivers``,
    ``truncated_components``, ``truncated_additions``) counts the cut items.
    ``autostart`` and ``changes`` are never cut. A summary that is still too long
    is not cut at all and says so in not_checked.
    """
    text_out = dump(summary)
    originals = {name: summary.get(name) for name, _ in CUT_LISTS}
    if len(text_out) > SUMMARY_MAX_CHARS:
        count_keys = dict(CUT_LISTS)
        kept = {name: len(items or []) for name, items in originals.items()}
        stages = [("programs", min(PROGRAMS_MIN, kept["programs"]))]
        stages += [(name, 0) for name, _ in CUT_LISTS[1:]]
        stages.append(("programs", 0))
        fitted = False
        for name, floor in stages:
            if floor >= kept[name]:
                continue
            items = originals[name]

            def fits(count: int, items=items, name=name) -> bool:
                summary[name] = items[:count]
                summary[count_keys[name]] = len(items) - count
                return len(dump(summary)) <= SUMMARY_MAX_CHARS

            if fits(floor):
                # The most items that fit, by bisection; the kept count did not fit.
                low, high = floor, kept[name] - 1
                while low < high:
                    middle = (low + high + 1) // 2
                    if fits(middle):
                        low = middle
                    else:
                        high = middle - 1
                fits(low)
                fitted = True
                break
            kept[name] = floor
        if not fitted:
            # Something else is too long: cutting the lists would lose them for nothing.
            for name, count_key in CUT_LISTS:
                summary[name] = originals[name]
                summary[count_key] = 0
        text_out = dump(summary)
    if len(text_out) > SUMMARY_MAX_CHARS:
        summary["not_checked"].append({
            "what": "summary budget",
            "reason": f"the summary exceeds {SUMMARY_MAX_CHARS} characters and was not cut",
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
    parser.add_argument("--data-dir", default=None, help=datadir.HELP)
    parser.add_argument("--detail", metavar="ID",
                        help="print one item of the newest detail file and exit")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    return parser


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("inventory-*.detail.json"), key=lambda p: p.name)
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
    if args.detail is not None and args.detail_file:
        # The detail file is named explicitly: no data directory is needed.
        return show_detail(Path(), args.detail, Path(args.detail_file).absolute())
    try:
        data_dir = datadir.resolve(args.data_dir)
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
    summary_file = work / f"inventory-{stamp}.summary.json"
    detail_file = work / f"inventory-{stamp}.detail.json"

    admin = bool(is_admin())
    loaded = baseline.load(state, SKILL, admin)
    previous = loaded["sources"] if loaded["status"] == "read" else {}

    config, own_reason = load_own(DEFAULT_OWN_FILE)
    first_run = {"dir": state, "loaded": load_first_run(state),
                 "decided_at": now.isoformat(timespec="seconds")}
    statuses, current, col = collect(run_ps, work, stamp, previous, config, admin,
                                     first_run)
    if own_reason is not None:
        col.skip("windows-own.json", f"nothing is classified as part of Windows: "
                                     f"{own_reason}")
    own_kinds = config["msix_signature_kinds"]

    comparison = {name: baseline.comparison_state(previous, name, statuses[name])
                  for name in SOURCES}
    changes, listed_changes, own_changes = build_changes(
        previous, current, comparison, own_kinds,
        skip_facts=statuses["file_facts"] not in READ_STATUSES,
        skip_program=any(statuses[s] not in READ_STATUSES for s in PROGRAM_SOURCES),
    )
    programs, own_count = build_programs(current, own_kinds)
    listed_programs = [summary_program(p) for p in programs if not p["own"]]
    autostart, own_autostart, unknown = build_autostart(current)
    if unknown:
        # A service whose registry was not read has no known targets at all.
        registry = sum(1 for entry in autostart if entry.get("own") is None
                       and "targets" in (entry.get("unread_fields") or []))
        causes = []
        if registry:
            causes.append(f"{registry} of them because their registry values could not "
                          f"be read")
        if unknown - registry:
            causes.append(f"{unknown - registry} of them because their files could not "
                          f"be checked")
        col.skip("autostart facts",
                 f"{unknown} autostart entries of the kinds "
                 f"{', '.join(sorted(config['own_kinds']))} have no file facts "
                 f"({' and '.join(causes)}, and the baseline had none), so own is null; "
                 f"they are listed only in the detail file")
    listed_autostart = [summary_autostart(entry)
                        for entry in autostart if entry.get("own") is False]

    components, listed_count = build_components(current)
    components_read = any(statuses[s] in READ_STATUSES for s in COMPONENT_SOURCES)
    listed_components = [{k: c.get(k) for k in ("id", "key", "kind", "name", "state")}
                         for c in components[:listed_count]] if components_read else None
    component_counts = {
        "feature": (state_counts(current["optional_features"], FEATURE_STATES.values())
                    if statuses["optional_features"] in READ_STATUSES else None),
        "capability": (state_counts(current["capabilities"])
                       if statuses["capabilities"] in READ_STATUSES else None),
        "drivers_without_inf": col.drivers_without_inf,
    }
    drivers, listed_driver_count = build_drivers(current)
    drivers_read = statuses["drivers"] in READ_STATUSES
    driver_fields = ("id", "key", "device_name", "class", "provider", "version", "date",
                     "signer")
    listed_drivers = [{k: d.get(k) for k in driver_fields}
                      for d in drivers[:listed_driver_count]] if drivers_read else None

    defender_method = next((e.get("method") for e in col.sources
                            if e["name"] == "defender_exclusions"), None)
    additions, listed_addition_count = build_additions(current, defender_method)
    additions_read = any(statuses[s] in READ_STATUSES for s in ADDITION_SOURCES)
    listed_additions = [summary_addition(e) for e in additions[:listed_addition_count]] \
        if additions_read else None
    own_firewall = None
    if statuses["firewall_rules"] in READ_STATUSES:
        own_firewall = {store: sum(1 for item in current["firewall_rules"].values()
                                   if item.get("store") == store and item.get("own") is True)
                        for store in FIREWALL_STORES}
    own_certificates = None
    if statuses["root_certificates"] in READ_STATUSES:
        own_certificates = sum(1 for item in current["root_certificates"].values()
                               if item.get("own") is True)
    hosts_file = {k: v for k, v in (col.hosts_file or {}).items()
                  if k in ("exists", "path_is_default", "unread_fields")}

    detail = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "sources": col.sources,
        "comparison": comparison,
        "programs": programs,
        "autostart": autostart,
        "components": components,
        "drivers": drivers,
        "additions": additions,
        "hosts_file": col.hosts_file,
        "current_sid": col.current_sid,
        "changes": changes,
    }
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    new_baseline = {
        "schema_version": baseline.SCHEMA_VERSION,
        "skill": SKILL,
        "created_at": now.isoformat(),
        "elevated": admin,
        "sources": baseline.merge_sources(
            previous, current, {name: statuses[name] for name in current}),
    }
    save_reason = baseline.save(state, baseline.baseline_name(SKILL, admin), new_baseline)

    compared = loaded["status"] == "read"
    reasons = []
    if loaded["status"] == "unreadable":
        reasons.append(loaded["reason"])
        col.skip("baseline", f"the baseline could not be read, so nothing was compared "
                             f"(the file is kept): {loaded['reason']}")
    if save_reason is not None:
        reasons.append(f"not saved: {save_reason}")
        col.skip("baseline save", f"this run's baseline was not saved: {save_reason}")
    baseline_info = {
        "status": "compared" if compared else loaded["status"],
        "created_at": loaded["created_at"] if compared else None,
        "age_days": baseline.age_days(loaded["created_at"], now) if compared else None,
        "saved": save_reason is None,
        "reason": "; ".join(reasons) if reasons else None,
    }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "sources": col.sources,
        "not_checked": col.not_checked,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": 0,
        "truncated_drivers": 0,
        "truncated_components": 0,
        "truncated_additions": 0,
        "baseline": baseline_info,
        "comparison": comparison,
        "programs": listed_programs,
        "autostart": listed_autostart,
        "components": listed_components,
        "component_counts": component_counts,
        "drivers": listed_drivers,
        "additions": listed_additions,
        "hosts_file": hosts_file,
        "own_counts": {"programs": own_count, "autostart": own_autostart,
                       "unknown": unknown,
                       "drivers": len(drivers) - listed_driver_count if drivers_read else None,
                       "firewall_rules": own_firewall,
                       "root_certificates": own_certificates},
        "changes": changes[:listed_changes],
        "own_changes": own_changes,
    }
    text_out = fit_budget(summary)
    summary_file.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

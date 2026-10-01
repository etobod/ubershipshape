"""Read the effective state of the catalogued Windows settings and compare it with the
saved baseline (read-only).

Every setting comes from ``data/settings-catalogue.json`` (``catalogue.py`` validates
it). The script reads each one, works out its effective value and where it comes from,
and states whether it is on the catalogue's list of expected values. It never judges
and never changes anything: ``--block`` only prints commands for the user to paste.

Readers (one read-only PowerShell job per read type, all entries of a type in one job,
run through an injectable ``run_ps``; see ``skills/ush-common/scripts/psrun.py``). A job
that fails makes its entries ``not_read`` and is named in ``not_checked``; a job whose
catalogue type is not used is not run. Enumerations are written as text by the jobs;
the numeric form of Windows PowerShell 5.1 is mapped to the name as well, and an
unknown number stays a number.

- ``registry_values``: every location of every ``registry`` entry, ``EditionID`` of
  ``HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion`` and ``WinHttpSettings``
  (read type ``winhttp_proxy``). Each value is read through
  ``RegistryKey.OpenBaseKey(<hive>, Registry64)``, ``OpenSubKey`` read-only, raw
  (``DoNotExpandEnvironmentNames``). A row is ``present`` (with value and kind;
  ``Binary`` as hex text), ``absent`` (no key or no value) or ``unreadable``.
- ``wifi_adapter``: physical 802.11 adapters; only the driver key each device names is
  opened (enumerating ``Control\\Class`` throws ``SecurityException``).
- ``services`` (``Get-Service`` and ``DelayedAutostart``), ``firewall``
  (``Get-NetFirewallProfile`` of the ActiveStore for the effective state, the
  PersistentStore for the local setting and the RSOP store for the policy; a failed
  PersistentStore or RSOP read is kept apart from an empty one), ``security_center`` (``AntiVirusProduct``), ``defender``
  (``Get-MpComputerStatus``; ``Get-MpPreference`` fails when another antivirus runs),
  ``device_guard`` (``Win32_DeviceGuard``), ``powercfg`` (``/getactivescheme`` and
  ``/query SCHEME_CURRENT <subgroup> <setting>``, parsed here without depending on the
  system language), ``dns`` (``Get-DnsClientServerAddress`` of adapters that are up),
  ``appx`` (``Get-AppxPackage -Name``), ``delivery_optimization`` (``Get-DOConfig``),
  ``optional_features`` (``Win32_OptionalFeature``, works without administrator rights;
  the whole list, looked up here), ``shadow_storage`` (``Win32_ShadowStorage``, only run
  with administrator rights) and ``capability_usage`` (camera, microphone and location
  consent keys of HKCU).

Effective state of a ``registry`` entry: the locations in catalogue order; the first
``present`` one whose raw value (as text) is in its ``map`` (or that has no ``map``)
gives ``effective`` (mapped) and ``source`` (its role); an ``unreadable`` location
before it makes the entry ``not_read``; with nothing set, ``effective`` is the
catalogue ``default`` and ``source`` is ``default``. A ``wifi_adapter_value`` entry's
``effective`` is the list of adapter values sorted by driver key; no adapter makes it
``not_applicable``. Other readers give ``source: system`` (the state read from the
system itself); lists (DNS, shadow storage) are sorted so that order alone is never a
change.

States: ``not_read``, ``not_applicable`` (``applies_if`` not met), ``info``
(``expected`` null), ``default_unknown`` (a null default used while ``expected`` is
set), ``matches`` and ``differs``. The summary lists ``differs``, ``not_read``,
``default_unknown`` and ``info``; ``matches`` and ``not_applicable`` are counted there
and listed in the detail file.

Baseline: sources ``settings`` (key = entry id, compared field ``effective``) and
``capability_usage`` (key ``usage:<capability>:<packaged|nonpackaged>:<subkey>``,
compared field ``value``) in ``<data dir>/state/ush-settings.json`` (or
``ush-settings.elevated.json``). An entry that was not read keeps its previous
``effective`` in the saved baseline and is never compared, so a failed reader gives no
false change. Keys added to or removed from the catalogue are counted in
``catalogue_changes``, not listed as changes.

The summary goes to stdout and to ``work/settings-<UTC stamp>.summary.json``; the
detail file ``work/settings-<UTC stamp>.detail.json`` holds every entry with its
locations, every change and every usage item. ``--detail <id>`` prints one item of
the newest detail file. ``--block e3,e7`` prints a paste-ready block (and its
rollback) for those items of the newest detail file.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The shared modules live in skills/ush-common/scripts; catalogue.py lives next to this.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))
sys.path.insert(0, str(Path(__file__).absolute().parent))

import baseline  # called as baseline.save(...), so tests can patch it
import catalogue
import datadir
import psrun
from psrun import dump, ps_script, run_job

SKILL = "ush-settings"
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
DETAIL_SECTIONS = ("settings", "changes", "usage")
CATALOGUE_PATH = Path(__file__).absolute().parents[1] / "data" / "settings-catalogue.json"

BASELINE_SOURCE = "settings"
USAGE_SOURCE = "capability_usage"
COMPARED_FIELDS = ("effective",)
USAGE_FIELDS = ("value",)
READ_STATUSES = ("read", "empty")
ROW_STATUSES = ("present", "absent", "unreadable")
SYSTEM_SOURCE = "system"

STATES = ("differs", "not_read", "default_unknown", "info", "matches", "not_applicable")
# States listed in the summary, in this order; the others are only counted there.
LISTED_STATES = ("differs", "not_read", "default_unknown", "info")
LEVEL_ORDER = {"standard": 0, "strict": 1}

EDITION_LOCATION = {"hive": "HKLM", "path": "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
                    "name": "EditionID"}
WINHTTP_LOCATION = {
    "hive": "HKLM",
    "path": "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\Connections",
    "name": "WinHttpSettings",
}
HOME_EDITION_PREFIX = "Core"
WIFI_CLASS_ROOT = "SYSTEM\\CurrentControlSet\\Control\\Class\\"
CONSENT_STORE = ("Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager"
                 "\\ConsentStore")
CAPABILITIES = ("webcam", "microphone", "location")

# Numeric forms of the enumerations (ConvertTo-Json on PS 5.1 writes enums as numbers).
SERVICE_START_TYPES = {0: "Boot", 1: "System", 2: "Automatic", 3: "Manual", 4: "Disabled"}
FIREWALL_ENABLED = {0: False, 1: True, 2: "NotConfigured"}
DOWNLOAD_MODES = {0: "HttpOnly", 1: "Lan", 2: "Group", 3: "Internet", 99: "Simple",
                  100: "Bypass"}
INSTALL_STATES = {1: "Enabled", 2: "Disabled", 3: "absent"}
INSTALL_STATE_UNKNOWN = 4
ADDRESS_FAMILIES = {2: "IPv4", 23: "IPv6"}
ANTIVIRUS_ENABLED_BIT = 0x1000
WINHTTP_PROXY_FLAG = 0x2

# Jobs for the read types other than registry and wifi_adapter_value.
JOB_OF_TYPE = {
    "service": "services",
    "firewall_profile": "firewall",
    "security_center_av": "security_center",
    "defender_status": "defender",
    "device_guard": "device_guard",
    "power_scheme": "powercfg",
    "powercfg_setting": "powercfg",
    "dns": "dns",
    "appx": "appx",
    "delivery_optimization": "delivery_optimization",
    "optional_feature": "optional_features",
    "shadow_storage": "shadow_storage",
}
ADMIN_ONLY_JOBS = ("shadow_storage",)

# Reads one value; returns an ordered dictionary {status, value, kind, error}. A missing
# key or value is absent; an exception is unreadable with its text. DWord and QWord are
# returned unsigned, Binary as lower-case hex text, MultiString as a list.
PS_READ_VALUE = r"""function Read-RegValue($base, [string]$path, [string]$name) {
  $row = [ordered]@{ status = $null; value = $null; kind = $null; error = $null }
  $k = $null
  try {
    $k = $base.OpenSubKey($path, $false)
    if ($null -eq $k) { $row.status = 'absent'; return $row }
    $v = $k.GetValue($name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    if ($null -eq $v) { $row.status = 'absent'; return $row }
    $kind = [string]$k.GetValueKind($name)
    if ($v -is [byte[]]) { $v = [System.BitConverter]::ToString($v).Replace('-', '').ToLowerInvariant() }
    elseif ($kind -eq 'DWord') { $v = [System.BitConverter]::ToUInt32([System.BitConverter]::GetBytes([int]$v), 0) }
    elseif ($kind -eq 'QWord') { $v = [System.BitConverter]::ToUInt64([System.BitConverter]::GetBytes([long]$v), 0) }
    elseif ($v -is [string[]]) { $v = [object[]]$v }
    $row.status = 'present'
    $row.value = $v
    $row.kind = $kind
  } catch {
    $row.status = 'unreadable'
    $row.value = $null
    $row.kind = $null
    $row.error = [string]$_.Exception.Message
  } finally {
    if ($null -ne $k) { $k.Close() }
  }
  return $row
}
"""

# __INPUT__ is replaced by the quoted path of {"locations": [{hive, path, name}]}.
REGISTRY_VALUES_BODY = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$hives = @{
  'HKLM' = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
  'HKCU' = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
}
$rows = New-Object System.Collections.Generic.List[object]
foreach ($l in @($in.locations)) {
  $hive = [string]$l.hive
  $base = $hives[$hive]
  if ($null -eq $base) {
    $r = [ordered]@{ status = 'unreadable'; value = $null; kind = $null; error = 'unknown hive' }
  } else {
    $r = Read-RegValue $base ([string]$l.path) ([string]$l.name)
  }
  $rows.Add([pscustomobject]@{
    hive = $hive; path = [string]$l.path; name = [string]$l.name
    status = $r.status; value = $r.value; kind = $r.kind; error = $r.error
  })
}
foreach ($b in $hives.Values) { $b.Close() }
$result = $rows.ToArray()
"""

# __NAMES__ is replaced by a list of quoted value names. Only the driver key the device
# names is opened. A driver key that cannot be found gives unreadable rows.
WIFI_ADAPTER_BODY = r"""$names = @(__NAMES__)
$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$rows = New-Object System.Collections.Generic.List[object]
foreach ($a in @(Get-NetAdapter -Physical | Where-Object { $_.NdisPhysicalMedium -eq 9 })) {
  $driver = $null
  $failure = $null
  try {
    $driver = [string](Get-PnpDeviceProperty -InstanceId $a.PnPDeviceID -KeyName 'DEVPKEY_Device_Driver').Data
    if (-not $driver) { $driver = $null; $failure = 'the device names no driver key' }
  } catch { $failure = [string]$_.Exception.Message }
  foreach ($n in $names) {
    if ($null -ne $failure) {
      $r = [ordered]@{ status = 'unreadable'; value = $null; kind = $null; error = $failure }
    } else {
      $r = Read-RegValue $hklm (__CLASS_ROOT__ + $driver) $n
    }
    $rows.Add([pscustomobject]@{
      driver_key = $driver; name = [string]$n
      status = $r.status; value = $r.value; kind = $r.kind; error = $r.error
    })
  }
}
$hklm.Close()
$result = $rows.ToArray()
"""

# __NAMES__: quoted service names. A service that does not exist is absent (the cmdlet's
# ObjectNotFound); any other error is unreadable, never absent. DelayedAutostart is read
# from the service key; its status is reported apart.
SERVICES_BODY = r"""$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$rows = New-Object System.Collections.Generic.List[object]
foreach ($n in @(__NAMES__)) {
  $row = [ordered]@{ name = [string]$n; status = $null; start_type = $null; delayed_autostart = $null; delayed_status = $null; error = $null }
  $s = $null
  try {
    $s = Get-Service -Name $n -ErrorAction Stop
    $row.status = 'present'
  } catch {
    if ([string]$_.CategoryInfo.Category -eq 'ObjectNotFound') { $row.status = 'absent' }
    else { $row.status = 'unreadable'; $row.error = [string]$_.Exception.Message }
  }
  if ($row.status -eq 'present') {
    $row.start_type = [string]$s.StartType
    $d = Read-RegValue $hklm ('SYSTEM\CurrentControlSet\Services\' + [string]$s.ServiceName) 'DelayedAutostart'
    $row.delayed_status = $d.status
    if ($d.status -eq 'present') { $row.delayed_autostart = $d.value }
  }
  $rows.Add([pscustomobject]$row)
}
$hklm.Close()
$result = $rows.ToArray()
"""

FIREWALL_BODY = r"""$local = $null
try {
  $local = @{}
  foreach ($p in @(Get-NetFirewallProfile -PolicyStore PersistentStore -ErrorAction Stop)) {
    $local[[string]$p.Name] = [string]$p.Enabled
  }
} catch { $local = $null }
$policy_read = $true
$policy = @{}
try {
  foreach ($p in @(Get-NetFirewallProfile -PolicyStore RSOP -ErrorAction Stop)) {
    $policy[[string]$p.Name] = [string]$p.Enabled
  }
} catch { $policy_read = $false; $policy = @{} }
$result = @(foreach ($p in @(Get-NetFirewallProfile -PolicyStore ActiveStore)) {
  $own = $null
  if ($null -ne $local -and $local.ContainsKey([string]$p.Name)) { $own = $local[[string]$p.Name] }
  $pol = $null
  if ($policy.ContainsKey([string]$p.Name)) { $pol = $policy[[string]$p.Name] }
  [pscustomobject]@{ profile = [string]$p.Name; enabled = [string]$p.Enabled; local_enabled = $own
                     policy_read = $policy_read; policy_enabled = $pol }
})
"""

SECURITY_CENTER_BODY = r"""$result = @(foreach ($p in @(Get-CimInstance -Namespace 'root\SecurityCenter2' -ClassName AntiVirusProduct)) {
  [pscustomobject]@{ display_name = [string]$p.displayName; product_state = [long]$p.productState }
})
"""

DEFENDER_BODY = r"""$s = Get-MpComputerStatus
$result = @([pscustomobject]@{
  AMRunningMode = [string]$s.AMRunningMode
  RealTimeProtectionEnabled = $s.RealTimeProtectionEnabled
  IsTamperProtected = $s.IsTamperProtected
})
"""

DEVICE_GUARD_BODY = r"""$result = @(foreach ($g in @(Get-CimInstance -Namespace 'root\Microsoft\Windows\DeviceGuard' -ClassName Win32_DeviceGuard)) {
  [pscustomobject]@{ SecurityServicesRunning = [int[]]@(foreach ($v in @($g.SecurityServicesRunning)) { if ($null -ne $v) { [int]$v } }) }
})
"""

# __QUERIES__ is replaced by one "Add-Query '<subgroup>' '<setting>'" line per setting.
POWERCFG_BODY = r"""$rows = New-Object System.Collections.Generic.List[object]
function Add-Query([string]$sub, [string]$set) {
  $t = (& powercfg.exe /query SCHEME_CURRENT $sub $set | Out-String)
  $rows.Add([pscustomobject]@{ query = ($sub + ' ' + $set); text = $t; exit_code = $LASTEXITCODE })
}
$t = (& powercfg.exe /getactivescheme | Out-String)
$rows.Add([pscustomobject]@{ query = 'active'; text = $t; exit_code = $LASTEXITCODE })
__QUERIES__
$result = $rows.ToArray()
"""

DNS_BODY = r"""$up = @(foreach ($a in @(Get-NetAdapter)) { if ([string]$a.Status -eq 'Up') { [int]$a.ifIndex } })
$result = @(foreach ($d in @(Get-DnsClientServerAddress)) {
  if ($up -contains [int]$d.InterfaceIndex) {
    [pscustomobject]@{
      interface = [string]$d.InterfaceAlias
      family = [int]$d.AddressFamily
      servers = [string[]]@(foreach ($s in @($d.ServerAddresses)) { if ($s) { [string]$s } })
    }
  }
})
"""

APPX_BODY = r"""$result = @(foreach ($n in @(__NAMES__)) {
  $p = @(Get-AppxPackage -Name $n)
  [pscustomobject]@{
    name = [string]$n
    status = $(if ($p.Count -gt 0) { 'present' } else { 'absent' })
    versions = [string[]]@(foreach ($x in $p) { [string]$x.Version })
  }
})
"""

DELIVERY_OPTIMIZATION_BODY = r"""$c = Get-DOConfig
$result = @([pscustomobject]@{ DownloadMode = [string]$c.DownloadMode })
"""

OPTIONAL_FEATURES_BODY = r"""$result = @(foreach ($f in @(Get-CimInstance -ClassName Win32_OptionalFeature)) {
  [pscustomobject]@{ Name = [string]$f.Name; InstallState = [int]$f.InstallState }
})
"""

SHADOW_STORAGE_BODY = r"""$letters = @{}
foreach ($v in @(Get-CimInstance -ClassName Win32_Volume)) { $letters[[string]$v.DeviceID] = [string]$v.DriveLetter }
$result = @(foreach ($s in @(Get-CimInstance -ClassName Win32_ShadowStorage)) {
  $id = [string]$s.Volume.DeviceID
  $letter = $letters[$id]
  [pscustomobject]@{
    volume = $(if ($letter) { $letter } else { $id })
    max_space = [uint64]$s.MaxSpace
    used_space = [uint64]$s.UsedSpace
    allocated_space = [uint64]$s.AllocatedSpace
  }
})
"""

# __ROOT__ is the quoted ConsentStore path, __CAPS__ the quoted capability names. Packages
# are the subkeys of each capability; programs are the subkeys of its NonPackaged key.
# A subkey that cannot be read gives a row with its error.
CAPABILITY_USAGE_BODY = r"""$hkcu = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
$rows = New-Object System.Collections.Generic.List[object]
function Add-Usage([string]$path, [string]$cap, [bool]$packaged, [string]$sub) {
  $row = [ordered]@{ capability = $cap; packaged = $packaged; subkey = $sub; value = $null; last_used_start = $null; last_used_stop = $null; error = $null }
  $k = $null
  try {
    $k = $hkcu.OpenSubKey($path + '\' + $sub, $false)
    if ($null -ne $k) {
      $v = $k.GetValue('Value', $null)
      if ($null -ne $v) { $row.value = [string]$v }
      $a = $k.GetValue('LastUsedTimeStart', $null)
      if ($null -ne $a) { $row.last_used_start = [long]$a }
      $b = $k.GetValue('LastUsedTimeStop', $null)
      if ($null -ne $b) { $row.last_used_stop = [long]$b }
    }
  } catch { $row.error = [string]$_.Exception.Message
  } finally { if ($null -ne $k) { $k.Close() } }
  $rows.Add([pscustomobject]$row)
}
foreach ($cap in @(__CAPS__)) {
  $capPath = __ROOT__ + '\' + $cap
  $ck = $hkcu.OpenSubKey($capPath, $false)
  if ($null -eq $ck) { continue }
  try {
    foreach ($sub in @($ck.GetSubKeyNames())) {
      if ($sub -eq 'NonPackaged') {
        $nk = $ck.OpenSubKey($sub, $false)
        if ($null -ne $nk) {
          try { $programs = @($nk.GetSubKeyNames()) } finally { $nk.Close() }
          foreach ($p in $programs) { Add-Usage ($capPath + '\NonPackaged') $cap $false $p }
        }
      } else { Add-Usage $capPath $cap $true $sub }
    }
  } finally { $ck.Close() }
}
$hkcu.Close()
$result = $rows.ToArray()
"""


# --- values ----------------------------------------------------------------
def text(value):
    """A non-empty string, or None; other types become their text."""
    if value is None:
        return None
    value = str(value)
    return value if value.strip() else None


def fold(*parts) -> tuple:
    """A case-insensitive key of location parts."""
    return tuple((text(p) or "").casefold() for p in parts)


def raw_key(value) -> str:
    """The raw registry value as text, the way ``map`` keys are written."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=True)


def same(left, right) -> bool:
    """Equal values of the same kind: ``True`` is not ``1`` here."""
    return isinstance(left, bool) == isinstance(right, bool) and left == right


def is_in(value, choices) -> bool:
    return any(same(value, choice) for choice in choices)


def location_label(location: dict) -> str:
    return f"{location.get('hive')}\\{location.get('path')}\\{location.get('name')}"


def as_int(value):
    """An integer from an int or a decimal string; None otherwise (bool is not an int)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    return None


def enum_name(value, names: dict):
    """The name of a numeric enum value; text stays text, an unknown number stays a number."""
    number = as_int(value) if not isinstance(value, str) else None
    if number is not None:
        return names.get(number, number)
    return value


def firewall_state(value):
    """A firewall profile's ``Enabled``: true/false, "NotConfigured", or None when absent."""
    if isinstance(value, str) and value.strip().casefold() in ("true", "false"):
        return value.strip().casefold() == "true"
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool):
        return value
    return enum_name(value, FIREWALL_ENABLED)


def firewall_policy(policy_read, value):
    """A firewall profile's policy (RSOP) state: None when the RSOP store was not read.

    A profile the RSOP store does not have, or one it has as "NotConfigured", means no
    policy ("NotConfigured"); otherwise the policy's ``Enabled`` as ``firewall_state``.
    """
    if policy_read is not True:
        return None
    state = firewall_state(value)
    return "NotConfigured" if state is None else state


def as_list(value) -> list:
    """A PowerShell field that may be null, one value or a list, as a list."""
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


# --- pure parsers ------------------------------------------------------------
GUID_NAME_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"\s+\((.*)\)\s*$")
INDEX_LINE_RE = re.compile(r"0x([0-9a-fA-F]{8})\s*$")


def parse_active_scheme(text_in):
    """``{guid, name}`` from ``powercfg /getactivescheme`` in any language, or None.

    The line ends with the GUID and the scheme name in parentheses.
    """
    if not isinstance(text_in, str):
        return None
    for line in text_in.splitlines():
        match = GUID_NAME_RE.search(line)
        if match:
            return {"guid": match.group(1), "name": match.group(2)}
    return None


def parse_query_indexes(text_in):
    """``(ac, dc)`` from ``powercfg /query``, or None.

    The current AC and DC indexes are the last two lines ending with ``0x`` and eight hex
    digits (the words before them depend on the system language). Fewer than two such
    lines is None.
    """
    if not isinstance(text_in, str):
        return None
    values = []
    for line in text_in.splitlines():
        match = INDEX_LINE_RE.search(line)
        if match:
            values.append(int(match.group(1), 16))
    if len(values) < 2:
        return None
    return values[-2], values[-1]


def parse_winhttp(hex_text):
    """``direct``, the proxy server text, or None from ``WinHttpSettings`` as hex text.

    Layout: flags DWORD at offset 8 (bit 2 = a proxy is set), then the server length
    DWORD at offset 12 and the server text. No value, or no proxy bit, is ``direct``; a
    value too short for what it claims is None.
    """
    if hex_text is None:
        return "direct"
    try:
        data = bytes.fromhex(str(hex_text))
    except ValueError:
        return None
    if len(data) < 12:
        return None
    flags = int.from_bytes(data[8:12], "little")
    if not flags & WINHTTP_PROXY_FLAG:
        return "direct"
    if len(data) < 16:
        return None
    length = int.from_bytes(data[12:16], "little")
    server = data[16:16 + length]
    if len(server) < length:
        return None
    return server.decode("ascii", errors="replace")


def filetime_iso(value):
    """A FILETIME integer (100-ns ticks since 1601 UTC) as ISO UTC; 0 or none is None."""
    number = as_int(value)
    if number is None or number <= 0:
        return None
    try:
        moment = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(
            microseconds=number // 10)
    except OverflowError:
        return None
    return moment.isoformat()


# --- collection ------------------------------------------------------------
class Collector:
    """Runs the jobs of one collection and keeps the sources and not_checked."""

    def __init__(self, run_ps, work: Path, stamp: str):
        self.run_ps = run_ps
        self.work = work
        self.stamp = stamp
        self.sources = []
        self.not_checked = []

    def job(self, job: str, body: str, depth: int = 4) -> dict:
        out_path = self.work / f"settings-{self.stamp}.{job}.json"
        script = ps_script(PS_READ_VALUE + body, out_path, depth)
        return run_job(self.run_ps, job, script, out_path)

    def record(self, name: str, status: str, reason=None) -> None:
        """One entry of sources; an unreadable source is also an item of not_checked."""
        self.sources.append({"name": name, "status": status, "reason": reason})
        if status == "unreadable":
            self.skip(name, reason)

    def skip(self, what: str, reason: str) -> None:
        self.not_checked.append({"what": what, "reason": reason})


def registry_locations(entries: list) -> list:
    """Every registry location of the catalogue plus ``EditionID`` (and ``WinHttpSettings``
    when a ``winhttp_proxy`` entry exists), once each."""
    result, seen = [], set()
    candidates = [loc for entry in entries if entry["read"]["type"] == "registry"
                  for loc in entry["read"]["locations"]] + [EDITION_LOCATION]
    if any(entry["read"]["type"] == "winhttp_proxy" for entry in entries):
        candidates.append(WINHTTP_LOCATION)
    for location in candidates:
        key = fold(location["hive"], location["path"], location["name"])
        if key not in seen:
            seen.add(key)
            result.append({k: location[k] for k in ("hive", "path", "name")})
    return result


def collect_registry(col: Collector, entries: list) -> dict:
    """Run ``registry_values``; return ``{folded location: row}``.

    When the job fails, the index is empty and every location reads as unreadable
    with the job's reason.
    """
    locations = registry_locations(entries)
    input_path = col.work / f"settings-{col.stamp}.registry_values.input.json"
    try:
        input_path.write_text(json.dumps({"locations": locations}, ensure_ascii=True),
                              encoding="utf-8")
    except OSError as exc:
        result = {"status": "unreadable", "rows": [],
                  "reason": f"the location list could not be written: "
                            f"{type(exc).__name__}: {exc}"}
    else:
        body = REGISTRY_VALUES_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
        result = col.job("registry_values", body)
    col.record("registry_values", result["status"], result["reason"])
    index = {}
    for row in result["rows"]:
        index.setdefault(fold(row.get("hive"), row.get("path"), row.get("name")), row)
    missing = ("registry_values was not read: " + (result["reason"] or "")
               if result["status"] not in READ_STATUSES
               else "no row for this location in the registry_values output")
    return {"index": index, "missing": missing,
            "read": result["status"] in READ_STATUSES}


def location_row(registry: dict, location: dict) -> dict:
    """``{status, value, kind, error}`` of one location; no row is unreadable."""
    row = registry["index"].get(fold(location["hive"], location["path"], location["name"]))
    if row is None:
        return {"status": "unreadable", "value": None, "kind": None,
                "error": registry["missing"]}
    status = row.get("status")
    if status not in ROW_STATUSES:
        return {"status": "unreadable", "value": None, "kind": None,
                "error": f"unexpected status {status!r} in the registry_values output"}
    if status != "present":
        return {"status": status, "value": None, "kind": None,
                "error": text(row.get("error")) if status == "unreadable" else None}
    return {"status": "present", "value": row.get("value"), "kind": text(row.get("kind")),
            "error": None}


def read_edition(col: Collector, registry: dict):
    """``EditionID`` as text, or None (named in not_checked) when it was not read."""
    row = location_row(registry, EDITION_LOCATION)
    value = text(row["value"]) if row["status"] == "present" else None
    if value is None:
        reason = {"absent": "the value is not there"}.get(
            row["status"], row["error"] or "the value is not text")
        col.skip("EditionID", f"{location_label(EDITION_LOCATION)} was not read ({reason}); "
                              "from_policy_on_home is null for policy-sourced settings")
    return value


def unique_names(entries: list, read_type: str, param: str = "name") -> list:
    """The ``read.<param>`` values of the entries of ``read_type``, once each (any case)."""
    names = []
    for entry in entries:
        if entry["read"]["type"] == read_type:
            name = entry["read"][param]
            if name.casefold() not in (n.casefold() for n in names):
                names.append(name)
    return names


def quoted_list(names: list) -> str:
    return ", ".join(psrun.ps_quote(name) for name in names)


def collect_wifi(col: Collector, entries: list):
    """Run ``wifi_adapter`` when a catalogue entry needs it; return the job result or None."""
    names = unique_names(entries, "wifi_adapter_value")
    if not names:
        return None
    body = (WIFI_ADAPTER_BODY
            .replace("__NAMES__", quoted_list(names))
            .replace("__CLASS_ROOT__", psrun.ps_quote(WIFI_CLASS_ROOT)))
    result = col.job("wifi_adapter", body)
    col.record("wifi_adapter", result["status"], result["reason"])
    return result


def job_bodies(entries: list) -> dict:
    """``{job: body}`` of the typed readers the catalogue uses."""
    used = {entry["read"]["type"] for entry in entries}
    bodies = {}
    if "service" in used:
        bodies["services"] = SERVICES_BODY.replace(
            "__NAMES__", quoted_list(unique_names(entries, "service")))
    if "firewall_profile" in used:
        bodies["firewall"] = FIREWALL_BODY
    if "security_center_av" in used:
        bodies["security_center"] = SECURITY_CENTER_BODY
    if "defender_status" in used:
        bodies["defender"] = DEFENDER_BODY
    if "device_guard" in used:
        bodies["device_guard"] = DEVICE_GUARD_BODY
    if used & {"power_scheme", "powercfg_setting"}:
        queries, seen = [], set()
        for entry in entries:
            if entry["read"]["type"] == "powercfg_setting":
                pair = (entry["read"]["subgroup"], entry["read"]["setting"])
                if fold(*pair) not in seen:
                    seen.add(fold(*pair))
                    queries.append("Add-Query " + " ".join(psrun.ps_quote(p) for p in pair))
        bodies["powercfg"] = POWERCFG_BODY.replace("__QUERIES__", "\n".join(queries))
    if "dns" in used:
        bodies["dns"] = DNS_BODY
    if "appx" in used:
        bodies["appx"] = APPX_BODY.replace("__NAMES__",
                                           quoted_list(unique_names(entries, "appx")))
    if "delivery_optimization" in used:
        bodies["delivery_optimization"] = DELIVERY_OPTIMIZATION_BODY
    if "optional_feature" in used:
        bodies["optional_features"] = OPTIONAL_FEATURES_BODY
    if "shadow_storage" in used:
        bodies["shadow_storage"] = SHADOW_STORAGE_BODY
    return bodies


def collect_typed(col: Collector, entries: list, admin: bool) -> dict:
    """Run the typed readers; return ``{job: result}`` (a job not run has status
    ``needs_admin``)."""
    results = {}
    for job, body in job_bodies(entries).items():
        if job in ADMIN_ONLY_JOBS and not admin:
            ids = [e["id"] for e in entries if JOB_OF_TYPE.get(e["read"]["type"]) == job]
            reason = "needs administrator rights; the job was not run"
            results[job] = {"status": "needs_admin", "reason": reason, "rows": []}
            col.sources.append({"name": job, "status": "not_run", "reason": reason})
            col.skip(job, f"{', '.join(ids)} not read: {reason} (run again from an "
                          "elevated shell to read it)")
            continue
        result = col.job(job, body)
        col.record(job, result["status"], result["reason"])
        results[job] = result
    return results


def collect_usage(col: Collector) -> dict:
    body = (CAPABILITY_USAGE_BODY
            .replace("__ROOT__", psrun.ps_quote(CONSENT_STORE))
            .replace("__CAPS__", quoted_list(CAPABILITIES)))
    result = col.job(USAGE_SOURCE, body)
    col.record(USAGE_SOURCE, result["status"], result["reason"])
    return result


# --- effective state -----------------------------------------------------------
def not_read(reason: str, **extra) -> dict:
    return {"effective": None, "source": None, "locations": None, "hkcu": False,
            "not_read": reason} | extra


def read_value(effective, source=SYSTEM_SOURCE, **extra) -> dict:
    return {"effective": effective, "source": source, "locations": None, "hkcu": False,
            "not_read": None} | extra


def evaluate_registry(entry: dict, registry: dict, col: Collector) -> dict:
    """Effective value and source of a registry entry, with its locations for the detail.

    ``hkcu`` is True when a location that decided the value, or one consulted before
    it, lies in HKCU (with no location set, every location decided the default).
    ``source_location`` is the index of the deciding location (None for the default).
    """
    locations, decided, hkcu = [], None, False
    result = {"effective": entry.get("default"), "source": "default", "not_read": None,
              "source_location": None}
    for index, location in enumerate(entry["read"]["locations"]):
        row = location_row(registry, location)
        locations.append({k: location[k] for k in ("hive", "path", "name", "role")} | row)
        if decided is not None:
            continue
        hkcu = hkcu or location["hive"] == "HKCU"
        if row["status"] == "unreadable":
            decided = location
            result = {"effective": None, "source": None, "source_location": None,
                      "not_read": f"{location_label(location)} could not be read: "
                                  f"{row['error'] or 'no reason given'}"}
            if registry["read"]:  # a failed job is already one item of not_checked
                col.skip(f"registry {location_label(location)}",
                         row["error"] or "not read")
        elif row["status"] == "present":
            mapping = location.get("map")
            if mapping is None:
                decided = location
                result = {"effective": row["value"], "source": location["role"],
                          "not_read": None, "source_location": index}
            elif raw_key(row["value"]) in mapping:
                decided = location
                result = {"effective": mapping[raw_key(row["value"])],
                          "source": location["role"], "not_read": None,
                          "source_location": index}
    return result | {"locations": locations, "hkcu": hkcu}


def adapter_order(driver_key):
    key = text(driver_key) or ""
    return (key.casefold(), key)


def evaluate_wifi(entry: dict, wifi, col: Collector) -> dict:
    """The list of adapter values sorted by driver key; no adapter is not applicable."""
    base = {"effective": None, "source": None, "not_read": None, "locations": None,
            "hkcu": False, "adapters": [], "no_adapter": False}
    if wifi is None or wifi["status"] not in READ_STATUSES:
        reason = wifi["reason"] if wifi else "the wifi_adapter job did not run"
        return base | {"not_read": f"wifi_adapter was not read: {reason}"}
    name = entry["read"]["name"].casefold()
    adapters = {}
    for row in wifi["rows"]:
        adapters.setdefault(row.get("driver_key"), None)
        if (text(row.get("name")) or "").casefold() == name:
            adapters[row.get("driver_key")] = adapters[row.get("driver_key")] or row
    if not adapters:
        return base | {"effective": [], "source": "default", "no_adapter": True}
    values, listed, failures, present = [], [], [], False
    for driver_key in sorted(adapters, key=adapter_order):
        row = adapters[driver_key]
        status = row.get("status") if row is not None else None
        item = {"driver_key": text(driver_key), "status": status,
                "value": row.get("value") if status == "present" else None,
                "kind": text(row.get("kind")) if status == "present" else None,
                "error": text(row.get("error")) if row is not None else None}
        if status not in ("present", "absent"):
            item["status"] = "unreadable"
            item["error"] = item["error"] or "no readable row for this adapter"
            failures.append(item)
            col.skip(f"wifi_adapter {item['driver_key']} {entry['read']['name']}",
                     item["error"])
        elif status == "present":
            present = True
            values.append(item["value"])
        else:
            values.append(entry.get("default"))
        listed.append(item)
    if failures:
        return base | {"adapters": listed,
                       "not_read": f"{len(failures)} Wi-Fi adapter(s) could not be read"}
    return base | {"effective": values, "source": "preference" if present else "default",
                   "adapters": listed}


class TypedReader:
    """Evaluates the entries of the typed readers from their job results."""

    def __init__(self, results: dict, registry: dict, col: Collector):
        self.results = results
        self.registry = registry
        self.col = col

    def job_rows(self, job: str):
        """``(rows, None)`` or ``(None, reason)`` when the job was not read."""
        result = self.results.get(job)
        if result is None:
            return None, f"the {job} job did not run"
        if result["status"] == "needs_admin":
            return None, ("needs administrator rights (shadow_storage is only read in an "
                          "elevated run)")
        if result["status"] not in READ_STATUSES:
            return None, f"{job} was not read: {result['reason'] or 'no reason given'}"
        return result["rows"], None

    def missing(self, entry: dict, job: str, reason: str) -> dict:
        """An entry the job answered without the row it needs: not read, named apart."""
        self.col.skip(f"{job} {entry['id']}", reason)
        return not_read(reason)

    def by_key(self, rows: list, field: str, key: str):
        for row in rows:
            if (text(row.get(field)) or "").casefold() == key.casefold():
                return row
        return None

    def evaluate(self, entry: dict) -> dict:
        kind = entry["read"]["type"]
        if kind == "winhttp_proxy":
            return self.winhttp(entry)
        job = JOB_OF_TYPE.get(kind)
        if job is None:
            return not_read("reader not implemented")
        rows, reason = self.job_rows(job)
        if rows is None:
            return not_read(reason)
        return getattr(self, kind)(entry, job, rows)

    # One method per read type: (entry, job, rows) -> found.
    def service(self, entry, job, rows):
        name = entry["read"]["name"]
        row = self.by_key(rows, "name", name)
        if row is None:
            return self.missing(entry, job, f"no row for the service {name}")
        status = row.get("status")
        if status == "absent":
            return read_value("absent")
        if status != "present":
            return self.missing(entry, job, f"the service {name} could not be read: "
                                            f"{text(row.get('error')) or status!r}")
        start = enum_name(row.get("start_type"), SERVICE_START_TYPES)
        if start is None:
            return self.missing(entry, job, f"the service {name} has no start type")
        if start == "Automatic":
            if row.get("delayed_status") == "unreadable":
                return self.missing(entry, job, f"DelayedAutostart of {name} could not be "
                                                "read")
            if as_int(row.get("delayed_autostart")) == 1:
                start = "AutomaticDelayed"
        return read_value(start)

    def firewall_profile(self, entry, job, rows):
        profile = entry["read"]["profile"]
        row = self.by_key(rows, "profile", profile)
        if row is None:
            return self.missing(entry, job, f"no row for the firewall profile {profile}")
        value = firewall_state(row.get("enabled"))
        if value is None:
            return self.missing(entry, job, f"the firewall profile {profile} has no state")
        return read_value(value, local_enabled=firewall_state(row.get("local_enabled")),
                          policy_enabled=firewall_policy(row.get("policy_read"),
                                                         row.get("policy_enabled")))

    def security_center_av(self, entry, job, rows):
        products, unknown, active = [], 0, False
        for row in rows:
            state = as_int(row.get("product_state"))
            products.append({"display_name": text(row.get("display_name")),
                             "product_state": state})
            if state is None:
                unknown += 1
            elif state & ANTIVIRUS_ENABLED_BIT:
                active = True
        if unknown and not active:
            return self.missing(entry, job, f"{unknown} antivirus product(s) have no "
                                            "readable productState")
        return read_value(active, products=products)

    def defender_status(self, entry, job, rows):
        field = entry["read"]["field"]
        if not rows:
            return self.missing(entry, job, "Get-MpComputerStatus returned nothing")
        value = rows[0].get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return self.missing(entry, job, f"Get-MpComputerStatus has no {field}")
        return read_value(value)

    def device_guard(self, entry, job, rows):
        if not rows:
            return self.missing(entry, job, "Win32_DeviceGuard returned nothing")
        running = [as_int(v) for v in as_list(rows[0].get("SecurityServicesRunning"))]
        return read_value(entry["read"]["service"] in running,
                          services_running=[v for v in running if v is not None])

    def power_scheme(self, entry, job, rows):
        row = self.by_key(rows, "query", "active")
        if row is None:
            return self.missing(entry, job, "no row for powercfg /getactivescheme")
        if as_int(row.get("exit_code")) not in (None, 0):
            return self.missing(entry, job, f"powercfg /getactivescheme exited "
                                            f"{row.get('exit_code')}")
        scheme = parse_active_scheme(row.get("text"))
        if scheme is None:
            return self.missing(entry, job, "no scheme GUID in powercfg /getactivescheme")
        return read_value(scheme)

    def powercfg_setting(self, entry, job, rows):
        read = entry["read"]
        query = f"{read['subgroup']} {read['setting']}"
        row = self.by_key(rows, "query", query)
        if row is None:
            return self.missing(entry, job, f"no row for powercfg /query {query}")
        if as_int(row.get("exit_code")) not in (None, 0):
            return self.missing(entry, job, f"powercfg /query {query} exited "
                                            f"{row.get('exit_code')}")
        indexes = parse_query_indexes(row.get("text"))
        if indexes is None:
            return self.missing(entry, job, f"powercfg /query {query} has fewer than two "
                                            "index lines")
        return read_value(indexes[0] if read["power"] == "ac" else indexes[1])

    def dns(self, entry, job, rows):
        servers = []
        for row in rows:
            family = row.get("family")
            servers.append({
                "interface": text(row.get("interface")),
                "family": enum_name(family, ADDRESS_FAMILIES),
                "servers": [str(s) for s in as_list(row.get("servers")) if text(s)],
            })
        servers.sort(key=lambda s: ((s["interface"] or "").casefold(), str(s["family"])))
        return read_value(servers)

    def appx(self, entry, job, rows):
        name = entry["read"]["name"]
        row = self.by_key(rows, "name", name)
        if row is None:
            return self.missing(entry, job, f"no row for the package {name}")
        status = row.get("status")
        if status not in ("present", "absent"):
            return self.missing(entry, job, f"the package {name} has the status {status!r}")
        # Get-AppxPackage lists the packages of the account running it, like HKCU.
        return read_value(status, hkcu=True)

    def delivery_optimization(self, entry, job, rows):
        if not rows:
            return self.missing(entry, job, "Get-DOConfig returned nothing")
        value = rows[0].get("DownloadMode")
        if value is None or (isinstance(value, str) and not value.strip()):
            return self.missing(entry, job, "Get-DOConfig has no DownloadMode")
        if isinstance(value, str) and as_int(value) is not None:
            value = as_int(value)
        return read_value(enum_name(value, DOWNLOAD_MODES))

    def optional_feature(self, entry, job, rows):
        name = entry["read"]["name"]
        row = self.by_key(rows, "Name", name)
        if row is None:
            # Not on a list that was read: absent (a failed query never gets here).
            return read_value("absent")
        state = row.get("InstallState")
        number = as_int(state)
        if number == INSTALL_STATE_UNKNOWN:
            return not_read("install state unknown")
        if number is None and isinstance(state, str):
            return read_value("absent" if state.casefold() == "absent" else state)
        if number is None:
            return self.missing(entry, job, f"the feature {name} has no install state")
        return read_value(INSTALL_STATES.get(number, number))

    def shadow_storage(self, entry, job, rows):
        volumes = [{"volume": text(r.get("volume")), "max_space": r.get("max_space"),
                    "used_space": r.get("used_space"),
                    "allocated_space": r.get("allocated_space")} for r in rows]
        volumes.sort(key=lambda v: (v["volume"] or "").casefold())
        return read_value(volumes)

    def winhttp(self, entry):
        row = location_row(self.registry, WINHTTP_LOCATION)
        location = dict(WINHTTP_LOCATION, role="preference") | row
        if row["status"] == "unreadable":
            if self.registry["read"]:
                self.col.skip(f"registry {location_label(WINHTTP_LOCATION)}",
                              row["error"] or "not read")
            return not_read(f"{location_label(WINHTTP_LOCATION)} could not be read: "
                            f"{row['error'] or 'no reason given'}", locations=[location])
        if row["status"] == "absent":
            return read_value("direct", source="default", locations=[location])
        proxy = parse_winhttp(row["value"] if isinstance(row["value"], str) else None)
        if proxy is None or not isinstance(row["value"], str):
            return self.missing(entry, "registry_values",
                                "WinHttpSettings is too short or not binary") | {
                "locations": [location]}
        return read_value(proxy, locations=[location])


def own_state(entry: dict, found: dict) -> tuple:
    """``(state, reason)`` of an entry from its own reading, before ``applies_if``."""
    if found["not_read"] is not None:
        return "not_read", found["not_read"]
    if found.get("no_adapter"):
        return "not_applicable", "no physical Wi-Fi adapter"
    expected = entry["expected"]
    if expected is None:
        return "info", None
    effective = found["effective"]
    uses_null_default = entry.get("default") is None and (
        found["source"] == "default"
        or (isinstance(effective, list) and any(v is None for v in effective)))
    if uses_null_default and entry["read"]["type"] in catalogue.TYPES_WITH_DEFAULT:
        return "default_unknown", None
    values = effective if entry["read"]["type"] == "wifi_adapter_value" else [effective]
    if all(is_in(value, expected) for value in values):
        return "matches", None
    return "differs", None


def evaluate(entries: list, registry: dict, wifi, typed: TypedReader) -> dict:
    """``{entry id: found}`` with ``state`` and ``reason`` after ``applies_if``."""
    found = {}
    for entry in entries:
        kind = entry["read"]["type"]
        if kind == "registry":
            result = evaluate_registry(entry, registry, typed.col)
        elif kind == "wifi_adapter_value":
            result = evaluate_wifi(entry, wifi, typed.col)
        else:
            result = typed.evaluate(entry)
        result["state"], result["reason"] = own_state(entry, result)
        found[entry["id"]] = result

    by_id = {entry["id"]: entry for entry in entries}
    settled = set()

    def settle(entry_id):
        # applies_if has no cycles (catalogue.py), so the recursion ends.
        if entry_id in settled:
            return
        settled.add(entry_id)
        condition = by_id[entry_id].get("applies_if")
        if condition is None:
            return
        result = found[entry_id]
        target = condition["entry"]
        settle(target)
        other = found[target]
        if other["state"] == "not_read":
            # Whatever this entry read, whether it applies is unknown.
            result["state"], result["reason"] = "not_read", f"depends on {target}"
        elif result["state"] == "not_read":
            return
        elif other["state"] != "not_applicable" and other["effective"] is None:
            # A value missing with a null default is unknown, not "condition not met".
            result["state"] = "not_read"
            result["reason"] = f"depends on {target} (its value is unknown)"
        elif other["state"] == "not_applicable" \
                or not is_in(other["effective"], condition["in"]):
            result["state"] = "not_applicable"
            result["reason"] = f"applies only when {target} is one of {condition['in']}"

    for entry in entries:
        settle(entry["id"])
    for result in found.values():
        if result["state"] == "not_read":
            result["effective"] = None  # an old value is never shown as current
            result["source"] = None
    return found


def policy_on_home(source, edition):
    if source != "policy":
        return False
    if edition is None:
        return None
    return edition.startswith(HOME_EDITION_PREFIX)


# --- summary items -------------------------------------------------------------
def build_items(entries: list, found: dict, edition, elevated: bool) -> list:
    """Every entry as a detail item with an id: listed states first, then the rest."""
    order = {state: n for n, state in enumerate(STATES)}
    ranked = sorted(
        enumerate(entries),
        key=lambda pair: (order[found[pair[1]["id"]]["state"]],
                          LEVEL_ORDER.get(pair[1]["level"], 9), pair[0]))
    items = []
    for number, (_, entry) in enumerate(ranked, 1):
        result = found[entry["id"]]
        item = {
            "id": f"e{number}",
            "entry": entry["id"],
            "area": entry["area"],
            "level": entry["level"],
            "title": entry["title"],
            "state": result["state"],
            "effective": result["effective"],
            "expected": entry["expected"],
            "source": result["source"],
            "from_policy_on_home": policy_on_home(result["source"], edition),
            "reason": result["reason"],
            "has_block": entry.get("apply") is not None,
        }
        if elevated:
            item["hkcu_elevated"] = bool(result["hkcu"])
        item["rationale"] = entry["rationale"]
        item["manual"] = entry.get("manual")
        if entry.get("applies_if") is not None:
            item["applies_if"] = entry["applies_if"]
        # What --block needs, so that it works from the detail file alone.
        item["read"] = entry["read"]
        item["apply"] = entry.get("apply")
        if entry.get("rollback_manual") is not None:
            item["rollback_manual"] = entry["rollback_manual"]
        if entry["read"]["type"] == "registry":
            item["source_location"] = result.get("source_location")
        if result.get("locations") is not None:
            item["locations"] = result["locations"]
        if entry["read"]["type"] == "wifi_adapter_value":
            item["adapters"] = result.get("adapters") or []
        for extra in ("products", "services_running", "local_enabled", "policy_enabled"):
            if extra in result:
                item[extra] = result[extra]
        items.append(item)
    return items


SUMMARY_ITEM_FIELDS = ("id", "entry", "area", "level", "title", "state", "effective",
                       "expected", "source", "from_policy_on_home", "reason", "has_block",
                       "hkcu_elevated")


def count_states(items: list) -> dict:
    by_state = {state: 0 for state in STATES}
    by_area = {}
    for item in items:
        by_state[item["state"]] += 1
        area = by_area.setdefault(item["area"], {})
        area[item["state"]] = area.get(item["state"], 0) + 1
    return {"by_state": by_state,
            "by_area": {area: dict(sorted(states.items()))
                        for area, states in sorted(by_area.items())}}


# --- usage ---------------------------------------------------------------------
def usage_app(packaged: bool, subkey: str) -> str:
    """The package name, or the program path (``#`` of the subkey name is ``\\``)."""
    return subkey if packaged else subkey.replace("#", "\\")


def usage_key(capability: str, packaged: bool, subkey: str) -> str:
    return f"usage:{capability}:{'packaged' if packaged else 'nonpackaged'}:{subkey}"


def build_usage(result: dict, col: Collector) -> list:
    """Usage items (``u1``...): in use first, then the last stop newest first, none last."""
    items, unreadable = [], 0
    for row in result["rows"]:
        capability = text(row.get("capability"))
        subkey = text(row.get("subkey"))
        if capability is None or subkey is None:
            unreadable += 1
            continue
        packaged = row.get("packaged") is not False
        start = filetime_iso(row.get("last_used_start"))
        stop = filetime_iso(row.get("last_used_stop"))
        item = {
            "capability": capability,
            "app": usage_app(packaged, subkey),
            "packaged": packaged,
            "value": text(row.get("value")),
            "last_used_start": start,
            "last_used_stop": stop,
            "in_use": start is not None and stop is None,
            "key": usage_key(capability, packaged, subkey),
        }
        error = text(row.get("error"))
        if error is not None:
            item["error"] = error
            unreadable += 1
        items.append(item)
    if unreadable:
        col.skip(USAGE_SOURCE, f"{unreadable} consent subkey(s) could not be read; their "
                               "value is not compared")
    items.sort(key=lambda i: (not i["in_use"], i["last_used_stop"] is None,
                              _descending(i["last_used_stop"] or ""), i["capability"],
                              i["app"].casefold()))
    return psrun.with_ids(items, "u")


def _descending(value: str) -> tuple:
    return tuple(-ord(c) for c in value)


def usage_baseline(items: list, previous: dict) -> tuple:
    """``(items to compare, items to save)`` of the ``capability_usage`` source.

    A subkey that could not be read is never compared; the saved item keeps its previous
    value, like an unread setting, so a later change is still reported.
    """
    compare_items, save_items = {}, {}
    for item in items:
        saved = {"value": item["value"], "capability": item["capability"],
                 "app": item["app"], "packaged": item["packaged"]}
        if "error" in item:
            saved["unread_fields"] = ["value"]
            before = previous.get(item["key"])
            save_items[item["key"]] = dict(before) if isinstance(before, dict) else saved
        else:
            save_items[item["key"]] = saved
        compare_items[item["key"]] = saved
    return compare_items, save_items


# --- comparison ------------------------------------------------------------------
def baseline_items(entries: list, found: dict, previous: dict) -> tuple:
    """``(items to compare, items to save)`` of the ``settings`` source.

    An entry that was not read is never compared; the saved item keeps its previous
    ``effective`` (or null with ``unread_fields``), so the next read gives no false change.
    """
    compare_items, save_items = {}, {}
    for entry in entries:
        result = found[entry["id"]]
        if result["state"] == "not_read":
            compare_items[entry["id"]] = {"effective": None, "unread_fields": ["effective"]}
            before = previous.get(entry["id"])
            save_items[entry["id"]] = (dict(before) if isinstance(before, dict)
                                       else {"effective": None,
                                             "unread_fields": ["effective"]})
        else:
            compare_items[entry["id"]] = {"effective": result["effective"]}
            save_items[entry["id"]] = {"effective": result["effective"]}
    return compare_items, save_items


def settings_changes(previous: dict, current: dict, state: str, items: list) -> tuple:
    """``(changes, catalogue_changes)``; added or removed keys are catalogue changes."""
    if state != "compared":
        return [], {"added": 0, "removed": 0}
    diff = baseline.compare(previous, current, COMPARED_FIELDS)
    by_entry = {item["entry"]: item for item in items}
    changes = []
    for key, fields in diff["changed"].items():
        item = by_entry[key]
        changes.append({
            "key": key, "change": "changed", "entry": key, "area": item["area"],
            "title": item["title"], "state": item["state"],
            "before": fields["effective"]["before"], "after": fields["effective"]["after"],
        })
    return changes, {"added": len(diff["added"]), "removed": len(diff["removed"])}


def usage_changes(previous: dict, current: dict, state: str) -> list:
    """Added, removed and changed consent subkeys (``entry`` is null)."""
    if state != "compared":
        return []
    diff = baseline.compare(previous, current, USAGE_FIELDS)

    def change(key, kind, item):
        return {"key": key, "change": kind, "entry": None,
                "capability": item.get("capability"), "app": item.get("app"),
                "packaged": item.get("packaged")}

    changes = [change(key, "added", current[key]) for key in diff["added"]]
    changes += [change(key, "removed", previous[key]) for key in diff["removed"]]
    for key, fields in diff["changed"].items():
        changes.append(change(key, "changed", current[key])
                       | {"before": fields["value"]["before"],
                          "after": fields["value"]["after"]})
    return changes


# --- summary and detail ------------------------------------------------------
def fit_budget(summary: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    Only ``usage`` is cut, from its end, and ``truncated`` counts the cut items. A
    summary that is still too long says so in not_checked.
    """
    text_out = dump(summary)
    usage = summary.get("usage")
    if len(text_out) > SUMMARY_MAX_CHARS and usage:

        def fits(kept: int) -> bool:
            summary["usage"] = usage[:kept]
            summary["truncated"] = len(usage) - kept
            return len(dump(summary)) <= SUMMARY_MAX_CHARS

        if fits(0):
            low, high = 0, len(usage) - 1  # the most usage items that fit, by bisection
            while low < high:
                middle = (low + high + 1) // 2
                if fits(middle):
                    low = middle
                else:
                    high = middle - 1
            fits(low)
        else:
            # Something else is too long: cutting usage would lose it for nothing.
            summary["usage"] = usage
            summary["truncated"] = 0
        text_out = dump(summary)
    if len(text_out) > SUMMARY_MAX_CHARS:
        summary["not_checked"].append({
            "what": "summary budget",
            "reason": f"the summary exceeds {SUMMARY_MAX_CHARS} characters and was not cut",
        })
        text_out = dump(summary)
    return text_out


# --- paste-ready block -----------------------------------------------------------
HEADER_NORMAL = ("# Run in a normal (non-elevated) Windows PowerShell "
                 "(the account whose settings these are)")
HEADER_ELEVATED = "# Run in an elevated Windows PowerShell (Run as administrator)"
HEADER_ROLLBACK_NORMAL = ("# Rollback: normal (non-elevated) Windows PowerShell; restores "
                          "the values read before the change")
HEADER_ROLLBACK_ELEVATED = ("# Rollback: elevated Windows PowerShell; restores the values "
                            "read before the change")
PARTS = (("normal", HEADER_NORMAL), ("elevated", HEADER_ELEVATED),
         ("rollback_normal", HEADER_ROLLBACK_NORMAL),
         ("rollback_elevated", HEADER_ROLLBACK_ELEVATED))
RESTORABLE_KINDS = ("DWord", "QWord", "String", "ExpandString")
EMPTY_KEY_NOTE = "# if the key was created, it stays empty; this is harmless"
SET_SERVICE_TYPES = ("Automatic", "Manual", "Disabled")
FIREWALL_TOKENS = {True: "True", False: "False", "NotConfigured": "NotConfigured"}
# A service name written bare for sc.exe (which takes the name as one word).
BARE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")


class NoBlock(Exception):
    """This item gets no command; the message is the reason, printed as a comment."""


def one_line(value) -> str:
    """A value as one line of comment text."""
    if isinstance(value, str):
        return " ".join(value.split())
    return json.dumps(value, ensure_ascii=True)


def reg_path(hive: str, path: str) -> str:
    return psrun.ps_quote(f"{hive}:\\{path}")


PS_EXTRA_QUOTES = ("\u2018", "\u2019", "\u201a", "\u201b")


def reg_literal(value, kind: str) -> str:
    """A registry value as a PowerShell literal of ``kind``; NoBlock when it cannot be."""
    if kind in ("DWord", "QWord"):
        number = as_int(value)
        bits = 32 if kind == "DWord" else 64
        if number is None or not -(1 << (bits - 1)) <= number < (1 << bits):
            raise NoBlock(f"previous value cannot be restored ({kind} {one_line(value)})")
        if number >= 1 << (bits - 1):
            number -= 1 << bits  # the provider takes the signed form of the same bits
        return str(number)
    if kind in ("String", "ExpandString") and isinstance(value, str):
        if any(quote in value for quote in PS_EXTRA_QUOTES):
            # Windows PowerShell ends a single-quoted string at these too.
            raise NoBlock("previous value holds a typographic quote and cannot be "
                          "quoted safely; restore it by hand")
        return psrun.ps_quote(value)
    raise NoBlock(f"previous value cannot be restored (kind {kind})")


def write_value(key: str, name: str, literal: str, kind: str) -> list:
    return [
        f"if (-not (Test-Path -LiteralPath {key})) {{ New-Item -Path {key} -Force | Out-Null }}",
        (f"New-ItemProperty -LiteralPath {key} -Name {psrun.ps_quote(name)} -Value {literal} "
         f"-PropertyType {kind} -Force | Out-Null"),
    ]


def remove_value(key: str, name: str) -> str:
    return f"Remove-ItemProperty -LiteralPath {key} -Name {psrun.ps_quote(name)}"


def restore_value(key: str, name: str, previous: dict) -> list:
    """Rollback lines from the previous state of one value."""
    status = previous.get("status")
    if status == "absent":
        return [remove_value(key, name), EMPTY_KEY_NOTE]
    if status != "present":
        raise NoBlock("previous state of the target location could not be read")
    kind = previous.get("kind")
    if kind not in RESTORABLE_KINDS:
        raise NoBlock(f"previous value cannot be restored (kind {kind})")
    return write_value(key, name, reg_literal(previous.get("value"), kind), kind)


def apply_value(key: str, name: str, apply: dict, previous: dict) -> list:
    """Change lines for a registry value; NoBlock when there is nothing to change."""
    if apply.get("remove"):
        if previous.get("status") == "absent":
            raise NoBlock("the value is already absent")
        return [remove_value(key, name)]
    return write_value(key, name, reg_literal(apply["value"], apply["kind"]), apply["kind"])


def block_registry(item: dict) -> tuple:
    apply = item["apply"]
    locations = item.get("locations") or []
    index = apply.get("location")
    if not isinstance(index, int) or not 0 <= index < len(locations):
        raise NoBlock("the detail file does not name the target location")
    target = locations[index]
    if target.get("status") not in ("present", "absent"):
        raise NoBlock("previous state of the target location could not be read")
    key = reg_path(target["hive"], target["path"])
    change = apply_value(key, target["name"], apply, target)
    rollback = restore_value(key, target["name"], target)
    shell = "normal" if target["hive"] == "HKCU" else "elevated"
    return shell, change, rollback


def block_wifi(item: dict) -> tuple:
    apply = item["apply"]
    name = item["read"]["name"]
    adapters = item.get("adapters") or []
    if not adapters:
        raise NoBlock("no Wi-Fi adapter was read")
    change, rollback = [], []
    for adapter in adapters:
        if not text(adapter.get("driver_key")):
            raise NoBlock("an adapter has no driver key")
        if adapter.get("status") not in ("present", "absent"):
            raise NoBlock("previous state of an adapter could not be read")
        key = reg_path("HKLM", WIFI_CLASS_ROOT + adapter["driver_key"])
        change += apply_value(key, name, apply, adapter)
        rollback += restore_value(key, name, adapter)
    return "elevated", change, rollback


def service_command(name: str, start: str) -> str:
    if start == "AutomaticDelayed":
        # PS 5.1 has no such startup type; sc.exe takes it (the space after "start=" is
        # required). The name is bare only when it is one plain word.
        word = name if BARE_NAME_RE.fullmatch(name) else psrun.ps_quote(name)
        return f"sc.exe config {word} start= delayed-auto"
    if start not in SET_SERVICE_TYPES:
        raise NoBlock(f"start type {one_line(start)} cannot be set here")
    return f"Set-Service -Name {psrun.ps_quote(name)} -StartupType {start}"


def block_service(item: dict) -> tuple:
    name = item["read"]["name"]
    previous = item.get("effective")
    if previous == "absent":
        raise NoBlock("the service is absent; there is nothing to set")
    change = [service_command(name, item["apply"]["start_type"])]
    try:
        rollback = [service_command(name, previous)]
    except NoBlock as exc:
        raise NoBlock(f"previous value cannot be restored ({exc})") from None
    return "elevated", change, rollback


def block_firewall(item: dict) -> tuple:
    # The command writes the local (persistent) setting; its effect and the rollback are
    # sound only when that setting is what decides the effective (active) state: no
    # policy (RSOP) sets the profile, and the local value matches the effective one.
    # Local equal to effective alone does not prove it: a policy may hold the same value.
    profile = psrun.ps_quote(item["read"]["profile"])
    policy = item.get("policy_enabled")
    if policy is None:
        raise NoBlock("the firewall policy (RSOP) was not read")
    if not same(policy, "NotConfigured"):
        raise NoBlock(f"decided by a policy ({one_line(policy)}), not the local setting")
    previous = item.get("local_enabled")
    if previous is None:
        raise NoBlock("the local firewall setting was not read")
    local_effect = True if same(previous, "NotConfigured") else previous
    if not same(local_effect, item.get("effective")):
        raise NoBlock("decided by a policy, not the local setting")
    token = next((t for v, t in FIREWALL_TOKENS.items() if same(previous, v)), None)
    if token is None:
        raise NoBlock(f"previous value cannot be restored ({one_line(previous)})")
    new = FIREWALL_TOKENS[bool(item["apply"]["enabled"])]
    return ("elevated",
            [f"Set-NetFirewallProfile -Profile {profile} -Enabled {new}"],
            [f"Set-NetFirewallProfile -Profile {profile} -Enabled {token}"])


def block_powercfg(item: dict) -> tuple:
    read = item["read"]
    previous = item.get("effective")
    if as_int(previous) is None or isinstance(previous, bool):
        raise NoBlock(f"previous value cannot be restored ({one_line(previous)})")
    verb = f"/set{read['power']}valueindex"
    target = (f"SCHEME_CURRENT {psrun.ps_quote(read['subgroup'])} "
              f"{psrun.ps_quote(read['setting'])}")
    activate = "powercfg /setactive SCHEME_CURRENT"
    return ("elevated",
            [f"powercfg {verb} {target} {int(item['apply']['value'])}", activate],
            [f"powercfg {verb} {target} {int(previous)}", activate])


def block_feature(item: dict) -> tuple:
    name = psrun.ps_quote(item["read"]["name"])
    change = [f"Disable-WindowsOptionalFeature -Online -FeatureName {name} -NoRestart"]
    if item.get("effective") == "Enabled":
        rollback = [f"Enable-WindowsOptionalFeature -Online -FeatureName {name} -NoRestart"]
    else:
        rollback = ["# nothing to restore: the feature was not enabled"]
    return "elevated", change, rollback


def block_appx(item: dict) -> tuple:
    name = psrun.ps_quote(item["read"]["name"])
    manual = item.get("rollback_manual") or "reinstall the package the way it was installed"
    return ("normal",
            [f"Get-AppxPackage -Name {name} | Remove-AppxPackage"],
            [f"# no command restores it: {one_line(manual)}"])


BLOCK_BUILDERS = {
    "registry": block_registry,
    "wifi_adapter_value": block_wifi,
    "service": block_service,
    "firewall_profile": block_firewall,
    "powercfg_setting": block_powercfg,
    "optional_feature": block_feature,
    "appx": block_appx,
}


def policy_above(item: dict):
    """The reason text when a location above the block's target decides the value."""
    apply = item.get("apply")
    read = item.get("read")
    if not isinstance(apply, dict) or not isinstance(read, dict) \
            or read.get("type") != "registry":
        return None
    index, source = apply.get("location"), item.get("source_location")
    locations = item.get("locations") or []
    if not (isinstance(index, int) and isinstance(source, int)
            and 0 <= source < index < len(locations)):
        return None
    decided = locations[source]
    return (f"set by {decided.get('role')} at {location_label(decided)}; this block would "
            "not change the effective value")


ELEVATED_NOTE = ("read in an elevated run, where HKCU and per-user apps may belong to "
                 "another account; run settings.py again from a normal shell first")


def item_block(item: dict, elevated: bool = False) -> tuple:
    """``(shell, change lines, rollback lines)`` of one detail item, or NoBlock.

    A normal-shell block (HKCU, per-user apps) read in an elevated run is refused: its
    change and rollback would be built from the elevating account's values.
    """
    state = item.get("state")
    policy_note = policy_above(item)
    if policy_note is not None:
        raise NoBlock(policy_note)
    if state == "matches":
        raise NoBlock("already as expected")
    if state == "not_read":
        raise NoBlock(f"not read: {one_line(item.get('reason') or 'no reason given')}")
    if state == "not_applicable":
        raise NoBlock(f"does not apply: {one_line(item.get('reason') or '')}")
    if not item.get("has_block"):
        raise NoBlock(f"no scripted change; {one_line(item.get('manual') or 'no manual step')}")
    read = item.get("read")
    if not isinstance(item.get("apply"), dict) or not isinstance(read, dict):
        raise NoBlock("the detail file does not hold the change; run the collection again")
    builder = BLOCK_BUILDERS.get(read.get("type"))
    if builder is None:
        raise NoBlock(f"no block for read type {read.get('type')}")
    try:
        shell, change, rollback = builder(item)
    except (KeyError, TypeError, ValueError) as exc:
        raise NoBlock(f"the detail item is incomplete ({type(exc).__name__})") from None
    if shell == "normal" and (elevated or item.get("hkcu_elevated")):
        raise NoBlock(ELEVATED_NOTE)
    return shell, change, rollback


def apply_label(item: dict) -> str:
    apply = item["apply"]
    for field in ("value", "start_type", "enabled", "state"):
        if field in apply:
            return one_line(apply[field])
    return "removed" if apply.get("remove") else one_line(apply)


def render_block(items: list, elevated: bool = False) -> tuple:
    """``(text, number of commands)`` of the paste-ready block for ``items``."""
    notes = []
    parts = {name: [] for name, _ in PARTS}
    for item in items:
        label = f"{item.get('id')} {item.get('entry')}"
        try:
            shell, change, rollback = item_block(item, elevated)
        except NoBlock as exc:
            notes.append(f"# {label}: no block: {exc}")
            continue
        parts[shell].append(f"# {label}: {one_line(item.get('effective'))} -> "
                            f"{apply_label(item)}")
        parts[shell].extend(change)
        parts[f"rollback_{shell}"].append(f"# {label}: back to "
                                          f"{one_line(item.get('effective'))}")
        parts[f"rollback_{shell}"].extend(rollback)
    lines = list(notes)
    for name, header in PARTS:
        if parts[name]:
            if lines:
                lines.append("")
            lines.append(header)
            lines.extend(parts[name])
    count = sum(1 for name in ("normal", "elevated") for line in parts[name]
                if not line.startswith("#"))
    return "\n".join(lines), count


def newest_detail(work: Path):
    files = sorted(work.glob("settings-*.detail.json"), key=lambda p: p.name)
    return files[-1] if files else None


def read_detail(path: Path):
    """The detail object, or None with the reason printed on stderr."""
    try:
        detail = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"{path} could not be read: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if not isinstance(detail, dict):
        print(f"{path} does not hold a detail object", file=sys.stderr)
        return None
    return detail


def show_block(work: Path, ids_text: str, detail_file: Path | None = None) -> int:
    path = detail_file if detail_file is not None else newest_detail(work)
    if path is None:
        print(f"no detail file in {work}; run the collection first", file=sys.stderr)
        return 1
    detail = read_detail(path)
    if detail is None:
        return 1
    ids = []
    for part in ids_text.split(","):
        if part.strip() and part.strip() not in ids:
            ids.append(part.strip())
    if not ids:
        print("--block needs at least one id (e.g. e3,e7)", file=sys.stderr)
        return 1
    by_id = {item.get("id"): item for item in detail.get("settings") or []
             if isinstance(item, dict)}
    unknown = [item_id for item_id in ids if item_id not in by_id]
    if unknown:
        print(f"id(s) {', '.join(unknown)} not found among the settings of {path}",
              file=sys.stderr)
        return 1
    text_out, count = render_block([by_id[item_id] for item_id in ids],
                                   detail.get("elevated") is not False)
    print(text_out)
    if count == 0:
        print("no command to paste: every item has a reason above", file=sys.stderr)
        return 1
    return 0


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
    parser.add_argument("--block", metavar="IDS",
                        help="print a paste-ready block (and its rollback) for these "
                             "comma-separated setting ids (e.g. e3,e7) and exit; nothing "
                             "is changed")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail or --block: read this detail file (the "
                             "summary's detail_file) instead of the newest one")
    return parser


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    newest = detail_file if detail_file is not None else newest_detail(work)
    if newest is None:
        print(f"no detail file in {work}; run the collection first", file=sys.stderr)
        return 1
    detail = read_detail(newest)
    if detail is None:
        return 1
    for section in DETAIL_SECTIONS:
        for item in detail.get(section) or []:
            if isinstance(item, dict) and item.get("id") == item_id:
                print(json.dumps(item, ensure_ascii=True, indent=1))
                return 0
    print(f"id {item_id!r} not found in {newest}", file=sys.stderr)
    return 1


def main(argv=None, run_ps=None, is_admin=None, now=None) -> int:
    """Collect, compare and summarise, or print one detail item with --detail, or a
    paste-ready block with --block.

    ``run_ps`` and ``is_admin`` are the two inputs from the machine. Either both
    are injected (tests) or neither (a real run): injecting only one is a
    TypeError, so a test that forgets a fake fails loudly instead of reading
    the machine.
    """
    if (run_ps is None) != (is_admin is None):
        raise TypeError("inject both run_ps and is_admin, or neither")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.detail is not None and args.block is not None:
        parser.error("--detail and --block cannot be used together")
    if args.detail_file and args.detail is None and args.block is None:
        parser.error("--detail-file needs --detail or --block")
    if args.detail_file:
        # The detail file is named explicitly: no data directory is needed.
        detail_file = Path(args.detail_file).absolute()
        if args.block is not None:
            return show_block(Path(), args.block, detail_file)
        return show_detail(Path(), args.detail, detail_file)
    try:
        data_dir = datadir.resolve(args.data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    work = data_dir / "work"
    state = data_dir / "state"
    if args.detail is not None:
        return show_detail(work, args.detail)
    if args.block is not None:
        return show_block(work, args.block)

    try:
        entries = catalogue.load(CATALOGUE_PATH)
    except catalogue.CatalogueError as exc:
        print(f"nothing was read: {exc}", file=sys.stderr)
        return 2

    run_ps = run_ps or default_run_ps
    is_admin = is_admin or default_is_admin
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    work.mkdir(parents=True, exist_ok=True)
    summary_file = work / f"settings-{stamp}.summary.json"
    detail_file = work / f"settings-{stamp}.detail.json"

    admin = bool(is_admin())
    loaded = baseline.load(state, SKILL, admin)
    previous = loaded["sources"] if loaded["status"] == "read" else {}
    previous_items = previous.get(BASELINE_SOURCE) or {}
    previous_usage = previous.get(USAGE_SOURCE) or {}

    col = Collector(run_ps, work, stamp)
    registry = collect_registry(col, entries)
    edition = read_edition(col, registry)
    wifi = collect_wifi(col, entries)
    typed = TypedReader(collect_typed(col, entries, admin), registry, col)
    usage_result = collect_usage(col)
    found = evaluate(entries, registry, wifi, typed)
    items = build_items(entries, found, edition, admin)
    usage = (build_usage(usage_result, col)
             if usage_result["status"] in READ_STATUSES else [])
    if admin:
        hkcu_count = sum(1 for item in items if item.get("hkcu_elevated"))
        col.skip("HKCU in an elevated run",
                 f"{hkcu_count} settings were decided by HKCU or per-user apps, and the "
                 "camera, microphone and location usage comes from HKCU, in an elevated "
                 "session: HKCU and the app list are those of the account that elevated, "
                 "which may not be the user's; read them again from a normal shell")

    # The settings source is read once the catalogue loaded: a failed reader only marks
    # its own entries as unread and never hides the changes of the others.
    status = "read" if entries else "empty"
    compare_items, save_items = baseline_items(entries, found, previous_items)
    usage_items, usage_saved = usage_baseline(usage, previous_usage)
    usage_status = usage_result["status"]
    comparison = {
        BASELINE_SOURCE: baseline.comparison_state(previous, BASELINE_SOURCE, status),
        USAGE_SOURCE: baseline.comparison_state(previous, USAGE_SOURCE, usage_status),
    }
    changes, catalogue_changes = settings_changes(previous_items, compare_items,
                                                  comparison[BASELINE_SOURCE], items)
    changes += usage_changes(previous_usage, usage_items, comparison[USAGE_SOURCE])
    changes = psrun.with_ids(changes, "c")
    for item in usage:
        del item["key"]

    detail = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "elevated": admin,
        "edition_id": edition,
        "sources": col.sources,
        "comparison": comparison,
        "settings": items,
        "changes": changes,
        "catalogue_changes": catalogue_changes,
        "usage": usage,
    }
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    new_baseline = {
        "schema_version": baseline.SCHEMA_VERSION,
        "skill": SKILL,
        "created_at": now.isoformat(),
        "elevated": admin,
        "sources": baseline.merge_sources(
            previous, {BASELINE_SOURCE: save_items, USAGE_SOURCE: usage_saved},
            {BASELINE_SOURCE: status, USAGE_SOURCE: usage_status}),
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
        "edition_id": edition,
        "sources": col.sources,
        "not_checked": col.not_checked,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": 0,
        "baseline": baseline_info,
        "comparison": comparison,
        "counts": count_states(items),
        "settings": [{k: item[k] for k in SUMMARY_ITEM_FIELDS if k in item}
                     for item in items if item["state"] in LISTED_STATES],
        "changes": changes,
        "catalogue_changes": catalogue_changes,
        "usage": list(usage),
    }
    text_out = fit_budget(summary)
    summary_file.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

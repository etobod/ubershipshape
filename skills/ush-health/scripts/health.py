"""Read the health of this machine once: storage, battery, devices, boot security,
updates, antivirus and recovery (read-only).

Every source is one or more read-only PowerShell jobs run through an injectable
``run_ps`` (see ``skills/ush-common/scripts/psrun.py``); tests pass a fake. The
result of a job comes back through a BOM-less UTF-8 file in the work directory,
never through stdout. Sources that need administrator rights are chosen by
``is_admin()``, not by their error: some of them return empty fields without
an error when run without the rights.

The summary goes to stdout and to ``work/health-<UTC stamp>.summary.json``; the
detail file ``work/health-<UTC stamp>.detail.json`` holds the full lists with the
same ids. ``--detail <id>`` prints one item of the newest detail file.

Disks ``k``, volumes ``v`` and devices ``p`` keep their numbers across runs through
the id map ``state/ush-health.ids.json`` (``ids.py``). The keys are ``json.dumps`` of
``["disk", UniqueId]``, ``["volume", drive letter]`` and ``["device", instance id]``; a
disk without ``UniqueId`` and a device without an instance id (null, empty or only
blanks) get a number for this run only. Pending updates ``q`` (an offline search of the
local update cache, not compared with the baseline) keep theirs by the key
``update:<KB numbers or title>|<driver provider>``. Update failures ``u`` are numbered
by place.

The baseline (``baseline.py``) is ``state/ush-health.json`` or
``state/ush-health.elevated.json``, with a day copy in ``state/history/``. Its sources
are ``disks`` (key UniqueId), ``volumes`` (drive letter), ``devices`` (instance id, only
devices whose status is not ``OK``) and ``os`` (one item ``"os"``). A disk or device
without a key, or with a key another item of the same run has, is left out of the
baseline and named in ``not_checked``; a repeated key gives no change and keeps its
saved item, and an item without a key stops ``removed`` for its source in that run
and keeps the saved items not seen. A compared field whose current value is null is
not compared (``unread_fields``) and the saved item keeps its previous value; such
fields of items on both sides are named in ``<source> not compared: <fields>``. Changes are
``c`` items, numbered for this run only. ``--compare-to <N>d`` compares with the day
copy at least N days old instead of the latest run; the latest baseline stays the base
of what is saved.

The script counts; it never judges. The only classification is the one the
data gives: devices whose Plug and Play status is not ``OK`` are listed, and
Windows Update entries whose result is Failed or Aborted are grouped. A value
that could not be read is ``null``, never ``false`` or ``0``; a documented
sentinel (Defender's 65535 and 4294967295) is ``null`` too.

Only ``updates.failures`` is cut to keep the summary within
``SUMMARY_MAX_CHARS``, from the oldest group; ``truncated`` counts the cut
groups and the detail file keeps them all (section ``update_failures``).
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The shared PowerShell runner and data-directory resolution live in skills/ush-common/scripts.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline
import datadir
import ids
import psrun
from psrun import dump, ps_quote, ps_script, run_job, with_ids

SKILL = "ush-health"
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
GIB = 1024 ** 3  # Explorer shows sizes in units of 1024**3 bytes
DETAIL_SECTIONS = ("disks", "volumes", "devices", "update_failures", "pending_updates",
                   "changes")
NEEDS_ADMIN = "needs administrator"
VOLUMES_NOT_READ = "volumes not read"
# The stderr of Get-PnpDevice when no device matches the filter.
NO_PNP_DEVICE = "No matching Win32_PnPEntity objects"
UNRECOGNISED_REAGENTC = "unrecognised reagentc output"

# OperationResultCode of the Windows Update Agent; any other code is keyed by
# its decimal value as text.
RESULT_NAMES = {0: "NotStarted", 1: "InProgress", 2: "Succeeded",
                3: "SucceededWithErrors", 4: "Failed", 5: "Aborted"}
FAILED_RESULTS = (4, 5)
SUCCEEDED = 2  # only a clean success supersedes a failed cumulative update
# Get-MpComputerStatus sentinels for "unknown/never" (e.g. Defender not running).
SIGNATURE_AGE_UNKNOWN = 65535
QUICK_SCAN_AGE_UNKNOWN = 4294967295
# DMTF time of Get-ComputerRestorePoint: yyyymmddHHMMSS.ffffff+zzz (offset in minutes).
DMTF_TIME = re.compile(r"^(\d{14})\.(\d{6})([+-])(\d{3})$")
# The English status line of reagentc /info; localised output is not recognised.
WINRE_STATUS = re.compile(r"^[ \t]*Windows RE status:[ \t]*(\S[^\r\n]*?)[ \t\r]*$",
                          re.MULTILINE)

# Shared helpers prepended to every job body. S keeps $null as null (a plain
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

PHYSICAL_DISKS_BODY = r"""$rows = @(Get-PhysicalDisk | ForEach-Object {
  [pscustomobject]@{
    DeviceId = S $_.DeviceId
    FriendlyName = S $_.FriendlyName
    MediaType = S $_.MediaType
    BusType = S $_.BusType
    Size = $_.Size
    HealthStatus = S $_.HealthStatus
    OperationalStatus = S $_.OperationalStatus
    UniqueId = S $_.UniqueId
  }
})
$result = $rows
"""

# Needs administrator rights (without them: "Access to a CIM resource was not
# available"). The counter is read per disk, so the DeviceId is the disk's; a
# disk whose counter cannot be read gets Error and keeps the other disks' rows.
DISK_RELIABILITY_BODY = r"""$rows = @(Get-PhysicalDisk | ForEach-Object {
  $c = $null
  $err = $null
  try { $c = $_ | Get-StorageReliabilityCounter -ErrorAction Stop }
  catch { $err = S $_.Exception.Message }
  [pscustomobject]@{
    DeviceId = S $_.DeviceId
    Error = $err
    Temperature = $c.Temperature
    Wear = $c.Wear
    ReadErrorsTotal = $c.ReadErrorsTotal
    WriteErrorsTotal = $c.WriteErrorsTotal
    PowerOnHours = $c.PowerOnHours
  }
})
$result = $rows
"""

VOLUMES_BODY = r"""$rows = @(Get-Volume | ForEach-Object {
  $letter = [string]$_.DriveLetter
  if ($letter -notmatch '^[A-Za-z]$') { $letter = $null }
  [pscustomobject]@{
    DriveLetter = $letter
    FileSystem = S $_.FileSystem
    Size = $_.Size
    SizeRemaining = $_.SizeRemaining
    HealthStatus = S $_.HealthStatus
  }
})
$result = $rows
"""

BATTERY_BODY = r"""$rows = @(Get-CimInstance -ClassName Win32_Battery | ForEach-Object {
  [pscustomobject]@{ Name = S $_.Name }
})
$result = $rows
"""

# powercfg writes the report to a file; it is parsed here and deleted at once.
BATTERY_REPORT_BODY = r"""$xml = {xml_path}
try {
  $out = & powercfg.exe /batteryreport /xml /output $xml
  if ($LASTEXITCODE -ne 0) {
    throw ('powercfg exit code ' + $LASTEXITCODE + ': ' + (($out | Out-String).Trim()))
  }
  $doc = New-Object System.Xml.XmlDocument
  $doc.Load($xml)
  $rows = @(foreach ($b in @($doc.BatteryReport.Batteries.Battery)) {
    if ($null -ne $b) {
      [pscustomobject]@{
        DesignCapacity = N $b.DesignCapacity
        FullChargeCapacity = N $b.FullChargeCapacity
        CycleCount = N $b.CycleCount
      }
    }
  })
  $result = $rows
} finally {
  Remove-Item -LiteralPath $xml -Force -ErrorAction SilentlyContinue
}
"""

DEVICES_BODY = r"""$rows = @(Get-PnpDevice -PresentOnly | ForEach-Object {
  $name = $_.FriendlyName
  if (-not $name) { $name = $_.Name }
  [pscustomobject]@{
    Name = S $name
    Class = S $_.Class
    Status = S $_.Status
    Problem = S $_.Problem
    InstanceId = S $_.InstanceId
  }
})
$result = $rows
"""

# A missing key or value is null (unknown), never 0.
SECURE_BOOT_BODY = r"""$value = $null
$key = 'HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State'
if (Test-Path -LiteralPath $key) {
  $value = (Get-ItemProperty -LiteralPath $key).UEFISecureBootEnabled
}
$result = [pscustomobject]@{
  UEFISecureBootEnabled = $value
  FirmwareType = S $env:firmware_type
}
"""

# Without a matching device Get-PnpDevice fails with NO_PNP_DEVICE: that is empty.
TPM_DEVICES_BODY = r"""$rows = @(Get-PnpDevice -Class SecurityDevices -PresentOnly | ForEach-Object {
  $name = $_.FriendlyName
  if (-not $name) { $name = $_.Name }
  [pscustomobject]@{ Name = S $name; Status = S $_.Status }
})
$result = $rows
"""

# Needs administrator rights. Get-Tpm is never used: without the rights it
# returns null fields without an error. The *_InitialValue properties are read,
# not the IsEnabled()/IsActivated() methods.
TPM_WMI_BODY = r"""$rows = @(Get-CimInstance -Namespace 'root\CIMV2\Security\MicrosoftTpm' -ClassName Win32_Tpm | ForEach-Object {
  [pscustomobject]@{
    SpecVersion = S $_.SpecVersion
    IsEnabled_InitialValue = $_.IsEnabled_InitialValue
    IsActivated_InitialValue = $_.IsActivated_InitialValue
  }
})
$result = $rows
"""

# {letters} is a list of quoted single letters checked in Python.
ENCRYPTION_BODY = r"""$shell = New-Object -ComObject Shell.Application
$rows = @(foreach ($letter in @({letters})) {
  $value = $null
  $folder = $shell.NameSpace($letter + ':\')
  if ($null -ne $folder) {
    $value = $folder.Self.ExtendedProperty('System.Volume.BitLockerProtection')
  }
  [pscustomobject]@{ DriveLetter = $letter; BitLockerProtection = $value }
})
$result = $rows
"""


# The Windows Update Agent gives Date in UTC with Kind Unspecified: SpecifyKind
# marks it as UTC without shifting it by the local zone.
UPDATE_HISTORY_BODY = r"""$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$count = $searcher.GetTotalHistoryCount()
$rows = @()
if ($count -gt 0) {
  $rows = @(foreach ($e in @($searcher.QueryHistory(0, $count))) {
    $date = $null
    if ($null -ne $e.Date) { $date = [DateTime]::SpecifyKind($e.Date, 'Utc').ToString('o') }
    [pscustomobject]@{
      Title = S $e.Title
      ResultCode = N $e.ResultCode
      HResult = N $e.HResult
      Date = $date
    }
  })
}
$result = $rows
"""

# Read-only and offline: Online false makes the search read only the agent's local
# cache, so nothing is sent and no scan is started. Type is 1 for software and 2 for
# a driver (UpdateType); a driver update also has DriverProvider, DriverClass and
# DriverVerDate. The agent gives its dates in UTC with Kind Unspecified: SpecifyKind
# marks them as UTC without a shift. An empty COM date (zero, 1899-12-30) means never
# and goes out as null. A failed read of the last scan date goes out as
# last_search_error, so it is never mistaken for an unknown date.
PENDING_UPDATES_BODY = r"""function UtcText($d) {
  if ($d -isnot [DateTime]) { return $null }
  if ($d.Year -lt 1900) { return $null }
  return [DateTime]::SpecifyKind($d, 'Utc').ToString('yyyy-MM-ddTHH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
}
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$searcher.Online = $false
$found = $searcher.Search('IsInstalled=0 and IsHidden=0')
$rows = @(for ($i = 0; $i -lt $found.Updates.Count; $i++) {
  $u = $found.Updates.Item($i)
  $type = S $u.Type
  if ($u.Type -eq 1) { $type = 'software' } elseif ($u.Type -eq 2) { $type = 'driver' }
  $provider = $null
  $class = $null
  $date = $null
  if ($type -eq 'driver') {
    $provider = S $u.DriverProvider
    $class = S $u.DriverClass
    $date = UtcText $u.DriverVerDate
  }
  $kbs = $u.KBArticleIDs
  $cats = $u.Categories
  [pscustomobject]@{
    title = S $u.Title
    kb = [string[]]@(for ($k = 0; $k -lt $kbs.Count; $k++) { 'KB' + [string]$kbs.Item($k) })
    categories = [string[]]@(for ($c = 0; $c -lt $cats.Count; $c++) { [string]$cats.Item($c).Name })
    type = $type
    driver_provider = $provider
    driver_class = $class
    driver_date = $date
    downloaded = $u.IsDownloaded
  }
})
$lastSearch = $null
$lastSearchError = $null
try {
  $auto = New-Object -ComObject Microsoft.Update.AutoUpdate
  $lastSearch = UtcText $auto.Results.LastSearchSuccessDate
} catch {
  $lastSearchError = S $_.Exception.Message
}
$result = [pscustomobject]@{
  updates = $rows
  last_search_success = $lastSearch
  last_search_error = $lastSearchError
}
"""
PENDING_UPDATES_DEPTH = 5  # result -> updates -> update -> kb/categories
NOT_A_SEARCH_RESULT = "the output is not one search result object with an updates list"

# OpenSubKey returns null for a missing key and throws when access is denied,
# so a denial is unreadable, never "not pending" (Test-Path would say false).
PENDING_REBOOT_BODY = r"""$hklm = [Microsoft.Win32.Registry]::LocalMachine
function Has($path) {
  $key = $hklm.OpenSubKey($path)
  if ($null -eq $key) { return $false }
  $key.Close()
  return $true
}
$sm = $hklm.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager')
if ($null -eq $sm) { throw 'the Session Manager key is missing' }
$rename = $null -ne $sm.GetValue('PendingFileRenameOperations')
$sm.Close()
$result = [pscustomobject]@{
  WindowsUpdateRebootRequired = Has 'SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
  ComponentBasedServicingRebootPending = Has 'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
  PendingFileRenameOperations = $rename
}
"""

# ProductName is not read: on Windows 11 it still says "Windows 10".
OS_VERSION_BODY = r"""$key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('SOFTWARE\Microsoft\Windows NT\CurrentVersion')
if ($null -eq $key) { throw 'the CurrentVersion key is missing' }
$result = [pscustomobject]@{
  DisplayVersion = S $key.GetValue('DisplayVersion')
  CurrentBuild = S $key.GetValue('CurrentBuild')
  UBR = N $key.GetValue('UBR')
  EditionID = S $key.GetValue('EditionID')
}
$key.Close()
"""

# productState goes out raw: the meaning of its bits is not documented.
ANTIVIRUS_PRODUCTS_BODY = r"""$rows = @(Get-CimInstance -Namespace 'root\SecurityCenter2' -ClassName AntiVirusProduct | ForEach-Object {
  [pscustomobject]@{ displayName = S $_.displayName; productState = N $_.productState }
})
$result = $rows
"""

DEFENDER_BODY = r"""$s = Get-MpComputerStatus
$updated = $null
if ($null -ne $s.AntivirusSignatureLastUpdated) {
  $updated = $s.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o')
}
$result = [pscustomobject]@{
  AMRunningMode = S $s.AMRunningMode
  RealTimeProtectionEnabled = $s.RealTimeProtectionEnabled
  AntivirusSignatureAge = N $s.AntivirusSignatureAge
  QuickScanAge = N $s.QuickScanAge
  AntivirusSignatureLastUpdated = $updated
}
"""

# Needs administrator rights ("Access denied" without them). CreationTime is
# DMTF text, parsed in Python.
RESTORE_POINTS_BODY = r"""$rows = @(Get-ComputerRestorePoint | ForEach-Object {
  [pscustomobject]@{
    CreationTime = S $_.CreationTime
    Description = S $_.Description
    SequenceNumber = N $_.SequenceNumber
  }
})
$result = $rows
"""

# Needs administrator rights (exit code 5 without them). The output is text in
# the language of the system; Python looks for the English status line only.
WINRE_BODY = r"""$out = & reagentc.exe /info
$text = (@($out) | ForEach-Object { [string]$_ }) -join "`n"
if ($LASTEXITCODE -ne 0) {
  throw ('reagentc exit code ' + $LASTEXITCODE + ': ' + $text.Trim())
}
$result = [pscustomobject]@{ Output = $text }
"""


# --- values ----------------------------------------------------------------
def number(value):
    """An int or float as is; anything else (None, bool, text) is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def text(value):
    return None if value is None else str(value)


def flag(value):
    """A real boolean, or an integer 0/non-zero; anything else is unknown (None)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return None


def gib(value):
    value = number(value)
    return None if value is None else round(value / GIB, 1)


def utc_text(value):
    """ISO 8601 text as UTC ``YYYY-MM-DDTHH:MM:SSZ``; a time without a zone is UTC.

    Anything that is not such a time is None.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dmtf_utc(value):
    """A DMTF time (``yyyymmddHHMMSS.ffffff+zzz``, offset in minutes) as UTC text."""
    match = DMTF_TIME.match(value.strip()) if isinstance(value, str) else None
    if match is None:
        return None
    stamp, _, sign, minutes = match.groups()
    offset = timedelta(minutes=int(minutes)) * (1 if sign == "+" else -1)
    try:
        local = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone(offset))
    except ValueError:  # an impossible date, or an offset of a day or more
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hresult(value):
    """A WUA HResult (a signed 32-bit number) as ``0x`` and 8 hex digits, or None."""
    value = number(value)
    if not isinstance(value, int):
        return None
    return f"0x{value & 0xFFFFFFFF:08X}"


def result_name(code) -> str:
    """The OperationResultCode name; another code is its decimal text."""
    code = number(code)
    if not isinstance(code, int):
        return "unknown"
    return RESULT_NAMES.get(code, str(code))


def not_sentinel(value, sentinel):
    """A number, or None for a missing value or the source's "unknown" sentinel."""
    value = number(value)
    return None if value == sentinel else value


def drive_letter(value):
    """A single ASCII letter, upper case, from "C", "C:" or "C:\\"; otherwise None."""
    if not isinstance(value, str):
        return None
    letter = value.strip().rstrip(":\\")
    if len(letter) == 1 and letter.isascii() and letter.isalpha():
        return letter.upper()
    return None


# --- collection ------------------------------------------------------------
class Collector:
    """Runs the jobs of one collection and keeps the sources and not_checked."""

    def __init__(self, run_ps, admin: bool, work: Path, stamp: str):
        self.run_ps = run_ps
        self.admin = admin
        self.work = work
        self.stamp = stamp
        self.sources = []
        self.not_checked = []

    def out_path(self, job: str) -> Path:
        return self.work / f"health-{self.stamp}.{job}.json"

    def job(self, job: str, body: str, empty_markers=(), depth: int = 4) -> dict:
        out_path = self.out_path(job)
        script = ps_script(PS_HELPERS + body, out_path, depth=depth)
        return run_job(self.run_ps, job, script, out_path, empty_markers=empty_markers)

    def record(self, name: str, status: str, reason=None) -> None:
        """One entry of sources; an unreadable source is also an item of not_checked."""
        self.sources.append({"name": name, "status": status, "reason": reason})
        if status == "unreadable":
            self.skip(name, reason)

    def skip(self, what: str, reason: str) -> None:
        self.not_checked.append({"what": what, "reason": reason})


def collect_disks(col: Collector) -> list | None:
    result = col.job("physical_disks", PHYSICAL_DISKS_BODY)
    col.record("physical_disks", result["status"], result["reason"])

    counters = {}
    if col.admin:
        rel = col.job("disk_reliability", DISK_RELIABILITY_BODY)
        col.record("disk_reliability", rel["status"], rel["reason"])
        counters = {text(row.get("DeviceId")): row for row in rel["rows"]}
    else:
        col.record("disk_reliability", "unreadable", NEEDS_ADMIN)

    if result["status"] == "unreadable":
        return None
    disks = []
    for row in result["rows"]:
        device_id = text(row.get("DeviceId"))
        counter = counters.get(device_id) if device_id is not None else None
        if counter is not None and counter.get("Error") is not None:
            col.skip(f"disk_reliability: {text(row.get('FriendlyName'))}",
                     text(counter.get("Error")))
            counter = None
        disks.append({
            "friendly_name": text(row.get("FriendlyName")),
            "media_type": text(row.get("MediaType")),
            "bus_type": text(row.get("BusType")),
            "size_gb": gib(row.get("Size")),
            "health_status": text(row.get("HealthStatus")),
            "operational_status": text(row.get("OperationalStatus")),
            "reliability": None if counter is None else {
                # 0 is what a drive that does not report temperature gives: unknown.
                "temperature_c": number(counter.get("Temperature")) or None,
                "wear_percent": number(counter.get("Wear")),
                "read_errors_total": number(counter.get("ReadErrorsTotal")),
                "write_errors_total": number(counter.get("WriteErrorsTotal")),
                "power_on_hours": number(counter.get("PowerOnHours")),
            },
            "device_id": device_id,  # detail only
            "unique_id": text(row.get("UniqueId")),  # detail only
        })
    return with_ids(disks, "k")


def collect_volumes(col: Collector) -> list | None:
    """Volumes with a drive letter; each gets ``protection`` from the encryption source."""
    result = col.job("volumes", VOLUMES_BODY)
    col.record("volumes", result["status"], result["reason"])
    if result["status"] == "unreadable":
        col.record("encryption", "unreadable", VOLUMES_NOT_READ)
        return None

    volumes = []
    for row in result["rows"]:
        letter = drive_letter(row.get("DriveLetter"))
        if letter is None:
            continue
        size, free = number(row.get("Size")), number(row.get("SizeRemaining"))
        volumes.append({
            "drive_letter": letter,
            "file_system": text(row.get("FileSystem")),
            "size_gb": gib(size),
            "free_gb": gib(free),
            "free_percent": (round(free / size * 100, 1)
                             if size is not None and free is not None and size > 0 else None),
            "health_status": text(row.get("HealthStatus")),
            "protection": None,
        })

    if not volumes:
        col.record("encryption", "empty")
        return with_ids(volumes, "v")
    letters = ", ".join(ps_quote(v["drive_letter"]) for v in volumes)
    enc = col.job("encryption", ENCRYPTION_BODY.replace("{letters}", letters))
    col.record("encryption", enc["status"], enc["reason"])
    protection = {drive_letter(row.get("DriveLetter")): row.get("BitLockerProtection")
                  for row in enc["rows"]}
    for vol in volumes:
        value = protection.get(vol["drive_letter"])
        # An empty value ("" or null) is unknown, never 0.
        vol["protection"] = value if number(value) is not None else None
    return with_ids(volumes, "v")


def empty_battery(present) -> dict:
    return {
        "present": present,
        "design_capacity_mwh": None,
        "full_charge_capacity_mwh": None,
        "full_charge_percent_of_design": None,
        "cycle_count": None,
    }


def collect_battery(col: Collector) -> dict | None:
    """No Win32_Battery instance is the sign of no battery; powercfg runs only with one."""
    result = col.job("battery", BATTERY_BODY)
    if result["status"] == "unreadable":
        col.record("battery", "unreadable", result["reason"])
        return None
    if result["status"] == "empty":
        col.record("battery", "empty")
        return empty_battery(False)

    battery = empty_battery(True)
    xml_path = col.work / f"health-{col.stamp}.battery.xml"
    body = BATTERY_REPORT_BODY.replace("{xml_path}", ps_quote(xml_path))
    report = col.job("battery_report", body)
    try:  # the job deletes it; this covers a job that stopped before its finally
        xml_path.unlink(missing_ok=True)
    except OSError as exc:
        col.skip("battery_report", f"the report file {xml_path} could not be deleted: "
                                   f"{type(exc).__name__}: {exc}")
    if report["status"] == "unreadable":
        col.record("battery", "unreadable", f"battery report: {report['reason']}")
        return battery
    if report["status"] == "empty":
        col.record("battery", "unreadable", "the battery report lists no battery")
        return battery

    col.record("battery", "read")
    if len(report["rows"]) > 1:
        col.skip("battery", f"the battery report lists {len(report['rows'])} batteries; "
                            "only the first is summarised")
    row = report["rows"][0]
    design = number(row.get("DesignCapacity"))
    full = number(row.get("FullChargeCapacity"))
    cycles = number(row.get("CycleCount"))
    battery.update({
        "design_capacity_mwh": design,
        "full_charge_capacity_mwh": full,
        "full_charge_percent_of_design": (round(full / design * 100, 1)
                                          if design and full is not None else None),
        # 0 cycles also means "not supported": unknown, not a count.
        "cycle_count": cycles if cycles else None,
    })
    return battery


def collect_devices(col: Collector) -> tuple[list | None, dict | None]:
    """Devices whose status is not OK, and the number of devices in each status."""
    result = col.job("devices", DEVICES_BODY)
    col.record("devices", result["status"], result["reason"])
    if result["status"] == "unreadable":
        return None, None
    by_status = {}
    listed = []
    for row in result["rows"]:
        status = text(row.get("Status"))
        key = "unknown" if status is None else status
        by_status[key] = by_status.get(key, 0) + 1
        if status != "OK":
            listed.append({
                "name": text(row.get("Name")),
                "class": text(row.get("Class")),
                "status": status,
                "problem": text(row.get("Problem")),
                "instance_id": text(row.get("InstanceId")),  # detail only
            })
    return with_ids(listed, "p"), by_status


def collect_secure_boot(col: Collector) -> dict | None:
    result = col.job("secure_boot", SECURE_BOOT_BODY)
    if result["status"] == "unreadable":
        col.record("secure_boot", "unreadable", result["reason"])
        return None
    row = result["rows"][0] if result["rows"] else {}
    # The job always writes one object; missing values inside it are unknown.
    col.record("secure_boot", "read" if result["rows"] else "empty")
    return {
        "enabled": flag(row.get("UEFISecureBootEnabled")),
        "firmware_type": text(row.get("FirmwareType")),
    }


def collect_tpm(col: Collector) -> dict:
    """The TPM as a device (no rights needed) and Win32_Tpm (administrator only)."""
    tpm = {"devices": None, "spec_version": None, "is_enabled": None, "is_activated": None}
    result = col.job("tpm_devices", TPM_DEVICES_BODY, empty_markers=(NO_PNP_DEVICE,))
    if result["status"] != "unreadable":
        tpm["devices"] = [{"name": text(row.get("Name")), "status": text(row.get("Status"))}
                          for row in result["rows"]]

    wmi_read = False
    wmi_reason = None
    if not col.admin:
        col.skip("tpm_wmi", NEEDS_ADMIN)
    else:
        wmi = col.job("tpm_wmi", TPM_WMI_BODY)
        if wmi["status"] == "unreadable":
            wmi_reason = wmi["reason"]
            col.skip("tpm_wmi", wmi_reason)
        elif wmi["rows"]:
            wmi_read = True
            row = wmi["rows"][0]
            spec = row.get("SpecVersion")
            tpm.update({
                "spec_version": spec if isinstance(spec, str) and spec.strip() else None,
                "is_enabled": row.get("IsEnabled_InitialValue")
                if isinstance(row.get("IsEnabled_InitialValue"), bool) else None,
                "is_activated": row.get("IsActivated_InitialValue")
                if isinstance(row.get("IsActivated_InitialValue"), bool) else None,
            })

    status = result["status"]
    if status == "empty" and wmi_read:
        status = "read"
    if status == "empty" and wmi_reason is not None:
        # No device found and Win32_Tpm failed: not "empty", which would mean
        # "no TPM". Not through record(): tpm_wmi has its own not_checked entry.
        col.sources.append({"name": "tpm", "status": "unreadable",
                            "reason": f"tpm_wmi: {wmi_reason}"})
        return tpm
    col.record("tpm", status, result["reason"])
    return tpm


DEFAULT_CUMULATIVE_FILE = Path(__file__).absolute().parents[1] / "data" / "cumulative-updates.json"


LINE_KINDS = ("build", "version")


def load_cumulative(path=None) -> list[dict]:
    """Load the cumulative update patterns: a JSON list of
    {id, pattern, line_kind, example, reason}, each pattern with a group ``line``.

    A missing or malformed file raises ValueError naming the file: a broken
    list must not silently change which failures are reported.
    """
    path = DEFAULT_CUMULATIVE_FILE if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, list):
        # ValueError like every other malformed-file case, so callers catch one type.
        raise ValueError(f"{path}: expected a JSON list of cumulative update patterns")  # noqa: TRY004
    entries = []
    for number, item in enumerate(data, 1):
        item = item if isinstance(item, dict) else {}
        pattern = item.get("pattern")
        if (not isinstance(item.get("id"), str) or not item["id"]
                or not isinstance(pattern, str) or not pattern
                or item.get("line_kind") not in LINE_KINDS):
            raise ValueError(f"{path}: entry {number} needs a non-empty id and pattern "
                             f"and a line_kind of {' or '.join(LINE_KINDS)}")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{path}: entry {number} ({item['id']}): the pattern does "
                             f"not compile: {exc}") from exc
        if "line" not in compiled.groupindex:
            raise ValueError(f"{path}: entry {number} ({item['id']}): the pattern has "
                             "no group named line")
        entries.append({"id": item["id"], "regex": compiled,
                        "line_kind": item["line_kind"]})
    return entries


def cumulative_line(title, patterns):
    """(line_kind, line) of the first pattern the title matches, else None."""
    if not isinstance(title, str):
        return None
    for entry in patterns:
        match = entry["regex"].search(title)
        if match and match.group("line"):
            return entry["line_kind"], match.group("line")
    return None


def collect_updates(col: Collector, patterns=()) -> dict | None:
    """Windows Update history: entries by result and the failed ones grouped."""
    result = col.job("update_history", UPDATE_HISTORY_BODY)
    col.record("update_history", result["status"], result["reason"])
    if result["status"] == "unreadable":
        return None
    by_result = {}
    groups = {}
    # (line_kind, line) -> the latest successful cumulative update of that Windows line.
    latest_success = {}
    for row in result["rows"]:
        name = result_name(row.get("ResultCode"))
        by_result[name] = by_result.get(name, 0) + 1
        code = number(row.get("ResultCode"))
        if code == SUCCEEDED:
            line = cumulative_line(row.get("Title"), patterns)
            when = utc_text(row.get("Date"))
            if line is not None and when is not None and (
                    line not in latest_success or when > latest_success[line]["date"]):
                latest_success[line] = {"title": text(row.get("Title")), "date": when}
        if code not in FAILED_RESULTS:
            continue
        # The result is part of the key, so a group never mixes Failed and Aborted.
        key = (text(row.get("Title")), hresult(row.get("HResult")), name)
        group = groups.setdefault(key, {
            "title": key[0], "result": name, "hresult": key[1],
            "count": 0, "first": None, "last": None,
        })
        group["count"] += 1
        when = utc_text(row.get("Date"))
        if when is not None:
            # One format, one zone: the text sorts as the time does.
            group["first"] = when if group["first"] is None else min(group["first"], when)
            group["last"] = when if group["last"] is None else max(group["last"], when)
    for group in groups.values():
        # Superseded only by a later Succeeded entry of the same Windows line.
        line = cumulative_line(group["title"], patterns)
        success = latest_success.get(line) if line is not None else None
        group["superseded_by"] = (dict(success) if success is not None
                                  and group["last"] is not None
                                  and success["date"] > group["last"] else None)
    # Newest last first; a group without a known time goes to the end.
    failures = sorted(groups.values(), key=lambda g: g["last"] or "", reverse=True)
    return {
        "history_count": len(result["rows"]),
        "by_result": by_result,
        "failures": with_ids(failures, "u"),
        "superseded": sum(1 for g in failures if g["superseded_by"] is not None),
    }


def text_list(value):
    """A list of texts (a lone text is a list of one); anything else is None."""
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return None
    return [str(entry) for entry in value if entry is not None]


def collect_pending_updates(col: Collector) -> tuple[list | None, str | None]:
    """Updates found and not installed, from the local cache, and the last scan date.

    ``(items, last_scan)``; items is None when the search could not be read. Ids are
    given later by ``number_stable``. Not compared with the baseline: a current state.
    """
    result = col.job("pending_updates", PENDING_UPDATES_BODY, depth=PENDING_UPDATES_DEPTH)
    if result["status"] == "unreadable":
        col.record("pending_updates", "unreadable", result["reason"])
        return None, None
    rows = result["rows"]
    row = rows[0] if len(rows) == 1 else {}
    updates = row.get("updates")
    if not isinstance(updates, list) or not all(isinstance(u, dict) for u in updates):
        col.record("pending_updates", "unreadable", NOT_A_SEARCH_RESULT)
        return None, None
    items = []
    for update in updates:
        item = {
            "id": None,
            "title": text(update.get("title")),
            "kb": text_list(update.get("kb")),
            "categories": text_list(update.get("categories")),
            "type": text(update.get("type")),
            "driver_provider": text(update.get("driver_provider")),
            "driver_class": text(update.get("driver_class")),
            "driver_date": utc_text(update.get("driver_date")),
            "downloaded": flag(update.get("downloaded")),
        }
        name = item["title"] or "an update without a title"
        for field in ("kb", "categories"):
            if item[field] is None:
                col.skip(f"pending_updates: {field}", f"{name}: not a list of texts")
        if update.get("driver_date") is not None and item["driver_date"] is None:
            col.skip("pending_updates: driver_date", f"{name}: the driver date is not a time")
        items.append(item)
    col.record("pending_updates", "read" if items else "empty")

    raw_scan = row.get("last_search_success")
    last_scan = utc_text(raw_scan)
    error = text(row.get("last_search_error"))
    if error:
        col.skip("pending_updates: last scan", error)
    elif raw_scan is not None and last_scan is None:
        col.skip("pending_updates: last scan", "the last scan date is not a time")
    return items, last_scan


def pending_update_key(item: dict):
    """``update:<KB numbers or title>|<driver provider>``, or None without KB and title."""
    name = ",".join(item.get("kb") or []) or key_text(item.get("title"))
    if not key_text(name):
        return None
    return f"update:{name}|{item.get('driver_provider') or ''}"


def collect_pending_reboot(col: Collector) -> dict | None:
    """Each pending-reboot signal on its own; there is no combined flag."""
    result = col.job("pending_reboot", PENDING_REBOOT_BODY)
    col.record("pending_reboot", result["status"], result["reason"])
    if result["status"] == "unreadable":
        return None
    row = result["rows"][0] if result["rows"] else {}
    return {
        "windows_update": flag(row.get("WindowsUpdateRebootRequired")),
        "component_servicing": flag(row.get("ComponentBasedServicingRebootPending")),
        "file_rename_operations": flag(row.get("PendingFileRenameOperations")),
    }


def collect_os_version(col: Collector) -> dict | None:
    result = col.job("os_version", OS_VERSION_BODY)
    col.record("os_version", result["status"], result["reason"])
    if result["status"] == "unreadable":
        return None
    row = result["rows"][0] if result["rows"] else {}
    return {
        "display_version": text(row.get("DisplayVersion")),
        "build": text(row.get("CurrentBuild")),
        "ubr": number(row.get("UBR")),
        "edition_id": text(row.get("EditionID")),
    }


def collect_antivirus(col: Collector) -> dict | None:
    """SecurityCenter2 products and Defender's status: two parts of one source.

    The source is read when either part was read. A failed part is null with
    its own not_checked entry; both failed make the source unreadable.
    """
    products_job = col.job("antivirus_products", ANTIVIRUS_PRODUCTS_BODY)
    products = None
    if products_job["status"] == "unreadable":
        col.skip("antivirus_products", products_job["reason"])
    else:
        products = []
        for row in products_job["rows"]:
            state = number(row.get("productState"))
            products.append({
                "display_name": text(row.get("displayName")),
                "product_state": f"0x{state:X}" if isinstance(state, int) else None,
            })

    defender_job = col.job("defender", DEFENDER_BODY)
    defender = None
    if defender_job["status"] == "unreadable":
        col.skip("defender", defender_job["reason"])
    elif not defender_job["rows"]:
        col.skip("defender", "Get-MpComputerStatus returned no status")
    else:
        row = defender_job["rows"][0]
        defender = {
            "running_mode": text(row.get("AMRunningMode")),
            "real_time_protection_enabled": flag(row.get("RealTimeProtectionEnabled")),
            "signature_age_days": not_sentinel(row.get("AntivirusSignatureAge"),
                                               SIGNATURE_AGE_UNKNOWN),
            "quick_scan_age_days": not_sentinel(row.get("QuickScanAge"),
                                                QUICK_SCAN_AGE_UNKNOWN),
            "signature_updated": utc_text(row.get("AntivirusSignatureLastUpdated")),
        }

    statuses = (products_job["status"], defender_job["status"])
    if statuses == ("unreadable", "unreadable"):
        # Not through record(): each part already has its own not_checked entry.
        col.sources.append({
            "name": "antivirus", "status": "unreadable",
            "reason": f"products: {products_job['reason']}; "
                      f"defender: {defender_job['reason']}",
        })
        return None
    result = {"products": products, "defender": defender}
    if products_job["status"] == "read" or defender is not None:
        col.record("antivirus", "read")
    else:
        # No product listed and no Defender status: Defender failed, so this is not
        # "empty", which would mean read. Not through record(): Defender already has
        # its own not_checked entry.
        reason = defender_job["reason"] or "Get-MpComputerStatus returned no status"
        col.sources.append({"name": "antivirus", "status": "unreadable",
                            "reason": f"defender: {reason}"})
    return result


def collect_restore_points(col: Collector) -> dict | None:
    """Administrator only: the number of restore points, the newest and the oldest."""
    if not col.admin:
        col.record("restore_points", "unreadable", NEEDS_ADMIN)
        return None
    result = col.job("restore_points", RESTORE_POINTS_BODY)
    col.record("restore_points", result["status"], result["reason"])
    if result["status"] == "unreadable":
        return None
    times = [dmtf_utc(row.get("CreationTime")) for row in result["rows"]]
    known = sorted(t for t in times if t is not None)
    if len(known) < len(times):
        col.skip("restore_points: creation time",
                 f"{len(times) - len(known)} of {len(times)} creation times "
                 "are not DMTF times")
    return {
        "count": len(result["rows"]),
        "newest": known[-1] if known else None,
        "oldest": known[0] if known else None,
    }


def collect_winre(col: Collector) -> dict | None:
    """Administrator only: the WinRE status exactly as reagentc /info writes it."""
    if not col.admin:
        col.record("winre", "unreadable", NEEDS_ADMIN)
        return None
    result = col.job("winre", WINRE_BODY)
    if result["status"] == "unreadable":
        col.record("winre", "unreadable", result["reason"])
        return None
    output = result["rows"][0].get("Output") if result["rows"] else None
    match = WINRE_STATUS.search(output) if isinstance(output, str) else None
    if match is None:
        # An unknown format is no reading, never "disabled".
        col.record("winre", "unreadable", UNRECOGNISED_REAGENTC)
        return None
    col.record("winre", "read")
    return {"status": match.group(1)}


def collect(run_ps, admin: bool, work: Path, stamp: str,
            patterns=()) -> tuple[dict, Collector]:
    """Run every source; return the data fields of the summary and the collector.

    A new source is one more ``collect_*`` function called here.
    """
    col = Collector(run_ps, admin, work, stamp)
    data = {}
    data["disks"] = collect_disks(col)
    data["volumes"] = collect_volumes(col)
    data["battery"] = collect_battery(col)
    data["devices"], data["devices_by_status"] = collect_devices(col)
    data["secure_boot"] = collect_secure_boot(col)
    data["tpm"] = collect_tpm(col)
    data["updates"] = collect_updates(col, patterns)
    data["pending_updates"], data["last_scan"] = collect_pending_updates(col)
    data["pending_reboot"] = collect_pending_reboot(col)
    data["os_version"] = collect_os_version(col)
    data["antivirus"] = collect_antivirus(col)
    data["restore_points"] = collect_restore_points(col)
    data["winre"] = collect_winre(col)
    return data, col


# --- summary and detail ------------------------------------------------------
DETAIL_ONLY_KEYS = {"disks": ("device_id", "unique_id"), "devices": ("instance_id",)}


def key_text(value):
    """A key value as text, or None when it is missing: null, empty or only blanks.

    PowerShell's ``S`` helper turns an empty CIM value into ``""``; such a value names
    no item, so it is treated exactly like null.
    """
    if value is None or not str(value).strip():
        return None
    return str(value)


def stable_key(kind: str, value):
    """The id-map key ``json.dumps([kind, value])``, or None when ``value`` is missing
    (null, empty or only blanks: the item then gets a number for this run only)."""
    value = key_text(value)
    if value is None:
        return None
    return json.dumps([kind, value], ensure_ascii=True)


# list name -> (prefix, key of one item)
STABLE_LISTS = (
    ("disks", "k", lambda item: stable_key("disk", item.get("unique_id"))),
    ("volumes", "v", lambda item: stable_key("volume", item.get("drive_letter"))),
    ("devices", "p", lambda item: stable_key("device", item.get("instance_id"))),
    ("pending_updates", "q", pending_update_key),
)


def number_stable(data: dict, numbering) -> None:
    """Give disks, volumes, devices and pending updates their stable ids from
    ``numbering`` (an ``ids.Numbering``), in the order of their lists."""
    for name, prefix, key_of in STABLE_LISTS:
        if data.get(name) is not None:
            numbering.assign(prefix, data[name], key_of)


# --- baseline ----------------------------------------------------------------------
DISK_FIELDS = ("friendly_name", "size_gb", "health_status", "operational_status",
               "wear_percent", "read_errors_total", "write_errors_total")
RELIABILITY_FIELDS = ("wear_percent", "read_errors_total", "write_errors_total")
VOLUME_FIELDS = ("file_system", "size_gb", "free_gb", "health_status", "protection")
DEVICE_FIELDS = ("name", "class", "status", "problem")
OS_FIELDS = ("display_version", "build", "ubr", "edition_id")
OS_KEY = "os"

# Baseline source -> the collector source that gives its status, the fields of a saved
# item and the fields compared. The order is the order of the changes.
BASELINE_SOURCES = {
    "disks": {"status_from": "physical_disks", "fields": DISK_FIELDS,
              "compared": DISK_FIELDS[1:]},
    "volumes": {"status_from": "volumes", "fields": VOLUME_FIELDS,
                "compared": VOLUME_FIELDS},
    "devices": {"status_from": "devices", "fields": DEVICE_FIELDS,
                "compared": ("status", "problem")},
    "os": {"status_from": "os_version", "fields": OS_FIELDS, "compared": OS_FIELDS},
}

# Baseline source -> (list in the data, key field, what the key is called, item word,
# name field). ``os`` is one object, not a list.
KEYED_LISTS = {
    "disks": ("disks", "unique_id", "UniqueId", "disk", "friendly_name"),
    "volumes": ("volumes", "drive_letter", "drive letter", "volume", "drive_letter"),
    "devices": ("devices", "instance_id", "InstanceId", "device", "name"),
}


def source_status(col: Collector, name: str):
    """The status of collector source ``name`` (None when it was not recorded)."""
    for source in col.sources:
        if source.get("name") == name:
            return source.get("status")
    return None


def item_values(source: str, item: dict) -> dict:
    """The baseline fields of one item of the summary data."""
    if source == "disks":
        reliability = item.get("reliability") or {}
        values = {field: item.get(field) for field in DISK_FIELDS
                  if field not in RELIABILITY_FIELDS}
        values.update({field: reliability.get(field) for field in RELIABILITY_FIELDS})
        return {field: values[field] for field in DISK_FIELDS}
    return {field: item.get(field) for field in BASELINE_SOURCES[source]["fields"]}


def keyed_items(source: str, items: list) -> tuple[dict, list, dict]:
    """``({key: item}, notes, held)`` of one list: items with a key no other item of this
    run has. An item without a key, or with a repeated one, is left out and gets a
    ``(what, reason)`` note that names it by id and name, never by its key.

    ``held`` is ``{"repeated": set of keys, "blank": bool}``: a repeated key gives no
    change and the saved baseline keeps its previous item; an item without a key may be
    any saved item, so no saved item of this source is ``removed`` in this run and the
    saved items not matched in this run are kept.
    """
    _, key_field, key_label, word, name_field = KEYED_LISTS[source]
    keys = [key_text(item.get(key_field)) for item in items]
    counts = {}
    for key in keys:
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    kept, notes = {}, []
    held = {"repeated": {key for key, count in counts.items() if count > 1},
            "blank": None in keys}
    for item, key in zip(items, keys):
        label = f"{word} {item.get('id')} ({item.get(name_field)})"
        if key is None:
            notes.append((f"{word} not compared: no {key_label}",
                          (f"{label} has no {key_label}, so it is not kept in the "
                           "baseline and not compared with earlier runs; it may be any "
                           f"saved {word}, so removed {word}s were not checked in this "
                           f"run and saved {word}s not seen in this run stay in the "
                           "baseline")))
        elif counts[key] > 1:
            notes.append((f"{word} not compared: repeated {key_label}",
                          (f"{label} has the same {key_label} as another {word} of this "
                           "run, so it is not kept in the baseline and not compared with "
                           f"earlier runs; the saved {word} with that {key_label}, if "
                           "any, stays in the baseline")))
        else:
            kept[key] = item
    return kept, notes, held


def baseline_pair(values: dict, compared, before) -> tuple[dict, dict]:
    """``(item to compare, item to save)`` of one item.

    A compared field whose current value is None is unknown: it is in the compared
    item's ``unread_fields``, so it gives no change. The saved item keeps the previous
    value of such a field and marks it unread only when the previous item had it unread
    too, or had no such field, or there was no previous item; one failed read never
    wipes the value the next run compares with.
    """
    unread = [field for field in compared if values.get(field) is None]
    compare_item = dict(values)
    save_item = dict(values)
    if not unread:
        return compare_item, save_item
    compare_item["unread_fields"] = list(unread)
    before = before if isinstance(before, dict) else None
    before_unread = set((before or {}).get("unread_fields") or [])
    still_unread = []
    for field in unread:
        if before is not None and field in before and field not in before_unread:
            save_item[field] = before[field]
        else:
            still_unread.append(field)
    if still_unread:
        save_item["unread_fields"] = still_unread
    return compare_item, save_item


def baseline_sources(data: dict, previous: dict) -> tuple[dict, dict, dict, list, dict]:
    """``(compare, save, current, notes, held)`` of the baseline sources of one run.

    ``compare`` and ``save`` are ``{source: {key: item}}`` (see ``baseline_pair``);
    ``current`` is ``{source: {key: summary item}}`` for the ids and names of the
    changes; ``notes`` are the ``(what, reason)`` pairs of items left out; ``held`` is
    ``{source: held}`` of ``keyed_items``. A source that was not read has no entry.
    ``previous`` is the source map of the latest baseline. ``save`` also keeps the
    previous item of a repeated key, and with an item without a key every previous
    item not matched in this run.
    """
    compare, save, current, notes, held = {}, {}, {}, [], {}
    for source, spec in BASELINE_SOURCES.items():
        if source == "os":
            if data.get("os_version") is None:
                continue
            kept, source_held = {OS_KEY: data["os_version"]}, None
        else:
            items = data.get(KEYED_LISTS[source][0])
            if items is None:
                continue
            kept, left_out, source_held = keyed_items(source, items)
            notes += left_out
            held[source] = source_held
        before_items = previous.get(source) if isinstance(previous, dict) else None
        before_items = before_items if isinstance(before_items, dict) else {}
        compare[source], save[source], current[source] = {}, {}, kept
        for key, item in kept.items():
            compare[source][key], save[source][key] = baseline_pair(
                item_values(source, item), spec["compared"], before_items.get(key))
        if source_held is not None:
            for key, item in before_items.items():
                if key in kept:
                    continue
                if source_held["blank"] or key in source_held["repeated"]:
                    save[source][key] = item
    return compare, save, current, notes, held


def unread_compared(reference: dict, compare: dict, comparison: dict) -> list:
    """``(what, reason)`` per compared source with fields left out of the comparison:
    those in ``unread_fields`` of an item of this run (``compare``) or of the same item
    in ``reference``, counted only for keys on both sides (an item added or removed
    compares no field)."""
    notes = []
    for source in BASELINE_SOURCES:
        if comparison.get(source) != "compared":
            continue
        before = reference.get(source) or {}
        after = compare.get(source) or {}
        fields, count = set(), 0
        for key in set(before) & set(after):
            unread = set()
            for item in (before[key], after[key]):
                if isinstance(item, dict):
                    unread |= {f for f in item.get("unread_fields") or []
                               if isinstance(f, str)}
            if unread:
                fields |= unread
                count += 1
        if fields:
            items = "1 item has" if count == 1 else f"{count} items have"
            notes.append((f"{source} not compared: {', '.join(sorted(fields))}",
                          (f"{items} no value for some of these fields in this run or in the run "
                           "compared with (not read), so they were not compared")))
    return notes


def change_name(source: str, key: str, item) -> object:
    """The name of a change: the disk's or device's name, the drive letter or ``os``."""
    if source == "os":
        return OS_KEY
    if source == "volumes":
        return key
    item = item if isinstance(item, dict) else {}
    return item.get(KEYED_LISTS[source][4])


def health_changes(reference: dict, compare: dict, current: dict, comparison: dict,
                   held: dict | None = None) -> list:
    """The changes against ``reference`` (a source map), in the order of
    ``BASELINE_SOURCES`` and then by key; only sources whose state is ``compared``.

    ``held`` is ``{source: held}`` of ``keyed_items``: a repeated key gives no change, and
    a source with an item without a key gives no ``removed``.
    """
    held = held or {}
    changes = []
    for source, spec in BASELINE_SOURCES.items():
        if comparison.get(source) != "compared":
            continue
        before = reference.get(source) or {}
        after = compare.get(source) or {}
        diff = baseline.compare(before, after, spec["compared"])
        source_held = held.get(source) or {"repeated": set(), "blank": False}
        found = [(key, "added") for key in diff["added"]]
        if not source_held["blank"]:
            found += [(key, "removed") for key in diff["removed"]]
        found += [(key, "changed") for key in diff["changed"]]
        found = [pair for pair in found if pair[0] not in source_held["repeated"]]
        for key, kind in sorted(found, key=lambda pair: pair[0]):
            now_item = current.get(source, {}).get(key)
            shown = before.get(key) if kind == "removed" else now_item
            changes.append({
                "source": source,
                "kind": kind,
                "item": (None if kind == "removed" or source == "os"
                         else now_item.get("id")),
                "name": change_name(source, key, shown),
                "fields": diff["changed"].get(key, {}) if kind == "changed" else {},
            })
    return psrun.with_ids(changes, "c")


def public(items, section):
    """The summary form of a detail list: without the keys kept for the detail file."""
    if items is None:
        return None
    drop = DETAIL_ONLY_KEYS.get(section, ())
    return [{k: v for k, v in item.items() if k not in drop} for item in items]


def build_summary(now, admin, col, data, summary_file, detail_file,
                  baseline_info=None) -> dict:
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
        "baseline": baseline_info,
    }
    for key, value in data.items():
        summary[key] = public(value, key) if key in DETAIL_SECTIONS else value
    if summary.get("updates") is not None:
        # A copy: fit_budget may cut the summary's failures, never the detail's. The
        # summary keeps only the groups no later cumulative update superseded; their
        # ids stay those of the detail file.
        summary["updates"] = dict(summary["updates"])
        summary["updates"]["failures"] = [
            group for group in summary["updates"]["failures"]
            if group["superseded_by"] is None]
    return summary


def build_detail(summary: dict, data: dict) -> dict:
    """The detail file: the full lists, update failures and changes included."""
    detail = {key: summary[key] for key in (
        "schema_version", "skill", "generated_at", "elevated", "sources")}
    detail["comparison"] = data.get("comparison")
    for section in DETAIL_SECTIONS:
        if section == "update_failures":
            updates = data["updates"]
            detail[section] = None if updates is None else updates["failures"]
        else:
            detail[section] = data.get(section)
    return detail


def fit_budget(summary: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    Only ``updates.failures`` is cut, from its end (the oldest groups), and
    ``truncated`` counts the cut groups. A summary that is still too long
    says so in not_checked.
    """
    text_out = dump(summary)
    updates = summary.get("updates")
    if len(text_out) > SUMMARY_MAX_CHARS and updates and updates.get("failures"):
        failures = updates["failures"]

        def fits(kept: int) -> bool:
            updates["failures"] = failures[:kept]
            summary["truncated"] = len(failures) - kept
            return len(dump(summary)) <= SUMMARY_MAX_CHARS

        if fits(0):
            low, high = 0, len(failures) - 1  # the most groups that fit, by bisection
            while low < high:
                middle = (low + high + 1) // 2
                if fits(middle):
                    low = middle
                else:
                    high = middle - 1
            fits(low)
        else:
            # Something else is too long: cutting failures would lose them for nothing.
            updates["failures"] = failures
            summary["truncated"] = 0
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
    datadir.add_arguments(parser)
    parser.add_argument("--detail", metavar="ID",
                        help="print one item of the newest detail file and exit")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    parser.add_argument("--compare-to", metavar="<N>d", help=baseline.COMPARE_TO_HELP)
    return parser


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("health-*.detail.json"), key=lambda p: p.name)
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
    """Collect and summarise, or print one detail item with --detail.

    ``run_ps`` and ``is_admin`` are the two inputs from the machine. Either
    both are injected (tests) or neither (a real run): injecting only one is a
    TypeError, so a test that forgets a fake fails loudly instead of reading
    the machine.
    """
    if (run_ps is None) != (is_admin is None):
        raise TypeError("inject both run_ps and is_admin, or neither")
    parser = build_parser()
    args = parser.parse_args(argv)
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
    summary_file = work / f"health-{stamp}.summary.json"
    detail_file = work / f"health-{stamp}.detail.json"

    try:
        patterns = load_cumulative()
    except ValueError as exc:
        print(f"the cumulative update patterns could not be read: {exc}", file=sys.stderr)
        return 1
    admin = bool(is_admin())
    data, col = collect(run_ps, admin, work, stamp, patterns)
    id_map, map_reason = ids.load_map(state, SKILL)
    if map_reason is not None:
        col.skip(*ids.load_note(map_reason))
    numbering = ids.Numbering(id_map, now.date().isoformat())
    number_stable(data, numbering)

    loaded = baseline.load(state, SKILL, admin)
    previous = loaded["sources"] if loaded["status"] == "read" else {}
    # The state compared with: the latest baseline, or a history copy with --compare-to.
    # Only the changes and comparison_state use it; the items to save are built from the
    # latest baseline (``previous``).
    reference = baseline.reference_for(state, SKILL, admin, loaded, args.compare_to,
                                       compare_days, now)
    statuses = {source: source_status(col, spec["status_from"])
                for source, spec in BASELINE_SOURCES.items()}
    compare_items, save_items, current_items, left_out, held = baseline_sources(
        data, previous)
    for what, reason in left_out:
        col.skip(what, reason)
    comparison = {source: baseline.comparison_state(reference["sources"], source, status)
                  for source, status in statuses.items()}
    data["comparison"] = comparison
    data["changes"] = health_changes(reference["sources"], compare_items, current_items,
                                     comparison, held)
    for what, reason in unread_compared(reference["sources"], compare_items, comparison):
        col.skip(what, reason)

    new_baseline = {
        "schema_version": baseline.SCHEMA_VERSION,
        "skill": SKILL,
        "created_at": now.isoformat(),
        "elevated": admin,
        "sources": baseline.merge_sources(previous, save_items, statuses),
    }
    # The detail file first: when it cannot be written the run stops and the old
    # baseline stays, so the next run reports these changes again.
    detail = build_detail(build_summary(now, admin, col, data, summary_file, detail_file),
                          data)
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    state_name = baseline.baseline_name(SKILL, admin)
    save_reason = baseline.save(state, state_name, new_baseline)
    history_reason = baseline.archive(state, state_name, now)
    if history_reason is not None:
        col.skip("baseline history", baseline.history_note(history_reason))
    for what, reason in reference["notes"]:
        col.skip(what, reason)
    info = reference["info"]
    reasons = list(info["reason"])
    if save_reason is not None:
        reasons.append(f"not saved: {save_reason}")
        col.skip("baseline save", f"this run's baseline was not saved: {save_reason}")
    baseline_info = {
        "status": info["status"],
        "created_at": info["created_at"],
        "age_days": info["age_days"],
        "saved": save_reason is None,
        "reason": "; ".join(reasons) if reasons else None,
        "reference": info["reference"],
        "reference_file": info["reference_file"],
    }

    summary = build_summary(now, admin, col, data, summary_file, detail_file,
                            baseline_info)

    map_save_reason = ids.save_map(state, SKILL, id_map, now.date().isoformat())
    if map_save_reason is not None:
        col.skip(*ids.save_note(map_save_reason))
    for what, reason in numbering.repeated_notes():
        col.skip(what, reason)

    text_out = fit_budget(summary)
    summary_file.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

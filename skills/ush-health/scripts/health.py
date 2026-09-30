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

import datadir
import psrun
from psrun import dump, ps_quote, ps_script, run_job, with_ids

SKILL = "ush-health"
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
GIB = 1024 ** 3  # Explorer shows sizes in units of 1024**3 bytes
DETAIL_SECTIONS = ("disks", "volumes", "devices", "update_failures")
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

    def job(self, job: str, body: str, empty_markers=()) -> dict:
        out_path = self.out_path(job)
        script = ps_script(PS_HELPERS + body, out_path)
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


def collect_updates(col: Collector) -> dict | None:
    """Windows Update history: entries by result and the failed ones grouped."""
    result = col.job("update_history", UPDATE_HISTORY_BODY)
    col.record("update_history", result["status"], result["reason"])
    if result["status"] == "unreadable":
        return None
    by_result = {}
    groups = {}
    for row in result["rows"]:
        name = result_name(row.get("ResultCode"))
        by_result[name] = by_result.get(name, 0) + 1
        if number(row.get("ResultCode")) not in FAILED_RESULTS:
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
    # Newest last first; a group without a known time goes to the end.
    failures = sorted(groups.values(), key=lambda g: g["last"] or "", reverse=True)
    return {
        "history_count": len(result["rows"]),
        "by_result": by_result,
        "failures": with_ids(failures, "u"),
    }


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


def collect(run_ps, admin: bool, work: Path, stamp: str) -> tuple[dict, Collector]:
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
    data["updates"] = collect_updates(col)
    data["pending_reboot"] = collect_pending_reboot(col)
    data["os_version"] = collect_os_version(col)
    data["antivirus"] = collect_antivirus(col)
    data["restore_points"] = collect_restore_points(col)
    data["winre"] = collect_winre(col)
    return data, col


# --- summary and detail ------------------------------------------------------
DETAIL_ONLY_KEYS = {"disks": ("device_id",), "devices": ("instance_id",)}


def public(items, section):
    """The summary form of a detail list: without the keys kept for the detail file."""
    if items is None:
        return None
    drop = DETAIL_ONLY_KEYS.get(section, ())
    return [{k: v for k, v in item.items() if k not in drop} for item in items]


def build_summary(now, admin, col, data, summary_file, detail_file) -> dict:
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
    }
    for key, value in data.items():
        summary[key] = public(value, key) if key in DETAIL_SECTIONS else value
    if summary.get("updates") is not None:
        # A copy: fit_budget may cut the summary's failures, never the detail's.
        summary["updates"] = dict(summary["updates"])
    return summary


def build_detail(summary: dict, data: dict) -> dict:
    """The detail file: the full lists, update failures included."""
    detail = {key: summary[key] for key in (
        "schema_version", "skill", "generated_at", "elevated", "sources")}
    for section in DETAIL_SECTIONS:
        if section == "update_failures":
            updates = data["updates"]
            detail[section] = None if updates is None else updates["failures"]
        else:
            detail[section] = data[section]
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
    if args.detail is not None and args.detail_file:
        # The detail file is named explicitly: no data directory is needed.
        return show_detail(Path(), args.detail, Path(args.detail_file).absolute())
    try:
        work = datadir.resolve(args.data_dir) / "work"
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    if args.detail is not None:
        return show_detail(work, args.detail)

    run_ps = run_ps or default_run_ps
    is_admin = is_admin or default_is_admin
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    work.mkdir(parents=True, exist_ok=True)
    summary_file = work / f"health-{stamp}.summary.json"
    detail_file = work / f"health-{stamp}.detail.json"

    admin = bool(is_admin())
    data, col = collect(run_ps, admin, work, stamp)
    summary = build_summary(now, admin, col, data, summary_file, detail_file)
    detail = build_detail(summary, data)
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    text_out = fit_budget(summary)
    summary_file.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

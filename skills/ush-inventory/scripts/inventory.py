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
  ``InfName`` (for example a software device, or a device without a driver; not device
  state, which ``ush-health`` measures) is no entry, only counted in
  ``component_counts.drivers_without_inf`` and listed by device name and class
  in ``drivers_without_inf_items`` of the detail file. A ``removed`` driver is a
  device that is not present now (e.g. unplugged), not an uninstalled driver.
- ``driver_packages``: the driver store listing as XML (``/enum-drivers /format
  xml``), only the third-party packages (published name ``oem<N>.inf``), each
  with ``device_state`` from the ``devices`` source (see ``package_state``):
  ``present``, ``non_present`` (with the disconnected ``devices`` that name it),
  ``no_device_found`` (no device found without administrator rights, which is not
  "no device"), or null with ``device_state_reason``. A failed job, an exit code
  other than 0 or a text that is no XML listing makes the source unreadable. The
  summary lists the ``non_present`` and ``no_device_found`` packages (``o..``, cut
  to the budget); ``--block`` prints no removal for any of them.
- ``devices``: every device Windows knows, present or not, as XML (``pnputil
  /enum-devices /drivers /format xml``), with ``DEVPKEY_Device_LastRemovalDate``
  of each disconnected device whose driver is an ``oem<N>.inf``. Used only for the
  package states; no instance id leaves the job's raw file. A failed job, an exit
  code other than 0 or a text that is no listing makes the source unreadable.
- ``firewall_rules``: the rule values of the ``FirewallRules`` keys of the local
  store (``local``), of Store apps (``app_iso``) and of the policy (``policy``);
  a missing key is no rules, a key that cannot be read fails the source. The
  rule text is split by ``parse_firewall_rule``.
- ``firewall_apps``: one more job gets the ``App`` values of all rules (not
  ``System``) in a JSON file and answers, per value, its expanded path and
  whether a file is there (``app_exists`` of each rule; see ``apply_firewall_apps``).
- ``root_certificates``: the thumbprint subkeys of five physical root stores in
  the registry (``machine_root``, ``machine_policy``, ``enterprise``,
  ``user_root``, ``authroot``), with subject, issuer and dates from ``Cert:``.
- ``hosts``: the ``hosts`` file in ``Tcpip\\Parameters\\DataBasePath``, split by
  ``parse_hosts``; a missing file is read and holds no entries.
- ``administrators``: ``Get-LocalGroupMember -SID S-1-5-32-544`` (``Enabled``
  from ``Get-LocalUser`` for local and Microsoft accounts), else ADSI
  (``method: adsi``); ``builtin`` is true for the built-in Administrator account
  (a SID ``S-1-5-21-...-500``).
- ``defender_exclusions``: only with administrator rights; ``Get-MpPreference``
  (``method: preference``), else the ``Exclusions`` registry keys
  (``method: registry``); each entry has ``origin`` ``policy`` or ``local``. A
  value hidden by Defender (``N/A: ...``) makes the source unreadable.
- ``install_folders``: only when a removed program has a usable
  ``install_location``: per folder whether it is there and, for one that is,
  its file count, bytes, newest ``LastWriteTimeUtc`` and 10 most common
  extensions (no item source, no baseline; see ``find_leftovers``).
- ``leftover_keys``: only when a removed program has a publisher and a name:
  per key ``SOFTWARE\\<publisher>\\<name>`` under HKLM (also WOW6432Node) and HKCU
  whether it is there and its value and subkey counts (64-bit view, read-only).

``leftovers`` lists what removed programs left (``l..``, never cut): a program
is removed when it is in the previous baseline and not now (and its display name
is not installed now); it is kept in ``<data dir>/state/inventory-removed.json``
until a run that read everything finds no leftover (see ``find_leftovers``).

Every item has a stable key (``win32:<hive>:<subkey>``, ``msix:<family>``,
``run:<hive>\\<Run|RunOnce>:<name>``, ``startup:<user|common>:<file>``,
``task:<path><name>``, ``service:<name or template>``, ``feature:<Name>``,
``capability:<Name>``, ``driver:<DeviceID>``,
``driver_package:<original name>|<provider>|<version>`` (case-folded),
``firewall:<store>:<value name>``,
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
every autostart entry, every component, every driver, every driver package, every
addition, every leftover, every vendor folder and every change with the same ids.
``--detail <id>`` prints one item of the newest detail
file. To keep the summary within ``SUMMARY_MAX_CHARS`` eight lists are cut from
their end, first the package changes at the end of ``changes`` (``PACKAGE_SOURCES``,
``truncated_changes`` with ``change_counts``), then each of the six short lists down
to its minimum: ``programs``
(``truncated``; programs without an install date, then the oldest installs) down to
``PROGRAMS_MIN``, ``vendor_folders`` (``truncated_vendor_folders``) down to
``VENDOR_FOLDERS_MIN``, ``driver_packages`` (``truncated_driver_packages``; the
first packages of the list stay: non_present, then filter packages, then the rest) down to ``DRIVER_PACKAGES_MIN``,
``drivers`` (``truncated_drivers``; the ``DRIVER_CLASSES_FIRST`` classes lead the
list) down to ``DRIVERS_MIN``, ``components`` (``truncated_components``) down to
``COMPONENTS_MIN`` and ``additions`` (``truncated_additions``; the items without a
change block in SKILL.md first, then the ones with a block) down to
``ADDITIONS_MIN``: every short list keeps its minimum before any list goes below
it. Then ``autostart`` (``truncated_autostart``, with ``autostart_counts``) down
to ``AUTOSTART_MIN``; then ``components``, ``driver_packages`` and ``drivers``
below their minimum, each only after the one before is empty; then
``vendor_folders``, ``additions`` and ``programs`` the same way. A ``null`` list
stays ``null``. When ``autostart`` and ``changes`` are over the budget on
their own, the six lists keep their minimums and ``autostart`` and ``changes``
(``truncated_changes``, with ``change_counts``) are cut, down to ``AUTOSTART_MIN``
and ``CHANGES_MIN``, then to nothing, and then the six lists to nothing in the
same order. The
changes named by a rule of ``data/collapsed_names.json`` (the firewall rules named
by an unresolved ``ms-resource:`` string) are collapsed in the summary into one
counted entry per change type. A program whose name, without a suffix of
``data/per_user_suffixes.json``, equals the name of another program with the
same publisher gets ``per_user_pair``, and so does that other program. A listed
program and autostart entry in the summary lack some fields the report does not
use (``install_location``, ``display_name``, an autostart entry's ``targets``,
a fact's ``company``, ...); the detail file and the baseline keep the
full items, and the comparison uses them.
"""

import argparse
import copy
import fnmatch
import hashlib
import json
import ntpath
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

# The shared modules live in skills/ush-common/scripts.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline  # called as baseline.save(...), so tests can patch it
import datadir
import ids
import psrun
from psrun import dump, ps_script, run_job

SKILL = "ush-inventory"
FIRST_RUN_FILE = "ush-inventory.first-run.json"
FIRST_RUN_SCHEMA = 1
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
DETAIL_SECTIONS = ("programs", "autostart", "components", "drivers", "driver_packages",
                   "additions", "changes", "leftovers", "vendor_folders")
DEFAULT_OWN_FILE = Path(__file__).absolute().parents[1] / "data" / "windows-own.json"
# The roots whose direct child folders are listed, the folder names that ship with
# Windows and the exact publishers of a vendor folder name; read at run time.
VENDOR_FOLDERS_FILE = Path(__file__).absolute().parents[1] / "data" / "vendor-folders.json"
# The name suffixes of a per-user install (" (User)"); read at run time.
PER_USER_SUFFIXES_FILE = (Path(__file__).absolute().parents[1] / "data"
                          / "per_user_suffixes.json")
# The names whose changes the summary collapses into one counted entry per change
# type (the unresolved "ms-resource:" firewall rule names); read at run time.
COLLAPSED_NAMES_FILE = (Path(__file__).absolute().parents[1] / "data"
                        / "collapsed_names.json")
# The rules that put a driver package in a group by its class or provider; read at
# run time.
DRIVER_PACKAGE_GROUPS_FILE = (Path(__file__).absolute().parents[1] / "data"
                              / "driver-package-groups.json")

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
# The package managers: last in SOURCES.
PACKAGE_SOURCES = ("pip_packages", "npm_packages")
# The sources with items, compared with the baseline.
SOURCES = (PROGRAM_SOURCES + AUTOSTART_SOURCES + COMPONENT_SOURCES
           + ("drivers", "driver_packages") + ADDITION_SOURCES
           # Last, so the budget cuts their changes first.
           + PACKAGE_SOURCES)
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
    # The published name (oem<N>.inf) is not compared, as inf_name of drivers.
    "driver_packages": ("provider", "class", "version", "date", "signer"),
    "firewall_rules": ("action", "dir", "active", "protocol", "lport", "rport", "app",
                       "svc", "profile"),
    "root_certificates": ("subject", "issuer", "not_after"),
    # The key holds the host name and the address; the line number is not compared,
    # so a moved line is no change and any other change is added or removed.
    "hosts": (),
    "administrators": ("name", "enabled"),
    "defender_exclusions": ("origin",),
    "pip_packages": ("version",),
    "npm_packages": ("version",),
}
# The field that names an item in a change, when it is not "name".
NAME_FIELDS = {"drivers": "device_name", "driver_packages": "original_name",
               "root_certificates": "subject",
               "hosts": "hostname", "defender_exclusions": "value"}
# Components: the kind of each source (in list order) and the state that is listed.
COMPONENT_KINDS = {"optional_features": "feature", "capabilities": "capability"}
LISTED_STATES = {"feature": "enabled", "capability": "Installed"}
FEATURE_STATES = {1: "enabled", 2: "disabled", 3: "absent"}
# Driver packages: the published name of a third-party package in the driver store,
# the class whose packages no device names as its INF, and why their
# device_state is null.
THIRD_PARTY_PACKAGE = re.compile(r"oem\d+\.inf", re.IGNORECASE)
EXTENSION_CLASS = "extension"
EXTENSION_REASON = "extension packages are not listed per device"
DEVICES_UNREAD_REASON = ("the devices (source devices) were not read, so no package "
                         "state is known")
# The Status of a device in the device listing, case-folded: a present device (any
# of these four), or one Windows knows but that is not connected now. Any other or a
# missing status counts for neither (see package_state).
PRESENT_STATUSES = ("started", "stopped", "disabled", "problem")
NON_PRESENT_STATUSES = ("disconnected",)
UNKNOWN_STATUS_REASON = "device status not known"
# Windows reuses an oem<N>.inf number after a package is removed, so a disconnected
# device of another class than the package may name an earlier package of that number.
OTHER_CLASS_REASON = ("a disconnected device of another class names this published "
                      "name (Windows reuses oem<N>.inf numbers), so it is no evidence")
# Why --block prints no removal for any driver package (plan 051).
PACKAGE_NO_BLOCK_REASON = (
    "Windows refused every removal tried on this machine although no device names the "
    "package without administrator rights; a removal is not offered until a read "
    "proves Windows will accept it")
# DriverVersion of the driver store listing: "MM/DD/YYYY <version>".
PACKAGE_VERSION = re.compile(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+(\S+)\s*")
ADMIN_REASON = ("requires administrator rights (not read in this run, which is not "
                "elevated); this is not an empty list")
# The lists cut to fit the budget, with the key that counts the cut items. Every short
# list (programs, vendor_folders, driver_packages, drivers, components, additions) keeps
# its minimum before any list goes below it; then autostart goes to AUTOSTART_MIN; then
# components, driver_packages (the packages no device or only a disconnected one names)
# and drivers go to nothing, in that
# order, so the listed drivers outlast the packages; then vendor_folders (the folders no
# rule matches, each not judged one repeating the shared not_judged cause; every folder
# is a lead the detail file and the not_checked cause still cover), additions and
# programs. changes loses its package changes first, before any other list, and the
# rest only in the fallback (see fit_budget).
CUT_LISTS = (("programs", "truncated"),
             ("vendor_folders", "truncated_vendor_folders"),
             ("driver_packages", "truncated_driver_packages"),
             ("drivers", "truncated_drivers"),
             ("components", "truncated_components"), ("additions", "truncated_additions"),
             ("autostart", "truncated_autostart"), ("changes", "truncated_changes"))
# A cut autostart or changes list carries the per-type counts of the whole list here.
COUNT_KEYS = {"autostart": "autostart_counts", "changes": "change_counts"}
# The items each list keeps before any list is cut further: the newest programs and
# the first vendor folders, driver packages, drivers, components and additions.
PROGRAMS_MIN = 20
VENDOR_FOLDERS_MIN = 10
DRIVER_PACKAGES_MIN = 10
DRIVERS_MIN = 10
COMPONENTS_MIN = 10
ADDITIONS_MIN = 10
AUTOSTART_MIN = 20
CHANGES_MIN = 20
# Driver classes (case-insensitive) put first among the listed drivers, in this
# order, so the graphics driver stays in a short list.
DRIVER_CLASSES_FIRST = ("DISPLAY",)
# Firewall rules: the stores (registry keys under HKLM) and the fields of a rule.
FIREWALL_STORES = ("local", "app_iso", "policy")
FIREWALL_FIELDS = {
    "action": "Action", "dir": "Dir", "active": "Active", "lport": "LPort",
    "rport": "RPort", "app": "App", "svc": "Svc", "name": "Name", "profile": "Profile",
    "embed_ctxt": "EmbedCtxt",
}
PROTOCOL_NAMES = {6: "TCP", 17: "UDP"}
# The App value of a rule that names the kernel, not a file: no app_exists.
FIREWALL_SYSTEM_APP = "system"
# Why a rule's app_exists is null (apply_firewall_apps), and how many rules one
# not_checked item names before it only counts the rest.
APP_UNREAD_REASONS = {
    "list": "the rule repeats its App value, so no file was checked",
    "no_row": "the firewall_apps job gave no answer for the App value",
    "variable": "the App value names a variable this account does not know "
                "(a % is left after expansion)",
    "unknown": "the check could not tell whether the file is there (access denied, "
               "or not a full path on a local drive)",
}
APP_UNREAD_NAMED = 20

# Leftovers of removed programs: the state file of the removed programs whose
# leftovers are still there, and the reason of a part whose target file is missing.
REMOVED_STATE = "inventory-removed"
REMOVED_STATE_VERSION = 1
REMOVED_FIELDS = ("key", "source", "name", "publisher", "install_location", "first_seen_gone")
MISSING_REASON = "target file does not exist"
# Causes for which a removed program's registry keys do not count as fully read.
KEYS_NOT_READ = "its registry keys were not read"
HKCU_ELEVATED = ("its HKCU keys were read from the elevated account, which may not be "
                 "the account that used the program; a non-elevated run reads them")
# The roots under which leftover_keys looks for SOFTWARE\<publisher>\<display name>.
LEFTOVER_KEY_ROOTS = ("HKLM\\SOFTWARE", "HKLM\\SOFTWARE\\WOW6432Node", "HKCU\\SOFTWARE")
# A full local or network path: a drive letter and a backslash, or a UNC share.
FULL_PATH = re.compile(r"^(?:[a-z]:\\|\\\\[^\\]+\\[^\\]+)", re.IGNORECASE)
# Raw targets under the Windows folder written with a variable.
SYSTEM_VARS = ("%systemroot%", "%windir%", "\\systemroot\\")
# Folders many programs share: a removed program whose install_location is one of
# them is not matched (no folder part, no item under it). Anything under the Windows
# folder is matched by WINDOWS_FOLDER and by %SystemRoot% of file_facts.
BROAD_FOLDER = re.compile(
    r"^[a-z]:\\(?:programdata"
    r"|program files(?: \(x86\))?(?:\\common files|\\windowsapps)?"
    r"|users(?:\\[^\\]+(?:\\(?:downloads|desktop|documents)"
    r"|\\appdata(?:\\(?:local(?:\\(?:programs|temp|microsoft))?|locallow"
    r"|roaming(?:\\microsoft)?))?)?)?)$",
    re.IGNORECASE)
WINDOWS_FOLDER = re.compile(r"^[a-z]:\\windows(?:\\|$)", re.IGNORECASE)
# Program sources whose read is needed to tell that nothing of a removed program is left.
LEFTOVER_SOURCES = AUTOSTART_SOURCES + ("file_facts", "firewall_rules")
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
FACT_FIELDS = ("expanded_path", "exists", "signature_status", "signer", "company", "sha256",
               "sha256_error")
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
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

# Shared by file_facts and firewall_apps. Test-LocalPath: a full path on a local
# drive (fixed, removable or RAM; never UNC or a network drive). Confirm-Missing:
# false only when listing the parent folder confirms the file is not there, or the
# parent folder itself is not there; a denied folder or a drive that is not ready
# gives null ("could not tell"), never false.
CONFIRM_MISSING_PS = r"""function Test-LocalPath([string]$path) {
  if ($path -notmatch '^[A-Za-z]:\\') { return $false }
  try {
    $type = [string](New-Object System.IO.DriveInfo $path.Substring(0, 1)).DriveType
  } catch {
    return $false
  }
  return @('Fixed', 'Removable', 'Ram') -contains $type
}
function Confirm-Missing([string]$path) {
  try {
    $parent = [System.IO.Path]::GetDirectoryName($path)
    $leaf = [System.IO.Path]::GetFileName($path)
    if (-not $parent -or -not $leaf -or $leaf.IndexOfAny([char[]]'*?') -ge 0) { return $null }
    if (@([System.IO.Directory]::GetFileSystemEntries($parent, $leaf)).Count -eq 0) { return $false }
    return $null
  } catch [System.IO.DirectoryNotFoundException] {
    return $false
  } catch {
    return $null
  }
}
"""

# __INPUT__ is replaced by the quoted path of {"paths": [...]}. A path without
# a folder is looked up in System32, the Windows folder and PATH, as Windows
# would start it. Nothing is written; a file that cannot be read is one row
# with Error. Exists is false only when Confirm-Missing confirms it on a local
# drive; a file File.Exists does not see but that cannot be confirmed missing
# gives Exists null with ExistsReason: not_local (a network path, a drive that
# is not local, a name not found on PATH) or not_confirmed (access denied, a
# drive not ready).
FILE_FACTS_BODY = CONFIRM_MISSING_PS + r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
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
    $reason = $null
    if (-not $exists) {
      $exists = $null
      if (Test-LocalPath $expanded) { $exists = Confirm-Missing $expanded }
      if ($null -eq $exists) {
        if (Test-LocalPath $expanded) { $reason = 'not_confirmed' } else { $reason = 'not_local' }
      }
    }
    $status = $null; $signer = $null; $company = $null; $sha = $null; $shaError = $null
    if ($exists) {
      try { $sha = S (Get-FileHash -LiteralPath $expanded -Algorithm SHA256 -ErrorAction Stop).Hash }
      catch { $shaError = S $_.Exception.Message }
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
      ExistsReason = $reason
      SignatureStatus = $status; Signer = $signer; Company = $company
      Sha256 = $sha; Sha256Error = $shaError
    })
  } catch {
    $rows.Add([pscustomobject]@{ Kind = 'file'; Path = $path; Error = S $_.Exception.Message })
  }
}
$result = $rows.ToArray()
"""

# __INPUT__ is replaced by the quoted path of {"apps": [...]} (the raw App values
# of the firewall rules). Nothing is written. exists is null when the expanded
# value still holds a % (a variable this account does not know), is not a full
# path on a local drive (UNC and network drives are never touched: nothing
# leaves the machine, and a host that does not answer would stall the job), or Get-Item fails for another reason than "not found" (e.g. access denied
# in WindowsApps); only ItemNotFoundException is false, and only when listing the
# parent folder confirms it: 5.1 also says "not found" for a file in a folder this
# account may not read (UnauthorizedAccessException there gives null).
FIREWALL_APPS_BODY = CONFIRM_MISSING_PS + r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$rows = New-Object System.Collections.Generic.List[object]
foreach ($a in @($in.apps)) {
  $app = S $a
  if (-not $app) { continue }
  $expanded = [Environment]::ExpandEnvironmentVariables($app)
  $exists = $null
  if ($expanded.IndexOf('%') -lt 0) {
    try {
      if (Test-LocalPath $expanded) {
        $null = Get-Item -LiteralPath $expanded -Force -ErrorAction Stop
        $exists = $true
      }
    } catch [System.Management.Automation.ItemNotFoundException] {
      $exists = Confirm-Missing $expanded
    } catch {
      $exists = $null
    }
  }
  $rows.Add([pscustomobject]@{ app = $app; expanded = $expanded; exists = $exists })
}
$result = $rows.ToArray()
"""

# __INPUT__ is replaced by the quoted path of {"folders": [...]} (the install
# folders of removed programs). Nothing is written. A folder is looked up by
# listing its parent, so a denied parent is "could not read" (exists null), not
# "not there"; a parent that is not there is "not there". A folder that is there
# is walked with an explicit stack; a junction or symbolic link is not followed.
# Any subfolder that cannot be listed makes the folder unreadable with the first
# error and no counts: partial counts would pass for the whole folder.
INSTALL_FOLDERS_BODY = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
function Message($err) {
  $ex = $err.Exception
  if ($null -ne $ex.InnerException) { $ex = $ex.InnerException }
  return S $ex.Message
}
$rows = New-Object System.Collections.Generic.List[object]
foreach ($f in @($in.folders)) {
  $path = S $f
  if (-not $path) { continue }
  $row = [ordered]@{ path = $path; exists = $null; status = 'unreadable'; reason = $null
    files = $null; bytes = $null; newest_write = $null; extensions = $null }
  try {
    $dir = $path.TrimEnd('\')
    $parent = [System.IO.Path]::GetDirectoryName($dir)
    $leaf = [System.IO.Path]::GetFileName($dir)
    if (-not $parent -or -not $leaf -or $leaf.IndexOfAny([char[]]'*?') -ge 0) {
      throw 'not a full folder path'
    }
    $found = $false
    try {
      $found = @([System.IO.Directory]::GetDirectories($parent, $leaf)).Count -gt 0
    } catch [System.IO.DirectoryNotFoundException] {
      $found = $false
    }
    if (-not $found) {
      $row.exists = $false
      $row.status = 'read'
    } else {
      $row.exists = $true
      $files = [long]0; $bytes = [long]0; $newest = $null; $ext = @{}; $first = $null
      $stack = New-Object System.Collections.Generic.Stack[string]
      $stack.Push($dir)
      while ($stack.Count -gt 0) {
        $d = $stack.Pop()
        try {
          foreach ($e in (New-Object System.IO.DirectoryInfo $d).GetFileSystemInfos()) {
            if ($e -is [System.IO.DirectoryInfo]) {
              if (($e.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
                $stack.Push($e.FullName)
              }
            } else {
              $files++
              $bytes += $e.Length
              $t = $e.LastWriteTimeUtc
              if ($null -eq $newest -or $t -gt $newest) { $newest = $t }
              $x = $e.Extension.ToLowerInvariant()
              if ($ext.ContainsKey($x)) { $ext[$x]++ } else { $ext[$x] = 1 }
            }
          }
        } catch {
          if ($null -eq $first) { $first = Message $_ }
        }
      }
      if ($null -ne $first) {
        $row.reason = $first
      } else {
        $top = @($ext.GetEnumerator() |
          Sort-Object @{ Expression = { $_.Value }; Descending = $true }, @{ Expression = { $_.Key } } |
          Select-Object -First 10)
        $list = New-Object System.Collections.Generic.List[object]
        foreach ($p in $top) { $list.Add([pscustomobject]@{ extension = [string]$p.Key; files = [long]$p.Value }) }
        $row.status = 'read'
        $row.files = $files
        $row.bytes = $bytes
        if ($null -ne $newest) { $row.newest_write = $newest.ToString('s') + 'Z' }
        $row.extensions = $list.ToArray()
      }
    }
  } catch {
    $row.exists = $null
    $row.status = 'unreadable'
    $row.reason = Message $_
  }
  $rows.Add([pscustomobject]$row)
}
$result = $rows.ToArray()
"""

# __INPUT__ is replaced by the quoted path of {"keys": [...]}: registry keys
# "HKLM\SOFTWARE\<publisher>\<name>" (also under WOW6432Node) and
# "HKCU\SOFTWARE\<publisher>\<name>" of removed programs. Read only: OpenSubKey
# without write access gives null for a missing key and throws when access is
# denied, so a denied key is "could not read" (exists null), never "not there".
# The 32-bit key is read by its WOW6432Node path in the 64-bit view.
LEFTOVER_KEYS_BODY = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$hives = @{ 'HKLM' = [Microsoft.Win32.RegistryHive]::LocalMachine; 'HKCU' = [Microsoft.Win32.RegistryHive]::CurrentUser }
$rows = New-Object System.Collections.Generic.List[object]
foreach ($p in @($in.keys)) {
  $path = S $p
  if (-not $path) { continue }
  $row = [ordered]@{ path = $path; exists = $null; status = 'unreadable'; reason = $null
    values = $null; subkeys = $null }
  try {
    $hive, $sub = $path.Split([char[]]'\', 2)
    if (-not $hives.ContainsKey($hive) -or -not $sub) { throw 'not an HKLM or HKCU key path' }
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hives[$hive], [Microsoft.Win32.RegistryView]::Registry64)
    try {
      $k = $base.OpenSubKey($sub)
      if ($null -eq $k) {
        $row.exists = $false
        $row.status = 'read'
      } else {
        try {
          $row.values = [long]$k.ValueCount
          $row.subkeys = [long]$k.SubKeyCount
          $row.exists = $true
          $row.status = 'read'
        } finally { $k.Close() }
      }
    } finally { $base.Close() }
  } catch {
    $row.exists = $null
    $row.status = 'unreadable'
    $row.values = $null
    $row.subkeys = $null
    $ex = $_.Exception
    if ($null -ne $ex.InnerException) { $ex = $ex.InnerException }
    $row.reason = S $ex.Message
  }
  $rows.Add([pscustomobject]$row)
}
$result = $rows.ToArray()
"""

# __INPUT__ is replaced by the quoted path of {"roots": [...]}: raw roots such as
# "%ProgramFiles%", expanded here. Read only: one row per root with its direct
# child folders. A root that cannot be listed (a variable left unexpanded, not
# there, access denied) is "unreadable" with the reason and no folders. A child
# that is a reparse point (a junction) is only marked, never opened. A child whose
# entries cannot be listed has has_entries null and the reason, never false.
VENDOR_FOLDERS_BODY = r"""$in = [System.IO.File]::ReadAllText(__INPUT__, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
function Message($err) {
  $ex = $err.Exception
  if ($null -ne $ex.InnerException) { $ex = $ex.InnerException }
  return S $ex.Message
}
$rows = New-Object System.Collections.Generic.List[object]
foreach ($r in @($in.roots)) {
  $raw = S $r
  if (-not $raw) { continue }
  $expanded = ([System.Environment]::ExpandEnvironmentVariables($raw)).TrimEnd('\')
  $row = [ordered]@{ root = $raw; expanded = $expanded; status = 'unreadable'; reason = $null
    folders = $null }
  try {
    if ($expanded.Contains('%')) { throw 'the root holds a variable this account does not know' }
    if (-not [System.IO.Path]::IsPathRooted($expanded)) { throw 'the root is not a full path' }
    $children = (New-Object System.IO.DirectoryInfo $expanded).GetDirectories()
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($d in $children) {
      $f = [ordered]@{ name = S $d.Name; path = S $d.FullName; reparse_point = $false
        has_entries = $null; reason = $null; last_write = $null }
      try { $f.last_write = $d.LastWriteTimeUtc.ToString('s') + 'Z' } catch { }
      if (($d.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        $f.reparse_point = $true
      } else {
        try {
          $e = [System.IO.Directory]::EnumerateFileSystemEntries($d.FullName).GetEnumerator()
          try { $f.has_entries = [bool]$e.MoveNext() } finally { $e.Dispose() }
        } catch {
          $f.has_entries = $null
          $f.reason = Message $_
        }
      }
      $list.Add([pscustomobject]$f)
    }
    $row.status = 'read'
    $row.folders = $list.ToArray()
  } catch {
    $row.status = 'unreadable'
    $row.folders = $null
    $row.reason = Message $_
  }
  $rows.Add([pscustomobject]$row)
}
$result = $rows.ToArray()
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

# Works without administrator rights. The driver store listing as XML (its tag names
# are not translated); the whole stdout and the exit code go to Python, which parses
# it. An older pnputil that refuses /format gives its usage text and a non-zero exit.
DRIVER_PACKAGES_BODY = r"""$exe = Join-Path $env:SystemRoot 'System32\pnputil.exe'
$text = (& $exe /enum-drivers /format xml | Out-String)
$result = [pscustomobject]@{ exit_code = $LASTEXITCODE; text = $text }
"""

# Works without administrator rights. Every device Windows knows, present or not, as
# XML (tag names are not translated); the whole stdout and the exit code go to Python.
# For each Disconnected device with an oem<N>.inf driver, DEVPKEY_Device_LastRemovalDate
# (a FileTime, readable without elevation) as a UTC yyyy-MM-dd, null when not read;
# keyed by the instance id, which only this raw file holds.
DEVICES_BODY = r"""$inv = [System.Globalization.CultureInfo]::InvariantCulture
$exe = Join-Path $env:SystemRoot 'System32\pnputil.exe'
$text = (& $exe /enum-devices /drivers /format xml | Out-String)
$code = $LASTEXITCODE
$removal = @{}
$xml = $null
if ($code -eq 0) { try { $xml = [xml]$text } catch { $xml = $null } }
if ($xml -ne $null) {
  foreach ($dev in @($xml.SelectNodes('/PnpUtil/Device'))) {
    $id = $dev.GetAttribute('InstanceId')
    $status = $dev.SelectSingleNode('Status')
    $driver = $dev.SelectSingleNode('DriverName')
    if (-not $id -or $status -eq $null -or $driver -eq $null) { continue }
    if ($status.InnerText.Trim() -ne 'Disconnected') { continue }
    if ($driver.InnerText.Trim() -notmatch '^oem\d+\.inf$') { continue }
    $day = $null
    try {
      $prop = Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_LastRemovalDate' -ErrorAction Stop
      if ($prop.Data -is [datetime]) { $day = $prop.Data.ToUniversalTime().ToString('yyyy-MM-dd', $inv) }
    } catch { $day = $null }
    $removal[$id] = $day
  }
}
$result = [pscustomobject]@{ exit_code = $code; text = $text; last_removal = $removal }
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
    return tuple(int(p) if p.strip().isascii() and p.strip().isdigit() else -1
                 for p in value.split("."))


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


def load_vendor_folders(path: Path):
    """The data file of the vendor folders as ``(config, None)``, or ``(None, reason)``.

    ``roots`` is the list of raw root strings (``%ProgramFiles%``), ``windows_names``
    a set of case-folded folder names and ``vendors`` ``{case-folded folder name:
    {case-folded publisher}}``. A file that cannot be used gives no config, so no
    folder is called unmatched by a list that was not read.
    """
    name = Path(path).name
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{name} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"{name} does not hold an object"
    roots = data.get("roots")
    if not is_strings(roots) or not roots or not all(root.strip() for root in roots):
        return None, f"{name}: roots is not a list of non-empty strings"
    names = data.get("windows_names")
    if not is_strings(names):
        return None, f"{name}: windows_names is not a list of strings"
    vendors = data.get("vendors")
    if not isinstance(vendors, dict) or not all(
            is_strings(publishers) for publishers in vendors.values()):
        return None, f"{name}: vendors is not an object of lists of strings"
    folded = {}
    for folder, publishers in vendors.items():
        folded.setdefault(folder.strip().casefold(), set()).update(
            p.strip().casefold() for p in publishers if p.strip())
    return {
        "roots": [root.strip() for root in roots],
        "windows_names": {n.strip().casefold() for n in names},
        "vendors": folded,
    }, None


def load_driver_package_groups(path: Path):
    """The rules of the driver package groups file as ``(rules, None)``, or
    ``(None, reason)`` when the file cannot be used.

    The file is a list of rules, each an object with exactly one of ``class`` and
    ``provider`` (a non-empty string), a non-empty ``group`` and a boolean
    ``no_device_by_nature``; no class and no provider in two rules (compared
    case-folded). Each rule comes back as ``{"match": "class" or "provider", "value":
    case-folded name, "group", "no_device_by_nature"}``. A file that cannot be used
    gives no rules, so no package is put in a group by a list that was not read."""
    name = Path(path).name
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{name} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(data, list):
        return None, f"{name} does not hold a list"
    rules = []
    seen = {"class": set(), "provider": set()}
    for number, item in enumerate(data, 1):
        if not isinstance(item, dict):
            return None, f"{name}: rule {number} is not an object"
        group = item.get("group")
        if not isinstance(group, str) or not group.strip():
            return None, f"{name}: rule {number} has no group"
        if not isinstance(item.get("no_device_by_nature"), bool):
            return None, f"{name}: rule {number}: no_device_by_nature is not true or false"
        keys = [key for key in ("class", "provider") if key in item]
        if len(keys) != 1:
            return None, f"{name}: rule {number} has neither or both of class and provider"
        value = item[keys[0]]
        if not isinstance(value, str) or not value.strip():
            return None, f"{name}: rule {number}: {keys[0]} is not a non-empty string"
        folded = value.strip().casefold()
        if folded in seen[keys[0]]:
            return None, f"{name}: {keys[0]} {value.strip()!r} is in two rules"
        seen[keys[0]].add(folded)
        rules.append({"match": keys[0], "value": folded, "group": group.strip(),
                      "no_device_by_nature": item["no_device_by_nature"]})
    return rules, None


def package_group(item: dict, rules) -> tuple:
    """``(group, no_device_by_nature)`` of one driver package by ``rules`` (see
    ``load_driver_package_groups``): a provider rule wins over a class rule, a package
    no rule matches is ``other``; ``(None, None)`` when the rules were not read."""
    if rules is None:
        return None, None
    for match in ("provider", "class"):
        value = item.get(match)
        if not isinstance(value, str):
            continue
        folded = value.strip().casefold()
        for rule in rules:
            if rule["match"] == match and rule["value"] == folded:
                return rule["group"], rule["no_device_by_nature"]
    return "other", False


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
        self.drivers_without_inf_items = None  # set by collect: their name and class
        # set by collect_devices: every device of the device listing ({device_name,
        # class, status, driver_name, last_removal}), None when it was not read
        self.devices = None
        self.hosts_file = None  # set by collect_hosts: the folder and file of hosts
        self.current_sid = None  # set by collect_administrators
        # set by collect_facts: {(source, key): {target path}} of the facts taken from
        # the previous baseline, for a comparison with another state (compare_view)
        self.carried_facts = {}
        # set by the collectors: {(source, key)} of the items seen in this run whose
        # row could not be read, for a comparison with another state (compare_view)
        self.unread_keys = set()
        # set by apply_firewall_apps: {raw App value, case-folded: expanded path}
        self.firewall_expanded = {}
        # set by collect_pip: the summary part package_managers.pip
        self.pip_summary = None
        # set by collect_npm: the summary part package_managers.npm
        self.npm_summary = None

    def job(self, job: str, body: str, depth: int = 4, file_name: str | None = None) -> dict:
        """Run one job; its output file is named by ``file_name`` (default: ``job``)."""
        out_path = self.work / f"inventory-{self.stamp}.{file_name or job}.json"
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
            col.unread_keys.add(("win32_programs", key))
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
    col.unread_keys.add((source, key))
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


def guess_instance(name: str, previous: dict, reference: dict | None = None) -> bool:
    """Whether a service whose ``Type`` was not read is a per-user instance.

    A baseline entry under the full name wins; then one under the template decides
    by its ``user_service``. ``previous`` (the latest baseline) is asked first, then
    ``reference`` (the state compared with, e.g. a history copy) by the same rules;
    with neither entry in either, only a name ending in ``INSTANCE_GUESS_SUFFIX``
    (``_`` and at least 5 hex digits) is taken for an instance, so a name such as
    ``Agent_1`` keeps its own key.
    """
    template = INSTANCE_SUFFIX.sub("", name)
    if template == name:
        return False
    for known_items in (previous, reference or {}):
        if f"service:{name}" in known_items:
            return False
        known = known_items.get(f"service:{template}")
        if known is not None:
            return isinstance(known, dict) and known.get("user_service") is True
    return INSTANCE_GUESS_SUFFIX.search(name) is not None


def collect_services(col: Collector, previous: dict,
                     reference: dict | None = None) -> tuple[str, dict]:
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
    ``user_service`` true; the full name when it has that key otherwise; when the
    baseline has neither key, the same rules with ``reference`` (the state compared
    with); the template when the name ends in ``INSTANCE_GUESS_SUFFIX`` (``_`` and at
    least 5 hex digits); else the full name.
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
            instance = guess_instance(name, previous, reference)
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
            col.unread_keys.add(("services", key))
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


def file_hash(row: dict, exists) -> dict:
    """``{sha256, sha256_error}`` of a ``file_facts`` row: the lower-case hash the job
    read, or None with the reason it has none."""
    value = text(row.get("Sha256"))
    if value is not None and SHA256_RE.fullmatch(value):
        return {"sha256": value.lower(), "sha256_error": None}
    error = text(row.get("Sha256Error"))
    if error is None:
        error = ("the file does not exist" if exists is False
                 else "the file's existence is not confirmed" if exists is None
                 else "the job gave no hash" if value is None
                 else f"the job gave no valid hash: {value[:40]!r}")
    return {"sha256": None, "sha256_error": error}


def carried_fact(known: dict) -> dict:
    """The fact fields of a baseline fact; a baseline from before the hash existed
    gives a null ``sha256`` with its reason."""
    fact = {field: known.get(field) for field in FACT_FIELDS}
    if fact["sha256"] is None and fact["sha256_error"] is None:
        fact["sha256_error"] = "the baseline holds no hash"
    return fact


def hash_reason(fact: dict, default: str) -> dict:
    """``fact`` with a reason for every null hash: its ``check_error``, else
    ``default``, or "no path" for a target without one."""
    if fact.get("sha256") is None and fact.get("sha256_error") is None:
        fact["sha256_error"] = (fact.get("check_error")
                                or (default if fact.get("path") is not None
                                    else "the target has no path"))
    return fact


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

    errors, unknown = {}, {}
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
                    # A file that could not be checked keeps its previous facts;
                    # check_error (detail file only) says why it was not checked.
                    errors.setdefault(target, text(row.get("Error")))
                    fact["check_error"] = text(row.get("Error"))
                    if target in known:
                        fact.update(carried_fact(known[target]))
                        item["facts_from_baseline"] = True
                        col.carried_facts.setdefault((source, key), set()).add(target)
                    else:
                        unread.add("facts")
                elif row is not None:
                    exists = row.get("Exists")
                    if not isinstance(exists, bool):
                        cause = EXISTS_UNKNOWN.get(text(row.get("ExistsReason")),
                                                   EXISTS_UNKNOWN[None])
                        unknown.setdefault(cause, []).append(target)
                    fact.update(
                        expanded_path=text(row.get("ExpandedPath")),
                        exists=exists if isinstance(exists, bool) else None,
                        signature_status=text(row.get("SignatureStatus")),
                        signer=text(row.get("Signer")),
                        company=text(row.get("Company")),
                    )
                    fact.update(file_hash(row, fact["exists"]))
                elif target is not None:
                    fact["sha256_error"] = "the job gave no row for this file"
                    unread.add("facts")
                fact["program"] = match(fact["expanded_path"])
                facts.append(hash_reason(fact, "the file could not be checked"))
        else:
            for target in item["targets"]:
                fact = null_fact(target)
                if target in known:
                    fact.update(carried_fact(known[target]))
                    fact["program"] = match(fact["expanded_path"])
                    item["facts_from_baseline"] = True
                    col.carried_facts.setdefault((source, key), set()).add(target)
                elif target is not None:
                    unread.add("facts")
                facts.append(hash_reason(fact, "the file facts were not read"))
        item["facts"] = facts
        if unread:
            item["unread_fields"] = sorted(unread)
        item["own"] = entry_own(item, config)
    # One not_checked item per file that could not be checked (at most
    # APP_UNREAD_NAMED), then one item counting the rest.
    for target, error in list(errors.items())[:APP_UNREAD_NAMED]:
        col.skip(f"file_facts {target}", error)
    more = len(errors) - APP_UNREAD_NAMED
    if more > 0:
        col.skip("file_facts more",
                 f"{more} more target(s) could not be checked; the detail file names "
                 f"each in its fact with check_error, the reason")
    # One not_checked item per cause, naming the targets (at most APP_UNREAD_NAMED).
    for cause, targets in sorted(unknown.items()):
        targets = list(dict.fromkeys(targets))
        named = ", ".join(targets[:APP_UNREAD_NAMED])
        more = len(targets) - APP_UNREAD_NAMED
        if more > 0:
            named += f" and {more} more (their facts have exists null in the detail file)"
        col.skip("file_facts exists",
                 f"{len(targets)} target(s): {named}; exists is null: {cause}")
    return status, dirs


# Why a file_facts row has Exists null (ExistsReason); None: no or an unknown reason.
EXISTS_UNKNOWN = {
    "not_local": "not a full path on a local drive (a network path, a drive that is "
                 "not local, or a name not found on the search path), so it was not "
                 "checked",
    "not_confirmed": "the file was not seen, but listing its folder could not confirm "
                     "it is missing (access denied, or the drive is not ready)",
    None: "the check gave no answer",
}


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


def collect_drivers(col: Collector, patterns) -> tuple[str, dict, list | None]:
    """``(status, {key: item}, rows without InfName)`` of ``Win32_PnPSignedDriver``.

    ``third_party`` is whether ``inf_name`` matches one of ``patterns`` (case-folded
    fnmatch patterns); ``own`` is its opposite. With ``patterns`` None (the data file
    could not be read) ``third_party`` is null and unread, and ``own`` is false. The
    rows without ``InfName`` are ``{device_name, class}`` (no device id), None when
    the source was not read.
    """
    result = col.job("drivers", DRIVERS_BODY)
    items, without_inf, without_id = {}, [], 0
    for row in result["rows"]:
        inf_name = text(row.get("InfName"))
        if inf_name is None:  # no INF file: e.g. a software device, or no driver
            without_inf.append({"device_name": text(row.get("DeviceName")),
                                "class": text(row.get("DeviceClass"))})
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


def package_version(value) -> tuple:
    """``(date, version)`` of a ``DriverVersion`` ``MM/DD/YYYY <version>``; the date as
    ``YYYY-MM-DD``. Any other shape (or a date that does not exist) gives ``(None,
    None)``."""
    match = PACKAGE_VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None, None
    month, day, year, version = match.groups()
    try:
        return date(int(year), int(month), int(day)).isoformat(), version
    except ValueError:
        return None, None


def parse_driver_store(value) -> tuple:
    """``(packages, reason)`` of the driver store listing XML: one dict per ``Driver``
    element ``{published_name, original_name, provider, class, version, date, signer}``
    (a missing value is None), or ``(None, reason)`` when the text is no listing."""
    if not isinstance(value, str) or not value.strip():
        return None, "the driver store listing gave no text"
    try:
        root = ET.fromstring(value.strip())
    except ET.ParseError as exc:
        return None, f"the driver store listing is not XML: {exc}"
    if root.tag != "PnpUtil":
        return None, f"the driver store listing has the root element {root.tag!r}, not PnpUtil"
    packages = []
    for element in root.iter("Driver"):
        day, version = package_version(element.findtext("DriverVersion"))
        packages.append({
            "published_name": text(element.get("DriverName")),
            "original_name": text(element.findtext("OriginalName")),
            "provider": text(element.findtext("ProviderName")),
            "class": text(element.findtext("ClassName")),
            "version": version,
            "date": day,
            "signer": text(element.findtext("SignerName")),
        })
    return packages, None


def pnputil_listing(col: Collector, name: str, body: str, what: str) -> tuple:
    """``(status, reason, row)`` of a job that answers one ``{exit_code, text}`` object
    of a pnputil ``/format xml`` listing (``what`` names it in a reason). A failed
    job, no single object, no exit code or an exit code other than 0 is
    ``unreadable`` with the reason; ``row`` is the object when ``read``."""
    result = col.job(name, body)
    rows = [row for row in result["rows"] if isinstance(row, dict)]
    status, reason = result["status"], result["reason"]
    if status == "read" and len(rows) != 1:
        return "unreadable", f"the {name} job gave {len(rows)} objects, not one", None
    if status != "read":
        return "unreadable", reason or f"the {name} job gave no result", None
    code = rows[0].get("exit_code")
    if isinstance(code, bool) or not isinstance(code, int):
        return "unreadable", f"the {name} job gave no exit code", None
    if code != 0:
        output = (text(rows[0].get("text")) or "").strip()[:300]
        return "unreadable", (f"the {what} ended with exit code {code} (an older "
                              f"Windows may not know /format xml): "
                              f"{output or 'no output'}"), None
    return "read", None, rows[0]


def removal_day(value):
    """``value`` when it is a ``yyyy-MM-dd`` day that exists, else None."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def parse_devices(value, last_removal) -> tuple:
    """``(devices, reason)`` of the device listing XML: one dict per ``Device`` element
    ``{device_name, class, status, driver_name, last_removal}`` (a missing value is
    None), or ``(None, reason)`` when the text is no listing. ``last_removal`` maps an
    instance id to ``yyyy-MM-dd``; a missing or other value, or a map that is no dict,
    gives null. The instance id is used for that lookup only and is not kept."""
    if not isinstance(value, str) or not value.strip():
        return None, "the device listing gave no text"
    try:
        root = ET.fromstring(value.strip())
    except ET.ParseError as exc:
        return None, f"the device listing is not XML: {exc}"
    if root.tag != "PnpUtil":
        return None, f"the device listing has the root element {root.tag!r}, not PnpUtil"
    dates = last_removal if isinstance(last_removal, dict) else {}
    devices = []
    for element in root.iter("Device"):
        devices.append({
            "device_name": text(element.findtext("DeviceDescription")),
            "class": text(element.findtext("ClassName")),
            "status": text(element.findtext("Status")),
            "driver_name": text(element.findtext("DriverName")),
            "last_removal": removal_day(dates.get(element.get("InstanceId"))),
        })
    return devices, None


def collect_devices(col: Collector) -> str:
    """The status of the ``devices`` source; sets ``col.devices`` (None unless read).

    A failed job, an exit code other than 0 or a text that is no listing makes the
    source unreadable with the reason, never empty; a listing without a ``Device``
    is ``empty``."""
    status, reason, row = pnputil_listing(col, "devices", DEVICES_BODY, "device listing")
    if status == "read":
        devices, reason = parse_devices(row.get("text"), row.get("last_removal"))
        if devices is None:
            status = "unreadable"
        elif not devices:
            status = "empty"
        col.devices = devices
    col.record("devices", status, reason)
    return status


def collect_driver_packages(col: Collector) -> tuple[str, dict]:
    """``(status, {key: item})`` of the third-party packages (``oem<N>.inf``) of the
    driver store.

    A failed job, an exit code other than 0 or a text that is no listing makes the
    source unreadable with the reason. The key is ``driver_package:<original
    name>|<provider>|<version>``, case-folded; a package without an original name has
    no key. A second package with the same key (another published name) is no item
    of its own: its published name goes to ``other_published_names`` of the first.
    A missing published name, date or version is null and named in
    ``unread_fields``; the published name is not part of the key.
    """
    status, reason, row = pnputil_listing(col, "driver_packages", DRIVER_PACKAGES_BODY,
                                          "driver store listing")
    packages = None
    if status == "read":
        packages, reason = parse_driver_store(row.get("text"))
        if packages is None:
            status = "unreadable"
    items, without_name = {}, 0
    if status != "read":
        col.record("driver_packages", status, reason)
        return status, items
    for package in packages:
        published = package["published_name"]
        # The listing holds third-party packages only, so a package whose published
        # name was not read is kept with that field unread (the key does not use it),
        # never taken for one that ships with Windows.
        if published is not None and not THIRD_PARTY_PACKAGE.fullmatch(published.strip()):
            continue  # a package that ships with Windows
        original = package["original_name"]
        if original is None:
            without_name += 1
            continue
        key = (f"driver_package:{original}|{package['provider'] or ''}|"
               f"{package['version'] or ''}").casefold()
        if key in items:
            if published is None:
                unread = items[key].setdefault("unread_fields", [])
                if "published_name" not in unread:
                    unread.append("published_name")
            elif items[key]["published_name"] is None:
                items[key]["published_name"] = published
            else:
                items[key].setdefault("other_published_names", []).append(published)
            continue
        item = dict(package)
        unread = [field for field in ("published_name", "version", "date")
                  if item[field] is None]
        if unread:
            item["unread_fields"] = unread
        items[key] = item
    skip_keyless(col, "driver_packages", "OriginalName", without_name)
    status, reason = entry_status("driver_packages", {"status": status, "reason": reason},
                                  items, without_name)
    col.record("driver_packages", status, reason)
    return status, items


def parse_firewall_rule(value, builtin) -> dict:
    """The fields of one rule text ``v2.xx|Key=Value|...|``.

    A key that appears more than once (e.g. ``LPort``) gives a list, once a string,
    never a null placeholder for a missing key. ``lport2`` lists the values of every
    other key starting with ``LPort`` (``LPort2_10`` ...), null when there is none. ``protocol`` is a number,
    ``protocol_name`` its name when known. ``own`` is true when every field of
    ``builtin['required_fields']`` is there and ``Name`` starts with its
    ``name_prefix``; with ``builtin`` None (the data file could not be read) no rule
    is own. A text that is no ``v2.`` rule gives every field null, and ``rule`` and
    every compared field in ``unread_fields``, so a later run that reads it is no change.
    """
    rule = {field: None for field in FIREWALL_FIELDS}
    rule.update(protocol=None, protocol_name=None, version=None, own=False, lport2=None)
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
    # The values of every other LPort... key (LPort2_10, LPort2_20, ...), in key order and
    # in value order within a key; detail file only, never compared.
    lport2 = [data for key, values in pairs.items()
              if key.startswith("LPort") and key != "LPort" for data in values]
    rule["lport2"] = lport2 or None
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


def apply_firewall_apps(col: Collector, items: dict) -> None:
    """Set ``app_exists`` of every rule with a program from the ``firewall_apps`` job.

    A rule without ``App``, with an empty one or with ``System`` (any case) gets no
    field. ``app_exists`` is the job's ``exists`` for the raw value, and null (named
    in ``unread_fields``) when ``App`` is a list (the key repeated), the job failed
    or gave no row for the value, its ``exists`` is not a boolean, or its
    ``expanded`` still holds a ``%``. Only ``expanded`` is checked for ``%``: a raw
    ``%SystemRoot%`` is the usual form of a rule. An empty set of values runs no job.
    The rules with a null ``app_exists`` are named in one ``not_checked`` item
    ``firewall_rules app_exists`` per reason (``APP_UNREAD_REASONS``). The expanded
    path of each value without a ``%`` left goes to ``col.firewall_expanded``, for
    the leftovers.
    """
    rules, apps, seen = [], [], set()
    for item in items.values():
        app = item.get("app")
        if app is None or (isinstance(app, str)
                           and (not app.strip() or app.strip().casefold() == FIREWALL_SYSTEM_APP)):
            continue
        rules.append(item)
        if isinstance(app, str) and app.casefold() not in seen:
            seen.add(app.casefold())
            apps.append(app)
    if not rules:
        return
    rows = {}
    if apps:
        input_path = col.work / f"inventory-{col.stamp}.firewall_apps.input.json"
        try:
            input_path.write_text(json.dumps({"apps": apps}, ensure_ascii=True),
                                  encoding="utf-8")
        except OSError as exc:
            result = {"status": "unreadable", "rows": [],
                      "reason": f"the program list could not be written: "
                                f"{type(exc).__name__}: {exc}"}
        else:
            body = FIREWALL_APPS_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
            result = col.job("firewall_apps", body)
        if result["status"] == "unreadable":
            col.skip("firewall_apps", result["reason"])
        elif result["status"] == "empty":
            col.skip("firewall_apps",
                     f"firewall_apps returned no rows for {len(apps)} programs, so "
                     f"app_exists is null")
        for row in result["rows"]:
            app = text(row.get("app"))
            if app is not None:
                rows.setdefault(app.casefold(), row)
        missing = sum(1 for app in apps if app.casefold() not in rows)
        if result["status"] == "read" and missing:
            col.skip("firewall_apps",
                     f"firewall_apps returned no row for {missing} of {len(apps)} "
                     f"programs, so their app_exists is null")
    unread, checked = {}, {id(rule) for rule in rules}
    for key, item in items.items():
        app = item.get("app")
        if id(item) not in checked:
            continue
        row = rows.get(app.casefold()) if isinstance(app, str) else None
        exists = row.get("exists") if row is not None else None
        expanded = row.get("expanded") if row is not None else None
        if isinstance(app, str) and isinstance(expanded, str) and "%" not in expanded:
            col.firewall_expanded.setdefault(app.casefold(), expanded)
        if not isinstance(app, str):
            reason = APP_UNREAD_REASONS["list"]
        elif row is None:
            reason = APP_UNREAD_REASONS["no_row"]
        elif isinstance(expanded, str) and "%" in expanded:
            reason = APP_UNREAD_REASONS["variable"]
        elif not isinstance(exists, bool) or not isinstance(expanded, str):
            reason = APP_UNREAD_REASONS["unknown"]
        else:
            reason = None
        if reason is not None:
            exists = None
        item["app_exists"] = exists
        if exists is None:
            item["unread_fields"] = sorted({*(item.get("unread_fields") or []), "app_exists"})
            unread.setdefault(reason, []).append(key)
    # One not_checked item per reason, naming the rules (at most APP_UNREAD_NAMED).
    for reason, keys in unread.items():
        keys = sorted(keys)
        named = ", ".join(keys[:APP_UNREAD_NAMED])
        more = len(keys) - APP_UNREAD_NAMED
        if more > 0:
            named += (f" and {more} more (their unread_fields name app_exists in the "
                      f"detail file)")
        col.skip("firewall_rules app_exists",
                 f"{len(keys)} rule(s): {named}; app_exists is null: {reason}")


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
    ``builtin`` is whether the SID is that of the built-in Administrator account
    (``S-1-5-21-...-500``).
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
                                   else sid == col.current_sid),
                    "builtin": sid.upper().startswith("S-1-5-21-") and sid.endswith("-500")}
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
    and left out; so is a registration without a company, a tag or an install path,
    and one whose ``<company>/<tag>`` an earlier Python already has.
    """
    result = col.job("python_registrations", PYTHON_REGISTRATIONS_BODY)
    if result["status"] == "unreadable":
        return "unreadable", result["reason"], []
    pythons, paths, names = [], set(), set()
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
            col.skip(f"pip_packages {python}",
                     "the PEP 514 registration has no InstallPath, so its packages are "
                     "not read")
            continue
        folded = install.strip().rstrip("\\/").casefold()
        if folded in paths:
            continue
        paths.add(folded)
        if STORE_PYTHON_PART in folded + "\\":
            col.skip(f"Python {tag} from the Microsoft Store (WindowsApps)",
                     "packages not read")
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
    input_path = col.work / f"inventory-{col.stamp}.{file_name}.input.json"
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


def collect_pip(col: Collector, previous: dict) -> tuple[str, dict]:
    """``(status, {key: item})`` of the source ``pip_packages``; the summary part
    ``{status, pythons}`` is kept in ``col.pip_summary``.

    Status ``read`` with at least one Python whose folders were looked at, ``empty``
    with none (no registration, or each one skipped and named in not_checked: from
    the Microsoft Store, without an InstallPath, or without a company or tag), ``unreadable`` when the registrations could
    not be read. A folder that could not be read (or was skipped) keeps its items from
    the previous baseline, marked ``from_baseline``, so they are not reported as
    removed; that Python's ``count`` is then null (unreadable) and the folder is named
    in not_checked.
    """
    col.skip(*UNREGISTERED_PYTHONS)
    status, reason, pythons = python_registrations(col)
    col.record("pip_packages", status, reason)
    if status != "read":
        col.pip_summary = {"status": status,
                           "pythons": [] if status == "empty" else None}
        return status, {}
    folders = []  # (python, kind, raw path or None, reason when None)
    for python in pythons:
        folders.append((python, "install", python["install_path"] + "\\Lib\\site-packages",
                        None))
        folders.append((python, "user", *user_site_packages(python)))
    answers = read_package_folders(
        col, list(dict.fromkeys(path for _, _, path, _ in folders if path is not None)))
    items, entries = {}, {}
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
            prefix = f"pip:{name}|{kind}|"
            for key, item in (previous or {}).items():
                if key.startswith(prefix) and isinstance(item, dict):
                    items[key] = copy.deepcopy(item)
                    items[key]["from_baseline"] = True  # not read in this run
                    col.unread_keys.add(("pip_packages", key))
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
# package.json (npm does not run). The package managers that are not read.
NPM_DEFAULT_PREFIX = "%APPDATA%\\npm"
NPMRC_PREFIX = re.compile(r"\s*prefix\s*=\s*(.*?)\s*$")
WINGET_NOT_READ = ("winget: not read",
                   "`winget list` may go online and has no offline flag")
OTHER_MANAGERS = ("other package managers (choco, scoop, cargo, go)", "not searched")
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
    package count) is null with status ``unreadable``. Also names the package managers
    that are not read (winget, the others) in not_checked, and, when npm is ``empty``,
    the prefixes not searched.
    """
    col.skip(*WINGET_NOT_READ)
    col.skip(*OTHER_MANAGERS)
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


def collect(run_ps, work: Path, stamp: str, previous: dict, config: dict, admin: bool,
            first_run: dict, reference: dict | None = None):
    """Run every source: ``(statuses, {source: {key: item}}, collector)``.

    ``reference`` is the state compared with; it only helps to key a service whose
    ``Type`` was not read.

    ``statuses`` and the returned map also hold ``file_facts`` (its directories), so
    they are kept in the baseline; ``startup_approved`` has a status and no items.
    The collector keeps the driver rows without ``InfName`` and their count.
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
        col, previous.get("services") or {}, (reference or {}).get("services") or {})

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
    statuses["drivers"], current["drivers"], col.drivers_without_inf_items = collect_drivers(
        col, config["driver_third_party_inf"])
    if col.drivers_without_inf_items is not None:
        col.drivers_without_inf = len(col.drivers_without_inf_items)
    statuses["driver_packages"], current["driver_packages"] = collect_driver_packages(col)
    # The states of the packages; not a baseline source (statuses), no item of its own.
    collect_devices(col)

    statuses["firewall_rules"], current["firewall_rules"] = collect_firewall(
        col, config["firewall_builtin"])
    apply_firewall_apps(col, current["firewall_rules"])
    statuses["root_certificates"], current["root_certificates"] = collect_certificates(
        col, config, first_run)
    statuses["hosts"], current["hosts"] = collect_hosts(col, config["hosts_default_dir"])
    statuses["administrators"], current["administrators"] = collect_administrators(col)
    statuses["defender_exclusions"], current["defender_exclusions"] = collect_defender(
        col, admin)
    statuses["pip_packages"], current["pip_packages"] = collect_pip(
        col, previous.get("pip_packages") or {})
    statuses["npm_packages"], current["npm_packages"] = collect_npm(
        col, previous.get("npm_packages") or {})
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


def numbering_of(numbering):
    """The run's ``ids.Numbering``, or one over an empty map (ids by place) for a
    caller without one."""
    return numbering if numbering is not None else ids.Numbering.fresh(SKILL)


def build_programs(current: dict, own_kinds: set, numbering=None) -> tuple[list, int]:
    """Every program with an id: listed ones (``own: false``) first, then own ones.
    The id is the stable number of the program's ``key`` (``numbering``)."""
    entries = [(source, key, item) for source in PROGRAM_SOURCES
               for key, item in current.get(source, {}).items()]
    entries.sort(key=program_order)
    listed = [e for e in entries if not is_own(e[0], e[2], own_kinds)]
    own = [e for e in entries if is_own(e[0], e[2], own_kinds)]
    programs = []
    for source, key, item in listed + own:
        programs.append({"id": None, "key": key, "source": source,
                         "own": is_own(source, item, own_kinds), **item})
    numbering_of(numbering).assign("a", programs)
    return programs, len(own)


def load_suffixes(path: Path):
    """The per-user name suffixes as ``(list, None)``, or ``(None, reason)``.

    The file holds a list of non-empty strings; an empty suffix would pair any
    two programs of the same name, so it makes the file unusable.
    """
    name = Path(path).name
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{name} could not be read: {type(exc).__name__}: {exc}"
    if not is_strings(data) or not all(data):
        return None, f"{name} does not hold a list of non-empty strings"
    return data, None


def publisher_of(program: dict):
    """The program's publisher, stripped and case-folded, or None when empty."""
    publisher = program.get("publisher")
    if isinstance(publisher, str) and publisher.strip():
        return publisher.strip().casefold()
    return None


def pair_installs(programs: list, suffixes: list) -> None:
    """Add ``per_user_pair`` to each program whose name, without one of
    ``suffixes`` (case-insensitive), equals the name of another program with the
    same publisher (non-empty, compared stripped and case-insensitive), and to
    that other program: a list of ``{id, name}`` sorted by the number in ``id``.
    A program without a publisher, or without a partner, gets no field."""
    by_name: dict = {}
    for program in programs:
        name = program.get("name")
        if isinstance(name, str):
            by_name.setdefault(name.casefold(), []).append(program)
    pairs: dict = {}
    for program in programs:
        name = program.get("name")
        if not isinstance(name, str):
            continue
        folded = name.casefold()
        for suffix in suffixes:
            suffix = suffix.casefold()
            if not folded.endswith(suffix):
                continue
            for partner in by_name.get(folded[:-len(suffix)], []):
                if partner is program or publisher_of(partner) != publisher_of(program) \
                        or publisher_of(program) is None:
                    continue
                pairs.setdefault(program["id"], {})[partner["id"]] = partner
                pairs.setdefault(partner["id"], {})[program["id"]] = program
    for program in programs:
        partners = pairs.get(program["id"])
        if partners:
            program["per_user_pair"] = [
                {"id": p["id"], "name": p.get("name")}
                for p in sorted(partners.values(), key=lambda p: int(p["id"][1:]))]


def stamp_autostart_age(col: Collector, current: dict, statuses: dict, loaded: dict,
                        now: datetime) -> None:
    """Give each autostart item of a read or ``empty`` source ``first_seen`` (UTC date)
    and ``passes_seen``, carried by key from the previous baseline (``loaded``) of this
    privilege level.

    An item in that baseline keeps its ``first_seen`` (or gets the baseline's
    ``created_at`` date when the field is missing or null, the earliest date the tool
    can show, marked ``first_seen_lower_bound`` true and carried so in later runs)
    and gets ``passes_seen`` + 1 (or 2, a lower bound). A new item gets today and 1.
    An item with ``from_baseline`` was not seen in this pass and keeps its values
    (null when its baseline copy has none). When the baseline exists but cannot be read, the age is unknown:
    both fields are null and not_checked says so. The fields are not compared
    (not in ``AUTOSTART_FIELDS``).
    """
    unreadable = loaded["status"] == "unreadable"
    previous = loaded["sources"] if loaded["status"] == "read" else {}
    baseline_day = (baseline.parse_utc(loaded["created_at"]).date().isoformat()
                    if loaded["status"] == "read" else None)
    today = now.astimezone(timezone.utc).date().isoformat()
    for source in AUTOSTART_SOURCES:
        if statuses.get(source) not in READ_STATUSES:
            continue
        before = previous.get(source) or {}
        for key, item in current.get(source, {}).items():
            if item.get("from_baseline"):
                for field in ("first_seen", "passes_seen", "first_seen_lower_bound"):
                    item.setdefault(field, None)
                continue
            if unreadable:
                item["first_seen"], item["passes_seen"] = None, None
                item["first_seen_lower_bound"] = None
                continue
            old = before.get(key)
            if old is None:
                item["first_seen"], item["passes_seen"] = today, 1
                item["first_seen_lower_bound"] = False
                continue
            first_seen, passes = old.get("first_seen"), old.get("passes_seen")
            if isinstance(first_seen, str):
                item["first_seen"] = first_seen
                item["first_seen_lower_bound"] = old.get("first_seen_lower_bound") is True
            else:
                item["first_seen"], item["first_seen_lower_bound"] = baseline_day, True
            item["passes_seen"] = (passes + 1 if isinstance(passes, int)
                                   and not isinstance(passes, bool) else 2)
    if unreadable:
        col.skip("autostart first_seen and passes_seen",
                 f"the age of the autostart entries is unknown because the previous "
                 f"baseline could not be read ({loaded['reason']}); first_seen and "
                 f"passes_seen are null in this run")


def build_autostart(current: dict, numbering=None) -> tuple[list, dict, int]:
    """Every autostart entry with an id, listed ones (``own: false``) first; the id is
    the stable number of the entry's ``key`` (``numbering``).

    Returns the entries, ``{kind: number of own entries}`` and the number of entries
    with ``own: null``.
    """
    entries = [(source, key, item) for source in AUTOSTART_SOURCES
               for key, item in sorted(current.get(source, {}).items(),
                                       key=lambda pair: (pair[0].casefold(), pair[0]))]
    listed = [e for e in entries if e[2].get("own") is False]
    rest = [e for e in entries if e[2].get("own") is not False]
    autostart = [{"id": None, "key": key, "source": source, **item}
                 for source, key, item in listed + rest]
    numbering_of(numbering).assign("s", autostart)
    per_kind = Counter(e[2].get("kind") for e in rest if e[2].get("own") is True)
    unknown = sum(1 for e in rest if e[2].get("own") is None)
    return autostart, dict(sorted(per_kind.items())), unknown


def text_order(value) -> tuple:
    """A sort key for text: case-insensitive, None last."""
    return (value is None, (value or "").casefold(), value or "")


def build_components(current: dict, numbering=None) -> tuple[list, int]:
    """Every feature and capability with an id; the listed ones (features
    ``enabled``, capabilities ``Installed``) first, each group by kind, then name.

    The id is the stable number of the item's ``key`` (``numbering``). Returns the
    items and the number of listed ones.
    """
    kinds = list(COMPONENT_KINDS.values())
    entries = [{"key": key, "kind": kind, "source": source, **item}
               for source, kind in COMPONENT_KINDS.items()
               for key, item in (current.get(source) or {}).items()]
    entries.sort(key=lambda e: (kinds.index(e["kind"]), text_order(e.get("name")), e["key"]))
    listed = [e for e in entries if e.get("state") == LISTED_STATES[e["kind"]]]
    rest = [e for e in entries if e.get("state") != LISTED_STATES[e["kind"]]]
    components = [{"id": None, **e} for e in listed + rest]
    numbering_of(numbering).assign("f", components)
    return components, len(listed)


def state_counts(items: dict, fixed=()) -> dict:
    """``{state: number}`` of a component source; a null state counts as ``unread``."""
    counts = Counter(item.get("state") or "unread" for item in items.values())
    result = {state: counts.pop(state, 0) for state in fixed}
    result.update(sorted(counts.items()))
    result.setdefault("unread", 0)
    return result


def build_drivers(current: dict, numbering=None) -> tuple[list, int]:
    """Every driver with an id; the listed ones (``own`` not true) first, each group
    with the classes of ``DRIVER_CLASSES_FIRST`` first (in that order), then by
    provider, then device name, null last. The id is the stable number of the
    driver's ``key`` (``numbering``). Returns the items and the listed count."""
    first = [name.casefold() for name in DRIVER_CLASSES_FIRST]

    def class_rank(entry: dict) -> int:
        value = entry.get("class")
        folded = value.casefold() if isinstance(value, str) else None
        return first.index(folded) if folded in first else len(first)

    entries = [{"key": key, **item} for key, item in (current.get("drivers") or {}).items()]
    entries.sort(key=lambda e: (class_rank(e), text_order(e.get("provider")),
                                text_order(e.get("device_name")), e["key"]))
    listed = [e for e in entries if e.get("own") is not True]
    rest = [e for e in entries if e.get("own") is True]
    drivers = [{"id": None, **e} for e in listed + rest]
    numbering_of(numbering).assign("d", drivers)
    return drivers, len(listed)


PUBLISHED_UNREAD_REASON = ("the published name (oem<N>.inf) of a copy of this package "
                           "was not read, so it cannot be matched to a device")


def devices_by_driver(devices) -> dict | None:
    """``{driver name, case-folded: [device]}`` of the device listing; None when it
    was not read."""
    if devices is None:
        return None
    named = {}
    for dev in devices:
        if isinstance(dev.get("driver_name"), str):
            named.setdefault(dev["driver_name"].strip().casefold(), []).append(dev)
    return named


def package_state(item: dict, named) -> tuple:
    """``(device_state, reason, devices)`` of one driver package from the devices that
    name one of its published names as their driver (``named``, see
    ``devices_by_driver``).

    ``present`` when a present device names it; else null with the reason when a
    device of a status not known names it (it may be present); else null with the reason when a
    disconnected device of another class names it (a reused ``oem<N>.inf`` number); else
    ``non_present`` with those disconnected devices (``{device_name, class, status, last_removal}``);
    else ``no_device_found``. Null with the reason for every package when the devices
    were not read, for an ``Extension`` package (a device names only its primary INF)
    and for one with no device when the published name of a copy was not read."""
    if named is None:
        return None, DEVICES_UNREAD_REASON, None
    if (item.get("class") or "").strip().casefold() == EXTENSION_CLASS:
        return None, EXTENSION_REASON, None
    names = [item.get("published_name"), *(item.get("other_published_names") or [])]
    found = [dev for name in names if isinstance(name, str)
             for dev in named.get(name.strip().casefold(), [])]
    statuses = [(dev.get("status") or "").strip().casefold() for dev in found]
    if any(status in PRESENT_STATUSES for status in statuses):
        return "present", None, None
    unknown = [dev.get("status") for dev, status in zip(found, statuses)
               if status not in NON_PRESENT_STATUSES]
    if unknown:
        shown = ", ".join(dict.fromkeys(one_line(s) if s is not None else "none given"
                                        for s in unknown))
        return None, f"{UNKNOWN_STATUS_REASON}: {shown}", None
    package_class = (item.get("class") or "").strip().casefold()
    other = [dev.get("class") for dev in found
             if package_class and (dev.get("class") or "").strip()
             and dev["class"].strip().casefold() != package_class]
    if other:
        shown = ", ".join(dict.fromkeys(one_line(c) for c in other))
        return None, f"{OTHER_CLASS_REASON}: {shown}", None
    if found:
        return "non_present", None, [{k: dev.get(k) for k in
                                      ("device_name", "class", "status", "last_removal")}
                                     for dev in found]
    if "published_name" in (item.get("unread_fields") or []):
        return None, PUBLISHED_UNREAD_REASON, None
    return "no_device_found", None, None


def build_driver_packages(current: dict, devices, numbering=None, rules=None) -> list:
    """Every third-party driver package with an id and ``device_state`` (see
    ``package_state``; a null one names its reason in ``device_state_reason``, a
    ``non_present`` one its ``devices``), its ``owner`` (the provider, null when not
    read) and its ``group`` and ``no_device_by_nature`` (see ``package_group``; null
    when the rules were not read), by provider, then original name, then version.
    The id is the stable number of the package's ``key`` (``numbering``)."""
    entries = [{"key": key, **item}
               for key, item in (current.get("driver_packages") or {}).items()]
    entries.sort(key=lambda e: (text_order(e.get("provider")),
                                text_order(e.get("original_name")),
                                text_order(e.get("version")), e["key"]))
    named = devices_by_driver(devices)
    packages = []
    for entry in entries:
        state, reason, found = package_state(entry, named)
        group, by_nature = package_group(entry, rules)
        provider = entry.get("provider")
        package = {"id": None, **entry, "device_state": state,
                   "owner": provider if isinstance(provider, str) else None,
                   "group": group, "no_device_by_nature": by_nature}
        if reason is not None:
            package["device_state_reason"] = reason
        if found is not None:
            package["devices"] = found
        packages.append(package)
    numbering_of(numbering).assign("o", packages)
    return packages


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


def no_block_reason(entry: dict, context: dict):
    """Why ``has_change_block`` gives no block, as one code per branch (the first
    that holds, in this order): ``store_app_iso``, ``store_policy``,
    ``cert_other_store``, ``cert_in_authroot``, ``cert_in_several_stores``,
    ``defender_origin``, ``defender_method``; None for an entry with a block."""
    if has_change_block(entry, context):
        return None
    kind = entry["kind"]
    if kind == "firewall_rule":
        store = entry.get("store")
        return f"store_{store}" if store in ("app_iso", "policy") else None
    if kind == "root_certificate":
        if entry.get("store") not in ("machine_root", "user_root"):
            return "cert_other_store"
        if entry.get("in_authroot") is True:
            return "cert_in_authroot"
        return "cert_in_several_stores"
    if kind == "defender_exclusion":
        if entry.get("origin") != "local":
            return "defender_origin"
        return "defender_method"
    return None


def build_additions(current: dict, defender_method=None,
                    numbering=None) -> tuple[list, int]:
    """Every item of the added-to-the-system sources with an id: the listed ones
    (``own`` not true) first, the rest after them. The listed ones are in two
    groups: those with a change block (``has_change_block``), then those without;
    within each group and within the rest by kind (``ADDITION_KINDS`` order), then
    by the kind's own order; a listed one without a block has ``no_block_reason``.
    The id is the stable number of the item's ``key`` (``numbering``). Returns the
    items and the listed count."""
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
    unblocked = []
    for entry in listed:
        reason = no_block_reason(entry, context)
        if reason is not None:
            entry["no_block_reason"] = reason
            unblocked.append(entry)
    listed = [e for e in listed if "no_block_reason" not in e] + unblocked
    rest = [e for e in entries if e["own"]]
    additions = [{"id": None, **e} for e in listed + rest]
    numbering_of(numbering).assign("x", additions)
    return additions, len(listed)


def summary_addition(entry: dict) -> dict:
    """One listed addition as it goes to the summary: a firewall rule and a root
    certificate with their main fields only (the subject cut to SUBJECT_MAX,
    ``windows_first_run``, ``app_exists`` and ``no_block_reason`` when the entry
    has them: a null in a fixed field would read as "not read"), any other kind
    with every field but ``own`` (and ``unread_fields`` when there are)."""
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
    if entry["kind"] in ("firewall_rule", "root_certificate"):
        for key in ("app_exists", "no_block_reason"):
            if key in entry:
                fields[key] = entry[key]
    if entry.get("unread_fields"):
        fields["unread_fields"] = entry["unread_fields"]
    return {**head, **fields}


def summary_program(program: dict) -> dict:
    """One listed program as it goes to the summary: without ``install_location``,
    ``source`` and ``own`` (the detail file keeps them)."""
    return {k: v for k, v in program.items()
            if k not in ("install_location", "source", "own")}


def summary_fact(fact):
    """One file fact as it goes to the summary: without ``company`` and
    ``check_error``, and without ``expanded_path`` when it equals ``path``."""
    if not isinstance(fact, dict):
        return fact
    return {k: v for k, v in fact.items()
            if k not in ("company", "check_error", "sha256", "sha256_error")
            and not (k == "expanded_path" and v == fact.get("path"))}


def summary_autostart(entry: dict) -> dict:
    """One listed autostart entry as it goes to the summary: without
    ``approved_raw`` (only for a rollback block), ``display_name`` and ``targets``
    (each resolved target is a fact's ``path``), each fact slimmed by
    ``summary_fact``. ``key`` stays: the report rules and ush-processes name an
    entry by it. The detail file keeps the full entry."""
    slim = {k: v for k, v in entry.items()
            if k not in ("approved_raw", "display_name", "targets")}
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
    read, or when ``compare_view`` took a program from the history copy (it names
    ``program`` in ``unread_fields``). A target added or removed is a change of
    ``targets`` only.
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


def compare_view(current: dict, statuses: dict, carried_facts: dict,
                 unread_keys: set = frozenset(), reference: dict | None = None) -> dict:
    """A copy of ``current`` for a comparison with a state other than the latest
    baseline (``--compare-to``): what this run did not read is unread in it.

    ``collect`` fills values it could not read from the latest baseline, which is
    no change against that baseline but would be one against an older state. In
    the copy an item with ``from_baseline`` has every compared field (and its
    ``facts``) in ``unread_fields``, so it can still be added (its key was seen in
    this run) but never changed; a ``run`` or ``startup_folder`` entry has the
    StartupApproved fields unread when ``startup_approved`` was not read; and a
    fact taken from the baseline (``carried_facts``) is left out, so that target's
    facts are not compared. An item seen in this run but not read (``unread_keys``)
    that the latest baseline lacks, so ``current`` lacks it too, is taken from
    ``reference`` with ``from_baseline``: it is still there, so it is not removed.
    When such an item is a program, every autostart entry has ``program`` unread:
    its targets were matched to the programs of this run, which lack it.
    ``current`` itself, saved and listed, is not changed.
    """
    view = copy.deepcopy(current)
    program_from_reference = False
    for source, key in sorted(unread_keys):
        items = view.get(source)
        before = (reference or {}).get(source) or {}
        if isinstance(items, dict) and key not in items and isinstance(before.get(key), dict):
            items[key] = copy.deepcopy(before[key])
            items[key]["from_baseline"] = True  # not read in this run
            program_from_reference |= source in PROGRAM_SOURCES
    approved_read = statuses.get("startup_approved") in READ_STATUSES
    for source in SOURCES:
        for key, item in (view.get(source) or {}).items():
            unread = set(item.get("unread_fields") or [])
            if item.get("from_baseline"):
                unread |= set(COMPARED_FIELDS[source])
                if source in AUTOSTART_SOURCES:
                    unread.add("facts")
            elif not approved_read and item.get("kind") in ("run", "startup_folder"):
                unread |= set(APPROVED_FIELDS)
            if program_from_reference and source in AUTOSTART_SOURCES:
                unread.add("program")
            carried = carried_facts.get((source, key))
            if carried:
                item["facts"] = [fact for fact in item.get("facts") or []
                                 if not (isinstance(fact, dict) and fact.get("path") in carried)]
            if unread:
                item["unread_fields"] = sorted(unread)
    return view


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


# --- leftovers of removed programs ---------------------------------------------
def removed_state_reason(data):
    """None when ``data`` has the shape of ``state/inventory-removed.json``, else why not."""
    if not isinstance(data, dict) or data.get("version") != REMOVED_STATE_VERSION \
            or data.get("skill") != SKILL or not isinstance(data.get("removed"), list):
        return (f"not an object with version {REMOVED_STATE_VERSION}, skill {SKILL} "
                f"and a list removed")
    for entry in data["removed"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) \
                or entry.get("source") not in PROGRAM_SOURCES \
                or not isinstance(entry.get("first_seen_gone"), str)                 or not isinstance(entry.get("seen_elevated", False), bool) \
                or not isinstance(entry.get("hkcu_absent", False), bool):
            return "an entry of removed has no key, source or first_seen_gone"
    return None


def load_removed(state_dir: Path) -> tuple[list, str | None]:
    """``(entries, reason)`` of ``state/inventory-removed.json``: no file is no entries
    and no reason; a file that cannot be read gives no entries and the reason."""
    path = Path(state_dir).absolute() / f"{REMOVED_STATE}.json"
    if not path.exists():
        return [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    reason = removed_state_reason(data)
    return ([], reason) if reason is not None else (data["removed"], None)


def removed_programs(previous: dict, programs_now: dict, state_entries: list,
                     today: str) -> tuple[list, list]:
    """``(entries, new)``: the removed programs to look for leftovers of.

    First the entries of the state file whose program is not installed now, then
    the programs of the previous baseline that are not installed now (``new``, the
    ones first seen gone ``today``). ``programs_now`` are the program sources as
    they are saved, so a source not read in this run removes nothing. A program
    whose display name (case-insensitive, exact) is installed now under any key is
    not removed: an upgrade may write a new key, often without ``InstallLocation``.
    """
    installed = {(source, key) for source in PROGRAM_SOURCES
                 for key in (programs_now.get(source) or {})}
    names = {name.casefold() for source in PROGRAM_SOURCES
             for item in (programs_now.get(source) or {}).values() if isinstance(item, dict)
             for name in [text(item.get("name"))] if name}

    def still_there(name):
        return isinstance(name, str) and name.strip() != "" and name.casefold() in names

    entries, new, seen = [], [], set()
    for entry in state_entries:
        ident = (entry["source"], entry["key"])
        if ident not in installed and ident not in seen and not still_there(entry.get("name")):
            seen.add(ident)
            kept = {field: entry.get(field) for field in REMOVED_FIELDS}
            kept["seen_elevated"] = entry.get("seen_elevated") is True
            kept["hkcu_absent"] = entry.get("hkcu_absent") is True
            entries.append(kept)
    for source in PROGRAM_SOURCES:
        for key, item in sorted((previous.get(source) or {}).items()):
            ident = (source, key)
            if ident in installed or ident in seen or not isinstance(item, dict)                     or still_there(text(item.get("name"))):
                continue
            seen.add(ident)
            entry = {"key": key, "source": source, "name": text(item.get("name")),
                     "publisher": text(item.get("publisher")),
                     "install_location": text(item.get("install_location")),
                     "first_seen_gone": today, "seen_elevated": False,
                     "hkcu_absent": False}
            entries.append(entry)
            new.append(entry)
    return entries, new


def usable_folder(location, skipped: set, system_root=None, broad=False):
    """``location`` as a folder to match (no quotes, no trailing backslash), or None
    when it cannot be one: empty, not a full local path, a drive root, one of the
    ``skipped`` (case-folded) Windows folders, or holding a ``%``.

    Without ``broad`` also None for a folder many programs share (``BROAD_FOLDER``:
    ``ProgramData``, ``Program Files``, a profile, its ``AppData`` folders) and for
    the Windows folder and anything under it (``system_root`` or ``C:\\Windows``)."""
    location = clean_path(location)
    location = location.rstrip("\\/") if location else None
    if not location or "%" in location or not FULL_PATH.match(location + "\\") \
            or DRIVE_ROOT.match(location) or location.casefold() in skipped:
        return None
    if not broad and (BROAD_FOLDER.match(location) or WINDOWS_FOLDER.match(location)
                      or under(location, system_root)):
        return None
    return location


def under(path, folder) -> bool:
    """Whether ``path`` is ``folder`` or lies under it, case-insensitively."""
    if path is None or folder is None:
        return False
    return (path.rstrip("\\/").casefold() + "\\").startswith(
        folder.rstrip("\\/").casefold() + "\\")


def folder_part(path: str, row) -> dict:
    """The folder part of a leftover from an ``install_folders`` row (None: no row).

    A row that is not clearly read (an unknown status, ``read`` without a boolean
    ``exists``, or a folder that is there without its counts) is ``unreadable``; an
    unreadable folder never has counts, so it never passes for an empty one.
    """
    part = {"kind": "folder", "path": path, "exists": None, "status": "unreadable",
            "reason": None, "files": None, "bytes": None, "newest_write": None,
            "extensions": None}
    if not isinstance(row, dict):
        part["reason"] = "the install_folders job gave no row for this folder"
        return part
    exists = row.get("exists") if isinstance(row.get("exists"), bool) else None
    part["exists"] = exists
    counts = {name: row.get(name) for name in ("files", "bytes")}
    counted = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                  for v in counts.values())
    if row.get("status") == "read" and exists is False:
        part["status"] = "read"
    elif row.get("status") == "read" and exists is True and counted:
        extensions = []
        for entry in as_list(row.get("extensions")):
            if isinstance(entry, dict) and isinstance(entry.get("extension"), str) \
                    and isinstance(entry.get("files"), int):
                extensions.append({"extension": entry["extension"], "files": entry["files"]})
        part.update(status="read", newest_write=text(row.get("newest_write")),
                    extensions=extensions[:10], **counts)
    elif row.get("status") == "read":
        part["reason"] = "the install_folders row says read but not whether the folder " \
                         "is there, or not its file count and size"
    else:
        part["reason"] = text(row.get("reason")) or "the install_folders job gave no reason"
    return part


def collect_install_folders(col: Collector, folders: list) -> dict:
    """Run ``install_folders`` for ``folders``: ``{folder, case-folded: folder part}``.

    A job that failed names itself in not_checked, and each folder is then
    ``unreadable`` with its reason; a folder without a row likewise.
    """
    input_path = col.work / f"inventory-{col.stamp}.install_folders.input.json"
    try:
        input_path.write_text(json.dumps({"folders": folders}, ensure_ascii=True),
                              encoding="utf-8")
    except OSError as exc:
        result = {"status": "unreadable", "rows": [],
                  "reason": f"the folder list could not be written: "
                            f"{type(exc).__name__}: {exc}"}
    else:
        body = INSTALL_FOLDERS_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
        result = col.job("install_folders", body)
    if result["status"] == "unreadable":
        col.skip("install_folders", result["reason"])
    rows = {}
    for row in result["rows"]:
        path = text(row.get("path"))
        if path is not None:
            rows.setdefault(path.rstrip("\\/").casefold(), row)
    parts = {}
    for folder in folders:
        row = rows.get(folder.casefold())
        part = folder_part(folder, row)
        if row is None and result["status"] == "unreadable":
            part["reason"] = result["reason"]
        parts[folder.casefold()] = part
    return parts


# Vendor folders: a folder name that is a GUID (Windows Installer caches a product or
# a patch by its code), the leaf of the root where such names are skipped, and the
# keys of component_counts.
GUID_NAME = re.compile(
    r"^\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$", re.IGNORECASE)
INSTALLER_LEAF = "installer"
VENDOR_COUNTS = ("vendor_folders_read", "vendor_folders_matched", "vendor_folders_unmatched",
                 "vendor_folders_unknown", "reparse_points", "installer_guid_folders")
VENDOR_SUMMARY = ("id", "key", "path", "root", "matched", "has_entries", "last_write")


def collect_vendor_folders(col: Collector, roots: list) -> list:
    """Run ``vendor_folders`` for ``roots``: ``[{root, expanded, status, reason,
    folders}]`` in the order of ``roots``, ``folders`` the job's child rows or None.

    The job is recorded as the source ``vendor_folders``. A job that failed (or whose
    input could not be written) makes every root ``unreadable`` with the job's reason;
    the source names it in not_checked. Otherwise a root without a row, or whose row
    is not clearly read, is ``unreadable`` with a reason and named in not_checked.
    """
    input_path = col.work / f"inventory-{col.stamp}.vendor_folders.input.json"
    try:
        input_path.write_text(json.dumps({"roots": roots}, ensure_ascii=True),
                              encoding="utf-8")
    except OSError as exc:
        result = {"status": "unreadable", "rows": [],
                  "reason": f"the root list could not be written: "
                            f"{type(exc).__name__}: {exc}"}
    else:
        body = VENDOR_FOLDERS_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
        result = col.job("vendor_folders", body)
    if result["status"] != "read":
        # Every root gives a row, so a job without rows did not list any root.
        reason = result["reason"] or "the vendor_folders job gave no row for any root"
        col.record("vendor_folders", "unreadable", reason)
        return [{"root": root, "expanded": None, "status": "unreadable", "reason": reason,
                 "folders": None} for root in roots]
    by_root = {}
    for row in result["rows"]:
        if isinstance(row, dict) and text(row.get("root")) is not None:
            by_root.setdefault(row["root"], row)
    rows = []
    for root in roots:
        row = by_root.get(root)
        entry = {"root": root, "expanded": None, "status": "unreadable", "reason": None,
                 "folders": None}
        if row is None:
            entry["reason"] = "the vendor_folders job gave no row for this root"
        else:
            entry["expanded"] = text(row.get("expanded"))
            folders = row.get("folders")
            if row.get("status") == "read" and entry["expanded"] is not None \
                    and isinstance(folders, (list, dict)):
                entry.update(status="read", folders=as_list(folders))
            elif row.get("status") == "read":
                entry["reason"] = ("the vendor_folders row says read but gives no expanded "
                                   "root or no folder list")
            else:
                entry["reason"] = (text(row.get("reason"))
                                   or "the vendor_folders job gave no reason")
        if entry["status"] != "read":
            col.skip(f"vendor_folders {root}", entry["reason"])
        rows.append(entry)
    if any(entry["status"] == "read" for entry in rows):
        col.record("vendor_folders", "read")
    else:
        col.record("vendor_folders", "unreadable", "no root could be listed")
    return rows


def vendor_children(col: Collector, config: dict, rows: list) -> tuple[list, int, int]:
    """``(folders, reparse points, installer GUID folders)``: the child folders of the
    read roots after the skips, each ``{id, key, name, path, root, has_entries,
    reason, last_write, matched, matched_by}``, by root and then by name.

    Skipped: a reparse point, a GUID-named folder of the ``Installer`` root, and a
    name of ``windows_names``. A row that is not a direct child of its root, or does
    not say whether it is a reparse point, is not judged and is named in not_checked.
    A folder whose entries were not listed has ``has_entries`` None and a reason.
    """
    folders, reparse, guid, malformed = [], 0, 0, 0
    for place, row in enumerate(rows):
        if row["status"] != "read":
            continue
        expanded = row["expanded"].rstrip("\\/")
        installer = expanded.rsplit("\\", 1)[-1].casefold() == INSTALLER_LEAF
        for child in row["folders"]:
            child = child if isinstance(child, dict) else {}
            name, path = text(child.get("name")), text(child.get("path"))
            if name is None or path is None or not isinstance(child.get("reparse_point"), bool) \
                    or path.rstrip("\\/").rsplit("\\", 1)[0].casefold() != expanded.casefold():
                malformed += 1
                continue
            if child["reparse_point"]:
                reparse += 1
                continue
            if installer and GUID_NAME.match(name.strip()):
                guid += 1
                continue
            if name.strip().casefold() in config["windows_names"]:
                continue
            has_entries = child.get("has_entries")
            has_entries = has_entries if isinstance(has_entries, bool) else None
            reason = text(child.get("reason"))
            if has_entries is None and reason is None:
                reason = "the vendor_folders job did not say whether the folder holds entries"
            folders.append({"id": None, "key": f"vendor_folder:{path.casefold()}",
                            "name": name, "path": path, "root": row["root"],
                            "has_entries": has_entries, "reason": reason,
                            "last_write": text(child.get("last_write")),
                            "matched": None, "matched_by": [], "_place": place})
    if malformed:
        col.skip("vendor_folders rows",
                 f"{malformed} child folder row(s) are not a direct child of their root or "
                 f"do not say whether they are a reparse point, so they are not judged")
    folders.sort(key=lambda f: (f["_place"], f["name"].casefold(), f["path"]))
    for folder in folders:
        del folder["_place"]
    return folders, reparse, guid


def find_vendor_folders(col: Collector, config, rows: list, programs: dict, autostart: list,
                        dirs: dict, statuses: dict, previous: dict,
                        numbering=None) -> tuple[list | None, dict, dict]:
    """``(listed, counts, detail section)`` of the top-level vendor folders.

    A folder is matched only by an exact rule: an installed program's
    ``install_location`` (one ``usable_folder`` accepts, so never a root such as
    ``C:\\ProgramData`` nor anything under the Windows folder) is the folder or lies
    under it; an autostart, service or task target lies under it; or the data file's
    ``vendors`` entry for its name lists a publisher an installed program has
    (case-folded, exact). Every other folder is unmatched; ``listed`` holds every
    folder no rule matches with a ``v`` id (key ``vendor_folder:<case-folded path>``)
    and its ``matched`` (false, or null when not judged).

    ``listed`` and every count are None when the data file could not be used or no
    root could be listed; ``listed`` is None also when a program source was not read
    and the baseline has none of its programs. Whenever ``listed`` is None the
    section's ``folders`` is None too; its ``roots`` is None only when the data file
    could not be used (the roots are then unknown). When an autostart source, a
    program source (whose baseline programs stand in), a target path or a program
    registry key was not read, a folder no rule matches is listed with ``matched``
    None and ``not_judged`` (the shared cause text, also in not_checked), counted in
    ``vendor_folders_unknown``: no folder is unmatched because something was not read.
    """
    counts = dict.fromkeys(VENDOR_COUNTS)
    section = {"roots": None if config is None else
               [{k: row[k] for k in ("root", "expanded", "status", "reason")}
                for row in rows], "folders": None}
    if config is None or not any(row["status"] == "read" for row in rows):
        return None, counts, section
    folders, reparse, guid = vendor_children(col, config, rows)
    counts.update(vendor_folders_read=len(folders), reparse_points=reparse,
                  installer_guid_folders=guid)

    missing = [s for s in PROGRAM_SOURCES
               if statuses.get(s) not in READ_STATUSES and not previous.get(s)]
    if missing:
        col.skip("vendor_folders",
                 f"no folder is called unmatched: the program source(s) "
                 f"{', '.join(missing)} were not read and the baseline holds none of "
                 f"their programs")
        return None, counts, section
    section["folders"] = folders

    dir_paths = {name: value.get("path") for name, value in (dirs or {}).items()
                 if isinstance(value, dict)}
    skipped = {d.rstrip("\\/").casefold() for d in dir_paths.values() if text(d)}
    system_root = text(dir_paths.get("SystemRoot"))
    locations, publishers = [], set()
    for source in PROGRAM_SOURCES:
        for item in (programs.get(source) or {}).values():
            if not isinstance(item, dict):
                continue
            location = usable_folder(item.get("install_location"), skipped, system_root)
            if location:
                locations.append(location)
            publisher = publisher_of(item)
            if publisher:
                publishers.add(publisher)
    targets, unknown_targets = [], 0
    for entry in autostart:
        unread = "targets" in (entry.get("unread_fields") or [])
        for path, raw, _ in entry_targets(entry):
            if path is not None:
                targets.append(path)
            elif raw is not None:
                unread = True
        unknown_targets += 1 if unread else 0

    causes = [f"the source {s}" for s in AUTOSTART_SOURCES
              if statuses.get(s) not in READ_STATUSES]
    causes += [f"the source {s} (only its baseline programs were matched)"
               for s in PROGRAM_SOURCES if statuses.get(s) not in READ_STATUSES]
    if unknown_targets:
        causes.append(f"the target path of {unknown_targets} autostart entr"
                      f"{'y' if unknown_targets == 1 else 'ies'}")
    unread_keys = {}
    for source, key in col.unread_keys:
        if source in PROGRAM_SOURCES and key not in (programs.get(source) or {}):
            unread_keys[source] = unread_keys.get(source, 0) + 1
    for source in PROGRAM_SOURCES:
        if unread_keys.get(source):
            causes.append(f"{unread_keys[source]} program key(s) of {source} that are in "
                          f"no baseline")

    for folder in folders:
        by = []
        if any(under(location, folder["path"]) for location in locations):
            by.append("install_location")
        if any(under(target, folder["path"]) for target in targets):
            by.append("target")
        if publishers & config["vendors"].get(folder["name"].strip().casefold(), set()):
            by.append("vendor")
        folder["matched_by"] = by
        folder["matched"] = True if by else (None if causes else False)
    shown = [folder for folder in folders if folder["matched"] is not True]
    numbering_of(numbering).assign("v", shown)
    unmatched = sum(1 for folder in shown if folder["matched"] is False)
    unknown = len(shown) - unmatched
    not_judged = "; ".join(causes)
    if unknown:
        col.skip("vendor_folders",
                 f"{unknown} top-level folder(s) that no rule matches are listed with "
                 f"matched null (not judged), because a folder could belong to what was "
                 f"not read: {not_judged}")
    counts.update(vendor_folders_matched=sum(1 for f in folders if f["matched"] is True),
                  vendor_folders_unmatched=unmatched, vendor_folders_unknown=unknown)
    listed = []
    for folder in shown:
        item = {k: folder[k] for k in VENDOR_SUMMARY}
        if folder["matched"] is None:
            item["not_judged"] = not_judged
        if folder["has_entries"] is None:
            item["unread_fields"] = ["has_entries"]
            item["has_entries_reason"] = folder["reason"]
        listed.append(item)
    return listed, counts, section


def program_keys(entry: dict) -> list | None:
    """The registry keys a removed program may have left, from its ``publisher`` and
    display ``name`` written exactly (never a prefix or a similar name):
    ``HKLM\\SOFTWARE\\<publisher>\\<name>``, the ``WOW6432Node`` variant and
    ``HKCU\\SOFTWARE\\<publisher>\\<name>``. None for a program without both, or with
    a backslash or a control character in one (it would name another key)."""
    publisher, name = text(entry.get("publisher")), text(entry.get("name"))
    if publisher is None or name is None:
        return []
    publisher, name = publisher.strip(), name.strip()
    if any("\\" in value or CONTROL_CHARS.search(value) for value in (publisher, name)):
        return None
    return [f"{root}\\{publisher}\\{name}" for root in LEFTOVER_KEY_ROOTS]


# A trailing bitness suffix of a display name: "Foo (64-bit)" uses the keys of "Foo".
BITNESS_SUFFIX = re.compile(r"\s*\((?:64-bit|32-bit|x64|x86)\)\s*$", re.IGNORECASE)


def keys_in_use(programs_now: dict) -> tuple[set, set]:
    """``(keys, names)`` of the programs installed now: their candidate keys
    (``program_keys``, case-folded), and ``(publisher, name without a bitness
    suffix)``, case-folded. A removed program's key in either is not a leftover."""
    keys, names = set(), set()
    for source in PROGRAM_SOURCES:
        for item in (programs_now.get(source) or {}).values():
            if not isinstance(item, dict):
                continue
            keys.update(key.casefold() for key in program_keys(item) or [])
            publisher, name = text(item.get("publisher")), text(item.get("name"))
            if publisher is not None and name is not None:
                names.add((publisher.strip().casefold(),
                           BITNESS_SUFFIX.sub("", name).strip().casefold()))
    return keys, names


def key_part(path: str, row) -> dict | None:
    """The registry part of a leftover from a ``leftover_keys`` row: None for a key
    that is not there; ``unreadable`` with the reason for a row that is not clearly
    read, so a key that could not be read never passes for one that is not there."""
    part = {"kind": "registry_key", "path": path, "exists": None, "status": "unreadable",
            "reason": None, "values": None, "subkeys": None}
    exists = row.get("exists") if isinstance(row.get("exists"), bool) else None
    counts = {name: row.get(name) for name in ("values", "subkeys")}
    counted = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                  for v in counts.values())
    if row.get("status") == "read" and exists is False:
        return None
    if row.get("status") == "read" and exists is True and counted:
        part.update(exists=True, status="read", **counts)
    elif row.get("status") == "read":
        part["reason"] = ("the leftover_keys row says read but not whether the key is "
                          "there, or not its value and subkey count")
    else:
        part["reason"] = text(row.get("reason")) or "the leftover_keys job gave no reason"
    return part


def collect_leftover_keys(col: Collector, keys: list) -> tuple[dict, set]:
    """Run ``leftover_keys`` for ``keys``: ``({key, case-folded: part or None}, unread)``.

    A key that is not there maps to None. ``unread`` holds the case-folded keys the
    job did not answer (it failed, or gave no row for them); they are named in
    not_checked and are neither a part nor "not there". Rows for keys not asked
    about are ignored.
    """
    input_path = col.work / f"inventory-{col.stamp}.leftover_keys.input.json"
    try:
        input_path.write_text(json.dumps({"keys": keys}, ensure_ascii=True),
                              encoding="utf-8")
    except OSError as exc:
        result = {"status": "unreadable", "rows": [],
                  "reason": f"the key list could not be written: "
                            f"{type(exc).__name__}: {exc}"}
    else:
        body = LEFTOVER_KEYS_BODY.replace("__INPUT__", psrun.ps_quote(input_path))
        result = col.job("leftover_keys", body)
    if result["status"] == "unreadable":
        col.skip("leftover_keys", f"the registry keys of removed programs were not read: "
                                  f"{result['reason']}")
        return {}, {key.casefold() for key in keys}
    rows = {}
    for row in result["rows"]:
        path = text(row.get("path")) if isinstance(row, dict) else None
        if path is not None:
            rows.setdefault(path.rstrip("\\").casefold(), row)
    parts, unread = {}, set()
    for key in keys:
        row = rows.get(key.casefold())
        if row is None:
            unread.add(key.casefold())
            continue
        parts[key.casefold()] = key_part(key, row)
    if unread:
        names = ", ".join(key for key in keys if key.casefold() in unread)
        col.skip("leftover_keys", f"the job gave no row for {len(unread)} registry keys, "
                                  f"so it is not known whether they are there: {names}")
    return parts, unread


def entry_targets(entry: dict) -> list:
    """``[(path, raw, exists)]`` of an autostart entry: the expanded path of each
    target (the raw one when it holds no ``%`` and was not expanded), its raw text
    and whether the file is there (None when not known)."""
    found = []
    facts = [f for f in entry.get("facts") or [] if isinstance(f, dict)]
    rows = facts or [{"path": target} for target in entry.get("targets") or []]
    for fact in rows:
        raw = text(fact.get("path"))
        path = text(fact.get("expanded_path"))
        if path is None and raw is not None and "%" not in raw:
            path = raw
        exists = fact.get("exists") if isinstance(fact.get("exists"), bool) else None
        found.append((path, raw, exists))
    return found


def rule_targets(item: dict, expanded: dict) -> list:
    """``[(path, raw, exists)]`` of a firewall rule with a program file, else ``[]``."""
    app = item.get("app")
    if not isinstance(app, str) or not app.strip() \
            or app.strip().casefold() == FIREWALL_SYSTEM_APP:
        return []
    path = expanded.get(app.casefold()) or (app if "%" not in app else None)
    exists = item.get("app_exists") if isinstance(item.get("app_exists"), bool) else None
    return [(path, app, exists)]


def leftover_part(item: dict, kind, target: tuple) -> dict:
    path, _, exists = target
    part = {"kind": kind, "key": item.get("key"), "id": item.get("id"),
            "name": item.get("name"), "path": path, "exists": exists}
    if exists is False:
        part["reason"] = MISSING_REASON
    return part


def find_leftovers(col: Collector, removed: list, programs_now: dict, dirs: dict,
                   autostart: list, additions: list, numbering=None, statuses=None,
                   admin=False) -> tuple[list, list]:
    """``(leftovers, kept)``: one leftover per removed program with something left,
    one per folder of missing targets that no removed program explains, and the
    removed programs (``removed`` entries) to keep in the state file.

    Only explicit facts count, never a similar name:

    - an autostart entry or firewall rule whose (expanded) target lies under the
      removed program's ``install_location`` is a part of that program; with
      ``exists`` false its ``reason`` is ``MISSING_REASON``;
    - the ``install_location`` itself, read by ``install_folders``, when it is still
      there or could not be read;
    - an entry whose every target is missing (``exists`` false) and lies under no
      removed program is a part of the leftover named by the folder of its first
      target.

    Never a leftover: an item that is Windows' own, anything with a target under
    the ``install_location`` of a program installed now, the folder of a removed
    program that is, contains or lies under such a location (nor anything under
    it), and a missing target under ``%SystemRoot%``. When ``%SystemRoot%`` is not
    known, missing targets are not grouped and not_checked says so. A removed
    program without a usable ``install_location`` (see ``usable_folder``: also a
    folder many programs share, or one under the Windows folder) is looked at no
    further. Removed programs with one ``install_location`` are one leftover
    (``program`` the first by name, ``other_programs`` the others).

    A removed program with no leftover is kept (``kept``, with a not_checked item)
    unless this run read everything that could hold one: its folder read as gone,
    the ``LEFTOVER_SOURCES`` read (``statuses``), no entry (not Windows' own) with a
    target path that could not be expanded, and, for a program an elevated run saw
    (``seen_elevated``), this run elevated (``admin``).
    """
    col.skip("leftovers before the first baseline",
             "a program removed before the first baseline is in no baseline, so its "
             "leftovers are not looked for")
    dir_paths = {name: value.get("path") for name, value in (dirs or {}).items()
                 if isinstance(value, dict)}
    skipped = {d.rstrip("\\/").casefold() for d in dir_paths.values() if text(d)}
    current_match = program_matcher(programs_now, dir_paths)
    installed = [folder for source in PROGRAM_SOURCES
                 for item in (programs_now.get(source) or {}).values()
                 if isinstance(item, dict)
                 for folder in [usable_folder(item.get("install_location"), skipped,
                                              broad=True)]
                 if folder]
    system_root = text(dir_paths.get("SystemRoot"))

    # Removed programs that share one install_location (e.g. the 64-bit and 32-bit
    # entries of one product) are one leftover: {folder, case-folded: (entries, folder)}.
    # The others with a publisher and a name are looked at only for their registry
    # keys: {publisher\name, case-folded: [entries]}.
    usable, shared, keyed, entry_keys = {}, [], {}, {}
    used_keys, used_names = keys_in_use(programs_now)
    for entry in sorted(removed, key=lambda e: (str(e.get("name")).casefold(),
                                                str(e.get("source")), str(e.get("key")))):
        keys = program_keys(entry)
        keys_skipped = keys is None
        if keys_skipped:
            col.skip(f"leftover_keys {entry.get('name')}",
                     "the publisher or the name holds a backslash or a control character, "
                     "so its registry keys were not looked up")
            keys = []
        # A key a program installed now uses (the same key, or the same publisher and
        # name but for a bitness suffix) is that program's, not a leftover.
        if (str(entry.get("publisher")).strip().casefold(),
                str(entry.get("name")).strip().casefold()) in used_names:
            keys = []
        keys = [key for key in keys if key.casefold() not in used_keys]
        entry_keys[id(entry)] = keys
        folder = usable_folder(entry.get("install_location"), skipped, system_root)
        in_installed = folder is not None and any(under(other, folder) or under(folder, other)
                                                  for other in installed)
        if in_installed:
            shared.append(folder)
            folder = None
        if folder is None:
            if keys:
                # publisher\name, case-folded: the part after "HKLM\SOFTWARE\".
                keyed.setdefault(keys[0].casefold().split("\\", 2)[2], []).append(entry)
            elif not in_installed and not keys_skipped:
                col.skip(f"leftovers {entry.get('name')}",
                         "no usable install_location and no registry key of its own to "
                         "look up, so its leftovers were not looked for")
            continue
        usable.setdefault(folder.casefold(), ([], folder))[0].append(entry)
    removed_match = program_matcher(
        {PROGRAM_SOURCES[0]: {group: {"install_location": folder}
                              for group, (_, folder) in usable.items()}}, dir_paths)

    by_program = {key: [] for key in usable}
    by_folder, folder_names = {}, {}
    no_root = 0
    # A fact carried over from the previous baseline (or an entry of a source not
    # read this run) may be outdated: its exists counts as not known, so it never
    # makes a missing target (as in missing_target_line).
    items = [(entry, entry.get("kind"),
              [(path, raw, None) for path, raw, _ in entry_targets(entry)]
              if entry.get("facts_from_baseline") is True or entry.get("from_baseline")
              else entry_targets(entry))
             for entry in autostart]
    items += [(item, "firewall_rule", rule_targets(item, col.firewall_expanded))
              for item in additions if item.get("kind") == "firewall_rule"]
    # A target whose path could not be expanded may lie under a removed program's
    # folder: such entries count as not read for the keep/drop rule below. A target
    # with no path at all (a COM handler, an empty command) names no folder.
    unexpanded = {}
    for item, kind, targets in items:
        if item.get("own") is not True and any(t[0] is None and t[1] is not None
                                               and "%" in t[1] for t in targets):
            unexpanded[str(kind)] = unexpanded.get(str(kind), 0) + 1
        targets = [t for t in targets if t[0] is not None]
        if item.get("own") is True or not targets:
            continue
        if any(current_match(t[0]) is not None or any(under(t[0], f) for f in shared)
               for t in targets):
            continue
        owner = next(((removed_match(t[0]), t) for t in targets
                      if removed_match(t[0]) is not None), None)
        if owner is not None:
            by_program[owner[0]].append(leftover_part(item, kind, owner[1]))
            continue
        if any(t[2] is not False for t in targets):
            continue
        if system_root is None:
            no_root += 1
            continue
        if any(under(t[0], system_root) or (t[1] or "").casefold().startswith(SYSTEM_VARS)
               for t in targets):
            continue
        folder = ntpath.dirname(targets[0][0].rstrip("\\/"))
        if not FULL_PATH.match(folder.rstrip("\\") + "\\"):
            continue
        group = folder.rstrip("\\/").casefold()
        folder_names.setdefault(group, folder)
        by_folder.setdefault(group, []).append(leftover_part(item, kind, targets[0]))
    if no_root:
        col.skip("leftovers of missing targets",
                 f"{no_root} entries point to missing files, but the Windows folder "
                 f"(%SystemRoot%) is not known in this run, so they were not grouped")

    folders = [folder for _, folder in usable.values()]
    folder_parts = collect_install_folders(col, folders) if folders else {}
    all_keys, asked = [], set()
    for entry in removed:
        for key in entry_keys.get(id(entry)) or []:
            if key.casefold() not in asked:
                asked.add(key.casefold())
                all_keys.append(key)
    key_parts, keys_unread = collect_leftover_keys(col, all_keys) if all_keys else ({}, set())

    def registry_parts(entries):
        """The key parts of ``entries`` (one per key) and the causes for which their
        keys do not count as fully read (for the keep/drop rule)."""
        parts, seen, causes = [], set(), []
        for entry in entries:
            for key in entry_keys.get(id(entry)) or []:
                folded = key.casefold()
                absent = folded not in keys_unread and key_parts.get(folded) is None
                if not absent and not admin and folded.startswith("hkcu\\"):
                    # Read as there, or not read: an earlier absence no longer holds.
                    entry["hkcu_absent"] = False
                if absent and folded.startswith("hkcu\\"):
                    # The elevated account's HKCU may not be the one that used the
                    # program: its absence there counts only once a non-elevated run
                    # read it (``hkcu_absent`` in the state file).
                    if not admin:
                        entry["hkcu_absent"] = True
                    elif entry.get("hkcu_absent") is not True \
                            and HKCU_ELEVATED not in causes:
                        causes.append(HKCU_ELEVATED)
                if folded in seen:
                    continue
                seen.add(folded)
                if folded in keys_unread:
                    if KEYS_NOT_READ not in causes:
                        causes.append(KEYS_NOT_READ)
                    continue
                part = key_parts.get(folded)
                if part is not None:
                    parts.append(part)
                    if part["status"] == "unreadable":
                        col.skip(f"leftover_keys {key}", part["reason"])
        return parts, causes

    def keep_unread(entries, causes):
        kept.extend(entries)
        names = ", ".join(sorted({str(e.get("name")) for e in entries}))
        col.skip(f"leftovers {names}",
                 f"kept in state/{REMOVED_STATE}.json, no leftover found but not "
                 f"everything was read: {'; '.join(causes)}")

    def add_leftover(key, entries, parts):
        programs = [{field: entry.get(field) for field in REMOVED_FIELDS}
                    for entry in entries]
        leftovers.append({"id": None, "key": key,
                          "program": programs[0], "other_programs": programs[1:],
                          "first_seen_gone": min(str(e.get("first_seen_gone"))
                                                 for e in entries),
                          "folder": None, "parts": parts})

    unread = [name for name in LEFTOVER_SOURCES
              if (statuses or {}).get(name) not in READ_STATUSES]
    leftovers, kept = [], []
    for group, (entries, folder) in sorted(
            usable.items(), key=lambda pair: (str(pair[1][0][0].get("name")).casefold(),
                                              pair[0])):
        parts = by_program[group]
        part = folder_parts.get(group)
        if part is not None and (part["exists"] is True or part["status"] == "unreadable"):
            parts.append(part)
            if part["status"] == "unreadable":
                col.skip(f"install_folders {folder}", part["reason"])
        keys_found, key_causes = registry_parts(entries)
        parts.extend(keys_found)
        if not parts:
            # Dropped only when this run read everything that could hold a leftover:
            # the folder is gone (read), the item sources and registry keys were read,
            # and a program an elevated run saw is looked at with elevation again.
            causes = []
            if part is None or part["status"] != "read" or part["exists"] is not False:
                causes.append("its folder was not read as gone")
            if unread:
                causes.append(f"the sources {', '.join(unread)} were not read")
            causes.extend(key_causes)
            if unexpanded:
                counts = ", ".join(f"{count} {kind}" for kind, count
                                   in sorted(unexpanded.items()))
                causes.append(f"entries with a target path that could not be expanded "
                              f"({counts}) may point into its folder")
            if not admin and any(e.get("seen_elevated") is True for e in entries):
                causes.append("an elevated run saw it, this run is not elevated (tasks "
                              "and services of other accounts may be hidden)")
            if causes:
                keep_unread(entries, causes)
            continue
        for entry in entries:
            entry["seen_elevated"] = entry.get("seen_elevated") is True or bool(admin)
        kept.extend(entries)
        add_leftover(f"leftover:location:{group}", entries, parts)
    # Removed programs without a usable install_location: only their registry keys.
    for group, entries in sorted(keyed.items(),
                                 key=lambda pair: (str(pair[1][0].get("name")).casefold(),
                                                   pair[0])):
        parts, key_causes = registry_parts(entries)
        if not parts:
            if key_causes:
                keep_unread(entries, key_causes)
            continue
        kept.extend(entries)
        add_leftover(f"leftover:keys:{group}", entries, parts)
    for group in sorted(by_folder):
        leftovers.append({"id": None, "key": f"leftover:folder:{group}", "program": None,
                          "other_programs": [], "first_seen_gone": None,
                          "folder": folder_names[group], "parts": by_folder[group]})
    numbering_of(numbering).assign("l", leftovers)
    return leftovers, kept


def save_removed(state_dir: Path, kept: list, had_file: bool):
    """Write the removed programs to keep (see ``find_leftovers``) to the state file; None,
    or the reason it was not saved. Nothing is written when there is no file and
    nothing to keep."""
    if not kept and not had_file:
        return None
    data = {"version": REMOVED_STATE_VERSION, "skill": SKILL,
            "removed": [{**{field: entry.get(field) for field in REMOVED_FIELDS},
                         "seen_elevated": entry.get("seen_elevated") is True,
                         "hkcu_absent": entry.get("hkcu_absent") is True}
                        for entry in kept]}
    return baseline.save_json(state_dir, REMOVED_STATE, data, removed_state_reason)


# --- summary and detail ------------------------------------------------------
def load_collapsed(path: Path):
    """The collapse rules as ``(list, None)``, or ``(None, reason)``.

    The file holds a list of ``{source, collapsed, prefix}`` objects of non-empty
    strings: a change of ``source`` whose name starts with ``prefix`` (case-insensitive)
    is collapsed into an entry labelled ``collapsed``. An empty prefix would collapse
    every change of the source, so it makes the file unusable.
    """
    name = Path(path).name
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{name} could not be read: {type(exc).__name__}: {exc}"
    keys = ("source", "collapsed", "prefix")
    if not isinstance(data, list) or not all(
            isinstance(rule, dict) and all(isinstance(rule.get(key), str) and rule[key]
                                           for key in keys)
            for rule in data):
        return None, f"{name} does not hold a list of {{source, collapsed, prefix}} strings"
    return data, None


def collapse_changes(changes: list, rules: list) -> list:
    """The listed changes with those named by a collapse rule collapsed: one entry
    ``{collapsed, source, change, count}`` per rule and change type, without an id,
    ahead of the listed changes, so the budget cuts plain changes first. The detail
    file keeps every change with its id."""
    out, lines = [], {}
    for entry in changes:
        name = entry.get("name")
        rule = next((rule for rule in rules if entry.get("source") == rule["source"]
                     and isinstance(name, str)
                     and name.lower().startswith(rule["prefix"].lower())), None)
        if rule is None:
            out.append(entry)
            continue
        key = (rule["collapsed"], rule["source"], entry["change"])
        line = lines.get(key)
        if line is None:
            line = lines[key] = {"collapsed": rule["collapsed"], "source": rule["source"],
                                 "change": entry["change"], "count": 0}
        line["count"] += 1
    return list(lines.values()) + out


def entry_count(entry: dict) -> int:
    """The changes an entry of the summary ``changes`` stands for: a collapsed entry
    its ``count``, any other item one."""
    return entry["count"] if "collapsed" in entry else 1


def list_counts(name: str, items: list) -> dict:
    """The per-type counts of a whole ``autostart`` or ``changes`` list: ``{kind: n}``,
    or ``{source: {added, removed, changed}}`` with a collapsed entry counted by its
    ``count``."""
    if name == "autostart":
        return dict(sorted(Counter(str(item.get("kind")) for item in items).items()))
    counts = {}
    for entry in items:
        by_change = counts.setdefault(entry.get("source"), dict.fromkeys(CHANGE_ORDER, 0))
        by_change[entry.get("change")] += entry_count(entry)
    return counts


def fit_budget(summary: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    The lists of ``CUT_LISTS`` are cut from their end, in stages, each stage only
    when the one before could not make the summary fit. First the package changes
    (``PACKAGE_SOURCES``, at the end of ``changes``), then the minimums:
    ``programs`` (programs without an install date, then the oldest installs) down
    to ``PROGRAMS_MIN``, ``vendor_folders`` down to ``VENDOR_FOLDERS_MIN``,
    ``driver_packages`` down to ``DRIVER_PACKAGES_MIN``,
    ``drivers`` down to ``DRIVERS_MIN``, ``components`` down to
    ``COMPONENTS_MIN`` and ``additions`` (the items without a change block, from the
    end of their group, then the items with one) down to ``ADDITIONS_MIN`` (a list
    with fewer items keeps them all): every short list keeps its minimum before any
    list goes below it. Then ``autostart`` down to ``AUTOSTART_MIN``. Then
    ``components``, ``driver_packages`` and ``drivers`` down to nothing, in that
    order, and then ``vendor_folders``, ``additions`` and ``programs``. A ``null``
    list (its source not read) stays ``null`` and its count key ``0``. Only
    when that is not enough, so ``autostart`` and ``changes`` are over the budget on
    their own, do the six lists go back to their minimums and ``autostart`` and
    ``changes`` get cut: down to ``AUTOSTART_MIN`` and ``CHANGES_MIN``, then to
    nothing, and then ``components``, ``driver_packages``, ``drivers``,
    ``vendor_folders``, ``additions`` and ``programs`` to nothing, in that order. Each count
    key of ``CUT_LISTS`` counts the cut items (``truncated_changes`` the cut changes,
    a collapsed entry by its ``count``); a cut
    ``autostart`` or ``changes`` also gets the per-type counts of the whole list in
    its ``COUNT_KEYS`` key (``null`` while it is not cut). A summary that is too long
    even with all eight lists empty is not cut at all and says so in not_checked.
    """
    text_out = dump(summary)
    originals = {name: summary.get(name) for name, _ in CUT_LISTS}
    if len(text_out) > SUMMARY_MAX_CHARS:
        count_keys = dict(CUT_LISTS)
        kept = {name: len(items or []) for name, items in originals.items()}
        minimums = {"programs": PROGRAMS_MIN, "vendor_folders": VENDOR_FOLDERS_MIN,
                    "driver_packages": DRIVER_PACKAGES_MIN,
                    "drivers": DRIVERS_MIN,
                    "components": COMPONENTS_MIN, "additions": ADDITIONS_MIN,
                    "autostart": AUTOSTART_MIN, "changes": CHANGES_MIN}
        floors = {name: min(minimums[name], kept[name]) for name in minimums}
        short_lists = [name for name, _ in CUT_LISTS if name not in COUNT_KEYS]
        # The lists that go to nothing, in this order, once every list is at its floor:
        # components, driver packages and then drivers; then vendor folders, additions
        # and programs.
        last_stages = [("components", 0), ("driver_packages", 0), ("drivers", 0),
                       ("vendor_folders", 0), ("additions", 0), ("programs", 0)]

        def fits(name: str, count: int) -> bool:
            items = originals[name]
            summary[name] = items[:count]
            summary[count_keys[name]] = (len(items) - count if name != "changes"
                                         else sum(map(entry_count, items[count:])))
            return len(dump(summary)) <= SUMMARY_MAX_CHARS

        def run_stages(stages) -> bool:
            for name, floor in stages:
                if floor >= kept[name]:
                    continue
                if name in COUNT_KEYS:
                    summary[COUNT_KEYS[name]] = list_counts(name, originals[name])
                if fits(name, floor):
                    # The most items that fit, by bisection; the kept count did not fit.
                    low, high = floor, kept[name] - 1
                    while low < high:
                        middle = (low + high + 1) // 2
                        if fits(name, middle):
                            low = middle
                        else:
                            high = middle - 1
                    fits(name, low)
                    return True
                kept[name] = floor
            return False

        # The package changes sit at the end of ``changes`` (PACKAGE_SOURCES are last
        # in SOURCES) and go first, before any other list is cut.
        changes = originals["changes"] or []
        package_floor = len(changes)
        while (package_floor
               and changes[package_floor - 1].get("source") in PACKAGE_SOURCES):
            package_floor -= 1
        # Then the six short lists to their floors, then autostart to its floor (with
        # its counts), and only then the short lists to nothing.
        fitted = run_stages([("changes", package_floor)]
                            + [(name, floors[name]) for name in short_lists]
                            + [("autostart", floors["autostart"])]
                            + last_stages)
        if not fitted:
            # autostart and changes are over the budget on their own: the six short
            # lists keep their floors, and these two are cut (autostart is at its floor
            # already).
            for name in short_lists:
                if originals[name] is not None:
                    fits(name, floors[name])
                    kept[name] = floors[name]
            fitted = run_stages([(name, floors[name]) for name in COUNT_KEYS]
                                + [(name, 0) for name in COUNT_KEYS]
                                + last_stages)
        if not fitted:
            # Something else is too long: cutting the lists would lose them for nothing.
            for name, count_key in CUT_LISTS:
                summary[name] = originals[name]
                summary[count_key] = 0
            for count_key in COUNT_KEYS.values():
                summary[count_key] = None
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
    parser.add_argument("--cut", action="store_true",
                        help="print the ids and names of the items the summary cut "
                             "(from the newest detail file) and exit")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail, --cut or --block: read this detail file (the "
                             "summary's detail_file) instead of the newest one")
    parser.add_argument("--compare-to", metavar="<N>d", help=baseline.COMPARE_TO_HELP)
    parser.add_argument("--block", metavar="IDS",
                        help="print the paste-ready blocks for these ids (comma-separated) "
                             "and exit")
    return parser


# --- change blocks (--block) ---------------------------------------------------------
# The printer mirrors the templates of SKILL.md "Change blocks"; it starts no job and
# writes no file. An entry it cannot fill safely gets "# <id>: no block: <reason>".
class NoBlock(Exception):
    """Why an item gets no change block (SKILL.md, "Change blocks")."""


# PowerShell takes each of these as a single quote, so each is doubled inside '...'.
PS_QUOTES = "'\u2018\u2019\u201a\u201b"
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# A profile folder of an account; Public and Default are not an account's.
PROFILE_ROOT = re.compile(
    r"[a-z]:\\users\\(?!(?:public|default|default user|all users)(?:[\\\"]|$))[^\\\"]+",
    re.IGNORECASE)
SC_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
# Remove-ItemProperty and Get-ItemProperty take these in -Name as wildcards.
NAME_WILDCARDS = re.compile(r"[*?\[\]]")
CODE_PAGE_REASON = "a value is not ASCII, so the text read from the console could differ"
APPROVED_ROOT = {
    "hkcu": "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved",
    "hklm": "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved",
}
RUN_ONCE_KINDS = ("String", "ExpandString")
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
SHELL_NOTE = {
    False: "Shell: normal (non-elevated) PowerShell of the user; an elevated one may run "
           "as another account and change that account's HKCU.",
    True: "Shell: elevated PowerShell (Run as administrator).",
}
ROLLBACK_NOTE = "# Rollback, same shell:"


def ps_quote(value) -> str:
    """``value`` as a single-quoted PowerShell string, each quote doubled."""
    if not isinstance(value, str) or not value:
        raise NoBlock("a value the block needs is missing in the detail file")
    if CONTROL_CHARS.search(value):
        raise NoBlock("a value the block needs holds a control character")
    return "'" + "".join(ch * 2 if ch in PS_QUOTES else ch for ch in value) + "'"


def value_name(entry: dict) -> str:
    """The quoted value name of a Run, RunOnce or Startup entry. A name with a
    wildcard (``*``, ``?``, ``[``, ``]``) gives no block: ``-Name`` would match
    other values as well."""
    name = entry.get("name")
    if isinstance(name, str) and NAME_WILDCARDS.search(name):
        raise NoBlock("the value name holds a wildcard character (* ? [ ]), so -Name "
                      "could match other values too")
    return ps_quote(name)


def one_line(value) -> str:
    return CONTROL_CHARS.sub(" ", str(value))


def profile_value(value: str, elevated: bool) -> tuple:
    """``(PowerShell expression, text for a comment)`` of ``value``. This account's
    profile folder is built from ``$env:USERPROFILE`` and shown as ``%USERPROFILE%``;
    another profile folder, or one in a value for an elevated shell, gives no block."""
    profile = os.environ.get("USERPROFILE") or ""
    parts = [value]
    if profile and PROFILE_ROOT.fullmatch(profile):
        parts = re.split(re.escape(profile) + r"(?=[\\\"]|$)", value, flags=re.IGNORECASE)
    if any(PROFILE_ROOT.search(part) for part in parts):
        raise NoBlock("the value points into the profile folder of another account")
    if len(parts) == 1:
        return ps_quote(value), value
    if elevated:
        raise NoBlock("the value holds a profile folder and an elevated shell may run as "
                      "another account, with another $env:USERPROFILE")
    pieces = []
    for index, part in enumerate(parts):
        if index:
            pieces.append("$env:USERPROFILE")
        if part:
            pieces.append(ps_quote(part))
    return "(" + " + ".join(pieces) + ")", "%USERPROFILE%".join(parts)


def ps_path(location: str) -> str:
    """``HKCU\\Software\\...`` as the PowerShell path ``HKCU:\\Software\\...``."""
    hive, rest = location.split("\\", 1)
    return f"{hive}:\\{rest}"


def approved_slot(entry: dict) -> tuple:
    """``(hive, StartupApproved key name)`` of a Run or Startup entry, from its key."""
    key = entry.get("key") if isinstance(entry.get("key"), str) else ""
    if entry.get("kind") == "run":
        for hive, slot in RUN_APPROVED.items():
            if key.startswith(f"run:{hive}\\Run:"):
                return slot
    else:
        for scope, slot in STARTUP_APPROVED.items():
            if key.startswith(f"startup:{scope}:"):
                return slot
    raise NoBlock(f"the key {one_line(key)!r} has no known StartupApproved value")


def block_run(entry: dict) -> tuple:
    """SKILL.md "Run or Startup entry": StartupApproved set to disabled (first byte 3)."""
    hive, slot = approved_slot(entry)
    elevated = hive != "hkcu"
    approved, raw = entry.get("approved"), entry.get("approved_raw")
    if approved == "disabled":
        raise NoBlock("the entry is already disabled (approved = disabled)")
    if approved not in ("not_set", "enabled"):
        raise NoBlock(f"approved is {approved!r}, so the previous state is not known")
    if approved == "enabled" and not (isinstance(raw, str) and raw and len(raw) % 2 == 0
                                      and set(raw) <= HEX_DIGITS):
        raise NoBlock("approved_raw (the previous value) is missing in the detail file")
    key = f"{APPROVED_ROOT[hive]}\\{slot}"
    name = value_name(entry)
    previous = f"approved = {approved}" + (f" (value {raw})" if approved == "enabled" else "")
    header = [
        (f"Turns off the autostart entry {name} ({hive.upper()} {slot}) as Task Manager "
         "does. The value or file itself stays."),
        SHELL_NOTE[elevated],
        "Risk: the program no longer starts at sign-in until the entry is turned on again.",
        f"Previous state: {previous}.",
    ]
    change = [
        f"$key = {ps_quote(key)}",
        "if (-not (Test-Path -LiteralPath $key)) { New-Item -Path $key -Force | Out-Null }",
        (f"New-ItemProperty -Path $key -Name {name} -PropertyType Binary "
         "-Value ([byte[]](3,0,0,0,0,0,0,0,0,0,0,0)) -Force | Out-Null"),
        f"(Get-ItemProperty -Path $key -Name {name}).{name}",
    ]
    if approved == "not_set":
        rollback = [f"Remove-ItemProperty -Path {ps_quote(key)} -Name {name}"]
    else:
        rollback = [
            f"$key = {ps_quote(key)}",
            f"$hex = {ps_quote(raw)}",
            ("$bytes = [byte[]]@(for ($i = 0; $i -lt $hex.Length; $i += 2) "
             "{ [Convert]::ToByte($hex.Substring($i, 2), 16) })"),
            (f"New-ItemProperty -Path $key -Name {name} -PropertyType Binary -Value $bytes "
             "-Force | Out-Null"),
        ]
    return elevated, header, change, f"back to {previous}", rollback


def block_run_once(entry: dict) -> tuple:
    """SKILL.md "RunOnce entry": the value is removed; the rollback writes it back."""
    key = entry.get("key") if isinstance(entry.get("key"), str) else ""
    hive = next((h for h in RUN_LOCATION if key.startswith(f"run:{h}\\RunOnce:")), None)
    if hive is None:
        raise NoBlock(f"the key {one_line(key)!r} is not a known RunOnce key")
    elevated = hive != "hkcu"
    kind, command = entry.get("value_kind"), entry.get("command")
    if kind not in RUN_ONCE_KINDS:
        raise NoBlock(f"value_kind {kind!r} has no template (String or ExpandString)")
    if not isinstance(command, str) or not command:
        raise NoBlock("the previous value (command) is missing in the detail file")
    value, shown = profile_value(command, elevated)
    path = ps_quote(ps_path(f"{RUN_LOCATION[hive]}\\RunOnce"))
    name = value_name(entry)
    header = [
        f"Removes the RunOnce value {name} ({hive.upper()}).",
        SHELL_NOTE[elevated],
        "Risk: a pending installer or update step may then never finish.",
        f"Previous value ({kind}): {one_line(shown)}",
    ]
    change = [f"Remove-ItemProperty -Path {path} -Name {name}",
              f"Get-ItemProperty -Path {path}"]
    rollback = [f"New-ItemProperty -Path {path} -Name {name} -PropertyType {kind} -Value {value}"]
    return elevated, header, change, "writes the previous value back", rollback


def block_task(entry: dict) -> tuple:
    """SKILL.md "Scheduled task": Disable-ScheduledTask; the rollback enables it."""
    location, state = entry.get("location"), entry.get("state")
    if entry.get("enabled") is False:
        raise NoBlock("the task is already disabled")
    if entry.get("enabled") is not True:
        raise NoBlock("enabled is not known, so the previous state is not known")
    # collect_tasks derives enabled from the state, so a null state reads as enabled.
    if not (isinstance(state, str) and state.strip()) or state.casefold() == "unknown":
        raise NoBlock("the task state was not read, so the previous state is not known")
    if not (isinstance(location, str) and location.startswith("\\")
            and location.endswith("\\")):
        raise NoBlock("the task path (location) is missing or not a task path")
    task = f"-TaskPath {ps_quote(location)} -TaskName {ps_quote(entry.get('name'))}"
    header = [
        f"Disables the task {one_line(location)}{one_line(entry.get('name'))}.",
        SHELL_NOTE[True],
        ("Risk: the task no longer runs on its triggers (e.g. the program's own updates "
         "stop) until it is enabled again."),
        f"Previous state: {one_line(state)}, enabled.",
    ]
    change = [f"Disable-ScheduledTask {task} | Out-Null",
              f"(Get-ScheduledTask {task}).State"]
    rollback = [f"Enable-ScheduledTask {task} | Out-Null"]
    return True, header, change, "enables the task again", rollback


def block_service(entry: dict) -> tuple:
    """SKILL.md "Per-user service" and "Other service": manual start; the rollback
    restores the start type read in this run."""
    name, user_service = entry.get("name"), entry.get("user_service")
    if not isinstance(name, str) or not name:
        raise NoBlock("the service name is missing in the detail file")
    if not isinstance(user_service, bool):
        raise NoBlock("user_service is not known, so the template does not apply")
    if "user_service" in (entry.get("unread_fields") or []):
        raise NoBlock("user_service is in unread_fields (guessed from the name), so the "
                      "template may not apply")
    if user_service:
        start = entry.get("template_start")
        if not isinstance(start, int) or isinstance(start, bool) or not 0 <= start <= 4:
            raise NoBlock("template_start is not known, so there is no rollback")
        key = ps_quote(f"HKLM:\\SYSTEM\\CurrentControlSet\\Services\\{name}")
        header = [
            (f"Sets the template of the per-user service {ps_quote(name)} to manual start "
             "(3). The instance may keep its start type until the next sign-in."),
            SHELL_NOTE[True],
            ("Risk: the service no longer starts at sign-in; a program that needs it may "
             "fail until it is started."),
            f"Previous Start value of the template: {start}.",
        ]
        change = [f"$key = {key}",
                  "Set-ItemProperty -Path $key -Name Start -Value 3 -Type DWord",
                  "(Get-ItemProperty -Path $key -Name Start).Start"]
        rollback = [f"Set-ItemProperty -Path {key} -Name Start -Value {start} -Type DWord"]
        return True, header, change, f"back to Start {start}", rollback
    delayed = entry.get("delayed")
    if not isinstance(delayed, bool):
        raise NoBlock("delayed is not known, so the previous start type is not known")
    if any(ch in name for ch in PS_QUOTES + '"'):
        raise NoBlock("the service name holds a quote")
    quoted = ps_quote(name)
    # A single-quoted filter: in double quotes PowerShell would expand $ and `.
    wql = ps_quote("Name='" + name.replace("\\", "\\\\") + "'")
    key = ps_quote(f"HKLM:\\SYSTEM\\CurrentControlSet\\Services\\{name}")
    previous = f"Automatic, delayed = {'true' if delayed else 'false'}"
    header = [
        (f"Sets the service {quoted} to manual start. The next run shows it as removed "
         "from the automatic services."),
        SHELL_NOTE[True],
        ("Risk: the service no longer starts at boot; a program that needs it may fail "
         "until it is started."),
        f"Previous start type: {previous}.",
    ]
    change = [
        f"Set-Service -Name {quoted} -StartupType Manual",
        f"(Get-CimInstance Win32_Service -Filter {wql}).StartMode",
        f"(Get-ItemProperty -Path {key}).DelayedAutostart",
    ]
    if delayed:
        # Windows PowerShell 5.1 has no AutomaticDelayedStart; sc is Set-Content there.
        sc_name = name if SC_NAME.match(name) else quoted
        rollback = [f"sc.exe config {sc_name} start= delayed-auto"]
    else:
        rollback = [f"Set-Service -Name {quoted} -StartupType Automatic"]
    return True, header, change, f"back to {previous}", rollback


AUTOSTART_BLOCKS = {
    "run": block_run,
    "startup_folder": block_run,
    "run_once": block_run_once,
    "task": block_task,
    "service": block_service,
}
NOT_AUTOSTART = {
    "programs": "this skill has no change block for a program",
    "drivers": ("no block for a device driver; a driver in use is removed only through "
                "its vendor's uninstaller or Device Manager, after the user decides"),
    "changes": "a change has no block; give the id of the item it names",
    "vendor_folders": "this skill has no block for a folder; ush-files has its own clean-up",
}


def autostart_block(entry: dict, context: dict) -> tuple:
    """The block parts of one autostart entry, or NoBlock with the reason of SKILL.md
    "Change blocks" (no previous value known, so no safe rollback)."""
    kind = entry.get("kind")
    unread = set(entry.get("unread_fields") or [])
    if entry.get("from_baseline") is True:
        raise NoBlock("not read in this run (from_baseline true), so its previous value "
                      "is not known")
    if entry.get("approved") == "unknown":
        raise NoBlock(f"approved is unknown (first byte {entry.get('approved_byte')}), "
                      "so its previous value is not known")
    for field in ("approved", "enabled"):
        if field in unread:
            raise NoBlock(f"{field} is in unread_fields, so its previous value is not known")
    if kind in ("run", "run_once", "startup_folder") \
            and context["approved_status"] not in READ_STATUSES:
        raise NoBlock("the source startup_approved was not read in this run (status "
                      f"{context['approved_status']}), so approved is the previous run's")
    if kind == "service":
        names = context["unread_services"]
        if names is None:
            raise NoBlock(f"the summary's not_checked could not be read "
                          f"({context['summary_reason']})")
        name = entry.get("name")
        if any(n == name or (entry.get("user_service") is True
                             and INSTANCE_SUFFIX.sub("", n) == name) for n in names):
            raise NoBlock(f"named in not_checked (services {one_line(name)}), so its "
                          "previous value is not known")
    builder = AUTOSTART_BLOCKS.get(kind)
    if builder is None:
        raise NoBlock(f"no template for kind {one_line(kind)!r}")
    parts = builder(entry)
    # An HKCU-shell entry (run:hkcu, startup:user, RunOnce of HKCU) read by an elevated
    # run may be another account's HKCU.
    if parts[0] is False:
        hkcu_read_by_this_account(context)
    missing = missing_target_line(entry)
    if missing is not None:
        elevated, header, change, back, rollback = parts
        parts = (elevated, [*header, missing], change, back, rollback)
    return parts


def hkcu_read_by_this_account(context: dict) -> None:
    """NoBlock unless the run that collected an HKCU value was not elevated."""
    if context.get("run_elevated") is True:
        raise NoBlock("the run that collected it was elevated, so its HKCU read may "
                      "belong to another account; print it with --detail-file of a "
                      "non-elevated run's detail file")
    if context.get("run_elevated") is not False:
        raise NoBlock("the detail file does not say whether the run was elevated, so its "
                      "HKCU read may belong to another account")


def missing_target_line(entry: dict):
    """One header line naming the target files of ``entry`` whose fact says ``exists``
    false (the path as written, not expanded), or None when every target is there or
    not known. A fact, not a judgement: the risk line stays as it is."""
    if entry.get("facts_from_baseline") is True \
            or "facts" in (entry.get("unread_fields") or []):
        # A fact carried over from the previous run may be outdated: no fact line.
        return None
    paths = []
    for fact in entry.get("facts") or []:
        if isinstance(fact, dict) and fact.get("exists") is False:
            path = text(fact.get("path")) or text(fact.get("expanded_path"))
            if path is not None and path not in paths:
                paths.append(path)
    if not paths:
        return None
    if not encodes(paths, "ascii"):
        return "Fact: a target file does not exist (its path is not ASCII; see --detail)."
    return f"Fact: the target file does not exist: {', '.join(map(one_line, paths))}"


# --- change blocks of additions (x..) and components (f..) ------------------------------
# The source of each kind, so "not read in this run" is checked per item.
KIND_SOURCE = {**{kind: source for source, kind in ADDITION_KINDS.items()},
               **{kind: source for source, kind in COMPONENT_KINDS.items()}}
# Disable-NetFirewallRule, *-WindowsOptionalFeature and *-WindowsCapability take these
# in -Name as wildcards (the backtick escapes the next one).
PATTERN_CHARS = re.compile(r"[*?\[\]`]")
THUMBPRINT = re.compile(r"^[0-9A-F]{40}$")
SID_TEXT = re.compile(r"^S-1-[0-9]+(?:-[0-9]+)+$")
ADMINISTRATORS_SID = "S-1-5-32-544"
NO_BLOCK_CODES = {
    "store_app_iso": "the rule is in store app_iso, so the app's package would restore it; "
                     "only a rule in store local gets a block",
    "store_policy": "the rule is in store policy, so a policy would restore it; only a "
                    "rule in store local gets a block",
    "cert_other_store": "the certificate is not in store machine_root or user_root, so a "
                        "policy would restore it",
    "cert_in_authroot": "the certificate is also in authroot (in_authroot true), so "
                        "Remove-Item could hit that copy",
    "cert_in_several_stores": "the thumbprint is also in another root store, so "
                              "Remove-Item could hit that copy",
    "defender_origin": "the exclusion's origin is not local, so a policy would restore it",
    "defender_method": "the exclusions were not read with Get-MpPreference (method "
                       "preference), so the template does not apply",
}
POLICY_ROOT = "HKLM:\\SOFTWARE\\Policies\\Microsoft\\SystemCertificates\\Root\\Certificates"
USER_POLICY_ROOT = "HKCU:\\Software\\Policies\\Microsoft\\SystemCertificates\\Root\\Certificates"
CERT_STORES = {
    "machine_root": {
        "item": "Cert:\\LocalMachine\\Root",
        "own": "HKLM:\\SOFTWARE\\Microsoft\\SystemCertificates\\ROOT\\Certificates",
        "others": ("HKLM:\\SOFTWARE\\Microsoft\\SystemCertificates\\AuthRoot\\Certificates",
                   POLICY_ROOT,
                   "HKLM:\\SOFTWARE\\Microsoft\\EnterpriseCertificates\\Root\\Certificates"),
    },
    "user_root": {
        "item": "Cert:\\CurrentUser\\Root",
        "own": "HKCU:\\Software\\Microsoft\\SystemCertificates\\Root\\Certificates",
        "others": ("HKLM:\\SOFTWARE\\Microsoft\\SystemCertificates\\ROOT\\Certificates",
                   "HKLM:\\SOFTWARE\\Microsoft\\SystemCertificates\\AuthRoot\\Certificates",
                   POLICY_ROOT,
                   "HKLM:\\SOFTWARE\\Microsoft\\EnterpriseCertificates\\Root\\Certificates",
                   USER_POLICY_ROOT),
    },
}
USER_CERT_SHELL = ("Shell: normal (non-elevated) PowerShell of the user; an elevated one may "
                   "run as another account and change that account's certificate store.")
DEFENDER_PARAMS = {"path": "ExclusionPath", "extension": "ExclusionExtension",
                   "process": "ExclusionProcess", "ip": "ExclusionIpAddress"}
TCPIP_PARAMETERS = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters"


def key_rest(item: dict, prefix: str) -> str:
    """The part of the item's ``key`` after ``prefix``; no block without it."""
    key = item.get("key")
    if not isinstance(key, str) or not key.startswith(prefix) or len(key) == len(prefix):
        raise NoBlock(f"the key {one_line(key)!r} does not start with {prefix!r}")
    return key[len(prefix):]


def needed(item: dict, *fields) -> None:
    """No block when a field the block needs is null or in ``unread_fields``."""
    unread = set(item.get("unread_fields") or [])
    for field in fields:
        if field in unread or item.get(field) is None:
            raise NoBlock(f"{field} is null or in unread_fields, so the block cannot be "
                          "filled safely")


def pattern_free(value: str, what: str) -> str:
    """``value`` quoted; a wildcard character gives no block (-Name would match more)."""
    if isinstance(value, str) and PATTERN_CHARS.search(value):
        raise NoBlock(f"the {what} holds a wildcard character (* ? [ ] `), so -Name could "
                      "match others too")
    return ps_quote(value)


def work_dir(context: dict) -> str:
    """``<data dir>\\work`` for an export or backup; no block when it is not known."""
    work = context.get("work_dir")
    if work is None:
        raise NoBlock("no data directory is known for the export or backup; give --data-dir")
    return str(work)


def block_firewall_rule(item: dict, context: dict) -> tuple:
    """SKILL.md "Firewall rule": disable a rule of store local by its value name."""
    store = item.get("store")
    if store != "local":
        raise NoBlock(f"the rule is in store {one_line(store)!r}, so a policy or the app's "
                      "package would restore it; only a rule in store local gets a block")
    name = pattern_free(key_rest(item, "firewall:local:"), "rule name")
    needed(item, "active")
    active = str(item["active"]).upper()
    if active == "FALSE":
        raise NoBlock("the rule is already disabled (Active = FALSE)")
    if active != "TRUE":
        raise NoBlock(f"Active is {one_line(item['active'])!r}, so the previous state is "
                      "not known")
    header = [
        (f"Disables the firewall rule {name} ({one_line(item.get('name'))!r}, store "
         "local). The rule is not deleted."),
        SHELL_NOTE[True],
        "Risk: the program the rule lets through loses that network access.",
        "Previous state: Active = TRUE.",
    ]
    change = [f"Disable-NetFirewallRule -Name {name}",
              f"(Get-NetFirewallRule -Name {name}).Enabled"]
    rollback = [f"Enable-NetFirewallRule -Name {name}"]
    return True, header, change, "enables the rule again", rollback


def block_root_certificate(item: dict, context: dict) -> tuple:
    """SKILL.md "Root certificate": checks the other root stores, exports into
    ``<data dir>\\work``, checks the file's thumbprint, then removes; the rollback
    imports the exported file."""
    store = item.get("store")
    if not isinstance(store, str):
        raise NoBlock("the store is null or missing, so it is not known which store to "
                      "remove it from")
    paths = CERT_STORES.get(store)
    if paths is None:
        raise NoBlock(f"the certificate is in store {one_line(store)!r}; only machine_root "
                      "and user_root get a block (a policy would restore it)")
    needed(item, "thumbprint", "in_authroot")
    thumb = item["thumbprint"]
    if not isinstance(thumb, str) or not THUMBPRINT.match(thumb):
        raise NoBlock("the thumbprint is not 40 hexadecimal digits")
    if key_rest(item, f"cert:{store}:") != thumb:
        raise NoBlock("the key does not name this thumbprint")
    if item["in_authroot"] is not False:
        raise NoBlock(NO_BLOCK_CODES["cert_in_authroot"])
    others = sorted(s for s in context["cert_stores"].get(thumb, set()) if s != store)
    if others:
        raise NoBlock(f"the thumbprint is also in store {', '.join(map(str, others))}, so "
                      "Remove-Item could hit that copy")
    elevated = store == "machine_root"
    if not elevated and context.get("run_elevated") is not False:
        raise NoBlock("the run that collected it was elevated, or does not say, so its "
                      "user_root read may belong to another account; print it with "
                      "--detail-file of a non-elevated run's detail file")
    work = work_dir(context)
    exported = f"{work}\\cert-{thumb}.cer"
    others_list = ", ".join(ps_quote(path) for path in paths["others"])
    header = [
        (f"Removes the root certificate {thumb} ({one_line(item.get('subject'))!r}, "
         f"store {store}). Exports it first into {work} and stops if the exported file "
         "has another thumbprint or the thumbprint is in another root store."),
        SHELL_NOTE[True] if elevated else USER_CERT_SHELL,
        "Risk: sites and programs that rely on this root are no longer trusted.",
        f"Previous state: in {paths['item']} (store {store}), in_authroot false.",
        ("The export holds only the certificate, not store properties such as the friendly "
         "name or restricted purposes, so the rollback may trust it for all its purposes."),
    ]
    change = [
        "& {",
        f"  $thumb = {ps_quote(thumb)}",
        f"  $item = {ps_quote(paths['item'] + chr(92))} + $thumb",
        f"  $own = {ps_quote(paths['own'] + chr(92))} + $thumb",
        f"  $others = @({others_list})",
        "  foreach ($store in $others) {",
        ("    if (Test-Path -LiteralPath (Join-Path $store $thumb)) { throw \"the thumbprint "
         "is also in $store; the Cert: store would not tell the copies apart; nothing "
         "removed\" }"),
        "  }",
        f"  $file = {ps_quote(work + chr(92) + 'cert-')} + $thumb + '.cer'",
        ("  Export-Certificate -Cert (Get-Item -LiteralPath $item -ErrorAction Stop) "
         "-FilePath $file -Type CERT -ErrorAction Stop | Out-Null"),
        ("  $copy = New-Object System.Security.Cryptography.X509Certificates."
         "X509Certificate2 $file"),
        ("  if ($copy.Thumbprint -ne $thumb) { throw \"the exported file has thumbprint "
         "$($copy.Thumbprint), not $thumb; nothing removed\" }"),
        "  Remove-Item -LiteralPath $item -ErrorAction Stop",
        "  Test-Path -LiteralPath $own",
        "}",
    ]
    rollback = [("# The export holds only the certificate, not store properties such as the "
                 "friendly name or restricted purposes, so this may trust it for all its "
                 "purposes."),
                (f"Import-Certificate -FilePath {ps_quote(exported)} "
                 f"-CertStoreLocation {ps_quote(paths['item'])}")]
    back = "imports the exported file (Windows may ask to confirm)"
    return elevated, header, change, back, rollback


HOSTS_EDIT = [
    ("  $reader = New-Object System.IO.StreamReader($hosts, [System.Text.Encoding]::Default, "
     "$true)"),
    "  $text = $reader.ReadToEnd(); $encoding = $reader.CurrentEncoding; $reader.Close()",
    "  $lines = New-Object System.Collections.Generic.List[string]",
    "  $lines.AddRange([string[]]($text -split \"`n\"))",
    "  $hits = @(for ($i = 0; $i -lt $lines.Count; $i++) {",
    ("    $words = @(($lines[$i].TrimEnd(\"`r\") -split '#', 2)[0].Trim() -split '[ \\t]+' "
     "| Where-Object { $_ })"),
    ("    if ($words.Count -ge 2 -and $words[0] -eq $address -and @($words[1..($words.Count "
     "- 1)] | Where-Object { $_ -eq $name }).Count -gt 0) { $i }"),
    "  })",
    ("  if ($hits.Count -ne 1) { throw \"expected one line with $address $name, found "
     "$($hits.Count); nothing changed\" }"),
    "  $i = $hits[0]",
    "  $cr = if ($lines[$i].EndsWith(\"`r\")) { \"`r\" } else { '' }",
    "  $parts = $lines[$i].TrimEnd(\"`r\") -split '#', 2",
    "  $words = @($parts[0].Trim() -split '[ \\t]+' | Where-Object { $_ })",
    "  $left = @($words[1..($words.Count - 1)] | Where-Object { $_ -ne $name })",
    "  if ($left.Count -gt 0) {",
    "    $line = (@($address) + $left) -join ' '",
    "    if ($parts.Count -eq 2) { $line += ' #' + $parts[1] }",
    "    $lines[$i] = $line + $cr",
    "  } else {",
    "    $lines.RemoveAt($i)",
    ("    if ($i -eq $lines.Count -and $i -gt 0) { $lines[$i - 1] = $lines[$i - 1].TrimEnd("
     "\"`r\") }"),
    "  }",
    "  [System.IO.File]::WriteAllText($hosts, ($lines -join \"`n\"), $encoding)",
    "  Select-String -LiteralPath $hosts -Pattern ([regex]::Escape($name))",
    "}",
]


def block_hosts_entry(item: dict, context: dict) -> tuple:
    """SKILL.md "Hosts entry": a stamped backup compared by hash before the one name is
    removed from its one line; the rollback copies the backup back."""
    hosts_file = context.get("hosts_file")
    if not isinstance(hosts_file, dict) or hosts_file.get("exists") is not True:
        raise NoBlock("the detail file does not say that the hosts file exists")
    needed(item, "address", "hostname")
    address, hostname = item["address"], item["hostname"]
    for value in (address, hostname):
        if not isinstance(value, str) or not value or re.search(r"[\s#]", value):
            raise NoBlock("the address or host name is empty or holds a space or #, so no "
                          "line would match it")
    if key_rest(item, "hosts:") != f"{hostname.casefold()}:{address}":
        raise NoBlock("the key does not name this address and host name")
    work = work_dir(context)
    backup = f"{work}\\hosts-{context['stamp']}-{item.get('id')}.bak"
    duplicates = item.get("duplicates")
    header = [
        (f"Removes the host name {ps_quote(hostname)} (address {address}) from the hosts "
         f"file. Copies the file into {work} first and stops if the copy differs, or if "
         "not exactly one line holds this address and name."),
        SHELL_NOTE[True],
        "Risk: the name is resolved by DNS again (a blocked site is reachable again).",
        (f"Previous state: line {one_line(item.get('line'))} of the hosts file holds "
         f"{address} {hostname} (duplicates {one_line(duplicates)})."),
    ]
    change = [
        "& {",
        f"  $address = {ps_quote(address)}; $name = {ps_quote(hostname)}",
        f"  $dir = (Get-ItemProperty -Path {ps_quote(TCPIP_PARAMETERS)}).DataBasePath",
        "  $hosts = Join-Path $dir 'hosts'",
        f"  $backup = {ps_quote(backup)}",
        ("  if (Test-Path -LiteralPath $backup) { throw \"$backup already exists (another "
         "block's backup); nothing changed\" }"),
        "  Copy-Item -LiteralPath $hosts -Destination $backup -ErrorAction Stop",
        "  $copyHash = (Get-FileHash -LiteralPath $backup -ErrorAction Stop).Hash",
        "  $hostsHash = (Get-FileHash -LiteralPath $hosts -ErrorAction Stop).Hash",
        ("  if (-not $copyHash -or $copyHash -ne $hostsHash) { throw 'the copy differs from "
         "the hosts file; nothing changed' }"),
        *HOSTS_EDIT,
    ]
    rollback = [
        f"$dir = (Get-ItemProperty -Path {ps_quote(TCPIP_PARAMETERS)}).DataBasePath",
        f"Copy-Item -LiteralPath {ps_quote(backup)} -Destination (Join-Path $dir 'hosts') -Force",
    ]
    return True, header, change, ("copies the backup back (this also undoes any later edit "
                                  "of the file)"), rollback


def block_administrator(item: dict, context: dict) -> tuple:
    """SKILL.md "Administrators member", within its "Rules": never the current
    account, none while any member's enabled is null, and only while an enabled
    is_current member read in this run stays in the group. That member never gets a
    block, so no set of blocks can empty the group. Members with from_baseline true
    are not counted."""
    sid = key_rest(item, "admin:")
    if not SID_TEXT.match(sid):
        raise NoBlock("the key does not hold a SID")
    if "is_current" in (item.get("unread_fields") or []) or item.get("is_current") is None:
        raise NoBlock("is_current is null, so it may be the account running the skill")
    if item.get("is_current") is not False:
        raise NoBlock("the member is the account running the skill (is_current true)")
    members = [m for m in context["administrators"] if m.get("from_baseline") is not True]
    if any(m.get("enabled") is None or "enabled" in (m.get("unread_fields") or [])
           for m in members):
        raise NoBlock("a member has enabled null, so it is not known which accounts could "
                      "still act as administrator")
    if not any(m.get("enabled") is True and m.get("is_current") is True
               and m is not item and m.get("key") != item.get("key") for m in members):
        raise NoBlock("no member read in this run with enabled true and is_current true "
                      "stays in the group, so removals could leave no member with enabled "
                      "true")
    group, member = ps_quote(ADMINISTRATORS_SID), ps_quote(sid)
    header = [
        f"Removes {sid} from Administrators ({ADMINISTRATORS_SID}).",
        SHELL_NOTE[True],
        ("Risk: the account loses administrator rights at its next sign-in; programs it "
         "runs as administrator stop working."),
        (f"Previous state: member ({one_line(item.get('object_class'))}, enabled "
         f"{one_line(item.get('enabled')).lower()})."),
    ]
    change = [f"Remove-LocalGroupMember -SID {group} -Member {member}",
              f"Get-LocalGroupMember -SID {group} | Select-Object SID, ObjectClass"]
    rollback = [f"Add-LocalGroupMember -SID {group} -Member {member}"]
    return True, header, change, "adds the member back", rollback


def block_defender_exclusion(item: dict, context: dict) -> tuple:
    """SKILL.md "Defender exclusion": only origin local read with method preference."""
    if context["methods"].get("defender_exclusions") != "preference":
        raise NoBlock(NO_BLOCK_CODES["defender_method"])
    needed(item, "origin", "type", "value")
    if item["origin"] != "local":
        raise NoBlock(NO_BLOCK_CODES["defender_origin"])
    param = DEFENDER_PARAMS.get(item["type"])
    if param is None:
        raise NoBlock(f"type {one_line(item['type'])!r} has no template")
    # This account's profile folder is built from $env:USERPROFILE (SKILL.md).
    value, shown = profile_value(item["value"], elevated=False)
    note = ("" if value.startswith("'") else
            " The path is built from $env:USERPROFILE: right only when the elevated shell "
            "runs as the same account.")
    header = [
        (f"Removes the Defender exclusion of the {item['type']} {one_line(shown)} (origin "
         f"local).{note}"),
        SHELL_NOTE[True],
        ("Risk: it is scanned again, which may slow a tool that relied on the exclusion."),
        f"Previous state: the {item['type']} is excluded from scanning.",
    ]
    change = [f"Remove-MpPreference -{param} {value}", f"(Get-MpPreference).{param}"]
    rollback = [f"Add-MpPreference -{param} {value}"]
    return True, header, change, "adds the exclusion back", rollback


def block_feature(item: dict, context: dict) -> tuple:
    """SKILL.md "Optional feature": disable an enabled feature; finishes at restart."""
    needed(item, "name", "state")
    if item["state"] != "enabled":
        raise NoBlock(f"state is {one_line(item['state'])!r}; only an enabled feature gets "
                      "a block")
    if key_rest(item, "feature:") != item["name"]:
        raise NoBlock("the key does not name this feature")
    name = pattern_free(item["name"], "feature name")
    header = [
        f"Disables the optional feature {name}. Finishes at the next restart.",
        SHELL_NOTE[True],
        "Risk: programs that use the feature stop working.",
        ("Features that depend on this one are disabled too, and the rollback enables only "
         "this one."),
        ("Previous state: enabled. Expected read-back: DisablePending (restart needed) or "
         "Disabled."),
    ]
    change = [(f"Disable-WindowsOptionalFeature -Online -FeatureName {name} -NoRestart "
               "| Out-Null"),
              f"(Get-WindowsOptionalFeature -Online -FeatureName {name}).State"]
    rollback = [f"Enable-WindowsOptionalFeature -Online -FeatureName {name} -NoRestart"]
    return True, header, change, ("enables it again (also finishes at restart; a feature "
                                  "with parents may need -All)"), rollback


def block_capability(item: dict, context: dict) -> tuple:
    """SKILL.md "Capability": remove an installed capability."""
    needed(item, "name", "state")
    if item["state"] != "Installed":
        raise NoBlock(f"state is {one_line(item['state'])!r}; only an Installed capability "
                      "gets a block")
    if key_rest(item, "capability:") != item["name"]:
        raise NoBlock("the key does not name this capability")
    name = pattern_free(item["name"], "capability name")
    header = [
        f"Removes the capability {name}. May finish at the next restart.",
        SHELL_NOTE[True],
        "Risk: the part of Windows it provides is gone until it is added back.",
        "Previous state: Installed. Expected read-back: anything other than Installed.",
    ]
    change = [f"Remove-WindowsCapability -Online -Name {name} | Out-Null",
              f"(Get-WindowsCapability -Online -Name {name}).State"]
    rollback = [f"Add-WindowsCapability -Online -Name {name}"]
    return True, header, change, ("adds it back (it may download the package from Windows "
                                  "Update, so it needs the network)"), rollback


ADDITION_BLOCKS = {
    "firewall_rule": block_firewall_rule,
    "root_certificate": block_root_certificate,
    "hosts_entry": block_hosts_entry,
    "administrator": block_administrator,
    "defender_exclusion": block_defender_exclusion,
    "feature": block_feature,
    "capability": block_capability,
}


def addition_block(item: dict, context: dict) -> tuple:
    """The block parts of one addition or component, or NoBlock with the reason of
    SKILL.md "Change blocks" (source not read, a needed field unread, an excluded kind)."""
    kind = item.get("kind")
    builder = ADDITION_BLOCKS.get(kind)
    if builder is None:
        raise NoBlock(f"no template for kind {one_line(kind)!r}")
    if item.get("from_baseline") is True:
        raise NoBlock("not read in this run (from_baseline true), so its previous state "
                      "is not known")
    status = context["statuses"].get(KIND_SOURCE[kind])
    if status not in READ_STATUSES:
        raise NoBlock(f"the source {KIND_SOURCE[kind]} was not read in this run (status "
                      f"{one_line(status)})")
    code = item.get("no_block_reason")
    if code is not None:
        raise NoBlock(NO_BLOCK_CODES.get(code, f"no_block_reason {one_line(code)}"))
    return builder(item, context)


# --- change blocks of leftovers (l..) ---------------------------------------------------
# A registry part's path: HKLM or HKCU, then SOFTWARE and at least one more key name.
# A registry part's path: <HKLM|HKCU>\SOFTWARE\<publisher>\<name>, or
# HKLM\SOFTWARE\WOW6432Node\<publisher>\<name>: exactly the keys leftover_keys asks.
REGISTRY_PART = re.compile(
    r"^(?:(?P<wow>HKLM)\\SOFTWARE\\WOW6432Node|(?P<hive>HKLM|HKCU)\\SOFTWARE)"
    r"\\(?P<publisher>[^\\]+)\\(?P<name>[^\\]+)$", re.IGNORECASE)
HIVE_NAMES = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER"}
FILE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
GUARD_64 = ("  if (-not [Environment]::Is64BitProcess) { throw 'this is a 32-bit PowerShell, "
            "which sees another HKLM\\SOFTWARE; open the 64-bit one; nothing removed' }")


# Environment variables a user-shell export path may be built from, most specific first
# (%LOCALAPPDATA% lies under %USERPROFILE%).
EXPORT_PATH_VARIABLES = ("LOCALAPPDATA", "USERPROFILE")


def export_file(context: dict, name: str, elevated: bool = False) -> tuple:
    """``(PowerShell expression, text for a comment)`` of the file ``name`` in
    ``<data dir>\\work``. For a block run in the user's own shell (``elevated`` false)
    whose data dir lies under ``%LOCALAPPDATA%`` or ``%USERPROFILE%``, the path is built
    from that variable at run time, so no account name or profile path is printed. An
    elevated shell may run as another account, so its path stays expanded."""
    path = f"{work_dir(context)}\\{name}"
    if not elevated:
        for variable in EXPORT_PATH_VARIABLES:
            base = (os.environ.get(variable) or "").replace("/", "\\").rstrip("\\")
            if not base or not re.match(r"[A-Za-z]:\\", base):
                continue
            if path.lower().startswith(base.lower() + "\\"):
                rest = path[len(base):]
                return (f"($env:{variable} + {ps_quote(rest)})", f"%{variable}%{rest}")
    return ps_quote(path), path


def block_registry_key(part: dict, context: dict) -> tuple:
    """SKILL.md "Registry key of a removed program": export the key into
    ``<data dir>\\work``, check the file holds the key's header line, then remove the
    key; the rollback imports the file. Hive and key come from the part's path alone."""
    path = part.get("path")
    match = REGISTRY_PART.match(path) if isinstance(path, str) else None
    if (match is None or CONTROL_CHARS.search(path)
            or (match["hive"] and match["publisher"].casefold() == "wow6432node")):
        raise NoBlock(f"the path {one_line(path)!r} is not a key "
                      f"SOFTWARE\\<publisher>\\<name> under HKLM or HKCU (or under "
                      f"HKLM\\SOFTWARE\\WOW6432Node), the only keys a leftover names")
    if part.get("status") != "read" or part.get("exists") is not True:
        raise NoBlock(f"the key was not read as there (status {one_line(part.get('status'))}"
                      f", exists {one_line(part.get('exists'))})")
    hive = (match["wow"] or match["hive"]).upper()
    rest = path.split("\\", 1)[1]
    elevated = hive == "HKLM"
    if not elevated:
        hkcu_read_by_this_account(context)
    key = f"{hive}\\{rest}"
    # One export file per key in one call: the same key twice prints one block.
    printed = context.setdefault("printed_keys", set())
    if key.casefold() in printed:
        raise NoBlock("the same key has its block above")
    printed.add(key.casefold())
    provider = f"{hive}:\\{rest}"
    header_line = f"[{HIVE_NAMES[hive]}\\{rest}]"
    # Names that sanitise alike (Foo Bar, Foo_Bar) differ by a hash of the whole key.
    digest = hashlib.sha256(key.casefold().encode("utf-8")).hexdigest()[:10]
    name = (f"reg-{hive.lower()}-{FILE_NAME_CHARS.sub('_', rest)[:100]}-{digest}-"
            f"{context['stamp']}.reg")
    file_expr, shown = export_file(context, name, elevated)
    counts = f"{one_line(part.get('values'))} values, {one_line(part.get('subkeys'))} subkeys"
    header = [
        (f"Removes the registry key {key} of a removed program. Exports it first to "
         f"{shown} and stops if the export is missing or does not hold the key."),
        SHELL_NOTE[elevated],
        ("Risk: settings the program kept in this key are gone; a program that still "
         "reads the key starts without them."),
        f"Previous state: the key is there ({counts}).",
    ]
    change = ["& {"]
    # A 32-bit PowerShell would see HKLM\SOFTWARE redirected to WOW6432Node; reg.exe
    # is told the 64-bit view as well.
    view = " /reg:64" if elevated else ""
    if elevated:
        change.append(GUARD_64)
    change += [
        f"  $file = {file_expr}",
        "  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null",
        ("  if (Test-Path -LiteralPath $file) { throw \"the export file $file is already "
         "there; nothing removed\" }"),
        f"  reg.exe export {ps_quote(key)} $file{view}",
        ("  if ($LASTEXITCODE -ne 0) { throw \"the export failed (exit code "
         "$LASTEXITCODE); nothing removed\" }"),
        (f"  if (-not (Test-Path -LiteralPath $file) -or -not (Select-String -LiteralPath "
         f"$file -SimpleMatch -Quiet -Pattern {ps_quote(header_line)})) {{ throw \"the "
         f"export $file is missing or does not hold the key; nothing removed\" }}"),
        f"  Remove-Item -LiteralPath {ps_quote(provider)} -Recurse -ErrorAction Stop",
        f"  Test-Path -LiteralPath {ps_quote(provider)}",
        "}",
    ]
    rollback = [f"reg.exe import {file_expr}"]
    if elevated:
        rollback = ["& {", GUARD_64.replace("nothing removed", "nothing imported"),
                    f"  reg.exe import {file_expr}{view}", "}"]
    back = "imports the exported file (the key, its values and subkeys)"
    return elevated, header, change, back, rollback


def block_driver_package(item: dict, context: dict) -> tuple:
    """SKILL.md "Driver packages": no removal for any package, whatever its
    ``device_state`` (plan 051: Windows refused every removal tried; no read without
    administrator rights shows what blocks it)."""
    raise NoBlock(PACKAGE_NO_BLOCK_REASON)


def leftover_part_block(part: dict, context: dict) -> tuple:
    """``(label, block parts)`` of one part of a leftover; NoBlock for a part without
    one. An autostart entry or firewall rule prints through its own template."""
    kind = part.get("kind")
    if kind == "registry_key":
        return "", block_registry_key(part, context)
    if kind == "folder":
        raise NoBlock("a folder is cleaned up only through ush-files, after the user "
                      "decides")
    found = context.get("items_by_key", {}).get(part.get("key"))
    if found is None:
        raise NoBlock(f"its entry {one_line(part.get('key'))!r} is not in the detail file")
    section, item = found
    builder = autostart_block if section == "autostart" else addition_block
    return f" ({one_line(part.get('id'))})", builder(item, context)


def leftover_blocks(item_id: str, item: dict, context: dict) -> list:
    """``[(lines, command count)]``: one block per part of the leftover ``item_id``."""
    blocks = []
    for part in item.get("parts") or []:
        if not isinstance(part, dict):
            continue
        label = f" ({one_line(part.get('id'))})" if part.get("id") else \
            f" ({one_line(part.get('kind'))})"
        try:
            label, (_elevated, header, change, back, rollback) = \
                leftover_part_block(part, context)
        except NoBlock as exc:
            blocks.append(([f"# {item_id}{label}: no block: {exc}"], 0))
            continue
        blocks.append(([f"# {item_id}{label}: {header[0]}",
                        *(f"# {line}" for line in header[1:]),
                        *change, f"{ROLLBACK_NOTE} {back}", *rollback], len(change)))
    if not blocks:
        blocks.append(([f"# {item_id}: no block: the leftover has no parts"], 0))
    return blocks


def printer_context(detail: dict) -> dict:
    """What the no-block conditions need beyond the entry: the status of
    ``startup_approved`` and the services named in the summary's ``not_checked``."""
    statuses = {s.get("name"): s.get("status") for s in detail.get("sources") or []
                if isinstance(s, dict)}
    elevated = detail.get("elevated")
    additions = [item for item in detail.get("additions") or [] if isinstance(item, dict)]
    cert_stores: dict = {}
    for item in additions:
        # Only text stores, so the sort in block_root_certificate cannot raise.
        if (item.get("kind") == "root_certificate" and isinstance(item.get("thumbprint"), str)
                and isinstance(item.get("store"), str)):
            cert_stores.setdefault(item["thumbprint"].upper(), set()).add(item.get("store"))
    context = {"approved_status": statuses.get("startup_approved"),
               "run_elevated": elevated if isinstance(elevated, bool) else None,
               "unread_services": None, "summary_reason": None,
               "statuses": statuses,
               "methods": {s.get("name"): s.get("method") for s in detail.get("sources") or []
                           if isinstance(s, dict)},
               "cert_stores": cert_stores,
               "administrators": [item for item in additions
                                  if item.get("kind") == "administrator"],
               "hosts_file": detail.get("hosts_file"),
               # The entries a leftover part names by key: {key: (section, item)}.
               "items_by_key": {item["key"]: (section, item)
                                for section in ("autostart", "additions")
                                for item in detail.get(section) or []
                                if isinstance(item, dict) and isinstance(item.get("key"), str)}}
    summary_file = detail.get("summary_file")
    if not isinstance(summary_file, str) or not summary_file:
        context["summary_reason"] = "the detail file names no summary_file"
        return context
    try:
        summary = json.loads(Path(summary_file).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        context["summary_reason"] = f"{type(exc).__name__}: {exc}"
        return context
    not_checked = summary.get("not_checked", []) if isinstance(summary, dict) else None
    if not isinstance(not_checked, list):
        context["summary_reason"] = "the summary holds no not_checked list"
        return context
    context["unread_services"] = [
        item["what"][len("services "):] for item in not_checked
        if isinstance(item, dict) and isinstance(item.get("what"), str)
        and item["what"].startswith("services ")]
    return context


def encodes(lines: list, encoding: str) -> bool:
    """Whether every line can be written in ``encoding`` (an unknown one: no)."""
    try:
        "\n".join(lines).encode(encoding)
    except (UnicodeError, LookupError):
        return False
    return True


def render_blocks(found: list, context: dict, encoding=None) -> tuple:
    """``(text, number of commands)``: one block per ``(id, section, item)`` in order.
    With ``encoding``, an entry whose lines do not encode in it gets a no-block line
    (ASCII) instead, so printing cannot fail half-way."""
    lines, count = [], 0
    for item_id, section, item in found:
        if section == "leftovers":
            for entry_lines, entry_count in leftover_blocks(item_id, item, context):
                if encoding is not None and not encodes(entry_lines, encoding):
                    entry_lines = [f"# {item_id}: no block for a part: {CODE_PAGE_REASON}"]
                    entry_count = 0
                if lines:
                    lines.append("")
                lines.extend(entry_lines)
                count += entry_count
            continue
        if lines:
            lines.append("")
        builder = {"autostart": autostart_block, "additions": addition_block,
                   "components": addition_block,
                   "driver_packages": block_driver_package}.get(section)
        if builder is None:
            entry_lines, entry_count = [f"# {item_id}: no block: {NOT_AUTOSTART[section]}"], 0
        else:
            try:
                _elevated, header, change, back, rollback = builder(item, context)
            except NoBlock as exc:
                entry_lines, entry_count = [f"# {item_id}: no block: {exc}"], 0
            else:
                entry_lines = [f"# {item_id}: {header[0]}",
                               *(f"# {line}" for line in header[1:]),
                               *change, f"{ROLLBACK_NOTE} {back}".rstrip(), *rollback]
                entry_count = len(change)
        if encoding is not None and not encodes(entry_lines, encoding):
            entry_lines, entry_count = [f"# {item_id}: no block: {CODE_PAGE_REASON}"], 0
        lines.extend(entry_lines)
        count += entry_count
    return "\n".join(lines), count


def show_block(work: Path, ids_text: str, detail_file: Path | None = None,
               backup_dir: Path | None = None, now: datetime | None = None) -> int:
    """Print the paste-ready blocks of the ids (comma-separated, duplicates dropped,
    order kept). Starts no machine job and writes no file; an unknown id gives 1.
    ``backup_dir`` (``<data dir>\\work``) is where a certificate or hosts block puts its
    export or backup, stamped with ``now``; without it those get no block."""
    if detail_file is None:
        files = sorted(work.glob("inventory-*.detail.json"), key=lambda p: p.name)
        if not files:
            print(f"no detail file in {work}; run the collection first", file=sys.stderr)
            return 1
        detail_file = files[-1]
    try:
        detail = json.loads(detail_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"{detail_file} could not be read: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    if not isinstance(detail, dict):
        print(f"{detail_file} does not hold a detail object", file=sys.stderr)
        return 1
    wanted = []
    for part in ids_text.split(","):
        if part.strip() and part.strip() not in wanted:
            wanted.append(part.strip())
    if not wanted:
        print("--block needs at least one id (e.g. s3,s7)", file=sys.stderr)
        return 1
    by_id = {}
    for section in DETAIL_SECTIONS:
        for item in detail.get(section) or []:
            if isinstance(item, dict) and item.get("id") is not None:
                by_id.setdefault(item["id"], (section, item))
    unknown = [item_id for item_id in wanted if item_id not in by_id]
    if unknown:
        print(f"id(s) {', '.join(unknown)} not found in {detail_file}", file=sys.stderr)
        return 1
    # ASCII only, like every other output of the script: the reader of a pipe may decode
    # it with another code page, and a changed name would make a false block.
    encoding = "ascii"
    context = printer_context(detail)
    context["work_dir"] = backup_dir
    context["stamp"] = (now or datetime.now(timezone.utc)).astimezone(
        timezone.utc).strftime("%Y%m%d-%H%M%S")
    text_out, count = render_blocks(
        [(item_id, *by_id[item_id]) for item_id in wanted], context, encoding)
    print(text_out)
    if count == 0:
        print("no command to paste: every id has a reason above", file=sys.stderr)
        return 1
    return 0


def cut_label_addition(item: dict):
    """The ``name`` of a cut addition, never a path or a SID: a certificate's subject
    (cut to SUBJECT_MAX), a hosts entry's hostname, a Defender exclusion's type only
    (its value is a path), any other kind's ``name``."""
    kind = item.get("kind")
    if kind == "root_certificate":
        subject = item.get("subject")
        return subject[:SUBJECT_MAX] if isinstance(subject, str) else None
    if kind == "hosts_entry":
        return item.get("hostname")
    if kind == "defender_exclusion":
        return item.get("type")
    return item.get("name")


CUT_LABELS = {
    "drivers": lambda item: item.get("device_name"),
    "driver_packages": lambda item: item.get("original_name"),
    "additions": cut_label_addition,
    # The folder name: the last part of its path.
    "vendor_folders": lambda item: (ntpath.basename(str(item.get("path") or "").rstrip("\\/"))
                                    or item.get("name")),
}


def show_cut(work: Path, detail_file: Path | None = None) -> int:
    """Print ``{detail_file, summary_file, cut}``: the listable items of the detail file
    that the summary of the same run does not hold. Starts no machine job."""
    if detail_file is None:
        files = sorted(work.glob("inventory-*.detail.json"), key=lambda p: p.name)
        if not files:
            print(f"no detail file in {work}; run the collection first", file=sys.stderr)
            return 1
        detail_file = files[-1]
    result, reason = ids.read_cut(detail_file, CUT_LABELS)
    if reason is not None:
        print(reason, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=1))
    return 0


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
    if args.detail is not None and args.cut:
        parser.error("--detail and --cut cannot be used together")
    if args.block is not None and (args.detail is not None or args.cut):
        parser.error("--block cannot be used with --detail or --cut")
    if args.block is not None:
        # The data dir is where a certificate export or hosts backup goes; with
        # --detail-file it is not needed for the other blocks.
        try:
            data_dir = datadir.resolve(args.data_dir, default=args.default_data_dir)
        except datadir.DataDirError as exc:
            if not args.detail_file:
                parser.error(str(exc))
            data_dir = None
        work = data_dir / "work" if data_dir is not None else None
        detail_file = Path(args.detail_file).absolute() if args.detail_file else None
        return show_block(work or Path(), args.block, detail_file, work, now)
    if args.detail_file and args.detail is None and not args.cut:
        parser.error("--detail-file needs --detail or --cut")
    compare_days = None
    if args.compare_to is not None:
        compare_days = baseline.parse_compare_to(args.compare_to)
        if compare_days is None:
            parser.error(f"--compare-to takes <N>d with N from 1 to "
                         f"{baseline.HISTORY_DAYS - 1}, e.g. 7d: {args.compare_to!r}")
    if args.detail_file:
        # The detail file is named explicitly: no data directory is needed.
        if args.cut:
            return show_cut(Path(), Path(args.detail_file).absolute())
        return show_detail(Path(), args.detail, Path(args.detail_file).absolute())
    try:
        data_dir = datadir.resolve(args.data_dir, default=args.default_data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    work = data_dir / "work"
    state = data_dir / "state"
    if args.detail is not None:
        return show_detail(work, args.detail)
    if args.cut:
        return show_cut(work)

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
    # The state compared with: the latest baseline, or a history copy with --compare-to.
    # ``previous`` stays the base of collect and merge_sources.
    reference = baseline.reference_for(state, SKILL, admin, loaded, args.compare_to,
                                       compare_days, now)
    reference_sources = reference["sources"]

    config, own_reason = load_own(DEFAULT_OWN_FILE)
    first_run = {"dir": state, "loaded": load_first_run(state),
                 "decided_at": now.isoformat(timespec="seconds")}
    statuses, current, col = collect(run_ps, work, stamp, previous, config, admin,
                                     first_run, reference_sources)
    stamp_autostart_age(col, current, statuses, loaded, now)
    if own_reason is not None:
        col.skip("windows-own.json", f"nothing is classified as part of Windows: "
                                     f"{own_reason}")
    own_kinds = config["msix_signature_kinds"]
    id_map, map_reason = ids.load_map(state, SKILL)
    if map_reason is not None:
        col.skip(*ids.load_note(map_reason))
    numbering = ids.Numbering(id_map, now.date().isoformat())

    comparison = {name: baseline.comparison_state(reference_sources, name, statuses[name])
                  for name in SOURCES}
    # Values taken from the latest baseline are no change against it, but would be
    # against a history copy: with --compare-to they are not compared.
    compared = (current if args.compare_to is None
                else compare_view(current, statuses, col.carried_facts, col.unread_keys,
                                  reference_sources))
    changes, listed_changes, own_changes = build_changes(
        reference_sources, compared, comparison, own_kinds,
        skip_facts=statuses["file_facts"] not in READ_STATUSES,
        skip_program=any(statuses[s] not in READ_STATUSES for s in PROGRAM_SOURCES),
    )
    programs, own_count = build_programs(current, own_kinds, numbering)
    collapse_rules, collapse_reason = load_collapsed(COLLAPSED_NAMES_FILE)
    if collapse_rules is None:
        col.skip("collapsed_names.json",
                 f"no change is collapsed in the summary: {collapse_reason}")
        collapse_rules = []
    suffixes, suffix_reason = load_suffixes(PER_USER_SUFFIXES_FILE)
    if suffixes is None:
        col.skip("per_user_suffixes.json",
                 f"no program is marked with per_user_pair: {suffix_reason}")
    else:
        pair_installs(programs, suffixes)
    listed_programs = [summary_program(p) for p in programs if not p["own"]]
    autostart, own_autostart, unknown = build_autostart(current, numbering)
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

    components, listed_count = build_components(current, numbering)
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
    drivers, listed_driver_count = build_drivers(current, numbering)
    drivers_read = statuses["drivers"] in READ_STATUSES
    driver_fields = ("id", "key", "device_name", "class", "provider", "version", "date",
                     "signer")
    listed_drivers = [{k: d.get(k) for k in driver_fields}
                      for d in drivers[:listed_driver_count]] if drivers_read else None
    # Driver packages: the summary lists the ones no present device names (non_present
    # and no_device_found), null when the store was not read, or when it holds packages
    # and the devices were not read.
    group_rules, groups_reason = load_driver_package_groups(DRIVER_PACKAGE_GROUPS_FILE)
    packages = build_driver_packages(current, col.devices, numbering, group_rules)
    packages_status = statuses["driver_packages"]
    if group_rules is None:
        col.skip(f"data/{DRIVER_PACKAGE_GROUPS_FILE.name}",
                 f"no driver package is put in a group; group, no_device_by_nature and "
                 f"driver_package_groups are null: {groups_reason}")
    if packages_status == "read" and col.devices is None:
        col.skip("driver_packages device_state", DEVICES_UNREAD_REASON)
    # Counted after matching: a package matched through another published name is not
    # unread, and with the devices not read the entry above covers every package.
    unread_names = sum(p.get("device_state_reason") == PUBLISHED_UNREAD_REASON
                       for p in packages)
    if unread_names:
        col.skip("driver_packages published_name",
                 f"{unread_names} package(s): {PUBLISHED_UNREAD_REASON}; device_state "
                 f"is null and they are listed only in the detail file")
    unknown_status = sum((p.get("device_state_reason") or "").startswith(
        UNKNOWN_STATUS_REASON) for p in packages)
    if unknown_status:
        col.skip("driver_packages device_state",
                 f"{unknown_status} package(s): a device that names the package has a "
                 f"status this script does not know ({UNKNOWN_STATUS_REASON}); "
                 f"device_state is null and they are listed only in the detail file")
    extensions = sum(p.get("device_state_reason") == EXTENSION_REASON for p in packages)
    if extensions:
        col.skip("driver_packages device_state (Extension packages)",
                 f"{extensions} package(s): {EXTENSION_REASON}; device_state is null and "
                 f"they are listed only in the detail file")
    other_class = sum((p.get("device_state_reason") or "").startswith(
        OTHER_CLASS_REASON) for p in packages)
    if other_class:
        col.skip("driver_packages device_class",
                 f"{other_class} package(s): {OTHER_CLASS_REASON}; device_state is null "
                 f"and they are listed only in the detail file")
    packages_judged = (packages_status == "empty"
                       or (packages_status == "read" and col.devices is not None))
    package_fields = ("id", "key", "published_name", "original_name", "provider", "class",
                      "version", "date", "signer", "device_state", "owner", "group",
                      "no_device_by_nature")
    listed_packages = None
    if packages_judged:
        listed_packages = []
        for p in packages:
            if p["device_state"] not in ("non_present", "no_device_found"):
                continue
            listed = {k: p.get(k) for k in package_fields}
            if "devices" in p:
                listed["devices"] = p["devices"]
            listed_packages.append(listed)
        # The budget cuts the list from its end, so the packages the report must name
        # come first: a non_present one (its device), then a filter package (its
        # owner), then the rest; each part keeps the provider/name/version order.
        listed_packages.sort(key=lambda p: (p["device_state"] != "non_present",
                                            p.get("no_device_by_nature") is not True))
    component_counts["driver_packages"] = (len(packages) if packages_status in READ_STATUSES
                                           else None)
    by_state = None
    if listed_packages is not None:
        by_state = {state: sum(p["device_state"] == state for p in packages)
                    for state in ("present", "non_present", "no_device_found")}
        by_state["unread"] = sum(p["device_state"] is None for p in packages)
    component_counts["driver_packages_by_state"] = by_state
    # Every package by group and state: null when the rules or the store were not read.
    package_groups = None
    if group_rules is not None and packages_status in READ_STATUSES:
        package_groups = []
        for group in sorted({p["group"] for p in packages}):
            members = [p for p in packages if p["group"] == group]
            counts = {state: sum(p["device_state"] == state for p in members)
                      for state in ("present", "non_present", "no_device_found")}
            counts["unread"] = sum(p["device_state"] is None for p in members)
            package_groups.append({"group": group, "count": len(members),
                                   "by_state": counts})

    defender_method = next((e.get("method") for e in col.sources
                            if e["name"] == "defender_exclusions"), None)
    additions, listed_addition_count = build_additions(current, defender_method,
                                                       numbering)
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

    # The program sources as they are saved, so a source not read in this run
    # removes no program.
    merged_sources = baseline.merge_sources(
        previous, current, {name: statuses[name] for name in current})
    removed_entries, removed_reason = load_removed(state)
    if removed_reason is not None:
        col.skip(f"state/{REMOVED_STATE}.json",
                 f"the programs removed in earlier runs are not known, only the ones "
                 f"removed since the last baseline are looked at: {removed_reason}")
    removed, _ = removed_programs(previous, merged_sources, removed_entries,
                                  now.date().isoformat())
    leftovers, kept_removed = find_leftovers(
        col, removed, merged_sources, current["file_facts"], autostart,
        additions, numbering, statuses, admin)
    removed_save_reason = save_removed(
        state, kept_removed, (state / f"{REMOVED_STATE}.json").exists())
    if removed_save_reason is not None:
        col.skip(f"state/{REMOVED_STATE}.json",
                 f"the removed programs were not saved, the next run will not know "
                 f"them: {removed_save_reason}")

    # Top-level vendor folders that no installed program matches (as saved, so a
    # program source not read in this run brings its baseline programs).
    vendor_config, vendor_reason = load_vendor_folders(VENDOR_FOLDERS_FILE)
    if vendor_config is None:
        col.record("vendor_folders", "unreadable",
                   f"no top-level folder is listed: {vendor_reason}")
        vendor_rows = []
    else:
        vendor_rows = collect_vendor_folders(col, vendor_config["roots"])
    listed_vendor_folders, vendor_counts, vendor_section = find_vendor_folders(
        col, vendor_config, vendor_rows, merged_sources, autostart, current["file_facts"],
        statuses, previous, numbering)
    component_counts.update(vendor_counts)

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
        "drivers_without_inf_items": col.drivers_without_inf_items,
        "driver_packages": packages,
        "additions": additions,
        "leftovers": leftovers,
        "vendor_folders": vendor_section["folders"],
        "vendor_folder_roots": vendor_section["roots"],
        "pip_packages": [{"key": key, **item}
                         for key, item in sorted(current["pip_packages"].items())],
        "npm_packages": [{"key": key, **item}
                         for key, item in sorted(current["npm_packages"].items())],
        "hosts_file": col.hosts_file,
        "current_sid": col.current_sid,
        "changes": changes,
        # The ids of the items the summary lists before the budget cut, for --cut.
        "listed": {name: [item["id"] for item in items or []] for name, items in (
            ("programs", listed_programs), ("autostart", listed_autostart),
            ("components", listed_components), ("drivers", listed_drivers),
            ("driver_packages", listed_packages), ("additions", listed_additions), ("changes", changes[:listed_changes]),
            ("vendor_folders", listed_vendor_folders))},
        "summary_file": str(summary_file),
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
        "not_checked": col.not_checked,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": 0,
        "truncated_vendor_folders": 0,
        "truncated_driver_packages": 0,
        "truncated_drivers": 0,
        "truncated_components": 0,
        "truncated_additions": 0,
        "truncated_autostart": 0,
        "truncated_changes": 0,
        "autostart_counts": None,
        "change_counts": None,
        "baseline": baseline_info,
        "comparison": comparison,
        "programs": listed_programs,
        "autostart": listed_autostart,
        "components": listed_components,
        "component_counts": component_counts,
        "drivers": listed_drivers,
        "driver_packages": listed_packages,
        "driver_package_groups": package_groups,
        "additions": listed_additions,
        "leftovers": leftovers,
        "vendor_folders": listed_vendor_folders,
        "package_managers": {"pip": col.pip_summary, "npm": col.npm_summary},
        "hosts_file": hosts_file,
        "own_counts": {"programs": own_count, "autostart": own_autostart,
                       "unknown": unknown,
                       "drivers": len(drivers) - listed_driver_count if drivers_read else None,
                       "firewall_rules": own_firewall,
                       "root_certificates": own_certificates},
        "changes": collapse_changes(changes[:listed_changes], collapse_rules),
        "own_changes": own_changes,
    }
    # Changes inside collapsed entries have no id in the summary; a count above 0
    # lets the report checker take their ids from the detail file.
    summary["collapsed_changes"] = sum(entry["count"] for entry in summary["changes"]
                                       if "collapsed" in entry)
    text_out = fit_budget(summary)
    summary_file.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Summary contract, ush-health (schema_version 1)

The ush-health fields of the summary, and the ush-health cases of the shared
parts. The shared contract (files and budget, `sources`, `not_checked`, ids
and `--detail`, recommendations, the report profile) is in
`skills/ush-common/references/summary-contract.md`; the report checker reads
the ush-health rules from `data/report-profile.json`.

## Files and output

One run of `scripts/health.py` writes two files to `<data dir>/work/`
(the data directory: `--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`, made absolute at once; see the shared
contract):

- `health-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text is
  printed on stdout. The time in the name is UTC, so names sort by time.
- `health-<YYYYmmdd-HHMMSS>.detail.json` - the detail file: `schema_version`,
  `skill`, `generated_at`, `elevated`, `sources`, `comparison` and the full
  lists `disks`, `volumes`, `devices`, `update_failures` (never truncated)
  and `changes`, with the same ids as the summary. Disks also keep
  `device_id` and `unique_id` (the disk's `UniqueId`) and devices
  `instance_id` there; the summary leaves them out.

Outside `work/` the run writes only to `<data dir>/state/`: the id map
`ush-health.ids.json` (see "Ids and --detail"), the baseline
`ush-health.json` (`ush-health.elevated.json` for an elevated run) with its
previous copy, and a day copy of the baseline in `state/history/` (see
"Baseline and changes").

The PowerShell jobs write their results to `health-<stamp>.<job>.json` in the
same directory (raw captures: never read them). The battery report of
`powercfg` goes to `health-<stamp>.battery.xml` and is deleted at once. The
script changes nothing on the machine and exits 0.

To keep the summary within its budget of 35 000 characters only
`updates.failures` is cut, from the end (the oldest groups); `truncated`
counts them, and the detail file (`update_failures`) keeps them all. When the
summary does not fit even with no failure group left, nothing is cut, the
summary goes out over the limit and `not_checked` gets the item
`summary budget`.

## Administrator rights

The script decides by `IsUserAnAdmin`, never by an error, which sources to
run: some of them give empty fields without an error when run without the
rights. `elevated` says which kind of run it was. Without the rights these
are not run:

| Source | Without administrator rights |
|---|---|
| `disk_reliability` (`Get-StorageReliabilityCounter`) | source `unreadable`, reason `needs administrator`; every disk's `reliability` is `null` |
| `tpm_wmi` (`Win32_Tpm`, part of `tpm`) | `not_checked` item `tpm_wmi`, reason `needs administrator`; `spec_version`, `is_enabled`, `is_activated` are `null` |
| `restore_points` (`Get-ComputerRestorePoint`) | source `unreadable`, reason `needs administrator`; `restore_points` is `null` |
| `winre` (`reagentc /info`) | source `unreadable`, reason `needs administrator`; `winre` is `null` |

Running the same script in an elevated PowerShell (the user does it, see
`SKILL.md`) reads a superset of the sources. It is still read-only.

## Summary fields

Besides the shared fields (`schema_version`, `skill` = `"ush-health"`,
`generated_at`, `sources`, `not_checked`, `summary_file`, `detail_file`,
`truncated`), a summary has:

| Field | Type | Meaning |
|---|---|---|
| `elevated` | bool | `true` when the run had administrator rights |
| `disks` | list or null | physical disks; ids `k..`, stable between runs (see "Ids and --detail"). `null` when `physical_disks` is unreadable |
| `volumes` | list or null | volumes with a drive letter; ids `v..`, stable between runs. `null` when `volumes` is unreadable |
| `battery` | object or null | the first battery, see below. `null` when `Win32_Battery` is unreadable |
| `devices` | list or null | Plug and Play devices whose status is not `OK`; ids `p..`, stable between runs. `[]` when every device is `OK`; `null` when `devices` is unreadable |
| `devices_by_status` | object or null | the number of present devices per `Status` (`OK`, `Error`, ...; a device without a status counts under `"unknown"`). `null` with `devices` |
| `secure_boot` | object or null | `enabled`, `firmware_type`, see below. `null` when unreadable |
| `tpm` | object | `devices`, `spec_version`, `is_enabled`, `is_activated`, see below. Always present |
| `updates` | object or null | Windows Update history, see below. `null` when `update_history` is unreadable |
| `pending_reboot` | object or null | three separate signals, see below. `null` when unreadable |
| `os_version` | object or null | `display_version`, `build`, `ubr`, `edition_id`. `null` when unreadable |
| `antivirus` | object or null | `products` and `defender`, see below. `null` when both parts are unreadable |
| `restore_points` | object or null | `count`, `newest`, `oldest`. `null` without administrator rights or when unreadable |
| `winre` | object or null | `status`. `null` without administrator rights or when unreadable |
| `baseline` | object | `{status, created_at, age_days, saved, reason, reference, reference_file}`, the shared meaning ("Baseline" of the shared contract); `status` is `compared`, `none` or `unreadable`. Always present |
| `comparison` | object | `{disks, volumes, devices, os}`, each `compared`, `no_baseline` or `not_read`. Always present |
| `changes` | list | the changes against the baseline, ids `c..`; `[]` when nothing changed or nothing was compared (see `comparison`). Always present |

A value that could not be read is `null`, never `false` or `0`. The script
counts and converts; it never rates a value.

### Disk

From `Get-PhysicalDisk`: `id`, `friendly_name`, `media_type`, `bus_type`,
`size_gb`, `health_status`, `operational_status` (the text Windows gives) and
`reliability`. Sizes are in units of 1024^3 bytes (what Explorer shows as
GB), rounded to 1 place.

`reliability` (administrator only, from `Get-StorageReliabilityCounter`) is
`null` without the rights, when the disk has no counter, or when its counter
could not be read (then `not_checked` has `disk_reliability: <friendly_name>`
with the error). Otherwise: `temperature_c`, `wear_percent`,
`read_errors_total`, `write_errors_total`, `power_on_hours`, each `null` when
the drive does not report it. A `Temperature` of 0 is what a drive without a
sensor reports: `temperature_c` is `null` (unknown), never 0.

### Volume

From `Get-Volume`, only volumes with a drive letter: `id`, `drive_letter`
(upper case, no colon), `file_system`, `size_gb`, `free_gb` (1024^3 bytes,
rounded to 1 place), `free_percent` (free / size x 100, rounded to 1 place,
computed from the bytes; `null` when the size is 0 or unknown),
`health_status` and `protection`.

`protection` is the raw `System.Volume.BitLockerProtection` value of the
volume (source `encryption`, read through `Shell.Application`, no rights
needed):

| Value | Meaning |
|---|---|
| `1` | BitLocker protection on |
| `2` | BitLocker protection off |
| any other number | not documented here: unknown, give it raw |
| `null` | could not be read (the source is `unreadable`, or the value was empty) |

### Battery

`present` (`false` when `Win32_Battery` lists no instance: no battery; then
every other field is `null`), `design_capacity_mwh`,
`full_charge_capacity_mwh`, `full_charge_percent_of_design` (full / design x
100, rounded to 1 place; `null` when either is unknown or design is 0) and
`cycle_count`. The capacities and cycles come from
`powercfg /batteryreport /xml`, run only when a battery is present. A
`CycleCount` of 0 is also what a battery that does not count cycles reports:
`cycle_count` is `null` (unknown), even though a new battery may truly have
0 cycles. With `present` `true` and the report unreadable, the fields are
`null` and the source `battery` is `unreadable`.

### Device

From `Get-PnpDevice -PresentOnly`, only devices whose `Status` is not `OK`:
`id`, `name` (friendly name, else name), `class`, `status` (`Error`,
`Degraded`, `Unknown`, ... or `null`) and `problem` (the problem code as the
text Windows gives, e.g. `CM_PROB_FAILED_START`, or `null`).

### Secure Boot

`enabled`: the `UEFISecureBootEnabled` value under
`HKLM\SYSTEM\CurrentControlSet\Control\SecureBoot\State` (`true` for a
non-zero number, `false` for 0; `null` when the key or value is missing,
which means unknown, not off). `firmware_type`: `%firmware_type%` as written
(`UEFI`, `Legacy`) or `null`.

### TPM

- `devices`: the TPM as a device (`Get-PnpDevice -Class SecurityDevices
  -PresentOnly`, no rights needed), a list of `{name, status}`; `[]` when no
  such device is present; `null` when that query failed.
- `spec_version`, `is_enabled`, `is_activated`: from `Win32_Tpm`
  (`root\CIMV2\Security\MicrosoftTpm`, administrator only; the
  `IsEnabled_InitialValue` and `IsActivated_InitialValue` properties). `null`
  without the rights, when the query failed or returned nothing. `Get-Tpm` is
  never used: without the rights it returns empty fields without an error.

### Updates

From the Windows Update Agent history (`Microsoft.Update.Session`,
`QueryHistory`, no rights needed):

- `history_count`: the number of history entries read;
- `by_result`: the number of entries per result name (table below);
- `failures`: the entries with `ResultCode` 4 or 5, grouped by (`title`,
  `hresult`, `result`), so a group never mixes `Failed` and `Aborted`. Ids
  `u1`, `u2`, ... Newest `last` first; groups without a known time at the end.

A failure group: `id`, `title`, `result` (`Failed` or `Aborted`), `hresult`
(`0x` and 8 upper-case hex digits of the 32-bit value, e.g. `0x8024200B`;
`null` when missing), `count`, `first`, `last` (ISO 8601 UTC with `Z`;
`null` when no entry of the group had a readable time). The agent gives the
time in UTC without a zone; the script marks it as UTC without shifting it.

| `ResultCode` | Result name |
|---|---|
| 0 | `NotStarted` |
| 1 | `InProgress` |
| 2 | `Succeeded` |
| 3 | `SucceededWithErrors` |
| 4 | `Failed` |
| 5 | `Aborted` |
| other number | its decimal text, e.g. `"7"` |
| missing | `"unknown"` (counted in `by_result`, never a failure) |

### Pending reboot

`windows_update` (the key `...\WindowsUpdate\Auto Update\RebootRequired`
exists), `component_servicing` (the key `...\Component Based
Servicing\RebootPending` exists) and `file_rename_operations` (the value
`PendingFileRenameOperations` under `Session Manager` exists). Each is given
on its own; there is no combined flag. A missing key is `false`; a key that
could not be opened makes the source `unreadable`, never `false`.
`file_rename_operations` alone is a weak signal: some software leaves it set
for good.

### OS version

From `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion`: `display_version`
(e.g. `24H2`), `build` (`CurrentBuild`, text), `ubr` (int) and `edition_id`.
`ProductName` is not read: on Windows 11 it still says Windows 10.

### Antivirus

Two parts of one source:

- `products`: from `root\SecurityCenter2 AntiVirusProduct`, a list of
  `{display_name, product_state}`. `product_state` is the raw `productState`
  as `0x` and upper-case hex without padding (e.g. `0x61100`); its bits are
  not documented and the script does not decode them. `null` when that part
  could not be read.
- `defender`: from `Get-MpComputerStatus`: `running_mode` (`AMRunningMode`
  as written), `real_time_protection_enabled`, `signature_age_days`,
  `quick_scan_age_days` and `signature_updated` (ISO 8601 UTC). `null` when
  that part could not be read or returned no status.

Sentinels: Defender reports "unknown or never" as a number. The script turns
them into `null`:

| Field | Sentinel | Summary |
|---|---|---|
| `signature_age_days` | `AntivirusSignatureAge` = 65535 | `null` |
| `quick_scan_age_days` | `QuickScanAge` = 4294967295 | `null` |

Status of the source `antivirus`:

- `read` when `products` was read with at least one product, or `defender`
  holds a status;
- `unreadable` when nothing was read and a part failed: `products` read but
  empty and `defender` `null` (the object is still given, with `products`
  `[]` and `defender` `null`), or both parts failed (`antivirus` is `null`).
  The reason names the failed part.

A failed part always has its own `not_checked` item (`antivirus_products` or
`defender`).

### Restore points

Administrator only. `count` (all points read), `newest` and `oldest` (the
`CreationTime` of the points, a DMTF time such as
`20260901103000.000000+120`, converted to ISO 8601 UTC with `Z`). A point
whose time is not a DMTF time is counted but left out of `newest`/`oldest`,
with a `not_checked` item. `count` 0 with status `empty`: read, no restore
points.

### WinRE

Administrator only. `status` is the text after `Windows RE status:` in the
output of `reagentc /info`, as written (e.g. `Enabled`). Only the English
line is recognised: any other output makes the source `unreadable` with the
reason `unrecognised reagentc output`, never "disabled".

## Sources

One entry per source, in this order, each with `name`, `status` and `reason`
(shared meaning):

| `name` | What | Needs administrator |
|---|---|---|
| `physical_disks` | `Get-PhysicalDisk` | no |
| `disk_reliability` | `Get-StorageReliabilityCounter` per disk | yes |
| `volumes` | `Get-Volume` | no |
| `encryption` | `System.Volume.BitLockerProtection` per lettered volume | no |
| `battery` | `Win32_Battery`, then `powercfg /batteryreport` | no |
| `devices` | `Get-PnpDevice -PresentOnly` | no |
| `secure_boot` | the `SecureBoot\State` registry value | no |
| `tpm` | TPM device, and `Win32_Tpm` when elevated | partly |
| `update_history` | Windows Update Agent history | no |
| `pending_reboot` | the three reboot signals | no |
| `os_version` | the `CurrentVersion` registry values | no |
| `antivirus` | `SecurityCenter2` and `Get-MpComputerStatus` | no |
| `restore_points` | `Get-ComputerRestorePoint` | yes |
| `winre` | `reagentc /info` | yes |

Special statuses:

- `disk_reliability` is `read` when the job ran, even when the counter of
  some disks failed (each such disk has its own `not_checked` item).
- `encryption` is `unreadable` with the reason `volumes not read` when
  `volumes` is unreadable, and `empty` when no volume has a drive letter.
- `battery` is `empty` when `Win32_Battery` lists no battery (`present`
  `false`); `unreadable` when the battery report failed or lists no battery.
- `secure_boot` is `read` whenever the job returned its object; a missing
  value inside it is `null`.
- `tpm` takes the status of the device query: `empty` (no TPM device) turns
  into `read` when `Win32_Tpm` was read, and into `unreadable` (reason
  `tpm_wmi: <error>`) when `Win32_Tpm` failed. When the device query failed
  the source is `unreadable` even if `Win32_Tpm` was read (its fields are
  still given).
- `update_history` is `empty` when the history holds no entries.
- `antivirus`: see Antivirus.

## Baseline and changes

Each run compares four sources with the baseline of the previous run of the
same kind (elevated or not; `--compare-to <N>d`: with the saved state at
least N days old, shared contract "Baseline") and then saves its own
baseline:

| Source | Status from | Key | Fields kept | Fields compared |
|---|---|---|---|---|
| `disks` | `physical_disks` | `unique_id` | `friendly_name`, `size_gb`, `health_status`, `operational_status`, `wear_percent`, `read_errors_total`, `write_errors_total` | all but `friendly_name` |
| `volumes` | `volumes` | `drive_letter` | `file_system`, `size_gb`, `free_gb`, `health_status`, `protection` | all |
| `devices` | `devices` | `instance_id` | `name`, `class`, `status`, `problem` | `status`, `problem` |
| `os` | `os_version` | `"os"` (one item) | `display_version`, `build`, `ubr`, `edition_id` | all |

`wear_percent`, `read_errors_total` and `write_errors_total` come from the
disk's `reliability`. The `devices` source holds only the devices whose
status is not `OK`, so a device that starts to fail is `added` and one that
recovers is `removed`.

- A field whose value is `null` in this run (not read) is not compared: it
  is in the item's `unread_fields`. The saved item keeps the previous value
  of that field, so the next successful read gives no false change. Without
  administrator rights the disk counters are not read, so they are compared
  only between elevated runs (each kind keeps its own baseline). Such
  fields are named in a `<source> not compared: <fields>` item of
  `not_checked`.
- A source whose status is not `read` or `empty` is not compared
  (`comparison` `not_read`) and keeps its previous items in the saved
  baseline. A source missing from the baseline compared with is
  `no_baseline`.
- A disk without a `UniqueId` and a device without an `instance_id` are
  neither kept nor compared, and nor are disks, volumes or devices whose
  key came twice in this run. A key that is empty or only whitespace counts
  as none. (A volume without a drive letter is not in `volumes` at all.)
- A key that came twice in this run gives no change (`added`, `removed` or
  `changed`), and the saved baseline keeps the previous item with that key.
- An item without a key may be any saved item, so its source gives no
  `removed` in this run (`added` and `changed` of keyed items still come),
  and the saved baseline keeps every previous item of that source not
  matched in this run. The reason of its `not compared` item says so.

A change: `id` (`c..`), `source` (`disks`, `volumes`, `devices`, `os`),
`kind` (`added`, `removed`, `changed`), `item` (the id of the disk, volume
or device in this run; `null` for `removed` and for `os`), `name` (the
disk's `friendly_name`, the drive letter, the device's `name`, or `"os"`;
for `removed` from the baseline) and `fields` (`{field: {before, after}}`
for `changed`, `{}` otherwise). Changes come in the order of the table,
then by key. The script gives `before` and `after` only: no difference and
no judgement.

## not_checked

Items have the shared shape. They are added for:

- every `unreadable` source (reason = the error text, or `needs
  administrator`), except `antivirus` and a `tpm` made `unreadable` by
  `Win32_Tpm`, whose failed parts have their own items;
- `tpm_wmi`: `Win32_Tpm` not run without administrator rights (`needs
  administrator`) or failed (the error text);
- `antivirus_products` and `defender`: a failed part of `antivirus`; a
  Defender job that returned no object gives `defender` with the reason
  `Get-MpComputerStatus returned no status`;
- `disk_reliability: <friendly_name>`: the counter of that disk could not be
  read (reason = the error);
- `battery`: the battery report lists more than one battery; only the first
  is summarised;
- `battery_report`: the report file could not be deleted from the work
  directory;
- `restore_points: creation time`: some creation times are not DMTF times
  (the reason gives how many of how many);
- `summary budget`: the summary exceeds 35000 characters and was not cut;
- `stable ids`: `state/ush-health.ids.json` could not be read, so the
  numbering started again (the file is kept as `.unreadable-<stamp>.json`
  when the new map is saved);
- `stable ids save`: the id map was not saved; this run's ids hold, the next
  run may give other ones (when the reason starts with "the id map was saved", only its previous copy was not replaced and the next run keeps these ids);
- `stable ids <letter>`: items whose key came twice in this run (two device
  rows with the same instance id), and items without a key (a disk without
  `UniqueId`, a device without an instance id); they got ids kept for this
  run only, named in the reason, so the next run may give them other ids;
- `disk not compared: no UniqueId` and `disk not compared: repeated
  UniqueId`, `device not compared: no InstanceId` and `device not compared:
  repeated InstanceId` (and `volume not compared: repeated drive letter`):
  that item is not kept in the baseline and not compared. The reason names
  it by id and name, never by its key (a `UniqueId` may hold a serial
  number). For `no ...` the reason also says that removed disks or devices
  were not checked in this run and that saved ones not seen stay in the
  baseline; for `repeated ...` it says that the saved item with that key
  stays in the baseline;
- `<source> not compared: <fields>` (`disks`, `volumes`, `devices` or
  `os`; the fields comma-separated and sorted): in a source that was
  compared, these fields are in `unread_fields` of an item of this run or
  of the same item in the state compared with, for items present on both
  sides; the reason gives the number of such items (each lacks one or
  more of the fields, not necessarily all) and says that the value was not
  read in this run or in the run compared with. An item only on
  one side (`added` or `removed`) does not count;
- `baseline` (the latest baseline could not be read), `reference baseline`
  (the history copy chosen by `--compare-to` could not be read, so nothing
  was compared), `baseline history` ("history not kept: ...", or "the day copy was kept, but old copies were not removed: ..." when
  only the cleanup failed) and
  `baseline save` (this run's baseline was not saved), as in the shared
  contract.

## Ids and --detail

Ids: `k..` disks, `v..` volumes, `p..` devices, `u..` update failure groups,
`c..` changes.

The numbers of `k`, `v` and `p` are stable between runs (shared contract,
"Ids and --detail"): the number belongs to the item, not to its position in
the list, so the summary may have gaps (`k1`, `k3`). The key of a disk is
its `UniqueId` (not `device_id`, which is only the enumeration number), of a
volume its drive letter and of a device its `instance_id`. The map from key
to number is kept in `<data dir>/state/ush-health.ids.json` (the same file
for a run with and without administrator rights); a new item takes a number
higher than any given before, and the number of an item that went away is
not given again. A disk without `UniqueId` and a device without `instance_id`
(a blank one, empty or only whitespace, counts as none) get a number for
this run only. The update failure groups `u` and the changes `c` are
numbered by position in each run.

`python -B skills/ush-health/scripts/health.py --data-dir <dir> --detail <id>`
prints the item with that id from the newest `health-*.detail.json` in
`<dir>/work/` (sections `disks`, `volumes`, `devices`, `update_failures`,
`changes`) and
exits 0. `--detail-file`, errors and exit codes are as in the shared contract.
A failure group cut from the summary (`truncated`) keeps its id: the summary
holds `u1` to `u<n>` and the cut ones are `u<n+1>` onward.

## Recommendations (written by the model in the report)

Fields and weights are in the shared contract. A `change` gives a paste-ready
block for the user to run (in an elevated PowerShell when it needs
administrator rights) and how to read the value back afterwards; the skill
never runs it. Running `health.py` elevated is a read, not a recommendation:
it changes nothing.

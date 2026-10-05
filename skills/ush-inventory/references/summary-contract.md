# Summary contract, ush-inventory (schema_version 1)

The ush-inventory fields of the summary, and the ush-inventory cases of the
shared parts. The shared contract (files and budget, `sources`,
`not_checked`, ids and `--detail`, the baseline, recommendations, the report
profile) is in `skills/ush-common/references/summary-contract.md`; the report
checker reads the ush-inventory rules from `data/report-profile.json`.

## Files and output

One run of `scripts/inventory.py` writes to `<data dir>` (the data
directory: `--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`, made absolute at once; see the shared
contract):

- `work/inventory-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same
  text is printed on stdout. The time in the name is UTC.
- `work/inventory-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `elevated`, `sources`,
  `comparison` and the full lists `programs`, `autostart`, `components`,
  `drivers`, `additions` and `changes` (never truncated), with the same ids
  as the summary, plus `hosts_file` (with `raw_dir`, `expanded_dir` and
  `path`), `current_sid` and `drivers_without_inf_items` (see "Drivers"). It also holds what the summary leaves out: the
  programs, autostart entries, drivers, firewall rules and certificates
  that are part of Windows, the entries with `own: null`, the components
  that are not listed, the changes of own items, the fields the summary
  drops (a program's `install_location`, `source` and `own`; an autostart
  entry's `approved_raw` and `display_name`, a fact's `company`, and a
  fact's `expanded_path` when it equals `path`; a driver's `inf_name`,
  `third_party` and `own`; the other fields of a firewall rule and a
  certificate), and the whole certificate subject. The baseline also keeps
  the full items, and the comparison and `own` are computed from them.
- `state/ush-inventory.json`, or `state/ush-inventory.elevated.json` for a
  run with administrator rights - the baseline (shared contract,
  "Baseline"). It is the only file the script keeps between runs.

The PowerShell jobs write their results to `work/inventory-<stamp>.<job>.json`
and the list of target files to `work/inventory-<stamp>.file_facts.input.json`
(raw captures: never read them). The script changes nothing on the machine
and exits 0; a `.lnk` shortcut is only read, never saved.

To keep the summary within its budget of 35 000 characters four lists may
be cut from their end, in these stages, each only when the one before it
did not make the summary fit:

| Stage | List | Count key | Cut first |
|---|---|---|---|
| 1 | `programs`, down to the 20 newest (`PROGRAMS_MIN`) | `truncated` | programs without an install date, then the oldest installs |
| 2 | `drivers`, down to the first 10 (`DRIVERS_MIN`) | `truncated_drivers` | the end of the driver order (`Display` drivers lead it) |
| 3 | `components`, down to the first 10 (`COMPONENTS_MIN`) | `truncated_components` | capabilities (they follow the features), then features, each from the end of the name order |
| 4 | `additions`, down to the first 10 (`ADDITIONS_MIN`) | `truncated_additions` | the items without a change block, from the end of their group, then the items with one (see "Additions") |
| 5 | `drivers`, below the first 10 | `truncated_drivers` | as in stage 2 |
| 6 | `components`, below the first 10 | `truncated_components` | as in stage 3 |
| 7 | `additions`, below the first 10 | `truncated_additions` | as in stage 4 |
| 8 | `programs`, below the 20 newest | `truncated` | as in stage 1 |

Stages 1 to 4 keep a short list of each: a list with fewer items than its
minimum keeps them all.

Each count key is always in the summary, `0` when nothing was cut. The
detail file keeps every item; the id of a cut item is its stable number
(see "Ids" below), not a position after the last one in the summary, so only
the detail file gives it: `inventory.py --cut [--detail-file <path>]` lists
the cut items as `{id, list, name}` (the ids in the detail file's `listed`
that the summary of `summary_file` does not hold) without starting any
machine job, and `--detail <id>` fetches one. The detail file's `listed` is
`{list: [id, ...]}`, the ids of the listable items of `programs`,
`autostart`, `components`, `drivers` and `additions` before the cut (own
items are never in it), and `summary_file` is the summary of the same run.
A detail file without `listed` or `summary_file`, or a summary that cannot be
read, makes `--cut` exit 1 with the missing field or file on stderr. `autostart` and `changes` are never cut. When the summary does not
fit even with all four lists empty, nothing is cut (every count is `0`),
the summary goes out over the limit and `not_checked` gets the item
`summary budget`.

## Sources

`sources` is a list of `{name, status, reason}`, one per job, in this order:

| Source | What is read | Gives |
|---|---|---|
| `win32_programs` | the `Uninstall` keys of `HKLM` (64-bit view), `HKLM\SOFTWARE\WOW6432Node` and `HKCU`; only subkeys with a `DisplayName` | programs |
| `msix_programs` | `Get-AppxPackage -PackageTypeFilter Main` of the current account only (other accounts need administrator rights and are not read) | programs |
| `run_keys` | the values of `Run` and `RunOnce` in `HKCU`, `HKLM` and `HKLM\SOFTWARE\WOW6432Node`, raw (environment variables not expanded), with their value kind | autostart entries |
| `startup_folders` | the files of the `Startup` (this account) and `CommonStartup` folders except `desktop.ini`; a `.lnk` is resolved to its target and arguments | autostart entries |
| `startup_approved` | `Explorer\StartupApproved\Run`, `Run32` and `StartupFolder` in `HKCU` and `HKLM` | no items: the `approved` and `enabled` fields of `run_keys` and `startup_folders` entries |
| `scheduled_tasks` | `Get-ScheduledTask`; only tasks with a logon (`MSFT_TaskLogonTrigger`) or boot (`MSFT_TaskBootTrigger`) trigger | autostart entries |
| `services` | `Win32_Service` with `StartMode` `Auto`, with `Type`, `DelayedAutostart` and `ServiceDll` from the service's registry key | autostart entries |
| `file_facts` | for every target file of the autostart entries: the expanded path, whether it exists, its Authenticode status, signer and company | no items: the `facts` of the entries |
| `optional_features` | `Win32_OptionalFeature` (no administrator rights needed) | components (`feature`) |
| `capabilities` | `Get-WindowsCapability -Online`, only with administrator rights; without them the job is not run and the source is `unreadable` with the reason `requires administrator rights (not read in this run, which is not elevated); this is not an empty list` | components (`capability`) |
| `drivers` | `Win32_PnPSignedDriver`, one row per device; a row without `InfName` is no item: `drivers_without_inf` counts the `Win32_PnPSignedDriver` rows without an INF file (for example software devices, or a device without a driver), not device state; device state is measured by `ush-health` | drivers |
| `firewall_rules` | the rule values of three `FirewallRules` keys under `HKLM`: `local` (`SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules`), `app_iso` (`...\FirewallPolicy\RestrictedServices\AppIso\FirewallRules`, rules of Store apps) and `policy` (`SOFTWARE\Policies\Microsoft\WindowsFirewall\FirewallRules`) | additions (`firewall_rule`) |
| (job `firewall_apps`, not a source) | the `App` values (text only, not `System`, not empty) of all rules, own ones included, in `work/inventory-<stamp>.firewall_apps.input.json`; each is expanded with `[Environment]::ExpandEnvironmentVariables` and checked with `Get-Item -LiteralPath -Force` in the context of the running account. Not run when no rule has such a value. A failed job, or no rows for a non-empty input, is a `not_checked` item `firewall_apps` | the `app_exists` of the rules |
| `root_certificates` | the thumbprint subkeys of five physical root stores in the registry: `machine_root` (`HKLM\SOFTWARE\Microsoft\SystemCertificates\ROOT`), `machine_policy` (`HKLM\SOFTWARE\Policies\Microsoft\SystemCertificates\Root`), `enterprise` (`HKLM\SOFTWARE\Microsoft\EnterpriseCertificates\Root`), `user_root` (`HKCU\Software\Microsoft\SystemCertificates\Root`), `authroot` (`HKLM\SOFTWARE\Microsoft\SystemCertificates\AuthRoot`); subject, issuer, dates and serial number from `Cert:` | additions (`root_certificate`) |
| `hosts` | the `hosts` file in the folder of `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\DataBasePath` (a missing value fails the job; a missing file is read and holds no entries) | additions (`hosts_entry`), `hosts_file` |
| `administrators` | the members of Administrators (`S-1-5-32-544`) by `Get-LocalGroupMember`, with `Enabled` from `Get-LocalUser` for local and Microsoft accounts; when `Get-LocalGroupMember` fails, ADSI. The source entry has `method`: `local_group_member` or `adsi` (`null` when the job gave nothing) | additions (`administrator`) |
| `defender_exclusions` | only with administrator rights (same reason as `capabilities` otherwise): `Get-MpPreference`, or, when it fails (e.g. another antivirus is active), the value names of `HKLM\SOFTWARE\Microsoft\Windows Defender\Exclusions\*`; in both cases the value names of the policy keys `HKLM\SOFTWARE\Policies\Microsoft\Windows Defender\Exclusions\*`. The source entry has `method`: `preference`, `registry` or `null` (not run or nothing given). A value Defender hides (`N/A: ...`) makes the source `unreadable` | additions (`defender_exclusion`) |

A missing key (no `StartupApproved` key, no `RunOnce` key, no `Uninstall` key
in `HKCU`) is "nothing there", not an error. A denied key fails the job, and
the source is `unreadable`. Rows came but none of them is an item: `empty`.
Only rows that could not be read: `unreadable`, never `empty`.

Without administrator rights a `scheduled_tasks` source that is `read` goes
with the `not_checked` item `scheduled_tasks visibility`: the task list may miss tasks this
account cannot see, without any error.

For the other sources the same holds: a missing `FirewallRules` key or root
store key is no items, a denied key fails the whole job. For
`optional_features`, `capabilities` and `drivers` a job that gave rows but
no item is `empty`, and one whose rows all lack their key field is
`unreadable`. The jobs of `firewall_rules`, `root_certificates`, `hosts`,
`administrators` and `defender_exclusions` give one row per store (or one
object), so these sources are `read` also when they hold no item: `read`
with no item of that kind is "nothing there".
Rows without their key field (`Name`, `DeviceID`, the rule's value name, the
thumbprint, the member's SID) are never dropped silently: the `not_checked`
item `<source> without <field>` gives their number.

## Keys

Every item has a stable `key`, the same in every run:

| Source | Key |
|---|---|
| `win32_programs` | `win32:<hklm64 / hklm32 / hkcu>:<subkey name>` |
| `msix_programs` | `msix:<PackageFamilyName>`; of two packages of one family the higher `Version` stays |
| `run_keys` | `run:<hkcu / hklm64 / hklm32>\<Run / RunOnce>:<value name>` |
| `startup_folders` | `startup:<user / common>:<file name>` |
| `scheduled_tasks` | `task:<TaskPath><TaskName>` |
| `services` | `service:<Name>`; for an instance of a per-user service (`Type` with bit 0x80) `service:<template>`, the template being the name without its `_<hex>` ending, so the new instance name at each sign-in is no change |
| `optional_features` | `feature:<Name>` |
| `capabilities` | `capability:<Name>` |
| `drivers` | `driver:<DeviceID>`: one item per device, not per driver package (`oem<N>.inf` changes when a driver is installed again) |
| `firewall_rules` | `firewall:<local / app_iso / policy>:<registry value name>`; for `local` the value name is the rule's `-Name` in `Get-NetFirewallRule` |
| `root_certificates` | `cert:<store>:<THUMBPRINT>` (upper case) |
| `hosts` | `hosts:<host name, lower case>:<address>` |
| `administrators` | `admin:<SID>` |
| `defender_exclusions` | `defender:<path / extension / process / ip>:<value, lower case>` |

The hive part of a `run:` key names the registry key: `hkcu` is
`HKCU\Software\Microsoft\Windows\CurrentVersion`, `hklm64` is
`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion`, `hklm32` is
`HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion` (the entry's
`location` has the full path).

## Summary fields

Besides the shared fields (`schema_version`, `skill` = `"ush-inventory"`,
`generated_at`, `sources`, `not_checked`, `summary_file`, `detail_file`,
`truncated`), a summary has (each key is always present; the profile's
`required_keys` make the report checker fail a summary without
`components`, `component_counts`, `drivers`, `additions` or `hosts_file`):

| Field | Type | Meaning |
|---|---|---|
| `elevated` | bool | the run had administrator rights; it then reads and writes the elevated baseline |
| `baseline` | object | shared contract, "Baseline": `status` (`none`, `compared`, `unreadable`), `created_at`, `age_days`, `saved`, `reason`, `reference` (`latest` or the `--compare-to` value, e.g. `7d`) and `reference_file` (the history copy compared with, or `null`). `created_at` and `age_days` are those of the state compared with |
| `comparison` | object | per item source (`win32_programs`, `msix_programs`, `run_keys`, `startup_folders`, `scheduled_tasks`, `services`, `optional_features`, `capabilities`, `drivers`, `firewall_rules`, `root_certificates`, `hosts`, `administrators`, `defender_exclusions`): `compared`, `no_baseline` or `not_read` (shared contract). A source added to the skill after the baseline was made is `no_baseline` on the first run |
| `truncated_drivers`, `truncated_components`, `truncated_additions` | int | the items cut from `drivers`, `components` and `additions` (see "Files and output"), `0` when none |
| `programs` | list | the programs with `own: false`, newest `install_date` first, no date last, then by name; ids `a..`. Each item is without `install_location`, `source` and `own` (in the detail file). A program that has `per_user_pair` is installed more than once by the same publisher: see "Install pairs". Cut to the budget (`truncated`) |
| `autostart` | list | the autostart entries with `own: false`, by source and key; ids `s..`. Never cut. `approved_raw` and `display_name` are left out, and each fact is without `company`, and without `expanded_path` when it equals `path` (all in the detail file) |
| `components` | list or `null` | the listed components: features with `state` `enabled` and capabilities with `state` `Installed`, features first, each by name; ids `f..`. Each item has only `id`, `key`, `kind` (`feature`, `capability`), `name` and `state`. `null` when neither `optional_features` nor `capabilities` was read. Cut to the budget (`truncated_components`) |
| `component_counts` | object | `feature`: `{enabled, disabled, absent, <any other state>, unread}` counts of all features (`enabled`, `disabled` and `absent` always present; `unread` counts `state` `null`), or `null` when `optional_features` was not read; `capability`: `{<state>: number, ..., unread}` of all capabilities, or `null` when `capabilities` was not read; `drivers_without_inf`: the number of `Win32_PnPSignedDriver` rows without an INF file (for example software devices, or a device without a driver), not device state; device state is measured by `ush-health`; `null` when `drivers` was not read. The rows themselves are `drivers_without_inf_items` of the detail file |
| `drivers` | list or `null` | the drivers whose `own` is not `true` (a third-party `.inf`, or unknown), the classes of `DRIVER_CLASSES_FIRST` (`Display`, case-insensitive) first, then by `provider`, then `device_name`, `null` last; ids `d..`. Each item has only `id`, `key`, `device_name`, `class`, `provider`, `version`, `date` and `signer`. `null` when `drivers` was not read. Cut to the budget (`truncated_drivers`) |
| `additions` | list or `null` | the items of the five added-to-the-system sources whose `own` is not `true`: first those with a change block, then those without, each group by kind in this order: `administrator`, `defender_exclusion`, `root_certificate`, `firewall_rule`, `hosts_entry`; ids `x..` (see "Additions"). `null` when none of the five sources was read. Cut to the budget (`truncated_additions`) |
| `hosts_file` | object | `{exists, path_is_default}` and, when any is `null`, `unread_fields` naming it (see "hosts_file") |
| `own_counts` | object | `programs`: the number of programs with `own: true`; `autostart`: `{kind: number}` of the entries with `own: true`, per `kind`; `unknown`: the number of entries with `own: null`; `drivers`: the drivers with `own: true` (`null` when not read); `firewall_rules`: `{local, app_iso, policy}` numbers of rules with `own: true` per store (`null` when not read); `root_certificates`: the certificates with `own: true` (`null` when not read) |
| `changes` | list | the changes since the baseline whose item is not own on at least one side; ids `c..`. Never cut |
| `own_changes` | object | `{added, removed, changed, by_source}`: the counts of the changes of items that are own on every side they have; those changes are only in the detail file. `by_source` is `{<source>: {added, removed, changed}}` for every item source of `comparison`, zeros included, so the model can say which source they came from (e.g. firewall rules after an update) |

Ids: `a..` programs, `s..` autostart entries, `f..` components, `d..`
drivers, `x..` additions, `c..` changes. The numbers of `a`, `s`, `f`,
`d` and `x` are stable between runs (shared contract, "Ids and --detail"):
the number is not the item's position in its list, so the summary may have
gaps (`a1`, `a5`, ...) and the id of an item that is only in the detail file
does not follow from the list. The map from an item's `key` to its number
is kept in `<data dir>/state/ush-inventory.ids.json` (the same file for a run
with and without administrator rights); a new item takes a number higher than
any given before, and the number of an item that went away is not given
again. A map that cannot be read starts the numbering again and gives a
`stable ids` item in `not_checked`; a map that is not saved gives
`stable ids save`; items whose key came twice in one run get ids kept for that
run only and a `stable ids <letter>` item. The changes `c` are numbered by
position in each run.

### Programs (`a..`)

| Field | Meaning |
|---|---|
| `key`, `source` | the item key and its source (`win32_programs`, `msix_programs`); `source` only in the detail file |
| `own` | `true` only for an MSIX app whose `signature_kind` is listed in `windows-own.json`; always `false` for a Win32 program. Only in the detail file (a summary program is always not own) |
| `per_user_pair` | list of `{id, name}`, sorted by the number in `id` (`a2` before `a10`): the other installs of the same program, with the same name and the same publisher (see "Install pairs"). Absent when the program has no pair, and on every program when `per_user_suffixes.json` could not be used |
| `name`, `version`, `publisher` | as read; for MSIX `publisher` is the `O=` value of the package `Publisher`, else its `CN=` value |
| `install_date` | `YYYY-MM-DD` or `null`. Win32: the registry `InstallDate` when it is `YYYYMMDD`; any other format or no value is `null`, never a guessed date. MSIX: PowerShell 5.1 has no install date, so this is the UTC creation date of the `InstallLocation` folder, which is the install **or the last update** of the current version; `null` when the folder is not there. Not compared |
| `install_location` | the program's folder, or `null`. Only in the detail file |
| `scope` | Win32 only: `machine` (`HKLM`) or `user` (`HKCU`) |
| `system_component` | Win32 only: `true` when `SystemComponent` = 1 (hidden in Settings), otherwise `false` |
| `signature_kind` | MSIX only: `Store`, `System`, `Developer` and so on, as read |
| `from_baseline` | `true` when the subkey could not be opened in this run and the item is the previous baseline's (see "Values not read") |

#### Install pairs

`data/per_user_suffixes.json` is a list of non-empty strings: the name
suffixes of an install for one user (`" (User)"`). A program whose `name`,
without one of these suffixes at its end, equals the `name` of another
program (case-insensitive) with the same publisher gets `per_user_pair` with
every such program, and each of them gets `per_user_pair` with it. The
publishers are compared without surrounding spaces and case-insensitively; a
program with an empty or `null` `publisher` gets no pair, and programs of
different publishers are no pair even with the same name. So `Microsoft Visual Studio Code`
and `Microsoft Visual Studio Code (User)` name each other, and an `(User)`
entry lists both copies of a program installed in `hklm64` and in `hklm32`.
Programs whose names differ in anything else (e.g. the `(x64)` and `(x86)`
redistributables) are no pair. The partner's `name` is in the field because
the partner may be own or cut from the summary. A missing file, invalid JSON
or anything other than a list of non-empty strings gives the `not_checked`
item `per_user_suffixes.json`, and no program has the field: that means "not
checked", not "no pairs".

### Autostart entries (`s..`)

| Field | Meaning |
|---|---|
| `key`, `source` | the item key and its source |
| `kind` | `run`, `run_once`, `startup_folder`, `task` or `service` |
| `location` | the registry key (`HKCU\Software\...\Run`), the Startup folder, the task path, or the service key `HKLM\SYSTEM\CurrentControlSet\Services\<name>` |
| `name` | the value name, the file name, the task name, or the service name (the template name for a per-user service) |
| `command` | raw: the registry value as stored, `<target> <arguments>` of a shortcut, the task actions joined by `; ` (`Execute Arguments`, or `ComHandler <CLSID>`), the service's `PathName` |
| `value_kind` | `run` and `run_once` only: the registry value kind (`String`, `ExpandString`, ...), for a rollback |
| `enabled` | `run`, `run_once`, `startup_folder`: `true` for `approved` `enabled` and `not_set`, `false` for `disabled`, `null` in `unread_fields` for `unknown`. `task`: `State` is not `Disabled`. `service`: always `true` |
| `approved`, `approved_byte`, `approved_raw` | `run`, `run_once`, `startup_folder` only; see "approved" |
| `state` | `task` and `service`: as read (`Ready`, `Disabled`, `Running`, `Stopped`, ...). For a per-user service `Running` when any instance runs, else the state of the first instance by name. Not compared |
| `display_name`, `delayed`, `user_service`, `template_start` | `service` only: the display name (only in the detail file); `delayed` `true` when `DelayedAutostart` = 1; `user_service` `true` for a per-user service; `template_start` the `Start` value of the template key (per-user services only; `null` when not read). A service whose registry values could not be read and that the previous baseline does not have names in `unread_fields` only the fields whose values were not read before the error: `delayed` (then `null`) when `DelayedAutostart` was not read, `user_service` when `Type` was not read; when it runs in `svchost.exe` (its target is a registry value) and its `ServiceDll` is unknown also `targets` and `facts`, and `own` `null`: then it is counted in `own_counts.unknown` and listed only in the detail file (see "Values not read") |
| `targets` | the target files as text, in action order, as taken from `command` before variables are expanded; `null` for a target that cannot be named |
| `facts` | one fact per target, in the same order: `{path, expanded_path, exists, signature_status, signer, company, program}`. In the summary a fact has no `company`, and no `expanded_path` when it equals `path`; the detail file has every field |
| `facts_from_baseline` | `true` when facts are the previous baseline's, because `file_facts` (or one file) could not be read |
| `own` | see "own and windows-own.json"; always `false` in the summary list |
| `unread_fields` | the fields whose value is unknown in this run (`["approved", "enabled"]`, `["enabled"]` for an `unknown` `approved`, `["facts"]`); they are never compared |
| `from_baseline` | `true` when the entry could not be read in this run and is the previous baseline's |

Targets, per kind:

- `run`, `run_once`: the file of `command`: a quoted start is the file; else
  the shortest prefix ending in `.exe .com .bat .cmd .dll .ps1 .vbs .js`
  before a space, a comma or the end; else the first word. A leading
  `\SystemRoot\` becomes `%SystemRoot%\`. `rundll32.exe C:\x\y.dll,Entry`
  gives `rundll32.exe`, the launcher, not the DLL.
- `startup_folder`: the shortcut's target, or the file itself.
- `task`: one target per action: `Execute` of an `Exec` action, the
  `InprocServer32` file of the CLSID of a `ComHandler` action (`null` when
  the CLSID has none).
- `service`: the file of `PathName`; for `svchost.exe` the `ServiceDll` of
  `Parameters` (of the template for a per-user service), else of the service
  key; `null` when neither exists.

Facts: `path` is the target as in `targets`; `expanded_path` is it with
environment variables expanded (a name without a folder is looked up in
`System32`, the Windows folder and `PATH`, as Windows would); `exists`;
`signature_status` from `Get-AuthenticodeSignature` (`Valid`, `NotSigned`,
`HashMismatch`, ...; `null` when the file does not exist); `signer`, the
`O=` of the signing certificate; `company`, `CompanyName` of the file's
version info; `program`, the key of the program (`win32:...` or `msix:...`)
whose `install_location` is the **longest** folder prefix of
`expanded_path`, case-insensitively, else `null`. An `install_location` that
is a drive root, `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%SystemRoot%` or
`System32` never matches. `program` is a match of facts, not a verdict: a
target with `exists: false` and `program: null` is what the model may call
orphaned.

### Components (`f..`)

In the detail file every feature and capability is an item: the listed ones
first (as in the summary), then the rest, each group features first and by
name.

| Field | Meaning |
|---|---|
| `key`, `source`, `kind` | the item key, its source and `feature` or `capability` |
| `name` | the feature's `Name`, the capability's `Name` |
| `caption` | features only: `Caption` (detail file only) |
| `state` | features: `InstallState` 1, 2, 3 as `enabled`, `disabled`, `absent`; any other value (4 is "unknown" to Windows) is `null` with `install_state` holding the number and `unread_fields` `["state"]`. Capabilities: the `State` name as read (`Installed`, `NotPresent`, ...), `null` with `unread_fields` `["state"]` when missing |

Components are never own: every change of one is listed.

### Drivers (`d..`)

| Field | Meaning |
|---|---|
| `key` | `driver:<DeviceID>` |
| `device_name`, `class` | `DeviceName`, `DeviceClass` |
| `inf_name` | `InfName` (detail file only) |
| `provider`, `version`, `signer` | `DriverProviderName`, `DriverVersion`, `Signer` |
| `date` | `DriverDate` as UTC `YYYY-MM-DD`, or `null` |
| `third_party` | `inf_name` matches a pattern of `driver_third_party_inf` (case-insensitive); `null` with `unread_fields` `["third_party"]` when the data file could not be used (detail file only) |
| `own` | the opposite of `third_party`; `false` when `third_party` is `null` (detail file only) |

A `removed` driver is a device that is not present now (unplugged, turned
off, or given another driver), not a driver that was uninstalled; `added`
is a device that appeared.

`drivers_without_inf_items` (detail file only) lists the `Win32_PnPSignedDriver`
rows without an INF file (for example software devices, or a device without a driver; not device state,
which `ush-health` measures), one `{device_name, class}` per row
(`DeviceName`, `DeviceClass`; no device id),
so the report can explain why this number differs from the device problems
of `ush-health`. `null` when `drivers` was not read, `[]` when it was read and
every row has an INF file.

### Additions (`x..`)

Every item has `id`, `key` and `kind`. In the summary a `firewall_rule`
keeps only `store`, `name`, `action`, `dir`, `active`, `protocol`,
`protocol_name`, `lport` and `app`, and a `root_certificate` only `store`,
`subject` (cut to 120 characters), `not_after`, `self_signed` and
`in_authroot`, plus `windows_first_run` when the certificate has that field;
both keep `app_exists` (rules) and `no_block_reason` only when the item has
that field (never as a `null` placeholder); the other kinds keep every field
but `own` and `source`.
`unread_fields` is kept when there are any. The detail file has every field
(plus `source` and `own`).

The listed items are in two groups. The first holds the items for which
`SKILL.md` ("Change blocks") gives a block: every item except those of the
second group. The second holds the items without a block: a `firewall_rule`
with a `store` other than `local`; a `root_certificate` with a `store` other
than `machine_root` and `user_root`, with `in_authroot` `true`, or whose
thumbprint is also in another root store; a `defender_exclusion` with an
`origin` other than `local` (`null` included) or read under a `method` other
than `preference`. An `administrator` is always in the first group, even one
the "Rules" of `SKILL.md` forbid removing: members are few and stay listed.
Every listed item of the second group has `no_block_reason`, the code of the
first condition that holds, in this order:

| `no_block_reason` | Condition |
|---|---|
| `store_app_iso` | a `firewall_rule` in the store `app_iso` |
| `store_policy` | a `firewall_rule` in the store `policy` |
| `cert_other_store` | a `root_certificate` in a store other than `machine_root` and `user_root` |
| `cert_in_authroot` | a `root_certificate` with `in_authroot` `true` |
| `cert_in_several_stores` | a `root_certificate` whose thumbprint is also in another root store |
| `defender_origin` | a `defender_exclusion` with `origin` other than `local` (`null` included) |
| `defender_method` | a `defender_exclusion` read under a `method` other than `preference` |

An item of the first group (and an own item) has no `no_block_reason`.
Each group is ordered by kind, then within a kind; a cut to the budget
takes the second group first, from its end (the ids are stable numbers, not
places in this order).
Within a kind the order is: `administrator` by
`name`; `defender_exclusion` by `value`; `root_certificate` by `subject`,
then `thumbprint`; `firewall_rule` by `store`, then `name`; `hosts_entry`
by `hostname`, then `address` (text case-insensitive, `null` last, the key
breaks ties).

`administrator`:

| Field | Meaning |
|---|---|
| `name`, `object_class`, `principal_source` | as `Get-LocalGroupMember` gives them (`object_class` is in the system language). Under `method: adsi`: `name` from the ADSI path, `principal_source` `null`, both in `unread_fields` |
| `enabled` | from `Get-LocalUser` for a member with `principal_source` `Local` or `MicrosoftAccount`. `null` without `unread_fields` when `Get-LocalUser` found no user with the SID (a group) or the member is of another source; `null` in `unread_fields` when `Get-LocalUser` failed otherwise, or under `method: adsi` for an `object_class` `User` |
| `is_current` | the member's SID is the running account's (`current_sid` of the detail file); `null` in `unread_fields` when `current_sid` was not read |
| `builtin` | `true` for the built-in Administrator account (a SID starting with `S-1-5-21-` and ending with `-500`), else `false`; never `null` (a member without a SID is no item) |

`defender_exclusion`:

| Field | Meaning |
|---|---|
| `type` | `path`, `extension`, `process` or `ip` |
| `value` | as read; the key folds its case |
| `origin` | `policy` when the value is under the policy keys, else `local`; a policy value missing from the effective lists is an item too. `null` in `unread_fields` when the policy keys could not be read (with the `not_checked` item `defender_exclusions origin`) |

`root_certificate`:

| Field | Meaning |
|---|---|
| `store` | `machine_root`, `machine_policy`, `enterprise`, `user_root` or `authroot` |
| `thumbprint` | upper case (detail file only) |
| `subject`, `issuer` | as `Cert:` gives them (`issuer` detail file only) |
| `not_before`, `not_after` | UTC `YYYY-MM-DD` (`not_before` detail file only) |
| `self_signed` | `subject` equals `issuer`; `null` in `unread_fields` when either is unknown |
| `in_authroot` | the thumbprint is also in `authroot` |
| `serial` | the serial number as `Cert:` gives it (hex text, detail file only) |
| `windows_first_run` | only on a certificate that matches an entry of `cert_windows_first_run` (store `machine_root`, `self_signed` `true`, `subject` `CN=<subject_cn>` or starting with `CN=<subject_cn>,`, `serial` in upper case equal to the entry's; an unread field matches nothing) or that an entry of `state/ush-inventory.first-run.json` trusts (see `cert_windows_first_run`). `true` with `own` `true`: the decision in that file trusts the certificate (even when its details are unread now). `false`: it matches but is not trusted (a changed thumbprint, one added after the first run, or several matches on the first run); `own` then follows the other rules and the certificate is listed. `null`, named in `unread_fields`: `ush-inventory.first-run.json` could not be read on this run, on every certificate that matches the list. Absent on every other certificate |

A field `Cert:` did not give (no such certificate, or an error) is `null`
and in `unread_fields`.

`firewall_rule`:

| Field | Meaning |
|---|---|
| `store` | `local`, `app_iso` or `policy` |
| `action`, `dir`, `active`, `lport`, `rport`, `app`, `svc`, `name`, `profile`, `embed_ctxt` | the rule text's `Action`, `Dir`, `Active`, `LPort`, `RPort`, `App`, `Svc`, `Name`, `Profile`, `EmbedCtxt` as text; a key that appears more than once gives a list, a missing key `null` |
| `protocol`, `protocol_name` | `Protocol` as a number, and `TCP` (6) or `UDP` (17), else `null` |
| `lport2` | the values of every other key of the rule text that starts with `LPort` (`LPort2_10`, `LPort2_20`, ...), in key order and in value order within a key, as a list of text; `null` when there is none. Detail file only, not compared |
| `version` | the rule text's version (`v2.xx`, detail file only) |
| `app_exists` | only on a rule whose `app` is not `null`, empty or `System` (any case): `true` when the job `firewall_apps` found a file at the expanded path, `false` only when `Get-Item` said "not found" and listing the parent folder confirms it (Windows PowerShell 5.1 also says "not found" for a file in a folder the account may not read, which gives `null`) (no file at this path in the profile of the running account; a path into another account's profile can give `false`). `null` in `unread_fields` when `app` is a list (the key repeated), the job failed or gave no row for the value, the expanded value still holds a `%` (a variable this account does not know; a raw `%SystemRoot%` is fine), the path is not on a local drive (UNC paths and network drives are not checked, so nothing leaves the machine), or `Get-Item` failed otherwise (e.g. access denied in `WindowsApps`). Not compared |

A value that is not a `v2.` rule text has every field `null` and
`unread_fields` `["rule"]` plus every compared field (`action`, `dir`,
`active`, `protocol`, `lport`, `rport`, `app`, `svc`, `profile`), so a run that
reads it later gives no `changed`.

`hosts_entry`:

| Field | Meaning |
|---|---|
| `address`, `hostname` | the first word of a line (before any `#`) and one further word; a line with several names gives one item per name |
| `line` | the line number (from 1) of the first line with this pair |
| `duplicates` | how many further times the pair occurs after its first place, on later lines or on the same line; above 0 does not by itself mean a second line |

### hosts_file

| Field | Meaning |
|---|---|
| `exists` | the hosts file is there; `false` is read (no entries); `null` when not read |
| `path_is_default` | the raw `DataBasePath` equals `hosts_default_dir` (case-insensitive, a trailing `\` ignored), or its expanded folder equals `hosts_default_dir` with `%SystemRoot%` replaced by the job's `SystemRoot`; `null` when the data file or `DataBasePath` could not be used |
| `unread_fields` | the fields above that are `null`, when any |

The source unreadable: both fields `null` and unread. The file there (or
possibly there) but without its text: the source is `unreadable`, `exists`
keeps what was read and `path_is_default` is `null`. The detail file adds
`raw_dir` (the raw `DataBasePath`), `expanded_dir` and `path`.

### Changes (`c..`)

| Field | Meaning |
|---|---|
| `key`, `source` | the item that changed |
| `change` | `added`, `removed` or `changed` |
| `name` | the item's name (after the change, or before it for `removed`): `name`, for a driver `device_name`, for a certificate `subject`, for a hosts entry `hostname`. A Defender exclusion has no `name`: its path is in `value` (a path key). An `administrators` change has no `name`: a change carries no account name (the account names of the members are only in `additions`) |
| `own` | `true` only when the item is own on every side it has; such changes are only in the detail file |
| `fields` | `changed` only: `{field: {before, after}}` of the compared fields that differ. For `administrators` a changed `name` is `{"changed": true}` without `before` and `after`; `enabled` keeps `before` and `after` |

Within a source the order is added, removed, changed, then by key. Only a
source whose `comparison` is `compared` gives changes.

Compared fields:

| Source | Fields |
|---|---|
| `win32_programs` | `name`, `version`, `publisher` |
| `msix_programs` | `name`, `version`, `publisher`, `signature_kind` |
| `run_keys`, `startup_folders`, `scheduled_tasks`, `services` | `command`, `targets`, `enabled`, and, per target present on both sides, `facts[<path>].exists`, `.signature_status`, `.signer`, `.program` |
| `optional_features`, `capabilities` | `state` |
| `drivers` | `provider`, `version`, `date`, `signer`, `third_party` (not `inf_name`: Windows numbers `oem<N>.inf` anew) |
| `firewall_rules` | `action`, `dir`, `active`, `protocol`, `lport`, `rport`, `app`, `svc`, `profile` |
| `root_certificates` | `subject`, `issuer`, `not_after` |
| `hosts` | none: the key holds the name and the address, and `line` is not compared, so a moved line is no change and any other change is `added` or `removed` |
| `administrators` | `name`, `enabled` |
| `defender_exclusions` | `origin` |

A fact change is named by its target, for example
`facts[C:\Program Files\Invented Editor\tray.exe].signature_status`. A target
added or removed is a change of `targets` only. `install_date`, `scope`,
`state`, `delayed`, `company` and `expanded_path` are not compared. `approved`
is not compared on its own, only through `enabled`: `not_set` becoming
`enabled` is no change.

Not compared in a run: `facts` when `file_facts` was not read (or either
side has `facts` in `unread_fields`); `program` when `win32_programs` or
`msix_programs` was not read, and with `--compare-to` when a program
subkey was taken from the history copy (see below); any field
that either side names in `unread_fields`. A plain `program: null` (no match) is not unread and is
compared.

## approved

The state Task Manager shows for a `Run` value or a Startup file, read from
the `StartupApproved` value of the same name (matched case-insensitively):

| Entry | `StartupApproved` key, value name |
|---|---|
| `run:hkcu\Run:<name>` | `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run`, `<name>` |
| `run:hklm64\Run:<name>` | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run`, `<name>` |
| `run:hklm32\Run:<name>` | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32`, `<name>` |
| `startup:user:<file>` | `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder`, `<file>` |
| `startup:common:<file>` | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder`, `<file>` |

| `approved` | Meaning |
|---|---|
| `enabled` | first byte 2 |
| `disabled` | first byte 3; `enabled` is `false` |
| `not_set` | no such value; Task Manager treats it as enabled |
| `unknown` | `enabled` is `null` and in `unread_fields`: what the byte means is not known. Any other first byte, given in `approved_byte`; or a value that is not binary, with `approved_byte` `null` (and the `not_checked` item `startup_approved <hive>\<key>:<name>`, reason `the value is not binary`) |

An entry with a `StartupApproved` value also has `approved_raw`: the whole
value as lowercase hex without separators (for example
`030000000000000000000000`), or `null` when the value is not binary. It is
in the detail file only (fetch the entry with `--detail`), for a rollback
block. `run_once` entries have no `StartupApproved` counterpart: always
`not_set` and `enabled` `true`.

## own and windows-own.json

`data/windows-own.json` is the only classification. It says what is part of
Windows, never what is unneeded:

| Field | Meaning |
|---|---|
| `msix_signature_kinds` | an MSIX app with one of these `signature_kind` values is `own: true` (`["System"]`) |
| `signer_organizations` | the `O=` values of a Windows signer (case-insensitive) |
| `launchers` | file names that start arbitrary code (`rundll32.exe`, `cmd.exe`, `powershell.exe`, `msiexec.exe`, ...; case-insensitive); a target with one of these names is never own |
| `own_kinds` | the autostart kinds that can be own (`["service", "task"]`) |
| `driver_third_party_inf` | `fnmatch` patterns of a third-party `.inf` name (`["oem*.inf"]`, case-insensitive); a driver whose `inf_name` matches is `third_party` and listed, any other driver is own |
| `firewall_builtin` | `{name_prefix, required_fields}` (`"@"`, `["EmbedCtxt"]`): a rule with every field of `required_fields` in its text and a `Name` that starts with `name_prefix` is own |
| `cert_windows_managed_stores` | stores whose every certificate is own (`["authroot"]`: Windows updates it by itself) |
| `cert_windows_shipped_thumbprints` | `[{thumbprint, subject, source}]`: a certificate in `machine_root` with one of these thumbprints is own; `subject` and `source` (the public Microsoft page that gives the thumbprint, or the plan that added it) only document the entry. The list holds public values, never values read from a machine |
| `cert_windows_first_run` | `[{subject_cn, serial, source}]`: a certificate recognised without a thumbprint, by its subject and serial number (`source`, the public Microsoft page that names it, only documents the entry). The decision is kept in `<data dir>/state/ush-inventory.first-run.json`, shared by the normal and the elevated run: `{schema_version: 1, entries: [{subject_cn, serial, decided_at, matched, unchecked}]}`, one entry per list entry, written by the first run that read the certificates (status `read` or `empty`) with the list usable and the file read or absent. `matched` holds the thumbprints that matched then, `unchecked` the `machine_root` thumbprints whose subject, `self_signed` or serial number was unread so the match was undecided. An entry is never changed. A `windows_first_run` value kept in an older baseline is not read: on a machine without this file the next run makes a new decision from the certificates present then. Exactly one `matched` thumbprint: that certificate is own (`windows_first_run` `true`) on every later run, also with its details unread. None matched: the one certificate of `unchecked` that matches on a later run is own, if exactly one does. Several matched: none is own. Any other matching certificate is listed with `windows_first_run` `false`. An entry added to the list later gets its own decision on the next run, so a certificate already on the machine then is trusted; an entry removed from the list is no longer applied. A bad shape of this list (not a list of objects with non-empty text `subject_cn` and `serial`) is a `not_checked` item `windows-own.json`; every decision in the file is then applied (matched by its subject and serial number) and no new one is made. When the file cannot be read (bad JSON or shape) nothing is decided or written and `not_checked` has the item `first-run certificates`, naming the file and the reason: deleting the file starts a new first run. A failed write of a new decision is the same `not_checked` item; the decision still applies to that run |
| `hosts_default_dir` | the default folder of the hosts file (`%SystemRoot%\System32\drivers\etc`), for `hosts_file.path_is_default` |

An autostart entry is `own: true` only when its `kind` is in `own_kinds` and
it has at least one target, every target is non-null, and for every target
`exists` is `true`, `signature_status` is `Valid`, `signer` is in
`signer_organizations`, and neither the file name of `path` nor that of
`expanded_path` is in `launchers`. Anything else is `own: false`: no file,
no signature, another signer, a `null` target, a launcher. When the facts of
an entry of `own_kinds` could not be read and the baseline had none
(`unread_fields` has `facts`: its files could not be checked, or, for a
service, its registry values could not be read), it is `own: null`: listed
only in the detail file, counted in `own_counts.unknown`, with the
`not_checked` item `autostart facts` giving how many and naming the cause. `run`, `run_once` and `startup_folder`
entries are always `own: false` and always listed, also when they point to a
Microsoft file (OneDrive, Teams, Edge). Win32 programs are never own.
Uncertainty never hides an entry.

A change is listed in `changes` when the item is `own: false` or `own: null`
on at least one side; a change of an item that is `own: true` on every side
it has is only counted in `own_changes`.

Drivers, firewall rules and root certificates are classified only by the
fields above; hosts entries, Administrators members and Defender exclusions
are never own, and components are never own. Store apps' rules in
`app_iso` usually carry `EmbedCtxt` and `Name=@{...}` and are then own. A
listed addition is outside these lists, which says nothing about whether
it is harmful.

When `windows-own.json` cannot be read or has a field of the wrong shape,
nothing is own: every item is listed, every driver has `third_party` `null`
in `unread_fields`, no firewall rule or certificate is own (also in
`authroot`) except a certificate trusted by a decision kept in
`state/ush-inventory.first-run.json`, `path_is_default` is `null`, and
`not_checked` has the item `windows-own.json`.

## Values not read

The general rule is in the shared contract ("Baseline"): a value that could
not be read is taken from the previous baseline by the item key, and only
without a previous value is it `null` and named in `unread_fields`. Per
case:

- A source that is `unreadable`: `comparison` `not_read`, no changes, and
  the baseline keeps its previous items (shared contract).
- `startup_approved` not read: `approved`, `approved_byte`, `approved_raw`
  and `enabled` of each `run` and `startup_folder` entry come from the
  previous baseline; an entry without a previous one has `approved` and
  `enabled` `null` and `unread_fields: ["approved", "enabled"]`.
- A `StartupApproved` value that is not binary: `approved: unknown`,
  `approved_byte: null`, `approved_raw: null` (a reading, not an unread
  field), `enabled` `null` with `unread_fields: ["enabled"]`, and a
  `not_checked` item.
- `file_facts` not read: each target's fact comes from the previous baseline
  by its `path` (`facts_from_baseline: true`, `program` matched again); a
  target without a previous fact makes the entry's `facts` unread
  (`unread_fields: ["facts"]`, fact fields `null`). One file that could not
  be checked (an error for that file only) is handled the same way for that
  target, with the `not_checked` item `file_facts <target>`.
- A program subkey that could not be opened: the `not_checked` item
  `win32_programs key <hive>:<subkey>`; the program is the previous
  baseline's with `from_baseline: true`, or is left out when the baseline had
  none. Only denied subkeys and no program: the source is `unreadable`.
- A Startup shortcut or a task that could not be read: the `not_checked`
  item `startup_folders <key>` or `scheduled_tasks <key>`; the entry is the
  previous baseline's with `from_baseline: true`, or is left out.
- A service whose registry values could not be read: the `not_checked` item
  `services <name>`, reason `registry values not read from <value name> on:
  ...` when the value whose read failed (`ErrorAt`) is known, else
  `registry values not read: ...`; the entry is the previous baseline's with
  `from_baseline: true`. Without a previous entry it is built from
  `Win32_Service` and the registry values read before `ErrorAt` (none when
  the error has no known `ErrorAt`); the values read are `Type`,
  `DelayedAutostart`, `ServiceDll`, `KeyServiceDll`, `TemplateServiceDll`,
  `TemplateKeyServiceDll`, `TemplateStart`, in this order. Fields whose values
  were not read are named in `unread_fields`, so they are not compared and a
  later clean read is no change: `delayed` is `null` and named when
  `DelayedAutostart` was not read; `user_service` is named when `Type` was
  not read (see below) and is never `null`. A service that runs in
  `svchost.exe` has its target in the registry (`ServiceDll`): when a value
  not read comes before the first non-empty one (for an instance the
  template's values first), `unread_fields` also names `targets` and `facts`
  and `own` is `null`: the entry is counted in `own_counts.unknown`, listed
  only in the detail file, and the reason of the `autostart facts` item
  names the registry as the cause. A target read before the error is
  checked as usual, as is any other service's target, its `PathName`.
- A service whose `Type` is not a number (not read, also without an error):
  `user_service` is guessed from the name and named in `unread_fields`. Its
  key is, in this order: the full name when the previous baseline has
  `service:<full name>`; the template (the name without its `_<hex>`
  ending) when the baseline has `service:<template>` with `user_service`
  `true`; the full name when the baseline has `service:<template>`
  otherwise; when the previous baseline has neither key, the same three
  rules with the state compared with (the history copy with `--compare-to`);
  the template when the name ends in `_` and at least 5 hex digits (e.g.
  `_1a2b3`, not `_1` or `_64`); else the full name. With the template's
  entry in either baseline any `_<hex>` ending is enough.

An entry with `from_baseline: true` keeps its previous `facts` and `own`.

With `--compare-to` the run compares with a history copy, not with the latest
baseline these values come from, so a value taken from the latest baseline is
not compared: an item with `from_baseline: true` can be `added` (its key was
seen in this run) but never `changed`; `approved` and `enabled` taken from the
baseline because `startup_approved` was not read are no change; and a fact
taken from the baseline (`facts_from_baseline`) is not compared for its
target. A program subkey, a Startup shortcut or a task seen in this run but
not read, which the latest baseline lacks (or which cannot come from it
because it could not be read), is taken for the comparison from the history
copy as if `from_baseline: true`: it is never `removed` or `changed`. When
such an item is a program subkey (`win32_programs`), every
autostart entry has `program` unread in the comparison: the targets were
matched to the programs of this run, which lack it, so a `program` that
differs from the history copy is no change. The
saved baseline and the lists keep these values as without the flag (such an
item stays left out of them).

## not_checked items of ush-inventory

Besides one item per `unreadable` source (`what` = the source name):

| `what` | When |
|---|---|
| `scheduled_tasks visibility` | a run without administrator rights in which `scheduled_tasks` was read (an `unreadable` source has its own item instead) |
| `win32_programs key <hive>:<subkey>`, `startup_folders <key>`, `scheduled_tasks <key>`, `services <name>`, `file_facts <target>` | one item could not be read (see "Values not read") |
| `startup_approved <hive>\<key>:<name>` | a `StartupApproved` value that is not binary |
| `autostart facts` | entries with `own: null`; the reason gives their number |
| `per_user_suffixes.json` | the suffix file could not be used; no program has `per_user_pair` (see "Install pairs") |
| `windows-own.json` | the data file could not be used; nothing is own except a certificate trusted by a decision kept in `state/ush-inventory.first-run.json` |
| `first-run certificates` | `ush-inventory.first-run.json` could not be read (nothing is decided or written; deleting the file starts a new first run), or a new decision could not be saved (it applies to this run only); the reason names the file |
| `baseline` | the baseline could not be read; it is kept as `.unreadable-<stamp>.json`. Without `--compare-to`: "the baseline could not be read, so nothing was compared"; with it: "the latest baseline could not be read; sources not read in this run keep nothing (the file is kept)", and the comparison with the history copy still takes place |
| `reference baseline` | with `--compare-to`: "the reference baseline <file> could not be read, so nothing was compared" (`baseline.status` `unreadable`) |
| `baseline history` | "history not kept: ...": this run's baseline could not be copied to `state/history/`; "the day copy was kept, but old copies were not removed: ...": the copy was made and only older copies stay past 31 days; `baseline.saved` is not changed by either |
| `baseline save` | this run's baseline was not saved (`baseline.saved` `false`) |
| `stable ids` | `state/ush-inventory.ids.json` could not be read, so the numbering started again; the file is kept as `.unreadable-<stamp>.json` when the new map is saved |
| `stable ids save` | the id map was not saved; this run's ids hold, the next run may give other ones (when the reason starts with "the id map was saved", only its previous copy was not replaced and the next run keeps these ids) |
| `stable ids <letter>` | items whose `key` came twice in this run; the later ones got ids kept for this run only, named in the reason |
| `<source> without <field>` | rows without their key field (`optional_features without Name`, `capabilities without Name`, `drivers without DeviceID`, `firewall_rules without value name`, `root_certificates without thumbprint`, `administrators without SID`); the reason gives their number |
| `defender_exclusions origin` | the policy exclusion keys could not be read, so every exclusion has `origin` `null` |
| `firewall_apps` | the job failed, returned no rows for N programs, or returned no row for some of them; those rules have `app_exists` `null` |
| `summary budget` | the summary is over the budget even with the four cut lists empty |

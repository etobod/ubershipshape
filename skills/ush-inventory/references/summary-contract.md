# Summary contract, ush-inventory (schema_version 1)

The ush-inventory fields of the summary, and the ush-inventory cases of the
shared parts. The shared contract (files and budget, `sources`,
`not_checked`, ids and `--detail`, the baseline, recommendations, the report
profile) is in `<plugin root>/skills/ush-common/references/summary-contract.md`; the report
checker reads the ush-inventory rules from `data/report-profile.json`.

## Files and output

One run of `scripts/inventory.py` writes to `<data dir>` (the data
directory: `--data-dir`, else `USH_DATA_DIR`, else
the plugin data folder (`--default-data-dir`), made absolute at once; see the shared
contract):

- `work/inventory-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same
  text is printed on stdout. The time in the name is UTC.
- `work/inventory-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `elevated`, `sources`,
  `comparison` and the full lists `programs`, `autostart`, `components`,
  `drivers`, `driver_packages`, `additions`, `leftovers`, `vendor_folders` (every folder read, see "Vendor folders") and `changes` (never truncated), with the same ids
  as the summary, plus `vendor_folder_roots`, `hosts_file` (with `raw_dir`, `expanded_dir` and
  `path`), `current_sid`, `drivers_without_inf_items` (see "Drivers") and the package lists
  `pip_packages` and `npm_packages` (every package read, each item with its `key`; see
  "Package managers"). It also holds what the summary leaves out: the
  programs, autostart entries, drivers, firewall rules and certificates
  that are part of Windows, the entries with `own: null`, the components
  that are not listed, the changes of own items, the fields the summary
  drops (a program's `install_location`, `source` and `own`; an autostart
  entry's `approved_raw` and `display_name`, a fact's `company`, `sha256` and
  `sha256_error`, and a
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

To keep the summary within its budget of 35 000 characters eight lists may
be cut from their end, in these stages, each only when the one before it
did not make the summary fit:

| Stage | List | Count key | Cut first |
|---|---|---|---|
| 0 | `changes`, its `pip_packages` and `npm_packages` changes (the last sources, so the end of the list), down to none of them | `truncated_changes` (with `change_counts`) | the end of the change order |
| 1 | `programs`, down to the 20 newest (`PROGRAMS_MIN`) | `truncated` | programs without an install date, then the oldest installs |
| 2 | `vendor_folders`, down to the first 10 (`VENDOR_FOLDERS_MIN`) | `truncated_vendor_folders` | the end of the folder order (by the order of `roots`, then by name) |
| 3 | `driver_packages`, down to the first 10 (`DRIVER_PACKAGES_MIN`) | `truncated_driver_packages` | the end of the package order (`provider`, `original_name`, `version`) |
| 4 | `drivers`, down to the first 10 (`DRIVERS_MIN`) | `truncated_drivers` | the end of the driver order (`Display` drivers lead it) |
| 5 | `components`, down to the first 10 (`COMPONENTS_MIN`) | `truncated_components` | capabilities (they follow the features), then features, each from the end of the name order |
| 6 | `additions`, down to the first 10 (`ADDITIONS_MIN`) | `truncated_additions` | the items without a change block, from the end of their group, then the items with one (see "Additions") |
| 7 | `autostart`, down to the first 20 (`AUTOSTART_MIN`) | `truncated_autostart` | the end of the autostart order |
| 8 | `components`, below the first 10 | `truncated_components` | as in stage 5 |
| 9 | `driver_packages`, below the first 10 | `truncated_driver_packages` | as in stage 3 |
| 10 | `drivers`, below the first 10 | `truncated_drivers` | as in stage 4 |
| 11 | `vendor_folders`, below the first 10 | `truncated_vendor_folders` | as in stage 2 |
| 12 | `additions`, below the first 10 | `truncated_additions` | as in stage 6 |
| 13 | `programs`, below the 20 newest | `truncated` | as in stage 1 |
| 14 | `changes`, down to the first 20 (`CHANGES_MIN`) | `truncated_changes` | the end of the change order, so the collapsed entries at its front go last (a collapsed entry is cut whole) |
| 15 | `autostart`, below the first 20 | `truncated_autostart` | as in stage 7 |
| 16 | `changes`, below the first 20 | `truncated_changes` | as in stage 14 |
| 17 | `components`, `driver_packages`, `drivers`, `vendor_folders`, `additions`, then `programs`, each to nothing | as in stages 8 to 13 | as in stages 8 to 13 |

Stage 0 runs before any other list is cut: the package changes go first,
whatever their number, and the changes of the other sources stay. Stages 1
to 6 keep a short list of each: a list with fewer items than its
minimum keeps them all. Every short list keeps its minimum before any list
goes below it, and `autostart` goes to its short list (stage 7) before any
short list goes below its minimum. Then components go to nothing, then driver
packages and only then drivers, so listed drivers outlast components and the
listed packages (every cut package stays in the detail file and is counted by
`truncated_driver_packages`); then the vendor folders (each not judged folder
repeats the same `not_judged` cause), the additions and last the programs. A
`null` `driver_packages` or `vendor_folders` stays `null` (with its count key
`0`).
Stages 14 to 16 run only when stage 13 did not make the
summary fit, so `autostart` and `changes` are over the budget on their own:
the six lists of stages 1 to 6 then go back to their short lists (`autostart`
stays at its short list of stage 7), and are emptied again only in stage 17,
after `autostart` and `changes`. A cut
`autostart` gets `autostart_counts` (`{kind: number}`) and a cut `changes`
gets `change_counts`
(`{source: {added, removed, changed}}`), the counts of the whole list before
the cut; each is `null` while its list is not cut.

Each count key is always in the summary, `0` when nothing was cut. It counts
the cut items; `truncated_changes` counts the cut changes, a cut collapsed
entry by its `count`, so it adds up with `change_counts`. The
detail file keeps every item; the id of a cut item is its stable number
(see "Ids" below), not a position after the last one in the summary, so only
the detail file gives it: `inventory.py --cut [--detail-file <path>]` lists
the cut items as `{id, list, name}` (the ids in the detail file's `listed`
that the summary of `summary_file` does not hold) without starting any
machine job, and `--detail <id>` fetches one. The detail file's `listed` is
`{list: [id, ...]}`, the ids of the listable items of `programs`,
`autostart`, `components`, `drivers`, `driver_packages`, `additions`,
`vendor_folders` and `changes` before the cut (so a change collapsed into an entry is listed by `--cut`
too) (own
items are never in it), and `summary_file` is the summary of the same run.
A detail file without `listed` or `summary_file`, or a summary that cannot be
read, makes `--cut` exit 1 with the missing field or file on stderr. When the summary does not
fit even with all eight lists empty, nothing is cut (every count is `0`),
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
| `file_facts` | for every target file of the autostart entries: the expanded path, whether it exists, its Authenticode status, signer and company, and the SHA-256 of its bytes (`Get-FileHash`, read-only) | no items: the `facts` of the entries |
| `optional_features` | `Win32_OptionalFeature` (no administrator rights needed) | components (`feature`) |
| `capabilities` | `Get-WindowsCapability -Online`, only with administrator rights; without them the job is not run and the source is `unreadable` with the reason `requires administrator rights (not read in this run, which is not elevated); this is not an empty list` | components (`capability`) |
| `drivers` | `Win32_PnPSignedDriver`, one row per device; a row without `InfName` is no item: `drivers_without_inf` counts the `Win32_PnPSignedDriver` rows without an INF file (for example software devices, or a device without a driver), not device state; device state is measured by `ush-health` | drivers |
| `driver_packages` | the driver store listing as XML (`pnputil /enum-drivers /format xml`, no administrator rights needed; the XML tag names do not depend on the system language), only the third-party packages (published name `oem<N>.inf`, case-insensitive). The job gives `{exit_code, text}`; an exit code other than 0 (e.g. an older Windows that refuses `/format`), a failed job or a text that is no `PnpUtil` XML makes the source `unreadable` with the reason, never `empty`. A store with only Windows packages is `empty` | driver packages |
| `devices` | every device Windows knows, present or not, as XML (`pnputil /enum-devices /drivers /format xml`, no administrator rights needed): per `Device` its `DeviceDescription`, `ClassName`, `Status` and `DriverName`, and for a `Disconnected` device whose `DriverName` is an `oem<N>.inf` its `DEVPKEY_Device_LastRemovalDate` (`Get-PnpDeviceProperty`) as a UTC `YYYY-MM-DD`, else `null`. The instance id is used for that lookup only; it is in no summary or detail field. The job gives `{exit_code, text, last_removal}`; an exit code other than 0, a failed job or a text that is no `PnpUtil` XML makes the source `unreadable` with the reason, never `empty`; a listing without a `Device` is `empty`. Used only for the `device_state` of the driver packages; it has no items, no baseline and no comparison | device states of driver packages |
| `firewall_rules` | the rule values of three `FirewallRules` keys under `HKLM`: `local` (`SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules`), `app_iso` (`...\FirewallPolicy\RestrictedServices\AppIso\FirewallRules`, rules of Store apps) and `policy` (`SOFTWARE\Policies\Microsoft\WindowsFirewall\FirewallRules`) | additions (`firewall_rule`) |
| (job `firewall_apps`, not a source) | the `App` values (text only, not `System`, not empty) of all rules, own ones included, in `work/inventory-<stamp>.firewall_apps.input.json`; each is expanded with `[Environment]::ExpandEnvironmentVariables` and checked with `Get-Item -LiteralPath -Force` in the context of the running account. Not run when no rule has such a value. A failed job, or no rows for a non-empty input, is a `not_checked` item `firewall_apps` | the `app_exists` of the rules |
| `root_certificates` | the thumbprint subkeys of five physical root stores in the registry: `machine_root` (`HKLM\SOFTWARE\Microsoft\SystemCertificates\ROOT`), `machine_policy` (`HKLM\SOFTWARE\Policies\Microsoft\SystemCertificates\Root`), `enterprise` (`HKLM\SOFTWARE\Microsoft\EnterpriseCertificates\Root`), `user_root` (`HKCU\Software\Microsoft\SystemCertificates\Root`), `authroot` (`HKLM\SOFTWARE\Microsoft\SystemCertificates\AuthRoot`); subject, issuer, dates and serial number from `Cert:` | additions (`root_certificate`) |
| `hosts` | the `hosts` file in the folder of `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\DataBasePath` (a missing value fails the job; a missing file is read and holds no entries) | additions (`hosts_entry`), `hosts_file` |
| `administrators` | the members of Administrators (`S-1-5-32-544`) by `Get-LocalGroupMember`, with `Enabled` from `Get-LocalUser` for local and Microsoft accounts; when `Get-LocalGroupMember` fails, ADSI. The source entry has `method`: `local_group_member` or `adsi` (`null` when the job gave nothing) | additions (`administrator`) |
| `defender_exclusions` | only with administrator rights (same reason as `capabilities` otherwise): `Get-MpPreference`, or, when it fails (e.g. another antivirus is active), the value names of `HKLM\SOFTWARE\Microsoft\Windows Defender\Exclusions\*`; in both cases the value names of the policy keys `HKLM\SOFTWARE\Policies\Microsoft\Windows Defender\Exclusions\*`. The source entry has `method`: `preference`, `registry` or `null` (not run or nothing given). A value Defender hides (`N/A: ...`) makes the source `unreadable` | additions (`defender_exclusion`) |
| `pip_packages` | the Pythons registered under PEP 514 (`HKCU\Software\Python` once, `HKLM\SOFTWARE\Python` in the 64-bit and the 32-bit view; job `python_registrations`), and for each the `*.dist-info\METADATA` and `*.egg-info\PKG-INFO` files (the first `Name:` and `Version:` header lines) of `<InstallPath>\Lib\site-packages` and of the per-user `%APPDATA%\Python\Python<XY>[-32]\site-packages` (job `package_folders`, layout `python`). pip and python never run. `read` with at least one Python whose folders were looked at, `empty` with none (no registration, or every one skipped: from the Microsoft Store, without an InstallPath, or without a company or tag, each named in `not_checked`), `unreadable` when the registrations could not be read | `package_managers.pip`, the detail list `pip_packages` |
| `npm_packages` | the npm global prefix: a non-blank environment variable `NPM_CONFIG_PREFIX` (its name in any case; `.npmrc` is then not read), else the first `prefix=` line of `%USERPROFILE%\.npmrc` (spaces around `=` allowed; job `npmrc`), else `%APPDATA%\npm`; the prefix stays raw, its `%VAR%` expanded by the job `package_folders`; then `name` and `version` of each `<prefix>\node_modules\*\package.json` and `<prefix>\node_modules\@<scope>\*\package.json` (job `package_folders`, layout `npm`; a folder without `package.json`, such as `.bin`, is no package; an empty, `null` or non-object `package.json`, or one without a string `version`, is a package with status `unreadable`). npm never runs. `read` with at least one package; `empty` when `node_modules` is missing ("npm not present") or holds no package; `unreadable` when `.npmrc` or the folder could not be read, or when nothing but scope folders that could not be listed came, never `empty` | `package_managers.npm`, the detail list `npm_packages` |
| `vendor_folders` | the direct child folders of the roots of `data/vendor-folders.json` (see "Vendor folders"); `read` when at least one root was listed (each root that could not be listed is a `not_checked` item `vendor_folders <root>`); `unreadable` when the job failed, no root could be listed or the data file could not be used. Not a baseline source: it is not in `comparison` and has no changes | vendor folders |

A missing key (no `StartupApproved` key, no `RunOnce` key, no `Uninstall` key
in `HKCU`) is "nothing there", not an error. A denied key fails the job, and
the source is `unreadable`. Rows came but none of them is an item: `empty`.
Only rows that could not be read: `unreadable`, never `empty`.

Without administrator rights a `scheduled_tasks` source that is `read` goes
with the `not_checked` item `scheduled_tasks visibility`: the task list may miss tasks this
account cannot see, without any error.

For the other sources the same holds: a missing `FirewallRules` key or root
store key is no items, a denied key fails the whole job. For
`optional_features`, `capabilities`, `drivers` and `driver_packages` a job that gave rows but
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
| `driver_packages` | `driver_package:<original name>\|<provider>\|<version>`, case-folded: the published `oem<N>.inf` changes when a package is installed again, and the store often keeps two versions of one package. A second package with the same key is no item of its own: its published name is in `other_published_names` of the first (detail file only) |
| `firewall_rules` | `firewall:<local / app_iso / policy>:<registry value name>`; for `local` the value name is the rule's `-Name` in `Get-NetFirewallRule` |
| `root_certificates` | `cert:<store>:<THUMBPRINT>` (upper case) |
| `hosts` | `hosts:<host name, lower case>:<address>` |
| `administrators` | `admin:<SID>` |
| `defender_exclusions` | `defender:<path / extension / process / ip>:<value, lower case>` |
| `vendor_folders` | `vendor_folder:<path>`, case-folded |
| `pip_packages` | `pip:<company>/<tag>\|<install / user>\|<name>`, the name normalised by PEP 503 (runs of `-`, `_`, `.` as one `-`) and case-folded; for a file that could not be read the name comes from the folder name. A second entry of the same name in one folder (a stale `dist-info`) gets `\|<entry, case-folded>` added; the plain key goes to the higher version |
| `npm_packages` | `npm:<name>`, case-folded: the install name, i.e. the `node_modules` entry (`left-pad`, `@contoso/tool`), which is the package name; the same key when `package.json` could not be read |

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
`components`, `component_counts`, `drivers`, `driver_packages`, `additions`, `hosts_file`, `vendor_folders` or `package_managers`):

| Field | Type | Meaning |
|---|---|---|
| `elevated` | bool | the run had administrator rights; it then reads and writes the elevated baseline |
| `baseline` | object | shared contract, "Baseline": `status` (`none`, `compared`, `unreadable`), `created_at`, `age_days`, `saved`, `reason`, `reference` (`latest` or the `--compare-to` value, e.g. `7d`) and `reference_file` (the history copy compared with, or `null`). `created_at` and `age_days` are those of the state compared with |
| `comparison` | object | per item source (`win32_programs`, `msix_programs`, `run_keys`, `startup_folders`, `scheduled_tasks`, `services`, `optional_features`, `capabilities`, `drivers`, `driver_packages`, `firewall_rules`, `root_certificates`, `hosts`, `administrators`, `defender_exclusions`, `pip_packages`, `npm_packages`): `compared`, `no_baseline` or `not_read` (shared contract). A source added to the skill after the baseline was made is `no_baseline` on the first run |
| `truncated_vendor_folders`, `truncated_driver_packages`, `truncated_drivers`, `truncated_components`, `truncated_additions`, `truncated_autostart`, `truncated_changes` | int | the items cut from `vendor_folders`, `driver_packages`, `drivers`, `components`, `additions`, `autostart` and `changes` (see "Files and output"), `0` when none (also when the list is `null`) |
| `autostart_counts` | object or `null` | `{kind: number}` of the whole `autostart` list when it was cut, else `null` |
| `change_counts` | object or `null` | `{source: {added, removed, changed}}` of the whole `changes` list (a collapsed entry by its `count`) when it was cut, else `null` |
| `collapsed_changes` | int | the changes inside the collapsed entries of `changes` before the budget cut, `0` when none; above 0 the report checker takes the `c..` ids from the detail file, so a report may name a collapsed change by its id |
| `programs` | list | the programs with `own: false`, newest `install_date` first, no date last, then by name; ids `a..`. Each item is without `install_location`, `source` and `own` (in the detail file). A program that has `per_user_pair` is installed more than once by the same publisher: see "Install pairs". Cut to the budget (`truncated`) |
| `autostart` | list | the autostart entries with `own: false`, by source and key; ids `s..`. Cut to the budget (`truncated_autostart`, `autostart_counts`). `targets`, `approved_raw` and `display_name` are left out (each target is a fact's `path`), and each fact is without `company`, and without `expanded_path` when it equals `path` (all in the detail file). Each entry carries `first_seen` (a UTC date `YYYY-MM-DD`) and `passes_seen` (int), also saved with the item in the baseline and never compared (not a `changed` field), counted per privilege level (the normal and the elevated run keep separate baselines). An entry new in this run has today's date and `1`; an entry of the previous baseline keeps its `first_seen` and gets its `passes_seen` + 1. When that baseline had no value (saved before these fields, or `null`), `first_seen` is the date of that baseline's `created_at`, the earliest date the tool can show, and `passes_seen` is `2`, a lower bound. `first_seen_lower_bound` (bool) is `true` for such a date and stays `true` in later runs, `false` for a date the tool saw itself, `null` when `first_seen` is `null`. An entry with `from_baseline` (not read in this run) keeps its baseline values, or `null` for each field its baseline copy lacks. When the previous baseline exists but cannot be read, both are `null` and `not_checked` has the item `autostart first_seen and passes_seen` saying the age is unknown. A count, never a verdict: no threshold is in code |
| `components` | list or `null` | the listed components: features with `state` `enabled` and capabilities with `state` `Installed`, features first, each by name; ids `f..`. Each item has only `id`, `key`, `kind` (`feature`, `capability`), `name` and `state`. `null` when neither `optional_features` nor `capabilities` was read. Cut to the budget (`truncated_components`) |
| `component_counts` | object | `feature`: `{enabled, disabled, absent, <any other state>, unread}` counts of all features (`enabled`, `disabled` and `absent` always present; `unread` counts `state` `null`), or `null` when `optional_features` was not read; `capability`: `{<state>: number, ..., unread}` of all capabilities, or `null` when `capabilities` was not read; `drivers_without_inf`: the number of `Win32_PnPSignedDriver` rows without an INF file (for example software devices, or a device without a driver), not device state; device state is measured by `ush-health`; `null` when `drivers` was not read. The rows themselves are `drivers_without_inf_items` of the detail file; `driver_packages`: the number of third-party driver packages, `null` when `driver_packages` was not read; `driver_packages_by_state`: `{present, non_present, no_device_found, unread}`, every package counted once by its `device_state` (`unread` counts `null`), before the budget cut (the summary list `driver_packages` holds fewer when `truncated_driver_packages` > 0), `null` when that list is `null`; `vendor_folders_read`, `vendor_folders_matched`, `vendor_folders_unmatched`, `vendor_folders_unknown` (`matched` `null`, see "Vendor folders"), `reparse_points` and `installer_guid_folders`: the counts of the top-level folders, all `null` when the data file could not be used or no root could be listed; `vendor_folders_matched`, `vendor_folders_unmatched` and `vendor_folders_unknown` are `null` also when the list `vendor_folders` is `null` because a program source was not read |
| `drivers` | list or `null` | the drivers whose `own` is not `true` (a third-party `.inf`, or unknown), the classes of `DRIVER_CLASSES_FIRST` (`Display`, case-insensitive) first, then by `provider`, then `device_name`, `null` last; ids `d..`. Each item has only `id`, `key`, `device_name`, `class`, `provider`, `version`, `date` and `signer`. `null` when `drivers` was not read. Cut to the budget (`truncated_drivers`) |
| `driver_packages` | list or `null` | the third-party driver packages with `device_state` `non_present` or `no_device_found` (see "Driver packages"): first the `non_present` ones, then those with `no_device_by_nature` `true`, then the rest, each part by `provider`, then `original_name`, then `version` (the budget cuts from the end, so the packages with a device or an owner to name stay longest); ids `o..`. Each item has `id`, `key`, `published_name`, `original_name`, `provider`, `class`, `version`, `date`, `signer`, `device_state`, `owner`, `group` and `no_device_by_nature` (see "Driver packages"), and a `non_present` one `devices`. `null` when `driver_packages` was not read, or when it holds packages and `devices` was not read; `[]` with `truncated_driver_packages` `0` when every package is `present` (or `null`) or the store holds no third-party package. Cut to the budget (`truncated_driver_packages`); with `truncated_driver_packages` above `0` the packages were cut, not absent: give the count, never call the list clean or empty; a `null` list stays `null`. `--block o<n>` prints no removal for any package (`# o<n>: no block: <reason>`) |
| `driver_package_groups` | list or `null` | every third-party driver package counted by its `group` (see "Driver packages"): one entry `{group, count, by_state}` per group that holds a package, by `group`; `by_state` is `{present, non_present, no_device_found, unread}` (`unread` counts `device_state` `null`), of all packages, never cut. `[]` when the store holds no third-party package. `null` when `driver_packages` was not read, or when `data/driver-package-groups.json` could not be used ("Not checked" names the file) |
| `additions` | list or `null` | the items of the five added-to-the-system sources whose `own` is not `true`: first those with a change block, then those without, each group by kind in this order: `administrator`, `defender_exclusion`, `root_certificate`, `firewall_rule`, `hosts_entry`; ids `x..` (see "Additions"). `null` when none of the five sources was read. Cut to the budget (`truncated_additions`) |
| `leftovers` | list | what removed programs left, never cut (see "Leftovers"); ids `l..`; `[]` when nothing is left |
| `vendor_folders` | list or `null` | the top-level folders of the vendor roots that no rule matches, cut to the budget like `driver_packages` (`truncated_vendor_folders`, see "Files and output" and "Vendor folders"): `matched` `false` (no installed program matches) or `matched` `null` with `not_judged` (not judged, because something was not read); ids `v..`; `[]` with `truncated_vendor_folders` `0` when every folder read is matched or a Windows name (with `truncated_vendor_folders` above `0` the folders were cut: give the count, never call the list clean) |
| `hosts_file` | object | `{exists, path_is_default}` and, when any is `null`, `unread_fields` naming it (see "hosts_file") |
| `package_managers` | object | `{pip, npm}`: counts only, the packages are in the detail file (see "Package managers") |
| `own_counts` | object | `programs`: the number of programs with `own: true`; `autostart`: `{kind: number}` of the entries with `own: true`, per `kind`; `unknown`: the number of entries with `own: null`; `drivers`: the drivers with `own: true` (`null` when not read); `firewall_rules`: `{local, app_iso, policy}` numbers of rules with `own: true` per store (`null` when not read); `root_certificates`: the certificates with `own: true` (`null` when not read) |
| `changes` | list | the changes since the baseline whose item is not own on at least one side; ids `c..`. The changes named by a rule of `data/collapsed_names.json` (a list of `{source, collapsed, prefix}`; today the firewall rules whose `name` starts with `ms-resource:`, an unresolved resource string, case-insensitive) are collapsed: one entry `{collapsed, source, change, count}` (e.g. `{collapsed: "ms-resource", source: "firewall_rules", change, count}`) per rule and change type, without an id, ahead of the other changes, so the budget cuts the other changes first; the detail file keeps each with its id. Cut to the budget (`truncated_changes`, `change_counts`) |
| `own_changes` | object | `{added, removed, changed, by_source}`: the counts of the changes of items that are own on every side they have; those changes are only in the detail file. `by_source` is `{<source>: {added, removed, changed}}` for every item source of `comparison`, zeros included, so the model can say which source they came from (e.g. firewall rules after an update) |

Ids: `a..` programs, `s..` autostart entries, `f..` components, `d..`
drivers, `o..` driver packages, `x..` additions, `l..` leftovers, `v..` vendor folders, `c..` changes. The numbers of
`a`, `s`, `f`, `d`, `o`, `x`, `l` and `v` are stable between runs (shared contract, "Ids and --detail"):
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
| `targets` | the target files as text, in action order, as taken from `command` before variables are expanded; `null` for a target that cannot be named. Only in the detail file: in the summary each target is the `path` of its fact |
| `facts` | one fact per target, in the same order: `{path, expanded_path, exists, signature_status, signer, company, sha256, sha256_error, program}`. `sha256` is the lower-case SHA-256 of the file's bytes, or `null` with `sha256_error` saying why (the file does not exist, its existence is not confirmed, the read failed, the job gave no row or no valid hash for it, or the fact was carried from a baseline that holds no hash); it is not compared between runs and is carried from the baseline like the other facts. A fact of a file that could not be checked also has `check_error`, the reason. In the summary a fact has no `company`, `check_error`, `sha256` or `sha256_error`, and no `expanded_path` when it equals `path`; the detail file has every field |
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
`System32`, the Windows folder and `PATH`, as Windows would); `exists`
(`false` only when the path is on a local drive and listing its parent
folder confirms the file is not there, or the parent folder is not there;
`null` when that cannot be confirmed: access denied, a drive not ready, a
network path, a name not found on the search path; each such target is
named in a `not_checked` item `file_facts exists`, one per cause);
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

### Driver packages (`o..`)

The detail file lists every third-party package of the driver store (summary:
only those with `device_state` `non_present` or `no_device_found`), by
`provider`, then `original_name`, then `version`.

| Field | Meaning |
|---|---|
| `key` | `driver_package:<original name>\|<provider>\|<version>`, case-folded |
| `published_name` | `DriverName`: the `oem<N>.inf` name in the store |
| `original_name` | `OriginalName`: the INF file name the vendor gave |
| `provider`, `class`, `signer` | `ProviderName`, `ClassName`, `SignerName` |
| `version`, `date` | the two parts of `DriverVersion` (`MM/DD/YYYY <version>`): the version, and the date as `YYYY-MM-DD`; both `null` and named in `unread_fields` when `DriverVersion` has another shape |
| `device_state` | from the `devices` source, matching a device's `DriverName` to the package's published name (or one of `other_published_names`), case-insensitive: `present` when a device with `Status` `Started`, `Stopped`, `Disabled` or `Problem` names it; else `null` when a device with another or no `Status` names it (it may be present); else `null` when a `Disconnected` device of another `ClassName` than the package's class names it (Windows reuses `oem<N>.inf` numbers, so it is no evidence); else `non_present` when only `Disconnected` devices name it; else `no_device_found`: no device found without administrator rights names it, which is not "no device" (Windows may hold a record a normal read does not show). `null` also for a package of class `Extension` (a device names only its primary INF), for every package when `devices` was not read, and for one with no device when the published name of a copy was not read (`published_name` in `unread_fields`; the key does not use it, so the package is kept); `device_state_reason` (detail file only) then says why |
| `owner` | the package's `provider`; `null` when the provider was not read |
| `group`, `no_device_by_nature` | from `data/driver-package-groups.json`: a list of rules, each with exactly one of `class` or `provider` (as the driver store gives them), a `group` and `no_device_by_nature` (`true` for a package that never has a device of its own, e.g. a file system filter or an antivirus); matched case-insensitively and exactly, each class and each provider in one rule only. A provider rule wins over a class rule (a filter a vendor ships in a device class follows its provider); a package no rule matches is `other` with `no_device_by_nature` `false`. Both `null` for every package when the file is missing or broken (not a list, a rule without `group`, a rule with neither or both of `class` and `provider`, a `no_device_by_nature` that is not `true` or `false`, a class or provider in two rules); `device_state` is kept. A `no_device_by_nature` package with `no_device_found` is owned by its provider, never a leftover |
| `devices` | only for `non_present`: the devices that name the package, each `{device_name, class, status, last_removal}` (`last_removal`: the day Windows last saw the device removed, `YYYY-MM-DD` in UTC, `null` when Windows gives none; never a guess). No instance id |
| `other_published_names` | detail file only, only when the store holds the same key more than once: the other published names |

A `null` `device_state` is never "no device": such a package is not in the
summary list. No state is "safe to remove", and `--block o<n>` prints no removal
for any package: Windows refused every removal tried on this machine although no
device names the package without administrator rights. The signer is a fact; the script does not judge it.
Driver packages are never own: every change of one is listed. A package
installed again under a new `oem<N>.inf` keeps its key and its id; a new
version is an `added` package and the old one `removed` (when the store no
longer holds it).

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

### Leftovers (`l..`)

A program is removed when its key is in a program source of the previous
baseline (of the same elevation) and not in that source now; a source not
read in this run removes nothing, and neither does a program whose display
name (case-insensitive, exact) is installed now under any key (an upgrade
that wrote a new key). The removed programs are kept in
`<data dir>/state/inventory-removed.json`
(`{version: 1, skill, removed: [{key, source, name, publisher,
install_location, first_seen_gone, seen_elevated, hkcu_absent}]}`,
`first_seen_gone` the `YYYY-MM-DD` of the run that first saw the program gone,
`seen_elevated` whether an elevated run found a leftover of it, `hkcu_absent`
whether the last non-elevated run read its HKCU key as absent; reset when one reads it as there or cannot read it). A program leaves the file
when it is installed again, when its `install_location` cannot be matched
(see below) and its registry keys were read as absent (or it has none to
look up), or when a run finds no leftover of it and read everything that
could hold one: its folder read as gone, its registry keys read as absent,
the sources `run_keys`,
`startup_folders`, `scheduled_tasks`, `services`, `file_facts` and
`firewall_rules` read, no autostart entry or firewall rule (not part of
Windows) with a target path that could not be expanded (a variable this
account does not know; it may point into the folder), and, with
`seen_elevated`, the run elevated.
Otherwise it stays, and the `not_checked` item `leftovers <name>` says what
was not read. A program
removed before the first baseline is not known: every run gives the
`not_checked` item `leftovers before the first baseline`. A removed program
with no usable `install_location` (and not in an installed program's folder)
and no registry key of its own to look up gives the `not_checked` item
`leftovers <name>`: nothing of it was looked for. A file that cannot be read
gives the `not_checked` item `state/inventory-removed.json` and only the
programs removed since the last baseline are looked at; it is kept as
`.unreadable-<stamp>.json` when the new file is saved.

Removed programs with one `install_location` (case-insensitive, a trailing
`\` ignored), e.g. the 64-bit and 32-bit entries of one product, are one
leftover (`key` `leftover:location:<folder>`). Removed programs whose
`install_location` cannot be matched give a leftover only through their
registry keys, one per `<publisher>\<name>` (case-insensitive; `key`
`leftover:keys:<publisher>\<name>`). Each leftover is `{id, key, program, other_programs,
first_seen_gone, folder, parts}`:

| Field | Meaning |
|---|---|
| `program` | `{key, source, name, publisher, install_location, first_seen_gone}` of the removed program, or `null` for a group of missing targets |
| `other_programs` | the other removed programs with the same `install_location`, in the shape of `program`; `[]` when none and for a group |
| `first_seen_gone` | the earliest `first_seen_gone` of the programs (here outside the path key `program`, so a report may give it), `null` for a group |
| `folder` | for a group of missing targets: the folder of their first target (a path key), else `null` |
| `parts` | what is left, at least one |

A part is the program's folder, `{kind: "folder", path, exists,
status, reason, files, bytes, newest_write, extensions}`, a registry key,
`{kind: "registry_key", path, exists, status, reason, values, subkeys}`, or an item,
`{kind, key, id, name, path, exists}` plus `reason` `"target file does not
exist"` when `exists` is `false` (the report gives it in the user's
language). The folder is the `install_location`
read by the job `install_folders` (read-only: whether the folder is there,
and for a folder that is: the number of files, their bytes, the newest
`LastWriteTimeUtc` as `newest_write` and the 10 most common extensions as
`[{extension, files}]`; reparse points are not followed). It is a part when
it is there (`status` `read`, `exists` `true`) or could not be read
(`status` `unreadable`, `reason`, counts `null`, also when only a subfolder
was denied: never "empty"); a folder that is gone is not a part. An item is
an autostart entry (`kind` of the entry, `id` `s..`) or a firewall rule
(`kind` `firewall_rule`, `id` `x..`, `path` the expanded `app`).

The registry keys are read by the job `leftover_keys` (read-only, the
64-bit view) for each removed program with a `publisher` and a `name`
(neither holding `\` or a control character; otherwise the `not_checked`
item `leftover_keys <name>`): `HKLM\SOFTWARE\<publisher>\<name>`,
`HKLM\SOFTWARE\WOW6432Node\<publisher>\<name>` and
`HKCU\SOFTWARE\<publisher>\<name>`, the publisher and name exactly as the
uninstall entry gives them. Each row is `{path, exists, status, reason,
values, subkeys}`, matched to the key by `path` (case-insensitive, exact;
other rows are ignored). A key that is there (`status` `read`, `exists`
`true`, `values` and `subkeys` the counts of its values and direct subkeys)
or could not be read (`status` `unreadable`, `reason`, counts `null`; also
the `not_checked` item `leftover_keys <path>`) is a part; a key read as
absent is not. A key alone makes a leftover. A key a program installed now uses is
never a part: one of that program's own candidate keys, or any key of a
removed program with the same `publisher` and the same `name` once a
trailing ` (64-bit)`, ` (32-bit)`, ` (x64)` or ` (x86)` is cut from the
installed name (both case-insensitive; "Foo Pro" does not protect "Foo").
An elevated run's HKCU may be another account's: there an HKCU key read as
absent counts as read only when a non-elevated run has read it as absent
before (`hkcu_absent`); otherwise the program stays (cause "its HKCU keys
were read from the elevated account ..."). A failed job (the
`not_checked` item `leftover_keys`) or a key with no row is not "no key":
the program stays in the state file (cause "its registry keys were not
read").

Only explicit facts make a part:

- an item whose (expanded) target lies under the removed program's
  `install_location`, which is a full path, no drive root, none of the
  folders of `file_facts` (`%ProgramFiles%` and the others), not under the
  Windows folder (`%SystemRoot%`, or `<drive>:\Windows`) and not a folder
  many programs share (`ProgramData`, `Program Files`, `Program Files (x86)`,
  their `Common Files`, `Program Files\WindowsApps`, `Users`, a profile
  (also `Users\Public`), its `Downloads`, `Desktop` and `Documents`, its
  `AppData`, `AppData\Local`, `AppData\Local\Programs`,
  `AppData\Local\Temp`, `AppData\Local\Microsoft`, `AppData\LocalLow`,
  `AppData\Roaming` and `AppData\Roaming\Microsoft` themselves; a folder
  inside them is matched);
- an item whose every target is missing (`exists` `false`, read in this run:
  a fact carried over from the previous baseline does not count) and lies
  under no removed program: grouped by the folder of its first target, `program`
  `null`.

Never a part: an item that is part of Windows (`own: true`); an item with a
target under the `install_location` of a program installed now; anything of
a removed program whose `install_location` is, contains or lies under that
of a program installed now (that program gives no leftover); a missing
target under `%SystemRoot%` (when `%SystemRoot%` is not known, missing
targets are not grouped and the `not_checked` item `leftovers of missing
targets` says how many). A similar name is never a fact. Order: the
programs by `name`, then the groups by folder.

### Vendor folders (`v..`)

The job `vendor_folders` (read-only) lists the direct child folders of each
root of `data/vendor-folders.json` (`{roots, windows_names, vendors}`):
`roots` are paths with environment variables (`%ProgramFiles%`,
`%ProgramFiles(x86)%`, `%ProgramData%`, `%WINDIR%\Installer`), expanded by the
job with `[Environment]::ExpandEnvironmentVariables` in the context of the
running account (a variable left unexpanded or a path that is not rooted makes
the root `unreadable`); `windows_names` are folder names that ship with
Windows (compared case-folded); `vendors` maps a folder name to the exact
publisher names of its vendor. Per child folder the job gives `name`, `path`,
`reparse_point`, `has_entries` (whether the folder holds any file or folder;
`null` with a `reason` when it cannot be listed, never `false`) and
`last_write` (the folder's last write time, UTC, `YYYY-MM-DDTHH:MM:SSZ`).

Left out before matching, never listed: a reparse point (a junction such as
`ProgramData\Application Data`; counted in `reparse_points`), a folder of the
`Installer` root whose name is a GUID in braces (MSI caches by product or
patch code; counted in `installer_guid_folders`), and a name of
`windows_names` (not counted). A row that is not a direct child of its root,
or does not say whether it is a reparse point, is not judged (the `not_checked`
item `vendor_folders rows`).

A folder is matched (`matched` `true`, `matched_by` naming each rule that
holds) when:

- `install_location`: the `install_location` of a program of this run (or,
  for a program source not read in this run, of its baseline items) is the
  folder or lies under it; a location under the Windows folder, a shared root
  such as `C:\ProgramData` or a known profile folder matches nothing;
- `target`: a target path of an autostart entry (run key, startup file,
  scheduled task or service) lies under it;
- `vendor`: `vendors` lists, for the folder's name, a publisher a program has
  (case-folded, exact).

A similar name is never a match. Every other folder is unmatched (`matched`
`false`): no installed program matches it. That is a fact, not a judgement:
the folder may hold data, settings or a shared component. When a source the
`target` rule uses, a program source (`win32_programs` or `msix_programs`, whose
baseline programs then stand in), the target path of an autostart entry, or a
program registry key that is in no baseline was not read, a folder that no rule matches
has `matched` `null` (not judged): it is listed with that `null` and the
cause, never as unmatched (the `not_checked` item `vendor_folders` says why and
how many; counted in `vendor_folders_unknown`): no folder is unmatched because
something was not read.

The summary list `vendor_folders` holds every folder no rule matches: the
unmatched ones (`matched` `false`) and the not judged ones (`matched` `null`),
numbered together, by the order of `roots`, then by name; each item has `id`,
`key`, `path`, `root`, `matched`, `has_entries` and `last_write`; a not judged
item also has `not_judged`, the text of the causes shared by every such folder
(the same text the `not_checked` item `vendor_folders` gives, e.g. `the target
path of 1 autostart entry`); and, when `has_entries` is `null`,
`unread_fields: ["has_entries"]` and `has_entries_reason`. It is `null` when
the data file could not be used, when no root could be listed, or when
`win32_programs` or `msix_programs` was not read and the baseline holds none
of its programs (the `not_checked` item `vendor_folders` names the source).
The list is cut to the budget from its end (stages 2 and 11 of "Files and
output"): `truncated_vendor_folders` counts the cut folders, `--cut` lists
them (`name` the folder name) and the detail file keeps them; a cut folder is
given as a count, its id is never named unless it was fetched with `--detail`.

The detail file's list `vendor_folders` holds every folder read after the
skips, matched ones included, with `id` (`null` unless listed), `key`, `name`,
`path`, `root`, `has_entries`, `reason`, `last_write`, `matched` and
`matched_by`; a report may name a `v..` id from it in an `ush:detail` line.
It is `null` whenever the summary list `vendor_folders` is `null`, never `[]`.
Beside it, `vendor_folder_roots` gives each root of the data file, in its
order, as `{root, expanded, status, reason}` (`status` `read` or
`unreadable`); when the job failed every root is `unreadable` with the job's
reason and `expanded` `null`. `vendor_folder_roots` is `null` only when the
data file could not be used (the roots are then unknown).

This skill has no block for a folder (`--block v<n>` says so).

### Package managers

`package_managers` holds counts; every package is in the detail lists
`pip_packages` and `npm_packages`. Their changes are in `changes` with the
other sources, and because `pip_packages` and `npm_packages` are the last
sources, their changes come last and the budget cuts them first. Newer
versions are not looked up (that needs the network; a later plan of
ush-advice): a count, never a verdict.

`package_managers.pip` is `{status, pythons}`: `status` as the source
`pip_packages`; `pythons` is `[]` when no Python's packages were read: none is
registered, or every registration was skipped, each with its `not_checked`
entry (`what` `Python <tag> from the Microsoft Store (WindowsApps)`; `what`
`pip_packages <company>/<tag>` with a reason naming no InstallPath; `what`
`pip_packages registration` for one without a company or tag), `null` when the registrations
could not be read, else one entry per Python:

| Field | Meaning |
|---|---|
| `python` | `<company>/<tag>` of the PEP 514 registration (`PythonCore/3.12`) |
| `count` | the packages read in both folders; `null` when a folder exists but could not be listed (the folder is in `not_checked`), never `0` |
| `unreadable` | the packages whose metadata file could not be read |
| `folders` | `{install, user}`: `read`, `absent` (the folder does not exist, counted `0`), `unreadable`, or `skipped` (the user folder name is not known from the registration; named in `not_checked`) |

`package_managers.npm` is `{status, prefix_from, count, unreadable}`:

| Field | Meaning |
|---|---|
| `status` | as the source `npm_packages`: `read`, `empty` (no `node_modules` folder: npm not present, or no package in it), `unreadable` |
| `prefix_from` | `NPM_CONFIG_PREFIX` (the environment variable), `npmrc` (a `prefix=` line of `%USERPROFILE%\.npmrc`) or `default` (`%APPDATA%\npm`), in that order; `null` when `.npmrc` could not be read |
| `count` | the packages read; `0` for `empty`; `null` for `unreadable` and when a scope folder (`@<scope>`) could not be listed, never `0` |
| `unreadable` | the packages whose `package.json` could not be read; `null` for `unreadable` |

Items of the detail lists:

| Field | Meaning |
|---|---|
| `key` | see "Keys" |
| `python`, `folder` | `pip_packages`: the Python and `install` or `user`. `npm_packages` has `folder`, the package folder (`<prefix>\node_modules\<name>`, the prefix raw) |
| `name`, `version` | as the metadata says (`Name`/`Version`, `name`/`version`); for a file that could not be read `version` is `null` and named in `unread_fields` (never compared), and `name` is `null` (pip) or the folder entry (npm) |
| `status`, `reason` | `read`, or `unreadable` with the reason |
| `entry` | pip, `unreadable` only: the `dist-info` / `egg-info` entry |
| `from_baseline` | `true` when the folder could not be read in this run and the item is the previous baseline's |

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
| `driver_packages` | `provider`, `class`, `version`, `date`, `signer` (not `published_name`, for the same reason; not `device_state`, `devices`, `owner`, `group` or `no_device_by_nature`) |
| `firewall_rules` | `action`, `dir`, `active`, `protocol`, `lport`, `rport`, `app`, `svc`, `profile` |
| `root_certificates` | `subject`, `issuer`, `not_after` |
| `hosts` | none: the key holds the name and the address, and `line` is not compared, so a moved line is no change and any other change is `added` or `removed` |
| `administrators` | `name`, `enabled` |
| `defender_exclusions` | `origin` |
| `pip_packages`, `npm_packages` | `version` |

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
  target, with the `not_checked` item `file_facts <target>`; after 20 such
  items, one item `file_facts more` gives the number of the rest. In the
  detail file every such fact has `check_error`, the reason it was not checked.
- A file `file_facts` did not see but could not confirm missing (`exists`
  `null`): one `not_checked` item `file_facts exists` per cause, with the
  number of targets and at most 20 of them by name (the rest as "and N more";
  every such fact is in the detail file): not a full path on a local drive, or not confirmed (access denied,
  a drive not ready).
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
| `win32_programs key <hive>:<subkey>`, `startup_folders <key>`, `scheduled_tasks <key>`, `services <name>`, `file_facts <target>`, `file_facts more`, `file_facts exists` | one item could not be read (see "Values not read") |
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
| `driver_packages device_state` | the store holds third-party packages but `devices` was not read: "the devices (source devices) were not read, so no package state is known"; every package has `device_state` `null` and the summary list `driver_packages` is `null`. Or: packages named by a device whose status the script does not know; the reason starts with their number; their `device_state` is `null` and they are in the detail file only |
| `data/driver-package-groups.json` | the groups file is missing or broken; the reason names the file and why. Every package has `group` and `no_device_by_nature` `null` and `driver_package_groups` is `null`; the package states are kept |
| `driver_packages device_class` | packages named only by disconnected devices of which at least one has another class than the package (a reused `oem<N>.inf` number): their `device_state` is `null` with `device_state_reason` starting "a disconnected device of another class names this published name (Windows reuses oem<N>.inf numbers), so it is no evidence" and naming those classes; the reason starts with their number; they are in the detail file only |
| `driver_packages device_state (Extension packages)` | the devices were read, but packages of class `Extension` are not listed per device (a device names only its primary INF): their `device_state` is `null` with `device_state_reason` saying so; the reason starts with their number; they are in the detail file only, and the item is absent when there is none or `devices` was not read |
| `driver_packages published_name` | the devices were read, but packages whose published name (`oem<N>.inf`) was not read on a copy match no device through another published name: their `device_state` is `null` with `device_state_reason` "the published name (oem<N>.inf) of a copy of this package was not read, so it cannot be matched to a device"; the reason starts with their number and names this reason; they are in the detail file only. Counted after matching, so a package matched through another published name is not in it, and the item is absent when `devices` was not read (`driver_packages device_state` covers that) |
| `<source> without <field>` | rows without their key field (`optional_features without Name`, `capabilities without Name`, `drivers without DeviceID`, `driver_packages without OriginalName`, `firewall_rules without value name`, `root_certificates without thumbprint`, `administrators without SID`); the reason gives their number |
| `defender_exclusions origin` | the policy exclusion keys could not be read, so every exclusion has `origin` `null` |
| `firewall_apps` | the job failed, returned no rows for N programs, or returned no row for some of them; those rules have `app_exists` `null` |
| `firewall_rules app_exists` | rules whose `app_exists` is `null` (their `unread_fields` name `app_exists`), one item per reason: the App value repeated, no answer of `firewall_apps`, a variable this account does not know, or a file that could not be checked; the reason names up to 20 rule keys |
| `install_folders`, `install_folders <folder>` | the job failed, or one removed program's folder could not be read; that folder part is `unreadable` |
| `state/inventory-removed.json` | the state file of removed programs could not be read or saved (see "Leftovers") |
| `leftovers <name>` | a removed program with no leftover found is kept in the state file because this run did not read everything that could hold one; the reason says what |
| `leftovers of missing targets` | `%SystemRoot%` is not known in this run, so entries with missing targets were not grouped |
| `summary budget` | the summary is over the budget even with all eight cut lists empty |
| `vendor_folders` | the data file `vendor-folders.json` could not be used (the reason names it; the source `vendor_folders` is `unreadable`); or `win32_programs` or `msix_programs` was not read and the baseline holds none of its programs; or folders that no rule matches are listed with `matched` `null` (not judged) because an autostart source, a target path or a program registry key was not read (the reason names what and how many). The list `vendor_folders` is `null` in the first two cases |
| `vendor_folders <root>` | that root could not be listed; its folders are in no list, those of the other roots are |
| `vendor_folders rows` | child folder rows of the job that are not a direct child of their root or lack `reparse_point`; the reason gives their number |
| `collapsed_names.json` | the collapse rule file could not be used; no change is collapsed in the summary `changes` |
| `Python installs not registered in PEP 514 (venvs, portable builds)` | every run: "not searched" |
| `winget: not read` | every run: "`winget list` may go online and has no offline flag" |
| `other package managers (choco, scoop, cargo, go)` | every run: "not searched" |
| `Python <tag> from the Microsoft Store (WindowsApps)` | a registered Python under `WindowsApps`: "packages not read" |
| `pip_packages <company>/<tag>`, `pip_packages registration` | a registration without company, tag or install path, or a second one with the same company and tag; its packages are not read |
| `pip_packages <company>/<tag> <install / user>` | that folder could not be listed (the Python's `count` is `null`), or the user folder is not known from the registration (`skipped`); its items keep the previous baseline's |
| `npm_packages` | the source is `unreadable`: `.npmrc` or the global `node_modules` folder could not be read (the reason says which); `package_managers.npm.count` is `null`. A missing `node_modules` is no item of this kind: npm is not present at that prefix (see the next row) |
| `npm global packages under another prefix` | `package_managers.npm.status` is `empty`: the global `node_modules` folder of the prefix read (from `NPM_CONFIG_PREFIX`, `.npmrc` or the default) is absent or holds no package: "the prefixes from the global or builtin npmrc and the folder of node.exe (nvm-windows, zip builds) were not searched". Not added with status `read` or `unreadable` |
| `npm_packages <node_modules folder>\@<scope>` | that scope folder could not be listed (the reason says why); its packages keep the previous baseline's items (`from_baseline`), no `npm:@<scope>` item is listed, and `package_managers.npm.count` is `null` |

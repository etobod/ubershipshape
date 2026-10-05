# Summary contract, ush-processes (schema_version 1)

The ush-processes fields of the summary and the detail file, and the
ush-processes cases of the shared parts. The shared contract (files and
budget, `sources`, `not_checked`, ids, recommendations, the report profile) is
in `skills/ush-common/references/summary-contract.md`; the report checker
reads the ush-processes rules from `data/report-profile.json`.

ush-processes is a snapshot of one moment: it keeps no baseline and compares
with no earlier run. In `state/` it reads the ush-inventory baseline and
writes only its id map `state/ush-processes.ids.json` (see "Groups").

## Files and output

One run of `scripts/processes.py` writes to `<data dir>` (the data
directory: `--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`, made absolute at once; see the shared
contract):

- `work/processes-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same
  text is printed on stdout. The time in the name is UTC.
- `work/processes-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `elevated`, `sources`,
  `sorted_by`, `inventory`, and the full lists `processes`, `groups`,
  `ports` and `udp_endpoints` (never truncated). Its groups hold all their
  pids, all their services and their process items (`processes`); command
  lines are only here, never in the summary. `listed` is
  `{"groups": [id, ...], "ports": [id, ...]}`, the ids of all groups and
  ports before the budget cut, and `summary_file` is the summary of the same
  run; `--cut` reads both.

The PowerShell jobs write their results to `work/processes-<stamp>.<job>.json`,
the list of group paths to `work/processes-<stamp>.file_facts.input.json` and
the processes asked for a fallback path to
`work/processes-<stamp>.image_paths.input.json` (raw captures: never read
them). The `image_paths` job also points `TMP` and `TEMP` at `work/` before it
compiles its helper, so the compiler's temporary files stay there. The script changes nothing on the machine
and exits 0 when the collection ran, also when jobs failed.

`--detail <id>` prints the group (`g..`, with its process items) or the TCP
port (`p..`) with that id from the newest `processes-*.detail.json` in
`<data dir>/work/`, and exits 0; an unknown id, or no detail file, exits 1
with a message on stderr. With `--detail-file <path>` (the summary's
`detail_file`) it reads that file instead, so the item comes from the same run
as the summary.

`--cut` prints `{detail_file, summary_file, cut}` for the newest detail file
(or the one given with `--detail-file`, which needs no data directory):
`cut` is a list of `{id, list, name}`, the ids in the detail file's `listed`
that the summary of `summary_file` does not hold. A group's `name` is the
group name; a port's `name` is its protocol, port and process name. It starts
no machine job. A detail file without `listed` or `summary_file`, or a summary
that cannot be read, makes `--cut` exit 1 with the missing field or file on
stderr. `--detail` and `--cut` cannot be used together.

## Sources

`sources` is a list of `{name, status, reason}`, one per job that ran, in this
order (`image_paths` is there only when it ran):

| Source | What is read | Gives |
|---|---|---|
| `processes` | `Win32_Process`: `ProcessId`, `ParentProcessId`, `Name`, `ExecutablePath`, `CommandLine`, `SessionId`, `WorkingSetSize`, `PrivatePageCount`, and `CreationDate` as ISO 8601 UTC text | processes and groups |
| `perf` | `Win32_PerfRawData_PerfProc_Process` without `_Total`: `IDProcess`, `WorkingSetPrivate` (the "Memory" column of Task Manager) | `memory_private_bytes` |
| `owners` | `GetOwner` of every process, each in its own try/catch (`{pid, return_value, domain, user}` or `{pid, error}`) | `owner` |
| `memory` | `Win32_OperatingSystem`: `TotalVisibleMemorySize`, `FreePhysicalMemory`, `TotalVirtualMemorySize`, `FreeVirtualMemory` (KB) | `memory` |
| `services` | `Win32_Service` with `ProcessId` > 0 (`Name`, `DisplayName`, `ProcessId`, `StartMode`) and `Type` from the service's registry key | group `services` |
| `network_profiles` | `Get-NetConnectionProfile`: only `NetworkCategory` of each profile, as text (`{Category}`); no interface name or index | `network_categories` |
| `image_paths` | for every process whose `ExecutablePath` is empty, that is not a pseudo-process and has a `started_at` (input `{ProcessId, CreationDate}`): `OpenProcess` with `PROCESS_QUERY_LIMITED_INFORMATION`, then `QueryFullProcessImageName` (flag 0, a Win32 path as WMI gives it) and `GetProcessTimes` on the same handle; rows `{ProcessId, Path, CreationTime, Error}`, the time in UTC. Runs only when there is such a process | a process `path` with `path_source` `query_image` |
| `file_facts` | for every group path: exists, Authenticode status as text, signer (`O=` of the certificate subject), company (`VersionInfo.CompanyName`); plus the expanded `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%SystemRoot%` and `System32` | group file facts and the folder rule of `program` |
| `tcp_listeners` | `Get-NetTCPConnection -State Listen`: `LocalAddress`, `LocalPort`, `OwningProcess` | `ports` |
| `udp_endpoints` | `Get-NetUDPEndpoint`: the same fields | `udp_bound`, detail `udp_endpoints` |

Both port cmdlets fail when they find nothing; a failure whose
FullyQualifiedErrorId starts with `CmdletizationQuery_NotFound` (in any
system language) is `empty`, not `unreadable`. Each job has its own status:
a failed `udp_endpoints` does not hide the TCP ports, and the other way
round.

`network_profiles` without a connection: Windows PowerShell 5.1 throws an
error of category `ObjectNotFound` with an id starting with
`CmdletizationQuery_NotFound`, which the job turns into no rows (`empty`);
any other error fails the job, including a missing command
(`CommandNotFoundException`, also `ObjectNotFound`).

A row of `image_paths` gives a process its path only when the row has a
full `Path` (with a drive or UNC prefix; a process without an image file
gives a bare name) and a `CreationTime` less than 1 second from the process's
`started_at`; a later or earlier time means the pid was reused by another
process, and the path is not taken. A row with `Error` (e.g. a protected
process without administrator rights), no row, an `empty` job or a failed
job leave the path unread; the paths from WMI never change.

Without administrator rights about two thirds of the processes come with an
empty path and command line and no error, and `GetOwner` works only for the
account's own processes: these fields are `null` and named in
`unread_fields`, the source stays `read`.

## Summary fields

Top level, besides the shared fields (`schema_version`, `skill`
`"ush-processes"`, `generated_at`, `sources`, `not_checked`, `summary_file`,
`detail_file`, `truncated`):

| Field | Type | Meaning |
|---|---|---|
| `elevated` | bool | the run had administrator rights |
| `sorted_by` | string | `memory_private_bytes` when `perf` is `read`, else `working_set_bytes`: the order of `groups`, and the memory column of the report |
| `memory` | object | memory of the machine, below |
| `network_categories` | object or null | network profiles counted per category (`{"Public": 2, "Private": 1}`); `{}` when there is no profile (no connection); `null` when `network_profiles` is `unreadable` |
| `inventory` | object | the ush-inventory baseline read, below |
| `counts` | object | counts over all processes, groups and endpoints, below |
| `groups` | list | groups `g..`, cut from the end to fit the budget (`truncated`) |
| `ports` | list | TCP listening ports `p..` |
| `udp_bound` | list | bound UDP sockets counted per group and scope, no ids |

### memory

`total_bytes`, `available_bytes` (`FreePhysicalMemory`), `used_bytes`
(total - available), `commit_total_bytes`, `commit_available_bytes`,
`commit_used_bytes`, `listed_private_bytes`, and the same values in GB
(`total_gb`, `available_gb`, `used_gb`, `commit_total_gb`,
`commit_available_gb`, `commit_used_gb`, `listed_private_gb`; bytes /
1024^3, rounded to 1 decimal place). `used_percent` and
`commit_used_percent` are `used / total * 100`, rounded to 1 decimal place,
`null` when a part is missing (or the total is 0). The report writes only the
`_gb` and `_percent` values.

When `memory` is not `read` (`unreadable`, or `empty`), all values except
`listed_private_*` are `null`, the percentages included. `listed_private_bytes` is the sum of
`memory_private_bytes` of the groups in the summary (after the cut; a group
with `null` counts 0), and `null` (never 0) when `perf` is not `read` or no group in the summary has
a read value (e.g. a failed `processes` job).

### counts

| Field | Meaning |
|---|---|
| `processes` | process items (all, detail file) |
| `groups` | groups (all, including the ones cut from the summary) |
| `path_unread` | processes with `path` in `unread_fields` |
| `command_line_unread` | processes with `command_line` in `unread_fields` |
| `owner_unread` | processes with `owner` `null` |
| `memory_unread` | processes with `memory_private_bytes` `null` |
| `no_image` | pseudo-processes, `path_kind` `"none"` |
| `ports` | TCP listening ports (all, including any cut from the summary) |
| `udp_endpoints` | UDP endpoints with a port other than 0 (detail `udp_endpoints`) |
| `udp_port_zero` | UDP endpoints on port 0, left out |
| `udp_bound_outside_summary` | UDP endpoints of groups cut from the summary |

### inventory

| Field | Meaning |
|---|---|
| `status` | `none` - no baseline file; `read`; `unreadable` - the file exists but could not be read |
| `reason` | why it is `unreadable`, else `null` |
| `created_at` | ISO 8601 time of the baseline, `null` unless `read` |
| `age_days` | days from `created_at` to `generated_at`, one decimal place, `null` unless `read` |
| `missing_sources` | of `run_keys`, `startup_folders`, `scheduled_tasks`, `services`, `win32_programs`, `msix_programs`, the ones not in the baseline; `null` unless `read` |
| `entries_without_path` | autostart entries (`run_keys`, `startup_folders`, `scheduled_tasks`) with `facts` unread, no facts, or a fact without `expanded_path`; `null` unless `read` |

The file is `state/ush-inventory.json`, or `state/ush-inventory.elevated.json`
for an elevated run (another set of tasks and `HKCU`; the two are never
mixed). It is only read, never changed.

## Process (detail `processes`, and a group's `processes`)

| Field | Meaning |
|---|---|
| `pid`, `name`, `session_id`, `started_at` | from `Win32_Process`; `started_at` is ISO 8601 text or `null` |
| `path_kind` | `"none"` for a pseudo-process, else `"file"` (below) |
| `path`, `command_line` | `null` when empty; then named in `unread_fields`, except for a pseudo-process. An empty `path` may be filled from `image_paths` (Sources) |
| `path_source` | `wmi` (from `ExecutablePath`), `query_image` (from `image_paths`), or `null` when no path was read (also for a pseudo-process) |
| `owner` | `domain\user` when `GetOwner` returned 0 and a user; else `null` and `owner` in `unread_fields` (also for an `{pid, error}` row, a missing row, or a failed `owners` job) |
| `memory_private_bytes` | `WorkingSetPrivate` from `perf`; `null` and unread when there is no row for the pid |
| `working_set_bytes`, `commit_bytes` | `WorkingSetSize`, `PrivatePageCount`; `null` and unread when missing |
| `memory_private_mb`, `working_set_mb`, `commit_mb` | the same in MB (bytes / 1024^2, 1 decimal place) |
| `parent_pid`, `parent`, `parent_gone` | below |
| `ancestors` | names of the parents in turn, at most 6; a pid seen before ends the chain |
| `group` | the id of its group |
| `unread_fields` | the fields above that were not read |

A process has `path_kind` `"none"` only when its path is empty and either
its pid is in `pids` of `data/no-image-processes.json` or its name is in
`names_with_parent_4` there and its parent pid is 4. That data file is the
only classification. A process named `Registry` with another parent and no
path is an ordinary process whose path was not read.

`parent` is `{pid, name}` of the process with `parent_pid` when that process
started no later than the child; then `parent_gone` is `false`. When no
process has that pid, or it started later (the pid was reused),
`parent` is `null` and `parent_gone` `true`. When the child's or the
candidate's `started_at` is `null`, or `parent_pid` itself was not read,
this cannot be decided: `parent` `null`, `parent_gone` `null`. `parent_pid`
0 gives `parent` `null` and `parent_gone` `false`. A `parent_pid` listed in
`data/no-image-processes.json` `pids` is never reused and Windows may report
`System` as starting after its own children, so that parent is taken without
the start-time check (`parent_gone` `false`).

## Groups

Processes are grouped by their path, case-insensitive. Processes whose path
was not read form a group per name with `path_read` `false`, never merged
with a group of a known path; `name` is the bare process name, so two groups
may share a name (one with a read path, one without): tell them apart by `id`
and `path_read`. Pseudo-processes form a group per name with `path_read`
`true`. Groups are ordered by `sorted_by` descending (`null` last), then
name, then first pid.

The `g` ids are stable between runs (shared contract, "Ids and --detail"):
the number belongs to the group's key (its kind `path`, `none` or `unread`
and the path or name, case-insensitive), not to its position in the list, so
the summary may have gaps (`g1`, `g5`, ...) and the id of a group that is only
in the detail file does not follow from the list. The map from key to number
is kept in `<data dir>/state/ush-processes.ids.json` (the same file for a run
with and without administrator rights; a process whose path only an
administrator reads is in an `unread` group without rights and in a `path`
group with them, so it has another `g` id); a new group takes a number higher
than any given before, and the number of a group that went away is not given
again. A map that cannot be read starts the numbering again and gives a
`stable ids` item in `not_checked`; a map that is not saved gives
`stable ids save`; items whose key came twice in one run get ids kept for that
run only and a `stable ids <letter>` item. Ports `p` are numbered by position
in each run.

| Field | Meaning |
|---|---|
| `id`, `name`, `path`, `path_kind` | as above; `name` is the process name of the first pid; `path` `null` for both a group with `path_read` `false` and a pseudo-process group |
| `path_read` | `false` only for a group of processes whose path was not read; `true` for a group with a path and for a pseudo-process group |
| `path_source` | `path_source` of the group's first process (by pid): `wmi`, `query_image` or `null` |
| `count` | processes in the group |
| `pids` | at most 20 in the summary, all in the detail file |
| `memory_private_bytes`, `working_set_bytes`, `commit_bytes` | sums of the known values; `null` (and unread) when none is known |
| `memory_private_mb`, `working_set_mb`, `commit_mb` | the sums in MB, 1 decimal place |
| `memory_unread_count` | processes whose `memory_private_bytes` is `null` |
| `started_at_min` | earliest `started_at`, or `null` |
| `owners` | the owners read, sorted |
| `owner_unread_count`, `command_line_unread_count` | processes with that field not read |
| `parents` | names of the parents outside the group (e.g. `services.exe`, `explorer.exe`) |
| `parent_gone_count` | processes with `parent_gone` `true` |
| `services` | services hosted by a process of the group, below; at most 15 in the summary |
| `services_count` | number of services (all), `null` when `services` is `null` |
| `autostart` | linked ush-inventory entries, below |
| `program` | `{key, name}` or `null`, below |
| `exists`, `signature_status`, `signer`, `company` | file facts, below |
| `started_by` | `service`, `autostart`, `parent`, `unknown` or `null`, below |
| `unread_fields` | fields of the group that were not read: `path` for a group with `path_read` `false`, a memory sum that is `null`, `services`, `autostart`, `program`, the file facts, `started_by` |
| `processes` | detail file only: the process items |

### services

Each item `{name, display_name, start_mode, key}`, sorted by name. `key` is
`service:<Name>`, and for an instance of a per-user service (registry
`Type` with bit 0x80) `service:<template>`, the name without its `_<hex>`
ending. When `Type` was not read, the template key is used only when the
ush-inventory baseline lists `service:<template>` with `user_service` `true`.
A failed `services` job gives every group `services` `null` with `services`
in `unread_fields` (never `[]`, which means "hosts no service"); an `empty`
job gives `[]`.

### autostart and the ush-inventory links

`autostart` is a list of `{key, kind, enabled}`, sorted by key:

- entries of `run_keys`, `startup_folders` and `scheduled_tasks` of the
  baseline with a `facts[].expanded_path` equal to the group path
  (case-insensitive). Entries with `facts` in `unread_fields` are skipped. A
  target whose file name (of `path` or `expanded_path`) is in
  `data/launchers.json` is never matched: it does not tell which process of
  that program the entry started;
- the group's service keys that the baseline lists in its `services`
  source (`kind` from the baseline, else `service`).

`autostart` is `null` with `autostart` in `unread_fields` when the baseline
was not read (`inventory.status` `none` or `unreadable`), when
`launchers.json` could not be read, or when the group's path was not read.
`[]` means "no entry found". A pseudo-process group gets `[]` when the
baseline was read.

`program` is `{key, name}` or `null`:

- `key` is the `program` of the facts of the first matched autostart entry
  (by key) that has one;
- else the key of the `win32_programs` or `msix_programs` item of the
  baseline whose `install_location` is the longest folder prefix of the
  path (case-insensitive, on a `\` boundary). A drive root and the
  expanded `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%SystemRoot%` and
  `System32` never match. This rule needs the baseline and a `read`
  `file_facts` job with those four folders;
- `name` is the `name` of the program item with that key in the baseline,
  `null` when the baseline does not list the key.

`program` is `null` with `program` in `unread_fields` when there is no key
from an entry and the folder rule cannot run (baseline not read, or
`file_facts` not `read`), and always for a group whose path was not read. A
`null` `program` without that is "no program found". A pseudo-process group
has `program` `null`, not unread.

### File facts

`exists`, `signature_status` (text such as `Valid` or `NotSigned`),
`signer` and `company` of the group path:

- a group whose path was not read (`path_kind` `"file"`, `path` `null`)
  and a pseudo-process group have all four `null` without `unread_fields`:
  there is nothing to read (the reason is in `path`);
- `exists` is `false` only when the file was not found; any other error
  checking the file (access denied, a bad path) is a row with an error, and
  all four are `null` and in `unread_fields`. So are they when the job is
  not `read` or has no row for the path;
- `exists` `false` gives `signature_status` `null`, not unread. A
  `signature_status` that is not text (a number), or missing for a file
  that exists, is `null` and unread. `signer` and `company` `null` for a
  checked file mean the certificate or the version info has none.

### started_by

A fact, not a judgement: the first rule that holds, in this order:

1. `services` `null` (not read): `null`.
2. The group hosts a service: `service`.
3. `autostart` `null` (not read): `null`.
4. An `autostart` item has `enabled` `true`: `autostart`.
5. An `autostart` item has `enabled` `null` (its state was not read): `null`.
6. A process of the group has `parent` `null` and `parent_gone` `null` (its
   parent could not be decided): `null`.
7. Every process has a `parent`: `parent`.
8. Otherwise: `unknown`.

A rule whose input was not read is never skipped: the walk stops there with
`started_by` `null` and `started_by` in `unread_fields`, since it is not
known whether the rule would hold. `null` is "not read", `unknown` is a
value. So a group of a service process that also has an autostart entry is
`service`, and a group whose path was not read (so `autostart` `null`) and
that hosts no service is `null`. An entry with `enabled` `false` does not
count as a start.

## Ports and UDP sockets

`scope` of an address (a `%zone` suffix is ignored): `loopback`
(`127.0.0.0/8`, `::1`), `all` (`0.0.0.0`, `::`), otherwise `address`.

`ports` (TCP in state `Listen` only; ids `p1...`): each
`{id, protocol, local_address, local_port, scope, pid, process, group,
group_in_summary}`. `protocol` is `"tcp"`, `process` the process name
(`null` when the pid is not in the process list), `group` the id of the
process's group, always a `g..` id even when that group was cut from the
summary (`null` when the pid is not in the process list), and
`group_in_summary` `false` when the group is not in the summary's `groups`
(`null` when `group` is `null`; summary only). A repeated `(address, port, pid)` within one job (a
dual-stack socket) is one item. Order: `scope` `all`, `address`, `loopback`,
then port, address, pid.

UDP has no listening state, and `Get-NetUDPEndpoint` also returns client
sockets (DNS, QUIC), so UDP endpoints are never ports and are not
"listening". The detail file lists them in `udp_endpoints` as
`{local_address, local_port, scope, pid, process, group}` (no ids; port 0
left out and counted in `counts.udp_port_zero`). The summary's `udp_bound`
counts them per group and scope: `{group, process, scope, count}`, where
`process` is the group's name, or the process name when `group` is `null`.
It holds the groups of the summary and the endpoints without a group; the
rest is counted in `counts.udp_bound_outside_summary`. `udp_bound` is not a
required list.

## not_checked

Besides every `unreadable` source (item `job <source>`):

| `what` | When |
|---|---|
| `no-image-processes.json` | the data file could not be read; no process is a pseudo-process |
| `process rows` | rows of `processes` without a usable or with a repeated `ProcessId` were left out |
| `ush-inventory baseline` | no baseline file, or it could not be read; the reason names the `state` folder |
| `ush-inventory sources` | the baseline lacks some of its sources (`inventory.missing_sources`) |
| `ush-inventory entries without a path` | `inventory.entries_without_path` > 0 |
| `launchers.json` | the data file could not be read (only when the baseline was read); no autostart entry is linked |
| `file_facts files` | the job was read but some group paths have no facts (an error row or no row) |
| `job file_facts` | the job returned no rows at all (`empty`), not even its folders |
| `job image_paths` | the job returned no rows (`empty`) although processes were sent; the reason gives their number. A failed job is the usual `job image_paths` item; a run without such processes has none |
| `network_profiles rows` | rows without a category text were left out of `network_categories` |
| `tcp_listeners rows`, `udp_endpoints rows` | rows without a usable address, port or process id were left out |
| `groups cut from the summary` | `truncated` > 0 |
| `stable ids` | `state/ush-processes.ids.json` could not be read, so the numbering started again; the file is kept as `.unreadable-<stamp>.json` when the new map is saved |
| `stable ids save` | the id map was not saved; this run's ids hold, the next run may give other ones (when the reason starts with "the id map was saved", only its previous copy was not replaced and the next run keeps these ids) |
| `stable ids <letter>` | items whose key came twice in this run; the later ones got ids kept for this run only, named in the reason |
| `ports cut from the summary` | ports were cut, with their number (below) |
| `summary budget` | the summary exceeds the budget and was not cut |

## Budget

The summary stays within 35 000 characters. `groups` is cut from its end
(the groups with the least memory); `truncated` counts the cut groups. They
are in the detail file. The id of a cut group is a stable number that does
not follow from the list; `--cut` lists the cut groups (and any cut ports). The
fields that depend on the cut (`memory.listed_private_*`,
`ports[].group_in_summary`, `udp_bound`, `counts.udp_bound_outside_summary`)
are computed for each size tried, before its length is measured. Only when
the summary does not fit even without any group are `ports` cut from their
end, with the item `ports cut from the summary` giving how many (they are
not counted in `truncated`); then as many groups as fit come back. When it
does not fit even without groups and ports, nothing is cut and the item
`summary budget` is added.

A failed `processes` job gives no processes and no groups, the source
`unreadable` and its `not_checked` item; the script still exits 0.

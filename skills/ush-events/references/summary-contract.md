# Summary contract, ush-events (schema_version 1)

The ush-events fields of the summary, and the ush-events cases of the shared
parts. The shared contract (files and budget, `sources`, `not_checked`, ids
and `--detail`, recommendations, the report profile) is in
`skills/ush-common/references/summary-contract.md`; the report checker reads
the ush-events rules from `data/report-profile.json`.

## Files and output

One run of `scripts/events.py` writes two files to `<data dir>/work/`
(the data directory: `--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`, made absolute at once; see the shared
contract):

- `events-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text is
  printed on stdout. The time in the name is UTC, so names sort by time.
- `events-<YYYYmmdd-HHMMSS>.detail.json` - the detail file: the full lists
  (never truncated) with the same ids as the summary, plus `reliability` and
  `unreadable`; the dump files are under `dump_files`.

To keep the summary within its budget of 35 000 characters only `groups` are
cut, from the end (the rarest); `truncated` counts them. Nothing
else is ever cut. When the summary does not fit even with every group cut
(a window with very many anomalies or boots), it goes out over the limit and
`not_checked` gets one item saying so; the full lists are in the detail file
either way.

## Summary fields

Besides the shared fields (`schema_version`, `generated_at`, `summary_file`,
`detail_file`), a summary has:

| Field | Type | Meaning |
|---|---|---|
| `skill` | string | `"ush-events"` |
| `window` | object | `start`, `end` (ISO 8601, UTC) and `days` (int): the time span read |
| `sources` | list | one entry per capture pass, see below |
| `groups` | list | level 1-3 events grouped by log, provider and Id (known noise excluded), most frequent first; ids `g1`, `g2`, ... |
| `noise` | list | groups that match the known-noise list `data/noise.json`, with `count` and `reason`; ids `n1`, `n2`, ... Noise is counted, never hidden |
| `boots` | list or null | boot sessions; id `b<index>` (`b0` is the part of a session that began before the window). `null` when System pass B was unreadable: sessions are unknown, and every anomaly's `boot` is `null` too |
| `anomalies` | list | bugchecks, unexpected shutdowns, Kernel-Power 41, sleep without wake; ids `a1`, `a2`, ... `boot` of a 6008 is the session of the EventLog 6009 or 6005 right after it, otherwise the session it was read in (the event log writes it before or after the markers of the boot that reports the crash). Never truncated |
| `reliability` | object | the daily Windows stability index from the Reliability Monitor, see below. Always present |
| `reliability_records` | list or null | Reliability Monitor records in the window grouped by source and Id, most frequent first; ids `r1`, `r2`, ... Never truncated. `null` when the records could not be read |
| `dumps` | object | the memory dump settings and files, linked to bugchecks by path, see below. Always present |
| `not_checked` | list | what could not be read or covered, see below. Always present; `[]` means nothing was skipped |
| `truncated` | int | how many groups were left out of the summary to fit the budget (cut from the end, the least frequent). `0` when none. The full list is in the detail file |

### Group

`id`, `provider`, `event_id`, `level` (lowest number seen, 1 = critical),
`log`, `count`, `first`, `last` (ISO 8601, UTC), `sample` (one shortened
message, direction marks removed), and the trend:

- `first_half`, `second_half` (int): events of the group before the window's
  midpoint (`window.start + days/2`) and at or after it; an event exactly at
  the midpoint counts in the second half.
- `trend` (string), the first rule that matches, with the thresholds read
  from the data file `data/trend.json` (`min_count`, `factor`, `min_delta`,
  and `reason` explaining the rule in words):
  1. `unknown`: the group's log has a `coverage_start` in `sources`, or the
     time of its oldest record could not be read (named in `not_checked`),
     so the halves are not comparable (the counts are still given);
  2. `too_few`: `count` < `min_count`;
  3. `rising`: `second_half` >= `factor` x `first_half` and `second_half` -
     `first_half` >= `min_delta`;
  4. `falling`: the same with the halves swapped;
  5. `stable`: anything else.

Noise items and anomalies have no trend. An unreadable or incomplete
`data/trend.json` stops the script with exit code 1 and a message on stderr,
before anything is collected; no summary is written.

### Noise item

`id`, `provider`, `event_id`, `count`, `reason`, `first`, `last`.

### Boot session

`id`, `index`, `start`, `end` (ISO 8601 or `null`), `clean_shutdown`
(`true` with an EventLog 6006, `false` without one when another boot
follows that is not Fast Startup, also when that boot wrote no Kernel-Boot
27 at all; `null` for the last session, which may still be running, for a
session followed by a Fast Startup boot: that shutdown hibernates the kernel
and writes no 6006, so it is unknown, not unclean; and for a session
followed by a boot whose Kernel-Boot 27 had no readable type, since that
boot may have been Fast Startup; and for a session followed by a boot whose
first Kernel-Boot 20 says the last shutdown succeeded (`Properties[0]`
"True") and that holds no EventLog 6008 or Kernel-Power 41: a Fast Startup
or hibernate shutdown after which the image was not loaded, whether the
boot is typed `cold` or has no Kernel-Boot 27; a crash, an EventLog 6008 or
Kernel-Power 41 in the following session, keeps `false` whatever its
Kernel-Boot 20 or boot type says), `boot_type` (`cold` or
`fast_startup`, from the first Kernel-Boot 27 of type 0 or 1 in the session;
`null` without one, always for session 0; a session opened by a
Kernel-Boot 27 of type 1 does not take the next boot's markers: a later
Kernel-General 12, EventLog 6009 or 6005 opens a new session; a session opened by
12, 6009 or 6005 takes a later Kernel-Boot 27 of type 1, and when it had no
typed 27 yet it is named in `not_checked`) and `hibernate_resumes` (the
number of Kernel-Boot 27 of type 2, resumes from hibernation, in the
session; 0 without any; those before the first boot of the window count in
session 0).

### Anomaly

`id`, `kind` (`bugcheck`, `unexpected_shutdown`, `kernel_power_41`,
`sleep_without_wake`), `time`, `boot` (session index), `log`, `record_id`;
a bugcheck also has `bugcheck_code` (e.g. `0x0000019c`, or `null`),
`bugcheck_raw`, `dump_path` (the dump path the bugcheck event names in its
second property, or `null`), `dump` (the id `d<n>` of that file in
`dumps.files` when the link is unambiguous, otherwise `null`; see Memory
dumps) and, when `dump_path` is set, `dump_path_listed` (`true` when the
path lies directly in `minidump_dir` or equals `dump_file`, so the
inventory looked for it; `false` when it lies elsewhere; `null` when the
dump settings are unknown). `sleep_without_wake` is a Kernel-Power 506 with no 507 and
no clean shutdown (6006) after it before the next 506 or the next boot.

### Reliability (stability index)

Read with `Get-CimInstance Win32_ReliabilityStabilityMetrics` (job
`R:metrics`, no elevation). Only measurements at or after `window.start` are
used; the filter is applied by the script, not by the query.

| Field | Meaning |
|---|---|
| `status` | `read`, `empty` (read, the Reliability Monitor recorded nothing) or `unreadable`, as in `sources` |
| `reason` | error text for `unreadable`, otherwise `null` |
| `daily` | list of `{date, index}`, one entry per UTC day (`date` is `YYYY-MM-DD`), oldest first. `index` is the `SystemStabilityIndex` of the day's latest measurement, rounded to 2 places. `[]` when nothing in the window; `null` when `unreadable` |
| `lowest` | `{date, index}` of the lowest `index` in `daily`, the earliest day on a tie. `null` when `daily` is empty or `null` |
| `drops` | list of `{date, index, previous_index}`: every day in `daily` whose `index` is lower than that of the entry before it (`previous_index`). The script compares; the report only picks which to name. `null` when `unreadable` |
| `records_status` | status of the records job (`R:records`): `read`, `empty` or `unreadable` |
| `records_reason` | error text when the records job is `unreadable`, otherwise `null` |

The measurements are roughly hourly; the index runs from 1 to 10 (10 =
stable). The script judges nothing: no threshold marks a day as bad.

### Reliability record group

Read with `Get-CimInstance Win32_ReliabilityRecords` (job `R:records`), only
records at or after `window.start`, grouped by (`SourceName`,
`EventIdentifier`): `id` (`r1`, `r2`, ...), `source`, `event_id`, `count`,
`first`, `last` (ISO 8601, UTC) and `product` (the `ProductName` of the
newest record, shortened like a group's `sample`; `null` without one) and
`products` (how many different `ProductName` values the group holds; a
missing one counts as one value). With `products` > 1 the `count` covers
several applications, and `product` names only the newest one.
Ordered like `groups`: most frequent first, then by source and Id.

### Memory dumps

Read without elevation: the values `CrashDumpEnabled`, `MinidumpDir` and
`DumpFile` under `HKLM\SYSTEM\CurrentControlSet\Control\CrashControl`
(read-only, environment variables expanded), the `*.dmp` files in
`MinidumpDir`, and `DumpFile` if it exists. Each file is opened once to see
whether it can be read; nothing is copied and no content is read.

| Field | Meaning |
|---|---|
| `status` | `read` (files found), `empty` (read, no dump files; also when `MinidumpDir` does not exist, as Windows creates it at the first dump) or `unreadable` (the registry values or the folder could not be read) |
| `reason` | error text for `unreadable`, otherwise `null` |
| `settings` | `crash_dump_enabled` (the raw value), `minidump_dir`, `dump_file` (paths) and `defaulted` (the names of those that were absent and took the Windows default: `7` (automatic memory dump), `%SystemRoot%\Minidump` or `%SystemRoot%\MEMORY.DMP`; a missing value is the default, not "disabled". The `7` for a missing `CrashDumpEnabled` is an unverified assumption about Windows, not a reading). `null` when the registry could not be read |
| `files` | the dump files, oldest `modified` first; ids `d1`, `d2`, ... Never truncated. `[]` for `empty`; for `unreadable` the files that could still be listed |

A file: `id`, `name`, `path`, `size` (bytes), `modified` (ISO 8601, UTC;
`null` when it could not be read or converted),
`readable` (`true` when it could be opened; `false` with `reason`, which
starts with `needs administrator` when access was denied - the file exists
and is locked or protected, it is not missing; a modification time that
could not be converted also gives `false` with a `reason`), `bugcheck` and
`bugcheck_candidates`.

Linking is by path only, never by time: a file and a bugcheck belong
together when the bugcheck's `dump_path` names the file's `path` (compared
case-insensitively, after normalising the path).

- `bugcheck_candidates`: the ids of every bugcheck in the window that names
  the file (`[]` for none).
- `bugcheck`: that id when exactly one bugcheck names the file, otherwise
  `null`. Several candidates are usual for `MEMORY.DMP`, which Windows
  overwrites at each crash: the file holds only the latest one, and which
  that is is not decided by the script.
- A bugcheck's `dump` is set only for such an unambiguous link.

The script does not rate a dump or say whether it should be kept.

Groups and noise come from pass A only. An event found only by pass B (the
boot and crash Ids) feeds `boots` and `anomalies`, never a group, so an
unreadable pass A is not hidden behind a few error groups.

## Sources

One entry per pass:

- `System` pass `A` and `Application` pass `A`: levels 1-3 in the window,
  read separately so a failure of one log does not take the other.
- `System` pass `B`: Ids 12, 20, 27, 41, 506, 507, 1001, 6005, 6006, 6008, 6009
  in the window (boots, boot type, shutdowns, sleep, crashes; most are
  level 4).

Fields, besides the shared `status` and `reason`:

| Field | Meaning |
|---|---|
| `log` | `System` or `Application` |
| `pass` | `A` or `B` |
| `event_count` | number of events read in this pass (`0` for `empty` and `unreadable`) |
| `log_oldest_record` | time of the oldest record in the whole log (any level), or `null` if unknown or the log has no records |
| `coverage_start` | set to `log_oldest_record` when that is later than `window.start`: the log does not cover the start of the window (cleared or overwritten). Set to `window.end` when the log holds no records at all: it covers nothing. Otherwise `null` |

The two Reliability Monitor jobs are not in `sources`: their statuses are
`reliability.status` and `reliability.records_status`.

`empty` means "read, nothing matched". An `empty` source with a
`coverage_start` covers only the time after `coverage_start`, so it must not
be reported as "clean" for the whole window.

`ush-events` (schema_version 1) keeps no baseline.

## not_checked

Items have the shared shape (`what` names the log or check). They are added
for:

- every `unreadable` source (reason = the error text);
- an oldest-record query that could not be read;
- every log whose oldest record is later than the window start
  (`from` = `window.start`, `to` = the oldest record);
- every log that holds no records at all ("<log> log: holds no records at
  all", `from` = `window.start`, `to` = `window.end`);
- events whose time could not be read (one item with their count; the list
  itself is under `unreadable` in the detail file);
- Kernel-Boot 27 events without a readable boot type (one item with their
  count; they are left out of `boot_type` and `hibernate_resumes`);
- boot sessions that a Kernel-Boot 27 of type 1 joined while they had no
  typed Kernel-Boot 27 (one item naming their ids, e.g. "boot sessions b1,
  b4: ..."; that 27 may have been a separate hybrid boot, so their `boot_type`
  and the `clean_shutdown` before them are uncertain; the sessions are not
  split; no item when `boots` is `null`);
- each Reliability Monitor query that could not be read (stability index,
  records), reason = the error text. An `empty` query adds nothing;
- Reliability Monitor measurements or records whose time (or index) could not
  be read (one item each with their count; they are left out);
- memory dumps with `dumps.status` `unreadable` (the registry values or the
  dump folder), reason = the error text. A dump file with `readable: false`
  is not an item here: it is listed in `dumps.files` with its `reason`;
- the summary itself when it is over its size limit with every group cut
  ("summary over its size limit of 35000 characters"; `groups` is empty and
  `truncated` counts them all; nothing else was cut, the full lists are in
  the detail file).

## Ids and --detail

`python -B skills/ush-events/scripts/events.py --data-dir <dir> --detail <id>`
prints the item with that id (`g..`, `n..`, `b..`, `a..`, `r..`, `d..`) from the newest
`events-*.detail.json` in `<dir>/work/` (never from a summary file) and exits 0.
`--detail-file`, errors and exit codes are as in the shared contract.

## dumps.py (copying memory dumps)

`python -B skills/ush-events/scripts/dumps.py --data-dir <dir>` prints the
same inventory as `dumps` (without ids and links) as JSON on stdout,
`{generated_at, inventory}`, and changes nothing. The user runs it with
`--copy` in an elevated PowerShell (see `SKILL.md`); the skill never runs
`--copy` itself.

`--copy` copies each readable dump to
`<dir>/dumps/<stem>-<modified UTC YYYYmmdd-HHMMSS>-<sha256[:12]><ext>`, so
two different `MEMORY.DMP` never share a name:

- the free space of `<dir>/dumps/` is checked first (free >= size);
- the copy goes to a temporary file, is checked, and only then gets its
  name; an existing file of that name is never overwritten;
- `verified` means the size and SHA-256 of the copy equal those of the
  source, both computed in this run, the source hashed again after the copy.
  A copy that fails the check is discarded.

`--delete-source` (only with `--copy`; alone it is an argument error, exit
code 2) removes a source only after a verified copy in this run (including
`already_copied`) and a fresh SHA-256 of the source, right before removal,
that still matches. Every failure keeps the source.

Stdout adds `dumps_dir`, `manifest`, `results` and, when the run stopped,
`error`. One result per inventory file: `name`, `source`, `status`
(`copied`, `already_copied` - a file of that name with the same SHA-256 is
there already - or `not_copied`), `reason` (why, or `null`), `copy` (path
or `null`), `sha256` (of the source, or `null`), `verified`,
`source_deleted` and `source_kept` (`true` unless the source was deleted).

`<dir>/dumps/manifest.json` is a JSON list; each run only appends, and
entries of earlier runs are never changed. It re-reads the manifest right
before each write, so an overlapping run keeps its entries. Fields of an entry: `name`,
`source`, `copy`, `size`, `sha256`, `copied_at` (ISO 8601, UTC),
`verified`, `source_deleted`, `reason`. When an entry is written:

- a copy verified in this run (`copied`) or a matching copy found
  (`already_copied`): an entry with `copy` set and `verified` `true`;
- a copy that was made but failed verification or could not be given its
  name (the copy is discarded): an entry with `copy` `null`, `verified`
  `false` and the `reason`;
- a copy never attempted - the source not readable, its size or time
  unknown, not enough free space, the target name taken by another file,
  no temporary file possible, or the copy function itself failing: no
  entry; the reason is only in the stdout `results`.

With `--delete-source` the entry naming the verified copy is written first
and the source is removed only after that write succeeded (if it fails, the
source is kept and the run stops with `error`). After the removal step the
same entry, written in this run, is rewritten with `source_deleted` and
`reason`; if that rewrite fails, `error` says so and the entry still names
the verified copy with `source_deleted` `false` - the stdout `results` then
hold the real outcome.

A manifest that cannot be read, or is not a JSON list, stops the run with
`error` before any copy and is left unchanged; one that becomes unreadable
during the run stops it at the next write, as a failed write does.

Exit codes: `0` every dump copied and verified (and, with
`--delete-source`, every source deleted); `1` anything else, including an
unreadable inventory or manifest; `2` bad arguments.

## logs.py (exporting and clearing a log)

`python -B skills/ush-events/scripts/logs.py --export <log> --data-dir <dir>`
exports `System` or `Application` (any other name, or `--clear` without
`--export`, is an argument error: exit code 2, nothing runs). It needs no
elevation and writes only under `<dir>`: the file to
`<dir>/exports/<log>-<UTC YYYYmmdd-HHMMSS>.evtx` (an existing file is never
overwritten) and the reads' result files to `<dir>/work/`. With `--clear`
(user-run, elevated, see `SKILL.md`) it then clears that log.

Stdout is one JSON object: `generated_at`, `log`, `exports_dir`, `manifest`,
`clear_requested`, `export`, `clear` and `error` (why the run stopped before
the export or while writing the manifest, else `null`). All paths are
absolute.

`export` (`null` only when the run stopped before it): `log`, `file`,
`verified`, `reason` (why not verified, or `null`), `sha256` (of the file,
or `null` when there is none), `exit_code` (of `wevtutil epl`, `null` when
it did not run), `state_before` (`status` `read` / `unreadable`, `reason`,
`record_count`, `oldest_record_id`, `newest_record_id` of the log before the
export) and `record_count`, `min_record_id`, `max_record_id` read back from
the file (`Get-WinEvent -Path`). `verified` is `true` only when all hold:
`wevtutil epl` exited 0; `min_record_id` <= `oldest_record_id`;
`max_record_id` >= `newest_record_id`; `record_count` = `max_record_id` -
`min_record_id` + 1 (no gap). A log with no records before the export is
not verified (nothing to compare). In a `Circular` log the oldest records
can be overwritten during the export; then `verified` is `false` and the
export should simply be run again.

`clear` is `null` without `--clear` or when the export is not verified
(`wevtutil cl` never runs then). Without administrator rights it is
`{log, cleared: false, reason, record_count_after: null}`, the reason (also
on stderr) says an elevated console is needed, and the export stays.
Otherwise the script runs
`wevtutil cl <log> /bu:<dir>/exports/<log>-<stamp>-rest.evtx` - the backup
holds the whole log at the moment of clearing, including records written
after the export - and `clear` has `log`, `cleared`, `reason`, `exit_code`,
`file` (the `-rest` file), `sha256`, `backup_record_count`,
`backup_min_record_id`, `backup_max_record_id` and `record_count_after`
(the log's `RecordCount` read back after clearing). `cleared` is `true`
only when `cl` exited 0, the `-rest` file can be read and hashed, its largest
`RecordId` is >= the export's `max_record_id`, and the log was read back
holding fewer records than the `-rest` file (records written after clearing
are allowed); otherwise `false` with every failed check in `reason`. So
`cleared` means "cleared and confirmed". The printed JSON decides the
result; the manifest entry has no `clear` fields. With `exit_code` `null`
(never run) nothing was cleared. With `exit_code` not `null` and
`record_count_after` `null` (the log was not read back)
whether the log was cleared is unknown: the `reason` says why. Otherwise `record_count_after`
is compared with `backup_record_count`, or with the export's
`record_count` when `backup_record_count` is `null`. With `exit_code` `0`,
below it the log was cleared (with `cleared` `false` only a check after it
failed), and not below it `wevtutil cl` reported success while the log
still holds its records. With a non-zero `exit_code` (`wevtutil cl` failed
or was stopped by a timeout), not below it most likely nothing was
cleared, and below it whether the log was cleared is unknown: a full
`Circular` log can lose a few records to overwriting on its own.

`<dir>/exports/manifest.json` is a JSON list; each run only appends, and it
re-reads the manifest right before each write, so an overlapping run keeps
its entries. Fields
of an entry: `log`, `kind` (`export` or `clear_backup`), `file`, `sha256`,
`record_count`, `min_record_id`, `max_record_id` (read back from the file),
`verified`, `reason`, `written_at` (ISO 8601, UTC). An entry is written for
every export file that `wevtutil epl` wrote (exit code 0), verified or not,
before any clearing; and for every `-rest` file, with `verified` `true` when it was
read back and ends no earlier than the export. A manifest that cannot be
read, or is not a JSON list, stops the run with `error` before any command
and is left unchanged.

Exit codes: `0` the export is verified (and, with `--clear`, `cleared` is
`true`); `1` anything else, including clearing refused without
administrator rights; `2` bad arguments.

## Recommendations (written by the model in the report)

Fields and weights are in the shared contract.

Archiving memory dumps (`dumps.py --copy`) is a `change` with:

- `risk`: the copies take disk space in the data directory (as much as the
  dumps, `size` in `dumps.files`); with `--delete-source` the original is
  gone, and only the verified copy remains;
- `evidence`: the dump ids (`d1`) and, when linked, their bugcheck (`a2`);
- `permissions`: administrator (an elevated PowerShell, run by the user);
- `rollback`: the copy stays; deleting the original is irreversible (it can
  only be copied back from the archive by hand).

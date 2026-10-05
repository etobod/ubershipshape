# Summary contract, ush-files (schema_version 1)

The ush-files fields of the summary and the detail file, and the ush-files
cases of the shared parts. The shared contract (files and budget, `sources`,
`not_checked`, ids, baseline, recommendations, the report profile) is in
`skills/ush-common/references/summary-contract.md`; the report checker
reads the ush-files rules from `data/report-profile.json`.

## Files and output

One run of `scripts/files.py` writes to `<data dir>` (the data directory:
`--data-dir`, else `USH_DATA_DIR`, else `%LOCALAPPDATA%\ubershipshape`,
made absolute at once; see the shared contract):

- `work/files-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text
  is printed on stdout. The time in the name is UTC.
- `work/files-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `elevated`, `scan`, `sources`,
  `comparison`, `drives`, the full lists `folders`, `large_files`,
  `changes`, `not_compared`, `cleanup` and `unreadable` (never truncated),
  and `summary_file`, the summary of the same run.
- `state/ush-files.json` (`ush-files.elevated.json` with administrator
  rights) - the baseline (see "Baseline and comparison").

The script changes nothing on the machine and starts no PowerShell. It
reads directories with `os.scandir` and the cached find data of each entry,
so no file is opened. It exits 0 when the walk ran, also when directories
could not be read; it exits 2 (nothing walked, nothing written) when
`data/scan.json` or `data/cleanup.json` is not usable.

`--detail <id>` prints the folder (`f..`), large file (`l..`), change
(`d..`) or cleanup item (`c..`) with that id from the newest
`files-*.detail.json` in `<data dir>/work/`, and exits 0; an unknown id, or
no detail file, exits 1 with a message on stderr. With
`--detail-file <path>` (the summary's `detail_file`) it reads that file
instead and needs no data directory. The ids are places in the lists of
one run, so fetch from the same run as the summary.

`--block <id>[,<id>]` prints the PowerShell block of each named cleanup
entry (a catalogue id such as `temp-user`, or a `c` id in catalogue order)
after a `#` line with its id, what it is, its risk, the shell it needs, its
conditions and its rollback, and exits 0. It needs no data directory, reads
nothing on the machine and writes nothing. An unknown id exits 1; an
unusable catalogue exits 2.

## Scan settings

`data/scan.json`: `depth` (folder records to that depth; the drive root is
depth 0), `large_file_bytes` (the large-file threshold), `summary_folders`,
`summary_large_files` and `summary_changes` (how many of each list the
summary holds at most). The summary repeats the first two as
`scan: {depth, large_file_bytes}`.

## The walk

Every fixed drive (`GetDriveTypeW` 3; a `subst` drive is left out) is
walked from its root:

- a directory that is a junction, mount point or symbolic link (a reparse
  tag with the name-surrogate bit) is not entered (`counts.reparse_skipped`);
- a directory with `FILE_ATTRIBUTE_RECALL_ON_OPEN` is not entered, because
  listing it makes the sync provider fetch it (`counts.cloud_only_dirs`);
- a file with `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` or
  `FILE_ATTRIBUTE_OFFLINE` is not on the disk: it counts in the folder's
  `cloud_only_files`, never in `bytes`, `files` or the large files;
- a directory that disappears during the walk is left out
  (`counts.vanished_dirs`) and is not unreadable;
- a directory that cannot be listed is unreadable: it goes to the detail
  list `unreadable` (`drive`, `path`, `reason`) and to the `unreadable_dirs`
  of every folder above it.

Sizes are the `st_size` of each file. A file with several hard links counts
in full under every path that reaches it, and a sparse or compressed file
counts at its full size, so folder sizes (and their sum, `scanned_bytes`)
can exceed what the drive really uses. The drive's `used_bytes` is the real
use.

## Top-level fields

Besides the shared fields (`schema_version`, `skill` `"ush-files"`,
`generated_at`, `sources`, `not_checked`, `summary_file`, `detail_file`,
`truncated`):

| Field | Meaning |
|---|---|
| `elevated` | the run had administrator rights |
| `duration_s` | seconds the run took |
| `scan` | `{depth, large_file_bytes}` of this run |
| `baseline` | the shared baseline object |
| `comparison` | `{sources: {source name: state}, previous_at, age_days}` |
| `counts` | see below |
| `drives`, `folders`, `large_files`, `changes`, `cleanup` | the lists below |
| `truncated_folders`, `truncated_large_files`, `truncated_changes` | items of each list left out of the summary, by the limit of `scan.json` or by the budget; `truncated` repeats `truncated_folders` |

`counts`: `drives`, `folders` (folder records), `dirs_listed`, `files` (on
the disk), `large_files`, `cloud_only_files`, `cloud_only_dirs`,
`reparse_skipped`, `vanished_dirs`, `unreadable_dirs`, `changes`,
`not_compared`. They count the main walk only; each cleanup item has its
own figures.

## Sources

`sources` is a list of `{name, drive, status, reason}`, three per fixed
drive of the run:

| Source | Status |
|---|---|
| `folders:<L>` | the walk of drive `<L>`: `read`, `empty` (the root holds nothing) or `unreadable` (the root could not be listed) |
| `large_files:<L>` | `read` when the drive has a large file, `empty` when it has none, `unreadable` with the root |
| `drives:<L>` | the drive's total, used and free bytes: `read` or `unreadable` |

## Drives

`drives`, one item per fixed drive: `letter`, `total_bytes`, `used_bytes`,
`free_bytes` and their `_gb` fields (one decimal; `null` when the usage was
not read), `scanned_bytes`, `scanned_gb` and `scanned_files` (the files on
the disk the walk found), `cloud_only_files`, `unreadable_dirs`. When the
drive root could not be listed (`folders:<L>` `unreadable`) nothing of the
drive was walked: `scanned_bytes`, `scanned_gb`, `scanned_files` and
`cloud_only_files` are `null`, not 0.

## Folders (ids f)

Every folder to `depth` has a record; what lies deeper rolls up into its
ancestor at `depth`, and every record rolls up into its parent. The list is
sorted by `bytes`, largest first; the ids follow that order.

Summary fields: `id`, `path`, `depth`, `bytes`, `gb`, `files`,
`cloud_only_files`, `listed` (the directory itself was listed),
`readable_part` (`true` when a directory in or under it could not be
listed: the sizes count only the readable part). The detail item adds
`drive`, `cloud_only_bytes`, `skipped` (`reparse` or `cloud_only` for a
directory that was not entered: `listed` `false`, `bytes` 0, its size not
read), `unreadable_dirs`, `unreadable_key` and `skipped_key` (the SHA-256 of
the lower-case paths of the unreadable, or skipped, directories in and under
it, sorted and joined with a newline; `null` when there is none).

## Large files (ids l)

Files of at least `large_file_bytes` on the disk, largest first: `id`,
`path`, `drive`, `depth`, `bytes`, `gb`, `modified` and `created` (UTC ISO
8601, `null` when not known).

## Baseline and comparison

The baseline (`skills/ush-common/scripts/baseline.py`) has these sources:

| Source | Key | Compared fields |
|---|---|---|
| `folders:<L>` | lower-case path | `bytes`, `files` |
| `large_files:<L>` | lower-case path | `bytes`, `modified` |
| `drives:<L>` | the letter | `used_bytes` |
| `scan_settings` | the letter | none: the `depth` and `large_file_bytes` the drive was walked with |

The other fields of an item (`listed`, `unreadable_key`, `skipped_key`,
`created`, `parent_path`, `parent_key`) serve the rules below and never give
a change. A drive that is not a fixed drive of this run has no status: its
sources are `not_read`, keep their items, and `not_checked` names the drive.

The comparison states are the shared ones (`compared`, `no_baseline`,
`not_read`) plus `settings_changed`: when this run's `depth` differs from the
one in `scan_settings` for the drive, `folders:<L>` gets it; when
`large_file_bytes` differs, `large_files:<L>` gets it. Such a source gives no
changes, and `not_checked` has an item with `sources`, `previous_settings`
and `settings`. The next run with the same settings compares again. A
baseline without `scan_settings` is compared as before.

## Changes (ids d)

Sorted by the absolute `delta_bytes`, largest first. Fields: `kind`,
`path`, `drive`, `depth`, `before_bytes`, `after_bytes`, `delta_bytes`,
`delta_gb` (one decimal, so a change under about 50 MB reads `0.0`),
`delta_mb` (`delta_bytes` in MB, 1 MB = 1048576 bytes, one decimal, signed
like `delta_bytes`), `readable_part` (the folder has unreadable directories, the same
in both runs, so the change covers the readable part);
`large_file_changed` also has `before_modified` and `after_modified`.

| `kind` | Meaning |
|---|---|
| `folder_grew`, `folder_shrank` | `bytes` of a folder differ |
| `folder_new`, `folder_gone` | a folder record appeared or went away; only the topmost one gives a change, the folders under it are part of it |
| `large_file_new`, `large_file_gone` | a file entered or left the large-file list |
| `large_file_changed` | `bytes` or `modified` of a large file differ; also a file of the previous list that is still on the disk but now below the threshold |
| `drive_used_changed` | `used_bytes` of the drive differ (`path` is the root) |

A new item has `before_bytes` `null`, a gone one `after_bytes` `null`.

A large file whose `bytes` are the same in both runs and whose `modified`
moved by exactly one hour (3600 seconds, either way) gives no change: a FAT
drive keeps local times, so after a daylight-saving switch every file on it
reads one hour off without being written.

A gone large file and a new one on the same drive with the same `bytes` and
the same known `created` look like one file moved or renamed (a move keeps
the creation time): neither is a change, so a file still on the disk never
reads as freed space; both paths are not compared (see below). A gone file
with no such partner stays `large_file_gone`.

## Not compared

Whatever differs but cannot be compared without a false alarm gives no
change: it counts in `counts.not_compared`, is listed in the detail
`not_compared` (`drive`, `kind` `folder` or `large_file`, `path`, `reason`)
and named in a `not_checked` item per drive (`what` `comparison on drive
X:`, `count`, the first `paths`), whose `reason` names every kind below in
short, among them "a gone and a new large file look moved or renamed (same
size and creation time)" and "a new or gone folder was skipped or could not be listed".
The reasons:

- a directory in or under a folder was unreadable or skipped (junction,
  cloud only) in only one of the two runs (`unreadable_key` or `skipped_key`
  differ), so its sizes are not comparable;
- the folder that holds a new or gone folder or large file was listed in
  only one of the two runs; for a file deeper than `depth`, its ancestor at
  `depth` must be listed in both and hold the same unreadable and skipped
  directories;
- a new or gone folder was skipped (junction, cloud only), so its size was
  not read;
- a new or gone folder could not itself be listed (`listed` `false`), so its
  size was not read ("it could not be listed, so its size was not read");
- a large file of the previous run is now only in the cloud;
- a large file new to the list was created (`created`) before the previous
  run: it existed then below the threshold or in another folder, and its
  earlier size is not known. Without a creation time it is `large_file_new`;
- a gone and a new large file on the same drive have the same `bytes` and the
  same known `created`: "it looks moved or renamed: a large file with the
  same size and creation time is at <the other path>" (each names the other);
- the baseline item is malformed (no text path, or a size or time of the
  wrong type).

## Cleanup (ids c)

`data/cleanup.json` holds `{"entries": [...]}`; every entry has `id`,
`what`, `paths`, `min_age_days`, `risk` (`low`, `medium`, `high`),
`needs_admin`, `conditions`, `rollback` and `block` (a PowerShell block),
and may have `ignore_names` (a list of file names, any case, that the
measurement does not count: `recycle-bin` has `desktop.ini`, which Windows
keeps in the bin folder of every account, so an otherwise empty bin is
`empty`). `%NAME%` in a path comes from the environment; `<drive>` stands for each
fixed drive of the run. Each entry is measured apart from the main walk,
with the rules of its block: it enters no reparse-point folder at all
(`FILE_ATTRIBUTE_REPARSE_POINT` or a reparse tag: a junction, a symbolic
link, and also a folder with a cloud reparse tag that the main walk
enters) and no cloud-only folder, and leaves cloud-only files out; such a
subfolder is left out of the sizes without a note, as the block leaves it
alone. A subdirectory that disappears is left out. Nothing is deleted.

Summary item, in catalogue order (never cut by the budget):

| Field | Meaning |
|---|---|
| `id`, `entry` | `c<n>`, and the catalogue id |
| `what` | what the place holds |
| `paths` | the catalogue paths, unexpanded (`%TEMP%`); the detail item has the expanded ones in `expanded_paths` |
| `status` | `read` (files found); `empty` (no file, or the folder does not exist: `reason` "the folder does not exist"); `partial` (a path or a folder under it could not be listed, or a path was not measured: the sizes count the rest); `unreadable` (no path could be listed, a variable is not set, or no fixed drive is known: the sizes are `null`; also when no path was read and at least one path could not be listed while the others do not exist or are not measured: a missing path is not a size of the others, so the sizes are `null`, never 0); `not_measured` (no path was measured: at least one path is itself a reparse point (a junction, a symbolic link, a cloud folder) or a cloud-only folder, so it was not entered, none could not be listed, and every other path does not exist; a missing path does not count as measured: the sizes are `null`, the place was read and is not unreadable) |
| `reason` | why it is `partial`, `unreadable`, `not_measured` or not there; else `null` |
| `bytes`, `files`, `gb` | everything in the place (`gb` with two decimals) |
| `bytes_older`, `files_older`, `gb_older` | only with `min_age_days` > 0: the files whose last write and creation are both more than `min_age_days` days before the run (the later of the two counts; a file unpacked or copied just now keeps an old last write but has a new creation time; with no creation time known, the last write alone), in the folders the block enters (no reparse-point folder), which is what the block deletes |
| `unreadable_dirs` | paths, and folders under them, that could not be listed |
| `skipped_paths` | paths that are themselves a reparse point (a junction, a symbolic link, a cloud folder) or a cloud-only folder, seen in the listing of their parent: not entered, not measured |
| `min_age_days`, `risk`, `needs_admin`, `conditions`, `rollback` | from the catalogue |

The summary item has no `block`: the blocks would take about half of the
summary budget. The detail item adds `block` (from the catalogue),
`expanded_paths`, `unreadable` (`path`, `reason`) and `skipped` (`path`,
`reason`); `--block <id>` prints the same block and reads nothing.
A `partial`, `unreadable` or `not_measured`
item has a `not_checked` item with `what` "cleanup entry <id>", `entry`,
`item` (the `c` id), `reason`, and for `partial` the `count` of what could
not be listed or was not measured.

The recycle bin (`recycle-bin`) is measured over every `S-...` folder of
`<drive>:\$Recycle.Bin` that could be read, so its size covers the bins of
every account that could be read, while the block empties only the bin of
the account that runs it: the size can overstate what the block frees. The
folders of other accounts usually cannot be read without administrator
rights, so on a normal run `partial` for the recycle bin usually means the
bins of other accounts.

The blocks: with `min_age_days` > 0 a block lists the files of each path
(it enters no reparse-point folder, so no junction, link or cloud folder,
and leaves cloud-only files alone; a path that is itself a reparse point
is skipped with a message) and removes only the files whose last write
(`LastWriteTime`) and creation (`CreationTime`) are both before the cut-off
(the time the block runs minus `min_age_days` days), one by one;
it never removes a folder, and it prints how many files it deleted, could
not delete and kept, and how many folders it could not read (listing
errors are collected with `-ErrorVariable`, never dropped); when that
number is above 0 it says that the counts are incomplete and gives the
first error. Every block of an entry with `needs_admin` `true` first stops
with a message ("Not elevated ... nothing deleted") when the shell is not
elevated. `windows-update-download` stops `wuauserv` and `bits`
when they run and starts again only those, also after an error.
`delivery-optimization` stops with a message when the shell is not
elevated, runs `Delete-DeliveryOptimizationCache` with `-ErrorAction Stop`
and prints its failure, then counts the files left, or says the count is
not known when the cache folder could not be read in full.
`recycle-bin` runs `Clear-RecycleBin` with `-ErrorAction Stop` for every
fixed drive and prints per drive "emptied", "already empty" (the error
for an empty bin, Win32 code 3) or "NOT emptied" with the error; then it
reads back the number of items left in the bin of the account (or says it
could not, and the next run measures it). `rollback` is "cannot be undone"
for every entry.

## not_checked

Besides the shared cases: the drive list could not be read; a drive root
could not be listed; the usage of a drive was not read; directories of a
drive could not be listed (`count`, an example); a drive of the baseline is
not a fixed drive of this run; changed scan settings; items not compared
(per drive); a cleanup entry `partial`, `unreadable` or `not_measured`; a
list cut from the summary by the budget; the baseline was not saved or its
history not kept.

## Budget

The summary holds at most `summary_folders`, `summary_large_files` and
`summary_changes` items of the three lists. To stay within 35 000
characters `folders` is cut from its end first, then `large_files`, then
`changes`, each with a `not_checked` item; `cleanup` is never cut.

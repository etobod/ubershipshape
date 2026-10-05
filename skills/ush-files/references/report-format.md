# Report format (ush-files)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/files-<YYYY-MM-DD-HHMM>.md` (local time of the
run) and checked with
`python -B skills/ush-common/scripts/check_report.py <report>` (or
`--latest --skill ush-files` for the newest `files-*.md`), which reads the
ush-files rules from `data/report-profile.json`.
Follow `skills/ush-common/references/report-style.md`: it says how every
report is written (time, numbers, dash, recommendation layout, language);
this file says what the ush-files report contains.
`<data dir>` is the data directory (`--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`); its absolute value is the directory above
`work/` in the summary's `summary_file`. The report text outside code blocks
writes it as `&lt;data dir>` in plain text, never in inline code (a `<`
before a letter fails the check, and inline code shows `&lt;` as it is), and
never the expanded path: it contains the account name, which a report must
not carry. The expanded path appears only in the `ush:summary` marker and
as the `--data-dir` value of every block that runs a skill script (rule 9 of
`report-style.md`).

The markers below are HTML comments: they do not depend on the report
language and do not show in a preview. Each marker stands on its own line,
outside quotes and lists; no other HTML comment is allowed. This file stays
in English; the report translates every heading and label, the table header
included.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. The checker is
shared by all skills (see `skills/ush-health/references/report-format.md`,
"Numbers", for the full list); in short:

- Every run of digits is a separate number: `2026-05-07` is 2026, 5 and 7,
  `160.0` is 160 and 0. Write a number with the same digits and precision
  as the JSON, with the decimal separator of the report language (rule 2 of
  `report-style.md`) (in Polish `160,0`), counts without a thousands
  separator.
- Sizes are written only from the `_gb` fields, with their digits:
  `used_gb`, `total_gb`, `free_gb` and `scanned_gb` of a drive, `gb` of a
  folder, large file or cleanup item, `gb_older` of a cleanup item and
  `delta_gb` of a change; the one `_mb` field is `delta_mb` of a change,
  for a change that `delta_gb` shows as `0,0` (under about 50 MB): write
  it in MB (`11,8 MB`). Drive, folder and change sizes have one decimal
  place, cleanup sizes two (`0,68 GB`). Never convert bytes, never add
  folders or cleanup items up, never compute a percentage or a difference.
- `path` and `paths` back no number (the profile's `path_keys`), and
  neither does `block` (in the detail file only). A path with digits in it
  goes in a fenced code block, or the report names the folder in words; a
  block is quoted only in a fenced code block.
- Item ids (`f1`, `l2`, `d3`, `c4`) are not numbers when they name an item
  of the summary, an item named in `ush:detail`, or an item cut from the
  summary (`truncated_folders`, `truncated_large_files`,
  `truncated_changes`). A word of that shape that is no such id is checked
  as a number.
- Write every number in digits: a number word (`dwa`, `trzy`, `two`, in any
  case or form) outside code fails the check unless the same word is in a
  text value of the summary (a name). `ten`, `jeden`, `one` and `oba` are
  not number words.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Dyski`)
  is fine when the numbering of its level counts from 1 in order. The first
  cell of a table row is ignored when it equals the row's position among the
  table's data rows, so never put a count there.
- Fenced code blocks are not checked: never put a finding's number in one.
- No HTML and no links outside code blocks: write a literal `<` as `&lt;`
  and a literal `]` before `(` or `:` as `&rsqb;`.

## Items the report must name

Every `changes[*].id`, `large_files[*].id` and `cleanup[*].id` of the
summary appears in a visible line of the report, as a word of its own (`d12`
does not name `d1`), each with a short name after it (rule 6 of
`report-style.md`). Several ids on one line are fine. A mention inside a
fenced code block or on a marker line does not count. The check lists each
missing id as `not named in the report: <id> (<list>)` and fails. Folders
are not required: name the ones worth a word.

## Folder sizes are not disk use

A file with several hard links counts in full under every path that reaches
it, and a sparse or compressed file counts at its full size. So a folder
can show more than it takes on the disk (`C:\Windows\WinSxS` holds hard
links to files of `C:\Windows\System32`, so both count them), and the sizes
of the folders, or `scanned_gb`, can exceed `used_gb` of the drive. The
report says so once, in the drives section, and always takes `used_gb` as
what the drive holds. Never present the sum of folders as the drive's use,
and never call the gap between `scanned_gb` and `used_gb` a finding by
itself.

## Layout

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

   Then the title with the time of the run (`generated_at`, in local time
   with the UTC time in brackets, rule 1 of `report-style.md`), and one
   line: whether the run was elevated (`elevated`). Without elevation say
   that folders of other accounts and some system folders could not be
   listed, with `counts.unreadable_dirs`.

2. Dashboard: a table, one row per item, in this order:

   | Item | Value |
   |---|---|
   | Drive C: | 160,0 of 238,4 GB used, 78,4 GB free |
   | Changes | 3 since the run of 2026-09-25 09:00 (07:00 UTC), 7,1 days |
   | Large files | 4 |
   | Not compared | 0 |

   - One row per item of `drives`: `used_gb` of `total_gb`, and `free_gb`.
     A `null` value is "not read", never "0".
   - Changes: `counts.changes`, with the baseline time and age (rule 12 of
     `report-style.md`: `baseline.created_at`, `baseline.age_days`). With
     `baseline.status` `none` the cell is "no baseline yet (first run)",
     never "0"; with `unreadable` it is "baseline not read".
   - Large files: `counts.large_files`.
   - Not compared: `counts.not_compared`.

3. Drives and folders: per drive, `used_gb`, `scanned_gb` and
   `scanned_files`, with the sentence of "Folder sizes are not disk use".
   Then the folders worth a word (the largest, a folder with
   `readable_part` `true`), each with its id, a short name, `gb` and
   `files`. A folder with `readable_part` `true` counts only its readable
   part: say so next to its size. With `truncated_folders` > 0, one line:
   how many folders are only in the detail file.

4. What changed: first one line per drive on the comparison
   (`comparison.sources`): `compared`, or why not (see "Degradation
   cases"). Then every item of `changes`, in the summary's order: id, the
   `kind` in words (grew, shrank, new folder, folder gone, new large file,
   large file gone, large file changed, drive use changed), a short name,
   `delta_gb` (or `delta_mb` when `delta_gb` is `0.0`), and `before_bytes` and `after_bytes` only through their
   meaning (new or gone). A change with `readable_part` `true` covers the
   readable part only: say so. A `large_file_changed` gives
   `before_modified` and `after_modified` as times (rule 1). With
   `truncated_changes` > 0, one line: how many changes are only in the
   detail file. Growth under the data directory (by default
   `%LOCALAPPDATA%\ubershipshape`, written `&lt;data dir>`) includes this
   skill's own baseline, history and work files.

5. Large files: every item of `large_files`: id, a short name (what the
   file is, for example a virtual disk or an installer), `gb`, and
   `modified` as a time (rule 1). With `truncated_large_files` > 0, one
   line: how many large files are only in the detail file.

6. To clean up: every item of `cleanup`, in the summary's order: id, `what`
   in words, `status`, `gb` and `files`, and with `min_age_days` > 0 also
   `gb_older` and `files_older` with the number of days ("older than 2
   days: 0,59 GB in 1204 files"): that is what the block deletes. Like the
   block, the sizes leave out every folder that is a link or another reparse
   point (also a cloud folder) and cloud-only folders. A file
   counts as older only when both its last write and its creation are that
   old, so a file an installer unpacked just now with an old date is not in
   it. A `partial` item counts the readable part only, an `unreadable` or
   `not_measured` one has no size (see "Degradation cases"). The recycle bin
   size covers the bins of every account that could be read, but its block
   empties only the bin of the account that runs it, so say that the size
   can overstate what the block frees. For each item you recommend, under
   its bullet:

   - what the user must make sure of first: `conditions`, in the report
     language;
   - the shell: `needs_admin` `true` is an elevated PowerShell, `false` the
     user's own PowerShell;
   - `risk`, and that it cannot be undone (`rollback`);
   - the block, copied word for word into a fenced `powershell` code block
     from the output of
     `python -B skills/ush-files/scripts/files.py --block <id>` (the lines
     after its `#` header line; the summary has no `block`). Never change a
     block and never write one of your own.

   The blocks delete only what the catalogue names; files of the user
   (documents, downloads, large files, folders of `folders`) get no block:
   name them and leave the decision to the user.

7. Recommendations, where you have any: each with `weight`, `kind`, `risk`,
   `evidence` (ids and values from the JSON), `permissions` and `rollback`
   in the layout of rule 4 of `skills/ush-common/references/report-style.md`
   (the fields are in `skills/ush-common/references/summary-contract.md`,
   "Recommendations"); with none, write the sentence of rule 14 there. A
   cleanup recommendation takes `risk` and `needs_admin` from its item, and
   its rollback is "cannot be undone"; its block stands in section 6 (or
   here, but once). After the user ran a block, a new run reads the sizes
   back (`SKILL.md`, step 8).

8. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail f3 c2 -->
   ```

   A named id that is not in the detail file fails the check.

9. Not checked, always last. Its marker stands directly before (or right
   after) the section heading:

   ```
   <!-- ush:not-checked -->
   ## Not checked
   ```

   It lists every `not_checked` item with its `what` and `reason`, names
   every `unreadable` source and every source whose comparison state is not
   `compared`. If `not_checked` is `[]` and nothing else is missing, it says
   "nothing".

## Account names

A report never carries the account name, except in the data directory path
where the section above allows it. A `path` of a folder, large file or
change, an `expanded_paths` entry of a cleanup item and a `not_checked`
reason often start with the profile folder, `C:\Users\` followed by the
account name: write that folder as `%USERPROFILE%`
(`%USERPROFILE%\Downloads`), in code blocks too. The folders of other
accounts are "the folder of another account", never by name.

## Values that are not readings

- `null` is "not read" (or "unknown" in the plain sense), in words, never
  "no", "none" or "0".
- `readable_part` `true` and `status` `partial`: the size is a lower bound,
  the readable part only.
- `listed` `false` with `skipped` `reparse` or `cloud_only` (from
  `--detail`): the folder was not entered, its size was not read; a
  junction points elsewhere, a cloud-only folder is not on the disk.
- `cloud_only_files`: files that are only in the cloud take no space on the
  disk; they are not counted in `gb`.
- A cleanup item `empty` with `reason` "the folder does not exist" is a
  reading: there is nothing to clean. The recycle bin leaves out the
  `desktop.ini` that Windows keeps in each bin folder, so an otherwise
  empty bin is `empty`.

## Degradation cases

Never report missing data as "none", "nothing there" or "no change":

- No baseline (`baseline.status` `none`, comparison state `no_baseline`):
  "no baseline yet, this run is the first; the next run shows what
  changed", never "no changes".
- An unreadable baseline (`baseline.status` `unreadable`): give `reason`;
  nothing was compared.
- `settings_changed` (a `not_checked` item with `previous_settings` and
  `settings`): the folders or large files of that drive were not compared
  because the depth or the threshold changed; the next run with the same
  settings compares them again.
- `not_read` for a drive (a drive of the baseline that is not here): the
  drive was not compared; the baseline keeps its items.
- Items not compared (`counts.not_compared` > 0): give the count and the
  reason of the `not_checked` item per drive; these items may have changed.
- A drive root unreadable (`folders:<L>` `unreadable`): no folders and no
  large files of that drive were read, and its `scanned_gb`,
  `scanned_files` and `cloud_only_files` are `null` ("not read"); its usage
  may still be known.
- Usage not read (`drives:<L>` `unreadable`): `used_gb`, `total_gb` and
  `free_gb` are "not read".
- Unreadable directories (`counts.unreadable_dirs` > 0, folders with
  `readable_part` `true`): the sizes of those folders are the readable part
  only. Without elevation offer an elevated run (`SKILL.md`, step 9).
- A cleanup item `unreadable`: its size is not known, never "0" or
  "empty"; give the `reason` (a variable not set, a folder that needs
  administrator rights). Give no block for it unless the user wants to run
  it without knowing the size; then say so.
- A cleanup item `partial`: the size covers the readable part; give the
  `count` of the `not_checked` item. For the recycle bin on a normal
  (non-elevated) run, `partial` usually means the bins of other accounts,
  which only an elevated run reads; the block does not empty those anyway.
- A cleanup item `not_measured`: the place is itself a junction, a link or
  another reparse point (a cloud folder, or one only in the cloud), so it
  was read but not entered, and any other path of it does not exist; it
  has no size; never "0" or "empty", and not "unreadable". Its block
  skips such a folder and deletes nothing in it.
- Lists cut from the summary (`truncated_folders`, `truncated_large_files`,
  `truncated_changes` > 0): give the numbers and say that the detail file
  has them.

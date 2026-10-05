---
name: ush-files
description: Show how full each fixed drive of this Windows machine is, its largest folders to a set depth and its large files, what grew, shrank, appeared or went away since the last run, and how much the known cleanup places hold (temporary files, downloaded Windows updates, the Delivery Optimization cache, crash dumps, error reports, the recycle bin), each with a paste-ready block. Use when the user asks where the disk space went, what fills the drive, what grew since last time, which files are large, or what can be cleaned up safely. Read-only; it deletes nothing itself.
---

# ush-files

Walks every fixed drive to a set depth, sums the sizes of the files on the
disk per folder, lists the files above a size threshold, compares all of it
with the baseline of the previous run, and measures each place of the
cleanup catalogue. A script counts and matches; you judge and write a
Markdown report; the user decides what to act on and runs the blocks
himself.

## When to use

- The user asks where the disk space went, what fills a drive, or how much
  is free.
- The user asks what grew, shrank, appeared or went away since the last run.
- The user asks which files are large, or which folders are the largest.
- The user asks what can be cleaned up, or how much the temporary files,
  the downloaded updates or the recycle bin hold.

Not for: deleting files of the user (documents, downloads, programs: the
report names them, the user decides with his own tools), uninstalling a
program (`ush-inventory`), the health of the disks and volumes
(`ush-health`), the event logs and their size (`ush-events`), duplicate
files, file contents or cloud storage. Say so if the user asks for these.

## Rules

- **Read-only.** `files.py` changes nothing on the machine. It writes only
  to `<data dir>/work/` and its baseline in `<data dir>/state/`. It deletes
  nothing: every cleanup is a block the user pastes into a shell himself.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a folder or a file.
- **Read only the summary JSON.** Never open the detail file or other files
  in `<data dir>/work/` directly. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the script writes:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  `%LOCALAPPDATA%\ubershipshape`. Take its absolute value from the summary's
  `summary_file` (the directory above `work/`). In the report text outside
  code blocks write it as `&lt;data dir>` in plain text, never the expanded
  path: it contains the account name (`references/report-format.md`).
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. Sizes only from the `_gb` fields
  (`gb`, `used_gb`, `delta_gb`, `gb_older`, ...) and, for a change whose
  `delta_gb` is `0.0`, from `delta_mb` (in MB), with their digits; never
  convert bytes, never add folders or entries up, never compute a percent.
- **Folder sizes are not disk use.** A file reachable by several hard links
  counts in full under every path, and a sparse or compressed file counts
  at its full size (`C:\Windows\WinSxS` shows more than it takes). The
  used space of a drive (`drives[].used_gb`) is the real figure; never
  present the sum of folders as what the drive holds.
- **Empty is not unreadable.** A folder with `readable_part` `true`, a
  cleanup item with `status` `partial`, `unreadable` or `not_measured` (the
  place is itself a junction, a link or another reparse point, not entered),
  a source `unreadable` or a comparison state other than `compared` must be
  reported as such (`references/report-format.md`, "Degradation cases"),
  never as "none", "nothing there" or "no change".
- **Cleanup only from the catalogue.** A block comes only from
  `files.py --block <id>`, word for word (the summary's cleanup items carry
  no `block`). Never write a deletion block
  of your own, and never suggest deleting a folder or a file of the user;
  for those, name the item and leave the decision to the user.
- **Before a cleanup block, its conditions.** Give the item's `conditions`
  as what the user must make sure of first, whether it needs an elevated
  shell (`needs_admin`), and its rollback: "cannot be undone".
- **Recommendations** carry `weight`, `kind`, `risk`, `evidence`,
  `permissions` and `rollback` as defined in the shared contract
  `skills/ush-common/references/summary-contract.md` ("Recommendations").
- **A success message is not verification.** After the user ran a block,
  a new run of `files.py` reads the sizes back.

## Steps

1. From the project root run, in a normal (non-elevated) shell:

   ```
   python -B skills/ush-files/scripts/files.py
   ```

   It walks every fixed drive, which can take minutes. It prints the summary
   JSON on stdout and writes it, with a detail file, to `<data dir>/work/`.
   The field meanings are in `references/summary-contract.md`.

2. Read the summary. For an item you need to understand (a folder's
   unreadable or skipped directories, a folder cut from the summary, a
   cleanup item's expanded paths and unreadable folders), fetch it:

   ```
   python -B skills/ush-files/scripts/files.py --detail <id> --detail-file <detail_file>
   ```

   `<detail_file>` is the summary's `detail_file`. The ids (`f` folders, `l`
   large files, `d` changes, `c` cleanup items) are places in the lists of
   this run, so always fetch from the same run's detail file. Remember every
   id you fetched and used.

3. Judge the findings: which drive is short of space, which folders and
   large files hold it, what grew since the last run and whether that is
   expected, and which cleanup places are worth emptying. Weigh them with
   the scale of the shared contract (`high`, `medium`, `low`). The script
   sets no threshold: the judgement is yours.

4. For each cleanup item you recommend, print its block with

   ```
   python -B skills/ush-files/scripts/files.py --block <id>
   ```

   (`<id>` the item's `id` or `entry`; it reads nothing on the machine and
   writes nothing) and copy the lines after its `#` header line into the
   report word for word. With it give the conditions, the shell
   it needs (`needs_admin` `true`: an elevated PowerShell; the block stops
   with "Not elevated" otherwise), its risk, and that it cannot be undone.
   After the user runs an age-based block, its last lines give how many
   folders it could not read; above 0 the counts it printed are incomplete,
   so never present them as the full result.

5. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/files-<YYYY-MM-DD-HHMM>.md` (local time of the run).
   The first line is `<!-- ush:summary <summary_file> -->` with the absolute
   `summary_file` path from the summary.

6. After saving, run:

   ```
   python -B skills/ush-common/scripts/check_report.py "<absolute data dir>/reports/files-<YYYY-MM-DD-HHMM>.md"
   ```

   (`--latest --skill ush-files` checks the newest `files-*.md` instead.) It
   fails on a number not backed by the JSON and on a change, large file or
   cleanup item of the summary not named in the report. Correct the report
   and run the check again until it prints `OK`. `OK` means each number
   occurs somewhere in the JSON, not that it is used for the right thing, so
   the rules above still bind you. Do not hand the report to the user before
   it prints `OK`.

7. Tell the user where the report is and give the main findings in a few
   lines.

8. After the user says a cleanup block ran, run step 1 again and report
   the sizes of those cleanup items from the new summary. Never take the
   counts the block printed as the result.

9. Only when `elevated` is `false`: you may say that a run with
   administrator rights reads more (system folders such as the Windows
   temporary files, the error reports and the Delivery Optimization cache,
   and the folders of other accounts). It is not required; do not run it
   yourself.

   ```
   # Runs the same read-only walk with administrator rights. It changes
   # nothing on the machine and writes only to <data dir>\work\ and its
   # baseline in <data dir>\state\.
   Set-Location "<absolute project root>"
   python -B skills/ush-files/scripts/files.py --data-dir "<absolute data dir>"
   ```

   An elevated run compares only with the elevated baseline
   (`ush-files.elevated.json`); its first run has no comparison. After the
   user says it ran, read the newest `<data dir>/work/files-*.summary.json`,
   whose `elevated` must be `true` (otherwise say that the block did not run
   elevated), and write a new report from that one summary, as in steps
   3-6. Never merge two summaries into one report.

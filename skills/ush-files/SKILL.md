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

## Plugin paths

- Plugin root: `${CLAUDE_PLUGIN_ROOT}`
- Data folder: `${CLAUDE_PLUGIN_DATA}`

The references write these two folders as `<plugin root>` and
`<plugin data>`: fill them in from the two lines above. A block for the user
starts with `Set-Location "<absolute plugin root>"`, the plugin root above.

If writing a file to the data folder is refused (a hook or a permission
rule blocks the Write or Edit tool), stop there. Never change a settings file
yourself. Tell the user that nothing was saved and why, and give them one
line to type in this session, without quotes: `/add-dir <data folder>`, the
absolute data folder written with forward slashes. It allows the folder for
this session only, with no settings file edit. To allow it for good, they can
add the same forward-slash path to `permissions.additionalDirectories` in
their user settings `~/.claude/settings.json` (never in a project's `.claude`
folder); that applies from the next session, so after only that change the
skill is run again in a new session. Write the file again with the same tool
only after the user says they ran `/add-dir`. If it is refused again, stop the
skill and tell the user that nothing was saved and why. Never write the file
another way (a shell command, another folder).

## When to use

- The user asks where the disk space went, what fills a drive, or how much
  is free.
- The user asks what grew, shrank, appeared or went away since the last run.
- The user asks which files are large, or which folders are the largest.
- The user asks what can be cleaned up, or how much the temporary files,
  the downloaded updates or the recycle bin hold.

Not for: deleting files of the user (documents, programs, large files: the
report names them, the user decides with his own tools); the Downloads
folder is the one exception, and only through `files.py --block downloads`:
files the user approved one by one, copied to a folder he names and deleted
only where the copy verified, printed after he decides, into a repair plan
(step 4). Also not for uninstalling a
program (`ush-inventory`), the health of the disks and volumes
(`ush-health`), the event logs and their size (`ush-events`), duplicate
files, file contents or cloud storage. Say so if the user asks for these.

## Rules

- **Read-only.** `files.py` changes nothing on the machine. It writes only
  to `<data dir>/work/` and its baseline in `<data dir>/state/`. It deletes
  nothing: every cleanup is a block the user runs himself, delivered in
  `run-me.ps1` or `run-me-admin.ps1` per `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/run-me.md`.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a folder or a file.
- **Read only the summary JSON.** Never open the detail file or other files
  in `<data dir>/work/` directly. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the script writes:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  the plugin data folder (`--default-data-dir`). Take its absolute value from the summary's
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
  for those, name the item and leave the decision to the user. The only
  block for files of the user is `files.py --block downloads` (step 4):
  copy, verify size and SHA-256, then delete, for Downloads files the user
  approved.
- **Before a cleanup block, its conditions.** Give the item's `conditions`
  as what the user must make sure of first, whether it needs an elevated
  shell (`needs_admin`), and its rollback: "cannot be undone".
- **Recommendations** carry `weight`, `kind`, `risk`, `evidence`,
  `permissions` and `rollback` as defined in the shared contract
  `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/summary-contract.md` ("Recommendations").
- **A success message is not verification.** After the user ran a block,
  a new run of `files.py` reads the sizes back.

## Steps

1. From the project root run, in a normal (non-elevated) shell:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-files/scripts/files.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}"
   ```

   It walks every fixed drive, which can take minutes. It prints the summary
   JSON on stdout and writes it, with a detail file, to `<data dir>/work/`.
   The field meanings are in `references/summary-contract.md`.

2. Read the summary. For an item you need to understand (a folder's
   unreadable or skipped directories, a folder cut from the summary, a
   cleanup item's expanded paths and unreadable folders), fetch it:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-files/scripts/files.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --detail <id> --detail-file <detail_file>
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

   Before judging, list `<data dir>/plans/` (not `done/`); for an open plan of this skill,
   compare this run's values with the values its run blocks set (its `Odczyt po zmianie`
   names how to read them back), write the result under `Notatki`, and move it to
   `plans/done/` (never over an existing file) only when every value the plan
   sets (by a run block or by a step in words) reads back as set; otherwise
   it stays open. If `plans/` cannot be listed, say so and give the reason; it
   is not "no plans".

4. The report proposes each cleanup item you recommend in words, with its
   conditions, the shell it needs (`needs_admin` `true`: an elevated
   PowerShell), its risk and that it cannot be undone, and holds no block
   (rule 8 of `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/report-style.md`). Only after the
   user chooses an item, print its block with

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-files/scripts/files.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --block <id>
   ```

   (`<id>` the item's `id` or `entry`; it reads nothing on the machine and
   writes nothing) and put the lines after its `#` header line word for
   word into a repair plan per `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/repair-plan.md`, in a
   fenced `powershell` code block marked `<!-- ush:block ush-files <id> -->`,
   with the conditions, the shell it needs
   (the block stops with "Not elevated" in a normal shell when
   `needs_admin` is `true`), its risk, and that it cannot be undone. The
   printer prints, per item, one `#` header line (what, risk, shell,
   conditions and `rollback: cannot be undone`) and then the block, and no
   rollback block: so the undo section gets, for the same id, the no-undo
   marker `<!-- ush:noundo ush-files <id> -->` followed by a line of words
   saying it cannot be undone, never a fenced block. Check the plan with
   `python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_repair_plan.py" <file>`, tell the user
   which plan holds it, and deliver the block per
   `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/run-me.md`: in `run-me-admin.ps1` when
   `needs_admin` is `true`, else in `run-me.ps1`; the block never goes into
   the chat or the report. After a new run has read the result back, write
   it under `Notatki` and move the plan to `plans/done/` only when every value
   the plan sets reads back as set (see the step before judging); otherwise it
   stays open; never delete it.
   After the user runs an age-based block, its last lines give how many
   folders it could not read; above 0 the counts it printed are incomplete,
   so never present them as the full result.

   Downloads (`downloads`): the report names the largest and oldest files
   and leaves the choice to the user. Only after the user approves files one
   by one (by editing a copy of the summary's `list_file` down to the
   approved entries, or by naming their `w` ids in the chat) and names a
   destination folder (for example on an external disk), print

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-files/scripts/files.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --block downloads --dest "<folder>" --list "<approved list file>"
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-files/scripts/files.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --block downloads --dest "<folder>" --list "<downloads.list_file of the summary you reported>" --ids w1,w5
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-files/scripts/files.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --block downloads --dest "<folder>" --ids w1,w5 --stamp <stamp of that list_file>
   ```

   With `--ids`, pass either `--list <list_file>` or `--stamp <stamp>`, both
   from the `downloads.list_file` of the summary the user saw (the stamp is
   the `YYYYmmdd-HHMMSS` in its name `files-<stamp>.downloads.json`): `w` ids
   are positions in one run's listing, and a later run of `files.py` (also
   inside `ush-runall`) numbers them anew. `--ids` without `--list` resolves
   from the newest list file of the data directory and needs `--stamp`; when
   that newest file carries another stamp (a newer run exists) it exits 1
   with no block: rerun, report and let the user approve again. The run
   block also checks, before any copy, that every listed file still in
   Downloads has the size and last write time of its list entry, and stops
   with nothing copied or deleted when one does not: that catches a file
   changed or replaced since the listing, not a different listing (the
   stamp guards that). It reads only the list file
   and writes nothing; without `--dest`, with an empty list, an unknown id,
   a missing, malformed or other stamp, or no list file it exits 1 and
   prints no block. The output is two parts:
   the run block (its `#` header line gives the shell, non-elevated, risk
   `medium` and the rollback) and, from the `# downloads undo block` line,
   the undo block. Put the lines after the run header word for word under
   `<!-- ush:block ush-files downloads -->` and the lines after the undo
   header under `<!-- ush:undo ush-files downloads -->` of a repair plan,
   with the risk `medium`, the shell (normal, non-elevated) and the files it
   names. The run block copies each file, compares the size and SHA-256 of
   the copy with the original, deletes the original only when both match,
   and stops at the first failed copy or mismatch with nothing deleted after
   it; it ends with the counts copied, verified, deleted and not deleted. The
   undo block copies the files back and verifies them; it deletes nothing.
   A new run of `files.py` reads the Downloads sizes back.

5. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/files-<YYYY-MM-DD-HHMM>.md` (local time of the run).
   The first line is `<!-- ush:summary <summary_file> -->` with the absolute
   `summary_file` path from the summary.

6. After saving, run:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_report.py" "<absolute data dir>/reports/files-<YYYY-MM-DD-HHMM>.md"
   ```

   (`python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_report.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --latest --skill ush-files`
   checks the newest `files-*.md` instead.) It
   fails on a number not backed by the JSON and on a change, large file or
   cleanup item of the summary not named in the report. Correct the report
   and run the check again until it prints `OK`. `OK` means each number
   occurs somewhere in the JSON, not that it is used for the right thing, so
   the rules above still bind you. Do not hand the report to the user before
   it prints `OK`.

7. Tell the user where the report is (the absolute path of the report file, in the chat answer only) and give the main findings in a few
   lines.

8. After the user says a cleanup block ran, run step 1 again and report
   the sizes of those cleanup items from the new summary. Never take the
   counts the block printed as the result.

9. Only when `elevated` is `false`: you may say that a run with
   administrator rights reads more (system folders such as the Windows
   temporary files, the error reports and the Delivery Optimization cache,
   and the folders of other accounts). It is not required; do not run it
   yourself. When the user wants it, deliver this block in `run-me-admin.ps1`
   per `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/run-me.md` (`run-me.ps1` is for a
   normal shell; this block needs the elevated one).

   ```
   # Runs the same read-only walk with administrator rights. It changes
   # nothing on the machine and writes only to <data dir>\work\ and its
   # baseline in <data dir>\state\.
   Set-Location "<absolute plugin root>"
   python -B skills/ush-files/scripts/files.py --data-dir "<absolute data dir>"
   ```

   An elevated run compares only with the elevated baseline
   (`ush-files.elevated.json`); its first run has no comparison. After the user
   says it ran, read the newest `<data dir>/work/files-*.summary.json`, which
   must be newer than the hand-off (its `generated_at`, UTC, later than the UTC
   time in the `# Written:` header of `run-me-admin.ps1`, never the file's
   modification time; `run-me.md` "After the run") and whose `elevated` must be
   `true`. When it is not newer, or `elevated` is not `true`, the elevated pass
   did not run, failed or ran without the rights: follow `run-me.md` "After the
   run", which says when to tell the user to run the same `run-me-admin.ps1`
   again from an elevated PowerShell and when to ask for the error first.
   Otherwise write a new report from that one summary, as in steps 3-6. Never
   merge two summaries into one report.

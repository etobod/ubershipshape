---
name: ush-events
description: Review the Windows System and Application event logs of the last 30 days and write a report of recurring errors, crashes (bugchecks), unexpected shutdowns, boot sessions, the daily stability index of the Reliability Monitor, memory dumps linked to their bugchecks, and known noise. Use when the user asks to check the event logs, why the machine crashed, restarted or froze, about memory dumps (minidumps, MEMORY.DMP, whether a crash left a dump, archiving or cleaning up dumps), to export or back up the System or Application log to an .evtx file, to clear (empty) one of those logs, or for a general health check of this Windows machine. Read-only by default.
---

# ush-events

Reads the `System` and `Application` event logs and the Reliability Monitor
(stability index and records, through WMI) without elevation, lets a script
count and group them, and writes a Markdown report for the user.
The script counts; you judge and write; the user decides what to act on.

## When to use

- The user asks to review the event logs, or what the logs say.
- The user asks about a crash, blue screen, sudden restart, freeze or a
  device that stopped working, and wants to see what Windows recorded.
- As part of a general health check of this machine.
- The user asks about memory dumps: whether a crash left one, where they
  are, or to archive them (optionally removing the originals).
- The user asks to export (back up) the `System` or `Application` log, or
  to clear one of them.

Not for: the `Security` log, analysing a dump's content (no debugger),
trends over months. Say so if the user asks
for these.

## Rules

- **Read-only by default.** `events.py` and `dumps.py` without flags change
  nothing on the machine; `logs.py --export` writes only under `ush-data/`.
  Do not run anything that needs administrator rights yourself (it would
  also leave its own events in the log). A recommended change, copying
  dumps and clearing a log are given as a paste-ready block the user runs
  themselves in an elevated PowerShell; you then read the result back.
- **Nothing leaves the machine.** No web search, no upload, no online tool.
- **Read only the summary JSON.** Never open the raw captures or other files
  in `ush-data/work/`. Single items come from `--detail <id>`.
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. Do not compute totals, averages,
  percentages or differences that are not in the JSON; do not write a
  number from memory or from the user's message. Describe instead of
  counting when the JSON has no number for it.
- **Empty is not unreadable.** A source with `status` `unreadable`, a
  `coverage_start`, `boots: null`, `reliability.status` `unreadable`,
  `reliability_records: null`, `dumps.status` `unreadable`, a dump file
  with `readable: false` or `truncated` > 0 must be reported as
  such (see the degradation cases in `references/report-format.md`), never
  as "clean".
- **The trend is the script's, and it is not a weight.** Each group's
  `trend` (`rising`, `falling`, `stable`, `too_few`, `unknown`) comes from
  the rule in `data/trend.json`; give it as written. `unknown` and
  `too_few` are neither rising nor calm: never report them as `stable` or
  as a warning. A trend never sets or changes a finding's weight.

## Steps

1. From the project root run:

   ```
   python -B skills/ush-events/scripts/events.py --data-dir ush-data
   ```

   It prints the summary JSON on stdout and writes it, with a detail file, to
   `ush-data/work/`. Use `--days <n>` only if the user asks for a different
   window. The field meanings are in `references/summary-contract.md`.

2. Read the summary. If you need one item in full (for example a group left
   out by `truncated`, or a boot session), fetch it:

   ```
   python -B skills/ush-events/scripts/events.py --data-dir ush-data --detail <id> --detail-file <detail_file>
   ```

   `<detail_file>` is the `detail_file` value from the summary, so the item
   comes from the same run that `check_report.py` checks against.

   Ids: `g..` groups, `n..` noise, `b..` boot sessions, `a..` anomalies,
   `r..` Reliability Monitor record groups, `d..` memory dump files.
   Remember every id you fetched and used.

3. Judge the findings: what is a real fault, what is harmless, what needs
   watching. Weigh them with the scale in `references/summary-contract.md`
   (`high`, `medium`, `low`). Known noise is reported separately, with its
   count and reason, never hidden.

4. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `ush-data/reports/events-<YYYY-MM-DD-HHMM>.md` (local time of the run).
   The first line is `<!-- ush:summary <summary_file> -->` with the absolute
   `summary_file` path from the summary.

5. Every recommendation carries `weight`, `kind` (`change`, `observe`,
   `consult_service`), `risk`, `evidence` (numbers and ids from the JSON),
   `permissions` and `rollback`, as defined in
   `references/summary-contract.md`.

6. After saving, run:

   ```
   python -B skills/ush-events/scripts/check_report.py ush-data/reports/events-<YYYY-MM-DD-HHMM>.md
   ```

   It prints `OK` when every number is backed by the JSON and the markers are
   in place. `OK` means each number occurs somewhere in the JSON, not that it
   is used for the right thing: small numbers (days, hours, minutes) almost
   always occur, so the rule above still binds you. Otherwise it names each unbacked number with its line: remove or
   correct that number (or fetch the item with `--detail` and name its id in
   `ush:detail`), save, and run the check again until it prints `OK`. Do not
   hand the report to the user before it does.

7. Tell the user where the report is and give the dashboard and the main
   findings in a few lines.

8. Memory dumps, only when `dumps.files` holds a dump worth keeping (for
   example one linked to a bugcheck) or the user asks to archive dumps.
   Reading a dump usually needs administrator rights, so do not run the copy
   yourself. Give the user this block for an elevated PowerShell, with the
   absolute project root and the absolute data directory filled in:

   ```
   # Copies every readable memory dump to <data dir>\dumps\, checks each copy
   # by SHA-256 against the original and records it in manifest.json there.
   # It deletes nothing and overwrites no earlier copy.
   Set-Location "<absolute project root>"
   python -B skills/ush-events/scripts/dumps.py --copy --data-dir "<absolute data dir>"
   ```

   Add `--delete-source` only when the user asked for the originals to be
   removed; then replace the block's sentence "It deletes nothing and
   overwrites no earlier copy." with "It overwrites no earlier copy. It
   deletes each original only after its copy is verified; the deletion
   cannot be undone."
   Never give `--delete-source` without `--copy`.

   Before you give the block, read the current UTC time from the machine
   (never guess it) and note it:

   ```
   python -B -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"
   ```

   After the user says it ran,
   read `<data dir>/dumps/manifest.json` (not the dumps); this run's entries
   are those with `copied_at` not earlier than that time - never simply the
   newest ones, which may belong to an earlier run - and tell the
   user, per dump, whether `verified` is `true`, where the `copy` is and,
   with `--delete-source`, whether `source_deleted` is `true`; name every
   entry with a `reason`. An entry with `verified` `false` and `copy` `null`
   is a copy that was made but failed its check and was discarded: the dump
   is not archived. A dump with no entry from this run was not recorded:
   ask for the script's output. Its `results` give the reason (not
   readable, not enough space, name taken by another file, or the copy
   failed), and its `error`, if any, says why the run stopped; when that is
   a failed manifest write, the dump being handled may already have a
   verified copy in `dumps/` without an entry, and the dumps after it were
   not handled. When the `error` says the manifest could not be updated
   after the removal step, do not trust that entry's `source_deleted`: the
   original may already be gone; take the outcome from `results`. Fields, when
   an entry is written, and exit codes are in
   `references/summary-contract.md`.

9. Exporting a log, only when the user asks for it (or asks to clear a
   log, which starts with an export). This needs no elevation and writes
   only to `ush-data/`, so you may run it yourself:

   ```
   python -B skills/ush-events/scripts/logs.py --export <System|Application> --data-dir ush-data
   ```

   Tell the user from its JSON whether `export.verified` is `true`, where
   `export.file` is and, if not verified, the `export.reason`. The file is
   also recorded in `ush-data/exports/manifest.json`. An export left
   unverified because the oldest records of a `Circular` log were
   overwritten during it is not a fault of the machine: run it again. A log
   with no records can never be verified (the `reason` says there is
   nothing to verify): do not run it again, and it cannot be cleared.

10. Clearing a log, only when the user explicitly asks for it. Never run it
    yourself and never pass `--clear` in any other step. Give the user this
    block for an elevated PowerShell, with the log name, the absolute
    project root and the absolute data directory filled in, together with:

    - **risk:** high - clearing is irreversible; `ush-events` loses the
      history of that log (clearing `System` removes the boot sessions,
      trends and bugchecks it would report);
    - **permissions:** administrator (an elevated PowerShell);
    - **rollback:** none - irreversible; the export and the `-rest` file are
      a copy to open in Event Viewer, they cannot be loaded back into the
      log.

    ```
    # Exports the <log> log to <data dir>\exports\, verifies the file by its
    # record ids and records it with its SHA-256 in manifest.json there. Only
    # after a verified export it clears the log with a backup of everything in
    # it at that moment (<log>-<stamp>-rest.evtx) and reads the backup and the
    # log back. Irreversible: the files can be opened in Event Viewer but not
    # loaded back into the log.
    Set-Location "<absolute project root>"
    python -B skills/ush-events/scripts/logs.py --export <log> --clear --data-dir "<absolute data dir>"
    ```

    After the user says it ran, ask for the JSON the script printed: it,
    not the manifest, decides the result (`<data dir>/exports/manifest.json`
    only tells where the files are; it has no `clear` fields). Tell the user
    whether `export.verified` and `clear.cleared` are `true`, where both
    files are, `clear.record_count_after`, and every `reason`:
    - `clear` `null`: nothing was cleared, because the export was not
      verified (give `export.reason`) or the run stopped before clearing
      (give the top-level `error`).
    - `cleared` `true`: cleared and confirmed.
    - `cleared` `false` with the elevation message, or `clear.exit_code`
      `null` (`wevtutil cl` never ran): nothing was cleared and the export
      stays.
    - `clear.exit_code` not `null` and `record_count_after` `null` (the log
      could not be read back): whether the log was cleared is unknown; say
      so plainly and give the `reason`. Never conclude either way.
    - Otherwise compare `record_count_after` with `backup_record_count`, or
      with `export.record_count` when `backup_record_count` is `null`. With
      `exit_code` `0`: below it the log was cleared (with `cleared` `false`
      a check afterwards failed: say it could not be confirmed, never "not
      cleared"); not below it, `wevtutil cl` reported success but the log
      still holds its records. With a non-zero `exit_code` (`wevtutil cl`
      failed or was stopped by a timeout): not below it, the log was most
      likely not cleared; below it, whether the log was cleared is unknown,
      because a full `Circular` log can lose a few records to overwriting
      on its own. Give the `reason` in every case.
    Fields and exit codes are in `references/summary-contract.md`.

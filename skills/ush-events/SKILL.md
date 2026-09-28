---
name: ush-events
description: Review the Windows System and Application event logs of the last 30 days and write a report of recurring errors, crashes (bugchecks), unexpected shutdowns, boot sessions and known noise. Use when the user asks to check the event logs, why the machine crashed, restarted or froze, or for a general health check of this Windows machine. Read-only.
---

# ush-events

Reads the `System` and `Application` event logs without elevation, lets a
script count and group the events, and writes a Markdown report for the user.
The script counts; you judge and write; the user decides what to act on.

## When to use

- The user asks to review the event logs, or what the logs say.
- The user asks about a crash, blue screen, sudden restart, freeze or a
  device that stopped working, and wants to see what Windows recorded.
- As part of a general health check of this machine.

Not for: the `Security` log, memory dumps, exporting or clearing a log,
trends over months. Say so if the user asks for these.

## Rules

- **Read-only.** The skill changes nothing on the machine. Do not run
  anything that needs administrator rights (it would also leave its own
  events in the log). A recommended change is only described, with a
  paste-ready block the user runs themselves.
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
  `coverage_start`, `boots: null` or `truncated` > 0 must be reported as
  such (see the degradation cases in `references/report-format.md`), never
  as "clean".

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

   Ids: `g..` groups, `n..` noise, `b..` boot sessions, `a..` anomalies.
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

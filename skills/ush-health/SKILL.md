---
name: ush-health
description: Read the health of this Windows machine once and write a report of disk health (and, elevated, the disks' reliability counters), free space on the volumes, battery wear, devices with an error in Device Manager, failed Windows updates, a pending restart and the Windows version, the antivirus state and signature age, restore points and WinRE, Secure Boot, TPM and BitLocker encryption. Use when the user asks for a health check or the state of this machine, whether the disks, the battery, the updates, the antivirus or the encryption are fine, how much free space is left, which devices have problems, or whether a restart is pending, and what changed in the disks, volumes, failing devices and Windows version since the last run (or since N days ago with --compare-to). Read-only.
---

# ush-health

Reads the state of this machine once, without elevation, through read-only
PowerShell jobs; a script counts and converts the values, and you write a
Markdown report for the user. The script counts; you judge and write; the
user decides what to act on.

## When to use

- The user asks for a health check of this machine, or how it is doing.
- The user asks about the disks (health, free space), the battery (wear,
  cycles), a device that does not work, failed updates, a pending restart,
  the Windows version, the antivirus, restore points, WinRE, Secure Boot,
  the TPM or BitLocker.
- The user asks what changed in the disks, the free space, the failing
  devices or the Windows version since the last run, or over a longer
  period (`--compare-to`).

Not for: the event logs, crashes and memory dumps (`ush-events`), trends
over many runs, a comparison of the battery, updates, TPM, Secure Boot,
antivirus, restore points or WinRE with an earlier run (each run gives
their current state only), decoding the bits of `productState`, fixing
anything automatically. Say so if the user asks for these.

## Rules

- **Read-only.** `health.py` changes nothing on the machine and writes only
  to `<data dir>` (`work/`, and its baseline, history copies and id map in
  `state/`). Do not run anything that needs administrator rights
  yourself. A recommended change is a paste-ready block the user runs
  themselves (in an elevated PowerShell when it needs the rights); you then
  read the value back.
- **Nothing leaves the machine.** No web search, no upload, no online tool.
- **Read only the summary JSON.** Never open the raw captures or other files
  in `<data dir>/work/`. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the scripts
  write: `--data-dir` when given, else `USH_DATA_DIR` (an absolute path),
  else `%LOCALAPPDATA%\ubershipshape`. Take its absolute value from the
  summary's `summary_file` (the directory above `work/`). In the report
  text outside code blocks write it as `&lt;data dir>` in plain text,
  never in inline code (a `<` before a letter fails the check, and inline
  code shows `&lt;` as it is), and never the expanded path: it contains
  the account name, which a report must not carry. The expanded path
  appears only in the `ush:summary` marker and in code blocks. Every block
  that runs a skill script starts with `Set-Location "<absolute project
  root>"` and passes `--data-dir "<absolute data dir>"` (rule 9 of
  `skills/ush-common/references/report-style.md`): an elevated shell of
  another account has a different `%LOCALAPPDATA%`.
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. Do not compute totals, percentages, sizes,
  ages or differences that are not in the JSON; do not write a number from
  memory or from the user's message.
- **Empty is not unreadable.** A source with `status` `unreadable` (reason
  `needs administrator` included), a list or object that is `null`, or
  `truncated` > 0 must be reported as such (see the degradation cases in
  `references/report-format.md`), never as "clean" or "none".
- **A missing value is not `false`.** `null` means unknown: never "off",
  "no" or `0`. The script already turned the sentinels (Defender's 65535 and
  4294967295, a battery's 0 cycles, a drive's 0 degrees) into `null`.
  `product_state` and a `protection` value other than 1 or 2 are given raw,
  without a conclusion.

## Steps

1. From the project root run:

   ```
   python -B skills/ush-health/scripts/health.py
   ```

   It prints the summary JSON on stdout and writes it, with a detail file, to
   `<data dir>/work/`, compares the disks, volumes, failing devices and the
   Windows version with the baseline of the previous run (`changes`,
   `baseline`, `comparison`) and saves the new baseline to
   `<data dir>/state/`. The field meanings are in
   `references/summary-contract.md`.

   When the user asks about changes over a longer period ("what changed this
   month", "since last week"), add `--compare-to <N>d` (N from 1 to 30, e.g.
   `--compare-to 7d`): the run then compares with the saved state at least N
   days old instead of the latest run (`baseline.reference`,
   `baseline.reference_file`). Without such a question run it without the
   flag. The flag changes nothing but the data directory; every run, with or
   without it, also keeps a day copy of the baseline in
   `<data dir>/state/history/` (30 days).

2. Read the summary. If you need one item in full (for example a failure
   group left out by `truncated`), fetch it:

   ```
   python -B skills/ush-health/scripts/health.py --detail <id> --detail-file <detail_file>
   ```

   `<detail_file>` is the `detail_file` value from the summary, so the item
   comes from the same run that the report checker checks against.

   Ids: `k..` disks, `v..` volumes, `p..` devices, `u..` update failure
   groups, `c..` changes. Remember every id you fetched and used.

3. Judge the findings: what is a real fault, what is harmless, what needs
   watching. Weigh them with the scale in the shared contract
   `skills/ush-common/references/summary-contract.md` (`high`, `medium`,
   `low`). The script sets no threshold: the judgement is yours, from the
   numbers.

4. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/health-<YYYY-MM-DD-HHMM>.md` (local time of the run).
   The first line is `<!-- ush:summary <summary_file> -->` with the absolute
   `summary_file` path from the summary.

5. Every recommendation carries `weight`, `kind` (`change`, `observe`,
   `consult_service`), `risk`, `evidence` (numbers and ids from the JSON),
   `permissions` and `rollback`, as defined in the shared contract.

6. After saving, run:

   ```
   python -B skills/ush-common/scripts/check_report.py "<absolute data dir>/reports/health-<YYYY-MM-DD-HHMM>.md"
   ```

   (`python -B skills/ush-common/scripts/check_report.py --latest --skill ush-health`
   checks the newest `health-*.md` instead.) The checker is shared by all
   skills; it reads the ush-health rules from `data/report-profile.json`.

   It prints `OK` when every number is backed by the JSON, every disk,
   volume, device, update failure group and change of the summary is named, and the
   markers are in place. `OK` means each number occurs somewhere in the JSON,
   not that it is used for the right thing, so the rule above still binds
   you. Otherwise it names each unbacked number with its line: remove or
   correct it (or fetch the item with `--detail` and name its id in
   `ush:detail`), save, and run the check again. A line
   `not named in the report: <id> (<list>)` means the report leaves out that
   item: name it in its section, save, and run the check again. Do not hand
   the report to the user before it prints `OK`.

7. Tell the user where the report is and give the dashboard and the main
   findings in a few lines.

8. Only when `elevated` is `false` and some sources were not read because
   they need administrator rights (`needs administrator` in `not_checked`):
   offer the user this block for an elevated PowerShell, with the absolute
   project root and the absolute data directory filled in. Do not run it
   yourself.

   ```
   # Runs the same read-only health check with administrator rights, so it also
   # reads the disks' reliability counters, Win32_Tpm, the restore points and
   # WinRE. It changes nothing on the machine and writes only to <data dir>\work\
   # and to <data dir>\state\ (its id map and a separate elevated baseline,
   # ush-health.elevated.json, with its day copies in state\history\).
   Set-Location "<absolute project root>"
   python -B skills/ush-health/scripts/health.py --data-dir "<absolute data dir>"
   ```

   After the user says it ran, read the new summary: the newest
   `<data dir>/work/health-*.summary.json`, whose `elevated` must be `true`
   (otherwise the block did not run elevated: say so). Then write the whole
   report again from that one summary, as in steps 3-6: a new
   `ush:summary` line, a new report file name, and the checker run on it
   until it prints `OK`. Never merge two summaries into one report: the
   elevated run reads a superset of the sources. The earlier report stays
   as it is.

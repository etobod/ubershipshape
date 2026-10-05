---
name: ush-settings
description: Check whether the privacy, telemetry, ads, AI, update, security, power, network, storage and permission settings of this Windows machine are as the user wants them, from a catalogue of settings with their expected values; show the effective value of each and where it comes from (policy, preference, Windows default, the system itself), what changed since the last run, and which apps used the camera, microphone and location. Use when the user asks whether their settings are right, what changed in their settings, whether telemetry, ads or Copilot are off, whether Defender, the firewall or UAC are on, or who used the camera or microphone. Read-only; gives paste-ready blocks the user runs themselves.
---

# ush-settings

Reads every setting of `data/settings-catalogue.json` through read-only
PowerShell jobs, works out its effective value and where that value comes
from, says whether it is one of the catalogue's expected values, and
compares everything with the baseline of the previous run. A script counts
and matches; you judge and write a Markdown report; the user decides what to
act on.

## When to use

- The user asks whether their privacy, security, power or network settings
  are the way they want them.
- The user asks what changed in their settings since the last run (after an
  update, after installing something).
- The user asks which apps used the camera, the microphone or the location,
  and when.

Not for: processes running now (`ush-processes`), installed programs and
autostart (`ush-inventory`), Defender exclusions and scan history, the event
logs (`ush-events`), the health of disks and updates (`ush-health`), applying
a change automatically. Say so if the user asks for these.

## Rules

- **Read-only.** `settings.py` changes nothing on the machine and writes only
  to `<data dir>`. `--block` only prints commands. The skill never applies a
  change: the user pastes the block into the shell it names, and you then
  read the value back by running the skill again.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a setting.
- **Read only the summary JSON.** Never open the raw captures or other files
  in `<data dir>/work/`. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the scripts write:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  `%LOCALAPPDATA%\ubershipshape`. Take its absolute value from the summary's
  `summary_file` (the directory above `work/`). In the report text outside
  code blocks write it as `&lt;data dir>` in plain text, never the expanded
  path: it contains the account name, which a report must not carry
  (`references/report-format.md`).
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. Do not count entries, add up the counts or
  compute an age yourself.
- **`default` is the effective state when no key is set, not "off".** An
  entry with `source` `default` has the catalogue's documented Windows
  default as its `effective` value; write it as "Windows default: <value>".
- **`from_policy_on_home` `true`** means the value comes from a policy key on
  a Home edition, where Windows may ignore that policy: write "set by policy,
  effect not confirmed on Home", never "enforced". `null` means the edition
  was not read.
- **`differs` is a fact, not a verdict.** It says only that the value is not
  on the catalogue's expected list. You judge whether it matters, from the
  entry's `rationale` (fetch it with `--detail`).
- **`strict` entries are recommended only with their cost named**, taken from
  the `rationale` (what the user loses: a feature, a convenience). A
  `standard` entry that differs may be recommended plainly.
- **Every recommendation carries** `weight`, `kind`, `risk`, `evidence`,
  `permissions` and `rollback`, as defined in the shared contract
  `skills/ush-common/references/summary-contract.md` ("Recommendations").
- **Empty is not unreadable.** `not_read`, `default_unknown`, a source with
  `status` `unreadable`, a comparison `not_read` or `no_baseline`, a first
  run, `hkcu_elevated`, or `truncated` > 0 must be reported as such (see the
  degradation cases in `references/report-format.md`), never as "fine" or
  "no changes".

## Steps

1. From the project root run, in a normal (non-elevated) shell:

   ```
   python -B skills/ush-settings/scripts/settings.py
   ```

   It prints the summary JSON on stdout and writes it, with a detail file, to
   `<data dir>/work/`, and saves the new baseline to `<data dir>/state/`.
   The field meanings are in `references/summary-contract.md`.

   When the user asks about changes over a longer period ("what changed this
   month", "since last week"), add `--compare-to <N>d` (N from 1 to 30, e.g.
   `--compare-to 7d`): the run then compares with the saved state at least N
   days old instead of the latest run (`baseline.reference`,
   `baseline.reference_file`). Without such a question run it without the
   flag. The flag changes nothing but the data directory; every run, with or
   without it, also keeps a day copy of the baseline in
   `<data dir>/state/history/` (30 days).

2. Read the summary. For the `rationale`, `manual`, `locations` or `adapters`
   of an entry listed in the summary, fetch the item (a change `c..` holds
   only its `entry`, `before` and `after`; the entry's `rationale` is known
   only while the entry is listed):

   ```
   python -B skills/ush-settings/scripts/settings.py --detail <id> --detail-file <detail_file>
   ```

   `<detail_file>` is the `detail_file` value from the summary, so the item
   comes from the same run that the report checker checks against. Ids: `e..`
   settings, `c..` changes, `u..` camera, microphone and location usage.
   Remember every id you fetched and used. Entries that match are only
   counted in the summary; their ids are not known, so do not fetch them.

3. Judge the findings: which `differs` entries matter to this user, which
   `not_read` entries hide something, which changes are worth a look, which
   usage is unexpected. Weigh them with the scale of the shared contract
   (`high`, `medium`, `low`). The script sets no threshold: the judgement is
   yours.

4. For every entry you recommend changing that has `has_block` `true`, get
   the block:

   ```
   python -B skills/ush-settings/scripts/settings.py --block e3,e7 --detail-file <detail_file>
   ```

   Put its output unchanged into the report as a ```` ```powershell ```` code
   block and say which part goes to which shell: the part under "Run in a
   normal (non-elevated) Windows PowerShell" in the user's own normal shell,
   the part under "Run in an elevated Windows PowerShell" in a shell started
   with "Run as administrator"; the rollback parts undo them in the same
   shells. Lines starting with `#` that say "no block" give the reason an
   entry got no command; report that reason. An entry with `has_block`
   `false` gets its `manual` step in words instead.

5. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/settings-<YYYY-MM-DD-HHMM>.md` (local time of the
   run). The first line is `<!-- ush:summary <summary_file> -->` with the
   absolute `summary_file` path from the summary.

6. After saving, run:

   ```
   python -B skills/ush-common/scripts/check_report.py "<absolute data dir>/reports/settings-<YYYY-MM-DD-HHMM>.md"
   ```

   (`--latest --skill ush-settings` checks the newest `settings-*.md`
   instead.) The checker is shared by all skills; it reads the ush-settings
   rules from `data/report-profile.json`. Correct the report and run the
   check again until it prints `OK`. `OK` means each number occurs somewhere
   in the JSON, not that it is used for the right thing, so the rules above
   still bind you. Do not hand the report to the user before it prints `OK`.

7. Tell the user where the report is and give the dashboard and the main
   findings in a few lines.

8. After the user says they pasted a block, run `settings.py` again in a
   **normal (non-elevated)** shell and check that each changed entry now has
   `state` `matches` and appears in `changes`; write a new report from that
   run. Every entry with a block can be read without administrator rights
   (the catalogue validator enforces it), so a normal run is enough. A
   message from PowerShell that it finished is not a read-back.

Optional: when the user wants the entries that need administrator rights
(`vss_max_space`) read as well, give this block for an elevated shell. Do not
run it yourself.

```
# Runs the same read-only settings check with administrator rights. It changes
# nothing on the machine and writes only to <data dir>\work\ and
# <data dir>\state\ (a separate elevated baseline, ush-settings.elevated.json,
# and the id map, ush-settings.ids.json).
Set-Location "<absolute project root>"
python -B skills/ush-settings/scripts/settings.py --data-dir "<absolute data dir>"
```

Say that this run compares only with the elevated baseline, so its first run
has no comparison, and that in it the `HKCU` values, the per-user apps and
the usage are those of the account that elevated the shell, which may not be
the user's (entries with `hkcu_elevated` `true`; `--block` gives no normal-
shell commands from such a run). After the user says it ran, read the newest
`<data dir>/work/settings-*.summary.json`, whose `elevated` must be `true`
(otherwise say that the block did not run elevated), and write a new report
from that one summary. Never merge two summaries into one report.

# Report format (ush-packages)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/packages-<YYYY-MM-DD-HHMM>.md` (local time of
the run) and checked with
`python -B "<plugin root>/skills/ush-common/scripts/check_report.py" <report>` (or
`--default-data-dir "<plugin data>" --latest --skill ush-packages` for the newest `packages-*.md`), which
reads the ush-packages rules from `data/report-profile.json`.
Follow `<plugin root>/skills/ush-common/references/report-style.md`: it says how every
report is written (time, numbers, dash, recommendation layout, language);
this file says what the ush-packages report contains.
`<data dir>` is the data directory (`--data-dir`, else `USH_DATA_DIR`, else
the plugin data folder (`--default-data-dir`)); its absolute value is the directory above
`work/` in the summary's `summary_file`. The report text outside code blocks
writes it as `&lt;data dir>` in plain text, never in inline code (a `<`
before a letter fails the check, and inline code shows `&lt;` as it is), and
never the expanded path: it contains the account name, which a report must
not carry. The expanded path appears only in the `ush:summary` marker.

The markers below are HTML comments: they do not depend on the report
language and do not show in a preview. Each marker stands on its own line,
outside quotes and lists; no other HTML comment is allowed. This file stays
in English; the report translates every heading and label, the table header
included.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. The checker is
shared by all skills (see `<plugin root>/skills/ush-health/references/report-format.md`,
"Numbers", for the full list); in short:

- Every run of digits is a separate number: `2.32.0` is 2, 32 and 0,
  `2026-11-09` is 2026, 11 and 9. A version is written as the JSON has it
  (it is a name, not a decimal number), with its dots.
- Names back their own digits: a package's `name`, `version` and `python`
  (`PythonCore/3.12`), a change's `name`, `version` and `fields`, and the
  other text values of the summary. `summary_file`, `detail_file`,
  `folder`, `entry`, `prefix_from`, `install_path` and `reference_file`
  back no number (the profile's `path_keys`): a number in a folder path is
  never written as a reading.
- Item ids (`k1`, `c2`) are not numbers when they name an item of the
  summary, an item named in `ush:detail` or an item cut from the summary
  (`truncated`, `truncated_changes`). A word of that shape that is no such
  id is checked as a number.
- Write every number in digits: a number word (`dwa`, `trzy`, `two`, in any
  case or form) outside code fails the check unless the same word is in a
  text value of the summary (a name). `ten`, `jeden`, `one` and `oba` are
  not number words.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Changes`)
  is fine when the numbering of its level counts from 1 in order. The first
  cell of a table row is ignored when it equals the row's position among the
  table's data rows, so never put a count there.
- Fenced code blocks are not checked: never put a finding's number in one.
- No HTML and no links outside code blocks: write a literal `<` as `&lt;`
  and a literal `]` before `(` or `:` as `&rsqb;`.

## Items the report must name

Every `packages[*].id` (`k..`) and `changes[*].id` (`c..`) of the summary
appears in a visible line of the report, as a word of its own (`k12` does
not name `k1`). Several ids on one line are fine. A mention inside a fenced
code block or on a marker line does not count. The check lists each missing
id as `not named in the report: <id> (<list>)` and fails. Items cut from the
summary and items fetched with `--detail` are not required. The summary must
also have `managers` (the profile's `required_keys`): a summary of an older
shape without it fails the check.

## Layout

The summary section of rule 15 "Summary first" in `report-style.md` comes
first, directly after the header (the `ush:summary` line, the title and its
line) and before the dashboard, which follows it under a `##` heading of
its own (item 2; the section runs to the next `##` heading, so nothing
without a heading may stand below it). The `<!-- ush:attention -->` line
stands directly above its `##` heading. Part 1 names each high or medium
recommendation of this report by its main source (the first id of its
`Dowód`). Part 2 says „nie dotyczy: decyzje sprawdza ush-runall”: this
skill checks no decisions. Part 3 names the open plans of
`<data dir>/plans/` (not `done/`) in a fenced code block. The last line
gives the count of low recommendations whose main source no line names.

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

   Then the title with the time of the run (`generated_at`, in local time
   with the UTC time in brackets, rule 1 of `report-style.md`), and one
   line: that the packages were read offline from the files on disk (no
   package manager ran, nothing went online), and whether the run was
   elevated (`elevated`).

2. Dashboard, directly after the summary section, under its own `## Overview`
   heading (in a Polish report `## Przegląd`): a table with one row per
   manager of `managers`, in the summary's order, with its state and its
   package count:

   | Manager | State | Packages |
   |---|---|---|
   | pip | read | PythonCore/3.12: 12 |
   | npm | npm not present | 0 |
   | winget | not read yet | not read |

   - pip: the cell names each Python of `managers.pip.pythons` with its
     `count`, or „not read” when a `count` is `null`; never add them up.
   - npm: `managers.npm.count`; `null` is „not read”, never 0. `status`
     `empty` is „npm not present” in the State cell.
   - A manager with `state` `not_read` is „not read yet” in the State cell
     and „not read” in the Packages cell, never „not present”, „none” or 0.
   - `state` `unreadable`: „could not be read”, with the reason in „Not
     checked”.

   Under the table, one line with `counts.packages` and `counts.changes`.

3. Changes since the last run. One line on the comparison: with
   `baseline.status` `compared`, the baseline's `created_at` (rule 1 of
   `report-style.md`) and `age_days`, and with `baseline.reference` other
   than `latest` that the run compared with the saved state of
   `baseline.reference`. Then every change of `changes`, one bullet each:
   its id, `name`, the Python for pip (`python`), and what changed: `added`
   with `version`, `removed` with `version`, `changed` with `fields.version`
   `before` and `after`. With `truncated_changes` above 0, one line: how
   many changes were cut and that the detail file has them. A source with
   comparison `no_baseline` (a first run) or `not_read` gives no changes:
   say so for that source, never „no changes”.

4. Installed packages, one `###` heading per read manager (pip, npm), each
   package of `packages` one bullet with its id, `name`, `version`, and the
   place: for pip the Python (`python`) and the folder (`install` or
   `user`), for npm „global folder”. Every package carries the words „not
   checked for updates” (in a Polish report „nie sprawdzono pod kątem
   aktualizacji”): no ush-advice lookup exists yet. Rule 7 (long lists) of
   `<plugin root>/skills/ush-common/references/report-style.md` applies: with
   many packages, the ones you say something about come in full and the
   rest of a manager in one compact line of ids and names, still marked
   „not checked for updates” once for the line. With `truncated` above 0,
   one line: how many packages were cut and that the detail file has them.

   A package is worth a look only for a fact of the JSON: `unreadable`
   (its metadata could not be read, with `reason`), a second entry of the
   same name in one folder (a key ending in `|<entry>`), or `from_baseline`
   (kept from the baseline because its folder could not be read in this
   run). Say which fact and why it matters. Never call a package removable,
   unused or old without such a fact.

5. Recommendations, where you have any: each with `weight`, `kind`, `risk`,
   `evidence` (ids and values from the JSON), `permissions` and `rollback`
   in the layout of rule 4 of `<plugin root>/skills/ush-common/references/report-style.md`
   (the fields are in `<plugin root>/skills/ush-common/references/summary-contract.md`,
   "Recommendations"); with none, write the sentence of rule 14 there. This
   skill gives no block: installing, updating or removing a package is the
   user's step outside this skill.

6. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail k3 c1 -->
   ```

   A named id that is not in the detail file fails the check.

7. Not checked, always last. Its marker stands directly before (or right
   after) the section heading:

   ```
   <!-- ush:not-checked -->
   ## Not checked
   ```

   It lists every `not_checked` item with its `what` and `reason` (every
   manager not read yet among them), names every `unreadable` source, and
   says that no package was checked for a newer version (no ush-advice
   lookup yet).

## Account names

A report never carries the account name, except in the `ush:summary`
marker, which the checker needs. A `folder` of an npm package, an `entry`
and a `not_checked` reason often start with the profile folder,
`C:\Users\` followed by the account name: write that folder as
`%USERPROFILE%` (`%USERPROFILE%\AppData\Roaming\npm`).

## Values that are not readings

- `null` is „not read”, in words, never „no”, „none” or „0”.
- A field in `unread_fields` is unknown in this run; never judge from it.
- `state` `not_read`: the manager was not read by this skill yet. It is
  never absent, missing or not installed.
- `from_baseline` `true`: the item is the previous baseline's, kept because
  its folder could not be read in this run; it is not a new reading.

## Degradation cases

Never report missing data as „none” or „nothing there”:

- pip `status` `unreadable` (`pythons` `null`): the PEP 514 registrations
  could not be read, or every registered Python is a Microsoft Store install
  or has no InstallPath, so none was read (their packages are kept from the
  baseline); give the reason from „Not checked”, name each such Python as
  registered but not read, never „no Python”.
- pip `pythons` `[]`: no Python whose packages were read. When „Not
  checked” names a `pip_packages registration` entry, name each such Python
  as registered but not read; only with none is it „no Python registered”.
- A Python whose `count` is `null`: one of its folders could not be
  listed; its packages there are kept from the baseline (`from_baseline`).
- npm `status` `empty`: „npm not present” at the prefix read (no global
  `node_modules`, or no package in it); say with it, from „Not checked”,
  that the other prefixes (the global or builtin npmrc and the folder of
  node.exe) were not searched, so npm may still be installed elsewhere.
- npm `status` `unreadable` or a `count` of `null`: „could not be read”,
  never 0; give the reason from „Not checked”.
- A first run (`baseline.status` `none`, comparison `no_baseline`): no
  changes can be given; say that this run is the baseline for the next.
- `baseline.status` `unreadable` or `baseline.saved` `false`: say so with
  the reason; the next run may report changes against an older state.
- Packages or changes cut (`truncated` or `truncated_changes` above 0):
  give the numbers and say that the detail file has them.
- A `stable ids` or `stable ids save` item: the ids of this run may differ
  from those of earlier or later reports; say so in „Not checked”.

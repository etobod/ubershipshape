# Report format (ush-health)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/health-<YYYY-MM-DD-HHMM>.md` (local time of the
run) and checked with
`python -B skills/ush-common/scripts/check_report.py <report>` (or
`--latest --skill ush-health` for the newest `health-*.md`), which reads the
ush-health rules from `data/report-profile.json`.
Follow `skills/ush-common/references/report-style.md`: it says how every
report is written (time, numbers, dash, recommendation layout, language);
this file says what the ush-health report contains.
`<data dir>` is the data directory (`--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`); its absolute value is the directory
above `work/` in the summary's `summary_file`. The report text outside code
blocks writes it as `&lt;data dir>` in plain text, never in inline code (a
`<` before a letter fails the check, and inline code shows `&lt;` as it
is), and never the expanded path: it contains the account name, which a
report must not carry. The expanded path
appears only in the `ush:summary` marker and in code blocks.

The markers below are HTML
comments: they do not depend on the report language and do not show in a
preview. Each marker stands on its own line, outside quotes and lists; no
other HTML comment is allowed. This file stays in English; the report
translates every heading and label, the dashboard header included.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. The checker is
shared by all skills; its rules in short:

- `0x...` is one hex number, backed only by a hex value of the JSON:
  `0x8024200B` by an `hresult`, `0x61100` by a `product_state`. Every other
  run of digits is a separate number: `12.3` is 12 and 3, `2026-09-01` is
  2026, 9 and 1. Write a number with the same digits and precision as the
  JSON, with the decimal separator of the report language (rule 2 of `report-style.md`) (in Polish `12,3`, never `12,30` or `12,35`), and counts
  without a thousands separator.
- Names back their own digits: a disk's `friendly_name`, a device's `name`,
  an update's `title` and the other text values of the summary. A device
  called `Invented Adapter 6 AX201` may be written with its name. Only
  `summary_file` and `detail_file` (paths; a path may appear only in a
  fenced code block) and the detail identifiers `device_id`, `unique_id`
  and `instance_id` back no number. Never write a disk's `unique_id` or a
  device's `instance_id` in the report: they may hold a serial number.
- Item ids (`k1`, `v2`, `p3`, `u4`, `c5`) are not numbers when they name an item of
  the summary, an item named in `ush:detail` or a failure group cut from the
  summary (`truncated`); the `id` values back no number, so a count next to
  an id must come from a reading. A word of that shape that is no such id is
  checked as a number.
- Write every number in digits. A number word from
  `skills/ush-common/data/number-words.json` (Polish cardinals from 2 to
  20, the tens and the hundreds in every case, e.g. `dwa`, `dwie`, `trzema`,
  `sto`, `stu`, and the singular of the word for thousand; English `two` to
  `twenty`, the tens, `hundred` and `thousand`) fails the check outside code blocks and
  inline code, in any case. A word counts only whole: a letter, a digit,
  `_` or a hyphen next to it makes it another word (`two-factor`). A word
  that also stands in a text value of the summary or of an `ush:detail`
  item (a name like `Invented Two Sync`) is fine; keys and the path and id
  keys back no word, as for digits. `ten`, `jeden`, `one`, `oba`, `both`,
  ordinals and collective numerals are not on the list.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Volumes`) is
  fine when the numbering of its level counts from 1 in order; write every
  heading with `#`. The first cell of a table row is ignored when it equals
  the row's position among the table's data rows, so never put a count
  there.
- Fenced code blocks (the paste-ready commands) are not checked: never put a
  finding's number in one. A fence starts at most 3 spaces in, at the top
  level or directly in a first-level `-` item, never on the line of the list
  marker; the closing fence has the same indent and character as the
  opening one. A block left open fails the check.
- No HTML and no links outside code blocks: `<` before a letter, `?`, `!`
  or `/`, and `](` or `]:` fail the check. Write a literal `<` as `&lt;` and
  a literal `]` before `(` or `:` as `&rsqb;`.
- Do not add up, average, round again or convert numbers yourself: no GB
  from bytes, no percent from two capacities, no days from a date. Every
  percent, size and age the report needs is in the JSON. Write a JSON time
  with a zone in local time with its UTC time in brackets (rule 1 of
  `report-style.md`); the check verifies the pair.

## Items the report must name

Every `disks[*].id`, `volumes[*].id`, `devices[*].id`,
`updates.failures[*].id` and `changes[*].id` of the summary appears in a
visible line of the report, as a word of its own (`p12` does not name `p1`).
A change's `item` is the id of the disk, volume or device it is about (or
`null`); like an `id` it backs no number. A mention inside a
fenced code block or on a marker line does not count. The check lists each
missing id as `not named in the report: <id> (<list>)` and fails. A list
that is `null` requires nothing. Failure groups cut from the summary
(`truncated`), items fetched with `--detail` and the TPM devices
(`tpm.devices`, which have no ids) are not required.

## Layout

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

   The path is the `summary_file` value from the summary.

2. Title and one line: when the summary was made (`generated_at`, rule 1 of
   `report-style.md`) and
   whether the run was elevated (`elevated`). Without elevation say that the
   sources which need administrator rights are in "Not checked".

3. Dashboard: a table with one row per area, in the order of the sections
   below.

   | # | Area | State | Action |
   |---|---|---|---|
   | 1 | Storage | Disk k1 Invented-SSD Healthy; volume v1 C: 12,3% free | 🔍 watch free space |
   | 2 | Devices | p1 Invented-Adapter Error | 🔧 see below |

   `#` is the section number of the area, `State` a few words with the ids
   and the numbers from the JSON, `Action` a legend symbol and a few words
   (no numbers of your own). An area whose sources were not read says so in
   `State` (❌ is not for that: see the legend).

4. Legend, under the dashboard:

   - 🔧 change — a fault the user can fix; the section gives the steps.
   - 🔍 observe or check — not clear yet, not read, or worth watching; run
     again later (elevated), or check one more thing (including
     `consult_service`).
   - ✅ fine — read and nothing wrong.
   - ❌ problem found — a fault with no fix the user can apply themselves
     (for example a failing disk or battery); the section says who can help.

5. One section per area (`## 1. <area>`, `## 2. <area>`, in order from 1),
   in this order:
   - Storage: every disk (`k..`) with `health_status`,
     `operational_status`, `size_gb` and, when read, its `reliability`
     values; every volume (`v..`) with `size_gb`, `free_gb`, `free_percent`
     and its encryption (`protection`, see below).
   - Battery: `present`, the capacities, `full_charge_percent_of_design` and
     `cycle_count`.
   - Devices: every device (`p..`) with its `name`, `class`, `status` and
     `problem`; the counts of `devices_by_status` as written.
   - Updates and Windows version: `os_version`, `by_result` as written,
     every failure group (`u..`) with its `title`, `result`, `hresult`,
     `count`, `first` and `last`, and the three `pending_reboot` signals,
     each on its own.
   - Antivirus: each product with `display_name` and `product_state` (raw),
     and Defender's `running_mode`, `real_time_protection_enabled`,
     `signature_age_days`, `quick_scan_age_days` and `signature_updated`.
   - Recovery: `restore_points` (`count`, `newest`, `oldest`) and `winre`
     (`status` as written).
   - Boot security: `secure_boot` (`enabled`, `firmware_type`) and `tpm`
     (its devices and, when read, `spec_version`, `is_enabled`,
     `is_activated`).
   - Changes since the last run: first the baseline: `Compared with the
     baseline of <created_at as in rule 1 of report-style.md>,
     <baseline.age_days> days old.`, or "no comparison" with the reason (see
     "Degradation cases"). With `baseline.reference` other than `latest`,
     say it is the saved state from `reference_file`, not the latest run.
     Then every change (`c..`) with its `source`, `kind` (`added`,
     `removed`, `changed`), its `item` when not `null` and its `name`, and
     for `changed` each field of `fields` with its `before` and `after` as
     written. Give only `before` and `after`: never a difference you
     computed (no "12,3 GB less"), and no judgement inside the list. A
     `free_gb` that moved is a measurement of the day, not a fault in
     itself; weigh it, if at all, in the Storage section from the current
     readings. `changes` `[]` with every source of `comparison` `compared`
     and no `... not compared: ...` item in `not_checked`: "no changes since
     the baseline" (✅). With such an item, say no changes were found among
     the items compared and name what was not compared (never ✅).

   Each section gives what was read, with the numbers and ids from the JSON,
   the judgement, and for each finding a recommendation with `weight`,
   `kind`, `risk`, `evidence`, `permissions` and `rollback` in the layout of
   rule 4 of `skills/ush-common/references/report-style.md` (the fields are
   in `references/summary-contract.md`). A `change` gives a paste-ready block
   and how to read the value back afterwards. An area with nothing wrong gets
   one or two lines, not a recommendation.

6. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail u14 p2 -->
   ```

   Without this line only the summary backs the numbers. A named id that is
   not in the detail file fails the check.

7. Not checked, always last. Its marker stands directly before (or right
   after) the section heading:

   ```
   <!-- ush:not-checked -->
   ## Not checked
   ```

   It lists every `not_checked` item with its `what` and `reason`, and names
   every `unreadable` source. A `needs administrator` item is written as
   "needs administrator rights", never as "none" or "off". If `not_checked`
   is `[]`, it says "nothing".

## Values that are not readings

- `null` is "unknown" (or "not read"), in words, never a number, never
  "no", "off" or "0". This covers the sentinels the script turned into
  `null`: `signature_age_days` (Defender's 65535), `quick_scan_age_days`
  (4294967295), `cycle_count` (a battery that reports 0 cycles; a new
  battery also reports 0, so the count is unknown either way) and
  `temperature_c` (a drive that reports 0). Never write the sentinel
  number itself.
- `protection`: `1` is BitLocker on, `2` is off. Any other value is given
  raw ("protection value 3, meaning not documented here"), with no
  conclusion about encryption. `null` is unknown.
- `product_state` is given raw, as written (`0x61100`), with no conclusion:
  its bits are not documented. Whether a product is on comes from
  Defender's fields, when read, not from `product_state`.
- `secure_boot.enabled` `null` is unknown, not off.
- `pending_reboot.file_rename_operations` `true` on its own (the other two
  `false`) is a weak signal: some software leaves it set for good. Say so,
  and never weigh it as a reboot that Windows Update requires.
- `winre.status` is given as written; the report does not translate it into
  a state the script did not read.

## Degradation cases

Never report missing data as "clean":

- A source with `status` `unreadable`: that source could not be read; give
  the `reason` and draw no conclusion for it. With the reason `needs
  administrator` (`disk_reliability`, `restore_points`, `winre`, and the
  item `tpm_wmi`), say the check needs an elevated run and offer it (step 8
  of `SKILL.md`); never "no restore points" or "WinRE off".
- A source with `status` `empty`: read, and nothing there - a finding in its
  own right: no failed update in the history (`failures` `[]` with
  `update_history` `read`), no restore points (`count` 0), no battery
  (`present` `false`), no volume with a letter.
- `devices` `[]`: every present device reports `OK` (✅). `devices` `null`:
  not read.
- `update_history` `empty`: the history holds no entries at all; it may have
  been cleared. Say so (🔍), never "all updates succeeded".
- `tpm.devices` `[]` with `tpm_wmi` in "Not checked": no TPM was found as a
  device and `Win32_Tpm` was not read; do not conclude that there is no TPM.
- `antivirus` with `products` or `defender` `null`: that part was not read
  (its item is in "Not checked"); report the other part only. `antivirus`
  `null`: nothing about the antivirus is known.
- `battery.present` `true` with the capacities `null` and `battery`
  `unreadable`: a battery is there but its report could not be read.
- A disk with `reliability` `null`: its counters were not read (see "Not
  checked"), not "no errors".
- `truncated` > 0: say how many failure groups were left out of the summary
  (the oldest) and that the detail file has them; their ids follow the last
  one in the summary. Fetch one with `--detail` if it matters.
- No baseline (`baseline.status` `none`, `reference` `latest`): a state of
  its own, "no comparison: this is the first run; the next run compares
  with this one", never "no changes since the last run". The first
  elevated run is also a first run: it compares only with the elevated
  baseline; say so.
- A baseline that could not be read (`baseline.status` `unreadable`, the
  item `baseline` in "Not checked"): nothing was compared; give the
  `reason`.
- `baseline.saved` `false` (item `baseline save`): the next run compares
  with the older baseline.
- `baseline.reference` other than `latest` (the run had `--compare-to`):
  say that the comparison is with the saved state from `reference_file`,
  `age_days` days old, not with the latest run. `status` `none` then means
  "there is no saved state from at least N days ago" (give the `reason`),
  not a first run and never "no changes". `status` `unreadable` with the
  item `reference baseline` in "Not checked": that copy could not be read,
  so nothing was compared; give the `reason`. A latest baseline that could
  not be read (item `baseline`, "the latest baseline could not be read")
  does not stop that comparison: say that sources not read in this run
  keep nothing.
- Item `baseline history` ("history not kept"): this run's baseline has no
  day copy, so a later `--compare-to` may not find it. With the reason "the
  day copy was kept, but old copies were not removed": the copy is there;
  only older copies stay longer than 31 days. Not a missing history.
- `comparison` `not_read` or `no_baseline` for `disks`, `volumes`,
  `devices` or `os`: no comparison for that source this time; its
  previous items stay in the baseline, so the next successful read gives
  no false change.
- Item `disk not compared: no UniqueId` (or `repeated UniqueId`) and
  `device not compared: no InstanceId` (or `repeated InstanceId`), and
  `volume not compared: repeated drive letter`: that disk, device or volume
  is in its section as read, but it is neither kept in the
  baseline nor compared; never "unchanged". With `no ...`, say that
  removed disks (or devices) were not checked this time: no `removed`
  change of that source means nothing, and the saved ones not seen stay in
  the baseline. With `repeated ...`, that key gives no change at all.
- Item `<source> not compared: <fields>` (e.g. `volumes not compared:
  protection`): those fields had no value in this run or in the run
  compared with, for the number of items the reason gives, so they were
  not compared there. Name the fields and say that a change of them would
  not show; never "unchanged" for them (and no ✅, see the changes row).

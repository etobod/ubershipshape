# Report format (ush-settings)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/settings-<YYYY-MM-DD-HHMM>.md` (local time of
the run) and checked with
`python -B skills/ush-common/scripts/check_report.py <report>` (or
`--latest --skill ush-settings` for the newest `settings-*.md`), which reads
the ush-settings rules from `data/report-profile.json`. `<data dir>` is the
data directory (`--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`); its absolute value is the directory above
`work/` in the summary's `summary_file`. The report text outside code blocks
writes it as `&lt;data dir>` in plain text, never in inline code, and never
the expanded path: it contains the account name, which a report must not
carry. The expanded path appears only in the `ush:summary` marker and as the
`--data-dir` value of a block for an elevated shell.

The markers below are HTML comments: they do not depend on the report
language and do not show in a preview. Each marker stands on its own line,
outside quotes and lists; no other HTML comment is allowed. This file stays
in English; the report translates every heading and label, the dashboard
header included.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. The checker is
shared by all skills (see `skills/ush-health/references/report-format.md`,
"Numbers", for the full list); in short:

- Every run of digits is a separate number: `2026-05-07` is 2026, 5 and 7.
  Write a number exactly as the JSON has it.
- Names back their own digits: an entry's `title` and `entry`, a usage
  item's `app`, and the other text values of the summary. `summary_file` and
  `detail_file` are paths and back no number (the profile's `path_keys`).
- A registry location (`locations`, `source_location`) is only in the detail
  file. A report that quotes one outside a code block (a value name with
  digits such as `SubscribedContent-338389Enabled`, or its path) fetches the
  entry with `--detail` and names it in `<!-- ush:detail e<n> -->`.
- Item ids (`e1`, `c2`, `u3`) are not numbers when they name an item of the
  summary, an item named in `ush:detail` or a usage item cut from the summary
  (`truncated`). A word of that shape that is no such id is checked as a
  number.
- Write every number in digits: a number word (`dwa`, `trzy`, `two`, in any
  case or form) outside code fails the check unless the same word is in a
  text value of the summary (a name). `ten`, `jeden`, `one` and `oba` are
  not number words.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Privacy`)
  is fine when the numbering of its level counts from 1 in order. The first
  cell of a table row is ignored when it equals the row's position among the
  table's data rows, so never put a count there.
- Fenced code blocks (the paste-ready commands) are not checked: never put a
  finding's number in one.
- No HTML and no links outside code blocks: write a literal `<` as `&lt;`
  and a literal `]` before `(` or `:` as `&rsqb;`. A registry path or a
  command belongs in inline code or a code block.
- Do not add up, subtract or convert numbers yourself: the counts per state
  and area are in `counts`, the baseline age is `baseline.age_days`.

## Items the report must name

Every `settings[*].id`, `changes[*].id` and `usage[*].id` of the summary
appears in a visible line of the report, as a word of its own (`e12` does not
name `e1`). Several ids on one line are fine (`e4, e5: ...`). A mention inside
a fenced code block or on a marker line does not count. The check lists each
missing id as `not named in the report: <id> (<list>)` and fails. Usage items
cut from the summary (`truncated`) and items fetched with `--detail` are not
required.

## Layout

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

2. Title and one line: when the summary was made (`generated_at`, UTC),
   whether the run was elevated (`elevated`) and the edition (`edition_id`).

3. Dashboard: a table with exactly one row per numbered section below
   ("Not checked" has none), in the same order, so that `#` is both the
   section number and the row's position.

   | # | Area | State | Action |
   |---|---|---|---|
   | 1 | Changes | c1 changed | 🔍 see below |
   | 2 | Privacy | e1 differs | 🔧 see below |
   | 3 | As expected | the other settings match | ✅ nothing to do |
   | 4 | Camera, microphone, location | u1 | ✅ nothing to do |

   `State` is a few words with the ids and the numbers from the JSON
   (`counts.by_area`), `Action` a legend symbol and a few words (no numbers
   of your own). An area whose sources were not read says so in `State`.

4. Legend, under the dashboard:

   - 🔧 change - a setting the user may want to change; the section gives
     the block or the manual step.
   - 🔍 observe or check - not read, not clear yet, or worth a look.
   - ✅ fine - read and as expected.
   - ❌ problem found - something the user cannot fix with a block from this
     skill; the section says who can help.

5. Sections, each `## <n>. <name>` in order from 1:

   - Changes since the last run: first the baseline: `Compared with the
     baseline of <created_at date>, <baseline.age_days> days old.`, or "no
     comparison" with the reason (see "Degradation cases"). Then every change
     (`c..`) with its `title` (or `capability` and `app` for usage), `change`,
     and for `changed` its `before` and `after`. Then, when not both 0,
     `catalogue_changes`: "The catalogue gained <added> and lost <removed>
     settings since the baseline; these are not changes of the machine."
   - One section per area with listed entries, `differs` first: each entry
     (`e..`) with `title`, `effective`, `expected`, `source` and, for a
     policy, `from_policy_on_home`. Then the `not_read` and `default_unknown`
     entries with their `reason`, then the `info` entries (read, with no
     expected value). Each finding gets a recommendation with `weight`,
     `kind`, `risk`, `evidence`, `permissions` and `rollback`
     (`skills/ush-common/references/summary-contract.md`). A `change` with a
     block puts the `--block` output into a ```` ```powershell ```` code
     block and says which part goes to which shell and that the skill is run
     again in a normal shell to read the value back; one without a block
     gives its `manual` step.
   - As expected: one line per area, with the number of `matches` from
     `counts.by_area` ("Security: 12 settings as expected"), no list. This
     section always exists (with "none" when no entry matches).
   - Camera, microphone and location: every usage item (`u..`) with
     `capability`, `app` (see "Account names"), `value`, `last_used_start`,
     `last_used_stop` and `in_use`. An item with `error` could not be read.
     An empty `usage` with the source `capability_usage` `unreadable` means
     it could not be read: say so, never "no app used them". When
     `truncated` > 0:
     how many were cut, their ids ("3 more usage items were cut from the
     summary: u5, u6, u7." with the real ids), and that the detail file has
     them.

6. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail e4 e9 -->
   ```

   An entry whose location the report quotes outside a code block is named
   here. A named id that is not in the detail file fails the check.

7. Not checked, always last. Its marker stands directly before (or right
   after) the section heading:

   ```
   <!-- ush:not-checked -->
   ## Not checked
   ```

   It lists every `not_checked` item with its `what` and `reason`, and names
   every `unreadable` source. If `not_checked` is `[]`, it says "nothing".

## Account names

A report never carries the account name, except in the data directory path
where the section above allows it. The `app` of a non-packaged usage item
(and of its change) is the program's full path, often under the profile
folder, `C:\Users\` followed by the account name. Write that folder as
`%USERPROFILE%` (`%USERPROFILE%\AppData\Local\...`), in the text and in code
blocks alike. Never write the `key` of a change: it carries the same path.
The same holds for any path from a detail item (`locations`, `adapters`).

## Values that are not readings

- `null` is "unknown" (or "not read"), in words, never "no", "off" or "0".
- `source` `default`: no key is set; `effective` is the catalogue's Windows
  default. Write "Windows default", never "disabled" or "not configured".
- `source` `system`: read from the system itself (a service, the firewall,
  Defender, `powercfg`), not from a catalogued key.
- `state` `not_applicable`: the entry's `applies_if` condition is not met
  (Fast Startup without hibernation); it is counted, not a finding.
- A usage `value` `Deny` with a recent `last_used_stop`: the app used the
  device before access was denied.

## Degradation cases

Never report missing data as "no changes" or "fine":

- First run (`baseline.status` `none`): "no comparison: this is the first
  run; the next run compares with this one". The first elevated run is also
  a first run: it compares only with the elevated baseline; say so.
- A baseline that could not be read (`baseline.status` `unreadable`, the
  item `baseline` in "Not checked"): nothing was compared; give the
  `reason`.
- `baseline.saved` `false` (item `baseline save`): the next run compares
  with the older baseline.
- `comparison` `not_read` or `no_baseline` for `settings` or
  `capability_usage`: no comparison for that source this time.
- No administrator rights (`elevated` `false`): `vss_max_space` is
  `not_read` ("needs administrator rights"); offer the elevated block of
  `SKILL.md`.
- An elevated run: entries with `hkcu_elevated` `true` and the usage come
  from the account that elevated the shell (item `HKCU in an elevated run`),
  which may not be the user's; say so, and give no block for them.
- `edition_id` `null` (item `EditionID`): `from_policy_on_home` is `null`
  for policy-sourced entries; whether the policy works is unknown.
- Defender off while another antivirus runs (`defender_mode`, an `info`
  entry of the summary, is not `Normal`, e.g. `Passive`, and
  `antivirus_active` is not listed, so it matches: an antivirus is active):
  `defender_realtime` and `defender_tamper` are `not_applicable`; this is
  normal with a third-party antivirus, not a finding. The summary does not
  name that antivirus; do not guess it. When
  `defender_mode` could not be read they are `not_read` ("depends on
  defender_mode").
- `catalogue_changes` not 0: the catalogue changed between runs; added
  entries have no `before`, removed ones are gone. They are not changes of
  the machine.
- A reader that failed (an item named after its job in "Not checked"): its
  entries are `not_read` with the reason; their previous values stay in the
  baseline, so the next successful read gives no false change.

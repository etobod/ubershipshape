# Report format (ush-inventory)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/inventory-<YYYY-MM-DD-HHMM>.md` (local time of
the run) and checked with
`python -B skills/ush-common/scripts/check_report.py <report>` (or
`--latest --skill ush-inventory` for the newest `inventory-*.md`), which
reads the ush-inventory rules from `data/report-profile.json`.
Follow `skills/ush-common/references/report-style.md`: it says how every
report is written (time, numbers, dash, recommendation layout, language);
this file says what the ush-inventory report contains.
`<data dir>` is the data directory (`--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`); its absolute value is the directory above
`work/` in the summary's `summary_file`. The report text outside code blocks
writes it as `&lt;data dir>` in plain text, never in inline code (a `<`
before a letter fails the check, and inline code shows `&lt;` as it is), and
never the expanded path: it contains the account name, which a report must
not carry. The expanded path appears only in the `ush:summary` marker, as
the `--data-dir` value of every block that runs a skill script (rule 9 of
`report-style.md`; an elevated shell of another account has a different
`%LOCALAPPDATA%`) and in the backup path of a certificate or hosts block
(`SKILL.md`, "Change blocks"), which must land in the same data directory; a
code block that runs no skill script writes it from the environment
(`"$env:LOCALAPPDATA\ubershipshape"`).

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

- Every run of digits is a separate number: `2026-05-07` is 2026, 5 and 7,
  `146.3` is 146 and 3. Write a number with the same digits and precision
  as the JSON, with the decimal separator of the report language (rule 2 of `report-style.md`) (in Polish `146,3`), counts without a thousands
  separator.
- Names back their own digits: a program's `name`, `version` and
  `publisher`, an entry's `name`, `location` and `command`, and the other
  text values of the summary. `Invented Tool 2024` may be written with its
  name. Item keys and file paths are no readings and back no number:
  `summary_file`, `detail_file`, `key`, `program`, `install_location`,
  `targets`, the fact `path` and `expanded_path`, a firewall rule's `app`
  and a Defender exclusion's `value`, also of type `ip` or `extension` (the
  profile's `path_keys`). Name an item by its id and `name`, not by its
  `key`; a value of these keys may appear only in a fenced code block.
- The summary leaves out some fields of a listed item: a program's
  `install_location`, a service's `display_name`, a fact's `company`, and a
  fact's `expanded_path` when it equals `path`. When the report needs one,
  fetch the item with `--detail <id>` and name it in an `ush:detail` line.
- Item ids (`a1`, `s2`, `f3`, `d4`, `x5`, `c6`) are not numbers when they
  name an item of the summary, an item named in `ush:detail` or an item cut
  from the summary (`truncated`, `truncated_drivers`,
  `truncated_components`, `truncated_additions`). A word of that shape that
  is no such id is checked as a number.
- Write every number in digits: a number word (`dwa`, `trzy`, `two`, in any
  case or form) outside code fails the check unless the same word is in a
  text value of the summary (a name). `ten`, `jeden`, `one` and `oba` are
  not number words.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Programs`)
  is fine when the numbering of its level counts from 1 in order. The first
  cell of a table row is ignored when it equals the row's position among the
  table's data rows, so never put a count there.
- Fenced code blocks (the paste-ready commands) are not checked: never put a
  finding's number in one.
- No HTML and no links outside code blocks: write a literal `<` as `&lt;`
  and a literal `]` before `(` or `:` as `&rsqb;`. A registry path or a
  command belongs in inline code or a code block.
- Do not add up, subtract or convert numbers yourself: no total of the
  `own_counts.autostart` kinds or of the `own_counts.firewall_rules`
  stores, no total of the `component_counts` states, no "N new programs"
  or "N firewall rules" counted by hand, no age in days from a date. The
  baseline age is `baseline.age_days`.

## Items the report must name

Every `id` of the summary lists `programs`, `autostart`, `components`,
`drivers`, `additions` and `changes` appears in a visible line of the
report, as a word of its own (`s12` does not name `s1`). Several ids on one
line are fine (`a4, a5, a6: ...`). A mention inside a fenced code block or
on a marker line does not count. The check lists each missing id as
`not named in the report: <id> (<list>)` and fails. Items cut from the
summary (the `truncated*` counts) and items fetched with `--detail` are not
required. A list that is `null` (its sources were not read) requires
nothing, but the keys `components`, `component_counts`, `drivers`,
`additions` and `hosts_file` must be in the summary: a summary without them
is of an older shape and fails with
`required key missing from the summary: <key>`.

## Layout

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

2. Title and one line: when the summary was made (`generated_at`, rule 1 of
   `report-style.md`) and
   whether the run was elevated (`elevated`). Without elevation say that the
   task list may be incomplete (the item `scheduled_tasks visibility` in
   "Not checked").

3. Dashboard: a table with one row per area, in the order of the sections
   below.

   | # | Area | State | Action |
   |---|---|---|---|
   | 1 | Comparison | c1 added, c2 changed | 🔍 see below |
   | 2 | Programs | a1 to a9 listed | ✅ nothing to do |
   | 3 | Autostart | s4 points to a missing file | 🔧 see below |
   | 4 | Components | f1 to f6 enabled features | ✅ nothing to do |
   | 5 | Drivers | d1 to d4 outside Windows | ✅ nothing to do |
   | 6 | Added to the system | x2 hosts entry | 🔍 see below |

   `#` is the section number of the area, `State` a few words with the ids
   and the numbers from the JSON, `Action` a legend symbol and a few words
   (no numbers of your own). An area whose sources were not read says so in
   `State`.

4. Legend, under the dashboard:

   - 🔧 change — an entry the user may want to turn off or fix; the section
     gives the block.
   - 🔍 observe or check — not clear yet, not read, or worth a look (a new
     entry, a changed signature).
   - ✅ fine — read and nothing to act on.
   - ❌ problem found — something the user cannot fix with a block from this
     skill; the section says who can help.

5. One section per area (`## 1. <area>`, in order from 1):

   - Comparison: first the baseline: `Compared with the baseline of
     <created_at as in rule 1 of report-style.md>, <baseline.age_days> days old.`, or on a first run
     "no comparison: this is the first run" (see "Degradation cases"). With
     `baseline.reference` other than `latest`, say it is the saved state from
     `reference_file`, not the latest run. Then
     `comparison` per source when any is not `compared`, and every change
     (`c..`) with its `change`, `name`, `source` and, for `changed`, each
     field of `fields` with `before` and `after`. A Defender exclusion change
     has `value` (a path) in place of `name`: name it by its id and `source`.
     An `administrators` change has no `name` (an account name, see
     "Account names"): name it by its id, `source` and `change`. Its changed
     `name` field is `{"changed": true}` without `before` and `after`: say
     only that the name changed. A changed `enabled` has `before` and
     `after` as any other field. A changed `app` of a
     firewall rule goes, `before` and `after`, in a fenced code block under
     the change's line, a profile folder written as `%USERPROFILE%`. A fact
     change (field `facts[<path>].<field>`) is named in the text by its id,
     `source` and the field name after the last `].` (e.g. `signer`), never
     by the full `facts[...]` key; the file name of the path goes in a
     fenced code block under the change's line (as a firewall rule's `app`),
     because its digits (e.g. `rundll32.exe`) back no number. Its `before`
     and `after` are written as for any other field. Then
     `own_changes` as written, one line: "Changes of Windows' own items: <added> added,
     <removed> removed, <changed> changed" (only in the detail file).
   - Programs: every program (`a..`) with `name`, `version`, `publisher`
     and `install_date`, newest first as in the summary; `scope` and
     `system_component` when they matter. For MSIX say that `install_date`
     is the install or the last update. Programs linked by `per_user_pair`
     (directly, or through a common partner: a `(User)` entry can pair with
     both a 64-bit and a 32-bit copy, which do not name each other; only
     programs with the same name and the same publisher are linked) are one
     program installed more than once: describe it once, at the first of
     the linked programs in the summary's `programs` list (ids are stable,
     not places in the list), with a note on its other installs (for the
     user, or for the computer), naming each one's `id` and `name`; each
     other linked program's line refers back to that id instead of
     repeating the description. Then, one line with its number:
     "Windows programs (not listed): <own_counts.programs>". When
     `truncated` > 0: how many were cut and that the detail file has them
     ("3 more programs were cut from the summary; the detail file has
     them."). Name a cut program only after fetching it with `--detail`
     (its id comes from `--cut`).
   - Autostart: every entry (`s..`) with `kind`, `name`, `location`,
     `command` (inline code), `enabled` and `approved`, and what `facts`
     say (exists, signature, signer, program). A `location` or `command`
     under the user's profile folder (`C:\Users\` and the account name)
     is written with `%USERPROFILE%` in place of that folder, in the text
     and in code blocks alike (see "Account names"). Then the Windows-own counts,
     each kind on its own line with its number, as written:
     "Windows services (not listed): <own_counts.autostart.service>",
     "Windows tasks (not listed): <own_counts.autostart.task>", and, when
     not 0, "Entries with unknown facts (not listed): <own_counts.unknown>".
     Never add the kinds up.
   - Components: every listed component (`f..`, the features with `state`
     `enabled` and the capabilities with `state` `Installed`) with `kind`
     and `name`. Then the counts of `component_counts`, one line per kind
     with each state and its number from the JSON, never added up:
     "Features: enabled <feature.enabled>, disabled <feature.disabled>,
     absent <feature.absent>, unread <feature.unread>" (and any other state
     key), "Capabilities: <state> <number>, ..., unread
     <capability.unread>". A kind whose count is `null` was not read: say
     so ("Capabilities: not read, requires administrator"), never 0. When
     `truncated_components` > 0: how many were cut, and that the detail file has them (`--cut` lists the cut items, see SKILL.md).
   - Drivers: every listed driver (`d..`, drivers whose `.inf` is not one
     of Windows') with `device_name`, `class`, `provider`, `version`,
     `date` and `signer`. Then, each on its own line with its number:
     "Windows drivers (not listed): <own_counts.drivers>" and "Driver rows
     without an INF file (not listed):
     <component_counts.drivers_without_inf>". Describe that number with
     this sentence, translated: "`Win32_PnPSignedDriver` rows without an
     INF file (for example software devices, or a device without a driver), not device state; device
     state is measured by `ush-health`." Say nothing more about what the
     rows mean; when the user compares it with `ush-health`, the rows are in `drivers_without_inf_items` of the detail file
     (`device_name` and `class`). Example of a Polish report:

     ```markdown
     Wiersze sterowników bez pliku INF (niewymienione): 2 — np. urządzenia programowe albo urządzenie bez sterownika, nie stan urządzeń; stan urządzeń mierzy `ush-health`.
     ```

     When `truncated_drivers` > 0: how many were cut, and that the detail file has them (`--cut` lists the cut items, see SKILL.md). A
     `removed` driver change is a device not present now, not an
     uninstalled driver.
   - Added to the system: first one sentence, translated: "This section
     lists what is outside the Windows lists of the skill's data file, not
     what is suspicious." Then every addition (`x..`) by `kind`:
     `administrator` (`object_class`, `principal_source`, `enabled`,
     `is_current`, `builtin`; never its `name`, see "Account names"),
     `defender_exclusion` (`type`, `value`, `origin`), `root_certificate`
     (`store`, `subject`, `not_after`, `self_signed`, `in_authroot`,
     `windows_first_run` when present),
     `firewall_rule` (`store`, `name`, `action`, `dir`, `active`,
     `protocol_name` or `protocol`, `lport`, `app`, `app_exists` when
     present), `hosts_entry`
     (`hostname`, `address`, `line`, `duplicates`). A rule's `app` and an
     exclusion's `value` go in a fenced code block under the item's line,
     never in the line itself (see the path keys above). A rule's
     `app_exists` `true` is "the program file is there"; `false` is "no
     file at this path in this profile" (the path was checked from the
     account that ran the skill, so a path into another account's profile
     can give it): a fact, not "the rule is unneeded"; `null` is "not
     checked". A rule without `app_exists` has no program file to check
     (no `app`, or `System`). An item without a change block gives its
     `no_block_reason` in words, translated, never the code alone:
     `store_app_iso` "a rule of a Store app (the app manages it)",
     `store_policy` "a rule set by policy", `cert_other_store` "a
     certificate in a store other than the root stores of the computer and
     the user", `cert_in_authroot` "the certificate is also in the Windows
     list of trusted roots", `cert_in_several_stores` "the certificate is
     in more than one root store", `defender_origin` "the exclusion was not
     added locally (policy or unknown)", `defender_method` "the exclusions
     were read from the registry, not from Defender". Example of a Polish
     report:

     ```markdown
     - x12 Invented Store App Rule — brak bloku: reguła aplikacji ze Sklepu, zarządza nią aplikacja. Pliku programu nie ma pod tą ścieżką w tym profilu.
     ```
     Then `hosts_file`:
     whether the file exists and whether its folder is the default one
     (`path_is_default` `false` is a finding: the name resolution reads
     another file). Then the Windows-own counts, each on its own line with
     its number, never added up: "Windows firewall rules (not listed):
     local <own_counts.firewall_rules.local>, Store apps
     <own_counts.firewall_rules.app_iso>, policy
     <own_counts.firewall_rules.policy>" and "Windows root certificates
     (not listed): <own_counts.root_certificates>"; a `null` count is "not
     read". A certificate with `windows_first_run` `true` is Windows' own
     because it was there at the first run; a listed certificate with
     `windows_first_run` `false` has the subject and serial number of that
     Windows certificate but is not trusted: a changed thumbprint, one added
     after the first run, or one of several such certificates on a first run.
     `windows_first_run` `null` means the decision file
     `ush-inventory.first-run.json` could not be read; say it was not checked.
     A `first-run certificates` item in "Not checked" names that file and the
     reason; deleting the file starts a new first run. When `truncated_additions` > 0: how many were cut, and that the detail file has them (`--cut` lists the cut items, see SKILL.md)
     (the items without a change block are cut first, from the end of their
     group: firewall rules outside `local`, certificates outside
     `machine_root` and `user_root`, with `in_authroot` `true` or also in another
     root store, Defender exclusions not added locally or not read by
     `preference`; then the items with a block, Administrators members among
     them).

   In "Comparison", after the `own_changes` line, give
   `own_changes.by_source` for each source whose three counts are not all
   0, one line each: "<source>: <added> added, <removed> removed,
   <changed> changed". A firewall rule or certificate change counted there
   is not listed; its items are in the detail file.

   Each section gives what was read, with the numbers and ids from the JSON,
   the judgement, and for each finding a recommendation with `weight`,
   `kind`, `risk`, `evidence`, `permissions` and `rollback` in the layout of
   rule 4 of `skills/ush-common/references/report-style.md` (the fields are
   in `skills/ush-common/references/summary-contract.md`, "Recommendations").
   A `change` gives a paste-ready block (see `SKILL.md`) and says that the
   skill is run again to read the value back. An area with nothing to act on
   gets one or two lines, not a recommendation.

6. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail s4 a12 -->
   ```

   A rollback block that uses `approved_raw` needs its entry fetched and
   named here. A named id that is not in the detail file fails the check.

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
where the section above allows it (the `ush:summary` marker, which the
checker needs, the `--data-dir` of every block that runs a skill script and the backup
path of a certificate or hosts block). A member of Administrators is named
by its id, `object_class`, `principal_source`, `enabled`, `is_current`
and `builtin`, never by its `name`, which holds an account name. Name a
member by its role (rule 13 of the report style): `builtin` `true` is "the
built-in Administrator account", `is_current` `true` is "your account"
(the account that ran the skill). Example of a Polish report:

```markdown
x1 — wbudowane konto Administrator, wyłączone. x2 — Twoje konto, włączone.
```

The user sees the names with
`Get-LocalGroupMember -SID S-1-5-32-544` in their own shell. A Defender
exclusion `value` under the profile folder is written with
`%USERPROFILE%` in its code block, like an autostart path. `location`, `command`,
`targets` and fact paths of `HKCU` and `startup:user` entries often start
with the profile folder, `C:\Users\` followed by the account name. Write
that folder as `%USERPROFILE%` (`%USERPROFILE%\AppData\Roaming\...`). In a
paste-ready block build the path from the environment instead, so the
pasted command writes the same value back:
`(Join-Path $env:USERPROFILE 'AppData\Roaming\Invented\tray.exe')`, or a
double-quoted string that starts with `$env:USERPROFILE` when the rest has
no `$` or backtick.

## Values that are not readings

- `null` is "unknown" (or "not read"), in words, never "no", "off" or "0".
  `install_date` `null` is "no install date recorded", not "old".
- `approved` `not_set` is "no Task Manager setting" (the entry runs);
  `unknown` is given raw with `approved_byte`, or as "not binary" when
  `approved_byte` is `null`, with no conclusion about whether it runs.
- A missing file (`exists` `false`), a missing signature (`NotSigned`) or
  `program` `null` is a fact, not a verdict: say what it is, then judge.
  `program` `null` means only that no installed program's folder contains
  the file.
- `own` `false` does not mean unneeded, and `own` `true` does not mean
  needed: it only says whether the item is part of Windows by the rules of
  `windows-own.json`.
- A field in `unread_fields` is unknown in this run; never judge from it.
- `from_baseline` `true`: the item is the previous run's, not read now; say
  so and make no change block for it. `facts_from_baseline` `true`: the file
  facts are the previous run's.
- A service named in a `not_checked` item `services <name>`: only the
  fields named in its `unread_fields`, and `template_start` when it is
  `null`, were not read; treat them as unknown and make no change block for
  it.
- A component with `state` `null` (`unread_fields` `["state"]`): its state
  was not read; a feature gives the raw `install_state` (4 is "unknown" to
  Windows). It counts as `unread` in `component_counts`.
- A driver's `third_party` `null` (in `unread_fields`): the data file could
  not be read, so it is not known whether the driver is Windows'.
- `hosts_file.exists` `false`: read, there is no hosts file (a finding,
  not an error). `path_is_default` `null`: not known.
- An addition's `own` is never in the summary: a listed addition is outside
  the Windows lists, which is all it says.

## Degradation cases

Never report missing data as "no changes" or "clean":

- First run (`baseline.status` `none`): "no comparison: this is the first
  run; the next run compares with this one". Never "no changes". The same
  holds for the first elevated run: an elevated run compares only with the
  elevated baseline, so it may say `none` although normal runs have one;
  say so.
- A baseline that could not be read (`baseline.status` `unreadable`, the
  item `baseline` in "Not checked"): nothing was compared; give the
  `reason`; the old file was kept and this run started a new baseline.
- `baseline.saved` `false`: this run's baseline was not saved (item
  `baseline save`); the next run compares with the older one.
- `baseline.reference` other than `latest` (the run had `--compare-to`):
  say that the comparison is with the saved state from `reference_file`,
  `age_days` days old, not with the latest run. `status` `none` then means
  "there is no saved state from at least N days ago" (give the `reason`), not
  a first run and never "no changes". `status` `unreadable` with the item
  `reference baseline` in "Not checked": that copy could not be read, so
  nothing was compared; give the `reason`. A latest baseline that could not be
  read (item `baseline`, "the latest baseline could not be read") does not
  stop that comparison: say that sources not read in this run keep nothing.
- Item `baseline history` ("history not kept"): this run's baseline has no
  day copy, so a later `--compare-to` may not find it. With the reason "the
  day copy was kept, but old copies were not removed": the copy is there;
  only older copies stay longer than 31 days. Not a missing history.
- A source with `comparison` `not_read` (`status` `unreadable`): no
  comparison for that source, and its items are missing from this report;
  give the `reason`. `no_baseline`: the source was not read in the
  baseline; no comparison for it this time. Never "no changes" for either.
- A source with `status` `empty`: read, and nothing there - a finding (no
  Run values, no Startup files).
- `startup_approved` or `file_facts` unreadable: the entries are listed, but
  `approved`, `enabled` or `facts` are the previous run's
  (`facts_from_baseline`) or unknown (`unread_fields`); say which. With
  `startup_approved` unreadable, no `run`, `run_once` or `startup_folder`
  entry gets a change block: its `approved` may be the previous run's
  without any flag on the entry.
- `own_counts.unknown` > 0 (item `autostart facts`): that many services or
  tasks were not listed because their files could not be checked or, for a
  service, its registry values could not be read (the item's reason says
  which); they are in the detail file.
- `windows-own.json` in "Not checked": nothing was classed as Windows' own
  except certificates trusted by the decisions kept in
  `ush-inventory.first-run.json`, so the lists are long; say so.
- `scheduled_tasks visibility` (a normal run): tasks of other accounts or
  of the system may be missing without an error; offer an elevated run.
- No administrator rights (`elevated` `false`): `capabilities` and
  `defender_exclusions` are `unreadable` with the reason "requires
  administrator rights ...". Say "not read in this run (requires
  administrator)", never "no capabilities" or "no exclusions", keep
  `component_counts.capability` `null` as "not read", and offer the
  elevated run.
- `firewall_rules` or `root_certificates` unreadable: `additions` has no
  item of that kind and `own_counts.firewall_rules` or
  `own_counts.root_certificates` is `null`. Say that the rules or the
  certificates were not read and give the `reason`; never "no rules added".
  The same for `hosts` (and `hosts_file` with its fields in
  `unread_fields`), `administrators` and `defender_exclusions`. When none
  of the five sources was read, `additions` is `null`: the whole section is
  "not read".
- `optional_features` and `capabilities` both unreadable: `components` is
  `null`; `drivers` unreadable: `drivers` and `own_counts.drivers` and
  `component_counts.drivers_without_inf` are `null`. Say "not read".
- A `not_checked` item `<source> without <field>` (e.g. `drivers without
  DeviceID`): that many rows had no key and are in no list; give the
  number from its `reason`.
- `defender_exclusions origin` in "Not checked": the policy lists could not
  be read, so every exclusion has `origin` `null` and gets no block.
- Truncated lists: `truncated`, `truncated_drivers`,
  `truncated_components` or `truncated_additions` > 0 means the summary
  holds only part of that list; the cut items are in the detail file.
  Ids are stable between runs, not positions, so the id of a cut item does
  not follow from the list: say how many were cut from each list and that
  the detail file has them. `--cut` lists the cut items (`id`, `list`,
  `name`); name one in the report only after fetching it with `--detail`,
  and then in the `ush:detail` line. Each cut list keeps a short list before any list is emptied: the
  20 newest programs and the first 10 drivers (a `Display` driver leads
  them), components and additions (see "Files and output" of
  `summary-contract.md`); report the short list as it is, never as the whole
  list. `autostart` and `changes` are never cut; a `summary budget` item in
  "Not checked" means the summary is over the budget and nothing was cut.
- `per_user_suffixes.json` in "Not checked": install pairs were not checked,
  so no program has `per_user_pair`; describe every program on its own and
  never say that no program is installed more than once.
- `windows-own.json` in "Not checked": besides the longer lists, every
  driver is listed with `third_party` in `unread_fields`, every firewall
  rule and every certificate (also of `authroot`) is listed except those
  trusted by `ush-inventory.first-run.json`, and
  `hosts_file.path_is_default` is unread.

# Report format (ush-inventory)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/inventory-<YYYY-MM-DD-HHMM>.md` (local time of
the run) and checked with
`python -B "<plugin root>/skills/ush-common/scripts/check_report.py" <report>` (or
`--default-data-dir "<plugin data>" --latest --skill ush-inventory` for the newest `inventory-*.md`), which
reads the ush-inventory rules from `data/report-profile.json`.
Follow `<plugin root>/skills/ush-common/references/report-style.md`: it says how every
report is written (time, numbers, dash, recommendation layout, language);
this file says what the ush-inventory report contains.
`<data dir>` is the data directory (`--data-dir`, else `USH_DATA_DIR`, else
the plugin data folder (`--default-data-dir`)); its absolute value is the directory above
`work/` in the summary's `summary_file`. The report text outside code blocks
writes it as `&lt;data dir>` in plain text, never in inline code (a `<`
before a letter fails the check, and inline code shows `&lt;` as it is), and
never the expanded path: it contains the account name, which a report must
not carry. The expanded path appears only in the `ush:summary` marker, as
the `--data-dir` value of every block that runs a skill script (rule 9 of
`report-style.md`; an elevated shell of another account has a different
`%LOCALAPPDATA%`) and in the backup path of a certificate or hosts block
(`SKILL.md`, "Change blocks"), which must land in the same data directory; a
block that runs no skill script is copied as the script prints it (an `HKCU`
key block builds a data directory under the profile from `$env:LOCALAPPDATA`
or `$env:USERPROFILE`, so it prints no profile path).

The markers below are HTML comments: they do not depend on the report
language and do not show in a preview. Each marker stands on its own line,
outside quotes and lists; no other HTML comment is allowed. This file stays
in English; the report translates every heading and label, the dashboard
header included.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. The checker is
shared by all skills (see `<plugin root>/skills/ush-health/references/report-format.md`,
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
  `install_location`, an autostart entry's `targets` (each target is a
  fact's `path`), a service's `display_name`, a fact's `company`, and a
  fact's `expanded_path` when it equals `path`. When the report needs one,
  fetch the item with `--detail <id>` and name it in an `ush:detail` line.
- Item ids (`a1`, `s2`, `f3`, `d4`, `o5`, `x6`, `v7`, `c8`) are not numbers when they
  name an item of the summary, an item named in `ush:detail` or an item cut
  from the summary (`truncated`, `truncated_vendor_folders`,
  `truncated_driver_packages`, `truncated_drivers`,
  `truncated_components`, `truncated_additions`, `truncated_autostart`,
  `truncated_changes`). A word of that shape that
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
`drivers`, `driver_packages`, `additions`, `leftovers`, `vendor_folders` and `changes` appears in a visible line of the
report, as a word of its own (`s12` does not name `s1`). Several ids on one
line are fine (`a4, a5, a6: ...`). A mention inside a fenced code block or
on a marker line does not count. The check lists each missing id as
`not named in the report: <id> (<list>)` and fails. Items cut from the
summary (the `truncated*` counts) and items fetched with `--detail` are not
required. A list that is `null` (its sources were not read) requires
nothing, but the keys `components`, `component_counts`, `drivers`,
`driver_packages`, `additions`, `hosts_file` and `vendor_folders` must be in the summary: a summary without them
is of an older shape and fails with
`required key missing from the summary: <key>`.

## Layout

The summary section of rule 15 "Summary first" in `report-style.md` comes
first, directly after the header (the `ush:summary` line, the title and its
line) and before the dashboard, which follows it with its legend under a `##`
heading of its own (item 3; the section runs to the next `##` heading, so
nothing without a heading may stand below it). The `<!-- ush:attention -->` line stands
directly above its `##` heading. Part 1
names each high or medium recommendation of this report by its main source
(the first id of its `Dowód`). Part 2 says „nie dotyczy: decyzje sprawdza
ush-runall”: this skill checks no decisions. Part 3 names the open plans of
`<data dir>/plans/` (not `done/`) in a fenced code block. The last line gives
the count of low recommendations whose main source no line names.

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

2. Title and one line: when the summary was made (`generated_at`, rule 1 of
   `report-style.md`) and
   whether the run was elevated (`elevated`). Without elevation say that the
   task list may be incomplete (the item `scheduled_tasks visibility` in
   "Not checked").

3. Dashboard, directly after the summary section, under its own `## Overview`
   heading (in a Polish report `## Przegląd`), with the legend (item 4) below
   it: a table with one row per area, in the order of the sections
   below.

   | # | Area | State | Action |
   |---|---|---|---|
   | 1 | Comparison | c1 added, c2 changed | 🔍 see below |
   | 2 | Programs | a1 to a9 listed | ✅ nothing to do |
   | 3 | Autostart | s4 points to a missing file | 🔧 see below |
   | 4 | Components | f1 to f6 enabled features | ✅ nothing to do |
   | 5 | Drivers | d1 to d4 outside Windows | ✅ nothing to do |
   | 6 | Driver packages | o1 no device found, o2 device not present | 🔍 see below |
   | 7 | Added to the system | x2 hosts entry | 🔍 see below |
   | 8 | Leftovers of removed programs | l1 folder and task | 🔧 see below |
   | 9 | Vendor folders: no installed program, or not judged | v1, v2 | 🔍 see below |

   `#` is the section number of the area, `State` a few words with the ids
   and the numbers from the JSON, `Action` a legend symbol and a few words
   (no numbers of your own). An area whose sources were not read says so in
   `State`.

4. Legend, under the dashboard:

   - 🔧 change — an entry the user may want to turn off or fix; the section
     proposes it in words; after the user decides, the block goes into a
     repair plan per `repair-plan.md`, not into the chat.
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
     only that the name changed. A collapsed entry (`collapsed`
     `ms-resource`, no id) stands for `count` firewall rule changes of one
     `change` type whose names are an unresolved resource string; give it
     one line, as written: "<N> zmian `ms-resource:` zwiniętych w jedną linię"
     with `count` as `<N>` and its `change` (in a report in another language,
     translated); the changes are in the detail file (`--cut` lists them). A changed `enabled` has `before` and
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
     When `truncated_changes` > 0, the list holds only the first changes:
     give `change_counts` per source, one line each ("<source>: <added>
     added, <removed> removed, <changed> changed"), and end the list with
     one line holding `truncated_changes` (the cut changes, collapsed ones
     included) and the words "pozostałe w pliku szczegółów" (translated in a report in another language).
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
     say (exists, signature, signer, program), and its age from
     `first_seen` and `passes_seen`, written in the report language as
     "first seen <first_seen>, in <passes_seen> passes" ("in 1 pass" for 1;
     Polish: "pierwszy raz widziany <first_seen>, w <passes_seen>
     przebiegach", "w 1 przebiegu" for 1). Both are
     per privilege level, and `first_seen` is a UTC date. When
     `first_seen_lower_bound` is `true`, the date is the earliest the tool
     can show (a baseline saved before these fields), not the day the entry
     appeared: say "seen since at least <first_seen>, in at least
     <passes_seen> passes" (Polish: "widziany co najmniej od <first_seen>,
     w co najmniej <passes_seen> przebiegach"): `passes_seen` is a lower
     bound too.
     When both are `null` (the previous baseline could not be read, see
     `not_checked`, or an entry not read in this run whose baseline copy has
     no age), write "age unknown", never a date. The script sets no
     threshold: the model judges. `passes_seen` counts runs of the tool,
     not logons, so several passes alone never show that a RunOnce value
     (`kind` `run_once`) did not finish: two runs can fall in one logon
     session. Give the date and the count as facts, and call the value
     one that never finished or one waiting for the next logon (the run
     cannot tell which, see Leftovers). A `location` or `command`
     under the user's profile folder (`C:\Users\` and the account name)
     is written with `%USERPROFILE%` in place of that folder, in the text
     and in code blocks alike (see "Account names"). Then the Windows-own counts,
     each kind on its own line with its number, as written:
     "Windows services (not listed): <own_counts.autostart.service>",
     "Windows tasks (not listed): <own_counts.autostart.task>", and, when
     not 0, "Entries with unknown facts (not listed): <own_counts.unknown>".
     Never add the kinds up. When `truncated_autostart` > 0, the list holds
     only the first entries: give `autostart_counts`, one line per kind with
     its number, and end the list with one line holding
     `truncated_autostart` and the words "pozostałe w pliku szczegółów".
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
   - Driver packages: the heading of a Polish report is "Pakiety sterowników
     według grup". The facts first, then your judgement. First the groups:
     one line per entry of `driver_package_groups` with its `group`, `count`
     and the four counts of `by_state` (`present`, `non_present`,
     `no_device_found`, `unread`). With `driver_package_groups` `null` say
     "groups not read" (the groups file could not be used, "Not checked" names
     `data/driver-package-groups.json` with the reason, every package's
     `group` is `null`; the states are still facts) or, when the store was
     not read, "not read". Then every listed
     package (`o..`, a third-party package of the driver store with
     `device_state` `non_present` or `no_device_found`), under its `group`, on
     its own line with
     its id, `original_name`, `published_name`, `owner`, `class`,
     `version`, `date`, `signer` and its state in words. A package with
     `no_device_by_nature` `true` (a filter or antivirus package that never
     has a device of its own) is shown as owned by its program (`owner`, the
     provider), never as a leftover, an orphan or "without a device", even
     with state `no_device_found`. States in words: `non_present`
     "known device not present", with each of its `devices` (name, class,
     status and `last_removal`, or "no removal date" when it is `null`);
     `no_device_found` "no device found without administrator rights",
     never "no device" or "orphan": Windows may hold a record a normal read
     does not show. The report names every `o..` id the summary holds. When
     `truncated_driver_packages` > 0 the list is cut to the budget: say how
     many packages were cut (the number from the JSON) and that the detail
     file has them (`--cut` lists the cut items, see SKILL.md); name a cut
     package only after fetching it with `--detail`, in an `ush:detail` line.
     A `null` list stays `null` (not read, see "Degradation cases"). Then, on
     one line with its numbers: "Third-party driver packages:
     <component_counts.driver_packages>" with the four counts of
     `component_counts.driver_packages_by_state` (`present`, `non_present`,
     `no_device_found`, `unread`). Then your judgement, marked as such, per
     package or per group: what the package is likely for (a device that is
     gone, an older version kept next to a newer one in use, a program's
     helper) and whether it looks worth a look. A state is a fact about this
     moment (a device unplugged now is not present), not proof that the
     package is unused or safe to remove; say so once. No package gets a
     removal: `--block o<n>` prints only `no block` with its reason, so
     propose no removal of a package; a Polish report says exactly once
     "Raport nie proponuje usuwania pakietów sterowników." An empty list (`[]`) with
     `truncated_driver_packages` `0` says that every third-party package is
     `present` (or has `device_state` `null`: such a package is not judged,
     and "Not checked" names those whose published name was not read, as
     `driver_packages published_name`, those named by a device of an
     unknown status, as `driver_packages device_state`, those named only by a
     disconnected device of another class, as `driver_packages device_class`,
     and the Extension packages, as `driver_packages device_state (Extension
     packages)`), or that the store
     holds none (then `component_counts.driver_packages` is 0); with such a
     "Not checked" entry never call the store clean.
     With `truncated_driver_packages` above `0` the packages were cut to the
     budget, not absent: give the count, never call the list clean or
     empty. Extension packages and the
     other packages with `device_state` `null` are never in the list; do
     not call them unused.
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
   - Leftovers of removed programs: the heading of a Polish report is
     "Pozostałości po usuniętych programach". The section is always there;
     with an empty `leftovers` list it says "brak" (in a report in another
     language, translated). Every leftover (`l..`) is named by its id. A
     leftover with `program` is what a program gone since an earlier run
     left: its `name`, `publisher` and `first_seen_gone` (the day a run first
     saw it gone), and the `name` of each of `other_programs` (other removed
     entries with the same folder, e.g. the 32-bit entry of the same product),
     then each part of `parts`. A leftover with `folder` and no
     `program` groups entries whose target files are all missing and that no
     removed program explains; name the folder in a fenced code block. A part
     of kind `folder` is the program's `install_location` (`path`, in a fenced
     code block): with `status` `read` give `files`, `bytes`, `newest_write`
     (rule 1 of `report-style.md`) and the `extensions` with their counts,
     and judge from them whether the folder may hold data worth keeping
     (documents, saves, settings written lately) or only program files;
     with `status` `unreadable` say it could not be read and give its
     `reason`, never "empty". A part of kind `registry_key` is a key
     `SOFTWARE\<publisher>\<name>` the program left under HKLM (also its
     32-bit view `WOW6432Node`) or HKCU (`path`, in a fenced code block):
     with `status` `read` give `values` and `subkeys` (the counts of its
     values and direct subkeys); with `status` `unreadable` say it could not
     be read and give its `reason`, never "brak klucza". A leftover may be
     only registry keys (a program with no usable folder). Any other part is
     an autostart entry or a firewall rule, named by its own `id` (the same item as in Autostart or
     Added to the system) and `name`; a part with `reason` gives it in the
     language of the report (`target file does not exist` is "plik docelowy
     nie istnieje" in a Polish report). The script only lists facts: per leftover the
     report proposes a plan in words, "usuń tak: ..." or "zostaw, bo ...",
     never a block (after the user decides, `--block l<n>` prints the blocks
     for the plan, see `SKILL.md`). A program removed
     before the first baseline is not known: the `not_checked` item
     `leftovers before the first baseline` says so; name it under "Not
     checked". A
     `leftovers <name>` item in "Not checked" is a removed program kept for a
     later run because this one could not read everything, e.g. a target
     path that could not be expanded (not "nothing left"); but when its
     reason says there is no usable install_location and no registry key of
     its own, nothing of it was looked for and it is not kept: never promise
     a later check. `leftovers before the first baseline` names no program.
     Only explicit facts make a leftover (a path under the old
     `install_location`, a missing target): a folder or entry with a similar
     name is never one, and nothing under the folder of a program installed
     now, nor a missing file under the Windows folder, is listed; a program
     installed in a shared folder (`ProgramData`, `Program Files`,
     `WindowsApps`, a profile, its `Downloads`, `Desktop` or `Documents`, or
     its `AppData` folders such as `Temp` and `Microsoft`) or under the
     Windows folder gives no leftover; a program folder inside one of them can.
   - Vendor folders with no installed program, or not judged: the facts first, then your
     judgement. Every listed folder (`v..`, a top-level folder under
     `Program Files`, `Program Files (x86)`, `ProgramData` or
     `Windows\Installer` that no installed program matches, `matched`
     `false`, or that the run could not judge, `matched` `null`) on its own line
     with its id, `path` (in a fenced code block), `has_entries` and
     `last_write` (rule 1 of `report-style.md`); the report names every `v..`
     id the summary holds, the not judged ones included. When
     `truncated_vendor_folders` > 0 the list is cut to the budget: say how
     many folders were cut (the number from the JSON) and that the detail
     file has them (`--cut` lists the cut items, see SKILL.md); never name a
     cut folder's id unless you fetched it with `--detail`, in an `ush:detail`
     line. A folder with
     `has_entries` `null` could not be listed: give `has_entries_reason`,
     never "empty". The folders with `matched` `false` are the ones no
     installed program matches. The folders with `matched` `null` go into
     their own group, "not judged", each on its own line with its id and
     `path`, after one line with the cause (`not_judged`, the same text for
     all of them): something they could belong to was not read, so the run
     cannot say whether a program matches them; never write "no installed
     program matches" for one, never count it among the unmatched, and offer the run again with administrator rights (`run-me-admin.ps1`, which elevates itself) (and, when the cause is a source or
     a program key, the cause named in "Not checked"). Then, each on its own
     line with its number from `component_counts`: folders read
     (`vendor_folders_read`), matched (`vendor_folders_matched`), with no
     installed program (`vendor_folders_unmatched`), not judged
     (`vendor_folders_unknown`, when above 0), junctions skipped
     (`reparse_points`) and GUID folders of `Windows\Installer` skipped
     (`installer_guid_folders`). Then your judgement, marked as such, per
     folder with `matched` `false` (never for a not judged one): what it likely holds (data or settings of a removed program, a
     shared component, a tool installed without an uninstall entry) and
     whether it looks worth a look. "No installed program matches" is a fact
     about the uninstall entries and autostart targets read, not proof that
     the folder is unused or safe to delete; say so once. This skill has no
     block for a folder. An empty list (`[]`) with `truncated_vendor_folders`
     `0` says that every folder read is matched or a Windows name. With
     `truncated_vendor_folders` above `0` the folders were cut to the budget,
     not absent: give the count, never call the list clean or empty.
   - Package managers are not in this report: pip, npm and the other package
     managers are read and reported by `ush-packages`.

   Leftovers (the SKILL.md rule "Leftovers are named"): an autostart entry
   with an existing target whose `signature_status` is set and not `Valid`,
   and every RunOnce value (`kind` `run_once`), are named in the autostart
   section with the fact that makes them one (`signature_status`, or "a
   RunOnce value": a step that never finished or one waiting for the next
   logon; the JSON holds no write or logon time, only `first_seen` and
   `passes_seen`, judged as in the Autostart section), then your judgement,
   marked as such, and whether it is worth a look (for a RunOnce value the
   judgement keeps both readings and says the run cannot tell which); listed
   driver packages whose `no_device_by_nature` is `false` and unmatched
   vendor folders in their own sections above (a package with `true` is
   named under its owner, never as a leftover; one with `null`, the groups
   file not read, is not judged as a leftover).
   A driver package whose `no_device_by_nature` is `false` and a vendor
   folder with `matched` `false` whose names
   match in the JSON are one entry (a folder with `matched` `null` is never
   merged: it stays in its "not judged" group): the folder's line names the package's id (`o..`) and the
   package's line names the folder's id (`v..`), with the matching name;
   the recommendation, if any, cites both.

   In "Comparison", after the `own_changes` line, give
   `own_changes.by_source` for each source whose three counts are not all
   0, one line each: "<source>: <added> added, <removed> removed,
   <changed> changed". A firewall rule or certificate change counted there
   is not listed; its items are in the detail file.

   Each section gives what was read, with the numbers and ids from the JSON,
   the judgement, and for each finding a recommendation with the problem in
   plain words (`Problem`), what to do now (`Co zrobić`) and `weight`, then
   `Szczegóły` with `kind`, `risk`, `evidence`, `permissions` and
   `rollback`, in the layout of rule 4 of
   `<plugin root>/skills/ush-common/references/report-style.md` (the fields are in
   `<plugin root>/skills/ush-common/references/summary-contract.md`, "Recommendations").
   A `change` is proposed in words and the report holds no block;
   after the user decides the model prints the block with `inventory.py
   --block <ids> --detail-file <detail_file>` (`SKILL.md` step 5), puts it
   into a repair plan per `<plugin root>/skills/ush-common/references/repair-plan.md`
   with its shell and its rollback, not into the chat, never filled by
   hand, and
   says that the skill is run again to read the value back (rule 8 of
   `report-style.md`). An item for which the printer gives `no block`
   gets no block after the decision either; say its reason. An area with nothing to act on
   gets one or two lines, not a recommendation.

6. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail s4 a12 -->
   ```

   A rollback block (put into the repair plan after the decision, not into
   the chat) that uses
   `approved_raw` needs its entry fetched and named here. A named id that is not in the detail file fails the check.

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
command the user runs writes the same value back:
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
- `driver_packages` unreadable (e.g. an older Windows without the XML
  listing): `driver_packages` and both of its counts are `null`; say "not
  read" with the `reason`, never "no packages without a device". `devices`
  unreadable while the store was read: the list `driver_packages` and
  `component_counts.driver_packages_by_state` are `null`, every package has
  `device_state` `null`, and "Not checked" holds `driver_packages
  device_state`; say that the packages were read but the devices were not,
  so no package state is known, and give `component_counts.driver_packages`.
- `data/driver-package-groups.json` broken or missing: every package has
  `group` and `no_device_by_nature` `null`, `driver_package_groups` is
  `null`, and "Not checked" holds `data/driver-package-groups.json` with
  the reason; say the groups were not checked and that no driver package
  was judged as a leftover, give the packages without a group and keep
  their states.
- `vendor_folders` `null` (the data file could not be used, no root could
  be listed, or a program source was not read and the baseline holds none
  of its programs; "Not checked" names which): say "not read" with the
  reason, never "no folders". A `not_checked` item `vendor_folders <root>`:
  that root was not listed, the others were. A `not_checked` item
  `vendor_folders` with folders listed with `matched` `null`
  (`vendor_folders_unknown` above 0): those folders were not judged because
  something they could belong to was not read; name them in the "not
  judged" group of "Vendor folders" with the cause, never as "matched" and
  never as "no installed program matches", and offer the elevated re-run.
- A `not_checked` item `<source> without <field>` (e.g. `drivers without
  DeviceID`): that many rows had no key and are in no list; give the
  number from its `reason`.
- `defender_exclusions origin` in "Not checked": the policy lists could not
  be read, so every exclusion has `origin` `null` and gets no block.
- Truncated lists: `truncated`, `truncated_vendor_folders`,
  `truncated_driver_packages`, `truncated_drivers`,
  `truncated_components`, `truncated_additions`, `truncated_autostart` or
  `truncated_changes` > 0 means the summary
  holds only part of that list; the cut items are in the detail file.
  Ids are stable between runs, not positions, so the id of a cut item does
  not follow from the list: say how many were cut from each list and that
  the detail file has them. `--cut` lists the cut items (`id`, `list`,
  `name`); name one in the report only after fetching it with `--detail`,
  and then in the `ush:detail` line. A list whose count key is above 0
  (`truncated` for programs, `truncated_<list>` for the other seven) is cut:
  it holds any number of items, none included, and the order in which the
  lists are cut is the stage table under "Files and output" of
  `summary-contract.md`. Report such a list as cut, with its count key only (for `autostart` and
  `changes` also `autostart_counts` and `change_counts`, as their paragraphs
  say):
  the number cut, from the JSON; never a number of listed items or a sum,
  never as the whole list, never as empty, and never by a size it is
  assumed to keep. `truncated_changes` counts changes (a collapsed entry by
  its count), not entries. Among the
  drivers a `Display` driver comes first. A `summary budget` item in
  "Not checked" means the summary is over the budget and nothing was cut.
- `per_user_suffixes.json` in "Not checked": install pairs were not checked,
  so no program has `per_user_pair`; describe every program on its own and
  never say that no program is installed more than once.
- `windows-own.json` in "Not checked": besides the longer lists, every
  driver is listed with `third_party` in `unread_fields`, every firewall
  rule and every certificate (also of `authroot`) is listed except those
  trusted by `ush-inventory.first-run.json`, and
  `hosts_file.path_is_default` is unread.

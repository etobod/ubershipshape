# Report format (ush-runall)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/runall-<YYYY-MM-DD-HHMM>.md` (local time of the
run) and checked with
`python -B "<plugin root>/skills/ush-common/scripts/check_report.py" <report>` (or
`--latest --skill ush-runall` for the newest `runall-*.md`), which reads the
ush-runall rules from `data/report-profile.json`.
Follow `<plugin root>/skills/ush-common/references/report-style.md`: it says how every
report is written (time, numbers, dash, recommendation layout, language);
this file says what the combined report contains. Each child's own
`references/report-format.md` still says how to describe its findings
(sizes, memory, degradation cases); where it asks for a section of its own,
this report gives that content inside the sections below.
`<data dir>` is the data directory (`--data-dir`, else `USH_DATA_DIR`, else
the plugin data folder (`--default-data-dir`)); its absolute value is the directory above
`work/` in the summary's `summary_file`. The report text outside code blocks
writes it as `&lt;data dir>` in plain text, never in inline code (a `<`
before a letter fails the check, and inline code shows `&lt;` as it is), and
never the expanded path: it contains the account name, which a report must
not carry. The expanded path appears only in the `ush:summary` marker and
as the `--data-dir` value of every block that runs a skill script (rule 9 of
`report-style.md`).

The markers below are HTML comments: they do not depend on the report
language and do not show in a preview. Each marker stands on its own line,
outside quotes and lists; no other HTML comment is allowed. This file stays
in English; the report translates every heading and label, the table header
included.

There is one report for the whole pass, never a separate report per skill.

## Numbers

Every number in the report comes from the `runall` summary JSON, or from an
item of the `runall` detail file fetched with `--detail <id>` and named in an
`ush:detail` line. The checker is shared by all skills (see
`<plugin root>/skills/ush-health/references/report-format.md`, "Numbers", for the full
list); in short:

- A number of a child (a count, a size, a reading, the digits of a device
  name or of a child's item id) is backed only when that child's `h` item is
  named in an `ush:detail` line: `<!-- ush:detail h1 h3 h4 -->`. A number
  that is only in an `h` item the line does not name fails the check, even
  when the report never names that item. Name every `h` item whose numbers
  or ids you cite.
- The checker does not catch every unbacked small number: the ids of the
  `runall` summary itself (`h1`…`h7`, `w1`…) back their own digits, so a
  count from 1 to 7 (and up to the last `w` id) passes the check even when
  its child's `h` item is not on the `ush:detail` line. Check those by hand:
  cite such a count only from an `h` item you fetched and named.
- Never use a child's own `--detail`: its detail file is not part of the
  `runall` JSON, so its numbers have no backing here.
- Every run of digits is a separate number: `2026-05-07` is 2026, 5 and 7,
  `160.0` is 160 and 0. Write a number with the same digits and precision
  as the JSON, with the decimal separator of the report language (rule 2 of
  `report-style.md`) (in Polish `160,0`), counts without a thousands
  separator. Never add children's numbers up, never compute a difference
  or a percentage.
- The ids `h1`…`h7` and `w1`… are not numbers when they name an item of the
  summary or of an `ush:detail` line, or a `w` item cut from the summary
  (`truncated` > 0). A child's ids are not `runall` ids: write them with the
  skill (`ush-inventory s11`, `ush-events g3`); their digits are checked as
  numbers and backed by the named `h` item.
- An item a child cut from its own summary (the child's `truncated` and its
  other cut counts) is given as a number of items, never by its id: it is
  not in the `h` item, so its digits have no backing. Except the rule of a
  `firewall_ports` item (`ush-inventory x<n>` in its `rule`): the `runall`
  summary backs it, so it is cited even when the rule is not in `h4`.
- `summary_file`, `detail_file` and `program_path` back no number (the
  profile's `path_keys`). A program path with digits goes in a fenced code
  block, or the report names the program by its file name in words.
- The profile is looser than the children's: a child's paths and ids back
  digits here. `OK` from the checker means each number occurs somewhere in
  the JSON, not that it belongs where you put it; take every number from
  the field it stands for.
- Write every number in digits: a number word (`dwa`, `trzy`, `two`, in any
  case or form) outside code fails the check unless the same word is in a
  text value of the summary or of a named `h` item (a name). `ten`,
  `jeden`, `one` and `oba` are not number words.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Zapora`)
  is fine when the numbering of its level counts from 1 in order. The first
  cell of a table row is ignored when it equals the row's position among the
  table's data rows, so never put a count there.
- Fenced code blocks are not checked: never put a finding's number in one.
- No HTML and no links outside code blocks: write a literal `<` as `&lt;`
  and a literal `]` before `(` or `:` as `&rsqb;`.

## Items the report must name

Every `children[*].id` (`h1`…`h7`) and every `firewall_ports[*].id` (`w1`…)
of the summary appears in a visible line of the report, as a word of its own
(`h12` does not name `h1`), each with a short name after it (rule 6 of
`report-style.md`): the skill for an `h` item, the rule's name or program
for a `w` item. An id on an `ush:detail` line, on another marker line or in
a fenced code block does not count. The check lists each missing id as
`not named in the report: <id> (<list>)` and fails. A `firewall_ports` that
is `null` requires nothing.

## Blocks

`runall` passes no flag to a child (no `--block`, no `--export`), so it
produces no block and changes nothing. The report proposes a change in
words and holds no change block (rule 8 of `report-style.md`). After the user
decides, the model puts the change blocks into a repair plan per
`<plugin root>/skills/ush-common/references/repair-plan.md`, never into the chat or the
report: each block printed by the child's print-only `--block`
(`ush-settings`, `ush-files`, `ush-inventory`), word for word, with its
shell, risk and rollback. A child without a `--block` printer (`ush-events`,
`ush-health`) gives, after the decision, the block from its own `SKILL.md`
template for the repair plan, filled with values from the child's detail
file and with every guard of the template kept (stamped backup, verify,
abort, rollback); in words only where the child has no template for that
change. The model checks the plan with
`python -B "<plugin root>/skills/ush-common/scripts/check_repair_plan.py" <file>` and tells
the user which file to open. Every block is one the user pastes into their own
shell (an elevated PowerShell where the child's rules say so) and runs
themselves; you never run it. After the user ran a block, a new run reads the
values back; the result goes under `Notatki` and the plan is moved to
`plans/done/` only when every value the plan sets reads back as set (see the
step before judging); otherwise it stays open; it is never deleted.

## Layout

### 1. Header

First line, exactly:

```
<!-- ush:summary <absolute summary_file path> -->
```

Then the title with the time of the pass (`generated_at`, in local time with
the UTC time in brackets, rule 1 of `report-style.md`) and its length
(`duration_s`). Then the `ush:detail` line with every `h` item (and every
cut `w` item) whose numbers or ids the report cites:

```
<!-- ush:detail h1 h3 h4 -->
```

A named id that is not in the detail file fails the check.

### 2. Verdict (Werdykt)

Right after the header, so the user reads the answer first:

- When a recommendation is worth a look: its name and its one-line title
  (the `Problem` of rule 4 of `report-style.md`, shortened), one line each,
  in the order of the recommendations. A recommendation is named by its main
  source, `ush-<skill> <id>` (the first source of its evidence, see
  "Recommendations"); a report never makes up an id of its own (such as
  "Z1"): its digits would be backed by no number of the JSON. With none: "wszystko w porządku"
  (in the report language).
- The verdict gives no count of its own ("3 rzeczy warte uwagi" is not
  written): every number in a report comes from the script's JSON, and the
  listed names already show how many there are. Only the memory line below
  carries numbers.
- The memory line: one line with the memory assessment of `ush-processes`,
  with `used_percent` and `available_gb` of the processes summary
  (`memory` in its `h` item, named in `ush:detail`). The judgement is
  yours, in plain words; the script sets no threshold. When `memory` is not
  `read` (its values `null`), the line says that memory was not read and
  its reason goes to "Not checked".
- Open repair plans: every open repair plan in `<data dir>/plans/` (not
  the ones in `plans/done/`), by file name, one per line in a fenced code
  block, never in inline code, with a note that they are not confirmed by a
  read-back yet (the last result, if any, is under its `Notatki`) (see `<plugin root>/skills/ush-common/references/repair-plan.md`). The
  report checker checks the digits in inline code (the date in a plan's
  name) against the summary JSON and skips a fenced code block. The chat
  answer names them the same way. With none, the line is left out.
- When `<data dir>/plans/` cannot be listed, the verdict says that the
  open repair plans could not be listed, and the reason goes to "Not
  checked"; it is never "no open plans".

### 3. Run state

One line per item of `children`, in order: id, skill, `status` in words,
`duration_s`, and for an `ok` child its `not_checked_count`, its own
`truncated` and its `elevated` (`null`: the child does not report it, as
`ush-events`). Every `h1`…`h7` stands here in the text. A child other than
`ok` gives its status in words (failed, timed out, gave no valid summary)
and that its findings are not in this report; its reason goes to "Not
checked". Then `counts` in one line.

### 4. Recommendations

One list for the whole machine, by weight: `high` first, then `medium`, then
`low`. Each recommendation has the problem in plain words (`Problem`), what
to do now (`Co zrobić`) and `weight`, then `Szczegóły` with `kind`, `risk`,
`evidence`, `permissions` and `rollback`, in the layout of rule 4 of
`<plugin root>/skills/ush-common/references/report-style.md` (the fields are in
`<plugin root>/skills/ush-common/references/summary-contract.md`, "Recommendations"), and
its source as `ush-<skill> <id>` in the evidence (several sources when it
rests on linked findings). The first source is its main source: it names the
recommendation in the verdict and in "Co możesz zrobić". A weight that comes from the strongest linked
finding says so and why. With no recommendation, write the sentence of rule
14 there.

`Co zrobić` proposes the change in words; no block stands in this section
(see "Blocks"). For a fault this machine cannot explain offline (a device
problem code, a crash or stop code), the next step offers "sprawdź w sieci
przez ush-advice" (check online with `ush-advice`): the user runs that skill
separately. `runall` itself stays offline and searches nothing.

Old memory dumps: when `dumps.older_than_window` in the `ush-events` `h`
item is above 0, one line says that this many memory dump files are older
than the events window, with that count as given. Their stop code is not in
this report: it goes under "Not checked" as "needs administrator". They get
one recommendation of weight `low`, with the fields of rule 4 of
`report-style.md`, named by the
first old dump file, `ush-events d<n>` (the file ids are in the `h` item:
`dumps.files` is never truncated). With `0` the line and the recommendation
are left out. With `null` the dumps could not be listed: they go under "Not
checked" with the child's reason, never as "no old dumps".

### 5. Changes since the last run (Zmiany)

The pass has updated the baselines of the children, so a later run of a
single skill will not show these changes again. That is why this section
exists, but it is a short summary, not the full lists:

- new programs by name;
- updates: by name only from the change items the child lists in its
  summary (`changes` of `ush-inventory`), at most 10, then "reszta w pliku
  szczegółów" with no count; changes of Windows' own items as the child's
  own counts per source (`own_changes.by_source`), each number as given,
  never added to the listed names or to each other; then "nic
  podejrzanego" or what is suspicious;
- the firewall as one conclusion; a collapsed entry of the child's
  `changes` (`collapsed`, no id) is one line per change type, in the
  child's wording "<N> zmian `ms-resource:` zwiniętych w jedną linię", with
  N its `count` as given, never added to another type or to the listed
  names;
- disks as growth, plus what can be removed (see the clean-up section);
- settings in one line.

Each line cites its source as `ush-<skill> <id>` where it names an item,
and takes its numbers from the child's `h` item. The full lists of every
child stay in the `runall` detail file (one `h` item per child): the section
names it in words (in the report language), as `detail_file` of the
`runall` summary in &lt;data dir>\work, the data directory written as at the
top of this file, and says that the full lists are there; it never writes
its file name or expanded path (the name carries digits no number backs, the
path the account name). A child whose baseline was missing or unreadable gives
"no comparison" for it, never "no changes". With none, say so per child.

### 6. Disk clean-up (Porządki)

One line per item of `cleanup` in the `ush-files` summary (`h6`), in its
order:

- its `what`, and the size it frees: `gb` (everything in the place), or,
  when the item has `min_age_days` above 0, `gb_older` with that age (only
  the files older than `min_age_days` days, which is what its block
  deletes);
- an item whose `status` is not `read` gives the status in words instead
  of a size alone: `empty` (nothing there), `unreadable` or `not_measured` (not
  measured; its `reason` goes to "Not checked"), never as 0. A `partial`
  item gives its size and says that it counts only the part that could be
  listed.

The section says what each line frees and that the user chooses which, if
any, to clean. Never a total: do not add the items up or give their sum
("Never add children's numbers up").

### 7. Links between skills

One entry per link: findings of different children about the same device,
driver, setting or time (for example a graphics crash after resume in
`ush-events`, a power setting in `ush-settings` and the display driver in
`ush-inventory`), each with its source `ush-<skill> <id>` and the value that
ties them (the same name, id, path or time in the JSON). A link is never
invented: without one, write that the findings of the children have no
common point.

### 8. Contradicting findings

Findings of different children that say different things about the same
thing, side by side, each with its source and value, without deciding
between them. With none, say so in one line.

### 9. Firewall rules and listening ports

Facts only; the script judges nothing and the report decides no risk on its
own. First the network categories: `network_categories` in words (`{}`: no
network profile, no connection; `null`: not read). Then every item of
`firewall_ports`, in the summary's order:

- id and short name (`rule_name`, or the program's file name), the rule
  (`ush-inventory x<n>`), `protocol` (6: TCP; `null`: every protocol) and
  `lport` (`null`: every port, since a rule with `lport2` is never matched);
- where the program listens: each `listening` port with its
  `local_address`, `local_port` and `scope`; `loopback_only` `true` means
  only on the loopback address (from this machine only), `false` means on
  other addresses too;
- the rule's `profile` set against `network_categories`: `Domain` in a rule
  is `DomainAuthenticated` in a network category, `null` means every
  profile, a list means each of its profiles;
- `app_exists` `false`: no file at that path for the account that ran the
  pass; `null`: not checked.

Then one line with `firewall_ports_counts`: `inbound_rules`, and the rules
counted `not_listening`, `not_compared`, `udp` and `other_protocol` (only as
counts, never one by one), and `ports_without_path` (listening ports that
were not compared: their program has no file, such as System, its path could
not be read, or the port has no group). With `truncated` > 0, one line: how
many items are only in the detail file.

Say plainly that `ports_without_path` also counts the ports of processes
with no file (System), while the port count of "Nie sprawdzono" ("Not
checked") covers only the ports whose program path could not be read (or
that have no group), so the two numbers differ: give both as they are,
never as the same thing and never as a contradiction. The "Nie sprawdzono"
port item exists only when the runall `not_checked` holds it; without it,
give `ports_without_path` alone and never write the other count as 0.

`firewall_ports` `[]` means that no
active inbound Allow rule matched a listening program; `null` means the
comparison was not made: say so and give the reason in "Not checked".

### 10. Run with administrator rights

Only when a child has `elevated` `false` and `not_checked` entries that need
administrator rights:

- The report gives one block for an elevated PowerShell that runs
  `runall.py` with `--data-dir` (the absolute data directory) and a
  `Set-Location` line (rule 9 of `report-style.md`), never the elevated
  re-run blocks of the single skills (a change block, given after the
  user decides, keeps its elevated parts); it says what that pass reads more and that it
  changes nothing.

```powershell
Set-Location "C:\proj"
python -B skills/ush-runall/scripts/runall.py --data-dir "C:\dane\ush"
```

Without such entries this section is left out.

### 11. What you can do (Co możesz zrobić)

The last section before "Not checked": the actions of the recommendations
(their `Co zrobić`), one line each, named by the recommendation's main source,
`ush-<skill> <id>`, in the
order of the recommendations; a clean-up the user may choose is one line
too. Each line proposes in words; no block stands here (see "Blocks"):
after the user decides, the blocks go into a repair plan per
`repair-plan.md`, not into the chat. With no
recommendation, it says that nothing needs doing.

### 12. Not checked

Always last. Its marker stands directly before (or right after) the section
heading:

```
<!-- ush:not-checked -->
## Not checked
```

It lists every `not_checked` item of the `runall` summary with its `what`
and `reason` (a child that did not finish, the firewall comparison not
made, listening ports whose program path could not be read), and, per
child, the child's own `not_checked` entries from its `h` item (their
number is `not_checked_count`). If every list is empty, it says "nothing".

## Account names

A report never carries the account name, except in the data directory path
where the section above allows it. A `program_path`, a child's path and a
`not_checked` reason often start with the profile folder, `C:\Users\`
followed by the account name: write that folder as `%USERPROFILE%`. In a
paste-ready PowerShell block (a child's change block) never write
`%USERPROFILE%`: Windows PowerShell does not expand it. Build the path from
the environment as the child's own report format says, for example
`(Join-Path $env:USERPROFILE 'AppData\Roaming\Invented\tray.exe')`, so the
pasted command writes the same value back.

## Identifiers

The `h` items hold whole child summaries, and with them values that never
go into a report: the computer name, account names, SIDs, serial numbers
and device instance ids, MAC addresses, and the addresses of the private
network (DNS servers, gateways, local IPs), also inside a quoted event
sample. Name a device by its name, an account by its role (the user's
account, an administrator), and shorten a sample around such a value. The
"Account names" rules of each child's own `report-format.md` still apply.

## Values that are not readings

- `null` is "not read" (or "unknown" in the plain sense), in words, never
  "no", "none" or "0".
- `summary` `null` in an `h` item: the child gave no summary; nothing of it
  is in this report.
- `elevated` `null`: the child does not report it, not "no".
- `firewall_ports` and `firewall_ports_counts` `null`: not compared, never
  "no open rules".

## Degradation cases

Never report missing data as "none", "nothing there" or "no change":

- A child `failed`, `timeout` or `bad_output`: its area was not checked in
  this pass; give its reason in "Not checked". A timeout whose reason says
  that stopping the processes it started was not confirmed: say that one of
  them may still be running.
- The firewall comparison not made (`null`): give the reason of its
  `not_checked` item.
- Firewall rules that could not be read: give the count of its
  `not_checked` item; they are in none of the firewall counts.
- Listening ports with an unread program path: the rules counted
  `not_listening` may belong to one of those programs; give the count of
  the `not_checked` item. That count is part of `ports_without_path`, which
  also counts the ports of a program without a file (System):
  give both as they are, never as the same thing and never as a
  contradiction.
- A child's own cut lists (`truncated` and its other cut counts above 0):
  give the numbers.
- `firewall_ports` cut (`truncated` > 0): give the number and that the
  detail file has them.

# Report format (ush-advice)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/advice-<YYYY-MM-DD-HHMM>.md` (local time of the
run) and checked with
`python -B skills/ush-common/scripts/check_report.py <report>` (or
`--latest --skill ush-advice` for the newest `advice-*.md`), which reads the
ush-advice rules from `data/report-profile.json`. Follow
`skills/ush-common/references/report-style.md`: it says how every report is
written (time, numbers, dash, recommendation layout, language); this file
says what the ush-advice report contains. `<data dir>` is the data directory
(`--data-dir`, else `USH_DATA_DIR`, else `%LOCALAPPDATA%\ubershipshape`); its
absolute value is the directory above `work/` in the summary's
`summary_file`. The report text outside code blocks writes it as
`&lt;data dir>` in plain text, never in inline code, and never the expanded
path: it contains the account name, which a report must not carry. The
expanded path appears only in the `ush:summary` marker and as the
`--data-dir` value of every block that runs a skill script (rule 9 of
`report-style.md`).

The report is written from the summary of the run with `--findings`. A
summary of a run without it has every list `null` and gives only the machine
facts: such a report says that the search was not done.

The markers below are HTML comments: they do not depend on the report
language and do not show in a preview. Each marker stands on its own line,
outside quotes and lists; no other HTML comment is allowed. This file stays
in English; the report translates every heading and label, the dashboard
header included.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. A number read
on a web page reaches the report only through the findings file and the
script. The checker is shared by all skills (see
`skills/ush-health/references/report-format.md`, "Numbers", for the full
list); in short:

- Every run of digits is a separate number: `2026-09-02` is 2026, 9 and 2,
  `26200.6899` is 26200 and 6899. Write a number with the same digits as the
  JSON, with the decimal separator of the report language (rule 2 of
  `report-style.md`). A build (`26200.6899`), a fixed build, a KB number and
  a BIOS version (`1.20`) are identifiers, not decimal numbers: copy them
  exactly as the JSON has them, with their dots, in a Polish report too.
- The values that back a report's numbers: the `machine` facts (`build`,
  `ubr`, `hotfixes`, `firmware.bios_version`, `firmware.bios_date`), and in
  the lists `month`, `kbs`, `fixed_builds`, `kb_installed`, `cve`,
  `version`, the dates and the counts. Quote a KB, a CVE, a fixed build or a
  BIOS date from these fields.
- A finding's `title`, `url`, `domain` and `query`, and `summary_file` and
  `detail_file`, back no number (the profile's `path_keys`): a number that
  is only in a title fails the check, even when the page said so.
- Item ids (`u1`, `k2`, `f1`, `i3`, `w4`) are not numbers when they name an
  item of the summary, an item named in `ush:detail` or an item cut from the
  summary (`truncated`, `truncated_exploited`). A query warning's
  `finding_id` is an id, never a number (the profile's `id_keys`). A word of
  that shape that is no such id is checked as a number.
- Write every number in digits: a number word (`dwa`, `trzy`, `two`, in any
  case or form) outside code fails the check unless the same word is in a
  text value of the summary (a name). `ten`, `jeden`, `one` and `oba` are
  not number words.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Firmware`)
  is fine when the numbering of its level counts from 1 in order. The first
  cell of a table row is ignored when it equals the row's position among the
  table's data rows, so never put a count there.
- Fenced code blocks are not checked: never put a finding's number in one.
- No HTML and no links outside code blocks: write a literal `<` as `&lt;`
  and a literal `]` before `(` or `:` as `&rsqb;`. An address goes in
  inline code, never as a link.

## Items the report must name

Every `updates[*].id`, `exploited[*].id` and `firmware[*].id` of the summary
appears in a visible line of the report, as a word of its own (`u12` does
not name `u1`). Several ids on one line are fine. A mention inside a fenced
code block or on a marker line does not count. The check lists each missing
id as `not named in the report: <id> (<list>)` and fails. A `null` list
requires nothing. Exploited items cut from the summary
(`truncated_exploited`), the known issues (`issues`) and items fetched with
`--detail` are not required; name the issues you describe.

## Layout

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

2. Title and one line: when the summary was made (`generated_at`, rule 1 of
   `report-style.md`) and the machine: `machine.display_version`, the build
   with its UBR (`build`.`ubr`), `edition_id`, `architecture` and `product`
   (when `product` is `null`, say what `product_reason` says: a version not
   in the product map, or a version that could not be read; never one for
   the other).

3. Dashboard: a table with one row per area, in this order: updates,
   exploited vulnerabilities, firmware, known issues, then the changes row.
   `State` is a few words
   with the ids and values from the JSON; `Action` a few words, no numbers
   of your own. An area whose list is `null` says „not checked” in `State`.

   | Area | State | Action |
   |---|---|---|
   | Updates | u1 2026-09 (KB5099901) installed | none |
   | Exploited vulnerabilities | k1 CVE-2026-40001 fixed here | none |
   | Firmware | f1 Contoso Book 14 BIOS 1.20 unverified | see below |
   | Known issues | i1 Invented issue | see below |
   | Changes | compared with the baseline of 2026-09-20 09:15 (07:15 UTC), 14 days old; updates: u1 2026-09; issues: nothing new; exploited, firmware: no comparison | see below |

   The last row is the changes row (rule 12 of `report-style.md`):
   - Its time part (rule 12), by `baseline.status`: `compared` gives the baseline
     time as in rule 1 (`baseline.created_at`) and its age
     (`baseline.age_days`); `none` gives „first run”; `unreadable` gives
     „baseline unreadable” with `baseline.reason`, without a time.
   - Then each list (`updates`, `exploited`, `firmware`, `issues`) by its
     `comparison.<list>`: `compared` gives the ids of its items with `new`
     `true`, each with a short name (rule 6), or „nothing new”; `not_read`
     gives „no comparison”, the search was not read; `no_baseline` gives
     „no comparison” too, never „nothing new”: with `baseline.status`
     `none` it is the first run, with `unreadable` the baseline could not be
     read, and with `compared` the list has no saved keys yet (it is read
     for the first time).
   - When `truncated` or `truncated_exploited` > 0, the items cut from that
     list are only in the detail file and the row does not cover them.
   - The row gives no count of new items: the summary has none, and a
     count of your own breaks „every number from the JSON”.
   - A Polish report writes „pierwszy przebieg”, „nie porównano” and „nic
     nowego”.

## Sections

After the dashboard the report has these sections, in this order, each with its
heading translated into the report language.

### Update state

The installed update ids (`machine.hotfixes`), then one
bullet per month (`u..`, newest first) with `month`, `kbs`,
`fixed_builds`, whether it is applied (`applied`: `true` installed,
`false` not installed, `null` not known, with `applied_reason` in words),
`kb_installed` and the counts.
- Name `cve_count` „CVEs recorded in the findings” (in a Polish report
  „CVE zapisane w ustaleniach”), never „CVEs fixed”: it counts what was
  written down, not what the month fixed. `critical_count` is the part of
  them rated Critical.
- `cve_count` and `critical_count` `null` are „not counted” (in a Polish
  report „nie policzono”): no CVE list from the MSRC (CVRF) document, never
  0.
- `kb_installed` is information only: a KB missing from it with
  `applied` `true` is not a missing update.
- A month whose `listed` is `false` is described in „Unverified”, not
  here; name its id here with a pointer.

### Exploited vulnerabilities

One bullet per item of `exploited` (`k..`)
with `cve`, `vendor` and `product`, `date_added`, `due_date`,
`ransomware`, the `month` that fixes it and whether that fix is applied
here (`applied`).
- `kev_other_count` is the number of distinct CVEs of `exploited` findings that are in
  none of the recorded update months. With the procedure of `SKILL.md`
  (KEV asked only about the CVEs of the update findings) it is normally 0;
  give it as a count, without an alarm for this machine, and never as a
  check of exploited vulnerabilities outside those months.
- When `truncated_exploited` > 0: how many were cut, their ids, and that
  the detail file has them.

### Firmware

The BIOS of this machine from `machine.firmware`
(`manufacturer`, `model`, `bios_version`, `bios_date`), then one bullet
per item of `firmware` (`f..`) with `version`, `release_date`,
`model_matches`, `same_version` and `newer` in words: `newer` `true` „the
manufacturer offers a newer BIOS”, `false` „no newer BIOS”, `null` „not
known” (another model, no date, or the BIOS not read).

### Known issues

One bullet per item of `issues` you describe (`i..`) with
`title` in the report language and `published`. When `truncated` > 0: how
many were cut and that the detail file has them.

### New since the last check

First the baseline: compared with the baseline
of `baseline.created_at` (rule 1 of `report-style.md`),
`baseline.age_days` days old, or „no comparison” with the reason (see
„Degradation cases”). Then the ids of the items with `new` `true`, per
list. A list whose `comparison` is not `compared` has no new items to
tell: say „no comparison” for it, never „nothing new”.

### Unverified

Every item with `listed` `false`, from any list, with its id
and what its page claims, as a claim of a source outside the list, never
as a fact. „Nothing” when there is none.

### Recommendations

Each with `weight`, `kind`, `risk`, `evidence`,
`permissions` and `rollback` in the layout of rule 4 of
`skills/ush-common/references/report-style.md` (the fields are in
`skills/ush-common/references/summary-contract.md`, „Recommendations”).
With none, write the fixed sentence of `report-style.md`.
- „Install the update”: for a month with `applied` `false` and `listed`
  `true`; a month with `listed` `false` goes to „Unverified” instead. Evidence:
  the month's id, `kbs`, `fixed_builds` and the build with its UBR;
  permissions: administrator; risk: a restart, and a known issue of
  `issues` when one applies; rollback: uninstall the update in Windows
  Update, update history.
- „Update the BIOS from the manufacturer's page”: for a firmware item
  with `newer` `true`. Evidence: the item's id, `version`,
  `release_date`, `bios_version` and `bios_date`; permissions:
  administrator; risk: a failed BIOS update can leave the machine
  unable to start (mains power, the manufacturer's steps); rollback:
  only what the manufacturer allows (some BIOS updates cannot be
  undone). A finding with `listed` `false` is recommended only as
  „check the manufacturer's page”.
- The read-back of either is a new run with a new findings file: the
  month then has `applied` `true`, or the item `newer` `false`. A
  message from the installer is not a read-back.

### Items fetched with `--detail`

Name every id you used, on one or more
lines anywhere in the report:

```
<!-- ush:detail w3 k4 -->
```

A named id that is not in the detail file fails the check.

### Not checked

Always last. Its marker stands directly before (or right
after) the section heading:

```
<!-- ush:not-checked -->
## Not checked
```

It lists every `not_checked` item with its `what` and `reason`, and
names every `unreadable` job of `sources` and every search of
`searches` that is not `read`, with its status and reason. A query
warning names its finding id and reason, never the query. If
`not_checked` is `[]`, it says „nothing”.

## Account names

A report never carries the account name, except in the data directory path
where the introduction of this file allows it. A `not_checked` reason that names a path
inside the data directory is written with `&lt;data dir>` in its place.

## Values that are not readings

- `null` is „not known” (or „not read”), in words, never „no”, „none” or
  „0”.
- A `null` list when its search is `partial` or `unreadable` (or missing
  from `searches`) goes to „Not checked” with the search's reason, never as
  „none” or „no updates”. Only `[]` (a `read` search with nothing found) is
  „none found”.
- `exploited` is also `null` without a read `msrc` (no CVE list of the
  update months) or without a read `release-info` (no update months).
- `applied` `null` („mixed”, „build mismatch”, no security release, the
  build not read) is „not known”, never „not installed”. A `preview` release
  is optional and never makes a month „not installed”.
- `model_matches` `false`: the finding is for another model; its `newer` is
  `null`.
- `listed` `false`: the address is outside the list of sources; the item is
  unverified, not false.

## Degradation cases

Never report missing data as „up to date”, „none” or „no changes”:

- No search done (`searches` `null`, a `not_checked` item `web search`):
  the report gives the machine facts and says the comparison was not done.
- A search `partial`, `unreadable` or `missing`: its list is `null`; say
  what was not checked and why.
- A job `unreadable` (`os_version`, `hotfixes`, `firmware`): its machine
  facts are `null`; `applied`, `kb_installed` or `newer` are then „not
  known”.
- `query_warnings` not empty: a query or address held a fact of this
  machine; say so at the top of the report, with the finding ids and the
  reasons.
- First run (`baseline.status` `none`): „no comparison: this is the first
  run; the next run compares with this one”.
- A baseline that could not be read (`baseline.status` `unreadable`):
  nothing was compared; give the `reason`.
- `baseline.saved` `false`: with the item `baseline save` the next run
  compares with the older baseline; without it no list was compared and the
  baseline was left as it was.
- Items cut (`truncated` or `truncated_exploited` > 0): give the numbers and
  say that the detail file has them.

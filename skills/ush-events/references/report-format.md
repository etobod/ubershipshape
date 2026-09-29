# Report format (ush-events)

The report is Markdown in the language the user addressed the skill in. It is
saved as `ush-data/reports/events-<YYYY-MM-DD-HHMM>.md` and checked with
`scripts/check_report.py`. The markers below are HTML comments: they do not
depend on the report language and do not show in a preview. Each marker
stands on its own line, outside quotes and lists; no other HTML comment is
allowed.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. The check reads
numbers this way:

- `0x...` is one hex number: `0x19C` matches `0x0000019c` in the JSON. A hex
  number is backed only by a hex value, a decimal number only by a decimal one.
- Every other run of digits is a separate number: `18.09.2026` is 18, 9 and
  2026; `3,5` is 3 and 5; `1 234` is 1 and 234; leading zeros do not matter.
  So dates and times may be written in local format and a decimal comma is
  fine, but write counts without a thousands separator (`1234`, not `1 234`):
  its parts are rarely in the JSON on their own.
- No numbered lists: use `-` bullets.
  A number at the start of a line (`1. `, `412. `, `- 4. `, `> 3. `) is
  checked like any other number, so a numbered list fails unless its
  numbers happen to be in the JSON.
- Ignored: the number of a numbered heading (`## 2. `) when the numbering
  of its level counts from 1 in order: the first numbered `##` heading is
  `## 1.`, the next `## 2.`, and the count starts again under every heading
  of a higher level (fewer `#`). Write every heading with `#`: a heading
  underlined with `===` or `---` does not start the count again. Any other
  heading number (`## 412.`, a
  skipped or repeated number) is checked, and so is a heading number in a
  `>` quote. Also ignored: the number in the first cell of a table row when it
  equals the row's position among the table's data rows (`| 3 | ...` as the
  third row; start every table row with `|`), and the marker lines
  (`ush:summary`, `ush:detail`, `ush:not-checked`). Therefore never put a
  count in the first cell of a table row.
- Item ids (`g3`, `n1`, `a2`, `b0`, `r4`, `d1`) can be written freely: an id of a summary
  item, of an item named in `ush:detail` or of a group cut from the summary
  (`truncated`) is not a number, and the `id` values of the JSON back no
  number: a count next to an id must come from a reading. (Other fields
  still do: a boot's `index` backs its own digits.) A word of that shape that is
  no such id is checked as a number. The same holds for the links
  `dump`, `bugcheck` and `bugcheck_candidates`: they back no number.
- Paths and file names (`path`, `name`, `dump_path`, `minidump_dir`,
  `dump_file`) back no number either: the digits of a minidump's name are
  not a reading, and a name or path with digits written in the text (a code
  span included) fails the check. Name a dump by its id (`d1`); a full path
  may appear only inside a fenced code block.
- Fenced code blocks (the paste-ready commands of a `change`) are not
  checked: a command needs its own constants. Never put a finding's number
  in a code block. Markers inside a code block do not count, and a block
  left open fails the check.
- Fences follow CommonMark. A fence line starts with at most 3 spaces: a
  code block at the top level or directly in a first-level `-` item (the
  check also accepts one under a numbered item, but a report has no
  numbered lists), never in a nested list item or in a `>` quote; otherwise
  the fence is not recognised and the command's constants are checked. A
  block opens with 3 or more backticks or tildes (a backtick fence has no
  backtick after it) and closes only on a line of the same character, at
  least as long, with nothing after it. Put the closing fence at exactly
  the indent of the opening fence: a closing fence at another indent fails
  the check (a preview may close the block there and show the lines after
  it unchecked). Indent every other line of a block at least as far as its
  opening fence (a block in a list item ends with the item); a line indented
  less fails the check. Never open a fence on the line of a list marker
  (`- ```powershell`): write the item's text after the marker and the
  fence on its own line below; a fence after a marker fails the check.
- No HTML and no links. The only HTML comments are the `ush:` markers. A
  marker is the whole line, never in a `>` quote or a list item, with
  nothing after it. Any other `<!--` fails the check, wherever it stands: in
  text, in a quote, after a backslash or in inline code. Write a literal
  `<!--` (in a quoted sample) as `&lt;!--`; a preview shows it as the opener.
  Outside code blocks, `<` directly before a letter, `?`, `!` or `/` fails the
  check anywhere in a line (a tag such as `<details>` or `<span>`, an
  autolink, `<?...`, `<![CDATA[`), and so do `]:` (a link reference
  definition) and `](` (a link or an image): a preview hides them or their
  target. Write a literal `<` there as `&lt;` (an event's `sample`:
  `> &lt;Data> text`). `<` before a space, a digit or `=` is text (`a < b`,
  `<= 3`). A placeholder such as `&lt;data dir>` goes in plain text or in a
  code block, never in inline code: inline code shows `&lt;` as it is and
  `<` fails the check. Name items in plain text, never as a link. Write a
  literal `]` before `:` or `(` (an event's `sample`) as `&rsqb;`
  (`> proc[x&rsqb;: text`); a preview shows it as `]`, and `\]` still fails
  the check. Inside a
  code block `<`, `]:` and `](` are fine (`<# ... #>` in PowerShell).
- Every other number is checked, in text, tables and quotes.
  Do not add up, average or convert numbers yourself; do not convert times to
  another time zone (the JSON times are UTC; write them as UTC or say so).

## Items the report must name

Every `groups[*].id`, `anomalies[*].id` and `dumps.files[*].id` of the
summary appears in a visible line of the report, as a word of its own
(`g25` does not name `g2`). A mention inside a fenced code block, on the
`ush:summary` line or on an `ush:detail` or `ush:not-checked` marker line
does not count. The check lists each missing id as
`not named in the report: <id> (<list>)` and fails. Boot sessions (`b`),
noise items (`n`), reliability records (`r`), groups cut from the summary
(`truncated`) and items fetched with `--detail` are not required. A group
that is not a finding goes on the "Other groups" line (layout, item 5).

## Layout

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

   The path is the `summary_file` value from the summary.

2. Title and one line: the window (`window.start` to `window.end`) and when
   the summary was made (`generated_at`).

3. Dashboard: a table with one row per finding, in the order of the sections
   below.

   | # | Finding | Count | Trend | Action |
   |---|---|---|---|---|
   | 1 | Bugcheck 0x0000019c | 1 | - | 🔧 see below |
   | 2 | Disk 7 (g1) | 5 | rising (0, then 5) | 🔍 run again later |

   `#` is the section number of the finding, `Count` a count from the JSON,
   `Action` a legend symbol and a few words (no numbers of your own). A row
   that covers several groups gives each group's count with its id
   (`g6: 11, g22: 2`), never one group's count for all of them.

   `Trend` is the group's `trend` as written in the JSON (in the report
   language), optionally with its `first_half` and `second_half`; the
   script sets it by the rule in `data/trend.json`
   (`references/summary-contract.md`). A row without a group (an anomaly,
   stability) has `-`; a row of several groups gives each group's trend with
   its id. Read it this way:
   - `unknown` (the log does not cover the whole window, or the time of its
     oldest record could not be read: see `not_checked` for which) and `too_few` (too
     few events to compare) are neither rising nor calm: write them as
     such, never as `stable`, and never as a reason to worry.
   - The trend is not a weight. A rare critical error stays important
     however it trends, and a `rising` harmless message stays harmless; the
     weight comes from what the events mean (`references/summary-contract.md`).
   - Never compute a trend, a ratio or a difference yourself.

4. Legend, under the dashboard:

   - 🔧 change - a fault the user can fix; the section gives the steps.
   - 🔍 observe or check - not clear yet; watch it, run again later, or
     check one more thing (including `consult_service`).
   - ✅ fine - read and nothing wrong (a source read with no events, noise).
   - ❌ problem found - a fault with no fix the user can apply themselves
     (for example failing hardware); the section says who can help.

5. One section per finding (`## 1. <name>`, `## 2. <name>` and so on, in
   order from 1), most important first:
   - what happened, with the numbers and times from the JSON and the ids
     (`g3`, `a1`);
   - a quoted sample from the group's `sample` (a `>` block, shortened if
     needed);
   - the judgement, and a recommendation with `weight`, `kind`, `risk`,
     `evidence`, `permissions` and `rollback`
     (`references/summary-contract.md`). A `change` gives a paste-ready block
     and how to read the value back afterwards.

   The groups that are not a finding go on one line at the end of the last
   finding section, written in the report language, each with its id and
   `count`: `Other groups: g29 (2), g22 (1), ...`. With no findings, put
   that line in a section of its own right after the dashboard and its
   legend.

6. Known noise, a separate section: one line per noise item with its
   provider, Id, `count` and `reason`. Noise is not a finding and is not
   hidden.

7. Boot sessions: how many, which ended without a clean shutdown
   (`clean_shutdown` false), and which anomalies fall into which session.
   Name the sessions with `hibernate_resumes` > 0 with their values, and the
   sessions whose `boot_type` is not `cold`, each on its own (no sums):
   `fast_startup`, or `null` = the type is unknown (always in session 0),
   never read as Fast Startup. `clean_shutdown` `null` before a Fast Startup
   boot, before a boot whose type could not be read (see "not checked"), or
   before a boot (cold or without a type) that reported the last shutdown as
   successful (a Fast Startup or hibernate shutdown writes no 6006), means
   "unknown", not "unclean". A 6008 or Kernel-Power 41 in the following
   session keeps `false`, even when that session is `fast_startup`. A `fast_startup` session
   does not take the next boot's markers (a Fast Startup boot writes only its
   Kernel-Boot 27), so the anomalies listed in a `fast_startup` session
   belong to it. A session named in "not checked" as joined by a Fast Startup
   Kernel-Boot 27 without a typed one of its own is not certainly Fast
   Startup: name it there, with the ids from that entry.

8. Stability (Reliability Monitor): from `reliability` and
   `reliability_records`.
   - The lowest day: `lowest` (`date` and `index`), and the latest day of
     `daily` for comparison.
   - The drops you think matter, chosen from `drops`, each with its `date`,
     `index` and `previous_index` as written there. Never compute a
     difference, an average or a trend yourself; name only values that are
     in the JSON. If you name only some drops, say that it is a selection
     (do not count the rest yourself).
   - The record groups that explain a drop or a finding, with their ids
     (`r1`) and `count`, `source` and `product`. With `products` > 1 never
     attribute the `count` to `product`: say that the group covers
     `products` applications and `product` is only the newest. Tie a record group to a
     drop only by its `first`/`last` dates, and say that it is a link in
     time, not a proven cause.
   - `status` `empty` or `daily` `[]`: read, but the Reliability Monitor
     recorded nothing in the window. Windows records the index regularly
     while its collection runs, so say that the collection may be off or its
     data cleared (🔍); never ✅ and never "stable".
     `unreadable`: give the `reason`, no conclusion. The same for
     `records_status`, `reliability_records` `null` meaning the records
     could not be read.

9. Memory dumps: from `dumps` and each bugcheck's `dump_path` and `dump`.
   - The settings: `crash_dump_enabled` as written, and where
     `minidump_dir` and `dump_file` point (paths without digits may be
     written); name those in `defaulted` as "Windows default". A value in
     `defaulted` was not set on the machine: it is the assumed Windows
     default, not a reading; say so.
   - Each file with its id (`d1`), `size`, `modified` and whether it is
     `readable`. `readable: false` with a `needs administrator` reason: the
     dump is there but locked or protected, not missing, and its content is
     unchecked.
   - Links: a file's `bugcheck` and the bugcheck's `dump` are a link by path.
     With `bugcheck` `null` and several `bugcheck_candidates` (typical for
     `MEMORY.DMP`, overwritten at each crash), name the candidates and say
     the file holds one of them, never which. A bugcheck with a `dump_path`
     and `dump` `null` whose path is not in `files`: when `dumps.status` is
     `read` or `empty` and `dump_path_listed` is `true`, its dump is gone
     (deleted or overwritten); say so. With `dump_path_listed` `false` the
     dump lies outside the places the inventory lists (the dump settings
     changed since): say only that it was not looked for there. With
     `dump_path_listed` `null`, say it could not be checked.
     When `dumps.status` is `unreadable`, `files` may be incomplete: say
     only that it could not be checked whether the dump still exists, with
     the `reason`. Never link a dump to a crash by time.
   - To keep a dump, recommend archiving it: a `change` with the fields from
     `references/summary-contract.md` (permissions administrator; rollback:
     the copy stays, deleting the original is irreversible) and the
     paste-ready block from `SKILL.md`. Deleting originals is only offered
     when the user asked for it.
   - `status` `empty`: read, no dumps (✅). `unreadable`: give the `reason`,
     no conclusion.

10. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail g41 b3 -->
   ```

   Without this line only the summary backs the numbers. A named id that is
   not in the detail file fails the check.

11. Not checked, always last. Its marker stands directly before (or right
   after) the section heading. The check only confirms that some heading has
   the marker next to it; placing it on this section is up to you:

   ```
   <!-- ush:not-checked -->
   ## Not checked
   ```

   It lists every `not_checked` item with its `what` and `reason` (and
   `from` / `to` for a time gap). If `not_checked` is `[]`, it says
   "nothing". It also names every `unreadable` source.

## Degradation cases

Never report missing data as "clean":

- A source with `status` `unreadable`: that log or pass could not be read;
  give the `reason` and draw no conclusion for it.
- A source with `status` `empty`: read, and nothing matched - a finding
  (✅), but see the next point.
- `coverage_start` set (later than `window.start`): the log covers only the
  time from that date (it was cleared or overwritten). Write "from <date>",
  never "clean for the whole window". If it equals `window.end`, the log
  holds no records at all.
- `boots` is `null`: the boot sessions are unknown (the boot pass could not
  be read), not "no boots"; anomalies have no session.
- `reliability.status` `unreadable` (`daily` `null`) or `reliability_records`
  `null`: the Reliability Monitor part could not be read; give the reason,
  never "stable". `status` `empty` or `daily` `[]`: read, nothing recorded
  in the window - the collection may be off or cleared (🔍), never ✅.
- `dumps.status` `unreadable`: the dump settings or folder could not be
  read; give the `reason`, never "no dumps". A file with `readable: false`
  exists; never report it as missing or as fine.
- `truncated` > 0: say how many groups were left out of the summary (the
  rarest) and that the detail file has them; fetch one with `--detail` if it
  matters.
- No baseline (skills that compare with one): "no baseline yet", never "no
  changes". Does not arise in `ush-events`, which keeps no baseline.

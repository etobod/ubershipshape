# Report format (ush-events)

The report is Markdown in the language the user addressed the skill in. It is
saved as `ush-data/reports/events-<YYYY-MM-DD-HHMM>.md` and checked with
`scripts/check_report.py`. The markers below are HTML comments: they do not
depend on the report language and do not show in a preview. Each marker
stands on its own line.

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
- Ignored: list and heading numbering at the start of a line (`1. `, `12) `,
  `## 2. `), the row number in the first cell of a table row (`| 3 | ...`;
  start every table row with `|`, or its row number is checked),
  and the marker lines (`ush:summary`, `ush:detail`, `ush:not-checked`).
  Therefore never put a count in the first cell of a table row.
- Fenced code blocks (the paste-ready commands of a `change`) are not
  checked: a command needs its own constants. Never put a finding's number
  in a code block. Markers inside a code block do not count, and a block
  left open fails the check.
- Every other number is checked, in text, tables and quotes.
  Do not add up, average or convert numbers yourself; do not convert times to
  another time zone (the JSON times are UTC; write them as UTC or say so).

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

   | # | Finding | Count | Action |
   |---|---|---|---|
   | 1 | Bugcheck 0x0000019c | 1 | 🔧 see below |
   | 2 | Kernel-Power 41 | 3 | 🔍 run again later |

   `#` is the section number of the finding, `Count` a count from the JSON,
   `Action` a legend symbol and a few words (no numbers of your own). A row
   that covers several groups gives each group's count with its id
   (`g6: 11, g22: 2`), never one group's count for all of them.

4. Legend, under the dashboard:

   - 🔧 change - a fault the user can fix; the section gives the steps.
   - 🔍 observe or check - not clear yet; watch it, run again later, or
     check one more thing (including `consult_service`).
   - ✅ fine - read and nothing wrong (a source read with no events, noise).
   - ❌ problem found - a fault with no fix the user can apply themselves
     (for example failing hardware); the section says who can help.

5. One section per finding (`## 1. <name>`), most important first:
   - what happened, with the numbers and times from the JSON and the ids
     (`g3`, `a1`);
   - a quoted sample from the group's `sample` (a `>` block, shortened if
     needed);
   - the judgement, and a recommendation with `weight`, `kind`, `risk`,
     `evidence`, `permissions` and `rollback`
     (`references/summary-contract.md`). A `change` gives a paste-ready block
     and how to read the value back afterwards.

6. Known noise, a separate section: one line per noise item with its
   provider, Id, `count` and `reason`. Noise is not a finding and is not
   hidden.

7. Boot sessions: how many, which ended without a clean shutdown
   (`clean_shutdown` false), and which anomalies fall into which session.

8. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail g41 b3 -->
   ```

   Without this line only the summary backs the numbers. A named id that is
   not in the detail file fails the check.

9. Not checked, always last. Its marker stands directly before (or right
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
- `truncated` > 0: say how many groups were left out of the summary (the
  rarest) and that the detail file has them; fetch one with `--detail` if it
  matters.
- No baseline (skills that compare with one): "no baseline yet", never "no
  changes". Does not arise in `ush-events`, which keeps no baseline.

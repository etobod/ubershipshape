# Report format (ush-processes)

The report is Markdown in the language the user addressed the skill in. It is
saved as `<data dir>/reports/processes-<YYYY-MM-DD-HHMM>.md` (local time of
the run) and checked with
`python -B skills/ush-common/scripts/check_report.py <report>` (or
`--latest --skill ush-processes` for the newest `processes-*.md`), which
reads the ush-processes rules from `data/report-profile.json`.
`<data dir>` is the data directory (`--data-dir`, else `USH_DATA_DIR`, else
`%LOCALAPPDATA%\ubershipshape`); its absolute value is the directory above
`work/` in the summary's `summary_file`. The report text outside code blocks
writes it as `&lt;data dir>` in plain text, never in inline code (a `<`
before a letter fails the check, and inline code shows `&lt;` as it is), and
never the expanded path: it contains the account name, which a report must
not carry. The expanded path appears only in the `ush:summary` marker and
as the `--data-dir` value of a block for an elevated shell (`SKILL.md`: an
elevated shell of another account has a different `%LOCALAPPDATA%`). A
`not_checked` reason or `inventory.reason` that names a path inside the
data directory (the ush-inventory baseline in `state`) is written with
`&lt;data dir>` in place of the data directory; this rule comes before
"Account names".

The markers below are HTML comments: they do not depend on the report
language and do not show in a preview. Each marker stands on its own line,
outside quotes and lists; no other HTML comment is allowed. This file stays
in English; the report translates every heading and label, the table header
included.

## Numbers

Every number in the report comes from the summary JSON, or from a detail item
fetched with `--detail <id>` and named in an `ush:detail` line. The checker is
shared by all skills (see `skills/ush-health/references/report-format.md`,
"Numbers", for the full list); in short:

- Every run of digits is a separate number: `2026-05-07` is 2026, 5 and 7,
  `1500.0` is 1500 and 0. Write a number exactly as the JSON has it, counts
  without a thousands separator.
- Memory is written only from the `_gb` fields of `memory` and the `_mb`
  fields of groups and processes, as the JSON has them (`1500.0`, not
  `1.5 GB`). Never convert bytes, never add groups up, never compute a
  percentage.
- Names back their own digits: a group's `name` and `path`, a port's
  `process` and `local_address`, a service's `name` and `display_name`, a
  program's `name`, an autostart `key`, and the other text values of the
  summary. Only `summary_file` and `detail_file` back no number (the
  profile's `path_keys`); a path from them may appear only in the
  `ush:summary` marker or a fenced code block.
- Item ids (`g1`, `p2`) are not numbers when they name an item of the
  summary, an item named in `ush:detail` or a group cut from the summary
  (`truncated`). A port's `group` is an id, never a number (the profile's
  `id_keys`). A word of that shape that is no such id is checked as a
  number.
- No numbered lists: use `-` bullets. A numbered heading (`## 2. Programs`)
  is fine when the numbering of its level counts from 1 in order. The first
  cell of a table row is ignored when it equals the row's position among the
  table's data rows, so never put a count there.
- Fenced code blocks are not checked: never put a finding's number in one.
- No HTML and no links outside code blocks: write a literal `<` as `&lt;`
  and a literal `]` before `(` or `:` as `&rsqb;`.

## Items the report must name

Every `groups[*].id` and `ports[*].id` of the summary appears in a visible
line of the report, as a word of its own (`g12` does not name `g1`). Several
ids on one line are fine (`g14, g15, g16: small helpers of ...`). A mention
inside a fenced code block or on a marker line does not count. The check
lists each missing id as `not named in the report: <id> (<list>)` and fails.
Groups cut from the summary (`truncated`), items fetched with `--detail`
and the `udp_bound` items (they have no id) are not required.

## Layout

1. First line, exactly:

   ```
   <!-- ush:summary <absolute summary_file path> -->
   ```

   Then the title with the time of the snapshot (`generated_at`, UTC: write
   it as UTC or say so; `inventory.created_at` carries its own zone), and one
   line: that it is a snapshot of that moment, and whether the run was
   elevated (`elevated`). Without elevation say that paths, command lines
   and owners of other accounts' and system processes were not read, with
   `counts.path_unread`, `counts.command_line_unread` and
   `counts.owner_unread`.

2. Memory in total, from `memory`: used, total and available (`used_gb`,
   `total_gb`, `available_gb`), commit when it matters (`commit_used_gb` of
   `commit_total_gb`), the number of processes and groups
   (`counts.processes`, `counts.groups`), and how much the listed groups
   hold (`listed_private_gb`: only the groups in the summary, so with
   `truncated` > 0 say that it covers the listed groups only).

3. Programs, one table with a row per group of the summary, in the
   summary's order:

   | # | Program | Processes | Memory (MB) | Started by |
   |---|---------|-----------|-------------|------------|
   | 1 | g1 browser.exe | 2 | 1000.0 | autostart |
   | 2 | g2 host.exe | 1 | 250.0 | service |

   `Program` is the id and `name` (and `program.name` when known),
   `Processes` is `count`, `Memory (MB)` is `memory_private_mb`. When
   `sorted_by` is `working_set_bytes`, the column is `working_set_mb`, and
   the header and one line under the table say that this is the working set,
   not private memory (see "Degradation cases"). `Started by` is
   `started_by` in words; `null` is "not read", never "unknown". A `null`
   memory value is "not read" in its cell. When `memory_unread_count` > 0,
   the memory is the sum of the processes that were read: mark the cell
   (e.g. "120 (2 not read)" with the real numbers) so a partial sum is not
   shown as the whole.

   When `truncated` > 0, one line under the table: how many groups were cut
   and their ids ("3 more groups were cut from the summary: g3, g4, g5."
   with the real ids), and that the detail file has them.

4. Groups worth a word: for each group you have something to say about
   (the largest ones, a group without a reason to run you can name, an
   unsigned or missing file, a group behind a port), one bullet with its id:
   what the program is (`program`, `company`, `signer`,
   `signature_status`), why it runs (`started_by` and its facts: `services`
   with their `name` and `start_mode`; the summary lists at most 15, so give
   `services_count` as the number of services and say when the list is
   shorter than it; `autostart` keys, `parents`,
   `parent_gone_count`), and whose account runs it in words ("your
   account", "the system account", "another account"), never the account
   name from `owners` (see "Account names"). A group whose
   `name` ends with `(path not read)` has an unread path, not a missing
   file; a pseudo-process group (`path_kind` `"none"`) has no file at all.
   The kernel starts it: `Registry`, `Memory Compression` and `Secure
   System` have `System` as their parent, and `System` and `System Idle
   Process` have no parent process at all. When `services` and the
   ush-inventory baseline and `launchers.json` were read, that gives
   `started_by` `parent` and `unknown`; otherwise `started_by` is `null` (not read) like any group's. Never present a pseudo-process as a
   program of unknown origin.
   A command line fetched with `--detail` is given as the program name and
   at most the argument that matters, never in full; a path in that
   argument follows "Account names". Every group not
   described here is still named in the table.

5. TCP ports, one bullet per item of `ports`, in the summary's order: id,
   `process` and its `group` id, `local_port`, and `scope` in words (`all`:
   on all addresses; `address`: on one address of the machine; `loopback`:
   local only) with `local_address`. For a port whose `group_in_summary` is
   `false`, say that its group was cut from the summary (`group_in_summary`
   is `null` exactly when `group` is `null`). A port with `group`
   `null` belongs to a process that was not in the process list (it ended or
   started between the jobs). A port on `all` is not a finding by itself:
   say what stands behind it.

6. UDP sockets, a short section from `udp_bound`: per group (or `process`
   when `group` is `null`) and `scope`, the `count` of bound UDP sockets.
   Never call them listening: they include client sockets. When
   `counts.udp_bound_outside_summary` is not 0, say that that many belong to
   groups cut from the summary. `counts.udp_port_zero` endpoints on port 0
   were left out; give that number when it is not 0.

7. Inventory, the ush-inventory list the links come from. With
   `inventory.status` `read`: "Links come from the ush-inventory baseline of
   <created_at date>, <age_days> days old.", plus `missing_sources` and
   `entries_without_path` when they are not empty or 0. Otherwise see
   "Degradation cases".

8. Recommendations, where you have any: each with `weight`, `kind`, `risk`,
   `evidence` (ids and values from the JSON), `permissions` and `rollback`
   (`skills/ush-common/references/summary-contract.md`,
   "Recommendations"). To end or turn off something, point to
   `ush-inventory` with the entry's key (`autostart[].key` or
   `services[].key`); give no block of your own.

9. Items fetched with `--detail`: name every id you used, on one or more
   lines anywhere in the report:

   ```
   <!-- ush:detail g3 p1 -->
   ```

   A named id that is not in the detail file fails the check.

10. Not checked, always last. Its marker stands directly before (or right
    after) the section heading:

    ```
    <!-- ush:not-checked -->
    ## Not checked
    ```

    It lists every `not_checked` item with its `what` and `reason`, and
    names every `unreadable` source. When `elevated` is `false` it also
    names what was not read for lack of administrator rights, with
    `counts.path_unread`, `counts.command_line_unread` and
    `counts.owner_unread`: the summary has no `not_checked` item for them,
    since the source stays `read` and the fields are only in
    `unread_fields`. If `not_checked` is `[]` and nothing else is
    missing, it says "nothing".

## Account names

A report never carries the account name, except in the data directory path
where the section above allows it (the `ush:summary` marker, which the
checker needs, and the `--data-dir` of an elevated-shell block). A group's
`path`, a process's `path` and `command_line` from `--detail`,
`inventory.reason` and the reason of a `not_checked` item (outside the data
directory, see above) often start with the profile folder, `C:\Users\` followed by the
account name: write that folder as `%USERPROFILE%`
(`%USERPROFILE%\AppData\Local\...`). `owners` holds `domain\user` names:
say "your account", "the system account" or "another account", never the
name itself.

## Values that are not readings

- `null` is "not read" (or "unknown" in the plain sense), in words, never
  "no", "none" or "0". For `started_by`, `null` is always "not read":
  `unknown` there is a real value, not missing data.
- A field in `unread_fields` is unknown in this run; never judge from it.
- `path_kind` `"none"`: a pseudo-process without an image file, even for an
  administrator. Its `null` path is not unread.
- `program` `null` without `program` in `unread_fields`: no installed
  program's folder contains the file and no linked autostart entry names a
  program. `program.name` `null`: the key is not in the ush-inventory list.
- `exists` `false`, a `signature_status` other than `Valid` or `signer`
  `null` is a fact, not a verdict: say what it is, then judge.
- `autostart` `[]` is "no autostart entry found for this path"; `null` is
  "not read". A launcher target (`rundll32.exe`, `cmd.exe`) is never
  matched, so a launcher group has `[]` even when an entry runs it.
- `parent_gone_count` > 0: the parent has ended or its pid was reused; not
  suspicious by itself.

## Degradation cases

Never report missing data as "none" or "nothing there":

- A failed `processes` job (source `processes` `unreadable`): there are no
  processes and no groups because nothing was read, not because nothing
  runs. Every count is 0 for that reason; do not give `counts.processes`,
  `counts.groups` or the unread counts as readings, and write no Programs
  table: say the process list could not be read and give the `not_checked`
  reason.
- No ush-inventory list (`inventory.status` `none`): `autostart` is "not
  read", and so is `started_by` of every group without a service; recommend
  running `ush-inventory` first. An elevated run reads only the elevated
  list; say so when `elevated` is `true`.
- An unreadable list (`inventory.status` `unreadable`): give `reason`, with
  the profile folder as `%USERPROFILE%` (see "Account names"); the rest as
  above.
- An unreadable launcher list (a `not_checked` item about `launchers.json`):
  `autostart` and the `started_by` of every group without a service are
  "not read", as with no ush-inventory list.
- An incomplete list (`missing_sources` not empty, `entries_without_path`
  not 0): a group without an autostart link may still have one.
- An old list: give `age_days` and suggest a new `ush-inventory` run when
  entries may have changed since.
- No administrator rights: many processes have `path`, `command_line` and
  `owner` not read, and their groups are named `<name> (path not read)`.
  Give the counts and offer an elevated run (`SKILL.md`, step 7); never
  write that these processes have no file.
- `perf` not read (`sorted_by` `working_set_bytes`): private memory is not
  known; the table uses `working_set_mb` and says that it is the working set
  (shared pages count in every process), and `listed_private_gb` is
  unknown.
- `memory` not read: the totals are unknown; the groups are still listed.
- `services` not read: `services` and `started_by` of every group are "not
  read"; never say that a group hosts no service.
- `file_facts` not read, or an item `file_facts files`: `exists`, the
  signature and the company of those groups are unknown, and `program` may
  be "not read".
- `tcp_listeners` or `udp_endpoints` `unreadable`: that protocol was not
  read; the other one is reported normally. `empty` is a finding: nothing
  listens on TCP, or no UDP socket is bound.
- Groups cut (`truncated` > 0) or ports cut (an item `ports cut from the
  summary`): give the numbers and say that the detail file has them.

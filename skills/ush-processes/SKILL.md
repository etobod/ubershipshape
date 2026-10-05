---
name: ush-processes
description: Show what uses the memory of this Windows machine right now, grouped by program (all processes of one executable together, largest first), why each group runs and who started it (the services it hosts, the autostart entry, task or service from the ush-inventory list, its parent processes, the program it belongs to, its signature and account), and which processes listen on TCP ports, local only or on all addresses, with the UDP sockets bound per process. Use when the user asks what eats the memory, why something is running, who started a process, or what listens on the network. A snapshot of the moment, read-only; it changes nothing and gives no change blocks.
---

# ush-processes

Reads the running processes, their memory, owners and parents, the services
they host, the file facts of their executables and the TCP listeners and UDP
endpoints through read-only PowerShell jobs, and links each group of
processes to the autostart list that `ush-inventory` saved last. A script
counts and matches; you judge and write a Markdown report; the user decides
what to act on. It is a snapshot of one moment: there is no baseline and no
comparison with an earlier run.

## When to use

- The user asks what eats the memory, which program uses the most, or why
  the machine is short of memory now.
- The user asks why a program or process is running, or who started it (a
  service, an autostart entry, a task, another process).
- The user asks what listens on the network, which process holds a port,
  or whether a port is open to other machines or local only.

Not for: turning an autostart entry, task or service off (`ush-inventory`
gives the blocks; its `--block` and its report are the place for it),
settings (`ush-settings`), the event logs (`ush-events`), the health of
disks, devices and updates (`ush-health`), ending a process, CPU use over
time, memory leaks or outgoing connections. Say so if the user asks for
these.

## Rules

- **Read-only, no change blocks.** `processes.py` changes nothing on the
  machine, writes to `<data dir>/work/` and, in `state/`, only its id map
  `ush-processes.ids.json`; it reads the ush-inventory baseline there. The report gives no block that ends a
  process, stops a service or turns autostart off.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a process, a port or a file.
- **Read only the summary JSON.** Never open the raw captures or other files
  in `<data dir>/work/`. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the script writes:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  `%LOCALAPPDATA%\ubershipshape`. Take its absolute value from the summary's
  `summary_file` (the directory above `work/`). In the report text outside
  code blocks write it as `&lt;data dir>` in plain text, never in inline
  code, and never the expanded path: it contains the account name, which a
  report must not carry (`references/report-format.md`). The `not_checked`
  reason of the ush-inventory baseline names the expanded `state` folder:
  write it as `&lt;data dir>` too.
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. Do not count processes or ports, add up
  memory or compute an age yourself.
- **Memory only from the `_gb`, `_mb` and `_percent` fields.** Write
  `memory.*_gb`, `memory.used_percent`, `memory.commit_used_percent` and the
  groups' `memory_private_mb` (or `working_set_mb`, see `sorted_by`) as the
  JSON has them; never convert bytes, never compute a percent, never add
  groups up.
- **`unread_fields` means "not read", never "none".** A field named there is
  unknown in this run: `path` `null` with `path` in `unread_fields` is a path
  Windows did not give this account, not a process without a file.
  `path_kind` `"none"` is different: a pseudo-process without an image file
  (the idle process, `System`, `Registry`, `Memory Compression`), not a
  missing right.
- **`started_by` is a fact from the sources, not a judgement.** It names the
  first rule that holds (`service`, `autostart`, `parent`, `unknown`); the
  full facts are next to it. `started_by` `null` with `started_by` in
  `unread_fields` is "not read" (an input of the rule was not read), never
  "unknown"; `unknown` is only the value `"unknown"`.
- **A port on all addresses is not a problem by definition.** `scope`
  `all` says the port accepts connections on every address of the machine
  (the firewall still decides); say what stands behind it (the process, its
  group, program, service and signature), then judge.
- **UDP sockets are not listeners.** `udp_bound` counts bound UDP sockets
  per group and scope; they include client sockets (DNS, QUIC). Never write
  that a process "listens" on UDP.
- **No full command line in the report.** Command lines are only in the
  detail file and may hold tokens or profile paths: write at most the
  program name and the one argument that matters.
- **Recommendations.** A recommendation to end or turn off something points
  to `ush-inventory` with the entry's key (from `autostart[].key` or
  `services[].key`) and carries `weight`, `kind`, `risk`, `evidence`,
  `permissions` and `rollback` as defined in the shared contract
  `skills/ush-common/references/summary-contract.md` ("Recommendations").
- **Empty is not unreadable.** A source with `status` `unreadable`, a field
  in `unread_fields`, `inventory.status` other than `read`, or `truncated`
  > 0 must be reported as such (see the degradation cases in
  `references/report-format.md`), never as "none" or "nothing there".

## Steps

1. From the project root run, in a normal (non-elevated) shell:

   ```
   python -B skills/ush-processes/scripts/processes.py
   ```

   It prints the summary JSON on stdout and writes it, with a detail file, to
   `<data dir>/work/`. The field meanings are in
   `references/summary-contract.md`. The links to autostart entries come from
   the ush-inventory baseline: when `inventory.status` is not `read`, or
   `inventory.age_days` is large, suggest running `ush-inventory` first.

2. Read the summary. For a group you need to understand (its processes, their
   parents, owners and command lines, or services beyond the first 15) or a
   port, fetch the item:

   ```
   python -B skills/ush-processes/scripts/processes.py --detail <id> --detail-file <detail_file>
   ```

   `<detail_file>` is the summary's `detail_file`, so the item comes from the
   same run as the summary. Ids: `g..` groups (stable between runs, not
   places in the list), `p..` TCP ports. Remember every id you fetched and
   used.

   The id of a group or port cut from the summary (`truncated`, or a
   `ports cut from the summary` item) cannot be guessed. Find the cut items
   with:

   ```
   python -B skills/ush-processes/scripts/processes.py --cut --detail-file <detail_file>
   ```

   It prints `cut`, a list of `{id, list, name}`, and starts no machine job.
   Fetch a cut item with `--detail` before you name it in the report.

3. Judge the findings: which groups hold the memory and why they run, which
   group runs without a reason you can name, which listening ports stand
   behind which program and whether that is expected. Weigh them with the
   scale of the shared contract (`high`, `medium`, `low`). The script sets no
   threshold: the judgement is yours.

4. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/processes-<YYYY-MM-DD-HHMM>.md` (local time of the
   run). The first line is `<!-- ush:summary <summary_file> -->` with the
   absolute `summary_file` path from the summary.

5. After saving, run:

   ```
   python -B skills/ush-common/scripts/check_report.py "<absolute data dir>/reports/processes-<YYYY-MM-DD-HHMM>.md"
   ```

   (`--latest --skill ush-processes` checks the newest `processes-*.md`
   instead.) The checker is shared by all skills; it reads the ush-processes
   rules from `data/report-profile.json`. It fails on a number not backed by
   the JSON and on a group or port of the summary not named in the report.
   Correct the report and run the check again until it prints `OK`. `OK`
   means each number occurs somewhere in the JSON, not that it is used for
   the right thing, so the rules above still bind you. Do not hand the
   report to the user before it prints `OK`.

6. Tell the user where the report is and give the main findings in a few
   lines.

7. Only when `elevated` is `false`: you may say that a run with
   administrator rights reads more (paths, command lines and owners of the
   processes of other accounts and of the system). It is not required; do
   not run it yourself.

   ```
   # Runs the same read-only process snapshot with administrator rights. It
   # changes nothing on the machine and writes only to <data dir>\work\ and
   # its id map in <data dir>\state\.
   Set-Location "<absolute project root>"
   python -B skills/ush-processes/scripts/processes.py --data-dir "<absolute data dir>"
   ```

   Say that an elevated run links groups only to the elevated ush-inventory
   baseline (`ush-inventory.elevated.json`); without one its `inventory.status`
   is `none`. After the user says it ran, read the newest
   `<data dir>/work/processes-*.summary.json`, whose `elevated` must be
   `true` (otherwise say that the block did not run elevated), and write a
   new report from that one summary, as in steps 3-5. Never merge two
   summaries into one report.

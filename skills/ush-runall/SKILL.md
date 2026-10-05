---
name: ush-runall
description: Run every measuring script of the ush-* skills on this Windows machine one after another (health, events, settings, inventory, processes, files, advice) and write one combined report - one list of recommendations by weight with the source of each, the links between findings of different skills, the contradicting findings side by side, the active inbound firewall rules set against the programs that really listen on TCP ports and the network category, and one block to run the whole pass with administrator rights when that reads more. Use when the user asks for a full check-up, "check everything", one report for the whole machine, or how the machine is doing overall. Read-only; it changes nothing on the machine.
---

# ush-runall

Runs the measuring script of each skill in `data/children.json` in turn,
each with only `--data-dir`, and summarises the pass: one item `h1`...`h7`
per child (status, duration, its `not_checked` count, `truncated`,
`elevated`), whose full summary is in the detail file. After the children it
sets the active inbound Allow firewall rules of `ush-inventory` against the
TCP listening ports of `ush-processes` (items `w1`...). A script runs and
counts; you read the children one at a time, judge and write one Markdown
report; the user decides what to act on.

## When to use

- The user asks for a full check-up of the machine, "check everything", or
  one report for the whole machine.
- The user asks how the machine is doing overall, or what to fix first
  across all areas.
- The user asks whether a firewall rule lets something in that really
  listens, or which open rules match listening programs.

Not for: one area only (run that skill: `ush-health`, `ush-events`,
`ush-settings`, `ush-inventory`, `ush-processes`, `ush-files`), the web
search of `ush-advice` (`runall` runs `advice.py` without findings, so it
gives the machine facts only; the search is a separate `ush-advice` run),
exporting or clearing event logs or copying dumps (`ush-events`'
`logs.py` and `dumps.py` change the disk or a log and are never run here),
or running anything on a schedule. Say so if the user asks for these.

## Rules

- **Read-only, no flag is passed on.** `runall.py` gives each child only
  `--data-dir` and never any other flag (`--block`, `--export`, `--detail`,
  `--days`, `--findings`, `--cut`, `--compare-to`, ...), so every child runs read-only. It never
  runs `logs.py` or `dumps.py`. It writes only to `<data dir>/work/`; the
  children write their own files and baselines to `<data dir>` as in a run
  of their own. Any block in the report is for the user to paste into their
  own shell (an elevated one where the child's rules say so); never run a
  block yourself.
- **No identifiers from the h items.** The child summaries carry the
  computer name, account names, SIDs, serial numbers and device instance
  ids, MAC addresses and private network addresses (also inside quoted
  event samples). Never quote them; see "Identifiers" in
  `references/report-format.md`.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a finding.
- **Read the h items one at a time.** Fetch `h1`, reduce it to its findings
  (ids, the numbers you will cite, its `not_checked` entries, its changes)
  in a short note, and only then fetch `h2`, and so on to `h7`, in order.
  Each item holds a full child summary: up to 35 000 characters as compact
  JSON, and more as `--detail` prints it indented, which can pass the
  output limit of the shell tool. When the output is cut or saved to a file,
  read the whole item (from that file, in parts) before you cite anything
  from it. Never keep two raw child summaries in view at once.
- **No --detail of a child script.** In this report use only the `h` items
  of the `runall` detail file (`runall.py --detail h<n> --detail-file
  <detail_file>`), never a child's own `--detail`: the numbers of a child's
  detail file have no backing in the `runall` report. Do not run a child
  script for a measurement either: it would write a new summary and new
  baselines that are not part of this pass.
- **Summaries meet only through `ush:detail`.** Never paste or merge child
  summaries into one file of your own. A child's number backs the report
  only when its `h` item is named in the report's
  `<!-- ush:detail h... -->` line; name every `h` item whose numbers or
  child ids you cite there.
- **The data directory.** `<data dir>` below is where the scripts write:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  `%LOCALAPPDATA%\ubershipshape`. Take its absolute value from the
  summary's `summary_file` (the directory above `work/`). In the report text
  outside code blocks write it as `&lt;data dir>` in plain text, never in
  inline code, and never the expanded path: it contains the account name,
  which a report must not carry (`references/report-format.md`).
- **Every number in the report comes from the JSON**: from the `runall`
  summary, or from an `h` item named in `ush:detail`. Each child's own rules
  for its numbers still hold (its `SKILL.md` and
  `references/report-format.md`): sizes only from the `_gb` fields of
  `ush-files`, memory only from the `_gb`, `_mb` and `_percent` fields of
  `ush-processes`, and so on. Never add children's numbers up.
- **Cite a child's item with its skill.** Write `ush-inventory s11`, never a
  bare `s11`: the letters of the children overlap (`g` is a group in
  `ush-events` and in `ush-processes`). An item a child cut from its own
  summary (its `truncated` counts) is given as a number of items, never by
  an id: its digits have no backing. The one exception is the rule of a
  `firewall_ports` item (`ush-inventory x<n>` in its `rule`): the `runall`
  summary backs it, so cite it even when the rule is not in `h4`; never
  fetch it with the inventory's `--detail`.
- **Name every h item.** The report text names each of `h1` to `h7` with its
  skill and status (`required_lists`); an id on the `ush:detail` line does
  not count.
- **One list of recommendations by weight.** `high` first, then `medium`,
  then `low`, each with the fields of
  `skills/ush-common/references/summary-contract.md` ("Recommendations")
  and its source as `ush-<skill> <id>` (several sources when it rests on
  several findings). The weights are yours; the script sets none.
- **Contradictions side by side.** When two children say different things
  about the same thing (a setting on in one and off in another, a driver
  updated in one and failing in another), put both findings next to each
  other with their sources and do not decide between them.
- **Links between skills.** Findings of different children about the same
  device, driver, setting or time (for example a graphics crash after
  resume in `ush-events`, a power setting in `ush-settings` and the display
  driver in `ush-inventory`) go into one entry with every source. The weight
  of a recommendation may come from the strongest linked finding; then the
  report says why. Without a real link (the same name, id, path or time in
  the JSON) the report does not invent one.
- **Firewall rules as facts.** Describe each `firewall_ports` item by facts:
  the program listens only on the loopback address (`loopback_only` `true`)
  or on other addresses too, and the rule's `profile` set against
  `network_categories` (`Domain` in a rule is `DomainAuthenticated` in a
  network category; a `profile` of `null` means every profile). The rules
  counted `not_listening`, `not_compared`, `udp` and `other_protocol` are
  given only as counts, never one by one. With `truncated` above 0 give how
  many items were cut.
- **One elevated block for the whole pass.** When a child has `elevated`
  `false` and `not_checked` entries that need administrator rights, the
  report gives one block for an elevated shell that runs `runall.py` with
  `--data-dir` (the absolute path, step 9), never the elevated re-run
  blocks of the single skills. The change blocks of step 5 keep their
  elevated parts.
- **All changes are in this report.** The pass has already updated the
  baselines of the children (`ush-inventory`, `ush-settings`, `ush-health`,
  `ush-files`, `ush-advice`), so a later run of a single skill will not show
  these changes again: report every change of every child here.
- **A success message is not verification.** After the user ran a block,
  a new run reads the values back.

## Steps

1. From the project root run, in a normal (non-elevated) shell:

   ```
   python -B skills/ush-runall/scripts/runall.py
   ```

   It runs seven scripts one after another, which takes minutes and can
   take longer than a shell tool allows (each child has its own time limit
   in `data/children.json`). Run it in the background, or with the longest
   timeout the tool allows, and wait until it exits: it writes its summary
   and detail file only at the end, while each finished child has already
   moved its baseline, so a pass stopped from outside loses those changes. A child that fails,
   times out or prints no valid summary does not stop the pass; it gets its
   status and a `not_checked` entry. The summary JSON goes to stdout and,
   with a detail file, to `<data dir>/work/`. The field meanings are in
   `references/summary-contract.md`.

2. Read the summary: `children` (status of each child), `counts`,
   `firewall_ports`, `firewall_ports_counts`, `network_categories`,
   `truncated` and `not_checked`.

3. For each child with status `ok`, in order from `h1` to `h7`, fetch its
   item:

   ```
   python -B skills/ush-runall/scripts/runall.py --detail h1 --detail-file <detail_file>
   ```

   `<detail_file>` is the `runall` summary's `detail_file`; `--detail` runs
   no child. Read the child's `summary` with that skill's
   `references/summary-contract.md`, write your short note of its findings,
   and only then fetch the next item. A child with another status has
   `summary` `null`: there is nothing to fetch. A `firewall_ports` item cut
   from the summary is fetched the same way (`--detail w51`).

4. Judge the findings across the children: weigh them with the scale of the
   shared contract (`high`, `medium`, `low`), link the findings about the
   same thing, set contradicting findings side by side, and read the
   firewall items against the network categories. The script sets no
   threshold: the judgement is yours.

5. For a recommendation that needs a change block, follow the `SKILL.md` of
   the child it comes from (for example `settings.py --block <id>
   --detail-file <the child's detail_file>` or `files.py --block <id>`,
   which only print), and copy the block word for word into a fenced code
   block with its shell, risk and rollback. When the command exits with an
   error or prints no block for that id, give no block: write the child's
   manual step in words, or say that no block could be printed and give the
   error line. Never write a change block yourself.

6. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/runall-<YYYY-MM-DD-HHMM>.md` (local time of the run).
   The first line is `<!-- ush:summary <summary_file> -->` with the absolute
   `summary_file` path of the `runall` summary. Write no separate report per
   skill for this pass.

7. After saving, run:

   ```
   python -B skills/ush-common/scripts/check_report.py "<absolute data dir>/reports/runall-<YYYY-MM-DD-HHMM>.md"
   ```

   (`--latest --skill ush-runall` checks the newest `runall-*.md` instead.)
   It fails on a number backed neither by the `runall` summary nor by an `h`
   item named in `ush:detail`, and on an `h` or `w` item of the summary not
   named in the report. Correct the report and run the check again until it
   prints `OK`. `OK` means each number occurs somewhere in that JSON, not
   that it is used for the right thing (a child's id or path can back a
   made-up number), so the rules above still bind you. Do not hand the
   report to the user before it prints `OK`.

8. Tell the user where the report is and give the main findings in a few
   lines.

9. Only when a child has `elevated` `false` and `not_checked` entries that
   need administrator rights: give one block for an elevated PowerShell that
   runs the whole pass. It is not required; do not run it yourself.

   ```
   # Runs the same read-only pass with administrator rights. It changes
   # nothing on the machine and writes only to <data dir>\work\ and the
   # baselines of the skills in <data dir>\state\.
   Set-Location "<absolute project root>"
   python -B skills/ush-runall/scripts/runall.py --data-dir "<absolute data dir>"
   ```

   Children with an elevated baseline compare an elevated run only with
   it, so their first elevated run has no comparison. After the user says
   it ran, read the newest `<data dir>/work/runall-*.summary.json`, check
   that the children that report `elevated` have it `true` (otherwise say
   that the block did not run elevated), and write a new report from that
   one pass, as in steps 2-7. Never merge two passes into one report.

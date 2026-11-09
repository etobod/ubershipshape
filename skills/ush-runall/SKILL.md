---
name: ush-runall
description: Run every measuring script of the ush-* skills on this Windows machine one after another (health, events, settings, inventory, processes, files, advice, packages) and write one combined report - one list of recommendations by weight with the source of each, the links between findings of different skills, the contradicting findings side by side, the active inbound firewall rules set against the programs that really listen on TCP ports and the network category, and one block to run the whole pass with administrator rights when that reads more. Use when the user asks for a full check-up, "check everything", one report for the whole machine, or how the machine is doing overall. Read-only; it changes nothing on the machine.
---

# ush-runall

Runs the measuring script of each skill in `data/children.json` in turn,
each with only `--data-dir`, and summarises the pass: one item `h1`...`h8`
per child (status, duration, its `not_checked` count, `truncated`,
`elevated`), whose full summary is in the detail file. After the children it
sets the active inbound Allow firewall rules of `ush-inventory` against the
TCP listening ports of `ush-processes` (items `w1`...), and links each
pending driver update of `ush-health` to a driver package of
`ush-inventory` that no present device uses (state `non_present` or
`no_device_found`) when the provider and the driver class are the same or
paired by `data/driver-link-aliases.json` (items `y1`...). A script runs and
counts; you read the children one at a time, judge and write one Markdown
report; the user decides what to act on.

## Plugin paths

- Plugin root: `${CLAUDE_PLUGIN_ROOT}`
- Data folder: `${CLAUDE_PLUGIN_DATA}`

The references write these two folders as `<plugin root>` and
`<plugin data>`: fill them in from the two lines above. A block for the user
starts with `Set-Location "<absolute plugin root>"`, the plugin root above.

If writing a file to the data folder is refused (a hook or a permission
rule blocks the Write or Edit tool), stop there. Never change a settings file
yourself. Tell the user that nothing was saved and why, and give them one
line to type in this session, without quotes: `/add-dir <data folder>`, the
absolute data folder written with forward slashes. It allows the folder for
this session only, with no settings file edit. To allow it for good, they can
add the same forward-slash path to `permissions.additionalDirectories` in
their user settings `~/.claude/settings.json` (never in a project's `.claude`
folder); that applies from the next session, so after only that change the
skill is run again in a new session. Write the file again with the same tool
only after the user says they ran `/add-dir`. If it is refused again, stop the
skill and tell the user that nothing was saved and why. Never write the file
another way (a shell command, another folder).

## When to use

- The user asks for a full check-up of the machine, "check everything", or
  one report for the whole machine.
- The user asks how the machine is doing overall, or what to fix first
  across all areas.
- The user asks whether a firewall rule lets something in that really
  listens, or which open rules match listening programs.

Not for: one area only (run that skill: `ush-health`, `ush-events`,
`ush-settings`, `ush-inventory`, `ush-processes`, `ush-files`,
`ush-packages`), the web
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
  of their own. Any block (the elevated pass in the report, a change block
  in a repair plan of step 5, never in the chat) is for the user to run in
  their own shell (an elevated one where the child's rules say so),
  delivered in `run-me.ps1` or `run-me-admin.ps1` per
  `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/run-me.md`; never run a block yourself.
- **No identifiers from the h items.** The child summaries carry the
  computer name, account names, SIDs, serial numbers and device instance
  ids, MAC addresses and private network addresses (also inside quoted
  event samples). Never quote them; see "Identifiers" in
  `references/report-format.md`.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a finding.
- **Read the h items one at a time.** Fetch `h1`, reduce it to its findings
  (ids, the numbers you will cite, its `not_checked` entries, its changes)
  in a short note, and only then fetch `h2`, and so on to `h8`, in order.
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
  the plugin data folder (`--default-data-dir`). Take its absolute value from the
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
- **Name every h item.** The report text names each of `h1` to `h8` with its
  skill and status (`required_lists`); an id on the `ush:detail` line does
  not count.
- **One list of recommendations by weight.** `high` first, then `medium`,
  then `low`, each in the two-part layout of rule 4 of
  `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/report-style.md`, with the fields of
  `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/summary-contract.md` ("Recommendations")
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
- **Leftovers are named, the model judges them.** From the `ush-inventory`
  item the report names each of these with its evidence and says whether it
  is worth a look: an autostart entry with a target that exists and whose
  `signature_status` is set and not `Valid` (a `null` status is a missing or
  unchecked file, never a signature finding); every RunOnce value (`kind` `run_once`); every unmatched vendor folder
  (`ush-inventory v..` with `matched` `false`; one with `matched` `null`
  was not judged: name it with its `not_judged` cause, never as a
  leftover). A driver package whose `no_device_by_nature` is `false` and a
  vendor folder with `matched` `false` whose names match in the JSON go into one entry with both sources (the rule "Links
  between skills"). So does each `driver_update_links` item (`y..`): the
  pending driver update `ush-health q<n>` and the package
  `ush-inventory o<n>` it links to: name both sides' provider and class
  (`provider`, `driver_class`, `package_provider`, `package_class`) and the
  package's state (`package_state`) and group (`package_group`). Call
  the two providers the same only when `provider_via` is `equal`, and the
  two classes the same only when `class_via` is `equal`; when one of them is
  `table`, say that a line of `driver-link-aliases.json` paired those two
  names.
- **Driver packages by state and group, no removal.** A driver package of
  `ush-inventory` (`o..`) is named by its `device_state`, never as an orphan
  or "without a device": `non_present` is "known device not present", with
  each device of its `devices` (name, class and `last_removal`, or "no
  removal date" when it is `null`); `no_device_found` is "no device found
  without administrator rights" (Windows may hold a record a normal read
  does not show). The report gives the packages of the `ush-inventory` item
  by `group` (`driver_package_groups`: `count` and `by_state` per group),
  each listed package under its group with its `owner`; a package with
  `no_device_by_nature` `true` (a filter or antivirus package) is owned by
  its program, never a leftover. A state is a fact about this moment, not
  proof that a package is unused or safe to remove. No driver package
  removal is offered or put into a repair plan: `ush-inventory --block
  o<n>` prints only `no block` with the reason, and the report points to
  `ush-inventory` for that reason.
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
- **The changes are summed up in this report.** The pass has already
  updated the baselines of the children (`ush-inventory`, `ush-settings`,
  `ush-health`, `ush-files`, `ush-advice`, `ush-packages`), so a later run
  of a single skill will not show these changes again. The report gives a
  short summary of them (new programs by name, updated programs by name
  from the listed change items only, at most 10, the rest in the detail
  file, package changes of `ush-packages` by name from its listed change
  items only under the same rule of at most 10, with its
  `truncated_changes` as a number when above 0, own changes
  as the child's own counts per source and never summed, the firewall as
  one conclusion, disks as growth and what can be removed, settings in one
  line) and names the `runall` detail file, which keeps the full lists of
  each child ("Changes since the last run" in
  `references/report-format.md`).
- **Packages are not checked for updates.** The report says once, in one
  sentence for the whole `ush-packages` item, that its packages are "not
  checked for updates" (its Polish wording is in
  `references/report-format.md`), never per package: no lookup of newer
  versions exists yet, so the report never calls a package current or
  outdated. A manager
  of `ush-packages` whose `state` is `not_read` is "not read yet" (its
  `not_checked` entry), never absent or not installed.
- **Not present is not "not read yet".** In the `h8` item (`ush-packages`),
  a manager whose `state` is `not_present` (none of its disk locations
  exists) is "not present", never "not read yet", "could not be read" or 0
  packages, and it is no finding; a manager whose `state` is `not_read`
  stays "not read yet". The two are never swapped.
- **Offline, with a pointer to ush-advice.** For a fault this machine cannot
  explain offline (a device problem code, a crash code), the report offers
  a web lookup through `ush-advice` as the next step (its Polish wording is
  in `references/report-format.md`); `runall` itself
  searches nothing.
- **A success message is not verification.** After the user ran a block,
  a new run reads the values back.

## Steps

1. From the project root run, in a normal (non-elevated) shell:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-runall/scripts/runall.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}"
   ```

   It runs the script of every child in `data/children.json` (eight in
   the repository) one after another, which takes minutes and can
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
   `driver_update_links`, `link_counts`, `truncated` and `not_checked`.

3. For each child with status `ok`, in order from `h1` to `h8`, fetch its
   item:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-runall/scripts/runall.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --detail h1 --detail-file <detail_file>
   ```

   `<detail_file>` is the `runall` summary's `detail_file`; `--detail` runs
   no child. Read the child's `summary` with that skill's
   `references/summary-contract.md`, write your short note of its findings,
   and only then fetch the next item. A child with another status has
   `summary` `null`: there is nothing to fetch. A `firewall_ports` item cut
   from the summary is fetched the same way (`--detail w51`).

4. Judge the findings across the children: weigh them with the scale of the
   shared contract (`high`, `medium`, `low`), link the findings about the
   same thing, set contradicting findings side by side, name the leftovers
   of the rule "Leftovers are named", and read the firewall items against
   the network categories. The script sets no
   threshold: the judgement is yours.

   Before judging, list `<data dir>/plans/` (not `done/`); for an open plan of a skill run in
   this pass, compare this run's values with the values its run blocks set (its `Odczyt po
   zmianie` names how to read them back), write the result under `Notatki`, and move it to
   `plans/done/` (never over an existing file) only when every value the plan
   sets (by a run block or by a step in words) reads back as set; otherwise
   it stays open. If `plans/` cannot be listed, say so and give the reason; it
   is not "no plans".

5. The report only proposes: a recommendation that needs a change says it
   in words (the "what to do" part of rule 4, rule 8 of
   `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/report-style.md`), and no change block
   ever goes into the report. Only after the user decides on a
   recommendation, take its blocks, with their shell, risk and rollback,
   following the `SKILL.md` of the child they come from:
   - A child with a print-only `--block` printer (`ush-settings`:
     `python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-settings/scripts/settings.py" --block <id> --detail-file <the child's detail_file> --data-dir "<absolute data dir>"`;
     `ush-files`: `python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-files/scripts/files.py" --block <id> --data-dir "<absolute data dir>"`;
     `ush-inventory`:
     `python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-inventory/scripts/inventory.py" --block <ids> --detail-file <the child's detail_file> --data-dir "<absolute data dir>"`)
     prints them; take that output word for word, split into run and undo
     blocks as the printer prints them:
     - `inventory.py --block` prints each entry as its `# <id>: ...`
       comment lines, the change, a line `# Rollback, same shell: ...` and
       then the rollback, with a blank line between entries. Split each
       entry at its `# Rollback, same shell:` line: the lines above it go
       word for word into a run fence under
       `<!-- ush:block ush-inventory <id> -->`; that line and the lines
       below it (up to the blank line before the next entry) go into the
       undo fence under `<!-- ush:undo ush-inventory <id> -->`, the same id;
       put the entry's shell on a line above its undo marker as well.
       A `# <id>: no block: <reason>` line gets no fence.
     - `settings.py --block` prints no rollback line per entry: after any
       `no block` lines it prints up to four parts, each opened by its
       header line (`# Run in a normal (non-elevated) Windows PowerShell`,
       `# Run in an elevated Windows PowerShell`, `# Rollback: normal
       (non-elevated) Windows PowerShell`, `# Rollback: elevated Windows
       PowerShell`) and separated by a blank line. Each part goes word for
       word into its own fence: a run part under
       `<!-- ush:block ush-settings normal -->` or
       `<!-- ush:block ush-settings elevated -->`, a rollback part under the
       undo marker with the id of its shell (`normal` or `elevated`).
     - `files.py --block` prints per item one `#` header line (ending in
       `rollback: cannot be undone`) and the block, and no rollback block:
       the lines after the header go into a run fence under
       `<!-- ush:block ush-files <id> -->`, and the undo section gets
       `<!-- ush:noundo ush-files <id> -->` followed by a line of words
       saying it cannot be undone, never a fence.
   - A child without a printer (`ush-events`, `ush-health`) gets the
     paste-ready block from the template in its own `SKILL.md`, filled with
     values from its own detail file, with every guard of the template kept
     (stamped backup, verify, abort, rollback).
   - Only where the child has no template for that change, give the step in
     words.

   Then write the repair plan per
   `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/repair-plan.md` as
   `<data dir>/plans/<YYYY-MM-DD>-<ascii-slug>.md`, with each block in
   `Bloki do uruchomienia` and its undo block in the undo section (its
   heading as `repair-plan.md` spells it); a block whose rollback is
   "cannot be undone" (a `files.py` clean-up, the `ush-events` dump copy
   with `--delete-source`, the log clear) gets the no-undo marker of
   `repair-plan.md` there instead, and check it:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_repair_plan.py" "<absolute path of the plan>"
   ```

   Correct the plan until the check gives `ok` `true`. Then tell the user
   which plan holds the blocks, and deliver the run blocks per
   `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/run-me.md`: all run blocks of a normal
   PowerShell in one `run-me.ps1`, all of an elevated one in one
   `run-me-admin.ps1`, in the plan's order; an undo block only when the user
   asks to undo, as its own file. The blocks are never given in the chat and
   never go into the report.

   When a printer exits with an error or prints no block for that id, put
   no block in the plan: write the child's manual step in words, or say that
   no block could be printed and give the error line. Never write a change
   block yourself: every block comes from a `--block` printer or a child's
   template.

   After the user ran the blocks, a new run reads the values back (the
   plan's `Odczyt po zmianie`). Write the result under `Notatki` of the plan
   and move the file to `<data dir>/plans/done/` with a move only under the
   condition of step 4 (otherwise it stays open); a plan is never deleted.

6. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/runall-<YYYY-MM-DD-HHMM>.md` (local time of the run).
   The first line is `<!-- ush:summary <summary_file> -->` with the absolute
   `summary_file` path of the `runall` summary. Write no separate report per
   skill for this pass.

7. After saving, run:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_report.py" "<absolute data dir>/reports/runall-<YYYY-MM-DD-HHMM>.md"
   ```

   In Windows PowerShell, the same command first sets
   `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false);` so the
   Polish letters of the printed section reach the chat unchanged; in a POSIX shell
   the command runs as it is.

   (`python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_report.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --latest --skill ush-runall`
   checks the newest `runall-*.md` instead.)
   It fails on a number backed neither by the `runall` summary nor by an `h`
   item named in `ush:detail`, and on an `h`, `w` or `y` item of the summary not
   named in the report. Correct the report and run the check again until it
   prints `OK`. `OK` means each number occurs somewhere in that JSON, not
   that it is used for the right thing (a child's id or path can back a
   made-up number), so the rules above still bind you. Do not hand the
   report to the user before it prints `OK`.

8. Tell the user where the report is (the absolute path of the report file, in the chat answer
   only): the chat answer is the summary section that `check_report.py` printed after `OK` when
   it checked the report, word for word, followed by that path, with nothing added. It holds no
   block: a block comes only after the user decides (step 5).

9. Only when a child has `elevated` `false` and `not_checked` entries that
   need administrator rights: give one block for an elevated PowerShell that
   runs the whole pass, delivered in `run-me-admin.ps1` per
   `${CLAUDE_PLUGIN_ROOT}/skills/ush-common/references/run-me.md` (not `run-me.ps1`, which is
   for a normal shell). It is not required; do not run it yourself.

   ```
   # Runs the same read-only pass with administrator rights. It changes
   # nothing on the machine and writes only to <data dir>\work\ and the
   # baselines of the skills in <data dir>\state\.
   Set-Location "<absolute plugin root>"
   python -B skills/ush-runall/scripts/runall.py --data-dir "<absolute data dir>"
   ```

   Children with an elevated baseline compare an elevated run only with it, so
   their first elevated run has no comparison. After the user says it ran, read
   the newest `<data dir>/work/runall-*.summary.json`, which must be newer than
   the hand-off (its `generated_at`, UTC, later than the UTC time in the
   `# Written:` header of `run-me-admin.ps1`, never the file's modification time;
   `run-me.md` "After the run"), in which no child with status `ok` has
   `elevated` `false`: a child whose status is not `ok` shows only as its
   status, and an `elevated` of `null` (`ush-events` and `ush-advice` report
   none) is not a missing right. When it is not newer, or a child with status
   `ok` has `elevated` `false`, the elevated pass did not run, failed or ran
   without the rights: follow `run-me.md` "After the run", which says when to
   tell the user to run the same `run-me-admin.ps1` again from an elevated
   PowerShell and when to ask for the error first. Otherwise write a new report
   from that one pass, as in steps 2-7. Never merge two passes into one report.

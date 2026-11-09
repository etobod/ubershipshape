---
name: ush-packages
description: List the packages the package managers of this Windows machine have installed, read offline from disk - pip for every Python registered in PEP 514 and the global npm packages - with each version and what was added, removed or changed since the last run. Every other package manager is listed as not read yet. Use when the user asks which Python or npm packages are installed, which versions, or what changed in them. Read-only; no package manager runs and nothing goes online, so no package is checked for a newer version.
---

# ush-packages

Reads the packages of the package managers from the files on disk through
read-only PowerShell jobs: pip (the metadata of every Python registered in
PEP 514, in its install and per-user `site-packages` folders) and npm (the
`package.json` of every global package). No package manager runs (no pip,
npm or winget command) and nothing goes online. It compares every package
with the baseline of the last run. A script counts and compares; you judge
and write a Markdown report; the user decides what to act on.

## Plugin paths

- Plugin root: `${CLAUDE_PLUGIN_ROOT}`
- Data folder: `${CLAUDE_PLUGIN_DATA}`

The references write these two folders as `<plugin root>` and
`<plugin data>`: fill them in from the two lines above.

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

- The user asks which Python (pip) or npm packages are installed, in which
  version, or for which Python.
- The user asks what changed in the packages since the last run, or over a
  longer period ("since last week").

Not for: installing, updating or removing a package (the skill gives no
block), whether a newer version exists (that needs an ush-advice lookup,
which does not exist yet), winget, go, VS Code extensions and the other
package managers (listed as not read yet), installed programs, drivers and
autostart (`ush-inventory`). Say so if the user asks for these.

## Rules

- **Read-only, no change blocks.** `packages.py` changes nothing on the
  machine and writes only to `<data dir>/work/` and `<data dir>/state/`
  (its baseline and id map). The report gives no block that installs,
  updates or removes a package.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a package or its newest version.
- **Not checked for updates.** No package is checked for a newer version:
  that needs an ush-advice lookup, which does not exist yet. Every package
  in the report is marked as not checked for updates; never call a version
  old or current.
- **Read only the summary JSON.** Never open the raw captures or other files
  in `<data dir>/work/`. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the script writes:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  the plugin data folder (`--default-data-dir`). Take its absolute value from the summary's
  `summary_file` (the directory above `work/`). In the report text outside
  code blocks write it as `&lt;data dir>` in plain text, never in inline
  code, and never the expanded path: it contains the account name, which a
  report must not carry (`references/report-format.md`).
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. Do not count packages or changes yourself.
- **A manager not read is not absent.** A manager with `state` `not_read`
  was not read by this skill yet: write "not read yet", never "not
  present", "not installed" or "none". npm `status` `empty` is "npm not
  present" at the prefix read, with the other prefixes not searched.
- **A package worth a look only from facts.** Name a package as worth a look
  only for a fact the JSON holds (`unreadable`, a second entry of the same
  name, a version kept from the baseline because its folder could not be
  read), with why; never call a package removable or unused without such a
  fact.
- **Empty is not unreadable.** A source with `status` `unreadable`, a count
  `null`, a field in `unread_fields`, an item with `from_baseline`, a
  comparison `not_read` or `no_baseline`, or `truncated` or
  `truncated_changes` > 0 must be reported as such (see the degradation
  cases in `references/report-format.md`), never as "none" or "nothing
  there".

## Steps

1. From the project root run, in a normal shell:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-packages/scripts/packages.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}"
   ```

   It prints the summary JSON on stdout and writes it, with a detail file, to
   `<data dir>/work/`, and saves the new baseline to `<data dir>/state/`.
   The field meanings are in `references/summary-contract.md`.

   When the user asks about changes over a longer period ("what changed this
   month", "since last week"), add `--compare-to <N>d` (N from 1 to 30, e.g.
   `--compare-to 7d`): the run then compares with the saved state at least N
   days old instead of the latest run (`baseline.reference`,
   `baseline.reference_file`). Without such a question run it without the
   flag. Every run, with or without it, also keeps a day copy of the
   baseline in `<data dir>/state/history/` (30 days).

2. Read the summary. For a package or change cut from the summary
   (`truncated`, `truncated_changes`) or one you need in full, fetch it:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-packages/scripts/packages.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --detail <id> --detail-file <detail_file>
   ```

   `<detail_file>` is the summary's `detail_file`, so the item comes from the
   same run as the summary. Ids: `k..` packages, `c..` changes (both stable
   between runs, not places in the list). Remember every id you fetched and
   used.

3. Judge the findings: which changes matter, which package is worth a look
   for a fact the JSON holds (see the rules), and what could not be read.
   Weigh them with the scale of the shared contract (`high`, `medium`,
   `low`). The script sets no threshold: the judgement is yours.

   Before writing, list `<data dir>/plans/` (not `done/`): its open repair plans,
   by file name, are part 3 of the report's summary section. This skill writes no
   plans of its own, so it reads nothing back and moves nothing. If `plans/`
   cannot be listed, say so in part 3, give the reason under "Not checked", and
   never write "nic" there. A missing `plans/` folder is read and empty: "nic".

4. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/packages-<YYYY-MM-DD-HHMM>.md` (local time of the
   run). The first line is `<!-- ush:summary <summary_file> -->` with the
   absolute `summary_file` path from the summary.

5. After saving, run:

   ```
   python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_report.py" "<absolute data dir>/reports/packages-<YYYY-MM-DD-HHMM>.md"
   ```

   In Windows PowerShell, the same command first sets
   `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false);` so the
   Polish letters of the printed section reach the chat unchanged; in a POSIX shell
   the command runs as it is.

   (`python -B "${CLAUDE_PLUGIN_ROOT}/skills/ush-common/scripts/check_report.py" --default-data-dir "${CLAUDE_PLUGIN_DATA}" --latest --skill ush-packages`
   checks the newest `packages-*.md`
   instead.) The checker is shared by all skills; it reads the ush-packages
   rules from `data/report-profile.json`. It fails on a number not backed by
   the JSON, on a package or change of the summary not named in the report
   and on a summary without `managers`. Correct the report and run the check
   again until it prints `OK`. `OK` means each number occurs somewhere in the
   JSON, not that it is used for the right thing, so the rules above still
   bind you. Do not hand the report to the user before it prints `OK`.

6. Tell the user where the report is (the absolute path of the report file, in the chat answer
   only): the chat answer is the summary section that `check_report.py` printed after `OK` when
   it checked the report, word for word, followed by that path, with nothing added.

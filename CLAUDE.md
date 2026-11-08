# ubershipshape

## Commands
Run from the project root. Needs Python 3.12, ruff and Windows PowerShell 5.1. (B-07)

- Tests: `python -B -m unittest discover -s tests -t .` (needs `tests/__init__.py`) (B-07)
- Lint: `python -m ruff check skills tests` (B-07)
- Run a skill script: `python -B skills/ush-<name>/scripts/<script>.py [--data-dir <dir>]` (B-07)
- Data directory: `--data-dir`, else `USH_DATA_DIR` (absolute), else `--default-data-dir` (the
  plugin's data folder `~/.claude/plugins/data/ubershipshape-ubershipshape/`, passed by SKILL.md as
  `${CLAUDE_PLUGIN_DATA}`); with none of them the script stops with a usage error. (B-07)
- Plugin version: raise `version` in `.claude-plugin/plugin.json` with every change to `skills/`,
  or an installed plugin is not updated. (B-07)

Never `python3` (a Microsoft Store stub that exits 0 silently) and never bare `ruff` (not on `PATH`). (B-07)

## Invariants
- **Read-only by default.** Any change to the machine, or to disk outside the data directory,
  needs an explicit flag. `ush-runall` never passes such flags on. The one write outside the data
  directory without a flag is the model writing `run-me.ps1` / `run-me-admin.ps1` in the cwd. (B-08)
- **Skills do not change the machine themselves.** They hand the user a paste-ready block for an
  elevated shell (delivered in run-me.ps1 / run-me-admin.ps1 in the cwd, B-02/B-09), say what it
  does, and then read the values back. The only exceptions are
  operations with an explicit flag whose safety condition is met (e.g. clearing a log only after
  a verified export). (B-08)
- **Copy and verify before anything irreversible.** A failed or unverified copy aborts. (B-08)
- **The script counts, the model judges.** No "this is a problem" threshold in code. Scripts
  classify only by explicit data files (known-noise list, settings catalogue). (B-08)
- **The model never reads raw command output.** Scripts return a JSON summary on stdout and a
  detail file on disk. Every number in a report comes from the script's JSON. (B-08)
- **Empty is not unreadable.** Code distinguishes "read, nothing there" from "could not read"
  in the data structure, never collapses the second into the first, and reports what it could
  not read and why. (B-08)
- **A missing policy key means "default", not "disabled".** Report the effective state. (B-08)
- **A success message is not verification.** Read the value back. (B-08)
- **A false alarm is worse than a miss.** Every classification rule has a test on clean data. (B-08)
- **Tests never touch the machine.** No registry, service or log writes; no live queries. (B-08)
- **Test data is written, not recorded.** Fixtures are invented from scratch with real field
  shapes; nothing captured from this machine goes into the repository. (B-08)
- **Nothing leaves the machine.** Only `ush-advice` reaches the network, with general queries only. (B-08)
- **Every recommendation carries** its risk level, the evidence, the permissions it needs and
  its rollback. (B-08)
- **Code, identifiers, comments, `SKILL.md` and skill docs in English.** Reports and messages to
  the user in the language the user addressed the skill in. File names and JSON keys ASCII. (B-08)

## Manual verification / UAT
A skill is not done until it has run on this machine: run it from the project root, open the
report in the plugin data folder's `reports\` (the chat answer names its full path), and check that each number matches the JSON
summary and that the "not checked" section names what was skipped (or says "nothing"). (B-09)

## Developer notes
Layout (B-10):

```
skills/ush-<name>/     the product: SKILL.md, references/, scripts/, data/ (noise lists, catalogues)
tests/ush-<name>/      unittest + invented fixtures (in the repository)
loc/                   workflow notes, gitignored
<data dir>             outside the project, output of runs: state/ (baselines), reports/, work/ (raw captures)
```

- Scripts take `--data-dir` (default: `USH_DATA_DIR`, else `--default-data-dir`) and make every
  path absolute at once. Never derive output paths from the script's own location. (B-10)
- The old `ush-data` directory in the project is not moved; it is reachable only via an explicit
  `--data-dir <project>/ush-data`. (B-10)
- Python standard library only; `unittest`; no third-party packages. (B-10)
- Machine facts: `loc/tmp/old-loc-2026-10-29/maszyna.md`. Old PowerShell → Python traps and the
  elevation table: brainstorm `loc/inbox/001-U-brainstorm-fresh-start-from-old-loc.md`, Notes,
  old `loc/PATTERNS.md`. (B-10)

## Limits
- Offline, no dependencies to install: the tool must work when the machine is in bad shape. (B-11)
- No machine name, account name, SID, SSID, MAC address, profile path, serial number or reading
  from this machine in any tracked file. (B-11)
- No `/code-review ultra` or any other review that uploads the code or data. (B-11)
- No scheduled or automatic runs; skills are run by hand. (B-11)

## User language
Polish. (B-12)

## Project-specific workflow
- Every plan ends with a milestone that runs the skill on this machine and produces a report. (B-13)
- Keep plans small (at most 3–5 milestones). No work on tooling in this project. (B-13)
- Plans are made one at a time from a `loc/PRD.md` direction, in the order given there. (B-13)

## Diagrams
<!-- Topics whose diagram `loc-diagram` keeps up to date in `loc/diagrams/` besides the project overview, one per line, e.g. "saving an entry". Empty: only the overview. -->

## Frontend
<!-- Only for a project with a user interface; empty: none. The UI check command (masterskills scripts/ui_check.py, which fails on a defect and takes the screenshot), Screenshots: on or declined, References: on or off, the tokens file, the pages and the widths, e.g. 375, 768, 1440; Scene views: the project's own screenshot command for states an address cannot reach, or none; an optional design plugin and its review command. Plans prove UI milestones with them, loc-review runs the design review. -->

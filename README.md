# ubershipshape

**A Claude Code plugin that checks a Windows machine and tells you, in plain words, what needs attention.**
Python measures, Claude explains, you decide. It never changes anything on its own.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757)
![Windows 11](https://img.shields.io/badge/Windows-11-0078d4)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)
![No dependencies](https://img.shields.io/badge/dependencies-none-success)
![Read-only](https://img.shields.io/badge/default-read--only-success)

```
You:     check the health of my computer

Claude:  Mostly fine. Two things want attention:
         1. Drive C: has 9% free space left (shrank by 14 GB since last week).
         2. A restart is pending after an update installed 3 days ago.
         Disks, battery, antivirus, Secure Boot and BitLocker: OK.
         Full report: C:\Users\<you>\.claude\plugins\data\ubershipshape-ubershipshape\reports\health-2026-10-31-1830.md
```
<sub>Example answer, numbers invented.</sub>

## Install

Inside Claude Code, run:

```
/plugin marketplace add etobod/ubershipshape
/plugin install ubershipshape@ubershipshape
/reload-plugins
```

That is all: no packages, no setup step. Python 3.12 must be on `PATH` (`python`, not `python3`).

<details>
<summary><strong>Prefer the terminal?</strong></summary>

```bash
claude plugin marketplace add etobod/ubershipshape
claude plugin install ubershipshape@ubershipshape
```

</details>

<details>
<summary><strong>From a local clone</strong></summary>

```
/plugin marketplace add C:/path/to/ubershipshape
/plugin install ubershipshape@ubershipshape
```

</details>

**Updates.** Claude Code does not update third-party plugins by itself:

```
/plugin marketplace update ubershipshape
/plugin update ubershipshape@ubershipshape
```

Then `/reload-plugins`, or open a new session. Your data and baselines stay where they are.

## Usage

Ask in your own words, in any language. Claude picks the skill:

| Ask | Runs |
|---|---|
| "check the health of my computer" | `ush-health` |
| "why did my laptop restart last night?" | `ush-events` |
| "is telemetry off? did my privacy settings change?" | `ush-settings` |
| "what starts with Windows? what was installed recently?" | `ush-inventory` |
| "what is eating my memory? what listens on the network?" | `ush-processes` |
| "where did my disk space go? what can I clean up?" | `ush-files` |
| "is Windows up to date? is there a newer BIOS?" | `ush-advice` |
| "check everything" | `ush-runall` |

Or call a skill directly, e.g. `/ubershipshape:ush-health`.

Every answer starts with a short verdict and names the **full path of the report**, a Markdown file
with the details, the evidence and, for each recommendation, its risk, the permissions it needs
and how to undo it.

## Skills

| Skill | What it looks at |
|---|---|
| **ush-health** | Disk health and free space, battery wear, devices with errors, failed updates, a pending restart, antivirus, restore points and WinRE, Secure Boot, TPM, BitLocker. |
| **ush-events** | 30 days of the System and Application logs collapsed into a short list: recurring errors, bugchecks, unexpected shutdowns, the stability index, memory dumps, known noise filtered out. |
| **ush-settings** | Privacy, telemetry, ads, AI, updates, security, power and network settings against a catalogue of expected values, where each value comes from, what drifted, and which apps used the camera, microphone or location. |
| **ush-inventory** | Installed programs and apps, what starts by itself, Windows components, drivers, and what was added outside Windows' own lists (firewall rules, root certificates, hosts entries, administrators, Defender exclusions), and what changed. |
| **ush-processes** | What uses the memory right now, grouped by program, why each one runs and who started it, and what listens on TCP and UDP ports. |
| **ush-files** | How full each drive is, the largest folders and files, what grew since last time, and how much the known cleanup places hold. |
| **ush-advice** | Latest security update installed? Known exploited vulnerabilities patched? Newer BIOS? Known issues of your Windows version? The only skill that goes online. |
| **ush-runall** | Runs all of the above and writes one report with one prioritised list of recommendations, links between findings and contradictions side by side. |

## How it works

```
  you ask ──▶ Claude picks a skill ──▶ Python script measures (read-only)
                                              │
                                              ▼
                      JSON summary  +  detail file on disk
                                              │
  you decide ◀── verdict + report path ◀── Claude reads the summary and writes the report
```

- **The script counts, the model judges.** Scripts have no "this is a problem" thresholds; every
  number in a report comes from the script's JSON, never from Claude reading raw command output.
- **Changes are yours to run.** When you decide to act on a recommendation, Claude writes a repair
  plan with paste-ready blocks for an elevated PowerShell, each with its undo block, and reads the
  values back on the next run. It does not run them itself.

## Principles

### Nothing changes without your consent

Read-only is the default. Every change needs an explicit flag, records the previous value and
documents its rollback. Anything irreversible is copied and verified first.

### Nothing leaves the machine

No telemetry, nothing uploaded. The one skill that reaches the network (`ush-advice`) asks general
questions, never about your data.

### No dependencies to install

Python 3.12 and its standard library. Works offline, which matters most when the machine is already
in trouble.

### A false alarm is worse than a miss

A tool that cries wolf on a healthy machine gets ignored, and the real finding gets ignored with it.
Known noise is filtered explicitly, with a reason recorded for each entry, and every rule is tested
on clean data.

### A report should still make sense in six months

In your language, with the evidence beside every recommendation, and with "what was not checked"
always stated, because "nothing found" and "could not read" are not the same.

## Your data

Reports, baselines (for "what changed since last time") and repair plans live in the plugin's data
folder:

```
~/.claude/plugins/data/ubershipshape-ubershipshape/
├── reports/   Markdown reports
├── state/     baselines for comparisons
├── plans/     repair plans (open, then done/)
└── work/      raw captures and detail files
```

The folder is kept across plugin updates. To use another folder, set `USH_DATA_DIR` (an absolute
path) or pass `--data-dir`.

> [!WARNING]
> Uninstalling the plugin **deletes this folder**, including your baselines and repair plans.
> To keep it: `claude plugin uninstall ubershipshape@ubershipshape --keep-data`

## Requirements

- Windows 11 (developed and tested on Windows 11 Home)
- [Claude Code](https://docs.claude.com/en/docs/claude-code)
- Python 3.12 on `PATH`, standard library only
- Some checks (disk reliability counters, BitLocker, some event data) read more when run elevated;
  the report names what it could not read and why

## Status

All eight skills work; testing as an installed plugin is in progress. Developed against Windows 11
Home.

## Development

```
python -B -m unittest discover -s tests -t .
python -m ruff check skills tests
```

Tests never touch the machine: no registry, service or log writes and no live queries; all fixtures
are invented.

## License

[MIT](LICENSE)

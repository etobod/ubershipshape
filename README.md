# ubershipshape

**Windows maintenance. Your machine, your rules.**

A set of skills for an assistant with shell access — Claude Code or a local
model. Python does the measuring, the model does the reasoning, you decide what
to act on.

---

## Skills

| Skill | What it does |
|---|---|
| **ush-events** | Collapses thousands of event-log entries into a list of a dozen. Surfaces bugchecks, sudden restarts, and sleeps the machine never woke from. |
| **ush-settings** | Watches whether your privacy and performance settings have quietly drifted back to where they were before you changed them. |
| **ush-advice** | Checks current recommendations and tests them against your actual machine. No generalities. |
| **ush-files** | Shows what appeared on disk since the last check. Cleanup with a list to approve first. |
| **ush-programs** | What is installed, what is new, and what you don't remember installing. |
| **ush-processes** | What is eating memory, why it is running, and who started it. |
| **ush-components** | Windows components — including the ones that switched themselves on after an update. |
| **ush-runall** | Runs all of the above and returns one report with one prioritised list of recommendations. Read-only, always — *run everything* never means *change everything*. |

---

## Principles

### Nothing changes without your consent

Read-only is the default. Every change needs an explicit flag, records the
previous value, and documents its rollback.

### Nothing leaves the machine

No telemetry, nothing uploaded. The one skill that reaches the network asks
general questions, never about your data.

### Nothing to install

Python 3.12 and the standard library. Works offline — which matters most when
the machine is already in trouble.

### A false alarm is worse than a miss

A tool that cries wolf on a healthy machine gets ignored, and the next
finding — the real one — gets ignored with it. Known noise is filtered
explicitly, with a reason recorded for each entry.

### A report should still make sense in six months

In your language, with a table of contents, and with the command and its real
output beside every change.

---

## Status

Early. The specification is written and the first skill is being built.
Developed against Windows 11 Home.

## License

MIT

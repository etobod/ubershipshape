# Repair plan

When the user decides to act on a finding, the model writes a repair plan: a
record of what is to be done to the machine and how to undo it. The user runs
the blocks; the plan is never run by a script.

## Location and name

`<data dir>/plans/<YYYY-MM-DD>-<ascii-slug>.md`, for example
`plans/2026-10-30-telemetria.md`. The slug is lowercase ASCII letters, digits
and hyphens. The plan is written in Polish, the user's language.

A plan is never overwritten. When a file of that name already exists in
`plans/` or in `plans/done/`, add `-2`, `-3` and so on before `.md`
(`plans/2026-10-30-telemetria-2.md`) until the name is free in both. The
same rule holds for the move to `plans/done/`: when the name is taken
there, the moved file gets the next free `-2`, `-3` suffix.

## Sections

Exactly these level-2 headings, in this order:

1. `## Problem` - what was found, with the numbers from the skill's JSON.
2. `## Wybrana opcja` - the option the user chose, its risk level and the
   permissions it needs.
3. `## Bloki do uruchomienia` - the blocks to run. Each carries its shell,
   risk and permissions.
4. `## Bloki cofające` - the blocks that restore the previous state.
5. `## Odczyt po zmianie` - the command that reads the value back after the
   change (usually a rerun of the skill).
6. `## Notatki` - the model's notes and, later, the read-back result.

Every block comes from the skill's `--block` printer, copied word for word,
or, for a skill without one, from the template in its `SKILL.md`, filled in
with values from the detail file and with every guard of the template kept.
A block is never written or filled in by hand otherwise.

## Markers

Each run block is a marker line followed by a fenced block:

````markdown
<!-- ush:block ush-settings s1 -->
```powershell
...
```
````

Its undo block has the same skill and id:

````markdown
<!-- ush:undo ush-settings s1 -->
```powershell
...
```
````

Every fenced block under `## Bloki do uruchomienia` needs its run marker on
the previous non-blank line; a block without one is reported as
`unmarked block, line N`. An undo marker counts only under `## Bloki cofające`
and only when its next non-blank line opens a fenced block.

A run block that cannot be undone (for example a clean-up, a deletion of the
originals after a verified copy, or the clearing of a log, whose rollback is
"cannot be undone") gets a no-undo marker in the undo section instead of an
undo block, followed by a line of words saying so:

````markdown
<!-- ush:noundo ush-files c2 -->
Tego bloku nie da się cofnąć (cannot be undone): usunięte pliki nie wracają.
````

The no-undo marker counts as the undo of its skill and id only under
`## Bloki cofające` and only when its next non-blank line is a line of words:
a no-undo marker followed by a fenced block, a heading or another marker does
not count.

Markers and their fenced blocks start at the left margin, never inside a list
item or a blockquote. Shell, risk and permissions go on a line above the
marker, never between the marker and its fence. A level-2 heading that is not
one of the six sections stays inside the section it is in.

A marker inside a fenced code block does not count. A plan with no blocks,
only words, is allowed: for example when the skill has no `--block` printer.

## Life cycle

1. The plan is open in `plans/`.
2. The user runs the blocks.
3. A later run reads the values back; the result goes under `## Notatki`.
4. Only when every value the plan sets reads back as set is the file moved to
   `plans/done/` (never over an existing file there, see "Location and name");
   otherwise it stays open. A plan is never deleted.

A stored block whose `Set-Location` folder no longer exists was written by an
older plugin version (an update installs the plugin into a new folder). Before
handing that block out again, replace the folder in its `Set-Location` line
with the current plugin root (`<plugin root>`, as an absolute path) and tell
the user you did so; change nothing else in the block, so its rollback still
works.

## Check

Check every plan right after writing it:

```powershell
python -B "<plugin root>/skills/ush-common/scripts/check_repair_plan.py" <file>
python -B "<plugin root>/skills/ush-common/scripts/check_repair_plan.py" --default-data-dir "<plugin data>" --latest
```

The checker prints JSON with `file`, `ok`, `missing_sections` and
`blocks_without_undo`, and exits 0 when `ok` is true, 1 when not. It looks
only for the headings and the markers; it never judges the text of the plan.
`--latest` takes the newest plan in `plans/`, never one in `plans/done/`; a
`plans/` directory that cannot be listed is an error with the reason (exit 2),
not "no plan".

# Run-me files

A block for the user (an elevated re-run, or a run or undo block of a repair
plan) is never handed over to be copied out of the chat or a plan. The model
writes it, with its file tool, into a file in the session's working directory
(the cwd):

- `run-me.ps1` for a normal (non-elevated) Windows PowerShell;
- `run-me-admin.ps1` for blocks that need administrator rights; it elevates
  itself.

The file is overwritten as a whole each time. One file holds the blocks the
user is to run now, for one shell only, in the order of their source. A run
block and its undo block are never in the same file: the undo block is
written only when the user asks to undo, as its own file.

## What the file holds

The block comes only from a `--block` printer, a template in a `SKILL.md` or a
repair plan, copied word for word, with every guard kept. Its `Set-Location`
to the plugin root stays inside the file. Around it, for `run-me-admin.ps1`:

```
# Shell: Windows PowerShell; starts itself as administrator, run it from a normal PowerShell
# Not elevated: it starts itself again as administrator (a UAC prompt) and this window stops.
# Does: <what the block does, one or two lines>
# Source: <the printer, the SKILL.md template or the repair plan file>
# Written: <YYYY-MM-DD HH:MM> (<YYYY-MM-DD HH:MM> UTC)
# Writes its output to run-me-admin.out.txt beside this file in the cwd.
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "Starting as administrator: accept the UAC prompt; the blocks run in a new window."
  Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File "<cwd>\run-me-admin.ps1"'
  Write-Host "This window is done. Wait for 'Finished.' in the new window."
} else {
  Start-Transcript -Path "<cwd>\run-me-admin.out.txt" -Force
  try {
    Write-Host "[<n>/<N>] <what the block does, a few words> ..."
<the block, word for word>
    Write-Host "[<n>/<N>] done"
    Write-Host "Finished. You can close this window."
  } finally { Stop-Transcript }
}
```

The blocks run only in the `else` branch: a window without the rights starts
the elevated one (`-NoExit` keeps it open when the blocks end) and does nothing
else. A refused UAC prompt starts nothing.

For `run-me.ps1`:

```
# Shell: normal (non-elevated) Windows PowerShell
# Does: <what the block does, one or two lines>
# Source: <the printer, the SKILL.md template or the repair plan file>
# Written: <YYYY-MM-DD HH:MM> (<YYYY-MM-DD HH:MM> UTC)
# Writes its output to run-me.out.txt beside this file in the cwd.
Start-Transcript -Path "<cwd>\run-me.out.txt" -Force
try {
  Write-Host "[<n>/<N>] <what the block does, a few words> ..."
<the block, word for word>
  Write-Host "[<n>/<N>] done"
  Write-Host "Finished. You can close this window."
} finally { Stop-Transcript }
```

`<n>` is the block's number in the file and `<N>` the number of blocks; the
`Write-Host` lines are ASCII and name no path or value from the machine.

The `# Written:` times come from the machine, never from a guess or the
conversation: read them just before writing the file,

```
python -B -c "from datetime import datetime, timezone; n = datetime.now().astimezone(); print(n.strftime('%Y-%m-%d %H:%M'), n.astimezone(timezone.utc).strftime('(%Y-%m-%d %H:%M UTC)'))"
```

and copy its output after `# Written: `.

`<cwd>` is the absolute working directory, written into the file: a file
pasted into a console instead of run with `-File` has no script folder, and
its transcript would land in the drive root; the elevated window starts in
another folder. The `finally` closes the transcript also when the block
throws.

Several run blocks of one shell go into one file one after another, each
under its own `# Source:` comment and between its own `[<n>/<N>]` start and
`done` lines, all inside the same `try { ... } finally`; the `Finished.` line
comes once, after the last block.

The file ends up as UTF-8 with BOM (Windows PowerShell 5.1 reads a UTF-8
file without BOM as ANSI); see "After writing".

## Before the first write

In a git repository, check the file and its out file together in the cwd:
`git check-ignore run-me.ps1 run-me.out.txt`, or
`git check-ignore run-me-admin.ps1 run-me-admin.out.txt`. It prints each
ignored name; when either name is missing from its output, tell the user that
file could be committed and ask before writing.

## After writing

Read back the written file and compare its block lines with their source line
by line. For a block taken from a repair plan whose `Set-Location` folder was
replaced per `repair-plan.md` (an older plugin version), the source is the
block after that replacement: the replaced folder is the one line that may
differ from the stored plan, and the user is told it was changed. Then give
it the BOM, whatever the file tool wrote (it reads an existing BOM and writes
exactly one):

```
python -B -c "import sys; p = sys.argv[1]; t = open(p, encoding='utf-8-sig').read(); open(p, 'w', encoding='utf-8-sig', newline='').write(t); print(open(p, 'rb').read(3) == bytes([239, 187, 191]))" "<absolute path of the file>"
```

It prints `True` when the file now starts with the BOM. Any difference in
the comparison, or `False`: write the file again; never hand over a file that
differs or prints `False`.

## What the user is given

One command line to type, and what the file does:

- `run-me.ps1`: `powershell -ExecutionPolicy Bypass -File .\run-me.ps1`
  in a normal PowerShell in the cwd;
- `run-me-admin.ps1`: `powershell -ExecutionPolicy Bypass -File "<cwd>\run-me-admin.ps1"`
  in a normal PowerShell, with `<cwd>` the absolute working directory; it
  shows a UAC prompt to accept, and the blocks run in a new window that stays
  open. Tell the user to answer only when that new window shows
  `Finished. You can close this window.` (or an error): the typed command
  returns at once, while the blocks may run for minutes.

`-ExecutionPolicy Bypass` applies to that one process and changes no machine
setting. Never run either file yourself.

## After the run

The out file (`run-me.out.txt` or `run-me-admin.out.txt`) is for the user
only: never open, read or search it (it is raw output with the machine and
account names). Whether the block ran, and what it changed, is shown only by
what the block's source names for reading it back, from JSON: for a skill's
elevated re-run, a new summary of that skill whose `generated_at` (UTC) is
later than the UTC time in the file's `# Written:` header, with `elevated`
`true`; for a change block, a new run of the skill (the repair plan's
`Odczyt po zmianie`); where the source names its own read-back (the
`ush-events` dump copy: `manifest.json` `copied_at` against the UTC time read
before the hand-off), that one. Never use the file's modification time: the
header is the moment of the hand-off.

A skill's read-only elevated re-run changes nothing, so it can always be run
again. When it left a summary newer than the header whose `elevated` is not
`true` (not elevated), it ran without the rights: tell the user to run the
same `run-me-admin.ps1` again, with the same command, and accept the UAC
prompt; a normal run of the skill cannot read what needs the rights. When it left no summary newer than the header, ask the user
whether the window showed an error. Without one, it did not run: hand the same
file back as above. With one, ask for the error message (below) and say what
it points to (a wrong folder in `Set-Location`, a refused UAC prompt, `python`
not found, the script stopping); then hand the same file back as above, once that
cause is put right. For `ush-runall` a child that fails shows in the new
summary as its status, so only a pass that wrote no summary at all comes
here.

A file with a change block is never handed back to be run again on that rule:
a change block writes no summary, and it may have changed the machine
already.

When the user says a block failed, ask only for the error message in their
own words, never to paste the out file or the window (its header and paths
carry the machine and account names). After a change block, also a failed
one, a new run of the skill reads back what it changed before anything else
is proposed.

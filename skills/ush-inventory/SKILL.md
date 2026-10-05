---
name: ush-inventory
description: List what is installed on this Windows machine (Win32 programs and MSIX apps), what starts by itself (Run and RunOnce registry values, Startup folders, scheduled tasks with a logon or boot trigger, automatic services) with the file facts of each entry, the Windows components (optional features and capabilities), the drivers, and what was added to the system outside Windows' own lists (firewall rules, root certificates, hosts entries, members of Administrators, Defender exclusions), and what changed since the last run. Use when the user asks what is installed, what starts with Windows or at sign-in, what slows down the start, which features or drivers are there, what was added to the system or changed recently, or whether an entry is needed. Items that are part of Windows are counted, not listed. Read-only; gives paste-ready blocks to turn an entry off or remove an addition.
---

# ush-inventory

Reads the installed programs, the autostart entries, the Windows
components, the drivers and the things added to the system (firewall rules,
root certificates, hosts entries, members of Administrators, Defender
exclusions) through read-only PowerShell jobs, checks the target file of
every autostart entry, and compares everything with the baseline of the
previous run. A script counts and matches; you judge and write a Markdown
report; the user decides what to act on.

## When to use

- The user asks what is installed, or what an installed program is.
- The user asks what starts by itself (at boot or at sign-in), what slows
  the start down, or whether an entry is needed.
- The user asks what changed since the last run: a new program, a new
  autostart entry, a changed command or signature, a new driver, feature,
  firewall rule, certificate or administrator.
- The user asks which Windows features or capabilities are on, or which
  drivers are installed and from whom.
- The user asks what was added to the system: firewall rules, root
  certificates, hosts entries, members of Administrators, Defender
  exclusions.

Not for: processes running now (`ush-processes`), Windows settings and
policies (`ush-settings`), the event logs (`ush-events`), the health of
disks, devices or updates (`ush-health`), uninstalling a program or a
driver, fixing anything automatically. Say so if the user asks for these.

## Rules

- **Read-only.** `inventory.py` changes nothing on the machine and writes
  only to `<data dir>`. Do not run any change yourself. A recommended change
  is a paste-ready block the user runs themselves (see "Change blocks"); you
  then read the value back by running the skill again.
- **Nothing leaves the machine.** No web search, no upload, no online tool,
  also not to look up a program or a file.
- **Read only the summary JSON.** Never open the raw captures or other files
  in `<data dir>/work/`. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the scripts write:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  `%LOCALAPPDATA%\ubershipshape`. Take its absolute value from the summary's
  `summary_file` (the directory above `work/`). In the report text outside
  code blocks write it as `&lt;data dir>` in plain text, never in inline
  code (a `<` before a letter fails the check, and inline code shows `&lt;`
  as it is), and never the expanded path: it contains the account name,
  which a report must not carry. The expanded path appears only in the
  `ush:summary` marker and in the `--data-dir` of every block that runs a
  skill script (`references/report-format.md`), and in the backup path of a
  certificate or hosts block. Every block that runs a skill script starts
  with `Set-Location "<absolute project root>"` and passes
  `--data-dir "<absolute data dir>"` (rule 9 of
  `skills/ush-common/references/report-style.md`): an elevated shell of
  another account has a different `%LOCALAPPDATA%`.
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. Do not count items, add up the Windows-own
  counts or compute an age yourself; do not write a number from memory or
  from the user's message.
- **"Unneeded" is your judgement, never the script's.** The script only
  says whether an item is part of Windows (`own`, by
  `data/windows-own.json`). Whether an entry is needed you judge from the
  facts: what it runs, which program it belongs to, whether the file exists
  and is signed, when it appeared. Say what the entry does before you
  suggest turning it off.
- **A missing signature or file is a fact, not a verdict.** `exists`
  `false`, `NotSigned` or `program` `null` is written as what it is; a
  launcher (`rundll32.exe`, `powershell.exe`) as target is normal for many
  entries.
- **Empty is not unreadable.** A source with `status` `unreadable`, a
  comparison `not_read` or `no_baseline`, a first run, a field in
  `unread_fields`, an item with `from_baseline`, or `truncated` > 0 must be
  reported as such (see the degradation cases in
  `references/report-format.md`), never as "no changes" or "clean".
- **A missing value is not `false`.** `null` means unknown; `approved`
  `not_set` means the entry runs.
- **`requires administrator` is "not read", never "none".** A source whose
  `reason` says it requires administrator rights (`capabilities` and
  `defender_exclusions` in a normal run) was not read: say so and offer the
  elevated run of step 8; never write "no capabilities" or "no exclusions".
- **A `removed` driver is a device that is not present now** (unplugged,
  switched off, or given another driver), not an uninstalled driver. Say so
  when you report it.
- **Outside Windows is a fact, not a verdict.** A firewall rule, root
  certificate, hosts entry, Administrators member or Defender exclusion in
  `additions` is only outside the Windows lists of `data/windows-own.json`
  (hosts entries, members and exclusions are always listed). Say what it is
  and what it allows, then judge; never call it suspicious because it is
  listed.
- **Administrators members.** Never recommend removing a member with
  `is_current` `true` or `null`, nor one whose removal would leave no member with
  `enabled` `true`. When any member has `enabled` `null`, recommend removing
  none and say why: it is not known which accounts could still act as
  administrator. `enabled` is `null` without `unread_fields` for a member
  that is a group or another kind of account (the job's `Get-LocalUser`
  found no local user with its SID, or the member is no local or Microsoft
  account); under the source's `method: adsi`, `name` and
  `principal_source` (and `enabled` for an `object_class` `User`) are in
  `unread_fields`.
- **No blocks for drivers.** A driver is reported and judged, never
  removed by this skill; the vendor's uninstaller or Device Manager is the
  way, and the user decides.
- **Defender exclusions.** Under the source's `method: registry` no Defender
  exclusion gets a block: Defender is not running (usually another antivirus
  is active), so `Remove-MpPreference` fails as `Get-MpPreference` did. Say
  that the exclusions are inactive while the other antivirus runs and can be
  removed once Defender is on again. An exclusion with `origin` `policy` or
  `null` gets no block either: a policy sets it and would restore it, or its
  origin is unknown.
- **Features and capabilities finish at restart.** Disabling a feature or
  removing a capability completes when Windows restarts; a run of the skill
  confirms it only after that restart. Say so with the block.

## Steps

1. From the project root run:

   ```
   python -B skills/ush-inventory/scripts/inventory.py
   ```

   It prints the summary JSON on stdout and writes it, with a detail file, to
   `<data dir>/work/`, and saves the new baseline to `<data dir>/state/`.
   The field meanings are in `references/summary-contract.md`.

   When the user asks about changes over a longer period ("what changed this
   month", "since last week"), add `--compare-to <N>d` (N from 1 to 30, e.g.
   `--compare-to 7d`): the run then compares with the saved state at least N
   days old instead of the latest run (`baseline.reference`,
   `baseline.reference_file`). Without such a question run it without the
   flag. The flag changes nothing but the data directory; every run, with or
   without it, also keeps a day copy of the baseline in
   `<data dir>/state/history/` (30 days).

2. Read the summary. If you need one item in full (a program cut by
   `truncated`, the `approved_raw` of an entry for a rollback block, a
   Windows-own item, a change of an own item), fetch it:

   ```
   python -B skills/ush-inventory/scripts/inventory.py --detail <id> --detail-file <detail_file>
   ```

   `<detail_file>` is the `detail_file` value from the summary, so the item
   comes from the same run that the report checker checks against.

   Ids are stable between runs, not places in the list, so the id of an
   item cut from the summary (`truncated`, `truncated_drivers`,
   `truncated_components`, `truncated_additions`) cannot be guessed. Find
   the cut items with:

   ```
   python -B skills/ush-inventory/scripts/inventory.py --cut --detail-file <detail_file>
   ```

   It prints `cut`, a list of `{id, list, name}`, and starts no machine job.
   Fetch a cut item with `--detail` before you name it in the report.

   Ids: `a..` programs, `s..` autostart entries, `f..` components
   (features and capabilities), `d..` drivers, `x..` additions, `c..`
   changes. Remember every id you fetched and used.

3. Judge the findings: which autostart entries the user likely does not
   need, which ones point to a missing or unsigned file, which changes are
   worth a look. Weigh them with the scale in the shared contract
   `skills/ush-common/references/summary-contract.md` (`high`, `medium`,
   `low`). The script sets no threshold: the judgement is yours.

4. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/inventory-<YYYY-MM-DD-HHMM>.md` (local time of the
   run). The first line is `<!-- ush:summary <summary_file> -->` with the
   absolute `summary_file` path from the summary.

5. Every recommendation carries `weight`, `kind` (`change`, `observe`,
   `consult_service`), `risk`, `evidence` (ids and values from the JSON),
   `permissions` and `rollback`, as defined in the shared contract. A
   `change` gives a block from "Change blocks".

6. After saving, run:

   ```
   python -B skills/ush-common/scripts/check_report.py "<absolute data dir>/reports/inventory-<YYYY-MM-DD-HHMM>.md"
   ```

   (`python -B skills/ush-common/scripts/check_report.py --latest --skill ush-inventory`
   checks the newest `inventory-*.md` instead.) The checker is shared by all
   skills; it reads the ush-inventory rules from `data/report-profile.json`.

   It prints `OK` when every number is backed by the JSON, every program,
   autostart entry, component, driver, addition and change of the summary is
   named, the summary has every key this skill requires, and the markers
   are in place. `OK` means each number occurs somewhere in the JSON, not that it
   is used for the right thing, so the rule above still binds you. Otherwise
   it names each unbacked number with its line, each item left out as
   `not named in the report: <id> (<list>)`, or each missing key as
   `required key missing from the summary: <key>` (a summary of an older
   shape: run the skill again). Correct the report, save, and run the
   check again. Do not hand the report to the user before it prints
   `OK`.

7. Tell the user where the report is and give the dashboard and the main
   findings in a few lines.

8. Only when `elevated` is `false`: you may offer an elevated run, which
   also sees the tasks this account cannot and reads the capabilities and
   the Defender exclusions. It compares only with an elevated baseline, so
   its first run has no comparison. Do not run it yourself.

   ```
   # Runs the same read-only inventory with administrator rights. It changes
   # nothing on the machine and writes only to <data dir>\work\ and
   # <data dir>\state\ (a separate elevated baseline and the id map).
   Set-Location "<absolute project root>"
   python -B skills/ush-inventory/scripts/inventory.py --data-dir "<absolute data dir>"
   ```

   After the user says it ran, read the newest
   `<data dir>/work/inventory-*.summary.json`, whose `elevated` must be
   `true` (otherwise say that the block did not run elevated), and write a
   new report from that one summary, as in steps 3-6. Never merge two
   summaries into one report.

## Change blocks

A block turns one autostart entry off, disables a firewall rule or a
feature, or removes a capability or one addition. Every block below is
written with invented values; fill in the real ones from the item. Each
recommendation with a block carries its `risk`, `evidence` (ids and values),
`permissions` (the shell) and `rollback` (the block's rollback). A block
that must stop when a check fails runs inside `& { ... }`, so that `throw`
ends the whole block and not only its line.

For an autostart entry fill in the values from the entry
(`name`, `location`, `command`, `value_kind`, `approved`, `approved_raw`,
`delayed`, `template_start`); fetch the entry with `--detail` when you need
`approved_raw` and name its id in `ush:detail`. Each block says in a comment
what it does and which shell it needs, and gives the previous value and the
rollback. After the user ran it, run the skill again: the new run reads the
value back (the entry shows `enabled` `false`, a `changed` change, or, for a
service, a `removed` one because it left the automatic list). A success
message from PowerShell is not a read-back.

Give no change block for an entry with `from_baseline` `true`, with
`approved` or `enabled` in `unread_fields`, with `approved` `unknown`, for a
`run`, `run_once` or `startup_folder` entry while the source
`startup_approved` is not `read` (its `approved` is the previous run's, not
the value now), or named in a `not_checked` item `services <name>`: its
previous value is not known, so there is no safe rollback. Say so instead.

Never write the account name: a path under the profile folder is written
with `%USERPROFILE%`, and a block builds it from `$env:USERPROFILE`
(`references/report-format.md`, "Account names").

Which shell:

- An `HKCU` entry (`run:hkcu\...`, `startup:user:...`) in a normal,
  **non-elevated** PowerShell of the user: an elevated shell may run as
  another account and would change that account's `HKCU`.
- An `HKLM` entry (`run:hklm64\...`, `run:hklm32\...`, `startup:common:...`),
  a task and a service in an **elevated** PowerShell.
- The blocks for components and additions below in an **elevated**
  PowerShell, except a `user_root` certificate: that one in a normal,
  **non-elevated** PowerShell of the user, for the same reason as `HKCU`.

### Run or Startup entry (`run`, `startup_folder`)

Marks the entry as disabled the way Task Manager does, in its
`StartupApproved` key (see "approved" in `references/summary-contract.md`
for the key of each entry). The value or the file itself stays. The key
may not exist yet, so the block creates it.

```
# Turns off the autostart entry 'InventedTool' (HKCU Run) as Task Manager does.
# Normal (non-elevated) PowerShell. Previous state: approved = not_set.
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
New-ItemProperty -Path $key -Name 'InventedTool' -PropertyType Binary -Value ([byte[]](3,0,0,0,0,0,0,0,0,0,0,0)) -Force | Out-Null
(Get-ItemProperty -Path $key -Name 'InventedTool').'InventedTool'
```

Rollback, same shell. When the entry was `not_set`:

```
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' -Name 'InventedTool'
```

When the entry had a value (`approved_raw`, from `--detail`), write it back:

```
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
$hex = '020000000000000000000000'
$bytes = [byte[]]@(for ($i = 0; $i -lt $hex.Length; $i += 2) { [Convert]::ToByte($hex.Substring($i, 2), 16) })
New-ItemProperty -Path $key -Name 'InventedTool' -PropertyType Binary -Value $bytes -Force | Out-Null
```

For an `HKLM` entry use the `HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\...`
key (`Run`, `Run32` for `hklm32`, `StartupFolder` for `startup:common`) in
an elevated shell.

### RunOnce entry (`run_once`)

A `RunOnce` value has no Task Manager state; the block removes the value.
Risk: a pending installer or update step may then never finish. Same shell
as a `Run` entry of that hive.

```
# Removes the RunOnce value 'InventedSetup' (HKCU). Normal PowerShell.
# Previous value (ExpandString): "%LOCALAPPDATA%\InventedSetup\finish.exe" /quiet
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'InventedSetup'
Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
```

Rollback, with the previous `command` and `-PropertyType` from `value_kind`
(`String`, `ExpandString`, ...):

```
New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'InventedSetup' -PropertyType ExpandString -Value '"%LOCALAPPDATA%\InventedSetup\finish.exe" /quiet'
```

### Scheduled task (`task`)

`location` is the task path, `name` the task name. Elevated shell.

```
# Disables the task \InventedVendor\InventedUpdater. Elevated PowerShell.
# Previous state: Ready.
Disable-ScheduledTask -TaskPath '\InventedVendor\' -TaskName 'InventedUpdater' | Out-Null
(Get-ScheduledTask -TaskPath '\InventedVendor\' -TaskName 'InventedUpdater').State
```

Rollback:

```
Enable-ScheduledTask -TaskPath '\InventedVendor\' -TaskName 'InventedUpdater' | Out-Null
```

### Per-user service (`user_service` `true`)

Windows starts one instance per sign-in from a template; the start type of
the template decides. `name` is the template name. Elevated shell. Needs
`template_start` (no block when it is `null`). The instance may keep its
start type until the next sign-in.

```
# Sets the template of the per-user service InventedSync to manual start (3).
# Elevated PowerShell. Previous Start value: 2.
$key = 'HKLM:\SYSTEM\CurrentControlSet\Services\InventedSync'
Set-ItemProperty -Path $key -Name Start -Value 3 -Type DWord
(Get-ItemProperty -Path $key -Name Start).Start
```

Rollback, with `template_start`:

```
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\InventedSync' -Name Start -Value 2 -Type DWord
```

### Other service (`service`)

Elevated shell. After the change the service is no longer automatic, so
the next run shows it as removed.

```
# Sets the service InventedAgent to manual start. Elevated PowerShell.
# Previous start type: Automatic, delayed = true.
Set-Service -Name 'InventedAgent' -StartupType Manual
(Get-CimInstance Win32_Service -Filter "Name='InventedAgent'").StartMode
(Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\InventedAgent').DelayedAutostart
```

Rollback when `delayed` is `false`:

```
Set-Service -Name 'InventedAgent' -StartupType Automatic
```

Rollback when `delayed` is `true` (Windows PowerShell 5.1 has no
`AutomaticDelayedStart`; write `sc.exe`, since `sc` is an alias of
`Set-Content`):

```
sc.exe config InventedAgent start= delayed-auto
```

### Components and additions: common rules

Fill in the values from the item in `components` or `additions` (fetch it
with `--detail` when you need a field the summary does not carry, such as a
certificate's `thumbprint` or a rule's key, and name its id in
`ush:detail`). After the user ran a block, run the skill again: the new run
reads the value back (a `changed` or `removed` change of that item). The
read-back lines inside a block are a first look, not the verification.

Give no block for an item whose source was not read in this run, for a
field the block needs that is `null` or in `unread_fields`, or for a kind
this section excludes; say why instead. No block for a driver, ever.

### Defender exclusion (`defender_exclusion`)

Only for `origin` `local`, and only when the source `defender_exclusions`
has `method: preference` (see "Rules"). The parameter follows `type`:
`path` `-ExclusionPath`, `extension` `-ExclusionExtension`, `process`
`-ExclusionProcess`, `ip` `-ExclusionIpAddress`. A `value` under the
profile folder is built from `$env:USERPROFILE` in a double-quoted string
(`"$env:USERPROFILE\..."`; in single quotes it is not expanded and
`Remove-MpPreference` removes nothing without an error); that is right only
when the elevated shell runs as the same account, so say so. Risk: the folder,
file type or process is scanned again, which may slow a tool that relied on
the exclusion.

```
# Removes the Defender exclusion of the folder C:\InventedTool\cache (origin local).
# Elevated PowerShell. Previous state: the path is excluded from scanning.
Remove-MpPreference -ExclusionPath 'C:\InventedTool\cache'
(Get-MpPreference).ExclusionPath
```

Rollback, same shell:

```
Add-MpPreference -ExclusionPath 'C:\InventedTool\cache'
```

### Firewall rule (`firewall_rule`)

Only for `store` `local`: a `policy` rule is set by a policy and an
`app_iso` rule by the app's package, which would restore it. The block
disables the rule; it never deletes it. `-Name` is the rule's registry
value name, the part of its `key` after `firewall:local:` (not the display
`name`). Risk: the program the rule lets through loses that network access.

```
# Disables the firewall rule {00000000-0000-0000-0000-00000000A001}
# ("Invented Sync TCP in", store local). Elevated PowerShell. Previous state: Active = TRUE.
Disable-NetFirewallRule -Name '{00000000-0000-0000-0000-00000000A001}'
(Get-NetFirewallRule -Name '{00000000-0000-0000-0000-00000000A001}').Enabled
```

Rollback, same shell:

```
Enable-NetFirewallRule -Name '{00000000-0000-0000-0000-00000000A001}'
```

### Root certificate (`root_certificate`)

Only for `store` `machine_root` (elevated shell, `Cert:\LocalMachine\Root`)
and `user_root` (**non-elevated** shell, `Cert:\CurrentUser\Root`). A
`machine_policy` or `enterprise` certificate gets no block, because a
policy would restore it. Neither does a `machine_root` certificate with
`in_authroot: true`, nor a thumbprint that is also in another root store:
the logical store `Cert:\LocalMachine\Root` joins `authroot`,
`machine_policy` and `enterprise`, and `Cert:\CurrentUser\Root` also joins
the machine stores and the user policy store, so `Remove-Item` could hit another copy. The block
checks the other stores in the registry itself and stops when the
thumbprint is in one of them. It then exports the certificate into
`<data dir>\work\` and checks the thumbprint of the file; a failed export or
another thumbprint stops the block before anything is removed. The read-back
is the registry key of the physical store, `False` when the certificate is
gone. Risk: sites and programs that rely on this root are no longer trusted.

```
# Removes the root certificate 0123456789ABCDEF0123456789ABCDEF01234567
# ("CN=Invented Root CA", store machine_root). Elevated PowerShell.
# Exports it first and stops if the exported file has another thumbprint.
& {
  $thumb = '0123456789ABCDEF0123456789ABCDEF01234567'
  $item = 'Cert:\LocalMachine\Root\' + $thumb
  $own = 'HKLM:\SOFTWARE\Microsoft\SystemCertificates\ROOT\Certificates\' + $thumb
  $others = @('HKLM:\SOFTWARE\Microsoft\SystemCertificates\AuthRoot\Certificates',
    'HKLM:\SOFTWARE\Policies\Microsoft\SystemCertificates\Root\Certificates',
    'HKLM:\SOFTWARE\Microsoft\EnterpriseCertificates\Root\Certificates')
  foreach ($store in $others) {
    if (Test-Path -LiteralPath (Join-Path $store $thumb)) { throw "the thumbprint is also in $store; the Cert: store would not tell the copies apart; nothing removed" }
  }
  $file = '<absolute data dir>\work\cert-' + $thumb + '.cer'
  Export-Certificate -Cert (Get-Item -LiteralPath $item -ErrorAction Stop) -FilePath $file -Type CERT -ErrorAction Stop | Out-Null
  $copy = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $file
  if ($copy.Thumbprint -ne $thumb) { throw "the exported file has thumbprint $($copy.Thumbprint), not $thumb; nothing removed" }
  Remove-Item -LiteralPath $item -ErrorAction Stop
  Test-Path -LiteralPath $own
}
```

For `user_root`, in a non-elevated shell: `$item` is
`'Cert:\CurrentUser\Root\' + $thumb`, `$own` is
`'HKCU:\Software\Microsoft\SystemCertificates\Root\Certificates\' + $thumb`,
and `$others` also holds
`'HKLM:\SOFTWARE\Microsoft\SystemCertificates\ROOT\Certificates'` and the
user policy store
`'HKCU:\Software\Policies\Microsoft\SystemCertificates\Root\Certificates'`
(`Cert:\CurrentUser\Root` joins it too).
Rollback, same shell, from the exported file (for `user_root` with
`Cert:\CurrentUser\Root`; Windows asks to confirm):

```
Import-Certificate -FilePath '<absolute data dir>\work\cert-0123456789ABCDEF0123456789ABCDEF01234567.cer' -CertStoreLocation 'Cert:\LocalMachine\Root'
```

### Hosts entry (`hosts_entry`)

Removes one host name from one line of the hosts file. The block copies the
file into `<data dir>\work\` and compares `Get-FileHash` of the copy and the
original; a difference, or a hash that could not be computed, stops it.
Every block gets its own stamp in the backup name, and the block stops when
that backup already exists, so a second block never overwrites the backup
the first one's rollback needs. It finds the line by its content (the
`address` and the `hostname` as separate words before any `#`), not by the
`line` number, and stops when no line or more than one line matches.
`duplicates` counts every repeat of the pair, also on the same line, so a
`duplicates` above 0 does not by itself mean the block stops; a repeat on
the same line is removed with the name. In that line it removes only
this name, and the whole line only when no name is left. It writes the file
back in the encoding it was read in. The folder comes from
`Tcpip\Parameters\DataBasePath`, as the skill reads it. Risk: the name is
resolved by DNS again (a blocked site is reachable again).

```
# Removes the host name ads.example (address 0.0.0.0) from the hosts file.
# Elevated PowerShell. Copies the file first and stops if the copy differs,
# or if not exactly one line holds this address and name.
& {
  $address = '0.0.0.0'; $name = 'ads.example'
  $dir = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters').DataBasePath
  $hosts = Join-Path $dir 'hosts'
  $backup = '<absolute data dir>\work\hosts-20260101-120000.bak'
  if (Test-Path -LiteralPath $backup) { throw "$backup already exists (another block's backup); nothing changed" }
  Copy-Item -LiteralPath $hosts -Destination $backup -ErrorAction Stop
  $copyHash = (Get-FileHash -LiteralPath $backup -ErrorAction Stop).Hash
  $hostsHash = (Get-FileHash -LiteralPath $hosts -ErrorAction Stop).Hash
  if (-not $copyHash -or $copyHash -ne $hostsHash) { throw 'the copy differs from the hosts file; nothing changed' }
  $reader = New-Object System.IO.StreamReader($hosts, [System.Text.Encoding]::Default, $true)
  $text = $reader.ReadToEnd(); $encoding = $reader.CurrentEncoding; $reader.Close()
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.AddRange([string[]]($text -split "`n"))
  $hits = @(for ($i = 0; $i -lt $lines.Count; $i++) {
    $words = @(($lines[$i].TrimEnd("`r") -split '#', 2)[0].Trim() -split '[ \t]+' | Where-Object { $_ })
    if ($words.Count -ge 2 -and $words[0] -eq $address -and @($words[1..($words.Count - 1)] | Where-Object { $_ -eq $name }).Count -gt 0) { $i }
  })
  if ($hits.Count -ne 1) { throw "expected one line with $address $name, found $($hits.Count); nothing changed" }
  $i = $hits[0]
  $cr = if ($lines[$i].EndsWith("`r")) { "`r" } else { '' }
  $parts = $lines[$i].TrimEnd("`r") -split '#', 2
  $words = @($parts[0].Trim() -split '[ \t]+' | Where-Object { $_ })
  $left = @($words[1..($words.Count - 1)] | Where-Object { $_ -ne $name })
  if ($left.Count -gt 0) {
    $line = (@($address) + $left) -join ' '
    if ($parts.Count -eq 2) { $line += ' #' + $parts[1] }
    $lines[$i] = $line + $cr
  } else {
    $lines.RemoveAt($i)
    if ($i -eq $lines.Count -and $i -gt 0) { $lines[$i - 1] = $lines[$i - 1].TrimEnd("`r") }
  }
  [System.IO.File]::WriteAllText($hosts, ($lines -join "`n"), $encoding)
  Select-String -LiteralPath $hosts -Pattern ([regex]::Escape($name))
}
```

Rollback, same shell, with the backup the block made:

```
$dir = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters').DataBasePath
Copy-Item -LiteralPath '<absolute data dir>\work\hosts-20260101-120000.bak' -Destination (Join-Path $dir 'hosts') -Force
```

The rollback puts back the whole file as it was before the block, so it
also undoes any later edit of the file.

### Administrators member (`administrator`)

Only within the rules of "Rules" (never `is_current` `true` or `null`, never the last
member with `enabled` `true`, none while any member has `enabled` `null`).
The member is named by its SID, the part of its `key` after `admin:`. Risk:
the account loses administrator rights at its next sign-in; programs it
runs as administrator stop working.

```
# Removes S-1-5-21-0-0-0-1002 from Administrators (S-1-5-32-544). Elevated PowerShell.
# Previous state: member.
Remove-LocalGroupMember -SID 'S-1-5-32-544' -Member 'S-1-5-21-0-0-0-1002'
Get-LocalGroupMember -SID 'S-1-5-32-544' | Select-Object SID, ObjectClass
```

Rollback, same shell:

```
Add-LocalGroupMember -SID 'S-1-5-32-544' -Member 'S-1-5-21-0-0-0-1002'
```

### Optional feature (`feature`)

Disables one feature with `state` `enabled`. The change finishes at the
next restart: the read-back in the block gives `DisablePending` (restart
needed) or `Disabled`; the skill's `state` shows `disabled` only after the
restart. Risk: programs that use the feature stop working.

```
# Disables the optional feature Invented-Feature-Client. Elevated PowerShell.
# Previous state: enabled. Finishes at the next restart.
Disable-WindowsOptionalFeature -Online -FeatureName 'Invented-Feature-Client' -NoRestart | Out-Null
(Get-WindowsOptionalFeature -Online -FeatureName 'Invented-Feature-Client').State
```

Expected: `DisablePending` or `Disabled`. Rollback, same shell (also
finishes at restart; a feature with parents may need `-All`):

```
Enable-WindowsOptionalFeature -Online -FeatureName 'Invented-Feature-Client' -NoRestart
```

### Capability (`capability`)

Removes one capability with `state` `Installed` (read only in an elevated
run). The change may finish at the next restart; the skill confirms it
after that restart. Risk: the part of Windows it provides is gone until it
is added back.

```
# Removes the capability Invented.Tools~~~~0.0.1.0. Elevated PowerShell.
# Previous state: Installed. May finish at the next restart.
Remove-WindowsCapability -Online -Name 'Invented.Tools~~~~0.0.1.0' | Out-Null
(Get-WindowsCapability -Online -Name 'Invented.Tools~~~~0.0.1.0').State
```

Expected: anything other than `Installed`. Rollback, same shell; it may
download the package from Windows Update, so it needs the network:

```
Add-WindowsCapability -Online -Name 'Invented.Tools~~~~0.0.1.0'
```

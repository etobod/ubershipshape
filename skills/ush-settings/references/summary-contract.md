# Summary contract, ush-settings (schema_version 1)

The ush-settings fields of the summary, and the ush-settings cases of the
shared parts. The shared contract (files and budget, `sources`,
`not_checked`, ids and `--detail`, the baseline, recommendations, the report
profile) is in `skills/ush-common/references/summary-contract.md`; the report
checker reads the ush-settings rules from `data/report-profile.json`.

## Files and output

One run of `scripts/settings.py` writes to `<data dir>` (the data directory:
`--data-dir`, else `USH_DATA_DIR`, else `%LOCALAPPDATA%\ubershipshape`, made
absolute at once):

- `work/settings-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same
  text is printed on stdout. The time in the name is UTC.
- `work/settings-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `elevated`, `edition_id`,
  `sources`, `comparison`, `catalogue_changes` and the full lists
  `settings` (every entry, `matches` and `not_applicable` included),
  `changes` and `usage` (never truncated), with the same ids as the summary.
  A settings item there also carries `rationale`, `manual`, `applies_if`,
  `read`, `apply`, `rollback_manual`, `source_location`, `locations` (every
  registry location with its `status`, `value` and `kind`), `adapters`,
  `products`, `services_running`, `local_enabled` (a firewall profile's
  local, persistent setting; `null` when it was not read) and
  `policy_enabled` (a firewall profile's policy state from the RSOP store:
  `"NotConfigured"` when no policy sets the profile, `true`/`false` when one
  does, `null` when the RSOP store could not be read), as far as they apply.
  `--block` gives a firewall block only when `policy_enabled` is
  `"NotConfigured"`.
- `state/ush-settings.json`, or `state/ush-settings.elevated.json` for a run
  with administrator rights - the baseline (see "Baseline").

The PowerShell jobs write their results to `work/settings-<stamp>.<job>.json`
(raw captures: never read them). The script changes nothing on the machine;
it exits 0, or 2 without reading anything when the catalogue does not load
(the problems go to stderr).

To keep the summary within its budget of 35 000 characters only `usage` is
cut, from its end; `truncated` counts the cut items, and the detail file
keeps them, with ids that follow the last one in the summary. When the
summary does not fit even with no usage item left, nothing is cut and
`not_checked` names the budget.

## The catalogue

`data/settings-catalogue.json` is the source of truth for what is read and
what is expected; `scripts/catalogue.py` validates it (its docstring lists
the rules). Each entry has `id`, `area` (`privacy`, `telemetry`, `ads`,
`ai`, `updates`, `security`, `power`, `network`, `permissions`, `storage`),
`level` (`standard` or `strict`), `title`, `rationale`, `read` (a read type
and its parameters), `expected` (a list of values, or `null` for an entry
that is only reported), `default` (the Windows default when nothing is set,
`null` when unknown), `apply` (the scripted change, or `null` with a
`manual` step), and optionally `applies_if` (`{entry, in}`) and
`rollback_manual`.

## Sources

`sources` is a list of `{name, status, reason}`, one per job the catalogue
uses (a job whose read type no entry uses is left out): `registry_values`,
`wifi_adapter`, `services`, `firewall`, `security_center`, `defender`,
`device_guard`, `powercfg`, `dns`, `appx`, `delivery_optimization`,
`optional_features`, `shadow_storage` and `capability_usage`. Besides the
shared `read`, `empty` and `unreadable`, a status can be `not_run`:
`shadow_storage` without administrator rights; its entries are `not_read`
and `not_checked` names them. A job that fails makes its entries `not_read`
and is named in `not_checked`. When `capability_usage` is `unreadable`,
`usage` is `[]`: nothing could be read, not "no app used the devices".

## Top-level fields

- `schema_version`, `skill` (`ush-settings`), `generated_at` (UTC),
  `elevated`.
- `edition_id`: `EditionID` of Windows (`Core` is Home), or `null` when it
  was not read (item `EditionID` in `not_checked`).
- `sources`, `not_checked` (`{what, reason}`), `summary_file`,
  `detail_file`, `truncated`.
- `baseline`: `{status, created_at, age_days, saved, reason, reference,
  reference_file}`; `status` is `compared`, `none` or `unreadable`.
  `reference` is `latest` or the `--compare-to` value (e.g. `7d`),
  `reference_file` the history copy compared with, or `null` (shared
  contract, "Baseline"). `created_at` and `age_days` are those of the state
  compared with. With `--compare-to` only `changes` and `comparison` use the
  copy; the saved baseline is built from the latest one. `not_checked` items
  of the baseline: `baseline` (the latest baseline could not be read),
  `reference baseline` (the history copy could not be read, so nothing was
  compared), `baseline history` ("history not kept", or "the day copy was kept, but old copies were not removed: ..." when only the cleanup
  failed) and `baseline save`.
- `comparison`: `{settings, capability_usage}`, each `compared`,
  `no_baseline` or `not_read`.
- `counts`: `{by_state: {<state>: n}, by_area: {<area>: {<state>: n}}}` over
  every entry of the catalogue.
- `settings`: the entries in the listed states (see below), `differs` first.
- `changes`, `catalogue_changes` (`{added, removed}`), `usage`.

## Settings items

Summary fields: `id` (`e1`...), `entry` (the catalogue id), `area`,
`level`, `title`, `state`, `effective`, `expected`, `source`,
`from_policy_on_home`, `reason`, `has_block`, and in an elevated run
`hkcu_elevated`.

The `e` ids are stable between runs: the number belongs to the catalogue entry
(`entry`), not to the item's position in the list, so the summary may have gaps
(`e1`, `e4`, ...). The map from the entry to its number is kept in
`<data dir>/state/ush-settings.ids.json` (the same file for a run with and
without administrator rights). On the first run with a map the numbers are the
places after sorting; later a new entry takes a number higher than any given
before, and the number of an entry that left the catalogue is not given again.
A map that cannot be read starts the numbering again and gives a `stable ids`
item in `not_checked`; a map that is not saved gives `stable ids save` (when the reason starts with "the id map was saved", only its previous copy was not replaced and the next run keeps these ids). The
`u` and `c` ids stay numbered by position in each run.

States, in this order:

| State | Meaning | In the summary |
|---|---|---|
| `differs` | read; `effective` is not in `expected` | listed |
| `not_read` | the value could not be read, or it depends on an entry that could not be read; `reason` says why; `effective` is `null` | listed |
| `default_unknown` | nothing is set, `expected` is set, and the catalogue has no `default` | listed |
| `info` | read; the entry has no `expected` | listed |
| `matches` | read; `effective` is in `expected` | counted |
| `not_applicable` | the `applies_if` condition is not met | counted |

`source`:

- `policy` or `preference`: the role of the registry location that decided
  the value (the first `present` location in catalogue order whose value is
  in its `map`, or that has no `map`);
- `default`: no location is set; `effective` is the catalogue's `default`;
- `system`: read from the system itself by a typed reader (a service, a
  firewall profile (the effective `ActiveStore`), Defender, `powercfg`, DNS, an app, an optional feature).

`from_policy_on_home`: `true` when `source` is `policy` and `edition_id`
starts with `Core` (a Home edition may ignore that policy), `false`
otherwise, `null` when the edition is unknown.

`hkcu_elevated` (elevated runs only): `true` when the value came from `HKCU`
or from a per-user reader (`appx`); in an elevated shell that is the
account that elevated, which may not be the user's.

## Changes

`changes` items (`c1`...):

- a setting: `key` (the entry id), `change` `changed`, `entry`, `area`,
  `title`, `state`, `before`, `after` (`effective` values);
- a usage item: `key`, `change` (`added`, `removed` or `changed`), `entry`
  `null`, `capability`, `app`, `packaged`, and for `changed` `before` and
  `after` (`value`).

Entries added to or removed from the catalogue are counted in
`catalogue_changes`, never listed as changes.

## Usage

`usage` items (`u1`...), from the consent store of `HKCU`: `capability`
(`webcam`, `microphone`, `location`), `app` (the package name, or the
program path for a non-packaged app), `packaged`, `value` (`Allow`, `Deny`,
or `null`), `last_used_start`, `last_used_stop` (UTC, or `null`), `in_use`
(started and not stopped), and `error` when the subkey could not be read.
Ordered: in use first, then by the last stop, newest first.

## Baseline

Sources `settings` (key = entry id, compared field `effective`) and
`capability_usage` (key `usage:<capability>:<packaged|nonpackaged>:<subkey>`,
compared field `value`). An entry that was not read keeps its previous
`effective` in the saved baseline and is never compared, so a failed reader
gives no false change; a usage subkey that could not be read (`error`) keeps
its previous `value` the same way. A normal run compares only with
`ush-settings.json`, an elevated one only with `ush-settings.elevated.json`.

## Paste-ready block

`settings.py --block e3,e7 [--detail-file <detail_file>]` prints, for those
items of the detail file (the newest one without `--detail-file`), up to four
parts, each headed by a comment:

- "Run in a normal (non-elevated) Windows PowerShell": `HKCU` registry
  values and apps (`Remove-AppxPackage`);
- "Run in an elevated Windows PowerShell": everything else (`HKLM`, Wi-Fi
  adapters, services, firewall, `powercfg`, optional features);
- "Rollback: normal ..." and "Rollback: elevated ...": the previous values
  read in that run, written back; where no command can restore a state (an
  app), a comment gives the manual step.

A registry key is created only inside `if (-not (Test-Path ...))`, printed
once per key in each part (before its first value; no block removes a key),
and only printed lines count as commands; texts are
quoted with `psrun.ps_quote`. An item without a block gives a `# <id>
<entry>: no block: <reason>` comment: already as expected, not read, does not
apply, set by a policy above the target, no scripted change, a previous
value that cannot be restored safely, a firewall profile whose local setting
was not read or is not what decides its effective state, or read in an
elevated run (no normal-shell commands from such a detail file). The
firewall rollback writes back the local setting. Exit 0 with at least one command,
1 with none or with an unknown id (message on stderr). Nothing is changed.

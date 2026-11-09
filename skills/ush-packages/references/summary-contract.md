# Summary contract, ush-packages (schema_version 1)

The ush-packages fields of the summary and the detail file, and the
ush-packages cases of the shared parts. The shared contract (files and
budget, `sources`, `not_checked`, ids, baseline, recommendations, the report
profile) is in `<plugin root>/skills/ush-common/references/summary-contract.md`;
the report checker reads the ush-packages rules from `data/report-profile.json`.
How the report is written is in `<plugin root>/skills/ush-common/references/report-style.md`
and `references/report-format.md`.

ush-packages reads the packages of the package managers from the files on
disk. No package manager runs (no pip, npm or winget command), nothing goes
online, and no package is checked for a newer version: that needs an
ush-advice lookup, which does not exist yet.

## Files and output

One run of `scripts/packages.py` writes to `<data dir>` (the data
directory: `--data-dir`, else `USH_DATA_DIR`, else the plugin data folder
(`--default-data-dir`), made absolute at once; see the shared contract):

- `work/packages-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same
  text is printed on stdout. The time in the name is UTC.
- `work/packages-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `elevated`, `sources`,
  `comparison`, the full lists `packages` and `changes` (never cut; the
  `packages` items here are the full items of the detail lists, with
  `manager` and `key`), the detail lists `pip_packages` and `npm_packages`
  (every item with its `key`), and `summary_file`, the summary of the same
  run.
- `state/ush-packages.json` (`ush-packages.elevated.json` for an elevated
  run) - the baseline, with the sources `pip_packages` and `npm_packages`;
  `state/history/` keeps a day copy of it (shared contract, "Baseline").
- `state/ush-packages.ids.json` - the id map of `k..` and `c..`.

The PowerShell jobs write their results to `work/packages-<stamp>.<job>.json`
and the folders asked for to `work/packages-<stamp>.package_folders.input.json`
(raw captures: never read them). The script changes nothing on the machine and
exits 0 when the collection ran, also when jobs failed.

`--detail <id>` prints the package (`k..`) or change (`c..`) with that id
from the newest `packages-*.detail.json` in `<data dir>/work/`, and exits 0;
an unknown id, or no detail file, exits 1 with a message on stderr. With
`--detail-file <path>` (the summary's `detail_file`) it reads that file
instead, needs no data directory, and starts no machine job.

`--compare-to <N>d` (N from 1 to 30) compares with the saved state at least
N days old (`state/history/`) instead of the latest baseline; see
"Comparison".

## Sources

`sources` is a list of `{name, status, reason}`, one per source, in this
order:

| Source | What is read | Gives |
|---|---|---|
| `pip_packages` | the Pythons registered under PEP 514 (`HKCU\Software\Python` once, `HKLM\SOFTWARE\Python` in the 64-bit and the 32-bit view; job `python_registrations`), and for each the `*.dist-info\METADATA` and `*.egg-info\PKG-INFO` files (the first `Name:` and `Version:` header lines) of `<InstallPath>\Lib\site-packages` and of the per-user `%APPDATA%\Python\Python<XY>[-32]\site-packages` (job `package_folders`, layout `python`). pip and python never run. `read` with at least one Python whose folders were looked at, `empty` with none (no registration, or every one skipped: from the Microsoft Store, or without a company or tag, each named in `not_checked`), `unreadable` when the registrations could not be read or no Python was read and one is left without an InstallPath; a Python without an InstallPath (not read through another registration of the same `<company>/<tag>`) keeps its packages from the previous baseline (`from_baseline`), also when the status is `unreadable` | `managers.pip`, the `pip` items of `packages`, the detail list `pip_packages` |
| `npm_packages` | the npm global prefix: a non-blank environment variable `NPM_CONFIG_PREFIX` (its name in any case; `.npmrc` is then not read), else the first `prefix=` line of `%USERPROFILE%\.npmrc` (spaces around `=` allowed; job `npmrc`), else `%APPDATA%\npm`; the prefix stays raw, its `%VAR%` expanded by the job `package_folders`; then `name` and `version` of each `<prefix>\node_modules\*\package.json` and `<prefix>\node_modules\@<scope>\*\package.json` (job `package_folders`, layout `npm`; a folder without `package.json`, such as `.bin`, is no package; an empty, `null` or non-object `package.json`, or one without a string `version`, is a package with status `unreadable`). npm never runs. `read` with at least one package; `empty` when `node_modules` is missing ("npm not present") or holds no package; `unreadable` when `.npmrc` or the folder could not be read, or when nothing but scope folders that could not be listed came, never `empty` | `managers.npm`, the `npm` items of `packages`, the detail list `npm_packages` |

## Summary fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version`, `skill`, `generated_at`, `elevated` | | shared contract |
| `sources` | list | see "Sources" |
| `baseline` | object | shared contract, "Baseline": `status` (`none`, `compared`, `unreadable`), `created_at`, `age_days`, `saved`, `reason`, `reference` (`latest` or the `--compare-to` value, e.g. `7d`) and `reference_file` (the history copy compared with, or `null`). `created_at` and `age_days` are those of the state compared with |
| `comparison` | object | per source (`pip_packages`, `npm_packages`): `compared`, `no_baseline` or `not_read` (shared contract). A first run is `no_baseline` and gives no changes |
| `managers` | object | one entry per manager of `data/managers.json`, in its order; see "Managers" |
| `counts` | object | `packages` (all packages, before the cut), `changes` (all changes, before the cut), and `added`, `removed`, `changed` (the changes of each kind) |
| `truncated` | int | the `packages` items cut from the summary |
| `truncated_changes` | int | the `changes` items cut from the summary |
| `not_checked` | list | shared contract; see "not_checked items" |
| `summary_file`, `detail_file` | string | the absolute paths of this run's files |
| `changes` | list | see "Changes (`c..`)" |
| `packages` | list | see "Packages (`k..`)" |

The summary keeps within 35000 characters: over it, `packages` items are cut
from the end first (down to none), then `changes` items, each counted in its
key above; the detail file keeps them all. A summary still too long after
both are cut adds a `summary budget` item to `not_checked`.

## Managers

`managers` is `{<name>: entry}` in the order of `data/managers.json` (a list
of `{name, step, read}`: the managers of B-01 with the step of B-20 that
reads them). Every entry has `state`:

| `state` | Meaning |
|---|---|
| `read` | pip or npm with `status` `read` or `empty` |
| `unreadable` | pip or npm with `status` `unreadable` |
| `not_read` | a manager this skill does not read yet; the entry is `{"state": "not_read"}` and `not_checked` has the item `<name>`: "not read yet". It is never "not present" |

`managers.pip` is `{state, status, pythons}`: `status` as the source
`pip_packages`; `pythons` is `[]` when no Python's packages were read: none is
registered, or every registration was skipped, each with its `not_checked`
entry (`what` `Python <tag> from the Microsoft Store (WindowsApps)`; `what`
`pip_packages registration` for one without a company or tag), `null` when the
registrations could not be read or no Python was read and one is left without an
InstallPath, else one entry
per Python read. A Python without an InstallPath has no entry: its `not_checked`
entry has `what` `pip_packages <company>/<tag>` and a reason naming no InstallPath.
Each entry:

| Field | Meaning |
|---|---|
| `python` | `<company>/<tag>` of the PEP 514 registration (`PythonCore/3.12`) |
| `count` | the packages read in both folders; `null` when a folder exists but could not be listed (the folder is in `not_checked`), never `0` |
| `unreadable` | the packages whose metadata file could not be read |
| `folders` | `{install, user}`: `read`, `absent` (the folder does not exist, counted `0`), `unreadable`, or `skipped` (the user folder name is not known from the registration; named in `not_checked`) |

`managers.npm` is `{state, status, prefix_from, count, unreadable}`:

| Field | Meaning |
|---|---|
| `status` | as the source `npm_packages`: `read`, `empty` (no `node_modules` folder: npm not present, or no package in it), `unreadable` |
| `prefix_from` | `NPM_CONFIG_PREFIX` (the environment variable), `npmrc` (a `prefix=` line of `%USERPROFILE%\.npmrc`) or `default` (`%APPDATA%\npm`), in that order; `null` when `.npmrc` could not be read |
| `count` | the packages read; `0` for `empty`; `null` for `unreadable` and when a scope folder (`@<scope>`) could not be listed, never `0` |
| `unreadable` | the packages whose `package.json` could not be read; `null` for `unreadable` |

## Packages (`k..`)

`packages` is one flat list over the read managers: pip first, then npm,
each by key. Ids `k<n>` are stable between runs (the id map), not places in
the list. A summary item:

| Field | Meaning |
|---|---|
| `id` | `k<n>` |
| `manager` | `pip` or `npm` |
| `key` | see "Keys" |
| `name`, `version` | as the metadata says (`Name`/`Version`, `name`/`version`); for a file that could not be read `version` is `null`, and `name` is `null` (pip) or the folder entry (npm) |
| `python` | pip only: `<company>/<tag>` of the Python |
| `folder` | pip: `install` or `user`; npm: the package folder (`<prefix>\node_modules\<name>`, the prefix raw) |
| `unreadable`, `reason` | only when the metadata file could not be read: `true` and why |
| `entry` | pip, unreadable only: the `dist-info` / `egg-info` entry |
| `from_baseline` | `true` when the folder could not be read in this run and the item is the previous baseline's |

The items of `packages` in the detail file, and of the detail lists
`pip_packages` and `npm_packages`, are the full items: also `status`
(`read` or `unreadable`), `reason`, and `unread_fields` (`["version"]` for an
unreadable file).

## Keys

| Source | Key |
|---|---|
| `pip_packages` | `pip:<company>/<tag>\|<install / user>\|<name>`, the name normalised by PEP 503 (runs of `-`, `_`, `.` as one `-`) and case-folded; for a file that could not be read the name comes from the folder name. A second entry of the same name in one folder (a stale `dist-info`) gets `\|<entry, case-folded>` added; the plain key goes to the higher version |
| `npm_packages` | `npm:<name>`, case-folded: the install name, i.e. the `node_modules` entry (`left-pad`, `@contoso/tool`), which is the package name; the same key when `package.json` could not be read |

## Changes (`c..`)

| Field | Meaning |
|---|---|
| `id` | `c<n>` |
| `key`, `source` | the item that changed |
| `change` | `added`, `removed` or `changed` |
| `name` | the item's name (after the change, or before it for `removed`) |
| `python` | `pip_packages` only: the Python |
| `version` | `added` and `removed` only: the version added or removed |
| `fields` | `changed` only: `{version: {before, after}}` |

pip changes come first, then npm; within a source the order is added,
removed, changed, then by key. Only a source whose `comparison` is
`compared` gives changes. The compared field of both sources is `version`;
a field that either side names in `unread_fields` is not compared.

An item kept from the baseline (`from_baseline: true`) is the same as in
the baseline, so it is no change. With `--compare-to` the run compares with a
history copy, not with the latest baseline these items come from, so such
an item can be `added` (its key was seen in this run) but never `changed`;
an item seen in this run but not read, which the latest baseline lacks, is
taken for the comparison from the history copy as if `from_baseline: true`:
it is never `removed` or `changed`. The saved baseline keeps these values
as without the flag.

## not_checked items of ush-packages

| `what` | When |
|---|---|
| `Python installs not registered in PEP 514 (venvs, portable builds)` | every run: "not searched" |
| `Python <tag> from the Microsoft Store (WindowsApps)` | a registration under the Store's folder; its packages are not read |
| `pip_packages` | the source is `unreadable`: the registrations could not be read |
| `pip_packages <company>/<tag>`, `pip_packages registration` | a registration without company, tag or install path, or a second one with the same company and tag; its packages are not read |
| `pip_packages <company>/<tag> <install / user>` | that folder could not be listed (the Python's `count` is `null`), or the user folder is not known from the registration (`skipped`); its items keep the previous baseline's |
| `npm_packages` | the source is `unreadable`: `.npmrc` or the global `node_modules` folder could not be read (the reason says which); `managers.npm.count` is `null`. A missing `node_modules` is no item of this kind: npm is not present at that prefix (see the next row) |
| `npm global packages under another prefix` | `managers.npm.status` is `empty`: the global `node_modules` folder of the prefix read (from `NPM_CONFIG_PREFIX`, `.npmrc` or the default) is absent or holds no package: "the prefixes from the global or builtin npmrc and the folder of node.exe (nvm-windows, zip builds) were not searched". Not added with status `read` or `unreadable` |
| `npm_packages <node_modules folder>\@<scope>` | that scope folder could not be listed (the reason says why); its packages keep the previous baseline's items (`from_baseline`), no `npm:@<scope>` item is listed, and `managers.npm.count` is `null` |
| `<manager name>` | every manager with `state` `not_read`: "not read yet" |
| `managers.json` | the data file could not be read: only pip and npm are listed under `managers`, the reason says why |
| `baseline`, `reference baseline`, `baseline history`, `baseline save` | shared contract, "Baseline" |
| `stable ids`, `stable ids save` | shared contract, "Ids" |
| `summary budget` | the summary exceeds the budget after every package and change was cut |

## Recommendations

This skill gives no block. A recommendation carries `weight`, `kind`,
`risk`, `evidence`, `permissions` and `rollback` as defined in the shared
contract ("Recommendations"); it names a package worth a look only for a
fact of the JSON (`unreadable`, a second entry of one name, `from_baseline`).

# Summary contract, ush-packages (schema_version 1)

The ush-packages fields of the summary and the detail file, and the
ush-packages cases of the shared parts. The shared contract (files and
budget, `sources`, `not_checked`, ids, baseline, recommendations, the report
profile) is in `<plugin root>/skills/ush-common/references/summary-contract.md`;
the report checker reads the ush-packages rules from `data/report-profile.json`.
How the report is written is in `<plugin root>/skills/ush-common/references/report-style.md`
and `references/report-format.md`.

ush-packages reads the packages of the package managers from the files on
disk: through read-only PowerShell jobs, and for winget, VS Code, the .NET
global tools, NuGet and the PowerShellGet modules directly in Python (winget's
tracking catalogs opened read-only and immutable, VS Code's `extensions.json`
read as text, the dotnet tool store and the NuGet global packages folder
listed, each module's `PSGetModuleInfo.xml` read as text; the user's Documents
folder is the `Personal` value of the user's shell folders, read from the
registry read-only). No package manager runs (no pip, npm, winget, VS Code,
dotnet or nuget command and no PowerShell module command), nothing goes
online, and no package is checked for a newer version here: packages are
checked for updates only in an ush-advice run with findings.

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
  `manager` and `key`), the detail lists `pip_packages`, `npm_packages`,
  `pipx_packages`, `uv_tools`, `conda_packages`, `winget_packages`,
  `vscode_extensions`, `dotnet_tools`, `nuget_packages` and `psgallery_modules`
  (every item with its `key`), and
  `summary_file`, the summary of the same run.
- `state/ush-packages.json` (`ush-packages.elevated.json` for an elevated
  run) - the baseline, with the sources `pip_packages`, `npm_packages`,
  `pipx_packages`, `uv_tools`, `conda_packages`, `winget_packages`,
  `vscode_extensions`, `dotnet_tools`, `nuget_packages` and `psgallery_modules`; `state/history/` keeps a day copy of it (shared contract, "Baseline").
- `state/ush-packages.ids.json` - the id map of `k..` and `c..`.

The PowerShell jobs write their results to `work/packages-<stamp>.<job>.json`
and the folders asked for to `work/packages-<stamp>.<job>.input.json`
(`package_folders`, `package_folders-npm`, `package_folders-uv` for the uv
tools' `site-packages`, `pipx_homes`, `uv_tools`, `conda_environments`; raw captures: never read
them). winget's tracking catalogs are read by Python itself (no job, no file
in `work/`): each is opened through SQLite with `mode=ro&immutable=1`, so
nothing is written beside it (no `-journal`, `-shm` or `-wal` file). VS
Code's `extensions.json`, the dotnet tool store, the NuGet global packages
folder and the PowerShell module folders are read by Python too (no job). The
script changes nothing on the machine and
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
| `pip_packages` | the Pythons registered under PEP 514 (`HKCU\Software\Python` once, `HKLM\SOFTWARE\Python` in the 64-bit and the 32-bit view; job `python_registrations`), and for each the `*.dist-info\METADATA` and `*.egg-info\PKG-INFO` files (the first `Name:` and `Version:` header lines) of `<InstallPath>\Lib\site-packages` and of the per-user `%APPDATA%\Python\Python<XY>[-32]\site-packages` (job `package_folders`, layout `python`). pip and python never run. `read` with at least one Python whose folders were looked at, `empty` with none (no registration, or every one skipped without a company or tag, each named in `not_checked`), `unreadable` when the registrations could not be read or no Python was read and one is left from the Microsoft Store or without an InstallPath; a Python without an InstallPath or from the Microsoft Store (not read through another registration of the same `<company>/<tag>`) keeps its packages from the previous baseline (`from_baseline`), also when the status is `unreadable` | `managers.pip`, the `pip` items of `packages`, the detail list `pip_packages` |
| `npm_packages` | the npm global prefix: a non-blank environment variable `NPM_CONFIG_PREFIX` (its name in any case; `.npmrc` is then not read), else the first `prefix=` line of `%USERPROFILE%\.npmrc` (spaces around `=` allowed; job `npmrc`), else `%APPDATA%\npm`; the prefix stays raw, its `%VAR%` expanded by the job `package_folders`; then `name` and `version` of each `<prefix>\node_modules\*\package.json` and `<prefix>\node_modules\@<scope>\*\package.json` (job `package_folders`, layout `npm`; a folder without `package.json`, such as `.bin`, is no package; an empty, `null` or non-object `package.json`, or one without a string `version`, is a package with status `unreadable`). npm never runs. `empty` with no `node_modules` folder (npm not present at the prefix read, `managers.npm.state` `not_present`) or no package in it; `read` with at least one package; `unreadable` when `.npmrc` or the folder could not be read, or when nothing but scope folders that could not be listed came, never `empty` | `managers.npm`, the `npm` items of `packages`, the detail list `npm_packages` |
| `pipx_packages` | the pipx homes: a non-blank environment variable `PIPX_HOME` alone, else `%USERPROFILE%\pipx`, `%USERPROFILE%\.local\pipx` and `%LOCALAPPDATA%\pipx\pipx` (the homes of pipx 1.5+, before 1.3, and 1.3-1.4), in that order (job `pipx_homes`); of each existing home, the `venvs\<venv>\pipx_metadata.json` files: `main_package.package` and `main_package.package_version`, and the `package_version` of each `injected_packages` entry. pipx never runs. `empty` with no home (pipx not present, `managers.pipx.state` `not_present`) or no venv; `read` with at least one item; `unreadable` when a home exists but could not be listed (the previous baseline's items are kept, `from_baseline`). A metadata file that cannot be read or parsed, or lacks a string version, is an item with status `unreadable` (the venv's injected items of the previous baseline are then kept, `from_baseline`). The `shared` folder is no venv | `managers.pipx`, the `pipx` items of `packages`, the detail list `pipx_packages` |
| `uv_tools` | the uv tool folder: a non-blank `UV_TOOL_DIR`, else `%APPDATA%\uv\data\tools` (job `uv_tools`); each subfolder holding `uv-receipt.toml` is a tool, and its `Lib\site-packages` is read as a pip folder (job `package_folders`, layout `python`); the tool's version is that of the `dist-info` / `egg-info` whose PEP 503 name is the tool folder's name (the highest version when there are several). uv never runs. `empty` with no tool folder (uv not present, `managers.uv.state` `not_present`) or no tool; `read` with at least one tool; `unreadable` when the folder exists but could not be listed (the previous baseline's items are kept). A tool without a matching `dist-info` is an item with status `unreadable` ("no dist-info of the tool's package"); a tool whose `Lib\site-packages` could not be listed keeps its previous item (`from_baseline`) | `managers.uv`, the `uv` items of `packages`, the detail list `uv_tools` |
| `conda_packages` | `%USERPROFILE%\.conda\environments.txt`, read whole; each non-blank line is an environment prefix (conda writes one per environment, base included); of each prefix, the `*.json` file names of `<prefix>\conda-meta`, split at the last two `-` into `<name>-<version>-<build>` (one job, `conda_environments`). The file contents are not read; conda never runs. `empty` with no `environments.txt` (conda not present, `managers.conda.state` `not_present`) or no package in any environment; `read` with at least one item or an environment whose `conda-meta` could not be listed; `unreadable` when `environments.txt` exists but could not be read (the previous baseline's items are kept, `from_baseline`). A prefix whose folder is absent gives no item; a prefix without `conda-meta` is read with no item; a prefix whose `conda-meta` could not be listed (or that is not a full path) keeps its previous items (`from_baseline`). A file name that does not split into three non-empty parts is an item with status `unreadable`, never guessed | `managers.conda`, the `conda` items of `packages`, the detail list `conda_packages` |
| `winget_packages` | the tracking catalogs of winget: each subfolder of `%LOCALAPPDATA%\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState` holding `installed.db` is one catalog (the packages winget recorded as installed through it), labelled by the subfolder name, case-folded. Read directly by Python, no job: `%LOCALAPPDATA%` is expanded from the environment (unset: winget not present), and each `installed.db` is opened with SQLite read-only and immutable. Its `metadata` `majorVersion` must be `1` (another value is unreadable: "tracking catalog schema <value> not known", never guessed); `manifest` joined with `ids`, `names` and `versions` gives per id one item with the highest version by dotted number (a tie broken by the version string, then by the highest manifest row) and `versions_recorded`. winget never runs. `empty` with no `LocalState` (winget not present, `managers.winget.state` `not_present`) or no catalog / no package; `read` with at least one item; `unreadable` when `LocalState` exists but could not be listed, or no catalog of it could be read (the previous baseline's items are kept, `from_baseline`). A catalog that cannot be read while another is read keeps its previous items (`from_baseline`, never `removed`); the source stays `read` and compared, and `managers.winget.count` is `null` | `managers.winget`, the `winget` items of `packages`, the detail list `winget_packages` |
| `vscode_extensions` | the VS Code extensions folder: a non-blank environment variable `VSCODE_EXTENSIONS` (its name in any case), else `%USERPROFILE%\.vscode\extensions`; its `extensions.json` (VS Code's list of the installed extensions), read whole. Read directly by Python, no job: `%USERPROFILE%` is expanded from the environment (unset: VS Code not present). Each entry with a string `identifier.id` is an item with the entry's `version`; an entry without a string `version` is an item with status `unreadable`; an entry without a string id cannot be keyed: it is no item and counts in `managers.vscode.unreadable`. The extension folders and `.obsolete` are not read; VS Code never runs. `empty` with no extensions folder (VS Code not present, `managers.vscode.state` `not_present`) or an empty list; `read` with at least one item; `unreadable` when the folder exists but `extensions.json` is missing ("no extensions.json in the extensions folder"), cannot be read, is not JSON, is not a list, or has entries of which none gives a string id (the previous baseline's items are kept, `from_baseline`) | `managers.vscode`, the `vscode` items of `packages`, the detail list `vscode_extensions` |
| `dotnet_tools` | the .NET global tools folder: a non-blank environment variable `DOTNET_CLI_HOME` (its name in any case) + `\.dotnet\tools`, else `%USERPROFILE%\.dotnet\tools`; its tool store `<tools>\.store\<id>\<version>`, listed directly by Python, no job (`%USERPROFILE%` expanded from the environment; unset: dotnet tools not present). Every version folder is complete; entries starting with `.` (`.stage`) are skipped at the id and the version level; an entry that is no folder is no id. Per id one item with the highest version by dotted number (a tie broken by the version string) and `versions_found`; an id folder without a version folder is no item and counts in `managers.dotnet-tools.incomplete`. dotnet never runs. `empty` with no tools folder (dotnet tools not present, `managers.dotnet-tools.state` `not_present`), no `.store` folder or no tool; `read` with at least one item; `unreadable` when the tools or store folder exists but could not be listed (the previous baseline's items are kept, `from_baseline`, never `removed`). An id folder that could not be listed is an item with status `unreadable`, counted in `managers.dotnet-tools.unreadable`, never `incomplete` | `managers.dotnet-tools`, the `dotnet-tools` items of `packages`, the detail list `dotnet_tools` |
| `nuget_packages` | the NuGet global packages folder: a non-blank environment variable `NUGET_PACKAGES`, else `%USERPROFILE%\.nuget\packages`, laid out `<id>\<version>` and listed directly by Python, no job (`NuGet.Config` is not read). A version is complete when its folder holds a file named exactly `.nupkg.metadata` (NuGet writes it after the package is fully extracted; a file `<id>.<version>.nupkg.metadata` does not count). Entries starting with `.` are skipped at the id and the version level. Per id one item with the highest complete version (a tie broken by the version string) and `versions_found` (the complete version folders); an id folder without a complete version is no item and counts in `managers.nuget.incomplete`. nuget and dotnet never run. `empty` with no folder (NuGet not present, `managers.nuget.state` `not_present`) or no package; `read` with at least one item; `unreadable` when the folder exists but could not be listed (the previous baseline's items are kept, `from_baseline`, never `removed`). An id folder that could not be listed, or a version folder whose `.nupkg.metadata` could not be checked, is an item with status `unreadable`, counted in `managers.nuget.unreadable`, never `incomplete` | `managers.nuget`, the `nuget` items of `packages`, the detail list `nuget_packages` |
| `psgallery_modules` | the PowerShell modules installed through PowerShellGet or PSResourceGet, in four module folders, each with a label: `user-windowspowershell` `<Documents>\WindowsPowerShell\Modules`, `user-powershell` `<Documents>\PowerShell\Modules`, `allusers-windowspowershell` `%ProgramFiles%\WindowsPowerShell\Modules`, `allusers-powershell` `%ProgramFiles%\PowerShell\Modules`. `<Documents>` is the raw `Personal` value of `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders` (read-only; expanded from the environment), else `%USERPROFILE%\Documents`. Listed directly by Python, no job; no PowerShell module command runs. A module is `<folder>\<Name>\<Version>\PSGetModuleInfo.xml` (CLIXML, UTF-16 or UTF-8): the elements with attribute `N` `Name`, `Version` and `Repository` under the top-level object's `MS`, whatever their tag. Per module folder one item with the highest parsed version by dotted number (a tie broken by the version string), `versions_found` (the version folders whose file parsed) and the `repository` of that version. A version folder whose file is not XML or lacks `Name` or `Version` is skipped while another version parses, else the item is `unreadable` with the reason. A module folder whose version folders hold no `PSGetModuleInfo.xml` is no item and counts in `managers.psgallery.other_modules`. `empty` with no module folder (PowerShellGet modules not present, `managers.psgallery.state` `not_present`) or no module; `read` with at least one item; `unreadable` when no folder was read and at least one could not be (the previous baseline's items are kept, `from_baseline`). A folder that exists but could not be listed, and the two `user-` folders when the Documents folder could not be read, keep their previous items (`from_baseline`, never `removed`); while another folder is read the source stays read and compared, and `managers.psgallery.count` is `null`. A module folder or a `PSGetModuleInfo.xml` that could not be read is an item with status `unreadable`, counted in `managers.psgallery.unreadable`, never in `other_modules` | `managers.psgallery`, the `psgallery` items of `packages`, the detail list `psgallery_modules` |

## Summary fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version`, `skill`, `generated_at`, `elevated` | | shared contract |
| `sources` | list | see "Sources" |
| `baseline` | object | shared contract, "Baseline": `status` (`none`, `compared`, `unreadable`), `created_at`, `age_days`, `saved`, `reason`, `reference` (`latest` or the `--compare-to` value, e.g. `7d`) and `reference_file` (the history copy compared with, or `null`). `created_at` and `age_days` are those of the state compared with |
| `comparison` | object | per source (`pip_packages`, `npm_packages`, `pipx_packages`, `uv_tools`, `conda_packages`, `winget_packages`, `vscode_extensions`, `dotnet_tools`, `nuget_packages`, `psgallery_modules`): `compared`, `no_baseline` or `not_read` (shared contract). A first run is `no_baseline` and gives no changes. A `not_present` manager's source is `empty`, so it is `compared` (or `no_baseline`), never `not_read`: a manager read before and not present now gives one `removed` change per old item |
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
| `read` | a read manager with `status` `read` or `empty` (`count` `0` when nothing is there) |
| `not_present` | npm, pipx, uv, conda, winget, vscode, dotnet-tools, nuget or psgallery: none of the manager's disk locations exists (for npm: the global `node_modules` folder of the prefix read; for winget: `LocalState`, or `%LOCALAPPDATA%` is unset; for vscode: the extensions folder, or `%USERPROFILE%` is unset; for dotnet-tools: the tools folder `.dotnet\tools`; for nuget: the global packages folder; for both, or `%USERPROFILE%` is unset when no variable names the folder; for psgallery: none of the four module folders, each of them looked at, so never when the Documents folder could not be read). The entry is `{"state": "not_present", "looked_in": [<raw paths>]}`; its source has status `empty`. Not `unreadable` (a location exists but could not be read) and not `read` with `count` `0` (a location exists and is empty) |
| `unreadable` | a read manager with `status` `unreadable` |
| `not_read` | a manager this skill does not read yet; the entry is `{"state": "not_read"}` and `not_checked` has the item `<name>`: "not read yet". It is never "not present" |

`managers.pip` is `{state, status, pythons}`: `status` as the source
`pip_packages`; `pythons` is `[]` when no Python's packages were read: none is
registered, or every registration was skipped for having no company or tag,
each with its `not_checked` entry (`what` `pip_packages registration`), `null`
when the registrations could not be read or no Python was read and one is left
from the Microsoft Store or without an InstallPath, else one entry
per Python read. A Python without an InstallPath has no entry: its `not_checked`
entry has `what` `pip_packages <company>/<tag>` and a reason naming no InstallPath.
Each entry:

| Field | Meaning |
|---|---|
| `python` | `<company>/<tag>` of the PEP 514 registration (`PythonCore/3.12`) |
| `count` | the packages read in both folders; `null` when a folder exists but could not be listed (the folder is in `not_checked`), never `0` |
| `unreadable` | the packages whose metadata file could not be read |
| `folders` | `{install, user}`: `read`, `absent` (the folder does not exist, counted `0`), `unreadable`, or `skipped` (the user folder name is not known from the registration; named in `not_checked`) |

`managers.npm` (not `not_present`) is `{state, status, prefix_from, count, unreadable}`.
With no global `node_modules` folder at the prefix read it is `{"state":
"not_present", "looked_in": ["<prefix>\node_modules"]}` (the prefix raw):

| Field | Meaning |
|---|---|
| `status` | as the source `npm_packages`: `read`, `empty` (the `node_modules` folder exists and holds no package), `unreadable` |
| `prefix_from` | `NPM_CONFIG_PREFIX` (the environment variable), `npmrc` (a `prefix=` line of `%USERPROFILE%\.npmrc`) or `default` (`%APPDATA%\npm`), in that order; `null` when `.npmrc` could not be read |
| `count` | the packages read; `0` for `empty`; `null` for `unreadable` and when a scope folder (`@<scope>`) could not be listed, never `0` |
| `unreadable` | the packages whose `package.json` could not be read; `null` for `unreadable` |

`managers.pipx` (not `not_present`) is `{state, status, homes, count, unreadable}`:
`status` as the source `pipx_packages`; `homes` is one `{folder, status}` per
home looked in (`folder` raw, `status` `read`, `absent` or `unreadable`);
`count` the items read (main and injected packages), `null` for `unreadable`;
`unreadable` the items whose metadata could not be read, `null` for
`unreadable`.

`managers.uv` (not `not_present`) is `{state, status, folder, count, unreadable}`:
`status` as the source `uv_tools`; `folder` the raw tool folder; `count` the
tools read, `null` for `unreadable` and when a tool's folder could not be
listed or checked (named in `not_checked`), never `0`; `unreadable` the tools
without a readable matching `dist-info`, `null` for `unreadable`.

`managers.conda` (not `not_present`) is `{state, status, file, environments,
count, unreadable}`: `status` as the source `conda_packages`; `file` the raw
`environments.txt` path; `environments` one `{label, folder, status}` per
prefix of the file, in file order (`label` the environment label, see "Keys";
`folder` the prefix as written in the file; `status` `read`, `absent` (the
folder does not exist: no item, not unreadable) or `unreadable` (named in
`not_checked`)), `null` for `unreadable`; `count` the packages read, `null`
for `unreadable` and when an environment could not be listed, never `0`;
`unreadable` the file names that do not split, `null` for `unreadable`.

`managers.winget` (not `not_present`) is `{state, status, catalogs, count,
unreadable}`: `status` as the source `winget_packages`; `catalogs` one
`{source, status, count, wal_present, reason}` per catalog, in folder-name
order (`source` the catalog label; `status` `read` or `unreadable`; `count` the
packages read from it, `null` when `unreadable`; `wal_present` `true` when a non-empty
`installed.db-wal` lies beside it, so winget's latest writes may not be seen
(`null` when that could not be checked); `reason` why it could not be read),
`null` when `LocalState` could not be listed; `count` the packages read,
`null` for `unreadable` and while any catalog is unreadable, never `0`;
`unreadable` the ids without a version plus the manifest rows without an id,
`null` for `unreadable`. A partly read winget (one catalog read, another not)
is `state` `read` with `count` `null`.

`managers.vscode` (not `not_present`) is `{state, status, folder_from, count,
unreadable}`: `status` as the source `vscode_extensions`; `folder_from`
`VSCODE_EXTENSIONS` (the environment variable) or `default`
(`%USERPROFILE%\.vscode\extensions`); `count` the extensions read (`0` for an
empty list), `null` for `unreadable`; `unreadable` the entries without a
version plus the entries without an id, `null` for `unreadable`.

`managers.dotnet-tools` and `managers.nuget` (not `not_present`) are `{state,
status, folder_from, count, unreadable, incomplete}`: `status` as the source
`dotnet_tools` / `nuget_packages`; `folder_from` `DOTNET_CLI_HOME` /
`NUGET_PACKAGES` (the environment variable) or `default`
(`%USERPROFILE%\.dotnet\tools` / `%USERPROFILE%\.nuget\packages`); `count` the
ids read (`0` when nothing is there), `null` for `unreadable`; `unreadable` the
ids whose folder could not be read, `null` for `unreadable`; `incomplete` the id
folders without a complete version (no item; for nuget: no `.nupkg.metadata` in
any version folder), `null` for `unreadable`. Not present, either is
`{"state": "not_present", "looked_in": [<raw folder>]}`.

`managers.psgallery` (not `not_present`) is `{state, status, folders, count,
unreadable, other_modules}`: `status` as the source `psgallery_modules`;
`folders` one entry per module folder that exists or could not be looked at,
`{source, status, count, reason}` (`source` the label, `status` `read` or
`unreadable`, `count` the modules read in it or `null`, `reason` why it could
not be read; a folder that does not exist has no entry); `count` the modules
read (`0` when nothing is there), `null` while any folder is `unreadable`;
`unreadable` the modules whose folder or `PSGetModuleInfo.xml` could not be
read or parsed; `other_modules` the module folders without a
`PSGetModuleInfo.xml` (not installed through PowerShellGet: no item); both
`null` for `unreadable`. Not present, it is `{"state": "not_present",
"looked_in": [<raw folders>]}`.

## Packages (`k..`)

`packages` is one flat list over the read managers: pip, npm, pipx, uv, conda,
winget, vscode, dotnet-tools, nuget, psgallery, each by key. Ids `k<n>` are stable between runs (the id map), not places in
the list. A summary item:

| Field | Meaning |
|---|---|
| `id` | `k<n>` |
| `manager` | `pip`, `npm`, `pipx`, `uv`, `conda`, `winget`, `vscode`, `dotnet-tools`, `nuget` or `psgallery` |
| `key` | see "Keys" |
| `name`, `version` | as the metadata says (`Name`/`Version`, `name`/`version`); for a file that could not be read `version` is `null`, and `name` is `null` (pip) or the folder entry (npm) |
| `python` | pip only: `<company>/<tag>` of the Python |
| `venv`, `injected` | pipx only: the venv's folder name, and `true` for a package injected into it |
| `environment` | conda only: the environment label |
| `source` | winget only: the catalog label (its subfolder name of `LocalState`, case-folded) |
| `versions_found` | dotnet-tools, nuget and psgallery only: the complete version folders of the id (psgallery: those whose `PSGetModuleInfo.xml` parsed); `version` is the highest of them; `null` for an unreadable item |
| `module_folder`, `repository` | psgallery only: the label of the module folder (`user-powershell`...) and the repository of the version listed (`PSGallery`, or `null` when the file names none) |
| `folder` | pip: `install` or `user`; npm: the package folder (`<prefix>\node_modules\<name>`, the prefix raw); pipx: `<home>\venvs\<venv>` (the home raw); uv: `<tool folder>\<tool>` (raw); conda: `<prefix>\conda-meta` (the prefix as `environments.txt` writes it, an expanded path); winget: `%LOCALAPPDATA%\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState\<catalog folder>` (raw); vscode: `<extensions folder>\<relativeLocation>` (the folder raw: `VSCODE_EXTENSIONS` as set, or `%USERPROFILE%\.vscode\extensions`), `null` when the entry has no `relativeLocation`; the `name` of a vscode item is its id; dotnet-tools: `<tools>\.store\<id>` (raw: `DOTNET_CLI_HOME` as set + `\.dotnet\tools`, or `%USERPROFILE%\.dotnet\tools`); nuget: `<packages folder>\<id>` (raw: `NUGET_PACKAGES` as set, or `%USERPROFILE%\.nuget\packages`); the `name` of a dotnet-tools or nuget item is its id folder name; psgallery: `<module folder>\<module>` (raw: the Documents folder as the registry or the default writes it, or `%ProgramFiles%`), its `name` the `Name` of the file (the folder name when unreadable) |
| `unreadable`, `reason` | only when the metadata file could not be read: `true` and why |
| `entry` | pip, unreadable only: the `dist-info` / `egg-info` entry |
| `from_baseline` | `true` when the folder could not be read in this run and the item is the previous baseline's |

The items of `packages` in the detail file, and of the detail lists
`pip_packages`, `npm_packages`, `pipx_packages`, `uv_tools`, `conda_packages`,
`winget_packages`, `vscode_extensions`, `dotnet_tools`, `nuget_packages` and `psgallery_modules`, are the
full items: also `status`
(`read` or `unreadable`), `reason`, and `unread_fields` (`["version"]` for an
unreadable file); a conda item also has `build`; a winget item also has `id`
(the package identifier as the catalog writes it) and `versions_recorded`
(the manifest rows of that id in the catalog: winget may keep a row per
version it installed; the item's `version` is the highest of them).

## Keys

| Source | Key |
|---|---|
| `pip_packages` | `pip:<company>/<tag>\|<install / user>\|<name>`, the name normalised by PEP 503 (runs of `-`, `_`, `.` as one `-`) and case-folded; for a file that could not be read the name comes from the folder name. A second entry of the same name in one folder (a stale `dist-info`) gets `\|<entry, case-folded>` added; the plain key goes to the higher version |
| `npm_packages` | `npm:<name>`, case-folded: the install name, i.e. the `node_modules` entry (`left-pad`, `@contoso/tool`), which is the package name; the same key when `package.json` could not be read |
| `pipx_packages` | `pipx:<venv>` for the main package and `pipx:<venv>\|<injected name>` for an injected one, case-folded. A venv name already seen in an earlier home (in the order of "Sources") gets `~2`, `~3`... (`pipx:contoso-cli~2`), so neither item replaces the other. A venv folder keeps the label it had in the previous baseline while no earlier venv took it, so when an earlier one goes away the other keeps its key; a new one takes the first free label |
| `uv_tools` | `uv:<tool folder name>`, case-folded |
| `conda_packages` | `conda:<label>\|<name>`, case-folded; the label is the prefix's last folder name, case-folded (`miniconda3`, `contoso`); a later prefix of the same label (in file order) gets `~2`, `~3`... (`conda:py312~2\|numpy`); a prefix keeps the label it had in the previous baseline while no earlier prefix took it, as for pipx. For a file name that does not split, the name is the file name without `.json`. A second file of the same name in one environment gets `\|<file name, case-folded>` added; the plain key goes to the higher version |
| `winget_packages` | `winget:<catalog label>\|<id>`, case-folded: the label is the catalog's subfolder name, the id the package identifier (`winget:contoso.source\|contoso.tool`) |
| `vscode_extensions` | `vscode:<id>`, case-folded: the extension's `identifier.id` (`vscode:contoso.theme`). A second entry of the same id (not written by VS Code) gets `\|<folder, case-folded>` added, as for npm |
| `dotnet_tools` | `dotnet-tools:<id>`, case-folded: the tool's folder name in the store (`dotnet-tools:contoso.cli`); one key per id, whatever its versions |
| `nuget_packages` | `nuget:<id>`, case-folded: the package's folder name (`nuget:contoso.json`); one key per id, whatever its versions |
| `psgallery_modules` | `psgallery:<label>\|<module>`, case-folded: the module folder's label and the module's folder name (`psgallery:user-powershell\|contoso.az`); one key per module folder, whatever its versions |

## Changes (`c..`)

| Field | Meaning |
|---|---|
| `id` | `c<n>` |
| `key`, `source` | the item that changed |
| `change` | `added`, `removed` or `changed` |
| `name` | the item's name (after the change, or before it for `removed`) |
| `python` | `pip_packages` only: the Python |
| `venv` | `pipx_packages` only: the venv |
| `environment` | `conda_packages` only: the environment label |
| `catalog` | `winget_packages` only: the catalog label (the item's `source`); the change's `source` stays the source name `winget_packages` |
| `module_folder`, `repository` | `psgallery_modules` only: the module folder's label (`user-powershell`...) and the repository of the item; the change's `source` stays the source name `psgallery_modules` |
| `version` | `added` and `removed` only: the version added or removed |
| `fields` | `changed` only: `{version: {before, after}}` |

Changes come by source (pip, npm, pipx, uv, conda, winget, vscode, dotnet-tools,
nuget, psgallery); within a source the order is
added, removed, changed, then by key. Only a source whose `comparison` is
`compared` gives changes. The compared field of every source is `version`;
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
| `pip_packages <company>/<tag> from the Microsoft Store (WindowsApps)` | a registration under the Store's folder; its packages are not read |
| `pip_packages` | the source is `unreadable`: the registrations could not be read, or no Python was read and each one left is a Microsoft Store install or has no InstallPath (their packages are kept from the baseline) |
| `pip_packages <company>/<tag>`, `pip_packages registration` | a registration without company, tag or install path, or a second one with the same company and tag; its packages are not read |
| `pip_packages <company>/<tag> <install / user>` | that folder could not be listed (the Python's `count` is `null`), or the user folder is not known from the registration (`skipped`); its items keep the previous baseline's |
| `npm_packages` | the source is `unreadable`: `.npmrc` or the global `node_modules` folder could not be read (the reason says which); `managers.npm.count` is `null`. A missing `node_modules` is no item of this kind: npm is `not_present` at that prefix (see the next row) |
| `npm global packages under another prefix` | `managers.npm.state` is `not_present` (the global `node_modules` folder of the prefix read, from `NPM_CONFIG_PREFIX`, `.npmrc` or the default, is absent) or `managers.npm.status` is `empty` (that folder holds no package): "the prefixes from the global or builtin npmrc and the folder of node.exe (nvm-windows, zip builds) were not searched". Not added with status `read` or `unreadable` |
| `npm_packages <node_modules folder>\@<scope>` | that scope folder could not be listed (the reason says why); its packages keep the previous baseline's items (`from_baseline`), no `npm:@<scope>` item is listed, and `managers.npm.count` is `null` |
| `pipx_packages` | the source is `unreadable`: a pipx home exists but could not be listed (the reason names it); `managers.pipx.count` is `null` and the previous items are kept |
| `pipx homes outside looked_in` | `managers.pipx.state` is `read` or `not_present`: "a pipx home set by another account's PIPX_HOME, or the default of another pipx version, is not searched" |
| `pipx shared libraries` | `managers.pipx.state` is `read`: the `shared` folder is no venv and is not read |
| `uv_tools` | the source is `unreadable`: the uv tool folder exists but could not be listed |
| `uv_tools <tool>` | that tool's `Lib\site-packages` could not be listed, or whether its folder holds `uv-receipt.toml` could not be checked; its item is kept from the previous baseline (`from_baseline`), never `removed`, and `managers.uv.count` is `null` |
| `uv tools outside looked_in` | `managers.uv.state` is `read` or `not_present`: "a tool folder set by UV_TOOL_DIR in another environment, or under XDG_DATA_HOME, is not searched" |
| `Python installs managed by uv` | `managers.uv.state` is `read`: the Pythons uv installs are not read |
| `conda_packages` | the source is `unreadable`: `environments.txt` exists but could not be read; `managers.conda.count` is `null` and the previous items are kept |
| `conda_packages <label>` | that environment's `conda-meta` could not be listed, or its line is not a full path (the reason names the folder); its items are kept from the previous baseline (`from_baseline`), never `removed`, and `managers.conda.count` is `null`. An absent prefix is no item of this kind (`conda_packages environment`: the job gave a line without a prefix, also with the count `null`) |
| `conda environments outside environments.txt (.condarc envs_dirs, CONDA_ENVS_PATH)` | `managers.conda.state` is `read` or `not_present`: "not searched" |
| `winget_packages` | the source is `unreadable`: `LocalState` exists but could not be listed, or no tracking catalog could be read; `managers.winget.count` is `null` and the previous items are kept |
| `winget_packages <label>` | that catalog could not be read: SQLite or the disk failed, or its schema is not known ("tracking catalog schema <value> not known"); its items are kept from the previous baseline (`from_baseline`), never `removed`, and `managers.winget.count` is `null` |
| `winget_packages <label> rows without an id` | manifest rows of that catalog give no id: they are not read, and counted in `managers.winget.unreadable` |
| `winget records not yet merged into <label>\installed.db` | a non-empty `installed.db-wal` lies beside that catalog (a zero-byte one, left after a checkpoint, is not named) (`wal_present` `true`): "the catalog is read immutable; writes still in its -wal file are not seen" (or whether one lies there could not be checked) |
| `winget records not checked against installed programs` | `managers.winget.state` is `read`: the tracking catalogs list what winget installed and may keep a package removed outside winget |
| `packages installed outside winget` | `managers.winget.state` is `read`: only winget's tracking catalogs are read |
| `vscode_extensions` | the source is `unreadable`: the extensions folder exists but `extensions.json` is missing ("no extensions.json in the extensions folder"), could not be read, is not JSON, is not a list, or none of its entries gives a string id; `managers.vscode.count` is `null` and the previous items are kept |
| `vscode_extensions entries without an id` | entries of `extensions.json` give no string `identifier.id`: the reason gives their number; they are no item, and counted in `managers.vscode.unreadable` |
| `VS Code Insiders, VSCodium and portable VS Code` | `managers.vscode.state` is `read` or `not_present`: only the extensions folder of VS Code is read, not those of other editions or of editors built on VS Code |
| `dotnet_tools` | the source is `unreadable`: the tools folder or its `.store` exists but could not be listed; `managers.dotnet-tools.count` is `null` and the previous items are kept |
| `dotnet_tools <id>` | that tool's folder in the store could not be listed: its item is `unreadable` (no `changed` change), counted in `managers.dotnet-tools.unreadable` |
| `dotnet tool folders without a version` | `managers.dotnet-tools.incomplete` is above 0: "no version folder in the tool's folder of the tool store" |
| `dotnet local tools (tool manifests) and tools installed with --tool-path` | `managers.dotnet-tools.state` is `read` or `not_present`: only the global tool store is read |
| `nuget_packages` | the source is `unreadable`: the global packages folder exists but could not be listed; `managers.nuget.count` is `null` and the previous items are kept |
| `nuget_packages <id>` | that package's folder could not be listed, or whether a version folder holds `.nupkg.metadata` could not be checked: its item is `unreadable` (no `changed` change), counted in `managers.nuget.unreadable` |
| `NuGet package folders without a complete version` | `managers.nuget.incomplete` is above 0: "no .nupkg.metadata in any version folder"; their number is `managers.nuget.incomplete` |
| `NuGet globalPackagesFolder of NuGet.Config, fallback folders and the http-cache` | `managers.nuget.state` is `read` or `not_present`: "not read" |
| `psgallery_modules` | the source is `unreadable`: no module folder could be read and at least one could not be; the previous items are kept |
| `psgallery_modules <label>` | that module folder exists but could not be listed, or (the two `user-` folders) the Documents folder could not be read from the user's shell folders: the reason says which; its previous items are kept (`from_baseline`, never `removed`) and `managers.psgallery.count` is `null` |
| `psgallery_modules <label> <module>` | that module's folder or a `PSGetModuleInfo.xml` of it could not be read, or no version of it parses (not XML, no `Name` or `Version`): its item is `unreadable` (no `changed` change), counted in `managers.psgallery.unreadable` |
| `PowerShell modules not installed through PowerShellGet` | `managers.psgallery.other_modules` is above 0: module folders without a `PSGetModuleInfo.xml` (shipped with Windows or copied by hand) are counted, not listed |
| `PowerShell module folders outside looked_in (PSModulePath)` | `managers.psgallery.state` is `read` or `not_present`: only the four standard module folders are searched |
| `<manager name>` | every manager with `state` `not_read`: "not read yet". A `not_present` manager has no such item and no unreadable item |
| `managers.json` | the data file could not be read: only the read managers (pip, npm, pipx, uv, conda, winget, vscode, dotnet-tools, nuget, psgallery) are listed under `managers`, the reason says why |
| `baseline`, `reference baseline`, `baseline history`, `baseline save` | shared contract, "Baseline" |
| `stable ids`, `stable ids save` | shared contract, "Ids" |
| `summary budget` | the summary exceeds the budget after every package and change was cut |

## Recommendations

This skill gives no block. A recommendation carries `weight`, `kind`,
`risk`, `evidence`, `permissions` and `rollback` as defined in the shared
contract ("Recommendations"); it names a package worth a look only for a
fact of the JSON (`unreadable`, a second entry of one name, `from_baseline`).

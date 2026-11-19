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
  `vscode_extensions`, `dotnet_tools`, `nuget_packages`, `psgallery_modules`,
  `choco_packages`, `scoop_apps`, `vcpkg_packages`, `pnpm_packages`,
  `yarn_packages`, `bun_packages`, `cargo_packages`, `gem_packages` and `composer_packages`
  (every item with its
  `key`), and
  `summary_file`, the summary of the same run.
- `state/ush-packages.json` (`ush-packages.elevated.json` for an elevated
  run) - the baseline, with the sources `pip_packages`, `npm_packages`,
  `pipx_packages`, `uv_tools`, `conda_packages`, `winget_packages`,
  `vscode_extensions`, `dotnet_tools`, `nuget_packages`, `psgallery_modules`,
  `choco_packages`, `scoop_apps`, `vcpkg_packages`, `pnpm_packages`,
  `yarn_packages`, `bun_packages`, `cargo_packages`, `gem_packages` and `composer_packages`;
  `state/history/` keeps a day copy of it (shared contract, "Baseline").
- `state/ush-packages.ids.json` - the id map of `k..` and `c..`.

The PowerShell jobs write their results to `work/packages-<stamp>.<job>.json`
and the folders asked for to `work/packages-<stamp>.<job>.input.json`
(`package_folders`, `package_folders-npm`, `package_folders-uv` for the uv
tools' `site-packages`, `pipx_homes`, `uv_tools`, `conda_environments`; raw captures: never read
them). winget's tracking catalogs are read by Python itself (no job, no file
in `work/`): each is opened through SQLite with `mode=ro&immutable=1`, so
nothing is written beside it (no `-journal`, `-shm` or `-wal` file). VS
Code's `extensions.json`, the dotnet tool store, the NuGet global packages
folder, the PowerShell module folders, the Chocolatey `lib` folder, the
Scoop `apps` folders, the vcpkg status database, the pnpm, yarn and bun global
folders, the cargo `.crates.toml` and the Composer `composer.json` and
`installed.json` are read by Python too (no
job). The
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
| `winget_packages` | the tracking catalogs of winget: each subfolder of `%LOCALAPPDATA%\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState` holding `installed.db` is one catalog (the packages winget recorded as installed through it), labelled by the subfolder name, case-folded. Read directly by Python, no job: `%LOCALAPPDATA%` is expanded from the environment (unset: winget not present), and each `installed.db` is opened with SQLite read-only and immutable. Its `metadata` `majorVersion` must be `1` (another value is unreadable: "tracking catalog schema <value> not known", never guessed); `manifest` joined with `ids`, `names` and `versions` gives per id one item with the highest version by dotted number (a tie broken by the version string, then by the highest manifest row) and `versions_recorded`. winget never runs. `empty` with no `LocalState` (winget not present, `managers.winget.state` `not_present`), with no catalog, or only when every catalog was read and gave no row; `read` when an item was found, a catalog could not be read, or manifest rows gave no id (`managers.winget.unreadable` counts them); `unreadable` when `LocalState` exists but could not be listed, or no catalog of it could be read (the previous baseline's items are kept, `from_baseline`). A catalog that cannot be read while another is read keeps its previous items (`from_baseline`, never `removed`); the source stays `read` and compared, and `managers.winget.count` is `null` | `managers.winget`, the `winget` items of `packages`, the detail list `winget_packages` |
| `vscode_extensions` | the VS Code extensions folder: a non-blank environment variable `VSCODE_EXTENSIONS` (its name in any case), else `%USERPROFILE%\.vscode\extensions`; its `extensions.json` (VS Code's list of the installed extensions), read whole. Read directly by Python, no job: `%USERPROFILE%` is expanded from the environment (unset: VS Code not present). Each entry with a string `identifier.id` is an item with the entry's `version`; an entry without a string `version` is an item with status `unreadable`; an entry without a string id cannot be keyed: it is no item and counts in `managers.vscode.unreadable`. The extension folders and `.obsolete` are not read; VS Code never runs. `empty` with no extensions folder (VS Code not present, `managers.vscode.state` `not_present`) or an empty list; `read` with at least one item; `unreadable` when the folder exists but `extensions.json` is missing ("no extensions.json in the extensions folder"), cannot be read, is not JSON, is not a list, or has entries of which none gives a string id (the previous baseline's items are kept, `from_baseline`) | `managers.vscode`, the `vscode` items of `packages`, the detail list `vscode_extensions` |
| `dotnet_tools` | the .NET global tools folder: a non-blank environment variable `DOTNET_CLI_HOME` (its name in any case) + `\.dotnet\tools`, else `%USERPROFILE%\.dotnet\tools`; its tool store `<tools>\.store\<id>\<version>`, listed directly by Python, no job (`%USERPROFILE%` expanded from the environment; unset: dotnet tools not present). Every version folder is complete; entries starting with `.` (`.stage`) are skipped at the id and the version level; an entry that is no folder is no id. Per id one item with the highest version by dotted number (a tie broken by the version string) and `versions_found`; an id folder without a version folder is no item and counts in `managers.dotnet-tools.incomplete`. dotnet never runs. `empty` with no tools folder (dotnet tools not present, `managers.dotnet-tools.state` `not_present`), no `.store` folder or no tool; `read` with at least one item; `unreadable` when the tools or store folder exists but could not be listed (the previous baseline's items are kept, `from_baseline`, never `removed`). An id folder that could not be listed is an item with status `unreadable`, counted in `managers.dotnet-tools.unreadable`, never `incomplete` | `managers.dotnet-tools`, the `dotnet-tools` items of `packages`, the detail list `dotnet_tools` |
| `nuget_packages` | the NuGet global packages folder: a non-blank environment variable `NUGET_PACKAGES`, else `%USERPROFILE%\.nuget\packages`, laid out `<id>\<version>` and listed directly by Python, no job (`NuGet.Config` is not read). A version is complete when its folder holds a file named exactly `.nupkg.metadata` (NuGet writes it after the package is fully extracted; a file `<id>.<version>.nupkg.metadata` does not count). Entries starting with `.` are skipped at the id and the version level. Per id one item with the highest complete version (a tie broken by the version string) and `versions_found` (the complete version folders); an id folder without a complete version is no item and counts in `managers.nuget.incomplete`. nuget and dotnet never run. `empty` with no folder (NuGet not present, `managers.nuget.state` `not_present`) or no package; `read` with at least one item; `unreadable` when the folder exists but could not be listed (the previous baseline's items are kept, `from_baseline`, never `removed`). An id folder that could not be listed, or a version folder whose `.nupkg.metadata` could not be checked, is an item with status `unreadable`, counted in `managers.nuget.unreadable`, never `incomplete` | `managers.nuget`, the `nuget` items of `packages`, the detail list `nuget_packages` |
| `psgallery_modules` | the PowerShell modules installed through PowerShellGet or PSResourceGet, in four module folders, each with a label: `user-windowspowershell` `<Documents>\WindowsPowerShell\Modules`, `user-powershell` `<Documents>\PowerShell\Modules`, `allusers-windowspowershell` `%ProgramFiles%\WindowsPowerShell\Modules`, `allusers-powershell` `%ProgramFiles%\PowerShell\Modules`. `<Documents>` is the raw `Personal` value of `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders` (read-only; expanded from the environment), else `%USERPROFILE%\Documents`. Listed directly by Python, no job; no PowerShell module command runs. A module is `<folder>\<Name>\<Version>\PSGetModuleInfo.xml` (CLIXML, UTF-16 or UTF-8): the elements with attribute `N` `Name`, `Version` and `Repository` under the top-level object's `MS`, whatever their tag. Per module folder one item with the highest parsed version by dotted number (a tie broken by the version string), `versions_found` (the version folders whose file parsed) and the `repository` of that version. A version folder whose file is not XML or lacks `Name` or `Version` is skipped while another version parses, else the item is `unreadable` with the reason. A module folder whose version folders hold no `PSGetModuleInfo.xml` is no item and counts in `managers.psgallery.other_modules`. `empty` with no module folder (PowerShellGet modules not present, `managers.psgallery.state` `not_present`) or no module; `read` with at least one item, or while one folder could not be listed and another was read; `unreadable` when no folder was read and at least one could not be (the previous baseline's items are kept, `from_baseline`). A folder that exists but could not be listed, and the two `user-` folders when the Documents folder could not be read, keep their previous items (`from_baseline`, never `removed`); while another folder is read the source stays read and compared, and `managers.psgallery.count` is `null`. A module folder or a `PSGetModuleInfo.xml` that could not be read is an item with status `unreadable`, counted in `managers.psgallery.unreadable`, never in `other_modules` | `managers.psgallery`, the `psgallery` items of `packages`, the detail list `psgallery_modules` |
| `choco_packages` | the Chocolatey root: a non-blank environment variable `ChocolateyInstall` (its name in any case), else `%ProgramData%\chocolatey`; each folder of `<root>\lib` holding `<folder>\<folder>.nuspec` is a package, listed directly by Python, no job (`%ProgramData%` expanded from the environment; unset: Chocolatey not present). The nuspec is parsed as XML, any namespace on each element: the text of `metadata/id` and `metadata/version`. Entries starting with `.` (`.chocolatey`) are skipped; an entry that is no folder is no package. A folder without its nuspec is no item and counts in `managers.choco.incomplete`. `lib-bad` and `lib-bkp` are not read. choco never runs. `empty` with no root (Chocolatey not present, `managers.choco.state` `not_present`), no `lib` folder or no package; `read` with at least one item; `unreadable` when the root or `lib` exists but could not be listed (the previous baseline's items are kept, `from_baseline`, never `removed`). A package folder that could not be listed, a folder holding `.chocolateyPending` (an install or upgrade choco has not finished), a nuspec that could not be checked or read, and a nuspec that is not XML or lacks `id` or `version` are an item with status `unreadable`, counted in `managers.choco.unreadable`, never `incomplete` | `managers.choco`, the `choco` items of `packages`, the detail list `choco_packages` |
| `scoop_apps` | the two Scoop roots, each with a label: `user` a non-blank environment variable `SCOOP` (its name in any case), else `%USERPROFILE%\scoop`; `global` a non-blank `SCOOP_GLOBAL`, else `%ProgramData%\scoop`. Each folder of `<root>\apps` is an app, listed directly by Python, no job (`%USERPROFILE%` and `%ProgramData%` expanded from the environment; unset: that root absent). The version is the string `version` of `<app>\current\manifest.json` (read through the `current` junction, never resolved), the bucket the `bucket` of `<app>\current\install.json` (`null` when that file is missing or names none, no error; `null` with a not_checked entry when it could not be read or is not JSON, the item still `read`). Entries starting with `.` are skipped; an entry that is no folder is no app; the folder `scoop` (Scoop's own core) is no app. An app folder without `current`, without `manifest.json`, or whose manifest has no non-blank string `version` is no item and counts in `managers.scoop.incomplete`. `persist`, `cache`, `buckets` and the older version folders beside `current` are not read. scoop never runs. `empty` with neither root (Scoop not present, `managers.scoop.state` `not_present`), no `apps` folder or no app; `read` with at least one item, or while one root could not be listed and the other was read; `unreadable` when no root was read and at least one exists but could not be listed (the previous baseline's items are kept, `from_baseline`). A root (or its `apps`) that exists but could not be listed keeps its previous items (`from_baseline`, never `removed`); while the other root is read the source stays read and compared, and `managers.scoop.count` is `null`. An app folder that could not be listed and a `manifest.json` that could not be read or is not JSON are an item with status `unreadable`, counted in `managers.scoop.unreadable`, never `incomplete` | `managers.scoop`, the `scoop` items of `packages`, the detail list `scoop_apps` |
| `vcpkg_packages` | the classic vcpkg root: a non-blank environment variable `VCPKG_ROOT`, else the first non-blank line of `%LOCALAPPDATA%\vcpkg\vcpkg.path.txt` (written by `vcpkg integrate install`); its status database `<root>\installed\vcpkg\status`, then each file of `<root>\installed\vcpkg\updates` whose name is all digits, in numeric order (any other entry there is not applied). Read directly by Python, no job. Each file is paragraphs separated by blank lines, each of `Field: value` lines (a line starting with a space continues the value); a later paragraph with the same `Package`, `Architecture` and `Feature` replaces an earlier one. The items are the paragraphs without `Feature` whose `Status` ends in ` installed`; the version is `Version`, with `#<Port-Version>` added when `Port-Version` is there and not `0`; an installed paragraph without a `Version` is an item with status `unreadable`, counted in `managers.vcpkg.unreadable`. vcpkg never runs; manifest-mode `vcpkg_installed` folders are not read. `empty` with no root (no variable, no path file or a blank one, or the root absent: vcpkg not present, `managers.vcpkg.state` `not_present`), no status file or no installed package; `read` with at least one item; `unreadable` when `vcpkg.path.txt` exists but could not be read, or the status file, an update file or the `updates` folder exists but could not be read (the previous baseline's items are kept, `from_baseline`, never `removed`; never a partial list) | `managers.vcpkg`, the `vcpkg` items of `packages`, the detail list `vcpkg_packages` |
| `pnpm_packages` | the pnpm global folder `<home>\global`, the home a non-blank environment variable `PNPM_HOME` (its name in any case), else `%LOCALAPPDATA%\pnpm`, read directly by Python, no job (the pnpm rc file is not read). Each folder of the global folder whose name is all digits is a layout folder (a part, labelled by the digits), read as `yarn_packages` reads its global folder; every other entry is named once in `not_checked`. The store `node_modules\.pnpm` and any `node_modules` entry that is not a `dependencies` key is no item; a global package's folder (pnpm's junction into `.pnpm`) is read through, never resolved. pnpm never runs. `empty` with the global folder absent (or `%LOCALAPPDATA%` unset: pnpm not present, `managers.pnpm.state` `not_present`) or no layout folder with a global package; `read` with at least one item, or while one layout folder could not be read and another was (its previous items kept, `from_baseline`); `unreadable` when the global folder exists but could not be listed, or no layout folder could be read and at least one could not be (the previous baseline's items are kept, never `removed`) | `managers.pnpm`, the `pnpm` items of `packages`, the detail list `pnpm_packages` |
| `yarn_packages` | the Yarn classic (v1) global folder: a non-blank environment variable `YARN_GLOBAL_FOLDER` (its name in any case), else `%LOCALAPPDATA%\Yarn\Data\global`, read directly by Python, no job (`.yarnrc` is not read; Yarn Berry has no global packages). Each key of `dependencies` in `<global folder>\package.json` is a global package; its version is the non-blank string `version` of `<global folder>\node_modules\<name>\package.json` (`/` of a scoped name as `\`). Any other `node_modules` entry (a hoisted dependency, `.bin`, a dot entry) is no item. A package whose `package.json` is missing, cannot be read, is not JSON or gives no version is an item with status `unreadable`, counted in `managers.yarn.unreadable`. yarn never runs. `empty` with the global folder absent (or `%LOCALAPPDATA%` unset: yarn not present, `managers.yarn.state` `not_present`), no `package.json` or one without `dependencies`; `read` with at least one item; `unreadable` when the global folder or its `package.json` exists but could not be read, is not a JSON object, or its `dependencies` is not an object (the previous baseline's items are kept, `from_baseline`, never `removed`) | `managers.yarn`, the `yarn` items of `packages`, the detail list `yarn_packages` |
| `bun_packages` | the bun global folder: a non-blank environment variable `BUN_INSTALL_GLOBAL_DIR` (its name in any case), else `<B>\install\global` with `<B>` a non-blank `BUN_INSTALL`, else `%USERPROFILE%\.bun`; read as `yarn_packages` (`bunfig.toml` is not read; bun never runs), each `unreadable` package counted in `managers.bun.unreadable`, `not_present` when the global folder is absent (or `%USERPROFILE%` unset when no variable names it) | `managers.bun`, the `bun` items of `packages`, the detail list `bun_packages` |
| `cargo_packages` | the crates installed with `cargo install`: the install root is a non-blank environment variable `CARGO_INSTALL_ROOT` (its name in any case), else a non-blank `CARGO_HOME`, else `%USERPROFILE%\.cargo`, read directly by Python, no job (the cargo `config.toml` is not read; `.crates2.json` is not read, cargo treats `.crates.toml` as the source of truth). Each key of the `v1` table of `<root>\.crates.toml` (parsed as TOML) is one crate, `<name> <version> (<source>)`: the name the text before the first space (see the key table for a key that could not be split), the version the next token as written (build metadata kept), `source_kind` the text before the first `+` inside the parentheses (`registry`, `sparse`, `git`, `path`; `null` without a `+`). The source URL is never stored. A key without a version or without a `(...)` part is an item with status `unreadable`, counted in `managers.cargo.unreadable`. cargo never runs. `empty` with the root absent (or `%USERPROFILE%` unset when no variable names it: cargo not present, `managers.cargo.state` `not_present`), no `.crates.toml`, or one that is empty or only whitespace; `read` with at least one item; `unreadable` when the root or `.crates.toml` exists but could not be read, is not TOML, or its `v1` is missing or not a table (the previous baseline's items are kept, `from_baseline`, never `removed`) | `managers.cargo`, the `cargo` items of `packages`, the detail list `cargo_packages` |
| `gem_packages` | the installed Ruby gems, read directly by Python, no job (no `gem` or `ruby` command runs). The gem folders (parts), in this order, each with a label: a non-blank environment variable `GEM_HOME` (its name in any case), label `GEM_HOME`; each non-blank `;`-separated entry of `GEM_PATH`, label `GEM_PATH-<n>` (1-based); each subfolder `<abi>` of `%USERPROFILE%\.gem\ruby`, label `user-<abi>`, and of `<XDG_DATA_HOME, else %USERPROFILE%\.local\share>\gem\ruby`, label `xdg-<abi>`; each subfolder `<abi>` of `<InstallLocation>\lib\ruby\gems` of each uninstall key (`HKCU` and `HKLM` in the 64-bit and the 32-bit view, read-only) whose `DisplayName` starts with `Ruby `, label `ruby-<abi>`. A label already used gets `~2`, `~3`; a folder already a part is skipped. A parent folder (`user`, `xdg`, `ruby`, `ruby~2`...) that exists but cannot be listed is itself a part with status `unreadable`. Each `*.gemspec` file of `<part>\specifications` (not of `specifications\default`, Ruby's default gems) is one installed version: name and version from its `# stub: <name> <version> ...` line, else from its `s.name = "..."` and `s.version = "..."` lines; per name one item with the highest version (compared as `Gem::Version` does: a segment with a letter is a prerelease, below the release with the same numbers; a tie broken by the version string) and `versions_found` (distinct versions). A gemspec that cannot be read or gives neither is an item with status `unreadable` keyed by its file name (or makes the gem it belongs to `unreadable`, see the item keys); each such file is counted in `managers.gem.unreadable`. No `specifications` folder: the part is read with no item. `empty` with parts read and no item; `read` with at least one item, or while a part (or the uninstall keys) could not be read and another part was (its previous items kept, `from_baseline`, never over an item of this run or of a label read in this run); `unreadable` when no part was read and at least one (or the uninstall keys) could not be; `empty` with no part found and the uninstall keys read (gem not present, `managers.gem.state` `not_present`) | `managers.gem`, the `gem` items of `packages`, the detail list `gem_packages` |
| `composer_packages` | the global Composer packages: the home is a non-blank environment variable `COMPOSER_HOME` (its name in any case), else `%APPDATA%\Composer`, read directly by Python, no job (`config.json`, `COMPOSER_VENDOR_DIR` and `COMPOSER` are not read). Each key holding `/` of `require` in `<home>\composer.json` is a global package; a key without `/` (`php`, `ext-*`, `lib-*`, `composer-plugin-api`) is a platform requirement, no item. Its version is the non-blank string `version` of the entry of `<home>\vendor\composer\installed.json` (an object with a `packages` list, Composer 2, or a bare list, Composer 1) whose `name` equals it, case-folded; the other entries (dependencies) are no item. A global package with no such entry or no version (or with `installed.json` absent) is an item with status `unreadable`, counted in `managers.composer.unreadable`. composer and php never run. `empty` with the home absent (or `%APPDATA%` unset when `COMPOSER_HOME` does not name it: composer not present, `managers.composer.state` `not_present`), no `composer.json`, or no `require`; `read` with at least one item; `unreadable` when the home, `composer.json` or `installed.json` exists but could not be read, `composer.json` is not a JSON object or its `require` is not an object, or `installed.json` has neither shape (the previous baseline's items are kept, `from_baseline`, never `removed`) | `managers.composer`, the `composer` items of `packages`, the detail list `composer_packages` |

## Summary fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version`, `skill`, `generated_at`, `elevated` | | shared contract |
| `sources` | list | see "Sources" |
| `baseline` | object | shared contract, "Baseline": `status` (`none`, `compared`, `unreadable`), `created_at`, `age_days`, `saved`, `reason`, `reference` (`latest` or the `--compare-to` value, e.g. `7d`) and `reference_file` (the history copy compared with, or `null`). `created_at` and `age_days` are those of the state compared with |
| `comparison` | object | per source (`pip_packages`, `npm_packages`, `pipx_packages`, `uv_tools`, `conda_packages`, `winget_packages`, `vscode_extensions`, `dotnet_tools`, `nuget_packages`, `psgallery_modules`, `choco_packages`, `scoop_apps`, `vcpkg_packages`, `pnpm_packages`, `yarn_packages`, `bun_packages`, `cargo_packages`, `gem_packages`, `composer_packages`): `compared`, `no_baseline` or `not_read` (shared contract). A first run is `no_baseline` and gives no changes. A `not_present` manager's source is `empty`, so it is `compared` (or `no_baseline`), never `not_read`: a manager read before and not present now gives one `removed` change per old item |
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
| `not_present` | npm, pipx, uv, conda, winget, vscode, dotnet-tools, nuget, psgallery, choco, scoop, vcpkg, pnpm, yarn, bun, cargo, gem or composer: none of the manager's disk locations exists (for npm: the global `node_modules` folder of the prefix read; for winget: `LocalState`, or `%LOCALAPPDATA%` is unset; for vscode: the extensions folder, or `%USERPROFILE%` is unset; for dotnet-tools: the tools folder `.dotnet\tools`; for nuget: the global packages folder; for both, or `%USERPROFILE%` is unset when no variable names the folder; for psgallery: none of the four module folders, each of them looked at, so never when the Documents folder could not be read; for choco: the root
(`ChocolateyInstall`, else `%ProgramData%\chocolatey`), or `%ProgramData%` is unset; for scoop:
neither the user root nor the global root, both looked at, `looked_in` the two raw roots; for vcpkg: no
root is named (no `VCPKG_ROOT`, and no `vcpkg.path.txt` or a blank one), or the root named does not
exist, `looked_in` the path file and the root it names; never when `vcpkg.path.txt` could not be
read; for pnpm: the global folder `<home>\global`, or `%LOCALAPPDATA%` is unset when `PNPM_HOME` does
not name the home, `looked_in` the raw global folder; for yarn and bun: the global folder, or `%LOCALAPPDATA%` (yarn) / `%USERPROFILE%` (bun) is
unset when no variable names it, `looked_in` the raw global folder; for cargo: the install root, or
`%USERPROFILE%` is unset when no variable names it, `looked_in` the raw root; for composer: the home,
or `%APPDATA%` is unset when `COMPOSER_HOME` does not name it, `looked_in` the raw home; for gem: no gem
folder exists, `looked_in` the raw `GEM_HOME`, the `GEM_PATH` entries, the two user bases and each
`<InstallLocation>\lib\ruby\gems`; never when the uninstall keys could not be read). The entry is `{"state": "not_present", "looked_in": [<raw paths>]}`; its source has status `empty`. Not `unreadable` (a location exists but could not be read) and not `read` with `count` `0` (a location exists and is empty) |
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

`managers.choco` (not `not_present`) is `{state, status, folder_from, count,
unreadable, incomplete}`: `status` as the source `choco_packages`;
`folder_from` `ChocolateyInstall` (the environment variable) or `default`
(`%ProgramData%\chocolatey`); `count` the packages read (`0` when nothing is
there), `null` for `unreadable`; `unreadable` the package folders whose folder
or nuspec could not be read or parsed, or that hold `.chocolateyPending`, `null`
for `unreadable`; `incomplete`
the package folders without a nuspec (no item), `null` for `unreadable`. Not
present, it is `{"state": "not_present", "looked_in": [<raw root>]}`.

`managers.scoop` (not `not_present`) is `{state, status, roots, count,
unreadable, incomplete}`: `status` as the source `scoop_apps`; `roots` one entry
per root that exists, `{source, status, folder_from, count, reason}`: `source`
the label (`user`, `global`), `status` `read` or `unreadable`, `folder_from` the
variable (`SCOOP`, `SCOOP_GLOBAL`) or `default`, `count` the apps read in that
root (`null` when it could not be listed), `reason` why it could not be listed;
`count` the apps read (`0` when nothing is there), `null` while any root is
unreadable; `unreadable` the apps whose folder or `manifest.json` could not be
read or parsed, `null` for `unreadable`; `incomplete` the app folders without a
current version (no item), `null` for `unreadable`. Not present, it is
`{"state": "not_present", "looked_in": [<the two raw roots>]}`.

`managers.vcpkg` (not `not_present`) is `{state, status, folder_from, count,
unreadable, update_files}`: `status` as the source `vcpkg_packages`; `folder_from`
`VCPKG_ROOT` (the environment variable) or `vcpkg.path.txt`; `count` the
installed packages read (`0` when nothing is there), `null` for `unreadable`;
`unreadable` the installed packages without a `Version`, `null` for `unreadable`;
`update_files` the update files applied after the status file, `null` for
`unreadable`. Not present, it is `{"state": "not_present", "looked_in":
[<the variable's value or the path file, and the root it names>]}`.

`managers.pnpm` (not `not_present`) is `{state, status, folder_from, parts,
count, unreadable}`: `status` as the source `pnpm_packages`; `folder_from`
`PNPM_HOME` or `default`; `parts` one entry per layout folder (each folder of
the global folder whose name is all digits), `{source, status, count, reason}`:
`source` the digits (`5`, pnpm's global layout version), `status` `read` or
`unreadable`, `count` the global packages read in it (`null` when it could not
be read), `reason` why its `package.json` could not be read; `parts` is `null`
when the global folder could not be listed; `count` the global packages read
(`0` when nothing is there), `null` while any part is unreadable; `unreadable`
the global packages whose `package.json` could not be read or gives no version,
`null` for `unreadable`. Not present, it is `{"state": "not_present",
"looked_in": [<the raw global folder>]}`.

`managers.yarn` and `managers.bun` (not `not_present`) are each `{state,
status, folder_from, count, unreadable}`: `status` as the source
`yarn_packages` / `bun_packages`; `folder_from` the variable the global folder
came from (`YARN_GLOBAL_FOLDER`; `BUN_INSTALL_GLOBAL_DIR` or `BUN_INSTALL`) or
`default`; `count` the global packages read (`0` when nothing is there), `null`
for `unreadable`; `unreadable` the global packages whose `package.json` could
not be read or gives no version, `null` for `unreadable`. Not present, each is
`{"state": "not_present", "looked_in": [<the raw global folder>]}`.

`managers.cargo` and `managers.composer` (not `not_present`) are each `{state,
status, folder_from, count, unreadable}`: `status` as the source
`cargo_packages` / `composer_packages`; `folder_from` the variable the root or
home came from (`CARGO_INSTALL_ROOT` or `CARGO_HOME`; `COMPOSER_HOME`) or
`default`; `count` the crates or global packages read (`0` when nothing is
there), `null` for `unreadable`; `unreadable` the crates whose key could not be
split, or the global packages without a version in `installed.json`, `null` for
`unreadable`. Not present, each is `{"state": "not_present", "looked_in": [<the
raw root or home>]}`.

`managers.gem` (not `not_present`) is `{state, status, parts, count,
unreadable}`: `status` as the source `gem_packages`; `parts` one row per gem
folder `{source, status, count, reason}` with `source` its label (`GEM_HOME`,
`GEM_PATH-<n>`, `user-<abi>`, `xdg-<abi>`, `ruby-<abi>`, or `user`, `xdg`,
`ruby` for a parent folder that could not be listed), `status` `read` or
`unreadable`, `count` its gems read (`null` when unreadable); `count` the gems
of every part, `null` while a part or the uninstall keys could not be read;
`unreadable` the gemspec files that could not be read or give no name and
version, `null` for `unreadable`. Not present, it is `{"state":
"not_present", "looked_in": [<raw folders>]}`.

## Packages (`k..`)

`packages` is one flat list over the read managers: pip, npm, pipx, uv, conda,
winget, vscode, dotnet-tools, nuget, psgallery, choco, scoop, vcpkg, pnpm, yarn, bun, cargo, gem, composer, each by key. Ids `k<n>` are stable between runs (the id map), not places in
the list. A summary item:

| Field | Meaning |
|---|---|
| `id` | `k<n>` |
| `manager` | `pip`, `npm`, `pipx`, `uv`, `conda`, `winget`, `vscode`, `dotnet-tools`, `nuget`, `psgallery`, `choco`, `scoop`, `vcpkg`, `pnpm`, `yarn`, `bun`, `cargo`, `gem` or `composer` |
| `key` | see "Keys" |
| `name`, `version` | as the metadata says (`Name`/`Version`, `name`/`version`); for a file that could not be read `version` is `null`, and `name` is `null` (pip) or the folder entry (npm) |
| `python` | pip only: `<company>/<tag>` of the Python |
| `venv`, `injected` | pipx only: the venv's folder name, and `true` for a package injected into it |
| `environment` | conda only: the environment label |
| `source` | winget only: the catalog label (its subfolder name of `LocalState`, case-folded) |
| `versions_found` | dotnet-tools, nuget and psgallery only: the complete version folders of the id (psgallery: those whose `PSGetModuleInfo.xml` parsed); `version` is the highest of them; `null` for an unreadable item |
| `module_folder`, `repository` | psgallery only: the label of the module folder (`user-powershell`...) and the repository of the version listed (`PSGallery`, or `null` when the file names none) |
| `root`, `bucket` | scoop only: the label of the root (`user`, `global`) and the bucket of `install.json` (`main`, or `null` when the file is missing, names none, could not be read or is not JSON) |
| `triplet` | vcpkg only: the `Architecture` of the package (`x64-windows`) |
| `layout` | pnpm only: the label of the layout folder the global package was read from (`5`) |
| `source_kind` | cargo only: the kind of source the crate was installed from, the text before the first `+` inside the parentheses of its `.crates.toml` key (`registry`, `sparse`, `git`, `path`), `null` when there is no `+`; the source URL is never stored |
| `gem_dir` | gem only: the label of the gem folder the gem was read from (`ruby-3.3.0`, `GEM_HOME`); `versions_found` the distinct versions of its gemspec files, `version` the highest |
| `folder` | pip: `install` or `user`; npm: the package folder (`<prefix>\node_modules\<name>`, the prefix raw); pipx: `<home>\venvs\<venv>` (the home raw); uv: `<tool folder>\<tool>` (raw); conda: `<prefix>\conda-meta` (the prefix as `environments.txt` writes it, an expanded path); winget: `%LOCALAPPDATA%\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState\<catalog folder>` (raw); vscode: `<extensions folder>\<relativeLocation>` (the folder raw: `VSCODE_EXTENSIONS` as set, or `%USERPROFILE%\.vscode\extensions`), `null` when the entry has no `relativeLocation`; the `name` of a vscode item is its id; dotnet-tools: `<tools>\.store\<id>` (raw: `DOTNET_CLI_HOME` as set + `\.dotnet\tools`, or `%USERPROFILE%\.dotnet\tools`); nuget: `<packages folder>\<id>` (raw: `NUGET_PACKAGES` as set, or `%USERPROFILE%\.nuget\packages`); the `name` of a dotnet-tools or nuget item is its id folder name; psgallery: `<module folder>\<module>` (raw: the Documents folder as the registry or the default writes it, or `%ProgramFiles%`), its `name` the `Name` of the file (the folder name when unreadable); choco: `<root>\lib\<folder>` (raw: `ChocolateyInstall` as set, or `%ProgramData%\chocolatey`), its `name` the nuspec `id` (the folder name when unreadable); scoop: `<root>\apps\<app>` (raw: `SCOOP` / `SCOOP_GLOBAL` as set, or `%USERPROFILE%\scoop` / `%ProgramData%\scoop`), its `name` the app folder name; vcpkg: `<root>\installed\<triplet>` (the root as `VCPKG_ROOT` or `vcpkg.path.txt` gives it), its `name` the `Package`; pnpm: `<home>\global\<layout>\node_modules\<name>` (the home raw: `PNPM_HOME` as set, or `%LOCALAPPDATA%\pnpm`), its `name` the `dependencies` key; yarn and bun: `<global folder>\node_modules\<name>` (the global folder raw: the variable as set, or the default), its `name` the `dependencies` key; cargo: the install root (raw: the variable as set, or `%USERPROFILE%\.cargo`), its `name` the text of the `.crates.toml` key before the first space, or `unparsed key <n>` for a key that could not be split and whose first word is not a crate name (the key table); composer: `<home>\vendor\<name>` (the home raw: `COMPOSER_HOME` as set, or `%APPDATA%\Composer`), its `name` the `require` key; gem: the gem folder (raw: the variable or uninstall-key value as set, or the default base, + `\<abi>`), its `name` the gemspec's name (the file name without `.gemspec` when unreadable) |
| `unreadable`, `reason` | only when the metadata file could not be read: `true` and why |
| `entry` | pip, unreadable only: the `dist-info` / `egg-info` entry |
| `from_baseline` | `true` when the folder could not be read in this run (winget: the catalog could not be read, or had manifest rows without an id) and the item is the previous baseline's |

The items of `packages` in the detail file, and of the detail lists
`pip_packages`, `npm_packages`, `pipx_packages`, `uv_tools`, `conda_packages`,
`winget_packages`, `vscode_extensions`, `dotnet_tools`, `nuget_packages`, `psgallery_modules`,
`choco_packages`, `scoop_apps`, `vcpkg_packages`, `pnpm_packages`, `yarn_packages`, `bun_packages`, `cargo_packages`, `gem_packages` and `composer_packages`, are the
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
| `choco_packages` | `choco:<lib folder name>`, case-folded (`choco:contoso.cli`); the same key when the nuspec could not be read |
| `scoop_apps` | `scoop:<label>\|<app>`, case-folded: the root's label and the app's folder name (`scoop:user\|git`); the same key when the manifest could not be read |
| `vcpkg_packages` | `vcpkg:<Package>:<Architecture>`, case-folded (`vcpkg:zlib:x64-windows`) |
| `pnpm_packages` | `pnpm:<layout>\|<name>`, case-folded: the layout folder's label and the `dependencies` key (`pnpm:5\|contoso-cli`); the same key when its `package.json` could not be read. A second name differing only in case gets `~2`, `~3`... |
| `yarn_packages` | `yarn:<name>`, case-folded: the `dependencies` key (`yarn:contoso-cli`, `yarn:@contoso/tool`); the same key when its `package.json` could not be read. A second name differing only in case gets `~2`, `~3`... |
| `bun_packages` | `bun:<name>`, case-folded, as for yarn (`bun:contoso-cli`) |
| `cargo_packages` | `cargo:<name>`, case-folded: the crate name of the `.crates.toml` key (`cargo:contoso-cli`); for a key that could not be split, its text before the first space when that is a crate name (letters, digits, `-`, `_`), else `unparsed key <n>` (`<n>` its place in `v1`), so a source URL never becomes a name. A second name differing only in case gets `~2`, `~3`... |
| `gem_packages` | `gem:<label>\|<name>`, case-folded name: the gem folder's label and the gem name (`gem:ruby-3.3.0\|contoso`); for a gemspec that could not be read or gives no name and version, its file name without `.gemspec` (`gem:ruby-3.3.0\|litware-0.1`), unless that file name is `<name>-<digit>...` of a gem read in the same folder: then that gem's item is `unreadable` (its highest version is unknown, never an older one) and the file has no item of its own. A second name differing only in case gets `~2`, `~3`... |
| `composer_packages` | `composer:<name>`, case-folded: the `require` key (`composer:contoso/cli`). A second name differing only in case gets `~2`, `~3`... |

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
| `root`, `bucket` | `scoop_apps` only: the root's label (`user`, `global`) and the item's bucket; the change's `source` stays the source name `scoop_apps` |
| `triplet` | `vcpkg_packages` only: the item's triplet |
| `layout` | `pnpm_packages` only: the item's layout label; the change's `source` stays the source name `pnpm_packages` |
| `source_kind` | `cargo_packages` only: the item's `source_kind` |
| `gem_dir` | `gem_packages` only: the item's gem folder label; the change's `source` stays the source name `gem_packages` |
| `version` | `added` and `removed` only: the version added or removed |
| `fields` | `changed` only: `{version: {before, after}}` |

Changes come by source (pip, npm, pipx, uv, conda, winget, vscode, dotnet-tools,
nuget, psgallery, choco, scoop, vcpkg, pnpm, yarn, bun, cargo, gem, composer); within a source the order is
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
| `winget_packages <label> rows without an id` | manifest rows of that catalog give no id: they are not read, and counted in `managers.winget.unreadable`; a previous package of that catalog not found now is kept `from_baseline`, never `removed` |
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
| `choco_packages` | the source is `unreadable`: the Chocolatey root or its `lib` folder exists but could not be listed; `managers.choco.count` is `null` and the previous items are kept |
| `choco_packages <folder>` | that package folder could not be listed, or its nuspec could not be checked or read, is not XML, or lacks `id` or `version`: its item is `unreadable` (no `changed` change), counted in `managers.choco.unreadable` |
| `choco_packages <folder>` (pending) | the package folder holds `.chocolateyPending`: "<folder>: .chocolateyPending present, the install is not finished"; its item is `unreadable` (never `removed`), counted in `managers.choco.unreadable` |
| `Chocolatey package folders without a nuspec` | `managers.choco.incomplete` is above 0: "no <folder>.nuspec in the package's folder of lib" |
| `Chocolatey lib-bad and lib-bkp folders` | `managers.choco.state` is `read` or `not_present`: "failed and backed-up installs are not read" |
| `scoop_apps` | the source is `unreadable`: no Scoop root could be read and at least one could not be; the previous items are kept |
| `scoop_apps <label>` | that root's `apps` folder exists but could not be listed: the reason says why; its previous items are kept (`from_baseline`, never `removed`) and `managers.scoop.count` is `null` |
| `scoop_apps <label> <app>` | that app's folder could not be listed, or its `manifest.json` could not be read or is not JSON: its item is `unreadable` (no `changed` change), counted in `managers.scoop.unreadable` |
| `scoop_apps <label> <app> install.json` | that app's `current\install.json` exists but could not be read or is not JSON: "<file> could not be read: <error>; bucket unknown" (or "<file>: not JSON: …"); the item stays `read` with `bucket` `null` |
| `Scoop apps without a current version` | `managers.scoop.incomplete` is above 0: "no current\manifest.json with a version in the app's folder" |
| `Scoop core (apps\scoop)` | a root holds `apps\scoop`: "Scoop's own folder is not an app" |
| `vcpkg_packages` | the source is `unreadable`: `vcpkg.path.txt`, the status file, an update file or the `updates` folder exists but could not be read (the reason says which); `managers.vcpkg.count` is `null` and the previous items are kept |
| `vcpkg update entries with a non-numeric name` | an entry of `installed\vcpkg\updates` whose name is not all digits: "not applied: vcpkg names its update files by digits only" |
| `vcpkg_packages <package>:<triplet>` | an installed core paragraph without `Version`: "no Version in the status database"; its item is `unreadable`, counted in `managers.vcpkg.unreadable` |
| `vcpkg manifest-mode vcpkg_installed folders in projects` | `managers.vcpkg.state` is `read` or `not_present`: "only the classic install's status database is read" |
| `pnpm_packages` | the source is `unreadable`: the global folder exists but could not be listed, or no layout folder could be read and at least one could not be (the reason says which); `managers.pnpm.count` is `null` and the previous items are kept |
| `pnpm_packages <layout>` | that layout folder could not be listed, or its `package.json` could not be read, is not a JSON object, or its `dependencies` is not an object: its previous items are kept (`from_baseline`, never `removed`) and `managers.pnpm.count` is `null` |
| `pnpm_packages <layout> <name>` | that global package's `node_modules\<name>\package.json` is missing, could not be read, is not JSON or gives no version: its item is `unreadable` (no `changed` change), counted in `managers.pnpm.unreadable` |
| `pnpm global entries with a non-numeric name` | an entry of the global folder that is not a folder with an all-digit name: "not read: pnpm names its global layout folders by digits only" |
| `pnpm global-dir setting in the pnpm rc file` | `managers.pnpm.state` is `read` or `not_present`: "the config file is not read; only PNPM_HOME and the default are looked at" |
| `yarn_packages`, `bun_packages` | the source is `unreadable`: the global folder or its `package.json` exists but could not be read, is not a JSON object, or its `dependencies` is not an object (the reason says which); `managers.<yarn/bun>.count` is `null` and the previous items are kept |
| `yarn_packages <name>`, `bun_packages <name>` | that global package's `node_modules\<name>\package.json` is missing, could not be read, is not JSON or gives no version: its item is `unreadable` (no `changed` change), counted in `managers.<yarn/bun>.unreadable` |
| `yarn global-folder setting in .yarnrc` | `managers.yarn.state` is `read` or `not_present`: "the config file is not read; only YARN_GLOBAL_FOLDER and the default are looked at" |
| `bun globalDir setting in bunfig.toml` | `managers.bun.state` is `read` or `not_present`: "the config file is not read; only BUN_INSTALL_GLOBAL_DIR, BUN_INSTALL and the default are looked at" |
| `cargo_packages` | the source is `unreadable`: the install root or its `.crates.toml` exists but could not be read, is not TOML, or its `v1` is missing or not a table (the reason says which); `managers.cargo.count` is `null` and the previous items are kept |
| `cargo_packages <name>` | a `.crates.toml` key without a version or without a `(...)` part: "the .crates.toml key could not be split"; its item is `unreadable`, counted in `managers.cargo.unreadable` |
| `cargo install.root setting in config.toml` | `managers.cargo.state` is `read` or `not_present`: "the config file is not read; only CARGO_INSTALL_ROOT, CARGO_HOME and the default are looked at" |
| `gem_packages` | the source is `unreadable`: no gem folder could be read and at least one could not be: "no gem folder could be read" (when only the uninstall keys could not be read and no gem folder exists, the source is `unreadable` with their reason, named once, as `Ruby installs in the uninstall keys`); `managers.gem.count` is `null` and the previous items are kept |
| `gem_packages <label>` | that gem folder, its `specifications` folder, or the parent folder `user`, `xdg`, `ruby` exists but could not be listed: its previous items are kept `from_baseline` (no `removed` change), `managers.gem.count` is `null` |
| `gem_packages <label> <file>` | that gemspec (`<file>` its name without `.gemspec`) could not be read or gives no gem name and version: its item, or the item of the gem it belongs to, is `unreadable`, counted in `managers.gem.unreadable` |
| `Ruby installs in the uninstall keys` | the uninstall keys, or some of them, could not be read (the reason says why and names the keys): the Rubies of the keys read are still looked at, those of the others are not, the previous `ruby-` items are kept `from_baseline`, `managers.gem.count` is `null`, and gem is never `not_present` |
| `Ruby default gems (specifications\default)` | a gem folder was read: "they ship with Ruby" |
| `Ruby installs outside the uninstall keys (portable, MSYS2, Scoop) and uninstall keys without InstallLocation` | every run that reads gem, also when gem is `not_present` or `unreadable`: "not searched; only GEM_HOME, GEM_PATH, the user gem folders and the Rubies of the uninstall keys are looked at" |
| `composer_packages` | the source is `unreadable`: the home, `composer.json` or `vendor\composer\installed.json` exists but could not be read, `composer.json` is not a JSON object or its `require` is not an object, or `installed.json` holds neither a `packages` list nor a list (the reason says which); `managers.composer.count` is `null` and the previous items are kept |
| `composer_packages <name>` | that global package is not in `vendor\composer\installed.json` (or the file is absent), or its entry gives no version: its item is `unreadable` (no `changed` change), counted in `managers.composer.unreadable` |
| `composer vendor-dir setting (config.json, COMPOSER_VENDOR_DIR) and COMPOSER` | `managers.composer.state` is `read` or `not_present`: "only <home>\vendor and composer.json are read" |
| `<manager name>` | every manager with `state` `not_read`: "not read yet". A `not_present` manager has no such item and no unreadable item |
| `managers.json` | the data file could not be read: only the read managers (pip, npm, pipx, uv, conda, winget, vscode, dotnet-tools, nuget, psgallery, choco, scoop, vcpkg, pnpm, yarn, bun, cargo, gem, composer) are listed under `managers`, the reason says why |
| `baseline`, `reference baseline`, `baseline history`, `baseline save` | shared contract, "Baseline" |
| `stable ids`, `stable ids save` | shared contract, "Ids" |
| `summary budget` | the summary exceeds the budget after every package and change was cut |

## Recommendations

This skill gives no block. A recommendation carries `weight`, `kind`,
`risk`, `evidence`, `permissions` and `rollback` as defined in the shared
contract ("Recommendations"); it names a package worth a look only for a
fact of the JSON (`unreadable`, a second entry of one name, `from_baseline`).

# Summary contract, ush-advice (schema_version 1)

The ush-advice fields of the summary and the detail file, the shape of the
findings file the model writes, and the ush-advice cases of the shared parts.
The shared contract (files and budget, `sources`, `not_checked`, ids,
baseline, recommendations, the report profile) is in
`skills/ush-common/references/summary-contract.md`; the report checker reads
the ush-advice rules from `data/report-profile.json`.

The script has no network code. It reads the facts of this machine and
compares them with what the model found online and wrote into the findings
file. It does not check that a finding is true; it checks the file's shape,
whether each address is on a domain of `data/sources.json`, and how each
finding compares with the machine.

## Files and output

One run of `scripts/advice.py` writes to `<data dir>` (the data directory:
`--data-dir`, else `USH_DATA_DIR`, else `%LOCALAPPDATA%\ubershipshape`, made
absolute at once; see the shared contract):

- `work/advice-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text
  is printed on stdout. The time in the name is UTC.
- `work/advice-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `sources`, `searches`,
  `machine`, `comparison`, the full lists `updates`, `exploited`,
  `firmware` and `issues` (never truncated), `kev_other`, `query_warnings`
  and `findings` (every finding as written, with `domain` and `listed`).
- `state/ush-advice.json` - the baseline (see "Baseline").

The PowerShell jobs write their results to `work/advice-<stamp>.<job>.json`
(raw captures: never read them). The script changes nothing on the machine
and never runs elevated jobs.

Exit codes: `0` the run finished, also when jobs failed or searches were
not read; `2` a usage error, `data/products.json` or `data/sources.json`
unreadable or of the wrong shape, or a findings file of the wrong shape (the
message names the entry, counted from 0). The data files and the findings
file are checked before any PowerShell runs and before anything is written.

`--detail <id>` prints the item with that id from the newest
`advice-*.detail.json` in `<data dir>/work/` (or from `--detail-file
<path>`, the summary's `detail_file`) and exits 0; an unknown id, or no
detail file, exits 1. It does not start PowerShell. Ids: `u..` updates,
`k..` exploited (`exploited` and then `kev_other`, one numbering), `f..`
firmware, `i..` issues, `w..` findings.

## Sources

`sources` is a list of `{name, status, reason}`, one per job, in this order:

| Source | What is read | Gives |
|---|---|---|
| `os_version` | `DisplayVersion`, `CurrentBuild`, `UBR`, `EditionID` of `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion` (not `ProductName`), and the processor architecture (`PROCESSOR_ARCHITEW6432`, else `PROCESSOR_ARCHITECTURE`) | `machine` version fields, `product` |
| `hotfixes` | `HotFixID` of every `Get-HotFix` row; not the computer name, not the install date | `machine.hotfixes` |
| `firmware` | `Manufacturer`, `Model` of `Win32_ComputerSystem`; `SMBIOSBIOSVersion`, `ReleaseDate` (`yyyy-MM-dd`, UTC) of `Win32_BIOS`. Never the serial number, the UUID or the computer name | `machine.firmware` |

A job that fails is `unreadable` and gives `null` in its fields and an item
`job <name>` in `not_checked`. `hotfixes` `empty` is `[]` and no item.
`os_version` `empty` (no row) gives `null` fields and an item; `firmware`
`empty` gives `machine.firmware` `null` as a whole, and an item.

## Top-level fields

Besides the shared fields (`schema_version`, `skill`, `generated_at`,
`sources`, `not_checked`, `summary_file`, `detail_file`, `truncated`):

| Field | Type | Meaning |
|---|---|---|
| `truncated` | int | `issues` items cut from the end of the summary |
| `truncated_exploited` | int | `exploited` items cut from the end of the summary |
| `baseline` | object | the shared baseline object, see "Baseline" |
| `comparison` | object | `{updates, exploited, firmware, issues}`, each `compared`, `no_baseline` or `not_read` |
| `searches` | list or `null` | the state of each search, see "Searches"; `null` without `--findings` |
| `machine` | object | the facts of this machine, see "Machine" |
| `query_warnings` | list or `null` | see "Query warnings"; `null` without `--findings` |
| `kev_other_count` | int or `null` | KEV findings whose CVE is in no update month (they are only in the detail file's `kev_other`); `null` when `exploited` is `null` |
| `updates` | list or `null` | one item per month, newest first; `null` unless the search `release-info` is `read` |
| `exploited` | list or `null` | KEV findings inside the update months; `null` unless `kev`, `msrc` and `release-info` are all `read` |
| `firmware` | list or `null` | firmware findings; `null` unless the search `firmware` is `read` |
| `issues` | list or `null` | known issues; `null` unless the search `release-health` is `read` |

A list is `null` (never `[]`) when its search was not read; `[]` is a search
that was read and found nothing. Without `--findings` all four lists,
`searches`, `query_warnings` and `kev_other_count` are `null`, and
`not_checked` has the item `web search`.

## Machine

| Field | Meaning |
|---|---|
| `display_version` | e.g. `25H2`, or `null` |
| `build` | `CurrentBuild` as text, e.g. `"26200"`, or `null` |
| `ubr` | `UBR` as an int, or `null` |
| `edition_id` | e.g. `Core`, or `null` |
| `architecture` | e.g. `AMD64`, or `null` |
| `product` | the MSRC product name from `data/products.json` for the key of `display_version` and `architecture` joined by a vertical bar, or `null` |
| `product_reason` | why `product` is `null` (a part not read, or the key not in the map), else `null` |
| `hotfixes` | sorted upper-case update ids (`KB...`), `[]` when none, `null` when not read |
| `firmware` | `{manufacturer, model, bios_version, bios_date}` (each may be `null`), or `null` when not read |

An `os_version` or `firmware` row with an empty field gives an item
`os_version fields` or `firmware fields` naming it; `hotfixes` rows without
an id are left out with an item `hotfixes rows`.

## The findings file

`--findings <path>` reads `{"searches": [...], "findings": [...]}`, exactly
these two keys, both lists. The model writes it to
`<data dir>\work\advice-findings-<YYYYmmdd-HHMMSS>.json`.

Each `searches` entry has exactly `id`, `status` and `reason`:

- `id`: `release-info`, `msrc`, `kev`, `release-health` or `firmware`, each at most once;
- `status`: `read`, `partial` (a cut or incomplete document) or
  `unreadable` (the fetch or search failed);
- `reason`: text or `null`; required for `partial` and `unreadable`.

Each `findings` entry has the common fields and the fields of its `kind`,
and no others:

| Field | Shape |
|---|---|
| `kind` | `update`, `exploited`, `firmware` or `issue` |
| `url` | an `https://` address with a host name |
| `title` | non-empty text |
| `query` | the WebSearch query as text, or `null` for a WebFetch |
| `published` | `yyyy-MM-dd` or `null` |

| Kind | Fields |
|---|---|
| `update` | `month` (`yyyy-MM`), `kb` (`KB` and digits), `fixed_build` (`10.0.<build>.<UBR>` as in CVRF, or `<build>.<UBR>` as the "OS Build" of a KB page; nothing else), `release_type` (`security` or `preview`), `cves` (a list of `{cve, severity}`: `CVE-yyyy-n` and text or `null`; or `null` for a row of the `release-info` table, which gives no CVEs) |
| `exploited` | `cve`, `vendor`, `product` (texts), `date_added` (a date), `due_date` (a date or `null`), `ransomware` (text or `null`) |
| `firmware` | `manufacturer`, `model`, `version` (texts), `release_date` (a date or `null`) |
| `issue` | the common fields only |

Any other shape, an unknown `kind` or a `fixed_build` of another form exits
2 with the entry's number.

## Searches

`searches` has five items `{name, status, reason}`, in the order
`release-info`, `msrc`, `kev`, `release-health`, `firmware`. `status` is the one from the file, or
`missing` when the file has no entry for it. A search that is not `read`
gives a `null` list and an item `search <id>` in `not_checked`; its findings
stay only in the detail file's `findings`.

| Search | List |
|---|---|
| `release-info` | `updates` (months, KBs, fixed builds) |
| `msrc` | no list of its own: the CVE counts of the months (`cve_count`, `critical_count`), and `exploited` together with `kev` |
| `kev` | `exploited` (also needs `msrc` and `release-info`) |
| `release-health` | `issues` |
| `firmware` | `firmware` |

`kev` `read` with `msrc` or `release-info` not `read` gives `exploited`
`null` and an item `exploited`: there is no CVE list of the months (`msrc`
not read) or no update months (`release-info` not read) to put the KEV
findings in.

## Findings (detail file)

Every finding of the file, in its order, with the id `w<n>`, its fields
(KB and CVE in upper case, texts stripped), `domain` (the host of `url`)
and `listed`: `true` when `domain` equals a domain of `data/sources.json`
or is a subdomain of one. For a `firmware` finding the domains of the
`firmware_domains` entries whose `manufacturer_prefix` starts the
manufacturer of this machine count too.

## Updates items

One per `month` of the `update` findings, newest first:

| Field | Meaning |
|---|---|
| `id` | `u<n>` |
| `month` | `yyyy-MM` |
| `kbs` | the month's KBs, sorted |
| `fixed_builds` | the month's fixed builds as `<build>.<UBR>`, sorted (security and preview) |
| `cve_count` | the distinct CVEs recorded in the month's findings (what was written down, not what the month fixed); `null` when `msrc` is not `read` or no finding of the month has a `cves` list, and with `msrc` `read` such months are named in an item `updates cve_count` |
| `critical_count` | those of them with a severity `Critical` in any finding; `null` when `cve_count` is |
| `listed` | `true` only when every finding of the month is listed |
| `kb_installed` | the `kbs` that are in `machine.hotfixes`; `null` when `hotfixes` is `null` (item `updates kb_installed`). Information only: `Get-HotFix` does not see every package |
| `applied` | `true`, `false` or `null`, see below |
| `applied_reason` | why `applied` is `null`, else `null` |
| `new` | see "Baseline" |

`applied` takes only the `security` findings of the month (a `preview`
release is optional). A fixed build of another build number than
`machine.build` is left out. The machine's (build, UBR) at or above every
remaining fixed build gives `true`, below every one `false`, in between
`null` ("mixed"). No security fixed build ("no security release"), none for
this build ("build mismatch") or `build` or `ubr` not read gives `null` and
an item `updates applied` in `not_checked`; never `false`.

## Exploited items

KEV findings, one per CVE (a repeated CVE keeps its first finding), whose
CVE is in the `cves` of some update finding:

| Field | Meaning |
|---|---|
| `id` | `k<n>` |
| `cve`, `vendor`, `product`, `date_added`, `due_date`, `ransomware` | from the finding |
| `url`, `listed` | from the finding |
| `in_updates` | `true` here |
| `month` | the earliest month whose findings name the CVE |
| `applied` | `true` when any such month has `applied` `true` (updates are cumulative), else the `applied` of the earliest month |
| `new` | see "Baseline" |

A KEV finding whose CVE is in no month goes to the detail file's
`kev_other` with the same fields (`in_updates` `false`, `month` and
`applied` `null`), its id continuing the `k` numbering after `exploited`;
the summary gives only `kev_other_count`. The script never guesses the
product from its name.

## Firmware items

One per manufacturer, model and version (a repeat keeps its first finding):

| Field | Meaning |
|---|---|
| `id` | `f<n>` |
| `manufacturer`, `model`, `version`, `release_date`, `url`, `listed` | from the finding |
| `model_matches` | manufacturer and model equal those of `machine.firmware`, ignoring case; `null` when they were not read |
| `same_version` | the whole `version`, or a part of it (split at characters outside `[0-9A-Za-z.]`) that holds a digit and either a dot or at least five characters, equals (ignoring case and a leading `v`) the whole `bios_version`, one of its parts, or the last dotted part of one; a shorter part such as a family code (`T70`) or a piece of a date (`20`) never matches alone, unless it is the only part that holds a digit (`BIOS 312`); `null` when `bios_version` was not read |
| `newer` | `false` when `same_version`; else `release_date` > `bios_date`; `null` when `model_matches` is not `true`, a date is missing or the version was not read |
| `new` | see "Baseline" |

Version texts are never compared as numbers.

## Issues items

One per `url` and `title` of the `issue` findings (one release
health page lists several issues; a repeat keeps its first finding): `id` (`i<n>`), `title`,
`published`, `url`, `listed`, `new`.

## Query warnings

`query_warnings` is a list of `{finding_id, reason}`, one per finding and
reason, never with the query itself. A fact is also found after one `v`
(`v1.54`) when no letter or digit stands before that `v`:

- `build`: the `query` or `url` holds `<build>.<UBR>` or
  `10.0.<build>.<UBR>` of this machine as a whole token, or the `query`
  holds `<build>-<UBR>`, or the `url` holds `<build>-<UBR>` once the KB
  page names are cut out of its path (only the path, before `?` or `#`):
  the KB (with `KB` or digits only) of an `update` finding or of
  `machine.hotfixes`, then `-` or `/`, one or more words that each hold a
  letter and end in `-` (`os-build-`, `os-builds-`, or the translated words
  of a localized page), then a five-digit build with its UBR, and at most
  one more after one word: `<KB>-os-build-<build>-<UBR>`,
  `<KB>/os-build-<build>-<UBR>`,
  `<KB>-os-builds-<build>-<UBR>-and-<build2>-<UBR2>`,
  `<KB>-kompilacja-systemu-operacyjnego-<build>-<UBR>`: a KB page names the
  builds of its KB that way;
- `bios_version`: the `query` or `url` holds the whole version of the BIOS
  of this machine, or one of its parts, as a whole token, ignoring case;
  the whole version and each part count only with at least four characters
  and a digit (`1.0` or `324` alone gives no warning);
- `kb`: the `query` holds a KB of `machine.hotfixes` that is the `kb` of no
  `update` finding.

Each item also gives an item `query warning <finding_id>` in
`not_checked`. `[]` means no warning.

## Budget

The summary stays within 35 000 characters. `issues` is cut from its end
first; only when the summary without any issue is still too long is
`exploited` cut from its end. `truncated` and `truncated_exploited` count
the items cut, and `not_checked` gets an item `issues cut from the summary`
or `exploited cut from the summary`. The detail file has every item.

## Baseline

`state/ush-advice.json`, a normal (non-elevated) baseline only. Sources and
keys:

| Source | Key |
|---|---|
| `updates` | `month` |
| `exploited` | `cve` (of `exploited` and `kev_other`) |
| `firmware` | `manufacturer`, `model` and `version` joined by a vertical bar, in lower case |
| `issues` | `url` and `title` (case ignored) |

A saved `issues` source keyed by `url` alone (an older baseline) is dropped: issues
are `no_baseline` for that run, so no issue comes back as new.

Every item has `new`: `null` unless its list's `comparison` is `compared`,
then `true` for a key not in the baseline and `false` otherwise. The saved
baseline holds the union of the keys of every run, so a key seen once is
never `new` again, also after a run that did not find it. A list that is
`null` (`comparison` `not_read`) keeps its saved keys. A run in which no
list could be built (no search read, or only `kev`, only `msrc`, or both read, since
`exploited` also needs a read `release-info`) does not write the baseline: `baseline.saved` is `false`
and `baseline.reason` says so, with no `not_checked` item. An unreadable
baseline (item `baseline`) or a failed save (item `baseline save`) is
reported as in the shared contract. After an unreadable baseline the new
baseline holds only the keys of this run, and a copy of the old file stays
next to it (`ush-advice.unreadable-<UTC stamp>.json`); keys seen only before it
come back as `new` `true` in a later run, since the lost file cannot say
what was seen.

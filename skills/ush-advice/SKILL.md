---
name: ush-advice
description: Check this Windows machine against what Microsoft, CISA and the hardware manufacturer publish - whether the latest monthly security update is installed (by build and UBR), whether known exploited vulnerabilities fixed in those updates are patched here, whether the manufacturer offers a newer BIOS, and which known issues Windows release health lists - and what is new since the last check. Use when the user asks whether Windows is up to date, whether the machine is patched against exploited vulnerabilities, whether there is a newer BIOS, or what known problems the current Windows version has. The only ush skill that goes online, and only the model does: a script reads the machine facts and compares the model's findings with them; read-only, it installs nothing.
---

# ush-advice

A script reads the facts of this machine without any network: the Windows
version, build and UBR, edition, architecture, the MSRC product name, the
installed update ids, and the manufacturer, model, version and date of the
BIOS. You then fetch the sources of `data/sources.json` and search the web
with general queries, write what you found into a findings file, and run the
script again with `--findings`. It checks the file's shape, marks every
finding as from a listed source or not, compares the findings with the
machine (is the month's update applied, is an exploited vulnerability fixed
here, is there a newer BIOS) and remembers what it saw before. You judge and
write a Markdown report; the user decides what to act on.

## When to use

- The user asks whether Windows is up to date, or whether the latest
  security update is installed.
- The user asks whether the machine is patched against vulnerabilities that
  are exploited in the wild.
- The user asks whether the manufacturer has a newer BIOS for this machine.
- The user asks what known issues the installed Windows version has, or
  what is new in advice since the last check.

Not for: installing updates or a BIOS, running Windows Update, Office, Edge,
.NET or drivers, the update history and failures of this machine
(`ush-health`), settings (`ush-settings`), installed programs
(`ush-inventory`). Say so if the user asks for these.

## Rules

- **Only you go online, never the script.** Use WebFetch on the addresses
  of `data/sources.json` (`release-info`, `msrc`, `kev`, `release-health`)
  and WebSearch for
  the rest (the BIOS page of the manufacturer, a KB page). No upload, no
  online tool that takes a file, nothing from this machine sent anywhere.
- **A query holds only facts shared by every such machine**: `Windows 11`,
  the version (`25H2`), the architecture (`x64`), the month (`2026-09`);
  for firmware also the manufacturer and the model from
  `machine.firmware`.
- **A query or a fetched address never holds** the build with its UBR
  (`26200.6899`, also written `26200-6899`) that you put there yourself, a KB number read from this machine, the BIOS version, the
  serial number, the computer name or the account name. The script reads no
  serial number and no computer name, so this rule is yours to keep.
- **Public ids taken from a fetched source may be used.** A KB or CVE you
  read in an MSRC document, the `release-info` table or a KB page may go
  into a query or an address; a KB that you know only from
  `machine.hotfixes` may not. The script warns about a KB of this machine
  in a query unless it is the `kb` of an `update` finding, so put into a
  query only a KB that is the `kb` of one of your `update` findings; never
  record a finding only to use its KB in a query.
- **An address taken from a fetched source may be fetched as it is**: a
  link from the `release-info` table, the MSRC document or a search result,
  even when the name of a KB page holds the build of that KB
  (`...-kb5099901-os-build-26200-6899-...`). The script gives no `build`
  warning for the hyphen form only in a KB page name, in the path of the
  address, that joins the KB of an `update` finding or a KB of
  `machine.hotfixes` (OOB and hotpatch items too) to its builds
  (`kb5099901-os-build-26200-6899`,
  `kb5099901-os-builds-26200-6899-and-26100-6899`, or the translated words
  of a localized page, `kb5099901-kompilacja-systemu-operacyjnego-26200-6899`);
  a search address with a
  KB and the build, or the build again elsewhere in the address, still
  warns. That silence is no permission: the KB in the address still comes
  from a fetched source, and a KB that you know only from
  `machine.hotfixes` may not go into an address.
- **Every finding goes into the `--findings` file.** A finding that is not
  in the file does not go into the report, not even as a remark.
- **A finding from outside the list is unverified.** The script marks it
  `listed: false`; the report puts it in the "Unverified" section (in a
  Polish report "Niezweryfikowane", not to be confused with "Nie sprawdzono"),
  never as a fact.
- **A search that failed or returned a cut document is never `read`.** In
  `searches` it has the status `unreadable` (with the error) or `partial`
  (with what was cut), so its list is `null`, never `[]`.
- **kev is checked only for the CVEs of your `update` findings**, one
  question per CVE about the KEV catalogue (it is too large to read whole).
  A CVE has an answer only when the fetch says it is listed, or says it is
  not listed in a document it read to the end. "Not listed" from a cut or
  summarised document, or a fetch that cannot say whether it saw the whole
  feed, is no answer. `kev` is `read` only when every one of those CVEs got
  an answer; otherwise it is `partial`.
- **release-info is `read` only when the release history table of
  `machine.display_version` was read to the end.** When
  `machine.display_version` is `null`, record no `update` finding from it
  and give `release-info` the status `unreadable` with the reason.
- **msrc is `read` only when the whole document was read**: WebFetch
  returned the month's MSRC (CVRF) document whole, neither cut nor
  summarised (it says so, and the last entry of its `Vulnerability` list is
  there), and you collected the CVEs for `machine.product` from every entry.
  The document gives no CVE count per product, so a count you make yourself
  proves nothing on its own. Otherwise it is `partial`.
  Today the month's CVRF document is larger than the WebFetch limit: when
  WebFetch fails on it, `msrc` is `unreadable` with that error; when it
  returns the document cut or summarised, `msrc` is `partial`. When `machine.product` is
  `null` there is no product to count for: record no `update` finding from
  the MSRC document and give `msrc` the status `unreadable` with
  `product_reason` as its reason. Unless `msrc` is `read`, record no
  `update` finding from the MSRC document at all: its months, KBs and
  builds come only from `release-info`.
- **Read only the summary JSON.** Never open the raw captures in
  `<data dir>/work/`. Single items come from `--detail <id>`.
- **The data directory.** `<data dir>` below is where the script writes:
  `--data-dir` when given, else `USH_DATA_DIR` (an absolute path), else
  `%LOCALAPPDATA%\ubershipshape`. Take its absolute value from the summary's
  `summary_file` (the directory above `work/`). In the report text outside
  code blocks write it as `&lt;data dir>` in plain text, never the expanded
  path: it contains the account name (`references/report-format.md`).
- **Every number in the report comes from the JSON**: from the summary, or
  from a detail item you fetched with `--detail` and named in the report's
  `<!-- ush:detail ... -->` line. A number you read on a web page reaches
  the report only through the findings file and the script's summary. The
  digits of a `title`, `url` or `query` back no number.
- **`applied` is decided by the build, not by the KB list.** `Get-HotFix`
  does not see every package, so `kb_installed` is information only.
  `applied` `null` is "not known", never "missing".
- **`newer` comes from the version first, then the date.** A BIOS with
  `newer` `null` is "not known"; never compare BIOS versions yourself.
- **Every recommendation carries** `weight`, `kind`, `risk`, `evidence`,
  `permissions` and `rollback`, as defined in the shared contract
  `skills/ush-common/references/summary-contract.md` ("Recommendations").
  The skill never installs anything: the user does, and you read the state
  back with a new run.
- **Empty is not unreadable.** A `null` list, a search not `read`, a job
  `unreadable`, a `query_warnings` item, a comparison `not_read` or
  `no_baseline`, or `truncated` > 0 must be reported as such (see the
  degradation cases in `references/report-format.md`), never as "none" or
  "up to date".

## Steps

1. From the project root run, in a normal (non-elevated) shell, without
   flags:

   ```
   python -B skills/ush-advice/scripts/advice.py
   ```

   It prints the summary JSON on stdout (the field meanings are in
   `references/summary-contract.md`). Note `machine.display_version`,
   `machine.architecture`, `machine.product` and `machine.firmware`
   (manufacturer and model); these are what your queries may use.

2. Fetch and search, following the rules above:
   - `release-info`: WebFetch the `url` of the source `release-info` in
     `data/sources.json` and find the release history table of
     `machine.display_version`. For each month you record (at least the
     newest month with a `B` row), write one `update` finding per `B` or
     `D` row of that month: `month` from the update type column, `B` ->
     `release_type` `security`, `D` -> `preview`, `kb`, the "Build" column
     as `fixed_build`, `cves` `null` and the page as `url`. Skip OOB rows
     and the hotpatch calendar table; take rows only from the table of
     `machine.display_version`.
   - `msrc`: WebFetch the `url` of the source `msrc` in `data/sources.json`, then the
     CVRF document of each month you check (the latest month at least).
     First check that the whole document was read and collect the CVEs it
     lists for `machine.product`; that sets the status of `msrc` (see the
     rules). Only when `msrc` is `read`, record for
     `machine.product` the KB, the fixed build, the release type and the CVEs
     with their severity as `update` findings; otherwise record nothing from
     the document, only the status of `msrc` with its reason. Skip hotpatch
     and out-of-band KBs, as in the `release-info` step.
   - `kev`: when no `update` finding has a CVE, do not ask; give `kev` the
     status `unreadable` with the reason "no `update` finding has a CVE".
     Otherwise, for each CVE of your `update` findings, ask the KEV catalogue
     address of `data/sources.json` whether it lists that CVE and whether
     the document it read was complete; record each listed one. A "not
     listed" from a document that was not read to the end makes `kev`
     `partial` (see the rules).
   - `release-health`: WebFetch the release health address and find the
     known issues of `machine.display_version`.
   - `firmware`: WebSearch for the BIOS page of the manufacturer and the
     model (no version, no serial number) and record the newest BIOS it
     offers. In the finding, `manufacturer` and `model` are copied exactly
     from `machine.firmware`, and a marketing name from the page goes only
     into `title`; `version` is the version alone as the page writes it
     (`312`, `F.21`), without words such as "BIOS" or "Version" and
     without a date.

3. Write what you found to
   `<data dir>\work\advice-findings-<YYYYmmdd-HHMMSS>.json` (UTC time), in
   the shape of "The findings file" in `references/summary-contract.md`:
   one entry in `searches` for each of the five searches `release-info`,
   `msrc`, `kev`, `release-health` and `firmware`, with the status `read`, `partial` (a cut document, with what
   was cut as the reason) or `unreadable` (with the error as the reason),
   and every finding in `findings`.

4. Run the script again with the file:

   ```
   python -B skills/ush-advice/scripts/advice.py --data-dir "<absolute data dir>" --findings "<absolute path of the findings file>"
   ```

   `<absolute data dir>` is the one of step 1 (the directory above `work/`
   in its `summary_file`), so both runs use the same baseline.

   Exit 2 names the entry of the file that has the wrong shape: correct the
   file and run again. Check `query_warnings`: an item means a query or an
   address held a fact of this machine; tell the user which finding and
   why, and keep that fact out of every later query.

   For an item you need in full (a finding's query, a KEV entry outside the
   update months, an item cut from the summary), fetch it:

   ```
   python -B skills/ush-advice/scripts/advice.py --detail <id> --detail-file <detail_file>
   ```

   Ids: `u..` months, `k..` exploited vulnerabilities (also those outside
   the update months, in `kev_other`), `f..` firmware, `i..` known issues,
   `w..` the findings as written. Remember every id you fetched and used.

5. Write the report in the language the user addressed you in, following
   `references/report-format.md`, and save it as
   `<data dir>/reports/advice-<YYYY-MM-DD-HHMM>.md` (local time of the run).
   The first line is `<!-- ush:summary <summary_file> -->` with the absolute
   `summary_file` path from the summary of step 4. Then run:

   ```
   python -B skills/ush-common/scripts/check_report.py "<absolute data dir>/reports/advice-<YYYY-MM-DD-HHMM>.md"
   ```

   (`--latest --skill ush-advice` checks the newest `advice-*.md` instead.)
   Correct the report and run the check again until it prints `OK`. `OK`
   means each number occurs somewhere in the JSON, not that it is used for
   the right thing, so the rules above still bind you. Do not hand the
   report to the user before it prints `OK`. Then tell the user where the
   report is and give the main findings in a few lines.

6. After the user says they installed an update or a BIOS, repeat steps 1-5
   with a new findings file. The read-back is the new summary: the month
   has `applied` `true`, or the BIOS finding has `newer` `false`. A message
   from Windows Update or the BIOS tool is not a read-back.

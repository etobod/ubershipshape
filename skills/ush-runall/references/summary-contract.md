# Summary contract, ush-runall (schema_version 1)

The ush-runall fields of the summary and the detail file, and the ush-runall
cases of the shared parts. The shared contract (files, `sources`,
`not_checked`, ids, recommendations, the report profile) is in
`<plugin root>/skills/ush-common/references/summary-contract.md`; the report checker reads
the ush-runall rules from `data/report-profile.json`.

## Files and output

One run of `scripts/runall.py` writes to `<data dir>` (the data directory:
`--data-dir`, else `USH_DATA_DIR`, else the plugin data folder (`--default-data-dir`), made
absolute at once; see the shared contract):

- `work/runall-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text
  is printed on stdout. The time in the name is UTC.
- `work/runall-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `summary_file` (the summary of
  the same run), `children` (one item per child with its full summary),
  `firewall_ports` (every matched rule, no limit), `firewall_ports_counts`,
  `network_categories`, `driver_update_links`, `link_counts`,
  `decisions`, `accepted`, `accepted_counts`, `review` (every review item,
  no limit) and `review_counts`.

Each child writes its own summary, detail file, baseline and id map to the
same `<data dir>`, as in a run of its own; `runall` keeps no baseline.

The script changes nothing on the machine itself and starts no PowerShell;
the children do what their own contracts say. It exits 0 when the pass ran,
also when children failed, timed out or gave bad output. It exits 2 (no
child run, nothing written) when `data/children.json` is not usable, and on
a usage error.

## Children

`data/children.json` is an ordered list of `{skill, script, timeout_s}`:
`skill` the full name (`ush-health`), `script` a bare file name resolved to
`skills/<skill>/scripts/<script>`, `timeout_s` a positive integer of at
most 86400 (one day). The ids
follow the order of the file, `h1` for its first entry. The repository
order is `ush-health`, `ush-events`, `ush-settings`, `ush-inventory`,
`ush-processes`, `ush-files`, `ush-advice`, `ush-packages`, so the ids are
`h1` to `h8` in that order. The file is not usable (exit 2) when it
cannot be read or is not a non-empty list, or an entry:

- has a key other than `skill`, `script`, `timeout_s`, or misses one;
- has a `skill` not of the form `ush-<lowercase letters>`, or `ush-runall`;
- has a `script` with `/`, `\` or `..`, not of the form `<letters>.py`, or
  `logs.py` or `dumps.py` (they change the disk or a log);
- has a `timeout_s` that is not a positive integer, or is over 86400;
- resolves to a path outside `skills/`;
- repeats a skill, or puts `ush-processes` before `ush-inventory`
  (`ush-processes` reads the `ush-inventory` baseline).

Each child is run without a shell, one at a time, with exactly
`[<python>, -B, <absolute script path>, --data-dir, <data dir>]`: no other
flag is ever passed on. A child that does not finish within its
`timeout_s` is stopped with every process it started before the next child
starts.

Status of a child:

| `status` | Condition |
|---|---|
| `ok` | exit code 0, and stdout is a JSON object whose `skill` is the entry's skill |
| `failed` | another exit code (the reason gives the code and the last line of stderr), or the child could not be run at all (the reason gives the exception type and text, e.g. `OSError`) |
| `timeout` | the child did not finish within `timeout_s`; the reason says whether stopping the processes it started was confirmed, or that one of them may still be running |
| `bad_output` | exit code 0, but stdout is not JSON, not a JSON object, or names another skill |

A status other than `ok` gives one `not_checked` item and the pass goes on.

## Top-level fields

Besides the shared fields (`schema_version`, `skill` `"ush-runall"`,
`generated_at`, `sources`, `not_checked`, `summary_file`, `detail_file`,
`truncated`):

| Field | Type | Meaning |
|---|---|---|
| `duration_s` | number | the whole pass in seconds, one decimal place |
| `counts` | object | children per status, only the statuses that occur, in the order `ok`, `failed`, `timeout`, `bad_output` (`{"ok": 7}`) |
| `children` | list | one item per child, ids `h1`... in run order (see below) |
| `firewall_ports` | list or `null` | the matched firewall rules, ids `w1`..., at most 50 (see "Firewall rules and listening ports"); `[]` when no rule matched; `null` when the comparison was not made |
| `firewall_ports_counts` | object or `null` | the counters of the comparison; `null` when it was not made |
| `network_categories` | object or `null` | a copy of `network_categories` of the `ush-processes` summary (network profiles counted per category, `{"Private": 1}`); `null` when that child is not `ok` or its summary has no such value |
| `driver_update_links` | list or `null` | pending driver updates linked to driver packages no present device uses, ids `y1`... (see "Pending driver updates and driver packages no present device uses"); `[]` when nothing links; `null` when a side was not read |
| `link_counts` | object or `null` | `{linked, updates_without_package, packages_without_update}`; `null` with `driver_update_links` `null` |
| `decisions` | list or `null` | one item per decision of `<data dir>/decisions.json`, ids `j1`... (see "The user's decisions"); `[]` when there is no file; `null` when the file cannot be used (one `not_checked` item names `decisions.json`) |
| `accepted` | list or `null` | one item per entry of `<data dir>/state/accepted.json`, ids `a1`... (see "Accepted findings"); `[]` when there is no file; `null` when the file or the kinds file cannot be used (one `not_checked` item names `accepted.json`) |
| `accepted_counts` | object or `null` | `{quiet, back, gone, not_checked}`: the `accepted` items per state, every state present (`0` when none); `null` with `accepted` `null` |
| `review` | list or `null` | the review items, ids `r1`..., at most 50 (see "Review dates"); `[]` when no program or package is listed and the file has no entry; `null` when `<data dir>/state/review-dates.json` cannot be used (one `not_checked` item names `review-dates.json`) |
| `review_counts` | object or `null` | `{due, no_decision, gone, not_checked, not_due, no_limit}`: every review item per state (the detail file's list, never cut), every state present (`0` when none); `null` with `review` `null` |
| `truncated_review` | int | `review` items cut from the summary by the limit of 50, from the end of the order; `0` when none (also when `review` is `null`). The detail file has them all |
| `truncated` | int | `firewall_ports` items cut from the summary by the limit of 50, from the end of the order; `0` when none. The detail file has them all |

The summary holds no child summary and is cut nowhere else; `runall`
reports no `elevated` of its own (each child item carries the child's).

`sources`: one entry per child, in run order:
`{name, id, script, status, reason}`, where `name` is the skill, `id` its
`h` id, `status` `read` for `ok` and `unreadable` otherwise, and `reason`
`null` for `ok`, else the reason of the child's status.

## Child items (`children`, ids `h..`)

| Field | Meaning |
|---|---|
| `id` | `h1`... in run order; a place in this run's list |
| `skill` | the child's skill |
| `status` | `ok`, `failed`, `timeout` or `bad_output` |
| `exit_code` | the child's exit code; `null` when it timed out or could not be run |
| `duration_s` | the child's run time in seconds, one decimal place (measured by `runall` when the child timed out or could not be run) |
| `summary_file` | the child's `summary_file`; `null` unless `ok` |
| `not_checked_count` | the number of items in the child's own `not_checked`; `null` unless `ok` (or when that is not a list) |
| `truncated` | the child's own top-level `truncated`; `null` unless `ok` or when the child has none |
| `elevated` | the child's own `elevated`; `null` unless `ok` or when the child gives none (`ush-events` gives none) |

The child's `not_checked` entries are not copied into the `runall`
`not_checked`: they are in its `h` item, counted by `not_checked_count`.

The detail file's `children` items have `id`, `skill`, `status` and
`summary`: the child's full summary as it printed it, or `null` when the
status is not `ok`. Read it with that skill's own
`references/summary-contract.md`. The ids inside it (`ush-inventory s11`,
`ush-events g3`) are the child's ids; the report checker knows only the
`h`, `w` and `y` ids of `runall`, so the digits of a child id are checked as
numbers and are backed when its `h` item is named in `ush:detail`.

## Firewall rules and listening ports (`firewall_ports`, ids `w..`)

After the children, `runall` sets the active inbound Allow firewall rules
against the TCP listening ports. It reads the detail files that the
`ush-inventory` and `ush-processes` summaries name in `detail_file`; nothing
on the machine is read. The comparison is made only when both children are
`ok`, both detail files can be read, the `ush-inventory` source
`firewall_rules` and the `ush-processes` source `tcp_listeners` are `read`
or `empty`, and the detail files hold the lists `additions` (inventory) and
`groups` and `ports` (processes). Otherwise `firewall_ports` and
`firewall_ports_counts` are `null` and `not_checked` has one item naming
each missing input. A comparison without a match gives `[]`, never `null`.

The rules are the items of `additions` with `kind` `firewall_rule`, `dir`
`In`, `action` `Allow` and `active` `TRUE` (text, any case; an `active` that
is not text leaves the rule out). Each such rule counts in
`inbound_rules` and in exactly one other counter, checked in this order:

| Counter | Rule |
|---|---|
| `udp` | `protocol` 17 (the ports of `ush-processes` are TCP only) |
| `other_protocol` | `protocol` neither `null` nor 6 |
| `not_compared` | `app` empty, not text (a list from a repeated key), `System` (any case: the kernel has no file) or still holding `%` after the environment variables are expanded; `svc` not empty (a service rule: `svchost.exe` hosts many services, so its path does not say which one listens); or an `lport` element that is not `*`, a number or a range `a-b` (`RPC`, `RPC-EPMap`, `IPHTTPSIn`, `Teredo`, ...); or a non-empty `lport2` (the rule's `LPort2_*` keys, whose ports and keywords are not read) |
| `matched` | the expanded `app` (case-insensitive) is the `path` of a listening port's group, and `lport` covers the port's `local_port`: `null` (any port), `*`, a number, a range, or a list one of whose elements covers it |
| `not_listening` | every other rule: no listening port of its program on a port it covers |

So `inbound_rules` = `matched` + `not_listening` + `not_compared` + `udp`
+ `other_protocol`. Environment variables are expanded with the environment
of the account that runs `runall`.

A port whose group is missing or has no `path` is not compared and counts
in `ports_without_path`. A port without a whole-number `local_port` is
left out without a count.

`firewall_ports_counts`:
`{inbound_rules, matched, not_listening, not_compared, udp,
other_protocol, ports_without_path}`.

Each `firewall_ports` item, one per `matched` rule, in the order of the
number after `x` in the rule's id (the `w` ids are places in this run's
list):

| Field | Meaning |
|---|---|
| `id` | `w1`... |
| `rule` | the rule as `ush-inventory x<n>` |
| `rule_name` | the rule's `name` |
| `program_path` | the rule's `app` with the environment variables expanded (a path: its digits back no number) |
| `lport` | the rule's `lport` as read: text, a list of texts, or `null` (any port) |
| `protocol` | 6 (TCP) or `null` (any protocol) |
| `profile` | the rule's `profile` as read: text such as `Private`, a list from a repeated key, or `null` (every profile) |
| `app_exists` | the rule's `app_exists` from `ush-inventory`; `null` when it has none |
| `listening` | the matched ports: `{port, local_address, local_port, scope}`, `port` as `ush-processes p<n>`, `scope` `all`, `address` or `loopback` |
| `loopback_only` | `true` when every matched port has `scope` `loopback`, else `false` |

The summary lists at most 50 items; `truncated` counts the rest, which are
in the detail file under the same `w` ids. `--detail w51` prints one.

## Pending driver updates and driver packages no present device uses (`driver_update_links`, ids `y..`)

After the children, `runall` reads `pending_updates` of the `ush-health`
detail file and `driver_packages` of the `ush-inventory` detail file (named
by the children's `detail_file`); nothing on the machine is read. The links
are made only when both children are `ok`, both detail files can be read,
the `ush-health` source `pending_updates` and the `ush-inventory` sources
`driver_packages` and `devices` (the source of `device_state`) are `read` or `empty`, and the detail files hold the lists
`pending_updates` and `driver_packages`. Otherwise `driver_update_links` and
`link_counts` are `null` and `not_checked` has one item naming each side
that was not read. Nothing linked gives `[]`, never `null`.

Only updates of `type` `driver` and packages whose `device_state` is
`non_present` (only a disconnected device names the package) or
`no_device_found` (no device found without administrator rights) take
part; `present` or `null` (the state was not judged) never links. An update and a package
link when both hold:

- the update's `driver_provider` and the package's `provider` are equal
  after case-folding, or are in one `providers` group of the table
  `data/driver-link-aliases.json` (a group works in both directions);
- the update's `driver_class` and the package's `class` are equal after
  case-folding, or the package's class is in the `inf` list of the
  update's class in the table's `classes` (one way only: Windows Update
  class to INF class).

An update or package without a provider or class links to nothing. Names are
never matched by similarity: a provider that only contains the other
(`Contoso` and `Contoso Ltd`) does not link unless a table line pairs them,
nor does a package of the same provider and another class. Each line of the
table names the run that showed the pair (`seen`). When the table is missing,
is not JSON or has a wrong shape (a list that is not a list, an `inf` or
`names` that is not a list of names, a group of fewer than two names, a name
in two groups, a Windows Update class twice), only equal names link and
`not_checked` gets one item naming the file and the reason. Each pair is one item, in the
order of the updates, then of the packages:

| Field | Meaning |
|---|---|
| `id` | `y1`... |
| `update` | the update as `ush-health q<n>` |
| `package` | the package as `ush-inventory o<n>` |
| `provider` | the update's `driver_provider` |
| `driver_class` | the update's `driver_class` |
| `package_provider` | the package's `provider` |
| `package_class` | the package's `class` |
| `provider_via` | `equal` when the two providers are equal after case-folding, `table` when a provider group of `driver-link-aliases.json` paired them |
| `class_via` | `equal` when the two classes are equal after case-folding, `table` when a class line of `driver-link-aliases.json` paired them |
| `title` | the update's `title` |
| `original_name` | the package's `original_name` |
| `package_state` | the package's `device_state`: `non_present` or `no_device_found` |
| `package_group` | the package's `group` (from `ush-inventory`'s `data/driver-package-groups.json`), `null` when the groups were not read |
| `package_no_device_by_nature` | the package's `no_device_by_nature`: `true` for a filter or antivirus package that never has a device of its own, `null` when the groups were not read |

`link_counts`: `linked` the number of `y` items, `updates_without_package`
the pending driver updates that link to no package, and
`packages_without_update` the packages with `device_state` `non_present` or
`no_device_found` that link to no update; a package with `device_state`
`present` or `null` counts nowhere. The detail file holds the same list; `--detail y1`
prints one item.

## The user's decisions (`decisions`, ids `j..`)

After the children, `runall` reads `<data dir>/decisions.json` with the
shared `decisions` module (`<plugin root>/skills/ush-common/scripts/decisions.py`; its
`setting` checks validated against the settings catalogue) and gives each
decision one item, the same in the summary and the detail file:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `j1`... in the order of the file |
| `decision` | string | the decision's id, `D<n>` |
| `state` | string | `kept`, `broken` or `not_checked` |
| `evidence` | list | `{skill, id}` of each child item the checks read or hit; on a `broken` item only those of its broken checks; a vendor folder adds `folder` and `root` (its `id` may be `null`) |
| `reason` | string or `null` | why a check was not made, one part per check; on a `broken` item, what a check could not read besides its hits (a vendor folder root not read) |
| `text`, `made`, `source` | string | copied from the decision |

A `setting` check reads the `ush-settings` detail item of its catalogue
entry: `matches` is `kept`, `differs` is `broken`; any other state, an item
measured against another expectation than the decision's, a missing item or
a child that is not `ok` is `not_checked`. A `vendor_absent` check compares
its `name`, case-folded and exact, with the detail files of this pass,
never the cut summaries:

| `match` | Lists (sources that must be read) |
|---|---|
| `publisher` | `ush-inventory` `programs` `publisher` (`win32_programs`, `msix_programs`) |
| `provider` | `ush-inventory` `driver_packages` and `drivers` `provider` (`driver_packages`, `drivers`), `ush-health` `pending_updates` `driver_provider` (`pending_updates`) |
| `folder` | `ush-inventory` `vendor_folders` `name`, matched ones included (`vendor_folders`; a root of `vendor_folder_roots` not `read` leaves the check `not_checked` unless a folder under a read root hits, which is `broken` with that root in `reason`) |

Every hit is evidence and makes the check `broken`; with no hit it is
`kept` only when every list was read, else `not_checked` (an empty list of
an unread source is not "no hit"). A decision is `broken` when any check
is, `kept` only when every check is, and `not_checked` otherwise.

## Accepted findings (`accepted`, ids `a..`)

After the decisions, `runall` reads `<data dir>/state/accepted.json` with the
shared `accepted` module (`<plugin root>/skills/ush-common/scripts/accepted.py`,
validated against `<plugin root>/skills/ush-common/data/accepted-kinds.json`)
and gives each entry one item, the same in the summary and the detail file:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `a1`... in the order of the file |
| `kind` | string | `update`, `autostart`, `event_group` or `firewall_rule` |
| `key` | string or list | the entry's key, as stored |
| `state` | string | `quiet`, `back`, `gone` or `not_checked` |
| `changed` | list | on `back`, one `{field, accepted, now}` per watched field that brings it back; a field under a target fact is named `facts[<path>].<field>`; `[]` otherwise |
| `skipped` | list | the watched fields (named as in `changed`) not compared because a side was null or not read; on `back` they are the fields beside `changed` that were not checked; `[]` otherwise |
| `evidence` | string or `null` | `"<skill> <id>"` of the child item matched in this pass; `null` when no item matched or the detail was not read |
| `accepted_on` | string | the date the entry was accepted, copied |
| `reason` | string or `null` | on `not_checked`, why; `null` otherwise |

Per entry the kinds file names the child skill, its detail section, an
optional `match` on the item, the key and the child `source` that must have
been read. The item is looked up in that child's detail file of this pass,
never its cut summary:

- the child not `ok`, its detail file unreadable or without the section,
  or the named source missing or not `read`/`empty`: `not_checked`, with
  the reason;
- no item with the same key: `gone`;
- several items with the same key (an `update` key, title and hresult,
  matches every failure group with them): the one with the latest `last`;
- an item whose own values were not read in this pass (`facts_from_baseline`
  true, a target fact with `check_error`, or a non-empty `unread_fields`):
  `not_checked`; carried values are never compared;
- otherwise each watched field is compared as the kinds file says
  (`changed`: any other value; `rises`: a larger number; `later`: a later
  UTC time); a field under `facts[]` per target fact present on both sides,
  by `path`. A `null` on one side (or a value that cannot be compared) is
  not compared: with no other change the item is `not_checked` naming those
  fields, never `back` and never `quiet`. Any change gives `back`, else
  `quiet`.

The script sets no threshold. `--detail a1` prints one item.

Entries are added and removed only on the user's word (`SKILL.md` step 10),
each with this pass's `runall` detail file:

- `accepted.py --accept "<skill> <id>" --detail-file <detail_file>` adds the
  entry of a child item the report cites; an entry with the same kind and
  key is replaced. A `back` item is accepted again with its `evidence`,
  never with `ush-runall a<n>`.
- `accepted.py --remove "ush-runall a<n>" --detail-file <detail_file>` reads
  item `a<n>` of `accepted` in that detail file and removes the entry with
  its `kind` and `key`, through the same verified write. Removing the last
  entry leaves `{"schema_version": 1, "entries": []}`.
- `--accept`, `--remove` and `--undo` are mutually exclusive and one is
  required; `--detail-file` is required with `--accept` and `--remove` and
  not taken with `--undo` (else a usage error, exit 2). Both `--accept` and
  `--remove` print `{ok, key, kind, path}`; a
  refusal (for `--remove`: a target not `ush-runall a<n>`, an id not in
  `accepted`, `accepted` `null`, a key no longer in `accepted.json`, or an
  unreadable `accepted.json`) prints `ok` `false` with `reason`, exits 1
  and writes nothing.
- The report's line of a `gone` item suggests `--remove` in words.
- A result may also carry `warning` (with `ok` `true`): the new file is
  saved, but `accepted.previous.json` was not replaced, so `--undo` does not
  restore the state before this write. Tell the user so.
- Rollback of either command: `accepted.py --undo` (with `--data-dir`, no
  `--detail-file`), the only undo, run on the user's word; no file under
  `state/` is copied or deleted by hand. Each write keeps the file before it
  as `<data dir>/state/accepted.previous.json` (one generation, through
  `baseline.save_json`); the first write ever first writes an empty accepted
  file, so its previous generation is "no accepted findings". `--undo`
  checks that file as `accepted.json` is checked, writes it back through
  the same verified write (the current file becomes the previous
  generation, so a second `--undo` goes back again), reads the result back
  and prints `{ok, entry_count, path}`, `warning` as above; with no
  previous file, or one that cannot be used, or an unreadable
  `accepted.json`, it prints `ok` `false` with
  `reason`, exits 1 and writes nothing. It restores only the state before
  the last write. `--accept` again is not an undo (it stores this pass's
  facts and date); a removed `gone` or `not_checked` entry cannot be
  accepted again from this pass, and after another write it is lost for
  good.

## Review dates (`review`, ids `r..`)

After the accepted findings, `runall` reads `<data dir>/state/review-dates.json`
with the shared `review_dates` module
(`<plugin root>/skills/ush-common/scripts/review_dates.py`). The file holds
`{"schema_version": 1, "entries": [...]}`, one entry per decision of the user:
`{kind, key, name, decided_on, period, review_on}`, `kind` `program` or
`package`, `name` a string or `null`, `period` `<N>d`, `<N>m`, `<N>y` or
`none`, the dates ISO `YYYY-MM-DD` local dates (`review_on` `null` for
`none`). Two entries with the same kind and key, or any other bad shape,
make the file unusable. No file means no decision yet.

The lists come from the child detail files of this pass, never their cut
summaries:

| Key prefix | `kind` | Child, detail list | Source |
|---|---|---|---|
| `win32:` | `program` | `ush-inventory` `programs` | `win32_programs` |
| `msix:` | `program` | `ush-inventory` `programs` | `msix_programs` |
| `pip:` | `package` | `ush-packages` `packages` | `pip_packages` |
| `npm:` | `package` | `ush-packages` `packages` | `npm_packages` |

One item per program whose `own` is not `true` (`null` counts as not
`true`) and per package, one per entry of a listed `own: true` program
(a Windows part without an entry gets none), and one per entry whose key
is in no list. The same item in the summary and the detail file:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `r1`... in the order of the list (below) |
| `kind` | string | `program` or `package` |
| `key` | string | the child's key (or the entry's, for an item in no list) |
| `name` | string or `null` | the child item's name; the entry's for an item in no list; `null` for a pip package whose metadata was not read |
| `state` | string | see below |
| `decided_on`, `period`, `review_on` | string or `null` | copied from the entry; `null` without one |
| `reason` | string or `null` | on `not_checked`, why; `null` otherwise |

States:

- `not_checked` (with the reason): the child not `ok`, its detail file
  unreadable or without the list, or the key's source missing or not
  `read`/`empty`; or the item was carried from the baseline
  (`from_baseline`, its source was not read in this pass), with an entry
  or without; or an entry whose key is in no list while the child's
  `not_checked` (summary or detail file) names a part of that source it
  could not read (`what` the source name, or the source name and a space:
  `win32_programs key ...`, `pip_packages <python> <folder>`,
  `npm_packages <folder>\<scope>`). Such an entry is never `gone`; any
  partial skip of a source covers every missing key of it. An entry whose
  key has none of the prefixes, or whose kind does not fit its prefix, is
  also `not_checked`.
- `gone`: an entry whose key is in no list (`own: true` programs included)
  and whose source was read whole.
- `no_decision`: a listed item without an entry.
- `no_limit`: an entry with period `none`.
- `due`: `review_on` is the local date of the run or earlier; `not_due`:
  later. The local date is `review_dates.local_date(now)`
  (`now.astimezone().date()`), the date the writer stores as `decided_on`.

Order: `due`, `no_decision`, `gone`, `not_checked`, `not_due`, `no_limit`,
then by `kind` and `key`; the summary keeps the first 50 and counts the rest
in `truncated_review`. `review_counts` counts every item. The script
compares the user's dates only and sets no threshold. `--detail r1` prints
one item.

## not_checked

Besides the shared cases:

- The accepted findings file not usable: `what` "the user's accepted
  findings (accepted.json)", `reason` why the file or the kinds file cannot
  be used, followed by "no accepted finding was checked".
- The review dates file not usable: `what` "the user's review dates
  (review-dates.json)", `reason` why it cannot be used, followed by "no
  review item was made".

- A child not `ok`: `{what, id, status, reason}`, `what`
  `"<skill> (<script>)"`, `id` its `h` id, `status` its status, `reason` the
  reason of the status followed by "its findings are not in this run".
- The firewall comparison not made: `what` "firewall rules against
  listening ports (firewall_rules of ush-inventory, tcp_listeners of
  ush-processes)", `reason` every missing input joined with "; " (a child
  not in `children.json` or not `ok`, no `detail_file`, a detail file that
  cannot be read or holds no object, a source missing, or not `read` or
  `empty` with its reason, a list missing), followed by "the comparison was
  not made".
- Firewall rules that could not be read: when the comparison was made and
  some `firewall_rule` items of the inventory detail have `rule` in
  `unread_fields` (a text that is no `v2.` rule) or a `dir`, `action` or
  `active` that is no single value: `what` "firewall rules that could not be
  read (firewall_rules of ush-inventory)", `reason` how many and that they
  are in no count of `firewall_ports_counts`.
- Listening ports with an unread program path: when the comparison was made,
  some ports belong to a group whose `path` is `null` although its
  `path_kind` is `file` (a program file whose path could not be read; a
  process without a file, such as System, does not count) or to no group of
  the detail file (the process list was not read, or the process started
  after it was read), and
  `not_listening` is above 0: `what` "programs of the listening ports
  without a path (tcp_listeners of ush-processes)", `reason` how many such
  ports there are and that the rules counted `not_listening` were not
  compared with them and may belong to one of them. This count is part of
  `ports_without_path`: the ports of a process without a file (System,
  `path_kind` `none`) count there but not here, so the two numbers
  differ.

- The driver update links not made: `what` "driver update links
  (pending_updates of ush-health, driver_packages and devices of
  ush-inventory)", `reason` every side not read joined with "; " (as for
  the firewall comparison: a child not `ok`, a detail file, source or list
  missing or not read, each naming its skill and source), followed by "the
  updates were not linked".

The `not_checked` entries of each child stay in its `h` item.

## --detail

`runall.py --detail <id>` prints one item, a child (`h3`), a firewall
item (`w1`), a driver update link (`y1`), a decision (`j1`), an accepted
finding (`a1`) or a review item (`r1`), from the newest `runall-*.detail.json` in `<data dir>/work/`
(by name, so by time) and exits 0. `--detail-file <path>` (the summary's
`detail_file`) reads that file instead and needs no data directory;
`--detail-file` without `--detail` is a usage error. An unknown id, no
detail file, or a file that cannot be read exits 1 with a message on
stderr. `--detail` never runs a child and writes nothing.

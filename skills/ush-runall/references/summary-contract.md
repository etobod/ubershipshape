# Summary contract, ush-runall (schema_version 1)

The ush-runall fields of the summary and the detail file, and the ush-runall
cases of the shared parts. The shared contract (files, `sources`,
`not_checked`, ids, recommendations, the report profile) is in
`skills/ush-common/references/summary-contract.md`; the report checker reads
the ush-runall rules from `data/report-profile.json`.

## Files and output

One run of `scripts/runall.py` writes to `<data dir>` (the data directory:
`--data-dir`, else `USH_DATA_DIR`, else `%LOCALAPPDATA%\ubershipshape`, made
absolute at once; see the shared contract):

- `work/runall-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text
  is printed on stdout. The time in the name is UTC.
- `work/runall-<YYYYmmdd-HHMMSS>.detail.json` - the detail file:
  `schema_version`, `skill`, `generated_at`, `summary_file` (the summary of
  the same run), `children` (one item per child with its full summary),
  `firewall_ports` (every matched rule, no limit), `firewall_ports_counts`
  and `network_categories`.

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
most 86400 (one day). The
repository order is `ush-health`, `ush-events`, `ush-settings`,
`ush-inventory`, `ush-processes`, `ush-files`, `ush-advice`, so the ids
are `h1` to `h7` in that order. The file is not usable (exit 2) when it
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
`h` and `w` ids of `runall`, so the digits of a child id are checked as
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

## not_checked

Besides the shared cases:

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

The `not_checked` entries of each child stay in its `h` item.

## --detail

`runall.py --detail <id>` prints one item, a child (`h3`) or a firewall
item (`w1`), from the newest `runall-*.detail.json` in `<data dir>/work/`
(by name, so by time) and exits 0. `--detail-file <path>` (the summary's
`detail_file`) reads that file instead and needs no data directory;
`--detail-file` without `--detail` is a usage error. An unknown id, no
detail file, or a file that cannot be read exits 1 with a message on
stderr. `--detail` never runs a child and writes nothing.

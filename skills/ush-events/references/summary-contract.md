# Summary contract (schema_version 1)

The shared shape of what a `ush-*` script hands to the model, and of the
recommendations the model writes in its report. `ush-events` is the first
skill that uses it; later skills follow the same shape.

The script counts; the model judges. The script never rates severity and never
writes a recommendation. Weights and recommendations are assigned by the model
in the report, from the numbers in the summary.

## Files and output

One run of `scripts/events.py` writes two files to `<data-dir>/work/`
(`--data-dir` defaults to `ush-data` relative to the working directory and is
made absolute at once):

- `events-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text is
  printed on stdout. The time in the name is UTC, so names sort by time.
- `events-<YYYYmmdd-HHMMSS>.detail.json` - the detail file: the full lists
  (never truncated) with the same ids as the summary, plus `unreadable`.

The model reads only the summary. It fetches single items from the detail file
with `--detail <id>` (see below), never by reading raw captures.

The summary is compact ASCII JSON. To keep it within 35 000 characters only
`groups` are cut, from the end (the rarest); `truncated` counts them. Nothing
else is ever cut, so a window with very many anomalies or boots can still
exceed the limit; the full lists are in the detail file either way.

## Summary fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `skill` | string | `"ush-events"` |
| `generated_at` | string | ISO 8601 with offset (UTC), time of the run |
| `window` | object | `start`, `end` (ISO 8601, UTC) and `days` (int): the time span read |
| `sources` | list | one entry per capture pass, see below |
| `groups` | list | level 1-3 events grouped by log, provider and Id (known noise excluded), most frequent first; ids `g1`, `g2`, ... |
| `noise` | list | groups that match the known-noise list `data/noise.json`, with `count` and `reason`; ids `n1`, `n2`, ... Noise is counted, never hidden |
| `boots` | list or null | boot sessions; id `b<index>` (`b0` is the part of a session that began before the window). `null` when System pass B was unreadable: sessions are unknown, and every anomaly's `boot` is `null` too |
| `anomalies` | list | bugchecks, unexpected shutdowns, Kernel-Power 41, sleep without wake; ids `a1`, `a2`, ... Never truncated |
| `not_checked` | list | what could not be read or covered, see below. Always present; `[]` means nothing was skipped |
| `summary_file` | string | absolute path of the summary file |
| `detail_file` | string | absolute path of the detail file |
| `truncated` | int | how many groups were left out of the summary to fit the budget (cut from the end, the least frequent). `0` when none. The full list is in the detail file |

### Group

`id`, `provider`, `event_id`, `level` (lowest number seen, 1 = critical),
`log`, `count`, `first`, `last` (ISO 8601, UTC), `sample` (one shortened
message, direction marks removed).

### Noise item

`id`, `provider`, `event_id`, `count`, `reason`, `first`, `last`.

### Boot session

`id`, `index`, `start`, `end` (ISO 8601 or `null`), `clean_shutdown`
(`true` with an EventLog 6006, `false` without one before the next boot,
`null` for the last session, which may still be running).

### Anomaly

`id`, `kind` (`bugcheck`, `unexpected_shutdown`, `kernel_power_41`,
`sleep_without_wake`), `time`, `boot` (session index), `log`, `record_id`;
a bugcheck also has `bugcheck_code` (e.g. `0x0000019c`, or `null`) and
`bugcheck_raw`. `sleep_without_wake` is a Kernel-Power 506 with no 507 and
no clean shutdown (6006) after it before the next 506 or the next boot.

Groups and noise come from pass A only. An event found only by pass B (the
boot and crash Ids) feeds `boots` and `anomalies`, never a group, so an
unreadable pass A is not hidden behind a few error groups.

## Sources

One entry per pass:

- `System` pass `A` and `Application` pass `A`: levels 1-3 in the window,
  read separately so a failure of one log does not take the other.
- `System` pass `B`: Ids 12, 41, 506, 507, 1001, 6005, 6006, 6008, 6009 in the
  window (boots, shutdowns, sleep, crashes; most are level 4).

Fields:

| Field | Meaning |
|---|---|
| `log` | `System` or `Application` |
| `pass` | `A` or `B` |
| `status` | `read` - events were read; `empty` - read, nothing matched; `unreadable` - could not be read |
| `reason` | error text for `unreadable` (PowerShell stderr, trimmed), otherwise `null` |
| `event_count` | number of events read in this pass (`0` for `empty` and `unreadable`) |
| `log_oldest_record` | time of the oldest record in the whole log (any level), or `null` if unknown or the log has no records |
| `coverage_start` | set to `log_oldest_record` when that is later than `window.start`: the log does not cover the start of the window (cleared or overwritten). Set to `window.end` when the log holds no records at all: it covers nothing. Otherwise `null` |

`empty` is a finding ("read, nothing there"); `unreadable` is not. An `empty`
source with a `coverage_start` covers only the time after `coverage_start`,
so it must not be reported as "clean" for the whole window.

No baseline: a skill that compares with a saved baseline reports "no
baseline yet" as a state of its own, never as "no changes". `ush-events`
(schema_version 1) keeps no baseline, so the case does not arise here.

## not_checked

Each item: `what` (string, names the log or check), `reason` (string), and for
a time gap also `from` and `to` (ISO 8601). Items are added for:

- every `unreadable` source (reason = the error text);
- an oldest-record query that could not be read;
- every log whose oldest record is later than the window start
  (`from` = `window.start`, `to` = the oldest record);
- every log that holds no records at all ("<log> log: holds no records at
  all", `from` = `window.start`, `to` = `window.end`);
- events whose time could not be read (one item with their count; the list
  itself is under `unreadable` in the detail file).

The report names each item; an empty list is reported as "nothing".

## Ids and --detail

`python -B skills/ush-events/scripts/events.py --data-dir <dir> --detail <id>`
prints the item with that id (`g..`, `n..`, `b..`, `a..`) from the newest
`events-*.detail.json` in `<dir>/work/` (never from a summary file) and exits 0.
With `--detail-file <path>` (the summary's `detail_file`) it reads that file
instead, so the item comes from the same run as the summary.
An unknown id, or no detail file, exits non-zero with a message on stderr.
It does not start PowerShell.

## Recommendations (written by the model in the report)

Every recommendation in any `ush-*` report carries these fields:

| Field | Values / content |
|---|---|
| `weight` | `high`, `medium` or `low` - one scale shared by all skills |
| `kind` | `change` (the user changes something), `observe` (watch it, run again later), `consult_service` (needs a hardware service or the vendor) |
| `risk` | what can go wrong when acting on it |
| `evidence` | the numbers and ids from the summary or detail items it rests on |
| `permissions` | what it needs (e.g. none, administrator) |
| `rollback` | how to undo it (or "nothing to undo" for `observe`) |

Weights:

- `high` - data loss, crashes or a failing device is likely; act soon.
- `medium` - a real fault with limited effect; act when convenient.
- `low` - a minor or cosmetic issue, or worth watching only.

The script assigns none of these; there is no threshold in code.

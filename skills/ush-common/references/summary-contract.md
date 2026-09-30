# Summary contract, shared part (schema_version 1)

The shape of what every `ush-*` script hands to the model, and of the
recommendations the model writes in its report. Each skill describes its own
fields in its own `references/summary-contract.md` and points here for the
rest.

The script counts; the model judges. The script never rates severity and never
writes a recommendation. Weights and recommendations are assigned by the model
in the report, from the numbers in the summary.

## Files and budget

One run of a skill script writes two files to `<data dir>/work/`, where
`<data dir>` is the data directory (`--data-dir` when given, else the `USH_DATA_DIR` environment variable
when set, else `%LOCALAPPDATA%\ubershipshape`; an empty variable counts as
not set. An empty `--data-dir`, a relative `USH_DATA_DIR` or `LOCALAPPDATA`,
or neither variable set stops the script with a usage error: a relative
value never falls through to the next source.
The directory is
made absolute at once; no output path is derived
from the script's location). The model takes its absolute value from the
summary's `summary_file` (the directory above `work/`):

- `<name>-<YYYYmmdd-HHMMSS>.summary.json` - the summary. The same text is
  printed on stdout. The time in the name is UTC, so names sort by time.
- `<name>-<YYYYmmdd-HHMMSS>.detail.json` - the detail file: the full lists
  (never truncated) with the same ids as the summary.

The model reads only the summary. It fetches single items from the detail file
with `--detail <id>` (see below), never by reading raw captures.

The summary is compact ASCII JSON and stays within a size budget (35 000
characters). Only the list the skill names may be cut to fit, from its end;
the top-level `truncated` (int) counts the items cut, `0` when none. Nothing
else is ever cut. A skill may name more than one list, each with its own
top-level count key (the skill's contract names them and the order they are
cut in); `truncated` still counts the first. When the summary does not fit
even with those lists empty, it goes out over the budget and `not_checked`
gets one item saying so.

Every summary has these top-level fields:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `skill` | string | the skill's name, e.g. `"ush-events"`; the report checker reads the skill's report profile by it |
| `generated_at` | string | ISO 8601 with offset (UTC), time of the run |
| `sources` | list | one entry per source read, see below |
| `not_checked` | list | what could not be read or covered, see below. Always present; `[]` means nothing was skipped |
| `summary_file` | string | absolute path of the summary file |
| `detail_file` | string | absolute path of the detail file |
| `truncated` | int | items cut from the summary to fit the budget |

## Sources

Every entry of `sources` has at least:

| Field | Meaning |
|---|---|
| `status` | `read` - data was read; `empty` - read, nothing there; `unreadable` - could not be read |
| `reason` | error text for `unreadable` (trimmed), otherwise `null` |

`empty` is a finding ("read, nothing there"); `unreadable` is not, and is
never collapsed into `empty` or into a missing value. A value that could not
be read is `null`, never `false` or `0`. A missing policy key means "default",
not "disabled": the summary gives the effective state.

No baseline: a skill that compares with a saved baseline reports "no
baseline yet" as a state of its own, never as "no changes".

## not_checked

Each item: `what` (string, names the source or check) and `reason` (string);
a time gap also has `from` and `to` (ISO 8601). Every `unreadable` source is
an item (reason = the error text); a source that needs administrator rights
in a run without them is an item with that reason, not an empty source. Each
skill lists its other cases.

The report names each item; an empty list is reported as "nothing".

## Ids and --detail

Every item of a summary or detail list has an `id`: one lowercase letter per
list followed by its 1-based position (`g1`, `g2`, ...). The letters of a
skill are in its report profile.

`python -B skills/<skill>/scripts/<script>.py --data-dir <dir> --detail <id>`
prints the item with that id from the newest detail file of the skill in
`<dir>/work/` (never from a summary file) and exits 0. With
`--detail-file <path>` (the summary's `detail_file`) it reads that file
instead, so the item comes from the same run as the summary. An unknown id,
or no detail file, exits non-zero with a message on stderr. It does not
start PowerShell.

## Baseline

A differential skill keeps its previous state in `<data dir>/state/`
(`skills/ush-common/scripts/baseline.py`): `<skill>.json`, or
`<skill>.elevated.json` for a run with administrator rights. An elevated run
sees another set (more tasks, `HKCU` of another account), so it is compared
only with an elevated baseline. The file has `schema_version` (`1`), `skill`,
`created_at` (ISO 8601, UTC), `elevated` and `sources`
(`{source name: {key: item}}`). A new baseline is written to a temporary
file, read back and compared before it replaces the old one; the old one
becomes `<skill>.previous.json` (one generation). A baseline that cannot be
read is never deleted or overwritten: it is kept next to the new one as
`<skill>.unreadable-<UTC stamp>.json`.

The summary has a `baseline` object:

| Field | Meaning |
|---|---|
| `status` | `none` - no baseline yet (first run); `compared` - a baseline was read and compared; `unreadable` - a baseline file exists but could not be read (bad JSON, another `schema_version`, `skill` or `elevated`, a time without a zone) |
| `created_at` | ISO 8601 time of the baseline compared with, `null` unless `compared` |
| `age_days` | days from `created_at` to `generated_at`, one decimal place, `null` unless `compared` |
| `saved` | `true` when this run's baseline was written and verified, `false` otherwise (then `not_checked` has an item) |
| `reason` | why the baseline was `unreadable` or not saved, otherwise `null` |

Each source also has a comparison state:

| State | Meaning |
|---|---|
| `compared` | the source was read now (`read` or `empty`) and is in the baseline |
| `no_baseline` | the source is not in the baseline (first run, an unreadable baseline, or a source added since) |
| `not_read` | the source is not `read` or `empty` now; the baseline keeps its previous items, so the next run does not see them as added |

Only `compared` gives changes. `no_baseline` and `not_read` give no changes
at all: they are reported as "no comparison" for that source, never as "no
changes". A change lists only the compared fields that differ, as
`{field: {before, after}}`; a field the item lists in `unread_fields` (its
source was not read, so its value is unknown) is not compared. A script that
cannot read a field takes its value from the item with the same key in the
previous baseline; only an item without a previous value gets `null` and
names the field in `unread_fields`, so a known value is never replaced by an
unknown one.

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

## Report profile

The report checker `skills/ush-common/scripts/check_report.py` is shared. It
takes the skill from the summary's `skill` key (only `ush-<lowercase letters>`
is accepted) and reads the skill's rules from
`skills/<skill>/data/report-profile.json`. A summary without `skill`, or a
skill without a profile, cannot be checked (exit 2).

| Field | Meaning |
|---|---|
| `detail_sections` | the lists of the detail file whose items `ush:detail` may name |
| `id_letters` | the letters of the item ids, e.g. `"gnabrd"` |
| `path_keys` | keys whose values are file paths or names; their digits back no number |
| `id_keys` | keys whose values are item ids or references to them; their digits back no number |
| `required_lists` | dotted paths (`dumps.files`) of the summary lists whose every item the report must name; a missing or `null` list requires nothing |
| `truncated` | `null`, or a list of `{"list": <dotted path>, "prefix": <letters>, "count_key": <summary key>}`, one per list the summary may cut from its end: the top-level summary key `count_key` (default `"truncated"`) counts the items cut from that list, and their ids (`<prefix><N+1>` to `<prefix><N+count>`, N the list's length) count as known. One such object without the list brackets works as a one-item list |
| `required_keys` | optional; top-level summary keys that must be present. A key whose value is `null` or empty is present; a missing key is named and gives exit `1`, so a summary of an older shape fails rather than passing because its list is missing |
| `report_prefix` | the file name prefix of the skill's reports, e.g. `"events-"` |

Example, the ush-health profile: `id_letters` `"kvpu"` (disks, volumes,
devices, update failure groups), `required_lists`
`["disks", "volumes", "devices", "updates.failures"]` (a nested list such as
`tpm.devices` is not required unless named), `truncated`
`{"list": "updates.failures", "prefix": "u"}`, `path_keys`
`["summary_file", "detail_file", "device_id", "instance_id"]` (the paths
and two detail-only identifiers), so device, disk and update names back the
digits a report quotes from them, and `report_prefix` `"health-"`.

Run it as:

```
python -B skills/ush-common/scripts/check_report.py <report.md>
python -B skills/ush-common/scripts/check_report.py --latest --skill <skill> [--data-dir <dir>]
```

`--latest` needs `--skill` and takes the newest `<report_prefix>*.md` in
`<data dir>/reports/`; a report whose summary names another skill is an
error. Exit codes: `0` OK, `1` numbers not backed, required items not
named or required summary keys missing, `2` the report, its JSON or its profile could not be checked.

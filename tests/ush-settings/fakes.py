"""Shared fakes for the ush-settings tests of milestones M2 and M3.

Interface under test (fixed before the code exists), M2 part:

- The script is loaded with ``load_script("ush-settings", "settings")``.
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``; ``now`` is a tz-aware
  datetime. Module-level ``default_run_ps`` and ``default_is_admin`` are used only when
  neither machine function is injected; exactly one injected raises ``TypeError``.
- Arguments: ``--data-dir DIR``, ``--detail ID``, ``--detail-file PATH``. The summary JSON is
  printed on stdout; its ``detail_file`` key is the absolute path of the detail JSON
  (``<data dir>/work/settings-<UTC stamp>.detail.json``).
- Module attribute ``CATALOGUE_PATH`` (a ``pathlib.Path``). The tests patch it with
  ``unittest.mock.patch.object`` to an invented catalogue ``{"schema_version": 1,
  "entries": [...]}`` that passes the M1 validator (``catalogue.load``).
- ``run_ps(job, script, out_path) -> (exit_code, stderr)``. ``FakePowerShell`` answers by
  job name and writes JSON to ``out_path`` as UTF-8 with a BOM (Windows PowerShell 5.1).
  A job it does not know answers ``[]``. A failed job is a non-zero exit code.
- Jobs in M2:
  - ``registry_values``: rows ``{hive, path, name, status: present|absent|unreadable,
    value, kind, error}``, one per catalogue registry location, plus the row for
    ``HKLM SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion EditionID``. Rows match
    locations case-insensitively on hive, path and name; a location without a row is
    ``unreadable``.
  - ``wifi_adapter``: rows ``{driver_key, name, status, value, kind, error}``, one per
    adapter per ``read.name`` of each ``wifi_adapter_value`` entry. ``[]`` = no adapter.
- Baseline: ``<data dir>/state/ush-settings.json`` (``ush-settings.elevated.json`` when
  elevated).
- Summary items (``settings``, ids ``e1``...) carry ``id, entry, area, level, title, state,
  effective, expected, source, from_policy_on_home, reason, has_block`` and, only in
  elevated runs, ``hkcu_elevated``. Entries in state ``matches`` / ``not_applicable`` are
  only counted in the summary but are listed, with the same fields, in the detail file's
  ``settings`` list; the tests read effective values from the detail file by ``entry``.
- ``changes`` items: ``id`` (``c1``...), ``key`` (the entry id), ``change``, ``entry``,
  ``area``, ``title``, ``state``; ``before``/``after`` on ``changed``.
  ``catalogue_changes`` is ``{"added": n, "removed": n}``.
- ``not_checked`` is a list of objects; tests only look for a word in its JSON text.

M3 part (readers, usage, paste-ready block). A failed job is a non-zero exit; a job may
answer a single object instead of a list, which is read as a one-element list.

- ``registry_values`` also carries ``HKLM SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\
  Internet Settings\\Connections WinHttpSettings``: ``kind: "Binary"``, ``value`` contiguous
  hex text; ``status: absent`` when missing.
- ``services``: ``{name, status: present|absent|unreadable, start_type: str|int,
  delayed_autostart: int|null, error}``; effective ``Automatic``, ``AutomaticDelayed``,
  ``Manual``, ``Disabled`` or ``"absent"``; numeric 2/3/4 -> Automatic/Manual/Disabled.
- ``firewall``: ``{profile, enabled: bool|int|str, local_enabled, policy_read: bool,
  policy_enabled: str|null}``; 0/1/2 -> false/true/"NotConfigured"; ``enabled`` is the
  effective state, ``local_enabled`` the local persistent setting, ``policy_enabled`` the
  RSOP profile's ``Enabled`` as text (null when RSOP has no such profile). The item's
  ``policy_enabled`` is null when ``policy_read`` is not true, "NotConfigured" when the
  profile is absent or NotConfigured, else mapped like ``enabled``.
- ``security_center``: ``{display_name, product_state: int}``; true when any product has
  bit 0x1000; ``[]`` -> false.
- ``defender``: one row ``{AMRunningMode, RealTimeProtectionEnabled, IsTamperProtected}``;
  effective = the field named by ``read.field``.
- ``device_guard``: one row ``{SecurityServicesRunning: [int]}``; true when ``read.service``
  is in the list.
- ``powercfg``: rows ``{query: "active", text}`` (``powercfg /getactivescheme``) and
  ``{query: "<subgroup> <setting>", text}`` (``powercfg /query SCHEME_CURRENT ...``).
  Pure functions ``parse_active_scheme(text) -> {guid, name} | None``,
  ``parse_query_indexes(text) -> (ac, dc) | None``, ``parse_winhttp(hex | None) ->
  "direct" | "<server>" | None``.
- ``dns``: ``{interface, family: IPv4|IPv6, servers: [str]}``.
- ``appx``: ``{name, status: present|absent}``.
- ``delivery_optimization``: one row ``{DownloadMode: str|int}``; 0/1/2/3/99/100 ->
  HttpOnly/Lan/Group/Internet/Simple/Bypass; an unknown number stays a number.
- ``optional_features``: the whole list ``{Name, InstallState: int}``; 1 Enabled,
  2 Disabled, 3 absent, 4 not_read; a name missing from a read list is ``absent``.
- ``shadow_storage``: only run when admin; ``{volume, max_space, used_space,
  allocated_space}``; without admin ``vss_max_space`` is not_read ("needs administrator").
- ``capability_usage``: ``{capability: webcam|microphone|location, packaged, subkey, value,
  last_used_start, last_used_stop}`` (FILETIME integers, 0 = null). Summary ``usage`` items
  (``u1``...): ``capability, app, packaged, value, last_used_start, last_used_stop,
  in_use``; changes of usage have ``entry: null`` and ``app``.
- ``--block e3,e7`` after a collect run in the same data dir: up to four parts headed by
  comment lines containing "Run in a normal (non-elevated) Windows PowerShell",
  "Run in an elevated Windows PowerShell", "Rollback: normal", "Rollback: elevated";
  exit 0 with at least one command, else 1 (also on an unknown id, with stderr).

``RealCatalogueTestCase`` leaves ``CATALOGUE_PATH`` unpatched (the real catalogue);
``clean_responses`` answers every job so that every entry of a catalogue is as expected.

Every value here is invented; nothing comes from a machine.
"""

import io
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT, load_script

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

EDITION_PATH = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
WIFI_VALUE = "PnPCapabilities"


def minutes(n):
    """``NOW`` advanced by ``n`` minutes (one run per minute in multi-run tests)."""
    return NOW + timedelta(minutes=n)


def ok(rows):
    """PowerShell wrote ``rows`` as JSON and exited 0."""
    return ("ok", rows)


def fail(stderr, code=1):
    """PowerShell exited with ``code`` and wrote ``stderr``; no file is written."""
    return ("fail", code, stderr)


class FakePowerShell:
    """Stands in for run_ps. Jobs not listed answer ``ok([])``."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        response = self.responses.get(job, ok([]))
        if response[0] == "ok":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Windows PowerShell 5.1 writes UTF-8 with a BOM.
            out_path.write_text(json.dumps(response[1]), encoding="utf-8-sig")
            return 0, ""
        _, code, stderr = response
        return code, stderr

    def jobs(self):
        return [call[0] for call in self.calls]


# --- catalogue builders -------------------------------------------------------------

def loc(hive, path, name, role, value_map=None):
    """One catalogue registry location."""
    location = {"hive": hive, "path": path, "name": name, "role": role}
    if value_map is not None:
        location["map"] = value_map
    return location


def registry_entry(entry_id, locations, expected, default, level="standard",
                   area="privacy", apply=None):
    """An invented ``registry`` entry; without ``apply`` it carries ``manual``."""
    entry = {
        "id": entry_id,
        "area": area,
        "level": level,
        "title": f"Invented setting {entry_id}",
        "rationale": "Controls an invented feature; the expected value costs nothing.",
        "read": {"type": "registry", "locations": locations},
        "expected": expected,
        "default": default,
        "apply": apply,
    }
    if apply is None:
        entry["manual"] = "Invented manual step; undo it the same way."
    return entry


def wifi_entry(entry_id="invented_wifi_power", expected=(24,), default=0):
    """An invented ``wifi_adapter_value`` entry reading ``PnPCapabilities``."""
    return {
        "id": entry_id,
        "area": "power",
        "level": "strict",
        "title": "Invented Wi-Fi power management",
        "rationale": "Keeps an invented adapter awake; costs some battery.",
        "read": {"type": "wifi_adapter_value", "name": WIFI_VALUE},
        "expected": list(expected) if expected is not None else None,
        "default": default,
        "apply": {"value": 24, "kind": "DWord"},
    }


# --- PowerShell rows ----------------------------------------------------------------

def present(location, value, kind="DWord"):
    """A ``registry_values`` row: the value exists."""
    return {"hive": location["hive"], "path": location["path"], "name": location["name"],
            "status": "present", "value": value, "kind": kind, "error": None}


def absent(location):
    """A ``registry_values`` row: no key or no value."""
    return {"hive": location["hive"], "path": location["path"], "name": location["name"],
            "status": "absent", "value": None, "kind": None, "error": None}


def unreadable(location, error="Requested registry access is not allowed."):
    """A ``registry_values`` row: the read failed."""
    return {"hive": location["hive"], "path": location["path"], "name": location["name"],
            "status": "unreadable", "value": None, "kind": None, "error": error}


EDITION_LOCATION = {"hive": "HKLM", "path": EDITION_PATH, "name": "EditionID"}


def edition(value="Core"):
    """The ``EditionID`` row of the ``registry_values`` job."""
    return present(EDITION_LOCATION, value, kind="String")


def registry(*rows, edition_row=None):
    """A successful ``registry_values`` answer; adds an ``EditionID`` "Core" row by default."""
    if edition_row is None:
        edition_row = edition("Core")
    return ok([*rows, edition_row])


def wifi(driver_key, value, status="present", name=WIFI_VALUE):
    """A ``wifi_adapter`` row for one adapter."""
    return {"driver_key": driver_key, "name": name, "status": status,
            "value": value if status == "present" else None,
            "kind": "DWord" if status == "present" else None,
            "error": "Invented read error." if status == "unreadable" else None}


# --- M3: the real catalogue and clean answers of every job ----------------------------

REAL_CATALOGUE = REPO_ROOT / "skills" / "ush-settings" / "data" / "settings-catalogue.json"

WINHTTP_LOCATION = {
    "hive": "HKLM",
    "path": "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\Connections",
    "name": "WinHttpSettings",
}

ADAPTER_1 = "InventedClass\\0001"
ADAPTER_2 = "InventedClass\\0002"

INVENTED_SCHEME_GUID = "11111111-2222-3333-4444-555555555555"
INVENTED_SUBGROUP_GUID = "aaaaaaaa-0000-0000-0000-000000000001"
INVENTED_SETTING_GUID = "bbbbbbbb-0000-0000-0000-000000000002"

ANTIVIRUS_ON = 0x61000   # bit 0x1000 set
ANTIVIRUS_OFF = 0x60000  # bit 0x1000 clear


def real_entries():
    """The entries of the real catalogue (M1 data), parsed as plain JSON."""
    return json.loads(REAL_CATALOGUE.read_text(encoding="utf-8"))["entries"]


def entry_location(entries, entry_id, index=0):
    """Location ``index`` of the registry entry ``entry_id``."""
    for entry in entries:
        if entry["id"] == entry_id:
            return entry["read"]["locations"][index]
    raise KeyError(entry_id)


def _location_key(location):
    return (location["hive"].lower(), location["path"].lower(), location["name"].lower())


def _raw_key(key):
    try:
        return int(key)
    except ValueError:
        return key


def _raw_for(target, value_map):
    """A raw registry value that gives ``target`` after the location's ``map``."""
    if value_map is None:
        return target
    for key, mapped in value_map.items():
        if mapped == target and type(mapped) is type(target):
            return _raw_key(key)
    return _raw_key(next(iter(value_map)))


def _kind(value):
    return "String" if isinstance(value, str) else "DWord"


def clean_registry_rows(entries):
    """One ``present`` row per registry location, each with the entry's expected value.

    Informational entries get their ``default`` (or 1 when the default is unknown, so
    ``HibernateEnabled`` is 1).
    """
    rows, seen = [], set()
    for entry in entries:
        if entry["read"]["type"] != "registry":
            continue
        expected = entry.get("expected")
        if expected:
            target = expected[0]
        elif entry.get("default") is not None:
            target = entry["default"]
        else:
            target = 1
        for location in entry["read"]["locations"]:
            key = _location_key(location)
            if key in seen:
                continue
            seen.add(key)
            raw = _raw_for(target, location.get("map"))
            rows.append(present(location, raw, kind=_kind(raw)))
    return rows


def winhttp_hex(flags, server="", bypass=""):
    """Invented ``WinHttpSettings`` bytes as contiguous hex text.

    Layout: DWORD 0x18, DWORD counter, DWORD flags (offset 8), DWORD server length
    (offset 12), server text, DWORD bypass length, bypass text.
    """
    data = struct.pack("<IIII", 0x18, 0, flags, len(server)) + server.encode("ascii")
    data += struct.pack("<I", len(bypass)) + bypass.encode("ascii")
    return data.hex().upper()


def winhttp_row(flags=1, server=""):
    """The ``WinHttpSettings`` row of ``registry_values``."""
    return present(WINHTTP_LOCATION, winhttp_hex(flags, server), kind="Binary")


def clean_registry(entries, *replacements, winhttp=None, edition_row=None):
    """A ``registry_values`` answer with clean rows; ``replacements`` replace rows by location."""
    replaced = {_location_key(row): row for row in replacements}
    rows = []
    for row in clean_registry_rows(entries):
        rows.append(replaced.pop(_location_key(row), row))
    rows.extend(replaced.values())
    rows.append(winhttp if winhttp is not None else winhttp_row(1))
    return registry(*rows, edition_row=edition_row)


def service_row(name, start_type, delayed=0, status="present"):
    """A ``services`` row."""
    return {"name": name, "status": status, "start_type": start_type,
            "delayed_autostart": delayed, "error": None}


_SAME = object()


def firewall_rows(enabled=True, local=_SAME, policy_read=True, policy=None):
    """``firewall`` rows for the three profiles.

    ``enabled`` is the effective (ActiveStore) state, ``local`` the local persistent
    setting (by default the same as ``enabled``; None when it could not be read).
    ``policy_read`` says whether the RSOP store was read; ``policy`` is the RSOP profile's
    ``Enabled`` as text (``"True"``, ``"False"``, ``"NotConfigured"``) or None when RSOP
    has no such profile. The default is "policy read, profile absent" (no policy).
    """
    local = enabled if local is _SAME else local
    return [{"profile": profile, "enabled": enabled, "local_enabled": local,
             "policy_read": policy_read, "policy_enabled": policy}
            for profile in ("Domain", "Private", "Public")]


def defender_row(mode="Normal", realtime=True, tamper=True):
    """The ``defender`` row (``Get-MpComputerStatus`` fields)."""
    return {"AMRunningMode": mode, "RealTimeProtectionEnabled": realtime,
            "IsTamperProtected": tamper}


def active_scheme_text(guid=INVENTED_SCHEME_GUID, name="Invented Plan"):
    """Invented English output of ``powercfg /getactivescheme``."""
    return f"Power Scheme GUID: {guid}  ({name})\r\n"


def query_text(ac, dc):
    """Invented English output of ``powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE``."""
    lines = [
        f"Power Scheme GUID: {INVENTED_SCHEME_GUID}  (Invented Plan)",
        f"  Subgroup GUID: {INVENTED_SUBGROUP_GUID}  (Sleep)",
        "    GUID Alias: SUB_SLEEP",
        f"    Power Setting GUID: {INVENTED_SETTING_GUID}  (Allow wake timers)",
        "      GUID Alias: RTCWAKE",
        "      Possible Setting Index: 000",
        "      Possible Setting Friendly Name: Disable",
        "      Possible Setting Index: 001",
        "      Possible Setting Friendly Name: Enable",
        "      Possible Setting Index: 002",
        "      Possible Setting Friendly Name: Important Wake Timers Only",
        f"    Current AC Power Setting Index: 0x{ac:08x}",
        f"    Current DC Power Setting Index: 0x{dc:08x}",
        "",
    ]
    return "\r\n".join(lines)


def powercfg_rows(ac=1, dc=0):
    """``powercfg`` rows: the active scheme and the RTCWAKE query."""
    return [{"query": "active", "text": active_scheme_text()},
            {"query": "SUB_SLEEP RTCWAKE", "text": query_text(ac, dc)}]


def clean_responses(entries, overrides=None):
    """Answers of every job for a clean machine; ``overrides`` replace answers by job name.

    Clean: Defender Normal with real-time and tamper protection on; firewall on for three
    profiles; DiagTrack Disabled; WinHttpSettings direct; DownloadMode Lan; no
    Microsoft.Copilot package; an antivirus with bit 0x1000; SecurityServicesRunning with 2;
    RTCWAKE DC 0; two Wi-Fi adapters at 24; Recall not on the feature list; every registry
    location at its expected value (HibernateEnabled 1, HiberbootEnabled 0).
    """
    responses = {
        "registry_values": clean_registry(entries),
        "wifi_adapter": ok([wifi(ADAPTER_1, 24), wifi(ADAPTER_2, 24)]),
        "services": ok([service_row("DiagTrack", "Disabled")]),
        "firewall": ok(firewall_rows(True)),
        "security_center": ok([{"display_name": "Invented Antivirus",
                                "product_state": ANTIVIRUS_ON}]),
        "defender": ok([defender_row()]),
        "device_guard": ok([{"SecurityServicesRunning": [2]}]),
        "powercfg": ok(powercfg_rows(ac=1, dc=0)),
        "dns": ok([{"interface": "Invented Ethernet", "family": "IPv4",
                    "servers": ["192.0.2.53", "192.0.2.54"]}]),
        "appx": ok([{"name": "Microsoft.Copilot", "status": "absent"}]),
        "delivery_optimization": ok([{"DownloadMode": "Lan"}]),
        "optional_features": ok([{"Name": "InventedFeature-Alpha", "InstallState": 1}]),
        "shadow_storage": ok([{"volume": "C:", "max_space": 10737418240,
                               "used_space": 1073741824, "allocated_space": 2147483648}]),
        "capability_usage": ok([]),
    }
    responses.update(overrides or {})
    return responses


# --- test case base -----------------------------------------------------------------

class SettingsTestCase(unittest.TestCase):
    """Loads settings.py, patches ``CATALOGUE_PATH`` to a temporary invented catalogue."""

    patch_catalogue = True

    @classmethod
    def setUpClass(cls):
        cls.settings = load_script("ush-settings", "settings")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.catalogue_file = self.root / "invented-catalogue.json"
        if self.patch_catalogue:
            patcher = mock.patch.object(self.settings, "CATALOGUE_PATH",
                                        self.catalogue_file)
            patcher.start()
            self.addCleanup(patcher.stop)
        self._dirs = 0

    def write_catalogue(self, entries):
        data = {"schema_version": 1, "entries": entries}
        self.catalogue_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def data_dir(self):
        """A fresh absolute data directory inside the temporary root."""
        self._dirs += 1
        return self.root / f"ush-data-{self._dirs}"

    def run_main(self, data_dir, fake, admin=False, now=NOW, extra=()):
        """Run main with both machine functions injected; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.settings.main(
                ["--data-dir", str(data_dir), *extra],
                run_ps=fake,
                is_admin=lambda: admin,
                now=now,
            )
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            return json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")

    def collect(self, fake, data_dir=None, admin=False, now=NOW):
        """Run a collection and return the parsed summary (exit code must be 0)."""
        code, stdout, stderr = self.run_main(
            data_dir or self.data_dir(), fake, admin=admin, now=now
        )
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def detail(self, summary):
        path = Path(summary.get("detail_file"))
        self.assertTrue(path.is_absolute(), path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))
        return data

    def items_by_entry(self, items):
        self.assertIsInstance(items, list, items)
        result = {}
        for item in items:
            self.assertNotIn(item.get("entry"), result, f"duplicate entry in {items}")
            result[item.get("entry")] = item
        return result

    def detail_item(self, summary, entry_id):
        """The detail-file ``settings`` item of ``entry_id`` (every state is listed there)."""
        items = self.items_by_entry(self.detail(summary).get("settings"))
        self.assertIn(entry_id, items, sorted(map(str, items)))
        return items[entry_id]

    def summary_items(self, summary):
        return self.items_by_entry(summary.get("settings"))

    def changes(self, summary):
        changes = summary.get("changes")
        self.assertIsInstance(changes, list, summary)
        return changes

    def not_checked_text(self, summary):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return json.dumps(items).lower()

    def not_checked_items(self, summary):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return items


class RealCatalogueTestCase(SettingsTestCase):
    """Runs against the real catalogue: ``CATALOGUE_PATH`` is not patched."""

    patch_catalogue = False

    def setUp(self):
        super().setUp()
        self.entries = real_entries()

    def clean_fake(self, overrides=None):
        return FakePowerShell(clean_responses(self.entries, overrides))

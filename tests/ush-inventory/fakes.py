"""Shared fakes for the ush-inventory tests of milestone M2 (programs, comparison, CLI).

Interface under test (fixed before the code exists):

- The script is loaded with ``load_script("ush-inventory", "inventory")``.
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``; ``now`` is a
  tz-aware datetime; the tests always pass ``--data-dir <tmp>``.
- ``run_ps(job, script, out_path) -> (exit_code, stderr)``. ``FakePowerShell`` answers
  by job name and writes JSON to ``out_path`` the way Windows PowerShell 5.1 does
  (UTF-8 with a BOM). Any job it does not know (a future source) answers ``[]``.
- Jobs in M2, one per source:
  - ``win32_programs`` rows ``{Hive: "hklm64"|"hklm32"|"hkcu", KeyName, DisplayName,
    DisplayVersion, Publisher, InstallDate, SystemComponent, InstallLocation}``; every
    subkey arrives, including ones without ``DisplayName``.
  - ``msix_programs`` rows ``{Name, PackageFamilyName, Version, Publisher (a DN),
    SignatureKind, InstallLocation, FolderCreated (ISO 8601 UTC or null)}``.
- Output: ``<data dir>/work/inventory-<UTC stamp>.summary.json`` and ``.detail.json``;
  baseline ``<data dir>/state/ush-inventory.json`` (``.elevated.json`` with
  administrator rights). The summary is also printed on stdout.
- Item keys: ``win32:<hive>:<KeyName>``, ``msix:<PackageFamilyName>``.

Assumptions added by these tests beyond the plan text:

- ``summary["sources"]`` is a list of ``{name, status, reason, ...}`` as in ush-health
  (a dict keyed by source name is accepted too).
- ``summary["comparison"]`` is a dict ``{source name: state}``.
- Every program item (summary and detail) carries its item ``key``, its ``id`` and
  ``own``; its fields are named as in the plan table (``name``, ``version``,
  ``install_date``, ``system_component`` ...).
- A ``not_checked`` item about a source names the source in ``what``; an item about the
  baseline has the word "baseline" in ``what`` or ``reason``.
- ``baseline.created_at`` is the injected ``now`` of the run that wrote it, so
  ``baseline.age_days`` follows from the injected times.
- ``inventory`` imports the shared module as ``import baseline`` and calls
  ``baseline.save(...)``, so ``inventory.baseline.save`` can be patched.

Every value here is invented; nothing comes from a machine.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

SOURCES = ("win32_programs", "msix_programs")

STORE_DN = "CN=Invented Signer, O=Invented Store Corp, C=US"
SYSTEM_DN = "CN=Invented Windows Signer, O=Invented Windows Corp, C=US"


def ok(payload):
    """PowerShell wrote ``payload`` as JSON and exited 0."""
    return ("ok", payload)


def failure(stderr, code=1):
    """PowerShell exited with ``code`` and wrote ``stderr``; no file is written."""
    return ("fail", code, stderr)


def win32(key_name, name, version="1.0.0", publisher="Invented Publisher Ltd",
          install_date="20260101", hive="hklm64", system_component=None,
          install_location=None):
    """One ``Uninstall`` subkey as the ``win32_programs`` job returns it."""
    return {
        "Hive": hive,
        "KeyName": key_name,
        "DisplayName": name,
        "DisplayVersion": version,
        "Publisher": publisher,
        "InstallDate": install_date,
        "SystemComponent": system_component,
        "InstallLocation": install_location,
    }


def msix(family, name, version="1.0.0.0", kind="Store", publisher=STORE_DN,
         folder_created="2026-08-01T10:00:00Z", install_location=None):
    """One package as the ``msix_programs`` job returns it."""
    if install_location is None:
        install_location = f"C:\\Invented\\WindowsApps\\{family}_{version}"
    return {
        "Name": name,
        "PackageFamilyName": family,
        "Version": version,
        "Publisher": publisher,
        "SignatureKind": kind,
        "InstallLocation": install_location,
        "FolderCreated": folder_created,
    }


def default_win32():
    return [
        win32("InventedAppOne", "Invented App 1", install_date="20260310"),
        win32("{11111111-2222-3333-4444-555555555555}", "Invented App 2",
              hive="hkcu", install_date="20260402"),
    ]


def default_msix():
    return [
        msix("Invented.StoreApp_0abc1def2ghj3", "Invented.StoreApp"),
        msix("Invented.SystemApp_0abc1def2ghj3", "Invented.SystemApp",
             kind="System", publisher=SYSTEM_DN),
    ]


def default_responses():
    """A clean, invented machine: two Win32 programs, one Store and one System app.

    The jobs of later sources (plan 052 M1 and M2) answer "nothing there" in the
    shape of their result (a list, or one object for ``hosts``, ``administrators``
    and ``defender_exclusions``); a test of those sources overrides them. The M2
    shapes are those of ``fakes_additions.m2_responses``.
    """
    no_policy = {"path": [], "extension": [], "process": [], "ip": []}
    return {
        "win32_programs": ok(default_win32()),
        "msix_programs": ok(default_msix()),
        "optional_features": ok([]),
        "capabilities": ok([]),
        "drivers": ok([]),
        "firewall_rules": ok([
            {"store": "local", "exists": True, "values": []},
            {"store": "app_iso", "exists": True, "values": []},
            {"store": "policy", "exists": False, "values": []},
        ]),
        "root_certificates": ok([
            {"store": store, "exists": True, "certificates": []}
            for store in ("machine_root", "machine_policy", "enterprise", "user_root",
                          "authroot")
        ]),
        "hosts": ok({
            "raw_dir": "%SystemRoot%\\System32\\drivers\\etc",
            "expanded_dir": "C:\\Windows\\System32\\drivers\\etc",
            "exists": True,
            "text": "",
        }),
        "administrators": ok({"method": "local_group_member",
                              "current_sid": "S-1-5-21-0-0-0-1001", "members": []}),
        "defender_exclusions": ok({"method": "preference", "path": [], "extension": [],
                                   "process": [], "ip": [], "policy": no_policy,
                                   "policy_error": None}),
    }


class FakePowerShell:
    """Stands in for run_ps. Jobs not listed answer ``ok([])``."""

    def __init__(self, responses=None):
        self.responses = default_responses()
        self.responses.update(responses or {})
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


def id_number(item_id, letter):
    """``"a12"`` -> 12 for letter ``a``; fails loudly on another shape."""
    text = str(item_id)
    if not text.startswith(letter) or not text[1:].isdigit():
        raise AssertionError(f"id {item_id!r} is not {letter}<number>")
    return int(text[1:])


class InventoryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = load_script("ush-inventory", "inventory")

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def run_main(self, data_dir, fake, admin=False, now=NOW, extra=()):
        """Run main with both machine functions injected; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.inventory.main(
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

    def source(self, summary, name):
        sources = summary.get("sources")
        if isinstance(sources, dict):
            self.assertIn(name, sources, sources)
            return sources[name]
        self.assertIsInstance(sources, list, summary)
        matches = [s for s in sources if s.get("name") == name]
        self.assertEqual(len(matches), 1, f"source {name}: {sources}")
        return matches[0]

    def assert_unreadable(self, summary, name):
        src = self.source(summary, name)
        self.assertEqual(src.get("status"), "unreadable", src)
        self.assertIsInstance(src.get("reason"), str, src)
        self.assertTrue(src["reason"].strip(), src)
        return src

    def not_checked(self, summary):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return items

    def notes_about_source(self, summary, name):
        return [item for item in self.not_checked(summary) if name in str(item.get("what"))]

    def notes_about_baseline(self, summary):
        return [
            item for item in self.not_checked(summary)
            if "baseline" in (str(item.get("what")) + " " + str(item.get("reason"))).lower()
        ]

    def comparison(self, summary):
        comparison = summary.get("comparison")
        self.assertIsInstance(comparison, dict, summary)
        return comparison

    def by_key(self, items):
        self.assertIsInstance(items, list, items)
        result = {}
        for item in items:
            self.assertNotIn(item.get("key"), result, f"duplicate key in {items}")
            result[item.get("key")] = item
        return result

    def changes(self, summary):
        changes = summary.get("changes")
        self.assertIsInstance(changes, list, summary)
        return changes

    def own_changes(self, summary):
        own = summary.get("own_changes")
        self.assertIsInstance(own, dict, summary)
        return own

    def assert_no_own_changes(self, summary):
        self.assertEqual(
            {k: self.own_changes(summary).get(k) for k in ("added", "removed", "changed")},
            {"added": 0, "removed": 0, "changed": 0},
        )

"""Review dates in skills/ush-runall/scripts/runall.py: the ``r`` items (plan 063, M1,
criteria K2-K5).

Interface under test (from the plan):

- After the children, ``runall`` gives one item ``r1``... for every inventory program
  whose ``own`` is not ``true`` (win32 and msix) and every pip and npm package, plus one
  for every entry of ``<data dir>/state/review-dates.json`` whose key is in no list. An
  item carries ``id``, ``kind`` (``program`` or ``package``), ``key``, ``name`` and
  ``state``: ``no_decision``, ``due`` (``review_on`` is the local date of the run or
  earlier), ``not_due``, ``no_limit`` (period ``none``), ``gone`` (key in no program list,
  ``own: true`` programs included, and no package list) or ``not_checked`` (with a
  ``reason``; its child or source was not read, the item was carried ``from_baseline``,
  or the child names a partial skip of that source in its ``not_checked``).
- The local date is ``local_date(now)`` (``now.astimezone().date()``), one helper in
  ``review_dates.py``.
- The detail file section ``review`` holds every item; the summary ``review`` holds the
  first ``REVIEW_MAX = 50`` in the order ``due``, ``no_decision``, ``gone``,
  ``not_checked``, ``not_due``, ``no_limit``, then by kind and key; ``truncated_review``
  is the number cut; ``review_counts`` counts every item per state.
- An unreadable file gives ``review`` ``null``, ``review_counts`` ``null`` and one runall
  ``not_checked`` entry naming ``review-dates.json``.
- ``runall.py --detail r1 --detail-file <detail file>`` prints the item and exits 0.

Assumptions added by these tests beyond the plan text:

- The file holds ``{"schema_version": 1, "entries": [...]}`` and an entry is
  ``{kind, key, name, decided_on, period, review_on}`` with ISO dates (the writer of M2
  does not exist yet; the tests write the file by hand and check it with
  ``review_dates.load``).
- Child detail shapes: ush-inventory ``programs[]`` with ``key``, ``source``
  (``win32_programs`` / ``msix_programs``), ``own``, ``name`` and, when carried,
  ``from_baseline: true``; ush-packages ``packages[]`` with ``manager``, ``key``, ``name``
  and ``from_baseline``, and ``managers`` (also in the summary) with ``status`` per
  manager. Sources ``win32_programs``, ``msix_programs``, ``pip_packages`` and
  ``npm_packages`` sit in the child's ``sources`` with ``status``.
- A partial skip is a child summary ``not_checked`` entry whose ``what`` starts with the
  source name (``win32_programs key hklm64\\<subkey>``, ``pip_packages <python> user
  folder``, ``npm_packages <scope>``) with a ``reason``.
- ``review_counts`` is a dict keyed by state; a state with no item may be missing or 0.
- The test makes the local zone UTC+2 in two ways: ``now`` is a ``datetime`` whose
  ``astimezone()`` without an argument converts to UTC+2, and every loaded ``local_date``
  (the runall module attribute and a loaded ``review_dates`` module) is patched to the
  same rule.
- Items in the summary are the same objects (same ``id``, ``kind``, ``key``, ``state``)
  as in the detail file.

Plan 063, M2, criterion K5 (``test_written_file_is_read``): the writer
``review_dates.py --set <id> --period <p> --detail-file <runall detail> --data-dir <dir>``
is run as a child process on the detail file of a fake pass (the real clock and the real
``local_date``, since the writer stores the real local date); the next pass reads its file.

Apart from that writer, no process is started: the children are fakes (``test_runall.py``, ``test_accepted.py``)
that write invented summaries and detail files in temporary directories. Every value is
invented (Contoso, Fabrikam).
"""

import json
import os
import subprocess
import sys
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from tests.skill_loader import load_script, script_path

from .test_accepted import AcceptedChildren
from .test_runall import RunallTestCase, exits

REVIEW_DATES_SCRIPT = script_path("ush-common", "review_dates")
PLUS_TWO = timezone(timedelta(hours=2), "UTC+02:00")
FAILURE = "Invented failure: access denied (0x80070005)."
NPM_FOLDER = "C:\\Users\\Invented\\AppData\\Roaming\\npm\\node_modules"
STATES = ("due", "no_decision", "gone", "not_checked", "not_due", "no_limit")


class PlusTwoNow(datetime):
    """A run time whose local zone is UTC+2, whatever the zone of the test machine."""

    def astimezone(self, tz=None):
        return datetime.astimezone(self, PLUS_TWO if tz is None else tz)


def plus_two_local_date(now):
    return now.astimezone(PLUS_TWO).date()


# 2026-09-20 14:00 local (UTC+2).
NOW = PlusTwoNow(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
# 2026-11-09 22:30 UTC is 2026-11-10 00:30 local (UTC+2): just after local midnight.
NOW_AFTER_MIDNIGHT = PlusTwoNow(2026, 11, 9, 22, 30, 0, tzinfo=timezone.utc)


def source(name, status="read"):
    return {"name": name, "status": status,
            "reason": FAILURE if status == "unreadable" else None}


# --- invented child data -------------------------------------------------------------------

def win32(subkey, name, own=False, from_baseline=False):
    item = {"key": f"win32:hklm64:{subkey}", "source": "win32_programs", "own": own,
            "name": name, "version": "1.4.0", "publisher": "Contoso Ltd.",
            "install_date": "2026-03-14",
            "install_location": f"C:\\Program Files\\Contoso\\{subkey}",
            "scope": "machine", "system_component": False}
    if from_baseline:
        item["from_baseline"] = True
    return item


def msix(family, name, own=None, from_baseline=False):
    item = {"key": f"msix:{family}", "source": "msix_programs", "own": own, "name": name,
            "version": "2.0.1.0", "publisher": "CN=Fabrikam Invented Publisher"}
    if from_baseline:
        item["from_baseline"] = True
    return item


def inventory_child(programs, win32_status="read", msix_status="read", not_checked=()):
    """(detail content, summary extra) of an ``ush-inventory`` child."""
    sources = [source("win32_programs", win32_status), source("msix_programs", msix_status),
               source("firewall_rules"), source("drivers", "empty"),
               source("devices", "empty"), source("driver_packages", "empty")]
    listed = []
    for number, program in enumerate(programs, start=1):
        item = dict(program)
        item["id"] = f"a{number}"
        listed.append(item)
    detail = {"schema_version": 1, "skill": "ush-inventory", "sources": sources,
              "programs": listed, "autostart": [], "additions": [], "drivers": [],
              "driver_packages": [], "components": [], "leftovers": [],
              "vendor_folders": [], "changes": [], "not_checked": list(not_checked)}
    return detail, {"not_checked": list(not_checked)}


def pip(name_key, name, folder="install", from_baseline=False):
    item = {"manager": "pip", "key": f"pip:PythonCore/3.12|{folder}|{name_key}",
            "name": name, "version": "1.2.0", "python": "PythonCore/3.12",
            "folder": folder}
    if from_baseline:
        item["from_baseline"] = True
    return item


def npm(name, from_baseline=False):
    item = {"manager": "npm", "key": f"npm:{name}", "name": name, "version": "2.1.0",
            "folder": NPM_FOLDER}
    if from_baseline:
        item["from_baseline"] = True
    return item


def packages_child(packages, pip_status="read", npm_status="read", not_checked=()):
    """(detail content, summary extra) of an ``ush-packages`` child."""
    sources = [source("pip_packages", pip_status), source("npm_packages", npm_status)]
    listed = []
    for number, package in enumerate(packages, start=1):
        item = dict(package)
        item["id"] = f"k{number}"
        listed.append(item)
    managers = {
        "pip": {"state": pip_status, "status": pip_status,
                "pythons": None if pip_status == "unreadable" else [
                    {"python": "PythonCore/3.12",
                     "count": sum(1 for p in listed if p["manager"] == "pip"),
                     "unreadable": 0, "folders": {"install": "read", "user": "read"}}]},
        "npm": {"state": npm_status, "status": npm_status, "prefix_from": "default",
                "count": None if npm_status == "unreadable"
                else sum(1 for p in listed if p["manager"] == "npm"),
                "unreadable": 0},
    }
    detail = {"schema_version": 1, "skill": "ush-packages", "sources": sources,
              "managers": managers, "packages": listed, "changes": [],
              "pip_packages": [p for p in listed if p["manager"] == "pip"],
              "npm_packages": [p for p in listed if p["manager"] == "npm"],
              "not_checked": list(not_checked)}
    return detail, {"managers": managers, "not_checked": list(not_checked)}


def entry(kind, key, name, review_on, period="6m", decided_on="2026-03-20"):
    if period == "none":
        review_on = None
    return {"kind": kind, "key": key, "name": name, "decided_on": decided_on,
            "period": period, "review_on": review_on}


# Clean data used by several tests.
TRAY = win32("ContosoTray", "Contoso Tray", own=False)
NOTES = msix("Fabrikam.Notes_0abc1def2ghj3", "Fabrikam Notes", own=None)
WINDOWS_PART = win32("InventedWindowsPart", "Invented Windows Runtime Part", own=True)
HTTP = pip("contoso-http", "contoso-http")
TOOL = npm("@contoso/tool")


class TestRunallReviewDates(RunallTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.review_dates = load_script("ush-common", "review_dates")

    # --- helpers ---------------------------------------------------------------------------

    def write_review(self, data_dir, entries):
        path = data_dir / "state" / "review-dates.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "entries": list(entries)},
                                   indent=2), encoding="utf-8")
        loaded = self.review_dates.load(data_dir)
        self.assertEqual(loaded.get("status"), "read", loaded)
        return path

    def local_date_patches(self, stack):
        """Patch every loaded ``local_date`` to the UTC+2 rule."""
        targets = [self.runall]
        targets.extend(module for module in list(sys.modules.values())
                       if module is not None
                       and str(getattr(module, "__file__", "") or "").replace("\\", "/")
                       .endswith("ush-common/scripts/review_dates.py"))
        for module in targets:
            if callable(getattr(module, "local_date", None)):
                stack.enter_context(mock.patch.object(module, "local_date",
                                                      plus_two_local_date))

    def run_pass(self, entries, inventory, packages, outcomes=None, now=NOW):
        """Write ``entries`` (unless ``None``) and run a pass; return (summary, data dir,
        fake)."""
        data_dir = self.data_dir()
        if entries is not None:
            self.write_review(data_dir, entries)
        fake = AcceptedChildren(self.temp(), outcomes, inventory=inventory,
                                packages=packages)
        with ExitStack() as stack:
            self.local_date_patches(stack)
            summary = self.collect(data_dir, fake, now=now)
        return summary, data_dir, fake

    def review(self, data):
        self.assertIn("review", data, sorted(data))
        value = data["review"]
        self.assertIsInstance(value, list, value)
        for item in value:
            self.assertIsInstance(item, dict, value)
        return value

    def for_key(self, data, key):
        matches = [item for item in self.review(data) if item.get("key") == key]
        self.assertEqual(len(matches), 1, f"{key}: {data.get('review')}")
        return matches[0]

    def assert_state(self, item, state):
        self.assertEqual(item.get("state"), state, item)

    def assert_not_checked(self, item):
        self.assert_state(item, "not_checked")
        reason = item.get("reason")
        self.assertIsInstance(reason, str, item)
        self.assertTrue(reason.strip(), item)

    def assert_counts_match(self, summary, items):
        counts = summary.get("review_counts")
        self.assertIsInstance(counts, dict, summary.get("review_counts"))
        for state in STATES:
            expected = sum(1 for item in items if item.get("state") == state)
            self.assertEqual(counts.get(state, 0), expected, (state, counts))
        self.assertEqual(sum(counts.values()), len(items), counts)

    def review_notes(self, summary):
        return [note for note in self.items(summary, "not_checked")
                if "review-dates.json" in json.dumps(note)]

    # --- K2 --------------------------------------------------------------------------------

    def test_items_without_file(self):
        summary, data_dir, _ = self.run_pass(
            None, inventory=inventory_child([TRAY, NOTES, WINDOWS_PART]),
            packages=packages_child([HTTP, TOOL]))
        self.assertFalse((data_dir / "state" / "review-dates.json").exists())

        expected = {TRAY["key"]: ("program", "Contoso Tray"),
                    NOTES["key"]: ("program", "Fabrikam Notes"),
                    HTTP["key"]: ("package", "contoso-http"),
                    TOOL["key"]: ("package", "@contoso/tool")}
        for where, data in (("summary", summary), ("detail", self.detail(summary))):
            with self.subTest(where=where):
                items = self.review(data)
                self.assertEqual(len(items), len(expected), items)
                self.assertEqual({item.get("key") for item in items}, set(expected), items)
                self.assertNotIn(WINDOWS_PART["key"], [item.get("key") for item in items])
                ids = [item.get("id") for item in items]
                self.assertEqual(len(set(ids)), len(ids), ids)
                for item in items:
                    self.assertRegex(str(item.get("id")), r"^r[1-9][0-9]*$", item)
                    kind, name = expected[item["key"]]
                    self.assertEqual(item.get("kind"), kind, item)
                    self.assertEqual(item.get("name"), name, item)
                    self.assert_state(item, "no_decision")

        self.assert_counts_match(summary, self.review(self.detail(summary)))
        self.assertEqual(summary["review_counts"].get("no_decision"), 4, summary)
        self.assertEqual(summary.get("truncated_review"), 0, summary)
        self.assertEqual(self.review_notes(summary), [], summary.get("not_checked"))

    # --- K3 --------------------------------------------------------------------------------

    def test_states(self):
        with self.subTest("the helper takes the local date"):
            self.assertEqual(self.review_dates.local_date(NOW_AFTER_MIDNIGHT),
                             date(2026, 11, 10))

        later = win32("ContosoLater", "Contoso Later")
        now_windows = win32("ContosoNowWindows", "Contoso Became Windows Part", own=True)
        gone_key = "win32:hklm64:FabrikamRemoved"
        entries = [
            entry("program", TRAY["key"], "Contoso Tray", "2026-09-20"),     # that day
            entry("program", NOTES["key"], "Fabrikam Notes", "2026-09-01"),  # earlier
            entry("program", later["key"], "Contoso Later", "2026-09-21"),   # the next day
            entry("package", HTTP["key"], "contoso-http", None, period="none"),
            entry("program", gone_key, "Fabrikam Removed", "2026-12-01"),
            entry("program", now_windows["key"], "Contoso Became Windows Part",
                  "2027-01-15", period="1y", decided_on="2026-01-15"),
        ]

        with self.subTest("date states, gone and own: true"):
            summary, _, _ = self.run_pass(
                entries,
                inventory=inventory_child([TRAY, NOTES, later, WINDOWS_PART, now_windows]),
                packages=packages_child([HTTP, TOOL]))
            expected = {TRAY["key"]: "due", NOTES["key"]: "due", later["key"]: "not_due",
                        HTTP["key"]: "no_limit", TOOL["key"]: "no_decision",
                        gone_key: "gone", now_windows["key"]: "not_due"}
            detail_items = self.review(self.detail(summary))
            self.assertEqual({item.get("key") for item in detail_items}, set(expected),
                             detail_items)
            for key, state in expected.items():
                with self.subTest(key=key):
                    self.assert_state(self.for_key(summary, key), state)
            self.assertNotIn(WINDOWS_PART["key"],
                             [item.get("key") for item in detail_items])
            gone = self.for_key(summary, gone_key)
            self.assertEqual(gone.get("kind"), "program", gone)
            self.assertEqual(self.for_key(summary, HTTP["key"]).get("kind"), "package")
            self.assert_counts_match(summary, detail_items)

        with self.subTest("the local date is compared, not the UTC date"):
            midnight = [
                entry("program", TRAY["key"], "Contoso Tray", "2026-11-10"),
                entry("program", NOTES["key"], "Fabrikam Notes", "2026-11-11"),
            ]
            summary, _, _ = self.run_pass(
                midnight, inventory=inventory_child([TRAY, NOTES]),
                packages=packages_child([]), now=NOW_AFTER_MIDNIGHT)
            self.assert_state(self.for_key(summary, TRAY["key"]), "due")
            self.assert_state(self.for_key(summary, NOTES["key"]), "not_due")
            self.assert_counts_match(summary, self.review(self.detail(summary)))

    # --- K4 --------------------------------------------------------------------------------

    def test_not_read_is_not_gone(self):
        locked = "win32:hklm64:ContosoLocked"
        old_pip = "pip:PythonCore/3.12|user|contoso-old"
        scoped = "npm:@fabrikam/cli"
        entries = [
            entry("program", TRAY["key"], "Contoso Tray", "2026-09-01"),
            entry("program", NOTES["key"], "Fabrikam Notes", "2027-03-01"),
            entry("package", HTTP["key"], "contoso-http", None, period="none"),
            entry("package", TOOL["key"], "@contoso/tool", "2026-09-10"),
        ]
        clean_inventory = inventory_child([TRAY, NOTES])
        clean_packages = packages_child([HTTP, TOOL])

        def items_of(summary):
            return self.review(self.detail(summary))

        def assert_never_gone(summary):
            for item in items_of(summary):
                self.assertNotEqual(item.get("state"), "gone", item)

        with self.subTest("inventory did not run"):
            summary, _, _ = self.run_pass(entries, clean_inventory, clean_packages,
                                          outcomes={"ush-inventory": exits(1)})
            self.assertEqual(self.child(summary, "ush-inventory").get("status"), "failed")
            self.assert_not_checked(self.for_key(summary, TRAY["key"]))
            self.assert_not_checked(self.for_key(summary, NOTES["key"]))
            self.assert_state(self.for_key(summary, HTTP["key"]), "no_limit")
            assert_never_gone(summary)

        with self.subTest("win32_programs not read"):
            summary, _, _ = self.run_pass(
                entries, inventory_child([NOTES], win32_status="unreadable"),
                clean_packages)
            self.assert_not_checked(self.for_key(summary, TRAY["key"]))
            self.assert_state(self.for_key(summary, NOTES["key"]), "not_due")
            assert_never_gone(summary)

        with self.subTest("msix_programs not read"):
            summary, _, _ = self.run_pass(
                entries, inventory_child([TRAY], msix_status="unreadable"), clean_packages)
            self.assert_not_checked(self.for_key(summary, NOTES["key"]))
            self.assert_state(self.for_key(summary, TRAY["key"]), "due")
            assert_never_gone(summary)

        with self.subTest("packages did not run"):
            summary, _, _ = self.run_pass(entries, clean_inventory, clean_packages,
                                          outcomes={"ush-packages": exits(1)})
            self.assertEqual(self.child(summary, "ush-packages").get("status"), "failed")
            self.assert_not_checked(self.for_key(summary, HTTP["key"]))
            self.assert_not_checked(self.for_key(summary, TOOL["key"]))
            self.assert_state(self.for_key(summary, TRAY["key"]), "due")
            assert_never_gone(summary)

        with self.subTest("pip not read"):
            summary, _, _ = self.run_pass(
                entries, clean_inventory, packages_child([TOOL], pip_status="unreadable"))
            self.assert_not_checked(self.for_key(summary, HTTP["key"]))
            self.assert_state(self.for_key(summary, TOOL["key"]), "due")
            assert_never_gone(summary)

        with self.subTest("npm not read"):
            summary, _, _ = self.run_pass(
                entries, clean_inventory, packages_child([HTTP], npm_status="unreadable"))
            self.assert_not_checked(self.for_key(summary, TOOL["key"]))
            self.assert_state(self.for_key(summary, HTTP["key"]), "no_limit")
            assert_never_gone(summary)

        denied_note = {"what": "win32_programs key hklm64\\ContosoLocked",
                       "reason": "Requested registry access is not allowed."}
        npm_note = {"what": "npm_packages @contoso/tool",
                    "reason": "Invented: the package folder could not be read."}

        with self.subTest("program carried from the baseline, with an entry"):
            carried = win32("ContosoTray", "Contoso Tray", from_baseline=True)
            summary, _, _ = self.run_pass(
                entries, inventory_child([carried, NOTES],
                                         not_checked=[{"what": "win32_programs key "
                                                               "hklm64\\ContosoTray",
                                                       "reason": FAILURE}]),
                clean_packages)
            self.assert_not_checked(self.for_key(summary, TRAY["key"]))
            assert_never_gone(summary)

        with self.subTest("program carried from the baseline, without an entry"):
            carried = win32("ContosoLocked", "Contoso Locked", from_baseline=True)
            summary, _, _ = self.run_pass(
                entries, inventory_child([TRAY, NOTES, carried], not_checked=[denied_note]),
                clean_packages)
            self.assert_not_checked(self.for_key(summary, locked))
            self.assert_state(self.for_key(summary, TRAY["key"]), "due")

        with self.subTest("package carried from the baseline, with and without an entry"):
            carried_tool = npm("@contoso/tool", from_baseline=True)
            carried_lib = npm("@contoso/lib", from_baseline=True)
            summary, _, _ = self.run_pass(
                entries, clean_inventory,
                packages_child([HTTP, carried_tool, carried_lib], npm_status="unreadable",
                               not_checked=[npm_note]))
            self.assert_not_checked(self.for_key(summary, TOOL["key"]))
            self.assert_not_checked(self.for_key(summary, carried_lib["key"]))
            self.assert_state(self.for_key(summary, HTTP["key"]), "no_limit")
            assert_never_gone(summary)

        partial = entries + [
            entry("program", locked, "Contoso Locked", "2026-12-01"),
            entry("package", old_pip, "contoso-old", "2026-12-01"),
            entry("package", scoped, "@fabrikam/cli", "2026-12-01"),
        ]

        with self.subTest("a denied win32 subkey, no baseline item"):
            summary, _, _ = self.run_pass(
                partial, inventory_child([TRAY, NOTES], not_checked=[denied_note]),
                packages_child([HTTP, TOOL, pip("contoso-old", "contoso-old", "user"),
                                npm("@fabrikam/cli")]))
            self.assert_not_checked(self.for_key(summary, locked))
            assert_never_gone(summary)

        with self.subTest("an unreadable pip folder, no baseline item"):
            pip_note = {"what": "pip_packages PythonCore/3.12 user folder",
                        "reason": "Invented: access to the folder was denied."}
            summary, _, _ = self.run_pass(
                partial, inventory_child([TRAY, NOTES, win32("ContosoLocked",
                                                             "Contoso Locked")]),
                packages_child([HTTP, TOOL, npm("@fabrikam/cli")], not_checked=[pip_note]))
            self.assert_not_checked(self.for_key(summary, old_pip))
            assert_never_gone(summary)

        with self.subTest("an unlisted npm scope, no baseline item"):
            scope_note = {"what": "npm_packages @fabrikam",
                          "reason": "Invented: the scope folder could not be listed."}
            summary, _, _ = self.run_pass(
                partial, inventory_child([TRAY, NOTES, win32("ContosoLocked",
                                                             "Contoso Locked")]),
                packages_child([HTTP, TOOL, pip("contoso-old", "contoso-old", "user")],
                               not_checked=[scope_note]))
            self.assert_not_checked(self.for_key(summary, scoped))
            assert_never_gone(summary)

        with self.subTest("clean data with every source read: no not_checked item"):
            gone_key = "npm:@fabrikam/removed"
            with_gone = entries + [entry("package", gone_key, "@fabrikam/removed",
                                         "2026-12-01")]
            summary, _, _ = self.run_pass(
                with_gone, inventory_child([TRAY, NOTES, WINDOWS_PART]),
                packages_child([HTTP, TOOL, npm("@contoso/lib")]))
            items = items_of(summary)
            self.assertEqual([item for item in items if item.get("state") == "not_checked"],
                             [], items)
            self.assert_state(self.for_key(summary, gone_key), "gone")
            self.assert_state(self.for_key(summary, TRAY["key"]), "due")
            self.assert_state(self.for_key(summary, NOTES["key"]), "not_due")
            self.assert_state(self.for_key(summary, HTTP["key"]), "no_limit")
            self.assert_state(self.for_key(summary, TOOL["key"]), "due")
            self.assert_state(self.for_key(summary, "npm:@contoso/lib"), "no_decision")
            self.assertEqual(summary["review_counts"].get("not_checked", 0), 0, summary)
            self.assertEqual(self.review_notes(summary), [], summary.get("not_checked"))

    # --- K5 --------------------------------------------------------------------------------

    def test_file_and_budget(self):
        with self.subTest("an unreadable review-dates.json"):
            data_dir = self.data_dir()
            path = data_dir / "state" / "review-dates.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version": 1, "entries": [{"kind": "program"',
                            encoding="utf-8")
            fake = AcceptedChildren(self.temp(), inventory=inventory_child([TRAY]),
                                    packages=packages_child([HTTP]))
            with ExitStack() as stack:
                self.local_date_patches(stack)
                summary = self.collect(data_dir, fake, now=NOW)
            self.assertIn("review", summary, sorted(summary))
            self.assertIsNone(summary["review"], summary["review"])
            self.assertIn("review_counts", summary, sorted(summary))
            self.assertIsNone(summary["review_counts"], summary["review_counts"])
            self.assertEqual(len(self.review_notes(summary)), 1, summary.get("not_checked"))

        with self.subTest("the order of the states"):
            due = win32("ContosoDue", "Contoso Due")
            new = win32("ContosoNew", "Contoso New")
            later = win32("ContosoLater", "Contoso Later")
            keep = win32("ContosoKeep", "Contoso Keep")
            unread = "msix:Contoso.Unread_0abc1def2ghj3"
            gone = "win32:hklm64:ContosoGone"
            summary, _, _ = self.run_pass(
                [entry("program", keep["key"], "Contoso Keep", None, period="none"),
                 entry("program", later["key"], "Contoso Later", "2027-01-01"),
                 entry("program", unread, "Contoso Unread", "2026-09-01"),
                 entry("program", gone, "Contoso Gone", "2026-09-01"),
                 entry("program", due["key"], "Contoso Due", "2026-09-01")],
                inventory_child([keep, later, new, due], msix_status="unreadable"),
                packages_child([]))
            self.assertEqual(
                [(item.get("key"), item.get("state")) for item in self.review(summary)],
                [(due["key"], "due"), (new["key"], "no_decision"), (gone, "gone"),
                 (unread, "not_checked"), (later["key"], "not_due"),
                 (keep["key"], "no_limit")])

        with self.subTest("more items than the budget"):
            self.assertEqual(getattr(self.runall, "REVIEW_MAX", None), 50)
            new = [win32(f"ContosoApp{n:03d}", f"Contoso App {n:03d}") for n in range(1, 61)]
            due = [win32(f"ContosoDue{n}", f"Contoso Due {n}") for n in (3, 1, 2)]
            later = [win32(f"ContosoLater{n}", f"Contoso Later {n}") for n in (1, 2)]
            keep = win32("ContosoKeep", "Contoso Keep")
            gone = "win32:hklm64:ContosoGone"
            entries = ([entry("program", p["key"], p["name"], "2026-09-15") for p in due]
                       + [entry("program", p["key"], p["name"], "2027-02-01") for p in later]
                       + [entry("program", keep["key"], keep["name"], None, period="none"),
                          entry("program", gone, "Contoso Gone", "2026-09-01")])
            summary, data_dir, fake = self.run_pass(
                entries, inventory_child(later + new + [keep] + due), packages_child([]))

            detail_items = self.review(self.detail(summary))
            self.assertEqual(len(detail_items), 67, len(detail_items))
            expected_keys = ({p["key"] for p in new + due + later + [keep]} | {gone})
            self.assertEqual({item.get("key") for item in detail_items}, expected_keys)

            kept = self.review(summary)
            first = (sorted(p["key"] for p in due)
                     + sorted(p["key"] for p in new)[:47])
            self.assertEqual([item.get("key") for item in kept], first)
            self.assertEqual(summary.get("truncated_review"), 17, summary)
            self.assert_counts_match(summary, detail_items)
            self.assertEqual(summary["review_counts"].get("due"), 3)
            self.assertEqual(summary["review_counts"].get("no_decision"), 60)
            self.assertEqual(summary["review_counts"].get("not_due"), 2)
            self.assertEqual(summary["review_counts"].get("no_limit"), 1)
            self.assertEqual(summary["review_counts"].get("gone"), 1)

            by_id = {item.get("id"): item for item in detail_items}
            self.assertEqual(len(by_id), 67, "duplicate ids in the detail file")
            for item in kept:
                twin = by_id.get(item.get("id"))
                self.assertIsNotNone(twin, item)
                for field in ("kind", "key", "name", "state"):
                    self.assertEqual(item.get(field), twin.get(field), (field, item, twin))

            r1 = by_id.get("r1")
            self.assertIsNotNone(r1, sorted(by_id))
            self.assertIn("r1", [item.get("id") for item in kept])
            code, stdout, stderr = self.run_main(
                data_dir, fake, extra=("--detail", "r1", "--detail-file",
                                       summary["detail_file"]), now=NOW)
            self.assertEqual(code, 0, stderr[-500:])
            self.assertIn(r1["key"], stdout)
            self.assertIn(r1["state"], stdout)

    # --- M2 K5 -----------------------------------------------------------------------------

    def run_set(self, data_dir, ids, period, detail_file):
        """Run the writer ``review_dates.py --set`` as a child process; return its JSON."""
        env = dict(os.environ)
        env.pop("USH_DATA_DIR", None)
        env["PYTHONIOENCODING"] = "utf-8"
        done = subprocess.run(
            [sys.executable, "-B", str(REVIEW_DATES_SCRIPT), "--set", ids,
             "--period", period, "--detail-file", str(detail_file),
             "--data-dir", str(data_dir)],
            capture_output=True, text=True, check=False, encoding="utf-8", env=env,
            timeout=120)
        try:
            result = json.loads(done.stdout)
        except ValueError:
            self.fail(f"stdout is not JSON: {done.stdout!r}; stderr: {done.stderr!r}")
        self.assertEqual(done.returncode, 0, result)
        self.assertIs(result.get("ok"), True, result)
        return result

    def test_written_file_is_read(self):
        # The writer stores the real local date, so both passes run at the real time
        # with the real local_date (no patch).
        now = datetime.now(timezone.utc)
        inventory = inventory_child([TRAY, NOTES, WINDOWS_PART])
        packages = packages_child([HTTP, TOOL])
        data_dir = self.data_dir()

        first = self.collect(data_dir, AcceptedChildren(self.temp(), inventory=inventory,
                                                        packages=packages), now=now)
        detail_file = first["detail_file"]
        ids = {item.get("key"): item.get("id") for item in self.review(self.detail(first))}
        for key in (TRAY["key"], HTTP["key"]):
            self.assertIn(key, ids, ids)
            self.assert_state(self.for_key(first, key), "no_decision")

        self.run_set(data_dir, ids[TRAY["key"]], "1y", detail_file)
        self.run_set(data_dir, ids[HTTP["key"]], "none", detail_file)

        loaded = self.review_dates.load(data_dir)
        self.assertEqual(loaded.get("status"), "read", loaded)
        by_key = {item.get("key"): item for item in loaded.get("entries") or []}
        self.assertEqual(set(by_key), {TRAY["key"], HTTP["key"]}, loaded)
        self.assertEqual(by_key[TRAY["key"]].get("kind"), "program", by_key)
        self.assertEqual(by_key[HTTP["key"]].get("kind"), "package", by_key)

        second = self.collect(data_dir, AcceptedChildren(self.temp(), inventory=inventory,
                                                         packages=packages), now=now)
        self.assertEqual(self.review_notes(second), [], second.get("not_checked"))
        self.assert_state(self.for_key(second, TRAY["key"]), "not_due")
        self.assert_state(self.for_key(second, HTTP["key"]), "no_limit")
        self.assert_state(self.for_key(second, NOTES["key"]), "no_decision")
        self.assert_state(self.for_key(second, TOOL["key"]), "no_decision")
        self.assert_counts_match(second, self.review(self.detail(second)))


if __name__ == "__main__":
    unittest.main()

"""Accepted findings matched by skills/ush-runall/scripts/runall.py (plan 060, M2,
criteria K1-K4).

Interface under test (from the plan, the kinds file and the accepted module docstring):

- ``<data dir>/state/accepted.json`` holds ``{"schema_version": 1, "entries": [...]}``; each
  entry is ``{kind, key, skill, evidence, accepted_on, facts}``, ``kind`` one of
  ``skills/ush-common/data/accepted-kinds.json`` (``update``: ush-health
  ``update_failures``, key ``[title, hresult]``, ``last`` watched as ``later``;
  ``autostart``: ush-inventory ``autostart``, key ``key``, ``command``, ``targets`` and the
  per-target ``facts[]`` fields ``expanded_path``, ``signature_status``, ``signer``,
  ``sha256`` watched as ``changed``; ``event_group``: ush-events ``groups``, key
  ``[log, provider, event_id]``, ``count`` ``rises`` and ``last`` ``later``;
  ``firewall_rule``: ush-inventory ``additions`` with ``kind`` ``firewall_rule``, key
  ``key``, ``app``, ``svc``, ``lport``, ``protocol``, ``action``, ``active``, ``profile``
  watched as ``changed``).
- ``accepted.entry_for(kind, item)`` (plan 060 M1) builds ``{kind, key, facts}`` from a
  child detail item; the tests build the entries of the file with it and add ``skill``,
  ``evidence`` and ``accepted_on``.
- After the children, ``runall`` gives each entry one item ``a1``... in the summary and
  the detail file list ``accepted``: ``{id, kind, key, state, changed, evidence,
  accepted_on, reason}``, ``state`` ``quiet``, ``back``, ``gone`` or ``not_checked``,
  ``changed`` a list of ``{field, accepted, now}``, ``evidence`` ``"<skill> <id>"`` or
  ``null``.
- An update key matches every group with that title + hresult; the latest ``last`` counts.
- A watched field that is ``null`` now is not ``back``; an autostart item whose facts are
  ``facts_from_baseline`` is ``not_checked``, never ``quiet``.
- No file gives ``accepted: []``; an unreadable file gives ``accepted: null`` and one
  ``not_checked`` entry naming ``accepted.json``.
- ``runall.py --detail a1 --detail-file <detail file>`` prints the item and exits 0.

Assumptions added by these tests beyond the plan text:

- The ``a`` ids follow the order of the entries in the file.
- The ``field`` of a changed per-target fact contains the fact's name (``sha256``,
  ``signer``); for a changed target path some ``field`` names a path or ``targets``.
  Top-level fields (``last``, ``count``, ``app``, ``lport``, ``active``) are named exactly.
- A ``quiet`` item has an empty ``changed``; ``not_checked`` items carry a non-empty
  ``reason``.
- The item that is ``back`` because an update failed again names the group with the later
  ``last`` as its evidence.
- ``--detail a1`` prints the item's JSON text, which holds its ``state`` and its key values.

No process is started: the children are fakes (``test_runall.py``) that write invented
summaries and detail files in temporary directories. Every value is invented (Contoso,
Fabrikam, made-up hashes).
"""

import copy
import json
import unittest

from tests.skill_loader import load_script

from .test_runall import FakeChildren, RunallTestCase, exits

FAILURE = "Invented failure: access denied (0x80070005)."
ACCEPTED_ON = "2026-11-05"

U_TITLE = "2026-10 Security Update for Invented Windows (KB5099002) (26100.4100)"
U_HRESULT = "0x80070002"
U_LAST = "2026-10-22T03:15:00Z"
U_LATER_LAST = "2026-11-04T02:40:00Z"

TASK_KEY = "task:\\Fabrikam\\FabrikamUpdaterLogon"
TASK_MAIN = "C:\\Program Files\\Fabrikam\\Updater\\fupdate.exe"
TASK_HELPER = "C:\\Program Files\\Fabrikam\\Updater\\fhelper.exe"
TASK_MOVED = "C:\\ProgramData\\Fabrikam\\Cache\\fupdate.exe"
SHA_MAIN = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
SHA_HELPER = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
SHA_HELPER_NEW = "9c9c9c9c8d8d8d8d7e7e7e7e6f6f6f6f5a5a5a5a4b4b4b4b3c3c3c3c2d2d2d2d"
SIGNER = "Fabrikam Inc."
SIGNER_NEW = "Invented Unknown Signer"

RULE_KEY = "firewall:local:{6A1C0E52-1111-4D2B-9C3A-0F0E0D0C0B0A}"
RULE_APP = "C:\\Program Files\\Fabrikam\\Sync\\fsync.exe"

EVENT_LAST = "2026-11-04T19:30:00Z"
EVENT_LATER_LAST = "2026-11-08T07:05:00Z"


def source(name, status="read"):
    return {"name": name, "status": status,
            "reason": FAILURE if status == "unreadable" else None}


# --- invented child data -------------------------------------------------------------------

def update_group(group_id, title, hresult, last, result="Failed", count=2):
    return {"id": group_id, "title": title, "result": result, "hresult": hresult,
            "count": count, "first": "2026-10-01T03:00:00Z", "last": last,
            "superseded_by": None}


def health_child(groups, history_status="read"):
    """(detail content, summary extra) of an ``ush-health`` child; ``groups`` ``None``
    means ``update_failures`` was not read."""
    sources = [source("update_history", history_status), source("pending_updates", "empty")]
    detail = {"schema_version": 1, "skill": "ush-health", "sources": sources, "items": [],
              "update_failures": None if groups is None else list(groups),
              "pending_updates": []}
    return detail, {"pending_updates": []}


def fact(path, signer=SIGNER, sha256=SHA_MAIN, sha256_error=None):
    item = {"path": path, "expanded_path": path, "exists": True,
            "signature_status": "Valid", "signer": signer, "company": signer,
            "program": None, "sha256": sha256}
    if sha256_error is not None:
        item["sha256_error"] = sha256_error
    return item


def task_item(main=TASK_MAIN, main_signer=SIGNER, helper_sha=SHA_HELPER,
              helper_sha_error=None, from_baseline=False):
    return {"id": "s3", "key": TASK_KEY, "source": "scheduled_tasks", "kind": "task",
            "location": "\\Fabrikam\\", "name": "FabrikamUpdaterLogon",
            "command": '"' + main + '" /logon; "' + TASK_HELPER + '" /check',
            "enabled": True, "state": "Ready", "targets": [main, TASK_HELPER],
            "facts": [fact(main, signer=main_signer, sha256=SHA_MAIN),
                      fact(TASK_HELPER, sha256=helper_sha, sha256_error=helper_sha_error)],
            "facts_from_baseline": from_baseline, "own": False, "unread_fields": []}


def rule_item(app=RULE_APP, lport="8080", active="TRUE"):
    return {"id": "x2", "key": RULE_KEY, "kind": "firewall_rule",
            "source": "firewall_rules", "own": False, "store": "local",
            "action": "Allow", "dir": "In", "active": active, "lport": lport,
            "rport": None, "app": app, "svc": None, "name": "Fabrikam Sync",
            "profile": "Private", "embed_ctxt": None, "protocol": 6,
            "protocol_name": "TCP", "lport2": None, "version": "v2.33",
            "app_exists": True}


def inventory_child(autostart, additions):
    sources = [source("run_keys"), source("scheduled_tasks"), source("file_facts"),
               source("firewall_rules"), source("drivers", "empty"),
               source("devices", "empty"), source("driver_packages", "empty")]
    detail = {"schema_version": 1, "skill": "ush-inventory", "sources": sources,
              "autostart": list(autostart), "additions": list(additions),
              "drivers": [], "driver_packages": [], "programs": [],
              "vendor_folders": [], "changes": []}
    return detail, {}


def event_group(count=12, last=EVENT_LAST):
    return {"id": "g4", "provider": "Contoso-Agent", "event_id": 7001, "level": 2,
            "log": "Application", "count": count, "first": "2026-10-23T08:00:00Z",
            "last": last, "sample": "Invented agent error.", "first_half": 5,
            "second_half": count - 5, "trend": "stable"}


def events_child(groups):
    # ush-events names a source by its log and pass, not by a name.
    sources = [{"log": log, "pass": "A", "status": "read", "reason": None}
               for log in ("System", "Application")]
    detail = {"schema_version": 1, "skill": "ush-events", "sources": sources,
              "groups": list(groups), "noise": [],
              "listed": {"groups": [g["id"] for g in groups], "noise": []}}
    return detail, {}


class AcceptedChildren(FakeChildren):
    """M1's fake children, with chosen detail files per skill; the detail's ``sources``
    also become the summary's."""

    def __init__(self, files_dir, outcomes=None, **contents):
        super().__init__(files_dir, outcomes)
        self.contents = contents

    def summary(self, skill, **kwargs):
        summary = super().summary(skill, **kwargs)
        content = self.contents.get(skill.replace("ush-", ""))
        if content is not None:
            detail, extra = content
            summary["sources"] = detail["sources"]
            summary.update(extra)
            with open(summary["detail_file"], "w", encoding="utf-8") as handle:
                json.dump(detail, handle)
            with open(summary["summary_file"], "w", encoding="utf-8") as handle:
                json.dump(summary, handle)
        return summary


class TestRunallAccepted(RunallTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.accepted = load_script("ush-common", "accepted")

    # --- helpers ---------------------------------------------------------------------------

    def entry(self, kind, item, skill):
        built = self.accepted.entry_for(kind, copy.deepcopy(item))
        self.assertIsInstance(built, dict, built)
        entry = dict(built)
        entry.update(kind=kind, skill=skill, evidence=f"{skill} {item['id']}",
                     accepted_on=ACCEPTED_ON)
        return entry

    def update_entry(self, last=U_LAST):
        return self.entry("update", update_group("u2", U_TITLE, U_HRESULT, last),
                          "ush-health")

    def autostart_entry(self):
        return self.entry("autostart", task_item(), "ush-inventory")

    def event_entry(self):
        return self.entry("event_group", event_group(), "ush-events")

    def rule_entry(self):
        return self.entry("firewall_rule", rule_item(), "ush-inventory")

    def write_accepted(self, data_dir, entries):
        path = data_dir / "state" / "accepted.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "entries": list(entries)},
                                   indent=2), encoding="utf-8")
        loaded = self.accepted.load(data_dir)
        self.assertEqual(loaded.get("status"), "read", loaded)
        return path

    def run_pass(self, entries, outcomes=None, **children):
        """Write ``entries`` (unless ``None``) and run a pass; return (summary, data dir,
        fake)."""
        data_dir = self.data_dir()
        if entries is not None:
            self.write_accepted(data_dir, entries)
        fake = AcceptedChildren(self.temp(), outcomes, **children)
        return self.collect(data_dir, fake), data_dir, fake

    def accepted_items(self, data):
        self.assertIn("accepted", data, sorted(data))
        value = data["accepted"]
        self.assertIsInstance(value, list, value)
        return value

    def for_key(self, data, kind, key):
        matches = [item for item in self.accepted_items(data)
                   if isinstance(item, dict) and item.get("kind") == kind
                   and item.get("key") == key]
        self.assertEqual(len(matches), 1, f"{kind} {key}: {data.get('accepted')}")
        return matches[0]

    def assert_state(self, item, state):
        self.assertEqual(item.get("state"), state, item)

    def assert_quiet(self, item):
        self.assert_state(item, "quiet")
        self.assertFalse(item.get("changed"), item)

    def assert_not_checked(self, item):
        self.assert_state(item, "not_checked")
        reason = item.get("reason")
        self.assertIsInstance(reason, str, item)
        self.assertTrue(reason.strip(), item)
        return reason

    def changed(self, item, matches):
        """The ``changed`` entries whose ``field`` satisfies ``matches``."""
        changed = item.get("changed")
        self.assertIsInstance(changed, list, item)
        return [entry for entry in changed
                if isinstance(entry, dict) and isinstance(entry.get("field"), str)
                and matches(entry["field"])]

    def assert_back_with(self, item, field, accepted, now):
        """``back`` with a changed entry for ``field`` (exact) holding both values."""
        self.assert_state(item, "back")
        found = self.changed(item, lambda name: name == field)
        self.assertEqual(len(found), 1, item)
        self.assertEqual(found[0].get("accepted"), accepted, item)
        self.assertEqual(found[0].get("now"), now, item)

    # --- K1 --------------------------------------------------------------------------------

    def test_update_states(self):
        key = [U_TITLE, U_HRESULT]
        other = update_group("u1", "Contoso Driver Update - Display - 31.0.101.5000",
                             "0x80073701", "2026-10-30T09:00:00Z", count=1)

        with self.subTest("the same last is quiet"):
            summary, _, _ = self.run_pass(
                [self.update_entry()],
                health=health_child([other, update_group("u2", U_TITLE, U_HRESULT,
                                                         U_LAST)]))
            items = self.accepted_items(summary)
            self.assertEqual([item.get("id") for item in items], ["a1"], items)
            item = self.for_key(summary, "update", key)
            self.assert_quiet(item)
            self.assertEqual(item.get("evidence"), "ush-health u2", item)
            self.assertEqual(item.get("accepted_on"), ACCEPTED_ON, item)

        with self.subTest("a later last of the same title + hresult is back"):
            # Two groups share the key (another result); the latest last counts.
            summary, _, _ = self.run_pass(
                [self.update_entry()],
                health=health_child([
                    other,
                    update_group("u2", U_TITLE, U_HRESULT, U_LATER_LAST),
                    update_group("u3", U_TITLE, U_HRESULT, U_LAST, result="Aborted",
                                 count=1)]))
            item = self.for_key(summary, "update", key)
            self.assert_back_with(item, "last", U_LAST, U_LATER_LAST)
            self.assertEqual(item.get("evidence"), "ush-health u2", item)

        with self.subTest("the later group listed after an older one is still back"):
            summary, _, _ = self.run_pass(
                [self.update_entry()],
                health=health_child([
                    update_group("u1", U_TITLE, U_HRESULT, U_LAST, result="Aborted",
                                 count=1),
                    update_group("u2", U_TITLE, U_HRESULT, U_LATER_LAST)]))
            item = self.for_key(summary, "update", key)
            self.assert_back_with(item, "last", U_LAST, U_LATER_LAST)

        with self.subTest("a group no longer present is gone"):
            # The same title fails with another hresult: a different key.
            summary, _, _ = self.run_pass(
                [self.update_entry()],
                health=health_child([other, update_group("u2", U_TITLE, "0x800F0922",
                                                         U_LATER_LAST)]))
            item = self.for_key(summary, "update", key)
            self.assert_state(item, "gone")
            self.assertIsNone(item.get("evidence"), item)

    # --- K2 --------------------------------------------------------------------------------

    def test_watched_fields(self):
        entries = [self.autostart_entry(), self.event_entry(), self.rule_entry()]
        event_key = ["Application", "Contoso-Agent", 7001]

        def run(task=None, group=None, rule=None):
            summary, _, _ = self.run_pass(
                entries,
                inventory=inventory_child([task or task_item()], [rule or rule_item()]),
                events=events_child([group or event_group()]),
                health=health_child([]))
            return (summary,
                    self.for_key(summary, "autostart", TASK_KEY),
                    self.for_key(summary, "event_group", event_key),
                    self.for_key(summary, "firewall_rule", RULE_KEY))

        with self.subTest("clean data: nothing changed is quiet"):
            summary, task, group, rule = run()
            self.assertEqual(sorted(item.get("id") for item in self.accepted_items(summary)),
                             ["a1", "a2", "a3"], summary.get("accepted"))
            for item in (task, group, rule):
                self.assert_quiet(item)
            self.assertEqual(task.get("evidence"), "ush-inventory s3", task)
            self.assertEqual(group.get("evidence"), "ush-events g4", group)
            self.assertEqual(rule.get("evidence"), "ush-inventory x2", rule)

        with self.subTest("autostart: a changed sha256 is back"):
            _, task, group, rule = run(task=task_item(helper_sha=SHA_HELPER_NEW))
            self.assert_state(task, "back")
            found = self.changed(task, lambda name: "sha256" in name)
            self.assertEqual(len(found), 1, task)
            self.assertEqual(found[0].get("accepted"), SHA_HELPER, task)
            self.assertEqual(found[0].get("now"), SHA_HELPER_NEW, task)
            self.assert_quiet(group)
            self.assert_quiet(rule)

        with self.subTest("autostart: a changed signer is back"):
            _, task, _, _ = run(task=task_item(main_signer=SIGNER_NEW))
            self.assert_state(task, "back")
            found = self.changed(task, lambda name: "signer" in name)
            self.assertEqual(len(found), 1, task)
            self.assertEqual(found[0].get("accepted"), SIGNER, task)
            self.assertEqual(found[0].get("now"), SIGNER_NEW, task)

        with self.subTest("autostart: a changed target path is back"):
            _, task, _, _ = run(task=task_item(main=TASK_MOVED))
            self.assert_state(task, "back")
            found = self.changed(task, lambda name: "path" in name or name == "targets")
            self.assertTrue(found, task)
            # Escaped as in the dump, so the backslashes of the path match.
            self.assertIn(json.dumps(TASK_MOVED)[1:-1],
                          json.dumps([entry.get("now") for entry in found]),
                          task)

        with self.subTest("event group: a risen count is back"):
            _, task, group, rule = run(group=event_group(count=15))
            self.assert_back_with(group, "count", 12, 15)
            self.assert_quiet(task)
            self.assert_quiet(rule)

        with self.subTest("event group: a later last is back"):
            _, _, group, _ = run(group=event_group(last=EVENT_LATER_LAST))
            self.assert_back_with(group, "last", EVENT_LAST, EVENT_LATER_LAST)

        with self.subTest("firewall rule: a changed program is back"):
            moved = "C:\\Users\\Public\\Fabrikam\\fsync.exe"
            _, task, group, rule = run(rule=rule_item(app=moved))
            self.assert_back_with(rule, "app", RULE_APP, moved)
            self.assert_quiet(task)
            self.assert_quiet(group)

        with self.subTest("firewall rule: a changed port is back"):
            _, _, _, rule = run(rule=rule_item(lport="8443"))
            self.assert_back_with(rule, "lport", "8080", "8443")

        with self.subTest("firewall rule: a changed state is back"):
            _, _, _, rule = run(rule=rule_item(active="FALSE"))
            self.assert_back_with(rule, "active", "TRUE", "FALSE")

    # --- K3 --------------------------------------------------------------------------------

    def test_not_read_is_not_quiet(self):
        event_key = ["Application", "Contoso-Agent", 7001]
        entries = [self.update_entry(), self.autostart_entry(), self.event_entry(),
                   self.rule_entry()]
        clean = {"health": health_child([update_group("u2", U_TITLE, U_HRESULT, U_LAST)]),
                 "inventory": inventory_child([task_item()], [rule_item()]),
                 "events": events_child([event_group()])}

        with self.subTest("children that did not run"):
            outcomes = {"ush-health": exits(1), "ush-events": exits(1),
                        "ush-inventory": exits(1)}
            summary, _, _ = self.run_pass(entries, outcomes, **clean)
            for skill in ("ush-health", "ush-events", "ush-inventory"):
                self.assertEqual(self.child(summary, skill).get("status"), "failed")
            for kind, key in (("update", [U_TITLE, U_HRESULT]), ("autostart", TASK_KEY),
                              ("event_group", event_key), ("firewall_rule", RULE_KEY)):
                with self.subTest(kind=kind):
                    self.assert_not_checked(self.for_key(summary, kind, key))

        with self.subTest("the update history was not read"):
            children = dict(clean, health=health_child(None, history_status="unreadable"))
            summary, _, _ = self.run_pass(entries, **children)
            self.assert_not_checked(self.for_key(summary, "update", [U_TITLE, U_HRESULT]))

        with self.subTest("a watched field that is null now is not back"):
            error = "Invented error: the file is being used by another process."
            children = dict(clean, inventory=inventory_child(
                [task_item(helper_sha=None, helper_sha_error=error)], [rule_item()]))
            summary, _, _ = self.run_pass(entries, **children)
            item = self.for_key(summary, "autostart", TASK_KEY)
            self.assertNotEqual(item.get("state"), "back", item)
            self.assertFalse(self.changed(item, lambda name: "sha256" in name), item)

        with self.subTest("autostart facts carried from the baseline"):
            children = dict(clean, inventory=inventory_child(
                [task_item(from_baseline=True)], [rule_item()]))
            summary, _, _ = self.run_pass(entries, **children)
            self.assert_not_checked(self.for_key(summary, "autostart", TASK_KEY))

        # --- plan 060, M2 code-review round 1 (orchestrator) -----------------------------

        with self.subTest("autostart facts listed in unread_fields"):
            item = task_item()
            item["unread_fields"] = ["facts"]
            children = dict(clean, inventory=inventory_child([item], [rule_item()]))
            summary, _, _ = self.run_pass(entries, **children)
            self.assert_not_checked(self.for_key(summary, "autostart", TASK_KEY))

        with self.subTest("a hash not read on both sides is not quiet"):
            error = "Invented error: access is denied."
            null_hash = task_item(helper_sha=None, helper_sha_error=error)
            accepted = [self.update_entry(), self.entry("autostart", null_hash,
                                                        "ush-inventory"),
                        self.event_entry(), self.rule_entry()]
            children = dict(clean, inventory=inventory_child([null_hash], [rule_item()]))
            summary, _, _ = self.run_pass(accepted, **children)
            item = self.for_key(summary, "autostart", TASK_KEY)
            self.assert_not_checked(item)
            self.assertIn("sha256", item.get("reason") or "", item)

    def test_missing_file_on_both_sides_is_quiet(self):
        """Clean data: a target that did not exist when accepted and still does not
        exist was read (nothing there), so the entry is quiet (plan 060, M2 code-review
        round 2)."""
        gone = r"C:\Program Files\Fabrikam\Removed\helper.exe"
        missing = {"path": gone, "expanded_path": gone, "exists": False,
                   "signature_status": None, "signer": None, "company": None,
                   "program": None, "sha256": None,
                   "sha256_error": "the file does not exist"}

        def item():
            built = task_item()
            built["targets"] = [TASK_MAIN, gone]
            built["facts"] = [built["facts"][0], dict(missing)]
            return built

        accepted = [self.update_entry(), self.entry("autostart", item(), "ush-inventory"),
                    self.event_entry(), self.rule_entry()]
        summary, _, _ = self.run_pass(
            accepted, health=health_child([update_group("u2", U_TITLE, U_HRESULT, U_LAST)]),
            inventory=inventory_child([item()], [rule_item()]),
            events=events_child([event_group()]))
        self.assert_quiet(self.for_key(summary, "autostart", TASK_KEY))

    # Regression of loc/inbox/060-plan-1-hard-accepted-findings-matching.md, Stuck gates,
    # M2 code-review (runall.py exempted exists false only on the current side).
    def test_unread_accepted_fact_now_missing_is_not_quiet(self):
        """A target whose facts were not confirmed when accepted (``exists`` null, every
        watched fact null) and that is missing now is not_checked, never quiet: a null on
        both sides is equal only when it was read on both sides (the kinds file
        ``_comment``; plan 060, M2 code-review, stuck point ``runall.py:871``). Written by
        loc-qa."""
        target = r"C:\Program Files\Fabrikam\Updater\fagent.exe"
        unconfirmed = {"path": target, "expanded_path": target, "exists": None,
                       "signature_status": None, "signer": None, "company": None,
                       "program": None, "sha256": None}
        missing = {"path": target, "expanded_path": target, "exists": False,
                   "signature_status": None, "signer": None, "company": None,
                   "program": None, "sha256": None,
                   "sha256_error": "the file does not exist"}

        def item(target_fact):
            built = task_item()
            built["targets"] = [TASK_MAIN, target]
            built["facts"] = [built["facts"][0], dict(target_fact)]
            return built

        accepted = [self.update_entry(),
                    self.entry("autostart", item(unconfirmed), "ush-inventory"),
                    self.event_entry(), self.rule_entry()]
        summary, _, _ = self.run_pass(
            accepted, health=health_child([update_group("u2", U_TITLE, U_HRESULT, U_LAST)]),
            inventory=inventory_child([item(missing)], [rule_item()]),
            events=events_child([event_group()]))
        self.assert_not_checked(self.for_key(summary, "autostart", TASK_KEY))

    def target_item(self, target_fact):
        target = target_fact["path"]
        built = task_item()
        built["targets"] = [TASK_MAIN, target]
        built["facts"] = [built["facts"][0], dict(target_fact)]
        return built

    def run_target(self, accepted_fact, now_fact):
        accepted = [self.update_entry(),
                    self.entry("autostart", self.target_item(accepted_fact), "ush-inventory"),
                    self.event_entry(), self.rule_entry()]
        summary, _, _ = self.run_pass(
            accepted, health=health_child([update_group("u2", U_TITLE, U_HRESULT, U_LAST)]),
            inventory=inventory_child([self.target_item(now_fact)], [rule_item()]),
            events=events_child([event_group()]))
        return self.for_key(summary, "autostart", TASK_KEY)

    # Regression: plan 060 final review (the accepted side kept no sha256_error, so a
    # hash that failed when accepted looked read).
    def test_hash_failed_when_accepted_now_missing_is_not_quiet(self):
        """A target that existed when accepted but whose hash could not be read
        (``sha256_error``), and that is missing now, is never quiet: it comes back
        with its exists change (both sides read), and the hash is not compared."""
        target = r"C:\Program Files\Fabrikam\Updater\fagent.exe"
        locked = fact(target, sha256=None, sha256_error="the file is in use")
        locked.update(signature_status=None, signer=None, company=None)  # only the hash differs
        missing = {"path": target, "expanded_path": target, "exists": False,
                   "signature_status": None, "signer": None, "company": None,
                   "program": None, "sha256": None,
                   "sha256_error": "the file does not exist"}
        item = self.run_target(locked, missing)
        self.assert_back_with(item, f"facts[{target}].exists", True, False)

    # Regression: plan 060 final review (facts[].exists was not watched).
    def test_target_missing_when_accepted_appears_is_back(self):
        """A target missing when accepted (read: nothing there) that exists now brings
        the entry back, with its exists change."""
        target = r"C:\Program Files\Fabrikam\Updater\fagent.exe"
        missing = {"path": target, "expanded_path": target, "exists": False,
                   "signature_status": None, "signer": None, "company": None,
                   "program": None, "sha256": None,
                   "sha256_error": "the file does not exist"}
        item = self.run_target(missing, fact(target))
        self.assert_back_with(item, f"facts[{target}].exists", False, True)
        # The appeared file's hash and signer were null when accepted: named as not
        # compared beside the change (plan 060 final review, round 2).
        self.assertIn(f"facts[{target}].sha256", item.get("skipped"), item)
        self.assertIn(f"facts[{target}].signer", item.get("skipped"), item)

    # Regression: loc/inbox/060-plan-1-hard-accepted-findings-matching.md (loc-qa round 2:
    # accepted.not_read_reason did not check the item's own from_baseline).
    def test_entry_carried_from_the_baseline_is_not_quiet(self):
        """An autostart entry that could not be read in this pass while its source was
        read (``from_baseline``: the whole item, facts included, is the previous
        baseline's; ush-inventory summary contract) is not_checked, never quiet: carried
        values are never compared (plan 060, M2). Written by loc-qa."""
        carried = task_item()
        carried["from_baseline"] = True
        accepted = [self.update_entry(), self.autostart_entry(), self.event_entry(),
                    self.rule_entry()]
        summary, _, _ = self.run_pass(
            accepted, health=health_child([update_group("u2", U_TITLE, U_HRESULT, U_LAST)]),
            inventory=inventory_child([carried], [rule_item()]),
            events=events_child([event_group()]))
        self.assert_not_checked(self.for_key(summary, "autostart", TASK_KEY))

    def test_other_reads_do_not_hide(self):
        """An unread field the kind does not keep, or another unread source of the same
        child, leaves an unchanged entry quiet (plan 060, M2 code-review round 1)."""
        event_key = ["Application", "Contoso-Agent", 7001]
        entries = [self.update_entry(), self.autostart_entry(), self.event_entry(),
                   self.rule_entry()]
        task = task_item()
        task["unread_fields"] = ["approved"]
        rule = rule_item()
        rule["unread_fields"] = ["app_exists"]
        events_detail, events_summary = events_child([event_group()])
        events_detail["sources"].append({"log": "Security", "pass": "B",
                                         "status": "unreadable",
                                         "reason": "needs administrator"})
        summary, _, _ = self.run_pass(
            entries, health=health_child([update_group("u2", U_TITLE, U_HRESULT, U_LAST)]),
            inventory=inventory_child([task], [rule]),
            events=(events_detail, events_summary))
        for kind, key in (("autostart", TASK_KEY), ("event_group", event_key),
                          ("firewall_rule", RULE_KEY)):
            with self.subTest(kind=kind):
                self.assert_quiet(self.for_key(summary, kind, key))

    # --- K4 --------------------------------------------------------------------------------

    def test_file_states(self):
        with self.subTest("no accepted.json"):
            summary, data_dir, _ = self.run_pass(None)
            self.assertFalse((data_dir / "state" / "accepted.json").exists())
            self.assertEqual(self.accepted_items(summary), [])
            self.assertEqual(self.accepted_items(self.detail(summary)), [])
            notes = [entry for entry in self.items(summary, "not_checked")
                     if "accepted.json" in json.dumps(entry)]
            self.assertEqual(notes, [], summary.get("not_checked"))

        with self.subTest("an unreadable accepted.json"):
            data_dir = self.data_dir()
            path = data_dir / "state" / "accepted.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version": 1, "entries": [{"kind": "update"',
                            encoding="utf-8")
            summary = self.collect(data_dir, AcceptedChildren(self.temp()))
            self.assertIn("accepted", summary, sorted(summary))
            self.assertIsNone(summary["accepted"], summary["accepted"])
            notes = [entry for entry in self.items(summary, "not_checked")
                     if "accepted.json" in json.dumps(entry)]
            self.assertEqual(len(notes), 1, summary.get("not_checked"))

        with self.subTest("--detail a1 prints the item"):
            summary, data_dir, fake = self.run_pass(
                [self.update_entry()],
                health=health_child([update_group("u2", U_TITLE, U_HRESULT, U_LAST)]))
            item = self.for_key(summary, "update", [U_TITLE, U_HRESULT])
            self.assertEqual(item.get("id"), "a1", item)
            in_detail = self.for_key(self.detail(summary), "update", [U_TITLE, U_HRESULT])
            self.assertEqual(in_detail.get("id"), "a1", in_detail)

            code, stdout, stderr = self.run_main(
                data_dir, fake, extra=("--detail", "a1", "--detail-file",
                                       summary["detail_file"]))
            self.assertEqual(code, 0, stderr[-500:])
            self.assertIn("quiet", stdout)
            self.assertIn(U_HRESULT, stdout)
            self.assertIn("KB5099002", stdout)


if __name__ == "__main__":
    unittest.main()

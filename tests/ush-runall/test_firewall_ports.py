"""Tests for the firewall rules against listening ports of skills/ush-runall/scripts/runall.py
(plan 098, M2).

Interface under test (from the plan):

- ``firewall_ports(inventory_detail, processes_detail, processes_summary)``: a pure function
  (no machine) that compares the inbound Allow rules of the ``ush-inventory`` detail file
  (items ``x...`` of ``additions``) with the TCP ports of the ``ush-processes`` detail file
  (``ports`` items ``p...``, each with ``group`` -> ``groups[].path``).
- A rule counts only when ``dir == "In"``, ``action == "Allow"`` and
  ``active.upper() == "TRUE"``; each such rule lands in exactly one counter, checked in the
  order ``udp``, ``other_protocol``, ``not_compared``, then ``matched`` / ``not_listening``.
- Matching: ``normcase(expandvars(app)) == normcase(group path)`` and ``lport`` is
  ``null``, ``*``, a number or range containing ``local_port``, or a list with such an
  element. A port with no group or a group with ``path: null`` counts in
  ``ports_without_path``.
- The runall summary gets ``firewall_ports`` (items ``w1``... for matched rules, sorted by
  the number after ``x``; each with ``rule``, ``rule_name``, ``program_path``, ``lport``,
  ``protocol``, ``profile``, ``app_exists``, ``listening`` [{port, local_address,
  local_port, scope}], ``loopback_only``), ``firewall_ports_counts`` {inbound_rules,
  matched, not_listening, not_compared, udp, other_protocol, ports_without_path} and
  ``network_categories`` (copied from the ``ush-processes`` summary). At most 50 items
  (``FIREWALL_PORTS_MAX``); the rest is counted in ``truncated``.
- When either child is not ``ok``, a detail file cannot be read, or the source
  ``firewall_rules`` / ``tcp_listeners`` is not ``read``/``empty``, ``firewall_ports`` and
  ``firewall_ports_counts`` are ``null`` and ``not_checked`` gets an entry.

Assumptions added by these tests beyond the plan text:

- ``firewall_ports`` returns either a dict with the keys ``firewall_ports`` and
  ``firewall_ports_counts``, or a pair ``(items, counts)``; both are accepted. Its items
  already carry their ``id`` (``w1``...). The tests of the pure function use fewer than 50
  matches, so it does not matter whether the 50-item limit is applied there or in ``main``.
- The rule fields in the ``ush-inventory`` detail file are named ``id``, ``kind``
  (``"firewall_rule"``), ``name``, ``action``, ``dir``, ``active``, ``protocol``, ``lport``,
  ``app``, ``svc``, ``profile`` and ``app_exists``; ``rule_name`` of a ``w`` item is the
  rule's ``name``. Another kind of addition (a Defender exclusion, no ``dir``) is not a rule.
- ``program_path`` of a ``w`` item is the rule's program in any of its equivalent forms
  (raw, expanded, or the group path): only ``normcase(expandvars(program_path))`` is
  compared.
- ``listening`` is compared without regard to order.
- The criterion lists ``x14`` (a list ``lport`` that matches ``p1``) among rules that give
  no ``w`` item, yet a matched rule gives an item. The base fixture therefore leaves
  ``x14`` out and has exactly one item ``w1``; adding ``x14`` is a separate case in which
  ``x14`` is matched to ``p1`` and becomes a second item.
- The ``sources`` of the fake child summary and of its detail file are the same list (as in
  M1's ``FakeChildren``); an unreadable source is set in both.
- The ``not_checked`` entry about a missing comparison mentions ``firewall`` or
  ``tcp_listeners`` somewhere in its JSON text (the plan: the source name and a reason).

Every value is invented; no process is started and nothing on the machine is read.
"""

import json
import os
import unittest
from unittest import mock

from .test_runall import FakeChildren, RunallTestCase, exits, ok

PROGRAM_RAW = "%ProgramFiles%\\Example\\srv.exe"
PROGRAM_EXPANDED = "C:\\PF\\Example\\srv.exe"
PROGRAM_GROUP_PATH = "c:\\pf\\example\\srv.exe"
SVCHOST_RAW = "%SystemRoot%\\system32\\svchost.exe"
SVCHOST_GROUP_PATH = "c:\\w\\system32\\svchost.exe"
FAKE_ENV = {"ProgramFiles": "C:\\PF", "SystemRoot": "C:\\W"}

COUNT_KEYS = ("matched", "not_listening", "not_compared", "udp", "other_protocol")


ABSENT = object()


def rule(n, app=PROGRAM_RAW, lport="8080", protocol=6, direction="In", action="Allow",
         active="TRUE", svc=None, profile=None, app_exists=True, lport2=ABSENT):
    """One firewall rule of the ush-inventory detail file, in the registry shape.

    ``lport2`` (the values of the rule's ``LPort2_*`` keys, or ``None``) is added only when
    given, so the rule without the argument has no ``lport2`` field at all.
    """
    result = {
        "id": f"x{n}",
        "key": f"firewall:local:{{invented-rule-{n}}}",
        "kind": "firewall_rule",
        "store": "local",
        "name": f"Invented rule {n}",
        "action": action,
        "dir": direction,
        "active": active,
        "protocol": protocol,
        "protocol_name": {6: "TCP", 17: "UDP"}.get(protocol),
        "lport": lport,
        "app": app,
        "svc": svc,
        "profile": profile,
        "app_exists": app_exists,
        "own": False,
        "unread_fields": [],
    }
    if lport2 is not ABSENT:
        result["lport2"] = lport2
    return result


def base_rules():
    """The K9 fixture without x12 and x14: exactly one rule (x2) is matched."""
    return [
        {"id": "x1", "key": "defender:path:c:\\invented cache", "kind": "defender_exclusion",
         "type": "path", "value": "C:\\Invented Cache", "origin": None, "own": False,
         "unread_fields": []},
        rule(2, profile="Private"),
        rule(3, active="FALSE"),
        rule(4, protocol=17),
        rule(5, lport="9090"),
        rule(6, lport="RPC"),
        rule(7, app=SVCHOST_RAW, svc="Example", protocol=6, lport=None),
        rule(8, app="%NIEZNANA%\\a.exe"),
        rule(9, app="C:\\PF\\Other\\b.exe"),
        rule(10, direction="Out"),
        rule(11, action="Block"),
        rule(13, app="", protocol=17),
        rule(15, lport=["9443", "RPC"]),
    ]


BASE_COUNTS = {
    "inbound_rules": 9,
    "matched": 1,
    "not_listening": 2,
    "not_compared": 4,
    "udp": 2,
    "other_protocol": 0,
    "ports_without_path": 1,
}

EMPTY_COUNTS = {"inbound_rules": 0, "matched": 0, "not_listening": 0, "not_compared": 0,
                "udp": 0, "other_protocol": 0, "ports_without_path": 0}


def group(gid, name, path):
    return {"id": gid, "name": name, "path": path,
            "path_kind": "file" if path else "none", "count": 1, "pids": [],
            "services": [], "autostart": [], "unread_fields": []}


def port(pid_item, local_address, local_port, scope, gid, process, pid):
    return {"id": pid_item, "protocol": "tcp", "local_address": local_address,
            "local_port": local_port, "scope": scope, "pid": pid, "process": process,
            "group": gid, "group_in_summary": True}


def base_groups():
    return [group("g1", "srv.exe", PROGRAM_GROUP_PATH),
            group("g2", "System", None),
            group("g3", "svchost.exe", SVCHOST_GROUP_PATH)]


def base_ports():
    return [port("p1", "127.0.0.1", 8080, "loopback", "g1", "srv.exe", 2100),
            port("p2", "0.0.0.0", 445, "all", "g2", "System", 4),
            port("p4", "0.0.0.0", 49670, "all", "g3", "svchost.exe", 1200)]


def inventory_detail(rules, status="read"):
    return {"sources": [{"name": "firewall_rules", "status": status, "reason": None}],
            "additions": list(rules)}


def processes_detail(groups, ports, status="read"):
    return {"sources": [{"name": "tcp_listeners", "status": status, "reason": None}],
            "groups": list(groups), "ports": list(ports)}


def processes_summary(network_categories=None, status="read"):
    summary = {"schema_version": 1, "skill": "ush-processes",
               "sources": [{"name": "tcp_listeners", "status": status, "reason": None}],
               "not_checked": [], "truncated": 0}
    if network_categories is not None:
        summary["network_categories"] = network_categories
    return summary


def listening(port_id, local_address, local_port, scope):
    return {"port": f"ush-processes {port_id}", "local_address": local_address,
            "local_port": local_port, "scope": scope}


P1 = listening("p1", "127.0.0.1", 8080, "loopback")


class FirewallChildren(FakeChildren):
    """M1's fake children, with chosen detail files for ush-inventory and ush-processes.

    ``inventory`` / ``processes`` replace the detail file content (its ``sources`` also
    become the summary's ``sources``); ``broken_inventory_detail`` writes a file that is
    not JSON instead.
    """

    def __init__(self, files_dir, outcomes=None, inventory=None, processes=None,
                 broken_inventory_detail=False):
        super().__init__(files_dir, outcomes)
        self.inventory = inventory
        self.processes = processes
        self.broken_inventory_detail = broken_inventory_detail

    def summary(self, skill, **kwargs):
        summary = super().summary(skill, **kwargs)
        detail_path = summary["detail_file"]
        content = {"ush-inventory": self.inventory,
                   "ush-processes": self.processes}.get(skill)
        if content is not None:
            summary["sources"] = content["sources"]
            with open(detail_path, "w", encoding="utf-8") as handle:
                json.dump(content, handle)
            with open(summary["summary_file"], "w", encoding="utf-8") as handle:
                json.dump(summary, handle)
        if skill == "ush-inventory" and self.broken_inventory_detail:
            with open(detail_path, "w", encoding="utf-8") as handle:
                handle.write("{invented: not json")
        return summary


class TestFirewallPorts(RunallTestCase):
    def compare(self, rules, groups, ports, summary=None):
        """Call the pure function; return (items, counts)."""
        with mock.patch.dict(os.environ, FAKE_ENV, clear=True):
            result = self.runall.firewall_ports(inventory_detail(rules),
                                                processes_detail(groups, ports),
                                                summary or processes_summary())
        if isinstance(result, dict):
            self.assertIn("firewall_ports", result, result)
            self.assertIn("firewall_ports_counts", result, result)
            items, counts = result["firewall_ports"], result["firewall_ports_counts"]
        else:
            self.assertIsInstance(result, (tuple, list), result)
            self.assertEqual(len(result), 2, result)
            items, counts = result
        self.assertIsInstance(items, list, items)
        self.assertIsInstance(counts, dict, counts)
        return items, counts

    def assert_item(self, item, item_id, rule_id, listens, loopback_only, profile=None,
                    lport="8080"):
        self.assertEqual(item.get("id"), item_id, item)
        self.assertEqual(item.get("rule"), f"ush-inventory {rule_id}", item)
        self.assertEqual(item.get("rule_name"), f"Invented rule {rule_id[1:]}", item)
        self.assertEqual(item.get("lport"), lport, item)
        self.assertEqual(item.get("protocol"), 6, item)
        self.assertIn("profile", item)
        self.assertEqual(item["profile"], profile, item)
        self.assertIs(item.get("app_exists"), True, item)
        program = item.get("program_path")
        self.assertIsInstance(program, str, item)
        with mock.patch.dict(os.environ, FAKE_ENV, clear=True):
            self.assertEqual(os.path.normcase(os.path.expandvars(program)),
                             os.path.normcase(PROGRAM_EXPANDED), item)
        got = item.get("listening")
        self.assertIsInstance(got, list, item)
        def key(entry):
            return json.dumps(entry, sort_keys=True)

        self.assertEqual(sorted(got, key=key), sorted(listens, key=key), item)
        self.assertIs(item.get("loopback_only"), loopback_only, item)

    def assert_counts_add_up(self, counts):
        self.assertEqual(counts["inbound_rules"], sum(counts[k] for k in COUNT_KEYS), counts)

    def test_rules_against_ports(self):
        with self.subTest("fixture: only x2 is matched, to p1 on loopback"):
            items, counts = self.compare(base_rules(), base_groups(), base_ports())
            self.assertEqual(len(items), 1, items)
            self.assert_item(items[0], "w1", "x2", [P1], True, profile="Private")
            self.assertEqual(counts, BASE_COUNTS)
            self.assert_counts_add_up(counts)

        with self.subTest("x14: a list lport with 8080 is matched to p1"):
            rules = base_rules() + [rule(14, lport=["8080", "9443"])]
            items, counts = self.compare(rules, base_groups(), base_ports())
            self.assertEqual([item.get("rule") for item in items],
                             ["ush-inventory x2", "ush-inventory x14"], items)
            self.assert_item(items[1], "w2", "x14", [P1], True, lport=["8080", "9443"])
            self.assertEqual(counts, dict(BASE_COUNTS, inbound_rules=10, matched=2))
            self.assert_counts_add_up(counts)

        with self.subTest("p3 on all addresses: loopback_only false"):
            ports = base_ports() + [port("p3", "0.0.0.0", 8080, "all", "g1", "srv.exe", 2100)]
            items, counts = self.compare(base_rules(), base_groups(), ports)
            self.assertEqual(len(items), 1, items)
            self.assert_item(items[0], "w1", "x2",
                             [P1, listening("p3", "0.0.0.0", 8080, "all")], False,
                             profile="Private")
            self.assertEqual(counts, BASE_COUNTS)

        with self.subTest("order by the number after x: x2 before x12"):
            rules = base_rules() + [rule(12)]
            items, counts = self.compare(rules, base_groups(), base_ports())
            self.assertEqual([(item.get("id"), item.get("rule")) for item in items],
                             [("w1", "ush-inventory x2"), ("w2", "ush-inventory x12")])
            self.assertEqual(counts, dict(BASE_COUNTS, inbound_rules=10, matched=2))
            self.assert_counts_add_up(counts)

        with self.subTest("clean: no rule matches, no item"):
            rules = [rule(5, lport="9090"), rule(9, app="C:\\PF\\Other\\b.exe")]
            items, counts = self.compare(rules, base_groups(), base_ports())
            self.assertEqual(items, [])
            self.assertEqual(counts, dict(EMPTY_COUNTS, inbound_rules=2, not_listening=2,
                                          ports_without_path=1))

        with self.subTest("main: the runall summary carries the comparison"):
            fake = FirewallChildren(
                self.temp(), inventory=inventory_detail(base_rules()),
                processes=processes_detail(base_groups(), base_ports()))
            with mock.patch.dict(os.environ, FAKE_ENV, clear=True):
                summary = self.collect(self.data_dir(), fake)
            items = self.items(summary, "firewall_ports")
            self.assertEqual(len(items), 1, items)
            self.assert_item(items[0], "w1", "x2", [P1], True, profile="Private")
            self.assertEqual(summary.get("firewall_ports_counts"), BASE_COUNTS)
            # p2 belongs to System, which has no image file (path_kind "none"): that is
            # not an unread path, so no entry (code review of M2, round 2).
            self.assertEqual(summary.get("not_checked"), [])

        # A group with an image file whose path could not be read (code review of M2).
        unread_group = dict(group("g4", "vendor.exe", None), path_kind="file",
                            unread_fields=["path"])
        unread_port = port("p5", "0.0.0.0", 5432, "all", "g4", "vendor.exe", 3300)

        with self.subTest("main: an unread program path and not_listening rules: one entry"):
            fake = FirewallChildren(
                self.temp(), inventory=inventory_detail(base_rules()),
                processes=processes_detail(base_groups() + [unread_group],
                                           base_ports() + [unread_port]))
            with mock.patch.dict(os.environ, FAKE_ENV, clear=True):
                summary = self.collect(self.data_dir(), fake)
            notes = summary.get("not_checked")
            self.assertEqual(len(notes), 1, notes)
            self.assertIn("tcp_listeners", json.dumps(notes[0]))
            self.assertIn("not_listening", notes[0]["reason"])

        with self.subTest("main: an unread program path and no not_listening rule: no entry"):
            fake = FirewallChildren(
                self.temp(), inventory=inventory_detail(
                    [rule for rule in base_rules() if rule.get("id") not in ("x5", "x9")]),
                processes=processes_detail(base_groups() + [unread_group],
                                           base_ports() + [unread_port]))
            with mock.patch.dict(os.environ, FAKE_ENV, clear=True):
                summary = self.collect(self.data_dir(), fake)
            self.assertEqual(summary["firewall_ports_counts"]["not_listening"], 0)
            self.assertEqual(summary.get("not_checked"), [])

        # Final review of plan 098: a port without a known process (the process list
        # was not read, or the process started after it) is not compared either.
        for label, groups, extra in (
                ("a port without a group", base_groups(),
                 [port("p6", "0.0.0.0", 5433, "all", None, None, 3400)]),
                ("no group read at all", [], [])):
            with self.subTest(f"main: {label} and not_listening rules: one entry"):
                fake = FirewallChildren(
                    self.temp(), inventory=inventory_detail(base_rules()),
                    processes=processes_detail(groups, base_ports() + extra))
                with mock.patch.dict(os.environ, FAKE_ENV, clear=True):
                    summary = self.collect(self.data_dir(), fake)
                notes = summary.get("not_checked")
                self.assertEqual(len(notes), 1, notes)
                self.assertIn("tcp_listeners", json.dumps(notes[0]))
                self.assertIn("not_listening", notes[0]["reason"])

        # Final review of plan 098: a rule the inventory could not read is in no counter,
        # so it gets an entry instead of vanishing.
        unread_rule = {"id": "x30", "key": "firewall:local:{invented-rule-30}",
                       "kind": "firewall_rule", "store": "local", "name": None,
                       "action": None, "dir": None, "active": None, "protocol": None,
                       "protocol_name": None, "lport": None, "app": None, "svc": None,
                       "profile": None, "version": None, "own": False,
                       "unread_fields": ["rule", "action", "dir", "active"]}
        for label, extra in (("a rule text that is no v2. rule", unread_rule),
                             ("a rule with two Dir values", rule(31, direction=["In", "In"]))):
            with self.subTest(f"main: {label}: one entry, counts unchanged"):
                fake = FirewallChildren(
                    self.temp(), inventory=inventory_detail(base_rules() + [extra]),
                    processes=processes_detail(base_groups(), base_ports()))
                with mock.patch.dict(os.environ, FAKE_ENV, clear=True):
                    summary = self.collect(self.data_dir(), fake)
                self.assertEqual(summary.get("firewall_ports_counts"), BASE_COUNTS)
                notes = summary.get("not_checked")
                self.assertEqual(len(notes), 1, notes)
                self.assertIn("firewall_rules", notes[0]["what"])
                self.assertIn("1 firewall rules", notes[0]["reason"])

        with self.subTest("App=System is not compared, even with System listening on 445"):
            rules = [rule(20, app="System", lport="445")]
            items, counts = self.compare(rules, base_groups(), base_ports())
            self.assertEqual(items, [])
            self.assertEqual(counts, dict(EMPTY_COUNTS, inbound_rules=1, not_compared=1,
                                          ports_without_path=1))

        with self.subTest("main clean: empty details give [] and no not_checked entry"):
            summary = self.collect(self.data_dir(), FakeChildren(self.temp()))
            self.assertEqual(summary.get("firewall_ports"), [])
            self.assertEqual(summary.get("firewall_ports_counts"), EMPTY_COUNTS)
            self.assertEqual(summary.get("not_checked"), [])
            self.assertEqual(summary.get("truncated"), 0)

    def firewall_notes(self, summary):
        return [entry for entry in self.items(summary, "not_checked")
                if "firewall" in json.dumps(entry).lower()
                or "tcp_listeners" in json.dumps(entry)]

    def assert_not_compared(self, summary, source=None):
        self.assertIn("firewall_ports", summary)
        self.assertIsNone(summary["firewall_ports"], summary.get("firewall_ports"))
        self.assertIn("firewall_ports_counts", summary)
        self.assertIsNone(summary["firewall_ports_counts"])
        notes = self.firewall_notes(summary)
        self.assertTrue(notes, summary.get("not_checked"))
        if source is not None:
            self.assertTrue(any(source in json.dumps(entry) for entry in notes), notes)

    def test_missing_inputs(self):
        clean_inventory = inventory_detail([rule(2, app=PROGRAM_EXPANDED)])
        clean_processes = processes_detail(base_groups(), base_ports())

        with self.subTest("ush-processes exits 1"):
            fake = FirewallChildren(self.temp(), {"ush-processes": exits(1)},
                                    inventory=clean_inventory, processes=clean_processes)
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-processes").get("status"), "failed")
            self.assert_not_compared(summary)

        with self.subTest("ush-inventory detail file is not readable"):
            fake = FirewallChildren(self.temp(), inventory=clean_inventory,
                                    processes=clean_processes, broken_inventory_detail=True)
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-inventory").get("status"), "ok")
            self.assert_not_compared(summary)

        with self.subTest("ush-inventory ok, firewall_rules unreadable"):
            fake = FirewallChildren(
                self.temp(),
                inventory=inventory_detail([rule(2, app=PROGRAM_EXPANDED)], status="unreadable"),
                processes=clean_processes)
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-inventory").get("status"), "ok")
            self.assert_not_compared(summary, "firewall_rules")

        with self.subTest("ush-processes ok, tcp_listeners unreadable"):
            fake = FirewallChildren(
                self.temp(), inventory=clean_inventory,
                processes=processes_detail(base_groups(), base_ports(), status="unreadable"))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-processes").get("status"), "ok")
            self.assert_not_compared(summary, "tcp_listeners")

        with self.subTest("network_categories copied from ush-processes"):
            fake = FirewallChildren(
                self.temp(), {"ush-processes": ok(extra={"network_categories": {"Private": 1}})},
                inventory=clean_inventory, processes=clean_processes)
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(summary.get("network_categories"), {"Private": 1})

        with self.subTest("60 matched rules: 50 items and truncated 10"):
            rules = [rule(n, app=PROGRAM_EXPANDED) for n in range(1, 61)]
            fake = FirewallChildren(self.temp(), inventory=inventory_detail(rules),
                                    processes=clean_processes)
            summary = self.collect(self.data_dir(), fake)
            items = self.items(summary, "firewall_ports")
            self.assertEqual(len(items), 50, len(items))
            self.assertEqual([item.get("id") for item in items],
                             [f"w{n}" for n in range(1, 51)])
            self.assertEqual([item.get("rule") for item in items],
                             [f"ush-inventory x{n}" for n in range(1, 51)])
            self.assertEqual(summary.get("truncated"), 10)
            self.assertEqual(summary.get("firewall_ports_counts", {}).get("matched"), 60)

    # A rule with LPort2_* keys (``lport2``) is not compared; absent or null keeps matching.
    LPORT2_CASES = (
        ("lport null, lport2 a range", None, ["5000-5010"]),
        ("lport 8080 (listening), lport2 a keyword", "8080", ["IPHTTPSIn"]),
    )

    def test_lport2_not_compared(self):
        for label, lport, lport2 in self.LPORT2_CASES:
            with self.subTest(f"alone: {label}"):
                rules = [rule(16, lport=lport, lport2=lport2)]
                items, counts = self.compare(rules, base_groups(), base_ports())
                self.assertEqual(items, [])
                self.assertEqual(counts, dict(EMPTY_COUNTS, inbound_rules=1, not_compared=1,
                                              ports_without_path=1))
                self.assert_counts_add_up(counts)

            with self.subTest(f"with the fixture: {label}"):
                rules = base_rules() + [rule(16, lport=lport, lport2=lport2)]
                items, counts = self.compare(rules, base_groups(), base_ports())
                self.assertEqual([item.get("rule") for item in items],
                                 ["ush-inventory x2"], items)
                self.assert_item(items[0], "w1", "x2", [P1], True, profile="Private")
                self.assertEqual(counts, dict(BASE_COUNTS, inbound_rules=10,
                                              not_compared=BASE_COUNTS["not_compared"] + 1))
                self.assert_counts_add_up(counts)

    def test_lport2_absent_keeps_match(self):
        for label, lport, _ in self.LPORT2_CASES:
            for variant, lport2 in (("no lport2 field", ABSENT), ("lport2 null", None)):
                extra = rule(16, lport=lport, lport2=lport2)
                if lport2 is ABSENT:
                    self.assertNotIn("lport2", extra)
                with self.subTest(f"alone: {label}, {variant}"):
                    items, counts = self.compare([extra], base_groups(), base_ports())
                    self.assertEqual(len(items), 1, items)
                    self.assert_item(items[0], "w1", "x16", [P1], True, lport=lport)
                    self.assertEqual(counts, dict(EMPTY_COUNTS, inbound_rules=1, matched=1,
                                                  ports_without_path=1))
                    self.assert_counts_add_up(counts)

        for variant, lport2 in (("no lport2 field", ABSENT), ("lport2 null", None)):
            with self.subTest(f"fixture, x2 with {variant}: counts as today"):
                rules = [rule(2, profile="Private", lport2=lport2)
                         if item.get("id") == "x2" else item for item in base_rules()]
                items, counts = self.compare(rules, base_groups(), base_ports())
                self.assertEqual(len(items), 1, items)
                self.assert_item(items[0], "w1", "x2", [P1], True, profile="Private")
                self.assertEqual(counts, BASE_COUNTS)
                self.assert_counts_add_up(counts)


if __name__ == "__main__":
    unittest.main()

"""The ``lport2`` field of a firewall rule in skills/ush-inventory/scripts/inventory.py
(plan 134, milestone M2, criteria K4, K5, K9): the values of the rule's ``LPort2_*``
keys, kept in the detail file and never compared with the baseline.

PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.
"""

import json
import unittest
from datetime import timedelta

from tests.skill_loader import REPO_ROOT

from .fakes import NOW, FakePowerShell, ok
from .fakes_additions import (
    FIREWALL_BUILTIN,
    AdditionsTestCase,
    firewall_result,
    fw_value,
    m2_responses,
    rule_text,
)

RULE = "{00000000-0000-0000-0000-00000000E134}"
KEY = f"firewall:local:{RULE}"
INVENTORY_CONTRACT = REPO_ROOT / "skills" / "ush-inventory" / "references" / "summary-contract.md"
RUNALL_CONTRACT = REPO_ROOT / "skills" / "ush-runall" / "references" / "summary-contract.md"
RUNALL_FORMAT = REPO_ROOT / "skills" / "ush-runall" / "references" / "report-format.md"


def server_rule(*extra):
    """An inbound Allow TCP rule a user added, with ``extra`` key/value pairs."""
    return rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "In"),
                      ("Protocol", "6"), *extra, ("App", "C:\\Apps\\x.exe"), ("Name", "X")])


def strip_field(data, field):
    """``data`` with ``field`` removed from every object, as an older run wrote it."""
    if isinstance(data, dict):
        return {key: strip_field(value, field) for key, value in data.items() if key != field}
    if isinstance(data, list):
        return [strip_field(value, field) for value in data]
    return data


class TestFirewallLport2(AdditionsTestCase):
    def parse_rule(self, text):
        return self.inventory.parse_firewall_rule(text, FIREWALL_BUILTIN)

    def test_parse_lport2(self):
        rule = self.parse_rule(server_rule(("LPort2_10", "IPHTTPSIn"), ("LPort2_10", "IPTLSIn")))
        self.assertIsNone(rule.get("lport"), rule)
        self.assertIn("lport2", rule, rule)
        self.assertEqual(rule["lport2"], ["IPHTTPSIn", "IPTLSIn"], rule)

        with self.subTest("keys in order, values in order within a key"):
            rule = self.parse_rule(server_rule(("LPort2_20", "B1"), ("LPort2_10", "A1"),
                                          ("LPort2_20", "B2")))
            self.assertEqual(rule.get("lport2"), ["B1", "B2", "A1"], rule)

        with self.subTest("only LPort"):
            rule = self.parse_rule(server_rule(("LPort", "8080")))
            self.assertIn("lport2", rule, rule)
            self.assertIsNone(rule["lport2"], rule)
            self.assertEqual(rule.get("lport"), "8080", rule)

        with self.subTest("not a v2. rule"):
            rule = self.parse_rule("garbage")
            self.assertIn("lport2", rule, rule)
            self.assertIsNone(rule["lport2"], rule)

    def test_lport2_not_compared(self):
        data_dir = self.data_dir()
        first = self.collect(FakePowerShell(m2_responses(firewall_rules=ok(firewall_result(
            local=[fw_value(RULE, server_rule())])))), data_dir=data_dir, now=NOW)
        self.assertEqual(self.source(first, "firewall_rules").get("status"), "read")
        state = data_dir / "state" / "ush-inventory.json"
        self.assertTrue(state.is_file(), state)
        old = json.loads(state.read_text(encoding="utf-8-sig"))
        state.write_text(json.dumps(strip_field(old, "lport2")), encoding="utf-8")
        self.assertNotIn('"lport2"', state.read_text(encoding="utf-8"))

        second = self.collect(FakePowerShell(m2_responses(firewall_rules=ok(firewall_result(
            local=[fw_value(RULE, server_rule(("LPort2_10", "IPHTTPSIn")))])))),
            data_dir=data_dir, now=NOW + timedelta(days=1))
        changes = [c for c in self.changes(second) if c.get("key") == KEY]
        self.assertEqual(changes, [], changes)

        listed = [item for item in self.additions_of(second, "firewall_rule")
                  if item.get("key") == KEY]
        self.assertEqual(len(listed), 1, self.additions_of(second, "firewall_rule"))
        self.assertNotIn("lport2", listed[0], listed[0])

        detail = [item for item in self.detail_additions_of(second, "firewall_rule")
                  if item.get("key") == KEY]
        self.assertEqual(len(detail), 1, detail)
        self.assertEqual(detail[0].get("lport2"), ["IPHTTPSIn"], detail[0])

        self.assertNotIn("lport2", self.inventory.COMPARED_FIELDS["firewall_rules"])
        self.assertNotIn("lport2", self.inventory.FIREWALL_SUMMARY)

    def test_contracts_name_lport2(self):
        rows = [line for line in INVENTORY_CONTRACT.read_text(encoding="utf-8").splitlines()
                if line.startswith("| `lport2`")]
        self.assertEqual(len(rows), 1, rows)

        rows = [line for line in RUNALL_CONTRACT.read_text(encoding="utf-8").splitlines()
                if line.startswith("| `not_compared`")]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("lport2", rows[0])

        lines = [line for line in RUNALL_FORMAT.read_text(encoding="utf-8").splitlines()
                 if "`lport`" in line and "null" in line]
        self.assertTrue(any("lport2" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()

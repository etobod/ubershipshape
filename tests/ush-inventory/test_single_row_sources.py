"""One-row answer of the ``firewall_apps`` source added in plan 107 (M2): ConvertTo-Json
writes a single object, not a list, when the job has one row. It must be read like a
one-element list.

PowerShell never starts; every value is invented.
"""

import unittest

from .fakes import FakePowerShell, ok
from .fakes_additions import (
    AdditionsTestCase,
    custom_rule,
    firewall_result,
    fw_value,
    m2_responses,
)
from .test_review_notes import APP_PRESENT, app_row, firewall_key, rule_name


class TestSingleRowSources(AdditionsTestCase):
    def test_firewall_apps_single_object(self):
        name = rule_name(201)
        firewall = firewall_result(local=[
            fw_value(name, custom_rule("Invented Present", app=APP_PRESENT))])
        summary = self.collect(FakePowerShell(m2_responses(
            firewall_rules=ok(firewall),
            firewall_apps=ok(app_row(APP_PRESENT, APP_PRESENT, True)))))
        rules = self.by_key(self.additions_of(summary, "firewall_rule"))
        item = rules.get(firewall_key("local", name))
        self.assertIsNotNone(item, sorted(map(str, rules)))
        self.assertIs(item.get("app_exists"), True, item)
        self.assertFalse(item.get("unread_fields"), item)
        self.assertEqual(
            [n for n in self.not_checked(summary) if "firewall_apps" in str(n)], [],
            self.not_checked(summary))


if __name__ == "__main__":
    unittest.main()

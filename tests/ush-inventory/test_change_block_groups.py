"""Which additions build_additions puts in the group with a change block (plan 074,
M1): the rules of SKILL.md that depend on the whole source, not on one item, and
Administrators members kept in the first group."""

import unittest

from tests.skill_loader import load_script

INV = load_script("ush-inventory", "inventory")

THUMB = "0123456789ABCDEF0123456789ABCDEF01234567"


def local_rule():
    return {"firewall_rules": {"firewall:local:{00000000-0000-0000-0000-00000000A001}": {
        "store": "local", "name": "Invented Sync TCP in", "enabled": True}}}


def blocked_keys(current, method=None):
    """The keys of the listed additions in the group with a change block."""
    additions, listed = INV.build_additions(current, method)
    context = INV.block_context(current, method)
    return {e["key"] for e in additions[:listed] if INV.has_change_block(e, context)}


class TestChangeBlockGroups(unittest.TestCase):
    def test_local_items_have_a_block(self):
        current = {**local_rule(),
                   "defender_exclusions": {"defender:path:C:\\Invented": {
                       "type": "path", "value": "C:\\Invented", "origin": "local"}},
                   "root_certificates": {f"cert:machine_root:{THUMB}": {
                       "store": "machine_root", "thumbprint": THUMB,
                       "in_authroot": False}},
                   "administrators": {
                       "admin:S-1-5-21-0-0-0-1002": {"enabled": True, "is_current": False}}}
        self.assertEqual(blocked_keys(current, "preference"), {
            "firewall:local:{00000000-0000-0000-0000-00000000A001}",
            "defender:path:C:\\Invented", f"cert:machine_root:{THUMB}",
            "admin:S-1-5-21-0-0-0-1002"})

    def test_defender_registry_method_has_no_block(self):
        current = {**local_rule(), "defender_exclusions": {"defender:path:C:\\Invented": {
            "type": "path", "value": "C:\\Invented", "origin": "local"}}}
        for method in ("registry", None):
            with self.subTest(method=method):
                self.assertNotIn("defender:path:C:\\Invented", blocked_keys(current, method))

    def test_certificate_in_another_store_has_no_block(self):
        current = {"root_certificates": {
            f"cert:machine_root:{THUMB}": {"store": "machine_root", "thumbprint": THUMB,
                                           "in_authroot": False},
            f"cert:enterprise:{THUMB}": {"store": "enterprise", "thumbprint": THUMB}}}
        self.assertEqual(blocked_keys(current), set())

    def test_every_member_is_in_the_first_group(self):
        current = {"administrators": {
            "admin:S-1-5-21-0-0-0-1001": {"enabled": True, "is_current": True},
            "admin:S-1-5-21-0-0-0-1002": {"enabled": None, "is_current": None}}}
        self.assertEqual(blocked_keys(current), set(current["administrators"]))

    def test_blockless_items_come_after(self):
        current = {**local_rule(), "defender_exclusions": {"defender:path:C:\\Invented": {
            "type": "path", "value": "C:\\Invented", "origin": "local"}}}
        additions, listed = INV.build_additions(current, "registry")
        self.assertEqual([e["key"] for e in additions[:listed]], [
            "firewall:local:{00000000-0000-0000-0000-00000000A001}",
            "defender:path:C:\\Invented"])


if __name__ == "__main__":
    unittest.main()

"""Firewall rules, root certificates, hosts, Administrators and Defender exclusions of
skills/ush-inventory/scripts/inventory.py (plan 052, milestone M2, criteria K1-K7, K9,
K10; K8 is in ``test_budget.py``). ``TestFirstRunCertificates``: plan 083, milestone M2,
criteria K11-K21 (Authenticode Root trusted on the first run).

The interface these tests assume is listed in ``fakes.py``, ``fakes_components.py`` and
``fakes_additions.py``. PowerShell never starts; every baseline lives in a temporary
directory; every value is invented.
"""

import inspect
import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, FakePowerShell, failure, ok
from .fakes_additions import (
    CURRENT_SID,
    FIREWALL_BUILTIN,
    SHIPPED_THUMBPRINTS,
    AdditionsTestCase,
    admins_result,
    builtin_rule,
    cert,
    certificates_result,
    custom_rule,
    defender_result,
    firewall_result,
    fw_store,
    fw_value,
    hosts_result,
    m2_responses,
    member,
    rule_text,
    store_app_rule,
    thumb,
)
from .fakes_components import ENABLED, capability, driver, feature
from .test_shipped_thumbprints import (
    AUTHENTICODE_CN,
    FIRST_RUN_KEY,
    REQUIRED_SUBJECTS,
    WINDOWS_OWN,
    shipped_entries,
)


def fake(**overrides):
    return FakePowerShell(m2_responses(**overrides))


def firewall_key(store, name):
    return f"firewall:{store}:{name}"


class TestFirewall(AdditionsTestCase):
    def parse_rule(self, text):
        parse = getattr(self.inventory, "parse_firewall_rule", None)
        self.assertIsNotNone(parse, "inventory has no parse_firewall_rule")
        required = [
            p for p in inspect.signature(parse).parameters.values()
            if p.default is p.empty
            and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        result = parse(text) if len(required) <= 1 else parse(text, FIREWALL_BUILTIN)
        self.assertIsInstance(result, dict, f"parse_firewall_rule({text!r}): {result!r}")
        return result

    def test_parse_and_own(self):
        rule = self.parse_rule(
            "v2.33|Action=Allow|Active=TRUE|Dir=In|Protocol=6|LPort=8080|LPort=8081|"
            "App=C:\\Apps\\x.exe|Name=X Server|"
        )
        self.assertEqual(rule.get("action"), "Allow", rule)
        self.assertEqual(rule.get("protocol_name"), "TCP", rule)
        self.assertEqual(rule.get("lport"), ["8080", "8081"], rule)
        self.assertEqual(rule.get("name"), "X Server", rule)
        self.assertIn("own", rule, rule)
        self.assertIs(rule.get("own"), False, rule)

        builtin = self.parse_rule(
            "v2.33|Action=Allow|Active=TRUE|Dir=In|Protocol=17|LPort=5353|"
            "EmbedCtxt=@FirewallAPI.dll,-1|Name=@FirewallAPI.dll,-2|"
        )
        self.assertIs(builtin.get("own"), True, builtin)

        no_context = self.parse_rule("v2.33|Action=Block|Active=TRUE|Dir=Out|Name=@x|")
        self.assertIn("own", no_context, no_context)
        self.assertIs(no_context.get("own"), False, no_context)

        garbage = self.parse_rule("garbage")
        self.assertIn("rule", garbage.get("unread_fields") or [], garbage)
        for field in ("action", "dir", "name"):
            self.assertIn(field, garbage, garbage)
            self.assertIsNone(garbage.get(field), garbage)
        self.assertIn("own", garbage, garbage)
        self.assertIs(garbage.get("own"), False, garbage)

    def test_stores_and_clean(self):
        named_a = "{00000000-0000-0000-0000-00000000A001}"
        named_b = "{00000000-0000-0000-0000-00000000A002}"
        broken = "{00000000-0000-0000-0000-00000000A003}"
        builtin_local = "InventedBuiltin-In-UDP"
        store_builtin = "{00000000-0000-0000-0000-00000000B001}"
        store_custom = "{00000000-0000-0000-0000-00000000B002}"
        result = firewall_result(
            local=[
                fw_value(named_a, custom_rule("Invented Alpha Server", port="8080")),
                fw_value(broken, "garbage"),
                fw_value(named_b, custom_rule("Invented Bravo Server", port="8081")),
                fw_value(builtin_local, builtin_rule(1)),
            ],
            app_iso=[
                fw_value(store_builtin, rule_text([
                    ("Action", "Allow"), ("Active", "TRUE"), ("Dir", "Out"),
                    ("EmbedCtxt", "@{Example.App_1.0.0.0_x64__abc}"),
                    ("Name", "@{Example.App_1.0.0.0_x64__abc?ms-resource://x}"),
                ], version="v2.31")),
                fw_value(store_custom, rule_text([
                    ("Action", "Allow"), ("Active", "TRUE"), ("Dir", "Out"),
                    ("Name", "Invented Store App Rule"),
                ], version="v2.31")),
            ],
            policy=None,
        )
        summary = self.collect(fake(firewall_rules=ok(result)))

        self.assertEqual(self.source(summary, "firewall_rules").get("status"), "read")
        listed = self.additions_of(summary, "firewall_rule")
        keys = [item.get("key") for item in listed]
        for key in (firewall_key("local", named_a), firewall_key("local", named_b),
                    firewall_key("local", broken), firewall_key("app_iso", store_custom)):
            self.assertIn(key, keys, listed)
        self.assertNotIn(firewall_key("app_iso", store_builtin), keys, listed)
        self.assertNotIn(firewall_key("local", builtin_local), keys, listed)

        app_item = listed[keys.index(firewall_key("app_iso", store_custom))]
        self.assertEqual(app_item.get("store"), "app_iso", app_item)

        # The unparsable rule has no name and comes after the named rules of its store.
        local_keys = [item.get("key") for item in listed if item.get("store") == "local"]
        self.assertEqual(local_keys[-1], firewall_key("local", broken), listed)
        self.assertEqual(set(local_keys[:-1]),
                         {firewall_key("local", named_a), firewall_key("local", named_b)},
                         listed)

        detail = self.by_key(self.detail_additions_of(summary, "firewall_rule"))
        store_rule = detail.get(firewall_key("app_iso", store_builtin))
        self.assertIsNotNone(store_rule, sorted(map(str, detail)))
        self.assertIs(store_rule.get("own"), True, store_rule)

        with self.subTest(case="clean machine"):
            clean = firewall_result(
                local=[fw_value(f"InventedBuiltin-{n}", builtin_rule(n)) for n in range(4)],
                app_iso=[fw_value(f"{{00000000-0000-0000-0000-0000000C{n:04d}}}",
                                  store_app_rule(n)) for n in range(3)],
                policy=None,
            )
            summary = self.collect(fake(firewall_rules=ok(clean)))
            self.assertEqual(self.additions_of(summary, "firewall_rule"), [])
            counts = self.own_counts(summary).get("firewall_rules")
            self.assertIsInstance(counts, dict, f"own_counts.firewall_rules: {counts!r}")
            self.assertEqual(counts.get("local"), 4, counts)
            self.assertEqual(counts.get("app_iso"), 3, counts)

    def test_summary_tells_icmp_from_any_protocol(self):
        icmp = rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "In"),
                          ("Protocol", "1"), ("Name", "Invented Ping")])
        anything = rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "In"),
                              ("Name", "Invented Any")])
        summary = self.collect(fake(firewall_rules=ok(firewall_result(
            local=[fw_value("InventedPing", icmp), fw_value("InventedAny", anything)]))))
        by_name = {item.get("name"): item for item in self.additions_of(summary, "firewall_rule")}
        self.assertEqual(by_name.get("Invented Ping", {}).get("protocol"), 1, by_name)
        self.assertIn("protocol", by_name.get("Invented Any", {}), by_name)
        self.assertIsNone(by_name.get("Invented Any", {}).get("protocol"), by_name)


class TestCertificates(AdditionsTestCase):
    def cert_key(self, store, thumbprint):
        return f"cert:{store}:{thumbprint}"

    def test_stores_authroot_and_unread_details(self):
        machine = thumb(0xA01)
        user = thumb(0xA02)
        auth = thumb(0xA03)
        summary = self.collect(fake(root_certificates=ok(certificates_result(
            machine_root=[cert(machine, subject="CN=Invented Self Root")],
            user_root=[cert(user, subject="CN=Invented User Root",
                            issuer="CN=Invented Other CA")],
            authroot=[cert(auth, subject="CN=Invented Auth Root")],
        ))))

        listed = self.by_key(self.additions_of(summary, "root_certificate"))
        self.assertEqual(set(listed), {self.cert_key("machine_root", machine),
                                       self.cert_key("user_root", user)}, listed)
        self.assertEqual(self.own_counts(summary).get("root_certificates"), 1,
                         self.own_counts(summary))
        self_signed = listed[self.cert_key("machine_root", machine)]
        self.assertIs(self_signed.get("self_signed"), True, self_signed)
        self.assertIs(self_signed.get("in_authroot"), False, self_signed)
        self.assertIs(listed[self.cert_key("user_root", user)].get("self_signed"), False,
                      listed[self.cert_key("user_root", user)])

        with self.subTest(case="also in authroot"):
            both = thumb(0xA04)
            summary = self.collect(fake(root_certificates=ok(certificates_result(
                machine_root=[cert(both, subject="CN=Invented Twin Root")],
                authroot=[cert(both, subject="CN=Invented Twin Root")],
            ))))
            listed = self.by_key(self.additions_of(summary, "root_certificate"))
            item = listed.get(self.cert_key("machine_root", both))
            self.assertIsNotNone(item, sorted(map(str, listed)))
            self.assertIs(item.get("in_authroot"), True, item)

        with self.subTest(case="details not read, then read"):
            data_dir = self.data_dir()
            later = thumb(0xA05)
            key = self.cert_key("machine_root", later)
            first = self.collect(fake(root_certificates=ok(certificates_result(
                machine_root=[cert(later, details=False)],
            ))), data_dir=data_dir, now=NOW)
            detail = self.by_key(self.detail_additions_of(first, "root_certificate"))
            item = detail.get(key)
            self.assertIsNotNone(item, sorted(map(str, detail)))
            self.assertIn("subject", item, item)
            self.assertIsNone(item.get("subject"), item)
            self.assertIn("subject", item.get("unread_fields") or [], item)

            second = self.collect(fake(root_certificates=ok(certificates_result(
                machine_root=[cert(later, subject="CN=Invented Later Root")],
            ))), data_dir=data_dir, now=NOW + timedelta(days=1))
            self.assertEqual(self.comparison(second).get("root_certificates"), "compared",
                             self.comparison(second))
            self.assertEqual(self.changes_from(second, "root_certificates"), [])

    def test_clean_machine_lists_no_certs(self):
        clean_machine = [cert(t, subject=f"CN=Invented name for {t[:6]}")
                         for t in SHIPPED_THUMBPRINTS]
        clean_auth = [cert(thumb(0xB00 + n), subject=f"CN=Invented Auth Root {n}")
                      for n in range(3)]
        summary = self.collect(fake(root_certificates=ok(certificates_result(
            machine_root=clean_machine, authroot=clean_auth,
        ))))
        self.assertEqual(self.additions_of(summary, "root_certificate"), [])
        self.assertEqual(self.own_counts(summary).get("root_certificates"), 10,
                         self.own_counts(summary))

        with self.subTest(case="shipped thumbprint in user_root, lookalike subject"):
            shipped = SHIPPED_THUMBPRINTS[1]
            lookalike = thumb(0xB10)
            summary = self.collect(fake(root_certificates=ok(certificates_result(
                machine_root=clean_machine + [cert(
                    lookalike, subject="CN=Microsoft Root Certificate Authority 2011")],
                user_root=[cert(shipped, subject="CN=Invented copy in user store")],
                authroot=clean_auth,
            ))))
            listed = self.by_key(self.additions_of(summary, "root_certificate"))
            self.assertEqual(set(listed), {self.cert_key("user_root", shipped),
                                           self.cert_key("machine_root", lookalike)}, listed)
            self.assertEqual(self.own_counts(summary).get("root_certificates"), 10,
                             self.own_counts(summary))

    def listed_microsoft_roots(self):
        """Thumbprints of the two required roots, read from the real data file (plan 080)."""
        entries = shipped_entries()
        self.assertIsInstance(entries, list, entries)
        found = []
        for subject in REQUIRED_SUBJECTS:
            matching = [e.get("thumbprint") for e in entries
                        if isinstance(e, dict) and e.get("subject") == subject]
            self.assertEqual(len(matching), 1, f"{subject!r}: {matching!r}")
            self.assertIsInstance(matching[0], str, matching)
            found.append(matching[0])
        return found

    def test_listed_microsoft_roots_are_own(self):
        listed_roots = self.listed_microsoft_roots()
        machine = [cert(t, subject=f"CN=Invented listed root {n}")
                   for n, t in enumerate(listed_roots)]
        summary = self.collect(fake(root_certificates=ok(certificates_result(
            machine_root=machine,
        ))))
        self.assertEqual(self.source(summary, "root_certificates").get("status"), "read")
        self.assertEqual(self.additions_of(summary, "root_certificate"), [])
        self.assertEqual(self.own_counts(summary).get("root_certificates"), 2,
                         self.own_counts(summary))

    def test_unlisted_root_still_added(self):
        listed_roots = self.listed_microsoft_roots()
        known = {e.get("thumbprint") for e in shipped_entries() if isinstance(e, dict)}
        unlisted = thumb(0xC80)
        self.assertNotIn(unlisted, known)
        machine = [cert(t, subject=f"CN=Invented listed root {n}")
                   for n, t in enumerate(listed_roots)]
        machine.append(cert(unlisted,
                            subject="CN=Microsoft ECC Product Root Certificate Authority 2018"))
        summary = self.collect(fake(root_certificates=ok(certificates_result(
            machine_root=machine,
        ))))
        listed = self.by_key(self.additions_of(summary, "root_certificate"))
        self.assertEqual(set(listed), {self.cert_key("machine_root", unlisted)}, listed)


AUTHENTICODE_SUBJECT = f"CN={AUTHENTICODE_CN}, O=MSFT, C=US"


def authenticode(thumbprint, **overrides):
    """An invented self-signed certificate with the Authenticode Root subject and serial."""
    fields = {"subject": AUTHENTICODE_SUBJECT, "serial": "01"}
    fields.update(overrides)
    return cert(thumbprint, **fields)


def machine_root(*certificates):
    return fake(root_certificates=ok(certificates_result(machine_root=list(certificates))))


class TestFirstRunCertificates(AdditionsTestCase):
    """A certificate of ``cert_windows_first_run`` is Windows' own when it is there on
    the first run, and stays own by its key afterwards (plan 083, milestone M2)."""

    def cert_key(self, store, thumbprint):
        return f"cert:{store}:{thumbprint}"

    def listed(self, summary):
        """Summary ``additions`` of kind ``root_certificate`` by key."""
        return self.by_key(self.additions_of(summary, "root_certificate"))

    def cert_item(self, summary, key):
        """The full item of the detail file, which carries ``own`` for every item."""
        detail = self.by_key(self.detail_additions_of(summary, "root_certificate"))
        item = detail.get(key)
        self.assertIsNotNone(item, f"{key} not in detail additions: {sorted(map(str, detail))}")
        return item

    def run_on(self, data_dir, day, *certificates):
        return self.collect(machine_root(*certificates), data_dir=data_dir,
                            now=NOW + timedelta(days=day))

    def assert_trusted(self, summary, key):
        item = self.cert_item(summary, key)
        self.assertIs(item.get("own"), True, item)
        self.assertIs(item.get("windows_first_run"), True, item)
        self.assertNotIn(key, self.listed(summary))

    def assert_listed_not_own(self, summary, key):
        item = self.cert_item(summary, key)
        self.assertIs(item.get("own"), False, item)
        self.assertIn(key, self.listed(summary))

    def test_first_run_trusts_listed_cert(self):
        listed = thumb(0x8301)
        key = self.cert_key("machine_root", listed)
        summary = self.collect(machine_root(authenticode(listed)))

        self.assertEqual(self.source(summary, "root_certificates").get("status"), "read")
        self.assert_trusted(summary, key)
        self.assertEqual(self.listed(summary), {})
        self.assertEqual(self.own_counts(summary).get("root_certificates"), 1,
                         self.own_counts(summary))

    def test_same_thumbprint_stays_own(self):
        data_dir = self.data_dir()
        listed = thumb(0x8302)
        key = self.cert_key("machine_root", listed)
        self.run_on(data_dir, 0, authenticode(listed))
        second = self.run_on(data_dir, 1, authenticode(listed))

        self.assertEqual(self.comparison(second).get("root_certificates"), "compared",
                         self.comparison(second))
        item = self.cert_item(second, key)
        self.assertIs(item.get("own"), True, item)
        self.assertEqual([c for c in self.changes(second) if c.get("key") == key], [])
        self.assert_no_own_changes(second)

    def test_changed_thumbprint_is_added(self):
        data_dir = self.data_dir()
        first_thumb, second_thumb = thumb(0x8303), thumb(0x8304)
        second_key = self.cert_key("machine_root", second_thumb)
        self.run_on(data_dir, 0, authenticode(first_thumb))
        second = self.run_on(data_dir, 1, authenticode(second_thumb))

        self.assert_listed_not_own(second, second_key)
        changes = [c for c in self.changes(second) if c.get("key") == second_key]
        self.assertEqual([c.get("change") for c in changes], ["added"], changes)
        summary_item = self.listed(second)[second_key]
        self.assertIn("windows_first_run", summary_item, summary_item)
        self.assertIs(summary_item.get("windows_first_run"), False, summary_item)

        third = self.run_on(data_dir, 2, authenticode(second_thumb))
        self.assert_listed_not_own(third, second_key)

    def test_near_match_is_not_trusted(self):
        near = thumb(0x8305)
        cases = {
            "not self-signed": ("machine_root",
                                authenticode(near, issuer="CN=Invented Issuing CA")),
            "other serial": ("machine_root", authenticode(near, serial="02")),
            "user store": ("user_root", authenticode(near)),
            "serial not read": ("machine_root", authenticode(near, serial=None)),
        }
        for case, (store, certificate) in cases.items():
            with self.subTest(case=case):
                summary = self.collect(fake(root_certificates=ok(certificates_result(
                    **{store: [certificate]}))))
                self.assert_listed_not_own(summary, self.cert_key(store, near))

    def test_two_matches_trust_none(self):
        one, two = thumb(0x8306), thumb(0x8307)
        summary = self.collect(machine_root(authenticode(one), authenticode(two)))
        for thumbprint in (one, two):
            with self.subTest(thumbprint=thumbprint):
                self.assert_listed_not_own(summary, self.cert_key("machine_root", thumbprint))

    def test_old_baseline_counts_as_first_run(self):
        data_dir = self.data_dir()
        listed = thumb(0x8308)
        key = self.cert_key("machine_root", listed)
        self.run_on(data_dir, 0, authenticode(listed))

        # Make the saved entry look as a run before the plan wrote it: no serial,
        # not own, no first-run mark.
        state = data_dir / "state" / "ush-inventory.json"
        self.assertTrue(state.is_file(), f"{state} was not written")
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        certificates = (saved.get("sources") or {}).get("root_certificates")
        self.assertIsInstance(certificates, dict, sorted(saved.get("sources") or {}))
        entry = certificates.get(key)
        self.assertIsInstance(entry, dict, sorted(certificates))
        entry.pop("serial", None)
        entry.pop("windows_first_run", None)
        entry["own"] = False
        unread = [f for f in entry.get("unread_fields") or [] if f != "serial"]
        if unread:
            entry["unread_fields"] = unread
        else:
            entry.pop("unread_fields", None)
        state.write_text(json.dumps(saved), encoding="utf-8")

        second = self.run_on(data_dir, 1, authenticode(listed))
        item = self.cert_item(second, key)
        self.assertIs(item.get("own"), True, item)
        self.assertNotIn(key, self.listed(second))

    def test_clean_data_unchanged(self):
        foreign, user = thumb(0x8309), thumb(0x830A)
        auth = [cert(thumb(0x8310 + n), subject=f"CN=Invented Auth Root {n}") for n in range(3)]
        summary = self.collect(fake(root_certificates=ok(certificates_result(
            machine_root=[cert(foreign, subject="CN=Invented Foreign Root", serial="01")],
            user_root=[cert(user, subject="CN=Invented User Root",
                            issuer="CN=Invented Other CA")],
            authroot=auth,
        ))))

        listed = self.listed(summary)
        self.assertEqual(set(listed), {self.cert_key("machine_root", foreign),
                                       self.cert_key("user_root", user)}, listed)
        self.assertEqual(self.own_counts(summary).get("root_certificates"), 3,
                         self.own_counts(summary))
        self.assertIs(self.cert_item(summary, self.cert_key("machine_root", foreign))
                      .get("own"), False)
        items = (list(listed.values())
                 + self.detail_additions_of(summary, "root_certificate"))
        marked = [item.get("key") for item in items if "windows_first_run" in item]
        self.assertEqual(marked, [], "windows_first_run on clean data")

    def test_body_reads_serial(self):
        body = getattr(self.inventory, "ROOT_CERTIFICATES_BODY", "")
        self.assertIsInstance(body, str)
        self.assertRegex(body, r"serial\s*=\s*S\s+\$c\.SerialNumber",
                         "ROOT_CERTIFICATES_BODY does not read the serial number")
        details = getattr(self.inventory, "CERT_DETAILS", ())
        self.assertIn("serial", tuple(details or ()), details)

    def test_pin_survives_unread_details(self):
        data_dir = self.data_dir()
        listed = thumb(0x830B)
        key = self.cert_key("machine_root", listed)
        self.run_on(data_dir, 0, authenticode(listed))

        second = self.run_on(data_dir, 1, authenticode(listed, details=False))
        self.assert_trusted(second, key)

        third = self.run_on(data_dir, 2, authenticode(listed))
        item = self.cert_item(third, key)
        self.assertIs(item.get("own"), True, item)

    def test_unread_first_run_keeps_window_open(self):
        listed = thumb(0x830E)
        key = self.cert_key("machine_root", listed)
        cases = {
            "details unread": authenticode(listed, details=False),
            "serial unread": authenticode(listed, serial=None),
        }
        for case, unreadable in cases.items():
            with self.subTest(case=case):
                data_dir = self.data_dir()
                first = self.run_on(data_dir, 0, unreadable)
                self.assertIsNot(self.cert_item(first, key).get("own"), True)
                second = self.run_on(data_dir, 1, authenticode(listed))
                self.assert_trusted(second, key)

    def test_old_baseline_with_unread_subject_counts_as_first_run(self):
        data_dir = self.data_dir()
        listed = thumb(0x830F)
        key = self.cert_key("machine_root", listed)
        self.run_on(data_dir, 0, authenticode(listed, details=False))

        state = data_dir / "state" / "ush-inventory.json"
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        entry = saved["sources"]["root_certificates"][key]
        entry.pop("serial", None)
        state.write_text(json.dumps(saved), encoding="utf-8")

        second = self.run_on(data_dir, 1, authenticode(listed))
        self.assert_trusted(second, key)

    def test_pin_closes_window_despite_unread_entry(self):
        data_dir = self.data_dir()
        pinned, other, later = thumb(0x8311), thumb(0x8312), thumb(0x8313)
        foreign = cert(other, subject="CN=Invented Foreign Root", details=False)
        self.run_on(data_dir, 0, authenticode(pinned), foreign)
        second = self.run_on(data_dir, 1, foreign, authenticode(later))
        self.assert_listed_not_own(second, self.cert_key("machine_root", later))

    def test_open_window_does_not_trust_new_key(self):
        data_dir = self.data_dir()
        other, planted = thumb(0x8314), thumb(0x8315)
        foreign = cert(other, subject="CN=Invented Foreign Root", details=False)
        self.run_on(data_dir, 0, foreign)
        second = self.run_on(data_dir, 1, foreign, authenticode(planted))
        self.assert_listed_not_own(second, self.cert_key("machine_root", planted))

    def test_planted_cert_stays_listed_next_run(self):
        """A matching certificate added after the first run is listed on every later
        run, also while an unrelated ``machine_root`` certificate stays unreadable."""
        data_dir = self.data_dir()
        other, planted = thumb(0x8316), thumb(0x8317)
        key = self.cert_key("machine_root", planted)
        foreign = cert(other, subject="CN=Invented Foreign Root", details=False)
        self.run_on(data_dir, 0, foreign)
        second = self.run_on(data_dir, 1, foreign, authenticode(planted))
        self.assert_listed_not_own(second, key)

        third = self.run_on(data_dir, 2, foreign, authenticode(planted))
        self.assert_listed_not_own(third, key)

    def test_second_of_two_matches_stays_listed(self):
        """Two matches on the first run trust none; removing one does not make the
        other own on the next run, also while an unrelated certificate is unreadable."""
        data_dir = self.data_dir()
        one, two, other = thumb(0x8318), thumb(0x8319), thumb(0x831A)
        key = self.cert_key("machine_root", two)
        foreign = cert(other, subject="CN=Invented Foreign Root", details=False)
        first = self.run_on(data_dir, 0, foreign, authenticode(one), authenticode(two))
        self.assert_listed_not_own(first, key)

        second = self.run_on(data_dir, 1, foreign, authenticode(two))
        self.assert_listed_not_own(second, key)

    def test_readded_cert_is_listed(self):
        data_dir = self.data_dir()
        first_thumb, later_thumb = thumb(0x830C), thumb(0x830D)
        self.run_on(data_dir, 0, authenticode(first_thumb))
        self.run_on(data_dir, 1)
        third = self.run_on(data_dir, 2, authenticode(later_thumb))
        self.assert_listed_not_own(third, self.cert_key("machine_root", later_thumb))

    def own_file_with(self, data):
        """Point inventory at a temporary copy of its data folder whose
        ``windows-own.json`` is ``data``; the real file is never written.

        The module attribute that names the file (or its data folder) is found by
        its value, so the test does not depend on the attribute's name.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name).resolve() / "data"
        shutil.copytree(WINDOWS_OWN.parent, folder)
        own_file = folder / WINDOWS_OWN.name
        own_file.write_text(json.dumps(data), encoding="utf-8")

        def same(value, target):
            if isinstance(value, str) and ("\n" in value or len(value) > 500):
                return False
            try:
                path = Path(value).resolve()
            except (OSError, ValueError, TypeError):
                return False
            return os.path.normcase(str(path)) == os.path.normcase(str(target.resolve()))

        patched = []
        for name, value in list(vars(self.inventory).items()):
            if not isinstance(value, (str, Path)):
                continue
            for target, replacement in ((WINDOWS_OWN, own_file), (WINDOWS_OWN.parent, folder)):
                if same(value, target):
                    new = str(replacement) if isinstance(value, str) else replacement
                    patcher = mock.patch.object(self.inventory, name, new)
                    patcher.start()
                    self.addCleanup(patcher.stop)
                    patched.append(name)
        self.assertTrue(patched, "inventory has no module attribute naming windows-own.json "
                                 "or its data folder, so the test cannot give it another file")
        return own_file

    def test_bad_first_run_list_trusts_none(self):
        data = json.loads(WINDOWS_OWN.read_text(encoding="utf-8-sig"))
        data[FIRST_RUN_KEY] = [{
            "subject_cn": AUTHENTICODE_CN,
            "source": "https://learn.microsoft.com/invented-page",
        }]
        self.own_file_with(data)

        listed = thumb(0x830E)
        key = self.cert_key("machine_root", listed)
        summary = self.collect(machine_root(authenticode(listed)))

        self.assertIn("additions", summary, sorted(summary))
        notes = [item for item in self.not_checked(summary)
                 if "windows-own.json" in str(item.get("what"))]
        self.assertTrue(notes, summary.get("not_checked"))
        self.assert_listed_not_own(summary, key)

    def bad_first_run_data(self):
        data = json.loads(WINDOWS_OWN.read_text(encoding="utf-8-sig"))
        good = json.loads(WINDOWS_OWN.read_text(encoding="utf-8-sig"))
        data[FIRST_RUN_KEY] = "not a list"
        return data, good

    def test_bad_list_on_first_run_keeps_window_open(self):
        """A first run that could not use the list does not end the first run: the
        next run with a good list still trusts the one matching certificate."""
        data, good = self.bad_first_run_data()
        own_file = self.own_file_with(data)
        data_dir = self.data_dir()
        listed = thumb(0x831B)
        key = self.cert_key("machine_root", listed)
        first = self.run_on(data_dir, 0, authenticode(listed))
        self.assert_listed_not_own(first, key)

        own_file.write_text(json.dumps(good), encoding="utf-8")
        second = self.run_on(data_dir, 1, authenticode(listed))
        self.assert_trusted(second, key)

    def test_bad_list_keeps_existing_pin(self):
        data, good = self.bad_first_run_data()
        own_file = self.own_file_with(good)
        data_dir = self.data_dir()
        listed = thumb(0x831C)
        key = self.cert_key("machine_root", listed)
        self.run_on(data_dir, 0, authenticode(listed))

        own_file.write_text(json.dumps(data), encoding="utf-8")
        second = self.run_on(data_dir, 1, authenticode(listed))
        self.assert_trusted(second, key)


class TestHosts(AdditionsTestCase):
    def test_entries_and_path(self):
        text = ("# Invented hosts file\n"
                "127.0.0.1 localhost # c\n"
                "\n"
                "0.0.0.0\tads.example ads2.example\n"
                "# another invented comment\n")

        parse = getattr(self.inventory, "parse_hosts", None)
        self.assertIsNotNone(parse, "inventory has no parse_hosts")
        parsed = parse(text)
        if isinstance(parsed, dict):
            parsed = list(parsed.values())
        self.assertIsInstance(parsed, list, f"parse_hosts: {parsed!r}")
        self.assertEqual(
            sorted((str(e.get("hostname")), str(e.get("address"))) for e in parsed
                   if isinstance(e, dict)),
            [("ads.example", "0.0.0.0"), ("ads2.example", "0.0.0.0"),
             ("localhost", "127.0.0.1")],
            parsed,
        )
        self.assertEqual(len(parsed), 3, parsed)

        repeated = text + "127.0.0.1 localhost\n"
        summary = self.collect(fake(hosts=ok(hosts_result(repeated))))
        self.assertEqual(self.source(summary, "hosts").get("status"), "read")
        entries = self.by_key(self.additions_of(summary, "hosts_entry"))
        self.assertEqual(set(entries), {"hosts:localhost:127.0.0.1",
                                        "hosts:ads.example:0.0.0.0",
                                        "hosts:ads2.example:0.0.0.0"}, entries)
        localhost = entries["hosts:localhost:127.0.0.1"]
        self.assertEqual(localhost.get("line"), 2, localhost)
        self.assertEqual(localhost.get("duplicates"), 1, localhost)
        self.assertEqual(localhost.get("address"), "127.0.0.1", localhost)
        self.assertEqual(localhost.get("hostname"), "localhost", localhost)
        hosts_file = self.hosts_file(summary)
        self.assertIs(hosts_file.get("exists"), True, hosts_file)
        self.assertIs(hosts_file.get("path_is_default"), True, hosts_file)

        with self.subTest(case="comments only"):
            summary = self.collect(fake(hosts=ok(hosts_result("# a\n# b\n"))))
            self.assertEqual(self.source(summary, "hosts").get("status"), "read")
            self.assertEqual(self.additions_of(summary, "hosts_entry"), [])

        with self.subTest(case="no file"):
            summary = self.collect(fake(hosts=ok(hosts_result(exists=False))))
            self.assertEqual(self.source(summary, "hosts").get("status"), "read")
            self.assertEqual(self.additions_of(summary, "hosts_entry"), [])
            self.assertIs(self.hosts_file(summary).get("exists"), False,
                          self.hosts_file(summary))

        with self.subTest(case="file there without its text"):
            row = hosts_result("")
            row["text"] = None
            summary = self.collect(fake(hosts=ok(row)))
            self.assertEqual(self.source(summary, "hosts").get("status"), "unreadable")
            self.assertTrue(self.notes_about_source(summary, "hosts"),
                            summary.get("not_checked"))

        with self.subTest(case="job tells missing from unreadable"):
            body = getattr(self.inventory, "HOSTS_BODY", "")
            self.assertNotIn("File]::Exists", body)
            self.assertIn("FileNotFoundException", body)

        with self.subTest(case="default folder written out in full"):
            row = hosts_result(text, raw_dir=r"C:\InventedWin\System32\drivers\etc",
                               expanded_dir=r"C:\InventedWin\System32\drivers\etc")
            row["system_root"] = r"C:\InventedWin"
            summary = self.collect(fake(hosts=ok(row)))
            self.assertIs(self.hosts_file(summary).get("path_is_default"), True,
                          self.hosts_file(summary))

        with self.subTest(case="other folder with the system root known"):
            row = hosts_result(text, raw_dir=r"C:\Other", expanded_dir=r"C:\Other")
            row["system_root"] = r"C:\InventedWin"
            summary = self.collect(fake(hosts=ok(row)))
            self.assertIs(self.hosts_file(summary).get("path_is_default"), False,
                          self.hosts_file(summary))

        with self.subTest(case="other directory"):
            summary = self.collect(fake(hosts=ok(hosts_result(
                text, raw_dir="C:\\Other", expanded_dir="C:\\Other"))))
            self.assertIs(self.hosts_file(summary).get("path_is_default"), False,
                          self.hosts_file(summary))


class TestAdministrators(AdditionsTestCase):
    def test_members_and_fallback(self):
        builtin = "S-1-5-21-0-0-0-500"
        group = "S-1-5-21-0-0-0-2001"
        members = [
            member(builtin, "EXAMPLE-PC\\InventedAdmin", enabled=False),
            member(CURRENT_SID, "EXAMPLE-PC\\invented.user",
                   principal_source="MicrosoftAccount", enabled=True),
            member(group, "EXAMPLE\\Invented Admins", object_class="Group",
                   principal_source="ActiveDirectory", enabled=None),
        ]
        summary = self.collect(fake(administrators=ok(admins_result(members))))

        listed = self.by_key(self.additions_of(summary, "administrator"))
        self.assertEqual(set(listed), {f"admin:{builtin}", f"admin:{CURRENT_SID}",
                                       f"admin:{group}"}, listed)
        for sid, enabled, current in ((builtin, False, False), (CURRENT_SID, True, True),
                                      (group, None, False)):
            item = listed[f"admin:{sid}"]
            self.assertIn("enabled", item, item)
            self.assertIs(item.get("enabled"), enabled, item)
            self.assertIs(item.get("is_current"), current, item)
        group_detail = self.by_key(self.detail_additions_of(summary, "administrator"))
        group_item = group_detail.get(f"admin:{group}")
        self.assertIsNotNone(group_item, sorted(map(str, group_detail)))
        self.assertNotIn("enabled", group_item.get("unread_fields") or [], group_item)

        with self.subTest(case="Get-LocalUser failed"):
            summary = self.collect(fake(administrators=ok(admins_result([
                member(builtin, "EXAMPLE-PC\\InventedAdmin", enabled=None,
                       enabled_error="Invented Get-LocalUser failure"),
            ]))))
            detail = self.by_key(self.detail_additions_of(summary, "administrator"))
            item = detail.get(f"admin:{builtin}")
            self.assertIsNotNone(item, sorted(map(str, detail)))
            self.assertIn("enabled", item, item)
            self.assertIsNone(item.get("enabled"), item)
            self.assertIn("enabled", item.get("unread_fields") or [], item)

        with self.subTest(case="ADSI fallback"):
            summary = self.collect(fake(administrators=ok(admins_result([
                member(builtin, "InventedAdmin", principal_source=None, enabled=None),
            ], method="adsi"))))
            self.assertEqual(self.source(summary, "administrators").get("status"), "read")
            self.assertEqual(self.source_method(summary, "administrators"), "adsi")
            keys = [item.get("key") for item in self.additions_of(summary, "administrator")]
            self.assertIn(f"admin:{builtin}", keys)
            # ADSI writes the name from the WinNT path, not as Get-LocalGroupMember
            # does, so a change of method is no change of name.
            detail = self.by_key(self.detail_additions_of(summary, "administrator"))
            item = detail.get(f"admin:{builtin}")
            self.assertIsNotNone(item, sorted(map(str, detail)))
            self.assertIn("name", item.get("unread_fields") or [], item)

        with self.subTest(case="object class in the system language"):
            local_group = "S-1-5-21-0-0-0-2002"
            summary = self.collect(fake(administrators=ok(admins_result([
                member(builtin, "EXAMPLE-PC\\InventedAdmin", object_class="Benutzer",
                       enabled=None),
                member(local_group, "EXAMPLE-PC\\Invented Local Admins",
                       object_class="Gruppe", enabled=None, is_user=False),
            ]))))
            detail = self.by_key(self.detail_additions_of(summary, "administrator"))
            user = detail.get(f"admin:{builtin}")
            self.assertIsNotNone(user, sorted(map(str, detail)))
            self.assertIn("enabled", user.get("unread_fields") or [], user)
            group_item = detail.get(f"admin:{local_group}")
            self.assertIsNotNone(group_item, sorted(map(str, detail)))
            self.assertNotIn("enabled", group_item.get("unread_fields") or [], group_item)

        with self.subTest(case="job does not rely on the object class text"):
            body = getattr(self.inventory, "ADMINISTRATORS_BODY", "")
            self.assertNotIn("$class -eq 'User'", body)
            self.assertIn("UserNotFoundException", body)

        with self.subTest(case="both methods failed"):
            summary = self.collect(fake(administrators=failure(
                "Invented: the group members could not be read")))
            self.assert_unreadable(summary, "administrators")
            self.assertTrue(self.notes_about_source(summary, "administrators"),
                            summary.get("not_checked"))


    def test_current_sid_unread(self):
        """No current SID read: whether a member is the running account is not known."""
        summary = self.collect(fake(administrators=ok(admins_result(
            [member(CURRENT_SID, "EXAMPLE-PC\\invented.user")], current_sid=None))))
        item = self.by_key(self.additions_of(summary, "administrator"))[f"admin:{CURRENT_SID}"]
        self.assertIn("is_current", item, item)
        self.assertIsNone(item.get("is_current"), item)
        self.assertIn("is_current", item.get("unread_fields") or [], item)

class TestAdministratorChanges(AdditionsTestCase):
    """A change in the Administrators group carries no account name (plan 070, M2)."""

    def admin_changes(self, data_dir, first_members, second_members):
        for n, members in enumerate((first_members, second_members)):
            summary = self.collect(fake(administrators=ok(admins_result(members))),
                                   data_dir=data_dir, now=NOW + timedelta(days=n))
        return self.by_key([c for c in self.changes(summary)
                            if c.get("source") == "administrators"])

    def test_change_carries_no_account_name(self):
        renamed = "S-1-5-21-0-0-0-1101"
        gone = "S-1-5-21-0-0-0-1102"
        new = "S-1-5-21-0-0-0-1103"
        names = ("Quellbrin", "Tamsivor", "Pelgrask", "Vondrimel")
        changes = self.admin_changes(
            self.data_dir(),
            [member(renamed, "EXAMPLE-PC\\Quellbrin"), member(gone, "EXAMPLE-PC\\Pelgrask")],
            [member(renamed, "EXAMPLE-PC\\Tamsivor"), member(new, "EXAMPLE-PC\\Vondrimel")],
        )

        self.assertEqual(
            {key: change.get("change") for key, change in changes.items()},
            {f"admin:{renamed}": "changed", f"admin:{gone}": "removed",
             f"admin:{new}": "added"},
            changes,
        )
        for key, change in changes.items():
            with self.subTest(key=key):
                self.assertNotIn("name", change, change)
                text = json.dumps(change).lower()
                for name in names:
                    self.assertNotIn(name.lower(), text, change)
        fields = changes[f"admin:{renamed}"].get("fields")
        self.assertIsInstance(fields, dict, changes[f"admin:{renamed}"])
        self.assertEqual(fields.get("name"), {"changed": True}, fields)

    def test_enabled_change_keeps_values(self):
        sid = "S-1-5-21-0-0-0-1104"
        changes = self.admin_changes(
            self.data_dir(),
            [member(sid, "EXAMPLE-PC\\Harnaveth", enabled=True)],
            [member(sid, "EXAMPLE-PC\\Harnaveth", enabled=False)],
        )

        self.assertEqual(set(changes), {f"admin:{sid}"}, changes)
        change = changes[f"admin:{sid}"]
        self.assertEqual(change.get("change"), "changed", change)
        self.assertEqual(change.get("fields"),
                         {"enabled": {"before": True, "after": False}}, change)


class TestDefender(AdditionsTestCase):
    def test_admin_only_and_fallback(self):
        result = defender_result(path=["C:\\Temp"])

        plain_fake = fake(defender_exclusions=ok(result))
        plain = self.collect(plain_fake, admin=False)
        self.assertNotIn("defender_exclusions", plain_fake.jobs())
        source = self.assert_unreadable(plain, "defender_exclusions")
        self.assertIn("requires administrator", source.get("reason"), source)
        self.assertEqual(len(self.notes_about_source(plain, "defender_exclusions")), 1,
                         plain.get("not_checked"))

        admin_fake = fake(defender_exclusions=ok(result))
        elevated = self.collect(admin_fake, admin=True)
        self.assertIn("defender_exclusions", admin_fake.jobs())
        self.assertEqual(self.source(elevated, "defender_exclusions").get("status"), "read")
        keys = [item.get("key")
                for item in self.additions_of(elevated, "defender_exclusion")]
        self.assertIn("defender:path:c:\\temp", keys)

        with self.subTest(case="hidden values"):
            summary = self.collect(fake(defender_exclusions=ok(defender_result(
                path=["N/A: Must be an administrator to view exclusions"]))), admin=True)
            self.assert_unreadable(summary, "defender_exclusions")
            # A hidden value is never an entry.
            self.assertEqual(self.additions_of(summary, "defender_exclusion"), [])

        with self.subTest(case="0x800106ba, read from the registry"):
            summary = self.collect(fake(defender_exclusions=ok(defender_result(
                method="registry", path=["C:\\Temp"]))), admin=True)
            self.assertEqual(self.source(summary, "defender_exclusions").get("status"),
                             "read")
            self.assertEqual(self.source_method(summary, "defender_exclusions"),
                             "registry")

        with self.subTest(case="origin"):
            policy = {"path": ["C:\\Policy"], "extension": [], "process": [], "ip": []}
            summary = self.collect(fake(defender_exclusions=ok(defender_result(
                path=["C:\\Temp", "C:\\Policy"], extension=[".inv"], policy=policy,
            ))), admin=True)
            listed = self.by_key(self.additions_of(summary, "defender_exclusion"))
            for key, origin in (("defender:path:c:\\policy", "policy"),
                                ("defender:path:c:\\temp", "local"),
                                ("defender:extension:.inv", "local")):
                item = listed.get(key)
                self.assertIsNotNone(item, sorted(map(str, listed)))
                self.assertEqual(item.get("origin"), origin, item)


class TestChanges(AdditionsTestCase):
    def test_additions_changes(self):
        data_dir = self.data_dir()
        old_rule = "{00000000-0000-0000-0000-00000000D001}"
        new_rule = "{00000000-0000-0000-0000-00000000D002}"
        admin_one = "S-1-5-21-0-0-0-1001"
        admin_two = "S-1-5-21-0-0-0-1002"
        removed_cert = thumb(0xD01)

        first = m2_responses(
            firewall_rules=ok(firewall_result(local=[
                fw_value(old_rule, custom_rule("Invented Old Server")),
                fw_value("InventedBuiltin-1", builtin_rule(1)),
            ])),
            hosts=ok(hosts_result("127.0.0.1 localhost\n")),
            administrators=ok(admins_result([member(admin_one, "EXAMPLE-PC\\invented.one")])),
            root_certificates=ok(certificates_result(
                machine_root=[cert(removed_cert, subject="CN=Invented Gone Root")])),
        )
        second = m2_responses(
            firewall_rules=ok(firewall_result(local=[
                fw_value(old_rule, custom_rule("Invented Old Server")),
                fw_value(new_rule, custom_rule("Invented New Server", port="9090")),
                fw_value("InventedBuiltin-1", builtin_rule(1)),
                fw_value("InventedBuiltin-2", builtin_rule(2)),
            ])),
            hosts=ok(hosts_result("# invented comment\n127.0.0.1 localhost\n"
                                  "0.0.0.0 ads.example\n")),
            administrators=ok(admins_result([
                member(admin_one, "EXAMPLE-PC\\invented.one"),
                member(admin_two, "EXAMPLE-PC\\invented.two"),
            ])),
            root_certificates=ok(certificates_result()),
        )

        self.collect(FakePowerShell(first), data_dir=data_dir, now=NOW)
        run2 = self.collect(FakePowerShell(second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        changes = [c for c in self.changes(run2)
                   if c.get("source") in ("firewall_rules", "root_certificates", "hosts",
                                          "administrators", "defender_exclusions")]
        self.assertEqual(len(changes), 4, changes)
        by_key = self.by_key(changes)
        self.assertEqual(set(by_key), {
            firewall_key("local", new_rule),
            "hosts:ads.example:0.0.0.0",
            f"admin:{admin_two}",
            f"cert:machine_root:{removed_cert}",
        }, by_key)
        self.assertEqual(by_key[f"cert:machine_root:{removed_cert}"].get("change"),
                         "removed")
        self.assertNotIn("hosts:localhost:127.0.0.1", by_key)
        self.assertEqual(self.by_source(run2, "firewall_rules").get("added"), 1,
                         self.own_changes(run2))


    def test_rule_read_later_is_no_change(self):
        """A rule unparsable on one run and parsable on the next is not ``changed``."""
        rule = "{00000000-0000-0000-0000-00000000D003}"
        texts = ("garbage", custom_rule("Invented Late Server"))
        for first, second in (texts, texts[::-1]):
            with self.subTest(first=first[:10]):
                data_dir = self.data_dir()
                for n, value in enumerate((first, second)):
                    summary = self.collect(
                        fake(firewall_rules=ok(firewall_result(local=[fw_value(rule, value)]))),
                        data_dir=data_dir, now=NOW + timedelta(days=n))
                changed = [c for c in self.changes(summary)
                           if c.get("key") == firewall_key("local", rule)]
                self.assertEqual(changed, [], changed)

    def test_defender_change_names_no_path(self):
        """A Defender exclusion change carries its path as ``value`` (a path key), not
        as ``name``, whose digits would back numbers in the report."""
        data_dir = self.data_dir()
        path = "C:\\Invented Cache 8163"
        for n, paths in enumerate(((), (path,))):
            summary = self.collect(fake(defender_exclusions=ok(defender_result(path=paths))),
                                   data_dir=data_dir, now=NOW + timedelta(days=n), admin=True)
        changes = [c for c in self.changes(summary) if c.get("source") == "defender_exclusions"]
        self.assertEqual(len(changes), 1, changes)
        self.assertNotIn("name", changes[0], changes[0])
        self.assertEqual(changes[0].get("value"), path, changes[0])

class TestSources(AdditionsTestCase):
    def test_each_addition_source_statuses(self):
        for name in ("firewall_rules", "root_certificates", "hosts", "administrators",
                     "defender_exclusions"):
            with self.subTest(source=name, case="failed job"):
                summary = self.collect(
                    fake(**{name: failure("Invented access failure 0x80070005")}),
                    admin=True,
                )
                self.assert_unreadable(summary, name)
                self.assertTrue(self.notes_about_source(summary, name),
                                summary.get("not_checked"))
                self.assertIn("additions", summary, sorted(summary))
                if name == "hosts":
                    hosts_file = self.hosts_file(summary)
                    for field in ("exists", "path_is_default"):
                        self.assertIn(field, hosts_file, hosts_file)
                        self.assertIsNone(hosts_file.get(field), hosts_file)
                        self.assertIn(field, hosts_file.get("unread_fields") or [],
                                      hosts_file)

        with self.subTest(case="all five failed"):
            summary = self.collect(fake(**{
                name: failure("Invented access failure 0x80070005")
                for name in ("firewall_rules", "root_certificates", "hosts",
                             "administrators", "defender_exclusions")
            }), admin=True)
            self.assertIn("additions", summary, sorted(summary))
            self.assertIsNone(summary.get("additions"), summary.get("additions"))

        single_rule = "{00000000-0000-0000-0000-00000000E001}"
        single_cert = thumb(0xE01)
        single_sid = "S-1-5-21-0-0-0-1003"
        singles = {
            "firewall_rules": (
                [fw_store("local", fw_value(single_rule, custom_rule("Invented Single"))),
                 fw_store("app_iso", []), fw_store("policy", [], exists=False)],
                [firewall_key("local", single_rule)],
            ),
            "root_certificates": (
                [dict(row, certificates=cert(single_cert, subject="CN=Invented Single Root"))
                 if row.get("store") == "user_root" else row
                 for row in certificates_result()],
                [f"cert:user_root:{single_cert}"],
            ),
            "administrators": (
                {"method": "local_group_member", "current_sid": CURRENT_SID,
                 "members": member(single_sid, "EXAMPLE-PC\\invented.single")},
                [f"admin:{single_sid}"],
            ),
            "defender_exclusions": (
                defender_result(path="C:\\Single", extension=".inv",
                                process="invented.exe", ip="192.0.2.1"),
                ["defender:path:c:\\single", "defender:extension:.inv",
                 "defender:process:invented.exe", "defender:ip:192.0.2.1"],
            ),
        }
        for name, (payload, expected) in singles.items():
            with self.subTest(source=name, case="single object"):
                summary = self.collect(fake(**{name: ok(payload)}), admin=True)
                self.assertEqual(self.source(summary, name).get("status"), "read")
                keys = [item.get("key") for item in self.additions(summary)]
                for key in expected:
                    self.assertIn(key, keys)


def all_strings(value):
    """Every string of a JSON value, dict keys included."""
    if isinstance(value, str):
        return {value}
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            found |= all_strings(item)
    elif isinstance(value, list):
        for item in value:
            found |= all_strings(item)
    return found


class TestUnreadSourceBaseline(AdditionsTestCase):
    """Read, then not read, then read without the item, for each source of plan 052
    (plan 074, milestone M2, K8; the pattern is ``test_programs.py``
    ``TestBaseline::test_unread_source_no_false_changes``)."""

    def cases(self):
        """``{source: (admin, payload with one item, payload without it, item key)}``."""
        rule = "{00000000-0000-0000-0000-00000000F001}"
        root = thumb(0xF01)
        sid = "S-1-5-21-0-0-0-1201"
        device = "PCI\\VEN_1AAA&DEV_0030\\0030"
        return {
            "optional_features": (
                False, [feature("InventedFeatureOn", ENABLED)], [],
                "feature:InventedFeatureOn"),
            "capabilities": (
                True, [capability("Invented.Tool~~~~0.0.1.0", "Installed")], [],
                "capability:Invented.Tool~~~~0.0.1.0"),
            "drivers": (
                False, [driver(device, "oem7.inf", device_name="Invented Probe Device")], [],
                f"driver:{device}"),
            "firewall_rules": (
                False,
                firewall_result(local=[fw_value(rule, custom_rule("Invented Probe Server"))]),
                firewall_result(),
                f"firewall:local:{rule}"),
            "root_certificates": (
                False,
                certificates_result(machine_root=[cert(root, subject="CN=Invented Probe Root")]),
                certificates_result(),
                f"cert:machine_root:{root}"),
            "hosts": (
                False, hosts_result("0.0.0.0 probe.example\n"), hosts_result(""),
                "hosts:probe.example:0.0.0.0"),
            "administrators": (
                False, admins_result([member(sid, "EXAMPLE-PC\\invented.probe")]),
                admins_result([]),
                f"admin:{sid}"),
            "defender_exclusions": (
                True, defender_result(path=["C:\\Invented\\Probe"]), defender_result(),
                "defender:path:c:\\invented\\probe"),
        }

    def baseline_strings(self, data_dir, admin):
        name = "ush-inventory.elevated.json" if admin else "ush-inventory.json"
        state = data_dir / "state" / name
        self.assertTrue(state.is_file(), f"{state} was not written")
        return all_strings(json.loads(state.read_text(encoding="utf-8-sig")))

    def test_unread_then_removed(self):
        cases = self.cases()
        self.assertEqual(set(cases), {"optional_features", "capabilities", "drivers",
                                      "firewall_rules", "root_certificates", "hosts",
                                      "administrators", "defender_exclusions"})
        for name, (admin, with_item, without_item, key) in cases.items():
            with self.subTest(source=name):
                data_dir = self.data_dir()

                first = self.collect(FakePowerShell({name: ok(with_item)}),
                                     data_dir=data_dir, admin=admin, now=NOW)
                self.assertEqual(self.source(first, name).get("status"), "read")
                self.assertIn(key, self.baseline_strings(data_dir, admin))

                second = self.collect(
                    FakePowerShell({name: failure("Invented access failure 0x80070005")}),
                    data_dir=data_dir, admin=admin, now=NOW + timedelta(days=1))
                self.assert_unreadable(second, name)
                self.assertEqual(self.comparison(second).get(name), "not_read",
                                 self.comparison(second))
                self.assertEqual(self.changes_from(second, name), [])
                self.assertEqual(self.changes(second), [])
                self.assertIn(key, self.baseline_strings(data_dir, admin))

                third = self.collect(FakePowerShell({name: ok(without_item)}),
                                     data_dir=data_dir, admin=admin,
                                     now=NOW + timedelta(days=2))
                self.assertEqual(self.comparison(third).get(name), "compared",
                                 self.comparison(third))
                changes = self.changes(third)
                self.assertEqual(len(changes), 1, changes)
                self.assertEqual(changes[0].get("key"), key, changes)
                self.assertEqual(changes[0].get("source"), name, changes)
                self.assertEqual(changes[0].get("change"), "removed", changes)


if __name__ == "__main__":
    unittest.main()

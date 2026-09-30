"""Readers of skills/ush-settings/scripts/settings.py other than the registry (plan 050, M3).

Interface under test (see ``fakes.py`` for the full contract of every job):

- Pure functions ``parse_active_scheme``, ``parse_query_indexes`` and ``parse_winhttp``.
- One PowerShell job per reader type: ``services``, ``firewall``, ``security_center``,
  ``defender``, ``device_guard``, ``powercfg``, ``dns``, ``appx``,
  ``delivery_optimization``, ``optional_features``, ``shadow_storage`` (admin only),
  ``capability_usage``; ``WinHttpSettings`` travels in ``registry_values``.
- A failed job gives ``not_read`` (``effective: null``) for its entries and an entry in
  ``not_checked``; a single object instead of a list is read as a one-element list.
- Numeric PS 5.1 enum forms are mapped to names; an unknown number stays a number.

Tests that name real catalogue ids run against the real catalogue (``RealCatalogueTestCase``
does not patch ``CATALOGUE_PATH``). Every machine answer is invented; PowerShell never starts.
"""

import json
import unittest

from tests.skill_loader import load_script

from .fakes import (
    ANTIVIRUS_OFF,
    ANTIVIRUS_ON,
    INVENTED_SCHEME_GUID,
    INVENTED_SETTING_GUID,
    INVENTED_SUBGROUP_GUID,
    RealCatalogueTestCase,
    active_scheme_text,
    defender_row,
    fail,
    firewall_rows,
    ok,
    query_text,
    service_row,
    winhttp_hex,
)

# Invented Polish output of ``powercfg /query``; escapes keep this file ASCII.
POLISH_QUERY = "\r\n".join([
    f"Identyfikator GUID schematu zasilania: {INVENTED_SCHEME_GUID}  (Invented Plan)",
    f"  Identyfikator GUID podgrupy: {INVENTED_SUBGROUP_GUID}  (Uśpienie)",
    "    Alias GUID: SUB_SLEEP",
    (f"    Identyfikator GUID ustawienia zasilania: {INVENTED_SETTING_GUID}  "
     "(Zezwalaj na czasomierze wznawiania)"),
    "      Alias GUID: RTCWAKE",
    "      Możliwy indeks ustawienia: 000",
    "      Możliwa przyjazna nazwa ustawienia: Wyłącz",
    "      Możliwy indeks ustawienia: 001",
    "      Możliwa przyjazna nazwa ustawienia: Włącz",
    "    Indeks bieżącego ustawienia zasilania prądem przemiennym: 0x00000001",
    "    Indeks bieżącego ustawienia zasilania prądem stałym: 0x00000000",
    "",
])

# Invented English output of a range setting: extra ``0x`` lines before AC and DC.
ENGLISH_RANGE_QUERY = "\n".join([
    f"Power Scheme GUID: {INVENTED_SCHEME_GUID}  (Invented Plan)",
    f"  Subgroup GUID: {INVENTED_SUBGROUP_GUID}  (Invented subgroup)",
    f"    Power Setting GUID: {INVENTED_SETTING_GUID}  (Invented setting)",
    "      Minimum Possible Setting: 0x00000000",
    "      Maximum Possible Setting: 0xffffffff",
    "      Possible Settings increment: 0x00000001",
    "      Possible Settings units: Invented units",
    "    Current AC Power Setting Index: 0x00000001",
    "    Current DC Power Setting Index: 0x00000000",
])

# Job name -> catalogue read types whose entries that job reads.
JOB_TYPES = {
    "registry_values": ("registry", "winhttp_proxy"),
    "wifi_adapter": ("wifi_adapter_value",),
    "services": ("service",),
    "firewall": ("firewall_profile",),
    "security_center": ("security_center_av",),
    "defender": ("defender_status",),
    "device_guard": ("device_guard",),
    "powercfg": ("power_scheme", "powercfg_setting"),
    "dns": ("dns",),
    "appx": ("appx",),
    "delivery_optimization": ("delivery_optimization",),
    "optional_features": ("optional_feature",),
    "shadow_storage": ("shadow_storage",),
    "capability_usage": (),
}


class PureFunctionCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = load_script("ush-settings", "settings")


class TestPowercfg(PureFunctionCase):
    def test_parse(self):
        english = query_text(ac=1, dc=0)
        for case, text in {"english": english, "polish": POLISH_QUERY,
                           "english range setting": ENGLISH_RANGE_QUERY}.items():
            with self.subTest(case=case):
                indexes = self.settings.parse_query_indexes(text)
                self.assertIsNotNone(indexes, text)
                self.assertEqual(tuple(indexes), (1, 0))

        with self.subTest(case="only one 0x line"):
            one_line = "\r\n".join(
                line for line in english.split("\r\n") if "Current DC" not in line
            )
            self.assertIn("0x00000001", one_line)
            self.assertIsNone(self.settings.parse_query_indexes(one_line))

        with self.subTest(case="active scheme, English"):
            self.assertEqual(self.settings.parse_active_scheme(active_scheme_text()),
                             {"guid": INVENTED_SCHEME_GUID, "name": "Invented Plan"})

        with self.subTest(case="active scheme, Polish"):
            text = (f"Identyfikator GUID schematu zasilania: {INVENTED_SCHEME_GUID}  "
                    "(Zrównoważony)\r\n")
            self.assertEqual(self.settings.parse_active_scheme(text),
                             {"guid": INVENTED_SCHEME_GUID,
                              "name": "Zrównoważony"})


class TestFirewallStore(PureFunctionCase):
    def test_reads_the_effective_store(self):
        # Without -PolicyStore ActiveStore the cmdlet reads the local persistent store,
        # so a firewall turned off by a policy key would read as on.
        self.assertIn("Get-NetFirewallProfile -PolicyStore ActiveStore",
                      self.settings.FIREWALL_BODY)
        self.assertIn("Get-NetFirewallProfile -PolicyStore PersistentStore",
                      self.settings.FIREWALL_BODY)


class TestWinhttp(PureFunctionCase):
    def test_parse(self):
        parse = self.settings.parse_winhttp
        with self.subTest(case="flag 1, direct"):
            self.assertEqual(parse(winhttp_hex(1)), "direct")
        with self.subTest(case="flag 3 with a server"):
            self.assertEqual(parse(winhttp_hex(3, "proxy.invalid:8080")),
                             "proxy.invalid:8080")
        with self.subTest(case="no value"):
            self.assertEqual(parse(None), "direct")
        with self.subTest(case="6 bytes"):
            self.assertIsNone(parse("180000000000"))


class TestDefender(RealCatalogueTestCase):
    def test_applies_if(self):
        with self.subTest(case="Defender not running"):
            fake = self.clean_fake({"defender": ok([defender_row(
                mode="Not running", realtime=False, tamper=False)])})
            summary = self.collect(fake)
            mode = self.detail_item(summary, "defender_mode")
            self.assertEqual(mode.get("effective"), "Not running", mode)
            for entry_id in ("defender_realtime", "defender_tamper"):
                item = self.detail_item(summary, entry_id)
                self.assertEqual(item.get("state"), "not_applicable", item)

        with self.subTest(case="Normal with real-time protection off"):
            fake = self.clean_fake({"defender": ok([defender_row(
                mode="Normal", realtime=False, tamper=True)])})
            item = self.detail_item(self.collect(fake), "defender_realtime")
            self.assertEqual(item.get("state"), "differs", item)
            self.assertIs(item.get("effective"), False, item)

        with self.subTest(case="defender job failed"):
            fake = self.clean_fake({"defender": fail("Invented Defender failure.")})
            summary = self.collect(fake)
            mode = self.detail_item(summary, "defender_mode")
            self.assertEqual(mode.get("state"), "not_read", mode)
            for entry_id in ("defender_realtime", "defender_tamper"):
                item = self.detail_item(summary, entry_id)
                self.assertEqual(item.get("state"), "not_read", item)
                self.assertIn("depends on defender_mode", item.get("reason") or "", item)


class TestSecurity(RealCatalogueTestCase):
    def test_bits(self):
        def antivirus(state):
            return ok([{"display_name": "Invented Antivirus", "product_state": state}])

        with self.subTest(case="productState 0x61000"):
            item = self.detail_item(
                self.collect(self.clean_fake({"security_center": antivirus(ANTIVIRUS_ON)})),
                "antivirus_active")
            self.assertIs(item.get("effective"), True, item)

        with self.subTest(case="productState 0x60000"):
            item = self.detail_item(
                self.collect(self.clean_fake({"security_center": antivirus(ANTIVIRUS_OFF)})),
                "antivirus_active")
            self.assertIs(item.get("effective"), False, item)

        with self.subTest(case="SecurityServicesRunning [2, 3]"):
            fake = self.clean_fake({"device_guard": ok([{"SecurityServicesRunning": [2, 3]}])})
            item = self.detail_item(self.collect(fake), "memory_integrity")
            self.assertIs(item.get("effective"), True, item)


class TestAdminOnly(RealCatalogueTestCase):
    def test_feature_and_admin_only(self):
        with self.subTest(case="no admin: shadow_storage not run, Recall not on the list"):
            fake = self.clean_fake()
            summary = self.collect(fake, admin=False)
            self.assertNotIn("shadow_storage", fake.jobs())
            self.assertIn("optional_features", fake.jobs())

            vss = self.detail_item(summary, "vss_max_space")
            self.assertEqual(vss.get("state"), "not_read", vss)
            self.assertIn("needs administrator", vss.get("reason") or "", vss)
            about_vss = [
                item for item in self.not_checked_items(summary)
                if any(word in json.dumps(item).lower()
                       for word in ("vss_max_space", "shadow_storage", "administrator"))
            ]
            self.assertEqual(len(about_vss), 1, self.not_checked_items(summary))

            recall = self.detail_item(summary, "recall_feature")
            self.assertEqual(recall.get("effective"), "absent", recall)
            self.assertEqual(recall.get("state"), "matches", recall)
            policy = self.detail_item(summary, "recall_snapshots_policy")
            self.assertEqual(policy.get("state"), "not_applicable", policy)

        with self.subTest(case="Recall InstallState 2"):
            fake = self.clean_fake({"optional_features": ok([
                {"Name": "InventedFeature-Alpha", "InstallState": 1},
                {"Name": "Recall", "InstallState": 2},
            ])})
            recall = self.detail_item(self.collect(fake), "recall_feature")
            self.assertEqual(recall.get("effective"), "Disabled", recall)
            self.assertEqual(recall.get("state"), "matches", recall)

        with self.subTest(case="Recall InstallState 4"):
            fake = self.clean_fake({"optional_features": ok([
                {"Name": "Recall", "InstallState": 4},
            ])})
            recall = self.detail_item(self.collect(fake), "recall_feature")
            self.assertEqual(recall.get("state"), "not_read", recall)
            self.assertIsNone(recall.get("effective"), recall)

        with self.subTest(case="query failed"):
            fake = self.clean_fake({"optional_features": fail("Invented CIM failure.")})
            recall = self.detail_item(self.collect(fake), "recall_feature")
            self.assertEqual(recall.get("state"), "not_read", recall)
            self.assertNotEqual(recall.get("effective"), "absent", recall)
            self.assertIsNone(recall.get("effective"), recall)


class TestSources(RealCatalogueTestCase):
    def own_entries(self, job):
        """Ids of the entries read by ``job`` (entries with ``applies_if`` excluded)."""
        types = JOB_TYPES[job]
        return [entry["id"] for entry in self.entries
                if entry["read"]["type"] in types and "applies_if" not in entry]

    def test_each_source_statuses(self):
        catalogue_types = {entry["read"]["type"] for entry in self.entries}
        covered = {t for types in JOB_TYPES.values() for t in types}
        self.assertLessEqual(catalogue_types, covered, "a read type without a job here")

        clean = self.collect(self.clean_fake(), admin=True)
        clean_not_checked = len(self.not_checked_items(clean))
        clean_items = self.items_by_entry(self.detail(clean).get("settings"))

        with self.subTest(case="no reader left unimplemented"):
            for item in clean_items.values():
                self.assertNotIn("not implemented", str(item.get("reason") or ""),
                                 item)
            self.assertEqual(len(clean_items), len(self.entries), sorted(clean_items))

        for job in JOB_TYPES:
            with self.subTest(job=job, case="failed"):
                fake = self.clean_fake({job: fail(f"Invented failure of {job}.")})
                summary = self.collect(fake, admin=True)
                self.assertIn(job, fake.jobs())
                own = self.own_entries(job)
                for entry_id in own:
                    item = self.detail_item(summary, entry_id)
                    self.assertEqual(item.get("state"), "not_read", item)
                    self.assertIsNone(item.get("effective"), item)
                self.assertGreater(len(self.not_checked_items(summary)), clean_not_checked,
                                   self.not_checked_items(summary))
                text = self.not_checked_text(summary)
                self.assertTrue(any(token.lower() in text for token in (job, *own)),
                                text)

        responses = self.clean_fake().responses
        for job, response in responses.items():
            if response[0] != "ok" or not isinstance(response[1], list) \
                    or len(response[1]) != 1:
                continue
            with self.subTest(job=job, case="single object instead of a list"):
                fake = self.clean_fake({job: ok(response[1][0])})
                summary = self.collect(fake, admin=True)
                for entry_id in self.own_entries(job):
                    item = self.detail_item(summary, entry_id)
                    self.assertNotEqual(item.get("state"), "not_read", item)
                    self.assertEqual(item.get("state"), clean_items[entry_id].get("state"),
                                     item)
                    self.assertEqual(item.get("effective"),
                                     clean_items[entry_id].get("effective"), item)


class TestEnums(RealCatalogueTestCase):
    def test_numeric_forms(self):
        fake = self.clean_fake({
            "services": ok([service_row("DiagTrack", 4)]),
            "firewall": ok(firewall_rows(1)),
            "delivery_optimization": ok([{"DownloadMode": 1}]),
        })
        summary = self.collect(fake)
        with self.subTest(case="service 4"):
            item = self.detail_item(summary, "diagtrack_service")
            self.assertEqual(item.get("effective"), "Disabled", item)
        for entry_id in ("firewall_domain", "firewall_private", "firewall_public"):
            with self.subTest(case="firewall 1", entry=entry_id):
                item = self.detail_item(summary, entry_id)
                self.assertIs(item.get("effective"), True, item)
        with self.subTest(case="DownloadMode 1"):
            item = self.detail_item(summary, "delivery_optimization")
            self.assertEqual(item.get("effective"), "Lan", item)

        with self.subTest(case="unknown DownloadMode number"):
            fake = self.clean_fake({"delivery_optimization": ok([{"DownloadMode": 7}])})
            item = self.detail_item(self.collect(fake), "delivery_optimization")
            self.assertEqual(item.get("effective"), 7, item)
            self.assertIs(type(item.get("effective")), int, item)
            self.assertEqual(item.get("state"), "differs", item)


class TestClean(RealCatalogueTestCase):
    def test_clean_machine_all_readers(self):
        info_ids = {entry["id"] for entry in self.entries if entry.get("expected") is None}
        self.assertIn("vss_max_space", info_ids)

        with self.subTest(case="admin"):
            summary = self.collect(self.clean_fake(), admin=True)
            by_state = summary.get("counts", {}).get("by_state")
            self.assertIsInstance(by_state, dict, summary.get("counts"))
            self.assertEqual(by_state.get("differs", 0), 0, by_state)
            states = {entry_id: item.get("state")
                      for entry_id, item in self.summary_items(summary).items()}
            self.assertEqual(states, {entry_id: "info" for entry_id in info_ids})

        with self.subTest(case="no admin"):
            summary = self.collect(self.clean_fake(), admin=False)
            by_state = summary.get("counts", {}).get("by_state")
            self.assertIsInstance(by_state, dict, summary.get("counts"))
            self.assertEqual(by_state.get("differs", 0), 0, by_state)
            items = self.summary_items(summary)
            states = {entry_id: item.get("state") for entry_id, item in items.items()}
            expected = {entry_id: "info" for entry_id in info_ids}
            expected["vss_max_space"] = "not_read"
            self.assertEqual(states, expected)
            self.assertIn("needs administrator", items["vss_max_space"].get("reason") or "")


if __name__ == "__main__":
    unittest.main()

"""Effective state and entry states of skills/ush-settings/scripts/settings.py (plan 050, M2).

Interface under test (see ``fakes.py`` for the full contract):

- ``settings.main(argv=None, run_ps=None, is_admin=None, now=None) -> int`` with
  ``--data-dir``; the summary JSON is printed on stdout, ``detail_file`` names the detail JSON.
- ``settings.CATALOGUE_PATH`` is patched to an invented catalogue.
- ``registry_values`` rows ``{hive, path, name, status, value, kind, error}`` plus the
  ``EditionID`` row; ``wifi_adapter`` rows ``{driver_key, name, status, value, kind, error}``.
- A ``registry`` entry: locations in catalogue order; the first ``present`` location whose
  value is in its ``map`` (or that has no ``map``) sets ``effective`` and ``source``
  (``policy``/``preference``); an ``unreadable`` location before it gives ``not_read``; with
  nothing set, ``effective`` = ``default`` and ``source`` = ``default``.
- A ``wifi_adapter_value`` entry: ``effective`` is the list of adapter values sorted by
  ``driver_key`` (missing value = ``default``); no adapter gives ``not_applicable``.
- States: ``not_read``, ``not_applicable``, ``info`` (``expected`` null), ``default_unknown``
  (default null used while ``expected`` is set), ``matches`` / ``differs``.
- ``from_policy_on_home``: true for ``source: policy`` with an ``EditionID`` starting with
  ``Core``, false for another read edition or another source, null for ``source: policy``
  when ``EditionID`` was not read (then ``edition_id`` is null and ``not_checked`` names it).
- Elevated runs: entries whose deciding location is in HKCU carry ``hkcu_elevated: true``
  and ``not_checked`` names HKCU; normal runs have no ``hkcu_elevated`` field.

Every value is invented; PowerShell never starts.
"""

import unittest

from .fakes import (
    EDITION_LOCATION,
    FakePowerShell,
    SettingsTestCase,
    absent,
    edition,
    loc,
    ok,
    present,
    registry,
    registry_entry,
    unreadable,
    wifi,
    wifi_entry,
)

POLICY = loc("HKLM", "SOFTWARE\\Policies\\InventedVendor\\Toggle", "DisableInventedToggle",
             "policy")
PREF = loc("HKCU", "Software\\InventedVendor\\Toggle", "InventedToggleEnabled", "preference")

GUARD_POLICY = loc("HKLM", "SOFTWARE\\Policies\\InventedVendor\\Guarded", "InventedGuard",
                   "policy")
GUARD_PREF = loc("HKCU", "Software\\InventedVendor\\Guarded", "InventedGuardEnabled",
                 "preference")

CAMERA_POLICY = loc("HKLM", "SOFTWARE\\Policies\\InventedVendor\\AppPrivacy",
                    "LetAppsAccessInventedCamera", "policy", {"1": "Allow", "2": "Deny"})
CAMERA_PREF = loc("HKLM", "SOFTWARE\\InventedVendor\\ConsentStore\\webcam", "Value",
                  "preference")

STATES_KEY = "Software\\InventedVendor\\States"


class TestRegistry(SettingsTestCase):
    def test_precedence_and_default(self):
        self.write_catalogue([
            registry_entry("invented_toggle", [POLICY, PREF], expected=[0], default=1),
        ])
        cases = {
            "only the preference": ([absent(POLICY), present(PREF, 0)], 0, "preference"),
            "policy and preference": ([present(POLICY, 1), present(PREF, 0)], 1, "policy"),
            "neither": ([absent(POLICY), absent(PREF)], 1, "default"),
        }
        for case, (rows, effective, source) in cases.items():
            with self.subTest(case=case):
                summary = self.collect(FakePowerShell({"registry_values": registry(*rows)}))
                item = self.detail_item(summary, "invented_toggle")
                self.assertEqual(item.get("effective"), effective, item)
                self.assertEqual(item.get("source"), source, item)

    def test_unreadable_and_unmapped(self):
        self.write_catalogue([
            registry_entry("invented_guarded", [GUARD_POLICY, GUARD_PREF], expected=[0],
                           default=1),
            registry_entry("invented_camera", [CAMERA_POLICY, CAMERA_PREF], expected=None,
                           default="Allow", area="permissions"),
        ])
        with self.subTest(case="unreadable policy before a present preference; "
                               "policy value outside the map"):
            fake = FakePowerShell({"registry_values": registry(
                unreadable(GUARD_POLICY), present(GUARD_PREF, 0),
                present(CAMERA_POLICY, 0), present(CAMERA_PREF, "Deny", kind="String"),
            )})
            summary = self.collect(fake)
            guarded = self.detail_item(summary, "invented_guarded")
            self.assertEqual(guarded.get("state"), "not_read", guarded)
            self.assertIsInstance(guarded.get("reason"), str, guarded)
            self.assertTrue(guarded["reason"].strip(), guarded)

            camera = self.detail_item(summary, "invented_camera")
            self.assertEqual(camera.get("effective"), "Deny", camera)
            self.assertEqual(camera.get("source"), "preference", camera)

        with self.subTest(case="policy value inside the map wins"):
            fake = FakePowerShell({"registry_values": registry(
                unreadable(GUARD_POLICY), present(GUARD_PREF, 0),
                present(CAMERA_POLICY, 2), present(CAMERA_PREF, "Allow", kind="String"),
            )})
            camera = self.detail_item(self.collect(fake), "invented_camera")
            self.assertEqual(camera.get("effective"), "Deny", camera)
            self.assertEqual(camera.get("source"), "policy", camera)


class TestStates(SettingsTestCase):
    def test_state_rules(self):
        default_one = loc("HKCU", STATES_KEY, "InventedDefaultOne", "preference")
        default_null = loc("HKCU", STATES_KEY, "InventedDefaultNull", "preference")
        info = loc("HKCU", STATES_KEY, "InventedInfo", "preference")
        match = loc("HKCU", STATES_KEY, "InventedMatch", "preference")
        self.write_catalogue([
            registry_entry("invented_default_one", [default_one], expected=[0], default=1),
            registry_entry("invented_default_null", [default_null], expected=[0],
                           default=None),
            registry_entry("invented_info", [info], expected=None, default=0),
            registry_entry("invented_match", [match], expected=[0], default=1),
        ])
        fake = FakePowerShell({"registry_values": registry(
            absent(default_one), absent(default_null), present(info, 5), present(match, 0),
        )})
        summary = self.collect(fake)
        expected_states = {
            "invented_default_one": "differs",
            "invented_default_null": "default_unknown",
            "invented_info": "info",
            "invented_match": "matches",
        }
        for entry_id, state in expected_states.items():
            with self.subTest(entry=entry_id):
                item = self.detail_item(summary, entry_id)
                self.assertEqual(item.get("state"), state, item)
        with self.subTest(entry="invented_default_one effective"):
            item = self.detail_item(summary, "invented_default_one")
            self.assertEqual(item.get("effective"), 1, item)
            self.assertEqual(item.get("source"), "default", item)

    def test_applies_if_on_unknown_value_is_not_read(self):
        # A target with no value and a null default is unknown, not "condition not met":
        # the dependent entry must not be hidden as not_applicable (a miss).
        target = loc("HKLM", STATES_KEY, "InventedTarget", "preference")
        dependent = loc("HKLM", STATES_KEY, "InventedDependent", "preference")
        dependent_entry = registry_entry("invented_dependent", [dependent], expected=[0],
                                         default=1)
        dependent_entry["applies_if"] = {"entry": "invented_target", "in": [1]}
        self.write_catalogue([
            registry_entry("invented_target", [target], expected=None, default=None),
            dependent_entry,
        ])

        with self.subTest(case="target unknown"):
            fake = FakePowerShell({"registry_values": registry(absent(target),
                                                               present(dependent, 1))})
            item = self.detail_item(self.collect(fake), "invented_dependent")
            self.assertEqual(item.get("state"), "not_read", item)
            self.assertIn("invented_target", item.get("reason") or "", item)

        with self.subTest(case="clean: target known and outside the list"):
            fake = FakePowerShell({"registry_values": registry(present(target, 0),
                                                               present(dependent, 1))})
            item = self.detail_item(self.collect(fake), "invented_dependent")
            self.assertEqual(item.get("state"), "not_applicable", item)

    def test_clean_machine_no_differs(self):
        mapped_policy = loc("HKLM", "SOFTWARE\\Policies\\InventedVendor\\Ads",
                            "DisabledByInventedPolicy", "policy", {"1": 0})
        mapped_pref = loc("HKCU", "Software\\InventedVendor\\Ads", "Enabled", "preference")
        null_default = loc("HKCU", STATES_KEY, "InventedAccepted", "preference")
        multi = loc("HKLM", "SOFTWARE\\InventedVendor\\Prompt", "InventedPromptLevel",
                    "preference")
        self.write_catalogue([
            registry_entry("invented_toggle", [POLICY, PREF], expected=[0], default=1),
            registry_entry("invented_mapped", [mapped_policy, mapped_pref], expected=[0],
                           default=1, area="ads"),
            registry_entry("invented_null_default", [null_default], expected=[1],
                           default=None),
            registry_entry("invented_multi", [multi], expected=[2, 5], default=5,
                           area="security"),
            wifi_entry("invented_wifi_power"),
        ])
        fake = FakePowerShell({
            "registry_values": registry(
                present(POLICY, 0), present(PREF, 0),
                present(mapped_policy, 1), present(mapped_pref, 0),
                present(null_default, 1),
                present(multi, 5),
            ),
            "wifi_adapter": ok([wifi("InventedClass\\0001", 24),
                                wifi("InventedClass\\0002", 24)]),
        })
        summary = self.collect(fake)
        entries = ("invented_toggle", "invented_mapped", "invented_null_default",
                   "invented_multi", "invented_wifi_power")
        for entry_id in entries:
            with self.subTest(entry=entry_id):
                item = self.detail_item(summary, entry_id)
                self.assertNotIn(item.get("state"), ("differs", "default_unknown"), item)
                # Guards against a vacuous pass: the clean value was read and compared.
                self.assertEqual(item.get("state"), "matches", item)

        self.assertIn("counts", summary)
        by_state = summary["counts"].get("by_state")
        self.assertIsInstance(by_state, dict, summary["counts"])
        self.assertEqual(by_state.get("differs", 0), 0, by_state)
        self.assertEqual(by_state.get("default_unknown", 0), 0, by_state)
        states = [item.get("state") for item in summary.get("settings", [])]
        self.assertNotIn("differs", states)
        self.assertNotIn("default_unknown", states)

    def test_policy_on_home_and_elevated_hkcu(self):
        hklm_policy = loc("HKLM", "SOFTWARE\\Policies\\InventedVendor\\Feature",
                          "DisableInventedFeature", "policy")
        hkcu_pref = loc("HKCU", "Software\\InventedVendor\\Feature", "InventedFeatureEnabled",
                        "preference")
        self.write_catalogue([
            registry_entry("invented_policy_hklm", [hklm_policy], expected=[1], default=0),
            registry_entry("invented_pref_hkcu", [hkcu_pref], expected=[0], default=1),
        ])

        def responses(edition_row):
            return FakePowerShell({"registry_values": registry(
                present(hklm_policy, 1), present(hkcu_pref, 0), edition_row=edition_row,
            )})

        with self.subTest(edition="Core"):
            summary = self.collect(responses(edition("Core")))
            self.assertEqual(summary.get("edition_id"), "Core", summary.get("edition_id"))
            policy = self.detail_item(summary, "invented_policy_hklm")
            self.assertEqual(policy.get("source"), "policy", policy)
            self.assertIs(policy.get("from_policy_on_home"), True, policy)
            pref = self.detail_item(summary, "invented_pref_hkcu")
            self.assertEqual(pref.get("source"), "preference", pref)
            self.assertIs(pref.get("from_policy_on_home"), False, pref)
            # A normal (non-elevated) run has no hkcu_elevated field.
            self.assertNotIn("hkcu_elevated", pref)
            self.assertNotIn("hkcu_elevated", policy)

        with self.subTest(edition="Professional"):
            summary = self.collect(responses(edition("Professional")))
            policy = self.detail_item(summary, "invented_policy_hklm")
            self.assertEqual(policy.get("source"), "policy", policy)
            self.assertIs(policy.get("from_policy_on_home"), False, policy)

        with self.subTest(edition="unreadable"):
            summary = self.collect(responses(unreadable(EDITION_LOCATION)))
            self.assertIn("edition_id", summary)
            self.assertIsNone(summary["edition_id"])
            policy = self.detail_item(summary, "invented_policy_hklm")
            self.assertEqual(policy.get("source"), "policy", policy)
            self.assertIn("from_policy_on_home", policy)
            self.assertIsNone(policy["from_policy_on_home"], policy)
            pref = self.detail_item(summary, "invented_pref_hkcu")
            self.assertIs(pref.get("from_policy_on_home"), False, pref)
            self.assertIn("editionid", self.not_checked_text(summary))

        with self.subTest(case="elevated run"):
            summary = self.collect(responses(edition("Core")), admin=True)
            self.assertIs(summary.get("elevated"), True, summary.get("elevated"))
            pref = self.detail_item(summary, "invented_pref_hkcu")
            self.assertIs(pref.get("hkcu_elevated"), True, pref)
            policy = self.detail_item(summary, "invented_policy_hklm")
            self.assertIsNot(policy.get("hkcu_elevated"), True, policy)
            self.assertIn("hkcu", self.not_checked_text(summary))


class TestWifi(SettingsTestCase):
    def test_adapters(self):
        self.write_catalogue([wifi_entry("invented_wifi_power", expected=[24], default=0)])
        cases = {
            "two adapters at 24": (
                [wifi("InventedClass\\0001", 24), wifi("InventedClass\\0002", 24)],
                "matches", [24, 24]),
            "one at 24, one without the value": (
                [wifi("InventedClass\\0001", 24),
                 wifi("InventedClass\\0002", None, status="absent")],
                "differs", [24, 0]),
            "no adapter": ([], "not_applicable", None),
        }
        for case, (rows, state, effective) in cases.items():
            with self.subTest(case=case):
                fake = FakePowerShell({"registry_values": registry(),
                                       "wifi_adapter": ok(rows)})
                item = self.detail_item(self.collect(fake), "invented_wifi_power")
                self.assertEqual(item.get("state"), state, item)
                if effective is not None:
                    self.assertEqual(item.get("effective"), effective, item)


if __name__ == "__main__":
    unittest.main()

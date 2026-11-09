"""The user's decisions checked by skills/ush-runall/scripts/runall.py (plan 030, M2,
criteria K1-K5).

Interface under test (from the plan and the decisions contract):

- ``<data dir>/decisions.json`` holds ``{"schema_version": 1, "decisions": [...]}``; each
  decision has ``id`` (``D<n>``), ``made``, ``text``, ``source`` and ``checks``, a list of
  ``{"kind": "setting", "skill": "ush-settings", "item": <catalogue id>, "expected": ...}``
  or ``{"kind": "vendor_absent", "match": "publisher" | "provider" | "folder",
  "name": <exact name>}`` (``skills/ush-common/scripts/decisions.py``).
- After the children, ``runall`` gives each decision one item ``j1``... in the summary and
  the detail file list ``decisions``, with ``decision`` (the decision's id), ``state``
  (``kept``, ``broken`` or ``not_checked``), ``evidence`` (a list of ``{skill, id}``),
  ``text``, ``made``, ``source`` and, for ``not_checked``, a ``reason``.
- A ``setting`` check reads the ``ush-settings`` detail item of its catalogue entry:
  ``matches`` is kept, ``differs`` is broken, any other state (or a failed child) is
  not checked with the state as the reason.
- A ``vendor_absent`` check compares its exact name, case-folded, with the lists of the
  child detail files (never the cut summaries): ``publisher`` with the inventory
  ``programs`` (sources ``win32_programs`` and ``msix_programs``); ``provider`` with every
  inventory ``driver_packages`` item, the inventory ``drivers`` and the ``ush-health``
  ``pending_updates`` ``driver_provider`` (sources ``driver_packages``, ``drivers``,
  ``pending_updates``); ``folder`` with the ``name`` of every inventory ``vendor_folders``
  item, matched ones included (source ``vendor_folders``, and every root of
  ``vendor_folder_roots`` read). An unread source, or a list that is ``null`` or missing,
  makes the check not checked.
- A decision with several checks is broken when any check is broken, kept only when every
  check was made and kept, and not checked otherwise.
- No file gives ``decisions: []`` and no ``not_checked`` entry; an unreadable file gives
  ``decisions: null`` and a ``not_checked`` entry naming ``decisions.json``.

Assumptions added by these tests beyond the plan text:

- An evidence entry names its child id as ``id`` (``e1``, ``o7``, ``q3``; ``"<skill> <id>"``
  is accepted too) and its skill as ``skill``. For a matched vendor folder, whose detail
  item has ``id`` ``null``, only a non-empty evidence that mentions ``ush-inventory`` is
  asserted.
- ``runall`` validates the setting checks against the real settings catalogue (as the M1
  loader does), so the setting decisions here name real catalogue entries with a number
  ``expected``, and use the catalogue's own expected values; their states come only from
  the invented ``ush-settings`` detail file.
- ``runall.py --detail j1 --detail-file <detail_file>`` prints that item (with its
  evidence) and exits 0, as for the ``h``, ``w`` and ``y`` ids.

No process is started: the children are fakes (``test_runall.py``) that write invented
summaries and detail files in temporary directories. Every value is invented (Contoso,
Fabrikam).
"""

import json
import unittest

from tests.skill_loader import REPO_ROOT

from .test_runall import FakeChildren, RunallTestCase, exits

CATALOGUE_FILE = REPO_ROOT / "skills" / "ush-settings" / "data" / "settings-catalogue.json"

MADE = "2026-10-31"
SOURCE = "invented repair plan settings-2026-10-31"
FAILURE = "Invented failure: access denied (0x80070005)."
SETTINGS_LISTED = ("differs", "not_read", "default_unknown", "info")
MISSING = object()

READ_ROOTS = (
    {"root": "%ProgramFiles%", "expanded": "C:\\PF", "status": "read", "reason": None},
    {"root": "%ProgramData%", "expanded": "C:\\PD", "status": "read", "reason": None},
)


def numeric_entries():
    """(catalogue id, expected) of the real catalogue entries that expect numbers."""
    data = json.loads(CATALOGUE_FILE.read_text(encoding="utf-8-sig"))
    entries = data.get("entries") if isinstance(data, dict) else None
    found = []
    for entry in entries or []:
        expected = entry.get("expected")
        if (isinstance(expected, list) and expected
                and all(type(value) is int for value in expected)):
            found.append((entry["id"], list(expected)))
    return found


# --- decisions -----------------------------------------------------------------------------

def decision(n, checks):
    return {"id": f"D{n}", "made": MADE, "text": f"Invented decision {n} in the user's words.",
            "source": SOURCE, "checks": list(checks)}


def setting_check(entry_id, expected):
    return {"kind": "setting", "skill": "ush-settings", "item": entry_id,
            "expected": list(expected)}


def vendor_check(match, name):
    return {"kind": "vendor_absent", "match": match, "name": name}


# --- invented child data -------------------------------------------------------------------

def settings_item(n, entry_id, state, expected):
    effective = {"matches": expected[0], "differs": expected[0] + 1}.get(state)
    return {"id": f"e{n}", "entry": entry_id, "area": "privacy", "level": "standard",
            "title": f"Invented title {n}", "state": state, "effective": effective,
            "expected": list(expected), "expected_from": "decision D1",
            "source": "preference" if effective is not None else None,
            "from_policy_on_home": False,
            "reason": None if effective is not None else "invented reason",
            "has_block": state == "differs"}


def settings_child(items):
    sources = [{"name": "registry_values", "status": "read", "reason": None}]
    detail = {"schema_version": 1, "skill": "ush-settings", "sources": sources,
              "settings": list(items)}
    listed = [item for item in items if item["state"] in SETTINGS_LISTED]
    return detail, {"settings": listed}


def program(n, name, publisher, source="win32_programs"):
    item = {"id": f"a{n}", "source": source, "name": name, "version": "1.0.0",
            "publisher": publisher, "install_date": "2026-08-01", "install_location": None,
            "own": False}
    if source == "win32_programs":
        item.update(key=f"win32:hklm64:{{invented-program-{n}}}", scope="machine",
                    system_component=False)
    else:
        item.update(key=f"msix:invented.app{n}_abcdefghijk", signature_kind="Store")
    return item


def driver(n, provider, device_name="Invented Display Adapter"):
    return {"id": f"d{n}", "key": f"driver:pci\\ven_1aaa&dev_00{n}\\invented",
            "device_name": device_name, "class": "Display", "provider": provider,
            "version": "31.0.1.1", "date": "2026-03-14", "signer": "Invented Driver Signer",
            "inf_name": f"oem{n + 40}.inf", "third_party": True, "own": False}


def driver_package(n, provider, original_name, device_state="no_device_found",
                   class_name="Display"):
    # Plan 051 M3: the package shape of ush-inventory moved from ``present_device`` to
    # ``device_state`` (False -> "no_device_found", None -> null).
    item = {"id": f"o{n}",
            "key": f"driver_package:{original_name}|{provider}|1.0.0.0".casefold(),
            "published_name": f"oem{n + 50}.inf", "original_name": original_name,
            "provider": provider, "class": class_name, "version": "1.0.0.0",
            "date": "2026-03-14", "signer": "Invented Driver Signer",
            "device_state": device_state, "owner": provider,
            "group": "graphics" if class_name == "Display" else "other",
            "no_device_by_nature": False}
    if device_state is None:
        item["device_state_reason"] = "invented reason: not judged"
    return item


def driver_update(n, provider):
    return {"id": f"q{n}", "title": f"{provider} - Display - 31.0.101.4200", "kb": [],
            "categories": ["Drivers"], "type": "driver", "driver_provider": provider,
            "driver_class": "Display", "driver_date": "2026-08-15T00:00:00Z",
            "downloaded": False}


def folder(name, matched, item_id=None, root=READ_ROOTS[0]):
    path = f"{root['expanded']}\\{name}"
    return {"id": item_id, "key": f"vendor_folder:{path}".casefold(), "name": name,
            "path": path, "root": root["root"], "has_entries": True, "reason": None,
            "last_write": "2026-10-30T08:15:00Z", "matched": matched,
            "matched_by": ["target"] if matched else []}


def inventory_child(programs=(), drivers=(), packages=(), folders=(), roots=READ_ROOTS,
                    unread=(), lists=None):
    """(detail content, summary extra) of an ``ush-inventory`` child.

    ``unread`` names sources that are ``unreadable``; ``lists`` replaces detail lists
    (``None`` for a null list, ``MISSING`` to leave the key out). The summary lists are
    empty and counted as cut, so only the detail file holds the items."""
    programs = list(programs)
    by_source = {
        "win32_programs": [p for p in programs if p["source"] == "win32_programs"],
        "msix_programs": [p for p in programs if p["source"] == "msix_programs"],
        "drivers": list(drivers),
        "driver_packages": list(packages),
    }
    sources = []
    for name in ("firewall_rules", "win32_programs", "msix_programs", "drivers",
                 "devices", "driver_packages", "vendor_folders"):
        if name in unread:
            sources.append({"name": name, "status": "unreadable", "reason": FAILURE})
        elif name in by_source and not by_source[name]:
            sources.append({"name": name, "status": "empty", "reason": None})
        else:
            sources.append({"name": name, "status": "read", "reason": None})
    detail = {"sources": sources, "additions": [], "programs": programs,
              "drivers": list(drivers), "driver_packages": list(packages),
              "vendor_folders": list(folders),
              "vendor_folder_roots": [dict(root) for root in roots]}
    for key, value in (lists or {}).items():
        if value is MISSING:
            detail.pop(key, None)
        else:
            detail[key] = value
    extra = {"truncated": len(programs),
             "truncated_drivers": len(drivers),
             "truncated_driver_packages": len(packages),
             "truncated_vendor_folders": len(folders)}
    for key in ("programs", "drivers", "driver_packages", "vendor_folders"):
        extra[key] = None if detail.get(key) is None else []
    return detail, extra


def health_child(updates, status=None):
    """(detail content, summary extra) of an ``ush-health`` child; ``updates`` ``None``
    means ``pending_updates`` was not read."""
    if status is None:
        status = "unreadable" if updates is None else ("empty" if updates == [] else "read")
    reason = FAILURE if status == "unreadable" else None
    sources = [{"name": "pending_updates", "status": status, "reason": reason}]
    detail = {"sources": sources, "items": [], "pending_updates": updates}
    return detail, {"pending_updates": None if updates is None else []}


class DecisionChildren(FakeChildren):
    """M1's fake children, with chosen detail files for ush-settings, ush-inventory and
    ush-health; the detail's ``sources`` also become the summary's."""

    def __init__(self, files_dir, outcomes=None, settings=None, inventory=None, health=None):
        super().__init__(files_dir, outcomes)
        self.contents = {"ush-settings": settings, "ush-inventory": inventory,
                         "ush-health": health}

    def summary(self, skill, **kwargs):
        summary = super().summary(skill, **kwargs)
        content = self.contents.get(skill)
        if content is not None:
            detail, extra = content
            summary["sources"] = detail["sources"]
            summary.update(extra)
            with open(summary["detail_file"], "w", encoding="utf-8") as handle:
                json.dump(detail, handle)
            with open(summary["summary_file"], "w", encoding="utf-8") as handle:
                json.dump(summary, handle)
        return summary


class TestRunallDecisions(RunallTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.entries = numeric_entries()
        if len(cls.entries) < 2:
            raise AssertionError("the settings catalogue has fewer than two entries that "
                                 "expect numbers; the fixtures need two")

    # --- helpers ---------------------------------------------------------------------------

    def write_decisions(self, data_dir, decisions):
        (data_dir / "decisions.json").write_text(
            json.dumps({"schema_version": 1, "decisions": list(decisions)}, indent=2),
            encoding="utf-8")

    def run_pass(self, decisions, outcomes=None, **children):
        """Write ``decisions`` (unless ``None``) and run a pass; return (summary, data
        dir, fake)."""
        data_dir = self.data_dir()
        if decisions is not None:
            self.write_decisions(data_dir, decisions)
        fake = DecisionChildren(self.temp(), outcomes, **children)
        return self.collect(data_dir, fake), data_dir, fake

    def decisions(self, data):
        self.assertIn("decisions", data, sorted(data))
        value = data["decisions"]
        self.assertIsInstance(value, list, value)
        return value

    def for_decision(self, data, decision_id):
        matches = [item for item in self.decisions(data)
                   if isinstance(item, dict) and item.get("decision") == decision_id]
        self.assertEqual(len(matches), 1, f"{decision_id}: {data.get('decisions')}")
        return matches[0]

    def assert_evidence(self, item, skill, child_id):
        evidence = item.get("evidence")
        self.assertIsInstance(evidence, list, item)
        found = [entry for entry in evidence
                 if isinstance(entry, dict) and entry.get("skill") == skill
                 and entry.get("id") in (child_id, f"{skill} {child_id}")]
        self.assertTrue(found, f"no evidence {skill} {child_id}: {item}")

    def assert_state(self, item, state):
        self.assertEqual(item.get("state"), state, item)

    def assert_not_checked(self, item):
        self.assert_state(item, "not_checked")
        reason = item.get("reason")
        self.assertIsInstance(reason, str, item)
        self.assertTrue(reason.strip(), item)
        return reason

    def decision_notes(self, summary):
        return [entry for entry in self.items(summary, "not_checked")
                if "decision" in json.dumps(entry).lower()]

    # --- K1 --------------------------------------------------------------------------------

    def test_setting_kept_and_broken(self):
        (entry_a, expected_a), (entry_b, expected_b) = self.entries[:2]
        decisions = [decision(1, [setting_check(entry_a, expected_a)]),
                     decision(2, [setting_check(entry_b, expected_b)])]
        settings = settings_child([settings_item(1, entry_a, "differs", expected_a),
                                   settings_item(2, entry_b, "matches", expected_b)])
        summary, data_dir, fake = self.run_pass(decisions, settings=settings)

        items = self.decisions(summary)
        self.assertEqual(sorted(item.get("id") for item in items), ["j1", "j2"], items)

        broken = self.for_decision(summary, "D1")
        self.assert_state(broken, "broken")
        self.assert_evidence(broken, "ush-settings", "e1")

        kept = self.for_decision(summary, "D2")
        self.assert_state(kept, "kept")

        for item, source in ((broken, decisions[0]), (kept, decisions[1])):
            with self.subTest(decision=source["id"]):
                self.assertEqual(item.get("text"), source["text"], item)
                self.assertEqual(item.get("made"), source["made"], item)
                self.assertEqual(item.get("source"), source["source"], item)

        with self.subTest("the detail file holds the decisions"):
            detail = self.detail(summary)
            in_detail = self.for_decision(detail, "D1")
            self.assertEqual(in_detail.get("id"), broken.get("id"), in_detail)
            self.assert_state(in_detail, "broken")
            self.assert_evidence(in_detail, "ush-settings", "e1")

        with self.subTest("--detail shows the evidence"):
            code, stdout, stderr = self.run_main(
                data_dir, fake,
                extra=("--detail", broken["id"], "--detail-file", summary["detail_file"]))
            self.assertEqual(code, 0, stderr[-500:])
            self.assertIn("D1", stdout)
            self.assertRegex(stdout, r"\be1\b")

    def test_broken_shows_only_what_came_back(self):
        (entry_a, expected_a), (entry_b, expected_b) = self.entries[:2]
        decisions = [decision(1, [setting_check(entry_a, expected_a),
                                  setting_check(entry_b, expected_b)])]
        settings = settings_child([settings_item(1, entry_a, "differs", expected_a),
                                   settings_item(2, entry_b, "matches", expected_b)])
        summary, _, _ = self.run_pass(decisions, settings=settings)
        broken = self.for_decision(summary, "D1")
        self.assert_state(broken, "broken")
        self.assertEqual(broken.get("evidence"), [{"skill": "ush-settings", "id": "e1"}],
                         broken)

        with self.subTest("a check not made adds no evidence to a broken decision"):
            other = [expected_b[0] + 5]
            decisions = [decision(1, [setting_check(entry_a, expected_a),
                                      setting_check(entry_b, other)])]
            summary, _, _ = self.run_pass(decisions, settings=settings)
            broken = self.for_decision(summary, "D1")
            self.assert_state(broken, "broken")
            self.assertEqual(broken.get("evidence"),
                             [{"skill": "ush-settings", "id": "e1"}], broken)
            self.assertIn("e2", broken.get("reason") or "", broken)

    # --- K2 --------------------------------------------------------------------------------

    def test_vendor_back(self):
        decisions = [decision(1, [vendor_check("provider", "Contoso")])]
        package = driver_package(7, "contoso", "contosodisplay.inf", device_state="no_device_found")
        other = driver_package(8, "Fabrikam", "fabrikamaudio.inf", device_state="no_device_found",
                               class_name="MEDIA")
        update = driver_update(3, "Contoso")

        cases = (
            ("an unused package and a pending update", [package, other], [update],
             (("ush-inventory", "o7"), ("ush-health", "q3"))),
            ("only an unused package", [package, other], [],
             (("ush-inventory", "o7"),)),
            ("only a pending driver update", [other], [update],
             (("ush-health", "q3"),)),
        )
        for label, packages, updates, evidence in cases:
            with self.subTest(label):
                summary, _, _ = self.run_pass(
                    decisions,
                    inventory=inventory_child(packages=packages,
                                              drivers=[driver(2, "Fabrikam")]),
                    health=health_child(updates))
                item = self.for_decision(summary, "D1")
                self.assert_state(item, "broken")
                for skill, child_id in evidence:
                    self.assert_evidence(item, skill, child_id)

    # --- K3 --------------------------------------------------------------------------------

    def test_vendor_absent_kept_exact_only(self):
        decisions = [decision(1, [vendor_check("publisher", "Contoso")]),
                     decision(2, [vendor_check("provider", "Contoso")]),
                     decision(3, [vendor_check("folder", "Contoso")])]
        inventory = inventory_child(
            programs=[program(1, "Contoso Studio", "Contoso Ltd"),
                      program(2, "Invented Notes", "Fabrikam", source="msix_programs")],
            drivers=[driver(2, "Contoso Ltd")],
            packages=[driver_package(7, "Contoso Ltd", "contosoltd.inf",
                                     device_state="no_device_found")],
            folders=[folder("Contoso Ltd", False, item_id="v1"),
                     folder("ContosoTools", True),
                     folder("Fabrikam", True, root=READ_ROOTS[1])])
        summary, _, _ = self.run_pass(decisions, inventory=inventory,
                                      health=health_child([driver_update(3, "Contoso Ltd")]))

        for decision_id in ("D1", "D2", "D3"):
            with self.subTest(decision=decision_id):
                self.assert_state(self.for_decision(summary, decision_id), "kept")
        self.assertEqual(self.decision_notes(summary), [], summary.get("not_checked"))

    # --- K4 --------------------------------------------------------------------------------

    def test_unread_is_not_kept(self):
        (entry_a, expected_a), (entry_b, expected_b) = self.entries[:2]
        vendors = [decision(1, [vendor_check("publisher", "Contoso")]),
                   decision(2, [vendor_check("provider", "Contoso")]),
                   decision(3, [vendor_check("folder", "Contoso")])]
        clean_programs = [program(1, "Invented Notes", "Fabrikam")]
        clean_drivers = [driver(2, "Fabrikam")]
        clean_packages = [driver_package(8, "Fabrikam", "fabrikamaudio.inf",
                                         device_state="no_device_found", class_name="MEDIA")]
        clean_folders = [folder("Fabrikam", True)]

        def inventory(**changes):
            args = {"programs": clean_programs, "drivers": clean_drivers,
                    "packages": clean_packages, "folders": clean_folders}
            args.update(changes)
            return inventory_child(**args)

        with self.subTest("the ush-inventory child failed"):
            summary, _, _ = self.run_pass(vendors, {"ush-inventory": exits(1)},
                                          inventory=inventory(), health=health_child([]))
            self.assertEqual(self.child(summary, "ush-inventory").get("status"), "failed")
            for decision_id in ("D1", "D2", "D3"):
                self.assert_not_checked(self.for_decision(summary, decision_id))

        with self.subTest("the ush-settings child failed"):
            summary, _, _ = self.run_pass(
                [decision(1, [setting_check(entry_a, expected_a)])],
                {"ush-settings": exits(1)},
                settings=settings_child([settings_item(1, entry_a, "matches", expected_a)]))
            self.assertEqual(self.child(summary, "ush-settings").get("status"), "failed")
            self.assert_not_checked(self.for_decision(summary, "D1"))

        unread_cases = (
            ("win32_programs unreadable, programs []", "D1",
             inventory(programs=[], unread=("win32_programs",))),
            ("programs missing from the detail file", "D1",
             inventory(lists={"programs": MISSING})),
            ("driver_packages unreadable and null", "D2",
             inventory(unread=("driver_packages",), lists={"driver_packages": None})),
            ("vendor_folders unreadable and null", "D3",
             inventory(unread=("vendor_folders",), lists={"vendor_folders": None})),
        )
        for label, decision_id, inventory_content in unread_cases:
            with self.subTest(label):
                summary, _, _ = self.run_pass(vendors, inventory=inventory_content,
                                              health=health_child([]))
                self.assert_not_checked(self.for_decision(summary, decision_id))

        with self.subTest("ush-health pending_updates unreadable and null"):
            summary, _, _ = self.run_pass(vendors, inventory=inventory(),
                                          health=health_child(None))
            self.assert_not_checked(self.for_decision(summary, "D2"))

        with self.subTest("two checks, one kept and one unread"):
            summary, _, _ = self.run_pass(
                [decision(1, [setting_check(entry_a, expected_a),
                              vendor_check("publisher", "Contoso")])],
                settings=settings_child([settings_item(1, entry_a, "matches", expected_a)]),
                inventory=inventory(programs=[], unread=("win32_programs",)),
                health=health_child([]))
            reason = self.assert_not_checked(self.for_decision(summary, "D1"))
            self.assertTrue(any(word in reason for word in
                                ("Contoso", "publisher", "vendor_absent", "win32_programs")),
                            reason)

        with self.subTest("a setting in state default_unknown"):
            summary, _, _ = self.run_pass(
                [decision(1, [setting_check(entry_b, expected_b)])],
                settings=settings_child([settings_item(1, entry_b, "default_unknown",
                                                       expected_b)]))
            reason = self.assert_not_checked(self.for_decision(summary, "D1"))
            self.assertIn("default_unknown", reason)

        with self.subTest("drivers unreadable while the detail still holds drivers: []"):
            unjudged = [driver_package(8, "Fabrikam", "fabrikamaudio.inf",
                                       device_state=None, class_name="MEDIA")]
            content = inventory(drivers=[], packages=unjudged, unread=("drivers",))
            self.assertEqual(content[0]["drivers"], [])
            summary, _, _ = self.run_pass(vendors, inventory=content,
                                          health=health_child([]))
            self.assert_not_checked(self.for_decision(summary, "D2"))

        with self.subTest("a folder that is back but matched is broken"):
            summary, _, _ = self.run_pass(
                vendors,
                inventory=inventory(folders=[folder("Contoso", True), *clean_folders]),
                health=health_child([]))
            item = self.for_decision(summary, "D3")
            self.assert_state(item, "broken")
            evidence = item.get("evidence")
            self.assertIsInstance(evidence, list, item)
            self.assertTrue(evidence, item)
            self.assertIn("ush-inventory", json.dumps(evidence))

        with self.subTest("one unreadable vendor folder root"):
            roots = (READ_ROOTS[0], {"root": "%ProgramData%", "expanded": "C:\\PD",
                                     "status": "unreadable", "reason": FAILURE})
            summary, _, _ = self.run_pass(vendors, inventory=inventory(roots=roots),
                                          health=health_child([]))
            self.assert_not_checked(self.for_decision(summary, "D3"))

        with self.subTest("a folder back under a read root, another root unreadable"):
            # Review fix (plan 030 M2): the hit under the read root is not dropped.
            roots = (READ_ROOTS[0], {"root": "%ProgramData%", "expanded": "C:\\PD",
                                     "status": "unreadable", "reason": FAILURE})
            summary, _, _ = self.run_pass(
                vendors,
                inventory=inventory(folders=[folder("Contoso", False, item_id="v1"),
                                             *clean_folders], roots=roots),
                health=health_child([]))
            item = self.for_decision(summary, "D3")
            self.assert_state(item, "broken")
            self.assert_evidence(item, "ush-inventory", "v1")

    # --- K5 --------------------------------------------------------------------------------

    def test_file_states(self):
        with self.subTest("no decisions file"):
            data_dir = self.data_dir()
            fake = FakeChildren(self.temp())
            summary = self.collect(data_dir, fake)
            self.assertFalse((data_dir / "decisions.json").exists())
            self.assertEqual(self.decisions(summary), [])
            self.assertEqual(summary.get("not_checked"), [])
            self.assertEqual(self.decisions(self.detail(summary)), [])

        unreadable = (
            ("not JSON", '{"schema_version": 1, "decisions": [ invented broken'),
            ("a check of an unknown kind", json.dumps({"schema_version": 1, "decisions": [
                decision(1, [{"kind": "invented_kind", "name": "Contoso"}])]})),
        )
        for label, text in unreadable:
            with self.subTest(f"unreadable file: {label}"):
                data_dir = self.data_dir()
                (data_dir / "decisions.json").write_text(text, encoding="utf-8")
                summary = self.collect(data_dir, FakeChildren(self.temp()))
                self.assertIn("decisions", summary, sorted(summary))
                self.assertIsNone(summary["decisions"], summary["decisions"])
                notes = [entry for entry in self.items(summary, "not_checked")
                         if "decisions.json" in json.dumps(entry)]
                self.assertEqual(len(notes), 1, summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

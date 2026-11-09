"""Links between pending driver updates and driver packages no present device uses in
skills/ush-runall/scripts/runall.py (plan 028, M2, criteria K1-K4 and K6; migrated to the
device states of plan 051, M3).

Interface under test (from the plan and the contracts):

- After the children, ``runall`` reads the ``ush-health`` detail file's
  ``pending_updates`` (items ``q<n>``: ``title``, ``kb``, ``categories``, ``type``
  ``software``/``driver``, ``driver_provider``, ``driver_class``, ``driver_date``,
  ``downloaded``; source ``pending_updates``) and the ``ush-inventory`` detail file's
  ``driver_packages`` (every third-party package, items ``o<n>`` with ``provider``,
  ``original_name`` and ``device_state`` ``present`` / ``non_present`` /
  ``no_device_found`` / null; source ``driver_packages``).
  The inventory source ``devices`` must be read too (the package states come from it).
- Only updates of ``type`` ``driver`` and packages with ``device_state`` ``non_present``
  or ``no_device_found`` take part. A pair links when ``driver_provider.casefold() == provider.casefold()``; a
  provider that only contains the other (``Contoso`` / ``Contoso Ltd``) does not.
- The runall summary and detail file get ``driver_update_links``: a list of ``y<n>``
  items, ``[]`` when nothing links, ``null`` when a side was not read (the health child
  not ``ok``, ``pending_updates`` ``null``, ``driver_packages`` ``null``, or the inventory
  ``devices`` source not read); then ``not_checked`` gets an entry naming the side.
- The summary gets ``link_counts`` ``{linked, updates_without_package,
  packages_without_update}``.

Assumptions added by these tests beyond the plan text:

- A ``y`` item has the fields ``id`` (``y1``...), ``update`` (``"ush-health q<n>"``),
  ``package`` (``"ush-inventory o<n>"``), ``provider`` (the update's or the package's
  provider: only its case-folded value is compared), ``title`` (the update's title) and
  ``original_name`` (the package's ``original_name``).
- ``link_counts``: ``linked`` is the number of ``y`` items; ``updates_without_package``
  the pending driver updates that link to no package; ``packages_without_update`` the
  packages with ``device_state`` ``non_present`` or ``no_device_found`` that link to no
  update. Packages with ``device_state`` ``present`` or null count nowhere. ``link_counts`` is not asserted
  when ``driver_update_links`` is ``null``.
- The ``not_checked`` entry about the links mentions "driver update" (or
  ``driver_update_links``; underscores read as spaces, any case) in its JSON text and
  names the side that was not read (``ush-health`` or ``ush-inventory``; for an unread
  inventory ``devices`` source also the word ``devices``).
- The fake child summaries carry the same ``sources`` as their detail files (as in
  ``test_firewall_ports.py``); the inventory detail keeps ``firewall_rules`` read with no
  ``additions``, so the firewall comparison adds no entry.

K6 runs the real ``health.main`` and ``inventory.main`` over their PowerShell fakes
(``tests/ush-health/test_pending_updates.py``, ``tests/ush-inventory/fakes*.py``) in a
temporary data directory and hands their summaries to ``runall.main`` through a fake
``run_child``. PowerShell never starts; every value is invented (Contoso, Fabrikam).
"""

import importlib
import io
import json
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests.skill_loader import load_script

from .test_runall import FakeChildren, RunallTestCase, exits, result

_pending = importlib.import_module("tests.ush-health.test_pending_updates")
_health_fakes = importlib.import_module("tests.ush-health.fakes_m3")
_inv_fakes = importlib.import_module("tests.ush-inventory.fakes")
_inv_components = importlib.import_module("tests.ush-inventory.fakes_components")
_inv_packages = importlib.import_module("tests.ush-inventory.fakes_driver_packages")

CONTOSO_TITLE = "Contoso - Display - 31.0.101.4200"
SOFTWARE_TITLE = "Invented Cumulative Update for Windows (KB5099998)"


# --- invented child data -------------------------------------------------------------------

def software_update(n, title=SOFTWARE_TITLE):
    return {"id": f"q{n}", "title": title, "kb": ["KB5099998"],
            "categories": ["Security Updates", "Windows 11"], "type": "software",
            "driver_provider": None, "driver_class": None, "driver_date": None,
            "downloaded": True}


def driver_update(n, provider, title=CONTOSO_TITLE, driver_class="Display"):
    return {"id": f"q{n}", "title": title, "kb": [], "categories": ["Drivers"],
            "type": "driver", "driver_provider": provider, "driver_class": driver_class,
            "driver_date": "2026-08-15T00:00:00Z", "downloaded": False}


def driver_package(n, provider, original_name, device_state, class_name="Display",
                   version="1.0.0.0"):
    # Plan 051 M3: migrated from ``present_device`` (False -> "no_device_found",
    # True -> "present", None -> null); the fields of M1/M2 come with it.
    item = {
        "id": f"o{n}",
        "key": f"driver_package:{original_name}|{provider}|{version}".casefold(),
        "published_name": f"oem{n + 40}.inf",
        "original_name": original_name,
        "provider": provider,
        "class": class_name,
        "version": version,
        "date": "2026-03-14",
        "signer": "Invented Driver Signer",
        "device_state": device_state,
        "group": "graphics" if class_name == "Display" else "other",
        "owner": provider,
        "no_device_by_nature": False,
    }
    if device_state is None:
        item["device_state_reason"] = "invented reason: not judged"
    return item


def health_child(updates, status=None, reason=None):
    """(detail content, summary extra) of an ``ush-health`` child.

    ``updates`` ``None`` means the source was not read."""
    if status is None:
        status = "empty" if updates == [] else "read"
    sources = [{"name": "pending_updates", "status": status, "reason": reason}]
    detail = {"sources": sources, "pending_updates": updates}
    extra = {"pending_updates": updates, "last_scan": "2026-09-19T06:45:00Z"}
    return detail, extra


def inventory_child(packages, packages_status="read", drivers_status="read",
                    drivers_reason=None, packages_reason=None, devices_status="read",
                    devices_reason=None):
    """(detail content, summary extra) of an ``ush-inventory`` child.

    The detail holds every package; the summary list only those with
    ``device_state`` ``non_present`` or ``no_device_found``, or ``null`` when the packages
    or the devices were not read (as the real inventory does)."""
    sources = [
        {"name": "firewall_rules", "status": "read", "reason": None},
        {"name": "drivers", "status": drivers_status, "reason": drivers_reason},
        {"name": "devices", "status": devices_status, "reason": devices_reason},
        {"name": "driver_packages", "status": packages_status, "reason": packages_reason},
    ]
    detail = {"sources": sources, "additions": [],
              "drivers": [] if drivers_status in ("read", "empty") else None,
              "driver_packages": packages}
    if packages is None or devices_status not in ("read", "empty"):
        listed = None
    else:
        listed = [item for item in packages
                  if item.get("device_state") in ("non_present", "no_device_found")]
    return detail, {"driver_packages": listed}


class LinkChildren(FakeChildren):
    """M1's fake children, with chosen detail files for ush-health and ush-inventory.

    ``health`` / ``inventory`` are the pairs given by ``health_child`` /
    ``inventory_child``; the detail's ``sources`` also become the summary's."""

    def __init__(self, files_dir, outcomes=None, health=None, inventory=None):
        super().__init__(files_dir, outcomes)
        self.children = {"ush-health": health, "ush-inventory": inventory}

    def summary(self, skill, **kwargs):
        summary = super().summary(skill, **kwargs)
        content = self.children.get(skill)
        if content is not None:
            detail, extra = content
            summary["sources"] = detail["sources"]
            summary.update(extra)
            with open(summary["detail_file"], "w", encoding="utf-8") as handle:
                json.dump(detail, handle)
            with open(summary["summary_file"], "w", encoding="utf-8") as handle:
                json.dump(summary, handle)
        return summary


def counts(linked, updates_without_package, packages_without_update):
    # Exactly three keys (architect triage of M2 code-review, 2026-11-06): a pair left
    # unlinked by its driver class is counted only on its own side, never as a hint that
    # a link may be missing.
    return {"linked": linked, "updates_without_package": updates_without_package,
            "packages_without_update": packages_without_update}


class TestDriverUpdateLinks(RunallTestCase):
    def links(self, summary):
        self.assertIn("driver_update_links", summary, sorted(summary))
        value = summary["driver_update_links"]
        self.assertIsInstance(value, list, value)
        return value

    def link_notes(self, summary):
        return [entry for entry in self.items(summary, "not_checked")
                if "driver update" in json.dumps(entry).lower().replace("_", " ")]

    def assert_link(self, item, item_id, update_id, package_id, provider, title,
                    original_name):
        self.assertEqual(item.get("id"), item_id, item)
        self.assertEqual(item.get("update"), f"ush-health {update_id}", item)
        self.assertEqual(item.get("package"), f"ush-inventory {package_id}", item)
        self.assertIsInstance(item.get("provider"), str, item)
        self.assertEqual(item["provider"].casefold(), provider.casefold(), item)
        self.assertEqual(item.get("title"), title, item)
        self.assertEqual(item.get("original_name"), original_name, item)

    def assert_not_linked(self, summary, side, also=None):
        """``driver_update_links`` null and a link entry naming ``side``."""
        self.assertIn("driver_update_links", summary, sorted(summary))
        self.assertIsNone(summary["driver_update_links"], summary["driver_update_links"])
        notes = [entry for entry in self.link_notes(summary) if side in json.dumps(entry)]
        if also is not None:
            notes = [entry for entry in notes
                     if re.search(rf"\b{also}\b", json.dumps(entry))]
        self.assertTrue(notes, summary.get("not_checked"))

    # --- K1 ----------------------------------------------------------------------------

    def test_exact_provider_links(self):
        fake = LinkChildren(
            self.temp(),
            health=health_child([software_update(1), driver_update(3, "Contoso")]),
            inventory=inventory_child([
                driver_package(7, "contoso", "contosodisplay.inf", "no_device_found"),
                driver_package(8, "Fabrikam", "fabrikamaudio.inf", "no_device_found",
                               class_name="MEDIA"),
            ]))
        summary = self.collect(self.data_dir(), fake)

        links = self.links(summary)
        self.assertEqual(len(links), 1, links)
        self.assert_link(links[0], "y1", "q3", "o7", "Contoso", CONTOSO_TITLE,
                         "contosodisplay.inf")
        self.assertEqual(summary.get("link_counts"), counts(1, 0, 1))
        self.assertEqual(self.link_notes(summary), [], summary.get("not_checked"))

        detail = self.detail(summary)
        self.assertIn("driver_update_links", detail, sorted(detail))
        self.assertEqual(detail["driver_update_links"], links)

    def test_other_class_no_link(self):
        # Judge fix (M2 code-review round 1): one provider, another driver class is no
        # link, so a display update is never tied to an unused Bluetooth package.
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Contoso")]),
            inventory=inventory_child([
                driver_package(7, "Contoso", "contosobt.inf", "no_device_found",
                               class_name="Bluetooth"),
                driver_package(8, "Contoso", "contosodisplay.inf", "no_device_found",
                               class_name="display"),
            ]))
        summary = self.collect(self.data_dir(), fake)

        links = self.links(summary)
        self.assertEqual([link.get("package") for link in links], ["ush-inventory o8"], links)
        self.assertEqual(summary.get("link_counts"), counts(1, 0, 1))

    def test_class_not_given_no_link(self):
        # Judge fix (M2 code-review round 2): a class that is null on either side never
        # links, also when both are null; both sides stay counted as unlinked.
        cases = (
            ("update class null", None, "Display"),
            ("package class null", "Display", None),
            ("both null", None, None),
        )
        for name, update_class, package_class in cases:
            with self.subTest(case=name):
                fake = LinkChildren(
                    self.temp(),
                    health=health_child([driver_update(3, "Contoso",
                                                       driver_class=update_class)]),
                    inventory=inventory_child([
                        driver_package(7, "Contoso", "contosodisplay.inf", "no_device_found",
                                       class_name=package_class),
                    ]))
                summary = self.collect(self.data_dir(), fake)
                self.assertEqual(self.links(summary), [])
                self.assertEqual(summary.get("link_counts"), counts(0, 1, 1))

    # --- K2 ----------------------------------------------------------------------------

    def test_nothing_pending_no_links(self):
        unused = driver_package(7, "Contoso", "contosodisplay.inf", "no_device_found")
        cases = (
            ("no update pending", []),
            ("only a software update pending", [software_update(1)]),
        )
        for label, updates in cases:
            with self.subTest(label):
                fake = LinkChildren(self.temp(), health=health_child(updates),
                                    inventory=inventory_child([unused]))
                summary = self.collect(self.data_dir(), fake)
                self.assertEqual(self.links(summary), [])
                self.assertEqual(summary.get("link_counts"), counts(0, 0, 1))
                self.assertEqual(summary.get("not_checked"), [])

    # --- K3 ----------------------------------------------------------------------------

    def test_similar_provider_no_link(self):
        cases = (
            ("update Contoso, package Contoso Ltd", "Contoso", "Contoso Ltd"),
            ("update Contoso Ltd, package Contoso", "Contoso Ltd", "Contoso"),
        )
        for label, update_provider, package_provider in cases:
            with self.subTest(label):
                fake = LinkChildren(
                    self.temp(),
                    health=health_child([driver_update(3, update_provider)]),
                    inventory=inventory_child([
                        driver_package(7, package_provider, "contosodisplay.inf", "no_device_found")]))
                summary = self.collect(self.data_dir(), fake)
                self.assertEqual(self.links(summary), [])
                self.assertEqual(summary.get("link_counts"), counts(0, 1, 1))

    # --- K4 ----------------------------------------------------------------------------

    def test_side_not_read(self):
        updates = [driver_update(3, "Contoso")]
        unused = driver_package(7, "contoso", "contosodisplay.inf", "no_device_found")

        with self.subTest("the ush-health child failed"):
            fake = LinkChildren(self.temp(), {"ush-health": exits(1)},
                                health=health_child(updates),
                                inventory=inventory_child([unused]))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-health").get("status"), "failed")
            self.assert_not_linked(summary, "ush-health")

        with self.subTest("ush-health pending_updates is null"):
            fake = LinkChildren(
                self.temp(),
                health=health_child(None, status="unreadable",
                                    reason="Invented COM failure, HRESULT 0x8024402C."),
                inventory=inventory_child([unused]))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-health").get("status"), "ok")
            self.assert_not_linked(summary, "ush-health")

        with self.subTest("the ush-inventory child failed"):
            fake = LinkChildren(self.temp(), {"ush-inventory": exits(1)},
                                health=health_child(updates),
                                inventory=inventory_child([unused]))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-inventory").get("status"), "failed")
            self.assert_not_linked(summary, "ush-inventory")

        with self.subTest("ush-inventory driver_packages is null"):
            fake = LinkChildren(
                self.temp(), health=health_child(updates),
                inventory=inventory_child(None, packages_status="unreadable",
                                          packages_reason="Invented exit code 87"))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-inventory").get("status"), "ok")
            self.assert_not_linked(summary, "ush-inventory")

        with self.subTest("the ush-inventory devices source is not read"):
            # Fixed after M3 code review (judge): the states come from the devices
            # source, so an unread one is "not read", never "nothing linked".
            unjudged = driver_package(7, "contoso", "contosodisplay.inf", None)
            fake = LinkChildren(
                self.temp(), health=health_child(updates),
                inventory=inventory_child([unjudged], devices_status="unreadable",
                                          devices_reason="Invented pnputil failure"))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.child(summary, "ush-inventory").get("status"), "ok")
            self.assert_not_linked(summary, "ush-inventory", also="devices")

        with self.subTest("an unread drivers source does not stop the links"):
            fake = LinkChildren(
                self.temp(), health=health_child(updates),
                inventory=inventory_child([unused], drivers_status="unreadable",
                                          drivers_reason="Invented CIM failure"))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(len(self.links(summary)), 1, summary.get("driver_update_links"))
            self.assertEqual(summary.get("link_counts"), counts(1, 0, 0))

        with self.subTest("device_state present or null is never linked"):
            fake = LinkChildren(
                self.temp(), health=health_child(updates),
                inventory=inventory_child([
                    driver_package(7, "contoso", "contosodisplay.inf", "present"),
                    driver_package(9, "Contoso", "contosodisplayext.inf", None,
                                   class_name="Extension"),
                ]))
            summary = self.collect(self.data_dir(), fake)
            self.assertEqual(self.links(summary), [])
            self.assertEqual(summary.get("link_counts"), counts(0, 1, 0))

    # --- K6 ----------------------------------------------------------------------------

    def run_skill(self, module, data_dir, run_ps, now):
        """Run a child skill's real ``main`` over its PowerShell fake; return its stdout
        (the summary JSON)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = module.main(["--data-dir", str(data_dir)], run_ps=run_ps,
                               is_admin=lambda: True, now=now)
        self.assertEqual(code, 0, err.getvalue()[-500:])
        return out.getvalue()

    def test_real_detail_files_link(self):
        health = load_script("ush-health", "health")
        inventory = load_script("ush-inventory", "inventory")
        # Tests never read the machine: no NPM_CONFIG_PREFIX of this process.
        inventory.ENVIRON = {}
        skills_dir = self.temp() / "skills-data"

        health_stdout = self.run_skill(
            health, skills_dir, _pending.FakePowerShell({"pending_updates": _health_fakes.ok(
                _pending.search_result([
                    _pending.software_update(),
                    _pending.driver_update(title=CONTOSO_TITLE, provider="Contoso"),
                ]))}),
            _health_fakes.NOW)

        contoso = _inv_packages.package("oem3.inf", "contosodisplay.inf", provider="contoso",
                                        class_name="Display")
        fabrikam = _inv_packages.package("oem4.inf", "fabrikamaudio.inf",
                                         provider="Fabrikam", class_name="MEDIA")
        inventory_stdout = self.run_skill(
            inventory, skills_dir, _inv_fakes.FakePowerShell({
                "driver_packages": _inv_packages.store([contoso, fabrikam]),
                "drivers": _inv_fakes.ok([_inv_components.driver(
                    "PCI\\VEN_1AAA&DEV_0050\\0050", "oem99.inf")]),
                # Plan 051 M3: the package states come from the ``devices`` source; one
                # started device names another package, so both stay no_device_found.
                "devices": _inv_packages.devices_answer([_inv_packages.device(
                    "PCI\\VEN_1AAA&DEV_0050\\0050", "oem99.inf", "Started")]),
            }),
            _inv_fakes.NOW)

        health_summary = json.loads(health_stdout)
        inventory_summary = json.loads(inventory_stdout)
        driver_items = [item for item in health_summary.get("pending_updates") or []
                        if item.get("type") == "driver"]
        self.assertEqual(len(driver_items), 1, health_summary.get("pending_updates"))
        packages = {item.get("original_name"): item
                    for item in inventory_summary.get("driver_packages") or []}
        self.assertEqual(set(packages), {"contosodisplay.inf", "fabrikamaudio.inf"},
                         inventory_summary.get("driver_packages"))

        fake = FakeChildren(self.temp(), {
            "ush-health": lambda fake, skill, argv, timeout_s: result(stdout=health_stdout),
            "ush-inventory":
                lambda fake, skill, argv, timeout_s: result(stdout=inventory_stdout),
        })
        summary = self.collect(self.data_dir(), fake)
        self.assertEqual(self.child(summary, "ush-health").get("status"), "ok")
        self.assertEqual(self.child(summary, "ush-inventory").get("status"), "ok")

        links = self.links(summary)
        self.assertEqual(len(links), 1, links)
        self.assert_link(links[0], "y1", driver_items[0]["id"],
                         packages["contosodisplay.inf"]["id"], "Contoso", CONTOSO_TITLE,
                         "contosodisplay.inf")
        self.assertEqual(summary.get("link_counts"), counts(1, 0, 1))
        self.assertEqual(self.link_notes(summary), [], summary.get("not_checked"))
        self.assertEqual(self.detail(summary).get("driver_update_links"), links)


# --- plan 051, M3: links follow the device states ------------------------------------------
#
# Interface under test (plan 051, M1-M3): an ``ush-inventory`` package carries
# ``device_state`` (``present`` / ``non_present`` / ``no_device_found`` / null), ``devices``
# for ``non_present``, ``group``, ``owner`` and ``no_device_by_nature``; ``present_device``
# is gone. The summary list ``driver_packages`` holds the ``non_present`` and
# ``no_device_found`` packages. ``link_driver_updates`` keeps only those two states and
# each ``y`` item adds ``package_state`` (the package's ``device_state``),
# ``package_group`` (the package's ``group``) and ``package_no_device_by_nature``.
#
# Assumptions added by these tests: the order of the ``y`` items is not asserted; the
# inventory child also reports a read ``devices`` source next to ``drivers`` and
# ``driver_packages``.

def stated_package(n, provider, original_name, device_state, class_name="Display",
                   group="graphics", version="1.0.0.0"):
    item = {
        "id": f"o{n}",
        "key": f"driver_package:{original_name}|{provider}|{version}".casefold(),
        "published_name": f"oem{n + 40}.inf",
        "original_name": original_name,
        "provider": provider,
        "class": class_name,
        "version": version,
        "date": "2026-03-14",
        "signer": "Invented Driver Signer",
        "device_state": device_state,
        "group": group,
        "owner": provider,
        "no_device_by_nature": False,
    }
    if device_state == "non_present":
        item["devices"] = [{"device_name": "Invented External Display Adapter",
                            "class": class_name, "status": "Disconnected",
                            "last_removal": "2026-07-02"}]
    if device_state is None:
        item["device_state_reason"] = "invented reason: device state not judged"
    return item


def stated_inventory_child(packages):
    """(detail content, summary extra) of an ``ush-inventory`` child with device states.

    The detail holds every package; the summary list those ``non_present`` or
    ``no_device_found``."""
    sources = [
        {"name": "firewall_rules", "status": "read", "reason": None},
        {"name": "drivers", "status": "read", "reason": None},
        {"name": "devices", "status": "read", "reason": None},
        {"name": "driver_packages", "status": "read", "reason": None},
    ]
    detail = {"sources": sources, "additions": [], "drivers": [],
              "driver_packages": packages}
    listed = [item for item in packages
              if item.get("device_state") in ("non_present", "no_device_found")]
    return detail, {"driver_packages": listed}


class TestDeviceStates(RunallTestCase):
    def links(self, summary):
        self.assertIn("driver_update_links", summary, sorted(summary))
        value = summary["driver_update_links"]
        self.assertIsInstance(value, list, value)
        return value

    # --- K1 ----------------------------------------------------------------------------

    def test_links_follow_states(self):
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Contoso")]),
            inventory=stated_inventory_child([
                stated_package(7, "Contoso", "contosodisplayold.inf", "non_present"),
                stated_package(8, "contoso", "contosodisplayext.inf", "no_device_found"),
                stated_package(9, "Contoso", "contosodisplay.inf", "present"),
            ]))
        summary = self.collect(self.data_dir(), fake)

        links = self.links(summary)
        by_package = {link.get("package"): link for link in links}
        self.assertEqual(len(by_package), len(links), links)
        self.assertEqual(set(by_package), {"ush-inventory o7", "ush-inventory o8"}, links)
        self.assertNotIn("ush-inventory o9", by_package, links)

        expected = {
            "ush-inventory o7": ("contosodisplayold.inf", "non_present"),
            "ush-inventory o8": ("contosodisplayext.inf", "no_device_found"),
        }
        for package, (original_name, state) in expected.items():
            with self.subTest(package=package):
                item = by_package[package]
                self.assertEqual(item.get("update"), "ush-health q3", item)
                self.assertEqual(item.get("title"), CONTOSO_TITLE, item)
                self.assertEqual(item.get("original_name"), original_name, item)
                self.assertIsInstance(item.get("provider"), str, item)
                self.assertEqual(item["provider"].casefold(), "contoso", item)
                self.assertIn("package_state", item, sorted(item))
                self.assertEqual(item["package_state"], state, item)
                self.assertIn("package_group", item, sorted(item))
                self.assertEqual(item["package_group"], "graphics", item)
        self.assertEqual(sorted(link.get("id") for link in links), ["y1", "y2"], links)

    # --- K2 ----------------------------------------------------------------------------

    def test_null_state_not_linked(self):
        # A package whose device state is not known (null) is never linked and is not
        # counted as a package without a device; a no_device_found package of another
        # provider and class is the control that is counted.
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Contoso")]),
            inventory=stated_inventory_child([
                stated_package(7, "Contoso", "contosodisplayold.inf", None),
                stated_package(8, "Fabrikam", "fabrikamaudio.inf", "no_device_found",
                               class_name="MEDIA", group="peripherals"),
            ]))
        summary = self.collect(self.data_dir(), fake)

        links = self.links(summary)
        self.assertEqual(links, [], links)
        self.assertEqual(summary.get("link_counts"), counts(0, 1, 1))


if __name__ == "__main__":
    unittest.main()

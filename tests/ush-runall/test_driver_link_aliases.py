"""Driver update links through the alias table in skills/ush-runall/scripts/runall.py
(plan 041, M1, criteria K1-K8; K9 is the unchanged ``test_driver_update_links``).

Interface under test (from the plan):

- ``runall.py`` has a module constant ``ALIASES_FILE`` (a ``Path``) that points to
  ``skills/ush-runall/data/driver-link-aliases.json``; these tests patch it to a
  temporary JSON file they write.
- Table shape: ``{"classes": [{"windows_update": str, "inf": [str, ...], "seen": str}],
  "providers": [{"names": [str, ...], "seen": str}]}``.
- A pending driver update and an orphan package link when the providers are equal after
  case-folding or are in one provider group (both directions), and the classes are equal
  after case-folding or the package's class is in the ``inf`` list of the update's class
  (one way: Windows Update -> INF). Every pair is one ``y<n>`` item.
- A table that cannot be read or has a wrong shape gives exact-name links only and one
  ``not_checked`` entry naming the file.
- The summary carries ``driver_update_links`` (``y<n>`` items with ``update``
  ``"ush-health q<n>"`` and ``package`` ``"ush-inventory o<n>"``) and ``link_counts``
  ``{linked, updates_without_package, packages_without_update}``.

Assumptions added by these tests beyond the plan text:

- ``ALIASES_FILE`` is read at run time (inside ``main``), so patching the module
  constant with ``mock.patch.object`` around ``collect`` is enough, as with
  ``CHILDREN_FILE``.
- ``link_counts`` follows ``test_driver_update_links``: ``updates_without_package`` counts
  the pending driver updates linked to no package, ``packages_without_update`` the
  packages with ``present_device`` false linked to no update.
- In K7 the ``not_checked`` entry "names the file" when its JSON text contains either
  the temporary file's name or ``driver-link-aliases``; exactly one such entry is
  expected. Its wording ("only exact names were linked") is not asserted.
- In K7 the "name in two provider groups" case uses names that are equal only after
  case-folding (``Fabrikam`` / ``fabrikam``), which the plan counts as the same name.
- In K6 the order of the two ``y`` items is not asserted; their ids must be ``y1`` and
  ``y2``.
- The shipped table (K8) is read as UTF-8 with an optional BOM; its ``seen`` values must
  be non-empty strings.

All names are invented (Contoso, Fabrikam); nothing touches the machine.
"""

import json
import unittest
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .test_driver_update_links import (
    LinkChildren,
    counts,
    driver_package,
    driver_update,
    health_child,
    inventory_child,
)
from .test_runall import RunallTestCase

SHIPPED_ALIASES = REPO_ROOT / "skills" / "ush-runall" / "data" / "driver-link-aliases.json"
SEEN = "invented test line, not a real run"


def class_line(windows_update, inf):
    return {"windows_update": windows_update, "inf": inf, "seen": SEEN}


def provider_group(*names):
    return {"names": list(names), "seen": SEEN}


def table(classes=(), providers=()):
    return {"classes": list(classes), "providers": list(providers)}


# A valid table with the lines used by K1-K5.
BASE_TABLE = table(
    classes=[class_line("Graphics", ["Display"])],
    providers=[provider_group("Contoso", "Contoso Holdings")],
)


class AliasTestCase(RunallTestCase):
    def aliases_file(self, content, name="aliases.json"):
        """Write ``content`` (a dict as JSON, or a str as is) to a temp file; return its
        path."""
        path = self.temp() / name
        text = content if isinstance(content, str) else json.dumps(content)
        path.write_text(text, encoding="utf-8")
        return path

    def collect_with(self, aliases_path, fake):
        with mock.patch.object(self.runall, "ALIASES_FILE", aliases_path):
            return self.collect(self.data_dir(), fake)

    def links(self, summary):
        self.assertIn("driver_update_links", summary, sorted(summary))
        value = summary["driver_update_links"]
        self.assertIsInstance(value, list, value)
        return value

    def pairs(self, links):
        return sorted((item.get("update"), item.get("package")) for item in links)


class TestDriverLinkAliases(AliasTestCase):
    # --- K1 ----------------------------------------------------------------------------

    def test_class_and_provider_through_table(self):
        cases = (
            ("update Contoso, package Contoso Holdings", "Contoso", "Contoso Holdings"),
            ("update Contoso Holdings, package Contoso", "Contoso Holdings", "Contoso"),
        )
        for label, update_provider, package_provider in cases:
            with self.subTest(label):
                fake = LinkChildren(
                    self.temp(),
                    health=health_child([driver_update(3, update_provider,
                                                       driver_class="Graphics")]),
                    inventory=inventory_child([
                        driver_package(7, package_provider, "contosodisplay.inf", False,
                                       class_name="Display")]))
                summary = self.collect_with(self.aliases_file(BASE_TABLE), fake)

                links = self.links(summary)
                self.assertEqual(len(links), 1, links)
                self.assertEqual(links[0].get("id"), "y1", links[0])
                self.assertEqual(links[0].get("update"), "ush-health q3", links[0])
                self.assertEqual(links[0].get("package"), "ush-inventory o7", links[0])
                self.assertEqual(summary.get("link_counts"), counts(1, 0, 0))

    # --- K2 ----------------------------------------------------------------------------

    def test_clean_data_no_link(self):
        # Providers differ and classes differ; neither pair is in the table, which holds
        # other lines.
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Fabrikam", driver_class="Bluetooth")]),
            inventory=inventory_child([
                driver_package(7, "Fabrikam Labs", "fabrikamports.inf", False,
                               class_name="Ports")]))
        summary = self.collect_with(self.aliases_file(BASE_TABLE), fake)

        self.assertEqual(self.links(summary), [])
        self.assertEqual(summary.get("link_counts"), counts(0, 1, 1))

    # --- K3 ----------------------------------------------------------------------------

    def test_provider_alias_class_unmapped_no_link(self):
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Contoso", driver_class="Bluetooth")]),
            inventory=inventory_child([
                driver_package(7, "Contoso Holdings", "contosoports.inf", False,
                               class_name="Ports")]))
        summary = self.collect_with(self.aliases_file(BASE_TABLE), fake)

        self.assertEqual(self.links(summary), [])
        self.assertEqual(summary.get("link_counts"), counts(0, 1, 1))

    # --- K4 ----------------------------------------------------------------------------

    def test_class_mapped_provider_differs_no_link(self):
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Contoso", driver_class="Graphics")]),
            inventory=inventory_child([
                driver_package(7, "Fabrikam", "fabrikamdisplay.inf", False,
                               class_name="Display")]))
        summary = self.collect_with(self.aliases_file(BASE_TABLE), fake)

        self.assertEqual(self.links(summary), [])
        self.assertEqual(summary.get("link_counts"), counts(0, 1, 1))

    # --- K5 ----------------------------------------------------------------------------

    def test_class_mapping_one_way(self):
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Contoso", driver_class="Display")]),
            inventory=inventory_child([
                driver_package(7, "Contoso", "contosographics.inf", False,
                               class_name="Graphics")]))
        summary = self.collect_with(self.aliases_file(BASE_TABLE), fake)

        self.assertEqual(self.links(summary), [])
        self.assertEqual(summary.get("link_counts"), counts(0, 1, 1))

    # --- K6 ----------------------------------------------------------------------------

    def test_one_update_two_packages(self):
        aliases = table(classes=[class_line("Graphics", ["Display", "Extension"])])
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, "Contoso", driver_class="Graphics")]),
            inventory=inventory_child([
                driver_package(7, "Contoso", "contosodisplay.inf", False,
                               class_name="Display"),
                driver_package(8, "Contoso", "contosodisplayext.inf", False,
                               class_name="Extension"),
            ]))
        summary = self.collect_with(self.aliases_file(aliases), fake)

        links = self.links(summary)
        self.assertEqual(len(links), 2, links)
        self.assertEqual(sorted(item.get("id") for item in links), ["y1", "y2"], links)
        self.assertEqual(self.pairs(links), [
            ("ush-health q3", "ush-inventory o7"),
            ("ush-health q3", "ush-inventory o8"),
        ])
        self.assertEqual(summary.get("link_counts"), counts(2, 0, 0))

    # --- K7 ----------------------------------------------------------------------------

    def test_unreadable_table_exact_only(self):
        # Each bad table would link the alias-only pair (q4 Fabrikam/Graphics with
        # o8 Fabrikam Holdings/Display) if it were used; only the exact pair
        # (q3 Contoso/Display with o7 Contoso/Display) may link.
        valid_classes = [class_line("Graphics", ["Display"])]
        valid_group = provider_group("Fabrikam", "Fabrikam Holdings")
        cases = (
            ("missing file", "missing-aliases.json", None),
            ("not JSON", "not-json-aliases.json", "{\"classes\": [ this is not JSON"),
            ("inf given as a string", "inf-string-aliases.json",
             table(classes=[class_line("Graphics", "Display")], providers=[valid_group])),
            ("a name in two provider groups", "two-groups-aliases.json",
             table(classes=valid_classes,
                   providers=[valid_group, provider_group("fabrikam", "Fabrikam Labs")])),
        )
        for label, name, content in cases:
            with self.subTest(label):
                if content is None:
                    path = self.temp() / name
                    self.assertFalse(path.exists(), path)
                else:
                    path = self.aliases_file(content, name)
                fake = LinkChildren(
                    self.temp(),
                    health=health_child([
                        driver_update(3, "Contoso", driver_class="Display"),
                        driver_update(4, "Fabrikam", title="Fabrikam - Graphics - 2.0",
                                      driver_class="Graphics"),
                    ]),
                    inventory=inventory_child([
                        driver_package(7, "Contoso", "contosodisplay.inf", False,
                                       class_name="Display"),
                        driver_package(8, "Fabrikam Holdings", "fabrikamdisplay.inf", False,
                                       class_name="Display"),
                    ]))
                summary = self.collect_with(path, fake)

                links = self.links(summary)
                self.assertEqual(self.pairs(links),
                                 [("ush-health q3", "ush-inventory o7")], links)
                self.assertEqual(summary.get("link_counts"), counts(1, 1, 1))

                notes = [entry for entry in self.items(summary, "not_checked")
                         if name in json.dumps(entry)
                         or "driver-link-aliases" in json.dumps(entry)]
                self.assertEqual(len(notes), 1, summary.get("not_checked"))


class TestShippedAliases(unittest.TestCase):
    # --- K8 ----------------------------------------------------------------------------

    def assert_text(self, value, where):
        self.assertIsInstance(value, str, where)
        self.assertTrue(value.strip(), where)

    def test_shape(self):
        self.assertTrue(SHIPPED_ALIASES.is_file(),
                        f"the shipped alias table is missing: {SHIPPED_ALIASES}")
        data = json.loads(SHIPPED_ALIASES.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))

        classes = data.get("classes")
        self.assertIsInstance(classes, list, data)
        seen_updates = []
        for entry in classes:
            self.assertIsInstance(entry, dict, entry)
            self.assert_text(entry.get("windows_update"), entry)
            inf = entry.get("inf")
            self.assertIsInstance(inf, list, entry)
            self.assertTrue(inf, entry)
            for name in inf:
                self.assert_text(name, entry)
            self.assert_text(entry.get("seen"), entry)
            seen_updates.append(entry["windows_update"].casefold())
        self.assertEqual(len(seen_updates), len(set(seen_updates)),
                         f"a windows_update name appears twice: {classes}")

        providers = data.get("providers")
        self.assertIsInstance(providers, list, data)
        group_of = {}
        for index, group in enumerate(providers):
            self.assertIsInstance(group, dict, group)
            names = group.get("names")
            self.assertIsInstance(names, list, group)
            self.assertGreaterEqual(len(names), 2, group)
            for name in names:
                self.assert_text(name, group)
            self.assert_text(group.get("seen"), group)
            for key in {name.casefold() for name in names}:
                self.assertNotIn(key, group_of,
                                 f"{key!r} is in groups {group_of.get(key)} and {index}")
                group_of[key] = index



class TestLinkEvidence(AliasTestCase):
    """Final review of plan 041 (judge: fix): a ``y`` item carries both sides' provider
    and class and says per side whether equal names or a table line made the link."""

    def link(self, update, package, aliases=BASE_TABLE):
        fake = LinkChildren(
            self.temp(),
            health=health_child([driver_update(3, update[0], driver_class=update[1])]),
            inventory=inventory_child([
                driver_package(7, package[0], "contosodisplay.inf", False,
                               class_name=package[1])]))
        path = self.aliases_file(aliases)
        summary = self.collect_with(path, fake)
        links = self.links(summary)
        self.assertEqual(len(links), 1, links)
        return links[0], summary

    def test_both_sides_and_how_each_matched(self):
        cases = (
            ("both through the table", ("Contoso", "Graphics"),
             ("Contoso Holdings", "Display"), "table", "table"),
            ("both equal", ("Contoso", "Display"), ("contoso", "display"),
             "equal", "equal"),
            ("equal provider, class through the table", ("Contoso", "Graphics"),
             ("contoso", "Display"), "equal", "table"),
            ("provider through the table, equal class", ("Contoso", "Display"),
             ("Contoso Holdings", "display"), "table", "equal"),
        )
        for label, update, package, provider_via, class_via in cases:
            with self.subTest(label):
                item, _ = self.link(update, package)
                self.assertEqual(item.get("provider"), update[0])
                self.assertEqual(item.get("driver_class"), update[1])
                self.assertEqual(item.get("package_provider"), package[0])
                self.assertEqual(item.get("package_class"), package[1])
                self.assertEqual(item.get("provider_via"), provider_via)
                self.assertEqual(item.get("class_via"), class_via)

    def test_unusable_table_links_say_equal(self):
        item, summary = self.link(("Contoso", "Display"), ("Contoso", "Display"),
                                  aliases="not json")
        self.assertEqual((item.get("provider_via"), item.get("class_via")),
                         ("equal", "equal"))
        notes = [entry for entry in summary.get("not_checked", [])
                 if "aliases" in json.dumps(entry)]
        self.assertEqual(len(notes), 1, summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

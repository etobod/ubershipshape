"""pipx and uv tools, and the manager state not_present (plan 066, M1, K1-K7, K9, K10).

Interface these tests assume (fixed before the code exists):

- Jobs ``pipx_homes`` and ``uv_tools`` as described in ``fakes.py``. The raw pipx homes
  are ``fakes.DEFAULT_PIPX_HOMES`` in that order, or only a non-blank ``PIPX_HOME`` (read
  from the module's ``ENVIRON``); the raw uv tool folder is ``fakes.DEFAULT_UV_FOLDER``,
  or only ``UV_TOOL_DIR``.
- Sources ``pipx_packages`` and ``uv_tools`` (in ``comparison``, the baseline and
  ``changes[].source``), compared on ``version``. The detail file keeps their items in
  lists of the same names, each item with its ``key``.
- Keys ``pipx:<venv>``, ``pipx:<venv>|<injected>``, ``pipx:<venv>~2``, ``uv:<tool>``
  (case-folded). pipx items carry ``name``, ``version``, ``venv``, ``injected``,
  ``folder`` (raw home + ``\\venvs\\<venv>``); uv items ``name``, ``version``, ``folder``.
- ``managers.pipx`` / ``managers.uv``: ``{state: "not_present", looked_in: [raw paths]}``
  when no location exists, else ``{state, status, homes|folder, count, unreadable}``.
- ``not_checked`` notes: what ``pipx homes outside looked_in`` and ``uv tools outside
  looked_in`` (state ``read`` or ``not_present``); "pipx shared libraries" and "Python
  installs managed by uv" only when read.
- A pipx change carries ``venv``.

PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.
"""

import json
import re
import unittest
from datetime import timedelta
from unittest import mock

from .fakes import (
    DEFAULT_PIPX_HOMES,
    DEFAULT_UV_FOLDER,
    NOW,
    PackagesTestCase,
    note_text,
    package,
    packages_fake,
    pipx_home,
    pipx_venv,
    pipx_venv_text,
    read_folder,
    unreadable_folder,
    unreadable_home,
    uv_entry,
    uv_folder,
    uv_site_packages,
)

PIPX_OUTSIDE = "pipx homes outside looked_in"
UV_OUTSIDE = "uv tools outside looked_in"
PIPX_SHARED = "pipx shared libraries"
UV_PYTHONS = "python installs managed by uv"
NOT_READ_YET = "not read yet"
DENIED = "Access to the path is denied (invented)"

HOME_NEW = DEFAULT_PIPX_HOMES[0]    # %USERPROFILE%\pipx
HOME_OLD = DEFAULT_PIPX_HOMES[1]    # %USERPROFILE%\.local\pipx
CONTOSO = "pipx:contoso-cli"
FABRIKAM = "pipx:contoso-cli|fabrikam-plugin"
WOODGROVE = "uv:woodgrove-lint"
CONTOSO_FMT = "uv:contoso-fmt"


def mentions_uv(item):
    return re.search(r"(?<![a-z0-9])uv(?![a-z0-9])", note_text(item)) is not None


class PipxUvTestCase(PackagesTestCase):
    def items(self, summary, source):
        items = self.detail(summary).get(source)
        self.assertIsInstance(items, list, f"detail {source}: {items!r}")
        return self.by_key(items)

    def pipx_items(self, summary):
        return self.items(summary, "pipx_packages")

    def uv_items(self, summary):
        return self.items(summary, "uv_tools")

    def saved(self, data_dir, source):
        state = json.loads((data_dir / "state" / "ush-packages.json")
                           .read_text(encoding="utf-8-sig"))
        return state["sources"].get(source) or {}


class TestNotPresent(PipxUvTestCase):
    def test_absent_managers_are_not_present(self):
        fake = packages_fake()
        summary = self.collect(fake, data_dir=self.data_dir(), now=NOW)

        self.assertEqual(self.manager(summary, "pipx"),
                         {"state": "not_present", "looked_in": list(DEFAULT_PIPX_HOMES)})
        self.assertEqual(self.manager(summary, "uv"),
                         {"state": "not_present", "looked_in": [DEFAULT_UV_FOLDER]})

        notes = self.not_checked(summary)
        pipx_notes = [item for item in notes if "pipx" in note_text(item)]
        self.assertEqual([item.get("what") for item in pipx_notes], [PIPX_OUTSIDE], notes)
        uv_notes = [item for item in notes if mentions_uv(item)]
        self.assertEqual([item.get("what") for item in uv_notes], [UV_OUTSIDE], notes)
        for item in notes:
            self.assertNotIn(PIPX_SHARED, note_text(item), notes)
            self.assertNotIn(UV_PYTHONS, note_text(item), notes)
        for item in pipx_notes + uv_notes:
            self.assertNotIn(NOT_READ_YET, note_text(item), item)
            self.assertTrue(str(item.get("reason") or "").strip(), item)

        managers = {item.get("manager") for item in self.package_list(summary)}
        self.assertNotIn("pipx", managers, summary.get("packages"))
        self.assertNotIn("uv", managers, summary.get("packages"))

        comparison = self.comparison(summary)
        self.assertNotEqual(comparison.get("pipx_packages"), "not_read", comparison)
        self.assertNotEqual(comparison.get("uv_tools"), "not_read", comparison)
        self.assertEqual(comparison.get("pipx_packages"), "no_baseline", comparison)
        self.assertEqual(comparison.get("uv_tools"), "no_baseline", comparison)

    def test_unlistable_home_is_unreadable(self):
        data_dir = self.data_dir()
        self.collect(
            packages_fake(pipx={HOME_NEW: pipx_home(
                pipx_venv("contoso-cli", "contoso-cli", "2.1.0"))}),
            data_dir=data_dir, now=NOW)
        run2 = self.collect(
            packages_fake(pipx={HOME_NEW: unreadable_home(DENIED)}),
            data_dir=data_dir, now=NOW + timedelta(days=1))

        pipx = self.manager(run2, "pipx")
        self.assertEqual(pipx.get("state"), "unreadable", pipx)
        self.assertNotEqual(pipx.get("state"), "not_present", pipx)
        self.assertIn("count", pipx, pipx)
        self.assertIsNone(pipx["count"], pipx)
        self.assertEqual(self.source(run2, "pipx_packages").get("status"), "unreadable")

        notes = [item for item in self.notes_with(run2, "pipx")
                 if DENIED.casefold() in note_text(item)]
        self.assertTrue(notes, run2.get("not_checked"))

        items = self.pipx_items(run2)
        self.assertEqual(set(items), {CONTOSO}, sorted(map(str, items)))
        self.assertIs(items[CONTOSO].get("from_baseline"), True, items[CONTOSO])
        self.assertEqual(items[CONTOSO].get("version"), "2.1.0", items[CONTOSO])
        self.assertEqual(self.changes_from(run2, "pipx_packages"), [])

    def test_present_and_empty_is_read(self):
        summary = self.collect(packages_fake(pipx={HOME_NEW: pipx_home()},
                                             uv={DEFAULT_UV_FOLDER: uv_folder()}))
        for name in ("pipx", "uv"):
            with self.subTest(manager=name):
                entry = self.manager(summary, name)
                self.assertEqual(entry.get("state"), "read", entry)
                self.assertNotEqual(entry.get("state"), "not_present", entry)
                self.assertIn("count", entry, entry)
                self.assertEqual(entry["count"], 0, entry)
        self.assertEqual(self.pipx_items(summary), {})
        self.assertEqual(self.uv_items(summary), {})


class TestPipx(PipxUvTestCase):
    def test_main_and_injected_packages(self):
        broken = "{ this is not JSON (invented)"
        summary = self.collect(packages_fake(pipx={HOME_NEW: pipx_home(
            pipx_venv("contoso-cli", "contoso-cli", "2.1.0",
                      injected={"fabrikam-plugin": "0.3"}),
            pipx_venv_text("northwind-tool", broken))}))

        items = self.pipx_items(summary)
        self.assertEqual(set(items), {CONTOSO, FABRIKAM, "pipx:northwind-tool"},
                         sorted(map(str, items)))

        main = items[CONTOSO]
        self.assertEqual(main.get("name"), "contoso-cli", main)
        self.assertEqual(main.get("version"), "2.1.0", main)
        self.assertEqual(main.get("venv"), "contoso-cli", main)
        self.assertIs(main.get("injected"), False, main)
        self.assertEqual(main.get("status"), "read", main)

        injected = items[FABRIKAM]
        self.assertEqual(injected.get("name"), "fabrikam-plugin", injected)
        self.assertEqual(injected.get("version"), "0.3", injected)
        self.assertEqual(injected.get("venv"), "contoso-cli", injected)
        self.assertIs(injected.get("injected"), True, injected)
        self.assertEqual(injected.get("status"), "read", injected)

        bad = items["pipx:northwind-tool"]
        self.assertEqual(bad.get("status"), "unreadable", bad)
        self.assertIsInstance(bad.get("reason"), str, bad)
        self.assertTrue(bad["reason"].strip(), bad)

    def test_pipx_home_variable(self):
        custom = "D:\\Invented\\pipx-home"
        pipx = {custom: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "2.1.0")),
                HOME_NEW: pipx_home(pipx_venv("tailspin-tool", "tailspin-tool", "1.0.0"))}
        with mock.patch.object(self.packages, "ENVIRON", {"PIPX_HOME": custom}):
            fake = packages_fake(pipx=pipx)
            summary = self.collect(fake)

        self.assertEqual(fake.pipx_inputs, [custom], fake.pipx_inputs)
        for home in DEFAULT_PIPX_HOMES:
            self.assertNotIn(home.casefold(),
                             [path.casefold() for path in fake.pipx_inputs], home)
        self.assertEqual(self.manager(summary, "pipx").get("state"), "read",
                         self.manager(summary, "pipx"))
        items = self.pipx_items(summary)
        self.assertEqual(set(items), {CONTOSO}, sorted(map(str, items)))
        self.assertEqual(items[CONTOSO].get("version"), "2.1.0", items[CONTOSO])

    def test_same_venv_in_two_homes(self):
        fake = packages_fake(pipx={
            HOME_NEW: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "2.1.0")),
            HOME_OLD: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "1.9.0")),
        })
        summary = self.collect(fake)

        self.assertEqual(fake.pipx_inputs, list(DEFAULT_PIPX_HOMES), fake.pipx_inputs)
        items = self.pipx_items(summary)
        second = CONTOSO + "~2"
        self.assertEqual(set(items), {CONTOSO, second}, sorted(map(str, items)))
        self.assertEqual(items[CONTOSO].get("version"), "2.1.0", items[CONTOSO])
        self.assertEqual(items[CONTOSO].get("folder"),
                         HOME_NEW + "\\venvs\\contoso-cli", items[CONTOSO])
        self.assertEqual(items[second].get("version"), "1.9.0", items[second])
        self.assertEqual(items[second].get("folder"),
                         HOME_OLD + "\\venvs\\contoso-cli", items[second])

    def test_label_kept_when_earlier_home_loses_venv(self):
        """Fixes 066 final-review #1: when the first home's venv goes away, the second
        home's same-named venv keeps its ``~2`` key, so no false ``changed``."""
        data_dir = self.data_dir()
        self.collect(packages_fake(pipx={
            HOME_NEW: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "2.1.0")),
            HOME_OLD: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "1.9.0")),
        }), data_dir=data_dir, now=NOW)
        second = self.collect(packages_fake(pipx={
            HOME_NEW: pipx_home(),
            HOME_OLD: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "1.9.0")),
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        items = self.pipx_items(second)
        self.assertEqual(set(items), {CONTOSO + "~2"}, sorted(map(str, items)))
        changes = self.changes_from(second, "pipx_packages")
        self.assertEqual([c.get("change") for c in changes], ["removed"], changes)
        self.assertEqual(changes[0].get("key"), CONTOSO, changes)

        # A new venv of the same name then takes the first free label, not ~2.
        third = self.collect(packages_fake(pipx={
            HOME_NEW: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "2.2.0")),
            HOME_OLD: pipx_home(pipx_venv("contoso-cli", "contoso-cli", "1.9.0")),
        }), data_dir=data_dir, now=NOW + timedelta(days=2))
        items = self.pipx_items(third)
        self.assertEqual(items[CONTOSO + "~2"].get("version"), "1.9.0", items)
        self.assertEqual(items[CONTOSO].get("version"), "2.2.0", items)
        changes = self.changes_from(third, "pipx_packages")
        self.assertEqual([(c.get("change"), c.get("key")) for c in changes],
                         [("added", CONTOSO)], changes)


class TestUv(PipxUvTestCase):
    def uv_fake(self, woodgrove):
        return packages_fake(
            uv={DEFAULT_UV_FOLDER: uv_folder(
                uv_entry("woodgrove-lint"),
                uv_entry("stray-folder", receipt=False),
                uv_entry("contoso-fmt"))},
            folders={
                uv_site_packages("woodgrove-lint"): woodgrove,
                uv_site_packages("stray-folder"): read_folder(
                    package("stray_folder", "9.9.9")),
                uv_site_packages("contoso-fmt"): read_folder(
                    package("click", "8.1.7")),
            })

    def test_tool_version_from_dist_info(self):
        data_dir = self.data_dir()
        woodgrove = read_folder(
            package("woodgrove_lint", "1.4.2", entry="woodgrove_lint-1.4.2.dist-info"),
            package("click", "8.1.7"))
        fake = self.uv_fake(woodgrove)
        first = self.collect(fake, data_dir=data_dir, now=NOW)

        items = self.uv_items(first)
        self.assertEqual(set(items), {WOODGROVE, CONTOSO_FMT}, sorted(map(str, items)))
        tool = items[WOODGROVE]
        self.assertEqual(tool.get("version"), "1.4.2", tool)
        self.assertEqual(tool.get("status"), "read", tool)
        self.assertNotIn(uv_site_packages("stray-folder").casefold(),
                         [path.casefold() for path in fake.input_paths()],
                         fake.input_paths())

        no_dist_info = items[CONTOSO_FMT]
        self.assertEqual(no_dist_info.get("status"), "unreadable", no_dist_info)
        self.assertEqual(no_dist_info.get("reason"), "no dist-info of the tool's package",
                         no_dist_info)

        # Second run: woodgrove-lint's site-packages cannot be listed.
        second = self.collect(self.uv_fake(unreadable_folder(DENIED)),
                              data_dir=data_dir, now=NOW + timedelta(days=1))
        items = self.uv_items(second)
        self.assertIn(WOODGROVE, items, sorted(map(str, items)))
        self.assertIs(items[WOODGROVE].get("from_baseline"), True, items[WOODGROVE])
        self.assertEqual(items[WOODGROVE].get("version"), "1.4.2", items[WOODGROVE])
        notes = [item for item in self.notes_with(second, "woodgrove-lint")
                 if DENIED.casefold() in note_text(item)]
        self.assertTrue(notes, second.get("not_checked"))
        removed = [change for change in self.changes_from(second, "uv_tools")
                   if change.get("change") == "removed"]
        self.assertEqual(removed, [], second.get("changes"))
        self.assertIn(WOODGROVE, self.saved(data_dir, "uv_tools"))


class TestChanges(PipxUvTestCase):
    def test_read_then_not_present(self):
        data_dir = self.data_dir()
        self.collect(
            packages_fake(pipx={HOME_NEW: pipx_home(
                pipx_venv("contoso-cli", "contoso-cli", "2.1.0"))}),
            data_dir=data_dir, now=NOW)

        second = self.collect(packages_fake(), data_dir=data_dir,
                              now=NOW + timedelta(days=1))
        self.assertEqual(self.manager(second, "pipx").get("state"), "not_present",
                         self.manager(second, "pipx"))
        self.assertEqual(self.comparison(second).get("pipx_packages"), "compared",
                         self.comparison(second))
        changes = self.changes_from(second, "pipx_packages")
        self.assertEqual([(c.get("key"), c.get("change")) for c in changes],
                         [(CONTOSO, "removed")], changes)

        third = self.collect(packages_fake(), data_dir=data_dir,
                             now=NOW + timedelta(days=2))
        self.assertEqual(self.changes_from(third, "pipx_packages"), [])
        self.assertEqual(self.changes(third), [])

    def test_pipx_and_uv_changes(self):
        data_dir = self.data_dir()

        def fake(contoso_version, tools):
            entries = [uv_entry(name) for name in tools]
            folders = {
                uv_site_packages("woodgrove-lint"): read_folder(
                    package("woodgrove_lint", "1.4.2")),
                uv_site_packages("contoso-fmt"): read_folder(
                    package("contoso_fmt", "0.5.0")),
            }
            return packages_fake(
                pipx={HOME_NEW: pipx_home(
                    pipx_venv("contoso-cli", "contoso-cli", contoso_version))},
                uv={DEFAULT_UV_FOLDER: uv_folder(*entries)},
                folders=folders)

        first = self.collect(fake("2.1.0", ["woodgrove-lint", "contoso-fmt"]),
                             data_dir=data_dir, now=NOW)
        self.assertEqual(self.changes(first), [])

        second = self.collect(fake("2.2.0", ["contoso-fmt"]),
                              data_dir=data_dir, now=NOW + timedelta(days=1))
        self.assertEqual(self.comparison(second).get("pipx_packages"), "compared",
                         self.comparison(second))
        self.assertEqual(self.comparison(second).get("uv_tools"), "compared",
                         self.comparison(second))
        changes = self.by_key(self.changes(second))
        self.assertEqual(
            {key: (change.get("source"), change.get("change"))
             for key, change in changes.items()},
            {CONTOSO: ("pipx_packages", "changed"),
             WOODGROVE: ("uv_tools", "removed")},
        )
        self.assertEqual(self.field_names(changes[CONTOSO]), ["version"], changes[CONTOSO])
        self.assertEqual(changes[CONTOSO].get("venv"), "contoso-cli", changes[CONTOSO])

        third = self.collect(fake("2.2.0", ["contoso-fmt"]),
                             data_dir=data_dir, now=NOW + timedelta(days=2))
        self.assertEqual(self.changes(third), [])


if __name__ == "__main__":
    unittest.main()

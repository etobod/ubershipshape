"""pip packages of every registered Python in skills/ush-packages/scripts/packages.py
(moved from tests/ush-inventory/test_package_managers.py by plan 061, M1; first written
for plan 029, M1, criteria K1-K7, and plan 042, M1).

Interface these tests assume:

- Job ``python_registrations`` answers rows ``{hive, view, company, tag, install_path,
  sys_version, sys_architecture}``; HKCU rows have ``view`` null. The code deduplicates
  Pythons by the case-folded install path without a trailing backslash and never sends a
  Python under ``\\WindowsApps\\`` (any case) to ``package_folders``.
- Job ``package_folders`` reads its input file ``<out stem>.input.json`` next to
  ``out_path`` (see ``fakes.FakePowerShell``).
- Source ``pip_packages``: key ``pip:<company>/<tag>|<install|user>|<name case-folded>``,
  compared field ``version``; items carry ``python``, ``folder``, ``name``, ``version``,
  ``status``, ``reason`` (and ``key`` in the detail file's ``pip_packages`` list).
- Summary ``managers.pip`` = ``{state, status, pythons: [{python, count, unreadable,
  folders: {install, user}}]}``.

PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.
"""

import json
import unittest
from datetime import timedelta

from .fakes import (
    DEFAULT_NPM_FOLDER,
    NOW,
    FakePowerShell,
    PackagesTestCase,
    failure,
    install_folder,
    note_text,
    npm_package,
    ok,
    package,
    packages_fake,
    read_folder,
    registration,
    unreadable_folder,
    unreadable_package,
    user_folder,
)

ALWAYS_NOTE = "not registered in pep 514"


class PipFakePowerShell(FakePowerShell):
    """``FakePowerShell`` whose ``input_paths`` lists only the pip (``python``) folders.

    The npm folder of the same ``package_folders`` job is left out: in ush-inventory the
    pip fake failed the ``npmrc`` job, so no npm folder was sent; here npm is read too.
    """

    def input_paths(self):
        return [str(folder.get("path")) for folder in self.folder_inputs
                if folder.get("layout") == "python"]


def pip_fake(registrations, folders=None):
    return PipFakePowerShell({"python_registrations": ok(list(registrations))}, folders)


class PipTestCase(PackagesTestCase):
    def pip(self, summary):
        return self.manager(summary, "pip")

    def pythons(self, summary):
        pythons = self.pip(summary).get("pythons")
        self.assertIsInstance(pythons, list, self.pip(summary))
        return {entry.get("python"): entry for entry in pythons}


class TestPip(PipTestCase):
    def test_counts_per_python(self):
        path312 = "C:\\Invented\\Python312\\"
        path311 = "C:\\Invented\\Python311-32\\"
        fake = pip_fake(
            [registration("3.12", path312),
             registration("3.11", path311, view="32", sys_architecture="32bit")],
            {
                install_folder(path312): read_folder(
                    package("requests", "2.31.0"),
                    package("idna", "3.6"),
                    package("PyYAML", "6.0.1"),
                ),
                install_folder(path311): read_folder(),
                user_folder("311", bits32=True): read_folder(package("certifi", "2024.2.2")),
            },
        )
        summary = self.collect(fake)

        self.assertEqual(self.source(summary, "pip_packages").get("status"), "read")
        self.assertEqual(self.pip(summary).get("status"), "read", self.pip(summary))
        pythons = self.pythons(summary)
        self.assertEqual(set(pythons), {"PythonCore/3.12", "PythonCore/3.11"}, pythons)
        py312 = pythons["PythonCore/3.12"]
        self.assertEqual(py312.get("count"), 3, py312)
        self.assertEqual(py312.get("unreadable"), 0, py312)
        self.assertEqual(py312.get("folders"), {"install": "read", "user": "absent"}, py312)
        py311 = pythons["PythonCore/3.11"]
        self.assertEqual(py311.get("count"), 1, py311)
        self.assertEqual(py311.get("unreadable"), 0, py311)
        self.assertEqual(py311.get("folders"), {"install": "read", "user": "read"}, py311)

        items = self.by_key(self.pip_items(summary))
        expected = {
            "pip:PythonCore/3.12|install|requests":
                ("PythonCore/3.12", "install", "requests", "2.31.0"),
            "pip:PythonCore/3.12|install|idna": ("PythonCore/3.12", "install", "idna", "3.6"),
            "pip:PythonCore/3.12|install|pyyaml":
                ("PythonCore/3.12", "install", "PyYAML", "6.0.1"),
            "pip:PythonCore/3.11|user|certifi":
                ("PythonCore/3.11", "user", "certifi", "2024.2.2"),
        }
        self.assertEqual(set(items), set(expected), sorted(map(str, items)))
        for key, (python, folder, name, version) in expected.items():
            item = items[key]
            self.assertEqual(item.get("python"), python, item)
            self.assertEqual(item.get("folder"), folder, item)
            self.assertEqual(item.get("name"), name, item)
            self.assertEqual(item.get("version"), version, item)
            self.assertEqual(item.get("status"), "read", item)
            self.assertIn("reason", item, item)
            self.assertIsNone(item["reason"], item)

    def test_changes_between_runs(self):
        data_dir = self.data_dir()
        path = "C:\\Invented\\Python312"
        regs = [registration("3.12", path)]
        first = {install_folder(path): read_folder(
            package("requests", "2.31.0"), package("idna", "3.6"),
            package("certifi", "2024.2.2"))}
        second = {install_folder(path): read_folder(
            package("requests", "2.32.0"), package("idna", "3.6"))}

        self.collect(pip_fake(regs, first), data_dir=data_dir, now=NOW)
        run2 = self.collect(pip_fake(regs, second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("pip_packages"), "compared",
                         self.comparison(run2))
        changes = self.by_key(self.changes_from(run2, "pip_packages"))
        newer = "pip:PythonCore/3.12|install|requests"
        gone = "pip:PythonCore/3.12|install|certifi"
        self.assertEqual(
            {key: change.get("change") for key, change in changes.items()},
            {newer: "changed", gone: "removed"},
        )
        self.assertEqual(self.field_names(changes[newer]), ["version"], changes[newer])

    def test_python_without_install_path_keeps_baseline(self):
        # M1 code-review fix: a Python whose registration lost its InstallPath is not
        # read, so its packages are kept from the baseline, never reported as removed.
        for case, others in (("only Python", []),
                             ("next to a read Python", ["3.11"])):
            with self.subTest(case=case):
                data_dir = self.data_dir()
                path = "C:\\Invented\\Python312"
                other = "C:\\Invented\\Python311"
                regs = [registration("3.12", path)]
                regs += [registration(tag, other) for tag in others]
                first = {install_folder(path): read_folder(
                    package("requests", "2.31.0"), package("idna", "3.6"))}
                self.collect(pip_fake(regs, first), data_dir=data_dir, now=NOW)

                regs2 = [registration("3.12", None)]
                regs2 += [registration(tag, other) for tag in others]
                run2 = self.collect(pip_fake(regs2, {}), data_dir=data_dir,
                                    now=NOW + timedelta(days=1))

                self.assertEqual(self.changes_from(run2, "pip_packages"), [], run2)
                state = json.loads((data_dir / "state" / "ush-packages.json")
                                   .read_text(encoding="utf-8-sig"))
                saved = state["sources"].get("pip_packages") or {}
                self.assertIn("pip:PythonCore/3.12|install|requests", saved, saved)
                self.assertTrue(self.notes_with(run2, "3.12", "pip_packages"),
                                run2.get("not_checked"))
                # Round 3: its packages stay listed, marked from_baseline.
                carried = self.by_key(self.pip_items(run2))
                self.assertIn("pip:PythonCore/3.12|install|requests", carried, carried)
                for item in carried.values():
                    self.assertIs(item.get("from_baseline"), True, item)

    def test_store_python_and_leftover_registration(self):
        # M1 code-review round 3: the reason never claims that no Python has an
        # InstallPath when a Store Python has one.
        regs = [registration("3.12", "C:\\Invented\\WindowsApps\\PythonSoftwareFoundation"
                             ".Python.3.12_invented\\"),
                registration("2.0", None, company="ContosoPy")]
        summary = self.collect(pip_fake(regs, {}))
        reason = str(self.source(summary, "pip_packages").get("reason") or "")
        self.assertNotIn("no registered Python has an InstallPath", reason, summary)
        self.assertTrue(self.notes_with(summary, "ContosoPy/2.0"), summary.get("not_checked"))

    def test_store_python_note_names_its_source(self):
        # Plan 063, M1 code-review round 1: a skipped Store Python is a partial skip of
        # pip_packages, so its not_checked entry names that source and its Python; runall
        # then keeps its review entries not_checked instead of gone.
        regs = [registration("3.12", "C:\\Invented\\WindowsApps\\PythonSoftwareFoundation"
                             ".Python.3.12_invented\\")]
        summary = self.collect(pip_fake(regs, {}))
        store = self.notes_with(summary, "microsoft store")
        self.assertEqual(len(store), 1, summary.get("not_checked"))
        self.assertEqual(store[0].get("what"),
                         "pip_packages PythonCore/3.12 from the Microsoft Store (WindowsApps)",
                         store)

    def test_store_only_first_run_is_unreadable(self):
        # Final review round 2: a first run with only a Store Python and no baseline
        # reads nothing, so pip is unreadable with pythons null and no item.
        store = ("C:\\Invented\\WindowsApps\\PythonSoftwareFoundation"
                 ".Python.3.12_invented")
        summary = self.collect(pip_fake([registration("3.12", store)], {}),
                               data_dir=self.data_dir(), now=NOW)
        self.assertEqual(self.pip(summary).get("status"), "unreadable", self.pip(summary))
        self.assertIsNone(self.pip(summary).get("pythons"), self.pip(summary))
        self.assertEqual(self.pip_items(summary), [], summary)

    def test_store_python_keeps_baseline(self):
        # Plan 063, M1 code-review round 2: a Python now skipped as a Store install is
        # not read, so its packages are kept from the baseline, never reported removed,
        # and its not_checked entry says why.
        data_dir = self.data_dir()
        path = "C:\\Invented\\Python312"
        first = {install_folder(path): read_folder(package("requests", "2.31.0"))}
        self.collect(pip_fake([registration("3.12", path)], first), data_dir=data_dir, now=NOW)
        store = ("C:\\Invented\\WindowsApps\\PythonSoftwareFoundation"
                 ".Python.3.12_invented")
        run2 = self.collect(pip_fake([registration("3.12", store)], {}), data_dir=data_dir,
                            now=NOW + timedelta(days=1))
        self.assertEqual(self.changes_from(run2, "pip_packages"), [], run2)
        # Final review: nothing was read, so the source is unreadable, never empty.
        self.assertEqual(self.pip(run2).get("status"), "unreadable", self.pip(run2))
        carried = self.by_key(self.pip_items(run2))
        self.assertIn("pip:PythonCore/3.12|install|requests", carried, carried)
        for item in carried.values():
            self.assertIs(item.get("from_baseline"), True, item)
        notes = self.notes_with(run2, "microsoft store")
        self.assertEqual(len(notes), 1, run2.get("not_checked"))
        self.assertIn("windowsapps", str(notes[0].get("reason") or "").casefold(), notes)

    def test_same_python_with_and_without_install_path(self):
        # M1 code-review round 2: a leftover registration of the same company/tag
        # without an InstallPath does not hide the copy that is read.
        data_dir = self.data_dir()
        path = "C:\\Invented\\Python312"
        first = {install_folder(path): read_folder(
            package("requests", "2.31.0"), package("idna", "3.6"))}
        regs = [registration("3.12", path)]
        self.collect(pip_fake(regs, first), data_dir=data_dir, now=NOW)

        regs2 = [registration("3.12", None, hive="HKCU"), registration("3.12", path)]
        second = {install_folder(path): read_folder(
            package("requests", "2.32.0"), package("idna", "3.6"))}
        run2 = self.collect(pip_fake(regs2, second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        changes = self.by_key(self.changes_from(run2, "pip_packages"))
        self.assertEqual({key: change.get("change") for key, change in changes.items()},
                         {"pip:PythonCore/3.12|install|requests": "changed"}, changes)
        self.assertEqual(self.pythons(run2)["PythonCore/3.12"].get("count"), 2, run2)
        # Round 3: the Python read is never also named as not read.
        self.assertEqual(self.notes_with(run2, "3.12", "InstallPath"), [],
                         run2.get("not_checked"))

    def test_only_python_without_install_path_is_not_empty(self):
        # M1 code-review round 2: "could not read" is never shown as "read, nothing
        # there".
        fake = pip_fake([registration("3.12", None)], {})
        summary = self.collect(fake)
        self.assertEqual(self.pip(summary).get("status"), "unreadable", self.pip(summary))
        self.assertEqual(self.pip(summary).get("state"), "unreadable", self.pip(summary))

    def test_store_python_named(self):
        regular = "C:\\Invented\\Python311\\"
        store = ("C:\\Users\\Invented\\AppData\\Local\\Microsoft\\WindowsApps\\"
                 "PythonSoftwareFoundation.Python.3.12_invented0abc\\")
        store_lower = ("c:\\program files\\windowsapps\\"
                       "pythonsoftwarefoundation.python.3.13_invented0abc\\")
        fake = pip_fake(
            [registration("3.11", regular),
             registration("3.12", store, hive="HKCU"),
             registration("3.13", store_lower, hive="HKCU")],
            {install_folder(regular): read_folder(package("idna", "3.6"))},
        )
        summary = self.collect(fake)

        self.assertEqual(set(self.pythons(summary)), {"PythonCore/3.11"},
                         self.pip(summary))
        self.assertEqual(self.pythons(summary)["PythonCore/3.11"].get("count"), 1)
        # Final review round 2: a Store Python next to one that is read keeps it read.
        self.assertEqual(self.pip(summary).get("status"), "read", self.pip(summary))
        for item in self.pip_items(summary):
            self.assertEqual(item.get("python"), "PythonCore/3.11", item)

        for path in fake.input_paths():
            folded = path.casefold()
            self.assertNotIn("windowsapps", folded, fake.input_paths())
            self.assertNotIn("python312", folded, fake.input_paths())
            self.assertNotIn("python313", folded, fake.input_paths())

        for tag in ("3.12", "3.13"):
            notes = self.notes_with(summary, "Microsoft Store", tag)
            self.assertTrue(notes, f"no Store note for {tag}: {summary.get('not_checked')}")

    def test_no_double_count_and_distinct_keys(self):
        hkcu_path = "C:\\Users\\Invented\\AppData\\Local\\Programs\\Python\\Python312"
        hklm_path = "c:\\USERS\\invented\\appdata\\local\\programs\\PYTHON\\python312\\"
        fake = pip_fake(
            [registration("3.12", hkcu_path, hive="HKCU"),
             registration("3.12", hklm_path, hive="HKLM", view="64")],
            {
                install_folder(hkcu_path): read_folder(package("requests", "2.31.0")),
                user_folder("312"): read_folder(package("requests", "2.32.0")),
            },
        )
        summary = self.collect(fake)

        pythons = self.pip(summary).get("pythons")
        self.assertIsInstance(pythons, list, self.pip(summary))
        self.assertEqual([entry.get("python") for entry in pythons], ["PythonCore/3.12"],
                         pythons)
        self.assertEqual(pythons[0].get("count"), 2, pythons)

        install_inputs = [path for path in fake.input_paths()
                          if path.casefold() == install_folder(hkcu_path).casefold()]
        self.assertEqual(len(install_inputs), 1, fake.input_paths())
        self.assertEqual(len(fake.input_paths()), 2, fake.input_paths())

        items = self.by_key(self.pip_items(summary))
        install_key = "pip:PythonCore/3.12|install|requests"
        user_key = "pip:PythonCore/3.12|user|requests"
        self.assertEqual(set(items), {install_key, user_key}, sorted(map(str, items)))
        self.assertEqual(items[install_key].get("folder"), "install", items[install_key])
        self.assertEqual(items[install_key].get("version"), "2.31.0", items[install_key])
        self.assertEqual(items[user_key].get("folder"), "user", items[user_key])
        self.assertEqual(items[user_key].get("version"), "2.32.0", items[user_key])

    def test_unlistable_site_packages(self):
        locked = "C:\\Invented\\Python312"
        empty = "C:\\Invented\\Python311"
        reason = "Access to the path is denied (invented)"
        fake = pip_fake(
            [registration("3.12", locked), registration("3.11", empty)],
            {install_folder(locked): unreadable_folder(reason)},
        )
        summary = self.collect(fake)

        pythons = self.pythons(summary)
        py312 = pythons.get("PythonCore/3.12")
        self.assertIsNotNone(py312, pythons)
        self.assertIn("count", py312, py312)
        self.assertIsNone(py312["count"], py312)
        self.assertEqual(py312.get("folders"), {"install": "unreadable", "user": "absent"},
                         py312)

        notes = self.notes_with(summary, "3.12", "pip_packages")
        self.assertTrue(notes, summary.get("not_checked"))
        self.assertIsInstance(notes[0].get("reason"), str, notes)
        self.assertTrue(notes[0]["reason"].strip(), notes)

        py311 = pythons.get("PythonCore/3.11")
        self.assertIsNotNone(py311, pythons)
        self.assertEqual(py311.get("count"), 0, py311)
        self.assertEqual(py311.get("unreadable"), 0, py311)
        self.assertEqual(py311.get("folders"), {"install": "absent", "user": "absent"}, py311)
        self.assertEqual(self.notes_with(summary, "3.11", "pip_packages"), [],
                         summary.get("not_checked"))

    def test_unreadable_metadata(self):
        path = "C:\\Invented\\Python312"
        reason = "The process cannot access the file (invented)"
        fake = pip_fake(
            [registration("3.12", path)],
            {install_folder(path): read_folder(
                package("requests", "2.31.0"),
                unreadable_package("broken_invented-1.0.dist-info", reason),
                package("idna", "3.6"),
            )},
        )
        summary = self.collect(fake)

        py312 = self.pythons(summary).get("PythonCore/3.12")
        self.assertIsNotNone(py312, self.pip(summary))
        self.assertEqual(py312.get("unreadable"), 1, py312)
        self.assertEqual(py312.get("folders"), {"install": "read", "user": "absent"}, py312)

        items = self.pip_items(summary)
        self.assertEqual(len(items), 3, items)
        unreadable = [item for item in items if item.get("status") == "unreadable"]
        self.assertEqual(len(unreadable), 1, items)
        self.assertEqual(unreadable[0].get("reason"), reason, unreadable)
        self.assertEqual(unreadable[0].get("python"), "PythonCore/3.12", unreadable)
        self.assertEqual(unreadable[0].get("folder"), "install", unreadable)

        read = {item.get("key"): item for item in items if item.get("status") == "read"}
        self.assertEqual(set(read), {"pip:PythonCore/3.12|install|requests",
                                     "pip:PythonCore/3.12|install|idna"}, items)
        self.assertEqual(read["pip:PythonCore/3.12|install|requests"].get("version"),
                         "2.31.0")
        self.assertEqual(read["pip:PythonCore/3.12|install|idna"].get("version"), "3.6")

    def test_no_python(self):
        fake = pip_fake([])
        summary = self.collect(fake)

        self.assertEqual(self.pip(summary),
                         {"state": "read", "status": "empty", "pythons": []})
        self.assertEqual(self.source(summary, "pip_packages").get("status"), "empty")
        self.assertEqual(self.pip_items(summary), [])

        always = [item for item in self.not_checked(summary) if ALWAYS_NOTE in note_text(item)]
        self.assertEqual(len(always), 1, summary.get("not_checked"))
        others = [item for item in self.not_checked(summary)
                  if ALWAYS_NOTE not in note_text(item)
                  and ("pip_packages" in note_text(item) or "python" in note_text(item))]
        self.assertEqual(others, [], summary.get("not_checked"))

    def test_unreadable_metadata_keeps_key(self):
        data_dir = self.data_dir()
        path = "C:\\Invented\\Python312"
        regs = [registration("3.12", path)]
        first = {install_folder(path): read_folder(package("requests", "2.31.0"))}
        second = {install_folder(path): read_folder(unreadable_package(
            "requests-2.31.0.dist-info", "The process cannot access the file (invented)"))}

        self.collect(pip_fake(regs, first), data_dir=data_dir, now=NOW)
        run2 = self.collect(pip_fake(regs, second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("pip_packages"), "compared",
                         self.comparison(run2))
        self.assertEqual(self.changes_from(run2, "pip_packages"), [])
        keys = {item.get("key") for item in self.pip_items(run2)}
        self.assertEqual(keys, {"pip:PythonCore/3.12|install|requests"})

    def test_pep503_name_normalised(self):
        data_dir = self.data_dir()
        path = "C:\\Invented\\Python312"
        regs = [registration("3.12", path)]
        first = {install_folder(path): read_folder(package("typing_extensions", "4.11.0"))}
        second = {install_folder(path): read_folder(package("typing-extensions", "4.12.0"))}

        self.collect(pip_fake(regs, first), data_dir=data_dir, now=NOW)
        run2 = self.collect(pip_fake(regs, second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        changes = self.by_key(self.changes_from(run2, "pip_packages"))
        key = "pip:PythonCore/3.12|install|typing-extensions"
        self.assertEqual({k: c.get("change") for k, c in changes.items()},
                         {key: "changed"})
        self.assertEqual(self.field_names(changes[key]), ["version"], changes[key])
        item = self.by_key(self.pip_items(run2))[key]
        self.assertEqual(item.get("name"), "typing-extensions", item)

    def test_duplicate_entries_highest_version_plain(self):
        path = "C:\\Invented\\Python312"
        regs = [registration("3.12", path)]
        plain = "pip:PythonCore/3.12|install|requests"
        stale = package("requests", "2.31.0")
        fresh = package("requests", "2.32.0")
        for order in ((stale, fresh), (fresh, stale)):
            summary = self.collect(pip_fake(regs, {install_folder(path): read_folder(*order)}))
            items = self.by_key(self.pip_items(summary))
            self.assertEqual(items[plain].get("version"), "2.32.0", items)
            self.assertEqual(
                items[plain + "|requests-2.31.0.dist-info"].get("version"), "2.31.0", items)

        data_dir = self.data_dir()
        self.collect(pip_fake(regs, {install_folder(path): read_folder(fresh, stale)}),
                     data_dir=data_dir, now=NOW)
        run2 = self.collect(
            pip_fake(regs, {install_folder(path): read_folder(
                package("requests", "2.33.0"), stale)}),
            data_dir=data_dir, now=NOW + timedelta(days=1))
        changes = self.by_key(self.changes_from(run2, "pip_packages"))
        self.assertEqual({k: c.get("change") for k, c in changes.items()},
                         {plain: "changed"})
        self.assertEqual(self.field_names(changes[plain]), ["version"], changes[plain])

    def test_free_threaded_user_folder(self):
        fake = pip_fake(
            [registration("3.13", "C:\\Invented\\Python313", sys_version="3.13"),
             registration("3.13t", "C:\\Invented\\Python313t", sys_version="3.13")],
        )
        self.collect(fake)

        inputs = [path.casefold() for path in fake.input_paths()]
        for wanted in (user_folder("313"), user_folder("313t")):
            self.assertEqual(inputs.count(wanted.casefold()), 1, fake.input_paths())

    def test_duplicate_release_candidate_below_final(self):
        path = "C:\\Invented\\Python312"
        regs = [registration("3.12", path)]
        plain = "pip:PythonCore/3.12|install|requests"
        final = package("requests", "2.32.0")
        candidate = package("requests", "2.32.0rc1")
        for order in ((candidate, final), (final, candidate)):
            summary = self.collect(pip_fake(regs, {install_folder(path): read_folder(*order)}))
            items = self.by_key(self.pip_items(summary))
            self.assertEqual(items[plain].get("version"), "2.32.0", items)

    def test_duplicate_current_metadata_locked(self):
        data_dir = self.data_dir()
        path = "C:\\Invented\\Python312"
        regs = [registration("3.12", path)]
        stale = package("requests", "2.31.0")
        first = {install_folder(path): read_folder(package("requests", "2.32.0"), stale)}
        second = {install_folder(path): read_folder(
            unreadable_package("requests-2.32.0.dist-info",
                               "The process cannot access the file (invented)"),
            stale)}

        self.collect(pip_fake(regs, first), data_dir=data_dir, now=NOW)
        run2 = self.collect(pip_fake(regs, second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        self.assertEqual(self.changes_from(run2, "pip_packages"), [])
        items = self.by_key(self.pip_items(run2))
        plain = items["pip:PythonCore/3.12|install|requests"]
        self.assertEqual(plain.get("status"), "unreadable", plain)
        self.assertEqual(plain.get("entry"), "requests-2.32.0.dist-info", plain)

    def test_unknown_python_core_tag_suffix(self):
        path = "C:\\Invented\\Python314Arm"
        fake = pip_fake(
            [registration("3.14-arm64", path, sys_version="3.14",
                          sys_architecture="ARM64")],
            {install_folder(path): read_folder(package("idna", "3.6"))},
        )
        summary = self.collect(fake)

        self.assertEqual(fake.input_paths(), [install_folder(path)], fake.input_paths())
        entry = self.pythons(summary).get("PythonCore/3.14-arm64")
        self.assertIsNotNone(entry, self.pip(summary))
        self.assertEqual(entry.get("folders"), {"install": "read", "user": "skipped"}, entry)
        self.assertEqual(entry.get("count"), 1, entry)
        self.assertTrue(self.notes_with(summary, "3.14-arm64", "user"),
                        summary.get("not_checked"))


# --- npm global packages and the always-present not_checked entries (plan 029, M2) ------
#


# ConvertTo-Json writes a list of one element as an object, not a list; a lone
# registration or package must still be read as one entry (plan 029, loc-qa).
class TestPipSingleElement(PipTestCase):
    def test_single_registration_and_single_package(self):
        path = "C:\\Invented\\Python312"
        fake = packages_fake(
            extra={"python_registrations": ok(registration("3.12", path))},
            folders={install_folder(path): {"status": "read", "reason": None,
                                            "packages": package("requests", "2.31.0")}})
        summary = self.collect(fake)

        pythons = self.pythons(summary)
        self.assertEqual(set(pythons), {"PythonCore/3.12"}, pythons)
        self.assertEqual(pythons["PythonCore/3.12"].get("count"), 1, pythons)
        items = self.by_key(self.pip_items(summary))
        self.assertEqual(set(items), {"pip:PythonCore/3.12|install|requests"},
                         sorted(map(str, items)))
        self.assertEqual(items["pip:PythonCore/3.12|install|requests"].get("version"),
                         "2.31.0")


# Plan 042 M1 (TEST-PLAN (b) "new source" in a diff skill): an unreadable registrations
# job, a first run with no baseline, and a package added between two runs.
class TestPipSourcesDiff(PipTestCase):
    PYTHON_PATH = "C:\\Invented\\DiffPython312"
    REQUESTS_KEY = "pip:PythonCore/3.12|install|requests"
    IDNA_KEY = "pip:PythonCore/3.12|install|idna"

    def saved_sources(self, data_dir):
        state = data_dir / "state" / "ush-packages.json"
        self.assertTrue(state.is_file(), f"{state} was not written")
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        sources = saved.get("sources")
        self.assertIsInstance(sources, dict, sorted(saved))
        return sources

    def test_registrations_job_fails_keeps_baseline(self):
        data_dir = self.data_dir()
        regs = [registration("3.12", self.PYTHON_PATH)]
        folders = {install_folder(self.PYTHON_PATH): read_folder(
            package("requests", "2.31.0"), package("idna", "3.6"))}
        stderr = "Invented registry error: the key HKLM\\Software\\Python could not be opened"

        self.collect(packages_fake(regs, folders), data_dir=data_dir, now=NOW)
        run2 = self.collect(
            packages_fake(folders=folders,
                          extra={"python_registrations": failure(stderr)}),
            data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.pip(run2),
                         {"state": "unreadable", "status": "unreadable", "pythons": None})
        notes = [item for item in self.not_checked(run2)
                 if item.get("what") == "pip_packages"
                 and stderr in str(item.get("reason"))]
        self.assertTrue(notes, run2.get("not_checked"))
        self.assertEqual(self.comparison(run2).get("pip_packages"), "not_read",
                         self.comparison(run2))
        self.assertEqual(self.changes_from(run2, "pip_packages"), [])

        saved_pip = self.saved_sources(data_dir).get("pip_packages")
        self.assertIsInstance(saved_pip, dict, saved_pip)
        self.assertTrue({self.REQUESTS_KEY, self.IDNA_KEY} <= set(saved_pip),
                        sorted(map(str, saved_pip)))

        run3 = self.collect(packages_fake(regs, folders), data_dir=data_dir,
                            now=NOW + timedelta(days=2))
        self.assertEqual(self.comparison(run3).get("pip_packages"), "compared",
                         self.comparison(run3))
        self.assertEqual(self.changes_from(run3, "pip_packages"), [])

    def test_first_run_no_comparison(self):
        regs = [registration("3.12", self.PYTHON_PATH)]
        fake = packages_fake(
            regs,
            {install_folder(self.PYTHON_PATH): read_folder(package("requests", "2.31.0")),
             DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))})
        summary = self.collect(fake, data_dir=self.data_dir(), now=NOW)

        comparison = self.comparison(summary)
        self.assertEqual(comparison.get("pip_packages"), "no_baseline", comparison)
        self.assertEqual(comparison.get("npm_packages"), "no_baseline", comparison)
        self.assertEqual(self.changes_from(summary, "pip_packages"), [])
        self.assertEqual(self.changes_from(summary, "npm_packages"), [])

        self.assertEqual(self.source(summary, "pip_packages").get("status"), "read")
        self.assertEqual(self.source(summary, "npm_packages").get("status"), "read")
        pip_items = self.by_key(self.pip_items(summary))
        self.assertEqual(set(pip_items), {self.REQUESTS_KEY}, sorted(map(str, pip_items)))
        npm_items = self.by_key(self.npm_items(summary))
        self.assertEqual(set(npm_items), {"npm:left-pad"}, sorted(map(str, npm_items)))
        for item in list(pip_items.values()) + list(npm_items.values()):
            self.assertEqual(item.get("status"), "read", item)
            self.assertNotEqual(item.get("from_baseline"), True, item)

    def test_pip_package_added(self):
        data_dir = self.data_dir()
        regs = [registration("3.12", self.PYTHON_PATH)]
        first = {install_folder(self.PYTHON_PATH): read_folder(
            package("requests", "2.31.0"))}
        second = {install_folder(self.PYTHON_PATH): read_folder(
            package("requests", "2.31.0"), package("idna", "3.6"))}

        self.collect(packages_fake(regs, first), data_dir=data_dir, now=NOW)
        run2 = self.collect(packages_fake(regs, second), data_dir=data_dir,
                            now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(run2).get("pip_packages"), "compared",
                         self.comparison(run2))
        changes = self.by_key(self.changes_from(run2, "pip_packages"))
        self.assertEqual({key: change.get("change") for key, change in changes.items()},
                         {self.IDNA_KEY: "added"})


if __name__ == "__main__":
    unittest.main()

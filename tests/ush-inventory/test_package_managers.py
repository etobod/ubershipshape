"""pip packages of every registered Python in skills/ush-inventory/scripts/inventory.py
(plan 029, milestone M1, criteria K1-K7).

Interface these tests assume (fixed before the code exists):

- Job ``python_registrations`` answers rows ``{hive, view, company, tag, install_path,
  sys_version, sys_architecture}``; HKCU rows have ``view`` null. The code deduplicates
  Pythons by the case-folded install path without a trailing backslash and never sends a
  Python under ``\\WindowsApps\\`` (any case) to ``package_folders``.
- Job ``package_folders`` reads its input file ``<out stem>.input.json`` next to
  ``out_path``: ``{"folders": [{"path": <raw path>, "layout": "python"}]}``. Raw paths are
  ``<install_path without trailing backslash>\\Lib\\site-packages`` and
  ``%APPDATA%\\Python\\Python<XY>[-32]\\site-packages``. It answers one row per folder
  ``{path, expanded, status, reason, packages}``.
- Source ``pip_packages``: key ``pip:<company>/<tag>|<install|user>|<name case-folded>``,
  compared field ``version``; items carry ``python``, ``folder``, ``name``, ``version``,
  ``status``, ``reason`` (and ``key`` in the detail file's ``pip_packages`` list).
- Summary ``package_managers.pip`` = ``{status, pythons: [{python, count, unreadable,
  folders: {install, user}}]}``.

PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.
"""

import json
import re
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, FakePowerShell, InventoryTestCase, ok
from .test_budget import BUDGET, budget_summary, slim_autostart_responses, slim_run_key

# An invented %APPDATA% expansion (not a reading from any machine).
APPDATA = "C:\\Users\\Invented\\AppData\\Roaming"

ALWAYS_NOTE = "not registered in pep 514"


def registration(tag, install_path, hive="HKLM", view="64", sys_version=None,
                 sys_architecture="64bit", company="PythonCore"):
    """One PEP 514 registration as the ``python_registrations`` job returns it."""
    if hive == "HKCU":
        view = None
    return {
        "hive": hive,
        "view": view,
        "company": company,
        "tag": tag,
        "install_path": install_path,
        "sys_version": tag if sys_version is None else sys_version,
        "sys_architecture": sys_architecture,
    }


def install_folder(install_path):
    """The raw install ``site-packages`` path the code sends for ``install_path``."""
    return install_path.rstrip("\\") + "\\Lib\\site-packages"


def user_folder(xy, bits32=False):
    """The raw per-user ``site-packages`` path for version digits ``xy``."""
    suffix = "-32" if bits32 else ""
    return f"%APPDATA%\\Python\\Python{xy}{suffix}\\site-packages"


def package(name, version, entry=None):
    """One package entry read from its ``dist-info``."""
    return {
        "entry": entry or f"{name}-{version}.dist-info",
        "name": name,
        "version": version,
        "status": "read",
        "reason": None,
    }


def unreadable_package(entry, reason):
    """One package entry whose ``METADATA`` could not be read."""
    return {"entry": entry, "name": None, "version": None, "status": "unreadable",
            "reason": reason}


def read_folder(*packages):
    return {"status": "read", "reason": None, "packages": list(packages)}


def unreadable_folder(reason):
    return {"status": "unreadable", "reason": reason, "packages": None}


def expand(raw):
    text = str(raw)
    marker = "%appdata%"
    index = text.casefold().find(marker)
    if index < 0:
        return text
    return text[:index] + APPDATA + text[index + len(marker):]


def package_folders_answer(folders, specs):
    """One row per input folder; a folder not in ``specs`` is ``absent``."""
    rows = []
    for folder in folders:
        raw = folder.get("path")
        spec = specs.get(str(raw).casefold())
        if spec is None:
            spec = {"status": "absent", "reason": None, "packages": []}
        rows.append({
            "path": raw,
            "expanded": expand(raw),
            "status": spec["status"],
            "reason": spec["reason"],
            "packages": spec["packages"],
        })
    return rows


class PipFakePowerShell(FakePowerShell):
    """``FakePowerShell`` that answers ``package_folders`` from its input file.

    ``folders`` maps a raw folder path (matched case-insensitively) to a folder spec
    built with ``read_folder`` or ``unreadable_folder``. Every input folder seen is kept in
    ``folder_inputs``.
    """

    def __init__(self, responses=None, folders=None):
        super().__init__(responses)
        self.specs = {str(path).casefold(): spec for path, spec in (folders or {}).items()}
        self.folder_inputs = []

    def __call__(self, job, script, out_path):
        if job != "package_folders" or job in self.responses:
            return super().__call__(job, script, out_path)
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        input_path = out_path.with_name(out_path.name[:-len(".json")] + ".input.json")
        data = json.loads(input_path.read_text(encoding="utf-8-sig"))
        folders = data.get("folders") or []
        self.folder_inputs.extend(folders)
        rows = package_folders_answer(folders, self.specs)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rows), encoding="utf-8-sig")
        return 0, ""

    def input_paths(self):
        return [str(folder.get("path")) for folder in self.folder_inputs]


def pip_fake(registrations, folders=None):
    return PipFakePowerShell({"python_registrations": ok(registrations)}, folders)


def note_text(item):
    return (str(item.get("what")) + " " + str(item.get("reason"))).casefold()


class PipTestCase(InventoryTestCase):
    def pip(self, summary):
        managers = summary.get("package_managers")
        self.assertIsInstance(managers, dict, sorted(summary))
        pip = managers.get("pip")
        self.assertIsInstance(pip, dict, managers)
        return pip

    def pythons(self, summary):
        pythons = self.pip(summary).get("pythons")
        self.assertIsInstance(pythons, list, self.pip(summary))
        return {entry.get("python"): entry for entry in pythons}

    def pip_items(self, summary):
        items = self.detail(summary).get("pip_packages")
        self.assertIsInstance(items, list, f"detail pip_packages: {items!r}")
        return items

    def changes_from(self, summary, source):
        return [c for c in self.changes(summary) if c.get("source") == source]

    def field_names(self, change):
        fields = change.get("fields")
        if isinstance(fields, dict):
            return sorted(fields)
        if isinstance(fields, list):
            return sorted(str(f) for f in fields)
        self.fail(f"change has no fields: {change}")

    def notes_with(self, summary, *words):
        return [item for item in self.not_checked(summary)
                if all(word.casefold() in note_text(item) for word in words)]


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

        self.assertEqual(self.pip(summary), {"status": "empty", "pythons": []})
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
# Interface these tests assume (fixed before the code exists):
#
# - Job ``npmrc`` (read-only, no input) reads ``%USERPROFILE%\.npmrc`` and answers
#   ``{"status": "read"|"absent"|"unreadable", "lines": [str]|null, "reason": str|null}``.
#   The first line ``prefix=<value>`` (spaces around ``=`` allowed) gives the prefix; with
#   no such line, or no file, the prefix is ``%APPDATA%\npm``. An unreadable ``.npmrc``
#   makes npm ``unreadable`` (count null, a not_checked entry naming npm).
# - Job ``package_folders`` (same input file as M1) gets ``{"path": "<raw prefix>\\
#   node_modules", "layout": "npm"}``; package ``entry`` is ``left-pad`` or
#   ``@contoso/tool``. ``absent`` means npm is not present (status ``empty``, count 0);
#   ``unreadable`` gives npm ``unreadable`` with count null.
# - Source ``npm_packages``: key ``npm:<name case-folded>``, compared field ``version``,
#   items carry ``name``, ``version``, ``status``, ``reason``, ``folder`` (and ``key`` in
#   the detail file's ``npm_packages`` list).
# - Summary ``package_managers.npm`` = ``{status, prefix_from: "npmrc"|"default", count,
#   unreadable}``.
# - ``SOURCES`` ends with ``pip_packages`` and ``npm_packages``.

DEFAULT_NPM_FOLDER = "%APPDATA%\\npm\\node_modules"
NPMRC_ABSENT = ok({"status": "absent", "lines": None, "reason": None})

PEP514_NOTE = "not registered in pep 514"
OTHER_MANAGERS = ("choco", "scoop", "cargo")

# K6: the package count of the over-budget run. 100 changes with short names may fit in
# the 35000-character budget, so more packages with long names are used (see the report).
BUDGET_PACKAGES = 400
BUDGET_AUTOSTART = 5


def npmrc_read(*lines):
    return ok({"status": "read", "lines": list(lines), "reason": None})


def npmrc_unreadable(reason):
    return ok({"status": "unreadable", "lines": None, "reason": reason})


def npm_package(name, version):
    """One package read from ``node_modules\\<name>\\package.json``."""
    return {"entry": name, "name": name, "version": version, "status": "read",
            "reason": None}


class NpmFakePowerShell(PipFakePowerShell):
    """``PipFakePowerShell`` that also answers the ``npmrc`` job.

    ``npmrc`` is the job's response (``npmrc_read``, ``npmrc_unreadable`` or
    ``NPMRC_ABSENT``, the default). npm folders are answered by ``package_folders``
    like the pip ones: a folder not in ``folders`` is ``absent``.
    """

    def __init__(self, responses=None, folders=None, npmrc=None):
        responses = dict(responses or {})
        responses.setdefault("npmrc", NPMRC_ABSENT if npmrc is None else npmrc)
        super().__init__(responses, folders)

    def npm_inputs(self):
        return [folder for folder in self.folder_inputs if folder.get("layout") == "npm"]


def npm_fake(folders=None, npmrc=None, registrations=(), extra=None):
    responses = {"python_registrations": ok(list(registrations))}
    responses.update(extra or {})
    return NpmFakePowerShell(responses, folders, npmrc)


def source_names(sources):
    """The names in ``SOURCES``: plain names, dicts with ``name`` or tuples/lists."""
    if isinstance(sources, dict):
        return [str(name) for name in sources]
    names = []
    for entry in sources:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict):
            names.append(str(entry.get("name")))
        else:
            names.append(str(entry[0]))
    return names


class TestNpm(PipTestCase):
    def setUp(self):
        # Plan 029 M2 review round 2: NPM_CONFIG_PREFIX is read; never from the real environment.
        patcher = mock.patch.object(self.inventory, "ENVIRON", {}, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def npm(self, summary):
        managers = summary.get("package_managers")
        self.assertIsInstance(managers, dict, sorted(summary))
        npm = managers.get("npm")
        self.assertIsInstance(npm, dict, managers)
        return npm

    def npm_items(self, summary):
        items = self.detail(summary).get("npm_packages")
        self.assertIsInstance(items, list, f"detail npm_packages: {items!r}")
        return items

    def test_global_packages(self):
        fake = npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            npm_package("left-pad", "1.3.0"),
            npm_package("JSONStream", "1.3.5"),
            npm_package("@contoso/tool", "2.1.0"),
        )})
        summary = self.collect(fake)

        self.assertEqual(fake.npm_inputs(), [{"path": DEFAULT_NPM_FOLDER, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("prefix_from"), "default", npm)
        self.assertEqual(npm.get("count"), 3, npm)
        self.assertEqual(npm.get("unreadable"), 0, npm)
        self.assertEqual(self.source(summary, "npm_packages").get("status"), "read")

        items = self.by_key(self.npm_items(summary))
        expected = {
            "npm:left-pad": ("left-pad", "1.3.0"),
            "npm:jsonstream": ("JSONStream", "1.3.5"),
            "npm:@contoso/tool": ("@contoso/tool", "2.1.0"),
        }
        self.assertEqual(set(items), set(expected), sorted(map(str, items)))
        for key, (name, version) in expected.items():
            item = items[key]
            self.assertEqual(item.get("name"), name, item)
            self.assertEqual(item.get("version"), version, item)
            self.assertEqual(item.get("status"), "read", item)
            self.assertIn("reason", item, item)
            self.assertIsNone(item["reason"], item)
            self.assertIn("folder", item, item)

    def test_prefix_from_npmrc(self):
        custom = "D:\\Invented\\npm-global\\node_modules"
        fake = npm_fake(
            {
                custom: read_folder(npm_package("@contoso/tool", "2.1.0")),
                DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0")),
                "E:\\Invented\\second-prefix\\node_modules":
                    read_folder(npm_package("rimraf", "5.0.5")),
            },
            npmrc=npmrc_read(
                "; invented user config",
                "registry=https://registry.example.invalid/",
                "prefix = D:\\Invented\\npm-global",
                "prefix=E:\\Invented\\second-prefix",
            ),
        )
        summary = self.collect(fake)

        self.assertEqual(fake.npm_inputs(), [{"path": custom, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("prefix_from"), "npmrc", npm)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("count"), 1, npm)
        items = self.by_key(self.npm_items(summary))
        self.assertEqual(set(items), {"npm:@contoso/tool"}, sorted(map(str, items)))
        self.assertEqual(items["npm:@contoso/tool"].get("version"), "2.1.0")

    def test_absent_versus_unreadable(self):
        with self.subTest(case="node_modules missing: npm not present"):
            summary = self.collect(npm_fake())
            npm = self.npm(summary)
            self.assertEqual(npm.get("status"), "empty", npm)
            self.assertEqual(npm.get("count"), 0, npm)
            self.assertEqual(npm.get("unreadable"), 0, npm)
            self.assertEqual(self.source(summary, "npm_packages").get("status"), "empty")
            self.assertEqual(self.npm_items(summary), [])
            # Plan 029 M2 code-review (judge: fix): an absent default folder names the prefixes not searched.
            notes = self.notes_with(summary, "npm")
            self.assertEqual(len(notes), 1, summary.get("not_checked"))
            self.assertIn("node.exe", note_text(notes[0]), notes)

        with self.subTest(case="node_modules cannot be listed"):
            reason = "Access to the path is denied (invented)"
            summary = self.collect(npm_fake({DEFAULT_NPM_FOLDER: unreadable_folder(reason)}))
            npm = self.npm(summary)
            self.assertEqual(npm.get("status"), "unreadable", npm)
            self.assertIn("count", npm, npm)
            self.assertIsNone(npm["count"], npm)
            notes = self.notes_with(summary, "npm")
            self.assertTrue(notes, summary.get("not_checked"))
            self.assertIsInstance(notes[0].get("reason"), str, notes)
            self.assertTrue(notes[0]["reason"].strip(), notes)

        with self.subTest(case=".npmrc cannot be read"):
            reason = "The process cannot access the file (invented)"
            summary = self.collect(npm_fake(
                {DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))},
                npmrc=npmrc_unreadable(reason)))
            npm = self.npm(summary)
            self.assertEqual(npm.get("status"), "unreadable", npm)
            self.assertIn("count", npm, npm)
            self.assertIsNone(npm["count"], npm)
            notes = self.notes_with(summary, "npm")
            self.assertTrue(notes, summary.get("not_checked"))
            self.assertIsInstance(notes[0].get("reason"), str, notes)
            self.assertTrue(notes[0]["reason"].strip(), notes)

    def test_not_checked_entries(self):
        path = "C:\\Invented\\Python312"
        runs = {
            "no Python, no npm": npm_fake(),
            "a Python and npm": npm_fake(
                {install_folder(path): read_folder(package("idna", "3.6")),
                 DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))},
                registrations=[registration("3.12", path)]),
        }
        for case, fake in runs.items():
            with self.subTest(case=case):
                summary = self.collect(fake)
                notes = self.not_checked(summary)

                winget = [item for item in notes if "winget" in note_text(item)]
                self.assertEqual(len(winget), 1, notes)
                self.assertIn("online", note_text(winget[0]), winget)

                pep514 = [item for item in notes if PEP514_NOTE in note_text(item)]
                self.assertEqual(len(pep514), 1, notes)

                others = [item for item in notes
                          if all(name in note_text(item) for name in OTHER_MANAGERS)
                          and re.search(r"\bgo\b", note_text(item))]
                self.assertEqual(len(others), 1, notes)
                self.assertIn("not searched", note_text(others[0]), others)

                for item in winget + pep514 + others:
                    self.assertIsInstance(item.get("reason"), str, item)
                    self.assertTrue(item["reason"].strip(), item)

    def test_package_changes_cut_first(self):
        names = source_names(self.inventory.SOURCES)
        self.assertEqual(set(names[-2:]), {"pip_packages", "npm_packages"}, names)

        def packages(version):
            return read_folder(*(
                npm_package(f"@contoso/invented-budget-package-with-a-long-example-name-{i:04d}",
                            version)
                for i in range(BUDGET_PACKAGES)))

        data_dir = self.data_dir()
        first = npm_fake({DEFAULT_NPM_FOLDER: packages("1.0.0")},
                         extra=slim_autostart_responses(0, 0))
        second = npm_fake({DEFAULT_NPM_FOLDER: packages("2.0.0")},
                          extra=slim_autostart_responses(BUDGET_AUTOSTART, 0))
        code, _stdout, stderr = self.run_main(data_dir, first, now=NOW)
        self.assertEqual(code, 0, stderr[:300])
        code, stdout, stderr = self.run_main(data_dir, second, now=NOW + timedelta(days=1))
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = self.parse(stdout)

        detail_changes = self.detail(summary).get("changes")
        self.assertIsInstance(detail_changes, list, type(detail_changes))
        npm_changes = [c for c in detail_changes if c.get("source") == "npm_packages"]
        self.assertEqual(len(npm_changes), BUDGET_PACKAGES)
        for change in npm_changes:
            self.assertEqual(change.get("change"), "changed", change)

        cut = summary.get("truncated_changes")
        self.assertIsInstance(cut, int, cut)
        self.assertGreater(cut, 0)

        kept = self.changes(summary)
        kept_keys = {c.get("key") for c in kept if isinstance(c, dict)}
        autostart_keys = {slim_run_key(i) for i in range(BUDGET_AUTOSTART)}
        self.assertTrue(autostart_keys <= kept_keys, sorted(autostart_keys - kept_keys))

        dropped = [c for c in detail_changes if c.get("key") not in kept_keys]
        self.assertEqual(len(dropped), cut, [c.get("key") for c in dropped][:5])
        self.assertEqual({c.get("source") for c in dropped}, {"npm_packages"},
                         [(c.get("source"), c.get("key")) for c in dropped][:5])

    # Review round 1 (plan 029 M2): regressions.
    def test_unlistable_scope_keeps_baseline(self):
        data_dir = self.data_dir()
        self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            npm_package("@contoso/tool", "1.2.0"), npm_package("left-pad", "1.3.0"))}),
            data_dir=data_dir, now=NOW)
        scope_row = {"entry": "@contoso", "name": None, "version": None,
                     "status": "unreadable", "reason": "Access to the path is denied (invented)"}
        run2 = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            scope_row, npm_package("left-pad", "1.3.0"))}),
            data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.changes_from(run2, "npm_packages"), [])
        items = self.by_key(self.npm_items(run2))
        self.assertNotIn("npm:@contoso", items, sorted(map(str, items)))
        self.assertIn("npm:@contoso/tool", items, sorted(map(str, items)))
        self.assertIs(items["npm:@contoso/tool"].get("from_baseline"), True,
                      items["npm:@contoso/tool"])
        self.assertTrue(self.notes_with(run2, "@contoso"), run2.get("not_checked"))

    def test_unreadable_or_versionless_package_json(self):
        cases = {
            "unreadable answer": {"entry": "left-pad", "name": None, "version": None,
                                  "status": "unreadable",
                                  "reason": "package.json is empty or not a JSON object"},
            "read without name or version": {"entry": "left-pad", "name": None,
                                             "version": None, "status": "read",
                                             "reason": None},
            "read without version": {"entry": "left-pad", "name": "left-pad",
                                     "version": None, "status": "read", "reason": None},
        }
        for case, row in cases.items():
            with self.subTest(case=case):
                data_dir = self.data_dir()
                self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
                    npm_package("left-pad", "1.3.0"))}), data_dir=data_dir, now=NOW)
                run2 = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(row)}),
                                    data_dir=data_dir, now=NOW + timedelta(days=1))
                self.assertEqual(self.changes_from(run2, "npm_packages"), [])
                items = self.by_key(self.npm_items(run2))
                self.assertEqual(set(items), {"npm:left-pad"}, sorted(map(str, items)))
                item = items["npm:left-pad"]
                self.assertEqual(item.get("status"), "unreadable", item)
                self.assertTrue(str(item.get("reason") or "").strip(), item)
                self.assertEqual(self.npm(run2).get("unreadable"), 1, self.npm(run2))

    def test_absent_default_names_other_prefixes(self):
        summary = self.collect(npm_fake())
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "empty", npm)
        self.assertEqual(npm.get("prefix_from"), "default", npm)
        notes = self.notes_with(summary, "node.exe")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn("node.exe", note_text(notes[0]), notes)
        self.assertTrue(str(notes[0].get("reason") or "").strip(), notes)

        with self.subTest(case="prefix from .npmrc, folder absent"):
            summary = self.collect(npm_fake(npmrc=npmrc_read("prefix=D:\\Invented\\npm")))
            self.assertEqual(self.npm(summary).get("status"), "empty")
            self.assertEqual(len(self.notes_with(summary, "node.exe")), 1,
                             summary.get("not_checked"))

        with self.subTest(case="npm read: no entry"):
            summary = self.collect(npm_fake(
                {DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))}))
            self.assertEqual(self.notes_with(summary, "node.exe"), [],
                             summary.get("not_checked"))

    def test_npmrc_non_dict_row(self):
        summary = self.collect(npm_fake(
            {DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))},
            npmrc=ok(["x"])))
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "unreadable", npm)
        self.assertIsNone(npm.get("count"), npm)
        notes = self.notes_with(summary, "npm")
        self.assertTrue(notes and str(notes[0].get("reason") or "").strip(),
                        summary.get("not_checked"))

    # Review round 2 (plan 029 M2): regressions.
    def test_prefix_from_environment(self):
        env_folder = "D:\\invented\\npm\\node_modules"
        folders = {env_folder: read_folder(npm_package("rimraf", "5.0.5")),
                   DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))}
        npmrc = npmrc_read("prefix=E:\\Invented\\from-npmrc")
        with mock.patch.object(self.inventory, "ENVIRON",
                               {"npm_config_prefix": "D:\\invented\\npm"}):
            fake = npm_fake(folders, npmrc=npmrc)
            summary = self.collect(fake)
        self.assertEqual(fake.npm_inputs(), [{"path": env_folder, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("prefix_from"), "NPM_CONFIG_PREFIX", npm)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("count"), 1, npm)

        with self.subTest(case="a %VAR% value is passed raw, expanded like .npmrc"):
            with mock.patch.object(self.inventory, "ENVIRON",
                                   {"NPM_CONFIG_PREFIX": "%APPDATA%\\npm-env\\"}):
                fake = npm_fake(folders)
                self.collect(fake)
            self.assertEqual(fake.npm_inputs(),
                             [{"path": "%APPDATA%\\npm-env\\node_modules", "layout": "npm"}])

        with self.subTest(case="a blank value does not count"):
            with mock.patch.object(self.inventory, "ENVIRON", {"NPM_CONFIG_PREFIX": "  "}):
                fake = npm_fake(folders)
                summary = self.collect(fake)
            self.assertEqual(fake.npm_inputs(), [{"path": DEFAULT_NPM_FOLDER, "layout": "npm"}])
            self.assertEqual(self.npm(summary).get("prefix_from"), "default")

    def test_empty_node_modules_names_other_prefixes(self):
        summary = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder()}))
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "empty", npm)
        self.assertEqual(npm.get("count"), 0, npm)
        notes = self.notes_with(summary, "another prefix")
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn("node.exe", note_text(notes[0]), notes)
        self.assertNotIn("npm_config_prefix", note_text(notes[0]), notes)

    def test_only_unlistable_scopes(self):
        data_dir = self.data_dir()
        self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(
            npm_package("@contoso/tool", "1.2.0"), npm_package("@contoso/cli", "0.4.0"))}),
            data_dir=data_dir, now=NOW)
        scope_row = {"entry": "@contoso", "name": None, "version": None,
                     "status": "unreadable", "reason": "Access to the path is denied (invented)"}
        run2 = self.collect(npm_fake({DEFAULT_NPM_FOLDER: read_folder(scope_row)}),
                            data_dir=data_dir, now=NOW + timedelta(days=1))

        npm = self.npm(run2)
        self.assertEqual(npm.get("status"), "unreadable", npm)
        self.assertIn("count", npm, npm)
        self.assertIsNone(npm["count"], npm)
        self.assertIn("unreadable", npm, npm)
        self.assertIsNone(npm["unreadable"], npm)
        self.assertTrue(self.notes_with(run2, "@contoso"), run2.get("not_checked"))
        self.assertEqual(self.changes_from(run2, "npm_packages"), [])
        items = self.by_key(self.npm_items(run2))
        self.assertEqual(set(items), {"npm:@contoso/tool", "npm:@contoso/cli"},
                         sorted(map(str, items)))
        for item in items.values():
            self.assertIs(item.get("from_baseline"), True, item)



# Final review round 1 (plan 029): package changes are cut before any other list.
class TestPackageChangesCutBeforeOtherLists(InventoryTestCase):
    def test_package_changes_cut_before_programs(self):
        summary = budget_summary({"programs": 40, "changes": 5})
        summary["changes"] += [
            {"id": f"n{i}", "name": f"@contoso/invented-package-{i:04d}",
             "source": "npm_packages", "change": "changed"} for i in range(200)]
        # The budget is the size of the summary with only the package changes cut.
        target = budget_summary({"programs": 40, "changes": 5})
        target["truncated_changes"] = 200
        target["change_counts"] = {"run_keys": {"added": 5, "removed": 0, "changed": 0},
                                   "npm_packages": {"added": 0, "removed": 0,
                                                    "changed": 200}}
        budget = len(self.inventory.dump(target)) + 50
        with mock.patch.object(self.inventory, "SUMMARY_MAX_CHARS", budget):
            self.inventory.fit_budget(summary)

        self.assertEqual(len(summary["programs"]), 40)
        self.assertEqual(summary["truncated"], 0)
        self.assertEqual([c["source"] for c in summary["changes"][:5]], ["run_keys"] * 5)
        kept_packages = len(summary["changes"]) - 5
        self.assertEqual(summary["truncated_changes"], 200 - kept_packages)
        self.assertGreater(summary["truncated_changes"], 0)


# Added by loc-qa (plan 029, TEST-PLAN (b) "new source"): ConvertTo-Json writes a list of
# one element as an object, not a list; a lone registration, package or .npmrc line
# must still be read as one entry.
class TestPackageManagersSingleElement(PipTestCase):
    # The helpers of TestNpm, without running its tests a second time.
    setUp = TestNpm.setUp
    npm = TestNpm.npm
    npm_items = TestNpm.npm_items

    def single_folder(self, package_row):
        return {"status": "read", "reason": None, "packages": package_row}

    def test_single_registration_and_single_package(self):
        path = "C:\\Invented\\Python312"
        fake = PipFakePowerShell(
            {"python_registrations": ok(registration("3.12", path)),
             "npmrc": NPMRC_ABSENT},
            {install_folder(path): self.single_folder(package("requests", "2.31.0"))})
        summary = self.collect(fake)

        pythons = self.pythons(summary)
        self.assertEqual(set(pythons), {"PythonCore/3.12"}, pythons)
        self.assertEqual(pythons["PythonCore/3.12"].get("count"), 1, pythons)
        items = self.by_key(self.pip_items(summary))
        self.assertEqual(set(items), {"pip:PythonCore/3.12|install|requests"},
                         sorted(map(str, items)))
        self.assertEqual(items["pip:PythonCore/3.12|install|requests"].get("version"),
                         "2.31.0")

    def test_single_npm_package_and_single_npmrc_line(self):
        custom = "D:\\Invented\\npm-global\\node_modules"
        npmrc = ok({"status": "read", "lines": "prefix=D:\\Invented\\npm-global",
                    "reason": None})
        fake = npm_fake({custom: self.single_folder(npm_package("left-pad", "1.3.0"))},
                        npmrc=npmrc)
        summary = self.collect(fake)

        self.assertEqual(fake.npm_inputs(), [{"path": custom, "layout": "npm"}],
                         fake.folder_inputs)
        npm = self.npm(summary)
        self.assertEqual(npm.get("status"), "read", npm)
        self.assertEqual(npm.get("prefix_from"), "npmrc", npm)
        self.assertEqual(npm.get("count"), 1, npm)
        items = self.by_key(self.npm_items(summary))
        self.assertEqual(set(items), {"npm:left-pad"}, sorted(map(str, items)))
        self.assertEqual(items["npm:left-pad"].get("version"), "1.3.0")


if __name__ == "__main__":
    unittest.main()

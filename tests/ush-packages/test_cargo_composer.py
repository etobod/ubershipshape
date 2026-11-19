"""cargo crates and global Composer packages read offline from disk (plan 086, M1, K1-K5).

Interface these tests assume (fixed before the code exists):

- Folders and files are read in Python through the module-level ``DISK`` object
  (``exists``, ``list_dir``, ``read_text``); locations are expanded from the module's
  ``ENVIRON``. The tests set ``USERPROFILE``, ``APPDATA``, ``CARGO_INSTALL_ROOT``,
  ``CARGO_HOME`` and ``COMPOSER_HOME`` to invented temporary folders, and replace
  ``DISK.read_text`` to raise for one chosen path, calling the original for every other
  path. No ``cargo``, ``composer`` or ``php`` command runs and PowerShell never starts.
- cargo: the root is ``CARGO_INSTALL_ROOT`` (non-blank), else ``CARGO_HOME``, else the raw
  ``%USERPROFILE%\\.cargo``; the record is ``<root>\\.crates.toml`` (each key of ``v1`` is
  ``<name> <version> (<source>)``). Source ``cargo_packages``; detail list
  ``cargo_packages`` (as for every earlier reader, the detail list is named after the
  source); key ``cargo:<name case-folded>``; fields ``name``, ``version``,
  ``source_kind``.
- composer: the home is ``COMPOSER_HOME`` (non-blank), else the raw
  ``%APPDATA%\\Composer``; each ``require`` key holding ``/`` of ``<home>\\composer.json``
  is a global package, its version from ``<home>\\vendor\\composer\\installed.json``
  (Composer 2: ``{"packages": [...]}``, Composer 1: a bare list). Source
  ``composer_packages``; detail list ``composer_packages``; key
  ``composer:<name case-folded>``.
- ``managers.cargo`` and ``managers.composer`` are ``{state, status, folder_from, count,
  unreadable}``, or ``{state: "not_present", looked_in: [...]}`` when the root is absent.

Every folder and file is written by hand in a temporary folder; every crate, package,
version, URL and path is invented.
"""

import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, PackagesTestCase, note_text, packages_fake

CARGO = "cargo"
COMPOSER = "composer"
CARGO_SOURCE = "cargo_packages"
COMPOSER_SOURCE = "composer_packages"
CARGO_PREFIX = "cargo:"
COMPOSER_PREFIX = "composer:"
RAW_CARGO_ROOT = "%USERPROFILE%\\.cargo"
RAW_COMPOSER_HOME = "%APPDATA%\\Composer"
NOT_READ_YET = "not read yet"
CARGO_CONFIG_NOTE = "install.root"
VENDOR_DIR_NOTE = "vendor-dir"
DENIED = "Access to the path is denied (invented)"

CONTOSO_KEY = "contoso-cli 1.2.3 (registry+https://invented.example/index)"
FABRIKAM_KEY = ("fabrikam-tool 0.4.0+build.7 "
                "(git+https://invented.example/tool?branch=main#abc123)")
BROKEN_KEY = "broken-key"

COMPOSER_REQUIRE = {"php": ">=8.1", "ext-json": "*", "contoso/cli": "^1.2",
                    "fabrikam/tool": "^3.0", "litware/gone": "^2.0"}
# left/pad is a dependency of a global package, never an item of its own.
INSTALLED = {"contoso/cli": "v1.2.3", "fabrikam/tool": "3.0.1", "left/pad": "1.3.0"}


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def toml_string(text):
    return json.dumps(text)


def crates_toml(*keys):
    """The text of an invented ``.crates.toml``: one ``v1`` entry per key."""
    lines = ["[v1]"]
    for key in keys:
        binary = key.split(" ")[0] + ".exe"
        lines.append(f"{toml_string(key)} = [{toml_string(binary)}]")
    return "\n".join(lines) + "\n"


def crate_key(name, version, source="registry+https://invented.example/index"):
    return f"{name} {version} ({source})"


def write_cargo_root(root, text=None):
    """An invented cargo install root; ``text`` None leaves ``.crates.toml`` out."""
    root = Path(root)
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / "contoso-cli.exe").write_bytes(b"MZinvented")
    if text is not None:
        (root / ".crates.toml").write_text(text, encoding="utf-8")
    return root


def installed_entry(name, version):
    return {
        "name": name,
        "version": version,
        "version_normalized": version.lstrip("v") + ".0",
        "type": "library",
        "description": "An invented package.",
        "install-path": "../" + name,
    }


def installed_text(versions, shape=2):
    """The text of an invented ``installed.json`` (Composer 2 object or Composer 1 list)."""
    entries = [installed_entry(name, version) for name, version in versions.items()]
    if shape == 1:
        return json.dumps(entries, indent=4)
    return json.dumps({"packages": entries, "dev": True, "dev-package-names": []}, indent=4)


def write_composer_home(home, require=None, installed=None, shape=2,
                        composer_text=None, installed_raw=None):
    """An invented Composer home.

    ``require`` None and ``composer_text`` None leave ``composer.json`` out; ``installed``
    maps names to versions (None and ``installed_raw`` None leave ``installed.json``
    out)."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    if composer_text is None and require is not None:
        composer_text = json.dumps({"require": dict(require)}, indent=4)
    if composer_text is not None:
        (home / "composer.json").write_text(composer_text, encoding="utf-8")
    if installed_raw is None and installed is not None:
        installed_raw = installed_text(installed, shape)
    if installed_raw is not None:
        meta = home / "vendor" / "composer"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "installed.json").write_text(installed_raw, encoding="utf-8")
    return home


def installed_path(home):
    return Path(home) / "vendor" / "composer" / "installed.json"


class CargoComposerTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def user_profile(self):
        """An invented %USERPROFILE% that exists, without a .cargo folder."""
        folder = self.temp_folder() / "Profile"
        folder.mkdir(parents=True)
        return folder

    def app_data(self):
        """An invented %APPDATA% that exists, without a Composer folder."""
        folder = self.temp_folder() / "Roaming"
        folder.mkdir(parents=True)
        return folder

    def collect_with(self, environ, data_dir=None, now=NOW):
        with mock.patch.object(self.packages, "ENVIRON", dict(environ)):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def items(self, summary, source):
        items = self.detail(summary).get(source)
        self.assertIsInstance(items, list, f"detail {source}: {items!r}")
        return self.by_key(items)

    def changes_with(self, summary, prefix):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith(prefix)]

    def change_kinds(self, summary, prefix):
        return sorted((str(change.get("key")), str(change.get("change")))
                      for change in self.changes_with(summary, prefix))

    def notes_about(self, summary, word):
        return [item for item in self.not_checked(summary)
                if word.casefold() in note_text(item)]

    def reason_named(self, summary, source, reason):
        """``reason`` appears in a ``not_checked`` entry or in the source's own reason."""
        texts = [note_text(item) for item in self.not_checked(summary)]
        texts.append(str(self.source(summary, source).get("reason")).casefold())
        return any(reason.casefold() in text for text in texts)

    def failing_read_text(self, failing_path, error):
        original = self.packages.DISK.read_text

        def read_text(path, *args, **kwargs):
            if same_path(path, failing_path):
                raise error
            return original(path, *args, **kwargs)

        return mock.patch.object(self.packages.DISK, "read_text", read_text)

    def assert_empty(self, summary, manager_name, source, folder_from=None):
        manager = self.manager(summary, manager_name)
        self.assertNotEqual(manager.get("state"), "not_present", manager)
        self.assertNotEqual(manager.get("state"), "unreadable", manager)
        self.assertEqual(manager.get("status"), "empty", manager)
        self.assertEqual(manager.get("count"), 0, manager)
        if folder_from is not None:
            self.assertEqual(manager.get("folder_from"), folder_from, manager)
        self.assertEqual(self.items(summary, source), {})

    def assert_carried(self, summary, manager_name, source, prefix, expected):
        """The source is unreadable, ``count`` null, ``expected`` (key -> version) kept
        ``from_baseline`` with no ``removed`` change, never ``not_present``."""
        manager = self.manager(summary, manager_name)
        self.assertEqual(manager.get("state"), "unreadable", manager)
        self.assertIn("count", manager, manager)
        self.assertIsNone(manager["count"], manager)
        self.assertEqual(self.source(summary, source).get("status"), "unreadable",
                         self.source(summary, source))
        items = self.items(summary, source)
        for key, version in expected.items():
            self.assertIn(key, items, sorted(map(str, items)))
            self.assertIs(items[key].get("from_baseline"), True, items[key])
            self.assertEqual(items[key].get("version"), version, items[key])
        removed = [change for change in self.changes_with(summary, prefix)
                   if change.get("change") == "removed"]
        self.assertEqual(removed, [], summary.get("changes"))


class TestCargo(CargoComposerTestCase):
    def test_absent_is_not_present(self):
        profile = self.user_profile()
        app_data = self.app_data()
        summary = self.collect_with({"USERPROFILE": str(profile),
                                     "APPDATA": str(app_data)})

        for name, raw in ((CARGO, RAW_CARGO_ROOT), (COMPOSER, RAW_COMPOSER_HOME)):
            manager = self.manager(summary, name)
            self.assertEqual(manager.get("state"), "not_present", manager)
            self.assertEqual(sorted(manager), ["looked_in", "state"], manager)
            looked_in = manager.get("looked_in")
            self.assertIsInstance(looked_in, list, manager)
            self.assertEqual([str(path).casefold() for path in looked_in],
                             [raw.casefold()], manager)

        for word in (CARGO, COMPOSER):
            for item in self.notes_about(summary, word):
                text = note_text(item)
                self.assertNotIn(NOT_READ_YET, text, item)
                self.assertNotIn("unreadable", text, item)
        for source in (CARGO_SOURCE, COMPOSER_SOURCE):
            self.assertNotEqual(self.source(summary, source).get("status"), "unreadable")
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith((CARGO_PREFIX, COMPOSER_PREFIX))
                 or item.get("manager") in (CARGO, COMPOSER)]
        self.assertEqual(found, [], found)

    def test_crates_from_toml(self):
        contoso, fabrikam, broken = (CARGO_PREFIX + "contoso-cli",
                                     CARGO_PREFIX + "fabrikam-tool",
                                     CARGO_PREFIX + BROKEN_KEY)
        root = write_cargo_root(self.temp_folder() / "invented-cargo",
                                crates_toml(CONTOSO_KEY, FABRIKAM_KEY, BROKEN_KEY))
        summary = self.collect_with({"CARGO_HOME": str(root),
                                     "USERPROFILE": str(self.user_profile())})

        items = self.items(summary, CARGO_SOURCE)
        self.assertEqual(set(items), {contoso, fabrikam, broken}, sorted(map(str, items)))
        self.assertEqual(items[contoso].get("name"), "contoso-cli", items[contoso])
        self.assertEqual(items[contoso].get("version"), "1.2.3", items[contoso])
        self.assertEqual(items[contoso].get("source_kind"), "registry", items[contoso])
        self.assertEqual(items[fabrikam].get("name"), "fabrikam-tool", items[fabrikam])
        self.assertEqual(items[fabrikam].get("version"), "0.4.0+build.7", items[fabrikam])
        self.assertEqual(items[fabrikam].get("source_kind"), "git", items[fabrikam])
        self.assertEqual(items[broken].get("status"), "unreadable", items[broken])

        for item in items.values():
            text = json.dumps(item).casefold()
            self.assertNotIn("https://", text, item)
            self.assertNotIn("invented.example", text, item)
        summary_text = json.dumps(
            [item for item in self.package_list(summary)
             if str(item.get("key")).startswith(CARGO_PREFIX)
             or item.get("manager") == CARGO]).casefold()
        self.assertNotIn("invented.example", summary_text)

        cargo = self.manager(summary, CARGO)
        self.assertEqual(cargo.get("state"), "read", cargo)
        self.assertEqual(cargo.get("unreadable"), 1, cargo)
        self.assertEqual(cargo.get("folder_from"), "CARGO_HOME", cargo)
        self.assertEqual(len(self.notes_about(summary, CARGO_CONFIG_NOTE)), 1,
                         summary.get("not_checked"))

        with self.subTest(case="CARGO_INSTALL_ROOT wins over CARGO_HOME"):
            # A decoy under CARGO_HOME: if it were read, northwind-decoy would appear.
            decoy = write_cargo_root(self.temp_folder() / "cargo-home",
                                     crates_toml(crate_key("northwind-decoy", "0.1.0")))
            install_root = write_cargo_root(self.temp_folder() / "cargo-install-root",
                                            crates_toml(CONTOSO_KEY))
            summary = self.collect_with({"CARGO_INSTALL_ROOT": str(install_root),
                                         "CARGO_HOME": str(decoy),
                                         "USERPROFILE": str(self.user_profile())})

            self.assertEqual(set(self.items(summary, CARGO_SOURCE)), {contoso})
            cargo = self.manager(summary, CARGO)
            self.assertEqual(cargo.get("folder_from"), "CARGO_INSTALL_ROOT", cargo)

        with self.subTest(case="neither variable: the default under USERPROFILE"):
            profile = self.user_profile()
            write_cargo_root(profile / ".cargo", crates_toml(CONTOSO_KEY))
            summary = self.collect_with({"USERPROFILE": str(profile)})

            items = self.items(summary, CARGO_SOURCE)
            self.assertEqual(set(items), {contoso}, sorted(map(str, items)))
            self.assertEqual(items[contoso].get("version"), "1.2.3", items[contoso])
            cargo = self.manager(summary, CARGO)
            self.assertEqual(cargo.get("state"), "read", cargo)
            self.assertEqual(cargo.get("folder_from"), "default", cargo)

        with self.subTest(case="a root without .crates.toml is empty"):
            root = write_cargo_root(self.temp_folder() / "cargo-no-record")
            summary = self.collect_with({"CARGO_HOME": str(root)})
            self.assert_empty(summary, CARGO, CARGO_SOURCE)

        with self.subTest(case="an unsplittable key keeps no URL or path"):
            # Fixes 086 M1 code-review: the whole key was the name when its first word
            # was empty, so a path install's URL went into the name and the key.
            odd = " contoso-cli 1.0 (path+file:///C:/Invented/src/contoso)"
            root = write_cargo_root(self.temp_folder() / "cargo-odd-key", crates_toml(odd))
            summary = self.collect_with({"CARGO_HOME": str(root)})

            items = self.items(summary, CARGO_SOURCE)
            self.assertEqual(len(items), 1, items)
            self.assertEqual(self.manager(summary, CARGO).get("unreadable"), 1)
            text = json.dumps([items, self.package_list(summary),
                               summary.get("not_checked")]).casefold()
            self.assertNotIn("file:", text)
            self.assertNotIn("invented/src", text)

        with self.subTest(case="a 0-byte .crates.toml is empty"):
            root = write_cargo_root(self.temp_folder() / "cargo-zero-bytes", "")
            self.assertEqual((root / ".crates.toml").stat().st_size, 0)
            summary = self.collect_with({"CARGO_HOME": str(root)})
            self.assert_empty(summary, CARGO, CARGO_SOURCE)

    def test_unreadable(self):
        contoso, fabrikam = CARGO_PREFIX + "contoso-cli", CARGO_PREFIX + "fabrikam-tool"
        baseline = {contoso: "1.2.3", fabrikam: "0.4.0+build.7"}

        def baseline_run():
            root = write_cargo_root(self.temp_folder() / "cargo-home",
                                    crates_toml(CONTOSO_KEY, FABRIKAM_KEY))
            environ = {"CARGO_HOME": str(root)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, CARGO_SOURCE)), set(baseline))
            return root, environ, data_dir

        with self.subTest(case=".crates.toml is not TOML"):
            root, environ, data_dir = baseline_run()
            (root / ".crates.toml").write_text(
                '[v1\n"contoso-cli 1.2.3 (registry+https://invented.example/index)" = [\n',
                encoding="utf-8")
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

            self.assert_carried(second, CARGO, CARGO_SOURCE, CARGO_PREFIX, baseline)
            self.assertTrue(self.source(second, CARGO_SOURCE).get("reason"),
                            self.source(second, CARGO_SOURCE))

        with self.subTest(case=".crates.toml cannot be read"):
            root, environ, data_dir = baseline_run()
            with self.failing_read_text(root / ".crates.toml", PermissionError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

            self.assert_carried(second, CARGO, CARGO_SOURCE, CARGO_PREFIX, baseline)
            self.assertTrue(self.reason_named(second, CARGO_SOURCE, DENIED),
                            second.get("not_checked"))

        with self.subTest(case="v1 is a list"):
            root, environ, data_dir = baseline_run()
            (root / ".crates.toml").write_text(
                f"v1 = [{toml_string(CONTOSO_KEY)}, {toml_string(FABRIKAM_KEY)}]\n",
                encoding="utf-8")
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

            self.assert_carried(second, CARGO, CARGO_SOURCE, CARGO_PREFIX, baseline)
            self.assertTrue(self.source(second, CARGO_SOURCE).get("reason"),
                            self.source(second, CARGO_SOURCE))


class TestComposer(CargoComposerTestCase):
    def assert_require_items(self, summary):
        contoso = COMPOSER_PREFIX + "contoso/cli"
        fabrikam = COMPOSER_PREFIX + "fabrikam/tool"
        gone = COMPOSER_PREFIX + "litware/gone"
        items = self.items(summary, COMPOSER_SOURCE)
        self.assertEqual(set(items), {contoso, fabrikam, gone}, sorted(map(str, items)))
        self.assertEqual(items[contoso].get("name"), "contoso/cli", items[contoso])
        self.assertEqual(items[contoso].get("version"), "v1.2.3", items[contoso])
        self.assertEqual(items[fabrikam].get("name"), "fabrikam/tool", items[fabrikam])
        self.assertEqual(items[fabrikam].get("version"), "3.0.1", items[fabrikam])
        self.assertEqual(items[gone].get("status"), "unreadable", items[gone])
        stray = [key for key in map(str, items)
                 if key.casefold() in (COMPOSER_PREFIX + "php",
                                       COMPOSER_PREFIX + "ext-json",
                                       COMPOSER_PREFIX + "left/pad")]
        self.assertEqual(stray, [], sorted(map(str, items)))

        composer = self.manager(summary, COMPOSER)
        self.assertEqual(composer.get("state"), "read", composer)
        self.assertEqual(composer.get("unreadable"), 1, composer)
        self.assertTrue(self.notes_about(summary, "litware/gone"),
                        summary.get("not_checked"))
        self.assertEqual(len(self.notes_about(summary, VENDOR_DIR_NOTE)), 1,
                         summary.get("not_checked"))

    def test_globals_from_require(self):
        home = write_composer_home(self.temp_folder() / "invented-composer",
                                   COMPOSER_REQUIRE, INSTALLED, shape=2)
        summary = self.collect_with({"COMPOSER_HOME": str(home),
                                     "APPDATA": str(self.app_data())})
        self.assert_require_items(summary)

        with self.subTest(case="Composer 1 installed.json (a bare list)"):
            home = write_composer_home(self.temp_folder() / "invented-composer-1",
                                       COMPOSER_REQUIRE, INSTALLED, shape=1)
            summary = self.collect_with({"COMPOSER_HOME": str(home),
                                         "APPDATA": str(self.app_data())})
            self.assert_require_items(summary)

        with self.subTest(case="an installed.json entry without a version"):
            # Fixes 086 M1 code-review: an entry present without a version was named
            # as missing from installed.json.
            entries = [installed_entry("contoso/cli", "v1.2.3"),
                       {"name": "fabrikam/tool", "type": "library"}]
            home = write_composer_home(
                self.temp_folder() / "invented-composer-no-version",
                {"contoso/cli": "^1.2", "fabrikam/tool": "^3.0"},
                installed_raw=json.dumps({"packages": entries}))
            summary = self.collect_with({"COMPOSER_HOME": str(home)})

            items = self.items(summary, COMPOSER_SOURCE)
            fabrikam = items[COMPOSER_PREFIX + "fabrikam/tool"]
            self.assertEqual(fabrikam.get("status"), "unreadable", fabrikam)
            notes = self.notes_about(summary, "fabrikam/tool")
            self.assertEqual(len(notes), 1, summary.get("not_checked"))
            self.assertIn("no version", note_text(notes[0]), notes)
            self.assertNotIn("is not in", note_text(notes[0]), notes)

        with self.subTest(case="the default home without composer.json is empty"):
            app_data = self.app_data()
            (app_data / "Composer").mkdir()
            summary = self.collect_with({"APPDATA": str(app_data)})
            self.assert_empty(summary, COMPOSER, COMPOSER_SOURCE, folder_from="default")

    def test_unreadable_and_changes(self):
        contoso = COMPOSER_PREFIX + "contoso/cli"
        fabrikam = COMPOSER_PREFIX + "fabrikam/tool"
        baseline = {contoso: "v1.2.3", fabrikam: "3.0.1"}
        require = {"php": ">=8.1", "contoso/cli": "^1.2", "fabrikam/tool": "^3.0"}
        installed = {"contoso/cli": "v1.2.3", "fabrikam/tool": "3.0.1"}

        def baseline_run():
            home = write_composer_home(self.temp_folder() / "composer-home",
                                       require, installed)
            environ = {"COMPOSER_HOME": str(home)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first, COMPOSER_SOURCE)), set(baseline))
            return home, environ, data_dir

        for file_label, path_of in (("composer.json", lambda h: h / "composer.json"),
                                    ("installed.json", installed_path)):
            with self.subTest(case=f"{file_label} is not JSON"):
                home, environ, data_dir = baseline_run()
                path_of(home).write_text('{"require": {"contoso/cli": ', encoding="utf-8")
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

                self.assert_carried(second, COMPOSER, COMPOSER_SOURCE, COMPOSER_PREFIX,
                                    baseline)
                self.assertTrue(self.source(second, COMPOSER_SOURCE).get("reason"),
                                self.source(second, COMPOSER_SOURCE))

            with self.subTest(case=f"{file_label} cannot be read"):
                home, environ, data_dir = baseline_run()
                with self.failing_read_text(path_of(home), PermissionError(DENIED)):
                    second = self.collect_with(environ, data_dir=data_dir,
                                               now=NOW + timedelta(days=1))

                self.assert_carried(second, COMPOSER, COMPOSER_SOURCE, COMPOSER_PREFIX,
                                    baseline)
                self.assertTrue(self.reason_named(second, COMPOSER_SOURCE, DENIED),
                                second.get("not_checked"))

        with self.subTest(case="changes of cargo and composer"):
            cargo_root = write_cargo_root(
                self.temp_folder() / "cargo-home",
                crates_toml(crate_key("contoso-cli", "1.2.3"),
                            crate_key("fabrikam-tool", "0.4.0")))
            composer_home = write_composer_home(self.temp_folder() / "composer-home",
                                                require, installed)
            environ = {"CARGO_HOME": str(cargo_root),
                       "COMPOSER_HOME": str(composer_home)}
            data_dir = self.data_dir()

            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(self.changes_with(first, CARGO_PREFIX), [])
            self.assertEqual(self.changes_with(first, COMPOSER_PREFIX), [])

            # A raised version, a removed and an added package in each manager.
            write_cargo_root(cargo_root,
                             crates_toml(crate_key("contoso-cli", "1.3.0"),
                                         crate_key("litware-gen", "2.0.0")))
            write_composer_home(
                composer_home,
                {"php": ">=8.1", "contoso/cli": "^1.3", "litware/new": "^2.0"},
                {"contoso/cli": "v1.3.0", "litware/new": "2.0.1"})
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

            self.assertEqual(self.change_kinds(second, CARGO_PREFIX),
                             sorted([(CARGO_PREFIX + "contoso-cli", "changed"),
                                     (CARGO_PREFIX + "fabrikam-tool", "removed"),
                                     (CARGO_PREFIX + "litware-gen", "added")]),
                             second.get("changes"))
            self.assertEqual(self.change_kinds(second, COMPOSER_PREFIX),
                             sorted([(contoso, "changed"),
                                     (fabrikam, "removed"),
                                     (COMPOSER_PREFIX + "litware/new", "added")]),
                             second.get("changes"))

            third = self.collect_with(environ, data_dir=data_dir,
                                      now=NOW + timedelta(days=2))
            self.assertEqual(self.changes_with(third, CARGO_PREFIX), [])
            self.assertEqual(self.changes_with(third, COMPOSER_PREFIX), [])


if __name__ == "__main__":
    unittest.main()

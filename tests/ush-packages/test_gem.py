"""Ruby gems read offline from every gem folder (plan 086, M2, K1-K5).

Interface these tests assume (fixed before the code exists):

- Folders and files are read in Python through the module-level ``DISK`` object
  (``exists``, ``list_dir(path)``: names, ``OSError`` on failure; ``read_text``);
  locations are expanded from the module's ``ENVIRON``. The tests set ``USERPROFILE``,
  ``GEM_HOME``, ``GEM_PATH`` and ``XDG_DATA_HOME`` to invented temporary folders and
  replace ``DISK.list_dir`` to raise for chosen paths, calling the original for every
  other path. No ``gem`` or ``ruby`` command runs and PowerShell never starts.
- The Ruby installs named in the Windows uninstall keys come from one read-only ``DISK``
  method, named here ``DISK.ruby_install_locations()`` (``RUBY_METHOD`` below; the plan
  does not name it): it returns the ``InstallLocation`` strings of every uninstall key
  whose ``DisplayName`` starts with ``Ruby `` and raises ``OSError`` when the keys cannot
  be read. Every test here replaces it, so no test reads the registry.
- Gem folders (parts) and their labels: ``GEM_HOME``; ``GEM_PATH-<n>`` per ``;`` entry of
  ``GEM_PATH``; ``user-<abi>`` per subfolder of ``%USERPROFILE%\\.gem\\ruby``; ``xdg-<abi>``
  per subfolder of ``<XDG_DATA_HOME, else %USERPROFILE%\\.local\\share>\\gem\\ruby``;
  ``ruby-<abi>`` per subfolder of ``<InstallLocation>\\lib\\ruby\\gems``. A parent folder
  that exists but cannot be listed is itself an ``unreadable`` part labelled ``user``,
  ``xdg`` or ``ruby``.
- A gem is a ``<part>\\specifications\\*.gemspec`` file (not ``specifications\\default``):
  name and version from its ``# stub: <name> <version> <platform> ...`` line, else from
  ``s.name = "..."`` / ``s.version = "..."``.
- Source ``gem_packages``; detail list ``gem_packages`` (named after the source, as for
  every earlier reader); key ``gem:<label>|<name case-folded>``; fields ``name``,
  ``version``, ``versions_found``, ``gem_dir`` (the label). A change carries ``gem_dir``.
- ``managers.gem`` is ``{state, status, parts: [{source, status, count, reason}], count,
  unreadable}`` with ``source`` the label, or ``{state: "not_present", looked_in: [...]}``.

The gemspec fixtures have the shape RubyGems writes into ``specifications`` (the stub
header, then ``Gem::Specification.new``). Every folder and file is written by hand in a
temporary folder; every gem name, version and path is invented.
"""

import os
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, PackagesTestCase, note_text, packages_fake

MANAGER = "gem"
SOURCE = "gem_packages"
PREFIX = "gem:"
# The plan does not name the new registry method; this is the name these tests fix.
RUBY_METHOD = "ruby_install_locations"
NOT_READ_YET = "not read yet"
DEFAULT_GEMS_NOTE = "default gems"
REGISTRY_NOTE = "ruby installs in the uninstall keys"
DENIED = "Access to the path is denied (invented)"
REGISTRY_ERROR = "Invented registry error: the Uninstall key could not be opened"
ABI = "3.3.0"


def key(label, name):
    return f"{PREFIX}{label}|{name.casefold()}"


def same_path(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right)))


def stub_gemspec(name, version, platform="ruby"):
    """A gemspec as RubyGems writes it into ``specifications``, with the stub line."""
    return "\n".join([
        "# -*- encoding: utf-8 -*-",
        f"# stub: {name} {version} {platform} lib",
        "",
        "Gem::Specification.new do |s|",
        f'  s.name = "{name}".freeze',
        f'  s.version = "{version}".freeze',
        "",
        ('  s.required_rubygems_version = Gem::Requirement.new(">= 0".freeze) '
         "if s.respond_to? :required_rubygems_version="),
        '  s.require_paths = ["lib".freeze]',
        '  s.authors = ["Invented Author".freeze]',
        '  s.summary = "An invented gem.".freeze',
        "end",
        "",
    ])


def plain_gemspec(name, version, platform):
    """A gemspec without the stub line: only ``s.name`` / ``s.version`` give the gem."""
    return "\n".join([
        "# -*- encoding: utf-8 -*-",
        "",
        "Gem::Specification.new do |s|",
        f'  s.name = "{name}"',
        f'  s.version = "{version}"',
        f'  s.platform = "{platform}"',
        ('  s.required_rubygems_version = Gem::Requirement.new(">= 0") '
         "if s.respond_to? :required_rubygems_version="),
        '  s.authors = ["Invented Author"]',
        '  s.summary = "An invented gem."',
        "end",
        "",
    ])


def nameless_gemspec():
    """A gemspec with neither a stub line nor ``s.name`` / ``s.version``."""
    return ("# -*- encoding: utf-8 -*-\n"
            "\n"
            "Gem::Specification.new do |s|\n"
            '  s.authors = ["Invented Author"]\n'
            '  s.summary = "An invented gem."\n'
            "end\n")


def add_gem(part, file_stem, text):
    """Write ``<part>\\specifications\\<file_stem>.gemspec``."""
    folder = Path(part) / "specifications"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{file_stem}.gemspec"
    path.write_text(text, encoding="utf-8")
    return path


def add_stub(part, name, version):
    return add_gem(part, f"{name}-{version}", stub_gemspec(name, version))


def ruby_gems(ruby):
    """``<InstallLocation>\\lib\\ruby\\gems``, created."""
    folder = Path(ruby) / "lib" / "ruby" / "gems"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class GemTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def profile(self):
        """An invented %USERPROFILE% that exists, without .gem or .local."""
        folder = self.temp_folder() / "Invented"
        folder.mkdir(parents=True)
        return folder

    def collect_with(self, environ, rubies=(), data_dir=None, now=NOW):
        """Collect with ``ENVIRON`` = ``environ`` and the registry method returning
        ``rubies`` (raising it when it is an exception)."""
        def install_locations():
            if isinstance(rubies, BaseException):
                raise rubies
            return [str(path) for path in rubies]

        # No create=True: a method of another name fails here, before main runs.
        with mock.patch.object(self.packages, "ENVIRON", dict(environ)), \
                mock.patch.object(self.packages.DISK, RUBY_METHOD, install_locations):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def failing_list_dir(self, failing_paths, error):
        original = self.packages.DISK.list_dir

        def list_dir(path):
            if any(same_path(path, failing) for failing in failing_paths):
                raise error
            return original(path)

        return mock.patch.object(self.packages.DISK, "list_dir", list_dir)

    def items(self, summary):
        items = self.detail(summary).get(SOURCE)
        self.assertIsInstance(items, list, f"detail {SOURCE}: {items!r}")
        return self.by_key(items)

    def gem(self, summary):
        return self.manager(summary, MANAGER)

    def parts(self, summary):
        """``managers.gem.parts`` by label."""
        parts = self.gem(summary).get("parts")
        self.assertIsInstance(parts, list, self.gem(summary))
        by_label = {}
        for part in parts:
            self.assertIsInstance(part, dict, parts)
            self.assertNotIn(part.get("source"), by_label, f"duplicate label in {parts}")
            by_label[part.get("source")] = part
        return by_label

    def gem_changes(self, summary):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith(PREFIX)]

    def change_kinds(self, summary):
        return sorted((str(change.get("key")), str(change.get("change")))
                      for change in self.gem_changes(summary))

    def notes_about(self, summary, word):
        return [item for item in self.not_checked(summary)
                if word.casefold() in note_text(item)]

    def assert_kept(self, summary, expected):
        """``expected`` (key -> version) kept ``from_baseline``, no ``removed`` change
        for them."""
        items = self.items(summary)
        for item_key, version in expected.items():
            self.assertIn(item_key, items, sorted(map(str, items)))
            self.assertIs(items[item_key].get("from_baseline"), True, items[item_key])
            self.assertEqual(items[item_key].get("version"), version, items[item_key])
        removed = [change for change in self.gem_changes(summary)
                   if change.get("change") == "removed" and change.get("key") in expected]
        self.assertEqual(removed, [], summary.get("changes"))

    def assert_count_null(self, summary):
        gem = self.gem(summary)
        self.assertIn("count", gem, gem)
        self.assertIsNone(gem["count"], gem)


class TestGem(GemTestCase):
    # K1
    def test_absent_is_not_present(self):
        summary = self.collect_with({"USERPROFILE": str(self.profile())}, rubies=())

        gem = self.gem(summary)
        self.assertEqual(gem.get("state"), "not_present", gem)
        self.assertEqual(sorted(gem), ["looked_in", "state"], gem)
        looked_in = gem.get("looked_in")
        self.assertIsInstance(looked_in, list, gem)
        folded = [str(path).casefold() for path in looked_in]
        self.assertTrue(any(".gem" in path for path in folded), gem)
        self.assertTrue(any(".local" in path for path in folded), gem)

        for item in self.not_checked(summary):
            text = note_text(item)
            # "gem" as a word (gem_packages too), never inside "management".
            if re.search(r"(?<![a-z0-9])gem(?![a-z0-9])", text):
                self.assertNotIn(NOT_READ_YET, text, item)
        self.assertNotEqual(self.source(summary, SOURCE).get("status"), "unreadable")
        found = [item for item in self.package_list(summary)
                 if str(item.get("key")).startswith(PREFIX)
                 or item.get("manager") == MANAGER]
        self.assertEqual(found, [], found)

    # K2
    def test_gems_of_ruby_folder(self):
        ruby = self.temp_folder() / "Ruby33-x64"
        part = ruby_gems(ruby) / ABI
        add_stub(part, "contoso", "1.2.3")
        add_stub(part, "contoso", "1.10.0")
        add_gem(part, "fabrikam-2.0.0-x64-mingw-ucrt",
                plain_gemspec("fabrikam", "2.0.0", "x64-mingw-ucrt"))
        add_stub(part, "fabrikam", "2.0.0")
        add_gem(part, "litware-0.1", nameless_gemspec())
        # A default gem ships with Ruby: specifications\default, never an item.
        default = part / "specifications" / "default"
        default.mkdir(parents=True)
        (default / "bigdecimal-3.1.5.gemspec").write_text(
            stub_gemspec("bigdecimal", "3.1.5"), encoding="utf-8")

        summary = self.collect_with({"USERPROFILE": str(self.profile())}, rubies=[ruby])

        label = f"ruby-{ABI}"
        contoso, fabrikam = key(label, "contoso"), key(label, "fabrikam")
        litware = key(label, "litware-0.1")
        items = self.items(summary)
        self.assertEqual(set(items), {contoso, fabrikam, litware}, sorted(map(str, items)))

        self.assertEqual(items[contoso].get("name"), "contoso", items[contoso])
        self.assertEqual(items[contoso].get("version"), "1.10.0", items[contoso])
        self.assertEqual(items[contoso].get("versions_found"), 2, items[contoso])
        self.assertEqual(items[fabrikam].get("name"), "fabrikam", items[fabrikam])
        self.assertEqual(items[fabrikam].get("version"), "2.0.0", items[fabrikam])
        self.assertEqual(items[fabrikam].get("versions_found"), 1, items[fabrikam])
        self.assertEqual(items[litware].get("status"), "unreadable", items[litware])
        for item in items.values():
            self.assertEqual(item.get("gem_dir"), label, item)

        bigdecimal = [item for item in [*items.values(), *self.package_list(summary)]
                      if "bigdecimal" in str(item.get("key")).casefold()
                      or "bigdecimal" in str(item.get("name")).casefold()]
        self.assertEqual(bigdecimal, [], bigdecimal)
        self.assertEqual(len(self.notes_about(summary, DEFAULT_GEMS_NOTE)), 1,
                         summary.get("not_checked"))
        self.assertTrue(self.notes_about(summary, "litware-0.1"),
                        summary.get("not_checked"))

        gem = self.gem(summary)
        self.assertEqual(gem.get("state"), "read", gem)
        self.assertEqual(gem.get("unreadable"), 1, gem)
        parts = self.parts(summary)
        self.assertIn(label, parts, parts)
        self.assertEqual(parts[label].get("status"), "read", parts[label])

    # K3
    def test_parts_and_versions(self):
        with self.subTest(case="a prerelease sorts below its release; GEM_HOME part"):
            home = self.temp_folder() / "gem-home"
            add_stub(home, "contoso", "1.0.0.pre")
            add_stub(home, "contoso", "1.0.0")
            summary = self.collect_with({"USERPROFILE": str(self.profile()),
                                         "GEM_HOME": str(home)})

            items = self.items(summary)
            contoso = key("GEM_HOME", "contoso")
            self.assertEqual(set(items), {contoso}, sorted(map(str, items)))
            self.assertEqual(items[contoso].get("version"), "1.0.0", items[contoso])
            self.assertEqual(items[contoso].get("gem_dir"), "GEM_HOME", items[contoso])
            self.assertEqual(set(self.parts(summary)), {"GEM_HOME"}, self.gem(summary))

        with self.subTest(case="two GEM_PATH entries"):
            first = self.temp_folder() / "gem-path-one"
            second = self.temp_folder() / "gem-path-two"
            add_stub(first, "contoso", "1.2.3")
            add_stub(second, "fabrikam", "2.0.0")
            summary = self.collect_with({"USERPROFILE": str(self.profile()),
                                         "GEM_PATH": f"{first};{second}"})

            self.assertEqual(set(self.parts(summary)), {"GEM_PATH-1", "GEM_PATH-2"},
                             self.gem(summary))
            self.assertEqual(set(self.items(summary)),
                             {key("GEM_PATH-1", "contoso"), key("GEM_PATH-2", "fabrikam")},
                             sorted(map(str, self.items(summary))))

        with self.subTest(case="the user and the XDG gem folders"):
            profile = self.profile()
            xdg = self.temp_folder() / "xdg-data"
            add_stub(profile / ".gem" / "ruby" / ABI, "contoso", "1.2.3")
            add_stub(xdg / "gem" / "ruby" / ABI, "fabrikam", "2.0.0")
            summary = self.collect_with({"USERPROFILE": str(profile),
                                         "XDG_DATA_HOME": str(xdg)})

            self.assertEqual(set(self.parts(summary)), {f"user-{ABI}", f"xdg-{ABI}"},
                             self.gem(summary))
            items = self.items(summary)
            self.assertEqual(set(items),
                             {key(f"user-{ABI}", "contoso"), key(f"xdg-{ABI}", "fabrikam")},
                             sorted(map(str, items)))

        with self.subTest(case="the XDG gem folder alone keeps its label"):
            xdg = self.temp_folder() / "xdg-data"
            add_stub(xdg / "gem" / "ruby" / ABI, "fabrikam", "2.0.0")
            summary = self.collect_with({"USERPROFILE": str(self.profile()),
                                         "XDG_DATA_HOME": str(xdg)})

            self.assertEqual(set(self.parts(summary)), {f"xdg-{ABI}"}, self.gem(summary))
            self.assertEqual(set(self.items(summary)), {key(f"xdg-{ABI}", "fabrikam")})

        with self.subTest(case="GEM_HOME equal to the Ruby gem folder is one part"):
            ruby = self.temp_folder() / "Ruby33-x64"
            part = ruby_gems(ruby) / ABI
            add_stub(part, "contoso", "1.2.3")
            summary = self.collect_with({"USERPROFILE": str(self.profile()),
                                         "GEM_HOME": str(part)}, rubies=[ruby])

            parts = self.parts(summary)
            self.assertEqual(len(parts), 1, parts)
            contoso = [item for item in self.items(summary).values()
                       if item.get("name") == "contoso"]
            self.assertEqual(len(contoso), 1, contoso)

    # K4
    def test_partly_read_and_changes(self):
        def two_parts():
            home = self.temp_folder() / "gem-home"
            other = self.temp_folder() / "gem-path"
            add_stub(home, "contoso", "1.0.0")
            add_stub(other, "fabrikam", "2.0.0")
            environ = {"USERPROFILE": str(self.profile()), "GEM_HOME": str(home),
                       "GEM_PATH": str(other)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first)),
                             {key("GEM_HOME", "contoso"), key("GEM_PATH-1", "fabrikam")},
                             sorted(map(str, self.items(first))))
            self.assertEqual(self.gem_changes(first), [])
            return home, other, environ, data_dir

        home, other, environ, data_dir = two_parts()
        (home / "specifications" / "contoso-1.0.0.gemspec").unlink()
        add_stub(home, "contoso", "1.1.0")
        with self.failing_list_dir([other / "specifications"], PermissionError(DENIED)):
            second = self.collect_with(environ, data_dir=data_dir,
                                       now=NOW + timedelta(days=1))

        gem = self.gem(second)
        self.assertEqual(gem.get("state"), "read", gem)
        self.assertEqual(self.source(second, SOURCE).get("status"), "read",
                         self.source(second, SOURCE))
        self.assert_count_null(second)
        self.assert_kept(second, {key("GEM_PATH-1", "fabrikam"): "2.0.0"})
        changes = self.gem_changes(second)
        self.assertEqual([(c.get("key"), c.get("change")) for c in changes],
                         [(key("GEM_HOME", "contoso"), "changed")], changes)
        self.assertEqual(changes[0].get("source"), SOURCE, changes[0])
        self.assertEqual(changes[0].get("gem_dir"), "GEM_HOME", changes[0])

        with self.subTest(case="both parts cannot be listed"):
            home, other, environ, data_dir = two_parts()
            with self.failing_list_dir([home / "specifications", other / "specifications"],
                                       PermissionError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

            gem = self.gem(second)
            self.assertEqual(gem.get("state"), "unreadable", gem)
            self.assertEqual(self.source(second, SOURCE).get("status"), "unreadable",
                             self.source(second, SOURCE))
            self.assert_count_null(second)

        with self.subTest(case="the user gem parent cannot be listed"):
            profile = self.profile()
            add_stub(profile / ".gem" / "ruby" / ABI, "contoso", "1.2.3")
            environ = {"USERPROFILE": str(profile)}
            data_dir = self.data_dir()
            first = self.collect_with(environ, data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first)), {key(f"user-{ABI}", "contoso")})

            with self.failing_list_dir([profile / ".gem" / "ruby"], PermissionError(DENIED)):
                second = self.collect_with(environ, data_dir=data_dir,
                                           now=NOW + timedelta(days=1))

            parts = self.parts(second)
            self.assertIn("user", parts, parts)
            self.assertEqual(parts["user"].get("status"), "unreadable", parts["user"])
            self.assertTrue(parts["user"].get("reason"), parts["user"])
            self.assert_kept(second, {key(f"user-{ABI}", "contoso"): "1.2.3"})
            self.assert_count_null(second)
            self.assertTrue(self.notes_about(second, f"{SOURCE} user"),
                            second.get("not_checked"))
            self.assertNotEqual(self.gem(second).get("state"), "not_present",
                                self.gem(second))

        with self.subTest(case="an unlistable Ruby beside a Ruby read"):
            denied_ruby = self.temp_folder() / "Ruby32-x64"
            denied_gems = ruby_gems(denied_ruby)
            ruby = self.temp_folder() / "Ruby33-x64"
            part = ruby_gems(ruby) / ABI
            add_stub(part, "contoso", "1.2.3")
            gone_spec = add_stub(part, "gone", "0.5.0")
            environ = {"USERPROFILE": str(self.profile())}
            data_dir = self.data_dir()
            contoso, gone = key(f"ruby-{ABI}", "contoso"), key(f"ruby-{ABI}", "gone")
            first = self.collect_with(environ, rubies=[ruby], data_dir=data_dir, now=NOW)
            self.assertEqual(set(self.items(first)), {contoso, gone})

            gone_spec.unlink()
            with self.failing_list_dir([denied_gems], PermissionError(DENIED)):
                second = self.collect_with(environ, rubies=[denied_ruby, ruby],
                                           data_dir=data_dir, now=NOW + timedelta(days=1))

            items = self.items(second)
            self.assertIn(contoso, items, sorted(map(str, items)))
            self.assertIsNot(items[contoso].get("from_baseline"), True, items[contoso])
            self.assertEqual(self.change_kinds(second), [(gone, "removed")],
                             second.get("changes"))
            self.assertNotEqual(self.gem(second).get("state"), "not_present",
                                self.gem(second))

    # K5
    def test_registry_unreadable(self):
        summary = self.collect_with({"USERPROFILE": str(self.profile())},
                                    rubies=OSError(REGISTRY_ERROR))

        gem = self.gem(summary)
        self.assertNotEqual(gem.get("state"), "not_present", gem)
        named = [item for item in self.notes_about(summary, REGISTRY_NOTE)
                 if REGISTRY_ERROR.casefold() in note_text(item)]
        self.assertTrue(named, summary.get("not_checked"))

    # loc/TEST-PLAN.md (b), new package manager reader: present and empty is read with
    # count 0, never not_present (written by loc-qa for plan 086).
    def test_present_and_empty(self):
        with self.subTest(case="GEM_HOME without a specifications folder"):
            home = self.temp_folder() / "gem-home"
            home.mkdir()
            summary = self.collect_with({"USERPROFILE": str(self.profile()),
                                         "GEM_HOME": str(home)})
            self.assert_empty_gem(summary, "GEM_HOME")

        with self.subTest(case="a Ruby gem folder with an empty specifications folder"):
            ruby = self.temp_folder() / "Ruby33-x64"
            (ruby_gems(ruby) / ABI / "specifications").mkdir(parents=True)
            summary = self.collect_with({"USERPROFILE": str(self.profile())}, rubies=[ruby])
            self.assert_empty_gem(summary, f"ruby-{ABI}")

    def assert_empty_gem(self, summary, label):
        gem = self.gem(summary)
        self.assertNotIn(gem.get("state"), ("not_present", "unreadable", "not_read"), gem)
        self.assertEqual(gem.get("status"), "empty", gem)
        self.assertEqual(gem.get("count"), 0, gem)
        self.assertEqual(gem.get("unreadable"), 0, gem)
        parts = self.parts(summary)
        self.assertEqual(set(parts), {label}, parts)
        self.assertEqual(parts[label].get("status"), "read", parts[label])
        self.assertEqual(parts[label].get("count"), 0, parts[label])
        self.assertEqual(self.items(summary), {})
        self.assertEqual(self.source(summary, SOURCE).get("status"), "empty",
                         self.source(summary, SOURCE))



class FakeKey:
    """An open key of ``FakeWinreg``: its subkeys and values in ``data``."""

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    """A ``winreg`` stand-in over invented uninstall keys: ``roots`` maps
    ``(hive, access)`` to ``{subkey: {value: data} or an exception to raise}``."""
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE = "HKCU", "HKLM"
    KEY_READ, KEY_WOW64_64KEY, KEY_WOW64_32KEY = 0x20019, 0x100, 0x200

    def __init__(self, roots):
        self.roots = roots

    def OpenKey(self, parent, name, reserved=0, access=0):
        if isinstance(parent, FakeKey):
            entry = parent.data[name]
            if isinstance(entry, BaseException):
                raise entry
            return FakeKey(entry)
        if (parent, access) not in self.roots:
            raise FileNotFoundError(2, "invented: no such key")
        return FakeKey(self.roots[(parent, access)])

    def EnumKey(self, key, index):
        names = list(key.data)
        if index >= len(names):
            error = OSError("invented: no more items")
            error.winerror = 259
            raise error
        return names[index]

    def QueryValueEx(self, key, name):
        if name not in key.data:
            raise FileNotFoundError(2, "invented: no such value")
        return key.data[name], 1


class TestGemReviewFixes(GemTestCase):
    """Plan 086 M2 code-review fixes."""

    def test_unreadable_key_keeps_the_other_rubies(self):
        ruby = r"C:\Invented\Ruby33-x64"
        fake = FakeWinreg({
            ("HKLM", FakeWinreg.KEY_READ | FakeWinreg.KEY_WOW64_64KEY): {
                "Contoso Tool": PermissionError(5, "invented: access is denied"),
                "RubyInstaller-3.3.0": {"DisplayName": "Ruby 3.3.0-1-x64",
                                        "InstallLocation": ruby + "\\"},
                "Fabrikam": {"DisplayName": "Fabrikam App",
                             "InstallLocation": r"C:\Invented\Fabrikam"},
            }})
        disk = self.packages.DISK
        with mock.patch.dict("sys.modules", {"winreg": fake}),                 self.assertRaises(OSError) as raised:
            type(disk).ruby_install_locations(disk)
        self.assertEqual(getattr(raised.exception, "found", None), [ruby + "\\"],
                         raised.exception)
        self.assertIn("Contoso Tool", str(raised.exception))

        part = ruby_gems(self.temp_folder() / "Ruby33-x64") / ABI
        add_stub(part, "contoso", "1.2.3")
        error = self.packages.PartlyReadError("1 uninstall key could not be read (invented)",
                                              [str(part.parent.parent.parent.parent)])
        summary = self.collect_with({"USERPROFILE": str(self.profile())}, rubies=error)
        items = self.items(summary)
        self.assertIn(key(f"ruby-{ABI}", "contoso"), items, sorted(map(str, items)))
        self.assertEqual(self.gem(summary).get("state"), "read", self.gem(summary))
        self.assert_count_null(summary)
        self.assertTrue(self.notes_about(summary, REGISTRY_NOTE), summary.get("not_checked"))

    def test_unreadable_newest_gemspec_is_no_downgrade(self):
        home = self.temp_folder() / "gem-home"
        add_stub(home, "contoso", "7.0.0")
        newest = add_stub(home, "contoso", "7.1.0")
        add_stub(home, "contoso-extra", "1.0.0")
        environ = {"USERPROFILE": str(self.profile()), "GEM_HOME": str(home)}
        data_dir = self.data_dir()
        first = self.collect_with(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(self.items(first)[key("GEM_HOME", "contoso")].get("version"),
                         "7.1.0")

        newest.write_text(nameless_gemspec(), encoding="utf-8")
        second = self.collect_with(environ, data_dir=data_dir, now=NOW + timedelta(days=1))

        items = self.items(second)
        self.assertEqual(sorted(items), [key("GEM_HOME", "contoso"),
                                         key("GEM_HOME", "contoso-extra")])
        contoso = items[key("GEM_HOME", "contoso")]
        self.assertEqual(contoso.get("status"), "unreadable", contoso)
        self.assertIsNone(contoso.get("version"), contoso)
        self.assertEqual(items[key("GEM_HOME", "contoso-extra")].get("status"), "read")
        self.assertEqual(self.gem_changes(second), [], second.get("changes"))
        self.assertTrue(self.notes_about(second, "contoso-7.1.0"), second.get("not_checked"))
        self.assertEqual(self.gem(second).get("unreadable"), 1, self.gem(second))

    def test_registry_reason_named_once(self):
        summary = self.collect_with({"USERPROFILE": str(self.profile())},
                                    rubies=OSError(REGISTRY_ERROR))
        named = [item for item in self.not_checked(summary)
                 if REGISTRY_ERROR.casefold() in note_text(item)]
        self.assertEqual(len(named), 1, summary.get("not_checked"))



class TestGemFinalReviewFixes(GemTestCase):
    """Plan 086 final-review fixes."""

    def test_other_rubies_named_as_not_searched(self):
        summary = self.collect_with({"USERPROFILE": str(self.profile())})
        self.assertEqual(self.gem(summary).get("state"), "not_present", self.gem(summary))
        self.assertTrue(self.notes_about(summary, "outside the uninstall keys"),
                        summary.get("not_checked"))

    def test_unreadable_counts_gemspec_files(self):
        home = self.temp_folder() / "gem-home"
        add_stub(home, "contoso", "7.0.0")
        add_stub(home, "contoso", "7.1.0").write_text(nameless_gemspec(), encoding="utf-8")
        add_stub(home, "contoso", "7.2.0").write_text(nameless_gemspec(), encoding="utf-8")
        summary = self.collect_with({"USERPROFILE": str(self.profile()),
                                     "GEM_HOME": str(home)})
        self.assertEqual(self.gem(summary).get("unreadable"), 2, self.gem(summary))
        self.assertTrue(self.notes_about(summary, "contoso-7.1.0"), summary.get("not_checked"))
        self.assertTrue(self.notes_about(summary, "contoso-7.2.0"), summary.get("not_checked"))


if __name__ == "__main__":
    unittest.main()

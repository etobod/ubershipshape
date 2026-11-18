"""VS Code extensions read offline from extensions.json (plan 073, M2, K1-K5).

Interface these tests assume (fixed before the code exists):

- Files are read in Python through the module-level ``DISK`` object (plan 073, M1);
  locations are expanded from the module's ``ENVIRON``. The tests set ``USERPROFILE``
  (and ``VSCODE_EXTENSIONS`` where named) to invented temporary folders.
- The extensions folder is ``VSCODE_EXTENSIONS`` (non-blank), else the raw
  ``%USERPROFILE%\\.vscode\\extensions``. It holds ``extensions.json``: a JSON list of
  entries ``{identifier: {id, uuid}, version, location, relativeLocation, metadata}``.
- Source ``vscode_extensions`` (in ``sources``, ``comparison`` and the baseline),
  compared on ``version``. The detail file keeps its items in ``vscode_extensions``,
  each with ``key`` ``vscode:<id case-folded>`` and the fields ``name``, ``version``,
  ``status``, ``folder`` (the extensions folder + ``\\`` + ``relativeLocation``).
- ``managers.vscode`` is ``{state: "not_present", looked_in: [raw path]}`` when the
  folder is absent, else ``{state, status, folder_from: "VSCODE_EXTENSIONS"|"default",
  count, unreadable}``.

PowerShell never starts; every extensions.json is written by hand in a temporary
folder; every id, version and path is invented.
"""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from .fakes import NOW, PackagesTestCase, note_text, packages_fake

SOURCE = "vscode_extensions"
RAW_DEFAULT_FOLDER = "%USERPROFILE%\\.vscode\\extensions"
MISSING_JSON_REASON = "no extensions.json in the extensions folder"
NO_ID_NOTE = "without an id"

CONTOSO_THEME = "vscode:contoso.theme"
FABRIKAM_LINT = "vscode:fabrikam.lint"


def entry(ext_id, version, folder=None):
    """One entry of extensions.json in the shape VS Code writes (invented values)."""
    if folder is not None:
        relative = folder
    else:
        relative = f"{ext_id}-{version}" if version is not None else ext_id
    row = {
        "identifier": {"id": ext_id, "uuid": "00000000-0000-4000-8000-000000000001"},
        "location": {"$mid": 1, "path": "/c:/invented/" + relative, "scheme": "file"},
        "relativeLocation": relative,
        "metadata": {"installedTimestamp": 1767225600000, "source": "gallery"},
    }
    if version is not None:
        row["version"] = version
    return row


def entry_without_id(version="2.0.0"):
    """An entry whose ``identifier`` has no ``id`` (cannot be keyed)."""
    return {
        "identifier": {"uuid": "00000000-0000-4000-8000-000000000002"},
        "version": version,
        "relativeLocation": "unnamed-" + version,
    }


class VscodeTestCase(PackagesTestCase):
    def temp_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def profile(self):
        """An invented %USERPROFILE% that exists, without a .vscode folder."""
        folder = self.temp_folder() / "Invented"
        folder.mkdir(parents=True)
        return folder

    def default_folder(self, profile):
        folder = profile / ".vscode" / "extensions"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_json(self, folder, entries):
        (Path(folder) / "extensions.json").write_text(json.dumps(entries), encoding="utf-8")

    def run_vscode(self, environ, data_dir=None, now=NOW):
        with mock.patch.object(self.packages, "ENVIRON", dict(environ)):
            return self.collect(packages_fake(), data_dir=data_dir, now=now)

    def vscode(self, summary):
        return self.manager(summary, "vscode")

    def vscode_items(self, summary):
        items = self.detail(summary).get(SOURCE)
        self.assertIsInstance(items, list, f"detail {SOURCE}: {items!r}")
        return self.by_key(items)

    def vscode_changes(self, summary):
        return [change for change in self.changes(summary)
                if str(change.get("key")).startswith("vscode:")]

    def vscode_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if "vscode" in note_text(item) or "vs code" in note_text(item)]

    @staticmethod
    def is_editions_note(item):
        text = note_text(item)
        return "insiders" in text and "vscodium" in text and "portable" in text


class TestVscode(VscodeTestCase):
    def test_absent_is_not_present(self):
        profile = self.profile()
        summary = self.run_vscode({"USERPROFILE": str(profile)})

        self.assertEqual(self.vscode(summary),
                         {"state": "not_present", "looked_in": [RAW_DEFAULT_FOLDER]})
        notes = self.vscode_notes(summary)
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertTrue(self.is_editions_note(notes[0]), notes)

    def test_extensions_from_json(self):
        profile = self.profile()
        folder = self.default_folder(profile)
        self.write_json(folder, [
            entry("contoso.theme", "1.4.0", folder="contoso.theme-1.4.0"),
            entry("fabrikam.lint", None),
            entry_without_id(),
        ])
        summary = self.run_vscode({"USERPROFILE": str(profile)})

        items = self.vscode_items(summary)
        self.assertEqual(set(items), {CONTOSO_THEME, FABRIKAM_LINT}, sorted(map(str, items)))
        theme = items[CONTOSO_THEME]
        self.assertEqual(theme.get("name"), "contoso.theme", theme)
        self.assertEqual(theme.get("version"), "1.4.0", theme)
        self.assertEqual(theme.get("status"), "read", theme)
        self.assertTrue(str(theme.get("folder")).endswith("\\contoso.theme-1.4.0"), theme)
        lint = items[FABRIKAM_LINT]
        self.assertEqual(lint.get("status"), "unreadable", lint)

        vscode = self.vscode(summary)
        self.assertEqual(vscode.get("state"), "read", vscode)
        self.assertEqual(vscode.get("folder_from"), "default", vscode)
        self.assertEqual(vscode.get("unreadable"), 2, vscode)

        notes = [item for item in self.not_checked(summary)
                 if NO_ID_NOTE in note_text(item)]
        self.assertEqual(len(notes), 1, summary.get("not_checked"))
        self.assertIn(SOURCE, note_text(notes[0]), notes)
        self.assertRegex(note_text(notes[0]), r"(?<![0-9])1(?![0-9])", notes)

    def test_missing_or_broken_json_is_unreadable(self):
        cases = {
            "no extensions.json": (None, MISSING_JSON_REASON),
            "extensions.json is not JSON": ("[{\"identifier\": {\"id\": \"contoso.theme\"",
                                            None),
            # Entries, none of them keyed: not "read, nothing there" (plan 073 M2
            # code review, round 1), else every baseline extension is "removed".
            "no entry has an id": (json.dumps([entry_without_id()]), None),
        }
        for case, (broken_text, reason) in cases.items():
            with self.subTest(case=case):
                profile = self.profile()
                folder = self.default_folder(profile)
                data_dir = self.data_dir()
                environ = {"USERPROFILE": str(profile)}

                self.write_json(folder, [entry("contoso.theme", "1.4.0"),
                                         entry("fabrikam.lint", "0.9.1")])
                first = self.run_vscode(environ, data_dir=data_dir, now=NOW)
                self.assertEqual(set(self.vscode_items(first)),
                                 {CONTOSO_THEME, FABRIKAM_LINT})

                json_path = folder / "extensions.json"
                if broken_text is None:
                    json_path.unlink()
                else:
                    json_path.write_text(broken_text, encoding="utf-8")
                second = self.run_vscode(environ, data_dir=data_dir,
                                         now=NOW + timedelta(days=1))

                vscode = self.vscode(second)
                self.assertEqual(vscode.get("state"), "unreadable", vscode)
                self.assertNotEqual(vscode.get("state"), "not_present", vscode)
                self.assertIn("count", vscode, vscode)
                self.assertIsNone(vscode["count"], vscode)
                self.assertEqual(self.source(second, SOURCE).get("status"), "unreadable")

                notes = [item for item in self.vscode_notes(second)
                         if not self.is_editions_note(item)]
                self.assertTrue(notes, second.get("not_checked"))
                self.assertTrue(str(notes[0].get("reason") or "").strip(), notes)
                if reason is not None:
                    self.assertTrue(
                        [item for item in notes if reason in note_text(item)],
                        second.get("not_checked"))

                items = self.vscode_items(second)
                for key, version in ((CONTOSO_THEME, "1.4.0"), (FABRIKAM_LINT, "0.9.1")):
                    self.assertIn(key, items, sorted(map(str, items)))
                    self.assertIs(items[key].get("from_baseline"), True, items[key])
                    self.assertEqual(items[key].get("version"), version, items[key])
                removed = [change for change in self.vscode_changes(second)
                           if change.get("change") == "removed"]
                self.assertEqual(removed, [], second.get("changes"))

    def test_variable_and_empty_list(self):
        # The default folder holds an extension; it must not be looked at.
        profile = self.profile()
        self.write_json(self.default_folder(profile), [entry("contoso.theme", "1.4.0")])
        variable_folder = self.temp_folder() / "invented-extensions"
        variable_folder.mkdir()
        self.write_json(variable_folder, [])

        summary = self.run_vscode({"USERPROFILE": str(profile),
                                   "VSCODE_EXTENSIONS": str(variable_folder)})
        vscode = self.vscode(summary)
        self.assertEqual(vscode.get("state"), "read", vscode)
        self.assertEqual(vscode.get("folder_from"), "VSCODE_EXTENSIONS", vscode)
        self.assertEqual(vscode.get("count"), 0, vscode)
        self.assertEqual(self.vscode_items(summary), {})

        with self.subTest(case="the variable's folder is absent: only it is looked in"):
            absent = self.temp_folder() / "no-such-extensions"
            summary = self.run_vscode({"USERPROFILE": str(profile),
                                       "VSCODE_EXTENSIONS": str(absent)})
            vscode = self.vscode(summary)
            self.assertEqual(vscode.get("state"), "not_present", vscode)
            looked_in = vscode.get("looked_in")
            self.assertIsInstance(looked_in, list, vscode)
            self.assertEqual(len(looked_in), 1, vscode)
            self.assertEqual(Path(looked_in[0]), absent, vscode)
            self.assertNotIn(RAW_DEFAULT_FOLDER.casefold(),
                             [str(path).casefold() for path in looked_in], vscode)

    def test_changes(self):
        profile = self.profile()
        folder = self.default_folder(profile)
        data_dir = self.data_dir()
        environ = {"USERPROFILE": str(profile)}

        self.write_json(folder, [entry("contoso.theme", "1.4.0"),
                                 entry("fabrikam.lint", "0.9.1")])
        first = self.run_vscode(environ, data_dir=data_dir, now=NOW)
        self.assertEqual(self.vscode_changes(first), [])

        self.write_json(folder, [entry("contoso.theme", "1.5.0")])
        second = self.run_vscode(environ, data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(second).get(SOURCE), "compared",
                         self.comparison(second))
        changes = self.by_key(self.vscode_changes(second))
        self.assertEqual({key: change.get("change") for key, change in changes.items()},
                         {CONTOSO_THEME: "changed", FABRIKAM_LINT: "removed"}, changes)
        self.assertEqual(self.field_names(changes[CONTOSO_THEME]), ["version"],
                         changes[CONTOSO_THEME])


if __name__ == "__main__":
    unittest.main()

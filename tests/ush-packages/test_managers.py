"""The summary's ``managers``: every manager of ``data/managers.json`` in its order
(plan 061, M1, K3).

Interface these tests assume (fixed before the code exists):

- ``skills/ush-packages/data/managers.json`` is a list of entries with ``name`` (a dict
  with the list under ``managers`` is accepted too); pip and npm are among them, and so
  is winget.
- ``summary["managers"]`` holds one entry per manager in the file's order: a dict keyed
  by name (key order) or a list of entries with ``name``.
- pip is ``{state, status, pythons}``; npm is ``{state, status, prefix_from, count,
  unreadable}``; pipx, uv and conda (plan 066) are ``not_present`` here, since none of
  their locations exists in these fixtures; so is winget (plan 073, M1: read from disk,
  and the empty ``ENVIRON`` of the tests names no location), and so is vscode (plan 073,
  M2), and so are dotnet-tools and nuget (plan 079, M1) and psgallery (plan 079, M2,
  with ``DISK.documents_folder()`` returning None), and so are choco and vcpkg (plan
  080, M1) and scoop (plan 080, M2); npm is ``{state: "not_present", looked_in}`` when its global ``node_modules``
  folder is missing (plan 073, M2); every other manager is ``{state:
  "not_read"}`` with one ``not_checked`` entry reading ``<name>: not read yet``
  (``what`` and ``reason`` joined by ": ").
- ``state`` is ``read`` for pip/npm ``status`` ``read`` or ``empty``, ``unreadable`` for
  ``status`` ``unreadable``.

PowerShell never starts; every value is invented.
"""

import json
import re
import unittest
from unittest import mock

from .fakes import (
    DEFAULT_NPM_FOLDER,
    MANAGERS_FILE,
    PackagesTestCase,
    failure,
    install_folder,
    note_text,
    npm_package,
    package,
    packages_fake,
    read_folder,
    registration,
    unreadable_folder,
)

PIP_KEYS = {"state", "status", "pythons"}
NPM_KEYS = {"state", "status", "prefix_from", "count", "unreadable"}
ABSENT_WORDS = ("not present", "absent", "not installed", "nie ma")


def manager_names():
    data = json.loads(MANAGERS_FILE.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("managers")
    if not isinstance(data, list):
        raise AssertionError(f"{MANAGERS_FILE}: no list of managers: {data!r}")  # noqa: TRY004
    names = []
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise AssertionError(f"{MANAGERS_FILE}: entry without a name: {entry!r}")  # noqa: TRY004
        names.append(entry["name"])
    return names


def mentions(item, name):
    return re.search(rf"(?<![a-z0-9]){re.escape(name.casefold())}(?![a-z0-9])",
                     note_text(item)) is not None


class TestManagers(PackagesTestCase):
    def test_every_manager_listed(self):
        self.assertTrue(MANAGERS_FILE.is_file(), f"missing {MANAGERS_FILE}")
        names = manager_names()
        folded = [name.casefold() for name in names]
        for wanted in ("pip", "npm", "winget"):
            self.assertIn(wanted, folded, names)
        self.assertEqual(len(set(folded)), len(folded), names)
        # Read by plan 066 (M1: pipx, uv; M2: conda) and plan 073 (M1: winget), and
        # absent in these fixtures (ENVIRON is empty, so no winget location is looked at).
        # Plan 073 M2: vscode too. Plan 079 M1: dotnet-tools and nuget (no USERPROFILE).
        # Plan 079 M2: psgallery (no USERPROFILE, no ProgramFiles, Documents unset).
        # Plan 080 M1: choco (no ProgramData) and vcpkg (no VCPKG_ROOT, no LOCALAPPDATA).
        # Plan 080 M2: scoop (no SCOOP, SCOOP_GLOBAL, USERPROFILE or ProgramData).
        # Plan 083 M1: yarn (no YARN_GLOBAL_FOLDER, no LOCALAPPDATA) and bun (no
        # BUN_INSTALL_GLOBAL_DIR, BUN_INSTALL or USERPROFILE).
        # Plan 083 M2: pnpm (no PNPM_HOME, no LOCALAPPDATA).
        absent_here = ("pipx", "uv", "conda", "winget", "vscode", "dotnet-tools", "nuget",
                       "psgallery", "choco", "vcpkg", "scoop", "yarn", "bun", "pnpm")
        others = [name for name in names
                  if name.casefold() not in ("pip", "npm") + absent_here]

        path = "C:\\Invented\\Python312"
        runs = {
            "pip and npm read": (
                packages_fake(
                    [registration("3.12", path)],
                    {install_folder(path): read_folder(package("requests", "2.31.0")),
                     DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"))}),
                ("read", "read"), ("read", "read")),
            "no Python, no npm": (
                packages_fake(),
                # Plan 073 M2: a missing node_modules is npm not_present (was read/empty).
                ("read", "empty"), ("not_present", None)),
            "pip and npm unreadable": (
                packages_fake(
                    folders={DEFAULT_NPM_FOLDER: unreadable_folder(
                        "Access to the path is denied (invented)")},
                    extra={"python_registrations": failure(
                        "Invented registry error: HKLM\\Software\\Python could not be opened")}),
                ("unreadable", "unreadable"), ("unreadable", "unreadable")),
        }
        for case, (fake, (pip_state, pip_status), (npm_state, npm_status)) in runs.items():
            with self.subTest(case=case):
                # The Documents folder is never read from the registry in a test.
                with mock.patch.object(self.packages.DISK, "documents_folder",
                                       lambda: None):
                    summary = self.collect(fake)
                listed = self.managers(summary)
                self.assertEqual([name for name, _ in listed], names, listed)

                pip = self.manager(summary, "pip")
                self.assertEqual(set(pip), PIP_KEYS, pip)
                self.assertEqual(pip["state"], pip_state, pip)
                self.assertEqual(pip["status"], pip_status, pip)

                npm = self.manager(summary, "npm")
                if npm_state == "not_present":
                    self.assertEqual(npm, {"state": "not_present",
                                           "looked_in": [DEFAULT_NPM_FOLDER]}, npm)
                else:
                    self.assertEqual(set(npm), NPM_KEYS, npm)
                    self.assertEqual(npm["state"], npm_state, npm)
                    self.assertEqual(npm["status"], npm_status, npm)

                notes = self.not_checked(summary)
                for name in absent_here:
                    entry = self.manager(summary, name)
                    self.assertEqual(entry.get("state"), "not_present", f"{name}: {entry}")
                for name in others:
                    entry = self.manager(summary, name)
                    self.assertEqual(entry, {"state": "not_read"}, f"{name}: {entry}")
                    wanted = f"{name}: not read yet".casefold()
                    own = [item for item in notes
                           if re.search(rf"(?<![\w-]){re.escape(wanted)}", note_text(item))]
                    self.assertEqual(len(own), 1, f"{name}: {notes}")
                    # A manager not read is never reported as absent.
                    for item in notes:
                        if mentions(item, name):
                            for word in ABSENT_WORDS:
                                self.assertNotIn(word, note_text(item), item)

                if npm_state == "not_present":
                    # Plan 073 M2: npm not_present (was ``empty`` with count 0 and
                    # unreadable 0); the other prefixes are still named.
                    npm_notes = [item for item in notes if "node.exe" in note_text(item)]
                    self.assertEqual(len(npm_notes), 1, notes)
                    self.assertNotIn("not read yet", note_text(npm_notes[0]), npm_notes)
                if npm_status == "unreadable":
                    self.assertIsNone(npm["count"], npm)
                if pip_status == "unreadable":
                    self.assertIsNone(pip["pythons"], pip)


if __name__ == "__main__":
    unittest.main()

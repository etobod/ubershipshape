"""The summary's ``managers``: every manager of ``data/managers.json`` in its order
(plan 061, M1, K3).

Interface these tests assume (fixed before the code exists):

- ``skills/ush-packages/data/managers.json`` is a list of entries with ``name`` (a dict
  with the list under ``managers`` is accepted too); pip and npm are among them, and so
  is winget (not read in this plan).
- ``summary["managers"]`` holds one entry per manager in the file's order: a dict keyed
  by name (key order) or a list of entries with ``name``.
- pip is ``{state, status, pythons}``; npm is ``{state, status, prefix_from, count,
  unreadable}``; every other manager is ``{state: "not_read"}`` with one ``not_checked``
  entry reading ``<name>: not read yet`` (``what`` and ``reason`` joined by ": ").
- ``state`` is ``read`` for pip/npm ``status`` ``read`` or ``empty``, ``unreadable`` for
  ``status`` ``unreadable``.

PowerShell never starts; every value is invented.
"""

import json
import re
import unittest

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
        others = [name for name in names if name.casefold() not in ("pip", "npm")]

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
                ("read", "empty"), ("read", "empty")),
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
                summary = self.collect(fake)
                listed = self.managers(summary)
                self.assertEqual([name for name, _ in listed], names, listed)

                pip = self.manager(summary, "pip")
                self.assertEqual(set(pip), PIP_KEYS, pip)
                self.assertEqual(pip["state"], pip_state, pip)
                self.assertEqual(pip["status"], pip_status, pip)

                npm = self.manager(summary, "npm")
                self.assertEqual(set(npm), NPM_KEYS, npm)
                self.assertEqual(npm["state"], npm_state, npm)
                self.assertEqual(npm["status"], npm_status, npm)

                notes = self.not_checked(summary)
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

                if npm_status == "empty":
                    # npm ``empty`` keeps its moved meaning and wording: npm is not
                    # present at the prefix read, and the other prefixes are named.
                    self.assertEqual(npm["count"], 0, npm)
                    self.assertEqual(npm["unreadable"], 0, npm)
                    npm_notes = [item for item in notes if "node.exe" in note_text(item)]
                    self.assertEqual(len(npm_notes), 1, notes)
                    self.assertNotIn("not read yet", note_text(npm_notes[0]), npm_notes)
                if npm_status == "unreadable":
                    self.assertIsNone(npm["count"], npm)
                if pip_status == "unreadable":
                    self.assertIsNone(pip["pythons"], pip)


if __name__ == "__main__":
    unittest.main()

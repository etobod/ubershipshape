"""Package changes since the last run (plan 061, M1, K4).

Interface these tests assume (fixed before the code exists):

- Baseline ``ush-packages`` with sources ``pip_packages`` and ``npm_packages``, compared
  on ``version``; ``summary["comparison"]`` is ``{source name: state}``.
- Changes are ``c<n>`` items with ``key``, ``source``, ``change`` (``added``,
  ``removed`` or ``changed``) and, for ``changed``, ``fields`` naming ``version``.
- A package kept from the baseline because its folder could not be listed carries
  ``from_baseline: true`` in the detail file's ``npm_packages`` list.

PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.
"""

import unittest
from datetime import timedelta

from .fakes import (
    DEFAULT_NPM_FOLDER,
    NOW,
    PackagesTestCase,
    id_number,
    install_folder,
    npm_package,
    package,
    packages_fake,
    read_folder,
    registration,
    unreadable_scope,
)

PYTHON = "C:\\Invented\\Python312"
REQUESTS = "pip:PythonCore/3.12|install|requests"
CERTIFI = "pip:PythonCore/3.12|install|certifi"
RIMRAF = "npm:rimraf"
TOOL = "npm:@contoso/tool"


def run_fake(pip_packages, npm_packages):
    return packages_fake(
        [registration("3.12", PYTHON)],
        {install_folder(PYTHON): read_folder(*pip_packages),
         DEFAULT_NPM_FOLDER: read_folder(*npm_packages)})


class TestChanges(PackagesTestCase):
    def test_changes_since_baseline(self):
        data_dir = self.data_dir()
        left_pad = npm_package("left-pad", "1.3.0")
        tool = npm_package("@contoso/tool", "2.1.0")

        # First run: no baseline, no comparison, no change.
        first = self.collect(
            run_fake([package("requests", "2.31.0"), package("certifi", "2024.2.2")],
                     [left_pad, tool]),
            data_dir=data_dir, now=NOW)
        self.assertEqual(self.comparison(first).get("pip_packages"), "no_baseline",
                         self.comparison(first))
        self.assertEqual(self.comparison(first).get("npm_packages"), "no_baseline",
                         self.comparison(first))
        self.assertEqual(self.changes(first), [])

        # Second run: requests changed version, certifi removed, rimraf added.
        second = self.collect(
            run_fake([package("requests", "2.32.0")],
                     [left_pad, tool, npm_package("rimraf", "5.0.5")]),
            data_dir=data_dir, now=NOW + timedelta(days=1))
        self.assertEqual(self.comparison(second).get("pip_packages"), "compared",
                         self.comparison(second))
        self.assertEqual(self.comparison(second).get("npm_packages"), "compared",
                         self.comparison(second))
        changes = self.changes(second)
        self.assertEqual(len(changes), 3, changes)
        by_key = self.by_key(changes)
        self.assertEqual(
            {key: (change.get("source"), change.get("change"))
             for key, change in by_key.items()},
            {REQUESTS: ("pip_packages", "changed"),
             CERTIFI: ("pip_packages", "removed"),
             RIMRAF: ("npm_packages", "added")},
        )
        self.assertEqual(self.field_names(by_key[REQUESTS]), ["version"], by_key[REQUESTS])
        numbers = [id_number(change.get("id"), "c") for change in changes]
        self.assertEqual(len(set(numbers)), 3, changes)

        # Third run: the @contoso scope cannot be listed, so @contoso/tool is carried
        # from the baseline; it gives no change, and nothing else changed.
        third = self.collect(
            run_fake([package("requests", "2.32.0")],
                     [left_pad, unreadable_scope("@contoso"), npm_package("rimraf", "5.0.5")]),
            data_dir=data_dir, now=NOW + timedelta(days=2))
        items = self.by_key(self.npm_items(third))
        self.assertIn(TOOL, items, sorted(map(str, items)))
        self.assertIs(items[TOOL].get("from_baseline"), True, items[TOOL])
        self.assertEqual(items[TOOL].get("version"), "2.1.0", items[TOOL])
        self.assertEqual(self.changes(third), [])


if __name__ == "__main__":
    unittest.main()

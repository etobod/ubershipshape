"""The summary budget of packages.py (plan 061, M1, K7).

About 400 invented npm packages with long names, generated in code; PowerShell never
starts. The budget is inventory's ``SUMMARY_MAX_CHARS``. Over it, ``packages`` items are
cut first, then ``c`` items; the cut items stay in the detail file's ``packages`` and
``changes`` lists, their counts are in the summary keys the report profile names for
those lists (``truncated`` entries, ``count_key`` defaulting to ``truncated``), and
``--detail <id>`` fetches one from the latest run without starting PowerShell.
"""

import unittest
from datetime import timedelta

from tests.skill_loader import load_script

from .fakes import (
    DEFAULT_NPM_FOLDER,
    NOW,
    FakePowerShell,
    PackagesTestCase,
    id_number,
    npm_package,
    packages_fake,
    read_folder,
    truncated_count_keys,
)

PACKAGES = 400


def budget_name(i):
    return f"@contoso/invented-budget-package-with-a-long-example-name-{i:04d}"


def budget_fake(version):
    return packages_fake(folders={DEFAULT_NPM_FOLDER: read_folder(
        *(npm_package(budget_name(i), version) for i in range(PACKAGES)))})


class TestBudget(PackagesTestCase):
    def sized_run(self, data_dir, fake, now):
        code, stdout, stderr = self.run_main(data_dir, fake, now=now)
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), self.budget)
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary, self.detail(summary)

    def cut(self, summary, list_name):
        key = self.count_keys.get(list_name)
        self.assertIsNotNone(key, f"no truncated entry for {list_name}: {self.count_keys}")
        value = summary.get(key)
        self.assertIsInstance(value, int, f"{key}: {value!r}")
        return value

    def fetch(self, data_dir, item_id):
        fake = FakePowerShell()
        code, stdout, stderr = self.run_main(data_dir, fake, now=NOW + timedelta(days=1),
                                             extra=["--detail", item_id])
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(fake.calls, [])
        item = self.parse(stdout)
        self.assertIsInstance(item, dict, stdout[:300])
        return item

    def test_packages_and_changes_cut_to_budget(self):
        inventory = load_script("ush-inventory", "inventory")
        self.assertEqual(self.packages.SUMMARY_MAX_CHARS, inventory.SUMMARY_MAX_CHARS)
        self.budget = self.packages.SUMMARY_MAX_CHARS
        self.count_keys = truncated_count_keys()
        names = {budget_name(i) for i in range(PACKAGES)}
        data_dir = self.data_dir()

        with self.subTest(case="first run: packages cut"):
            summary, detail = self.sized_run(data_dir, budget_fake("1.0.0"), NOW)
            kept = self.package_list(summary)
            cut = self.cut(summary, "packages")
            self.assertGreater(cut, 0)
            self.assertEqual(len(kept) + cut, PACKAGES)
            self.assertEqual(self.changes(summary), [])
            self.assertEqual(self.cut(summary, "changes"), 0)
            everything = self.package_list(detail)
            self.assertEqual({item.get("name") for item in everything}, names)
            for item in everything:
                id_number(item.get("id"), "k")

        summary, detail = self.sized_run(data_dir, budget_fake("2.0.0"),
                                         NOW + timedelta(days=1))
        kept_changes = self.changes(summary)
        all_packages = self.package_list(detail)
        all_changes = detail.get("changes")
        self.assertIsInstance(all_changes, list, type(all_changes))
        with self.subTest(case="second run: packages cut first, then changes"):
            self.assertEqual(self.package_list(summary), [])
            self.assertEqual(self.cut(summary, "packages"), PACKAGES)
            cut_changes = self.cut(summary, "changes")
            self.assertGreater(cut_changes, 0)
            self.assertEqual(len(kept_changes) + cut_changes, PACKAGES)

            self.assertEqual({item.get("name") for item in all_packages}, names)
            self.assertEqual(len(all_changes), PACKAGES)
            self.assertEqual({c.get("key") for c in all_changes},
                             {f"npm:{name}" for name in names})
            for change in all_changes:
                self.assertEqual(change.get("change"), "changed", change)
                id_number(change.get("id"), "c")

        with self.subTest(case="--detail fetches a cut package and a cut change"):
            kept_ids = {c.get("id") for c in kept_changes}
            cut_change = next((c for c in all_changes if c.get("id") not in kept_ids), None)
            self.assertIsNotNone(cut_change, "no change was cut from the summary")
            item = self.fetch(data_dir, cut_change["id"])
            self.assertEqual(item.get("id"), cut_change["id"], item)
            self.assertEqual(item.get("key"), cut_change.get("key"), item)

            cut_package = all_packages[-1]
            item = self.fetch(data_dir, cut_package["id"])
            self.assertEqual(item.get("id"), cut_package["id"], item)
            self.assertEqual(item.get("name"), cut_package.get("name"), item)
            self.assertEqual(item.get("version"), "2.0.0", item)


if __name__ == "__main__":
    unittest.main()

"""conda environments read from environments.txt and conda-meta file names
(plan 066, M2, K1-K5).

Interface these tests assume (fixed before the code exists):

- Job ``conda_environments`` as described in ``fakes.py``; its input names the raw
  ``fakes.CONDA_ENVIRONMENTS_FILE`` (``%USERPROFILE%\\.conda\\environments.txt``).
- Source ``conda_packages`` (in ``comparison``, the baseline and ``changes[].source``),
  compared on ``version``. The detail file keeps its items in ``conda_packages``, each
  item with its ``key``.
- Keys ``conda:<label>|<name case-folded>``; the label is the prefix's last folder name,
  case-folded, with ``~2``, ``~3`` for later prefixes of the same label. Item fields
  ``name``, ``version``, ``build``, ``environment`` (the label), ``folder``
  (``<prefix>\\conda-meta``).
- ``managers.conda``: ``{state: "not_present", looked_in: [raw path]}`` when the file is
  missing; for a read conda it holds ``environments``: rows ``{label, folder: <prefix>,
  status}``; an unreadable file gives ``state`` ``unreadable`` with ``count`` null.
- ``not_checked`` holds "conda environments outside environments.txt (.condarc
  envs_dirs, CONDA_ENVS_PATH)" when conda is read or not present.

PowerShell never starts; every baseline lives in a temporary directory; every path and
value is invented.
"""

import unittest
from datetime import timedelta

from .fakes import (
    CONDA_ENVIRONMENTS_FILE,
    NOW,
    PackagesTestCase,
    absent_prefix,
    conda_file,
    conda_prefix,
    note_text,
    packages_fake,
    unreadable_conda_file,
    unreadable_prefix,
)

OUTSIDE = "conda environments outside environments.txt (.condarc envs_dirs, CONDA_ENVS_PATH)"
NOT_READ_YET = "not read yet"
DENIED = "Access to the path is denied (invented)"

BASE = "D:\\Invented\\Miniconda3"
CONTOSO_ENV = "D:\\Invented\\Miniconda3\\envs\\contoso"
GONE_ENV = "D:\\Invented\\Retired\\envs\\oldlab"
NUMPY_FILE = "numpy-1.26.4-py312h1234_0.json"
CONTOSO_FILE = "contoso-tools-0.9-pyhd8ed1ab_0.json"
NUMPY = "conda:miniconda3|numpy"
CONTOSO_TOOLS = "conda:contoso|contoso-tools"


class CondaTestCase(PackagesTestCase):
    def conda_items(self, summary):
        items = self.detail(summary).get("conda_packages")
        self.assertIsInstance(items, list, f"detail conda_packages: {items!r}")
        return self.by_key(items)

    def environments(self, summary):
        conda = self.manager(summary, "conda")
        rows = conda.get("environments")
        self.assertIsInstance(rows, list, conda)
        return [{"label": row.get("label"), "folder": row.get("folder"),
                 "status": row.get("status")} for row in rows]

    def conda_notes(self, summary):
        return [item for item in self.not_checked(summary) if "conda" in note_text(item)]


class TestConda(CondaTestCase):
    def test_no_environments_file_is_not_present(self):
        fake = packages_fake()
        summary = self.collect(fake)

        self.assertEqual(fake.conda_inputs, [CONDA_ENVIRONMENTS_FILE], fake.conda_inputs)
        self.assertEqual(self.manager(summary, "conda"),
                         {"state": "not_present", "looked_in": [CONDA_ENVIRONMENTS_FILE]})

        notes = self.conda_notes(summary)
        self.assertEqual(len(notes), 1, notes)
        text = note_text(notes[0])
        self.assertIn(OUTSIDE.casefold(), text, notes)
        self.assertNotIn(NOT_READ_YET, text, notes)
        self.assertNotIn("unreadable", text, notes)
        self.assertNotIn("could not", text, notes)

    def test_packages_from_file_names(self):
        fake = packages_fake(conda=conda_file(
            conda_prefix(BASE, NUMPY_FILE),
            conda_prefix(CONTOSO_ENV, CONTOSO_FILE)))
        summary = self.collect(fake)

        self.assertEqual(self.manager(summary, "conda").get("state"), "read",
                         self.manager(summary, "conda"))
        items = self.conda_items(summary)
        self.assertEqual(set(items), {NUMPY, CONTOSO_TOOLS}, sorted(map(str, items)))

        numpy = items[NUMPY]
        self.assertEqual(numpy.get("name"), "numpy", numpy)
        self.assertEqual(numpy.get("version"), "1.26.4", numpy)
        self.assertEqual(numpy.get("build"), "py312h1234_0", numpy)
        self.assertEqual(numpy.get("environment"), "miniconda3", numpy)
        self.assertEqual(numpy.get("folder"), BASE + "\\conda-meta", numpy)

        tools = items[CONTOSO_TOOLS]
        self.assertEqual(tools.get("name"), "contoso-tools", tools)
        self.assertEqual(tools.get("version"), "0.9", tools)
        self.assertEqual(tools.get("build"), "pyhd8ed1ab_0", tools)
        self.assertEqual(tools.get("environment"), "contoso", tools)
        self.assertEqual(tools.get("folder"), CONTOSO_ENV + "\\conda-meta", tools)

        self.assertEqual(self.environments(summary), [
            {"label": "miniconda3", "folder": BASE, "status": "read"},
            {"label": "contoso", "folder": CONTOSO_ENV, "status": "read"},
        ])

    def test_absent_and_unreadable_environments(self):
        data_dir = self.data_dir()
        first = self.collect(
            packages_fake(conda=conda_file(
                conda_prefix(BASE, NUMPY_FILE),
                absent_prefix(GONE_ENV))),
            data_dir=data_dir, now=NOW)

        # The absent prefix: listed as absent, no items, not unreadable.
        self.assertEqual(self.manager(first, "conda").get("state"), "read",
                         self.manager(first, "conda"))
        rows = self.environments(first)
        gone = [row for row in rows if row["folder"] == GONE_ENV]
        self.assertEqual(len(gone), 1, rows)
        self.assertEqual(gone[0]["status"], "absent", rows)
        items = self.conda_items(first)
        self.assertEqual(set(items), {NUMPY}, sorted(map(str, items)))
        for item in items.values():
            self.assertNotEqual(item.get("folder"), GONE_ENV + "\\conda-meta", item)
        for item in self.conda_notes(first):
            text = note_text(item)
            if "oldlab" in text:
                self.assertNotIn("unreadable", text, item)
                self.assertNotIn("could not", text, item)

        # Second run: the base prefix's conda-meta cannot be listed.
        second = self.collect(
            packages_fake(conda=conda_file(
                unreadable_prefix(BASE, DENIED),
                absent_prefix(GONE_ENV))),
            data_dir=data_dir, now=NOW + timedelta(days=1))

        items = self.conda_items(second)
        self.assertIn(NUMPY, items, sorted(map(str, items)))
        self.assertIs(items[NUMPY].get("from_baseline"), True, items[NUMPY])
        self.assertEqual(items[NUMPY].get("version"), "1.26.4", items[NUMPY])

        base_rows = [row for row in self.environments(second) if row["folder"] == BASE]
        self.assertEqual(len(base_rows), 1, self.environments(second))
        self.assertEqual(base_rows[0]["status"], "unreadable", base_rows)

        notes = [item for item in self.not_checked(second)
                 if DENIED.casefold() in note_text(item)
                 and "miniconda3" in note_text(item)]
        self.assertTrue(notes, second.get("not_checked"))

        removed = [change for change in self.changes_from(second, "conda_packages")
                   if change.get("change") == "removed"]
        self.assertEqual(removed, [], second.get("changes"))

    def test_unreadable_environments_file(self):
        summary = self.collect(packages_fake(conda=unreadable_conda_file(DENIED)))

        conda = self.manager(summary, "conda")
        self.assertEqual(conda.get("state"), "unreadable", conda)
        self.assertNotEqual(conda.get("state"), "not_present", conda)
        self.assertIn("count", conda, conda)
        self.assertIsNone(conda["count"], conda)

    def test_same_label_prefixes(self):
        first_prefix = "D:\\Invented\\Miniconda3\\envs\\py312"
        second_prefix = "E:\\Invented\\Elsewhere\\py312"
        summary = self.collect(packages_fake(conda=conda_file(
            conda_prefix(first_prefix, "numpy-1.26.4-py312h1234_0.json"),
            conda_prefix(second_prefix, "numpy-2.1.0-py312h5678_0.json"))))

        self.assertEqual(self.environments(summary), [
            {"label": "py312", "folder": first_prefix, "status": "read"},
            {"label": "py312~2", "folder": second_prefix, "status": "read"},
        ])

        items = self.conda_items(summary)
        first_key, second_key = "conda:py312|numpy", "conda:py312~2|numpy"
        self.assertEqual(set(items), {first_key, second_key}, sorted(map(str, items)))
        self.assertEqual(items[first_key].get("version"), "1.26.4", items[first_key])
        self.assertEqual(items[first_key].get("environment"), "py312", items[first_key])
        self.assertEqual(items[first_key].get("folder"), first_prefix + "\\conda-meta",
                         items[first_key])
        self.assertEqual(items[second_key].get("version"), "2.1.0", items[second_key])
        self.assertEqual(items[second_key].get("environment"), "py312~2", items[second_key])
        self.assertEqual(items[second_key].get("folder"), second_prefix + "\\conda-meta",
                         items[second_key])

    def test_duplicate_prefix_lines_read_once(self):
        """Fixes 066 M2 code-review #2: the same prefix written twice (other case, a
        trailing backslash) is one environment, read once."""
        prefix = "D:\\Invented\\Miniconda3"
        summary = self.collect(packages_fake(conda=conda_file(
            conda_prefix(prefix, "numpy-1.26.4-py312h1234_0.json"),
            conda_prefix("d:\\invented\\miniconda3\\", "numpy-1.26.4-py312h1234_0.json"),
            conda_prefix("D:/Invented//Miniconda3", "numpy-1.26.4-py312h1234_0.json"))))

        self.assertEqual(self.environments(summary), [
            {"label": "miniconda3", "folder": prefix, "status": "read"},
        ])
        self.assertEqual(set(self.conda_items(summary)), {"conda:miniconda3|numpy"})
        self.assertEqual(summary["managers"]["conda"]["count"], 1)

    def test_label_kept_when_earlier_prefix_goes(self):
        """Fixes 066 final-review #1: the second prefix of a label keeps ``~2`` when the
        first one leaves environments.txt, so its packages give no false ``changed``."""
        first_prefix = "D:\\Invented\\Miniconda3\\envs\\py312"
        second_prefix = "E:\\Invented\\Elsewhere\\py312"
        data_dir = self.data_dir()
        self.collect(packages_fake(conda=conda_file(
            conda_prefix(first_prefix, "numpy-1.26.4-py312h1234_0.json"),
            conda_prefix(second_prefix, "numpy-2.1.0-py312h5678_0.json"))),
            data_dir=data_dir, now=NOW)
        second = self.collect(packages_fake(conda=conda_file(
            conda_prefix(second_prefix, "numpy-2.1.0-py312h5678_0.json"))),
            data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.environments(second), [
            {"label": "py312~2", "folder": second_prefix, "status": "read"}])
        self.assertEqual(set(self.conda_items(second)), {"conda:py312~2|numpy"})
        changes = self.changes_from(second, "conda_packages")
        self.assertEqual([(c.get("change"), c.get("key")) for c in changes],
                         [("removed", "conda:py312|numpy")], changes)


if __name__ == "__main__":
    unittest.main()

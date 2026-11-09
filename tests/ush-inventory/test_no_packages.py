"""ush-inventory without pip and npm (plan 061, milestone M2, criterion K1).

pip and npm packages moved to ush-packages. Interface these tests assume (fixed before
the code exists):

- An inventory summary has no ``package_managers`` key; its detail file has no
  ``pip_packages`` and no ``npm_packages`` key.
- The run starts no pip, npm or ``.npmrc`` job: no ``python_registrations`` or ``npmrc``
  job, no job whose name names pip or npm, no ``package_folders`` input folder with the
  layout ``python`` or ``npm``, and no job script that reads ``.npmrc``.
- A baseline (``<data dir>/state/ush-inventory.json``, ``sources`` keyed by source name,
  then by item key) that still holds ``pip_packages`` items from an older run gives no
  change and no ``c`` item for them; the changes come only from inventory sources.

PowerShell never starts; every baseline lives in a temporary directory; every value is
invented.
"""

import json
import unittest
from datetime import timedelta
from pathlib import Path

from .fakes import NOW, FakePowerShell, InventoryTestCase, default_win32, ok, win32

PACKAGE_JOBS = ("python_registrations", "npmrc")
PACKAGE_LAYOUTS = ("python", "npm")

NEW_PROGRAM_KEY = "win32:hklm64:InventedNewApp"

# Items as an older inventory run saved them in its pip_packages source (invented).
OLD_PIP_ITEMS = {
    "pip:PythonCore/3.12|install|requests": {
        "python": "PythonCore/3.12", "folder": "install", "name": "requests",
        "version": "2.31.0", "status": "read", "reason": None,
    },
    "pip:PythonCore/3.12|user|certifi": {
        "python": "PythonCore/3.12", "folder": "user", "name": "certifi",
        "version": "2024.2.2", "status": "read", "reason": None,
    },
}


class RecordingFakePowerShell(FakePowerShell):
    """``FakePowerShell`` that also keeps the input folders of any ``package_folders``
    call, read from ``<out stem>.input.json`` next to ``out_path``."""

    def __init__(self, responses=None):
        super().__init__(responses)
        self.folder_inputs = []

    def __call__(self, job, script, out_path):
        if job == "package_folders":
            path = Path(out_path)
            input_path = path.with_name(path.name[:-len(".json")] + ".input.json")
            if input_path.is_file():
                data = json.loads(input_path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    self.folder_inputs.extend(data.get("folders") or [])
        return super().__call__(job, script, out_path)


class TestNoPackages(InventoryTestCase):
    def assert_no_package_jobs(self, fake):
        jobs = fake.jobs()
        for job in PACKAGE_JOBS:
            self.assertNotIn(job, jobs, jobs)
        for job in jobs:
            folded = str(job).casefold()
            self.assertNotIn("pip", folded, jobs)
            self.assertNotIn("npm", folded, jobs)
        layouts = [str(folder.get("layout")) for folder in fake.folder_inputs
                   if isinstance(folder, dict)]
        for layout in PACKAGE_LAYOUTS:
            self.assertNotIn(layout, layouts, fake.folder_inputs)
        for job, script, _ in fake.calls:
            self.assertNotIn(".npmrc", str(script).casefold(), job)

    def assert_no_package_data(self, summary):
        self.assertNotIn("package_managers", summary, sorted(summary))
        detail = self.detail(summary)
        self.assertNotIn("pip_packages", detail, sorted(detail))
        self.assertNotIn("npm_packages", detail, sorted(detail))

    def assert_only_new_program(self, changes, where):
        self.assertIsInstance(changes, list, f"{where}: {changes!r}")
        for change in changes:
            source = str(change.get("source"))
            key = str(change.get("key"))
            self.assertNotIn(source, ("pip_packages", "npm_packages"), f"{where}: {change}")
            self.assertFalse(key.startswith(("pip:", "npm:")), f"{where}: {change}")
        self.assertEqual(
            [(c.get("source"), c.get("key"), c.get("change")) for c in changes],
            [("win32_programs", NEW_PROGRAM_KEY, "added")],
            where,
        )

    def test_no_packages(self):
        data_dir = self.data_dir()

        first_fake = RecordingFakePowerShell()
        first = self.collect(first_fake, data_dir=data_dir, now=NOW)
        self.assert_no_package_jobs(first_fake)
        self.assert_no_package_data(first)

        # The saved baseline still holds pip_packages items, as one from before the move.
        state = data_dir / "state" / "ush-inventory.json"
        self.assertTrue(state.is_file(), f"{state} was not written")
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        sources = saved.get("sources")
        self.assertIsInstance(sources, dict, sorted(saved))
        sources["pip_packages"] = json.loads(json.dumps(OLD_PIP_ITEMS))
        state.write_text(json.dumps(saved), encoding="utf-8")

        second_fake = RecordingFakePowerShell({"win32_programs": ok(
            default_win32() + [win32("InventedNewApp", "Invented New App",
                                     install_date="20260919")])})
        second = self.collect(second_fake, data_dir=data_dir, now=NOW + timedelta(days=1))
        self.assert_no_package_jobs(second_fake)
        self.assert_no_package_data(second)

        self.assert_only_new_program(self.changes(second), "summary changes")
        self.assert_only_new_program(self.detail(second).get("changes"), "detail changes")


if __name__ == "__main__":
    unittest.main()

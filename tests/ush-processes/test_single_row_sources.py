"""One-row answers of the sources added in plan 107 (M1): ConvertTo-Json writes a single
object, not a list, when a job has one row. ``image_paths`` and ``network_profiles``
must read it like a one-element list.

PowerShell never starts; every process, path and time is invented.
"""

import unittest

from .fakes import FakePowerShell, ProcessesTestCase, machine, ok, proc
from .test_review_notes import FIREFOX, image_row


class TestSingleRowSources(ProcessesTestCase):
    def test_image_paths_single_object(self):
        fake = FakePowerShell(machine([proc(300, "firefox.exe", path=None, created=10)]))
        fake.responses["image_paths"] = ok(image_row(300, FIREFOX, 10))
        summary = self.collect(fake)
        groups = [g for g in self.groups(summary) if g.get("name") == "firefox.exe"]
        self.assertEqual(len(groups), 1, self.groups(summary))
        self.assertEqual(groups[0].get("path"), FIREFOX, groups[0])
        self.assertEqual(groups[0].get("path_source"), "query_image", groups[0])
        self.assertIs(groups[0].get("path_read"), True, groups[0])
        self.assertEqual(
            [n for n in self.not_checked(summary) if "image_paths" in str(n)], [],
            self.not_checked(summary))

    def test_network_profiles_single_object(self):
        responses = machine([proc(120, "editor.exe", r"C:\Apps\Editor\editor.exe", created=3)])
        responses["network_profiles"] = ok({"Category": "Private"})
        summary = self.collect(FakePowerShell(responses))
        self.assertEqual(summary.get("network_categories"), {"Private": 1}, summary)
        self.assertEqual(
            [n for n in self.not_checked(summary) if "network_profiles" in str(n)], [],
            self.not_checked(summary))


if __name__ == "__main__":
    unittest.main()

"""The installed packages in the summary (plan 061, M1, K8).

Interface these tests assume (fixed before the code exists):

- ``summary["packages"]`` is one flat list over the read managers. Each item has
  ``manager`` (``pip`` or ``npm``), ``id`` (``k<n>``), ``name`` and ``version``; a pip
  item has ``python`` (``<company>/<tag>``) and ``folder`` (``install`` or ``user``); an
  npm item has ``folder``, the ``node_modules`` folder it was read from.
- ``packages`` is a required list of the report profile (id letter ``k``): a report
  that leaves out a ``k`` item fails ``check_report.py``.

PowerShell never starts; every value is invented.
"""

import unittest

from .fakes import (
    DEFAULT_NPM_FOLDER,
    PackagesTestCase,
    id_number,
    install_folder,
    npm_package,
    package,
    packages_fake,
    read_folder,
    registration,
    user_folder,
)
from .test_report_profile import ReportCheckMixin, clean_report_lines

PYTHON = "C:\\Invented\\Python312"


class TestSummaryPackages(ReportCheckMixin, PackagesTestCase):
    def test_every_package_listed_and_required(self):
        fake = packages_fake(
            [registration("3.12", PYTHON)],
            {install_folder(PYTHON): read_folder(package("requests", "2.31.0")),
             user_folder("312"): read_folder(package("idna", "3.6")),
             DEFAULT_NPM_FOLDER: read_folder(npm_package("left-pad", "1.3.0"),
                                             npm_package("@contoso/tool", "2.1.0"))})
        summary = self.collect(fake)

        with self.subTest(case="every package with its version and place"):
            items = self.package_list(summary)
            by_package = {(item.get("manager"), item.get("name")): item for item in items}
            self.assertEqual(len(by_package), len(items), items)
            expected = {
                ("pip", "requests"): ("2.31.0", "install"),
                ("pip", "idna"): ("3.6", "user"),
                ("npm", "left-pad"): ("1.3.0", None),
                ("npm", "@contoso/tool"): ("2.1.0", None),
            }
            self.assertEqual(set(by_package), set(expected), sorted(by_package))
            ids = []
            for (manager, name), (version, folder) in expected.items():
                item = by_package[(manager, name)]
                ids.append(id_number(item.get("id"), "k"))
                self.assertEqual(item.get("version"), version, item)
                if manager == "pip":
                    self.assertEqual(item.get("python"), "PythonCore/3.12", item)
                    self.assertEqual(item.get("folder"), folder, item)
                else:
                    self.assertIn("node_modules", str(item.get("folder")).casefold(), item)
            self.assertEqual(len(set(ids)), len(ids), items)

        with self.subTest(case="a report without a k item fails the checker"):
            self.make_workspace()
            self.assert_real_profile()
            summary_file, _ = self.write_summary("packages-k")
            clean = clean_report_lines(summary_file)
            self.assert_passes(clean, "packages-2026-11-09-1010.md")
            lines = [line for line in clean if not line.startswith("- k2:")]
            self.assert_names_missing(lines, "packages-2026-11-09-1011.md", "k2")


if __name__ == "__main__":
    unittest.main()

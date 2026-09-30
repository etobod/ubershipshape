"""The 35000-character summary budget of inventory.py (plan 048, M2).

2000 invented Win32 programs, generated in code, each with its own install date;
PowerShell is never started. The interface is described in ``fakes.py``.
"""

import json
import random
import unittest
from datetime import date, timedelta
from pathlib import Path

from .fakes import NOW, FakePowerShell, InventoryTestCase, ok, win32
from .fakes_additions import (
    admins_result,
    cert,
    certificates_result,
    custom_rule,
    firewall_result,
    fw_value,
    hosts_result,
    m2_responses,
    member,
    thumb,
)
from .fakes_autostart import run_value
from .fakes_components import DISABLED, ENABLED, driver, feature

PROGRAMS = 2000
BUDGET = 35000
FIRST_DAY = date(2020, 1, 1)


def install_day(index):
    return FIRST_DAY + timedelta(days=index)


def program_rows():
    """Program i is installed i days after FIRST_DAY; the rows arrive shuffled."""
    rows = [
        win32(
            f"InventedBudgetApp{i:04d}",
            f"Invented Budget App {i:04d} with an Invented Example Component",
            version=f"{i % 7}.{i % 13}.{i}",
            publisher="Invented Publisher of Example Software Ltd",
            install_date=install_day(i).strftime("%Y%m%d"),
            install_location=f"C:\\Invented\\Programs\\Budget App {i:04d}",
        )
        for i in range(PROGRAMS)
    ]
    random.Random(48).shuffle(rows)
    return rows


def third_party_driver_rows(count):
    """``count`` invented drivers from ``oem<N>.inf`` files (not part of Windows)."""
    return [
        driver(
            f"PCI\\VEN_1AAA&DEV_{i:04X}\\INVENTED{i:04d}",
            f"oem{i}.inf",
            device_name=f"Invented Budget Device {i:04d} with an Invented Example Controller",
            provider="Invented Hardware Vendor of Example Devices Ltd",
            version=f"{i % 9}.{i % 5}.{i}.0",
            date="2025-06-01",
        )
        for i in range(count)
    ]


def feature_key(i):
    return f"feature:InventedBudgetFeature{i:04d}"


def feature_rows(count, disabled=()):
    """``count`` invented features, enabled except the indexes in ``disabled``."""
    return [
        feature(f"InventedBudgetFeature{i:04d}", DISABLED if i in disabled else ENABLED)
        for i in range(count)
    ]


def firewall_rows(count):
    """``count`` invented rules in the ``local`` store, none of them built in."""
    return firewall_result(local=[
        fw_value(f"{{00000000-0000-0000-0000-{i:012d}}}",
                 custom_rule(f"Invented Budget Server {i:04d}", port=str(10000 + i),
                             app=f"C:\\Invented\\Budget Server {i:04d}\\server.exe"))
        for i in range(count)
    ])


def machine_certs(count):
    """``count`` invented roots in ``machine_root``, none of them shipped with Windows."""
    return [cert(thumb(0xF000 + i), subject=f"CN=Invented Budget Root {i}",
                 issuer="CN=Invented Budget Issuer") for i in range(count)]


def hosts_text(count):
    return "".join(f"0.0.0.0 ad{i:05d}.example\n" for i in range(count))


def autostart_rows():
    return [
        run_value("InventedTrayA", "\"C:\\Invented\\Tray A\\tray.exe\" /background"),
        run_value("InventedTrayB", "\"C:\\Invented\\Tray B\\tray.exe\" /minimized"),
    ]


class TestBudget(InventoryTestCase):
    def test_programs_cut_to_budget(self):
        fake = FakePowerShell({"win32_programs": ok(program_rows()), "msix_programs": ok([])})
        code, stdout, stderr = self.run_main(self.data_dir(), fake)
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = json.loads(stdout)

        truncated = summary.get("truncated")
        self.assertIsInstance(truncated, int, truncated)
        self.assertGreater(truncated, 0)

        kept = summary.get("programs")
        self.assertIsInstance(kept, list, kept)
        self.assertGreater(len(kept), 0)
        self.assertEqual(len(kept) + truncated, PROGRAMS)

        # The newest installs stay, newest first.
        newest = range(PROGRAMS - 1, PROGRAMS - 1 - len(kept), -1)
        self.assertEqual(
            [item.get("install_date") for item in kept],
            [install_day(i).isoformat() for i in newest],
        )
        self.assertEqual(
            [item.get("key") for item in kept],
            [f"win32:hklm64:InventedBudgetApp{i:04d}" for i in newest],
        )

        detail_path = Path(summary.get("detail_file"))
        self.assertTrue(detail_path.is_absolute(), detail_path)
        detail = json.loads(detail_path.read_text(encoding="utf-8-sig"))
        everything = detail.get("programs")
        self.assertIsInstance(everything, list, type(everything))
        self.assertEqual(len(everything), PROGRAMS)
        self.assertEqual(
            {item.get("key") for item in everything},
            {f"win32:hklm64:InventedBudgetApp{i:04d}" for i in range(PROGRAMS)},
        )

    def sized_run(self, data_dir, fake, now):
        """Run main; the summary must fit the budget. Return (summary, detail)."""
        code, stdout, stderr = self.run_main(data_dir, fake, now=now)
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = json.loads(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        detail_path = Path(summary.get("detail_file"))
        self.assertTrue(detail_path.is_absolute(), detail_path)
        detail = json.loads(detail_path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(detail, dict, type(detail))
        return summary, detail

    def listed(self, data, name):
        value = data.get(name)
        self.assertIsInstance(value, list, f"{name}: {type(value).__name__}")
        return value

    def count(self, summary, name):
        value = summary.get(name)
        self.assertIsInstance(value, int, f"{name}: {value!r}")
        return value

    def test_cut_order(self):
        with self.subTest(case="programs gone, drivers cut, components whole"):
            data_dir = self.data_dir()
            switched = {3, 40, 77}
            before = {
                "win32_programs": ok(program_rows()), "msix_programs": ok([]),
                "drivers": ok(third_party_driver_rows(500)),
                "optional_features": ok(feature_rows(100, disabled=switched)),
                "run_keys": ok(autostart_rows()),
            }
            after = dict(before, optional_features=ok(feature_rows(100)))
            self.run_main(data_dir, FakePowerShell(before), now=NOW)
            summary, detail = self.sized_run(data_dir, FakePowerShell(after),
                                             now=NOW + timedelta(days=1))

            self.assertEqual(self.count(summary, "truncated"), PROGRAMS)
            self.assertEqual(self.listed(summary, "programs"), [])
            truncated_drivers = self.count(summary, "truncated_drivers")
            self.assertGreater(truncated_drivers, 0)
            self.assertEqual(len(self.listed(summary, "drivers")) + truncated_drivers, 500)
            self.assertEqual(
                {item.get("key") for item in self.listed(summary, "components")},
                {feature_key(i) for i in range(100)},
            )
            self.assertFalse(summary.get("truncated_components"),
                             summary.get("truncated_components"))

            self.assertEqual(len(self.listed(summary, "autostart")), 2)
            self.assertEqual(
                {item.get("key") for item in self.listed(summary, "changes")},
                {feature_key(i) for i in switched},
            )

            self.assertEqual(len(self.listed(detail, "programs")), PROGRAMS)
            self.assertEqual(len(self.listed(detail, "drivers")), 500)
            self.assertEqual(len(self.listed(detail, "components")), 100)

        with self.subTest(case="programs and drivers gone, components cut"):
            summary, detail = self.sized_run(
                self.data_dir(),
                FakePowerShell({
                    "win32_programs": ok(program_rows()), "msix_programs": ok([]),
                    "drivers": ok(third_party_driver_rows(50)),
                    "optional_features": ok(feature_rows(3000)),
                }),
                now=NOW,
            )

            self.assertEqual(self.count(summary, "truncated"), PROGRAMS)
            self.assertEqual(self.listed(summary, "programs"), [])
            self.assertEqual(self.count(summary, "truncated_drivers"), 50)
            self.assertEqual(self.listed(summary, "drivers"), [])
            truncated_components = self.count(summary, "truncated_components")
            self.assertGreater(truncated_components, 0)
            self.assertEqual(
                len(self.listed(summary, "components")) + truncated_components, 3000
            )

            self.assertEqual(len(self.listed(detail, "programs")), PROGRAMS)
            self.assertEqual(len(self.listed(detail, "drivers")), 50)
            self.assertEqual(
                {item.get("key") for item in self.listed(detail, "components")},
                {feature_key(i) for i in range(3000)},
            )

    def of_kind(self, items, kind):
        return [item for item in items if isinstance(item, dict) and item.get("kind") == kind]

    def test_additions_cut_last(self):
        admins = admins_result([
            member("S-1-5-21-0-0-0-1001", "EXAMPLE-PC\\invented.one"),
            member("S-1-5-21-0-0-0-1002", "EXAMPLE-PC\\invented.two"),
        ])

        with self.subTest(case="1000 firewall rules cut, members and certificates stay"):
            summary, _ = self.sized_run(
                self.data_dir(),
                FakePowerShell(m2_responses(
                    win32_programs=ok(program_rows()), msix_programs=ok([]),
                    firewall_rules=ok(firewall_rows(1000)),
                    administrators=ok(admins),
                    root_certificates=ok(certificates_result(machine_root=machine_certs(2))),
                    hosts=ok(hosts_result("")),
                )),
                now=NOW,
            )
            self.assertEqual(self.count(summary, "truncated"), PROGRAMS)
            self.assertGreater(self.count(summary, "truncated_additions"), 0)
            additions = self.listed(summary, "additions")
            self.assertEqual(len(self.of_kind(additions, "administrator")), 2)
            self.assertEqual(len(self.of_kind(additions, "root_certificate")), 2)

        with self.subTest(case="20000 hosts entries cut, rules and certificates stay"):
            summary, _ = self.sized_run(
                self.data_dir(),
                FakePowerShell(m2_responses(
                    win32_programs=ok(program_rows()), msix_programs=ok([]),
                    firewall_rules=ok(firewall_rows(50)),
                    root_certificates=ok(certificates_result(machine_root=machine_certs(3))),
                    hosts=ok(hosts_result(hosts_text(20000))),
                )),
                now=NOW,
            )
            self.assertEqual(self.count(summary, "truncated"), PROGRAMS)
            truncated_additions = self.count(summary, "truncated_additions")
            self.assertGreater(truncated_additions, 0)
            additions = self.listed(summary, "additions")
            self.assertEqual(len(self.of_kind(additions, "firewall_rule")), 50)
            self.assertEqual(len(self.of_kind(additions, "root_certificate")), 3)
            self.assertEqual(
                len(self.of_kind(additions, "hosts_entry")) + truncated_additions, 20000
            )


if __name__ == "__main__":
    unittest.main()

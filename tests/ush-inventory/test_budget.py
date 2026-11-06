"""The 35000-character summary budget of inventory.py (plan 048, M2).

2000 invented Win32 programs, generated in code, each with its own install date;
PowerShell is never started. The interface is described in ``fakes.py``.
"""

import json
import random
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .fakes import NOW, FakePowerShell, InventoryTestCase, id_number, msix, ok, win32
from .fakes_additions import (
    admins_result,
    cert,
    certificates_result,
    custom_rule,
    defender_result,
    firewall_result,
    fw_value,
    hosts_result,
    m2_responses,
    member,
    thumb,
)
from .fakes_autostart import VENDOR, facts, file_row, run_value, service
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
        with self.subTest(case="programs down to the minimum, drivers cut, components whole"):
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

            self.assertEqual(self.count(summary, "truncated"), PROGRAMS - PROGRAMS_MINIMUM)
            self.assertEqual([p["id"] for p in self.listed(summary, "programs")],
                             [p["id"] for p in self.listed(detail, "programs")][:PROGRAMS_MINIMUM])
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

        with self.subTest(case="programs and drivers at the minimum, components cut"):
            summary, detail = self.sized_run(
                self.data_dir(),
                FakePowerShell({
                    "win32_programs": ok(program_rows()), "msix_programs": ok([]),
                    "drivers": ok(third_party_driver_rows(50)),
                    "optional_features": ok(feature_rows(3000)),
                }),
                now=NOW,
            )

            self.assertEqual(self.count(summary, "truncated"), PROGRAMS - PROGRAMS_MINIMUM)
            self.assertEqual([p["id"] for p in self.listed(summary, "programs")],
                             [p["id"] for p in self.listed(detail, "programs")][:PROGRAMS_MINIMUM])
            # Plan 107 M3: drivers keep their short list (DRIVERS_MIN) before
            # components are cut.
            drivers_min = self.inventory.DRIVERS_MIN
            self.assertEqual(self.count(summary, "truncated_drivers"), 50 - drivers_min)
            self.assertEqual([d["id"] for d in self.listed(summary, "drivers")],
                             [d["id"] for d in self.listed(detail, "drivers")][:drivers_min])
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
            self.assertEqual(self.count(summary, "truncated"), PROGRAMS - PROGRAMS_MINIMUM)
            self.assertEqual(len(self.listed(summary, "programs")), PROGRAMS_MINIMUM)
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
            self.assertEqual(self.count(summary, "truncated"), PROGRAMS - PROGRAMS_MINIMUM)
            self.assertEqual(len(self.listed(summary, "programs")), PROGRAMS_MINIMUM)
            truncated_additions = self.count(summary, "truncated_additions")
            self.assertGreater(truncated_additions, 0)
            additions = self.listed(summary, "additions")
            self.assertEqual(len(self.of_kind(additions, "firewall_rule")), 50)
            self.assertEqual(len(self.of_kind(additions, "root_certificate")), 3)
            self.assertEqual(
                len(self.of_kind(additions, "hosts_entry")) + truncated_additions, 20000
            )


# --- Slim summary items (plan 074, M1, K1-K3) -------------------------------------------

SLIM_COMPANY = "Invented Vendor Company of Example Tools"


def slim_program_rows(count):
    """``count`` invented Win32 programs, each with a long ``install_location``."""
    return [
        win32(
            f"InventedSlimApp{i:02d}",
            f"Invented Slim App {i:02d}",
            version=f"2.{i}.0",
            publisher="Invented Publisher of Example Software Ltd",
            install_date=install_day(i).strftime("%Y%m%d"),
            install_location=(f"C:\\Invented\\Programs\\Invented Slim Application Folder {i:02d}"
                              "\\An Invented Long Subfolder Name For The Example"),
        )
        for i in range(count)
    ]


def slim_tray_target(i):
    return f"C:\\Invented\\Slim Tray {i:02d}\\tray.exe"


def slim_agent_target(i):
    return f"%ProgramFiles%\\Invented Slim Agent {i:02d}\\agent.exe"


def slim_agent_expanded(i):
    return f"C:\\Program Files\\Invented Slim Agent {i:02d}\\agent.exe"


def slim_autostart_responses(runs, services):
    """``runs`` Run values and ``services`` services, all vendor-signed (never own).

    A Run value's target is written out in full (``expanded_path`` equals ``path``); a
    service's target starts with ``%ProgramFiles%`` (``expanded_path`` differs).
    """
    run_rows = [run_value(f"InventedSlimTray{i:02d}", f"\"{slim_tray_target(i)}\" /background")
                for i in range(runs)]
    service_rows = [
        service(f"InventedSlimAgent{i:02d}", f"\"{slim_agent_target(i)}\" -service",
                display_name=f"Invented Slim Agent Service Number {i:02d}")
        for i in range(services)
    ]
    file_rows = (
        [file_row(slim_tray_target(i), signer=VENDOR, company=SLIM_COMPANY)
         for i in range(runs)]
        + [file_row(slim_agent_target(i), expanded=slim_agent_expanded(i), signer=VENDOR,
                    company=SLIM_COMPANY) for i in range(services)]
    )
    return {
        "run_keys": ok(run_rows),
        "services": ok(service_rows),
        "file_facts": facts(*file_rows),
    }


class TestSlimSummary(InventoryTestCase):
    def summary_items(self, summary, name):
        items = summary.get(name)
        self.assertIsInstance(items, list, f"{name}: {type(items).__name__}")
        return items

    def detail_by_key(self, summary, name):
        return self.by_key(self.summary_items(self.detail(summary), name))

    def fact_by_path(self, entry, path):
        entry_facts = entry.get("facts")
        self.assertIsInstance(entry_facts, list, entry)
        matches = [fact for fact in entry_facts
                   if isinstance(fact, dict) and fact.get("path") == path]
        self.assertEqual(len(matches), 1, f"fact {path} in {entry}")
        return matches[0]

    def test_program_fields(self):
        win32_key = "win32:hklm64:InventedSlimApp"
        msix_key = "msix:Invented.SlimStore_0abc1def2ghj3"
        win32_location = "C:\\Invented\\Programs\\Invented Slim App"
        msix_location = "C:\\Invented\\WindowsApps\\Invented.SlimStore_2.0.0.0"
        summary = self.collect(FakePowerShell({
            "win32_programs": ok([win32("InventedSlimApp", "Invented Slim App",
                                        version="3.1.0", install_location=win32_location)]),
            "msix_programs": ok([msix("Invented.SlimStore_0abc1def2ghj3", "Invented.SlimStore",
                                      version="2.0.0.0", install_location=msix_location)]),
        }))

        listed = self.by_key(self.summary_items(summary, "programs"))
        self.assertEqual(set(listed), {win32_key, msix_key}, listed)
        for key, name, version in ((win32_key, "Invented Slim App", "3.1.0"),
                                   (msix_key, "Invented.SlimStore", "2.0.0.0")):
            item = listed[key]
            with self.subTest(item=key, place="summary"):
                self.assertIn("id", item, item)
                id_number(item.get("id"), "a")
                self.assertEqual(item.get("key"), key, item)
                self.assertEqual(item.get("name"), name, item)
                self.assertEqual(item.get("version"), version, item)
                for field in ("install_location", "source", "own"):
                    self.assertNotIn(field, item, item)

        full = self.detail_by_key(summary, "programs")
        for key, location, source in ((win32_key, win32_location, "win32_programs"),
                                      (msix_key, msix_location, "msix_programs")):
            with self.subTest(item=key, place="detail"):
                self.assertIn(key, full, sorted(full))
                self.assertEqual(full[key].get("install_location"), location, full[key])
                self.assertEqual(full[key].get("source"), source, full[key])

    def test_autostart_fields(self):
        service_key = "service:InventedSlimAgent"
        run_key = "run:hkcu\\Run:InventedSlimTool"
        agent = "C:\\Invented\\Slim Agent\\agent.exe"
        tool = "%SystemRoot%\\Invented\\tool.exe"
        tool_expanded = "C:\\Windows\\Invented\\tool.exe"
        display_name = "Invented Slim Agent Service"
        summary = self.collect(FakePowerShell({
            "services": ok([service("InventedSlimAgent", f"\"{agent}\" -service",
                                    display_name=display_name)]),
            "run_keys": ok([run_value("InventedSlimTool", f"{tool} /tray",
                                      value_kind="ExpandString")]),
            "file_facts": facts(
                file_row(agent, signer=VENDOR, company=SLIM_COMPANY),
                file_row(tool, expanded=tool_expanded, signer=VENDOR, company=SLIM_COMPANY),
            ),
        }))

        listed = self.by_key(self.summary_items(summary, "autostart"))
        self.assertIn(service_key, listed, sorted(listed))
        self.assertIn(run_key, listed, sorted(listed))

        slim_service = listed[service_key]
        self.assertNotIn("display_name", slim_service, slim_service)
        slim_agent_fact = self.fact_by_path(slim_service, agent)
        self.assertNotIn("company", slim_agent_fact, slim_agent_fact)
        self.assertNotIn("expanded_path", slim_agent_fact, slim_agent_fact)

        slim_tool_fact = self.fact_by_path(listed[run_key], tool)
        self.assertNotIn("company", slim_tool_fact, slim_tool_fact)
        self.assertEqual(slim_tool_fact.get("expanded_path"), tool_expanded, slim_tool_fact)

        full = self.detail_by_key(summary, "autostart")
        self.assertIn(service_key, full, sorted(full))
        self.assertIn(run_key, full, sorted(full))
        self.assertEqual(full[service_key].get("display_name"), display_name, full[service_key])
        full_agent_fact = self.fact_by_path(full[service_key], agent)
        self.assertEqual(full_agent_fact.get("company"), SLIM_COMPANY, full_agent_fact)
        self.assertEqual(full_agent_fact.get("expanded_path"), agent, full_agent_fact)
        full_tool_fact = self.fact_by_path(full[run_key], tool)
        self.assertEqual(full_tool_fact.get("company"), SLIM_COMPANY, full_tool_fact)
        self.assertEqual(full_tool_fact.get("expanded_path"), tool_expanded, full_tool_fact)

    def test_slim_fields_no_false_changes(self):
        runs, services = 15, 15
        responses = {
            "win32_programs": ok(slim_program_rows(40)),
            "msix_programs": ok([]),
            **slim_autostart_responses(runs, services),
        }
        data_dir = self.data_dir()
        self.collect(FakePowerShell(responses), data_dir=data_dir, now=NOW)
        summary = self.collect(FakePowerShell(responses), data_dir=data_dir,
                               now=NOW + timedelta(days=1))

        # The slim summary lists are shorter than the same items taken whole.
        for name, count in (("programs", 40), ("autostart", runs + services)):
            with self.subTest(list=name):
                slim = self.summary_items(summary, name)
                self.assertEqual(len(slim), count, [item.get("key") for item in slim])
                full = self.detail_by_key(summary, name)
                whole = [full.get(item.get("key")) for item in slim]
                self.assertNotIn(None, whole, sorted(full))
                self.assertLess(len(json.dumps(slim)), len(json.dumps(whole)))

        # The comparison uses the full items: the same machine gives no change.
        self.assertEqual(summary.get("baseline", {}).get("status"), "compared",
                         summary.get("baseline"))
        comparison = self.comparison(summary)
        for name in ("win32_programs", "run_keys", "services"):
            self.assertEqual(comparison.get(name), "compared", comparison)
        self.assertEqual(self.changes(summary), [])

        # The baseline ush-processes reads keeps every field.
        state = data_dir / "state" / "ush-inventory.json"
        self.assertTrue(state.is_file(), f"{state} was not written")
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        sources = saved.get("sources")
        self.assertIsInstance(sources, dict, sorted(saved))

        programs = sources.get("win32_programs")
        self.assertIsInstance(programs, dict, sorted(sources))
        program = programs.get("win32:hklm64:InventedSlimApp07")
        self.assertIsInstance(program, dict, sorted(programs))
        self.assertEqual(program.get("install_location"),
                         slim_program_rows(40)[7]["InstallLocation"], program)

        saved_services = sources.get("services")
        self.assertIsInstance(saved_services, dict, sorted(sources))
        agent = saved_services.get("service:InventedSlimAgent03")
        self.assertIsInstance(agent, dict, sorted(saved_services))
        self.assertEqual(agent.get("display_name"),
                         "Invented Slim Agent Service Number 03", agent)
        agent_fact = self.fact_by_path(agent, slim_agent_target(3))
        self.assertEqual(agent_fact.get("company"), SLIM_COMPANY, agent_fact)
        self.assertEqual(agent_fact.get("expanded_path"), slim_agent_expanded(3), agent_fact)

        saved_runs = sources.get("run_keys")
        self.assertIsInstance(saved_runs, dict, sorted(sources))
        tray = saved_runs.get("run:hkcu\\Run:InventedSlimTray05")
        self.assertIsInstance(tray, dict, sorted(saved_runs))
        tray_fact = self.fact_by_path(tray, slim_tray_target(5))
        self.assertEqual(tray_fact.get("company"), SLIM_COMPANY, tray_fact)
        self.assertEqual(tray_fact.get("expanded_path"), slim_tray_target(5), tray_fact)


# --- Order of additions: items with a change block are cut last (plan 074, M1, K4-K5) -

def rule_value_name(group, i):
    return f"{{00000000-0000-0000-{group:04d}-{i:012d}}}"


def app_iso_rule(i):
    return fw_value(rule_value_name(1, i),
                    custom_rule(f"Invented App Rule {i:04d}", port=str(20000 + i),
                                app=f"C:\\Invented\\Store Rules\\App {i:04d}\\app.exe"))


def local_rule(i):
    return fw_value(rule_value_name(2, i),
                    custom_rule(f"Invented Kept Server {i}", port=str(30000 + i),
                                app=f"C:\\Invented\\Kept Server {i}\\server.exe"))


def policy_rule(i):
    return fw_value(rule_value_name(3, i),
                    custom_rule(f"Invented Policy Rule {i}", port=str(40000 + i),
                                app=f"C:\\Invented\\Policy Rules\\{i}\\app.exe"))


def rule_key(store, value):
    return f"firewall:{store}:{value['name']}"


class TestAdditionsOrder(InventoryTestCase):
    def addition_keys(self, items):
        self.assertIsInstance(items, list, f"additions: {type(items).__name__}")
        return [item.get("key") for item in items]

    def test_blockless_cut_first(self):
        machine_thumb = thumb(0xC001)
        enterprise_thumb = thumb(0xC002)
        app_iso = [app_iso_rule(i) for i in range(200)]
        local = [local_rule(i) for i in range(5)]
        code, stdout, stderr = self.run_main(self.data_dir(), FakePowerShell(m2_responses(
            win32_programs=ok(program_rows()), msix_programs=ok([]),
            firewall_rules=ok(firewall_result(local=local, app_iso=app_iso)),
            root_certificates=ok(certificates_result(
                machine_root=[cert(machine_thumb, subject="CN=Invented Machine Root")],
                enterprise=[cert(enterprise_thumb, subject="CN=Invented Enterprise Root")],
            )),
        )))
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = self.parse(stdout)

        self.assertEqual(summary.get("truncated"), PROGRAMS - PROGRAMS_MINIMUM,
                         summary.get("truncated"))
        self.assertEqual(len(summary.get("programs")), PROGRAMS_MINIMUM)
        truncated = summary.get("truncated_additions")
        self.assertIsInstance(truncated, int, truncated)
        self.assertGreater(truncated, 0)

        with_block = ([f"cert:machine_root:{machine_thumb}"]
                      + [rule_key("local", value) for value in local])
        without_block = ([f"cert:enterprise:{enterprise_thumb}"]
                         + [rule_key("app_iso", value) for value in app_iso])
        self.assertLess(truncated, len(without_block))

        kept = self.addition_keys(summary.get("additions"))
        for key in with_block:
            self.assertIn(key, kept)
        self.assertEqual(kept, with_block + without_block[:-truncated])

        detail_items = self.detail(summary).get("additions")
        self.addition_keys(detail_items)
        cut = sorted(
            (item for item in detail_items
             if item.get("own") is not True and item.get("key") not in kept),
            key=lambda item: id_number(item.get("id"), "x"),
        )
        self.assertEqual([item.get("key") for item in cut], without_block[-truncated:])

    def test_order_without_budget_pressure(self):
        admin_sid = "S-1-5-21-0-0-0-1005"
        machine_thumb = thumb(0xC101)
        enterprise_thumb = thumb(0xC102)
        local = local_rule(0)
        app_iso = app_iso_rule(0)
        policy = policy_rule(0)
        summary = self.collect(FakePowerShell(m2_responses(
            administrators=ok(admins_result([member(admin_sid, "EXAMPLE-PC\\invented.admin")])),
            defender_exclusions=ok(defender_result(path=["C:\\Invented\\Cache"])),
            root_certificates=ok(certificates_result(
                machine_root=[cert(machine_thumb, subject="CN=Invented Machine Root")],
                enterprise=[cert(enterprise_thumb, subject="CN=Invented Enterprise Root")],
            )),
            firewall_rules=ok(firewall_result(local=[local], app_iso=[app_iso],
                                              policy=[policy])),
            hosts=ok(hosts_result("0.0.0.0 ads.example\n")),
        )), admin=True)

        self.assertIs(summary.get("elevated"), True, summary.get("elevated"))
        self.assertEqual(self.addition_keys(summary.get("additions")), [
            f"admin:{admin_sid}",
            "defender:path:c:\\invented\\cache",
            f"cert:machine_root:{machine_thumb}",
            rule_key("local", local),
            "hosts:ads.example:0.0.0.0",
            f"cert:enterprise:{enterprise_thumb}",
            rule_key("app_iso", app_iso),
            rule_key("policy", policy),
        ])
        self.assertEqual(summary.get("truncated_additions"), 0,
                         summary.get("truncated_additions"))


# --- A minimum of 20 programs is kept before the other lists are cut -------------------

PROGRAMS_MINIMUM = 20
PRESSURE_DRIVERS = 500
PRESSURE_FEATURES = 100
PRESSURE_RULES = 1000

# K3: the drivers, components and additions that must be cut whole before the programs
# go below the minimum.
BELOW_MINIMUM_DRIVERS = 50
BELOW_MINIMUM_FEATURES = 50
BELOW_MINIMUM_RULES = 50
# K3: the autostart list is sized so that the summary without programs leaves room for
# about this many slim programs (fewer than PROGRAMS_MINIMUM, more than zero). The size of
# one slim autostart item and one slim program belongs to the code, so the number of
# autostart items is found by measuring the script's own output at run time (a binary
# search, see ``autostart_items_for_room``); with the slim items of plan 074 it lands at
# roughly 31-33k characters of autostart.
BELOW_MINIMUM_ROOM = 8
# K3: upper bound of the search; far more than the budget needs.
AUTOSTART_SEARCH_LIMIT = 600

# K6: an autostart list far over the budget on its own (500 items).
OVERSIZED_RUNS = 250
OVERSIZED_SERVICES = 250

# How the summary may be written on stdout; the one whose length matches is used to
# measure "one more program".
DUMP_STYLES = (
    {},
    {"indent": 2},
    {"indent": 1},
    {"indent": 4},
    {"separators": (",", ":")},
    {"ensure_ascii": False},
    {"indent": 2, "ensure_ascii": False},
    {"separators": (",", ":"), "ensure_ascii": False},
)


def budget_key(i):
    return f"win32:hklm64:InventedBudgetApp{i:04d}"


def newest_keys(count, total=PROGRAMS):
    """Keys of the ``count`` newest of programs 0..total-1 (program i is i days newer)."""
    return [budget_key(i) for i in range(total - 1, total - 1 - count, -1)]


def some_program_rows(indexes):
    """The rows of ``program_rows`` for program numbers in ``indexes`` (still shuffled)."""
    names = {f"InventedBudgetApp{i:04d}" for i in indexes}
    return [row for row in program_rows() if row["KeyName"] in names]


def autostart_split(items):
    """``items`` autostart entries as (Run values, services)."""
    return (items + 1) // 2, items // 2


class TestProgramsMinimum(InventoryTestCase):
    sized_run = TestBudget.sized_run
    listed = TestBudget.listed
    count = TestBudget.count

    def pressure_responses(self, rows):
        """``rows`` programs with drivers, components and additions over the budget."""
        return m2_responses(
            win32_programs=ok(rows), msix_programs=ok([]),
            drivers=ok(third_party_driver_rows(PRESSURE_DRIVERS)),
            optional_features=ok(feature_rows(PRESSURE_FEATURES)),
            firewall_rules=ok(firewall_rows(PRESSURE_RULES)),
        )

    def summary_dumps(self, stdout, summary):
        """The json.dumps style that reproduces the length of the printed summary."""
        printed = len(stdout.strip())
        for style in DUMP_STYLES:
            if len(json.dumps(summary, **style)) == printed:
                return lambda data, style=style: json.dumps(data, **style)
        self.fail(f"no json.dumps style reproduces the printed summary ({printed} chars)")

    def assert_next_program_overflows(self, stdout, summary, detail):
        """Adding the next program from the detail file would break the budget.

        The next program is the one right after the kept ones in the detail list (same
        order). It is reduced to the fields the kept summary items carry (its slim form),
        appended to the summary's ``programs`` with ``truncated`` lowered by one, and the
        summary is written again in the style that reproduces the printed length.
        """
        kept = self.listed(summary, "programs")
        everything = self.listed(detail, "programs")
        self.assertTrue(kept, "no program kept to take the slim fields from")
        self.assertLess(len(kept), len(everything))
        following = everything[len(kept)]
        slim = {field: following[field] for field in kept[0] if field in following}
        grown = dict(summary, programs=kept + [slim],
                     truncated=self.count(summary, "truncated") - 1)
        dumps = self.summary_dumps(stdout, summary)
        self.assertGreater(len(dumps(grown)), BUDGET,
                           f"program {following.get('key')} would still fit")

    def assert_kept_are_first(self, summary, detail, total=PROGRAMS):
        kept = self.listed(summary, "programs")
        everything = self.listed(detail, "programs")
        self.assertEqual([item.get("key") for item in kept], newest_keys(len(kept), total))
        self.assertEqual([item.get("id") for item in kept],
                         [item.get("id") for item in everything[:len(kept)]])
        self.assertEqual([item.get("key") for item in kept],
                         [item.get("key") for item in everything[:len(kept)]])
        return kept

    def printed_length(self, responses):
        code, stdout, stderr = self.run_main(self.data_dir(), FakePowerShell(responses))
        self.assertEqual(code, 0, stderr[:300])
        return len(stdout.strip())

    def autostart_items_for_room(self, programs_room):
        """The largest autostart size whose summary leaves ``programs_room`` slim programs.

        Measured on the script's own output: the summary with no program and no other
        list, and the growth of the summary per slim program (ten newest programs).
        """
        bare = {"win32_programs": ok([]), "msix_programs": ok([])}
        empty = self.printed_length(bare)
        ten = self.printed_length(dict(
            bare, win32_programs=ok(some_program_rows(range(PROGRAMS - 10, PROGRAMS)))))
        per_program = (ten - empty) / 10
        self.assertGreater(per_program, 0)
        target = BUDGET - programs_room * per_program

        def fits(items):
            return self.printed_length(
                dict(bare, **slim_autostart_responses(*autostart_split(items)))) <= target

        low, high = 0, AUTOSTART_SEARCH_LIMIT
        self.assertTrue(fits(low), "the bare summary leaves no room")
        self.assertFalse(fits(high), "the autostart search limit is too small")
        while high - low > 1:
            middle = (low + high) // 2
            if fits(middle):
                low = middle
            else:
                high = middle
        return low

    def test_minimum_kept_before_other_lists(self):
        summary, detail = self.sized_run(
            self.data_dir(), FakePowerShell(self.pressure_responses(program_rows())), now=NOW)

        kept = self.assert_kept_are_first(summary, detail)
        self.assertEqual(len(kept), PROGRAMS_MINIMUM)
        self.assertEqual(self.count(summary, "truncated"), PROGRAMS - PROGRAMS_MINIMUM)
        self.assertEqual(len(self.listed(detail, "programs")), PROGRAMS)

        truncated_drivers = self.count(summary, "truncated_drivers")
        self.assertGreater(truncated_drivers, 0)
        self.assertEqual(len(self.listed(summary, "drivers")) + truncated_drivers,
                         PRESSURE_DRIVERS)

    def test_programs_above_minimum_when_room(self):
        data_dir = self.data_dir()
        code, stdout, stderr = self.run_main(
            data_dir, FakePowerShell({"win32_programs": ok(program_rows()),
                                      "msix_programs": ok([])}))
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = self.parse(stdout)
        detail = self.detail(summary)

        kept = self.assert_kept_are_first(summary, detail)
        self.assertGreater(len(kept), PROGRAMS_MINIMUM)
        self.assertEqual(len(kept) + self.count(summary, "truncated"), PROGRAMS)
        for name in ("truncated_drivers", "truncated_components", "truncated_additions"):
            self.assertEqual(self.count(summary, name), 0, name)
        self.assert_next_program_overflows(stdout, summary, detail)

    def test_below_minimum_only_after_other_lists(self):
        items = self.autostart_items_for_room(BELOW_MINIMUM_ROOM)
        runs, services = autostart_split(items)
        responses = m2_responses(
            win32_programs=ok(program_rows()), msix_programs=ok([]),
            drivers=ok(third_party_driver_rows(BELOW_MINIMUM_DRIVERS)),
            optional_features=ok(feature_rows(BELOW_MINIMUM_FEATURES)),
            firewall_rules=ok(firewall_rows(BELOW_MINIMUM_RULES)),
            **slim_autostart_responses(runs, services),
        )
        code, stdout, stderr = self.run_main(self.data_dir(), FakePowerShell(responses))
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = self.parse(stdout)
        detail = self.detail(summary)

        self.assertEqual(len(self.listed(summary, "autostart")), items)
        for name, whole, cut in (("drivers", BELOW_MINIMUM_DRIVERS, "truncated_drivers"),
                                 ("components", BELOW_MINIMUM_FEATURES,
                                  "truncated_components"),
                                 ("additions", BELOW_MINIMUM_RULES, "truncated_additions")):
            with self.subTest(list=name):
                self.assertEqual(self.count(summary, cut), whole)
                self.assertEqual(self.listed(summary, name), [])

        kept = self.assert_kept_are_first(summary, detail)
        self.assertGreater(len(kept), 0)
        self.assertLess(len(kept), PROGRAMS_MINIMUM)
        self.assertEqual(len(kept) + self.count(summary, "truncated"), PROGRAMS)
        self.assert_next_program_overflows(stdout, summary, detail)

    def test_few_programs_kept_whole(self):
        few = 5
        summary, detail = self.sized_run(
            self.data_dir(),
            FakePowerShell(self.pressure_responses(some_program_rows(range(few)))),
            now=NOW,
        )

        kept = self.assert_kept_are_first(summary, detail, total=few)
        self.assertEqual(len(kept), few)
        self.assertEqual(self.count(summary, "truncated"), 0)
        truncated_drivers = self.count(summary, "truncated_drivers")
        self.assertGreater(truncated_drivers, 0)
        self.assertEqual(len(self.listed(summary, "drivers")) + truncated_drivers,
                         PRESSURE_DRIVERS)

    def test_no_cut_without_pressure(self):
        programs, drivers, features, rules = 10, 3, 3, 2
        summary, _detail = self.sized_run(
            self.data_dir(),
            FakePowerShell(m2_responses(
                win32_programs=ok(some_program_rows(range(programs))), msix_programs=ok([]),
                drivers=ok(third_party_driver_rows(drivers)),
                optional_features=ok(feature_rows(features)),
                firewall_rules=ok(firewall_rows(rules)),
            )),
            now=NOW,
        )

        for name in ("truncated", "truncated_drivers", "truncated_components",
                     "truncated_additions"):
            self.assertEqual(self.count(summary, name), 0, name)
        self.assertEqual([item.get("key") for item in self.listed(summary, "programs")],
                         newest_keys(programs, total=programs))
        self.assertEqual(len(self.listed(summary, "drivers")), drivers)
        self.assertEqual({item.get("key") for item in self.listed(summary, "components")},
                         {feature_key(i) for i in range(features)})
        self.assertEqual(len(self.listed(summary, "additions")), rules)
        self.assertNotIn("summary budget",
                         [item.get("what") for item in self.not_checked(summary)])

    def test_autostart_alone_over_budget_is_cut(self):
        # Plan 010 M1: autostart over the budget on its own is cut with per-kind counts
        # (it was never cut before, and the summary went out over the budget).
        programs, drivers, features, rules = 30, 5, 5, 3
        responses = m2_responses(
            win32_programs=ok(some_program_rows(range(programs))), msix_programs=ok([]),
            drivers=ok(third_party_driver_rows(drivers)),
            optional_features=ok(feature_rows(features)),
            firewall_rules=ok(firewall_rows(rules)),
            **slim_autostart_responses(OVERSIZED_RUNS, OVERSIZED_SERVICES),
        )
        code, stdout, stderr = self.run_main(self.data_dir(), FakePowerShell(responses))
        self.assertEqual(code, 0, stderr[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = self.parse(stdout)

        autostart = self.listed(summary, "autostart")
        cut = self.count(summary, "truncated_autostart")
        self.assertGreater(cut, 0)
        self.assertEqual(len(autostart) + cut, OVERSIZED_RUNS + OVERSIZED_SERVICES)
        self.assertEqual(sum(summary["autostart_counts"].values()),
                         OVERSIZED_RUNS + OVERSIZED_SERVICES)
        # Programs go down to their minimum first; the short lists are kept whole.
        self.assertEqual(self.count(summary, "truncated"), programs - 20)
        for name in ("truncated_drivers", "truncated_components", "truncated_additions"):
            self.assertEqual(self.count(summary, name), 0, name)
        self.assertEqual(len(self.listed(summary, "drivers")), drivers)
        self.assertEqual(len(self.listed(summary, "components")), features)
        self.assertEqual(len(self.listed(summary, "additions")), rules)
        self.assertNotIn("summary budget",
                         [item.get("what") for item in self.not_checked(summary)])


# --- Collapsed ms-resource changes; autostart and changes cut with counts (plan 010, M1) -

MS_RESOURCE_RULES = 200
MS_RESOURCE_NAME = "ms-resource:ProductPkgDisplayName"
LARGE_RUNS = 1500
LARGE_SERVICES = 1500
CHANGE_TYPES = ("added", "removed", "changed")
# Wordings pinned in skills/ush-inventory/references/report-format.md (Polish, escaped
# so this file stays ASCII).
COLLAPSED_WORDING = "<N> zmian `ms-resource:` zwini\u0119tych w jedn\u0105 lini\u0119"
REST_IN_DETAIL_WORDING = "pozosta\u0142e w pliku szczeg\u00f3\u0142\u00f3w"


def ms_resource_rule(i):
    """An invented rule named like an unresolved Store resource; not built in."""
    return fw_value(rule_value_name(5, i),
                    custom_rule(MS_RESOURCE_NAME, port=str(50000 + i),
                                app=f"C:\\Invented\\Resource Apps\\App {i:03d}\\app.exe"))


def slim_run_key(i):
    return f"run:hkcu\\Run:InventedSlimTray{i:02d}"


def slim_service_key(i):
    return f"service:InventedSlimAgent{i:02d}"


class TestCollapsedChanges(InventoryTestCase):
    sized_run = TestBudget.sized_run
    listed = TestBudget.listed
    count = TestBudget.count

    def run_pair(self, before, after):
        """Two runs on one data dir; return (summary, detail) of the second."""
        data_dir = self.data_dir()
        code, _stdout, stderr = self.run_main(data_dir, FakePowerShell(before), now=NOW)
        self.assertEqual(code, 0, stderr[:300])
        return self.sized_run(data_dir, FakePowerShell(after), now=NOW + timedelta(days=1))

    def ids_and_keys(self, items):
        return [(item.get("id"), item.get("key")) for item in items]

    def budget_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if item.get("what") == "summary budget"]

    def test_ms_resource_changes_collapse(self):
        rules = [ms_resource_rule(i) for i in range(MS_RESOURCE_RULES)]
        summary, detail = self.run_pair(
            m2_responses(),
            m2_responses(firewall_rules=ok(firewall_result(local=rules))),
        )

        changes = self.listed(summary, "changes")
        firewall = [c for c in changes
                    if isinstance(c, dict) and c.get("source") == "firewall_rules"]
        self.assertEqual(len(firewall), 1, firewall[:5])
        collapsed = firewall[0]
        self.assertEqual(collapsed.get("collapsed"), "ms-resource", collapsed)
        self.assertEqual(collapsed.get("change"), "added", collapsed)
        self.assertEqual(collapsed.get("count"), MS_RESOURCE_RULES, collapsed)
        self.assertNotIn("id", collapsed, collapsed)
        # Nothing is cut, so only this count lets the report checker know the
        # collapsed changes' ids.
        self.assertEqual(self.count(summary, "truncated_changes"), 0)
        self.assertEqual(self.count(summary, "collapsed_changes"), MS_RESOURCE_RULES)

        detail_firewall = [c for c in self.listed(detail, "changes")
                           if isinstance(c, dict) and c.get("source") == "firewall_rules"]
        self.assertEqual(len(detail_firewall), MS_RESOURCE_RULES)
        self.assertEqual({c.get("key") for c in detail_firewall},
                         {rule_key("local", value) for value in rules})
        for change in detail_firewall:
            self.assertNotIn("collapsed", change, change)
            self.assertEqual(change.get("change"), "added", change)
        ids = [id_number(c.get("id"), "c") for c in detail_firewall]
        self.assertEqual(len(set(ids)), MS_RESOURCE_RULES, ids)

    def test_collapsed_change_kept_when_plain_changes_cut(self):
        # Firewall changes come late in the change order; the collapsed entry
        # must still be kept while plain changes are cut.
        rules = [ms_resource_rule(i) for i in range(MS_RESOURCE_RULES)]
        summary, _detail = self.run_pair(
            {**slim_autostart_responses(0, 0), **m2_responses()},
            {**slim_autostart_responses(LARGE_RUNS, LARGE_SERVICES),
             **m2_responses(firewall_rules=ok(firewall_result(local=rules)))},
        )

        changes = self.listed(summary, "changes")
        collapsed = [c for c in changes if isinstance(c, dict) and "collapsed" in c]
        self.assertEqual(len(collapsed), 1, changes[:5])
        self.assertEqual(collapsed[0].get("count"), MS_RESOURCE_RULES, collapsed)
        cut = self.count(summary, "truncated_changes")
        self.assertGreater(cut, 0)
        listed = sum(c["count"] if "collapsed" in c else 1 for c in changes)
        self.assertEqual(listed + cut, LARGE_RUNS + LARGE_SERVICES + MS_RESOURCE_RULES)
        self.assertEqual(self.budget_notes(summary), [])

    def test_large_autostart_and_changes_fit(self):
        summary, detail = self.run_pair(
            slim_autostart_responses(0, 0),
            slim_autostart_responses(LARGE_RUNS, LARGE_SERVICES),
        )
        total = LARGE_RUNS + LARGE_SERVICES
        expected_keys = ({slim_run_key(i) for i in range(LARGE_RUNS)}
                         | {slim_service_key(i) for i in range(LARGE_SERVICES)})

        # The detail file keeps every item.
        detail_autostart = self.listed(detail, "autostart")
        self.assertEqual({item.get("key") for item in detail_autostart}, expected_keys)
        self.assertEqual(len(detail_autostart), total)
        self.assertEqual([item for item in detail_autostart if item.get("own") is True], [])
        detail_changes = self.listed(detail, "changes")
        self.assertEqual({c.get("key") for c in detail_changes}, expected_keys)
        self.assertEqual(len(detail_changes), total)
        for change in detail_changes:
            self.assertEqual(change.get("change"), "added", change)

        # autostart: a prefix of the detail list, the rest counted.
        truncated_autostart = self.count(summary, "truncated_autostart")
        self.assertGreater(truncated_autostart, 0)
        kept_autostart = self.listed(summary, "autostart")
        self.assertEqual(len(kept_autostart) + truncated_autostart, total)
        self.assertEqual(self.ids_and_keys(kept_autostart),
                         self.ids_and_keys(detail_autostart[:len(kept_autostart)]))
        kinds = {}
        for item in detail_autostart:
            kinds[item.get("kind")] = kinds.get(item.get("kind"), 0) + 1
        autostart_counts = summary.get("autostart_counts")
        self.assertIsInstance(autostart_counts, dict, autostart_counts)
        self.assertEqual(autostart_counts, kinds)
        self.assertEqual(sum(autostart_counts.values()), total)

        # changes: a prefix of the detail list, the rest counted per source and type.
        truncated_changes = self.count(summary, "truncated_changes")
        self.assertGreater(truncated_changes, 0)
        kept_changes = self.listed(summary, "changes")
        self.assertEqual(len(kept_changes) + truncated_changes, total)
        self.assertEqual(self.ids_and_keys(kept_changes),
                         self.ids_and_keys(detail_changes[:len(kept_changes)]))
        expected_counts = {}
        for change in detail_changes:
            per_type = expected_counts.setdefault(
                change.get("source"), dict.fromkeys(CHANGE_TYPES, 0))
            per_type[change.get("change")] += 1
        change_counts = summary.get("change_counts")
        self.assertIsInstance(change_counts, dict, change_counts)
        self.assertEqual(change_counts, expected_counts)
        self.assertEqual(sum(sum(per_type.values()) for per_type in change_counts.values()),
                         total)

        self.assertEqual(self.budget_notes(summary), [])

    def test_small_summary_unchanged(self):
        kept_rule, new_rule = local_rule(0), local_rule(1)
        summary, detail = self.run_pair(
            m2_responses(firewall_rules=ok(firewall_result(local=[kept_rule])),
                         **slim_autostart_responses(1, 1)),
            m2_responses(firewall_rules=ok(firewall_result(local=[kept_rule, new_rule])),
                         **slim_autostart_responses(2, 1)),
        )

        changes = self.listed(summary, "changes")
        self.assertEqual([c for c in changes if isinstance(c, dict) and "collapsed" in c], [])
        detail_changes = self.listed(detail, "changes")
        self.assertEqual(self.ids_and_keys(changes), self.ids_and_keys(detail_changes))

        new_key = rule_key("local", new_rule)
        firewall = [c for c in changes if c.get("key") == new_key]
        self.assertEqual(len(firewall), 1, changes)
        self.assertEqual(firewall[0].get("source"), "firewall_rules", firewall[0])
        self.assertEqual(firewall[0].get("change"), "added", firewall[0])
        id_number(firewall[0].get("id"), "c")
        self.assertIn(slim_run_key(1), [c.get("key") for c in changes], changes)

        self.assertEqual(len(self.listed(summary, "autostart")),
                         len(self.listed(detail, "autostart")))
        self.assertEqual(self.count(summary, "truncated_autostart"), 0)
        self.assertEqual(self.count(summary, "truncated_changes"), 0)
        self.assertEqual(self.count(summary, "collapsed_changes"), 0)
        for name in ("autostart_counts", "change_counts"):
            self.assertIn(name, summary, sorted(summary))
            self.assertIsNone(summary.get(name), name)
        self.assertEqual(self.budget_notes(summary), [])

    def test_format_pins_collapsed_wording(self):
        path = REPO_ROOT / "skills" / "ush-inventory" / "references" / "report-format.md"
        text = " ".join(path.read_text(encoding="utf-8").split())
        self.assertIn(COLLAPSED_WORDING, text)
        self.assertIn(REST_IN_DETAIL_WORDING, text)


# --- fit_budget on its own; the collapse rule file (plan 010, M1 review round 1) -----

SIX_LISTS = ("programs", "drivers", "components", "additions", "autostart", "changes")
COUNT_NAMES = {"programs": "truncated", "drivers": "truncated_drivers",
               "components": "truncated_components", "additions": "truncated_additions",
               "autostart": "truncated_autostart", "changes": "truncated_changes",
               "driver_packages": "truncated_driver_packages"}


def budget_summary(sizes, pad=""):
    """An invented summary with the six lists of ``sizes`` and one text of ``pad``."""
    summary = {"pad": pad, "not_checked": []}
    for name in SIX_LISTS:
        items = []
        for i in range(sizes.get(name, 0)):
            item = {"id": f"x{i}", "name": f"Invented {name} item {i:04d}"}
            if name == "autostart":
                item["kind"] = "run"
            if name == "changes":
                item.update(source="run_keys", change="added")
            items.append(item)
        summary[name] = items
        summary[COUNT_NAMES[name]] = 0
    summary["autostart_counts"] = None
    summary["change_counts"] = None
    return summary


BUDGET_SIZES = {"programs": 40, "drivers": 15, "components": 15, "additions": 15,
                "autostart": 40, "changes": 40}


class TestFitBudgetFallback(InventoryTestCase):
    SIZES = BUDGET_SIZES

    def fit(self, summary, budget):
        with mock.patch.object(self.inventory, "SUMMARY_MAX_CHARS", budget):
            return self.inventory.fit_budget(summary)

    def what(self, summary):
        return [item.get("what") for item in summary["not_checked"]]

    def test_nothing_fits_cuts_nothing(self):
        summary = budget_summary(self.SIZES, pad="x" * 5000)
        self.fit(summary, 1000)
        for name in SIX_LISTS:
            self.assertEqual(len(summary[name]), self.SIZES[name], name)
            self.assertEqual(summary[COUNT_NAMES[name]], 0, name)
        self.assertIsNone(summary["autostart_counts"])
        self.assertIsNone(summary["change_counts"])
        self.assertIn("summary budget", self.what(summary))

    def test_fits_only_with_all_six_lists_empty(self):
        empty = budget_summary({}, pad="x" * 2000)
        empty["autostart_counts"] = {"run": self.SIZES["autostart"]}
        empty["change_counts"] = {"run_keys": {"added": self.SIZES["changes"],
                                               "removed": 0, "changed": 0}}
        for name in SIX_LISTS:
            empty[COUNT_NAMES[name]] = self.SIZES[name]
        budget = len(self.inventory.dump(empty)) + 5
        summary = budget_summary(self.SIZES, pad="x" * 2000)
        text = self.fit(summary, budget)
        self.assertLessEqual(len(text), budget)
        for name in SIX_LISTS:
            self.assertEqual(summary[name], [], name)
            self.assertEqual(summary[COUNT_NAMES[name]], self.SIZES[name], name)
        self.assertNotIn("summary budget", self.what(summary))

    def test_cut_collapsed_entry_counts_its_changes(self):
        summary = budget_summary({"changes": 30})
        summary["changes"].append({"collapsed": "ms-resource", "source": "firewall_rules",
                                   "change": "added", "count": 200})
        budget = len(self.inventory.dump(summary)) - 10
        self.fit(summary, budget)
        kept = summary["changes"]
        self.assertFalse(any("collapsed" in entry for entry in kept), kept[-1:])
        self.assertEqual(len(kept) + summary["truncated_changes"], 30 + 200)
        total = sum(sum(by.values()) for by in summary["change_counts"].values())
        self.assertEqual(total, 30 + 200)


class TestCollapseRules(InventoryTestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collapsed_names.json"
            if text is not None:
                path.write_text(text, encoding="utf-8")
            return self.inventory.load_collapsed(path)

    def test_shipped_file_collapses_ms_resource_firewall_rules(self):
        rules, reason = self.inventory.load_collapsed(self.inventory.COLLAPSED_NAMES_FILE)
        self.assertIsNone(reason)
        self.assertIn({"source": "firewall_rules", "collapsed": "ms-resource",
                       "prefix": "ms-resource:"}, rules)

    def test_unusable_file_gives_a_reason(self):
        for label, text in (("missing", None), ("not json", "{"), ("not a list", "{}"),
                            ("empty prefix", '[{"source": "s", "collapsed": "c", "prefix": ""}]')):
            with self.subTest(label):
                rules, reason = self.load(text)
                self.assertIsNone(rules)
                self.assertIn("collapsed_names.json", reason)

    def test_clean_changes_stay_listed(self):
        rules = [{"source": "firewall_rules", "collapsed": "ms-resource",
                  "prefix": "ms-resource:"}]
        changes = [{"id": "c1", "source": "firewall_rules", "change": "added",
                    "name": "Invented Game Server"},
                   {"id": "c2", "source": "run_keys", "change": "added",
                    "name": "ms-resource:InventedNotAFirewallRule"},
                   {"id": "c3", "source": "firewall_rules", "change": "changed",
                    "name": None}]
        self.assertEqual(self.inventory.collapse_changes(changes, rules), changes)

    def test_unusable_file_collapses_nothing_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "collapsed_names.json"
            with mock.patch.object(self.inventory, "COLLAPSED_NAMES_FILE", missing):
                responses = m2_responses(firewall_rules=ok(firewall_rows(2)))
                code, stdout, stderr = self.run_main(self.data_dir(),
                                                     FakePowerShell(responses))
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIn("collapsed_names.json",
                      [item.get("what") for item in summary["not_checked"]])


# --- Drivers keep their short list before components are cut (plan 107) --------------
#
# Stage order of the first pass, each stage stopping as soon as the summary fits:
# programs->20, drivers->10, components->10, components->0, drivers->0, additions->10,
# additions->0, programs->0. Fallback (autostart/changes too long on their own): the four
# short lists at their minimums, autostart and changes to their floors, then to 0, then
# components->0, drivers->0, additions->0, programs->0.
#
# Each case is sized against the real SUMMARY_MAX_CHARS: the expected end state is built
# by hand, a ``leftovers`` list (never cut) fills it up to FLOOR_GAP characters below the
# budget, and every item of the list cut last is longer than FLOOR_GAP, so one more item
# of it would not fit.

FLOOR_GAP = 30
FLOOR_DRIVER_PAD = 220
FLOOR_COMPONENT_PAD = 80
FLOOR_ADDITION_PAD = 80
FLOOR_PROGRAM_PAD = 80
FLOOR_AUTOSTART_PAD = 300
LEFTOVER_CHUNK = 1000


def floor_items(name, count, pad):
    """``count`` invented items of one list, all of the same length."""
    items = []
    for i in range(count):
        item = {"id": f"{name[0]}{i:03d}",
                "name": f"Invented floor {name} item {i:03d} " + "n" * pad}
        if name == "autostart":
            item["kind"] = "run"
        if name == "changes":
            item.update(source="run_keys", change="added")
        items.append(item)
    return items


def floor_summary(lists):
    """An invented summary holding ``lists`` (name -> items), nothing cut yet."""
    summary = {"leftovers": [], "not_checked": [],
               "autostart_counts": None, "change_counts": None}
    for name in SIX_LISTS:
        summary[name] = list(lists.get(name, []))
        summary[COUNT_NAMES[name]] = 0
    return summary


def cut_state(summary, kept):
    """A copy of ``summary`` with each list in ``kept`` (name -> number) cut to a prefix."""
    state = json.loads(json.dumps(summary))
    for name, number in kept.items():
        whole = len(summary[name])
        state[name] = summary[name][:number]
        state[COUNT_NAMES[name]] = whole - number
    if "autostart" in kept and kept["autostart"] < len(summary["autostart"]):
        state["autostart_counts"] = {"run": len(summary["autostart"])}
    if "changes" in kept and kept["changes"] < len(summary["changes"]):
        state["change_counts"] = {"run_keys": {"added": len(summary["changes"]),
                                               "removed": 0, "changed": 0}}
    return state


class TestDriverFloor(InventoryTestCase):
    listed = TestBudget.listed
    count = TestBudget.count

    def size(self, summary):
        return len(self.inventory.dump(summary))

    def budget(self):
        return self.inventory.SUMMARY_MAX_CHARS

    def fill(self, state, target):
        """Set ``state["leftovers"]`` so that the dumped ``state`` is ``target`` long."""
        state["leftovers"] = []
        room = target - self.size(state)
        self.assertGreater(room, 2 * LEFTOVER_CHUNK, "the end state leaves no room to fill")
        state["leftovers"] = ["x" * LEFTOVER_CHUNK] * (room // (LEFTOVER_CHUNK + 100)) + [""]
        rest = target - self.size(state)
        self.assertGreaterEqual(rest, 0)
        state["leftovers"][-1] = "x" * rest
        self.assertEqual(self.size(state), target)
        return state["leftovers"]

    def sized_case(self, summary, end, one_more):
        """Fill ``summary`` so that the ``end`` cut fits and the ``one_more`` cut does not."""
        budget = self.budget()
        leftovers = self.fill(cut_state(summary, end), budget - FLOOR_GAP)
        summary["leftovers"] = leftovers
        over = cut_state(summary, one_more)
        self.assertGreater(self.size(over), budget, "fixture: one more item would still fit")
        self.assertGreater(self.size(summary), budget, "fixture: the summary already fits")
        return summary

    def fit(self, summary):
        text = self.inventory.fit_budget(summary)
        self.assertLessEqual(len(text), self.budget())
        return text

    def test_drivers_keep_minimum_before_components(self):
        drivers_min = self.inventory.DRIVERS_MIN
        drivers = floor_items("drivers", 64, FLOOR_DRIVER_PAD)
        components = floor_items("components", 40, FLOOR_COMPONENT_PAD)
        additions = floor_items("additions", 40, FLOOR_ADDITION_PAD)
        summary = self.sized_case(
            floor_summary({"drivers": drivers, "components": components,
                           "additions": additions}),
            end={"drivers": drivers_min, "components": 0},
            one_more={"drivers": drivers_min, "components": 1},
        )

        self.fit(summary)

        self.assertEqual(self.listed(summary, "components"), [])
        self.assertEqual(self.count(summary, "truncated_components"), 40)
        self.assertEqual(len(self.listed(summary, "drivers")), drivers_min)
        self.assertEqual(self.count(summary, "truncated_drivers"), 64 - drivers_min)
        self.assertEqual(self.count(summary, "truncated_drivers"), 54)
        self.assertEqual(self.listed(summary, "additions"), additions)
        self.assertEqual(self.count(summary, "truncated_additions"), 0)

    def test_fitting_summary_keeps_all_drivers(self):
        drivers = floor_items("drivers", 64, FLOOR_DRIVER_PAD)
        summary = floor_summary({
            "drivers": drivers,
            "components": floor_items("components", 40, FLOOR_COMPONENT_PAD),
            "additions": floor_items("additions", 40, FLOOR_ADDITION_PAD),
        })
        self.assertLess(self.size(summary), self.budget(), "fixture: summary over budget")

        self.fit(summary)

        self.assertEqual(self.listed(summary, "drivers"), drivers)
        self.assertEqual(self.count(summary, "truncated_drivers"), 0)

    def test_additions_kept_while_drivers_cut(self):
        drivers_min = self.inventory.DRIVERS_MIN
        kept_drivers = 4
        self.assertLess(kept_drivers, drivers_min)
        drivers = floor_items("drivers", 30, FLOOR_DRIVER_PAD)
        components = floor_items("components", 40, FLOOR_COMPONENT_PAD)
        additions = floor_items("additions", 40, FLOOR_ADDITION_PAD)
        summary = self.sized_case(
            floor_summary({"drivers": drivers, "components": components,
                           "additions": additions}),
            end={"drivers": kept_drivers, "components": 0},
            one_more={"drivers": kept_drivers + 1, "components": 0},
        )

        self.fit(summary)

        kept = self.listed(summary, "drivers")
        self.assertLess(len(kept), drivers_min)
        self.assertEqual(len(kept) + self.count(summary, "truncated_drivers"), 30)
        self.assertEqual(self.listed(summary, "components"), [])
        self.assertEqual(self.count(summary, "truncated_components"), 40)
        self.assertEqual(self.listed(summary, "additions"), additions)
        self.assertEqual(self.count(summary, "truncated_additions"), 0)

    def test_drivers_zero_only_after_autostart_and_changes(self):
        inv = self.inventory
        lists = {
            "programs": floor_items("programs", 40, FLOOR_PROGRAM_PAD),
            "drivers": floor_items("drivers", 30, FLOOR_DRIVER_PAD),
            "components": floor_items("components", 30, FLOOR_COMPONENT_PAD),
            "additions": floor_items("additions", 30, FLOOR_ADDITION_PAD),
            "autostart": floor_items("autostart", 40, FLOOR_AUTOSTART_PAD),
            "changes": floor_items("changes", 40, FLOOR_AUTOSTART_PAD),
        }
        end = {"programs": inv.PROGRAMS_MIN, "drivers": 0, "components": 0,
               "additions": inv.ADDITIONS_MIN, "autostart": 0, "changes": 0}
        summary = self.sized_case(floor_summary(lists), end=end,
                                  one_more=dict(end, drivers=1))
        # The first pass alone (all four short lists at 0) does not fit: autostart and
        # changes are too long on their own, so the fallback decides.
        first_pass_end = cut_state(summary, {"programs": 0, "drivers": 0, "components": 0,
                                             "additions": 0})
        self.assertGreater(self.size(first_pass_end), self.budget(),
                           "fixture: the first pass would fit")

        self.fit(summary)

        self.assertEqual(self.listed(summary, "drivers"), [])
        self.assertEqual(self.count(summary, "truncated_drivers"), len(lists["drivers"]))
        self.assertEqual(self.listed(summary, "autostart"), [])
        self.assertEqual(self.count(summary, "truncated_autostart"), len(lists["autostart"]))
        self.assertEqual(self.listed(summary, "changes"), [])
        self.assertEqual(self.count(summary, "truncated_changes"), len(lists["changes"]))


# --- Driver packages are cut to the budget (plan 024 QA, architect 2026-11-06) ---------
#
# First pass: programs->20, driver_packages->10, drivers->10, components->10,
# components->0, drivers->0, driver_packages->0, additions->10, additions->0, programs->0.
# A long package list must not push the listed drivers below their minimum while
# autostart, changes and additions fit. The sizes are invented.

LONG_AUTOSTART_PAD = 120
LONG_CHANGES_PAD = 120
LONG_ADDITIONS = 12
LONG_PACKAGES = 50


def package_items(count):
    """``count`` invented orphan driver packages with every summary field."""
    return [{
        "id": f"o{i}",
        "key": f"package:inventedpkg{i:03d}.inf:1.{i}.0.0",
        "published_name": f"oem{i + 100}.inf",
        "original_name": f"inventedpkg{i:03d}.inf",
        "provider": "Invented Hardware Vendor of Example Devices Ltd",
        "class": "Extension",
        "version": f"1.{i}.0.0",
        "date": "2024-03-04",
        "signer": "Invented Hardware Compatibility Publisher",
        "present_device": False,
    } for i in range(count)]


def package_summary(lists, packages):
    """``floor_summary`` with ``driver_packages`` (a list or None) and its count key."""
    summary = floor_summary(lists)
    summary["driver_packages"] = packages
    summary["truncated_driver_packages"] = 0
    return summary


class TestDriverPackagesCut(InventoryTestCase):
    listed = TestBudget.listed
    count = TestBudget.count
    size = TestDriverFloor.size
    budget = TestDriverFloor.budget
    fill = TestDriverFloor.fill
    sized_case = TestDriverFloor.sized_case
    fit = TestDriverFloor.fit

    def long_package_lists(self):
        return {
            "programs": floor_items("programs", 30, FLOOR_PROGRAM_PAD),
            "drivers": floor_items("drivers", 48, FLOOR_DRIVER_PAD),
            "components": floor_items("components", 11, FLOOR_COMPONENT_PAD),
            "additions": floor_items("additions", LONG_ADDITIONS, FLOOR_ADDITION_PAD),
            "autostart": floor_items("autostart", 30, LONG_AUTOSTART_PAD),
            "changes": floor_items("changes", 9, LONG_CHANGES_PAD),
        }

    def test_packages_cut_before_drivers_go_below_minimum(self):
        inv = self.inventory
        lists = self.long_package_lists()
        packages = package_items(LONG_PACKAGES)
        self.assertGreater(len(inv.dump(packages)), 15000, "fixture: packages too short")
        # Sized so that the old order (packages never cut) ends with drivers [] and
        # components []: one driver more would not fit.
        end = {"programs": inv.PROGRAMS_MIN, "drivers": 0, "components": 0}
        summary = self.sized_case(package_summary(lists, packages), end=end,
                                  one_more=dict(end, drivers=1))

        self.fit(summary)

        held = self.listed(summary, "driver_packages")
        self.assertGreater(len(held), 0)
        self.assertLess(len(held), LONG_PACKAGES)
        self.assertEqual(held, packages[:len(held)])
        self.assertEqual(self.count(summary, "truncated_driver_packages"),
                         LONG_PACKAGES - len(held))
        # Packages reach their floor before drivers are cut at all: with the reverse
        # order the drivers would stop at exactly DRIVERS_MIN and packages above theirs.
        self.assertEqual(len(held), inv.DRIVER_PACKAGES_MIN)
        drivers = self.listed(summary, "drivers")
        self.assertGreater(len(drivers), inv.DRIVERS_MIN)
        self.assertEqual(drivers, lists["drivers"][:len(drivers)])
        self.assertEqual(self.count(summary, "truncated_drivers"),
                         len(lists["drivers"]) - len(drivers))
        self.assertEqual(self.listed(summary, "autostart"), lists["autostart"])
        self.assertEqual(self.count(summary, "truncated_autostart"), 0)
        self.assertEqual(self.listed(summary, "changes"), lists["changes"])
        self.assertEqual(self.count(summary, "truncated_changes"), 0)
        self.assertEqual(self.listed(summary, "additions"), lists["additions"])
        self.assertEqual(self.count(summary, "truncated_additions"), 0)

    def test_fitting_summary_keeps_every_package(self):
        packages = package_items(LONG_PACKAGES)
        summary = package_summary({"drivers": floor_items("drivers", 20, FLOOR_DRIVER_PAD)},
                                  packages)
        self.assertLess(self.size(summary), self.budget(), "fixture: summary over budget")

        self.fit(summary)

        self.assertEqual(self.listed(summary, "driver_packages"), packages)
        self.assertEqual(self.count(summary, "truncated_driver_packages"), 0)

    def test_null_packages_stay_null_when_cut(self):
        sizes = dict(BUDGET_SIZES)
        for case in ("first pass", "fallback", "nothing fits"):
            with self.subTest(case):
                summary = budget_summary(sizes, pad="x" * 2000)
                summary["driver_packages"] = None
                summary["truncated_driver_packages"] = 0
                if case == "first pass":
                    budget = len(self.inventory.dump(summary)) - 10
                elif case == "fallback":
                    empty = budget_summary({}, pad="x" * 2000)
                    empty["driver_packages"] = None
                    empty["truncated_driver_packages"] = 0
                    empty["autostart_counts"] = {"run": sizes["autostart"]}
                    empty["change_counts"] = {"run_keys": {"added": sizes["changes"],
                                                           "removed": 0, "changed": 0}}
                    for name in SIX_LISTS:
                        empty[COUNT_NAMES[name]] = sizes[name]
                    budget = len(self.inventory.dump(empty)) + 5
                else:
                    budget = 1000
                with mock.patch.object(self.inventory, "SUMMARY_MAX_CHARS", budget):
                    self.inventory.fit_budget(summary)
                self.assertIn("driver_packages", summary)
                self.assertIsNone(summary["driver_packages"])
                self.assertEqual(summary["truncated_driver_packages"], 0)
                if case == "fallback":
                    self.assertEqual(summary["autostart"], [])
                    self.assertEqual(summary["changes"], [])

    def test_fallback_empties_packages_after_drivers_before_additions(self):
        # autostart alone is over the budget, so the first pass fails. The budget lies
        # between the fallback state with 5 packages and the one with 6: autostart and
        # changes at 0, components and drivers at 0, additions and programs at their
        # floors.
        inv = self.inventory
        lists = {
            "programs": floor_items("programs", 25, FLOOR_PROGRAM_PAD),
            "drivers": floor_items("drivers", 20, FLOOR_DRIVER_PAD),
            "components": floor_items("components", 15, FLOOR_COMPONENT_PAD),
            "additions": floor_items("additions", 15, FLOOR_ADDITION_PAD),
            "autostart": floor_items("autostart", 140, FLOOR_AUTOSTART_PAD),
            "changes": floor_items("changes", 30, FLOOR_AUTOSTART_PAD),
        }
        packages = package_items(20)
        summary = package_summary(lists, packages)
        end = {"programs": inv.PROGRAMS_MIN, "additions": inv.ADDITIONS_MIN,
               "components": 0, "drivers": 0, "autostart": 0, "changes": 0,
               "driver_packages": 5}
        low = self.size(cut_state(summary, end))
        high = self.size(cut_state(summary, dict(end, driver_packages=6)))
        budget = (low + high) // 2
        first_pass_end = {name: 0 for name in ("programs", "drivers", "components",
                                               "additions", "driver_packages")}
        self.assertGreater(self.size(cut_state(summary, first_pass_end)), budget,
                           "fixture: the first pass would fit")

        with mock.patch.object(inv, "SUMMARY_MAX_CHARS", budget):
            text = inv.fit_budget(summary)

        self.assertLessEqual(len(text), budget)
        self.assertEqual(summary["autostart"], [])
        self.assertEqual(summary["drivers"], [])
        self.assertEqual(summary["truncated_drivers"], 20)
        self.assertEqual(summary["driver_packages"], packages[:5])
        self.assertEqual(summary["truncated_driver_packages"], 15)
        self.assertEqual(summary["additions"], lists["additions"][:inv.ADDITIONS_MIN])

    def test_packages_emptied_after_drivers_before_additions(self):
        # Sized so that drivers and components at 0 with 5 packages fits and 6 do not:
        # packages go below their minimum only after drivers are empty, and additions
        # stay whole.
        inv = self.inventory
        lists = {
            "drivers": floor_items("drivers", 30, FLOOR_DRIVER_PAD),
            "components": floor_items("components", 20, FLOOR_COMPONENT_PAD),
            "additions": floor_items("additions", 20, FLOOR_ADDITION_PAD),
        }
        packages = package_items(30)
        end = {"drivers": 0, "components": 0, "driver_packages": 5}
        summary = self.sized_case(package_summary(lists, packages), end=end,
                                  one_more=dict(end, driver_packages=6))
        self.assertLess(5, inv.DRIVER_PACKAGES_MIN)

        self.fit(summary)

        self.assertEqual(self.listed(summary, "drivers"), [])
        self.assertEqual(self.count(summary, "truncated_drivers"), 30)
        self.assertEqual(self.listed(summary, "driver_packages"), packages[:5])
        self.assertEqual(self.count(summary, "truncated_driver_packages"), 25)
        self.assertEqual(self.listed(summary, "additions"), lists["additions"])
        self.assertEqual(self.count(summary, "truncated_additions"), 0)


if __name__ == "__main__":
    unittest.main()

"""Tests for skills/ush-processes/scripts/processes.py (plan 051, M2): why a group runs.
Services, the ush-inventory baseline, the program rule and file facts. The interface is
described in ``fakes.py`` and ``fakes_links.py``.

PowerShell never starts; every process, path, service, key and number is invented.
"""

import os
import unittest

from .fakes import FakePowerShell, failure, proc
from .fakes_links import (
    PROGRAM_FILES,
    USER_SERVICE_INSTANCE,
    VENDOR,
    LinksTestCase,
    autostart_item,
    endpoint,
    file_error,
    file_row,
    inventory_sources,
    program_item,
    responses,
    service_item,
    service_row,
    write_inventory,
    write_raw_inventory,
)

SVCHOST = r"C:\Windows\System32\svchost.exe"
SERVICES_EXE = r"C:\Windows\System32\services.exe"
EXPLORER = r"C:\Windows\explorer.exe"
SYNC = r"C:\Apps\Sync\sync.exe"


def inventory_notes(summary_notes):
    return [n for n in summary_notes
            if "inventory" in f"{n.get('what')} {n.get('reason')}".lower()]


class TestServices(LinksTestCase):
    def test_services_and_template_key(self):
        rows = [
            proc(700, "services.exe", SERVICES_EXE, created=1),
            proc(900, "svchost.exe", SVCHOST, parent=700, created=2),
            proc(950, "widgethost.exe", r"C:\Apps\Widget\widgethost.exe", parent=700,
                 created=3),
            proc(960, "agent.exe", r"C:\Apps\Agent\agent.exe", parent=700, created=4),
        ]
        services = [
            service_row("InventedAlpha", 900, start_mode="Auto", display_name="Invented Alpha"),
            service_row("InventedBeta", 900, start_mode="Manual", display_name="Invented Beta"),
            service_row("WidgetUserSvc_1a2b", 950, start_mode="Auto",
                        type_=USER_SERVICE_INSTANCE, display_name="Invented Widget"),
            # An underscore and hex tail without the 0x80 bit is not an instance.
            service_row("Invented_Agent_3c4d", 960, display_name="Invented Agent"),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources())
        summary = self.collect(FakePowerShell(responses(rows, services=services)),
                               data_dir=data_dir)

        host = self.group_with_pid(summary, 900)
        self.assertIsInstance(host.get("services"), list, host)
        self.assertEqual(
            sorted((s.get("name"), s.get("display_name"), s.get("start_mode"), s.get("key"))
                   for s in host["services"]),
            [
                ("InventedAlpha", "Invented Alpha", "Auto", "service:InventedAlpha"),
                ("InventedBeta", "Invented Beta", "Manual", "service:InventedBeta"),
            ],
        )
        self.assertEqual(host.get("services_count"), 2, host)
        self.assertEqual(host.get("started_by"), "service", host)

        widget = self.group_with_pid(summary, 950)
        self.assertEqual(len(widget.get("services") or []), 1, widget)
        self.assertEqual(widget["services"][0].get("name"), "WidgetUserSvc_1a2b", widget)
        self.assertEqual(widget["services"][0].get("key"), "service:WidgetUserSvc", widget)

        agent = self.group_with_pid(summary, 960)
        self.assertEqual(len(agent.get("services") or []), 1, agent)
        self.assertEqual(agent["services"][0].get("key"), "service:Invented_Agent_3c4d",
                         agent)

    def test_services_failure_is_unread(self):
        rows = [
            proc(500, "explorer.exe", EXPLORER, created=1),
            proc(700, "services.exe", SERVICES_EXE, created=1),
            proc(900, "svchost.exe", SVCHOST, parent=700, created=2),
            proc(901, "svchost.exe", SVCHOST, parent=700, created=3),
            proc(950, "sync.exe", SYNC, parent=500, created=4),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources(
            run_keys={"run:HKCU\\Run:Sync": autostart_item("run", SYNC)},
        ))
        fake_responses = responses(rows)
        fake_responses["services"] = failure("Invented: Win32_Service query failed.")
        summary = self.collect(FakePowerShell(fake_responses), data_dir=data_dir)

        self.assertEqual(self.source(summary, "services").get("status"), "unreadable")

        host = self.group_with_pid(summary, 900)
        self.assert_unread(host, "services")
        self.assert_unread(host, "started_by")

        sync = self.group_with_pid(summary, 950)
        self.assertEqual([a.get("key") for a in sync.get("autostart") or []],
                         ["run:HKCU\\Run:Sync"], sync)
        self.assert_unread(sync, "started_by")

        self.assertEqual(len(self.notes_about(summary, "services")), 1,
                         self.not_checked(summary))


class TestInventory(LinksTestCase):
    def test_autostart_match(self):
        running = r"C:\apps\sync\SYNC.EXE"
        rows = [
            proc(500, "explorer.exe", EXPLORER, created=1),
            proc(950, "sync.exe", running, parent=500, created=2),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources(
            run_keys={"run:HKCU\\Run:Sync": autostart_item(
                "run", SYNC, program="win32:hklm64:InventedSync")},
            win32_programs={
                "win32:hklm64:InventedSync": program_item("Invented Sync",
                                                          r"D:\Invented\SyncData"),
                # The longest prefix would give this one; the entry's facts win.
                "win32:hklm64:InventedSuite": program_item("Invented Suite", r"C:\Apps\Sync"),
            },
        ))
        summary = self.collect(FakePowerShell(responses(rows)), data_dir=data_dir)

        group = self.group_with_pid(summary, 950)
        autostart = group.get("autostart")
        self.assertIsInstance(autostart, list, group)
        self.assertEqual(
            [{k: a.get(k) for k in ("key", "kind", "enabled")} for a in autostart],
            [{"key": "run:HKCU\\Run:Sync", "kind": "run", "enabled": True}],
        )
        self.assertEqual(group.get("started_by"), "autostart", group)
        self.assertEqual(group.get("program"),
                         {"key": "win32:hklm64:InventedSync", "name": "Invented Sync"}, group)

    def test_missing_or_unreadable_baseline(self):
        rows = [
            proc(700, "services.exe", SERVICES_EXE, created=1),
            proc(900, "svchost.exe", SVCHOST, parent=700, created=2),
            proc(950, "notes.exe", r"C:\Apps\Notes\notes.exe", created=3),
        ]
        services = [service_row("InventedAlpha", 900)]

        def check(summary, status):
            self.assertEqual(self.inventory(summary).get("status"), status)
            for group in self.groups(summary):
                with self.subTest(status=status, group=group.get("name")):
                    self.assert_unread(group, "autostart")
            self.assertEqual(self.group_with_pid(summary, 900).get("started_by"), "service")
            self.assert_unread(self.group_with_pid(summary, 950), "started_by")
            self.assertGreaterEqual(len(inventory_notes(self.not_checked(summary))), 1,
                                    self.not_checked(summary))

        with self.subTest("no baseline file"):
            summary = self.collect(FakePowerShell(responses(rows, services=services)))
            check(summary, "none")

        with self.subTest("unreadable baseline file"):
            data_dir = self.data_dir()
            path = write_raw_inventory(data_dir, '{"schema_version": 1, "skill": ')
            before_bytes = path.read_bytes()
            before_mtime = os.stat(path).st_mtime_ns
            summary = self.collect(FakePowerShell(responses(rows, services=services)),
                                   data_dir=data_dir)
            check(summary, "unreadable")
            self.assertEqual(path.read_bytes(), before_bytes)
            self.assertEqual(os.stat(path).st_mtime_ns, before_mtime)

    def test_program_prefix(self):
        tray = r"C:\Apps\Tray\tray.exe"
        synth = r"C:\Apps\Synth\synth.exe"
        tool = PROGRAM_FILES + r"\Invented Tool\tool.exe"
        rows = [
            proc(500, "explorer.exe", EXPLORER, created=1),
            proc(610, "sync.exe", SYNC, parent=500, created=2),
            proc(620, "synth.exe", synth, parent=500, created=3),
            proc(630, "tool.exe", tool, parent=500, created=4),
            proc(640, "tray.exe", tray, parent=500, created=5),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources(
            run_keys={"run:HKCU\\Run:Tray": autostart_item(
                "run", tray, program="win32:hklm64:InventedTray")},
            win32_programs={
                "win32:hklm64:InventedApps": program_item("Invented Apps", r"C:\Apps"),
                "win32:hklm64:InventedSync": program_item("Invented Sync", r"C:\Apps\Sync"),
                "win32:hklm64:InventedSyn": program_item("Invented Syn", r"C:\Apps\Syn"),
                "win32:hklm64:InventedInstaller": program_item("Invented Installer",
                                                               PROGRAM_FILES),
                "win32:hklm64:InventedTray": program_item("Invented Tray",
                                                          r"D:\Invented\TrayData"),
            },
        ))

        summary = self.collect(FakePowerShell(responses(rows)), data_dir=data_dir)
        self.assertEqual(self.group_with_pid(summary, 610).get("program"),
                         {"key": "win32:hklm64:InventedSync", "name": "Invented Sync"})
        self.assertEqual(self.group_with_pid(summary, 620).get("program"),
                         {"key": "win32:hklm64:InventedApps", "name": "Invented Apps"})
        self.assert_not_unread(self.group_with_pid(summary, 630), "program")

        with self.subTest("file_facts failed"):
            fake_responses = responses(rows)
            fake_responses["file_facts"] = failure("Invented: file facts job failed.")
            summary = self.collect(FakePowerShell(fake_responses), data_dir=data_dir)
            self.assert_unread(self.group_with_pid(summary, 610), "program")
            self.assertEqual(self.group_with_pid(summary, 640).get("program"),
                             {"key": "win32:hklm64:InventedTray", "name": "Invented Tray"})

    def test_launcher_not_matched(self):
        rundll = r"C:\Windows\System32\rundll32.exe"
        rows = [
            proc(500, "explorer.exe", EXPLORER, created=1),
            proc(700, "rundll32.exe", r"c:\windows\system32\RUNDLL32.EXE", parent=500,
                 created=2),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources(
            scheduled_tasks={"task:\\InventedLogonTask": autostart_item("task", rundll)},
        ))
        summary = self.collect(FakePowerShell(responses(rows)), data_dir=data_dir)

        group = self.group_with_pid(summary, 700)
        self.assertEqual(group.get("autostart"), [], group)
        self.assertNotEqual(group.get("started_by"), "autostart", group)

    def test_incomplete_baseline_reported(self):
        rows = [
            proc(500, "explorer.exe", EXPLORER, created=1),
            proc(950, "sync.exe", SYNC, parent=500, created=2),
        ]
        run_keys = {"run:HKCU\\Run:Sync": autostart_item("run", SYNC)}

        # The same machine with a complete baseline: the reference for new notes.
        complete_dir = self.data_dir()
        write_inventory(complete_dir, inventory_sources(run_keys=run_keys))
        complete = self.collect(FakePowerShell(responses(rows)), data_dir=complete_dir)
        self.assertEqual(self.inventory(complete).get("status"), "read")
        self.assertEqual(self.inventory(complete).get("missing_sources"), [])
        self.assertEqual(self.inventory(complete).get("entries_without_path"), 0)

        incomplete_dir = self.data_dir()
        run_keys["run:HKCU\\Run:Hidden"] = autostart_item(
            "run", r"%INVENTEDVAR%\hidden.exe", expanded=None)
        sources = inventory_sources(run_keys=run_keys)
        del sources["scheduled_tasks"]
        write_inventory(incomplete_dir, sources)
        summary = self.collect(FakePowerShell(responses(rows)), data_dir=incomplete_dir)

        inventory = self.inventory(summary)
        self.assertEqual(inventory.get("status"), "read", inventory)
        self.assertEqual(inventory.get("missing_sources"), ["scheduled_tasks"], inventory)
        self.assertEqual(inventory.get("entries_without_path"), 1, inventory)
        self.assertEqual(
            len(self.not_checked(summary)) - len(self.not_checked(complete)), 2,
            (self.not_checked(complete), self.not_checked(summary)),
        )

        with self.subTest("unreadable baseline gives a reason"):
            data_dir = self.data_dir()
            write_raw_inventory(data_dir, "not JSON at all")
            summary = self.collect(FakePowerShell(responses(rows)), data_dir=data_dir)
            inventory = self.inventory(summary)
            self.assertEqual(inventory.get("status"), "unreadable", inventory)
            self.assertIsInstance(inventory.get("reason"), str, inventory)
            self.assertTrue(inventory["reason"].strip(), inventory)


class TestFacts(LinksTestCase):
    def test_unread_vs_nothing_to_read(self):
        good = r"C:\Apps\Good\good.exe"
        numeric = r"C:\Apps\Numeric\numeric.exe"
        broken = r"C:\Apps\Broken\broken.exe"
        rows = [
            proc(610, "good.exe", good, created=1),
            proc(620, "numeric.exe", numeric, created=2),
            proc(630, "broken.exe", broken, created=3),
            proc(640, "ghost.exe", path=None, created=4),
        ]
        files = [
            file_row(good, status="Valid", signer=VENDOR, company="Invented Company"),
            file_row(numeric, status=0),
            file_error(broken),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources())
        summary = self.collect(FakePowerShell(responses(rows, files=files)),
                               data_dir=data_dir)

        g = self.group_with_pid(summary, 610)
        self.assert_read(g, "signature_status", "Valid")
        self.assert_read(g, "signer", VENDOR)
        self.assert_read(g, "company", "Invented Company")
        self.assert_read(g, "exists", True)

        self.assert_unread(self.group_with_pid(summary, 620), "signature_status")
        self.assert_unread(self.group_with_pid(summary, 630), "signature_status")

        ghost = self.group_named(self.groups(summary), "ghost.exe",
                                 path_read=False)
        self.assert_not_unread(ghost, "signature_status")

        with self.subTest("file_facts failed"):
            fake_responses = responses(rows, files=files)
            fake_responses["file_facts"] = failure("Invented: file facts job failed.")
            summary = self.collect(FakePowerShell(fake_responses), data_dir=data_dir)
            self.assert_unread(self.group_with_pid(summary, 610), "signature_status")
            self.assertEqual(len(self.notes_about(summary, "file_facts")), 1,
                             self.not_checked(summary))


class TestUnreadInputs(LinksTestCase):
    def test_unread_path_or_parent_is_not_nothing(self):
        rows = [
            proc(4, "System", None, parent=0, created=0),
            proc(500, "explorer.exe", EXPLORER, created=1),
            proc(960, "hidden.exe", None, parent=500, created=2),
            proc(970, "late.exe", r"C:\Apps\Late\late.exe", parent=500, created=None),
            proc(980, "notes.exe", r"C:\Apps\Notes\notes.exe", parent=500, created=3),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources())
        summary = self.collect(FakePowerShell(responses(rows)), data_dir=data_dir)

        # Clean-data reference: a known path and a known parent give facts, nothing unread.
        notes = self.group_with_pid(summary, 980)
        self.assertEqual(notes.get("autostart"), [], notes)
        self.assertEqual(notes.get("started_by"), "parent", notes)
        self.assertEqual(notes.get("unread_fields"), [], notes)

        # A pseudoprocess has no file: nothing to match, nothing unread.
        system = self.group_with_pid(summary, 4)
        self.assertEqual(system.get("autostart"), [], system)
        self.assertNotIn("started_by", system.get("unread_fields") or [], system)

        # An unread path: the autostart and program rules could not be applied.
        hidden = self.group_with_pid(summary, 960)
        for field in ("autostart", "program", "started_by"):
            with self.subTest(group="hidden.exe", field=field):
                self.assert_unread(hidden, field)

        # A missing start time: whether the parent is still the parent is not known.
        late = self.group_with_pid(summary, 970)
        self.assertEqual(late.get("autostart"), [], late)
        self.assert_unread(late, "started_by")

    def test_disabled_entry_does_not_start(self):
        rows = [
            proc(500, "explorer.exe", EXPLORER, created=1),
            proc(950, "sync.exe", SYNC, parent=500, created=2),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources(
            run_keys={r"run:HKCU\Run:Sync": autostart_item("run", SYNC, enabled=False)}))
        summary = self.collect(FakePowerShell(responses(rows)), data_dir=data_dir)

        group = self.group_with_pid(summary, 950)
        self.assertEqual([a.get("enabled") for a in group.get("autostart") or []], [False], group)
        self.assertEqual(group.get("started_by"), "parent", group)

    def test_file_check_tells_not_found_from_denied(self):
        body = self.processes.FILE_FACTS_BODY
        self.assertIn("Get-Item -LiteralPath", body)
        self.assertIn("ItemNotFoundException", body)


class TestBaselineServices(LinksTestCase):
    """Services the ush-inventory baseline lists join ``autostart``; the template key
    of a per-user instance when ``Type`` was not read (review notes of plan 051, M2)."""

    def test_baseline_service_joins_autostart(self):
        rows = [
            proc(700, "services.exe", SERVICES_EXE, created=1),
            proc(900, "svchost.exe", SVCHOST, parent=700, created=2),
            proc(950, "widgethost.exe", r"C:\Apps\Widget\widgethost.exe", parent=700,
                 created=3),
        ]
        services = [
            service_row("InventedAlpha", 900),
            # Not in the baseline: no autostart link.
            service_row("InventedBeta", 900),
            service_row("WidgetUserSvc_1a2b", 950, type_=USER_SERVICE_INSTANCE),
        ]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources(services={
            "service:InventedAlpha": service_item("InventedAlpha", SVCHOST),
            "service:WidgetUserSvc": service_item(
                "WidgetUserSvc", r"C:\Apps\Widget\widgethost.exe", enabled=False),
        }))
        summary = self.collect(FakePowerShell(responses(rows, services=services)),
                               data_dir=data_dir)

        host = self.group_with_pid(summary, 900)
        self.assertEqual(host.get("autostart"),
                         [{"key": "service:InventedAlpha", "kind": "service", "enabled": True}],
                         host)
        self.assertEqual(host.get("started_by"), "service", host)

        widget = self.group_with_pid(summary, 950)
        self.assertEqual(widget.get("autostart"),
                         [{"key": "service:WidgetUserSvc", "kind": "service", "enabled": False}],
                         widget)
        self.assertEqual(widget.get("started_by"), "service", widget)

        with self.subTest("clean data: baseline without these services"):
            clean_dir = self.data_dir()
            write_inventory(clean_dir, inventory_sources())
            summary = self.collect(FakePowerShell(responses(rows, services=services)),
                                   data_dir=clean_dir)
            for pid in (900, 950):
                group = self.group_with_pid(summary, pid)
                self.assertEqual(group.get("autostart"), [], group)
                self.assertNotIn("autostart", group.get("unread_fields") or [], group)

    def test_template_key_without_type(self):
        rows = [
            proc(700, "services.exe", SERVICES_EXE, created=1),
            proc(950, "widgethost.exe", r"C:\Apps\Widget\widgethost.exe", parent=700,
                 created=2),
            proc(960, "agent.exe", r"C:\Apps\Agent\agent.exe", parent=700, created=3),
            proc(970, "other.exe", r"C:\Apps\Other\other.exe", parent=700, created=4),
        ]
        services = [
            service_row("WidgetUserSvc_1a2b", 950, type_=None),
            service_row("Invented_Agent_3c4d", 960, type_=None),
            service_row("PlainSvc", 970, type_=None),
        ]
        user_template = service_item("WidgetUserSvc", r"C:\Apps\Widget\widgethost.exe")
        user_template["user_service"] = True
        # Listed, but not as a per-user service: the name keeps its ending.
        not_user = service_item("Invented_Agent", r"C:\Apps\Agent\agent.exe")
        not_user["user_service"] = False
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources(services={
            "service:WidgetUserSvc": user_template,
            "service:Invented_Agent": not_user,
        }))
        summary = self.collect(FakePowerShell(responses(rows, services=services)),
                               data_dir=data_dir)

        def key_of(pid):
            group = self.group_with_pid(summary, pid)
            self.assertEqual(len(group.get("services") or []), 1, group)
            return group["services"][0].get("key")

        self.assertEqual(key_of(950), "service:WidgetUserSvc")
        self.assertEqual(key_of(960), "service:Invented_Agent_3c4d")
        self.assertEqual(key_of(970), "service:PlainSvc")

        with self.subTest("no baseline: the full name is kept"):
            summary = self.collect(FakePowerShell(responses(rows, services=services)))
            self.assertEqual(key_of(950), "service:WidgetUserSvc_1a2b")


class TestSingleObject(LinksTestCase):
    def test_one_row_written_as_object(self):
        """ConvertTo-Json writes a single row as an object, not a list: it is still a row."""
        rows = [proc(900, "svchost.exe", SVCHOST, created=1)]
        fake_responses = responses(
            rows,
            services=[service_row("InventedAlpha", 900)],
            tcp=[endpoint("0.0.0.0", 445, 900)],
            udp=[endpoint("127.0.0.1", 5353, 900)],
        )
        for job in ("processes", "perf", "owners", "memory", "services", "tcp_listeners",
                    "udp_endpoints"):
            kind, payload = fake_responses[job]
            self.assertEqual(len(payload), 1, job)
            fake_responses[job] = (kind, payload[0])
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources())
        summary = self.collect(FakePowerShell(fake_responses), data_dir=data_dir)

        for job in ("processes", "perf", "owners", "memory", "services", "tcp_listeners",
                    "udp_endpoints"):
            with self.subTest(job=job):
                self.assertEqual(self.source(summary, job).get("status"), "read")
        group = self.group_with_pid(summary, 900)
        self.assertIsNotNone(group.get("memory_private_bytes"), group)
        self.assertEqual(group.get("owners"), ["HOST\\alice"], group)
        self.assertEqual([s.get("name") for s in group.get("services") or []],
                         ["InventedAlpha"], group)
        self.assertIsNotNone(summary.get("memory", {}).get("total_bytes"), summary)
        self.assertEqual([(p.get("local_port"), p.get("pid")) for p in self.ports(summary)],
                         [(445, 900)])
        self.assertEqual([(u.get("scope"), u.get("count")) for u in summary.get("udp_bound")],
                         [("loopback", 1)])


if __name__ == "__main__":
    unittest.main()

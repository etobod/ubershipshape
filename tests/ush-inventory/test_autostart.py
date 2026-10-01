"""Autostart entries and file facts of skills/ush-inventory/scripts/inventory.py
(plan 048, milestone M3).

The general interface (``main(argv, run_ps, is_admin, now)``, ``FakePowerShell``,
``sources``, ``comparison``, item ``key``/``id``/``own``, ``not_checked`` wording) is in
``fakes.py``. PowerShell never starts; every baseline lives in a temporary directory;
every value is invented.

Interface fixed for M3 (the implementation follows it):

- Pure function ``inventory.target_path(command) -> str | None``.
- One PowerShell job per source; each answers a list of rows (a single object is read
  as a one-element list):
  - ``run_keys``: ``{Hive: "hkcu"|"hklm64"|"hklm32", Key: "Run"|"RunOnce", Name,
    Value (raw, unexpanded), ValueKind ("String"|"ExpandString")}``. Item key
    ``run:<Hive>\\<Key>:<Name>``; ``kind`` ``run``/``run_once``.
  - ``startup_folders``: ``{Scope: "user"|"common", FileName, FullName, TargetPath,
    Arguments}`` (the last two null when not a ``.lnk``); ``desktop.ini`` is skipped.
    Key ``startup:<Scope>:<FileName>``; ``command`` is ``TargetPath + " " + Arguments``
    for a ``.lnk`` (``TargetPath`` alone without arguments), ``FullName`` otherwise.
  - ``startup_approved``: ``{Hive: "hkcu"|"hklm", Key: "Run"|"Run32"|"StartupFolder",
    Name, Bytes: [int, ...]}``; ``[]`` is status ``empty``. ``Run`` of hive X joins
    ``run:<X>\\Run`` (hklm -> hklm64), ``Run32`` of hklm joins ``run:hklm32\\Run``,
    ``StartupFolder`` of hkcu/hklm joins ``startup:user``/``startup:common``, by Name.
  - ``scheduled_tasks``: ``{TaskPath, TaskName, State, Triggers: [CIM class names],
    Actions: [{Type: "Exec"|"ComHandler", Execute, Arguments, ClassId,
    InprocServer32 (resolved path or null)}]}``. Key ``task:<TaskPath><TaskName>``.
  - ``services``: ``{Name, DisplayName, PathName, State, StartMode, Type (int),
    DelayedAutostart, ServiceDll, KeyServiceDll, TemplateServiceDll,
    TemplateKeyServiceDll, TemplateStart}``; only ``StartMode`` ``Auto`` rows are entries.
  - ``file_facts``: rows ``{Kind: "dir", Name: "ProgramFiles"|"ProgramFilesX86"|
    "SystemRoot"|"System32", Path}`` and ``{Kind: "file", Path (the target as requested),
    ExpandedPath, Exists, SignatureStatus, Signer, Company}``; rows match targets by
    ``Path`` case-insensitively; extra rows are ignored; a target with no row gets null
    fact fields (not unread).
- Each ``facts[i]`` has ``path, expanded_path, exists, signature_status, signer,
  company, program``; a change of one fact is reported in ``fields`` as
  ``facts[<path>].<field>`` with ``{before, after}`` as in M2.
- ``summary["autostart"]`` lists only ``own: false`` entries (ids ``s<n>``);
  ``own_counts.autostart`` is a dict ``{kind: number of own: true entries}``;
  ``own_counts.unknown`` is an int; the detail file section ``autostart`` holds all.
- ``unread_fields`` is a list on the entry, e.g. ``["approved", "enabled"]``,
  ``["facts"]``.

Extra assumptions stated here:

- A source job answering ``[]`` has status ``empty`` (as in M2), so on the clean machine
  ``run_keys``, ``startup_folders`` and ``startup_approved`` are ``empty``.
- ``facts_from_baseline: true`` is a field of the entry, not of each fact.
- An entry whose facts could not be read keeps its ``facts`` list with one element per
  target, whose fact fields are null (a null ``facts`` is accepted too).
- The ``not_checked`` item about a failed ``file_facts`` job contains the text
  ``file_facts`` somewhere in the item; the note about tasks invisible without
  administrator names ``scheduled_tasks`` in ``what``.
"""

import json
import unittest
from datetime import timedelta

from .fakes import NOW, FakePowerShell, InventoryTestCase, failure, id_number, ok, win32
from .fakes_autostart import (
    BOOT,
    CLEAN_SERVICE_KEYS,
    CLEAN_TASK_KEYS,
    DAILY,
    ENTRY_SOURCES,
    LOGON,
    MS,
    PROGRAM_FILES,
    SHARE_PROCESS,
    USER_SERVICE_INSTANCE,
    VENDOR,
    approved,
    clean_responses,
    com_action,
    exec_action,
    facts,
    file_row,
    run_value,
    service,
    startup_file,
    task,
)

FACT_FIELDS = ("expanded_path", "exists", "signature_status", "signer", "company")


def run_key(name, hive="hkcu", key="Run"):
    return f"run:{hive}\\{key}:{name}"


class AutostartTestCase(InventoryTestCase):
    def listed(self, summary):
        """Autostart entries of the summary, by key."""
        return self.by_key(summary.get("autostart"))

    def all_entries(self, summary):
        """Autostart entries of the detail file, by key."""
        return self.by_key(self.detail(summary).get("autostart"))

    def entry(self, summary, key):
        entries = self.all_entries(summary)
        self.assertIn(key, entries, sorted(entries))
        return entries[key]

    def first_fact(self, entry):
        facts_list = entry.get("facts")
        self.assertIsInstance(facts_list, list, entry)
        self.assertTrue(facts_list, entry)
        return facts_list[0]

    def assert_facts_unread(self, entry):
        facts_list = entry.get("facts")
        if facts_list is None:
            return
        self.assertIsInstance(facts_list, list, entry)
        for fact in facts_list:
            for field in FACT_FIELDS:
                self.assertIsNone(fact.get(field), f"{field} in {entry}")

    def own_counts(self, summary):
        counts = summary.get("own_counts")
        self.assertIsInstance(counts, dict, summary)
        return counts


class TestTarget(AutostartTestCase):
    def test_target_path_cases(self):
        cases = [
            ('"C:\\Program Files\\A B\\x.exe" --tray', "C:\\Program Files\\A B\\x.exe"),
            ("C:\\Program Files\\A B\\x.exe --tray", "C:\\Program Files\\A B\\x.exe"),
            ("rundll32.exe C:\\x\\y.dll,Entry", "rundll32.exe"),
            ("\\SystemRoot\\System32\\z.exe", "%SystemRoot%\\System32\\z.exe"),
            ("C:\\PROGRAM FILES\\A B\\X.EXE --tray", "C:\\PROGRAM FILES\\A B\\X.EXE"),
            ("", None),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(self.inventory.target_path(command), expected)


class TestOwn(AutostartTestCase):
    def test_own_needs_every_fact(self):
        probe = "C:\\Windows\\System32\\inventedprobe.exe"
        rundll_upper = "C:\\WINDOWS\\System32\\RunDll32.EXE"
        cases = [
            ("existing Valid Microsoft file", probe, file_row(probe), True),
            ("NotSigned", probe,
             file_row(probe, status="NotSigned", signer=None, company=MS), False),
            ("HashMismatch", probe, file_row(probe, status="HashMismatch"), False),
            ("file does not exist", probe, file_row(probe, exists=False), False),
            ("signer not in the list", probe, file_row(probe, signer=VENDOR), False),
            ("launcher rundll32.exe", "rundll32.exe C:\\Invented\\probe.dll,Entry",
             file_row("rundll32.exe"), False),
            ("launcher in other case", rundll_upper + " C:\\Invented\\probe.dll,Entry",
             file_row(rundll_upper), False),
            ("launcher MsiExec.exe", "MsiExec.exe /V", file_row("MsiExec.exe"), False),
        ]
        key = "service:InventedProbeSvc"
        for label, path_name, row, expected in cases:
            with self.subTest(case=label):
                fake = FakePowerShell({
                    "services": ok([service("InventedProbeSvc", path_name)]),
                    "file_facts": facts(row),
                })
                summary = self.collect(fake)
                entry = self.entry(summary, key)
                self.assertIs(entry.get("own"), expected, entry)
                listed = self.listed(summary)
                if expected:
                    self.assertNotIn(key, listed, listed)
                else:
                    self.assertIn(key, listed, listed)
                    self.assertIs(listed[key].get("own"), False, listed[key])

    def test_clean_machine_lists_nothing(self):
        summary = self.collect(FakePowerShell(clean_responses()))

        self.assertEqual(summary.get("autostart"), [])
        for name in ("services", "scheduled_tasks"):
            self.assertEqual(self.source(summary, name).get("status"), "read", name)
        for name in ("run_keys", "startup_folders", "startup_approved"):
            self.assertEqual(self.source(summary, name).get("status"), "empty", name)

        counts = self.own_counts(summary)
        per_kind = counts.get("autostart")
        self.assertIsInstance(per_kind, dict, counts)
        self.assertEqual({k: v for k, v in per_kind.items() if v},
                         {"service": 3, "task": 2}, per_kind)
        self.assertEqual(counts.get("unknown"), 0, counts)

        entries = self.all_entries(summary)
        self.assertEqual(set(entries), CLEAN_SERVICE_KEYS | CLEAN_TASK_KEYS, sorted(entries))
        for entry in entries.values():
            self.assertIs(entry.get("own"), True, entry)

    def test_run_entries_always_listed(self):
        target = "C:\\Program Files\\Microsoft\\InventedSync\\sync.exe"
        responses = clean_responses(extra_files=[file_row(target)])
        responses["run_keys"] = ok([run_value("InventedSync", f'"{target}" /background')])
        summary = self.collect(FakePowerShell(responses))

        key = run_key("InventedSync")
        listed = self.listed(summary)
        self.assertIn(key, listed, listed)
        entry = listed[key]
        self.assertIs(entry.get("own"), False, entry)
        self.assertEqual(entry.get("kind"), "run", entry)
        id_number(entry.get("id"), "s")

        detail_entry = self.entry(summary, key)
        fact = self.first_fact(detail_entry)
        self.assertEqual(fact.get("path"), target, fact)
        self.assertIs(fact.get("exists"), True, fact)
        self.assertEqual(fact.get("signature_status"), "Valid", fact)
        self.assertEqual(fact.get("signer"), MS, fact)


class TestApproved(AutostartTestCase):
    RUNS = (
        run_value("InventedOff", "C:\\Apps\\Off\\off.exe"),
        run_value("InventedWow", "C:\\Apps\\Wow\\wow.exe", hive="hklm32"),
        run_value("InventedWow", "C:\\Apps\\Wow64\\wow.exe", hive="hklm64"),
        run_value("InventedPlain", "C:\\Apps\\Plain\\plain.exe"),
        run_value("InventedOdd", "C:\\Apps\\Odd\\odd.exe"),
    )

    def test_join_and_bytes(self):
        rows = [
            approved("InventedOff", 3),
            approved("InventedWow", 3, hive="hklm", key="Run32"),
            approved("InventedOdd", 6),
        ]
        summary = self.collect(FakePowerShell({
            "run_keys": ok(list(self.RUNS)),
            "startup_approved": ok(rows),
        }))
        self.assertEqual(self.source(summary, "startup_approved").get("status"), "read")

        off = self.entry(summary, run_key("InventedOff"))
        self.assertEqual(off.get("approved"), "disabled", off)
        self.assertIs(off.get("enabled"), False, off)

        wow32 = self.entry(summary, run_key("InventedWow", hive="hklm32"))
        self.assertEqual(wow32.get("approved"), "disabled", wow32)
        self.assertIs(wow32.get("enabled"), False, wow32)

        wow64 = self.entry(summary, run_key("InventedWow", hive="hklm64"))
        self.assertEqual(wow64.get("approved"), "not_set", wow64)
        self.assertIs(wow64.get("enabled"), True, wow64)

        plain = self.entry(summary, run_key("InventedPlain"))
        self.assertEqual(plain.get("approved"), "not_set", plain)
        self.assertIs(plain.get("enabled"), True, plain)

        odd = self.entry(summary, run_key("InventedOdd"))
        self.assertEqual(odd.get("approved"), "unknown", odd)
        self.assertEqual(odd.get("approved_byte"), 6, odd)

        with self.subTest(case="no StartupApproved key"):
            summary = self.collect(FakePowerShell({
                "run_keys": ok(list(self.RUNS)),
                "startup_approved": ok([]),
            }))
            self.assertEqual(self.source(summary, "startup_approved").get("status"), "empty")
            plain = self.entry(summary, run_key("InventedPlain"))
            self.assertEqual(plain.get("approved"), "not_set", plain)
            self.assertIs(plain.get("enabled"), True, plain)


class TestServices(AutostartTestCase):
    def test_svchost_dll(self):
        host = "C:\\WINDOWS\\system32\\svchost.exe -k InventedGroup -p"
        dll = "%SystemRoot%\\System32\\inventedwith.dll"
        summary = self.collect(FakePowerShell({
            "services": ok([
                service("InventedWithDll", host, type_=SHARE_PROCESS, service_dll=dll),
                service("InventedNoDll", host, type_=SHARE_PROCESS),
            ]),
            # svchost.exe itself is Valid and Microsoft-signed: it must not become the target.
            "file_facts": facts(
                file_row(dll, expanded="C:\\Windows\\System32\\inventedwith.dll"),
                file_row("C:\\WINDOWS\\system32\\svchost.exe"),
            ),
        }))

        with_dll = self.entry(summary, "service:InventedWithDll")
        self.assertEqual(with_dll.get("targets"), [dll], with_dll)
        self.assertEqual(self.first_fact(with_dll).get("path"), dll, with_dll)

        no_dll = self.entry(summary, "service:InventedNoDll")
        self.assertEqual(no_dll.get("targets"), [None], no_dll)
        self.assertIs(no_dll.get("own"), False, no_dll)
        self.assertIn("service:InventedNoDll", self.listed(summary))

    def test_user_service_instances_keyed_by_template(self):
        dll = "%SystemRoot%\\System32\\inventedwidget.dll"
        host = "C:\\WINDOWS\\system32\\svchost.exe -k InventedUserGroup"
        file_facts = facts(file_row(dll, expanded="C:\\Windows\\System32\\inventedwidget.dll"))
        key = "service:WidgetUserSvc"

        def instance(name, state="Running"):
            return service(name, host, state=state, type_=USER_SERVICE_INSTANCE,
                           template_service_dll=dll, template_start=2)

        def widget_keys(summary):
            return [k for k in self.all_entries(summary) if str(k).startswith("service:Widget")]

        data_dir = self.data_dir()
        first = self.collect(FakePowerShell({
            "services": ok([instance("WidgetUserSvc_1a2b")]),
            "file_facts": file_facts,
        }), data_dir=data_dir, now=NOW)
        self.assertEqual(widget_keys(first), [key])
        entry = self.entry(first, key)
        self.assertIs(entry.get("user_service"), True, entry)
        self.assertEqual(entry.get("targets"), [dll], entry)
        self.assertEqual(entry.get("name"), "WidgetUserSvc", entry)

        second = self.collect(FakePowerShell({
            "services": ok([instance("WidgetUserSvc_9f8e")]),
            "file_facts": file_facts,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))
        self.assertEqual(widget_keys(second), [key])
        self.assertEqual(self.changes(second), [])
        self.assert_no_own_changes(second)

        stopped = instance("WidgetUserSvc_1a2b", state="Stopped")
        running = instance("WidgetUserSvc_9f8e", state="Running")
        for order in ([stopped, running], [running, stopped]):
            with self.subTest(case="two instances in one run",
                              order=[row["Name"] for row in order]):
                summary = self.collect(FakePowerShell({
                    "services": ok(order),
                    "file_facts": file_facts,
                }))
                self.assertEqual(widget_keys(summary), [key])
                self.assertEqual(self.entry(summary, key).get("state"), "Running")


class TestTasks(AutostartTestCase):
    def test_actions_and_triggers(self):
        com_dll = "%SystemRoot%\\System32\\inventedhandler.dll"
        exe = "C:\\Windows\\System32\\inventedmixed.exe"
        summary = self.collect(FakePowerShell({
            "scheduled_tasks": ok([
                task("InventedComTask",
                     [com_action("{1B2C3D4E-5F60-4718-9A2B-3C4D5E6F7A8B}", com_dll)],
                     triggers=(LOGON,)),
                task("InventedMixedTask",
                     [exec_action(exe, "/start"),
                      com_action("{2C3D4E5F-6071-4829-AB3C-4D5E6F7A8B9C}", None)],
                     triggers=(BOOT,)),
                task("InventedDailyTask", [exec_action(exe)], triggers=(DAILY,)),
            ]),
            "file_facts": facts(
                file_row(com_dll, expanded="C:\\Windows\\System32\\inventedhandler.dll"),
                file_row(exe),
            ),
        }))
        entries = self.all_entries(summary)

        com = entries.get("task:\\Invented\\InventedComTask")
        self.assertIsNotNone(com, sorted(entries))
        self.assertEqual(com.get("targets"), [com_dll], com)

        mixed = entries.get("task:\\Invented\\InventedMixedTask")
        self.assertIsNotNone(mixed, sorted(entries))
        self.assertEqual(mixed.get("targets"), [exe, None], mixed)
        self.assertIs(mixed.get("own"), False, mixed)
        self.assertIn("task:\\Invented\\InventedMixedTask", self.listed(summary))

        self.assertNotIn("task:\\Invented\\InventedDailyTask", entries)

    def test_visibility_note(self):
        for admin in (False, True):
            with self.subTest(admin=admin):
                summary = self.collect(FakePowerShell(clean_responses()), admin=admin)
                self.assertEqual(self.source(summary, "scheduled_tasks").get("status"), "read")
                notes = self.notes_about_source(summary, "scheduled_tasks")
                if admin:
                    self.assertEqual(notes, [])
                else:
                    self.assertTrue(notes, summary.get("not_checked"))


class TestProgram(AutostartTestCase):
    def run_with(self, programs, targets):
        """Run with ``programs`` as Win32 rows and one hkcu Run value per target."""
        responses = clean_responses(extra_files=[file_row(p) for p in targets.values()])
        responses["win32_programs"] = ok(programs)
        responses["run_keys"] = ok([run_value(name, path) for name, path in targets.items()])
        return self.collect(FakePowerShell(responses))

    def program_of(self, summary, name):
        fact = self.first_fact(self.entry(summary, run_key(name)))
        self.assertIn("program", fact)
        return fact["program"]

    def test_target_matched_to_program(self):
        with self.subTest(case="folder boundary, root and Program Files skipped"):
            programs = [
                win32("InventedTool", "Invented Tool", install_location="C:\\Apps\\Tool"),
                win32("InventedRoot", "Invented Root", install_location="C:\\"),
                win32("InventedPF", "Invented PF", install_location=PROGRAM_FILES),
            ]
            summary = self.run_with(programs, {
                "InTool": "C:\\Apps\\Tool\\x.exe",
                "InTool2": "C:\\Apps\\Tool2\\x.exe",
                "Outside": "D:\\Elsewhere\\y.exe",
                "InProgramFiles": "C:\\Program Files\\Other\\o.exe",
            })
            self.assertEqual(self.program_of(summary, "InTool"), "win32:hklm64:InventedTool")
            self.assertIsNone(self.program_of(summary, "InTool2"))
            self.assertIsNone(self.program_of(summary, "Outside"))
            self.assertIsNone(self.program_of(summary, "InProgramFiles"))

        apps = win32("InventedApps", "Invented Apps", install_location="C:\\Apps")
        tool = win32("InventedTool", "Invented Tool", install_location="C:\\Apps\\Tool")
        for programs in ([apps, tool], [tool, apps]):
            with self.subTest(case="longest prefix wins",
                              order=[p["KeyName"] for p in programs]):
                summary = self.run_with(programs, {"InTool": "C:\\Apps\\Tool\\x.exe"})
                self.assertEqual(self.program_of(summary, "InTool"),
                                 "win32:hklm64:InventedTool")

        with self.subTest(case="clean machine, targets in the Windows directory"):
            summary = self.collect(FakePowerShell(clean_responses()))
            entries = self.all_entries(summary)
            self.assertTrue(entries)
            for key, entry in entries.items():
                for fact in entry.get("facts") or []:
                    self.assertIn("program", fact, key)
                    self.assertIsNone(fact["program"], f"{key}: {fact}")


class TestFacts(AutostartTestCase):
    def test_facts_failure_no_false_changes(self):
        data_dir = self.data_dir()
        tool_target = "%ProgramFiles%\\Tool\\t.exe"
        tool_expanded = "C:\\Program Files\\Tool\\t.exe"
        vendor_target = "C:\\Apps\\Svc\\svc.exe"
        win_target = "C:\\Windows\\System32\\inventedwin.exe"
        new_svc_target = "C:\\Windows\\System32\\inventednew.exe"
        new_run_target = "C:\\Apps\\NewRun\\n.exe"

        programs = ok([win32("InventedTool", "Invented Tool",
                             install_location="C:\\Program Files\\Tool")])
        base_services = [service("InventedVendorSvc", f'"{vendor_target}"'),
                         service("InventedWinSvc", win_target)]
        base_runs = [run_value("InventedTray", f'"{tool_target}" --tray',
                               value_kind="ExpandString")]
        more_services = base_services + [service("InventedNewSvc", new_svc_target)]
        more_runs = base_runs + [run_value("InventedNewRun", new_run_target)]
        all_facts = facts(
            file_row(tool_target, expanded=tool_expanded, signer=VENDOR),
            file_row(vendor_target, signer=VENDOR),
            file_row(win_target),
            file_row(new_svc_target),
            file_row(new_run_target, signer=VENDOR),
        )
        tray = run_key("InventedTray")
        new_svc = "service:InventedNewSvc"
        new_run = run_key("InventedNewRun")
        tool_key = "win32:hklm64:InventedTool"

        first = self.collect(FakePowerShell({
            "win32_programs": programs,
            "services": ok(base_services),
            "run_keys": ok(base_runs),
            "file_facts": all_facts,
        }), data_dir=data_dir, now=NOW)
        self.assertEqual(self.first_fact(self.entry(first, tray)).get("program"), tool_key)

        second_responses = {
            "win32_programs": programs,
            "services": ok(more_services),
            "run_keys": ok(more_runs),
            "file_facts": failure("Invented signature query failure"),
        }
        second = self.collect(FakePowerShell(second_responses), data_dir=data_dir,
                              now=NOW + timedelta(days=1))

        changes = self.by_key(self.changes(second))
        self.assertEqual(set(changes), {new_svc, new_run}, changes)
        for change in changes.values():
            self.assertEqual(change.get("change"), "added", change)
        self.assert_no_own_changes(second)
        self.assertTrue(
            [item for item in self.not_checked(second) if "file_facts" in json.dumps(item)],
            second.get("not_checked"),
        )

        entries = self.all_entries(second)
        for key in (tray, "service:InventedVendorSvc", "service:InventedWinSvc"):
            self.assertIn(key, entries, sorted(entries))
            self.assertIs(entries[key].get("facts_from_baseline"), True, entries[key])
        tray_fact = self.first_fact(entries[tray])
        self.assertEqual(tray_fact.get("path"), tool_target, tray_fact)
        self.assertEqual(tray_fact.get("expanded_path"), tool_expanded, tray_fact)
        self.assertEqual(tray_fact.get("program"), tool_key, tray_fact)

        listed = self.listed(second)
        new_service = entries.get(new_svc)
        self.assertIsNotNone(new_service, sorted(entries))
        self.assertIn("own", new_service)
        self.assertIsNone(new_service["own"], new_service)
        self.assertIn("facts", new_service.get("unread_fields") or [], new_service)
        self.assert_facts_unread(new_service)
        self.assertNotIn(new_svc, listed)
        self.assertEqual(self.own_counts(second).get("unknown"), 1, self.own_counts(second))

        self.assertIn(new_run, listed, listed)
        self.assertIs(listed[new_run].get("own"), False, listed[new_run])

        third = self.collect(FakePowerShell(dict(second_responses, file_facts=all_facts)),
                             data_dir=data_dir, now=NOW + timedelta(days=2))
        self.assertEqual(self.changes(third), [])
        self.assert_no_own_changes(third)


class TestChanges(AutostartTestCase):
    def test_autostart_changes(self):
        data_dir = self.data_dir()
        vendor_target = "C:\\Apps\\Vendor\\vsvc.exe"
        ms_target = "C:\\Windows\\System32\\inventedms.exe"
        new_target = "C:\\Apps\\New\\new.exe"
        toggle_run = run_value("InventedToggle", "C:\\Apps\\Toggle\\toggle.exe")
        not_set_run = run_value("InventedNotSet", "C:\\Apps\\NotSet\\notset.exe")
        vendor_svc = service("InventedVendorSvc", f'"{vendor_target}"')
        common_files = [
            file_row("C:\\Apps\\Toggle\\toggle.exe", signer=VENDOR),
            file_row("C:\\Apps\\NotSet\\notset.exe", signer=VENDOR),
            file_row(new_target, signer=VENDOR),
            file_row(ms_target),
        ]

        self.collect(FakePowerShell({
            "run_keys": ok([toggle_run, not_set_run]),
            "startup_approved": ok([approved("InventedToggle", 2)]),
            "services": ok([vendor_svc]),
            "file_facts": facts(file_row(vendor_target, signer=VENDOR), *common_files),
        }), data_dir=data_dir, now=NOW)

        second = self.collect(FakePowerShell({
            "run_keys": ok([toggle_run, not_set_run,
                            run_value("InventedNew", new_target)]),
            "startup_approved": ok([approved("InventedToggle", 3),
                                    approved("InventedNotSet", 2)]),
            "services": ok([vendor_svc, service("InventedMsSvc", ms_target)]),
            "file_facts": facts(file_row(vendor_target, status="HashMismatch", signer=VENDOR),
                                *common_files),
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        changes = self.by_key(self.changes(second))
        self.assertEqual(
            set(changes),
            {run_key("InventedNew"), run_key("InventedToggle"), "service:InventedVendorSvc"},
            changes,
        )

        added = changes[run_key("InventedNew")]
        self.assertEqual(added.get("change"), "added", added)
        self.assertEqual(added.get("source"), "run_keys", added)

        toggled = changes[run_key("InventedToggle")]
        self.assertEqual(toggled.get("change"), "changed", toggled)
        self.assertEqual(toggled.get("source"), "run_keys", toggled)
        self.assertEqual(toggled.get("fields"),
                         {"enabled": {"before": True, "after": False}}, toggled)

        signature = changes["service:InventedVendorSvc"]
        self.assertEqual(signature.get("change"), "changed", signature)
        self.assertEqual(signature.get("source"), "services", signature)
        self.assertEqual(
            signature.get("fields"),
            {f"facts[{vendor_target}].signature_status":
             {"before": "Valid", "after": "HashMismatch"}},
            signature,
        )

        for change in changes.values():
            id_number(change.get("id"), "c")
        self.assertEqual(
            {k: self.own_changes(second).get(k) for k in ("added", "removed", "changed")},
            {"added": 1, "removed": 0, "changed": 0},
        )


class TestSources(AutostartTestCase):
    def test_each_source_statuses(self):
        single = "C:\\Apps\\Single\\s.exe"
        single_run = run_value("InventedSingle", single)
        cases = {
            "run_keys": ({"run_keys": ok(single_run)}, run_key("InventedSingle"), None),
            "startup_folders": (
                {"startup_folders": ok(startup_file(
                    "Invented Single.lnk", "C:\\Invented\\Startup\\Invented Single.lnk",
                    target=single, arguments="--min"))},
                "startup:user:Invented Single.lnk", None),
            "startup_approved": (
                {"run_keys": ok([single_run]),
                 "startup_approved": ok(approved("InventedSingle", 3))},
                run_key("InventedSingle"), ("approved", "disabled")),
            "scheduled_tasks": (
                {"scheduled_tasks": ok(task("InventedSingleTask", [exec_action(single)]))},
                "task:\\Invented\\InventedSingleTask", None),
            "services": (
                {"services": ok(service("InventedSingleSvc", single))},
                "service:InventedSingleSvc", None),
        }
        self.assertEqual(set(cases), set(ENTRY_SOURCES))
        for name, (responses, key, field) in cases.items():
            with self.subTest(source=name, case="failed job"):
                summary = self.collect(FakePowerShell(
                    {name: failure("Invented access failure 0x80070005")}
                ))
                self.assert_unreadable(summary, name)
                self.assertTrue(self.notes_about_source(summary, name),
                                summary.get("not_checked"))

            with self.subTest(source=name, case="single object"):
                summary = self.collect(FakePowerShell(
                    dict(responses, file_facts=facts(file_row(single, signer=VENDOR)))
                ))
                self.assertEqual(self.source(summary, name).get("status"), "read")
                entry = self.entry(summary, key)
                if field is not None:
                    self.assertEqual(entry.get(field[0]), field[1], entry)

        with self.subTest(case="startup_approved unread between runs"):
            data_dir = self.data_dir()
            off = run_value("InventedOff", "C:\\Apps\\Off\\off.exe")
            late = run_value("InventedLate", "C:\\Apps\\Late\\late.exe")
            files = facts(file_row("C:\\Apps\\Off\\off.exe", signer=VENDOR),
                          file_row("C:\\Apps\\Late\\late.exe", signer=VENDOR))

            self.collect(FakePowerShell({
                "run_keys": ok([off]),
                "startup_approved": ok([approved("InventedOff", 3)]),
                "file_facts": files,
            }), data_dir=data_dir, now=NOW)

            second = self.collect(FakePowerShell({
                "run_keys": ok([off, late]),
                "startup_approved": failure("Invented registry read failure"),
                "file_facts": files,
            }), data_dir=data_dir, now=NOW + timedelta(days=1))
            changes = self.by_key(self.changes(second))
            self.assertEqual(set(changes), {run_key("InventedLate")}, changes)
            self.assertEqual(changes[run_key("InventedLate")].get("change"), "added")
            late_entry = self.entry(second, run_key("InventedLate"))
            self.assertIn("enabled", late_entry.get("unread_fields") or [], late_entry)

            third = self.collect(FakePowerShell({
                "run_keys": ok([off, late]),
                "startup_approved": ok([approved("InventedOff", 3),
                                        approved("InventedLate", 2)]),
                "file_facts": files,
            }), data_dir=data_dir, now=NOW + timedelta(days=2))
            self.assertEqual(self.changes(third), [])

        with self.subTest(case="win32_programs unread"):
            data_dir = self.data_dir()
            target = "C:\\Apps\\Tool\\x.exe"
            base = {
                "run_keys": ok([run_value("InventedToolTray", target)]),
                "file_facts": facts(file_row(target, signer=VENDOR)),
            }
            first = self.collect(FakePowerShell(dict(base, win32_programs=ok([
                win32("InventedTool", "Invented Tool", install_location="C:\\Apps\\Tool"),
            ]))), data_dir=data_dir, now=NOW)
            self.assertEqual(
                self.first_fact(self.entry(first, run_key("InventedToolTray"))).get("program"),
                "win32:hklm64:InventedTool",
            )

            second = self.collect(FakePowerShell(dict(
                base, win32_programs=failure("Invented uninstall key read failure")
            )), data_dir=data_dir, now=NOW + timedelta(days=1))
            self.assert_unreadable(second, "win32_programs")
            self.assertEqual(self.changes(second), [])


class TestApprovedUnknown(AutostartTestCase):
    """A ``StartupApproved`` value of unknown meaning leaves ``enabled`` unread
    (plan 074, milestone M2, criteria K2-K4)."""

    ODD_TARGET = "C:\\Invented\\Odd\\odd.exe"
    ODD = run_value("InventedOdd", ODD_TARGET)

    def odd_responses(self, approved_rows):
        responses = clean_responses(extra_files=[file_row(self.ODD_TARGET, signer=VENDOR)])
        responses["run_keys"] = ok([self.ODD])
        responses["startup_approved"] = ok(approved_rows)
        return responses

    def test_unknown_value_leaves_enabled_unread(self):
        with self.subTest(case="first byte 6"):
            summary = self.collect(FakePowerShell(self.odd_responses(
                [approved("InventedOdd", 6)])))
            odd = self.entry(summary, run_key("InventedOdd"))
            self.assertEqual(odd.get("approved"), "unknown", odd)
            self.assertEqual(odd.get("approved_byte"), 6, odd)
            self.assertIn("enabled", odd, odd)
            self.assertIsNone(odd["enabled"], odd)
            self.assertIn("enabled", odd.get("unread_fields") or [], odd)

        with self.subTest(case="value not binary"):
            summary = self.collect(FakePowerShell(self.odd_responses(
                [{"Hive": "hkcu", "Key": "Run", "Name": "InventedOdd", "Bytes": None}])))
            odd = self.entry(summary, run_key("InventedOdd"))
            self.assertEqual(odd.get("approved"), "unknown", odd)
            self.assertIn("enabled", odd, odd)
            self.assertIsNone(odd["enabled"], odd)
            self.assertIn("enabled", odd.get("unread_fields") or [], odd)

    def test_known_values_have_no_unread_fields(self):
        targets = {
            "InventedOn": "C:\\Invented\\On\\on.exe",
            "InventedOff": "C:\\Invented\\Off\\off.exe",
            "InventedPlain": "C:\\Invented\\Plain\\plain.exe",
        }
        responses = clean_responses(
            extra_files=[file_row(path, signer=VENDOR) for path in targets.values()])
        responses["run_keys"] = ok([run_value(name, path) for name, path in targets.items()])
        responses["startup_approved"] = ok([approved("InventedOn", 2),
                                            approved("InventedOff", 3)])
        summary = self.collect(FakePowerShell(responses))
        self.assertEqual(self.source(summary, "startup_approved").get("status"), "read")

        for name, state, enabled in (("InventedOn", "enabled", True),
                                     ("InventedOff", "disabled", False),
                                     ("InventedPlain", "not_set", True)):
            with self.subTest(entry=name):
                entry = self.entry(summary, run_key(name))
                self.assertEqual(entry.get("approved"), state, entry)
                self.assertIs(entry.get("enabled"), enabled, entry)
                self.assertFalse(entry.get("unread_fields"), entry)

    def test_unknown_value_is_no_change(self):
        data_dir = self.data_dir()
        key = run_key("InventedOdd")
        self.collect(FakePowerShell(self.odd_responses([approved("InventedOdd", 2)])),
                     data_dir=data_dir, now=NOW)
        second = self.collect(FakePowerShell(self.odd_responses([approved("InventedOdd", 6)])),
                              data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.comparison(second).get("run_keys"), "compared",
                         self.comparison(second))
        self.assertEqual(self.entry(second, key).get("approved_byte"), 6)
        enabled_changes = [c for c in self.changes(second)
                           if c.get("key") == key or "enabled" in (c.get("fields") or {})]
        self.assertEqual(enabled_changes, [], enabled_changes)


class TestNewLaunchers(AutostartTestCase):
    """Microsoft-signed programs that run any code are launchers (plan 074, M2, K5-K6)."""

    def test_control_task_is_listed(self):
        control = "C:\\Windows\\System32\\control.exe"
        key = "task:\\Invented\\InventedControlTask"
        responses = clean_responses(extra_files=[file_row(control)])
        responses["scheduled_tasks"] = ok(list(responses["scheduled_tasks"][1]) + [
            task("InventedControlTask",
                 [exec_action(control, "C:\\Invented\\Panel\\invented.cpl")],
                 triggers=(LOGON,)),
        ])
        summary = self.collect(FakePowerShell(responses))

        entry = self.entry(summary, key)
        fact = self.first_fact(entry)
        self.assertEqual(fact.get("path"), control, fact)
        self.assertIs(fact.get("exists"), True, fact)
        self.assertEqual(fact.get("signature_status"), "Valid", fact)
        self.assertEqual(fact.get("signer"), MS, fact)
        self.assertIs(entry.get("own"), False, entry)

        listed = self.listed(summary)
        self.assertIn(key, listed, listed)
        self.assertIs(listed[key].get("own"), False, listed[key])

    def test_svchost_service_stays_own(self):
        host = "C:\\WINDOWS\\system32\\svchost.exe -k InventedNetGroup -p"
        dll = "%SystemRoot%\\System32\\inventednet.dll"
        key = "service:InventedNetSvc"
        responses = clean_responses(extra_files=[
            file_row(dll, expanded="C:\\Windows\\System32\\inventednet.dll"),
            file_row("C:\\WINDOWS\\system32\\svchost.exe"),
        ])
        responses["services"] = ok(list(responses["services"][1]) + [
            service("InventedNetSvc", host, type_=SHARE_PROCESS, service_dll=dll),
        ])
        summary = self.collect(FakePowerShell(responses))

        entry = self.entry(summary, key)
        self.assertEqual(entry.get("targets"), [dll], entry)
        self.assertIs(entry.get("own"), True, entry)
        self.assertNotIn(key, self.listed(summary))
        self.assertEqual(summary.get("autostart"), [])


if __name__ == "__main__":
    unittest.main()

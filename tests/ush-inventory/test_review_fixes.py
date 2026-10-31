"""Regression tests for the M3 code-review findings of plan 048 (ush-inventory).

A target file or a service whose values could not be read in this run is no change:
it keeps what the previous baseline knew. Every value is invented.
"""

import re
import unittest
from datetime import timedelta

from tests.skill_loader import load_script

from .fakes import NOW, FakePowerShell, ok
from .fakes_autostart import (
    CLEAN_SERVICES,
    SHARE_PROCESS,
    USER_SERVICE_INSTANCE,
    clean_responses,
    facts,
    file_row,
    run_value,
    service,
)
from .test_autostart import AutostartTestCase, run_key

HOST = "C:\\WINDOWS\\system32\\svchost.exe -k InventedGroup -p"

STEADY_EXE = "C:\\Windows\\System32\\inventedsteady.exe"
STEADY_ROW = service("InventedSteadySvc", STEADY_EXE)

UNREAD_FIELDS = ("targets", "facts", "delayed", "user_service")


def file_error(path):
    return {"Kind": "file", "Path": path, "Error": "Invented access denied"}


def registry_error(name, path_name=HOST):
    """A ``services`` row whose registry values could not be read: ``Type``,
    ``DelayedAutostart``, the ``ServiceDll`` fields and ``TemplateStart`` stay null."""
    row = service(name, path_name, type_=None, delayed=None)
    row["Error"] = "Invented registry failure"
    return row


def steady_fake(*rows, files=()):
    """A run with one always-readable service plus ``rows``."""
    return FakePowerShell({
        "services": ok([STEADY_ROW, *rows]),
        "file_facts": facts(file_row(STEADY_EXE), *files),
    })


class TestUnreadFile(AutostartTestCase):
    def test_file_error_keeps_previous_facts(self):
        data_dir = self.data_dir()
        known = "C:\\Windows\\System32\\inventedknown.exe"
        new = "C:\\Windows\\System32\\inventednew.exe"
        known_key, new_key = "service:InventedKnownSvc", "service:InventedNewSvc"

        first = self.collect(FakePowerShell({
            "services": ok([service("InventedKnownSvc", known)]),
            "file_facts": facts(file_row(known)),
        }), data_dir=data_dir, now=NOW)
        self.assertIs(self.entry(first, known_key).get("own"), True)

        second = self.collect(FakePowerShell({
            "services": ok([service("InventedKnownSvc", known),
                            service("InventedNewSvc", new)]),
            "file_facts": facts(file_error(known), file_error(new)),
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        changes = self.by_key(self.changes(second))
        self.assertEqual(set(changes), {new_key}, changes)
        self.assert_no_own_changes(second)
        entry = self.entry(second, known_key)
        self.assertIs(entry.get("own"), True, entry)
        self.assertIs(entry.get("facts_from_baseline"), True, entry)
        self.assertIs(self.first_fact(entry).get("exists"), True, entry)
        self.assertIsNone(self.entry(second, new_key).get("own"))
        self.assertTrue([item for item in self.not_checked(second) if known in str(item.get("what"))],
                        second.get("not_checked"))


class TestUnreadService(AutostartTestCase):
    def test_registry_error_keeps_previous_entry(self):
        data_dir = self.data_dir()
        dll = "%SystemRoot%\\System32\\inventeddll.dll"
        widget_dll = "%SystemRoot%\\System32\\inventedwidget.dll"
        file_facts = facts(file_row(dll), file_row(widget_dll))

        first = self.collect(FakePowerShell({
            "services": ok([
                service("InventedDllSvc", HOST, type_=SHARE_PROCESS, service_dll=dll),
                service("WidgetUserSvc_1a2b", HOST, type_=USER_SERVICE_INSTANCE,
                        template_service_dll=widget_dll, template_start=2),
            ]),
            "file_facts": file_facts,
        }), data_dir=data_dir, now=NOW)
        self.assertIn("service:WidgetUserSvc", self.all_entries(first))

        failed = service("InventedDllSvc", HOST, type_=SHARE_PROCESS)
        failed["Error"] = "Invented registry failure"
        widget = service("WidgetUserSvc_9f8e", HOST, type_=None)
        widget["Error"] = "Invented registry failure"
        second = self.collect(FakePowerShell({
            "services": ok([failed, widget]),
            "file_facts": file_facts,
        }), data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertEqual(self.changes(second), [])
        self.assert_no_own_changes(second)
        entries = self.all_entries(second)
        self.assertIn("service:WidgetUserSvc", entries, sorted(entries))
        self.assertNotIn("service:WidgetUserSvc_9f8e", entries)
        self.assertEqual(entries["service:InventedDllSvc"].get("targets"), [dll])

    def test_template_row_does_not_hide_instance(self):
        """The template listed next to its instance: still one per-user entry, whatever
        the row order, and a later unread instance is no change."""
        data_dir = self.data_dir()
        dll = "%SystemRoot%\\System32\\inventedwidget.dll"
        key = "service:WidgetUserSvc"
        template = service("WidgetUserSvc", HOST, state="Stopped", type_=0x60)
        instance = service("WidgetUserSvc_1a2b", HOST, type_=USER_SERVICE_INSTANCE,
                           template_service_dll=dll, template_start=2)
        for order in ([template, instance], [instance, template]):
            with self.subTest(order=[row["Name"] for row in order]):
                summary = self.collect(FakePowerShell({
                    "services": ok(order), "file_facts": facts(file_row(dll)),
                }))
                entry = self.entry(summary, key)
                self.assertIs(entry.get("user_service"), True, entry)
                self.assertEqual(entry.get("template_start"), 2, entry)
                self.assertEqual(entry.get("targets"), [dll], entry)
                self.assertEqual(entry.get("state"), "Running", entry)

        self.collect(FakePowerShell({
            "services": ok([template, instance]), "file_facts": facts(file_row(dll)),
        }), data_dir=data_dir, now=NOW)
        unread = service("WidgetUserSvc_9f8e", HOST, type_=None)
        unread["Error"] = "Invented registry failure"
        second = self.collect(FakePowerShell({
            "services": ok([template, unread]), "file_facts": facts(file_row(dll)),
        }), data_dir=data_dir, now=NOW + timedelta(days=1))
        self.assertEqual(self.changes(second), [])
        self.assertNotIn("service:WidgetUserSvc_9f8e", self.all_entries(second))


class TestUnreadNewService(AutostartTestCase):
    """A service whose registry could not be read and that no previous baseline knows
    (plan 070, M2): its unread fields are named, and a later clean read is no change."""

    def service_changes(self, summary, prefix):
        return [c for c in self.changes(summary) if str(c.get("key")).startswith(prefix)]

    def test_shared_service_read_later_is_no_change(self):
        data_dir = self.data_dir()
        dll = "%SystemRoot%\\System32\\inventedshared.dll"
        key = "service:InventedSharedSvc"

        self.collect(steady_fake(), data_dir=data_dir, now=NOW)
        self.collect(steady_fake(registry_error("InventedSharedSvc")),
                     data_dir=data_dir, now=NOW + timedelta(days=1))
        third = self.collect(steady_fake(
            service("InventedSharedSvc", HOST, type_=SHARE_PROCESS, service_dll=dll),
            files=(file_row(dll),),
        ), data_dir=data_dir, now=NOW + timedelta(days=2))

        self.assertIn(key, self.all_entries(third), sorted(self.all_entries(third)))
        changed = [c for c in self.changes(third)
                   if c.get("key") == key and c.get("change") == "changed"]
        self.assertEqual(changed, [], changed)

    def test_user_instance_read_later_is_no_change(self):
        data_dir = self.data_dir()
        dll = "%SystemRoot%\\System32\\inventeduser.dll"
        key = "service:InventedUserSvc"

        self.collect(steady_fake(), data_dir=data_dir, now=NOW)
        second = self.collect(steady_fake(registry_error("InventedUserSvc_1a2b3")),
                              data_dir=data_dir, now=NOW + timedelta(days=1))
        entries = self.all_entries(second)
        self.assertIn(key, entries, sorted(entries))
        self.assertNotIn("service:InventedUserSvc_1a2b3", entries, sorted(entries))

        third = self.collect(steady_fake(
            service("InventedUserSvc_1a2b3", HOST, type_=USER_SERVICE_INSTANCE,
                    template_service_dll=dll, template_start=2),
            files=(file_row(dll),),
        ), data_dir=data_dir, now=NOW + timedelta(days=2))

        flips = [c for c in self.service_changes(third, "service:InventedUserSvc")
                 if c.get("change") in ("added", "removed")]
        self.assertEqual(flips, [], flips)

    def test_known_plain_service_keeps_full_key(self):
        data_dir = self.data_dir()
        exe = "C:\\Windows\\System32\\inventedab.exe"
        key = "service:Invented_ab"

        responses = clean_responses(extra_files=(file_row(exe),))
        responses["services"] = ok(list(CLEAN_SERVICES) + [service("Invented_ab", exe)])
        first = self.collect(FakePowerShell(responses), data_dir=data_dir, now=NOW)
        self.assertIn(key, self.all_entries(first), sorted(self.all_entries(first)))

        responses = clean_responses(extra_files=(file_row(exe),))
        responses["services"] = ok(list(CLEAN_SERVICES) + [registry_error("Invented_ab", exe)])
        second = self.collect(FakePowerShell(responses), data_dir=data_dir,
                              now=NOW + timedelta(days=1))

        entries = self.all_entries(second)
        self.assertIn(key, entries, sorted(entries))
        self.assertNotIn("service:Invented", entries, sorted(entries))
        self.assertEqual(entries[key].get("targets"), [exe], entries[key])
        self.assertIs(entries[key].get("user_service"), False, entries[key])
        flips = [c for c in self.service_changes(second, "service:Invented")
                 if c.get("change") in ("added", "removed")]
        self.assertEqual(flips, [], flips)

    def test_unread_new_service_fields(self):
        data_dir = self.data_dir()
        key = "service:InventedSharedSvc"

        self.collect(steady_fake(), data_dir=data_dir, now=NOW)
        second = self.collect(steady_fake(registry_error("InventedSharedSvc")),
                              data_dir=data_dir, now=NOW + timedelta(days=1))

        entry = self.entry(second, key)
        unread = entry.get("unread_fields") or []
        for field in UNREAD_FIELDS:
            self.assertIn(field, unread, entry)
        self.assertIn("delayed", entry, entry)
        self.assertIsNone(entry.get("delayed"), entry)
        self.assertIn("own", entry, entry)
        self.assertIsNone(entry.get("own"), entry)

        # The not_checked item about autostart facts names the registry as the cause.
        about_facts = [item for item in self.not_checked(second)
                       if "autostart" in str(item).lower() or "fact" in str(item).lower()]
        self.assertTrue(about_facts, second.get("not_checked"))
        self.assertTrue(
            [item for item in about_facts if "registry" in str(item.get("reason")).lower()],
            about_facts,
        )

    def test_unread_exe_service_keeps_its_facts(self):
        """A service outside svchost.exe starts its PathName, read from Win32_Service:
        its target and facts stay checked when only its registry values failed."""
        data_dir = self.data_dir()
        exe = "C:\\Invented\\inventedagent.exe"
        key = "service:InventedAgentSvc"

        self.collect(steady_fake(), data_dir=data_dir, now=NOW)
        second = self.collect(steady_fake(registry_error("InventedAgentSvc", exe),
                                          files=(file_row(exe, signer="Invented Soft"),)),
                              data_dir=data_dir, now=NOW + timedelta(days=1))

        entry = self.entry(second, key)
        unread = entry.get("unread_fields") or []
        self.assertEqual(sorted(unread), ["delayed", "user_service"], entry)
        self.assertEqual(entry.get("targets"), [exe], entry)
        self.assertIs(entry.get("own"), False, entry)

    def test_repeated_unread_instance_keeps_template_key(self):
        data_dir = self.data_dir()
        key = "service:InventedUserSvc"
        summaries = []
        for n in range(2):
            summaries.append(self.collect(
                steady_fake(registry_error("InventedUserSvc_1a2b3")),
                data_dir=data_dir, now=NOW + timedelta(days=n)))

        for n, summary in enumerate(summaries, start=1):
            with self.subTest(run=n):
                entries = self.all_entries(summary)
                self.assertIn(key, entries, sorted(entries))
                self.assertNotIn("service:InventedUserSvc_1a2b3", entries, sorted(entries))
        flips = [c for c in self.service_changes(summaries[1], "service:InventedUserSvc")
                 if c.get("change") in ("added", "removed")]
        self.assertEqual(flips, [], flips)

    def test_missing_type_marks_user_service_unread(self):
        row = service("InventedUserSvc_1a2b3", HOST, type_=None)
        summary = self.collect(steady_fake(row))

        entries = self.all_entries(summary)
        matching = [entry for k, entry in entries.items()
                    if str(k).startswith("service:InventedUserSvc")]
        self.assertEqual(len(matching), 1, sorted(entries))
        entry = matching[0]
        self.assertIn("user_service", entry.get("unread_fields") or [], entry)

    def test_short_suffix_is_not_guessed(self):
        """Plan 080, M2 K1: without ``Type`` and without a baseline, a suffix of fewer
        than 5 hex digits is part of the name, not an instance suffix."""
        data_dir = self.data_dir()
        exe_short = "C:\\Invented\\Tool\\inventedtool1a.exe"
        exe_long = "C:\\Invented\\Tool\\inventedtool1a2b.exe"
        keys = ("service:InventedTool_1a", "service:InventedTool_1a2b")

        def responses():
            result = clean_responses(extra_files=(
                file_row(exe_short, signer="Invented Soft"),
                file_row(exe_long, signer="Invented Soft"),
            ))
            result["services"] = ok(list(CLEAN_SERVICES) + [
                registry_error("InventedTool_1a", exe_short),
                registry_error("InventedTool_1a2b", exe_long),
            ])
            return result

        first = self.collect(FakePowerShell(responses()), data_dir=data_dir, now=NOW)
        entries = self.all_entries(first)
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, entries, sorted(entries))
                self.assertIsNot(entries[key].get("user_service"), True, entries[key])
        self.assertNotIn("service:InventedTool", entries, sorted(entries))

        second = self.collect(FakePowerShell(responses()), data_dir=data_dir,
                              now=NOW + timedelta(days=1))
        entries = self.all_entries(second)
        for key in keys:
            self.assertIn(key, entries, sorted(entries))
        self.assertNotIn("service:InventedTool", entries, sorted(entries))
        tool_changes = self.service_changes(second, "service:InventedTool")
        self.assertEqual(tool_changes, [], tool_changes)

    def test_five_hex_suffix_is_guessed(self):
        """Plan 080, M2 K2: without ``Type`` and without a baseline, a suffix of 5 hex
        digits marks a per-user instance, keyed by its template."""
        summary = self.collect(steady_fake(registry_error("InventedUserSvc_1a2b3")),
                               data_dir=self.data_dir(), now=NOW)

        entries = self.all_entries(summary)
        self.assertIn("service:InventedUserSvc", entries, sorted(entries))
        self.assertNotIn("service:InventedUserSvc_1a2b3", entries, sorted(entries))


class TestApprovedNotBinary(AutostartTestCase):
    def test_not_binary_value_is_not_not_set(self):
        summary = self.collect(FakePowerShell({
            "run_keys": ok([run_value("InventedOdd", "C:\\Apps\\Odd\\odd.exe"),
                            run_value("InventedPlain", "C:\\Apps\\Plain\\plain.exe")]),
            "startup_approved": ok([{"Hive": "hkcu", "Key": "Run", "Name": "InventedOdd",
                                     "Bytes": None}]),
        }))
        odd = self.entry(summary, run_key("InventedOdd"))
        self.assertEqual(odd.get("approved"), "unknown", odd)
        self.assertIsNone(odd.get("approved_byte"), odd)
        self.assertTrue([item for item in self.not_checked(summary)
                         if "InventedOdd" in str(item.get("what"))], summary.get("not_checked"))
        plain = self.entry(summary, run_key("InventedPlain"))
        self.assertEqual(plain.get("approved"), "not_set", plain)


class TestFileFactsSearch(unittest.TestCase):
    """The PATH search list of the file-facts script (plan 074, M2 K1).

    The fake PowerShell never runs the script text, so this checks its shape.
    """

    @staticmethod
    def block_after(text, start):
        """Return the braced block that opens at the first ``{`` after ``start``."""
        open_at = text.index("{", start)
        depth = 0
        for at in range(open_at, len(text)):
            if text[at] == "{":
                depth += 1
            elif text[at] == "}":
                depth -= 1
                if depth == 0:
                    return text[open_at:at + 1]
        raise AssertionError("unbalanced braces after " + text[start:start + 40])

    def test_bad_path_entry_is_skipped(self):
        body = load_script("ush-inventory", "inventory").FILE_FACTS_BODY
        files_loop = body.index("foreach ($p in $paths)")
        before = body[:files_loop]
        self.assertIn("$search =", before, "no $search assignment before the files loop")
        built = before[before.index("$search ="):]
        self.assertIn("ExpandEnvironmentVariables", built)
        self.assertIn(".Trim('\"')", built)
        self.assertIn("IndexOfAny", built)
        self.assertIn("GetInvalidPathChars()", built)
        self.assertLess(built.index("ExpandEnvironmentVariables"), built.index("IndexOfAny"),
                        "entries are filtered before they are expanded")

        loop = body[files_loop:]
        self.assertNotIn("ExpandEnvironmentVariables($dir)", loop)
        inner = self.block_after(loop, loop.index("foreach ($dir in $search)"))
        self.assertIn("Combine", inner)
        self.assertNotIn("try", inner)
        self.assertIn("try", loop[:loop.index("foreach ($dir in $search)")],
                      "Combine must stay inside the per-file try")


# The order in which the services job reads the registry values of one service
# (plan 083, M1); a row whose read failed at one of them has it and every later one null.
SERVICE_READ_ORDER = ("Type", "DelayedAutostart", "ServiceDll", "KeyServiceDll",
                      "TemplateServiceDll", "TemplateKeyServiceDll", "TemplateStart")

REGISTRY_FAILURE = "Invented registry failure"


def partial_read(name, error_at, path_name=HOST, **fields):
    """A ``services`` row whose registry read stopped at ``error_at``: the values read
    before it keep what ``fields`` gives, ``error_at`` and every later value are null."""
    row = service(name, path_name, **fields)
    for value_name in SERVICE_READ_ORDER[SERVICE_READ_ORDER.index(error_at):]:
        row[value_name] = None
    row["Error"] = REGISTRY_FAILURE
    row["ErrorAt"] = error_at
    return row


class TestPartialServiceRead(AutostartTestCase):
    """A service whose registry read failed part way keeps the values read before the
    failure (plan 083, M1). Every value is invented; the baseline is empty unless a test
    runs twice on one data directory."""

    def target_changes(self, summary, key):
        """``changed`` items of ``key`` with a ``targets`` field, from the summary and
        from the detail file (changes of own entries are only in the detail file)."""
        items = list(self.changes(summary)) + list(self.detail(summary).get("changes") or [])
        return [c for c in items
                if c.get("key") == key and c.get("change") == "changed"
                and any(f == "targets" or str(f).startswith("targets[")
                        for f in (c.get("fields") or {}))]

    def services_item(self, summary, name):
        whats = [(item, str(item.get("what"))) for item in self.not_checked(summary)]
        items = [item for item, what in whats if what.startswith("services") and name in what]
        self.assertEqual(len(items), 1, summary.get("not_checked"))
        return items[0]

    def test_error_at_service_dll_keeps_type_and_delayed(self):
        row = partial_read("InventedSharedSvc", "ServiceDll", type_=SHARE_PROCESS, delayed=1)
        summary = self.collect(steady_fake(row))

        entry = self.entry(summary, "service:InventedSharedSvc")
        self.assertIs(entry.get("delayed"), True, entry)
        self.assertIs(entry.get("user_service"), False, entry)
        self.assertEqual(sorted(entry.get("unread_fields") or []), ["facts", "targets"], entry)
        self.assertIn("own", entry, entry)
        self.assertIsNone(entry.get("own"), entry)

    def test_read_service_dll_is_checked(self):
        dll = "%SystemRoot%\\System32\\inventedpartial.dll"
        row = partial_read("InventedSharedSvc", "KeyServiceDll", type_=SHARE_PROCESS,
                           service_dll=dll)
        summary = self.collect(steady_fake(row, files=(file_row(dll),)))

        entry = self.entry(summary, "service:InventedSharedSvc")
        self.assertEqual(entry.get("targets"), [dll], entry)
        self.assertFalse(entry.get("unread_fields"), entry)
        self.assertIs(entry.get("own"), True, entry)
        self.assertEqual(self.own_counts(summary).get("unknown"), 0, self.own_counts(summary))

    def test_unread_template_dll_keeps_target_unread(self):
        instance_dll = "%SystemRoot%\\System32\\inventedinstance.dll"
        row = partial_read("InventedUserSvc_1a2b3", "TemplateServiceDll",
                           type_=USER_SERVICE_INSTANCE, delayed=1, service_dll=instance_dll)
        summary = self.collect(steady_fake(row, files=(file_row(instance_dll),)))

        entries = self.all_entries(summary)
        self.assertIn("service:InventedUserSvc", entries, sorted(entries))
        self.assertNotIn("service:InventedUserSvc_1a2b3", entries, sorted(entries))
        entry = entries["service:InventedUserSvc"]
        unread = entry.get("unread_fields") or []
        self.assertIs(entry.get("user_service"), True, entry)
        self.assertNotIn("user_service", unread, entry)
        self.assertIs(entry.get("delayed"), True, entry)
        self.assertNotIn("delayed", unread, entry)
        self.assertIn("targets", unread, entry)
        self.assertIn("facts", unread, entry)

    def test_error_without_step_reads_nothing(self):
        cases = (
            ("no ErrorAt", registry_error("InventedNoStepSvc"), "service:InventedNoStepSvc"),
            ("ErrorAt Type", partial_read("InventedTypeStepSvc", "Type"),
             "service:InventedTypeStepSvc"),
        )
        for label, row, key in cases:
            with self.subTest(case=label):
                summary = self.collect(steady_fake(row))
                entry = self.entry(summary, key)
                unread = entry.get("unread_fields") or []
                for field in UNREAD_FIELDS:
                    self.assertIn(field, unread, entry)
                self.assertIn("delayed", entry, entry)
                self.assertIsNone(entry.get("delayed"), entry)
                self.assertIn("own", entry, entry)
                self.assertIsNone(entry.get("own"), entry)

    def test_clean_services_have_no_unread_fields(self):
        summary = self.collect(FakePowerShell(clean_responses()))

        entries = self.all_entries(summary)
        self.assertIn("service:InventedHostSvc", entries, sorted(entries))
        services = {k: e for k, e in entries.items() if str(k).startswith("service:")}
        self.assertTrue(services, sorted(entries))
        for key, entry in services.items():
            with self.subTest(key=key):
                self.assertFalse(entry.get("unread_fields"), entry)
        for item in self.not_checked(summary):
            what = str(item.get("what"))
            self.assertFalse(what.startswith("services"), item)
            self.assertNotIn("autostart facts", what, item)

    def test_read_target_is_compared(self):
        data_dir = self.data_dir()
        key = "service:InventedSharedSvc"
        first_dll = "%SystemRoot%\\System32\\inventedfirst.dll"
        second_dll = "%SystemRoot%\\System32\\inventedsecond.dll"

        self.collect(steady_fake(
            partial_read("InventedSharedSvc", "KeyServiceDll", type_=SHARE_PROCESS,
                         service_dll=first_dll),
            files=(file_row(first_dll),),
        ), data_dir=data_dir, now=NOW)
        second = self.collect(steady_fake(
            service("InventedSharedSvc", HOST, type_=SHARE_PROCESS, service_dll=second_dll),
            files=(file_row(second_dll),),
        ), data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertTrue(self.target_changes(second, key),
                        (self.changes(second), self.detail(second).get("changes")))

    def test_body_records_error_step(self):
        inventory = self.inventory
        body = inventory.SERVICES_BODY
        self.assertEqual(tuple(getattr(inventory, "SERVICE_READ_ORDER", ())), SERVICE_READ_ORDER)

        steps = []
        for name in SERVICE_READ_ORDER:
            found = list(re.finditer(r"\$at\s*=\s*'" + name + r"'", body))
            self.assertEqual(len(found), 1, f"$at = '{name}' must appear exactly once")
            steps.append(found[0])
            first_row = re.search(r"\$row\.(\w+)\s*=(?!=)", body[found[0].end():])
            self.assertIsNotNone(first_row, f"no $row. assignment after $at = '{name}'")
            self.assertEqual(first_row.group(1), name,
                             f"first $row. assignment after $at = '{name}'")
        starts = [step.start() for step in steps]
        self.assertEqual(starts, sorted(starts), "steps are not in SERVICE_READ_ORDER")

        tries = [m.start() for m in re.finditer(r"\btry\s*\{", body[:starts[0]])]
        self.assertTrue(tries, "no try before the first step")
        loops = [m.start() for m in re.finditer(r"foreach", body[:tries[-1]], re.IGNORECASE)]
        self.assertTrue(loops, "no loop before the try of the steps")
        self.assertRegex(body[loops[-1]:tries[-1]], r"\$at\s*=\s*(\$null|''|\"\")",
                         "$at is not reset in the loop before the try")

        catch = re.search(r"\bcatch\b", body[starts[-1]:])
        self.assertIsNotNone(catch, "no catch after the last step")
        block = TestFileFactsSearch.block_after(body, starts[-1] + catch.start())
        self.assertRegex(block, r"ErrorAt\s*=\s*\$at\b", "catch does not record ErrorAt from $at")

    def test_unread_target_is_not_compared(self):
        data_dir = self.data_dir()
        key = "service:InventedSharedSvc"
        dll = "%SystemRoot%\\System32\\inventedlater.dll"

        self.collect(steady_fake(
            partial_read("InventedSharedSvc", "ServiceDll", type_=SHARE_PROCESS, delayed=1),
        ), data_dir=data_dir, now=NOW)
        second = self.collect(steady_fake(
            service("InventedSharedSvc", HOST, type_=SHARE_PROCESS, delayed=1, service_dll=dll),
            files=(file_row(dll),),
        ), data_dir=data_dir, now=NOW + timedelta(days=1))

        self.assertIn(key, self.all_entries(second), sorted(self.all_entries(second)))
        self.assertEqual(self.target_changes(second, key), [])

    def test_reason_names_error_step(self):
        with self.subTest(case="ErrorAt ServiceDll"):
            summary = self.collect(steady_fake(
                partial_read("InventedStepSvc", "ServiceDll", type_=SHARE_PROCESS)))
            reason = str(self.services_item(summary, "InventedStepSvc").get("reason"))
            self.assertTrue(reason.startswith("registry values not read"), reason)
            self.assertIn("ServiceDll", reason)

        with self.subTest(case="no ErrorAt"):
            summary = self.collect(steady_fake(registry_error("InventedNoStepSvc")))
            reason = self.services_item(summary, "InventedNoStepSvc").get("reason")
            self.assertEqual(reason, f"registry values not read: {REGISTRY_FAILURE}")


if __name__ == "__main__":
    unittest.main()

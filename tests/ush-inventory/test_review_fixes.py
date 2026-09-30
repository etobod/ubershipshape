"""Regression tests for the M3 code-review findings of plan 048 (ush-inventory).

A target file or a service whose values could not be read in this run is no change:
it keeps what the previous baseline knew. Every value is invented.
"""

import unittest
from datetime import timedelta

from .fakes import NOW, FakePowerShell, ok
from .fakes_autostart import (
    SHARE_PROCESS,
    USER_SERVICE_INSTANCE,
    facts,
    file_row,
    run_value,
    service,
)
from .test_autostart import AutostartTestCase, run_key

HOST = "C:\\WINDOWS\\system32\\svchost.exe -k InventedGroup -p"


def file_error(path):
    return {"Kind": "file", "Path": path, "Error": "Invented access denied"}


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


if __name__ == "__main__":
    unittest.main()

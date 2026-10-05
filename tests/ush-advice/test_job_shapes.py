"""Job result shapes of skills/ush-advice/scripts/advice.py (plan 139, M1): a single
object instead of a list gives the same facts, ``sources`` names the status of each job
(``read``, ``empty``, ``unreadable``), and a missing ``firmware`` field value is null.

The interface is described in ``fakes.py`` and in
``skills/ush-advice/references/summary-contract.md``. PowerShell never starts; every
value is invented.
"""

import unittest

from .fakes import (
    JOBS,
    AdviceTestCase,
    FakePowerShell,
    failure,
    firmware_row,
    hotfix_row,
    ok,
    os_version_row,
)

VERSION_FIELDS = ("display_version", "build", "ubr", "edition_id", "architecture",
                  "product")


class TestJobShapes(AdviceTestCase):
    def source(self, summary, name):
        sources = summary.get("sources")
        self.assertIsInstance(sources, list, summary)
        found = [entry for entry in sources if entry.get("name") == name]
        self.assertEqual(len(found), 1, f"sources entries named {name}: {sources}")
        return found[0]

    def job_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if str(item.get("what")).startswith("job ")]

    def test_single_hotfix_object(self):
        fake = FakePowerShell({"hotfixes": ok(hotfix_row("KB5099901"))})
        summary = self.collect(fake)
        facts = self.machine_of(summary)
        self.assertEqual(facts.get("hotfixes"), ["KB5099901"], facts)
        self.assertEqual(self.source(summary, "hotfixes").get("status"), "read",
                         summary.get("sources"))

    def test_single_row_objects(self):
        os_row = os_version_row()
        fw_row = firmware_row()
        as_list = self.collect(FakePowerShell({
            "os_version": ok([os_row]),
            "firmware": ok([fw_row]),
        }))
        as_object = self.collect(FakePowerShell({
            "os_version": ok(os_row),
            "firmware": ok(fw_row),
        }))
        list_facts = self.machine_of(as_list)
        object_facts = self.machine_of(as_object)

        # The reference run must have real values, so equality is not null == null.
        self.assertIsInstance(list_facts.get("firmware"), dict, list_facts)
        self.assertEqual(list_facts.get("build"), "26200", list_facts)
        self.assertEqual(list_facts.get("ubr"), 6899, list_facts)

        self.assertEqual(object_facts.get("firmware"), list_facts.get("firmware"),
                         object_facts)
        for field in VERSION_FIELDS:
            self.assertIn(field, object_facts, object_facts)
            self.assertEqual(object_facts[field], list_facts.get(field), field)
        for name in ("os_version", "firmware"):
            self.assertEqual(self.source(as_object, name).get("status"), "read",
                             as_object.get("sources"))

    def test_all_read(self):
        summary = self.collect(FakePowerShell({
            "os_version": ok([os_version_row()]),
            "hotfixes": ok([hotfix_row("KB5099901"), hotfix_row("KB5099917")]),
            "firmware": ok([firmware_row()]),
        }))
        for name in JOBS:
            with self.subTest(name):
                entry = self.source(summary, name)
                self.assertEqual(entry.get("status"), "read", entry)
                self.assertIn("reason", entry, entry)
                self.assertIsNone(entry["reason"], entry)
        self.assertEqual(self.job_notes(summary), [], self.not_checked(summary))

    def test_empty_hotfixes_status(self):
        summary = self.collect(FakePowerShell({"hotfixes": ok([])}))
        self.assertEqual(self.source(summary, "hotfixes").get("status"), "empty",
                         summary.get("sources"))
        facts = self.machine_of(summary)
        self.assertIn("hotfixes", facts, facts)
        self.assertEqual(facts["hotfixes"], [], facts)
        self.assertEqual(self.notes_about(summary, "hotfixes"), [],
                         self.not_checked(summary))

    def test_unreadable_status(self):
        for name in JOBS:
            with self.subTest(name):
                fake = FakePowerShell({name: failure(f"Invented: {name} job failed.")})
                summary = self.collect(fake)
                entry = self.source(summary, name)
                self.assertEqual(entry.get("status"), "unreadable", entry)
                reason = entry.get("reason")
                self.assertIsInstance(reason, str, entry)
                self.assertTrue(reason.strip(), entry)
                notes = [item for item in self.not_checked(summary)
                         if item.get("what") == f"job {name}"]
                self.assertTrue(notes, self.not_checked(summary))

    def test_empty_single_row_jobs(self):
        for name in ("os_version", "firmware"):
            with self.subTest(name):
                summary = self.collect(FakePowerShell({name: ok([])}))
                entry = self.source(summary, name)
                self.assertEqual(entry.get("status"), "empty", entry)
                self.assertIn("reason", entry, entry)
                self.assertIsNone(entry["reason"], entry)
                notes = [item for item in self.not_checked(summary)
                         if item.get("what") == f"job {name}"]
                self.assertEqual(len(notes), 1, self.not_checked(summary))

    def test_firmware_missing_field_is_null(self):
        summary = self.collect(FakePowerShell({
            "firmware": ok([firmware_row(bios_version="")]),
        }))
        firmware = self.machine_of(summary).get("firmware")
        self.assertIsInstance(firmware, dict, summary.get("machine"))
        self.assertIn("bios_version", firmware, firmware)
        # assertIsNone rejects "", False and 0 alike.
        self.assertIsNone(firmware["bios_version"], firmware)
        self.assertEqual(firmware.get("manufacturer"), "Contoso Ltd.", firmware)
        self.assertEqual(firmware.get("model"), "Contoso Book 14", firmware)
        self.assertEqual(firmware.get("bios_date"), "2026-04-15", firmware)
        notes = [item for item in self.not_checked(summary)
                 if item.get("what") == "firmware fields"]
        self.assertTrue(notes, self.not_checked(summary))
        self.assertTrue(any("bios_version" in str(item.get("reason")) for item in notes),
                        notes)


if __name__ == "__main__":
    unittest.main()

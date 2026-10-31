"""Machine facts of skills/ush-advice/scripts/advice.py (plan 103, M1): the values the
three jobs return, the product name from the map, the job bodies' object keys, and
unreadable versus empty results.

The interface is described in ``fakes.py``. PowerShell never starts; every value is
invented.
"""

import json
import unittest

from .fakes import (
    JOBS,
    KNOWN_PRODUCT,
    STAMP,
    AdviceTestCase,
    FakePowerShell,
    failure,
    machine,
    ok,
    os_version_row,
    pscustomobject_keys,
)

FIRMWARE_KEYS = {"Manufacturer", "Model", "SMBIOSBIOSVersion", "ReleaseDate"}
HOTFIX_KEYS = {"HotFixID"}
FORBIDDEN_WORDS = ("SerialNumber", "UUID", "CSName", "InstalledOn")
FINDINGS_FIELDS = ("updates", "exploited", "firmware", "issues")


class TestMachine(AdviceTestCase):
    def test_facts_and_product(self):
        with self.subTest("facts from the jobs and the product from the map"):
            data_dir = self.data_dir()
            fake = FakePowerShell(machine(kbs=["KB5099901", "KB5099917"]))
            summary = self.collect(fake, data_dir=data_dir)
            self.assertEqual(summary.get("skill"), "ush-advice", summary)
            self.assertEqual(sorted(set(fake.jobs())), sorted(JOBS), fake.jobs())

            facts = self.machine_of(summary)
            self.assertEqual(facts.get("display_version"), "25H2", facts)
            self.assertEqual(facts.get("build"), "26200", facts)
            self.assertIs(type(facts.get("ubr")), int, facts)
            self.assertEqual(facts.get("ubr"), 6899, facts)
            self.assertEqual(facts.get("edition_id"), "Core", facts)
            self.assertEqual(facts.get("architecture"), "AMD64", facts)
            self.assertEqual(facts.get("product"), KNOWN_PRODUCT, facts)
            self.assertIsNone(facts.get("product_reason"), facts)
            self.assertIsInstance(facts.get("hotfixes"), list, facts)
            self.assertEqual(sorted(facts["hotfixes"]), ["KB5099901", "KB5099917"], facts)
            self.assertEqual(facts.get("firmware"), {
                "manufacturer": "Contoso Ltd.",
                "model": "Contoso Book 14",
                "bios_version": "CB14.317.0",
                "bios_date": "2026-04-15",
            })

            sources = summary.get("sources")
            self.assertIsInstance(sources, list, summary)
            self.assertEqual(sorted(s.get("name") for s in sources), sorted(JOBS), sources)

            work = data_dir / "work"
            summary_path = work / f"advice-{STAMP}.summary.json"
            detail_path = work / f"advice-{STAMP}.detail.json"
            self.assertTrue(summary_path.is_file(), sorted(p.name for p in work.glob("*")))
            self.assertTrue(detail_path.is_file(), sorted(p.name for p in work.glob("*")))
            on_disk = json.loads(summary_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(on_disk.get("machine"), facts)

        with self.subTest("DisplayVersion outside the map"):
            fake = FakePowerShell({"os_version": ok([os_version_row(display_version="29H9")])})
            facts = self.machine_of(self.collect(fake))
            self.assertEqual(facts.get("display_version"), "29H9", facts)
            self.assertIsNone(facts.get("product"), facts)
            reason = facts.get("product_reason")
            self.assertIsInstance(reason, str, facts)
            self.assertTrue(reason.strip(), facts)

        for name, keys in (("FIRMWARE_BODY", FIRMWARE_KEYS), ("HOTFIXES_BODY", HOTFIX_KEYS)):
            with self.subTest(f"{name} object keys"):
                body = getattr(self.advice, name, None)
                self.assertIsInstance(body, str, f"advice.{name} is not a text constant")
                literals = pscustomobject_keys(body)
                self.assertTrue(literals, f"no [pscustomobject]@{{...}} literal in {name}")
                for found in literals:
                    self.assertEqual(found, keys, f"{name}: {sorted(found)}")
                lowered = body.lower()
                for word in FORBIDDEN_WORDS:
                    self.assertNotIn(word.lower(), lowered, f"{name} mentions {word}")

    def test_unreadable_and_empty(self):
        cases = (
            ("os_version failed", "os_version", failure("Invented: registry read failed.")),
            ("hotfixes failed", "hotfixes", failure("Invented: Get-HotFix failed.")),
            ("hotfixes empty", "hotfixes", ok([])),
            ("firmware failed", "firmware", failure("Invented: Win32_BIOS query failed.")),
        )
        for label, job, response in cases:
            with self.subTest(label):
                fake = FakePowerShell({job: response})
                code, stdout, stderr = self.run_main(self.data_dir(), fake)
                self.assertEqual(code, 0, stderr[:300])
                summary = self.parse(stdout)
                self.assertIsInstance(summary, dict, stdout[:300])
                facts = self.machine_of(summary)

                if label == "os_version failed":
                    self.assertIsNone(facts.get("build"), facts)
                    self.assertIsNone(facts.get("ubr"), facts)
                    self.assertTrue(self.notes_about(summary, "os_version"),
                                    self.not_checked(summary))
                elif label == "hotfixes failed":
                    self.assertIn("hotfixes", facts, facts)
                    self.assertIsNone(facts["hotfixes"], facts)
                    self.assertTrue(self.notes_about(summary, "hotfixes"),
                                    self.not_checked(summary))
                elif label == "hotfixes empty":
                    self.assertEqual(facts.get("hotfixes"), [], facts)
                    self.assertEqual(self.notes_about(summary, "hotfixes"), [],
                                     self.not_checked(summary))
                elif label == "firmware failed":
                    self.assertIn("firmware", facts, facts)
                    self.assertIsNone(facts["firmware"], facts)
                    self.assertTrue(self.notes_about(summary, "firmware"),
                                    self.not_checked(summary))

                for field in FINDINGS_FIELDS:
                    self.assertIn(field, summary, f"summary has no {field}")
                    self.assertIsNone(summary[field], f"{field} without --findings")
                self.assertTrue(self.search_notes(summary), self.not_checked(summary))


if __name__ == "__main__":
    unittest.main()

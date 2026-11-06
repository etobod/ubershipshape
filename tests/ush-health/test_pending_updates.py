"""Pending updates and the last scan date in health.py (plan 028, M1).

Every update below is invented; PowerShell is never started.

Raw-output contract of the new job (defined here, before the code exists):

- ``health.main`` runs one read-only PowerShell job named ``pending_updates``
  through ``run_ps(job, script, out_path)``. Its script creates
  ``Microsoft.Update.Session``, its ``UpdateSearcher`` with ``Online = $false``,
  searches ``IsInstalled=0 and IsHidden=0`` and reads
  ``Microsoft.Update.AutoUpdate`` ``Results.LastSearchSuccessDate``.
- On success the job writes one JSON object to ``out_path`` and exits 0::

      {
        "updates": [
          {
            "title": "<string>",
            "kb": ["KB<digits>", ...],          # may be empty
            "categories": ["<name>", ...],
            "type": "software" | "driver",
            "driver_provider": "<string>" | null,   # null for software
            "driver_class": "<string>" | null,      # null for software
            "driver_date": "YYYY-MM-DDTHH:MM:SS" | null,  # UTC, no zone
            "downloaded": true | false
          }
        ],
        "last_search_success": "YYYY-MM-DDTHH:MM:SS" | null   # UTC, no zone
      }

- A COM error makes the job exit non-zero with the error text on stderr and
  no output file. Output that is not JSON, or JSON that is not an object with
  an ``updates`` list, does not parse.

Summary contract: top-level ``pending_updates`` (list of items with ids ``q<n>``,
null when unreadable) and ``last_scan`` (ISO UTC string ending in ``Z``, or
null); source ``pending_updates`` in ``sources``; ``pending_updates`` also in
the detail file named by ``detail_file``.
"""

import importlib
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

_fakes = importlib.import_module("tests.ush-health.fakes_m3")
HealthTestCase = _fakes.HealthTestCase
ok = _fakes.ok
failure = _fakes.failure

JOB = "pending_updates"

SOFTWARE_TITLE = "Invented Cumulative Update for Windows (KB5099999)"
DRIVER_TITLE = "Contoso - Display - 31.0.101.9999"


def raw_text(text):
    """PowerShell exited 0 and wrote ``text`` verbatim (it may not be JSON)."""
    return ("raw", text)


class FakePowerShell(_fakes.FakePowerShell):
    """The M3 fake, plus a ``raw`` response that writes text as it is."""

    def __call__(self, job, script, out_path):
        response = self.responses.get(job)
        if response is not None and response[0] == "raw":
            out_path = Path(out_path)
            self.calls.append((job, script, out_path))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(response[1], encoding="utf-8-sig")
            return 0, ""
        return super().__call__(job, script, out_path)


def software_update(title=SOFTWARE_TITLE, kb=("KB5099999",), downloaded=True):
    return {
        "title": title,
        "kb": list(kb),
        "categories": ["Security Updates", "Windows 11"],
        "type": "software",
        "driver_provider": None,
        "driver_class": None,
        "driver_date": None,
        "downloaded": downloaded,
    }


def driver_update(title=DRIVER_TITLE, provider="Contoso", cls="Display",
                  date="2026-08-15T00:00:00", downloaded=False):
    return {
        "title": title,
        "kb": [],
        "categories": ["Drivers"],
        "type": "driver",
        "driver_provider": provider,
        "driver_class": cls,
        "driver_date": date,
        "downloaded": downloaded,
    }


def search_result(updates, last_search_success="2026-09-27T06:45:00"):
    return {"updates": list(updates), "last_search_success": last_search_success}


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestPendingUpdates(HealthTestCase):
    def pending(self, summary):
        self.assertIn("pending_updates", summary, sorted(summary))
        items = summary["pending_updates"]
        self.assertIsInstance(items, list, items)
        return items

    def by_title(self, items):
        return {item.get("title"): item for item in items}

    def test_items_and_last_scan(self):
        fake = FakePowerShell({JOB: ok(search_result(
            [software_update(), driver_update()]))})
        summary = self.collect(fake)

        self.assertEqual(self.source(summary, JOB).get("status"), "read")
        items = self.pending(summary)
        self.assertEqual(len(items), 2, items)
        self.assertEqual(sorted(item.get("id") for item in items), ["q1", "q2"], items)

        titles = self.by_title(items)
        self.assertEqual(set(titles), {SOFTWARE_TITLE, DRIVER_TITLE}, items)

        software = titles[SOFTWARE_TITLE]
        self.assertEqual(software.get("kb"), ["KB5099999"], software)
        self.assertEqual(software.get("categories"), ["Security Updates", "Windows 11"],
                         software)
        self.assertEqual(software.get("type"), "software", software)
        self.assertIsNone(software.get("driver_provider"), software)
        self.assertIsNone(software.get("driver_class"), software)
        self.assertIsNone(software.get("driver_date"), software)
        self.assertIs(software.get("downloaded"), True, software)

        driver = titles[DRIVER_TITLE]
        self.assertEqual(driver.get("kb"), [], driver)
        self.assertEqual(driver.get("categories"), ["Drivers"], driver)
        self.assertEqual(driver.get("type"), "driver", driver)
        self.assertEqual(driver.get("driver_provider"), "Contoso", driver)
        self.assertEqual(driver.get("driver_class"), "Display", driver)
        self.assertIsInstance(driver.get("driver_date"), str, driver)
        self.assertTrue(driver["driver_date"].startswith("2026-08-15"), driver)
        self.assertIs(driver.get("downloaded"), False, driver)

        self.assertIn("last_scan", summary, sorted(summary))
        last_scan = summary["last_scan"]
        self.assertIsInstance(last_scan, str, last_scan)
        self.assertTrue(last_scan.endswith("Z"), last_scan)
        # The zone-less date is UTC: no shift by the local zone.
        self.assertEqual(instant(last_scan),
                         datetime(2026, 9, 27, 6, 45, tzinfo=timezone.utc))
        # Clean data, including a driver with no KB: no per-field not_checked entry.
        whats = [entry.get("what") for entry in summary.get("not_checked", [])]
        self.assertEqual([w for w in whats if str(w).startswith(JOB + ":")], [], whats)

    def test_unreadable_fields_named(self):
        broken = driver_update(title="Contoso - Broken - 1.0")
        broken["kb"] = {"value": "KB1"}
        broken["driver_date"] = "not a date"
        fake = FakePowerShell({JOB: ok(search_result([software_update(), broken]))})
        summary = self.collect(fake)

        entries = {(e.get("what"), e.get("reason")) for e in summary.get("not_checked", [])}
        self.assertIn((JOB + ": kb", "Contoso - Broken - 1.0: not a list of texts"), entries)
        self.assertIn((JOB + ": driver_date",
                       "Contoso - Broken - 1.0: the driver date is not a time"), entries)
        self.assertNotIn(JOB + ": categories", {what for what, _ in entries})
        item = self.by_title(self.pending(summary))["Contoso - Broken - 1.0"]
        self.assertIsNone(item.get("kb"), item)
        self.assertIsNone(item.get("driver_date"), item)

    def test_none_pending(self):
        fake = FakePowerShell({JOB: ok(search_result([]))})
        summary = self.collect(fake)

        self.assertEqual(self.pending(summary), [])
        self.assertEqual(self.source(summary, JOB).get("status"), "empty")
        self.assertNotIn(JOB, self.not_checked_whats(summary))

    def test_unreadable_search(self):
        cases = (
            ("COM error", failure(
                "New-Object : Invented COM failure, HRESULT 0x8024402C.", code=1),
             "0x8024402C"),
            ("not JSON", raw_text('{"updates": [{"title": "Invented'), None),
            ("no updates list", ok({"last_search_success": None}), None),
        )
        for name, response, reason_part in cases:
            with self.subTest(case=name):
                summary = self.collect(FakePowerShell({JOB: response}))
                src = self.assert_unreadable_with_entry(summary, JOB)
                if reason_part is not None:
                    self.assertIn(reason_part, src["reason"], src)
                self.assertIn("pending_updates", summary, sorted(summary))
                self.assertIsNone(summary["pending_updates"])

    def test_unknown_scan_date(self):
        fake = FakePowerShell({JOB: ok(search_result(
            [software_update()], last_search_success=None))})
        summary = self.collect(fake)

        self.assertEqual(self.source(summary, JOB).get("status"), "read")
        self.assertEqual(len(self.pending(summary)), 1)
        self.assertIn("last_scan", summary, sorted(summary))
        self.assertIsNone(summary["last_scan"])

    def test_search_is_offline(self):
        fake = FakePowerShell({JOB: ok(search_result([]))})
        self.collect(fake)

        script = fake.script_of(JOB)
        self.assertIn("Microsoft.Update.Session", script)
        self.assertRegex(script, re.compile(r"\.Online\s*=\s*\$false", re.IGNORECASE))
        self.assertNotRegex(script, re.compile(r"\.Online\s*=\s*\$true", re.IGNORECASE))

    def test_detail_file_holds_list(self):
        fake = FakePowerShell({JOB: ok(search_result(
            [software_update(), driver_update()]))})
        summary = self.collect(fake)
        items = self.pending(summary)
        self.assertEqual(len(items), 2, items)

        detail_path = summary.get("detail_file")
        self.assertIsInstance(detail_path, str, summary.get("detail_file"))
        detail = json.loads(Path(detail_path).read_text(encoding="utf-8-sig"))
        self.assertIn("pending_updates", detail, sorted(detail))
        detail_items = detail["pending_updates"]
        self.assertIsInstance(detail_items, list, detail_items)

        summary_by_id = {item.get("id"): item for item in items}
        detail_by_id = {item.get("id"): item for item in detail_items}
        self.assertEqual(set(detail_by_id), set(summary_by_id), detail_items)
        for item_id, item in summary_by_id.items():
            with self.subTest(id=item_id):
                for key, value in item.items():
                    self.assertEqual(detail_by_id[item_id].get(key), value,
                                     f"{item_id}.{key}")


if __name__ == "__main__":
    unittest.main()

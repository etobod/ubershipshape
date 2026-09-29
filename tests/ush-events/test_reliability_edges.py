"""Reliability Monitor edge cases found in review (invented data only)."""

import unittest
from datetime import datetime, timezone

from tests.skill_loader import load_script

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


class TestStabilityWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def test_bad_index_before_window_is_not_unreadable(self):
        found = {"status": "read", "reason": None, "events": [
            {"TimeGenerated": "2026-03-01T10:00:00.0000000Z", "SystemStabilityIndex": None},
            {"TimeGenerated": "2026-09-10T10:00:00.0000000Z", "SystemStabilityIndex": 7.25},
        ]}
        stable, bad = self.events.stability(found, START)
        self.assertEqual(bad, 0)
        self.assertEqual(stable["daily"], [{"date": "2026-09-10", "index": 7.25}])

    def test_bad_index_in_window_is_counted(self):
        found = {"status": "read", "reason": None, "events": [
            {"TimeGenerated": "2026-09-10T10:00:00.0000000Z", "SystemStabilityIndex": "x"},
        ]}
        stable, bad = self.events.stability(found, START)
        self.assertEqual(bad, 1)
        self.assertEqual(stable["daily"], [])


class TestRecordProducts(unittest.TestCase):
    def test_distinct_products_are_counted(self):
        events = load_script("ush-events", "events")

        def row(day, product):
            return {"TimeGenerated": f"2026-09-{day:02d}T10:00:00.0000000Z",
                    "SourceName": "Application Error", "EventIdentifier": 1000,
                    "ProductName": product}

        found = {"status": "read", "reason": None, "events": [
            row(10, "InventedEditor.exe"), row(11, "InventedEditor.exe"),
            row(12, "InventedPlayer.exe"),
        ]}
        grouped, bad = events.reliability_records(found, START)
        self.assertEqual(bad, 0)
        self.assertEqual([(g["count"], g["product"], g["products"]) for g in grouped],
                         [(3, "InventedPlayer.exe", 2)])


if __name__ == "__main__":
    unittest.main()

"""The 35000-character summary budget of health.py (plan 047, M3).

2000 invented failure groups; PowerShell is never started.
"""

import importlib
import json
import random
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

_fakes = importlib.import_module("tests.ush-health.fakes_m3")
FakePowerShell = _fakes.FakePowerShell
HealthTestCase = _fakes.HealthTestCase
ok = _fakes.ok

GROUPS = 2000
BUDGET = 35000
START = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def title(index):
    return f"Invented Update Package {index:04d} for an Invented Example Component"


def failure_rows():
    """One failed entry per group; group i fails i hours after START (UTC, no zone)."""
    rows = [
        {
            "Title": title(i),
            "ResultCode": 4,
            "HResult": -2145116149 - i,
            "Date": (START + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S"),
        }
        for i in range(GROUPS)
    ]
    random.Random(47).shuffle(rows)
    return rows


class TestBudget(HealthTestCase):
    def test_failures_cut_to_budget(self):
        fake = FakePowerShell({"update_history": ok(failure_rows())})
        code, stdout = self.run_main(fake, admin=True)
        self.assertEqual(code, 0, stdout[:300])
        self.assertLessEqual(len(stdout.strip()), BUDGET)
        summary = json.loads(stdout)

        truncated = summary.get("truncated")
        self.assertIsInstance(truncated, int, truncated)
        self.assertGreater(truncated, 0)

        updates = summary.get("updates")
        self.assertIsInstance(updates, dict, updates)
        self.assertEqual(updates.get("history_count"), GROUPS)
        kept = updates.get("failures")
        self.assertIsInstance(kept, list, kept)
        self.assertGreater(len(kept), 0)
        self.assertEqual(len(kept) + truncated, GROUPS)

        # The newest groups stay, newest first.
        newest_titles = [title(i) for i in range(GROUPS - 1, GROUPS - 1 - len(kept), -1)]
        self.assertEqual([group.get("title") for group in kept], newest_titles)

        detail_path = Path(summary.get("detail_file"))
        self.assertTrue(detail_path.is_absolute(), detail_path)
        detail = json.loads(detail_path.read_text(encoding="utf-8-sig"))
        all_groups = detail.get("update_failures")
        self.assertIsInstance(all_groups, list, type(all_groups))
        self.assertEqual(len(all_groups), GROUPS)
        self.assertEqual(
            {group.get("title") for group in all_groups},
            {title(i) for i in range(GROUPS)},
        )

    def test_failures_kept_when_cutting_cannot_help(self):
        # Something other than the failures is over budget on its own.
        failures = [{"id": "u1", "title": title(1)}, {"id": "u2", "title": title(2)}]
        summary = {
            "devices": ["Invented Device " + "x" * BUDGET],
            "updates": {"failures": list(failures)},
            "truncated": 0,
            "not_checked": [],
        }
        self.health.fit_budget(summary)

        self.assertEqual(summary["updates"]["failures"], failures)
        self.assertEqual(summary["truncated"], 0)
        self.assertEqual([item["what"] for item in summary["not_checked"]],
                         ["summary budget"])


if __name__ == "__main__":
    unittest.main()

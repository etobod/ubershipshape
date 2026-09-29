"""Summary size budget: fit_budget reports a summary it cannot fit (invented data only).

fit_budget(summary, limit) cuts groups from the end and sets "truncated" until
the JSON text fits "limit" characters. When the summary is still over the
limit with every group cut, it names that in not_checked.
"""

import copy
import json
import unittest

from tests.skill_loader import load_script

EXPECTED_REASON = (
    "all groups were cut and the summary still does not fit; only groups are "
    "ever cut, all lists are complete in the detail file"
)


def _group(provider, event_id, count):
    return {"provider": provider, "event_id": event_id, "level": 2,
            "log": "System", "count": count}


def _anomaly(index):
    return {
        "kind": "unexpected_shutdown",
        "time": f"2026-09-{10 + index:02d}T07:15:00+02:00",
        "boot": index + 1,
        "log": "System",
        "record_id": 1000 + index,
    }


def _summary(groups, anomalies):
    return {
        "schema_version": 1,
        "window_days": 7,
        "groups": groups,
        "truncated": 0,
        "anomalies": anomalies,
        "not_checked": [],
    }


def _size_limit_entries(parsed):
    return [e for e in parsed["not_checked"] if "size limit" in e.get("what", "")]


class TestSummaryBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_script("ush-events", "events")

    def _groups(self):
        return [
            _group("Microsoft-Windows-Kernel-Power", 41, 3),
            _group("Service Control Manager", 7000, 5),
            _group("Microsoft-Windows-WHEA-Logger", 17, 2),
        ]

    def test_over_limit_without_groups_is_reported(self):
        limit = 400
        anomalies = [_anomaly(i) for i in range(8)]
        summary = _summary(self._groups(), anomalies)
        # Precondition on the invented data: over the limit even with no groups.
        self.assertGreater(len(self.events.dump({**summary, "groups": [], "truncated": 3})), limit)

        parsed = json.loads(self.events.fit_budget(copy.deepcopy(summary), limit))

        self.assertEqual(parsed["groups"], [])
        self.assertEqual(parsed["truncated"], 3)
        entries = _size_limit_entries(parsed)
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(parsed["not_checked"]), 1)
        self.assertIn(str(limit), entries[0]["what"])
        self.assertEqual(
            entries[0]["what"], f"summary over its size limit of {limit} characters"
        )
        self.assertEqual(entries[0]["reason"], EXPECTED_REASON)

    def test_summary_within_limit_is_untouched(self):
        limit = 35000
        summary = _summary(self._groups(), [_anomaly(1)])
        expected = self.events.dump(copy.deepcopy(summary))
        self.assertLessEqual(len(expected), limit)

        text = self.events.fit_budget(copy.deepcopy(summary), limit)

        self.assertEqual(text, expected)
        parsed = json.loads(text)
        self.assertEqual(parsed["truncated"], 0)
        self.assertEqual(_size_limit_entries(parsed), [])

    def test_cutting_groups_still_works(self):
        groups = [
            _group("Microsoft-Windows-Kernel-Power", 41, 3),
            _group("Service Control Manager", 7000, 5),
            _group("Microsoft-Windows-WHEA-Logger", 17, 2),
            _group("Microsoft-Windows-DistributedCOM", 10016, 40),
            _group("Microsoft-Windows-Time-Service", 129, 6),
        ]
        summary = _summary(groups, [_anomaly(1)])
        # Limit set to the size of the summary with the last three groups cut,
        # so it fits only after cutting some (not all) groups.
        partial = copy.deepcopy(summary)
        partial["groups"] = partial["groups"][:2]
        partial["truncated"] = 3
        limit = len(self.events.dump(partial))
        self.assertGreater(len(self.events.dump(copy.deepcopy(summary))), limit)

        text = self.events.fit_budget(copy.deepcopy(summary), limit)

        parsed = json.loads(text)
        # Exactly the groups that fit are kept: none cut too many.
        self.assertEqual(parsed["truncated"], 3)
        self.assertEqual(len(parsed["groups"]), 2)
        self.assertLessEqual(len(text), limit)
        self.assertEqual(_size_limit_entries(parsed), [])


if __name__ == "__main__":
    unittest.main()

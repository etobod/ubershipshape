"""The ``fault`` finding kind in skills/ush-advice/scripts/advice.py (plan 009, M2).

A ``fault`` finding has the common fields (``kind``, ``url``, ``title``, ``query``,
``published``) plus ``fault`` (public fault text), ``source_item`` (the skill and item id
that found it), ``advice`` (what the page says to do) and ``fix`` (``available``,
``none_today`` or ``unknown``). ``query_warnings`` gains the reason ``device_id`` for a
device instance id shape in a query or url.

Assumed interface beyond ``fakes.py``: module-level ``check_finding(finding)`` that
returns normally for a good shape and raises the module-level exception class
``ShapeError`` for a bad one. A bad shape given to ``--findings`` exits 2 naming the
entry, as for the other kinds.

The interface is described in ``fakes.py``. PowerShell never starts; every fault code,
device id, url, title and query is invented.
"""

import json
import unittest

from .fakes import (
    AdviceTestCase,
    FakePowerShell,
    findings_doc,
    search,
)

FAULT_URL = ("https://learn.microsoft.com/windows-hardware/drivers/install/"
             "invented-cm-prob-failed-post-start")
GENERAL_QUERY = "CM_PROB_FAILED_POST_START Windows 11 USB hub"
DEVICE_ID = "USB\\VID_1234&PID_5678\\5&2A3B4C5D&0&1"
DEVICE_INSTANCE_PART = "5&2A3B4C5D&0&1"


def fault_finding(fault="CM_PROB_FAILED_POST_START", source_item="ush-health h3",
                  advice="Invented advice: reinstall the hub driver, then restart.",
                  fix="available", url=FAULT_URL, query=GENERAL_QUERY,
                  title="Invented page: device cannot start (code 10)",
                  published="2026-08-14"):
    """An invented ``fault`` finding with every field."""
    return {
        "kind": "fault",
        "url": url,
        "title": title,
        "query": query,
        "published": published,
        "fault": fault,
        "source_item": source_item,
        "advice": advice,
        "fix": fix,
    }


def fault_searches():
    return [search("release-health")]


class TestFault(AdviceTestCase):
    def warnings_of(self, summary):
        warnings = summary.get("query_warnings")
        self.assertIsInstance(warnings, list, summary.get("query_warnings"))
        for warning in warnings:
            self.assertIsInstance(warning, dict, warnings)
            self.assertTrue(str(warning.get("finding_id", "")).startswith("w"), warnings)
        return warnings

    def pairs(self, warnings):
        return [(w.get("finding_id"), w.get("reason")) for w in warnings]

    def assert_shape_error_exit(self, finding):
        """``--findings`` with ``finding`` exits 2, names the entry and writes no state."""
        data_dir = self.data_dir()
        code, stdout, stderr = self.run_findings(
            data_dir, FakePowerShell(), findings_doc(fault_searches(), [finding]))
        self.assertEqual(code, 2, f"stdout={stdout[:300]!r} stderr={stderr[:300]!r}")
        self.assertRegex(stderr, r"\b(0|1)\b", "stderr does not name the entry number")
        state = data_dir / "state"
        written = sorted(p.name for p in state.rglob("*")) if state.exists() else []
        self.assertEqual(written, [], "files written under state/ after a bad file")

    # K1
    def test_fault_shape(self):
        check_finding = getattr(self.advice, "check_finding", None)
        shape_error = getattr(self.advice, "ShapeError", None)
        self.assertTrue(callable(check_finding), "advice.check_finding is missing")
        self.assertTrue(isinstance(shape_error, type)
                        and issubclass(shape_error, Exception),
                        "advice.ShapeError is missing or not an exception class")

        for fix in ("available", "none_today", "unknown"):
            with self.subTest(f"every field, fix {fix!r}: check_finding passes"):
                try:
                    check_finding(fault_finding(fix=fix))
                except shape_error as exc:
                    self.fail(f"a complete fault finding raised ShapeError: {exc}")

        with self.subTest("every field: --findings exits 0"):
            self.collect_findings(FakePowerShell(),
                                  findings_doc(fault_searches(), [fault_finding()]))

        no_advice = fault_finding()
        del no_advice["advice"]
        maybe = fault_finding(fix="maybe")
        for label, bad in (("without advice", no_advice), ("fix maybe", maybe)):
            with (self.subTest(f"{label}: check_finding raises ShapeError"),
                  self.assertRaises(shape_error)):
                check_finding(bad)
            with self.subTest(f"{label}: --findings exits 2"):
                self.assert_shape_error_exit(bad)

    # K2
    def test_general_query_no_warning(self):
        summary = self.collect_findings(FakePowerShell(), findings_doc(
            fault_searches(), [fault_finding(query=GENERAL_QUERY)]))
        self.assertEqual(self.warnings_of(summary), [])

    # K3
    def test_device_id_warns(self):
        query = f"CM_PROB_FAILED_POST_START {DEVICE_ID}"
        code, stdout, stderr = self.run_findings(
            self.data_dir(), FakePowerShell(),
            findings_doc(fault_searches(), [fault_finding(query=query)]))
        self.assertEqual(code, 0, f"--findings run failed: {stderr[:400]}")
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])

        warnings = self.warnings_of(summary)
        self.assertEqual(self.pairs(warnings), [("w1", "device_id")], warnings)

        # The id may appear raw or JSON-escaped (backslashes doubled).
        forms = (DEVICE_ID, json.dumps(DEVICE_ID)[1:-1], DEVICE_INSTANCE_PART, query)
        for warning in warnings:
            text = json.dumps(warning)
            for form in forms:
                with self.subTest(f"{form!r} not in the warning entry"):
                    self.assertNotIn(form, text, warning)
                    for value in warning.values():
                        self.assertNotIn(form, str(value), warning)
        for form in forms:
            with self.subTest(f"{form!r} not in the summary JSON"):
                self.assertNotIn(form, stdout)
                self.assertNotIn(form, json.dumps(summary))


if __name__ == "__main__":
    unittest.main()

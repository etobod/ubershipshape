"""Failed cumulative updates superseded by a later success in health.py (plan 059, M1).

Every title, KB number, build and date here is invented; PowerShell is never
started. Title shapes follow the plan:
- ``<YYYY-MM> Security Update (KB<n>) (<build>.<revision>)``, line = build
- ``<YYYY-MM> Cumulative Update ... (<build>.<revision>)``, line = build
- ``Cumulative Update for Windows 11 Version <version> ...``, line = version
"""

import importlib
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_fakes = importlib.import_module("tests.ush-health.fakes_m3")
FakePowerShell = _fakes.FakePowerShell
HealthTestCase = _fakes.HealthTestCase
ok = _fakes.ok

SUCCEEDED = 2
SUCCEEDED_WITH_ERRORS = 3
FAILED = 4
ABORTED = 5

HRESULT = -2145116149  # 0x8024200B

SEC_FAILED = "2026-08 Security Update (KB9900001) (26100.4001)"
SEC_LATER = "2026-09 Security Update (KB9900002) (26100.4100)"
SEC_OTHER_BUILD = "2026-09 Security Update (KB9900003) (99999.4100)"
CU_BUILD_LATER = "2026-09 Cumulative Update for x64-based Systems (KB9900004) (26100.4200)"
VER_25H2_FAILED = "Cumulative Update for Windows 11 Version 25H2 for x64-based Systems (KB9900011)"
VER_25H2_LATER = "Cumulative Update for Windows 11 Version 25H2 for x64-based Systems (KB9900012)"
VER_24H2_FAILED = "Cumulative Update for Windows 11 Version 24H2 for x64-based Systems (KB9900013)"

TITLE_DRIVER = "Invented Vendor - System - 1.2.3.4"
TITLE_STORE = "9NINVENTEDAPP-Invented.Store.App"
CLEAN_TITLES = (
    TITLE_DRIVER,
    "Invented Vendor Inc. - Display - 31.0.101.9999",
    "Security Intelligence Update for Microsoft Defender Antivirus - KB2267602 (Version 1.999.123.0) - Current Channel (Broad)",
    "Update for Microsoft Defender Antivirus antimalware platform - KB4052623 (Version 4.18.99999.1) - Current Channel (Broad)",
    "Windows Malicious Software Removal Tool x64 - v5.999 (KB890830)",
    "2099-01 Cumulative Update for .NET Framework 3.5 and 4.8.1 for Windows 11, version 99H9 for x64 (KB9900021)",
    "2099-01 Cumulative Update for .NET Framework 3.5 and 4.8.1 for Windows 11 Version 99H9 for x64-based Systems (KB9900022) (99999.1001)",
    TITLE_STORE,
    "Invented Windows Feature Experience Pack 1000.99999.1001.0",
)


def entry(title, result_code, date, hresult=0):
    """One row of the update_history projection; Date is UTC without a zone."""
    return {"Title": title, "ResultCode": result_code, "HResult": hresult, "Date": date}


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class SupersededCase(HealthTestCase):
    def run_history(self, rows):
        summary = self.collect(FakePowerShell({"update_history": ok(rows)}))
        self.assertEqual(self.source(summary, "update_history").get("status"), "read")
        updates = summary.get("updates")
        self.assertIsInstance(updates, dict, updates)
        self.assertIsInstance(updates.get("failures"), list, updates)
        return summary, updates

    def detail_groups(self, summary):
        detail_path = Path(summary.get("detail_file"))
        detail = json.loads(detail_path.read_text(encoding="utf-8-sig"))
        groups = detail.get("update_failures")
        self.assertIsInstance(groups, list, sorted(detail))
        return groups

    def group(self, groups, title):
        matches = [g for g in groups if g.get("title") == title]
        self.assertEqual(len(matches), 1, f"groups titled {title!r}: {groups}")
        return matches[0]

    def assert_not_superseded(self, updates, title):
        group = self.group(updates["failures"], title)
        self.assertIn("superseded_by", group, group)
        self.assertIsNone(group["superseded_by"], group)
        return group

    def assert_superseded_by(self, summary, updates, title, by_title, by_date):
        self.assertNotIn(title, [g.get("title") for g in updates["failures"]],
                         updates["failures"])
        group = self.group(self.detail_groups(summary), title)
        superseded_by = group.get("superseded_by")
        self.assertIsInstance(superseded_by, dict, group)
        self.assertEqual(superseded_by.get("title"), by_title, group)
        self.assertIsInstance(superseded_by.get("date"), str, group)
        self.assertEqual(instant(superseded_by["date"]), utc(by_date), group)


class TestSuperseded(SupersededCase):
    def test_later_success_supersedes(self):
        rows = [
            entry(SEC_FAILED, FAILED, "2026-08-14T10:00:00", hresult=HRESULT),
            entry(SEC_FAILED, FAILED, "2026-08-20T10:00:00", hresult=HRESULT),
            entry(SEC_LATER, SUCCEEDED, "2026-09-12T09:00:00"),
        ]
        summary, updates = self.run_history(rows)

        self.assertEqual(updates.get("superseded"), 1, updates)
        self.assertEqual(updates["failures"], [])
        self.assert_superseded_by(summary, updates, SEC_FAILED,
                                  SEC_LATER, "2026-09-12T09:00:00")

    def test_not_superseded(self):
        with self.subTest(case="success before the group's last"):
            rows = [
                entry(SEC_FAILED, FAILED, "2026-09-01T10:00:00", hresult=HRESULT),
                entry(SEC_LATER, SUCCEEDED, "2026-09-10T09:00:00"),
                entry(SEC_FAILED, FAILED, "2026-09-15T10:00:00", hresult=HRESULT),
            ]
            _, updates = self.run_history(rows)
            self.assertEqual(updates.get("superseded"), 0, updates)
            self.assert_not_superseded(updates, SEC_FAILED)

        with self.subTest(case="later success of another build"):
            rows = [
                entry(SEC_FAILED, FAILED, "2026-09-01T10:00:00", hresult=HRESULT),
                entry(SEC_OTHER_BUILD, SUCCEEDED, "2026-09-10T09:00:00"),
            ]
            _, updates = self.run_history(rows)
            self.assertEqual(updates.get("superseded"), 0, updates)
            self.assert_not_superseded(updates, SEC_FAILED)

        with self.subTest(case="failure group without a known time"):
            rows = [
                entry(SEC_FAILED, FAILED, None, hresult=HRESULT),
                entry(SEC_LATER, SUCCEEDED, "2026-09-10T09:00:00"),
            ]
            _, updates = self.run_history(rows)
            self.assertEqual(updates.get("superseded"), 0, updates)
            group = self.assert_not_superseded(updates, SEC_FAILED)
            self.assertIsNone(group.get("last"), group)

    def test_only_succeeded_supersedes(self):
        for name, code in (("SucceededWithErrors", SUCCEEDED_WITH_ERRORS),
                           ("Failed", FAILED),
                           ("Aborted", ABORTED)):
            with self.subTest(later_result=name):
                rows = [
                    entry(SEC_FAILED, FAILED, "2026-09-01T10:00:00", hresult=HRESULT),
                    entry(SEC_LATER, code, "2026-09-10T09:00:00", hresult=HRESULT),
                ]
                _, updates = self.run_history(rows)
                self.assertEqual(updates.get("superseded"), 0, updates)
                self.assert_not_superseded(updates, SEC_FAILED)

    def test_version_shape(self):
        with self.subTest(case="same version supersedes"):
            rows = [
                entry(VER_25H2_FAILED, FAILED, "2026-09-01T10:00:00", hresult=HRESULT),
                entry(VER_25H2_LATER, SUCCEEDED, "2026-09-10T09:00:00"),
            ]
            summary, updates = self.run_history(rows)
            self.assertEqual(updates.get("superseded"), 1, updates)
            self.assert_superseded_by(summary, updates, VER_25H2_FAILED,
                                      VER_25H2_LATER, "2026-09-10T09:00:00")

        with self.subTest(case="another version does not supersede"):
            rows = [
                entry(VER_24H2_FAILED, FAILED, "2026-09-01T10:00:00", hresult=HRESULT),
                entry(VER_25H2_LATER, SUCCEEDED, "2026-09-10T09:00:00"),
            ]
            _, updates = self.run_history(rows)
            self.assertEqual(updates.get("superseded"), 0, updates)
            self.assert_not_superseded(updates, VER_24H2_FAILED)

        with self.subTest(case="cumulative build shape supersedes security build shape"):
            rows = [
                entry(SEC_FAILED, FAILED, "2026-08-20T10:00:00", hresult=HRESULT),
                entry(CU_BUILD_LATER, SUCCEEDED, "2026-09-15T09:00:00"),
            ]
            summary, updates = self.run_history(rows)
            self.assertEqual(updates.get("superseded"), 1, updates)
            self.assert_superseded_by(summary, updates, SEC_FAILED,
                                      CU_BUILD_LATER, "2026-09-15T09:00:00")

    def test_ids_match_detail(self):
        # K6: one group in the middle is superseded; the summary keeps the ids of the
        # detail file, gaps included.
        rows = [
            entry(TITLE_DRIVER, FAILED, "2026-09-20T10:00:00", hresult=HRESULT),
            entry(SEC_FAILED, FAILED, "2026-09-05T10:00:00", hresult=HRESULT),
            entry(SEC_LATER, SUCCEEDED, "2026-09-12T09:00:00"),
            entry(TITLE_STORE, ABORTED, "2026-09-01T10:00:00", hresult=HRESULT),
        ]
        summary, updates = self.run_history(rows)
        detail = {g.get("title"): g.get("id") for g in self.detail_groups(summary)}
        self.assertEqual(len(detail), 3, detail)
        self.assertEqual(updates.get("superseded"), 1, updates)
        self.assertEqual([g.get("title") for g in updates["failures"]],
                         [TITLE_DRIVER, TITLE_STORE])
        for group in updates["failures"]:
            self.assertEqual(group.get("id"), detail[group["title"]], group)
        self.assertNotIn(detail[SEC_FAILED], [g.get("id") for g in updates["failures"]])


class TestPatterns(HealthTestCase):
    def write_data_file(self, content):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name).resolve() / "cumulative-updates.json"
        path.write_text(content, encoding="utf-8")
        return path

    def test_clean_titles(self):
        entries = self.health.load_cumulative(self.health.DEFAULT_CUMULATIVE_FILE)
        self.assertTrue(entries)
        raw = json.loads(self.health.DEFAULT_CUMULATIVE_FILE.read_text(encoding="utf-8-sig"))
        for item in raw:
            with self.subTest(pattern=item["id"]):
                compiled = re.compile(item["pattern"])
                self.assertIn("line", compiled.groupindex)
                self.assertIn(item["line_kind"], ("build", "version"))
                match = compiled.search(item["example"])
                self.assertIsNotNone(match, item["example"])
                self.assertTrue(match.group("line"))
                for title in CLEAN_TITLES:
                    self.assertIsNone(compiled.search(title), title)

    def test_malformed_file(self):
        valid_entry = {
            "id": "invented-security",
            "pattern": r"^\d{4}-\d{2} Security Update \(KB\d+\) \((?P<line>\d+)\.\d+\)$",
            "line_kind": "build",
            "example": "2026-08 Security Update (KB9900001) (26100.4001)",
            "reason": "Invented entry for a loader test.",
        }
        no_line_group = dict(valid_entry, id="invented-no-line",
                             pattern=r"^\d{4}-\d{2} Security Update \(KB\d+\) \((?P<build>\d+)\.\d+\)$")
        bad_regex = dict(valid_entry, id="invented-bad-regex",
                         pattern=r"^\d{4}-\d{2} Security Update \((?P<line>\d+")
        cases = (
            ("not a JSON list", json.dumps(valid_entry)),
            ("entry without a line group", json.dumps([no_line_group])),
            ("pattern does not compile", json.dumps([bad_regex])),
        )
        for name, content in cases:
            with self.subTest(case=name):
                path = self.write_data_file(content)
                with self.assertRaises(ValueError) as caught:
                    self.health.load_cumulative(path)
                self.assertIn(str(path), str(caught.exception))


REPO = Path(__file__).absolute().parents[2]


def section(text, start, end):
    """The text from the line holding ``start`` up to the next line holding ``end``."""
    head = text.index(start)
    stop = text.find(end, head + len(start))
    return text[head:stop if stop != -1 else len(text)]


class TestDocs(unittest.TestCase):
    """The report formats give the superseded failures only as a count."""

    def read(self, skill):
        path = REPO / "skills" / skill / "references" / "report-format.md"
        return path.read_text(encoding="utf-8")

    def test_health_format(self):
        text = self.read("ush-health")
        layout = section(text, "## Layout", "## Values that are not readings")
        self.assertIn("`updates.superseded`", layout)
        self.assertIn("only as a count", layout)
        self.assertIn("never a recommendation", layout)
        empty = section(text, "- A source with `status` `empty`", "\n- ")
        self.assertIn("`superseded`", empty)
        self.assertIn("never \"no failed update\"", empty)

    def test_runall_format(self):
        text = self.read("ush-runall")
        run_state = section(text, "### 3. Run state", "### 4.")
        self.assertIn("`updates.superseded`", run_state)
        self.assertIn("`ush-health`", run_state)
        children = json.loads((REPO / "skills" / "ush-runall" / "data" / "children.json")
                              .read_text(encoding="utf-8-sig"))
        health_id = "h{}".format(1 + [c["skill"] for c in children].index("ush-health"))
        self.assertIn(f"`{health_id}`", run_state)
        self.assertIn("`ush:detail`", run_state)
        self.assertIn("never `0`", run_state)
        recommendations = section(text, "### 5. Recommendations", "### 6.")
        self.assertNotIn("`updates.superseded`", recommendations)
        self.assertIn("never a recommendation", run_state)


if __name__ == "__main__":
    unittest.main()

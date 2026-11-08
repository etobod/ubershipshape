"""The ush-inventory report profile, checked through the shared report checker.

The checker loads the real ``skills/ush-inventory/data/report-profile.json``
through its unpatched ``SKILLS_DIR``; no copy of the profile is used.
All summary data below is invented.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import load_script

SKILL = "ush-inventory"
# Keys whose values supply no numbers (the profile's path_keys and id_keys).
SKIP_KEYS = frozenset({"summary_file", "detail_file", "key", "program", "install_location",
                       "targets", "path", "expanded_path", "app", "value", "reference_file",
                       "id"})

GENERATED_AT = "2026-09-30T08:10:00+00:00"
TARGET = "C:\\Apps\\Invented Editor 652\\v658\\tray.exe"


SOURCES = ("win32_programs", "msix_programs", "run_keys", "startup_folders",
           "startup_approved", "scheduled_tasks", "services", "file_facts")
ITEM_SOURCES = ("win32_programs", "msix_programs", "run_keys", "startup_folders",
                "scheduled_tasks", "services")
TRAY = "C:\\Program Files\\Invented Editor\\tray.exe"
DETAIL_SECTIONS = ("programs", "autostart", "changes", "components", "drivers", "additions",
                   "driver_packages")
# Plan 052 M3: summary keys the real profile requires, and the new id letters.
REQUIRED_KEYS_052 = ("components", "component_counts", "drivers", "additions", "hosts_file")
SOURCES_052 = ("optional_features", "capabilities", "drivers", "firewall_rules",
               "root_certificates", "hosts", "administrators", "defender_exclusions")
ADMIN_ONLY = ("capabilities", "defender_exclusions")


def _fact(path, program):
    return {"path": path, "expanded_path": path, "exists": True,
            "signature_status": "Valid", "signer": "Example Soft",
            "company": "Example Soft", "program": program}


def _autostart_item():
    return {
        "id": "s1",
        "key": "run:hkcu\\Run:InventedTray",
        "source": "run_keys",
        "kind": "run",
        "location": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        "name": "InventedTray",
        "command": f'"{TRAY}" --quiet',
        "value_kind": "String",
        "enabled": True,
        "approved": "enabled",
        "approved_byte": 2,
        "targets": [TRAY],
        "facts": [_fact(TRAY, "win32:hklm64:InventedEditor")],
        "facts_from_baseline": False,
        "own": False,
        "unread_fields": [],
        "from_baseline": False,
    }


def _program(item_id, name, version, publisher, install_date):
    return {
        "id": item_id,
        "key": f"win32:hklm64:{name.replace(' ', '')}",
        "source": "win32_programs",
        "own": False,
        "name": name,
        "version": version,
        "publisher": publisher,
        "install_date": install_date,
        "install_location": f"C:\\Program Files\\{name}",
        "scope": "machine",
        "system_component": False,
        "from_baseline": False,
    }


def _change_item(name):
    return {
        "id": "c1",
        "key": f"win32:hklm64:{name.replace(' ', '')}",
        "source": "win32_programs",
        "change": "added",
        "name": name,
        "own": False,
    }


def _summary_data(summary_file, detail_file, *, programs, changes, truncated, baseline,
                  own_counts):
    compared = "compared" if baseline["status"] == "compared" else "no_baseline"
    return {
        "schema_version": 1,
        "skill": SKILL,
        "generated_at": GENERATED_AT,
        "elevated": False,
        "sources": [{"name": name, "status": "read", "reason": None} for name in SOURCES],
        "not_checked": [{"what": "scheduled_tasks visibility",
                         "reason": "without administrator rights the task list may be "
                                   "incomplete"}],
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": truncated,
        "baseline": baseline,
        "comparison": {name: compared for name in ITEM_SOURCES},
        "programs": programs,
        "autostart": [_autostart_item()],
        "own_counts": own_counts,
        "changes": changes,
        "own_changes": {"added": 0, "removed": 0, "changed": 0},
        # Plan 052 M3 point 6: the keys of the profile's required_keys, empty here.
        "components": [],
        "component_counts": {
            "feature": {"enabled": 0, "disabled": 0, "absent": 0, "unread": 0},
            "capability": None,
            "drivers_without_inf": 0,
        },
        "drivers": [],
        "additions": [],
        "hosts_file": {"exists": True, "path_is_default": True},
        # Plan 024 M2: driver_packages joins the profile's required_keys, empty here.
        "driver_packages": [],
        # Plan 025 M1: vendor_folders joins the profile's required_keys, empty here.
        "vendor_folders": [],
        # Plan 029 M2: package_managers joins the profile's required_keys, empty here.
        "package_managers": {
            "pip": {"status": "empty", "pythons": []},
            "npm": {"status": "empty", "prefix_from": "default", "count": 0,
                    "unreadable": 0},
        },
    }


def _clean_summary(summary_file, detail_file):
    """One program, one autostart entry, one change; compared with a baseline."""
    return _summary_data(
        summary_file,
        detail_file,
        programs=[_program("a1", "Invented Editor", "4.2.0", "Example Soft", "2026-03-14")],
        changes=[_change_item("Invented Editor")],
        truncated=0,
        baseline={
            "status": "compared",
            "created_at": "2026-05-07T01:00:00+00:00",
            "age_days": 146.3,
            "saved": True,
            "reason": None,
        },
        own_counts={"programs": 23, "autostart": {"service": 17, "task": 9}, "unknown": 0},
    )


def _clean_report_lines(summary_file):
    """A report whose numbers all come from the clean summary."""
    return [
        f"<!-- ush:summary {summary_file} -->",
        "# Inventory report, 2026-09-30 08:10",
        "",
        "| # | Area | State | Action |",
        "|---|------|-------|--------|",
        "| 1 | Programs | one listed | none |",
        "| 2 | Autostart | one listed | review |",
        "| 3 | Changes | one since the baseline | none |",
        "",
        "## Comparison",
        "Compared with the baseline of 2026-05-07, 146.3 days old.",
        "- c1: Invented Editor was added, version 4.2.0.",
        "",
        "## Programs",
        "- a1: Invented Editor 4.2.0 by Example Soft, installed 2026-03-14.",
        "- Windows programs: 23.",
        "",
        "## Autostart",
        ("- s1: InventedTray starts at sign-in from the Run key of HKCU; approved, "
         "file present, signature valid."),
        "- Windows services (not listed): 17.",
        "- Windows tasks (not listed): 9.",
        "",
        "## Not checked",
        "<!-- ush:not-checked -->",
        "- scheduled_tasks visibility: the task list may be incomplete without administrator rights.",
    ]


def _summary_048_shape(summary_file, detail_file):
    """The clean summary as plan 048 wrote it: none of the 052 keys."""
    summary = _clean_summary(summary_file, detail_file)
    for key in REQUIRED_KEYS_052:
        summary.pop(key, None)
    return summary


def _summary_052(summary_file, detail_file, *, truncated_drivers=0):
    """The clean summary with one component, one driver and two additions (no admin)."""
    summary = _clean_summary(summary_file, detail_file)
    summary["sources"] += [
        {"name": name, "status": "unreadable" if name in ADMIN_ONLY else "read",
         "reason": "requires administrator" if name in ADMIN_ONLY else None}
        for name in SOURCES_052
    ]
    summary["not_checked"] += [{"what": name, "reason": "requires administrator"}
                               for name in ADMIN_ONLY]
    summary["comparison"].update(
        {name: "not_read" if name in ADMIN_ONLY else "compared" for name in SOURCES_052})
    summary["own_counts"].update({
        "drivers": 118,
        "firewall_rules": {"local": 402, "app_iso": 61, "policy": 0},
        "root_certificates": 9,
    })
    summary["components"] = [{
        "id": "f1",
        "key": "feature:Invented-Feature-Alpha",
        "kind": "feature",
        "name": "Invented-Feature-Alpha",
        "state": "enabled",
    }]
    summary["component_counts"] = {
        "feature": {"enabled": 1, "disabled": 14, "absent": 6, "unread": 0},
        "capability": None,
        "drivers_without_inf": 7,
    }
    summary["drivers"] = [{
        "id": "d1",
        "key": "driver:PCI\\VEN_1AAA&DEV_0030\\0030",
        "device_name": "Invented Network Adapter",
        "class": "Net",
        "provider": "Invented Hardware Vendor Ltd",
        "version": "12.7.3.1",
        "date": "2026-02-11",
        "signer": "Invented Hardware Compatibility Publisher",
    }]
    summary["additions"] = [
        {
            "id": "x1",
            "key": "admin:S-1-5-21-0-0-0-1001",
            "kind": "administrator",
            "name": "InventedUser",
            "object_class": "User",
            "principal_source": "MicrosoftAccount",
            "enabled": True,
            "is_current": True,
            "unread_fields": [],
        },
        {
            "id": "x2",
            "key": "hosts:ads.example:0.0.0.0",
            "kind": "hosts_entry",
            "address": "0.0.0.0",
            "hostname": "ads.example",
            "line": 3,
            "duplicates": 0,
        },
    ]
    summary["hosts_file"] = {"exists": True, "path_is_default": True}
    summary["truncated_drivers"] = truncated_drivers
    summary["truncated_components"] = 0
    summary["truncated_additions"] = 0
    return summary


def _report_052_lines(summary_file):
    """The clean report plus the 052 sections; every number comes from _summary_052."""
    base = _clean_report_lines(summary_file)
    cut = base.index("## Not checked")
    sections = [
        "## Components",
        "- f1: Invented-Feature-Alpha (optional feature), enabled.",
        "- Optional features enabled: 1, disabled: 14, not present: 6.",
        "",
        "## Drivers",
        ("- d1: Invented Network Adapter (Net) from Invented Hardware Vendor Ltd, "
         "version 12.7.3.1 of 2026-02-11, signed by Invented Hardware Compatibility "
         "Publisher."),
        "- Windows drivers (not listed): 118.",
        "- Devices without a driver: 7.",
        "",
        "## Added to the system",
        "Things outside the Windows lists of the data file, not suspicious things.",
        ("- x1: InventedUser is a member of Administrators (MicrosoftAccount), enabled; "
         "this is the current account."),
        "- x2: the hosts file maps ads.example to 0.0.0.0.",
        "- The hosts file exists at the default path.",
        "- Windows firewall rules (not listed): 402 local, 61 app_iso, 0 policy.",
        "- Windows root certificates (not listed): 9.",
        "",
    ]
    not_checked = [
        "- capabilities: requires administrator.",
        "- defender_exclusions: requires administrator.",
    ]
    return base[:cut] + sections + base[cut:] + not_checked


def _numbers(data):
    """Integers the checker would take from parsed JSON (skip keys left out)."""
    found = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                found.update(int(n) for n in re.findall(r"[0-9]+", str(key)))
                if key not in SKIP_KEYS:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, (int, float, str)) and not isinstance(item, bool):
            found.update(int(n) for n in re.findall(r"[0-9]+", str(item)))
    return found


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def _assert_real_profile(self):
        # The checker's own SKILLS_DIR, not patched: the real profile file.
        profile = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        self.assertTrue(profile.is_file(),
                        f"the ush-inventory report profile is missing: {profile}")

    def _write_summary(self, name, builder, cut=None):
        """Write the summary and its detail file; ``cut`` adds items cut from the summary
        to detail sections ({section: [item, ...]})."""
        summary_file = self.work / f"{name}-summary.json"
        detail_file = self.work / f"{name}-detail.json"
        summary = builder(summary_file, detail_file)
        # Every detail section is written, also the 052 ones, so that no test can fail
        # on a missing detail section instead of what it asserts.
        detail = {section: list(summary.get(section) or []) + list((cut or {}).get(section, []))
                  for section in DETAIL_SECTIONS}
        detail_file.write_text(json.dumps(detail), encoding="utf-8")
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        return summary_file, summary

    def _write_report(self, lines, name):
        path = self.reports / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _run(self, report):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(report)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_clean_report_passes(self):
        self._assert_real_profile()
        summary_file, _ = self._write_summary("inventory", _clean_summary)
        report = self._write_report(_clean_report_lines(summary_file),
                                    "inventory-2026-09-30-0810.md")
        code, output = self._run(report)
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)

    def test_missing_item_or_rewritten_number_fails(self):
        self._assert_real_profile()
        summary_file, summary = self._write_summary("inventory", _clean_summary)
        clean = _clean_report_lines(summary_file)
        code, output = self._run(self._write_report(clean, "control.md"))
        self.assertEqual(code, 0, f"the control report should pass; output:\n{output}")

        with self.subTest("autostart item s1 not named"):
            lines = [line for line in clean if not line.startswith("- s1:")]
            self.assertFalse(any(re.search(r"\bs1\b", line) for line in lines[1:]))
            code, output = self._run(self._write_report(lines, "no-entry.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertTrue(
                any(re.search(r"\bs1\b", line) and "autostart" in line
                    for line in output.splitlines()),
                f"expected a line naming s1 and autostart; output:\n{output}",
            )

        with self.subTest("age_days written differently from the JSON"):
            number = "147"
            summary_text = summary_file.read_text(encoding="utf-8")
            self.assertNotIn(number, summary_text, "the number must not occur in the JSON")
            self.assertNotIn(int(number), _numbers(summary))
            self.assertNotIn(number, str(self.root), "temp path collides with the number")
            original = "Compared with the baseline of 2026-05-07, 146.3 days old."
            self.assertIn(original, clean)
            lines = [line.replace("146.3", number) if line == original else line
                     for line in clean]
            code, output = self._run(self._write_report(lines, "rewritten.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn(number, output)

    def test_key_and_path_digits_back_no_number(self):
        """Item keys and file paths are no readings: their digits back nothing."""
        self._assert_real_profile()

        def keyed_summary(summary_file, detail_file):
            summary = _clean_summary(summary_file, detail_file)
            summary["programs"][0].update({
                "key": "win32:hklm64:InventedEditor731",
                "install_location": "C:\\Apps\\Invented Editor 652",
            })
            summary["autostart"][0].update({
                "key": "run:hkcu\\Run:InventedTray",
                "targets": [TARGET],
                "facts": [{
                    "path": TARGET,
                    "expanded_path": TARGET,
                    "exists": True, "signature_status": "Valid",
                    "signer": "Example Soft", "company": "Example Soft",
                    "program": "win32:hklm64:InventedEditor731",
                }],
            })
            # A fact change is named by its target, and a program change carries
            # program keys: neither backs a number.
            summary["changes"].append({
                "id": "c2", "key": "run:hkcu\\Run:InventedTray", "source": "run_keys",
                "change": "changed", "name": "InventedTray", "own": False,
                "fields": {
                    f"facts[{TARGET}].signature_status": {"before": "Valid",
                                                          "after": "NotSigned"},
                    f"facts[{TARGET}].program": {"before": "win32:hklm64:InventedEditor731",
                                                 "after": None},
                },
            })
            return summary

        summary_file, _ = self._write_summary("inventory-keys", keyed_summary)
        clean = _clean_report_lines(summary_file) + [
            "- c2: InventedTray, signature Valid became NotSigned; no program matched now."]
        code, output = self._run(self._write_report(clean, "keys-control.md"))
        self.assertEqual(code, 0, f"the control report should pass; output:\n{output}")
        for number in ("731", "652", "658"):
            with self.subTest(number=number):
                self.assertNotIn(number, str(self.root), "temp path collides with the number")
                lines = clean + [f"- {number} programs were checked."]
                code, output = self._run(self._write_report(lines, f"keys-{number}.md"))
                self.assertEqual(code, 1, f"output:\n{output}")
                self.assertIn(number, output)

    def test_cut_programs_are_known(self):
        self._assert_real_profile()

        def cut_summary(summary_file, detail_file):
            return _summary_data(
                summary_file,
                detail_file,
                programs=[
                    _program("a1", "Invented Viewer", "3.1", "Example Soft", "2026-01-20"),
                    _program("a2", "Sample Notes", "2.0.6", "Sample Works", "2026-02-11"),
                ],
                changes=[_change_item("Sample Notes")],
                truncated=3,
                baseline={"status": "none", "created_at": None, "age_days": None,
                          "saved": True, "reason": None},
                own_counts={"programs": 12, "autostart": {"service": 9, "task": 6},
                            "unknown": 0},
            )

        # Program ids are stable: the cut ones are known from the detail file,
        # not from the positions after the list.
        cut = [
            _program("a14", "Invented Mapper", "1.0", "Example Soft", "2026-01-20"),
            _program("a17", "Sample Clock", "2.0", "Sample Works", "2026-02-11"),
            _program("a23", "Invented Player", "3.1", "Example Soft", "2026-01-20"),
        ]
        summary_file, summary = self._write_summary("inventory-cut", cut_summary,
                                                    cut={"programs": cut})
        self.assertEqual(len(summary["programs"]), 2)
        self.assertEqual(summary["truncated"], 3)
        # a14, a17 and a23 are backed only by being known ids, not by their digits.
        for number in (14, 17, 23):
            self.assertNotIn(number, _numbers(summary))

        lines = [
            f"<!-- ush:summary {summary_file} -->",
            "# Inventory report, 2026-09-30 08:10",
            "",
            "## Comparison",
            "No comparison: this is the first run.",
            "- c1: Sample Notes was added, version 2.0.6.",
            "",
            "## Programs",
            "- a1: Invented Viewer 3.1 by Example Soft, installed 2026-01-20.",
            "- a2: Sample Notes 2.0.6 by Sample Works, installed 2026-02-11.",
            "- 3 more programs were cut from the summary: a14, a17, a23.",
            "- Windows programs: 12.",
            "",
            "## Autostart",
            "- s1: InventedTray starts at sign-in from the Run key of HKCU.",
            "- Windows services (not listed): 9.",
            "- Windows tasks (not listed): 6.",
            "",
            "## Not checked",
            "<!-- ush:not-checked -->",
            "- scheduled_tasks visibility: the task list may be incomplete.",
        ]
        code, output = self._run(self._write_report(lines, "inventory-2026-09-30-0811.md"))
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)

    # Plan 052 M3.

    def _run_guarded(self, report):
        """Like _run, but a crash of the checker is a result, not a test error."""
        try:
            return self._run(report)
        except (TypeError, KeyError, AttributeError, ValueError) as exc:  # a crash fails the assertion
            return None, f"checker raised {type(exc).__name__}: {exc}"

    def _assert_052_profile(self):
        """The real profile knows the 052 lists (plan 052 M3 point 2)."""
        self._assert_real_profile()
        path = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        letters = profile.get("id_letters") or ""
        for letter in "fdx":
            self.assertIn(letter, letters, f"id_letters of the profile: {letters!r}")
        required = profile.get("required_keys") or []
        for key in REQUIRED_KEYS_052:
            self.assertIn(key, required, f"required_keys of the profile: {required!r}")

    def test_summary_before_052_fails(self):
        self._assert_real_profile()
        summary_file, _ = self._write_summary("inventory-052", _clean_summary)
        clean = _clean_report_lines(summary_file)
        code, output = self._run_guarded(self._write_report(clean, "control.md"))
        self.assertEqual(code, 0, f"the control report should pass; output:\n{output}")

        old_file, old = self._write_summary("inventory-048", _summary_048_shape)
        for key in REQUIRED_KEYS_052:
            self.assertNotIn(key, old)
        lines = _clean_report_lines(old_file)
        self.assertFalse(any("components" in line for line in lines))
        self.assertNotIn("components", str(self.root), "temp path contains the key name")
        code, output = self._run_guarded(self._write_report(lines, "old-shape.md"))
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertNotIn("OK", output)
        self.assertIn("components", output)

    def test_clean_report_with_new_lists_passes(self):
        self._assert_052_profile()
        summary_file, summary = self._write_summary("inventory-new", _summary_052)
        lines = _report_052_lines(summary_file)
        for item_id in ("a1", "s1", "c1", "f1", "d1", "x1"):
            self.assertTrue(any(re.search(rf"\b{item_id}\b", line) for line in lines[1:]),
                            item_id)
        for number in ("14", "118", "402", "61", "7", "9"):
            self.assertIn(int(number), _numbers(summary), number)
        code, output = self._run_guarded(
            self._write_report(lines, "inventory-2026-09-30-0812.md"))
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertIn("OK", output)

    def test_missing_addition_fails_and_cut_drivers_known(self):
        self._assert_real_profile()
        summary_file, _ = self._write_summary("inventory-new", _summary_052)
        clean = _report_052_lines(summary_file)
        code, output = self._run_guarded(self._write_report(clean, "control.md"))
        self.assertEqual(code, 0, f"the control report should pass; output:\n{output}")

        with self.subTest("addition x2 not named"):
            lines = [line for line in clean if not line.startswith("- x2:")]
            self.assertFalse(any(re.search(r"\bx2\b", line) for line in lines[1:]))
            self.assertFalse(any("additions" in line for line in lines))
            self.assertNotIn("additions", str(self.root), "temp path contains the list name")
            code, output = self._run_guarded(self._write_report(lines, "no-entry.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn("additions", output)

        with self.subTest("truncated_drivers 2: d27 and d36 from the detail file are known"):
            # Driver ids are stable: the cut ones come from the detail file.
            cut_drivers = [
                {"id": "d27", "key": "driver:PCI\\VEN_1AAA&DEV_0031\\0031",
                 "device_name": "Invented Audio Device", "class": "Media"},
                {"id": "d36", "key": "driver:USB\\VID_1AAA&PID_0032\\0032",
                 "device_name": "Invented Card Reader", "class": "USB"},
            ]
            cut_file, cut = self._write_summary(
                "inventory-cut-drivers",
                lambda s, d: _summary_052(s, d, truncated_drivers=2),
                cut={"drivers": cut_drivers})
            self.assertEqual(len(cut["drivers"]), 1)
            # d27 and d36 are backed only by being known ids, not by their digits.
            for number in (27, 36):
                self.assertNotIn(number, _numbers(cut))
            lines = _report_052_lines(cut_file)
            at = lines.index("- Windows drivers (not listed): 118.")
            lines.insert(at,
                         "- d27 and d36 were cut from the summary; they are in the detail file.")
            code, output = self._run_guarded(self._write_report(lines, "cut-drivers.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)


    def test_collapsed_change_id_known(self):
        """A change inside a collapsed entry is named by its id from the detail file,
        also when nothing was cut (plan 010 M1, code-review round 2)."""
        self._assert_real_profile()
        collapsed_rules = [
            {"id": f"c{number}", "key": f"fw:local:{{invented-{number}}}",
             "source": "firewall_rules", "change": "added",
             "name": f"ms-resource:invented-{number}", "own": False}
            for number in (47, 48, 49)
        ]

        def build(count_key_value):
            def builder(summary_file, detail_file):
                summary = _summary_052(summary_file, detail_file)
                summary["changes"].append({"collapsed": "ms-resource",
                                           "source": "firewall_rules",
                                           "change": "added", "count": 3})
                summary["truncated_autostart"] = 0
                summary["truncated_changes"] = 0
                summary["collapsed_changes"] = count_key_value
                return summary
            return builder

        for value, expected in ((3, 0), (0, 1)):
            with self.subTest(collapsed_changes=value):
                summary_file, summary = self._write_summary(
                    f"inventory-collapsed-{value}", build(value),
                    cut={"changes": collapsed_rules})
                self.assertNotIn(48, _numbers(summary))
                lines = _report_052_lines(summary_file)
                at = lines.index("## Not checked")
                lines.insert(at, "- c48 is one of 3 collapsed firewall rule changes.")
                code, output = self._run_guarded(
                    self._write_report(lines, f"collapsed-{value}.md"))
                self.assertEqual(code, expected, f"output:\n{output}")

    def test_addition_paths_back_no_number(self):
        """A firewall rule's program and a Defender exclusion are paths: no readings."""
        self._assert_real_profile()
        game = "C:\\Games\\Invented Game 7342\\bin\\game.exe"
        cache = "C:\\Invented Cache 8163"

        def with_paths(summary_file, detail_file):
            summary = _summary_052(summary_file, detail_file)
            summary["additions"] += [
                {"id": "x3", "key": "firewall:local:{invented-rule}", "kind": "firewall_rule",
                 "store": "local", "name": "InventedGame", "action": "Allow", "dir": "In",
                 "active": "TRUE", "protocol": None, "protocol_name": None, "lport": None,
                 "app": game},
                {"id": "x4", "key": "defender:path:" + cache.lower(),
                 "kind": "defender_exclusion", "type": "path", "value": cache,
                 "origin": None},
            ]
            return summary

        summary_file, _ = self._write_summary("inventory-paths", with_paths)
        clean = _report_052_lines(summary_file)
        at = clean.index("- x2: the hosts file maps ads.example to 0.0.0.0.") + 1
        clean[at:at] = ["- x3: firewall rule InventedGame (local) allows inbound traffic.",
                        "- x4: a Defender path exclusion of unknown origin."]
        code, output = self._run_guarded(self._write_report(clean, "paths-control.md"))
        self.assertEqual(code, 0, f"the control report should pass; output:\n{output}")
        for number in ("7342", "8163"):
            with self.subTest(number=number):
                self.assertNotIn(number, str(self.root), "temp path collides with the number")
                lines = clean + [f"- {number} rules were checked."]
                code, output = self._run_guarded(self._write_report(lines, f"paths-{number}.md"))
                self.assertEqual(code, 1, f"output:\n{output}")
                self.assertIn(number, output)


# Plan 024 M2 (K6): orphan driver packages (o..) are a required list of the profile.
PACKAGE_ITEM = {
    "id": "o1",
    "key": "driver_package:inventedpad.inf|invented peripherals corp|1.2.3.4",
    "published_name": "oem12.inf",
    "original_name": "inventedpad.inf",
    "provider": "Invented Peripherals Corp",
    "class": "Mouse",
    "version": "1.2.3.4",
    "date": "2024-03-14",
    "signer": "Invented Driver Signer",
    "present_device": False,
}


def _summary_packages(summary_file, detail_file):
    """The 052 summary plus one driver package with no present device, of 3 in the store."""
    summary = _summary_052(summary_file, detail_file)
    summary["sources"].append({"name": "driver_packages", "status": "read", "reason": None})
    summary["comparison"]["driver_packages"] = "compared"
    summary["component_counts"].update({"driver_packages": 3,
                                        "driver_packages_without_device": 1})
    summary["driver_packages"] = [dict(PACKAGE_ITEM)]
    return summary


def _report_packages_lines(summary_file):
    """The 052 report plus a Driver packages section; numbers from _summary_packages."""
    lines = _report_052_lines(summary_file)
    at = lines.index("## Not checked")
    lines[at:at] = [
        "## Driver packages",
        ("- o1: inventedpad.inf from Invented Peripherals Corp (Mouse), version 1.2.3.4 "
         "of 2024-03-14, signed by Invented Driver Signer; no present device uses it."),
        "- Third-party driver packages: 3, with no present device: 1.",
        "",
    ]
    return lines


class TestDriverPackagesProfile(unittest.TestCase):
    # The helpers of TestProfile, without running its tests a second time.
    setUp = TestProfile.setUp
    _assert_real_profile = TestProfile._assert_real_profile
    _write_summary = TestProfile._write_summary
    _write_report = TestProfile._write_report
    _run = TestProfile._run
    _run_guarded = TestProfile._run_guarded

    def test_orphan_package_must_be_named(self):
        self._assert_real_profile()
        path = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("o", profile.get("id_letters") or "", profile.get("id_letters"))
        self.assertIn("driver_packages", profile.get("required_lists") or [],
                      profile.get("required_lists"))
        self.assertIn("driver_packages", profile.get("required_keys") or [],
                      profile.get("required_keys"))

        summary_file, _ = self._write_summary("inventory-packages", _summary_packages)
        named = _report_packages_lines(summary_file)
        code, output = self._run_guarded(
            self._write_report(named, "inventory-2026-11-05-1420.md"))
        self.assertEqual(code, 0, f"the report naming o1 should pass; output:\n{output}")
        self.assertIn("OK", output)

        left_out = [line for line in named if not line.startswith("- o1:")]
        self.assertFalse(any(re.search(r"\bo1\b", line) for line in left_out[1:]))
        code, output = self._run_guarded(self._write_report(left_out, "no-package.md"))
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertTrue(
            any("not named in the report" in line and re.search(r"\bo1\b", line)
                for line in output.splitlines()),
            f"expected 'not named in the report' naming o1; output:\n{output}")


# Plan 025 M1 (K7): vendor folders no installed program matches (v..) are a required
# list of the profile.
VENDOR_FOLDER_ITEM = {
    "id": "v1",
    "key": "vendor_folder:c:\\programdata\\contoso",
    "path": "C:\\ProgramData\\Contoso",
    "root": "%ProgramData%",
    "matched": False,
    "has_entries": True,
    "last_write": "2025-11-02T09:15:00Z",
}
# Plan 025, option C: a folder no rule matches while an autostart target was not read
# is listed too, with matched null and the cause in not_judged.
NOT_JUDGED_FOLDER_ITEM = {
    "id": "v2",
    "key": "vendor_folder:c:\\program files\\fabrikam",
    "path": "C:\\Program Files\\Fabrikam",
    "root": "%ProgramFiles%",
    "matched": None,
    "has_entries": True,
    "last_write": "2025-10-14T08:00:00Z",
    "not_judged": "the target path of 1 autostart entry",
}


def _summary_vendor_folders(summary_file, detail_file):
    """The driver package summary plus one unmatched vendor folder of 5 read."""
    summary = _summary_packages(summary_file, detail_file)
    summary["sources"].append({"name": "vendor_folders", "status": "read", "reason": None})
    summary["component_counts"].update({
        "vendor_folders_read": 5,
        "vendor_folders_matched": 4,
        "vendor_folders_unmatched": 1,
        "reparse_points": 2,
        "installer_guid_folders": 6,
    })
    summary["vendor_folders"] = [dict(VENDOR_FOLDER_ITEM)]
    return summary


def _report_vendor_folders_lines(summary_file):
    """The driver package report plus a Vendor folders section; numbers from
    _summary_vendor_folders."""
    lines = _report_packages_lines(summary_file)
    at = lines.index("## Not checked")
    lines[at:at] = [
        "## Vendor folders",
        ("- v1: C:\\ProgramData\\Contoso (root %ProgramData%) holds entries, last written "
         "2025-11-02; no installed program matches it."),
        ("- Top-level folders read: 5, matched: 4, not matched: 1; reparse points "
         "skipped: 2; Installer folders named by a product code: 6."),
        "",
    ]
    return lines


class TestVendorFoldersProfile(unittest.TestCase):
    # The helpers of TestProfile, without running its tests a second time.
    setUp = TestProfile.setUp
    _assert_real_profile = TestProfile._assert_real_profile
    _write_summary = TestProfile._write_summary
    _write_report = TestProfile._write_report
    _run = TestProfile._run
    _run_guarded = TestProfile._run_guarded

    def _write_vendor_summary(self, name):
        """Write the summary and its detail file, with the detail list
        ``vendor_folders`` (every folder read) and the roots' status beside it."""
        summary_file, summary = self._write_summary(name, _summary_vendor_folders)
        detail_file = Path(summary["detail_file"])
        detail = json.loads(detail_file.read_text(encoding="utf-8"))
        detail["vendor_folder_roots"] = [{"root": "%ProgramData%", "expanded": "C:\\ProgramData",
                                          "status": "read", "reason": None}]
        detail["vendor_folders"] = [dict(VENDOR_FOLDER_ITEM, name="Contoso", reason=None,
                                         matched=False, matched_by=[])]
        detail_file.write_text(json.dumps(detail), encoding="utf-8")
        return summary_file

    def test_folder_fetched_in_detail_passes(self):
        """A report that names a vendor folder in an ``ush:detail`` line finds it in
        the detail file's ``vendor_folders`` list."""
        self._assert_real_profile()
        summary_file = self._write_vendor_summary("inventory-vendor-folders-detail")
        lines = _report_vendor_folders_lines(summary_file)
        at = lines.index("## Vendor folders") + 1
        lines[at:at] = ["<!-- ush:detail v1 -->"]
        code, output = self._run_guarded(self._write_report(lines, "vendor-folder-detail.md"))
        self.assertEqual(code, 0, f"a report fetching v1 should pass; output:\n{output}")
        self.assertIn("OK", output)

    def test_unmatched_folder_must_be_named(self):
        self._assert_real_profile()
        path = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("v", profile.get("id_letters") or "", profile.get("id_letters"))
        self.assertIn("vendor_folders", profile.get("required_lists") or [],
                      profile.get("required_lists"))
        self.assertIn("vendor_folders", profile.get("required_keys") or [],
                      profile.get("required_keys"))

        summary_file = self._write_vendor_summary("inventory-vendor-folders")
        named = _report_vendor_folders_lines(summary_file)
        code, output = self._run_guarded(
            self._write_report(named, "inventory-2026-11-06-0930.md"))
        self.assertEqual(code, 0, f"the report naming v1 should pass; output:\n{output}")
        self.assertIn("OK", output)

        left_out = [line for line in named if not line.startswith("- v1:")]
        self.assertFalse(any(re.search(r"\bv1\b", line) for line in left_out[1:]))
        code, output = self._run_guarded(self._write_report(left_out, "no-vendor-folder.md"))
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertTrue(
            any("not named in the report" in line and re.search(r"\bv1\b", line)
                for line in output.splitlines()),
            f"expected 'not named in the report' naming v1; output:\n{output}")

    def test_not_judged_folder_must_be_named(self):
        """A listed folder with matched null (not judged) is a required v id too."""
        self._assert_real_profile()
        summary_file = self._write_vendor_summary("inventory-vendor-folders-not-judged")
        summary = json.loads(Path(summary_file).read_text(encoding="utf-8"))
        summary["vendor_folders"].append(dict(NOT_JUDGED_FOLDER_ITEM))
        summary["component_counts"].update({"vendor_folders_matched": 3,
                                            "vendor_folders_unknown": 1})
        Path(summary_file).write_text(json.dumps(summary), encoding="utf-8")

        lines = _report_vendor_folders_lines(summary_file)
        at = lines.index("## Not checked")
        lines[at:at] = [
            "## Vendor folders not judged",
            ("- v2: C:\\Program Files\\Fabrikam (root %ProgramFiles%) not judged: "
             "the target path of 1 autostart entry could not be read."),
            "",
        ]
        code, output = self._run_guarded(
            self._write_report(lines, "inventory-2026-11-06-0931.md"))
        self.assertEqual(code, 0, f"the report naming v1 and v2 should pass; output:\n{output}")
        self.assertIn("OK", output)

        left_out = [line for line in lines if not line.startswith("- v2:")]
        self.assertFalse(any(re.search(r"\bv2\b", line) for line in left_out))
        code, output = self._run_guarded(self._write_report(left_out, "no-not-judged.md"))
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertTrue(
            any("not named in the report" in line and re.search(r"\bv2\b", line)
                for line in output.splitlines()),
            f"expected 'not named in the report' naming v2; output:\n{output}")


# Plan 029 M2 (K5): package_managers is a required key of the profile.
PACKAGE_MANAGERS_NOTES = [
    {"what": "winget",
     "reason": "not read: `winget list` may go online and has no offline flag"},
    {"what": "Python installs not registered in PEP 514 (venvs, portable builds)",
     "reason": "not searched"},
    {"what": "other package managers (choco, scoop, cargo, go)", "reason": "not searched"},
]


def _summary_package_managers(summary_file, detail_file):
    """The clean summary plus one Python with 3 packages and npm with 2 packages."""
    summary = _clean_summary(summary_file, detail_file)
    summary["sources"] += [{"name": name, "status": "read", "reason": None}
                           for name in ("pip_packages", "npm_packages")]
    summary["comparison"].update({"pip_packages": "compared", "npm_packages": "compared"})
    summary["not_checked"] += [dict(note) for note in PACKAGE_MANAGERS_NOTES]
    summary["package_managers"] = {
        "pip": {"status": "read", "pythons": [{
            "python": "PythonCore/3.12", "count": 3, "unreadable": 0,
            "folders": {"install": "read", "user": "absent"},
        }]},
        "npm": {"status": "read", "prefix_from": "npmrc", "count": 2, "unreadable": 0},
    }
    return summary


def _summary_without_package_managers(summary_file, detail_file):
    """The same summary without the package_managers key (a summary before plan 029)."""
    summary = _summary_package_managers(summary_file, detail_file)
    summary.pop("package_managers")
    return summary


PACKAGE_MANAGERS_SECTION = [
    "## Package managers",
    "- pip, Python PythonCore/3.12: 3 packages, 0 unreadable; the user folder is absent.",
    "- npm (prefix from .npmrc): 2 global packages, 0 unreadable.",
    "- No package changes since the baseline.",
    "- Newer versions are not checked here; that is a matter for ush-advice.",
    "",
]
PACKAGE_MANAGERS_NOT_CHECKED = [
    "- winget: not read, `winget list` may go online and has no offline flag.",
    "- Python installs not registered in PEP 514 (venvs, portable builds): not searched.",
    "- Other package managers (choco, scoop, cargo, go): not searched.",
]


def _report_package_managers_lines(summary_file, with_section=True):
    """The clean report plus a Package managers section (numbers from
    _summary_package_managers) and the three not-checked lines."""
    lines = _clean_report_lines(summary_file)
    if with_section:
        at = lines.index("## Not checked")
        lines[at:at] = PACKAGE_MANAGERS_SECTION
    return lines + PACKAGE_MANAGERS_NOT_CHECKED


class TestPackageManagersProfile(unittest.TestCase):
    # The helpers of TestProfile, without running its tests a second time.
    setUp = TestProfile.setUp
    _assert_real_profile = TestProfile._assert_real_profile
    _write_summary = TestProfile._write_summary
    _write_report = TestProfile._write_report
    _run = TestProfile._run
    _run_guarded = TestProfile._run_guarded

    def test_package_managers_required(self):
        self._assert_real_profile()

        summary_file, summary = self._write_summary("inventory-package-managers",
                                                    _summary_package_managers)
        self.assertIn("package_managers", summary)
        lines = _report_package_managers_lines(summary_file)
        code, output = self._run_guarded(
            self._write_report(lines, "inventory-2026-11-08-1000.md"))
        self.assertEqual(code, 0,
                         f"the report with package managers should pass; output:\n{output}")
        self.assertIn("OK", output)

        old_file, old = self._write_summary("inventory-before-029",
                                            _summary_without_package_managers)
        self.assertNotIn("package_managers", old)
        lines = _report_package_managers_lines(old_file, with_section=False)
        self.assertFalse(any("package_managers" in line for line in lines))
        self.assertNotIn("package_managers", str(self.root), "temp path contains the key")
        code, output = self._run_guarded(self._write_report(lines, "no-package-managers.md"))
        self.assertEqual(code, 1, f"output:\n{output}")
        self.assertNotIn("OK", output)
        self.assertIn("package_managers", output)

        path = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("package_managers", profile.get("required_keys") or [],
                      profile.get("required_keys"))


if __name__ == "__main__":
    unittest.main()

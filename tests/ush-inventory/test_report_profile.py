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
DETAIL_SECTIONS = ("programs", "autostart", "changes", "components", "drivers", "additions")
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


if __name__ == "__main__":
    unittest.main()

"""The ush-processes report profile, checked through the shared report checker
(plan 051, M3).

The checker loads the real ``skills/ush-processes/data/report-profile.json``
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

SKILL = "ush-processes"
# Keys whose values supply no numbers (the profile's path_keys and id_keys).
SKIP_KEYS = frozenset({"summary_file", "detail_file", "id", "group"})
DETAIL_SECTIONS = ("groups", "ports")

GENERATED_AT = "2026-09-30T08:10:00+00:00"
TOTAL_BYTES = "8589934592"
SOURCES = ("processes", "perf", "owners", "memory", "services", "file_facts",
           "tcp_listeners", "udp_endpoints")


def _browser_group():
    return {
        "id": "g1",
        "name": "browser.exe",
        "path": "C:\\Apps\\Invented Browser\\browser.exe",
        "path_kind": "file",
        "count": 2,
        "pids": [130, 131],
        "memory_private_bytes": 1048576000,
        "memory_private_mb": 1000.0,
        "working_set_bytes": 1111490560,
        "working_set_mb": 1060.0,
        "memory_unread_count": 0,
        "services": [],
        "autostart": [{"key": "run:hkcu\\Run:InventedBrowser", "name": "InventedBrowser"}],
        "program": {"key": "win:hklm:InventedBrowser", "name": "Invented Browser"},
        "started_by": "autostart",
        "parent_gone": False,
        "unread_fields": [],
    }


def _host_group():
    return {
        "id": "g2",
        "name": "host.exe",
        "path": "C:\\Apps\\Invented Host\\host.exe",
        "path_kind": "file",
        "count": 1,
        "pids": [600],
        "memory_private_bytes": 262144000,
        "memory_private_mb": 250.0,
        "working_set_bytes": 293601280,
        "working_set_mb": 280.0,
        "memory_unread_count": 0,
        "services": [{"name": "InventedHostSvc", "key": "service:InventedHostSvc"}],
        "autostart": [],
        "program": {"key": "win:hklm:InventedHost", "name": "Invented Host"},
        "started_by": "service",
        "parent_gone": False,
        "unread_fields": [],
    }


def _ports():
    return [
        {
            "id": "p1",
            "protocol": "tcp",
            "local_address": "0.0.0.0",
            "local_port": 8080,
            "scope": "all",
            "pid": 600,
            "process": "host.exe",
            "group": "g2",
            "group_in_summary": True,
        },
        {
            "id": "p2",
            "protocol": "tcp",
            "local_address": "127.0.0.1",
            "local_port": 3000,
            "scope": "loopback",
            "pid": 130,
            "process": "browser.exe",
            "group": "g1",
            "group_in_summary": True,
        },
    ]


def _summary_data(summary_file, detail_file, *, truncated, counts):
    return {
        "schema_version": 1,
        "skill": SKILL,
        "generated_at": GENERATED_AT,
        "elevated": False,
        "sources": [{"name": name, "status": "read", "reason": None} for name in SOURCES],
        "not_checked": [],
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": truncated,
        "sorted_by": "memory_private_bytes",
        "memory": {
            "total_bytes": int(TOTAL_BYTES),
            "total_gb": 8.0,
            "available_gb": 2.0,
            "used_gb": 6.0,
            "listed_private_gb": 1.2,
        },
        "counts": counts,
        "groups": [_browser_group(), _host_group()],
        "ports": _ports(),
        "udp_bound": [{"group": "g2", "scope": "all", "count": 2}],
        "inventory": {
            "status": "read",
            "created_at": "2026-09-28T19:30:00+00:00",
            "age_days": 1.6,
            "missing_sources": [],
            "entries_without_path": 0,
            "reason": None,
        },
    }


def _clean_summary(summary_file, detail_file):
    """Two groups, two TCP ports, one UDP count; nothing cut."""
    return _summary_data(
        summary_file, detail_file, truncated=0,
        counts={"groups": 2, "processes": 3, "path_unread": 0,
                "command_line_unread": 0, "no_image": 0, "udp_port_zero": 0},
    )


def _cut_summary(summary_file, detail_file):
    """The same two groups, with 3 more groups cut from the summary.

    No count of all groups here: a total would back the digits of a cut id by
    itself, and the test must show that the cut ids are known from the detail file.
    """
    return _summary_data(
        summary_file, detail_file, truncated=3,
        counts={"processes": 3, "path_unread": 0, "command_line_unread": 0,
                "no_image": 0, "udp_port_zero": 0},
    )


MEMORY_LINE = f"- Memory in use: 6.0 GB of 8.0 GB ({TOTAL_BYTES} bytes); 2.0 GB available."
PORT_P2_LINE = "- p2: browser.exe (g1) listens on TCP 3000 on loopback only (127.0.0.1)."


def _clean_report_lines(summary_file, group_lines=()):
    """A report whose numbers all come from the clean summary."""
    return [
        f"<!-- ush:summary {summary_file} -->",
        "# Processes report, 2026-09-30 08:10",
        "",
        "## Memory",
        MEMORY_LINE,
        "- The listed groups hold 1.2 GB of private memory.",
        "",
        "## Programs",
        "| # | Program | Processes | Memory (MB) | Started by |",
        "|---|---------|-----------|-------------|------------|",
        "| 1 | g1 browser.exe | 2 | 1000.0 | autostart |",
        "| 2 | g2 host.exe | 1 | 250.0 | service |",
        "",
        "- g1: Invented Browser, started at sign-in by the autostart entry InventedBrowser.",
        "- g2: Invented Host, running as the service InventedHostSvc.",
        *group_lines,
        "",
        "## TCP ports",
        "- p1: host.exe (g2) listens on TCP 8080 on all addresses (0.0.0.0).",
        PORT_P2_LINE,
        "",
        "## UDP sockets",
        "- g2 host.exe: 2 bound UDP sockets on all addresses.",
        "",
        "## Inventory",
        "Links come from the ush-inventory baseline of 2026-09-28, 1.6 days old.",
        "",
        "## Not checked",
        "<!-- ush:not-checked -->",
        "- nothing.",
    ]


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


def _digit_free_tempdir():
    """A temporary directory whose random name holds no digits.

    The random part of a temp name could otherwise hold a guarded number and
    make a guard fail by chance.
    """
    for _ in range(500):
        tmp = tempfile.TemporaryDirectory(prefix="ush-processes-")
        if not re.search(r"\d", Path(tmp.name).resolve().name):
            return tmp
        tmp.cleanup()
    raise AssertionError("could not get a temporary directory name without digits")


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _digit_free_tempdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def _assert_real_profile(self):
        # The checker's own SKILLS_DIR, not patched: the real profile file.
        profile = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        self.assertTrue(profile.is_file(),
                        f"the ush-processes report profile is missing: {profile}")

    def _write_summary(self, name, builder, cut=None):
        """Write the summary and its detail file; ``cut`` adds items cut from the summary
        to detail sections ({section: [item, ...]})."""
        summary_file = self.work / f"{name}-summary.json"
        detail_file = self.work / f"{name}-detail.json"
        summary = builder(summary_file, detail_file)
        detail = {section: list(summary[section]) + list((cut or {}).get(section, []))
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
        summary_file, _ = self._write_summary("processes", _clean_summary)
        report = self._write_report(_clean_report_lines(summary_file),
                                    "processes-2026-09-30-0810.md")
        code, output = self._run(report)
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertTrue(output.startswith("OK"), f"output:\n{output}")

    def test_missing_port_or_rewritten_number_fails(self):
        self._assert_real_profile()
        summary_file, summary = self._write_summary("processes", _clean_summary)
        clean = _clean_report_lines(summary_file)
        code, output = self._run(self._write_report(clean, "processes-2026-09-30-0811.md"))
        self.assertEqual(code, 0, f"the control report should pass; output:\n{output}")

        with self.subTest("port p2 not named"):
            self.assertIn(PORT_P2_LINE, clean)
            lines = [line for line in clean if line != PORT_P2_LINE]
            self.assertFalse(any(re.search(r"\bp2\b", line) for line in lines[1:]))
            code, output = self._run(self._write_report(lines, "processes-2026-09-30-0812.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertTrue(
                any(re.search(r"\bp2\b", line) and "ports" in line
                    for line in output.splitlines()),
                f"expected a line naming p2 and ports; output:\n{output}",
            )

        with self.subTest("memory.total_bytes written differently from the JSON"):
            number = "8589934529"
            summary_text = summary_file.read_text(encoding="utf-8")
            self.assertNotIn(number, summary_text, "the number must not occur in the JSON")
            self.assertNotIn(int(number), _numbers(summary))
            self.assertNotIn(number, str(self.root), "temp path collides with the number")
            self.assertIn(MEMORY_LINE, clean)
            lines = [line.replace(TOTAL_BYTES, number) if line == MEMORY_LINE else line
                     for line in clean]
            self.assertNotEqual(lines, clean)
            code, output = self._run(self._write_report(lines, "processes-2026-09-30-0813.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertIn(number, output)

    def test_cut_groups_are_known(self):
        self._assert_real_profile()
        # Group ids are stable: the cut ones are known from the detail file,
        # not from the positions after the list.
        cut = []
        for item_id, name in (("g14", "editor.exe"), ("g17", "sync.exe"), ("g23", "tray.exe")):
            group = _host_group()
            group.update({"id": item_id, "name": name,
                          "path": f"C:\\Apps\\Invented Tools\\{name}"})
            cut.append(group)
        summary_file, summary = self._write_summary("processes-cut", _cut_summary,
                                                    cut={"groups": cut})
        self.assertEqual(len(summary["groups"]), 2)
        self.assertEqual(summary["truncated"], 3)
        # g14, g17 and g23 are backed only by being known ids, not by their digits.
        for number in (14, 17, 23):
            self.assertNotIn(number, _numbers(summary))

        lines = _clean_report_lines(
            summary_file,
            group_lines=("- 3 more groups were cut from the summary: g14, g17, g23.",),
        )
        code, output = self._run(self._write_report(lines, "processes-2026-09-30-0814.md"))
        self.assertEqual(code, 0, f"output:\n{output}")
        self.assertTrue(output.startswith("OK"), f"output:\n{output}")


if __name__ == "__main__":
    unittest.main()

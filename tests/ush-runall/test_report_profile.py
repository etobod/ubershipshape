"""The ush-runall report profile, checked through the shared report checker (plan 098, M3).

The checker loads the real ``skills/ush-runall/data/report-profile.json`` through its
unpatched ``SKILLS_DIR``; no copy of the profile is used, and the checker is not changed.
The plan gives the profile: ``report_prefix`` ``runall-``, ``detail_sections``
children/firewall_ports, ``id_letters`` ``hw``, ``required_lists`` children/firewall_ports,
``required_keys`` children/firewall_ports/firewall_ports_counts, ``truncated`` for
firewall_ports (w, count_key ``truncated``), ``id_keys`` ``[]`` and ``path_keys``
summary_file, detail_file, program_path.

K7 builds the summary and the detail file with ``runall.main`` and an injected fake
``run_child`` (M1/M2 helpers of ``test_runall.py`` and ``test_firewall_ports.py``); no
process is started and nothing on the machine is read.

Assumptions beyond the plan:

- With the plan's children table, the children get the ids ``h1`` (ush-health), ``h2``
  (ush-events), ``h3`` (ush-settings), ``h4`` (ush-inventory) ... ``h7`` (ush-advice);
  the test asserts this before relying on it.
- The ``summary_file`` named in the summary printed by ``main`` holds that same summary,
  and the detail file holds ``children`` items with ``id`` and ``summary`` and the
  ``firewall_ports`` items (as M1/M2 describe).
- The checker reports a required id it misses as ``not named in the report: <id>`` and
  an unbacked number by printing the number (as for the other skills).

``_clean_summary`` and ``_detail_data`` are a hand-written runall summary and detail file
in the shape of M1/M2, used by ``tests/ush-common/test_check_report_words.py``.
All data below is invented.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.skill_loader import REPO_ROOT, load_script

from .test_firewall_ports import (
    FirewallChildren,
    group,
    inventory_detail,
    port,
    processes_detail,
    rule,
)
from .test_runall import TABLE, RunallTestCase, entries, ok

SKILL = "ush-runall"
PROFILE_FILE = REPO_ROOT / "skills" / SKILL / "data" / "report-profile.json"
# The profile's path_keys and id_keys: their values supply no numbers.
SKIP_KEYS = frozenset({"summary_file", "detail_file", "program_path"})

PROGRAM = "C:\\PF\\Example\\srv.exe"
PROGRAM_GROUP_PATH = "c:\\pf\\example\\srv.exe"

DEVICE_NUMBER = "7731"      # a digit in the ush-health device name (h1)
EVENTS_ONLY_NUMBER = "5813"  # only in the ush-events summary (h2), never named
SETTING_VALUE = "4729"      # a numeric value of a ush-settings element (h3)
NESTED_NUMBER = "6183"      # a nested count of the ush-inventory summary (h4)
INVENTED_NUMBER = "9157"    # in no JSON at all

EXPECTED_IDS = {"ush-health": "h1", "ush-events": "h2", "ush-settings": "h3",
                "ush-inventory": "h4", "ush-processes": "h5", "ush-files": "h6",
                "ush-advice": "h7"}

H3_LINE = "- h3 ush-settings: ok."
W1_LINE = ("- w1: reguła ush-inventory x2 (Invented rule 2) dopuszcza port 8080; program "
           "słucha tylko na pętli zwrotnej (127.0.0.1), profil Private; sieci Private: 1.")


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
    """A temporary directory whose random name holds no digits."""
    for _ in range(500):
        tmp = tempfile.TemporaryDirectory(prefix="ush-runall-")
        if not re.search(r"\d", Path(tmp.name).resolve().name):
            return tmp
        tmp.cleanup()
    raise AssertionError("could not get a temporary directory name without digits")


# --- a hand-written runall summary (used by the shared number-word test) ---------------

GENERATED_AT = "2026-09-20T12:00:00+00:00"
CHILD_ROWS = (("h1", "ush-health"), ("h2", "ush-events"), ("h3", "ush-settings"),
              ("h4", "ush-inventory"), ("h5", "ush-processes"), ("h6", "ush-files"),
              ("h7", "ush-advice"))


def _child_summary_file(skill):
    stem = skill.removeprefix("ush-")
    return f"C:\\Invented\\ubershipshape\\work\\{stem}-2026-09-20-1200.summary.json"


def _w1_item():
    return {
        "id": "w1",
        "rule": "ush-inventory x2",
        "rule_name": "Invented Server",
        "program_path": "%ProgramFiles%\\Invented Server 7\\srv.exe",
        "lport": "8080",
        "protocol": 6,
        "profile": "Private",
        "app_exists": True,
        "listening": [{"port": "ush-processes p1", "local_address": "127.0.0.1",
                       "local_port": 8080, "scope": "loopback"}],
        "loopback_only": True,
    }


def _clean_summary(summary_file, detail_file):
    """Seven children ok, one firewall rule matched to a loopback port, nothing cut."""
    return {
        "schema_version": 1,
        "skill": SKILL,
        "generated_at": GENERATED_AT,
        "duration_s": 10.5,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "sources": [{"name": skill, "status": "read", "reason": None}
                    for _, skill in CHILD_ROWS],
        "children": [
            {"id": item_id, "skill": skill, "status": "ok", "exit_code": 0,
             "duration_s": 1.5, "summary_file": _child_summary_file(skill),
             "not_checked_count": 0, "truncated": 0,
             "elevated": None if skill == "ush-events" else False}
            for item_id, skill in CHILD_ROWS
        ],
        "counts": {"ok": 7},
        "firewall_ports": [_w1_item()],
        "firewall_ports_counts": {"inbound_rules": 9, "matched": 1, "not_listening": 2,
                                  "not_compared": 4, "udp": 2, "other_protocol": 0,
                                  "ports_without_path": 1},
        "network_categories": {"Private": 1},
        "truncated": 0,
        "not_checked": [],
    }


def _detail_data(summary):
    """The detail file of ``summary``: a minimal child summary per child, and the
    firewall_ports list."""
    children = []
    for child in summary["children"]:
        children.append({"id": child["id"], "summary": {
            "schema_version": 1, "skill": child["skill"], "generated_at": GENERATED_AT,
            "sources": [], "not_checked": [], "truncated": 0,
            "summary_file": child["summary_file"]}})
    return {"children": children, "firewall_ports": list(summary["firewall_ports"])}


# --- K6 and K7 ---------------------------------------------------------------------------

class TestReportProfile(RunallTestCase):
    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _digit_free_tempdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.reports = self.root / "reports"
        self.reports.mkdir()
        self._count = 0

    def temp(self):
        """A digit-free temporary directory, so no temp name backs a guarded number."""
        self._count += 1
        name, number = "", self._count
        while number:
            number, rest = divmod(number, 26)
            name += "abcdefghijklmnopqrstuvwxyz"[rest]
        path = self.root / f"tmp-{name}"
        path.mkdir()
        return path

    def _run(self, report):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(report)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def _write_report(self, lines, name):
        path = self.reports / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _assert_real_profile(self):
        profile = Path(self.check.SKILLS_DIR) / SKILL / "data" / "report-profile.json"
        self.assertTrue(profile.is_file(), f"the ush-runall report profile is missing: {profile}")

    def test_profile_keys(self):
        self._assert_real_profile()
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict, data)

        with self.subTest("path_keys"):
            path_keys = data.get("path_keys")
            self.assertIsInstance(path_keys, list, path_keys)
            self.assertEqual(sorted(path_keys),
                             sorted(["summary_file", "detail_file", "program_path"]))
            self.assertEqual(len(path_keys), 3, path_keys)

        with self.subTest("id_letters"):
            self.assertEqual(data.get("id_letters"), "hw")

        with self.subTest("id_keys"):
            self.assertIn("id_keys", data)
            self.assertEqual(data["id_keys"], [])

        with self.subTest("the checker loads it with exactly these skipped keys"):
            profile = self.check.load_profile(SKILL)
            self.assertEqual(profile.skip_keys, SKIP_KEYS)

    def _fake_children(self):
        """Fake children: invented summaries with the values K7 cites, a firewall rule x2
        matched to the loopback port p1."""
        outcomes = {
            "ush-health": ok(extra={"devices": [
                {"id": "p1", "name": f"Invented Audio {DEVICE_NUMBER}",
                 "problem": "CM_PROB_FAILED_START"}]}),
            "ush-events": ok(extra={"event_count": int(EVENTS_ONLY_NUMBER), "groups": [
                {"id": "r3", "provider": "Invented-Provider", "count": 4}]}),
            "ush-settings": ok(extra={"settings": [
                {"id": "e1", "name": "InventedSetting", "value": int(SETTING_VALUE)}]}),
            "ush-inventory": ok(extra={
                "counts": {"windows_services": int(NESTED_NUMBER)},
                "autostart": [{"id": "s11", "name": "InventedTray", "approved": True}]}),
            "ush-processes": ok(extra={"network_categories": {"Private": 1}}),
        }
        return FirewallChildren(
            self.temp(), outcomes,
            inventory=inventory_detail([rule(2, app=PROGRAM, profile="Private")]),
            processes=processes_detail(
                [group("g1", "srv.exe", PROGRAM_GROUP_PATH)],
                [port("p1", "127.0.0.1", 8080, "loopback", "g1", "srv.exe", 2100)]))

    def _report_lines(self, summary_file, drop=(), replace=None, extra=()):
        replace = replace or {}
        lines = [
            f"<!-- ush:summary {summary_file} -->",
            "# Raport zbiorczy",
            "",
            "<!-- ush:detail h1 h3 h4 -->",
            "",
            "## Stan przebiegu",
            "- h1 ush-health: ok.",
            "- h2 ush-events: ok.",
            H3_LINE,
            "- h4 ush-inventory: ok.",
            "- h5 ush-processes: ok.",
            "- h6 ush-files: ok.",
            "- h7 ush-advice: ok.",
            "",
            "## Ustalenia",
            f"- Urządzenie Invented Audio {DEVICE_NUMBER} (ush-health) zgłasza problem.",
            f"- Ustawienie e1 (ush-settings) ma wartość {SETTING_VALUE}.",
            f"- Usługi Windows według ush-inventory: {NESTED_NUMBER}.",
            "- Pozycja ush-inventory s11: wpis autostartu InventedTray.",
            "",
            "## Zapora wobec portów nasłuchu",
            W1_LINE,
            *extra,
            "",
            "## Nie sprawdzono",
            "<!-- ush:not-checked -->",
            "- nic.",
        ]
        return [replace.get(line, line) for line in lines if line not in drop]

    def test_nested_numbers(self):
        self._assert_real_profile()
        fake = self._fake_children()
        summary = self.collect(self.data_dir(), fake,
                               children=self.children_file(entries(TABLE)))
        summary_file = Path(str(summary.get("summary_file")))
        self.assertTrue(summary_file.is_absolute(), summary_file)
        on_disk = json.loads(summary_file.read_text(encoding="utf-8-sig"))
        detail = self.detail(summary)

        # Fixture guards: the ids the report relies on, and where each number lives.
        for skill, item_id in EXPECTED_IDS.items():
            self.assertEqual(self.child(summary, skill).get("id"), item_id, skill)
            self.assertEqual(self.child(summary, skill).get("status"), "ok", skill)
        self.assertEqual([item.get("id") for item in self.items(summary, "firewall_ports")],
                         ["w1"])
        items = {item_id: self.by_id(detail, item_id) for item_id in EXPECTED_IDS.values()}
        in_summary = _numbers(on_disk)
        named = in_summary | _numbers(items["h1"]) | _numbers(items["h3"]) \
            | _numbers(items["h4"])
        for number, item_id in ((DEVICE_NUMBER, "h1"), (SETTING_VALUE, "h3"),
                                (NESTED_NUMBER, "h4"), (EVENTS_ONLY_NUMBER, "h2")):
            self.assertNotIn(int(number), in_summary, f"{number} in the runall summary")
            self.assertIn(int(number), _numbers(items[item_id]), f"{number} not in {item_id}")
        self.assertNotIn(int(EVENTS_ONLY_NUMBER), named,
                         "the h2 number is backed elsewhere; the h2 case would prove nothing")
        everything = named.union(*(_numbers(item) for item in items.values()),
                                 *(_numbers(item) for item in detail.get("firewall_ports")
                                   or []))
        self.assertNotIn(int(INVENTED_NUMBER), everything)
        for number in (DEVICE_NUMBER, SETTING_VALUE, NESTED_NUMBER, EVENTS_ONLY_NUMBER,
                       INVENTED_NUMBER):
            self.assertNotIn(number, str(self.root), "temp path collides with the number")

        clean = self._report_lines(summary_file)

        with self.subTest("clean report with nested numbers of h1, h3 and h4 passes"):
            code, output = self._run(self._write_report(clean, "runall-2026-09-20-1200.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertTrue(any(line.startswith("OK:") for line in output.splitlines()),
                            f"output:\n{output}")

        with self.subTest("a number that is not in the JSON"):
            lines = self._report_lines(
                summary_file, extra=[f"- Sprawdzono {INVENTED_NUMBER} wpisów."])
            code, output = self._run(self._write_report(lines, "runall-invented.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn(INVENTED_NUMBER, output)

        with self.subTest("a number only in h2, which ush:detail does not name"):
            lines = self._report_lines(
                summary_file, extra=[f"- Zdarzeń według ush-events: {EVENTS_ONLY_NUMBER}."])
            code, output = self._run(self._write_report(lines, "runall-h2-number.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn(EVENTS_ONLY_NUMBER, output)

        with self.subTest("ush-events r3 does not name the item h3"):
            self.assertIn(H3_LINE, clean)
            lines = self._report_lines(summary_file,
                                       replace={H3_LINE: "- ush-events r3: grupa zdarzeń."})
            text_lines = [line for line in lines[1:] if not line.startswith("<!--")]
            self.assertFalse(any(re.search(r"\bh3\b", line) for line in text_lines))
            code, output = self._run(self._write_report(lines, "runall-r3.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn("not named in the report: h3", output)

        with self.subTest("the summary has w1 and the report does not name it"):
            self.assertIn(W1_LINE, clean)
            lines = self._report_lines(summary_file, drop=(W1_LINE,))
            self.assertFalse(any(re.search(r"\bw1\b", line) for line in lines[1:]))
            code, output = self._run(self._write_report(lines, "runall-no-w1.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn("not named in the report: w1", output)


if __name__ == "__main__":
    unittest.main()

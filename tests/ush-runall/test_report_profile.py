"""The ush-runall report profile, checked through the shared report checker (plan 098, M3).

The checker loads the real ``skills/ush-runall/data/report-profile.json`` through its
unpatched ``SKILLS_DIR``; no copy of the profile is used, and the checker is not changed.
The plan gives the profile: ``report_prefix`` ``runall-``, ``detail_sections``
children/firewall_ports, ``id_letters`` ``hw`` (``hwy`` since plan 028, M2; ``hjwy`` since plan 030, M2), ``required_lists`` children/firewall_ports,
``required_keys`` children/firewall_ports/firewall_ports_counts, ``truncated`` for
firewall_ports (w, count_key ``truncated``), ``id_keys`` ``[]`` and ``path_keys``
summary_file, detail_file, program_path.

K7 builds the summary and the detail file with ``runall.main`` and an injected fake
``run_child`` (M1/M2 helpers of ``test_runall.py`` and ``test_firewall_ports.py``); no
process is started and nothing on the machine is read.

Assumptions beyond the plan:

- With the plan's children table, the children get the ids ``h1`` (ush-health), ``h2``
  (ush-events), ``h3`` (ush-settings), ``h4`` (ush-inventory) ... ``h7`` (ush-advice), ``h8``
  (ush-packages);
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

from tests.report_summary import with_summary
from tests.skill_loader import REPO_ROOT, load_script

from .test_firewall_ports import (
    FirewallChildren,
    group,
    inventory_detail,
    port,
    processes_detail,
    rule,
)
from .test_runall import TABLE, FakeChildren, RunallTestCase, entries, ok

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
                "ush-advice": "h7", "ush-packages": "h8"}

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
              ("h7", "ush-advice"), ("h8", "ush-packages"))


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
    """Eight children ok, one firewall rule matched to a loopback port, nothing cut."""
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
        "counts": {"ok": 8},
        "firewall_ports": [_w1_item()],
        "firewall_ports_counts": {"inbound_rules": 9, "matched": 1, "not_listening": 2,
                                  "not_compared": 4, "udp": 2, "other_protocol": 0,
                                  "ports_without_path": 1},
        "network_categories": {"Private": 1},
        # Plan 028, M2: no pending driver update links to an orphan package.
        "driver_update_links": [],
        "link_counts": {"linked": 0, "updates_without_package": 0,
                        "packages_without_update": 0},
        # Plan 030, M2: no decisions file, so no decision to name.
        "decisions": [],
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
    return {"children": children, "firewall_ports": list(summary["firewall_ports"]),
            "driver_update_links": list(summary.get("driver_update_links") or []),
            "decisions": list(summary.get("decisions") or [])}


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

    def _write_report(self, lines, name, accepted=0):
        # accepted: the quiet accepted count of the summary runall.main writes
        # (no accepted.json: 0), on the summary's last line since plan 067, M2.
        path = self.reports / name
        path.write_text("\n".join(with_summary(lines, SKILL, accepted=accepted)) + "\n",
                        encoding="utf-8")
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
            # "a" since plan 060, M2 (accepted findings a1, a2, ...); "r" since plan 063,
            # M1 (review items r1, r2, ...).
            self.assertEqual(sorted(data.get("id_letters", "")), sorted("ahjrwy"))

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
            "- h8 ush-packages: ok.",
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

    # Plan 061, M2, K5: the runall summary of the repository's children.json, built by the
    # fake runner of test_eight_children, holds h8 (ush-packages); the report must name it.
    def test_h8_required(self):
        self._assert_real_profile()
        fake = FakeChildren(self.temp())
        summary = self.collect(self.data_dir(), fake)
        summary_file = Path(str(summary.get("summary_file")))
        self.assertTrue(summary_file.is_absolute(), summary_file)

        # Fixture guards: eight children, h8 is ush-packages, nothing else to name.
        ids = [c.get("id") for c in self.items(summary, "children")]
        self.assertEqual(ids, [f"h{n}" for n in range(1, 9)])
        self.assertEqual(self.by_id(summary, "h8").get("skill"), "ush-packages")
        for child in self.items(summary, "children"):
            self.assertEqual(child.get("status"), "ok", child)
        self.assertEqual(summary.get("not_checked"), [])

        h8_line = "- h8 ush-packages: ok."
        skills = [c.get("skill") for c in self.items(summary, "children")]

        def report(drop=()):
            lines = [
                f"<!-- ush:summary {summary_file} -->",
                "# Raport zbiorczy",
                "",
                "## Decyzje",
                "Brak decyzji do omówienia.",
                "",
                "## Stan przebiegu",
                *[f"- h{n} {skill}: ok." for n, skill in enumerate(skills, start=1)],
                "",
                "## Zalecenia",
                "Brak zaleceń w tym przebiegu.",
                "",
                "## Powiązania między skillami",
                "Brak powiązań między ustaleniami różnych skilli.",
                "",
                "## Zapora wobec portów nasłuchu",
                "Brak reguł zapory dopasowanych do portów nasłuchu.",
                "",
                "## Sprzeczne ustalenia",
                "Brak.",
                "",
                "## Nie sprawdzono",
                "<!-- ush:not-checked -->",
                "Nic.",
            ]
            return [line for line in lines if line not in drop]

        with self.subTest("control: h1 to h8 named"):
            lines = report()
            self.assertIn(h8_line, lines)
            code, output = self._run(self._write_report(lines, "runall-2026-09-20-1400.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertTrue(any(line.startswith("OK:") for line in output.splitlines()),
                            f"output:\n{output}")

        with self.subTest("h8 not named"):
            lines = report(drop=(h8_line,))
            self.assertFalse(any(re.search(r"\bh8\b", line) for line in lines[1:]))
            code, output = self._run(self._write_report(lines, "runall-2026-09-20-1401.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertIn("not named in the report: h8", output)


# --- plan 028, M2, K5 ----------------------------------------------------------------------

# A link of a pending driver update (ush-health q3) to an orphan driver package
# (ush-inventory o7). Field names as assumed in test_driver_update_links.py.
Y1_ITEM = {
    "id": "y1",
    "update": "ush-health q3",
    "package": "ush-inventory o7",
    "provider": "Contoso",
    "title": "Contoso - Display - Invented Update",
    "original_name": "contosodisplay.inf",
}
Y1_LINE = ("- y1: oczekująca aktualizacja sterownika ush-health q3 (Contoso) dotyczy pakietu "
           "ush-inventory o7 (contosodisplay.inf), którego nie używa żadne urządzenie.")


class TestDriverUpdateLinksProfile(unittest.TestCase):
    """A report that leaves out a listed ``y`` id fails the checker (plan 028, M2, K5).

    The summary and detail file are hand-written (``_clean_summary`` plus one link); the
    real ``skills/ush-runall/data/report-profile.json`` is used, which the plan gives
    ``y`` in ``id_letters`` and ``driver_update_links`` in ``required_lists``,
    ``required_keys`` and ``detail_sections``."""

    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _digit_free_tempdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.summary_file = self.work_dir / "runall-summary.json"
        self.detail_file = self.work_dir / "runall-detail.json"

    def _write_data(self):
        summary = _clean_summary(self.summary_file, self.detail_file)
        summary["driver_update_links"] = [dict(Y1_ITEM)]
        summary["link_counts"] = {"linked": 1, "updates_without_package": 0,
                                  "packages_without_update": 0}
        detail = _detail_data(summary)
        detail["driver_update_links"] = [dict(Y1_ITEM)]
        self.summary_file.write_text(json.dumps(summary), encoding="utf-8")
        self.detail_file.write_text(json.dumps(detail), encoding="utf-8")

    def _write_report(self, link_lines, name, accepted="not_checked"):
        lines = [
            f"<!-- ush:summary {self.summary_file} -->",
            "# Raport zbiorczy, 2026-09-20",
            "",
            "## Stan przebiegu",
            "- h1 ush-health: ok, 1.5 s.",
            "- h2 ush-events: ok, 1.5 s.",
            "- h3 ush-settings: ok, 1.5 s.",
            "- h4 ush-inventory: ok, 1.5 s.",
            "- h5 ush-processes: ok, 1.5 s.",
            "- h6 ush-files: ok, 1.5 s.",
            "- h7 ush-advice: ok, 1.5 s.",
            "- h8 ush-packages: ok, 1.5 s.",
            "- Cały przebieg trwał 10.5 s.",
            "",
            "## Zalecenia",
            "Brak zaleceń w tym przebiegu.",
            "",
            "## Powiązania między skillami",
            *(link_lines or ["Brak powiązań między ustaleniami różnych skilli."]),
            "",
            "## Zapora wobec portów nasłuchu",
            ("- w1: reguła ush-inventory x2 (Invented Server) dopuszcza port 8080; program "
             "słucha tylko na pętli zwrotnej (127.0.0.1), profil Private; sieci Private: 1."),
            ("- Pozostałe reguły przychodzące: bez nasłuchu 2, nieporównane 4, UDP 2, "
             "inny protokół 0."),
            "",
            "## Sprzeczne ustalenia",
            "Brak.",
            "",
            "## Nie sprawdzono",
            "<!-- ush:not-checked -->",
            "Nic.",
        ]
        path = self.reports_dir / name
        path.write_text("\n".join(with_summary(lines, SKILL, accepted=accepted)) + "\n",
                        encoding="utf-8")
        return path

    def _run(self, report_path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(report_path)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_link_must_be_named(self):
        self._write_data()

        with self.subTest("control: y1 named"):
            code, output = self._run(self._write_report([Y1_LINE],
                                                        "runall-2026-09-20-1200.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("y1 not named"):
            code, output = self._run(self._write_report([], "runall-2026-09-20-1201.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertIn("not named in the report: y1", output)


# --- plan 030, M2, K6 ----------------------------------------------------------------------

# A broken user decision (D1) with a ush-settings item as its evidence. Field names as in
# plan 030, M2: decision, state, evidence [{skill, id}], text, made, source, reason.
J1_ITEM = {
    "id": "j1",
    "decision": "D1",
    "state": "broken",
    "evidence": [{"skill": "ush-settings", "id": "e3"}],
    "text": "Invented: the privacy settings stay as they were set.",
    "made": "2026-10-31",
    "source": "invented repair plan",
    "reason": None,
}
J1_LINE = ("- j1: decyzja D1 złamana: ush-settings e3 znów ma dawną wartość. "
           "Niczego nie zmieniono.")


class TestDecisionsProfile(unittest.TestCase):
    """A report that leaves out a listed ``j`` id fails the checker (plan 030, M2, K6).

    The summary and detail file are hand-written (``_clean_summary`` plus one decision);
    the real ``skills/ush-runall/data/report-profile.json`` is used, which the plan gives
    ``j`` in ``id_letters`` and ``decisions`` in ``required_lists``, ``required_keys`` and
    ``detail_sections``."""

    def setUp(self):
        self.check = load_script("ush-common", "check_report")
        tmp = _digit_free_tempdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.summary_file = self.work_dir / "runall-summary.json"
        self.detail_file = self.work_dir / "runall-detail.json"

    def _write_data(self):
        summary = _clean_summary(self.summary_file, self.detail_file)
        summary["decisions"] = [json.loads(json.dumps(J1_ITEM))]
        detail = _detail_data(summary)
        detail["decisions"] = [json.loads(json.dumps(J1_ITEM))]
        self.summary_file.write_text(json.dumps(summary), encoding="utf-8")
        self.detail_file.write_text(json.dumps(detail), encoding="utf-8")

    def _write_report(self, decision_lines, name, accepted="not_checked"):
        lines = [
            f"<!-- ush:summary {self.summary_file} -->",
            "# Raport zbiorczy, 2026-09-20",
            "",
            "## Decyzje",
            *(decision_lines or ["Brak decyzji do omówienia."]),
            "",
            "## Stan przebiegu",
            "- h1 ush-health: ok, 1.5 s.",
            "- h2 ush-events: ok, 1.5 s.",
            "- h3 ush-settings: ok, 1.5 s.",
            "- h4 ush-inventory: ok, 1.5 s.",
            "- h5 ush-processes: ok, 1.5 s.",
            "- h6 ush-files: ok, 1.5 s.",
            "- h7 ush-advice: ok, 1.5 s.",
            "- h8 ush-packages: ok, 1.5 s.",
            "- Cały przebieg trwał 10.5 s.",
            "",
            "## Zalecenia",
            "Brak zaleceń w tym przebiegu.",
            "",
            "## Powiązania między skillami",
            "Brak powiązań między ustaleniami różnych skilli.",
            "",
            "## Zapora wobec portów nasłuchu",
            ("- w1: reguła ush-inventory x2 (Invented Server) dopuszcza port 8080; program "
             "słucha tylko na pętli zwrotnej (127.0.0.1), profil Private; sieci Private: 1."),
            ("- Pozostałe reguły przychodzące: bez nasłuchu 2, nieporównane 4, UDP 2, "
             "inny protokół 0."),
            "",
            "## Sprzeczne ustalenia",
            "Brak.",
            "",
            "## Nie sprawdzono",
            "<!-- ush:not-checked -->",
            "Nic.",
        ]
        path = self.reports_dir / name
        path.write_text("\n".join(with_summary(lines, SKILL, accepted=accepted)) + "\n",
                        encoding="utf-8")
        return path

    def _run(self, report_path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.check.main([str(report_path)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_decision_must_be_named(self):
        self._write_data()

        with self.subTest("control: j1 named"):
            code, output = self._run(self._write_report([J1_LINE],
                                                        "runall-2026-09-20-1200.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("j1 not named"):
            code, output = self._run(self._write_report([], "runall-2026-09-20-1201.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertNotIn("OK", output)
            self.assertIn("not named in the report: j1", output)


# --- plan 060, M2, K5 ----------------------------------------------------------------------

# An accepted update that failed again (back) and an accepted rule that is gone; ids a1, a2.
ACCEPTED_ITEMS = [
    {"id": "a1", "kind": "update", "key": ["Invented Cumulative Update", "0x80070005"],
     "state": "back",
     "changed": [{"field": "last", "accepted": "2026-09-01T08:00:00Z",
                  "now": "2026-09-19T08:00:00Z"}],
     "evidence": "ush-health u4", "accepted_on": "2026-09-02", "reason": None},
    {"id": "a2", "kind": "firewall_rule", "key": "fw:{invented-rule}", "state": "gone",
     "changed": [], "evidence": None, "accepted_on": "2026-09-03", "reason": None},
]
ACCEPTED_COUNTS = {"quiet": 0, "back": 1, "gone": 1, "not_checked": 0}


A1_LINE = "- a1: zaakceptowana aktualizacja znów zawiodła; wróciła."
A2_LINE = "- a2: zaakceptowanej reguły zapory już nie ma; można ją usunąć (--remove)."


class TestAcceptedProfile(TestDecisionsProfile):
    """A summary with ``accepted`` items and ``accepted_counts`` passes the runall
    profile with a report that names its ``back`` and ``gone`` items and gives the
    quiet count on the summary's last line (plan 060, M2, K5; format of plan 067, M2);
    an ``a`` item named in ``ush:detail`` backs its numbers."""

    def _write_data(self):
        super()._write_data()
        for path in (self.summary_file, self.detail_file):
            data = json.loads(path.read_text(encoding="utf-8"))
            data["accepted"] = json.loads(json.dumps(ACCEPTED_ITEMS))
            data["accepted_counts"] = dict(ACCEPTED_COUNTS)
            path.write_text(json.dumps(data), encoding="utf-8")

    def test_current_format_passes(self):
        self._write_data()
        with self.subTest("a1 and a2 named, no number of theirs"):
            code, output = self._run(self._write_report([J1_LINE, A1_LINE, A2_LINE],
                                                        "runall-2026-09-20-1300.md",
                                                        accepted=0))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("a1 named through ush:detail"):
            line = ("- a1: zaakceptowana aktualizacja znów zawiodła "
                    "(ostatnio 2026-09-19, zaakceptowana 2026-09-02).")
            path = self._write_report([J1_LINE, line, A2_LINE], "runall-2026-09-20-1301.md",
                                      accepted=0)
            text = path.read_text(encoding="utf-8").replace(
                "## Nie sprawdzono", "<!-- ush:detail a1 -->\n## Nie sprawdzono")
            path.write_text(text, encoding="utf-8")
            code, output = self._run(path)
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("control: an unbacked number fails"):
            line = "- a1: zaakceptowana aktualizacja zawiodła 4711 razy."
            code, output = self._run(self._write_report([J1_LINE, line, A2_LINE],
                                                        "runall-2026-09-20-1302.md",
                                                        accepted=0))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn("4711", output)

    test_decision_must_be_named = None


# --- plan 063, M1, K6 ----------------------------------------------------------------------

REVIEW_ITEMS = [
    {"id": "r1", "kind": "program", "key": "win32:hklm64:{invented-contoso-tool}",
     "name": "Contoso Tool", "state": "due", "decided_on": "2025-09-01", "period": "1y",
     "review_on": "2026-09-01", "reason": None},
    {"id": "r2", "kind": "package", "key": "npm:fabrikam-cli", "name": "fabrikam-cli",
     "state": "no_decision", "decided_on": None, "period": None, "review_on": None,
     "reason": None},
]
REVIEW_COUNTS = {"no_decision": 1, "due": 1, "not_due": 0, "no_limit": 0, "gone": 0,
                 "not_checked": 0}


class TestReviewProfile(TestDecisionsProfile):
    """A summary with ``review`` items, ``review_counts`` and ``truncated_review`` still
    passes the runall profile with a report in the current format, which names no ``r``
    item (plan 063, M1, K6); an ``r`` item named in ``ush:detail`` backs its numbers."""

    def _write_data(self):
        super()._write_data()
        for path in (self.summary_file, self.detail_file):
            data = json.loads(path.read_text(encoding="utf-8"))
            data["review"] = json.loads(json.dumps(REVIEW_ITEMS))
            data["review_counts"] = dict(REVIEW_COUNTS)
            data["truncated_review"] = 0
            path.write_text(json.dumps(data), encoding="utf-8")

    def test_current_format_passes(self):
        self._write_data()
        with self.subTest("no r item named"):
            code, output = self._run(self._write_report([J1_LINE],
                                                        "runall-2026-09-20-1400.md"))
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("r1 named through ush:detail"):
            line = "- r1: termin przeglądu minął 2026-09-01."
            path = self._write_report([J1_LINE, line], "runall-2026-09-20-1401.md")
            text = path.read_text(encoding="utf-8").replace(
                "## Nie sprawdzono", "<!-- ush:detail r1 -->\n## Nie sprawdzono")
            path.write_text(text, encoding="utf-8")
            code, output = self._run(path)
            self.assertEqual(code, 0, f"output:\n{output}")
            self.assertIn("OK", output)

        with self.subTest("control: an unbacked number fails"):
            line = "- r1: termin przeglądu minął 4711 dni temu."
            code, output = self._run(self._write_report([J1_LINE, line],
                                                        "runall-2026-09-20-1402.md"))
            self.assertEqual(code, 1, f"output:\n{output}")
            self.assertIn("4711", output)

    test_decision_must_be_named = None



# --- plan 061, M2, K4 ----------------------------------------------------------------------

RUNALL_DIR = REPO_ROOT / "skills" / SKILL
RUNALL_DOCS = ("SKILL.md", "references/report-format.md", "references/summary-contract.md")
# A range of h ids in the docs: `h1`...`h8`, `h1`…`h8`, `h1` to `h8`.
H_RANGE = re.compile(r"\bh1`?\s*(?:\.\.\.|…|to)\s*`?h(\d+)\b")
# SKILL.md is ASCII: it says the rule in English and the report format gives the Polish words.
NOT_CHECKED_FOR_UPDATES = {"SKILL.md": "not checked for updates",
                           "report-format.md": "nie sprawdzono pod kątem aktualizacji"}


def _flat(text):
    """``text`` with every run of white space as one space."""
    return " ".join(text.split())


def _section(text, heading):
    """The flat text from ``heading`` up to the next heading of the same or a higher level."""
    lines = text.splitlines()
    start = lines.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("#")
                and len(lines[i]) - len(lines[i].lstrip("#")) <= level), len(lines))
    return _flat("\n".join(lines[start:end]))


class TestDocsFollowChildren(unittest.TestCase):
    def test_docs_follow_children(self):
        children = json.loads((RUNALL_DIR / "data" / "children.json").read_text(
            encoding="utf-8"))
        skills = [child.get("skill") for child in children]
        self.assertIn("ush-packages", skills)
        texts = {name: (RUNALL_DIR / name).read_text(encoding="utf-8")
                 for name in RUNALL_DOCS}

        for name, text in texts.items():
            with self.subTest(f"{name}: no 'seven' and every h range ends at the last child"):
                self.assertIsNone(re.search(r"(?i)\bseven\b", text), name)
                ends = [int(n) for n in H_RANGE.findall(text)]
                self.assertTrue(ends, f"{name} names no h1...h<n> range")
                self.assertEqual(set(ends), {len(children)}, f"{name}: {ends}")

        skill_md = _flat(texts["SKILL.md"])
        report_format = texts["references/report-format.md"]
        flat_format = _flat(report_format)

        with self.subTest("the baselines the pass moves name ush-packages"):
            for name, flat in (("SKILL.md", skill_md), ("report-format.md", flat_format)):
                match = re.search(r"updated the baselines of the children \(([^)]*)\)", flat)
                self.assertIsNotNone(match, f"{name} has no list of moved baselines")
                self.assertIn("`ush-packages`", match.group(1), name)

        with self.subTest("the changes section names ush-packages"):
            section = _section(report_format, "### 6. Changes since the last run (Zmiany)")
            self.assertIn("ush-packages", section)
            match = re.search(r"\*\*The changes are summed up in this report\.\*\*(.*?)"
                              r"(?: - \*\*|$)", skill_md)
            self.assertIsNotNone(match, "SKILL.md has no rule on the changes")
            self.assertIn("ush-packages", match.group(1))
            # final-review: the cut change items of ush-packages are given as a number.
            self.assertIn("`truncated_changes`", _flat(section))
            self.assertIn("`truncated_changes`", match.group(1))

        with self.subTest("packages are not checked for updates; not_read is never absent"):
            for name, flat in (("SKILL.md", skill_md), ("report-format.md", flat_format)):
                self.assertIn(NOT_CHECKED_FOR_UPDATES[name], flat, name)
                # M2 code-review: said once for all packages, never per package.
                self.assertNotIn("every package", flat.casefold(), name)
                self.assertIn("once", flat.casefold(), name)
                rule = [sentence for sentence in re.split(r"(?<=\.) ", flat)
                        if "`not_read`" in sentence and "ush-packages" in sentence]
                self.assertTrue(rule, f"{name} has no rule on a not_read manager")
                self.assertTrue(any("not read yet" in s and "absent" in s for s in rule),
                                f"{name}: {rule}")


if __name__ == "__main__":
    unittest.main()

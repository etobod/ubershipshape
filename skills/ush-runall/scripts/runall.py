"""Run the measuring scripts of the ush-* skills one after another and summarise the run.

``data/children.json`` is an ordered list of ``{skill, script, timeout_s}``; ``script`` is a
bare file name resolved to ``<skills>/<skill>/scripts/<script>``. Each child gets exactly
``[python, -B, <script>, --data-dir, <data dir>]``: no other flag is ever passed on, so a
child runs read-only. ``logs.py`` and ``dumps.py`` (they change the disk or a log), the
skill ``ush-runall``, an unknown key, a script outside ``skills/``, a repeated skill and
``ush-processes`` before ``ush-inventory`` (processes reads the inventory baseline) make
the file unusable: exit 2 before any child runs.

Children run one at a time, through an injectable ``run_child(argv, timeout_s) ->
{returncode, stdout, stderr_tail, duration_s}``. The default starts the child with
``subprocess.Popen`` (no shell) and, on a timeout, stops its whole process tree before the
next child starts. A child's status:

- ``ok``: exit code 0 and stdout is a JSON object whose ``skill`` is the entry's skill;
- ``failed``: another exit code (with the last stderr line), or ``run_child`` raised;
- ``timeout``: the child did not finish within ``timeout_s``;
- ``bad_output``: exit code 0, but stdout is not such an object.

A status other than ``ok`` gives one ``not_checked`` entry and the run goes on.

The summary lists each child as an item ``h1``... in run order (status, exit code,
duration, its summary file, its ``not_checked`` count, ``truncated`` and ``elevated``);
the detail file holds each child's full summary under the same id (``null`` when the
status is not ``ok``). ``--detail h3`` prints one item of the newest detail file without
running anything; ``--detail-file`` names the file to read. Nothing is judged here.

After the children, ``firewall_ports`` compares the active inbound Allow firewall rules of
the ``ush-inventory`` detail file with the TCP listening ports of the ``ush-processes``
detail file (both named by the children's ``detail_file``): an item ``w...`` per rule
whose program listens on a port its lport covers, with counters for every other rule
(``udp``, ``other_protocol``, ``not_compared``, ``not_listening``) and
``network_categories`` copied from the ``ush-processes`` summary. The summary lists at
most ``FIREWALL_PORTS_MAX`` items and counts the rest in ``truncated``; the detail file
holds them all. When a child is not ``ok``, its detail file cannot be read or the source
``firewall_rules`` / ``tcp_listeners`` was not read, the list and the counters are null
and ``not_checked`` says why.

``driver_update_links`` links a pending driver update of the ``ush-health`` detail file
(``pending_updates``, type ``driver``) to a driver package of the ``ush-inventory`` detail
file that no present device uses (``driver_packages``, ``device_state`` ``non_present`` or
``no_device_found``; never ``present`` or null) when their providers and driver classes
are equal after case-folding or paired by ``data/driver-link-aliases.json``: an item
``y...`` per pair, naming both ids, both sides' provider and class, per side whether equal
names or a table line matched them, and the package's state, group and
``no_device_by_nature``, with ``link_counts``. When either list or the inventory source ``devices`` (the source of the package states) was not read, both
are null and ``not_checked`` names the side.

``decisions`` checks the user's decisions of ``<data dir>/decisions.json`` (read by the
shared ``decisions`` module, its setting checks validated against the settings
catalogue) against the child detail files of this pass: an item ``j...`` per decision with
``decision``, ``state`` (``kept``, ``broken`` or ``not_checked``), ``evidence`` (a list of
``{skill, id}``), ``reason``, ``text``, ``made`` and ``source``. A ``setting`` check reads the
``ush-settings`` item of its catalogue entry: ``matches`` is kept, ``differs`` broken, any
other state not checked. A ``vendor_absent`` check compares its exact name, case-folded,
with the inventory ``programs`` publishers, the driver ``provider`` of the inventory
``driver_packages`` and ``drivers`` and of the ``ush-health`` ``pending_updates``, or the
``name`` of every inventory ``vendor_folders`` item; a source not read in this run, or a
list that is null or missing, makes it not checked. A decision is broken when a check is
broken, kept only when every check was made and kept; a broken item's ``evidence``
holds only the items of its broken checks. No file gives ``[]``; a file that
cannot be used gives ``null`` and one ``not_checked`` entry.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import accepted as accepted_file
import datadir
import decisions as decisions_file
from baseline import parse_utc
from psrun import dump

SKILL = "ush-runall"
SCHEMA_VERSION = 1
SKILLS_DIR = Path(__file__).resolve().parents[2]
CHILDREN_FILE = SKILLS_DIR / "ush-runall" / "data" / "children.json"
# Explicit pairs of Windows Update and INF names for the driver update links (D-05).
ALIASES_FILE = SKILLS_DIR / "ush-runall" / "data" / "driver-link-aliases.json"
CHILD_KEYS = ("skill", "script", "timeout_s")
SKILL_NAME = re.compile(r"ush-[a-z]+")  # as check_report.check_skill_name, fullmatch
FORBIDDEN_SCRIPTS = ("logs.py", "dumps.py")  # they change the disk or a log
# A plain lower-case name: Windows drops a trailing dot or space and opens a stream
# suffix, so "logs.py." would otherwise slip past FORBIDDEN_SCRIPTS and run logs.py.
SCRIPT_NAME = re.compile(r"[a-z_]+\.py")
# A child that reads the baseline of another must run after it: (earlier, later).
ORDER_RULES = (("ush-inventory", "ush-processes"),)
DETAIL_SECTIONS = ("children", "firewall_ports", "driver_update_links", "decisions",
                   "accepted")
ACCEPTED_STATES = ("quiet", "back", "gone", "not_checked")
SKILL_HEALTH = "ush-health"
SKILL_INVENTORY = "ush-inventory"
SKILL_PROCESSES = "ush-processes"
SKILL_SETTINGS = "ush-settings"
CATALOGUE_FILE = SKILLS_DIR / SKILL_SETTINGS / "data" / "settings-catalogue.json"
# vendor_absent match -> ((skill, source, detail section, field compared), ...)
VENDOR_LISTS = {
    "publisher": ((SKILL_INVENTORY, "win32_programs", "programs", "publisher"),
                  (SKILL_INVENTORY, "msix_programs", "programs", "publisher")),
    "provider": ((SKILL_INVENTORY, "driver_packages", "driver_packages", "provider"),
                 (SKILL_INVENTORY, "drivers", "drivers", "provider"),
                 (SKILL_HEALTH, "pending_updates", "pending_updates", "driver_provider")),
    "folder": ((SKILL_INVENTORY, "vendor_folders", "vendor_folders", "name"),),
}
# (skill, source that must be read, detail sections the comparison needs)
FIREWALL_INPUTS = ((SKILL_INVENTORY, "firewall_rules", ("additions",)),
                   (SKILL_PROCESSES, "tcp_listeners", ("groups", "ports")))
READ_STATUSES = ("read", "empty")
FIREWALL_PORTS_MAX = 50  # summary items; the rest is counted in truncated
STATUSES = ("ok", "failed", "timeout", "bad_output")
STDERR_TAIL_CHARS = 2000
REASON_MAX = 300
KILL_TIMEOUT_S = 60  # taskkill itself
REAP_TIMEOUT_S = 30  # reading what is left of a killed child's pipes
TIMEOUT_MAX_S = 86400  # one day; a larger timeout_s in children.json is not usable


class ChildrenError(Exception):
    """children.json cannot be used; nothing may run."""


def error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:REASON_MAX]


# --- children.json ----------------------------------------------------------------------
def script_path(child: dict) -> Path:
    """The absolute path of a child's script under ``SKILLS_DIR``."""
    return (SKILLS_DIR / child["skill"] / "scripts" / child["script"]).resolve()


def check_child(child, position: int) -> dict:
    where = f"entry {position}"
    if not isinstance(child, dict):
        raise ChildrenError(f"{where} is not an object")
    unknown = sorted(set(child) - set(CHILD_KEYS))
    if unknown:
        raise ChildrenError(f"{where} has keys other than {', '.join(CHILD_KEYS)}: "
                            f"{', '.join(unknown)}")
    missing = [key for key in CHILD_KEYS if key not in child]
    if missing:
        raise ChildrenError(f"{where} misses {', '.join(missing)}")
    skill, script, timeout_s = child["skill"], child["script"], child["timeout_s"]
    if not isinstance(skill, str) or not SKILL_NAME.fullmatch(skill):
        raise ChildrenError(f"{where}: skill {skill!r} is not of the form ush-<letters>")
    if skill == SKILL:
        raise ChildrenError(f"{where}: {SKILL} cannot run itself")
    if not isinstance(script, str) or not script.strip():
        raise ChildrenError(f"{where}: script {script!r} is not a file name")
    if "/" in script or "\\" in script or ".." in script:
        raise ChildrenError(f"{where}: script {script!r} must be a bare file name")
    if not SCRIPT_NAME.fullmatch(script):
        raise ChildrenError(f"{where}: script {script!r} is not of the form <letters>.py")
    if script.lower() in FORBIDDEN_SCRIPTS:
        raise ChildrenError(f"{where}: {script} changes the machine and is never run here")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s <= 0:
        raise ChildrenError(f"{where}: timeout_s {timeout_s!r} is not a positive integer")
    if timeout_s > TIMEOUT_MAX_S:
        raise ChildrenError(f"{where}: timeout_s {timeout_s} is over the limit of "
                            f"{TIMEOUT_MAX_S} s")
    if not script_path(child).is_relative_to(SKILLS_DIR.resolve()):
        raise ChildrenError(f"{where}: script {script!r} resolves outside {SKILLS_DIR}")
    return {"skill": skill, "script": script, "timeout_s": timeout_s}


def load_children(path: Path) -> list:
    """The checked list of children; ChildrenError when the file cannot be used."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ChildrenError(f"{path} could not be read: {error_text(exc)}") from None
    if not isinstance(data, list) or not data:
        raise ChildrenError(f"{path} is not a non-empty list")
    children = [check_child(child, n) for n, child in enumerate(data, 1)]
    skills = [child["skill"] for child in children]
    repeated = sorted({skill for skill in skills if skills.count(skill) > 1})
    if repeated:
        raise ChildrenError(f"skills listed more than once: {', '.join(repeated)}")
    for earlier, later in ORDER_RULES:
        if earlier in skills and later in skills and skills.index(later) < skills.index(earlier):
            raise ChildrenError(f"{later} must run after {earlier}, whose baseline it reads")
    return children


def child_argv(child: dict, data_dir) -> list:
    """The only command line a child gets: the interpreter, -B, its script, the data dir."""
    return [sys.executable, "-B", str(script_path(child)), "--data-dir", str(data_dir)]


# --- running a child --------------------------------------------------------------------
def kill_tree(pid: int) -> bool:
    """Stop a process and every process it started (PowerShell jobs of a child). True
    only when taskkill reports success; a failure is not hidden behind proc.kill()."""
    try:
        done = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                              stdin=subprocess.DEVNULL, capture_output=True, check=False,
                              timeout=KILL_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return False  # proc.kill() below still stops the child itself
    return getattr(done, "returncode", None) == 0


def default_run_child(argv: list, timeout_s: int) -> dict:
    """Run one child without a shell; raise TimeoutExpired after stopping its tree. The
    raised exception carries ``tree_stopped``: True only when taskkill succeeded and the
    child's pipes closed, so nothing it started can still be running. Any other exception
    while waiting (an interrupt, an overflow) stops the tree the same way and is raised
    again unchanged."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.monotonic()
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                            env=env, shell=False)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        # The child is still alive, so its tree (with PowerShell) can still be found.
        tree_killed = kill_tree(proc.pid) is True
        proc.kill()
        try:
            proc.communicate(timeout=REAP_TIMEOUT_S)
            reaped = True
        except subprocess.TimeoutExpired:
            reaped = False  # something it started still holds the pipes
        exc.tree_stopped = tree_killed and reaped
        raise
    except BaseException:
        # Waiting failed for another reason; the child must not outlive the run.
        kill_tree(proc.pid)
        proc.kill()
        try:
            proc.communicate(timeout=REAP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            pass  # the original exception below says what went wrong
        raise
    return {"returncode": proc.returncode, "stdout": stdout or "",
            "stderr_tail": (stderr or "")[-STDERR_TAIL_CHARS:],
            "duration_s": round(time.monotonic() - started, 1)}


def last_line(text) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-1][:REASON_MAX] if lines else ""


def run_one(run_child, child: dict, data_dir: Path) -> dict:
    """Run one child and classify the result: {status, exit_code, duration_s, summary,
    reason}. Nothing a child does stops the run."""
    skill, script, timeout_s = child["skill"], child["script"], child["timeout_s"]
    started = time.monotonic()
    outcome = {"status": None, "exit_code": None, "duration_s": None, "summary": None,
               "reason": None}

    def measured():
        return round(time.monotonic() - started, 1)

    try:
        result = run_child(child_argv(child, data_dir), timeout_s)
    except subprocess.TimeoutExpired as exc:
        if getattr(exc, "tree_stopped", None) is True:
            stopped = "was stopped with the processes it started"
        else:
            stopped = ("was stopped, but stopping the processes it started was not "
                       "confirmed; one of them may still be running")
        outcome.update(status="timeout", duration_s=measured(),
                       reason=f"{script} did not finish within {timeout_s} s and {stopped}")
        return outcome
    except Exception as exc:  # noqa: BLE001 - any failure is this child's status, not the run's
        outcome.update(status="failed", duration_s=measured(),
                       reason=f"{script} could not be run: {error_text(exc)}")
        return outcome

    result = result if isinstance(result, dict) else {}
    duration = result.get("duration_s")
    valid_duration = isinstance(duration, (int, float)) and not isinstance(duration, bool)
    outcome["duration_s"] = round(duration, 1) if valid_duration else measured()
    code = result.get("returncode")
    outcome["exit_code"] = code
    if code != 0:
        line = last_line(result.get("stderr_tail"))
        outcome.update(status="failed",
                       reason=f"{script} exited with code {code}; last error line: "
                              f"{line or 'none'}")
        return outcome
    try:
        summary = json.loads(str(result.get("stdout") or ""))
    except ValueError as exc:
        outcome.update(status="bad_output",
                       reason=f"{script} exited 0, but its output is not JSON: "
                              f"{error_text(exc)}")
        return outcome
    if not isinstance(summary, dict):
        outcome.update(status="bad_output",
                       reason=f"{script} exited 0, but its output is not a JSON object")
        return outcome
    if summary.get("skill") != skill:
        named = str(summary.get("skill"))[:REASON_MAX]
        outcome.update(status="bad_output",
                       reason=f"{script} exited 0, but its summary names skill {named!r}, "
                              f"not {skill}")
        return outcome
    outcome.update(status="ok", summary=summary)
    return outcome


def child_item(item_id: str, child: dict, outcome: dict) -> dict:
    """The summary item of one child: its own values, never its summary."""
    summary = outcome["summary"] or {}
    notes = summary.get("not_checked")
    return {
        "id": item_id,
        "skill": child["skill"],
        "status": outcome["status"],
        "exit_code": outcome["exit_code"],
        "duration_s": outcome["duration_s"],
        "summary_file": summary.get("summary_file"),
        "not_checked_count": len(notes) if isinstance(notes, list) else None,
        "truncated": summary.get("truncated"),
        "elevated": summary.get("elevated"),
    }


# --- firewall rules against listening ports ---------------------------------------------
def int_text(value: str):
    """A non-negative decimal integer written as text, else None."""
    value = value.strip()
    return int(value) if value.isascii() and value.isdigit() else None


def port_test(value):
    """One lport element as a test ``local_port -> bool``; None when it is not ``*``, a
    number or a range ``a-b`` (a keyword such as RPC, or not text)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value == "*":
        return lambda port: True
    number = int_text(value)
    if number is not None:
        return lambda port: port == number
    low, sep, high = value.partition("-")
    if sep:
        low, high = int_text(low), int_text(high)
        if low is not None and high is not None:
            return lambda port: low <= port <= high
    return None


def lport_tests(lport):
    """The tests of a rule's lport (null means any port); None when any element cannot
    be read as ``*``, a number or a range."""
    if lport is None:
        return [lambda port: True]
    values = lport if isinstance(lport, list) else [lport]
    tests = [port_test(value) for value in values]
    if not tests or any(test is None for test in tests):
        return None
    return tests


def rule_order(rule_id) -> tuple:
    """The sort key of an ``x...`` id: by the number after ``x``."""
    text = str(rule_id)
    number = int_text(text[1:]) if text.startswith("x") else None
    return (0, number, text) if number is not None else (1, 0, text)


def firewall_ports(inventory_detail: dict, processes_detail: dict,
                   processes_summary: dict) -> dict:
    """The active inbound Allow rules against the TCP listening ports, without the machine.

    ``{firewall_ports, firewall_ports_counts, network_categories}``: one item per
    matched rule (id ``w...``, in the order of the number after ``x``), the full list
    without any limit. Each active inbound Allow rule lands in exactly one counter,
    checked in this order: ``udp``, ``other_protocol``, ``not_compared``, then
    ``matched`` or ``not_listening``. A rule is matched when
    ``normcase(expandvars(app))`` is the path of a port's group and its lport covers the
    port. A rule with a non-empty ``lport2`` (its ``LPort2_*`` keys) is not compared.
    Environment variables are expanded with this process's environment. Facts only;
    nothing is judged.
    """
    paths = {group.get("id"): group.get("path")
             for group in processes_detail.get("groups") or [] if isinstance(group, dict)}
    ports, without_path = [], 0
    for port in processes_detail.get("ports") or []:
        if not isinstance(port, dict):
            continue
        path = paths.get(port.get("group")) if port.get("group") is not None else None
        if not isinstance(path, str) or not path:
            without_path += 1
            continue
        local_port = port.get("local_port")
        if isinstance(local_port, int) and not isinstance(local_port, bool):
            ports.append((os.path.normcase(path), port))

    counts = {"inbound_rules": 0, "matched": 0, "not_listening": 0, "not_compared": 0,
              "udp": 0, "other_protocol": 0, "ports_without_path": without_path}
    matched = []
    for rule in inventory_detail.get("additions") or []:
        if not isinstance(rule, dict) or rule.get("kind") != "firewall_rule":
            continue
        active = rule.get("active")
        if (rule.get("dir") != "In" or rule.get("action") != "Allow"
                or not isinstance(active, str) or active.upper() != "TRUE"):
            continue
        counts["inbound_rules"] += 1
        protocol = rule.get("protocol")
        if protocol == 17 and not isinstance(protocol, bool):
            counts["udp"] += 1
            continue
        if protocol is not None and (isinstance(protocol, bool) or protocol != 6):
            counts["other_protocol"] += 1
            continue
        app = rule.get("app")
        program = os.path.expandvars(app) if isinstance(app, str) else ""
        tests = lport_tests(rule.get("lport"))
        # LPort2_* keys hold ports or keywords this comparison does not read, so lport
        # alone would not say which ports the rule opens.
        lport2 = rule.get("lport2")
        has_lport2 = lport2 is not None and lport2 != []
        # "System" names the kernel, which has no image file: no group path can match it.
        if (not program.strip() or "%" in program or rule.get("svc") or tests is None
                or has_lport2 or program.strip().lower() == "system"):
            counts["not_compared"] += 1
            continue
        program_key = os.path.normcase(program)
        listening = [port for path, port in ports
                     if path == program_key
                     and any(test(port["local_port"]) for test in tests)]
        if not listening:
            counts["not_listening"] += 1
            continue
        counts["matched"] += 1
        matched.append((rule_order(rule.get("id")), {
            "rule": f"{SKILL_INVENTORY} {rule.get('id')}",
            "rule_name": rule.get("name"),
            "program_path": program,
            "lport": rule.get("lport"),
            "protocol": protocol,
            "profile": rule.get("profile"),
            "app_exists": rule.get("app_exists"),
            "listening": [{"port": f"{SKILL_PROCESSES} {port.get('id')}",
                           "local_address": port.get("local_address"),
                           "local_port": port.get("local_port"),
                           "scope": port.get("scope")} for port in listening],
            "loopback_only": all(port.get("scope") == "loopback" for port in listening),
        }))
    matched.sort(key=lambda pair: pair[0])
    items = [{"id": f"w{n}", **item} for n, (_, item) in enumerate(matched, 1)]
    return {"firewall_ports": items, "firewall_ports_counts": counts,
            "network_categories": (processes_summary or {}).get("network_categories")}


def read_child_detail(skill: str, outcome, source, sections: tuple):
    """``(detail, None)`` of an ok child whose ``source`` was read, or ``(None, reason)``.
    ``source`` is a source name, an object of fields a source must have (``{"log":
    "System", "pass": "A"}``), or ``None``/``{}`` when no source is required."""
    if outcome is None:
        return None, f"{skill} is not in children.json"
    if outcome["status"] != "ok":
        return None, f"{skill} gave no summary (status {outcome['status']})"
    path = outcome["summary"].get("detail_file")
    if not isinstance(path, str) or not path:
        return None, f"the {skill} summary names no detail_file"
    try:
        detail = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"the {skill} detail file could not be read: {error_text(exc)}"
    if not isinstance(detail, dict):
        return None, f"the {skill} detail file does not hold an object"
    want = {"name": source} if isinstance(source, str) else dict(source or {})
    label = source if isinstance(source, str) else ", ".join(
        f"{field} {value}" for field, value in want.items())
    entries = [entry for entry in detail.get("sources") or [] if want
               and isinstance(entry, dict)
               and all(entry.get(field) == value for field, value in want.items())]
    if want and not entries:
        return None, f"source {label} is not in the {skill} detail file"
    for entry in entries:
        if entry.get("status") not in READ_STATUSES:
            why = str(entry.get("reason") or "no reason given")[:REASON_MAX]
            return None, f"source {label} of {skill} is {entry.get('status')}: {why}"
    missing = [name for name in sections if not isinstance(detail.get(name), list)]
    if missing:
        return None, f"the {skill} detail file has no list {', '.join(missing)}"
    return detail, None


def unread_path_ports(processes_detail: dict) -> int:
    """Listening ports whose program path is unknown: their group has an image file
    whose path could not be read, or the port has no group of the detail file (the
    process list was not read, or the process started after it was read)."""
    groups = [group for group in processes_detail.get("groups") or []
              if isinstance(group, dict)]
    known = {group.get("id") for group in groups}
    unread = {group.get("id") for group in groups
              if group.get("path") is None and group.get("path_kind") == "file"}
    return sum(1 for port in processes_detail.get("ports") or []
               if isinstance(port, dict)
               and (port.get("group") in unread or port.get("group") not in known))


def unreadable_rules(inventory_detail: dict) -> int:
    """Firewall rules of the inventory detail whose text could not be read or whose
    direction, action or state is no single value: none of them is counted."""
    count = 0
    for rule in inventory_detail.get("additions") or []:
        if not isinstance(rule, dict) or rule.get("kind") != "firewall_rule":
            continue
        unread = rule.get("unread_fields")
        if ((isinstance(unread, list) and "rule" in unread)
                or any(not isinstance(rule.get(key), (str, type(None)))
                       for key in ("dir", "action", "active"))):
            count += 1
    return count


def compare_firewall(outcomes: dict) -> tuple:
    """``(result, notes)``: the firewall comparison of the run and its not_checked
    entries; when an input is missing, null ``firewall_ports`` and counts and one
    entry naming why."""
    processes = outcomes.get(SKILL_PROCESSES)
    processes_summary = (processes["summary"] if processes and processes["status"] == "ok"
                         else {})
    details, reasons = [], []
    for skill, source, sections in FIREWALL_INPUTS:
        detail, reason = read_child_detail(skill, outcomes.get(skill), source, sections)
        details.append(detail)
        if reason is not None:
            reasons.append(reason)
    if reasons:
        result = {"firewall_ports": None, "firewall_ports_counts": None,
                  "network_categories": processes_summary.get("network_categories")}
        note = {"what": f"firewall rules against listening ports (firewall_rules of "
                        f"{SKILL_INVENTORY}, tcp_listeners of {SKILL_PROCESSES})",
                "reason": "; ".join(reasons) + "; the comparison was not made"}
        return result, [note]
    result = firewall_ports(details[0], details[1], processes_summary)
    counts = result["firewall_ports_counts"]
    notes = []
    unreadable = unreadable_rules(details[0])
    if unreadable:
        notes.append({"what": f"firewall rules that could not be read (firewall_rules of "
                              f"{SKILL_INVENTORY})",
                      "reason": f"{unreadable} firewall rules could not be read and are "
                                f"in no count of firewall_ports_counts"})
    unread = unread_path_ports(details[1])
    if unread and counts["not_listening"]:
        # A port whose program path is unknown was never compared, so a rule counted
        # not_listening may belong to its program: say so instead of hiding it.
        # A process without an image file (System, path_kind "none") is not unread.
        notes.append({
            "what": f"programs of the listening ports without a path (tcp_listeners of "
                    f"{SKILL_PROCESSES})",
            "reason": f"{unread} listening ports have a program path that could not be "
                      f"read or no known process; the {counts['not_listening']} rules "
                      f"counted not_listening were not compared with them and may belong "
                      f"to one of them"})
    return result, notes


def read_link_aliases() -> tuple:
    """``(classes, groups, reason)`` of the alias table ``ALIASES_FILE``: ``classes`` maps a
    case-folded Windows Update class to the set of case-folded INF classes it stands for,
    ``groups`` a case-folded provider name to the number of its group. When the file cannot
    be read or has a wrong shape, both are empty and ``reason`` says why."""
    try:
        data = json.loads(ALIASES_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}, {}, "the file is missing"
    except (OSError, UnicodeDecodeError) as error:
        return {}, {}, f"the file could not be read: {error}"
    except json.JSONDecodeError as error:
        return {}, {}, f"the file is not JSON: {error}"

    def names(value):
        return (isinstance(value, list) and bool(value)
                and all(isinstance(name, str) and name.strip() for name in value))

    if not (isinstance(data, dict) and isinstance(data.get("classes"), list)
            and isinstance(data.get("providers"), list)):
        return {}, {}, "classes and providers must be lists"
    classes, groups = {}, {}
    for line in data["classes"]:
        update_class = line.get("windows_update") if isinstance(line, dict) else None
        if not (isinstance(update_class, str) and update_class.strip()
                and names(line.get("inf"))):
            return {}, {}, ("every classes line needs a windows_update name and an inf "
                            "list of names")
        key = update_class.casefold()
        if key in classes:
            return {}, {}, f"the class {update_class!r} appears twice"
        classes[key] = {name.casefold() for name in line["inf"]}
    for number, line in enumerate(data["providers"]):
        members = line.get("names") if isinstance(line, dict) else None
        if not (names(members) and len(members) >= 2):
            return {}, {}, "every providers group needs a list of at least two names"
        for name in members:
            key = name.casefold()
            if groups.get(key, number) != number:
                return {}, {}, f"the provider {name!r} is in two groups"
            groups[key] = number
    return classes, groups, None


# The device states of an ush-inventory driver package that no present device uses; a
# package in another state (present, or null when not judged) is never linked.
LINKED_PACKAGE_STATES = ("non_present", "no_device_found")


def link_driver_updates(outcomes: dict) -> tuple:
    """``(result, notes)``: one item ``y...`` per pair of a pending driver update of
    ``ush-health`` and a driver package of ``ush-inventory`` whose ``device_state`` is
    ``non_present`` or ``no_device_found`` (never ``present`` or null), whose providers are equal after case-folding or in one group of ``ALIASES_FILE``, and
    whose driver classes are equal after case-folding or the package's class is listed for
    the update's class there (an update or package without either is linked to nothing),
    and ``link_counts``. Each item names both sides' provider and class and, in
    ``provider_via`` and ``class_via``, how that side matched: ``equal`` or ``table``; and
    the package's ``device_state``, ``group`` and ``no_device_by_nature`` as
    ``package_state``, ``package_group`` and ``package_no_device_by_nature``.
    When a side was not read, both are null and one not_checked entry
    names why; when the table cannot be used, only equal names link and one entry says so."""
    inputs = ((SKILL_HEALTH, "pending_updates", ("pending_updates",)),
              (SKILL_INVENTORY, "driver_packages", ("driver_packages",)),
              (SKILL_INVENTORY, "devices", ()))
    details, reasons = [], []
    for skill, source, sections in inputs:
        detail, reason = read_child_detail(skill, outcomes.get(skill), source, sections)
        details.append(detail)
        if reason is not None:
            reasons.append(reason)
    if reasons:
        note = {"what": f"driver update links (pending_updates of {SKILL_HEALTH}, "
                        f"driver_packages and devices of {SKILL_INVENTORY})",
                "reason": "; ".join(reasons) + "; the updates were not linked"}
        return {"driver_update_links": None, "link_counts": None}, [note]
    updates = [item for item in details[0]["pending_updates"]
               if isinstance(item, dict) and item.get("type") == "driver"]
    packages = [item for item in details[1]["driver_packages"]
                if isinstance(item, dict)
                and item.get("device_state") in LINKED_PACKAGE_STATES]
    classes, groups, reason = read_link_aliases()
    notes = []
    if reason is not None:
        notes.append({"what": f"driver link alias table ({ALIASES_FILE.name})",
                      "reason": f"{reason}; only equal provider and class names were "
                                f"linked"})

    def provider_match(first, second):
        """``"equal"``, ``"table"`` or None: how two provider names match."""
        first, second = first.casefold(), second.casefold()
        if first == second:
            return "equal"
        if first in groups and groups[first] == groups.get(second):
            return "table"
        return None

    def class_match(update_class, package_class):
        """``"equal"``, ``"table"`` or None: how an update's class matches a package's."""
        update_class, package_class = update_class.casefold(), package_class.casefold()
        if update_class == package_class:
            return "equal"
        if package_class in classes.get(update_class, ()):
            return "table"
        return None

    links, linked_updates, linked_packages = [], set(), set()
    for u, update in enumerate(updates):
        provider, cls = update.get("driver_provider"), update.get("driver_class")
        if not isinstance(provider, str):
            continue
        for p, package in enumerate(packages):
            other, other_cls = package.get("provider"), package.get("class")
            if not (isinstance(other, str) and isinstance(cls, str)
                    and isinstance(other_cls, str)):
                continue
            provider_via = provider_match(provider, other)
            class_via = class_match(cls, other_cls)
            if provider_via is None or class_via is None:
                continue
            links.append({"id": f"y{len(links) + 1}",
                          "update": f"{SKILL_HEALTH} {update.get('id')}",
                          "package": f"{SKILL_INVENTORY} {package.get('id')}",
                          "provider": provider, "driver_class": cls,
                          "package_provider": other, "package_class": other_cls,
                          "provider_via": provider_via, "class_via": class_via,
                          "title": update.get("title"),
                          "original_name": package.get("original_name"),
                          "package_state": package.get("device_state"),
                          "package_group": package.get("group"),
                          "package_no_device_by_nature":
                              package.get("no_device_by_nature")})
            linked_updates.add(u)
            linked_packages.add(p)
    counts = {"linked": len(links),
              "updates_without_package": len(updates) - len(linked_updates),
              "packages_without_update": len(packages) - len(linked_packages)}
    return {"driver_update_links": links, "link_counts": counts}, notes


# --- the user's decisions ---------------------------------------------------------------
def catalogue_expectations():
    """``{entry id: expected}`` of the settings catalogue, or None when it cannot be read
    (the setting checks are then measured only against the ``ush-settings`` items)."""
    try:
        data = json.loads(CATALOGUE_FILE.read_text(encoding="utf-8-sig"))
        return {entry["id"]: entry.get("expected") for entry in data["entries"]}
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError):
        return None


def check_setting(check: dict, outcomes: dict) -> tuple:
    """``(state, evidence, reason)`` of one ``setting`` check."""
    detail, reason = read_child_detail(SKILL_SETTINGS, outcomes.get(SKILL_SETTINGS), None,
                                       ("settings",))
    if reason is not None:
        return "not_checked", [], reason
    items = [item for item in detail["settings"]
             if isinstance(item, dict) and item.get("entry") == check["item"]]
    if not items:
        return "not_checked", [], f"no {SKILL_SETTINGS} item for {check['item']}"
    item = items[0]
    evidence = [{"skill": SKILL_SETTINGS, "id": item.get("id")}]
    if item.get("expected") != check["expected"]:
        return "not_checked", evidence, (
            f"{SKILL_SETTINGS} {item.get('id')} was measured against "
            f"{item.get('expected')!r}, not the decision's {check['expected']!r}")
    state = item.get("state")
    if state == "matches":
        return "kept", evidence, None
    if state == "differs":
        return "broken", evidence, None
    return "not_checked", evidence, f"{SKILL_SETTINGS} {item.get('id')} is {state}"


def unread_roots(detail: dict):
    """The reason no folder check can be made from ``vendor_folder_roots``, or None."""
    roots = detail.get("vendor_folder_roots")
    if not isinstance(roots, list):
        return f"the {SKILL_INVENTORY} detail file has no list vendor_folder_roots"
    unread = [str(root.get("root")) if isinstance(root, dict) else repr(root)
              for root in roots
              if not (isinstance(root, dict) and root.get("status") == "read")]
    if unread:
        return f"vendor folder roots not read: {', '.join(unread)}"
    return None


def check_vendor(check: dict, outcomes: dict) -> tuple:
    """``(state, evidence, reason)`` of one ``vendor_absent`` check."""
    name = check["name"].casefold()
    evidence, reasons = [], []
    for skill, source, section, field in VENDOR_LISTS[check["match"]]:
        detail, reason = read_child_detail(skill, outcomes.get(skill), source, (section,))
        if reason is not None:
            reasons.append(reason)
            continue
        if section == "vendor_folders":
            # A root not read leaves the check open, but a hit under a root that was
            # read is still a hit.
            root_reason = unread_roots(detail)
            if root_reason is not None:
                reasons.append(root_reason)
        for item in detail[section]:
            if not isinstance(item, dict):
                continue
            if section == "programs" and item.get("source") != source:
                continue
            value = item.get(field)
            if not (isinstance(value, str) and value.casefold() == name):
                continue
            hit = {"skill": skill, "id": item.get("id")}
            if section == "vendor_folders":
                hit.update(folder=item.get("name"), root=item.get("root"))
            evidence.append(hit)
    if evidence:
        return "broken", evidence, "; ".join(reasons) or None
    if reasons:
        return "not_checked", [], "; ".join(reasons)
    return "kept", [], None


def check_one_decision(item_id: str, decision: dict, outcomes: dict) -> dict:
    """The ``j`` item of one decision."""
    states, found_by_check, unmade = [], [], []
    for n, check in enumerate(decision["checks"], 1):
        if check["kind"] == "setting":
            label = f"check {n} (setting {check['item']})"
            state, found, reason = check_setting(check, outcomes)
        else:
            label = f"check {n} (vendor_absent {check['match']} {check['name']!r})"
            state, found, reason = check_vendor(check, outcomes)
        states.append(state)
        found_by_check.append(found)
        if reason:
            unmade.append(f"{label}: {reason}"[:REASON_MAX])
    # A broken decision keeps only the evidence of its broken checks: what came back.
    broken = "broken" in states
    evidence = [entry for check_state, found in zip(states, found_by_check)
                if not broken or check_state == "broken" for entry in found]
    if broken:
        state = "broken"
    elif all(value == "kept" for value in states):
        state = "kept"
    else:
        state = "not_checked"
    return {"id": item_id, "decision": decision["id"], "state": state,
            "evidence": evidence, "reason": "; ".join(unmade) or None,
            "text": decision["text"], "made": decision["made"],
            "source": decision["source"]}


def check_decisions(outcomes: dict, data_dir: Path) -> tuple:
    """``(items or None, notes)``: one ``j`` item per decision of ``decisions.json``;
    ``[]`` without the file, ``None`` and one not_checked entry when it cannot be used."""
    loaded = decisions_file.load(data_dir, catalogue_expected=catalogue_expectations())
    if loaded["status"] == "unreadable":
        return None, [{"what": f"the user's decisions ({decisions_file.FILE_NAME})",
                       "reason": f"{loaded['reason']}; no decision was checked"}]
    return [check_one_decision(f"j{n}", decision, outcomes)
            for n, decision in enumerate(loaded["decisions"], 1)], []


# --- accepted findings (plan 060) -------------------------------------------------------
def fact_read(fact: dict, sub: str) -> bool:
    """Whether a target fact's ``sub`` field was read: the file does not exist (read,
    nothing there), or it exists and the field has no error beside it (sha256 with
    sha256_error). A file whose existence was not confirmed was not read."""
    if fact.get("exists") is False:
        return True
    return fact.get("exists") is True and fact.get(f"{sub}_error") is None


def watched_differs(how: str, accepted, now, now_read: bool = True):
    """True when ``now`` brings an accepted value back by ``how``, False when not,
    None when the two cannot be compared (a null on one side, a null now that was not
    read (``now_read`` false), a value of another type)."""
    if accepted is None and now is None:
        return False if now_read else None
    if accepted is None or now is None:
        return None
    if how == "changed":
        return accepted != now
    if how == "rises":
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                      for v in (accepted, now))
        return now > accepted if numbers else None
    try:
        return parse_utc(now) > parse_utc(accepted)
    except (TypeError, ValueError):
        return None


def compare_watched(kind: dict, facts: dict, item: dict) -> tuple:
    """``(changed, skipped)``: the watched fields whose value brings the entry back, as
    ``{field, accepted, now}``, and the names of those that could not be compared. A
    field under ``facts[]`` is compared per target fact present on both sides, by path,
    and named ``facts[<path>].<field>``."""
    changed, skipped = [], []
    for field, how in kind["watched"].items():
        if field.startswith(accepted_file.FACT_LIST):
            sub = field[len(accepted_file.FACT_LIST):]
            before = {fact.get("path"): fact for fact in facts.get("facts") or []
                      if isinstance(fact, dict) and fact.get("path") is not None}
            pairs = [(f"facts[{fact['path']}].{sub}", before[fact["path"]].get(sub),
                      fact.get(sub), fact_read(fact, sub)
                      and fact_read(before[fact["path"]], sub))
                     for fact in item.get("facts") or []
                     if isinstance(fact, dict) and fact.get("path") in before]
        else:
            pairs = [(field, facts.get(field), item.get(field), True)]
        for name, then, now, now_read in pairs:
            differs = watched_differs(how, then, now, now_read)
            if differs is None:
                skipped.append(name)
            elif differs:
                changed.append({"field": name, "accepted": then, "now": now})
    return changed, skipped


def accepted_source(kind: dict, facts: dict) -> dict:
    """The fields of the child source a kind needs read (its ``source``; a value
    ``@field`` is taken from the entry's facts)."""
    return {field: facts.get(value[1:]) if isinstance(value, str) and value.startswith("@")
            else value for field, value in (kind.get("source") or {}).items()}


def latest(candidates: list) -> dict:
    """The candidate with the latest ``last``; one without a readable time loses."""
    def when(item):
        try:
            return (1, parse_utc(item.get("last")))
        except (TypeError, ValueError):
            return (0, datetime.min.replace(tzinfo=timezone.utc))
    return max(candidates, key=when)


def match_accepted(item_id: str, entry: dict, kinds: dict, outcomes: dict) -> dict:
    """The ``a`` item of one accepted entry: its state against this pass."""
    result = {"id": item_id, "kind": entry["kind"], "key": entry["key"],
              "state": "not_checked", "changed": [], "skipped": [], "evidence": None,
              "accepted_on": entry.get("accepted_on"), "reason": None}
    kind = kinds[entry["kind"]]
    skill, section = kind["skill"], kind["section"]
    facts = entry.get("facts") if isinstance(entry.get("facts"), dict) else {}
    detail, reason = read_child_detail(skill, outcomes.get(skill),
                                       accepted_source(kind, facts), (section,))
    if reason is not None:
        return dict(result, reason=reason)
    match = kind.get("match") or {}
    candidates = [item for item in detail[section] if isinstance(item, dict)
                  and all(item.get(field) == value for field, value in match.items())
                  and accepted_file.key_of(kind, item) == entry["key"]]
    if not candidates:
        return dict(result, state="gone")
    item = latest(candidates)
    result["evidence"] = f"{skill} {item.get('id')}"
    reason = accepted_file.not_read_reason(item, REASON_MAX, kind["facts"])
    if reason is not None:
        return dict(result, reason=reason)
    changed, skipped = compare_watched(kind, facts, item)
    if changed:
        return dict(result, state="back", changed=changed, skipped=skipped)
    if skipped:
        return dict(result, skipped=skipped,
                    reason=f"not compared (a null value): {', '.join(skipped)}")
    return dict(result, state="quiet")


def check_accepted(outcomes: dict, data_dir: Path) -> tuple:
    """``(items or None, counts or None, notes)``: one ``a`` item per entry of
    ``accepted.json``; ``[]`` without the file, ``None`` and one not_checked entry when
    the file or the kinds file cannot be used."""
    kinds, kinds_reason = accepted_file.load_kinds()
    loaded = accepted_file.load(data_dir, kinds)
    if loaded["status"] == "none":
        return [], dict.fromkeys(ACCEPTED_STATES, 0), []
    if loaded["status"] != "read" or kinds is None:
        why = loaded["reason"] or kinds_reason
        return None, None, [{"what": f"the user's accepted findings "
                                     f"({accepted_file.FILE_NAME})",
                             "reason": f"{why}; no accepted finding was checked"}]
    items = [match_accepted(f"a{n}", entry, kinds, outcomes)
             for n, entry in enumerate(loaded["entries"], 1)]
    counts = Counter(item["state"] for item in items)
    return items, {state: counts[state] for state in ACCEPTED_STATES}, []


# --- command line -----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    datadir.add_arguments(parser)
    parser.add_argument("--detail", metavar="ID",
                        help="print one item (a child h1, h2, ..., a firewall item w1, "
                             "w2, ..., a driver update link y1, y2, ..., a decision j1, "
                             "j2, ... or an accepted finding a1, a2, ...) of the newest "
                             "detail file and exit; no child is run")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    return parser


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("runall-*.detail.json"), key=lambda p: p.name)
        if not files:
            print(f"no detail file in {work}; run runall first", file=sys.stderr)
            return 1
        newest = files[-1]
    try:
        detail = json.loads(newest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"{newest} could not be read: {error_text(exc)}", file=sys.stderr)
        return 1
    if not isinstance(detail, dict):
        print(f"{newest} does not hold a detail object", file=sys.stderr)
        return 1
    for section in DETAIL_SECTIONS:
        for item in detail.get(section) or []:
            if isinstance(item, dict) and item.get("id") == item_id:
                print(json.dumps(item, ensure_ascii=True, indent=1))
                return 0
    print(f"id {item_id!r} not found in {newest}", file=sys.stderr)
    return 1


def main(argv=None, run_child=None, now=None) -> int:
    """Run every child of children.json and summarise, or print one item with --detail."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.detail_file is not None and args.detail is None:
        parser.error("--detail-file needs --detail")
    if args.detail_file is not None:
        # The detail file is named explicitly: no data directory is needed.
        return show_detail(Path(), args.detail, Path(args.detail_file).absolute())
    try:
        data_dir = datadir.resolve(args.data_dir, os.environ, default=args.default_data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    work = data_dir / "work"
    if args.detail is not None:
        return show_detail(work, args.detail)

    try:
        children = load_children(CHILDREN_FILE)
    except ChildrenError as exc:
        print(f"children.json not usable, no child was run: {exc}", file=sys.stderr)
        return 2

    run_child = run_child or default_run_child
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    work.mkdir(parents=True, exist_ok=True)
    summary_file = work / f"runall-{stamp}.summary.json"
    detail_file = work / f"runall-{stamp}.detail.json"
    started = time.monotonic()

    items, detail_items, sources, not_checked = [], [], [], []
    outcomes = {}
    for n, child in enumerate(children, 1):
        item_id = f"h{n}"
        outcome = run_one(run_child, child, data_dir)
        outcomes[child["skill"]] = outcome
        item = child_item(item_id, child, outcome)
        items.append(item)
        detail_items.append({"id": item_id, "skill": child["skill"],
                             "status": outcome["status"], "summary": outcome["summary"]})
        ok = outcome["status"] == "ok"
        sources.append({"name": child["skill"], "id": item_id, "script": child["script"],
                        "status": "read" if ok else "unreadable",
                        "reason": None if ok else outcome["reason"]})
        if not ok:
            not_checked.append({"what": f"{child['skill']} ({child['script']})",
                                "id": item_id, "status": outcome["status"],
                                "reason": f"{outcome['reason']}; its findings are not in "
                                          f"this run"})

    firewall, firewall_notes = compare_firewall(outcomes)
    not_checked.extend(firewall_notes)
    links, link_notes = link_driver_updates(outcomes)
    not_checked.extend(link_notes)
    decision_items, decision_notes = check_decisions(outcomes, data_dir)
    not_checked.extend(decision_notes)
    accepted_items, accepted_counts, accepted_notes = check_accepted(outcomes, data_dir)
    not_checked.extend(accepted_notes)
    all_ports = firewall["firewall_ports"]
    listed_ports = all_ports[:FIREWALL_PORTS_MAX] if all_ports is not None else None
    cut_ports = len(all_ports) - len(listed_ports) if all_ports is not None else 0

    counts = dict(Counter(item["status"] for item in items))
    counts = {status: counts[status] for status in STATUSES if status in counts}
    duration = round(time.monotonic() - started, 1)

    detail = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "summary_file": str(summary_file),
        "children": detail_items,
        "firewall_ports": all_ports,
        "firewall_ports_counts": firewall["firewall_ports_counts"],
        "network_categories": firewall["network_categories"],
        "driver_update_links": links["driver_update_links"],
        "link_counts": links["link_counts"],
        "decisions": decision_items,
        "accepted": accepted_items,
        "accepted_counts": accepted_counts,
    }
    detail_file.write_text(dump(detail) + "\n", encoding="utf-8")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "sources": sources,
        "not_checked": not_checked,
        "summary_file": str(summary_file),
        "detail_file": str(detail_file),
        "truncated": cut_ports,  # firewall_ports items cut by FIREWALL_PORTS_MAX
        "duration_s": duration,
        "counts": counts,
        "children": items,
        "firewall_ports": listed_ports,
        "firewall_ports_counts": firewall["firewall_ports_counts"],
        "network_categories": firewall["network_categories"],
        "driver_update_links": links["driver_update_links"],
        "link_counts": links["link_counts"],
        "decisions": decision_items,
        "accepted": accepted_items,
        "accepted_counts": accepted_counts,
    }
    text_out = dump(summary)
    summary_file.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Builders for the ush-processes tests of milestone M2 (plan 051): services, file facts,
TCP/UDP endpoints and the ush-inventory baseline.

The M1 interface (``main``, ``FakePowerShell``, the M1 jobs, output files, ``sources``,
``not_checked``, groups) is described in ``fakes.py`` and stays. M2 adds:

- Jobs and rows (``FakePowerShell`` answers them by name; an unknown job answers ``[]``):
  - ``services``: ``{Name, DisplayName, ProcessId, StartMode, Type}``; ``Type`` is the
    registry service type as an int (bit 0x80 = per-user instance).
  - ``file_facts``: directory rows ``{Kind: "dir", Name, Path}`` for ``ProgramFiles``,
    ``ProgramFilesX86``, ``SystemRoot``, ``System32`` and file rows ``{Kind: "file", Path,
    ExpandedPath, Exists, SignatureStatus, Signer, Company}`` or ``{Kind: "file", Path,
    Error}``. ``Path`` is the group path as given; matching is case-insensitive.
  - ``tcp_listeners`` and ``udp_endpoints``: ``{LocalAddress, LocalPort, OwningProcess}``.
    No results is a failure whose stderr carries the FullyQualifiedErrorId
    ``CmdletizationQuery_NotFound_...``; that gives status ``empty``.
- The ush-inventory baseline is ``<data dir>/state/ush-inventory.json``
  (``ush-inventory.elevated.json`` for an admin run) in the format ``baseline.load``
  accepts.
- Group fields: ``services``, ``services_count``, ``autostart``, ``program`` (``{key,
  name}`` or null), ``signature_status``, ``signer``, ``company``, ``exists``,
  ``started_by``; unread markers in the group's ``unread_fields``.
- Summary: ``inventory {status, reason, age_days, created_at, missing_sources,
  entries_without_path}``, ``ports`` (ids ``p1...``), ``udp_bound``,
  ``counts.udp_port_zero``, ``counts.udp_bound_outside_summary``.

Assumptions added by these tests beyond that interface:

- A port item's ``process`` is the process ``Name``; ``protocol`` is ``"tcp"`` in any case.
- A ``not_checked`` item about the ush-inventory baseline mentions ``inventory`` in its
  ``what`` or ``reason``.
- A ``not_checked`` item about cut ports carries the number of ports left out as a
  number in its text.

Every value here is invented; nothing comes from a machine. Directory values are the
Windows defaults, not readings.
"""

import json
from pathlib import Path

from .fakes import ProcessesTestCase, machine, ok

VENDOR = "Invented Vendor Ltd"

PROGRAM_FILES = "C:\\Program Files"
PROGRAM_FILES_X86 = "C:\\Program Files (x86)"
SYSTEM_ROOT = "C:\\Windows"
SYSTEM32 = "C:\\Windows\\System32"

OWN_PROCESS = 0x10
SHARE_PROCESS = 0x20
# A per-user service instance: share process + user service + instance bits.
USER_SERVICE_INSTANCE = 0x20 | 0x40 | 0x80

INVENTORY_SOURCES = (
    "run_keys",
    "startup_folders",
    "scheduled_tasks",
    "services",
    "win32_programs",
    "msix_programs",
)

BASELINE_CREATED = "2026-09-18T12:00:00+00:00"

# What Windows PowerShell 5.1 writes when Get-NetTCPConnection finds nothing; the
# message line is invented (it is localized on a real system), the FQID is not.
TCP_NOT_FOUND = (
    "Get-NetTCPConnection : Invented localized message: no matching objects.\r\n"
    "    + CategoryInfo          : ObjectNotFound: (Listen:State) "
    "[Get-NetTCPConnection], CimJobException\r\n"
    "    + FullyQualifiedErrorId : CmdletizationQuery_NotFound_State,"
    "Get-NetTCPConnection\r\n"
)

_SAME = object()


# --- PowerShell rows -------------------------------------------------------------------


def dir_rows():
    """The four directories the ``file_facts`` job expands next to the facts."""
    return [
        {"Kind": "dir", "Name": "ProgramFiles", "Path": PROGRAM_FILES},
        {"Kind": "dir", "Name": "ProgramFilesX86", "Path": PROGRAM_FILES_X86},
        {"Kind": "dir", "Name": "SystemRoot", "Path": SYSTEM_ROOT},
        {"Kind": "dir", "Name": "System32", "Path": SYSTEM32},
    ]


def file_row(path, exists=True, status="Valid", signer=VENDOR, company=None, expanded=None):
    """One file fact; ``path`` is the group path exactly as it was requested."""
    return {
        "Kind": "file",
        "Path": path,
        "ExpandedPath": path if expanded is None else expanded,
        "Exists": exists,
        "SignatureStatus": status,
        "Signer": signer,
        "Company": signer if company is None else company,
    }


def file_error(path, error="Invented: the file could not be opened."):
    return {"Kind": "file", "Path": path, "Error": error}


def facts_for(rows):
    """One Valid ``file_row`` per distinct (case-insensitive) path of the process rows."""
    seen, result = set(), []
    for row in rows:
        path = row.get("ExecutablePath")
        if path and path.lower() not in seen:
            seen.add(path.lower())
            result.append(file_row(path))
    return result


def service_row(name, pid, start_mode="Auto", type_=OWN_PROCESS, display_name=None):
    """One ``Win32_Service`` row with the registry ``Type`` the ``services`` job adds."""
    return {
        "Name": name,
        "DisplayName": display_name or f"Invented service {name}",
        "ProcessId": pid,
        "StartMode": start_mode,
        "Type": type_,
    }


def endpoint(address, port, pid):
    """One row of ``tcp_listeners`` or ``udp_endpoints``."""
    return {"LocalAddress": address, "LocalPort": port, "OwningProcess": pid}


def responses(rows, services=(), files=None, tcp=(), udp=(), **machine_kwargs):
    """Responses for every M1 and M2 job.

    ``files`` is the list of file rows (default: one Valid row per process path); the
    directory rows are always added. ``machine_kwargs`` go to ``fakes.machine``.
    """
    result = machine(rows, **machine_kwargs)
    file_rows = facts_for(rows) if files is None else list(files)
    result.update({
        "services": ok(list(services)),
        "file_facts": ok(dir_rows() + file_rows),
        "tcp_listeners": ok(list(tcp)),
        "udp_endpoints": ok(list(udp)),
    })
    return result


# --- ush-inventory baseline ------------------------------------------------------------


def fact(target, program=None, expanded=_SAME, exists=True, status="Valid", signer=VENDOR):
    """One element of an inventory item's ``facts``; ``expanded=None`` is an unread path."""
    return {
        "path": target,
        "expanded_path": target if expanded is _SAME else expanded,
        "exists": exists,
        "signature_status": status,
        "signer": signer,
        "company": signer,
        "program": program,
    }


def autostart_item(kind, target, program=None, enabled=True, expanded=_SAME):
    """A ``run_keys`` / ``startup_folders`` / ``scheduled_tasks`` item."""
    return {
        "kind": kind,
        "enabled": enabled,
        "targets": [target],
        "facts": [fact(target, program=program, expanded=expanded)],
        "unread_fields": [],
    }


def service_item(name, target, enabled=True):
    return {
        "kind": "service",
        "name": name,
        "enabled": enabled,
        "targets": [target],
        "facts": [fact(target)],
    }


def program_item(name, install_location):
    return {"name": name, "install_location": install_location, "publisher": VENDOR}


def inventory_sources(run_keys=None, startup_folders=None, scheduled_tasks=None,
                      services=None, win32_programs=None, msix_programs=None):
    """All six sources, each ``{key: item}`` (empty when not given)."""
    return {
        "run_keys": dict(run_keys or {}),
        "startup_folders": dict(startup_folders or {}),
        "scheduled_tasks": dict(scheduled_tasks or {}),
        "services": dict(services or {}),
        "win32_programs": dict(win32_programs or {}),
        "msix_programs": dict(msix_programs or {}),
    }


def inventory_path(data_dir, elevated=False):
    name = "ush-inventory.elevated.json" if elevated else "ush-inventory.json"
    return Path(data_dir) / "state" / name


def write_inventory(data_dir, sources, elevated=False, created_at=BASELINE_CREATED):
    """Write a valid ush-inventory baseline and return its path."""
    path = inventory_path(data_dir, elevated)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "skill": "ush-inventory",
        "created_at": created_at,
        "elevated": bool(elevated),
        "sources": sources,
    }
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def write_raw_inventory(data_dir, text, elevated=False):
    """Write ``text`` as the baseline file (for an unreadable baseline)."""
    path = inventory_path(data_dir, elevated)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- Test case -------------------------------------------------------------------------


class LinksTestCase(ProcessesTestCase):
    def group_with_pid(self, summary, pid):
        """The summary group whose ``pids`` holds ``pid``."""
        matches = [g for g in self.groups(summary) if pid in (g.get("pids") or [])]
        self.assertEqual(len(matches), 1,
                         f"group with pid {pid}: {[g.get('pids') for g in self.groups(summary)]}")
        return matches[0]

    def detail_group_id(self, summary, pid):
        """The id of the detail group whose processes hold ``pid``."""
        groups = self.detail(summary).get("groups")
        self.assertIsInstance(groups, list)
        matches = [
            g.get("id") for g in groups
            if any(p.get("pid") == pid for p in (g.get("processes") or []))
        ]
        self.assertEqual(len(matches), 1, f"detail group with pid {pid}: {matches}")
        return matches[0]

    def inventory(self, summary):
        inventory = summary.get("inventory")
        self.assertIsInstance(inventory, dict, summary.get("inventory"))
        return inventory

    def ports(self, summary):
        ports = summary.get("ports")
        self.assertIsInstance(ports, list, summary.get("ports"))
        return ports

    def assert_not_unread(self, item, field):
        """``field`` is null and not in ``unread_fields``: nothing to read."""
        self.assertIn(field, item, item)
        self.assertIsNone(item[field], item)
        self.assertIsInstance(item.get("unread_fields"), list, item)
        self.assertNotIn(field, item["unread_fields"], item)

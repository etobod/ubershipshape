"""Invented PowerShell rows for the autostart sources of ush-inventory (plan 048, M3).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``comparison``, item
``key``/``id``/``own``) is described in ``fakes.py``. This module only builds rows for the
M3 jobs, in the shapes fixed for M3 (see the docstring of ``test_autostart.py``).

Every value here is invented; nothing comes from a machine. Directory values are the
Windows defaults, not readings.
"""

from .fakes import ok

MS = "Microsoft Corporation"
VENDOR = "Invented Vendor Ltd"

LOGON = "MSFT_TaskLogonTrigger"
BOOT = "MSFT_TaskBootTrigger"
DAILY = "MSFT_TaskDailyTrigger"

OWN_PROCESS = 0x10
SHARE_PROCESS = 0x20
# A per-user service instance: share process + user service + instance bits.
USER_SERVICE_INSTANCE = 0x20 | 0x40 | 0x80

ENTRY_SOURCES = (
    "run_keys",
    "startup_folders",
    "startup_approved",
    "scheduled_tasks",
    "services",
)

PROGRAM_FILES = "C:\\Program Files"
PROGRAM_FILES_X86 = "C:\\Program Files (x86)"
SYSTEM_ROOT = "C:\\Windows"
SYSTEM32 = "C:\\Windows\\System32"


def dir_rows():
    """The four directories the ``file_facts`` job expands next to the facts."""
    return [
        {"Kind": "dir", "Name": "ProgramFiles", "Path": PROGRAM_FILES},
        {"Kind": "dir", "Name": "ProgramFilesX86", "Path": PROGRAM_FILES_X86},
        {"Kind": "dir", "Name": "SystemRoot", "Path": SYSTEM_ROOT},
        {"Kind": "dir", "Name": "System32", "Path": SYSTEM32},
    ]


def file_row(path, expanded=None, exists=True, status="Valid", signer=MS, company=None):
    """One file fact; ``path`` is the target exactly as it was requested."""
    return {
        "Kind": "file",
        "Path": path,
        "ExpandedPath": path if expanded is None else expanded,
        "Exists": exists,
        "SignatureStatus": status,
        "Signer": signer,
        "Company": signer if company is None else company,
    }


def facts(*rows):
    """A successful ``file_facts`` answer: the directory rows plus ``rows``."""
    return ok(dir_rows() + list(rows))


def run_value(name, value, hive="hkcu", key="Run", value_kind="String"):
    """One value of a ``Run``/``RunOnce`` key as the ``run_keys`` job returns it."""
    return {"Hive": hive, "Key": key, "Name": name, "Value": value, "ValueKind": value_kind}


def startup_file(file_name, full_name, target=None, arguments=None, scope="user"):
    """One file of a Startup folder; ``target``/``arguments`` only for a ``.lnk``."""
    return {
        "Scope": scope,
        "FileName": file_name,
        "FullName": full_name,
        "TargetPath": target,
        "Arguments": arguments,
    }


def approved(name, first_byte, hive="hkcu", key="Run"):
    """One ``StartupApproved`` value: 12 bytes, the first one given."""
    return {"Hive": hive, "Key": key, "Name": name, "Bytes": [first_byte] + [0] * 11}


def exec_action(execute, arguments=None):
    return {"Type": "Exec", "Execute": execute, "Arguments": arguments,
            "ClassId": None, "InprocServer32": None}


def com_action(class_id, inproc):
    """``inproc`` is the resolved ``InprocServer32`` path, or None for an unknown CLSID."""
    return {"Type": "ComHandler", "Execute": None, "Arguments": None,
            "ClassId": class_id, "InprocServer32": inproc}


def task(name, actions, triggers=(LOGON,), path="\\Invented\\", state="Ready"):
    return {
        "TaskPath": path,
        "TaskName": name,
        "State": state,
        "Triggers": list(triggers),
        "Actions": list(actions),
    }


def service(name, path_name, state="Running", start_mode="Auto", type_=OWN_PROCESS,
            delayed=0, service_dll=None, key_service_dll=None,
            template_service_dll=None, template_key_service_dll=None,
            template_start=None, display_name=None):
    """One ``Win32_Service`` row with the registry fields the ``services`` job adds."""
    return {
        "Name": name,
        "DisplayName": display_name or f"Invented service {name}",
        "PathName": path_name,
        "State": state,
        "StartMode": start_mode,
        "Type": type_,
        "DelayedAutostart": delayed,
        "ServiceDll": service_dll,
        "KeyServiceDll": key_service_dll,
        "TemplateServiceDll": template_service_dll,
        "TemplateKeyServiceDll": template_key_service_dll,
        "TemplateStart": template_start,
    }


# A clean invented machine: every service and task target is an existing,
# Valid, Microsoft-signed, non-launcher file; no Run values, no Startup files.
CLEAN_SERVICES = [
    service("InventedWinSvcA", "C:\\Windows\\System32\\inventedsvca.exe"),
    service("InventedWinSvcB", "\"C:\\Windows\\System32\\inventedsvcb.exe\" -service"),
    service("InventedHostSvc", "C:\\Windows\\system32\\svchost.exe -k InventedGroup -p",
            type_=SHARE_PROCESS, service_dll="%SystemRoot%\\System32\\inventedhost.dll"),
]
CLEAN_TASKS = [
    task("InventedLogonTask",
         [exec_action("%windir%\\System32\\inventedtask.exe", "/logon")],
         triggers=(LOGON,)),
    task("InventedBootCom",
         [com_action("{0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D}",
                     "%SystemRoot%\\System32\\inventedcom.dll")],
         triggers=(BOOT,)),
]
CLEAN_FILES = [
    file_row("C:\\Windows\\System32\\inventedsvca.exe"),
    file_row("C:\\Windows\\System32\\inventedsvcb.exe"),
    file_row("%SystemRoot%\\System32\\inventedhost.dll",
             expanded="C:\\Windows\\System32\\inventedhost.dll"),
    file_row("%windir%\\System32\\inventedtask.exe",
             expanded="C:\\Windows\\System32\\inventedtask.exe"),
    file_row("%SystemRoot%\\System32\\inventedcom.dll",
             expanded="C:\\Windows\\System32\\inventedcom.dll"),
]
CLEAN_SERVICE_KEYS = {"service:InventedWinSvcA", "service:InventedWinSvcB",
                      "service:InventedHostSvc"}
CLEAN_TASK_KEYS = {"task:\\Invented\\InventedLogonTask", "task:\\Invented\\InventedBootCom"}


def clean_responses(extra_files=()):
    """Responses for the clean machine; ``extra_files`` adds file facts."""
    return {
        "run_keys": ok([]),
        "startup_folders": ok([]),
        "startup_approved": ok([]),
        "scheduled_tasks": ok(list(CLEAN_TASKS)),
        "services": ok(list(CLEAN_SERVICES)),
        "file_facts": facts(*CLEAN_FILES, *extra_files),
    }

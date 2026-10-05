"""Give the facts of this machine that Windows and firmware advice is compared with
(read-only, no network).

The model, not this script, goes online: it reads the sources of
``data/sources.json`` and searches with general queries. This script never imports a
network module.

Sources (one read-only PowerShell job each, never elevated, run through an injectable
``run_ps``; see ``skills/ush-common/scripts/psrun.py``):

- ``os_version``: ``DisplayVersion``, ``CurrentBuild``, ``UBR`` and ``EditionID`` of
  ``HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion`` (``ProductName`` is not
  read: on Windows 11 it still says "Windows 10"), and the processor architecture of
  the machine (``PROCESSOR_ARCHITEW6432`` when PowerShell runs as a 32-bit process on a
  64-bit machine, else ``PROCESSOR_ARCHITECTURE``).
- ``hotfixes``: the ``HotFixID`` of every ``Get-HotFix`` row, nothing else (the
  computer name and the install date are not read).
- ``firmware``: ``Manufacturer`` and ``Model`` of ``Win32_ComputerSystem`` and
  ``SMBIOSBIOSVersion`` and ``ReleaseDate`` (``yyyy-MM-dd``) of ``Win32_BIOS``. The
  serial number, the UUID and the computer name are never selected.

``machine.product`` is the MSRC product name from ``data/products.json`` for
``<DisplayVersion>|<architecture>``; when the map has no such key, or a part of the key
was not read, it is null and ``product_reason`` says why. ``data/sources.json`` lists
the sources the model may fetch and the support domains of firmware manufacturers.
Either file unreadable or of the wrong shape exits 2 before any PowerShell runs.

A failed job gives null in its fields and a ``not_checked`` item naming the job; an
empty hotfix list is ``[]`` and no item. Without ``--findings`` the top-level
``updates``, ``exploited``, ``firmware`` and ``issues`` are null and ``not_checked``
says the search was not done.

``--findings <file>`` reads what the model found online:
``{"searches": [{id, status, reason}], "findings": [...]}``. The file is checked
before PowerShell runs and before anything is written; a bad shape exits 2 and names
the entry. Each list comes from one search (``updates`` from ``release-info``, ``exploited``
from ``kev``, ``issues`` from ``release-health``, ``firmware`` from ``firmware``); a
search that is missing or not ``read`` gives a null list (never ``[]``) and a
``not_checked`` item, and its findings stay only in the detail file's ``findings``.
``msrc`` gives only the CVE counts of the months; ``exploited`` also needs ``msrc`` and
``release-info``.
Each finding gets ``domain`` and ``listed`` (its host is a domain of
``data/sources.json`` or a subdomain of one; for firmware also the domains of the
manufacturer of this machine). The comparison with the machine:

- ``updates`` (one per month): ``applied`` compares the build and UBR of this machine
  with the fixed builds of the month's ``security`` releases only. A fixed build of
  another build number is left out ("build mismatch"); at or above every one gives
  true, below every one false, in between null ("mixed"). No security release, or no
  build or UBR, gives null and never false. ``kb_installed`` is information only.
- ``exploited``: a KEV entry whose CVE is in a month's ``cves``; ``applied`` is true
  when any such month is applied (updates are cumulative), else the earliest month's.
  A KEV entry outside the months goes to ``kev_other`` in the detail file and is only
  counted in the summary. Its ids continue the ``k`` numbering after ``exploited``.
- ``firmware``: ``model_matches``, ``same_version`` (the whole page version, or a
  page part with a digit and a dot or of at least five characters, is the whole BIOS
  version, one of its parts or the last dotted part of one) and ``newer`` (only for a
  matching model and another version, by release date). Version numbers are never
  compared as numbers.
- ``query_warnings``: a query or url that holds the build with UBR or the BIOS version
  (whole or a part, each of at least four characters with a digit) of this machine,
  also after one ``v``, or a query with a KB of this machine that no update finding
  names. The warning names the finding, never the query.

A repeated month is one item; a repeated CVE, firmware version or issue (url and
title) keeps its first finding. The baseline ``state/ush-advice.json`` keeps the keys
seen (month, CVE, ``manufacturer|model|version`` in lower case, ``url|title`` of an
issue with the title in lower case) as the union of
every run, so a key seen once is never ``new`` again; a search not read keeps the
saved keys and a run with no search read does not write the baseline at all.

Nothing is judged and nothing on the machine is changed. The summary goes to stdout
and to ``work/advice-<UTC stamp>.summary.json`` (at most 35 000 characters: ``issues``
and then ``exploited`` are cut from their end); the detail file
``work/advice-<UTC stamp>.detail.json`` has everything. ``--detail <id>`` prints one
item of the newest detail file.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import baseline  # called as baseline.save(...), so tests can patch it
import datadir
import psrun
from psrun import dump, ps_script, run_job

SKILL = "ush-advice"
SCHEMA_VERSION = 1
SUMMARY_MAX_CHARS = 35000
DATA_DIR = Path(__file__).absolute().parents[1] / "data"
PRODUCTS_FILE = DATA_DIR / "products.json"
SOURCES_FILE = DATA_DIR / "sources.json"
JOBS = ("os_version", "hotfixes", "firmware")
FINDINGS_FIELDS = ("updates", "exploited", "firmware", "issues")
DETAIL_SECTIONS = ("updates", "exploited", "kev_other", "firmware", "issues", "findings")
SOURCE_FIELDS = {"id", "url", "kind", "domains"}
FIRMWARE_DOMAIN_FIELDS = {"manufacturer_prefix", "domains"}
DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")

# --findings: the searches, the list each one fills and the fields of each kind.
SEARCH_IDS = ("release-info", "msrc", "kev", "release-health", "firmware")
SEARCH_STATUSES = ("read", "partial", "unreadable")
LIST_OF_SEARCH = {"release-info": "updates", "kev": "exploited",
                  "release-health": "issues", "firmware": "firmware"}
SEARCH_OF_LIST = {name: search_id for search_id, name in LIST_OF_SEARCH.items()}
# What a search that was not read leaves null: msrc fills no list of its own, only the
# CVE counts of the months (and, with kev, exploited).
NULL_WITHOUT = {**{search_id: f"{name} is null" for search_id, name in LIST_OF_SEARCH.items()},
                "msrc": "cve_count, critical_count and exploited are null"}
COMMON_FIELDS = ("kind", "url", "title", "query", "published")
KIND_FIELDS = {
    "update": ("month", "kb", "fixed_build", "release_type", "cves"),
    "exploited": ("cve", "vendor", "product", "date_added", "due_date", "ransomware"),
    "firmware": ("manufacturer", "model", "version", "release_date"),
    "issue": (),
}
RELEASE_TYPES = ("security", "preview")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
KB = re.compile(r"^KB\d+$", re.IGNORECASE)
CVE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
# 10.0.B.U (CVRF) or B.U (the "OS Build" of a KB page); nothing else.
FIXED_BUILD = re.compile(r"^(?:10\.0\.)?(\d+)\.(\d+)$")
# Tokens are compared whole: a boundary is any character outside [0-9A-Za-z.].
TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z.]+")
BASELINE_SOURCES = FINDINGS_FIELDS

# Shared helpers prepended to every job body (a copy of health.py's PS_HELPERS; skills
# do not import each other). S keeps $null as null (a plain [string] cast would turn
# it into ""); N reads an integer from text or null.
PS_HELPERS = r"""function S($v) {
  if ($null -eq $v) { return $null }
  if ($v -is [array]) { return (@($v | ForEach-Object { [string]$_ }) -join ', ') }
  return [string]$v
}
function N($v) {
  if ($null -eq $v) { return $null }
  [long]$n = 0
  if ([long]::TryParse(([string]$v).Trim(), [ref]$n)) { return $n }
  return $null
}
"""

# ProductName is not read: on Windows 11 it still says "Windows 10".
OS_VERSION_BODY = r"""$key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('SOFTWARE\Microsoft\Windows NT\CurrentVersion')
if ($null -eq $key) { throw 'the CurrentVersion key is missing' }
$arch = $env:PROCESSOR_ARCHITEW6432
if ([string]::IsNullOrEmpty($arch)) { $arch = $env:PROCESSOR_ARCHITECTURE }
$result = [pscustomobject]@{
  DisplayVersion = S $key.GetValue('DisplayVersion')
  CurrentBuild = S $key.GetValue('CurrentBuild')
  UBR = N $key.GetValue('UBR')
  EditionID = S $key.GetValue('EditionID')
  Architecture = S $arch
}
$key.Close()
"""

# Only the update id: the rows also carry the computer name and the install date,
# which are not needed and not read.
HOTFIXES_BODY = r"""$result = @(Get-HotFix | ForEach-Object {
  [pscustomobject]@{ HotFixID = S $_.HotFixID }
})
"""

# Only the four fields below are selected; nothing that identifies this one machine.
# ReleaseDate arrives as local time; firmware stores it in UTC, so the date is taken in UTC.
FIRMWARE_BODY = r"""$system = @(Get-CimInstance -ClassName Win32_ComputerSystem -Property Manufacturer, Model)[0]
$bios = @(Get-CimInstance -ClassName Win32_BIOS -Property SMBIOSBIOSVersion, ReleaseDate)[0]
$date = $null
if ($null -ne $bios -and $bios.ReleaseDate -is [datetime]) {
  $date = $bios.ReleaseDate.ToUniversalTime().ToString('yyyy-MM-dd', [System.Globalization.CultureInfo]::InvariantCulture)
}
$result = [pscustomobject]@{
  Manufacturer = S $system.Manufacturer
  Model = S $system.Model
  SMBIOSBIOSVersion = S $bios.SMBIOSBIOSVersion
  ReleaseDate = $date
}
"""

BODIES = {
    "os_version": OS_VERSION_BODY,
    "hotfixes": HOTFIXES_BODY,
    "firmware": FIRMWARE_BODY,
}


# --- small helpers ---------------------------------------------------------------
def text(value):
    """A stripped non-empty string, or None (an empty field is not read, never "none")."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def as_int(value):
    """An int from a JSON number or a numeric string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


# --- data files ------------------------------------------------------------------
class DataFileError(Exception):
    """A data file of the skill could not be read or has the wrong shape."""


def read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise DataFileError(f"{path} could not be read: {type(exc).__name__}: {exc}") from exc


def load_products(path: Path) -> dict:
    """``{"<DisplayVersion>|<architecture>": "<MSRC product name>"}``."""
    data = read_json(path)
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, dict) or not products:
        raise DataFileError(f"{path} does not hold a non-empty 'products' object")
    for key, name in products.items():
        parts = key.split("|")
        if (len(parts) != 2 or not all(text(p) == p for p in parts)
                or key != key.upper() or not text(name)):
            raise DataFileError(f"{path}: entry {key!r} is not "
                                f"'<DisplayVersion>|<ARCHITECTURE>': '<product name>' (no spaces around "
                                f"the parts, upper-case)")
    return products


def check_domains(path: Path, where: str, domains) -> None:
    if (not isinstance(domains, list) or not domains
            or not all(isinstance(d, str) and DOMAIN.fullmatch(d) for d in domains)):
        raise DataFileError(f"{path}: {where} 'domains' is not a non-empty list of "
                            f"lower-case host names")


def load_sources(path: Path) -> dict:
    """``{"sources": [{id, url, kind, domains}], "firmware_domains": [...]}``."""
    data = read_json(path)
    if not isinstance(data, dict):
        raise DataFileError(f"{path} does not hold an object")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise DataFileError(f"{path} does not hold a non-empty 'sources' list")
    seen = set()
    for index, source in enumerate(sources):
        where = f"source {index}"
        if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
            raise DataFileError(f"{path}: {where} does not have exactly the fields "
                                f"{', '.join(sorted(SOURCE_FIELDS))}")
        if not text(source["id"]) or source["id"] in seen:
            raise DataFileError(f"{path}: {where} has an empty or repeated 'id'")
        seen.add(source["id"])
        if not isinstance(source["url"], str) or not source["url"].startswith("https://"):
            raise DataFileError(f"{path}: {where} 'url' is not an https:// address")
        if not text(source["kind"]):
            raise DataFileError(f"{path}: {where} has an empty 'kind'")
        check_domains(path, where, source["domains"])
    firmware = data.get("firmware_domains")
    if not isinstance(firmware, list) or not firmware:
        raise DataFileError(f"{path} does not hold a non-empty 'firmware_domains' list")
    for index, entry in enumerate(firmware):
        where = f"firmware_domains {index}"
        if not isinstance(entry, dict) or set(entry) != FIRMWARE_DOMAIN_FIELDS:
            raise DataFileError(f"{path}: {where} does not have exactly the fields "
                                f"{', '.join(sorted(FIRMWARE_DOMAIN_FIELDS))}")
        if not text(entry["manufacturer_prefix"]):
            raise DataFileError(f"{path}: {where} has an empty 'manufacturer_prefix'")
        check_domains(path, where, entry["domains"])
    return data


# --- collection --------------------------------------------------------------------
def record(job: str, result: dict, sources: list, not_checked: list) -> dict:
    """Name the job's status in ``sources`` (and in ``not_checked`` when unreadable)."""
    sources.append({"name": job, "status": result["status"], "reason": result["reason"]})
    if result["status"] == "unreadable":
        not_checked.append({"what": f"job {job}", "reason": result["reason"]})
    return result


def collect(run_ps, work: Path, stamp: str, sources: list, not_checked: list) -> dict:
    """Run every job in order; return their results by job."""
    results = {}
    for job in JOBS:
        out_path = work / f"advice-{stamp}.{job}.json"
        script = ps_script(PS_HELPERS + BODIES[job], out_path)
        results[job] = record(job, run_job(run_ps, job, script, out_path),
                              sources, not_checked)
    return results


def first_row(result: dict):
    """The first row of a read job, or None when the job was not read or is empty."""
    return result["rows"][0] if result["status"] == "read" else None


def os_facts(result: dict, not_checked: list) -> dict:
    row = first_row(result)
    if row is None and result["status"] == "empty":
        not_checked.append({"what": "job os_version",
                            "reason": "the job returned no row; the version is not known"})
    facts = {
        "display_version": text((row or {}).get("DisplayVersion")),
        "build": text((row or {}).get("CurrentBuild")),
        "ubr": as_int((row or {}).get("UBR")),
        "edition_id": text((row or {}).get("EditionID")),
        "architecture": text((row or {}).get("Architecture")),
    }
    if row is not None:
        missing = [name for name, value in facts.items() if value is None]
        if missing:
            not_checked.append({"what": "os_version fields",
                                "reason": f"Windows returned no value for {', '.join(missing)}"})
    return facts


def hotfix_list(result: dict, not_checked: list):
    """Sorted unique update ids; ``[]`` for an empty answer, None when not read."""
    if result["status"] == "unreadable":
        return None
    ids, bad = set(), 0
    for row in result["rows"]:
        value = text(row.get("HotFixID"))
        if value is None:
            bad += 1
        else:
            ids.add(value.upper())
    if bad:
        not_checked.append({"what": "hotfixes rows",
                            "reason": f"{bad} rows of the hotfixes job had no HotFixID "
                                      f"and were left out"})
    return sorted(ids)


def firmware_facts(result: dict, not_checked: list):
    """``{manufacturer, model, bios_version, bios_date}`` or None when not read."""
    row = first_row(result)
    if row is None:
        if result["status"] == "empty":
            not_checked.append({"what": "job firmware",
                                "reason": "the job returned no row; the firmware is not "
                                          "known"})
        return None
    facts = {
        "manufacturer": text(row.get("Manufacturer")),
        "model": text(row.get("Model")),
        "bios_version": text(row.get("SMBIOSBIOSVersion")),
        "bios_date": text(row.get("ReleaseDate")),
    }
    missing = [name for name, value in facts.items() if value is None]
    if missing:
        not_checked.append({"what": "firmware fields",
                            "reason": f"Windows returned no value for {', '.join(missing)}"})
    return facts


def product_of(facts: dict, products: dict):
    """``(MSRC product name, None)`` or ``(None, reason)``."""
    version, arch = facts["display_version"], facts["architecture"]
    if version is None or arch is None:
        unread = [name for name, value in (("DisplayVersion", version),
                                           ("architecture", arch)) if value is None]
        return None, f"{' and '.join(unread)} not read"
    key = f"{version.upper()}|{arch.upper()}"
    if key not in products:
        return None, f"{key} is not in {PRODUCTS_FILE.name}"
    return products[key], None


# --- the findings file --------------------------------------------------------------
class FindingsError(Exception):
    """The --findings file could not be read or has the wrong shape."""


class ShapeError(Exception):
    """One finding has the wrong shape (the message says what is wrong)."""


def host_of(url: str):
    """The lower-case host of an ``https://`` address, or None when it has none.

    No URL library is used (the skill imports no network module): the authority ends at
    the first ``/``, ``\\``, ``?`` or ``#``; user info before ``@`` and a port are
    dropped, so ``https://support.microsoft.com@evil.example/`` has the host
    ``evil.example``.
    """
    authority = re.split(r"[/\\?#]", url[len("https://"):], maxsplit=1)[0]
    host = authority.rpartition("@")[2]
    host = re.sub(r":\d*$", "", host).rstrip(".").lower()
    return host if DOMAIN.fullmatch(host) else None


def is_date(value) -> bool:
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def fixed_pair(value):
    """``(build, UBR)`` of a ``fixed_build`` text, or None for any other shape."""
    match = FIXED_BUILD.fullmatch(value) if isinstance(value, str) else None
    return None if match is None else (int(match.group(1)), int(match.group(2)))


def check_finding(entry) -> dict:
    """The finding with its texts stripped and KB and CVE in upper case.

    Raises ``ShapeError`` with the problem when the shape is wrong.
    """
    if not isinstance(entry, dict):
        raise ShapeError("is not an object")
    kind = entry.get("kind")
    if not isinstance(kind, str) or kind not in KIND_FIELDS:
        raise ShapeError(f"has the unknown kind {kind!r} (known: "
                         f"{', '.join(KIND_FIELDS)})")
    expected = set(COMMON_FIELDS) | set(KIND_FIELDS[kind])
    missing = sorted(expected - set(entry))
    if missing:
        raise ShapeError(f"({kind}) has no {', '.join(missing)}")
    extra = sorted(set(entry) - expected)
    if extra:
        raise ShapeError(f"({kind}) has unknown fields {', '.join(extra)}")

    def required(name):
        value = text(entry[name])
        if value is None:
            raise ShapeError(f"({kind}) '{name}' is not a non-empty text")
        return value

    def optional(name):
        value = entry[name]
        if value is not None and text(value) is None:
            raise ShapeError(f"({kind}) '{name}' is neither a non-empty text nor null")
        return text(value)

    def a_date(name, nullable=True):
        value = entry[name]
        if value is None and nullable:
            return None
        if not is_date(value):
            raise ShapeError(f"({kind}) '{name}' is not a yyyy-MM-dd date"
                             f"{' or null' if nullable else ''}")
        return value

    url = entry["url"]
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ShapeError(f"({kind}) 'url' is not an https:// address")
    if host_of(url) is None:
        raise ShapeError(f"({kind}) 'url' has no host name")
    out = {"kind": kind, "url": url.strip(), "title": required("title"),
           "query": optional("query"), "published": a_date("published")}
    if kind == "update":
        month = entry["month"]
        if not isinstance(month, str) or not MONTH.fullmatch(month):
            raise ShapeError("(update) 'month' is not a yyyy-MM month")
        kb = required("kb")
        if not KB.fullmatch(kb):
            raise ShapeError("(update) 'kb' is not KB followed by digits")
        if fixed_pair(entry["fixed_build"]) is None:
            raise ShapeError("(update) 'fixed_build' is neither 10.0.<build>.<UBR> nor "
                             "<build>.<UBR>")
        if entry["release_type"] not in RELEASE_TYPES:
            raise ShapeError(f"(update) 'release_type' is not one of "
                             f"{', '.join(RELEASE_TYPES)}")
        cves = entry["cves"]
        if cves is not None and not isinstance(cves, list):
            raise ShapeError("(update) 'cves' is neither a list nor null")
        checked = None if cves is None else []
        for number, item in enumerate(cves or []):
            if (not isinstance(item, dict) or set(item) != {"cve", "severity"}
                    or not isinstance(item["cve"], str)
                    or not CVE.fullmatch(item["cve"].strip())
                    or (item["severity"] is not None and text(item["severity"]) is None)):
                raise ShapeError(f"(update) cves item {number} is not "
                                 f"{{cve: CVE-yyyy-n, severity: text or null}}")
            checked.append({"cve": item["cve"].strip().upper(),
                            "severity": text(item["severity"])})
        out.update(month=month, kb=kb.upper(), fixed_build=entry["fixed_build"],
                   release_type=entry["release_type"], cves=checked)
    elif kind == "exploited":
        cve = required("cve")
        if not CVE.fullmatch(cve):
            raise ShapeError("(exploited) 'cve' is not CVE-yyyy-n")
        out.update(cve=cve.upper(), vendor=required("vendor"), product=required("product"),
                   date_added=a_date("date_added", nullable=False),
                   due_date=a_date("due_date"), ransomware=optional("ransomware"))
    elif kind == "firmware":
        out.update(manufacturer=required("manufacturer"), model=required("model"),
                   version=required("version"), release_date=a_date("release_date"))
    return out


def load_findings(path: Path) -> dict:
    """``{"searches": {id: {status, reason}}, "findings": [checked finding]}``.

    Raises ``FindingsError`` naming the entry (counted from 0) on any bad shape.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise FindingsError(f"{path} could not be read: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"searches", "findings"}:
        raise FindingsError(f"{path} is not an object with exactly 'searches' and "
                            f"'findings'")
    if not isinstance(data["searches"], list) or not isinstance(data["findings"], list):
        raise FindingsError(f"{path}: 'searches' and 'findings' must be lists")
    searches = {}
    for index, entry in enumerate(data["searches"]):
        where = f"{path}: entry {index} of 'searches' (counted from 0)"
        if not isinstance(entry, dict) or set(entry) != {"id", "status", "reason"}:
            raise FindingsError(f"{where} does not have exactly id, status and reason")
        if entry["id"] not in SEARCH_IDS:
            raise FindingsError(f"{where} has the unknown id {entry['id']!r} (known: "
                                f"{', '.join(SEARCH_IDS)})")
        if entry["id"] in searches:
            raise FindingsError(f"{where} repeats the id {entry['id']!r}")
        if entry["status"] not in SEARCH_STATUSES:
            raise FindingsError(f"{where} has the status {entry['status']!r} (known: "
                                f"{', '.join(SEARCH_STATUSES)})")
        if entry["reason"] is not None and text(entry["reason"]) is None:
            raise FindingsError(f"{where}: 'reason' is neither a non-empty text nor null")
        if entry["status"] != "read" and text(entry["reason"]) is None:
            raise FindingsError(f"{where}: a {entry['status']} search needs a reason")
        searches[entry["id"]] = {"status": entry["status"], "reason": text(entry["reason"])}
    findings = []
    for index, entry in enumerate(data["findings"]):
        try:
            findings.append(check_finding(entry))
        except ShapeError as exc:
            raise FindingsError(f"{path}: entry {index} of 'findings' (counted from 0) "
                                f"{exc}") from exc
    return {"searches": searches, "findings": findings}


# --- findings compared with the machine ---------------------------------------------
def domains_for(finding: dict, sources: dict, manufacturer) -> list:
    domains = [d for source in sources["sources"] for d in source["domains"]]
    if finding["kind"] == "firmware" and manufacturer:
        for entry in sources["firmware_domains"]:
            if manufacturer.casefold().startswith(entry["manufacturer_prefix"].casefold()):
                domains.extend(entry["domains"])
    return domains


def is_listed(domain: str, domains: list) -> bool:
    """The domain is one of ``domains`` or a subdomain of one, never a mere suffix."""
    return any(domain == d or domain.endswith("." + d) for d in domains)


def search_states(searches: dict, not_checked: list) -> list:
    """``[{name, status, reason}]`` for every search; a missing one is ``missing``."""
    states = []
    for search_id in SEARCH_IDS:
        entry = searches.get(search_id)
        effect = NULL_WITHOUT[search_id]
        if entry is None:
            states.append({"name": search_id, "status": "missing",
                           "reason": "the findings file has no entry for this search"})
            not_checked.append({"what": f"search {search_id}",
                                "reason": f"the findings file has no entry for the search "
                                          f"{search_id}, so {effect}"})
            continue
        states.append({"name": search_id, **entry})
        if entry["status"] != "read":
            not_checked.append({"what": f"search {search_id}",
                                "reason": f"the search {search_id} is {entry['status']} "
                                          f"({entry['reason']}), so {effect}; its "
                                          f"findings are only in the detail file"})
    return states


def machine_pair(machine: dict):
    """``(CurrentBuild, UBR)`` of this machine as ints, or None when either is unread."""
    build, ubr = machine.get("build"), machine.get("ubr")
    if isinstance(build, str) and build.isdigit() and isinstance(ubr, int):
        return int(build), ubr
    return None


def applied_of(group: list, pair):
    """``(applied, applied_reason, note kind)``; only ``security`` releases count."""
    security = sorted({fixed_pair(f["fixed_build"]) for f in group
                       if f["release_type"] == "security"})
    if not security:
        return None, ("no security release of this month is in the findings (a preview "
                      "release is optional)"), "no_security"
    if pair is None:
        return None, "the build or UBR of this machine was not read", "no_build"
    same = [p for p in security if p[0] == pair[0]]
    if not same:
        return None, ("build mismatch: no security fixed build of this month is for the "
                      "build of this machine"), "mismatch"
    if all(pair >= p for p in same):
        return True, None, None
    if all(pair < p for p in same):
        return False, None, None
    return None, ("mixed: the build of this machine is at or above some security fixed "
                  "builds of this month and below others"), None


def build_updates(update_findings: list, machine: dict, not_checked: list,
                  msrc_read: bool):
    """Month items (newest first) and ``{month: set of CVEs}``. ``cve_count`` and
    ``critical_count`` are null when ``msrc`` was not read or no finding of the month
    has a ``cves`` list (a release-information row has none)."""
    pair = machine_pair(machine)
    hotfixes = machine.get("hotfixes")
    by_month = {}
    for finding in update_findings:
        by_month.setdefault(finding["month"], []).append(finding)
    items, month_cves, notes, uncounted = [], {}, {}, []
    for month in sorted(by_month, reverse=True):
        group = by_month[month]
        severities = {}
        for finding in group:
            for item in finding["cves"] or []:
                severities.setdefault(item["cve"], set()).add(
                    (item["severity"] or "").casefold())
        counted = msrc_read and any(f["cves"] is not None for f in group)
        if counted:
            month_cves[month] = set(severities)
        elif msrc_read:
            uncounted.append(month)
        kbs = sorted({f["kb"] for f in group})
        applied, reason, note = applied_of(group, pair)
        if note:
            notes.setdefault(note, []).append(month)
        items.append({
            "month": month,
            "kbs": kbs,
            "fixed_builds": [f"{b}.{u}" for b, u in
                             sorted({fixed_pair(f["fixed_build"]) for f in group})],
            "cve_count": len(severities) if counted else None,
            "critical_count": (sum(1 for s in severities.values() if "critical" in s)
                               if counted else None),
            "listed": all(f["listed"] for f in group),
            "kb_installed": None if hotfixes is None else [kb for kb in kbs if kb in hotfixes],
            "applied": applied,
            "applied_reason": reason,
        })
    texts = {
        "no_build": "the build or UBR of this machine was not read, so applied is null for "
                    "every month",
        "no_security": "no security release is in the findings for the months {}, so "
                       "applied is null for them",
        "mismatch": "no security fixed build is for the build of this machine in the "
                    "months {} (build mismatch), so applied is null for them",
    }
    if "no_build" in notes:
        not_checked.append({"what": "updates applied", "reason": texts["no_build"]})
    for kind in ("no_security", "mismatch"):
        if kind in notes:
            not_checked.append({"what": "updates applied",
                                "reason": texts[kind].format(", ".join(notes[kind]))})
    if uncounted:
        not_checked.append({"what": "updates cve_count",
                            "reason": f"no finding of the months {', '.join(uncounted)} "
                                      f"has a CVE list, so cve_count and critical_count "
                                      f"are null for them"})
    if items and hotfixes is None:
        not_checked.append({"what": "updates kb_installed",
                            "reason": "the hotfixes job was not read, so kb_installed is "
                                      "null for every month"})
    return items, month_cves


def build_exploited(findings: list, months: list, month_cves: dict):
    """``(exploited, kev_other)``: KEV entries inside and outside the update months."""
    applied = {item["month"]: item["applied"] for item in months}
    inside, outside, seen = [], [], set()
    for finding in findings:
        if finding["cve"] in seen:
            continue
        seen.add(finding["cve"])
        found = sorted(m for m, cves in month_cves.items() if finding["cve"] in cves)
        item = {key: finding[key] for key in KIND_FIELDS["exploited"]}
        item.update(url=finding["url"], listed=finding["listed"], in_updates=bool(found),
                    month=found[0] if found else None,
                    applied=(True if any(applied[m] is True for m in found)
                             else applied[found[0]] if found else None))
        (inside if found else outside).append(item)
    return inside, outside


def version_parts(bios_version: str) -> set:
    """The whole version, each part between characters outside [0-9A-Za-z.] and the last
    dotted part of each, in lower case."""
    parts = {bios_version.strip().casefold()}
    for member in TOKEN_SPLIT.split(bios_version):
        if member:
            parts.add(member.casefold())
            parts.add(member.rsplit(".", 1)[-1].casefold())
    parts.discard("")
    return parts


def without_v(part: str) -> str:
    """``v1.20`` and ``1.20`` are one version."""
    return part[1:] if re.fullmatch(r"v[0-9].*", part) else part


def is_same_version(page_version: str, bios_version: str) -> bool:
    """True when the whole version from the page, or one of its parts that holds a
    digit and a dot or is at least five characters long, is a part of the machine's
    version (a leading ``v`` ignored on both sides).

    ``1.45 (N3EET45W)`` from a page is the installed ``N3EET45W (1.45 )``, ``312`` is
    ``X515EA.312`` and ``F.20 Rev.A`` is ``F.20``; ``G.20`` is not ``F.20``, because a
    page part is taken whole and never cut at its last dot. A family code (``T70`` of
    ``T70 Ver. 01.17.00``) or a piece of a date (``2026``, ``20``) is too short to name
    the version alone, so the findings file gives the version alone (``SKILL.md``);
    the only part that holds a digit counts as the whole version (``BIOS 312``).
    """
    installed = {without_v(part) for part in version_parts(bios_version)}
    offered = {page_version.strip().casefold()}
    with_digit = [member.casefold() for member in TOKEN_SPLIT.split(page_version)
                  if any(ch.isdigit() for ch in member)]
    if len(with_digit) == 1:
        offered |= set(with_digit)
    offered |= {member for member in with_digit if "." in member or len(member) >= 5}
    return bool({without_v(part) for part in offered} & installed)


def build_firmware(findings: list, facts) -> list:
    """Firmware items; ``newer`` by release date only for a matching model and another
    version (version texts are never compared as numbers)."""
    items, seen = [], set()
    for finding in findings:
        key = firmware_key(finding)
        if key in seen:
            continue
        seen.add(key)
        model_matches = same_version = newer = None
        if facts is not None and facts["manufacturer"] and facts["model"]:
            model_matches = (finding["manufacturer"].casefold()
                             == facts["manufacturer"].casefold()
                             and finding["model"].casefold() == facts["model"].casefold())
        if facts is not None and facts["bios_version"]:
            same_version = is_same_version(finding["version"], facts["bios_version"])
        bios_date = facts["bios_date"] if facts is not None else None
        if model_matches is True and same_version is not None:
            if same_version:
                newer = False
            elif finding["release_date"] and is_date(bios_date):
                newer = finding["release_date"] > bios_date
        items.append({
            "manufacturer": finding["manufacturer"],
            "model": finding["model"],
            "version": finding["version"],
            "release_date": finding["release_date"],
            "url": finding["url"],
            "listed": finding["listed"],
            "model_matches": model_matches,
            "same_version": same_version,
            "newer": newer,
        })
    return items


def issue_key(item: dict) -> str:
    # One release health page lists several issues, so the address alone is not one issue.
    return item["url"] + "|" + item["title"].strip().casefold()


def build_issues(findings: list) -> list:
    items, seen = [], set()
    for finding in findings:
        if issue_key(finding) in seen:
            continue
        seen.add(issue_key(finding))
        items.append({"title": finding["title"], "published": finding["published"],
                      "url": finding["url"], "listed": finding["listed"]})
    return items


def fact_pattern(fact: str, prefix: str = ""):
    """A whole-token search for ``fact`` (with an optional ``prefix``), ignoring case.

    A dot that ends a sentence or starts a file extension (``.html``, ``.pdf``) is a
    boundary; a dot followed by a digit continues a version, so ``26200.6899`` is not
    found in ``26200.68991`` or ``26200.6899.1``. One ``v`` before the fact is part of
    it (``v1.54``), unless a letter or digit stands before that ``v`` (``xv1.54``).
    """
    return re.compile(r"(?<![0-9A-Za-z])(?<![0-9]\.)v?" + prefix + re.escape(fact)
                      + r"(?![0-9A-Za-z])(?!\.[0-9])", re.IGNORECASE)


def without_page_name(url: str, page_name) -> str:
    """``url`` with every KB page name ``page_name`` finds cut out of its path only.

    As in ``host_of``, no URL library: the path runs from the first ``/`` or ``\\``
    after ``https://`` to the first ``?`` or ``#``; the query and fragment are kept.
    """
    if page_name is None:
        return url
    head, sep, rest = url.partition("://")
    authority, path = re.match(r"([^/\\?#]*)(.*)", rest, re.DOTALL).groups()
    path, tail = re.match(r"([^?#]*)(.*)", path, re.DOTALL).groups()
    return head + sep + authority + page_name.sub("", path) + tail


def query_warnings(findings: list, machine: dict, not_checked: list) -> list:
    """``[{finding_id, reason}]``: a query or url holding a fact of this machine.

    The warning never carries the query.
    """
    pair = machine_pair(machine)
    build_pattern = None if pair is None else fact_pattern(f"{pair[0]}.{pair[1]}",
                                                           r"(?:10\.0\.)?")
    # KB pages name the build with hyphens (``...-kb5099901-os-build-26200-6899-...``,
    # ``...-kb5099901-os-builds-26200-6899-and-26100-6899-...``). That form warns in
    # every query, and in a url unless it stands only in the KB page name, in the
    # url's path, of the KB of an ``update`` finding or of ``machine.hotfixes``: the
    # page of that KB names its own build, which is no reading of this machine. The
    # page name is cut out of the path and the rest of the url is searched, so a
    # search address or the build again elsewhere in the url still warns.
    hyphen_pattern = None if pair is None else fact_pattern(f"{pair[0]}-{pair[1]}")
    page_kbs = sorted({kb[2:] for kb in
                       [*(f["kb"] for f in findings if f["kind"] == "update"),
                        *(machine.get("hotfixes") or [])]
                       if isinstance(kb, str) and KB.fullmatch(kb)})
    # After the KB, the words of the page name (``os-build``, ``os-builds``, or the
    # translated words of a localized page, each with a letter), then one build of five
    # digits and at most one more after one word (``-and-``, ``-i-``, ``-und-``), so the
    # build again right after the page name stays in the url.
    page_build = r"[0-9]{5}-[0-9]+"
    page_word = r"[^-/\\?#\s]*[^\W\d_][^-/\\?#\s]*-"
    page_name = re.compile(r"(?<![0-9A-Za-z])(?:kb)?(?:" + "|".join(page_kbs)
                           + rf")[-/](?:{page_word})+{page_build}"
                           rf"(?:-{page_word}{page_build})?(?![0-9])",
                           re.IGNORECASE) if page_kbs else None
    bios = ((machine.get("firmware") or {}).get("bios_version") or "").strip()
    # The whole version and each of its members, each only when it holds a digit and
    # is at least four characters long (``N3EET45W`` of ``N3EET45W (1.45 )``): a member
    # alone names the version as well. Shorter texts such as ``HP``, ``45`` or a whole
    # version ``1.0`` are too common to warn about. A leading ``v`` is dropped, since
    # ``fact_pattern`` finds the fact with or without one (``V1.20`` and ``1.20``).
    bios_facts = {without_v(f.casefold()) for f in [bios, *TOKEN_SPLIT.split(bios)]
                  if len(without_v(f.casefold())) >= 4 and any(c.isdigit() for c in f)}
    bios_patterns = [fact_pattern(fact) for fact in sorted(bios_facts)]
    found_kbs = {f["kb"] for f in findings if f["kind"] == "update"}
    own_kbs = set()
    for kb in machine.get("hotfixes") or []:
        if kb not in found_kbs and KB.fullmatch(kb):
            own_kbs.update({kb.upper(), kb[2:]})
    warnings = []
    for finding in findings:
        texts = [t for t in (finding["query"], finding["url"]) if t]
        reasons = []
        query, url = finding["query"] or "", finding["url"] or ""
        if build_pattern is not None and (any(build_pattern.search(t) for t in texts)
                                          or hyphen_pattern.search(query)
                                          or hyphen_pattern.search(
                                              without_page_name(url, page_name))):
            reasons.append("build")
        if any(pattern.search(t) for pattern in bios_patterns for t in texts):
            reasons.append("bios_version")
        if any(fact_pattern(kb).search(finding["query"] or "") for kb in own_kbs):
            reasons.append("kb")
        for reason in reasons:
            warnings.append({"finding_id": finding["id"], "reason": reason})
            not_checked.append({
                "what": f"query warning {finding['id']}",
                "reason": f"the query or url of finding {finding['id']} holds the "
                          f"{reason} of this machine; check what was sent before the "
                          f"next search",
            })
    return warnings


def firmware_key(item: dict) -> str:
    return "|".join(item[k].strip().casefold() for k in ("manufacturer", "model", "version"))


BASELINE_KEYS = {
    "updates": lambda item: (item["month"], {"month": item["month"]}),
    "exploited": lambda item: (item["cve"], {"cve": item["cve"]}),
    "firmware": lambda item: (firmware_key(item), {"manufacturer": item["manufacturer"],
                                                   "model": item["model"],
                                                   "version": item["version"]}),
    "issues": lambda item: (issue_key(item), {"url": item["url"], "title": item["title"]}),
}


def compare_findings(doc: dict, machine: dict, sources: dict, not_checked: list) -> dict:
    """Every list of the findings compared with the machine; ``None`` for a list whose
    search was not read. Also the detail ``findings``, ``kev_other``, the search
    states and the query warnings."""
    manufacturer = (machine.get("firmware") or {}).get("manufacturer")
    findings = []
    for number, finding in enumerate(doc["findings"], start=1):
        domain = host_of(finding["url"])
        findings.append({"id": f"w{number}", **finding, "domain": domain,
                         "listed": is_listed(domain, domains_for(finding, sources,
                                                                 manufacturer))})
    states = search_states(doc["searches"], not_checked)
    read = {s["name"] for s in states if s["status"] == "read"}
    of_kind = {kind: [f for f in findings if f["kind"] == kind] for kind in KIND_FIELDS}

    months, month_cves = build_updates(of_kind["update"], machine,
                                       not_checked if "release-info" in read else [],
                                       "msrc" in read)
    exploited, kev_other = build_exploited(of_kind["exploited"], months, month_cves)
    # Without the CVE lists (msrc) or the months (release-info) no KEV entry can be
    # placed inside or outside the update months.
    if "kev" in read and "msrc" not in read:
        not_checked.append({"what": "exploited",
                            "reason": "no CVE list of the update months (msrc not read), "
                                      "so exploited is null"})
    elif "kev" in read and "release-info" not in read:
        not_checked.append({"what": "exploited",
                            "reason": "no update months (release-info not read), so "
                                      "exploited is null"})
    lists = {
        "updates": months,
        "exploited": exploited,
        "firmware": build_firmware(of_kind["firmware"], machine.get("firmware")),
        "issues": build_issues(of_kind["issue"]),
    }
    for name in FINDINGS_FIELDS:
        if SEARCH_OF_LIST[name] not in read:
            lists[name] = None
    if not {"kev", "msrc", "release-info"} <= read:
        lists["exploited"] = None
        kev_other = None
    for name, letter in (("updates", "u"), ("exploited", "k"), ("firmware", "f"),
                         ("issues", "i")):
        if lists[name] is not None:
            lists[name] = [{"id": f"{letter}{number}", **item}
                           for number, item in enumerate(lists[name], start=1)]
    if kev_other is not None:
        # kev_other continues the k numbering, so the ids cut from exploited stay k1..kN.
        first = len(lists["exploited"] or []) + 1
        kev_other = [{"id": f"k{number}", **item}
                     for number, item in enumerate(kev_other, start=first)]
    return {
        "searches": states,
        "findings": findings,
        "lists": lists,
        "kev_other": kev_other,
        "query_warnings": query_warnings(findings, machine, not_checked),
    }


# --- baseline ---------------------------------------------------------------------------
def apply_baseline(state: Path, lists: dict, kev_other, now: datetime,
                   not_checked: list):
    """Mark ``new`` on every item and save the union of the saved and current keys.

    Returns ``(comparison, baseline info)``. A list that is None was not read: it is
    not compared and its saved keys stay. With no list read the baseline is not
    written, so a run without findings never rotates ``previous``.
    """
    loaded = baseline.load(state, SKILL, False)
    previous = loaded["sources"] if loaded["status"] == "read" else {}
    if any("|" not in key for key in (previous.get("issues") or {})):
        # Issues saved by their address alone, before one page could hold several:
        # those keys cannot be compared, so issues start again without a baseline.
        previous = {name: keys for name, keys in previous.items() if name != "issues"}
    statuses, current = {}, {}
    for name in BASELINE_SOURCES:
        items = lists[name]
        if name == "exploited" and items is not None:
            items = items + (kev_other or [])
        if items is None:
            statuses[name] = "not_read"
            continue
        current[name] = dict(BASELINE_KEYS[name](item) for item in items)
        statuses[name] = "read" if current[name] else "empty"
    comparison = {name: baseline.comparison_state(previous, name, statuses[name])
                  for name in BASELINE_SOURCES}
    for name in BASELINE_SOURCES:
        items = lists[name]
        if items is None:
            continue
        if name == "exploited":
            items = items + (kev_other or [])
        added = None
        if comparison[name] == "compared":
            added = set(baseline.compare(previous[name], current[name], ())["added"])
        for item in items:
            item["new"] = None if added is None else BASELINE_KEYS[name](item)[0] in added

    reasons = []
    if loaded["status"] == "unreadable":
        reasons.append(loaded["reason"])
        not_checked.append({"what": "baseline",
                            "reason": f"the baseline could not be read, so nothing was "
                                      f"compared (the file is kept): {loaded['reason']}"})
    save_reason = None
    if current:
        union = {name: {**previous.get(name, {}), **items}
                 for name, items in current.items()}
        save_reason = baseline.save(state, baseline.baseline_name(SKILL, False), {
            "schema_version": baseline.SCHEMA_VERSION,
            "skill": SKILL,
            "created_at": now.isoformat(),
            "elevated": False,
            "sources": baseline.merge_sources(previous, union, statuses),
        })
        if save_reason is not None:
            reasons.append(f"not saved: {save_reason}")
            not_checked.append({"what": "baseline save",
                                "reason": f"this run's baseline was not saved: "
                                          f"{save_reason}"})
    else:
        reasons.append("no list was compared (a search was not read, or exploited "
                       "lacked the msrc or release-info search), so the baseline was "
                       "left as it was")
    compared = loaded["status"] == "read"
    info = {
        "status": "compared" if compared else loaded["status"],
        "created_at": loaded["created_at"] if compared else None,
        "age_days": baseline.age_days(loaded["created_at"], now) if compared else None,
        "saved": bool(current) and save_reason is None,
        "reason": "; ".join(reasons) if reasons else None,
    }
    return comparison, info


# --- summary budget -------------------------------------------------------------------
def most_that_fit(fits, high: int) -> int:
    """The largest n in 0..high with ``fits(n)``, by bisection; ``fits(0)`` holds."""
    low = 0
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    return low


def fit_budget(summary: dict) -> str:
    """The summary text within SUMMARY_MAX_CHARS.

    ``issues`` is cut from its end first; only when the summary without any issue is
    still too long is ``exploited`` cut from its end, and then as many issues as fit
    come back. ``truncated`` and ``truncated_exploited`` count the items cut, and a
    ``not_checked`` item names each cut list. Notes are in place while measuring.
    """
    full = {"issues": summary["issues"], "exploited": summary["exploited"]}
    counts = {"issues": "truncated", "exploited": "truncated_exploited"}
    notes = {name: {"what": f"{name} cut from the summary", "reason": ""} for name in full}

    def fits(kept_issues: int, kept_exploited: int) -> bool:
        for name, kept in (("issues", kept_issues), ("exploited", kept_exploited)):
            if full[name] is None:
                continue
            summary[name] = full[name][:kept]
            summary[counts[name]] = len(full[name]) - kept
            notes[name]["reason"] = (f"{summary[counts[name]]} {name} items at the end of "
                                     f"the list are only in the detail file; summary "
                                     f"budget {SUMMARY_MAX_CHARS} characters")
        return len(dump(summary)) <= SUMMARY_MAX_CHARS

    n_issues, n_exploited = len(full["issues"] or []), len(full["exploited"] or [])
    if fits(n_issues, n_exploited):
        return dump(summary)
    added = [notes[name] for name in full if full[name]]
    summary["not_checked"].extend(added)
    if fits(0, n_exploited):
        fits(most_that_fit(lambda n: fits(n, n_exploited), n_issues), n_exploited)
    elif fits(0, 0):
        kept = most_that_fit(lambda n: fits(0, n), n_exploited)
        fits(most_that_fit(lambda n: fits(n, kept), n_issues), kept)
    else:
        # Something else is too long: cutting would lose the lists for nothing.
        fits(n_issues, n_exploited)
        for note in added:
            summary["not_checked"].remove(note)
        summary["not_checked"].append({
            "what": "summary budget",
            "reason": f"the summary exceeds {SUMMARY_MAX_CHARS} characters even without "
                      f"issues and exploited and was not cut",
        })
        return dump(summary)
    for name in full:
        if notes[name] in summary["not_checked"] and not summary[counts[name]]:
            summary["not_checked"].remove(notes[name])
    return dump(summary)


# --- machine functions ----------------------------------------------------------------
def default_run_ps(job, script, out_path):
    return psrun.default_run_ps(job, script, out_path)


# --- command line ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=None, help=datadir.HELP)
    parser.add_argument("--detail", metavar="ID",
                        help="print one item of the newest detail file and exit")
    parser.add_argument("--detail-file", metavar="PATH",
                        help="with --detail: read this detail file (the summary's "
                             "detail_file) instead of the newest one")
    parser.add_argument("--findings", metavar="PATH",
                        help="compare the findings file the model wrote "
                             "({searches, findings}) with this machine")
    return parser


def show_detail(work: Path, item_id: str, detail_file: Path | None = None) -> int:
    if detail_file is not None:
        newest = detail_file
    else:
        files = sorted(work.glob("advice-*.detail.json"), key=lambda p: p.name)
        if not files:
            print(f"no detail file in {work}; run the collection first", file=sys.stderr)
            return 1
        newest = files[-1]
    try:
        detail = json.loads(newest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"{newest} could not be read: {type(exc).__name__}: {exc}", file=sys.stderr)
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


def main(argv=None, run_ps=None, now=None) -> int:
    """Collect the machine facts and summarise, or print one detail item with --detail.

    ``run_ps`` is the only input from the machine; tests inject a fake.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data_dir = datadir.resolve(args.data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    work = data_dir / "work"
    if args.detail_file is not None and args.detail is None:
        parser.error("--detail-file needs --detail")
    if args.detail is not None:
        detail_file = None if args.detail_file is None else Path(args.detail_file).resolve()
        return show_detail(work, args.detail, detail_file)

    try:
        products = load_products(PRODUCTS_FILE)
        source_list = load_sources(SOURCES_FILE)
    except DataFileError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    doc = None
    if args.findings is not None:
        try:
            doc = load_findings(Path(args.findings).resolve())
        except FindingsError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    run_ps = run_ps or default_run_ps
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")  # UTC, so names sort by time
    work.mkdir(parents=True, exist_ok=True)
    summary_file = work / f"advice-{stamp}.summary.json"
    detail_file = work / f"advice-{stamp}.detail.json"

    sources, not_checked = [], []
    results = collect(run_ps, work, stamp, sources, not_checked)
    facts = os_facts(results["os_version"], not_checked)
    product, product_reason = product_of(facts, products)
    machine = {
        **facts,
        "product": product,
        "product_reason": product_reason,
        "hotfixes": hotfix_list(results["hotfixes"], not_checked),
        "firmware": firmware_facts(results["firmware"], not_checked),
    }
    if doc is None:
        not_checked.append({"what": "web search",
                            "reason": "the search was not done: no --findings file was "
                                      "given, so updates, exploited vulnerabilities, "
                                      "firmware and known issues are not compared with "
                                      "this machine"})
        compared = {"searches": None, "findings": None,
                    "lists": {field: None for field in FINDINGS_FIELDS},
                    "kev_other": None, "query_warnings": None}
    else:
        compared = compare_findings(doc, machine, source_list, not_checked)
    lists, kev_other = compared["lists"], compared["kev_other"]
    comparison, baseline_info = apply_baseline(data_dir / "state", lists, kev_other, now,
                                               not_checked)

    detail = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "generated_at": now.isoformat(),
        "sources": sources,
        "searches": compared["searches"],
        "machine": machine,
        "comparison": comparison,
        **lists,
        "kev_other": kev_other,
        "query_warnings": compared["query_warnings"],
        "findings": compared["findings"],
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
        "truncated": 0,
        "truncated_exploited": 0,
        "baseline": baseline_info,
        "comparison": comparison,
        "searches": compared["searches"],
        "machine": machine,
        "query_warnings": compared["query_warnings"],
        "kev_other_count": None if kev_other is None else len(kev_other),
        **lists,
    }
    text_out = fit_budget(summary)
    summary_file.write_text(text_out, encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

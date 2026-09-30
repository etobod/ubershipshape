"""Load and validate the ush-settings catalogue (``data/settings-catalogue.json``).

The catalogue is data: every setting the skill reads, the values it expects and, where a
safe change exists, how a paste-ready block would apply it. ``load(path)`` returns the list
of entries or raises ``CatalogueError`` listing every problem found (not only the first),
each problem naming the entry it belongs to.

Rules checked here, beyond field shapes and types:

- ``id`` matches ``[a-z][a-z0-9_]*`` in full and is unique;
- ``applies_if`` conditions do not form a cycle;
- ``area`` and ``level`` come from fixed sets;
- ``read.type`` is known and carries exactly its parameters;
- ``apply`` matches the read type (a registry ``location`` index must be in range);
- ``manual`` is required when ``apply`` is null and ``expected`` is not;
- ``rollback_manual`` is required for an ``appx`` entry with ``apply``;
- ``applies_if.entry`` names another entry of the catalogue;
- ``apply`` is refused for a read type that only works with administrator rights: the
  change must be verifiable by a normal (non-elevated) re-run;
- ``apply`` is refused on an HKCU policy key (``Software\\Policies`` or
  ``Software\\Microsoft\\Windows\\CurrentVersion\\Policies``): writing there
  needs administrator rights, and an elevated shell may write another account's HKCU.
"""

import json
import re
from pathlib import Path

SCHEMA_VERSION = 1

ID_RE = re.compile(r"[a-z][a-z0-9_]*")
AREAS = {"privacy", "telemetry", "ads", "ai", "updates", "security", "power", "network",
         "permissions", "storage"}
LEVELS = {"standard", "strict"}
HIVES = {"HKLM", "HKCU"}
ROLES = {"policy", "preference"}
REGISTRY_KINDS = {"DWord", "String"}
START_TYPES = {"Automatic", "AutomaticDelayed", "Manual", "Disabled"}
FIREWALL_PROFILES = {"Domain", "Private", "Public"}
DEFENDER_FIELDS = {"AMRunningMode", "RealTimeProtectionEnabled", "IsTamperProtected"}
POWER_LINES = {"ac", "dc"}

REQUIRED_KEYS = ("id", "area", "level", "title", "rationale", "read", "expected", "apply")
OPTIONAL_KEYS = ("default", "manual", "applies_if", "rollback_manual")

# Read types whose ``default`` is meaningful: a value missing everywhere means "default".
TYPES_WITH_DEFAULT = {"registry", "wifi_adapter_value"}
# Read types that only work with administrator rights; they may never carry ``apply``.
ADMIN_ONLY_TYPES = {"shadow_storage"}
# Read types for which no safe scripted change exists.
NO_APPLY_TYPES = {"security_center_av", "defender_status", "device_guard", "power_scheme",
                  "dns", "winhttp_proxy", "delivery_optimization", "shadow_storage"}

# HKCU policy roots: writing under them needs administrator rights.
HKCU_POLICY_ROOTS = ("software\\policies",
                     "software\\microsoft\\windows\\currentversion\\policies")


class CatalogueError(Exception):
    """The catalogue could not be loaded; ``problems`` lists every problem found."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("invalid settings catalogue:\n" + "\n".join(
            f"- {problem}" for problem in self.problems))


def _one_of(value, allowed):
    """True when ``value`` is text from ``allowed``; a JSON list or object never is."""
    return isinstance(value, str) and value in allowed


def _is_int(value):
    return type(value) is int


def _is_scalar(value):
    return value is None or isinstance(value, (str, bool, int))


def _nonempty_str(value):
    return isinstance(value, str) and bool(value.strip())


def _param_str(params, key, problems, label, allowed=None):
    value = params.get(key)
    if not _nonempty_str(value):
        problems.append(f"{label}: read.{key} must be a non-empty string")
    elif allowed is not None and not _one_of(value, allowed):
        problems.append(f"{label}: read.{key} {value!r} is not one of {sorted(allowed)}")


def _check_location(location, index, label, problems):
    where = f"{label}: read.locations[{index}]"
    if not isinstance(location, dict):
        problems.append(f"{where} must be an object")
        return
    extra = set(location) - {"hive", "path", "name", "role", "map"}
    if extra:
        problems.append(f"{where}: unknown keys {sorted(extra)}")
    if not _one_of(location.get("hive"), HIVES):
        problems.append(f"{where}: hive must be one of {sorted(HIVES)}")
    path = location.get("path")
    if not _nonempty_str(path):
        problems.append(f"{where}: path must be a non-empty string")
    elif path.startswith("\\") or path.endswith("\\"):
        problems.append(f"{where}: path must not start or end with a backslash")
    if not _nonempty_str(location.get("name")):
        problems.append(f"{where}: name must be a non-empty string")
    if not _one_of(location.get("role"), ROLES):
        problems.append(f"{where}: role must be one of {sorted(ROLES)}")
    if "map" in location:
        mapping = location["map"]
        if not isinstance(mapping, dict) or not mapping:
            problems.append(f"{where}: map must be a non-empty object")
        else:
            for key, value in mapping.items():
                if not isinstance(key, str):
                    problems.append(f"{where}: map key {key!r} must be text")
                if not _is_scalar(value) or value is None:
                    problems.append(f"{where}: map value for {key!r} must be a scalar")


# Parameters of each read type besides ``type``; a callable checks them.
def _read_registry(read, label, problems):
    locations = read.get("locations")
    if not isinstance(locations, list) or not locations:
        problems.append(f"{label}: read.locations must be a non-empty list")
        return
    for index, location in enumerate(locations):
        _check_location(location, index, label, problems)


def _read_named(read, label, problems):
    _param_str(read, "name", problems, label)


def _read_firewall(read, label, problems):
    _param_str(read, "profile", problems, label, FIREWALL_PROFILES)


def _read_defender(read, label, problems):
    _param_str(read, "field", problems, label, DEFENDER_FIELDS)


def _read_device_guard(read, label, problems):
    if not _is_int(read.get("service")):
        problems.append(f"{label}: read.service must be an integer")


def _read_powercfg(read, label, problems):
    _param_str(read, "subgroup", problems, label)
    _param_str(read, "setting", problems, label)
    _param_str(read, "power", problems, label, POWER_LINES)


def _read_none(read, label, problems):
    return None


READ_TYPES = {
    "registry": (("locations",), _read_registry),
    "wifi_adapter_value": (("name",), _read_named),
    "service": (("name",), _read_named),
    "firewall_profile": (("profile",), _read_firewall),
    "security_center_av": ((), _read_none),
    "defender_status": (("field",), _read_defender),
    "device_guard": (("service",), _read_device_guard),
    "power_scheme": ((), _read_none),
    "powercfg_setting": (("subgroup", "setting", "power"), _read_powercfg),
    "dns": ((), _read_none),
    "winhttp_proxy": ((), _read_none),
    "appx": (("name",), _read_named),
    "optional_feature": (("name",), _read_named),
    "delivery_optimization": ((), _read_none),
    "shadow_storage": ((), _read_none),
}


def _check_value_kind(apply, label, problems):
    kind = apply.get("kind")
    value = apply.get("value")
    if not _one_of(kind, REGISTRY_KINDS):
        problems.append(f"{label}: apply.kind must be one of {sorted(REGISTRY_KINDS)}")
    elif kind == "DWord" and not (_is_int(value) and 0 <= value <= 0xFFFFFFFF):
        problems.append(f"{label}: apply.value must be a 32-bit unsigned integer for DWord")
    elif kind == "String" and not isinstance(value, str):
        problems.append(f"{label}: apply.value must be text for String")


def _check_keys(apply, allowed, label, problems):
    if set(apply) != set(allowed):
        problems.append(f"{label}: apply must have exactly the keys {sorted(allowed)}, "
                        f"not {sorted(apply)}")
        return False
    return True


def _check_apply(entry, read_type, label, problems):
    apply = entry.get("apply")
    if apply is None:
        return
    if read_type in ADMIN_ONLY_TYPES:
        problems.append(f"{label}: apply must be null for {read_type}: it is read only with "
                        "administrator rights, so a change could not be read back in a "
                        "normal shell")
        return
    if read_type in NO_APPLY_TYPES:
        problems.append(f"{label}: apply must be null for read type {read_type}")
        return
    if not isinstance(apply, dict):
        problems.append(f"{label}: apply must be an object or null")
        return

    if read_type == "registry":
        if "remove" in apply:
            if not _check_keys(apply, ("location", "remove"), label, problems):
                return
            if apply["remove"] is not True:
                problems.append(f"{label}: apply.remove must be true")
        elif not _check_keys(apply, ("location", "value", "kind"), label, problems):
            return
        else:
            _check_value_kind(apply, label, problems)
        locations = entry["read"].get("locations")
        index = apply.get("location")
        if not _is_int(index):
            problems.append(f"{label}: apply.location must be an integer index")
        elif not isinstance(locations, list) or not 0 <= index < len(locations):
            problems.append(f"{label}: apply.location {index} is out of range of "
                            "read.locations")
        else:
            target = locations[index]
            if isinstance(target, dict) and target.get("hive") == "HKCU":
                path = str(target.get("path", "")).lower()
                if any(path == root or path.startswith(root + "\\")
                       for root in HKCU_POLICY_ROOTS):
                    problems.append(f"{label}: apply targets an HKCU policy key: "
                                    "writing there needs administrator rights and an "
                                    "elevated shell may write another account's HKCU")
    elif read_type == "wifi_adapter_value":
        if _check_keys(apply, ("value", "kind"), label, problems):
            _check_value_kind(apply, label, problems)
    elif read_type == "service":
        if _check_keys(apply, ("start_type",), label, problems) and \
                not _one_of(apply["start_type"], START_TYPES):
            problems.append(f"{label}: apply.start_type must be one of {sorted(START_TYPES)}")
    elif read_type == "firewall_profile":
        if _check_keys(apply, ("enabled",), label, problems) and \
                not isinstance(apply["enabled"], bool):
            problems.append(f"{label}: apply.enabled must be true or false")
    elif read_type == "powercfg_setting":
        if _check_keys(apply, ("value",), label, problems) and not _is_int(apply["value"]):
            problems.append(f"{label}: apply.value must be an integer")
    elif read_type == "appx":
        if _check_keys(apply, ("remove",), label, problems) and apply["remove"] is not True:
            problems.append(f"{label}: apply.remove must be true")
    elif read_type == "optional_feature":
        if _check_keys(apply, ("state",), label, problems) and apply["state"] != "Disabled":
            problems.append(f"{label}: apply.state must be 'Disabled'")


def _check_entry(entry, label, problems):
    """Check one entry on its own; cross-entry rules are in ``_validate``."""
    missing = [key for key in REQUIRED_KEYS if key not in entry]
    if missing:
        problems.append(f"{label}: missing keys {missing}")
    extra = set(entry) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS)
    if extra:
        problems.append(f"{label}: unknown keys {sorted(extra)}")

    if not _one_of(entry.get("area"), AREAS):
        problems.append(f"{label}: area {entry.get('area')!r} is not one of {sorted(AREAS)}")
    if not _one_of(entry.get("level"), LEVELS):
        problems.append(f"{label}: level {entry.get('level')!r} is not one of "
                        f"{sorted(LEVELS)}")
    for key in ("title", "rationale"):
        if key in entry and not _nonempty_str(entry[key]):
            problems.append(f"{label}: {key} must be a non-empty string")
    for key in ("manual", "rollback_manual"):
        if key in entry and not _nonempty_str(entry[key]):
            problems.append(f"{label}: {key} must be a non-empty string when present")

    expected = entry.get("expected")
    if expected is not None:
        if not isinstance(expected, list) or not expected:
            problems.append(f"{label}: expected must be null or a non-empty list")
        elif not all(_is_scalar(value) and value is not None for value in expected):
            problems.append(f"{label}: expected values must be scalars")

    read = entry.get("read")
    read_type = None
    if not isinstance(read, dict):
        problems.append(f"{label}: read must be an object")
    else:
        read_type = read.get("type")
        if not _one_of(read_type, READ_TYPES):
            problems.append(f"{label}: unknown read type {read_type!r}")
            read_type = None
        else:
            params, check = READ_TYPES[read_type]
            extra = set(read) - {"type"} - set(params)
            if extra:
                problems.append(f"{label}: unknown read parameters {sorted(extra)} for "
                                f"{read_type}")
            check(read, label, problems)

    if read_type is not None:
        if read_type in TYPES_WITH_DEFAULT:
            if "default" not in entry:
                problems.append(f"{label}: default is required for read type {read_type} "
                                "(null means unknown)")
            elif not _is_scalar(entry["default"]):
                problems.append(f"{label}: default must be a scalar or null")
        elif "default" in entry:
            problems.append(f"{label}: default is only allowed for "
                            f"{sorted(TYPES_WITH_DEFAULT)}")
        _check_apply(entry, read_type, label, problems)
        if read_type == "appx" and entry.get("apply") is not None \
                and "rollback_manual" not in entry:
            problems.append(f"{label}: rollback_manual is required for appx with apply")
        if read_type != "appx" and "rollback_manual" in entry:
            problems.append(f"{label}: rollback_manual is only for appx entries")

    if "apply" in entry and entry["apply"] is None and expected is not None \
            and "manual" not in entry:
        problems.append(f"{label}: manual is required when apply is null and expected is set")


def _validate(data):
    problems = []
    if not isinstance(data, dict):
        return ["catalogue: top level must be an object"]
    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"catalogue: schema_version must be {SCHEMA_VERSION}")
    extra = set(data) - {"schema_version", "entries"}
    if extra:
        problems.append(f"catalogue: unknown top-level keys {sorted(extra)}")
    entries = data.get("entries")
    if not isinstance(entries, list):
        problems.append("catalogue: entries must be a list")
        return problems

    seen = set()
    all_ids = {entry.get("id") for entry in entries
               if isinstance(entry, dict) and isinstance(entry.get("id"), str)}
    conditions = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entry #{index}: must be an object")
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and ID_RE.fullmatch(entry_id):
            label = f"entry {entry_id}"
            if entry_id in seen:
                problems.append(f"{label}: duplicate id")
            seen.add(entry_id)
        else:
            label = f"entry #{index} (id {entry_id!r})"
            problems.append(f"{label}: id must match {ID_RE.pattern}")
        _check_entry(entry, label, problems)

        if "applies_if" in entry:
            condition = entry["applies_if"]
            if not isinstance(condition, dict) or set(condition) != {"entry", "in"}:
                problems.append(f"{label}: applies_if must be {{entry, in}}")
            else:
                target = condition["entry"]
                if not isinstance(target, str):
                    problems.append(f"{label}: applies_if.entry must be an entry id")
                elif target == entry_id:
                    problems.append(f"{label}: applies_if refers to itself")
                elif target not in all_ids:
                    problems.append(f"{label}: applies_if.entry {target!r} is not in the "
                                    "catalogue")
                elif isinstance(entry_id, str):
                    conditions[entry_id] = target
                values = condition["in"]
                if not isinstance(values, list) or not values \
                        or not all(_is_scalar(v) and v is not None for v in values):
                    problems.append(f"{label}: applies_if.in must be a non-empty list of "
                                    "scalars")
    problems.extend(_cycle_problems(conditions))
    return problems


def _cycle_problems(conditions):
    """Name each ``applies_if`` cycle longer than one entry (self-reference is checked apart)."""
    problems = []
    reported = set()
    for start in sorted(conditions):
        path = [start]
        current = conditions[start]
        while current in conditions and current not in path:
            path.append(current)
            current = conditions[current]
        if current in path:
            cycle = path[path.index(current):]
            if len(cycle) > 1 and not reported.intersection(cycle):
                reported.update(cycle)
                problems.append("entries " + " -> ".join(cycle + [current])
                                + ": applies_if forms a cycle")
    return problems


def load(path):
    """Return the catalogue entries from ``path`` (str or Path), or raise CatalogueError."""
    path = Path(path).absolute()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogueError([f"catalogue: cannot read {path}: {exc}"]) from exc
    problems = _validate(data)
    if problems:
        raise CatalogueError(problems)
    return data["entries"]

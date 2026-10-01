"""Invented PowerShell results and helpers for the "added to the system" sources of
ush-inventory (plan 052, milestone M2).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``comparison``,
``not_checked``, item ``key``/``id``/``own``, the ``admin`` flag of ``run_main`` and
``collect``) is described in ``fakes.py``; the M1 helpers in ``fakes_components.py``.

Job result shapes assumed here (the plan leaves the exact PowerShell rows open; every
key is lowercase ASCII, as the plan names the ``hosts`` result):

- ``firewall_rules``: a list, one row per store,
  ``{store: "local"|"app_iso"|"policy", exists: bool, values: [{name, data}]}``.
  ``exists: false`` is a missing key (no rules in that store, not an error). ``values``
  may be a single object instead of a list (``ConvertTo-Json``). A key that could not be
  read fails the whole job (non-zero exit), so the source is ``unreadable``.
- ``root_certificates``: a list, one row per store,
  ``{store: "machine_root"|"machine_policy"|"enterprise"|"user_root"|"authroot",
  exists: bool, certificates: [{thumbprint, details}]}``; ``details`` is
  ``{subject, issuer, not_before, not_after, serial}`` (dates ``yyyy-MM-dd``) or ``null`` when the
  ``Cert:`` provider had no such certificate or threw. ``certificates`` may be a single
  object.
- ``hosts``: one object ``{raw_dir, expanded_dir, exists, text}``; ``text`` is ``null``
  when the file does not exist.
- ``administrators``: one object ``{method: "local_group_member"|"adsi", current_sid,
  members: [{sid, name, object_class, principal_source, is_user, enabled,
  enabled_error}]}``; ``object_class`` is in the system language. ``is_user`` is
  ``false`` when ``Get-LocalUser`` found no user with the SID, ``true`` when it did,
  else ``null``. ``enabled_error`` is the text of a failed ``Get-LocalUser``
  (``enabled`` then ``null``), else ``null``. ``members`` may be a single object. Both methods failing is a
  failed job.
- ``defender_exclusions``: one object ``{method: "preference"|"registry", path,
  extension, process, ip, policy, policy_error}``; ``path`` ... ``ip`` are lists of
  strings (or a single string); ``policy`` is ``{path, extension, process, ip}`` with the
  value names under the policy key, or ``null`` with ``policy_error`` the reason.

Summary and detail shapes assumed (from the plan's M2 text):

- ``additions`` is always in the summary: a list (ids ``x..``, items ``{id, key, kind,
  ...}``, only ``own: false``) or ``null`` when all five M2 sources are unreadable. The
  detail file has a full ``additions`` section with every item, ``own`` and
  ``unread_fields``.
- ``hosts_file`` is always in the summary: ``{exists, path_is_default}`` plus
  ``unread_fields`` when the ``hosts`` source is unreadable.
- ``own_counts.firewall_rules`` is ``{local, app_iso, policy}``;
  ``own_counts.root_certificates`` a number; ``truncated_additions`` a number.
- The ``method`` of ``administrators`` and ``defender_exclusions`` is found on that
  source's entry in ``sources`` (summary or detail file), or on a ``<source>`` object of
  the detail file.
- ``parse_firewall_rule(text)`` returns a dict with the rule fields, ``own`` and
  ``unread_fields``; if it takes a second required argument, it is the
  ``firewall_builtin`` pattern of ``windows-own.json``. ``parse_hosts(text)`` returns the
  entries as a list (or a dict keyed by entry) of ``{address, hostname, line, ...}``;
  lines are numbered from 1.

Every value here is invented; nothing comes from a machine. SIDs are
``S-1-5-21-0-0-0-...``; directories are the Windows defaults, not readings. The only
real thumbprints are the public Microsoft root thumbprints listed in the plan.
"""

from .fakes import ok
from .fakes_components import ComponentsTestCase

M2_SOURCES = (
    "firewall_rules",
    "root_certificates",
    "hosts",
    "administrators",
    "defender_exclusions",
)

FIREWALL_STORES = ("local", "app_iso", "policy")
CERT_STORES = ("machine_root", "machine_policy", "enterprise", "user_root", "authroot")

FIREWALL_BUILTIN = {"name_prefix": "@", "required_fields": ["EmbedCtxt"]}

DEFAULT_HOSTS_DIR = "%SystemRoot%\\System32\\drivers\\etc"
EXPANDED_HOSTS_DIR = "C:\\Windows\\System32\\drivers\\etc"

CURRENT_SID = "S-1-5-21-0-0-0-1001"

# Public SHA-1 thumbprints of roots Windows installs itself (from the plan).
SHIPPED_THUMBPRINTS = (
    "A43489159A520F0D93D032CCAF37E7FE20A8B419",
    "CDD4EEAE6000AC7F40C3802C171E30148030C072",
    "3B1EFD3A66EA28B16697394703A72CA340A05BD5",
    "8F43288AD272F3103B6FB1428485EA3014C0BCFE",
    "245C97DF7514E7CF2DF8BE72AE957B9E04741E85",
    "18F7C1FCC3090203FD5BAA2F861A754976C8DD25",
    "BE36A4562FB2EE05DBB3D32323ADF445084ED656",
)


def thumb(n):
    """An invented 40-hex-digit thumbprint, uppercase."""
    return f"{n:040X}"


# --- firewall_rules -------------------------------------------------------------------

def rule_text(pairs, version="v2.33"):
    """``v2.xx|Key=Value|...|`` from a list of ``(key, value)`` pairs."""
    return version + "|" + "".join(f"{k}={v}|" for k, v in pairs)


def custom_rule(name, port="8080", app="C:\\Invented\\Server\\server.exe", direction="In"):
    """A rule an application or the user added: no ``EmbedCtxt``."""
    return rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", direction),
                      ("Protocol", "6"), ("LPort", port), ("App", app), ("Name", name)])


def builtin_rule(n):
    """A rule shipped with Windows: ``EmbedCtxt`` and ``Name=@...``."""
    return rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "In"),
                      ("Protocol", "17"), ("LPort", str(5000 + n)),
                      ("App", "%SystemRoot%\\system32\\svchost.exe"),
                      ("Name", f"@FirewallAPI.dll,-{28000 + n}"),
                      ("EmbedCtxt", f"@FirewallAPI.dll,-{29000 + n}")])


def store_app_rule(n):
    """A Store app rule in ``app_iso``: ``EmbedCtxt=@{...}`` and ``Name=@{...}``."""
    package = f"Example.App{n}_1.0.0.0_x64__abc"
    return rule_text([("Action", "Allow"), ("Active", "TRUE"), ("Dir", "Out"),
                      ("EmbedCtxt", f"@{{{package}}}"),
                      ("Name", f"@{{{package}?ms-resource://x}}")], version="v2.31")


def fw_value(name, data):
    return {"name": name, "data": data}


def fw_store(store, values, exists=True):
    """One firewall store; ``values`` is a list of ``fw_value`` (or a single one)."""
    return {"store": store, "exists": exists, "values": values}


def firewall_result(local=(), app_iso=(), policy=None):
    """All three stores; ``policy=None`` is a missing policy key."""
    return [
        fw_store("local", list(local)),
        fw_store("app_iso", list(app_iso)),
        fw_store("policy", list(policy or []), exists=policy is not None),
    ]


# --- root_certificates ----------------------------------------------------------------

def cert(thumbprint, subject="CN=Invented Root", issuer=None, not_before="2024-01-01",
         not_after="2034-01-01", details=True, serial="4F2A"):
    """One certificate subkey; ``details=False`` means ``Cert:`` gave nothing.

    ``serial`` is the serial number as ``Cert:`` gives it (hex text); ``serial=None`` is a
    serial number that was not read (plan 083, M2).
    """
    if not details:
        return {"thumbprint": thumbprint, "details": None}
    return {
        "thumbprint": thumbprint,
        "details": {
            "subject": subject,
            "issuer": subject if issuer is None else issuer,
            "not_before": not_before,
            "not_after": not_after,
            "serial": serial,
        },
    }


def cert_store(store, certificates, exists=True):
    return {"store": store, "exists": exists, "certificates": certificates}


def certificates_result(**stores):
    """Every store, empty unless given: ``certificates_result(user_root=[cert(...)])``."""
    return [cert_store(name, list(stores.get(name, []))) for name in CERT_STORES]


# --- hosts ------------------------------------------------------------------------------

def hosts_result(text="", raw_dir=DEFAULT_HOSTS_DIR, expanded_dir=EXPANDED_HOSTS_DIR,
                 exists=True):
    return {
        "raw_dir": raw_dir,
        "expanded_dir": expanded_dir,
        "exists": exists,
        "text": text if exists else None,
    }


# --- administrators ---------------------------------------------------------------------

def member(sid, name, object_class="User", principal_source="Local", enabled=True,
           enabled_error=None, is_user=None):
    return {
        "sid": sid,
        "name": name,
        "object_class": object_class,
        "principal_source": principal_source,
        "is_user": is_user,
        "enabled": enabled,
        "enabled_error": enabled_error,
    }


def admins_result(members, current_sid=CURRENT_SID, method="local_group_member"):
    return {"method": method, "current_sid": current_sid, "members": members}


# --- defender_exclusions ----------------------------------------------------------------

def empty_policy():
    return {"path": [], "extension": [], "process": [], "ip": []}


def defender_result(method="preference", path=(), extension=(), process=(), ip=(),
                    policy="empty", policy_error=None):
    """Lists may be passed as a single string to mimic ``ConvertTo-Json``."""
    def as_given(value):
        return value if isinstance(value, str) else list(value)

    return {
        "method": method,
        "path": as_given(path),
        "extension": as_given(extension),
        "process": as_given(process),
        "ip": as_given(ip),
        "policy": empty_policy() if policy == "empty" else policy,
        "policy_error": policy_error,
    }


# --- responses --------------------------------------------------------------------------

def m2_responses(**overrides):
    """"Nothing there" answers for the five M2 jobs, in the shape of each result."""
    responses = {
        "firewall_rules": ok(firewall_result()),
        "root_certificates": ok(certificates_result()),
        "hosts": ok(hosts_result("")),
        "administrators": ok(admins_result([])),
        "defender_exclusions": ok(defender_result()),
    }
    responses.update(overrides)
    return responses


class AdditionsTestCase(ComponentsTestCase):
    """Helpers that turn a missing key or a wrong shape into an assertion failure."""

    def additions(self, summary):
        return self.summary_list(summary, "additions")

    def additions_of(self, summary, kind):
        return [item for item in self.additions(summary) if item.get("kind") == kind]

    def detail_additions_of(self, summary, kind):
        return [item for item in self.detail_list(summary, "additions")
                if item.get("kind") == kind]

    def hosts_file(self, summary):
        self.assertIn("hosts_file", summary, sorted(summary))
        value = summary.get("hosts_file")
        self.assertIsInstance(value, dict, f"hosts_file: {value!r}")
        return value

    def source_method(self, summary, name):
        entry = self.source(summary, name)
        if isinstance(entry, dict) and "method" in entry:
            return entry.get("method")
        detail = self.detail(summary)
        sources = detail.get("sources")
        if isinstance(sources, dict):
            entry = sources.get(name)
            if isinstance(entry, dict) and "method" in entry:
                return entry.get("method")
        if isinstance(sources, list):
            for entry in sources:
                if isinstance(entry, dict) and entry.get("name") == name and "method" in entry:
                    return entry.get("method")
        section = detail.get(name)
        if isinstance(section, dict) and "method" in section:
            return section.get("method")
        self.fail(f"no method for source {name} in summary or detail file")

    def m2_notes(self, summary):
        return [
            item for item in self.not_checked(summary)
            if any(name in str(item.get("what")) for name in M2_SOURCES)
        ]

"""Invented PowerShell rows and helpers for the component and driver sources of
ush-inventory (plan 052, milestone M1).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``comparison``,
``not_checked``, item ``key``/``id``/``own``, the ``admin`` flag of ``run_main`` and
``collect``) is described in ``fakes.py``. ``FakePowerShell`` answers ``ok([])`` for every
job it is not given, so the 048 tests keep working and these tests only list M1 jobs.

Interface assumed for M1 (from the plan's table and bullets):

- Three new jobs, one per source, called through ``run_ps(job, script, out_path)``:
  - ``optional_features`` rows ``{Name, Caption, InstallState}`` (``Win32_OptionalFeature``);
    ``InstallState`` 1 -> ``state: "enabled"``, 2 -> ``"disabled"``, 3 -> ``"absent"``, any
    other value -> ``state: null``, ``"state"`` in ``unread_fields`` and ``install_state``
    with the number. Key ``feature:<Name>``; fields ``name``, ``caption``, ``state``.
  - ``capabilities`` rows ``{Name, State}`` (``State`` as text: ``Installed``,
    ``NotPresent``, ``Staged``); run only with administrator rights (``admin=True``).
    Key ``capability:<Name>``; fields ``name``, ``state``. Without administrator rights
    the job is never called and the source is ``unreadable`` with a reason containing
    ``requires administrator``.
  - ``drivers`` rows ``{DeviceID, DeviceName, DeviceClass, InfName, DriverProviderName,
    DriverVersion, DriverDate (yyyy-MM-dd or null), Signer}`` (``Win32_PnPSignedDriver``).
    Key ``driver:<DeviceID>``; fields ``device_name``, ``class``, ``inf_name``,
    ``provider``, ``version``, ``date``, ``signer``, ``third_party``, ``own``.
    ``third_party`` when ``inf_name`` matches ``oem*.inf`` case-insensitively; ``own`` is
    ``not third_party``. A row without ``InfName`` is no item.
- Summary keys (always present): ``components`` (list or null; ids ``f..``; items
  ``{id, key, kind, name, state}``, only features ``enabled`` and capabilities
  ``Installed``), ``component_counts`` (object: ``feature`` and ``capability`` are
  ``{state: number}`` including ``unread``, or null when that source was not read;
  ``drivers_without_inf`` a number or null), ``drivers`` (list or null; ids ``d..``; items
  ``{id, key, device_name, class, provider, version, date, signer}``, only ``own: false``,
  by ``provider`` then ``device_name``, null last), ``own_counts.drivers`` (number),
  ``truncated_drivers`` and ``truncated_components`` (numbers).
- ``own_changes.by_source`` is ``{source: {added, removed, changed}}``.
- The detail file has the full sections ``components`` and ``drivers`` (every item,
  with ``own``, ``third_party``, ``inf_name``, ``unread_fields``, ``install_state``).
- A change's ``fields`` names the changed fields: either the 048 dict
  ``{field: {before, after}}`` or a list of names; only the names are asserted.

Every value here is invented; nothing comes from a machine.
"""

from .fakes import InventoryTestCase

M1_SOURCES = ("optional_features", "capabilities", "drivers")

ENABLED = 1
DISABLED = 2
ABSENT = 3
UNKNOWN = 4

VENDOR = "Invented Hardware Vendor Ltd"
VENDOR_SIGNER = "Invented Hardware Compatibility Publisher"
WINDOWS_PROVIDER = "Invented Windows Provider"
WINDOWS_SIGNER = "Invented Windows Signer"


def feature(name, install_state, caption=None):
    """One ``Win32_OptionalFeature`` row as the ``optional_features`` job returns it."""
    return {
        "Name": name,
        "Caption": caption if caption is not None else f"Invented caption of {name}",
        "InstallState": install_state,
    }


def capability(name, state):
    """One ``Get-WindowsCapability`` row as the ``capabilities`` job returns it."""
    return {"Name": name, "State": state}


def driver(device_id, inf_name, device_name="Invented Device", device_class="SYSTEM",
           provider=VENDOR, version="1.0.0.0", date="2026-01-15", signer=VENDOR_SIGNER):
    """One ``Win32_PnPSignedDriver`` row as the ``drivers`` job returns it."""
    return {
        "DeviceID": device_id,
        "DeviceName": device_name,
        "DeviceClass": device_class,
        "InfName": inf_name,
        "DriverProviderName": provider,
        "DriverVersion": version,
        "DriverDate": date,
        "Signer": signer,
    }


def windows_driver(device_id, inf_name, device_name="Invented Windows Device"):
    """A driver from a file that ships with Windows (not ``oem*.inf``)."""
    return driver(device_id, inf_name, device_name=device_name,
                  provider=WINDOWS_PROVIDER, signer=WINDOWS_SIGNER)


class ComponentsTestCase(InventoryTestCase):
    """Helpers that turn a missing key or a wrong shape into an assertion failure."""

    def summary_list(self, summary, name):
        self.assertIn(name, summary, f"summary has no {name!r}: {sorted(summary)}")
        value = summary.get(name)
        self.assertIsInstance(value, list, f"{name}: {value!r}")
        return value

    def components(self, summary):
        return self.summary_list(summary, "components")

    def drivers(self, summary):
        return self.summary_list(summary, "drivers")

    def component_counts(self, summary):
        counts = summary.get("component_counts")
        self.assertIsInstance(counts, dict, f"component_counts: {counts!r}")
        return counts

    def kind_counts(self, summary, kind):
        counts = self.component_counts(summary).get(kind)
        self.assertIsInstance(counts, dict, f"component_counts.{kind}: {counts!r}")
        return counts

    def own_counts(self, summary):
        counts = summary.get("own_counts")
        self.assertIsInstance(counts, dict, f"own_counts: {counts!r}")
        return counts

    def detail_list(self, summary, name):
        value = self.detail(summary).get(name)
        self.assertIsInstance(value, list, f"detail {name}: {value!r}")
        return value

    def changes_from(self, summary, source):
        return [c for c in self.changes(summary) if c.get("source") == source]

    def by_source(self, summary, source):
        by_source = self.own_changes(summary).get("by_source")
        self.assertIsInstance(by_source, dict, f"own_changes.by_source: {by_source!r}")
        counts = by_source.get(source)
        self.assertIsInstance(counts, dict, f"own_changes.by_source.{source}: {counts!r}")
        return counts

    def field_names(self, change):
        fields = change.get("fields")
        if isinstance(fields, dict):
            return sorted(fields)
        if isinstance(fields, list):
            return sorted(str(f) for f in fields)
        self.fail(f"change has no fields: {change}")

    def m1_notes(self, summary):
        """``not_checked`` items that name one of the M1 sources."""
        return [
            item for item in self.not_checked(summary)
            if any(name in str(item.get("what")) for name in M1_SOURCES)
        ]

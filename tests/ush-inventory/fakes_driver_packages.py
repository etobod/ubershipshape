"""Invented driver store listings for the ``driver_packages`` source of ush-inventory
(plan 024, milestone M2).

The general interface (``main``, ``FakePowerShell``, ``sources``, ``comparison``,
``not_checked``, item ``key``/``id``) is described in ``fakes.py``; the ``drivers`` job
rows come from ``fakes_components.driver``.

Interface fixed for M2 (the code does not exist yet):

- A job named ``driver_packages`` runs ``pnputil /enum-drivers /format xml`` and answers
  one JSON object ``{"exit_code": <int>, "text": "<the whole stdout>"}``. An exit code
  other than 0 (e.g. a refused ``/format``, where the tool prints usage text), text that
  is not parseable XML, or a failed job make the source ``unreadable`` with a reason.
- Only third-party packages (published name ``oem<N>.inf``) are kept. ``DriverVersion``
  holds ``MM/DD/YYYY`` and the version separated by a space; the item gives ``date``
  (ISO ``YYYY-MM-DD``) and ``version``.
- Item fields (summary and detail): ``id`` (``o<n>``), ``key``, ``published_name``,
  ``original_name``, ``provider``, ``class``, ``version``, ``date``, ``signer``. Key
  ``driver_package:<original name>|<provider>|<version>``, case-folded. (Plan 024's
  ``present_device`` and ``driver_packages_without_device`` were replaced by plan 051
  M1, below.)
- ``component_counts`` has ``driver_packages`` (all third-party packages). The detail
  file section ``driver_packages`` holds every third-party package.

Plan 051, milestone M1 adds a source ``devices``:

- A job named ``devices`` runs ``pnputil /enum-devices /drivers /format xml`` and answers
  one JSON object ``{"exit_code": <int>, "text": "<the whole stdout>", "last_removal":
  {<InstanceId>: "yyyy-MM-dd" | null}}``. The ``last_removal`` key is an assumption of
  these tests: the plan says the job reads ``DEVPKEY_Device_LastRemovalDate`` for each
  ``Disconnected`` device with an ``oem<N>.inf`` driver and returns it as a UTC
  ``yyyy-MM-dd``, but does not name the field; ``devices_answer`` is the one place that
  builds it. A failed job, an exit code other than 0 or text that is no listing make the
  source ``unreadable``.
- The listing: root ``PnpUtil``, one ``Device`` element (attribute ``InstanceId``) per
  device with children ``DeviceDescription``, ``ClassName``, ``ClassGuid``,
  ``ManufacturerName``, ``Status``, ``DriverName`` and ``MatchingDrivers``.
- Each package gets ``device_state`` (``present`` / ``non_present`` /
  ``no_device_found`` / null with ``device_state_reason``); a ``non_present`` package has
  ``devices``: ``[{device_name, class, status, last_removal}]``, no instance id. The
  summary list ``driver_packages`` holds ``non_present`` and ``no_device_found``
  packages, and is null when ``devices`` was not read; ``component_counts`` has
  ``driver_packages_by_state`` ``{present, non_present, no_device_found, unread}``.

Every value here is invented; nothing comes from a machine.
"""

from xml.sax.saxutils import escape, quoteattr

from .fakes import id_number, ok
from .fakes_components import ComponentsTestCase

PROVIDER = "Invented Peripherals Corp"
SIGNER = "Invented Driver Signer"
MOUSE_GUID = "{00000000-0000-0000-0000-00000000a001}"
MONITOR_GUID = "{00000000-0000-0000-0000-00000000a002}"
EXTENSION_GUID = "{00000000-0000-0000-0000-00000000a0e1}"

USAGE_TEXT = (
    "Invented PnP Utility\r\n\r\n"
    "Usage:\r\n"
    "  invented-utility /enum-drivers [/invented-option]\r\n"
    "Invented usage text: the option is not known.\r\n"
)

BROKEN_XML = (
    '<?xml version="1.0" encoding="utf-8"?>\r\n'
    '<PnpUtil Version="1.0" Command="/enum-drivers /format xml">\r\n'
    '  <Driver DriverName="oem3.inf">\r\n'
    "    <OriginalName>inventedbroken.inf</Original"
)


def package(published, original, provider=PROVIDER, class_name="Mouse",
            class_guid=MOUSE_GUID, version="1.2.3.4", date="03/14/2024", signer=SIGNER):
    """One package of the invented driver store (``date`` as ``MM/DD/YYYY``)."""
    return {
        "published": published,
        "original": original,
        "provider": provider,
        "class": class_name,
        "class_guid": class_guid,
        "version": version,
        "date": date,
        "signer": signer,
    }


def store_xml(packages):
    """The whole stdout of ``pnputil /enum-drivers /format xml`` for ``packages``."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<PnpUtil Version="1.0" Command="/enum-drivers /format xml">']
    for pkg in packages:
        lines.append(f"  <Driver DriverName={quoteattr(pkg['published'])}>")
        for tag, value in (("OriginalName", pkg["original"]),
                           ("ProviderName", pkg["provider"]),
                           ("ClassName", pkg["class"]),
                           ("ClassGuid", pkg["class_guid"]),
                           ("DriverVersion", f"{pkg['date']} {pkg['version']}"),
                           ("SignerName", pkg["signer"])):
            lines.append(f"    <{tag}>{escape(value)}</{tag}>")
        lines.append("    <CatalogAttributes/>")
        lines.append("    <WhcpVersion/>")
        lines.append("  </Driver>")
    lines.append("</PnpUtil>")
    return "\r\n".join(lines) + "\r\n"


def store(packages, exit_code=0):
    """The ``driver_packages`` job answer for a store holding ``packages``."""
    return ok({"exit_code": exit_code, "text": store_xml(packages)})


def store_text(text, exit_code):
    """The ``driver_packages`` job answer with any stdout and exit code."""
    return ok({"exit_code": exit_code, "text": text})


def device(instance_id, driver_name, status, name="Invented Device", class_name="Mouse",
           class_guid=MOUSE_GUID, manufacturer="Invented Peripherals Corp"):
    """One device of ``pnputil /enum-devices /drivers`` (``status`` None: no ``Status``)."""
    return {
        "instance_id": instance_id,
        "name": name,
        "class": class_name,
        "class_guid": class_guid,
        "manufacturer": manufacturer,
        "status": status,
        "driver": driver_name,
    }


def devices_xml(devices):
    """The whole stdout of ``pnputil /enum-devices /drivers /format xml``."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<PnpUtil Version="1.0" Command="/enum-devices /drivers /format xml">']
    for dev in devices:
        lines.append(f"  <Device InstanceId={quoteattr(dev['instance_id'])}>")
        for tag, value in (("DeviceDescription", dev["name"]),
                           ("ClassName", dev["class"]),
                           ("ClassGuid", dev["class_guid"]),
                           ("ManufacturerName", dev["manufacturer"]),
                           ("Status", dev["status"]),
                           ("DriverName", dev["driver"])):
            if value is not None:
                lines.append(f"    <{tag}>{escape(value)}</{tag}>")
        if dev["driver"] is not None:
            lines.append("    <MatchingDrivers>")
            lines.append(f"      <Driver DriverName={quoteattr(dev['driver'])}>")
            lines.append("        <Rank>00FF0000</Rank>")
            lines.append("        <Status>Best Ranked / Installed</Status>")
            lines.append("      </Driver>")
            lines.append("    </MatchingDrivers>")
        lines.append("  </Device>")
    lines.append("</PnpUtil>")
    return "\r\n".join(lines) + "\r\n"


def devices_answer(devices, last_removal=None, exit_code=0):
    """The ``devices`` job answer for ``devices``; ``last_removal`` maps an instance id
    to ``yyyy-MM-dd`` (or None when the date was not read)."""
    return ok({"exit_code": exit_code, "text": devices_xml(devices),
               "last_removal": dict(last_removal or {})})


def devices_text(text, exit_code):
    """The ``devices`` job answer with any stdout and exit code."""
    return ok({"exit_code": exit_code, "text": text, "last_removal": {}})


def package_key(pkg):
    """``driver_package:<original name>|<provider>|<version>``, case-folded."""
    return f"driver_package:{pkg['original']}|{pkg['provider']}|{pkg['version']}".casefold()


def iso_date(date):
    """``MM/DD/YYYY`` -> ``YYYY-MM-DD``."""
    month, day, year = date.split("/")
    return f"{year}-{month}-{day}"


class DriverPackagesTestCase(ComponentsTestCase):
    def packages(self, summary):
        return self.summary_list(summary, "driver_packages")

    def detail_packages(self, summary):
        return self.by_key(self.detail_list(summary, "driver_packages"))

    def package_notes(self, summary):
        return self.notes_about_source(summary, "driver_packages")

    def assert_package(self, item, pkg, device_state):
        """Every item field of one package, ``device_state`` included."""
        self.assertIsNotNone(item, pkg)
        id_number(item.get("id"), "o")
        self.assertEqual(item.get("key"), package_key(pkg), item)
        self.assertEqual(item.get("published_name"), pkg["published"], item)
        self.assertEqual(item.get("original_name"), pkg["original"], item)
        self.assertEqual(item.get("provider"), pkg["provider"], item)
        self.assertEqual(item.get("class"), pkg["class"], item)
        self.assertEqual(item.get("version"), pkg["version"], item)
        self.assertEqual(item.get("date"), iso_date(pkg["date"]), item)
        self.assertEqual(item.get("signer"), pkg["signer"], item)
        self.assertIn("device_state", item, item)
        self.assertEqual(item["device_state"], device_state, item)

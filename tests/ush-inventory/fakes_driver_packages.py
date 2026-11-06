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
  ``original_name``, ``provider``, ``class``, ``version``, ``date``, ``signer``,
  ``present_device`` (true/false/null). Key
  ``driver_package:<original name>|<provider>|<version>``, case-folded.
- ``present_device`` is true when a ``drivers`` row has the same ``InfName``
  (case-insensitive), rows without ``DeviceID`` included; class ``Extension`` gives null.
  When ``drivers`` is unreadable every package is null, summary ``driver_packages`` is
  null and a not_checked entry says the present devices were not read.
- Summary list ``driver_packages`` holds only ``present_device`` false;
  ``component_counts`` has ``driver_packages`` (all third-party packages) and
  ``driver_packages_without_device``. The detail file section ``driver_packages`` holds
  every third-party package.

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

    def assert_package(self, item, pkg, present_device):
        """Every item field of one package, ``present_device`` included."""
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
        self.assertIn("present_device", item, item)
        if present_device is None:
            self.assertIsNone(item["present_device"], item)
        else:
            self.assertIs(item["present_device"], present_device, item)

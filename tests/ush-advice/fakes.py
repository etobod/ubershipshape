"""Shared fakes for the ush-advice tests of milestone M1 (plan 103).

Interface under test (fixed before the code exists):

- The script is loaded with ``load_script("ush-advice", "advice")``.
- ``main(argv=None, run_ps=None, now=None) -> int``; ``now`` is a tz-aware datetime;
  the tests always pass ``--data-dir <tmp dir>``. With ``run_ps`` None the module-level
  ``default_run_ps`` is used; the tests always inject ``run_ps`` (and replace
  ``default_run_ps`` with a function that raises ``AssertionError``).
- ``run_ps(job, script, out_path) -> (exit_code, stderr)``. ``FakePowerShell`` answers
  by job name and writes JSON to ``out_path`` as Windows PowerShell 5.1 does (UTF-8 with
  a BOM); a failed job writes no file and returns a non-zero code with stderr. A job it
  does not know answers ``[]``.
- Jobs and row shapes:
  - ``os_version``: one row ``{DisplayVersion, CurrentBuild, UBR, EditionID,
    Architecture}``; ``UBR`` an int, ``CurrentBuild`` text.
  - ``hotfixes``: rows ``{HotFixID}``.
  - ``firmware``: one row ``{Manufacturer, Model, SMBIOSBIOSVersion, ReleaseDate}``;
    ``ReleaseDate`` a ``yyyy-MM-dd`` text.
- Module-level text constants ``OS_VERSION_BODY``, ``HOTFIXES_BODY`` and
  ``FIRMWARE_BODY`` hold the job bodies. Every ``[pscustomobject]@{ ... }`` literal in
  ``FIRMWARE_BODY`` has exactly the keys ``Manufacturer``, ``Model``,
  ``SMBIOSBIOSVersion``, ``ReleaseDate``; in ``HOTFIXES_BODY`` exactly ``HotFixID``.
  Neither body mentions ``SerialNumber``, ``UUID``, ``CSName`` or ``InstalledOn``
  (case-insensitive).
- Module-level ``Path`` constants ``PRODUCTS_FILE`` and ``SOURCES_FILE`` (tests patch
  them with ``mock.patch.object``). ``data/products.json`` is
  ``{"products": {"<DisplayVersion>|<architecture>": "<MSRC product name>"}}`` and
  contains ``"25H2|AMD64": "Windows 11 Version 25H2 for x64-based Systems"``. A products
  file without the ``products`` object exits 2 with a message on stderr, and ``run_ps``
  is never called.
- Output: ``<data dir>/work/advice-<UTC stamp YYYYmmdd-HHMMSS>.summary.json`` and
  ``.detail.json``; the summary is also printed on stdout.
- Summary: ``skill`` is ``"ush-advice"``; ``sources`` is a list of
  ``{name, status, reason}`` with names ``os_version``, ``hotfixes``, ``firmware``;
  ``not_checked`` is a list of ``{what, reason}`` and an item about a job names the job
  in ``what``; ``machine`` is ``{display_version, build, ubr, edition_id, architecture,
  product, product_reason, hotfixes, firmware}`` with ``firmware`` either
  ``{manufacturer, model, bios_version, bios_date}`` or null; ``build`` is the
  CurrentBuild text, ``ubr`` an int; ``product_reason`` is null when the product is
  known and a non-empty text when it is not.
- Without ``--findings`` the top-level ``updates``, ``exploited``, ``firmware`` and
  ``issues`` are null and ``not_checked`` has an item whose ``what`` or ``reason``
  mentions the search (matched case-insensitively on "search").
- A failed ``os_version`` gives ``build`` and ``ubr`` null; a failed ``hotfixes`` gives
  ``machine.hotfixes`` null; a ``hotfixes`` answer ``[]`` gives ``machine.hotfixes ==
  []`` with no ``not_checked`` item naming hotfixes; a failed ``firmware`` gives
  ``machine.firmware`` null. Each failure adds a ``not_checked`` item naming the job.
  The exit code is 0 in every one of these cases.
- ``--detail <unknown id>`` exits 1 without calling ``run_ps``.

Interface added by milestone M2 (findings compared with the machine):

- ``--findings <path>`` reads a JSON file ``{"searches": [{id, status, reason}],
  "findings": [...]}``; search ids ``msrc``, ``kev``, ``release-health``, ``firmware``;
  status ``read``, ``partial`` or ``unreadable``. Every finding has ``kind`` (``update``,
  ``exploited``, ``firmware``, ``issue``), ``url``, ``title``, ``query`` and
  ``published`` plus the fields of its kind (see the builders below).
- A bad shape (an entry without ``url``, an ``http://`` url, an unknown ``kind``, a
  ``fixed_build`` that is neither ``10.0.B.U`` nor ``B.U``) exits 2, stderr names the
  entry number (0-based or 1-based), and nothing is written under ``state/``.
- Summary top-level lists, each item with ``id`` and ``new``:
  - ``updates`` (ids ``u...``, one per ``month``): ``month``, ``kbs``,
    ``fixed_builds`` (``"B.U"`` texts), ``cve_count``, ``critical_count``, ``listed``,
    ``kb_installed`` (list or null), ``applied`` (true/false/null),
    ``applied_reason`` (null or a text containing "build mismatch" or "mixed").
  - ``exploited`` (ids ``k...``): ``cve``, ``vendor``, ``product``, ``date_added``,
    ``due_date``, ``ransomware``, ``listed``, ``in_updates``, ``month``, ``applied``.
  - ``firmware`` (ids ``f...``): ``manufacturer``, ``model``, ``version``,
    ``release_date``, ``listed``, ``model_matches``, ``same_version``, ``newer``.
  - ``issues`` (ids ``i...``): ``title``, ``published``, ``listed``.
  - A list is null when its search is missing or not ``read``; ``[]`` when ``read``
    with no findings of its kind.
- Summary also has ``kev_other_count`` (int), ``query_warnings`` (list of
  ``{finding_id, reason}``, ``reason`` in ``build``/``bios_version``/``kb``,
  ``finding_id`` a ``w...`` id, never the query text), ``truncated``,
  ``truncated_exploited``, ``comparison`` (``{updates, exploited, firmware, issues}``,
  each ``compared``/``no_baseline``/``not_read``) and ``detail_file``. A list that was
  not read adds a ``not_checked`` item naming its search id in ``what`` or ``reason``;
  a missing UBR with update findings adds an item; each query warning adds an item.
- Detail file: ``findings`` (every finding of the file, ids ``w1...`` in file order,
  each with ``domain`` and ``listed``), ``kev_other`` and full ``updates``,
  ``exploited``, ``firmware``, ``issues`` (never truncated).
- Baseline ``<data dir>/state/ush-advice.json``: the tests only check that it exists
  and survives across runs.
- ``listed`` for firmware also uses ``firmware_domains`` of ``data/sources.json``,
  matched by the machine manufacturer prefix case-insensitively (Lenovo -> lenovo.com,
  HP -> hp.com).

Every value here is invented; nothing comes from a machine.
"""

import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.skill_loader import load_script

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
STAMP = "20260920-120000"

KNOWN_PRODUCT = "Windows 11 Version 25H2 for x64-based Systems"
JOBS = ("os_version", "hotfixes", "firmware")


def ok(payload):
    """PowerShell wrote ``payload`` as JSON and exited 0."""
    return ("ok", payload)


def failure(stderr="Invented failure: access denied.", code=1):
    """PowerShell exited with ``code`` and wrote ``stderr``; no file is written."""
    return ("fail", code, stderr)


def os_version_row(display_version="25H2", build="26200", ubr=6899,
                   edition_id="Core", architecture="AMD64"):
    return {
        "DisplayVersion": display_version,
        "CurrentBuild": build,
        "UBR": ubr,
        "EditionID": edition_id,
        "Architecture": architecture,
    }


def hotfix_row(kb):
    return {"HotFixID": kb}


def firmware_row(manufacturer="Contoso Ltd.", model="Contoso Book 14",
                 bios_version="CB14.317.0", release_date="2026-04-15"):
    return {
        "Manufacturer": manufacturer,
        "Model": model,
        "SMBIOSBIOSVersion": bios_version,
        "ReleaseDate": release_date,
    }


DEFAULT_KBS = ["KB5099901", "KB5099917"]


def machine(os_row=None, kbs=None, firmware=None):
    """Responses for all three jobs; every job succeeds with invented values."""
    return {
        "os_version": ok([os_row if os_row is not None else os_version_row()]),
        "hotfixes": ok([hotfix_row(kb) for kb in (DEFAULT_KBS if kbs is None else kbs)]),
        "firmware": ok([firmware if firmware is not None else firmware_row()]),
    }


class FakePowerShell:
    """Stands in for run_ps. Jobs not listed answer ``ok([])``."""

    def __init__(self, responses=None):
        self.responses = machine()
        self.responses.update(responses or {})
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        response = self.responses.get(job, ok([]))
        if response[0] == "ok":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Windows PowerShell 5.1 writes UTF-8 with a BOM.
            out_path.write_text(json.dumps(response[1]), encoding="utf-8-sig")
            return 0, ""
        _, code, stderr = response
        return code, stderr

    def jobs(self):
        return [call[0] for call in self.calls]


def search(search_id, status="read", reason=None):
    """One entry of the findings file's ``searches`` list."""
    return {"id": search_id, "status": status, "reason": reason}


def update_finding(month, kb, fixed_build, cves=(), release_type="security", url=None,
                   query=None, title=None, published=None):
    """An invented ``update`` finding; ``cves`` is a list of (cve, severity) pairs, or
    None for a release-information row without CVEs (written as ``null``)."""
    return {
        "kind": "update",
        "url": url or f"https://support.microsoft.com/help/{kb.removeprefix('KB')}",
        "title": title or f"Invented cumulative update {kb}",
        "query": query,
        "published": published,
        "month": month,
        "kb": kb,
        "fixed_build": fixed_build,
        "release_type": release_type,
        "cves": (None if cves is None
                 else [{"cve": cve, "severity": severity} for cve, severity in cves]),
    }


def exploited_finding(cve, url=None, query=None, title=None, vendor="Contoso",
                      product="Invented Product", date_added="2026-09-02",
                      due_date="2026-09-23", ransomware="Unknown"):
    """An invented ``exploited`` finding."""
    return {
        "kind": "exploited",
        "url": url or "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        "title": title or f"Invented exploited vulnerability {cve}",
        "query": query,
        "published": None,
        "cve": cve,
        "vendor": vendor,
        "product": product,
        "date_added": date_added,
        "due_date": due_date,
        "ransomware": ransomware,
    }


def firmware_finding(manufacturer, model, version, release_date, url, query=None,
                     title=None):
    """An invented ``firmware`` finding."""
    return {
        "kind": "firmware",
        "url": url,
        "title": title or f"Invented BIOS update {version}",
        "query": query,
        "published": None,
        "manufacturer": manufacturer,
        "model": model,
        "version": version,
        "release_date": release_date,
    }


def issue_finding(title, url, query=None, published="2026-09-10"):
    """An invented ``issue`` finding (common fields only)."""
    return {
        "kind": "issue",
        "url": url,
        "title": title,
        "query": query,
        "published": published,
    }


def findings_doc(searches, findings):
    return {"searches": list(searches), "findings": list(findings)}


def machine_touched(*args, **kwargs):
    raise AssertionError("a real machine function was called")


_KEY = re.compile(r"""^\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?\s*=(?!=)""")
_LITERAL = re.compile(r"\[pscustomobject\]\s*@\{", re.IGNORECASE)


def pscustomobject_keys(body):
    """Return one set of keys per ``[pscustomobject]@{ ... }`` literal in ``body``.

    Only the top level of each literal counts: text inside nested braces, parentheses
    or quotes is skipped, and a key is the identifier before ``=`` at the start of a
    line or after a ``;``.
    """
    result = []
    for match in _LITERAL.finditer(body):
        index = match.end()
        depth = 0
        quote = None
        top = []
        while index < len(body):
            char = body[index]
            if quote:
                if char == quote:
                    quote = None
                if depth == 0:
                    top.append(char)
            elif char in "'\"":
                quote = char
                if depth == 0:
                    top.append(char)
            elif char in "{(":
                depth += 1
            elif char in "})":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0:
                top.append(char)
            index += 1
        keys = set()
        for segment in re.split(r"[;\n]", "".join(top)):
            key = _KEY.match(segment)
            if key:
                keys.add(key.group(1))
        result.append(keys)
    return result


class AdviceTestCase(unittest.TestCase):
    advice = None

    def setUp(self):
        cls = type(self)
        if cls.advice is None:
            try:
                cls.advice = load_script("ush-advice", "advice")
            except FileNotFoundError:
                self.fail("skills/ush-advice/scripts/advice.py not found")
        patcher = mock.patch.object(self.advice, "default_run_ps", machine_touched,
                                    create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def temp_file(self, name, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name).resolve() / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_main(self, data_dir, fake, now=NOW, extra=()):
        """Run main with run_ps injected; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.advice.main(
                ["--data-dir", str(data_dir), *extra],
                run_ps=fake,
                now=now,
            )
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            return json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")

    def collect(self, fake, data_dir=None, now=NOW):
        """Run a collection and return the parsed summary (exit code must be 0)."""
        code, stdout, stderr = self.run_main(data_dir or self.data_dir(), fake, now=now)
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def machine_of(self, summary):
        facts = summary.get("machine")
        self.assertIsInstance(facts, dict, summary)
        return facts

    def not_checked(self, summary):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return items

    def notes_about(self, summary, job):
        return [item for item in self.not_checked(summary) if job in str(item.get("what"))]

    def run_findings(self, data_dir, fake, doc, now=NOW):
        """Write ``doc`` to a temp file and run with ``--findings``.

        Returns (code, stdout, stderr); a ``SystemExit`` from main counts as its code.
        """
        path = self.temp_file("findings.json", json.dumps(doc))
        try:
            return self.run_main(data_dir, fake, now=now, extra=["--findings", str(path)])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
            return code, "", f"SystemExit({exc.code!r})"

    def collect_findings(self, fake, doc, data_dir=None, now=NOW):
        """Run with ``--findings``; the exit code must be 0; return the summary."""
        code, stdout, stderr = self.run_findings(data_dir or self.data_dir(), fake, doc,
                                                 now=now)
        self.assertEqual(code, 0, f"--findings run failed: {stderr[:400]}")
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        return summary

    def detail_of(self, summary):
        path = summary.get("detail_file")
        self.assertIsInstance(path, str, "summary has no detail_file")
        detail = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        self.assertIsInstance(detail, dict, path)
        return detail

    def items(self, summary, name):
        value = summary.get(name)
        self.assertIsInstance(value, list, f"{name}: {value!r}")
        return value

    def item_by(self, summary, name, key, value):
        found = [item for item in self.items(summary, name) if item.get(key) == value]
        self.assertEqual(len(found), 1, f"{name} items with {key}={value!r}: {found}")
        return found[0]

    def search_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if "search" in str(item.get("what")).lower()
                or "search" in str(item.get("reason")).lower()]

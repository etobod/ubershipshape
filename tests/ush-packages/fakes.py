"""Shared fakes for the ush-packages tests (plan 061, M1).

Interface under test (fixed before the code exists):

- The script is loaded with ``load_script("ush-packages", "packages")``.
- ``main(argv=None, run_ps=None, is_admin=None, now=None) -> int``; ``now`` is a
  tz-aware datetime; the tests always pass ``--data-dir <tmp>``.
- ``run_ps(job, script, out_path) -> (exit_code, stderr)``. ``FakePowerShell`` answers
  only the pip, npm and ``.npmrc`` jobs moved from ush-inventory and writes JSON to
  ``out_path`` the way Windows PowerShell 5.1 does (UTF-8 with a BOM):
  - ``python_registrations``: rows ``{hive, view, company, tag, install_path,
    sys_version, sys_architecture}`` (default: no Python registered).
  - ``package_folders``: reads its input file ``<out stem>.input.json`` next to
    ``out_path`` (``{"folders": [{"path": <raw path>, "layout": "python"|"npm"}]}``) and
    answers one row per folder ``{path, expanded, status, reason, packages}``; a folder
    not given to the fake is ``absent``.
  - ``npmrc``: ``{status: "read"|"absent"|"unreadable", lines, reason}`` (default:
    absent).
  Any other job fails (exit 1): the skill has no other job in this plan.
- The module reads the process environment through ``ENVIRON`` (as inventory did); the
  tests replace it with an empty dict.
- Output: the summary on stdout, with ``detail_file`` naming the detail file; the
  detail file keeps the moved lists ``pip_packages`` and ``npm_packages`` and the full
  ``packages`` and ``changes`` lists.

Every value here is invented; nothing comes from a machine.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from tests.skill_loader import REPO_ROOT, load_script

SKILL = "ush-packages"
NOW = datetime(2026, 11, 9, 10, 0, 0, tzinfo=timezone.utc)

PROFILE_FILE = REPO_ROOT / "skills" / SKILL / "data" / "report-profile.json"
MANAGERS_FILE = REPO_ROOT / "skills" / SKILL / "data" / "managers.json"

# An invented %APPDATA% expansion (not a reading from any machine).
APPDATA = "C:\\Users\\Invented\\AppData\\Roaming"
DEFAULT_NPM_FOLDER = "%APPDATA%\\npm\\node_modules"


def ok(payload):
    """PowerShell wrote ``payload`` as JSON and exited 0."""
    return ("ok", payload)


def failure(stderr, code=1):
    """PowerShell exited with ``code`` and wrote ``stderr``; no file is written."""
    return ("fail", code, stderr)


NPMRC_ABSENT = ok({"status": "absent", "lines": None, "reason": None})


def npmrc_read(*lines):
    return ok({"status": "read", "lines": list(lines), "reason": None})


def npmrc_unreadable(reason):
    return ok({"status": "unreadable", "lines": None, "reason": reason})


def registration(tag, install_path, hive="HKLM", view="64", sys_version=None,
                 sys_architecture="64bit", company="PythonCore"):
    """One PEP 514 registration as the ``python_registrations`` job returns it."""
    if hive == "HKCU":
        view = None
    return {
        "hive": hive,
        "view": view,
        "company": company,
        "tag": tag,
        "install_path": install_path,
        "sys_version": tag if sys_version is None else sys_version,
        "sys_architecture": sys_architecture,
    }


def install_folder(install_path):
    """The raw install ``site-packages`` path the code sends for ``install_path``."""
    return install_path.rstrip("\\") + "\\Lib\\site-packages"


def user_folder(xy, bits32=False):
    """The raw per-user ``site-packages`` path for version digits ``xy``."""
    suffix = "-32" if bits32 else ""
    return f"%APPDATA%\\Python\\Python{xy}{suffix}\\site-packages"


def package(name, version, entry=None):
    """One pip package entry read from its ``dist-info``."""
    return {
        "entry": entry or f"{name}-{version}.dist-info",
        "name": name,
        "version": version,
        "status": "read",
        "reason": None,
    }


def unreadable_package(entry, reason):
    """One pip package entry whose ``METADATA`` could not be read."""
    return {"entry": entry, "name": None, "version": None, "status": "unreadable",
            "reason": reason}


def npm_package(name, version):
    """One npm package read from ``node_modules\\<name>\\package.json``."""
    return {"entry": name, "name": name, "version": version, "status": "read",
            "reason": None}


def unreadable_scope(scope, reason="Access to the path is denied (invented)"):
    """An npm scope folder (``@contoso``) that could not be listed."""
    return {"entry": scope, "name": None, "version": None, "status": "unreadable",
            "reason": reason}


def read_folder(*packages):
    return {"status": "read", "reason": None, "packages": list(packages)}


def unreadable_folder(reason):
    return {"status": "unreadable", "reason": reason, "packages": None}


def expand(raw):
    text = str(raw)
    marker = "%appdata%"
    index = text.casefold().find(marker)
    if index < 0:
        return text
    return text[:index] + APPDATA + text[index + len(marker):]


def package_folders_answer(folders, specs):
    """One row per input folder; a folder not in ``specs`` is ``absent``."""
    rows = []
    for folder in folders:
        raw = folder.get("path")
        spec = specs.get(str(raw).casefold())
        if spec is None:
            spec = {"status": "absent", "reason": None, "packages": []}
        rows.append({
            "path": raw,
            "expanded": expand(raw),
            "status": spec["status"],
            "reason": spec["reason"],
            "packages": spec["packages"],
        })
    return rows


class FakePowerShell:
    """Stands in for run_ps; answers only ``python_registrations``, ``package_folders``
    and ``npmrc``.

    ``responses`` overrides a job's answer (``ok(...)`` or ``failure(...)``). ``folders``
    maps a raw folder path (matched case-insensitively) to a folder spec built with
    ``read_folder`` or ``unreadable_folder``; ``package_folders`` answers from it unless
    ``responses`` names that job. Every input folder seen is kept in ``folder_inputs``.
    """

    def __init__(self, responses=None, folders=None):
        self.responses = {"python_registrations": ok([]), "npmrc": NPMRC_ABSENT}
        self.responses.update(responses or {})
        self.specs = {str(path).casefold(): spec for path, spec in (folders or {}).items()}
        self.folder_inputs = []
        self.calls = []

    def __call__(self, job, script, out_path):
        out_path = Path(out_path)
        self.calls.append((job, script, out_path))
        if job == "package_folders" and job not in self.responses:
            input_path = out_path.with_name(out_path.name[:-len(".json")] + ".input.json")
            data = json.loads(input_path.read_text(encoding="utf-8-sig"))
            folders = data.get("folders") or []
            if isinstance(folders, dict):
                folders = [folders]
            self.folder_inputs.extend(folders)
            response = ok(package_folders_answer(folders, self.specs))
        elif job in self.responses:
            response = self.responses[job]
        else:
            response = failure(f"FakePowerShell: {job!r} is not a pip, npm or .npmrc job")
        if response[0] == "ok":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Windows PowerShell 5.1 writes UTF-8 with a BOM.
            out_path.write_text(json.dumps(response[1]), encoding="utf-8-sig")
            return 0, ""
        _, code, stderr = response
        return code, stderr

    def jobs(self):
        return [call[0] for call in self.calls]

    def input_paths(self):
        return [str(folder.get("path")) for folder in self.folder_inputs]

    def npm_inputs(self):
        return [folder for folder in self.folder_inputs if folder.get("layout") == "npm"]


def packages_fake(registrations=(), folders=None, npmrc=None, extra=None):
    """A fake with the given Pythons, folders and ``.npmrc`` answer."""
    responses = {"python_registrations": ok(list(registrations))}
    if npmrc is not None:
        responses["npmrc"] = npmrc
    responses.update(extra or {})
    return FakePowerShell(responses, folders)


def note_text(item):
    return (str(item.get("what")) + ": " + str(item.get("reason"))).casefold()


def id_number(item_id, letter):
    """``"k12"`` -> 12 for letter ``k``; fails loudly on another shape."""
    text = str(item_id)
    if not text.startswith(letter) or not text[1:].isdigit():
        raise AssertionError(f"id {item_id!r} is not {letter}<number>")
    return int(text[1:])


def load_profile():
    """The real ``skills/ush-packages/data/report-profile.json``."""
    return json.loads(PROFILE_FILE.read_text(encoding="utf-8-sig"))


def truncated_count_keys(profile=None):
    """``{list name: summary key of its cut count}`` from the profile's ``truncated``
    entries (``count_key`` defaults to ``truncated``, as in the shared checker)."""
    profile = load_profile() if profile is None else profile
    entries = profile.get("truncated") or []
    if isinstance(entries, dict):
        entries = [entries]
    return {entry["list"]: entry.get("count_key", "truncated") for entry in entries}


class PackagesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packages = load_script(SKILL, "packages")
        # Tests never read the machine: the process environment (NPM_CONFIG_PREFIX)
        # is replaced by an empty one; a test that needs a variable patches its own.
        cls.packages.ENVIRON = {}

    def data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve() / "ush-data"

    def run_main(self, data_dir, fake, admin=False, now=NOW, extra=()):
        """Run main with both machine functions injected; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.packages.main(
                ["--data-dir", str(data_dir), *extra],
                run_ps=fake,
                is_admin=lambda: admin,
                now=now,
            )
        return code, out.getvalue(), err.getvalue()

    def parse(self, stdout):
        try:
            return json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout is not JSON ({exc}): {stdout[:300]!r}")

    def collect(self, fake, data_dir=None, admin=False, now=NOW):
        """Run a collection and return the parsed summary (exit code must be 0)."""
        code, stdout, stderr = self.run_main(
            data_dir or self.data_dir(), fake, admin=admin, now=now
        )
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertIsInstance(summary, dict, stdout[:300])
        self.assertEqual(summary.get("skill"), SKILL, sorted(summary))
        return summary

    def detail(self, summary):
        path = Path(summary.get("detail_file"))
        self.assertTrue(path.is_absolute(), path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, type(data))
        return data

    def source(self, summary, name):
        sources = summary.get("sources")
        if isinstance(sources, dict):
            self.assertIn(name, sources, sources)
            return sources[name]
        self.assertIsInstance(sources, list, summary)
        matches = [s for s in sources if s.get("name") == name]
        self.assertEqual(len(matches), 1, f"source {name}: {sources}")
        return matches[0]

    def comparison(self, summary):
        comparison = summary.get("comparison")
        self.assertIsInstance(comparison, dict, summary)
        return comparison

    def changes(self, summary):
        changes = summary.get("changes")
        self.assertIsInstance(changes, list, summary)
        return changes

    def changes_from(self, summary, source):
        return [c for c in self.changes(summary) if c.get("source") == source]

    def not_checked(self, summary):
        items = summary.get("not_checked")
        self.assertIsInstance(items, list, summary)
        return items

    def notes_with(self, summary, *words):
        return [item for item in self.not_checked(summary)
                if all(word.casefold() in note_text(item) for word in words)]

    def by_key(self, items):
        self.assertIsInstance(items, list, items)
        result = {}
        for item in items:
            self.assertNotIn(item.get("key"), result, f"duplicate key in {items}")
            result[item.get("key")] = item
        return result

    def field_names(self, change):
        fields = change.get("fields")
        if isinstance(fields, dict):
            return sorted(fields)
        if isinstance(fields, list):
            return sorted(str(f) for f in fields)
        self.fail(f"change has no fields: {change}")

    def managers(self, summary):
        """The summary's ``managers`` as an ordered list of (name, entry).

        A dict keyed by manager name keeps its key order; a list of entries carries
        each manager's ``name`` (left out of the returned entry).
        """
        managers = summary.get("managers")
        if isinstance(managers, dict):
            return list(managers.items())
        self.assertIsInstance(managers, list, sorted(summary))
        listed = []
        for entry in managers:
            self.assertIsInstance(entry, dict, managers)
            self.assertIn("name", entry, entry)
            listed.append((entry["name"], {k: v for k, v in entry.items() if k != "name"}))
        return listed

    def manager(self, summary, name):
        found = dict(self.managers(summary))
        self.assertIn(name, found, found)
        self.assertIsInstance(found[name], dict, found)
        return found[name]

    def package_list(self, data):
        """The flat ``packages`` list of a summary or detail file."""
        items = data.get("packages")
        self.assertIsInstance(items, list, f"packages: {type(items).__name__}")
        return items

    def npm_items(self, summary):
        items = self.detail(summary).get("npm_packages")
        self.assertIsInstance(items, list, f"detail npm_packages: {items!r}")
        return items

    def pip_items(self, summary):
        items = self.detail(summary).get("pip_packages")
        self.assertIsInstance(items, list, f"detail pip_packages: {items!r}")
        return items

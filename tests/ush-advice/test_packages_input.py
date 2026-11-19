"""The package list in the ush-advice summary (plan 075, M1).

``advice.py`` reads the newest ``<data dir>/work/packages-*.detail.json`` written by
``ush-packages`` (newest by file name) and lists its packages:

- summary ``packages``: ``[{id: "p<n>", manager, name, version}]`` or null when the input
  is not read; summary ``package_lookups``: the de-duplicated ``[{manager, name}]``;
- summary ``packages_input``: ``{status, reason, generated_at, elevated, listed, skipped,
  managers}``; ``status`` ``read``/``none``/``unreadable``; ``skipped`` counts per cause
  ``from_baseline``, ``unreadable``, ``no_version``; ``managers`` is ``{manager: {status,
  reason}}`` copied from the input's ``sources``;
- ``truncated_packages`` and ``truncated_lookups``; the advice detail file holds the whole
  ``packages`` and ``package_lookups``; ``--detail p<n>`` prints one package.

The ush-packages detail files here are written by hand with the field shapes of
``skills/ush-packages/scripts/packages.py`` (``sources`` a list of ``{name, status,
reason}``, one list per source of ``{key, **item}``). Every name, version and path is
invented; PowerShell is faked and never starts.
"""

import json
import os
import re
import unittest
from datetime import datetime, timedelta, timezone

from .fakes import (
    AdviceTestCase,
    FakePowerShell,
    exploited_finding,
    findings_doc,
    issue_finding,
    machine_touched,
    search,
    update_finding,
)

RUN_NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)

SOURCE_LISTS = ("pip_packages", "npm_packages", "pipx_packages", "uv_tools",
                "conda_packages", "winget_packages", "vscode_extensions")

INVENTED_HOME = "C:\\Users\\Invented"
PYTHON_A = INVENTED_HOME + "\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
PYTHON_B = INVENTED_HOME + "\\AppData\\Local\\Programs\\Python\\Python313\\python.exe"
NPM_ROOT = INVENTED_HOME + "\\AppData\\Roaming\\npm\\node_modules"
WINGET_FOLDER = (INVENTED_HOME + "\\AppData\\Local\\Packages\\"
                 "Invented.DesktopAppInstaller_0000000000000\\LocalState")
VSCODE_ROOT = INVENTED_HOME + "\\.vscode\\extensions"
CONDA_ROOT = INVENTED_HOME + "\\invented-conda"

ID_PATTERN = re.compile(r"^p[1-9][0-9]*$")


# --- invented ush-packages items ---------------------------------------------------

def pip_item(name, version, python=PYTHON_A, kind="install", **extra):
    item = {"python": python, "folder": kind, "name": name, "version": version,
            "status": "read", "reason": None}
    item.update(extra)
    return {"key": f"pip:{python}|{kind}|{name.casefold()}", **item}


def npm_item(name, version, status="read", **extra):
    folder = NPM_ROOT + "\\" + name
    item = {"name": name, "version": version, "status": status,
            "reason": None if status == "read" else "Invented: package.json could not be read",
            "folder": folder}
    if status == "unreadable":
        item["version"] = None
        item["unread_fields"] = ["version"]
    item.update(extra)
    return {"key": f"npm:{name.casefold()}", **item}


def winget_item(name, package_id, version, **extra):
    item = {"name": name, "id": package_id, "version": version, "versions_recorded": 1,
            "source": "winget", "folder": WINGET_FOLDER, "status": "read", "reason": None}
    item.update(extra)
    return {"key": f"winget:winget|{package_id.casefold()}", **item}


def vscode_item(name, version, **extra):
    folder = f"{VSCODE_ROOT}\\{name}-{version}"
    item = {"name": name, "version": version, "folder": folder, "status": "read",
            "reason": None}
    item.update(extra)
    return {"key": f"vscode:{name.casefold()}|{folder.casefold()}", **item}


def conda_item(name, version, environment="base", **extra):
    item = {"name": name, "version": version, "build": "py312_0",
            "environment": environment, "folder": CONDA_ROOT, "status": "read",
            "reason": None}
    item.update(extra)
    return {"key": f"conda:{environment}|{name.casefold()}", **item}


def packages_detail(lists, generated_at="2026-11-01T10:00:00+00:00", elevated=False,
                    statuses=None, stamp="20261101-100000"):
    """An invented ush-packages detail file: one list per source, ``sources`` read or
    empty by its list unless ``statuses`` names ``(status, reason)`` for a source."""
    statuses = statuses or {}
    sources = []
    for name in SOURCE_LISTS:
        status, reason = statuses.get(name, ("read" if lists.get(name) else "empty", None))
        sources.append({"name": name, "status": status, "reason": reason})
    doc = {
        "schema_version": 1,
        "skill": "ush-packages",
        "generated_at": generated_at,
        "elevated": elevated,
        "sources": sources,
        "comparison": {name: "no_baseline" for name in SOURCE_LISTS},
        "packages": [],
        "changes": [],
    }
    for name in SOURCE_LISTS:
        doc[name] = list(lists.get(name, []))
    doc["summary_file"] = (INVENTED_HOME + "\\ush-data\\work\\"
                           f"packages-{stamp}.summary.json")
    return doc


def k1_lists():
    return {
        "pip_packages": [pip_item("contoso-lib", "1.2.0"),
                         pip_item("fabrikam-old", "0.9.0", from_baseline=True)],
        "npm_packages": [npm_item("litware", None, status="unreadable")],
        "winget_packages": [winget_item("Contoso Tool", "Contoso.Tool", "3.1")],
        "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")],
    }


def all_strings(value):
    """Every string in a parsed JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from all_strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from all_strings(inner)


class TestPackagesInput(AdviceTestCase):
    def write_packages(self, data_dir, doc, stamp="20261101-100000"):
        work = data_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        path = work / f"packages-{stamp}.detail.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return path

    def run_with(self, doc, data_dir=None, now=RUN_NOW, stamp="20261101-100000"):
        data_dir = data_dir or self.data_dir()
        self.write_packages(data_dir, doc, stamp=stamp)
        return self.collect(FakePowerShell(), data_dir=data_dir, now=now)

    def packages_input(self, summary):
        value = summary.get("packages_input")
        self.assertIsInstance(value, dict, f"packages_input: {value!r}")
        return value

    def note_texts(self, summary):
        return [f"{item.get('what')} {item.get('reason')}"
                for item in self.not_checked(summary)]

    # K1
    def test_read_items_only_name_and_version(self):
        summary = self.run_with(packages_detail(k1_lists()))
        packages = self.items(summary, "packages")

        self.assertEqual([(p.get("manager"), p.get("name"), p.get("version"))
                          for p in packages],
                         [("pip", "contoso-lib", "1.2.0"),
                          ("winget", "Contoso.Tool", "3.1"),
                          ("vscode", "contoso.theme", "1.4.0")], packages)
        for package in packages:
            with self.subTest(package=package.get("name")):
                self.assertEqual(set(package), {"id", "manager", "name", "version"}, package)
                self.assertRegex(str(package.get("id")), ID_PATTERN)
        self.assertEqual(len({p.get("id") for p in packages}), 3, packages)

        skipped = self.packages_input(summary).get("skipped")
        self.assertIsInstance(skipped, dict, skipped)
        self.assertEqual(skipped.get("from_baseline"), 1, skipped)
        self.assertEqual(skipped.get("unreadable"), 1, skipped)

    # final review (judge fix 075 #3): a skipped item is named, never only counted
    def test_skipped_items_in_not_checked(self):
        summary = self.run_with(packages_detail(k1_lists()))
        notes = self.notes_about(summary, "packages skipped")
        reasons = sorted(str(item.get("reason")) for item in notes)
        self.assertEqual(len(notes), 2, notes)
        self.assertTrue(any("from_baseline" in r and "1 " in r for r in reasons), reasons)
        self.assertTrue(any("unreadable" in r and "1 " in r for r in reasons), reasons)

        with self.subTest("clean data gives no skipped item"):
            clean = {"pip_packages": [pip_item("contoso-lib", "1.2.0")],
                     "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")]}
            summary = self.run_with(packages_detail(clean), data_dir=self.data_dir())
            self.assertEqual(self.notes_about(summary, "packages skipped"), [],
                             self.not_checked(summary))

    # K2
    def test_newest_run_wins(self):
        data_dir = self.data_dir()
        older = packages_detail(
            {"pip_packages": [pip_item("contoso-lib", "1.2.0")]},
            generated_at="2026-11-01T10:00:00+00:00", elevated=False,
            stamp="20261101-100000")
        newer = packages_detail(
            {"pip_packages": [pip_item("contoso-lib", "1.3.0")],
             "winget_packages": [winget_item("Contoso Tool", "Contoso.Tool", "3.1")]},
            generated_at="2026-11-02T09:30:00+00:00", elevated=True,
            stamp="20261102-093000")
        # The newer file is written first and the older one gets the later mtime:
        # only the file name orders the runs.
        newer_path = self.write_packages(data_dir, newer, stamp="20261102-093000")
        older_path = self.write_packages(data_dir, older, stamp="20261101-100000")
        stat = newer_path.stat()
        os.utime(older_path, (stat.st_atime + 3600, stat.st_mtime + 3600))

        summary = self.collect(FakePowerShell(), data_dir=data_dir, now=RUN_NOW)
        packages_input = self.packages_input(summary)
        self.assertEqual(packages_input.get("status"), "read", packages_input)
        self.assertEqual(packages_input.get("generated_at"), "2026-11-02T09:30:00+00:00",
                         packages_input)
        self.assertIs(packages_input.get("elevated"), True, packages_input)
        self.assertEqual([(p.get("manager"), p.get("name"), p.get("version"))
                          for p in self.items(summary, "packages")],
                         [("pip", "contoso-lib", "1.3.0"),
                          ("winget", "Contoso.Tool", "3.1")])

    # K3
    def test_missing_unreadable_and_empty(self):
        with self.subTest("no packages-*.detail.json"):
            summary = self.collect(FakePowerShell(), data_dir=self.data_dir(), now=RUN_NOW)
            self.assertIn("packages", summary, summary.keys())
            self.assertIsNone(summary["packages"], summary["packages"])
            self.assertEqual(self.packages_input(summary).get("status"), "none")
            notes = [text for text in self.note_texts(summary)
                     if "ush-packages" in text and re.search(r"not (been )?run", text)]
            self.assertTrue(notes, self.not_checked(summary))

        with self.subTest("a detail file that is not JSON"):
            data_dir = self.data_dir()
            work = data_dir / "work"
            work.mkdir(parents=True)
            (work / "packages-20261101-100000.detail.json").write_text(
                "{ invented, not json", encoding="utf-8")
            summary = self.collect(FakePowerShell(), data_dir=data_dir, now=RUN_NOW)
            packages_input = self.packages_input(summary)
            self.assertEqual(packages_input.get("status"), "unreadable", packages_input)
            reason = packages_input.get("reason")
            self.assertIsInstance(reason, str, packages_input)
            self.assertRegex(reason, r"JSONDecodeError|ValueError|UnicodeDecodeError")
            self.assertIn("packages", summary, summary.keys())
            self.assertIsNone(summary["packages"], "an unreadable input is never []")
            self.assertTrue([text for text in self.note_texts(summary) if "packag" in text],
                            self.not_checked(summary))

        with self.subTest("every source list empty"):
            summary = self.run_with(packages_detail({}))
            self.assertEqual(self.packages_input(summary).get("status"), "read")
            self.assertEqual(summary.get("packages"), [])

        with self.subTest("pip_packages source unreadable with no items"):
            doc = packages_detail(
                {"vscode_extensions": [vscode_item("contoso.theme", "1.4.0")]},
                statuses={"pip_packages": ("unreadable",
                                           "Invented: no Python could be listed")})
            summary = self.run_with(doc)
            managers = self.packages_input(summary).get("managers")
            self.assertIsInstance(managers, dict, managers)
            pip = managers.get("pip")
            self.assertIsInstance(pip, dict, managers)
            self.assertEqual(pip.get("status"), "unreadable", pip)
            self.assertNotIn(0, [value for value in pip.values()
                                 if isinstance(value, int) and not isinstance(value, bool)],
                             f"pip is counted as 0 packages: {pip}")
            pip_notes = [item for item in self.not_checked(summary)
                         if "pip" in str(item.get("what"))]
            self.assertTrue(pip_notes, self.not_checked(summary))
            self.assertEqual([p for p in self.items(summary, "packages")
                              if p.get("manager") == "pip"], [])

    # K4
    def test_no_path_or_key_leaves(self):
        lists = k1_lists()
        lists["pip_packages"].append(pip_item("contoso-lib", "1.3.0", python=PYTHON_B))
        lists["conda_packages"] = [conda_item("contoso-conda-lib", "2.0.0")]
        doc = packages_detail(lists)
        summary = self.run_with(doc)
        detail = self.detail_of(summary)

        forbidden = set()
        for name in SOURCE_LISTS:
            for item in doc[name]:
                forbidden.add(item["key"])
                for field in ("folder", "python"):
                    if isinstance(item.get(field), str) and "\\" in item[field]:
                        forbidden.add(item[field])
        forbidden.add(doc["summary_file"])

        for label, value in (("summary", summary), ("detail", detail),
                             ("packages", summary.get("packages"))):
            strings = list(all_strings(value))
            with self.subTest(label):
                for text in strings:
                    folded = text.casefold().replace("/", "\\")
                    self.assertNotIn("\\users\\invented", folded, text[:200])
                    for bad in forbidden:
                        self.assertNotIn(bad.casefold(), text.casefold(), text[:200])

    # K5
    def test_budget_cuts_packages_first(self):
        total = 3000
        pip = [pip_item(f"contoso-invented-package-{n:05d}-with-a-longer-name",
                        f"1.{n}.0") for n in range(total)]
        doc = packages_detail({"pip_packages": pip})

        cves = [f"CVE-2026-{61000 + n}" for n in range(3)]
        findings = [update_finding("2026-11", "KB5099911", "26200.7001",
                                   cves=[(cve, "Important") for cve in cves])]
        findings += [exploited_finding(cve) for cve in cves]
        findings += [issue_finding(
            f"Invented issue {n}",
            f"https://learn.microsoft.com/windows/release-health/invented-pkg-issue-{n}")
            for n in range(3)]
        findings_file = findings_doc(
            [search("release-info"), search("msrc"), search("kev"),
             search("release-health")], findings)

        small_dir = self.data_dir()
        # A small run with nothing cut and nothing skipped, so only the cut notes differ.
        self.write_packages(small_dir, packages_detail(
            {"pip_packages": [pip_item("contoso-lib", "1.2.0")]}))
        small = self.collect_findings(FakePowerShell(), findings_file, data_dir=small_dir,
                                      now=RUN_NOW)

        data_dir = self.data_dir()
        self.write_packages(data_dir, doc)
        code, stdout, stderr = self.run_findings(data_dir, FakePowerShell(), findings_file,
                                                 now=RUN_NOW)
        self.assertEqual(code, 0, f"--findings run failed: {stderr[:400]}")
        limit = getattr(self.advice, "SUMMARY_MAX_CHARS", None)
        self.assertIsInstance(limit, int, "advice.SUMMARY_MAX_CHARS is missing")
        self.assertLessEqual(len(stdout), limit, f"summary is {len(stdout)} chars")
        summary = self.parse(stdout)
        detail = self.detail_of(summary)

        all_packages = detail.get("packages")
        self.assertIsInstance(all_packages, list, "detail file has no packages section")
        self.assertEqual(len(all_packages), total)
        shown = self.items(summary, "packages")
        truncated_packages = summary.get("truncated_packages")
        self.assertIsInstance(truncated_packages, int, truncated_packages)
        self.assertGreater(truncated_packages, 0)
        self.assertEqual(len(shown) + truncated_packages, total)
        self.assertEqual(shown, all_packages[:len(shown)], "packages not cut from the end")

        self.assertEqual(summary.get("truncated"), 0, "issues were cut")
        self.assertEqual(summary.get("truncated_exploited"), 0, "exploited were cut")
        self.assertEqual(len(self.items(summary, "issues")), 3)
        self.assertEqual(len(self.items(summary, "exploited")), 3)

        all_lookups = detail.get("package_lookups")
        self.assertIsInstance(all_lookups, list, "detail file has no package_lookups")
        self.assertEqual(len(all_lookups), total)
        lookups = self.items(summary, "package_lookups")
        truncated_lookups = summary.get("truncated_lookups")
        self.assertIsInstance(truncated_lookups, int, truncated_lookups)
        self.assertGreater(truncated_lookups, 0)
        self.assertEqual(len(lookups) + truncated_lookups, total)
        self.assertEqual(lookups, all_lookups[:len(lookups)], "lookups not cut from the end")

        self.assertGreater(len(self.not_checked(summary)), len(self.not_checked(small)),
                           self.not_checked(summary))
        self.assertTrue([text for text in self.note_texts(summary) if "packages" in text],
                        self.not_checked(summary))

        last = all_packages[-1]
        self.assertEqual(last.get("name"),
                         f"contoso-invented-package-{total - 1:05d}-with-a-longer-name")
        code, stdout, stderr = self.run_main(data_dir, machine_touched, now=RUN_NOW,
                                             extra=["--detail", str(last.get("id"))])
        self.assertEqual(code, 0, stderr[:300])
        item = self.parse(stdout)
        self.assertIsInstance(item, dict, stdout[:300])
        self.assertEqual(item.get("id"), last.get("id"), item)
        self.assertEqual(item.get("name"), last.get("name"), item)
        self.assertEqual(item.get("version"), last.get("version"), item)

    # K7
    def test_ids_stable(self):
        def ids_of(summary):
            return {(p.get("manager"), p.get("name"), p.get("version")): p.get("id")
                    for p in self.items(summary, "packages")}

        lists = {
            "pip_packages": [pip_item("contoso-lib", "1.2.0"),
                             pip_item("fabrikam-util", "4.0.1")],
            "npm_packages": [npm_item("litware-cli", "2.5.0")],
            "winget_packages": [winget_item("Contoso Tool", "Contoso.Tool", "3.1")],
            "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")],
        }
        data_dir = self.data_dir()
        self.write_packages(data_dir, packages_detail(lists))
        first = ids_of(self.collect(FakePowerShell(), data_dir=data_dir, now=RUN_NOW))
        second = ids_of(self.collect(FakePowerShell(), data_dir=data_dir,
                                     now=RUN_NOW + timedelta(hours=1)))
        self.assertEqual(len(first), 5, first)
        self.assertEqual(second, first)

        removed = ("pip", "fabrikam-util", "4.0.1")
        lists["pip_packages"] = [pip_item("contoso-lib", "1.2.0")]
        self.write_packages(data_dir, packages_detail(
            lists, generated_at="2026-11-02T10:00:00+00:00", stamp="20261102-100000"),
            stamp="20261102-100000")
        third = ids_of(self.collect(FakePowerShell(), data_dir=data_dir,
                                    now=RUN_NOW + timedelta(hours=2)))
        expected = {key: value for key, value in first.items() if key != removed}
        self.assertEqual(third, expected)

    # K8
    def test_lookups_deduplicated(self):
        lists = {
            "pip_packages": [pip_item("contoso-lib", "1.2.0", python=PYTHON_A),
                             pip_item("contoso-lib", "1.3.0", python=PYTHON_B)],
            "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")],
        }
        summary = self.run_with(packages_detail(lists))

        pip = [p for p in self.items(summary, "packages")
               if p.get("manager") == "pip" and p.get("name") == "contoso-lib"]
        self.assertEqual(len(pip), 2, pip)
        self.assertEqual(sorted(p.get("version") for p in pip), ["1.2.0", "1.3.0"])
        self.assertNotEqual(pip[0].get("id"), pip[1].get("id"), pip)

        lookups = self.items(summary, "package_lookups")
        for lookup in lookups:
            self.assertEqual(set(lookup), {"manager", "name"}, lookup)
        self.assertEqual([lookup for lookup in lookups
                          if lookup.get("manager") == "pip"
                          and lookup.get("name") == "contoso-lib"],
                         [{"manager": "pip", "name": "contoso-lib"}])


    # K3, review fix (M1/code-review round 1): an unreadable manager lists nothing
    def test_unreadable_manager_lists_nothing(self):
        for status, note in ((None, "not in the detail file"), ("partial", "unknown status")):
            with self.subTest(status=status):
                doc = packages_detail(k1_lists())
                if status is None:
                    doc["sources"] = [entry for entry in doc["sources"]
                                      if entry["name"] != "winget_packages"]
                else:
                    for entry in doc["sources"]:
                        if entry["name"] == "winget_packages":
                            entry["status"] = status
                summary = self.run_with(doc, data_dir=self.data_dir())
                info = self.packages_input(summary)
                self.assertEqual(info["managers"]["winget"]["status"], "unreadable")
                self.assertIn(note, info["managers"]["winget"]["reason"])
                managers = [p["manager"] for p in self.items(summary, "packages")]
                self.assertNotIn("winget", managers)
                self.assertEqual(sorted(set(managers)), ["pip", "vscode"])
                self.assertTrue(any(item.get("what") == "packages winget"
                                    for item in self.not_checked(summary)),
                                self.note_texts(summary))
                self.assertNotIn("winget", [lookup["manager"]
                                            for lookup in summary["package_lookups"]])

    # K6
    def test_sources_match_ush_packages(self):
        """Every PACKAGE_SOURCES entry is a source of ush-packages' READ_MANAGERS,
        in the order of SOURCES; ush-packages may read more sources than advice
        looks up (plan 079: those are named in advice's not_checked)."""
        from tests.skill_loader import load_script
        packages = load_script("ush-packages", "packages")
        advice = load_script("ush-advice", "advice")
        inverse = {source: manager for manager, source in packages.READ_MANAGERS.items()}
        for source, manager in advice.PACKAGE_SOURCES.items():
            self.assertEqual(inverse.get(source), manager, source)
        self.assertEqual(tuple(advice.PACKAGE_SOURCES),
                         tuple(s for s in packages.SOURCES if s in advice.PACKAGE_SOURCES))


OTHER_SOURCES_WHAT = "packages of other managers"


class TestOtherSources(AdviceTestCase):
    """Plan 079, M2: the ush-packages sources advice does not look up are named once."""

    write_packages = TestPackagesInput.write_packages
    run_with = TestPackagesInput.run_with

    # K6
    def test_unlooked_sources_named(self):
        doc = packages_detail({"pip_packages": [pip_item("contoso-lib", "1.2.0")]})
        doc["sources"] += [
            {"name": "dotnet_tools", "status": "empty", "reason": None},
            {"name": "nuget_packages", "status": "read", "reason": None},
            {"name": "psgallery_modules", "status": "read", "reason": None},
        ]
        doc["comparison"].update({"dotnet_tools": "no_baseline",
                                  "nuget_packages": "no_baseline",
                                  "psgallery_modules": "no_baseline"})
        doc["dotnet_tools"] = []
        doc["nuget_packages"] = [{
            "key": "nuget:contoso.json", "name": "contoso.json", "version": "13.0.1",
            "versions_found": 1,
            "folder": INVENTED_HOME + "\\.nuget\\packages\\contoso.json",
            "status": "read", "reason": None}]
        doc["psgallery_modules"] = [{
            "key": "psgallery:user-powershell|contoso.az", "name": "Contoso.Az",
            "version": "1.10.0", "versions_found": 2, "repository": "PSGallery",
            "module_folder": "user-powershell",
            "folder": INVENTED_HOME + "\\Documents\\PowerShell\\Modules\\Contoso.Az",
            "status": "read", "reason": None}]
        summary = self.run_with(doc)

        notes = [item for item in self.not_checked(summary)
                 if item.get("what") == OTHER_SOURCES_WHAT]
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        self.assertEqual(notes[0].get("reason"),
                         "ush-advice does not look up the ush-packages sources "
                         "nuget_packages, psgallery_modules", notes)

        with self.subTest("only the 7 known sources"):
            summary = self.run_with(packages_detail(k1_lists()), data_dir=self.data_dir())
            notes = [item for item in self.not_checked(summary)
                     if item.get("what") == OTHER_SOURCES_WHAT]
            self.assertEqual(notes, [], self.not_checked(summary))

    # Plan 080, M2, K5
    def test_step3_sources_named(self):
        doc = packages_detail({"pip_packages": [pip_item("contoso-lib", "1.2.0")]})
        doc["sources"] += [
            {"name": "choco_packages", "status": "read", "reason": None},
            {"name": "scoop_apps", "status": "read", "reason": None},
            {"name": "vcpkg_packages", "status": "read", "reason": None},
        ]
        doc["comparison"].update({"choco_packages": "no_baseline",
                                  "scoop_apps": "no_baseline",
                                  "vcpkg_packages": "no_baseline"})
        doc["choco_packages"] = [{
            "key": "choco:contoso.cli", "name": "Contoso.Cli", "version": "1.10.0",
            "folder": "%ProgramData%\\chocolatey\\lib\\contoso.cli",
            "status": "read", "reason": None}]
        doc["scoop_apps"] = [{
            "key": "scoop:user|fabrikam", "name": "fabrikam", "version": "2.47.1",
            "bucket": "main", "root": "user",
            "folder": INVENTED_HOME + "\\scoop\\apps\\fabrikam",
            "status": "read", "reason": None}]
        doc["vcpkg_packages"] = [{
            "key": "vcpkg:litware:x64-windows", "name": "litware", "version": "1.3.1",
            "triplet": "x64-windows",
            "folder": "C:\\Invented\\vcpkg\\installed\\x64-windows",
            "status": "read", "reason": None}]
        summary = self.run_with(doc)

        notes = [item for item in self.not_checked(summary)
                 if item.get("what") == OTHER_SOURCES_WHAT]
        self.assertEqual(len(notes), 1, self.not_checked(summary))
        self.assertEqual(notes[0].get("reason"),
                         "ush-advice does not look up the ush-packages sources "
                         "choco_packages, scoop_apps, vcpkg_packages", notes)


if __name__ == "__main__":
    unittest.main()

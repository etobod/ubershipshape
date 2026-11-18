"""winget and VS Code latest versions read from saved registry answers (plan 078, M1).

Interface under test, beyond ``fakes.py``, ``test_packages_input.py`` and
``test_package_kind.py``:

- A ``package`` finding of manager ``winget`` or ``vscode`` has the common fields plus
  ``manager``, ``package`` and ``registry_file`` (a non-empty text), never
  ``latest_version``. Every other manager keeps ``latest_version`` and never has
  ``registry_file``. A finding that breaks this exits 2 and stderr names the entry
  number and the field.
- ``registry_file`` is resolved against ``<data dir>/work/`` and read only when it is a
  bare name matching ``advice-registry-[0-9A-Za-z-]+\\.json`` of an existing file.
- winget: the git trees answer ``{sha, url, tree, truncated}``; a version folder is a
  ``tree`` entry without ``/`` holding a blob ``<path>/<package>.yaml``; numeric folders
  are candidates, the rest are counted in ``not_numeric``.
- vscode: the ``extensionquery`` answer ``results[0].extensions[]``; exactly one extension
  ``publisherName.extensionName`` equal to ``package`` (case-folded); versions with the
  property ``Microsoft.VisualStudio.Code.PreRelease`` = ``true`` are counted in
  ``pre_release``; a version listed once per target platform is one version.
- The detail file's finding gets ``latest_version`` and ``registry`` ``{file, status,
  reason, versions, not_numeric, pre_release}``; a failure gives ``status``
  ``unreadable``, ``latest_version`` null and a ``not_checked`` item ``package finding
  w<n>`` with the reason.

Every name, version, sha and answer here is invented; PowerShell is faked.
"""

import hashlib
import json
import re
import unittest

from . import test_package_kind as kind_tests
from . import test_packages_input as input_tests
from .fakes import FakePowerShell, findings_doc, search

PackageTestCase = kind_tests.PackageTestCase
package_finding = kind_tests.package_finding
RUN_NOW = input_tests.RUN_NOW
pip_item = input_tests.pip_item
winget_item = input_tests.winget_item
vscode_item = input_tests.vscode_item
packages_detail = input_tests.packages_detail

PRE_RELEASE_KEY = "Microsoft.VisualStudio.Code.PreRelease"
WINGET_FILE = "advice-registry-20261118-120000-1.json"
VSCODE_FILE = "advice-registry-20261118-120000-2.json"
WINGET_URL = ("https://api.github.com/repos/microsoft/winget-pkgs/git/trees/"
              "master:manifests/c/Contoso/Tool?recursive=1")
VSCODE_URL = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"


def registry_finding(manager, package, registry_file, url=None, query=None,
                     title=None, published=None):
    """An invented winget or vscode ``package`` finding naming a registry file."""
    return {
        "kind": "package",
        "url": url or (WINGET_URL if manager == "winget" else VSCODE_URL),
        "title": title or f"Invented registry answer for {package}",
        "query": query if query is not None else package,
        "published": published,
        "manager": manager,
        "package": package,
        "registry_file": registry_file,
    }


# --- invented winget git trees answers ---------------------------------------------

def _sha(text):
    return hashlib.sha1(f"invented {text}".encode()).hexdigest()


def tree_folder(path):
    sha = _sha(path)
    return {"path": path, "mode": "040000", "type": "tree", "sha": sha,
            "url": f"https://api.github.com/repos/microsoft/winget-pkgs/git/trees/{sha}"}


def tree_blob(path, size=1024):
    sha = _sha(path)
    return {"path": path, "mode": "100644", "type": "blob", "sha": sha, "size": size,
            "url": f"https://api.github.com/repos/microsoft/winget-pkgs/git/blobs/{sha}"}


def version_folder(version, package_id):
    """A version folder with the package's manifests, as the trees API lists it."""
    return [tree_folder(version),
            tree_blob(f"{version}/{package_id}.installer.yaml"),
            tree_blob(f"{version}/{package_id}.locale.en-US.yaml"),
            tree_blob(f"{version}/{package_id}.yaml", size=512)]


def trees_answer(entries, truncated=False):
    return {
        "sha": _sha("root"),
        "url": "https://api.github.com/repos/microsoft/winget-pkgs/git/trees/"
               + _sha("root"),
        "tree": list(entries),
        "truncated": truncated,
    }


def winget_answer(versions, package_id="Contoso.Tool", truncated=False):
    entries = []
    for version in versions:
        entries.extend(version_folder(version, package_id))
    return trees_answer(entries, truncated=truncated)


# --- invented VS Code extensionquery answers ---------------------------------------

def vscode_version(version, pre_release=False, target_platform=None):
    properties = [
        {"key": "Microsoft.VisualStudio.Code.Engine", "value": "^1.90.0"},
        {"key": "Microsoft.VisualStudio.Code.ExtensionKind", "value": "workspace"},
    ]
    if pre_release:
        properties.append({"key": PRE_RELEASE_KEY, "value": "true"})
    entry = {"version": version, "flags": "validated",
             "lastUpdated": "2026-11-10T08:00:00.000Z", "properties": properties}
    if target_platform is not None:
        entry["targetPlatform"] = target_platform
    return entry


def extension(publisher, name, versions):
    return {
        "publisher": {"publisherId": "00000000-0000-0000-0000-000000000001",
                      "publisherName": publisher, "displayName": publisher.title()},
        "extensionId": "00000000-0000-0000-0000-000000000002",
        "extensionName": name,
        "displayName": f"Invented {name}",
        "flags": "validated, public",
        "versions": list(versions),
    }


def extension_answer(extensions):
    count = {"name": "TotalCount", "count": len(extensions)}
    metadata = [{"metadataType": "ResultCount", "metadataItems": [count]}]
    return {"results": [{"extensions": list(extensions), "pagingToken": None,
                         "resultMetadata": metadata}]}


def vscode_answer(versions, publisher="contoso", name="theme"):
    return extension_answer([extension(publisher, name, versions)])


class RegistryTestCase(PackageTestCase):
    def run_registry(self, lists, findings, files=None, outside=None, status="read"):
        """Write the ush-packages detail file, the registry files (``{name: answer}``
        under ``work/``; ``outside`` the same, in the data directory itself) and run
        with ``--findings``; return the summary."""
        data_dir = self.data_dir()
        self.write_packages(data_dir, packages_detail(lists))
        for folder, written in ((data_dir / "work", files), (data_dir, outside)):
            for name, answer in (written or {}).items():
                text = answer if isinstance(answer, str) else json.dumps(answer)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / name).write_text(text, encoding="utf-8")
        doc = findings_doc([search("packages", status)], findings)
        return self.collect_findings(FakePowerShell(), doc, data_dir=data_dir,
                                     now=RUN_NOW)

    def detail_finding(self, summary, finding_id):
        findings = self.detail_of(summary).get("findings")
        self.assertIsInstance(findings, list, "detail file has no findings")
        found = [f for f in findings if f.get("id") == finding_id]
        self.assertEqual(len(found), 1, findings)
        return found[0]

    def registry_of(self, finding):
        registry = finding.get("registry")
        self.assertIsInstance(registry, dict, finding)
        return registry


class TestWinget(RegistryTestCase):
    # K1
    def test_highest_numeric_folder(self):
        entries = []
        for version in ("3.10.0.2", "3.10.0.10", "3.10.0", "3.9"):
            entries.extend(version_folder(version, "Contoso.Tool"))
        entries.extend(version_folder("3.11-preview", "Contoso.Tool"))
        entries.extend([tree_folder("Addon"),
                        tree_folder("Addon/1.0.0"),
                        tree_blob("Addon/1.0.0/Contoso.Tool.Addon.yaml"),
                        tree_blob("Addon/1.0.0/Contoso.Tool.Addon.installer.yaml")])
        entries.extend([tree_folder("4"),
                        tree_folder("4/4.0.1"),
                        tree_blob("4/4.0.1/Contoso.Tool.4.yaml"),
                        tree_blob("4/4.0.1/Contoso.Tool.4.installer.yaml")])
        lists = {"winget_packages": [winget_item("Contoso Tool", "Contoso.Tool",
                                                 "3.10.0.2")]}
        summary = self.run_registry(
            lists, [registry_finding("winget", "Contoso.Tool", WINGET_FILE)],
            files={WINGET_FILE: trees_answer(entries)})

        item = self.package(summary, "winget", "Contoso.Tool")
        self.assertIs(item.get("checked"), True, item)
        self.assertEqual(item.get("finding_id"), "w1", item)
        self.assertEqual(item.get("latest_version"), "3.10.0.10", item)
        self.assertIs(item.get("newer_available"), True, item)

        finding = self.detail_finding(summary, "w1")
        self.assertEqual(finding.get("latest_version"), "3.10.0.10", finding)
        registry = self.registry_of(finding)
        self.assertEqual(registry.get("file"), WINGET_FILE, registry)
        self.assertEqual(registry.get("status"), "read", registry)
        self.assertIsNone(registry.get("reason"), registry)
        self.assertEqual(registry.get("versions"), 4, registry)
        self.assertEqual(registry.get("not_numeric"), 1, registry)
        self.assertIn("pre_release", registry, registry)
        self.assertIsNone(registry["pre_release"], registry)


class TestVscode(RegistryTestCase):
    # K2
    def test_release_not_pre_release(self):
        answer = vscode_answer([
            vscode_version("2.1.0", pre_release=True),
            vscode_version("2.0.9"),
            vscode_version("2.0.10", target_platform="win32-x64"),
            vscode_version("2.0.10", target_platform="linux-x64"),
            vscode_version("2.0.x-insider"),
        ])
        lists = {"vscode_extensions": [vscode_item("contoso.theme", "2.0.10")]}
        summary = self.run_registry(
            lists, [registry_finding("vscode", "contoso.theme", VSCODE_FILE)],
            files={VSCODE_FILE: answer})

        item = self.package(summary, "vscode", "contoso.theme")
        self.assertIs(item.get("checked"), True, item)
        self.assertEqual(item.get("finding_id"), "w1", item)
        self.assertEqual(item.get("latest_version"), "2.0.10", item)
        self.assertIn("newer_available", item, item)
        self.assertIs(item["newer_available"], False, item)

        finding = self.detail_finding(summary, "w1")
        self.assertEqual(finding.get("latest_version"), "2.0.10", finding)
        registry = self.registry_of(finding)
        self.assertEqual(registry.get("file"), VSCODE_FILE, registry)
        self.assertEqual(registry.get("status"), "read", registry)
        self.assertEqual(registry.get("pre_release"), 1, registry)
        self.assertEqual(registry.get("not_numeric"), 1, registry)
        self.assertEqual(registry.get("versions"), 2, registry)


class TestUnreadable(RegistryTestCase):
    # K3
    def test_not_checked_cases(self):
        good_winget = winget_answer(["3.0", "3.1", "3.2"])
        cases = (
            ("missing file", "winget", WINGET_FILE, {}, None),
            ("a path out of work", "winget", "..\\x.json", {}, {"x.json": good_winget}),
            ("not an advice-registry name", "winget", "other.json",
             {"other.json": good_winget}, None),
            ("not JSON", "winget", WINGET_FILE,
             {WINGET_FILE: '{"sha": "abc", "tree": [{"path": "3.2", "ty'}, None),
            ("truncated tree", "winget", WINGET_FILE,
             {WINGET_FILE: winget_answer(["3.0", "3.1", "3.2"], truncated=True)}, None),
            ("manifests of another package", "winget", WINGET_FILE,
             {WINGET_FILE: winget_answer(["3.0", "3.2"], package_id="Other.Tool")}, None),
            ("no extension", "vscode", VSCODE_FILE,
             {VSCODE_FILE: extension_answer([])}, None),
            ("another extension", "vscode", VSCODE_FILE,
             {VSCODE_FILE: vscode_answer([vscode_version("1.5.0")], publisher="other")},
             None),
            ("only pre-release versions", "vscode", VSCODE_FILE,
             {VSCODE_FILE: vscode_answer([vscode_version("1.6.0", pre_release=True),
                                          vscode_version("1.5.0", pre_release=True)])},
             None),
        )
        lists = {"winget_packages": [winget_item("Contoso Tool", "Contoso.Tool", "3.1")],
                 "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")]}
        for label, manager, registry_file, files, outside in cases:
            with self.subTest(label):
                package = "Contoso.Tool" if manager == "winget" else "contoso.theme"
                name = "Contoso.Tool" if manager == "winget" else "contoso.theme"
                summary = self.run_registry(
                    lists, [registry_finding(manager, package, registry_file)],
                    files=files, outside=outside)

                item = self.package(summary, manager, name)
                self.assertIs(item.get("checked"), False, item)
                self.assertIsNone(item.get("latest_version"), item)
                self.assertIsNone(item.get("newer_available"), item)

                pattern = re.compile(r"(?<![0-9A-Za-z])w1(?![0-9])")
                notes = [note for note in self.not_checked(summary)
                         if pattern.search(str(note.get("what")))]
                self.assertTrue(notes, self.not_checked(summary))
                for note in notes:
                    self.assertIsInstance(note.get("reason"), str, note)
                    self.assertTrue(note["reason"].strip(), note)

                finding = self.detail_finding(summary, "w1")
                self.assertIsNone(finding.get("latest_version"), finding)
                registry = self.registry_of(finding)
                self.assertEqual(registry.get("status"), "unreadable", registry)
                self.assertIsInstance(registry.get("reason"), str, registry)
                self.assertTrue(registry["reason"].strip(), registry)
                for key in ("versions", "not_numeric", "pre_release"):
                    self.assertIn(key, registry, registry)
                    self.assertIsNone(registry[key], registry)

                counts = self.counts(summary)
                own = counts.get(manager)
                self.assertIsInstance(own, dict, counts)
                self.assertEqual(own.get("checked"), 0, counts)
                self.assertEqual(own.get("newer"), 0, counts)
                self.assertEqual(own.get("not_comparable"), 0, counts)
                self.assertEqual(counts.get("all", {}).get("newer"), 0, counts)


class TestShape(RegistryTestCase):
    # K4
    def test_either_or(self):
        winget_latest = package_finding("winget", "Contoso.Tool", "9.9")
        vscode_without = registry_finding("vscode", "contoso.theme", VSCODE_FILE)
        del vscode_without["registry_file"]
        pip_with = package_finding("pip", "contoso-lib", "1.3.0")
        pip_with["registry_file"] = WINGET_FILE
        valid = [package_finding("pip", "contoso-lib", "1.3.0"),
                 package_finding("pip", "fabrikam-util", "1.1.0"),
                 package_finding("npm", "litware-cli", "2.6.0"),
                 package_finding("npm", "northwind-cli", "1.0.0")]
        index = len(valid)
        lists = {"pip_packages": [pip_item("contoso-lib", "1.2.0"),
                                  pip_item("fabrikam-util", "1.0.0")],
                 "winget_packages": [winget_item("Contoso Tool", "Contoso.Tool", "3.1")],
                 "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")]}
        for label, bad, field in (("winget with latest_version", winget_latest,
                                   "latest_version"),
                                  ("vscode without registry_file", vscode_without,
                                   "registry_file"),
                                  ("pip with registry_file", pip_with, "registry_file")):
            with self.subTest(label):
                data_dir = self.data_dir()
                self.write_packages(data_dir, packages_detail(lists))
                code, stdout, stderr = self.run_findings(
                    data_dir, FakePowerShell(),
                    findings_doc([search("packages")], [*valid, bad]), now=RUN_NOW)
                self.assertEqual(code, 2, f"stdout={stdout[:300]!r} stderr={stderr[:300]!r}")
                self.assertRegex(stderr, rf"\b({index}|{index + 1})\b",
                                 "stderr does not name the entry number")
                self.assertIn(field, stderr, "stderr does not name the field")


class TestClean(RegistryTestCase):
    # K5
    def test_current_versions_not_flagged(self):
        lists = {"winget_packages": [winget_item("Contoso Tool", "Contoso.Tool", "3.1")],
                 "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")]}
        summary = self.run_registry(
            lists,
            [registry_finding("winget", "Contoso.Tool", WINGET_FILE),
             registry_finding("vscode", "contoso.theme", VSCODE_FILE)],
            files={WINGET_FILE: winget_answer(["2.9", "3.0", "3.1"]),
                   VSCODE_FILE: vscode_answer([vscode_version("1.4.0"),
                                               vscode_version("1.3.9")])})

        for manager, name in (("winget", "Contoso.Tool"), ("vscode", "contoso.theme")):
            with self.subTest(manager):
                item = self.package(summary, manager, name)
                self.assertIs(item.get("checked"), True, item)
                self.assertIn("newer_available", item, item)
                self.assertIs(item["newer_available"], False, item)

        all_counts = self.counts(summary).get("all")
        self.assertIsInstance(all_counts, dict, self.counts(summary))
        self.assertEqual(all_counts.get("newer"), 0, all_counts)
        self.assertEqual(all_counts.get("not_comparable"), 0, all_counts)
        self.assertEqual(self.names_finding(summary, "w1"), [], self.not_checked(summary))
        self.assertEqual(self.names_finding(summary, "w2"), [], self.not_checked(summary))
        self.assertEqual([text for text in self.note_texts(summary)
                          if "package finding" in text], [], self.not_checked(summary))

    # K6
    def test_pip_unchanged(self):
        lists = {"pip_packages": [pip_item("contoso-lib", "1.2.0")]}
        summary = self.run_registry(lists,
                                    [package_finding("pip", "contoso-lib", "1.3.0")])
        item = self.package(summary, "pip", "contoso-lib")
        self.assertIs(item.get("checked"), True, item)
        self.assertEqual(item.get("finding_id"), "w1", item)
        self.assertEqual(item.get("latest_version"), "1.3.0", item)
        self.assertIs(item.get("newer_available"), True, item)


if __name__ == "__main__":
    unittest.main()

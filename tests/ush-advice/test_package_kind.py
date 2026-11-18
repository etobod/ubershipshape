"""The ``package`` finding kind and the ``packages`` search (plan 075, M2).

Interface under test, beyond ``fakes.py`` and ``test_packages_input.py``:

- ``compare_versions(installed, latest)``, a module-level pure function: ``True`` when
  both versions are dot-separated digit runs and latest > installed (shorter one padded
  with ``0`` parts), ``False`` when not greater, ``None`` for anything else.
- Search id ``packages``; a finding of kind ``package`` has the common fields plus
  ``manager``, ``package`` and ``latest_version`` (non-empty texts, ``manager`` one of the
  ush-packages managers). Since plan 078, ``winget`` and ``vscode`` findings carry
  ``registry_file`` instead of ``latest_version`` (``test_registry_files.py``).
- With ``--findings``, every summary ``packages`` item gets ``checked`` and, when checked,
  ``finding_id``, ``latest_version`` and ``newer_available``. ``package_counts`` is
  ``{manager: {listed, checked, not_checked, newer, not_comparable}, "all": {...}}``.
- ``data/sources.json`` has ``package_domains`` (``{manager: [domains]}``), checked by
  ``load_sources``; a ``package`` finding is listed only on its manager's domains.
- ``query_warnings`` gains the reasons ``path`` and ``account``; ``account`` reads
  ``USERNAME``, ``COMPUTERNAME`` and ``USERDOMAIN`` from the module-level ``ENVIRON``,
  which these tests replace.

Every name, version, url, account and computer name is invented; PowerShell is faked.
"""

import json
import re
import unittest
from unittest import mock

from . import test_fault as fault_tests
from . import test_packages_input as input_tests
from .fakes import (
    AdviceTestCase,
    FakePowerShell,
    exploited_finding,
    findings_doc,
    firmware_finding,
    issue_finding,
    search,
    update_finding,
)

RUN_NOW = input_tests.RUN_NOW
pip_item = input_tests.pip_item
npm_item = input_tests.npm_item
winget_item = input_tests.winget_item
vscode_item = input_tests.vscode_item
packages_detail = input_tests.packages_detail
k1_lists = input_tests.k1_lists

NEUTRAL_ENVIRON = {"USERNAME": "inventedperson", "COMPUTERNAME": "INVENTED-BOX",
                   "USERDOMAIN": "INVENTED-BOX"}
K6_ENVIRON = {"USERNAME": "inventeduser", "COMPUTERNAME": "INVENTED-PC"}

DEFAULT_URLS = {
    "pip": "https://pypi.org/project/{name}/",
    "npm": "https://www.npmjs.com/package/{name}",
    "winget": "https://github.com/microsoft/winget-pkgs/tree/master/manifests/c/{name}",
    "vscode": "https://marketplace.visualstudio.com/items?itemName={name}",
}

EXPECTED_PACKAGE_DOMAINS = {
    "pip": ["pypi.org"],
    "pipx": ["pypi.org"],
    "uv": ["pypi.org"],
    "npm": ["registry.npmjs.org", "www.npmjs.com"],
    "conda": ["anaconda.org"],
    "winget": ["github.com"],
    "vscode": ["marketplace.visualstudio.com"],
}


def package_finding(manager, package, latest_version, url=None, query=None, title=None,
                    published="2026-11-10"):
    """An invented ``package`` finding with every field."""
    return {
        "kind": "package",
        "url": url or DEFAULT_URLS[manager].format(name=package),
        "title": title or f"Invented registry page of {package}",
        "query": query if query is not None else f"{package} {manager} registry",
        "published": published,
        "manager": manager,
        "package": package,
        "latest_version": latest_version,
    }


def registry_package_finding(manager, package, registry_file):
    """An invented winget or vscode ``package`` finding naming a saved registry answer
    (plan 078: these managers carry ``registry_file``, never ``latest_version``)."""
    finding = package_finding(manager, package, None)
    del finding["latest_version"]
    finding["registry_file"] = registry_file
    return finding


def invented_winget_answer(package_id, versions):
    """An invented git trees answer: one folder per version with ``<v>/<id>.yaml``."""
    tree = []
    for version in versions:
        tree.append({"path": version, "mode": "040000", "type": "tree",
                     "sha": "0" * 40, "url": "https://api.github.com/invented"})
        tree.append({"path": f"{version}/{package_id}.yaml", "mode": "100644",
                     "type": "blob", "sha": "1" * 40, "size": 512,
                     "url": "https://api.github.com/invented"})
    return {"sha": "2" * 40, "url": "https://api.github.com/invented", "tree": tree,
            "truncated": False}


def invented_vscode_answer(publisher, name, versions):
    """An invented extensionquery answer with one extension and release versions."""
    return {"results": [{"extensions": [{
        "publisher": {"publisherName": publisher}, "extensionName": name,
        "versions": [{"version": v, "flags": "validated", "properties": []}
                     for v in versions]}]}]}


class PackageTestCase(AdviceTestCase):
    def setUp(self):
        super().setUp()
        self.had_environ = hasattr(self.advice, "ENVIRON")
        patcher = mock.patch.object(self.advice, "ENVIRON", dict(NEUTRAL_ENVIRON),
                                    create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_packages(self, data_dir, doc, stamp="20261101-100000"):
        work = data_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        path = work / f"packages-{stamp}.detail.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return path

    def run_packages(self, lists, findings, status="read", reason=None, statuses=None,
                     registry_files=None):
        """Write an invented ush-packages detail file (and ``registry_files``,
        ``{name: answer}``, under ``work/``), run with ``--findings`` holding the
        ``packages`` search and ``findings``; return the summary."""
        data_dir = self.data_dir()
        self.write_packages(data_dir, packages_detail(lists, statuses=statuses))
        for name, answer in (registry_files or {}).items():
            (data_dir / "work" / name).write_text(json.dumps(answer), encoding="utf-8")
        doc = findings_doc([search("packages", status, reason)], findings)
        return self.collect_findings(FakePowerShell(), doc, data_dir=data_dir,
                                     now=RUN_NOW)

    def package(self, summary, manager, name, version=None):
        found = [p for p in self.items(summary, "packages")
                 if p.get("manager") == manager and p.get("name") == name
                 and (version is None or p.get("version") == version)]
        self.assertEqual(len(found), 1, f"{manager} {name} {version}: {found}")
        return found[0]

    def counts(self, summary):
        value = summary.get("package_counts")
        self.assertIsInstance(value, dict, f"package_counts: {value!r}")
        return value

    def note_texts(self, summary):
        return [f"{item.get('what')} {item.get('reason')}"
                for item in self.not_checked(summary)]

    def names_finding(self, summary, finding_id):
        pattern = re.compile(rf"(?<![0-9A-Za-z]){finding_id}(?![0-9])")
        return [text for text in self.note_texts(summary) if pattern.search(text)]

    def warnings_of(self, summary):
        warnings = summary.get("query_warnings")
        self.assertIsInstance(warnings, list, f"query_warnings: {warnings!r}")
        return warnings

    def reasons(self, summary, finding_id=None):
        return [w.get("reason") for w in self.warnings_of(summary)
                if finding_id is None or w.get("finding_id") == finding_id]


class TestCompareVersions(PackageTestCase):
    # K1
    def test_generic_comparator(self):
        compare = getattr(self.advice, "compare_versions", None)
        self.assertTrue(callable(compare), "advice.compare_versions is missing")
        cases = (
            (("1.2", "1.2.0"), False),
            (("1.2.0", "1.10.0"), True),
            (("2.0", "1.9"), False),
            (("1.0", "1.1rc1"), None),
            (("1!1.0", "1.0"), None),
            (("1.0+local", "1.0"), None),
        )
        for (installed, latest), expected in cases:
            with self.subTest(installed=installed, latest=latest):
                self.assertIs(compare(installed, latest), expected)


class TestPackageFindings(PackageTestCase):
    # K2
    def test_compare_and_count(self):
        # Plan 078: winget and vscode read their latest version from a registry file;
        # the not-comparable case ("1.5.0-beta") moves to npm.
        lists = k1_lists()
        lists["npm_packages"].append(npm_item("northwind-cli", "1.4.0"))
        summary = self.run_packages(lists, [
            package_finding("pip", "contoso-lib", "1.3.0"),
            registry_package_finding("winget", "Contoso.Tool",
                                     "advice-registry-20261118-120000-1.json"),
            registry_package_finding("vscode", "contoso.theme",
                                     "advice-registry-20261118-120000-2.json"),
            package_finding("npm", "northwind-cli", "1.5.0-beta"),
        ], registry_files={
            "advice-registry-20261118-120000-1.json":
                invented_winget_answer("Contoso.Tool", ["3.0", "3.1"]),
            "advice-registry-20261118-120000-2.json":
                invented_vscode_answer("contoso", "theme", ["1.4.0", "1.3.9"]),
        })
        for (manager, name, finding_id, latest, expected) in (
                ("pip", "contoso-lib", "w1", "1.3.0", True),
                ("winget", "Contoso.Tool", "w2", "3.1", False),
                ("vscode", "contoso.theme", "w3", "1.4.0", False),
                ("npm", "northwind-cli", "w4", "1.5.0-beta", None)):
            with self.subTest(package=name):
                item = self.package(summary, manager, name)
                self.assertIs(item.get("checked"), True, item)
                self.assertEqual(item.get("finding_id"), finding_id, item)
                self.assertEqual(item.get("latest_version"), latest, item)
                self.assertIn("newer_available", item, item)
                self.assertIs(item["newer_available"], expected, item)

        counts = self.counts(summary)
        self.assertEqual(counts.get("pip"), {"listed": 1, "checked": 1, "not_checked": 0,
                                             "newer": 1, "not_comparable": 0}, counts)
        self.assertIsInstance(counts.get("all"), dict, counts)
        self.assertEqual(counts["all"].get("not_checked"), 0, counts)

        with self.subTest("one finding for two installs of the same pip name"):
            lists = {"pip_packages": [
                pip_item("contoso-lib", "1.2.0", python=input_tests.PYTHON_A),
                pip_item("contoso-lib", "1.3.0", python=input_tests.PYTHON_B)]}
            summary = self.run_packages(
                lists, [package_finding("pip", "contoso-lib", "1.3.0")])
            older = self.package(summary, "pip", "contoso-lib", "1.2.0")
            newer = self.package(summary, "pip", "contoso-lib", "1.3.0")
            self.assertIs(older.get("checked"), True, older)
            self.assertIs(newer.get("checked"), True, newer)
            self.assertIs(older.get("newer_available"), True, older)
            self.assertIs(newer.get("newer_available"), False, newer)
            self.assertEqual(self.counts(summary).get("pip", {}).get("checked"), 2,
                             self.counts(summary))

    # K3
    def test_partial_search_counts_unchecked(self):
        findings = [package_finding("pip", "contoso-lib", "1.3.0")]
        summary = self.run_packages(k1_lists(), findings, status="partial",
                                    reason="Invented: only one package looked up")
        counts = self.counts(summary)
        all_counts = counts.get("all")
        self.assertIsInstance(all_counts, dict, counts)
        self.assertEqual({key: all_counts.get(key)
                          for key in ("listed", "checked", "not_checked")},
                         {"listed": 3, "checked": 1, "not_checked": 2}, all_counts)

        for item in self.items(summary, "packages"):
            with self.subTest(package=item.get("name")):
                if item.get("checked") is not True:
                    self.assertIs(item.get("checked"), False, item)
                    self.assertIsNot(item.get("newer_available"), False,
                                     f"newer_available false without a finding: {item}")
        self.assertIs(self.package(summary, "pip", "contoso-lib").get("checked"), True)

        read_summary = self.run_packages(k1_lists(), findings, status="read")
        read_notes = set(self.note_texts(read_summary))
        partial_notes = [text for text in self.note_texts(summary)
                         if "packages" in text and text not in read_notes]
        self.assertTrue(partial_notes, "no not_checked item names the partial packages "
                                       f"search: {self.not_checked(summary)}")
        for text in self.note_texts(summary):
            if "packages" in text:
                self.assertNotIn("only in the detail file", text)

        with self.subTest("unreadable pip, empty npm"):
            lists = {"winget_packages": [winget_item("Contoso Tool", "Contoso.Tool", "3.1")],
                     "vscode_extensions": [vscode_item("contoso.theme", "1.4.0")]}
            summary = self.run_packages(
                lists, [registry_package_finding("winget", "Contoso.Tool",
                                                 "advice-registry-20261118-120000-1.json")],
                registry_files={"advice-registry-20261118-120000-1.json":
                                invented_winget_answer("Contoso.Tool", ["3.0", "3.1"])},
                statuses={"pip_packages": ("unreadable",
                                           "Invented: no Python could be listed")})
            counts = self.counts(summary)
            self.assertIsInstance(counts.get("pip"), dict, counts)
            self.assertIn("listed", counts["pip"], counts)
            self.assertIsNone(counts["pip"]["listed"], counts)
            self.assertIsInstance(counts.get("npm"), dict, counts)
            self.assertEqual(counts["npm"].get("listed"), 0, counts)
            for item in self.items(summary, "packages"):
                if item.get("checked") is not True:
                    self.assertIsNot(item.get("newer_available"), False, item)

    # K4
    def test_unmatched_repeated_and_bad_shape(self):
        with self.subTest("a finding for a package not in the list"):
            summary = self.run_packages(k1_lists(), [
                package_finding("pip", "contoso-lib", "1.3.0"),
                package_finding("pip", "fabrikam-missing", "2.0.0"),
            ])
            detail = self.detail_of(summary)
            ids = [f.get("id") for f in detail.get("findings") or []]
            self.assertIn("w2", ids, detail.get("findings"))
            self.assertTrue(self.names_finding(summary, "w2"), self.not_checked(summary))
            self.assertEqual([p for p in self.items(summary, "packages")
                              if p.get("finding_id") == "w2"], [])
            self.assertEqual([p for p in self.items(summary, "packages")
                              if p.get("latest_version") == "2.0.0"], [])

        with self.subTest("a second finding for the same package"):
            summary = self.run_packages(k1_lists(), [
                package_finding("pip", "contoso-lib", "1.3.0"),
                package_finding("pip", "contoso-lib", "9.9.9"),
            ])
            item = self.package(summary, "pip", "contoso-lib")
            self.assertEqual(item.get("finding_id"), "w1", item)
            self.assertEqual(item.get("latest_version"), "1.3.0", item)
            self.assertTrue(self.names_finding(summary, "w2"), self.not_checked(summary))
            self.assertEqual([p for p in self.items(summary, "packages")
                              if p.get("finding_id") == "w2"], [])

        unknown_manager = package_finding("pip", "contoso-lib", "1.3.0")
        unknown_manager["manager"] = "cargo"
        no_latest = package_finding("pip", "contoso-lib", "1.3.0")
        del no_latest["latest_version"]
        extra_field = package_finding("pip", "contoso-lib", "1.3.0")
        extra_field["installed_version"] = "1.2.0"
        for label, bad in (("unknown manager", unknown_manager),
                           ("missing latest_version", no_latest),
                           ("extra field", extra_field)):
            with self.subTest(label):
                data_dir = self.data_dir()
                self.write_packages(data_dir, packages_detail(k1_lists()))
                fake = FakePowerShell()
                code, stdout, stderr = self.run_findings(
                    data_dir, fake, findings_doc([search("packages")], [bad]), now=RUN_NOW)
                self.assertEqual(code, 2, f"stdout={stdout[:300]!r} stderr={stderr[:300]!r}")
                self.assertEqual(fake.calls, [], "a PowerShell job ran before the check")

    # K5
    def test_domains_per_manager(self):
        lists = {"pip_packages": [pip_item("contoso-lib", "1.2.0"),
                                  pip_item("fabrikam-util", "4.0.1")],
                 "npm_packages": [npm_item("litware-cli", "2.5.0")]}
        summary = self.run_packages(lists, [
            package_finding("pip", "contoso-lib", "1.3.0",
                            url="https://pypi.org/project/contoso-lib/"),
            package_finding("npm", "litware-cli", "2.6.0",
                            url="https://pypi.org/project/litware-cli/"),
            package_finding("pip", "fabrikam-util", "4.1.0",
                            url="https://support.microsoft.com/help/invented-fabrikam-util"),
        ])
        findings = self.detail_of(summary).get("findings")
        self.assertIsInstance(findings, list, "detail file has no findings")
        listed = {f.get("id"): f.get("listed") for f in findings}
        self.assertIs(listed.get("w1"), True, findings)
        self.assertIs(listed.get("w2"), False, findings)
        self.assertIs(listed.get("w3"), False, findings)


class TestPackageWarnings(PackageTestCase):
    def run_one(self, finding):
        return self.run_packages(k1_lists(), [finding])

    # K6
    def test_path_and_account(self):
        self.assertTrue(self.had_environ, "advice.ENVIRON is missing")
        clean_url = "https://pypi.org/project/contoso-lib/"
        clean_query = "contoso-lib latest version"
        cases = (
            ("account: user name", clean_url, "inventeduser contoso-lib", "account"),
            ("account: computer name", clean_url, "invented-pc contoso-lib", "account"),
            ("path: encoded drive url",
             "https://contoso.example/C%3A%5CUsers%5Cx", clean_query, "path"),
            ("path: drive path in a query", clean_url,
             "contoso-lib C:\\Users\\x\\proj", "path"),
        )
        with mock.patch.object(self.advice, "ENVIRON", dict(K6_ENVIRON)):
            for label, url, query, reason in cases:
                with self.subTest(label):
                    summary = self.run_one(
                        package_finding("pip", "contoso-lib", "1.3.0", url=url, query=query))
                    self.assertIn(reason, self.reasons(summary, "w1"),
                                  self.warnings_of(summary))
                    texts = [json.dumps(self.warnings_of(summary)).casefold(),
                             json.dumps(self.not_checked(summary)).casefold()]
                    for text in texts:
                        self.assertNotIn("inventeduser", text)
                        self.assertNotIn("invented-pc", text)
                        self.assertNotIn(query.casefold(), text)
                        self.assertNotIn(json.dumps(query)[1:-1].casefold(), text)

            with self.subTest("a longer word holding the user name"):
                summary = self.run_one(package_finding(
                    "pip", "contoso-lib", "1.3.0", url=clean_url,
                    query="inventeduser2 contoso-lib"))
                self.assertNotIn("account", self.reasons(summary), self.warnings_of(summary))

            with self.subTest("clean url and query"):
                summary = self.run_one(package_finding(
                    "pip", "contoso-lib", "1.3.0", url=clean_url, query=clean_query))
                self.assertEqual(self.warnings_of(summary), [])

    # K7
    def test_existing_kinds_clean(self):
        self.assertTrue(self.had_environ, "advice.ENVIRON is missing")
        findings = [
            update_finding("2026-11", "KB5099911", "26200.7001",
                           cves=[("CVE-2026-61001", "Important")],
                           query="Windows 11 25H2 November 2026 cumulative update"),
            exploited_finding("CVE-2026-61001",
                              query="CVE-2026-61001 Contoso Invented Product"),
            firmware_finding("Contoso Ltd.", "Contoso Book 14", "CB14.320.0", "2026-10-01",
                             url="https://www.contoso.com/support/contoso-book-14/bios",
                             query="Contoso Book 14 BIOS update"),
            issue_finding("Invented issue: printing stops",
                          "https://learn.microsoft.com/windows/release-health/invented-issue",
                          query="Windows 11 25H2 known issues printing"),
            fault_tests.fault_finding(),
        ]
        doc = findings_doc([search("release-info"), search("msrc"), search("kev"),
                            search("release-health"), search("firmware")], findings)
        with mock.patch.object(self.advice, "ENVIRON", dict(K6_ENVIRON)):
            summary = self.collect_findings(FakePowerShell(), doc, data_dir=self.data_dir(),
                                            now=RUN_NOW)
        bad = [w for w in self.warnings_of(summary) if w.get("reason") in ("path", "account")]
        self.assertEqual(bad, [], self.warnings_of(summary))


class TestPackageDomains(PackageTestCase):
    # K8
    def test_load_sources(self):
        real = json.loads(self.advice.SOURCES_FILE.read_text(encoding="utf-8"))

        with self.subTest("the real sources.json loads"):
            self.assertEqual({manager: sorted(domains) for manager, domains
                              in (real.get("package_domains") or {}).items()},
                             {manager: sorted(domains) for manager, domains
                              in EXPECTED_PACKAGE_DOMAINS.items()})
            fake = FakePowerShell()
            code, stdout, stderr = self.run_main(self.data_dir(), fake, now=RUN_NOW)
            self.assertEqual(code, 0, stderr[:300])

        unknown = json.loads(json.dumps(real))
        unknown.setdefault("package_domains", {})["cargo"] = ["crates.io"]
        empty = json.loads(json.dumps(real))
        empty.setdefault("package_domains", {})["pip"] = []
        for label, data in (("unknown manager", unknown), ("empty domain list", empty)):
            with self.subTest(label):
                sources = self.temp_file("sources.json", json.dumps(data))
                fake = FakePowerShell()
                with mock.patch.object(self.advice, "SOURCES_FILE", sources):
                    code, stdout, stderr = self.run_main(self.data_dir(), fake, now=RUN_NOW)
                self.assertEqual(code, 2, stdout[:300])
                self.assertTrue(stderr.strip(), "no message on stderr")
                self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()

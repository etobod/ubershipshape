"""Stable item ids of ush-inventory across runs and the ``--cut`` mode (plan 108, M3, K4).

Interface under test (from the plan; the general one is in ``fakes.py``):

- The lists ``a`` (programs), ``s`` (autostart), ``f`` (components), ``d`` (drivers) and
  ``x`` (additions) take their numbers from a map kept in
  ``<data dir>/state/ush-inventory.ids.json``, keyed by the item ``key``: an item that
  stays keeps its id, a new item takes a number higher than any given before, a number of
  an item that went away is not given again. Changes ``c`` stay positional (``c1``...).
- An unreadable map file gives a ``not_checked`` entry and exit code 0.
- The detail file carries ``listed`` (``{list name: [id, ...]}``, the ids of the listable
  items before the budget cut) and ``summary_file`` (the path of the summary of the same
  run).
- ``main(["--cut", ...])`` prints JSON with the items ``{id, list, name}`` of the ids in
  ``listed`` that are not in the summary of ``summary_file``; it never starts a machine
  job. ``--cut --detail-file <path>`` needs no data directory. A detail file without
  ``listed`` gives exit code 1 and the field name on stderr.

Assumptions added by these tests beyond the plan text:

- The ``--cut`` output is either the list of items itself or an object holding exactly
  one such list.
- An item's ``list`` is the name of the ``listed`` entry that holds its id.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .fakes import (
    NOW,
    SYSTEM_DN,
    FakePowerShell,
    InventoryTestCase,
    id_number,
    msix,
    ok,
    win32,
)
from .fakes_additions import (
    builtin_rule,
    cert,
    certificates_result,
    custom_rule,
    firewall_result,
    fw_value,
    m2_responses,
    thumb,
)
from .fakes_components import driver, windows_driver

SKILL_DIR = REPO_ROOT / "skills" / "ush-inventory"

PROGRAMS = 2000
REMOVED_NEWEST = 30
DRIVERS = 500
RULES = 1000

OWN_PROGRAM_FAMILY = "Invented.SystemApp_0abc1def2ghj3"
OWN_PROGRAM_KEY = f"msix:{OWN_PROGRAM_FAMILY}"
OWN_DRIVER_ID = "ROOT\\INVENTED_WINDOWS\\0000"
OWN_DRIVER_KEY = f"driver:{OWN_DRIVER_ID}"
OWN_RULE_NAME = "{00000000-0000-0000-9999-000000000001}"
OWN_RULE_KEY = f"firewall:local:{OWN_RULE_NAME}"
CUT_CERT_THUMB = thumb(0xE001)
CUT_CERT_SUBJECT = "CN=Invented Cut Enterprise Root"
CUT_CERT_KEY = f"cert:enterprise:{CUT_CERT_THUMB}"

SUMMARY_LISTS = ("programs", "autostart", "components", "drivers", "additions")
CUT_COUNTS = {"a": "truncated", "d": "truncated_drivers", "f": "truncated_components",
              "x": "truncated_additions"}


# --- invented machine data -------------------------------------------------------------

def program_rows(indexes):
    """Win32 programs; program i is installed i days after the first one (a higher i is
    newer)."""
    rows = []
    for i in indexes:
        day = (NOW.date() - timedelta(days=4000 - i)).strftime("%Y%m%d")
        rows.append(win32(f"InventedStableApp{i:04d}", f"Invented Stable App {i:04d}",
                          install_date=day,
                          install_location=f"C:\\Invented\\Programs\\Stable App {i:04d}"))
    return rows


def own_program():
    return msix(OWN_PROGRAM_FAMILY, "Invented.SystemApp", kind="System", publisher=SYSTEM_DN)


def driver_rows():
    rows = [
        driver(f"PCI\\VEN_1AAA&DEV_{i:04X}\\INVENTEDSTABLE{i:04d}", f"oem{i}.inf",
               device_name=f"Invented Stable Device {i:04d}",
               provider="Invented Hardware Vendor Ltd", version=f"1.0.{i}.0")
        for i in range(DRIVERS)
    ]
    rows.append(windows_driver(OWN_DRIVER_ID, "invented_windows.inf",
                               device_name="Invented Windows Own Device"))
    return rows


def local_rules(count):
    rules = [
        fw_value(f"{{00000000-0000-0000-0000-{i:012d}}}",
                 custom_rule(f"Invented Stable Server {i:04d}", port=str(10000 + i),
                             app=f"C:\\Invented\\Stable Server {i:04d}\\server.exe"))
        for i in range(count)
    ]
    rules.append(fw_value(OWN_RULE_NAME, builtin_rule(1)))
    return rules


def pressure_responses(program_indexes):
    """Programs, drivers and firewall rules far over the summary budget, plus one own
    program, one own driver, one own firewall rule and one enterprise root certificate
    (an addition without a change block, so it is cut first)."""
    return m2_responses(
        win32_programs=ok(program_rows(program_indexes)),
        msix_programs=ok([own_program()]),
        drivers=ok(driver_rows()),
        firewall_rules=ok(firewall_result(local=local_rules(RULES))),
        root_certificates=ok(certificates_result(
            enterprise=[cert(CUT_CERT_THUMB, subject=CUT_CERT_SUBJECT)])),
    )


def rule(n):
    """Small firewall fixture: rule n, value names and rule names ascending with n."""
    return fw_value(f"{{00000000-0000-0000-0001-{n:012d}}}",
                    custom_rule(f"Invented Kept Rule {n}", port=str(21000 + n),
                                app=f"C:\\Invented\\Kept Rule {n}\\app.exe"))


def rule_key(value):
    return f"firewall:local:{value['name']}"


def small_responses(rules):
    return m2_responses(firewall_rules=ok(firewall_result(local=rules)))


def joined(path):
    return " ".join(Path(path).read_text(encoding="utf-8").split())


class TestStableIds(InventoryTestCase):
    # --- helpers ------------------------------------------------------------------------

    def run_bare(self, argv, fake):
        """main without --data-dir; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.inventory.main(list(argv), run_ps=fake, is_admin=lambda: False,
                                       now=NOW + timedelta(days=2))
        return code, out.getvalue(), err.getvalue()

    def items_of(self, data, name):
        items = data.get(name)
        self.assertIsInstance(items, list, f"{name}: {type(items).__name__}")
        return items

    def ids_by_key(self, items):
        return {item.get("key"): item.get("id") for item in items}

    def detail_by_id(self, detail):
        result = {}
        for name in SUMMARY_LISTS:
            for item in detail.get(name) or []:
                if isinstance(item, dict) and item.get("id") is not None:
                    result[item["id"]] = item
        return result

    def summary_ids(self, summary):
        ids = set()
        for value in summary.values():
            if isinstance(value, list):
                ids.update(item.get("id") for item in value
                           if isinstance(item, dict) and item.get("id") is not None)
        return ids

    def cut_items(self, stdout):
        try:
            data = json.loads(stdout)
        except ValueError as exc:
            self.fail(f"--cut stdout is not JSON ({exc}): {stdout[:300]!r}")
        if isinstance(data, dict):
            lists = [value for value in data.values()
                     if isinstance(value, list)
                     and all(isinstance(item, dict) and "id" in item for item in value)]
            self.assertEqual(len(lists), 1, f"no single list of items in {sorted(data)}")
            data = lists[0]
        self.assertIsInstance(data, list, stdout[:300])
        for item in data:
            self.assertIsInstance(item, dict, item)
        return data

    def x_numbers(self, detail):
        return [id_number(item.get("id"), "x") for item in self.items_of(detail, "additions")]

    def assert_positional_changes(self, summary):
        changes = self.changes(summary)
        self.assertEqual([change.get("id") for change in changes],
                         [f"c{n}" for n in range(1, len(changes) + 1)], changes)

    # --- K4: ids survive removal; new ids grow; changes stay positional ------------------

    def test_firewall_ids_survive_removal(self):
        data_dir = self.data_dir()
        r1, r2, r3, r4 = rule(1), rule(2), rule(3), rule(4)

        first = self.collect(FakePowerShell(small_responses([r1, r2, r3])),
                             data_dir=data_dir, now=NOW)
        self.assertTrue((data_dir / "state" / "ush-inventory.ids.json").is_file(),
                        "the id map was not written")
        first_ids = self.ids_by_key(self.items_of(first, "additions"))
        for value in (r1, r2, r3):
            self.assertIn(rule_key(value), first_ids, sorted(map(str, first_ids)))
        self.assert_positional_changes(first)

        # The middle rule goes away: a positional number would shift for one neighbour.
        second = self.collect(FakePowerShell(small_responses([r1, r3])),
                              data_dir=data_dir, now=NOW + timedelta(hours=1))
        second_ids = self.ids_by_key(self.items_of(second, "additions"))
        self.assertNotIn(rule_key(r2), second_ids)
        for value in (r1, r3):
            self.assertEqual(second_ids.get(rule_key(value)), first_ids[rule_key(value)],
                             f"{rule_key(value)} changed its id")
        self.assertTrue(self.changes(second), "the removed rule gave no change")
        self.assert_positional_changes(second)

        # A new rule takes a number higher than every number given before.
        third = self.collect(FakePowerShell(small_responses([r1, r3, r4])),
                             data_dir=data_dir, now=NOW + timedelta(hours=2))
        third_ids = self.ids_by_key(self.items_of(third, "additions"))
        for value in (r1, r3):
            self.assertEqual(third_ids.get(rule_key(value)), first_ids[rule_key(value)],
                             f"{rule_key(value)} changed its id")
        earlier = self.x_numbers(self.detail(first)) + self.x_numbers(self.detail(second))
        self.assertIn(rule_key(r4), third_ids, sorted(map(str, third_ids)))
        self.assertGreater(id_number(third_ids[rule_key(r4)], "x"), max(earlier))
        self.assertTrue(self.changes(third), "the new rule gave no change")
        self.assert_positional_changes(third)

    def test_unreadable_map_noted(self):
        clean_dir = self.data_dir()
        clean = self.collect(FakePowerShell(small_responses([rule(1), rule(2)])),
                             data_dir=clean_dir, now=NOW)

        broken_dir = self.data_dir()
        state = broken_dir / "state"
        state.mkdir(parents=True)
        (state / "ush-inventory.ids.json").write_text("{not json", encoding="utf-8")
        code, stdout, stderr = self.run_main(
            broken_dir, FakePowerShell(small_responses([rule(1), rule(2)])), now=NOW)
        self.assertEqual(code, 0, stderr[:300])
        broken = self.parse(stdout)

        def text(item, data_dir):
            # The two runs differ only in their data directory and the map file.
            dumped = json.dumps(item, sort_keys=True)
            for form in (json.dumps(str(data_dir))[1:-1], str(data_dir)):
                dumped = dumped.replace(form, "<data dir>")
            return dumped

        known = {text(item, clean_dir) for item in self.not_checked(clean)}
        extra = [item for item in self.not_checked(broken)
                 if text(item, broken_dir) not in known]
        self.assertTrue(extra, f"no not_checked entry about the unreadable id map: "
                               f"{self.not_checked(broken)}")
        for item in self.items_of(broken, "additions"):
            id_number(item.get("id"), "x")

    # --- K4: --cut ---------------------------------------------------------------------

    def test_cut_lists_cut_items(self):
        data_dir = self.data_dir()
        code, stdout, stderr = self.run_main(
            data_dir, FakePowerShell(pressure_responses(range(PROGRAMS))), now=NOW)
        self.assertEqual(code, 0, stderr[:300])
        first_ids = self.ids_by_key(self.items_of(self.detail(self.parse(stdout)), "programs"))

        # The second run lacks the newest programs, so the numbers of the programs left are
        # no longer their places in the list.
        code, stdout, stderr = self.run_main(
            data_dir, FakePowerShell(pressure_responses(range(PROGRAMS - REMOVED_NEWEST))),
            now=NOW + timedelta(days=1))
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        detail_path = Path(summary.get("detail_file"))
        detail = self.detail(summary)

        # Preconditions of the fixture: programs, drivers and the certificate were cut.
        self.assertGreater(summary.get("truncated"), 0)
        self.assertGreater(summary.get("truncated_drivers"), 0)
        self.assertGreater(summary.get("truncated_additions"), 0)
        self.assertNotIn(CUT_CERT_KEY,
                         [item.get("key") for item in self.items_of(summary, "additions")])

        # The detail file names the listable ids and the summary of the same run.
        listed = detail.get("listed")
        self.assertIsInstance(listed, dict, f"listed: {listed!r}")
        summary_file = detail.get("summary_file")
        self.assertIsInstance(summary_file, str, f"summary_file: {summary_file!r}")
        summary_path = Path(summary_file)
        self.assertTrue(summary_path.is_file(), summary_path)
        self.assertEqual(summary_path.name,
                         detail_path.name.replace(".detail.json", ".summary.json"))

        cut_fake = FakePowerShell()
        code, cut_stdout, stderr = self.run_main(data_dir, cut_fake, extra=["--cut"],
                                                 now=NOW + timedelta(days=2))
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(cut_fake.calls, [], "--cut started a machine job")
        cut = self.cut_items(cut_stdout)

        # Exactly the listable ids missing from the summary, with their real ids.
        in_summary = self.summary_ids(summary)
        expected = {(item_id, name) for name, ids in listed.items() for item_id in ids
                    if item_id not in in_summary}
        self.assertEqual({(item.get("id"), item.get("list")) for item in cut}, expected)
        by_letter = {}
        for item in cut:
            by_letter.setdefault(str(item.get("id"))[:1], []).append(item)
        for letter, count_name in CUT_COUNTS.items():
            self.assertEqual(len(by_letter.get(letter, [])), summary.get(count_name) or 0,
                             f"cut items with prefix {letter} against {count_name}")

        everything = self.detail_by_id(detail)
        for item in cut:
            self.assertEqual(set(item), {"id", "list", "name"}, item)
            self.assertNotIn("install_location", item, item)
            self.assertNotIn("key", item, item)
            self.assertIn(item["id"], everything, item)

        # A cut program keeps the id it had in the first run.
        cut_programs = [item for item in cut if str(item["id"]).startswith("a")]
        self.assertTrue(cut_programs)
        for item in cut_programs:
            full = everything[item["id"]]
            self.assertEqual(item["id"], first_ids.get(full.get("key")), full.get("key"))
            self.assertEqual(item["name"], full.get("name"), item)

        # Own items of the fixture are never listed as cut.
        keyed = {full.get("key"): full for full in everything.values()}
        cut_ids = {item["id"] for item in cut}
        for own_key in (OWN_PROGRAM_KEY, OWN_DRIVER_KEY, OWN_RULE_KEY):
            own = keyed.get(own_key)
            if own is not None:
                self.assertNotIn(own.get("id"), cut_ids, own_key)

        # A driver is named by device_name; the cut certificate has a name.
        cut_drivers = [item for item in cut if str(item["id"]).startswith("d")]
        self.assertTrue(cut_drivers)
        for item in cut_drivers:
            self.assertEqual(item["name"], everything[item["id"]].get("device_name"), item)
        cert_item = keyed.get(CUT_CERT_KEY)
        self.assertIsNotNone(cert_item, "the certificate is not in the detail file")
        cert_cut = [item for item in cut if item["id"] == cert_item.get("id")]
        self.assertEqual(len(cert_cut), 1, f"certificate {cert_item.get('id')} not cut")
        self.assertIsNotNone(cert_cut[0]["name"], cert_cut[0])

        # --cut --detail-file without any data directory gives the same.
        bare_fake = FakePowerShell()
        with mock.patch.dict(os.environ):
            os.environ.pop("USH_DATA_DIR", None)
            os.environ.pop("LOCALAPPDATA", None)
            code, bare_stdout, stderr = self.run_bare(
                ["--cut", "--detail-file", str(detail_path)], bare_fake)
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(bare_fake.calls, [], "--cut started a machine job")
        self.assertEqual(self.cut_items(bare_stdout), cut)

        # --detail on a cut id gives that item.
        detail_fake = FakePowerShell()
        code, item_stdout, stderr = self.run_main(
            data_dir, detail_fake, extra=["--detail", cert_item["id"]],
            now=NOW + timedelta(days=2))
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(detail_fake.calls, [])
        fetched = self.parse(item_stdout)
        self.assertIsInstance(fetched, dict, item_stdout[:300])
        self.assertEqual(fetched.get("id"), cert_item["id"], fetched)
        self.assertEqual(fetched.get("key"), CUT_CERT_KEY, fetched)

        # A detail file without listed: exit 1, the field named on stderr.
        stripped = {k: v for k, v in json.loads(detail_path.read_text(encoding="utf-8-sig"))
                    .items() if k != "listed"}
        stripped_path = detail_path.parent / "inventory-stripped-test.detail.json"
        stripped_path.write_text(json.dumps(stripped), encoding="utf-8")
        stripped_fake = FakePowerShell()
        code, out, err = self.run_main(
            data_dir, stripped_fake, extra=["--cut", "--detail-file", str(stripped_path)],
            now=NOW + timedelta(days=2))
        self.assertEqual(code, 1, out[:300])
        self.assertIn("listed", err)
        self.assertEqual(stripped_fake.calls, [])

    # --- K4: documents -------------------------------------------------------------------

    def test_docs_describe_cut(self):
        for name in ("references/report-format.md", "references/summary-contract.md"):
            text = joined(SKILL_DIR / name)
            with self.subTest(document=name):
                for phrase in ("a3, a4, a5", "follow the last one", "follow that order"):
                    self.assertNotIn(phrase, text)
                for sentence in re.split(r"(?<=[.!?])\s+", text):
                    if "their ids" in sentence.lower():
                        self.assertIsNone(
                            re.search(r"\bcut\b|truncat", sentence, re.IGNORECASE),
                            sentence)
        self.assertIn("--cut", (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

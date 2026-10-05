"""Stable group ids of ush-processes across runs and the ``--cut`` mode (plan 108, M4, K6).

Interface under test (from the plan; the general one is in ``fakes.py`` and
``fakes_links.py``):

- Groups ``g`` take their numbers from a map kept in
  ``<data dir>/state/ush-processes.ids.json``. The stable key is built from the group
  kind (``path``, ``none``, ``unread``) and its value, so a group that stays keeps its
  id when another group goes away, and a ``none`` group and an ``unread`` group with the
  same name are two keys (no repeated-key note). Ports ``p`` stay positional.
- The detail file carries ``listed`` (``{list name: [id, ...]}``, the ids of the
  listable items before the budget cut) and ``summary_file``.
- ``main(["--cut", ...])`` prints JSON with the items ``{id, list, name}`` of the ids in
  ``listed`` that are not in the summary of ``summary_file``; it never starts a machine
  job. ``--cut --detail-file <path>`` needs no data directory.
- ``--detail <id>`` on a cut id prints that group.

Assumptions added by these tests beyond the plan text:

- The ``--cut`` output is either the list of items itself or an object holding exactly
  one such list.
- An item's ``list`` is the name of the ``listed`` entry that holds its id; a group's
  ``name`` is the group ``name`` of the detail file.
- A ``not_checked`` entry about repeated keys names the ids it concerns.

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

from .fakes import MB, NOW, FakePowerShell, proc
from .fakes_links import LinksTestCase, endpoint, responses

SKILL_DIR = REPO_ROOT / "skills" / "ush-processes"

ALPHA = r"C:\Apps\Alpha\alpha.exe"
BETA = r"C:\Apps\Beta\beta.exe"
GAMMA = r"C:\Apps\Gamma\gamma.exe"

CUT_TOOLS = 400
REMOVED_TOP = 30


def joined(path):
    return " ".join(Path(path).read_text(encoding="utf-8").split())


def small_rows(with_alpha):
    """Alpha has the most memory, so it is the first group of the first run. Registry
    under pid 4 has no image file (a ``none`` group); Registry under another parent has
    an unread path (an ``unread`` group with the same name)."""
    rows = []
    if with_alpha:
        rows.append(proc(500, "alpha.exe", ALPHA, created=1))
    rows += [
        proc(600, "beta.exe", BETA, created=2),
        proc(700, "gamma.exe", GAMMA, created=3),
        proc(120, "Registry", path=None, parent=4, created=0),
        proc(3000, "Registry", path="", command_line="", parent=700, created=5),
    ]
    return rows


def small_private(with_alpha):
    private = {600: 300 * MB, 700: 200 * MB, 120: 50 * MB, 3000: 40 * MB}
    if with_alpha:
        private[500] = 400 * MB
    return private


def tool_path(i):
    return rf"C:\Apps\Tool{i:04d}\tool{i:04d}.exe"


def tool_rows(indexes):
    """One group per tool; a higher index has more memory, so it comes first."""
    rows = [proc(1000 + i, f"tool{i:04d}.exe", tool_path(i), created=1) for i in indexes]
    private = {1000 + i: (i + 1) * 4096 for i in indexes}
    return rows, private


class TestStableIds(LinksTestCase):
    # --- helpers ------------------------------------------------------------------------

    def run_bare(self, argv, fake):
        """main without --data-dir; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.processes.main(list(argv), run_ps=fake, is_admin=lambda: False,
                                       now=NOW + timedelta(days=2))
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def group_view(group):
        return (group.get("name"), group.get("path"), group.get("path_read"))

    def ids_by_view(self, groups):
        result = {}
        for group in groups:
            view = self.group_view(group)
            self.assertNotIn(view, result, f"two groups look the same: {view}")
            result[view] = group.get("id")
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

    def assert_positional_ports(self, summary):
        ports = self.ports(summary)
        self.assertTrue(ports, "the fixture has ports")
        self.assertEqual([port.get("id") for port in ports],
                         [f"p{n}" for n in range(1, len(ports) + 1)], ports)

    def registry_groups(self, summary):
        none = self.group_named(self.groups(summary), "Registry", path_read=True)
        unread = self.group_named(self.groups(summary), "Registry", path_read=False)
        return none, unread

    def assert_no_repeat_note(self, summary, ids):
        for entry in self.not_checked(summary):
            text = json.dumps(entry)
            for group_id in ids:
                self.assertIsNone(re.search(rf"\b{re.escape(group_id)}\b", text),
                                  f"not_checked names {group_id}: {entry}")
            self.assertFalse(str(entry.get("what", "")).startswith("stable ids"), entry)

    # --- K6: group ids survive; none and unread differ; ports stay positional ------------

    def test_group_ids_survive(self):
        data_dir = self.data_dir()
        first = self.collect(
            FakePowerShell(responses(
                small_rows(True), private=small_private(True),
                tcp=[endpoint("0.0.0.0", 8080, 500), endpoint("0.0.0.0", 9090, 600)])),
            data_dir=data_dir, now=NOW)
        self.assertTrue((data_dir / "state" / "ush-processes.ids.json").is_file(),
                        "the id map was not written")
        first_ids = self.ids_by_view(self.groups(first))
        alpha_view = ("alpha.exe", ALPHA, True)
        self.assertEqual(self.groups(first)[0].get("name"), "alpha.exe",
                         "precondition: alpha is the first group")
        self.assert_positional_ports(first)

        none, unread = self.registry_groups(first)
        self.assertEqual(none.get("path_kind"), "none", none)
        self.assertNotEqual(none.get("id"), unread.get("id"))
        self.assert_no_repeat_note(first, (none.get("id"), unread.get("id")))

        # The process of the first group is gone: a positional number would shift for
        # every group after it.
        second = self.collect(
            FakePowerShell(responses(
                small_rows(False), private=small_private(False),
                tcp=[endpoint("0.0.0.0", 9090, 600), endpoint("127.0.0.1", 7070, 700)])),
            data_dir=data_dir, now=NOW + timedelta(hours=1))
        second_ids = self.ids_by_view(self.groups(second))
        self.assertNotIn(alpha_view, second_ids)
        self.assertEqual(set(second_ids), set(first_ids) - {alpha_view})
        for view, group_id in second_ids.items():
            self.assertEqual(group_id, first_ids[view], f"group {view} changed its id")
        self.assert_positional_ports(second)

        none, unread = self.registry_groups(second)
        self.assertNotEqual(none.get("id"), unread.get("id"))
        self.assert_no_repeat_note(second, (none.get("id"), unread.get("id")))

    # --- K6: --cut ---------------------------------------------------------------------

    def test_cut_lists_cut_groups(self):
        data_dir = self.data_dir()
        rows, private = tool_rows(range(CUT_TOOLS))
        code, stdout, stderr = self.run_main(
            data_dir, FakePowerShell(responses(rows, private=private)), now=NOW)
        self.assertEqual(code, 0, stderr[:300])
        first_detail = self.detail(self.parse(stdout))
        first_ids = {g.get("path"): g.get("id") for g in first_detail.get("groups") or []}

        # The second run lacks the groups with the most memory, so the numbers of the
        # groups left are no longer their places in the list.
        rows, private = tool_rows(range(CUT_TOOLS - REMOVED_TOP))
        code, stdout, stderr = self.run_main(
            data_dir, FakePowerShell(responses(rows, private=private)),
            now=NOW + timedelta(days=1))
        self.assertEqual(code, 0, stderr[:300])
        summary = self.parse(stdout)
        self.assertGreater(summary.get("truncated") or 0, 0, "precondition: groups cut")
        detail_path = Path(summary.get("detail_file"))
        detail = self.detail(summary)

        listed = detail.get("listed")
        self.assertIsInstance(listed, dict, f"listed: {listed!r}")
        summary_file = detail.get("summary_file")
        self.assertIsInstance(summary_file, str, f"summary_file: {summary_file!r}")
        self.assertTrue(Path(summary_file).is_file(), summary_file)

        cut_fake = FakePowerShell()
        code, cut_stdout, stderr = self.run_main(data_dir, cut_fake, extra=["--cut"],
                                                 now=NOW + timedelta(days=2))
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(cut_fake.calls, [], "--cut started a machine job")
        cut = self.cut_items(cut_stdout)

        in_summary = self.summary_ids(summary)
        expected = {(item_id, name) for name, ids in listed.items() for item_id in ids
                    if item_id not in in_summary}
        self.assertEqual({(item.get("id"), item.get("list")) for item in cut}, expected)

        groups_by_id = {g.get("id"): g for g in detail.get("groups") or []}
        cut_groups = [item for item in cut if str(item.get("id")).startswith("g")]
        self.assertEqual(len(cut_groups), summary["truncated"], cut_groups[:5])
        for item in cut:
            self.assertEqual(set(item), {"id", "list", "name"}, item)
        for item in cut_groups:
            full = groups_by_id.get(item["id"])
            self.assertIsNotNone(full, item)
            self.assertEqual(item["name"], full.get("name"), item)
            # A cut group keeps the id it had in the first run.
            self.assertEqual(item["id"], first_ids.get(full.get("path")), full.get("path"))

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

        # --detail on a cut id gives that group.
        target = cut_groups[0]
        detail_fake = FakePowerShell()
        code, item_stdout, stderr = self.run_main(
            data_dir, detail_fake, extra=["--detail", target["id"]],
            now=NOW + timedelta(days=2))
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(detail_fake.calls, [])
        fetched = self.parse(item_stdout)
        self.assertIsInstance(fetched, dict, item_stdout[:300])
        self.assertEqual(fetched.get("id"), target["id"], fetched)
        self.assertEqual(fetched.get("path"), groups_by_id[target["id"]].get("path"))

    # --- K6: documents -------------------------------------------------------------------

    def test_docs_describe_cut(self):
        report_format = joined(SKILL_DIR / "references" / "report-format.md")
        contract = joined(SKILL_DIR / "references" / "summary-contract.md")
        self.assertNotIn("g3, g4, g5", report_format)
        self.assertNotIn("follow the last one", contract)
        for name, text in (("report-format.md", report_format),
                           ("summary-contract.md", contract)):
            with self.subTest(document=name):
                self.assertNotIn("follow that order", text)
                for sentence in re.split(r"(?<=[.!?])\s+", text):
                    if "their ids" in sentence.lower():
                        self.assertIsNone(
                            re.search(r"\bcut\b|truncat", sentence, re.IGNORECASE),
                            sentence)
        self.assertIn("--cut", (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("--cut", report_format)


if __name__ == "__main__":
    unittest.main()

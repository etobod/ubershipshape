"""Stable group and noise ids of ush-events across runs and the ``--cut`` mode
(plan 108, M4, K8).

Interface under test (from the plan; the general one is in ``test_collect.py``):

- Groups ``g`` (key: log, provider, event id) and known noise ``n`` (key: provider,
  event id) take their numbers from a map kept in
  ``<data dir>/state/ush-events.ids.json``: an item that stays keeps its id when another
  goes away. Boots, anomalies, reliability records and dump files stay positional.
- The detail file carries ``listed`` (``{list name: [id, ...]}``, the ids before the
  budget cut) and ``summary_file``.
- ``main(["--cut", ...])`` prints JSON with the items ``{id, list, name}`` of the ids in
  ``listed`` that are not in the summary of ``summary_file``; the ``name`` of a group is
  made from its provider, event id and log. It never starts a machine job.
  ``--cut --detail-file <path>`` needs no data directory.

Assumptions added by these tests beyond the plan text:

- The ``--cut`` output is either the list of items itself or an object holding exactly
  one such list.
- An item's ``list`` is the name of the ``listed`` entry that holds its id.
- ``--cut`` calls neither ``run_ps`` nor ``read_dumps``.

Every event here is invented; nothing is read from the machine and PowerShell never
starts. All output goes to a temporary directory.
"""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests.skill_loader import REPO_ROOT

from .test_collect import (
    APPLICATION,
    NO_DUMPS,
    NOW,
    SYSTEM,
    CollectTestCase,
    FakePowerShell,
    event,
    ok,
)

SKILL_DIR = REPO_ROOT / "skills" / "ush-events"

# Known noise from skills/ush-events/data/noise.json (provider, event id).
NOISE_FIRST = ("Win32k", 700)
NOISE_SECOND = ("Microsoft-Windows-DistributedCOM", 10016)
NOISE_THIRD = ("Microsoft-Windows-Kernel-PnP", 219)

FIRST_GROUP = (SYSTEM, "Invented-Disk-Provider", 7)
OTHER_GROUPS = (
    (SYSTEM, "Invented-Net-Provider", 4201),
    (APPLICATION, "Invented-App-Provider", 1000),
    (SYSTEM, "Invented-App-Provider", 1000),  # same provider and id, another log
)

CUT_GROUPS = 400
TOP_GROUPS = 30


def joined(path):
    return " ".join(Path(path).read_text(encoding="utf-8").split())


def times(count, day=20):
    """``count`` distinct event times within the window of NOW (and of NOW + 1 day)."""
    return [f"2026-09-{day:02d}T{10 + n // 60:02d}:{n % 60:02d}:00.0000000+02:00"
            for n in range(count)]


def events_of(log, provider, event_id, count, day=20):
    return [event(provider, event_id, 2, moment, log=log)
            for moment in times(count, day)]


def small_responses(with_first):
    """The first group has the most events, so it is g1 of the first run; the first
    noise item has the most events too."""
    system, application = [], []
    if with_first:
        system += events_of(*FIRST_GROUP, 5, day=18)
        system += events_of(SYSTEM, *NOISE_FIRST, 4, day=18)
    system += events_of(*OTHER_GROUPS[0], 3, day=19)
    application += events_of(*OTHER_GROUPS[1], 2, day=20)
    system += events_of(*OTHER_GROUPS[2], 1, day=21)
    system += events_of(SYSTEM, *NOISE_SECOND, 2, day=22)
    application += events_of(APPLICATION, *NOISE_THIRD, 1, day=23)
    return {"A:System": ok(system), "A:Application": ok(application)}


def cut_responses(with_top):
    """Many groups, far over the summary budget. The top groups have two events each,
    so they come first; the others have one."""
    system = []
    if with_top:
        for i in range(TOP_GROUPS):
            system += events_of(SYSTEM, f"Invented-Top-Provider-{i:02d}", 100 + i, 2,
                                day=10 + i % 10)
    for i in range(CUT_GROUPS):
        system.append(event(f"Invented-Many-Provider-{i:03d}", 2000 + i, 3,
                            times(1, day=10 + i % 15)[0], log=SYSTEM))
    return {"A:System": ok(system)}


class TestStableIds(CollectTestCase):
    # --- helpers ------------------------------------------------------------------------

    def call_main(self, argv, fake, now, read_dumps=NO_DUMPS):
        """main with ``argv``; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.events.main(list(argv), run_ps=fake, now=now, read_dumps=read_dumps)
        return code, out.getvalue(), err.getvalue()

    def collect_in(self, data_dir, fake, now):
        code, stdout, stderr = self.call_main(["--data-dir", str(data_dir)], fake, now)
        self.assertEqual(code, 0, stderr[:300])
        return self.parse(stdout)

    def detail(self, summary):
        data = json.loads(Path(summary["detail_file"]).read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict)
        return data

    def group_ids(self, items):
        result = {}
        for item in items:
            key = (item.get("log"), item.get("provider"), item.get("event_id"))
            self.assertNotIn(key, result, f"two groups with key {key}")
            result[key] = item.get("id")
        return result

    def noise_ids(self, items):
        result = {}
        for item in items:
            key = (item.get("provider"), item.get("event_id"))
            self.assertNotIn(key, result, f"two noise items with key {key}")
            result[key] = item.get("id")
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

    # --- K8: group and noise ids survive -------------------------------------------------

    def test_group_ids_survive(self):
        data_dir = self.data_dir()
        first = self.collect_in(data_dir, FakePowerShell(small_responses(True)), NOW)
        self.assertTrue((data_dir / "state" / "ush-events.ids.json").is_file(),
                        "the id map was not written")
        first_groups = self.group_ids(self.list_field(first, "groups"))
        first_noise = self.noise_ids(self.list_field(first, "noise"))
        self.assertEqual(set(first_groups), {FIRST_GROUP, *OTHER_GROUPS})
        self.assertEqual(set(first_noise), {NOISE_FIRST, NOISE_SECOND, NOISE_THIRD})
        self.assertEqual(self.list_field(first, "groups")[0].get("provider"),
                         FIRST_GROUP[1], "precondition: the first group comes first")

        # The first group and the first noise item are gone: positional numbers would
        # shift for every item after them.
        second = self.collect_in(data_dir, FakePowerShell(small_responses(False)),
                                 NOW + timedelta(hours=1))
        second_groups = self.group_ids(self.list_field(second, "groups"))
        second_noise = self.noise_ids(self.list_field(second, "noise"))
        self.assertEqual(set(second_groups), set(OTHER_GROUPS))
        self.assertEqual(set(second_noise), {NOISE_SECOND, NOISE_THIRD})
        for key, group_id in second_groups.items():
            self.assertEqual(group_id, first_groups[key], f"group {key} changed its id")
        for key, noise_id in second_noise.items():
            self.assertEqual(noise_id, first_noise[key], f"noise {key} changed its id")

    # --- K8: --cut ---------------------------------------------------------------------

    def test_cut_lists_cut_groups(self):
        data_dir = self.data_dir()
        first = self.collect_in(data_dir, FakePowerShell(cut_responses(True)), NOW)
        first_ids = self.group_ids(self.detail(first).get("groups") or [])

        # The second run lacks the top groups, so the numbers of the groups left are no
        # longer their places in the list.
        second = self.collect_in(data_dir, FakePowerShell(cut_responses(False)),
                                 NOW + timedelta(days=1))
        self.assertGreater(second.get("truncated") or 0, 0, "precondition: groups cut")
        detail_path = Path(second["detail_file"])
        detail = self.detail(second)
        listed = detail.get("listed")
        self.assertIsInstance(listed, dict, f"listed: {listed!r}")
        summary_file = detail.get("summary_file")
        self.assertIsInstance(summary_file, str, f"summary_file: {summary_file!r}")
        self.assertTrue(Path(summary_file).is_file(), summary_file)

        dumps_calls = []

        def recording_dumps():
            dumps_calls.append(1)
            return NO_DUMPS()

        cut_fake = FakePowerShell()
        code, cut_stdout, stderr = self.call_main(["--data-dir", str(data_dir), "--cut"],
                                                  cut_fake, NOW + timedelta(days=2),
                                                  read_dumps=recording_dumps)
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(cut_fake.calls, [], "--cut started a machine job")
        self.assertEqual(dumps_calls, [], "--cut read the memory dumps")
        cut = self.cut_items(cut_stdout)

        in_summary = self.summary_ids(second)
        expected = {(item_id, name) for name, ids in listed.items() for item_id in ids
                    if item_id not in in_summary}
        self.assertEqual({(item.get("id"), item.get("list")) for item in cut}, expected)

        groups_by_id = {g.get("id"): g for g in detail.get("groups") or []}
        cut_groups = [item for item in cut if str(item.get("id")).startswith("g")]
        self.assertEqual(len(cut_groups), second["truncated"], cut_groups[:5])
        for item in cut:
            self.assertEqual(set(item), {"id", "list", "name"}, item)
        for item in cut_groups:
            full = groups_by_id.get(item["id"])
            self.assertIsNotNone(full, item)
            self.assertIsNotNone(item["name"], item)
            self.assertIn(full.get("provider"), json.dumps(item["name"]), item)
            # A cut group keeps the id it had in the first run.
            key = (full.get("log"), full.get("provider"), full.get("event_id"))
            self.assertEqual(item["id"], first_ids.get(key), key)

        # --cut --detail-file without any data directory gives the same.
        bare_fake = FakePowerShell()
        with mock.patch.dict(os.environ):
            os.environ.pop("USH_DATA_DIR", None)
            os.environ.pop("LOCALAPPDATA", None)
            code, bare_stdout, stderr = self.call_main(
                ["--cut", "--detail-file", str(detail_path)], bare_fake,
                NOW + timedelta(days=2), read_dumps=recording_dumps)
        self.assertEqual(code, 0, stderr[:300])
        self.assertEqual(bare_fake.calls, [], "--cut started a machine job")
        self.assertEqual(dumps_calls, [], "--cut read the memory dumps")
        self.assertEqual(self.cut_items(bare_stdout), cut)

    # --- K8: documents -------------------------------------------------------------------

    def test_docs_describe_cut(self):
        report_format = joined(SKILL_DIR / "references" / "report-format.md")
        contract = joined(SKILL_DIR / "references" / "summary-contract.md")
        for name, text in (("report-format.md", report_format),
                           ("summary-contract.md", contract)):
            with self.subTest(document=name):
                self.assertNotIn("ids `g1`, `g2`", text)
                self.assertNotIn("follow the last one", text)
        self.assertIn("--cut", (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("--cut", report_format)


if __name__ == "__main__":
    unittest.main()

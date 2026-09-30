"""Tests for skills/ush-processes/scripts/processes.py (plan 051, M1): process items,
groups and the summary. The interface is described in ``fakes.py``.

PowerShell never starts; every process, path, user and number is invented.
"""

import threading
import unittest

from .fakes import (
    MB,
    FakePowerShell,
    ProcessesTestCase,
    failure,
    find_key,
    machine,
    memory_row,
    owner_error,
    owner_row,
    proc,
)


class TestProcess(ProcessesTestCase):
    def test_empty_is_unread(self):
        rows = [
            proc(100, "blank.exe", path="", command_line="", created=1),
            proc(200, "nulls.exe", path=None, command_line=None, created=2),
            proc(300, "full.exe", path=r"C:\Apps\Full\full.exe",
                 command_line=r'"C:\Apps\Full\full.exe" --invented-mode', created=3),
        ]
        summary = self.collect(FakePowerShell(machine(rows)))
        items = self.detail_processes(summary)

        for pid in (100, 200):
            with self.subTest(pid=pid):
                self.assert_unread(items[pid], "path")
                self.assert_unread(items[pid], "command_line")

        self.assert_read(items[300], "path", r"C:\Apps\Full\full.exe")
        self.assert_read(items[300], "command_line", r'"C:\Apps\Full\full.exe" --invented-mode')

        self.assertEqual(summary["counts"].get("command_line_unread"), 2, summary["counts"])

    def test_owner(self):
        rows = [
            proc(100, "one.exe", r"C:\Apps\One\one.exe", created=1),
            proc(200, "two.exe", r"C:\Apps\Two\two.exe", created=2),
            proc(300, "three.exe", r"C:\Apps\Three\three.exe", created=3),
            proc(400, "four.exe", r"C:\Apps\Four\four.exe", created=4),
        ]
        owners = [
            owner_row(100, user=None, domain=None, return_value=2),
            owner_row(200, user="alice", domain="HOST", return_value=0),
            owner_error(300),
            owner_row(400, user="bob", domain="HOST", return_value=0),
        ]
        summary = self.collect(FakePowerShell(machine(rows, owners=owners)))
        items = self.detail_processes(summary)

        self.assert_unread(items[100], "owner")
        self.assert_read(items[200], "owner", "HOST\\alice")
        self.assert_unread(items[300], "owner")
        self.assert_read(items[400], "owner", "HOST\\bob")

        with self.subTest("owners job failed"):
            responses = machine(rows, owners=owners)
            responses["owners"] = failure("Invented: GetOwner job failed.")
            summary = self.collect(FakePowerShell(responses))
            items = self.detail_processes(summary)
            self.assertEqual(sorted(items), [100, 200, 300, 400])
            for pid, item in items.items():
                with self.subTest(pid=pid):
                    self.assert_unread(item, "owner")
            self.assertEqual(len(self.notes_about(summary, "owners")), 1,
                             self.not_checked(summary))

    def test_parents(self):
        rows = [
            proc(10, "launcher.exe", r"C:\Apps\Launcher\launcher.exe", parent=0, created=1),
            proc(20, "child.exe", r"C:\Apps\Child\child.exe", parent=10, created=5),
            # PID 40 was reused by a process started after its child: the parent is gone.
            proc(30, "orphan.exe", r"C:\Apps\Orphan\orphan.exe", parent=40, created=10),
            proc(40, "late.exe", r"C:\Apps\Late\late.exe", parent=0, created=20),
            proc(50, "root.exe", r"C:\Apps\Root\root.exe", parent=0, created=2),
            # The candidate parent has no start time: undecidable.
            proc(60, "nodate.exe", r"C:\Apps\NoDate\nodate.exe", parent=0, created=None),
            proc(70, "kid.exe", r"C:\Apps\Kid\kid.exe", parent=60, created=30),
            # A parent loop with equal start times.
            proc(80, "loopa.exe", r"C:\Apps\Loop\loopa.exe", parent=90, created=40),
            proc(90, "loopb.exe", r"C:\Apps\Loop\loopb.exe", parent=80, created=40),
        ]
        fake = FakePowerShell(machine(rows))

        result = {}

        def run():
            try:
                result["summary"] = self.collect(fake)
                result["items"] = self.detail_processes(result["summary"])
            except BaseException as exc:  # noqa: BLE001 - re-raised in the main thread
                result["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=60)
        self.assertFalse(worker.is_alive(), "collection did not finish: parent loop hangs")
        if "error" in result:
            raise result["error"]
        items = result["items"]

        child = items[20]
        self.assertEqual(child.get("parent_pid"), 10, child)
        self.assertEqual(child.get("parent"), {"pid": 10, "name": "launcher.exe"}, child)
        self.assertEqual(child.get("ancestors"), ["launcher.exe"], child)

        orphan = items[30]
        self.assertIsNone(orphan.get("parent"), orphan)
        self.assertIs(orphan.get("parent_gone"), True, orphan)

        root = items[50]
        self.assertIsNone(root.get("parent"), root)
        self.assertIs(root.get("parent_gone"), False, root)

        kid = items[70]
        self.assertIn("parent_gone", kid)
        self.assertIsNone(kid.get("parent"), kid)
        self.assertIsNone(kid["parent_gone"], kid)

        loop = items[80]
        ancestors = loop.get("ancestors")
        self.assertIsInstance(ancestors, list, loop)
        self.assertLessEqual(len(ancestors), 2, loop)
        self.assertEqual(ancestors[0], "loopb.exe", loop)

    def test_pseudoprocess_command_line_not_unread(self):
        # A pseudoprocess has no command line even with administrator rights: nothing
        # to read, so it is not counted as unread (added after the code, plan 051 M1).
        pseudo = [
            proc(0, "System Idle Process", path=None, parent=0, created=None),
            proc(4, "System", path=None, parent=0, created=0),
        ]
        regular = [proc(700, "session.exe", r"C:\Apps\Session\session.exe", parent=4,
                        command_line=r'"C:\Apps\Session\session.exe" --invented', created=1)]
        summary = self.collect(FakePowerShell(machine(pseudo + regular)), admin=True)
        self.assertEqual(summary["counts"].get("command_line_unread"), 0, summary["counts"])
        items = self.detail_processes(summary)
        for pid in (0, 4):
            with self.subTest(pid=pid):
                self.assertIsNone(items[pid].get("command_line"), items[pid])
                self.assertNotIn("command_line", items[pid].get("unread_fields"), items[pid])
        for group in self.groups(summary):
            with self.subTest(group=group.get("name")):
                self.assertEqual(group.get("command_line_unread_count"), 0, group)

    def test_pseudoprocesses_not_unread(self):
        pseudo = [
            proc(0, "System Idle Process", path=None, parent=0, created=None),
            proc(4, "System", path=None, parent=0, created=0),
            proc(120, "Registry", path=None, parent=4, created=0),
            proc(2000, "Memory Compression", path=None, parent=4, created=1),
        ]
        regular = [
            proc(700, "session.exe", r"C:\Apps\Session\session.exe", parent=4, created=1),
            proc(812, "host.exe", r"C:\Apps\Host\host.exe", parent=700, created=2),
            proc(900, "shell.exe", r"C:\Apps\Shell\shell.exe", parent=700, created=3),
        ]
        summary = self.collect(FakePowerShell(machine(pseudo + regular)), admin=True)
        counts = summary["counts"]
        self.assertEqual(counts.get("path_unread"), 0, counts)
        self.assertEqual(counts.get("no_image"), 4, counts)

        items = self.detail_processes(summary)
        for pid in (0, 4, 120, 2000):
            with self.subTest(pid=pid):
                item = items[pid]
                self.assertEqual(item.get("path_kind"), "none", item)
                self.assertIsNone(item.get("path"), item)
                self.assertIsInstance(item.get("unread_fields"), list, item)
                self.assertNotIn("path", item["unread_fields"], item)
        for pid in (700, 812, 900):
            with self.subTest(pid=pid):
                self.assertEqual(items[pid].get("path_kind"), "file", items[pid])

        with self.subTest("Registry with another parent is an ordinary process"):
            impostor = proc(3000, "Registry", path="", command_line="", parent=812,
                            created=5)
            summary = self.collect(
                FakePowerShell(machine(pseudo + regular + [impostor])), admin=True
            )
            item = self.detail_processes(summary)[3000]
            self.assertEqual(item.get("path_kind"), "file", item)
            self.assert_unread(item, "path")
            self.assertEqual(summary["counts"].get("path_unread"), 1, summary["counts"])
            self.assertEqual(summary["counts"].get("no_image"), 4, summary["counts"])


    def test_kernel_parent_is_not_gone(self):
        # Windows may report System (pid 4) as starting after its own children.
        rows = [
            proc(4, "System", path=None, parent=0, created=5),
            proc(120, "Registry", path=None, parent=4, created=0),
            proc(700, "session.exe", r"C:\Apps\Session\session.exe", parent=4, created=1),
        ]
        summary = self.collect(FakePowerShell(machine(rows)), admin=True)
        items = self.detail_processes(summary)
        for pid in (120, 700):
            with self.subTest(pid=pid):
                self.assertEqual((items[pid].get("parent") or {}).get("pid"), 4, items[pid])
                self.assertIs(items[pid].get("parent_gone"), False, items[pid])


class TestGroups(ProcessesTestCase):
    def test_grouping_and_order(self):
        browser = r"C:\Apps\Browser\browser.exe"
        editor = r"C:\Apps\Editor\editor.exe"
        rows = [
            proc(110, "svc.exe", path=None, created=1),
            proc(111, "svc.exe", path=None, created=2),
            proc(120, "editor.exe", editor, created=3),
            proc(121, "editor.exe", editor, created=4),
            proc(130, "browser.exe", browser, created=5),
            proc(131, "browser.exe", browser, parent=130, created=6),
            proc(132, "browser.exe", browser, parent=130, created=7),
            proc(133, "BROWSER.EXE", r"c:\apps\browser\BROWSER.EXE", parent=130, created=8),
        ]
        private = {
            110: 10 * MB, 111: 10 * MB,
            120: 600 * MB,  # 121 has no perf row
            130: 100 * MB, 131: 200 * MB, 132: 300 * MB, 133: 400 * MB,
        }
        summary = self.collect(FakePowerShell(machine(rows, private=private)))
        groups = self.groups(summary)

        self.assertEqual(
            [g.get("name") for g in groups],
            ["browser.exe", "editor.exe", "svc.exe (path not read)"],
        )
        ids = [g.get("id") for g in groups]
        self.assertEqual(sorted(ids), ["g1", "g2", "g3"], ids)
        self.assertEqual(summary["counts"].get("groups"), 3, summary["counts"])

        b = self.group_named(groups, "browser.exe")
        self.assertEqual(b.get("path").lower(), browser.lower(), b)
        self.assertEqual(b.get("count"), 4, b)
        self.assertEqual(sorted(b.get("pids")), [130, 131, 132, 133], b)
        self.assertEqual(b.get("memory_private_bytes"), 1000 * MB, b)
        self.assertEqual(b.get("memory_unread_count"), 0, b)
        self.assertIsInstance(b.get("unread_fields"), list, b)

        e = self.group_named(groups, "editor.exe")
        self.assertEqual(e.get("count"), 2, e)
        self.assertEqual(e.get("memory_private_bytes"), 600 * MB, e)
        self.assertEqual(e.get("memory_unread_count"), 1, e)

        s = self.group_named(groups, "svc.exe (path not read)")
        self.assertIsNone(s.get("path"), s)
        self.assertEqual(s.get("count"), 2, s)
        self.assertEqual(sorted(s.get("pids")), [110, 111], s)
        self.assertEqual(s.get("memory_private_bytes"), 20 * MB, s)


class TestSummary(ProcessesTestCase):
    def test_memory_and_command_lines_detail_only(self):
        studio = r"C:\Apps\Studio\studio.exe"
        token = "INVENTED-TOKEN-7731"
        command = f'"{studio}" --session-token={token}'
        rows = [
            proc(210, "studio.exe", studio, command_line=command, created=1),
            proc(211, "studio.exe", studio, command_line=command, parent=210, created=2),
        ]
        responses = machine(
            rows,
            private={210: 786432000, 211: 786432000},
            memory=memory_row(total_kb=8388608, free_kb=3145728),
        )
        summary = self.collect(FakePowerShell(responses))

        memory = summary["memory"]
        self.assertEqual(memory.get("total_bytes"), 8589934592, memory)
        self.assertEqual(memory.get("total_gb"), 8.0, memory)
        self.assertEqual(memory.get("available_gb"), 3.0, memory)
        self.assertEqual(memory.get("used_gb"), 5.0, memory)

        group = self.group_named(self.groups(summary), "studio.exe")
        self.assertEqual(group.get("memory_private_bytes"), 1572864000, group)
        self.assertEqual(group.get("memory_private_mb"), 1500.0, group)

        self.assertFalse(find_key(summary, "command_line"), "command_line in the summary")
        self.assertNotIn(token, self.summary_text(summary))

        detail = self.detail(summary)
        items = self.detail_processes(summary)
        self.assertEqual(items[210].get("command_line"), command)
        self.assertEqual(items[211].get("command_line"), command)
        detail_groups = [g for g in detail.get("groups") if g.get("id") == group.get("id")]
        self.assertEqual(len(detail_groups), 1, detail.get("groups"))
        self.assertEqual(
            sorted(p.get("command_line") for p in detail_groups[0].get("processes")),
            [command, command],
        )

    def test_budget(self):
        total = 4000
        rows = [
            proc(1000 + i, f"tool{i:04d}.exe", rf"C:\Apps\Tool{i:04d}\tool{i:04d}.exe",
                 created=1)
            for i in range(total)
        ]
        private = {1000 + i: (i + 1) * 4096 for i in range(total)}
        summary = self.collect(FakePowerShell(machine(rows, private=private)))

        self.assertLessEqual(len(self.summary_text(summary)), 35000)
        truncated = summary.get("truncated")
        self.assertIsInstance(truncated, int, summary.get("truncated"))
        self.assertGreater(truncated, 0)
        self.assertEqual(len(self.groups(summary)) + truncated, total)

        detail_groups = self.detail(summary).get("groups")
        self.assertEqual(len(detail_groups), total)
        self.assertEqual(len({g.get("id") for g in detail_groups}), total)

    def test_perf_or_memory_failure(self):
        rows = [
            proc(310, "alpha.exe", r"C:\Apps\Alpha\alpha.exe", working_set=50 * MB, created=1),
            proc(320, "beta.exe", r"C:\Apps\Beta\beta.exe", working_set=300 * MB, created=2),
            proc(330, "gamma.exe", r"C:\Apps\Gamma\gamma.exe", working_set=120 * MB,
                 created=3),
        ]

        with self.subTest("perf failed"):
            responses = machine(rows)
            responses["perf"] = failure("Invented: performance counters unavailable.")
            summary = self.collect(FakePowerShell(responses))
            self.assertEqual(self.source(summary, "perf").get("status"), "unreadable")
            self.assertEqual(summary.get("sorted_by"), "working_set_bytes")
            groups = self.groups(summary)
            self.assertEqual(
                [g.get("name") for g in groups], ["beta.exe", "gamma.exe", "alpha.exe"]
            )
            self.assertEqual(
                [g.get("working_set_mb") for g in groups], [300.0, 120.0, 50.0]
            )
            self.assertIn("listed_private_gb", summary["memory"])
            self.assertIsNone(summary["memory"].get("listed_private_gb"), summary["memory"])
            self.assertEqual(len(self.notes_about(summary, "perf")), 1,
                             self.not_checked(summary))

        with self.subTest("memory failed"):
            responses = machine(rows)
            responses["memory"] = failure("Invented: Win32_OperatingSystem unavailable.")
            summary = self.collect(FakePowerShell(responses))
            self.assertIn("total_gb", summary["memory"])
            self.assertIsNone(summary["memory"].get("total_gb"), summary["memory"])
            self.assertEqual(len(self.notes_about(summary, "memory")), 1,
                             self.not_checked(summary))
            self.assertEqual(
                sorted(g.get("name") for g in self.groups(summary)),
                ["alpha.exe", "beta.exe", "gamma.exe"],
            )

        with self.subTest("processes failed: no listed sum, not a zero"):
            responses = machine(rows)
            responses["processes"] = failure("Invented: Win32_Process unavailable.")
            summary = self.collect(FakePowerShell(responses))
            self.assertEqual(self.source(summary, "processes").get("status"), "unreadable")
            self.assertEqual(self.groups(summary), [])
            self.assertIsNone(summary["memory"].get("listed_private_bytes"), summary["memory"])
            self.assertIsNone(summary["memory"].get("listed_private_gb"), summary["memory"])


if __name__ == "__main__":
    unittest.main()

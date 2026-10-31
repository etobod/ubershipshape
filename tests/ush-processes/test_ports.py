"""Tests for skills/ush-processes/scripts/processes.py (plan 051, M2): TCP listening
ports and bound UDP endpoints. The interface is described in ``fakes.py`` and
``fakes_links.py``.

PowerShell never starts; every process, address (documentation ranges) and port is
invented.
"""

import json
import re
import unittest

from .fakes import FakePowerShell, failure, proc
from .fakes_links import (
    TCP_NOT_FOUND,
    LinksTestCase,
    endpoint,
    inventory_sources,
    responses,
    write_inventory,
)


class TestPorts(LinksTestCase):
    def collect_with_inventory(self, fake):
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources())
        return self.collect(fake, data_dir=data_dir)

    def test_scope_order_dedup(self):
        rows = [
            proc(4, "System", path=None, parent=0, created=0),
            proc(500, "host.exe", r"C:\Apps\Host\host.exe", created=1),
            proc(600, "web.exe", r"C:\Apps\Web\web.exe", created=2),
        ]
        tcp = [
            endpoint("0.0.0.0", 445, 4),
            endpoint("127.0.0.1", 5000, 600),
            endpoint("::1", 5000, 600),
            endpoint("192.0.2.10", 8080, 500),
            endpoint("0.0.0.0", 445, 4),
        ]
        udp = [
            endpoint("0.0.0.0", 0, 600),
            endpoint("0.0.0.0", 5353, 500),
            endpoint("0.0.0.0", 5355, 500),
            endpoint("127.0.0.1", 51000, 500),
        ]
        summary = self.collect_with_inventory(
            FakePowerShell(responses(rows, tcp=tcp, udp=udp)))

        g4 = self.group_with_pid(summary, 4).get("id")
        g500 = self.group_with_pid(summary, 500).get("id")
        g600 = self.group_with_pid(summary, 600).get("id")

        ports = self.ports(summary)
        self.assertEqual(len(ports), 4, ports)
        for port in ports:
            with self.subTest(port=port):
                self.assertEqual(str(port.get("protocol")).lower(), "tcp", port)
        self.assertEqual([p.get("scope") for p in ports],
                         ["all", "address", "loopback", "loopback"], ports)

        def view(port):
            return (port.get("local_address"), port.get("local_port"), port.get("pid"),
                    port.get("process"), port.get("group"))

        self.assertEqual(view(ports[0]), ("0.0.0.0", 445, 4, "System", g4))
        self.assertEqual(view(ports[1]), ("192.0.2.10", 8080, 500, "host.exe", g500))
        self.assertEqual(
            sorted(view(p) for p in ports[2:]),
            [("127.0.0.1", 5000, 600, "web.exe", g600), ("::1", 5000, 600, "web.exe", g600)],
        )

        self.assertEqual(summary["counts"].get("udp_port_zero"), 1, summary["counts"])
        udp_bound = summary.get("udp_bound")
        self.assertIsInstance(udp_bound, list, summary.get("udp_bound"))
        self.assertEqual(
            sorted((u.get("group"), u.get("scope"), u.get("count")) for u in udp_bound),
            sorted([(g500, "all", 2), (g500, "loopback", 1)]),
        )

    def test_budget_empty_and_failure(self):
        with self.subTest("4000 groups and 40 ports"):
            total = 4000
            rows = [
                proc(1000 + i, f"tool{i:04d}.exe", rf"C:\Apps\Tool{i:04d}\tool{i:04d}.exe",
                     created=1)
                for i in range(total)
            ]
            private = {1000 + i: (i + 1) * 4096 for i in range(total)}
            largest, smallest = 1000 + total - 1, 1000
            tcp = [endpoint("0.0.0.0", 20000 + n, largest) for n in range(39)]
            tcp.append(endpoint("0.0.0.0", 30000, smallest))
            udp = [endpoint("0.0.0.0", 5353, smallest)]
            summary = self.collect_with_inventory(
                FakePowerShell(responses(rows, tcp=tcp, udp=udp, private=private)))

            self.assertLessEqual(len(self.summary_text(summary)), 35000)
            self.assertGreater(summary.get("truncated") or 0, 0, summary.get("truncated"))
            ports = self.ports(summary)
            self.assertEqual(sorted(p.get("local_port") for p in ports),
                             sorted([20000 + n for n in range(39)] + [30000]))

            cut_id = self.detail_group_id(summary, smallest)
            self.assertNotIn(cut_id, [g.get("id") for g in self.groups(summary)])
            self.assertRegex(str(cut_id), r"^g[0-9]+$")
            cut_port = [p for p in ports if p.get("local_port") == 30000]
            self.assertEqual(len(cut_port), 1, ports)
            self.assertEqual(cut_port[0].get("group"), cut_id, cut_port[0])
            self.assertIs(cut_port[0].get("group_in_summary"), False, cut_port[0])
            self.assertEqual(summary["counts"].get("udp_bound_outside_summary"), 1,
                             summary["counts"])

        with self.subTest("4000 ports"):
            rows = [
                proc(500, "host.exe", r"C:\Apps\Host\host.exe", created=1),
                proc(600, "web.exe", r"C:\Apps\Web\web.exe", created=2),
            ]
            tcp = [endpoint("0.0.0.0", 10000 + n, 500) for n in range(4000)]
            summary = self.collect_with_inventory(FakePowerShell(responses(rows, tcp=tcp)))

            self.assertLessEqual(len(self.summary_text(summary)), 35000)
            kept = len(self.ports(summary))
            self.assertLess(kept, 4000)
            omitted = 4000 - kept
            pattern = re.compile(rf"(?<![0-9]){omitted}(?![0-9])")
            self.assertTrue(
                any(pattern.search(json.dumps(note)) for note in self.not_checked(summary)),
                f"no not_checked item names {omitted} omitted ports: "
                f"{self.not_checked(summary)}",
            )

        with self.subTest("no TCP listener is empty, not unreadable"):
            rows = [proc(500, "host.exe", r"C:\Apps\Host\host.exe", created=1)]
            fake_responses = responses(rows, udp=[endpoint("0.0.0.0", 5353, 500)])
            fake_responses["tcp_listeners"] = failure(TCP_NOT_FOUND)
            summary = self.collect_with_inventory(FakePowerShell(fake_responses))

            self.assertEqual(self.source(summary, "tcp_listeners").get("status"), "empty")
            self.assertEqual(self.notes_about(summary, "tcp_listeners"), [])
            self.assertEqual(self.ports(summary), [])

        with self.subTest("udp_endpoints failed, TCP read"):
            rows = [proc(500, "host.exe", r"C:\Apps\Host\host.exe", created=1)]
            fake_responses = responses(rows, tcp=[endpoint("0.0.0.0", 8443, 500)])
            fake_responses["udp_endpoints"] = failure("Invented: Get-NetUDPEndpoint failed.")
            summary = self.collect_with_inventory(FakePowerShell(fake_responses))

            ports = self.ports(summary)
            self.assertEqual([(p.get("local_port"), p.get("pid")) for p in ports],
                             [(8443, 500)])
            self.assertEqual(len(self.notes_about(summary, "udp_endpoints")), 1,
                             self.not_checked(summary))


class TestPortOwner(LinksTestCase):
    def test_port_of_unlisted_process_is_not_cut(self):
        rows = [proc(500, "server.exe", r"C:\Apps\Server\server.exe", created=1)]
        tcp = [endpoint("0.0.0.0", 8080, 500), endpoint("127.0.0.1", 9090, 777)]
        data_dir = self.data_dir()
        write_inventory(data_dir, inventory_sources())
        summary = self.collect(FakePowerShell(responses(rows, tcp=tcp)), data_dir=data_dir)

        by_port = {p.get("local_port"): p for p in self.ports(summary)}
        self.assertIs(by_port[8080].get("group_in_summary"), True, by_port)
        self.assertIsNone(by_port[9090].get("group"), by_port)
        self.assertIsNone(by_port[9090].get("group_in_summary"), by_port)


if __name__ == "__main__":
    unittest.main()

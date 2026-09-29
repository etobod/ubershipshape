"""Shutdown status carried by the next boot's Kernel-Boot 20 (invented data only).

Kernel-Boot 20 at the start of a boot reports in Properties[0] whether the
previous shutdown succeeded ("True"/"true") or not ("False"). A session
without 6006 that is followed by a cold boot whose Kernel-Boot 20 says the
shutdown succeeded has an unknown shutdown (None), not an unclean one.
A missing or unreadable status keeps the old rule (False), and crash events
of the next boot (6008, Kernel-Power 41) always keep it False.

Every event is created in the intended RecordId order: the code under test
orders by RecordId, so times inside a boot are out of order on purpose.
"""

import importlib
import unittest

# Helpers of the Fast Startup tests; the package name has a hyphen.
_fast = importlib.import_module("tests.ush-events.test_fast_startup")

CRASH_KINDS = ("unexpected_shutdown", "kernel_power_41")
BOOT_KEYS = {"index", "start", "end", "clean_shutdown", "boot_type", "hibernate_resumes"}
OTHER_PROVIDER = "Microsoft-Windows-WindowsUpdateClient"


def _crash_anomalies(result):
    return sorted(
        (a["kind"], a["boot"]) for a in result["anomalies"] if a["kind"] in CRASH_KINDS
    )


def shutdown_status_event(time, properties):
    """A Kernel-Boot 20 with the given Properties list."""
    return _fast.event(_fast.KERNEL_BOOT, 20, 4, time, properties)


def first_cold_session(closed=False):
    """Cold session on 2026-09-20 with one later event; 6006 only if closed."""
    events = _fast.boot_markers("2026-09-20", "08", "0") + [
        _fast.event(_fast.EVENTLOG, 6013, 4, "2026-09-20T12:00:00+02:00"),
    ]
    if closed:
        events.append(_fast.event(_fast.EVENTLOG, 6006, 4, "2026-09-20T18:00:00+02:00"))
    return events


def cold_boot_with_status(status_event_factory):
    """Next cold boot in the order 6009, 6005, 12, [status event], 27 "0".

    status_event_factory is called at its place in the order (so its RecordId
    falls between 12 and 27) and returns an event, or None for no event.
    """
    events = [
        _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
        _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
        _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
    ]
    status = status_event_factory("2026-09-21T08:00:01+02:00")
    if status is not None:
        events.append(status)
    events.append(_fast.boot_type_event("2026-09-21T08:00:02+02:00", "0"))
    return events


def crash_boot_with_status(properties):
    """Next boot in the order 12, Kernel-Boot 20, 27 "0", 6008, 6009, 6005, 41."""
    return [
        _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
        shutdown_status_event("2026-09-21T08:00:01+02:00", properties),
        _fast.boot_type_event("2026-09-21T08:00:02+02:00", "0"),
        _fast.event(_fast.EVENTLOG, 6008, 2, "2026-09-21T08:00:05+02:00"),
        _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
        _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
        _fast.event(_fast.KERNEL_POWER, 41, 1, "2026-09-21T08:00:12+02:00"),
    ]


class TestShutdownStatus(_fast.FastStartupTestCase):
    def test_successful_shutdown_before_cold_boot_is_unknown(self):
        # K1: no 6006, next cold boot's Kernel-Boot 20 says the shutdown succeeded.
        for value in ("True", "true"):
            with self.subTest(value=value):
                events = first_cold_session() + cold_boot_with_status(
                    lambda time, value=value: shutdown_status_event(time, [value])
                )
                boots = self.events.analyze(events, [])["boots"]
                self.assertEqual(
                    [(b["index"], b["boot_type"]) for b in boots],
                    [(1, "cold"), (2, "cold")],
                )
                self.assertIsNone(boots[0]["clean_shutdown"])

    def test_failed_shutdown_stays_unclean(self):
        # K2: next boot says the shutdown failed and shows crash events.
        events = first_cold_session() + crash_boot_with_status(["False"])
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2])
        self.assertIs(boots[0]["clean_shutdown"], False)
        self.assertEqual(
            _crash_anomalies(result),
            [("kernel_power_41", 2), ("unexpected_shutdown", 2)],
        )

    def test_missing_or_unreadable_status_keeps_old_rule(self):
        # K3: no Kernel-Boot 20, or one whose status cannot be read.
        cases = {
            "no event 20": lambda time: None,
            "empty properties": lambda time: shutdown_status_event(time, []),
            "empty string": lambda time: shutdown_status_event(time, [""]),
            "unknown value": lambda time: shutdown_status_event(time, ["x"]),
        }
        for name, factory in cases.items():
            with self.subTest(case=name):
                events = first_cold_session() + cold_boot_with_status(factory)
                boots = self.events.analyze(events, [])["boots"]
                self.assertEqual([b["index"] for b in boots], [1, 2])
                self.assertIs(boots[0]["clean_shutdown"], False)

    def test_clean_session_unchanged_and_no_new_field(self):
        # K4: clean data; the session closed by 6006 stays clean.
        events = first_cold_session(closed=True) + cold_boot_with_status(
            lambda time: shutdown_status_event(time, ["True"])
        )
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2])
        self.assertIs(boots[0]["clean_shutdown"], True)
        for boot in boots:
            self.assertEqual(set(boot), BOOT_KEYS)

    def test_status_only_from_kernel_boot(self):
        # K5: an Id 20 from another provider carries no shutdown status.
        self.assertIn(20, self.events.PASS_B_IDS)
        events = first_cold_session() + cold_boot_with_status(
            lambda time: _fast.event(OTHER_PROVIDER, 20, 4, time, ["True"])
        )
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2])
        self.assertIs(boots[0]["clean_shutdown"], False)

    def test_crash_events_override_successful_status(self):
        # K6: Kernel-Boot 20 says "True" but the next boot shows 6008 and 41.
        events = first_cold_session() + crash_boot_with_status(["True"])
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2])
        self.assertIs(boots[0]["clean_shutdown"], False)
        self.assertEqual(
            _crash_anomalies(result),
            [("kernel_power_41", 2), ("unexpected_shutdown", 2)],
        )

    def test_crash_keeps_unclean_before_joined_fast_startup_27(self):
        # Review of M2: a Fast Startup 27 that joins the crash boot must not
        # hide the 6008 and 41 recorded in it.
        events = first_cold_session() + [
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
            _fast.event(_fast.EVENTLOG, 6008, 2, "2026-09-21T08:00:05+02:00"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
            _fast.event(_fast.KERNEL_POWER, 41, 1, "2026-09-21T08:00:12+02:00"),
            _fast.boot_type_event("2026-09-22T08:00:02+02:00", "1"),
        ]
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual([(b["index"], b["boot_type"]) for b in boots],
                         [(1, "cold"), (2, "fast_startup")])
        self.assertIs(boots[0]["clean_shutdown"], False)

    def test_joined_fast_startup_27_without_crash_stays_unknown(self):
        # Clean-data guard for the test above: no 6008 and no 41.
        events = first_cold_session() + [
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
            _fast.boot_type_event("2026-09-22T08:00:02+02:00", "1"),
        ]
        boots = self.events.analyze(events, [])["boots"]
        self.assertIsNone(boots[0]["clean_shutdown"])

    def test_crash_event_before_markers_counts_for_next_boot(self):
        # Review of M3: a 6008 written before the first marker of the boot
        # that reports the crash must not mark the crashed session itself.
        events = first_cold_session() + cold_boot_with_status(
            lambda time: shutdown_status_event(time, ["True"])
        ) + [
            _fast.event(_fast.EVENTLOG, 6008, 2, "2026-09-22T08:00:05+02:00"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-22T08:00:10+02:00"),
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-22T08:00:00+02:00"),
            shutdown_status_event("2026-09-22T08:00:01+02:00", ["True"]),
            _fast.boot_type_event("2026-09-22T08:00:02+02:00", "0"),
        ]
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual([b["index"] for b in boots], [1, 2, 3])
        self.assertIsNone(boots[0]["clean_shutdown"])
        self.assertIs(boots[1]["clean_shutdown"], False)
        self.assertEqual(_crash_anomalies(result), [("unexpected_shutdown", 3)])

    def test_crash_events_after_markers_do_not_reach_next_boot(self):
        # Review of M3, round 2: 6008 and 41 after all markers of the boot
        # that reports the crash stay with it; a later Fast Startup boot or
        # a successful status keeps the shutdown before it unknown.
        def crash_boot():
            return [
                _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
                _fast.boot_type_event("2026-09-21T08:00:02+02:00", "0"),
                _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
                _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
                _fast.event(_fast.EVENTLOG, 6008, 2, "2026-09-21T08:00:11+02:00"),
                _fast.event(_fast.KERNEL_POWER, 41, 1, "2026-09-21T08:00:12+02:00"),
            ]

        next_boots = {
            "fast_startup": lambda: [
                _fast.boot_type_event("2026-09-22T08:00:02+02:00", "1")
            ],
            "status_true": lambda: cold_boot_with_status(
                lambda time: shutdown_status_event(time.replace("09-21", "09-22"), ["True"])
            ),
        }
        for name, later in next_boots.items():
            with self.subTest(next_boot=name):
                # Built in RecordId order: each call creates the next events.
                events = first_cold_session()
                events += crash_boot()
                events += later()
                result = self.events.analyze(events, [])
                boots = result["boots"]
                self.assertEqual([b["index"] for b in boots], [1, 2, 3])
                self.assertIs(boots[0]["clean_shutdown"], False)
                self.assertIsNone(boots[1]["clean_shutdown"])
                self.assertEqual(
                    _crash_anomalies(result),
                    [("kernel_power_41", 2), ("unexpected_shutdown", 2)],
                )

    def test_last_6008_of_reporting_boot_stays_with_it(self):
        # QA of plan 032: a 6008 that is the last collected event of the boot
        # reporting the crash belongs to that boot; the Fast Startup boot after
        # it keeps the shutdown before it unknown, not unclean.
        events = first_cold_session() + [
            _fast.event(_fast.KERNEL_GENERAL, 12, 4, "2026-09-21T08:00:00+02:00"),
            _fast.boot_type_event("2026-09-21T08:00:02+02:00", "0"),
            _fast.event(_fast.KERNEL_POWER, 41, 1, "2026-09-21T08:00:12+02:00"),
            _fast.event(_fast.EVENTLOG, 6009, 4, "2026-09-21T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6005, 4, "2026-09-21T08:00:10+02:00"),
            _fast.event(_fast.EVENTLOG, 6008, 2, "2026-09-21T08:00:11+02:00"),
            _fast.boot_type_event("2026-09-22T08:00:02+02:00", "1"),
        ]
        result = self.events.analyze(events, [])
        boots = result["boots"]
        self.assertEqual(
            [(b["index"], b["boot_type"]) for b in boots],
            [(1, "cold"), (2, "cold"), (3, "fast_startup")],
        )
        self.assertIs(boots[0]["clean_shutdown"], False)
        self.assertIsNone(boots[1]["clean_shutdown"])
        self.assertEqual(
            _crash_anomalies(result),
            [("kernel_power_41", 2), ("unexpected_shutdown", 2)],
        )


if __name__ == "__main__":
    unittest.main()

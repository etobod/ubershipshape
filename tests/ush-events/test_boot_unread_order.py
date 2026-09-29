"""Which session an unreadable Kernel-Boot 27 marks (invented data only)."""

import importlib
import unittest

# Helpers of the Fast Startup tests; the package name has a hyphen.
_fast = importlib.import_module("tests.ush-events.test_fast_startup")


class TestUnreadableBootOrder(_fast.FastStartupTestCase):
    def test_unreadable_27_after_a_typed_one_marks_the_next_boot(self):
        # Two cold sessions without 6006; the next boot's unreadable 27 comes
        # before its own markers, after the second session's typed 27.
        events = (_fast.boot_markers("2026-09-20", "08", "0")
                  + _fast.boot_markers("2026-09-21", "08", "0")
                  + [_fast.unreadable_boot_type_event("2026-09-22T08:00:02+02:00")]
                  + _fast.boot_without_type("2026-09-22", "08"))
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual([(b["index"], b["clean_shutdown"]) for b in boots],
                         [(1, False), (2, None), (3, None)])

    def test_unreadable_27_after_6006_marks_the_next_boot(self):
        events = (_fast.boot_markers("2026-09-20", "08", "0")
                  + _fast.boot_without_type("2026-09-21", "08")
                  + [_fast.event(_fast.EVENTLOG, 6006, 4, "2026-09-21T18:00:00+02:00"),
                     _fast.unreadable_boot_type_event("2026-09-22T08:00:02+02:00")]
                  + _fast.boot_without_type("2026-09-22", "08"))
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual([(b["index"], b["clean_shutdown"]) for b in boots],
                         [(1, False), (2, True), (3, None)])


    def test_unreadable_27_before_the_first_boot_leaves_session_0_unknown(self):
        # Session 0 started before the window; boot 1 wrote an unreadable 27
        # before its markers, so it may have been Fast Startup.
        events = ([_fast.event(_fast.EVENTLOG, 6013, 4, "2026-09-20T07:00:00+02:00"),
                   _fast.unreadable_boot_type_event("2026-09-20T07:59:59+02:00")]
                  + _fast.boot_without_type("2026-09-20", "08"))
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual([(b["index"], b["clean_shutdown"]) for b in boots],
                         [(0, None), (1, None)])

    def test_early_unreadable_27s_leave_every_shutdown_unknown(self):
        # Each boot writes its unreadable 27 before its own markers; the 27
        # may belong to either session, so no shutdown is called unclean.
        events = []
        for day in ("2026-09-20", "2026-09-21", "2026-09-22"):
            events += [_fast.unreadable_boot_type_event(f"{day}T07:59:59+02:00")]
            events += _fast.boot_without_type(day, "08")
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual([(b["index"], b["clean_shutdown"]) for b in boots],
                         [(1, None), (2, None), (3, None)])

    def test_unreadable_27_after_the_markers_invents_no_session(self):
        # 009 M3 K6 in written order: the unreadable 27 comes after 6005.
        events = (_fast.boot_without_type("2026-09-20", "08")
                  + [_fast.unreadable_boot_type_event("2026-09-20T08:00:01+02:00"),
                     _fast.boot_type_event("2026-09-20T08:00:02+02:00", "0")])
        boots = self.events.analyze(events, [])["boots"]
        self.assertEqual([(b["index"], b["clean_shutdown"], b["boot_type"]) for b in boots],
                         [(1, None, "cold")])


if __name__ == "__main__":
    unittest.main()

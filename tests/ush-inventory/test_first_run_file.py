"""The first-run decision file of skills/ush-inventory/scripts/inventory.py (plan 092,
milestone M2, criteria K4-K15).

Interface these tests assume (from the plan):

- ``<data dir>/state/ush-inventory.first-run.json``, one file for the normal and the
  elevated mode: ``{"schema_version": 1, "entries": [{"subject_cn", "serial",
  "decided_at", "matched": [thumbprints], "unchecked": [thumbprints]}]}``; thumbprints
  and serials upper case. A saved entry never changes.
- ``inventory.save_first_run(state_dir, data, read_back=None)`` writes it and raises
  ``OSError`` or ``ValueError`` on failure.
- A failed write or an unreadable file gives a ``not_checked`` item whose ``what`` names
  ``first-run certificates``.
- An unreadable file gives every matching ``machine_root`` certificate
  ``windows_first_run`` null, with ``windows_first_run`` in ``unread_fields``.

The helpers of ``TestFirstRunCertificates`` in ``test_additions.py`` are reused, not
copied. PowerShell never starts; every data directory is temporary; every value is
invented.
"""

import json
import unittest
from datetime import timedelta
from unittest import mock

from . import test_additions as additions
from .fakes import NOW, failure, ok
from .fakes_additions import AdditionsTestCase, cert, certificates_result, thumb
from .test_shipped_thumbprints import AUTHENTICODE_CN, FIRST_RUN_KEY, WINDOWS_OWN

authenticode = additions.authenticode
machine_root = additions.machine_root
fake = additions.fake

FIRST_RUN_NOTE = "first-run certificates"
DECISION_FILE = "ush-inventory.first-run.json"

_helpers = additions.TestFirstRunCertificates


class TestFirstRunFile(AdditionsTestCase):
    """Plan 092, milestone M2: the first-run decision is made once, kept in its own
    state file and applied by every later run in both modes."""

    # Reused from TestFirstRunCertificates (test_additions.py).
    cert_key = _helpers.cert_key
    listed = _helpers.listed
    cert_item = _helpers.cert_item
    run_on = _helpers.run_on
    assert_trusted = _helpers.assert_trusted
    assert_listed_not_own = _helpers.assert_listed_not_own
    own_file_with = _helpers.own_file_with
    bad_first_run_data = _helpers.bad_first_run_data

    # --- helpers ------------------------------------------------------------------------

    def run_elevated(self, data_dir, day, *certificates):
        return self.collect(machine_root(*certificates), data_dir=data_dir, admin=True,
                            now=NOW + timedelta(days=day))

    def decision_path(self, data_dir):
        return data_dir / "state" / DECISION_FILE

    def decisions(self, data_dir):
        path = self.decision_path(data_dir)
        self.assertTrue(path.is_file(), f"{path} was not written")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertIsInstance(data, dict, data)
        self.assertEqual(data.get("schema_version"), 1, data)
        self.assertIsInstance(data.get("entries"), list, data)
        return data

    def entry(self, data_dir, subject_cn=AUTHENTICODE_CN, serial="01"):
        entries = [e for e in self.decisions(data_dir)["entries"]
                   if isinstance(e, dict) and e.get("subject_cn") == subject_cn
                   and e.get("serial") == serial]
        self.assertEqual(len(entries), 1,
                         f"entries for {subject_cn!r}/{serial}: "
                         f"{self.decisions(data_dir)['entries']}")
        return entries[0]

    def first_run_notes(self, summary):
        return [item for item in self.not_checked(summary)
                if FIRST_RUN_NOTE in str(item.get("what"))]

    def assert_listed_first_run_false(self, summary, key):
        self.assert_listed_not_own(summary, key)
        item = self.cert_item(summary, key)
        self.assertIn("windows_first_run", item, item)
        self.assertIs(item.get("windows_first_run"), False, item)

    # --- K4-K15 -------------------------------------------------------------------------

    def test_first_run_writes_decision(self):
        data_dir = self.data_dir()
        listed = thumb(0x9201)
        key = self.cert_key("machine_root", listed)
        summary = self.run_on(data_dir, 0, authenticode(listed))

        entry = self.entry(data_dir)
        self.assertEqual(entry.get("subject_cn"), AUTHENTICODE_CN, entry)
        self.assertEqual(entry.get("serial"), "01", entry)
        self.assertEqual(entry.get("matched"), [listed], entry)
        self.assertEqual(entry.get("unchecked"), [], entry)
        decided_at = entry.get("decided_at")
        self.assertIsInstance(decided_at, str, entry)
        self.assertTrue(decided_at.strip(), entry)

        self.assert_trusted(summary, key)

    def test_elevated_first_run_uses_same_decision(self):
        data_dir = self.data_dir()
        first, later = thumb(0x9202), thumb(0x9203)
        self.run_on(data_dir, 0, authenticode(first))
        before = self.entry(data_dir)
        self.assertEqual(before.get("matched"), [first], before)
        self.assertFalse((data_dir / "state" / "ush-inventory.elevated.json").exists(),
                         "an elevated baseline exists before the first elevated run")

        elevated = self.run_elevated(data_dir, 1, authenticode(later))
        self.assert_listed_first_run_false(elevated, self.cert_key("machine_root", later))

        after = self.entry(data_dir)
        self.assertEqual(after.get("matched"), [first], after)
        self.assertEqual(after, before)

    def test_two_matches_never_trusted(self):
        data_dir = self.data_dir()
        one, two = thumb(0x9204), thumb(0x9205)
        key = self.cert_key("machine_root", two)
        self.run_on(data_dir, 0, authenticode(one), authenticode(two))

        with self.subTest(mode="normal"):
            normal = self.run_on(data_dir, 1, authenticode(two))
            self.assert_listed_first_run_false(normal, key)
        with self.subTest(mode="elevated"):
            elevated = self.run_elevated(data_dir, 2, authenticode(two))
            self.assert_listed_first_run_false(elevated, key)

    def test_bad_list_run_keeps_decision(self):
        bad, good = self.bad_first_run_data()
        own_file = self.own_file_with(good)
        data_dir = self.data_dir()
        pinned, planted = thumb(0x9206), thumb(0x9207)
        planted_key = self.cert_key("machine_root", planted)

        first = self.run_on(data_dir, 0, authenticode(pinned))
        self.assert_trusted(first, self.cert_key("machine_root", pinned))
        second = self.run_on(data_dir, 1, authenticode(planted))
        self.assert_listed_first_run_false(second, planted_key)

        own_file.write_text(json.dumps(bad), encoding="utf-8")
        self.run_on(data_dir, 2, authenticode(planted))

        own_file.write_text(json.dumps(good), encoding="utf-8")
        fourth = self.run_on(data_dir, 3, authenticode(planted))
        self.assert_listed_first_run_false(fourth, planted_key)

    def test_bad_list_first_run_writes_nothing(self):
        bad, good = self.bad_first_run_data()
        own_file = self.own_file_with(bad)
        data_dir = self.data_dir()
        listed = thumb(0x9208)
        key = self.cert_key("machine_root", listed)

        self.run_on(data_dir, 0, authenticode(listed))
        self.assertFalse(self.decision_path(data_dir).exists(),
                         "the decision file was written by a run with an unusable list")

        own_file.write_text(json.dumps(good), encoding="utf-8")
        second = self.run_on(data_dir, 1, authenticode(listed))
        self.assert_trusted(second, key)
        self.assertEqual(self.entry(data_dir).get("matched"), [listed])

    def test_bad_list_applies_recorded_decision(self):
        bad, good = self.bad_first_run_data()
        own_file = self.own_file_with(good)
        data_dir = self.data_dir()
        pinned, planted = thumb(0x9209), thumb(0x920A)
        self.run_on(data_dir, 0, authenticode(pinned))

        own_file.write_text(json.dumps(bad), encoding="utf-8")
        second = self.run_on(data_dir, 1, authenticode(pinned), authenticode(planted))
        self.assert_trusted(second, self.cert_key("machine_root", pinned))
        self.assert_listed_first_run_false(second, self.cert_key("machine_root", planted))

    def test_unreadable_file_is_kept(self):
        data_dir = self.data_dir()
        path = self.decision_path(data_dir)
        path.parent.mkdir(parents=True)
        broken = b'{"schema_version": 1, "entries": [{"subject_cn": '
        path.write_bytes(broken)

        listed = thumb(0x920B)
        key = self.cert_key("machine_root", listed)
        summary = self.run_on(data_dir, 0, authenticode(listed))

        self.assertEqual(path.read_bytes(), broken, "the unreadable decision file changed")
        notes = self.first_run_notes(summary)
        self.assertTrue(notes, summary.get("not_checked"))
        self.assertTrue(
            any(DECISION_FILE in str(n.get("what")) + " " + str(n.get("reason"))
                for n in notes),
            notes,
        )

        item = self.cert_item(summary, key)
        self.assertIn("windows_first_run", item, item)
        self.assertIsNone(item.get("windows_first_run"), item)
        self.assertIn("windows_first_run", item.get("unread_fields") or [], item)
        self.assert_listed_not_own(summary, key)

    def test_unchecked_cert_trusted_when_read(self):
        data_dir = self.data_dir()
        real, planted = thumb(0x920C), thumb(0x920D)
        self.run_on(data_dir, 0, authenticode(real, details=False))

        entry = self.entry(data_dir)
        self.assertEqual(entry.get("matched"), [], entry)
        self.assertEqual(entry.get("unchecked"), [real], entry)

        second = self.run_on(data_dir, 1, authenticode(real), authenticode(planted))
        self.assert_trusted(second, self.cert_key("machine_root", real))
        self.assert_listed_first_run_false(second, self.cert_key("machine_root", planted))

    def test_write_failure_reported(self):
        self.assertTrue(hasattr(self.inventory, "save_first_run"),
                        "inventory has no save_first_run")

        def failing_save(*args, **kwargs):
            raise OSError("invented write failure")

        patcher = mock.patch.object(self.inventory, "save_first_run", failing_save)
        patcher.start()
        self.addCleanup(patcher.stop)

        data_dir = self.data_dir()
        listed = thumb(0x920E)
        key = self.cert_key("machine_root", listed)
        summary = self.run_on(data_dir, 0, authenticode(listed))

        notes = self.first_run_notes(summary)
        self.assertTrue(notes, summary.get("not_checked"))
        for note in notes:
            reason = note.get("reason")
            self.assertIsInstance(reason, str, note)
            self.assertTrue(reason.strip(), note)
        self.assert_trusted(summary, key)
        self.assertFalse(self.decision_path(data_dir).exists(),
                         "the decision file exists although the write failed")

    def test_failed_read_writes_nothing(self):
        # Control: the same machine with the certificates read does write the file,
        # so the absence below comes from the failed read.
        control = self.data_dir()
        self.run_on(control, 0, authenticode(thumb(0x9211)))
        self.assertTrue(self.decision_path(control).exists(), "control run wrote nothing")

        data_dir = self.data_dir()
        summary = self.collect(fake(root_certificates=failure("Invented access denied")),
                               data_dir=data_dir)
        self.assert_unreadable(summary, "root_certificates")
        self.assertFalse(self.decision_path(data_dir).exists(),
                         "the decision file was written without a root_certificates read")

    def test_new_list_entry_decided_later(self):
        good = json.loads(WINDOWS_OWN.read_text(encoding="utf-8-sig"))
        own_file = self.own_file_with(good)
        data_dir = self.data_dir()
        pinned, second_root = thumb(0x920F), thumb(0x9210)
        self.run_on(data_dir, 0, authenticode(pinned))
        before = self.decisions(data_dir)["entries"]
        first_entry = self.entry(data_dir)

        new_cn = "Invented First Run Root"
        extended = json.loads(json.dumps(good))
        extended[FIRST_RUN_KEY].append({
            "subject_cn": new_cn,
            "serial": "0A",
            "source": "https://learn.microsoft.com/invented-page",
        })
        own_file.write_text(json.dumps(extended), encoding="utf-8")

        new_cert = cert(second_root, subject=f"CN={new_cn}, O=Invented Corp, C=US",
                        serial="0A")
        second = self.run_on(data_dir, 1, authenticode(pinned), new_cert)

        self.assertEqual(self.entry(data_dir), first_entry)
        after = self.decisions(data_dir)["entries"]
        for entry in before:
            self.assertIn(entry, after)
        added = self.entry(data_dir, subject_cn=new_cn, serial="0A")
        self.assertEqual(added.get("matched"), [second_root], added)
        self.assertEqual(added.get("unchecked"), [], added)
        self.assert_trusted(second, self.cert_key("machine_root", second_root))
        self.assert_trusted(second, self.cert_key("machine_root", pinned))

    def test_clean_machine_no_match(self):
        # The same invented machine as TestFirstRunCertificates.test_clean_data_unchanged,
        # whose result is the one without a decision file.
        data_dir = self.data_dir()
        foreign, user = thumb(0x9211), thumb(0x9212)
        auth = [cert(thumb(0x9220 + n), subject=f"CN=Invented Auth Root {n}")
                for n in range(3)]
        summary = self.collect(fake(root_certificates=ok(certificates_result(
            machine_root=[cert(foreign, subject="CN=Invented Foreign Root", serial="01")],
            user_root=[cert(user, subject="CN=Invented User Root",
                            issuer="CN=Invented Other CA")],
            authroot=auth,
        ))), data_dir=data_dir)

        entries = self.decisions(data_dir)["entries"]
        self.assertTrue(entries, "the decision file has no entries")
        self.entry(data_dir)
        for entry in entries:
            with self.subTest(entry=entry.get("subject_cn")):
                self.assertEqual(entry.get("matched"), [], entry)
                self.assertEqual(entry.get("unchecked"), [], entry)

        listed = self.listed(summary)
        self.assertEqual(set(listed), {self.cert_key("machine_root", foreign),
                                       self.cert_key("user_root", user)}, listed)
        self.assertEqual(self.own_counts(summary).get("root_certificates"), 3,
                         self.own_counts(summary))
        items = (list(listed.values())
                 + self.detail_additions_of(summary, "root_certificate"))
        marked = [item.get("key") for item in items if "windows_first_run" in item]
        self.assertEqual(marked, [], "windows_first_run on clean data")


if __name__ == "__main__":
    unittest.main()

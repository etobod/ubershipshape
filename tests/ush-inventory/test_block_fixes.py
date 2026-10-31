"""Regression tests for five fixes of the ``--block`` printer (plan 005, M1, review).

1. The read-back filter of an "other service" is a single-quoted PowerShell string, so
   ``$`` and backticks in the name are not expanded; ``\\`` is doubled for WQL.
2. A Run, RunOnce or Startup value name with ``*``, ``?``, ``[`` or ``]`` gets no block
   (``-Name`` takes them as wildcards).
3. A service with ``user_service`` in ``unread_fields`` gets no block.
4. An entry whose lines do not encode in the console's code page gets the ASCII line
   ``# <id>: no block: a value cannot be shown in this console's code page``.
5. An HKCU-shell entry gets no block when the run was elevated or its elevation is not
   known.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import io
import json
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout

from .fakes import NOW, FakePowerShell
from .test_block import (
    RUN_ENTRY,
    SERVICE_ENTRY,
    STAMP,
    TASK_ENTRY,
    USER_SERVICE_ENTRY,
    BlockTestCase,
    commands,
    detail_document,
)

CODE_PAGE_LINE = "no block: a value is not ASCII, so the text read from the console could differ"

RUN_ONCE_ENTRY = {
    "id": "s7",
    "key": "run:hkcu\\RunOnce:InventedSetup",
    "source": "run_keys",
    "kind": "run_once",
    "location": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce",
    "name": "InventedSetup",
    "command": "\"%LOCALAPPDATA%\\InventedSetup\\finish.exe\" /quiet",
    "value_kind": "ExpandString",
    "targets": ["%LOCALAPPDATA%\\InventedSetup\\finish.exe"],
    "approved": "not_set",
    "enabled": True,
    "own": False,
}

STARTUP_ENTRY = {
    "id": "s8",
    "key": "startup:user:InventedLauncher.lnk",
    "source": "startup_folders",
    "kind": "startup_folder",
    "location": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup",
    "name": "InventedLauncher.lnk",
    "command": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
               "\\InventedLauncher.lnk",
    "approved": "not_set",
    "enabled": True,
    "own": False,
}


def entry(base, **changes):
    result = dict(base)
    result.update(changes)
    return result


def no_block_pattern(item_id):
    return rf"(?m)^#\s*{item_id}\s*:\s*no block\s*:\s*\S"


class FixTestCase(BlockTestCase):
    def prepare_entries(self, entries, elevated=False):
        """A data dir whose detail file holds ``entries``; ``elevated`` None drops the
        key. Returns (data_dir, detail_file)."""
        data_dir = self.data_dir()
        work = data_dir / "work"
        work.mkdir(parents=True)
        summary_file = work / f"inventory-{STAMP}.summary.json"
        summary_file.write_text(json.dumps({"skill": "ush-inventory", "not_checked": []}),
                                encoding="utf-8")
        document = detail_document(summary_file)
        document["autostart"] = [dict(item) for item in entries]
        document["listed"]["autostart"] = [item["id"] for item in entries]
        if elevated is None:
            del document["elevated"]
        else:
            document["elevated"] = elevated
        detail_file = work / f"inventory-{STAMP}.detail.json"
        detail_file.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return data_dir, detail_file

    def assert_no_block(self, stdout, item_id, name):
        self.assertRegex(stdout, no_block_pattern(item_id), stdout)
        self.assertFalse(any(name in line for line in commands(stdout)), stdout)


class TestServiceFilter(FixTestCase):
    def test_filter_is_single_quoted(self):
        cases = {
            "dollar": ("INVENTEDSQL$INSTANCE", "'Name=''INVENTEDSQL$INSTANCE'''"),
            "backtick": ("Invented`Agent", "'Name=''Invented`Agent'''"),
            "backslash": ("Invented\\Agent", "'Name=''Invented\\\\Agent'''"),
        }
        for case, (name, expected) in cases.items():
            with self.subTest(case=case):
                item = entry(SERVICE_ENTRY, name=name, key=f"service:{name}")
                data_dir, detail_file = self.prepare_entries([item])
                code, stdout, stderr = self.block(data_dir, ["s3"], detail_file=detail_file)
                self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                reads = [line for line in commands(stdout) if "Win32_Service" in line]
                self.assertEqual(len(reads), 1, stdout)
                self.assertIn(f"-Filter {expected})", reads[0])
                self.assertNotIn('"', reads[0])


class TestWildcardNames(FixTestCase):
    def test_wildcard_value_names_get_no_block(self):
        for base in (RUN_ENTRY, RUN_ONCE_ENTRY, STARTUP_ENTRY):
            for char in "*?[]":
                with self.subTest(kind=base["kind"], char=char):
                    name = f"Invented{char}Name"
                    item = entry(base, name=name,
                                 key=base["key"].rsplit(":", 1)[0] + ":" + name)
                    data_dir, detail_file = self.prepare_entries([item])
                    _code, stdout, _stderr = self.block(data_dir, [item["id"]],
                                                        detail_file=detail_file)
                    self.assertEqual(commands(stdout), [], stdout)
                    self.assert_no_block(stdout, item["id"], name)
                    self.assertIn("wildcard", stdout)

    def test_plain_value_names_keep_their_block(self):
        # Clean data: the same entries without a wildcard still get a block.
        for base in (RUN_ENTRY, RUN_ONCE_ENTRY, STARTUP_ENTRY):
            with self.subTest(kind=base["kind"]):
                data_dir, detail_file = self.prepare_entries([base])
                code, stdout, stderr = self.block(data_dir, [base["id"]],
                                                  detail_file=detail_file)
                self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                self.assertTrue(any(f"'{base['name']}'" in line
                                    for line in commands(stdout)), stdout)


class TestGuessedUserService(FixTestCase):
    def test_guessed_user_service_gets_no_block(self):
        for base in (USER_SERVICE_ENTRY, SERVICE_ENTRY):
            with self.subTest(user_service=base["user_service"]):
                item = entry(base, unread_fields=["user_service"])
                data_dir, detail_file = self.prepare_entries([item])
                _code, stdout, _stderr = self.block(data_dir, [item["id"]],
                                                    detail_file=detail_file)
                self.assertEqual(commands(stdout), [], stdout)
                self.assert_no_block(stdout, item["id"], item["name"])
                self.assertIn("user_service", stdout)

    def test_read_user_service_keeps_its_block(self):
        for base in (USER_SERVICE_ENTRY, SERVICE_ENTRY):
            with self.subTest(user_service=base["user_service"]):
                item = entry(base, unread_fields=["display_name"])
                data_dir, detail_file = self.prepare_entries([item])
                code, stdout, stderr = self.block(data_dir, [item["id"]],
                                                  detail_file=detail_file)
                self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                self.assertTrue(commands(stdout), stdout)


class TestCodePage(FixTestCase):
    def block_to(self, data_dir, ids, detail_file, stdout):
        """Run ``--block`` with ``stdout`` as sys.stdout; a print that cannot encode
        fails the test instead of raising."""
        err = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(err):
                code = self.inventory.main(
                    ["--data-dir", str(data_dir), "--block", ",".join(ids),
                     "--detail-file", str(detail_file)],
                    run_ps=FakePowerShell(), is_admin=lambda: False, now=NOW)
        except UnicodeEncodeError as exc:
            self.fail(f"printing the blocks raised {exc!r}")
        return code, err.getvalue()

    def test_entry_outside_the_code_page_gets_no_block(self):
        odd = entry(RUN_ENTRY, name="Invented\u2603Tool",
                    key="run:hkcu\\Run:Invented\u2603Tool")
        data_dir, detail_file = self.prepare_entries([odd, TASK_ENTRY])
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding="ascii", newline="\n")
        code, stderr = self.block_to(data_dir, ["s1", "s2"], detail_file, stdout)
        stdout.flush()
        text = raw.getvalue().decode("ascii")
        self.assertEqual(code, 0, stderr[:300] or text[:300])
        self.assertIn(f"# s1: {CODE_PAGE_LINE}", text.splitlines())
        self.assertFalse(any("Invented" in line and "Tool" in line
                             for line in commands(text)), text)
        # The other entry is printed whole.
        self.assertTrue(any("Disable-ScheduledTask" in line for line in commands(text)), text)

    def test_non_ascii_name_gets_no_block_on_a_utf8_console(self):
        # A Polish letter encodes in UTF-8 and cp1250 alike, but the reader of the pipe
        # may decode it with another code page: no block, and exit 1 with no command.
        odd = entry(RUN_ENTRY, name="Narz\u0119dzie",
                    key="run:hkcu\\Run:Narz\u0119dzie")
        data_dir, detail_file = self.prepare_entries([odd])
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
        code, stderr = self.block_to(data_dir, ["s1"], detail_file, stdout)
        stdout.flush()
        text = raw.getvalue().decode("utf-8")
        self.assertEqual(code, 1, stderr[:300] or text[:300])
        self.assertIn(f"# s1: {CODE_PAGE_LINE}", text.splitlines())
        self.assertEqual(commands(text), [])

    def test_entry_inside_the_code_page_keeps_its_block(self):
        data_dir, detail_file = self.prepare_entries([RUN_ENTRY])
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding="ascii", newline="\n")
        code, stderr = self.block_to(data_dir, ["s1"], detail_file, stdout)
        stdout.flush()
        text = raw.getvalue().decode("ascii")
        self.assertEqual(code, 0, stderr[:300] or text[:300])
        self.assertNotIn("code page", text)
        self.assertTrue(commands(text), text)


class TestElevatedRun(FixTestCase):
    def test_hkcu_entries_of_an_elevated_run_get_no_block(self):
        for elevated in (True, None, "yes"):
            for base in (RUN_ENTRY, STARTUP_ENTRY, RUN_ONCE_ENTRY):
                with self.subTest(elevated=elevated, kind=base["kind"]):
                    data_dir, detail_file = self.prepare_entries([base], elevated=elevated)
                    _code, stdout, _stderr = self.block(data_dir, [base["id"]],
                                                        detail_file=detail_file)
                    self.assertEqual(commands(stdout), [], stdout)
                    self.assert_no_block(stdout, base["id"], base["name"])
                    self.assertIn("elevated", stdout)
                    if elevated is True:
                        self.assertIn("--detail-file", stdout)

    def test_elevated_shell_entries_keep_their_block(self):
        # Clean data: HKLM-shell entries of an elevated run, and HKCU entries of a
        # non-elevated run, keep their block.
        hklm = entry(RUN_ENTRY, key="run:hklm64\\Run:InventedTool",
                     location="HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run")
        cases = [(True, hklm), (True, TASK_ENTRY), (True, SERVICE_ENTRY),
                 (False, RUN_ENTRY), (False, STARTUP_ENTRY), (False, RUN_ONCE_ENTRY)]
        for elevated, base in cases:
            with self.subTest(elevated=elevated, key=base["key"]):
                data_dir, detail_file = self.prepare_entries([base], elevated=elevated)
                code, stdout, stderr = self.block(data_dir, [base["id"]],
                                                  detail_file=detail_file)
                self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                self.assertTrue(commands(stdout), stdout)
                self.assertIsNone(re.search(no_block_pattern(base["id"]), stdout), stdout)


class TestUnreadTaskState(FixTestCase):
    # Plan 005 final review: a task whose State was not read must not get a block whose
    # rollback enables it.
    def test_task_with_unread_state_gets_no_block(self):
        for state in (None, "", "Unknown"):
            with self.subTest(state=state):
                item = entry(TASK_ENTRY, state=state, enabled=True)
                data_dir, detail_file = self.prepare_entries([item])
                _code, stdout, _stderr = self.block(data_dir, [item["id"]],
                                                    detail_file=detail_file)
                self.assertEqual(commands(stdout), [], stdout)
                self.assert_no_block(stdout, item["id"], item["name"])
                self.assertIn("state", stdout)

    def test_task_with_read_state_keeps_its_block(self):
        for state in ("Ready", "Running"):
            with self.subTest(state=state):
                item = entry(TASK_ENTRY, state=state)
                data_dir, detail_file = self.prepare_entries([item])
                code, stdout, stderr = self.block(data_dir, [item["id"]],
                                                  detail_file=detail_file)
                self.assertEqual(code, 0, stderr[:300] or stdout[:300])
                self.assertTrue(any("Disable-ScheduledTask" in line
                                    for line in commands(stdout)), stdout)


if __name__ == "__main__":
    unittest.main()

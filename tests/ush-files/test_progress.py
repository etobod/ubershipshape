"""Progress lines of the ush-files scan on stderr (plan 071, M1).

The general interface is described in ``fakes.py``. Interface from the plan (M1):

- With progress enabled (``USH_PROGRESS=1``), ``files.py`` prints ``drive <i> / <total>``
  (with the drive letter) when each drive walk starts, and a directory counter without a
  total (``<label> <n> directories``) during the walk; the final counter line of a walk
  is printed when it ends. Scans are named by kind and position, never by a path.
- stdout stays exactly the JSON summary.

Assumptions added by this test beyond the plan text:

- The progress helper reads ``os.environ`` and ``sys.stderr`` at call time; the test sets
  ``USH_PROGRESS`` in ``os.environ`` and also in the injected ``environ`` of ``main``.
- The drive letter appears in the ``drive <i> / <total>`` line as a separate word
  (``C``, ``C:`` or ``(C:)``).
- Paths written into the summary under the data directory differ between two runs only
  by the data directory itself, so the comparison replaces it with a placeholder.

Every name and size is invented; nothing comes from a machine.
"""

import json
import os
import re
import unittest
from unittest import mock

from .fakes import FAKE_PROFILE, FakeMachine, FilesTestCase, fake_environ

# Distinctive invented names, so any of them in a progress line is a leaked path.
NAMES = ("Alphawood", "Betamarsh", "Gammafen", "Deltacove", "Epsilonrock",
         "zetafile.bin", "etafile.bin", "thetafile.bin")


def trees():
    return {
        "C": {
            "Alphawood": {"Betamarsh": {"zetafile.bin": 10}, "etafile.bin": 4},
            "Gammafen": {"thetafile.bin": 5},
        },
        "D": {
            "Deltacove": {"Epsilonrock": {"zetafile.bin": 7}},
        },
    }


def placeholder(value, data_dir):
    """Replace the data directory in every string of a parsed JSON value."""
    prefixes = {str(data_dir), str(data_dir).replace("\\", "/")}
    if isinstance(value, dict):
        return {key: placeholder(item, data_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [placeholder(item, data_dir) for item in value]
    if isinstance(value, str):
        for prefix in prefixes:
            value = value.replace(prefix, "<data>")
        return value
    return value


class TestFilesProgress(FilesTestCase):
    def run_with(self, progress_on):
        data_dir = self.data_dir()
        environ = fake_environ()
        with mock.patch.dict(os.environ):
            if progress_on:
                os.environ["USH_PROGRESS"] = "1"
                environ["USH_PROGRESS"] = "1"
            else:
                os.environ.pop("USH_PROGRESS", None)
            code, stdout, stderr = self.run_main(data_dir, FakeMachine(trees()),
                                                 environ=environ)
        self.assertEqual(code, 0, stderr[-500:])
        return placeholder(self.parse(stdout), data_dir), stderr

    def test_scan_progress_on_stderr_stdout_is_json(self):
        quiet_summary, _ = self.run_with(False)
        summary, stderr = self.run_with(True)

        with self.subTest("stdout is the same JSON summary"):
            self.assertIsInstance(summary, dict)
            self.assertEqual(summary, quiet_summary)

        lines = [line.rstrip("\r") for line in stderr.splitlines() if line.strip()]

        with self.subTest("drive lines"):
            for index, letter in ((1, "C"), (2, "D")):
                matches = [line for line in lines
                           if re.match(rf"^drive {index} / 2\b", line)]
                self.assertEqual(len(matches), 1, lines)
                self.assertRegex(matches[0], rf"\b{letter}\b")

        with self.subTest("directory counter lines"):
            counters = [line for line in lines if re.fullmatch(r".+ \d+ directories", line)]
            self.assertTrue(counters, lines)

        with self.subTest("no path in any line"):
            for line in lines:
                self.assertNotIn("\\", line)
                self.assertNotIn(FAKE_PROFILE.lower(), line.lower())
                self.assertNotIn("tester", line.lower())
                for name in NAMES:
                    self.assertNotIn(name.lower(), line.lower())
            self.assertNotIn(json.dumps(FAKE_PROFILE)[1:-1], stderr)


if __name__ == "__main__":
    unittest.main()

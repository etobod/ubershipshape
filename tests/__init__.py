"""Test package.

For the whole run the data directory points at a fresh temporary directory
(``USH_DATA_DIR``) and ``LOCALAPPDATA`` is removed, so a script called without
``--data-dir`` never reads or writes the real profile.
"""

import atexit
import os
import shutil
import tempfile

_DATA_DIR = tempfile.mkdtemp(prefix="ush-tests-")
atexit.register(shutil.rmtree, _DATA_DIR, ignore_errors=True)
os.environ["USH_DATA_DIR"] = _DATA_DIR
os.environ.pop("LOCALAPPDATA", None)

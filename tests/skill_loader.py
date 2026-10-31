"""Load skill scripts by file path.

Skill directories contain a hyphen (``skills/ush-events/``), so they are not
importable packages. Tests load a script module straight from its file.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).absolute().parents[1]


def script_path(skill: str, script: str) -> Path:
    """Return the absolute path of ``skills/<skill>/scripts/<script>.py``."""
    return REPO_ROOT / "skills" / skill / "scripts" / f"{script}.py"


def load_script(skill: str, script: str):
    """Import ``skills/<skill>/scripts/<script>.py`` and return the module."""
    path = script_path(skill, script)
    name = f"ush_{skill.replace('-', '_')}_{script}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: dataclasses look their module up in sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

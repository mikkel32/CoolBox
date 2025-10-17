"""Virtual environment management helpers."""
from __future__ import annotations

import sys

from ._logging import log
from ._state import get_venv_dir

__all__ = ["_venv_python", "ensure_venv"]


def _venv_python() -> str:
    venv_dir = get_venv_dir()
    python = venv_dir / (
        "Scripts/python.exe" if sys.platform.startswith("win") else "bin/python"
    )
    return str(python)


def ensure_venv() -> str:
    venv_dir = get_venv_dir()
    if not venv_dir.exists():
        log(f"Creating venv at {venv_dir}")
        import venv as _venv

        _venv.EnvBuilder(with_pip=True, clear=False, upgrade=False).create(str(venv_dir))
    return _venv_python()

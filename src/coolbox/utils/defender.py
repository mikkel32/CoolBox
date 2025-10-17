"""Compatibility wrapper for :mod:`coolbox.utils.security.defender`."""
from __future__ import annotations

from .security.defender import *  # type: ignore F401,F403
from .security import defender as _defender_module

for _compat_name in ("_run_ex", "_ps"):
    if hasattr(_defender_module, _compat_name):
        globals()[_compat_name] = getattr(_defender_module, _compat_name)

__all__ = getattr(_defender_module, "__all__", [name for name in globals() if not name.startswith("_")])

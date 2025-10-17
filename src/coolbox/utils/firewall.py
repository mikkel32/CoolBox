"""Compatibility wrapper for :mod:`coolbox.utils.security.firewall`."""
from __future__ import annotations

from .security.firewall import *  # type: ignore F401,F403
from .security import firewall as _firewall_module

for _compat_name in ("_run_ex", "_ps"):
    if hasattr(_firewall_module, _compat_name):
        globals()[_compat_name] = getattr(_firewall_module, _compat_name)

__all__ = getattr(_firewall_module, "__all__", [name for name in globals() if not name.startswith("_")])

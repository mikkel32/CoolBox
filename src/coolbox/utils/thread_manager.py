"""Compatibility wrapper for :mod:`coolbox.utils.processes.thread_manager`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .processes.thread_manager import *  # type: ignore F401,F403
from .processes import thread_manager as _thread_manager

try:  # pragma: no cover - target may not define __all__
    from .processes.thread_manager import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(
        name for name in vars(_thread_manager) if not name.startswith("_")
    )

del _thread_manager

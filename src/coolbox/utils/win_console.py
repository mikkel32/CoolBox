"""Compatibility wrapper for :mod:`coolbox.utils.system.win_console`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .system.win_console import *  # type: ignore F401,F403
from .system import win_console as _win_console

try:  # pragma: no cover - target may not define __all__
    from .system.win_console import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_win_console) if not name.startswith("_"))

del _win_console

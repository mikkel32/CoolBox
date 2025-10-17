"""Compatibility wrapper for :mod:`coolbox.utils.system.win_console`."""
from __future__ import annotations

from .system.win_console import *  # type: ignore F401,F403
try:  # pragma: no cover - target may not define __all__
    from .system.win_console import __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = [name for name in globals() if not name.startswith('_')]

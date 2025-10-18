"""Compatibility wrapper for :mod:`coolbox.utils.system`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .system import *  # type: ignore F401,F403
from . import system as _system

try:  # pragma: no cover - target may not define __all__
    from .system import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_system) if not name.startswith("_"))

del _system

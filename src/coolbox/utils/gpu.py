"""Compatibility wrapper for :mod:`coolbox.utils.system.gpu`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .system.gpu import *  # type: ignore F401,F403
from .system import gpu as _gpu

try:  # pragma: no cover - target may not define __all__
    from .system.gpu import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_gpu) if not name.startswith("_"))

del _gpu

"""Compatibility wrapper for :mod:`coolbox.utils.system.vm`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .system.vm import *  # type: ignore F401,F403
from .system import vm as _vm

try:  # pragma: no cover - target may not define __all__
    from .system.vm import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_vm) if not name.startswith("_"))

del _vm

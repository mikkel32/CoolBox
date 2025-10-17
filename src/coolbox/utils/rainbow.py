"""Compatibility wrapper for :mod:`coolbox.utils.display.rainbow`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .display.rainbow import *  # type: ignore F401,F403
from .display import rainbow as _rainbow

try:  # pragma: no cover - target may not define __all__
    from .display.rainbow import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_rainbow) if not name.startswith("_"))

del _rainbow

"""Compatibility wrapper for :mod:`coolbox.utils.display.hover_tracker`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .display.hover_tracker import *  # type: ignore F401,F403
from .display import hover_tracker as _hover_tracker

try:  # pragma: no cover - target may not define __all__
    from .display.hover_tracker import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_hover_tracker) if not name.startswith("_"))

del _hover_tracker

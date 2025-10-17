"""Compatibility wrapper for :mod:`coolbox.utils.display.hover_tracker`."""
from __future__ import annotations

from .display.hover_tracker import *  # type: ignore F401,F403
try:  # pragma: no cover - target may not define __all__
    from .display.hover_tracker import __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = [name for name in globals() if not name.startswith('_')]

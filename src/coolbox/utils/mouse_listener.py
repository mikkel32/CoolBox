"""Compatibility wrapper for :mod:`coolbox.utils.display.mouse_listener`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .display.mouse_listener import *  # type: ignore F401,F403
from .display import mouse_listener as _mouse_listener

try:  # pragma: no cover - target may not define __all__
    from .display.mouse_listener import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_mouse_listener) if not name.startswith("_"))

del _mouse_listener

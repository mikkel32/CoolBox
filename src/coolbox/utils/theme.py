"""Compatibility wrapper for :mod:`coolbox.utils.display.theme`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .display.theme import *  # type: ignore F401,F403
from .display import theme as _theme

try:  # pragma: no cover - target may not define __all__
    from .display.theme import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_theme) if not name.startswith("_"))

if hasattr(_theme, "_ConfigLike"):
    _ConfigLike = _theme._ConfigLike
    if "_ConfigLike" not in __all__:
        __all__ = tuple(list(__all__) + ["_ConfigLike"])

del _theme

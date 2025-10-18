"""Compatibility wrapper for :mod:`coolbox.utils.display.color_utils`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .display.color_utils import *  # type: ignore F401,F403
from .display import color_utils as _color_utils

try:  # pragma: no cover - target may not define __all__
    from .display.color_utils import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_color_utils) if not name.startswith("_"))

del _color_utils

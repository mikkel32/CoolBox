"""Compatibility wrapper for :mod:`coolbox.utils.system.helpers`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .system.helpers import *  # type: ignore F401,F403
from .system import helpers as _helpers

try:  # pragma: no cover - target may not define __all__
    from .system.helpers import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_helpers) if not name.startswith("_"))

del _helpers

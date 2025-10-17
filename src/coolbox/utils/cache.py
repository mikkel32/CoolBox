"""Compatibility wrapper for :mod:`coolbox.utils.files.cache`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .files.cache import *  # type: ignore F401,F403
from .files import cache as _cache

try:  # pragma: no cover - target may not define __all__
    from .files.cache import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_cache) if not name.startswith("_"))

del _cache

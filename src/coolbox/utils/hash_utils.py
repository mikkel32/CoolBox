"""Compatibility wrapper for :mod:`coolbox.utils.system.hash_utils`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .system.hash_utils import *  # type: ignore F401,F403
from .system import hash_utils as _hash_utils

try:  # pragma: no cover - target may not define __all__
    from .system.hash_utils import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_hash_utils) if not name.startswith("_"))

del _hash_utils

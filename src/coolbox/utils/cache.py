"""Compatibility wrapper for :mod:`coolbox.utils.files.cache`."""
from __future__ import annotations

from .files.cache import *  # type: ignore F401,F403
try:  # pragma: no cover - target may not define __all__
    from .files.cache import __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = [name for name in globals() if not name.startswith('_')]

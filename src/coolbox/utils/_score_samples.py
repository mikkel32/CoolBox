"""Compatibility wrapper for :mod:`coolbox.utils.analysis._score_samples`."""
from __future__ import annotations

try:  # pragma: no cover - optional extension may be missing
    from .analysis._score_samples import *  # type: ignore F401,F403
    try:  # pragma: no cover - target may not define __all__
        from .analysis._score_samples import __all__  # type: ignore F401
    except ImportError:  # pragma: no cover - fallback when __all__ missing
        __all__ = [name for name in globals() if not name.startswith("_")]
except Exception:  # pragma: no cover - extension unavailable
    __all__ = []

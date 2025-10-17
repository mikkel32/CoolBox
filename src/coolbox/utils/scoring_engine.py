"""Compatibility wrapper for :mod:`coolbox.utils.analysis.scoring_engine`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .analysis.scoring_engine import *  # type: ignore F401,F403
from .analysis import scoring_engine as _scoring_engine

try:  # pragma: no cover - target may not define __all__
    from .analysis.scoring_engine import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_scoring_engine) if not name.startswith("_"))

del _scoring_engine

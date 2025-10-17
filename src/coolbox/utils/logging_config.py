"""Compatibility wrapper for :mod:`coolbox.utils.system.logging_config`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .system.logging_config import *  # type: ignore F401,F403
from .system import logging_config as _logging_config

try:  # pragma: no cover - target may not define __all__
    from .system.logging_config import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_logging_config) if not name.startswith("_"))

del _logging_config

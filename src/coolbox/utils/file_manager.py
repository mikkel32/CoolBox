"""Compatibility wrapper for :mod:`coolbox.utils.files.file_manager`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .files.file_manager import *  # type: ignore F401,F403
from .files import file_manager as _file_manager

try:  # pragma: no cover - target may not define __all__
    from .files.file_manager import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_file_manager) if not name.startswith("_"))

del _file_manager

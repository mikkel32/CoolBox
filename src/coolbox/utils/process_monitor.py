"""Compatibility wrapper for :mod:`coolbox.utils.processes.monitor`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .processes.monitor import *  # type: ignore F401,F403
from .processes import monitor as _monitor

try:  # pragma: no cover - target may not define __all__
    from .processes.monitor import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_monitor) if not name.startswith("_"))

del _monitor

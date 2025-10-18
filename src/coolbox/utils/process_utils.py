"""Compatibility wrapper for :mod:`coolbox.utils.processes.utils`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .processes.utils import *  # type: ignore F401,F403
from .processes import utils as _utils

try:  # pragma: no cover - target may not define __all__
    from .processes.utils import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_utils) if not name.startswith("_"))

del _utils

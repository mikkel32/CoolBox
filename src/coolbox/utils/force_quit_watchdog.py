"""Compatibility wrapper for :mod:`coolbox.utils.processes.force_quit_watchdog`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .processes.force_quit_watchdog import *  # type: ignore F401,F403
from .processes import force_quit_watchdog as _force_quit_watchdog

try:  # pragma: no cover - target may not define __all__
    from .processes.force_quit_watchdog import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(
        name for name in vars(_force_quit_watchdog) if not name.startswith("_")
    )

del _force_quit_watchdog

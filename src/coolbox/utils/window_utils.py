"""Compatibility wrapper for :mod:`coolbox.utils.display.window_utils`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from .display.window_utils import *  # type: ignore F401,F403
from .display import window_utils as _window_utils

try:  # pragma: no cover - target may not define __all__
    from .display.window_utils import __all__ as __all__  # type: ignore F401
except ImportError:  # pragma: no cover - fallback when __all__ missing
    __all__ = tuple(name for name in vars(_window_utils) if not name.startswith("_"))

if hasattr(_window_utils, "_TRANSIENT_PIDS"):
    _TRANSIENT_PIDS = _window_utils._TRANSIENT_PIDS
if hasattr(_window_utils, "_MIN_WINDOW_WIDTH"):
    _MIN_WINDOW_WIDTH = _window_utils._MIN_WINDOW_WIDTH
if hasattr(_window_utils, "_MIN_WINDOW_HEIGHT"):
    _MIN_WINDOW_HEIGHT = _window_utils._MIN_WINDOW_HEIGHT
if hasattr(_window_utils, "_CFG_LOADED"):
    _CFG_LOADED = _window_utils._CFG_LOADED
if hasattr(_window_utils, "_WINDOWS_CACHE"):
    _WINDOWS_CACHE = _window_utils._WINDOWS_CACHE
if hasattr(_window_utils, "_WINDOWS_THREAD"):
    _WINDOWS_THREAD = _window_utils._WINDOWS_THREAD
if hasattr(_window_utils, "_WINDOWS_EVENT_UNSUB"):
    _WINDOWS_EVENT_UNSUB = _window_utils._WINDOWS_EVENT_UNSUB
if hasattr(_window_utils, "_WINDOWS_EVENTS_SUPPORTED"):
    _WINDOWS_EVENTS_SUPPORTED = _window_utils._WINDOWS_EVENTS_SUPPORTED
if hasattr(_window_utils, "_WINDOWS_REFRESH"):
    _WINDOWS_REFRESH = _window_utils._WINDOWS_REFRESH
if hasattr(_window_utils, "_RECENT_WINDOWS"):
    _RECENT_WINDOWS = _window_utils._RECENT_WINDOWS
if hasattr(_window_utils, "_fallback_list_windows_at"):
    _fallback_list_windows_at = _window_utils._fallback_list_windows_at
if hasattr(_window_utils, "_remember_window"):
    _remember_window = _window_utils._remember_window
if hasattr(_window_utils, "_cleanup_recent"):
    _cleanup_recent = _window_utils._cleanup_recent

_exported_private = [
    name
    for name in (
        "_TRANSIENT_PIDS",
        "_MIN_WINDOW_WIDTH",
        "_MIN_WINDOW_HEIGHT",
        "_CFG_LOADED",
        "_WINDOWS_CACHE",
        "_WINDOWS_THREAD",
        "_WINDOWS_EVENT_UNSUB",
        "_WINDOWS_EVENTS_SUPPORTED",
        "_WINDOWS_REFRESH",
        "_RECENT_WINDOWS",
        "_fallback_list_windows_at",
        "_remember_window",
        "_cleanup_recent",
    )
    if name in locals()
]

if _exported_private:
    __all__ = tuple(list(__all__) + _exported_private)

del _window_utils

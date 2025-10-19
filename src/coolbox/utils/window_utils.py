"""Compatibility wrapper for :mod:`coolbox.utils.display.window_utils`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

import importlib
import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING, cast


def _load_window_module() -> ModuleType:
    """Return a freshly imported window utilities module."""

    module = importlib.import_module("coolbox.utils.display.window_utils")
    return importlib.reload(module)


def _reexport(module: ModuleType) -> tuple[str, ...]:
    exported: list[str] = []
    for name in dir(module):
        if name.startswith("__") and name.endswith("__"):
            continue
        globals()[name] = getattr(module, name)
        exported.append(name)
    return tuple(dict.fromkeys(exported))


_TARGET_MODULE = _load_window_module()
__all__ = cast(tuple[str, ...], _reexport(_TARGET_MODULE))  # pyright: ignore[reportUnsupportedDunderOperation]

if TYPE_CHECKING:  # pragma: no cover - expose runtime attributes for typing
    from coolbox.utils.display.window_utils import (
        filter_windows_at,
        has_active_window_support,
        has_cursor_window_support,
        WindowInfo,
        _CFG_LOADED,
        _MIN_WINDOW_HEIGHT,
        _MIN_WINDOW_WIDTH,
        _WINDOWS_CACHE,
        _WINDOWS_THREAD,
        _WINDOWS_EVENT_UNSUB,
        _WINDOWS_EVENTS_SUPPORTED,
        get_active_window,
        get_window_under_cursor,
        list_windows_at,
        make_window_clickthrough,
        remove_window_clickthrough,
        set_window_colorkey,
        subscribe_active_window,
        subscribe_window_change,
        is_transient_pid,
    )


class _WindowProxy(ModuleType):
    """Mirror attribute updates onto the underlying window module."""

    def __getattr__(self, name: str):  # type: ignore[override]
        try:
            return super().__getattribute__(name)
        except AttributeError:
            return getattr(_TARGET_MODULE, name)

    def __setattr__(self, name: str, value):  # type: ignore[override]
        target = _TARGET_MODULE
        if (
            name == "_TARGET_MODULE"
            or name.startswith("__")
            or getattr(target, "__name__", None) == __name__
        ):
            super().__setattr__(name, value)
            return
        setattr(target, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name: str):  # type: ignore[override]
        target = _TARGET_MODULE
        if (
            name == "_TARGET_MODULE"
            or name.startswith("__")
            or getattr(target, "__name__", None) == __name__
        ):
            super().__delattr__(name)
            return
        if hasattr(target, name):
            delattr(target, name)
        super().__delattr__(name)


_module_obj = sys.modules.get(__name__)
if _module_obj is not None:
    _module_obj.__class__ = _WindowProxy


del importlib, ModuleType, _load_window_module, _reexport

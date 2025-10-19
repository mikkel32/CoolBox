from __future__ import annotations

from typing import Any, Callable, Iterable

from coolbox.utils.display.window_utils import (
    WindowInfo as WindowInfo,
    filter_windows_at as filter_windows_at,
    has_active_window_support as has_active_window_support,
    has_cursor_window_support as has_cursor_window_support,
    is_transient_pid as is_transient_pid,
    list_windows_at as list_windows_at,
    make_window_clickthrough as make_window_clickthrough,
    remove_window_clickthrough as remove_window_clickthrough,
    set_window_colorkey as set_window_colorkey,
    subscribe_active_window as subscribe_active_window,
    subscribe_window_change as subscribe_window_change,
)

_MIN_WINDOW_WIDTH: int
_MIN_WINDOW_HEIGHT: int
_CFG_LOADED: bool
_WINDOWS_CACHE: dict[str, Any]
_WINDOWS_THREAD: Any
_WINDOWS_EVENT_UNSUB: Callable[[], None] | None
_WINDOWS_EVENTS_SUPPORTED: bool


def get_active_window() -> WindowInfo: ...

def get_window_under_cursor() -> WindowInfo: ...

def list_windows() -> Iterable[WindowInfo]: ...

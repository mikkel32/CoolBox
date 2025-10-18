"""Display-related utilities grouped under a dedicated namespace."""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from .color_utils import adjust_color, darken_color, hex_brightness, lighten_color
from .rainbow import NeonPulseBorder, RainbowBorder

__all__ = [
    "adjust_color",
    "darken_color",
    "hex_brightness",
    "lighten_color",
    "RainbowBorder",
    "NeonPulseBorder",
    "window_utils",
    "HoverTracker",
    "capture_mouse",
    "get_global_listener",
    "is_supported",
    "log",
    "ThemeManager",
    "_ConfigLike",
    "center_window",
    "get_screen_refresh_rate",
]

if TYPE_CHECKING:
    from . import window_utils as window_utils
    from .hover_tracker import HoverTracker
    from .mouse_listener import (
        capture_mouse,
        get_global_listener,
        is_supported,
        log,
    )
    from .theme import ThemeManager, _ConfigLike
    from .ui import center_window, get_screen_refresh_rate


_LAZY_ATTRS = {
    "window_utils": "coolbox.utils.display.window_utils",
    "HoverTracker": "coolbox.utils.display.hover_tracker",
    "capture_mouse": "coolbox.utils.display.mouse_listener",
    "get_global_listener": "coolbox.utils.display.mouse_listener",
    "is_supported": "coolbox.utils.display.mouse_listener",
    "log": "coolbox.utils.display.mouse_listener",
    "ThemeManager": "coolbox.utils.display.theme",
    "_ConfigLike": "coolbox.utils.display.theme",
    "center_window": "coolbox.utils.display.ui",
    "get_screen_refresh_rate": "coolbox.utils.display.ui",
}


def __getattr__(name: str) -> Any:
    try:
        module_name = _LAZY_ATTRS[name]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise AttributeError(name) from exc
    module = import_module(module_name)
    value = getattr(module, name, module if name == "window_utils" else None)
    if name == "window_utils":
        globals()[name] = module
        return module
    if value is None:  # pragma: no cover - should not happen
        raise AttributeError(name)
    globals()[name] = value
    return value

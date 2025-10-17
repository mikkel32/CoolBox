"""Compatibility wrapper for :mod:`coolbox.utils.display.ui`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

import os

_FALLBACK_EXPORTS = ("center_window", "get_screen_refresh_rate")


def _fallback() -> tuple[str, ...]:
    def center_window(*_args: object, **_kwargs: object) -> None:
        """No-op placeholder when UI dependencies are unavailable."""

    def get_screen_refresh_rate(*_args: object, **_kwargs: object) -> int:
        """Return a conservative refresh rate in lightweight mode."""

        return 60

    globals().update(
        {
            "center_window": center_window,
            "get_screen_refresh_rate": get_screen_refresh_rate,
        }
    )
    return _FALLBACK_EXPORTS


if os.environ.get("COOLBOX_LIGHTWEIGHT"):
    __all__ = _fallback()
else:  # pragma: no cover - runtime import of optional dependencies
    try:
        from .display import ui as _ui_module
    except Exception:  # pragma: no cover - missing optional dependencies
        __all__ = _fallback()
    else:
        from .display.ui import *  # type: ignore F401,F403
        try:  # pragma: no cover - target may not define __all__
            from .display.ui import __all__ as __all__  # type: ignore F401
        except ImportError:  # pragma: no cover - fallback when __all__ missing
            __all__ = tuple(
                name for name in vars(_ui_module) if not name.startswith("_")
            )
        del _ui_module

"""Compatibility wrapper for :mod:`coolbox.utils.display.ui`."""
from __future__ import annotations

import os


def _fallback() -> None:
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
    globals()["__all__"] = ["center_window", "get_screen_refresh_rate"]


if os.environ.get("COOLBOX_LIGHTWEIGHT"):
    _fallback()
else:  # pragma: no cover - runtime import of optional dependencies
    try:
        from .display.ui import *  # type: ignore F401,F403
        try:  # pragma: no cover - target may not define __all__
            from .display.ui import __all__  # type: ignore F401
        except ImportError:  # pragma: no cover - fallback when __all__ missing
            __all__ = [name for name in globals() if not name.startswith("_")]
    except Exception:  # pragma: no cover - missing optional dependencies
        _fallback()

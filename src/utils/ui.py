import os
import subprocess
import sys
import customtkinter as ctk

try:  # pragma: no cover - optional OS modules
    import ctypes
except Exception:  # pragma: no cover
    ctypes = None
try:  # pragma: no cover - optional OS modules
    from Quartz import (
        CGDisplayCopyDisplayMode,
        CGMainDisplayID,
        CGDisplayModeGetRefreshRate,
    )
except Exception:  # pragma: no cover
    CGDisplayCopyDisplayMode = None


def center_window(window: ctk.CTkToplevel) -> None:
    """Center *window* on the screen."""
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = (window.winfo_screenwidth() - width) // 2
    y = (window.winfo_screenheight() - height) // 2
    window.geometry(f"{width}x{height}+{x}+{y}")


def get_screen_refresh_rate(default: int = 60) -> int:
    """Return the primary monitor refresh rate in Hz.

    If the rate cannot be determined, ``default`` is returned.
    """

    # Allow manual override for tests and edge cases
    env = os.getenv("COOLBOX_REFRESH_RATE")
    if env and env.isdigit():
        return int(env)

    # macOS
    if sys.platform == "darwin" and CGDisplayCopyDisplayMode:
        try:
            mode = CGDisplayCopyDisplayMode(CGMainDisplayID())
            rate = int(round(CGDisplayModeGetRefreshRate(mode)))
            if rate:
                return rate
        except Exception:  # pragma: no cover - best effort only
            pass

    # Windows
    if os.name == "nt" and ctypes is not None:
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            dc = user32.GetDC(0)
            VREFRESH = 116
            rate = gdi32.GetDeviceCaps(dc, VREFRESH)
            user32.ReleaseDC(0, dc)
            if rate:
                return int(rate)
        except Exception:  # pragma: no cover - best effort only
            pass

    # X11 via xrandr
    if sys.platform.startswith("linux"):
        try:
            out = subprocess.check_output(["xrandr", "--current"], text=True)
            for line in out.splitlines():
                if "*" in line:
                    parts = line.split()
                    for p in parts:
                        if p.endswith("*") and p[:-1].replace(".", "", 1).isdigit():
                            return int(float(p[:-1]))
        except Exception:  # pragma: no cover - optional tool
            pass

    return int(default)

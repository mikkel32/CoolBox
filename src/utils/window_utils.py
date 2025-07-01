from __future__ import annotations

"""Helpers for retrieving information about desktop windows."""

import ctypes
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from ctypes import wintypes
from typing import List
from typing import Any


@dataclass(frozen=True)
class WindowInfo:
    """Process ID, geometry and title for a window."""

    pid: int | None
    rect: tuple[int, int, int, int] | None = None
    title: str | None = None


def has_active_window_support() -> bool:
    """Return ``True`` if active window detection should work on this system."""
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    return bool(shutil.which("xdotool") and shutil.which("xprop"))


def has_cursor_window_support() -> bool:
    """Return ``True`` if detecting the window under the cursor is supported."""
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        try:
            import Quartz  # noqa: F401
        except Exception:
            return False
        return True
    return bool(
        shutil.which("xdotool") and shutil.which("xprop") and shutil.which("xwininfo")
    )


def get_active_window() -> WindowInfo:
    """Return information about the currently active window."""
    if sys.platform.startswith("win"):
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo(None)
        rect = wintypes.RECT()
        geom = None
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geom = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        return WindowInfo(int(pid.value) if pid.value else None, geom, title)

    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to get unix id of (first process whose frontmost is true)',
                ],
                text=True,
            )
            pid = int(out.strip())
            title = None
            try:
                title = subprocess.check_output(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events" to tell (first process whose frontmost is true) to get name of front window',
                    ],
                    text=True,
                ).strip()
            except Exception:
                pass
            return WindowInfo(pid, None, title or None)
        except Exception:
            return WindowInfo(None)

    xdotool = shutil.which("xdotool")
    xprop = shutil.which("xprop")
    xwininfo = shutil.which("xwininfo")
    if not xdotool or not xprop:
        return WindowInfo(None)
    try:
        win = subprocess.check_output([xdotool, "getwindowfocus"], text=True).strip()
        pid_line = subprocess.check_output(
            [xprop, "-id", win, "_NET_WM_PID"], text=True
        )
        match = re.search(r"= (\d+)", pid_line)
        pid = int(match.group(1)) if match else None
        geom = None
        title = None
        if xwininfo:
            geom_out = subprocess.check_output([xwininfo, "-id", win], text=True)
            gx = re.search(r"Absolute upper-left X:\s+(\d+)", geom_out)
            gy = re.search(r"Absolute upper-left Y:\s+(\d+)", geom_out)
            gw = re.search(r"Width:\s+(\d+)", geom_out)
            gh = re.search(r"Height:\s+(\d+)", geom_out)
            if gx and gy and gw and gh:
                geom = (
                    int(gx.group(1)),
                    int(gy.group(1)),
                    int(gw.group(1)),
                    int(gh.group(1)),
                )
        title_out = subprocess.check_output([xprop, "-id", win, "WM_NAME"], text=True)
        title_match = re.search(r'"(.*)"', title_out)
        if title_match:
            title = title_match.group(1)
        return WindowInfo(pid, geom, title)
    except Exception:
        return WindowInfo(None)


def get_window_under_cursor() -> WindowInfo:
    """Return information about the window under the mouse cursor."""
    if sys.platform.startswith("win"):
        pt = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return WindowInfo(None)
        hwnd = ctypes.windll.user32.WindowFromPoint(pt)
        if not hwnd:
            return WindowInfo(None)
        rect = wintypes.RECT()
        geom = None
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geom = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        return WindowInfo(int(pid.value) if pid.value else None, geom, title)

    if sys.platform == "darwin":
        try:
            import Quartz

            event = Quartz.CGEventCreate(None)
            loc = Quartz.CGEventGetLocation(event)
            windows = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
            )
            for win in windows:
                bounds = win.get("kCGWindowBounds")
                if not bounds:
                    continue
                x = int(bounds.get("X", 0))
                y = int(bounds.get("Y", 0))
                w = int(bounds.get("Width", 0))
                h = int(bounds.get("Height", 0))
                if x <= loc.x <= x + w and y <= loc.y <= y + h:
                    pid = int(win.get("kCGWindowOwnerPID", 0))
                    title = win.get("kCGWindowName")
                    return WindowInfo(pid, (x, y, w, h), title)
        except Exception:
            return WindowInfo(None)

    xdotool = shutil.which("xdotool")
    xprop = shutil.which("xprop")
    xwininfo = shutil.which("xwininfo")
    if not xdotool or not xprop or not xwininfo:
        return WindowInfo(None)
    try:
        info = subprocess.check_output(
            [xdotool, "getmouselocation", "--shell"], text=True
        )
        data = dict(line.split("=") for line in info.splitlines() if "=" in line)
        win = data.get("WINDOW")
        if not win:
            return WindowInfo(None)
        pid_line = subprocess.check_output(
            [xprop, "-id", win, "_NET_WM_PID"], text=True
        )
        match = re.search(r"= (\d+)", pid_line)
        pid = int(match.group(1)) if match else None
        geom = None
        title = None
        geom_out = subprocess.check_output([xwininfo, "-id", win], text=True)
        gx = re.search(r"Absolute upper-left X:\s+(\d+)", geom_out)
        gy = re.search(r"Absolute upper-left Y:\s+(\d+)", geom_out)
        gw = re.search(r"Width:\s+(\d+)", geom_out)
        gh = re.search(r"Height:\s+(\d+)", geom_out)
        if gx and gy and gw and gh:
            geom = (
                int(gx.group(1)),
                int(gy.group(1)),
                int(gw.group(1)),
                int(gh.group(1)),
            )
        title_out = subprocess.check_output([xprop, "-id", win, "WM_NAME"], text=True)
        title_match = re.search(r'"(.*)"', title_out)
        if title_match:
            title = title_match.group(1)
        return WindowInfo(pid, geom, title)
    except Exception:
        return WindowInfo(None)


def get_window_at(x: int, y: int) -> WindowInfo:
    """Return information about the window at ``(x, y)`` in screen coordinates."""

    if sys.platform.startswith("win"):
        pt = wintypes.POINT(x, y)
        hwnd = ctypes.windll.user32.WindowFromPoint(pt)
        if not hwnd:
            return WindowInfo(None)
        rect = wintypes.RECT()
        geom = None
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geom = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        return WindowInfo(int(pid.value) if pid.value else None, geom, title)

    if sys.platform == "darwin":
        try:
            import Quartz

            windows = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
            )
            for win in windows:
                bounds = win.get("kCGWindowBounds")
                if not bounds:
                    continue
                wx = int(bounds.get("X", 0))
                wy = int(bounds.get("Y", 0))
                ww = int(bounds.get("Width", 0))
                wh = int(bounds.get("Height", 0))
                if wx <= x <= wx + ww and wy <= y <= wy + wh:
                    pid = int(win.get("kCGWindowOwnerPID", 0))
                    title = win.get("kCGWindowName")
                    return WindowInfo(pid, (wx, wy, ww, wh), title)
        except Exception:
            return WindowInfo(None)

    # X11 fallback - coordinates ignored
    return get_window_under_cursor()


def list_windows_at(x: int, y: int) -> List[WindowInfo]:
    """Return windows at ``(x, y)`` ordered from front to back."""

    if sys.platform.startswith("win"):
        windows: List[WindowInfo] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd: wintypes.HWND, _lparam: wintypes.LPARAM) -> bool:
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            if not (rect.left <= x <= rect.right and rect.top <= y <= rect.bottom):
                return True
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title_buf = ctypes.create_unicode_buffer(1024)
            length = ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 1024)
            title = title_buf.value if length else None
            windows.append(
                WindowInfo(
                    int(pid.value) if pid.value else None,
                    (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                    title,
                )
            )
            return True

        ctypes.windll.user32.EnumWindows(enum_proc, 0)
        return windows

    if sys.platform == "darwin":
        try:
            import Quartz

            opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
            win_list = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
            results: List[WindowInfo] = []
            for win in win_list:
                bounds = win.get("kCGWindowBounds")
                if not bounds:
                    continue
                wx = int(bounds.get("X", 0))
                wy = int(bounds.get("Y", 0))
                ww = int(bounds.get("Width", 0))
                wh = int(bounds.get("Height", 0))
                if wx <= x <= wx + ww and wy <= y <= wy + wh:
                    pid = int(win.get("kCGWindowOwnerPID", 0))
                    title = win.get("kCGWindowName")
                    results.append(WindowInfo(pid, (wx, wy, ww, wh), title))
            return results
        except Exception:
            return [get_window_at(x, y)]

    # X11: attempt to use _NET_CLIENT_LIST_STACKING for z-order information
    try:
        stacking = subprocess.check_output(
            ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"], text=True
        )
        ids = [w.strip() for w in stacking.split("#", 1)[1].split()] if "#" in stacking else []
        results: List[WindowInfo] = []
        for wid in ids:
            geom_out = subprocess.check_output(["xwininfo", "-id", wid], text=True)
            gx = re.search(r"Absolute upper-left X:\s+(\d+)", geom_out)
            gy = re.search(r"Absolute upper-left Y:\s+(\d+)", geom_out)
            gw = re.search(r"Width:\s+(\d+)", geom_out)
            gh = re.search(r"Height:\s+(\d+)", geom_out)
            if not (gx and gy and gw and gh):
                continue
            wx = int(gx.group(1))
            wy = int(gy.group(1))
            ww = int(gw.group(1))
            wh = int(gh.group(1))
            if not (wx <= x <= wx + ww and wy <= y <= wy + wh):
                continue
            pid_line = subprocess.check_output(["xprop", "-id", wid, "_NET_WM_PID"], text=True)
            match = re.search(r"= (\d+)", pid_line)
            pid = int(match.group(1)) if match else None
            title_out = subprocess.check_output(["xprop", "-id", wid, "WM_NAME"], text=True)
            title_match = re.search(r'"(.*)"', title_out)
            title = title_match.group(1) if title_match else None
            results.append(WindowInfo(pid, (wx, wy, ww, wh), title))
        return results
    except Exception:
        pass

    info = get_window_at(x, y)
    return [info] if info.pid is not None else []


def make_window_clickthrough(win: Any) -> bool:
    """Attempt to make ``win`` ignore mouse events.

    Parameters
    ----------
    win:
        The tkinter window or any object with ``winfo_id`` and ``attributes``
        methods. Returns ``True`` if the platform supports click-through
        windows and the call succeeded.
    """

    try:
        if sys.platform.startswith("win"):
            hwnd = wintypes.HWND(int(win.winfo_id()))
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            WS_EX_NOACTIVATE = 0x08000000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            # make the window visually transparent using a color key so drawn
            # elements like the crosshair remain visible while the background
            # is invisible. fall back to opaque if color parsing fails.
            try:
                r, g, b = (c >> 8 for c in win.winfo_rgb(win.cget("bg")))
            except Exception:  # pragma: no cover - defensive
                r, g, b = 0, 0, 0
            colorref = b << 16 | g << 8 | r
            ctypes.windll.user32.SetLayeredWindowAttributes(
                hwnd, colorref, 255, 0x1
            )
            return True

        if sys.platform == "darwin":
            try:
                import objc
                from Cocoa import NSWindow

                ns_win = objc.objc_object(c_void_p=win.winfo_id())
                NSWindow(ns_win).setIgnoresMouseEvents_(True)
                return True
            except Exception:
                return False

        # X11: fall back to making the background fully transparent
        win.attributes("-transparentcolor", win.cget("bg"))
        win.update_idletasks()
        return True
    except Exception:
        return False


def remove_window_clickthrough(win: Any) -> bool:
    """Attempt to restore normal mouse interaction for ``win``.

    Parameters
    ----------
    win:
        The tkinter window or any object with ``winfo_id`` and ``attributes``
        methods.

    Returns
    -------
    bool
        ``True`` if the window was restored or no special handling was needed.
    """

    try:
        if sys.platform.startswith("win"):
            hwnd = wintypes.HWND(int(win.winfo_id()))
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            WS_EX_NOACTIVATE = 0x08000000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style &= ~(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            return True

        if sys.platform == "darwin":
            try:
                import objc
                from Cocoa import NSWindow

                ns_win = objc.objc_object(c_void_p=win.winfo_id())
                NSWindow(ns_win).setIgnoresMouseEvents_(False)
                return True
            except Exception:
                return False

        win.attributes("-transparentcolor", "")
        win.update_idletasks()
        return True
    except Exception:
        return False

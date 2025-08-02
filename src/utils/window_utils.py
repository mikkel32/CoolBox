from __future__ import annotations

"""Helpers for retrieving information about desktop windows."""

import ctypes
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from ctypes import wintypes
from typing import Any
from typing import List

try:  # pragma: no cover - optional dependency
    from Xlib import X, Xatom, display as xlib_display

    _X_DISPLAY = xlib_display.Display()
    _X_ROOT = _X_DISPLAY.screen().root
    _NET_CLIENT_LIST_STACKING = _X_DISPLAY.intern_atom("_NET_CLIENT_LIST_STACKING")
    _WM_PID = _X_DISPLAY.intern_atom("_NET_WM_PID")
    _WM_NAME = _X_DISPLAY.intern_atom("WM_NAME")
except Exception:  # noqa: F401
    _X_DISPLAY = None
    _X_ROOT = None
    _NET_CLIENT_LIST_STACKING = None
    _WM_PID = None
    _WM_NAME = None

# Cache populated by a background enumeration thread.  The cache is intentionally
# long lived so repeated overlay updates can reuse results without blocking.
_WINDOWS_CACHE: dict[str, Any] = {"time": 0.0, "windows": []}
_WINDOWS_CACHE_SEC = 10.0
_WINDOWS_LOCK = threading.RLock()
_WINDOWS_THREAD: threading.Thread | None = None
_WINDOWS_REFRESH = threading.Event()


@dataclass(frozen=True)
class WindowInfo:
    """Process ID, geometry and title for a window."""

    pid: int | None
    rect: tuple[int, int, int, int] | None = None
    title: str | None = None


_ACTIVE_WINDOW_CACHE: dict[str, Any] = {
    "time": 0.0,
    "info": WindowInfo(None),
}
_ACTIVE_WINDOW_CACHE_SEC = 0.3


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


def _get_active_window_uncached() -> WindowInfo:
    """Return information about the currently active window without caching."""
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


def get_active_window() -> WindowInfo:
    """Return information about the currently active window using a short cache."""
    now = time.monotonic()
    if now - _ACTIVE_WINDOW_CACHE["time"] < _ACTIVE_WINDOW_CACHE_SEC:
        return _ACTIVE_WINDOW_CACHE["info"]
    info = _get_active_window_uncached()
    _ACTIVE_WINDOW_CACHE["time"] = now
    _ACTIVE_WINDOW_CACHE["info"] = info
    return info


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

    if _X_DISPLAY is not None:
        try:
            pointer = _X_ROOT.query_pointer()
            wins = _fallback_list_windows_at(pointer.root_x, pointer.root_y)
            if wins:
                return wins[0]
        except Exception:
            pass

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

    wins = _fallback_list_windows_at(x, y)
    return wins[0] if wins else WindowInfo(None)


def _enumerate_x11_windows() -> List[WindowInfo]:
    """Enumerate windows using a persistent X11 connection."""

    windows: List[WindowInfo] = []
    try:
        root = _X_ROOT
        prop = root.get_full_property(_NET_CLIENT_LIST_STACKING, Xatom.WINDOW)
        ids = list(prop.value) if prop else []
        for wid in reversed(ids):  # front to back
            win = _X_DISPLAY.create_resource_object("window", wid)
            geom = win.get_geometry()
            abs_pos = win.translate_coords(root, 0, 0)
            wx, wy = abs_pos.x, abs_pos.y
            ww, wh = geom.width, geom.height
            pid_prop = win.get_full_property(_WM_PID, Xatom.CARDINAL)
            pid = int(pid_prop.value[0]) if pid_prop and pid_prop.value else None
            name_prop = win.get_full_property(_WM_NAME, X.AnyPropertyType)
            title = None
            if name_prop and name_prop.value:
                try:
                    title = name_prop.value.decode("utf-8", "ignore")
                except Exception:  # pragma: no cover - defensive
                    title = None
            windows.append(WindowInfo(pid, (wx, wy, ww, wh), title))
    except Exception:
        pass
    return windows


def _enumerate_subproc_windows() -> List[WindowInfo]:
    """Enumerate X11 windows via subprocess calls."""

    windows: List[WindowInfo] = []
    try:
        stacking = subprocess.check_output(
            ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"], text=True
        )
        ids = (
            [w.strip() for w in stacking.split("#", 1)[1].split()]
            if "#" in stacking
            else []
        )
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
            pid_line = subprocess.check_output(
                ["xprop", "-id", wid, "_NET_WM_PID"], text=True
            )
            match = re.search(r"= (\d+)", pid_line)
            pid = int(match.group(1)) if match else None
            title_out = subprocess.check_output(
                ["xprop", "-id", wid, "WM_NAME"], text=True
            )
            title_match = re.search(r'"(.*)"', title_out)
            title = title_match.group(1) if title_match else None
            windows.append(WindowInfo(pid, (wx, wy, ww, wh), title))
    except Exception:
        pass
    return windows


def _refresh_windows() -> List[WindowInfo]:
    """Return a full window list using the best available method."""

    if _X_DISPLAY is not None:
        return _enumerate_x11_windows()
    return _enumerate_subproc_windows()


def _window_enum_worker() -> None:
    """Worker thread that refreshes the window cache."""

    while True:
        _WINDOWS_REFRESH.wait()
        _WINDOWS_REFRESH.clear()
        windows = _refresh_windows()
        now = time.time()
        with _WINDOWS_LOCK:
            _WINDOWS_CACHE["time"] = now
            _WINDOWS_CACHE["windows"] = windows


def _ensure_window_worker() -> None:
    """Start the enumeration thread if needed."""

    global _WINDOWS_THREAD
    if _WINDOWS_THREAD is None or not _WINDOWS_THREAD.is_alive():
        _WINDOWS_THREAD = threading.Thread(target=_window_enum_worker, daemon=True)
        _WINDOWS_THREAD.start()


def prime_window_cache() -> None:
    """Ensure the window cache is populated asynchronously."""

    _ensure_window_worker()
    if not _WINDOWS_REFRESH.is_set():
        _WINDOWS_REFRESH.set()


def filter_windows_at(x: int, y: int, windows: List[WindowInfo]) -> List[WindowInfo]:
    """Return windows covering ``(x, y)`` from ``windows``.

    This helper performs only a simple bounds check and performs no I/O,
    making it safe to use from the UI thread.
    """

    results: List[WindowInfo] = []
    for win in windows:
        rect = win.rect
        if rect and rect[0] <= x <= rect[0] + rect[2] and rect[1] <= y <= rect[1] + rect[3]:
            results.append(win)
    return results


def _fallback_list_windows_at(
    x: int, y: int, windows: List[WindowInfo] | None = None
) -> List[WindowInfo]:
    """Return cached window enumeration results for ``(x, y)``.

    When ``windows`` is provided, it is used directly which makes the call
    non-blocking. Otherwise the function serves results from the shared cache
    and schedules a background refresh when the cache is stale.
    """

    _ensure_window_worker()
    if windows is None:
        now = time.time()
        with _WINDOWS_LOCK:
            last = _WINDOWS_CACHE.get("time", 0.0)
            windows = list(_WINDOWS_CACHE.get("windows", []))
        if (now - last >= _WINDOWS_CACHE_SEC or not windows) and not _WINDOWS_REFRESH.is_set():
            _WINDOWS_REFRESH.set()
    return filter_windows_at(x, y, windows)


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

    # X11 and other Unix-like systems
    return _fallback_list_windows_at(x, y)


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


def set_window_colorkey(win: Any) -> bool:
    """Set a transparent color key for ``win`` without changing event handling."""

    try:
        if sys.platform.startswith("win"):
            hwnd = wintypes.HWND(int(win.winfo_id()))
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            try:
                r, g, b = (c >> 8 for c in win.winfo_rgb(win.cget("bg")))
            except Exception:
                r, g, b = 0, 0, 0
            colorref = b << 16 | g << 8 | r
            ctypes.windll.user32.SetLayeredWindowAttributes(
                hwnd, colorref, 255, 0x1
            )
            return True

        if sys.platform == "darwin":
            try:
                import objc
                from Cocoa import NSWindow, NSColor

                ns_win = objc.objc_object(c_void_p=win.winfo_id())
                NSWindow(ns_win).setOpaque_(False)
                NSWindow(ns_win).setBackgroundColor_(NSColor.clearColor())
                return True
            except Exception:
                return False

        win.attributes("-transparentcolor", win.cget("bg"))
        win.update_idletasks()
        return True
    except Exception:
        return False

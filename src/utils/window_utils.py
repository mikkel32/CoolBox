from __future__ import annotations

"""Helpers for retrieving information about desktop windows."""

import ctypes
import logging
import os
import re
import shutil
import subprocess
import importlib
import sys
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass
from ctypes import wintypes
from typing import Any, List, Callable, TYPE_CHECKING, cast

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
    X = None  # type: ignore[assignment]
    Xatom = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing helpers
    from ctypes import LibraryLoader
else:  # pragma: no cover - runtime fallback when ctypes extensions missing
    LibraryLoader = Any

logger = logging.getLogger(__name__)

if sys.platform.startswith("win"):
    _CTYPES_WINDLL: LibraryLoader | None = cast(
        LibraryLoader | None, getattr(ctypes, "windll", None)
    )
    _CTYPES_WINFUNCTYPE: Callable[..., Any] | None = cast(
        Callable[..., Any] | None, getattr(ctypes, "WINFUNCTYPE", None)
    )
else:
    _CTYPES_WINDLL = None
    _CTYPES_WINFUNCTYPE = None

# Cache populated by a background enumeration thread.  The cache is intentionally
# long lived so repeated overlay updates can reuse results without blocking.
_WINDOWS_CACHE: dict[str, Any] = {"time": 0.0, "windows": []}
_WINDOWS_CACHE_SEC = 10.0
_WINDOWS_LOCK = threading.RLock()
_WINDOWS_THREAD: threading.Thread | None = None
_WINDOWS_REFRESH = threading.Event()
_WINDOWS_EVENT_UNSUB: Callable[[], None] | None = None
_WINDOWS_EVENTS_SUPPORTED = False

# Small ring buffer of recently accessed windows to reduce cold-cache hits
_RECENT_MAX = 8
_RECENT_WINDOWS: deque[WindowInfo] = deque()
_RECENT_LOCK = threading.RLock()


_MIN_WINDOW_WIDTH = 0
_MIN_WINDOW_HEIGHT = 0
_TRANSIENT_PIDS: set[int] = set()
_CFG_LOADED = False


def _get_windll() -> LibraryLoader | None:
    """Return the cached ``ctypes.windll`` loader when available."""

    if not sys.platform.startswith("win"):
        return None
    return _CTYPES_WINDLL


def _get_winfunctype() -> Callable[..., Any] | None:
    """Return ``ctypes.WINFUNCTYPE`` when present on this platform."""

    if not sys.platform.startswith("win"):
        return None
    return _CTYPES_WINFUNCTYPE


def _get_user32() -> Any | None:
    """Return the ``user32`` library when available."""

    windll = _get_windll()
    if windll is None:
        return None
    return getattr(windll, "user32", None)


def _get_kernel32() -> Any | None:
    """Return the ``kernel32`` library when available."""

    windll = _get_windll()
    if windll is None:
        return None
    return getattr(windll, "kernel32", None)


def _load_thresholds() -> None:
    """Load size thresholds from ``Config`` lazily to avoid import cycles."""

    global _CFG_LOADED, _MIN_WINDOW_WIDTH, _MIN_WINDOW_HEIGHT
    if _CFG_LOADED:
        return
    _CFG_LOADED = True
    try:  # pragma: no cover - defensive
        from src.config import Config

        cfg = Config()
        _MIN_WINDOW_WIDTH = int(cfg.get("window_min_width", 0) or 0)
        _MIN_WINDOW_HEIGHT = int(cfg.get("window_min_height", 0) or 0)
    except Exception:
        pass


def _close_window_handle(info: WindowInfo) -> None:
    """Release any OS resources held for ``info``."""

    if sys.platform.startswith("win") and info.icon:
        windll = _get_windll()
        if windll is None:
            return
        user32 = getattr(windll, "user32", None)
        if user32 is None:
            return
        try:
            cast(Any, user32).DestroyIcon(wintypes.HICON(int(info.icon)))
        except Exception:
            pass


def _remember_window(info: WindowInfo) -> None:
    """Add ``info`` to the recent ring buffer."""

    if info.handle is None:
        return
    with _RECENT_LOCK:
        for existing in list(_RECENT_WINDOWS):
            if existing.handle == info.handle:
                _RECENT_WINDOWS.remove(existing)
                _close_window_handle(existing)
                break
        _RECENT_WINDOWS.append(info)
        while len(_RECENT_WINDOWS) > _RECENT_MAX:
            old = _RECENT_WINDOWS.popleft()
            _close_window_handle(old)


def _cleanup_recent(active: set[int]) -> None:
    """Remove windows not present in ``active`` from the ring buffer."""

    with _RECENT_LOCK:
        for win in list(_RECENT_WINDOWS):
            if win.handle is not None and win.handle not in active:
                _RECENT_WINDOWS.remove(win)
                _close_window_handle(win)


def _get_window_icon(hwnd: wintypes.HWND) -> int | None:
    """Return a handle to ``hwnd``'s small icon if available."""

    if not sys.platform.startswith("win"):
        return None
    windll = _get_windll()
    if windll is None:
        return None
    user32 = getattr(windll, "user32", None)
    if user32 is None:
        return None
    user32 = cast(Any, user32)
    WM_GETICON = 0x007F
    ICON_SMALL2 = 2
    GCL_HICON = -14
    GCL_HICONSM = -34
    hicon = user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL2, 0)
    if not hicon:
        hicon = user32.GetClassLongW(hwnd, GCL_HICONSM)
    if not hicon:
        hicon = user32.GetClassLongW(hwnd, GCL_HICON)
    return int(hicon) if hicon else None


@dataclass(frozen=True)
class WindowInfo:
    """Process ID, geometry and metadata for a window."""

    pid: int | None
    rect: tuple[int, int, int, int] | None = None
    title: str | None = None
    handle: int | None = None
    icon: Any | None = None


_ACTIVE_WINDOW_CACHE: dict[str, Any] = {
    "time": 0.0,
    "info": WindowInfo(None),
}
_ACTIVE_WINDOW_CACHE_SEC = 0.3


_ACTIVE_SUBSCRIBERS: list[Callable[[WindowInfo], None]] = []
_ACTIVE_SUB_LOCK = threading.RLock()
_ACTIVE_THREAD: threading.Thread | None = None
_ACTIVE_STOP = threading.Event()
_POLL_INTERVAL = 0.5
_WIN_THREAD_ID: int | None = None


def has_active_window_support() -> bool:
    """Return ``True`` if active window detection should work on this system."""
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    return bool(shutil.which("xdotool") and shutil.which("xprop"))


def has_cursor_window_support(*, warn: bool = False) -> bool:
    """Return ``True`` if detecting the window under the cursor is supported."""
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        try:
            import Quartz  # noqa: F401
        except Exception as exc:
            logger.exception("Quartz import failed")
            if warn:
                warnings.warn(
                    f"Cursor window detection unavailable: {exc}",
                    RuntimeWarning,
                )
            return False
        return True
    if not os.environ.get("DISPLAY"):
        if warn:
            warnings.warn(
                "Cursor window detection unavailable: DISPLAY not set",
                RuntimeWarning,
            )
        return False
    return bool(
        shutil.which("xdotool") and shutil.which("xprop") and shutil.which("xwininfo")
    )


def _get_active_window_uncached() -> WindowInfo:
    """Return information about the currently active window without caching."""
    if sys.platform.startswith("win"):
        windll = _get_windll()
        if windll is None:
            return WindowInfo(None)
        user32 = getattr(windll, "user32", None)
        if user32 is None:
            return WindowInfo(None)
        user32 = cast(Any, user32)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo(None)
        rect = wintypes.RECT()
        geom = None
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geom = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        icon = _get_window_icon(hwnd)
        info = WindowInfo(
            int(pid.value) if pid.value else None,
            geom,
            title,
            int(hwnd),
            icon,
        )
        _remember_window(info)
        return info

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


def _dispatch_active(info: WindowInfo) -> None:
    with _ACTIVE_SUB_LOCK:
        callbacks = list(_ACTIVE_SUBSCRIBERS)
    for cb in callbacks:
        try:
            cb(info)
        except Exception:
            pass


def _win_active_thread() -> None:
    global _WIN_THREAD_ID
    user32 = _get_user32()
    kernel32 = _get_kernel32()
    if user32 is None or kernel32 is None:
        return
    user32 = cast(Any, user32)
    kernel32 = cast(Any, kernel32)

    winfunctype = _get_winfunctype()
    if winfunctype is None:
        return

    WinEventProc = winfunctype(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        wintypes.LONG,
        wintypes.LONG,
        wintypes.DWORD,
        wintypes.DWORD,
    )

    EVENT_SYSTEM_FOREGROUND = 0x0003
    WINEVENT_OUTOFCONTEXT = 0x0000

    def _info_from_hwnd(hwnd: wintypes.HWND) -> WindowInfo:
        rect = wintypes.RECT()
        geom = None
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geom = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        icon = _get_window_icon(hwnd)
        info = WindowInfo(
            int(pid.value) if pid.value else None,
            geom,
            title,
            int(hwnd),
            icon,
        )
        _remember_window(info)
        return info

    def _callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        if event == EVENT_SYSTEM_FOREGROUND:
            _dispatch_active(_info_from_hwnd(hwnd))

    proc = WinEventProc(_callback)
    hook = user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND,
        EVENT_SYSTEM_FOREGROUND,
        0,
        proc,
        0,
        0,
        WINEVENT_OUTOFCONTEXT,
    )
    _WIN_THREAD_ID = kernel32.GetCurrentThreadId()
    msg = wintypes.MSG()
    while not _ACTIVE_STOP.is_set() and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    if hook:
        user32.UnhookWinEvent(hook)


def _mac_active_thread() -> None:
    try:
        quartz_mod = importlib.import_module("Quartz")
    except Exception:
        logger.exception("Quartz import failed")
        return
    Quartz = cast(Any, quartz_mod)

    def _callback(proxy, type_, event, refcon):
        _dispatch_active(_get_active_window_uncached())
        return event

    mask = (
        Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved)
        | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
        | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
    )
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        mask,
        _callback,
        None,
    )
    if not tap:
        return
    run_loop = Quartz.CFRunLoopGetCurrent()
    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(run_loop, source, Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    while not _ACTIVE_STOP.is_set():
        Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.1, True)
    Quartz.CGEventTapEnable(tap, False)


def _poll_active_thread() -> None:
    last: int | None = None
    while not _ACTIVE_STOP.is_set():
        info = _get_active_window_uncached()
        if info.pid != last:
            last = info.pid
            _dispatch_active(info)
        time.sleep(_POLL_INTERVAL)


def _ensure_active_thread() -> None:
    global _ACTIVE_THREAD
    if _ACTIVE_THREAD is not None:
        return
    if sys.platform.startswith("win"):
        target = _win_active_thread
    elif sys.platform == "darwin":
        target = _mac_active_thread
    else:
        target = _poll_active_thread
    _ACTIVE_THREAD = threading.Thread(target=target, daemon=True)
    _ACTIVE_THREAD.start()


def subscribe_active_window(
    callback: Callable[[WindowInfo], None]
) -> Callable[[], None]:
    """Subscribe to foreground window changes."""

    with _ACTIVE_SUB_LOCK:
        _ACTIVE_SUBSCRIBERS.append(callback)
        _ensure_active_thread()

    def unsubscribe() -> None:
        with _ACTIVE_SUB_LOCK:
            try:
                _ACTIVE_SUBSCRIBERS.remove(callback)
            except ValueError:
                pass
            if not _ACTIVE_SUBSCRIBERS:
                _ACTIVE_STOP.set()
                if sys.platform.startswith("win") and _WIN_THREAD_ID is not None:
                    try:
                        user32 = _get_user32()
                        if user32 is not None:
                            cast(Any, user32).PostThreadMessageW(_WIN_THREAD_ID, 0x0012, 0, 0)
                    except Exception:
                        pass
                if _ACTIVE_THREAD is not None:
                    _ACTIVE_THREAD.join()
                _ACTIVE_STOP.clear()
                globals()["_ACTIVE_THREAD"] = None

    return unsubscribe


def subscribe_window_change(
    callback: Callable[[], None]
) -> Callable[[], None] | None:
    """Subscribe to global window change events.

    The callback is invoked whenever a top-level window is created, destroyed,
    moved or resized.  Returns an unsubscribe function or ``None`` when the
    current platform does not support such notifications.
    """

    if sys.platform.startswith("win"):
        try:
            user32 = _get_user32()
            winfunctype = _get_winfunctype()
            if user32 is None or winfunctype is None:
                return None
            user32 = cast(Any, user32)
            WINEVENT_OUTOFCONTEXT = 0x0000
            EVENT_MIN = 0x00000001
            EVENT_MAX = 0x7FFFFFFF

            WinEventProcType = winfunctype(
                None,
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.HWND,
                wintypes.LONG,
                wintypes.LONG,
                wintypes.DWORD,
                wintypes.DWORD,
            )

            stop = threading.Event()

            def _proc(hook, event, hwnd, obj, child, thread, time_ms):  # pragma: no cover - OS callback
                if hwnd and obj == 0:
                    try:
                        callback()
                    except Exception:
                        pass

            proc = WinEventProcType(_proc)
            hook = user32.SetWinEventHook(
                EVENT_MIN,
                EVENT_MAX,
                0,
                proc,
                0,
                0,
                WINEVENT_OUTOFCONTEXT,
            )
            if not hook:
                return None

            def _pump() -> None:
                msg = wintypes.MSG()
                while not stop.is_set():
                    while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                    time.sleep(0.1)
                user32.UnhookWinEvent(hook)

            thread = threading.Thread(target=_pump, daemon=True)
            thread.start()

            def unsubscribe() -> None:
                stop.set()
                thread.join()

            return unsubscribe
        except Exception:
            return None

    return None


def get_window_under_cursor() -> WindowInfo:
    """Return information about the window under the mouse cursor."""
    if sys.platform.startswith("win"):
        user32 = _get_user32()
        if user32 is None:
            return WindowInfo(None)
        user32 = cast(Any, user32)
        pt = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return WindowInfo(None)
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return WindowInfo(None)
        rect = wintypes.RECT()
        geom = None
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geom = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        icon = _get_window_icon(hwnd)
        info = WindowInfo(
            int(pid.value) if pid.value else None,
            geom,
            title,
            int(hwnd),
            icon,
        )
        _remember_window(info)
        return info

    if sys.platform == "darwin":
        try:
            quartz_mod = importlib.import_module("Quartz")
        except Exception:
            return WindowInfo(None)

        Quartz = cast(Any, quartz_mod)
        pid = None
        title = None
        handle = None
        x = y = w = h = 0
        found = False

        try:
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
                    handle = int(win.get("kCGWindowNumber", 0))
                    found = True
                    break
        except Exception:
            return WindowInfo(None)
        if not found:
            return WindowInfo(None)
        info = WindowInfo(pid, (x, y, w, h), title, handle)
        _remember_window(info)
        return info

    if _X_DISPLAY is not None and _X_ROOT is not None:
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
        data: dict[str, str] = {}
        for line in info.splitlines():
            try:
                key, value = line.split("=", 1)
            except ValueError:
                continue
            data[key] = value
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
        user32 = _get_user32()
        if user32 is None:
            return WindowInfo(None)
        user32 = cast(Any, user32)
        pt = wintypes.POINT(x, y)
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return WindowInfo(None)
        rect = wintypes.RECT()
        geom = None
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            geom = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        icon = _get_window_icon(hwnd)
        info = WindowInfo(
            int(pid.value) if pid.value else None,
            geom,
            title,
            int(hwnd),
            icon,
        )
        _remember_window(info)
        return info

    if sys.platform == "darwin":
        try:
            quartz_mod = importlib.import_module("Quartz")
        except Exception:
            return WindowInfo(None)

        Quartz = cast(Any, quartz_mod)
        pid = None
        title = None
        wx = wy = ww = wh = 0

        try:
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
                    break
        except Exception:
            return WindowInfo(None)
        if pid is None:
            return WindowInfo(None)
        return WindowInfo(pid, (wx, wy, ww, wh), title)

    wins = _fallback_list_windows_at(x, y)
    return wins[0] if wins else WindowInfo(None)


def _enumerate_win_windows() -> List[WindowInfo]:
    """Enumerate all top-level windows on Windows."""

    windows: List[WindowInfo] = []

    winfunctype = _get_winfunctype()
    user32 = _get_user32()
    if winfunctype is None or user32 is None:
        return windows
    user32 = cast(Any, user32)

    @winfunctype(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: wintypes.HWND, _lparam: wintypes.LPARAM) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(1024)
        length = user32.GetWindowTextW(hwnd, title_buf, 1024)
        title = title_buf.value if length else None
        icon = _get_window_icon(hwnd)
        info = WindowInfo(
            int(pid.value) if pid.value else None,
            (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
            title,
            int(hwnd),
            icon,
        )
        windows.append(info)
        return True

    user32.EnumWindows(enum_proc, 0)
    return windows


def _enumerate_x11_windows() -> List[WindowInfo]:
    """Enumerate windows using a persistent X11 connection."""

    windows: List[WindowInfo] = []
    if _X_DISPLAY is None or _X_ROOT is None or Xatom is None or X is None:
        return windows
    try:
        root = _X_ROOT
        if _NET_CLIENT_LIST_STACKING is None:
            return windows
        prop = root.get_full_property(_NET_CLIENT_LIST_STACKING, Xatom.WINDOW)
        ids = list(prop.value) if prop else []
        for wid in reversed(ids):  # front to back
            win = _X_DISPLAY.create_resource_object("window", wid)
            geom = win.get_geometry()
            abs_pos = win.translate_coords(root, 0, 0)
            wx, wy = abs_pos.x, abs_pos.y
            ww, wh = geom.width, geom.height
            if _WM_PID is None or _WM_NAME is None:
                pid_prop = None
                name_prop = None
            else:
                pid_prop = win.get_full_property(_WM_PID, Xatom.CARDINAL)
                name_prop = win.get_full_property(_WM_NAME, X.AnyPropertyType)
            pid = int(pid_prop.value[0]) if pid_prop and pid_prop.value else None
            title = None
            if name_prop and name_prop.value:
                try:
                    title = name_prop.value.decode("utf-8", "ignore")
                except Exception:  # pragma: no cover - defensive
                    title = None
            windows.append(
                WindowInfo(pid, (wx, wy, ww, wh), title, int(wid))
            )
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
            handle = int(wid, 16) if wid.startswith("0x") else int(wid)
            windows.append(WindowInfo(pid, (wx, wy, ww, wh), title, handle))
    except Exception:
        pass
    return windows


def _refresh_windows() -> List[WindowInfo]:
    """Return a full window list using the best available method."""
    if sys.platform.startswith("win"):
        return _enumerate_win_windows()
    if _X_DISPLAY is not None and _X_ROOT is not None and Xatom is not None and X is not None:
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
        active_handles = {w.handle for w in windows if w.handle is not None}
        _cleanup_recent(active_handles)
        for w in windows:
            _remember_window(w)


def _ensure_window_worker() -> None:
    """Start the enumeration thread and subscribe to change events."""

    global _WINDOWS_THREAD, _WINDOWS_EVENT_UNSUB, _WINDOWS_EVENTS_SUPPORTED
    if _WINDOWS_THREAD is None or not _WINDOWS_THREAD.is_alive():
        _WINDOWS_THREAD = threading.Thread(target=_window_enum_worker, daemon=True)
        _WINDOWS_THREAD.start()
    if _WINDOWS_EVENT_UNSUB is None:
        unsub = subscribe_window_change(lambda: _WINDOWS_REFRESH.set())
        if unsub is not None:
            _WINDOWS_EVENT_UNSUB = unsub
            _WINDOWS_EVENTS_SUPPORTED = True


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
    _load_thresholds()
    results: List[WindowInfo] = []
    for win in windows:
        rect = win.rect
        if not rect:
            continue
        if rect[2] < _MIN_WINDOW_WIDTH or rect[3] < _MIN_WINDOW_HEIGHT:
            if win.pid is not None:
                _TRANSIENT_PIDS.add(win.pid)
            continue
        title = (win.title or "").lower()
        if "tooltip" in title or "menu" in title:
            if win.pid is not None:
                _TRANSIENT_PIDS.add(win.pid)
            continue
        if rect[0] <= x <= rect[0] + rect[2] and rect[1] <= y <= rect[1] + rect[3]:
            results.append(win)
    return results


def is_transient_pid(pid: int | None) -> bool:
    """Return ``True`` if *pid* was marked as transient."""

    return pid is not None and pid in _TRANSIENT_PIDS


def _fallback_list_windows_at(
    x: int, y: int, windows: List[WindowInfo] | None = None
) -> List[WindowInfo]:
    """Return cached window enumeration results for ``(x, y)``.

    When ``windows`` is provided, it is used directly which makes the call
    non-blocking. Otherwise the function serves results from the shared cache
    and schedules a background refresh when the cache is stale.
    """

    _ensure_window_worker()
    with _RECENT_LOCK:
        recent = list(_RECENT_WINDOWS)
    hits = filter_windows_at(x, y, recent)
    if hits:
        return hits
    if windows is None:
        now = time.time()
        with _WINDOWS_LOCK:
            last = _WINDOWS_CACHE.get("time", 0.0)
            windows = list(_WINDOWS_CACHE.get("windows", []))
        should_refresh = not windows
        if not _WINDOWS_EVENTS_SUPPORTED:
            should_refresh |= now - last >= _WINDOWS_CACHE_SEC
        if should_refresh and not _WINDOWS_REFRESH.is_set():
            _WINDOWS_REFRESH.set()
    result = filter_windows_at(x, y, windows)
    for w in result:
        _remember_window(w)
    return result


def list_windows_at(x: int, y: int, depth: int | None = None) -> List[WindowInfo]:
    """Return up to ``depth`` windows at ``(x, y)`` from front to back.

    When ``depth`` is ``1`` the function avoids the cached enumeration and
    uses :func:`get_window_at` for a fast lookup.  When ``depth`` is ``None``
    or greater than ``1`` the stacked windows are collected from the shared
    cache.  On Windows the top window is always resolved with
    ``WindowFromPoint`` to ensure accurate z-ordering.
    """

    if depth == 1:
        info = get_window_at(x, y)
        return [info] if info.pid is not None or info.handle is not None else []

    stack = _fallback_list_windows_at(x, y)
    if sys.platform.startswith("win"):
        top = get_window_at(x, y)
        if top.handle is not None:
            stack = [top] + [w for w in stack if w.handle != top.handle]
    if depth is not None:
        stack = stack[:depth]
    return stack


def make_window_clickthrough(win: Any, *, warn: bool = False) -> bool:
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
            user32 = _get_user32()
            if user32 is None:
                return False
            user32 = cast(Any, user32)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            # make the window visually transparent using a color key so drawn
            # elements like the crosshair remain visible while the background
            # is invisible. fall back to opaque if color parsing fails.
            try:
                r, g, b = (c >> 8 for c in win.winfo_rgb(win.cget("bg")))
            except Exception:  # pragma: no cover - defensive
                r, g, b = 0, 0, 0
            colorref = b << 16 | g << 8 | r
            user32.SetLayeredWindowAttributes(
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
            except Exception as exc:
                logger.exception("macOS clickthrough failed")
                if warn:
                    warnings.warn(
                        f"Click-through unsupported: {exc}",
                        RuntimeWarning,
                    )
                return False

        # X11: fall back to making the background fully transparent
        win.attributes("-transparentcolor", win.cget("bg"))
        win.update_idletasks()
        return True
    except Exception as exc:
        logger.exception("clickthrough setup failed")
        if warn:
            warnings.warn(
                f"Click-through setup failed: {exc}",
                RuntimeWarning,
            )
        return False


def remove_window_clickthrough(win: Any, *, warn: bool = False) -> bool:
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
            user32 = _get_user32()
            if user32 is None:
                return False
            user32 = cast(Any, user32)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style &= ~(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            return True

        if sys.platform == "darwin":
            try:
                import objc
                from Cocoa import NSWindow

                ns_win = objc.objc_object(c_void_p=win.winfo_id())
                NSWindow(ns_win).setIgnoresMouseEvents_(False)
                return True
            except Exception as exc:
                logger.exception("macOS clickthrough restore failed")
                if warn:
                    warnings.warn(
                        f"Restore click-through failed: {exc}",
                        RuntimeWarning,
                    )
                return False

        win.attributes("-transparentcolor", "")
        win.update_idletasks()
        return True
    except Exception as exc:
        logger.exception("clickthrough restore failed")
        if warn:
            warnings.warn(
                f"Click-through restore failed: {exc}",
                RuntimeWarning,
            )
        return False


def set_window_colorkey(win: Any, *, warn: bool = False) -> bool:
    """Set a transparent color key for ``win`` without changing event handling."""

    try:
        if sys.platform.startswith("win"):
            hwnd = wintypes.HWND(int(win.winfo_id()))
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            user32 = _get_user32()
            if user32 is None:
                return False
            user32 = cast(Any, user32)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            try:
                r, g, b = (c >> 8 for c in win.winfo_rgb(win.cget("bg")))
            except Exception:
                r, g, b = 0, 0, 0
            colorref = b << 16 | g << 8 | r
            user32.SetLayeredWindowAttributes(
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
            except Exception as exc:
                logger.exception("macOS colorkey failed")
                if warn:
                    warnings.warn(
                        f"Color key unsupported: {exc}",
                        RuntimeWarning,
                    )
                return False

        win.attributes("-transparentcolor", win.cget("bg"))
        win.update_idletasks()
        return True
    except Exception as exc:
        logger.exception("colorkey setup failed")
        if warn:
            warnings.warn(
                f"Color key setup failed: {exc}",
                RuntimeWarning,
            )
        return False

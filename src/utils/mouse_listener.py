"""Cross-platform global mouse and keyboard listener utilities.

This module prefers native OS hooks to keep latency low and to avoid the
additional dependency on ``pynput`` when possible.  On Windows a low level
mouse and keyboard hook is installed via ``SetWindowsHookEx`` using the
``WH_MOUSE_LL`` and ``WH_KEYBOARD_LL`` hook types.  macOS relies on a
``CGEventTap`` registered at the ``kCGHIDEventTap`` level.  Other platforms
fall back to ``pynput`` which provides a reasonable implementation for X11
environments.

Events are filtered in the hook callback so only the minimal information is
dispatched to higher layers.  For example only left button events are emitted
for clicks and only key down events are propagated for the keyboard hook.
"""

from __future__ import annotations

import atexit
import sys
import threading
from contextlib import contextmanager
from typing import Callable, Optional

from .helpers import log

_JOIN_TIMEOUT = 0.2  # seconds

# -- Optional dependencies -------------------------------------------------

try:  # pragma: no cover - optional dependency may be missing
    from pynput import mouse, keyboard
except Exception:  # pragma: no cover - dependency not installed
    mouse = None  # type: ignore
    keyboard = None  # type: ignore


# -- Platform specific hook implementations --------------------------------

if sys.platform.startswith("win"):
    import ctypes
    from ctypes import wintypes

    WH_MOUSE_LL = 14
    WH_KEYBOARD_LL = 13
    WM_MOUSEMOVE = 0x0200
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    LowLevelMouseProc = ctypes.WINFUNCTYPE(
        wintypes.LPARAM, wintypes.INT, wintypes.WPARAM, wintypes.LPARAM
    )
    LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        wintypes.LPARAM, wintypes.INT, wintypes.WPARAM, wintypes.LPARAM
    )

    class _WinHook(threading.Thread):
        def __init__(
            self,
            on_move: Callable[[int, int], None] | None,
            on_click: Callable[[int, int, bool], None] | None,
            on_key: Callable[[int, bool], None] | None,
        ) -> None:
            super().__init__(daemon=True)
            self.on_move = on_move
            self.on_click = on_click
            self.on_key = on_key
            self._stop = threading.Event()
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32
            self._mouse_hook = None
            self._key_hook = None

        def run(self) -> None:  # pragma: no cover - platform specific
            def mouse_proc(nCode, wParam, lParam):
                if nCode == 0 and lParam and (self.on_move or self.on_click):
                    info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    if wParam == WM_MOUSEMOVE and self.on_move:
                        self.on_move(info.pt.x, info.pt.y)
                    elif wParam in (WM_LBUTTONDOWN, WM_LBUTTONUP) and self.on_click:
                        self.on_click(info.pt.x, info.pt.y, wParam == WM_LBUTTONDOWN)
                return self._user32.CallNextHookEx(None, nCode, wParam, lParam)

            def keyboard_proc(nCode, wParam, lParam):
                if (
                    nCode == 0
                    and lParam
                    and self.on_key
                    and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                ):
                    info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    self.on_key(info.vkCode, True)
                return self._user32.CallNextHookEx(None, nCode, wParam, lParam)

            self._mouse_proc = LowLevelMouseProc(mouse_proc)
            self._key_proc = LowLevelKeyboardProc(keyboard_proc)

            if self.on_move or self.on_click:
                self._mouse_hook = self._user32.SetWindowsHookExW(
                    WH_MOUSE_LL,
                    self._mouse_proc,
                    self._kernel32.GetModuleHandleW(None),
                    0,
                )

            if self.on_key:
                self._key_hook = self._user32.SetWindowsHookExW(
                    WH_KEYBOARD_LL,
                    self._key_proc,
                    self._kernel32.GetModuleHandleW(None),
                    0,
                )

            msg = wintypes.MSG()
            while not self._stop.is_set() and self._user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))

            if self._mouse_hook:
                self._user32.UnhookWindowsHookEx(self._mouse_hook)
            if self._key_hook:
                self._user32.UnhookWindowsHookEx(self._key_hook)

        def stop(self) -> None:  # pragma: no cover - platform specific
            self._stop.set()
            if self._user32 is not None:
                self._user32.PostThreadMessageW(self.ident, 0x0012, 0, 0)  # WM_QUIT

elif sys.platform == "darwin":
    try:  # pragma: no cover - optional dependency may be missing
        import Quartz
    except Exception:  # pragma: no cover - dependency not installed
        Quartz = None  # type: ignore

    class _MacHook(threading.Thread):
        def __init__(
            self,
            on_move: Callable[[int, int], None] | None,
            on_click: Callable[[int, int, bool], None] | None,
            on_key: Callable[[int, bool], None] | None,
        ) -> None:
            super().__init__(daemon=True)
            self.on_move = on_move
            self.on_click = on_click
            self.on_key = on_key
            self._stop = threading.Event()

        def run(self) -> None:  # pragma: no cover - platform specific
            if Quartz is None:
                return

            def _callback(proxy, type_, event, refcon):
                if type_ == Quartz.kCGEventMouseMoved and self.on_move:
                    loc = Quartz.CGEventGetLocation(event)
                    self.on_move(int(loc.x), int(loc.y))
                elif type_ in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp) and self.on_click:
                    loc = Quartz.CGEventGetLocation(event)
                    self.on_click(int(loc.x), int(loc.y), type_ == Quartz.kCGEventLeftMouseDown)
                elif type_ == Quartz.kCGEventKeyDown and self.on_key:
                    keycode = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode
                    )
                    self.on_key(int(keycode), True)
                return event

            mask = 0
            if self.on_move or self.on_click:
                mask |= Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved)
                mask |= Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
                mask |= Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseUp)
            if self.on_key:
                mask |= Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)

            tap = Quartz.CGEventTapCreate(
                Quartz.kCGHIDEventTap,
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
            while not self._stop.is_set():
                Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.1, True)
            Quartz.CGEventTapEnable(tap, False)

        def stop(self) -> None:  # pragma: no cover - platform specific
            self._stop.set()

else:
    _WinHook = None  # type: ignore
    _MacHook = None  # type: ignore


# -- Public listener wrapper ------------------------------------------------

def is_supported() -> bool:
    """Return ``True`` if a global listener can be started."""

    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        return Quartz is not None
    return mouse is not None or keyboard is not None


class GlobalMouseListener:
    """Manage global mouse and keyboard hooks."""

    def __init__(self) -> None:
        self._listener: Optional[threading.Thread] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._move_cb: Optional[Callable[[int, int], None]] = None
        self._click_cb: Optional[Callable[[int, int, bool], None]] = None
        self._key_cb: Optional[Callable[[int, bool], None]] = None
        self._ref_count = 0

    # -- Fallback wrappers -------------------------------------------------
    def _wrap_move(self, cb: Callable[[int, int], None] | None):
        if cb is None:
            return None

        def _on_move(x: int, y: int) -> None:
            try:
                cb(x, y)
            except Exception as e:
                log(f"move callback error: {e}")

        return _on_move

    def _wrap_click(self, cb: Callable[[int, int, bool], None] | None):
        if cb is None:
            return None

        def _on_click(x: int, y: int, button, pressed: bool) -> None:
            try:
                if button == getattr(mouse, "Button", object()).left:
                    cb(x, y, pressed)
            except Exception as e:
                log(f"click callback error: {e}")

        return _on_click

    def _wrap_key(self, cb: Callable[[int, bool], None] | None):
        if cb is None:
            return None

        def _on_press(key) -> None:
            try:
                cb(getattr(key, "vk", getattr(getattr(key, "value", key), "vk", 0)), True)
            except Exception as e:
                log(f"key callback error: {e}")

        return _on_press

    # ------------------------------------------------------------------

    def start(
        self,
        on_move: Callable[[int, int], None] | None = None,
        on_click: Callable[[int, int, bool], None] | None = None,
        on_key: Callable[[int, bool], None] | None = None,
    ) -> bool:
        """Start or update the underlying listener if possible."""

        self._move_cb = on_move
        self._click_cb = on_click
        self._key_cb = on_key

        # Native hooks
        if sys.platform.startswith("win"):
            if self._listener is None or not self._listener.is_alive():
                self._listener = _WinHook(on_move, on_click, on_key)
                self._listener.start()
            else:
                self._listener.on_move = on_move
                self._listener.on_click = on_click
                self._listener.on_key = on_key
            return True

        if sys.platform == "darwin" and _MacHook is not None:
            if self._listener is None or not self._listener.is_alive():
                self._listener = _MacHook(on_move, on_click, on_key)
                self._listener.start()
            else:
                self._listener.on_move = on_move
                self._listener.on_click = on_click
                self._listener.on_key = on_key
            return True

        # Fallback to pynput
        started = False
        if mouse is not None:
            move_cb = self._wrap_move(on_move)
            click_cb = self._wrap_click(on_click)
            if self._mouse_listener is None or not self._mouse_listener.is_alive():
                self._mouse_listener = mouse.Listener(
                    on_move=move_cb, on_click=click_cb
                )
                try:
                    self._mouse_listener.start()
                    started = True
                except Exception:  # pragma: no cover - start failures are rare
                    self._mouse_listener = None
            else:
                self._mouse_listener.on_move = move_cb
                self._mouse_listener.on_click = click_cb
                started = True

        if keyboard is not None and (on_key or self._keyboard_listener is not None):
            key_cb = self._wrap_key(on_key)
            if self._keyboard_listener is None or not self._keyboard_listener.is_alive():
                self._keyboard_listener = keyboard.Listener(on_press=key_cb)
                try:
                    self._keyboard_listener.start()
                    started = True
                except Exception:  # pragma: no cover - start failures are rare
                    self._keyboard_listener = None
            else:
                self._keyboard_listener.on_press = key_cb
                started = True

        running = (
            started
            or self._listener is not None
            or self._mouse_listener is not None
            or self._keyboard_listener is not None
        )
        if running:
            self._ref_count += 1
        return running

    def _stop_listeners(self) -> None:
        if self._listener is not None and isinstance(self._listener, threading.Thread):
            stop = getattr(self._listener, "stop", None)
            if stop is not None:
                try:
                    stop()
                except Exception:  # pragma: no cover - defensive
                    pass
            self._listener = None

        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
                self._mouse_listener.join(timeout=_JOIN_TIMEOUT)
                if getattr(self._mouse_listener, "is_alive", lambda: False)():
                    log(
                        f"mouse listener thread failed to stop within {_JOIN_TIMEOUT}s"
                    )
            except Exception:  # pragma: no cover - defensive
                pass
            finally:
                self._mouse_listener = None

        if self._keyboard_listener is not None:
            try:
                self._keyboard_listener.stop()
                self._keyboard_listener.join(timeout=_JOIN_TIMEOUT)
                if getattr(self._keyboard_listener, "is_alive", lambda: False)():
                    log(
                        f"keyboard listener thread failed to stop within {_JOIN_TIMEOUT}s"
                    )
            except Exception:  # pragma: no cover - defensive
                pass
            finally:
                self._keyboard_listener = None

    def stop(self, force: bool = False) -> None:
        if self._ref_count > 0:
            self._ref_count -= 1
        if self._ref_count == 0 or force:
            self._ref_count = 0
            self._stop_listeners()

    def release(self) -> None:
        self.stop()


@contextmanager
def capture_mouse(
    on_move: Callable[[int, int], None] | None = None,
    on_click: Callable[[int, int, bool], None] | None = None,
    on_key: Callable[[int, bool], None] | None = None,
) -> "GlobalMouseListener":
    """Context manager to start a global mouse/keyboard listener."""

    listener = GlobalMouseListener()
    started = listener.start(on_move=on_move, on_click=on_click, on_key=on_key)
    try:
        yield listener if started else None
    finally:
        if started:
            listener.release()


_GLOBAL_LISTENER = GlobalMouseListener()


def get_global_listener() -> GlobalMouseListener:
    """Return the shared global listener instance."""

    return _GLOBAL_LISTENER


atexit.register(_GLOBAL_LISTENER.stop, True)

"""Cross-platform global mouse listener utilities."""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Callable, Optional

try:
    from pynput import mouse
except Exception:  # pragma: no cover - optional dependency may be missing
    mouse = None


def is_supported() -> bool:
    """Return ``True`` if a global mouse listener can be started."""

    return mouse is not None


class GlobalMouseListener:
    """Lightweight wrapper around ``pynput.mouse.Listener``."""

    def __init__(self) -> None:
        self._listener: Optional[mouse.Listener] = None
        self._move_cb: Optional[Callable[[int, int], None]] = None
        self._click_cb: Optional[Callable[[int, int, bool], None]] = None

    def _wrap_move(self, cb: Callable[[int, int], None] | None):
        if cb is None or mouse is None:
            return None

        def _on_move(x: int, y: int) -> None:
            try:
                cb(x, y)
            except Exception:
                pass

        return _on_move

    def _wrap_click(self, cb: Callable[[int, int, bool], None] | None):
        if cb is None or mouse is None:
            return None

        def _on_click(x: int, y: int, button: mouse.Button, pressed: bool) -> None:
            try:
                if button == mouse.Button.left:
                    cb(x, y, pressed)
            except Exception:
                pass

        return _on_click

    def start(
        self,
        on_move: Callable[[int, int], None] | None = None,
        on_click: Callable[[int, int, bool], None] | None = None,
    ) -> bool:
        """Start or update the underlying listener if possible.

        Returns
        -------
        bool
            ``True`` if the listener is running.
        """
        if mouse is None:
            return False

        self._move_cb = self._wrap_move(on_move)
        self._click_cb = self._wrap_click(on_click)

        if self._listener is None or not self._listener.is_alive():
            self._listener = mouse.Listener(
                on_move=self._move_cb,
                on_click=self._click_cb,
            )
            try:
                self._listener.start()
            except Exception:  # pragma: no cover - start failures are rare
                self._listener = None
                return False
        else:
            self._listener.on_move = self._move_cb
            self._listener.on_click = self._click_cb
        return True

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
                self._listener.join()
            except Exception:  # pragma: no cover - defensive
                pass
            finally:
                self._listener = None
                self._move_cb = None
                self._click_cb = None


@contextmanager
def capture_mouse(
    on_move: Callable[[int, int], None] | None = None,
    on_click: Callable[[int, int, bool], None] | None = None,
) -> "GlobalMouseListener":
    """Context manager to start a global mouse listener."""

    listener = GlobalMouseListener()
    started = listener.start(on_move=on_move, on_click=on_click)
    try:
        yield listener if started else None
    finally:
        if started:
            listener.stop()


_GLOBAL_LISTENER = GlobalMouseListener()


def get_global_listener() -> GlobalMouseListener:
    """Return the shared global mouse listener instance."""

    return _GLOBAL_LISTENER


atexit.register(_GLOBAL_LISTENER.stop)


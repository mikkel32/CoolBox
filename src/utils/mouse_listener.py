"""Cross-platform global mouse listener utilities."""

from __future__ import annotations

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

    def __init__(
        self,
        on_move: Callable[[int, int], None] | None = None,
        on_click: Callable[[int, int, bool], None] | None = None,
    ) -> None:
        self._listener: Optional[mouse.Listener] = None if mouse is None else mouse.Listener(
            on_move=self._wrap_move(on_move),
            on_click=self._wrap_click(on_click),
        )

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

    def start(self) -> bool:
        """Start the underlying listener if possible.

        Returns
        -------
        bool
            ``True`` if the listener started successfully.
        """
        if self._listener is None:
            return False
        try:
            self._listener.start()
            return True
        except Exception:  # pragma: no cover - start failures are rare
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
                self._listener.join()
            except Exception:  # pragma: no cover - defensive
                pass


@contextmanager
def capture_mouse(
    on_move: Callable[[int, int], None] | None = None,
    on_click: Callable[[int, int, bool], None] | None = None,
) -> "GlobalMouseListener":
    """Context manager to start a global mouse listener."""

    listener = GlobalMouseListener(on_move=on_move, on_click=on_click)
    started = listener.start()
    try:
        yield listener if started else None
    finally:
        if started:
            listener.stop()

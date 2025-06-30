from __future__ import annotations

"""Overlay for selecting a window by clicking it.

The overlay uses global mouse hooks when available so it can remain fully
transparent to input without stealing focus. When hooks aren't supported it
falls back to regular event bindings and temporarily disables mouse capture
while polling the underlying window.
"""

import os
import tkinter as tk
from typing import Optional

from src.utils.window_utils import (
    get_active_window,
    get_window_at,
    make_window_clickthrough,
    remove_window_clickthrough,
    WindowInfo,
)
from src.utils.mouse_listener import capture_mouse, is_supported

# Polling delay used when global hooks aren't available
KILL_BY_CLICK_INTERVAL = float(os.getenv("KILL_BY_CLICK_INTERVAL", "0.03"))


class ClickOverlay(tk.Toplevel):
    """Fullscreen transparent window used to select another window.

    Parameters
    ----------
    parent:
        The parent ``tk`` widget owning the overlay.
    highlight:
        Color used for the selection rectangle and crosshair lines.
    probe_attempts:
        Number of times to retry window detection when the cursor is over one
        of this process's windows.
    timeout:
        Automatically close the overlay after this many seconds if provided.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        highlight: str = "red",
        probe_attempts: int = 5,
        timeout: float | None = None,
        interval: float = KILL_BY_CLICK_INTERVAL,
    ) -> None:
        super().__init__(parent)
        # Configure fullscreen before enabling override-redirect to avoid
        # "can't set fullscreen attribute" errors on some platforms.
        self.attributes("-topmost", True)
        self.attributes("-fullscreen", True)
        self.overrideredirect(True)
        self.configure(cursor="crosshair")

        # use a unique background color that can be made transparent. this is
        # applied before enabling click-through so the color key matches the
        # actual background when ``make_window_clickthrough`` is called.
        bg_color = (
            parent.cget("bg") if isinstance(parent, tk.Widget) else "#000001"
        )
        self.configure(bg=bg_color)

        self._clickthrough = False
        if is_supported():
            self._clickthrough = make_window_clickthrough(self)

        # Using an empty string for the canvas background causes a TclError on
        # some platforms. Use the chosen background color so the canvas itself
        # becomes transparent via the color key.
        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.rect = self.canvas.create_rectangle(0, 0, 1, 1, outline=highlight, width=2)
        # crosshair lines spanning the entire screen for precise selection
        self.hline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
        self.vline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
        self.label = self.canvas.create_text(
            0,
            0,
            anchor="nw",
            fill=highlight,
            text="",
            font=("TkDefaultFont", 10, "bold"),
        )
        self.probe_attempts = probe_attempts
        self.timeout = timeout
        self.interval = interval
        self._after_id: Optional[str] = None
        self._timeout_id: Optional[str] = None
        self._update_pending = False
        self._using_hooks = False
        self.pid: int | None = None
        self.title_text: str | None = None
        self._own_pid = os.getpid()
        try:
            self._cursor_x = self.winfo_pointerx()
            self._cursor_y = self.winfo_pointery()
        except Exception:
            self._cursor_x = 0
            self._cursor_y = 0

    def _position_label(self, px: int, py: int, sw: int, sh: int) -> None:
        """Place the info label near the cursor while keeping it on-screen."""
        x = px + 10
        y = py + 10
        bbox = self.canvas.bbox(self.label)
        if bbox:
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            if x + width > sw:
                x = px - width - 10
            if y + height > sh:
                y = py - height - 10
        self.canvas.coords(self.label, x, y)

    def _queue_update(self, _e: object | None = None) -> None:
        """Schedule an overlay update in the main thread."""
        if isinstance(_e, tk.Event):
            self._cursor_x = _e.x_root
            self._cursor_y = _e.y_root
        if not self._update_pending:
            self._update_pending = True
            self.after_idle(self._process_update)

    def _process_update(self) -> None:
        self._update_pending = False
        self._update_rect()
        if not self._using_hooks:
            self._after_id = self.after(
                int(self.interval * 1000), self._queue_update
            )

    def _on_move(self, x: int, y: int) -> None:
        self._cursor_x = x
        self._cursor_y = y
        self._queue_update()

    def _query_window(self) -> WindowInfo:
        """Return the window info below the cursor, ignoring this overlay."""
        info = get_window_at(int(self._cursor_x), int(self._cursor_y))
        if self._clickthrough:
            for _ in range(self.probe_attempts):
                if info.pid not in (self._own_pid, None):
                    break
                info = get_window_at(int(self._cursor_x), int(self._cursor_y))
        else:
            was_click = make_window_clickthrough(self)
            try:
                for _ in range(self.probe_attempts):
                    if info.pid not in (self._own_pid, None):
                        break
                    info = get_window_at(int(self._cursor_x), int(self._cursor_y))
            finally:
                if was_click:
                    remove_window_clickthrough(self)
        if info.pid is None:
            info = get_active_window()
        return info

    def _update_rect(self, info: WindowInfo | None = None) -> None:
        if info is None:
            info = self._query_window()
        if not getattr(self, "_raised", False):
            self.lift()
            self._raised = True
        self.pid = info.pid
        self.title_text = info.title

        px = int(self._cursor_x)
        py = int(self._cursor_y)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Draw crosshair lines centered on the cursor only when moved
        if not hasattr(self, "_last_pos") or self._last_pos != (px, py, sw, sh):
            self.canvas.coords(self.hline, 0, py, sw, py)
            self.canvas.coords(self.vline, px, 0, px, sh)
            self._last_pos = (px, py, sw, sh)

        if info.rect:
            rect = (
                info.rect[0],
                info.rect[1],
                info.rect[0] + info.rect[2],
                info.rect[1] + info.rect[3],
            )
        else:
            rect = (-5, -5, -5, -5)
        if rect != getattr(self, "_last_rect", None):
            self.canvas.coords(self.rect, *rect)
            self._last_rect = rect
        text = info.title or ("PID " + str(info.pid) if info.pid else "")
        if text != getattr(self, "_last_text", None):
            self.canvas.itemconfigure(self.label, text=text)
            self._last_text = text
        self._position_label(px, py, sw, sh)

    def _on_click(self) -> None:
        info: WindowInfo = self._query_window()
        self.pid = info.pid
        self.title_text = info.title
        self.close()

    def _click(self, x: int, y: int, pressed: bool) -> None:
        if pressed:
            self._cursor_x = x
            self._cursor_y = y
            self.after(0, self._on_click)

    def _click_event(self, e: tk.Event) -> None:
        self._cursor_x = e.x_root
        self._cursor_y = e.y_root
        self.after(0, self._on_click)

    def close(self, _e: object | None = None) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._timeout_id is not None:
            try:
                self.after_cancel(self._timeout_id)
            except Exception:
                pass
            self._timeout_id = None
        if self._clickthrough:
            remove_window_clickthrough(self)
        self.destroy()

    def choose(self) -> tuple[int | None, str | None]:
        """Show the overlay and return the PID and title of the clicked window."""
        self.bind("<Escape>", self.close)
        self.protocol("WM_DELETE_WINDOW", self.close)
        use_hooks = self._clickthrough and is_supported()
        if use_hooks:
            with capture_mouse(
                on_move=self._on_move,
                on_click=self._click,
            ) as listener:
                if listener is None:
                    use_hooks = False
                    if self._clickthrough:
                        remove_window_clickthrough(self)
                        self._clickthrough = False
                else:
                    self._using_hooks = True
                    self._queue_update()
                    if self.timeout is not None:
                        self._timeout_id = self.after(int(self.timeout * 1000), self.close)
                    self.wait_window()
                    return self.pid, self.title_text

        self._using_hooks = False
        self.bind("<Motion>", self._queue_update)
        self.bind("<Button-1>", self._click_event)
        self._queue_update()
        if self.timeout is not None:
            self._timeout_id = self.after(int(self.timeout * 1000), self.close)
        self.wait_window()
        return self.pid, self.title_text

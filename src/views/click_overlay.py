from __future__ import annotations

"""Overlay for selecting a window by clicking it."""

import os
import tkinter as tk
from typing import Optional

from src.utils.window_utils import (
    get_active_window,
    get_window_under_cursor,
    WindowInfo,
)


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
    ) -> None:
        super().__init__(parent)
        # Configure fullscreen before enabling override-redirect to avoid
        # "can't set fullscreen attribute" errors on some platforms.
        self.attributes("-topmost", True)
        self.attributes("-fullscreen", True)
        self.overrideredirect(True)
        self.configure(cursor="crosshair")
        # Using an empty string for the canvas background causes a TclError on
        # some platforms. Use the parent's background color to keep the canvas
        # visually unobtrusive while avoiding invalid color values.
        bg_color = parent.cget("bg") if isinstance(parent, tk.Widget) else self.cget("bg")
        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.rect = self.canvas.create_rectangle(
            0, 0, 1, 1, outline=highlight, width=2
        )
        # crosshair lines spanning the entire screen for precise selection
        self.hline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
        self.vline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
        self.label = self.canvas.create_text(
            0, 0, anchor="nw", fill=highlight, text="", font=("TkDefaultFont", 10, "bold")
        )
        self.probe_attempts = probe_attempts
        self.timeout = timeout
        self._after_id: Optional[str] = None
        self._timeout_id: Optional[str] = None
        self.pid: int | None = None
        self.title_text: str | None = None
        self._own_pid = os.getpid()

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

    def _query_window(self) -> WindowInfo:
        """Return the window info below the cursor, ignoring this overlay."""
        info = get_window_under_cursor()
        if info.pid == self._own_pid or info.pid is None:
            alpha = float(self.attributes("-alpha")) if self.attributes("-alpha") != "" else 1.0
            try:
                self.attributes("-alpha", 0.0)
                # Probe multiple times in case other windows from this process are stacked
                for _ in range(self.probe_attempts):
                    info = get_window_under_cursor()
                    if info.pid not in (self._own_pid, None):
                        break
            finally:
                self.attributes("-alpha", alpha)
        if info.pid is None:
            info = get_active_window()
        return info

    def _update_rect(self, _e: object | None = None) -> None:
        info: WindowInfo = self._query_window()
        self.lift()
        self.pid = info.pid
        self.title_text = info.title

        px = self.winfo_pointerx()
        py = self.winfo_pointery()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Draw crosshair lines centered on the cursor
        self.canvas.coords(self.hline, 0, py, sw, py)
        self.canvas.coords(self.vline, px, 0, px, sh)

        if info.rect:
            x, y, w, h = info.rect
            self.canvas.coords(self.rect, x, y, x + w, y + h)
        else:
            self.canvas.coords(self.rect, -5, -5, -5, -5)
        text = info.title or ("PID " + str(info.pid) if info.pid else "")
        self.canvas.itemconfigure(self.label, text=text)
        self._position_label(px, py, sw, sh)
        # poll at ~30fps for smooth updates
        self._after_id = self.after(30, self._update_rect)

    def _click(self, _e: object | None = None) -> None:
        # Refresh window info on click to avoid stale selections when moving fast
        info: WindowInfo = self._query_window()
        self.pid = info.pid
        self.title_text = info.title
        self.close()

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
        self.destroy()

    def choose(self) -> tuple[int | None, str | None]:
        """Show the overlay and return the PID and title of the clicked window."""
        self.bind("<Motion>", self._update_rect)
        self.bind("<Button-1>", self._click)
        self.bind("<Escape>", self.close)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._update_rect()
        if self.timeout is not None:
            self._timeout_id = self.after(int(self.timeout * 1000), self.close)
        self.grab_set()
        self.wait_window()
        return self.pid, self.title_text

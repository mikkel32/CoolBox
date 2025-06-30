from __future__ import annotations

"""Overlay for selecting a window by clicking it."""

import tkinter as tk
from typing import Optional

from src.utils.window_utils import get_window_under_cursor, WindowInfo


class ClickOverlay(tk.Toplevel):
    """Fullscreen transparent window used to select another window."""

    def __init__(self, parent: tk.Misc, highlight: str = "red") -> None:
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
        self.label = self.canvas.create_text(
            0, 0, anchor="nw", fill=highlight, text="", font=("TkDefaultFont", 10, "bold")
        )
        self._after_id: Optional[str] = None
        self.pid: int | None = None
        self.title_text: str | None = None

    def _update_rect(self, _e: object | None = None) -> None:
        self.withdraw()
        info: WindowInfo = get_window_under_cursor()
        self.deiconify()
        self.lift()
        self.pid = info.pid
        self.title_text = info.title
        if info.rect:
            x, y, w, h = info.rect
            self.canvas.coords(self.rect, x, y, x + w, y + h)
            self.canvas.coords(self.label, x + 3, y + 3)
        else:
            self.canvas.coords(self.rect, -5, -5, -5, -5)
            self.canvas.coords(self.label, -5, -5)
        text = info.title or ("PID " + str(info.pid) if info.pid else "")
        self.canvas.itemconfigure(self.label, text=text)
        self._after_id = self.after(50, self._update_rect)

    def _click(self, _e: object | None = None) -> None:
        self.close()

    def close(self, _e: object | None = None) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self.destroy()

    def choose(self) -> tuple[int | None, str | None]:
        """Show the overlay and return the PID and title of the clicked window."""
        self.bind("<Motion>", self._update_rect)
        self.bind("<Button-1>", self._click)
        self.bind("<Escape>", self.close)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._update_rect()
        self.grab_set()
        self.wait_window()
        return self.pid, self.title_text

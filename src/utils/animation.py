from __future__ import annotations
import customtkinter as ctk


def slide_widget(widget: ctk.CTkBaseClass, start: float, end: float, *, steps: int = 20, delay: int = 5) -> None:
    """Slide *widget* horizontally from *start* to *end* relative x position."""
    delta = (end - start) / steps
    for i in range(steps):
        widget.place_configure(relx=start + delta * i)
        widget.update_idletasks()
        widget.after(delay)
    widget.place_configure(relx=end)

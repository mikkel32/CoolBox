"""Simple tooltip implementation for CTk widgets."""
from __future__ import annotations

import customtkinter as ctk


class Tooltip(ctk.CTkToplevel):
    """Popup tooltip window bound to a widget."""

    def __init__(self, parent: ctk.CTkBaseClass, text: str) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        self.withdraw()
        self.label = ctk.CTkLabel(self, text=text, font=ctk.CTkFont(size=12))
        self.label.pack(padx=6, pady=3)

    def show(self, x: int, y: int) -> None:
        """Display the tooltip at screen coordinates (x, y)."""
        self.geometry(f"+{x}+{y}")
        self.deiconify()

    def hide(self) -> None:
        """Hide the tooltip."""
        self.withdraw()

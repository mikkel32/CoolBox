from __future__ import annotations

import customtkinter as ctk

from .base_dialog import BaseDialog


class ShortcutHelpDialog(BaseDialog):
    """Show a list of available keyboard shortcuts."""

    def __init__(self, app):
        super().__init__(app, title="Keyboard Shortcuts", geometry="400x350")

        container = self.create_card(self, shadow=True)
        inner = container.inner
        self.add_title(inner, "Keyboard Shortcuts", use_pack=False).grid(
            row=0, column=0, columnspan=2, pady=(0, self.pady)
        )

        shortcuts = [
            ("Ctrl+H", "Home view"),
            ("Ctrl+T", "Tools view"),
            ("Ctrl+S", "Settings view"),
            ("Ctrl+Q", "Quick Settings"),
            ("Ctrl+Alt+F", "Force Quit dialog"),
            ("F11", "Toggle fullscreen"),
            ("Ctrl+F", "Focus search"),
            ("Esc", "Close dialog/Exit"),
            ("F1", "Show this help"),
        ]

        for idx, (keys, desc) in enumerate(shortcuts, start=1):
            lbl_key = ctk.CTkLabel(inner, text=keys)
            lbl_desc = ctk.CTkLabel(inner, text=desc)
            self._mark_font_role(lbl_key, "normal")
            self._mark_font_role(lbl_desc, "normal")
            lbl_key.grid(row=idx, column=0, sticky="e", padx=self.gpadx, pady=self.gpady)
            lbl_desc.grid(row=idx, column=1, sticky="w", padx=self.gpadx, pady=self.gpady)

        inner.grid_columnconfigure(1, weight=1)
        self.center_window()
        self.refresh_fonts()
        self.refresh_theme()

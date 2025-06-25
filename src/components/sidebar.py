"""Sidebar component for navigation."""
from __future__ import annotations

import customtkinter as ctk
from typing import Dict

from .tooltip import Tooltip

WIDTH = 200


class Sidebar(ctk.CTkFrame):
    """Application sidebar for navigation"""

    def __init__(self, parent, app):
        super().__init__(parent, corner_radius=0, width=WIDTH)
        self.app = app
        self.buttons: Dict[str, ctk.CTkButton] = {}
        self.icons: Dict[str, str] = {}
        self.labels: Dict[str, str] = {}
        self._tooltips: Dict[str, Tooltip] = {}

        # Prevent geometry from shrinking
        self.grid_propagate(False)
        self.grid_rowconfigure(4, weight=1)

        self.title = ctk.CTkLabel(
            self,
            text="CoolBox",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        self.title.grid(row=0, column=0, padx=20, pady=(20, 30))

        # Navigation buttons
        self._create_nav_button("home", "🏠 Home", 1)
        self._create_nav_button("tools", "🛠️ Tools", 2)
        self._create_nav_button("settings", "⚙️ Settings", 3)

        spacer = ctk.CTkFrame(self, fg_color="transparent")
        spacer.grid(row=4, column=0, sticky="nsew")

        self._create_nav_button("about", "ℹ️ About", 5)

        self.theme_toggle = ctk.CTkButton(
            self,
            text="🌙 Dark Mode",
            command=self._toggle_theme,
            height=32,
        )
        self.theme_toggle.grid(row=6, column=0, padx=20, pady=(10, 5), sticky="ew")

    # ------------------------------------------------------------------
    def _on_hover(self, tooltip: Tooltip, event) -> None:
        x = self.winfo_rootx() + self.winfo_width() + 10
        y = event.widget.winfo_rooty() + event.widget.winfo_height() // 2
        tooltip.show(x, y)

    # ------------------------------------------------------------------
    def _create_nav_button(self, name: str, text: str, row: int) -> None:
        icon, label = text.split(" ", 1)
        button = ctk.CTkButton(
            self,
            text=text,
            command=lambda: self.app.switch_view(name),
            height=40,
            anchor="w",
            font=ctk.CTkFont(size=14),
        )
        button.grid(row=row, column=0, padx=20, pady=5, sticky="ew")
        self.buttons[name] = button
        self.icons[name] = icon
        self.labels[name] = label
        tooltip = Tooltip(self, label)
        self._tooltips[name] = tooltip
        button.bind("<Enter>", lambda e, t=tooltip: self._on_hover(t, e))
        button.bind("<Leave>", lambda e, t=tooltip: t.hide())

    # ------------------------------------------------------------------
    def set_active(self, view_name: str) -> None:
        for button in self.buttons.values():
            button.configure(fg_color=["#3B8ED0", "#1F6AA5"])
        if view_name in self.buttons:
            self.buttons[view_name].configure(fg_color=["#1F6AA5", "#144870"])

    # ------------------------------------------------------------------
    def _toggle_theme(self) -> None:
        current = ctk.get_appearance_mode()
        new_mode = "light" if current == "Dark" else "dark"
        ctk.set_appearance_mode(new_mode)

        if new_mode == "dark":
            self.theme_toggle.configure(text="🌙 Dark Mode")
        else:
            self.theme_toggle.configure(text="☀️ Light Mode")

        self.app.config.set("appearance_mode", new_mode)

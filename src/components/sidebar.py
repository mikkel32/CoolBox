"""Sidebar component for navigation."""

from __future__ import annotations

import customtkinter as ctk

from .base_component import BaseComponent
from .icon_button import IconButton

SIDEBAR_WIDTH = 200


class Sidebar(BaseComponent):
    """Application sidebar for navigation"""

    def __init__(self, parent, app):
        """Initialize sidebar"""
        super().__init__(parent, app, corner_radius=0, width=SIDEBAR_WIDTH)
        self.accent = app.theme.get_theme().get("accent_color", "#1faaff")
        self.active_color = [self.accent, self.accent]
        self.inactive_color = ["#3B8ED0", "#1F6AA5"]
        self.grid_propagate(False)

        # Configure grid
        self.grid_rowconfigure(4, weight=1)  # Make row 4 expandable

        # Title
        self.title = ctk.CTkLabel(self, text="CoolBox", font=self.title_font)
        self._mark_font_role(self.title, "title")
        self.title.grid(row=0, column=0, padx=20, pady=(20, 30))

        # Segmented navigation
        self._segments = {
            "home": "🏠 Home",
            "tools": "🛠 Tools",
            "settings": "⚙ Settings",
            "about": "❓ About",
        }
        self.seg_var = ctk.StringVar(value=self._segments["home"])
        self.segmented = ctk.CTkSegmentedButton(
            self,
            variable=self.seg_var,
            values=list(self._segments.values()),
            command=self._on_segment,
            font=self.font,
        )
        self._mark_font_role(self.segmented, "normal")
        self.segmented.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.add_tooltip(self.segmented, "Switch application view")

        # Spacer frame (this will expand)
        spacer = ctk.CTkFrame(self, fg_color="transparent")
        spacer.grid(row=4, column=0, sticky="nsew")

        # Theme toggle
        self.theme_toggle = IconButton(
            self,
            self.app,
            "🌙",
            text="Dark Mode",
            command=self._toggle_theme,
            width=120,
        )
        self.theme_toggle.grid(row=6, column=0, padx=20, pady=(10, 5), sticky="ew")

        # Spacer below theme toggle
        spacer_bottom = ctk.CTkFrame(self, fg_color="transparent")
        spacer_bottom.grid(row=7, column=0, pady=(0, 20))

    def _on_segment(self, value: str) -> None:
        """Switch view when a segmented button is selected."""
        for key, label in self._segments.items():
            if label == value:
                self.app.switch_view(key)
                self.set_active(key)
                break

    def set_active(self, view_name: str):
        """Highlight the selected segment."""
        if hasattr(self, "segmented"):
            label = self._segments.get(view_name, view_name)
            self.seg_var.set(label)

    def _toggle_theme(self):
        """Toggle between light and dark theme"""
        current = ctk.get_appearance_mode()
        new_mode = "light" if current == "Dark" else "dark"
        ctk.set_appearance_mode(new_mode)

        # Update button text
        if new_mode == "dark":
            self.theme_toggle.configure(text="🌙 Dark Mode")
        else:
            self.theme_toggle.configure(text="☀️ Light Mode")

        # Save preference
        self.app.config.set("appearance_mode", new_mode)

    def refresh_fonts(self) -> None:
        """Update fonts based on the current configuration."""
        size = int(self.app.config.get("font_size", 14))
        scale = float(self.app.config.get("ui_scale", 1.0))
        family = self.app.config.get("font_family", "Arial")
        self.font.configure(size=int(size * scale), family=family)
        self.title_font.configure(size=int((size + 10) * scale), family=family)
        self.title.configure(font=self.title_font)
        if hasattr(self, "segmented"):
            self.segmented.configure(font=self.font)
        self.theme_toggle.configure(font=self.font)

    def refresh_scale(self) -> None:
        self.refresh_fonts()

    def refresh_theme(self) -> None:
        """Refresh accent colors."""
        self.accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        self.active_color = [self.accent, self.accent]
        self.set_active(self.app.current_view or "home")

"""Sidebar component for navigation."""

from __future__ import annotations

import customtkinter as ctk
from typing import Dict

from .tooltip import Tooltip

SIDEBAR_WIDTH = 200


class Sidebar(ctk.CTkFrame):
    """Application sidebar for navigation"""

    def __init__(self, parent, app):
        """Initialize sidebar"""
        super().__init__(parent, corner_radius=0, width=SIDEBAR_WIDTH)
        self.app = app
        self.buttons: Dict[str, ctk.CTkButton] = {}
        self.icons: Dict[str, str] = {}
        self.labels: Dict[str, str] = {}
        self._tooltips: Dict[str, Tooltip] = {}
        size = int(app.config.get("font_size", 14))
        self.font = ctk.CTkFont(size=size)
        self.title_font = ctk.CTkFont(size=size + 10, weight="bold")
        self.accent = app.theme.get_theme().get("accent_color", "#1faaff")
        self.active_color = [self.accent, self.accent]
        self.inactive_color = ["#3B8ED0", "#1F6AA5"]
        self.grid_propagate(False)

        # Configure grid
        self.grid_rowconfigure(4, weight=1)  # Make row 4 expandable

        # Title
        self.title = ctk.CTkLabel(
            self,
            text="CoolBox",
            font=self.title_font,
        )
        self.title.grid(row=0, column=0, padx=20, pady=(20, 30))

        # Navigation buttons
        self._create_nav_button("home", "🏠 Home", 1)
        self._create_nav_button("tools", "🛠️ Tools", 2)
        self._create_nav_button("settings", "⚙️ Settings", 3)

        # Spacer frame (this will expand)
        spacer = ctk.CTkFrame(self, fg_color="transparent")
        spacer.grid(row=4, column=0, sticky="nsew")

        # About button at bottom
        self._create_nav_button("about", "ℹ️ About", 5)

        # Theme toggle
        self.theme_toggle = ctk.CTkButton(
            self,
            text="🌙 Dark Mode",
            command=self._toggle_theme,
            height=32,
            font=self.font,
        )
        self.theme_toggle.grid(row=6, column=0, padx=20, pady=(10, 5), sticky="ew")

        # Spacer below theme toggle
        spacer_bottom = ctk.CTkFrame(self, fg_color="transparent")
        spacer_bottom.grid(row=7, column=0, pady=(0, 20))

    def _on_hover(self, tooltip: Tooltip, event) -> None:
        """Show tooltip below a button."""
        x = event.widget.winfo_rootx() + event.widget.winfo_width() // 2
        y = event.widget.winfo_rooty() + event.widget.winfo_height() + 10
        tooltip.show(x, y)

    def _create_nav_button(self, name: str, text: str, row: int):
        """Create a navigation button"""
        icon, label = text.split(" ", 1)
        button = ctk.CTkButton(
            self,
            text=text,
            command=lambda: self.app.switch_view(name),
            height=40,
            anchor="w",
            font=self.font,
        )
        button.grid(row=row, column=0, padx=20, pady=5, sticky="ew")
        self.buttons[name] = button
        self.icons[name] = icon
        self.labels[name] = label
        tooltip = Tooltip(self, label)
        self._tooltips[name] = tooltip
        button.bind("<Enter>", lambda e, t=tooltip: self._on_hover(t, e))
        button.bind("<Leave>", lambda e, t=tooltip: t.hide())

    def set_active(self, view_name: str):
        """Set the active button"""
        # Reset all buttons
        for button in self.buttons.values():
            button.configure(fg_color=self.inactive_color)

        # Highlight active button
        if view_name in self.buttons:
            self.buttons[view_name].configure(fg_color=self.active_color)

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
        self.font.configure(size=size)
        self.title_font.configure(size=size + 10)
        self.title.configure(font=self.title_font)
        for btn in self.buttons.values():
            btn.configure(font=self.font)
        self.theme_toggle.configure(font=self.font)

    def refresh_theme(self) -> None:
        """Refresh accent colors."""
        self.accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        self.active_color = [self.accent, self.accent]
        self.set_active(self.app.current_view or "home")

"""Sidebar component for navigation."""

from __future__ import annotations

import customtkinter as ctk
from typing import Dict

from .tooltip import Tooltip

COLLAPSED_WIDTH = 60
EXPANDED_WIDTH = 200
AUTO_COLLAPSE_WIDTH = 700


class Sidebar(ctk.CTkFrame):
    """Application sidebar for navigation"""

    def __init__(self, parent, app):
        """Initialize sidebar"""
        super().__init__(parent, corner_radius=0, width=EXPANDED_WIDTH)
        self.app = app
        self.buttons: Dict[str, ctk.CTkButton] = {}
        self.icons: Dict[str, str] = {}
        self.labels: Dict[str, str] = {}
        self._tooltips: Dict[str, Tooltip] = {}
        self.collapsed: bool = False
        self._auto_collapsed = False
        self._animating = False
        self._anim_job: str | None = None
        # Prevent grid geometry from overriding the specified width so
        # collapsing the sidebar actually changes its visible size.
        self.grid_propagate(False)

        # Configure grid
        self.grid_rowconfigure(4, weight=1)  # Make row 4 expandable

        # Title
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
        )
        self.theme_toggle.grid(row=6, column=0, padx=20, pady=(10, 5), sticky="ew")

        # Collapse/expand button
        self.collapse_btn = ctk.CTkButton(
            self,
            text="◀",
            command=self.toggle,
            width=32,
            height=32,
        )
        self.collapse_btn.grid(row=7, column=0, pady=(0, 20))

    def set_collapsed(self, collapsed: bool) -> None:
        """Collapse or expand the sidebar."""
        if collapsed == self.collapsed and not self._animating:
            return
        self.collapsed = collapsed
        width = COLLAPSED_WIDTH if collapsed else EXPANDED_WIDTH
        self._animate_width(width)
        self.title.configure(text="🧊" if collapsed else "CoolBox")
        for name, button in self.buttons.items():
            icon = self.icons[name]
            label = self.labels[name]
            button.configure(text=icon if collapsed else f"{icon} {label}")
        current = ctk.get_appearance_mode()
        if current == "Dark":
            dark_text = "🌙" if collapsed else "🌙 Dark Mode"
        else:
            dark_text = "☀️" if collapsed else "☀️ Light Mode"
        self.theme_toggle.configure(text=dark_text)
        self.collapse_btn.configure(text="▶" if collapsed else "◀")
        if not collapsed:
            for tooltip in self._tooltips.values():
                tooltip.hide()

    def toggle(self) -> None:
        """Toggle collapsed state."""
        self._auto_collapsed = False
        self.set_collapsed(not self.collapsed)

    def _on_hover(self, tooltip: Tooltip, event) -> None:
        """Show tooltip for a button when sidebar is collapsed."""
        if not self.collapsed:
            return
        x = self.winfo_rootx() + self.winfo_width() + 10
        y = event.widget.winfo_rooty() + event.widget.winfo_height() // 2
        tooltip.show(x, y)

    def _animate_width(self, target: int) -> None:
        """Animate sidebar width change to *target* pixels."""
        start = self.winfo_width()
        steps = 8
        delta = (target - start) / steps

        def step(i: int = 1) -> None:
            if i > steps:
                self.configure(width=target)
                self._animating = False
                self._anim_job = None
                return
            self.configure(width=int(start + delta * i))
            self._anim_job = self.after(15, lambda: step(i + 1))

        if self._anim_job is not None:
            self.after_cancel(self._anim_job)

        self._animating = True
        step()

    def auto_adjust(self, window_width: int) -> None:
        """Collapse or expand based on *window_width* for responsive layout."""
        if self._animating:
            return
        if window_width <= AUTO_COLLAPSE_WIDTH and not self.collapsed:
            self._auto_collapsed = True
            self.set_collapsed(True)
        elif window_width > AUTO_COLLAPSE_WIDTH and self.collapsed and self._auto_collapsed:
            self._auto_collapsed = False
            self.set_collapsed(False)

    def _create_nav_button(self, name: str, text: str, row: int):
        """Create a navigation button"""
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

    def set_active(self, view_name: str):
        """Set the active button"""
        # Reset all buttons
        for button in self.buttons.values():
            button.configure(fg_color=["#3B8ED0", "#1F6AA5"])

        # Highlight active button
        if view_name in self.buttons:
            self.buttons[view_name].configure(fg_color=["#1F6AA5", "#144870"])

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
        # Refresh collapsed state label
        if self.collapsed:
            self.set_collapsed(True)

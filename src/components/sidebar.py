"""
Sidebar component for navigation
"""
import customtkinter as ctk
from typing import Dict


class Sidebar(ctk.CTkFrame):
    """Application sidebar for navigation"""

    def __init__(self, parent, app):
        """Initialize sidebar"""
        super().__init__(parent, corner_radius=0, width=200)
        self.app = app
        self.buttons: Dict[str, ctk.CTkButton] = {}

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
        self.theme_toggle.grid(row=6, column=0, padx=20, pady=(10, 20), sticky="ew")

    def _create_nav_button(self, name: str, text: str, row: int):
        """Create a navigation button"""
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

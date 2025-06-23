"""Utility functions and classes for theming CoolBox."""
import json
from pathlib import Path
from typing import Dict

import customtkinter as ctk


class ThemeManager:
    """Manage application themes."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or (Path.home() / ".coolbox")
        self._theme_file = self._config_dir / "custom_theme.json"

        if self._theme_file.exists():
            self.load_theme()

    def load_theme(self) -> Dict[str, str]:
        """Load theme from disk and apply it."""
        try:
            with open(self._theme_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            ctk.set_default_color_theme(str(self._theme_file))
            return data.get("CTk", {}).get("color_scale", {})
        except Exception:
            return {}

    def apply_theme(self, theme: Dict[str, str]) -> None:
        """Apply a custom color theme to CTk widgets.

        ``CustomTkinter`` uses JSON files for custom themes.  This function
        writes ``theme`` to ``custom_theme.json`` in the configuration
        directory and instructs CTk to load it.
        """

        self._config_dir.mkdir(exist_ok=True)
        theme_data = {
            "CTk": {
                "color_scale": {
                    "primary_color": theme.get("primary_color", "#1f538d"),
                    "secondary_color": theme.get("secondary_color", "#212121"),
                    "text_color": theme.get("text_color", "#ffffff"),
                    "background_color": theme.get("background_color", "#1e1e1e"),
                    "accent_color": theme.get("accent_color", "#007acc"),
                }
            }
        }

        with open(self._theme_file, "w", encoding="utf-8") as f:
            json.dump(theme_data, f, indent=4)

        ctk.set_default_color_theme(str(self._theme_file))
            
    def use_default_theme(self) -> None:
        """Reset to the default theme values."""
        ctk.set_default_color_theme("blue")

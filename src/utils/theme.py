"""Utility functions and classes for theming CoolBox."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, TYPE_CHECKING
import sys

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from ..config import Config

import customtkinter as ctk


def get_system_accent_color() -> str:
    """Return the OS accent color if available."""
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM"
            ) as key:
                value = winreg.QueryValueEx(key, "AccentColor")[0]
            r = (value >> 16) & 0xFF
            g = (value >> 8) & 0xFF
            b = value & 0xFF
            return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        pass
    return "#007acc"


class ThemeManager:
    """Manage application themes and persist user customizations."""

    def __init__(self, config_dir: Path | None = None, config: Config | None = None) -> None:
        self._config_dir = config_dir or (Path.home() / ".coolbox")
        self._theme_file = self._config_dir / "custom_theme.json"
        self.current_theme: Dict[str, str] = {}
        self._config = config

        if self._theme_file.exists():
            self.current_theme = self.load_theme()

    def bind_config(self, config: Config) -> None:
        """Attach a configuration object for automatic persistence."""
        self._config = config

    def load_theme(self) -> Dict[str, str]:
        """Load theme from disk and apply it."""
        try:
            with open(self._theme_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            colors = data.get("CTk", {}).get("color_scale", {})
            ctk.set_default_color_theme(str(self._theme_file))
            self.current_theme = colors
            return colors
        except Exception:
            self.current_theme = {}
            return {}

    def apply_theme(self, theme: Dict[str, str]) -> None:
        """Apply a custom color theme to CTk widgets.

        ``CustomTkinter`` uses JSON files for custom themes.  This function
        writes ``theme`` to ``custom_theme.json`` in the configuration
        directory and instructs CTk to load it.
        """

        self._config_dir.mkdir(exist_ok=True)

        # load the builtin "blue" theme as a base so all required keys are
        # present. this avoids KeyError when CustomTkinter widgets expect
        # certain settings like ``CTkFrame`` to exist.
        builtin_path = (
            Path(ctk.__file__).parent / "assets" / "themes" / "blue.json"
        )
        try:
            with open(builtin_path, "r", encoding="utf-8") as f:
                theme_data = json.load(f)
        except Exception:
            theme_data = {"CTk": {}}

        self.current_theme = {
            "primary_color": theme.get("primary_color", "#1f538d"),
            "secondary_color": theme.get("secondary_color", "#212121"),
            "text_color": theme.get("text_color", "#ffffff"),
            "background_color": theme.get("background_color", "#1e1e1e"),
            "accent_color": theme.get("accent_color", "#007acc"),
        }
        theme_data.setdefault("CTk", {})["color_scale"] = self.current_theme

        with open(self._theme_file, "w", encoding="utf-8") as f:
            json.dump(theme_data, f, indent=4)

        ctk.set_default_color_theme(str(self._theme_file))
        if self._config is not None:
            self._config.set("theme", self.current_theme)

    def get_theme(self) -> Dict[str, str]:
        """Return a copy of the currently applied theme."""
        return self.current_theme.copy()

    def export_theme(self, path: str) -> None:
        """Export the current theme configuration to *path*."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"CTk": {"color_scale": self.current_theme}}, f, indent=4)

    def import_theme(self, path: str) -> None:
        """Import theme settings from *path* and apply them."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.apply_theme(data.get("CTk", {}).get("color_scale", {}))
        except Exception:
            pass

    def use_default_theme(self) -> None:
        """Reset to the default theme values."""
        self.current_theme = {}
        ctk.set_default_color_theme("blue")
        if self._config is not None:
            self._config.set("theme", self.current_theme)

"""Utility functions and classes for theming CoolBox."""
import customtkinter as ctk
from typing import Dict


class ThemeManager:
    """Manage application themes."""

    def apply_theme(self, theme: Dict[str, str]) -> None:
        """Apply a custom color theme to CTk widgets."""
        for key, value in theme.items():
            ctk.set_widget_scaling(1.0)
            # For now we simply expose method for future expansion
            # CustomTkinter does not yet support setting arbitrary colors
            # dynamically beyond built-in themes, but this placeholder allows
            # future improvements.
            
    def use_default_theme(self) -> None:
        """Reset to the default theme values."""
        ctk.set_default_color_theme("blue")

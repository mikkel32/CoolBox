"""Theme utilities."""

import tkinter as tk


def apply_theme(root: tk.Misc) -> None:
    """Apply a basic theme to the application."""
    root.option_add("*Font", "Arial 11")

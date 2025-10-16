"""Reusable widget helpers using CustomTkinter."""

import customtkinter as ctk


def info_label(master: ctk.CTkBaseClass, text: str, *, font=None) -> ctk.CTkLabel:
    """Return a grey informational label using master's font when available."""
    if font is None:
        font = getattr(master, "font", None)
    label = ctk.CTkLabel(master, text=text, text_color="gray", font=font)
    marker = getattr(master, "_mark_font_role", None)
    if callable(marker):
        marker(label, "normal")
    return label

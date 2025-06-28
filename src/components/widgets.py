"""Reusable widget helpers using CustomTkinter."""

import customtkinter as ctk


def info_label(master: ctk.CTkBaseClass, text: str, *, font=None) -> ctk.CTkLabel:
    """Return a grey informational label using master's font when available."""
    if font is None:
        font = getattr(master, "font", None)
    label = ctk.CTkLabel(master, text=text, text_color="gray", font=font)
    if hasattr(master, "_mark_font_role"):
        master._mark_font_role(label, "normal")
    return label

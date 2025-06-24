"""Reusable widget helpers using CustomTkinter."""

import customtkinter as ctk


def info_label(master: ctk.CTkBaseClass, text: str) -> ctk.CTkLabel:
    """Return a grey informational label."""
    return ctk.CTkLabel(master, text=text, text_color="gray")

"""Reusable widgets."""

import tkinter as tk


def info_label(master: tk.Misc, text: str) -> tk.Label:
    return tk.Label(master, text=text, fg="#555")

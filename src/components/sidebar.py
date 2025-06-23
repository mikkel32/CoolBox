"""Sidebar navigation component."""

import tkinter as tk
from typing import Callable


class Sidebar(tk.Frame):
    def __init__(self, master: tk.Misc, callback: Callable[[str], None]) -> None:
        super().__init__(master, width=150, bg="#EEE")
        self.callback = callback
        self._init_ui()

    def _init_ui(self) -> None:
        buttons = [
            ("Home", "home"),
            ("Tools", "tools"),
            ("Settings", "settings"),
            ("About", "about"),
        ]
        for text, name in buttons:
            btn = tk.Button(self, text=text, command=lambda n=name: self.callback(n))
            btn.pack(fill=tk.X, pady=2, padx=4)

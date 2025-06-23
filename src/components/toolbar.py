"""Toolbar component."""

import tkinter as tk


class Toolbar(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg="#222")
        self.label = tk.Label(self, text="CoolBox", fg="white", bg="#222")
        self.label.pack(side=tk.LEFT, padx=5, pady=5)

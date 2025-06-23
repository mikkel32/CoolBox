"""Status bar component."""

import tkinter as tk


class StatusBar(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg="#EEE")
        self.label = tk.Label(self, text="Ready", anchor="w")
        self.label.pack(fill=tk.X, padx=4)

    def set_status(self, text: str) -> None:
        self.label.config(text=text)

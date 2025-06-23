"""Home screen view."""

import tkinter as tk
from ..components.widgets import info_label


class HomeView(tk.Frame):
    def __init__(self, master: tk.Misc, app: tk.Misc) -> None:
        super().__init__(master)
        info = info_label(self, "Welcome to CoolBox!")
        info.pack(pady=20)

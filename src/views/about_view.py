"""About screen view."""

import tkinter as tk
from ..components.widgets import info_label


class AboutView(tk.Frame):
    def __init__(self, master: tk.Misc, app: tk.Misc) -> None:
        super().__init__(master)
        label = info_label(self, "CoolBox v1.0")
        label.pack(pady=20)

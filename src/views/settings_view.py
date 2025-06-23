"""Settings screen view."""

import tkinter as tk
from ..components.widgets import info_label


class SettingsView(tk.Frame):
    def __init__(self, master: tk.Misc, app: tk.Misc) -> None:
        super().__init__(master)
        label = info_label(self, "Modify your settings here.")
        label.pack(pady=20)

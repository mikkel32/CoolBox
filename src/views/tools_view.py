"""Tools screen view."""

import tkinter as tk
from ..components.widgets import info_label


class ToolsView(tk.Frame):
    def __init__(self, master: tk.Misc, app: tk.Misc) -> None:
        super().__init__(master)
        label = info_label(self, "Tools will appear here.")
        label.pack(pady=20)

import customtkinter as ctk

from .base_component import BaseComponent
from .icon_button import IconButton


class SearchEntry(BaseComponent):
    """Entry widget with an integrated search button."""

    def __init__(self, parent, app, variable: ctk.StringVar, command, *, placeholder: str = "Search...", width: int = 200):
        super().__init__(parent, app)
        self.variable = variable
        self.command = command
        self.entry = ctk.CTkEntry(self, textvariable=variable, placeholder_text=placeholder, width=width)
        self._mark_font_role(self.entry, "normal")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<KeyRelease>", lambda _e: command())
        self.entry.bind("<Return>", lambda _e: command())
        self.entry.bind("<Escape>", lambda _e: (variable.set(""), command()))
        self.button = IconButton(self, app, "🔍", command=command, width=30)
        self.button.pack(side="right", padx=(5, 0))
        self.register_widget(self.entry)
        self.register_widget(self.button)

    def refresh_theme(self) -> None:  # type: ignore[override]
        super().refresh_theme()
        self.entry.configure(border_color=self.accent)
        self.button.configure(fg_color=self.accent, hover_color=self.accent)

    def refresh_fonts(self) -> None:  # type: ignore[override]
        super().refresh_fonts()
        self.entry.configure(font=self.font)

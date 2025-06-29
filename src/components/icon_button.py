import customtkinter as ctk
from ..views.base_mixin import UIHelperMixin
from .tooltip import Tooltip


class IconButton(ctk.CTkButton, UIHelperMixin):
    """Button with accent-colored icon and optional tooltip."""

    def __init__(
        self,
        parent,
        app,
        icon: str,
        *,
        text: str = "",
        command=None,
        tooltip: str | None = None,
        width: int = 40,
        height: int = 30,
        **kwargs,
    ) -> None:
        label = f"{icon} {text}".strip()
        ctk.CTkButton.__init__(self, parent, text=label, command=command, width=width, height=height, **kwargs)
        UIHelperMixin.__init__(self, app)
        if hasattr(parent, "register_widget"):
            try:
                parent.register_widget(self)
            except Exception:
                pass
        self._mark_font_role(self, "normal")
        self.configure(font=self.font)
        if tooltip:
            tip = Tooltip(self, tooltip)
            self.bind("<Enter>", lambda e: self._show_tooltip(self, tip))
            self.bind("<Leave>", lambda e: tip.hide())
        self.refresh_theme()
        self.refresh_fonts()

    def refresh_theme(self) -> None:  # type: ignore[override]
        if getattr(self, "app", None) is None:
            return
        accent = self.app.theme.get_theme().get("accent_color", "#1faaff")
        self.configure(fg_color=accent, hover_color=accent)

    def refresh_fonts(self) -> None:  # type: ignore[override]
        if getattr(self, "app", None) is None:
            return
        size = int(self.app.config.get("font_size", 14))
        scale = float(self.app.config.get("ui_scale", 1.0))
        family = self.app.config.get("font_family", "Arial")
        self.font.configure(size=int(size * scale), family=family)
        self.configure(font=self.font)

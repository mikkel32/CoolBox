import tkinter as tk
import customtkinter as ctk

from .base_component import BaseComponent


class Gauge(BaseComponent):
    """Circular gauge widget displaying a percentage value."""

    def __init__(
        self,
        master,
        title: str,
        *,
        size: int = 120,
        thickness: int = 12,
        color: str = "#3B8ED0",
        auto_color: bool = False,
        app=None,
        owner=None,
    ) -> None:
        app = app or getattr(master, "app", None)
        super().__init__(master, app, width=size, height=size)
        if owner is not None and hasattr(owner, "register_widget"):
            owner.register_widget(self)
        self._size = size
        self._thickness = thickness
        self._color = color
        self._auto_color = auto_color
        self._value = 0.0

        scale = 1.0
        base = 14
        family = "Arial"
        if self.app is not None:
            base = int(self.app.config.get("font_size", 14))
            scale = float(self.app.config.get("ui_scale", 1.0))
            family = self.app.config.get("font_family", "Arial")
        self.font = ctk.CTkFont(
            size=max(int((base - 2) * scale), 8), family=family, weight="bold"
        )
        self.title_font = ctk.CTkFont(size=int((base - 2) * scale), family=family)

        self.canvas = tk.Canvas(
            self,
            width=size,
            height=size,
            highlightthickness=0,
            bg=self._apply_appearance_mode(self.cget("fg_color")),
        )
        self.canvas.pack()
        pad = thickness // 2 + 2
        self.arc = self.canvas.create_arc(
            pad,
            pad,
            size - pad,
            size - pad,
            start=90,
            extent=0,
            style="arc",
            outline=color,
            width=thickness,
        )
        self.label = ctk.CTkLabel(self, text="0%", font=self.font)
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        self.title_label = ctk.CTkLabel(self, text=title, font=self.title_font)
        self.title_label.place(relx=0.5, rely=1.0, anchor="s", y=-4)

    def set(self, value: float | None) -> None:
        """Set gauge value between 0 and 100 or display N/A."""
        if value is None:
            self._value = 0.0
            self.canvas.itemconfig(self.arc, extent=0, outline=self._color)
            self.label.configure(text="N/A")
            return
        value = max(0.0, min(100.0, float(value)))
        self._value = value
        extent = -value / 100.0 * 360.0
        color = self._color
        if self._auto_color:
            if value >= 90:
                color = "#d9534f"  # red
            elif value >= 70:
                color = "#f0ad4e"  # orange
            else:
                color = "#5cb85c"  # green
        self.canvas.itemconfig(self.arc, extent=extent, outline=color)
        self.label.configure(text=f"{value:.0f}%")

    def refresh_fonts(self) -> None:
        if self.app is None:
            return
        base = int(self.app.config.get("font_size", 14))
        scale = float(self.app.config.get("ui_scale", 1.0))
        family = self.app.config.get("font_family", "Arial")
        self.font.configure(size=max(int((base - 2) * scale), 8), family=family)
        self.title_font.configure(size=int((base - 2) * scale), family=family)
        self.label.configure(font=self.font)
        self.title_label.configure(font=self.title_font)

    def refresh_scale(self) -> None:
        self.refresh_fonts()

    def refresh_theme(self) -> None:
        if self.app is None:
            return
        self._color = self.app.theme.get_theme().get("accent_color", self._color)
        self.canvas.itemconfig(self.arc, outline=self._color)

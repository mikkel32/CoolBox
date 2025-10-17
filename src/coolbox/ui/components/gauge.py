import tkinter as tk
import customtkinter as ctk


class Gauge(ctk.CTkFrame):
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
    ) -> None:
        super().__init__(master, width=size, height=size)
        self._size = size
        self._thickness = thickness
        self._color = color
        self._auto_color = auto_color
        self._value = 0.0

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
        self.label = ctk.CTkLabel(self, text="0%", font=ctk.CTkFont(size=16, weight="bold"))
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        self.title_label = ctk.CTkLabel(self, text=title)
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

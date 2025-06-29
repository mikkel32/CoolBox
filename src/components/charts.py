from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .base_component import BaseComponent


class LineChart(BaseComponent):
    """Simple line chart widget with matplotlib."""

    def __init__(
        self,
        master,
        title: str,
        color: str = "#1f6aa5",
        *,
        size: tuple[float, float] = (4, 2),
        app=None,
        owner=None,
    ) -> None:
        """Create a new line chart widget.

        Parameters
        ----------
        master:
            Parent tkinter widget.
        title:
            Chart title displayed above the plot.
        color:
            Initial line color.
        size:
            Matplotlib figure size as ``(width, height)`` in inches.
        """
        app = app or getattr(master, "app", None)
        super().__init__(master, app)
        if owner is not None and hasattr(owner, "register_widget"):
            owner.register_widget(self)

        scale = 1.0
        base = 14
        family = "Arial"
        if self.app is not None:
            base = int(self.app.config.get("font_size", 14))
            scale = float(self.app.config.get("ui_scale", 1.0))
            family = self.app.config.get("font_family", "Arial")
        self.font_size = int(base * scale)
        self.title_size = int((base + 2) * scale)
        self.font_family = family

        self._fig = Figure(figsize=size, dpi=100)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_title(title, fontsize=self.title_size, fontfamily=self.font_family)
        self._ax.set_ylim(0, 100)
        self._ax.set_xlim(0, 60)
        self._ax.set_ylabel("%", fontsize=self.font_size, fontfamily=self.font_family)
        self._ax.grid(True, linestyle="--", alpha=0.5)
        (self._line,) = self._ax.plot([], [], color=color, linewidth=2)
        self._data: list[float] = []
        canvas = FigureCanvasTkAgg(self._fig, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        # keep a reference to the matplotlib canvas without interfering with
        # CTkFrame's internal `_canvas` attribute
        self._mpl_canvas = canvas

    def add_point(self, value: float) -> None:
        self._data.append(value)
        if len(self._data) > 60:
            self._data.pop(0)
        self._line.set_data(range(len(self._data)), self._data)
        self._ax.set_xlim(0, max(60, len(self._data)))
        self._mpl_canvas.draw_idle()

    def set_color(self, color: str) -> None:
        """Update the line color."""
        self._line.set_color(color)
        self._mpl_canvas.draw_idle()

    def clear(self) -> None:
        """Remove all data points from the chart."""
        self._data.clear()
        self._line.set_data([], [])
        self._ax.set_xlim(0, 60)
        self._mpl_canvas.draw_idle()

    def refresh_fonts(self) -> None:
        if self.app is None:
            return
        base = int(self.app.config.get("font_size", 14))
        scale = float(self.app.config.get("ui_scale", 1.0))
        family = self.app.config.get("font_family", "Arial")
        self.font_size = int(base * scale)
        self.title_size = int((base + 2) * scale)
        self.font_family = family
        self._ax.title.set_fontsize(self.title_size)
        self._ax.title.set_fontfamily(self.font_family)
        self._ax.yaxis.label.set_fontsize(self.font_size)
        self._ax.yaxis.label.set_fontfamily(self.font_family)
        for label in list(self._ax.get_xticklabels()) + list(
            self._ax.get_yticklabels()
        ):
            label.set_fontsize(self.font_size)
            label.set_fontfamily(self.font_family)
        self._mpl_canvas.draw_idle()

    def refresh_scale(self) -> None:
        self.refresh_fonts()

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .base_component import BaseComponent


class BarChart(BaseComponent):
    """Simple vertical bar chart for displaying lists of values."""

    def __init__(
        self,
        master,
        title: str,
        *,
        bar_color: str = "#3B8ED0",
        size: tuple[float, float] = (4, 2),
        app=None,
        owner=None,
    ) -> None:
        """Create a new bar chart widget.

        Parameters
        ----------
        master:
            Parent tkinter widget.
        title:
            Title displayed above the chart.
        bar_color:
            Initial color for the bars.
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
        self._bars = self._ax.bar([], [], color=bar_color)
        self._ax.grid(True, axis="y", linestyle="--", alpha=0.5)
        canvas = FigureCanvasTkAgg(self._fig, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        # store the matplotlib canvas separately to avoid clashing with
        # CTkFrame's internal canvas attribute
        self._mpl_canvas = canvas

    def set_values(self, values: list[float]) -> None:
        self._ax.cla()
        self._ax.set_ylim(0, 100)
        self._bars = self._ax.bar(range(len(values)), values, color="#3B8ED0")
        self._ax.grid(True, axis="y", linestyle="--", alpha=0.5)
        self._mpl_canvas.draw_idle()

    def set_bar_color(self, color: str) -> None:
        """Change the bar color."""
        for bar in self._bars:
            bar.set_color(color)
        self._mpl_canvas.draw_idle()

    def clear(self) -> None:
        """Remove all bars from the chart."""
        self._ax.cla()
        self._ax.set_ylim(0, 100)
        self._bars = self._ax.bar([], [], color="#3B8ED0")
        self._ax.grid(True, axis="y", linestyle="--", alpha=0.5)
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
        for label in list(self._ax.get_xticklabels()) + list(
            self._ax.get_yticklabels()
        ):
            label.set_fontsize(self.font_size)
            label.set_fontfamily(self.font_family)
        self._mpl_canvas.draw_idle()

    def refresh_scale(self) -> None:
        self.refresh_fonts()

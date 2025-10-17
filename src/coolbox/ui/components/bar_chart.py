import customtkinter as ctk
try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except ImportError:  # pragma: no cover - runtime dependency check
    from coolbox.ensure_deps import ensure_matplotlib

    ensure_matplotlib()
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class BarChart(ctk.CTkFrame):
    """Simple vertical bar chart for displaying lists of values."""

    def __init__(
        self,
        master,
        title: str,
        *,
        bar_color: str = "#3B8ED0",
        size: tuple[float, float] = (4, 2),
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
        super().__init__(master)
        self._fig = Figure(figsize=size, dpi=100)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_title(title)
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

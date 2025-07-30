import customtkinter as ctk
try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_matplotlib

    ensure_matplotlib()
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class LineChart(ctk.CTkFrame):
    """Simple line chart widget with matplotlib."""

    def __init__(self, master, title: str, color: str = "#1f6aa5", *,
                 size: tuple[float, float] = (4, 2)) -> None:
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
        super().__init__(master)
        self._fig = Figure(figsize=size, dpi=100)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_title(title)
        self._ax.set_ylim(0, 100)
        self._ax.set_xlim(0, 60)
        self._ax.set_ylabel("%")
        self._ax.grid(True, linestyle="--", alpha=0.5)
        self._line, = self._ax.plot([], [], color=color, linewidth=2)
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

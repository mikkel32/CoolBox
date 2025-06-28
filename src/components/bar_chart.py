import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class BarChart(ctk.CTkFrame):
    """Simple vertical bar chart for displaying lists of values."""

    def __init__(self, master, title: str, *, bar_color: str = "#3B8ED0") -> None:
        super().__init__(master)
        self._fig = Figure(figsize=(4, 2), dpi=100)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_title(title)
        self._ax.set_ylim(0, 100)
        self._bars = self._ax.bar([], [], color=bar_color)
        self._ax.grid(True, axis="y", linestyle="--", alpha=0.5)
        canvas = FigureCanvasTkAgg(self._fig, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas = canvas

    def set_values(self, values: list[float]) -> None:
        self._ax.cla()
        self._ax.set_ylim(0, 100)
        self._bars = self._ax.bar(range(len(values)), values, color="#3B8ED0")
        self._ax.grid(True, axis="y", linestyle="--", alpha=0.5)
        self._canvas.draw_idle()


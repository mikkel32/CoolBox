import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class LineChart(ctk.CTkFrame):
    """Simple line chart widget with matplotlib."""

    def __init__(self, master, title: str, color: str = "#1f6aa5") -> None:
        super().__init__(master)
        self._fig = Figure(figsize=(4, 2), dpi=100)
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
        self._canvas = canvas

    def add_point(self, value: float) -> None:
        self._data.append(value)
        if len(self._data) > 60:
            self._data.pop(0)
        self._line.set_data(range(len(self._data)), self._data)
        self._ax.set_xlim(0, max(60, len(self._data)))
        self._canvas.draw_idle()

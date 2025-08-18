import json

try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()
import customtkinter as ctk
try:
    import pyperclip
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_pyperclip

    pyperclip = ensure_pyperclip()
import tkinter as tk
try:
    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_matplotlib

    ensure_matplotlib()
    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

from ..utils.system_utils import get_system_info, get_system_metrics
from ..components import LineChart, Gauge, BarChart
from .base_dialog import BaseDialog


class SystemInfoDialog(BaseDialog):
    """Modern dashboard window showing system metrics."""

    def __init__(self, app):
        super().__init__(app, title="System Info", geometry="900x600", resizable=(True, True))
        # Provide a wider default size so all gauges and charts fit without
        # clipping. The previous width of 600px was not sufficient for the
        # six gauges displayed side by side. Increasing the width ensures the
        # interface is fully visible on start-up.

        self._after_id: int | None = None
        self.interval_var = tk.IntVar(value=1)
        self.paused = False
        self._create_layout()
        self._update_metrics()
        self.center_window()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    # ------------------------------------------------------------------ UI setup
    def _create_layout(self) -> None:
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(10, 0))
        copy_btn = ctk.CTkButton(toolbar, text="Copy", width=100, command=self._copy_info)
        copy_btn.pack(side="left", padx=5)
        self.add_tooltip(copy_btn, "Copy system info to clipboard")
        export_btn = ctk.CTkButton(
            toolbar, text="Export", width=100, command=self._export_json
        )
        export_btn.pack(side="left", padx=5)
        self.add_tooltip(export_btn, "Export metrics to JSON")
        self.pause_btn = ctk.CTkButton(
            toolbar, text="Pause", width=80, command=self._toggle_pause
        )
        self.pause_btn.pack(side="right")
        self.add_tooltip(self.pause_btn, "Pause or resume updates")
        ctk.CTkOptionMenu(
            toolbar,
            variable=self.interval_var,
            values=["1", "2", "5", "10"],
            command=lambda _: self._restart_loop(),
            width=80,
        ).pack(side="right", padx=5)
        close_btn = ctk.CTkButton(toolbar, text="Close", width=80, command=self.destroy)
        close_btn.pack(side="right", padx=5)
        self.add_tooltip(close_btn, "Close this window")

        tabview = ctk.CTkTabview(self)
        tabview.pack(fill="both", expand=True, padx=20, pady=20)
        self.overview_tab = tabview.add("Overview")
        self.perf_tab = tabview.add("Performance")
        self.hw_tab = tabview.add("Hardware")

        # Overview text
        # Match the wider window so text uses available space
        self.info_box = ctk.CTkTextbox(self.overview_tab, width=820, height=300)
        self.info_box.pack(fill="both", expand=True)
        self.info_box.insert("1.0", get_system_info())
        self.info_box.configure(state="disabled")

        # Gauges and charts
        gauge_frame = ctk.CTkFrame(self.perf_tab, fg_color="transparent")
        gauge_frame.pack(fill="x")
        self.cpu_gauge = Gauge(gauge_frame, "CPU", auto_color=True)
        self.mem_gauge = Gauge(gauge_frame, "Memory", color="#2386c8", auto_color=True)
        self.disk_gauge = Gauge(gauge_frame, "Disk", color="#dbb73a", auto_color=True)
        self.temp_gauge = Gauge(gauge_frame, "Temp", color="#d9534f", auto_color=True)
        self.batt_gauge = Gauge(gauge_frame, "Battery", color="#5cb85c", auto_color=True)
        self.net_gauge = Gauge(gauge_frame, "Network", color="#8e44ad", auto_color=True)
        self.cpu_gauge.grid(row=0, column=0, padx=10, pady=10)
        self.mem_gauge.grid(row=0, column=1, padx=10, pady=10)
        self.disk_gauge.grid(row=0, column=2, padx=10, pady=10)
        self.temp_gauge.grid(row=0, column=3, padx=10, pady=10)
        self.batt_gauge.grid(row=0, column=4, padx=10, pady=10)
        self.net_gauge.grid(row=0, column=5, padx=10, pady=10)
        for i in range(6):
            gauge_frame.grid_columnconfigure(i, weight=1)

        perf_top = ctk.CTkFrame(self.perf_tab, fg_color="transparent")
        perf_top.pack(fill="x")
        self.net_label = ctk.CTkLabel(
            perf_top, text="Network: 0 MB/s \u2191 / 0 MB/s \u2193", font=self.font
        )
        self.net_label.pack(anchor="w", padx=5)
        self.disk_io_label = ctk.CTkLabel(
            perf_top, text="Disk I/O: 0 MB/s \u2193 / 0 MB/s \u2191", font=self.font
        )
        self.disk_io_label.pack(anchor="w", padx=5)

        chart_frame = ctk.CTkFrame(self.perf_tab, fg_color="transparent")
        chart_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.cpu_chart = LineChart(chart_frame, "CPU Usage", "#db3a34")
        self.cpu_chart.pack(fill="both", expand=True)
        self.mem_chart = LineChart(chart_frame, "Memory Usage", "#2386c8")
        self.mem_chart.pack(fill="both", expand=True, pady=5)
        self.net_up_chart = LineChart(chart_frame, "Network Up", "#34a853")
        self.net_up_chart.pack(fill="both", expand=True)
        self.net_down_chart = LineChart(chart_frame, "Network Down", "#db4437")
        self.net_down_chart.pack(fill="both", expand=True)
        self.disk_read_chart = LineChart(chart_frame, "Disk Read", "#4e79a7")
        self.disk_read_chart.pack(fill="both", expand=True, pady=5)
        self.disk_write_chart = LineChart(chart_frame, "Disk Write", "#f28e2b")
        self.disk_write_chart.pack(fill="both", expand=True, pady=(0, 5))
        NavigationToolbar2Tk(self.cpu_chart._mpl_canvas, chart_frame).pack(
            side="bottom", fill="x"
        )

        # Per-core usage chart
        self.core_count = psutil.cpu_count(logical=True)
        self.core_chart = BarChart(self.hw_tab, "CPU per Core")
        self.core_chart.pack(fill="both", expand=True)

        other = ctk.CTkFrame(self.hw_tab, fg_color="transparent")
        other.pack(fill="x", pady=(10, 0))
        self.freq_label = ctk.CTkLabel(other, text="CPU Freq: 0 MHz", font=self.font)
        self.freq_label.pack(anchor="w")
        self.temp_label = ctk.CTkLabel(other, text="CPU Temp: N/A", font=self.font)
        self.temp_label.pack(anchor="w")
        self.mem_detail = ctk.CTkLabel(other, text="Memory: 0/0 GB", font=self.font)
        self.mem_detail.pack(anchor="w")
        self.disk_detail = ctk.CTkLabel(other, text="Disk: 0/0 GB", font=self.font)
        self.disk_detail.pack(anchor="w")
        self.battery_label = ctk.CTkLabel(other, text="Battery: N/A", font=self.font)
        self.battery_label.pack(anchor="w")

    # --------------------------------------------------------------------- helpers
    def _copy_info(self) -> None:
        info = get_system_info()
        pyperclip.copy(info)
        if self.app.status_bar is not None:
            self.app.status_bar.set_message("System info copied", "success")

    def _export_json(self) -> None:
        metrics = get_system_metrics()
        data = {"info": get_system_info(), "metrics": metrics}
        path = ctk.filedialog.asksaveasfilename(
            title="Export System Info",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            if self.app.status_bar is not None:
                self.app.status_bar.set_message(f"Exported {path}", "success")

    def _toggle_pause(self) -> None:
        """Pause or resume the metrics update loop."""
        if self.paused:
            self.paused = False
            self.pause_btn.configure(text="Pause")
            self._restart_loop()
        else:
            self.paused = True
            self.pause_btn.configure(text="Resume")
            if self._after_id is not None:
                self.after_cancel(self._after_id)

    def _restart_loop(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._after_id = None
        if not self.paused:
            self._update_metrics()

    # ------------------------------------------------------------------ update loop
    def _update_metrics(self) -> None:
        metrics = get_system_metrics()
        self.cpu_gauge.set(metrics["cpu"])
        self.mem_gauge.set(metrics["memory"])
        self.disk_gauge.set(metrics["disk"])
        self.temp_gauge.set(metrics.get("cpu_temp"))
        self.batt_gauge.set(metrics.get("battery"))
        self.cpu_chart.add_point(metrics["cpu"])
        self.mem_chart.add_point(metrics["memory"])
        if "prev" not in self.__dict__:
            self.prev = metrics
        sent = (metrics["sent"] - self.prev["sent"]) / (1024 * 1024)
        recv = (metrics["recv"] - self.prev["recv"]) / (1024 * 1024)
        self.net_up_chart.add_point(sent)
        self.net_down_chart.add_point(recv)
        self.net_label.configure(
            text=f"Network: {sent:.1f} MB/s \u2191 / {recv:.1f} MB/s \u2193"
        )
        net_percent = sent + recv
        self.net_gauge.set(min(net_percent, 100.0))
        read_mb = (metrics["read_bytes"] - self.prev["read_bytes"]) / (1024 * 1024)
        write_mb = (metrics["write_bytes"] - self.prev["write_bytes"]) / (1024 * 1024)
        self.disk_read_chart.add_point(read_mb)
        self.disk_write_chart.add_point(write_mb)
        self.disk_io_label.configure(
            text=f"Disk I/O: {read_mb:.1f} MB/s \u2193 / {write_mb:.1f} MB/s \u2191"
        )
        freq = metrics.get("cpu_freq")
        if freq:
            self.freq_label.configure(text=f"CPU Freq: {freq:.0f} MHz")
        temp = metrics.get("cpu_temp")
        if temp is not None:
            self.temp_label.configure(text=f"CPU Temp: {temp:.0f}°C")
        else:
            self.temp_label.configure(text="CPU Temp: N/A")
        self.mem_detail.configure(
            text=f"Memory: {metrics['memory_used']:.1f}/{metrics['memory_total']:.1f} GB"
        )
        self.disk_detail.configure(
            text=f"Disk: {metrics['disk_used']:.1f}/{metrics['disk_total']:.1f} GB"
        )
        batt = metrics.get("battery")
        if batt is not None:
            self.battery_label.configure(text=f"Battery: {batt:.0f}%")
        else:
            self.battery_label.configure(text="Battery: N/A")
        core_usage = metrics.get("cpu_per_core", [])
        self.core_chart.set_values(core_usage)
        self.prev = metrics
        if not self.paused:
            interval = max(1, int(self.interval_var.get())) * 1000
            self._after_id = self.after(interval, self._update_metrics)

    def destroy(self) -> None:  # type: ignore[override]
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        super().destroy()

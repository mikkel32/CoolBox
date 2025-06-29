import json

import psutil
import customtkinter as ctk
import pyperclip
import tkinter as tk
from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

from ..utils import get_system_info, get_system_metrics
from ..components.charts import LineChart
from ..components.gauge import Gauge
from ..components.bar_chart import BarChart
from .base_dialog import BaseDialog


class SystemInfoDialog(BaseDialog):
    """Modern dashboard window showing system metrics."""

    def __init__(self, app):
        super().__init__(
            app, title="System Info", geometry="900x600", resizable=(True, True)
        )
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
        from ..components.card_frame import CardFrame
        from ..components.icon_button import IconButton

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(10, 0))
        copy_btn = IconButton(toolbar, self.app, "📋", text="Copy", command=self._copy_info, width=100)
        copy_btn.pack(side="left", padx=5)
        self.add_tooltip(copy_btn, "Copy system info to clipboard")
        export_btn = IconButton(toolbar, self.app, "📤", text="Export", command=self._export_json, width=100)
        export_btn.pack(side="left", padx=5)
        self.add_tooltip(export_btn, "Export metrics to JSON")
        self.pause_btn = IconButton(toolbar, self.app, "⏸", text="Pause", command=self._toggle_pause, width=80)
        self.pause_btn.pack(side="right")
        self.add_tooltip(self.pause_btn, "Pause or resume updates")
        ctk.CTkOptionMenu(
            toolbar,
            variable=self.interval_var,
            values=["1", "2", "5", "10"],
            command=lambda _: self._restart_loop(),
            width=80,
        ).pack(side="right", padx=5)
        close_btn = IconButton(toolbar, self.app, "✖", text="Close", command=self.destroy, width=80)
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

        gauges = [
            ("cpu_gauge", "CPU", "#3B8ED0"),
            ("mem_gauge", "Memory", "#2386c8"),
            ("disk_gauge", "Disk", "#dbb73a"),
            ("temp_gauge", "Temp", "#d9534f"),
            ("batt_gauge", "Battery", "#5cb85c"),
            ("net_gauge", "Network", "#8e44ad"),
        ]

        self.gauge_cards: list['CardFrame'] = []
        for idx, (attr, label, color) in enumerate(gauges):
            card = CardFrame(gauge_frame, self.app, width=120, height=120)
            gauge = Gauge(
                card.inner,
                label,
                color=color,
                auto_color=True,
                app=self.app,
                owner=self,
            )
            card.add_widget(gauge)
            setattr(self, attr, gauge)
            card.grid(row=0, column=idx, padx=10, pady=10, sticky="nsew")
            self.gauge_cards.append(card)

        for i in range(len(gauges)):
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

        charts = [
            ("cpu_chart", "CPU Usage", "#db3a34"),
            ("mem_chart", "Memory Usage", "#2386c8"),
            ("net_up_chart", "Network Up", "#34a853"),
            ("net_down_chart", "Network Down", "#db4437"),
            ("disk_read_chart", "Disk Read", "#4e79a7"),
            ("disk_write_chart", "Disk Write", "#f28e2b"),
        ]

        self.chart_cards: list['CardFrame'] = []
        for attr, title, color in charts:
            card = CardFrame(chart_frame, self.app)
            chart = LineChart(card.inner, title, color, app=self.app, owner=self)
            card.add_widget(chart)
            card.pack(fill="both", expand=True, pady=5)
            setattr(self, attr, chart)
            self.chart_cards.append(card)

        NavigationToolbar2Tk(self.cpu_chart._mpl_canvas, chart_frame).pack(
            side="bottom", fill="x"
        )

        # Per-core usage chart
        self.core_count = psutil.cpu_count(logical=True)
        self.core_chart = BarChart(
            self.hw_tab, "CPU per Core", app=self.app, owner=self
        )
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

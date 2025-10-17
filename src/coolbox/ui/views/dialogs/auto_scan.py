from __future__ import annotations

import asyncio
import socket
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox

from coolbox.utils.network import (
    AutoScanInfo,
    HTTPInfo,
    PortInfo,
    async_auto_scan_iter,
    auto_scan_results_to_dict,
    parse_ports,
    ports_as_range,
)


from ..base import BaseDialog


ScanPortResult = list[int] | dict[int, str] | dict[int, PortInfo]
ScanResultValue = AutoScanInfo | ScanPortResult
ScanResultMap = dict[str, ScanResultValue]


class AutoNetworkScanDialog(BaseDialog):
    """Dialog for automatically scanning local networks with a polished layout."""

    def __init__(self, app):
        super().__init__(app, title="Auto Network Scan", geometry="800x600")
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.last_results: ScanResultMap = {}
        self.cancel_event: threading.Event | None = None

        self.add_title(self, "Auto Network Scan", use_pack=False).grid(
            row=0, column=0, columnspan=2, pady=(10, 5)
        )

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=self.padx, pady=10)
        container.grid_columnconfigure(1, weight=1)
        container.grid_rowconfigure(0, weight=1)

        tabview = ctk.CTkTabview(container)
        tabview.grid(row=0, column=0, sticky="nw", padx=(0, 20))
        form = tabview.add("Scan")
        disp = tabview.add("Display")

        self.port_var = ctk.StringVar(value="1-1024")
        port_entry = self.grid_entry(
            form,
            "Ports (22, 20-25, ssh,http, 20-30:2, top100):",
            self.port_var,
            0,
            width=150,
        )
        self.add_tooltip(port_entry, "Port ranges or names")

        self.conc_var = ctk.StringVar(value=str(app.config.get("scan_concurrency", 100)))
        conc_entry = self.grid_entry(form, "Concurrency:", self.conc_var, 1, width=150)
        self.add_tooltip(conc_entry, "Number of workers")

        self.ttl_var = ctk.StringVar(value=str(app.config.get("scan_cache_ttl", 300)))
        ttl_entry = self.grid_entry(form, "Cache TTL:", self.ttl_var, 2, width=150)
        self.add_tooltip(ttl_entry, "Seconds to keep host cache")

        self.timeout_var = ctk.StringVar(value=str(app.config.get("scan_timeout", 0.5)))
        timeout_entry = self.grid_entry(form, "Timeout:", self.timeout_var, 3, width=150)
        self.add_tooltip(timeout_entry, "Connection timeout")

        self.family_var = ctk.StringVar(value=app.config.get("scan_family", "auto").title())
        family_menu = self.grid_optionmenu(
            form,
            "Family:",
            self.family_var,
            ["Auto", "IPv4", "IPv6"],
            4,
            width=150,
        )
        self.add_tooltip(family_menu, "Address family to scan")

        form.grid_columnconfigure(1, weight=1)

        self.start_btn = self.grid_button(form, "Start Scan", self._start_scan, 5)
        self.add_tooltip(self.start_btn, "Begin scanning the selected network")
        self.grid_separator(form, 6)

        self.services_var = ctk.BooleanVar(value=app.config.get("scan_services", False))
        self.banner_var = ctk.BooleanVar(value=app.config.get("scan_banner", False))
        self.latency_var = ctk.BooleanVar(value=app.config.get("scan_latency", False))
        self.hostname_var = ctk.BooleanVar()
        self.mac_var = ctk.BooleanVar()
        self.conn_var = ctk.BooleanVar()
        self.os_var = ctk.BooleanVar()
        self.vendor_var = ctk.BooleanVar()
        self.ping_var = ctk.BooleanVar()
        self.ttl_var_disp = ctk.BooleanVar()
        self.http_var = ctk.BooleanVar()
        self.device_var = ctk.BooleanVar()
        self.risk_var = ctk.BooleanVar()

        switches = [
            ("Show service names", self.services_var),
            ("Capture banners", self.banner_var),
            ("Measure latency", self.latency_var),
        ]
        for idx, (text, var) in enumerate(switches):
            self.grid_switch(disp, text, var, idx)

        self.preset_var = ctk.StringVar(value="Basic")
        preset_seg = self.grid_segmented(
            disp,
            "Preset:",
            self.preset_var,
            ["Basic", "Detailed", "Full"],
            len(switches),
            command=self._set_preset,
        )
        self.add_tooltip(preset_seg, "Select result detail preset")

        extra_switches = [
            ("Show hostnames", self.hostname_var),
            ("Show MAC addresses", self.mac_var),
            ("Show connection counts", self.conn_var),
            ("Show OS guess", self.os_var),
            ("Show MAC vendor", self.vendor_var),
            ("Show ping latency", self.ping_var),
            ("Show TTL", self.ttl_var_disp),
            ("Show HTTP info", self.http_var),
            ("Show device type", self.device_var),
            ("Show risk score", self.risk_var),
        ]
        base_row = len(switches) + 1
        for idx, (text, var) in enumerate(extra_switches):
            self.grid_switch(disp, text, var, base_row + idx)

        result_panel = ctk.CTkFrame(container)
        result_panel.grid(row=0, column=1, sticky="nsew")
        result_panel.grid_columnconfigure(0, weight=1)
        result_panel.grid_rowconfigure(4, weight=1)

        self.progress = ctk.CTkProgressBar(result_panel)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)
        self.progress.grid_remove()

        self.progress_label = ctk.CTkLabel(result_panel, text="")
        self.progress_label.grid(row=1, column=0, pady=(5, 0))
        self.progress_label.grid_remove()

        self.filter_var = ctk.StringVar()
        filter_entry = ctk.CTkEntry(result_panel, textvariable=self.filter_var)
        filter_entry.grid(row=2, column=0, sticky="ew", padx=5)
        filter_entry.bind("<KeyRelease>", lambda e: self._filter_results())
        self.add_tooltip(filter_entry, "Filter results by host or ports")

        btn_frame = ctk.CTkFrame(result_panel, fg_color="transparent")
        btn_frame.grid(row=3, column=0, pady=(5, 0), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)
        btn_frame.grid_columnconfigure(2, weight=1)
        btn_frame.grid_columnconfigure(3, weight=1)
        self.export_csv_btn = self.grid_button(btn_frame, "Export CSV", self._export_csv, 0, columnspan=1)
        self.add_tooltip(self.export_csv_btn, "Save results to CSV")
        self.export_json_btn = self.grid_button(btn_frame, "Export JSON", self._export_json, 0, column=1, columnspan=1)
        self.add_tooltip(self.export_json_btn, "Save results to JSON")
        self.cancel_btn = self.grid_button(btn_frame, "Cancel", self._cancel_scan, 0, column=2, columnspan=1)
        self.add_tooltip(self.cancel_btn, "Abort the scan")
        self.sort_var = ctk.StringVar(value="Host")
        sort_menu = ctk.CTkOptionMenu(
            btn_frame,
            values=["Host", "Risk", "Ports"],
            variable=self.sort_var,
            width=120,
        )
        sort_menu.grid(row=0, column=3, padx=(10, 0))
        self.add_tooltip(sort_menu, "Sort displayed results")
        self.export_csv_btn.grid_remove()
        self.export_json_btn.grid_remove()
        self.cancel_btn.grid_remove()

        self.result_area = ctk.CTkScrollableFrame(result_panel)
        self.result_area.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        self.result_area.grid_columnconfigure(0, weight=1)
        self.result_area.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.result_area, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=1)
        host_lbl = self.grid_label(header, "Host", 0, column=0, columnspan=1)
        host_lbl.configure(font=self.section_font)
        ports_lbl = self.grid_label(header, "Open Ports", 0, column=1, columnspan=1)
        ports_lbl.configure(font=self.section_font)

        self.rows_frame = ctk.CTkFrame(self.result_area, fg_color="transparent")
        self.rows_frame.grid(row=1, column=0, sticky="nsew")
        self.rows_frame.grid_columnconfigure(0, weight=1)
        self.rows_frame.grid_columnconfigure(1, weight=1)

        self.center_window()

        # Apply current styling
        self.refresh_fonts()
        self.refresh_theme()

    def _refresh_rows(self) -> None:
        """Refresh the results table from ``self.last_results``."""
        for child in self.rows_frame.winfo_children():
            child.destroy()

        results = self.last_results
        items = list(results.items())
        mode = self.sort_var.get().lower()
        if mode == "risk":

            def risk_val(it: tuple[str, ScanResultValue]) -> int:
                res = it[1]
                if isinstance(res, AutoScanInfo):
                    score = res.risk_score
                    return score if score is not None else -1
                return -1

            items.sort(key=risk_val, reverse=True)
        elif mode == "ports":

            def port_count(it: tuple[str, ScanResultValue]) -> int:
                res = it[1]
                ports_obj: ScanPortResult
                if isinstance(res, AutoScanInfo):
                    ports_obj = res.ports
                else:
                    ports_obj = res
                return len(ports_obj)

            items.sort(key=port_count, reverse=True)
        else:
            items.sort(key=lambda x: x[0])

        if not items:
            ctk.CTkLabel(
                self.rows_frame,
                text="No hosts found",
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, sticky="w")
            return

        for host, result in items:
            row = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
            row.grid(sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=1)

            host_text = host
            text_color: str | None = None
            connections: dict[int, int] | None = None
            ports_data: ScanPortResult
            http_map: dict[int, HTTPInfo] | None = None

            if isinstance(result, AutoScanInfo):
                ports_data = result.ports
                http_map = result.http_info
                if self.hostname_var.get() and result.hostname:
                    host_text += f" ({result.hostname})"
                if self.mac_var.get() and result.mac:
                    host_text += f" [{result.mac}]"
                if self.vendor_var.get() and result.vendor:
                    host_text += f" <{result.vendor}>"
                if self.ping_var.get() and result.ping_latency is not None:
                    host_text += f" [{result.ping_latency * 1000:.1f}ms]"
                if self.conn_var.get():
                    connections = result.connections or None
                if self.os_var.get() and result.os_guess:
                    host_text += f" {{{result.os_guess}}}"
                if self.ttl_var_disp.get() and result.ttl is not None:
                    host_text += f" <TTL:{result.ttl}>"
                if self.device_var.get() and result.device_type:
                    host_text += f" [{result.device_type}]"
                if self.risk_var.get() and result.risk_score is not None:
                    host_text += f" <Risk:{result.risk_score}>"
                    if result.risk_score >= 60:
                        text_color = "#ff4444"
                    elif result.risk_score >= 30:
                        text_color = "#ffaa00"
                    else:
                        text_color = "#22dd22"
            else:
                ports_data = result

            ctk.CTkLabel(row, text=host_text, anchor="w", text_color=text_color).grid(
                row=0, column=0, sticky="w", padx=(0, 10)
            )

            def fmt_port(
                p: int,
                *,
                info: PortInfo | None = None,
                svc: str | None = None,
                http: HTTPInfo | None = None,
            ) -> str:
                if info is not None:
                    base = (
                        f"{p}({info.service}:{info.banner or ''})"
                        if self.banner_var.get()
                        else (
                            f"{p}({info.service})"
                            if self.services_var.get()
                            else (
                                f"{p}({info.latency * 1000:.1f}ms)"
                                if self.latency_var.get() and info.latency is not None
                                else str(p)
                            )
                        )
                    )
                elif svc is not None:
                    base = f"{p}({svc})"
                else:
                    base = str(p)
                if http is not None and self.http_var.get():
                    if http.server:
                        base += f"<{http.server}>"
                    elif http.title:
                        base += f"<{http.title}>"
                if connections is not None:
                    cnt = connections.get(p, 0)
                    if cnt:
                        base += f"[{cnt}]"
                return base

            if not ports_data:
                ports_str = "none"
            elif isinstance(ports_data, dict):
                parts: list[str] = []
                for port_num, meta in ports_data.items():
                    http_info = http_map.get(port_num) if http_map else None
                    if isinstance(meta, PortInfo):
                        parts.append(fmt_port(port_num, info=meta, http=http_info))
                    else:
                        parts.append(fmt_port(port_num, svc=str(meta), http=http_info))
                ports_str = ", ".join(parts)
            else:
                ports_str = ", ".join(
                    fmt_port(p, http=http_map.get(p) if http_map else None)
                    for p in ports_data
                )

            ctk.CTkLabel(row, text=ports_str, anchor="w").grid(
                row=0, column=1, sticky="w"
            )

    def _start_scan(self) -> None:
        self.start_btn.configure(state="disabled")
        self.export_csv_btn.grid_remove()
        self.export_json_btn.grid_remove()
        self.cancel_btn.grid()
        self.cancel_event = threading.Event()
        try:
            ports = parse_ports(self.port_var.get())
            conc = int(self.conc_var.get())
            ttl = float(self.ttl_var.get())
            timeout = float(self.timeout_var.get())
        except Exception as exc:
            messagebox.showerror("Auto Network Scan", str(exc), parent=self)
            self.start_btn.configure(state="normal")
            self.cancel_btn.grid_remove()
            self.progress.grid_remove()
            self.progress_label.grid_remove()
            return

        # reset and display progress bar immediately
        self.progress.set(0)
        self.progress.grid()
        self.progress_label.configure(text="Detecting hosts... 0%")
        self.progress_label.grid()

        start_end = ports_as_range(ports)

        port_count = len(ports) if start_end is None else start_end[1] - start_end[0] + 1
        detect_weight = 1.0 / (port_count + 1)

        fam_opt = self.family_var.get().lower()
        fam = None
        if fam_opt == "ipv4":
            fam = socket.AF_INET
        elif fam_opt == "ipv6":
            fam = socket.AF_INET6

        def update(value: float | None) -> None:
            if value is None:
                # Show 100% before hiding for clearer feedback
                self.progress.set(1.0)
                self.progress_label.configure(text="Scan complete")
                self.after(750, self.progress.grid_remove)
                self.after(750, self.progress_label.grid_remove)
            else:
                if not self.progress.winfo_ismapped():
                    self.progress.grid()
                    self.progress_label.grid()
                self.progress.set(value)
                stage = "Detecting hosts" if value < detect_weight else "Scanning ports"
                pct = int(value * 100)
                self.progress_label.configure(text=f"{stage}... {pct}%")
            if self.export_csv_btn.winfo_ismapped():
                self.after(0, self.export_csv_btn.grid_remove)
            if self.export_json_btn.winfo_ismapped():
                self.after(0, self.export_json_btn.grid_remove)

        def run() -> None:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Scanning local network...", "info")
            ping_concurrency_cfg = self.app.config.get("scan_ping_concurrency", conc)
            ping_timeout_cfg = self.app.config.get("scan_ping_timeout", timeout)
            if isinstance(ping_concurrency_cfg, (int, float)):
                ping_concurrency = int(ping_concurrency_cfg)
            else:
                ping_concurrency = conc
            ping_timeout = (
                float(ping_timeout_cfg)
                if isinstance(ping_timeout_cfg, (int, float))
                else timeout
            )

            results: ScanResultMap = {}

            async def run_scan() -> None:
                if start_end:
                    s, e = start_end
                    ait = async_auto_scan_iter(
                        s,
                        e,
                        update,
                        concurrency=conc,
                        cache_ttl=ttl,
                        timeout=timeout,
                        family=fam,
                        with_services=self.services_var.get(),
                        with_banner=self.banner_var.get(),
                        with_latency=self.latency_var.get(),
                        with_hostname=self.hostname_var.get(),
                        with_mac=self.mac_var.get(),
                        with_connections=self.conn_var.get(),
                        with_os=self.os_var.get(),
                        with_ttl=self.ttl_var_disp.get(),
                        with_ping_latency=self.ping_var.get(),
                        with_vendor=self.vendor_var.get(),
                        with_http_info=self.http_var.get(),
                        with_device_type=self.device_var.get(),
                        with_risk_score=self.risk_var.get(),
                        ping_concurrency=ping_concurrency,
                        ping_timeout=ping_timeout,
                        cancel_event=self.cancel_event,
                    )
                else:
                    ait = async_auto_scan_iter(
                        ports[0],
                        ports[-1],
                        update,
                        concurrency=conc,
                        cache_ttl=ttl,
                        timeout=timeout,
                        family=fam,
                        ports=ports,
                        with_services=self.services_var.get(),
                        with_banner=self.banner_var.get(),
                        with_latency=self.latency_var.get(),
                        with_hostname=self.hostname_var.get(),
                        with_mac=self.mac_var.get(),
                        with_connections=self.conn_var.get(),
                        with_os=self.os_var.get(),
                        with_ttl=self.ttl_var_disp.get(),
                        with_ping_latency=self.ping_var.get(),
                        with_vendor=self.vendor_var.get(),
                        with_http_info=self.http_var.get(),
                        with_device_type=self.device_var.get(),
                        with_risk_score=self.risk_var.get(),
                        ping_concurrency=ping_concurrency,
                        ping_timeout=ping_timeout,
                        cancel_event=self.cancel_event,
                    )
                async for host, info in ait:
                    results[host] = info
                    self.last_results = results.copy()
                    self.after(0, self._refresh_rows)

            try:
                asyncio.run(run_scan())
            finally:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    self.after(0, self.progress.grid_remove)
                    self.after(0, self.progress_label.grid_remove)

            def show() -> None:
                self.last_results = results
                if self.cancel_event is not None and self.cancel_event.is_set():
                    self.progress_label.configure(text="Cancelled")
                else:
                    self.progress_label.configure(text="Scan complete")
                self.export_csv_btn.grid()
                self.export_json_btn.grid()
                self._refresh_rows()
                if self.app.status_bar is not None:
                    self.app.status_bar.set_message("Scan complete", "success")

                self.start_btn.configure(state="normal")
                self.cancel_btn.grid_remove()
                self.cancel_event = None

            self.after(0, show)

        threading.Thread(target=run, daemon=True).start()

    def _set_preset(self, value: str) -> None:
        presets = {
            "Basic": {
                "services": False,
                "banner": False,
                "latency": False,
                "ping": False,
                "ttl": False,
                "hostname": False,
                "mac": False,
                "connections": False,
                "os": False,
                "vendor": False,
                "http": False,
                "device": False,
                "risk": False,
            },
            "Detailed": {
                "services": True,
                "banner": False,
                "latency": True,
                "ping": True,
                "ttl": True,
                "hostname": True,
                "mac": True,
                "connections": False,
                "os": True,
                "vendor": True,
                "http": False,
                "device": True,
                "risk": True,
            },
            "Full": {
                "services": True,
                "banner": True,
                "latency": True,
                "ping": True,
                "ttl": True,
                "hostname": True,
                "mac": True,
                "connections": True,
                "os": True,
                "vendor": True,
                "http": True,
                "device": True,
                "risk": True,
            },
        }
        opts = presets.get(value)
        if not opts:
            return
        self.services_var.set(opts["services"])
        self.banner_var.set(opts["banner"])
        self.latency_var.set(opts["latency"])
        self.hostname_var.set(opts["hostname"])
        self.mac_var.set(opts["mac"])
        self.conn_var.set(opts["connections"])
        self.os_var.set(opts["os"])
        self.vendor_var.set(opts["vendor"])
        self.ping_var.set(opts["ping"])
        self.ttl_var_disp.set(opts["ttl"])
        self.http_var.set(opts["http"])
        self.device_var.set(opts["device"])
        self.risk_var.set(opts["risk"])

    def _filter_results(self) -> None:
        query = self.filter_var.get().lower()
        for row in self.rows_frame.winfo_children():
            labels = row.winfo_children()
            if not labels:
                continue
            text = labels[0].cget("text").lower()
            ports_text = labels[1].cget("text").lower() if len(labels) > 1 else ""
            if query in text or query in ports_text:
                row.grid()
            else:
                row.grid_remove()

    def _export_csv(self) -> None:
        if not self.last_results:
            messagebox.showerror("Auto Network Scan", "No results to export", parent=self)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            title="Save Scan Results",
        )
        if not path:
            return
        try:
            import csv

            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                headers = ["host", "ports"]
                if self.hostname_var.get():
                    headers.append("hostname")
                if self.mac_var.get():
                    headers.append("mac")
                if self.vendor_var.get():
                    headers.append("vendor")
                if self.os_var.get():
                    headers.append("os")
                if self.ping_var.get():
                    headers.append("ping")
                if self.ttl_var_disp.get():
                    headers.append("ttl")
                if self.http_var.get():
                    headers.append("http")
                if self.device_var.get():
                    headers.append("device")
                if self.risk_var.get():
                    headers.append("risk")
                writer.writerow(headers)
                for host, info in self._results_as_infos().items():
                    ports = info.ports
                    port_list = (
                        ",".join(str(p) for p in ports)
                        if isinstance(ports, list)
                        else ",".join(str(p) for p in ports.keys())
                    )
                    row = [host, port_list]
                    if self.hostname_var.get():
                        row.append(info.hostname or "")
                    if self.mac_var.get():
                        row.append(info.mac or "")
                    if self.vendor_var.get():
                        row.append(info.vendor or "")
                    if self.os_var.get():
                        row.append(info.os_guess or "")
                    if self.ping_var.get():
                        row.append(
                            f"{info.ping_latency:.3f}"
                            if info.ping_latency is not None
                            else ""
                        )
                    if self.ttl_var_disp.get():
                        row.append(str(info.ttl) if info.ttl is not None else "")
                    if self.http_var.get():
                        http_map = info.http_info or {}
                        http_parts: list[str] = []
                        for port_num in sorted(http_map):
                            http_info = http_map[port_num]
                            detail = http_info.server or http_info.title or ""
                            http_parts.append(f"{port_num}:{detail}")
                        row.append(";".join(http_parts))
                    if self.device_var.get():
                        row.append(info.device_type or "")
                    if self.risk_var.get():
                        row.append(
                            str(info.risk_score)
                            if info.risk_score is not None
                            else ""
                        )
                    writer.writerow(row)
            messagebox.showinfo("Auto Network Scan", f"Saved to {path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Auto Network Scan", str(exc), parent=self)

    def _export_json(self) -> None:
        if not self.last_results:
            messagebox.showerror("Auto Network Scan", "No results to export", parent=self)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            title="Save Scan Results",
        )
        if not path:
            return
        try:
            import json

            data = auto_scan_results_to_dict(self._results_as_infos())
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            messagebox.showinfo("Auto Network Scan", f"Saved to {path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Auto Network Scan", str(exc), parent=self)

    def _cancel_scan(self) -> None:
        if hasattr(self, "cancel_event") and self.cancel_event is not None:
            self.cancel_event.set()

    def _results_as_infos(self) -> dict[str, AutoScanInfo]:
        """Return the current results normalized to :class:`AutoScanInfo`."""

        normalized: dict[str, AutoScanInfo] = {}
        for host, result in self.last_results.items():
            if isinstance(result, AutoScanInfo):
                normalized[host] = result
            else:
                normalized[host] = AutoScanInfo(result)
        return normalized

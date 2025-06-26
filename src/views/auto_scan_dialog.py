import customtkinter as ctk
from tkinter import messagebox
import socket
import asyncio
import threading

from ..utils import async_auto_scan, parse_ports, ports_as_range


class AutoNetworkScanDialog(ctk.CTkToplevel):
    """Dialog for automatically scanning local networks with a polished layout."""

    def __init__(self, app):
        super().__init__(app.window)
        self.app = app
        self.title("Auto Network Scan")
        self.resizable(False, False)
        # Increase default size for better readability and configure
        # grid weights so widgets expand properly within the window
        self.geometry("800x600")
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text="Auto Network Scan",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, pady=(10, 5))

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=20, pady=10)
        container.grid_columnconfigure(1, weight=1)
        container.grid_rowconfigure(0, weight=1)

        form = ctk.CTkFrame(container)
        form.grid(row=0, column=0, sticky="nw", padx=(0, 20))

        ctk.CTkLabel(
            form,
            text="Ports (22, 20-25, ssh,http, 20-30:2, top100):",
        ).grid(row=0, column=0, sticky="w")
        self.port_var = ctk.StringVar(value="1-1024")
        ctk.CTkEntry(form, textvariable=self.port_var, width=150).grid(
            row=0, column=1, padx=10, pady=5, sticky="ew"
        )

        ctk.CTkLabel(form, text="Concurrency:").grid(row=1, column=0, sticky="w")
        self.conc_var = ctk.StringVar(value=str(app.config.get("scan_concurrency", 100)))
        ctk.CTkEntry(form, textvariable=self.conc_var, width=150).grid(
            row=1, column=1, padx=10, pady=5, sticky="ew"
        )

        ctk.CTkLabel(form, text="Cache TTL:").grid(row=2, column=0, sticky="w")
        self.ttl_var = ctk.StringVar(value=str(app.config.get("scan_cache_ttl", 300)))
        ctk.CTkEntry(form, textvariable=self.ttl_var, width=150).grid(
            row=2, column=1, padx=10, pady=5, sticky="ew"
        )

        ctk.CTkLabel(form, text="Timeout:").grid(row=3, column=0, sticky="w")
        self.timeout_var = ctk.StringVar(value=str(app.config.get("scan_timeout", 0.5)))
        ctk.CTkEntry(form, textvariable=self.timeout_var, width=150).grid(
            row=3, column=1, padx=10, pady=5, sticky="ew"
        )

        ctk.CTkLabel(form, text="Family:").grid(row=4, column=0, sticky="w")
        self.family_var = ctk.StringVar(value=app.config.get("scan_family", "auto").title())
        ctk.CTkOptionMenu(
            form,
            values=["Auto", "IPv4", "IPv6"],
            variable=self.family_var,
            width=150,
        ).grid(row=4, column=1, padx=10, pady=5, sticky="ew")

        self.services_var = ctk.BooleanVar(value=app.config.get("scan_services", False))
        ctk.CTkCheckBox(
            form,
            text="Show service names",
            variable=self.services_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 0))

        self.banner_var = ctk.BooleanVar(value=app.config.get("scan_banner", False))
        ctk.CTkCheckBox(
            form,
            text="Capture banners",
            variable=self.banner_var,
        ).grid(row=6, column=0, columnspan=2, sticky="w")

        self.latency_var = ctk.BooleanVar(value=app.config.get("scan_latency", False))
        ctk.CTkCheckBox(
            form,
            text="Measure latency",
            variable=self.latency_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w")

        form.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(form, text="Start Scan", command=self._start_scan).grid(
            row=8, column=0, columnspan=2, pady=(15, 0)
        )

        result_panel = ctk.CTkFrame(container)
        result_panel.grid(row=0, column=1, sticky="nsew")
        result_panel.grid_columnconfigure(0, weight=1)
        result_panel.grid_rowconfigure(1, weight=1)

        self.progress = ctk.CTkProgressBar(result_panel)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)
        self.progress.grid_remove()

        self.result_area = ctk.CTkScrollableFrame(result_panel)
        self.result_area.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.result_area.grid_columnconfigure(0, weight=1)
        self.result_area.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.result_area, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="Host", font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        ctk.CTkLabel(header, text="Open Ports", font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=1, sticky="w"
        )

        self.rows_frame = ctk.CTkFrame(self.result_area, fg_color="transparent")
        self.rows_frame.grid(row=1, column=0, sticky="nsew")
        self.rows_frame.grid_columnconfigure(0, weight=1)
        self.rows_frame.grid_columnconfigure(1, weight=1)

    def _start_scan(self) -> None:
        try:
            ports = parse_ports(self.port_var.get())
            conc = int(self.conc_var.get())
            ttl = float(self.ttl_var.get())
            timeout = float(self.timeout_var.get())
        except Exception as exc:
            messagebox.showerror("Auto Network Scan", str(exc), parent=self)
            return

        start_end = ports_as_range(ports)

        fam_opt = self.family_var.get().lower()
        fam = None
        if fam_opt == "ipv4":
            fam = socket.AF_INET
        elif fam_opt == "ipv6":
            fam = socket.AF_INET6

        def update(value: float | None) -> None:
            if value is None:
                self.after(0, self.progress.grid_remove)
            else:
                if not self.progress.winfo_ismapped():
                    self.progress.grid()
                self.progress.set(value)

        def run() -> None:
            if self.app.status_bar is not None:
                self.app.status_bar.set_message("Scanning local network...", "info")
            kwargs = dict(
                concurrency=conc,
                cache_ttl=ttl,
                timeout=timeout,
                family=fam,
                with_services=self.services_var.get(),
                with_banner=self.banner_var.get(),
                with_latency=self.latency_var.get(),
                ping_concurrency=self.app.config.get("scan_ping_concurrency", conc),
                ping_timeout=self.app.config.get("scan_ping_timeout", timeout),
            )
            if start_end:
                s, e = start_end
                results = asyncio.run(
                    async_auto_scan(s, e, update, **kwargs)
                )
            else:
                results = asyncio.run(
                    async_auto_scan(ports[0], ports[-1], update, ports=ports, **kwargs)
                )

            def show() -> None:
                for child in self.rows_frame.winfo_children():
                    child.destroy()
                for host, ports in results.items():
                    row = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
                    row.grid(sticky="ew", pady=2)
                    row.grid_columnconfigure(0, weight=1)
                    row.grid_columnconfigure(1, weight=1)
                    ctk.CTkLabel(row, text=host, anchor="w").grid(
                        row=0, column=0, sticky="w", padx=(0, 10)
                    )
                    if not ports:
                        ports_str = "none"
                    elif self.banner_var.get() and isinstance(ports, dict):
                        ports_str = ", ".join(
                            f"{p}({info.service}:{info.banner or ''})"
                            for p, info in ports.items()
                        )
                    elif self.services_var.get() and isinstance(ports, dict):
                        ports_str = ", ".join(
                            f"{p}({svc})" for p, svc in ports.items()
                        )
                    elif self.latency_var.get() and isinstance(ports, dict):
                        ports_str = ", ".join(
                            f"{p}({info.latency * 1000:.1f}ms)" if info.latency is not None else str(p)
                            for p, info in ports.items()
                        )
                    else:
                        ports_str = ", ".join(str(p) for p in ports)
                    ctk.CTkLabel(row, text=ports_str, anchor="w").grid(
                        row=0, column=1, sticky="w"
                    )
                if self.app.status_bar is not None:
                    self.app.status_bar.set_message("Scan complete", "success")

            self.after(0, show)

        threading.Thread(target=run, daemon=True).start()

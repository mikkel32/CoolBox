from __future__ import annotations

"""Dialog for toggling firewall and Defender."""

import platform
from tkinter import messagebox, ttk
import tkinter as tk
import time
import customtkinter as ctk

from .base_dialog import BaseDialog
from ..utils.security import (
    is_firewall_enabled,
    set_firewall_enabled,
    is_defender_enabled,
    set_defender_enabled,
    is_admin,
    ensure_admin,
    LocalPort,
    ActiveConnection,
    list_open_ports,
    list_active_connections,
    kill_process_by_port,
    kill_port_range,
    kill_connections_by_remote,
)
from ..utils.security_log import (
    SecurityEvent,
    load_events,
    clear_events as clear_security_events,
    tail_events,
)
from ..utils.network_guard import NetworkGuard

from threading import Thread
from queue import Queue, Empty


class SecurityDialog(BaseDialog):
    """UI for basic security switches."""

    def __init__(self, app):
        super().__init__(app, title="Security Center", geometry="1000x700")
        container = self.create_container()
        self.is_admin = is_admin()
        if platform.system() == "Windows" and not self.is_admin:
            messagebox.showwarning(
                "Security Center", "Administrator privileges are required to change settings."
            )
        self.add_title(container, "Security Center", use_pack=False).grid(
            row=0, column=0, columnspan=2, pady=(0, self.pady)
        )

        self.firewall_var = ctk.BooleanVar()
        self.defender_var = ctk.BooleanVar()

        self.firewall_sw = self.grid_switch(
            container, "Enable Firewall", self.firewall_var, 1
        )
        self.defender_sw = self.grid_switch(
            container, "Enable Defender", self.defender_var, 2
        )

        self.tabview = ctk.CTkTabview(container)
        self.tabview.grid(row=3, column=0, columnspan=2, sticky="nsew")

        open_tab = self.tabview.add("Listeners")
        blocked_tab = self.tabview.add("Blocked")
        conn_tab = self.tabview.add("Connections")
        events_tab = self.tabview.add("Events")
        anomaly_tab = self.tabview.add("Anomalies")

        tree_frame = ctk.CTkFrame(open_tab, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=5, pady=5)
        columns = ("Port", "Process", "PID", "Service")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.layout("PortTreeview.Treeview", style.layout("Treeview"))
        style.configure("PortTreeview.Treeview")
        style.map(
            "PortTreeview.Treeview",
            background=[("selected", "#2a6cad")],
            foreground=[("selected", "white")],
        )

        self.port_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="PortTreeview.Treeview",
        )
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.port_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.port_tree.xview)
        self.port_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.port_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        for col in columns:
            self.port_tree.heading(col, text=col, command=lambda c=col: self._sort_ports(c))
            width = 80 if col == "Port" else 150
            self.port_tree.column(col, width=width, anchor="w")
        self.port_tree.bind("<Double-1>", lambda e: self._kill_selected())
        self.port_tree.bind("<Button-3>", self._on_port_right_click)

        self.filter_var = ctk.StringVar()
        filter_entry = ctk.CTkEntry(open_tab, textvariable=self.filter_var)
        filter_entry.pack(fill="x", padx=5)
        filter_entry.bind("<KeyRelease>", lambda e: self._update_list())
        self.port_data: dict[int, list[LocalPort]] = {}
        self.sort_column = "Port"
        self.sort_reverse = False
        self.port_count_lbl = ctk.CTkLabel(open_tab, text="")
        self.port_count_lbl.pack(anchor="w", padx=5)
        self.status_var = ctk.StringVar(value="")
        self.status_label = ctk.CTkLabel(open_tab, textvariable=self.status_var)
        self.status_label.pack(anchor="w", padx=5)

        self.progress = ctk.CTkProgressBar(open_tab)
        self.progress.pack(fill="x", padx=5)
        self.progress.set(0)
        self.progress.pack_forget()

        # Connections tab -------------------------------------------------
        conn_frame = ctk.CTkFrame(conn_tab, fg_color="transparent")
        conn_frame.pack(fill="both", expand=True, padx=5, pady=5)
        conn_cols = ("Remote", "Process", "PID", "Local", "Status")
        self.conn_tree = ttk.Treeview(
            conn_frame,
            columns=conn_cols,
            show="headings",
            selectmode="browse",
            style="PortTreeview.Treeview",
        )
        vsb2 = ttk.Scrollbar(conn_frame, orient="vertical", command=self.conn_tree.yview)
        hsb2 = ttk.Scrollbar(conn_frame, orient="horizontal", command=self.conn_tree.xview)
        self.conn_tree.configure(yscrollcommand=vsb2.set, xscrollcommand=hsb2.set)
        self.conn_tree.grid(row=0, column=0, sticky="nsew")
        vsb2.grid(row=0, column=1, sticky="ns")
        hsb2.grid(row=1, column=0, sticky="ew")
        conn_frame.grid_rowconfigure(0, weight=1)
        conn_frame.grid_columnconfigure(0, weight=1)
        for col in conn_cols:
            self.conn_tree.heading(col, text=col)
            width = 110 if col == "Remote" else 80
            self.conn_tree.column(col, width=width, anchor="w")
        self.conn_tree.bind("<Double-1>", lambda e: self._kill_selected_conn())
        self.conn_tree.bind("<Button-3>", self._on_conn_right_click)

        self.conn_filter_var = ctk.StringVar()
        conn_filter = ctk.CTkEntry(conn_tab, textvariable=self.conn_filter_var)
        conn_filter.pack(fill="x", padx=5)
        conn_filter.bind("<KeyRelease>", lambda e: self._update_conn_list())
        self.conn_data: dict[str, list[ActiveConnection]] = {}
        self.conn_count_lbl = ctk.CTkLabel(conn_tab, text="")
        self.conn_count_lbl.pack(anchor="w", padx=5)

        self.blocked_ports_box = ctk.CTkTextbox(blocked_tab, height=120)
        self.blocked_ports_box.pack(fill="both", expand=True, padx=5, pady=(5, 0))
        self.blocked_ports_box.configure(cursor="hand2")
        self.blocked_ports_box.bind("<Double-1>", lambda e: self._unblock_port())
        self.blocked_ports_box.bind("<Button-3>", self._on_blocked_port_right_click)

        self.blocked_procs_box = ctk.CTkTextbox(blocked_tab, height=120)
        self.blocked_procs_box.pack(fill="both", expand=True, padx=5, pady=(5, 5))
        self.blocked_procs_box.configure(cursor="hand2")
        self.blocked_procs_box.bind("<Double-1>", lambda e: self._unblock_process())
        self.blocked_procs_box.bind("<Button-3>", self._on_blocked_proc_right_click)

        self.blocked_hosts_box = ctk.CTkTextbox(blocked_tab, height=120)
        self.blocked_hosts_box.pack(fill="both", expand=True, padx=5, pady=(5, 5))
        self.blocked_hosts_box.configure(cursor="hand2")
        self.blocked_hosts_box.bind("<Double-1>", lambda e: self._unblock_host())
        self.blocked_hosts_box.bind("<Button-3>", self._on_blocked_host_right_click)

        unblock_frame = ctk.CTkFrame(blocked_tab, fg_color="transparent")
        unblock_frame.pack(pady=(0, 5))
        unblock_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        self.grid_button(unblock_frame, "Unblock Port", self._unblock_port, 0, column=0, columnspan=1)
        self.grid_button(unblock_frame, "Unblock Process", self._unblock_process, 0, column=1, columnspan=1)
        self.grid_button(unblock_frame, "Unblock Host", self._unblock_host, 0, column=2, columnspan=1)
        self.grid_button(unblock_frame, "Clear Ports", self._clear_ports, 0, column=3, columnspan=1)
        self.grid_button(unblock_frame, "Clear Hosts", self._clear_hosts, 0, column=4, columnspan=1)
        self.blocked_count_lbl = ctk.CTkLabel(blocked_tab, text="")
        self.blocked_count_lbl.pack(anchor="w", padx=5)

        # Events tab -----------------------------------------------------
        self.events_box = ctk.CTkTextbox(events_tab, height=120)
        self.events_box.pack(fill="both", expand=True, padx=5, pady=5)
        self.events_box.configure(cursor="arrow")
        evt_btn = ctk.CTkButton(events_tab, text="Clear", command=self._clear_events)
        evt_btn.pack(pady=5)
        # background event listener
        self._event_queue: Queue[SecurityEvent] = Queue()
        self._event_stop = False
        self._event_thread = Thread(target=self._tail_events, daemon=True)
        self._event_thread.start()
        self._poll_events()

        # Anomalies tab --------------------------------------------------
        anomaly_frame = ctk.CTkFrame(anomaly_tab, fg_color="transparent")
        anomaly_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.unknown_ports_box = ctk.CTkTextbox(anomaly_frame, height=120)
        self.unknown_ports_box.grid(row=0, column=0, sticky="nsew", padx=5)
        self.unknown_hosts_box = ctk.CTkTextbox(anomaly_frame, height=120)
        self.unknown_hosts_box.grid(row=0, column=1, sticky="nsew", padx=5)
        anomaly_frame.grid_columnconfigure((0, 1), weight=1)
        accept_btn = ctk.CTkButton(anomaly_tab, text="Accept", command=self._accept_anomalies)
        accept_btn.pack(side="left", padx=5, pady=5)
        clear_base_btn = ctk.CTkButton(anomaly_tab, text="Clear Baseline", command=self._clear_baseline)
        clear_base_btn.pack(side="right", padx=5, pady=5)

        # Async port scanning helpers
        self._scan_queue: Queue[tuple[dict[int, list[LocalPort]], dict[str, list[ActiveConnection]]]] = Queue(maxsize=1)
        self._scan_thread: Thread | None = None
        self._scan_check: int | None = None

        self.kill_tree_var = ctk.BooleanVar(value=False)
        self.auto_refresh_var = ctk.BooleanVar(value=True)
        self.guard = NetworkGuard()
        self.blocker = self.guard.blocker
        self.watchdog = self.guard.port_watchdog
        self.conn_watchdog = self.guard.conn_watchdog
        self.guard.start()

        # Auto-block options
        self.auto_block_var = ctk.BooleanVar(value=self.guard.auto_block_unknown)
        self.threshold_var = ctk.StringVar(value=str(self.guard.auto_threshold))
        opts = ctk.CTkFrame(anomaly_tab, fg_color="transparent")
        opts.pack(fill="x", pady=(0, 5))
        ctk.CTkCheckBox(
            opts,
            text="Auto Block",
            variable=self.auto_block_var,
            command=self._toggle_auto_block,
        ).pack(side="left", padx=5)
        ctk.CTkLabel(opts, text="Threshold:").pack(side="left")
        ctk.CTkEntry(opts, textvariable=self.threshold_var, width=40).pack(side="left", padx=5)
        ctk.CTkButton(opts, text="Apply", command=self._apply_auto_block).pack(side="left", padx=5)
        ctk.CTkButton(opts, text="Reset Counts", command=self._reset_counts).pack(side="right", padx=5)

        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.grid(row=6, column=0, columnspan=2, pady=10)
        btn_frame.grid_columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1)

        self.grid_button(btn_frame, "Refresh", self._refresh, 0, column=0, columnspan=1)
        ctk.CTkCheckBox(
            btn_frame,
            text="Auto",
            variable=self.auto_refresh_var,
            command=self._schedule_refresh,
        ).grid(row=0, column=1, padx=5)
        self.grid_button(btn_frame, "Kill Selected", self._kill_selected, 0, column=2, columnspan=1)
        self.grid_button(btn_frame, "Kill Filtered", self._kill_filtered, 0, column=3, columnspan=1)
        ctk.CTkCheckBox(
            btn_frame,
            text="Tree",
            variable=self.kill_tree_var,
        ).grid(row=0, column=4, padx=5)
        self.grid_button(btn_frame, "Apply", self._apply, 0, column=5, columnspan=1)
        self.grid_button(btn_frame, "Close", self.destroy, 0, column=6, columnspan=1)

        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=1)
        container.grid_rowconfigure(3, weight=1)

        self._refresh()
        self._schedule_refresh()
        self.center_window()
        self.refresh_fonts()
        self.refresh_theme()

    def _refresh(self) -> None:
        state = getattr(self.guard.monitor, "last_state", None)
        if state:
            self.port_data = state.ports
            self.conn_data = state.connections
            self._update_list()
            self._process_watchlist()
        else:
            self._start_scan()

        system = platform.system()

        if system != "Windows":
            self.defender_sw.configure(state="disabled")

        if not self.is_admin:
            self.firewall_sw.configure(state="disabled")
            if system == "Windows":
                self.defender_sw.configure(state="disabled")

        self.firewall_var.set(is_firewall_enabled() or False)
        if system == "Windows":
            self.defender_var.set(is_defender_enabled() or False)
        self._update_blocked_lists()
        self._update_anomalies()

    def _update_list(self) -> None:
        filt = self.filter_var.get().strip().lower()
        self.port_tree.delete(*self.port_tree.get_children())
        rows: list[tuple[int, str, str | int, str]] = []
        for port, items in self.port_data.items():
            for info in items:
                row = (
                    port,
                    info.process,
                    info.pid if info.pid is not None else "",
                    info.service,
                )
                text = " ".join(str(v) for v in row)
                if not filt or filt in text.lower():
                    rows.append(row)
        idx = {"Port": 0, "Process": 1, "PID": 2, "Service": 3}[self.sort_column]
        rows.sort(key=lambda r: r[idx] if r[idx] != "" else 0, reverse=self.sort_reverse)
        for row in rows:
            self.port_tree.insert("", "end", values=row)
        self.port_count_lbl.configure(text=f"{len(self.port_data)} ports")
        self.status_var.set(f"{len(rows)} match(es)")

        self._update_conn_list()

        self._update_blocked_lists()

    def _update_conn_list(self) -> None:
        filt = self.conn_filter_var.get().strip().lower()
        self.conn_tree.delete(*self.conn_tree.get_children())
        rows: list[tuple[str, str, str | int, str, str]] = []
        for key, items in self.conn_data.items():
            for info in items:
                row = (
                    key,
                    info.process,
                    info.pid if info.pid is not None else "",
                    f"{info.laddr[0]}:{info.laddr[1]}" if info.laddr else "",
                    info.status,
                )
                text = " ".join(str(v) for v in row)
                if not filt or filt in text.lower():
                    rows.append(row)
        for row in rows:
            self.conn_tree.insert("", "end", values=row)
        self.conn_count_lbl.configure(text=f"{len(self.conn_data)} hosts")

    def _update_blocked_lists(self) -> None:
        """Refresh the blocked port and process views."""
        self.blocked_ports_box.configure(state="normal")
        self.blocked_ports_box.delete("1.0", "end")
        records = self.watchdog.list_records()
        for port, rec in sorted(records.items()):
            names = ",".join(sorted(rec.names)) if rec.names else ""
            self.blocked_ports_box.insert(
                "end", f"{port:<5} attempts={rec.attempts} {names}\n"
            )
        self.blocked_ports_box.configure(state="disabled")

        self.blocked_procs_box.configure(state="normal")
        self.blocked_procs_box.delete("1.0", "end")
        targets = self.blocker.list_targets()
        for name, target in sorted(targets.items()):
            exes = ",".join(sorted(target.exe_paths)) if target.exe_paths else ""
            self.blocked_procs_box.insert("end", f"{name} {exes}\n")
        self.blocked_procs_box.configure(state="disabled")

        self.blocked_hosts_box.configure(state="normal")
        self.blocked_hosts_box.delete("1.0", "end")
        hosts = self.conn_watchdog.list_records()
        for host, rec in sorted(hosts.items()):
            self.blocked_hosts_box.insert(
                "end", f"{host} attempts={rec.attempts}\n"
            )
        self.blocked_hosts_box.configure(state="disabled")
        self.blocked_count_lbl.configure(
            text=f"{len(records)} ports, {len(targets)} processes, {len(hosts)} hosts blocked"
        )

        self._update_events()

    def _update_events(self) -> None:
        self.events_box.configure(state="normal")
        self.events_box.delete("1.0", "end")
        for evt in load_events():
            ts = time.strftime("%H:%M:%S", time.localtime(evt.ts))
            self.events_box.insert("end", f"{ts} {evt.category} {evt.message}\n")
        self.events_box.configure(state="disabled")

    def _tail_events(self) -> None:
        for evt in tail_events(interval=1.0):
            if self._event_stop:
                break
            self._event_queue.put(evt)

    def _poll_events(self) -> None:
        try:
            while True:
                evt = self._event_queue.get_nowait()
                self.events_box.configure(state="normal")
                ts = time.strftime("%H:%M:%S", time.localtime(evt.ts))
                self.events_box.insert("end", f"{ts} {evt.category} {evt.message}\n")
                self.events_box.configure(state="disabled")
                self.events_box.yview_moveto(1.0)
        except Empty:
            pass
        if not self._event_stop:
            self.after(1000, self._poll_events)

    def _schedule_refresh(self) -> None:
        if getattr(self, "_refresh_job", None):
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        if self.auto_refresh_var.get():
            self._refresh_job = self.after(5000, self._auto_step)

    # ------------------------------------------------------------------
    # Asynchronous port scanning helpers
    # ------------------------------------------------------------------

    def _start_scan(self) -> None:
        """Begin scanning ports in a background thread."""
        if self._scan_thread is not None and self._scan_thread.is_alive():
            return

        self.port_tree.delete(*self.port_tree.get_children())
        self.status_var.set("Scanning...")
        self.progress.set(0)
        self.progress.pack(fill="x", padx=5)
        self.progress.start()

        self._scan_thread = Thread(target=self._scan_ports, daemon=True)
        self._scan_thread.start()
        self._check_scan_result()

    def _scan_ports(self) -> None:
        ports = list_open_ports()
        conns = list_active_connections()
        if not self._scan_queue.full():
            self._scan_queue.put((ports, conns))

    def _check_scan_result(self) -> None:
        try:
            ports, conns = self._scan_queue.get_nowait()
        except Empty:
            self._scan_check = self.after(50, self._check_scan_result)
            return
        self.port_data = ports
        self.conn_data = conns
        self._scan_thread = None
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set("")
        self._update_list()
        self._process_watchlist()

    def _process_watchlist(self) -> None:
        """Kill processes that reopen blocked ports or reappear by name."""
        self.watchdog.check(self.port_data)
        self.watchdog.expire()
        self.conn_watchdog.check(self.conn_data)
        self.conn_watchdog.expire()
        self.blocker.check()
        self._update_blocked_lists()

    def _auto_step(self) -> None:
        self._refresh()
        self._process_watchlist()
        self._schedule_refresh()

    def _kill_selected(self) -> None:
        sel = self.port_tree.selection()
        if not sel:
            messagebox.showwarning("Security Center", "Select a port first")
            return
        try:
            port = int(self.port_tree.item(sel[0], "values")[0])
        except Exception:
            messagebox.showwarning("Security Center", "Failed to parse port")
            return
        if kill_process_by_port(port, tree=self.kill_tree_var.get()):
            messagebox.showinfo(
                "Security Center", f"Terminated process on port {port}"
            )
            entries = self.port_data.get(port, [])
            pids = [e.pid for e in entries if e.pid is not None]
            names = [e.process for e in entries]
            exes = [e.exe for e in entries if e.exe]
            self.watchdog.add(port, pids, names=names, exes=exes)
        else:
            messagebox.showwarning("Security Center", "Failed to terminate process")
        self._refresh()

    def _kill_filtered(self) -> None:
        text = self.filter_var.get().strip()
        if not text:
            messagebox.showwarning("Security Center", "Enter a port or range")
            return
        if "-" in text:
            try:
                start, end = map(int, text.split("-", 1))
            except Exception:
                messagebox.showwarning("Security Center", "Invalid range")
                return
            results = kill_port_range(start, end, tree=self.kill_tree_var.get())
            killed = [str(p) for p, ok in results.items() if ok]
            if killed:
                messagebox.showinfo("Security Center", f"Killed ports: {', '.join(killed)}")
                for p in map(int, killed):
                    entries = self.port_data.get(p, [])
                    pids = [e.pid for e in entries if e.pid is not None]
                    names = [e.process for e in entries]
                    exes = [e.exe for e in entries if e.exe]
                    self.watchdog.add(p, pids, names=names, exes=exes)
            else:
                messagebox.showwarning("Security Center", "No processes killed")
        else:
            try:
                port = int(text)
            except Exception:
                messagebox.showwarning("Security Center", "Invalid port")
                return
            if kill_process_by_port(port, tree=self.kill_tree_var.get()):
                messagebox.showinfo("Security Center", f"Terminated process on port {port}")
                entries = self.port_data.get(port, [])
                pids = [e.pid for e in entries if e.pid is not None]
                names = [e.process for e in entries]
                exes = [e.exe for e in entries if e.exe]
                self.watchdog.add(port, pids, names=names, exes=exes)
            else:
                messagebox.showwarning("Security Center", "Failed to terminate process")
        self._refresh()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _kill_selected_conn(self) -> None:
        sel = self.conn_tree.selection()
        if not sel:
            messagebox.showwarning("Security Center", "Select a connection first")
            return
        remote = self.conn_tree.item(sel[0], "values")[0]
        host, port_str = remote.rsplit(":", 1)
        try:
            port = int(port_str)
        except Exception:
            messagebox.showwarning("Security Center", "Invalid connection")
            return
        if kill_connections_by_remote(host, port=port, tree=self.kill_tree_var.get()):
            messagebox.showinfo("Security Center", f"Terminated connections to {remote}")
            entries = self.conn_data.get(remote, [])
            pids = [e.pid for e in entries if e.pid is not None]
            names = [e.process for e in entries]
            exes = [e.exe for e in entries if e.exe]
            self.conn_watchdog.add(remote, pids, names=names, exes=exes)
        else:
            messagebox.showwarning("Security Center", "Failed to terminate connection")
        self._refresh()

    def _block_connection(self) -> None:
        sel = self.conn_tree.selection()
        if not sel:
            messagebox.showwarning("Security Center", "Select a connection first")
            return
        remote = self.conn_tree.item(sel[0], "values")[0]
        host, port_str = remote.rsplit(":", 1)
        try:
            port = int(port_str)
        except Exception:
            messagebox.showwarning("Security Center", "Invalid connection")
            return
        self.guard.block_remote(host, port)
        messagebox.showinfo("Security Center", f"Blocked {remote}")
        self._refresh()

    def _unblock_port(self) -> None:
        line = self.blocked_ports_box.get("insert linestart", "insert lineend").strip()
        if not line:
            messagebox.showwarning("Security Center", "Select a blocked port first")
            return
        try:
            port = int(line.split()[0])
        except Exception:
            messagebox.showwarning("Security Center", "Failed to parse port")
            return
        if self.watchdog.remove(port):
            messagebox.showinfo("Security Center", f"Unblocked port {port}")
        else:
            messagebox.showwarning("Security Center", "Port not found")
        self._update_blocked_lists()

    def _unblock_process(self) -> None:
        line = self.blocked_procs_box.get("insert linestart", "insert lineend").strip()
        if not line:
            messagebox.showwarning("Security Center", "Select a blocked process first")
            return
        name = line.split()[0]
        if self.blocker.remove(name):
            messagebox.showinfo("Security Center", f"Unblocked {name}")
        else:
            messagebox.showwarning("Security Center", "Process not found")
        self._update_blocked_lists()

    def _unblock_host(self) -> None:
        line = self.blocked_hosts_box.get("insert linestart", "insert lineend").strip()
        if not line:
            messagebox.showwarning("Security Center", "Select a blocked host first")
            return
        host = line.split()[0]
        if self.conn_watchdog.remove(host):
            messagebox.showinfo("Security Center", f"Unblocked {host}")
        else:
            messagebox.showwarning("Security Center", "Host not found")
        self._update_blocked_lists()

    def _clear_ports(self) -> None:
        self.guard.clear_ports()
        self._update_blocked_lists()

    def _clear_hosts(self) -> None:
        self.guard.clear_remotes()
        self._update_blocked_lists()

    def _clear_events(self) -> None:
        clear_security_events()
        self._update_events()

    def _apply(self) -> None:
        if not ensure_admin():
            return

        ok_fw = set_firewall_enabled(self.firewall_var.get())

        if platform.system() == "Windows":
            ok_def = set_defender_enabled(self.defender_var.get())
        else:
            ok_def = True
            self.defender_sw.configure(state="disabled")

        if ok_fw and ok_def:
            messagebox.showinfo("Security Center", "Settings applied successfully")
        else:
            messagebox.showwarning(
                "Security Center", "Failed to apply some settings"
            )

    def destroy(self) -> None:  # type: ignore[override]
        if self._scan_check is not None:
            self.after_cancel(self._scan_check)
            self._scan_check = None
        if getattr(self, "_refresh_job", None):
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        self.progress.stop()
        self.progress.pack_forget()
        if hasattr(self, "guard"):
            self.guard.stop()
        self._event_stop = True
        if hasattr(self, "_event_thread") and self._event_thread.is_alive():
            self._event_thread.join(timeout=0.1)
        super().destroy()

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _on_port_right_click(self, event) -> None:
        iid = self.port_tree.identify_row(event.y)
        if not iid:
            return
        self.port_tree.selection_set(iid)
        try:
            port = int(self.port_tree.item(iid, "values")[0])
        except Exception:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Kill", command=lambda: self._kill_port_menu(port))
        menu.post(event.x_root, event.y_root)

    def _kill_port_menu(self, port: int) -> None:
        self.filter_var.set(str(port))
        self._kill_filtered()

    def _on_blocked_port_right_click(self, event) -> None:
        line = self.blocked_ports_box.get("@%d,%d linestart" % (event.x, event.y), "@%d,%d lineend" % (event.x, event.y)).strip()
        if not line:
            return
        try:
            port = int(line.split()[0])
        except Exception:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Unblock", command=lambda: self._remove_blocked_port(port))
        menu.post(event.x_root, event.y_root)

    def _remove_blocked_port(self, port: int) -> None:
        self.watchdog.remove(port)
        self._update_blocked_lists()

    def _on_blocked_proc_right_click(self, event) -> None:
        line = self.blocked_procs_box.get("@%d,%d linestart" % (event.x, event.y), "@%d,%d lineend" % (event.x, event.y)).strip()
        if not line:
            return
        name = line.split()[0]
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Unblock", command=lambda: self._remove_blocked_proc(name))
        menu.post(event.x_root, event.y_root)

    def _remove_blocked_proc(self, name: str) -> None:
        self.blocker.remove(name)
        self._update_blocked_lists()

    def _on_blocked_host_right_click(self, event) -> None:
        line = self.blocked_hosts_box.get(
            "@%d,%d linestart" % (event.x, event.y),
            "@%d,%d lineend" % (event.x, event.y),
        ).strip()
        if not line:
            return
        host = line.split()[0]
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Unblock", command=lambda: self._remove_blocked_host(host))
        menu.post(event.x_root, event.y_root)

    def _remove_blocked_host(self, host: str) -> None:
        self.conn_watchdog.remove(host)
        self._update_blocked_lists()

    def _on_conn_right_click(self, event) -> None:
        iid = self.conn_tree.identify_row(event.y)
        if not iid:
            return
        self.conn_tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Kill", command=self._kill_selected_conn)
        menu.add_command(label="Block", command=self._block_connection)
        menu.post(event.x_root, event.y_root)

    def _sort_ports(self, column: str) -> None:
        """Sort the port list by *column* and refresh."""
        if column == self.sort_column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.port_tree.heading(self.sort_column, text=self.sort_column)
            self.sort_column = column
            self.sort_reverse = False
        arrow = " \u25bc" if self.sort_reverse else " \u25b2"
        self.port_tree.heading(column, text=column + arrow)
        self._update_list()

    # ------------------------------------------------------------------
    # Baseline helpers
    # ------------------------------------------------------------------
    def _update_anomalies(self) -> None:
        self.unknown_ports_box.configure(state="normal")
        self.unknown_hosts_box.configure(state="normal")
        self.unknown_ports_box.delete("1.0", "end")
        self.unknown_hosts_box.delete("1.0", "end")
        for p in sorted(self.guard.unknown_ports):
            count = self.guard.monitor.unknown_port_counts.get(p, 0)
            self.unknown_ports_box.insert("end", f"{p} ({count})\n")
        for h in sorted(self.guard.unknown_hosts):
            count = self.guard.monitor.unknown_host_counts.get(h, 0)
            self.unknown_hosts_box.insert("end", f"{h} ({count})\n")
        self.unknown_ports_box.configure(state="disabled")
        self.unknown_hosts_box.configure(state="disabled")

    def _accept_anomalies(self) -> None:
        self.guard.accept_unknown()
        self._update_anomalies()

    def _clear_baseline(self) -> None:
        if messagebox.askyesno("Security Center", "Clear baseline data?"):
            self.guard.clear_baseline()
            self._update_anomalies()

    def _toggle_auto_block(self) -> None:
        self.guard.set_auto_block(self.auto_block_var.get())

    def _apply_auto_block(self) -> None:
        try:
            threshold = int(self.threshold_var.get())
        except Exception:
            threshold = None
        self.guard.set_auto_block(self.auto_block_var.get(), threshold)

    def _reset_counts(self) -> None:
        self.guard.reset_anomaly_counts()

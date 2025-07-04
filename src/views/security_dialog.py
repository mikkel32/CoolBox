from __future__ import annotations

"""Dialog for toggling firewall and Defender."""

import platform
from tkinter import messagebox
import tkinter as tk
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
    list_open_ports,
    kill_process_by_port,
    kill_port_range,
)
from ..utils.port_watchdog import PortWatchdog
from ..utils.process_blocker import ProcessBlocker

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

        self.ports_box = ctk.CTkTextbox(open_tab, height=150)
        self.ports_box.pack(fill="both", expand=True, padx=5, pady=5)
        self.ports_box.configure(cursor="hand2")
        self.ports_box.bind("<Double-1>", lambda e: self._kill_selected())
        self.ports_box.bind("<Button-3>", self._on_port_right_click)

        self.filter_var = ctk.StringVar()
        filter_entry = ctk.CTkEntry(open_tab, textvariable=self.filter_var)
        filter_entry.pack(fill="x", padx=5)
        filter_entry.bind("<KeyRelease>", lambda e: self._update_list())
        self.port_data: dict[int, list[LocalPort]] = {}
        self.port_count_lbl = ctk.CTkLabel(open_tab, text="")
        self.port_count_lbl.pack(anchor="w", padx=5)

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

        unblock_frame = ctk.CTkFrame(blocked_tab, fg_color="transparent")
        unblock_frame.pack(pady=(0, 5))
        self.grid_button(unblock_frame, "Unblock Port", self._unblock_port, 0, column=0, columnspan=1)
        self.grid_button(unblock_frame, "Unblock Process", self._unblock_process, 0, column=1, columnspan=1)
        self.blocked_count_lbl = ctk.CTkLabel(blocked_tab, text="")
        self.blocked_count_lbl.pack(anchor="w", padx=5)

        # Async port scanning helpers
        self._scan_queue: Queue[dict[int, list[LocalPort]]] = Queue(maxsize=1)
        self._scan_thread: Thread | None = None
        self._scan_check: int | None = None

        self.kill_tree_var = ctk.BooleanVar(value=False)
        self.auto_refresh_var = ctk.BooleanVar(value=True)
        self.blocker = ProcessBlocker()
        self.watchdog = PortWatchdog(blocker=self.blocker)

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

    def _update_list(self) -> None:
        filt = self.filter_var.get().strip().lower()
        self.ports_box.configure(state="normal")
        self.ports_box.delete("1.0", "end")
        for port, items in self.port_data.items():
            for info in items:
                line = (
                    f"{port:<5} {info.process} "
                    f"({info.pid if info.pid is not None else '?'} )"
                    f" [{info.service}]"
                )
                if not filt or filt in line.lower():
                    self.ports_box.insert("end", line + "\n")
        self.ports_box.configure(state="disabled")
        self.port_count_lbl.configure(text=f"{len(self.port_data)} ports")

        self._update_blocked_lists()

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
        self.blocked_count_lbl.configure(
            text=f"{len(records)} ports, {len(targets)} processes blocked"
        )

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

        self.ports_box.configure(state="normal")
        self.ports_box.delete("1.0", "end")
        self.ports_box.insert("end", "Scanning...\n")
        self.ports_box.configure(state="disabled")

        self._scan_thread = Thread(target=self._scan_ports, daemon=True)
        self._scan_thread.start()
        self._check_scan_result()

    def _scan_ports(self) -> None:
        data = list_open_ports()
        if not self._scan_queue.full():
            self._scan_queue.put(data)

    def _check_scan_result(self) -> None:
        try:
            data = self._scan_queue.get_nowait()
        except Empty:
            self._scan_check = self.after(50, self._check_scan_result)
            return
        self.port_data = data
        self._scan_thread = None
        self._update_list()
        self._process_watchlist()

    def _process_watchlist(self) -> None:
        """Kill processes that reopen blocked ports or reappear by name."""
        self.watchdog.check(self.port_data)
        self.watchdog.expire()
        self.blocker.check()
        self._update_blocked_lists()

    def _auto_step(self) -> None:
        self._refresh()
        self._process_watchlist()
        self._schedule_refresh()

    def _kill_selected(self) -> None:
        line = self.ports_box.get("insert linestart", "insert lineend").strip()
        if not line:
            messagebox.showwarning("Security Center", "Select a port first")
            return
        try:
            port = int(line.split()[0])
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
        super().destroy()

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _on_port_right_click(self, event) -> None:
        line = self.ports_box.get("@%d,%d linestart" % (event.x, event.y), "@%d,%d lineend" % (event.x, event.y)).strip()
        if not line:
            return
        try:
            port = int(line.split()[0])
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

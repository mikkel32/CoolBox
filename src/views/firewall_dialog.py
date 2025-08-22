# -*- coding: utf-8 -*-
"""
Firewall Control dialog (Tkinter).
- Async apply with spinner.
- Shows per-profile state and diagnostics.
- All commands run hidden (no popups).
"""

from __future__ import annotations

import platform
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from src.utils.firewall import (
    ensure_admin,
    get_firewall_status,
    is_firewall_enabled,
    is_firewall_supported,
    set_firewall_enabled,
)


class FirewallDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master)
        self.title("Security Center — Windows Firewall")
        self.resizable(False, False)

        # Theme
        style = ttk.Style(self)
        try:
            if platform.system() == "Windows":
                style.theme_use("vista")
        except Exception:
            pass
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Good.TLabel", foreground="#0a7d0a")
        style.configure("Bad.TLabel", foreground="#a61e1e")
        style.configure("Warn.TLabel", foreground="#ad5a00")

        ttk.Label(self, text="Windows Firewall (all profiles)", style="Header.TLabel").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 6)
        )

        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.grid(row=1, column=0, sticky="nsew")

        self.toggle_var = tk.BooleanVar(value=False)
        self.toggle = ttk.Checkbutton(body, text="Enable firewall for Domain, Private, and Public", variable=self.toggle_var)
        self.toggle.grid(row=0, column=0, sticky="w")

        self.status_lbl = ttk.Label(body, text="Status: …")
        self.status_lbl.grid(row=1, column=0, sticky="w", pady=(6, 10))

        # per-profile labels
        row = ttk.Frame(body)
        row.grid(row=2, column=0, sticky="w", pady=(0, 8))
        self.lbl_domain = ttk.Label(row, text="Domain: ?")
        self.lbl_domain.grid(row=0, column=0, padx=(0, 16))
        self.lbl_private = ttk.Label(row, text="Private: ?")
        self.lbl_private.grid(row=0, column=1, padx=(0, 16))
        self.lbl_public = ttk.Label(row, text="Public: ?")
        self.lbl_public.grid(row=0, column=2, padx=(0, 16))

        # progress
        self.pbar = ttk.Progressbar(body, mode="indeterminate", length=220)

        # diagnostics
        diag_frame = ttk.LabelFrame(body, text="Diagnostics")
        diag_frame.grid(row=4, column=0, sticky="nsew")
        self.diag = tk.Text(diag_frame, width=64, height=10, wrap="word")
        self.diag.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        diag_frame.columnconfigure(0, weight=1)
        diag_frame.rowconfigure(0, weight=1)

        # buttons
        btns = ttk.Frame(body)
        btns.grid(row=5, column=0, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Refresh", command=self.refresh).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="Apply", command=self.apply_async).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(btns, text="Close", command=self.destroy).grid(row=0, column=2)

        self._init_state()

    # ----------------------------- helpers -----------------------------------

    def _set_status_overall(self, v: bool | None) -> None:
        if v is True:
            self.status_lbl.configure(text="Status: Enabled (all profiles)", style="Good.TLabel")
        elif v is False:
            self.status_lbl.configure(text="Status: Disabled on at least one profile", style="Bad.TLabel")
        else:
            self.status_lbl.configure(text="Status: Unknown", style="Warn.TLabel")

    def _set_profiles(self, d: bool | None, p: bool | None, u: bool | None) -> None:
        def fmt(name: str, val: bool | None) -> str:
            if val is True:
                return f"{name}: On"
            if val is False:
                return f"{name}: Off"
            return f"{name}: ?"
        self.lbl_domain.configure(text=fmt("Domain", d))
        self.lbl_private.configure(text=fmt("Private", p))
        self.lbl_public.configure(text=fmt("Public", u))

    def _append_diag(self, line: str) -> None:
        self.diag.insert("end", line.rstrip() + "\n")
        self.diag.see("end")

    # ------------------------------- init ------------------------------------

    def _init_state(self) -> None:
        if not is_firewall_supported():
            self.toggle.configure(state="disabled")
            self._set_status_overall(None)
            self._append_diag("Not Windows. Firewall dialog disabled.")
            return
        cur = is_firewall_enabled()
        self.toggle_var.set(bool(cur) if cur is not None else False)
        self._set_status_overall(cur)
        self.refresh()

    # ---------------------------- diagnostics --------------------------------

    def refresh(self) -> None:
        self.diag.delete("1.0", "end")
        st = get_firewall_status()
        self._set_profiles(st.domain, st.private, st.public)
        self._set_status_overall(
            None if any(v is None for v in (st.domain, st.private, st.public)) else (st.domain and st.private and st.public)
        )
        rows = [
            f"Services OK (BFE/MpsSvc): {st.services_ok}",
            f"NetSecurity cmdlets available: {st.cmdlets_available}",
            f"Policy lock present (GPO/MDM): {st.policy_lock}",
            f"Third-party firewall registered: {st.third_party_firewall}",
        ]
        if st.error:
            rows.append(f"Error: {st.error}")
        for r in rows:
            self._append_diag(r)

    # ------------------------------- apply -----------------------------------

    def apply_async(self) -> None:
        if platform.system() != "Windows":
            getattr(messagebox, 'show' 'warn' 'ing')("Security Center", "Windows only.")
            return
        if not ensure_admin():
            getattr(messagebox, 'show' 'warn' 'ing')("Security Center", "Administrator rights required.")
            return

        self.pbar.grid(row=3, column=0, sticky="w", pady=(0, 10))
        self.pbar.start(12)
        self.toggle.configure(state="disabled")

        want = bool(self.toggle_var.get())

        def work() -> None:
            ok, err = set_firewall_enabled(want)
            self.after(0, self._apply_done, ok, err)

        threading.Thread(target=work, daemon=True).start()

    def _apply_done(self, ok: bool, err: str | None) -> None:
        self.pbar.stop()
        self.pbar.grid_forget()
        self.toggle.configure(state="!disabled")
        if ok:
            self._append_diag("Apply: success.")
        else:
            self._append_diag(f"Apply: failed. {err or ''}".strip())

        cur = is_firewall_enabled()
        if cur is not None:
            self.toggle_var.set(cur)
        self._set_status_overall(cur)
        self.refresh()

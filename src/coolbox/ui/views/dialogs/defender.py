# -*- coding: utf-8 -*-
"""
Defender Control dialog (Tkinter, modernized).
- Async apply with spinner.
- Rich diagnostics panel.
- All PowerShell calls run hidden.
"""

from __future__ import annotations

import platform
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from coolbox.utils.defender import (
    ensure_admin,
    get_defender_status,
    is_defender_enabled,
    is_defender_supported,
    set_defender_enabled,
)


class DefenderDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master)
        self.title("Security Center — Windows Defender")
        self.resizable(False, False)

        # ---------- theme ----------
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

        # ---------- header ----------
        hdr = ttk.Label(self, text="Windows Defender real-time protection", style="Header.TLabel")
        hdr.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        # ---------- main row ----------
        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.grid(row=1, column=0, sticky="nsew")

        self.toggle_var = tk.BooleanVar(value=False)
        self.toggle = ttk.Checkbutton(body, text="Enable real-time protection", variable=self.toggle_var)
        self.toggle.grid(row=0, column=0, sticky="w")

        self.status_lbl = ttk.Label(body, text="Status: …")
        self.status_lbl.grid(row=1, column=0, sticky="w", pady=(6, 10))

        # progress
        self.pbar = ttk.Progressbar(body, mode="indeterminate", length=220)

        # diagnostics box
        diag_frame = ttk.LabelFrame(body, text="Diagnostics")
        diag_frame.grid(row=3, column=0, sticky="nsew")
        self.diag = tk.Text(diag_frame, width=64, height=10, wrap="word")
        self.diag.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        diag_frame.columnconfigure(0, weight=1)
        diag_frame.rowconfigure(0, weight=1)

        # buttons
        btns = ttk.Frame(body)
        btns.grid(row=4, column=0, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Refresh", command=self.refresh).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="Apply", command=self.apply_async).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(btns, text="Close", command=self.destroy).grid(row=0, column=2)

        self._init_state()

    # ----------------------------- helpers -----------------------------------

    def _append_diag(self, line: str) -> None:
        self.diag.insert("end", line.rstrip() + "\n")
        self.diag.see("end")

    def _set_status(self, ok: bool | None) -> None:
        if ok is True:
            self.status_lbl.configure(text="Status: Enabled", style="Good.TLabel")
        elif ok is False:
            self.status_lbl.configure(text="Status: Disabled", style="Bad.TLabel")
        else:
            self.status_lbl.configure(text="Status: Unknown", style="Warn.TLabel")

    # ------------------------------- init ------------------------------------

    def _init_state(self) -> None:
        if platform.system() != "Windows":
            self.toggle.configure(state="disabled")
            self._set_status(None)
            self._append_diag("Not Windows. Defender unsupported.")
            return

        if not is_defender_supported():
            self.toggle.configure(state="disabled")
            self._set_status(None)
            self._append_diag("Defender PowerShell cmdlets unavailable.")
            return

        cur = is_defender_enabled()
        self.toggle_var.set(bool(cur) if cur is not None else False)
        self._set_status(cur)
        self.refresh()  # fill diagnostics

    # ---------------------------- diagnostics --------------------------------

    def refresh(self) -> None:
        self.diag.delete("1.0", "end")
        st = get_defender_status()
        self._set_status(st.realtime)
        rows = [
            f"Realtime enabled: {st.realtime}",
            f"Services OK: {st.services_ok}",
            f"Cmdlets available: {st.cmdlets_available}",
            f"Tamper Protection ON: {st.tamper_on}",
            f"Policy lock present: {st.policy_lock}",
            f"Third-party AV present: {st.third_party_av_present}",
        ]
        if st.error:
            rows.append(f"Error: {st.error}")
        for r in rows:
            self._append_diag(r)

    # ------------------------------- apply -----------------------------------

    def apply_async(self) -> None:
        if platform.system() != "Windows":
            messagebox.showwarning("Security Center", "Windows only.")
            return
        if not ensure_admin():
            messagebox.showwarning("Security Center", "Administrator rights required.")
            return

        self.pbar.grid(row=2, column=0, sticky="w", pady=(0, 10))
        self.pbar.start(12)
        self.toggle.configure(state="disabled")

        want = bool(self.toggle_var.get())

        def work() -> None:
            ok, err = set_defender_enabled(want)
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

        cur = is_defender_enabled()
        if cur is not None:
            self.toggle_var.set(cur)
        self._set_status(cur)
        self.refresh()

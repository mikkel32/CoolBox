# -*- coding: utf-8 -*-
"""
Security Center dialog with hardened Defender control and diagnostics.
"""

from __future__ import annotations

import platform
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING

from src.utils.security import (
    ensure_admin,
    get_defender_status,
    is_defender_supported,
    read_current_states,
    set_firewall_enabled,
    set_defender_enabled,
)

if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from src.app import CoolBoxApp


class SecurityDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc | "CoolBoxApp" | None = None) -> None:
        """Create the dialog.

        *master* may be either a Tk widget or a :class:`CoolBoxApp` instance.
        The latter case occurs when the dialog is launched from the main
        application, which provides the root window on its ``window`` attribute.
        """

        app = master if hasattr(master, "window") else None
        tk_master = master.window if app is not None else master

        super().__init__(tk_master)

        self.app: "CoolBoxApp | None" = app  # type: ignore[assignment]
        if self.app is not None and hasattr(self.app, "register_dialog"):
            self.app.register_dialog(self)
        if self.app is not None and hasattr(self.app, "get_icon_photo"):
            try:
                icon = self.app.get_icon_photo()
                if icon is not None:
                    self.iconphoto(False, icon)
            except Exception:
                pass
        self.bind("<Escape>", lambda _e: self.destroy())
        self.title("Security Center")
        self.resizable(False, False)

        self.firewall_var = tk.BooleanVar(value=False)
        self.defender_var = tk.BooleanVar(value=False)

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        self.firewall_sw = ttk.Checkbutton(
            frm, text="Firewall enabled", variable=self.firewall_var
        )
        self.firewall_sw.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.defender_sw = ttk.Checkbutton(
            frm,
            text="Windows Defender real-time protection",
            variable=self.defender_var,
        )
        self.defender_sw.grid(row=1, column=0, sticky="w", pady=(0, 8))

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Diagnose", command=self._diagnose).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(btns, text="Apply", command=self._apply).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Button(btns, text="Close", command=self.destroy).grid(row=0, column=2)

        self._init_state()

    # ------------------------------ state -----------------------------------

    def _init_state(self) -> None:
        fw, df = read_current_states()
        if fw is not None:
            self.firewall_var.set(bool(fw))

        if platform.system() == "Windows" and is_defender_supported():
            self.defender_sw.state(["!disabled"])
            if df is not None:
                self.defender_var.set(bool(df))
        else:
            self.defender_var.set(False)
            self.defender_sw.state(["disabled"])
            self.defender_sw.configure(
                text="Windows Defender real-time protection (unsupported)"
            )

    # ----------------------------- actions ----------------------------------

    def _diagnose(self) -> None:
        if platform.system() != "Windows":
            messagebox.showinfo("Security Center", "Defender is Windows-only.")
            return
        st = get_defender_status()
        lines = []
        lines.append(f"Realtime: {st.realtime}")
        lines.append(f"Services OK: {st.services_ok}")
        lines.append(f"Cmdlets available: {st.cmdlets_available}")
        lines.append(f"Tamper Protection ON: {st.tamper_on}")
        lines.append(f"Policy lock present: {st.policy_lock}")
        lines.append(f"Managed by organization: {st.managed_by_org}")
        lines.append(f"Third-party AV present: {st.third_party_av_present}")
        if st.error:
            lines.append(f"Error: {st.error}")
        messagebox.showinfo(
            "Security Center — Defender diagnostics", "\n".join(lines)
        )
    def _apply(self) -> None:
        if not ensure_admin():
            messagebox.showwarning("Security Center", "Administrator rights required.")
            return

        ok_fw = set_firewall_enabled(bool(self.firewall_var.get()))

        ok_def, err_def = True, None
        if platform.system() == "Windows" and "disabled" not in self.defender_sw.state():
            ok_def, err_def = set_defender_enabled(bool(self.defender_var.get()))

        if ok_fw and ok_def:
            messagebox.showinfo("Security Center", "Settings applied successfully")
            self._init_state()
            return

        parts = []
        if not ok_fw:
            parts.append("Firewall")
        if not ok_def:
            parts.append("Defender")
        detail = f"\n{err_def}" if err_def else ""
        messagebox.showwarning(
            "Security Center", f"Failed to apply: {', '.join(parts)}{detail}"
        )
    def destroy(self) -> None:  # type: ignore[override]
        if self.app is not None and hasattr(self.app, "unregister_dialog"):
            self.app.unregister_dialog(self)
        super().destroy()

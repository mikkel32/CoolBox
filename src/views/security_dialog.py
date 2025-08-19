# -*- coding: utf-8 -*-
"""
Security Center dialog that launches advanced Firewall and Defender controls.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Optional, Tuple

from src.utils.firewall import (
    is_firewall_supported,
    get_firewall_status,
    FirewallStatus,
)
from src.utils.defender import (
    is_defender_supported,
    get_defender_status,
    DefenderStatus,
)
from src.app import error_handler as eh
from .firewall_dialog import FirewallDialog
from .defender_dialog import DefenderDialog

if TYPE_CHECKING:  # pragma: no cover
    from src.app import CoolBoxApp


# expose for tests

def read_current_statuses() -> Tuple[FirewallStatus, DefenderStatus]:
    fw = get_firewall_status() if is_firewall_supported() else FirewallStatus(
        None, None, None, False, False, False, False, None, "Unsupported"
    )
    df = get_defender_status() if is_defender_supported() else DefenderStatus(
        None, None, False, False, False, False, None, "Unsupported"
    )
    return fw, df


def read_current_states() -> Tuple[Optional[bool], Optional[bool]]:
    fw, df = read_current_statuses()
    profiles = (fw.domain, fw.private, fw.public)
    fw_state: Optional[bool]
    if any(v is None for v in profiles):
        fw_state = None
    else:
        fw_state = bool(all(profiles))
    return fw_state, df.realtime


class SecurityDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc | "CoolBoxApp" | None = None) -> None:
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

        style = ttk.Style(self)
        try:
            # Use native theme on Windows when available
            if tk.TkVersion >= 8.6 and self.tk.call("tk", "windowingsystem") == "win32":
                style.theme_use("vista")
        except Exception:
            pass
        style.configure("Good.TLabel", foreground="#0a7d0a")
        style.configure("Bad.TLabel", foreground="#a61e1e")
        style.configure("Warn.TLabel", foreground="#ad5a00")

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        # firewall row
        self.lbl_fw = ttk.Label(frm, text="Firewall: …")
        self.lbl_fw.grid(row=0, column=0, sticky="w")
        ttk.Button(frm, text="Firewall…", command=self._open_firewall).grid(
            row=0, column=1, padx=(8, 0)
        )

        # defender row
        self.lbl_df = ttk.Label(frm, text="Defender: …")
        self.lbl_df.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(frm, text="Defender…", command=self._open_defender).grid(
            row=1, column=1, padx=(8, 0)
        )

        # buttons
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Refresh", command=self.refresh).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(btns, text="Close", command=self.destroy).grid(row=0, column=1)

        self.refresh()

    # ----------------------------- helpers -----------------------------------

    def _set_lbl(
        self, lbl: ttk.Label, name: str, val: Optional[bool], supported: bool
    ) -> None:
        if not supported:
            lbl.configure(text=f"{name}: Unsupported", style="Warn.TLabel")
            return
        if val is True:
            lbl.configure(text=f"{name}: On", style="Good.TLabel")
        elif val is False:
            lbl.configure(text=f"{name}: Off", style="Bad.TLabel")
        else:
            lbl.configure(text=f"{name}: Unknown", style="Warn.TLabel")

    # ------------------------------ actions ----------------------------------

    def refresh(self) -> None:
        try:
            fw_status, df_status = read_current_statuses()
        except Exception as e:  # pragma: no cover - safety net
            eh.handle_exception(type(e), e, e.__traceback__)
            messagebox.showerror("Security Center", f"Failed to read state: {e}")
            fw_status = FirewallStatus(None, None, None, False, False, False, False, None, str(e))
            df_status = DefenderStatus(None, None, False, False, False, False, None, str(e))

        profiles = (fw_status.domain, fw_status.private, fw_status.public)
        fw_state = None if any(v is None for v in profiles) else bool(all(profiles))
        self._set_lbl(self.lbl_fw, "Firewall", fw_state, is_firewall_supported())
        self._set_lbl(self.lbl_df, "Defender", df_status.realtime, is_defender_supported())

        if fw_status.error:
            messagebox.showwarning("Security Center", f"Firewall: {fw_status.error}")
        if df_status.error:
            messagebox.showwarning("Security Center", f"Defender: {df_status.error}")

    def _open_firewall(self) -> None:
        if not is_firewall_supported():
            messagebox.showwarning("Security Center", "Firewall control unsupported.")
            return
        try:
            FirewallDialog(self).grab_set()
        except Exception as e:  # pragma: no cover - UI failure
            eh.handle_exception(type(e), e, e.__traceback__)
            messagebox.showerror("Security Center", f"Failed to open Firewall: {e}")

    def _open_defender(self) -> None:
        if not is_defender_supported():
            messagebox.showwarning("Security Center", "Defender control unsupported.")
            return
        try:
            DefenderDialog(self).grab_set()
        except Exception as e:  # pragma: no cover - UI failure
            eh.handle_exception(type(e), e, e.__traceback__)
            messagebox.showerror("Security Center", f"Failed to open Defender: {e}")

    def destroy(self) -> None:  # type: ignore[override]
        if self.app is not None and hasattr(self.app, "unregister_dialog"):
            self.app.unregister_dialog(self)
        super().destroy()

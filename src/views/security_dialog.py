# -*- coding: utf-8 -*-
"""
Security Center dialog that launches advanced Firewall and Defender controls.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Optional, Tuple

from src.utils.firewall import is_firewall_enabled, is_firewall_supported
from src.utils.defender import is_defender_enabled, is_defender_supported
from .firewall_dialog import FirewallDialog
from .defender_dialog import DefenderDialog

if TYPE_CHECKING:  # pragma: no cover
    from src.app import CoolBoxApp


# expose for tests

def read_current_states() -> Tuple[Optional[bool], Optional[bool]]:
    fw = is_firewall_enabled() if is_firewall_supported() else None
    df = is_defender_enabled() if is_defender_supported() else None
    return fw, df


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

    def _fmt(self, val: Optional[bool]) -> str:
        if val is True:
            return "On"
        if val is False:
            return "Off"
        return "Unknown"

    # ------------------------------ actions ----------------------------------

    def refresh(self) -> None:
        fw, df = read_current_states()
        self.lbl_fw.configure(text=f"Firewall: {self._fmt(fw)}")
        if is_defender_supported():
            self.lbl_df.configure(text=f"Defender: {self._fmt(df)}")
        else:
            self.lbl_df.configure(text="Defender: Unsupported")

    def _open_firewall(self) -> None:
        FirewallDialog(self).grab_set()

    def _open_defender(self) -> None:
        DefenderDialog(self).grab_set()

    def destroy(self) -> None:  # type: ignore[override]
        if self.app is not None and hasattr(self.app, "unregister_dialog"):
            self.app.unregister_dialog(self)
        super().destroy()

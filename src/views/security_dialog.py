from __future__ import annotations

"""Dialog for toggling firewall and Defender."""

import platform
from tkinter import messagebox
import customtkinter as ctk

from .base_dialog import BaseDialog
from ..utils.security import (
    is_firewall_enabled,
    set_firewall_enabled,
    is_defender_enabled,
    set_defender_enabled,
    is_admin,
    ensure_admin,
)


class SecurityDialog(BaseDialog):
    """UI for basic security switches."""

    def __init__(self, app):
        super().__init__(app, title="Security Center", geometry="320x200")
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

        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.grid_button(btn_frame, "Refresh", self._refresh, 0, column=0, columnspan=1)
        self.grid_button(btn_frame, "Apply", self._apply, 0, column=1, columnspan=1)
        self.grid_button(btn_frame, "Close", self.destroy, 0, column=2, columnspan=1)

        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=1)

        self._refresh()
        self.center_window()
        self.refresh_fonts()
        self.refresh_theme()

    def _refresh(self) -> None:
        if platform.system() != "Windows" or not self.is_admin:
            self.firewall_sw.configure(state="disabled")
            self.defender_sw.configure(state="disabled")
            return
        self.firewall_var.set(is_firewall_enabled() or False)
        self.defender_var.set(is_defender_enabled() or False)

    def _apply(self) -> None:
        if platform.system() != "Windows":
            messagebox.showinfo(
                "Security Center", "Firewall and Defender control is Windows only."
            )
            return
        if not ensure_admin():
            return
        ok_fw = set_firewall_enabled(self.firewall_var.get())
        ok_def = set_defender_enabled(self.defender_var.get())
        if ok_fw and ok_def:
            messagebox.showinfo("Security Center", "Settings applied successfully")
        else:
            messagebox.showwarning(
                "Security Center", "Failed to apply some settings"
            )

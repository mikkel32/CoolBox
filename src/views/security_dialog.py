# -*- coding: utf-8 -*-
"""
Minimal, fast Tkinter UI for Security Center.
Two toggles: Firewall and Defender Real-time. Status live. Non-blocking.
No PowerShell popups; work is done via utils with hidden windows.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from types import SimpleNamespace

from src.utils import security


# expose for tests and patching ------------------------------------------------

is_firewall_enabled = security.is_firewall_enabled
is_defender_supported = getattr(security, "is_defender_supported", lambda: False)
get_defender_status = security.get_defender_status
set_firewall_enabled = security.set_firewall_enabled
set_defender_enabled = security.set_defender_enabled
set_defender_realtime = security.set_defender_realtime
DefenderStatus = security.DefenderStatus


def read_current_statuses():
    fw_enabled = is_firewall_enabled()
    fw = SimpleNamespace(
        domain=fw_enabled,
        private=fw_enabled,
        public=fw_enabled,
        error=None,
    )
    df = get_defender_status()
    return fw, df


class SecurityDialog(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=16)
        self.master.title("Security Center")
        self.master.geometry("480x240")
        self.master.resizable(False, False)

        self._fw_var = tk.BooleanVar(value=False)
        self._rt_var = tk.BooleanVar(value=False)

        title = ttk.Label(self, text="Security Center", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w")

        self._admin_lbl = ttk.Label(self, text="Admin: checking...")
        self._admin_lbl.grid(row=0, column=2, sticky="e")

        ttk.Label(self, text="Windows Firewall").grid(row=1, column=0, sticky="w", pady=(16, 4))
        self._fw_switch = ttk.Checkbutton(
            self, text="Enabled", variable=self._fw_var, command=self._on_fw_toggle
        )
        self._fw_switch.grid(row=1, column=1, sticky="w", pady=(16, 4))
        self._fw_status = ttk.Label(self, text="Status: ...")
        self._fw_status.grid(row=1, column=2, sticky="e", pady=(16, 4))

        ttk.Label(self, text="Microsoft Defender Realtime").grid(row=2, column=0, sticky="w", pady=4)
        self._rt_switch = ttk.Checkbutton(
            self, text="Enabled", variable=self._rt_var, command=self._on_rt_toggle
        )
        self._rt_switch.grid(row=2, column=1, sticky="w", pady=4)
        self._rt_status = ttk.Label(self, text="Status: ...")
        self._rt_status.grid(row=2, column=2, sticky="e", pady=4)

        self._refresh_btn = ttk.Button(self, text="Refresh", command=self.refresh_async)
        self._refresh_btn.grid(row=3, column=2, sticky="e", pady=(12, 0))

        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.columnconfigure(2, weight=1)

        self.refresh_async()

    # --------------------------- Event handlers ----------------------------

    def _on_fw_toggle(self):
        target = bool(self._fw_var.get())
        self._disable_inputs()
        threading.Thread(target=self._apply_firewall, args=(target,), daemon=True).start()

    def _on_rt_toggle(self):
        target = bool(self._rt_var.get())
        self._disable_inputs()
        threading.Thread(target=self._apply_realtime, args=(target,), daemon=True).start()

    # ------------------------------ Workers --------------------------------

    def _apply_firewall(self, enabled: bool):
        ok = set_firewall_enabled(enabled)
        self.after(0, lambda: self._post_apply("fw", ok))

    def _apply_realtime(self, enabled: bool):
        ok = (
            set_defender_enabled(enabled)[0]
            if enabled
            else set_defender_realtime(False)
        )
        self.after(0, lambda: self._post_apply("rt", ok))

    def _post_apply(self, kind: str, ok: bool):
        if not ok:
            messagebox.showerror(
                "Operation failed",
                "The requested change could not be applied.\n"
                "Ensure you are running as Administrator and that policy does not block it.",
            )
        self.refresh_async()

    # ------------------------------- Refresh --------------------------------

    def refresh_async(self):
        self._disable_inputs()
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self):
        admin = security.is_admin()
        fw_status, ds = read_current_statuses()
        profiles = (
            getattr(fw_status, "domain", None),
            getattr(fw_status, "private", None),
            getattr(fw_status, "public", None),
        )
        if any(v is None for v in profiles):
            fw = None
        else:
            fw = bool(all(profiles))
        self.after(0, lambda: self._set_states(admin, fw, ds))

    def _set_states(self, admin: bool, fw_enabled: bool | None, ds):
        self._admin_lbl.config(text=f"Admin: {'Yes' if admin else 'No'}")

        if fw_enabled is None:
            self._fw_var.set(False)
            self._fw_status.config(text="Status: unknown")
        else:
            self._fw_var.set(bool(fw_enabled))
            self._fw_status.config(text=f"Status: {'Enabled' if fw_enabled else 'Disabled'}")

        rt = getattr(ds, "realtime_enabled", getattr(ds, "realtime", None))
        svc = getattr(ds, "service_state", None) or "UNKNOWN"
        tamper = getattr(ds, "tamper_protection", getattr(ds, "tamper_on", None))
        rt_txt = []
        if rt is None:
            rt_txt.append("RT: unknown")
        else:
            rt_txt.append("RT: on" if rt else "RT: off")
        rt_txt.append(f"SVC: {svc}")
        if tamper is not None:
            rt_txt.append(f"TP: {'on' if tamper else 'off'}")
        self._rt_status.config(text="Status: " + " | ".join(rt_txt))
        self._rt_var.set(bool(rt) if rt is not None else False)

        self._enable_inputs(admin)

    # ------------------------------ UI state --------------------------------

    def _disable_inputs(self):
        for w in (self._fw_switch, self._rt_switch, self._refresh_btn):
            w.state(["disabled"])

    def _enable_inputs(self, admin: bool):
        self._refresh_btn.state(["!disabled"])
        if admin:
            self._fw_switch.state(["!disabled"])
            self._rt_switch.state(["!disabled"])
        else:
            self._fw_switch.state(["disabled"])
            self._rt_switch.state(["disabled"])


def run():
    root = tk.Tk()
    try:
        root.call("ttk::style", "theme", "use", "vista")
    except Exception:
        pass
    SecurityDialog(root)
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover
    run()


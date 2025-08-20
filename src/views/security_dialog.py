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

from typing import Callable, Type

from src.utils import security
from .firewall_dialog import FirewallDialog
from .defender_dialog import DefenderDialog


class SecurityDialog(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=16)
        self.master.title("Security Center")
        self.master.geometry("480x240")
        self.master.resizable(False, False)

        self._fw_var = tk.BooleanVar(value=False)
        self._rt_var = tk.BooleanVar(value=False)

        # Track dialogs opened from the "+" buttons so they can be
        # positioned smartly around the main window.
        self._child_windows: list[tk.Toplevel] = []
        # True when dialogs stack vertically (above/below the root).
        self._child_vertical = False
        # Direction for the child stack: "right", "left", "below" or "above".
        # Defaults to stacking on the right side of the main window.
        self._child_dir = "right"
        self.master.bind("<Configure>", self._reposition_children)

        # Shared styles for status labels
        style = ttk.Style(self.master)
        style.configure("Good.TLabel", foreground="#0a7d0a")
        style.configure("Bad.TLabel", foreground="#a61e1e")
        style.configure("Warn.TLabel", foreground="#ad5a00")

        # Header
        title = ttk.Label(self, text="Security Center", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")

        # Admin state
        self._admin_lbl = ttk.Label(self, text="Admin: checking...")
        self._admin_lbl.grid(row=0, column=1, sticky="e")

        # Firewall section
        fw_frame = ttk.LabelFrame(self, text="Windows Firewall")
        fw_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 4))
        ttk.Button(fw_frame, text="+", width=2, command=self._open_firewall).grid(row=0, column=0, padx=(0, 4))
        self._fw_switch = ttk.Checkbutton(
            fw_frame, text="Enabled", variable=self._fw_var, command=self._on_fw_toggle
        )
        self._fw_switch.grid(row=0, column=1, sticky="w")
        self._fw_status = ttk.Label(fw_frame, text="Status: ...")
        self._fw_status.grid(row=0, column=2, sticky="e")
        fw_frame.columnconfigure(1, weight=1)

        # Defender section
        rt_frame = ttk.LabelFrame(self, text="Microsoft Defender Realtime")
        rt_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(rt_frame, text="+", width=2, command=self._open_defender).grid(row=0, column=0, padx=(0, 4))
        self._rt_switch = ttk.Checkbutton(
            rt_frame, text="Enabled", variable=self._rt_var, command=self._on_rt_toggle
        )
        self._rt_switch.grid(row=0, column=1, sticky="w")
        self._rt_status = ttk.Label(rt_frame, text="Status: ...")
        self._rt_status.grid(row=0, column=2, sticky="e")
        rt_frame.columnconfigure(1, weight=1)

        # Refresh button
        self._refresh_btn = ttk.Button(self, text="Refresh", command=self.refresh_async)
        self._refresh_btn.grid(row=3, column=1, sticky="e", pady=(12, 0))

        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Initial load
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
        ok = security.set_firewall_enabled(enabled)
        self.after(0, lambda: self._post_apply("fw", ok))

    def _apply_realtime(self, enabled: bool):
        # Use composite helper so enabling ensures service + realtime.
        ok = (
            security.set_defender_enabled(enabled)
            if enabled
            else security.set_defender_realtime(False)
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

    # --------------------------- Subdialogs --------------------------------

    def _open_firewall(self) -> None:
        self._open_dialog(FirewallDialog)

    def _open_defender(self) -> None:
        self._open_dialog(DefenderDialog)

    def _open_dialog(self, dlg_cls: Type[tk.Toplevel]) -> None:
        """Create dialog and slide it in beside the main window.

        When the dialog is closed, it smoothly slides out and the remaining
        dialogs stay neatly locked beside the main window.
        """
        dlg = dlg_cls(self.master)
        dlg.update_idletasks()
        self._child_windows.append(dlg)
        # Reposition existing dialogs and decide stacking orientation
        self._reposition_children(exclude=dlg)
        self._slide_in(dlg)

        def _close() -> None:
            if dlg in self._child_windows:
                self._child_windows.remove(dlg)

            def after() -> None:
                dlg.destroy()
                self._reposition_children()

            self._slide_out(dlg, after)

        dlg.protocol("WM_DELETE_WINDOW", _close)

    # ------------------------------- Refresh --------------------------------

    def refresh_async(self):
        self._disable_inputs()
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self):
        admin = security.is_admin()
        fw = security.is_firewall_enabled()
        ds = security.get_defender_status()
        self.after(0, lambda: self._set_states(admin, fw, ds))

    def _set_states(self, admin: bool, fw_enabled: bool | None, ds: security.DefenderStatus):
        self._admin_lbl.config(text=f"Admin: {'Yes' if admin else 'No'}")

        if fw_enabled is None:
            self._fw_var.set(False)
            self._fw_status.config(text="Status: unknown", style="Warn.TLabel")
        else:
            self._fw_var.set(bool(fw_enabled))
            self._fw_status.config(
                text=f"Status: {'Enabled' if fw_enabled else 'Disabled'}",
                style="Good.TLabel" if fw_enabled else "Bad.TLabel",
            )

        rt = ds.realtime_enabled
        svc = ds.service_state or "UNKNOWN"
        tamper = ds.tamper_protection
        rt_txt = []
        if rt is None:
            rt_txt.append("RT: unknown")
        else:
            rt_txt.append("RT: on" if rt else "RT: off")
        rt_txt.append(f"SVC: {svc}")
        if tamper is not None:
            rt_txt.append(f"TP: {'on' if tamper else 'off'}")
        self._rt_status.config(
            text="Status: " + " | ".join(rt_txt),
            style=(
                "Good.TLabel" if rt else "Bad.TLabel" if rt is False else "Warn.TLabel"
            ),
        )
        self._rt_var.set(bool(rt) if rt is not None else False)

        self._enable_inputs(admin)

    # ------------------------------ UI state --------------------------------

    def _disable_inputs(self):
        for w in (self._fw_switch, self._rt_switch, self._refresh_btn):
            w.state(["disabled"])

    def _enable_inputs(self, admin: bool):
        # Allow viewing even without admin. Changes require admin.
        self._refresh_btn.state(["!disabled"])
        if admin:
            self._fw_switch.state(["!disabled"])
            self._rt_switch.state(["!disabled"])
        else:
            self._fw_switch.state(["disabled"])
            self._rt_switch.state(["disabled"])

    # --------------------------- Window helpers -----------------------------

    def _update_orientation(self) -> None:
        """Decide how child dialogs should stack around the main window."""
        self.master.update_idletasks()

        root_x = self.master.winfo_rootx()
        root_y = self.master.winfo_rooty()
        root_w = self.master.winfo_width()
        root_h = self.master.winfo_height()
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()

        total_w = 0
        total_h = 0
        for win in self._child_windows:
            if win.winfo_exists():
                win.update_idletasks()
                total_w += win.winfo_width()
                total_h += win.winfo_height()

        space_right = screen_w - (root_x + root_w)
        space_left = root_x
        space_below = screen_h - (root_y + root_h)
        space_above = root_y

        if max(space_right, space_left) >= total_w:
            self._child_vertical = False
            self._child_dir = "right" if space_right >= space_left else "left"
        else:
            self._child_vertical = True
            self._child_dir = "below" if space_below >= space_above else "above"

    def _slide_in(self, win: tk.Toplevel) -> None:
        """Animate a window sliding in beside or above/below the main window."""
        self.master.update_idletasks()
        win.update_idletasks()

        root_x = self.master.winfo_rootx()
        root_y = self.master.winfo_rooty()
        root_w = self.master.winfo_width()
        root_h = self.master.winfo_height()

        win_w = win.winfo_width()
        win_h = win.winfo_height()

        steps = 12
        delay = 15

        if self._child_vertical:
            final_x = root_x
            if self._child_dir == "below":
                final_y = root_y + root_h
                for w in self._child_windows[:-1]:
                    if w.winfo_exists():
                        final_y += w.winfo_height()
                start_y = final_y + win_h
                win.geometry(f"+{final_x}+{start_y}")

                delta = (start_y - final_y) / steps

                def step(i: int = 0) -> None:
                    y = int(start_y - delta * i)
                    win.geometry(f"+{final_x}+{y}")
                    if i < steps:
                        win.after(delay, step, i + 1)

                step()
            else:  # stack above
                final_y = root_y - win_h
                for w in self._child_windows[:-1]:
                    if w.winfo_exists():
                        final_y -= w.winfo_height()
                start_y = final_y - win_h
                win.geometry(f"+{final_x}+{start_y}")

                delta = (final_y - start_y) / steps

                def step(i: int = 0) -> None:
                    y = int(start_y + delta * i)
                    win.geometry(f"+{final_x}+{y}")
                    if i < steps:
                        win.after(delay, step, i + 1)

                step()
        else:
            final_y = root_y
            if self._child_dir == "right":
                final_x = root_x + root_w
                for w in self._child_windows[:-1]:
                    if w.winfo_exists():
                        final_x += w.winfo_width()
                start_x = final_x + win_w
                win.geometry(f"+{start_x}+{final_y}")

                delta = (start_x - final_x) / steps

                def step(i: int = 0) -> None:
                    x = int(start_x - delta * i)
                    win.geometry(f"+{x}+{final_y}")
                    if i < steps:
                        win.after(delay, step, i + 1)

                step()
            else:  # stack to the left
                final_x = root_x - win_w
                for w in self._child_windows[:-1]:
                    if w.winfo_exists():
                        final_x -= w.winfo_width()
                start_x = final_x - win_w
                win.geometry(f"+{start_x}+{final_y}")

                delta = (final_x - start_x) / steps

                def step(i: int = 0) -> None:
                    x = int(start_x + delta * i)
                    win.geometry(f"+{x}+{final_y}")
                    if i < steps:
                        win.after(delay, step, i + 1)

                step()

    def _slide_out(self, win: tk.Toplevel, on_done: Callable[[], None]) -> None:
        """Animate a window sliding out before closing."""
        try:
            self.master.update_idletasks()
            win.update_idletasks()
            start_x = win.winfo_x()
            start_y = win.winfo_y()
            win_w = win.winfo_width()
            win_h = win.winfo_height()
        except Exception:
            on_done()
            return

        steps = 12
        delay = 15
        if self._child_vertical:
            if self._child_dir == "below":
                end_y = start_y + win_h
                delta = (end_y - start_y) / steps

                def step(i: int = 0) -> None:
                    y = int(start_y + delta * i)
                    win.geometry(f"+{start_x}+{y}")
                    if i < steps:
                        win.after(delay, step, i + 1)
                    else:
                        on_done()

                step()
            else:  # above
                end_y = start_y - win_h
                delta = (start_y - end_y) / steps

                def step(i: int = 0) -> None:
                    y = int(start_y - delta * i)
                    win.geometry(f"+{start_x}+{y}")
                    if i < steps:
                        win.after(delay, step, i + 1)
                    else:
                        on_done()

                step()
        else:
            if self._child_dir == "right":
                end_x = start_x + win_w
                delta = (end_x - start_x) / steps

                def step(i: int = 0) -> None:
                    x = int(start_x + delta * i)
                    win.geometry(f"+{x}+{start_y}")
                    if i < steps:
                        win.after(delay, step, i + 1)
                    else:
                        on_done()

                step()
            else:  # left
                end_x = start_x - win_w
                delta = (start_x - end_x) / steps

                def step(i: int = 0) -> None:
                    x = int(start_x - delta * i)
                    win.geometry(f"+{x}+{start_y}")
                    if i < steps:
                        win.after(delay, step, i + 1)
                    else:
                        on_done()

                step()

    def _reposition_children(self, event: tk.Event | None = None, exclude: tk.Toplevel | None = None) -> None:
        """Keep child dialogs locked beside or around the main window."""
        if not self._child_windows:
            return
        self._update_orientation()
        self.master.update_idletasks()
        root_x = self.master.winfo_rootx()
        root_y = self.master.winfo_rooty()
        root_w = self.master.winfo_width()
        root_h = self.master.winfo_height()

        if self._child_vertical:
            x = root_x
            if self._child_dir == "below":
                y = root_y + root_h
                for win in list(self._child_windows):
                    if win is exclude:
                        continue
                    if win.winfo_exists():
                        win.update_idletasks()
                        win.geometry(f"+{x}+{y}")
                        y += win.winfo_height()
                    else:
                        self._child_windows.remove(win)
            else:  # above
                y = root_y
                for win in list(self._child_windows):
                    if win is exclude:
                        continue
                    if win.winfo_exists():
                        win.update_idletasks()
                        y -= win.winfo_height()
                        win.geometry(f"+{x}+{y}")
                    else:
                        self._child_windows.remove(win)
        else:
            y = root_y
            if self._child_dir == "right":
                x = root_x + root_w
                for win in list(self._child_windows):
                    if win is exclude:
                        continue
                    if win.winfo_exists():
                        win.update_idletasks()
                        win.geometry(f"+{x}+{y}")
                        x += win.winfo_width()
                    else:
                        self._child_windows.remove(win)
            else:  # left
                x = root_x
                for win in list(self._child_windows):
                    if win is exclude:
                        continue
                    if win.winfo_exists():
                        win.update_idletasks()
                        x -= win.winfo_width()
                        win.geometry(f"+{x}+{y}")
                    else:
                        self._child_windows.remove(win)


def run():
    root = tk.Tk()
    # Modern ttk theme fallback
    try:
        root.call("ttk::style", "theme", "use", "vista")
    except Exception:
        pass
    SecurityDialog(root)
    root.mainloop()


if __name__ == "__main__":
    run()


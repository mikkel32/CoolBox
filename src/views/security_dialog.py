# -*- coding: utf-8 -*-
"""
Minimal, fast Tkinter UI for Security Center.
Two toggles: Firewall and Defender Real-time. Status live. Non-blocking.
No PowerShell popups; work is done via utils with hidden windows.
"""

from __future__ import annotations

import sys
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, ttk

from typing import Callable, Type, TypeVar, cast

from src.utils import security
from .firewall_dialog import FirewallDialog
from .defender_dialog import DefenderDialog


T = TypeVar("T")


class _AsyncDispatcher:
    """Coordinate background work and marshal results onto the UI thread."""

    def __init__(self, widget: tk.Misc):
        self._widget = widget
        self._lock = threading.Lock()
        self._tokens: dict[str, object] = {}

    def submit(
        self,
        key: str,
        func: Callable[[], T],
        on_success: Callable[[T], None],
        on_error: Callable[[BaseException, str], None] | None = None,
    ) -> None:
        token = object()
        with self._lock:
            self._tokens[key] = token

        def worker() -> None:
            try:
                result = func()
            except Exception as exc:  # pragma: no cover - defensive path
                trace = traceback.format_exc()
                self._schedule(lambda: self._deliver_error(key, token, exc, trace, on_error))
            else:
                self._schedule(lambda: self._deliver_success(key, token, result, on_success))

        threading.Thread(target=worker, daemon=True).start()

    def _schedule(self, callback: Callable[[], None]) -> None:
        try:
            self._widget.after(0, callback)
        except tk.TclError:  # pragma: no cover - UI already destroyed
            pass

    def _pop_token(self, key: str, token: object) -> bool:
        with self._lock:
            current = self._tokens.get(key)
            if current is not token:
                return False
            self._tokens.pop(key, None)
            return True

    def _deliver_success(
        self, key: str, token: object, result: T, on_success: Callable[[T], None]
    ) -> None:
        if self._pop_token(key, token):
            on_success(result)

    def _deliver_error(
        self,
        key: str,
        token: object,
        exc: BaseException,
        trace: str,
        on_error: Callable[[BaseException, str], None] | None,
    ) -> None:
        if not self._pop_token(key, token):
            return
        if on_error is not None:
            on_error(exc, trace)


class SecurityDialog(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master, padding=16)
        window = self.winfo_toplevel()
        if not isinstance(window, (tk.Tk, tk.Toplevel)):
            raise TypeError("SecurityDialog requires a Tk or Toplevel master")
        self._window: tk.Toplevel | tk.Tk = cast("tk.Toplevel | tk.Tk", window)
        self._window.title("Security Center")
        self._window.geometry("480x240")
        self._window.resizable(False, False)

        self._fw_var = tk.BooleanVar(value=False)
        self._rt_var = tk.BooleanVar(value=False)
        self._dispatcher = _AsyncDispatcher(self)

        # Track dialogs opened from the "+" buttons so they can be
        # positioned near the main window on any available side.
        self._child_windows: list[tk.Toplevel] = []
        self._child_vertical = False  # stack beside by default
        # Track which side the child windows should use when stacking.
        # "right"/"left" for horizontal layouts, "below"/"above" for vertical.
        self._child_side = "right"
        self._window.bind("<Configure>", self._reposition_children)

        # Shared styles for status labels
        style = ttk.Style(self._window)
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

        self._report_var = tk.StringVar(value="No activity yet.")
        self._report_lbl = ttk.Label(
            self,
            textvariable=self._report_var,
            wraplength=440,
            style="Warn.TLabel",
        )
        self._report_lbl.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Initial load
        self.refresh_async()

    # --------------------------- Event handlers ----------------------------

    def _on_fw_toggle(self):
        target = bool(self._fw_var.get())
        self._disable_inputs()
        self._dispatcher.submit(
            "fw",
            lambda: self._apply_firewall(target),
            lambda ok: self._post_apply("fw", ok),
            lambda exc, trace: self._handle_async_failure("firewall", exc, trace),
        )

    def _on_rt_toggle(self):
        target = bool(self._rt_var.get())
        self._disable_inputs()
        self._dispatcher.submit(
            "rt",
            lambda: self._apply_realtime(target),
            lambda ok: self._post_apply("rt", ok),
            lambda exc, trace: self._handle_async_failure("Defender", exc, trace),
        )

    # ------------------------------ Workers --------------------------------

    def _apply_firewall(self, enabled: bool) -> security.ActionOutcome:
        return security.set_firewall_enabled(enabled)

    def _apply_realtime(self, enabled: bool) -> security.ActionOutcome:
        # Use composite helper so enabling ensures service + realtime.
        return (
            security.set_defender_enabled(enabled)
            if enabled
            else security.set_defender_realtime(False)
        )

    def _post_apply(self, kind: str, outcome: security.ActionOutcome):
        action = self._friendly_action(kind)
        if outcome.success:
            detail = outcome.detail or f"{action} completed successfully."
            self._update_report(detail, success=True)
        else:
            actors = ", ".join(outcome.blockers) if outcome.blockers else "unknown forces"
            message = f"{action} was blocked by {actors}."
            if outcome.detail:
                message = f"{message} Details: {outcome.detail}"
            self._update_report(message, success=False)
            messagebox.showerror("Operation blocked", message)
        self.refresh_async()

    # --------------------------- Subdialogs --------------------------------

    def _open_firewall(self) -> None:
        self._open_dialog(FirewallDialog)

    def _open_defender(self) -> None:
        self._open_dialog(DefenderDialog)

    def _open_dialog(self, dlg_cls: Type[tk.Toplevel]) -> None:
        """Create dialog and slide it in near the main window.

        When the dialog is closed, it smoothly slides out and the remaining
        dialogs stay neatly arranged around the main window.
        """
        dlg = dlg_cls(self._window)
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
        self._dispatcher.submit(
            "refresh",
            security.get_security_snapshot,
            self._set_states,
            lambda exc, trace: self._handle_async_failure("refresh", exc, trace),
        )

    def _set_states(self, snapshot: security.SecuritySnapshot):
        admin = snapshot.admin
        fw_enabled = snapshot.firewall_enabled
        ds = snapshot.defender

        self._admin_lbl.config(text=f"Admin: {'Yes' if admin else 'No'}")

        if fw_enabled is None:
            self._fw_var.set(False)
            txt = "Status: unknown"
            style = "Warn.TLabel"
        else:
            self._fw_var.set(bool(fw_enabled))
            state_txt = "Enabled" if fw_enabled else "Disabled"
            txt = f"Status: {state_txt}"
            style = "Good.TLabel" if fw_enabled else "Bad.TLabel"
        if snapshot.firewall_blockers:
            txt += " | Block: " + ", ".join(snapshot.firewall_blockers)
            style = "Bad.TLabel"
        self._fw_status.config(text=txt, style=style)

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
        if ds.blockers:
            rt_txt.append("Block: " + ", ".join(ds.blockers))
        self._rt_status.config(
            text="Status: " + " | ".join(rt_txt),
            style=(
                "Good.TLabel" if rt else "Bad.TLabel" if rt is False else "Warn.TLabel"
            ),
        )
        self._rt_var.set(bool(rt) if rt is not None else False)

        self._enable_inputs(admin)

    def _handle_async_failure(self, label: str, exc: BaseException, trace: str) -> None:
        print(trace, file=sys.stderr)
        msg = (
            f"An unexpected error occurred while processing {label} actions."
            " Check logs for details."
        )
        self._update_report(msg, success=False)
        messagebox.showerror("Security Center", msg)
        self._enable_inputs(False)

    def _update_report(self, text: str, *, success: bool) -> None:
        prefix = "Last action: "
        self._report_var.set(prefix + text)
        self._report_lbl.configure(style="Good.TLabel" if success else "Bad.TLabel")

    @staticmethod
    def _friendly_action(kind: str) -> str:
        mapping = {
            "fw": "Firewall toggle",
            "rt": "Defender realtime toggle",
            "refresh": "Refresh",
        }
        return mapping.get(kind, kind.capitalize())

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
        """Choose stacking orientation and side for child dialogs."""
        self.master.update_idletasks()
        root_x = self.master.winfo_rootx()
        root_y = self.master.winfo_rooty()
        root_w = self.master.winfo_width()
        root_h = self.master.winfo_height()
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()

        child_ws: list[int] = []
        child_hs: list[int] = []
        for win in self._child_windows:
            if win.winfo_exists():
                win.update_idletasks()
                child_ws.append(win.winfo_width())
                child_hs.append(win.winfo_height())

        if not child_ws:
            self._child_vertical = False
            self._child_side = "right"
            return

        horiz_w = root_w + sum(child_ws)
        horiz_h = max([root_h] + child_hs)
        vert_w = max([root_w] + child_ws)
        vert_h = root_h + sum(child_hs)

        fits_horiz = horiz_w <= screen_w and horiz_h <= screen_h
        fits_vert = vert_w <= screen_w and vert_h <= screen_h

        if fits_horiz and not fits_vert:
            self._child_vertical = False
        elif fits_vert and not fits_horiz:
            self._child_vertical = True
        elif fits_vert and fits_horiz:
            self._child_vertical = False
        else:
            overflow_h = (horiz_w - screen_w) + (horiz_h - screen_h)
            overflow_v = (vert_w - screen_w) + (vert_h - screen_h)
            self._child_vertical = overflow_v < overflow_h

        right_space = screen_w - (root_x + root_w)
        left_space = root_x
        bottom_space = screen_h - (root_y + root_h)
        top_space = root_y

        if self._child_vertical:
            needed = sum(child_hs)
            if bottom_space >= needed or bottom_space >= top_space:
                self._child_side = "below"
            else:
                self._child_side = "above"
        else:
            needed = sum(child_ws)
            if right_space >= needed or right_space >= left_space:
                self._child_side = "right"
            else:
                self._child_side = "left"

    def _slide_in(self, win: tk.Toplevel) -> None:
        """Animate a window sliding in beside the main window."""
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
            if self._child_side == "below":
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
            else:  # above
                final_y = root_y
                for w in self._child_windows[:-1]:
                    if w.winfo_exists():
                        final_y -= w.winfo_height()
                final_y -= win_h
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
            if self._child_side == "right":
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
            else:  # left
                final_x = root_x
                for w in self._child_windows[:-1]:
                    if w.winfo_exists():
                        final_x -= w.winfo_width()
                final_x -= win_w
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
            if self._child_side == "below":
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
            if self._child_side == "right":
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
        """Keep child dialogs locked around the main window."""
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
            if self._child_side == "below":
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
                        h = win.winfo_height()
                        y -= h
                        win.geometry(f"+{x}+{y}")
                    else:
                        self._child_windows.remove(win)
        else:
            y = root_y
            if self._child_side == "right":
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
                        w = win.winfo_width()
                        x -= w
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


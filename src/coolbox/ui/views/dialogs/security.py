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
from datetime import datetime
from tkinter import messagebox, ttk

from typing import Callable, Optional, Type, TypeVar, cast

from coolbox.utils import security
from .firewall import FirewallDialog
from .defender import DefenderDialog


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
        self._window.geometry("620x480")
        self._window.resizable(False, False)

        self._fw_var = tk.BooleanVar(value=False)
        self._rt_var = tk.BooleanVar(value=False)
        self._last_refresh_var = tk.StringVar(value="Last updated: pending…")
        self._fw_pending_var = tk.StringVar(value="")
        self._rt_pending_var = tk.StringVar(value="")
        self._fw_action_text = tk.StringVar(value="Checking…")
        self._rt_action_text = tk.StringVar(value="Checking…")
        self._dispatcher = _AsyncDispatcher(self)
        self._busy_messages: list[str] = []
        self._auto_job: Optional[str] = None
        self._fw_state: Optional[bool] = None
        self._rt_state: Optional[bool] = None
        self._updating_fw_var = False
        self._updating_rt_var = False
        self._run_admin_visible = False

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
        style.configure("Caption.TLabel", foreground="#4f5d6b", font=("Segoe UI", 9))
        style.configure("BusyCaption.TLabel", foreground="#0b4faa", font=("Segoe UI", 9, "italic"))

        for style_name, bg, fg in (
            ("Status.Good.TLabel", "#e8f5e9", "#0a7d0a"),
            ("Status.Bad.TLabel", "#fdecea", "#a61e1e"),
            ("Status.Warn.TLabel", "#fff4e5", "#ad5a00"),
            ("Status.Info.TLabel", "#e7f0fd", "#0b4faa"),
        ):
            style.configure(
                style_name,
                background=bg,
                foreground=fg,
                padding=(10, 4),
                relief="flat",
                anchor="w",
            )
            style.map(style_name, background=[("!disabled", bg), ("disabled", bg)])

        style.configure("Report.Pending.TLabel", foreground="#0b4faa")
        style.configure("Report.Success.TLabel", foreground="#0a7d0a")
        style.configure("Report.Failure.TLabel", foreground="#a61e1e")

        # Header
        title = ttk.Label(self, text="Security Center", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")

        last_refresh = ttk.Label(self, textvariable=self._last_refresh_var, style="Caption.TLabel")
        last_refresh.grid(row=0, column=1, sticky="e")

        admin_frame = ttk.Frame(self)
        admin_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        admin_frame.columnconfigure(0, weight=1)

        self._admin_lbl = ttk.Label(admin_frame, text="Admin: checking...")
        self._admin_lbl.grid(row=0, column=0, sticky="w")

        self._admin_hint = ttk.Label(
            admin_frame,
            text="Administrator permissions are required for changes.",
            style="Caption.TLabel",
        )
        self._admin_hint.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self._admin_btn = ttk.Button(
            admin_frame,
            text="Run as administrator…",
            command=self._attempt_admin,
        )
        self._admin_btn.grid(row=0, column=1, rowspan=2, sticky="e")
        self._admin_btn.state(["disabled"])
        self._admin_btn.grid_remove()

        subtitle = ttk.Label(
            self,
            text="Manage Windows Firewall and Defender realtime protection with verified toggles.",
            style="Caption.TLabel",
            wraplength=460,
        )
        subtitle.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 12))

        # Firewall section
        fw_frame = ttk.LabelFrame(self, text="Windows Firewall")
        fw_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(fw_frame, text="+", width=2, command=self._open_firewall).grid(row=0, column=0, padx=(0, 4))
        self._fw_switch = ttk.Checkbutton(
            fw_frame,
            variable=self._fw_var,
            command=self._on_fw_toggle,
            textvariable=self._fw_action_text,
        )
        self._fw_switch.grid(row=0, column=1, sticky="w")
        self._fw_status = ttk.Label(
            fw_frame,
            text="Status: ...",
            style="Status.Info.TLabel",
            wraplength=220,
        )
        self._fw_status.grid(row=0, column=2, sticky="e")
        ttk.Label(
            fw_frame,
            text="Applies to Domain, Private, and Public profiles in one step.",
            style="Caption.TLabel",
            wraplength=320,
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(
            fw_frame,
            textvariable=self._fw_pending_var,
            style="Caption.TLabel",
            wraplength=320,
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(4, 0))
        fw_frame.columnconfigure(1, weight=1)

        # Defender section
        rt_frame = ttk.LabelFrame(self, text="Microsoft Defender Realtime")
        rt_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(rt_frame, text="+", width=2, command=self._open_defender).grid(row=0, column=0, padx=(0, 4))
        self._rt_switch = ttk.Checkbutton(
            rt_frame,
            variable=self._rt_var,
            command=self._on_rt_toggle,
            textvariable=self._rt_action_text,
        )
        self._rt_switch.grid(row=0, column=1, sticky="w")
        self._rt_status = ttk.Label(
            rt_frame,
            text="Status: ...",
            style="Status.Info.TLabel",
            wraplength=220,
        )
        self._rt_status.grid(row=0, column=2, sticky="e")
        ttk.Label(
            rt_frame,
            text=(
                "Disabling stops realtime scanning and attempts to stop the WinDefend service; "
                "enabling restarts it."
            ),
            style="Caption.TLabel",
            wraplength=320,
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(
            rt_frame,
            textvariable=self._rt_pending_var,
            style="Caption.TLabel",
            wraplength=320,
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(4, 0))
        rt_frame.columnconfigure(1, weight=1)

        controls = ttk.Frame(self)
        controls.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        controls.columnconfigure(0, weight=1)

        # Refresh button
        self._refresh_btn = ttk.Button(controls, text="Refresh", command=self.refresh_async)
        self._refresh_btn.grid(row=0, column=1, sticky="e")

        self._auto_refresh_var = tk.BooleanVar(value=False)
        self._auto_refresh = ttk.Checkbutton(
            controls,
            text="Auto-refresh every 30s",
            variable=self._auto_refresh_var,
            command=self._on_auto_refresh_changed,
        )
        self._auto_refresh.grid(row=0, column=0, sticky="w")

        self._busy_var = tk.StringVar(value="")
        self._busy_lbl = ttk.Label(self, textvariable=self._busy_var, style="BusyCaption.TLabel")
        self._busy_bar = ttk.Progressbar(self, mode="indeterminate", length=180)

        self._report_var = tk.StringVar(
            value="Use the switches to apply changes. Results are verified automatically."
        )
        self._report_lbl = ttk.Label(
            self,
            textvariable=self._report_var,
            wraplength=440,
            style="Report.Pending.TLabel",
        )
        self._report_lbl.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        log_frame = ttk.LabelFrame(self, text="Activity log")
        log_frame.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._log = tk.Text(
            log_frame,
            height=7,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
        )
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=scroll.set)
        self._log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(8, weight=1)

        # Initial load
        self.refresh_async()

    # --------------------------- Event handlers ----------------------------

    def _on_fw_toggle(self):
        if self._updating_fw_var:
            return
        current = self._fw_state
        if current is None:
            self._append_log("Firewall toggle ignored because status is unknown.")
            messagebox.showwarning(
                "Security Center",
                "The current firewall status is unknown. Refresh the snapshot before changing it.",
            )
            self._set_fw_var(False)
            self._fw_pending_var.set("")
            return
        target = not current
        self._set_fw_var(current)
        self._fw_pending_var.set(f"Requested: {'Enable' if target else 'Disable'} firewall")
        self._append_log(f"Requesting firewall change -> {'on' if target else 'off'}")
        self._announce_pending("Applying firewall change…")
        self._set_status_badge(self._fw_status, "Status: applying change…", "info")
        self._disable_inputs()
        self._dispatcher.submit(
            "fw",
            lambda: self._apply_firewall(target),
            lambda ok: self._post_apply("fw", ok),
            lambda exc, trace: self._handle_async_failure("firewall", exc, trace),
        )

    def _on_rt_toggle(self):
        if self._updating_rt_var:
            return
        current = self._rt_state
        if current is None:
            self._append_log("Realtime toggle ignored because status is unknown.")
            messagebox.showwarning(
                "Security Center",
                "Realtime status is unknown. Refresh before applying changes.",
            )
            self._set_rt_var(False)
            self._rt_pending_var.set("")
            return
        target = not current
        self._set_rt_var(current)
        self._rt_pending_var.set(
            f"Requested: {'Enable' if target else 'Disable'} Defender realtime"
        )
        self._append_log(f"Requesting Defender realtime change -> {'on' if target else 'off'}")
        self._announce_pending("Updating Defender realtime…")
        self._set_status_badge(self._rt_status, "Status: applying change…", "info")
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
            self._append_log(f"{action} succeeded: {detail}")
        else:
            actors = ", ".join(outcome.blockers) if outcome.blockers else "unknown forces"
            message = f"{action} was blocked by {actors}."
            if outcome.detail:
                message = f"{message} Details: {outcome.detail}"
            self._update_report(message, success=False)
            messagebox.showerror("Operation blocked", message)
            self._append_log(f"{action} blocked: {message}")
        if kind == "fw":
            self._fw_pending_var.set("")
        elif kind == "rt":
            self._rt_pending_var.set("")
        self._end_busy()
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
        self._announce_pending("Refreshing security snapshot…")
        self._set_status_badge(self._fw_status, "Status: refreshing…", "info")
        self._set_status_badge(self._rt_status, "Status: refreshing…", "info")
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
        if admin:
            self._admin_hint.config(text="You have administrator control.")
            self._admin_btn.state(["disabled"])
            if self._run_admin_visible:
                self._admin_btn.grid_remove()
                self._run_admin_visible = False
        else:
            self._admin_hint.config(
                text="Elevation is required to apply firewall or Defender changes."
            )
            if not self._run_admin_visible:
                self._admin_btn.grid()
                self._run_admin_visible = True
            self._admin_btn.state(["!disabled"])

        if fw_enabled is None:
            self._fw_state = None
            self._set_fw_var(False)
            txt = "Status: unknown"
            tone = "warn"
            self._fw_action_text.set("Firewall status unknown")
        else:
            self._fw_state = bool(fw_enabled)
            self._set_fw_var(bool(fw_enabled))
            state_txt = "Enabled" if fw_enabled else "Disabled"
            txt = f"Status: {state_txt}"
            tone = "good" if fw_enabled else "bad"
            self._fw_action_text.set(
                "Turn Firewall Off" if fw_enabled else "Turn Firewall On"
            )
        if snapshot.firewall_blockers:
            txt += " | Block: " + ", ".join(snapshot.firewall_blockers)
            tone = "bad"
        self._set_status_badge(self._fw_status, txt, tone)

        rt = ds.realtime_enabled
        svc = ds.service_state or "UNKNOWN"
        tamper = ds.tamper_protection
        rt_txt = []
        if rt is None:
            rt_txt.append("RT: unknown")
            self._rt_state = None
            self._set_rt_var(False)
            self._rt_action_text.set("Realtime status unknown")
        else:
            rt_txt.append("RT: on" if rt else "RT: off")
            self._rt_state = bool(rt)
            self._set_rt_var(bool(rt))
            self._rt_action_text.set(
                "Turn Defender Off" if rt else "Turn Defender On"
            )
        rt_txt.append(f"SVC: {svc}")
        if tamper is not None:
            rt_txt.append(f"TP: {'on' if tamper else 'off'}")
        rt_tone = "warn" if rt is None else ("good" if rt else "bad")
        if ds.blockers:
            rt_txt.append("Block: " + ", ".join(ds.blockers))
            rt_tone = "bad"
        self._set_status_badge(
            self._rt_status,
            "Status: " + " | ".join(rt_txt),
            rt_tone,
        )
        self._rt_pending_var.set("")
        self._fw_pending_var.set("")
        if not admin:
            if fw_enabled is None:
                self._fw_action_text.set("Admin required (status unknown)")
            else:
                self._fw_action_text.set("Admin required for firewall")
            if rt is None:
                self._rt_action_text.set("Admin required (status unknown)")
            else:
                self._rt_action_text.set("Admin required for Defender")
        now = datetime.now().strftime("%H:%M:%S")
        self._last_refresh_var.set(f"Last updated: {now}")
        fw_status = "on" if fw_enabled else ("off" if fw_enabled is not None else "unknown")
        rt_status = "on" if rt else ("off" if rt is not None else "unknown")
        self._append_log(
            f"Snapshot refreshed (admin={'yes' if admin else 'no'}, firewall={fw_status}, realtime={rt_status})"
        )
        self._enable_inputs(admin)
        self._end_busy()

    def _handle_async_failure(self, label: str, exc: BaseException, trace: str) -> None:
        print(trace, file=sys.stderr)
        msg = (
            f"An unexpected error occurred while processing {label} actions."
            " Check logs for details."
        )
        self._update_report(msg, success=False)
        messagebox.showerror("Security Center", msg)
        self._enable_inputs(False)
        self._append_log(f"{label.capitalize()} action failed: {exc}")
        self._end_busy()

    def _update_report(self, text: str, *, success: bool) -> None:
        prefix = "Last action: "
        self._report_var.set(prefix + text)
        self._report_lbl.configure(
            style="Report.Success.TLabel" if success else "Report.Failure.TLabel"
        )

    def _announce_pending(self, text: str) -> None:
        self._report_var.set(text)
        self._report_lbl.configure(style="Report.Pending.TLabel")
        self._begin_busy(text)

    def _set_status_badge(self, label: ttk.Label, message: str, tone: str) -> None:
        mapping = {
            "good": "Status.Good.TLabel",
            "bad": "Status.Bad.TLabel",
            "warn": "Status.Warn.TLabel",
            "info": "Status.Info.TLabel",
        }
        label.config(text=message, style=mapping.get(tone, "Status.Info.TLabel"))

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
        if admin and self._fw_state is not None:
            self._fw_switch.state(["!disabled"])
        else:
            self._fw_switch.state(["disabled"])
        if admin and self._rt_state is not None:
            self._rt_switch.state(["!disabled"])
        else:
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

    # ------------------------------- Busy/UI helpers ------------------------

    def _begin_busy(self, message: str) -> None:
        self._busy_messages.append(message)
        self._busy_var.set(message)
        if len(self._busy_messages) == 1:
            self._busy_lbl.grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 4))
            self._busy_bar.grid(row=6, column=1, sticky="e", pady=(12, 4))
            self._busy_bar.start(12)

    def _end_busy(self) -> None:
        if not self._busy_messages:
            return
        self._busy_messages.pop()
        if self._busy_messages:
            self._busy_var.set(self._busy_messages[-1])
            return
        self._busy_var.set("")
        self._busy_bar.stop()
        self._busy_lbl.grid_remove()
        self._busy_bar.grid_remove()

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert("end", f"[{timestamp}] {message}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_fw_var(self, value: bool) -> None:
        self._updating_fw_var = True
        try:
            self._fw_var.set(value)
        finally:
            self._updating_fw_var = False

    def _set_rt_var(self, value: bool) -> None:
        self._updating_rt_var = True
        try:
            self._rt_var.set(value)
        finally:
            self._updating_rt_var = False

    def _attempt_admin(self) -> None:
        self._append_log("Attempting to relaunch Security Center with elevation…")
        if security.relaunch_security_center():
            self._update_report(
                "Elevation requested. Accept the Windows UAC prompt to continue.",
                success=True,
            )
            self._append_log("Elevation relaunch initiated via ShellExecute.")
        else:
            messagebox.showinfo(
                "Security Center",
                "Unable to trigger elevation. Launch this tool from an administrator session instead.",
            )
            self._append_log("Elevation relaunch request was not issued (already admin or unsupported).")

    def _on_auto_refresh_changed(self) -> None:
        if self._auto_refresh_var.get():
            self._append_log("Auto-refresh enabled (30s cadence).")
            self._schedule_auto_refresh(initial=True)
        else:
            self._append_log("Auto-refresh disabled.")
            if self._auto_job is not None:
                try:
                    self.after_cancel(self._auto_job)
                except Exception:
                    pass
                self._auto_job = None

    def _schedule_auto_refresh(self, *, initial: bool = False) -> None:
        if not self._auto_refresh_var.get():
            return
        delay = 1000 if initial else 30000
        self._auto_job = self.after(delay, self._auto_refresh_tick)

    def _auto_refresh_tick(self) -> None:
        self._auto_job = None
        if not self._auto_refresh_var.get():
            return
        if self._refresh_btn.instate(["disabled"]):
            self._schedule_auto_refresh()
            return
        self._append_log("Auto-refresh cycle triggered.")
        self.refresh_async()
        self._schedule_auto_refresh()


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


#!/usr/bin/env python3
# error_handler.py — resilient error + warning capture with Tk dialogs and cooperative warning chaining

from __future__ import annotations

import atexit
import logging
import os
import platform
import queue
import sys
import threading
import time
import traceback
import warnings
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, Type
import weakref

# ---- typing-only tkinter alias so Pylance accepts annotations even if tk is None
if TYPE_CHECKING:
    import tkinter as tkt
    TkRoot = tkt.Misc  # type: ignore[valid-type]
else:
    TkRoot = Any  # runtime placeholder

try:  # GUI is optional
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except Exception:
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    scrolledtext = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------
# Public buffers
# -------------------------------------------------------------------------------------------------
RECENT_ERRORS: list[str] = []
RECENT_WARNINGS: list[str] = []
_MAX_LOGS = 50

# -------------------------------------------------------------------------------------------------
# Internal state
# -------------------------------------------------------------------------------------------------
@dataclass
class _Hooks:
    sys_excepthook: Callable[..., Any]
    threading_excepthook: Optional[Callable[..., Any]]
    sys_unraisablehook: Optional[Callable[..., Any]]

_state_lock = threading.RLock()
_installed = False

# Warning chain: our wrapper stays installed; we forward to downstream target.
_downstream_showwarning: Callable[..., Any] = warnings.showwarning  # updated dynamically
_logging_showwarning = getattr(logging, "_showwarning", None)  # for dedupe heuristic
_warn_popups = os.getenv("COOLBOX_WARNINGS_POPUP", "0") == "1"
_log_warnings = True  # can be toggled via install()

# Guard recursion if logging handlers emit warnings
_tls = threading.local()  # .in_warning set when inside _chain_showwarning

# Tk UI pump
_UI_QUEUE: "queue.Queue[Tuple[str, str, str]]" = queue.Queue()
_PUMP_STARTED = False
_root_ref: "weakref.ReferenceType[Any] | None" = None

# Watchdog
_watchdog_thread: Optional[threading.Thread] = None
_watchdog_stop = threading.Event()
_last_seen_sw_id: int = id(warnings.showwarning)


# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------
def _record(buf: list[str], msg: str) -> None:
    buf.append(msg)
    if len(buf) > _MAX_LOGS:
        del buf[: len(buf) - _MAX_LOGS]


def _collect_context() -> str:
    try:
        return (
            f"platform={platform.platform()} "
            f"python={sys.executable} {sys.version.split()[0]} "
            f"cwd={os.getcwd()} "
            f"argv={' '.join(sys.argv)}"
        )
    except Exception as exc:
        return f"failed to collect context: {exc}"


def _get_log_file() -> Path | None:
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler):
            return Path(h.baseFilename)
    return None


# -------------------------------------------------------------------------------------------------
# UI pump
# -------------------------------------------------------------------------------------------------
def _start_ui_pump(root: TkRoot) -> None:
    global _PUMP_STARTED, _root_ref
    if _PUMP_STARTED:
        return
    _PUMP_STARTED = True
    _root_ref = weakref.ref(root)

    def _poll() -> None:
        try:
            while True:
                kind, message, details = _UI_QUEUE.get_nowait()
                try:
                    if kind == "error":
                        _show_error_dialog(message, details)
                    else:
                        _show_error_dialog(f"Warning: {message}", details)
                except Exception:
                    logger.exception("UI pump failed to show dialog")
        except queue.Empty:
            pass
        try:
            r = _root_ref() if _root_ref else None
            if r is not None:
                r.after(200, _poll)
        except Exception:
            # root destroyed
            pass

    try:
        root.after(200, _poll)
    except Exception:
        logger.debug("Failed to start UI pump", exc_info=True)


def _enqueue_ui(kind: str, message: str, details: str) -> None:
    try:
        _UI_QUEUE.put_nowait((kind, message, details))
    except Exception:
        logger.debug("Failed to enqueue UI job", exc_info=True)


# -------------------------------------------------------------------------------------------------
# Dialogs
# -------------------------------------------------------------------------------------------------
def _show_error_dialog(message: str, details: str) -> None:
    # Non-main threads must enqueue
    if tk is not None and threading.current_thread() is not threading.main_thread():
        _enqueue_ui("error", message, details)
        return

    # Headless or tests
    if tk is None:
        if messagebox is not None:
            try:
                messagebox.showerror("Unexpected Error", f"{message}\n\n{details}")
            except Exception:
                logger.exception("Failed to display error dialog (headless)")
                logger.error("Unhandled exception: %s\n%s", message, details)
        else:
            logger.error("Unhandled exception: %s\n%s", message, details)
        return

    try:
        # Prefer ModernErrorDialog if available
        try:
            import customtkinter as ctk  # type: ignore
            from src.components.modern_error_dialog import ModernErrorDialog  # type: ignore

            root = tk._default_root  # type: ignore[attr-defined]
            created_root = False
            if root is None or not getattr(root, "winfo_exists", lambda: False)():
                root = ctk.CTk()  # type: ignore
                root.withdraw()
                created_root = True

            dialog = ModernErrorDialog(root, message, details, _get_log_file())
            root.wait_window(dialog)
            if created_root:
                root.destroy()
            return
        except Exception:
            pass

        # Basic Tk dialog
        root = tk._default_root  # type: ignore[attr-defined]
        created_root = False
        if root is None or not getattr(root, "winfo_exists", lambda: False)():
            root = tk.Tk()  # type: ignore[call-arg]
            root.withdraw()
            created_root = True

        dialog = tk.Toplevel(root)  # type: ignore[call-arg]
        dialog.title("Unexpected Error")
        dialog.resizable(True, True)

        ttk.Label(dialog, text=message, padding=10).pack()  # type: ignore[attr-defined]

        text = scrolledtext.ScrolledText(dialog, width=80, height=20)  # type: ignore[attr-defined]
        text.insert("1.0", details)
        text.configure(state="disabled")
        text.pack_forget()

        def toggle() -> None:
            if text.winfo_manager():
                text.pack_forget()
                more_btn.configure(text="See details")
            else:
                text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
                more_btn.configure(text="Hide details")

        more_btn = ttk.Button(dialog, text="See details", command=toggle)  # type: ignore[attr-defined]
        more_btn.pack(pady=(0, 5))

        log_file = _get_log_file()
        if log_file is not None:
            def open_log() -> None:
                try:
                    webbrowser.open(log_file.as_uri())
                except Exception:
                    if messagebox is not None:
                        messagebox.showinfo("Error Details", f"Log file located at {log_file}")
            ttk.Button(dialog, text="Open Log", command=open_log).pack(pady=(0, 5))  # type: ignore[attr-defined]

        ttk.Button(dialog, text="OK", command=dialog.destroy).pack(pady=(0, 10))  # type: ignore[attr-defined]

        dialog.transient(root)
        dialog.grab_set()
        root.wait_window(dialog)
        if created_root:
            root.destroy()
    except Exception as dialog_error:
        logger.exception("Failed to display error dialog")
        try:
            tb = "".join(traceback.format_exception(type(dialog_error), dialog_error, dialog_error.__traceback__))
            _record(RECENT_ERRORS, f"{datetime.now().isoformat()}:DialogError:show_error_dialog:{dialog_error}\n{tb}")
        except Exception:
            logger.debug("Failed to record dialog error", exc_info=True)
        if messagebox is not None:
            try:
                messagebox.showerror("Unexpected Error", f"{message}\n\n{details}")
            except Exception:
                logger.error("Unhandled exception: %s\n%s", message, details)
        else:
            logger.error("Unhandled exception: %s\n%s", message, details)


# -------------------------------------------------------------------------------------------------
# Exception handling
# -------------------------------------------------------------------------------------------------
def handle_exception(exc: Type[BaseException], value: BaseException, tb) -> None:
    timestamp = datetime.now().isoformat()
    if tb is not None:
        last = traceback.extract_tb(tb)[-1]
        location = f"{last.filename}:{last.lineno}"
    else:
        location = "unknown location"

    logger.error(
        "Unhandled exception %s at %s on %s", exc.__name__, location, timestamp,
        exc_info=(exc, value, tb),
    )

    tb_str = "".join(traceback.format_exception(exc, value, tb))
    context = _collect_context()
    _record(RECENT_ERRORS, f"{timestamp}:{exc.__name__}:{location}:{value}\n{context}\n{tb_str}")

    if isinstance(value, OSError):
        desc = f"I/O error: {value}"
    elif isinstance(value, ValueError):
        desc = f"Invalid value: {value}"
    else:
        desc = str(value)

    msg = f"{desc} (at {location} on {timestamp})"
    details = "\n".join([
        f"Exception: {exc.__name__}",
        f"Message: {value}",
        f"Location: {location}",
        f"Time: {timestamp}",
        f"Context: {context}",
        "Traceback:",
        tb_str,
    ])
    _show_error_dialog(msg, details)


# -------------------------------------------------------------------------------------------------
# Warnings: cooperative chain that never spams
# -------------------------------------------------------------------------------------------------
def _chain_showwarning(message, category, filename, lineno, file=None, line=None):
    # prevent recursion if downstream logs or warns
    if getattr(_tls, "in_warning", False):
        # still forward to downstream to preserve behavior
        try:
            _downstream_showwarning(message, category, filename, lineno, file=file, line=line)
        except Exception:
            logger.debug("downstream showwarning failed during recursion", exc_info=True)
        return

    _tls.in_warning = True
    try:
        # Normalize and record
        ts = datetime.now().isoformat()
        text = f"{ts}:{filename}:{lineno}:{category.__name__}:{message}"
        _record(RECENT_WARNINGS, text)

        # Optional popup
        if _warn_popups:
            title = f"{category.__name__} at {filename}:{lineno}"
            if tk is not None and threading.current_thread() is threading.main_thread():
                _show_error_dialog(title, text)
            else:
                _enqueue_ui("warning", title, text)

        # Log once if downstream is not logging's _showwarning
        if _log_warnings and _downstream_showwarning is not _logging_showwarning:
            logger.warning(text)

        # Always forward so other systems observe the warning
        try:
            _downstream_showwarning(message, category, filename, lineno, file=file, line=line)
        except Exception:
            logger.debug("downstream showwarning raised", exc_info=True)
    finally:
        _tls.in_warning = False


def _rechain_showwarning_if_stomped() -> None:
    # If someone overwrote warnings.showwarning, capture it as downstream and restore our chain
    global _downstream_showwarning, _last_seen_sw_id
    current = warnings.showwarning
    cur_id = id(current)
    if current is _chain_showwarning:
        _last_seen_sw_id = cur_id
        return
    if cur_id != _last_seen_sw_id:
        _downstream_showwarning = current  # update downstream target
        warnings.showwarning = _chain_showwarning  # keep us on top
        _last_seen_sw_id = id(warnings.showwarning)  # now our id
        # No user-visible warning. Quiet self-heal.


# -------------------------------------------------------------------------------------------------
# Install / watchdog
# -------------------------------------------------------------------------------------------------
def _snapshot_hooks() -> _Hooks:
    return _Hooks(
        sys_excepthook=sys.excepthook,
        threading_excepthook=getattr(threading, "excepthook", None),
        sys_unraisablehook=getattr(sys, "unraisablehook", None),
    )


def _apply_hooks() -> None:
    sys.excepthook = handle_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: handle_exception(args.exc_type, args.exc_value, args.exc_traceback)  # type: ignore[attr-defined]
    if hasattr(sys, "unraisablehook"):
        def _unraisable(args):
            exc = args.exc_type or type(args.exc_value)
            handle_exception(exc, args.exc_value, args.exc_traceback)
        sys.unraisablehook = _unraisable  # type: ignore[attr-defined]

    # Install our warning chain on top of whatever is there
    global _downstream_showwarning, _last_seen_sw_id
    _downstream_showwarning = warnings.showwarning
    warnings.showwarning = _chain_showwarning
    _last_seen_sw_id = id(warnings.showwarning)


def _start_watchdog() -> None:
    global _watchdog_thread
    if _watchdog_thread and _watchdog_thread.is_alive():
        return
    _watchdog_stop.clear()

    def _run():
        # fast first pass, then slower
        deadline = time.time() + 1.0
        while not _watchdog_stop.wait(0.25):
            try:
                _rechain_showwarning_if_stomped()
                # repair hooks if someone replaced them
                if sys.excepthook is not handle_exception:
                    sys.excepthook = handle_exception
                if hasattr(threading, "excepthook") and threading.excepthook is not None:
                    if getattr(threading.excepthook, "__name__", "") != "<lambda>":
                        threading.excepthook = lambda args: handle_exception(args.exc_type, args.exc_value, args.exc_traceback)  # type: ignore[attr-defined]
                if hasattr(sys, "unraisablehook") and getattr(sys, "unraisablehook", None) is not None:
                    if getattr(sys.unraisablehook, "__name__", "") != "_unraisable":
                        def _unraisable(args):
                            exc = args.exc_type or type(args.exc_value)
                            handle_exception(exc, args.exc_value, args.exc_traceback)
                        sys.unraisablehook = _unraisable  # type: ignore[attr-defined]
            except Exception:
                logger.debug("watchdog repair failed", exc_info=True)
            # After first second, back off to 2s intervals
            if time.time() > deadline:
                break
        # slower cadence
        while not _watchdog_stop.wait(2.0):
            try:
                _rechain_showwarning_if_stomped()
            except Exception:
                logger.debug("watchdog slow check failed", exc_info=True)

    _watchdog_thread = threading.Thread(target=_run, name="error-handler-watchdog", daemon=True)
    _watchdog_thread.start()


def _patch_tk_for_future_roots() -> None:
    if tk is None:
        return
    try:
        orig_init = tk.Tk.__init__  # type: ignore[attr-defined]

        def _wrapped(self, *a, **kw):
            orig_init(self, *a, **kw)
            try:
                self.report_callback_exception = handle_exception  # type: ignore[attr-defined]
            except Exception:
                pass
            _start_ui_pump(self)

        if getattr(tk.Tk.__init__, "__name__", "") != "_wrapped":  # type: ignore[attr-defined]
            tk.Tk.__init__ = _wrapped  # type: ignore[assignment]
    except Exception:
        logger.debug("Failed to patch tk.Tk.__init__", exc_info=True)


def install(window: TkRoot | None = None, *, warn_popups: Optional[bool] = None, log_warnings: Optional[bool] = None) -> None:
    """Install global hooks and cooperative warning capture. Safe to call multiple times."""
    global _installed, _warn_popups, _log_warnings
    with _state_lock:
        if warn_popups is not None:
            _warn_popups = bool(warn_popups)
        if log_warnings is not None:
            _log_warnings = bool(log_warnings)

        if _installed:
            # refresh UI pump if a new window is supplied
            if tk is not None and window is not None:
                try:
                    window.report_callback_exception = handle_exception  # type: ignore[attr-defined]
                except Exception:
                    logger.debug("Failed to hook report_callback_exception", exc_info=True)
                _start_ui_pump(window)
            return

        _snapshot_hooks()  # not used now, kept for symmetry/future
        _apply_hooks()

        if tk is not None:
            root = window or getattr(tk, "_default_root", None)  # type: ignore[attr-defined]
            if root is not None:
                try:
                    root.report_callback_exception = handle_exception  # type: ignore[attr-defined]
                except Exception:
                    logger.debug("Failed to hook report_callback_exception", exc_info=True)
                _start_ui_pump(root)
            _patch_tk_for_future_roots()

        _start_watchdog()
        atexit.register(_drain_queue_at_exit)
        _installed = True


def uninstall() -> None:
    """Remove hooks and stop watchdog. Buffers remain."""
    global _installed
    with _state_lock:
        if not _installed:
            return
        try:
            # Restore just the warnings chain to current downstream target
            if warnings.showwarning is _chain_showwarning:
                warnings.showwarning = _downstream_showwarning
        except Exception:
            logger.debug("uninstall warnings restoration failed", exc_info=True)
        finally:
            _watchdog_stop.set()
            _installed = False


def _drain_queue_at_exit() -> None:
    # No GUI at shutdown; dump pending UI messages to logs
    try:
        while True:
            kind, message, details = _UI_QUEUE.get_nowait()
            tag = "Warning" if kind == "warning" else "Error"
            logger.error("Late UI %s at exit: %s\n%s", tag, message, details)
    except queue.Empty:
        pass


# -------------------------------------------------------------------------------------------------
# Health + test aids
# -------------------------------------------------------------------------------------------------
def health() -> dict[str, bool]:
    return {
        "installed": _installed,
        "warnings_chained": warnings.showwarning is _chain_showwarning,
        "ui_pump_running": _PUMP_STARTED,
        "has_tk": tk is not None,
    }


def trigger_test_error() -> None:
    raise RuntimeError("test error from trigger_test_error()")


def trigger_test_warning() -> None:
    warnings.warn("test warning from trigger_test_warning()", UserWarning)


__all__ = [
    "install",
    "uninstall",
    "handle_exception",
    "RECENT_ERRORS",
    "RECENT_WARNINGS",
    "health",
    "trigger_test_error",
    "trigger_test_warning",
]


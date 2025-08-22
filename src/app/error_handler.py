#!/usr/bin/env python3
# error_handler.py — guaranteed popups via auto-install on import, Tk + native + subprocess fallbacks, asyncio hook

from __future__ import annotations

import atexit
import argparse
import contextlib
import ctypes
import json
import logging
import os
import platform
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import warnings
import webbrowser
import weakref
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, Type, TypeVar

# -------- tkinter import (optional)
if TYPE_CHECKING:
    import tkinter as tkt
    TkRoot = tkt.Misc  # type: ignore[valid-type]
else:
    TkRoot = Any

logger = logging.getLogger(__name__)

# -------- env + headless
_HEADLESS = os.getenv("COOLBOX_LIGHTWEIGHT") == "1"
if not _HEADLESS and sys.platform.startswith("linux"):
    _HEADLESS = not bool(os.getenv("DISPLAY"))

# Auto-install defaults ON. Set COOLBOX_AUTO_INSTALL=0 to disable.
_AUTO_INSTALL = os.getenv("COOLBOX_AUTO_INSTALL", "1") == "1"
# Keep hidden root unless disabled.
_FORCE_GUI = os.getenv("COOLBOX_ERROR_UI_FORCE", "1") == "1"

if not _HEADLESS:
    try:
        import tkinter as tk  # type: ignore
        from tkinter import messagebox, scrolledtext, ttk  # type: ignore
    except Exception:
        tk = None  # type: ignore[assignment]
        messagebox = None  # type: ignore[assignment]
        scrolledtext = None  # type: ignore[assignment]
        ttk = None  # type: ignore[assignment]
else:
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    scrolledtext = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

# -------- public buffers
RECENT_ERRORS: list[str] = []
RECENT_WARNINGS: list[str] = []
_MAX_LOGS = 50

# -------- internal state
@dataclass
class _Hooks:
    sys_excepthook: Callable[..., Any]
    threading_excepthook: Optional[Callable[..., Any]]
    sys_unraisablehook: Optional[Callable[..., Any]]

_state_lock = threading.RLock()
_installed = False
_orig_hooks: _Hooks | None = None

_downstream_showwarning: Callable[..., Any] = warnings.showwarning
_logging_showwarning = getattr(logging, "_showwarning", None)
_warn_popups = os.getenv("COOLBOX_WARNINGS_POPUP", "0") == "1"
_log_warnings = True
_tls = threading.local()

_UI_QUEUE: "queue.Queue[Tuple[str, str, str]]" = queue.Queue()
_PUMP_STARTED = False
_root_ref: "weakref.ReferenceType[Any] | None" = None
_persistent_root: Any | None = None
_want_persistent_root = _FORCE_GUI
_last_pump_activity = 0.0

_watchdog_thread: Optional[threading.Thread] = None
_watchdog_stop = threading.Event()
_last_seen_sw_id: int = id(warnings.showwarning)

_LAST_POPUP_AT: dict[str, float] = {}
_POPUP_INTERVAL_S = float(os.getenv("COOLBOX_POPUP_INTERVAL_S", "1.5"))

_NATIVE_FALLBACK_S = float(os.getenv("COOLBOX_NATIVE_FALLBACK_S", "1.0"))

# -------------------------------------------------------------------------------------------------
# helpers
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

def _now_s() -> float:
    return time.monotonic()

def _should_popup(key: str) -> bool:
    t = _now_s()
    last = _LAST_POPUP_AT.get(key, -1e9)
    if t - last >= _POPUP_INTERVAL_S:
        _LAST_POPUP_AT[key] = t
        return True
    return False

def _root_alive(r: Any | None) -> bool:
    try:
        return bool(r) and getattr(r, "winfo_exists", lambda: False)()
    except Exception:
        return False

def _current_root() -> Any | None:
    r = _root_ref() if _root_ref else None
    if _root_alive(r):
        return r
    if tk is not None:
        dr = getattr(tk, "_default_root", None)  # type: ignore[attr-defined]
        if _root_alive(dr):
            return dr
    if _root_alive(_persistent_root):
        return _persistent_root
    return None

def _pythonw_executable() -> str:
    if sys.platform.startswith("win"):
        p = Path(sys.executable)
        candidate = p.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable

# -------------------------------------------------------------------------------------------------
# subprocess popup fallback
def _spawn_popup_subprocess(title: str, body: str) -> None:
    body = body[:2000]
    script = r"""
import sys, ctypes, subprocess
try:
    import tkinter as tk
    from tkinter import messagebox
    r = tk.Tk(); r.withdraw()
    try: messagebox.showerror(sys.argv[1], sys.argv[2])
    finally:
        try: r.destroy()
        except Exception: pass
    raise SystemExit(0)
except Exception:
    pass
try:
    if sys.platform.startswith('win'):
        MB_OK=0x0; MB_SYSTEMMODAL=0x1000; MB_TOPMOST=0x40000; MB_ICONERROR=0x10
        ctypes.windll.user32.MessageBoxW(None, sys.argv[2], sys.argv[1], MB_OK|MB_SYSTEMMODAL|MB_TOPMOST|MB_ICONERROR)
        raise SystemExit(0)
except Exception:
    pass
try:
    if sys.platform=='darwin':
        subprocess.run(["osascript","-e",f'display alert "{sys.argv[1]}" message "{sys.argv[2]}" as critical'], check=False)
    else:
        for cmd in (["zenity","--error","--no-wrap","--title",sys.argv[1],"--text",sys.argv[2]],
                    ["kdialog","--error",f"{sys.argv[1]}\n\n{sys.argv[2]}"]):
            try: subprocess.run(cmd, check=False)
            except Exception: continue
except Exception:
    pass
"""
    try:
        subprocess.Popen(
            [_pythonw_executable(), "-c", script, title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(0x00000008 if sys.platform.startswith("win") else 0),
        )
    except Exception:
        logger.error("Failed to spawn popup subprocess", exc_info=True)

# -------------------------------------------------------------------------------------------------
# native OS dialog (same process)
def _native_error_dialog(title: str, body: str) -> None:
    if _HEADLESS:
        logger.error("%s\n%s", title, body)
        return
    try:
        if sys.platform.startswith("win"):
            MB_OK = 0x0; MB_SYSTEMMODAL = 0x1000; MB_TOPMOST = 0x40000; MB_ICONERROR = 0x10
            ctypes.windll.user32.MessageBoxW(None, body, title, MB_OK | MB_SYSTEMMODAL | MB_TOPMOST | MB_ICONERROR)  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e", f'display alert "{title}" message "{body[:900].replace("\"","\\\"")}" as critical'],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return
        for cmd in (["zenity", "--error", "--no-wrap", "--title", title, "--text", body[:2000]],
                    ["kdialog", "--error", f"{title}\n\n{body[:2000]}"]):
            try:
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return
            except Exception:
                continue
    except Exception:
        pass
    logger.error("Native fallback dialog:\n%s\n%s", title, body)

# -------------------------------------------------------------------------------------------------
# UI pump
def _start_ui_pump(root: TkRoot) -> None:
    global _PUMP_STARTED, _root_ref
    try:
        _root_ref = weakref.ref(root)
    except Exception:
        _root_ref = None
    _PUMP_STARTED = False

    def _poll() -> None:
        global _PUMP_STARTED, _last_pump_activity
        drained = False
        try:
            while True:
                kind, message, details = _UI_QUEUE.get_nowait()
                drained = True
                _last_pump_activity = time.monotonic()
                try:
                    if kind == "error":
                        _show_error_dialog(message, details)
                    else:
                        _show_error_dialog(f"Warning: {message}", details)
                except Exception:
                    logger.exception("UI pump failed to show dialog")
        except queue.Empty:
            pass

        r = _current_root()
        if _root_alive(r):
            try:
                r.after(200, _poll)
                _PUMP_STARTED = True
                if drained:
                    _last_pump_activity = time.monotonic()
            except Exception:
                _PUMP_STARTED = False
        else:
            _PUMP_STARTED = False

    r = _current_root() or root
    try:
        r.after(200, _poll)
        _PUMP_STARTED = True
    except Exception:
        logger.debug("Failed to start UI pump", exc_info=True)
        _PUMP_STARTED = False

def _enqueue_ui(kind: str, message: str, details: str) -> None:
    try:
        _UI_QUEUE.put_nowait((kind, message, details))
    except Exception:
        logger.debug("Failed to enqueue UI job", exc_info=True)
    _kick_ui(kind, message, details)

def _kick_ui(kind: str, message: str, details: str) -> None:
    if tk is None:
        title = "Unexpected Error" if kind == "error" else "Warning"
        body = f"{message}\n\n{details[:2000]}"
        _native_error_dialog(title, body)
        _spawn_popup_subprocess(title, body)
        return

    r = _current_root()
    if not _root_alive(r) and _want_persistent_root:
        r = _ensure_hidden_root(persistent=True)
    if _root_alive(r) and not _PUMP_STARTED:
        _start_ui_pump(r)

    enqueue_ts = time.monotonic()

    def _fallback_probe() -> None:
        time.sleep(_NATIVE_FALLBACK_S)
        stagnant = (not _PUMP_STARTED) or (_last_pump_activity < enqueue_ts)
        if stagnant:
            title = "Unexpected Error" if kind == "error" else "Warning"
            body = f"{message}\n\n{details[:2000]}"
            _native_error_dialog(title, body)
            _spawn_popup_subprocess(title, body)

    threading.Thread(target=_fallback_probe, name="error-handler-fallback", daemon=True).start()

# -------------------------------------------------------------------------------------------------
# hidden root
def _ensure_hidden_root(persistent: bool) -> TkRoot | None:
    global _persistent_root
    if tk is None:
        return None
    r = _current_root()
    if _root_alive(r):
        return r
    try:
        try:
            import customtkinter as ctk  # type: ignore
            r = ctk.CTk()  # type: ignore
        except Exception:
            r = tk.Tk()  # type: ignore[call-arg]
        r.withdraw()
        setattr(r, "_cbx_err_persistent", bool(persistent))
        _persistent_root = r
        try:
            tk._default_root = r  # type: ignore[attr-defined]
        except Exception:
            pass
        _start_ui_pump(r)
        return r
    except Exception:
        logger.debug("Failed to create hidden root", exc_info=True)
        return None

# -------------------------------------------------------------------------------------------------
# dialogs
def _show_error_dialog(message: str, details: str) -> None:
    # non-main thread → enqueue
    if tk is not None and threading.current_thread() is not threading.main_thread():
        if _want_persistent_root:
            _ensure_hidden_root(persistent=True)
        _enqueue_ui("error", message, details)
        return

    if tk is None:
        diag = diagnose_ui()
        logger.error("Unhandled exception: %s\n%s\nUI diagnostics: %s", message, details, diag)
        return

    if not _should_popup(f"E:{message.splitlines()[0][:200]}"):
        logger.error("Suppressed popup: %s\n%s", message, details)
        return

    root = _current_root()
    if not _root_alive(root):
        root = _ensure_hidden_root(persistent=_want_persistent_root)
    if not _root_alive(root):
        title = "Unexpected Error"; body = f"{message}\n\n{details[:2000]}"
        _native_error_dialog(title, body); _spawn_popup_subprocess(title, body); return

    try:
        # Prefer modern dialog
        try:
            import customtkinter as ctk  # type: ignore
            from src.components.modern_error_dialog import ModernErrorDialog  # type: ignore
            dialog = ModernErrorDialog(root, message, details, _get_log_file())
            root.wait_window(dialog); return
        except Exception:
            pass

        dialog = tk.Toplevel(root)  # type: ignore[call-arg]
        dialog.title("Unexpected Error"); dialog.resizable(True, True)
        ttk.Label(dialog, text=message, padding=10).pack()  # type: ignore[attr-defined]
        text = scrolledtext.ScrolledText(dialog, width=80, height=20)  # type: ignore[attr-defined]
        text.insert("1.0", details); text.configure(state="disabled"); text.pack_forget()

        def toggle() -> None:
            if text.winfo_manager():
                text.pack_forget(); more_btn.configure(text="See details")
            else:
                text.pack(fill="both", expand=True, padx=10, pady=(0, 10)); more_btn.configure(text="Hide details")

        more_btn = ttk.Button(dialog, text="See details", command=toggle)  # type: ignore[attr-defined]
        more_btn.pack(pady=(0, 5))

        log_file = _get_log_file()
        if log_file is not None:
            def open_log() -> None:
                try: webbrowser.open(log_file.as_uri())
                except Exception:
                    if messagebox is not None:
                        messagebox.showinfo("Error Details", f"Log file located at {log_file}")
            ttk.Button(dialog, text="Open Log", command=open_log).pack(pady=(0, 5))  # type: ignore[attr-defined]

        ttk.Button(dialog, text="OK", command=dialog.destroy).pack(pady=(0, 10))  # type: ignore[attr-defined]
        dialog.transient(root); dialog.grab_set(); root.wait_window(dialog)
    except Exception as dialog_error:
        logger.exception("Failed to display error dialog")
        try:
            tb = "".join(traceback.format_exception(type(dialog_error), dialog_error, dialog_error.__traceback__))
            _record(RECENT_ERRORS, f"{datetime.now().isoformat()}:DialogError:show_error_dialog:{dialog_error}\n{tb}")
        except Exception:
            logger.debug("Failed to record dialog error", exc_info=True)
        title = "Unexpected Error"; body = f"{message}\n\n{details[:2000]}"
        _native_error_dialog(title, body); _spawn_popup_subprocess(title, body)

# -------------------------------------------------------------------------------------------------
# exception handling
def handle_exception(exc: Type[BaseException], value: BaseException, tb) -> None:
    ts = datetime.now().isoformat()
    if tb is not None:
        last = traceback.extract_tb(tb)[-1]; location = f"{last.filename}:{last.lineno}"
    else:
        location = "unknown location"

    logger.error("Unhandled exception %s at %s on %s", exc.__name__, location, ts, exc_info=(exc, value, tb))
    tb_str = "".join(traceback.format_exception(exc, value, tb))
    context = _collect_context()
    _record(RECENT_ERRORS, f"{ts}:{exc.__name__}:{location}:{value}\n{context}\n{tb_str}")

    desc = f"I/O error: {value}" if isinstance(value, OSError) else (f"Invalid value: {value}" if isinstance(value, ValueError) else str(value))
    msg = f"{desc} (at {location} on {ts})"
    details = "\n".join([f"Exception: {exc.__name__}", f"Message: {value}", f"Location: {location}", f"Time: {ts}", f"Context: {context}", "Traceback:", tb_str])
    _show_error_dialog(msg, details)

def _last_resort_report(exc: Type[BaseException], value: BaseException, tb, handler_error: BaseException, log_error: BaseException | None = None) -> None:
    try:
        details = "".join(traceback.format_exception(exc, value, tb))
        details += "\nHandlerError:\n" + "".join(traceback.format_exception(type(handler_error), handler_error, handler_error.__traceback__))
        if log_error is not None:
            details += "\nLoggingError:\n" + "".join(traceback.format_exception(type(log_error), log_error, log_error.__traceback__))
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".log", prefix="error_handler_") as tmp:
            tmp.write(details); path = tmp.name
    except Exception:
        path = None
    msg = f"Critical failure in error handler: {handler_error}. Original {exc.__name__}: {value}."
    if path: msg += f" Details written to {path}."
    msg += "\n"
    for s in {sys.stderr, getattr(sys, "__stderr__", sys.stderr)}:
        try: s.write(msg); s.flush()
        except Exception: pass

def safe_handle_exception(exc: Type[BaseException], value: BaseException, tb) -> None:
    try:
        handle_exception(exc, value, tb)
    except Exception as handler_error:  # pragma: no cover
        log_error: BaseException | None = None
        try: logger.error("Error handler failed: %s", handler_error, exc_info=True)
        except Exception as le: log_error = le
        _last_resort_report(exc, value, tb, handler_error, log_error)

T = TypeVar("T")
def guard(func: Callable[..., T], *args, **kwargs) -> Optional[T]:
    try: return func(*args, **kwargs)
    except Exception as exc:  # pragma: no cover
        safe_handle_exception(type(exc), exc, exc.__traceback__); return None

@contextlib.contextmanager
def error_boundary(*, reraise: bool = False):
    try: yield
    except Exception as exc:  # pragma: no cover
        safe_handle_exception(type(exc), exc, exc.__traceback__)
        if reraise: raise

# -------------------------------------------------------------------------------------------------
# warnings
def _chain_showwarning(message, category, filename, lineno, file=None, line=None):
    if getattr(_tls, "in_warning", False):
        try: _downstream_showwarning(message, category, filename, lineno, file=file, line=line)
        except Exception: logger.debug("downstream showwarning failed during recursion", exc_info=True)
        return
    _tls.in_warning = True
    try:
        ts = datetime.now().isoformat()
        text = f"{ts}:{filename}:{lineno}:{category.__name__}:{message}"
        _record(RECENT_WARNINGS, text)
        if _warn_popups:
            title = f"{category.__name__} at {filename}:{lineno}"
            if tk is not None and threading.current_thread() is threading.main_thread():
                if _should_popup(f"W:{filename}:{lineno}:{category.__name__}"):
                    _show_error_dialog(title, text)
            else:
                if _want_persistent_root: _ensure_hidden_root(persistent=True)
                _enqueue_ui("warning", title, text)
        if _log_warnings and _downstream_showwarning is not _logging_showwarning:
            logger.warning(text)
        try: _downstream_showwarning(message, category, filename, lineno, file=file, line=line)
        except Exception: logger.debug("downstream showwarning raised", exc_info=True)
    finally:
        _tls.in_warning = False

def _rechain_showwarning_if_stomped() -> None:
    global _downstream_showwarning, _last_seen_sw_id
    current = warnings.showwarning; cur_id = id(current)
    if current is _chain_showwarning:
        _last_seen_sw_id = cur_id; return
    if cur_id != _last_seen_sw_id:
        _downstream_showwarning = current; warnings.showwarning = _chain_showwarning; _last_seen_sw_id = id(warnings.showwarning)

# -------------------------------------------------------------------------------------------------
# asyncio hook
def _install_asyncio_on_loop(loop: Any) -> None:
    try:
        def _asyncio_handler(loop, context):
            exc = context.get("exception")
            msg = context.get("message") or "asyncio unhandled error"
            if exc is None:
                safe_handle_exception(RuntimeError, RuntimeError(msg), None)
            else:
                safe_handle_exception(type(exc), exc, exc.__traceback__)
        loop.set_exception_handler(_asyncio_handler)
    except Exception:
        logger.debug("Failed to set asyncio exception handler", exc_info=True)

def _patch_asyncio() -> None:
    try:
        import asyncio
    except Exception:
        return
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
            except Exception:
                loop = None
        if loop is not None:
            _install_asyncio_on_loop(loop)
    except Exception:
        logger.debug("Asyncio default loop hook failed", exc_info=True)
    try:
        orig_new_event_loop = asyncio.new_event_loop
        def _wrapped_new_event_loop():
            l = orig_new_event_loop()
            try: _install_asyncio_on_loop(l)
            except Exception: pass
            return l
        if getattr(asyncio.new_event_loop, "__name__", "") != "_wrapped_new_event_loop":
            asyncio.new_event_loop = _wrapped_new_event_loop  # type: ignore[assignment]
    except Exception:
        logger.debug("Asyncio new_event_loop patch failed", exc_info=True)

# -------------------------------------------------------------------------------------------------
# install/uninstall/watchdog
def _snapshot_hooks() -> _Hooks:
    return _Hooks(sys_excepthook=sys.excepthook, threading_excepthook=getattr(threading, "excepthook", None), sys_unraisablehook=getattr(sys, "unraisablehook", None))

def _apply_hooks() -> None:
    sys.excepthook = handle_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda a: handle_exception(a.exc_type, a.exc_value, a.exc_traceback)  # type: ignore[attr-defined]
    if hasattr(sys, "unraisablehook"):
        def _unraisable(args):
            exc = args.exc_type or type(args.exc_value)
            handle_exception(exc, args.exc_value, args.exc_traceback)
        sys.unraisablehook = _unraisable  # type: ignore[attr-defined]
    global _downstream_showwarning, _last_seen_sw_id
    _downstream_showwarning = warnings.showwarning
    warnings.showwarning = _chain_showwarning
    _last_seen_sw_id = id(warnings.showwarning)
    _patch_asyncio()

def _start_watchdog() -> None:
    global _watchdog_thread
    if _watchdog_thread and _watchdog_thread.is_alive():
        return
    _watchdog_stop.clear()

    def _run():
        until = time.time() + 1.0
        while not _watchdog_stop.wait(0.25):
            try:
                _rechain_showwarning_if_stomped()
                if sys.excepthook is not handle_exception:
                    sys.excepthook = handle_exception
                if hasattr(threading, "excepthook") and threading.excepthook is not None:
                    if getattr(threading.excepthook, "__name__", "") != "<lambda>":
                        threading.excepthook = lambda a: handle_exception(a.exc_type, a.exc_value, a.exc_traceback)  # type: ignore[attr-defined]
                if hasattr(sys, "unraisablehook") and getattr(sys, "unraisablehook", None) is not None:
                    if getattr(sys.unraisablehook, "__name__", "") != "_unraisable":
                        def _unraisable(args):
                            exc = args.exc_type or type(args.exc_value)
                            handle_exception(exc, args.exc_value, args.exc_traceback)
                        sys.unraisablehook = _unraisable  # type: ignore[attr-defined]
            except Exception:
                logger.debug("watchdog repair failed", exc_info=True)
            if time.time() > until:
                break
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
            try: self.report_callback_exception = handle_exception  # type: ignore[attr-defined]
            except Exception: pass
            _start_ui_pump(self)
        if getattr(tk.Tk.__init__, "__name__", "") != "_wrapped":
            tk.Tk.__init__ = _wrapped  # type: ignore[assignment]
    except Exception:
        logger.debug("Failed to patch tk.Tk.__init__", exc_info=True)

def install(window: TkRoot | None = None, *, warn_popups: Optional[bool] = None, log_warnings: Optional[bool] = None, ensure_root: Optional[bool] = None) -> None:
    global _installed, _warn_popups, _log_warnings, _orig_hooks, _want_persistent_root
    with _state_lock:
        if warn_popups is not None: _warn_popups = bool(warn_popups)
        if log_warnings is not None: _log_warnings = bool(log_warnings)
        if ensure_root is None: ensure_root = _FORCE_GUI
        _want_persistent_root = bool(ensure_root)

        if _installed:
            if tk is not None and window is not None:
                try: window.report_callback_exception = handle_exception  # type: ignore[attr-defined]
                except Exception: logger.debug("Failed to hook report_callback_exception", exc_info=True)
                _start_ui_pump(window)
            return

        _orig_hooks = _snapshot_hooks()
        _apply_hooks()

        if tk is not None:
            root = window or _current_root()
            if root is None and _want_persistent_root:
                root = _ensure_hidden_root(persistent=True)
            if root is not None:
                try: root.report_callback_exception = handle_exception  # type: ignore[attr-defined]
                except Exception: logger.debug("Failed to hook report_callback_exception", exc_info=True)
                _start_ui_pump(root)
            _patch_tk_for_future_roots()

        _start_watchdog()
        atexit.register(_drain_queue_at_exit)
        _installed = True

def uninstall() -> None:
    global _installed, _orig_hooks
    with _state_lock:
        if not _installed: return
        try:
            if warnings.showwarning is _chain_showwarning:
                warnings.showwarning = _downstream_showwarning
            if _orig_hooks is not None:
                sys.excepthook = _orig_hooks.sys_excepthook
                if hasattr(threading, "excepthook") and _orig_hooks.threading_excepthook is not None:
                    threading.excepthook = _orig_hooks.threading_excepthook
                if hasattr(sys, "unraisablehook") and _orig_hooks.sys_unraisablehook is not None:
                    sys.unraisablehook = _orig_hooks.sys_unraisablehook
        except Exception:
            logger.debug("uninstall restoration failed", exc_info=True)
        finally:
            _watchdog_stop.set(); _installed = False; _orig_hooks = None

def _drain_queue_at_exit() -> None:
    try:
        while True:
            kind, message, details = _UI_QUEUE.get_nowait()
            tag = "Warning" if kind == "warning" else "Error"
            logger.error("Late UI %s at exit: %s\n%s", tag, message, details)
    except queue.Empty:
        pass

# -------------------------------------------------------------------------------------------------
# health + diagnostics
def health() -> dict[str, bool]:
    return {
        "installed": _installed,
        "warnings_chained": warnings.showwarning is _chain_showwarning,
        "ui_pump_running": _PUMP_STARTED,
        "has_tk": tk is not None,
        "headless": _HEADLESS,
    }

def diagnose_ui() -> dict[str, Any]:
    info: dict[str, Any] = {"headless": _HEADLESS, "tk_available": tk is not None, "display": os.getenv("DISPLAY")}
    if _HEADLESS:
        info["reason"] = "headless environment"; return info
    try:
        _tk = tk
        if _tk is None:
            import tkinter as _tk  # type: ignore
            info["tk_available"] = True
        r = _tk.Tk()  # type: ignore[call-arg]
        r.withdraw(); r.destroy()
        info["can_init_tk"] = True
    except Exception as exc:  # pragma: no cover
        info["reason"] = f"tk init failed: {exc}"
    return info

# -------------------------------------------------------------------------------------------------
# test aids
def trigger_test_error() -> None:
    raise RuntimeError("test error from trigger_test_error()")

def trigger_test_warning() -> None:
    warnings.warn("test warning from trigger_test_warning()", UserWarning)

def force_test_dialog(msg: str = "forced test") -> None:
    _show_error_dialog(msg, f"context: { _collect_context() }")

__all__ = [
    "install","uninstall","handle_exception","safe_handle_exception","guard","error_boundary",
    "RECENT_ERRORS","RECENT_WARNINGS","health","diagnose_ui","trigger_test_error","trigger_test_warning","force_test_dialog",
]

# -------------------------------------------------------------------------------------------------
# CLI
def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Error handler helper")
    parser.add_argument("--check", action="store_true", help="Install handler and print health")
    parser.add_argument("--trigger-error", action="store_true", help="Emit a test exception")
    parser.add_argument("--trigger-warning", action="store_true", help="Emit a test warning")
    parser.add_argument("--force-dialog", action="store_true", help="Show a forced dialog now")
    parser.add_argument("--diagnose-ui", action="store_true", help="Include GUI diagnostics")
    parser.add_argument("--ensure-root", action="store_true", help="Create hidden root if none exists")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall before exiting")
    args = parser.parse_args(argv)

    install(ensure_root=args.ensure_root if args.ensure_root is not None else None)

    if args.force_dialog:
        force_test_dialog("CLI forced dialog")

    if args.trigger_error:
        with error_boundary():
            trigger_test_error()
    if args.trigger_warning:
        with error_boundary():
            trigger_test_warning()

    info = health()
    if args.diagnose_ui:
        info["ui"] = diagnose_ui()
    print(json.dumps(info))
    if args.uninstall:
        uninstall()
    return 0 if info.get("installed") else 1

def main() -> int:
    return _cli()

# -------------------------------------------------------------------------------------------------
# auto-install on import (fixes “works once, not again” if your app skips install later)
def _auto_bootstrap() -> None:
    if not _AUTO_INSTALL:
        return
    try:
        install(ensure_root=True)
    except Exception:
        # never crash caller due to handler init
        try: logger.debug("auto-install failed", exc_info=True)
        except Exception: pass

_auto_bootstrap()

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

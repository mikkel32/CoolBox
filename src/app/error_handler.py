from __future__ import annotations

import logging
import os
import platform
import sys
import threading
import traceback
import warnings
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Type

try:  # pragma: no cover - imported lazily for GUI environments
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except Exception:  # pragma: no cover - tests run in headless mode
    tk = None  # type: ignore
    messagebox = None  # type: ignore

logger = logging.getLogger(__name__)

# In-memory buffers retaining recent errors and warnings so tests or other
# components can introspect what happened without parsing log files.
RECENT_ERRORS: list[str] = []
RECENT_WARNINGS: list[str] = []
_MAX_LOGS = 50


def _record(buf: list[str], msg: str) -> None:
    """Append ``msg`` to ``buf`` and trim the list to ``_MAX_LOGS`` entries."""
    buf.append(msg)
    if len(buf) > _MAX_LOGS:
        del buf[: len(buf) - _MAX_LOGS]


def _collect_context() -> str:
    """Return basic runtime context for diagnostic purposes."""
    try:
        return (
            f"platform={platform.platform()} "
            f"python={sys.executable} {sys.version.split()[0]} "
            f"cwd={os.getcwd()} "
            f"argv={' '.join(sys.argv)}"
        )
    except Exception as exc:  # pragma: no cover - extremely unlikely
        return f"failed to collect context: {exc}"


def _get_log_file() -> Path | None:
    """Return the first file handled by ``logger`` if available."""
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


def _show_error_dialog(message: str, details: str) -> None:
    """Display a friendly dialog with optional expandable details.

    The dialog uses ``tkinter`` when available and falls back to a simple
    ``messagebox.showerror`` or logging when running headless.  A *See details*
    button toggles visibility of the traceback and an *Open Log* button is
    provided when a log file is available.
    """

    # When Tk isn't available (e.g. during unit tests), fall back to
    # ``messagebox`` if possible or just log the error.
    if tk is None:
        if messagebox is not None:
            try:
                messagebox.showerror("Unexpected Error", f"{message}\n\n{details}")
            except Exception:  # pragma: no cover - best effort
                logger.error("Unhandled exception: %s\n%s", message, details)
        else:  # pragma: no cover - headless environment
            logger.error("Unhandled exception: %s\n%s", message, details)
        return

    try:  # pragma: no cover - UI logic not exercised in tests
        try:
            import customtkinter as ctk
            from src.components.modern_error_dialog import ModernErrorDialog

            root = tk._default_root
            created_root = False
            if root is None:
                root = ctk.CTk()
                root.withdraw()
                created_root = True

            dialog = ModernErrorDialog(root, message, details, _get_log_file())
            root.wait_window(dialog)
            if created_root:
                root.destroy()
            return
        except Exception:
            pass

        root = tk._default_root
        created_root = False
        if root is None:
            root = tk.Tk()
            root.withdraw()
            created_root = True

        dialog = tk.Toplevel(root)
        dialog.title("Unexpected Error")
        dialog.resizable(True, True)

        ttk.Label(dialog, text=message, padding=10).pack()

        text = scrolledtext.ScrolledText(dialog, width=80, height=20)
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

        more_btn = ttk.Button(dialog, text="See details", command=toggle)
        more_btn.pack(pady=(0, 5))

        log_file = _get_log_file()

        if log_file is not None:
            def open_log() -> None:
                try:
                    webbrowser.open(log_file.as_uri())
                except Exception:  # pragma: no cover - platform specific
                    if messagebox is not None:
                        messagebox.showinfo(
                            "Error Details", f"Log file located at {log_file}"
                        )

            ttk.Button(dialog, text="Open Log", command=open_log).pack(pady=(0, 5))

        ttk.Button(dialog, text="OK", command=dialog.destroy).pack(pady=(0, 10))

        dialog.transient(root)
        dialog.grab_set()
        root.wait_window(dialog)
        if created_root:
            root.destroy()
    except Exception:  # pragma: no cover - last resort fallback
        if messagebox is not None:
            try:
                messagebox.showerror("Unexpected Error", f"{message}\n\n{details}")
            except Exception:
                logger.error("Unhandled exception: %s\n%s", message, details)
        else:
            logger.error("Unhandled exception: %s\n%s", message, details)


def handle_exception(exc: Type[BaseException], value: BaseException, tb) -> None:
    """Log *value* with traceback and show a friendly error dialog.

    This function is used for ``sys.excepthook`` and Tk's
    ``report_callback_exception`` so any uncaught exceptions are routed here.
    """
    timestamp = datetime.now().isoformat()
    if tb is not None:
        last = traceback.extract_tb(tb)[-1]
        location = f"{last.filename}:{last.lineno}"
    else:
        location = "unknown location"

    logger.error(
        "Unhandled exception %s at %s on %s",
        exc.__name__,
        location,
        timestamp,
        exc_info=(exc, value, tb),
    )

    tb_str = "".join(traceback.format_exception(exc, value, tb))
    context = _collect_context()
    _record(
        RECENT_ERRORS,
        f"{timestamp}:{exc.__name__}:{location}:{value}\n{context}\n{tb_str}",
    )

    if isinstance(value, IOError):
        desc = f"An I/O error occurred: {value}"
    elif isinstance(value, ValueError):
        desc = f"Invalid value: {value}"
    else:
        desc = str(value)

    msg = f"{desc} (at {location} on {timestamp})"
    details_lines = [
        f"Exception: {exc.__name__}",
        f"Message: {value}",
        f"Location: {location}",
        f"Time: {timestamp}",
        f"Context: {context}",
        "Traceback:",
        tb_str,
    ]
    formatted_details = "\n".join(details_lines)
    _show_error_dialog(msg, formatted_details)


def install(window=None) -> None:
    """Install global hooks so all warnings and errors are logged."""

    def _thread_hook(args):
        if window is not None and hasattr(window, "after"):
            window.after(
                0,
                lambda: handle_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                ),
            )
        else:
            handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    def _unraisable_hook(args):
        exc = args.exc_type or type(args.exc_value)
        handle_exception(exc, args.exc_value, args.exc_traceback)

    sys.excepthook = handle_exception
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable_hook

    def _showwarning(message, category, filename, lineno, file=None, line=None):
        timestamp = datetime.now().isoformat()
        text = f"{timestamp}:{filename}:{lineno}:{category.__name__}:{message}"
        logger.warning(text)
        _record(RECENT_WARNINGS, text)

    warnings.showwarning = _showwarning
    logging.captureWarnings(True)

    if window is not None:
        window.report_callback_exception = handle_exception


__all__ = ["install", "handle_exception", "RECENT_ERRORS", "RECENT_WARNINGS"]

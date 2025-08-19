from __future__ import annotations

import logging
import os
import platform
import sys
import threading
import traceback
import warnings
import webbrowser
from pathlib import Path
from tkinter import messagebox
from typing import Type

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


def handle_exception(exc: Type[BaseException], value: BaseException, tb) -> None:
    """Log *value* with traceback and show a friendly error dialog.

    This function is used for ``sys.excepthook`` and Tk's
    ``report_callback_exception`` so any uncaught exceptions are routed here.
    """
    logger.error("Unhandled exception", exc_info=(exc, value, tb))

    tb_str = "".join(traceback.format_exception(exc, value, tb))
    context = _collect_context()
    _record(RECENT_ERRORS, f"{exc.__name__}:{value}\n{context}\n{tb_str}")

    if isinstance(value, IOError):
        msg = f"An I/O error occurred: {value}"
    elif isinstance(value, ValueError):
        msg = f"Invalid value: {value}"
    else:
        msg = str(value)

    try:
        show = messagebox.askyesno("Unexpected Error", f"{msg}\n\nShow details?")
    except Exception:  # pragma: no cover - UI may be unavailable
        show = False

    if show:
        log_file = _get_log_file()
        if log_file:
            try:
                webbrowser.open(log_file.as_uri())
            except Exception:  # pragma: no cover - platform specific
                messagebox.showinfo("Error Details", tb_str)
        else:
            messagebox.showinfo("Error Details", tb_str)


def install(window=None) -> None:
    """Install global hooks so all warnings and errors are logged."""

    def _thread_hook(args):
        handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    def _unraisable_hook(args):
        exc = args.exc_type or type(args.exc_value)
        handle_exception(exc, args.exc_value, args.exc_traceback)

    sys.excepthook = handle_exception
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable_hook

    def _showwarning(message, category, filename, lineno, file=None, line=None):
        text = f"{filename}:{lineno}:{category.__name__}:{message}"
        logger.warning(text)
        _record(RECENT_WARNINGS, text)

    warnings.showwarning = _showwarning
    logging.captureWarnings(True)

    if window is not None:
        window.report_callback_exception = handle_exception


__all__ = ["install", "handle_exception", "RECENT_ERRORS", "RECENT_WARNINGS"]

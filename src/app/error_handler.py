from __future__ import annotations

import logging
import traceback
import webbrowser
import sys
import threading
import warnings
from pathlib import Path
from tkinter import messagebox
from typing import Type

logger = logging.getLogger(__name__)


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

    if isinstance(value, IOError):
        msg = f"An I/O error occurred: {value}"
    elif isinstance(value, ValueError):
        msg = f"Invalid value: {value}"
    else:
        msg = str(value)

    try:
        show = messagebox.askyesno("Unexpected Error", f"{msg}\n\nShow details?")
    except Exception:
        show = False

    if show:
        log_file = _get_log_file()
        if log_file:
            try:
                webbrowser.open(log_file.as_uri())
            except Exception:
                messagebox.showinfo("Error Details", tb_str)
        else:
            messagebox.showinfo("Error Details", tb_str)


def install(window=None) -> None:
    """Install global hooks so all warnings and errors are logged."""

    def _thread_hook(args):
        handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = handle_exception
    threading.excepthook = _thread_hook

    def _showwarning(message, category, filename, lineno, file=None, line=None):
        logger.warning("%s:%s:%s: %s", filename, lineno, category.__name__, message)

    warnings.showwarning = _showwarning

    if window is not None:
        window.report_callback_exception = handle_exception

from __future__ import annotations

import logging
import traceback
import webbrowser
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

    This function is installed as ``window.report_callback_exception`` so any
    uncaught exceptions raised in Tkinter callbacks are routed here.
    """
    tb_str = "".join(traceback.format_exception(exc, value, tb))
    logger.error("Unhandled exception:\n%s", tb_str)

    if isinstance(value, IOError):
        msg = f"An I/O error occurred: {value}"
    elif isinstance(value, ValueError):
        msg = f"Invalid value: {value}"
    else:
        msg = str(value)

    if messagebox.askyesno("Unexpected Error", f"{msg}\n\nShow details?"):
        log_file = _get_log_file()
        if log_file:
            try:
                webbrowser.open(log_file.as_uri())
            except Exception:
                messagebox.showinfo("Error Details", tb_str)
        else:
            messagebox.showinfo("Error Details", tb_str)

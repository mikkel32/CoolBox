from __future__ import annotations

import logging
from tkinter import messagebox
from typing import Type

logger = logging.getLogger(__name__)


def handle_exception(exc: Type[BaseException], value: BaseException, tb) -> None:
    """Log *value* with traceback and show a friendly error dialog.

    This function is installed as ``window.report_callback_exception`` so any
    uncaught exceptions raised in Tkinter callbacks are routed here.
    """
    logger.error("Unhandled exception", exc_info=(exc, value, tb))
    messagebox.showerror("Unexpected Error", str(value))

"""Logging utilities shared across the setup command."""
from __future__ import annotations

import logging
import os

from ._ui import console

__all__ = ["log", "logger"]

logger = logging.getLogger("coolbox.setup")
logger.setLevel(logging.INFO)
if os.environ.get("COOLBOX_LOG_FILE"):
    handler = logging.FileHandler(os.environ["COOLBOX_LOG_FILE"])
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(handler)
else:
    logger.addHandler(logging.NullHandler())
logger.propagate = False


def log(message: str) -> None:
    logger.info(message)
    try:
        console.print(f"[dim]»[/] {message}")
    except Exception:
        print(message)

"""Application-wide logging configuration using rich handlers."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler


def setup_logging(level: int = logging.INFO, log_file: str | None = None) -> None:
    """Configure standard logging with RichHandler and optional file output.

    Parameters
    ----------
    level:
        Minimum logging severity. Defaults to ``logging.INFO``.
    log_file:
        Optional path to a log file. If provided, a ``RotatingFileHandler``
        will be attached writing plain text logs suitable for diagnostics.
        If ``None``, the environment variable ``COOLBOX_LOG_FILE`` is
        consulted. When neither are provided no file logging is configured.
    """
    if log_file is None:
        log_file = os.getenv("COOLBOX_LOG_FILE")

    handlers: list[logging.Handler] = [
        RichHandler(rich_tracebacks=True, markup=True)
    ]

    if log_file:
        file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        handlers=handlers,
        format="%(message)s",
        force=True,
    )


__all__ = ["setup_logging"]

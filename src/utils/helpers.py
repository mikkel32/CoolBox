"""Various helper utilities."""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import subprocess
from typing import Literal
import psutil

logging.basicConfig(level=logging.INFO)


def log(message: str) -> None:
    """Log a message using ``logging``."""
    logging.info(message)


def open_path(path: str) -> None:
    """Open *path* with the default application for the platform."""
    if platform.system() == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def calc_hash(path: str, algo: Literal["md5", "sha1", "sha256"] = "md5") -> str:
    """Return the hexadecimal hash of ``path`` using *algo*."""
    hash_func = getattr(hashlib, algo)()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def get_system_info() -> str:
    """Return a formatted multi-line string with system information."""
    mem = psutil.virtual_memory().total / (1024 * 1024 * 1024)
    info = (
        f"Platform: {platform.system()} {platform.release()}\n"
        f"Processor: {platform.processor()}\n"
        f"Architecture: {platform.architecture()[0]}\n"
        f"CPU Cores: {psutil.cpu_count(logical=True)}\n"
        f"Memory: {mem:.1f} GB\n"
        f"Python: {platform.python_version()}"
    )
    return info

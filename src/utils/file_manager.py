"""File management utilities."""

from pathlib import Path
from typing import Optional


def read_text(path: str) -> str:
    return Path(path).read_text()


def write_text(path: str, data: str) -> None:
    Path(path).write_text(data)


def pick_file() -> Optional[str]:
    """Dummy placeholder for file picking logic."""
    return None

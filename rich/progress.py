"""Tiny progress bar helpers used by CoolBox."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from .console import Console


class Progress:
    """Simplified progress display."""

    def __init__(
        self,
        *columns,
        console: Console | None = None,
        transient: bool = False,
        disable: bool = False,
    ) -> None:
        self.console = console or Console()
        self.total = 100
        self.completed = 0.0
        self.description = ""
        self.transient = transient
        self.disable = disable

    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.transient:
            self.console.print()

    def add_task(self, description: str, total: float | None = None, start: bool = False) -> int:
        self.description = description
        if total is not None:
            self.total = total
        if start:
            self.update(0)
        return 0

    def update(self, _task_id: int, *, advance: float | None = None, completed: float | None = None) -> None:
        if completed is not None:
            self.completed = completed
        elif advance is not None:
            self.completed += advance
        self.refresh()

    def refresh(self) -> None:
        percent = self.completed / self.total if self.total else 0
        bar_width = 20
        filled = int(percent * bar_width)
        bar = "[" + "#" * filled + "-" * (bar_width - filled) + "]"
        if not self.disable:
            self.console.print(
                f"{self.description} {bar} {percent*100:5.1f}%", end="\r"
            )
            if self.completed >= self.total:
                self.console.print()


class SpinnerColumn:
    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - placeholder
        pass


class TextColumn:
    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - placeholder
        pass


class TimeElapsedColumn:  # pragma: no cover - placeholder
    pass


class BarColumn:
    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - placeholder
        pass


__all__ = ["Progress", "SpinnerColumn", "TextColumn", "TimeElapsedColumn", "BarColumn"]

"""Very small Live display helper used by CoolBox."""

from __future__ import annotations

from .console import Console, Control


class Live:
    """Context manager that continually updates the console."""

    def __init__(self, *, console: Console | None = None, refresh_per_second: int = 4) -> None:
        self.console = console or Console()
        self.refresh_per_second = refresh_per_second

    def __enter__(self) -> "Live":
        self.console.control(Control.show_cursor(False))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.console.control(Control.show_cursor(True))

    def update(self, renderable) -> None:
        self.console.control(Control.home())
        self.console.print(renderable)


__all__ = ["Live"]

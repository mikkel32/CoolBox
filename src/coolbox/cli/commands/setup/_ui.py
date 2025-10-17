"""UI helpers shared across setup command actions."""
from __future__ import annotations

import threading
from contextlib import nullcontext
from typing import Sequence

from ._config import CONFIG, RAINBOW_COLORS
from ._helpers import helper_console
from ._rich_support import (
    BarColumn,
    Column,
    Console,
    ConsoleType,
    MofNCompleteColumn,
    Panel,
    Progress,
    ProgressColumn,
    Table,
    TaskProgressColumn,
    Text,
    TextType,
    TimeElapsedColumn,
    box,
)

__all__ = [
    "ConsoleType",
    "LockingConsole",
    "NeonPulseBorder",
    "Panel",
    "Progress",
    "Table",
    "Text",
    "TextType",
    "console",
    "create_progress",
    "rainbow_text",
    "SmartPercentColumn",
    "RainbowSpinnerColumn",
    "nullcontext",
]


class _NoopBorder:
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


try:  # pragma: no cover - optional rich helper
    from coolbox.utils.rainbow import NeonPulseBorder as _BorderImpl  # type: ignore
except Exception:  # pragma: no cover - fallback when optional helper missing
    _BorderImpl = _NoopBorder  # type: ignore


def NeonPulseBorder(**kwargs):
    return _BorderImpl(**kwargs)


class RainbowSpinnerColumn(ProgressColumn):
    """Spinner compatible with Rich 13.x that cycles through rainbow colours."""

    def __init__(self, frames: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", colors: Sequence[str] | None = None):
        super().__init__()
        self.frames = frames
        self.colors = list(colors or RAINBOW_COLORS)
        self._index = 0

    def get_table_column(self, *_, **__):  # pragma: no cover - compatibility shim
        return Column(no_wrap=True, justify="left", min_width=1, ratio=None)

    def render(self, task):  # type: ignore[override]
        char = self.frames[self._index % len(self.frames)]
        color = self.colors[self._index % len(self.colors)]
        self._index += 1
        return Text(char, style=color)


class SmartPercentColumn(ProgressColumn):
    """Always show percentage even when the total is unknown."""

    def __init__(self, precision: int = 0):
        super().__init__()
        self.precision = max(0, int(precision))

    def get_table_column(self, *_, **__):
        return Column(no_wrap=True, justify="right", min_width=5, ratio=None)

    def render(self, task):  # type: ignore[override]
        try:
            total = task.total
            completed = task.completed or 0
            if total and total > 0:
                pct = max(0.0, min(100.0, 100.0 * float(completed) / float(total)))
                fmt = f"{{0:.{self.precision}f}}%"
                return Text(fmt.format(pct))
            phase_pct = float(task.fields.get("phase_pct", 0.0)) if hasattr(task, "fields") else 0.0
            pct = max(0.0, min(99.0, phase_pct))
            fmt = f"{{0:.{self.precision}f}}%"
            return Text(fmt.format(pct))
        except Exception:
            return Text("--%")


def rainbow_text(message: str, colors: Sequence[str] | None = None) -> TextType:
    palette = list(colors or RAINBOW_COLORS)
    text = Text()
    for index, char in enumerate(message):
        text.append(char, style=palette[index % len(palette)])
    return text


class LockingConsole:
    """Thread-safe wrapper around a base console implementation."""

    def __init__(self, base: ConsoleType | None = None):
        self._lock = threading.RLock()
        self._console = base or Console(soft_wrap=False, highlight=False)

    def __enter__(self):
        enter = getattr(self._console, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        exit_ = getattr(self._console, "__exit__", None)
        if callable(exit_):
            return exit_(exc_type, exc, tb)
        return False

    def print(self, *args, **kwargs):
        with self._lock:
            self._console.print(*args, **kwargs)

    def log(self, *args, **kwargs):
        with self._lock:
            self._console.log(*args, **kwargs)

    def flush(self) -> None:
        with self._lock:
            try:
                self._console.file.flush()
            except Exception:
                pass

    @property
    def raw(self) -> ConsoleType:
        return self._console

    def __getattr__(self, name):
        return getattr(self._console, name)


console = LockingConsole(helper_console or Console(soft_wrap=False, highlight=False))


def create_progress(**overrides):
    """Create a Rich progress helper configured for the setup UI."""

    return Progress(
        RainbowSpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(bar_width=None),
        SmartPercentColumn(precision=0),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        refresh_per_second=10,
        console=console.raw,
        transient=True,
        disable=CONFIG.no_anim,
        **overrides,
    )

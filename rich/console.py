"""Minimal subset of the Rich console API used by CoolBox.

This module is **not** a full featured implementation of Rich. It only
implements the pieces required by the rest of the project so that CoolBox
can run without installing the `rich` package. If the real library is
available it should be preferred.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


class Console:
    """Very small console implementation supporting ``print`` and ``control``."""

    def __init__(self, file=None) -> None:
        self.file = file or sys.stdout

    def print(self, *values, sep: str = " ", end: str = "\n", **_: object) -> None:
        """Write the given values to ``self.file``."""
        self.file.write(sep.join(str(v) for v in values) + end)
        self.file.flush()

    def log(self, *values, **kwargs) -> None:  # pragma: no cover - trivial
        self.print(*values, **kwargs)

    def clear(self) -> None:  # pragma: no cover - trivial
        os.system("cls" if os.name == "nt" else "clear")

    def control(self, control: "Control") -> None:
        """Send a :class:`Control` sequence to the terminal."""
        self.file.write(control.sequence)
        self.file.flush()

    def rule(self, text: str = "") -> None:  # pragma: no cover - formatting
        line = "-" * 10
        if text:
            self.print(f"{line} {text} {line}")
        else:
            self.print(line * 2)


@dataclass
class Control:
    """Terminal control sequence container."""

    sequence: str

    @staticmethod
    def home() -> "Control":
        return Control("\x1b[H")

    @staticmethod
    def move_to(x: int, y: int) -> "Control":
        return Control(f"\x1b[{y + 1};{x + 1}H")

    @staticmethod
    def show_cursor(show: bool = True) -> "Control":
        return Control("\x1b[?25h" if show else "\x1b[?25l")


class Group:
    """Simple container for multiple renderables."""

    def __init__(self, *renderables) -> None:  # pragma: no cover - trivial
        self.renderables = list(renderables)

    def __iter__(self):  # pragma: no cover - trivial
        return iter(self.renderables)


__all__ = ["Console", "Control", "Group"]

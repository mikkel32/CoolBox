from __future__ import annotations

import math

import shutil
import threading
import time
from typing import Iterable, Tuple

from rich.console import Console, Control
from rich.text import Text


THEMES: dict[str, list[str]] = {
    "classic": ["red", "yellow", "green", "cyan", "blue", "magenta"],
    "awau": [
        "#ff75c3",
        "#ffa647",
        "#ffe654",
        "#8efc94",
        "#74eaf7",
        "#d6a4ff",
    ],
}

BORDER_STYLES: dict[str, Tuple[str, str, str, str, str, str]] = {
    "single": ("┏", "┓", "┗", "┛", "━", "┃"),
    "double": ("╔", "╗", "╚", "╝", "═", "║"),
    "rounded": ("╭", "╮", "╰", "╯", "─", "│"),
}


class RainbowBorder:
    """Animate a colorful frame around the terminal without disrupting output.

    Parameters
    ----------
    speed:
        Delay in seconds between animation frames.
    theme:
        Named color palette to use from :data:`THEMES`.
    colors:
        Explicit color sequence overriding the theme.
    style:
        Border style key from :data:`BORDER_STYLES`.
    console:
        Optional :class:`rich.console.Console` instance.
    """

    def __init__(
        self,
        speed: float = 0.05,
        *,
        theme: str = "classic",
        colors: Iterable[str] | None = None,
        style: str = "single",
        console: Console | None = None,
    ) -> None:
        self.speed = speed
        self.console = console or Console()
        self.colors = list(colors) if colors is not None else THEMES.get(theme, THEMES["classic"])
        self.border = BORDER_STYLES.get(style, BORDER_STYLES["single"])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "RainbowBorder":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self.console.control(Control.show_cursor(False))  # hide cursor
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
            self._clear()
            self.console.control(Control.show_cursor(True))  # show cursor

    def _run(self) -> None:
        offset = 0
        while not self._stop.is_set():
            self._draw(offset)
            time.sleep(self.speed)
            offset += 1

    def _draw(self, offset: int) -> None:
        width, height = shutil.get_terminal_size(fallback=(80, 24))
        colors = self.colors
        c = len(colors)
        self.console.file.write("\x1b7")  # save cursor

        tl, tr, bl, br, h, v = self.border
        top = Text(tl + h * (width - 2) + tr)
        for i in range(width):
            top.stylize(colors[(offset + i) % c], i, i + 1)
        self.console.control(Control.home())
        self.console.print(top, end="")

        bottom = Text(bl + h * (width - 2) + br)
        for i in range(width):
            bottom.stylize(colors[(offset + height + i) % c], i, i + 1)
        self.console.control(Control.move_to(0, height - 1))
        self.console.print(bottom, end="")

        for row in range(1, height - 1):
            left_style = colors[(offset + width + row) % c]
            right_style = colors[(offset + width + height + row) % c]
            self.console.control(Control.move_to(0, row))
            self.console.print(Text(v, style=left_style), end="")
            self.console.control(Control.move_to(width - 1, row))
            self.console.print(Text(v, style=right_style), end="")

        self.console.file.write("\x1b8")  # restore cursor
        self.console.file.flush()

    def _clear(self) -> None:
        width, height = shutil.get_terminal_size(fallback=(80, 24))
        blank = " " * width
        self.console.file.write("\x1b7")
        self.console.control(Control.home())
        self.console.print(blank, end="")
        for row in range(1, height - 1):
            self.console.control(Control.move_to(0, row))
            self.console.print(" ", end="")
            self.console.control(Control.move_to(width - 1, row))
            self.console.print(" ", end="")
        self.console.control(Control.move_to(0, height - 1))
        self.console.print(blank, end="")
        self.console.file.write("\x1b8")
        self.console.file.flush()


class NeonPulseBorder(RainbowBorder):
    """Animate a pulsing neon gradient around the terminal."""

    def __init__(
        self,
        speed: float = 0.05,
        *,
        base_color: str = "#00eaff",
        highlight_color: str = "#ff00d0",
        style: str = "rounded",
        console: Console | None = None,
    ) -> None:
        super().__init__(speed, colors=[base_color], style=style, console=console)
        self.base_color = base_color
        self.highlight_color = highlight_color
        self._phase = 0.0

    def _blend(self, c1: str, c2: str, t: float) -> str:
        c1 = c1.lstrip("#")
        c2 = c2.lstrip("#")
        if len(c1) == 3:
            c1 = "".join(ch * 2 for ch in c1)
        if len(c2) == 3:
            c2 = "".join(ch * 2 for ch in c2)
        r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
        r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
        r = round(r1 + (r2 - r1) * t)
        g = round(g1 + (g2 - g1) * t)
        b = round(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _generate_colors(self, width: int, height: int) -> list[str]:
        """Return a list of colors for the current phase."""
        perimeter = 2 * width + 2 * height - 4
        colors = []
        for i in range(perimeter):
            pos = i / perimeter
            pulse = (math.sin(self._phase) + 1.0) / 2.0
            color = self._blend(self.base_color, self.highlight_color, (pos + pulse) % 1.0)
            colors.append(color)
        return colors

    def _run(self) -> None:
        offset = 0
        while not self._stop.is_set():
            width, height = shutil.get_terminal_size(fallback=(80, 24))
            self.colors = self._generate_colors(width, height)
            self._draw(offset)
            time.sleep(self.speed)
            self._phase += 0.05
            offset += 1

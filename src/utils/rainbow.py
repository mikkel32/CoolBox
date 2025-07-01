from __future__ import annotations

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

    def __exit__(self, exc_type, exc, tb) -> None:
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

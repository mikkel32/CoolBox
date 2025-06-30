from __future__ import annotations

import shutil
import threading
import time
from rich.console import Console
from rich.text import Text

class RainbowBorder:
    """Animate a rainbow frame around the terminal without disrupting output."""

    def __init__(self, speed: float = 0.05, console: Console | None = None) -> None:
        self.speed = speed
        self.console = console or Console()
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
            self.console.control("\x1b[?25l")  # hide cursor
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
            self._clear()
            self.console.control("\x1b[?25h")  # show cursor

    def _run(self) -> None:
        offset = 0
        while not self._stop.is_set():
            self._draw(offset)
            time.sleep(self.speed)
            offset += 1

    def _draw(self, offset: int) -> None:
        width, height = shutil.get_terminal_size(fallback=(80, 24))
        colors = ["red", "yellow", "green", "cyan", "blue", "magenta"]
        c = len(colors)
        self.console.control("\x1b7")  # save cursor

        top = Text("─" * width)
        for i in range(width):
            top.stylize(colors[(offset + i) % c], i, i + 1)
        self.console.control("\x1b[1;1H")
        self.console.print(top, end="")

        bottom = Text("─" * width)
        for i in range(width):
            bottom.stylize(colors[(offset + height + i) % c], i, i + 1)
        self.console.control(f"\x1b[{height};1H")
        self.console.print(bottom, end="")

        for row in range(2, height):
            left_style = colors[(offset + width + row) % c]
            right_style = colors[(offset + width + height + row) % c]
            self.console.control(f"\x1b[{row};1H")
            self.console.print(Text("│", style=left_style), end="")
            self.console.control(f"\x1b[{row};{width}H")
            self.console.print(Text("│", style=right_style), end="")

        self.console.control("\x1b8")  # restore cursor
        self.console.file.flush()

    def _clear(self) -> None:
        width, height = shutil.get_terminal_size(fallback=(80, 24))
        blank = " " * width
        self.console.control("\x1b7")
        self.console.control("\x1b[1;1H")
        self.console.print(blank, end="")
        for row in range(2, height):
            self.console.control(f"\x1b[{row};1H")
            self.console.print(" ", end="")
            self.console.control(f"\x1b[{row};{width}H")
            self.console.print(" ", end="")
        self.console.control(f"\x1b[{height};1H")
        self.console.print(blank, end="")
        self.console.control("\x1b8")
        self.console.file.flush()

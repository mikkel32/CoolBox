from __future__ import annotations

import math
import random
import shutil
import threading
import time
from contextlib import contextmanager
from typing import Iterable, Tuple, List, Sequence

try:
    from rich.console import Console, Control
    from rich.text import Text
except ImportError:  # pragma: no cover
    from ..ensure_deps import ensure_rich  # type: ignore
    ensure_rich()
    from rich.console import Console, Control
    from rich.text import Text


# ---- atomic console to prevent torn output -----------------------------------

class LockingConsole(Console):
    """Console that guards all writes with a re-entrant lock to avoid interleaving."""
    def __init__(self, *args, lock: threading.RLock | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock: threading.RLock = lock or threading.RLock()

    def print(self, *args, **kwargs):  # type: ignore[override]
        with self._lock:
            return super().print(*args, **kwargs)

    def control(self, *args, **kwargs):  # type: ignore[override]
        with self._lock:
            return super().control(*args, **kwargs)

_RLOCK_TYPE = type(threading.RLock())

@contextmanager
def _console_lock_ctx(console: Console):
    lock = getattr(console, "_lock", None)
    if isinstance(lock, _RLOCK_TYPE):
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
    else:
        yield


# ---- color + themes ----------------------------------------------------------

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x

def _hsl_to_hex(h: float, s: float, l: float) -> str:
    # h,s,l in [0,1]
    def hue_to_rgb(p: float, q: float, t: float) -> float:
        t = t % 1.0
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p
    s = _clamp01(s); l = _clamp01(l)
    if s == 0.0:
        r = g = b = l
    else:
        q = l + s - l * s if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = hue_to_rgb(p, q, h + 1/3)
        g = hue_to_rgb(p, q, h)
        b = hue_to_rgb(p, q, h - 1/3)
    return f"#{int(r*255+0.5):02x}{int(g*255+0.5):02x}{int(b*255+0.5):02x}"

THEMES: dict[str, Sequence[str]] = {
    "classic": ["red", "yellow", "green", "cyan", "blue", "magenta"],
    "awau": ["#ff75c3", "#ffa647", "#ffe654", "#8efc94", "#74eaf7", "#d6a4ff"],
    "matrix": ["#0f0", "#0c0", "#0a0", "#070", "#050", "#020"],
    "sunset": ["#ff6b6b", "#ff8e53", "#ffd166", "#06d6a0", "#118ab2", "#8338ec"],
    "pride": ["#e40303", "#ff8c00", "#ffed00", "#008026", "#004dff", "#750787"],
}

BORDER_STYLES: dict[str, Tuple[str, str, str, str, str, str]] = {
    "single": ("┏", "┓", "┗", "┛", "═", "║"),
    "double": ("╔", "╗", "╚", "╝", "═", "║"),
    "rounded": ("╭", "╮", "╰", "╯", "─", "│"),
    "heavy": ("┏", "┓", "┗", "┛", "━", "┃"),
}


# ---- base border -------------------------------------------------------------

class RainbowBorder:
    """
    Animated rainbow frame around the terminal, resize-aware.
    """

    def __init__(
        self,
        speed: float = 0.05,
        *,
        theme: str = "classic",
        colors: Iterable[str] | None = None,
        style: str = "single",
        console: Console | None = None,
        use_alt_screen: bool = False,
        thickness: int = 1,
    ) -> None:
        self.speed = max(0.01, float(speed))
        self.console = console or LockingConsole()
        self.colors = list(colors) if colors is not None else list(THEMES.get(theme, THEMES["classic"]))
        self.border = BORDER_STYLES.get(style, BORDER_STYLES["single"])
        self.use_alt_screen = use_alt_screen
        self.thickness = max(1, int(thickness))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_size: Tuple[int, int] | None = None

    def __enter__(self) -> "RainbowBorder":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        if self._thread is None and getattr(self.console, "is_terminal", True):
            self._stop.clear()
            with _console_lock_ctx(self.console):
                if self.use_alt_screen:
                    self.console.file.write("\x1b[?1049h")
                hide_cursor = getattr(Control, "hide_cursor", None)
                if hide_cursor:
                    self.console.control(hide_cursor())
                else:
                    self.console.control(Control.show_cursor(False))
                self.console.file.flush()
            self._thread = threading.Thread(target=self._run, daemon=True, name="RainbowBorder")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
            self._clear()
            with _console_lock_ctx(self.console):
                show_cursor = getattr(Control, "show_cursor")
                try:
                    self.console.control(show_cursor(True))
                except TypeError:
                    self.console.control(show_cursor())
                if self.use_alt_screen:
                    self.console.file.write("\x1b[?1049l")
                self.console.file.flush()

    def _run(self) -> None:
        offset = 0
        while not self._stop.is_set():
            t0 = time.perf_counter()
            self._draw(offset)
            elapsed = time.perf_counter() - t0
            sleep_for = self.speed - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            offset += 1

    def _draw(self, offset: int) -> None:
        width, height = shutil.get_terminal_size(fallback=(80, 24))
        if width < 4 or height < 3:
            return
        self._last_size = (width, height)

        tl, tr, bl, br, h, v = self.border
        C = max(1, len(self.colors))

        with _console_lock_ctx(self.console):
            self.console.file.write("\x1b7")  # save cursor

            for layer in range(self.thickness):
                w = width - layer * 2
                hgt = height - layer * 2
                if w < 2 or hgt < 2:
                    continue

                # top
                top = Text((tl if layer == 0 else " ") + ("─" * (w - 2)) + (tr if layer == 0 else " "))
                for i in range(w):
                    top.stylize(self.colors[(offset + i + layer) % C], i, i + 1)
                self.console.control(Control.move_to(layer, layer))
                self.console.print(top, end="")

                # bottom
                bottom = Text((bl if layer == 0 else " ") + ("─" * (w - 2)) + (br if layer == 0 else " "))
                for i in range(w):
                    bottom.stylize(self.colors[(offset + hgt + i + layer) % C], i, i + 1)
                self.console.control(Control.move_to(layer, layer + hgt - 1))
                self.console.print(bottom, end="")

                # sides
                for row in range(1, hgt - 1):
                    left_style = self.colors[(offset + w + row + layer) % C]
                    right_style = self.colors[(offset + w + hgt + row + layer) % C]
                    self.console.control(Control.move_to(layer, layer + row))
                    self.console.print(Text("│", style=left_style), end="")
                    self.console.control(Control.move_to(layer + w - 1, layer + row))
                    self.console.print(Text("│", style=right_style), end="")

            self.console.file.write("\x1b8")  # restore cursor
            self.console.file.flush()

    def _clear(self) -> None:
        size = self._last_size or shutil.get_terminal_size(fallback=(80, 24))
        width, height = size
        if width < 1 or height < 1:
            return
        blank = " " * width
        with _console_lock_ctx(self.console):
            self.console.file.write("\x1b7")
            for row in range(height):
                self.console.control(Control.move_to(0, row))
                self.console.print(blank, end="")
            self.console.file.write("\x1b8")
            self.console.file.flush()


# ---- neon pulse (improved rainbow) ------------------------------------------

class NeonPulseBorder(RainbowBorder):
    """
    Advanced border with HSL rainbow and neon pulse.
    """

    def __init__(
        self,
        speed: float = 0.05,
        *,
        base_color: str | None = None,
        highlight_color: str | None = None,
        style: str = "rounded",
        console: Console | None = None,
        theme: str = "pride",
        thickness: int = 1,
        use_alt_screen: bool = False,
        saturation: float = 0.95,
        lightness: float = 0.55,
        glow_strength: float = 0.25,
    ) -> None:
        super().__init__(
            speed,
            colors=[],
            style=style,
            console=console,
            use_alt_screen=use_alt_screen,
            thickness=thickness,
            theme=theme,
        )
        self.theme = theme
        self.base_color = base_color or "#00eaff"
        self.highlight_color = highlight_color or "#ff00d0"
        self._phase = 0.0
        self._rng = random.Random(int("C00LB0X", 36))
        self.saturation = float(saturation)
        self.lightness = float(lightness)
        self.glow_strength = float(glow_strength)

    def _perimeter_len(self, width: int, height: int, layer: int) -> int:
        w = width - layer * 2
        h = height - layer * 2
        return max(1, 2 * w + 2 * h - 4)

    def _generate_layer_palette(self, width: int, height: int, layer: int, offset: int) -> List[str]:
        n = self._perimeter_len(width, height, layer)
        phase = self._phase + layer * 0.33
        colors: List[str] = []
        for i in range(n):
            t = (i + offset) / max(1, n)
            hue = (t + phase * 0.07) % 1.0
            sat = self.saturation
            lum = self.lightness

            ridge = (math.sin(phase * 2.2 + i * 0.045) + 1.0) * 0.5
            lum += self.glow_strength * (ridge ** 3)

            lum += (self._rng.random() - 0.5) * 0.02
            sat += (self._rng.random() - 0.5) * 0.01

            colors.append(_hsl_to_hex(hue, _clamp01(sat), _clamp01(lum)))
        return colors

    def _draw(self, offset: int) -> None:
        width, height = shutil.get_terminal_size(fallback=(80, 24))
        if width < 4 or height < 3:
            return
        self._last_size = (width, height)

        with _console_lock_ctx(self.console):
            self.console.file.write("\x1b7")

            base_offset = offset
            for layer in range(self.thickness):
                w = width - layer * 2
                hgt = height - layer * 2
                if w < 2 or hgt < 2:
                    continue

                palette = self._generate_layer_palette(width, height, layer, base_offset)
                n = len(palette)

                top = Text(("╭" if layer == 0 else " ") + ("─" * (w - 2)) + ("╮" if layer == 0 else " "))
                for i in range(w):
                    top.stylize(palette[(i) % n], i, i + 1)
                self.console.control(Control.move_to(layer, layer))
                self.console.print(top, end="")

                bottom = Text(("╰" if layer == 0 else " ") + ("─" * (w - 2)) + ("╯" if layer == 0 else " "))
                for i in range(w):
                    bottom.stylize(palette[(hgt + i) % n], i, i + 1)
                self.console.control(Control.move_to(layer, layer + hgt - 1))
                self.console.print(bottom, end="")

                for row in range(1, hgt - 1):
                    left_style = palette[(w + row) % n]
                    right_style = palette[(w + hgt + row) % n]
                    self.console.control(Control.move_to(layer, layer + row))
                    self.console.print(Text("│", style=left_style), end="")
                    self.console.control(Control.move_to(layer + w - 1, layer + row))
                    self.console.print(Text("│", style=right_style), end="")

            self.console.file.write("\x1b8")
            self.console.file.flush()

    @staticmethod
    def _blend(c1: str, c2: str, t: float) -> str:
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

    def _generate_colors(self, width: int, height: int) -> List[str]:
        perimeter = max(1, 2 * width + 2 * height - 4)
        colors: List[str] = []
        pulse = (math.sin(self._phase) + 1.0) * 0.5
        same = self.base_color.lower() == self.highlight_color.lower()
        for i in range(perimeter):
            pos = (i / perimeter + (pulse * 0.25 if not same else 0.0)) % 1.0
            if same:
                color = self.base_color
            else:
                color = self._blend(self.base_color, self.highlight_color, pos)
                ridge = (math.sin(self._phase * 2.4 + i * 0.045) + 1.0) * 0.5
                if ridge > 0.85:
                    color = self._blend(color, "#ffffff", (ridge - 0.85) / 0.15)
            colors.append(color)
        return colors

    def _run(self) -> None:
        offset = 0
        while not self._stop.is_set():
            t0 = time.perf_counter()
            self._draw(offset)
            self._phase += 0.06
            elapsed = time.perf_counter() - t0
            sleep_for = self.speed - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            offset += 1

"""Overlay for selecting a window by clicking it.

The overlay uses global mouse hooks when available so it can remain fully
transparent to input without stealing focus. When hooks aren't supported it
falls back to regular event bindings and temporarily disables mouse capture
while polling the underlying window.
"""

from __future__ import annotations

import os
import time
import math
import re
import warnings
import tkinter as tk
from collections import deque
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, Callable, Any, Protocol
from enum import Enum, auto
from threading import Lock
import atexit
import psutil
from PIL import Image, ImageTk

try:  # pragma: no cover - optional dependency
    from PyQt5 import QtCore, QtWidgets, QtQuick, QtOpenGL, QtGui
except Exception:  # pragma: no cover - optional dependency
    QtCore = QtWidgets = QtQuick = QtOpenGL = QtGui = None

from src.utils.window_utils import (
    get_active_window,
    get_window_at,
    get_window_under_cursor,
    list_windows_at,
    make_window_clickthrough,
    remove_window_clickthrough,
    set_window_colorkey,
    subscribe_active_window,
    subscribe_window_change,
    WindowInfo,
)
from src.utils.mouse_listener import get_global_listener, is_supported
from src.utils.scoring_engine import ScoringEngine, tuning
from src.utils.hover_tracker import HoverTracker
from ._fast_confidence import weighted_confidence as _weighted_confidence_np
from src.utils import get_screen_refresh_rate
from src.utils.helpers import log
from src.config import Config

QT_AVAILABLE = QtWidgets is not None
QT_QUICK_AVAILABLE = QtQuick is not None

CFG = Config()


def _load_int(env: str, key: str, default: int) -> int:
    """Return an int loaded from ``env`` or configuration ``key``."""
    val = os.getenv(env)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    try:
        cfg_val = CFG.get(key)
        if cfg_val is not None:
            return int(cfg_val)
    except Exception:
        pass
    return default


_EXECUTOR: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = Lock()


def get_executor() -> ThreadPoolExecutor:
    """Return a shared executor, creating it on first use."""
    global _EXECUTOR
    if _EXECUTOR is None:
        with _EXECUTOR_LOCK:
            if _EXECUTOR is None:
                workers = _load_int(
                    "KILL_BY_CLICK_WORKERS", "kill_by_click_workers", 2
                )
                _EXECUTOR = ThreadPoolExecutor(max_workers=workers)
                atexit.register(_EXECUTOR.shutdown, cancel_futures=True)
    return _EXECUTOR


DEFAULT_HIGHLIGHT = os.getenv("KILL_BY_CLICK_HIGHLIGHT", "red")

# Enable enriched labels with process names/icons when environment flag is set
ENRICH_LABELS = os.getenv("KILL_BY_CLICK_APP_LABELS", "").lower() not in (
    "",
    "0",
    "false",
    "no",
)

_PROCESS_CACHE: dict[int, tuple[str, ImageTk.PhotoImage | None]] = {}


def _process_details(pid: int) -> tuple[str, ImageTk.PhotoImage | None]:
    """Return process name and optional icon for ``pid``."""
    if pid in _PROCESS_CACHE:
        return _PROCESS_CACHE[pid]
    name = ""
    icon_img: ImageTk.PhotoImage | None = None
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        exe = proc.exe()
        if exe and exe.lower().endswith((".ico", ".png")):
            img = Image.open(exe).resize((16, 16))
            icon_img = ImageTk.PhotoImage(img)
    except Exception:
        pass
    _PROCESS_CACHE[pid] = (name, icon_img)
    return name, icon_img


def _auto_tune_interval(samples: int = 60) -> tuple[float, float, float]:
    """Calibrate refresh intervals based on average frame render time."""
    root = tk.Tk()
    root.withdraw()
    canvas = tk.Canvas(root)
    canvas.pack()
    root.update_idletasks()
    times: list[float] = []
    for _ in range(max(1, samples)):
        start = time.perf_counter()
        root.update()
        end = time.perf_counter()
        times.append(end - start)
    root.destroy()
    avg = sum(times) / len(times)
    interval = max(DEFAULT_INTERVAL, avg * 2)
    min_interval = max(avg * 1.2, 0.001)
    max_interval = interval * 5
    os.environ["KILL_BY_CLICK_INTERVAL"] = str(interval)
    os.environ["KILL_BY_CLICK_MIN_INTERVAL"] = str(min_interval)
    os.environ["KILL_BY_CLICK_MAX_INTERVAL"] = str(max_interval)
    try:
        CFG.set("kill_by_click_interval_calibrated", interval)
        CFG.set("kill_by_click_min_interval_calibrated", min_interval)
        CFG.set("kill_by_click_max_interval_calibrated", max_interval)
        CFG.save()
    except Exception:
        pass
    return interval, min_interval, max_interval


_INTERVAL_INDEX = {
    "kill_by_click_interval": 0,
    "kill_by_click_min_interval": 1,
    "kill_by_click_max_interval": 2,
}


def _load_calibrated(env: str, key: str, default: float) -> float:
    """Return a float loaded from ``env`` or configuration ``key``."""
    val = os.getenv(env)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    try:
        cfg_val = CFG.get(key)
        if cfg_val is not None:
            return float(cfg_val)
        calib_val = CFG.get(f"{key}_calibrated")
        if calib_val is not None:
            return float(calib_val)
        if key in _INTERVAL_INDEX and os.environ.get("DISPLAY"):
            tuned = _auto_tune_interval()
            return float(tuned[_INTERVAL_INDEX[key]])
    except Exception:
        pass
    return default


def _load_str(env: str, key: str, default: str) -> str:
    """Return a string loaded from ``env`` or configuration ``key``."""
    val = os.getenv(env)
    if val:
        return val
    try:
        cfg_val = CFG.get(key)
        if cfg_val:
            return str(cfg_val)
    except Exception:
        pass
    return default


def _load_bool(env: str, key: str, default: bool) -> bool:
    """Return a bool loaded from ``env`` or configuration ``key``."""
    val = os.getenv(env)
    if val is not None:
        if val.lower() in {"1", "true", "yes", "on"}:
            return True
        if val.lower() in {"0", "false", "no", "off"}:
            return False
    try:
        cfg_val = CFG.get(key)
        if cfg_val is not None:
            return bool(cfg_val)
    except Exception:
        pass
    return default


# Allow the refresh interval to be configured via an environment
# variable. Falling back to half the screen refresh period keeps the
# overlay snappy (120 FPS on a 60 Hz display) while providing an easy
# knob for users.
DEFAULT_INTERVAL = 1 / (get_screen_refresh_rate() * 2)
KILL_BY_CLICK_INTERVAL = _load_calibrated(
    "KILL_BY_CLICK_INTERVAL", "kill_by_click_interval", DEFAULT_INTERVAL
)

# Alpha used when a transparent color key cannot be applied. This keeps the
# overlay visible instead of fully hiding it.
FALLBACK_ALPHA = float(os.getenv("KILL_BY_CLICK_FALLBACK_ALPHA", "0.3"))

# Minimum time between colorkey validations in milliseconds
COLORKEY_RECHECK_MS = int(
    os.getenv("KILL_BY_CLICK_COLORKEY_RECHECK_MS", "1000")
)

# Base cache TTL for window probing in seconds
PROBE_CACHE_TTL = float(os.getenv("KILL_BY_CLICK_PROBE_TTL", "0.1"))

# Grid size in pixels for position-based probe caching
PROBE_CACHE_GRANULARITY = _load_int(
    "KILL_BY_CLICK_PROBE_GRID", "kill_by_click_probe_grid", 5
)

# Base move debounce derived from screen refresh rate (half a frame).
# Users may override via ``KILL_BY_CLICK_MOVE_DEBOUNCE_MS`` /
# ``kill_by_click_move_debounce_ms`` and adjust per instance at runtime.
DEFAULT_MOVE_DEBOUNCE_MS = int(1000 / (get_screen_refresh_rate() * 2))

# Rendering backend selection ("canvas", "qt" or "qtquick")
DEFAULT_BACKEND = _load_str(
    "KILL_BY_CLICK_BACKEND", "kill_by_click_backend", "canvas"
).lower()

KF_PROCESS_NOISE = _load_calibrated(
    "KILL_BY_CLICK_KF_PROCESS_NOISE", "kill_by_click_kf_process_noise", 1.0
)
KF_MEASUREMENT_NOISE = _load_calibrated(
    "KILL_BY_CLICK_KF_MEASUREMENT_NOISE",
    "kill_by_click_kf_measurement_noise",
    5.0,
)


class _Kalman1D:
    def __init__(self, process_noise: float, measurement_noise: float):
        self.q = process_noise
        self.r = measurement_noise
        self.x = 0.0
        self.v = 0.0
        self.P = [[1.0, 0.0], [0.0, 1.0]]
        self.initialized = False

    def update(self, z: float, dt: float) -> tuple[float, float]:
        if not self.initialized:
            self.x = z
            self.initialized = True
            return self.x, self.v
        self.x += self.v * dt
        p00, p01 = self.P[0]
        p10, p11 = self.P[1]
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt
        p00 = p00 + dt * (p10 + p01) + dt2 * p11 + self.q * dt4 / 4.0
        p01 = p01 + dt * p11 + self.q * dt3 / 2.0
        p10 = p10 + dt * p11 + self.q * dt3 / 2.0
        p11 = p11 + self.q * dt2
        y = z - self.x
        s = p00 + self.r
        k0 = p00 / s
        k1 = p10 / s
        self.x += k0 * y
        self.v += k1 * y
        self.P = [
            [p00 - k0 * p00, p01 - k0 * p01],
            [p10 - k1 * p00, p11 - k1 * p01],
        ]
        return self.x, self.v


_COLOR_CACHE: dict[str, str] = {}


def _normalize_color(widget: tk.Misc, color: str) -> str:
    """Return ``color`` as a lowercase ``#rrggbb`` string.

    The value is memoized to avoid repeated conversions and handles shorthand
    hex values without relying on ``winfo_rgb``.
    """

    c = str(color or "").strip()
    if not c:
        return ""
    cached = _COLOR_CACHE.get(c)
    if cached is not None:
        return cached
    if c.startswith("#"):
        hexpart = c[1:]
        if re.fullmatch(r"[0-9a-fA-F]{3}", hexpart):
            result = "#" + "".join(ch * 2 for ch in hexpart).lower()
        elif re.fullmatch(r"[0-9a-fA-F]{6}", hexpart):
            result = "#" + hexpart.lower()
        else:
            result = c.lower()
        _COLOR_CACHE[c] = result
        return result
    try:
        r, g, b = widget.winfo_rgb(c)
        result = f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"
    except Exception:
        result = c.lower()
    _COLOR_CACHE[c] = result
    return result


class CanvasAPI(Protocol):
    """Minimal drawing interface shared by overlay backends."""

    def create_rectangle(self, *args: Any, **kwargs: Any) -> Any: ...  # noqa: E704

    def create_line(self, *args: Any, **kwargs: Any) -> Any: ...  # noqa: E704

    def create_text(self, *args: Any, **kwargs: Any) -> Any: ...  # noqa: E704

    def coords(self, item: Any, *args: Any) -> Any: ...  # noqa: E704

    def itemconfigure(self, item: Any, **kwargs: Any) -> Any: ...  # noqa: E704

    def bbox(self, item: Any) -> Any: ...  # noqa: E704


class TkCanvas(CanvasAPI):
    """Adapter exposing ``tk.Canvas`` through ``CanvasAPI``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._canvas = tk.Canvas(*args, **kwargs)

    # Delegate standard methods to the underlying canvas
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - trivial
        return getattr(self._canvas, name)

    # Explicitly expose API methods for type checkers
    def create_rectangle(self, *args: Any, **kwargs: Any) -> Any:
        return self._canvas.create_rectangle(*args, **kwargs)

    def create_line(self, *args: Any, **kwargs: Any) -> Any:
        return self._canvas.create_line(*args, **kwargs)

    def create_text(self, *args: Any, **kwargs: Any) -> Any:
        return self._canvas.create_text(*args, **kwargs)

    def coords(self, item: Any, *args: Any) -> Any:
        return self._canvas.coords(item, *args)

    def itemconfigure(self, item: Any, **kwargs: Any) -> Any:
        return self._canvas.itemconfigure(item, **kwargs)

    def bbox(self, item: Any) -> Any:
        return self._canvas.bbox(item)


if QT_AVAILABLE:

    class QtCanvas(CanvasAPI):  # pragma: no cover - GUI heavy
        """``CanvasAPI`` implementation using ``QGraphicsScene``."""

        def __init__(self, parent: QtWidgets.QWidget) -> None:
            scene = QtWidgets.QGraphicsScene(parent)
            view = QtWidgets.QGraphicsView(scene, parent)
            view.setStyleSheet("background: transparent")
            view.setFrameShape(QtWidgets.QFrame.NoFrame)
            view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            if QtOpenGL is not None:
                try:
                    view.setViewport(QtOpenGL.QGLWidget())
                except Exception:
                    pass
            self._view = view
            self._scene = scene

        def widget(self) -> QtWidgets.QWidget:
            return self._view

        def create_rectangle(
            self, x1: float, y1: float, x2: float, y2: float, *, outline: str = "red", width: int = 1
        ) -> Any:
            pen = QtGui.QPen(QtGui.QColor(outline))
            pen.setWidth(width)
            rect = self._scene.addRect(x1, y1, x2 - x1, y2 - y1, pen)
            return rect

        def create_line(
            self, x1: float, y1: float, x2: float, y2: float, *, fill: str = "red", dash: Any | None = None
        ) -> Any:
            pen = QtGui.QPen(QtGui.QColor(fill))
            if dash:
                pen.setStyle(QtCore.Qt.DashLine)
            line = self._scene.addLine(x1, y1, x2, y2, pen)
            return line

        def create_text(self, x: float, y: float, *, text: str = "", fill: str = "red", font: Any | None = None, anchor: str | None = None) -> Any:
            item = self._scene.addText(text)
            item.setDefaultTextColor(QtGui.QColor(fill))
            item.setPos(x, y)
            return item

        def coords(self, item: Any, *args: Any) -> Any:
            if hasattr(item, "setRect") and len(args) == 4:
                item.setRect(*args)
            elif hasattr(item, "setLine") and len(args) == 4:
                item.setLine(*args)
            elif hasattr(item, "setPos") and len(args) >= 2:
                item.setPos(args[0], args[1])

        def itemconfigure(self, item: Any, **kwargs: Any) -> Any:
            if "text" in kwargs and hasattr(item, "setPlainText"):
                item.setPlainText(kwargs["text"])
            if "width" in kwargs and hasattr(item, "setPen"):
                pen = item.pen()
                pen.setWidth(kwargs["width"])
                item.setPen(pen)
            if "fill" in kwargs and hasattr(item, "setDefaultTextColor"):
                item.setDefaultTextColor(QtGui.QColor(kwargs["fill"]))

        def bbox(self, item: Any) -> Any:
            if hasattr(item, "boundingRect"):
                rect = item.boundingRect()
                return rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height()
            return None


class UpdateState(Enum):
    IDLE = auto()
    PENDING = auto()
    RUNNING = auto()


class OverlayState(Enum):
    INIT = auto()
    HOOKED = auto()
    POLLING = auto()


if QT_AVAILABLE:
    class QtClickOverlay(QtWidgets.QWidget):  # pragma: no cover - GUI heavy
        """Simple transparent overlay rendered with Qt."""

        def __init__(
            self,
            parent=None,
            *,
            highlight: str = DEFAULT_HIGHLIGHT,
            show_label: bool = True,
            **_: Any,
        ) -> None:
            app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
            super().__init__(parent)
            self.backend = "qt"
            self._app = app
            self.setWindowFlag(QtCore.Qt.FramelessWindowHint)
            self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            self.showFullScreen()
            self.canvas = QtCanvas(self)
            self.canvas.widget().setGeometry(self.rect())
            self.canvas.widget().show()
            self.rect = self.canvas.create_rectangle(0, 0, 1, 1, outline=highlight, width=2)
            self.hline = self.canvas.create_line(0, 0, 0, 0, fill=highlight)
            self.vline = self.canvas.create_line(0, 0, 0, 0, fill=highlight)
            self.label = None
            if show_label:
                self.label = self.canvas.create_text(10, 10, text="", fill=highlight)

        def close(self) -> None:  # pragma: no cover - GUI heavy
            super().close()
            if not QtWidgets.QApplication.topLevelWidgets():
                self._app.quit()

    if QT_QUICK_AVAILABLE:

        class QtQuickClickOverlay(QtClickOverlay):  # pragma: no cover - GUI heavy
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self.backend = "qtquick"

    else:  # pragma: no cover - Qt optional

        class QtQuickClickOverlay:  # type: ignore
            def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
                raise RuntimeError("QtQuick backend not available")

else:  # pragma: no cover - Qt optional

    class QtClickOverlay:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
            raise RuntimeError("Qt backend not available")

    class QtQuickClickOverlay:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
            raise RuntimeError("QtQuick backend not available")


class ClickOverlay(tk.Toplevel):
    """Fullscreen transparent window used to select another window.

    Parameters
    ----------
    parent:
        The parent ``tk`` widget owning the overlay.
    highlight:
        Color used for the selection rectangle and crosshair lines.
    show_crosshair:
        Whether to draw crosshair lines centered on the cursor.
    show_label:
        Whether to display an informational label near the cursor.
    probe_attempts:
        Number of times to retry window detection when the cursor is over one
        of this process's windows.
    timeout:
        Automatically close the overlay after this many seconds if provided.
    on_hover:
        Optional callback invoked with ``(pid, title)`` when the hovered window
        changes.
    backend:
        Rendering backend to use (``"canvas"``, ``"qt"`` or ``"qtquick"``).
        Defaults to ``KILL_BY_CLICK_BACKEND`` or ``"canvas"``.
    """

    def __new__(
        cls,
        parent: tk.Misc | None,
        *args: Any,
        backend: str | None = None,
        **kwargs: Any,
    ) -> "ClickOverlay | QtClickOverlay | QtQuickClickOverlay":
        selected = (backend or DEFAULT_BACKEND).lower()
        if selected in {"qtquick", "opengl"} and QT_QUICK_AVAILABLE:
            return QtQuickClickOverlay(parent, *args, **kwargs)
        if selected == "qt" and QT_AVAILABLE:
            return QtClickOverlay(parent, *args, **kwargs)
        return super().__new__(cls)

    @staticmethod
    def auto_tune_interval(samples: int = 60) -> tuple[float, float, float]:
        return _auto_tune_interval(samples)

    def __init__(
        self,
        parent: tk.Misc,
        *,
        highlight: str = DEFAULT_HIGHLIGHT,
        show_crosshair: bool = True,
        show_label: bool = True,
        probe_attempts: int = 3,
        timeout: float | None = None,
        interval: float = KILL_BY_CLICK_INTERVAL,
        min_interval: float | None = None,
        max_interval: float | None = None,
        delay_scale: float | None = None,
        skip_confirm: bool | None = None,
        on_hover: Callable[[int | None, str | None], None] | None = None,
        basic_render: bool = False,
        adaptive_interval: bool | None = None,
        _backend: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = "canvas"
        self._closed = tk.BooleanVar(value=False)
        env = os.getenv("KILL_BY_CLICK_CROSSHAIR")
        if env in ("0", "false", "no"):
            show_crosshair = False
        env = os.getenv("KILL_BY_CLICK_LABEL")
        if env in ("0", "false", "no"):
            show_label = False
        self.show_crosshair = show_crosshair
        self.show_label = show_label
        self.basic_render = basic_render
        # Hide until fully configured to avoid a brief black flash
        self.withdraw()
        if not self.basic_render:
            try:
                self.attributes("-alpha", 0.0)
            except Exception:
                pass
        # Configure fullscreen before enabling override-redirect to avoid
        # "can't set fullscreen attribute" errors on some platforms.
        self.attributes("-topmost", True)
        self.attributes("-fullscreen", True)
        self.overrideredirect(True)
        self.configure(cursor="crosshair")

        # use a unique background color that can be made transparent. normalize
        # to a hex string so the value matches across ``configure`` and
        # ``-transparentcolor``; some platforms don't recognize symbolic color
        # names which results in a black overlay.
        bg_color = "#000001"
        if isinstance(parent, tk.Widget):
            try:
                bg_color = parent.cget("bg")
            except Exception:
                pass
        self._bg_color = _normalize_color(self, bg_color)
        # Initialize color key tracking before configuring the widget so that
        # ``configure`` can safely call ``_maybe_ensure_colorkey``.
        self._has_colorkey = False
        self._colorkey_warning_shown = False
        self._colorkey_last_check = 0.0
        self._colorkey_last_key = ""
        self._colorkey_last_bg = self._bg_color
        self.configure(bg=self._bg_color)

        if is_supported():
            make_window_clickthrough(self)
        if not self.basic_render:
            # Validate and restore the transparent color key to avoid a fullscreen
            # black window if the system drops support.
            self._maybe_ensure_colorkey(force=True)

        # Using an empty string for the canvas background causes a TclError on
        # some platforms. Use the chosen background color so the canvas itself
        # becomes transparent via the color key.
        self.canvas = TkCanvas(
            self, bg=self._bg_color, highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack(fill="both", expand=True)
        self.rect = self.canvas.create_rectangle(0, 0, 1, 1, outline=highlight, width=2)
        # crosshair lines spanning the entire screen for precise selection
        if self.show_crosshair:
            self.hline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
            self.vline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
        else:
            self.hline = None
            self.vline = None
        if self.show_label:
            self.label = self.canvas.create_text(
                0,
                0,
                anchor="nw",
                fill=highlight,
                text="",
                font=("TkDefaultFont", 10, "bold"),
            )
            self.icon_item = None
            self.icon_img: ImageTk.PhotoImage | None = None
        else:
            self.label = None
            self.icon_item = None
            self.icon_img = None
        # Fade in now that the window is fully configured. If the color key
        # cannot be applied the overlay remains semi-transparent so the user
        # can still see the screen.
        try:
            self.update_idletasks()
            self.deiconify()
            if not self.basic_render:
                self._maybe_ensure_colorkey(force=True)
        except Exception:
            pass
        self.probe_attempts = probe_attempts
        self.timeout = timeout
        if adaptive_interval is None:
            adaptive_interval = _load_bool(
                "KILL_BY_CLICK_AUTO_INTERVAL",
                "kill_by_click_auto_interval",
                True,
            )
        self.adaptive_interval = adaptive_interval
        self.interval = interval
        if min_interval is None:
            self.min_interval = _load_calibrated(
                "KILL_BY_CLICK_MIN_INTERVAL",
                "kill_by_click_min_interval",
                tuning.min_interval,
            )
        else:
            self.min_interval = min_interval
        if max_interval is None:
            self.max_interval = _load_calibrated(
                "KILL_BY_CLICK_MAX_INTERVAL",
                "kill_by_click_max_interval",
                tuning.max_interval,
            )
        else:
            self.max_interval = max_interval
        if self.min_interval > self.max_interval:
            self.min_interval, self.max_interval = self.max_interval, self.min_interval
        if delay_scale is None:
            try:
                self.delay_scale = float(
                    os.getenv("KILL_BY_CLICK_DELAY_SCALE", str(tuning.delay_scale))
                )
            except ValueError:
                self.delay_scale = tuning.delay_scale
        else:
            self.delay_scale = delay_scale
        if self.delay_scale <= 0:
            self.delay_scale = tuning.delay_scale
        if skip_confirm is None:
            env = os.getenv("KILL_BY_CLICK_SKIP_CONFIRM")
            skip_confirm = env not in (None, "0", "false", "no")
        self.skip_confirm = skip_confirm
        self.on_hover = on_hover
        self._after_id: Optional[str] = None
        self._timeout_id: Optional[str] = None
        self.update_state = UpdateState.IDLE
        self._state_lock = Lock()

        # Background executor for window queries and scoring
        self._executor = get_executor()
        self.state = OverlayState.INIT
        self.pid: int | None = None
        self.title_text: str | None = None
        self._last_info: WindowInfo | None = None
        self._cached_info: WindowInfo | None = None
        self._screen_w = self.winfo_screenwidth()
        self._screen_h = self.winfo_screenheight()
        try:
            self._dpi = float(self.winfo_fpixels("1i"))
        except Exception:
            self._dpi = 96.0
        logical_move_px = _load_int(
            "KILL_BY_CLICK_MIN_MOVE_PX", "kill_by_click_min_move_px", 2
        )
        self._min_move_px = max(
            1, int(round(logical_move_px * (self._dpi / 96.0)))
        )
        self._move_debounce_ms = _load_int(
            "KILL_BY_CLICK_MOVE_DEBOUNCE_MS",
            "kill_by_click_move_debounce_ms",
            DEFAULT_MOVE_DEBOUNCE_MS,
        )
        self.engine = ScoringEngine(
            tuning,
            self._screen_w,
            self._screen_h,
            os.getpid(),
        )
        self._own_pid = os.getpid()
        self._initial_active_pid: int | None = None
        self._velocity = 0.0
        self._probe_cache_ttl = PROBE_CACHE_TTL
        self._probe_cache_px = PROBE_CACHE_GRANULARITY
        self._point_cache: dict[tuple[int, int], tuple[WindowInfo, float]] = {}
        self._path_history: deque[tuple[int, int]] = deque(maxlen=tuning.path_history)
        self._last_move_time = time.time()
        self._last_move_pos = (0, 0)
        self._move_scheduled = False
        self._pending_move: tuple[int, int, float] | None = None
        self._hover = HoverTracker()
        # Expose internal trackers for backwards compatibility with tests
        self._gaze_duration = self._hover.gaze_duration
        self._pid_history = self._hover.pid_history
        self._info_history = self._hover.info_history
        self._pid_stability = self._hover.pid_stability
        self._click_x = 0
        self._click_y = 0
        self._active_history: deque[tuple[int, float]] = deque(
            maxlen=tuning.active_history_size
        )
        # Share history with the scoring engine
        self.engine.active_history = self._active_history
        # Active window tracking via subscription callback.
        try:
            self._active_window = get_active_window()
            self._active_pid = self._active_window.pid
        except Exception:
            self._active_window = WindowInfo(None)
            self._active_pid = None
        self._unsubscribe_active = subscribe_active_window(self._on_active_window)
        self._destroyed = False
        self._query_future: Future[WindowInfo] | None = None
        self._flash_id: str | None = None
        try:
            self._cursor_x = self.winfo_pointerx()
            self._cursor_y = self.winfo_pointery()
        except Exception:
            self._cursor_x = 0
            self._cursor_y = 0
        self._last_move_pos = (self._cursor_x, self._cursor_y)
        self._kf_x = _Kalman1D(KF_PROCESS_NOISE, KF_MEASUREMENT_NOISE)
        self._kf_y = _Kalman1D(KF_PROCESS_NOISE, KF_MEASUREMENT_NOISE)
        self._kf_x.update(self._cursor_x, 0.0)
        self._kf_y.update(self._cursor_y, 0.0)
        self._frame_times: deque[float] = deque(maxlen=60)
        self.avg_frame_ms = 0.0
        self._last_frame_start = 0.0
        self._last_frame_end = 0.0
        self._frame_count = 0
        # Off-screen buffer of last drawn state so only changed regions update
        self._buffer: dict[str, Any] = {
            "cursor": (None, None),
            "rect": (-5, -5, -5, -5),
            "label_text": "",
            "label_pos": (0, 0),
            "icon_pos": (0, 0),
            "pid": None,
            "hline": (0, 0, 0, 0),
            "vline": (0, 0, 0, 0),
            "screen": (0, 0),
        }
        # Cache for window enumeration to minimize repeated list_windows_at calls
        self._window_cache_rect: tuple[int, int, int, int] | None = None
        self._window_cache: list[WindowInfo] = []
        self._window_cache_time: float = 0.0
        self._window_cache_future: Future[list[WindowInfo]] | None = None
        self._unsubscribe_windows = subscribe_window_change(self._on_windows_changed)
        if self._unsubscribe_windows is not None:
            self._refresh_window_cache(int(self._cursor_x), int(self._cursor_y))
        self.reset()

    def configure(self, cnf=None, **kw):  # type: ignore[override]
        """Configure widget options and reapply transparency on bg changes."""
        result = super().configure(cnf or {}, **kw)
        bg = kw.get("bg") or kw.get("background")
        if bg is not None:
            self._bg_color = _normalize_color(self, bg)
            self._maybe_ensure_colorkey(force=True)
        return result

    config = configure

    def _score_async(
        self, func: Callable[[], Any], callback: Callable[[Any], None] | None = None
    ) -> Future[Any]:
        """Run ``func`` on the worker thread and invoke ``callback`` with the result."""

        future: Future[Any] = self._executor.submit(func)
        if callback is not None:
            future.add_done_callback(
                lambda fut: self.after(0, lambda: callback(fut.result()))
            )
        return future

    def _track_async(
        self, info: WindowInfo, callback: Callable[[Any], None] | None = None
    ) -> None:
        """Queue ``engine.tracker.add`` on the worker thread."""

        self._score_async(
            lambda: self.engine.tracker.add(info, self._initial_active_pid), callback
        )

    def _weighted_confidence_async(
        self, samples: list[WindowInfo], callback: Callable[[tuple[WindowInfo | None, float, float]], None]
    ) -> None:
        """Run ``engine.weighted_confidence`` on the worker thread."""
        with self._state_lock:
            cx = self._cursor_x
            cy = self._cursor_y
            vel = self._velocity
            path = list(self._path_history)
            init = self._initial_active_pid

        self._score_async(
            lambda: _weighted_confidence_np(
                self.engine,
                samples,
                cx,
                cy,
                vel,
                path,
                init,
            ),
            callback,
        )

    def _weighted_confidence(
        self, samples: list[WindowInfo]
    ) -> tuple[WindowInfo | None, float, float]:
        """Synchronous wrapper around :meth:`_weighted_confidence_async`.

        The heavy computation runs on the worker thread while the caller waits
        for the result, avoiding any blocking work on the Tk event loop.
        """
        with self._state_lock:
            cx = self._cursor_x
            cy = self._cursor_y
            vel = self._velocity
            path = list(self._path_history)
            init = self._initial_active_pid

        future = self._score_async(
            lambda: _weighted_confidence_np(
                self.engine,
                samples,
                cx,
                cy,
                vel,
                path,
                init,
            )
        )
        return future.result()

    def _on_windows_changed(self) -> None:
        """Refresh cached windows when the desktop changes."""

        if not self._destroyed:
            self._refresh_window_cache(int(self._cursor_x), int(self._cursor_y))

    def _on_active_window(self, info: WindowInfo) -> None:
        """Handle active window change notifications."""

        self._active_window = info
        self._active_pid = info.pid
        if not self._destroyed:
            now = time.monotonic()
            pid = info.pid
            if pid not in (self._own_pid, None):
                if not self._active_history or self._active_history[-1][0] != pid:
                    self._active_history.append((pid, now))
            self._queue_update()

    def destroy(self) -> None:  # type: ignore[override]
        """Ensure background threads exit before destroying the window."""
        self._destroyed = True
        try:
            self._unsubscribe_active()
        except Exception:
            pass
        try:
            if self._unsubscribe_windows:
                self._unsubscribe_windows()
        except Exception:
            pass
        super().destroy()

    def _ensure_colorkey(self) -> None:
        """Ensure the overlay background remains fully transparent.

        The method verifies that the window's transparent color key matches the
        configured background color and attempts to restore it if missing. When
        the color key cannot be set the overlay falls back to a semi-transparent
        window instead of remaining fully invisible.
        """
        if self.basic_render:
            return
        try:
            if not self._has_colorkey:
                self._has_colorkey = set_window_colorkey(self)
            key = _normalize_color(self, self.attributes("-transparentcolor"))
            bg = self._bg_color
            if key != bg:
                self._has_colorkey = set_window_colorkey(self)
                key = _normalize_color(self, self.attributes("-transparentcolor"))
                if key != bg:
                    self._has_colorkey = False
        except Exception:
            self._has_colorkey = False
        try:
            if self._has_colorkey:
                self.attributes("-alpha", 1.0)
            else:
                self.attributes("-alpha", FALLBACK_ALPHA)
        except Exception:
            pass
        if not self._has_colorkey and not self._colorkey_warning_shown:
            warnings.warn(
                "transparency color key unavailable; using fallback alpha"
            )
            self._colorkey_warning_shown = True

    def _maybe_ensure_colorkey(self, *, force: bool = False) -> None:
        """Revalidate the transparent color key when necessary."""
        if self.basic_render:
            return
        now = time.monotonic()
        try:
            key = _normalize_color(self, self.attributes("-transparentcolor"))
        except Exception:
            key = ""
        bg = self._bg_color
        if (
            force
            or key != self._colorkey_last_key
            or bg != self._colorkey_last_bg
            or (now - self._colorkey_last_check) * 1000 >= COLORKEY_RECHECK_MS
        ):
            self._ensure_colorkey()
            self._colorkey_last_key = key
            self._colorkey_last_bg = bg
            self._colorkey_last_check = now

    def _flash_highlight(self) -> None:
        """Temporarily thicken the highlight rectangle when the target changes."""

        self.canvas.itemconfigure(self.rect, width=3)
        if self._flash_id is not None:
            try:
                self.after_cancel(self._flash_id)
            except Exception:
                pass
        self._flash_id = self.after(
            tuning.flash_duration_ms,
            lambda: self.canvas.itemconfigure(self.rect, width=2),
        )

    def set_highlight_color(self, color: str) -> None:
        """Update the highlight color for all overlay elements."""
        self.canvas.itemconfigure(self.rect, outline=color)
        if self.hline is not None:
            self.canvas.itemconfigure(self.hline, fill=color)
        if self.vline is not None:
            self.canvas.itemconfigure(self.vline, fill=color)
        if self.label is not None:
            self.canvas.itemconfigure(self.label, fill=color)

    def _calc_label_pos(self, px: int, py: int, sw: int, sh: int) -> tuple[int, int] | None:
        """Return label coordinates near the cursor, constrained to the screen."""
        if not self.show_label or self.label is None:
            return None
        x = px + 10
        y = py + 10
        bbox = self.canvas.bbox(self.label)
        if bbox:
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            if x + width > sw:
                x = px - width - 10
            if y + height > sh:
                y = py - height - 10
        return x, y

    def _apply_updates(self, updates: dict[str, tuple[int, ...] | str]) -> None:
        """Apply buffered canvas updates and log render duration."""
        if not updates:
            return
        start = time.perf_counter()
        regions = []
        if "hline" in updates and self.hline is not None:
            new = updates["hline"]
            old = self._buffer.get("hline")
            if (
                old is not None
                and new[2] - new[0] == old[2] - old[0]
                and new[3] - new[1] == old[3] - old[1]
            ):
                dx = new[0] - old[0]
                dy = new[1] - old[1]
                self.canvas.move(self.hline, dx, dy)
            else:
                self.canvas.coords(self.hline, *new)
            self._buffer["hline"] = new
            regions.append(self.canvas.bbox(self.hline))
        if "vline" in updates and self.vline is not None:
            new = updates["vline"]
            old = self._buffer.get("vline")
            if (
                old is not None
                and new[2] - new[0] == old[2] - old[0]
                and new[3] - new[1] == old[3] - old[1]
            ):
                dx = new[0] - old[0]
                dy = new[1] - old[1]
                self.canvas.move(self.vline, dx, dy)
            else:
                self.canvas.coords(self.vline, *new)
            self._buffer["vline"] = new
            regions.append(self.canvas.bbox(self.vline))
        if "rect" in updates:
            new = updates["rect"]
            old = self._buffer["rect"]
            if (
                new[2] - new[0] == old[2] - old[0]
                and new[3] - new[1] == old[3] - old[1]
            ):
                dx = new[0] - old[0]
                dy = new[1] - old[1]
                self.canvas.move(self.rect, dx, dy)
            else:
                self.canvas.coords(self.rect, *new)
            regions.append(self.canvas.bbox(self.rect))
        if "label_text" in updates and self.label is not None:
            self.canvas.itemconfigure(self.label, text=updates["label_text"])
            regions.append(self.canvas.bbox(self.label))
        if "label_pos" in updates and self.label is not None:
            new = updates["label_pos"]
            old = self._buffer.get("label_pos", (0, 0))
            dx = new[0] - old[0]
            dy = new[1] - old[1]
            self.canvas.move(self.label, dx, dy)
            self._buffer["label_pos"] = new
            regions.append(self.canvas.bbox(self.label))
        if "icon" in updates:
            img = updates["icon"]
            if img is None and self.icon_item is not None:
                self.canvas.delete(self.icon_item)
                self.icon_item = None
                self.icon_img = None
            elif img is not None:
                if self.icon_item is None:
                    self.icon_item = self.canvas.create_image(0, 0, image=img, anchor="nw")
                else:
                    self.canvas.itemconfigure(self.icon_item, image=img)
                self.icon_img = img
                regions.append(self.canvas.bbox(self.icon_item))
        if "icon_pos" in updates and self.icon_item is not None:
            new = updates["icon_pos"]
            old = self._buffer.get("icon_pos", (0, 0))
            dx = new[0] - old[0]
            dy = new[1] - old[1]
            self.canvas.move(self.icon_item, dx, dy)
            self._buffer["icon_pos"] = new
            regions.append(self.canvas.bbox(self.icon_item))
        end = time.perf_counter()
        log(
            f"ClickOverlay updated {len(regions)} regions in {(end - start) * 1000:.2f}ms"
        )

    def _queue_update(self, _e: object | None = None) -> None:
        """Schedule an overlay update in the main thread.

        When called from ``<Motion>`` events this also updates velocity and
        tracking fields so fallback bindings behave like the hook-based path.
        """
        # Refresh active PID from the cached window to avoid polling the OS
        active = self._active_window
        self._active_pid = active.pid
        if isinstance(_e, tk.Event):
            now = time.time()
            dt = now - self._last_move_time
            dist = math.hypot(
                _e.x_root - self._last_move_pos[0],
                _e.y_root - self._last_move_pos[1],
            )
            thr_ms, thr_px = self._move_thresholds()
            if dt * 1000.0 < thr_ms and dist < thr_px:
                return
            self._last_move_time = now
            self._last_move_pos = (_e.x_root, _e.y_root)
            self._path_history.append((_e.x_root, _e.y_root))
            self.engine.heatmap.update(_e.x_root, _e.y_root)
            with self._state_lock:
                fx, vx = self._kf_x.update(_e.x_root, dt)
                fy, vy = self._kf_y.update(_e.y_root, dt)
                self._cursor_x = fx
                self._cursor_y = fy
                self._velocity = math.hypot(vx, vy)
        elif self.state is OverlayState.POLLING:
            mx = self.winfo_pointerx()
            my = self.winfo_pointery()
            now = time.time()
            dt = now - self._last_move_time
            dist = math.hypot(mx - self._last_move_pos[0], my - self._last_move_pos[1])
            thr_ms, thr_px = self._move_thresholds()
            if dt * 1000.0 < thr_ms and dist < thr_px:
                return
            self._last_move_time = now
            self._last_move_pos = (mx, my)
            self._path_history.append((mx, my))
            self.engine.heatmap.update(mx, my)
            with self._state_lock:
                fx, vx = self._kf_x.update(mx, dt)
                fy, vy = self._kf_y.update(my, dt)
                self._cursor_x = fx
                self._cursor_y = fy
                self._velocity = math.hypot(vx, vy)
        _ = self._update_hover_tracker()
        if self.update_state is UpdateState.IDLE:
            self.update_state = UpdateState.PENDING
            self.after_idle(self._process_update)

    def _update_hover_tracker(self) -> WindowInfo | None:
        """Update hover statistics and return a stable guess if available."""
        info = self._query_window()
        self._hover.update(info, self._own_pid)
        if info.pid not in (self._own_pid, None):
            self._last_info = info
            self._track_async(info)
        elif info.pid is None:
            self._last_info = None
        return self._hover.stable_info(self._velocity)

    def _next_delay(self) -> int:
        """Return the delay in milliseconds until the next update."""
        interval = max(min(self.interval, self.max_interval), self.min_interval)
        base_ms = interval * 1000.0
        min_ms = self.min_interval * 1000.0
        max_ms = self.max_interval * 1000.0
        # Scale the refresh rate using a smooth curve so large
        # cursor movements speed up updates without sudden jumps.
        scale = 1.0 / (1.0 + self._velocity / self.delay_scale)
        delay = base_ms * scale
        if self.avg_frame_ms:
            delay = max(delay - self.avg_frame_ms, min_ms)
        delay = max(min(delay, max_ms), min_ms)
        return int(delay)

    def _retune_interval(self) -> None:
        """Adjust refresh intervals based on recent frame rendering times."""
        avg_sec = self.avg_frame_ms / 1000.0
        interval = max(DEFAULT_INTERVAL, avg_sec * 2)
        self.interval = max(min(interval, self.max_interval), self.min_interval)

    def _process_update(self) -> None:
        self.update_state = UpdateState.RUNNING
        if self.state is OverlayState.POLLING:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
        else:
            with self._state_lock:
                x = self._cursor_x
                y = self._cursor_y
        with self._state_lock:
            if x != self._cursor_x or y != self._cursor_y:
                self._cached_info = None
            self._cursor_x = x
            self._cursor_y = y
        start = time.perf_counter()
        self._last_frame_start = start

        future = self._executor.submit(self._query_window_at, int(x), int(y))

        def _on_done(fut: Future[WindowInfo]) -> None:
            try:
                info = fut.result()
            except Exception:
                info = WindowInfo(None)
            self.after_idle(lambda: self._finish_update(info, start))

        future.add_done_callback(_on_done)

    def _finish_update(self, info: WindowInfo, start: float) -> None:
        self._update_rect(info)
        end = time.perf_counter()
        self._last_frame_end = end
        frame_ms = (end - start) * 1000.0
        self._frame_times.append(frame_ms)
        self.avg_frame_ms = sum(self._frame_times) / len(self._frame_times)
        self._frame_count += 1
        if self._frame_count % self._frame_times.maxlen == 0:
            log(f"ClickOverlay avg frame {self.avg_frame_ms:.2f}ms")
            if self.adaptive_interval:
                self._retune_interval()
        self.update_state = UpdateState.IDLE
        self._after_id = self.after(self._next_delay(), self._queue_update)

    def _update_probe_cache_ttl(self) -> None:
        """Scale probe cache TTL inversely with cursor velocity."""
        self._probe_cache_ttl = PROBE_CACHE_TTL / (1.0 + self._velocity)

    def set_move_debounce_ms(self, ms: int | None = None) -> None:
        """Adjust base move debounce in milliseconds.

        Passing ``None`` reloads the value from configuration and screen refresh
        rate. The value is clamped to zero allowing debounce to be disabled for
        zero-lag operation.
        """
        if ms is None:
            ms = _load_int(
                "KILL_BY_CLICK_MOVE_DEBOUNCE_MS",
                "kill_by_click_move_debounce_ms",
                DEFAULT_MOVE_DEBOUNCE_MS,
            )
        self._move_debounce_ms = max(0, int(ms))

    def _move_thresholds(self) -> tuple[float, float]:
        """Return debounce thresholds scaled by cursor velocity and DPI.

        Thresholds grow with pointer velocity and display DPI while never
        dropping below ``self._move_debounce_ms`` or the per-instance
        ``_min_move_px``. This keeps slow, precise movements responsive on
        low-DPI screens while reducing update frequency during fast motion or on
        high-DPI displays.
        """
        vel_scale = max(1.0, self._velocity / 100.0)
        dpi_scale = self._dpi / 96.0 if getattr(self, "_dpi", 0) else 1.0
        ms = self._move_debounce_ms * max(1.0, vel_scale * dpi_scale)
        px = max(self._min_move_px, self._min_move_px * vel_scale)
        return ms, px

    def _on_move(self, x: int, y: int) -> None:
        """Record a mouse move from the pynput hook.

        The listener runs in an OS thread so heavy work is deferred to the
        Tk event loop using :meth:`after_idle`. Small, rapid movements are
        ignored based on dynamic thresholds from :meth:`_move_thresholds`.
        """
        now = time.time()
        self._pending_move = (x, y, now)
        if self._move_scheduled:
            return
        dt_ms = (now - self._last_move_time) * 1000.0
        dist = math.hypot(x - self._last_move_pos[0], y - self._last_move_pos[1])
        thr_ms, thr_px = self._move_thresholds()
        if dt_ms < thr_ms and dist < thr_px:
            return
        self._move_scheduled = True
        fast_dist = thr_px * 5
        base_vel = float("inf") if thr_ms <= 0 else (thr_px / thr_ms) * 1000.0
        inst_vel = float("inf") if dt_ms <= 0 else (dist / dt_ms) * 1000.0
        fast_vel = base_vel * 4
        try:
            if dist >= fast_dist or inst_vel >= fast_vel:
                self._handle_move()
            else:
                self.after_idle(self._handle_move)
        except Exception:
            self._move_scheduled = False

    def _handle_move(self) -> None:
        """Process the latest pending move on the Tk thread."""
        self._move_scheduled = False
        if not self._pending_move:
            return
        x, y, now = self._pending_move
        self._pending_move = None
        dt = now - self._last_move_time
        self._last_move_time = now
        self._last_move_pos = (x, y)
        self._path_history.append((x, y))
        if self.engine.tuning.heatmap_weight > 0:
            self.engine.heatmap.update(x, y)
        with self._state_lock:
            fx, vx = self._kf_x.update(x, dt)
            fy, vy = self._kf_y.update(y, dt)
            self._cursor_x = fx
            self._cursor_y = fy
            self._velocity = math.hypot(vx, vy)
            self._cached_info = None
        self._update_probe_cache_ttl()
        mnow = time.monotonic()
        rect = self._window_cache_rect
        ttl = self._probe_cache_ttl
        if (
            rect is None
            or not (
                rect[0] <= x < rect[0] + rect[2]
                and rect[1] <= y < rect[1] + rect[3]
            )
            or mnow - self._window_cache_time >= ttl
        ):
            if self._window_cache_future is None or self._window_cache_future.done():
                self._refresh_window_cache(int(x), int(y))
        self._queue_update()

    def _query_window(self) -> WindowInfo:
        """Return the window info below the cursor, ignoring this overlay."""
        with self._state_lock:
            x, y = int(self._cursor_x), int(self._cursor_y)
        return self._query_window_at(x, y)

    def _query_window_async(self, callback: Callable[[WindowInfo], None]) -> None:
        """Resolve the window under the cursor on the worker thread."""
        if self._query_future is not None and not self._query_future.done():
            self._query_future.cancel()
            self._query_future.add_done_callback(
                lambda f: f.exception() if not f.cancelled() else None
            )

        with self._state_lock:
            x, y = int(self._cursor_x), int(self._cursor_y)
        future = self._executor.submit(self._query_window_at, x, y)
        self._query_future = future

        def _on_done(fut: Future[WindowInfo]) -> None:
            self._query_future = None
            self.after(0, lambda: callback(fut.result()))

        future.add_done_callback(_on_done)

    def _set_window_cache(self, wins: list[WindowInfo]) -> None:
        """Update cached window list and bounding rectangle."""
        self._window_cache_future = None
        self._window_cache = wins
        self._window_cache_time = time.monotonic()
        rects = [w.rect for w in wins if w.rect]
        if rects:
            minx = min(r[0] for r in rects)
            miny = min(r[1] for r in rects)
            maxx = max(r[0] + r[2] for r in rects)
            maxy = max(r[1] + r[3] for r in rects)
            self._window_cache_rect = (minx, miny, maxx - minx, maxy - miny)
        else:
            self._window_cache_rect = None

    def _refresh_window_cache(self, x: int, y: int) -> None:
        """Asynchronously refresh windows beneath ``(x, y)``."""
        self._window_cache_future = self._score_async(
            lambda: list_windows_at(x, y), self._set_window_cache
        )

    def _probe_point(self, x: int, y: int) -> WindowInfo:
        """Return window info at ``(x, y)`` with smart caching."""
        now = time.monotonic()
        ttl = self._probe_cache_ttl
        key = (x // self._probe_cache_px, y // self._probe_cache_px)
        for k, (_, ts) in list(self._point_cache.items()):
            if now - ts >= ttl:
                del self._point_cache[k]
        cached = self._point_cache.get(key)
        if cached and now - cached[1] < ttl:
            return cached[0]

        rect = self._window_cache_rect
        if (
            rect
            and rect[0] <= x < rect[0] + rect[2]
            and rect[1] <= y < rect[1] + rect[3]
            and now - self._window_cache_time < ttl
        ):
            wins = self._window_cache
        elif self._unsubscribe_windows is not None:
            wins = self._window_cache
            if self._window_cache_future is None or self._window_cache_future.done():
                self._refresh_window_cache(x, y)
        else:
            top = get_window_under_cursor()
            if top.pid in (self._own_pid, None):
                wins = self._window_cache or [top]
                if self._window_cache_future is None or self._window_cache_future.done():
                    self._refresh_window_cache(x, y)
            else:
                wins = [top]
                self._set_window_cache(wins)
        if not wins:
            info = WindowInfo(None)
        else:
            for win in wins:
                if win.pid not in (self._own_pid, None):
                    info = win
                    break
            else:
                info = wins[0]
        self._point_cache[key] = (info, now)
        return info

    def _query_window_at(self, x: int, y: int) -> WindowInfo:
        """Return the window info at ``(x, y)`` in screen coordinates.

        The method performs at most one probe per call. When the scoring
        engine's history indicates that the previously probed window remains
        reliable, the cached result is reused and no probe is performed. The
        cache is refreshed only when confidence falls below
        ``tuning.confidence_ratio`` or the best scoring window differs from the
        cached one.
        """

        self.engine.tracker.decay()
        with self._state_lock:
            cached = self._cached_info
        if (
            cached is not None
            and cached.pid not in (self._own_pid, None)
            and cached.rect
            and cached.rect[0] <= x < cached.rect[0] + cached.rect[2]
            and cached.rect[1] <= y < cached.rect[1] + cached.rect[3]
        ):
            return cached
        best, ratio = self.engine.tracker.best_with_confidence()
        if (
            best is not None
            and cached is not None
            and best.pid == cached.pid
            and ratio >= tuning.confidence_ratio
        ):
            return cached

        if self.state is OverlayState.HOOKED:
            info = self._probe_point(x, y)
        else:
            was_click = make_window_clickthrough(self)
            try:
                info = self._probe_point(x, y)
            finally:
                if was_click:
                    remove_window_clickthrough(self)

        with self._state_lock:
            self._cached_info = info
        if info.pid is None:
            return self._last_info or WindowInfo(None)
        if info.pid == self._own_pid:
            return self._last_info or WindowInfo(None)
        return info

    def _update_rect(self, info: WindowInfo | None = None) -> None:
        if info is None:
            if self._query_future is None:
                self._query_window_async(self._update_rect)
            info = self._last_info or self._active_window or WindowInfo(None)
        self.pid = info.pid
        self.title_text = info.title

        px = int(self._cursor_x)
        py = int(self._cursor_y)
        sw = self._screen_w
        sh = self._screen_h
        dist = math.hypot(px - self._buffer["cursor"][0], py - self._buffer["cursor"][1])
        cursor_moved = dist >= self._min_move_px
        updates: dict[str, tuple[int, ...] | str] = {}
        self._draw_crosshair(updates, px, py, sw, sh, cursor_moved)
        rect, text, window_changed, hover_changed = self._update_label(info, updates)
        if dist < self._min_move_px and not window_changed:
            return
        if cursor_moved or window_changed or hover_changed:
            if self.show_label and self.label is not None:
                pos = self._calc_label_pos(px, py, sw, sh)
                if pos is not None:
                    updates["label_pos"] = pos
                    if ENRICH_LABELS and self.icon_item is not None:
                        updates["icon_pos"] = (pos[0] - 20, pos[1])
        else:
            return

        self._apply_updates(updates)
        self._buffer["cursor"] = (px, py)
        self._buffer["rect"] = rect
        self._buffer["label_text"] = text
        if "label_pos" in updates:
            self._buffer["label_pos"] = updates["label_pos"]
        self._buffer["pid"] = info.pid
        self._handle_hover(hover_changed)

    def _draw_crosshair(
        self,
        updates: dict[str, tuple[int, ...] | str],
        px: int,
        py: int,
        sw: int,
        sh: int,
        cursor_changed: bool,
    ) -> None:
        """Populate updates with crosshair coordinates."""
        if (
            self.show_crosshair
            and self.hline is not None
            and self.vline is not None
            and (cursor_changed or self._buffer["screen"] != (sw, sh))
        ):
            updates["hline"] = (0, py, sw, py)
            updates["vline"] = (px, 0, px, sh)
            self._buffer["screen"] = (sw, sh)

    def _update_label(
        self,
        info: WindowInfo,
        updates: dict[str, tuple[int, ...] | str],
    ) -> tuple[tuple[int, int, int, int], str, bool, bool]:
        """Update overlay rectangle and label text."""
        if info.pid is None or not info.rect:
            rect = (-5, -5, -5, -5)
            text = ""
        else:
            rect = (
                info.rect[0],
                info.rect[1],
                info.rect[0] + info.rect[2],
                info.rect[1] + info.rect[3],
            )
            text = info.title or (f"PID {info.pid}" if info.pid else "")
            if ENRICH_LABELS and info.pid is not None:
                name, icon_img = _process_details(info.pid)
                if name:
                    text = name
                updates["icon"] = icon_img

        window_changed = rect != self._buffer["rect"] or info.pid != self._buffer["pid"]
        text_changed = text != self._buffer["label_text"]
        if window_changed:
            updates["rect"] = rect
            if info.pid != self._buffer["pid"]:
                self._flash_highlight()
        if self.show_label and self.label is not None and (
            text_changed or info.pid != self._buffer["pid"]
        ):
            updates["label_text"] = text
        hover_changed = text_changed or info.pid != self._buffer["pid"]
        return rect, text, window_changed, hover_changed

    def _handle_hover(self, hover_changed: bool) -> None:
        """Invoke the hover callback when the target window changes."""
        if hover_changed and self.on_hover is not None:
            try:
                self.on_hover(self.pid, self.title_text)
            except Exception:
                pass

    def _stable_info(self) -> WindowInfo | None:
        """Return a best guess based solely on recent hover history."""
        return self._hover.stable_info(self._velocity)

    def _confirm_window(self) -> WindowInfo:
        """Re-query the click location after the overlay closes."""
        info = get_window_at(int(self._click_x), int(self._click_y))
        self.engine.tracker.add(info, self._initial_active_pid)
        return info

    def _on_click(self) -> None:
        info: WindowInfo = self._query_window_at(int(self._click_x), int(self._click_y))
        if info.pid in (self._own_pid, None):
            stable = self._stable_info()
            if stable is not None:
                info = stable
            else:
                tracked, ratio = self.engine.tracker.best_with_confidence()
                if tracked is not None and ratio >= tuning.tracker_ratio:
                    info = tracked
                elif self._last_info is not None:
                    info = self._last_info
                else:
                    info = self._active_window
        else:
            self._last_info = info

        self.pid = info.pid
        self.title_text = info.title
        if self.skip_confirm:
            self.close()
            return

        self.close()

        confirm = self._confirm_window()
        samples = [info, confirm]
        weights = self.engine.score_samples(
            samples,
            self._cursor_x,
            self._cursor_y,
            self._velocity,
            self._path_history,
            self._initial_active_pid,
        )
        if confirm.pid not in (self._own_pid, None):
            weights[confirm.pid] = weights.get(confirm.pid, 0.0) + tuning.confirm_weight
        choice = self.engine.select_from_weights(samples, weights)
        if choice is not None:
            self.pid = choice.pid
            self.title_text = choice.title

    def _click(self, x: int, y: int, pressed: bool) -> None:
        if pressed:
            with self._state_lock:
                self._cursor_x = x
                self._cursor_y = y
            self._click_x = x
            self._click_y = y
            self.after(0, self._on_click)

    def _click_event(self, e: tk.Event) -> None:
        with self._state_lock:
            self._cursor_x = e.x_root
            self._cursor_y = e.y_root
        self._click_x = e.x_root
        self._click_y = e.y_root
        self.after(0, self._on_click)

    def apply_defaults(self) -> None:
        """Reload configuration defaults from environment and config."""
        self.interval = _load_calibrated(
            "KILL_BY_CLICK_INTERVAL", "kill_by_click_interval", tuning.interval
        )
        self.min_interval = _load_calibrated(
            "KILL_BY_CLICK_MIN_INTERVAL",
            "kill_by_click_min_interval",
            tuning.min_interval,
        )
        self.max_interval = _load_calibrated(
            "KILL_BY_CLICK_MAX_INTERVAL",
            "kill_by_click_max_interval",
            tuning.max_interval,
        )
        self.delay_scale = _load_calibrated(
            "KILL_BY_CLICK_DELAY_SCALE",
            "kill_by_click_delay_scale",
            tuning.delay_scale,
        )
        if self.delay_scale <= 0:
            self.delay_scale = tuning.delay_scale
        env = os.getenv("KILL_BY_CLICK_SKIP_CONFIRM")
        self.skip_confirm = env not in (None, "0", "false", "no")

    def reset(self) -> None:
        """Hide the overlay and clear runtime state."""
        try:
            remove_window_clickthrough(self)
        except Exception:
            pass
        self.withdraw()
        for seq in ("<Motion>", "<Button-1>", "<Escape>"):
            try:
                self.unbind(seq)
            except Exception:
                pass
        try:
            self.protocol("WM_DELETE_WINDOW", lambda: None)
        except Exception:
            pass
        self.pid = None
        self.title_text = None
        self._last_info = None
        with self._state_lock:
            self._cached_info = None
        self._hover.reset()
        self._path_history.clear()
        self._point_cache.clear()
        self._active_history.clear()
        self._move_scheduled = False
        self._pending_move = None
        self._closed.set(False)
        self.update_state = UpdateState.IDLE
        self.state = OverlayState.INIT
        self.interval = tuning.interval
        self.min_interval = tuning.min_interval
        self.max_interval = tuning.max_interval

    def close(self, _e: object | None = None) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._timeout_id is not None:
            try:
                self.after_cancel(self._timeout_id)
            except Exception:
                pass
            self._timeout_id = None
        if self._flash_id is not None:
            try:
                self.after_cancel(self._flash_id)
            except Exception:
                pass
            self._flash_id = None
        self.reset()
        self._closed.set(True)

    def choose(self) -> tuple[int | None, str | None]:
        """Show the overlay and return the PID and title of the clicked window."""
        self._closed.set(False)
        listener = get_global_listener()
        listener.start()
        try:
            if is_supported():
                make_window_clickthrough(self)
            self._maybe_ensure_colorkey(force=True)
            self.deiconify()
            self.lift()
            self.update_idletasks()
            self.wait_visibility()
        except Exception:
            pass
        self.bind("<Escape>", self.close)
        self._initial_active_pid = self._active_pid
        if self._initial_active_pid is None:
            try:
                self._initial_active_pid = self._active_window.pid
            except Exception:
                self._initial_active_pid = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        if self.on_hover is not None:
            try:
                self.on_hover(None, None)
            except Exception:
                pass
        use_hooks = is_supported()
        try:
            if use_hooks and listener.start(on_move=self._on_move, on_click=self._click):
                self._using_hooks = True
                self.state = OverlayState.HOOKED
                self._queue_update()
                if self.timeout is not None:
                    self._timeout_id = self.after(
                        int(self.timeout * 1000), self.close
                    )
                self.wait_variable(self._closed)
                return self.pid, self.title_text

            self._using_hooks = False
            self.state = OverlayState.POLLING
            self.bind("<Motion>", self._queue_update)
            self.bind("<Button-1>", self._click_event)
            self._queue_update()
            if self.timeout is not None:
                self._timeout_id = self.after(int(self.timeout * 1000), self.close)
            self.wait_variable(self._closed)
            return self.pid, self.title_text
        finally:
            try:
                listener.stop()
            finally:
                self.reset()

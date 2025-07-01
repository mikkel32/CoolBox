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
import tkinter as tk
from collections import deque
from typing import Optional, Callable
from enum import Enum, auto

from src.utils.window_utils import (
    get_active_window,
    get_window_at,
    list_windows_at,
    make_window_clickthrough,
    remove_window_clickthrough,
    WindowInfo,
)
from src.utils.mouse_listener import capture_mouse, is_supported
from src.utils.scoring_engine import ScoringEngine, tuning

DEFAULT_HIGHLIGHT = os.getenv("KILL_BY_CLICK_HIGHLIGHT", "red")

# Allow the refresh interval to be configured via an environment
# variable. Falling back to the tuning default keeps behaviour
# consistent for tests while providing an easy knob for users.
KILL_BY_CLICK_INTERVAL = float(
    os.getenv("KILL_BY_CLICK_INTERVAL", str(tuning.interval))
)


class UpdateState(Enum):
    IDLE = auto()
    PENDING = auto()


class OverlayState(Enum):
    INIT = auto()
    HOOKED = auto()
    POLLING = auto()


class ClickOverlay(tk.Toplevel):
    """Fullscreen transparent window used to select another window.

    Parameters
    ----------
    parent:
        The parent ``tk`` widget owning the overlay.
    highlight:
        Color used for the selection rectangle and crosshair lines.
    probe_attempts:
        Number of times to retry window detection when the cursor is over one
        of this process's windows.
    timeout:
        Automatically close the overlay after this many seconds if provided.
    on_hover:
        Optional callback invoked with ``(pid, title)`` when the hovered window
        changes.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        highlight: str = DEFAULT_HIGHLIGHT,
        probe_attempts: int = 5,
        timeout: float | None = None,
        interval: float = KILL_BY_CLICK_INTERVAL,
        min_interval: float | None = None,
        max_interval: float | None = None,
        delay_scale: float | None = None,
        skip_confirm: bool | None = None,
        on_hover: Callable[[int | None, str | None], None] | None = None,
    ) -> None:
        super().__init__(parent)
        # Configure fullscreen before enabling override-redirect to avoid
        # "can't set fullscreen attribute" errors on some platforms.
        self.attributes("-topmost", True)
        self.attributes("-fullscreen", True)
        self.overrideredirect(True)
        self.configure(cursor="crosshair")

        # use a unique background color that can be made transparent. this is
        # applied before enabling click-through so the color key matches the
        # actual background when ``make_window_clickthrough`` is called.
        bg_color = parent.cget("bg") if isinstance(parent, tk.Widget) else "#000001"
        self.configure(bg=bg_color)

        if is_supported():
            make_window_clickthrough(self)

        # Using an empty string for the canvas background causes a TclError on
        # some platforms. Use the chosen background color so the canvas itself
        # becomes transparent via the color key.
        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.rect = self.canvas.create_rectangle(0, 0, 1, 1, outline=highlight, width=2)
        # crosshair lines spanning the entire screen for precise selection
        self.hline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
        self.vline = self.canvas.create_line(0, 0, 0, 0, fill=highlight, dash=(4, 2))
        self.label = self.canvas.create_text(
            0,
            0,
            anchor="nw",
            fill=highlight,
            text="",
            font=("TkDefaultFont", 10, "bold"),
        )
        self.probe_attempts = probe_attempts
        self.timeout = timeout
        self.interval = interval
        if min_interval is None:
            try:
                self.min_interval = float(
                    os.getenv("KILL_BY_CLICK_MIN_INTERVAL", str(tuning.min_interval))
                )
            except ValueError:
                self.min_interval = tuning.min_interval
        else:
            self.min_interval = min_interval
        if max_interval is None:
            try:
                self.max_interval = float(
                    os.getenv("KILL_BY_CLICK_MAX_INTERVAL", str(tuning.max_interval))
                )
            except ValueError:
                self.max_interval = tuning.max_interval
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
        self.state = OverlayState.INIT
        self.pid: int | None = None
        self.title_text: str | None = None
        self._last_info: WindowInfo | None = None
        self._screen_w = self.winfo_screenwidth()
        self._screen_h = self.winfo_screenheight()
        self.engine = ScoringEngine(
            tuning,
            self._screen_w,
            self._screen_h,
            os.getpid(),
        )
        self._own_pid = os.getpid()
        self._initial_active_pid: int | None = None
        self._velocity = 0.0
        self._path_history: deque[tuple[int, int]] = deque(maxlen=tuning.path_history)
        self._last_move_time = time.time()
        self._last_move_pos = (0, 0)
        self._pid_stability: dict[int, int] = {}
        self._pid_history = deque(maxlen=tuning.pid_history_size)
        self._info_history = deque(maxlen=tuning.pid_history_size)
        self._current_pid: int | None = None
        self._current_streak: int = 0
        self._click_x = 0
        self._click_y = 0
        self._gaze_duration: dict[int, float] = {}
        self._hover_start = time.monotonic()
        self._last_gaze_pid: int | None = None
        self._last_active_query = 0.0
        self._active_history: deque[tuple[int, float]] = deque(
            maxlen=tuning.active_history_size
        )
        self._last_pid: int | None = None
        self._flash_id: str | None = None
        try:
            self._cursor_x = self.winfo_pointerx()
            self._cursor_y = self.winfo_pointery()
        except Exception:
            self._cursor_x = 0
        self._cursor_y = 0
        self._last_move_pos = (self._cursor_x, self._cursor_y)

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

    def _position_label(self, px: int, py: int, sw: int, sh: int) -> None:
        """Place the info label near the cursor while keeping it on-screen."""
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
        self.canvas.coords(self.label, x, y)

    def _queue_update(self, _e: object | None = None) -> None:
        """Schedule an overlay update in the main thread.

        When called from ``<Motion>`` events this also updates velocity and
        tracking fields so fallback bindings behave like the hook-based path.
        """
        if isinstance(_e, tk.Event):
            now = time.time()
            dx = _e.x_root - self._last_move_pos[0]
            dy = _e.y_root - self._last_move_pos[1]
            dt = now - self._last_move_time
            if dt > 0:
                vel = math.hypot(dx, dy) / dt
                self._velocity = (
                    self._velocity * (1 - tuning.velocity_smooth)
                    + vel * tuning.velocity_smooth
                )
            self._last_move_time = now
            self._last_move_pos = (_e.x_root, _e.y_root)
            self._path_history.append((_e.x_root, _e.y_root))
            self.engine.heatmap.update(_e.x_root, _e.y_root)
            self._cursor_x = _e.x_root
            self._cursor_y = _e.y_root
        else:
            try:
                self._cursor_x = self.winfo_pointerx()
                self._cursor_y = self.winfo_pointery()
            except Exception:
                pass
        if self.update_state is UpdateState.IDLE:
            self.update_state = UpdateState.PENDING
            self.after_idle(self._process_update)

    def _next_delay(self) -> int:
        """Return the delay in milliseconds until the next update."""
        base_ms = self.interval * 1000.0
        min_ms = self.min_interval * 1000.0
        max_ms = self.max_interval * 1000.0
        # Scale the refresh rate using a smooth curve so large
        # cursor movements speed up updates without sudden jumps.
        scale = 1.0 / (1.0 + self._velocity / self.delay_scale)
        delay = base_ms * scale
        delay = max(min(delay, max_ms), min_ms)
        return int(delay)

    def _process_update(self) -> None:
        self.update_state = UpdateState.IDLE
        try:
            self._cursor_x = self.winfo_pointerx()
            self._cursor_y = self.winfo_pointery()
        except Exception:
            pass
        self._update_rect()
        now = time.monotonic()
        if now - self._last_active_query >= self.interval:
            active = get_active_window().pid
            self._last_active_query = now
            if active not in (self._own_pid, None):
                if not self._active_history or self._active_history[-1][0] != active:
                    self._active_history.append((active, now))
        self._after_id = self.after(self._next_delay(), self._queue_update)

    def _on_move(self, x: int, y: int) -> None:
        now = time.time()
        dx = x - self._last_move_pos[0]
        dy = y - self._last_move_pos[1]
        dt = now - self._last_move_time
        if dt > 0:
            vel = math.hypot(dx, dy) / dt
            self._velocity = (
                self._velocity * (1 - tuning.velocity_smooth)
                + vel * tuning.velocity_smooth
            )
        self._last_move_time = now
        self._last_move_pos = (x, y)
        self._path_history.append((x, y))
        self.engine.heatmap.update(x, y)
        self._cursor_x = x
        self._cursor_y = y
        self._queue_update()

    def _query_window(self) -> WindowInfo:
        """Return the window info below the cursor, ignoring this overlay."""

        return self._query_window_at(int(self._cursor_x), int(self._cursor_y))

    def _probe_point(self, x: int, y: int) -> WindowInfo:
        """Return window info at ``(x, y)`` applying fallbacks."""

        info = get_window_at(x, y)
        if info.pid is not None and info.rect is None:
            for win in list_windows_at(x, y):
                if win.pid == info.pid:
                    info = WindowInfo(info.pid, win.rect, info.title or win.title)
                    break
        if info.pid in (self._own_pid, None):
            for win in list_windows_at(x, y):
                if win.pid not in (self._own_pid, None):
                    info = win
                    break
        return info

    def _query_window_at(self, x: int, y: int) -> WindowInfo:
        """Return the window info at ``(x, y)`` in screen coordinates."""

        def probe() -> WindowInfo:
            return self._probe_point(x, y)

        samples: list[WindowInfo] = []

        if self.state is OverlayState.HOOKED:
            info = probe()
            samples.append(info)
            self.engine.tracker.add(info, self._initial_active_pid)
            for _ in range(self.probe_attempts):
                confirm = probe()
                samples.append(confirm)
                self.engine.tracker.add(confirm, self._initial_active_pid)
                if info.pid not in (self._own_pid, None) and confirm.pid == info.pid:
                    break
                info = confirm
        else:
            was_click = make_window_clickthrough(self)
            try:
                info = probe()
                samples.append(info)
                self.engine.tracker.add(info, self._initial_active_pid)
                for _ in range(self.probe_attempts):
                    confirm = probe()
                    samples.append(confirm)
                    self.engine.tracker.add(confirm, self._initial_active_pid)
                    if (
                        info.pid not in (self._own_pid, None)
                        and confirm.pid == info.pid
                    ):
                        break
                    info = confirm
            finally:
                if was_click:
                    remove_window_clickthrough(self)

        choice, ratio, prob = self.engine.weighted_confidence(
            samples,
            self._cursor_x,
            self._cursor_y,
            self._velocity,
            self._path_history,
            self._initial_active_pid,
        )
        if choice is not None:
            info = choice
        attempts = 0
        while (
            ratio < tuning.confidence_ratio or prob < tuning.dominance
        ) and attempts < tuning.extra_attempts:
            more = probe()
            samples.append(more)
            self.engine.tracker.add(more, self._initial_active_pid)
            choice, ratio, prob = self.engine.weighted_confidence(
                samples,
                self._cursor_x,
                self._cursor_y,
                self._velocity,
                self._path_history,
                self._initial_active_pid,
            )
            if choice is not None:
                info = choice
            attempts += 1

        if info.pid in (self._own_pid, None):
            for dx in range(-tuning.near_radius, tuning.near_radius + 1):
                for dy in range(-tuning.near_radius, tuning.near_radius + 1):
                    if dx == 0 and dy == 0:
                        continue
                    alt = self._probe_point(x + dx, y + dy)
                    samples.append(alt)
                    self.engine.tracker.add(alt, self._initial_active_pid)
            choice = self.engine.weighted_choice(
                samples,
                self._cursor_x,
                self._cursor_y,
                self._velocity,
                self._path_history,
                self._initial_active_pid,
            )
            if choice is not None:
                info = choice

        if info.pid is None:
            if self._last_info is not None:
                return self._last_info
            return WindowInfo(None)
        if info.pid == self._own_pid:
            return self._last_info or WindowInfo(None)
        return info

    def _update_rect(self, info: WindowInfo | None = None) -> None:
        if info is None:
            info = self._query_window()
        if not getattr(self, "_raised", False):
            self.lift()
            self._raised = True
        self.pid = info.pid
        self.title_text = info.title
        now = time.monotonic()
        if self._last_gaze_pid is not None and self._last_gaze_pid != info.pid:
            dur = now - self._hover_start
            if self._last_gaze_pid not in (self._own_pid, None):
                self._gaze_duration[self._last_gaze_pid] = (
                    self._gaze_duration.get(self._last_gaze_pid, 0.0) + dur
                )
            self._hover_start = now
        self._last_gaze_pid = info.pid
        for pid in list(self._gaze_duration):
            self._gaze_duration[pid] *= tuning.gaze_decay
            if self._gaze_duration[pid] < tuning.score_min:
                del self._gaze_duration[pid]
        if info.pid not in (self._own_pid, None):
            self._last_info = info
            self._pid_history.append(info.pid)
            self._info_history.append(info)
            self.engine.tracker.add(info, self._initial_active_pid)
            self._pid_stability[info.pid] = self._pid_stability.get(info.pid, 0) + 1
            for pid in list(self._pid_stability):
                if pid != info.pid:
                    self._pid_stability[pid] = max(0, self._pid_stability[pid] - 1)
            if info.pid == self._current_pid:
                self._current_streak += 1
            else:
                self._current_pid = info.pid
                self._current_streak = 1
        elif info.pid is None:
            self._last_info = None

        px = int(self._cursor_x)
        py = int(self._cursor_y)
        cursor_changed = (px, py) != getattr(self, "_last_cursor", (None, None))
        sw = self._screen_w
        sh = self._screen_h
        # Draw crosshair lines centered on the cursor only when moved
        if (
            cursor_changed
            or not hasattr(self, "_last_pos")
            or self._last_pos != (px, py, sw, sh)
        ):
            self.canvas.coords(self.hline, 0, py, sw, py)
            self.canvas.coords(self.vline, px, 0, px, sh)
            self._last_pos = (px, py, sw, sh)

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
            text = info.title or f"PID {info.pid}" if info.pid else ""
        old_pid = getattr(self, "_last_pid", None)
        window_changed = (
            rect != getattr(self, "_last_rect", None) or info.pid != old_pid
        )
        if window_changed:
            self.canvas.coords(self.rect, *rect)
            self._last_rect = rect
            if info.pid != old_pid:
                self._flash_highlight()
        if text != getattr(self, "_last_text", None) or info.pid != old_pid:
            self.canvas.itemconfigure(self.label, text=text)
            self._last_text = text
        if not cursor_changed and not window_changed:
            return
        self._last_cursor = (px, py)
        self._last_pid = info.pid
        self._position_label(px, py, sw, sh)
        if self.on_hover is not None:
            try:
                self.on_hover(self.pid, self.title_text)
            except Exception:
                pass

    def _stable_info(self) -> WindowInfo | None:
        """Return a best guess based solely on recent hover history."""
        if not self._pid_stability:
            return None
        pid, count = max(self._pid_stability.items(), key=lambda i: i[1])
        threshold = tuning.stability_threshold + int(
            self._velocity * tuning.vel_stab_scale
        )
        if count < threshold:
            return None
        for info in reversed(self._info_history):
            if info.pid == pid:
                return info
        return WindowInfo(pid)

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
                    info = get_active_window()
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
            self._cursor_x = x
            self._cursor_y = y
            self._click_x = x
            self._click_y = y
            self.after(0, self._on_click)

    def _click_event(self, e: tk.Event) -> None:
        self._cursor_x = e.x_root
        self._cursor_y = e.y_root
        self._click_x = e.x_root
        self._click_y = e.y_root
        self.after(0, self._on_click)

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
        remove_window_clickthrough(self)
        self.destroy()

    def choose(self) -> tuple[int | None, str | None]:
        """Show the overlay and return the PID and title of the clicked window."""
        self.bind("<Escape>", self.close)
        self._initial_active_pid = get_active_window().pid
        self.protocol("WM_DELETE_WINDOW", self.close)
        if self.on_hover is not None:
            try:
                self.on_hover(None, None)
            except Exception:
                pass
        use_hooks = is_supported()
        if use_hooks:
            with capture_mouse(
                on_move=self._on_move,
                on_click=self._click,
            ) as listener:
                if listener is None:
                    use_hooks = False
                    remove_window_clickthrough(self)
                    self.state = OverlayState.POLLING
                else:
                    self.state = OverlayState.HOOKED
                    self._queue_update()
                    if self.timeout is not None:
                        self._timeout_id = self.after(
                            int(self.timeout * 1000), self.close
                        )
                    self.wait_window()
                    return self.pid, self.title_text

        if not use_hooks:
            remove_window_clickthrough(self)
            self.state = OverlayState.POLLING
        self.bind("<Motion>", self._queue_update)
        self.bind("<Button-1>", self._click_event)
        self._queue_update()
        if self.timeout is not None:
            self._timeout_id = self.after(int(self.timeout * 1000), self.close)
        self.wait_window()
        return self.pid, self.title_text

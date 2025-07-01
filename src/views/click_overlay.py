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
from typing import Optional

from src.utils.window_utils import (
    get_active_window,
    get_window_at,
    list_windows_at,
    make_window_clickthrough,
    remove_window_clickthrough,
    WindowInfo,
)
from src.utils.mouse_listener import capture_mouse, is_supported

# Polling delay used when global hooks aren't available
KILL_BY_CLICK_INTERVAL = float(os.getenv("KILL_BY_CLICK_INTERVAL", "0.03"))
PID_HISTORY_SIZE = int(os.getenv("KILL_BY_CLICK_HISTORY", "5"))
SAMPLE_DECAY = float(os.getenv("KILL_BY_CLICK_SAMPLE_DECAY", "0.85"))
HISTORY_DECAY = float(os.getenv("KILL_BY_CLICK_HISTORY_DECAY", "0.9"))
SAMPLE_WEIGHT = float(os.getenv("KILL_BY_CLICK_SAMPLE_WEIGHT", "1.0"))
HISTORY_WEIGHT = float(os.getenv("KILL_BY_CLICK_HISTORY_WEIGHT", "0.7"))
ACTIVE_BONUS = float(os.getenv("KILL_BY_CLICK_ACTIVE_BONUS", "2.0"))
AREA_WEIGHT = float(os.getenv("KILL_BY_CLICK_AREA_WEIGHT", "0.0"))
CONFIDENCE_RATIO = float(os.getenv("KILL_BY_CLICK_CONFIDENCE", "1.2"))
EXTRA_ATTEMPTS = int(os.getenv("KILL_BY_CLICK_EXTRA_ATTEMPTS", "3"))
SCORE_DECAY = float(os.getenv("KILL_BY_CLICK_SCORE_DECAY", "0.9"))
SCORE_MIN = float(os.getenv("KILL_BY_CLICK_SCORE_MIN", "0.1"))
SOFTMAX_TEMP = float(os.getenv("KILL_BY_CLICK_SOFTMAX_TEMP", "1.0"))
DOMINANCE = float(os.getenv("KILL_BY_CLICK_DOMINANCE", "0.55"))
STABILITY_THRESHOLD = int(os.getenv("KILL_BY_CLICK_STABILITY", "1"))
VELOCITY_SCALE = float(os.getenv("KILL_BY_CLICK_VELOCITY_SCALE", "0.0"))
STABILITY_WEIGHT = float(os.getenv("KILL_BY_CLICK_STABILITY_WEIGHT", "0.0"))
CENTER_WEIGHT = float(os.getenv("KILL_BY_CLICK_CENTER_WEIGHT", "0.0"))
EDGE_PENALTY = float(os.getenv("KILL_BY_CLICK_EDGE_PENALTY", "0.0"))
EDGE_BUFFER = int(os.getenv("KILL_BY_CLICK_EDGE_BUFFER", "5"))
VEL_STAB_SCALE = float(os.getenv("KILL_BY_CLICK_VEL_STAB_SCALE", "0.0"))
PATH_HISTORY = int(os.getenv("KILL_BY_CLICK_PATH_HISTORY", "15"))
PATH_WEIGHT = float(os.getenv("KILL_BY_CLICK_PATH_WEIGHT", "0.0"))
HEATMAP_RES = int(os.getenv("KILL_BY_CLICK_HEATMAP_RES", "64"))
HEATMAP_DECAY = float(os.getenv("KILL_BY_CLICK_HEATMAP_DECAY", "0.9"))
HEATMAP_WEIGHT = float(os.getenv("KILL_BY_CLICK_HEATMAP_WEIGHT", "0.0"))
STREAK_WEIGHT = float(os.getenv("KILL_BY_CLICK_STREAK_WEIGHT", "0.0"))
TRACKER_RATIO = float(os.getenv("KILL_BY_CLICK_TRACKER_RATIO", "1.5"))
RECENCY_WEIGHT = float(os.getenv("KILL_BY_CLICK_RECENCY_WEIGHT", "0.0"))
DURATION_WEIGHT = float(os.getenv("KILL_BY_CLICK_DURATION_WEIGHT", "0.0"))
CONFIRM_DELAY = float(os.getenv("KILL_BY_CLICK_CONFIRM_DELAY", "0.05"))
CONFIRM_WEIGHT = float(os.getenv("KILL_BY_CLICK_CONFIRM_WEIGHT", "1.0"))
ZORDER_WEIGHT = float(os.getenv("KILL_BY_CLICK_ZORDER_WEIGHT", "0.0"))
GAZE_DECAY = float(os.getenv("KILL_BY_CLICK_GAZE_DECAY", "0.9"))
GAZE_WEIGHT = float(os.getenv("KILL_BY_CLICK_GAZE_WEIGHT", "0.0"))
ACTIVE_HISTORY_SIZE = int(os.getenv("KILL_BY_CLICK_ACTIVE_HISTORY", "5"))
ACTIVE_HISTORY_WEIGHT = float(os.getenv("KILL_BY_CLICK_ACTIVE_WEIGHT", "0.0"))
ACTIVE_HISTORY_DECAY = float(os.getenv("KILL_BY_CLICK_ACTIVE_DECAY", "0.9"))
VELOCITY_SMOOTH = float(os.getenv("KILL_BY_CLICK_VEL_SMOOTH", "0.5"))


def _softmax(weights: dict[int, float]) -> dict[int, float]:
    """Return softmax probabilities for ``weights`` using ``SOFTMAX_TEMP``."""
    if not weights:
        return {}
    scale = 1.0 / max(SOFTMAX_TEMP, 1e-6)
    exps = {pid: math.exp(w * scale) for pid, w in weights.items()}
    total = sum(exps.values())
    if total <= 0.0:
        return {}
    return {pid: val / total for pid, val in exps.items()}


class CursorHeatmap:
    """Track cursor dwell time across the screen using a decaying grid."""

    def __init__(self, width: int, height: int) -> None:
        self.res = max(1, HEATMAP_RES)
        self.decay = HEATMAP_DECAY
        self.w = width // self.res + 1
        self.h = height // self.res + 1
        self.grid = [[0.0 for _ in range(self.w)] for _ in range(self.h)]

    def update(self, x: int, y: int) -> None:
        gx = min(int(x / self.res), self.w - 1)
        gy = min(int(y / self.res), self.h - 1)
        for row in self.grid:
            for i in range(len(row)):
                row[i] *= self.decay
        self.grid[gy][gx] += 1.0

    def region_score(self, rect: tuple[int, int, int, int] | None) -> float:
        if not rect:
            return 0.0
        x, y, w, h = rect
        gx1 = max(0, int(x / self.res))
        gy1 = max(0, int(y / self.res))
        gx2 = min(self.w - 1, int((x + w) / self.res))
        gy2 = min(self.h - 1, int((y + h) / self.res))
        total = 0.0
        cells = 0
        for gy in range(gy1, gy2 + 1):
            row = self.grid[gy]
            for gx in range(gx1, gx2 + 1):
                total += row[gx]
                cells += 1
        return total / max(cells, 1)


class WindowTracker:
    """Track window weights with exponential decay."""

    def __init__(self) -> None:
        self.scores: dict[int, float] = {}
        self.info_history: deque[WindowInfo] = deque(maxlen=PID_HISTORY_SIZE)
        self.last_seen: dict[int, float] = {}
        self.durations: dict[int, float] = {}

    def decay(self) -> None:
        for pid in list(self.scores):
            self.scores[pid] *= SCORE_DECAY
            if self.scores[pid] < SCORE_MIN:
                del self.scores[pid]

    def add(self, info: WindowInfo, active: int | None = None) -> None:
        if info.pid is None:
            return
        self.decay()
        weight = SAMPLE_WEIGHT
        if active is not None and info.pid == active:
            weight *= ACTIVE_BONUS
        if info.rect and AREA_WEIGHT:
            area = info.rect[2] * info.rect[3]
            if area:
                weight += AREA_WEIGHT / float(area)
        self.scores[info.pid] = self.scores.get(info.pid, 0.0) + weight
        self.info_history.append(info)
        now = time.monotonic()
        last = self.last_seen.get(info.pid)
        if last is not None:
            self.durations[info.pid] = self.durations.get(info.pid, 0.0) + now - last
        self.last_seen[info.pid] = now

    def best(self) -> WindowInfo | None:
        if not self.scores:
            return None
        pid = max(self.scores.items(), key=lambda i: i[1])[0]
        for info in reversed(self.info_history):
            if info.pid == pid:
                return info
        return WindowInfo(pid)

    def best_with_confidence(self) -> tuple[WindowInfo | None, float]:
        if not self.scores:
            return None, 0.0
        ordered = sorted(self.scores.items(), key=lambda i: i[1], reverse=True)
        best_pid, best_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        info = self.best()
        return info, best_score / (second_score or 1e-6)


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
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        highlight: str = "red",
        probe_attempts: int = 5,
        timeout: float | None = None,
        interval: float = KILL_BY_CLICK_INTERVAL,
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

        self._clickthrough = False
        if is_supported():
            self._clickthrough = make_window_clickthrough(self)

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
        self._after_id: Optional[str] = None
        self._timeout_id: Optional[str] = None
        self._update_pending = False
        self._using_hooks = False
        self.pid: int | None = None
        self.title_text: str | None = None
        self._last_info: WindowInfo | None = None
        self._pid_history = deque(maxlen=PID_HISTORY_SIZE)
        self._info_history = deque(maxlen=PID_HISTORY_SIZE)
        self._tracker = WindowTracker()
        self._own_pid = os.getpid()
        self._initial_active_pid: int | None = None
        self._velocity = 0.0
        self._path_history: deque[tuple[int, int]] = deque(maxlen=PATH_HISTORY)
        self._last_move_time = time.time()
        self._last_move_pos = (0, 0)
        self._pid_stability: dict[int, int] = {}
        self._heatmap = CursorHeatmap(
            self.winfo_screenwidth(), self.winfo_screenheight()
        )
        self._current_pid: int | None = None
        self._current_streak: int = 0
        self._click_x = 0
        self._click_y = 0
        self._gaze_duration: dict[int, float] = {}
        self._hover_start = time.monotonic()
        self._last_gaze_pid: int | None = None
        self._active_history: deque[tuple[int, float]] = deque(maxlen=ACTIVE_HISTORY_SIZE)
        try:
            self._cursor_x = self.winfo_pointerx()
            self._cursor_y = self.winfo_pointery()
        except Exception:
            self._cursor_x = 0
        self._cursor_y = 0
        self._last_move_pos = (self._cursor_x, self._cursor_y)

    def _score_samples(self, samples: list[WindowInfo]) -> dict[int, float]:
        """Return a PID->weight mapping from ``samples`` and hover history."""

        weights: dict[int, float] = dict(self._tracker.scores)
        active = self._initial_active_pid

        power = 1.0
        for info in reversed(
            [s for s in samples if s.pid not in (self._own_pid, None)]
        ):
            vel_factor = 1.0 / (1.0 + self._velocity * VELOCITY_SCALE)
            w = SAMPLE_WEIGHT * power * vel_factor
            if info.pid == active:
                w *= ACTIVE_BONUS
            if info.rect and AREA_WEIGHT:
                area = info.rect[2] * info.rect[3]
                if area:
                    w += AREA_WEIGHT / float(area)
            if info.rect and CENTER_WEIGHT:
                cx = info.rect[0] + info.rect[2] / 2
                cy = info.rect[1] + info.rect[3] / 2
                dist = math.hypot(cx - self._cursor_x, cy - self._cursor_y)
                diag = math.hypot(info.rect[2], info.rect[3])
                if diag:
                    w += CENTER_WEIGHT * (1 - min(dist / diag, 1.0))
            if info.rect and EDGE_PENALTY:
                left = info.rect[0]
                top = info.rect[1]
                right = left + info.rect[2]
                bottom = top + info.rect[3]
                near_x = min(abs(self._cursor_x - left), abs(self._cursor_x - right))
                near_y = min(abs(self._cursor_y - top), abs(self._cursor_y - bottom))
                if near_x <= EDGE_BUFFER or near_y <= EDGE_BUFFER:
                    w *= max(0.0, 1.0 - EDGE_PENALTY)
            if info.rect and PATH_WEIGHT and self._path_history:
                inside = 0
                for px, py in self._path_history:
                    if (
                        info.rect[0] <= px <= info.rect[0] + info.rect[2]
                        and info.rect[1] <= py <= info.rect[1] + info.rect[3]
                    ):
                        inside += 1
                w += PATH_WEIGHT * inside / len(self._path_history)
            if HEATMAP_WEIGHT and info.rect:
                heat = self._heatmap.region_score(info.rect)
                area = info.rect[2] * info.rect[3] or 1
                w += HEATMAP_WEIGHT * heat / float(area)
            weights[info.pid] = weights.get(info.pid, 0.0) + w
            power *= SAMPLE_DECAY

        power = 1.0
        for pid in reversed(self._pid_history):
            vel_factor = 1.0 / (1.0 + self._velocity * VELOCITY_SCALE)
            w = HISTORY_WEIGHT * power * vel_factor
            if pid == active:
                w *= ACTIVE_BONUS
            weights[pid] = weights.get(pid, 0.0) + w
            power *= HISTORY_DECAY

        if STABILITY_WEIGHT:
            for pid, count in self._pid_stability.items():
                weights[pid] = weights.get(pid, 0.0) + count * STABILITY_WEIGHT

        if STREAK_WEIGHT and self._current_pid is not None:
            weights[self._current_pid] = (
                weights.get(self._current_pid, 0.0) + self._current_streak * STREAK_WEIGHT
            )

        now = time.monotonic()
        if RECENCY_WEIGHT:
            for pid, last in self._tracker.last_seen.items():
                weights[pid] = weights.get(pid, 0.0) + RECENCY_WEIGHT / (now - last + 1e-6)
        if DURATION_WEIGHT:
            for pid, dur in self._tracker.durations.items():
                weights[pid] = weights.get(pid, 0.0) + dur * DURATION_WEIGHT

        if ZORDER_WEIGHT:
            stack = list_windows_at(int(self._cursor_x), int(self._cursor_y))
            for idx, info in enumerate(stack):
                if info.pid is None:
                    continue
                weights[info.pid] = weights.get(info.pid, 0.0) + ZORDER_WEIGHT / (idx + 1)

        if GAZE_WEIGHT:
            for pid, dur in self._gaze_duration.items():
                weights[pid] = weights.get(pid, 0.0) + dur * GAZE_WEIGHT

        if ACTIVE_HISTORY_WEIGHT and self._active_history:
            power = 1.0
            for pid, _ in reversed(self._active_history):
                weights[pid] = weights.get(pid, 0.0) + ACTIVE_HISTORY_WEIGHT * power
                power *= ACTIVE_HISTORY_DECAY

        return weights

    def _select_from_weights(
        self, samples: list[WindowInfo], weights: dict[int, float]
    ) -> WindowInfo | None:
        if not weights:
            return None

        pid = max(weights.items(), key=lambda item: item[1])[0]
        for info in reversed(samples):
            if info.pid == pid:
                return info
        for info in reversed(self._info_history):
            if info.pid == pid:
                return info
        return WindowInfo(pid)

    def _weighted_choice(self, samples: list[WindowInfo]) -> WindowInfo | None:
        """Return the best guess from samples and recent history using weights."""

        weights = self._score_samples(samples)
        return self._select_from_weights(samples, weights)

    def _weighted_confidence(
        self, samples: list[WindowInfo]
    ) -> tuple[WindowInfo | None, float, float]:
        """Return the best guess, confidence ratio and probability."""

        weights = self._score_samples(samples)
        if not weights:
            return None, 0.0, 0.0

        probs = _softmax(weights)
        ordered = sorted(probs.items(), key=lambda i: i[1], reverse=True)
        best_pid, best_prob = ordered[0]
        second_prob = ordered[1][1] if len(ordered) > 1 else 0.0
        ratio = best_prob / (second_prob or 1e-6)
        info = self._select_from_weights(samples, weights)
        return info, ratio, best_prob

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
                self._velocity = self._velocity * (1 - VELOCITY_SMOOTH) + vel * VELOCITY_SMOOTH
            self._last_move_time = now
            self._last_move_pos = (_e.x_root, _e.y_root)
            self._path_history.append((_e.x_root, _e.y_root))
            self._heatmap.update(_e.x_root, _e.y_root)
            self._cursor_x = _e.x_root
            self._cursor_y = _e.y_root
        else:
            try:
                self._cursor_x = self.winfo_pointerx()
                self._cursor_y = self.winfo_pointery()
            except Exception:
                pass
        if not self._update_pending:
            self._update_pending = True
            self.after_idle(self._process_update)

    def _process_update(self) -> None:
        self._update_pending = False
        try:
            self._cursor_x = self.winfo_pointerx()
            self._cursor_y = self.winfo_pointery()
        except Exception:
            pass
        self._update_rect()
        active = get_active_window().pid
        if active not in (self._own_pid, None):
            if not self._active_history or self._active_history[-1][0] != active:
                self._active_history.append((active, time.monotonic()))
        self._after_id = self.after(int(self.interval * 1000), self._queue_update)

    def _on_move(self, x: int, y: int) -> None:
        now = time.time()
        dx = x - self._last_move_pos[0]
        dy = y - self._last_move_pos[1]
        dt = now - self._last_move_time
        if dt > 0:
            vel = math.hypot(dx, dy) / dt
            self._velocity = self._velocity * (1 - VELOCITY_SMOOTH) + vel * VELOCITY_SMOOTH
        self._last_move_time = now
        self._last_move_pos = (x, y)
        self._path_history.append((x, y))
        self._heatmap.update(x, y)
        self._cursor_x = x
        self._cursor_y = y
        self._queue_update()

    def _query_window(self) -> WindowInfo:
        """Return the window info below the cursor, ignoring this overlay."""

        return self._query_window_at(int(self._cursor_x), int(self._cursor_y))

    def _query_window_at(self, x: int, y: int) -> WindowInfo:
        """Return the window info at ``(x, y)`` in screen coordinates."""

        def probe() -> WindowInfo:
            return get_window_at(x, y)

        samples: list[WindowInfo] = []

        if self._clickthrough:
            info = probe()
            samples.append(info)
            self._tracker.add(info, self._initial_active_pid)
            for _ in range(self.probe_attempts):
                time.sleep(self.interval)
                confirm = probe()
                samples.append(confirm)
                self._tracker.add(confirm, self._initial_active_pid)
                if info.pid not in (self._own_pid, None) and confirm.pid == info.pid:
                    break
                info = confirm
        else:
            was_click = make_window_clickthrough(self)
            try:
                info = probe()
                samples.append(info)
                self._tracker.add(info, self._initial_active_pid)
                for _ in range(self.probe_attempts):
                    time.sleep(self.interval)
                    confirm = probe()
                    samples.append(confirm)
                    self._tracker.add(confirm, self._initial_active_pid)
                    if (
                        info.pid not in (self._own_pid, None)
                        and confirm.pid == info.pid
                    ):
                        break
                    info = confirm
            finally:
                if was_click:
                    remove_window_clickthrough(self)

        choice, ratio, prob = self._weighted_confidence(samples)
        if choice is not None:
            info = choice
        attempts = 0
        while (ratio < CONFIDENCE_RATIO or prob < DOMINANCE) and attempts < EXTRA_ATTEMPTS:
            time.sleep(self.interval)
            more = probe()
            samples.append(more)
            self._tracker.add(more, self._initial_active_pid)
            choice, ratio, prob = self._weighted_confidence(samples)
            if choice is not None:
                info = choice
            attempts += 1

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
            self._gaze_duration[pid] *= GAZE_DECAY
            if self._gaze_duration[pid] < SCORE_MIN:
                del self._gaze_duration[pid]
        if info.pid not in (self._own_pid, None):
            self._last_info = info
            self._pid_history.append(info.pid)
            self._info_history.append(info)
            self._tracker.add(info, self._initial_active_pid)
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
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Draw crosshair lines centered on the cursor only when moved
        if not hasattr(self, "_last_pos") or self._last_pos != (px, py, sw, sh):
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
        if rect != getattr(self, "_last_rect", None):
            self.canvas.coords(self.rect, *rect)
            self._last_rect = rect
        if text != getattr(self, "_last_text", None):
            self.canvas.itemconfigure(self.label, text=text)
            self._last_text = text
        self._position_label(px, py, sw, sh)

    def _stable_info(self) -> WindowInfo | None:
        """Return a best guess based solely on recent hover history."""
        if not self._pid_stability:
            return None
        pid, count = max(self._pid_stability.items(), key=lambda i: i[1])
        threshold = STABILITY_THRESHOLD + int(self._velocity * VEL_STAB_SCALE)
        if count < threshold:
            return None
        for info in reversed(self._info_history):
            if info.pid == pid:
                return info
        return WindowInfo(pid)

    def _confirm_window(self) -> WindowInfo:
        """Re-query the click location after the overlay closes."""
        time.sleep(CONFIRM_DELAY)
        info = get_window_at(int(self._click_x), int(self._click_y))
        self._tracker.add(info, self._initial_active_pid)
        return info

    def _on_click(self) -> None:
        info: WindowInfo = self._query_window_at(int(self._click_x), int(self._click_y))
        if info.pid in (self._own_pid, None):
            stable = self._stable_info()
            if stable is not None:
                info = stable
            else:
                tracked, ratio = self._tracker.best_with_confidence()
                if tracked is not None and ratio >= TRACKER_RATIO:
                    info = tracked
                elif self._last_info is not None:
                    info = self._last_info
                else:
                    info = get_active_window()
        else:
            self._last_info = info

        self.pid = info.pid
        self.title_text = info.title
        self.close()

        confirm = self._confirm_window()
        samples = [info, confirm]
        weights = self._score_samples(samples)
        if confirm.pid not in (self._own_pid, None):
            weights[confirm.pid] = weights.get(confirm.pid, 0.0) + CONFIRM_WEIGHT
        choice = self._select_from_weights(samples, weights)
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
        if self._clickthrough:
            remove_window_clickthrough(self)
        self.destroy()

    def choose(self) -> tuple[int | None, str | None]:
        """Show the overlay and return the PID and title of the clicked window."""
        self.bind("<Escape>", self.close)
        self._initial_active_pid = get_active_window().pid
        self.protocol("WM_DELETE_WINDOW", self.close)
        use_hooks = self._clickthrough and is_supported()
        if use_hooks:
            with capture_mouse(
                on_move=self._on_move,
                on_click=self._click,
            ) as listener:
                if listener is None:
                    use_hooks = False
                    if self._clickthrough:
                        remove_window_clickthrough(self)
                        self._clickthrough = False
                else:
                    self._using_hooks = True
                    self._queue_update()
                    if self.timeout is not None:
                        self._timeout_id = self.after(
                            int(self.timeout * 1000), self.close
                        )
                    self.wait_window()
                    return self.pid, self.title_text

        self._using_hooks = False
        self.bind("<Motion>", self._queue_update)
        self.bind("<Button-1>", self._click_event)
        self._queue_update()
        if self.timeout is not None:
            self._timeout_id = self.after(int(self.timeout * 1000), self.close)
        self.wait_window()
        return self.pid, self.title_text

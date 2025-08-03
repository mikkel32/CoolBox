from __future__ import annotations

import math
import os
import time
from collections import deque
from dataclasses import dataclass, fields
from typing import Deque, Dict, List, Tuple

from .window_utils import (
    WindowInfo,
    list_windows_at,
    prime_window_cache,
    is_transient_pid,
)

try:  # Optional NumPy acceleration
    import numpy as _np
except Exception:  # pragma: no cover - optional dependency
    _np = None

try:  # Optional Cython helpers for heat-map updates
    from ._heatmap import decay_and_bump as _cy_decay_and_bump
except Exception:  # pragma: no cover - extension may be absent
    _cy_decay_and_bump = None

try:  # Optional Cython helpers for sample scoring
    from ._score_samples import update_weights as _cy_score_samples
except Exception:  # pragma: no cover - extension may be absent
    _cy_score_samples = None


@dataclass(slots=True)
class Tuning:
    """Weight and scoring parameters loaded from environment variables."""

    # Default overlay update interval in seconds. Doubling the frame rate to
    # 120 FPS keeps cursor tracking smooth while still allowing users to
    # override via ``KILL_BY_CLICK_INTERVAL``.
    interval: float = 1 / 120
    # Dynamic adjustment bounds for the overlay refresh delay.
    # The update interval scales between these values based on
    # cursor velocity so quick movements feel responsive while
    # idle periods use fewer resources.
    # Allow the interval to scale between ~240 FPS and ~60 FPS based on cursor
    # velocity so rapid motion speeds up updates and idle periods slow down to
    # conserve resources.
    min_interval: float = 1 / 240
    max_interval: float = 1 / 60
    # Divisor controlling how strongly pointer speed compresses the overlay
    # refresh interval. Larger values make motion influence the delay more
    # gradually while smaller values cause faster updates during quick moves.
    delay_scale: float = 400.0
    pid_history_size: int = 5
    sample_decay: float = 0.85
    history_decay: float = 0.9
    sample_weight: float = 1.0
    history_weight: float = 0.7
    active_bonus: float = 2.0
    area_weight: float = 0.0
    confidence_ratio: float = 1.2
    extra_attempts: int = 3
    score_decay: float = 0.9
    score_min: float = 0.1
    softmax_temp: float = 1.0
    dominance: float = 0.55
    stability_threshold: int = 1
    velocity_scale: float = 0.0
    stability_weight: float = 0.0
    center_weight: float = 0.0
    edge_penalty: float = 0.0
    edge_buffer: int = 5
    vel_stab_scale: float = 0.0
    path_history: int = 15
    path_weight: float = 0.0
    heatmap_res: int = 64
    heatmap_decay: float = 0.9
    heatmap_weight: float = 0.0
    streak_weight: float = 0.0
    tracker_ratio: float = 1.5
    recency_weight: float = 0.0
    duration_weight: float = 0.0
    confirm_delay: float = 0.0
    confirm_weight: float = 1.0
    zorder_weight: float = 0.0
    gaze_decay: float = 0.9
    gaze_weight: float = 0.0
    active_history_size: int = 5
    active_history_weight: float = 0.0
    active_history_decay: float = 0.9
    near_radius: int = 2
    velocity_smooth: float = 0.5
    flash_duration_ms: int = 150

    @classmethod
    def from_env(cls, prefix: str = "") -> "Tuning":
        params = {}
        for f in fields(cls):
            env = os.getenv(f"{prefix}{f.name.upper()}")
            if env is None:
                params[f.name] = f.default
                continue
            try:
                if f.type is int:
                    params[f.name] = int(env)
                elif f.type is float:
                    params[f.name] = float(env)
                else:
                    params[f.name] = env
            except Exception:
                params[f.name] = f.default
        return cls(**params)


def softmax(weights: Dict[int, float], temp: float) -> Dict[int, float]:
    if not weights:
        return {}
    scale = 1.0 / max(temp, 1e-6)
    exps = {pid: math.exp(w * scale) for pid, w in weights.items()}
    total = sum(exps.values())
    if total <= 0.0:
        return {}
    return {pid: val / total for pid, val in exps.items()}


class CursorHeatmap:
    def __init__(self, width: int, height: int, tuning: Tuning) -> None:
        self.tuning = tuning
        self.res = max(1, tuning.heatmap_res)
        self.decay = tuning.heatmap_decay
        self.w = width // self.res + 1
        self.h = height // self.res + 1
        if _np is not None:
            self.grid = _np.zeros((self.h, self.w), dtype=_np.float64)
        else:  # pragma: no cover - slow fallback
            self.grid = [[0.0 for _ in range(self.w)] for _ in range(self.h)]
        self._global_decay = 1.0

    def update(self, x: int, y: int) -> None:
        """Decay the heat-map and bump the cell under ``(x, y)``.

        When ``tuning.heatmap_weight`` is zero the heat-map is not used for
        scoring so we skip the work entirely.
        """
        if self.tuning.heatmap_weight <= 0:
            return
        gx = min(int(x / self.res), self.w - 1)
        gy = min(int(y / self.res), self.h - 1)
        if _cy_decay_and_bump is not None and _np is not None:
            self._global_decay = _cy_decay_and_bump(
                self.grid, self.decay, self._global_decay, gx, gy
            )
            return
        self._global_decay *= self.decay
        if self._global_decay < 1e-6:
            if _np is not None:
                self.grid *= self._global_decay
            else:  # pragma: no cover - slow fallback
                for row in self.grid:
                    for i in range(len(row)):
                        row[i] *= self._global_decay
            self._global_decay = 1.0
        if _np is not None:
            self.grid[gy, gx] += 1.0 / self._global_decay
        else:  # pragma: no cover - slow fallback
            self.grid[gy][gx] += 1.0 / self._global_decay

    def region_score(self, rect: Tuple[int, int, int, int] | None) -> float:
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
        return total * self._global_decay / max(cells, 1)


class WindowTracker:
    def __init__(self, tuning: Tuning) -> None:
        self.tuning = tuning
        self.scores: Dict[int, float] = {}
        self.info_history: Deque[WindowInfo] = deque(maxlen=tuning.pid_history_size)
        self.last_seen: Dict[int, float] = {}
        self.durations: Dict[int, float] = {}

    def decay(self) -> None:
        for pid in list(self.scores):
            self.scores[pid] *= self.tuning.score_decay
            if self.scores[pid] < self.tuning.score_min:
                del self.scores[pid]

    def add(self, info: WindowInfo, active: int | None = None) -> None:
        if info.pid is None:
            return
        self.decay()
        weight = self.tuning.sample_weight
        if active is not None and info.pid == active:
            weight *= self.tuning.active_bonus
        if info.rect and self.tuning.area_weight:
            area = info.rect[2] * info.rect[3]
            if area:
                weight += self.tuning.area_weight / float(area)
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

    def best_with_confidence(self) -> Tuple[WindowInfo | None, float]:
        if not self.scores:
            return None, 0.0
        if _np is not None:
            pids = _np.fromiter(self.scores.keys(), dtype=_np.int64)
            scores = _np.fromiter(self.scores.values(), dtype=_np.float64)
            idx = int(scores.argmax())
            best_pid = int(pids[idx])
            best_score = float(scores[idx])
            if scores.size > 1:
                second_score = float(_np.partition(scores, -2)[-2])
            else:
                second_score = 0.0
        else:  # pragma: no cover - fallback path
            ordered = sorted(self.scores.items(), key=lambda i: i[1], reverse=True)
            best_pid, best_score = ordered[0]
            second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        info = self.best()
        return info, best_score / (second_score or 1e-6)


class ScoringEngine:
    def __init__(self, tuning: Tuning, width: int, height: int, own_pid: int) -> None:
        self.tuning = tuning
        self.own_pid = own_pid
        self.tracker = WindowTracker(tuning)
        self.pid_history: Deque[int] = deque(maxlen=tuning.pid_history_size)
        self.info_history: Deque[WindowInfo] = deque(maxlen=tuning.pid_history_size)
        self.pid_stability: Dict[int, int] = {}
        self.current_pid: int | None = None
        self.current_streak = 0
        self.gaze_duration: Dict[int, float] = {}
        self.active_history: Deque[Tuple[int, float]] = deque(
            maxlen=tuning.active_history_size
        )
        self.heatmap = CursorHeatmap(width, height, tuning)
        prime_window_cache()

    def score_samples(
        self,
        samples: List[WindowInfo],
        cursor_x: float,
        cursor_y: float,
        velocity: float,
        path_history: Deque[Tuple[int, int]],
        initial_active_pid: int | None,
    ) -> Dict[int, float]:
        weights: Dict[int, float] = dict(self.tracker.scores)
        active = initial_active_pid
        if is_transient_pid(active):
            active = None

        relevant_samples = [
            s
            for s in samples
            if s.pid not in (self.own_pid, None) and not is_transient_pid(s.pid)
        ]
        if _cy_score_samples is not None:
            weights = _cy_score_samples(
                relevant_samples,
                cursor_x,
                cursor_y,
                velocity,
                list(path_history),
                self.tuning,
                self.own_pid,
                weights,
                list(self.pid_history),
                self.heatmap,
                active,
            )
        else:
            power = 1.0
            for info in reversed(relevant_samples):
                vel_factor = 1.0 / (1.0 + velocity * self.tuning.velocity_scale)
                w = self.tuning.sample_weight * power * vel_factor
                if info.pid == active:
                    w *= self.tuning.active_bonus
                if info.rect and self.tuning.area_weight:
                    area = info.rect[2] * info.rect[3]
                    if area:
                        w += self.tuning.area_weight / float(area)
                if info.rect and self.tuning.center_weight:
                    cx = info.rect[0] + info.rect[2] / 2
                    cy = info.rect[1] + info.rect[3] / 2
                    dist = math.hypot(cx - cursor_x, cy - cursor_y)
                    diag = math.hypot(info.rect[2], info.rect[3])
                    if diag:
                        w += self.tuning.center_weight * (1 - min(dist / diag, 1.0))
                if info.rect and self.tuning.edge_penalty:
                    left = info.rect[0]
                    top = info.rect[1]
                    right = left + info.rect[2]
                    bottom = top + info.rect[3]
                    near_x = min(abs(cursor_x - left), abs(cursor_x - right))
                    near_y = min(abs(cursor_y - top), abs(cursor_y - bottom))
                    if (
                        near_x <= self.tuning.edge_buffer
                        or near_y <= self.tuning.edge_buffer
                    ):
                        w *= max(0.0, 1.0 - self.tuning.edge_penalty)
                if info.rect and self.tuning.path_weight and path_history:
                    inside = 0
                    for px, py in path_history:
                        if (
                            info.rect[0] <= px <= info.rect[0] + info.rect[2]
                            and info.rect[1] <= py <= info.rect[1] + info.rect[3]
                        ):
                            inside += 1
                    w += self.tuning.path_weight * inside / len(path_history)
                if self.tuning.heatmap_weight and info.rect:
                    heat = self.heatmap.region_score(info.rect)
                    area = info.rect[2] * info.rect[3] or 1
                    w += self.tuning.heatmap_weight * heat / float(area)
                weights[info.pid] = weights.get(info.pid, 0.0) + w
                power *= self.tuning.sample_decay

            power = 1.0
            for pid in reversed(self.pid_history):
                if is_transient_pid(pid):
                    continue
                vel_factor = 1.0 / (1.0 + velocity * self.tuning.velocity_scale)
                w = self.tuning.history_weight * power * vel_factor
                if pid == active:
                    w *= self.tuning.active_bonus
                weights[pid] = weights.get(pid, 0.0) + w
                power *= self.tuning.history_decay

        if self.tuning.stability_weight:
            for pid, count in self.pid_stability.items():
                if is_transient_pid(pid):
                    continue
                weights[pid] = (
                    weights.get(pid, 0.0) + count * self.tuning.stability_weight
                )

        if (
            self.tuning.streak_weight
            and self.current_pid is not None
            and not is_transient_pid(self.current_pid)
        ):
            weights[self.current_pid] = (
                weights.get(self.current_pid, 0.0)
                + self.current_streak * self.tuning.streak_weight
            )

        now = time.monotonic()
        if self.tuning.recency_weight:
            for pid, last in self.tracker.last_seen.items():
                if is_transient_pid(pid):
                    continue
                weights[pid] = weights.get(pid, 0.0) + self.tuning.recency_weight / (
                    now - last + 1e-6
                )
        if self.tuning.duration_weight:
            for pid, dur in self.tracker.durations.items():
                if is_transient_pid(pid):
                    continue
                weights[pid] = weights.get(pid, 0.0) + dur * self.tuning.duration_weight

        if self.tuning.zorder_weight:
            if len(samples) <= 1:
                for info in samples:
                    if info.pid is None:
                        continue
                    weights[info.pid] = weights.get(
                        info.pid, 0.0
                    ) + self.tuning.zorder_weight
            else:
                prime_window_cache()
                stack = list_windows_at(
                    int(cursor_x), int(cursor_y), len(samples)
                )
                for idx, info in enumerate(stack):
                    if info.pid is None:
                        continue
                    weights[info.pid] = weights.get(
                        info.pid, 0.0
                    ) + self.tuning.zorder_weight / (idx + 1)

        if self.tuning.gaze_weight:
            for pid, dur in self.gaze_duration.items():
                if is_transient_pid(pid):
                    continue
                weights[pid] = weights.get(pid, 0.0) + dur * self.tuning.gaze_weight

        if self.tuning.active_history_weight and self.active_history:
            power = 1.0
            for pid, _ in reversed(self.active_history):
                if is_transient_pid(pid):
                    continue
                weights[pid] = (
                    weights.get(pid, 0.0) + self.tuning.active_history_weight * power
                )
                power *= self.tuning.active_history_decay

        return weights

    def select_from_weights(
        self, samples: List[WindowInfo], weights: Dict[int, float]
    ) -> WindowInfo | None:
        if not weights:
            return None
        pid = max(weights.items(), key=lambda item: item[1])[0]
        for info in reversed(samples):
            if info.pid == pid:
                return info
        for info in reversed(self.info_history):
            if info.pid == pid:
                return info
        return WindowInfo(pid)

    def weighted_choice(
        self,
        samples: List[WindowInfo],
        cursor_x: float,
        cursor_y: float,
        velocity: float,
        path_history: Deque[Tuple[int, int]],
        initial_active_pid: int | None,
    ) -> WindowInfo | None:
        weights = self.score_samples(
            samples, cursor_x, cursor_y, velocity, path_history, initial_active_pid
        )
        return self.select_from_weights(samples, weights)

    def weighted_confidence(
        self,
        samples: List[WindowInfo],
        cursor_x: float,
        cursor_y: float,
        velocity: float,
        path_history: Deque[Tuple[int, int]],
        initial_active_pid: int | None,
    ) -> Tuple[WindowInfo | None, float, float]:
        weights = self.score_samples(
            samples, cursor_x, cursor_y, velocity, path_history, initial_active_pid
        )
        if not weights:
            return None, 0.0, 0.0
        probs = softmax(weights, self.tuning.softmax_temp)
        ordered = sorted(probs.items(), key=lambda i: i[1], reverse=True)
        best_pid, best_prob = ordered[0]
        second_prob = ordered[1][1] if len(ordered) > 1 else 0.0
        ratio = best_prob / (second_prob or 1e-6)
        info = self.select_from_weights(samples, weights)
        return info, ratio, best_prob


tuning = Tuning.from_env(prefix="KILL_BY_CLICK_")

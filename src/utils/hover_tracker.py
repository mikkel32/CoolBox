import time
from collections import deque
from typing import Deque, Dict

from src.utils.window_utils import WindowInfo
from src.utils.scoring_engine import tuning


class HoverTracker:
    """Track hover history and estimate stable window focus."""

    def __init__(self) -> None:
        self._gaze_duration: Dict[int, float] = {}
        self._pid_history: Deque[int] = deque(maxlen=tuning.pid_history_size)
        self._info_history: Deque[WindowInfo] = deque(maxlen=tuning.pid_history_size)
        self._pid_stability: Dict[int, int] = {}
        self._current_pid: int | None = None
        self._current_streak: int = 0
        self._hover_start = time.monotonic()
        self._last_pid: int | None = None
        self._last_emitted: WindowInfo | None = None

    # Public accessors -------------------------------------------------
    @property
    def gaze_duration(self) -> Dict[int, float]:
        return self._gaze_duration

    @property
    def pid_history(self) -> Deque[int]:
        return self._pid_history

    @property
    def info_history(self) -> Deque[WindowInfo]:
        return self._info_history

    @property
    def pid_stability(self) -> Dict[int, int]:
        return self._pid_stability

    @property
    def current_pid(self) -> int | None:
        return self._current_pid

    @current_pid.setter
    def current_pid(self, value: int | None) -> None:
        self._current_pid = value

    @property
    def current_streak(self) -> int:
        return self._current_streak

    @current_streak.setter
    def current_streak(self, value: int) -> None:
        self._current_streak = value

    # Core logic -------------------------------------------------------
    def update(self, info: WindowInfo, own_pid: int | None = None) -> None:
        """Update internal hover statistics for ``info``."""
        now = time.monotonic()
        if self._last_pid is None:
            self._last_pid = info.pid
            self._hover_start = now
        elif self._last_pid != info.pid:
            dur = now - self._hover_start
            if self._last_pid not in (own_pid, None):
                self._gaze_duration[self._last_pid] = (
                    self._gaze_duration.get(self._last_pid, 0.0) + dur
                )
            self._hover_start = now
            self._last_pid = info.pid
        for pid in list(self._gaze_duration):
            self._gaze_duration[pid] *= tuning.gaze_decay
            if self._gaze_duration[pid] < tuning.score_min:
                del self._gaze_duration[pid]
        if info.pid not in (own_pid, None):
            self._pid_history.append(info.pid)
            self._info_history.append(info)
            self._pid_stability[info.pid] = self._pid_stability.get(info.pid, 0) + 1
            for pid in list(self._pid_stability):
                if pid != info.pid:
                    self._pid_stability[pid] = max(0, self._pid_stability[pid] - 1)
            if info.pid == self._current_pid:
                self._current_streak += 1
            else:
                self._current_pid = info.pid
                self._current_streak = 1

    def stable_info(self, velocity: float) -> WindowInfo | None:
        """Return a best-guess ``WindowInfo`` based on recent history."""
        if not self._pid_stability:
            return self._last_emitted
        pid, count = max(self._pid_stability.items(), key=lambda i: i[1])
        threshold = tuning.stability_threshold + int(velocity * tuning.vel_stab_scale)
        if count < threshold:
            return self._last_emitted
        for info in reversed(self._info_history):
            if info.pid == pid:
                self._last_emitted = info
                return info
        self._last_emitted = WindowInfo(pid)
        return self._last_emitted

    def reset(self) -> None:
        """Clear all runtime state."""
        self._gaze_duration.clear()
        self._pid_history.clear()
        self._info_history.clear()
        self._pid_stability.clear()
        self._current_pid = None
        self._current_streak = 0
        self._hover_start = time.monotonic()
        self._last_pid = None

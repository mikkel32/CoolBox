"""Process monitoring utilities for the Force Quit dialog."""

from __future__ import annotations

import os
from pathlib import Path

import time
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty, Full
from dataclasses import dataclass, field
from typing import ClassVar
from collections import deque
import heapq
import random
import math
try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()


@dataclass(slots=True)
class MovingAverage:
    """Incremental moving average over a fixed window."""

    window: int
    values: deque[float] = field(default_factory=deque)
    total: float = 0.0

    def add(self, value: float) -> float:
        self.values.append(value)
        self.total += value
        if len(self.values) > self.window:
            self.total -= self.values.popleft()
        return self.average

    def __len__(self) -> int:
        return len(self.values)

    @property
    def average(self) -> float:
        if not self.values:
            return 0.0
        return self.total / len(self.values)


# Thresholds for detecting significant process changes
CHANGE_CPU_THRESHOLD = float(os.getenv("FORCE_QUIT_CHANGE_CPU", "0.5"))
CHANGE_MEM_THRESHOLD = float(os.getenv("FORCE_QUIT_CHANGE_MEM", "1.0"))
CHANGE_IO_THRESHOLD = float(os.getenv("FORCE_QUIT_CHANGE_IO", "0.5"))
CHANGE_SCORE_THRESHOLD = float(os.getenv("FORCE_QUIT_CHANGE_SCORE", "1.0"))
CHANGE_AGG_WINDOW = int(os.getenv("FORCE_QUIT_CHANGE_AGG", "1"))
CHANGE_ALPHA = float(os.getenv("FORCE_QUIT_CHANGE_ALPHA", "0.2"))
CHANGE_RATIO = float(os.getenv("FORCE_QUIT_CHANGE_RATIO", "0.3"))
CHANGE_STD_MULT = float(os.getenv("FORCE_QUIT_CHANGE_STD_MULT", "2.0"))
CHANGE_MAD_MULT = float(os.getenv("FORCE_QUIT_CHANGE_MAD_MULT", "3.0"))
CHANGE_DECAY = float(os.getenv("FORCE_QUIT_CHANGE_DECAY", "0.8"))

# Warning thresholds for classifying processes
WARN_CPU_THRESHOLD = float(os.getenv("FORCE_QUIT_WARN_CPU", "40.0"))
WARN_MEM_THRESHOLD = float(os.getenv("FORCE_QUIT_WARN_MEM", "200.0"))
WARN_IO_THRESHOLD = float(os.getenv("FORCE_QUIT_WARN_IO", "1.0"))

# Critical thresholds for process classification
CPU_ALERT_THRESHOLD = float(os.getenv("FORCE_QUIT_CPU_ALERT", "80.0"))
MEM_ALERT_THRESHOLD = float(os.getenv("FORCE_QUIT_MEM_ALERT", "500.0"))


# Trending thresholds and sample window
TREND_WINDOW = int(os.getenv("FORCE_QUIT_TREND_WINDOW", "5"))
TREND_CPU_THRESHOLD = float(os.getenv("FORCE_QUIT_TREND_CPU", "5.0"))
TREND_MEM_THRESHOLD = float(os.getenv("FORCE_QUIT_TREND_MEM", "50.0"))
TREND_IO_THRESHOLD = float(os.getenv("FORCE_QUIT_TREND_IO", "1.0"))
TREND_IO_WINDOW = int(os.getenv("FORCE_QUIT_TREND_IO_WINDOW", str(TREND_WINDOW)))

# Dynamic CPU sampling for idle processes
IDLE_CPU_THRESHOLD = float(os.getenv("FORCE_QUIT_IDLE_CPU", "0.1"))
IDLE_CYCLES = int(os.getenv("FORCE_QUIT_IDLE_CYCLES", "3"))
MAX_SKIP = int(os.getenv("FORCE_QUIT_MAX_SKIP", "5"))

# Idle CPU baseline learning
IDLE_BASELINE_ALPHA = float(os.getenv("FORCE_QUIT_IDLE_BASELINE", "0.3"))
IDLE_BASELINE_RATIO = float(os.getenv("FORCE_QUIT_IDLE_RATIO", "0.2"))
IDLE_DECAY = float(os.getenv("FORCE_QUIT_IDLE_DECAY", "0.5"))
IDLE_DECAY_EXP = float(os.getenv("FORCE_QUIT_IDLE_DECAY_EXP", "1.0"))

# Global idle baseline
IDLE_GLOBAL_ALPHA = float(os.getenv("FORCE_QUIT_IDLE_GLOBAL_ALPHA", "0.3"))
# Random jitter applied when extending skip intervals so processes do not
# resample in lockstep. Values above ``1.0`` introduce variability.
IDLE_JITTER = float(os.getenv("FORCE_QUIT_IDLE_JITTER", "1.0"))
# Number of recent CPU samples used to compute adaptive idle baselines
IDLE_HISTORY = int(os.getenv("FORCE_QUIT_IDLE_WINDOW", "5"))
# Idle/active hysteresis to prevent flapping near the threshold
IDLE_HYSTERESIS = float(os.getenv("FORCE_QUIT_IDLE_HYSTERESIS", "0.1"))
# Maximum time in seconds a process can be skipped before it is
# force-sampled again to refresh idle baselines
IDLE_REFRESH = float(os.getenv("FORCE_QUIT_IDLE_REFRESH", "30"))
# Idle baseline update factor when CPU sampling is skipped
IDLE_SKIP_ALPHA = float(os.getenv("FORCE_QUIT_IDLE_SKIP_ALPHA", "0.3"))
# Number of initial cycles a new process is always sampled before idle skipping
IDLE_GRACE = int(os.getenv("FORCE_QUIT_IDLE_GRACE", "1"))
# Factor used to extend skip intervals during idle periods
IDLE_MULT = float(os.getenv("FORCE_QUIT_IDLE_MULT", "2.0"))
# Enable dynamic skip interval scaling based on how far CPU usage is below the
# idle threshold. When ``False`` the multiplier is applied directly.
IDLE_DYNAMIC_MULT = os.getenv("FORCE_QUIT_IDLE_DYNAMIC_MULT", "false").lower() in {
    "1",
    "true",
    "yes",
}
# Scale idle multiplier using memory deficits
IDLE_DYNAMIC_MEM = os.getenv("FORCE_QUIT_IDLE_DYNAMIC_MEM", "false").lower() in {
    "1",
    "true",
    "yes",
}
# Scale idle multiplier using I/O deficits
IDLE_DYNAMIC_IO = os.getenv("FORCE_QUIT_IDLE_DYNAMIC_IO", "false").lower() in {
    "1",
    "true",
    "yes",
}
# Combination mode for dynamic scaling: ``mean`` or ``rms``
IDLE_DYNAMIC_MODE = os.getenv("FORCE_QUIT_IDLE_DYNAMIC_MODE", "mean").lower()
# Exponent applied to the combined deficit when scaling skip intervals
IDLE_DYNAMIC_EXP = float(os.getenv("FORCE_QUIT_IDLE_DYNAMIC_EXP", "1.0"))
# Weights applied to CPU, memory and I/O deficits when computing the multiplier
IDLE_CPU_WEIGHT = float(os.getenv("FORCE_QUIT_IDLE_CPU_WEIGHT", "1.0"))
IDLE_MEM_WEIGHT = float(os.getenv("FORCE_QUIT_IDLE_MEM_WEIGHT", "1.0"))
IDLE_IO_WEIGHT = float(os.getenv("FORCE_QUIT_IDLE_IO_WEIGHT", "1.0"))
# Skip interval reset multiplier
IDLE_RESET_RATIO = float(os.getenv("FORCE_QUIT_IDLE_RESET_RATIO", "2.0"))
# Interval in seconds to check for CPU spikes while skipping
IDLE_CHECK_INTERVAL = float(os.getenv("FORCE_QUIT_IDLE_CHECK_INTERVAL", "5"))
# Number of samples gathered after activity resumes before skipping can occur
IDLE_ACTIVE_SAMPLES = int(os.getenv("FORCE_QUIT_IDLE_ACTIVE_SAMPLES", "3"))
# Memory delta in MB that triggers sampling during idle skipping
IDLE_MEM_DELTA = float(os.getenv("FORCE_QUIT_IDLE_MEM_DELTA", "50.0"))
# I/O delta in MB/s that triggers sampling during idle skipping
IDLE_IO_DELTA = float(os.getenv("FORCE_QUIT_IDLE_IO_DELTA", "5.0"))
# Memory usage multiplier that triggers sampling during idle skipping
IDLE_MEM_RATIO = float(os.getenv("FORCE_QUIT_IDLE_MEM_RATIO", "2.0"))
# Reset skip interval when memory usage exceeds this multiple of the baseline
IDLE_MEM_RESET_RATIO = float(os.getenv("FORCE_QUIT_IDLE_MEM_RESET_RATIO", "2.0"))
# I/O throughput multiplier that triggers sampling during idle skipping
IDLE_IO_RATIO = float(os.getenv("FORCE_QUIT_IDLE_IO_RATIO", "2.0"))
# Reset skip interval when I/O usage exceeds this multiple of the baseline
IDLE_IO_RESET_RATIO = float(os.getenv("FORCE_QUIT_IDLE_IO_RESET_RATIO", "2.0"))
# Global memory baseline adaptation factor
IDLE_MEM_GLOBAL_ALPHA = float(os.getenv("FORCE_QUIT_IDLE_MEM_GLOBAL_ALPHA", "0.3"))
# Global I/O baseline adaptation factor
IDLE_IO_GLOBAL_ALPHA = float(os.getenv("FORCE_QUIT_IDLE_IO_GLOBAL_ALPHA", "0.3"))
# Reset skip interval when a process is trending upwards
IDLE_TREND_RESET = os.getenv("FORCE_QUIT_IDLE_TREND_RESET", "true").lower() in {"1", "true", "yes"}
# Number of active cycles recorded after a trending process breaks skipping
IDLE_TREND_SAMPLES = int(os.getenv("FORCE_QUIT_IDLE_TREND_SAMPLES", "3"))

# Bulk CPU time scanning
BULK_CPU_THRESHOLD = int(os.getenv("FORCE_QUIT_BULK_CPU", "20"))
BULK_CPU_WORKERS = int(os.getenv("FORCE_QUIT_BULK_WORKERS", "4"))

# Pause monitoring when overall CPU usage is high
LOAD_THRESHOLD = float(os.getenv("FORCE_QUIT_LOAD_THRESHOLD", "0"))
LOAD_CYCLES = int(os.getenv("FORCE_QUIT_LOAD_CYCLES", "2"))

# Adaptive batch scanning
BATCH_SIZE = int(os.getenv("FORCE_QUIT_BATCH_SIZE", "100"))
AUTO_BATCH = os.getenv("FORCE_QUIT_AUTO_BATCH", "true").lower() in {"1", "true", "yes"}
MIN_BATCH_SIZE = int(os.getenv("FORCE_QUIT_MIN_BATCH", "25"))
MAX_BATCH_SIZE = int(os.getenv("FORCE_QUIT_MAX_BATCH", "1000"))

# Adaptive interval tuning
MIN_INTERVAL = float(os.getenv("FORCE_QUIT_MIN_INTERVAL", "0.5"))
MAX_INTERVAL = float(os.getenv("FORCE_QUIT_MAX_INTERVAL", "10.0"))
AUTO_INTERVAL = os.getenv("FORCE_QUIT_AUTO_INTERVAL", "true").lower() in {"1", "true", "yes"}

# Dynamic thread pool scaling
MIN_WORKERS = int(os.getenv("FORCE_QUIT_MIN_WORKERS", "2"))
MAX_WORKERS = int(os.getenv("FORCE_QUIT_MAX_WORKERS", "16"))


@dataclass(slots=True)
class ProcessEntry:
    """Snapshot of a running process."""

    pid: int
    name: str
    cpu: float
    mem: float
    user: str
    start: float
    status: str
    cpu_time: float
    threads: int
    read_bytes: int
    write_bytes: int
    files: int
    conns: int
    io_rate: float = 0.0
    samples: deque[float] = field(default_factory=deque)
    io_samples: deque[float] = field(default_factory=deque)
    mem_samples: deque[float] = field(default_factory=deque)
    max_samples: int = 5
    delta_cpu: float = 0.0
    delta_mem: float = 0.0
    delta_io: float = 0.0
    ema_cpu: float = 0.0
    ema_mem: float = 0.0
    ema_io: float = 0.0
    baseline_cpu: float = 0.0
    baseline_mem: float = 0.0
    baseline_io: float = 0.0
    baseline_cpu_var: float = 0.0
    baseline_mem_var: float = 0.0
    baseline_io_var: float = 0.0
    baseline_cpu_mad: float = 0.0
    baseline_mem_mad: float = 0.0
    baseline_io_mad: float = 0.0
    level: str = "normal"
    changed: bool = False
    trending_cpu: bool = False
    trending_mem: bool = False
    trending_io: bool = False
    stable: bool = False
    normal: bool = False
    recent_scores: deque[float] = field(default_factory=deque)
    last_score: float = 0.0
    score_sum: float = 0.0
    change_score_threshold: ClassVar[float] = CHANGE_SCORE_THRESHOLD
    change_agg_window: ClassVar[int] = CHANGE_AGG_WINDOW
    change_alpha: ClassVar[float] = CHANGE_ALPHA
    change_ratio: ClassVar[float] = CHANGE_RATIO
    change_std_mult: ClassVar[float] = CHANGE_STD_MULT
    change_mad_mult: ClassVar[float] = CHANGE_MAD_MULT
    change_decay: ClassVar[float] = float(os.getenv("FORCE_QUIT_CHANGE_DECAY", "0.8"))
    cpu_threshold: ClassVar[float] = CHANGE_CPU_THRESHOLD
    mem_threshold: ClassVar[float] = CHANGE_MEM_THRESHOLD
    io_threshold: ClassVar[float] = CHANGE_IO_THRESHOLD
    ema_alpha: ClassVar[float] = 0.3

    def __post_init__(self) -> None:
        self.samples = deque(self.samples, maxlen=self.max_samples)
        self.io_samples = deque(self.io_samples, maxlen=self.max_samples)
        self.mem_samples = deque(self.mem_samples, maxlen=self.max_samples)
        self.recent_scores = deque(self.recent_scores, maxlen=self.change_agg_window)
        self.last_score = 0.0
        self.score_sum = 0.0
        self.ema_cpu = self.cpu
        self.ema_mem = self.mem
        self.ema_io = self.io_rate
        self.baseline_cpu = self.cpu
        self.baseline_mem = self.mem
        self.baseline_io = self.io_rate
        self.baseline_cpu_var = 0.0
        self.baseline_mem_var = 0.0
        self.baseline_io_var = 0.0
        self.baseline_cpu_mad = 0.0
        self.baseline_mem_mad = 0.0
        self.baseline_io_mad = 0.0

    def __lt__(self, other: "ProcessEntry") -> bool:
        """Order entries by average CPU then memory then PID."""
        if not isinstance(other, ProcessEntry):
            return NotImplemented
        return (
            self.avg_cpu,
            self.mem,
            self.pid,
        ) < (
            other.avg_cpu,
            other.mem,
            other.pid,
        )

    def add_sample(self, cpu: float, io: float, mem: float) -> None:
        self.samples.append(cpu)
        self.io_samples.append(io)
        self.mem_samples.append(mem)

    @property
    def avg_cpu(self) -> float:
        if not self.samples:
            return self.cpu
        return sum(self.samples) / len(self.samples)

    @property
    def avg_io(self) -> float:
        if not self.io_samples:
            return self.io_rate
        return sum(self.io_samples) / len(self.io_samples)

    def compute_trends(
        self,
        cpu_window: int,
        mem_window: int,
        io_window: int,
        cpu_thresh: float,
        mem_thresh: float,
        io_thresh: float,
    ) -> None:
        """Update trending flags using slope and exponential moving average."""

        def slope(values: list[float]) -> float:
            n = len(values)
            if n < 2:
                return 0.0
            sum_x = n * (n - 1) / 2
            sum_x2 = (n - 1) * n * (2 * n - 1) / 6
            sum_y = sum(values)
            sum_xy = sum(i * v for i, v in enumerate(values))
            denom = n * sum_x2 - sum_x * sum_x
            if denom == 0:
                return 0.0
            return (n * sum_xy - sum_x * sum_y) / denom

        if len(self.samples) >= cpu_window:
            recent = list(self.samples)[-cpu_window:]
            cpu_slope = slope(recent) * (len(recent) - 1)
        else:
            cpu_slope = 0.0
        if len(self.mem_samples) >= mem_window:
            recent_m = list(self.mem_samples)[-mem_window:]
            mem_slope = slope(recent_m) * (len(recent_m) - 1)
        else:
            mem_slope = 0.0
        if len(self.io_samples) >= io_window:
            recent_io = list(self.io_samples)[-io_window:]
            io_slope = slope(recent_io) * (len(recent_io) - 1)
        else:
            io_slope = 0.0

        if self.samples:
            self.ema_cpu = self.ema_alpha * self.samples[-1] + (1 - self.ema_alpha) * self.ema_cpu
            cpu_diff = self.samples[-1] - self.ema_cpu
        else:
            cpu_diff = 0.0
        if self.mem_samples:
            self.ema_mem = self.ema_alpha * self.mem_samples[-1] + (1 - self.ema_alpha) * self.ema_mem
            mem_diff = self.mem_samples[-1] - self.ema_mem
        else:
            mem_diff = 0.0
        if self.io_samples:
            self.ema_io = self.ema_alpha * self.io_samples[-1] + (1 - self.ema_alpha) * self.ema_io
            io_diff = self.io_samples[-1] - self.ema_io
        else:
            io_diff = 0.0

        self.trending_cpu = max(cpu_slope, cpu_diff) >= cpu_thresh
        self.trending_mem = max(mem_slope, mem_diff) >= mem_thresh
        self.trending_io = max(io_slope, io_diff) >= io_thresh

    def _change_score(self, other: "ProcessEntry") -> float:
        cpu_std = self.baseline_cpu_var ** 0.5
        mem_std = self.baseline_mem_var ** 0.5
        io_std = self.baseline_io_var ** 0.5
        cpu_mad = self.baseline_cpu_mad
        mem_mad = self.baseline_mem_mad
        io_mad = self.baseline_io_mad
        cpu_thr = max(
            0.01,
            self.cpu_threshold,
            self.baseline_cpu * self.change_ratio,
            cpu_std * self.change_std_mult,
            cpu_mad * self.change_mad_mult,
        )
        mem_thr = max(
            0.01,
            self.mem_threshold,
            self.baseline_mem * self.change_ratio,
            mem_std * self.change_std_mult,
            mem_mad * self.change_mad_mult,
        )
        io_thr = max(
            0.01,
            self.io_threshold,
            self.baseline_io * self.change_ratio,
            io_std * self.change_std_mult,
            io_mad * self.change_mad_mult,
        )
        score = (
            abs(other.cpu - self.baseline_cpu) / cpu_thr
            + abs(other.mem - self.baseline_mem) / mem_thr
            + abs(other.io_rate - self.baseline_io) / io_thr
        )
        self._update_baseline(other)
        self.last_score = score
        return score

    def _update_baseline(self, other: "ProcessEntry") -> None:
        alpha = self.change_alpha
        diff = other.cpu - self.baseline_cpu
        self.baseline_cpu += alpha * diff
        self.baseline_cpu_var = (
            (1 - alpha) * self.baseline_cpu_var + alpha * diff * diff
        )
        self.baseline_cpu_mad = (
            (1 - alpha) * self.baseline_cpu_mad + alpha * abs(diff)
        )
        diff = other.mem - self.baseline_mem
        self.baseline_mem += alpha * diff
        self.baseline_mem_var = (
            (1 - alpha) * self.baseline_mem_var + alpha * diff * diff
        )
        self.baseline_mem_mad = (
            (1 - alpha) * self.baseline_mem_mad + alpha * abs(diff)
        )
        diff = other.io_rate - self.baseline_io
        self.baseline_io += alpha * diff
        self.baseline_io_var = (
            (1 - alpha) * self.baseline_io_var + alpha * diff * diff
        )
        self.baseline_io_mad = (
            (1 - alpha) * self.baseline_io_mad + alpha * abs(diff)
        )

    def changed_since(self, other: "ProcessEntry") -> bool:
        if any(
            [
                self.name != other.name,
                self.user != other.user,
                self.status != other.status,
                self.threads != other.threads,
                self.files != other.files,
                self.conns != other.conns,
            ]
        ):
            return True
        score = self._change_score(other)
        self.recent_scores.append(score)
        self.score_sum = self.score_sum * self.change_decay + score
        total = sum(self.recent_scores)
        return max(total, self.score_sum) >= self.change_score_threshold

    def changed_basic(self, other: "ProcessEntry") -> bool:
        """Return True if basic metrics changed since ``other``."""
        if any(
            [
                self.name != other.name,
                self.user != other.user,
                self.status != other.status,
                self.threads != other.threads,
            ]
        ):
            return True
        score = self._change_score(other)
        self.recent_scores.append(score)
        self.score_sum = self.score_sum * self.change_decay + score
        total = sum(self.recent_scores)
        return max(total, self.score_sum) >= self.change_score_threshold

    def update_level(
        self,
        warn_cpu: float,
        warn_mem: float,
        warn_io: float,
        crit_cpu: float,
        crit_mem: float,
    ) -> None:
        """Classify the entry as normal, warning or critical."""
        if (
            self.cpu >= crit_cpu
            or self.mem >= crit_mem
            or self.io_rate >= warn_io * 2
        ):
            self.level = "critical"
        elif (
            self.cpu >= warn_cpu
            or self.mem >= warn_mem
            or self.io_rate >= warn_io
        ):
            self.level = "warning"
        else:
            self.level = "normal"


class ProcessWatcher(threading.Thread):
    """Background thread streaming process snapshots to the UI.

    Metrics are gathered concurrently using a thread pool. Expensive details
    like open file and connection counts are refreshed every ``detail_interval``
    cycles to keep overhead low. Updates are pushed through ``queue`` as
    ``(updates, removed)`` pairs where ``updates`` is a mapping of PID to
    ``ProcessEntry`` instances and ``removed`` is the set of PIDs that have
    disappeared since the last refresh. ``process_count`` tracks how many
    processes were seen in the most recent refresh cycle so the UI can display
    totals without recalculating them each time. Processes that remain unchanged
    for ``stable_cycles`` refreshes are considered stable and only refresh their
    expensive details every ``stable_skip`` cycles, further reducing overhead.
    ``ratio_window`` controls how many recent change ratios are averaged when
    tuning refresh intervals, smoothing out brief spikes. Processes owned by
    any usernames in ``exclude_users`` are skipped entirely.

    Parameters
    ----------
    cpu_alert:
        CPU usage threshold at which a process is classified as ``critical``.
        This complements ``warn_cpu`` and allows callers to distinguish between
        warning and critical states.
    mem_alert:
        Memory usage threshold for the ``critical`` level. Processes exceeding
        this value will be highlighted even if their CPU usage is low.
    """

    def __init__(
        self,
        queue: Queue[tuple[dict[int, ProcessEntry], set[int], float]],
        interval: float = 2.0,
        detail_interval: int = 3,
        max_workers: int | None = None,
        min_workers: int = MIN_WORKERS,
        max_worker_limit: int = MAX_WORKERS,
        sample_size: int = 5,
        limit: int | None = None,
        adaptive: bool = AUTO_INTERVAL,
        adaptive_detail: bool = True,
        *,
        conn_interval: float = 2.0,
        file_interval: float = 2.0,
        cache_ttl: float = 30.0,
        conn_global_threshold: int = 50,
        file_global_threshold: int = 50,
        stable_cycles: int = 10,
        stable_skip: int = 3,
        hide_system: bool = False,
        exclude_users: set[str] | None = None,
        ignore_names: set[str] | None = None,
        slow_ratio: float = 0.02,
        fast_ratio: float = 0.2,
        ratio_window: int = 5,
        trend_window: int = TREND_WINDOW,
        trend_cpu: float = TREND_CPU_THRESHOLD,
        trend_mem: float = TREND_MEM_THRESHOLD,
        trend_io: float = TREND_IO_THRESHOLD,
        trend_io_window: int = TREND_IO_WINDOW,
        trend_slow_ratio: float = 0.05,
        trend_fast_ratio: float = 0.25,
        normal_window: int = 3,
        visible_cpu: float = CHANGE_CPU_THRESHOLD,
        visible_mem: float = 10.0,
        visible_io: float = 0.1,
        visible_auto: bool = False,
        warn_cpu: float = WARN_CPU_THRESHOLD,
        warn_mem: float = WARN_MEM_THRESHOLD,
        warn_io: float = WARN_IO_THRESHOLD,
        cpu_alert: float = CPU_ALERT_THRESHOLD,
        mem_alert: float = MEM_ALERT_THRESHOLD,
        ignore_age: float = 1.0,
        change_alpha: float = CHANGE_ALPHA,
        change_ratio: float = CHANGE_RATIO,
        change_mad_mult: float = CHANGE_MAD_MULT,
        change_decay: float = CHANGE_DECAY,
        idle_cpu: float = IDLE_CPU_THRESHOLD,
        idle_cycles: int = IDLE_CYCLES,
        max_skip: int = MAX_SKIP,
        idle_baseline: float = IDLE_BASELINE_ALPHA,
        idle_ratio: float = IDLE_BASELINE_RATIO,
        idle_decay: float = IDLE_DECAY,
        idle_decay_exp: float = IDLE_DECAY_EXP,
        idle_global_alpha: float = IDLE_GLOBAL_ALPHA,
        idle_jitter: float = IDLE_JITTER,
        idle_window: int = IDLE_HISTORY,
        idle_hysteresis: float = IDLE_HYSTERESIS,
        idle_refresh: float = IDLE_REFRESH,
        idle_skip_alpha: float = IDLE_SKIP_ALPHA,
        idle_grace: int = IDLE_GRACE,
        idle_mult: float = IDLE_MULT,
        idle_reset_ratio: float = IDLE_RESET_RATIO,
        idle_check_interval: float = IDLE_CHECK_INTERVAL,
        idle_active_samples: int = IDLE_ACTIVE_SAMPLES,
        idle_trend_samples: int = IDLE_TREND_SAMPLES,
        idle_mem_delta: float = IDLE_MEM_DELTA,
        idle_io_delta: float = IDLE_IO_DELTA,
        idle_mem_ratio: float = IDLE_MEM_RATIO,
        idle_io_ratio: float = IDLE_IO_RATIO,
        idle_mem_reset_ratio: float = IDLE_MEM_RESET_RATIO,
        idle_io_reset_ratio: float = IDLE_IO_RESET_RATIO,
        idle_mem_global_alpha: float = IDLE_MEM_GLOBAL_ALPHA,
        idle_io_global_alpha: float = IDLE_IO_GLOBAL_ALPHA,
        idle_trend_reset: bool = IDLE_TREND_RESET,
        idle_dynamic_mult: bool = IDLE_DYNAMIC_MULT,
        idle_dynamic_mem: bool = IDLE_DYNAMIC_MEM,
        idle_dynamic_io: bool = IDLE_DYNAMIC_IO,
        idle_dynamic_mode: str = IDLE_DYNAMIC_MODE,
        idle_dynamic_exp: float = IDLE_DYNAMIC_EXP,
        idle_cpu_weight: float = IDLE_CPU_WEIGHT,
        idle_mem_weight: float = IDLE_MEM_WEIGHT,
        idle_io_weight: float = IDLE_IO_WEIGHT,
        bulk_cpu_threshold: int = BULK_CPU_THRESHOLD,
        bulk_cpu_workers: int = BULK_CPU_WORKERS,
        load_threshold: float = LOAD_THRESHOLD,
        load_cycles: int = LOAD_CYCLES,
        batch_size: int = BATCH_SIZE,
        auto_batch: bool = AUTO_BATCH,
        min_batch_size: int = MIN_BATCH_SIZE,
        max_batch_size: int = MAX_BATCH_SIZE,
        min_interval: float = MIN_INTERVAL,
        max_interval: float = MAX_INTERVAL,
    ) -> None:
        super().__init__(daemon=True)
        self.queue = queue
        self.min_interval = max(0.1, float(min_interval))
        self.max_interval = max(self.min_interval, float(max_interval))
        self.interval = float(interval)
        self.interval = max(self.min_interval, min(self.max_interval, self.interval))
        self.target_interval = self.interval
        self.detail_interval = max(1, detail_interval)
        self.target_detail_interval = self.detail_interval
        self.limit = limit
        self.adaptive = adaptive
        self.adaptive_detail = adaptive_detail
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._snapshot: dict[int, ProcessEntry] = {}
        self._detail_ts: dict[int, float] = {}
        self._conn_cache: dict[int, tuple[int, float]] = {}
        self._file_cache: dict[int, tuple[int, float]] = {}
        self._file_future = None
        self._global_conn_future = None
        self._global_file_future = None
        self._global_conn_data: dict[int, int] = {}
        self._global_conn_ts = 0.0
        self._global_file_data: dict[int, int] = {}
        self._global_file_ts = 0.0
        self.conn_interval = float(conn_interval)
        self.file_interval = float(file_interval)
        self.cache_ttl = float(cache_ttl)
        self.conn_global_threshold = int(conn_global_threshold)
        self.file_global_threshold = int(file_global_threshold)
        self._last_ts = time.monotonic()
        workers = max_workers or min(8, (os.cpu_count() or 1) * 2)
        workers = min(max_worker_limit, max(min_workers, workers))
        self.min_workers = min_workers
        self.max_workers = max_worker_limit
        self._executor = ThreadPoolExecutor(max_workers=workers)
        self._cpu_count = psutil.cpu_count(logical=True) or (os.cpu_count() or 1)
        self.sample_size = max(1, sample_size)
        self.process_count = 0
        self._last_detail_count = 0
        self._stable_cycles = max(1, int(stable_cycles))
        self._stable_skip = max(1, int(stable_skip))
        self._stable_counts: dict[int, int] = {}
        self._slow_ratio = float(slow_ratio)
        self._fast_ratio = float(fast_ratio)
        self._ratio_window = max(1, int(ratio_window))
        self._ratio_history: deque[float] = deque(maxlen=self._ratio_window)
        self.hide_system = hide_system
        self.exclude_users: set[str] = {u.lower() for u in (exclude_users or set())}
        self.ignore_names: set[str] = {n.lower() for n in (ignore_names or set())}
        self._trend_window = max(1, int(trend_window))
        self._trend_cpu = float(trend_cpu)
        self._trend_mem = float(trend_mem)
        self._trend_io = float(trend_io)
        self._trend_io_window = max(1, int(trend_io_window))
        self._trend_slow_ratio = float(trend_slow_ratio)
        self._trend_fast_ratio = float(trend_fast_ratio)
        self._trend_history: deque[float] = deque(maxlen=self._ratio_window)
        self._normal_window = max(1, int(normal_window))
        self.visible_cpu = float(visible_cpu)
        self.visible_mem = float(visible_mem)
        self.visible_io = float(visible_io)
        self.visible_auto = bool(visible_auto)
        self.warn_cpu = float(warn_cpu)
        self.warn_mem = float(warn_mem)
        self.warn_io = float(warn_io)
        self.cpu_alert = float(cpu_alert)
        self.mem_alert = float(mem_alert)
        self.ignore_age = float(ignore_age)
        self.change_alpha = float(change_alpha)
        self.change_ratio = float(change_ratio)
        self.change_mad_mult = float(change_mad_mult)
        self.change_decay = float(change_decay)
        ProcessEntry.change_decay = self.change_decay
        self._auto_cpu = 0.0
        self._auto_mem = 0.0
        self._auto_io = 0.0
        self._normal_counts: dict[int, int] = {}
        self._idle_counts: dict[int, int] = {}
        self._cpu_skip_counts: dict[int, int] = {}
        self._cpu_skip_intervals: dict[int, int] = {}
        self._cpu_ts: dict[int, float] = {}
        self._idle_baseline: dict[int, float] = {}
        self.idle_cpu = float(idle_cpu)
        self.idle_cycles = max(1, int(idle_cycles))
        self.max_skip = max(1, int(max_skip))
        self.idle_baseline_alpha = float(idle_baseline)
        self.idle_ratio = float(idle_ratio)
        self.idle_decay = float(idle_decay)
        self.idle_decay_exp = max(0.1, float(idle_decay_exp))
        self.idle_global_alpha = float(idle_global_alpha)
        self.idle_jitter = max(1.0, float(idle_jitter))
        self.idle_window = max(1, int(idle_window))
        self.idle_hysteresis = max(0.0, float(idle_hysteresis))
        self.idle_refresh = max(0.0, float(idle_refresh))
        self.idle_skip_alpha = max(0.0, min(1.0, float(idle_skip_alpha)))
        self.idle_grace = max(0, int(idle_grace))
        self.idle_mult = max(1.0, float(idle_mult))
        self.idle_dynamic_mult = bool(idle_dynamic_mult)
        self.idle_dynamic_mem = bool(idle_dynamic_mem)
        self.idle_dynamic_io = bool(idle_dynamic_io)
        self.idle_dynamic_mode = str(idle_dynamic_mode).lower()
        self.idle_dynamic_exp = max(0.1, float(idle_dynamic_exp))
        self.idle_cpu_weight = max(0.0, float(idle_cpu_weight))
        self.idle_mem_weight = max(0.0, float(idle_mem_weight))
        self.idle_io_weight = max(0.0, float(idle_io_weight))
        self.idle_reset_ratio = max(1.0, float(idle_reset_ratio))
        self.idle_check_interval = max(0.0, float(idle_check_interval))
        self.idle_active_samples = max(0, int(idle_active_samples))
        self.idle_trend_samples = max(0, int(idle_trend_samples))
        self.idle_mem_delta = max(0.0, float(idle_mem_delta))
        self.idle_io_delta = max(0.0, float(idle_io_delta))
        self.idle_mem_ratio = max(1.0, float(idle_mem_ratio))
        self.idle_io_ratio = max(1.0, float(idle_io_ratio))
        self.idle_mem_reset_ratio = max(1.0, float(idle_mem_reset_ratio))
        self.idle_io_reset_ratio = max(1.0, float(idle_io_reset_ratio))
        self.idle_mem_global_alpha = float(idle_mem_global_alpha)
        self.idle_io_global_alpha = float(idle_io_global_alpha)
        self.idle_trend_reset = bool(idle_trend_reset)
        self._global_idle_baseline = 0.0
        self._grace_counts: dict[int, int] = {}
        self._idle_history: dict[int, MovingAverage] = {}
        self._global_idle_history = MovingAverage(self.idle_window)
        self._idle_state: dict[int, bool] = {}
        self._active_counts: dict[int, int] = {}
        self._idle_mem_baseline: dict[int, float] = {}
        self._idle_io_baseline: dict[int, float] = {}
        self._idle_mem_history: dict[int, MovingAverage] = {}
        self._idle_io_history: dict[int, MovingAverage] = {}
        self._global_mem_baseline = 0.0
        self._global_io_baseline = 0.0
        self._global_mem_history = MovingAverage(self.idle_window)
        self._global_io_history = MovingAverage(self.idle_window)
        self.bulk_cpu_threshold = max(1, int(bulk_cpu_threshold))
        self.bulk_cpu_workers = max(1, int(bulk_cpu_workers))
        self.load_threshold = float(load_threshold)
        self.load_cycles = max(1, int(load_cycles))
        self._load_skip = 0
        self._prev_system_time = self._system_time()
        self._system_time_delta = float(self._cpu_count)
        self.batch_size = max(1, int(batch_size))
        self.auto_batch = bool(auto_batch)
        self.min_batch_size = max(1, int(min_batch_size))
        self.max_batch_size = max(self.min_batch_size, int(max_batch_size))
        self._batch_history = deque(maxlen=5)
        self._interval_history = deque(maxlen=5)
        self._cycle_time_history = deque(maxlen=5)
        self._throughput_history = deque(maxlen=5)
        self._proc_iter = None
        self._proc_pids: list[int] = []
        self._new_pids: set[int] = set()
        self._cycle_updates = 0
        self._cycle_trending = 0
        self._cycle_elapsed = 0.0
        self._last_change_ratio = 0.0
        self._last_trend_ratio = 0.0
        self._processed_batches = 0
        self._total_batches = 1

    def _update_idle_state(self, pid: int, cpu: float, mem: float, io_rate: float) -> None:
        """Update idle counters and skip interval for *pid* based on usage."""

        hist = self._idle_history.setdefault(pid, MovingAverage(self.idle_window))
        avg = hist.add(cpu)
        baseline = self._idle_baseline.get(pid, self._global_idle_baseline or avg)
        baseline = baseline * (1 - self.idle_baseline_alpha) + avg * self.idle_baseline_alpha
        self._idle_baseline[pid] = baseline
        gavg = self._global_idle_history.add(cpu)
        self._global_idle_baseline = (
            self._global_idle_baseline * (1 - self.idle_global_alpha)
            + gavg * self.idle_global_alpha
        )

        mhist = self._idle_mem_history.setdefault(pid, MovingAverage(self.idle_window))
        mavg = mhist.add(mem)
        mbaseline = self._idle_mem_baseline.get(pid, mavg)
        mbaseline = mbaseline * (1 - self.idle_baseline_alpha) + mavg * self.idle_baseline_alpha
        self._idle_mem_baseline[pid] = mbaseline
        mgavg = self._global_mem_history.add(mem)
        self._global_mem_baseline = (
            self._global_mem_baseline * (1 - self.idle_mem_global_alpha)
            + mgavg * self.idle_mem_global_alpha
        )

        ihist = self._idle_io_history.setdefault(pid, MovingAverage(self.idle_window))
        iavg = ihist.add(io_rate)
        ibaseline = self._idle_io_baseline.get(pid, iavg)
        ibaseline = ibaseline * (1 - self.idle_baseline_alpha) + iavg * self.idle_baseline_alpha
        self._idle_io_baseline[pid] = ibaseline
        igavg = self._global_io_history.add(io_rate)
        self._global_io_baseline = (
            self._global_io_baseline * (1 - self.idle_io_global_alpha)
            + igavg * self.idle_io_global_alpha
        )

        grace = self._grace_counts.get(pid, self.idle_grace)
        if grace <= self.idle_grace:
            self._idle_state[pid] = False
            self._idle_counts[pid] = 0
            self._cpu_skip_intervals[pid] = 1
            return

        thr = max(self.idle_cpu, baseline * self.idle_ratio)
        upper = thr * (1 + self.idle_hysteresis)
        lower = thr * (1 - self.idle_hysteresis)
        state = self._idle_state.get(pid, False)

        if cpu > thr * self.idle_reset_ratio:
            state = False
            self._cpu_skip_intervals[pid] = 1
            prev_idle = self._idle_counts.get(pid, 0)
            self._idle_counts[pid] = 0
            self._idle_state[pid] = state
            if self._active_counts.get(pid, 0) == 0 and prev_idle > 0:
                self._active_counts[pid] = self.idle_active_samples
            return

        if mem > mbaseline * self.idle_mem_reset_ratio:
            self._cpu_skip_intervals[pid] = 1
            prev_idle = self._idle_counts.get(pid, 0)
            self._idle_counts[pid] = 0
            self._idle_state[pid] = False
            if self._active_counts.get(pid, 0) == 0 and prev_idle > 0:
                self._active_counts[pid] = self.idle_active_samples
            return

        if io_rate > ibaseline * self.idle_io_reset_ratio:
            self._cpu_skip_intervals[pid] = 1
            prev_idle = self._idle_counts.get(pid, 0)
            self._idle_counts[pid] = 0
            self._idle_state[pid] = False
            if self._active_counts.get(pid, 0) == 0 and prev_idle > 0:
                self._active_counts[pid] = self.idle_active_samples
            return

        if state:
            if cpu > upper:
                state = False
                if self._active_counts.get(pid, 0) == 0 and self._idle_counts.get(pid, 0) > 0:
                    self._active_counts[pid] = self.idle_active_samples
        else:
            if cpu < lower:
                state = True

        self._idle_state[pid] = state

        if state:
            self._idle_counts[pid] = self._idle_counts.get(pid, 0) + 1
            if self._idle_counts[pid] >= self.idle_cycles:
                prev_int = self._cpu_skip_intervals.get(pid, 1)
                jitter = 1.0
                if self.idle_jitter > 1.0:
                    jitter = random.uniform(1.0, self.idle_jitter)
                factor = self.idle_mult
                deficits: list[float] = []
                weights: list[float] = []
                if self.idle_dynamic_mult:
                    diff = max(0.0, min(thr, thr - cpu))
                    deficits.append(diff / max(thr, 0.001))
                    weights.append(self.idle_cpu_weight)
                if self.idle_dynamic_mem:
                    base_mem = self._idle_mem_baseline.get(pid, mem)
                    if base_mem > 0:
                        deficits.append(max(0.0, base_mem - mem) / base_mem)
                        weights.append(self.idle_mem_weight)
                if self.idle_dynamic_io:
                    base_io = self._idle_io_baseline.get(pid, io_rate)
                    if base_io > 0:
                        deficits.append(max(0.0, base_io - io_rate) / base_io)
                        weights.append(self.idle_io_weight)
                if deficits:
                    if self.idle_dynamic_mode == "rms":
                        scaled = math.sqrt(
                            sum((d * w) ** 2 for d, w in zip(deficits, weights))
                            / len(deficits)
                        )
                    else:
                        scaled = sum(d * w for d, w in zip(deficits, weights)) / len(deficits)
                    scaled = min(1.0, max(0.0, scaled))
                    scaled = scaled ** self.idle_dynamic_exp
                    factor = 1 + (self.idle_mult - 1) * scaled
                self._cpu_skip_intervals[pid] = min(
                    int(prev_int * factor * jitter),
                    self.max_skip,
                )
        else:
            self._idle_counts[pid] = 0
            prev_int = self._cpu_skip_intervals.get(pid, 1)
            decay = self.idle_decay
            if self.idle_dynamic_mult and cpu > thr:
                diff = (cpu - thr) / max(thr, 0.001)
                decay = decay ** (1 + diff ** self.idle_decay_exp)
            self._cpu_skip_intervals[pid] = max(
                1, int(prev_int * decay)
            )

    def _reset_idle_state(self, pid: int) -> None:
        """Remove idle tracking state for *pid*."""

        self._idle_counts.pop(pid, None)
        self._cpu_skip_counts.pop(pid, None)
        self._cpu_skip_intervals.pop(pid, None)
        self._idle_baseline.pop(pid, None)
        self._idle_history.pop(pid, None)
        self._cpu_ts.pop(pid, None)
        self._idle_state.pop(pid, None)
        self._grace_counts.pop(pid, None)
        self._active_counts.pop(pid, None)
        self._idle_mem_baseline.pop(pid, None)
        self._idle_io_baseline.pop(pid, None)
        self._idle_mem_history.pop(pid, None)
        self._idle_io_history.pop(pid, None)

    def _record_idle_sample(self, pid: int, cpu: float, mem: float, io_rate: float) -> None:
        """Update baselines when sampling is skipped."""

        hist = self._idle_history.setdefault(pid, MovingAverage(self.idle_window))
        avg = hist.add(cpu)
        baseline = self._idle_baseline.get(pid, self._global_idle_baseline or avg)
        alpha = self.idle_skip_alpha
        self._idle_baseline[pid] = baseline * (1 - alpha) + avg * alpha
        gavg = self._global_idle_history.add(cpu)
        self._global_idle_baseline = (
            self._global_idle_baseline * (1 - self.idle_global_alpha)
            + gavg * self.idle_global_alpha
        )
        mhist = self._idle_mem_history.setdefault(pid, MovingAverage(self.idle_window))
        mavg = mhist.add(mem)
        mbaseline = self._idle_mem_baseline.get(pid, mavg)
        self._idle_mem_baseline[pid] = mbaseline * (1 - alpha) + mavg * alpha
        mgavg = self._global_mem_history.add(mem)
        self._global_mem_baseline = (
            self._global_mem_baseline * (1 - self.idle_mem_global_alpha)
            + mgavg * self.idle_mem_global_alpha
        )
        ihist = self._idle_io_history.setdefault(pid, MovingAverage(self.idle_window))
        iavg = ihist.add(io_rate)
        ibaseline = self._idle_io_baseline.get(pid, iavg)
        self._idle_io_baseline[pid] = ibaseline * (1 - alpha) + iavg * alpha
        igavg = self._global_io_history.add(io_rate)
        self._global_io_baseline = (
            self._global_io_baseline * (1 - self.idle_io_global_alpha)
            + igavg * self.idle_io_global_alpha
        )

    def _should_skip_cpu(
        self,
        pid: int,
        proc: psutil.Process,
        prev: ProcessEntry | None,
        ts: float,
        bulk: dict[int, float] | None = None,
    ) -> bool:
        """Return ``True`` if CPU sampling should be skipped for ``pid``.

        When the time since the last sample exceeds ``idle_check_interval`` a
        lightweight CPU time check is performed. If usage exceeds
        ``idle_reset_ratio`` times the idle threshold, the skip interval is
        reset so spikes are detected quickly.
        """

        active = self._active_counts.get(pid, 0)
        if active > 0:
            self._active_counts[pid] = active - 1
            return False
        if (
            self.idle_trend_reset
            and prev is not None
            and (
                prev.trending_cpu
                or prev.trending_mem
                or prev.trending_io
            )
        ):
            self._cpu_skip_intervals[pid] = 1
            self._idle_counts[pid] = 0
            self._idle_state[pid] = False
            self._active_counts[pid] = max(
                self._active_counts.get(pid, 0), self.idle_trend_samples
            )
            return False
        if prev is None:
            self._grace_counts[pid] = 1
            return False
        grace = self._grace_counts.get(pid, self.idle_grace)
        if grace <= self.idle_grace:
            self._grace_counts[pid] = grace + 1
            return False
        skip_int = self._cpu_skip_intervals.get(pid, 1)
        skip_count = self._cpu_skip_counts.get(pid, 0)
        if skip_int > 1 and skip_count < skip_int:
            last = self._cpu_ts.get(pid, ts)
            if ts - last < self.idle_refresh:
                if ts - last >= self.idle_check_interval:
                    try:
                        mem = proc.memory_info().rss / (1024 * 1024)
                    except Exception:
                        mem = prev.mem
                    base_mem = self._idle_mem_baseline.get(pid, prev.mem)
                    if (
                        mem - prev.mem > self.idle_mem_delta
                        or mem > base_mem * self.idle_mem_ratio
                    ):
                        self._cpu_skip_intervals[pid] = 1
                        prev_idle = self._idle_counts.get(pid, 0)
                        self._idle_counts[pid] = 0
                        self._idle_state[pid] = False
                        if self._active_counts.get(pid, 0) == 0 and prev_idle > 0:
                            self._active_counts[pid] = self.idle_active_samples
                        return False
                    if mem > base_mem * self.idle_mem_reset_ratio:
                        self._active_counts[pid] = self.idle_active_samples
                        return False
                    try:
                        io = proc.io_counters()
                        io_rate = (
                            io.read_bytes
                            - prev.read_bytes
                            + io.write_bytes
                            - prev.write_bytes
                        ) / max(ts - last, 0.001) / (1024 * 1024)
                    except Exception:
                        io_rate = 0.0
                    base_io = self._idle_io_baseline.get(pid, prev.io_rate)
                    if (
                        io_rate > self.idle_io_delta
                        or io_rate > base_io * self.idle_io_ratio
                    ):
                        self._cpu_skip_intervals[pid] = 1
                        prev_idle = self._idle_counts.get(pid, 0)
                        self._idle_counts[pid] = 0
                        self._idle_state[pid] = False
                        if self._active_counts.get(pid, 0) == 0 and prev_idle > 0:
                            self._active_counts[pid] = self.idle_active_samples
                        return False
                    if io_rate > base_io * self.idle_io_reset_ratio:
                        self._active_counts[pid] = self.idle_active_samples
                        return False

                    cpu_time = self._proc_cpu_time(pid, proc, bulk)
                    cpu = (cpu_time - prev.cpu_time) / self._system_time_delta * 100
                    thr = max(
                        self.idle_cpu,
                        self._idle_baseline.get(pid, self.idle_cpu) * self.idle_ratio,
                    )
                    if cpu > thr * self.idle_reset_ratio:
                        self._active_counts[pid] = self.idle_active_samples
                        return False
                return True
        return False

    def _should_pause_for_load(self) -> bool:
        """Return ``True`` if monitoring should pause due to system load."""

        if self.load_threshold <= 0:
            return False
        if self._load_skip > 0:
            self._load_skip -= 1
            return True
        try:
            load = psutil.cpu_percent(interval=None)
        except Exception:
            return False
        if load >= self.load_threshold:
            self._load_skip = self.load_cycles - 1
            return True
        return False

    def _should_ignore_process(self, name: str) -> bool:
        """Return ``True`` if ``name`` matches any ignored process name."""
        return name.lower() in self.ignore_names

    def _proc_cpu_time(
        self,
        pid: int,
        proc: psutil.Process,
        bulk: dict[int, float] | None = None,
    ) -> float:
        """Return cumulative CPU time for *pid* with a fast `/proc` path."""

        if bulk and pid in bulk:
            return bulk[pid]

        if isinstance(proc, psutil.Process) and os.path.isdir("/proc"):
            try:
                with open(f"/proc/{pid}/stat", "r") as f:
                    parts = f.read().split()
                clk_tck = os.sysconf("SC_CLK_TCK")
                return (float(parts[13]) + float(parts[14])) / float(clk_tck)
            except Exception:
                pass
        try:
            return sum(proc.cpu_times())
        except (psutil.NoSuchProcess, ProcessLookupError):
            raise
        except AttributeError:
            raise psutil.NoSuchProcess(pid)
        except Exception:
            return 0.0

    def _system_time(self) -> float:
        """Return cumulative system CPU time."""
        if os.path.isdir("/proc"):
            try:
                with open("/proc/stat", "r") as f:
                    parts = f.readline().split()[1:]
                return sum(float(p) for p in parts)
            except Exception:
                pass
        return sum(psutil.cpu_times())

    def _scan_proc_stat(self, pids: set[int]) -> dict[int, float]:
        """Return CPU times for *pids* by reading ``/proc/<pid>/stat``.

        Uses the internal executor to parallelize reading when many
        processes are sampled.
        """

        results: dict[int, float] = {}
        if not pids or not os.path.isdir("/proc"):
            return results
        clk_tck = os.sysconf("SC_CLK_TCK")

        def read(pid: int) -> tuple[int, float] | None:
            try:
                with open(f"/proc/{pid}/stat", "r") as f:
                    parts = f.read().split()
                return pid, (float(parts[13]) + float(parts[14])) / float(clk_tck)
            except Exception:
                return None

        chunk = max(len(pids) // self.bulk_cpu_workers, 1)
        for item in self._executor.map(read, pids, chunksize=chunk):
            if item is not None:
                pid, val = item
                results[pid] = val
        return results

    def _next_batch(self, attrs: list[str]) -> tuple[list[psutil.Process], bool]:
        """Return the next batch of processes and whether a full cycle ended."""
        if self._proc_iter is None:
            self._proc_pids = psutil.pids()
            self.process_count = len(self._proc_pids)
            self._new_pids = set(self._proc_pids)
            self._proc_iter = psutil.process_iter(attrs=attrs)
            self._processed_batches = 0
            self._total_batches = max(1, math.ceil(self.process_count / self.batch_size))
        procs: list[psutil.Process] = []
        cycle_end = False
        try:
            for _ in range(self.batch_size):
                proc = next(self._proc_iter)
                procs.append(proc)
        except StopIteration:
            self._proc_iter = None
            cycle_end = True
        return procs, cycle_end

    def _maybe_sample_cpu(
        self,
        proc: psutil.Process,
        prev: ProcessEntry | None,
        ts: float,
        mem: float,
        read_bytes: int,
        write_bytes: int,
        bulk: dict[int, float] | None = None,
    ) -> tuple[float, float, float]:
        """Return ``(cpu_time, cpu, io_rate)`` with idle skip logic."""

        pid = proc.pid
        skip = self._should_skip_cpu(pid, proc, prev, ts, bulk)

        if skip:
            self._cpu_skip_counts[pid] = self._cpu_skip_counts.get(pid, 0) + 1
            cpu_time = (
                prev.cpu_time if prev else self._proc_cpu_time(pid, proc, bulk)
            )
            cpu = prev.cpu if prev else 0.0
            io_rate = prev.io_rate if prev else 0.0
            if prev is not None:
                self._record_idle_sample(pid, prev.cpu, prev.mem, prev.io_rate)
            return cpu_time, cpu, io_rate

        cpu_time = self._proc_cpu_time(pid, proc, bulk)
        prev_ts = self._cpu_ts.get(pid, ts)
        delta = max(ts - prev_ts, 0.001)
        self._cpu_ts[pid] = ts
        if prev is not None:
            cpu = (cpu_time - prev.cpu_time) / self._system_time_delta * 100
            io_rate = (
                (read_bytes - prev.read_bytes + write_bytes - prev.write_bytes)
                / delta
                / (1024 * 1024)
            )
            self._cpu_skip_counts[pid] = 0
            self._update_idle_state(pid, cpu, mem, io_rate)
        else:
            cpu = 0.0
            io_rate = 0.0
            self._idle_counts.pop(pid, None)
            self._cpu_skip_intervals.pop(pid, None)
            self._cpu_skip_counts.pop(pid, None)
            self._idle_baseline[pid] = self._global_idle_baseline
            self._idle_mem_baseline[pid] = self._global_mem_baseline
            self._idle_io_baseline[pid] = self._global_io_baseline
            self._global_mem_baseline = (
                self._global_mem_baseline * (1 - self.idle_mem_global_alpha)
                + mem * self.idle_mem_global_alpha
            )
            self._global_io_baseline = (
                self._global_io_baseline * (1 - self.idle_io_global_alpha)
                + io_rate * self.idle_io_global_alpha
            )
            self._global_mem_history.add(mem)
            self._global_io_history.add(io_rate)
            self._idle_mem_history[pid] = MovingAverage(self.idle_window)
            self._idle_io_history[pid] = MovingAverage(self.idle_window)
            ma = MovingAverage(self.idle_window)
            ma.add(0.0)
            self._idle_history[pid] = ma
            self._idle_state[pid] = False
        return cpu_time, cpu, io_rate

    def set_interval(self, interval: float) -> None:
        self.target_interval = max(self.min_interval, float(interval))
        self.interval = self.target_interval
        self._clamp_interval()

    def set_detail_interval(self, interval: int) -> None:
        self.target_detail_interval = max(1, int(interval))
        self.detail_interval = self.target_detail_interval

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def run(self) -> None:
        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            new_sys = self._system_time()
            self._system_time_delta = max(new_sys - self._prev_system_time, 0.001)
            self._prev_system_time = new_sys
            self._prune_caches(loop_start)
            if (
                self.process_count > self.conn_global_threshold * 2
                and self._global_conn_future is None
                and (
                    not self._global_conn_data
                    or loop_start - self._global_conn_ts > self.conn_interval
                )
            ):
                self._global_conn_future = self._executor.submit(
                    psutil.net_connections, kind="inet"
                )
            if (
                self.process_count > self.file_global_threshold * 2
                and os.path.isdir("/proc")
                and self._global_file_future is None
                and (
                    not self._global_file_data
                    or loop_start - self._global_file_ts > self.file_interval
                )
            ):
                self._global_file_future = self._executor.submit(
                    self._scan_fd_proc_all
                )
            if self._pause_event.is_set():
                if self._stop_event.wait(self.interval):
                    break
                continue

            if self._should_pause_for_load():
                if self._stop_event.wait(self.interval):
                    break
                continue

            now = time.monotonic()
            self._last_ts = now
            updates: dict[int, ProcessEntry] = {}
            trending = 0

            # Avoid fetching CPU times for all processes up front so idle
            # processes incur less overhead. CPU usage is collected on demand
            # after determining whether we should sample the process this cycle.
            basic_attrs = [
                "pid",
                "name",
                "username",
                "create_time",
                "memory_info",
                "status",
                "num_threads",
            ]
            if hasattr(psutil.Process(), "io_counters"):
                basic_attrs.append("io_counters")

            proc_data: dict[int, tuple[
                psutil.Process,
                ProcessEntry | None,
                float,
                int,
                int,
                str,
                str,
                float,
                str,
                int,
            ]] = {}
            sample_pids: set[int] = set()

            procs, cycle_end = self._next_batch(basic_attrs)
            self._processed_batches += 1
            for proc in procs:
                try:
                    with proc.oneshot():
                        pid = proc.info["pid"]
                        name = proc.info.get("name", "")
                        user = proc.info.get("username") or ""
                        if self.hide_system and user.lower() in {"root", "system", "localsystem"}:
                            continue
                        if user.lower() in self.exclude_users:
                            continue
                        if self._should_ignore_process(name):
                            continue
                        mem = proc.info["memory_info"].rss / (1024 * 1024)
                        start = proc.info.get("create_time", 0.0)
                        if self.ignore_age and time.time() - start < self.ignore_age:
                            continue
                        status = proc.info.get("status", "")
                        threads = proc.info.get("num_threads", 0)
                        io = proc.info.get("io_counters")
                        if io:
                            read_bytes = io.read_bytes
                            write_bytes = io.write_bytes
                        else:
                            read_bytes = write_bytes = 0
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    continue

                prev = self._snapshot.get(pid)
                if not self._should_skip_cpu(pid, proc, prev, now):
                    sample_pids.add(pid)
                proc_data[pid] = (
                    proc,
                    prev,
                    mem,
                    read_bytes,
                    write_bytes,
                    name,
                    user,
                    start,
                    status,
                    threads,
                )

            cpu_map: dict[int, float] = {}
            if len(sample_pids) >= self.bulk_cpu_threshold:
                cpu_map = self._scan_proc_stat(sample_pids)

            def collect(
                data: tuple[
                    psutil.Process,
                    ProcessEntry | None,
                    float,
                    int,
                    int,
                    str,
                    str,
                    float,
                    str,
                    int,
                ]
            ) -> tuple[ProcessEntry, bool, bool] | None:
                """Return updated entry, change flag and per-entry trending flag."""
                (
                    proc,
                    prev,
                    mem,
                    read_bytes,
                    write_bytes,
                    name,
                    user,
                    start,
                    status,
                    threads,
                ) = data
                pid = proc.pid
                trending_flag = False
                try:
                    cpu_time, cpu, io_rate = self._maybe_sample_cpu(
                        proc,
                        prev,
                        now,
                        mem,
                        read_bytes,
                        write_bytes,
                        cpu_map,
                    )
                except (psutil.Error, ProcessLookupError, AttributeError):
                    return None

                if prev is not None and cpu_time == prev.cpu_time and cpu == prev.cpu:
                    changed = prev.changed_basic(
                        ProcessEntry(
                            pid=pid,
                            name=name,
                            cpu=prev.cpu,
                            mem=round(mem, 1),
                            user=user,
                            start=start,
                            status=status,
                            cpu_time=prev.cpu_time,
                            threads=threads,
                            read_bytes=read_bytes,
                            write_bytes=write_bytes,
                            files=prev.files,
                            conns=prev.conns,
                            io_rate=prev.io_rate,
                            samples=list(prev.samples),
                            io_samples=list(prev.io_samples),
                            max_samples=self.sample_size,
                        )
                    )
                    delta_mem = round(mem - prev.mem, 1)
                    prev.mem = round(mem, 1)
                    prev.user = user
                    prev.start = start
                    prev.status = status
                    prev.cpu_time = cpu_time
                    prev.threads = threads
                    prev.read_bytes = read_bytes
                    prev.write_bytes = write_bytes
                    prev.delta_cpu = 0.0
                    prev.delta_mem = delta_mem
                    prev.delta_io = 0.0
                    prev.changed = changed
                    prev.add_sample(prev.cpu, prev.io_rate, prev.mem)
                    prev.compute_trends(
                        self._trend_window,
                        self._trend_window,
                        self._trend_io_window,
                        self._trend_cpu,
                        self._trend_mem,
                        self._trend_io,
                    )
                    prev.update_level(
                        self.warn_cpu,
                        self.warn_mem,
                        self.warn_io,
                        self.cpu_alert,
                        self.mem_alert,
                    )
                    return prev, changed, trending_flag

                if prev is not None:
                    self._cpu_skip_counts[pid] = 0
                    changed = prev.changed_basic(
                        ProcessEntry(
                            pid=pid,
                            name=name,
                            cpu=round(cpu, 1),
                            mem=round(mem, 1),
                            user=user,
                            start=start,
                            status=status,
                            cpu_time=cpu_time,
                            threads=threads,
                            read_bytes=read_bytes,
                            write_bytes=write_bytes,
                            files=prev.files,
                            conns=prev.conns,
                            io_rate=round(io_rate, 1),
                            samples=list(prev.samples),
                            io_samples=list(prev.io_samples),
                            max_samples=self.sample_size,
                        )
                    )
                    delta_cpu = round(cpu - prev.cpu, 1)
                    delta_mem = round(mem - prev.mem, 1)
                    delta_io = round(io_rate - prev.io_rate, 1)
                    prev.cpu = round(cpu, 1)
                    prev.mem = round(mem, 1)
                    prev.user = user
                    prev.start = start
                    prev.status = status
                    prev.cpu_time = cpu_time
                    prev.threads = threads
                    prev.read_bytes = read_bytes
                    prev.write_bytes = write_bytes
                    prev.io_rate = round(io_rate, 1)
                    prev.delta_cpu = delta_cpu
                    prev.delta_mem = delta_mem
                    prev.delta_io = delta_io
                    prev.changed = changed
                    prev.add_sample(prev.cpu, prev.io_rate, prev.mem)
                    prev.compute_trends(
                        self._trend_window,
                        self._trend_window,
                        self._trend_io_window,
                        self._trend_cpu,
                        self._trend_mem,
                        self._trend_io,
                    )
                    prev.update_level(
                        self.warn_cpu,
                        self.warn_mem,
                        self.warn_io,
                        self.cpu_alert,
                        self.mem_alert,
                    )
                    if (
                        prev.trending_cpu
                        or prev.trending_mem
                        or prev.trending_io
                    ):
                        trending_flag = True
                    return prev, changed, trending_flag

                entry = ProcessEntry(
                    pid=pid,
                    name=name,
                    cpu=0.0,
                    mem=round(mem, 1),
                    user=user,
                    start=start,
                    status=status,
                    cpu_time=cpu_time,
                    threads=threads,
                    read_bytes=read_bytes,
                    write_bytes=write_bytes,
                    files=0,
                    conns=0,
                    io_rate=0.0,
                    samples=[],
                    io_samples=[],
                    max_samples=self.sample_size,
                )
                entry.add_sample(entry.cpu, entry.io_rate, entry.mem)
                entry.compute_trends(
                    self._trend_window,
                    self._trend_window,
                    self._trend_io_window,
                    self._trend_cpu,
                    self._trend_mem,
                    self._trend_io,
                )
                entry.update_level(
                    self.warn_cpu,
                    self.warn_mem,
                    self.warn_io,
                    self.cpu_alert,
                    self.mem_alert,
                )
                if entry.trending_cpu or entry.trending_mem or entry.trending_io:
                    trending_flag = True
                entry.changed = True
                self._normal_counts[pid] = 0
                return entry, True, trending_flag

            heap: list[tuple[tuple[float, float, int], ProcessEntry]] = []
            entries: list[ProcessEntry] = []
            detail_candidates: list[ProcessEntry] = []
            now_ts = time.monotonic()

            for result in self._executor.map(collect, proc_data.values()):
                if not result:
                    continue
                entry, changed_flag, trending_flag = result
                if trending_flag:
                    trending += 1
                if self.limit:
                    score = (entry.avg_cpu, entry.mem, entry.pid)
                    item = (score, entry, changed_flag)
                    if len(heap) < self.limit:
                        heapq.heappush(heap, item)
                    else:
                        heapq.heappushpop(heap, item)
                else:
                    entries.append((entry, changed_flag))

            if self.visible_auto:
                cpu_vals = [e.cpu for e, _c in entries]
                mem_vals = [e.mem for e, _c in entries]
                io_vals = [e.io_rate for e, _c in entries]
                self._update_auto_baselines(cpu_vals, mem_vals, io_vals)

            if self.limit:
                entries = [
                    (e, ch) for _s, e, ch in heapq.nlargest(self.limit, heap)
                ]

            for entry, changed in entries:
                if changed:
                    updates[entry.pid] = entry
                    self._stable_counts[entry.pid] = 0
                else:
                    self._stable_counts[entry.pid] = self._stable_counts.get(entry.pid, 0) + 1
                entry.stable = self._stable_counts.get(entry.pid, 0) >= self._stable_cycles
                skip_stable = (
                    self._stable_counts.get(entry.pid, 0) >= self._stable_cycles
                    and self._stable_counts[entry.pid] % self._stable_skip != 0
                )
                cpu_thresh = self._auto_cpu if self.visible_auto else self.visible_cpu
                mem_thresh = self._auto_mem if self.visible_auto else self.visible_mem
                io_thresh = self._auto_io if self.visible_auto else self.visible_io
                if (
                    not changed
                    and not (entry.trending_cpu or entry.trending_mem or entry.trending_io)
                    and entry.cpu < cpu_thresh
                    and entry.mem < mem_thresh
                    and entry.io_rate < io_thresh
                    and not entry.stable
                ):
                    self._normal_counts[entry.pid] = self._normal_counts.get(entry.pid, 0) + 1
                else:
                    self._normal_counts[entry.pid] = 0
                entry.normal = self._normal_counts[entry.pid] >= self._normal_window
                if (
                    changed
                    or now_ts - self._detail_ts.get(entry.pid, 0.0) >= self.detail_interval
                ) and not skip_stable:
                    detail_candidates.append(entry)
                self._snapshot[entry.pid] = entry
            if not self.limit:
                entries.sort(key=lambda ec: (ec[0].cpu, ec[0].mem), reverse=True)

            if detail_candidates:
                now_conn = time.monotonic()
                now_file = now_conn
                cand_pids = {e.pid for e in detail_candidates}
                fetch = [
                    p
                    for p in cand_pids
                    if now_conn - self._conn_cache.get(p, (0, 0))[1]
                    >= self.conn_interval
                ]
                file_fetch = [
                    p
                    for p in cand_pids
                    if now_file - self._file_cache.get(p, (0, 0))[1]
                    >= self.file_interval
                ]
                conn_counts: dict[int, int] = {}
                if fetch:
                    if len(fetch) > self.conn_global_threshold:
                        if self._global_conn_future and self._global_conn_future.done():
                            all_conns = self._global_conn_future.result()
                            self._global_conn_future = None
                            counts: dict[int, int] = {}
                            for conn in all_conns:
                                pid = conn.pid
                                if pid is None:
                                    continue
                                counts[pid] = counts.get(pid, 0) + 1
                            self._global_conn_data = counts
                            self._global_conn_ts = now_conn
                            for pid, cnt in counts.items():
                                self._conn_cache[pid] = (cnt, now_conn)
                            conn_counts = {pid: counts.get(pid, 0) for pid in cand_pids}
                        elif self._global_conn_data:
                            for pid in fetch:
                                if pid in self._global_conn_data:
                                    conn_counts[pid] = self._global_conn_data[pid]
                    else:
                        def _get_conn(pid: int) -> tuple[int, int] | None:
                            try:
                                proc = psutil.Process(pid)
                                if hasattr(proc, "net_connections"):
                                    conns = proc.net_connections(kind="inet")
                                else:  # pragma: no cover - psutil<6
                                    conns = proc.connections(kind="inet")
                                return pid, len(conns)
                            except Exception:
                                return None

                        for res in self._executor.map(_get_conn, fetch):
                            if not res:
                                continue
                            pid, cnt = res
                            conn_counts[pid] = cnt
                            self._conn_cache[pid] = (cnt, now_conn)
                for pid in cand_pids:
                    if pid not in conn_counts and pid in self._conn_cache:
                        conn_counts[pid] = self._conn_cache[pid][0]

                file_counts: dict[int, int] = {}

                def _get_file_count(pid: int) -> tuple[int, int] | None:
                    try:
                        proc_path = f"/proc/{pid}/fd"
                        if os.path.isdir(proc_path):
                            return pid, sum(1 for _ in os.scandir(proc_path))
                        proc = psutil.Process(pid)
                        with proc.oneshot():
                            if hasattr(proc, "num_handles"):
                                return pid, proc.num_handles()
                            if hasattr(proc, "num_fds"):
                                return pid, proc.num_fds()
                            return pid, len(proc.open_files())
                    except Exception:
                        return None

                if file_fetch:
                    if (
                        len(file_fetch) > self.file_global_threshold
                        and os.path.isdir("/proc")
                    ):
                        if self._global_file_future and self._global_file_future.done():
                            self._global_file_data = self._global_file_future.result()
                            self._global_file_ts = now_file
                            self._global_file_future = None
                        if self._global_file_data:
                            for pid in file_fetch:
                                if pid in self._global_file_data:
                                    file_counts[pid] = self._global_file_data[pid]
                        else:
                            if self._file_future is None:
                                self._file_future = self._executor.submit(
                                    self._scan_fd_proc, set(file_fetch)
                                )
                            if self._file_future and self._file_future.done():
                                all_counts = self._file_future.result()
                                self._file_future = None
                                file_counts.update(all_counts)
                    else:
                        for res in self._executor.map(_get_file_count, file_fetch):
                            if not res:
                                continue
                            pid, count = res
                            file_counts[pid] = count
                    for pid in file_fetch:
                        self._file_cache[pid] = (
                            file_counts.get(pid, self._file_cache.get(pid, (0, 0))[0]),
                            now_file,
                        )
                for pid in cand_pids:
                    if pid not in file_counts and pid in self._file_cache:
                        file_counts[pid] = self._file_cache[pid][0]

                def gather_detail(entry: ProcessEntry) -> ProcessEntry:
                    try:
                        entry.files = file_counts.get(entry.pid, entry.files)
                    except Exception:
                        pass
                    entry.conns = conn_counts.get(entry.pid, entry.conns)
                    return entry
                detail_start = time.monotonic()
                for det in self._executor.map(gather_detail, detail_candidates):
                    updates[det.pid] = det
                    self._snapshot[det.pid] = det
                    self._detail_ts[det.pid] = time.monotonic()
                detail_elapsed = time.monotonic() - detail_start
                if self.adaptive_detail:
                    if detail_elapsed > self.target_interval / 3:
                        self.detail_interval = min(
                            self.detail_interval + 1,
                            self.target_detail_interval * 5,
                        )
                    elif (
                        detail_elapsed < self.target_interval / 10
                        and self.detail_interval > self.target_detail_interval
                    ):
                        self.detail_interval = max(
                            self.detail_interval - 1,
                            self.target_detail_interval,
                        )
                self._last_detail_count = len(detail_candidates)

            else:
                self._last_detail_count = 0

            removed = set()
            if cycle_end:
                removed = set(self._snapshot) - self._new_pids
                self._new_pids.clear()

            progress = self._processed_batches / self._total_batches

            if updates or removed:
                try:
                    self.queue.put_nowait((updates, removed, progress))
                except Full:
                    try:
                        self.queue.get_nowait()
                    except Empty:
                        pass
                    self.queue.put_nowait((updates, removed, progress))
                for pid in removed:
                    self._snapshot.pop(pid, None)
                    self._detail_ts.pop(pid, None)
                    self._conn_cache.pop(pid, None)
                    self._file_cache.pop(pid, None)
                    self._stable_counts.pop(pid, None)
                    self._normal_counts.pop(pid, None)
                    self._reset_idle_state(pid)

            elapsed = time.monotonic() - loop_start
            self._cycle_elapsed += elapsed
            self._cycle_updates += len(updates)
            self._cycle_trending += trending

            if cycle_end and self.adaptive:
                if self._cycle_elapsed > self.target_interval * 1.5:
                    self.interval = min(self.interval * 1.25, self.target_interval * 5)
                elif self._cycle_elapsed < self.target_interval * 0.7 and self.interval > self.target_interval:
                    self.interval = max(self.interval * 0.9, self.target_interval)
                change_ratio = self._cycle_updates / max(self.process_count, 1)
                self._ratio_history.append(change_ratio)
                avg_ratio = sum(self._ratio_history) / len(self._ratio_history)
                self._trend_history.append(self._cycle_trending / max(self.process_count, 1))
                avg_trend = sum(self._trend_history) / len(self._trend_history)
                if avg_ratio < self._slow_ratio and avg_trend < self._trend_slow_ratio:
                    self.interval = min(self.interval + 0.5, self.target_interval * 5)
                    self._stable_cycles = min(self._stable_cycles + 1, 20)
                elif avg_ratio > self._fast_ratio or avg_trend > self._trend_fast_ratio:
                    self.interval = max(self.interval - 0.5, self.target_interval)
                    self._stable_cycles = max(self._stable_cycles - 1, 1)
                self._clamp_interval()
                self._finish_cycle()

            if self._stop_event.wait(self.interval):
                break

    def stop(self) -> None:
        self._stop_event.set()
        self._executor.shutdown(wait=False)

    def _prune_caches(self, now: float) -> None:
        """Drop stale connection and file count cache entries."""
        stale = [pid for pid, (_, ts) in self._conn_cache.items() if now - ts > self.cache_ttl]
        for pid in stale:
            self._conn_cache.pop(pid, None)
        stale = [pid for pid, (_, ts) in self._file_cache.items() if now - ts > self.cache_ttl]
        for pid in stale:
            self._file_cache.pop(pid, None)
        if now - self._global_conn_ts > self.cache_ttl:
            self._global_conn_data.clear()
        if now - self._global_file_ts > self.cache_ttl:
            self._global_file_data.clear()

    def _update_batch_size(self) -> None:
        """Dynamically adjust ``batch_size`` using cycle time and activity."""
        if not self.auto_batch:
            return
        change_ratio = self._cycle_updates / max(self.process_count, 1)
        trend_ratio = self._cycle_trending / max(self.process_count, 1)
        avg_time = (
            sum(self._cycle_time_history) / len(self._cycle_time_history)
            if self._cycle_time_history
            else self._cycle_elapsed
        )
        if (
            avg_time > self.target_interval * 1.5
            or change_ratio > 0.5
            or trend_ratio > 0.4
        ) and self.batch_size > self.min_batch_size:
            self.batch_size = max(self.min_batch_size, int(self.batch_size * 0.8))
        elif (
            avg_time < self.target_interval * 0.75
            and change_ratio < 0.2
            and trend_ratio < 0.2
            and self.batch_size < self.max_batch_size
        ):
            self.batch_size = min(self.max_batch_size, int(self.batch_size * 1.2))
        self._batch_history.append(self.batch_size)

    def _clamp_interval(self) -> None:
        """Ensure ``interval`` stays within configured bounds."""
        self.interval = max(self.min_interval, min(self.max_interval, self.interval))

    def _resize_executor(self, workers: int) -> None:
        """Replace thread pool with *workers* threads."""
        if workers == self._executor._max_workers:
            return
        self._executor.shutdown(wait=False)
        self._executor = ThreadPoolExecutor(max_workers=workers)

    def _maybe_resize_executor(self) -> None:
        """Adjust thread pool size based on ``process_count``."""
        cur = self._executor._max_workers
        if self.process_count > cur * 4 and cur < self.max_workers:
            self._resize_executor(min(self.max_workers, cur * 2))
        elif self.process_count < cur * 2 and cur > self.min_workers:
            self._resize_executor(max(self.min_workers, cur // 2))

    def _finish_cycle(self) -> None:
        """Finalize metrics and reset per-cycle counters."""
        self._last_change_ratio = self._cycle_updates / max(self.process_count, 1)
        self._last_trend_ratio = self._cycle_trending / max(self.process_count, 1)
        self._cycle_time_history.append(self._cycle_elapsed)
        self._interval_history.append(self.interval)
        if self._cycle_elapsed:
            self._throughput_history.append(
                self.process_count / self._cycle_elapsed
            )
        self._clamp_interval()
        self._update_batch_size()
        self._maybe_resize_executor()
        self._cycle_elapsed = 0.0
        self._cycle_updates = 0
        self._cycle_trending = 0

    @property
    def recent_change_ratio(self) -> float:
        """Return the ratio of changed processes in the last cycle."""
        return self._last_change_ratio

    @property
    def recent_trend_ratio(self) -> float:
        """Return the ratio of trending processes in the last cycle."""
        return self._last_trend_ratio

    @property
    def average_batch_size(self) -> float:
        """Return the average batch size over recent cycles."""
        if self._batch_history:
            return sum(self._batch_history) / len(self._batch_history)
        return float(self.batch_size)

    @property
    def average_cycle_time(self) -> float:
        """Return the average cycle duration in seconds."""
        if self._cycle_time_history:
            return sum(self._cycle_time_history) / len(self._cycle_time_history)
        return self.target_interval

    @property
    def average_interval(self) -> float:
        """Return the average refresh interval in seconds."""
        if self._interval_history:
            return sum(self._interval_history) / len(self._interval_history)
        return self.interval

    @property
    def average_throughput(self) -> float:
        """Return average processes scanned per second."""
        if self._throughput_history:
            return sum(self._throughput_history) / len(self._throughput_history)
        if self._cycle_elapsed:
            return self.process_count / self._cycle_elapsed
        return 0.0

    @property
    def worker_count(self) -> int:
        """Return current thread pool size."""
        return self._executor._max_workers

    def _update_auto_baselines(
        self, cpu_vals: list[float], mem_vals: list[float], io_vals: list[float]
    ) -> None:
        def percentile(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            k = max(0, min(len(values) - 1, int(len(values) * p) - 1))
            return sorted(values)[k]

        alpha = 0.3
        cpu = percentile(cpu_vals, 0.75)
        mem = percentile(mem_vals, 0.75)
        io = percentile(io_vals, 0.75)
        self._auto_cpu = cpu if self._auto_cpu == 0.0 else self._auto_cpu * (1 - alpha) + cpu * alpha
        self._auto_mem = mem if self._auto_mem == 0.0 else self._auto_mem * (1 - alpha) + mem * alpha
        self._auto_io = io if self._auto_io == 0.0 else self._auto_io * (1 - alpha) + io * alpha

    def _scan_fd_proc(self, pids: set[int]) -> dict[int, int]:
        """Return open file counts for *pids* by scanning /proc."""
        counts: dict[int, int] = {}
        proc_root = Path("/proc")
        for entry in os.scandir(proc_root):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid not in pids:
                continue
            fd_path = os.path.join(entry.path, "fd")
            if os.path.isdir(fd_path):
                try:
                    counts[pid] = sum(1 for _ in os.scandir(fd_path))
                except Exception:
                    continue
            if len(counts) == len(pids):
                break
        return counts

    def _scan_fd_proc_all(self) -> dict[int, int]:
        """Return open file counts for all processes by scanning /proc."""
        counts: dict[int, int] = {}
        proc_root = Path("/proc")
        for entry in os.scandir(proc_root):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            fd_path = os.path.join(entry.path, "fd")
            if os.path.isdir(fd_path):
                try:
                    counts[pid] = sum(1 for _ in os.scandir(fd_path))
                except Exception:
                    continue
        return counts


__all__ = [
    "ProcessEntry",
    "ProcessWatcher",
    "MovingAverage",
]

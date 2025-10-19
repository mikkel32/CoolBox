"""SLO instrumentation helpers used during application startup."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict

from coolbox.catalog import get_catalog


class SLOTracker:
    """Collects SLO metrics for a single CoolBox runtime session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._run_id: str | None = None
        self._profile: str | None = None
        self._start_time: float | None = None
        self._ttff_recorded = False
        self._spawn_recorded: set[str] = set()
        self._tool_latencies: dict[str, list[float]] = defaultdict(list)

    # ------------------------------------------------------------------
    def start_run(self, *, profile: str | None = None) -> str:
        with self._lock:
            self._run_id = uuid.uuid4().hex
            self._profile = profile
            self._start_time = time.perf_counter()
            self._ttff_recorded = False
            self._spawn_recorded.clear()
            self._tool_latencies.clear()
            return self._run_id

    def reset(self) -> None:
        with self._lock:
            self._run_id = None
            self._profile = None
            self._start_time = None
            self._ttff_recorded = False
            self._spawn_recorded.clear()
            self._tool_latencies.clear()

    # ------------------------------------------------------------------
    def record_profile(self, profile: str | None) -> None:
        with self._lock:
            self._profile = profile

    def record_ttff(self) -> None:
        with self._lock:
            if self._run_id is None or self._start_time is None or self._ttff_recorded:
                return
            delta = (time.perf_counter() - self._start_time) * 1000.0
            metadata = {"profile": self._profile} if self._profile else {}
            try:
                get_catalog().record_startup_metric(
                    self._run_id,
                    "ttff_ms",
                    delta,
                    metadata=metadata,
                )
            except Exception:  # pragma: no cover - persistence best effort
                pass
            self._ttff_recorded = True

    def record_plugin_spawn(self, plugin_id: str) -> None:
        with self._lock:
            if self._run_id is None or self._start_time is None:
                return
            if plugin_id in self._spawn_recorded:
                return
            self._spawn_recorded.add(plugin_id)
            delta = (time.perf_counter() - self._start_time) * 1000.0
            metadata = {"profile": self._profile, "plugin_id": plugin_id}
            try:
                get_catalog().record_startup_metric(
                    self._run_id,
                    "plugin_cold_start_ms",
                    delta,
                    metadata=metadata,
                )
            except Exception:  # pragma: no cover - persistence best effort
                pass

    def record_tool_invocation(self, plugin_id: str, duration: float) -> None:
        with self._lock:
            if self._run_id is None:
                return
            samples = self._tool_latencies.setdefault(plugin_id, [])
            samples.append(duration * 1000.0)
            samples.sort()
            index = max(int(len(samples) * 0.95) - 1, 0)
            p95 = samples[index]
            metadata = {"profile": self._profile, "plugin_id": plugin_id}
            try:
                get_catalog().record_startup_metric(
                    self._run_id,
                    "tool_latency_p95_ms",
                    p95,
                    metadata=metadata,
                )
            except Exception:  # pragma: no cover - persistence best effort
                pass

    def current_run(self) -> str | None:
        with self._lock:
            return self._run_id


_TRACKER = SLOTracker()


def get_slo_tracker() -> SLOTracker:
    return _TRACKER


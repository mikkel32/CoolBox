"""Process supervisor and resource budget enforcement for plugin workers."""

from __future__ import annotations

import json
import logging
import platform
import re
import traceback
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Sequence
import math
import threading

try:  # pragma: no cover - optional dependency on Unix only
    import resource
except Exception:  # pragma: no cover - compatibility shim
    resource = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency for process inspection
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore[assignment]

from coolbox.catalog import get_catalog
from coolbox.telemetry.slo import get_slo_tracker
from coolbox.paths import artifacts_dir, ensure_directory

from coolbox.telemetry.tracing import (
    SpanKind,
    Status,
    StatusCode,
    current_carrier,
    extract_context,
    set_status,
    start_span,
    trace_id_hex,
)

from coolbox.utils.security.permissions import get_permission_manager

from .manifest import PluginDefinition, ResourceBudget
from .runtime.environment import RuntimeActivation, apply_runtime_activation
from .runtime.toold_client import TooldProcess, TooldProcessError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from coolbox.telemetry.client import NullTelemetryClient, TelemetryClient


class PluginWorkerError(RuntimeError):
    """Base class for worker supervision errors."""

    def __init__(self, plugin_id: str, message: str) -> None:
        super().__init__(message)
        self.plugin_id = plugin_id


class PluginSandboxError(PluginWorkerError):
    """Raised when sandbox application fails."""


class PluginRuntimeError(PluginWorkerError):
    """Raised when plugin execution raises unexpectedly."""

    def __init__(self, plugin_id: str, message: str, *, original: Exception | None = None) -> None:
        super().__init__(plugin_id, message)
        self.original = original


class PluginStartupError(PluginWorkerError):
    """Raised when a plugin crash should abort startup."""

    def __init__(
        self,
        plugin_id: str,
        message: str,
        *,
        diagnostics: "WorkerDiagnostics | None" = None,
        original: Exception | None = None,
    ) -> None:
        super().__init__(plugin_id, message)
        self.diagnostics = diagnostics
        self.original = original


@dataclass(slots=True)
class BudgetLimits:
    """Resource limits derived from the manifest budget."""

    cpu_percent: float | None = None
    memory_bytes: int | None = None
    wall_time: float | None = None

    @classmethod
    def from_budget(cls, budget: ResourceBudget | None) -> "BudgetLimits":
        if budget is None:
            return cls()
        return cls(
            cpu_percent=_parse_cpu_percent(budget.cpu),
            memory_bytes=_parse_memory_spec(budget.memory),
            wall_time=float(budget.timeout) if budget.timeout is not None else None,
        )

    def is_enforced(self) -> bool:
        return any(value is not None for value in (self.cpu_percent, self.memory_bytes, self.wall_time))


def budget_limits_to_payload(limits: BudgetLimits) -> dict[str, float | int | None]:
    """Serialize :class:`BudgetLimits` to a JSON compatible payload."""

    return {
        "cpu_percent": limits.cpu_percent,
        "memory_bytes": limits.memory_bytes,
        "wall_time": limits.wall_time,
    }


def _coerce_optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _coerce_float(value: object, default: float = 0.0) -> float:
    coerced = _coerce_optional_float(value)
    return coerced if coerced is not None else default


def budget_limits_from_payload(payload: Mapping[str, object] | None) -> BudgetLimits:
    """Deserialize :class:`BudgetLimits` from :func:`budget_limits_to_payload`."""

    if not payload:
        return BudgetLimits()
    cpu_percent = payload.get("cpu_percent")
    memory_bytes = payload.get("memory_bytes")
    wall_time = payload.get("wall_time")
    return BudgetLimits(
        cpu_percent=_coerce_optional_float(cpu_percent),
        memory_bytes=_coerce_optional_int(memory_bytes),
        wall_time=_coerce_optional_float(wall_time),
    )


def _resolve_runtime_entrypoint(definition: PluginDefinition | None) -> str | None:
    if definition is None:
        return None
    runtime = definition.runtime
    return runtime.entrypoint or runtime.handler or runtime.module


@dataclass(slots=True)
class WorkerDiagnostics:
    """Structured diagnostics captured when a worker misbehaves."""

    plugin_id: str
    wall_time: float
    cpu_time: float
    memory_usage: int | None
    limits: BudgetLimits
    breaches: Mapping[str, tuple[float | int | None, float | int | None]]
    mini_dump: Path | None = None
    telemetry_payload: dict[str, object] = field(default_factory=dict)


def diagnostics_to_payload(diagnostics: WorkerDiagnostics) -> dict[str, object]:
    """Serialize diagnostics for transport across process boundaries."""

    payload: dict[str, object] = {
        "plugin_id": diagnostics.plugin_id,
        "wall_time": diagnostics.wall_time,
        "cpu_time": diagnostics.cpu_time,
        "memory_usage": diagnostics.memory_usage,
        "limits": budget_limits_to_payload(diagnostics.limits),
        "breaches": {
            key: (actual, limit)
            for key, (actual, limit) in diagnostics.breaches.items()
        },
        "telemetry_payload": dict(diagnostics.telemetry_payload),
    }
    if diagnostics.mini_dump is not None:
        payload["mini_dump"] = str(diagnostics.mini_dump)
    return payload


def diagnostics_from_payload(payload: Mapping[str, object]) -> WorkerDiagnostics:
    """Reconstruct diagnostics produced by :func:`diagnostics_to_payload`."""

    limits_payload = payload.get("limits")
    limits = budget_limits_from_payload(limits_payload if isinstance(limits_payload, Mapping) else None)
    breaches_raw = payload.get("breaches")
    breaches: dict[str, tuple[float | int | None, float | int | None]] = {}
    if isinstance(breaches_raw, Mapping):
        for key, value in breaches_raw.items():
            if isinstance(value, (list, tuple)) and len(value) == 2:
                breaches[str(key)] = (value[0], value[1])
    telemetry_payload = payload.get("telemetry_payload")
    if isinstance(telemetry_payload, Mapping):
        telemetry = dict(telemetry_payload)
    else:
        telemetry = {}
    mini_dump_raw = payload.get("mini_dump")
    mini_dump = Path(mini_dump_raw) if isinstance(mini_dump_raw, str) else None
    return WorkerDiagnostics(
        plugin_id=str(payload.get("plugin_id", "")),
        wall_time=_coerce_float(payload.get("wall_time"), 0.0),
        cpu_time=_coerce_float(payload.get("cpu_time"), 0.0),
        memory_usage=_coerce_optional_int(payload.get("memory_usage")),
        limits=limits,
        breaches=breaches,
        mini_dump=mini_dump,
        telemetry_payload=telemetry,
    )


@dataclass(slots=True)
class WorkerRuntimeSnapshot:
    """Runtime metadata for a worker process."""

    pid: int | None
    status: str | None
    open_ports: tuple[str, ...]
    process_tree: tuple[str, ...]


@dataclass(slots=True)
class PluginTraceRecord:
    """Record describing an individual plugin invocation."""

    trace_id: str | None
    method: str
    status: str
    duration: float
    timestamp: float
    error: str | None = None


@dataclass(slots=True)
class PluginMetricsSnapshot:
    """Aggregated runtime metrics for a single plugin."""

    plugin_id: str
    invocations: int
    errors: int
    error_rate: float
    latency_p50: float | None
    latency_p95: float | None
    latency_p99: float | None
    memory_high_water: int | None
    capability_denials: int
    recent_traces: tuple[PluginTraceRecord, ...]


class _PluginMetrics:
    __slots__ = (
        "latencies",
        "invocations",
        "errors",
        "memory_high_water",
        "capability_denials",
        "traces",
    )

    def __init__(self, max_samples: int, max_traces: int) -> None:
        self.latencies: deque[float] = deque(maxlen=max_samples)
        self.invocations = 0
        self.errors = 0
        self.memory_high_water: int | None = None
        self.capability_denials = 0
        self.traces: deque[PluginTraceRecord] = deque(maxlen=max_traces)


class PluginMetricsRegistry:
    """Thread-safe registry collecting per-plugin performance metrics."""

    def __init__(self, *, max_samples: int = 256, max_traces: int = 25) -> None:
        self._max_samples = max_samples
        self._max_traces = max_traces
        self._lock = threading.RLock()
        self._metrics: dict[str, _PluginMetrics] = {}

    def _ensure(self, plugin_id: str) -> _PluginMetrics:
        metrics = self._metrics.get(plugin_id)
        if metrics is None:
            metrics = _PluginMetrics(self._max_samples, self._max_traces)
            self._metrics[plugin_id] = metrics
        return metrics

    def touch(self, plugin_id: str) -> None:
        with self._lock:
            self._ensure(plugin_id)

    def record_invocation(
        self,
        plugin_id: str,
        *,
        duration: float,
        trace_id: str | None,
        method: str,
        status: str,
        error: str | None = None,
    ) -> None:
        timestamp = time.time()
        with self._lock:
            metrics = self._ensure(plugin_id)
            metrics.invocations += 1
            metrics.latencies.append(duration)
            if status != "ok":
                metrics.errors += 1
            metrics.traces.append(
                PluginTraceRecord(
                    trace_id=trace_id,
                    method=method,
                    status=status,
                    duration=duration,
                    timestamp=timestamp,
                    error=error,
                )
            )
        try:
            get_catalog().record_plugin_trace(
                plugin_id,
                method=method,
                status=status,
                duration=duration,
                timestamp=timestamp,
                trace_id=trace_id,
                error=error,
            )
        except Exception:  # pragma: no cover - persistence best effort
            pass
        get_slo_tracker().record_tool_invocation(plugin_id, duration)

    def record_capability_denial(self, plugin_id: str, reason: str | None = None) -> None:
        with self._lock:
            metrics = self._ensure(plugin_id)
            metrics.capability_denials += 1
            metrics.traces.append(
                PluginTraceRecord(
                    trace_id=None,
                    method="sandbox",
                    status="capability_denied",
                    duration=0.0,
                    timestamp=time.time(),
                    error=reason,
                )
            )

    def observe_diagnostics(
        self, plugin_id: str, diagnostics: WorkerDiagnostics | None
    ) -> None:
        if diagnostics is None:
            return
        memory_value = diagnostics.memory_usage
        if memory_value is None:
            breach = diagnostics.breaches.get("memory_bytes")
            if breach and breach[0] is not None:
                try:
                    memory_value = int(float(breach[0]))
                except (TypeError, ValueError):
                    memory_value = None
        if memory_value is None:
            return
        with self._lock:
            metrics = self._ensure(plugin_id)
            if metrics.memory_high_water is None:
                metrics.memory_high_water = memory_value
            else:
                metrics.memory_high_water = max(metrics.memory_high_water, memory_value)

    def snapshot(self) -> dict[str, PluginMetricsSnapshot]:
        with self._lock:
            summary: dict[str, PluginMetricsSnapshot] = {}
            for plugin_id, metrics in self._metrics.items():
                latencies = sorted(metrics.latencies)
                summary[plugin_id] = PluginMetricsSnapshot(
                    plugin_id=plugin_id,
                    invocations=metrics.invocations,
                    errors=metrics.errors,
                    error_rate=self._compute_error_rate(metrics.invocations, metrics.errors),
                    latency_p50=self._percentile(latencies, 0.50),
                    latency_p95=self._percentile(latencies, 0.95),
                    latency_p99=self._percentile(latencies, 0.99),
                    memory_high_water=metrics.memory_high_water,
                    capability_denials=metrics.capability_denials,
                    recent_traces=tuple(metrics.traces),
                )
            return summary

    @staticmethod
    def _compute_error_rate(invocations: int, errors: int) -> float:
        if invocations <= 0:
            return 0.0
        return errors / invocations

    @staticmethod
    def _percentile(samples: Sequence[float], percentile: float) -> float | None:
        if not samples:
            return None
        if len(samples) == 1:
            return samples[0]
        k = (len(samples) - 1) * percentile
        lower = math.floor(k)
        upper = math.ceil(k)
        if lower == upper:
            return samples[int(k)]
        lower_value = samples[lower]
        upper_value = samples[upper]
        return lower_value + (upper_value - lower_value) * (k - lower)


_GLOBAL_PLUGIN_METRICS = PluginMetricsRegistry()


def get_global_plugin_metrics() -> PluginMetricsRegistry:
    """Return the global plugin metrics registry."""

    return _GLOBAL_PLUGIN_METRICS


class BudgetViolation(RuntimeError):
    """Raised when a worker exceeds its declared budget."""

    def __init__(self, diagnostics: WorkerDiagnostics) -> None:
        super().__init__("worker budget exceeded")
        self.diagnostics = diagnostics


class BudgetController:
    """Measure resource utilisation for plugin callbacks."""

    def __init__(
        self,
        plugin_id: str,
        limits: BudgetLimits,
        *,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.limits = limits
        self.logger = logger or logging.getLogger("coolbox.plugins.supervisor")
        self._clock = clock or time.perf_counter

    def run(self, func: Callable[..., object], *args, **kwargs):
        start_wall = self._clock()
        start_cpu = time.process_time()
        start_memory = _current_memory_usage()
        try:
            return func(*args, **kwargs)
        finally:
            wall_elapsed = self._clock() - start_wall
            cpu_elapsed = time.process_time() - start_cpu
            memory_usage = _current_memory_usage()
            breaches: dict[str, tuple[float | int | None, float | int | None]] = {}
            if self.limits.wall_time is not None and wall_elapsed > self.limits.wall_time:
                breaches["wall_time"] = (wall_elapsed, self.limits.wall_time)
            cpu_percent = None
            if wall_elapsed > 0:
                cpu_percent = (cpu_elapsed / wall_elapsed) * 100.0
            if self.limits.cpu_percent is not None and cpu_percent is not None:
                if cpu_percent > self.limits.cpu_percent:
                    breaches["cpu_percent"] = (cpu_percent, self.limits.cpu_percent)
            if self.limits.memory_bytes is not None and memory_usage is not None:
                baseline = start_memory or 0
                delta = max(memory_usage - baseline, 0)
                if delta > self.limits.memory_bytes:
                    breaches["memory_bytes"] = (delta, self.limits.memory_bytes)
            if breaches:
                diagnostics = self._build_diagnostics(
                    wall_elapsed,
                    cpu_elapsed,
                    memory_usage,
                    breaches,
                )
                raise BudgetViolation(diagnostics)

    def _build_diagnostics(
        self,
        wall_elapsed: float,
        cpu_elapsed: float,
        memory_usage: int | None,
        breaches: Mapping[str, tuple[float | int | None, float | int | None]],
    ) -> WorkerDiagnostics:
        normalized_breaches: dict[
            str, tuple[float | int | None, float | int | None]
        ] = {}
        for key, (actual, limit) in breaches.items():
            actual_value: float | int | None
            if isinstance(actual, (int, float)):
                actual_value = float(actual)
            else:
                actual_value = actual
            limit_value: float | int | None
            if isinstance(limit, (int, float)):
                limit_value = float(limit)
            else:
                limit_value = limit
            normalized_breaches[key] = (actual_value, limit_value)

        payload: dict[str, object] = {
            "plugin": self.plugin_id,
            "wall_time": wall_elapsed,
            "cpu_time": cpu_elapsed,
            "breaches": normalized_breaches,
        }
        if memory_usage is not None:
            payload["memory_usage"] = memory_usage
        dump = _write_mini_dump(self.plugin_id, payload)
        telemetry: dict[str, object] = {
            "plugin": self.plugin_id,
            "wall_time": wall_elapsed,
            "cpu_time": cpu_elapsed,
            "memory_usage": memory_usage,
            "breaches": {
                key: {
                    "observed": actual,
                    "limit": limit,
                }
                for key, (actual, limit) in breaches.items()
            },
            "mini_dump": str(dump) if dump else None,
        }
        diagnostics = WorkerDiagnostics(
            plugin_id=self.plugin_id,
            wall_time=wall_elapsed,
            cpu_time=cpu_elapsed,
            memory_usage=memory_usage,
            limits=self.limits,
            breaches=breaches,
            mini_dump=dump,
            telemetry_payload=telemetry,
        )
        return diagnostics


class WorkerSupervisor:
    """Coordinate sandbox configuration and budget enforcement."""

    _MAX_SYSCALLS = 25

    def __init__(
        self,
        *,
        metrics: PluginMetricsRegistry | None = None,
        sandbox_enabled: bool = True,
    ) -> None:
        self._workers: dict[str, _WorkerProcess] = {}
        self._definitions: dict[str, PluginDefinition] = {}
        self._metrics = metrics or get_global_plugin_metrics()
        self._recent_syscalls: dict[str, deque[str]] = {}
        self._applied_permissions: dict[str, dict[str, str]] = {}
        self._sandbox_enabled = sandbox_enabled
        self._telemetry: "TelemetryClient | NullTelemetryClient | None" = None

    def attach_telemetry(self, telemetry) -> None:
        self._telemetry = telemetry

    def register(
        self,
        plugin_id: str,
        plugin: object,
        definition: PluginDefinition | None,
        *,
        logger: logging.Logger | None = None,
        runtime_activation: RuntimeActivation | None = None,
    ) -> None:
        self._metrics.touch(plugin_id)
        if definition is not None and self._sandbox_enabled:
            try:
                _apply_sandbox(plugin_id, definition.capabilities.sandbox, logger)
            except Exception as exc:  # pragma: no cover - defensive
                self._metrics.record_capability_denial(plugin_id, str(exc))
                raise PluginSandboxError(plugin_id, f"failed to apply sandbox: {exc}") from exc
        if definition is not None:
            self._definitions[plugin_id] = definition
            limits = BudgetLimits.from_budget(definition.resources)
            scopes: Iterable[str] = tuple(definition.capabilities.sandbox)
        else:
            limits = BudgetLimits()
            scopes = ()
        activation_payload = runtime_activation.to_payload() if runtime_activation else None
        self._workers[plugin_id] = _WorkerProcess(
            plugin_id,
            plugin,
            limits,
            definition=definition,
            scopes=scopes,
            logger=logger,
            activation_payload=activation_payload,
            telemetry=self._telemetry,
            sandbox_enabled=self._sandbox_enabled,
        )
        self._record_syscall(plugin_id, "worker registered")
        get_slo_tracker().record_plugin_spawn(plugin_id)

    def unregister(self, plugin_id: str) -> None:
        worker = self._workers.pop(plugin_id, None)
        if worker is not None:
            worker.shutdown()
        self._definitions.pop(plugin_id, None)
        self._record_syscall(plugin_id, "worker unregistered")

    def call(self, plugin_id: str, method_name: str, *args, **kwargs):
        worker = self._workers.get(plugin_id)
        if worker is None:
            raise PluginRuntimeError(plugin_id, f"plugin '{plugin_id}' not registered")
        self._metrics.touch(plugin_id)
        start_time = time.perf_counter()
        status = "ok"
        error_text: str | None = None
        span = None
        attributes = {
            "coolbox.plugin.id": plugin_id,
            "coolbox.plugin.method": method_name,
        }
        try:
            with start_span(
                "coolbox.plugins.call",
                kind=SpanKind.CLIENT,
                attributes=attributes,
            ) as span_obj:
                span = span_obj
                carrier = current_carrier()
                trace_identifier = trace_id_hex(span_obj)
                worker.set_active_trace(trace_identifier, carrier)
                try:
                    result = worker.call(
                        method_name,
                        *args,
                        trace_context=carrier,
                        **kwargs,
                    )
                finally:
                    worker.clear_active_trace()
                if span:
                    span.set_attribute("coolbox.plugin.status", "ok")
                    set_status(span, Status(StatusCode.OK))
                return result
        except BudgetViolation as violation:
            status = "budget_violation"
            error_text = "budget exceeded"
            self._metrics.observe_diagnostics(plugin_id, violation.diagnostics)
            if span:
                span.record_exception(violation)
                set_status(span, Status(StatusCode.ERROR, "budget"))
            raise PluginStartupError(
                plugin_id,
                f"Plugin '{plugin_id}' exceeded its resource budget",
                diagnostics=violation.diagnostics,
            ) from violation
        except PluginStartupError as exc:
            status = "startup_error"
            error_text = str(exc)
            self._metrics.observe_diagnostics(plugin_id, getattr(exc, "diagnostics", None))
            if span:
                span.record_exception(exc)
                set_status(span, Status(StatusCode.ERROR, exc.plugin_id))
            raise
        except Exception as exc:
            status = "runtime_error"
            error_text = str(exc)
            if span:
                span.record_exception(exc)
                set_status(span, Status(StatusCode.ERROR, "runtime"))
            raise PluginRuntimeError(
                plugin_id,
                f"Plugin '{plugin_id}' raised: {exc}",
                original=exc,
            ) from exc
        finally:
            duration = time.perf_counter() - start_time
            if span:
                span.set_attribute("coolbox.plugin.duration_ms", duration * 1000.0)
            self._metrics.record_invocation(
                plugin_id,
                duration=duration,
                trace_id=trace_id_hex(span),
                method=method_name,
                status=status,
                error=error_text,
            )
            millis = int(duration * 1000.0)
            summary = f"{method_name} -> {status} ({millis} ms)"
            self._record_syscall(plugin_id, summary)

    def clear(self) -> None:
        for worker in list(self._workers.values()):
            worker.shutdown()
        self._workers.clear()
        self._definitions.clear()
        self._recent_syscalls.clear()
        self._applied_permissions.clear()

    def metrics_snapshot(self) -> dict[str, PluginMetricsSnapshot]:
        return self._metrics.snapshot()

    def recent_syscalls_snapshot(self) -> dict[str, tuple[str, ...]]:
        return {plugin_id: tuple(entries) for plugin_id, entries in self._recent_syscalls.items()}

    def security_runtime_snapshot(self) -> dict[str, dict[str, object]]:
        snapshot: dict[str, dict[str, object]] = {}
        for plugin_id, worker in self._workers.items():
            info = worker.runtime_snapshot()
            snapshot[plugin_id] = {
                "pid": info.pid,
                "status": info.status,
                "open_ports": info.open_ports,
                "process_tree": info.process_tree,
            }
        return snapshot

    def apply_permission_update(self, plugin_id: str, grants: Mapping[str, str]) -> None:
        self._applied_permissions[plugin_id] = dict(grants)
        if grants:
            changes = ", ".join(f"{cap}:{state}" for cap, state in sorted(grants.items()))
        else:
            changes = "no grants"
        self._record_syscall(plugin_id, f"permissions updated ({changes})")

    def applied_permissions(self) -> Mapping[str, Mapping[str, str]]:
        return {plugin_id: dict(data) for plugin_id, data in self._applied_permissions.items()}

    def _record_syscall(self, plugin_id: str, summary: str) -> None:
        log = self._recent_syscalls.setdefault(
            plugin_id, deque(maxlen=self._MAX_SYSCALLS)
        )
        timestamp = datetime.utcnow().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {summary}"
        log.appendleft(entry)
        try:
            get_permission_manager().record_syscall_summary(plugin_id, summary)
        except Exception:
            pass


def _parse_cpu_percent(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$", value)
    if match:
        return float(match.group(1))
    try:
        numeric = float(value)
        if numeric <= 0:
            return None
        if numeric > 100:
            return 100.0
        return numeric
    except ValueError:
        return None


def _parse_memory_spec(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)([KMGTP]?)(?:B)?\s*$", value, re.IGNORECASE)
    if not match:
        return None
    magnitude = float(match.group(1))
    suffix = match.group(2).upper()
    multipliers = {
        "": 1,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
    }
    return int(magnitude * multipliers.get(suffix, 1))


def _current_memory_usage() -> int | None:
    if resource is None:  # pragma: no cover - platform specific
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    memory = getattr(usage, "ru_maxrss", None)
    if memory is None:
        return None
    if platform.system() == "Darwin":
        return int(memory)
    return int(memory) * 1024


def _write_mini_dump(plugin_id: str, payload: Mapping[str, object]) -> Path | None:
    try:
        plugin_root = ensure_directory(artifacts_dir() / "plugins" / plugin_id)
        directory = ensure_directory(plugin_root / "diagnostics")
        timestamp = int(time.time() * 1000)
        path = directory / f"{timestamp}.json"
        enriched = dict(payload)
        enriched.setdefault("plugin_id", plugin_id)
        enriched.setdefault("captured_at", time.time())
        manifest: Mapping[str, object] | None
        try:
            manifest = get_catalog().manifest_for_plugin(plugin_id)
        except Exception:  # pragma: no cover - diagnostics best effort
            manifest = None
        if manifest:
            enriched.setdefault("manifest", manifest)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(enriched, handle, indent=2, sort_keys=True)
        if manifest:
            manifest_path = plugin_root / "manifest.json"
            try:
                manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            except Exception:  # pragma: no cover - best effort
                pass
        return path
    except Exception:  # pragma: no cover - diagnostics best effort
        return None


def _apply_sandbox(plugin_id: str, scopes: Iterable[str], logger: logging.Logger | None) -> None:
    scopes_set = {scope.lower() for scope in scopes}
    system = platform.system().lower()
    if logger:
        logger.debug(
            "Applying sandbox",
            extra={"plugin": plugin_id, "system": system, "scopes": sorted(scopes_set)},
        )
    # The actual OS-specific sandbox configuration is a no-op placeholder in
    # the test environment. The hooks below provide structured logging so the
    # caller can diagnose misconfiguration without depending on privileged
    # system calls.
    if "unsafe" in scopes_set:
        raise RuntimeError("sandbox scope 'unsafe' is not permitted")


class RemotePluginError(Exception):
    """Container for remote plugin exception details."""

    def __init__(self, message: str, traceback_text: str | None = None) -> None:
        super().__init__(message)
        self.traceback = traceback_text

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.traceback:
            return f"{super().__str__()}\n{self.traceback}"
        return super().__str__()



class _WorkerProcess:
    """Coordinate sandboxed execution through the ``toold`` runner."""

    def __init__(
        self,
        plugin_id: str,
        plugin: object,
        limits: BudgetLimits,
        *,
        definition: PluginDefinition | None,
        scopes: Iterable[str] = (),
        logger: logging.Logger | None = None,
        activation_payload: Mapping[str, object] | None = None,
        telemetry: "TelemetryClient | NullTelemetryClient | None" = None,
        sandbox_enabled: bool = True,
    ) -> None:
        self.plugin_id = plugin_id
        self.limits = limits
        self._definition = definition
        self._scopes = tuple(scopes)
        self._logger_name = logger.name if logger else "coolbox.plugins.supervisor"
        self._logger_level = logger.getEffectiveLevel() if logger else logging.INFO
        self._activation_payload = dict(activation_payload) if activation_payload else None
        self._telemetry = telemetry
        self._sandbox_enabled = sandbox_enabled and definition is not None
        self._local_plugin = plugin if not self._sandbox_enabled else None
        self._controller: BudgetController | None = None
        self._remote: TooldProcess | None = None
        self._active_trace_context: Mapping[str, str] | None = None
        self._active_trace_id: str | None = None
        self._last_trace_context: Mapping[str, str] | None = None
        self._last_trace_id: str | None = None
        if not self._sandbox_enabled:
            if plugin is not None:
                self._controller = BudgetController(plugin_id, limits, logger=logger)
            return
        entrypoint = _resolve_runtime_entrypoint(definition)
        if not entrypoint:
            self._sandbox_enabled = False
            self._local_plugin = plugin
            self._controller = BudgetController(plugin_id, limits, logger=logger)
            return
        if definition is None:
            raise PluginSandboxError(plugin_id, "Sandboxed execution requires a plugin definition")
        environment = dict(definition.runtime.environment)
        heartbeat_interval = limits.wall_time or 15.0
        limits_payload = budget_limits_to_payload(limits)
        try:
            self._remote = TooldProcess(
                plugin_id,
                entrypoint=entrypoint,
                environment=environment,
                activation_payload=self._activation_payload,
                limits_payload=limits_payload,
                scopes=self._scopes,
                logger_name=self._logger_name,
                logger_level=self._logger_level,
                heartbeat_interval=max(1.0, float(heartbeat_interval)),
                telemetry_callback=self._handle_telemetry,
            )
        except TooldProcessError as exc:
            raise PluginSandboxError(plugin_id, str(exc)) from exc

    def set_active_trace(
        self,
        trace_id: str | None,
        carrier: Mapping[str, str] | None,
    ) -> None:
        self._active_trace_id = trace_id
        self._active_trace_context = dict(carrier) if carrier else None

    def clear_active_trace(self) -> None:
        self._active_trace_context = None
        self._active_trace_id = None

    def _update_trace_snapshot(
        self, trace_id: str | None, trace_context: Mapping[str, str] | None
    ) -> None:
        self._last_trace_context = dict(trace_context) if trace_context else None
        if trace_id:
            self._last_trace_id = trace_id
        elif self._active_trace_id:
            self._last_trace_id = self._active_trace_id
        else:
            self._last_trace_id = None

    def call(
        self,
        method_name: str,
        *args,
        trace_context: Mapping[str, str] | None = None,
        **kwargs,
    ) -> object:
        if self._remote is not None:
            try:
                response = self._remote.call(
                    method_name,
                    args=args,
                    kwargs=kwargs,
                    trace_context=trace_context,
                )
            except TooldProcessError as exc:
                raise PluginRuntimeError(self.plugin_id, str(exc)) from exc
            trace_payload = response.get("trace")
            trace_context_payload = (
                dict(trace_payload)
                if isinstance(trace_payload, Mapping)
                else None
            )
            trace_identifier = response.get("trace_id")
            self._update_trace_snapshot(
                str(trace_identifier)
                if isinstance(trace_identifier, str)
                else None,
                trace_context_payload,
            )
            status = response.get("status")
            if status == "ok":
                return response.get("result")
            if status == "violation":
                diagnostics = response.get("diagnostics")
                if isinstance(diagnostics, Mapping):
                    raise BudgetViolation(diagnostics_from_payload(diagnostics))
                raise PluginRuntimeError(self.plugin_id, "worker reported malformed diagnostics")
            if status == "startup_error":
                diagnostics = response.get("diagnostics")
                payload = diagnostics_from_payload(diagnostics) if isinstance(diagnostics, Mapping) else None
                message = response.get("message", "plugin startup error")
                raise PluginStartupError(self.plugin_id, message, diagnostics=payload)
            if status == "runtime_error":
                message = response.get("message", "plugin raised an error")
                remote = RemotePluginError(message, response.get("traceback"))
                raise PluginRuntimeError(self.plugin_id, message, original=remote)
            if status == "timeout":
                diagnostics = response.get("diagnostics")
                if isinstance(diagnostics, Mapping):
                    raise BudgetViolation(diagnostics_from_payload(diagnostics))
                raise PluginRuntimeError(self.plugin_id, "worker timeout missing diagnostics")
            raise PluginRuntimeError(self.plugin_id, f"worker returned unknown status {status!r}")
        plugin = self._local_plugin
        if plugin is None:
            raise PluginRuntimeError(self.plugin_id, "plugin instance unavailable")
        method = getattr(plugin, method_name)
        controller = self._controller
        try:
            if controller and controller.limits.is_enforced():
                result = controller.run(method, *args, **kwargs)
            else:
                result = method(*args, **kwargs)
        except BudgetViolation:
            raise
        except PluginStartupError:
            raise
        except Exception as exc:
            raise PluginRuntimeError(self.plugin_id, f"Plugin '{self.plugin_id}' raised: {exc}", original=exc) from exc
        if trace_context:
            self._update_trace_snapshot(None, trace_context)
        else:
            self._update_trace_snapshot(None, None)
        return result

    def runtime_snapshot(self) -> WorkerRuntimeSnapshot:
        if self._remote is None:
            return WorkerRuntimeSnapshot(None, "in-process", (), ())
        pid = self._remote.pid
        if pid is None:
            return WorkerRuntimeSnapshot(None, None, (), ())
        if psutil is None:  # pragma: no cover - optional dependency
            return WorkerRuntimeSnapshot(pid, None, (), ())
        try:
            process = psutil.Process(pid)
        except Exception:  # pragma: no cover - defensive when process exits
            return WorkerRuntimeSnapshot(pid, None, (), ())
        try:
            status = process.status()
        except Exception:  # pragma: no cover - psutil defensive
            status = None
        ports = _format_open_ports(process)
        tree = _format_process_tree(process)
        return WorkerRuntimeSnapshot(pid, status, ports, tree)

    def shutdown(self) -> None:
        if self._remote is not None:
            self._remote.shutdown()

    def _handle_telemetry(self, payload: Mapping[str, object]) -> None:
        client = self._telemetry
        if client is None:
            return
        recorder = getattr(client, "record_plugin", None)
        if callable(recorder):
            try:
                enriched = dict(payload)
                trace_id = self._active_trace_id or self._last_trace_id
                if trace_id and "trace_id" not in enriched:
                    enriched["trace_id"] = trace_id
                recorder(enriched)
            except Exception:  # pragma: no cover - defensive logging only
                logging.getLogger("coolbox.plugins.supervisor").debug(
                    "Telemetry callback raised", exc_info=True
                )

def _format_open_ports(process) -> tuple[str, ...]:
    if psutil is None:  # pragma: no cover - optional dependency
        return ()
    try:
        connections = process.connections(kind="inet")  # type: ignore[attr-defined]
    except Exception:
        try:
            connections = process.net_connections(kind="inet")  # type: ignore[attr-defined]
        except Exception:
            return ()
    entries: list[str] = []
    for conn in connections[:50]:
        local = _format_address(getattr(conn, "laddr", None))
        remote = _format_address(getattr(conn, "raddr", None))
        status = getattr(conn, "status", "")
        if remote == "—":
            text = f"{local} ({status or 'listening'})"
        else:
            text = f"{local} -> {remote} ({status or 'connected'})"
        entries.append(text)
    return tuple(dict.fromkeys(entries))


def _format_address(address) -> str:
    if not address:
        return "—"
    if isinstance(address, tuple):
        if len(address) >= 2:
            host, port = address[0], address[1]
        elif address:
            host, port = address[0], "*"
        else:
            host, port = "*", "*"
        return f"{host}:{port}"
    host = getattr(address, "ip", None) or getattr(address, "host", None) or "*"
    port = getattr(address, "port", None)
    return f"{host}:{port if port is not None else '*'}"


def _format_process_tree(process) -> tuple[str, ...]:
    if psutil is None:  # pragma: no cover - optional dependency
        return ()
    lines: list[str] = []
    try:
        lines.append(f"Worker {process.pid}: {process.name()}")
    except Exception:
        lines.append(f"Worker {process.pid}")
    try:
        for parent in process.parents():
            try:
                lines.append(f"Parent {parent.pid}: {parent.name()}")
            except Exception:
                lines.append(f"Parent {parent.pid}")
    except Exception:
        pass
    try:
        for child in process.children(recursive=True):
            try:
                lines.append(f"Child {child.pid}: {child.name()}")
            except Exception:
                lines.append(f"Child {child.pid}")
    except Exception:
        pass
    if len(lines) > 40:
        lines = lines[:39] + ["…"]
    return tuple(lines)


def _worker_entrypoint(
    connection,
    plugin_id: str,
    plugin: object,
    limits: BudgetLimits,
    scopes: Iterable[str],
    logger_name: str,
    logger_level: int,
    activation_payload: Mapping[str, object] | None,
) -> None:
    """Entry point for the plugin worker subprocess."""

    logger = logging.getLogger(logger_name)
    logger.setLevel(logger_level)
    try:
        apply_runtime_activation(activation_payload)
    except Exception as exc:  # pragma: no cover - defensive
        connection.send({"status": "error", "message": f"environment activation failed: {exc}"})
        connection.close()
        return
    try:
        _apply_sandbox(plugin_id, scopes, logger)
    except Exception as exc:  # pragma: no cover - defensive
        connection.send({"status": "error", "message": f"sandbox setup failed: {exc}"})
        connection.close()
        return

    controller = BudgetController(plugin_id, limits, logger=logger)
    connection.send({"status": "ready"})

    while True:
        try:
            message = connection.recv()
        except EOFError:
            break
        cmd = message.get("cmd")
        if cmd == "shutdown":
            connection.send({"status": "shutdown"})
            break
        if cmd != "call":
            connection.send({"status": "runtime_error", "message": f"unknown command {cmd!r}"})
            continue
        method_name = message.get("method")
        args = message.get("args", ())
        kwargs = message.get("kwargs", {})
        method = getattr(plugin, method_name)
        trace_context = message.get("trace") if isinstance(message.get("trace"), Mapping) else None
        span_attributes = {
            "coolbox.plugin.id": plugin_id,
            "coolbox.plugin.method": method_name,
        }
        response: dict[str, object]
        trace_payload: dict[str, str] | None = None
        with start_span(
            "coolbox.plugins.worker",
            context=extract_context(trace_context),
            kind=SpanKind.SERVER,
            attributes=span_attributes,
        ) as span:
            try:
                if limits.is_enforced():
                    result = controller.run(method, *args, **kwargs)
                else:
                    result = method(*args, **kwargs)
            except BudgetViolation as violation:
                response = {"status": "violation", "diagnostics": violation.diagnostics}
                if span:
                    span.record_exception(violation)
                    span.set_attribute("coolbox.plugin.status", "budget_violation")
                    set_status(span, Status(StatusCode.ERROR, "budget"))
            except PluginStartupError as exc:
                response = {
                    "status": "startup_error",
                    "message": str(exc),
                    "diagnostics": getattr(exc, "diagnostics", None),
                }
                if span:
                    span.record_exception(exc)
                    span.set_attribute("coolbox.plugin.status", "startup_error")
                    set_status(span, Status(StatusCode.ERROR, "startup"))
            except Exception as exc:  # pragma: no cover - plugin errors routed as runtime errors
                response = {
                    "status": "runtime_error",
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
                if span:
                    span.record_exception(exc)
                    span.set_attribute("coolbox.plugin.status", "runtime_error")
                    set_status(span, Status(StatusCode.ERROR, "runtime"))
            else:
                response = {"status": "ok", "result": result}
                if span:
                    span.set_attribute("coolbox.plugin.status", "ok")
                    set_status(span, Status(StatusCode.OK))
            trace_payload = current_carrier()
        if trace_payload:
            response["trace"] = trace_payload
        connection.send(response)

    connection.close()


__all__ = [
    "BudgetController",
    "BudgetLimits",
    "budget_limits_from_payload",
    "budget_limits_to_payload",
    "BudgetViolation",
    "diagnostics_from_payload",
    "diagnostics_to_payload",
    "PluginRuntimeError",
    "PluginSandboxError",
    "PluginStartupError",
    "PluginWorkerError",
    "PluginMetricsRegistry",
    "PluginMetricsSnapshot",
    "PluginTraceRecord",
    "WorkerDiagnostics",
    "WorkerRuntimeSnapshot",
    "WorkerSupervisor",
    "get_global_plugin_metrics",
]

"""Process supervisor and resource budget enforcement for plugin workers."""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import platform
import re
import traceback
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

try:  # pragma: no cover - optional dependency on Unix only
    import resource
except Exception:  # pragma: no cover - compatibility shim
    resource = None  # type: ignore[assignment]

from coolbox.paths import artifacts_dir, ensure_directory

from .manifest import PluginDefinition, ResourceBudget


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
        payload = {
            "plugin": self.plugin_id,
            "wall_time": wall_elapsed,
            "cpu_time": cpu_elapsed,
            "breaches": {key: (float(actual), float(limit)) if isinstance(actual, (int, float)) else (actual, limit) for key, (actual, limit) in breaches.items()},
        }
        if memory_usage is not None:
            payload["memory_usage"] = memory_usage
        dump = _write_mini_dump(self.plugin_id, payload)
        diagnostics = WorkerDiagnostics(
            plugin_id=self.plugin_id,
            wall_time=wall_elapsed,
            cpu_time=cpu_elapsed,
            memory_usage=memory_usage,
            limits=self.limits,
            breaches=breaches,
            mini_dump=dump,
            telemetry_payload={
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
            },
        )
        return diagnostics


class WorkerSupervisor:
    """Coordinate sandbox configuration and budget enforcement."""

    def __init__(self) -> None:
        self._workers: dict[str, _WorkerProcess] = {}
        self._definitions: dict[str, PluginDefinition] = {}

    def register(
        self,
        plugin_id: str,
        plugin: object,
        definition: PluginDefinition | None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        if definition is not None:
            try:
                _apply_sandbox(plugin_id, definition.capabilities.sandbox, logger)
            except Exception as exc:  # pragma: no cover - defensive
                raise PluginSandboxError(plugin_id, f"failed to apply sandbox: {exc}") from exc
            self._definitions[plugin_id] = definition
            limits = BudgetLimits.from_budget(definition.resources)
            scopes: Iterable[str] = tuple(definition.capabilities.sandbox)
        else:
            limits = BudgetLimits()
            scopes = ()
        self._workers[plugin_id] = _WorkerProcess(
            plugin_id,
            plugin,
            limits,
            scopes=scopes,
            logger=logger,
        )

    def unregister(self, plugin_id: str) -> None:
        worker = self._workers.pop(plugin_id, None)
        if worker is not None:
            worker.shutdown()
        self._definitions.pop(plugin_id, None)

    def call(self, plugin_id: str, method_name: str, *args, **kwargs):
        worker = self._workers.get(plugin_id)
        if worker is None:
            raise PluginRuntimeError(plugin_id, f"plugin '{plugin_id}' not registered")
        try:
            return worker.call(method_name, *args, **kwargs)
        except BudgetViolation as violation:
            raise PluginStartupError(
                plugin_id,
                f"Plugin '{plugin_id}' exceeded its resource budget",
                diagnostics=violation.diagnostics,
            ) from violation
        except PluginStartupError:
            raise
        except Exception as exc:
            raise PluginRuntimeError(plugin_id, f"Plugin '{plugin_id}' raised: {exc}", original=exc) from exc

    def clear(self) -> None:
        for worker in list(self._workers.values()):
            worker.shutdown()
        self._workers.clear()
        self._definitions.clear()


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
        directory = ensure_directory(artifacts_dir() / "plugin_dumps")
        timestamp = int(time.time() * 1000)
        path = directory / f"{plugin_id}-{timestamp}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
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
    """Host plugin execution inside a dedicated worker process."""

    _RESPONSE_GRACE = 0.1

    def __init__(
        self,
        plugin_id: str,
        plugin: object,
        limits: BudgetLimits,
        *,
        scopes: Iterable[str] = (),
        logger: logging.Logger | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.limits = limits
        self._scopes = tuple(scopes)
        self._logger_name = logger.name if logger else "coolbox.plugins.supervisor"
        self._logger_level = logger.getEffectiveLevel() if logger else logging.INFO
        self._closed = False
        self._context = _multiprocessing_context()
        parent_conn, child_conn = self._context.Pipe(duplex=True)
        self._connection = parent_conn
        self._process = self._context.Process(
            target=_worker_entrypoint,
            args=(
                child_conn,
                plugin_id,
                plugin,
                limits,
                self._scopes,
                self._logger_name,
                self._logger_level,
            ),
            name=f"coolbox-plugin-{plugin_id}",
        )
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"This process .* is multi-threaded, use of fork\(\) may lead to deadlocks in the child\.",
                    category=DeprecationWarning,
                    module="multiprocessing.popen_fork",
                )
                self._process.start()
        except Exception:
            child_conn.close()
            self._connection.close()
            self._closed = True
            raise
        child_conn.close()
        try:
            ready = self._connection.recv()
        except EOFError as exc:  # pragma: no cover - defensive
            raise PluginRuntimeError(plugin_id, "worker failed to start") from exc
        status = ready.get("status")
        if status == "error":
            message = ready.get("message", "worker startup failed")
            self._terminate()
            raise PluginSandboxError(plugin_id, message)
        if status != "ready":  # pragma: no cover - defensive
            self._terminate()
            raise PluginRuntimeError(plugin_id, f"unexpected worker handshake: {status!r}")

    def call(self, method_name: str, *args, **kwargs):
        if self._closed:
            raise PluginRuntimeError(self.plugin_id, "worker already shut down")
        if not self._process.is_alive():
            raise PluginRuntimeError(self.plugin_id, "worker terminated unexpectedly")
        payload = {
            "cmd": "call",
            "method": method_name,
            "args": args,
            "kwargs": kwargs,
        }
        start = time.perf_counter()
        try:
            self._connection.send(payload)
        except (BrokenPipeError, OSError) as exc:
            raise PluginRuntimeError(self.plugin_id, "failed to communicate with worker") from exc
        response = self._recv_response(method_name, start)
        status = response.get("status")
        if status == "ok":
            return response.get("result")
        if status == "violation":
            diagnostics = response.get("diagnostics")
            if isinstance(diagnostics, WorkerDiagnostics):
                raise BudgetViolation(diagnostics)
            raise PluginRuntimeError(self.plugin_id, "worker reported malformed diagnostics")
        if status == "startup_error":
            diagnostics = response.get("diagnostics")
            message = response.get("message", "plugin startup error")
            raise PluginStartupError(self.plugin_id, message, diagnostics=diagnostics)
        if status == "runtime_error":
            message = response.get("message", "plugin raised an error")
            remote = RemotePluginError(message, response.get("traceback"))
            raise PluginRuntimeError(self.plugin_id, message, original=remote)
        if status == "timeout":
            diagnostics = response.get("diagnostics")
            if isinstance(diagnostics, WorkerDiagnostics):
                raise BudgetViolation(diagnostics)
            raise PluginRuntimeError(self.plugin_id, "worker timeout missing diagnostics")
        raise PluginRuntimeError(self.plugin_id, f"worker returned unknown status {status!r}")

    def shutdown(self) -> None:
        if self._closed:
            return
        try:
            if self._process.is_alive():
                try:
                    self._connection.send({"cmd": "shutdown"})
                except (BrokenPipeError, OSError):
                    pass
                else:
                    if self._connection.poll(self._RESPONSE_GRACE):
                        try:
                            self._connection.recv()
                        except EOFError:
                            pass
        finally:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=1)
            if self._process.is_alive():  # pragma: no cover - defensive
                self._process.kill()
                self._process.join(timeout=1)
            try:
                self._process.close()
            except Exception:  # pragma: no cover - defensive
                pass
            try:
                self._connection.close()
            except OSError:  # pragma: no cover - defensive
                pass
            self._closed = True

    def _recv_response(self, method_name: str, start_time: float) -> Mapping[str, object]:
        timeout = self.limits.wall_time
        if timeout is not None:
            grace = max(timeout * 0.1, self._RESPONSE_GRACE)
            wait_time = timeout + grace
            if not self._connection.poll(wait_time):
                elapsed = time.perf_counter() - start_time
                diagnostics = self._build_timeout_diagnostics(method_name, elapsed)
                self._terminate()
                return {"status": "timeout", "diagnostics": diagnostics}
        try:
            return self._connection.recv()
        except EOFError as exc:
            self._terminate()
            raise PluginRuntimeError(self.plugin_id, "worker pipe closed unexpectedly") from exc

    def _build_timeout_diagnostics(self, method_name: str, elapsed: float) -> WorkerDiagnostics:
        limit = self.limits.wall_time or 0.0
        breaches = {"wall_time": (elapsed, limit)}
        payload = {
            "plugin": self.plugin_id,
            "method": method_name,
            "wall_time": elapsed,
            "limit": limit,
            "breaches": {
                "wall_time": {
                    "observed": elapsed,
                    "limit": limit,
                }
            },
        }
        dump = _write_mini_dump(self.plugin_id, payload)
        telemetry_payload = dict(payload)
        telemetry_payload["mini_dump"] = str(dump) if dump else None
        return WorkerDiagnostics(
            plugin_id=self.plugin_id,
            wall_time=elapsed,
            cpu_time=0.0,
            memory_usage=None,
            limits=self.limits,
            breaches=breaches,
            mini_dump=dump,
            telemetry_payload=telemetry_payload,
        )

    def _terminate(self) -> None:
        if self._closed:
            return
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(timeout=1)
        if self._process.is_alive():  # pragma: no cover - defensive
            self._process.kill()
            self._process.join(timeout=1)
        try:
            self._process.close()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self._connection.close()
        except OSError:  # pragma: no cover - defensive
            pass
        self._closed = True


def _multiprocessing_context() -> mp.context.BaseContext:
    """Select a multiprocessing context compatible with the host platform."""

    for method in ("fork", "spawn"):
        try:
            if method in mp.get_all_start_methods():
                return mp.get_context(method)
        except ValueError:  # pragma: no cover - fallback if context unavailable
            continue
    return mp.get_context()


def _worker_entrypoint(
    connection,
    plugin_id: str,
    plugin: object,
    limits: BudgetLimits,
    scopes: Iterable[str],
    logger_name: str,
    logger_level: int,
) -> None:
    """Entry point for the plugin worker subprocess."""

    logger = logging.getLogger(logger_name)
    logger.setLevel(logger_level)
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
        try:
            if limits.is_enforced():
                result = controller.run(method, *args, **kwargs)
            else:
                result = method(*args, **kwargs)
        except BudgetViolation as violation:
            connection.send({"status": "violation", "diagnostics": violation.diagnostics})
        except PluginStartupError as exc:
            connection.send(
                {
                    "status": "startup_error",
                    "message": str(exc),
                    "diagnostics": getattr(exc, "diagnostics", None),
                }
            )
        except Exception as exc:  # pragma: no cover - plugin errors routed as runtime errors
            connection.send(
                {
                    "status": "runtime_error",
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        else:
            connection.send({"status": "ok", "result": result})

    connection.close()


__all__ = [
    "BudgetController",
    "BudgetLimits",
    "BudgetViolation",
    "PluginRuntimeError",
    "PluginSandboxError",
    "PluginStartupError",
    "PluginWorkerError",
    "WorkerDiagnostics",
    "WorkerSupervisor",
]

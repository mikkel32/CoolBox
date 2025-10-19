"""Standalone runner hosting a single plugin inside a sandbox process."""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from coolbox.plugins.runtime.environment import apply_runtime_activation
from coolbox.plugins.runtime.native import _temporary_environment
from coolbox.plugins.worker import (
    BudgetController,
    BudgetViolation,
    PluginSandboxError,
    PluginStartupError,
    WorkerDiagnostics,
    budget_limits_from_payload,
    diagnostics_to_payload,
)
from coolbox.plugins.worker import _apply_sandbox  # type: ignore[attr-defined]
from coolbox.telemetry.tracing import (
    SpanKind,
    Status,
    StatusCode,
    current_carrier,
    current_trace_id,
    extract_context,
    set_status,
    start_span,
    trace_id_hex,
)


class _JsonRpcStream:
    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write
        self._lock = threading.Lock()

    def send(self, payload: Mapping[str, Any]) -> None:
        message = json.dumps(payload, separators=(",", ":"))
        with self._lock:
            self._write(message + "\n")

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": dict(params)})


class _TelemetryStream:
    """Capture stdout/stderr writes and forward them as telemetry events."""

    def __init__(self, stream: str, rpc: _JsonRpcStream, plugin_id: str) -> None:
        self._stream = stream
        self._rpc = rpc
        self._plugin_id = plugin_id
        self._buffer: list[str] = []
        self._lock = threading.Lock()

    def write(self, data: str) -> int:  # pragma: no cover - exercised indirectly
        if not data:
            return 0
        with self._lock:
            self._buffer.append(data)
            joined = "".join(self._buffer)
            lines = joined.split("\n")
            self._buffer = [lines.pop()] if lines else []
        for line in lines:
            self._emit(line)
        return len(data)

    def flush(self) -> None:  # pragma: no cover - trivial
        with self._lock:
            if not self._buffer:
                return
            data = "".join(self._buffer)
            self._buffer.clear()
        if data:
            self._emit(data)

    def _emit(self, message: str) -> None:
        payload = {
            "plugin": self._plugin_id,
            "kind": self._stream,
            "message": message,
            "timestamp": time.time(),
        }
        trace_id = current_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id
        self._rpc.notify("telemetry.event", payload)


class _TelemetryLogHandler(logging.Handler):
    def __init__(self, plugin_id: str, rpc: _JsonRpcStream) -> None:
        super().__init__()
        self._plugin = plugin_id
        self._rpc = rpc

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - exercised indirectly
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - defensive
            message = record.getMessage()
        payload = {
            "plugin": self._plugin,
            "kind": "log",
            "level": record.levelname,
            "message": message,
            "logger": record.name,
            "timestamp": time.time(),
        }
        trace_id = current_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id
        self._rpc.notify("telemetry.event", payload)


def _load_plugin(entrypoint: str) -> Any:
    module_name, _, attr = entrypoint.partition(":")
    module = importlib.import_module(module_name)
    target = getattr(module, attr) if attr else module
    return target() if callable(target) else target


def _handle_call(
    plugin: Any,
    params: Mapping[str, Any],
    controller: BudgetController,
) -> dict[str, Any]:
    method_name = params.get("method")
    if not isinstance(method_name, str):
        return {"status": "runtime_error", "message": "missing method name"}
    args = params.get("args")
    kwargs = params.get("kwargs")
    if not isinstance(args, Sequence):
        return {"status": "runtime_error", "message": "arguments must be a sequence"}
    if not isinstance(kwargs, Mapping):
        return {"status": "runtime_error", "message": "keyword arguments must be a mapping"}
    span_attributes = {
        "coolbox.plugin.id": controller.plugin_id,
        "coolbox.plugin.method": method_name,
    }
    with start_span(
        "coolbox.plugins.worker",
        kind=SpanKind.SERVER,
        attributes=span_attributes,
    ) as span:
        method = getattr(plugin, method_name, None)
        if method is None:
            response: dict[str, object] = {
                "status": "runtime_error",
                "message": f"method '{method_name}' not found",
            }
            if span:
                span.set_attribute("coolbox.plugin.status", "missing_method")
                set_status(span, Status(StatusCode.ERROR, "missing_method"))
            trace_payload = current_carrier()
            if trace_payload:
                response["trace"] = dict(trace_payload)
            trace_id = trace_id_hex(span)
            if trace_id:
                response["trace_id"] = trace_id
            return response
        try:
            if controller.limits.is_enforced():
                result = controller.run(method, *list(args), **dict(kwargs))
            else:
                result = method(*list(args), **dict(kwargs))
        except BudgetViolation as violation:
            if span:
                span.record_exception(violation)
                span.set_attribute("coolbox.plugin.status", "budget_violation")
                set_status(span, Status(StatusCode.ERROR, "budget"))
            return {
                "status": "violation",
                "diagnostics": diagnostics_to_payload(violation.diagnostics),
            }
        except PluginStartupError as exc:
            if span:
                span.record_exception(exc)
                span.set_attribute("coolbox.plugin.status", "startup_error")
                set_status(span, Status(StatusCode.ERROR, "startup"))
            diagnostics = None
            raw_diagnostics = getattr(exc, "diagnostics", None)
            if isinstance(raw_diagnostics, WorkerDiagnostics):
                diagnostics = diagnostics_to_payload(raw_diagnostics)
            return {
                "status": "startup_error",
                "message": str(exc),
                "diagnostics": diagnostics,
            }
        except Exception as exc:  # pragma: no cover - plugin errors routed as runtime errors
            if span:
                span.record_exception(exc)
                span.set_attribute("coolbox.plugin.status", "runtime_error")
                set_status(span, Status(StatusCode.ERROR, "runtime"))
            return {
                "status": "runtime_error",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        else:
            if span:
                span.set_attribute("coolbox.plugin.status", "ok")
                set_status(span, Status(StatusCode.OK))
            response: dict[str, object] = {"status": "ok", "result": result}
    trace_payload = current_carrier()
    if trace_payload:
        response["trace"] = dict(trace_payload)
    trace_id = trace_id_hex(span)
    if trace_id:
        response["trace_id"] = trace_id
    return response


def _heartbeat_loop(stop: threading.Event, rpc: _JsonRpcStream, plugin_id: str, interval: float) -> None:
    while not stop.wait(interval):
        rpc.notify(
            "heartbeat",
            {
                "plugin": plugin_id,
                "timestamp": time.time(),
            },
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch a sandboxed plugin runner")
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--environment")
    parser.add_argument("--activation")
    parser.add_argument("--limits", required=True)
    parser.add_argument("--scopes")
    parser.add_argument("--logger")
    parser.add_argument("--log-level", type=int)
    parser.add_argument("--heartbeat", type=float, default=15.0)
    args = parser.parse_args(argv)

    def _write_message(message: str) -> None:
        sys.stdout.write(message)

    rpc = _JsonRpcStream(_write_message)
    plugin_id = args.plugin_id

    try:
        if args.activation:
            activation_payload = json.loads(args.activation)
        else:
            activation_payload = None
    except json.JSONDecodeError as exc:
        rpc.notify("telemetry.event", {
            "plugin": plugin_id,
            "kind": "stderr",
            "message": f"invalid activation payload: {exc}",
            "timestamp": time.time(),
        })
        return 2

    try:
        limits_payload = json.loads(args.limits)
    except json.JSONDecodeError as exc:
        rpc.notify("telemetry.event", {
            "plugin": plugin_id,
            "kind": "stderr",
            "message": f"invalid limits payload: {exc}",
            "timestamp": time.time(),
        })
        return 2

    try:
        environment_payload = json.loads(args.environment) if args.environment else {}
    except json.JSONDecodeError as exc:
        rpc.notify("telemetry.event", {
            "plugin": plugin_id,
            "kind": "stderr",
            "message": f"invalid environment payload: {exc}",
            "timestamp": time.time(),
        })
        return 2
    environment: dict[str, str]
    if isinstance(environment_payload, Mapping):
        environment = {str(key): str(value) for key, value in environment_payload.items()}
    else:
        rpc.notify("telemetry.event", {
            "plugin": plugin_id,
            "kind": "stderr",
            "message": "invalid environment payload: expected mapping",
            "timestamp": time.time(),
        })
        return 2

    scopes: Sequence[str]
    try:
        scopes = tuple(json.loads(args.scopes)) if args.scopes else ()
    except json.JSONDecodeError as exc:
        rpc.notify("telemetry.event", {
            "plugin": plugin_id,
            "kind": "stderr",
            "message": f"invalid sandbox scopes: {exc}",
            "timestamp": time.time(),
        })
        return 2

    logger = logging.getLogger(args.logger or f"coolbox.plugins.toold.{plugin_id}")
    if args.log_level is not None:
        logger.setLevel(args.log_level)
    handler = _TelemetryLogHandler(plugin_id, rpc)
    logger.addHandler(handler)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        apply_runtime_activation(activation_payload)
        limits = budget_limits_from_payload(limits_payload if isinstance(limits_payload, Mapping) else None)
        with _temporary_environment(environment):
            plugin = _load_plugin(args.entrypoint)
        if scopes:
            _apply_sandbox(plugin_id, scopes, logger)
    except PluginSandboxError as exc:
        rpc.notify("telemetry.event", {
            "plugin": plugin_id,
            "kind": "stderr",
            "message": f"sandbox setup failed: {exc}",
            "timestamp": time.time(),
        })
        return 3
    except Exception as exc:  # pragma: no cover - diagnostic only
        rpc.notify("telemetry.event", {
            "plugin": plugin_id,
            "kind": "stderr",
            "message": f"failed to initialize plugin: {exc}",
            "timestamp": time.time(),
        })
        return 3

    controller = BudgetController(plugin_id, limits, logger=logger)
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(stop_event, rpc, plugin_id, max(1.0, float(args.heartbeat))),
        name=f"toold-{plugin_id}-heartbeat",
        daemon=True,
    )
    heartbeat.start()

    stdout_redirect = _TelemetryStream("stdout", rpc, plugin_id)
    stderr_redirect = _TelemetryStream("stderr", rpc, plugin_id)
    sys.stdout = stdout_redirect  # type: ignore[assignment]
    sys.stderr = stderr_redirect  # type: ignore[assignment]

    rpc.notify("ready", {"plugin": plugin_id})

    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        cmd = message.get("method")
        identifier = message.get("id")
        if cmd == "shutdown":
            if identifier is not None:
                rpc.send({"jsonrpc": "2.0", "id": identifier, "result": {"status": "shutdown"}})
            break
        if cmd != "call":
            if identifier is not None:
                rpc.send(
                    {
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "result": {"status": "runtime_error", "message": f"unknown command {cmd}"},
                    }
                )
            continue
        params = message.get("params", {})
        trace_carrier = params.get("trace") if isinstance(params, Mapping) else None
        method_name = params.get("method") if isinstance(params, Mapping) else None
        rpc_attributes = {
            "coolbox.plugin.id": plugin_id,
            "coolbox.plugin.rpc.method": str(method_name) if method_name is not None else "<unknown>",
        }
        parent_context = extract_context(trace_carrier if isinstance(trace_carrier, Mapping) else None)
        with start_span(
            "coolbox.plugins.rpc",
            context=parent_context,
            kind=SpanKind.SERVER,
            attributes=rpc_attributes,
        ) as rpc_span:
            result = _handle_call(plugin, params, controller)
            if rpc_span:
                status = result.get("status") if isinstance(result, Mapping) else None
                if status:
                    rpc_span.set_attribute("coolbox.plugin.rpc.status", status)
                    set_status(
                        rpc_span,
                        Status(StatusCode.OK)
                        if status == "ok"
                        else Status(StatusCode.ERROR, str(status)),
                    )
        rpc.send({"jsonrpc": "2.0", "id": identifier, "result": result})

    stop_event.set()
    heartbeat.join(timeout=1.0)
    handler.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

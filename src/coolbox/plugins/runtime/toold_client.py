"""Host-side client for interacting with the toold runner."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

_JSON = json.dumps


class TooldProcessError(RuntimeError):
    """Raised when the toold subprocess fails or becomes unavailable."""


class TooldProcess:
    """Manage a sandboxed plugin hosted inside the ``toold`` runner."""

    _READY_TIMEOUT = 30.0

    def __init__(
        self,
        plugin_id: str,
        *,
        entrypoint: str,
        environment: Mapping[str, str] | None,
        activation_payload: Mapping[str, object] | None,
        limits_payload: Mapping[str, object],
        scopes: Sequence[str] = (),
        logger_name: str | None = None,
        logger_level: int | None = None,
        heartbeat_interval: float | None = None,
        telemetry_callback: Callable[[Mapping[str, object]], None] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self._telemetry_callback = telemetry_callback
        self._responses: dict[int, Mapping[str, Any]] = {}
        self._response_cv = threading.Condition()
        self._ready_event = threading.Event()
        self._shutdown = threading.Event()
        self._last_heartbeat = time.time()
        self._next_id = 1
        self._logger = logging.getLogger("coolbox.plugins.toold.client")
        self._last_trace_id: str | None = None
        args = [
            sys.executable,
            "-m",
            "coolbox.plugins.runtime.toold_runner",
            "--plugin-id",
            plugin_id,
            "--entrypoint",
            entrypoint,
            "--limits",
            _JSON(dict(limits_payload), separators=(",", ":")),
        ]
        if environment:
            args.extend(["--environment", _JSON(dict(environment), separators=(",", ":"))])
        if activation_payload:
            args.extend(["--activation", _JSON(dict(activation_payload), separators=(",", ":"))])
        if scopes:
            args.extend(["--scopes", _JSON(list(scopes), separators=(",", ":"))])
        if logger_name:
            args.extend(["--logger", logger_name])
        if logger_level is not None:
            args.extend(["--log-level", str(int(logger_level))])
        if heartbeat_interval is not None:
            args.extend(["--heartbeat", str(float(heartbeat_interval))])
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1,
            )
        except OSError as exc:  # pragma: no cover - defensive
            raise TooldProcessError(f"failed to spawn toold: {exc}") from exc
        if self._process.stdin is None or self._process.stdout is None or self._process.stderr is None:
            self._process.kill()
            raise TooldProcessError("failed to initialize pipes for toold process")
        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        self._stderr = self._process.stderr
        self._stdout_thread = threading.Thread(target=self._stdout_loop, name=f"toold-{plugin_id}-stdout", daemon=True)
        self._stderr_thread = threading.Thread(target=self._stderr_loop, name=f"toold-{plugin_id}-stderr", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        if not self._ready_event.wait(self._READY_TIMEOUT):
            self.shutdown()
            raise TooldProcessError(f"timeout waiting for plugin '{plugin_id}' sandbox readiness")

    # ------------------------------------------------------------------
    @property
    def pid(self) -> int | None:
        return getattr(self._process, "pid", None)

    @property
    def last_heartbeat(self) -> float:
        return self._last_heartbeat

    def call(
        self,
        method: str,
        *,
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        trace_context: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        if self._shutdown.is_set():
            raise TooldProcessError("toold process already shut down")
        if self._process.poll() is not None:
            raise TooldProcessError("toold process terminated unexpectedly")
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "call",
            "params": {
                "method": method,
                "args": list(args or ()),
                "kwargs": dict(kwargs or {}),
            },
        }
        if trace_context:
            payload["params"]["trace"] = dict(trace_context)
        self._last_trace_id = None
        self._send(payload)
        with self._response_cv:
            while request_id not in self._responses:
                if self._shutdown.is_set():
                    raise TooldProcessError("toold process shutting down")
                if self._process.poll() is not None:
                    raise TooldProcessError("toold process terminated")
                self._response_cv.wait(timeout=1.0)
            response = self._responses.pop(request_id)
        if "error" in response:
            raise TooldProcessError(str(response["error"]))
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise TooldProcessError("malformed response payload from toold")
        trace_id = response.get("trace_id")
        if isinstance(trace_id, str):
            self._last_trace_id = trace_id
        trace_payload = response.get("trace")
        if isinstance(trace_payload, Mapping):
            self._last_trace_id = response.get("trace_id", self._last_trace_id)
        return result

    def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        try:
            self._send({"jsonrpc": "2.0", "id": self._next_id, "method": "shutdown"})
        except Exception:
            pass
        try:
            self._stdin.close()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self._stdout.close()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self._stderr.close()
        except Exception:  # pragma: no cover - defensive
            pass
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self._process.kill()
        with self._response_cv:
            self._response_cv.notify_all()

    # ------------------------------------------------------------------ internal helpers
    def _send(self, payload: Mapping[str, Any]) -> None:
        line = _JSON(payload, separators=(",", ":")) + "\n"
        try:
            self._stdin.write(line)
            self._stdin.flush()
        except Exception as exc:
            raise TooldProcessError(f"failed to send request to toold: {exc}") from exc

    def _stdout_loop(self) -> None:
        for raw_line in self._stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._emit_telemetry({
                    "plugin": self.plugin_id,
                    "kind": "stdout",
                    "message": raw_line.rstrip("\n"),
                    "timestamp": time.time(),
                })
                continue
            self._handle_message(message)
        self._shutdown.set()
        with self._response_cv:
            self._response_cv.notify_all()

    def _stderr_loop(self) -> None:
        for raw_line in self._stderr:
            text = raw_line.rstrip("\n")
            if not text:
                continue
            self._emit_telemetry(
                {
                    "plugin": self.plugin_id,
                    "kind": "stderr",
                    "message": text,
                    "timestamp": time.time(),
                }
            )
        self._shutdown.set()

    def _handle_message(self, message: Mapping[str, Any]) -> None:
        if message.get("method") == "ready":
            self._ready_event.set()
            return
        if message.get("method") == "heartbeat":
            params = message.get("params")
            if isinstance(params, Mapping):
                timestamp = params.get("timestamp")
                if isinstance(timestamp, (int, float)):
                    self._last_heartbeat = float(timestamp)
            return
        if message.get("method", "").startswith("telemetry"):
            params = message.get("params")
            if isinstance(params, Mapping):
                payload = dict(params)
                payload.setdefault("plugin", self.plugin_id)
                payload.setdefault("timestamp", time.time())
                if self._last_trace_id and "trace_id" not in payload:
                    payload["trace_id"] = self._last_trace_id
                self._emit_telemetry(payload)
            return
        if "id" in message:
            try:
                identifier = int(message["id"])
            except Exception:  # pragma: no cover - defensive
                return
            with self._response_cv:
                self._responses[identifier] = message
                self._response_cv.notify_all()

    def _emit_telemetry(self, payload: Mapping[str, Any]) -> None:
        if self._telemetry_callback is None:
            return
        try:
            self._telemetry_callback(payload)
        except Exception:  # pragma: no cover - defensive
            self._logger.debug("Telemetry callback raised", exc_info=True)


__all__ = ["TooldProcess", "TooldProcessError"]

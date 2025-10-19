"""Lightweight helpers for integrating OpenTelemetry tracing."""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Mapping, MutableMapping, MutableSequence, Sequence

import requests
from requests.auth import AuthBase


if TYPE_CHECKING:  # pragma: no cover - typing only
    from opentelemetry.trace import Span as _SpanType, SpanKind as _SpanKindType, Status as _StatusType, StatusCode as _StatusCodeType
else:  # pragma: no cover - fallback typing when OpenTelemetry is absent at runtime
    _SpanType = Any  # type: ignore[assignment]
    _SpanKindType = Any  # type: ignore[assignment]
    _StatusType = Any  # type: ignore[assignment]
    _StatusCodeType = Any  # type: ignore[assignment]

SpanType = _SpanType
SpanKindType = _SpanKindType
StatusType = _StatusType
StatusCodeType = _StatusCodeType
if TYPE_CHECKING:  # pragma: no cover - typing only
    from opentelemetry.sdk.trace.export import SpanExporter as _SpanExporterType
else:  # pragma: no cover - fallback typing when OpenTelemetry SDK is absent
    _SpanExporterType = Any  # type: ignore[assignment]

SpanExporterType = _SpanExporterType

class _FallbackSpanKind:  # pragma: no cover - best effort shim
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class _FallbackStatus:  # pragma: no cover - shim mirroring minimal API surface
    def __init__(self, status_code: Any, description: str | None = None) -> None:
        self.status_code = status_code
        self.description = description


class _FallbackStatusCode:  # pragma: no cover - shim for StatusCode enum
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


_OtelSpan: Any = Any  # type: ignore[assignment]
_OtelSpanKind: Any = _FallbackSpanKind  # type: ignore[assignment]
_OtelStatus: Any = _FallbackStatus  # type: ignore[assignment]
_OtelStatusCode: Any = _FallbackStatusCode  # type: ignore[assignment]


try:  # pragma: no cover - optional dependency
    from opentelemetry import context as _otel_context
    from opentelemetry import trace as _otel_trace
    from opentelemetry.propagate import extract as _otel_extract, inject as _otel_inject
    from opentelemetry.trace import Span as _OtelSpan, SpanKind as _OtelSpanKind, Status as _OtelStatus, StatusCode as _OtelStatusCode

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - fallback when OpenTelemetry is unavailable
    _OTEL_AVAILABLE = False
    _otel_trace = None  # type: ignore[assignment]
    _otel_extract = None  # type: ignore[assignment]
    _otel_inject = None  # type: ignore[assignment]


if _OTEL_AVAILABLE:
    Span = _OtelSpan
    SpanKind = _OtelSpanKind
    Status = _OtelStatus
    StatusCode = _OtelStatusCode
else:
    Span = Any  # type: ignore[misc,assignment]
    SpanKind = _FallbackSpanKind  # type: ignore[assignment]
    Status = _FallbackStatus
    StatusCode = _FallbackStatusCode


_LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency for exporters
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider as _SdkTracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
        SpanExportResult,
        SimpleSpanProcessor,
    )

    _OTEL_SDK_AVAILABLE = True
except Exception:  # pragma: no cover - exporter configuration optional
    Resource = Any  # type: ignore[assignment]
    _SdkTracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]
    SimpleSpanProcessor = None  # type: ignore[assignment]
    ConsoleSpanExporter = None  # type: ignore[assignment]

    class _SpanExportResultFallback:
        SUCCESS = 0
        FAILURE = 1

    class _SpanExporterFallback:
        def export(self, spans: Sequence[Any]) -> int:  # pragma: no cover - fallback
            return _SpanExportResultFallback.FAILURE

        def shutdown(self) -> None:  # pragma: no cover - fallback
            return None

    SpanExporter = _SpanExporterFallback  # type: ignore[assignment]
    SpanExportResult = _SpanExportResultFallback  # type: ignore[assignment]
    ReadableSpan = Any  # type: ignore[assignment]
    _OTEL_SDK_AVAILABLE = False

_CONFIGURED = False


def _env_flag(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _coerce_json(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except Exception:  # pragma: no cover - defensive
            return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _coerce_json(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_coerce_json(item) for item in value]
    return str(value)


def _sanitize_attributes(attributes: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not attributes:
        return {}
    return {str(key): _coerce_json(value) for key, value in attributes.items()}


def _serialize_span(span: ReadableSpan) -> dict[str, Any]:  # type: ignore[valid-type]
    context = getattr(span, "context", None)
    parent = getattr(span, "parent", None)
    status = getattr(span, "status", None)
    resource = getattr(span, "resource", None)
    instrumentation = getattr(span, "instrumentation_scope", None)
    trace_id = (
        f"{context.trace_id:032x}"
        if context is not None and getattr(context, "trace_id", None) is not None
        else None
    )
    span_id = (
        f"{context.span_id:016x}"
        if context is not None and getattr(context, "span_id", None) is not None
        else None
    )
    parent_id = (
        f"{parent.span_id:016x}"
        if parent is not None and getattr(parent, "span_id", None) is not None
        else None
    )
    status_code = None
    status_message = None
    if status is not None:
        status_code = getattr(getattr(status, "status_code", None), "name", None) or str(
            getattr(status, "status_code", "")
        )
        status_message = getattr(status, "description", None)
    start_time = getattr(span, "start_time", None) or 0
    end_time = getattr(span, "end_time", None) or start_time
    duration_ms = (end_time - start_time) / 1_000_000 if end_time and start_time else 0.0
    events_payload = []
    for event in getattr(span, "events", []) or []:
        events_payload.append(
            {
                "name": getattr(event, "name", ""),
                "timestamp": getattr(event, "timestamp", 0) / 1_000_000_000,
                "attributes": _sanitize_attributes(getattr(event, "attributes", {})),
            }
        )
    resource_attrs = _sanitize_attributes(getattr(resource, "attributes", {}))
    return {
        "timestamp": start_time / 1_000_000_000,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_id,
        "name": getattr(span, "name", ""),
        "kind": getattr(getattr(span, "kind", None), "name", None) or str(getattr(span, "kind", "")),
        "status_code": status_code,
        "status_message": status_message,
        "duration_ms": duration_ms,
        "attributes": _sanitize_attributes(getattr(span, "attributes", {})),
        "resource": resource_attrs,
        "events": events_payload,
        "instrumentation_scope": {
            "name": getattr(instrumentation, "name", None),
            "version": getattr(instrumentation, "version", None),
        },
    }


class JsonlSpanExporter(SpanExporter):  # type: ignore[misc]
    """Write spans to a JSON-lines file for offline diagnostics."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:  # type: ignore[misc]
        if not spans:
            return SpanExportResult.SUCCESS  # type: ignore[attr-defined]
        try:
            records = [_serialize_span(span) for span in spans]
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    for record in records:
                        handle.write(json.dumps(record) + "\n")
        except Exception:  # pragma: no cover - defensive logging only
            _LOGGER.debug("Failed to write spans to %s", self._path, exc_info=True)
            return SpanExportResult.FAILURE  # type: ignore[attr-defined]
        return SpanExportResult.SUCCESS  # type: ignore[attr-defined]

    def shutdown(self) -> None:  # pragma: no cover - nothing to release
        return None


class ClickHouseSpanExporter(SpanExporter):  # type: ignore[misc]
    """Push spans to a ClickHouse endpoint using JSONEachRow."""

    def __init__(
        self,
        *,
        endpoint: str,
        database: str = "coolbox",
        table: str = "otel_spans",
        username: str | None = None,
        password: str | None = None,
        session: requests.Session | None = None,
        auto_create: bool = True,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._database = database
        self._table = table
        self._username = username
        self._password = password
        self._session = session or requests.Session()
        self._logger = logging.getLogger("coolbox.telemetry.trace.clickhouse")
        if auto_create:
            self._ensure_table()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:  # type: ignore[misc]
        if not spans:
            return SpanExportResult.SUCCESS  # type: ignore[attr-defined]
        rows = "\n".join(json.dumps(_serialize_span(span)) for span in spans)
        sql = f"INSERT INTO {self._database}.{self._table} FORMAT JSONEachRow"
        try:
            self._execute(sql, data=rows)
        except Exception:  # pragma: no cover - diagnostics only
            self._logger.debug("Failed to export spans to ClickHouse", exc_info=True)
            return SpanExportResult.FAILURE  # type: ignore[attr-defined]
        return SpanExportResult.SUCCESS  # type: ignore[attr-defined]

    def shutdown(self) -> None:  # pragma: no cover - relies on session cleanup
        self._session.close()

    def _ensure_table(self) -> None:
        sql = (
            f"CREATE TABLE IF NOT EXISTS {self._database}.{self._table} ("
            "timestamp DateTime64(9), "
            "trace_id String, "
            "span_id String, "
            "parent_span_id String, "
            "name String, "
            "kind String, "
            "duration_ms Float64, "
            "status_code String, "
            "status_message String, "
            "attributes JSON, "
            "resource JSON, "
            "events JSON, "
            "instrumentation_scope JSON"
            ") ENGINE = MergeTree ORDER BY (timestamp, trace_id, span_id)"
        )
        try:
            self._execute(sql)
        except Exception:  # pragma: no cover - best effort only
            self._logger.debug("ClickHouse table creation failed", exc_info=True)

    def _execute(self, sql: str, *, data: str | None = None) -> None:
        auth: AuthBase | tuple[str, str] | None = None
        if self._username is not None:
            auth = (self._username, self._password or "")
        response = self._session.post(
            f"{self._endpoint}",
            params={"query": sql},
            data=data,
            auth=auth,
            timeout=10,
        )
        response.raise_for_status()


def configure_from_environment(*, force: bool = False) -> None:
    """Configure OpenTelemetry exporters from environment variables."""

    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    if not (_OTEL_AVAILABLE and _OTEL_SDK_AVAILABLE):
        return
    exporters: list[SpanExporterType] = []

    if _env_flag(os.getenv("COOLBOX_OTEL_EXPORT_CONSOLE")) and ConsoleSpanExporter is not None:
        try:
            exporters.append(ConsoleSpanExporter())  # type: ignore[call-arg]
        except Exception:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to initialise console span exporter", exc_info=True)

    if _env_flag(os.getenv("COOLBOX_OTEL_EXPORT_JSONL")):
        path_value = os.getenv("COOLBOX_OTEL_EXPORT_JSONL_PATH", "artifacts/traces.jsonl")
        try:
            exporters.append(JsonlSpanExporter(Path(path_value)))
        except Exception:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to initialise JSONL span exporter", exc_info=True)

    if _env_flag(os.getenv("COOLBOX_OTEL_EXPORT_CLICKHOUSE")):
        endpoint = os.getenv("COOLBOX_CLICKHOUSE_URL")
        if endpoint:
            database = os.getenv("COOLBOX_CLICKHOUSE_DATABASE", "coolbox")
            table = os.getenv("COOLBOX_CLICKHOUSE_TABLE", "otel_spans")
            username = os.getenv("COOLBOX_CLICKHOUSE_USER")
            password = os.getenv("COOLBOX_CLICKHOUSE_PASSWORD")
            try:
                exporters.append(
                    ClickHouseSpanExporter(
                        endpoint=endpoint,
                        database=database,
                        table=table,
                        username=username,
                        password=password,
                    )
                )
            except Exception:  # pragma: no cover - defensive
                _LOGGER.debug("Failed to initialise ClickHouse span exporter", exc_info=True)

    if not exporters:
        _CONFIGURED = True
        return

    service_name = os.getenv("COOLBOX_OTEL_SERVICE_NAME", "coolbox")
    service_version = os.getenv("COOLBOX_VERSION")
    resource_attributes = {"service.name": service_name}
    if service_version:
        resource_attributes["service.version"] = service_version

    resource = Resource.create(resource_attributes)  # type: ignore[call-arg]
    provider = _SdkTracerProvider(resource=resource)  # type: ignore[operator]

    for exporter in exporters:
        try:
            if ConsoleSpanExporter is not None and isinstance(exporter, ConsoleSpanExporter):
                processor = SimpleSpanProcessor(exporter)  # type: ignore[call-arg]
            else:
                processor = BatchSpanProcessor(exporter)  # type: ignore[call-arg]
            provider.add_span_processor(processor)
        except Exception:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to attach span processor", exc_info=True)

    setattr(provider, "_coolbox_configured", True)
    try:
        _otel_trace.set_tracer_provider(provider)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        _LOGGER.debug("Failed to set tracer provider", exc_info=True)
        return
    _CONFIGURED = True

def _default_tracer() -> Any:
    if not (_OTEL_AVAILABLE and _otel_trace is not None):
        return None
    return _otel_trace.get_tracer("coolbox.telemetry")  # type: ignore[attr-defined]


def _safe_inject(carrier: MutableMapping[str, str], *, context: Any | None = None) -> None:
    if not _OTEL_AVAILABLE or _otel_inject is None:
        return
    try:
        _otel_inject(carrier, context=context)
    except Exception:  # pragma: no cover - defensive logging only
        _LOGGER.debug("Failed to inject OpenTelemetry context", exc_info=True)


def _safe_extract(carrier: Mapping[str, str] | None) -> Any | None:
    if not _OTEL_AVAILABLE or _otel_extract is None:
        return None
    try:
        return _otel_extract(carrier or {})
    except Exception:  # pragma: no cover - defensive logging only
        _LOGGER.debug("Failed to extract OpenTelemetry context", exc_info=True)
        return None


@contextmanager
def start_span(
    name: str,
    *,
    context: Any | None = None,
    attributes: Mapping[str, Any] | None = None,
    kind: SpanKindType | str | None = None,
) -> Iterator[SpanType | None]:
    """Start an OpenTelemetry span, yielding ``None`` when tracing is disabled."""

    if not _OTEL_AVAILABLE:
        yield None
        return
    tracer = _default_tracer()
    span_cm = tracer.start_as_current_span(name, context=context, kind=kind)  # type: ignore[call-arg]
    with span_cm as span:  # type: ignore[assignment]
        if attributes:
            for key, value in attributes.items():
                try:
                    span.set_attribute(key, value)  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover - defensive
                    continue
        yield span


def inject_context(carrier: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """Populate *carrier* with the current trace context."""

    _safe_inject(carrier)
    return carrier


def inject_with_context(
    carrier: MutableMapping[str, str], *, context: Any | None
) -> MutableMapping[str, str]:
    """Populate *carrier* with an explicit *context* when available."""

    _safe_inject(carrier, context=context)
    return carrier


def extract_context(carrier: Mapping[str, str] | None) -> Any | None:
    """Return the OpenTelemetry context extracted from *carrier*."""

    return _safe_extract(carrier)


def current_carrier() -> dict[str, str]:
    """Return a dictionary populated with the active trace context."""

    carrier: dict[str, str] = {}
    inject_context(carrier)
    return carrier


def trace_id_hex(span: SpanType | None) -> str | None:
    """Return the hexadecimal trace identifier for *span* when available."""

    if not (_OTEL_AVAILABLE and span is not None):
        return None
    try:
        span_context = span.get_span_context()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        return None
    if not getattr(span_context, "is_valid", False):
        return None
    trace_id = getattr(span_context, "trace_id", None)
    if trace_id is None:
        return None
    return f"{trace_id:032x}"


def set_status(span: SpanType | None, status: StatusType | object) -> None:
    """Assign *status* to *span* if tracing is enabled."""

    if not (_OTEL_AVAILABLE and span is not None):
        return
    try:
        span.set_status(status)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        _LOGGER.debug("Failed to set span status", exc_info=True)


def current_trace_id() -> str | None:
    """Return the active trace identifier when tracing is enabled."""

    if not _OTEL_AVAILABLE or _otel_trace is None:  # type: ignore[truthy-function]
        return None
    try:
        span = _otel_trace.get_current_span()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        return None
    return trace_id_hex(span)


__all__ = [
    "Span",
    "SpanKind",
    "Status",
    "StatusCode",
    "current_carrier",
    "current_trace_id",
    "extract_context",
    "configure_from_environment",
    "inject_context",
    "inject_with_context",
    "set_status",
    "start_span",
    "trace_id_hex",
]


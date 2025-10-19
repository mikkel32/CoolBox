"""Lightweight helpers for integrating OpenTelemetry tracing."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping, MutableMapping
import logging


try:  # pragma: no cover - optional dependency
    from opentelemetry import context as _otel_context
    from opentelemetry import trace as _otel_trace
    from opentelemetry.propagate import extract as _otel_extract, inject as _otel_inject
    from opentelemetry.trace import Span, SpanKind, Status, StatusCode

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - fallback when OpenTelemetry is unavailable
    Span = Any  # type: ignore[misc,assignment]

    class _FallbackSpanKind:  # pragma: no cover - best effort shim
        INTERNAL = "INTERNAL"
        SERVER = "SERVER"
        CLIENT = "CLIENT"
        PRODUCER = "PRODUCER"
        CONSUMER = "CONSUMER"

    SpanKind = _FallbackSpanKind  # type: ignore[assignment]

    class Status:  # pragma: no cover - shim mirroring minimal API surface
        def __init__(self, status_code: Any, description: str | None = None) -> None:
            self.status_code = status_code
            self.description = description

    class StatusCode:  # pragma: no cover - shim for StatusCode enum
        UNSET = "UNSET"
        OK = "OK"
        ERROR = "ERROR"

    _OTEL_AVAILABLE = False
    _otel_trace = None  # type: ignore[assignment]
    _otel_extract = None  # type: ignore[assignment]
    _otel_inject = None  # type: ignore[assignment]


_LOGGER = logging.getLogger(__name__)


def _default_tracer() -> Any:
    if not _OTEL_AVAILABLE:
        return None
    return _otel_trace.get_tracer("coolbox.telemetry")


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
    kind: SpanKind | str | None = None,
) -> Iterator[Span | None]:
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


def trace_id_hex(span: Span | None) -> str | None:
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


def set_status(span: Span | None, status: Status) -> None:
    """Assign *status* to *span* if tracing is enabled."""

    if not (_OTEL_AVAILABLE and span is not None):
        return
    try:
        span.set_status(status)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        _LOGGER.debug("Failed to set span status", exc_info=True)


__all__ = [
    "Span",
    "SpanKind",
    "Status",
    "StatusCode",
    "current_carrier",
    "extract_context",
    "inject_context",
    "inject_with_context",
    "set_status",
    "start_span",
    "trace_id_hex",
]


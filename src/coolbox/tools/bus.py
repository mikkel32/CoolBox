"""Asynchronous in-process router for tool invocations."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field, replace
import inspect
from threading import RLock
from typing import Any, Union

from coolbox.proto import toolbus_pb2
from coolbox.telemetry import tracing

PayloadType = bytes | str | Mapping[str, Any] | Sequence[Any] | None
InvokeReturn = Union["InvocationResult", toolbus_pb2.InvokeResponse, PayloadType]
StreamItem = Union[toolbus_pb2.StreamChunk, "InvocationResult", PayloadType]
EventItem = Union[toolbus_pb2.Event, Mapping[str, Any], tuple[str, PayloadType]]

ToolInvokeCallable = Callable[["InvocationContext", bytes], InvokeReturn | Awaitable[InvokeReturn]]
ToolStreamCallable = Callable[["InvocationContext", bytes], AsyncIterator[StreamItem] | Awaitable[AsyncIterator[StreamItem]] | Iterable[StreamItem]]
ToolSubscribeCallable = Callable[["InvocationContext", Sequence[str]], AsyncIterator[EventItem] | Awaitable[AsyncIterator[EventItem]] | Iterable[EventItem]]


class GuardRejected(RuntimeError):
    """Raised when a guard clause rejects an invocation."""


@dataclass(slots=True)
class InvocationContext:
    """Context provided to handlers registered with the tool bus."""

    request_id: str
    tool: str
    metadata: Mapping[str, str]
    endpoint: "ToolEndpoint"

    @property
    def source(self) -> str:
        return self.endpoint.source


@dataclass(slots=True)
class InvocationResult:
    """Normalized response returned from a tool invocation."""

    status: int = toolbus_pb2.StatusCode.STATUS_OK
    payload: PayloadType = None
    error: str | None = None

    def to_proto(self, request_id: str) -> toolbus_pb2.InvokeResponse:
        return toolbus_pb2.InvokeResponse(
            request_id=request_id,
            status=self.status,
            payload=_encode_payload(self.payload),
            error=self.error or "",
        )


@dataclass(slots=True)
class ToolEndpoint:
    """Registered handler for tool invocations."""

    name: str
    source: str
    invoke_handler: ToolInvokeCallable | None = None
    stream_handler: ToolStreamCallable | None = None
    subscribe_handler: ToolSubscribeCallable | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def supports_invoke(self) -> bool:
        return self.invoke_handler is not None

    def supports_stream(self) -> bool:
        return self.stream_handler is not None

    def supports_subscribe(self) -> bool:
        return self.subscribe_handler is not None


ToolRegistration = ToolEndpoint


@dataclass(slots=True)
class Subscription:
    """Async iterator backed by the in-process subscription registry."""

    topics: tuple[str, ...]
    queue: "asyncio.Queue[toolbus_pb2.Event | None]"
    cancel: Callable[[], None]
    _closed: bool = False

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> toolbus_pb2.Event:
        if self._closed and self.queue.empty():
            raise StopAsyncIteration
        item = await self.queue.get()
        if item is None:
            self._closed = True
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.cancel()
            self.queue.put_nowait(None)


class ToolBus:
    """In-process async router that multiplexes invocations across providers."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("coolbox.tools.bus")
        self._endpoints: dict[str, ToolEndpoint] = {}
        self._subscribers: MutableMapping[str, set[asyncio.Queue[toolbus_pb2.Event | None]]] = defaultdict(set)
        self._lock = RLock()

    # ------------------------------------------------------------------
    async def invoke(self, request: toolbus_pb2.InvokeRequest) -> toolbus_pb2.InvokeResponse:
        """Execute a request/response tool invocation."""

        metadata = dict(request.header.metadata)
        carrier_context = tracing.extract_context(metadata)
        endpoint = self._endpoints.get(request.header.tool)
        context = InvocationContext(
            request_id=request.header.request_id or _generate_request_id(),
            tool=request.header.tool,
            metadata=metadata,
            endpoint=endpoint if endpoint else ToolEndpoint(
                name=request.header.tool,
                source="<unregistered>",
            ),
        )
        span_attributes = {
            "coolbox.tool.name": context.tool,
            "coolbox.tool.request_id": context.request_id,
            "coolbox.tool.source": context.endpoint.source,
        }
        with tracing.start_span(
            "coolbox.toolbus.invoke",
            context=carrier_context,
            kind=tracing.SpanKind.SERVER,
            attributes=span_attributes,
        ) as span:
            tracing.inject_context(metadata)
            if endpoint is None or not endpoint.supports_invoke():
                if span:
                    span.set_attribute("coolbox.tool.status", "not_found")
                return toolbus_pb2.InvokeResponse(
                    request_id=context.request_id,
                    status=toolbus_pb2.StatusCode.STATUS_NOT_FOUND,
                    error=f"Tool '{context.tool}' is not registered",
                )
            try:
                result_obj = await _maybe_await(
                    endpoint.invoke_handler(context, request.payload)
                )  # type: ignore[arg-type]
                result = _coerce_invocation_result(result_obj)
            except GuardRejected as exc:
                if span:
                    span.record_exception(exc)
                    span.set_attribute("coolbox.tool.status", "guard_rejected")
                return toolbus_pb2.InvokeResponse(
                    request_id=context.request_id,
                    status=toolbus_pb2.StatusCode.STATUS_GUARD_REJECTED,
                    error=str(exc),
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                if span:
                    span.record_exception(exc)
                    span.set_attribute("coolbox.tool.status", "error")
                self._logger.exception("Invocation for tool %s failed", context.tool)
                return toolbus_pb2.InvokeResponse(
                    request_id=context.request_id,
                    status=toolbus_pb2.StatusCode.STATUS_ERROR,
                    error=str(exc),
                )
            if span:
                span.set_attribute("coolbox.tool.status", "ok")
            return result.to_proto(context.request_id)

    async def stream(self, request: toolbus_pb2.StreamRequest) -> AsyncIterator[toolbus_pb2.StreamChunk]:
        """Execute a streaming invocation yielding multiple chunks."""

        metadata = dict(request.header.metadata)
        carrier_context = tracing.extract_context(metadata)
        endpoint = self._endpoints.get(request.header.tool)
        context = InvocationContext(
            request_id=request.header.request_id or _generate_request_id(),
            tool=request.header.tool,
            metadata=metadata,
            endpoint=endpoint if endpoint else ToolEndpoint(
                name=request.header.tool,
                source="<unregistered>",
            ),
        )
        span_attributes = {
            "coolbox.tool.name": context.tool,
            "coolbox.tool.request_id": context.request_id,
            "coolbox.tool.source": context.endpoint.source,
        }
        with tracing.start_span(
            "coolbox.toolbus.stream",
            context=carrier_context,
            kind=tracing.SpanKind.SERVER,
            attributes=span_attributes,
        ) as span:
            tracing.inject_context(metadata)
            if endpoint is None or not endpoint.supports_stream():
                if span:
                    span.set_attribute("coolbox.tool.status", "not_found")
                yield toolbus_pb2.StreamChunk(
                    request_id=context.request_id,
                    status=toolbus_pb2.StatusCode.STATUS_NOT_FOUND,
                    end_of_stream=True,
                    error=f"Stream '{context.tool}' is not registered",
                )
                return
            try:
                stream_obj = await _maybe_iter(
                    endpoint.stream_handler, context, request.payload
                )  # type: ignore[arg-type]
            except GuardRejected as exc:
                if span:
                    span.record_exception(exc)
                    span.set_attribute("coolbox.tool.status", "guard_rejected")
                yield toolbus_pb2.StreamChunk(
                    request_id=context.request_id,
                    status=toolbus_pb2.StatusCode.STATUS_GUARD_REJECTED,
                    end_of_stream=True,
                    error=str(exc),
                )
                return
            except Exception as exc:  # pragma: no cover - defensive logging
                if span:
                    span.record_exception(exc)
                    span.set_attribute("coolbox.tool.status", "error")
                self._logger.exception("Streaming invocation for %s failed", context.tool)
                yield toolbus_pb2.StreamChunk(
                    request_id=context.request_id,
                    status=toolbus_pb2.StatusCode.STATUS_ERROR,
                    end_of_stream=True,
                    error=str(exc),
                )
                return
            async for chunk in stream_obj:
                normalized = _coerce_stream_chunk(chunk, context.request_id)
                yield normalized
            if span:
                span.set_attribute("coolbox.tool.status", "ok")
            yield toolbus_pb2.StreamChunk(
                request_id=context.request_id,
                status=toolbus_pb2.StatusCode.STATUS_OK,
                end_of_stream=True,
            )

    async def subscribe(self, request: toolbus_pb2.SubscribeRequest) -> Subscription:
        """Subscribe to one or more topics, optionally delegated to a worker."""

        metadata = dict(request.header.metadata)
        carrier_context = tracing.extract_context(metadata)
        endpoint = self._endpoints.get(request.header.tool)
        context = InvocationContext(
            request_id=request.header.request_id or _generate_request_id(),
            tool=request.header.tool,
            metadata=metadata,
            endpoint=endpoint if endpoint else ToolEndpoint(
                name=request.header.tool,
                source="<unregistered>",
            ),
        )
        topics = tuple(request.topics or (context.tool,))
        span_attributes = {
            "coolbox.tool.name": context.tool,
            "coolbox.tool.request_id": context.request_id,
            "coolbox.tool.source": context.endpoint.source,
        }
        with tracing.start_span(
            "coolbox.toolbus.subscribe",
            context=carrier_context,
            kind=tracing.SpanKind.SERVER,
            attributes=span_attributes,
        ) as span:
            tracing.inject_context(metadata)
            if endpoint and endpoint.supports_subscribe():
                queue: asyncio.Queue[toolbus_pb2.Event | None] = asyncio.Queue()

                async def _forward() -> None:
                    try:
                        stream_obj = await _maybe_iter(
                            endpoint.subscribe_handler, context, topics
                        )  # type: ignore[arg-type]
                        async for item in stream_obj:
                            queue.put_nowait(_coerce_event(item, context.request_id))
                    except asyncio.CancelledError:  # pragma: no cover - subscription teardown
                        pass
                    except Exception as exc:  # pragma: no cover - defensive logging
                        if span:
                            span.record_exception(exc)
                            span.set_attribute("coolbox.tool.status", "error")
                        self._logger.exception(
                            "Subscription stream for %s failed", context.tool
                        )
                    finally:
                        queue.put_nowait(None)

                task = asyncio.create_task(_forward())

                def _cancel() -> None:
                    task.cancel()

                if span:
                    span.set_attribute("coolbox.tool.status", "ok")
                return Subscription(topics=topics, queue=queue, cancel=_cancel)
            if span:
                span.set_attribute("coolbox.tool.status", "local")
            return self._subscribe_local(context.request_id, topics)

    # ------------------------------------------------------------------
    def register_local(
        self,
        name: str,
        *,
        invoke: ToolInvokeCallable | None = None,
        stream: ToolStreamCallable | None = None,
        subscribe: ToolSubscribeCallable | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ToolRegistration:
        """Register a local in-process endpoint."""

        endpoint = ToolEndpoint(
            name=name,
            source="local",
            invoke_handler=invoke,
            stream_handler=stream,
            subscribe_handler=subscribe,
            metadata=dict(metadata or {}),
        )
        self.register_endpoint(endpoint)
        return endpoint

    def register_endpoint(self, endpoint: ToolEndpoint) -> None:
        """Register a fully-configured endpoint instance."""

        with self._lock:
            if endpoint.name in self._endpoints:
                raise ValueError(f"Endpoint '{endpoint.name}' already registered")
            self._endpoints[endpoint.name] = endpoint

    def register_worker(self, worker_id: str, endpoints: Iterable[ToolEndpoint]) -> None:
        """Register endpoints backed by an isolated worker."""

        for endpoint in endpoints:
            clone = replace(
                endpoint,
                source=endpoint.source or f"worker:{worker_id}",
            )
            self.register_endpoint(clone)

    def unregister(self, name: str) -> None:
        """Remove a registered endpoint."""

        with self._lock:
            self._endpoints.pop(name, None)

    # ------------------------------------------------------------------
    def publish(
        self,
        topic: str,
        payload: PayloadType,
        *,
        metadata: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> None:
        """Publish an event to local subscribers."""

        if topic not in self._subscribers:
            return
        event = toolbus_pb2.Event(
            topic=topic,
            payload=_encode_payload(payload),
            metadata=dict(metadata or {}),
            request_id=request_id or _generate_request_id(),
        )
        for queue in list(self._subscribers[topic]):
            queue.put_nowait(event)

    # ------------------------------------------------------------------
    def get_endpoint(self, name: str) -> ToolEndpoint | None:
        return self._endpoints.get(name)

    # ------------------------------------------------------------------
    def _subscribe_local(self, request_id: str, topics: tuple[str, ...]) -> Subscription:
        queue: asyncio.Queue[toolbus_pb2.Event | None] = asyncio.Queue()
        for topic in topics:
            self._subscribers[topic].add(queue)

        def _cancel() -> None:
            for topic in topics:
                subscribers = self._subscribers.get(topic)
                if not subscribers:
                    continue
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(topic, None)

        return Subscription(topics=topics, queue=queue, cancel=_cancel)


# ----------------------------------------------------------------------
async def _maybe_await(value: InvokeReturn | Awaitable[InvokeReturn]) -> InvokeReturn:
    if inspect.isawaitable(value):
        return await value  # type: ignore[arg-type]
    return value  # type: ignore[return-value]


async def _maybe_iter(
    func: ToolStreamCallable | ToolSubscribeCallable,
    context: InvocationContext,
    argument: Any,
) -> AsyncIterator[Any]:
    result = func(context, argument)
    if inspect.isawaitable(result):
        result = await result
    if hasattr(result, "__aiter__"):
        return result  # type: ignore[return-value]
    if isinstance(result, Iterable):
        async def _gen() -> AsyncIterator[Any]:
            for item in result:  # pragma: no branch - simple passthrough
                yield item
        return _gen()
    raise TypeError("Handler must return an async iterator or iterable")


def _coerce_invocation_result(obj: InvokeReturn) -> InvocationResult:
    if isinstance(obj, InvocationResult):
        return obj
    if isinstance(obj, toolbus_pb2.InvokeResponse):
        return InvocationResult(status=obj.status, payload=obj.payload, error=obj.error or None)
    if isinstance(obj, tuple) and len(obj) == 2:
        payload, status = obj
        return InvocationResult(status=int(status), payload=payload)
    return InvocationResult(payload=obj)


def _coerce_stream_chunk(item: StreamItem, request_id: str) -> toolbus_pb2.StreamChunk:
    if isinstance(item, toolbus_pb2.StreamChunk):
        if not item.request_id:
            item.request_id = request_id
        return item
    if isinstance(item, InvocationResult):
        return toolbus_pb2.StreamChunk(
            request_id=request_id,
            status=item.status,
            payload=_encode_payload(item.payload),
            error=item.error or "",
        )
    return toolbus_pb2.StreamChunk(
        request_id=request_id,
        status=toolbus_pb2.StatusCode.STATUS_OK,
        payload=_encode_payload(item),
    )


def _coerce_event(item: EventItem, request_id: str) -> toolbus_pb2.Event:
    if isinstance(item, toolbus_pb2.Event):
        if not item.request_id:
            item.request_id = request_id
        return item
    if isinstance(item, tuple):
        topic, payload = item
        return toolbus_pb2.Event(
            topic=str(topic),
            payload=_encode_payload(payload),
            request_id=request_id,
        )
    if isinstance(item, Mapping):
        topic = str(item.get("topic"))
        payload = item.get("payload")
        metadata = {
            str(key): str(value)
            for key, value in dict(item.get("metadata", {})).items()
        }
        return toolbus_pb2.Event(
            topic=topic,
            payload=_encode_payload(payload),
            metadata=metadata,
            request_id=str(item.get("request_id", request_id)),
        )
    raise TypeError(f"Unsupported event payload: {type(item)!r}")


def _encode_payload(payload: PayloadType) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    try:
        return json.dumps(payload, sort_keys=True).encode("utf-8")
    except TypeError:
        return str(payload).encode("utf-8")


def _generate_request_id() -> str:
    return uuid.uuid4().hex


__all__ = [
    "GuardRejected",
    "InvocationContext",
    "InvocationResult",
    "Subscription",
    "ToolBus",
    "ToolEndpoint",
    "ToolRegistration",
]

"""Lightweight protocol message representations for the tool bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import MutableMapping, Sequence


class StatusCode(IntEnum):
    """Enumeration of response status codes used by the tool bus."""

    STATUS_OK = 0
    STATUS_ERROR = 1
    STATUS_NOT_FOUND = 2
    STATUS_UNAVAILABLE = 3
    STATUS_GUARD_REJECTED = 4


@dataclass(slots=True)
class Header:
    """Metadata header describing a tool bus request."""

    request_id: str = ""
    tool: str = ""
    metadata: MutableMapping[str, str] = field(default_factory=dict)

    def copy(self) -> "Header":
        """Return a shallow copy of the header and metadata."""

        return Header(request_id=self.request_id, tool=self.tool, metadata=dict(self.metadata))


@dataclass(slots=True)
class InvokeRequest:
    """Request payload for invoke style tool bus calls."""

    header: Header = field(default_factory=Header)
    payload: bytes = b""


@dataclass(slots=True)
class InvokeResponse:
    """Response payload produced by invoke handlers."""

    request_id: str = ""
    status: StatusCode = StatusCode.STATUS_OK
    payload: bytes = b""
    error: str = ""

    def success(self) -> bool:
        return self.status == StatusCode.STATUS_OK


@dataclass(slots=True)
class StreamRequest:
    """Request payload for stream style tool bus calls."""

    header: Header = field(default_factory=Header)
    payload: bytes = b""


@dataclass(slots=True)
class StreamChunk:
    """Chunk of data emitted from a streaming invocation."""

    request_id: str = ""
    payload: bytes = b""
    end_of_stream: bool = False
    status: StatusCode = StatusCode.STATUS_OK
    error: str = ""


@dataclass(slots=True)
class SubscribeRequest:
    """Request payload describing subscription topics."""

    header: Header = field(default_factory=Header)
    topics: Sequence[str] = field(default_factory=tuple)


@dataclass(slots=True)
class Event:
    """Event published on the tool bus."""

    topic: str = ""
    payload: bytes = b""
    metadata: MutableMapping[str, str] = field(default_factory=dict)
    request_id: str = ""


@dataclass(slots=True)
class Ack:
    """Acknowledgement emitted from the tool bus."""

    request_id: str = ""
    status: StatusCode = StatusCode.STATUS_OK
    error: str = ""


__all__ = [
    "Ack",
    "Event",
    "Header",
    "InvokeRequest",
    "InvokeResponse",
    "StatusCode",
    "StreamChunk",
    "StreamRequest",
    "SubscribeRequest",
]

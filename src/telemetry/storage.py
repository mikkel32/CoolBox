"""Storage adapters for telemetry events."""
from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Iterable, List, Protocol
import json

from .events import TelemetryEvent


class TelemetryStorageAdapter(Protocol):
    """Protocol for persisting telemetry events."""

    def persist(self, event: TelemetryEvent) -> None:
        ...

    def flush(self) -> None:
        ...

    def bootstrap(self) -> Iterable[TelemetryEvent]:
        """Return previously persisted events for knowledge-base hydration."""
        return []


class JsonlTelemetryStorage:
    """Append-only JSON-lines storage suitable for opt-in telemetry."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._buffer: List[TelemetryEvent] = []
        self._lock = Lock()

    def persist(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._buffer.append(event)

    def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                for event in self._buffer:
                    handle.write(json.dumps(event.to_dict()) + "\n")
            self._buffer.clear()

    def bootstrap(self) -> Iterable[TelemetryEvent]:
        if not self.path.exists():
            return []
        events: List[TelemetryEvent] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    events.append(TelemetryEvent.from_dict(data))
        except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
            return []
        return events


class InMemoryTelemetryStorage:
    """Non-persistent storage used for unit tests."""

    def __init__(self) -> None:
        self.events: List[TelemetryEvent] = []

    def persist(self, event: TelemetryEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        return None

    def bootstrap(self) -> Iterable[TelemetryEvent]:
        return list(self.events)


__all__ = [
    "TelemetryStorageAdapter",
    "JsonlTelemetryStorage",
    "InMemoryTelemetryStorage",
]

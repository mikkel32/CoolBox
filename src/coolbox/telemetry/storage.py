"""Storage adapters for telemetry events."""
from __future__ import annotations

from pathlib import Path
from threading import Lock

from typing import Any, Iterable, List, MutableSequence, Protocol, Sequence
import json
import logging
import threading

try:  # pragma: no cover - optional dependency for telemetry exporters
    import requests  # type: ignore[assignment]
except Exception:  # pragma: no cover - degrade gracefully when requests is absent
    requests = None  # type: ignore[assignment]

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


class CompositeTelemetryStorage:
    """Multiplex events across multiple storage adapters."""

    def __init__(
        self,
        adapters: Sequence[TelemetryStorageAdapter],
        *,
        bootstrap_index: int = 0,
    ) -> None:
        if not adapters:
            raise ValueError("CompositeTelemetryStorage requires at least one adapter")
        self._adapters: tuple[TelemetryStorageAdapter, ...] = tuple(adapters)
        if bootstrap_index < 0 or bootstrap_index >= len(self._adapters):
            raise IndexError("bootstrap_index out of range")
        self._bootstrap_index = bootstrap_index

    def persist(self, event: TelemetryEvent) -> None:
        for adapter in self._adapters:
            try:
                adapter.persist(event)
            except Exception:  # pragma: no cover - defensive logging
                logging.getLogger(__name__).debug(
                    "Telemetry adapter %s.persist failed", adapter, exc_info=True
                )

    def flush(self) -> None:
        for adapter in self._adapters:
            try:
                adapter.flush()
            except Exception:  # pragma: no cover - defensive logging
                logging.getLogger(__name__).debug(
                    "Telemetry adapter %s.flush failed", adapter, exc_info=True
                )

    def bootstrap(self) -> Iterable[TelemetryEvent]:
        return self._adapters[self._bootstrap_index].bootstrap()


class ClickHouseTelemetryStorage:
    """Stream telemetry events to a ClickHouse HTTP endpoint."""

    def __init__(
        self,
        *,
        endpoint: str = "http://localhost:8123",
        database: str = "coolbox",
        table: str = "telemetry_events",
        username: str | None = None,
        password: str | None = None,
        session: Any | None = None,
        batch_size: int = 64,
        auto_create: bool = True,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.database = database
        self.table = table
        self.username = username
        self.password = password
        if session is not None:
            self._session = session
        elif requests is not None:
            self._session = requests.Session()
        else:
            raise RuntimeError("requests is required to use ClickHouse telemetry storage")
        self._batch_size = max(1, batch_size)
        self._buffer: MutableSequence[TelemetryEvent] = []
        self._lock = threading.Lock()
        self._logger = logging.getLogger("coolbox.telemetry.clickhouse")
        if auto_create:
            self._ensure_table()

    # ------------------------------------------------------------------
    def persist(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self._batch_size:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def bootstrap(self) -> Iterable[TelemetryEvent]:
        return []

    # ------------------------------------------------------------------ internal helpers
    def _ensure_table(self) -> None:
        sql = (
            f"CREATE TABLE IF NOT EXISTS {self.database}.{self.table} ("
            "timestamp DateTime64(3), "
            "type String, "
            "metadata JSON"
            ") ENGINE = MergeTree ORDER BY (timestamp, type)"
        )
        try:
            self._execute(sql)
        except Exception:  # pragma: no cover - best effort table creation
            self._logger.debug("ClickHouse table creation failed", exc_info=True)

    def _flush_locked(self) -> None:
        if not self._buffer:
            return
        events = list(self._buffer)
        self._buffer.clear()
        rows = "\n".join(
            json.dumps(
                {
                    "timestamp": event.timestamp,
                    "type": event.type.value,
                    "metadata": event.metadata,
                }
            )
            for event in events
        )
        sql = f"INSERT INTO {self.database}.{self.table} FORMAT JSONEachRow"
        try:
            self._execute(sql, data=rows)
        except Exception:  # pragma: no cover - diagnostic logging only
            self._logger.debug("Failed to insert telemetry batch into ClickHouse", exc_info=True)

    def _execute(self, sql: str, *, data: str | None = None) -> None:
        auth = None
        if self.username is not None and self.password is not None:
            auth = (self.username, self.password)
        if not hasattr(self._session, "post"):
            raise RuntimeError("Configured HTTP session does not provide a 'post' method")
        response = self._session.post(
            self.endpoint,
            params={"query": sql},
            data=data,
            auth=auth,
            timeout=5,
            headers={"Content-Type": "application/json"} if data else None,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"ClickHouse request failed with status {response.status_code}: {response.text[:200]}"
            )


__all__ = [
    "TelemetryStorageAdapter",
    "JsonlTelemetryStorage",
    "InMemoryTelemetryStorage",
    "CompositeTelemetryStorage",
    "ClickHouseTelemetryStorage",
]

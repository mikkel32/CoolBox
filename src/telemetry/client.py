"""Telemetry client orchestrating consent, storage and knowledge base."""
from __future__ import annotations

from typing import Callable, Mapping
import platform
import time

from .events import TelemetryEvent, TelemetryEventType
from .knowledge import TelemetryKnowledgeBase
from .storage import TelemetryStorageAdapter


class NullTelemetryClient:
    """Telemetry client that drops all events."""

    knowledge: TelemetryKnowledgeBase

    def __init__(self) -> None:
        self.knowledge = TelemetryKnowledgeBase()

    def record_environment(self, metadata: Mapping[str, object]) -> None:
        return None

    def record_stage(self, metadata: Mapping[str, object]) -> None:
        return None

    def record_task(self, metadata: Mapping[str, object]) -> None:
        return None

    def record_run(self, metadata: Mapping[str, object]) -> None:
        return None

    def flush(self) -> None:
        return None


class TelemetryClient:
    """Collects telemetry events and forwards them to the configured storage."""

    def __init__(
        self,
        storage: TelemetryStorageAdapter,
        *,
        clock: Callable[[], float] | None = None,
        knowledge_base: TelemetryKnowledgeBase | None = None,
    ) -> None:
        self.storage = storage
        self.clock = clock or time.time
        self.knowledge = knowledge_base or TelemetryKnowledgeBase()
        self._enabled = True
        self.knowledge.load(storage.bootstrap())

    def disable(self) -> None:
        self._enabled = False

    def _record(self, event: TelemetryEvent) -> None:
        if not self._enabled:
            return
        self.storage.persist(event)
        self.knowledge.observe(event)

    def record_environment(self, metadata: Mapping[str, object] | None = None) -> None:
        payload = {
            "platform": platform.platform(),
            "python": platform.python_version(),
        }
        if metadata:
            payload.update(metadata)
        self._record(TelemetryEvent(TelemetryEventType.ENVIRONMENT, metadata=payload))

    def record_run(self, metadata: Mapping[str, object] | None = None) -> None:
        self._record(TelemetryEvent(TelemetryEventType.RUN, metadata=dict(metadata or {})))

    def record_stage(self, metadata: Mapping[str, object]) -> None:
        data = dict(metadata)
        data.setdefault("recorded_at", self.clock())
        self._record(TelemetryEvent(TelemetryEventType.STAGE, metadata=data))

    def record_task(self, metadata: Mapping[str, object]) -> None:
        data = dict(metadata)
        data.setdefault("recorded_at", self.clock())
        self._record(TelemetryEvent(TelemetryEventType.TASK, metadata=data))

    def record_consent(self, *, granted: bool, source: str) -> None:
        self._record(
            TelemetryEvent(
                TelemetryEventType.CONSENT,
                metadata={"granted": granted, "source": source},
            )
        )

    def flush(self) -> None:
        if not self._enabled:
            return
        self.storage.flush()


__all__ = ["TelemetryClient", "NullTelemetryClient"]

"""Telemetry event primitives for orchestrator instrumentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping
import time


class TelemetryEventType(str, Enum):
    """Enumerates the event types captured by the telemetry pipeline."""

    ENVIRONMENT = "environment"
    STAGE = "stage"
    TASK = "task"
    CONSENT = "consent"
    RUN = "run"


@dataclass(slots=True)
class TelemetryEvent:
    """Serializable telemetry payload."""

    type: TelemetryEventType
    timestamp: float = field(default_factory=lambda: time.time())
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TelemetryEvent":
        event_type = TelemetryEventType(data["type"])
        timestamp = float(data.get("timestamp", time.time()))
        metadata = dict(data.get("metadata", {}))
        return cls(event_type, timestamp=timestamp, metadata=metadata)


__all__ = ["TelemetryEvent", "TelemetryEventType"]

"""Telemetry package providing consent, storage and knowledge utilities."""
from .client import NullTelemetryClient, TelemetryClient
from .consent import ConsentDecision, TelemetryConsentManager
from .events import TelemetryEvent, TelemetryEventType
from .knowledge import (
    ConfigPatch,
    RemediationSuggestion,
    TaskOverride,
    TelemetryKnowledgeBase,
)
from .storage import (
    ClickHouseTelemetryStorage,
    CompositeTelemetryStorage,
    InMemoryTelemetryStorage,
    JsonlTelemetryStorage,
    TelemetryStorageAdapter,
)
from . import tracing

__all__ = [
    "NullTelemetryClient",
    "TelemetryClient",
    "TelemetryConsentManager",
    "ConsentDecision",
    "TelemetryEvent",
    "TelemetryEventType",
    "TelemetryKnowledgeBase",
    "RemediationSuggestion",
    "ConfigPatch",
    "TaskOverride",
    "TelemetryStorageAdapter",
    "JsonlTelemetryStorage",
    "InMemoryTelemetryStorage",
    "CompositeTelemetryStorage",
    "ClickHouseTelemetryStorage",
    "tracing",
]

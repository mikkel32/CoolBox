"""Event primitives shared between the setup orchestrator and dashboards."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, MutableMapping, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.setup.orchestrator import SetupStage


class DashboardEventType(str, Enum):
    """Kinds of events emitted by the setup orchestrator."""

    STAGE = "stage"
    TASK = "task"
    LOG = "log"
    THEME = "theme"
    TROUBLESHOOTING = "troubleshooting"


@dataclass(slots=True)
class DashboardEvent:
    """Base dashboard event payload."""

    type: DashboardEventType
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "payload": dict(self.payload)}


class StageEvent(DashboardEvent):
    """Stage lifecycle transition event."""

    __slots__ = ("stage", "status", "message")

    def __init__(
        self,
        stage: "SetupStage",
        *,
        status: str,
        message: str | None = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(DashboardEventType.STAGE, payload or {})
        self.stage = stage
        self.status = status
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update({
            "stage": self.stage.value if hasattr(self.stage, "value") else str(self.stage),
            "status": self.status,
            "message": self.message,
        })
        return data


class TaskEvent(DashboardEvent):
    """Individual task lifecycle events."""

    __slots__ = ("task", "stage", "status", "error")

    def __init__(
        self,
        task: str,
        stage: "SetupStage",
        *,
        status: str,
        error: str | None = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(DashboardEventType.TASK, payload or {})
        self.task = task
        self.stage = stage
        self.status = status
        self.error = error

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update({
            "task": self.task,
            "stage": self.stage.value if hasattr(self.stage, "value") else str(self.stage),
            "status": self.status,
            "error": self.error,
        })
        return data


class LogEvent(DashboardEvent):
    """Log entry originating from the orchestrator."""

    __slots__ = ("level", "message")

    def __init__(self, level: str, message: str, *, payload: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(DashboardEventType.LOG, payload or {})
        self.level = level
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update({"level": self.level, "message": self.message})
        return data


class TroubleshootingEvent(DashboardEvent):
    """Event produced when diagnostics complete."""

    __slots__ = ("diagnostic", "result")

    def __init__(self, diagnostic: str, result: Mapping[str, Any]) -> None:
        super().__init__(DashboardEventType.TROUBLESHOOTING, result)
        self.diagnostic = diagnostic
        self.result = result

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update({"diagnostic": self.diagnostic})
        return data


class ThemeEvent(DashboardEvent):
    """Event signalling that a theme change was requested."""

    __slots__ = ("theme",)

    def __init__(self, theme: str, *, payload: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(DashboardEventType.THEME, payload or {})
        self.theme = theme

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update({"theme": self.theme})
        return data


DashboardEventMap = MutableMapping[str, DashboardEvent]

__all__ = [
    "DashboardEvent",
    "DashboardEventMap",
    "DashboardEventType",
    "LogEvent",
    "StageEvent",
    "TaskEvent",
    "ThemeEvent",
    "TroubleshootingEvent",
]

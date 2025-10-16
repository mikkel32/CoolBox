"""Setup orchestration package for CoolBox."""

from .orchestrator import SetupOrchestrator, SetupTask, SetupStage, SetupResult, SetupStatus

__all__ = [
    "SetupOrchestrator",
    "SetupTask",
    "SetupStage",
    "SetupResult",
    "SetupStatus",
]

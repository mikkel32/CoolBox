"""Console dashboard primitives for CoolBox."""

from .dashboard import (
    BaseDashboard,
    DashboardLayout,
    DashboardTheme,
    DashboardThemeProfile,
    DashboardThemeSettings,
    JsonDashboard,
    TextualDashboard,
    TroubleshootingStudio,
    create_dashboard,
)
from .events import (
    DashboardEvent,
    DashboardEventType,
    LogEvent,
    StageEvent,
    TaskEvent,
    TroubleshootingEvent,
)

__all__ = [
    "BaseDashboard",
    "DashboardLayout",
    "DashboardTheme",
    "DashboardThemeProfile",
    "DashboardThemeSettings",
    "JsonDashboard",
    "TextualDashboard",
    "TroubleshootingStudio",
    "create_dashboard",
    "DashboardEvent",
    "DashboardEventType",
    "LogEvent",
    "StageEvent",
    "TaskEvent",
    "TroubleshootingEvent",
]

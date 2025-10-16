from types import SimpleNamespace

import pytest

from src.console.dashboard import (
    DashboardLayout,
    DashboardTheme,
    DashboardThemeSettings,
    JsonDashboard,
    TextualDashboardApp,
    TroubleshootingStudio,
    TEXTUAL_AVAILABLE,
    THEME_PROFILES,
)
from src.console.events import TaskEvent
from src.setup.orchestrator import SetupStage
from src.telemetry import TelemetryKnowledgeBase
from src.telemetry.events import TelemetryEvent, TelemetryEventType


def _seed_knowledge_base() -> TelemetryKnowledgeBase:
    kb = TelemetryKnowledgeBase()
    kb.observe(
        TelemetryEvent(
            TelemetryEventType.TASK,
            metadata={
                "status": "failed",
                "failure_code": "preflight:fail:RuntimeError",
                "suggested_fix": "Check configuration",
            },
        )
    )
    return kb


def test_json_dashboard_surfaces_suggestions() -> None:
    kb = _seed_knowledge_base()
    dashboard = JsonDashboard(theme=DashboardTheme.MINIMAL, knowledge_base=kb)
    failure_event = TaskEvent(
        "fail",
        SetupStage.PREFLIGHT,
        status="failed",
        error="RuntimeError('boom')",
        payload={"failure_code": "preflight:fail:RuntimeError", "error_type": "RuntimeError"},
    )
    dashboard.handle_event(failure_event)
    suggestion_events = [event for event in dashboard.events if event.get("type") == "suggestion"]
    assert suggestion_events
    assert suggestion_events[0]["suggestion"] == "Check configuration"


@pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="Textual UI not available in test environment")
def test_textual_dashboard_logs_suggestions(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = _seed_knowledge_base()
    orchestrator = SimpleNamespace(stage_order=())
    studio = TroubleshootingStudio(publisher=lambda event: None)
    theme = DashboardThemeSettings(THEME_PROFILES[DashboardTheme.MINIMAL])
    app = TextualDashboardApp(
        orchestrator,
        theme=theme,
        layout=DashboardLayout.MINIMAL,
        studio=studio,
        knowledge_base=kb,
    )
    messages: list[tuple[str, str]] = []

    def capture(level: str, message: str, *, theme: object) -> None:
        messages.append((level, message))

    monkeypatch.setattr(app.deps, "record", lambda *_, **__: None)
    monkeypatch.setattr(app.log_panel, "add_entry", capture)
    failure_event = TaskEvent(
        "fail",
        SetupStage.PREFLIGHT,
        status="failed",
        error="RuntimeError('boom')",
        payload={"failure_code": "preflight:fail:RuntimeError", "error_type": "RuntimeError"},
    )
    app.handle_dashboard_event(failure_event)
    assert any("Suggested fix" in message for _, message in messages)

"""Smoke tests for the console dashboard."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from src.console.dashboard import (
    DashboardLayout,
    DashboardTheme,
    DashboardThemeSettings,
    JsonDashboard,
    TroubleshootingStudio,
)
from src.console.events import StageEvent, TaskEvent, ThemeEvent
from src.setup.orchestrator import SetupOrchestrator, SetupStage, SetupTask
from src.setup.recipes import Recipe
from src.telemetry import TelemetryKnowledgeBase


def test_json_dashboard_records_events() -> None:
    dashboard = JsonDashboard(theme=DashboardTheme.BRANDED)
    dashboard.start()
    dashboard.handle_event(StageEvent(SetupStage.PREFLIGHT, status="started"))
    dashboard.handle_event(
        TaskEvent("preflight.check", SetupStage.PREFLIGHT, status="completed", payload={"ok": True})
    )
    state = dashboard.export_state()
    assert state["theme"]["profile"] == DashboardTheme.BRANDED.value
    assert any(event.get("stage") == "preflight" for event in state["events"])


def test_orchestrator_publishes_events(tmp_path: Path) -> None:
    orchestrator = SetupOrchestrator(root=tmp_path)
    events: list = []
    orchestrator.subscribe(events.append)

    def task_action(context):
        return {"ok": True}

    orchestrator.register_task(
        SetupTask("deps", SetupStage.PREFLIGHT, task_action)
    )
    orchestrator.register_task(
        SetupTask("preflight.ok", SetupStage.PREFLIGHT, task_action, dependencies=("deps",))
    )
    recipe = Recipe(name="test", data={})

    orchestrator.run(recipe)

    stage_events = [event for event in events if isinstance(event, StageEvent)]
    task_events = [event for event in events if isinstance(event, TaskEvent)]
    assert any(event.status == "started" for event in stage_events)
    assert any(event.status == "completed" for event in stage_events)
    assert any(event.task == "preflight.ok" and event.status == "completed" for event in task_events)


def test_troubleshooting_studio_bundle(tmp_path: Path) -> None:
    published: list = []
    studio = TroubleshootingStudio(publisher=published.append)
    result = studio.run("doctor")
    assert "python" in result.payload
    bundle_path = tmp_path / "bundle.json"
    studio.export_bundle(bundle_path)
    payload = json.loads(bundle_path.read_text())
    assert {"doctor", "virtualenv", "collect"}.issubset(payload)
    assert published  # diagnostics publish events


def test_textual_dashboard_handles_events() -> None:
    pytest.importorskip("textual", reason="textual is required")
    class DummyOrchestrator:
        stage_order = (SetupStage.PREFLIGHT,)

        def __init__(self) -> None:
            self.rerun_calls: list[SetupStage] = []

        def rerun_stage(self, stage: SetupStage) -> None:
            self.rerun_calls.append(stage)

    orchestrator = cast(SetupOrchestrator, DummyOrchestrator())
    studio = TroubleshootingStudio()

    from src.console.dashboard import TextualDashboardApp, THEME_PROFILES

    app = TextualDashboardApp(
        orchestrator,
        theme=DashboardThemeSettings(THEME_PROFILES[DashboardTheme.MINIMAL]),
        layout=DashboardLayout.MINIMAL,
        studio=studio,
        knowledge_base=TelemetryKnowledgeBase(),
    )

    async def run_app() -> None:
        async with app.run_test() as pilot:  # type: ignore[attr-defined]
            app.handle_dashboard_event(StageEvent(SetupStage.PREFLIGHT, status="started"))
            app.handle_dashboard_event(
                TaskEvent("preflight.ok", SetupStage.PREFLIGHT, status="completed", payload={})
            )
            app.handle_dashboard_event(ThemeEvent(DashboardTheme.HIGH_CONTRAST.value))
            await pilot.pause()
            rendered = app.summary.render()
            assert "preflight" in str(rendered)
            assert app._theme.profile.name is DashboardTheme.HIGH_CONTRAST

    asyncio.run(run_app())

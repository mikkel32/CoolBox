"""Unit tests covering orchestrator dependency management."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.setup.orchestrator import (
    SetupOrchestrator,
    SetupResult,
    SetupStage,
    SetupStatus,
    SetupTask,
)
from src.setup.recipes import Recipe


def _orchestrator(tmp_path) -> SetupOrchestrator:
    return SetupOrchestrator(root=tmp_path)


def test_run_validates_missing_dependencies(tmp_path) -> None:
    orchestrator = _orchestrator(tmp_path)

    orchestrator.register_task(
        SetupTask(
            name="primary",
            stage=SetupStage.PREFLIGHT,
            action=lambda context: {},
            dependencies=("missing",),
        )
    )

    recipe = Recipe(name="missing")
    with pytest.raises(ValueError) as excinfo:
        orchestrator.run(recipe, load_plugins=False)

    assert "depends on unknown task 'missing'" in str(excinfo.value)


def test_run_detects_dependency_cycles(tmp_path) -> None:
    orchestrator = _orchestrator(tmp_path)

    orchestrator.register_task(
        SetupTask(
            name="alpha",
            stage=SetupStage.PREFLIGHT,
            action=lambda context: {},
            dependencies=("omega",),
        )
    )
    orchestrator.register_task(
        SetupTask(
            name="omega",
            stage=SetupStage.PREFLIGHT,
            action=lambda context: {},
            dependencies=("alpha",),
        )
    )

    recipe = Recipe(name="cycle")
    with pytest.raises(ValueError) as excinfo:
        orchestrator.run(recipe, load_plugins=False)

    assert "Cyclic dependency" in str(excinfo.value)


def test_dependency_failure_marks_downstream_tasks(tmp_path) -> None:
    orchestrator = _orchestrator(tmp_path)
    events: list[Any] = []
    orchestrator.subscribe(events.append)

    def fail_task(context):
        return SetupResult(
            task="fails",
            stage=SetupStage.PREFLIGHT,
            status=SetupStatus.FAILED,
            payload={},
            error=RuntimeError("boom"),
        )

    orchestrator.register_task(
        SetupTask(name="fails", stage=SetupStage.PREFLIGHT, action=fail_task)
    )
    orchestrator.register_task(
        SetupTask(
            name="blocked",
            stage=SetupStage.PREFLIGHT,
            action=lambda context: {},
            dependencies=("fails",),
        )
    )

    recipe = Recipe(name="blocked")
    results = orchestrator.run(recipe, load_plugins=False)

    blocked = next(result for result in results if result.task == "blocked")
    assert blocked.status is SetupStatus.SKIPPED
    assert blocked.payload["reason"] == "dependency-blocked"
    assert blocked.payload["failure_code"] == "preflight:blocked:dependency-blocked"

    task_events = [event for event in events if getattr(event, "task", None) == "blocked"]
    assert any(event.payload.get("reason") == "dependency-blocked" for event in task_events)


def test_fail_fast_blocks_later_stages(tmp_path) -> None:
    orchestrator = _orchestrator(tmp_path)
    stage_two = SimpleNamespace(ran=False)

    def fail(context):
        return SetupResult(
            task="primary",
            stage=SetupStage.PREFLIGHT,
            status=SetupStatus.FAILED,
            payload={},
            error=RuntimeError("boom"),
        )

    orchestrator.register_task(
        SetupTask(name="primary", stage=SetupStage.PREFLIGHT, action=fail)
    )
    orchestrator.register_task(
        SetupTask(
            name="secondary",
            stage=SetupStage.VERIFICATION,
            action=lambda context: setattr(stage_two, "ran", True) or {},
        )
    )

    recipe = Recipe(name="fail-fast")
    orchestrator.run(recipe, load_plugins=False)

    assert stage_two.ran is False


def test_continue_on_failure_allows_later_stages(tmp_path) -> None:
    orchestrator = _orchestrator(tmp_path)
    stage_two = SimpleNamespace(ran=False)

    def fail(context):
        return SetupResult(
            task="primary",
            stage=SetupStage.PREFLIGHT,
            status=SetupStatus.FAILED,
            payload={},
            error=RuntimeError("boom"),
        )

    orchestrator.register_task(
        SetupTask(name="primary", stage=SetupStage.PREFLIGHT, action=fail)
    )
    orchestrator.register_task(
        SetupTask(
            name="secondary",
            stage=SetupStage.VERIFICATION,
            action=lambda context: setattr(stage_two, "ran", True) or {},
        )
    )

    recipe = Recipe(
        name="continue",
        data={"config": {"continue_on_failure": True}},
    )
    orchestrator.run(recipe, load_plugins=False)

    assert stage_two.ran is True

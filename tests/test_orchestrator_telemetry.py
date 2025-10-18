import pytest

from coolbox.setup.orchestrator import (
    SetupOrchestrator,
    SetupResult,
    SetupStage,
    SetupStatus,
    SetupTask,
)
from coolbox.setup.recipes import Recipe
from coolbox.telemetry import InMemoryTelemetryStorage, TelemetryClient, TelemetryEventType


class _Clock:
    def __init__(self, start: float = 1_000.0, step: float = 0.25) -> None:
        self.value = start
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


@pytest.mark.usefixtures("tmp_path")
def test_orchestrator_emits_telemetry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    clock = _Clock()
    storage = InMemoryTelemetryStorage()
    telemetry = TelemetryClient(storage, clock=clock)
    monkeypatch.setattr("coolbox.setup.orchestrator.time.time", clock)

    orchestrator = SetupOrchestrator(root=tmp_path, telemetry=telemetry)

    def succeed(context):
        return {"status": "ok"}

    def fail(context):
        return SetupResult(
            task="fail",
            stage=SetupStage.PREFLIGHT,
            status=SetupStatus.FAILED,
            payload={"suggested_fix": "Restart the installer"},
            error=RuntimeError("boom"),
        )

    orchestrator.register_task(
        SetupTask(name="prepare", stage=SetupStage.PREFLIGHT, action=succeed)
    )
    orchestrator.register_task(
        SetupTask(name="fail", stage=SetupStage.PREFLIGHT, action=fail)
    )

    recipe = Recipe(name="demo")
    results = orchestrator.run(recipe, load_plugins=False)

    assert any(result.status is SetupStatus.FAILED for result in results)

    run_events = [event for event in storage.events if event.type is TelemetryEventType.RUN]
    assert run_events and run_events[0].metadata["offline"] is False

    task_events = [event for event in storage.events if event.type is TelemetryEventType.TASK]
    failure_event = next(event for event in task_events if event.metadata["status"] == "failed")
    assert failure_event.metadata["failure_code"] == "preflight:fail:RuntimeError"
    assert failure_event.metadata["suggested_fix"] == "Restart the installer"

    stage_events = [event for event in storage.events if event.type is TelemetryEventType.STAGE]
    assert any(event.metadata["status"] == "failed" for event in stage_events)

    suggestion = telemetry.knowledge.suggest_fix(
        failure_code="preflight:fail:RuntimeError"
    )
    assert suggestion is not None
    assert suggestion.title == "Restart the installer"

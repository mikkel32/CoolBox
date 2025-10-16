from types import SimpleNamespace

import pytest

from src.boot import BootManager
from src.setup.orchestrator import SetupOrchestrator, SetupStage, SetupTask
from src.setup.recipes import Recipe
from src.telemetry import InMemoryTelemetryStorage, TelemetryClient, TelemetryEventType


class _ConsentStub:
    def __init__(self, granted: bool = True) -> None:
        self.granted = granted

    def ensure_opt_in(self):
        return SimpleNamespace(granted=self.granted, source="integration")


class _RecipeLoader:
    def __init__(self, recipe: Recipe) -> None:
        self._recipe = recipe

    def load(self, identifier):  # pragma: no cover - simple passthrough
        return self._recipe


def _build_orchestrator(root, telemetry: TelemetryClient) -> SetupOrchestrator:
    orchestrator = SetupOrchestrator(root=root, telemetry=telemetry)

    def preflight(context):
        mode = "offline" if context.get("setup.offline") else "online"
        return {"mode": mode}

    def verify(context):
        return {}

    orchestrator.register_task(SetupTask("preflight", SetupStage.PREFLIGHT, preflight))
    orchestrator.register_task(SetupTask("verify", SetupStage.VERIFICATION, verify))
    return orchestrator


@pytest.fixture()
def telemetry_client() -> TelemetryClient:
    storage = InMemoryTelemetryStorage()

    def clock() -> float:
        clock.current += 0.5
        return clock.current

    clock.current = 5_000.0  # type: ignore[attr-defined]
    return TelemetryClient(storage, clock=clock)


def _boot_manager(tmp_path, telemetry: TelemetryClient) -> BootManager:
    recipe = Recipe(name="integration", data={"stages": {"preflight": {}, "verification": {}}})
    loader = _RecipeLoader(recipe)
    return BootManager(
        manifest_path=None,
        app_factory=lambda: SimpleNamespace(run=lambda: None),
        orchestrator_factory=lambda: _build_orchestrator(tmp_path, telemetry),
        recipe_loader=loader,
        dependency_checker=lambda root: False,
        telemetry=telemetry,
        consent_manager=_ConsentStub(),
    )


def test_online_setup_flow_emits_telemetry(tmp_path, telemetry_client: TelemetryClient) -> None:
    manager = _boot_manager(tmp_path, telemetry_client)
    manager.run([])
    run_event = next(event for event in telemetry_client.storage.events if event.type is TelemetryEventType.RUN)
    assert run_event.metadata["offline"] is False
    stage_events = [event for event in telemetry_client.storage.events if event.type is TelemetryEventType.STAGE]
    assert {event.metadata["stage"] for event in stage_events} >= {"preflight", "verification"}


def test_offline_setup_flow_records_mode(tmp_path, telemetry_client: TelemetryClient, monkeypatch) -> None:
    monkeypatch.setenv("_OFFLINE", "1")
    manager = _boot_manager(tmp_path, telemetry_client)
    manager.run([])
    run_event = next(event for event in telemetry_client.storage.events if event.type is TelemetryEventType.RUN)
    assert run_event.metadata["offline"] is True
    stage_events = [event for event in telemetry_client.storage.events if event.type is TelemetryEventType.STAGE]
    assert any(event.metadata["stage"] == "preflight" for event in stage_events)

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Mapping, cast

import pytest

from coolbox.boot import BootManager
from coolbox.setup import load_last_run
from coolbox.setup.orchestrator import (
    SetupOrchestrator,
    SetupResult,
    SetupStage,
    SetupStatus,
    SetupTask,
)
from coolbox.setup.recipes import Recipe, RecipeLoader
from coolbox.telemetry import InMemoryTelemetryStorage, TelemetryClient, TelemetryEventType
from coolbox.telemetry.consent import ConsentDecision, TelemetryConsentManager


class _ConsentStub(TelemetryConsentManager):
    def __init__(self, granted: bool = True) -> None:
        super().__init__(storage_path=None)
        self._granted = granted

    def ensure_opt_in(
        self, *, default: Literal["deny", "allow"] = "deny"
    ) -> ConsentDecision:
        return ConsentDecision(granted=self._granted, source="integration")


class _RecipeLoader(RecipeLoader):
    def __init__(self, recipe: Recipe) -> None:
        super().__init__(search_paths=[])
        self._recipe = recipe

    def load(
        self,
        identifier: str | Path | None,
        *,
        overrides: Mapping[str, object] | None = None,
    ) -> Recipe:
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
    state = {"current": 5_000.0}

    def clock() -> float:
        state["current"] += 0.5
        return state["current"]

    client = TelemetryClient(storage, clock=clock)
    return client


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
    storage = cast(InMemoryTelemetryStorage, telemetry_client.storage)
    run_event = next(event for event in storage.events if event.type is TelemetryEventType.RUN)
    assert run_event.metadata["offline"] is False
    stage_events = [event for event in storage.events if event.type is TelemetryEventType.STAGE]
    assert {event.metadata["stage"] for event in stage_events} >= {"preflight", "verification"}


def test_offline_setup_flow_records_mode(tmp_path, telemetry_client: TelemetryClient, monkeypatch) -> None:
    monkeypatch.setenv("_OFFLINE", "1")
    manager = _boot_manager(tmp_path, telemetry_client)
    manager.run([])
    storage = cast(InMemoryTelemetryStorage, telemetry_client.storage)
    run_event = next(event for event in storage.events if event.type is TelemetryEventType.RUN)
    assert run_event.metadata["offline"] is True
    stage_events = [event for event in storage.events if event.type is TelemetryEventType.STAGE]
    assert any(event.metadata["stage"] == "preflight" for event in stage_events)


def test_setup_flow_stops_after_blocking_failure(tmp_path, telemetry_client: TelemetryClient) -> None:
    orchestrator = SetupOrchestrator(root=tmp_path, telemetry=telemetry_client)
    executed: list[str] = []

    def fail(context):
        return SetupResult(
            task="preflight.fail",
            stage=SetupStage.PREFLIGHT,
            status=SetupStatus.FAILED,
            payload={},
            error=RuntimeError("boom"),
        )

    orchestrator.register_task(
        SetupTask("preflight.fail", SetupStage.PREFLIGHT, fail)
    )
    orchestrator.register_task(
        SetupTask(
            "verify.should_not_run",
            SetupStage.VERIFICATION,
            lambda context: executed.append("verify") or {},
        )
    )

    recipe = Recipe(name="integration", data={"stages": {"preflight": {}, "verification": {}}})
    orchestrator.run(recipe, plugins=())

    assert executed == []
    storage = cast(InMemoryTelemetryStorage, telemetry_client.storage)
    verification_events = {
        event.metadata["stage"]
        for event in storage.events
        if event.type is TelemetryEventType.STAGE
    }
    assert "verification" not in verification_events


def test_recovery_resume_skips_completed_tasks(
    tmp_path, telemetry_client: TelemetryClient
) -> None:
    call_counts = {"preflight": 0, "verify": 0}
    state = {"should_fail": True}

    def _resume_orchestrator() -> SetupOrchestrator:
        orchestrator = SetupOrchestrator(root=tmp_path, telemetry=telemetry_client)

        def preflight(context):
            call_counts["preflight"] += 1
            return {"attempt": call_counts["preflight"]}

        def verify(context):
            call_counts["verify"] += 1
            if state["should_fail"]:
                state["should_fail"] = False
                return SetupResult(
                    task="verify",
                    stage=SetupStage.VERIFICATION,
                    status=SetupStatus.FAILED,
                    payload={"attempt": call_counts["verify"]},
                    error=RuntimeError("boom"),
                )
            return {"attempt": call_counts["verify"]}

        orchestrator.register_task(SetupTask("preflight", SetupStage.PREFLIGHT, preflight))
        orchestrator.register_task(SetupTask("verify", SetupStage.VERIFICATION, verify))
        return orchestrator

    recipe = Recipe(
        name="integration",
        data={"stages": {"preflight": {}, "verification": {}}},
    )
    loader = _RecipeLoader(recipe)
    manager = BootManager(
        manifest_path=None,
        app_factory=lambda: SimpleNamespace(run=lambda: None),
        orchestrator_factory=_resume_orchestrator,
        recipe_loader=loader,
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=_ConsentStub(),
    )
    recipe_obj = manager._load_recipe(None)

    with pytest.raises(RuntimeError):
        manager._execute_setup(
            recipe_obj,
            stages=None,
            task_names=None,
            plugins=None,
            dev=None,
        )

    assert call_counts["preflight"] == 1
    assert call_counts["verify"] == 1
    journal = load_last_run(tmp_path)
    assert journal is not None

    manager._execute_setup(
        recipe_obj,
        stages=[SetupStage.VERIFICATION],
        task_names=None,
        plugins=None,
        dev=None,
    )

    assert call_counts["preflight"] == 1
    assert call_counts["verify"] == 2

    storage = cast(InMemoryTelemetryStorage, telemetry_client.storage)
    verification_events = [
        event
        for event in storage.events
        if event.type is TelemetryEventType.STAGE
        and event.metadata.get("stage") == "verification"
    ]
    assert len(verification_events) >= 2
    statuses = {event.metadata.get("status") for event in verification_events}
    assert {"failed", "completed"}.issubset(statuses)

    journal_after = load_last_run(tmp_path)
    assert journal_after is not None
    verify_results = [res for res in journal_after.results if res.task == "verify"]
    assert len(verify_results) == 2
    assert verify_results[-1].status is SetupStatus.SUCCESS

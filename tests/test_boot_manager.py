from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Mapping, cast

import pytest

from src.boot import BootManager
from src.setup.orchestrator import SetupOrchestrator, SetupStage
from src.setup.plugins import PluginManager
from src.setup.recipes import Recipe, RecipeLoader
from src.telemetry import InMemoryTelemetryStorage, TelemetryClient, TelemetryEventType
from src.telemetry.consent import ConsentDecision, TelemetryConsentManager


class DummyRecipeLoader(RecipeLoader):
    def __init__(self, recipe: Recipe | None = None) -> None:
        super().__init__(search_paths=[])
        self._recipe = recipe or Recipe(name="test")
        self.loaded: list[str | Path | None] = []

    def load(
        self,
        identifier: str | Path | None,
        *,
        overrides: Mapping[str, object] | None = None,
    ) -> Recipe:
        self.loaded.append(identifier)
        return self._recipe


class DummyConsentManager(TelemetryConsentManager):
    def __init__(self, *, granted: bool = True) -> None:
        super().__init__(storage_path=None)
        self.granted = granted
        self.calls = 0

    def ensure_opt_in(
        self, *, default: Literal["deny", "allow"] = "deny"
    ) -> ConsentDecision:
        self.calls += 1
        return ConsentDecision(granted=self.granted, source="test")


class DummyOrchestrator(SetupOrchestrator):
    def __init__(self) -> None:
        super().__init__(root=Path.cwd(), plugin_manager=PluginManager())
        self.last_run: dict[str, object] | None = None

    def run(
        self,
        recipe,
        *,
        stages=None,
        task_names=None,
        load_plugins=True,
    ):
        self.last_run = {
            "recipe": recipe,
            "stages": stages,
            "task_names": task_names,
            "load_plugins": load_plugins,
        }
        return []


@pytest.fixture()
def manifest(tmp_path: Path) -> Path:
    data = {
        "profiles": {
            "default": {
                "orchestrator": {"stages": ["verification"], "load_plugins": False},
                "preload": {"modules": ["pkg.module"], "callables": ["pkg:preload"]},
                "recovery": {"dashboard": {"mode": "json"}},
            }
        }
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture()
def telemetry_client() -> TelemetryClient:
    storage = InMemoryTelemetryStorage()
    state = {"current": 1_000.0}

    def clock() -> float:
        state["current"] += 1.0
        return state["current"]

    return TelemetryClient(storage, clock=clock)


def _stub_app():
    return SimpleNamespace(run=lambda: None)


def test_boot_manager_invokes_preload(
    monkeypatch: pytest.MonkeyPatch, manifest: Path, telemetry_client: TelemetryClient
) -> None:
    calls: list[tuple[list[str], list[str]]] = []

    def fake_preload(self, *, modules, callables):
        calls.append((list(modules), list(callables)))

    monkeypatch.setattr(BootManager, "_preload_components", fake_preload)
    loader = DummyRecipeLoader()
    manager = BootManager(
        manifest_path=manifest,
        app_factory=_stub_app,
        orchestrator_factory=DummyOrchestrator,
        recipe_loader=loader,
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=DummyConsentManager(),
    )
    manager.run([])
    assert calls
    modules, callables = calls[0]
    assert modules == ["pkg.module"]
    assert callables == ["pkg:preload"]


def test_boot_manager_skips_preload_when_debug(
    monkeypatch: pytest.MonkeyPatch, manifest: Path, telemetry_client: TelemetryClient
) -> None:
    calls = 0

    def fake_preload(self, *, modules, callables):
        nonlocal calls
        calls += 1

    monkeypatch.setattr(BootManager, "_preload_components", fake_preload)
    loader = DummyRecipeLoader()
    manager = BootManager(
        manifest_path=manifest,
        app_factory=_stub_app,
        orchestrator_factory=DummyOrchestrator,
        recipe_loader=loader,
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=DummyConsentManager(),
    )
    manager.run(["--debug"])
    assert calls == 0


def test_boot_manager_passes_manifest_stages(
    monkeypatch: pytest.MonkeyPatch, manifest: Path, telemetry_client: TelemetryClient
) -> None:
    loader = DummyRecipeLoader()
    manager = BootManager(
        manifest_path=manifest,
        app_factory=_stub_app,
        orchestrator_factory=DummyOrchestrator,
        recipe_loader=loader,
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=DummyConsentManager(),
    )
    manager.run([])
    orchestrator = cast(DummyOrchestrator, manager.orchestrator)
    assert orchestrator.last_run is not None
    assert orchestrator.last_run["stages"] == [SetupStage.VERIFICATION]
    assert orchestrator.last_run["load_plugins"] is False


def test_boot_manager_fallback_to_console(
    monkeypatch: pytest.MonkeyPatch, manifest: Path, telemetry_client: TelemetryClient
) -> None:
    events: list[str] = []

    class DashboardStub:
        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

        def handle_event(self, event):
            events.append(event.message)

    monkeypatch.setattr("src.boot.manager.create_dashboard", lambda *_, **__: DashboardStub())
    loader = DummyRecipeLoader()

    def failing_app():
        class _App:
            def run(self):
                raise RuntimeError("boom")

        return _App()

    manager = BootManager(
        manifest_path=manifest,
        app_factory=failing_app,
        orchestrator_factory=DummyOrchestrator,
        recipe_loader=loader,
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=DummyConsentManager(),
    )
    manager.run([])
    assert events[0] == "start"
    assert events[-1] == "stop"
    assert any("GUI failed" in msg for msg in events if isinstance(msg, str))


def test_boot_manager_unknown_profile_raises(
    manifest: Path, telemetry_client: TelemetryClient
) -> None:
    manager = BootManager(
        manifest_path=manifest,
        app_factory=_stub_app,
        orchestrator_factory=DummyOrchestrator,
        recipe_loader=DummyRecipeLoader(),
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=DummyConsentManager(),
    )
    with pytest.raises(ValueError):
        manager.run(["--profile", "missing"])


def test_boot_manager_emits_environment_telemetry(
    manifest: Path, telemetry_client: TelemetryClient
) -> None:
    manager = BootManager(
        manifest_path=manifest,
        app_factory=_stub_app,
        orchestrator_factory=DummyOrchestrator,
        recipe_loader=DummyRecipeLoader(),
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=DummyConsentManager(),
    )
    manager.run([])
    storage = cast(InMemoryTelemetryStorage, telemetry_client.storage)
    env_events = [
        event for event in storage.events if event.type is TelemetryEventType.ENVIRONMENT
    ]
    assert env_events
    assert env_events[0].metadata["profile"] == "default"


def test_boot_manager_disables_telemetry_when_opt_out(
    manifest: Path, telemetry_client: TelemetryClient
) -> None:
    manager = BootManager(
        manifest_path=manifest,
        app_factory=_stub_app,
        orchestrator_factory=DummyOrchestrator,
        recipe_loader=DummyRecipeLoader(),
        dependency_checker=lambda root: False,
        telemetry=telemetry_client,
        consent_manager=DummyConsentManager(granted=False),
    )
    manager.run([])
    storage = cast(InMemoryTelemetryStorage, telemetry_client.storage)
    assert not storage.events

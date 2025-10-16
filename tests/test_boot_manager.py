import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.boot import BootManager
from src.setup.orchestrator import SetupStage
from src.telemetry import InMemoryTelemetryStorage, TelemetryClient, TelemetryEventType


class DummyRecipe:
    def __init__(self, name: str = "test") -> None:
        self.name = name
        self.data: dict[str, object] = {}

    @property
    def config(self) -> dict[str, object]:
        return {}

    def stage_config(self, stage: str | SetupStage) -> dict[str, object]:
        return {}


class DummyRecipeLoader:
    def __init__(self, recipe: DummyRecipe | None = None) -> None:
        self._recipe = recipe or DummyRecipe()
        self.loaded: list[str | None] = []

    def load(self, identifier: str | None) -> DummyRecipe:
        self.loaded.append(identifier)
        return self._recipe


class DummyPluginManager:
    def iter_progress_columns(self):  # pragma: no cover - interface stub
        return ()

    def load_entrypoints(self, orchestrator):  # pragma: no cover - interface stub
        return None


class DummyConsentManager:
    def __init__(self, *, granted: bool = True) -> None:
        self.granted = granted
        self.calls = 0

    def ensure_opt_in(self):
        self.calls += 1
        return SimpleNamespace(granted=self.granted, source="test")


class DummyOrchestrator:
    def __init__(self) -> None:
        self._tasks: dict[str, object] = {}
        self.plugin_manager = DummyPluginManager()
        self.logger = logging.getLogger("dummy.orchestrator")
        self.stage_order = tuple()
        self.last_run: dict[str, object] | None = None

    def register_task(self, task) -> None:
        self._tasks[task.name] = task

    def register_tasks(self, tasks) -> None:  # pragma: no cover - convenience
        for task in tasks:
            self.register_task(task)

    @property
    def tasks(self) -> dict[str, object]:  # pragma: no cover - accessed by boot manager
        return dict(self._tasks)

    def run(self, recipe, *, stages=None, task_names=None, load_plugins=True):
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

    def clock() -> float:
        clock.current += 1.0
        return clock.current

    clock.current = 1000.0  # type: ignore[attr-defined]
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
    assert manager.orchestrator.last_run is not None
    assert manager.orchestrator.last_run["stages"] == [SetupStage.VERIFICATION]
    assert manager.orchestrator.last_run["load_plugins"] is False


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
    env_events = [
        event for event in telemetry_client.storage.events if event.type is TelemetryEventType.ENVIRONMENT
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
    assert not telemetry_client.storage.events

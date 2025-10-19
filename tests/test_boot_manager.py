from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Mapping, cast

import pytest

from coolbox.boot import BootManager
from coolbox.plugins import (
    PluginCapabilities,
    PluginDefinition,
    PluginDevSettings,
    PluginIOSchema,
    ResourceBudget,
    RuntimeConfiguration,
    StartupHooks,
)
from coolbox.plugins.runtime import PluginRuntimeManager
from coolbox.setup.orchestrator import SetupOrchestrator, SetupStage
from coolbox.setup.plugins import PluginManager
from coolbox.setup.recipes import Recipe, RecipeLoader
from coolbox.telemetry import InMemoryTelemetryStorage, TelemetryClient, TelemetryEventType
from coolbox.telemetry.consent import ConsentDecision, TelemetryConsentManager
from coolbox.plugins.worker import PluginStartupError


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
        plugins=None,
        dev=None,
    ):
        self.last_run = {
            "recipe": recipe,
            "stages": stages,
            "task_names": task_names,
            "plugins": plugins,
            "dev": dev,
        }
        return []


@pytest.fixture()
def manifest(tmp_path: Path) -> Path:
    data = {
        "profiles": {
            "default": {
                "orchestrator": {"stages": ["verification"], "load_plugins": False},
                "plugins": [
                    {
                        "id": "test-plugin",
                        "description": "Test plugin",
                        "runtime": {
                            "kind": "native",
                            "entrypoint": "coolbox.setup.plugins:NullPlugin",
                            "environment": {},
                            "features": [],
                        },
                        "capabilities": {
                            "provides": [],
                            "requires": [],
                            "sandbox": ["native"],
                        },
                        "io": {
                            "inputs": {},
                            "outputs": {},
                        },
                        "resources": {
                            "cpu": "1",
                            "memory": "16Mi",
                            "disk": "16Mi",
                            "gpu": "0",
                            "timeout": 5,
                        },
                        "hooks": {
                            "before": [],
                            "after": [],
                            "on_failure": [],
                        },
                        "dev": {
                            "hot_reload": False,
                            "watch": [],
                            "locales": [],
                        },
                    }
                ],
                "preload": {"modules": ["pkg.module"], "callables": ["pkg:preload"]},
                "recovery": {"dashboard": {"mode": "json"}},
                "dev": {"hot_reload": False, "watch": [], "locales": []},
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


class _StubPermissionManager:
    def __init__(self) -> None:
        self.registrations: list[tuple[str, tuple[str, ...]]] = []
        self.unregistered: list[str] = []
        self.supervisor = None

    def bind_supervisor(self, supervisor) -> None:
        self.supervisor = supervisor

    def register_worker(
        self,
        plugin_id: str,
        *,
        display_name: str | None = None,
        provides=(),
        requires=(),
        sandbox=(),
    ) -> None:
        ordered = tuple(sorted(dict.fromkeys(sandbox)))
        self.registrations.append((plugin_id, ordered))

    def unregister_worker(self, plugin_id: str) -> None:
        self.unregistered.append(plugin_id)


class _StubSupervisor:
    def __init__(self) -> None:
        self.register_calls: list[tuple[str, tuple[str, ...]]] = []

    def register(
        self,
        plugin_id,
        plugin,
        definition,
        *,
        logger=None,
        runtime_activation=None,
    ) -> None:
        sandbox = tuple(definition.capabilities.sandbox)
        self.register_calls.append((plugin_id, sandbox))

    def unregister(self, plugin_id: str) -> None:  # pragma: no cover - noop cleanup
        return None

    def clear(self) -> None:  # pragma: no cover - noop cleanup
        return None

    def metrics_snapshot(self):  # pragma: no cover - not relevant to test
        return {}


class _StubRuntimeManager(PluginRuntimeManager):
    runtime_kind = "native"

    class _Worker:
        def __init__(self) -> None:
            self.plugin = _StubRuntimeManager._Worker._Plugin()
            self.runtime_activation = None

        class _Plugin:
            name = "stub"

            def register(self, registrar) -> None:  # pragma: no cover - noop
                return None

        def reload(self):  # pragma: no cover - noop
            return self.plugin

        def shutdown(self) -> None:  # pragma: no cover - noop
            return None

    def supports(self, definition) -> bool:  # pragma: no cover - align with base logic
        return True

    def create_worker(self, definition, *, logger=None):  # type: ignore[override]
        return self._Worker()


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
    assert orchestrator.last_run["plugins"] == ()


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

    monkeypatch.setattr("coolbox.boot.manager.create_dashboard", lambda *_, **__: DashboardStub())
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


def test_boot_manager_switches_to_recovery_on_plugin_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_data = {
        "profiles": {
            "default": {
                "orchestrator": {"recipe": "demo"},
                "preload": {},
                "recovery": {"dashboard": {"mode": "json"}},
                "plugins": [
                    {
                        "id": "fixtures.crash",
                        "runtime": {
                            "kind": "native",
                            "entrypoint": "tests.fixtures.plugins:CrashPlugin",
                        },
                        "capabilities": {
                            "provides": [],
                            "requires": [],
                            "sandbox": [],
                        },
                        "io": {"inputs": {}, "outputs": {}},
                        "resources": {
                            "cpu": "50%",
                            "memory": "32M",
                            "disk": None,
                            "gpu": None,
                            "timeout": 5,
                        },
                        "hooks": {"before": [], "after": [], "on_failure": []},
                        "dev": {"hot_reload": False, "watch": [], "locales": []},
                    }
                ],
                "dev": {"hot_reload": False, "watch": [], "locales": []},
                "recovery_profile": "recovery",
            },
            "recovery": {
                "orchestrator": {"recipe": "recovery"},
                "preload": {},
                "recovery": {"hints": ["baseline recovery"]},
                "plugins": [],
                "dev": {"hot_reload": False, "watch": [], "locales": []},
            },
        }
    }
    manifest_path = tmp_path / "crash_manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    fallback_calls = []

    def fake_fallback(self, exc, profile):
        fallback_calls.append((exc, profile))

    monkeypatch.setattr(BootManager, "_fallback_to_console", fake_fallback)

    storage = InMemoryTelemetryStorage()
    telemetry = TelemetryClient(storage)

    manager = BootManager(
        manifest_path=manifest_path,
        app_factory=_stub_app,
        orchestrator_factory=SetupOrchestrator,
        recipe_loader=DummyRecipeLoader(),
        dependency_checker=lambda root: False,
        telemetry=telemetry,
        consent_manager=DummyConsentManager(),
    )

    manager.run([])

    assert fallback_calls, "expected recovery fallback to trigger"
    error, profile = fallback_calls[0]
    assert isinstance(error, PluginStartupError)
    assert profile.name == "recovery"
    hints = profile.recovery.get("hints", []) if isinstance(profile.recovery, Mapping) else []
    assert any("fixtures.crash" in str(hint) for hint in hints)


def test_manifest_scopes_propagated_to_supervisor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    permission_manager = _StubPermissionManager()
    supervisor = _StubSupervisor()
    monkeypatch.setattr("coolbox.setup.plugins.get_permission_manager", lambda: permission_manager)
    monkeypatch.setattr("coolbox.setup.plugins.WorkerSupervisor", lambda: supervisor)

    orchestrator = SetupOrchestrator(root=tmp_path)
    orchestrator.plugin_manager._runtime_managers = (_StubRuntimeManager(),)

    definition = PluginDefinition(
        identifier="demo",
        runtime=RuntimeConfiguration(
            kind="native", entrypoint="coolbox.setup.plugins:NullPlugin"
        ),
        capabilities=PluginCapabilities(
            provides=("setup.remediation",),
            requires=("network",),
            sandbox=("filesystem", "network"),
        ),
        io=PluginIOSchema(inputs={}, outputs={}),
        resources=ResourceBudget(cpu=None, memory=None, disk=None, gpu=None, timeout=None),
        hooks=StartupHooks(before=(), after=(), on_failure=()),
        dev=PluginDevSettings(hot_reload=False, watch_paths=(), locales=()),
        description="stub",
        version="0",
    )

    orchestrator.plugin_manager.load_from_manifest(orchestrator, [definition])

    assert supervisor.register_calls == [("demo", ("filesystem", "network"))]
    assert permission_manager.registrations == [("demo", ("filesystem", "network"))]

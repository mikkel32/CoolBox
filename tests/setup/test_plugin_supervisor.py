from __future__ import annotations

import json
import pytest

from coolbox.plugins.manifest import (
    PluginCapabilities,
    PluginDefinition,
    PluginDevSettings,
    PluginIOSchema,
    ResourceBudget,
    RuntimeConfiguration,
    StartupHooks,
)
from coolbox.plugins.worker import PluginStartupError
from coolbox.setup.orchestrator import Recipe, SetupOrchestrator, SetupStage, StageContext
from coolbox.setup.plugins import PluginManager
from coolbox.telemetry.client import TelemetryClient
from coolbox.telemetry.events import TelemetryEventType
from coolbox.telemetry.storage import InMemoryTelemetryStorage

from tests.fixtures.plugins import SlowPlugin


def _definition(identifier: str, *, timeout: int = 0) -> PluginDefinition:
    return PluginDefinition(
        identifier=identifier,
        runtime=RuntimeConfiguration(kind="native", entrypoint="tests.fixtures.plugins:SlowPlugin"),
        capabilities=PluginCapabilities(provides=(), requires=(), sandbox=()),
        io=PluginIOSchema(inputs={}, outputs={}),
        resources=ResourceBudget(cpu="10%", memory="1M", disk=None, gpu=None, timeout=timeout),
        hooks=StartupHooks(before=(), after=(), on_failure=()),
        dev=PluginDevSettings(hot_reload=False, watch_paths=(), locales=()),
        description=None,
    )


def _orchestrator(tmp_path, telemetry: TelemetryClient | None = None) -> SetupOrchestrator:
    manager = PluginManager()
    orchestrator = SetupOrchestrator(root=tmp_path, plugin_manager=manager)
    if telemetry is not None:
        orchestrator.attach_telemetry(telemetry)
    return orchestrator


def test_supervisor_enforces_wall_time_budget(tmp_path):
    storage = InMemoryTelemetryStorage()
    telemetry = TelemetryClient(storage)
    orchestrator = _orchestrator(tmp_path, telemetry)
    manager = orchestrator.plugin_manager
    definition = _definition("fixtures.slow", timeout=0)
    plugin = SlowPlugin(delay=0.05)
    manager.register_plugin(plugin, orchestrator, plugin_id=definition.identifier, definition=definition)

    context = StageContext(root=tmp_path, recipe=Recipe(name="demo", data={}), orchestrator=orchestrator)

    with pytest.raises(PluginStartupError):
        manager.dispatch_before_stage(SetupStage.PREFLIGHT, context)

    assert manager.is_disabled(definition.identifier)
    plugin_events = [event for event in storage.events if event.type is TelemetryEventType.PLUGIN]
    assert plugin_events, "expected plugin telemetry event"
    metadata = plugin_events[0].metadata
    assert metadata["plugin"] == definition.identifier
    assert metadata.get("fatal") is True or metadata.get("fatal") is False


def test_violation_details_serialisable(tmp_path):
    storage = InMemoryTelemetryStorage()
    telemetry = TelemetryClient(storage)
    orchestrator = _orchestrator(tmp_path, telemetry)
    manager = orchestrator.plugin_manager
    definition = _definition("fixtures.slow", timeout=0)
    manager.register_plugin(SlowPlugin(delay=0.02), orchestrator, plugin_id=definition.identifier, definition=definition)
    context = StageContext(root=tmp_path, recipe=Recipe(name="demo", data={}), orchestrator=orchestrator)

    with pytest.raises(PluginStartupError):
        manager.dispatch_before_stage(SetupStage.PREFLIGHT, context)

    violations = manager.pop_violations()
    assert violations and violations[0].plugin == definition.identifier
    payload = violations[0].diagnostics.telemetry_payload if violations[0].diagnostics else {}
    # ensure diagnostics payload can be serialized to JSON for persistence
    json.dumps(payload)

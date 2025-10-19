from __future__ import annotations

from coolbox.console.events import LogEvent, TaskEvent
from coolbox.setup.orchestrator import (
    SetupOrchestrator,
    SetupResult,
    SetupStage,
    SetupStatus,
    StageContext,
)
from coolbox.setup.plugins import AdaptiveRemediationPlugin, PluginManager
from coolbox.setup.recipes import Recipe
from coolbox.telemetry.events import TelemetryEvent, TelemetryEventType
from coolbox.telemetry.knowledge import TelemetryKnowledgeBase


def _prime_knowledge() -> TelemetryKnowledgeBase:
    knowledge = TelemetryKnowledgeBase()
    knowledge.observe(
        TelemetryEvent(
            TelemetryEventType.TASK,
            metadata={
                "status": "failed",
                "failure_code": "preflight:demo:RuntimeError",
                "stage": "preflight",
                "task": "demo",
                "error_type": "RuntimeError",
                "suggested_remediation": {
                    "title": "Install dependencies",
                    "commands": ["pip install coolbox-deps"],
                    "config_patches": [{"path": "env.debug", "value": True}],
                    "task_overrides": [
                        {"task": "install", "parameters": {"force": True}}
                    ],
                    "confidence": 0.85,
                    "retry": True,
                },
            },
        )
    )
    return knowledge


def _failed_result(
    failure_code: str = "preflight:demo:RuntimeError",
    *,
    error: Exception | None = None,
) -> SetupResult:
    if error is None:
        error = RuntimeError("boom")
    return SetupResult(
        task="demo",
        stage=SetupStage.PREFLIGHT,
        status=SetupStatus.FAILED,
        payload={"failure_code": failure_code},
        error=error,
    )


def _stage_context(orchestrator: SetupOrchestrator) -> StageContext:
    recipe = Recipe(name="demo")
    return StageContext(root=orchestrator.root, recipe=recipe, orchestrator=orchestrator)


def test_validator_chooses_knowledge_driven_plan(tmp_path) -> None:
    knowledge = _prime_knowledge()
    manager = PluginManager()
    orchestrator = SetupOrchestrator(root=tmp_path, plugin_manager=manager)
    plugin = AdaptiveRemediationPlugin(knowledge)
    manager.register_plugin(plugin, orchestrator)
    context = _stage_context(orchestrator)
    result = _failed_result()

    validator = next(iter(manager.iter_continuous_validators()))
    decision = validator(result, context)

    assert decision is not None
    assert decision.retry is True
    assert "Install dependencies" in decision.reason
    assert decision.repairs


def test_remediation_action_updates_context(tmp_path) -> None:
    knowledge = _prime_knowledge()
    manager = PluginManager()
    orchestrator = SetupOrchestrator(root=tmp_path, plugin_manager=manager)
    plugin = AdaptiveRemediationPlugin(knowledge)
    manager.register_plugin(plugin, orchestrator)
    context = _stage_context(orchestrator)
    result = _failed_result()
    validator = next(iter(manager.iter_continuous_validators()))
    decision = validator(result, context)
    assert decision is not None

    action = decision.repairs[0]
    remediation_result = action(context, result)
    assert remediation_result is not None
    context.results[remediation_result.task] = remediation_result

    bucket = context.state["adaptive_remediation"]
    assert bucket["commands"] == ["pip install coolbox-deps"]
    assert bucket["config_patches"][0]["path"] == "env.debug"
    assert bucket["task_overrides"]["install"]["force"] is True
    assert remediation_result.payload["suggested_remediation"]["title"] == "Install dependencies"
    assert remediation_result.payload["applied"]["stage"] == "preflight"


def test_plugin_emits_diagnostic_events(tmp_path) -> None:
    knowledge = _prime_knowledge()
    manager = PluginManager()
    orchestrator = SetupOrchestrator(root=tmp_path, plugin_manager=manager)
    plugin = AdaptiveRemediationPlugin(knowledge)
    manager.register_plugin(plugin, orchestrator)
    context = _stage_context(orchestrator)
    captured: list = []
    orchestrator.subscribe(captured.append)

    result = _failed_result()
    validator = next(iter(manager.iter_continuous_validators()))
    decision = validator(result, context)
    assert decision is not None

    action = decision.repairs[0]
    remediation_result = action(context, result)
    assert remediation_result is not None

    task_events = [event for event in captured if isinstance(event, TaskEvent)]
    log_events = [event for event in captured if isinstance(event, LogEvent)]
    assert any(event.status == "remediation" for event in task_events)
    assert any(event.status == "remediation-applied" for event in task_events)
    assert any("confidence" in event.payload for event in log_events)
    assert all(event.payload.get("stage") == "preflight" for event in task_events)


def test_validator_recovers_from_unseen_failure_code(tmp_path) -> None:
    knowledge = _prime_knowledge()
    manager = PluginManager()
    orchestrator = SetupOrchestrator(root=tmp_path, plugin_manager=manager)
    plugin = AdaptiveRemediationPlugin(knowledge)
    manager.register_plugin(plugin, orchestrator)
    context = _stage_context(orchestrator)

    result = _failed_result(
        "preflight:demo:ValueError",
        error=ValueError("different"),
    )

    validator = next(iter(manager.iter_continuous_validators()))
    decision = validator(result, context)

    assert decision is not None
    assert decision.retry is True
    assert decision.repairs
    assert "Install dependencies" in decision.reason

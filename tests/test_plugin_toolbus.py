import asyncio
import json

from coolbox.plugins.manifest import (
    PluginCapabilities,
    PluginDefinition,
    PluginDevSettings,
    PluginIOSchema,
    ResourceBudget,
    RuntimeConfiguration,
    StartupHooks,
    ToolBusDeclaration,
)
from coolbox.proto import toolbus_pb2
from coolbox.setup.orchestrator import SetupOrchestrator
from coolbox.setup.plugins import PluginRegistrar, SetupPlugin
from coolbox.setup.plugins.adaptive_remediation import AdaptiveRemediationPlugin
from coolbox.telemetry.knowledge import RemediationSuggestion, TelemetryKnowledgeBase


class DummyPlugin(SetupPlugin):
    name = "dummy"

    def __init__(self) -> None:
        self.invocations: list[dict[str, object]] = []

    def register(self, registrar: PluginRegistrar) -> None:  # type: ignore[override]
        return

    def before_stage(self, stage, context) -> None:  # pragma: no cover - unused
        return

    def after_stage(self, stage, results, context) -> None:  # pragma: no cover - unused
        return

    def before_task(self, task, context) -> None:  # pragma: no cover - unused
        return

    def after_task(self, result, context) -> None:  # pragma: no cover - unused
        return

    def on_error(self, task, error, context) -> None:  # pragma: no cover - unused
        return

    def handle(self, context, payload: bytes) -> dict[str, object]:
        data = json.loads(payload.decode("utf-8"))
        self.invocations.append(data)
        return {"handled": True, "payload": data}


def test_plugin_manager_registers_toolbus_endpoints(tmp_path):
    async def runner():
        orchestrator = SetupOrchestrator(root=tmp_path)
        plugin = DummyPlugin()
        definition = PluginDefinition(
            identifier="dummy",
            runtime=RuntimeConfiguration(kind="native"),
            capabilities=PluginCapabilities(provides=(), requires=(), sandbox=()),
            io=PluginIOSchema(inputs={}, outputs={}),
            resources=ResourceBudget(cpu=None, memory=None, disk=None, gpu=None, timeout=None),
            hooks=StartupHooks(before=(), after=(), on_failure=()),
            dev=PluginDevSettings(hot_reload=False, watch_paths=(), locales=()),
            description=None,
            toolbus=ToolBusDeclaration(
                invoke={"tools.dummy": "handle"},
                stream={},
                subscribe={},
            ),
        )
        orchestrator.plugin_manager.register_plugin(plugin, orchestrator, definition=definition)
        request = toolbus_pb2.InvokeRequest(
            header=toolbus_pb2.Header(request_id="req", tool="tools.dummy"),
            payload=json.dumps({"message": "hi"}).encode("utf-8"),
        )
        response = await orchestrator.tool_bus.invoke(request)
        assert response.status == toolbus_pb2.StatusCode.STATUS_OK
        assert plugin.invocations == [{"message": "hi"}]

    asyncio.run(runner())


class _StubKnowledgeBase(TelemetryKnowledgeBase):
    def __init__(self, suggestion: RemediationSuggestion) -> None:
        super().__init__()
        self.suggestion = suggestion
        self.calls: list[dict[str, object]] = []

    def suggest_fix(
        self,
        *,
        failure_code: str | None = None,
        error_type: str | None = None,
        stage: str | None = None,
        task: str | None = None,
    ) -> RemediationSuggestion | None:
        self.calls.append(
            {
                "failure_code": failure_code,
                "error_type": error_type,
                "stage": stage,
                "task": task,
            }
        )
        return self.suggestion


def test_adaptive_remediation_toolbus_endpoint(tmp_path):
    async def runner():
        orchestrator = SetupOrchestrator(root=tmp_path)
        knowledge = _StubKnowledgeBase(
            RemediationSuggestion(
                title="Fix Connectivity",
                commands=("restart-service",),
                confidence=0.75,
                retry=False,
            )
        )
        plugin = AdaptiveRemediationPlugin(knowledge_base=knowledge)
        orchestrator.plugin_manager.register_plugin(plugin, orchestrator)
        payload = json.dumps(
            {
                "failure_code": "stage.task:Error",
                "error_type": "Error",
                "stage": "preflight",
                "task": "diagnostics",
            }
        ).encode("utf-8")
        request = toolbus_pb2.InvokeRequest(
            header=toolbus_pb2.Header(
                request_id="req-1",
                tool="setup.remediation.suggest",
            ),
            payload=payload,
        )
        response = await orchestrator.tool_bus.invoke(request)
        assert response.status == toolbus_pb2.StatusCode.STATUS_OK
        body = json.loads(response.payload.decode("utf-8"))
        assert body["suggestion"]["title"] == "Fix Connectivity"
        assert knowledge.calls

    asyncio.run(runner())

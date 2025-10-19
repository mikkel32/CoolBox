"""Plugin interfaces for the CoolBox setup orchestrator."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from importlib import metadata
import inspect
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Protocol, Sequence, TYPE_CHECKING, cast, runtime_checkable

from coolbox.plugins import PluginDefinition, ProfileDevSettings
from coolbox.catalog import get_catalog
from coolbox.plugins.hotreload import HotReloadController
from coolbox.plugins.runtime import (
    NativeRuntimeManager,
    PluginRuntimeManager,
    PluginWorker,
    WasmRuntimeManager,
)
from coolbox.plugins.worker import (
    PluginMetricsSnapshot,
    PluginRuntimeError,
    PluginSandboxError,
    PluginStartupError,
    WorkerDiagnostics,
    WorkerSupervisor,
)
from coolbox.plugins.update import PluginChannelUpdater
from coolbox.tools import ToolBus, ToolEndpoint
from coolbox.paths import artifacts_dir, ensure_directory
from coolbox.utils.security.permissions import get_permission_manager

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..orchestrator import SetupOrchestrator, SetupResult, SetupStage, StageContext
    from ..orchestrator import SetupTask


ENTRYPOINT_GROUP = "coolbox.setup"


Validator = Callable[["SetupResult", "StageContext"], None]
Reporter = Callable[[Sequence["SetupResult"], "StageContext"], None]
ProgressColumnFactory = Callable[["StageContext"], Any]
RemediationAction = Callable[["StageContext", "SetupResult"], Optional["SetupResult"]]


@dataclass
class ValidatorDecision:
    """Decision returned by continuous validators."""

    name: str
    reason: str
    repairs: Sequence[RemediationAction] = ()
    rollbacks: Sequence[RemediationAction] = ()
    retry: bool = False


ContinuousValidator = Callable[["SetupResult", "StageContext"], Optional[ValidatorDecision]]


@runtime_checkable
class SetupPlugin(Protocol):
    """Protocol for setup orchestrator plugins."""

    name: str

    def register(self, registrar: "PluginRegistrar") -> None:
        """Register tasks or hooks with the orchestrator."""

    def before_stage(self, stage: "SetupStage", context: "StageContext") -> None:
        """Called immediately before a stage runs."""

    def after_stage(self, stage: "SetupStage", results: Sequence["SetupResult"], context: "StageContext") -> None:
        """Called after a stage completes."""

    def before_task(self, task: "SetupTask", context: "StageContext") -> None:
        """Called immediately before an individual task executes."""

    def after_task(self, result: "SetupResult", context: "StageContext") -> None:
        """Called right after an individual task finishes."""

    def on_error(self, task: "SetupTask", error: BaseException, context: "StageContext") -> None:
        """Called when a task raises an exception."""


class NullPlugin:
    """Fallback plugin with no-op handlers."""

    name = "null"

    def register(self, registrar: "PluginRegistrar") -> None:  # pragma: no cover - trivial
        return

    def before_stage(self, stage: "SetupStage", context: "StageContext") -> None:  # pragma: no cover - trivial
        return

    def after_stage(self, stage: "SetupStage", results: Sequence["SetupResult"], context: "StageContext") -> None:  # pragma: no cover - trivial
        return

    def before_task(self, task: "SetupTask", context: "StageContext") -> None:  # pragma: no cover - trivial
        return

    def after_task(self, result: "SetupResult", context: "StageContext") -> None:  # pragma: no cover - trivial
        return

    def on_error(self, task: "SetupTask", error: BaseException, context: "StageContext") -> None:  # pragma: no cover - trivial
        return


@dataclass
class PluginHandle:
    """Track plugin metadata and registered callbacks."""

    identifier: str
    plugin: "SetupPlugin"
    definition: PluginDefinition | None
    runtime_manager: PluginRuntimeManager | None
    worker: PluginWorker | None = None
    validators: list[Validator] = field(default_factory=list)
    reporters: list[Reporter] = field(default_factory=list)
    progress_columns: list[ProgressColumnFactory] = field(default_factory=list)
    continuous_validators: list[ContinuousValidator] = field(default_factory=list)
    tool_endpoints: list[str] = field(default_factory=list)
    disabled: bool = False
    last_diagnostics: WorkerDiagnostics | None = None


@dataclass(slots=True)
class PluginViolation:
    """Snapshot of a plugin supervision failure."""

    plugin: str
    reason: str
    diagnostics: WorkerDiagnostics | None
    fatal: bool


@dataclass
class PluginRegistrar:
    """Registration API handed to plugins."""

    orchestrator: "SetupOrchestrator"
    manager: "PluginManager"
    handle: "PluginHandle"
    tool_bus: ToolBus | None = None

    def add_task(self, task: "SetupTask") -> None:
        self.orchestrator.register_task(task)

    def add_validator(self, validator: Validator) -> None:
        self.manager.validators.append(validator)
        self.handle.validators.append(validator)

    def add_reporter(self, reporter: Reporter) -> None:
        self.manager.reporters.append(reporter)
        self.handle.reporters.append(reporter)

    def add_progress_column(self, factory: ProgressColumnFactory) -> None:
        self.manager.progress_columns.append(factory)
        self.handle.progress_columns.append(factory)

    def add_continuous_validator(self, validator: ContinuousValidator) -> None:
        self.manager.continuous_validators.append(validator)
        self.handle.continuous_validators.append(validator)

    def add_tool_endpoint(
        self,
        name: str,
        handler: Callable[[Any, Any], Any],
        *,
        mode: str = "invoke",
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.manager.register_tool_endpoint(
            self.handle,
            name,
            handler,
            mode=mode,
            metadata=metadata,
        )


class PluginManager:
    """Load and manage setup plugins."""

    def __init__(self) -> None:
        self.plugins: list[SetupPlugin] = []
        self.validators: list[Validator] = []
        self.reporters: list[Reporter] = []
        self.progress_columns: list[ProgressColumnFactory] = []
        self.continuous_validators: list[ContinuousValidator] = []
        self._runtime_managers: tuple[PluginRuntimeManager, ...] = (
            NativeRuntimeManager(),
            WasmRuntimeManager(),
        )
        self._handles: Dict[str, PluginHandle] = {}
        self._workers: Dict[str, PluginWorker] = {}
        self._hot_reload: HotReloadController | None = None
        self._manifest_definitions: Dict[str, PluginDefinition] = {}
        self._profile_dev: ProfileDevSettings | None = None
        self._supervisor = WorkerSupervisor()
        self._violations: list[PluginViolation] = []
        self._tool_bus: ToolBus | None = None
        self._tool_endpoint_registry: Dict[str, Dict[str, ToolEndpoint]] = {}
        self._permission_manager = get_permission_manager()
        self._permission_manager.bind_supervisor(self._supervisor)
        self._updater = PluginChannelUpdater()

    def attach_tool_bus(self, bus: ToolBus) -> None:
        """Attach a tool bus to register plugin endpoints with."""

        self._tool_bus = bus

    def plugin_metrics(self) -> Mapping[str, PluginMetricsSnapshot]:
        """Return a snapshot of per-plugin supervisor metrics."""

        return self._supervisor.metrics_snapshot()

    def updater(self) -> PluginChannelUpdater:
        """Expose the plugin channel updater."""

        return self._updater

    def load_entrypoints(self, orchestrator: "SetupOrchestrator", group: str = ENTRYPOINT_GROUP) -> None:
        """Discover plugins via entry points."""

        try:
            entry_points = metadata.entry_points()
        except Exception:  # pragma: no cover - metadata lookup errors are non critical
            return
        for ep in entry_points.select(group=group):
            try:
                plugin_obj = ep.load()
                plugin_instance = plugin_obj() if callable(plugin_obj) else plugin_obj
                plugin = cast(SetupPlugin, plugin_instance)
            except Exception as exc:  # pragma: no cover - defensive
                orchestrator.logger.warning("Failed to load setup plugin %s: %s", ep.name, exc)
                continue
            self.register_plugin(plugin, orchestrator, plugin_id=str(ep.name))

    def register_plugin(
        self,
        plugin: SetupPlugin,
        orchestrator: "SetupOrchestrator",
        *,
        plugin_id: str | None = None,
        definition: PluginDefinition | None = None,
        runtime: PluginRuntimeManager | None = None,
        worker: PluginWorker | None = None,
    ) -> None:
        identifier = plugin_id or getattr(plugin, "name", plugin.__class__.__name__)
        self._remove_handle(identifier)
        handle = PluginHandle(
            identifier=identifier,
            plugin=plugin,
            definition=definition,
            runtime_manager=runtime,
            worker=worker,
        )
        registrar = PluginRegistrar(orchestrator, self, handle, tool_bus=self._tool_bus)
        try:
            plugin.register(registrar)
        except Exception as exc:
            orchestrator.logger.warning("Plugin %s register() failed: %s", getattr(plugin, "name", plugin), exc)
            return
        self._auto_register_toolbus(handle, orchestrator)
        try:
            activation = getattr(worker, "runtime_activation", None)
            self._supervisor.register(
                identifier,
                plugin,
                definition,
                logger=orchestrator.logger,
                runtime_activation=activation,
            )
        except PluginSandboxError as exc:
            orchestrator.logger.warning("Plugin %s sandbox configuration failed: %s", identifier, exc)
            return
        capabilities = definition.capabilities if definition is not None else None
        provides = capabilities.provides if capabilities else ()
        requires = capabilities.requires if capabilities else ()
        sandbox = capabilities.sandbox if capabilities else ()
        display_name = getattr(plugin, "name", identifier)
        self._permission_manager.register_worker(
            identifier,
            display_name=display_name,
            provides=provides,
            requires=requires,
            sandbox=sandbox,
        )
        self.plugins.append(plugin)
        self._handles[identifier] = handle

    def iter_validators(self) -> Iterable[Validator]:
        return list(self.validators)

    def _remove_handle(self, identifier: str) -> None:
        handle = self._handles.pop(identifier, None)
        if handle is None:
            return
        for collection, entries in (
            (self.validators, handle.validators),
            (self.reporters, handle.reporters),
            (self.progress_columns, handle.progress_columns),
            (self.continuous_validators, handle.continuous_validators),
        ):
            for entry in entries:
                try:
                    collection.remove(entry)
                except ValueError:
                    continue
        try:
            self.plugins.remove(handle.plugin)
        except ValueError:
            pass
        handle.validators.clear()
        handle.reporters.clear()
        handle.progress_columns.clear()
        handle.continuous_validators.clear()
        registry = self._tool_endpoint_registry.pop(identifier, None)
        if registry and self._tool_bus:
            for endpoint in registry.values():
                self._tool_bus.unregister(endpoint.name)
        handle.tool_endpoints.clear()
        self._supervisor.unregister(identifier)
        self._permission_manager.unregister_worker(identifier)

    def clear(self) -> None:
        for worker in list(self._workers.values()):
            try:
                worker.shutdown()
            except Exception:  # pragma: no cover - defensive cleanup
                continue
        self._workers.clear()
        for identifier in list(self._handles.keys()):
            self._permission_manager.unregister_worker(identifier)
        if self._tool_bus:
            for registry in self._tool_endpoint_registry.values():
                for endpoint in registry.values():
                    self._tool_bus.unregister(endpoint.name)
        self._tool_endpoint_registry.clear()
        self._handles.clear()
        self.plugins.clear()
        self.validators.clear()
        self.reporters.clear()
        self.progress_columns.clear()
        self.continuous_validators.clear()
        self._manifest_definitions.clear()
        self._profile_dev = None
        if self._hot_reload is not None:
            self._hot_reload.stop()
            self._hot_reload = None
        self._violations.clear()
        self._supervisor.clear()

    def register_tool_endpoint(
        self,
        handle: PluginHandle,
        name: str,
        handler: Callable[[Any, Any], Any],
        *,
        mode: str = "invoke",
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        if self._tool_bus is None:
            raise RuntimeError("Tool bus is not configured")
        registry = self._tool_endpoint_registry.setdefault(handle.identifier, {})
        endpoint = registry.get(name)
        metadata_map = {str(key): str(value) for key, value in (metadata or {}).items()}
        if endpoint is None:
            endpoint = ToolEndpoint(
                name=name,
                source="local",
                metadata=dict(metadata_map),
            )
            self._tool_bus.register_endpoint(endpoint)
            registry[name] = endpoint
            handle.tool_endpoints.append(name)
        elif metadata_map:
            merged = dict(endpoint.metadata)
            merged.update(metadata_map)
            endpoint.metadata = merged
        normalized = self._prepare_handler(handler)
        mode = mode.lower()
        if mode == "invoke":
            endpoint.invoke_handler = normalized
        elif mode == "stream":
            endpoint.stream_handler = normalized
        elif mode == "subscribe":
            endpoint.subscribe_handler = normalized
        else:
            raise ValueError(f"Unsupported endpoint mode: {mode}")

    @staticmethod
    def _prepare_handler(handler: Callable[[Any, Any], Any]) -> Callable[[Any, Any], Any]:
        signature = inspect.signature(handler)
        positional = [
            param
            for param in signature.parameters.values()
            if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(param.kind == param.VAR_POSITIONAL for param in signature.parameters.values())
        if not positional and not has_varargs:
            def wrapper(context: Any, payload: Any) -> Any:
                return handler()

            return wrapper
        if len(positional) == 1 and positional[0].name not in {"context", "ctx"}:
            def wrapper(context: Any, payload: Any) -> Any:
                return handler(payload)

            return wrapper

        def wrapper(context: Any, payload: Any) -> Any:
            return handler(context, payload)

        return wrapper

    def _auto_register_toolbus(self, handle: PluginHandle, orchestrator: "SetupOrchestrator") -> None:
        declaration = handle.definition.toolbus if handle.definition else None
        if declaration is None:
            return
        for name, target in declaration.invoke.items():
            callback = getattr(handle.plugin, target, None)
            if callable(callback):
                self.register_tool_endpoint(handle, name, callback, mode="invoke")
            else:
                orchestrator.logger.warning(
                    "Plugin %s missing invoke handler %s for tool %s",
                    handle.identifier,
                    target,
                    name,
                )
        for name, target in declaration.stream.items():
            callback = getattr(handle.plugin, target, None)
            if callable(callback):
                self.register_tool_endpoint(handle, name, callback, mode="stream")
            else:
                orchestrator.logger.warning(
                    "Plugin %s missing stream handler %s for tool %s",
                    handle.identifier,
                    target,
                    name,
                )
        for name, target in declaration.subscribe.items():
            callback = getattr(handle.plugin, target, None)
            if callable(callback):
                self.register_tool_endpoint(handle, name, callback, mode="subscribe")
            else:
                orchestrator.logger.warning(
                    "Plugin %s missing subscribe handler %s for tool %s",
                    handle.identifier,
                    target,
                    name,
                )

    def iter_reporters(self) -> Iterable[Reporter]:
        return list(self.reporters)

    def iter_progress_columns(self) -> Iterable[ProgressColumnFactory]:
        return list(self.progress_columns)

    def iter_continuous_validators(self) -> Iterable[ContinuousValidator]:
        return list(self.continuous_validators)

    def dispatch_before_stage(self, stage: "SetupStage", context: "StageContext") -> None:
        orchestrator = context.orchestrator
        for handle in list(self._handles.values()):
            if handle.disabled:
                continue
            try:
                self._invoke_plugin(handle, "before_stage", orchestrator, stage, context)
            except PluginStartupError as exc:
                self._record_violation(handle, exc, fatal=True, orchestrator=orchestrator)
                raise
            except PluginRuntimeError as exc:
                self._record_violation(handle, exc, fatal=True, orchestrator=orchestrator)
                raise PluginStartupError(handle.identifier, str(exc), original=exc.original)

    def dispatch_after_stage(self, stage: "SetupStage", results: Sequence["SetupResult"], context: "StageContext") -> None:
        orchestrator = context.orchestrator
        for handle in list(self._handles.values()):
            if handle.disabled:
                continue
            try:
                self._invoke_plugin(handle, "after_stage", orchestrator, stage, results, context)
            except PluginStartupError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)
            except PluginRuntimeError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)

    def dispatch_before_task(self, task: "SetupTask", context: "StageContext") -> None:
        orchestrator = context.orchestrator
        for handle in list(self._handles.values()):
            if handle.disabled:
                continue
            try:
                self._invoke_plugin(handle, "before_task", orchestrator, task, context)
            except PluginStartupError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)
            except PluginRuntimeError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)

    def dispatch_after_task(self, result: "SetupResult", context: "StageContext") -> None:
        orchestrator = context.orchestrator
        for handle in list(self._handles.values()):
            if handle.disabled:
                continue
            try:
                self._invoke_plugin(handle, "after_task", orchestrator, result, context)
            except PluginStartupError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)
            except PluginRuntimeError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)

    def dispatch_error(self, task: "SetupTask", error: BaseException, context: "StageContext") -> None:
        orchestrator = context.orchestrator
        for handle in list(self._handles.values()):
            if handle.disabled:
                continue
            try:
                self._invoke_plugin(handle, "on_error", orchestrator, task, error, context)
            except PluginStartupError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)
            except PluginRuntimeError as exc:
                self._record_violation(handle, exc, fatal=False, orchestrator=orchestrator)

    def _invoke_plugin(
        self,
        handle: PluginHandle,
        method_name: str,
        orchestrator: "SetupOrchestrator",
        *args,
    ) -> None:
        identifier = handle.identifier
        try:
            self._supervisor.call(identifier, method_name, *args)
        except PluginStartupError as exc:
            raise
        except PluginRuntimeError as exc:
            orchestrator.logger.warning(
                "Plugin %s %s failed: %s",
                identifier,
                method_name,
                exc,
            )
            raise

    def _record_violation(
        self,
        handle: PluginHandle,
        error: PluginStartupError | PluginRuntimeError,
        *,
        fatal: bool,
        orchestrator: "SetupOrchestrator",
    ) -> None:
        identifier = handle.identifier
        handle.disabled = True
        diagnostics = getattr(error, "diagnostics", None)
        handle.last_diagnostics = diagnostics
        reason = str(error)
        orchestrator.logger.warning(
            "Disabling plugin %s due to %s",
            identifier,
            reason,
        )
        violation = PluginViolation(
            plugin=identifier,
            reason=reason,
            diagnostics=diagnostics,
            fatal=fatal,
        )
        self._violations.append(violation)
        payload = {
            "plugin": identifier,
            "reason": reason,
            "fatal": fatal,
        }
        if diagnostics is not None:
            payload.update(diagnostics.telemetry_payload)
        telemetry = orchestrator.telemetry
        recorder = getattr(telemetry, "record_plugin", None)
        if callable(recorder):
            recorder(payload)

    def violations(self) -> Sequence[PluginViolation]:
        return tuple(self._violations)

    def pop_violations(self) -> list[PluginViolation]:
        violations, self._violations = self._violations, []
        return violations

    def is_disabled(self, plugin_id: str) -> bool:
        handle = self._handles.get(plugin_id)
        return bool(handle and handle.disabled)

    def load_from_manifest(
        self,
        orchestrator: "SetupOrchestrator",
        definitions: Sequence[PluginDefinition],
        *,
        dev: ProfileDevSettings | None = None,
        profile: str | None = None,
        manifest_path: str | None = None,
    ) -> None:
        self.clear()
        self._profile_dev = dev
        resolved: list[PluginDefinition] = []
        for definition in definitions:
            self._updater.bootstrap(definition)
            resolved_definition = self._updater.resolve_definition(definition.identifier, definition)
            resolved.append(resolved_definition)
        self._manifest_definitions = {definition.identifier: definition for definition in resolved}
        catalog = get_catalog()
        profile_name = profile or "default"
        for definition in resolved:
            try:
                catalog.record_manifest(profile_name, definition, manifest_path=manifest_path)
            except Exception:  # pragma: no cover - persistence best effort
                orchestrator.logger.debug(
                    "Failed to persist plugin manifest metadata",
                    exc_info=True,
                )
            try:
                plugin_root = ensure_directory(artifacts_dir() / "plugins" / definition.identifier)
                manifest_file = plugin_root / "manifest.json"
                payload = {
                    "profile": profile_name,
                    "manifest_path": manifest_path,
                    "definition": {
                        "identifier": definition.identifier,
                        "version": definition.version,
                        "description": definition.description,
                    },
                    "runtime": definition.runtime.kind,
                    "updated_at": time.time(),
                }
                manifest_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            except Exception:  # pragma: no cover - diagnostics best effort
                orchestrator.logger.debug(
                    "Failed to persist plugin manifest artifact",
                    exc_info=True,
                )
            runtime = self._resolve_runtime(definition)
            worker = runtime.create_worker(definition, logger=orchestrator.logger)
            self._workers[definition.identifier] = worker
            self.register_plugin(
                worker.plugin,
                orchestrator,
                plugin_id=definition.identifier,
                definition=definition,
                runtime=runtime,
                worker=worker,
            )
        self._configure_hot_reload(resolved, orchestrator)

    def reload_plugin(self, plugin_id: str, orchestrator: "SetupOrchestrator") -> None:
        definition = self._manifest_definitions.get(plugin_id)
        worker = self._workers.get(plugin_id)
        if definition is None or worker is None:
            return
        handle = self._handles.get(plugin_id)
        runtime = handle.runtime_manager if handle and handle.runtime_manager else self._resolve_runtime(definition)
        try:
            plugin = worker.reload()
        except Exception as exc:  # pragma: no cover - developer diagnostics
            orchestrator.logger.warning("Failed to hot-reload plugin %s: %s", plugin_id, exc)
            return
        self.register_plugin(
            plugin,
            orchestrator,
            plugin_id=plugin_id,
            definition=definition,
            runtime=runtime,
            worker=worker,
        )

    def _resolve_runtime(self, definition: PluginDefinition) -> PluginRuntimeManager:
        for manager in self._runtime_managers:
            if manager.supports(definition):
                return manager
        raise RuntimeError(f"No runtime manager available for plugin '{definition.identifier}' ({definition.runtime.kind})")

    def _configure_hot_reload(
        self,
        definitions: Sequence[PluginDefinition],
        orchestrator: "SetupOrchestrator",
    ) -> None:
        dev = self._profile_dev
        enable_profile = bool(dev and dev.hot_reload)
        any_plugin_hot = enable_profile or any(defn.dev.hot_reload for defn in definitions)
        if not any_plugin_hot:
            if self._hot_reload is not None:
                self._hot_reload.stop()
                self._hot_reload = None
            return
        controller = self._ensure_hot_reload(orchestrator)
        profile_watch = tuple(dev.watch_paths) if dev else ()
        for definition in definitions:
            if not (enable_profile or definition.dev.hot_reload):
                controller.unwatch(definition.identifier)
                continue
            watch_paths = definition.dev.watch_paths or profile_watch
            if watch_paths:
                controller.watch(definition.identifier, watch_paths)
        # ensure callback bound even if no specific watches configured
        controller.set_callback(lambda pid: self.reload_plugin(pid, orchestrator))

    def _ensure_hot_reload(self, orchestrator: "SetupOrchestrator") -> HotReloadController:
        if self._hot_reload is None:
            self._hot_reload = HotReloadController()
        self._hot_reload.set_callback(lambda pid: self.reload_plugin(pid, orchestrator))
        return self._hot_reload


from .adaptive_remediation import AdaptiveRemediationPlugin

__all__ = [
    "PluginManager",
    "PluginRegistrar",
    "SetupPlugin",
    "Validator",
    "Reporter",
    "ProgressColumnFactory",
    "ContinuousValidator",
    "ValidatorDecision",
    "RemediationAction",
    "ENTRYPOINT_GROUP",
    "AdaptiveRemediationPlugin",
    "PluginViolation",
]

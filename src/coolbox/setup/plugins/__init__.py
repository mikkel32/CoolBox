"""Plugin interfaces for the CoolBox setup orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Callable, Dict, Iterable, Optional, Protocol, Sequence, TYPE_CHECKING, cast, runtime_checkable

from coolbox.plugins import PluginDefinition, ProfileDevSettings
from coolbox.plugins.hotreload import HotReloadController
from coolbox.plugins.runtime import (
    NativeRuntimeManager,
    PluginRuntimeManager,
    PluginWorker,
    WasmRuntimeManager,
)
from coolbox.plugins.worker import (
    PluginRuntimeError,
    PluginSandboxError,
    PluginStartupError,
    WorkerDiagnostics,
    WorkerSupervisor,
)

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
        registrar = PluginRegistrar(orchestrator, self, handle)
        try:
            plugin.register(registrar)
        except Exception as exc:
            orchestrator.logger.warning("Plugin %s register() failed: %s", getattr(plugin, "name", plugin), exc)
            return
        try:
            self._supervisor.register(identifier, plugin, definition, logger=orchestrator.logger)
        except PluginSandboxError as exc:
            orchestrator.logger.warning("Plugin %s sandbox configuration failed: %s", identifier, exc)
            return
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
        self._supervisor.unregister(identifier)

    def clear(self) -> None:
        for worker in list(self._workers.values()):
            try:
                worker.shutdown()
            except Exception:  # pragma: no cover - defensive cleanup
                continue
        self._workers.clear()
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
    ) -> None:
        self.clear()
        self._profile_dev = dev
        self._manifest_definitions = {definition.identifier: definition for definition in definitions}
        for definition in definitions:
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
        self._configure_hot_reload(definitions, orchestrator)

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

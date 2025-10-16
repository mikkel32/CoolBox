"""Plugin interfaces for the CoolBox setup orchestrator."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable, Iterable, List, Optional, Protocol, Sequence, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .orchestrator import SetupOrchestrator, SetupResult, SetupStage, StageContext
    from .orchestrator import SetupTask


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
class PluginRegistrar:
    """Registration API handed to plugins."""

    orchestrator: "SetupOrchestrator"
    manager: "PluginManager"

    def add_task(self, task: "SetupTask") -> None:
        self.orchestrator.register_task(task)

    def add_validator(self, validator: Validator) -> None:
        self.manager.validators.append(validator)

    def add_reporter(self, reporter: Reporter) -> None:
        self.manager.reporters.append(reporter)

    def add_progress_column(self, factory: ProgressColumnFactory) -> None:
        self.manager.progress_columns.append(factory)

    def add_continuous_validator(self, validator: ContinuousValidator) -> None:
        self.manager.continuous_validators.append(validator)


class PluginManager:
    """Load and manage setup plugins."""

    def __init__(self) -> None:
        self.plugins: list[SetupPlugin] = []
        self.validators: list[Validator] = []
        self.reporters: list[Reporter] = []
        self.progress_columns: list[ProgressColumnFactory] = []
        self.continuous_validators: list[ContinuousValidator] = []

    def load_entrypoints(self, orchestrator: "SetupOrchestrator", group: str = ENTRYPOINT_GROUP) -> None:
        """Discover plugins via entry points."""

        try:
            entry_points = metadata.entry_points()
        except Exception:  # pragma: no cover - metadata lookup errors are non critical
            return
        for ep in entry_points.select(group=group):
            try:
                plugin_obj = ep.load()
                plugin: SetupPlugin = plugin_obj() if callable(plugin_obj) else plugin_obj
            except Exception as exc:  # pragma: no cover - defensive
                orchestrator.logger.warning("Failed to load setup plugin %s: %s", ep.name, exc)
                continue
            self.register_plugin(plugin, orchestrator)

    def register_plugin(self, plugin: SetupPlugin, orchestrator: "SetupOrchestrator") -> None:
        registrar = PluginRegistrar(orchestrator, self)
        try:
            plugin.register(registrar)
        except Exception as exc:
            orchestrator.logger.warning("Plugin %s register() failed: %s", getattr(plugin, "name", plugin), exc)
            return
        self.plugins.append(plugin)

    def iter_validators(self) -> Iterable[Validator]:
        return list(self.validators)

    def iter_reporters(self) -> Iterable[Reporter]:
        return list(self.reporters)

    def iter_progress_columns(self) -> Iterable[ProgressColumnFactory]:
        return list(self.progress_columns)

    def iter_continuous_validators(self) -> Iterable[ContinuousValidator]:
        return list(self.continuous_validators)

    def dispatch_before_stage(self, stage: "SetupStage", context: "StageContext") -> None:
        for plugin in self.plugins:
            try:
                plugin.before_stage(stage, context)
            except Exception as exc:
                orchestrator = context.orchestrator
                orchestrator.logger.warning("Plugin %s before_stage failed: %s", getattr(plugin, "name", plugin), exc)

    def dispatch_after_stage(self, stage: "SetupStage", results: Sequence["SetupResult"], context: "StageContext") -> None:
        for plugin in self.plugins:
            try:
                plugin.after_stage(stage, results, context)
            except Exception as exc:
                orchestrator = context.orchestrator
                orchestrator.logger.warning("Plugin %s after_stage failed: %s", getattr(plugin, "name", plugin), exc)

    def dispatch_before_task(self, task: "SetupTask", context: "StageContext") -> None:
        for plugin in self.plugins:
            try:
                plugin.before_task(task, context)
            except Exception as exc:
                orchestrator = context.orchestrator
                orchestrator.logger.warning("Plugin %s before_task failed: %s", getattr(plugin, "name", plugin), exc)

    def dispatch_after_task(self, result: "SetupResult", context: "StageContext") -> None:
        for plugin in self.plugins:
            try:
                plugin.after_task(result, context)
            except Exception as exc:
                orchestrator = context.orchestrator
                orchestrator.logger.warning("Plugin %s after_task failed: %s", getattr(plugin, "name", plugin), exc)

    def dispatch_error(self, task: "SetupTask", error: BaseException, context: "StageContext") -> None:
        for plugin in self.plugins:
            try:
                plugin.on_error(task, error, context)
            except Exception as exc:
                orchestrator = context.orchestrator
                orchestrator.logger.warning("Plugin %s on_error failed: %s", getattr(plugin, "name", plugin), exc)


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
]

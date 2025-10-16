"""Core setup orchestrator implementation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging
import time
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence

from .plugins import PluginManager, Validator
from .recipes import Recipe


class SetupStage(Enum):
    """Stages executed by the orchestrator."""

    PREFLIGHT = "preflight"
    DEPENDENCY_RESOLUTION = "dependency-resolution"
    INSTALLERS = "installers"
    VERIFICATION = "verification"
    SUMMARIES = "summaries"


STAGE_ORDER: tuple[SetupStage, ...] = (
    SetupStage.PREFLIGHT,
    SetupStage.DEPENDENCY_RESOLUTION,
    SetupStage.INSTALLERS,
    SetupStage.VERIFICATION,
    SetupStage.SUMMARIES,
)


class SetupStatus(Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class SetupResult:
    """Structured result returned by a stage task."""

    task: str
    stage: SetupStage
    status: SetupStatus
    payload: dict[str, Any] = field(default_factory=dict)
    error: BaseException | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float = field(default_factory=time.time)
    attempts: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "stage": self.stage.value,
            "status": self.status.value,
            "payload": self.payload,
            "error": repr(self.error) if self.error else None,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


TaskAction = Callable[["StageContext"], Optional[Mapping[str, Any]] | Optional[SetupResult]]


@dataclass
class SetupTask:
    """Representation of a runnable setup task."""

    name: str
    stage: SetupStage
    action: TaskAction
    dependencies: Sequence[str] = field(default_factory=tuple)
    allow_fail: bool = False
    max_retries: int = 1


@dataclass
class StageContext:
    """State passed to stage tasks."""

    root: Path
    recipe: Recipe
    orchestrator: "SetupOrchestrator"
    state: MutableMapping[str, Any] = field(default_factory=dict)
    results: MutableMapping[str, SetupResult] = field(default_factory=dict)

    def stage_config(self, stage: SetupStage) -> dict[str, Any]:
        return self.recipe.stage_config(stage)

    def set(self, key: str, value: Any) -> None:
        self.state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def progress_columns(self) -> list[Any]:
        return [factory(self) for factory in self.orchestrator.plugin_manager.iter_progress_columns()]


class SetupOrchestrator:
    """Coordinates the execution of setup stages."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        tasks: Sequence[SetupTask] | None = None,
        plugin_manager: PluginManager | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.root = Path(root or Path.cwd()).resolve()
        self.logger = logger or logging.getLogger("coolbox.setup.orchestrator")
        self._tasks: dict[str, SetupTask] = {}
        self._attempts: dict[str, int] = {}
        self._results: dict[str, SetupResult] = {}
        self._last_recipe: Recipe | None = None
        self.plugin_manager = plugin_manager or PluginManager()
        if tasks:
            for task in tasks:
                self.register_task(task)

    # --- registration -------------------------------------------------
    def register_task(self, task: SetupTask) -> None:
        if task.name in self._tasks:
            raise ValueError(f"Task '{task.name}' already registered")
        self._tasks[task.name] = task

    def register_tasks(self, tasks: Iterable[SetupTask]) -> None:
        for task in tasks:
            self.register_task(task)

    # --- lifecycle ----------------------------------------------------
    @property
    def tasks(self) -> dict[str, SetupTask]:
        return dict(self._tasks)

    @property
    def results(self) -> dict[str, SetupResult]:
        return dict(self._results)

    def run(
        self,
        recipe: Recipe,
        *,
        stages: Sequence[SetupStage] | None = None,
        task_names: Sequence[str] | None = None,
        load_plugins: bool = True,
    ) -> list[SetupResult]:
        if not self._tasks:
            raise RuntimeError("No tasks registered for setup orchestration")
        stage_filter = set(stages or [])
        task_filter = set(task_names or [])
        self._results = {}
        self._attempts = {}
        self._last_recipe = recipe

        context = StageContext(root=self.root, recipe=recipe, orchestrator=self)
        if load_plugins:
            self.plugin_manager.load_entrypoints(self)
        results: list[SetupResult] = []
        for stage in STAGE_ORDER:
            if stage_filter and stage not in stage_filter:
                continue
            stage_tasks = [t for t in self._tasks.values() if t.stage is stage]
            if task_filter:
                stage_tasks = [t for t in stage_tasks if t.name in task_filter]
            if not stage_tasks:
                continue
            stage_results = self._run_stage(stage, stage_tasks, context)
            results.extend(stage_results)
        return results

    def retry(
        self,
        *,
        task_names: Sequence[str] | None = None,
        stages: Sequence[SetupStage] | None = None,
        recipe: Recipe | None = None,
    ) -> list[SetupResult]:
        if self._last_recipe is None and recipe is None:
            raise RuntimeError("No prior recipe run recorded; call run() first")
        retry_recipe = recipe or self._last_recipe
        if retry_recipe is None:
            raise RuntimeError("No recipe available for retry")
        return self.run(retry_recipe, stages=stages, task_names=task_names, load_plugins=False)

    # --- helpers ------------------------------------------------------
    def _run_stage(
        self, stage: SetupStage, tasks: Sequence[SetupTask], context: StageContext
    ) -> list[SetupResult]:
        stage_results: list[SetupResult] = []
        self.plugin_manager.dispatch_before_stage(stage, context)
        stage_config = context.stage_config(stage)
        disabled_tasks = set(stage_config.get("skip", []) if isinstance(stage_config, dict) else [])
        for task in tasks:
            if task.name in disabled_tasks:
                result = SetupResult(
                    task=task.name,
                    stage=stage,
                    status=SetupStatus.SKIPPED,
                    payload={"reason": "recipe-skip"},
                )
                context.results[task.name] = result
                stage_results.append(result)
                continue
            run_attempts = self._attempts.get(task.name, 0) + 1
            self._attempts[task.name] = run_attempts
            self.plugin_manager.dispatch_before_task(task, context)
            try:
                raw = task.action(context)
                if isinstance(raw, SetupResult):
                    result = raw
                    result.attempts = run_attempts
                else:
                    payload = dict(raw or {})
                    result = SetupResult(
                        task=task.name,
                        stage=stage,
                        status=SetupStatus.SUCCESS,
                        payload=payload,
                        attempts=run_attempts,
                    )
            except Exception as exc:  # pragma: no cover - defensive
                self.plugin_manager.dispatch_error(task, exc, context)
                result = SetupResult(
                    task=task.name,
                    stage=stage,
                    status=SetupStatus.FAILED,
                    payload={},
                    error=exc,
                    attempts=run_attempts,
                )
                if not task.allow_fail:
                    self.logger.error("Task %s failed during %s: %s", task.name, stage.value, exc)
            finally:
                result.finished_at = time.time()
            context.results[task.name] = result
            stage_results.append(result)
            self.plugin_manager.dispatch_after_task(result, context)
            for validator in self._validators():
                try:
                    validator(result, context)
                except Exception as exc:
                    self.logger.warning("Validator error for %s: %s", task.name, exc)
            if result.status is SetupStatus.FAILED and not task.allow_fail:
                break
        self.plugin_manager.dispatch_after_stage(stage, stage_results, context)
        for reporter in self.plugin_manager.iter_reporters():
            try:
                reporter(stage_results, context)
            except Exception as exc:
                self.logger.warning("Reporter error for stage %s: %s", stage.value, exc)
        self._results.update({r.task: r for r in stage_results})
        return stage_results

    def _validators(self) -> Iterable[Validator]:
        return self.plugin_manager.iter_validators()


__all__ = [
    "SetupOrchestrator",
    "SetupTask",
    "SetupResult",
    "SetupStatus",
    "SetupStage",
    "STAGE_ORDER",
    "StageContext",
]

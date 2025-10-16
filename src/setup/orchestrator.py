"""Core setup orchestrator implementation."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging
import time
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence

from src.console.events import DashboardEvent, LogEvent, StageEvent, TaskEvent

from .plugins import (
    PluginManager,
    Validator,
    ContinuousValidator,
    ValidatorDecision,
    RemediationAction,
)
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
        self._subscribers: list[Callable[[DashboardEvent], None]] = []
        self.stage_order: tuple[SetupStage, ...] = STAGE_ORDER
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
        offline_flag = os.environ.get("_OFFLINE")
        offline_enabled = False
        if offline_flag is not None:
            offline_enabled = offline_flag not in {"0", "false", "False", ""}
            if offline_enabled:
                os.environ["COOLBOX_OFFLINE"] = "1"
            else:
                os.environ.pop("COOLBOX_OFFLINE", None)
        elif os.environ.get("COOLBOX_OFFLINE") == "1":
            offline_enabled = True
        context.set("setup.offline", offline_enabled)
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
                self._publish(StageEvent(stage, status="skipped", payload={"reason": "no tasks"}))
                continue
            try:
                stage_results = self._run_stage(stage, stage_tasks, context)
            except Exception as exc:
                self._publish(
                    StageEvent(
                        stage,
                        status="failed",
                        payload={"error": repr(exc)},
                    )
                )
                raise
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

    def rerun_stage(self, stage: SetupStage) -> list[SetupResult]:
        """Retry a specific stage using the most recent recipe."""

        return self.retry(stages=[stage])

    # --- dashboard integration --------------------------------------------
    def subscribe(self, callback: Callable[[DashboardEvent], None]) -> None:
        """Register *callback* to receive dashboard events."""

        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[DashboardEvent], None]) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _publish(self, event: DashboardEvent) -> None:
        for subscriber in list(self._subscribers):
            try:
                subscriber(event)
            except Exception:  # pragma: no cover - best effort delivery
                self.logger.debug("dashboard subscriber failed", exc_info=True)

    # --- helpers ------------------------------------------------------
    def _run_stage(
        self, stage: SetupStage, tasks: Sequence[SetupTask], context: StageContext
    ) -> list[SetupResult]:
        stage_results: list[SetupResult] = []
        self._publish(StageEvent(stage, status="started"))
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
                self._publish(TaskEvent(task.name, stage, status="skipped", payload=result.payload))
                continue
            break_stage = False
            self._publish(
                TaskEvent(
                    task.name,
                    stage,
                    status="started",
                    payload={"dependencies": list(task.dependencies)},
                )
            )
            while True:
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
                        self._publish(
                            LogEvent("error", f"Task {task.name} failed: {exc}")
                        )
                        self.logger.error(
                            "Task %s failed during %s: %s", task.name, stage.value, exc
                        )
                finally:
                    result.finished_at = time.time()
                context.results[task.name] = result
                stage_results.append(result)
                self.plugin_manager.dispatch_after_task(result, context)
                if result.status is SetupStatus.SUCCESS:
                    self._publish(
                        TaskEvent(
                            task.name,
                            stage,
                            status="completed",
                            payload=result.payload,
                        )
                    )
                elif result.status is SetupStatus.FAILED:
                    self._publish(
                        TaskEvent(
                            task.name,
                            stage,
                            status="failed",
                            error=repr(result.error),
                        )
                    )
                else:
                    self._publish(
                        TaskEvent(
                            task.name,
                            stage,
                            status=result.status.value,
                            payload=result.payload,
                        )
                    )
                retry_requested = False
                for validator in self._validators():
                    try:
                        validator(result, context)
                    except Exception as exc:
                        self.logger.warning("Validator error for %s: %s", task.name, exc)
                retry_requested = (
                    self._apply_continuous_validators(result, context, stage_results)
                    or retry_requested
                )
                if (
                    retry_requested
                    and result.status is SetupStatus.FAILED
                    and not task.allow_fail
                    and run_attempts < task.max_retries
                ):
                    self._publish(
                        LogEvent(
                            "info",
                            f"Retrying task {task.name} after remediation (attempt {run_attempts + 1})",
                        )
                    )
                    self.logger.info(
                        "Retrying task %s after remediation (attempt %s)",
                        task.name,
                        run_attempts + 1,
                    )
                    continue
                if result.status is SetupStatus.FAILED and not task.allow_fail:
                    break_stage = True
                break
            if break_stage:
                break
        self.plugin_manager.dispatch_after_stage(stage, stage_results, context)
        for reporter in self.plugin_manager.iter_reporters():
            try:
                reporter(stage_results, context)
            except Exception as exc:
                self.logger.warning("Reporter error for stage %s: %s", stage.value, exc)
        self._results.update({r.task: r for r in stage_results})
        self._publish(
            StageEvent(
                stage,
                status="completed",
                payload={"results": [res.as_dict() for res in stage_results]},
            )
        )
        return stage_results

    def _validators(self) -> Iterable[Validator]:
        return self.plugin_manager.iter_validators()

    def _continuous_validators(self) -> Iterable[ContinuousValidator]:
        return self.plugin_manager.iter_continuous_validators()

    def _apply_continuous_validators(
        self,
        result: SetupResult,
        context: StageContext,
        stage_results: list[SetupResult],
    ) -> bool:
        retry_requested = False
        for validator in self._continuous_validators():
            try:
                decision = validator(result, context)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning(
                    "Continuous validator error for %s: %s", result.task, exc
                )
                continue
            if not decision:
                continue
            self.logger.info(
                "Continuous validator %s triggered remediation: %s",
                decision.name,
                decision.reason,
            )
            self._run_remediations(
                decision.rollbacks, "rollback", decision, result, context, stage_results
            )
            self._run_remediations(
                decision.repairs, "repair", decision, result, context, stage_results
            )
            retry_requested = retry_requested or decision.retry
        return retry_requested

    def _run_remediations(
        self,
        actions: Sequence[RemediationAction],
        phase: str,
        decision: ValidatorDecision,
        result: SetupResult,
        context: StageContext,
        stage_results: list[SetupResult],
    ) -> None:
        for action in actions:
            try:
                remediation_result = action(context, result)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error(
                    "Remediation %s from validator %s failed: %s",
                    phase,
                    decision.name,
                    exc,
                )
                continue
            if isinstance(remediation_result, SetupResult):
                remediation_result.finished_at = time.time()
                context.results[remediation_result.task] = remediation_result
                stage_results.append(remediation_result)


__all__ = [
    "SetupOrchestrator",
    "SetupTask",
    "SetupResult",
    "SetupStatus",
    "SetupStage",
    "STAGE_ORDER",
    "StageContext",
]

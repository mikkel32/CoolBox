"""Core setup orchestrator implementation."""
from __future__ import annotations

import heapq
import importlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import logging
import time
from typing import IO, Any, Callable, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence

from coolbox.console.events import DashboardEvent, LogEvent, StageEvent, TaskEvent
from coolbox.plugins import PluginDefinition, ProfileDevSettings
from coolbox.tools import ToolBus
from coolbox.telemetry import NullTelemetryClient, TelemetryClient

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
    error_repr: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float = field(default_factory=time.time)
    attempts: int = 1

    def __post_init__(self) -> None:
        if self.error is not None and self.error_repr is None:
            self.error_repr = repr(self.error)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "stage": self.stage.value,
            "status": self.status.value,
            "payload": self.payload,
            "error": self.error_repr if self.error_repr else None,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SetupResult":
        payload = dict(data.get("payload", {}))
        started_at = float(data.get("started_at", time.time()))
        finished_at = float(data.get("finished_at", started_at))
        attempts = int(data.get("attempts", 1))
        status = SetupStatus(data.get("status", SetupStatus.SUCCESS.value))
        stage = SetupStage(data.get("stage", SetupStage.PREFLIGHT.value))
        error_repr = data.get("error")
        return cls(
            task=str(data.get("task")),
            stage=stage,
            status=status,
            payload=payload,
            error=None,
            error_repr=str(error_repr) if error_repr else None,
            started_at=started_at,
            finished_at=finished_at,
            attempts=attempts,
        )


@dataclass(slots=True)
class SetupRunJournal:
    """Persisted record of a setup execution attempt."""

    path: Path
    metadata: Mapping[str, Any]
    results: Sequence[SetupResult]

    def latest_results(self) -> dict[str, SetupResult]:
        summary: dict[str, SetupResult] = {}
        for result in self.results:
            summary[result.task] = result
        return summary

    def iter_events(self) -> Iterable[DashboardEvent]:
        current_stage: SetupStage | None = None
        stage_results: list[SetupResult] = []
        for result in self.results:
            if current_stage != result.stage:
                if current_stage is not None:
                    yield _journal_stage_event(current_stage, stage_results)
                    stage_results = []
                current_stage = result.stage
                yield StageEvent(
                    current_stage,
                    status="started",
                    payload={"source": "journal"},
                )
            stage_results.append(result)
            yield _journal_task_event(result)
        if current_stage is not None:
            yield _journal_stage_event(current_stage, stage_results)


def _journal_stage_event(stage: SetupStage, results: Sequence[SetupResult]) -> StageEvent:
    if not results:
        return StageEvent(stage, status="completed", payload={"source": "journal"})
    final = results[-1]
    if final.status is SetupStatus.FAILED:
        status = "failed"
    elif all(res.status is SetupStatus.SKIPPED for res in results):
        status = "skipped"
    else:
        status = "completed"
    payload = {"results": [res.as_dict() for res in results], "source": "journal"}
    return StageEvent(stage, status=status, payload=payload)


def _journal_task_event(result: SetupResult) -> TaskEvent:
    status_map = {
        SetupStatus.SUCCESS: "completed",
        SetupStatus.FAILED: "failed",
        SetupStatus.SKIPPED: "skipped",
    }
    payload_data: dict[str, Any] = {"source": "journal"}
    if isinstance(result.payload, Mapping):
        payload_data.update(result.payload)
    elif result.payload:
        payload_data["payload"] = result.payload
    payload: Mapping[str, Any] | None = payload_data or None
    error = result.error_repr if result.status is SetupStatus.FAILED else None
    return TaskEvent(
        result.task,
        result.stage,
        status=status_map.get(result.status, result.status.value),
        error=error,
        payload={"source": "journal", "payload": payload} if payload else {"source": "journal"},
    )


def _journal_directory(root: Path) -> Path:
    return root / "artifacts" / "setup_runs"


def _load_journal(path: Path) -> SetupRunJournal:
    metadata: dict[str, Any] = {}
    results: list[SetupResult] = []
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            record_type = record.get("type")
            if record_type == "run" and not metadata:
                metadata = {k: v for k, v in record.items() if k != "type"}
            elif record_type in {"resume", "run"}:
                continue
            else:
                results.append(SetupResult.from_dict(record))
    return SetupRunJournal(path=path, metadata=metadata, results=tuple(results))


def load_last_run(root: Path | None = None) -> SetupRunJournal | None:
    """Return the most recent journaled setup run, if any."""

    base = Path(root or Path.cwd()).resolve()
    journal_dir = _journal_directory(base)
    if not journal_dir.exists():
        return None
    candidates = sorted(journal_dir.glob("*.jsonl"), key=lambda entry: entry.stat().st_mtime, reverse=True)
    for candidate in candidates:
        try:
            return _load_journal(candidate)
        except Exception:  # pragma: no cover - corrupted journal entries
            continue
    return None


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


def _parse_truthy(value: str | None) -> bool:
    """Return ``True`` when ``value`` represents a truthy flag."""

    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


class SetupOrchestrator:
    """Coordinates the execution of setup stages."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        tasks: Sequence[SetupTask] | None = None,
        plugin_manager: PluginManager | None = None,
        logger: logging.Logger | None = None,
        telemetry: TelemetryClient | None = None,
    ) -> None:
        self.root = Path(root or Path.cwd()).resolve()
        self.logger = logger or logging.getLogger("coolbox.setup.orchestrator")
        self._tasks: dict[str, SetupTask] = {}
        self._attempts: dict[str, int] = {}
        self._results: dict[str, SetupResult] = {}
        self._last_recipe: Recipe | None = None
        self.plugin_manager = plugin_manager or PluginManager()
        self.tool_bus = ToolBus()
        self.plugin_manager.attach_tool_bus(self.tool_bus)
        self._subscribers: list[Callable[[DashboardEvent], None]] = []
        self.stage_order: tuple[SetupStage, ...] = STAGE_ORDER
        self.telemetry: TelemetryClient | NullTelemetryClient = telemetry or NullTelemetryClient()
        self._journal_path: Path | None = None
        self._journal_file: IO[str] | None = None
        self._journal_metadata: dict[str, Any] | None = None
        self._loaded_journal: SetupRunJournal | None = None
        self._resume_journal: SetupRunJournal | None = None
        self._resume_results: dict[str, SetupResult] = {}
        self._resume_successes: set[str] = set()
        self._resume_success_pending: set[str] = set()
        self._last_plugins: Sequence[PluginDefinition] | None = None
        self._profile_dev: ProfileDevSettings | None = None
        self._active_profile_name: str | None = None
        self._manifest_hint: str | None = None
        if tasks:
            for task in tasks:
                self.register_task(task)

    def attach_telemetry(self, telemetry: TelemetryClient | None) -> None:
        self.telemetry = telemetry or NullTelemetryClient()

    def set_profile_context(
        self,
        *,
        profile_name: str | None,
        manifest_path: str | None,
    ) -> None:
        """Record contextual metadata for subsequent plugin loading."""

        self._active_profile_name = profile_name
        self._manifest_hint = manifest_path

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
        plugins: Sequence[PluginDefinition] | None = None,
        dev: ProfileDevSettings | None = None,
    ) -> list[SetupResult]:
        if not self._tasks:
            raise RuntimeError("No tasks registered for setup orchestration")
        requested_stages = list(stages or [])
        requested_tasks = list(task_names or [])
        stage_filter = set(requested_stages)
        task_filter = set(requested_tasks)
        resume_map = dict(self._resume_results)
        self._results = resume_map
        self._attempts = {}
        self._last_recipe = recipe
        self._resume_success_pending = set(self._resume_successes)

        context = StageContext(root=self.root, recipe=recipe, orchestrator=self, results=self._results)
        offline_flag = os.environ.get("_OFFLINE")
        if offline_flag is not None:
            offline_enabled = _parse_truthy(offline_flag)
        else:
            offline_enabled = _parse_truthy(os.environ.get("COOLBOX_OFFLINE"))
            if offline_enabled:
                try:  # pragma: no cover - defensive import
                    setup_module = importlib.import_module("setup")
                except Exception:  # pragma: no cover - setup unavailable
                    pass
                else:
                    forced = bool(getattr(setup_module, "_OFFLINE_FORCED", False))
                    auto_detected = bool(
                        getattr(setup_module, "offline_auto_detected", lambda: False)()
                    )
                    if forced and not auto_detected:
                        offline_enabled = False
        if offline_enabled:
            os.environ["COOLBOX_OFFLINE"] = "1"
        else:
            os.environ.pop("COOLBOX_OFFLINE", None)
        context.set("setup.offline", offline_enabled)

        plugin_ids: Sequence[str] | None
        if plugins is None:
            self.plugin_manager.load_entrypoints(self)
            self._last_plugins = None
            plugin_ids = None
        else:
            plugin_list = list(plugins)
            self._last_plugins = tuple(plugin_list)
            self._profile_dev = dev
            plugin_ids = [definition.identifier for definition in plugin_list]
            if plugin_list:
                self.plugin_manager.load_from_manifest(
                    self,
                    plugin_list,
                    dev=dev,
                    profile=self._active_profile_name,
                    manifest_path=self._manifest_hint,
                )
        execution_plan = self._build_execution_plan(stage_filter, task_filter)
        results: list[SetupResult] = []
        self._start_journal(
            recipe,
            requested_stages=requested_stages,
            requested_tasks=requested_tasks,
            plugins=plugin_ids,
        )
        try:
            run_metadata = {
                "recipe": recipe.name,
                "stages": [stage.value for stage in self.stage_order],
                "task_count": len(self._tasks),
                "offline": offline_enabled,
            }
            if plugin_ids is not None:
                run_metadata["plugins"] = list(plugin_ids)
            self.telemetry.record_run(run_metadata)
            continue_on_failure = bool(recipe.config.get("continue_on_failure"))
            for stage in self.stage_order:
                if stage_filter and stage not in stage_filter:
                    continue
                stage_tasks = execution_plan.get(stage, [])
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
                    self._record_stage_telemetry(
                        stage,
                        status="failed",
                        duration=time.time() - context.get(f"stage.{stage.value}.started", time.time()),
                        failure_code=f"{stage.value}:exception:{type(exc).__name__}",
                        metadata={"error": repr(exc)},
                    )
                    raise
                results.extend(stage_results)
                if not continue_on_failure:
                    blocking_failure = next(
                        (
                            res
                            for res in stage_results
                            if res.status is SetupStatus.FAILED
                            and (task_meta := self._tasks.get(res.task)) is not None
                            and not task_meta.allow_fail
                        ),
                        None,
                    )
                    if blocking_failure is not None:
                        break
            return results
        finally:
            self._finish_journal()
            self._resume_results = {}
            self._resume_successes.clear()
            self._resume_success_pending.clear()
            self._resume_journal = None

    def retry(
        self,
        *,
        task_names: Sequence[str] | None = None,
        stages: Sequence[SetupStage] | None = None,
        recipe: Recipe | None = None,
    ) -> list[SetupResult]:
        if self._last_recipe is None and recipe is None:
            journal = load_last_run(self.root)
            if journal:
                self._loaded_journal = journal
                self.resume_from_journal(journal)
                recipe_data = journal.metadata.get("recipe") if journal.metadata else None
                recipe_name = journal.metadata.get("recipe_name") if journal.metadata else None
                if recipe_data and isinstance(recipe_data, Mapping):
                    recipe = Recipe(name=str(recipe_name or "recovered"), data=dict(recipe_data))
                    self._last_recipe = recipe
        if self._last_recipe is None and recipe is None:
            raise RuntimeError("No prior recipe run recorded; call run() first")
        retry_recipe = recipe or self._last_recipe
        if retry_recipe is None:
            raise RuntimeError("No recipe available for retry")
        plugins_arg: Sequence[PluginDefinition] | None
        if self._last_plugins is None:
            plugins_arg = None
        else:
            plugins_arg = tuple(self._last_plugins)
        return self.run(
            retry_recipe,
            stages=stages,
            task_names=task_names,
            plugins=plugins_arg,
            dev=self._profile_dev,
        )

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
        try:
            self.tool_bus.publish(
                topic="setup.events",
                payload={
                    "type": event.__class__.__name__,
                    "repr": repr(event),
                },
                metadata={"source": "orchestrator"},
            )
        except Exception:  # pragma: no cover - defensive logging
            self.logger.debug("tool bus publish failed", exc_info=True)

    def replay_events(self, events: Iterable[DashboardEvent]) -> None:
        """Replay historical dashboard events to current subscribers."""

        for event in events:
            self._publish(event)

    # --- journal helpers --------------------------------------------
    def resume_from_journal(self, journal: SetupRunJournal | None) -> None:
        """Prime the orchestrator with prior successful task results."""

        if journal is None:
            self._resume_journal = None
            self._resume_results = {}
            self._resume_successes.clear()
            return
        self._resume_journal = journal
        latest = journal.latest_results()
        successes: dict[str, SetupResult] = {}
        for name, result in latest.items():
            if result.status is SetupStatus.SUCCESS:
                successes[name] = SetupResult.from_dict(result.as_dict())
        self._resume_results = successes
        self._resume_successes = set(successes.keys())

    def _start_journal(
        self,
        recipe: Recipe,
        *,
        requested_stages: Sequence[SetupStage],
        requested_tasks: Sequence[str],
        plugins: Sequence[str] | None,
    ) -> None:
        journal_dir = _journal_directory(self.root)
        journal_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        stage_values = [stage.value for stage in requested_stages]
        task_values = list(requested_tasks)
        resume_journal = self._resume_journal
        resume_entry = (
            resume_journal is not None and resume_journal.path.exists()
        )
        if resume_entry:
            assert resume_journal is not None
            path = resume_journal.path
            mode = "a"
        else:
            path = journal_dir / f"{timestamp}.jsonl"
            mode = "w"
        self._journal_path = path
        self._journal_file = path.open(mode, encoding="utf-8")
        if resume_entry:
            assert resume_journal is not None
            self._journal_metadata = dict(resume_journal.metadata)
            entry = {
                "type": "resume",
                "timestamp": timestamp,
                "stages": stage_values,
                "tasks": task_values,
            }
            self._write_journal_entry(entry)
        else:
            metadata: dict[str, Any] = {
                "timestamp": timestamp,
                "recipe_name": recipe.name,
                "recipe": recipe.as_dict(),
                "stages": stage_values,
                "tasks": task_values,
                "plugins": list(plugins) if plugins is not None else None,
            }
            if recipe.source is not None:
                metadata["recipe_source"] = str(recipe.source)
            self._journal_metadata = metadata
            entry = {"type": "run"}
            entry.update(metadata)
            self._write_journal_entry(entry)

    def _write_journal_entry(self, entry: Mapping[str, Any]) -> None:
        if self._journal_file is None:
            return
        json.dump(entry, self._journal_file)
        self._journal_file.write("\n")
        self._journal_file.flush()

    def _record_journal_result(self, result: SetupResult) -> None:
        if self._journal_file is None:
            return
        entry = {"type": "result"}
        entry.update(result.as_dict())
        self._write_journal_entry(entry)

    def _finish_journal(self) -> None:
        if self._journal_file is not None:
            try:
                self._journal_file.flush()
            finally:
                self._journal_file.close()
        self._journal_file = None
        if self._journal_path is not None:
            try:
                self._loaded_journal = _load_journal(self._journal_path)
            except Exception:  # pragma: no cover - defensive against corrupted journals
                self._loaded_journal = None


    # --- helpers ------------------------------------------------------
    def _run_stage(
        self, stage: SetupStage, tasks: Sequence[SetupTask], context: StageContext
    ) -> list[SetupResult]:
        stage_results: list[SetupResult] = []
        stage_started_at = time.time()
        context.set(f"stage.{stage.value}.started", stage_started_at)
        self._publish(StageEvent(stage, status="started"))
        self.plugin_manager.dispatch_before_stage(stage, context)
        stage_config = context.stage_config(stage)
        disabled_tasks = set(stage_config.get("skip", []) if isinstance(stage_config, dict) else [])
        stage_failed = False

        def _skip_task(
            task_obj: SetupTask,
            reason: str,
            payload: Mapping[str, Any] | None = None,
        ) -> None:
            base_payload: dict[str, Any] = {"reason": reason}
            if payload:
                base_payload.update(payload)
            failure_suffix: dict[str, str] = {
                "dependency-blocked": "dependency-blocked",
                "dependency-missing": "dependency-missing",
                "stage-aborted": "stage-aborted",
            }
            suffix = failure_suffix.get(reason)
            if suffix:
                base_payload["failure_code"] = f"{stage.value}:{task_obj.name}:{suffix}"
            result = SetupResult(
                task=task_obj.name,
                stage=stage,
                status=SetupStatus.SKIPPED,
                payload=base_payload,
                attempts=0,
            )
            context.results[task_obj.name] = result
            stage_results.append(result)
            self._publish(
                TaskEvent(
                    task_obj.name,
                    stage,
                    status="skipped",
                    payload=base_payload,
                )
            )
            self._record_task_telemetry(task_obj, result)

        for task in tasks:
            if task.name in self._resume_success_pending:
                existing = context.results.get(task.name)
                if existing:
                    stage_results.append(existing)
                self._resume_success_pending.discard(task.name)
                continue
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
            dependency_results = {dep: context.results.get(dep) for dep in task.dependencies}
            missing_dependencies = sorted(name for name, res in dependency_results.items() if res is None)
            blocked_dependencies = {
                name: res.status.value
                for name, res in dependency_results.items()
                if res is not None and res.status is not SetupStatus.SUCCESS
            }
            if missing_dependencies:
                _skip_task(
                    task,
                    "dependency-missing",
                    {"missing": missing_dependencies},
                )
                continue
            if blocked_dependencies:
                _skip_task(
                    task,
                    "dependency-blocked",
                    {"dependencies": blocked_dependencies},
                )
                stage_failed = True
                continue
            if stage_failed:
                _skip_task(task, "stage-aborted")
                continue
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
                started_at = time.time()
                result: SetupResult | None = None
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
                finished_at = time.time()
                if result is None:
                    raise RuntimeError("Task action did not produce a SetupResult")
                result.started_at = started_at
                result.finished_at = finished_at
                context.results[task.name] = result
                self._record_journal_result(result)
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
                    failure_code = self._failure_code(result)
                    failure_payload: dict[str, Any] = {}
                    if failure_code:
                        failure_payload["failure_code"] = failure_code
                    if result.payload:
                        failure_payload["payload"] = result.payload
                    if result.error:
                        failure_payload["error_type"] = type(result.error).__name__
                    self._publish(
                        TaskEvent(
                            task.name,
                            stage,
                            status="failed",
                            error=repr(result.error),
                            payload=failure_payload or None,
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
                self._record_task_telemetry(task, result)
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
                    stage_failed = True
                break
        self.plugin_manager.dispatch_after_stage(stage, stage_results, context)
        for reporter in self.plugin_manager.iter_reporters():
            try:
                reporter(stage_results, context)
            except Exception as exc:
                self.logger.warning("Reporter error for stage %s: %s", stage.value, exc)
        self._results.update({r.task: r for r in stage_results})
        duration = time.time() - stage_started_at
        stage_failure = next((res for res in stage_results if res.status is SetupStatus.FAILED), None)
        status = "failed" if stage_failure else "completed"
        self._publish(
            StageEvent(
                stage,
                status=status,
                payload={"results": [res.as_dict() for res in stage_results]},
            )
        )
        failure_code = self._failure_code(stage_failure) if stage_failure else None
        self._record_stage_telemetry(
            stage,
            status=status,
            duration=duration,
            failure_code=failure_code,
            metadata={"results": [res.as_dict() for res in stage_results]},
        )
        return stage_results

    def _failure_code(self, result: SetupResult | None) -> str | None:
        if result is None:
            return None
        if isinstance(result.payload, Mapping):
            failure_code = result.payload.get("failure_code")
            if isinstance(failure_code, str):
                return failure_code
        error_type = type(result.error).__name__ if result.error else "unknown"
        return f"{result.stage.value}:{result.task}:{error_type}"

    def _record_stage_telemetry(
        self,
        stage: SetupStage,
        *,
        status: str,
        duration: float,
        failure_code: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "stage": stage.value,
            "status": status,
            "duration_ms": int(duration * 1000),
        }
        if failure_code:
            payload["failure_code"] = failure_code
        if metadata:
            payload.update(metadata)
        self.telemetry.record_stage(payload)

    def _record_task_telemetry(self, task: SetupTask, result: SetupResult) -> None:
        duration = max(result.finished_at - result.started_at, 0.0)
        payload: dict[str, Any] = {
            "task": task.name,
            "stage": task.stage.value,
            "status": result.status.value,
            "duration_ms": int(duration * 1000),
            "attempts": result.attempts,
        }
        failure_code = None
        if isinstance(result.payload, Mapping):
            fc = result.payload.get("failure_code")
            if isinstance(fc, str):
                failure_code = fc
        if result.status is SetupStatus.FAILED:
            failure_code = failure_code or self._failure_code(result)
            if failure_code:
                payload["failure_code"] = failure_code
            if result.error:
                payload["error_type"] = type(result.error).__name__
                payload["error_message"] = repr(result.error)
        elif failure_code:
            payload["failure_code"] = failure_code
        if result.payload:
            suggested_fix = result.payload.get("suggested_fix") if isinstance(result.payload, Mapping) else None
            if suggested_fix:
                payload["suggested_fix"] = suggested_fix
            if isinstance(result.payload, Mapping):
                remediation_metadata = result.payload.get("suggested_remediation")
                if remediation_metadata:
                    payload["suggested_remediation"] = self._normalize_remediation_metadata(
                        remediation_metadata
                    )
            payload["payload_keys"] = sorted(result.payload.keys()) if isinstance(result.payload, Mapping) else []
        self.telemetry.record_task(payload)

    def _normalize_remediation_metadata(self, data: Any) -> Any:
        if hasattr(data, "to_payload"):
            try:
                payload = data.to_payload()  # type: ignore[attr-defined]
            except Exception:
                payload = None
            if payload is not None:
                return self._normalize_remediation_metadata(payload)
        if isinstance(data, Mapping):
            return {key: self._normalize_remediation_metadata(value) for key, value in data.items()}
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
            return [self._normalize_remediation_metadata(item) for item in data]
        return data

    def _build_execution_plan(
        self,
        stage_filter: set[SetupStage],
        task_filter: set[str],
    ) -> dict[SetupStage, list[SetupTask]]:
        stage_plan: dict[SetupStage, list[SetupTask]] = {}
        stage_index = {stage: idx for idx, stage in enumerate(self.stage_order)}
        for stage in self.stage_order:
            if stage_filter and stage not in stage_filter:
                continue
            stage_tasks = [task for task in self._tasks.values() if task.stage is stage]
            if task_filter:
                stage_tasks = [task for task in stage_tasks if task.name in task_filter]
            if not stage_tasks:
                stage_plan[stage] = []
                continue
            stage_task_map = {task.name: task for task in stage_tasks}
            ordered_names = [task.name for task in stage_tasks]
            order_index = {name: idx for idx, name in enumerate(ordered_names)}
            adjacency: dict[str, set[str]] = {name: set() for name in stage_task_map}
            dependents: dict[str, list[str]] = {name: [] for name in stage_task_map}
            for task in stage_tasks:
                for dep_name in task.dependencies:
                    if dep_name not in self._tasks:
                        raise ValueError(
                            f"Task '{task.name}' depends on unknown task '{dep_name}'"
                        )
                    dep_task = self._tasks[dep_name]
                    dep_stage = dep_task.stage
                    if stage_index[dep_stage] > stage_index[stage]:
                        raise ValueError(
                            f"Task '{task.name}' depends on future stage task '{dep_name}'"
                        )
                    if dep_stage is stage:
                        if dep_name not in stage_task_map:
                            raise ValueError(
                                f"Task '{task.name}' depends on filtered task '{dep_name}' in stage '{stage.value}'"
                            )
                        adjacency[task.name].add(dep_name)
                        dependents.setdefault(dep_name, []).append(task.name)
                    else:
                        if stage_filter and dep_stage not in stage_filter and stage_index[dep_stage] < stage_index[stage]:
                            raise ValueError(
                                f"Task '{task.name}' depends on task '{dep_name}' from skipped stage '{dep_stage.value}'"
                            )
                        if task_filter and dep_name not in task_filter:
                            raise ValueError(
                                f"Task '{task.name}' depends on filtered task '{dep_name}'"
                            )
            heap: list[tuple[int, str]] = []
            for name, deps in adjacency.items():
                if not deps:
                    heapq.heappush(heap, (order_index[name], name))
            ordered: list[str] = []
            while heap:
                _, name = heapq.heappop(heap)
                ordered.append(name)
                for follower in dependents.get(name, []):
                    deps = adjacency[follower]
                    if name in deps:
                        deps.remove(name)
                    if not deps:
                        heapq.heappush(heap, (order_index[follower], follower))
            if len(ordered) != len(stage_tasks):
                raise ValueError(f"Cyclic dependency detected in stage '{stage.value}'")
            stage_plan[stage] = [stage_task_map[name] for name in ordered]
        return stage_plan

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
    "SetupRunJournal",
    "load_last_run",
]

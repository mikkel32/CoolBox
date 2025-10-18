"""Adaptive remediation plugin that leverages telemetry insights."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Sequence, TYPE_CHECKING

from coolbox.console.events import LogEvent, TaskEvent
from coolbox.telemetry import RemediationSuggestion, TelemetryKnowledgeBase

if TYPE_CHECKING:  # pragma: no cover - imports for typing only
    from ..orchestrator import SetupOrchestrator, SetupResult, SetupStatus, StageContext

from . import RemediationAction, SetupPlugin, ValidatorDecision


@dataclass(slots=True)
class _RemediationPlan:
    """Snapshot of staged remediation instructions."""

    commands: list[str]
    config_patches: list[Mapping[str, object]]
    task_overrides: dict[str, Mapping[str, object]]


class AdaptiveRemediationPlugin(SetupPlugin):
    """Register a continuous validator that proposes telemetry-backed fixes."""

    name = "adaptive-remediation"

    def __init__(self, knowledge_base: TelemetryKnowledgeBase | None = None) -> None:
        self._override_knowledge = knowledge_base
        self._orchestrator: "SetupOrchestrator | None" = None

    # --- SetupPlugin API -------------------------------------------------
    def register(self, registrar) -> None:  # type: ignore[override]
        self._orchestrator = registrar.orchestrator
        registrar.add_continuous_validator(self._continuous_validator)
        if getattr(registrar, "add_tool_endpoint", None) is not None:
            registrar.add_tool_endpoint(
                "setup.remediation.suggest",
                self.toolbus_suggest,
                metadata={"plugin": self.name},
            )

    def before_stage(self, stage, context) -> None:  # pragma: no cover - interface hook
        return

    def after_stage(self, stage, results, context) -> None:  # pragma: no cover - interface hook
        return

    def before_task(self, task, context) -> None:  # pragma: no cover - interface hook
        return

    def after_task(self, result, context) -> None:  # pragma: no cover - interface hook
        return

    def on_error(self, task, error, context) -> None:  # pragma: no cover - interface hook
        return

    # --- internals -------------------------------------------------------
    def _knowledge(self, context: "StageContext | None") -> TelemetryKnowledgeBase:
        if self._override_knowledge:
            return self._override_knowledge
        if context is not None:
            return context.orchestrator.telemetry.knowledge
        if self._orchestrator is not None:
            return self._orchestrator.telemetry.knowledge
        raise RuntimeError("Telemetry knowledge source unavailable")

    def _continuous_validator(self, result: "SetupResult", context: "StageContext"):
        from ..orchestrator import SetupStatus  # local import to avoid circular dependency

        if result.status is not SetupStatus.FAILED:
            return None
        knowledge = self._knowledge(context)
        failure_code = self._resolve_failure_code(result)
        error_type = type(result.error).__name__ if result.error else None
        suggestion = knowledge.suggest_fix(
            failure_code=failure_code,
            error_type=error_type,
            stage=result.stage.value,
            task=result.task,
        )
        if not suggestion:
            return None
        self._emit_prediction(context, result, suggestion, failure_code)
        actions = tuple(self._remediation_actions(context, suggestion))
        if not actions:
            return None
        reason = f"Applying remediation '{suggestion.title}' (confidence {suggestion.confidence:.2f})"
        return ValidatorDecision(
            name=self.name,
            reason=reason,
            repairs=actions,
            retry=suggestion.retry,
        )

    # --- Tool bus integration ------------------------------------------
    def toolbus_suggest(self, context, payload: bytes) -> Mapping[str, object]:
        data: Mapping[str, object]
        if not payload:
            data = {}
        else:
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = {}
        failure_code = data.get("failure_code") if isinstance(data, Mapping) else None
        error_type = data.get("error_type") if isinstance(data, Mapping) else None
        stage = data.get("stage") if isinstance(data, Mapping) else None
        task = data.get("task") if isinstance(data, Mapping) else None
        knowledge = self._knowledge(None)
        suggestion = knowledge.suggest_fix(
            failure_code=failure_code if isinstance(failure_code, str) else None,
            error_type=error_type if isinstance(error_type, str) else None,
            stage=stage if isinstance(stage, str) else None,
            task=task if isinstance(task, str) else None,
        )
        if suggestion is None:
            return {
                "suggestion": None,
                "request_id": getattr(context, "request_id", None),
            }
        return {
            "suggestion": suggestion.to_payload(),
            "confidence": suggestion.confidence,
            "retry": suggestion.retry,
            "request_id": getattr(context, "request_id", None),
        }

    def _resolve_failure_code(self, result: "SetupResult") -> str | None:
        payload = result.payload if isinstance(result.payload, Mapping) else {}
        failure_code = payload.get("failure_code") if isinstance(payload, Mapping) else None
        if isinstance(failure_code, str) and failure_code:
            return failure_code
        error_type = type(result.error).__name__ if result.error else "unknown"
        return f"{result.stage.value}:{result.task}:{error_type}"

    def _remediation_actions(
        self,
        context: "StageContext",
        suggestion: RemediationSuggestion,
    ) -> Sequence[RemediationAction]:
        plan = self._build_plan(context, suggestion)

        def apply_plan(stage_context: "StageContext", failed_result: "SetupResult") -> "SetupResult":
            from ..orchestrator import SetupResult, SetupStatus  # local import to avoid circular dependency

            bucket = stage_context.state.setdefault(
                "adaptive_remediation",
                {
                    "commands": [],
                    "config_patches": [],
                    "task_overrides": {},
                },
            )
            commands_store = bucket.setdefault("commands", [])
            config_store = bucket.setdefault("config_patches", [])
            override_store = bucket.setdefault("task_overrides", {})
            commands_store.extend(plan.commands)
            config_store.extend(plan.config_patches)
            override_store.update(plan.task_overrides)
            suggestion_payload = suggestion.to_payload()
            remediation_payload = {
                "source": self.name,
                "suggestion": suggestion_payload,
                "confidence": suggestion.confidence,
                "target_task": failed_result.task,
                "stage": failed_result.stage.value,
            }
            stage_context.orchestrator._publish(  # emit applied event for dashboards
                TaskEvent(
                    failed_result.task,
                    failed_result.stage,
                    status="remediation-applied",
                    payload=remediation_payload,
                )
            )
            stage_context.orchestrator._publish(
                LogEvent(
                    "info",
                    f"Remediation actions staged for {failed_result.task} (confidence {suggestion.confidence:.2f})",
                    payload=remediation_payload,
                )
            )
            return SetupResult(
                task=f"{failed_result.task}#adaptive-remediation",
                stage=failed_result.stage,
                status=SetupStatus.SUCCESS,
                payload={
                    "applied": remediation_payload,
                    "suggested_remediation": suggestion_payload,
                },
            )

        return (apply_plan,)

    def _build_plan(self, context: "StageContext", suggestion: RemediationSuggestion) -> _RemediationPlan:
        config_patches = [patch.to_payload() for patch in suggestion.config_patches]
        overrides: dict[str, Mapping[str, object]] = {}
        for override in suggestion.task_overrides:
            overrides[override.task] = dict(override.parameters)
        return _RemediationPlan(
            commands=list(suggestion.commands),
            config_patches=config_patches,
            task_overrides=overrides,
        )

    def _emit_prediction(
        self,
        context: "StageContext",
        result: "SetupResult",
        suggestion: RemediationSuggestion,
        failure_code: str | None,
    ) -> None:
        payload = {
            "source": self.name,
            "suggestion": suggestion.to_payload(),
            "confidence": suggestion.confidence,
            "failure_code": failure_code,
            "task": result.task,
            "stage": result.stage.value,
        }
        context.orchestrator._publish(
            TaskEvent(
                result.task,
                result.stage,
                status="remediation",  # indicates prediction rather than completion
                payload=payload,
            )
        )
        context.orchestrator._publish(
            LogEvent(
                "info",
                f"{self.name} predicted remediation for {result.task}: {suggestion.describe()}",
                payload=payload,
            )
        )


__all__ = ["AdaptiveRemediationPlugin"]

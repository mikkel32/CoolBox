"""Simple knowledge base built on top of recorded telemetry events."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import json
from typing import Any, Dict, Hashable, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple, TypeVar

from .events import TelemetryEvent, TelemetryEventType


@dataclass(frozen=True)
class ConfigPatch:
    """Declarative configuration update produced by remediation insights."""

    path: str
    value: Any
    operation: str = "set"

    def to_payload(self) -> Mapping[str, Any]:
        return {"path": self.path, "value": self.value, "operation": self.operation}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ConfigPatch | None":
        path = payload.get("path")
        if not isinstance(path, str) or not path:
            return None
        operation = payload.get("operation", "set")
        if not isinstance(operation, str) or not operation:
            operation = "set"
        return cls(path=path, value=payload.get("value"), operation=operation)


@dataclass(frozen=True)
class TaskOverride:
    """Instruction describing how to retry a task with new parameters."""

    task: str
    parameters: Mapping[str, Any]

    def to_payload(self) -> Mapping[str, Any]:
        return {"task": self.task, "parameters": dict(self.parameters)}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TaskOverride | None":
        task = payload.get("task")
        if not isinstance(task, str) or not task:
            return None
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, Mapping):
            return None
        return cls(task=task, parameters=dict(parameters))


@dataclass(frozen=True)
class RemediationSuggestion:
    """Structured remediation metadata returned by the knowledge base."""

    title: str
    description: str | None = None
    commands: tuple[str, ...] = ()
    config_patches: tuple[ConfigPatch, ...] = ()
    task_overrides: tuple[TaskOverride, ...] = ()
    retry: bool = True
    confidence: float = 0.0
    source: str | None = None
    notes: str | None = None

    def fingerprint(self) -> str:
        return json.dumps(self.to_payload(), sort_keys=True, default=str)

    def to_payload(self) -> Mapping[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "commands": list(self.commands),
            "config_patches": [patch.to_payload() for patch in self.config_patches],
            "task_overrides": [override.to_payload() for override in self.task_overrides],
            "retry": self.retry,
            "confidence": self.confidence,
            "source": self.source,
            "notes": self.notes,
        }

    def with_confidence(self, confidence: float) -> "RemediationSuggestion":
        return replace(self, confidence=confidence)

    def describe(self) -> str:
        parts = [self.title]
        if self.commands:
            parts.append("Commands: " + ", ".join(self.commands))
        if self.config_patches:
            patches = ", ".join(patch.path for patch in self.config_patches)
            parts.append(f"Config patches: {patches}")
        if self.task_overrides:
            overrides = ", ".join(override.task for override in self.task_overrides)
            parts.append(f"Task overrides: {overrides}")
        parts.append(f"Confidence: {self.confidence:.2f}")
        return " | ".join(part for part in parts if part)


@dataclass
class FailureInsight:
    """Aggregated failure insight used for suggestion ranking."""

    occurrences: int
    suggestions: Counter[str]
    library: MutableMapping[str, RemediationSuggestion]

    def register(self, suggestion: RemediationSuggestion) -> None:
        key = suggestion.fingerprint()
        self.suggestions[key] += 1
        if key not in self.library:
            self.library[key] = suggestion

    def top_suggestion(self) -> Optional[RemediationSuggestion]:
        if not self.suggestions:
            return None
        key, count = self.suggestions.most_common(1)[0]
        suggestion = self.library.get(key)
        if suggestion is None:
            return None
        support = count / self.occurrences if self.occurrences else suggestion.confidence
        confidence = max(suggestion.confidence, support)
        return suggestion.with_confidence(confidence)


_CONTEXT_WEIGHTS: Mapping[str, float] = {
    "failure_code": 2.5,
    "stage_task": 2.1,
    "task_error": 1.9,
    "stage_error": 1.8,
    "stage": 1.6,
    "task": 1.5,
    "error": 1.4,
    "global": 1.2,
}


_KeyType = TypeVar("_KeyType", bound=Hashable)


class TelemetryKnowledgeBase:
    """In-memory aggregator of telemetry signals for troubleshooting hints."""

    def __init__(self) -> None:
        self._failures: MutableMapping[str, FailureInsight] = {}
        self._contextual: MutableMapping[Tuple[str, str], FailureInsight] = {}
        self._global_insight = FailureInsight(occurrences=0, suggestions=Counter(), library={})

    def observe(self, event: TelemetryEvent) -> None:
        if event.type is not TelemetryEventType.TASK:
            return
        metadata = event.metadata
        failure_code = metadata.get("failure_code")
        status = metadata.get("status")
        if not failure_code or status != "failed":
            return
        insight = self._get_or_create(self._failures, failure_code)
        insight.occurrences += 1
        stage = metadata.get("stage")
        task = metadata.get("task")
        error_type = metadata.get("error_type")
        context_keys: list[Tuple[str, str]] = []
        if isinstance(stage, str) and stage:
            context_keys.append(("stage", stage))
        if isinstance(task, str) and task:
            context_keys.append(("task", task))
        if isinstance(error_type, str) and error_type:
            context_keys.append(("error", error_type))
        if isinstance(stage, str) and stage and isinstance(task, str) and task:
            context_keys.append(("stage_task", f"{stage}:{task}"))
        if isinstance(stage, str) and stage and isinstance(error_type, str) and error_type:
            context_keys.append(("stage_error", f"{stage}:{error_type}"))
        if isinstance(task, str) and task and isinstance(error_type, str) and error_type:
            context_keys.append(("task_error", f"{task}:{error_type}"))

        contextual_insights: list[FailureInsight] = [insight]
        for key in context_keys:
            context_insight = self._get_or_create(self._contextual, key)
            context_insight.occurrences += 1
            contextual_insights.append(context_insight)

        global_insight = self._global_insight
        global_insight.occurrences += 1
        contextual_insights.append(global_insight)

        for suggestion in self._extract_suggestions(metadata):
            for target in contextual_insights:
                target.register(suggestion)

    def _extract_suggestions(self, metadata: Mapping[str, Any]) -> Sequence[RemediationSuggestion]:
        suggestions: list[RemediationSuggestion] = []
        structured = metadata.get("suggested_remediation")
        if isinstance(structured, Mapping):
            parsed = self._parse_remediation(structured)
            if parsed:
                suggestions.append(parsed)
        elif isinstance(structured, Sequence) and not isinstance(structured, (str, bytes, bytearray)):
            for entry in structured:
                if isinstance(entry, Mapping):
                    parsed = self._parse_remediation(entry)
                    if parsed:
                        suggestions.append(parsed)
        fallback = metadata.get("suggested_fix")
        if isinstance(fallback, str) and fallback and not suggestions:
            suggestions.append(
                RemediationSuggestion(
                    title=fallback,
                    description=fallback,
                    notes="legacy",
                )
            )
        return suggestions

    def _parse_remediation(self, payload: Mapping[str, Any]) -> RemediationSuggestion | None:
        title = payload.get("title") or payload.get("summary") or payload.get("name")
        if not isinstance(title, str) or not title:
            title = "Automated remediation"
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            description = str(description)
        commands_payload = payload.get("commands", [])
        commands: list[str] = []
        if isinstance(commands_payload, Sequence) and not isinstance(commands_payload, (str, bytes, bytearray)):
            for command in commands_payload:
                if isinstance(command, str):
                    commands.append(command)
        config_patches_payload = payload.get("config_patches", [])
        patches: list[ConfigPatch] = []
        if isinstance(config_patches_payload, Sequence) and not isinstance(config_patches_payload, (str, bytes, bytearray)):
            for entry in config_patches_payload:
                if isinstance(entry, Mapping):
                    patch = ConfigPatch.from_payload(entry)
                    if patch:
                        patches.append(patch)
        overrides_payload = payload.get("task_overrides", [])
        overrides: list[TaskOverride] = []
        if isinstance(overrides_payload, Sequence) and not isinstance(overrides_payload, (str, bytes, bytearray)):
            for entry in overrides_payload:
                if isinstance(entry, Mapping):
                    override = TaskOverride.from_payload(entry)
                    if override:
                        overrides.append(override)
        retry = payload.get("retry", True)
        if not isinstance(retry, bool):
            retry = bool(retry)
        confidence = payload.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        source_value = payload.get("source")
        source = source_value if isinstance(source_value, str) else None
        notes_value = payload.get("notes")
        notes = notes_value if isinstance(notes_value, str) else str(notes_value) if notes_value is not None else None
        return RemediationSuggestion(
            title=title,
            description=description,
            commands=tuple(commands),
            config_patches=tuple(patches),
            task_overrides=tuple(overrides),
            retry=retry,
            confidence=confidence_value,
            source=source,
            notes=notes,
        )

    def _get_or_create(
        self,
        store: MutableMapping[_KeyType, FailureInsight],
        key: _KeyType,
    ) -> FailureInsight:
        insight = store.get(key)
        if insight is None:
            insight = FailureInsight(occurrences=0, suggestions=Counter(), library={})
            store[key] = insight
        return insight

    def load(self, events: Iterable[TelemetryEvent]) -> None:
        for event in events:
            self.observe(event)

    def suggest_fix(
        self,
        *,
        failure_code: Optional[str] = None,
        error_type: Optional[str] = None,
        stage: Optional[str] = None,
        task: Optional[str] = None,
    ) -> Optional[RemediationSuggestion]:
        """Return the most likely remediation suggestion for the failure signature."""

        candidates: dict[str, tuple[float, RemediationSuggestion]] = {}

        def register_candidate(kind: str, key: Optional[str]) -> None:
            if not key:
                return
            if kind == "failure_code":
                insight = self._failures.get(key)
            else:
                insight = self._contextual.get((kind, key))
            if not insight:
                return
            suggestion = insight.top_suggestion()
            if not suggestion:
                return
            fingerprint = suggestion.fingerprint()
            score = self._score_candidate(kind, suggestion)
            current = candidates.get(fingerprint)
            if current is None or score > current[0]:
                candidates[fingerprint] = (score, suggestion)

        register_candidate("failure_code", failure_code)
        if stage and task:
            register_candidate("stage_task", f"{stage}:{task}")
        if task and error_type:
            register_candidate("task_error", f"{task}:{error_type}")
        if stage and error_type:
            register_candidate("stage_error", f"{stage}:{error_type}")
        register_candidate("stage", stage)
        register_candidate("task", task)
        register_candidate("error", error_type)

        if self._global_insight.occurrences:
            suggestion = self._global_insight.top_suggestion()
            if suggestion:
                fingerprint = suggestion.fingerprint()
                score = self._score_candidate("global", suggestion)
                current = candidates.get(fingerprint)
                if current is None or score > current[0]:
                    candidates[fingerprint] = (score, suggestion)

        if not candidates:
            return None
        return max(candidates.values(), key=lambda item: item[0])[1]

    def _score_candidate(self, kind: str, suggestion: RemediationSuggestion) -> float:
        weight = _CONTEXT_WEIGHTS.get(kind, 1.0)
        return suggestion.confidence + weight

    def summarize(self) -> Dict[str, Mapping[str, object]]:
        summary: dict[str, Mapping[str, object]] = {}
        for code, insight in self._failures.items():
            suggestion = insight.top_suggestion()
            summary[code] = {
                "occurrences": insight.occurrences,
                "top_remediation": suggestion.to_payload() if suggestion else None,
                "top_fix": suggestion.describe() if suggestion else None,
            }
        return summary


__all__ = [
    "TelemetryKnowledgeBase",
    "FailureInsight",
    "ConfigPatch",
    "TaskOverride",
    "RemediationSuggestion",
]

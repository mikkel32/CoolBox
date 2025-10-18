from __future__ import annotations

from coolbox.telemetry.events import TelemetryEvent, TelemetryEventType
from coolbox.telemetry.knowledge import TelemetryKnowledgeBase


def _event(
    *,
    stage: str,
    task: str,
    failure_code: str,
    error_type: str,
    title: str,
    confidence: float,
) -> TelemetryEvent:
    return TelemetryEvent(
        TelemetryEventType.TASK,
        metadata={
            "status": "failed",
            "stage": stage,
            "task": task,
            "failure_code": failure_code,
            "error_type": error_type,
            "suggested_remediation": {
                "title": title,
                "confidence": confidence,
                "retry": True,
            },
        },
    )


def test_contextual_suggestion_used_for_unseen_failure_code() -> None:
    knowledge = TelemetryKnowledgeBase()
    knowledge.observe(
        _event(
            stage="preflight",
            task="demo",
            failure_code="preflight:demo:RuntimeError",
            error_type="RuntimeError",
            title="Install dependencies",
            confidence=0.35,
        )
    )

    suggestion = knowledge.suggest_fix(
        failure_code="preflight:demo:ValueError",
        error_type="ValueError",
        stage="preflight",
        task="demo",
    )

    assert suggestion is not None
    assert suggestion.title == "Install dependencies"


def test_specific_context_beats_generic_error_fix() -> None:
    knowledge = TelemetryKnowledgeBase()
    knowledge.observe(
        _event(
            stage="preflight",
            task="demo",
            failure_code="preflight:demo:RuntimeError",
            error_type="RuntimeError",
            title="Install dependencies",
            confidence=0.3,
        )
    )
    knowledge.observe(
        _event(
            stage="install",
            task="packages",
            failure_code="install:packages:RuntimeError",
            error_type="RuntimeError",
            title="Restart installation",
            confidence=0.95,
        )
    )

    suggestion = knowledge.suggest_fix(
        failure_code="preflight:demo:ValueError",
        error_type="RuntimeError",
        stage="preflight",
        task="demo",
    )

    assert suggestion is not None
    assert suggestion.title == "Install dependencies"


def test_error_type_fallback_when_no_context() -> None:
    knowledge = TelemetryKnowledgeBase()
    knowledge.observe(
        _event(
            stage="install",
            task="packages",
            failure_code="install:packages:RuntimeError",
            error_type="RuntimeError",
            title="Retry runtime fix",
            confidence=0.7,
        )
    )

    suggestion = knowledge.suggest_fix(
        failure_code="diagnostics:scan:RuntimeError",
        error_type="RuntimeError",
    )

    assert suggestion is not None
    assert suggestion.title == "Retry runtime fix"

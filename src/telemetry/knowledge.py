"""Simple knowledge base built on top of recorded telemetry events."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Optional

from .events import TelemetryEvent, TelemetryEventType


@dataclass
class FailureInsight:
    """Aggregated failure insight used for suggestion ranking."""

    occurrences: int
    fixes: Counter

    def top_fix(self) -> Optional[str]:
        if not self.fixes:
            return None
        return self.fixes.most_common(1)[0][0]


class TelemetryKnowledgeBase:
    """In-memory aggregator of telemetry signals for troubleshooting hints."""

    def __init__(self) -> None:
        self._failures: MutableMapping[str, FailureInsight] = {}

    def observe(self, event: TelemetryEvent) -> None:
        if event.type is not TelemetryEventType.TASK:
            return
        metadata = event.metadata
        failure_code = metadata.get("failure_code")
        suggested_fix = metadata.get("suggested_fix")
        status = metadata.get("status")
        if not failure_code or status != "failed":
            return
        insight = self._failures.get(failure_code)
        if insight is None:
            insight = FailureInsight(occurrences=0, fixes=Counter())
            self._failures[failure_code] = insight
        insight.occurrences += 1
        if suggested_fix:
            insight.fixes[suggested_fix] += 1

    def load(self, events: Iterable[TelemetryEvent]) -> None:
        for event in events:
            self.observe(event)

    def suggest_fix(self, *, failure_code: Optional[str] = None, error_type: Optional[str] = None) -> Optional[str]:
        """Return the most likely fix string for the failure signature."""

        if failure_code and failure_code in self._failures:
            return self._failures[failure_code].top_fix()
        if error_type:
            candidates = [
                insight.top_fix()
                for code, insight in self._failures.items()
                if code.endswith(f":{error_type}")
            ]
            for suggestion in candidates:
                if suggestion:
                    return suggestion
        return None

    def summarize(self) -> Dict[str, Mapping[str, object]]:
        return {
            code: {
                "occurrences": insight.occurrences,
                "top_fix": insight.top_fix(),
            }
            for code, insight in self._failures.items()
        }


__all__ = ["TelemetryKnowledgeBase", "FailureInsight"]

"""Opt-in consent management for telemetry collection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Optional
import json
import os

from .events import TelemetryEvent, TelemetryEventType


@dataclass
class ConsentDecision:
    """Recorded decision about telemetry participation."""

    granted: bool
    source: str

    def to_event(self) -> TelemetryEvent:
        return TelemetryEvent(
            TelemetryEventType.CONSENT,
            metadata={"granted": self.granted, "source": self.source},
        )


class TelemetryConsentManager:
    """Persisted consent preferences with environment overrides."""

    def __init__(self, *, storage_path: Path | None = None) -> None:
        self.storage_path = Path(storage_path or Path.home() / ".coolbox" / "telemetry-consent.json")

    def _load_state(self) -> Optional[Mapping[str, object]]:
        if not self.storage_path.exists():
            return None
        try:
            text = self.storage_path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            return json.loads(text or "{}")
        except json.JSONDecodeError:
            return None

    def _save_state(self, granted: bool) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"granted": granted}, indent=2)
        self.storage_path.write_text(payload, encoding="utf-8")

    def current_decision(self) -> ConsentDecision | None:
        env = os.getenv("COOLBOX_TELEMETRY")
        if env is not None:
            granted = env.strip().lower() in {"1", "true", "yes", "on"}
            return ConsentDecision(granted=granted, source="env")
        state = self._load_state()
        if not state:
            return None
        granted = bool(state.get("granted", False))
        return ConsentDecision(granted=granted, source="stored")

    def ensure_opt_in(self, *, default: Literal["deny", "allow"] = "deny") -> ConsentDecision:
        decision = self.current_decision()
        if decision is not None:
            return decision
        granted = default == "allow"
        self._save_state(granted)
        return ConsentDecision(granted=granted, source="default")

    def opt_in(self) -> ConsentDecision:
        self._save_state(True)
        return ConsentDecision(granted=True, source="user")

    def opt_out(self) -> ConsentDecision:
        self._save_state(False)
        return ConsentDecision(granted=False, source="user")


__all__ = ["TelemetryConsentManager", "ConsentDecision"]

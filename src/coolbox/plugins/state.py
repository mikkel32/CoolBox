"""Persistence helpers for plugin initialization outcomes."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence

from coolbox.paths import artifacts_dir, ensure_directory

_LOGGER = logging.getLogger("coolbox.plugins.state")
_STATE_FILENAME = "plugin_init_state.json"


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip()) if value.strip() else default
        except ValueError:
            return default
    return default


@dataclass(frozen=True, slots=True)
class PluginInitState:
    """Snapshot of the most recent plugin initialization outcome."""

    status: Literal["success", "failed"]
    updated_at: float
    profile: str | None = None
    recovery_profile: str | None = None
    plugin_id: str | None = None
    message: str | None = None
    hints: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "updated_at": self.updated_at,
        }
        if self.profile is not None:
            payload["profile"] = self.profile
        if self.recovery_profile is not None:
            payload["recovery_profile"] = self.recovery_profile
        if self.plugin_id is not None:
            payload["plugin_id"] = self.plugin_id
        if self.message is not None:
            payload["message"] = self.message
        if self.hints:
            payload["hints"] = list(self.hints)
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "PluginInitState":
        status = str(payload.get("status", "")).strip()
        if status not in {"success", "failed"}:
            raise ValueError(f"Invalid plugin init status: {status!r}")
        timestamp = _coerce_float(payload.get("updated_at"), 0.0)
        profile = payload.get("profile")
        recovery = payload.get("recovery_profile")
        plugin_id = payload.get("plugin_id")
        message = payload.get("message")
        hints = payload.get("hints")
        return cls(
            status=status,  # type: ignore[arg-type]
            updated_at=timestamp,
            profile=str(profile) if isinstance(profile, str) else None,
            recovery_profile=str(recovery) if isinstance(recovery, str) else None,
            plugin_id=str(plugin_id) if isinstance(plugin_id, str) else None,
            message=str(message) if isinstance(message, str) else None,
            hints=tuple(str(hint) for hint in hints) if isinstance(hints, Iterable) else (),
        )


def _state_path() -> Path:
    return ensure_directory(artifacts_dir()) / _STATE_FILENAME


def load_plugin_init_state() -> PluginInitState | None:
    """Return the last recorded plugin initialization state, if any."""

    path = _state_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive parsing
        _LOGGER.debug("Failed to load plugin init state", exc_info=exc)
        return None
    if not isinstance(payload, Mapping):
        return None
    try:
        return PluginInitState.from_payload(payload)
    except Exception as exc:  # pragma: no cover - defensive parsing
        _LOGGER.debug("Invalid plugin init payload", exc_info=exc)
        return None


def _write_state(state: PluginInitState) -> None:
    path = _state_path()
    try:
        path.write_text(json.dumps(state.to_payload(), indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive persistence
        _LOGGER.debug("Failed to persist plugin init state", exc_info=exc)


def record_plugin_init_success(profile: str | None = None) -> PluginInitState:
    """Persist a successful plugin initialization attempt."""

    state = PluginInitState(status="success", updated_at=time.time(), profile=profile)
    _write_state(state)
    return state


def record_plugin_init_failure(
    *,
    profile: str,
    plugin_id: str,
    message: str,
    recovery_profile: str | None,
    hints: Sequence[str] | None = None,
) -> PluginInitState:
    """Persist a failed plugin initialization attempt."""

    normalized_hints = tuple(str(hint) for hint in (hints or ()) if str(hint))
    state = PluginInitState(
        status="failed",
        updated_at=time.time(),
        profile=profile,
        recovery_profile=recovery_profile,
        plugin_id=plugin_id,
        message=message,
        hints=normalized_hints,
    )
    _write_state(state)
    return state


def clear_plugin_init_state() -> None:
    """Remove any persisted plugin initialization state."""

    path = _state_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception as exc:  # pragma: no cover - defensive cleanup
        _LOGGER.debug("Failed to clear plugin init state", exc_info=exc)


__all__ = [
    "PluginInitState",
    "clear_plugin_init_state",
    "load_plugin_init_state",
    "record_plugin_init_failure",
    "record_plugin_init_success",
]

"""Capability governance and permission management for plugin workers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Dict, Iterable, Optional

from .core import (
    CapabilityGrantState,
    SecurityPluginsSnapshot,
    WorkerSecurityInsight,
)


@dataclass(slots=True)
class CapabilityGrant:
    """Mutable state for a single capability grant."""

    capability: str
    state: str = "allowed"
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    requested_at: Optional[datetime] = None
    request_reason: Optional[str] = None
    pending: bool = False
    auto_downgrade_after: Optional[timedelta] = field(default_factory=lambda: timedelta(minutes=15))
    allow_once: bool = False
    requires_admin: bool = True

    def to_state(self) -> CapabilityGrantState:
        """Return an immutable snapshot for UI consumption."""

        auto_seconds = (
            float(self.auto_downgrade_after.total_seconds())
            if self.auto_downgrade_after
            else None
        )
        return CapabilityGrantState(
            capability=self.capability,
            state=self.state,
            expires_at=self.expires_at,
            last_used_at=self.last_used_at,
            requested_at=self.requested_at,
            request_reason=self.request_reason,
            pending=self.pending,
            auto_downgrade_after=auto_seconds,
            requires_admin=self.requires_admin,
        )


@dataclass(slots=True)
class WorkerRegistration:
    """Metadata describing a registered worker."""

    plugin_id: str
    display_name: str
    provides: tuple[str, ...]
    requires: tuple[str, ...]
    sandbox: tuple[str, ...]


class PermissionManager:
    """Track worker capability grants and outstanding permission requests."""

    _MAX_SYSCALLS = 20

    def __init__(self) -> None:
        self._lock = RLock()
        self._registrations: Dict[str, WorkerRegistration] = {}
        self._grants: Dict[str, Dict[str, CapabilityGrant]] = {}
        self._pending: set[tuple[str, str]] = set()
        self._supervisor = None
        self._syscalls: Dict[str, deque[str]] = {}

    # ------------------------------------------------------------------ registry
    def register_worker(
        self,
        plugin_id: str,
        *,
        display_name: Optional[str] = None,
        provides: Iterable[str] = (),
        requires: Iterable[str] = (),
        sandbox: Iterable[str] = (),
    ) -> None:
        """Register *plugin_id* with declared capability metadata."""

        registration = WorkerRegistration(
            plugin_id=plugin_id,
            display_name=display_name or plugin_id,
            provides=tuple(sorted(dict.fromkeys(provides))),
            requires=tuple(sorted(dict.fromkeys(requires))),
            sandbox=tuple(sorted(dict.fromkeys(sandbox))),
        )
        with self._lock:
            self._registrations[plugin_id] = registration
            grants = self._grants.setdefault(plugin_id, {})
            for capability in registration.requires:
                grants.setdefault(capability, CapabilityGrant(capability))
            if plugin_id not in self._syscalls:
                self._syscalls[plugin_id] = deque(maxlen=self._MAX_SYSCALLS)

    def unregister_worker(self, plugin_id: str) -> None:
        with self._lock:
            self._registrations.pop(plugin_id, None)
            self._grants.pop(plugin_id, None)
            self._pending = {item for item in self._pending if item[0] != plugin_id}
            self._syscalls.pop(plugin_id, None)

    def bind_supervisor(self, supervisor) -> None:
        """Bind to *supervisor* so updates propagate to running workers."""

        self._supervisor = supervisor

    # ---------------------------------------------------------------- capability
    def request_capability(
        self,
        plugin_id: str,
        capability: str,
        *,
        reason: Optional[str] = None,
        requires_admin: bool = True,
    ) -> CapabilityGrantState:
        """Record a pending request for *capability*."""

        now = datetime.now(timezone.utc)
        with self._lock:
            grant = self._ensure_grant(plugin_id, capability)
            grant.pending = True
            grant.requested_at = now
            grant.request_reason = reason
            grant.requires_admin = requires_admin
            grant.state = "pending"
            self._pending.add((plugin_id, capability))
            self._record_syscall(plugin_id, f"requested {capability}")
            return grant.to_state()

    def resolve_request(
        self,
        plugin_id: str,
        capability: str,
        decision: str,
        *,
        duration: Optional[timedelta] = None,
    ) -> CapabilityGrantState:
        """Resolve a pending capability request."""

        decision = decision.lower()
        now = datetime.now(timezone.utc)
        with self._lock:
            grant = self._ensure_grant(plugin_id, capability)
            grant.pending = False
            grant.requested_at = grant.requested_at or now
            self._pending.discard((plugin_id, capability))
            if decision == "allow_once":
                grant.state = "allowed"
                grant.allow_once = True
                grant.expires_at = None
            elif decision in {"allow", "allow_always"}:
                grant.state = "allowed"
                grant.allow_once = False
                grant.expires_at = None
            elif decision in {"allow_15", "allow_temporal", "allow_temporary"}:
                grant.state = "allowed"
                grant.allow_once = False
                grant.expires_at = now + (duration or timedelta(minutes=15))
            elif decision in {"downgrade", "limited"}:
                grant.state = "downgraded"
                grant.allow_once = False
                grant.expires_at = None
            elif decision in {"deny", "revoke"}:
                grant.state = "revoked"
                grant.allow_once = False
                grant.expires_at = None
            else:
                raise ValueError(f"Unknown decision '{decision}'")
            grant.request_reason = None
            self._notify_supervisor_locked(plugin_id)
            self._record_syscall(plugin_id, f"{decision} {capability}")
            return grant.to_state()

    def allow_once(self, plugin_id: str, capability: str) -> CapabilityGrantState:
        return self.resolve_request(plugin_id, capability, "allow_once")

    def allow_for(
        self, plugin_id: str, capability: str, duration: timedelta
    ) -> CapabilityGrantState:
        return self.resolve_request(
            plugin_id, capability, "allow_temporary", duration=duration
        )

    def allow_always(self, plugin_id: str, capability: str) -> CapabilityGrantState:
        return self.resolve_request(plugin_id, capability, "allow_always")

    def downgrade(self, plugin_id: str, capability: str) -> CapabilityGrantState:
        return self.resolve_request(plugin_id, capability, "downgrade")

    def revoke(self, plugin_id: str, capability: str) -> CapabilityGrantState:
        return self.resolve_request(plugin_id, capability, "revoke")

    def record_activity(self, plugin_id: str, capability: str) -> None:
        with self._lock:
            grant = self._ensure_grant(plugin_id, capability)
            now = datetime.now(timezone.utc)
            grant.last_used_at = now
            if grant.allow_once:
                grant.state = "revoked"
                grant.allow_once = False
            if grant.expires_at and grant.expires_at < now:
                grant.state = "revoked"
                grant.expires_at = None
            self._notify_supervisor_locked(plugin_id)

    # ----------------------------------------------------------------- snapshot
    def snapshot(self) -> SecurityPluginsSnapshot:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._expire_inactive_locked(now)
            runtime, syscalls = self._collect_supervisor_state()
            workers: list[WorkerSecurityInsight] = []
            pending: list[CapabilityGrantState] = []
            for plugin_id, registration in sorted(self._registrations.items()):
                grants = [
                    grant.to_state()
                    for grant in self._grants.get(plugin_id, {}).values()
                ]
                grants.sort(key=lambda state: state.capability)
                runtime_info = runtime.get(plugin_id)
                open_ports: tuple[str, ...]
                process_tree: tuple[str, ...]
                pid: Optional[int]
                status: Optional[str]
                if runtime_info is None:
                    open_ports = ()
                    process_tree = ()
                    pid = None
                    status = None
                else:
                    open_ports = tuple(runtime_info.get("open_ports", ()))
                    process_tree = tuple(runtime_info.get("process_tree", ()))
                    pid = runtime_info.get("pid")
                    status = runtime_info.get("status")
                recent = tuple(syscalls.get(plugin_id, ()))
                workers.append(
                    WorkerSecurityInsight(
                        plugin_id=plugin_id,
                        display_name=registration.display_name,
                        provides=registration.provides,
                        requires=registration.requires,
                        sandbox=registration.sandbox,
                        grants=tuple(grants),
                        open_ports=open_ports,
                        recent_syscalls=recent,
                        process_tree=process_tree,
                        pid=pid,
                        status=status,
                    )
                )
                for state in grants:
                    if state.pending:
                        pending.append(state)
            return SecurityPluginsSnapshot(
                generated_at=now,
                workers=tuple(workers),
                pending_requests=tuple(pending),
            )

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    # -------------------------------------------------------------- syscalls log
    def record_syscall_summary(self, plugin_id: str, summary: str) -> None:
        with self._lock:
            self._record_syscall(plugin_id, summary)

    # ------------------------------------------------------------------ helpers
    def _ensure_grant(self, plugin_id: str, capability: str) -> CapabilityGrant:
        grants = self._grants.setdefault(plugin_id, {})
        return grants.setdefault(capability, CapabilityGrant(capability))

    def _record_syscall(self, plugin_id: str, summary: str) -> None:
        queue = self._syscalls.setdefault(
            plugin_id, deque(maxlen=self._MAX_SYSCALLS)
        )
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        queue.appendleft(f"[{timestamp}] {summary}")

    def _collect_supervisor_state(self) -> tuple[dict, dict[str, tuple[str, ...]]]:
        runtime: dict = {}
        syscalls: dict[str, tuple[str, ...]] = {}
        supervisor = self._supervisor
        if supervisor is None:
            return runtime, syscalls
        runtime_method = getattr(supervisor, "security_runtime_snapshot", None)
        if callable(runtime_method):
            try:
                runtime = runtime_method()
            except Exception:
                runtime = {}
        syscall_method = getattr(supervisor, "recent_syscalls_snapshot", None)
        if callable(syscall_method):
            try:
                syscalls = {
                    key: tuple(value)
                    for key, value in syscall_method().items()
                }
            except Exception:
                syscalls = {}
        else:
            syscalls = {
                plugin_id: tuple(queue)
                for plugin_id, queue in self._syscalls.items()
            }
        return runtime, syscalls

    def _notify_supervisor_locked(self, plugin_id: str) -> None:
        supervisor = self._supervisor
        if supervisor is None:
            return
        callback = getattr(supervisor, "apply_permission_update", None)
        if not callable(callback):
            return
        grants = self._grants.get(plugin_id, {})
        payload = {name: grant.state for name, grant in grants.items()}
        try:
            callback(plugin_id, payload)
        except Exception:
            # Supervisor updates are best-effort for UI visibility.
            pass

    def _expire_inactive_locked(self, now: datetime) -> None:
        dirty: set[str] = set()
        for plugin_id, grants in self._grants.items():
            for grant in grants.values():
                if grant.pending:
                    continue
                if grant.expires_at and grant.expires_at < now:
                    if grant.state != "revoked":
                        grant.state = "revoked"
                        dirty.add(plugin_id)
                    grant.expires_at = None
                    continue
                if (
                    grant.auto_downgrade_after
                    and grant.last_used_at
                    and now - grant.last_used_at > grant.auto_downgrade_after
                    and grant.state == "allowed"
                ):
                    grant.state = "downgraded"
                    dirty.add(plugin_id)
        for plugin_id in dirty:
            self._notify_supervisor_locked(plugin_id)


_MANAGER: PermissionManager | None = None


def get_permission_manager() -> PermissionManager:
    """Return the global :class:`PermissionManager` instance."""

    global _MANAGER
    if _MANAGER is None:
        _MANAGER = PermissionManager()
    return _MANAGER


def reset_permission_manager() -> None:
    """Reset the singleton for test isolation."""

    global _MANAGER
    _MANAGER = PermissionManager()


__all__ = [
    "CapabilityGrant",
    "PermissionManager",
    "get_permission_manager",
    "reset_permission_manager",
]


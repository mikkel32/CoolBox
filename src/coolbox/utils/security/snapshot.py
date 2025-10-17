"""Snapshot helpers combining firewall and Defender state."""
from __future__ import annotations

from .admin import is_admin
from .core import DefenderStatus, SecuritySnapshot, guarded_call
from .defender_control import get_defender_status
from .firewall_control import detect_firewall_blockers, is_firewall_enabled


def get_security_snapshot() -> SecuritySnapshot:
    """Collect a coherent snapshot for the Security Center dialog."""

    admin = guarded_call(is_admin, False)
    firewall = guarded_call(is_firewall_enabled, None)
    firewall_blockers = detect_firewall_blockers()
    defender = guarded_call(
        get_defender_status,
        DefenderStatus(None, None, None, None, None, ()),
    )
    return SecuritySnapshot(
        admin=admin,
        firewall_enabled=firewall,
        defender=defender,
        firewall_blockers=firewall_blockers,
    )


__all__ = ["get_security_snapshot"]

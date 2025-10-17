"""Compatibility wrapper for :mod:`coolbox.utils.security.firewall`."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .security.firewall import (
        _MAC_PLIST_BOOTSTRAP_TEMPLATE,
        _mac_defaults_plist_bootstrap,
        _mac_defaults_plist_cached,
        _mac_defaults_plist_value,
        _mac_defaults_plist_write,
        _mac_defaults_read_int,
        _mac_defaults_write_int,
        _mac_detect_tooling_cached,
        _mac_firewall_global_state,
        _mac_launchctl_refresh,
        _mac_query_socketfilterfw,
        _mac_set_firewall_enabled,
        _mac_tooling,
        _run_ex,
        ensure_admin,
        get_firewall_status,
        is_firewall_enabled,
        is_firewall_supported,
        set_firewall_enabled,
        MacFirewallTooling,
    )
else:
    from .security.firewall import *  # type: ignore F401,F403
    from .security import firewall as _firewall_module

    _compat_names = {
        "_MAC_PLIST_BOOTSTRAP_TEMPLATE",
        "_mac_defaults_plist_bootstrap",
        "_mac_defaults_plist_cached",
        "_mac_defaults_plist_value",
        "_mac_defaults_plist_write",
        "_mac_defaults_read_int",
        "_mac_defaults_write_int",
        "_mac_detect_tooling_cached",
        "_mac_firewall_global_state",
        "_mac_launchctl_refresh",
        "_mac_query_socketfilterfw",
        "_mac_set_firewall_enabled",
        "_mac_tooling",
        "_run_ex",
        "ensure_admin",
        "get_firewall_status",
        "is_firewall_enabled",
        "is_firewall_supported",
        "set_firewall_enabled",
        "MacFirewallTooling",
    }

    for _name in _compat_names:
        if hasattr(_firewall_module, _name):
            globals()[_name] = getattr(_firewall_module, _name)

    _fallback_exports = [name for name in globals() if not name.startswith("__")]
    __all__ = sorted(
        set(getattr(_firewall_module, "__all__", []))
        | set(_compat_names)
        | set(_fallback_exports)
    )

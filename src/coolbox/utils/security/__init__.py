"""Security utilities organized into focused submodules."""
from __future__ import annotations

import sys
import types
from importlib import import_module

from . import platform as platform_state
from .admin import is_admin as _is_admin, relaunch_security_center
from .core import (
    ActionOutcome,
    DefenderStatus,
    RunResult,
    SecuritySnapshot,
    run_command,
    run_command_background,
    run_powershell,
)
from .defender_control import (
    defender_service_status,
    detect_defender_blockers,
    ensure_defender_autostart,
    get_defender_status,
    is_defender_realtime_on,
    set_defender_enabled,
    set_defender_realtime,
    start_defender_service,
    stop_defender_service,
)
from .firewall_control import (
    detect_firewall_blockers,
    is_firewall_enabled,
    set_firewall_enabled,
)
from .snapshot import get_security_snapshot


def is_admin() -> bool:
    """Return ``True`` when the current process has administrator rights."""

    return _is_admin()


def ensure_admin() -> bool:
    """Compatibility wrapper that delegates to :func:`is_admin`."""

    return is_admin()


_IS_WINDOWS = platform_state.IS_WINDOWS
_IS_MAC = platform_state.IS_MAC
_NETSH_EXE = platform_state.NETSH_EXE
_SC_EXE = platform_state.SC_EXE
_POWERSHELL_EXE = platform_state.POWERSHELL_EXE

# Backwards-compatible entry points expected by older tests.
_run = run_command
_run_ps = run_powershell


class _SecurityModule(types.ModuleType):
    """Module type that keeps platform flags in sync for legacy shims."""

    def __setattr__(self, name: str, value):  # type: ignore[override]
        if name == "_IS_WINDOWS":
            platform_state.IS_WINDOWS = value
        elif name == "_IS_MAC":
            platform_state.IS_MAC = value
        elif name == "_NETSH_EXE":
            platform_state.NETSH_EXE = value
        elif name == "_SC_EXE":
            platform_state.SC_EXE = value
        elif name == "_POWERSHELL_EXE":
            platform_state.POWERSHELL_EXE = value
        elif name == "is_admin":
            from . import admin as admin_module

            admin_module.is_admin = value  # type: ignore[assignment]
        elif name == "_run":
            from . import defender_control, firewall_control

            firewall_control.RUN_COMMAND = value
            defender_control.RUN_COMMAND = value
        elif name == "_run_ps":
            from . import defender_control

            defender_control.RUN_POWERSHELL = value
        elif name == "get_defender_status":
            from . import defender_control

            defender_control.get_defender_status = value  # type: ignore[assignment]
        elif name == "detect_defender_blockers":
            from . import defender_control

            defender_control.detect_defender_blockers = value  # type: ignore[assignment]
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _SecurityModule

__all__ = [
    "ActionOutcome",
    "DefenderStatus",
    "RunResult",
    "SecuritySnapshot",
    "defender_service_status",
    "detect_defender_blockers",
    "detect_firewall_blockers",
    "ensure_admin",
    "ensure_defender_autostart",
    "get_defender_status",
    "get_security_snapshot",
    "is_admin",
    "is_defender_realtime_on",
    "is_firewall_enabled",
    "relaunch_security_center",
    "run_command_background",
    "set_defender_enabled",
    "set_defender_realtime",
    "set_firewall_enabled",
    "start_defender_service",
    "stop_defender_service",
    "_IS_MAC",
    "_IS_WINDOWS",
    "_NETSH_EXE",
    "_POWERSHELL_EXE",
    "_SC_EXE",
    "_run",
    "_run_ps",
]


def __getattr__(name: str):
    if name == "defender_utils":
        module = import_module("coolbox.utils.security.defender")
        globals()[name] = module
        return module
    if name == "firewall_utils":
        module = import_module("coolbox.utils.security.firewall")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()) | {"defender_utils", "firewall_utils"})

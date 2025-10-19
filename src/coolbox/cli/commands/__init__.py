"""Concrete command implementations for the CoolBox CLI."""
from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, Any

__all__ = [
    "exe_inspector",
    "kill_by_click",
    "network_scan",
    "process_monitor",
    "preview_plugin",
    "run_vm_debug",
    "security_center",
    "security_center_hidden",
    "setup",
    "recipes",
    "workspace_bundle",
    "load",
]

_COMMAND_NAMES = {
    "exe_inspector",
    "kill_by_click",
    "network_scan",
    "process_monitor",
    "preview_plugin",
    "run_vm_debug",
    "security_center",
    "security_center_hidden",
    "setup",
    "recipes",
    "workspace_bundle",
}

if TYPE_CHECKING:
    from . import exe_inspector as exe_inspector
    from . import kill_by_click as kill_by_click
    from . import network_scan as network_scan
    from . import process_monitor as process_monitor
    from . import preview_plugin as preview_plugin
    from . import run_vm_debug as run_vm_debug
    from . import security_center as security_center
    from . import security_center_hidden as security_center_hidden
    from . import setup as setup
    from . import workspace_bundle as workspace_bundle


def load(name: str) -> ModuleType:
    """Dynamically import a command module by *name*."""

    if name not in _COMMAND_NAMES:
        raise ValueError(f"Unknown command: {name}")
    return import_module(f"{__name__}.{name}")


def __getattr__(name: str) -> Any:
    if name in _COMMAND_NAMES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()) | _COMMAND_NAMES)

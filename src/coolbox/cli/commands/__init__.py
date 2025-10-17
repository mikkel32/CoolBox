"""Concrete command implementations for the CoolBox CLI."""
from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any

__all__ = [
    "exe_inspector",
    "kill_by_click",
    "network_scan",
    "process_monitor",
    "run_vm_debug",
    "security_center",
    "security_center_hidden",
    "setup",
    "load",
]

_COMMAND_NAMES = {
    "exe_inspector",
    "kill_by_click",
    "network_scan",
    "process_monitor",
    "run_vm_debug",
    "security_center",
    "security_center_hidden",
    "setup",
}


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

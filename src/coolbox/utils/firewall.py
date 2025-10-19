"""Compatibility wrapper for :mod:`coolbox.utils.security.firewall`."""
from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING


def _load_firewall_module() -> ModuleType:
    """Return a freshly imported security firewall module."""

    module = importlib.import_module("coolbox.utils.security.firewall")
    return importlib.reload(module)


def _reexport(module: ModuleType) -> tuple[str, ...]:
    """Copy attributes from *module* into this namespace."""

    exported: list[str] = []
    for name in dir(module):
        if name.startswith("__") and name.endswith("__"):
            continue
        globals()[name] = getattr(module, name)
        exported.append(name)
    return tuple(dict.fromkeys(exported))


_TARGET_MODULE = _load_firewall_module()
_reexport(_TARGET_MODULE)

if TYPE_CHECKING:  # pragma: no cover - typing assistance for re-exported members
    from coolbox.utils.security.firewall import (
        FirewallStatus,
        MacFirewallTooling,
        _MAC_PLIST_BOOTSTRAP_TEMPLATE,
        _mac_defaults_plist_bootstrap,
        _mac_defaults_plist_cached,
        _mac_defaults_plist_value,
        _mac_defaults_plist_write,
        _mac_defaults_read_int,
        _mac_defaults_write_int,
        _mac_detect_tooling_cached,
        _mac_firewall_global_state,
        _mac_query_socketfilterfw,
        _mac_set_firewall_enabled,
        _run_ex,
        get_firewall_status,
        is_firewall_enabled,
        is_firewall_supported,
        set_firewall_enabled,
    )


class _FirewallProxy(ModuleType):
    """Mirror attribute updates onto the underlying firewall module."""

    def __getattr__(self, name: str):  # type: ignore[override]
        try:
            return super().__getattribute__(name)
        except AttributeError:
            return getattr(_TARGET_MODULE, name)

    def __setattr__(self, name: str, value):  # type: ignore[override]
        target = _TARGET_MODULE
        if (
            name == "_TARGET_MODULE"
            or name.startswith("__")
            or getattr(target, "__name__", None) == __name__
        ):
            super().__setattr__(name, value)
            return
        setattr(target, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name: str):  # type: ignore[override]
        target = _TARGET_MODULE
        if (
            name == "_TARGET_MODULE"
            or name.startswith("__")
            or getattr(target, "__name__", None) == __name__
        ):
            super().__delattr__(name)
            return
        if hasattr(target, name):
            delattr(target, name)
        super().__delattr__(name)


_module_obj = sys.modules.get(__name__)
if _module_obj is not None:
    _module_obj.__class__ = _FirewallProxy

del importlib, ModuleType, _load_firewall_module, _reexport

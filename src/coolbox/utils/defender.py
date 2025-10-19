"""Compatibility wrapper for :mod:`coolbox.utils.security.defender`."""
from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING


def _load_defender_module() -> ModuleType:
    """Return a freshly imported security defender module."""

    module = importlib.import_module("coolbox.utils.security.defender")
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


_TARGET_MODULE = _load_defender_module()
_reexport(_TARGET_MODULE)

if TYPE_CHECKING:  # pragma: no cover - typing hints for re-exported helpers
    from coolbox.utils.security.defender import (
        get_defender_status,
        _ps,
        _run_ex,
        ensure_admin,
        is_defender_supported,
        is_defender_enabled,
        set_defender_enabled,
    )


class _DefenderProxy(ModuleType):
    """Mirror attribute updates onto the underlying defender module."""

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
    _module_obj.__class__ = _DefenderProxy


del importlib, ModuleType, _load_defender_module, _reexport

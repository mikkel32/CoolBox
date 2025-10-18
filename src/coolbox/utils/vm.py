"""Compatibility wrapper for :mod:`coolbox.utils.system.vm`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

import importlib
import sys
from types import ModuleType


def _load_vm_module() -> ModuleType:
    """Return a freshly imported VM helper module."""

    module = importlib.import_module("coolbox.utils.system.vm")
    return importlib.reload(module)


def _reexport(module: ModuleType) -> tuple[str, ...]:
    exported: list[str] = []
    for name in dir(module):
        if name.startswith("__") and name.endswith("__"):
            continue
        globals()[name] = getattr(module, name)
        exported.append(name)
    return tuple(dict.fromkeys(exported))


_TARGET_MODULE = _load_vm_module()
__all__ = _reexport(_TARGET_MODULE)


class _VMProxy(ModuleType):
    """Mirror attribute updates onto the underlying VM module."""

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
    _module_obj.__class__ = _VMProxy


del importlib, ModuleType, _load_vm_module, _reexport

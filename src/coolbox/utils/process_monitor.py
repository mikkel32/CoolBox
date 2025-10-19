"""Compatibility wrapper for :mod:`coolbox.utils.processes.monitor`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

import importlib
import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING, cast


def _load_monitor_module() -> ModuleType:
    """Return a freshly imported process monitor module."""

    name = "coolbox.utils.processes.monitor"
    if name in sys.modules:
        importlib.invalidate_caches()
        del sys.modules[name]
    return importlib.import_module(name)


def _reexport(module: ModuleType) -> tuple[str, ...]:
    exported: list[str] = []
    for name in dir(module):
        if name.startswith("__") and name.endswith("__"):
            continue
        globals()[name] = getattr(module, name)
        exported.append(name)
    return tuple(dict.fromkeys(exported))


_TARGET_MODULE = _load_monitor_module()
__all__ = cast(tuple[str, ...], _reexport(_TARGET_MODULE))  # pyright: ignore[reportUnsupportedDunderOperation]

if TYPE_CHECKING:  # pragma: no cover - surface runtime exports for type checking
    from coolbox.utils.processes.monitor import ProcessEntry, ProcessWatcher


class _MonitorProxy(ModuleType):
    """Mirror attribute updates onto the underlying monitor module."""

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
    _module_obj.__class__ = _MonitorProxy


del importlib, ModuleType, _load_monitor_module, _reexport

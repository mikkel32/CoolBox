"""Native runtime manager that loads plugins directly in-process."""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import ExitStack, contextmanager
from typing import Iterator

from .base import PluginRuntimeManager, PluginWorker
from .environment import ensure_runtime_environment

from coolbox.plugins.manifest import PluginDefinition


@contextmanager
def _temporary_environment(overrides: dict[str, str]) -> Iterator[None]:
    if not overrides:
        yield
        return
    original = {key: os.environ.get(key) for key in overrides}
    try:
        os.environ.update({key: str(value) for key, value in overrides.items()})
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class NativeWorker(PluginWorker):
    """Worker that executes plugin code inside the host interpreter."""

    def __init__(self, definition: PluginDefinition, entrypoint: str, *, logger=None) -> None:
        self._entrypoint = entrypoint
        module, _, attr = entrypoint.partition(":")
        self._module_name = module
        self._attribute = attr or ""
        self._environment = dict(definition.runtime.environment)
        runtime_env = ensure_runtime_environment(definition)
        self._runtime_environment = runtime_env
        self.runtime_activation = runtime_env.activation
        super().__init__(definition, logger=logger)

    def _start(self):  # type: ignore[override]
        with ExitStack() as stack:
            if self.runtime_activation:
                stack.enter_context(self.runtime_activation.temporary())
            stack.enter_context(_temporary_environment(self._environment))
            module = importlib.import_module(self._module_name)
            target = getattr(module, self._attribute) if self._attribute else module
            plugin = target() if callable(target) else target
        return plugin

    def reload(self):  # type: ignore[override]
        self.shutdown()
        if self._module_name in sys.modules:
            importlib.reload(sys.modules[self._module_name])
        return super().reload()


class NativeRuntimeManager(PluginRuntimeManager):
    """Runtime manager for native plugins."""

    runtime_kind = "native"

    def create_worker(self, definition: PluginDefinition, *, logger=None) -> NativeWorker:  # type: ignore[override]
        entrypoint = definition.runtime.entrypoint or definition.runtime.handler or definition.runtime.module
        if not entrypoint:
            raise RuntimeError(
                f"Plugin '{definition.identifier}' missing native entrypoint declaration"
            )
        return NativeWorker(definition, entrypoint=entrypoint, logger=logger)


__all__ = ["NativeRuntimeManager", "NativeWorker"]

"""Base abstractions for plugin runtime managers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from logging import Logger

    from coolbox.plugins.manifest import PluginDefinition
    from coolbox.setup.plugins import SetupPlugin
    from .environment import RuntimeActivation


class PluginWorker(ABC):
    """Represents a sandboxed worker hosting a plugin implementation."""

    def __init__(self, definition: "PluginDefinition", *, logger: "Logger | None" = None) -> None:
        self.definition = definition
        self.logger = logger
        if not hasattr(self, "runtime_activation"):
            self.runtime_activation: "RuntimeActivation | None" = None
        self.plugin: "SetupPlugin" = self._start()

    @abstractmethod
    def _start(self) -> "SetupPlugin":
        """Instantiate the plugin within the sandbox."""

    def reload(self) -> "SetupPlugin":
        """Restart the worker and return the replacement plugin instance."""

        self.shutdown()
        self.plugin = self._start()
        return self.plugin

    def shutdown(self) -> None:
        """Terminate the worker if the plugin exposes a shutdown hook."""

        plugin = getattr(self, "plugin", None)
        if plugin is None:
            return
        closer = getattr(plugin, "shutdown", None)
        if callable(closer):  # pragma: no cover - defensive
            try:
                closer()
            except Exception:
                if self.logger:
                    self.logger.debug("Plugin shutdown hook failed", exc_info=True)


class PluginRuntimeManager(ABC):
    """Factory for plugin workers running under a specific runtime."""

    runtime_kind: str

    def supports(self, definition: "PluginDefinition") -> bool:
        return definition.runtime.kind == self.runtime_kind

    @abstractmethod
    def create_worker(
        self,
        definition: "PluginDefinition",
        *,
        logger: "Logger | None" = None,
    ) -> PluginWorker:
        """Create a worker for ``definition``."""


__all__ = ["PluginRuntimeManager", "PluginWorker"]

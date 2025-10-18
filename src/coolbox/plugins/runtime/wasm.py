"""WASM runtime manager placeholder for future sandbox support."""

from __future__ import annotations

from .base import PluginRuntimeManager, PluginWorker

from coolbox.plugins.manifest import PluginDefinition


class WasmWorker(PluginWorker):
    """Worker that proxies WASM plugins to a NullPlugin fallback."""

    def _start(self):  # type: ignore[override]
        from coolbox.setup.plugins import NullPlugin

        if self.logger:
            self.logger.warning(
                "WASM runtime for plugin '%s' is not available; falling back to null sandbox",
                self.definition.identifier,
            )
        return NullPlugin()


class WasmRuntimeManager(PluginRuntimeManager):
    """Runtime manager that would spawn WASM workers when supported."""

    runtime_kind = "wasm"

    def create_worker(self, definition: PluginDefinition, *, logger=None) -> WasmWorker:  # type: ignore[override]
        if not definition.runtime.module:
            raise RuntimeError(
                f"Plugin '{definition.identifier}' requires a 'module' declaration for wasm runtime"
            )
        return WasmWorker(definition, logger=logger)


__all__ = ["WasmRuntimeManager", "WasmWorker"]

"""WASM runtime manager placeholder for future sandbox support."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from coolbox.paths import project_root

from .base import PluginRuntimeManager, PluginWorker

from coolbox.plugins.manifest import PluginDefinition, RuntimeBuild


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
        module_path = _prepare_wasm_packaging(definition, logger=logger)
        if logger:
            logger.debug("Prepared WASM module for %s at %s", definition.identifier, module_path)
        return WasmWorker(definition, logger=logger)


__all__ = ["WasmRuntimeManager", "WasmWorker"]


def _prepare_wasm_packaging(definition: PluginDefinition, *, logger: logging.Logger | None) -> Path:
    packaging = definition.runtime.wasm
    module_ref: Path | None
    build: RuntimeBuild | None
    if packaging is not None:
        module_ref = packaging.module
        build = packaging.build
    elif definition.runtime.module:
        module_ref = Path(definition.runtime.module)
        build = definition.runtime.build
    else:
        raise RuntimeError(
            f"Plugin '{definition.identifier}' requires a 'module' declaration for wasm runtime"
        )
    module_path = _resolve_path(module_ref)
    if packaging is not None:
        packaging.module = module_path
    if module_path.exists():
        return module_path
    if build and build.steps:
        _run_build_steps(build, logger=logger)
    if not module_path.exists():
        raise RuntimeError(
            f"Plugin '{definition.identifier}' missing WASM module at {module_path} after build"
        )
    return module_path


def _run_build_steps(build: RuntimeBuild, *, logger: logging.Logger | None) -> None:
    for step in build.steps:
        if not step.command:
            continue
        env = os.environ.copy()
        env.update(step.environment)
        cwd = _resolve_path(step.cwd) if step.cwd else None
        cmd = " ".join(step.command) if step.shell else list(step.command)
        if logger:
            logger.info("Executing WASM build step %s", step.name)
        try:
            subprocess.run(
                cmd,
                check=True,
                shell=step.shell,
                cwd=str(cwd) if cwd else None,
                env=env,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - subprocess failure
            message = f"Build step '{step.name}' failed with exit code {exc.returncode}"
            if logger:
                logger.error(message)
            raise RuntimeError(message) from exc


def _resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (project_root() / path).resolve()

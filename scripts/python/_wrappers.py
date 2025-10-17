"""Shared helpers for compatibility wrappers around packaged CLI commands."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Awaitable, Callable, MutableMapping, Sequence

CommandMain = Callable[[Sequence[str] | None], None]
AsyncCommandMain = Callable[[Sequence[str] | None], Awaitable[None]]


def _ensure_project_root() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    project_str = str(project_root)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    return project_root

def _ensure_scripts_package() -> None:
    """Import the bootstrap helpers after ensuring the project root is visible."""

    _ensure_project_root()
    import_module("scripts.bootstrap")


def _load_bootstrap_helpers():
    _ensure_scripts_package()
    from scripts import ensure_cli_environment, expose_module

    return ensure_cli_environment, expose_module


def _load_command_module(namespace: MutableMapping[str, object], command: str):
    ensure_cli_environment, expose_module = _load_bootstrap_helpers()
    ensure_cli_environment()
    return expose_module(namespace, f"coolbox.cli.commands.{command}")


def sync_command(namespace: MutableMapping[str, object], command: str) -> CommandMain:
    """Return a synchronous entry point for ``command``."""

    loader = _load_command_module(namespace, command)

    def main(argv: Sequence[str] | None = None) -> None:
        module = loader()
        module.main(argv)

    return main


def async_command(namespace: MutableMapping[str, object], command: str) -> AsyncCommandMain:
    """Return an asynchronous entry point for ``command``."""

    loader = _load_command_module(namespace, command)

    async def main(argv: Sequence[str] | None = None) -> None:
        module = loader()
        await module.main(argv)

    return main


__all__ = ["async_command", "sync_command"]

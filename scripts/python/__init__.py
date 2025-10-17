"""Python entry points bundled with the CoolBox project."""
from __future__ import annotations

from scripts import ensure_cli_environment

ensure_cli_environment()

__all__ = ["ensure_cli_environment"]


def __getattr__(name: str):  # pragma: no cover - convenience proxy
    if name == "commands":
        from coolbox.cli import commands as _commands

        return _commands
    raise AttributeError(name)

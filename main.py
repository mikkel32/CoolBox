#!/usr/bin/env python3
"""Compatibility script that exposes the CoolBox CLI helpers."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from scripts import ensure_cli_environment, load_module

ensure_cli_environment()

if TYPE_CHECKING:  # pragma: no cover - imported for static analysis only
    from coolbox.cli import bootstrap as cli_bootstrap  # noqa: F401


class _CLIModule(Protocol):
    """Runtime surface used from :mod:`coolbox.cli`."""

    default_root: Callable[[], Path]

    def main(self, argv: Iterable[str] | None = None) -> None: ...

    def parse_requirements(self, path: Path) -> Iterable[str]: ...

    def missing_requirements(self, path: Path) -> list[str]: ...

    def requirements_satisfied(self, path: Path) -> bool: ...

    def compute_setup_state(self, root: Path | None = None) -> str: ...

    def run_setup_if_needed(self, root: Path | None = None) -> bool: ...

    def run_setup(self, recipe_name: str | None) -> None: ...


class _BootstrapModule(Protocol):
    """Subset of :mod:`coolbox.cli.bootstrap` reassigned at runtime."""

    compute_setup_state: Callable[[Path | None], str]
    missing_requirements: Callable[[Path], list[str]]
    parse_requirements: Callable[[Path], Iterable[str]]
    requirements_satisfied: Callable[[Path], bool]
    default_root: Callable[[], Path]

_cli = cast("_CLIModule", load_module("coolbox.cli"))
_cli_bootstrap = cast("_BootstrapModule", load_module("coolbox.cli.bootstrap"))

default_root: Callable[[], Path] = _cli.default_root


def main(argv: Iterable[str] | None = None) -> None:
    """Invoke the packaged CLI entry point."""

    _cli.main(argv)


# Backwards-compatible wrappers expected by tests and external scripts.
def _parse_requirements(path: Path):
    return _cli.parse_requirements(path)


def _missing_requirements(path: Path):
    return list(_cli.missing_requirements(path))


def _requirements_satisfied(path: Path) -> bool:
    return _cli.requirements_satisfied(path)


def _compute_setup_state(root: Path | None = None) -> str:
    return _cli.compute_setup_state(root)


def _run_setup_if_needed(root: Path | None = None) -> bool:
    bootstrap_ns: dict[str, object] = vars(_cli_bootstrap)
    keys = (
        "compute_setup_state",
        "missing_requirements",
        "parse_requirements",
        "requirements_satisfied",
        "default_root",
    )
    original_bindings = {name: bootstrap_ns[name] for name in keys}
    try:
        bootstrap_ns["compute_setup_state"] = _compute_setup_state
        bootstrap_ns["missing_requirements"] = _missing_requirements
        bootstrap_ns["parse_requirements"] = _parse_requirements
        bootstrap_ns["requirements_satisfied"] = _requirements_satisfied
        bootstrap_ns["default_root"] = default_root
        return _cli.run_setup_if_needed(root)
    finally:
        for name, value in original_bindings.items():
            bootstrap_ns[name] = value


def _run_setup(recipe_name: str | None) -> None:
    _cli.run_setup(recipe_name)


__all__ = [
    "_compute_setup_state",
    "_missing_requirements",
    "_parse_requirements",
    "_requirements_satisfied",
    "_run_setup",
    "_run_setup_if_needed",
    "default_root",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    import sys

    main(sys.argv[1:])

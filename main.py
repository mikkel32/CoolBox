#!/usr/bin/env python3
"""Compatibility script that exposes the CoolBox CLI helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from scripts import ensure_cli_environment, load_module

ensure_cli_environment()

_cli = load_module("coolbox.cli")
_cli_bootstrap = load_module("coolbox.cli.bootstrap")

default_root = _cli.default_root


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
    original_bindings = (
        _cli_bootstrap.compute_setup_state,
        _cli_bootstrap.missing_requirements,
        _cli_bootstrap.parse_requirements,
        _cli_bootstrap.requirements_satisfied,
        _cli_bootstrap.default_root,
    )

    try:
        _cli_bootstrap.compute_setup_state = _compute_setup_state  # type: ignore[assignment]
        _cli_bootstrap.missing_requirements = _missing_requirements  # type: ignore[assignment]
        _cli_bootstrap.parse_requirements = _parse_requirements  # type: ignore[assignment]
        _cli_bootstrap.requirements_satisfied = _requirements_satisfied  # type: ignore[assignment]
        _cli_bootstrap.default_root = default_root  # type: ignore[assignment]
        return _cli.run_setup_if_needed(root)
    finally:
        (
            _cli_bootstrap.compute_setup_state,
            _cli_bootstrap.missing_requirements,
            _cli_bootstrap.parse_requirements,
            _cli_bootstrap.requirements_satisfied,
            _cli_bootstrap.default_root,
        ) = original_bindings


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

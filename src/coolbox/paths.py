"""Centralized helpers for resolving project directories and assets."""
from __future__ import annotations

import os
from functools import lru_cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Iterable

_PROJECT_MARKERS: tuple[str, ...] = (
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "requirements.txt",
    ".git",
)


@lru_cache(maxsize=1)
def package_root() -> Path:
    """Return the installed package directory."""

    return Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def source_root() -> Path:
    """Return the ``src`` directory that contains :mod:`coolbox`."""

    return package_root().parent


def _looks_like_project(path: Path) -> bool:
    return any((path / marker).exists() for marker in _PROJECT_MARKERS)


@lru_cache(maxsize=1)
def project_root() -> Path:
    """Best-effort detection of the project checkout root."""

    env_root = os.environ.get("COOLBOX_PROJECT_ROOT")
    if env_root:
        candidate = Path(env_root).expanduser()
        if candidate.exists():
            return candidate

    src_parent = source_root().parent
    if _looks_like_project(src_parent):
        return src_parent

    cwd = Path.cwd()
    if _looks_like_project(cwd):
        return cwd

    return src_parent


@lru_cache(maxsize=1)
def artifacts_dir() -> Path:
    """Location for runtime artifact storage (may not exist)."""

    return project_root() / "artifacts"


@lru_cache(maxsize=1)
def scripts_dir() -> Path:
    """Location of auxiliary CLI scripts (may not exist)."""

    return project_root() / "scripts"


@lru_cache(maxsize=1)
def python_scripts_dir() -> Path:
    """Location of Python-based CLI helpers."""

    return scripts_dir() / "python"


@lru_cache(maxsize=1)
def dev_scripts_dir() -> Path:
    """Location of developer environment helpers (shell wrappers, etc.)."""

    return scripts_dir() / "dev"


def ensure_directory(path: Path) -> Path:
    """Create ``path`` if missing and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def assets_root() -> Traversable:
    """Return the resource container that stores bundled assets."""

    return resources.files("coolbox.assets")


def asset_path(*segments: Iterable[str] | str) -> Traversable:
    """Join ``segments`` under :func:`assets_root`.

    ``segments`` may be strings or iterables of strings and is flattened to
    produce the final path.
    """

    parts: list[str] = []
    for segment in segments:
        if isinstance(segment, str):
            parts.append(segment)
        else:
            parts.extend(segment)
    traversable: Traversable = assets_root()
    for part in parts:
        traversable = traversable.joinpath(part)
    return traversable

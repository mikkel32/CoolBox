"""Bootstrap helpers for legacy CoolBox entry points and scripts."""
from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, MutableMapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPTS_ROOT = Path(__file__).resolve().parent
PYTHON_SCRIPTS_ROOT = SCRIPTS_ROOT / "python"
DEV_SCRIPTS_ROOT = SCRIPTS_ROOT / "dev"


def _iter_paths(extra_paths: Iterable[Path] | None = None) -> Iterable[Path]:
    yield PROJECT_ROOT
    yield SRC_ROOT
    if extra_paths:
        yield from extra_paths


def ensure_cli_environment(extra_paths: Iterable[Path] | None = None) -> None:
    """Ensure the ``src`` tree and optional paths are importable."""

    for path in _iter_paths(extra_paths):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


def load_module(module_name: str, *, extra_paths: Iterable[Path] | None = None) -> ModuleType:
    """Return ``module_name`` after bootstrapping the CLI environment."""

    ensure_cli_environment(extra_paths)
    return import_module(module_name)


def expose_module(
    namespace: MutableMapping[str, Any],
    module_name: str,
    *,
    extra_paths: Iterable[Path] | None = None,
) -> Callable[[], ModuleType]:
    """Attach ``__getattr__``/``__dir__`` hooks that proxy ``module_name``."""

    cache: dict[str, ModuleType] = {}

    def _load() -> ModuleType:
        module = cache.get("module")
        if module is None:
            module = load_module(module_name, extra_paths=extra_paths)
            cache["module"] = module
        return module

    def __getattr__(name: str) -> Any:
        return getattr(_load(), name)

    def __dir__() -> list[str]:
        return sorted(set(namespace) | set(dir(_load())))

    namespace["__getattr__"] = __getattr__
    namespace["__dir__"] = __dir__
    return _load


__all__ = [
    "DEV_SCRIPTS_ROOT",
    "PROJECT_ROOT",
    "PYTHON_SCRIPTS_ROOT",
    "SCRIPTS_ROOT",
    "SRC_ROOT",
    "ensure_cli_environment",
    "expose_module",
    "load_module",
]

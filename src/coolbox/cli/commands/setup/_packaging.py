"""Helpers for inspecting packaging metadata and hooks."""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

__all__ = ["supports_native_builds"]

_METADATA_SENTINELS = ("pyproject.toml", "setup.cfg")
_SETUP_MODULE_CANDIDATES = {
    "setuptools",
    "distutils",
    "distutils.core",
}


def supports_native_builds(root: Path | str) -> bool:
    """Return ``True`` when *root* exposes standard packaging metadata.

    ``python -m build`` expects a declarative configuration file (``pyproject.toml``
    or ``setup.cfg``) or a traditional ``setup()`` entry point.  CoolBox ships a
    custom bootstrapper as ``setup.py`` which does not necessarily provide these
    hooks.  Proactively detecting their absence lets callers skip native wheel
    builds instead of bubbling up backend errors to end users.
    """

    root_path = Path(root)
    return _supports_native_builds_cached(root_path.resolve())


@lru_cache(maxsize=None)
def _supports_native_builds_cached(root: Path) -> bool:
    for sentinel in _METADATA_SENTINELS:
        if (root / sentinel).is_file():
            return True

    setup_path = root / "setup.py"
    try:
        source = setup_path.read_text(encoding="utf-8")
    except OSError:
        return False

    try:
        tree = ast.parse(source, filename=str(setup_path))
    except SyntaxError:
        return False

    analyzer = _SetupAnalyzer()
    analyzer.visit(tree)
    return analyzer.uses_setup


class _SetupAnalyzer(ast.NodeVisitor):
    """Detects whether a module imports and invokes ``setup()``."""

    def __init__(self) -> None:
        self.direct_names: set[str] = set()
        self.module_aliases: set[str] = set()
        self.uses_setup: bool = False

    # ``ast.NodeVisitor`` interface -------------------------------------------------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # pragma: no cover - exercised via visit()
        if node.module in _SETUP_MODULE_CANDIDATES:
            for alias in node.names:
                if alias.name == "setup":
                    self.direct_names.add(alias.asname or alias.name)
                else:
                    fullname = _qualify(node.module, alias.name)
                    if fullname in _SETUP_MODULE_CANDIDATES:
                        self.module_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # pragma: no cover - exercised via visit()
        for alias in node.names:
            if alias.name in _SETUP_MODULE_CANDIDATES:
                binding = alias.asname or alias.name.split(".")[0]
                self.module_aliases.add(binding)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # pragma: no cover - exercised via visit()
        if self.uses_setup:
            return
        target = node.func
        if isinstance(target, ast.Name):
            if target.id in self.direct_names:
                self.uses_setup = True
        else:
            dotted = _dotted_name(target)
            if dotted and dotted.endswith(".setup"):
                base = dotted[: -len(".setup")]
                first = base.split(".", 1)[0]
                if (
                    base in _SETUP_MODULE_CANDIDATES
                    or base in self.module_aliases
                    or first in self.module_aliases
                    or first in _SETUP_MODULE_CANDIDATES
                ):
                    self.uses_setup = True
        if not self.uses_setup:
            self.generic_visit(node)


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _qualify(prefix: str | None, name: str) -> str:
    if prefix:
        return f"{prefix}.{name}".rstrip(".")
    return name


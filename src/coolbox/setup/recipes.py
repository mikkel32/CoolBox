"""Recipe parsing utilities for setup orchestration."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence, TYPE_CHECKING, cast

from importlib import resources
from importlib.resources.abc import Traversable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .orchestrator import SetupStage

try:  # pragma: no cover - optional dependency
    import yaml
except Exception:  # pragma: no cover - fallback when PyYAML is unavailable
    yaml = None

_STAGE_KEYS: tuple[str, ...] = (
    "preflight",
    "dependency-resolution",
    "installers",
    "verification",
    "summaries",
)

_DEFAULT_RECIPE: dict[str, Any] = {
    "name": "default",
    "config": {
        "requirements": "requirements.txt",
        "sentinel": ".setup_done",
        "skip_when_clean": True,
        "write_sentinel_on_skip": False,
        "skip_update": True,
        "force": False,
        "continue_on_failure": False,
    },
    "stages": {key: {} for key in _STAGE_KEYS},
}


@dataclass
class Recipe:
    """Structured representation of a setup recipe."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    source: Path | Traversable | None = None

    @property
    def config(self) -> dict[str, Any]:
        base = dict(_DEFAULT_RECIPE["config"])
        base.update(self.data.get("config", {}))
        return base

    def stage_config(self, stage: str | SetupStage) -> dict[str, Any]:
        key = getattr(stage, "value", stage)
        stages = self.data.get("stages", {})
        raw = stages.get(key, {})
        if isinstance(raw, dict):
            return dict(raw)
        if raw is None:
            return {}
        return {"value": raw}

    def as_dict(self) -> dict[str, Any]:
        payload = dict(_DEFAULT_RECIPE)
        payload.update(self.data)
        payload["name"] = self.name
        return payload


class RecipeLoader:
    """Load recipes from JSON/YAML files with inheritance support."""

    def __init__(self, search_paths: Sequence[Path] | None = None) -> None:
        default_paths: list[Path | Traversable] = [
            Path.cwd() / "assets" / "setup" / "recipes",
            Path.cwd() / "assets" / "recipes",
            resources.files("coolbox.assets").joinpath("setup", "recipes"),
            resources.files("coolbox.assets").joinpath("recipes"),
        ]
        candidates: list[Path | Traversable] = list(search_paths or []) + default_paths
        seen: set[str] = set()
        self.search_paths: list[Path | Traversable] = []
        for candidate in candidates:
            if not candidate:
                continue
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            self.search_paths.append(candidate)
        self._loading: set[str] = set()

    def load(
        self,
        identifier: str | Path | None,
        *,
        overrides: Mapping[str, Any] | None = None,
    ) -> Recipe:
        if identifier is None:
            data = merge_dicts(_DEFAULT_RECIPE, overrides or {})
            return Recipe(name="default", data=data)
        path = self._resolve(identifier)
        data = self._read_recipe(path)
        name = data.get("name") or self._stem(path)
        merged = self._merge_extends(data, self._parent(path))
        if overrides:
            merged = merge_dicts(merged, dict(overrides))
        return Recipe(name=name, data=merged, source=path)

    # ------------------------------------------------------------------
    def _merge_extends(
        self, data: dict[str, Any], base_dir: Path | Traversable | None
    ) -> dict[str, Any]:
        extends = data.get("extends", [])
        if not extends:
            return merge_dicts(_DEFAULT_RECIPE, data)
        merged: dict[str, Any] = {}
        for entry in extends:
            parent_path = self._resolve(entry, base_dir=base_dir)
            parent_data = self._read_recipe(parent_path)
            parent_merged = self._merge_extends(parent_data, self._parent(parent_path))
            merged = merge_dicts(merged, parent_merged)
        merged = merge_dicts(merged, data)
        return merged

    def _resolve(
        self,
        identifier: str | Path,
        *,
        base_dir: Path | Traversable | None = None,
    ) -> Path | Traversable:
        candidate = Path(identifier)
        if not candidate.suffix and candidate.name not in {"default"}:
            for suffix in (".yml", ".yaml", ".json"):
                try:
                    resolved = self._resolve(candidate.with_suffix(suffix), base_dir=base_dir)
                except FileNotFoundError:
                    continue
                if self._exists(resolved):
                    return resolved
        if candidate.is_absolute():
            if candidate.exists():
                return candidate
            raise FileNotFoundError(candidate)
        search_space: list[Path | Traversable] = []
        if base_dir is not None:
            search_space.append(base_dir)
        search_space.extend(self.search_paths)
        for root in search_space:
            path = self._join_path(root, candidate)
            if self._exists(path):
                return path
        raise FileNotFoundError(f"Recipe '{identifier}' not found in {search_space}")

    @staticmethod
    def _join_path(root: Path | Traversable, relative: Path) -> Path | Traversable:
        if isinstance(root, Path):
            return root / relative
        return root.joinpath(*relative.parts)

    @staticmethod
    def _exists(path: Path | Traversable) -> bool:
        exists = getattr(path, "exists", None)
        if callable(exists):
            try:
                return bool(exists())
            except OSError:
                return False
        return Path(str(path)).exists()

    @staticmethod
    def _stem(path: Path | Traversable) -> str:
        if isinstance(path, Path):
            return path.stem
        name = getattr(path, "name", None)
        if isinstance(name, str):
            return Path(name).stem
        return Path(str(path)).stem

    @staticmethod
    def _parent(path: Path | Traversable | None) -> Path | Traversable | None:
        if path is None:
            return None
        if isinstance(path, Path):
            return path.parent
        parent = getattr(path, "parent", None)
        if parent is not None:
            return parent
        return Path(str(path)).parent

    def _read_recipe(self, path: Path | Traversable) -> dict[str, Any]:
        key = str(path)
        if key in self._loading:
            raise RuntimeError(f"Circular recipe extends detected: {path}")
        self._loading.add(key)
        try:
            if isinstance(path, Path):
                text = path.read_text(encoding="utf-8")
                suffix = path.suffix
            else:
                text = path.read_text(encoding="utf-8")
                suffix = Path(path.name).suffix if hasattr(path, "name") else ""
            if suffix in {".yml", ".yaml"}:
                if yaml is None:
                    raise RuntimeError("PyYAML is required to read YAML recipes")
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text)
            if not isinstance(data, dict):
                raise TypeError(f"Recipe file {path} must contain a mapping")
            return data
        finally:
            self._loading.remove(key)


def merge_dicts(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge two dictionaries."""

    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(value, Mapping) and isinstance(existing, Mapping):
            result[key] = merge_dicts(
                cast(Mapping[str, Any], existing),
                cast(Mapping[str, Any], value),
            )
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = [*result[key], *value]
        else:
            result[key] = value
    return result


__all__ = ["Recipe", "RecipeLoader", "merge_dicts"]

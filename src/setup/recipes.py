"""Recipe parsing utilities for setup orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
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
    },
    "stages": {key: {} for key in _STAGE_KEYS},
}


@dataclass
class Recipe:
    """Structured representation of a setup recipe."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None

    @property
    def config(self) -> dict[str, Any]:
        base = dict(_DEFAULT_RECIPE["config"])
        base.update(self.data.get("config", {}))
        return base

    def stage_config(self, stage: str | "SetupStage") -> dict[str, Any]:
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
        default_paths = [
            Path.cwd() / "assets" / "setup" / "recipes",
            Path.cwd() / "assets" / "recipes",
        ]
        self.search_paths = list(dict.fromkeys([p for p in (search_paths or []) if p] + default_paths))
        self._loading: set[Path] = set()

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
        name = data.get("name") or path.stem
        merged = self._merge_extends(data, path.parent)
        if overrides:
            merged = merge_dicts(merged, dict(overrides))
        return Recipe(name=name, data=merged, source=path)

    # ------------------------------------------------------------------
    def _merge_extends(self, data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
        extends = data.get("extends", [])
        if not extends:
            return merge_dicts(_DEFAULT_RECIPE, data)
        merged: dict[str, Any] = {}
        for entry in extends:
            parent_path = self._resolve(entry, base_dir=base_dir)
            parent_data = self._read_recipe(parent_path)
            parent_merged = self._merge_extends(parent_data, parent_path.parent)
            merged = merge_dicts(merged, parent_merged)
        merged = merge_dicts(merged, data)
        return merged

    def _resolve(self, identifier: str | Path, *, base_dir: Path | None = None) -> Path:
        candidate = Path(identifier)
        if not candidate.suffix and candidate.name not in {"default"}:
            for suffix in (".yml", ".yaml", ".json"):
                try:
                    resolved = self._resolve(candidate.with_suffix(suffix), base_dir=base_dir)
                except FileNotFoundError:
                    continue
                if resolved.exists():
                    return resolved
        if candidate.is_absolute():
            if candidate.exists():
                return candidate
            raise FileNotFoundError(candidate)
        search_space = []
        if base_dir is not None:
            search_space.append(base_dir)
        search_space.extend(self.search_paths)
        for root in search_space:
            path = root / candidate
            if path.exists():
                return path
        raise FileNotFoundError(f"Recipe '{identifier}' not found in {search_space}")

    def _read_recipe(self, path: Path) -> dict[str, Any]:
        if path in self._loading:
            raise RuntimeError(f"Circular recipe extends detected: {path}")
        self._loading.add(path)
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix in {".yml", ".yaml"}:
                if yaml is None:
                    raise RuntimeError("PyYAML is required to read YAML recipes")
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text)
            if not isinstance(data, dict):
                raise TypeError(f"Recipe file {path} must contain a mapping")
            return data
        finally:
            self._loading.remove(path)


def merge_dicts(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge two dictionaries."""

    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = merge_dicts(result[key], value)  # type: ignore[arg-type]
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = [*result[key], *value]
        else:
            result[key] = value
    return result


__all__ = ["Recipe", "RecipeLoader", "merge_dicts"]

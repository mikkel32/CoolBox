"""Filesystem helpers for configuration storage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigPaths:
    """Resolved filesystem locations for configuration data."""

    root: Path
    config_file: Path
    cache_dir: Path

    @classmethod
    def create(cls, root: Path | None = None) -> "ConfigPaths":
        """Return paths rooted at *root* or the default config directory."""

        base = Path(root) if root is not None else Path.home() / ".coolbox"
        base = base.expanduser().resolve()
        return cls(root=base, config_file=base / "config.json", cache_dir=base / "cache")

    def ensure(self) -> None:
        """Create the configuration and cache directories if needed."""

        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)


__all__ = ["ConfigPaths"]

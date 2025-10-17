"""High-level configuration manager used throughout CoolBox."""
from __future__ import annotations

import json
import logging
import shutil
import sys
from copy import deepcopy
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict

from .defaults import DEFAULT_SETTINGS
from .paths import ConfigPaths

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)


class Config:
    """Load, mutate, and persist application configuration."""

    def __init__(
        self,
        *,
        paths: ConfigPaths | None = None,
        defaults: Dict[str, Any] | None = None,
    ) -> None:
        self.paths = paths or ConfigPaths.create()
        self.defaults: Dict[str, Any] = deepcopy(defaults or DEFAULT_SETTINGS)
        self.config: Dict[str, Any] = self.defaults.copy()
        self.load_ok = self._load_config()

    @property
    def config_dir(self) -> Path:
        """Return the directory holding configuration files."""

        return self.paths.root

    @property
    def config_file(self) -> Path:
        """Return the primary configuration file path."""

        return self.paths.config_file

    @property
    def cache_dir(self) -> Path:
        """Return the directory used for cached data."""

        return self.paths.cache_dir

    def ensure_dirs(self) -> None:
        """Create configuration and cache directories if necessary."""

        self.paths.ensure()

    def _load_config(self) -> bool:
        """Load configuration from disk, falling back to defaults."""

        self.ensure_dirs()
        path = self.paths.config_file
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded_config = json.load(handle)
                self.config = {**self.defaults, **loaded_config}
                return True
            except JSONDecodeError as exc:
                logger.warning("Invalid config file, resetting to defaults: %s", exc)
                backup = path.with_suffix(path.suffix + ".bak")
                try:
                    shutil.move(path, backup)
                except OSError as backup_err:
                    logger.warning("Failed to back up invalid config: %s", backup_err)
                self.config = self.defaults.copy()
                self.save()
                return False
            except OSError as exc:
                logger.error("Error reading config: %s", exc)
                self.config = self.defaults.copy()
                return False
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Error loading config: %s", exc)
                self.config = self.defaults.copy()
                return False
        else:
            self.config = self.defaults.copy()
            return True

    def save(self) -> bool:
        """Persist the current configuration to disk."""

        try:
            with open(self.paths.config_file, "w", encoding="utf-8") as handle:
                json.dump(self.config, handle, indent=4)
            return True
        except OSError as exc:
            msg = f"Error saving config: {exc}"
            logger.error(msg)
            sys.stdout.write(msg + "\n")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key* or ``default`` when unset."""

        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Assign *value* to *key* within the configuration."""

        self.config[key] = value

    def get_section_state(self, key: str, default: bool = True) -> bool:
        """Return the persisted expand/collapse state for *key*."""

        states = self.config.setdefault("section_states", {})
        return bool(states.get(key, default))

    def set_section_state(self, key: str, value: bool) -> None:
        """Persist the expand/collapse state for *key*."""

        states = self.config.setdefault("section_states", {})
        states[key] = value
        self.save()

    def add_recent_file(self, filepath: str) -> None:
        """Add *filepath* to the recent files list."""

        recent = self.config.get("recent_files", [])
        if filepath in recent:
            recent.remove(filepath)
        recent.insert(0, filepath)
        max_files = self.config.get("max_recent_files", 10)
        self.config["recent_files"] = recent[:max_files]
        self.save()

    def reset_to_defaults(self) -> None:
        """Replace the configuration with the default values."""

        self.config = self.defaults.copy()
        self.save()

    def clear_cache(self) -> int:
        """Delete the cached files and directories, returning the count."""

        count = 0
        self.ensure_dirs()
        cache_dir = self.paths.cache_dir
        if cache_dir.exists():
            for path in cache_dir.iterdir():
                try:
                    if path.is_file():
                        path.unlink()
                    else:
                        shutil.rmtree(path)
                    count += 1
                except Exception:  # pragma: no cover - defensive
                    continue
        return count


__all__ = ["Config"]

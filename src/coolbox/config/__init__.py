"""Configuration helpers and defaults for CoolBox."""
from __future__ import annotations

from .defaults import DEFAULT_SETTINGS
from .manager import Config
from .paths import ConfigPaths

__all__ = ["Config", "ConfigPaths", "DEFAULT_SETTINGS"]

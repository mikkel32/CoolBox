"""Configuration and environment-derived settings for the setup command."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

__all__ = ["CONFIG", "Config", "DEFAULT_RAINBOW", "RAINBOW_COLORS", "IS_TTY"]

DEFAULT_RAINBOW = (
    "#e40303",
    "#ff8c00",
    "#ffed00",
    "#008026",
    "#004dff",
    "#750787",
)


@dataclass
class Config:
    """Runtime configuration derived from environment variables."""

    no_git: bool = os.environ.get("COOLBOX_NO_GIT") == "1"
    cli_no_anim: bool = os.environ.get("COOLBOX_FORCE_NO_ANIM") == "1"
    no_anim: bool = False
    border_enabled_default: bool = False
    alt_screen: bool = False
    rainbow_colors: Sequence[str] = field(default_factory=lambda: DEFAULT_RAINBOW)


def _load_user_config() -> dict:
    for path in (Path.home() / ".coolboxrc", Path.cwd() / ".coolboxrc"):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                # Keep configuration loading permissive so a broken file
                # does not block execution.
                pass
    return {}


CONFIG = Config()
USER_CFG = _load_user_config()
for key, value in USER_CFG.items():
    if hasattr(CONFIG, key):
        setattr(CONFIG, key, value)

IS_TTY = sys.stdout.isatty()
CONFIG.no_anim = (
    CONFIG.cli_no_anim
    or os.environ.get("COOLBOX_NO_ANIM") == "1"
    or os.environ.get("COOLBOX_CI") == "1"
    or os.environ.get("CI") == "1"
    or not IS_TTY
)
_border_env = os.environ.get("COOLBOX_BORDER")
CONFIG.border_enabled_default = False if _border_env is None else _border_env == "1"
CONFIG.alt_screen = os.environ.get("COOLBOX_ALT_SCREEN") == "1"
if os.environ.get("COOLBOX_COLORS"):
    CONFIG.rainbow_colors = tuple(os.environ["COOLBOX_COLORS"].split(","))

RAINBOW_COLORS: Sequence[str] = tuple(CONFIG.rainbow_colors)

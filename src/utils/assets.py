from __future__ import annotations

"""Asset path helpers used throughout CoolBox."""

from pathlib import Path
import os
import sys


def assets_base() -> Path:
    """Return the base directory containing bundled assets."""
    base_env = os.environ.get("COOLBOX_ASSETS")
    if base_env:
        return Path(base_env)
    if getattr(sys, "frozen", False):  # Support PyInstaller
        return Path(getattr(sys, "_MEIPASS"))  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def asset_path(*parts: str) -> Path:
    """Return the absolute path to a file in the ``assets`` directory."""
    return assets_base().joinpath("assets", *parts)

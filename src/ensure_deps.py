"""Utilities to ensure required packages are available at runtime."""

from __future__ import annotations

import importlib
import subprocess
import sys
from types import ModuleType
from typing import Optional

try:  # Avoid circular imports when utils.helpers requires ensure_deps
    from .utils.helpers import log
except Exception:  # pragma: no cover - fallback logger
    import logging

    logging.basicConfig(level=logging.INFO)

    def log(message: str) -> None:
        """Fallback logger used during early imports."""
        logging.info(message)


_DEF_VERSION = "5.2.2"
_DEF_PSUTIL = "5.9.0"
_DEF_PILLOW = "11.0.0"


def require_package(name: str, version: Optional[str] = None) -> ModuleType:
    """Import and return *name*, installing it first if missing."""

    try:
        return importlib.import_module(name)
    except ImportError:
        pkg = f"{name}=={version}" if version else name
        log(f"Package '{name}' missing, attempting install of {pkg}...")
        cmd = [sys.executable, "-m", "pip", "install", pkg]
        try:
            subprocess.check_call(cmd)
        except Exception as exc:
            if version:
                log(f"Failed to install {pkg}, trying latest version...")
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", name])
                except Exception as exc2:  # pragma: no cover - install step may fail
                    raise ImportError(
                        f"{name} is required. Install dependencies with 'python setup.py' or 'pip install -r requirements.txt'."
                    ) from exc2
            else:
                raise ImportError(
                    f"{name} is required. Install dependencies with 'python setup.py' or 'pip install -r requirements.txt'."
                ) from exc
        return importlib.import_module(name)


def ensure_customtkinter(version: str = _DEF_VERSION) -> ModuleType:
    """Return the ``customtkinter`` module, installing it if needed."""

    return require_package("customtkinter", version)


def ensure_psutil(version: str = _DEF_PSUTIL) -> ModuleType:
    """Return the ``psutil`` module, installing it if needed."""

    return require_package("psutil", version)


def ensure_pillow(version: str = _DEF_PILLOW) -> ModuleType:
    """Return the ``PIL`` module, installing Pillow if needed."""

    try:
        return importlib.import_module("PIL")
    except ImportError:
        require_package("Pillow", version)
        return importlib.import_module("PIL")

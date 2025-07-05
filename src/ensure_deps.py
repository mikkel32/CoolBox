"""Utilities to ensure required packages are available at runtime."""

from __future__ import annotations

import importlib
import subprocess
import sys
from types import ModuleType
from typing import Optional

from .utils.helpers import log


_DEF_VERSION = "5.2.2"


def require_package(
    name: str,
    version: Optional[str] = None,
    *,
    install_name: Optional[str] = None,
) -> ModuleType:
    """Import and return *name*, installing it first if missing.

    Parameters
    ----------
    name:
        Module name to import.
    version:
        Optional version specifier for installation.
    install_name:
        Package name to install if different from *name*.
    """

    try:
        return importlib.import_module(name)
    except ImportError:
        pkg_name = install_name or name
        pkg = f"{pkg_name}=={version}" if version else pkg_name
        log(f"Package '{name}' missing, attempting install of {pkg}...")
        try:
            subprocess.check_call([
                sys.executable,
                "-m",
                "pip",
                "install",
                pkg,
            ])
        except Exception as exc:  # pragma: no cover - install step may fail
            raise ImportError(
                f"{name} is required. Install dependencies with 'python setup.py' or 'pip install -r requirements.txt'."
            ) from exc
        return importlib.import_module(name)


def ensure_customtkinter(version: str = _DEF_VERSION) -> ModuleType:
    """Return the ``customtkinter`` module, installing it if needed."""

    return require_package("customtkinter", version)


def ensure_pillow(version: str = "10.0.0") -> ModuleType:
    """Return the ``PIL`` package, installing Pillow if missing."""

    return require_package("PIL", version, install_name="pillow")

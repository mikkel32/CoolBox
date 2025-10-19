"""Environment and filesystem helpers for the setup command."""
from __future__ import annotations

import importlib
import hashlib
import os
import socket
import sys
from pathlib import Path
from typing import Sequence, Tuple

from coolbox.paths import project_root as _discover_project_root

from ._logging import logger

__all__ = [
    "BASE_ENV",
    "CACHE_ROOT",
    "DEV_PACKAGES",
    "MIN_PYTHON",
    "ROOT_DIR",
    "REQUIREMENTS_FILE",
    "STAMP_CACHE_ROOT",
    "WHEEL_CACHE_ROOT",
    "check_python_version",
    "default_cache_root",
    "get_root",
    "get_venv_dir",
    "is_offline",
    "locate_root",
    "offline_auto_detected",
    "release_lightweight_mode",
    "set_offline",
]

MIN_PYTHON: Tuple[int, int] = (3, 10)
if sys.version_info < MIN_PYTHON:  # pragma: no cover - defensive import guard
    raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")


def locate_root(start: Path) -> Path:
    path = Path(start).resolve()
    markers = {"requirements.txt", "pyproject.toml", ".git"}
    for parent in (path, *path.parents):
        if any((parent / marker).exists() for marker in markers):
            return parent
    return path


def _project_root() -> Path:
    env = os.environ.get("COOLBOX_ROOT") or os.environ.get("COOLBOX_PROJECT_ROOT")
    if env:
        candidate = Path(env).expanduser()
        try:
            return candidate.resolve()
        except OSError:
            return candidate
    detected = _discover_project_root()
    if detected.exists():
        return detected
    return locate_root(Path(__file__).resolve())


def get_root() -> Path:
    return _project_root()


def get_venv_dir() -> Path:
    env = os.environ.get("COOLBOX_VENV")
    if env:
        return Path(env).resolve()
    return _project_root() / ".venv"


ROOT_DIR = _project_root()
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
DEV_PACKAGES: Sequence[str] = ("pip-tools>=7", "build>=1", "wheel>=0.43", "pytest>=8")


def default_cache_root() -> Path:
    env = os.environ.get("COOLBOX_CACHE")
    if env:
        return Path(env).expanduser().resolve()
    try:
        home = Path.home()
    except Exception:
        home = ROOT_DIR
    return (home / ".coolbox" / "cache").resolve()


CACHE_ROOT = default_cache_root()


def _cache_dir(name: str) -> Path:
    path = CACHE_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


WHEEL_CACHE_ROOT = _cache_dir("wheels")
STAMP_CACHE_ROOT = _cache_dir("stamps")

_LIGHTWEIGHT_FORCED = False
if "COOLBOX_LIGHTWEIGHT" not in os.environ:
    os.environ["COOLBOX_LIGHTWEIGHT"] = "1"
    _LIGHTWEIGHT_FORCED = True


BASE_ENV = {
    **os.environ,
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONIOENCODING": "utf-8",
    "GIT_TERMINAL_PROMPT": "0",
}


def _detect_offline(timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection(("pypi.org", 443), timeout=timeout):
            return False
    except OSError:
        return True


_OFFLINE_FORCED = os.environ.get("COOLBOX_OFFLINE") == "1"
_OFFLINE_AUTO: bool | None = None


def set_offline(value: bool) -> None:
    global _OFFLINE_FORCED, _OFFLINE_AUTO
    _OFFLINE_FORCED = value
    _OFFLINE_AUTO = True if value else False
    if value:
        os.environ["COOLBOX_OFFLINE"] = "1"
        BASE_ENV["COOLBOX_OFFLINE"] = "1"
    else:
        os.environ.pop("COOLBOX_OFFLINE", None)
        BASE_ENV.pop("COOLBOX_OFFLINE", None)


def is_offline() -> bool:
    global _OFFLINE_FORCED
    if os.environ.get("COOLBOX_OFFLINE") == "1":
        _OFFLINE_FORCED = True
        return True
    if _OFFLINE_FORCED:
        return True
    global _OFFLINE_AUTO
    if _OFFLINE_AUTO is None:
        _OFFLINE_AUTO = _detect_offline()
    return _OFFLINE_AUTO


def offline_auto_detected() -> bool:
    return (_OFFLINE_AUTO is True) and not _OFFLINE_FORCED


def _refresh_coolbox_bindings() -> None:
    """Ensure the public ``coolbox`` module exposes the full application."""

    module = sys.modules.get("coolbox")
    if module is None:
        return

    try:
        coolbox_app_mod = importlib.import_module("coolbox.app")
    except Exception:
        logger.debug("Failed to import coolbox.app when releasing lightweight mode", exc_info=True)
        return

    try:
        coolbox_app = getattr(coolbox_app_mod, "CoolBoxApp")
    except AttributeError:
        logger.debug("coolbox.app missing CoolBoxApp attribute", exc_info=True)
        return

    setattr(module, "CoolBoxApp", coolbox_app)
    lazy_attrs = getattr(module, "_LAZY_ATTRS", None)
    if isinstance(lazy_attrs, dict):
        lazy_attrs["CoolBoxApp"] = ("coolbox.app", "CoolBoxApp")


def _reload_module(name: str) -> None:
    """Reload *name* when it is already imported.

    Modules like :mod:`coolbox.utils` and :mod:`coolbox.app.error_handler` cache
    lightweight-mode state at import time.  Reloading them after toggling the
    ``COOLBOX_LIGHTWEIGHT`` flag ensures they observe the updated environment.
    """

    module = sys.modules.get(name)
    if module is None:
        return

    try:
        importlib.reload(module)
    except Exception:  # pragma: no cover - defensive diagnostics
        logger.debug("Failed to reload %s when releasing lightweight mode", name, exc_info=True)


def release_lightweight_mode() -> bool:
    """Undo lightweight mode and restore the real GUI class when possible."""

    global _LIGHTWEIGHT_FORCED
    toggled = False

    if os.environ.pop("COOLBOX_LIGHTWEIGHT", None) is not None:
        toggled = True
    if BASE_ENV.pop("COOLBOX_LIGHTWEIGHT", None) is not None:
        toggled = True

    if _LIGHTWEIGHT_FORCED:
        _LIGHTWEIGHT_FORCED = False
        toggled = True

    if toggled:
        for module_name in (
            "coolbox.utils",
            "coolbox.utils.display.ui",
            "coolbox.app.error_handler",
            "coolbox.app",
        ):
            _reload_module(module_name)
        _refresh_coolbox_bindings()

    return toggled


def check_python_version(min_version: tuple[int, int] = (3, 8)) -> None:
    if sys.version_info < min_version:
        required = ".".join(map(str, min_version))
        current = sys.version.split()[0]
        msg = f"Python {required}+ is required, but {current} is running"
        logger.error(msg)
        raise RuntimeError(msg)

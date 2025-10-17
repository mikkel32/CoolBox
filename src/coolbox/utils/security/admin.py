"""Administrative privilege helpers for security tooling."""
from __future__ import annotations

import sys
from typing import List, Optional

from coolbox.paths import scripts_dir

from . import platform as platform_state


def is_admin() -> bool:
    """Return ``True`` when the current process has administrator rights."""

    if not platform_state.IS_WINDOWS:
        return False
    loader = platform_state.get_windll()
    if loader is None:
        return False
    try:
        return bool(loader.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin() -> bool:
    """Backwards-compatible alias for :func:`is_admin`."""

    return is_admin()


def relaunch_security_center(args: Optional[List[str]] = None) -> bool:
    """Attempt to relaunch Security Center with elevated privileges."""

    if not platform_state.IS_WINDOWS or is_admin():
        return False
    loader = platform_state.get_windll()
    if loader is None:
        return False
    script = scripts_dir() / "security_center_hidden.py"
    if not script.exists():
        return False
    params = " ".join(f'"{part}"' for part in [str(script), *(args or [])])
    try:
        rc = loader.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception:
        return False
    return rc > 32


__all__ = ["ensure_admin", "is_admin", "relaunch_security_center"]

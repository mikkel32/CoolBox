"""Platform detection helpers and constants for security tooling."""
from __future__ import annotations

import ctypes
import platform
from typing import Any, Optional

_SYSTEM = platform.system()
IS_WINDOWS = _SYSTEM == "Windows"
IS_MAC = _SYSTEM == "Darwin"

CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
SC_EXE: Optional[str] = r"C:\\Windows\\System32\\sc.exe" if IS_WINDOWS else None
NETSH_EXE: Optional[str] = r"C:\\Windows\\System32\\netsh.exe" if IS_WINDOWS else None
POWERSHELL_EXE: Optional[str] = (
    r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    if IS_WINDOWS
    else None
)

_windll: Any | None = getattr(ctypes, "windll", None) if IS_WINDOWS else None


def get_windll() -> Any | None:
    """Return the cached ``ctypes.windll`` loader when available."""

    if not IS_WINDOWS:
        return None
    global _windll
    loader = _windll
    if loader is None:
        loader = getattr(ctypes, "windll", None)
        _windll = loader
    return loader


__all__ = [
    "CREATE_NO_WINDOW",
    "IS_MAC",
    "IS_WINDOWS",
    "NETSH_EXE",
    "POWERSHELL_EXE",
    "SC_EXE",
    "get_windll",
]

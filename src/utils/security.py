from __future__ import annotations

"""Utilities for toggling common security settings on Windows."""

import platform
import subprocess
from typing import Optional


# ---------------------------------------------------------------------------
# Firewall helpers
# ---------------------------------------------------------------------------

def is_firewall_enabled() -> Optional[bool]:
    """Return ``True`` if the Windows firewall is enabled."""
    if platform.system() != "Windows":
        return None
    try:
        out = subprocess.check_output(
            ["netsh", "advfirewall", "show", "allprofiles"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    for line in out.splitlines():
        if "State" in line:
            if "ON" in line.upper():
                return True
            if "OFF" in line.upper():
                return False
    return None

def set_firewall_enabled(enabled: bool) -> bool:
    """Enable or disable the Windows firewall."""
    if platform.system() != "Windows":
        return False
    state = "on" if enabled else "off"
    try:
        subprocess.run(
            ["netsh", "advfirewall", "set", "allprofiles", "state", state],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Windows Defender helpers
# ---------------------------------------------------------------------------

def is_defender_enabled() -> Optional[bool]:
    """Return ``True`` if real-time protection is enabled."""
    if platform.system() != "Windows":
        return None
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-Command",
                "(Get-MpPreference).DisableRealtimeMonitoring",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    val = out.strip().lower()
    if val in {"true", "1"}:
        return False
    if val in {"false", "0"}:
        return True
    return None

def set_defender_enabled(enabled: bool) -> bool:
    """Enable or disable Windows Defender real-time protection."""
    if platform.system() != "Windows":
        return False
    value = "$false" if enabled else "$true"
    try:
        subprocess.run(
            [
                "powershell",
                "-Command",
                f"Set-MpPreference -DisableRealtimeMonitoring {value}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


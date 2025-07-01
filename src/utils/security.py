from __future__ import annotations

"""Utilities for toggling common security settings on Windows."""


import platform
import subprocess
from typing import Optional


# ---------------------------------------------------------------------------
# Firewall helpers
# ---------------------------------------------------------------------------

def is_firewall_enabled() -> Optional[bool]:
    """Return ``True`` if the system firewall is enabled."""
    system = platform.system()
    if system == "Windows":
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
    elif system in {"Linux", "Darwin"}:
        try:
            out = subprocess.check_output(["ufw", "status"], text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return None
        for line in out.splitlines():
            if "Status:" in line:
                if "active" in line.lower():
                    return True
                if "inactive" in line.lower():
                    return False
        return None
    return None


def set_firewall_enabled(enabled: bool) -> bool:
    """Enable or disable the system firewall."""
    system = platform.system()
    if system == "Windows":
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
    elif system in {"Linux", "Darwin"}:
        cmd = ["ufw", "enable"] if enabled else ["ufw", "disable"]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
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


# ---------------------------------------------------------------------------
# Privilege helpers

# ---------------------------------------------------------------------------

def is_admin() -> Optional[bool]:
    """Return ``True`` if the current process has administrative privileges."""
    system = platform.system()
    if system == "Windows":
        try:
            import ctypes  # lazy import
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    elif system in {"Linux", "Darwin"}:
        try:
            import os
            return os.geteuid() == 0
        except Exception:
            return False
    return None


def ensure_admin(prompt: str = "Administrator access is required.") -> bool:
    """Request elevation if needed and relaunch with admin rights."""
    if is_admin():
        return True

    system = platform.system()

    if system == "Windows":
        try:
            import ctypes
            import sys
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Security Center", f"{prompt}\n\nRelaunch with administrator rights?"
            ):
                return False

            params = " ".join([f'"{arg}"' for arg in sys.argv])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            return False
        except Exception:
            return False

    elif system in {"Linux", "Darwin"}:
        try:
            import os
            import sys

            try:
                from tkinter import messagebox, Tk

                root = Tk()
                root.withdraw()
                ok = messagebox.askyesno(
                    "Security Center", f"{prompt}\n\nRelaunch with administrator rights?"
                )
                root.destroy()
                if not ok:
                    return False
            except Exception:
                response = input(f"{prompt}\nRelaunch with sudo? [y/N] ")
                if response.strip().lower() != "y":
                    return False

            os.execvp("sudo", ["sudo", sys.executable, *sys.argv])
            return False
        except Exception:
            return False

    return False


def require_admin(prompt: str = "Administrator access is required.") -> None:
    """Ensure the process is running with admin rights or raise ``PermissionError``.

    This will display an elevation prompt via :func:`ensure_admin` and, if the
    user declines or elevation fails, ``PermissionError`` is raised.  When
    elevation succeeds the current process is replaced and this function does
    not return.
    """

    if not ensure_admin(prompt):
        raise PermissionError("Administrator privileges are required")

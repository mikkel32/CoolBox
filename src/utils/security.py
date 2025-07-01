"""Utilities for toggling common security settings on Windows."""

from __future__ import annotations


import platform
import subprocess
from typing import Optional
from pathlib import Path
import sys
import socket
from dataclasses import dataclass
import psutil
from .win_console import hidden_creation_flags
from .kill_utils import kill_process, kill_process_tree


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


@dataclass(slots=True)
class LocalPort:
    """Information about a local listening port."""

    port: int
    pid: int | None
    process: str
    service: str


_SERVICE_CACHE: dict[int, str] = {}
_PROC_NAME_CACHE: dict[int, str] = {}


def list_open_ports() -> dict[int, list[LocalPort]]:
    """Return a mapping of listening ports to :class:`LocalPort` objects.

    Reuses cached service names and process names to reduce repeated lookups
    when scanning ports frequently.
    """

    ports: dict[int, list[LocalPort]] = {}
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                continue

            port = conn.laddr.port
            pid: int | None = conn.pid

            if pid is not None:
                proc_name = _PROC_NAME_CACHE.get(pid)
                if proc_name is None:
                    try:
                        proc_name = psutil.Process(pid).name()
                    except Exception:
                        proc_name = "unknown"
                    _PROC_NAME_CACHE[pid] = proc_name
            else:
                proc_name = "unknown"

            service = _SERVICE_CACHE.get(port)
            if service is None:
                try:
                    service = socket.getservbyport(port)
                except Exception:
                    service = "unknown"
                _SERVICE_CACHE[port] = service

            ports.setdefault(port, []).append(LocalPort(port, pid, proc_name, service))
    except Exception:
        return {}

    return {p: v for p, v in sorted(ports.items())}


def kill_process_by_port(port: int, *, tree: bool = False) -> bool:
    """Kill any processes listening on ``port``.

    If ``tree`` is ``True`` terminate each process and all of its children using
    :func:`kill_process_tree`. Otherwise terminate just the listening processes
    via :func:`kill_process`.
    """

    ports = list_open_ports()
    entries = ports.get(port) or []
    killed = False
    for entry in entries:
        if entry.pid is None:
            continue
        if tree:
            ok = kill_process_tree(entry.pid)
        else:
            ok = kill_process(entry.pid)
        killed = killed or ok
    return killed


def kill_port_range(start: int, end: int, *, tree: bool = False) -> dict[int, bool]:
    """Kill all listeners within ``start``..``end`` (inclusive)."""

    ports = list_open_ports()
    results: dict[int, bool] = {}
    for port in range(start, end + 1):
        entries = ports.get(port) or []
        killed = False
        for entry in entries:
            if entry.pid is None:
                continue
            if tree:
                ok = kill_process_tree(entry.pid)
            else:
                ok = kill_process(entry.pid)
            killed = killed or ok
        results[port] = killed
    return results


def launch_security_center(*, hide_console: bool = False) -> bool:
    """Launch the standalone security_center script with admin rights if needed.

    Parameters
    ----------
    hide_console:
        When ``True`` on Windows the command is executed using ``pythonw.exe``
        if available and the ``CREATE_NO_WINDOW`` flag for a fully hidden
        console. On other platforms the flag is ignored.
    """

    script_name = "security_center_hidden.py" if hide_console else "security_center.py"
    script = Path(__file__).resolve().parents[2] / "scripts" / script_name
    if not script.is_file():
        return False

    python = Path(sys.executable)
    kwargs: dict[str, object] = {}

    if hide_console:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
        if platform.system() == "Windows":
            pythonw = python.with_name("pythonw.exe")
            if pythonw.is_file():
                python = pythonw
            kwargs["creationflags"] = hidden_creation_flags()

    if is_admin():
        try:
            subprocess.Popen([str(python), str(script)], **kwargs)
            return True
        except Exception:
            return False

    system = platform.system()

    if system == "Windows":
        try:
            import ctypes  # lazy import
            params = f'"{script}"'
            show = 0 if hide_console else 1
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(python), params, None, show)
            return rc > 32
        except Exception:
            return False
    elif system in {"Linux", "Darwin"}:
        try:
            subprocess.Popen(["sudo", str(python), str(script)], **kwargs)
            return True
        except Exception:
            return False

    return False

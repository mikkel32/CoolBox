"""Utilities for toggling common security settings on Windows."""

from __future__ import annotations


import platform
import shutil
import subprocess
import os
from functools import lru_cache
import re
from typing import Optional
from pathlib import Path
import sys
import socket
from dataclasses import dataclass
try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency check
    from ..ensure_deps import ensure_psutil

    psutil = ensure_psutil()
from .win_console import hidden_creation_flags
from .process_utils import run_command as _run, run_command_background
from .kill_utils import kill_process, kill_process_tree


@lru_cache(maxsize=1)
def _unix_firewall_tool() -> str:
    """Return the available firewall tool on Unix systems.

    The result is cached to avoid repeated ``shutil.which`` lookups. If no
    known tool is detected ``ufw`` is returned as a fallback so calls remain
    predictable on systems without these utilities installed.
    """
    fallback: str | None = None
    for tool in ("ufw", "firewall-cmd", "pfctl"):
        path = shutil.which(tool)
        if not path:
            continue
        binary = Path(path).name
        if binary == tool:
            return tool
        if fallback is None:
            fallback = binary
    return fallback or "ufw"


# ---------------------------------------------------------------------------
# Firewall helpers
# ---------------------------------------------------------------------------

def is_firewall_enabled() -> Optional[bool]:
    """Return ``True`` if the system firewall is enabled."""
    system = platform.system()
    if system == "Windows":
        out = _run(
            ["netsh", "advfirewall", "show", "allprofiles"],
            capture=True,
        )
        if out is None:
            return None
        for line in out.splitlines():
            m = re.search(r"State\s+(\w+)", line, re.I)
            if m:
                return m.group(1).lower() == "on"
        return None
    elif system in {"Linux", "Darwin"}:
        tool = _unix_firewall_tool()
        if tool == "ufw":
            out = _run(["ufw", "status"], capture=True)
            if out is None:
                return None
            for line in out.splitlines():
                if "Status:" in line:
                    if "active" in line.lower():
                        return True
                    if "inactive" in line.lower():
                        return False
            return None
        elif tool == "firewall-cmd":
            out = _run(["firewall-cmd", "--state"], capture=True)
            if out is None:
                return None
            return out.strip() == "running"
        elif tool == "pfctl":
            out = _run(["pfctl", "-s", "info"], capture=True)
            if out is None:
                return None
            for line in out.splitlines():
                m = re.search(r"Status:\s+(\w+)", line)
                if m:
                    return m.group(1).lower() == "enabled"
            return None
        return None
    return None


def set_firewall_enabled(enabled: bool) -> bool:
    """Enable or disable the system firewall."""
    system = platform.system()
    if system == "Windows":
        state = "on" if enabled else "off"
        return (
            _run(
                ["netsh", "advfirewall", "set", "allprofiles", "state", state]
            )
            is not None
        )
    elif system in {"Linux", "Darwin"}:
        tool = _unix_firewall_tool()
        if tool == "ufw":
            cmd = ["ufw", "enable"] if enabled else ["ufw", "disable"]
            return _run(cmd) is not None
        elif tool == "firewall-cmd":
            action = "start" if enabled else "stop"
            return _run(["systemctl", action, "firewalld"]) is not None
        elif tool == "pfctl":
            cmd = ["pfctl", "-e"] if enabled else ["pfctl", "-d"]
            return _run(cmd) is not None
        return False
    return False


# ---------------------------------------------------------------------------
# Windows Defender helpers
# ---------------------------------------------------------------------------

def is_defender_enabled() -> Optional[bool]:
    """Return ``True`` if real-time protection is enabled."""
    if platform.system() != "Windows":
        return None
    out = _run(
        [
            "powershell",
            "-Command",
            "(Get-MpPreference).DisableRealtimeMonitoring",
        ],
        capture=True,
    )
    if out is None:
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
    return (
        _run(
            [
                "powershell",
                "-Command",
                f"Set-MpPreference -DisableRealtimeMonitoring {value}",
            ]
        )
        is not None
    )


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
    kwargs["env"] = os.environ.copy()

    if is_admin():
        return run_command_background([str(python), str(script)], **kwargs)

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
        return run_command_background(["sudo", str(python), str(script)], **kwargs)

    return False

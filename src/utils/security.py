"""Utilities for toggling common security settings on Windows."""

from __future__ import annotations


import platform
import shutil
import subprocess
import os
from functools import lru_cache
import re
from typing import Optional, Iterable
from pathlib import Path
import sys
import socket
from dataclasses import dataclass
import asyncio
import time
import psutil
from typing import TYPE_CHECKING
from .win_console import hidden_creation_flags
from .process_utils import run_command as _run, run_command_background
from .kill_utils import kill_process, kill_process_tree

if TYPE_CHECKING:
    from .port_watchdog import PortWatchdog
    from .connection_watchdog import ConnectionWatchdog


@lru_cache(maxsize=1)
def _unix_firewall_tool() -> str:
    """Return the available firewall tool on Unix systems.

    The result is cached to avoid repeated ``shutil.which`` lookups. If no
    known tool is detected ``ufw`` is returned as a fallback so calls remain
    predictable on systems without these utilities installed.
    """
    fallback: str | None = None
    for tool in ("ufw", "firewall-cmd", "pfctl", "iptables"):
        path = shutil.which(tool)
        if not path:
            continue
        binary = Path(path).name
        if binary == tool:
            return tool
        if fallback is None:
            fallback = binary
    return fallback or "ufw"


_RESOLVE_CACHE: dict[str, tuple[str, float]] = {}
_RESOLVE_TTL = float(os.environ.get("RESOLVE_CACHE_TTL", 300.0))


def clear_resolve_cache() -> None:
    """Clear the cached DNS lookups."""

    _RESOLVE_CACHE.clear()


def resolve_host(host: str, *, ttl: float = _RESOLVE_TTL) -> str:
    """Resolve ``host`` to an IP address with caching and TTL."""

    entry = _RESOLVE_CACHE.get(host)
    now = time.time()
    if entry and now - entry[1] < ttl:
        return entry[0]
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = host
    _RESOLVE_CACHE[host] = (ip, now)
    return ip


async def async_resolve_host(host: str, *, ttl: float = _RESOLVE_TTL) -> str:
    """Asynchronous wrapper for :func:`resolve_host`."""

    return await asyncio.to_thread(resolve_host, host, ttl=ttl)


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


def block_port_firewall(port: int, protocol: str = "tcp") -> bool:
    """Block inbound traffic to ``port`` via the system firewall."""
    system = platform.system()
    if system == "Windows":
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name=CoolBoxBlock{port}",
            "dir=in",
            "action=block",
            f"protocol={protocol.upper()}",
            f"localport={port}",
        ]
        return _run(cmd) is not None

    if system in {"Linux", "Darwin"}:
        tool = _unix_firewall_tool()
        if tool == "ufw":
            cmd = ["ufw", "deny", f"{port}/{protocol}"]
        elif tool == "firewall-cmd":
            cmd = [
                "firewall-cmd",
                "--permanent",
                "--add-rich-rule",
                f"rule family=ipv4 port port={port} protocol={protocol} drop",
            ]
            if _run(cmd) is None:
                return False
            return _run(["firewall-cmd", "--reload"]) is not None
        elif tool == "iptables":
            cmd = [
                "iptables",
                "-A",
                "INPUT",
                "-p",
                protocol,
                "--dport",
                str(port),
                "-j",
                "DROP",
            ]
        else:
            return False
        return _run(cmd) is not None

    return False


async def async_block_port_firewall(
    port: int, protocol: str = "tcp"
) -> bool:
    """Asynchronous wrapper for :func:`block_port_firewall`."""

    return await asyncio.to_thread(block_port_firewall, port, protocol)


def unblock_port_firewall(port: int, protocol: str = "tcp") -> bool:
    """Remove firewall rules blocking ``port``."""
    system = platform.system()
    if system == "Windows":
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "delete",
            "rule",
            f"name=CoolBoxBlock{port}",
            f"protocol={protocol.upper()}",
            f"localport={port}",
        ]
        return _run(cmd) is not None

    if system in {"Linux", "Darwin"}:
        tool = _unix_firewall_tool()
        if tool == "ufw":
            cmd = ["ufw", "delete", "deny", f"{port}/{protocol}"]
        elif tool == "firewall-cmd":
            cmd = [
                "firewall-cmd",
                "--permanent",
                "--remove-rich-rule",
                f"rule family=ipv4 port port={port} protocol={protocol} drop",
            ]
            if _run(cmd) is None:
                return False
            return _run(["firewall-cmd", "--reload"]) is not None
        elif tool == "iptables":
            cmd = [
                "iptables",
                "-D",
                "INPUT",
                "-p",
                protocol,
                "--dport",
                str(port),
                "-j",
                "DROP",
            ]
        else:
            return False
        return _run(cmd) is not None

    return False


async def async_unblock_port_firewall(
    port: int, protocol: str = "tcp"
) -> bool:
    """Asynchronous wrapper for :func:`unblock_port_firewall`."""

    return await asyncio.to_thread(unblock_port_firewall, port, protocol)


def block_remote_firewall(host: str, port: int | None = None, protocol: str = "tcp") -> bool:
    """Block outbound traffic to ``host`` via the system firewall."""
    ip = resolve_host(host)
    system = platform.system()
    if system == "Windows":
        rule = f"CoolBoxBlockRemote{ip.replace('.', '_')}_{port or 'any'}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={rule}",
            "dir=out",
            "action=block",
            f"remoteip={ip}",
        ]
        if port is not None:
            cmd += [f"protocol={protocol.upper()}", f"remoteport={port}"]
        return _run(cmd) is not None

    if system in {"Linux", "Darwin"}:
        tool = _unix_firewall_tool()
        if tool == "ufw":
            cmd = ["ufw", "deny", "out", "to", ip]
            if port is not None:
                cmd += ["port", str(port), protocol]
        elif tool == "firewall-cmd":
            if port is None:
                rule = f"rule family=ipv4 destination address={ip} drop"
            else:
                rule = (
                    f"rule family=ipv4 destination address={ip} "
                    f"port port={port} protocol={protocol} drop"
                )
            cmd = ["firewall-cmd", "--permanent", "--add-rich-rule", rule]
            if _run(cmd) is None:
                return False
            return _run(["firewall-cmd", "--reload"]) is not None
        elif tool == "iptables":
            cmd = ["iptables", "-A", "OUTPUT", "-d", ip]
            if port is not None:
                cmd += ["-p", protocol, "--dport", str(port)]
            cmd += ["-j", "DROP"]
        else:
            return False
        return _run(cmd) is not None

    return False


async def async_block_remote_firewall(
    host: str, port: int | None = None, protocol: str = "tcp"
) -> bool:
    """Asynchronous wrapper for :func:`block_remote_firewall`."""

    return await asyncio.to_thread(block_remote_firewall, host, port, protocol)


def unblock_remote_firewall(host: str, port: int | None = None, protocol: str = "tcp") -> bool:
    """Remove firewall rules blocking traffic to ``host``."""
    ip = resolve_host(host)
    system = platform.system()
    if system == "Windows":
        rule = f"CoolBoxBlockRemote{ip.replace('.', '_')}_{port or 'any'}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "delete",
            "rule",
            f"name={rule}",
        ]
        if port is not None:
            cmd += [f"protocol={protocol.upper()}", f"remoteport={port}"]
        cmd += [f"remoteip={ip}"]
        return _run(cmd) is not None

    if system in {"Linux", "Darwin"}:
        tool = _unix_firewall_tool()
        if tool == "ufw":
            cmd = ["ufw", "delete", "deny", "out", "to", ip]
            if port is not None:
                cmd += ["port", str(port), protocol]
        elif tool == "firewall-cmd":
            if port is None:
                rule = f"rule family=ipv4 destination address={ip} drop"
            else:
                rule = (
                    f"rule family=ipv4 destination address={ip} "
                    f"port port={port} protocol={protocol} drop"
                )
            cmd = ["firewall-cmd", "--permanent", "--remove-rich-rule", rule]
            if _run(cmd) is None:
                return False
            return _run(["firewall-cmd", "--reload"]) is not None
        elif tool == "iptables":
            cmd = ["iptables", "-D", "OUTPUT", "-d", ip]
            if port is not None:
                cmd += ["-p", protocol, "--dport", str(port)]
            cmd += ["-j", "DROP"]
        else:
            return False
        return _run(cmd) is not None

    return False


async def async_unblock_remote_firewall(
    host: str, port: int | None = None, protocol: str = "tcp"
) -> bool:
    """Asynchronous wrapper for :func:`unblock_remote_firewall`."""

    return await asyncio.to_thread(unblock_remote_firewall, host, port, protocol)


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
    exe: str | None = None


@dataclass(slots=True)
class ActiveConnection:
    """Information about an active network connection."""

    laddr: tuple[str, int] | None
    raddr: tuple[str, int] | None
    status: str
    pid: int | None
    process: str
    exe: str | None = None


_SERVICE_CACHE: dict[int, str] = {}
_PROC_NAME_CACHE: dict[int, str] = {}
_PROC_EXE_CACHE: dict[int, str] = {}


def network_snapshot() -> list[psutil._common.sconn]:
    """Return a snapshot of current inet connections."""

    try:
        return psutil.net_connections(kind="inet")
    except Exception:
        return []


async def async_network_snapshot() -> list[psutil._common.sconn]:
    """Asynchronous wrapper for :func:`network_snapshot`."""

    return await asyncio.to_thread(network_snapshot)


def refresh_process_cache(pids: Iterable[int]) -> None:
    """Populate process caches for ``pids`` in bulk.

    Parameters
    ----------
    pids:
        Iterable of process IDs to query. Only PIDs missing from the caches
        will trigger lookups.
    """

    missing = {pid for pid in pids if pid not in _PROC_NAME_CACHE}
    if not missing:
        return

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        pid = proc.info.get("pid")
        if pid not in missing:
            continue
        name = proc.info.get("name") or "unknown"
        exe = proc.info.get("exe")
        _PROC_NAME_CACHE[pid] = name
        if exe:
            _PROC_EXE_CACHE[pid] = exe
        missing.discard(pid)
        if not missing:
            return

    for pid in list(missing):
        try:
            p = psutil.Process(pid)
            _PROC_NAME_CACHE[pid] = p.name()
            exe = p.exe()
            if exe:
                _PROC_EXE_CACHE[pid] = exe
        except Exception:
            _PROC_NAME_CACHE[pid] = "unknown"
        missing.discard(pid)


async def async_refresh_process_cache(pids: Iterable[int]) -> None:
    """Asynchronous wrapper for :func:`refresh_process_cache`."""

    await asyncio.to_thread(refresh_process_cache, pids)


def list_open_ports(
    connections: Iterable[psutil._common.sconn] | None = None,
) -> dict[int, list[LocalPort]]:
    """Return a mapping of listening ports to :class:`LocalPort` objects.

    Reuses cached service names and process names to reduce repeated lookups
    when scanning ports frequently.
    """

    ports: dict[int, list[LocalPort]] = {}
    try:
        if connections is None:
            connections = network_snapshot()
        connections = [c for c in connections if c.status == psutil.CONN_LISTEN and c.laddr]
        refresh_process_cache({c.pid for c in connections if c.pid is not None})

        for conn in connections:
            port = conn.laddr.port
            pid: int | None = conn.pid

            if pid is not None:
                proc_name = _PROC_NAME_CACHE.get(pid, "unknown")
                proc_exe = _PROC_EXE_CACHE.get(pid)
            else:
                proc_name = "unknown"
                proc_exe = None

            service = _SERVICE_CACHE.get(port)
            if service is None:
                try:
                    service = socket.getservbyport(port)
                except Exception:
                    service = "unknown"
                _SERVICE_CACHE[port] = service

            ports.setdefault(port, []).append(LocalPort(port, pid, proc_name, service, proc_exe))
    except Exception:
        return {}

    return {p: v for p, v in sorted(ports.items())}


async def async_list_open_ports(
    connections: Iterable[psutil._common.sconn] | None = None,
) -> dict[int, list[LocalPort]]:
    """Asynchronous wrapper for :func:`list_open_ports`."""

    return await asyncio.to_thread(list_open_ports, connections)


def list_active_connections(connections: Iterable[psutil._common.sconn] | None = None) -> dict[str, list[ActiveConnection]]:
    """Return a mapping of ``"ip:port"`` to :class:`ActiveConnection` objects."""

    conns: dict[str, list[ActiveConnection]] = {}
    try:
        if connections is None:
            connections = network_snapshot()
        connections = [c for c in connections if c.raddr]
        refresh_process_cache({c.pid for c in connections if c.pid is not None})

        for conn in connections:
            pid: int | None = conn.pid
            if pid is not None:
                proc_name = _PROC_NAME_CACHE.get(pid, "unknown")
                proc_exe = _PROC_EXE_CACHE.get(pid)
            else:
                proc_name = "unknown"
                proc_exe = None

            key = f"{conn.raddr.ip}:{conn.raddr.port}"
            laddr = (conn.laddr.ip, conn.laddr.port) if conn.laddr else None
            raddr = (conn.raddr.ip, conn.raddr.port)
            conns.setdefault(key, []).append(
                ActiveConnection(
                    laddr,
                    raddr,
                    conn.status,
                    pid,
                    proc_name,
                    proc_exe,
                )
            )
    except Exception:
        return {}

    return {k: v for k, v in sorted(conns.items())}


async def async_list_active_connections(
    connections: Iterable[psutil._common.sconn] | None = None,
) -> dict[str, list[ActiveConnection]]:
    """Asynchronous wrapper for :func:`list_active_connections`."""

    return await asyncio.to_thread(list_active_connections, connections)


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


async def async_kill_process_by_port(port: int, *, tree: bool = False) -> bool:
    """Asynchronous wrapper for :func:`kill_process_by_port`."""

    return await asyncio.to_thread(kill_process_by_port, port, tree=tree)


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


async def async_kill_port_range(
    start: int, end: int, *, tree: bool = False
) -> dict[int, bool]:
    """Asynchronous wrapper for :func:`kill_port_range`."""

    return await asyncio.to_thread(kill_port_range, start, end, tree=tree)


def kill_connections_by_remote(host: str, port: int | None = None, *, tree: bool = False) -> bool:
    """Terminate processes with connections to ``host`` and optional ``port``."""

    ip = resolve_host(host)

    killed = False
    for conn in psutil.net_connections(kind="inet"):
        if not conn.raddr or conn.pid is None:
            continue
        if conn.raddr.ip != ip:
            continue
        if port is not None and conn.raddr.port != port:
            continue
        if tree:
            ok = kill_process_tree(conn.pid)
        else:
            ok = kill_process(conn.pid)
        killed = killed or ok
    return killed


def kill_connections_by_remotes(
    hosts: Iterable[str], port: int | None = None, *, tree: bool = False
) -> dict[str, bool]:
    """Terminate processes connected to any of ``hosts``.

    Parameters
    ----------
    hosts:
        Iterable of hostnames or IP addresses.
    port:
        Optional port number to match. When ``None`` all ports are
        considered.
    tree:
        If ``True`` processes are terminated with their children via
        :func:`kill_process_tree`.
    """

    results: dict[str, bool] = {}
    for host in hosts:
        results[host] = kill_connections_by_remote(host, port=port, tree=tree)
    return results


async def async_kill_connections_by_remote(
    host: str, port: int | None = None, *, tree: bool = False
) -> bool:
    """Asynchronous wrapper for :func:`kill_connections_by_remote`."""

    return await asyncio.to_thread(kill_connections_by_remote, host, port=port, tree=tree)


async def async_kill_connections_by_remotes(
    hosts: Iterable[str], port: int | None = None, *, tree: bool = False
) -> dict[str, bool]:
    """Asynchronous wrapper for :func:`kill_connections_by_remotes`."""

    return await asyncio.to_thread(kill_connections_by_remotes, hosts, port=port, tree=tree)


def monitor_network(
    *,
    port_watchdog: "PortWatchdog | None" = None,
    conn_watchdog: "ConnectionWatchdog | None" = None,
) -> tuple[dict[int, list[LocalPort]], dict[str, list[ActiveConnection]]]:
    """Snapshot network state and feed it to any provided watchdogs."""

    conns = network_snapshot()
    ports = list_open_ports(conns)
    remote = list_active_connections(conns)

    if port_watchdog:
        port_watchdog.check(ports)
        port_watchdog.expire()
        port_watchdog.blocker.check()

    if conn_watchdog:
        conn_watchdog.check(remote)
        conn_watchdog.expire()
        conn_watchdog.blocker.check()

    return ports, remote


async def async_monitor_network(
    *,
    port_watchdog: "PortWatchdog | None" = None,
    conn_watchdog: "ConnectionWatchdog | None" = None,
) -> tuple[dict[int, list[LocalPort]], dict[str, list[ActiveConnection]]]:
    """Asynchronous wrapper for :func:`monitor_network`."""

    return await asyncio.to_thread(
        monitor_network,
        port_watchdog=port_watchdog,
        conn_watchdog=conn_watchdog,
    )


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
    module = f"src.security_center{'_hidden' if hide_console else ''}"
    use_script = script.is_file()

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

    if use_script:
        args = [str(python), str(script)]
        params = f'"{script}"'
    else:
        args = [str(python), "-m", module]
        params = f'-m {module}'

    if is_admin():
        return run_command_background(args, **kwargs)

    system = platform.system()

    if system == "Windows":
        try:
            import ctypes  # lazy import
            show = 0 if hide_console else 1
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(python), params, None, show)
            return rc > 32
        except Exception:
            return False
    elif system in {"Linux", "Darwin"}:
        if use_script:
            cmd = ["sudo", str(python), str(script)]
        else:
            cmd = ["sudo", str(python), "-m", module]
        return run_command_background(cmd, **kwargs)

    return False

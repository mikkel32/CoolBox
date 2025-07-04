from __future__ import annotations

"""High level manager combining network watchdogs and monitoring."""

from typing import Optional, Iterable
import asyncio

from .process_blocker import ProcessBlocker
from .port_watchdog import PortWatchdog
from .connection_watchdog import ConnectionWatchdog
from .network_monitor import NetworkMonitor, AsyncNetworkMonitor
from .network_baseline import NetworkBaseline
from . import security, security_log


class NetworkGuard:
    """Coordinate watchdogs and periodic monitoring."""

    def __init__(
        self,
        interval: float = 5.0,
        *,
        firewall: bool = False,
        baseline: NetworkBaseline | None = None,
        auto_block_unknown: bool = False,
        auto_threshold: int = 1,
        anomaly_ttl: float = 60.0,
    ) -> None:
        self.blocker = ProcessBlocker()
        self.port_watchdog = PortWatchdog(blocker=self.blocker, firewall=firewall)
        self.conn_watchdog = ConnectionWatchdog(blocker=self.blocker, firewall=firewall)
        self.baseline = baseline or NetworkBaseline()
        self.auto_block_unknown = auto_block_unknown
        self.auto_threshold = max(1, auto_threshold)
        self.monitor = NetworkMonitor(
            interval=interval,
            port_watchdog=self.port_watchdog,
            conn_watchdog=self.conn_watchdog,
            baseline=self.baseline,
            callback=self._on_monitor_update,
            anomaly_ttl=anomaly_ttl,
        )

    # ------------------------------------------------------------------
    # Monitor control
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.monitor.start()

    def stop(self, timeout: Optional[float] = None) -> None:
        self.monitor.stop(timeout)

    def __enter__(self) -> "NetworkGuard":
        """Start monitoring when entering a context."""
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Stop monitoring when leaving a context."""
        self.stop()

    @property
    def running(self) -> bool:
        return self.monitor.running

    # ------------------------------------------------------------------
    # Manual blocking helpers
    # ------------------------------------------------------------------
    def block_port(self, port: int, *, firewall: bool = False) -> bool:
        ports = security.list_open_ports()
        entries = ports.get(port, [])
        pids = {e.pid for e in entries if e.pid is not None}
        names = {e.process for e in entries}
        exes = {e.exe for e in entries if e.exe}
        if entries:
            self.port_watchdog.add(port, pids, names=names, exes=exes)
        if firewall:
            if security.block_port_firewall(port):
                security_log.add_security_event("firewall_block_port", f"{port}")
        res = security.kill_process_by_port(port, tree=True)
        if res:
            security_log.add_security_event("block_port", f"{port}")
        return res

    def block_remote(
        self, host: str, port: int | None = None, *, firewall: bool = False
    ) -> bool:
        conns = security.list_active_connections()
        ip = security.resolve_host(host)
        key = f"{ip}:{port}" if port is not None else None

        pids: set[int] = set()
        names: set[str] = set()
        exes: set[str] = set()

        if key:
            entries = conns.get(key) or []
            pids.update(e.pid for e in entries if e.pid is not None)
            names.update(e.process for e in entries)
            exes.update(e.exe for e in entries if e.exe)
            if entries:
                self.conn_watchdog.add(key, pids, names=names, exes=exes)
        else:
            for k, entries in conns.items():
                if k.split(":", 1)[0] != ip:
                    continue
                pids.update(e.pid for e in entries if e.pid is not None)
                names.update(e.process for e in entries)
                exes.update(e.exe for e in entries if e.exe)
                self.conn_watchdog.add(
                    k,
                    {e.pid for e in entries if e.pid is not None},
                    names=names,
                    exes=exes,
                )
        if firewall:
            if security.block_remote_firewall(ip, port):
                security_log.add_security_event(
                    "firewall_block_remote", f"{ip}:{port}" if port else ip
                )
        res = security.kill_connections_by_remote(host, port=port, tree=True)
        if res:
            security_log.add_security_event(
                "block_remote", f"{ip}:{port}" if port else ip
            )
        return res

    def block_port_range(
        self, start: int, end: int, *, firewall: bool = False
    ) -> dict[int, bool]:
        """Kill and watch all listeners within ``start``..``end``."""

        ports_info = security.list_open_ports()
        for port in range(start, end + 1):
            entries = ports_info.get(port) or []
            if not entries:
                continue
            pids = {e.pid for e in entries if e.pid is not None}
            names = {e.process for e in entries}
            exes = {e.exe for e in entries if e.exe}
            self.port_watchdog.add(port, pids, names=names, exes=exes)
            if firewall:
                if security.block_port_firewall(port):
                    security_log.add_security_event("firewall_block_port", f"{port}")
        res = security.kill_port_range(start, end, tree=True)
        for port, ok in res.items():
            if ok:
                security_log.add_security_event("block_port", f"{port}")
        return res

    def block_remotes(
        self, hosts: Iterable[str], port: int | None = None, *, firewall: bool = False
    ) -> dict[str, bool]:
        """Block multiple remote hosts."""

        conns = security.list_active_connections()
        results: dict[str, bool] = {}
        for host in hosts:
            ip = security.resolve_host(host)
            key = f"{ip}:{port}" if port is not None else None

            pids: set[int] = set()
            names: set[str] = set()
            exes: set[str] = set()

            if key:
                entries = conns.get(key) or []
                pids.update(e.pid for e in entries if e.pid is not None)
                names.update(e.process for e in entries)
                exes.update(e.exe for e in entries if e.exe)
                if entries:
                    self.conn_watchdog.add(key, pids, names=names, exes=exes)
            else:
                for k, entries in conns.items():
                    if k.split(":", 1)[0] != ip:
                        continue
                    pids.update(e.pid for e in entries if e.pid is not None)
                    names.update(e.process for e in entries)
                    exes.update(e.exe for e in entries if e.exe)
                    self.conn_watchdog.add(
                        k,
                        {e.pid for e in entries if e.pid is not None},
                        names=names,
                        exes=exes,
                    )

            if firewall:
                if security.block_remote_firewall(ip, port):
                    security_log.add_security_event(
                        "firewall_block_remote", f"{ip}:{port}" if port else ip
                    )
            res = security.kill_connections_by_remote(host, port=port, tree=True)
            if res:
                security_log.add_security_event(
                    "block_remote", f"{ip}:{port}" if port else ip
                )
            results[host] = res
        return results

    # ------------------------------------------------------------------
    # Manual unblocking helpers
    # ------------------------------------------------------------------

    def unblock_port(self, port: int, *, firewall: bool = False) -> bool:
        removed = self.port_watchdog.remove(port)
        if firewall and not self.port_watchdog.firewall:
            if security.unblock_port_firewall(port):
                security_log.add_security_event("firewall_unblock_port", f"{port}")
        if removed:
            security_log.add_security_event("unblock_port", f"{port}")
        return removed

    def unblock_remote(
        self, host: str, port: int | None = None, *, firewall: bool = False
    ) -> bool:
        key = f"{security.resolve_host(host)}:{port}" if port is not None else host
        removed = self.conn_watchdog.remove(key)
        if firewall and not self.conn_watchdog.firewall:
            ip = security.resolve_host(host)
            if security.unblock_remote_firewall(ip, port):
                security_log.add_security_event(
                    "firewall_unblock_remote", f"{ip}:{port}" if port else ip
                )
        if removed:
            security_log.add_security_event(
                "unblock_remote",
                (
                    f"{security.resolve_host(host)}:{port}"
                    if port
                    else security.resolve_host(host)
                ),
            )
        return removed

    def unblock_port_range(
        self, start: int, end: int, *, firewall: bool = False
    ) -> dict[int, bool]:
        results: dict[int, bool] = {}
        for port in range(start, end + 1):
            res = self.unblock_port(port, firewall=firewall)
            if res:
                security_log.add_security_event("unblock_port", f"{port}")
            results[port] = res
        return results

    def unblock_remotes(
        self, hosts: Iterable[str], port: int | None = None, *, firewall: bool = False
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for host in hosts:
            res = self.unblock_remote(host, port=port, firewall=firewall)
            if res:
                ip = security.resolve_host(host)
                security_log.add_security_event(
                    "unblock_remote", f"{ip}:{port}" if port else ip
                )
            results[host] = res
        return results

    # ------------------------------------------------------------------
    # Clearing helpers
    # ------------------------------------------------------------------

    def clear_ports(self) -> None:
        """Remove all watched ports and unblock firewall rules."""
        self.port_watchdog.clear()
        security_log.add_security_event("clear_ports", "all")

    def clear_remotes(self) -> None:
        """Remove all watched remote hosts and unblock firewall rules."""
        self.conn_watchdog.clear()
        security_log.add_security_event("clear_hosts", "all")

    def clear_processes(self) -> None:
        """Remove all blocked process names."""
        self.blocker.clear()
        security_log.add_security_event("clear_processes", "all")

    def clear_all(self) -> None:
        """Clear both port and connection watch lists."""
        self.clear_ports()
        self.clear_remotes()
        self.clear_processes()
        security_log.add_security_event("clear_all", "all")

    def set_auto_block(self, enabled: bool, threshold: int | None = None) -> None:
        """Configure automatic blocking of unknown items."""

        self.auto_block_unknown = bool(enabled)
        if threshold is not None:
            try:
                self.auto_threshold = max(1, int(threshold))
            except Exception:
                pass

    def reset_anomaly_counts(self) -> None:
        """Reset unknown port and host counters."""

        self.monitor.reset_counts()

    def set_anomaly_ttl(self, ttl: float) -> None:
        """Update the anomaly tracking TTL."""

        try:
            self.monitor.anomaly_ttl = max(0.1, float(ttl))
        except Exception:
            pass

    def accept_unknown(self) -> None:
        if self.baseline:
            self.baseline.diff(self.unknown_ports, self.unknown_hosts, update=True)

    def clear_baseline(self) -> None:
        if self.baseline:
            self.baseline.clear()

    # ------------------------------------------------------------------
    # Baseline helpers
    # ------------------------------------------------------------------
    @property
    def unknown_ports(self) -> set[int]:
        return getattr(self.monitor, "unknown_ports", set())

    @property
    def unknown_hosts(self) -> set[str]:
        return getattr(self.monitor, "unknown_hosts", set())

    def _on_monitor_update(self, monitor: NetworkMonitor) -> None:
        if not self.auto_block_unknown:
            return
        for port, count in list(monitor.unknown_port_counts.items()):
            if count >= self.auto_threshold:
                self.block_port(port, firewall=self.port_watchdog.firewall)
                monitor.unknown_port_counts[port] = 0
        for host, count in list(monitor.unknown_host_counts.items()):
            if count >= self.auto_threshold:
                if ":" in host:
                    ip, port_str = host.split(":", 1)
                    try:
                        port_num = int(port_str)
                    except Exception:
                        port_num = None
                else:
                    ip = host
                    port_num = None
                self.block_remote(ip, port_num, firewall=self.conn_watchdog.firewall)
                monitor.unknown_host_counts[host] = 0


class AsyncNetworkGuard:
    """Asynchronous variant of :class:`NetworkGuard`."""

    def __init__(
        self,
        interval: float = 5.0,
        *,
        firewall: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
        baseline: NetworkBaseline | None = None,
        auto_block_unknown: bool = False,
        auto_threshold: int = 1,
        anomaly_ttl: float = 60.0,
    ) -> None:
        self.blocker = ProcessBlocker()
        self.port_watchdog = PortWatchdog(blocker=self.blocker, firewall=firewall)
        self.conn_watchdog = ConnectionWatchdog(blocker=self.blocker, firewall=firewall)
        self.baseline = baseline or NetworkBaseline()
        self.auto_block_unknown = auto_block_unknown
        self.auto_threshold = max(1, auto_threshold)
        self.monitor = AsyncNetworkMonitor(
            interval=interval,
            port_watchdog=self.port_watchdog,
            conn_watchdog=self.conn_watchdog,
            loop=loop,
            baseline=self.baseline,
            callback=self._on_monitor_update,
            anomaly_ttl=anomaly_ttl,
        )

    # ------------------------------------------------------------------
    # Monitor control
    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.monitor.running

    async def start(self) -> None:
        await self.monitor.start()

    async def stop(self) -> None:
        await self.monitor.stop()

    async def __aenter__(self) -> "AsyncNetworkGuard":
        """Start monitoring when entering an async context."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Stop monitoring when leaving an async context."""
        await self.stop()

    # ------------------------------------------------------------------
    # Manual blocking helpers
    # ------------------------------------------------------------------
    async def block_port(self, port: int, *, firewall: bool = False) -> bool:
        ports = await security.async_list_open_ports()
        entries = ports.get(port, [])
        pids = {e.pid for e in entries if e.pid is not None}
        names = {e.process for e in entries}
        exes = {e.exe for e in entries if e.exe}
        if entries:
            await self.port_watchdog.async_add(port, pids, names=names, exes=exes)
        if firewall:
            if await security.async_block_port_firewall(port):
                security_log.add_security_event("firewall_block_port", f"{port}")
        res = await security.async_kill_process_by_port(port, tree=True)
        if res:
            security_log.add_security_event("block_port", f"{port}")
        return res

    async def block_remote(
        self, host: str, port: int | None = None, *, firewall: bool = False
    ) -> bool:
        conns = await security.async_list_active_connections()
        ip = await security.async_resolve_host(host)
        key = f"{ip}:{port}" if port is not None else None

        pids: set[int] = set()
        names: set[str] = set()
        exes: set[str] = set()

        if key:
            entries = conns.get(key) or []
            pids.update(e.pid for e in entries if e.pid is not None)
            names.update(e.process for e in entries)
            exes.update(e.exe for e in entries if e.exe)
            if entries:
                await self.conn_watchdog.async_add(key, pids, names=names, exes=exes)
        else:
            for k, entries in conns.items():
                if k.split(":", 1)[0] != ip:
                    continue
                pids.update(e.pid for e in entries if e.pid is not None)
                names.update(e.process for e in entries)
                exes.update(e.exe for e in entries if e.exe)
                await self.conn_watchdog.async_add(
                    k,
                    {e.pid for e in entries if e.pid is not None},
                    names=names,
                    exes=exes,
                )
        if firewall:
            if await security.async_block_remote_firewall(ip, port):
                security_log.add_security_event(
                    "firewall_block_remote", f"{ip}:{port}" if port else ip
                )
        res = await security.async_kill_connections_by_remote(
            host, port=port, tree=True
        )
        if res:
            security_log.add_security_event(
                "block_remote", f"{ip}:{port}" if port else ip
            )
        return res

    async def block_port_range(
        self, start: int, end: int, *, firewall: bool = False
    ) -> dict[int, bool]:
        ports_info = await security.async_list_open_ports()
        for port in range(start, end + 1):
            entries = ports_info.get(port) or []
            if not entries:
                continue
            pids = {e.pid for e in entries if e.pid is not None}
            names = {e.process for e in entries}
            exes = {e.exe for e in entries if e.exe}
            await self.port_watchdog.async_add(port, pids, names=names, exes=exes)
            if firewall:
                if await security.async_block_port_firewall(port):
                    security_log.add_security_event("firewall_block_port", f"{port}")
        res = await security.async_kill_port_range(start, end, tree=True)
        for port, ok in res.items():
            if ok:
                security_log.add_security_event("block_port", f"{port}")
        return res

    async def block_remotes(
        self, hosts: Iterable[str], port: int | None = None, *, firewall: bool = False
    ) -> dict[str, bool]:
        conns = await security.async_list_active_connections()
        results: dict[str, bool] = {}
        for host in hosts:
            ip = await security.async_resolve_host(host)
            key = f"{ip}:{port}" if port is not None else None

            pids: set[int] = set()
            names: set[str] = set()
            exes: set[str] = set()

            if key:
                entries = conns.get(key) or []
                pids.update(e.pid for e in entries if e.pid is not None)
                names.update(e.process for e in entries)
                exes.update(e.exe for e in entries if e.exe)
                if entries:
                    await self.conn_watchdog.async_add(
                        key, pids, names=names, exes=exes
                    )
            else:
                for k, entries in conns.items():
                    if k.split(":", 1)[0] != ip:
                        continue
                    pids.update(e.pid for e in entries if e.pid is not None)
                    names.update(e.process for e in entries)
                    exes.update(e.exe for e in entries if e.exe)
                    await self.conn_watchdog.async_add(
                        k,
                        {e.pid for e in entries if e.pid is not None},
                        names=names,
                        exes=exes,
                    )

            if firewall:
                if await security.async_block_remote_firewall(ip, port):
                    security_log.add_security_event(
                        "firewall_block_remote", f"{ip}:{port}" if port else ip
                    )
            res = await security.async_kill_connections_by_remote(
                host, port=port, tree=True
            )
            if res:
                security_log.add_security_event(
                    "block_remote", f"{ip}:{port}" if port else ip
                )
            results[host] = res
        return results

    # ------------------------------------------------------------------
    # Manual unblocking helpers
    # ------------------------------------------------------------------
    async def unblock_port(self, port: int, *, firewall: bool = False) -> bool:
        removed = await self.port_watchdog.async_remove(port)
        if firewall and not self.port_watchdog.firewall:
            if await security.async_unblock_port_firewall(port):
                security_log.add_security_event("firewall_unblock_port", f"{port}")
        if removed:
            security_log.add_security_event("unblock_port", f"{port}")
        return removed

    async def unblock_remote(
        self, host: str, port: int | None = None, *, firewall: bool = False
    ) -> bool:
        key = (
            f"{await security.async_resolve_host(host)}:{port}"
            if port is not None
            else host
        )
        removed = await self.conn_watchdog.async_remove(key)
        if firewall and not self.conn_watchdog.firewall:
            ip = await security.async_resolve_host(host)
            if await security.async_unblock_remote_firewall(ip, port):
                security_log.add_security_event(
                    "firewall_unblock_remote", f"{ip}:{port}" if port else ip
                )
        if removed:
            ip = await security.async_resolve_host(host)
            security_log.add_security_event(
                "unblock_remote", f"{ip}:{port}" if port else ip
            )
        return removed

    async def unblock_port_range(
        self, start: int, end: int, *, firewall: bool = False
    ) -> dict[int, bool]:
        results: dict[int, bool] = {}
        for port in range(start, end + 1):
            res = await self.unblock_port(port, firewall=firewall)
            if res:
                security_log.add_security_event("unblock_port", f"{port}")
            results[port] = res
        return results

    async def unblock_remotes(
        self, hosts: Iterable[str], port: int | None = None, *, firewall: bool = False
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for host in hosts:
            res = await self.unblock_remote(host, port=port, firewall=firewall)
            if res:
                ip = await security.async_resolve_host(host)
                security_log.add_security_event(
                    "unblock_remote", f"{ip}:{port}" if port else ip
                )
            results[host] = res
        return results

    # ------------------------------------------------------------------
    # Clearing helpers
    # ------------------------------------------------------------------
    async def clear_ports(self) -> None:
        await self.port_watchdog.async_clear()
        security_log.add_security_event("clear_ports", "all")

    async def clear_remotes(self) -> None:
        await self.conn_watchdog.async_clear()
        security_log.add_security_event("clear_hosts", "all")

    async def clear_processes(self) -> None:
        await self.blocker.async_clear()
        security_log.add_security_event("clear_processes", "all")

    async def clear_all(self) -> None:
        await self.clear_ports()
        await self.clear_remotes()
        await self.clear_processes()
        security_log.add_security_event("clear_all", "all")

    async def set_auto_block(self, enabled: bool, threshold: int | None = None) -> None:
        """Asynchronously configure automatic blocking."""

        self.auto_block_unknown = bool(enabled)
        if threshold is not None:
            try:
                self.auto_threshold = max(1, int(threshold))
            except Exception:
                pass

    async def reset_anomaly_counts(self) -> None:
        """Asynchronously reset anomaly counters."""

        await self.monitor.reset_counts()

    async def set_anomaly_ttl(self, ttl: float) -> None:
        """Asynchronously update the anomaly tracking TTL."""

        try:
            self.monitor.anomaly_ttl = max(0.1, float(ttl))
        except Exception:
            pass

    async def accept_unknown(self) -> None:
        if self.baseline:
            self.baseline.diff(self.unknown_ports, self.unknown_hosts, update=True)

    async def clear_baseline(self) -> None:
        if self.baseline:
            self.baseline.clear()

    # ------------------------------------------------------------------
    # Baseline helpers
    # ------------------------------------------------------------------
    @property
    def unknown_ports(self) -> set[int]:
        return getattr(self.monitor, "unknown_ports", set())

    @property
    def unknown_hosts(self) -> set[str]:
        return getattr(self.monitor, "unknown_hosts", set())

    async def _on_monitor_update(self, monitor: AsyncNetworkMonitor) -> None:
        if not self.auto_block_unknown:
            return
        for port, count in list(monitor.unknown_port_counts.items()):
            if count >= self.auto_threshold:
                await self.block_port(port, firewall=self.port_watchdog.firewall)
                monitor.unknown_port_counts[port] = 0
        for host, count in list(monitor.unknown_host_counts.items()):
            if count >= self.auto_threshold:
                if ":" in host:
                    ip, port_str = host.split(":", 1)
                    try:
                        port_num = int(port_str)
                    except Exception:
                        port_num = None
                else:
                    ip = host
                    port_num = None
                await self.block_remote(
                    ip,
                    port_num,
                    firewall=self.conn_watchdog.firewall,
                )
                monitor.unknown_host_counts[host] = 0

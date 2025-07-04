from __future__ import annotations

"""Background network monitor feeding port and connection watchdogs."""

from dataclasses import dataclass
import asyncio
import threading
from typing import Optional, Callable
import inspect
from collections import deque
import time

from .port_watchdog import PortWatchdog
from .connection_watchdog import ConnectionWatchdog
from . import security
from .network_baseline import NetworkBaseline


@dataclass(slots=True)
class NetworkState:
    """Collected snapshot of open ports and remote connections."""

    ports: dict[int, list[security.LocalPort]]
    connections: dict[str, list[security.ActiveConnection]]


class NetworkMonitor:
    """Periodically capture network state in a background thread."""

    def __init__(
        self,
        interval: float = 5.0,
        *,
        port_watchdog: PortWatchdog | None = None,
        conn_watchdog: ConnectionWatchdog | None = None,
        baseline: NetworkBaseline | None = None,
        callback: Callable[["NetworkMonitor"], None] | None = None,
        anomaly_ttl: float = 60.0,
    ) -> None:
        self.interval = max(interval, 0.1)
        self.port_watchdog = port_watchdog
        self.conn_watchdog = conn_watchdog
        self.baseline = baseline
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_state: Optional[NetworkState] = None
        self.unknown_ports: set[int] = set()
        self.unknown_hosts: set[str] = set()
        self.unknown_port_counts: dict[int, int] = {}
        self.unknown_host_counts: dict[str, int] = {}
        self._callback = callback
        self.anomaly_ttl = max(anomaly_ttl, 0.1)
        self._port_history: dict[int, deque[float]] = {}
        self._host_history: dict[str, deque[float]] = {}

    # ------------------------------------------------------------------
    # Thread control
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        if not self.running:
            return
        self._stop.set()
        self._thread.join(timeout)
        self._thread = None

    def reset_counts(self) -> None:
        """Clear accumulated anomaly counters."""

        self.unknown_port_counts.clear()
        self.unknown_host_counts.clear()
        self._port_history.clear()
        self._host_history.clear()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            ports, conns = security.monitor_network(
                port_watchdog=self.port_watchdog,
                conn_watchdog=self.conn_watchdog,
            )
            self.last_state = NetworkState(ports, conns)
            if self.baseline:
                self.unknown_ports, self.unknown_hosts = self.baseline.diff(
                    ports.keys(), conns.keys()
                )
                now = time.time()
                ttl = self.anomaly_ttl
                for p in self.unknown_ports:
                    hist = self._port_history.setdefault(p, deque())
                    hist.append(now)
                for h in self.unknown_hosts:
                    hist = self._host_history.setdefault(h, deque())
                    hist.append(now)
                # prune histories and update counts
                for key, hist in list(self._port_history.items()):
                    while hist and now - hist[0] > ttl:
                        hist.popleft()
                    if hist:
                        self.unknown_port_counts[key] = len(hist)
                    else:
                        self._port_history.pop(key, None)
                        self.unknown_port_counts.pop(key, None)
                for key, hist in list(self._host_history.items()):
                    while hist and now - hist[0] > ttl:
                        hist.popleft()
                    if hist:
                        self.unknown_host_counts[key] = len(hist)
                    else:
                        self._host_history.pop(key, None)
                        self.unknown_host_counts.pop(key, None)
            if self._callback:
                try:
                    self._callback(self)
                except Exception:
                    pass
            if self._stop.wait(self.interval):
                break


class AsyncNetworkMonitor:
    """Asynchronously capture network state in a background task."""

    def __init__(
        self,
        interval: float = 5.0,
        *,
        port_watchdog: PortWatchdog | None = None,
        conn_watchdog: ConnectionWatchdog | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        baseline: NetworkBaseline | None = None,
        callback: Callable[["AsyncNetworkMonitor"], None] | None = None,
        anomaly_ttl: float = 60.0,
    ) -> None:
        self.interval = max(interval, 0.1)
        self.port_watchdog = port_watchdog
        self.conn_watchdog = conn_watchdog
        self.baseline = baseline
        self.loop = loop or asyncio.get_event_loop()
        self._task: asyncio.Task | None = None
        self.last_state: Optional[NetworkState] = None
        self.unknown_ports: set[int] = set()
        self.unknown_hosts: set[str] = set()
        self.unknown_port_counts: dict[int, int] = {}
        self.unknown_host_counts: dict[str, int] = {}
        self._callback = callback
        self.anomaly_ttl = max(anomaly_ttl, 0.1)
        self._port_history: dict[int, deque[float]] = {}
        self._host_history: dict[str, deque[float]] = {}

    # ------------------------------------------------------------------
    # Task control
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._task = self.loop.create_task(self._run())

    async def stop(self) -> None:
        if not self.running:
            return
        assert self._task is not None
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def reset_counts(self) -> None:
        """Asynchronously clear anomaly counters."""

        self.unknown_port_counts.clear()
        self.unknown_host_counts.clear()
        self._port_history.clear()
        self._host_history.clear()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        try:
            while True:
                ports, conns = await security.async_monitor_network(
                    port_watchdog=self.port_watchdog,
                    conn_watchdog=self.conn_watchdog,
                )
                self.last_state = NetworkState(ports, conns)
                if self.baseline:
                    self.unknown_ports, self.unknown_hosts = self.baseline.diff(
                        ports.keys(), conns.keys()
                    )
                    now = time.time()
                    ttl = self.anomaly_ttl
                    for p in self.unknown_ports:
                        hist = self._port_history.setdefault(p, deque())
                        hist.append(now)
                    for h in self.unknown_hosts:
                        hist = self._host_history.setdefault(h, deque())
                        hist.append(now)
                    for key, hist in list(self._port_history.items()):
                        while hist and now - hist[0] > ttl:
                            hist.popleft()
                        if hist:
                            self.unknown_port_counts[key] = len(hist)
                        else:
                            self._port_history.pop(key, None)
                            self.unknown_port_counts.pop(key, None)
                    for key, hist in list(self._host_history.items()):
                        while hist and now - hist[0] > ttl:
                            hist.popleft()
                        if hist:
                            self.unknown_host_counts[key] = len(hist)
                        else:
                            self._host_history.pop(key, None)
                            self.unknown_host_counts.pop(key, None)
                if self._callback:
                    try:
                        res = self._callback(self)
                        if inspect.iscoroutine(res):
                            await res
                    except Exception:
                        pass
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            pass

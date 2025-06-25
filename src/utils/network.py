"""Networking helpers used by CoolBox tools."""

from __future__ import annotations

import asyncio
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Dict, Iterable
import subprocess
import platform
import time
import ipaddress
import psutil

from .cache import CacheManager

# Simple disk-backed cache for port scan results. Each entry maps
# ``"host|start|end"`` to a list of open ports. Results are persisted to
# disk so expensive scans aren't repeated between sessions.
_CACHE_FILE = Path(
    os.environ.get(
        "NETWORK_CACHE_FILE",
        str(Path.home() / ".coolbox" / "cache" / "scan_cache.json"),
    )
)

# Cache manager instance used by both sync and async scanners
PORT_CACHE: CacheManager[List[int]] = CacheManager[List[int]](_CACHE_FILE)

# In-memory cache for host resolution results
_HOST_CACHE: Dict[tuple[str, int | None], tuple[str, int, float]] = {}
_HOST_CACHE_TTL = float(os.environ.get("HOST_CACHE_TTL", 300))


def _resolve_host(host: str, family: int | None = None) -> tuple[str, int]:
    """Resolve ``host`` and return address and family.

    When *family* is ``None`` IPv4 is preferred when available. Results are
    cached for ``_HOST_CACHE_TTL`` seconds to avoid repeated DNS lookups.
    """
    key = (host, family)
    cached = _HOST_CACHE.get(key)
    if cached and time.time() - cached[2] < _HOST_CACHE_TTL:
        return cached[0], cached[1]

    try:
        infos = socket.getaddrinfo(host, None, family=family or 0)
        if family is None:
            ipv4 = next((i for i in infos if i[0] == socket.AF_INET), None)
            info = ipv4 or infos[0]
        else:
            info = next((i for i in infos if i[0] == family), infos[0])
        addr, resolved_family = info[4][0], info[0]
    except Exception:
        resolved_family = socket.AF_INET6 if family == socket.AF_INET6 else socket.AF_INET
        addr = host

    _HOST_CACHE[key] = (addr, resolved_family, time.time())
    return addr, resolved_family


def clear_scan_cache() -> None:
    """Remove all cached scan results and host lookups."""
    PORT_CACHE.clear()
    _HOST_CACHE.clear()


def clear_host_cache() -> None:
    """Clear cached DNS lookups."""
    _HOST_CACHE.clear()


def parse_port_range(port_str: str) -> tuple[int, int]:
    """Return ``(start, end)`` from ``port_str`` or raise ``ValueError``."""

    if "-" in port_str:
        start_s, end_s = port_str.split("-", 1)
    else:
        start_s = end_s = port_str

    start = int(start_s)
    end = int(end_s)

    if not (1 <= start <= 65535 and 1 <= end <= 65535 and start <= end):
        raise ValueError(f"Invalid port range: {port_str}")

    return start, end


def detect_local_hosts(max_hosts_per_network: int = 256) -> list[str]:
    """Return a list of hosts on local IPv4 networks.

    ``max_hosts_per_network`` limits the number of addresses returned per
    network. Larger networks are truncated by increasing the prefix length so
    no more than the requested number of hosts are scanned.
    """

    hosts: list[str] = []
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family != socket.AF_INET or not addr.netmask:
                continue
            try:
                network = ipaddress.ip_network(
                    f"{addr.address}/{addr.netmask}", strict=False
                )
            except Exception:
                continue

            if max_hosts_per_network and network.num_addresses - 2 > max_hosts_per_network:
                import math

                needed_prefix = 32 - math.ceil(
                    math.log2(max_hosts_per_network + 2)
                )
                prefix = max(network.prefixlen, needed_prefix)
                network = ipaddress.ip_network(
                    f"{addr.address}/{prefix}", strict=False
                )

            for ip in network.hosts():
                ip_str = str(ip)
                if ip_str != addr.address:
                    hosts.append(ip_str)

    return sorted(set(hosts))


def _ping_host(host: str, timeout: float = 1.0) -> bool:
    """Return ``True`` if ``host`` responds to ping within ``timeout`` seconds."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout)), host]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


async def async_filter_active_hosts(
    hosts: Iterable[str],
    progress: Callable[[float | None], None] | None = None,
    *,
    concurrency: int = 100,
    timeout: float = 1.0,
) -> list[str]:
    """Return a subset of ``hosts`` that respond to ping."""

    host_list = list(hosts)
    active: list[str] = []
    total = len(host_list)
    completed = 0

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def run(host: str) -> None:
        nonlocal completed
        async with sem:
            result = await loop.run_in_executor(None, _ping_host, host, timeout)
            if result:
                active.append(host)
        completed += 1
        if progress is not None:
            progress(completed / total)

    tasks = [asyncio.create_task(run(h)) for h in host_list]
    await asyncio.gather(*tasks)

    if progress is not None:
        progress(None)

    return active


async def async_auto_scan(
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
) -> Dict[str, List[int]]:
    """Automatically scan detected hosts on local networks."""

    hosts = detect_local_hosts()
    if not hosts:
        if progress is not None:
            progress(None)
        return {}

    if progress is not None:
        def det_prog(val: float | None) -> None:
            if val is None:
                progress(0.5)
            else:
                progress(val * 0.5)
    else:
        det_prog = None

    hosts = await async_filter_active_hosts(
        hosts,
        det_prog,
        concurrency=concurrency,
        timeout=timeout,
    )
    if not hosts:
        if progress is not None:
            progress(None)
        return {}

    if progress is not None:
        def scan_prog(val: float | None) -> None:
            if val is None:
                progress(1.0)
            else:
                progress(0.5 + val * 0.5)
    else:
        scan_prog = None

    return await async_scan_targets(
        hosts,
        start,
        end,
        scan_prog,
        concurrency=concurrency,
        cache_ttl=cache_ttl,
        family=family,
        timeout=timeout,
    )


def scan_ports(
    host: str,
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
) -> List[int]:
    """Scan *host* from *start* to *end* and return a list of open ports.

    If *progress* is provided it will be called with values between 0 and 1
    as scanning progresses. When scanning completes ``progress(None)`` is
    called to signal completion.  Results are cached for ``cache_ttl``
    seconds to avoid redundant scans.

    ``family`` can be set to ``socket.AF_INET`` or ``socket.AF_INET6`` to
    force IPv4 or IPv6 scanning. ``timeout`` controls the connection timeout
    in seconds.
    """
    cache_key = f"{host}|{start}|{end}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(cache_key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, resolved_family = _resolve_host(host, family)

    open_ports: List[int] = []
    total = end - start + 1

    def scan(port: int) -> int | None:
        with socket.socket(resolved_family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            if sock.connect_ex((addr, port)) == 0:
                return port
        return None

    with ThreadPoolExecutor(max_workers=min(100, total)) as executor:
        future_to_port = {executor.submit(scan, p): p for p in range(start, end + 1)}
        for i, future in enumerate(as_completed(future_to_port), 1):
            if progress is not None:
                progress(i / total)
            result = future.result()
            if result is not None:
                open_ports.append(result)

    if progress is not None:
        progress(None)

    ports = sorted(open_ports)
    if cache_ttl > 0:
        PORT_CACHE.set(cache_key, ports, cache_ttl)
    return ports


async def async_scan_ports(
    host: str,
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
) -> List[int]:
    """Asynchronously scan *host* and return a list of open ports.

    ``concurrency`` limits the number of simultaneous connection attempts,
    preventing excessive resource usage when scanning large port ranges.

    ``family`` forces IPv4 or IPv6 scanning when set to ``socket.AF_INET`` or
    ``socket.AF_INET6``. ``timeout`` sets the connection timeout in seconds.
    """

    cache_key = f"{host}|{start}|{end}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(cache_key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, resolved_family = _resolve_host(host, family)

    open_ports: list[int] = []
    total = end - start + 1
    completed = 0

    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def scan(port: int) -> int | None:
        nonlocal completed
        try:
            async with sem:
                conn = asyncio.open_connection(addr, port, family=resolved_family)
                reader, writer = await asyncio.wait_for(conn, timeout=timeout)
                writer.close()
                await writer.wait_closed()
                return port
        except Exception:
            return None
        finally:
            completed += 1
            if progress is not None:
                progress(completed / total)

    tasks = [asyncio.create_task(scan(p)) for p in range(start, end + 1)]
    for task in asyncio.as_completed(tasks):
        result = await task
        if result is not None:
            open_ports.append(result)

    if progress is not None:
        progress(None)

    ports = sorted(open_ports)
    if cache_ttl > 0:
        PORT_CACHE.set(cache_key, ports, cache_ttl)
    return ports


def scan_targets(
    hosts: Iterable[str],
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
) -> Dict[str, List[int]]:
    """Scan multiple ``hosts`` and return a mapping of host->open ports.

    ``family`` behaves the same as in :func:`scan_ports` and allows forcing
    IPv4 or IPv6. ``timeout`` is passed to :func:`scan_ports`.
    """

    host_list = list(hosts)
    results: Dict[str, List[int]] = {}
    total = len(host_list)
    completed = 0

    for host in host_list:
        results[host] = scan_ports(
            host,
            start,
            end,
            cache_ttl=cache_ttl,
            family=family,
            timeout=timeout,
        )
        completed += 1
        if progress is not None:
            progress(completed / total)

    if progress is not None:
        progress(None)

    return results


async def async_scan_targets(
    hosts: Iterable[str],
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
) -> Dict[str, List[int]]:
    """Asynchronously scan multiple hosts.

    ``family`` behaves the same as in :func:`async_scan_ports`. ``timeout`` is
    passed to :func:`async_scan_ports`.
    """

    host_list = list(hosts)
    results: Dict[str, List[int]] = {}
    total = len(host_list)
    completed = 0

    async def run(host: str) -> None:
        nonlocal completed
        results[host] = await async_scan_ports(
            host,
            start,
            end,
            concurrency=concurrency,
            cache_ttl=cache_ttl,
            family=family,
            timeout=timeout,
        )
        completed += 1
        if progress is not None:
            progress(completed / total)

    await asyncio.gather(*(run(h) for h in host_list))

    if progress is not None:
        progress(None)

    return results

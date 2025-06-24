"""Networking helpers used by CoolBox tools."""

from __future__ import annotations

import asyncio
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Dict, Iterable

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


def _resolve_host(host: str) -> tuple[str, int]:
    """Resolve ``host`` preferring IPv4 when available."""
    try:
        infos = socket.getaddrinfo(host, None)
        ipv4 = next((i for i in infos if i[0] == socket.AF_INET), None)
        info = ipv4 or infos[0]
        return info[4][0], info[0]
    except Exception:
        return host, socket.AF_INET


def clear_scan_cache() -> None:
    """Remove all cached scan results from memory and disk."""
    PORT_CACHE.clear()


def scan_ports(
    host: str,
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    *,
    cache_ttl: float = 60.0,
) -> List[int]:
    """Scan *host* from *start* to *end* and return a list of open ports.

    If *progress* is provided it will be called with values between 0 and 1
    as scanning progresses. When scanning completes ``progress(None)`` is
    called to signal completion.  Results are cached for ``cache_ttl``
    seconds to avoid redundant scans.
    """
    cache_key = f"{host}|{start}|{end}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(cache_key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, family = _resolve_host(host)

    open_ports: List[int] = []
    total = end - start + 1

    def scan(port: int) -> int | None:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
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
) -> List[int]:
    """Asynchronously scan *host* and return a list of open ports.

    ``concurrency`` limits the number of simultaneous connection attempts,
    preventing excessive resource usage when scanning large port ranges.
    """

    cache_key = f"{host}|{start}|{end}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(cache_key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, family = _resolve_host(host)

    open_ports: list[int] = []
    total = end - start + 1
    completed = 0

    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def scan(port: int) -> int | None:
        nonlocal completed
        try:
            async with sem:
                conn = asyncio.open_connection(addr, port, family=family)
                reader, writer = await asyncio.wait_for(conn, timeout=0.5)
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
) -> Dict[str, List[int]]:
    """Scan multiple ``hosts`` and return a mapping of host->open ports."""

    host_list = list(hosts)
    results: Dict[str, List[int]] = {}
    total = len(host_list)
    completed = 0

    for host in host_list:
        results[host] = scan_ports(host, start, end, cache_ttl=cache_ttl)
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
) -> Dict[str, List[int]]:
    """Asynchronously scan multiple hosts."""

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
        )
        completed += 1
        if progress is not None:
            progress(completed / total)

    await asyncio.gather(*(run(h) for h in host_list))

    if progress is not None:
        progress(None)

    return results

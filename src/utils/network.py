"""Networking helpers used by CoolBox tools."""

from __future__ import annotations

import asyncio
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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


def _flags_key(*, with_services: bool, with_banner: bool, with_latency: bool) -> str:
    """Return a short string representing option flags for cache keys."""
    return f"{int(with_services)}{int(with_banner)}{int(with_latency)}"


# In-memory cache for host resolution results
_HOST_CACHE: Dict[tuple[str, int | None], tuple[str, int, float]] = {}
_HOST_CACHE_TTL = float(os.environ.get("HOST_CACHE_TTL", 300))

# Cache of port number -> service name mappings used when returning
# detailed scan results. This avoids repeated lookups via
# ``socket.getservbyport`` which can be relatively expensive on some
# platforms.
_SERVICE_CACHE: Dict[int, str] = {}

# Top 100 TCP ports by frequency from the Nmap project. These are used for
# quick "top ports" scans that prioritize commonly open services.
TOP_PORTS: list[int] = [
    80, 23, 443, 21, 22, 25, 3389, 110, 445, 139, 143, 53, 135, 3306, 8080,
    1723, 111, 995, 993, 5900, 1025, 587, 8888, 199, 1720, 465, 548, 113, 81,
    6001, 10000, 514, 5060, 179, 1026, 2000, 8443, 8000, 32768, 554, 26, 1433,
    49152, 2001, 515, 8008, 49154, 1027, 5666, 646, 5000, 5631, 631, 49153,
    8081, 2049, 88, 79, 5800, 106, 2121, 1110, 49155, 6000, 513, 990, 5357,
    427, 49156, 543, 544, 5101, 144, 7, 389, 8009, 3128, 444, 9999, 5009, 7070,
    5190, 3000, 5432, 1900, 3986, 13, 1029, 9, 5051, 6646, 49157, 1028, 873,
    1755, 2717, 4899, 9100, 119, 37
]


@dataclass
class PortInfo:
    """Information about an open port."""

    service: str
    banner: str | None = None
    latency: float | None = None


def _get_service_name(port: int) -> str:
    """Return the service name for ``port`` if known."""
    name = _SERVICE_CACHE.get(port)
    if name is not None:
        return name
    try:
        name = socket.getservbyport(port)
    except Exception:
        name = "unknown"
    _SERVICE_CACHE[port] = name
    return name


def _read_banner(sock: socket.socket, limit: int = 100) -> str | None:
    """Return a banner string from an open socket if available."""
    try:
        data = sock.recv(limit)
    except Exception:
        return None
    return data.decode(errors="ignore").strip() or None


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


def _get_port_number(value: str) -> int:
    """Return the numeric port for ``value`` which may be a service name."""

    if value.isdigit():
        port = int(value)
    else:
        try:
            port = socket.getservbyname(value)
        except Exception:
            raise ValueError(f"Unknown service/port: {value}")
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid port: {value}")
    return port


def parse_port_range(port_str: str) -> tuple[int, int]:
    """Return ``(start, end)`` from ``port_str`` or raise ``ValueError``."""

    if "-" in port_str:
        start_s, end_s = port_str.split("-", 1)
    else:
        start_s = end_s = port_str

    start = _get_port_number(start_s)
    end = _get_port_number(end_s)

    if start > end:
        raise ValueError(f"Invalid port range: {port_str}")

    return start, end


def parse_ports(spec: str, *, allow_top: bool = True) -> list[int]:
    """Return a sorted list of ports from *spec*.

    ``spec`` may include individual ports, ranges (``20-25``) and comma
    separated combinations (``22,80-90``).  A range can optionally include a
    step using ``start-end:step`` which allows scanning only every ``step``
    port.  When ``allow_top`` is ``True`` the ``"topN"`` shortcut expands to the
    ``N`` most common ports from :data:`TOP_PORTS`.
    """

    spec = spec.strip().lower()
    if allow_top and spec.startswith("top"):
        num = spec[3:] or "100"
        top_n = int(num)
        return TOP_PORTS[: max(1, min(top_n, len(TOP_PORTS)))]

    ports: set[int] = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        step = 1
        if ':' in part:
            part, step_str = part.split(':', 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"Invalid step: {step_str}")
        if '-' in part:
            start, end = parse_port_range(part)
            ports.update(range(start, end + 1, step))
        else:
            if step != 1:
                raise ValueError(f"Invalid port specification: {part}:{step}")
            port = _get_port_number(part)
            ports.add(port)

    return sorted(ports)


def parse_hosts(spec: str) -> list[str]:
    """Expand *spec* into a sorted list of host strings.

    The input may contain comma separated values, IPv4/IPv6 networks in
    CIDR notation, or address ranges like ``192.168.1.10-20``.  Hostnames
    and addresses may be mixed freely.
    """

    hosts: set[str] = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue

        if '/' in part:
            try:
                net = ipaddress.ip_network(part, strict=False)
            except Exception:
                hosts.add(part)
            else:
                hosts.update(str(ip) for ip in net.hosts())
            continue

        if '-' in part:
            start_s, end_s = part.split('-', 1)
            try:
                start_ip = ipaddress.ip_address(start_s)
                if '.' in end_s or ':' in end_s:
                    end_ip = ipaddress.ip_address(end_s)
                else:
                    base = int(start_ip)
                    end_ip = start_ip.__class__(base - base % 256 + int(end_s))
                if int(end_ip) < int(start_ip):
                    raise ValueError
            except Exception:
                hosts.add(part)
            else:
                for ip_int in range(int(start_ip), int(end_ip) + 1):
                    hosts.add(str(ipaddress.ip_address(ip_int)))
            continue

        if '*' in part and '.' in part:
            segments = part.split('.')
            if all(seg == '*' or seg.isdigit() for seg in segments):
                base = [s if s != '*' else '0' for s in segments]
                prefix_len = 8 * sum(s != '*' for s in segments)
                try:
                    net = ipaddress.ip_network('.'.join(base) + f'/{prefix_len}', strict=False)
                except Exception:
                    hosts.add(part)
                else:
                    hosts.update(str(ip) for ip in net.hosts())
                continue

        hosts.add(part)

    return sorted(hosts)


def ports_as_range(ports: Iterable[int]) -> tuple[int, int] | None:
    """Return ``(start, end)`` if ``ports`` form a contiguous range."""
    port_list = sorted(set(int(p) for p in ports))
    if not port_list:
        return None
    start, end = port_list[0], port_list[-1]
    if port_list == list(range(start, end + 1)):
        return start, end
    return None


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
    return (
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        == 0
    )


async def _async_ping_host(host: str, timeout: float = 1.0) -> bool:
    """Asynchronously ping ``host`` and return ``True`` if reachable."""

    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout)), host]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout + 1)
        return proc.returncode == 0
    except Exception:
        return False


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

    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def run(host: str) -> None:
        nonlocal completed
        async with sem:
            if await _async_ping_host(host, timeout):
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
    ports: Iterable[int] | None = None,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    ping_concurrency: int | None = None,
    ping_timeout: float | None = None,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> Dict[str, List[int]] | Dict[str, Dict[int, str]] | Dict[str, Dict[int, PortInfo]]:
    """Automatically scan detected hosts on local networks.

    ``ports`` overrides ``start``/``end`` and allows scanning an arbitrary
    list of ports. ``with_services`` adds service names for each open port.
    When ``with_banner`` is true, a short banner string is captured from each
    service and both the banner and service name are returned.
    ``ping_concurrency`` and ``ping_timeout`` override the values used when
    pinging hosts during discovery.
    """

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
        concurrency=ping_concurrency or concurrency,
        timeout=ping_timeout or timeout,
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

    if ports is not None:
        return await async_scan_targets_list(
            hosts,
            ports,
            scan_prog,
            concurrency=concurrency,
            cache_ttl=cache_ttl,
            family=family,
            timeout=timeout,
            with_services=with_services,
            with_banner=with_banner,
            with_latency=with_latency,
        )
    return await async_scan_targets(
        hosts,
        start,
        end,
        scan_prog,
        concurrency=concurrency,
        cache_ttl=cache_ttl,
        family=family,
        timeout=timeout,
        with_services=with_services,
        with_banner=with_banner,
        with_latency=with_latency,
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
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> List[int] | Dict[int, str] | Dict[int, PortInfo]:
    """Scan *host* from *start* to *end* and return open ports.

    If *progress* is provided it will be called with values between 0 and 1
    as scanning progresses. When scanning completes ``progress(None)`` is
    called to signal completion.  Results are cached for ``cache_ttl``
    seconds to avoid redundant scans.

    ``family`` can be set to ``socket.AF_INET`` or ``socket.AF_INET6`` to
    force IPv4 or IPv6 scanning. ``timeout`` controls the connection timeout
    in seconds.
    """
    cache_key = f"{host}|{start}|{end}|{_flags_key(with_services=with_services, with_banner=with_banner, with_latency=with_latency)}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(cache_key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, resolved_family = _resolve_host(host, family)

    open_ports: list[tuple[int, str | None, float | None]] = []
    total = end - start + 1

    def scan(port: int) -> tuple[int, str | None, float | None] | None:
        with socket.socket(resolved_family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            start_ts = time.perf_counter()
            if sock.connect_ex((addr, port)) == 0:
                latency = time.perf_counter() - start_ts if with_latency else None
                banner = _read_banner(sock) if with_banner else None
                return port, banner, latency
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

    ports = sorted(open_ports, key=lambda t: t[0])
    port_nums = [p for p, _, _ in ports]
    if cache_ttl > 0:
        PORT_CACHE.set(cache_key, port_nums, cache_ttl)

    if with_banner or with_latency:
        return {
            p: PortInfo(_get_service_name(p), b, lat if with_latency else None)
            for p, b, lat in ports
        }
    if with_services:
        return {p: _get_service_name(p) for p, _, _ in ports}
    return port_nums


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
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> List[int] | Dict[int, str] | Dict[int, PortInfo]:
    """Asynchronously scan *host* and return a list of open ports.

    ``concurrency`` limits the number of simultaneous connection attempts,
    preventing excessive resource usage when scanning large port ranges.

    ``family`` forces IPv4 or IPv6 scanning when set to ``socket.AF_INET`` or
    ``socket.AF_INET6``. ``timeout`` sets the connection timeout in seconds.
    """

    cache_key = f"{host}|{start}|{end}|{_flags_key(with_services=with_services, with_banner=with_banner, with_latency=with_latency)}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(cache_key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, resolved_family = _resolve_host(host, family)

    open_ports: list[tuple[int, str | None, float | None]] = []
    total = end - start + 1
    completed = 0

    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def scan(port: int) -> tuple[int, str | None, float | None] | None:
        nonlocal completed
        try:
            async with sem:
                start_ts = time.perf_counter()
                conn = asyncio.open_connection(addr, port, family=resolved_family)
                reader, writer = await asyncio.wait_for(conn, timeout=timeout)
                latency = time.perf_counter() - start_ts if with_latency else None
                banner = None
                if with_banner:
                    try:
                        banner_bytes = await asyncio.wait_for(reader.read(100), 0.1)
                        banner = banner_bytes.decode(errors="ignore").strip() or None
                    except Exception:
                        banner = None
                writer.close()
                await writer.wait_closed()
                return port, banner, latency
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

    ports = sorted(open_ports, key=lambda t: t[0])
    port_nums = [p for p, _, _ in ports]
    if cache_ttl > 0:
        PORT_CACHE.set(cache_key, port_nums, cache_ttl)

    if with_banner or with_latency:
        return {
            p: PortInfo(_get_service_name(p), b, lat if with_latency else None)
            for p, b, lat in ports
        }
    if with_services:
        return {p: _get_service_name(p) for p, _, _ in ports}
    return port_nums


def scan_targets(
    hosts: Iterable[str],
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> Dict[str, List[int] | Dict[int, str] | Dict[int, PortInfo]]:
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
            with_services=with_services,
            with_banner=with_banner,
            with_latency=with_latency,
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
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> Dict[str, List[int] | Dict[int, str] | Dict[int, PortInfo]]:
    """Asynchronously scan multiple hosts.

    ``family`` behaves the same as in :func:`async_scan_ports`. ``timeout`` is
    passed to :func:`async_scan_ports`.
    """

    host_list = list(hosts)
    results: Dict[str, List[int]] | Dict[str, Dict[int, str]] | Dict[str, Dict[int, PortInfo]] = {}
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
            with_services=with_services,
            with_banner=with_banner,
            with_latency=with_latency,
        )
        completed += 1
        if progress is not None:
            progress(completed / total)

    await asyncio.gather(*(run(h) for h in host_list))

    if progress is not None:
        progress(None)

    return results


def scan_port_list(
    host: str,
    ports: Iterable[int],
    progress: Callable[[float | None], None] | None = None,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> List[int] | Dict[int, str] | Dict[int, PortInfo]:
    """Scan a specific list of ``ports`` on ``host``."""

    port_list = sorted(set(int(p) for p in ports))
    if not port_list:
        if progress is not None:
            progress(None)
        return {}

    key = f"{host}|{','.join(map(str, port_list))}|{_flags_key(with_services=with_services, with_banner=with_banner, with_latency=with_latency)}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, resolved_family = _resolve_host(host, family)

    open_ports: list[tuple[int, str | None, float | None]] = []
    total = len(port_list)

    def scan(port: int) -> tuple[int, str | None, float | None] | None:
        with socket.socket(resolved_family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            start_ts = time.perf_counter()
            if sock.connect_ex((addr, port)) == 0:
                latency = time.perf_counter() - start_ts if with_latency else None
                banner = _read_banner(sock) if with_banner else None
                return port, banner, latency
        return None

    with ThreadPoolExecutor(max_workers=min(100, total)) as executor:
        future_to_port = {executor.submit(scan, p): p for p in port_list}
        for i, future in enumerate(as_completed(future_to_port), 1):
            if progress is not None:
                progress(i / total)
            result = future.result()
            if result is not None:
                open_ports.append(result)

    if progress is not None:
        progress(None)

    ports_sorted = sorted(open_ports, key=lambda t: t[0])
    port_nums = [p for p, _, _ in ports_sorted]
    if cache_ttl > 0:
        PORT_CACHE.set(key, port_nums, cache_ttl)

    if with_banner or with_latency:
        return {
            p: PortInfo(_get_service_name(p), b, lat if with_latency else None)
            for p, b, lat in ports_sorted
        }
    if with_services:
        return {p: _get_service_name(p) for p, _, _ in ports_sorted}
    return port_nums


async def async_scan_port_list(
    host: str,
    ports: Iterable[int],
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> List[int] | Dict[int, str] | Dict[int, PortInfo]:
    """Asynchronously scan ``ports`` on ``host``."""

    port_list = sorted(set(int(p) for p in ports))
    if not port_list:
        if progress is not None:
            progress(None)
        return {}

    key = f"{host}|{','.join(map(str, port_list))}|{_flags_key(with_services=with_services, with_banner=with_banner, with_latency=with_latency)}"
    if cache_ttl > 0:
        PORT_CACHE.prune()
        cached = PORT_CACHE.get(key, cache_ttl)
        if cached is not None:
            if progress is not None:
                progress(None)
            return cached

    addr, resolved_family = _resolve_host(host, family)

    open_ports: list[tuple[int, str | None, float | None]] = []
    total = len(port_list)
    completed = 0

    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def scan(port: int) -> tuple[int, str | None, float | None] | None:
        nonlocal completed
        try:
            async with sem:
                start_ts = time.perf_counter()
                conn = asyncio.open_connection(addr, port, family=resolved_family)
                reader, writer = await asyncio.wait_for(conn, timeout=timeout)
                latency = time.perf_counter() - start_ts if with_latency else None
                banner = None
                if with_banner:
                    try:
                        data = await asyncio.wait_for(reader.read(100), 0.1)
                        banner = data.decode(errors="ignore").strip() or None
                    except Exception:
                        banner = None
                writer.close()
                await writer.wait_closed()
                return port, banner, latency
        except Exception:
            return None
        finally:
            completed += 1
            if progress is not None:
                progress(completed / total)

    tasks = [asyncio.create_task(scan(p)) for p in port_list]
    for task in asyncio.as_completed(tasks):
        result = await task
        if result is not None:
            open_ports.append(result)

    if progress is not None:
        progress(None)

    ports_sorted = sorted(open_ports, key=lambda t: t[0])
    port_nums = [p for p, _, _ in ports_sorted]
    if cache_ttl > 0:
        PORT_CACHE.set(key, port_nums, cache_ttl)

    if with_banner or with_latency:
        return {
            p: PortInfo(_get_service_name(p), b, lat if with_latency else None)
            for p, b, lat in ports_sorted
        }
    if with_services:
        return {p: _get_service_name(p) for p, _, _ in ports_sorted}
    return port_nums


def scan_top_ports(
    host: str,
    *,
    top: int = 100,
    progress: Callable[[float | None], None] | None = None,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> List[int] | Dict[int, str] | Dict[int, PortInfo]:
    """Scan the Nmap ``top`` ports on ``host``."""

    return scan_port_list(
        host,
        TOP_PORTS[:max(1, min(top, len(TOP_PORTS)))],
        progress,
        cache_ttl=cache_ttl,
        family=family,
        timeout=timeout,
        with_services=with_services,
        with_banner=with_banner,
        with_latency=with_latency,
    )


async def async_scan_top_ports(
    host: str,
    *,
    top: int = 100,
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> List[int] | Dict[int, str] | Dict[int, PortInfo]:
    """Asynchronously scan the Nmap ``top`` ports."""

    return await async_scan_port_list(
        host,
        TOP_PORTS[:max(1, min(top, len(TOP_PORTS)))],
        progress,
        concurrency=concurrency,
        cache_ttl=cache_ttl,
        family=family,
        timeout=timeout,
        with_services=with_services,
        with_banner=with_banner,
        with_latency=with_latency,
    )


def scan_targets_list(
    hosts: Iterable[str],
    ports: Iterable[int],
    progress: Callable[[float | None], None] | None = None,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> Dict[str, List[int] | Dict[int, str] | Dict[int, PortInfo]]:
    """Scan ``hosts`` for a specific list of ``ports``."""

    host_list = list(hosts)
    results: Dict[str, List[int]] | Dict[str, Dict[int, str]] | Dict[str, Dict[int, PortInfo]] = {}
    total = len(host_list)
    completed = 0

    for host in host_list:
        results[host] = scan_port_list(
            host,
            ports,
            cache_ttl=cache_ttl,
            family=family,
            timeout=timeout,
            with_services=with_services,
            with_banner=with_banner,
            with_latency=with_latency,
        )
        completed += 1
        if progress is not None:
            progress(completed / total)

    if progress is not None:
        progress(None)

    return results


async def async_scan_targets_list(
    hosts: Iterable[str],
    ports: Iterable[int],
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
    *,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
) -> Dict[str, List[int] | Dict[int, str] | Dict[int, PortInfo]]:
    """Asynchronously scan ``ports`` on multiple ``hosts``."""

    host_list = list(hosts)
    results: Dict[str, List[int]] | Dict[str, Dict[int, str]] | Dict[str, Dict[int, PortInfo]] = {}
    total = len(host_list)
    completed = 0

    async def run(host: str) -> None:
        nonlocal completed
        results[host] = await async_scan_port_list(
            host,
            ports,
            concurrency=concurrency,
            cache_ttl=cache_ttl,
            family=family,
            timeout=timeout,
            with_services=with_services,
            with_banner=with_banner,
            with_latency=with_latency,
        )
        completed += 1
        if progress is not None:
            progress(completed / total)

    await asyncio.gather(*(run(h) for h in host_list))

    if progress is not None:
        progress(None)

    return results

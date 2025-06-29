"""Networking helpers used by CoolBox tools."""

from __future__ import annotations

import asyncio
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import ssl
import re
from pathlib import Path
from typing import Callable, List, Dict, Iterable, Any, AsyncIterator
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

# Cache of discovered local hosts to avoid recomputing interface networks on
# every auto scan. The TTL can be configured via the ``LOCAL_HOST_CACHE_TTL``
# environment variable.
_LOCAL_HOST_CACHE_TTL = float(os.environ.get("LOCAL_HOST_CACHE_TTL", 60.0))
_LOCAL_HOST_CACHE: list[str] | None = None
_LOCAL_HOST_CACHE_TS: float = 0.0

# Disk-backed cache for reverse DNS lookups so hostname resolution doesn't
# block repeated scans. TTL is configurable via ``DNS_CACHE_TTL``.
_DNS_CACHE_FILE = Path(
    os.environ.get(
        "DNS_CACHE_FILE",
        str(Path.home() / ".coolbox" / "cache" / "dns_cache.json"),
    )
)
_DNS_CACHE_TTL = float(os.environ.get("DNS_CACHE_TTL", 3600.0))
DNS_CACHE: CacheManager[str] = CacheManager[str](_DNS_CACHE_FILE)

# Precompiled regex to parse TTL or hop limit from ping output. This captures
# values in forms like ``ttl=64`` or ``hlim:64`` and is case-insensitive.
_TTL_RE = re.compile(r"\b(?:ttl|hlim)[=\s:]+(\d+)", re.IGNORECASE)


def _cancelled(event: Any) -> bool:
    """Return ``True`` if the optional *event* is set."""

    try:
        return bool(event and event.is_set())
    except Exception:
        return False


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


@dataclass
class HTTPInfo:
    """Simple HTTP metadata for a host and port."""

    server: str | None = None
    title: str | None = None


@dataclass
class AutoScanInfo:
    """Detailed information returned by :func:`async_auto_scan`.

    ``ports`` holds the open port results while optional metadata like
    ``hostname`` or ``mac`` may be included when requested. ``vendor`` is a
    best-effort lookup based on the MAC address prefix.
    """

    ports: List[int] | Dict[int, str] | Dict[int, PortInfo]
    hostname: str | None = None
    mac: str | None = None
    connections: Dict[int, int] | None = None
    os_guess: str | None = None
    ping_latency: float | None = None
    ttl: int | None = None
    vendor: str | None = None
    http_info: Dict[int, HTTPInfo] | None = None
    device_type: str | None = None
    _risk_score: int | None = field(default=None, init=False, repr=False)

    @property
    def risk_score(self) -> int | None:  # pragma: no cover - simple accessor
        """Return the cached risk score if computed."""

        return self._risk_score

    @risk_score.setter
    def risk_score(self, value: int | None) -> None:  # pragma: no cover - simple mutator
        self._risk_score = value

    def compute_risk_score(self) -> int:
        """Calculate and store the risk score for this host."""
        score = _estimate_risk(self)
        self._risk_score = score
        return score


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


def clear_dns_cache() -> None:
    """Remove cached hostnames."""

    DNS_CACHE.clear()


def clear_local_host_cache() -> None:
    """Clear cached local host discovery results."""

    global _LOCAL_HOST_CACHE, _LOCAL_HOST_CACHE_TS
    _LOCAL_HOST_CACHE = None
    _LOCAL_HOST_CACHE_TS = 0.0


def get_mac_address(host: str) -> str | None:
    """Return the MAC address for ``host`` if available."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["arp", "-a", host]
    else:
        cmd = ["arp", "-n", host]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
    except Exception:
        return None
    for line in result.stdout.splitlines():
        if host in line:
            parts = line.split()
            for part in parts:
                if ":" in part and len(part) >= 17:
                    return part
    return None


def get_mac_vendor(mac: str | None) -> str | None:
    """Return a vendor name for ``mac`` using a simple prefix lookup."""

    if not mac:
        return None
    mac = mac.lower().replace("-", ":")
    parts = mac.split(":")
    if len(parts) < 3:
        return None
    prefix = ":".join(parts[:3])
    return _MAC_VENDORS.get(prefix)


async def async_get_hostname(host: str, *, ttl: float | None = None) -> str | None:
    """Return the hostname for ``host`` with caching."""

    effective_ttl = _DNS_CACHE_TTL if ttl is None else ttl
    cached = DNS_CACHE.get(host, effective_ttl)
    if cached is not None:
        return cached

    loop = asyncio.get_running_loop()
    try:
        name = await loop.run_in_executor(None, socket.gethostbyaddr, host)
        hostname = name[0]
    except Exception:
        hostname = None

    if hostname:
        DNS_CACHE.set(host, hostname, effective_ttl)
    return hostname


_LOCAL_ADDRS = {
    addr.address
    for addrs in psutil.net_if_addrs().values()
    for addr in addrs
    if addr.family in (socket.AF_INET, socket.AF_INET6)
}

# Minimal MAC prefix -> vendor mapping used for vendor lookups. This is not
# exhaustive but provides common examples without requiring an external file.
_MAC_VENDORS = {
    "00:1a:2b": "Cisco",
    "00:0c:29": "VMware",
    "00:1c:42": "Parallels",
    "b8:27:eb": "Raspberry Pi Foundation",
    "3c:5a:b4": "Google",
}


def _is_local_host(host: str) -> bool:
    """Return ``True`` if ``host`` refers to this machine."""
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = host
    return ip in _LOCAL_ADDRS or ip.startswith("127.") or ip == "::1"


def _get_connection_counts(ports: Iterable[int]) -> Dict[int, int]:
    """Return active connection counts for ``ports`` on the local machine."""
    counts = {p: 0 for p in ports}
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port in counts:
                counts[conn.laddr.port] += 1
    except Exception:
        pass
    return counts


def _extract_ttl_from_ping(output: str) -> int | None:
    """Return TTL or hop limit extracted from raw ping ``output``."""

    match = _TTL_RE.search(output)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _guess_os_from_ttl(ttl: int | None) -> str | None:
    """Return a rough OS guess based on ``ttl`` from ping."""

    if ttl is None:
        return None
    if ttl >= 255:
        return "Cisco/Network"
    if ttl >= 128:
        return "Windows"
    if ttl >= 64:
        return "Linux"
    return "Unknown"


def _guess_device_type(info: AutoScanInfo) -> str | None:
    """Return a best-effort device type guess for ``info``."""

    ports = (
        info.ports.keys()
        if isinstance(info.ports, dict)
        else info.ports
    )
    vendor = (info.vendor or "").lower()
    server_str = " ".join(
        (http.server or "").lower()
        for http in (info.http_info or {}).values()
        if http is not None
    )

    if 9100 in ports or 515 in ports:
        return "Printer"
    if any(v in vendor for v in ("cisco", "netgear", "tp-link", "d-link")):
        return "Router"
    if "vmware" in vendor:
        return "Virtual Machine"
    if "raspberry" in vendor or "raspberry" in server_str:
        return "IoT"
    if 22 in ports and not (80 in ports or 443 in ports):
        return "Headless"
    return None


def _estimate_risk(info: AutoScanInfo) -> int:
    """Return a heuristic risk score for ``info`` between 0 and 100."""

    ports = info.ports.keys() if isinstance(info.ports, dict) else info.ports
    score = 0
    weights = {
        23: 40,  # telnet
        21: 35,  # ftp
        445: 30,  # smb
        139: 20,  # netbios
        3389: 20,  # rdp
        80: 10,
        443: 5,
        22: 5,
    }
    for p in ports:
        score += weights.get(p, 1)

    open_count = len(list(ports))
    if open_count > 5:
        score += (open_count - 5) * 2

    if info.os_guess:
        if info.os_guess == "Windows":
            score += 5
        elif info.os_guess == "Linux":
            score += 3
        else:
            score += 2

    device = info.device_type or _guess_device_type(info)
    if device == "Router":
        score += 15
    elif device == "IoT":
        score += 10
    elif device == "Printer":
        score += 5

    if info.vendor and info.vendor.lower() in {
        "cisco",
        "netgear",
        "tp-link",
        "d-link",
    }:
        score += 5

    return min(score, 100)


async def async_get_http_info(host: str, port: int, timeout: float = 2.0) -> HTTPInfo | None:
    """Return simple HTTP information for ``host`` on ``port``.

    A ``GET /`` request is made and the ``Server`` header and HTML ``<title>``
    value are extracted when available. HTTPS is used automatically for port
    443.
    """

    try:
        addr, family = _resolve_host(host)
        ssl_ctx = ssl.create_default_context() if port == 443 else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(addr, port, family=family, ssl=ssl_ctx),
            timeout,
        )
        request = f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()
        data = bytearray()
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) >= 65536:
                break
        writer.close()
        await writer.wait_closed()
    except Exception:
        return None

    # split headers and body
    try:
        header_part, body = bytes(data).split(b"\r\n\r\n", 1)
    except ValueError:
        header_part, body = bytes(data), b""
    headers = header_part.decode(errors="ignore").splitlines()
    server = None
    for line in headers:
        if line.lower().startswith("server:"):
            server = line.split(":", 1)[1].strip()
            break
    title = None
    if b"<title" in body.lower():
        try:
            start = body.lower().index(b"<title")
            end = body.lower().index(b"</title", start)
            title_tag = body[start:end]
            title_start = title_tag.index(b">") + 1
            title = title_tag[title_start:].decode(errors="ignore").strip()
        except Exception:
            title = None
    return HTTPInfo(server, title)


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


def detect_local_hosts(max_hosts_per_network: int = 256, *, use_cache: bool = True) -> list[str]:
    """Return a list of hosts on local IPv4 networks.

    ``max_hosts_per_network`` limits the number of addresses returned per
    network. Larger networks are truncated by increasing the prefix length so
    no more than the requested number of hosts are scanned.
    """

    global _LOCAL_HOST_CACHE, _LOCAL_HOST_CACHE_TS
    if (
        use_cache
        and _LOCAL_HOST_CACHE is not None
        and _LOCAL_HOST_CACHE_TTL > 0
        and time.time() - _LOCAL_HOST_CACHE_TS < _LOCAL_HOST_CACHE_TTL
    ):
        return _LOCAL_HOST_CACHE

    hosts: list[str] = []
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family not in (socket.AF_INET, socket.AF_INET6) or not addr.netmask:
                continue
            try:
                if addr.family == socket.AF_INET6:
                    if ':' in str(addr.netmask):
                        prefixlen = bin(int(ipaddress.IPv6Address(addr.netmask))).count('1')
                    else:
                        prefixlen = int(addr.netmask)
                    network = ipaddress.ip_network(
                        f"{addr.address}/{prefixlen}", strict=False
                    )
                else:
                    network = ipaddress.ip_network(
                        f"{addr.address}/{addr.netmask}", strict=False
                    )
            except Exception:
                continue

            if max_hosts_per_network and network.num_addresses - 1 > max_hosts_per_network:
                import math

                needed_prefix = network.max_prefixlen - math.ceil(
                    math.log2(max_hosts_per_network + 1)
                )
                prefix = max(network.prefixlen, needed_prefix)
                network = ipaddress.ip_network(
                    f"{addr.address}/{prefix}", strict=False
                )

            count = 0
            for ip in network.hosts():
                ip_str = str(ip)
                if ip_str != addr.address:
                    hosts.append(ip_str)
                    count += 1
                    if max_hosts_per_network and count >= max_hosts_per_network:
                        break

    hosts = sorted(set(hosts))
    if use_cache and _LOCAL_HOST_CACHE_TTL > 0:
        _LOCAL_HOST_CACHE = hosts
        _LOCAL_HOST_CACHE_TS = time.time()
    return hosts


async def async_detect_local_hosts(
    max_hosts_per_network: int = 256,
    progress: Callable[[float | None], None] | None = None,
    *,
    concurrency: int = 100,
    timeout: float = 1.0,
    use_cache: bool = True,
    return_ttl: bool = False,
    return_latency: bool = False,
    cancel_event: Any | None = None,
) -> list[str] | Dict[str, object]:
    """Return active local hosts with optional TTL/latency details."""

    hosts = detect_local_hosts(max_hosts_per_network, use_cache=use_cache)
    if not hosts:
        if progress is not None:
            progress(None)
        return {} if (return_ttl or return_latency) else []

    return await async_filter_active_hosts(
        hosts,
        progress,
        concurrency=concurrency,
        timeout=timeout,
        return_ttl=return_ttl,
        return_latency=return_latency,
        cancel_event=cancel_event,
    )


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


async def _async_ping_host(
    host: str,
    timeout: float = 1.0,
    *,
    return_ttl: bool = False,
    return_latency: bool = False,
) -> bool | tuple[bool, int | None] | tuple[bool, int | None, float]:
    """Asynchronously ping ``host`` and optionally return the TTL and latency."""

    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout)), host]
    try:
        start_ts = time.perf_counter() if return_latency else 0.0
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE if return_ttl else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout + 1)
        ok = proc.returncode == 0
        latency_val = time.perf_counter() - start_ts if return_latency else None
        ttl_val = None
        if return_ttl and out:
            ttl_val = _extract_ttl_from_ping(out.decode(errors="ignore"))
        if return_ttl and return_latency:
            return ok, ttl_val, latency_val
        if return_ttl:
            return ok, ttl_val
        if return_latency:
            return ok, latency_val
        return ok
    except Exception:
        if return_ttl and return_latency:
            return False, None, None
        if return_ttl:
            return False, None
        if return_latency:
            return False, None
        return False


async def async_filter_active_hosts(
    hosts: Iterable[str],
    progress: Callable[[float | None], None] | None = None,
    *,
    concurrency: int = 100,
    timeout: float = 1.0,
    return_ttl: bool = False,
    return_latency: bool = False,
    cancel_event: Any | None = None,
) -> list[str] | Dict[str, object]:
    """Return active hosts with optional TTL/latency details."""

    host_list = list(hosts)
    active_list: list[str] = []
    active_map: Dict[str, object] = {}
    total = len(host_list)
    completed = 0

    if _cancelled(cancel_event):
        if progress is not None:
            progress(None)
        return active_map if return_ttl else active_list

    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def run(host: str) -> None:
        nonlocal completed
        if _cancelled(cancel_event):
            return
        async with sem:
            if _cancelled(cancel_event):
                return
            res = await _async_ping_host(
                host,
                timeout,
                return_ttl=return_ttl,
                return_latency=return_latency,
            )
            if _cancelled(cancel_event):
                return
            if return_ttl or return_latency:
                ok = res[0]  # type: ignore[index]
                ttl_val = None
                lat_val = None
                if return_ttl and return_latency:
                    ttl_val = res[1]  # type: ignore[index]
                    lat_val = res[2]  # type: ignore[index]
                elif return_ttl:
                    ttl_val = res[1]  # type: ignore[index]
                elif return_latency:
                    lat_val = res[1]  # type: ignore[index]
                if ok:
                    if return_ttl and return_latency:
                        active_map[host] = (ttl_val, lat_val)
                    elif return_ttl:
                        active_map[host] = ttl_val
                    else:
                        active_map[host] = lat_val
            else:
                if res:  # type: ignore[truthy-bool]
                    active_list.append(host)
        completed += 1
        if progress is not None:
            progress(completed / total)

    tasks = [asyncio.create_task(run(h)) for h in host_list]
    await asyncio.gather(*tasks)

    if _cancelled(cancel_event):
        if progress is not None:
            progress(None)
        return active_map if return_ttl else active_list

    if progress is not None:
        progress(None)

    return active_map if (return_ttl or return_latency) else active_list


async def async_auto_scan_iter(
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
    with_mac: bool = False,
    with_hostname: bool = False,
    with_connections: bool = False,
    with_os: bool = False,
    with_ttl: bool = False,
    with_ping_latency: bool = False,
    with_vendor: bool = False,
    with_http_info: bool = False,
    with_device_type: bool = False,
    with_risk_score: bool = False,
    cancel_event: Any | None = None,
) -> AsyncIterator[tuple[str, List[int] | Dict[int, str] | Dict[int, PortInfo] | AutoScanInfo]]:
    """Yield auto scan results one host at a time.

    This works like :func:`async_auto_scan` but yields each host's result
    as soon as scanning completes. ``progress`` reports combined progress
    across host detection and scanning.
    """

    port_count = len(set(int(p) for p in ports)) if ports is not None else end - start + 1
    detect_weight = 1.0 / (port_count + 1)
    scan_weight = 1.0 - detect_weight

    if progress is not None:
        def det_prog(val: float | None) -> None:
            if val is None:
                progress(detect_weight)
            else:
                progress(val * detect_weight)
    else:
        det_prog = None

    filter_result = await async_detect_local_hosts(
        progress=det_prog,
        concurrency=ping_concurrency or concurrency,
        timeout=ping_timeout or timeout,
        return_ttl=with_os or with_ttl,
        return_latency=with_ping_latency,
        cancel_event=cancel_event,
    )
    if _cancelled(cancel_event):
        if progress is not None:
            progress(1.0)
        return
    if not filter_result:
        if progress is not None:
            progress(1.0)
        return

    host_ttls: Dict[str, int | None] | None = None
    host_lat: Dict[str, float | None] | None = None
    if with_os or with_ping_latency or with_ttl:
        if with_ping_latency and (with_os or with_ttl):
            host_ttls = {h: t for h, (t, _) in filter_result.items()}  # type: ignore[assignment]
            host_lat = {h: l for h, (_, l) in filter_result.items()}  # type: ignore[assignment]
        elif with_os or with_ttl:
            host_ttls = filter_result  # type: ignore[assignment]
        else:
            host_lat = filter_result  # type: ignore[assignment]
        hosts = list(filter_result.keys())  # type: ignore[assignment]
    else:
        hosts = filter_result  # type: ignore[assignment]

    if _cancelled(cancel_event):
        if progress is not None:
            progress(1.0)
        return
    if not hosts:
        if progress is not None:
            progress(1.0)
        return

    progress_map: Dict[str, float] = {h: 0.0 for h in hosts}

    def update_scan() -> None:
        if progress is not None:
            progress(detect_weight + sum(progress_map.values()) / len(progress_map) * scan_weight)

    async def scan_host(host: str) -> tuple[str, List[int] | Dict[int, str] | Dict[int, PortInfo] | AutoScanInfo]:
        def sub_prog(val: float | None) -> None:
            progress_map[host] = 1.0 if val is None else val
            update_scan()

        if ports is not None:
            result_ports = await async_scan_port_list(
                host,
                ports,
                sub_prog,
                concurrency=concurrency,
                cache_ttl=cache_ttl,
                family=family,
                timeout=timeout,
                with_services=with_services,
                with_banner=with_banner,
                with_latency=with_latency,
            )
        else:
            result_ports = await async_scan_ports(
                host,
                start,
                end,
                sub_prog,
                concurrency=concurrency,
                cache_ttl=cache_ttl,
                family=family,
                timeout=timeout,
                with_services=with_services,
                with_banner=with_banner,
                with_latency=with_latency,
            )

        if not (
            with_mac
            or with_hostname
            or with_connections
            or with_os
            or with_ping_latency
            or with_ttl
            or with_vendor
            or with_http_info
            or with_device_type
            or with_risk_score
        ):
            return host, result_ports

        info = AutoScanInfo(result_ports)
        if with_hostname:
            info.hostname = await async_get_hostname(host)
        if with_mac or with_vendor:
            mac_val = get_mac_address(host)
            if with_mac:
                info.mac = mac_val
            if with_vendor:
                info.vendor = get_mac_vendor(mac_val)
        if with_connections and _is_local_host(host):
            port_list = result_ports.keys() if isinstance(result_ports, dict) else result_ports
            info.connections = _get_connection_counts(port_list)
        ttl_val = host_ttls.get(host) if host_ttls else None
        if with_os:
            info.os_guess = _guess_os_from_ttl(ttl_val)
        if with_ttl:
            info.ttl = ttl_val
        if with_ping_latency:
            info.ping_latency = host_lat.get(host) if host_lat else None
        if with_http_info:
            tasks = [asyncio.create_task(async_get_http_info(host, p)) for p in (result_ports.keys() if isinstance(result_ports, dict) else result_ports)]
            for p, task in zip((result_ports.keys() if isinstance(result_ports, dict) else result_ports), tasks):
                res = await task
                if res is None:
                    continue
                if info.http_info is None:
                    info.http_info = {}
                info.http_info[p] = res
        if with_device_type:
            info.device_type = _guess_device_type(info)
        if with_risk_score:
            info.compute_risk_score()
        return host, info

    tasks = [asyncio.create_task(scan_host(h)) for h in hosts]
    for coro in asyncio.as_completed(tasks):
        if _cancelled(cancel_event):
            break
        yield await coro

    if progress is not None:
        progress(None)


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
    with_mac: bool = False,
    with_hostname: bool = False,
    with_connections: bool = False,
    with_os: bool = False,
    with_ttl: bool = False,
    with_ping_latency: bool = False,
    with_vendor: bool = False,
    with_http_info: bool = False,
    with_device_type: bool = False,
    with_risk_score: bool = False,
    cancel_event: Any | None = None,
) -> Dict[str, List[int]] | Dict[str, Dict[int, str]] | Dict[str, Dict[int, PortInfo]]:
    """Automatically scan detected hosts on local networks.

    ``ports`` overrides ``start``/``end`` and allows scanning an arbitrary
    list of ports. ``with_services`` adds service names for each open port.
    When ``with_banner`` is true, a short banner string is captured from each
    service and both the banner and service name are returned.
    ``ping_concurrency`` and ``ping_timeout`` override the values used when
    pinging hosts during discovery. ``with_os`` adds a best-effort OS guess
    derived from ping TTL values. ``with_ttl`` records the raw TTL for each host
    and ``with_ping_latency`` records the round-trip time when ``True``.
    ``with_vendor`` attempts to identify the
    network adapter vendor using a small built-in prefix table when MAC
    addresses are collected. ``with_http_info`` performs a simple HTTP request
    for open web ports (80/443) and captures server and title information.
    ``with_device_type`` adds a simple heuristic classification such as
    "Router" or "Printer" based on vendor and open ports. ``with_risk_score``
    calculates a basic risk value for each host using open ports and other
    gathered metadata.
    """

    results: Dict[str, List[int] | Dict[int, str] | Dict[int, PortInfo] | AutoScanInfo] = {}
    async for host, info in async_auto_scan_iter(
        start,
        end,
        progress,
        concurrency,
        ports=ports,
        cache_ttl=cache_ttl,
        family=family,
        timeout=timeout,
        ping_concurrency=ping_concurrency,
        ping_timeout=ping_timeout,
        with_services=with_services,
        with_banner=with_banner,
        with_latency=with_latency,
        with_mac=with_mac,
        with_hostname=with_hostname,
        with_connections=with_connections,
        with_os=with_os,
        with_ttl=with_ttl,
        with_ping_latency=with_ping_latency,
        with_vendor=with_vendor,
        with_http_info=with_http_info,
        with_device_type=with_device_type,
        with_risk_score=with_risk_score,
        cancel_event=cancel_event,
    ):
        results[host] = info

    return results


async def async_scan_hosts_detailed(
    hosts: Iterable[str],
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
    *,
    ports: Iterable[int] | None = None,
    cache_ttl: float = 60.0,
    family: int | None = None,
    timeout: float = 0.5,
    ping: bool = False,
    ping_concurrency: int | None = None,
    ping_timeout: float | None = None,
    with_services: bool = False,
    with_banner: bool = False,
    with_latency: bool = False,
    with_mac: bool = False,
    with_hostname: bool = False,
    with_connections: bool = False,
    with_os: bool = False,
    with_ttl: bool = False,
    with_ping_latency: bool = False,
    with_vendor: bool = False,
    with_http_info: bool = False,
    with_device_type: bool = False,
    with_risk_score: bool = False,
    cancel_event: Any | None = None,
) -> Dict[str, AutoScanInfo]:
    """Scan ``hosts`` with optional metadata collection.

    ``ping`` filters inactive hosts before scanning and controls whether TTL
    and latency are measured. Remaining options mirror :func:`async_auto_scan`.
    """

    host_list = list(dict.fromkeys(hosts))

    port_count = len(set(int(p) for p in ports)) if ports is not None else end - start + 1
    need_ping = ping or with_os or with_ttl or with_ping_latency
    detect_weight = (1.0 / (port_count + 1)) if need_ping else 0.0
    scan_weight = 1.0 - detect_weight

    if not host_list:
        if progress is not None:
            progress(1.0)
        return {}

    if progress is not None:
        def det_prog(val: float | None) -> None:
            if val is None:
                progress(detect_weight)
            else:
                progress(val * detect_weight)
    else:
        det_prog = None

    host_ttls: Dict[str, int | None] | None = None
    host_lat: Dict[str, float | None] | None = None
    if need_ping:
        res = await async_filter_active_hosts(
            host_list,
            det_prog,
            concurrency=ping_concurrency or concurrency,
            timeout=ping_timeout or timeout,
            return_ttl=with_os or with_ttl,
            return_latency=with_ping_latency,
            cancel_event=cancel_event,
        )
        if _cancelled(cancel_event):
            if progress is not None:
                progress(None)
            return {}
        if ping:
            host_list = [h for h in host_list if h in res]
        if with_os or with_ttl or with_ping_latency:
            if with_ping_latency and (with_os or with_ttl):
                host_ttls = {h: t for h, (t, _) in res.items()}  # type: ignore[assignment]
                host_lat = {h: l for h, (_, l) in res.items()}  # type: ignore[assignment]
            elif with_os or with_ttl:
                host_ttls = res  # type: ignore[assignment]
            else:
                host_lat = res  # type: ignore[assignment]

    if not host_list:
        if progress is not None:
            progress(None)
        return {}

    if progress is not None:
        def scan_prog(val: float | None) -> None:
            if val is None:
                progress(1.0)
            else:
                progress(detect_weight + val * scan_weight)
    else:
        scan_prog = None

    if ports is not None:
        results = await async_scan_targets_list(
            host_list,
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
    else:
        results = await async_scan_targets(
            host_list,
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

    if _cancelled(cancel_event):
        if progress is not None:
            progress(None)
        return {}

    detailed: Dict[str, AutoScanInfo] = {}
    hostname_map: Dict[str, str | None] | None = None
    if with_hostname:
        tasks = {
            h: asyncio.create_task(async_get_hostname(h)) for h in results
        }
        hostname_map = {}
        for h, t in tasks.items():
            hostname_map[h] = await t

    for host, ports_open in results.items():
        if _cancelled(cancel_event):
            break
        info = AutoScanInfo(ports_open)
        if with_hostname and hostname_map is not None:
            info.hostname = hostname_map.get(host)
        if with_mac or with_vendor:
            mac_val = get_mac_address(host)
            if with_mac:
                info.mac = mac_val
            if with_vendor:
                info.vendor = get_mac_vendor(mac_val)
        if with_connections and _is_local_host(host):
            port_list = ports_open.keys() if isinstance(ports_open, dict) else ports_open
            info.connections = _get_connection_counts(port_list)
        ttl_val = host_ttls.get(host) if host_ttls else None
        if with_os:
            info.os_guess = _guess_os_from_ttl(ttl_val)
        if with_ttl:
            info.ttl = ttl_val
        if with_ping_latency:
            info.ping_latency = host_lat.get(host) if host_lat else None
        detailed[host] = info

    if with_http_info and not _cancelled(cancel_event):
        tasks: list[tuple[str, int, asyncio.Task[HTTPInfo | None]]] = []
        for host, info in detailed.items():
            ports_iter = info.ports.keys() if isinstance(info.ports, dict) else info.ports
            for port in ports_iter:
                if _cancelled(cancel_event):
                    break
                task = asyncio.create_task(async_get_http_info(host, port))
                tasks.append((host, port, task))

        for host, port, task in tasks:
            if _cancelled(cancel_event):
                break
            res = await task
            if res is None:
                continue
            info = detailed[host]
            if info.http_info is None:
                info.http_info = {}
            info.http_info[port] = res

    if with_device_type:
        for host, info in detailed.items():
            if _cancelled(cancel_event):
                break
            info.device_type = _guess_device_type(info)

    if with_risk_score:
        for info in detailed.values():
            info.compute_risk_score()

    return detailed


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
    passed to :func:`async_scan_ports`. When ``progress`` is provided it receives
    updates aggregated across all hosts so the reported value steadily climbs
    from 0 to 1 as individual host scans complete.
    """

    host_list = list(hosts)
    results: Dict[str, List[int]] | Dict[str, Dict[int, str]] | Dict[str, Dict[int, PortInfo]] = {}
    total = len(host_list)

    progress_map: Dict[str, float] = {h: 0.0 for h in host_list}

    def update_progress() -> None:
        if progress is not None:
            progress(sum(progress_map.values()) / total)

    async def run(host: str) -> None:
        def sub_prog(val: float | None) -> None:
            progress_map[host] = 1.0 if val is None else val
            update_progress()

        results[host] = await async_scan_ports(
            host,
            start,
            end,
            sub_prog,
            concurrency=concurrency,
            cache_ttl=cache_ttl,
            family=family,
            timeout=timeout,
            with_services=with_services,
            with_banner=with_banner,
            with_latency=with_latency,
        )

    await asyncio.gather(*(run(h) for h in host_list))

    if progress is not None:
        progress(None)

    return results


def auto_scan_info_to_dict(info: AutoScanInfo) -> Dict[str, Any]:
    """Return ``info`` serialized to a JSON-serializable dict."""

    if isinstance(info.ports, dict):
        ports: Dict[str, Any] = {
            str(p): {
                "service": pi.service,
                **({"banner": pi.banner} if pi.banner is not None else {}),
                **(
                    {"latency": pi.latency}
                    if pi.latency is not None
                    else {}
                ),
            }
            for p, pi in info.ports.items()
        }
    else:
        ports = [int(p) for p in info.ports]

    result: Dict[str, Any] = {"ports": ports}
    if info.hostname is not None:
        result["hostname"] = info.hostname
    if info.mac is not None:
        result["mac"] = info.mac
    if info.vendor is not None:
        result["vendor"] = info.vendor
    if info.connections is not None:
        result["connections"] = info.connections
    if info.os_guess is not None:
        result["os"] = info.os_guess
    if info.ping_latency is not None:
        result["ping_latency"] = info.ping_latency
    if info.ttl is not None:
        result["ttl"] = info.ttl
    if info.http_info is not None:
        result["http"] = {
            str(p): {
                k: v
                for k, v in {
                    "server": h.server,
                    "title": h.title,
                }.items()
                if v is not None
            }
            for p, h in info.http_info.items()
            if h is not None
        }
    if info.device_type is not None:
        result["device"] = info.device_type
    if info.risk_score is not None:
        result["risk"] = info.risk_score
    return result


def auto_scan_results_to_dict(results: Dict[str, AutoScanInfo]) -> Dict[str, Any]:
    """Return a JSON-serializable mapping for ``results``."""

    return {host: auto_scan_info_to_dict(info) for host, info in results.items()}


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
    """Asynchronously scan ``ports`` on multiple ``hosts``.

    When ``progress`` is supplied it reflects combined progress across all hosts
    so values advance smoothly from 0 to 1 until all scans finish.
    """

    host_list = list(hosts)
    results: Dict[str, List[int]] | Dict[str, Dict[int, str]] | Dict[str, Dict[int, PortInfo]] = {}
    total = len(host_list)

    progress_map: Dict[str, float] = {h: 0.0 for h in host_list}

    def update_progress() -> None:
        if progress is not None:
            progress(sum(progress_map.values()) / total)

    async def run(host: str) -> None:
        def sub_prog(val: float | None) -> None:
            progress_map[host] = 1.0 if val is None else val
            update_progress()

        results[host] = await async_scan_port_list(
            host,
            ports,
            sub_prog,
            concurrency=concurrency,
            cache_ttl=cache_ttl,
            family=family,
            timeout=timeout,
            with_services=with_services,
            with_banner=with_banner,
            with_latency=with_latency,
        )

    await asyncio.gather(*(run(h) for h in host_list))

    if progress is not None:
        progress(None)

    return results

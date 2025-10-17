import socket
import socketserver
import threading
import asyncio
import importlib
import subprocess
import shutil
import asyncio
import importlib
import io
import json
import shutil
import socket
import socketserver
import sys
import threading
import time
from collections import namedtuple
from pathlib import Path
from typing import Any, Dict, cast

import psutil
import pytest

from coolbox.cli.commands import network_scan as network_cli

import coolbox.utils.network as network


Snicaddr = namedtuple(
    "Snicaddr", ["family", "address", "netmask", "broadcast", "ptp"]
)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(1)


class _BannerHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"banner")
        self.request.recv(1)


class _IPv6Server(socketserver.TCPServer):
    address_family = socket.AF_INET6


def test_scan_ports():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_ports("localhost", port, port)
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]

    assert network.scan_ports("localhost", port + 1, port + 1) == []


def test_scan_ports_cache(monkeypatch):
    calls: list[float | None] = []

    def progress(value: float | None) -> None:
        calls.append(value)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            network.scan_ports("localhost", port, port, progress)
            calls.clear()
            network.scan_ports("localhost", port, port, progress)
        finally:
            server.shutdown()
            thread.join()

    assert calls == [None]


def test_scan_ports_disk_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setenv("NETWORK_CACHE_FILE", str(cache_file))
    importlib.reload(network)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            network.scan_ports("localhost", port, port)
            # Reload module to drop in-memory cache while keeping the file
            importlib.reload(network)
            calls = []
            network.scan_ports("localhost", port, port, calls.append)
        finally:
            server.shutdown()
            thread.join()

    assert cache_file.exists()
    assert calls == [None]


def test_scan_ports_with_services():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_ports("localhost", port, port, with_services=True)
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result, dict)
        assert list(result.keys()) == [port]
        service = result[port]
        assert isinstance(service, str)


def test_scan_ports_with_banner():
    with socketserver.TCPServer(("localhost", 0), _BannerHandler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_ports("localhost", port, port, with_banner=True)
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result, dict)
        info = result[port]
        assert isinstance(info, network.PortInfo)
    assert info.banner == "banner"


def test_scan_ports_with_latency():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                Dict[int, network.PortInfo],
                network.scan_ports("localhost", port, port, with_latency=True),
            )
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result, dict)
        info = result[port]
        assert isinstance(info, network.PortInfo)
        assert info.latency is not None


def test_scan_port_list():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_port_list("localhost", [port])
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_async_scan_port_list():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(network.async_scan_port_list("localhost", [port]))
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_scan_top_ports(monkeypatch):
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(network, "TOP_PORTS", [port])
        try:
            result = network.scan_top_ports("localhost", top=1)
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_async_scan_top_ports(monkeypatch):
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(network, "TOP_PORTS", [port])
        try:
            result = asyncio.run(network.async_scan_top_ports("localhost", top=1))
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_async_scan_ports():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(network.async_scan_ports("localhost", port, port))
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]

    assert asyncio.run(network.async_scan_ports("localhost", port + 1, port + 1)) == []


def test_async_scan_ports_cache():
    calls: list[float | None] = []

    def progress(value: float | None) -> None:
        calls.append(value)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            asyncio.run(network.async_scan_ports("localhost", port, port, progress))
            calls.clear()
            asyncio.run(network.async_scan_ports("localhost", port, port, progress))
        finally:
            server.shutdown()
            thread.join()

    assert calls == [None]


def test_async_scan_ports_custom_concurrency():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
                network.async_scan_ports("localhost", port, port, concurrency=1)
            )
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_async_scan_targets_host_concurrency(monkeypatch):
    active = 0
    max_active = 0

    async def fake_scan_ports(host, start, end, progress=None, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return [start]

    monkeypatch.setattr(network, "async_scan_ports", fake_scan_ports)

    result = asyncio.run(
        network.async_scan_targets(["h1", "h2", "h3"], 1, 1, host_concurrency=2)
    )

    assert set(result.keys()) == {"h1", "h2", "h3"}
    assert max_active <= 2


def test_async_scan_targets_list_host_concurrency(monkeypatch):
    active = 0
    max_active = 0

    async def fake_scan_port_list(host, ports, progress=None, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return ports

    monkeypatch.setattr(network, "async_scan_port_list", fake_scan_port_list)

    result = asyncio.run(
        network.async_scan_targets_list(["h1", "h2", "h3"], [1], host_concurrency=2)
    )

    assert set(result.keys()) == {"h1", "h2", "h3"}
    assert max_active <= 2


def test_async_scan_ports_with_services():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
                network.async_scan_ports("localhost", port, port, with_services=True)
            )
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result, dict)
        assert list(result.keys()) == [port]
        assert isinstance(result[port], str)


def test_async_scan_ports_with_banner():
    with socketserver.TCPServer(("localhost", 0), _BannerHandler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
                network.async_scan_ports("localhost", port, port, with_banner=True)
            )
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result, dict)
        info = result[port]
        assert isinstance(info, network.PortInfo)
    assert info.banner == "banner"


def test_async_scan_ports_with_latency():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                Dict[int, network.PortInfo],
                asyncio.run(
                    network.async_scan_ports(
                        "localhost", port, port, with_latency=True
                    )
                ),
            )
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result, dict)
        info = result[port]
        assert isinstance(info, network.PortInfo)
        assert info.latency is not None


def test_scan_cache_ttl_expires(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setenv("NETWORK_CACHE_FILE", str(cache_file))
    importlib.reload(network)

    calls: list[float | None] = []
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            network.scan_ports("localhost", port, port, calls.append, cache_ttl=0.1)
            time.sleep(0.2)
            calls.clear()
            network.scan_ports("localhost", port, port, calls.append)
        finally:
            server.shutdown()
            thread.join()

    assert len(calls) > 1 and calls[-1] is None


def test_clear_scan_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setenv("NETWORK_CACHE_FILE", str(cache_file))
    importlib.reload(network)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            network.scan_ports("localhost", port, port)
        finally:
            server.shutdown()
            thread.join()

    assert cache_file.exists()
    network.clear_scan_cache()
    assert not cache_file.exists()
    assert len(network.PORT_CACHE) == 0
    assert not network._HOST_CACHE


def test_scan_ports_ipv6():
    with _IPv6Server(("::1", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_ports("::1", port, port)
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_async_scan_ports_ipv6():
    with _IPv6Server(("::1", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(network.async_scan_ports("::1", port, port))
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_scan_targets():
    with socketserver.TCPServer(
        ("localhost", 0), _Handler
    ) as s1, socketserver.TCPServer(("localhost", 0), _Handler) as s2:
        p1 = s1.server_address[1]
        t1 = threading.Thread(target=s1.serve_forever, daemon=True)
        t2 = threading.Thread(target=s2.serve_forever, daemon=True)
        t1.start()
        t2.start()
        try:
            result = network.scan_targets(["localhost", "127.0.0.1"], p1, p1)
        finally:
            s1.shutdown()
            s2.shutdown()
            t1.join()
            t2.join()
        assert result["localhost"] == [p1]


def test_async_scan_targets():
    with socketserver.TCPServer(
        ("localhost", 0), _Handler
    ) as s1, socketserver.TCPServer(("localhost", 0), _Handler) as s2:
        p2 = s2.server_address[1]
        t1 = threading.Thread(target=s1.serve_forever, daemon=True)
        t2 = threading.Thread(target=s2.serve_forever, daemon=True)
        t1.start()
        t2.start()
        try:
            result = asyncio.run(
                network.async_scan_targets(["localhost", "127.0.0.1"], p2, p2)
            )
        finally:
            s1.shutdown()
            s2.shutdown()
            t1.join()
            t2.join()
        assert result["localhost"] == [p2]


def test_async_scan_targets_progress(monkeypatch):
    updates: list[float | None] = []

    async def fake_scan_ports(host: str, start: int, end: int, progress=None, **kw):
        if progress:
            progress(0.5)
            progress(None)
        return [start]

    monkeypatch.setattr(network, "async_scan_ports", fake_scan_ports)

    result = asyncio.run(network.async_scan_targets(["h1", "h2"], 1, 1, updates.append))

    assert result == {"h1": [1], "h2": [1]}
    assert updates[-2:] == [1.0, None]


def test_async_scan_hosts_detailed_no_ping_progress(monkeypatch):
    """Progress should still reach 1.0 when pinging isn't required."""
    updates: list[float | None] = []

    async def fake_scan_targets(hosts, start, end, progress=None, **kwargs):
        if progress:
            progress(0.5)
            progress(None)
        return {h: [start] for h in hosts}

    monkeypatch.setattr(network, "async_scan_targets", fake_scan_targets)

    result = asyncio.run(
        network.async_scan_hosts_detailed(["h1", "h2"], 1, 1, updates.append)
    )

    assert set(result.keys()) == {"h1", "h2"}
    assert all(isinstance(info, network.AutoScanInfo) for info in result.values())
    assert updates[-1] == 1.0


def test_family_override():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_ports(
                "localhost",
                port,
                port,
                family=socket.AF_INET,
            )
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_custom_timeout():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_ports("localhost", port, port, timeout=0.1)
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
                network.async_scan_ports("localhost", port, port, timeout=0.1)
            )
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]

    with _IPv6Server(("::1", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
                network.async_scan_ports(
                    "::1",
                    port,
                    port,
                    family=socket.AF_INET6,
                )
            )
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]


def test_network_scan_cli(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert f"localhost: {port}" in result.stdout


def test_network_scan_cli_services(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                    "--services",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert f"localhost: {port}(" in result.stdout


def test_network_scan_cli_banner(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _BannerHandler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                    "--banner",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "banner" in result.stdout


def test_network_scan_cli_latency(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                    "--latency",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "ms" in result.stdout


def test_network_scan_cli_top(monkeypatch):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(network, "TOP_PORTS", [port])
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "0",  # dummy port argument
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                    "--top",
                    "1",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "localhost:" in result.stdout


def test_network_scan_cli_list(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    f"{port},{port + 1}",
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert f"localhost: {port}" in result.stdout


def test_network_scan_cli_host_range(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "127.0.0.1-3",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "127.0.0.1:" in result.stdout


def test_network_scan_cli_ping(monkeypatch):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def fake_filter(hosts, progress=None, *, concurrency=0, timeout=0):
            assert concurrency == 5
            assert timeout == 0.2
            return [h for h in hosts if h == "localhost"]

        monkeypatch.setattr(network, "async_filter_active_hosts", fake_filter)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "other",
                    "--ping",
                    "--ping-timeout",
                    "0.2",
                    "--ping-concurrency",
                    "5",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "other" not in result.stdout


def test_network_scan_cli_ping_details(monkeypatch):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def fake_filter(
            hosts,
            progress=None,
            *,
            concurrency=0,
            timeout=0,
            return_ttl=False,
            return_latency=False,
        ):
            assert return_ttl
            assert return_latency
            return {h: (64, 0.01) for h in hosts if h == "localhost"}

        monkeypatch.setattr(network, "async_filter_active_hosts", fake_filter)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "other",
                    "--ping",
                    "--ping-timeout",
                    "0.2",
                    "--ping-concurrency",
                    "5",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                    "--os",
                    "--ping-latency",
                    "--ping-ttl",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "{Linux}" in result.stdout
    assert "<TTL:64>" in result.stdout
    assert "ms]" in result.stdout


def test_network_scan_cli_auto(monkeypatch):
    script = Path("scripts/python/network_scan.py")
    monkeypatch.setattr(
        network,
        "async_detect_local_hosts",
        lambda progress=None, **kw: ["localhost"],
    )
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "--auto",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0


def test_network_scan_cli_auto_with_hosts(monkeypatch):
    script = Path("scripts/python/network_scan.py")
    monkeypatch.setattr(
        network,
        "async_detect_local_hosts",
        lambda progress=None, **kw: ["localhost"],
    )

    def fake_filter(hosts, progress=None, **kw):
        assert "localhost" in hosts and "other" in hosts
        return [h for h in hosts if h == "localhost"]

    monkeypatch.setattr(network, "async_filter_active_hosts", fake_filter)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "other",
                    "--auto",
                    "--ping",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "other" not in result.stdout


def test_network_scan_cli_auto_with_hosts_no_ping(monkeypatch):
    script = Path("scripts/python/network_scan.py")
    monkeypatch.setattr(
        network,
        "async_detect_local_hosts",
        lambda progress=None, **kw: ["localhost"],
    )

    def fake_filter(hosts, progress=None, **kw):
        assert "localhost" in hosts and "other" in hosts
        return [h for h in hosts if h == "localhost"]

    monkeypatch.setattr(network, "async_filter_active_hosts", fake_filter)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "other",
                    "--auto",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert "other" in result.stdout


def test_network_scan_cli_auto_dedupe(monkeypatch):
    script = Path("scripts/python/network_scan.py")
    monkeypatch.setattr(
        network,
        "async_detect_local_hosts",
        lambda progress=None, **kw: ["localhost"],
    )
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "--auto",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert result.stdout.count("localhost:") == 1


def test_network_scan_cli_detailed(monkeypatch):
    async def fake_scan(*args, **kwargs):
        assert kwargs["with_hostname"]
        assert kwargs["with_mac"]
        assert kwargs["with_os"]
        info = network.AutoScanInfo([80])
        info.hostname = "pc"
        info.mac = "00:11:22:33:44:55"
        info.os_guess = "Linux"
        return {"localhost": info}

    monkeypatch.setattr(network_cli, "async_scan_hosts_detailed", fake_scan)
    monkeypatch.setattr(
        sys,
        "argv",
        ["network_scan.py", "80", "localhost", "--hostname", "--mac", "--os"],
    )
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    asyncio.run(network_cli.main())

    out = captured.getvalue()
    assert "(pc)" in out
    assert "[00:11:22:33:44:55]" in out
    assert "{Linux}" in out


def test_network_scan_cli_json(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                    "--json",
                    "-",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert port in data["localhost"]["ports"]


def test_network_scan_cli_stream(tmp_path):
    script = Path("scripts/python/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(port),
                    "localhost",
                    "--timeout",
                    "0.1",
                    "--family",
                    "ipv4",
                    "--json",
                    "-",
                    "--stream",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert '"localhost"' in result.stdout


def test_network_scan_cli_host_concurrency(monkeypatch):
    async def fake_scan_hosts(*args, host_concurrency=0, **kwargs):
        assert host_concurrency == 5
        return {"localhost": network.AutoScanInfo([80])}

    monkeypatch.setattr(
        network_cli, "async_scan_hosts_detailed", fake_scan_hosts
    )
    monkeypatch.setattr(
        sys, "argv", ["network_scan.py", "80", "localhost", "--host-concurrency", "5"]
    )
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    asyncio.run(network_cli.main())
    out = captured.getvalue()
    assert "localhost" in out


def test_parse_port_range_single():
    assert network.parse_port_range("80") == (80, 80)


def test_parse_port_range_range():
    assert network.parse_port_range("20-25") == (20, 25)


def test_parse_port_range_invalid():
    with pytest.raises(ValueError):
        network.parse_port_range("70000")


def test_parse_ports_single():
    assert network.parse_ports("80") == [80]


def test_parse_ports_range():
    assert network.parse_ports("20-22") == [20, 21, 22]


def test_parse_ports_list():
    assert network.parse_ports("22,80,443") == [22, 80, 443]


def test_parse_ports_combo():
    assert network.parse_ports("22,80-82") == [22, 80, 81, 82]


def test_parse_ports_top():
    ports = network.parse_ports("top3")
    assert ports == network.TOP_PORTS[:3]


def test_parse_ports_step():
    assert network.parse_ports("20-24:2") == [20, 22, 24]


def test_parse_ports_step_invalid():
    with pytest.raises(ValueError):
        network.parse_ports("80:2")


def test_parse_ports_service_names():
    ports = network.parse_ports("ssh,http")
    assert ports == [22, 80]


def test_ports_as_range():
    assert network.ports_as_range([20, 21, 22]) == (20, 22)
    assert network.ports_as_range([22, 25]) is None


def test_parse_ports_invalid():
    with pytest.raises(ValueError):
        network.parse_ports("70000")


def test_parse_hosts_single():
    assert network.parse_hosts("localhost") == ["localhost"]


def test_parse_hosts_list():
    assert network.parse_hosts("1.1.1.1,2.2.2.2") == ["1.1.1.1", "2.2.2.2"]


def test_parse_hosts_cidr():
    assert network.parse_hosts("192.168.0.0/30") == ["192.168.0.1", "192.168.0.2"]


def test_parse_hosts_range():
    assert network.parse_hosts("10.0.0.1-3") == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


def test_parse_hosts_wildcard():
    hosts = network.parse_hosts("192.168.1.*")
    assert "192.168.1.0" not in hosts  # network address skipped
    assert "192.168.1.1" in hosts


def test_extract_ttl_from_ping():
    samples = [
        ("Reply from 1.1.1.1: bytes=32 time=1ms TTL=64", 64),
        ("64 bytes from 1.1.1.1: icmp_seq=1 ttl=128 time=0.1 ms", 128),
        ("icmp_seq=1 ttl:255 time=0.5 ms", 255),
        ("64 bytes from ::1: icmp_seq=1 hlim=200", 200),
    ]
    for text, ttl in samples:
        assert network._extract_ttl_from_ping(text) == ttl
    assert network._extract_ttl_from_ping("no ttl here") is None


def test_detect_local_hosts(monkeypatch):
    snic = Snicaddr

    def fake_if_addrs() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET,
                    address="192.168.1.10",
                    netmask="255.255.255.0",
                    broadcast=None,
                    ptp=None,
                )
            ]
        }

    monkeypatch.setattr(psutil, "net_if_addrs", fake_if_addrs)
    hosts = network.detect_local_hosts(max_hosts_per_network=6, use_cache=False)
    assert "192.168.1.10" not in hosts
    assert len(hosts) == 5


def test_detect_local_hosts_ipv6(monkeypatch):
    snic = Snicaddr

    def fake_if_addrs() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET6,
                    address="2001:db8::1",
                    netmask="ffff:ffff:ffff:ffff::",
                    broadcast=None,
                    ptp=None,
                )
            ]
        }

    monkeypatch.setattr(psutil, "net_if_addrs", fake_if_addrs)
    hosts = network.detect_local_hosts(max_hosts_per_network=2, use_cache=False)
    assert "2001:db8::1" not in hosts
    assert hosts == ["2001:db8::2", "2001:db8::3"]


def test_detect_local_hosts_skip_link_local(monkeypatch):
    snic = Snicaddr

    def fake_if_addrs() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET,
                    address="169.254.1.5",
                    netmask="255.255.0.0",
                    broadcast=None,
                    ptp=None,
                )
            ],
            "eth1": [
                snic(
                    family=socket.AF_INET6,
                    address="fe80::1",
                    netmask="ffff:ffff:ffff:ffff::",
                    broadcast=None,
                    ptp=None,
                )
            ],
        }

    monkeypatch.setattr(psutil, "net_if_addrs", fake_if_addrs)
    hosts = network.detect_local_hosts(use_cache=False)
    assert hosts == []


def test_detect_local_hosts_include_arp(monkeypatch):
    snic = Snicaddr

    def fake_if_addrs() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET,
                    address="192.168.1.10",
                    netmask="255.255.255.0",
                    broadcast=None,
                    ptp=None,
                )
            ]
        }

    monkeypatch.setattr(psutil, "net_if_addrs", fake_if_addrs)
    monkeypatch.setattr(network, "_ARP_CACHE_DATA", {"192.168.1.5": "aa:bb:cc:dd:ee:ff"})
    monkeypatch.setattr(network, "_refresh_arp_cache", lambda force=False: None)

    hosts = network.detect_local_hosts(use_cache=False, include_arp=True)
    assert "192.168.1.5" in hosts


def test_detect_local_hosts_cache_ttl(tmp_path, monkeypatch):
    snic = Snicaddr

    cache_file = tmp_path / "hosts.json"
    monkeypatch.setenv("LOCAL_HOST_CACHE_FILE", str(cache_file))
    import importlib
    importlib.reload(network)

    def addrs_first() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET,
                    address="192.168.1.10",
                    netmask="255.255.255.0",
                    broadcast=None,
                    ptp=None,
                )
            ]
        }

    def addrs_second() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET,
                    address="10.0.0.5",
                    netmask="255.255.255.0",
                    broadcast=None,
                    ptp=None,
                )
            ]
        }

    monkeypatch.setattr(psutil, "net_if_addrs", addrs_first)
    hosts1 = network.detect_local_hosts(use_cache=True)

    monkeypatch.setenv("LOCAL_HOST_CACHE_TTL", "0")
    import importlib

    importlib.reload(network)
    try:
        monkeypatch.setattr(psutil, "net_if_addrs", addrs_second)
        hosts2 = network.detect_local_hosts(use_cache=True)
        assert hosts1 != hosts2
    finally:
        monkeypatch.delenv("LOCAL_HOST_CACHE_TTL", raising=False)
        importlib.reload(network)


def test_clear_local_host_cache(tmp_path, monkeypatch):
    snic = Snicaddr

    cache_file = tmp_path / "hosts.json"
    monkeypatch.setenv("LOCAL_HOST_CACHE_FILE", str(cache_file))
    import importlib
    importlib.reload(network)

    def addrs1() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET,
                    address="192.168.1.10",
                    netmask="255.255.255.0",
                    broadcast=None,
                    ptp=None,
                )
            ]
        }

    def addrs2() -> dict[str, list]:
        return {
            "eth0": [
                snic(
                    family=socket.AF_INET,
                    address="10.1.1.5",
                    netmask="255.255.255.0",
                    broadcast=None,
                    ptp=None,
                )
            ]
        }

    monkeypatch.setattr(psutil, "net_if_addrs", addrs1)
    hosts1 = network.detect_local_hosts(use_cache=True)

    monkeypatch.setattr(psutil, "net_if_addrs", addrs2)
    hosts2 = network.detect_local_hosts(use_cache=True)
    assert hosts2 == hosts1
    assert cache_file.exists()

    network.clear_local_host_cache()
    assert not cache_file.exists()
    hosts3 = network.detect_local_hosts(use_cache=True)
    assert hosts3 != hosts1


def test_refresh_arp_cache_fallback(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/sbin/ip" if name == "ip" else None)

    def fake_run(cmd, capture=False, **kwargs):
        if cmd[0] == "arp":
            return None
        assert cmd == ["ip", "neighbor"]
        return "192.168.1.10 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n"

    monkeypatch.setattr(network, "_run", fake_run)
    network.clear_arp_cache()
    hosts = network.detect_arp_hosts()
    assert hosts == ["192.168.1.10"]


def test_arp_cache_file(tmp_path, monkeypatch):
    cache_file = tmp_path / "arp.json"
    monkeypatch.setenv("ARP_CACHE_FILE", str(cache_file))
    import importlib
    importlib.reload(network)

    calls = 0

    def fake_run(cmd, capture=False, **kwargs):
        nonlocal calls
        calls += 1
        return "192.168.1.10 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n"

    monkeypatch.setattr(network, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/sbin/arp" if name == "arp" else None)

    network.clear_arp_cache()
    hosts1 = network.detect_arp_hosts()
    assert hosts1 == ["192.168.1.10"]
    assert cache_file.exists()

    hosts2 = network.detect_arp_hosts()
    assert hosts2 == hosts1
    assert calls == 1

    network.clear_arp_cache()
    assert not cache_file.exists()


def test_async_auto_scan(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost", "other"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return (host == "localhost", 64, 0.01)
        if return_ttl:
            return (host == "localhost", 64)
        if return_latency:
            return (host == "localhost", 0.01)
        return host == "localhost"

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, list[int]],
                asyncio.run(network.async_auto_scan(port, port, ports=[port])),
            )
        finally:
            server.shutdown()
            thread.join()

    assert result["localhost"] == [port]


def test_async_auto_scan_with_services(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, dict[int, str]],
                asyncio.run(
                    network.async_auto_scan(
                        port, port, ports=[port], with_services=True
                    )
                ),
            )
        finally:
            server.shutdown()
            thread.join()

    assert isinstance(result["localhost"], dict)
    assert list(result["localhost"].keys()) == [port]


def test_async_auto_scan_with_banner(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    with socketserver.TCPServer(("localhost", 0), _BannerHandler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, dict[int, network.PortInfo]],
                asyncio.run(
                    network.async_auto_scan(
                        port, port, ports=[port], with_banner=True
                    )
                ),
            )
        finally:
            server.shutdown()
            thread.join()

    assert isinstance(result["localhost"], dict)
    info = result["localhost"][port]
    assert isinstance(info, network.PortInfo)
    assert info.banner == "banner"


def test_async_auto_scan_detailed(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    async def fake_mac(h):
        return "00:0c:29:aa:bb:cc"

    monkeypatch.setattr(network, "async_get_mac_address", fake_mac)
    monkeypatch.setattr(
        network, "_get_connection_counts", lambda ports: {p: 2 for p in ports}
    )

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, network.AutoScanInfo],
                asyncio.run(
                    network.async_auto_scan(
                        port,
                        port,
                        ports=[port],
                        with_mac=True,
                        with_hostname=True,
                        with_connections=True,
                        with_os=True,
                        with_vendor=True,
                        with_device_type=True,
                    )
                ),
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.mac == "00:0c:29:aa:bb:cc"
    assert info.connections is not None
    assert info.connections[port] == 2
    assert info.os_guess == "Linux"
    assert info.vendor == "VMware"
    assert info.device_type == "Virtual Machine"


def test_async_filter_active_hosts(monkeypatch):
    calls: list[str] = []

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        calls.append(host)
        if return_ttl:
            return (host == "1.1.1.1", 64 if host == "1.1.1.1" else None)
        return host == "1.1.1.1"

    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    result = asyncio.run(
        network.async_filter_active_hosts(["1.1.1.1", "2.2.2.2"], concurrency=2)
    )

    assert result == ["1.1.1.1"]
    assert sorted(calls) == ["1.1.1.1", "2.2.2.2"]


def test_async_filter_active_hosts_ttl(monkeypatch):
    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if host == "1.1.1.1":
            if return_ttl and return_latency:
                return True, 64, 0.01
            if return_ttl:
                return True, 64
            if return_latency:
                return True, 0.01
            return True
        if return_ttl and return_latency:
            return False, None, None
        if return_ttl:
            return False, None
        if return_latency:
            return False, None
        return False

    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    result = asyncio.run(
        network.async_filter_active_hosts(
            ["1.1.1.1", "2.2.2.2"], concurrency=2, return_ttl=True
        )
    )

    assert result == {"1.1.1.1": 64}


def test_async_detect_local_hosts(monkeypatch):
    def fake_detect(
        max_hosts_per_network: int = 256,
        *,
        use_cache: bool = True,
        include_arp: bool = True,
    ):
        return ["1.1.1.1", "2.2.2.2"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        return host == "1.1.1.1"

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    result = asyncio.run(network.async_detect_local_hosts(concurrency=2))

    assert result == ["1.1.1.1"]


def test_async_detect_local_hosts_ttl(monkeypatch):
    def fake_detect(
        max_hosts_per_network: int = 256,
        *,
        use_cache: bool = True,
        include_arp: bool = True,
    ):
        return ["1.1.1.1", "2.2.2.2"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if host == "1.1.1.1":
            if return_ttl and return_latency:
                return True, 64, 0.01
            if return_ttl:
                return True, 64
            if return_latency:
                return True, 0.01
            return True
        if return_ttl and return_latency:
            return False, None, None
        if return_ttl:
            return False, None
        if return_latency:
            return False, None
        return False

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    result = asyncio.run(
        network.async_detect_local_hosts(concurrency=2, return_ttl=True)
    )

    assert result == {"1.1.1.1": 64}


def test_async_get_http_info():
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Server", "TestServer")
            self.end_headers()
            self.wfile.write(b"<html><title>Hello</title></html>")

    with http.server.HTTPServer(("localhost", 0), Handler) as srv:
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            info = asyncio.run(network.async_get_http_info("localhost", port))
        finally:
            srv.shutdown()
            thread.join()

    assert isinstance(info, network.HTTPInfo)
    assert info.title == "Hello"


def test_async_get_http_info_cache(tmp_path, monkeypatch):
    import http.server

    cache_file = tmp_path / "http.json"
    monkeypatch.setenv("HTTP_CACHE_FILE", str(cache_file))
    import importlib

    importlib.reload(network)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Server", "CacheServer")
            self.end_headers()
            self.wfile.write(b"<html><title>Cached</title></html>")

    with http.server.HTTPServer(("localhost", 0), Handler) as srv:
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            info1 = asyncio.run(network.async_get_http_info("localhost", port))
        finally:
            srv.shutdown()
            thread.join()

    assert info1 and info1.title == "Cached"
    assert cache_file.exists()

    async def fail_connect(*args, **kwargs):
        raise OSError

    monkeypatch.setattr(asyncio, "open_connection", fail_connect)
    info2 = asyncio.run(network.async_get_http_info("localhost", port))
    assert info2 and info2.title == "Cached"


def test_async_ping_cache(monkeypatch):
    calls = 0

    async def fake_run(cmd, capture=False, **kwargs):
        nonlocal calls
        calls += 1
        return "ttl=64", 0

    monkeypatch.setattr(network, "_run_async_ex", fake_run)

    res1 = asyncio.run(network._async_ping_host("1.1.1.1", return_ttl=True))
    res2 = asyncio.run(network._async_ping_host("1.1.1.1", return_ttl=True))

    assert res1 == (True, 64)
    assert res2 == (True, 64)
    assert calls == 1


def test_ping_host_success(monkeypatch):
    monkeypatch.setattr(network, "_run_ex", lambda cmd, **k: ("", 0))
    assert network._ping_host("1.1.1.1") is True


def test_ping_host_fail(monkeypatch):
    monkeypatch.setattr(network, "_run_ex", lambda cmd, **k: (None, 1))
    assert network._ping_host("1.1.1.1") is False


def test_async_auto_scan_http_info(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Server", "ScanServer")
            self.end_headers()
            self.wfile.write(b"<html><title>World</title></html>")

    with http.server.HTTPServer(("localhost", 0), Handler) as srv:
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, network.AutoScanInfo],
                asyncio.run(
                    network.async_auto_scan(
                        port,
                        port,
                        ports=[port],
                        with_http_info=True,
                    )
                ),
            )
        finally:
            srv.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.http_info is not None
    assert port in info.http_info
    assert info.http_info[port].title == "World"


def test_async_auto_scan_ping_latency(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, network.AutoScanInfo],
                asyncio.run(
                    network.async_auto_scan(
                        port,
                        port,
                        ports=[port],
                        with_ping_latency=True,
                    )
                ),
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.ping_latency is not None


def test_async_auto_scan_cancel(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost", "other"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    cancel = asyncio.Event()
    cancel.set()

    result = cast(
        dict[str, list[int]],
        asyncio.run(network.async_auto_scan(1, 1, cancel_event=cancel)),
    )

    assert result == {}


def test_async_filter_active_hosts_cancel(monkeypatch):
    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, None, 0.01
        if return_ttl:
            return True, None
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    cancel = asyncio.Event()
    cancel.set()

    result = asyncio.run(
        network.async_filter_active_hosts(["1.1.1.1"], cancel_event=cancel)
    )

    assert result == []


def test_guess_device_type():
    info = network.AutoScanInfo({80: network.PortInfo("http")})
    info.vendor = "Cisco"
    info.http_info = {80: network.HTTPInfo(server="Cisco Router")}

    assert network._guess_device_type(info) == "Router"


def test_estimate_risk():
    info = network.AutoScanInfo(
        {21: network.PortInfo("ftp"), 80: network.PortInfo("http")}
    )
    info.os_guess = "Windows"
    info.device_type = "Router"
    score = network._estimate_risk(info)
    assert score >= 50


def test_async_auto_scan_risk(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, network.AutoScanInfo],
                asyncio.run(
                    network.async_auto_scan(
                        port,
                        port,
                        ports=[port],
                        with_risk_score=True,
                    )
                ),
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.risk_score is not None


def test_autoscaninfo_compute_risk_score():
    info = network.AutoScanInfo([22, 80])
    score = info.compute_risk_score()
    assert info.risk_score == score
    assert 0 <= score <= 100


def test_async_auto_scan_ttl(monkeypatch):
    def fake_detect(*args, **kwargs) -> list[str]:
        return ["localhost"]

    async def fake_ping(
        host: str,
        timeout: float = 1.0,
        *,
        return_ttl: bool = False,
        return_latency: bool = False,
    ):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = cast(
                dict[str, network.AutoScanInfo],
                asyncio.run(
                    network.async_auto_scan(
                        port,
                        port,
                        ports=[port],
                        with_ttl=True,
                    )
                ),
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.ttl == 64


def test_async_scan_hosts_detailed(monkeypatch):
    async def fake_filter(*args, **kwargs):
        return {"localhost": (64, 0.01)}

    async def fake_scan(hosts, ports, *args, **kwargs):
        return {h: {80: network.PortInfo("http")} for h in hosts}

    monkeypatch.setattr(network, "async_filter_active_hosts", fake_filter)
    monkeypatch.setattr(network, "async_scan_targets_list", fake_scan)

    async def fake_mac(h):
        return "00:0c:29:aa:bb:cc"

    monkeypatch.setattr(network, "async_get_mac_address", fake_mac)
    monkeypatch.setattr(network, "get_mac_vendor", lambda m: "VMware")
    monkeypatch.setattr(
        network, "_get_connection_counts", lambda ports: {p: 1 for p in ports}
    )

    result = asyncio.run(
        network.async_scan_hosts_detailed(
            ["localhost"],
            80,
            80,
            ports=[80],
            ping=True,
            with_services=True,
            with_hostname=True,
            with_mac=True,
            with_vendor=True,
            with_connections=True,
            with_os=True,
            with_ping_latency=True,
        )
    )

    info = result["localhost"]
    assert info.os_guess == "Linux"
    assert info.ping_latency == 0.01
    assert info.mac == "00:0c:29:aa:bb:cc"
    assert info.vendor == "VMware"
    assert info.connections is not None
    assert info.connections[80] == 1


def test_async_get_hostname_cache(monkeypatch):
    calls: list[str] = []

    def fake_gethostbyaddr(host: str):
        calls.append(host)
        return ("pc", [], [host])

    monkeypatch.setattr(socket, "gethostbyaddr", fake_gethostbyaddr)

    first = asyncio.run(network.async_get_hostname("1.1.1.1", ttl=1))
    second = asyncio.run(network.async_get_hostname("1.1.1.1", ttl=1))

    assert first == "pc"
    assert second == "pc"
    assert calls == ["1.1.1.1"]


def test_async_resolve_host():
    addr, fam = asyncio.run(network._async_resolve_host("localhost"))
    assert isinstance(addr, str)
    assert fam in (socket.AF_INET, socket.AF_INET6)


def test_async_auto_scan_iter(monkeypatch):
    async def fake_detect(progress=None, **kw):
        if progress:
            progress(0.5)
            progress(None)
        return ["h1", "h2"]

    async def fake_scan(host, start, end, progress=None, **kw):
        if progress:
            progress(0.5)
            progress(None)
        return [start]

    monkeypatch.setattr(network, "async_detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "async_scan_ports", fake_scan)

    updates: list[float | None] = []

    async def run() -> list[str]:
        res = []
        async for host, ports in network.async_auto_scan_iter(1, 1, updates.append):
            res.append(host)
        return res

    hosts = asyncio.run(run())

    assert hosts == ["h1", "h2"]
    assert updates[-2:] == [1.0, None]


def test_async_scan_hosts_iter(monkeypatch):
    async def fake_scan(host, start, end, progress=None, **kw):
        if progress:
            progress(0.5)
            progress(None)
        return [start]

    monkeypatch.setattr(network, "async_scan_ports", fake_scan)

    updates: list[float | None] = []

    async def run() -> list[str]:
        res = []
        async for host, ports in network.async_scan_hosts_iter([
            "h1",
            "h2",
        ], 1, 1, updates.append):
            res.append(host)
        return res

    hosts = asyncio.run(run())

    assert hosts == ["h1", "h2"]
    assert updates[-2:] == [1.0, None]

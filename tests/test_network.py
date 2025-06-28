import socket
import socketserver
import threading
import asyncio
import importlib
import subprocess
import sys
import time
from pathlib import Path

import src.utils.network as network
import psutil
import pytest


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
        assert isinstance(result[port], str)


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
        assert isinstance(result[port], network.PortInfo)
    assert result[port].banner == "banner"


def test_scan_ports_with_latency():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = network.scan_ports("localhost", port, port, with_latency=True)
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result[port], network.PortInfo)
        assert result[port].latency is not None


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
            result = asyncio.run(
                network.async_scan_top_ports("localhost", top=1)
            )
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
        assert isinstance(result[port], network.PortInfo)
        assert result[port].banner == "banner"


def test_async_scan_ports_with_latency():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
                network.async_scan_ports("localhost", port, port, with_latency=True)
            )
        finally:
            server.shutdown()
            thread.join()
        assert isinstance(result[port], network.PortInfo)
        assert result[port].latency is not None


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
    with socketserver.TCPServer(("localhost", 0), _Handler) as s1, socketserver.TCPServer(("localhost", 0), _Handler) as s2:
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
    with socketserver.TCPServer(("localhost", 0), _Handler) as s1, socketserver.TCPServer(("localhost", 0), _Handler) as s2:
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
    script = Path("scripts/network_scan.py")
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [sys.executable, str(script), str(port), "localhost", "--timeout", "0.1", "--family", "ipv4"],
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            thread.join()

    assert result.returncode == 0
    assert f"localhost: {port}" in result.stdout


def test_network_scan_cli_services(tmp_path):
    script = Path("scripts/network_scan.py")
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
    script = Path("scripts/network_scan.py")
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
    script = Path("scripts/network_scan.py")
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
    script = Path("scripts/network_scan.py")
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
    script = Path("scripts/network_scan.py")
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
    script = Path("scripts/network_scan.py")
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
    script = Path("scripts/network_scan.py")
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
    assert "localhost" in result.stdout
    assert "other" not in result.stdout


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


def test_detect_local_hosts(monkeypatch):
    snic = psutil._common.snicaddr

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
    hosts = network.detect_local_hosts(max_hosts_per_network=6)
    assert "192.168.1.10" not in hosts
    assert len(hosts) == 5


def test_async_auto_scan(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost", "other"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
            result = asyncio.run(network.async_auto_scan(port, port, ports=[port]))
        finally:
            server.shutdown()
            thread.join()

    assert result["localhost"] == [port]


def test_async_auto_scan_with_services(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
            result = asyncio.run(network.async_auto_scan(port, port, ports=[port], with_services=True))
        finally:
            server.shutdown()
            thread.join()

    assert isinstance(result["localhost"], dict)
    assert list(result["localhost"].keys()) == [port]


def test_async_auto_scan_with_banner(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
            result = asyncio.run(network.async_auto_scan(port, port, ports=[port], with_banner=True))
        finally:
            server.shutdown()
            thread.join()

    assert isinstance(result["localhost"], dict)
    info = result["localhost"][port]
    assert isinstance(info, network.PortInfo)
    assert info.banner == "banner"


def test_async_auto_scan_detailed(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
        if return_ttl and return_latency:
            return True, 64, 0.01
        if return_ttl:
            return True, 64
        if return_latency:
            return True, 0.01
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)
    monkeypatch.setattr(network, "get_mac_address", lambda h: "00:0c:29:aa:bb:cc")
    monkeypatch.setattr(network, "_get_connection_counts", lambda ports: {p: 2 for p in ports})

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
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
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.mac == "00:0c:29:aa:bb:cc"
    assert info.connections[port] == 2
    assert info.os_guess == "Linux"
    assert info.vendor == "VMware"
    assert info.device_type == "Virtual Machine"


def test_async_filter_active_hosts(monkeypatch):
    calls: list[str] = []

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
        network.async_filter_active_hosts(["1.1.1.1", "2.2.2.2"], concurrency=2, return_ttl=True)
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


def test_async_auto_scan_http_info(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
            result = asyncio.run(
                network.async_auto_scan(
                    port,
                    port,
                    ports=[port],
                    with_http_info=True,
                )
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
    def fake_detect() -> list[str]:
        return ["localhost"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
            result = asyncio.run(
                network.async_auto_scan(
                    port,
                    port,
                    ports=[port],
                    with_ping_latency=True,
                )
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.ping_latency is not None


def test_async_auto_scan_cancel(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost", "other"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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

    result = asyncio.run(
        network.async_auto_scan(1, 1, cancel_event=cancel)
    )

    assert result == {}


def test_async_filter_active_hosts_cancel(monkeypatch):
    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
    info = network.AutoScanInfo({21: network.PortInfo("ftp"), 80: network.PortInfo("http")})
    info.os_guess = "Windows"
    info.device_type = "Router"
    score = network._estimate_risk(info)
    assert score >= 50


def test_async_auto_scan_risk(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
        return True

    monkeypatch.setattr(network, "detect_local_hosts", fake_detect)
    monkeypatch.setattr(network, "_async_ping_host", fake_ping)

    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(
                network.async_auto_scan(
                    port,
                    port,
                    ports=[port],
                    with_risk_score=True,
                )
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.risk_score is not None


def test_async_auto_scan_ttl(monkeypatch):
    def fake_detect() -> list[str]:
        return ["localhost"]

    async def fake_ping(host: str, timeout: float = 1.0, *, return_ttl: bool = False, return_latency: bool = False):
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
            result = asyncio.run(
                network.async_auto_scan(
                    port,
                    port,
                    ports=[port],
                    with_ttl=True,
                )
            )
        finally:
            server.shutdown()
            thread.join()

    info = result["localhost"]
    assert isinstance(info, network.AutoScanInfo)
    assert info.ttl == 64

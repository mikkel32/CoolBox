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


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
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

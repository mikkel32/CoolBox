import socketserver
import threading

import asyncio

from src.utils.network import scan_ports, async_scan_ports


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(1)


def test_scan_ports():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = scan_ports("localhost", port, port)
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]

    # Closed port
    assert scan_ports("localhost", port + 1, port + 1) == []


def test_async_scan_ports():
    with socketserver.TCPServer(("localhost", 0), _Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = asyncio.run(async_scan_ports("localhost", port, port))
        finally:
            server.shutdown()
            thread.join()
        assert result == [port]

    assert asyncio.run(async_scan_ports("localhost", port + 1, port + 1)) == []

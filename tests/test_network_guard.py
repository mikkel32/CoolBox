import types
import json
import pytest

from src.utils.network_guard import NetworkGuard, AsyncNetworkGuard
from src.utils.network_baseline import NetworkBaseline
from src.utils import security


def test_guard_start_stop(monkeypatch):
    called = {"start": 0, "stop": 0}

    class FakeMonitor:
        running = False

        def start(self):
            called["start"] += 1
            self.running = True

        def stop(self, timeout=None):
            called["stop"] += 1
            self.running = False

    guard = NetworkGuard()
    monkeypatch.setattr(guard, "monitor", FakeMonitor())

    guard.start()
    assert guard.running is True
    guard.stop()
    assert guard.running is False
    assert called == {"start": 1, "stop": 1}


def test_guard_context(monkeypatch):
    calls = []

    class FakeMonitor:
        running = False

        def start(self):
            calls.append("start")
            self.running = True

        def stop(self, timeout=None):
            calls.append("stop")
            self.running = False

    guard = NetworkGuard()
    monkeypatch.setattr(guard, "monitor", FakeMonitor())

    with guard as g:
        assert g.running is True

    assert calls == ["start", "stop"]


def test_guard_firewall_option():
    guard = NetworkGuard(firewall=True)
    assert guard.port_watchdog.firewall is True
    assert guard.conn_watchdog.firewall is True


def test_block_port(monkeypatch):
    guard = NetworkGuard()
    monkeypatch.setattr(
        guard.port_watchdog,
        "add",
        lambda port, pids, names=None, exes=None: called.append(
            (port, pids, names, exes)
        ),
    )
    called = []
    monkeypatch.setattr(
        "src.utils.security.kill_process_by_port", lambda port, tree=True: True
    )
    monkeypatch.setattr(
        "src.utils.security.list_open_ports",
        lambda: {50: [types.SimpleNamespace(pid=1, process="p", exe="/p")]},
    )

    assert guard.block_port(50) is True
    assert called and called[0][0] == 50


def test_block_remote(monkeypatch):
    guard = NetworkGuard()
    called = []
    monkeypatch.setattr(
        guard.conn_watchdog,
        "add",
        lambda k, pids, names=None, exes=None: called.append((k, pids, names, exes)),
    )
    monkeypatch.setattr(
        "src.utils.security.kill_connections_by_remote",
        lambda h, port=None, tree=True: True,
    )
    monkeypatch.setattr(
        "src.utils.security.list_active_connections",
        lambda: {"1.1.1.1:80": [types.SimpleNamespace(pid=2, process="x", exe="/x")]},
    )
    monkeypatch.setattr("socket.gethostbyname", lambda h: "1.1.1.1")

    assert guard.block_remote("example.com", 80) is True
    assert called and called[0][0] == "1.1.1.1:80"


def test_block_port_range(monkeypatch):
    guard = NetworkGuard()
    added = []
    monkeypatch.setattr(
        guard.port_watchdog,
        "add",
        lambda port, pids, names=None, exes=None: added.append(port),
    )
    monkeypatch.setattr(
        "src.utils.security.list_open_ports",
        lambda: {
            50: [types.SimpleNamespace(pid=1, process="p", exe="/p")],
            51: [types.SimpleNamespace(pid=2, process="q", exe="/q")],
        },
    )
    monkeypatch.setattr(
        "src.utils.security.kill_port_range",
        lambda s, e, tree=True: {50: True, 51: False},
    )

    res = guard.block_port_range(50, 51)
    assert res == {50: True, 51: False}
    assert set(added) == {50, 51}


def test_block_remotes(monkeypatch):
    guard = NetworkGuard()
    added = []
    monkeypatch.setattr(
        guard.conn_watchdog,
        "add",
        lambda k, pids, names=None, exes=None: added.append(k),
    )
    monkeypatch.setattr(
        "src.utils.security.list_active_connections",
        lambda: {"1.1.1.1:80": [types.SimpleNamespace(pid=3, process="x", exe="/x")]},
    )
    monkeypatch.setattr(
        "src.utils.security.kill_connections_by_remote",
        lambda h, port=None, tree=True: h == "host1",
    )
    monkeypatch.setattr(
        "socket.gethostbyname",
        lambda h: {"host1": "1.1.1.1", "host2": "2.2.2.2"}.get(h, h),
    )

    res = guard.block_remotes(["host1", "host2"], 80)
    assert res == {"host1": True, "host2": False}
    assert "1.1.1.1:80" in added


def test_block_remote_firewall(monkeypatch):
    guard = NetworkGuard()
    monkeypatch.setattr(
        "src.utils.security.list_active_connections",
        lambda: {"1.1.1.1:80": [types.SimpleNamespace(pid=2, process="x", exe="/x")]},
    )
    monkeypatch.setattr(
        "src.utils.security.kill_connections_by_remote",
        lambda h, port=None, tree=True: True,
    )
    monkeypatch.setattr("socket.gethostbyname", lambda h: "1.1.1.1")
    calls = []
    monkeypatch.setattr(
        "src.utils.security.block_remote_firewall",
        lambda ip, port: calls.append((ip, port)) or True,
    )

    assert guard.block_remote("example.com", 80, firewall=True) is True
    assert calls == [("1.1.1.1", 80)]


def test_block_remotes_firewall(monkeypatch):
    guard = NetworkGuard()
    monkeypatch.setattr(
        "src.utils.security.list_active_connections",
        lambda: {"1.1.1.1:80": [types.SimpleNamespace(pid=3, process="x", exe="/x")]},
    )
    monkeypatch.setattr(
        "src.utils.security.kill_connections_by_remote",
        lambda h, port=None, tree=True: True,
    )
    monkeypatch.setattr(
        "socket.gethostbyname",
        lambda h: {"host1": "1.1.1.1", "host2": "2.2.2.2"}.get(h, h),
    )
    calls = []
    monkeypatch.setattr(
        "src.utils.security.block_remote_firewall",
        lambda ip, port: calls.append((ip, port)) or True,
    )

    res = guard.block_remotes(["host1", "host2"], 80, firewall=True)
    assert res == {"host1": True, "host2": True}
    assert ("1.1.1.1", 80) in calls and ("2.2.2.2", 80) in calls


def test_block_port_firewall(monkeypatch):
    guard = NetworkGuard()
    monkeypatch.setattr(
        "src.utils.security.list_open_ports",
        lambda: {90: [types.SimpleNamespace(pid=5, process="p", exe="/p")]},
    )
    monkeypatch.setattr(
        "src.utils.security.kill_process_by_port", lambda p, tree=True: True
    )
    calls = []
    monkeypatch.setattr(
        "src.utils.security.block_port_firewall",
        lambda port: calls.append(port) or True,
    )

    assert guard.block_port(90, firewall=True) is True
    assert calls == [90]


def test_unblock_port(monkeypatch):
    guard = NetworkGuard()
    called = []
    monkeypatch.setattr(
        guard.port_watchdog, "remove", lambda p: called.append(p) or True
    )
    monkeypatch.setattr(
        "src.utils.security.unblock_port_firewall",
        lambda p: called.append(f"fw{p}") or True,
    )

    res = guard.unblock_port(55, firewall=True)
    assert res is True
    assert called == [55, "fw55"]


def test_block_port_range_firewall(monkeypatch):
    guard = NetworkGuard()
    monkeypatch.setattr(
        "src.utils.security.list_open_ports",
        lambda: {
            91: [types.SimpleNamespace(pid=1, process="a", exe="/a")],
            92: [types.SimpleNamespace(pid=2, process="b", exe="/b")],
        },
    )
    monkeypatch.setattr(
        "src.utils.security.kill_port_range",
        lambda s, e, tree=True: {91: True, 92: True},
    )
    added = []
    monkeypatch.setattr(
        guard.port_watchdog,
        "add",
        lambda port, pids, names=None, exes=None: added.append(port),
    )
    calls = []
    monkeypatch.setattr(
        "src.utils.security.block_port_firewall",
        lambda port: calls.append(port) or True,
    )

    res = guard.block_port_range(91, 92, firewall=True)
    assert res == {91: True, 92: True}
    assert set(added) == {91, 92}
    assert calls == [91, 92]


def test_unblock_remote(monkeypatch):
    guard = NetworkGuard()
    called = []
    monkeypatch.setattr(
        guard.conn_watchdog, "remove", lambda k: called.append(k) or True
    )
    monkeypatch.setattr(
        "src.utils.security.unblock_remote_firewall",
        lambda ip, port: called.append(f"fw{ip}:{port}") or True,
    )
    monkeypatch.setattr("socket.gethostbyname", lambda h: "8.8.8.8")
    security.clear_resolve_cache()

    res = guard.unblock_remote("example.com", 80, firewall=True)
    assert res is True
    assert called == ["8.8.8.8:80", "fw8.8.8.8:80"]


def test_guard_logging(monkeypatch):
    guard = NetworkGuard()
    events = []
    monkeypatch.setattr(
        "src.utils.network_guard.security_log.add_security_event",
        lambda c, m: events.append((c, m)),
    )
    monkeypatch.setattr(
        "src.utils.security.list_open_ports",
        lambda: {80: [types.SimpleNamespace(pid=1, process="p", exe="/p")]},
    )
    monkeypatch.setattr(
        "src.utils.security.kill_process_by_port", lambda p, tree=True: True
    )
    monkeypatch.setattr("src.utils.security.block_port_firewall", lambda p: True)
    guard.block_port(80, firewall=True)
    monkeypatch.setattr(guard.port_watchdog, "remove", lambda p: True)
    monkeypatch.setattr("src.utils.security.unblock_port_firewall", lambda p: True)
    guard.unblock_port(80, firewall=True)
    monkeypatch.setattr(
        "src.utils.security.list_active_connections",
        lambda: {"1.1.1.1:80": [types.SimpleNamespace(pid=2, process="x", exe="/x")]},
    )
    monkeypatch.setattr(
        "src.utils.security.kill_connections_by_remote",
        lambda h, port=None, tree=True: True,
    )
    monkeypatch.setattr("socket.gethostbyname", lambda h: "1.1.1.1")
    security.clear_resolve_cache()
    monkeypatch.setattr(
        "src.utils.security.block_remote_firewall", lambda ip, port: True
    )
    guard.block_remote("example.com", 80, firewall=True)
    monkeypatch.setattr(guard.conn_watchdog, "remove", lambda k: True)
    monkeypatch.setattr(
        "src.utils.security.unblock_remote_firewall", lambda ip, port: True
    )
    guard.unblock_remote("example.com", 80, firewall=True)
    assert ("block_port", "80") in events
    assert ("firewall_block_port", "80") in events
    assert ("unblock_port", "80") in events
    assert ("firewall_unblock_port", "80") in events
    assert ("block_remote", "1.1.1.1:80") in events
    assert ("firewall_block_remote", "1.1.1.1:80") in events
    assert ("unblock_remote", "1.1.1.1:80") in events
    assert ("firewall_unblock_remote", "1.1.1.1:80") in events


def test_clear_helpers(monkeypatch):
    guard = NetworkGuard()
    pcalls = []
    rcalls = []
    bcalls = []
    monkeypatch.setattr(guard.port_watchdog, "clear", lambda: pcalls.append(True))
    monkeypatch.setattr(guard.conn_watchdog, "clear", lambda: rcalls.append(True))
    monkeypatch.setattr(guard.blocker, "clear", lambda: bcalls.append(True))

    guard.clear_ports()
    guard.clear_remotes()
    guard.clear_all()

    assert pcalls == [True, True]
    assert rcalls == [True, True]
    assert bcalls == [True]


@pytest.mark.asyncio
async def test_async_guard_start_stop(monkeypatch):
    calls = {"start": 0, "stop": 0}

    class FakeMonitor:
        running = False

        async def start(self):
            calls["start"] += 1
            self.running = True

        async def stop(self):
            calls["stop"] += 1
            self.running = False

    guard = AsyncNetworkGuard()
    monkeypatch.setattr(guard, "monitor", FakeMonitor())

    await guard.start()
    assert guard.running is True
    await guard.stop()
    assert guard.running is False
    assert calls == {"start": 1, "stop": 1}


@pytest.mark.asyncio
async def test_async_guard_context(monkeypatch):
    calls = []

    class FakeMonitor:
        running = False

        async def start(self):
            calls.append("start")
            self.running = True

        async def stop(self):
            calls.append("stop")
            self.running = False

    guard = AsyncNetworkGuard()
    monkeypatch.setattr(guard, "monitor", FakeMonitor())

    async with guard as g:
        assert g.running is True

    assert calls == ["start", "stop"]


@pytest.mark.asyncio
async def test_async_block_port(monkeypatch):
    guard = AsyncNetworkGuard()
    added = []

    async def fake_add(port, *a, **k):
        added.append(port)

    async def fake_list():
        return {55: [types.SimpleNamespace(pid=1, process="p", exe="/p")]}

    async def fake_kill(port, tree=True):
        return True

    async def fake_block(port):
        added.append(f"fw{port}")
        return True

    monkeypatch.setattr(guard.port_watchdog, "async_add", fake_add)
    monkeypatch.setattr("src.utils.security.async_list_open_ports", fake_list)
    monkeypatch.setattr("src.utils.security.async_kill_process_by_port", fake_kill)
    monkeypatch.setattr("src.utils.security.async_block_port_firewall", fake_block)

    assert await guard.block_port(55, firewall=True) is True
    assert added == [55, "fw55"]


@pytest.mark.asyncio
async def test_async_unblock_port(monkeypatch):
    guard = AsyncNetworkGuard()
    calls = []

    async def fake_remove(p):
        calls.append(p)
        return True

    async def fake_unblock(p):
        calls.append(f"fw{p}")
        return True

    monkeypatch.setattr(guard.port_watchdog, "async_remove", fake_remove)
    monkeypatch.setattr("src.utils.security.async_unblock_port_firewall", fake_unblock)
    assert await guard.unblock_port(55, firewall=True) is True
    assert calls == [55, "fw55"]


@pytest.mark.asyncio
async def test_async_clear(monkeypatch):
    guard = AsyncNetworkGuard()
    pcalls = []
    rcalls = []
    bcalls = []

    async def pc():
        pcalls.append(True)

    async def rc():
        rcalls.append(True)

    async def bc():
        bcalls.append(True)

    monkeypatch.setattr(guard.port_watchdog, "async_clear", pc)
    monkeypatch.setattr(guard.conn_watchdog, "async_clear", rc)
    monkeypatch.setattr(guard.blocker, "async_clear", bc)

    await guard.clear_all()

    assert pcalls == [True]
    assert rcalls == [True]
    assert bcalls == [True]


def test_guard_baseline(tmp_path):
    guard = NetworkGuard(baseline=NetworkBaseline(path=tmp_path / "b.json"))
    guard.monitor.unknown_ports = {1}
    guard.monitor.unknown_hosts = {"h"}
    guard.accept_unknown()
    data = json.loads((tmp_path / "b.json").read_text())
    assert data["ports"] == [1]
    assert data["hosts"] == ["h"]
    guard.clear_baseline()
    data = json.loads((tmp_path / "b.json").read_text())
    assert data == {"ports": [], "hosts": []}


def test_guard_auto_block(monkeypatch):
    guard = NetworkGuard(auto_block_unknown=True, auto_threshold=2)
    calls = []
    monkeypatch.setattr(
        guard, "block_port", lambda p, firewall=False: calls.append(("p", p))
    )
    monkeypatch.setattr(
        guard,
        "block_remote",
        lambda h, port=None, firewall=False: calls.append(("h", h, port)),
    )
    guard.monitor.unknown_port_counts = {80: 2}
    guard.monitor.unknown_host_counts = {"1.1.1.1:80": 3}
    guard._on_monitor_update(guard.monitor)
    assert ("p", 80) in calls
    assert ("h", "1.1.1.1", 80) in calls
    assert guard.monitor.unknown_port_counts[80] == 0
    assert guard.monitor.unknown_host_counts["1.1.1.1:80"] == 0


@pytest.mark.asyncio
async def test_async_guard_auto_block(monkeypatch):
    guard = AsyncNetworkGuard(auto_block_unknown=True, auto_threshold=1)
    calls = []

    async def bp(port, firewall=False):
        calls.append(("p", port))

    async def br(host, port=None, firewall=False):
        calls.append(("h", host, port))

    monkeypatch.setattr(guard, "block_port", bp)
    monkeypatch.setattr(guard, "block_remote", br)
    guard.monitor.unknown_port_counts = {90: 1}
    guard.monitor.unknown_host_counts = {"2.2.2.2:80": 1}
    await guard._on_monitor_update(guard.monitor)
    assert ("p", 90) in calls
    assert ("h", "2.2.2.2", 80) in calls
    assert guard.monitor.unknown_port_counts[90] == 0
    assert guard.monitor.unknown_host_counts["2.2.2.2:80"] == 0


def test_set_auto_block_and_reset():
    guard = NetworkGuard()
    guard.monitor.unknown_port_counts = {1: 2}
    guard.monitor.unknown_host_counts = {"h": 3}
    guard.set_auto_block(True, 5)
    assert guard.auto_block_unknown is True
    assert guard.auto_threshold == 5
    guard.reset_anomaly_counts()
    assert guard.monitor.unknown_port_counts == {}
    assert guard.monitor.unknown_host_counts == {}


@pytest.mark.asyncio
async def test_async_set_auto_block_and_reset():
    guard = AsyncNetworkGuard()
    guard.monitor.unknown_port_counts = {2: 1}
    guard.monitor.unknown_host_counts = {"x": 1}
    await guard.set_auto_block(True, 3)
    assert guard.auto_block_unknown is True
    assert guard.auto_threshold == 3
    await guard.reset_anomaly_counts()
    assert guard.monitor.unknown_port_counts == {}
    assert guard.monitor.unknown_host_counts == {}


def test_set_anomaly_ttl():
    guard = NetworkGuard()
    guard.set_anomaly_ttl(30)
    assert guard.monitor.anomaly_ttl == 30


@pytest.mark.asyncio
async def test_async_set_anomaly_ttl():
    guard = AsyncNetworkGuard()
    await guard.set_anomaly_ttl(15)
    assert guard.monitor.anomaly_ttl == 15

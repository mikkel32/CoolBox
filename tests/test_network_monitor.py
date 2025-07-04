import time
import asyncio
from types import SimpleNamespace

import pytest

from src.utils.network_monitor import (
    NetworkMonitor,
    AsyncNetworkMonitor,
    NetworkState,
)
from src.utils import security
from src.utils.network_baseline import NetworkBaseline
from pathlib import Path


def test_network_monitor_loop(monkeypatch):
    calls = {"count": 0}

    def fake_monitor_network(*, port_watchdog=None, conn_watchdog=None):
        calls["count"] += 1
        return {1: []}, {"h": []}

    monkeypatch.setattr(security, "monitor_network", fake_monitor_network)

    nm = NetworkMonitor(interval=0.01)
    nm.start()
    time.sleep(0.11)
    nm.stop()

    assert calls["count"] >= 2
    assert not nm.running
    assert nm.last_state == NetworkState({1: []}, {"h": []})


def test_network_monitor_watchdogs(monkeypatch):
    events = {}

    class FakePortWD:
        def __init__(self):
            self.blocker = SimpleNamespace(check=lambda: events.setdefault("bp", True))

        def check(self, data):
            events["pc"] = isinstance(data, dict)

        def expire(self):
            events["pe"] = True

    class FakeConnWD:
        def __init__(self):
            self.blocker = SimpleNamespace(check=lambda: events.setdefault("bc", True))

        def check(self, data):
            events["cc"] = isinstance(data, dict)

        def expire(self):
            events["ce"] = True

    def fake_monitor_network(*, port_watchdog=None, conn_watchdog=None):
        if port_watchdog:
            port_watchdog.check({})
            port_watchdog.expire()
            port_watchdog.blocker.check()
        if conn_watchdog:
            conn_watchdog.check({})
            conn_watchdog.expire()
            conn_watchdog.blocker.check()
        return {}, {}

    monkeypatch.setattr(security, "monitor_network", fake_monitor_network)

    nm = NetworkMonitor(
        interval=0.01, port_watchdog=FakePortWD(), conn_watchdog=FakeConnWD()
    )
    nm.start()
    time.sleep(0.03)
    nm.stop()

    assert events == {
        "bp": True,
        "pc": True,
        "pe": True,
        "bc": True,
        "cc": True,
        "ce": True,
    }


def test_monitor_counts_and_callback(monkeypatch, tmp_path):
    bl = NetworkBaseline(path=tmp_path / "b.json")

    def fake_monitor_network(*, port_watchdog=None, conn_watchdog=None):
        return {55: []}, {"1.1.1.1:80": []}

    called = []

    def cb(monitor):
        called.append((dict(monitor.unknown_port_counts), dict(monitor.unknown_host_counts)))

    monkeypatch.setattr(security, "monitor_network", fake_monitor_network)

    nm = NetworkMonitor(interval=0.01, baseline=bl, callback=cb)
    nm._stop = SimpleNamespace(is_set=lambda: False, wait=lambda t: True)
    nm._run()

    assert nm.unknown_port_counts == {55: 1}
    assert nm.unknown_host_counts == {"1.1.1.1:80": 1}
    assert called and called[0][0] == {55: 1}


@pytest.mark.asyncio
async def test_async_helpers(monkeypatch):
    monkeypatch.setattr(security, "network_snapshot", lambda: [])
    ports = await security.async_list_open_ports([])
    conns = await security.async_list_active_connections([])
    assert ports == {}
    assert conns == {}


@pytest.mark.asyncio
async def test_async_network_monitor(monkeypatch):
    calls = {"count": 0}

    async def fake_async_monitor_network(*, port_watchdog=None, conn_watchdog=None):
        calls["count"] += 1
        return {1: []}, {"h": []}

    monkeypatch.setattr(security, "async_monitor_network", fake_async_monitor_network)

    nm = AsyncNetworkMonitor(interval=0.01)
    await nm.start()
    await asyncio.sleep(0.06)
    await nm.stop()

    assert calls["count"] >= 1
    assert nm.last_state == NetworkState({1: []}, {"h": []})


def test_reset_counts():
    nm = NetworkMonitor()
    nm.unknown_port_counts = {80: 2}
    nm.unknown_host_counts = {"h": 3}
    nm.reset_counts()
    assert nm.unknown_port_counts == {}
    assert nm.unknown_host_counts == {}


@pytest.mark.asyncio
async def test_async_reset_counts():
    nm = AsyncNetworkMonitor()
    nm.unknown_port_counts = {1: 1}
    nm.unknown_host_counts = {"h": 1}
    await nm.reset_counts()
    assert nm.unknown_port_counts == {}
    assert nm.unknown_host_counts == {}


def test_anomaly_ttl(monkeypatch):
    bl = NetworkBaseline(path=Path("/tmp/bl.json"))

    def fake_monitor_network(*, port_watchdog=None, conn_watchdog=None):
        return {99: []}, {"2.2.2.2:80": []}

    monkeypatch.setattr(security, "monitor_network", fake_monitor_network)

    nm = NetworkMonitor(interval=0.01, baseline=bl, anomaly_ttl=0.05)
    nm._stop = SimpleNamespace(is_set=lambda: False, wait=lambda t: True)
    nm._run()
    assert nm.unknown_port_counts == {99: 1}
    time.sleep(0.1)
    nm._run()
    assert nm.unknown_port_counts == {99: 1}

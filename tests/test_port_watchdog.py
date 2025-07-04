import psutil
import time
import json
import pytest

from src.utils.port_watchdog import PortWatchdog, PortRecord
from src.utils.process_blocker import ProcessBlocker
from src.utils.security import LocalPort


def test_watchdog_kills_reopened(monkeypatch, tmp_path):
    killed = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = PortWatchdog(
        max_attempts=2,
        blocker=ProcessBlocker(path=tmp_path / "b.json"),
        path=tmp_path / "w.json",
    )
    wd.add(80, [123])

    ports = {80: [LocalPort(80, 123, 'proc', 'http')]}
    wd.check(ports)
    assert killed == [123]
    assert 80 in wd.records

    wd.check(ports)
    assert killed == [123, 123]
    assert 80 in wd.records


def test_watchdog_handles_new_pid(monkeypatch, tmp_path):
    killed = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = PortWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / "b.json"),
        path=tmp_path / "w.json",
    )
    wd.add(81, [200])

    ports = {81: [LocalPort(81, 201, 'proc', 'http')]}
    wd.check(ports)
    assert set(killed) == {200, 201}
    assert 81 in wd.records


def test_watchdog_escalates_to_blocker(monkeypatch, tmp_path):
    killed = []
    blocked = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    blocker = ProcessBlocker(path=tmp_path / "b.json")
    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(blocker, 'add_by_pid', lambda pid: blocked.append(pid))
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = PortWatchdog(max_attempts=1, blocker=blocker, path=tmp_path / "w.json")
    wd.add(82, [300])

    ports = {82: [LocalPort(82, 300, 'proc', 'http')]}
    wd.check(ports)
    assert killed == [300]
    assert blocked == [300]


def test_watchdog_escalates_by_name_when_pid_gone(monkeypatch, tmp_path):
    killed = []
    blocked = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    blocker = ProcessBlocker(path=tmp_path / "b.json")
    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(blocker, 'add', lambda name, exe=None: blocked.append((name, exe)))
    # Simulate original pid gone but new pid alive
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: pid == 401)

    wd = PortWatchdog(max_attempts=1, blocker=blocker, path=tmp_path / "w.json")
    wd.add(83, [400], names=['evil'], exes=['/bad'])

    ports = {83: [LocalPort(83, 401, 'evil', 'http', '/bad')]}
    wd.check(ports)

    assert killed == [401]
    assert blocked == [('evil', '/bad')]


def test_watchdog_expiration(monkeypatch, tmp_path):
    killed = []

    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', lambda pid, timeout=3.0: killed.append(pid) or True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = PortWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / 'b.json'),
        expiration=0.1,
        firewall=True,
        path=tmp_path / 'w.json',
    )
    calls = []
    monkeypatch.setattr('src.utils.port_watchdog.security.unblock_port_firewall', lambda port: calls.append(port) or True)
    wd.add(90, [900], names=['x'], exes=['/x'])

    # No ports open, record should expire after 0.1s
    wd.check({})
    assert 90 in wd.records
    time.sleep(0.11)
    wd.check({})
    assert 90 not in wd.records
    assert calls == [90]


def test_watchdog_persistence(tmp_path):
    path = tmp_path / 'persist.json'
    wd = PortWatchdog(path=path)
    wd.add(55, [111])
    assert path.is_file()

    new_wd = PortWatchdog(path=path)
    assert 55 in new_wd.records


def test_save_persists_blocked_flag(tmp_path):
    path = tmp_path / 'persist.json'
    wd = PortWatchdog(firewall=True, path=path)
    wd.records[70] = PortRecord({7}, blocked_firewall=True)
    wd.save()
    data = json.loads(path.read_text())
    assert data['70']['blocked_firewall'] is True


def test_watchdog_firewall(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    called = []
    monkeypatch.setattr('src.utils.port_watchdog.security.block_port_firewall', lambda port: called.append(port) or True)
    events = []
    monkeypatch.setattr('src.utils.port_watchdog.security_log.add_security_event', lambda c, m: events.append((c, m)))

    wd = PortWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / 'b.json'),
        firewall=True,
        path=tmp_path / 'w.json',
    )
    wd.add(99, [500])
    wd.check({99: [LocalPort(99, 500, 'p', 'svc')]})
    assert called == [99]
    assert any(e[0] == 'firewall_block_port' for e in events)


def test_watchdog_remove_unblocks(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    calls = []
    monkeypatch.setattr('src.utils.port_watchdog.security.block_port_firewall', lambda port: None)
    monkeypatch.setattr('src.utils.port_watchdog.security.unblock_port_firewall', lambda port: calls.append(port) or True)

    wd = PortWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / 'b.json'),
        firewall=True,
        path=tmp_path / 'w.json',
    )
    wd.add(100, [5])
    wd.check({100: [LocalPort(100, 5, 'p', 'svc')]})
    assert wd.remove(100) is True
    assert calls == [100]


@pytest.mark.asyncio
async def test_async_methods(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    wd = PortWatchdog(blocker=ProcessBlocker(path=tmp_path / 'b.json'), path=tmp_path / 'w.json')
    await wd.async_add(88, [1])
    await wd.async_check({88: [LocalPort(88, 1, 'p', 'svc')]})
    await wd.async_expire()


def test_expire_method_unblocks(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    calls = []
    monkeypatch.setattr('src.utils.port_watchdog.security.unblock_port_firewall', lambda port: calls.append(port) or True)

    wd = PortWatchdog(expiration=0.0, firewall=True, path=tmp_path / 'w.json')
    wd.records[50] = PortRecord({1}, blocked_firewall=True)
    wd.expire()
    assert not wd.records
    assert calls == [50]


def test_clear_unblocks(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    calls = []
    monkeypatch.setattr('src.utils.port_watchdog.security.unblock_port_firewall', lambda port: calls.append(port) or True)

    wd = PortWatchdog(firewall=True, path=tmp_path / 'w.json')
    wd.records[60] = PortRecord({2}, blocked_firewall=True)
    wd.records[61] = PortRecord({3}, blocked_firewall=True)
    wd.clear()
    assert not wd.records
    assert calls == [60, 61]

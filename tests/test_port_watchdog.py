import types
import psutil
import pytest
import time

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

    wd = PortWatchdog(max_attempts=2, blocker=ProcessBlocker(path=tmp_path / "b.json"))
    wd.add(80, [123])

    ports = {80: [LocalPort(80, 123, 'proc', 'http')]}
    wd.check(ports)
    assert killed == [123]
    assert 80 in wd.records

    wd.check(ports)
    assert killed == [123, 123]
    assert 80 not in wd.records


def test_watchdog_handles_new_pid(monkeypatch, tmp_path):
    killed = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = PortWatchdog(max_attempts=1, blocker=ProcessBlocker(path=tmp_path / "b.json"))
    wd.add(81, [200])

    ports = {81: [LocalPort(81, 201, 'proc', 'http')]}
    wd.check(ports)
    assert set(killed) == {200, 201}
    assert 81 not in wd.records


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

    wd = PortWatchdog(max_attempts=1, blocker=blocker)
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

    wd = PortWatchdog(max_attempts=1, blocker=blocker)
    wd.add(83, [400], names=['evil'], exes=['/bad'])

    ports = {83: [LocalPort(83, 401, 'evil', 'http', '/bad')]}
    wd.check(ports)

    assert killed == [401]
    assert blocked == [('evil', '/bad')]


def test_watchdog_expiration(monkeypatch, tmp_path):
    killed = []

    monkeypatch.setattr('src.utils.port_watchdog.kill_process_tree', lambda pid, timeout=3.0: killed.append(pid) or True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: False)

    wd = PortWatchdog(max_attempts=5, blocker=ProcessBlocker(path=tmp_path/'b.json'), expiration=0.1)
    wd.add(90, [900], names=['x'], exes=['/x'])

    # No ports open, record should expire after 0.1s
    wd.check({})
    assert 90 in wd.records
    time.sleep(0.11)
    wd.check({})
    assert 90 not in wd.records


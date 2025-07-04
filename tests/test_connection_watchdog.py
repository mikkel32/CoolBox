import psutil
import pytest

import json
from src.utils.connection_watchdog import ConnectionWatchdog, ConnectionRecord
from src.utils.process_blocker import ProcessBlocker
from src.utils.security import ActiveConnection


def test_watchdog_kills_reconnected(monkeypatch, tmp_path):
    killed = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = ConnectionWatchdog(
        max_attempts=2,
        blocker=ProcessBlocker(path=tmp_path / "b.json"),
        path=tmp_path / "w.json",
    )
    wd.add('1.1.1.1:80', [123])

    conns = {'1.1.1.1:80': [ActiveConnection(('0.0.0.0', 0), ('1.1.1.1', 80), 'ESTABLISHED', 123, 'proc')]}
    wd.check(conns)
    assert killed == [123]
    assert '1.1.1.1:80' in wd.records

    wd.check(conns)
    assert killed == [123, 123]
    assert '1.1.1.1:80' in wd.records


def test_watchdog_handles_new_pid(monkeypatch, tmp_path):
    killed = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = ConnectionWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / "b.json"),
        path=tmp_path / "w.json",
    )
    wd.add('2.2.2.2:80', [200])

    conns = {'2.2.2.2:80': [ActiveConnection(('0.0.0.0', 0), ('2.2.2.2', 80), 'ESTABLISHED', 201, 'proc')]}
    wd.check(conns)
    assert set(killed) == {200, 201}
    assert '2.2.2.2:80' in wd.records


def test_watchdog_escalates_to_blocker(monkeypatch, tmp_path):
    killed = []
    blocked = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    blocker = ProcessBlocker(path=tmp_path / "b.json")
    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(blocker, 'add_by_pid', lambda pid: blocked.append(pid))
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = ConnectionWatchdog(max_attempts=1, blocker=blocker, path=tmp_path / "w.json")
    wd.add('3.3.3.3:80', [300])

    conns = {'3.3.3.3:80': [ActiveConnection(('0.0.0.0', 0), ('3.3.3.3', 80), 'ESTABLISHED', 300, 'proc')]}
    wd.check(conns)
    assert killed == [300]
    assert blocked == [300]


def test_watchdog_escalates_by_name_when_pid_gone(monkeypatch, tmp_path):
    killed = []
    blocked = []

    def fake_kill(pid, *, timeout=3.0):
        killed.append(pid)
        return True

    blocker = ProcessBlocker(path=tmp_path / "b.json")
    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', fake_kill)
    monkeypatch.setattr(blocker, 'add', lambda name, exe=None: blocked.append((name, exe)))
    # Simulate original pid gone but new pid alive
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: pid == 401)

    wd = ConnectionWatchdog(max_attempts=1, blocker=blocker, path=tmp_path / "w.json")
    wd.add('4.4.4.4:80', [400], names=['evil'], exes=['/bad'])

    conns = {'4.4.4.4:80': [ActiveConnection(('0.0.0.0', 0), ('4.4.4.4', 80), 'ESTABLISHED', 401, 'evil', '/bad')]}
    wd.check(conns)

    assert killed == [401]
    assert blocked == [('evil', '/bad')]


def test_watchdog_expiration(monkeypatch, tmp_path):
    killed = []

    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', lambda pid, timeout=3.0: killed.append(pid) or True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    wd = ConnectionWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / 'b.json'),
        expiration=0.1,
        firewall=True,
        path=tmp_path / 'w.json',
    )
    calls = []
    monkeypatch.setattr('src.utils.connection_watchdog.security.unblock_remote_firewall', lambda host, port=None: calls.append((host, port)) or True)
    wd.add('5.5.5.5:80', [900], names=['x'], exes=['/x'])

    # No connections, record should expire after 0.1s
    wd.check({})
    assert '5.5.5.5:80' in wd.records
    import time
    time.sleep(0.11)
    wd.check({})
    assert '5.5.5.5:80' not in wd.records
    assert calls == [('5.5.5.5', 80)]


def test_watchdog_firewall(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    calls = []
    monkeypatch.setattr(
        'src.utils.connection_watchdog.security.block_remote_firewall',
        lambda host, port=None: calls.append((host, port)) or True,
    )
    events = []
    monkeypatch.setattr(
        'src.utils.connection_watchdog.security_log.add_security_event',
        lambda c, m: events.append((c, m)),
    )

    wd = ConnectionWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / 'b.json'),
        firewall=True,
        path=tmp_path / 'w.json',
    )
    wd.add('1.1.1.1:80', [7])
    conns = {'1.1.1.1:80': [ActiveConnection(('0.0.0.0', 0), ('1.1.1.1', 80), 'ESTABLISHED', 7, 'proc')]}
    wd.check(conns)
    assert calls == [('1.1.1.1', 80)]
    assert any(e[0] == 'firewall_block_remote' for e in events)


def test_watchdog_remove_unblocks(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    calls = []
    monkeypatch.setattr(
        'src.utils.connection_watchdog.security.block_remote_firewall',
        lambda host, port=None: None,
    )
    monkeypatch.setattr(
        'src.utils.connection_watchdog.security.unblock_remote_firewall',
        lambda host, port=None: calls.append((host, port)) or True,
    )
    events = []
    monkeypatch.setattr(
        'src.utils.connection_watchdog.security_log.add_security_event',
        lambda c, m: events.append((c, m)),
    )

    wd = ConnectionWatchdog(
        max_attempts=1,
        blocker=ProcessBlocker(path=tmp_path / 'b.json'),
        firewall=True,
        path=tmp_path / 'w.json',
    )
    wd.add('9.9.9.9:80', [1])
    wd.check({
        '9.9.9.9:80': [
            ActiveConnection(
                ('0.0.0.0', 0),
                ('9.9.9.9', 80),
                'ESTABLISHED',
                1,
                'p',
            )
        ]
    })
    assert wd.remove('9.9.9.9:80') is True
    assert calls == [('9.9.9.9', 80)]
    assert any(e[0] == 'firewall_unblock_remote' for e in events)


@pytest.mark.asyncio
async def test_async_methods(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    wd = ConnectionWatchdog(blocker=ProcessBlocker(path=tmp_path / 'b.json'), path=tmp_path / 'w.json')
    await wd.async_add('2.2.2.2:80', [1])
    conns = {'2.2.2.2:80': [ActiveConnection(('0.0.0.0', 0), ('2.2.2.2', 80), 'ESTABLISHED', 1, 'p')]}
    await wd.async_check(conns)
    await wd.async_expire()


def test_expire_method_unblocks(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    calls = []
    monkeypatch.setattr('src.utils.connection_watchdog.security.unblock_remote_firewall', lambda host, port=None: calls.append((host, port)) or True)

    wd = ConnectionWatchdog(expiration=0.0, firewall=True, path=tmp_path / 'w.json')
    wd.records['1.1.1.1:80'] = ConnectionRecord({1}, blocked_firewall=True)
    wd.expire()
    assert '1.1.1.1:80' not in wd.records
    assert calls == [('1.1.1.1', 80)]


def test_clear_unblocks(monkeypatch, tmp_path):
    monkeypatch.setattr('src.utils.connection_watchdog.kill_process_tree', lambda pid, timeout=3.0: True)
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)
    calls = []
    monkeypatch.setattr('src.utils.connection_watchdog.security.unblock_remote_firewall', lambda host, port=None: calls.append((host, port)) or True)

    wd = ConnectionWatchdog(firewall=True, path=tmp_path / 'w.json')
    wd.records['2.2.2.2:80'] = ConnectionRecord({2}, blocked_firewall=True)
    wd.records['3.3.3.3:443'] = ConnectionRecord({3}, blocked_firewall=True)
    wd.clear()
    assert not wd.records
    assert calls == [('2.2.2.2', 80), ('3.3.3.3', 443)]


def test_save_persists_blocked_flag(tmp_path):
    wd = ConnectionWatchdog(firewall=True, path=tmp_path / 'w.json')
    wd.records['4.4.4.4:80'] = ConnectionRecord({4}, blocked_firewall=True)
    wd.save()
    data = json.loads((tmp_path / 'w.json').read_text())
    assert data['4.4.4.4:80']['blocked_firewall'] is True

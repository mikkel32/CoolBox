from types import SimpleNamespace
import psutil

from src.utils.security import (
    list_active_connections,
    kill_connections_by_remote,
)
import src.utils.security as security


def test_list_active_connections(monkeypatch):
    security._PROC_NAME_CACHE.clear()
    security._PROC_EXE_CACHE.clear()
    fake_conns = [
        SimpleNamespace(
            laddr=SimpleNamespace(ip='1.2.3.4', port=1000),
            raddr=SimpleNamespace(ip='8.8.8.8', port=80),
            status='ESTABLISHED',
            pid=1234,
        ),
        SimpleNamespace(
            laddr=None,
            raddr=None,
            status='LISTEN',
            pid=None,
        ),
    ]
    monkeypatch.setattr(security, 'network_snapshot', lambda: list(fake_conns))
    monkeypatch.setattr(
        psutil,
        'process_iter',
        lambda attrs=None: iter([SimpleNamespace(info={'pid': 1234, 'name': 'proc', 'exe': '/p'})]),
    )
    monkeypatch.setattr(psutil, 'Process', lambda pid: (_ for _ in ()).throw(AssertionError))
    conns = list_active_connections()
    assert '8.8.8.8:80' in conns
    entry = conns['8.8.8.8:80'][0]
    assert entry.pid == 1234
    assert entry.process == 'proc'
    assert entry.exe == '/p'


def test_kill_connections_by_remote(monkeypatch):
    security._PROC_NAME_CACHE.clear()
    security._PROC_EXE_CACHE.clear()
    fake_conns = [
        SimpleNamespace(
            laddr=SimpleNamespace(ip='1.2.3.4', port=1000),
            raddr=SimpleNamespace(ip='8.8.8.8', port=80),
            status='ESTABLISHED',
            pid=4321,
        )
    ]
    monkeypatch.setattr(psutil, 'net_connections', lambda kind='inet': fake_conns)
    killed = []

    monkeypatch.setattr('src.utils.security.kill_process', lambda pid, timeout=3.0: killed.append(('kill', pid)) or True)
    monkeypatch.setattr('src.utils.security.kill_process_tree', lambda pid, timeout=3.0: killed.append(('tree', pid)) or True)

    assert kill_connections_by_remote('8.8.8.8', tree=False) is True
    assert killed == [('kill', 4321)]
    killed.clear()
    assert kill_connections_by_remote('8.8.8.8', port=80, tree=True) is True
    assert killed == [('tree', 4321)]


def test_kill_connections_by_remotes(monkeypatch):
    fake_conns = [
        SimpleNamespace(
            laddr=SimpleNamespace(ip='1.2.3.4', port=1000),
            raddr=SimpleNamespace(ip='8.8.8.8', port=80),
            status='ESTABLISHED',
            pid=123,
        )
    ]
    monkeypatch.setattr(psutil, 'net_connections', lambda kind='inet': fake_conns)
    monkeypatch.setattr('src.utils.security.kill_process_tree', lambda pid, timeout=3.0: True)

    res = security.kill_connections_by_remotes(['8.8.8.8', '9.9.9.9'], tree=True)
    assert res == {'8.8.8.8': True, '9.9.9.9': False}


def test_network_snapshot_error(monkeypatch):
    monkeypatch.setattr(psutil, 'net_connections', lambda kind='inet': (_ for _ in ()).throw(OSError))
    assert security.network_snapshot() == []


def test_list_functions_with_snapshot(monkeypatch):
    fake = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=55), raddr=None, pid=1),
        SimpleNamespace(laddr=SimpleNamespace(ip='0.0.0.0', port=0), raddr=SimpleNamespace(ip='2.2.2.2', port=80), status='ESTABLISHED', pid=1),
    ]
    called = {'snap': 0}

    def fake_snap():
        called['snap'] += 1
        return list(fake)

    monkeypatch.setattr(security, 'network_snapshot', fake_snap)
    monkeypatch.setattr(security, 'refresh_process_cache', lambda pids: None)

    ports = security.list_open_ports(fake)
    conns = security.list_active_connections(fake)

    assert 55 in ports
    assert '2.2.2.2:80' in conns
    assert called['snap'] == 0


def test_monitor_network(monkeypatch):
    fake = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=99), raddr=None, pid=5),
        SimpleNamespace(laddr=SimpleNamespace(ip='0.0.0.0', port=0), raddr=SimpleNamespace(ip='4.4.4.4', port=443), status='ESTABLISHED', pid=5),
    ]
    monkeypatch.setattr(security, 'network_snapshot', lambda: list(fake))
    monkeypatch.setattr(security, 'refresh_process_cache', lambda pids: None)

    events = {}

    class FakePortWD:
        def __init__(self):
            self.blocker = SimpleNamespace(check=lambda: events.setdefault('bp', True))

        def check(self, data):
            events['pc'] = isinstance(data, dict)

        def expire(self):
            events['pe'] = True

    class FakeConnWD:
        def __init__(self):
            self.blocker = SimpleNamespace(check=lambda: events.setdefault('bc', True))

        def check(self, data):
            events['cc'] = isinstance(data, dict)

        def expire(self):
            events['ce'] = True

    ports, conns = security.monitor_network(port_watchdog=FakePortWD(), conn_watchdog=FakeConnWD())
    assert 99 in ports
    assert '4.4.4.4:443' in conns
    assert events == {'bp': True, 'pc': True, 'pe': True, 'bc': True, 'cc': True, 'ce': True}

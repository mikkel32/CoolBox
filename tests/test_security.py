import subprocess
import platform
import os
import sys
from types import SimpleNamespace
import psutil
import socket
from src.utils import kill_utils
import pytest

from src.utils import security
from src.utils.security import (
    LocalPort,
    is_firewall_enabled,
    set_firewall_enabled,
    is_defender_enabled,
    set_defender_enabled,
    is_admin,
    ensure_admin,
    require_admin,
    list_open_ports,
    kill_process_by_port,
    kill_port_range,
)


def test_is_firewall_enabled_true(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    def fake_output(cmd, text=True, stderr=None):
        return "State ON"
    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_firewall_enabled() is True


def test_is_firewall_enabled_false(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    def fake_output(cmd, text=True, stderr=None):
        return "State OFF"
    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_firewall_enabled() is False


def test_set_firewall_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    called = {}

    def fake_run(cmd, check=True, stdout=None, stderr=None):
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert set_firewall_enabled(True) is True
    assert called["cmd"] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]


def test_is_firewall_enabled_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    def fake_output(cmd, text=True, stderr=None):
        return "Status: active"

    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_firewall_enabled() is True


def test_set_firewall_enabled_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    called = {}

    def fake_run(cmd, check=True, stdout=None, stderr=None):
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert set_firewall_enabled(False) is True
    assert called["cmd"] == ["ufw", "disable"]


def test_is_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    def fake_output(cmd, text=True, stderr=None):
        return "False"
    monkeypatch.setattr(subprocess, "check_output", fake_output)
    assert is_defender_enabled() is True


def test_set_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    called = {}

    def fake_run(cmd, check=True, stdout=None, stderr=None):
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert set_defender_enabled(False) is True
    assert called["cmd"] == [
        "powershell",
        "-Command",
        "Set-MpPreference -DisableRealtimeMonitoring $true",
    ]


def test_is_admin_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    import ctypes
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    assert is_admin() is True


def test_is_admin_unix(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    assert is_admin() is True


def test_ensure_admin_already_admin(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    import ctypes
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    assert ensure_admin() is True


def test_ensure_admin_unix(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "geteuid", lambda: 1, raising=False)
    called = {}
    monkeypatch.setattr(os, "execvp", lambda prog, args: called.update({"prog": prog, "args": args}))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    assert ensure_admin() is False
    assert called.get("prog") == "sudo"


def test_require_admin_failure(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "geteuid", lambda: 1, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    with pytest.raises(PermissionError):
        require_admin()


def test_list_open_ports(monkeypatch):
    fake_conns = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=80), pid=1234),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=22), pid=None),
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": fake_conns)

    def fake_process(pid):
        return SimpleNamespace(name=lambda: "proc")

    monkeypatch.setattr(psutil, "Process", fake_process)
    monkeypatch.setattr(socket, "getservbyport", lambda p: {80: "http", 22: "ssh"}.get(p, "unknown"))

    ports = list_open_ports()
    assert ports == {
        22: [security.LocalPort(22, None, "unknown", "ssh")],
        80: [security.LocalPort(80, 1234, "proc", "http")],
    }


def test_kill_process_by_port(monkeypatch):
    called = {}
    fake_conns = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=80), pid=1234)
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": fake_conns)
    class FakeProc:
        def __init__(self, pid):
            called["pid"] = pid
        def terminate(self):
            called["term"] = True
        def kill(self):
            called["kill"] = True
        def wait(self, timeout=None):
            pass

    monkeypatch.setattr(psutil, "Process", FakeProc)
    assert kill_process_by_port(80) is True
    assert called == {"pid": 1234, "term": True}

    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": [])
    assert kill_process_by_port(80) is False


def test_kill_port_range(monkeypatch):
    called = []
    fake_conns = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=80), pid=111),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=81), pid=222),
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": fake_conns)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(name=lambda: "proc"))

    monkeypatch.setattr(security, "kill_process", lambda pid, timeout=3.0: (called.append(pid), True)[1])
    monkeypatch.setattr(security, "kill_process_tree", lambda pid, timeout=3.0: (called.append(pid), True)[1])
    res = kill_port_range(80, 81)
    assert res == {80: True, 81: True}
    assert called == [111, 222]

    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": [])
    assert kill_port_range(80, 81) == {80: False, 81: False}


def test_launch_security_center_missing(monkeypatch):
    monkeypatch.setattr(security.Path, "is_file", lambda self: False, raising=False)
    assert security.launch_security_center() is False


def test_launch_security_center_admin(monkeypatch):
    monkeypatch.setattr(security.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    called = {}
    monkeypatch.setattr(subprocess, "Popen", lambda args: called.setdefault("args", args))
    assert security.launch_security_center() is True
    assert called.get("args", [])[0] == sys.executable


def test_launch_security_center_sudo(monkeypatch):
    monkeypatch.setattr(security.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(security, "is_admin", lambda: False)
    monkeypatch.setattr(security.platform, "system", lambda: "Linux")
    called = {}
    monkeypatch.setattr(subprocess, "Popen", lambda args: called.setdefault("args", args))
    assert security.launch_security_center() is True
    assert called.get("args", [])[0] == "sudo"

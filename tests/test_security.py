import subprocess
import platform
import os
import sys
from types import SimpleNamespace
import psutil
import socket
import shutil
import pytest

from src.utils import security
from src.utils.security import (
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

    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, capture=False, **kwargs: "State ON" if capture else "",
    )
    assert is_firewall_enabled() is True


def test_is_firewall_enabled_false(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, capture=False, **kwargs: "State OFF" if capture else "",
    )
    assert is_firewall_enabled() is False


def test_set_firewall_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    called = {}

    def fake_run(cmd, capture=False, **kwargs):
        called["cmd"] = cmd
        return ""
    monkeypatch.setattr(security, "_run", fake_run)
    assert set_firewall_enabled(True) is True
    assert called["cmd"] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]


def test_is_firewall_enabled_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, capture=False, **kwargs: "Status: active" if capture else "",
    )
    assert is_firewall_enabled() is True


def test_set_firewall_enabled_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    called = {}

    def fake_run(cmd, capture=False, **kwargs):
        called["cmd"] = cmd
        return ""
    monkeypatch.setattr(security, "_run", fake_run)
    assert set_firewall_enabled(False) is True
    assert called["cmd"] == ["ufw", "disable"]


def test_is_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, capture=False, **kwargs: "False" if capture else "",
    )
    assert is_defender_enabled() is True


def test_set_defender_enabled(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    called = {}

    def fake_run(cmd, capture=False, **kwargs):
        called["cmd"] = cmd
        return ""
    monkeypatch.setattr(security, "_run", fake_run)
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
        return SimpleNamespace(name=lambda: "proc", exe=lambda: "/proc")

    monkeypatch.setattr(psutil, "Process", fake_process)
    monkeypatch.setattr(socket, "getservbyport", lambda p: {80: "http", 22: "ssh"}.get(p, "unknown"))

    ports = list_open_ports()
    assert ports == {
        22: [security.LocalPort(22, None, "unknown", "ssh", None)],
        80: [security.LocalPort(80, 1234, "proc", "http", "/proc")],
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

    def fake_bg(args, **kwargs):
        called["args"] = args
        called.update(kwargs)
        return True

    monkeypatch.setattr(security, "run_command_background", fake_bg)
    assert security.launch_security_center() is True
    assert called.get("args", [])[0] == sys.executable
    assert "creationflags" not in called
    assert "stdout" not in called
    assert "stderr" not in called


def test_launch_security_center_sudo(monkeypatch):
    monkeypatch.setattr(security.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(security, "is_admin", lambda: False)
    monkeypatch.setattr(security.platform, "system", lambda: "Linux")
    called = {}

    def fake_bg(args, **kwargs):
        called["args"] = args
        called.update(kwargs)
        return True

    monkeypatch.setattr(security, "run_command_background", fake_bg)
    assert security.launch_security_center() is True
    assert called.get("args", [])[0] == "sudo"
    assert "creationflags" not in called
    assert "stdout" not in called
    assert "stderr" not in called


def test_launch_security_center_hidden(monkeypatch):
    monkeypatch.setattr(security.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    monkeypatch.setattr(security.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    called = {}

    def fake_bg(args, **kwargs):
        called["args"] = args
        called.update(kwargs)
        return True

    monkeypatch.setattr(security, "run_command_background", fake_bg)

    assert security.launch_security_center(hide_console=True) is True
    assert called.get("args", [])[0].endswith("pythonw.exe")
    expected = (
        subprocess.CREATE_NO_WINDOW
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
    )
    assert called.get("creationflags") == expected
    assert called.get("stdout") is subprocess.DEVNULL
    assert called.get("stderr") is subprocess.DEVNULL


def test_launch_security_center_hidden_elevate(monkeypatch):
    monkeypatch.setattr(security.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(security, "is_admin", lambda: False)
    monkeypatch.setattr(security.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    called = {}

    def fake_shell_execute(hwnd, verb, file, params, directory, show):
        called["file"] = file
        called["verb"] = verb
        called["params"] = params
        called["show"] = show
        return 40

    import ctypes

    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(ShellExecuteW=fake_shell_execute)),
        raising=False,
    )

    assert security.launch_security_center(hide_console=True) is True
    assert called["file"].endswith("pythonw.exe")
    assert called["verb"] == "runas"
    assert called["show"] == 0


def test_launch_security_center_hidden_unix(monkeypatch):
    monkeypatch.setattr(security.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    monkeypatch.setattr(security.platform, "system", lambda: "Linux")
    called = {}

    def fake_bg(args, **kwargs):
        called["args"] = args
        called.update(kwargs)
        return True

    monkeypatch.setattr(security, "run_command_background", fake_bg)

    assert security.launch_security_center(hide_console=True) is True
    assert called.get("args", [])[0] == sys.executable
    assert "creationflags" not in called
    assert called.get("stdout") is subprocess.DEVNULL
    assert called.get("stderr") is subprocess.DEVNULL


def test_unix_firewall_tool_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(shutil, "which", lambda name: calls.append(name) or "pfctl")
    security._unix_firewall_tool.cache_clear()
    assert security._unix_firewall_tool() == "pfctl"
    assert security._unix_firewall_tool() == "pfctl"
    assert calls.count("pfctl") == 1


def test_run_timeout(monkeypatch):
    captured = {}

    def fake_run(args, check=True, stdout=None, timeout=None, **kwargs):
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert security._run(["echo", "hi"]) == ""
    assert captured.get("timeout") == 10.0


def test_is_firewall_enabled_pfctl(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(security, "_unix_firewall_tool", lambda: "pfctl")
    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, capture=False, **kwargs: "Status: Enabled" if capture else "",
    )
    assert is_firewall_enabled() is True


def test_set_firewall_enabled_pfctl(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(security, "_unix_firewall_tool", lambda: "pfctl")
    called = {}

    def fake_run(cmd, capture=False, **kwargs):
        called["cmd"] = cmd
        return ""

    monkeypatch.setattr(security, "_run", fake_run)
    assert set_firewall_enabled(False) is True
    assert called["cmd"] == ["pfctl", "-d"]

import ctypes
import os
import platform
from types import SimpleNamespace

import pytest

from src.utils import security


def test_is_firewall_enabled_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, timeout=30: security.RunResult(0, "State ON\nState ON", ""),
    )
    assert security.is_firewall_enabled() is True


def test_set_firewall_enabled_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(security, "is_admin", lambda: True)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    cmds: list[list[str]] = []

    def fake_run(cmd, timeout=30):
        cmds.append(cmd)
        if cmd[:6] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]:
            return security.RunResult(0, "", "")
        return security.RunResult(0, "State ON\nState ON", "")

    monkeypatch.setattr(security, "_run", fake_run)
    res = security.set_firewall_enabled(True)
    assert res.success is True
    assert cmds[0] == ["netsh", "advfirewall", "set", "allprofiles", "state", "on"]


def test_set_defender_realtime(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    scripts: list[str] = []

    def fake_run_ps(ps_script, timeout=30):
        scripts.append(ps_script)
        return security.RunResult(0, "", "")

    monkeypatch.setattr(security, "_run_ps", fake_run_ps)
    monkeypatch.setattr(
        security,
        "get_defender_status",
        lambda: security.DefenderStatus("RUNNING", True, True, True, True),
    )
    monkeypatch.setattr(security, "detect_defender_blockers", lambda: ())
    res = security.set_defender_realtime(True)
    assert res.success is True
    assert "DisableRealtimeMonitoring False" in scripts[0]


def test_is_admin_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    assert security.is_admin() is True


def test_is_admin_non_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(security, "_IS_WINDOWS", False)
    assert security.is_admin() is False


def test_ensure_admin(monkeypatch):
    monkeypatch.setattr(security, "is_admin", lambda: True)
    assert security.ensure_admin() is True


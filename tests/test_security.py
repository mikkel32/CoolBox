import ctypes
from types import SimpleNamespace

from src.utils import security


def test_is_firewall_enabled_parses(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(security.os.path, "exists", lambda p: True)
    sample = "State ON\nProfile\nState ON"
    monkeypatch.setattr(
        security,
        "_run",
        lambda cmd, timeout=30: security.RunResult(0, sample, ""),
    )
    assert security.is_firewall_enabled() is True


def test_set_firewall_enabled(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(security, "is_admin", lambda: True)
    monkeypatch.setattr(security.os.path, "exists", lambda p: True)
    calls = {}

    def fake_run(cmd, timeout=30):
        calls["cmd"] = cmd
        return security.RunResult(0, "", "")

    monkeypatch.setattr(security, "_run", fake_run)
    monkeypatch.setattr(security, "is_firewall_enabled", lambda: True)
    assert security.set_firewall_enabled(True) is True
    assert calls["cmd"][0] == "netsh"


def test_is_admin_windows(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    assert security.is_admin() is True


def test_ensure_admin(monkeypatch):
    monkeypatch.setattr(security, "is_admin", lambda: True)
    assert security.ensure_admin() is True

